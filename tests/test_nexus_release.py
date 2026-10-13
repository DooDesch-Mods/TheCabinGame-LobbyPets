"""Exercise accepted-release dependency capture, upload binding and readback over HTTP."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import nexus_release as release
import nexus_api as draft
import release as github_release


class NexusReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=TOOLS.parent / "tests")
        assert Path(self.temporary.name).resolve().is_relative_to((TOOLS.parent / "tests").resolve())
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "dist").mkdir()
        self.archive = self.root / f"dist/{release.package.MOD}-0.1.0.zip"
        self.archive.write_bytes(b"accepted release archive fixture")
        for target, name, value in [(release, "ROOT", self.root), (release, "RECEIPT", self.root / "dist/nexus-release.json"),
                (release.package, "ROOT", self.root), (release.package, "MOD", release.package.MOD), (release.package, "VERSION", "0.1.0")]:
            scope = patch.object(target, name, value)
            scope.start()
            self.addCleanup(scope.stop)
        scope = patch.dict(os.environ, {"NEXUS_MOD_ID": "100", "NEXUS_FILE_GROUP_ID": "200",
            "NEXUSMODS_API_KEY": "fixture-secret", "NEXUS_VERSION_ID": "301"}, clear=True)
        scope.start()
        self.addCleanup(scope.stop)
        acceptance = patch.object(release.package, "require_acceptance")
        self.acceptance = acceptance.start()
        self.addCleanup(acceptance.stop)
        package_check = patch.object(release.package, "verify")
        self.package_check = package_check.start()
        self.addCleanup(package_check.stop)
        self.parent_status = "not_published"
        self.files = [{"id": "200", "name": "Main"}]
        self.versions = [{"id": "299", "file": {"id": "200"}, "category": "main", "position": "1", "version": "old"},
            {"id": "300", "file": {"id": "200"}, "category": "main", "position": "2", "version": "0.1.0-ready.abc"}]
        self.definition = {"ranges": [{"target_mod_file": {"id": "400"},
            "min_version": {"id": "500", "file": {"id": "400"}},
            "max_version": {"id": "501", "file": {"id": "400"}}}]}
        self.dependencies = {"299": [], "300": [copy.deepcopy(self.definition)], "301": []}
        self.calls = []
        self.ignore_put = False
        opened = patch.object(draft.urllib.request, "urlopen", side_effect=self.http)
        self.opened = opened.start()
        self.addCleanup(opened.stop)

    def http(self, request, timeout):
        method = request.get_method()
        path = request.full_url.removeprefix(draft.BASE)
        payload = json.loads(request.data) if request.data is not None else None
        self.calls.append((method, path, payload))
        if path == "/mods/batch":
            self.assertEqual(payload, {"mod_ids": ["100"]})
            data = {"data": {"mods": [{"id": "100", "game_id": "10562", "status": self.parent_status}]}}
        elif path == "/mods/100/files":
            data = {"data": {"mod_files": self.files}}
        elif path == "/mod-files/200/versions":
            data = {"data": {"versions": self.versions}}
        elif path.endswith("/dependencies/dlc"):
            data = {"dlc_dependency_definitions": []}
        elif path.endswith("/dependencies/ranges"):
            version = path.split("/")[2]
            if method == "PUT":
                self.assertEqual(version, "301")
                self.assertEqual(payload, {"dependency_definitions": [{"ranges": [{"min_version_id": "500", "max_version_id": "501"}]}]})
                if not self.ignore_put:
                    self.dependencies[version] = [copy.deepcopy(self.definition)]
                data = None
            else:
                data = {"dependency_definitions": self.dependencies[version]}
        else:
            self.fail(f"unexpected HTTP operation: {method} {path}")
        response = MagicMock()
        response.status = 204 if data is None else 200
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = b"" if data is None else json.dumps(data).encode()
        response.__enter__.return_value = response
        return response

    def upload(self):
        self.versions[1]["category"] = "archived"
        self.versions.append({"id": "301", "file": {"id": "200"}, "category": "main", "position": "3", "version": "0.1.0"})

    def prepare(self):
        result = release.preflight(self.archive, "0.1.0")
        self.assertEqual(result["previous_version_id"], "300")
        self.assertFalse(result["requirements_confirmed"])
        self.upload()
        return result

    def test_latest_main_ranges_are_copied_to_acknowledged_release_and_read_back(self):
        self.prepare()
        result = release.verify()
        self.assertTrue(result["accepted"] and result["requirements_confirmed"] and result["parent_identity_confirmed"])
        self.assertEqual(result["confirmed_version_id"], "301")
        self.assertFalse(result["remote_archive_sha256_confirmed"])
        self.assertEqual(sum(method == "PUT" for method, _, _ in self.calls), 1)
        release.verify()
        self.assertEqual(sum(method == "PUT" for method, _, _ in self.calls), 1, "confirmed readback must not replay PUT")
        self.package_check.assert_called_with(self.archive, candidate=False)
        self.assertNotIn("fixture-secret", release.RECEIPT.read_text())

    def test_published_release_parent_is_allowed(self):
        self.parent_status = "published"
        self.prepare()
        self.assertEqual(release.verify()["status"], "published")

    def test_missing_ack_foreign_file_wrong_version_and_category_block_before_put(self):
        self.prepare()
        original = copy.deepcopy(self.versions[-1])
        for change, reason in [({"file": {"id": "999"}}, "another file group"), ({"version": "other"}, "version/file/category"),
                ({"category": "optional"}, "version/file/category")]:
            self.versions[-1] = dict(original, **change)
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, reason):
                release.verify()
        self.versions[-1] = original
        for ack in ("", "300", "999"):
            with patch.dict(os.environ, {"NEXUS_VERSION_ID": ack}), self.assertRaises(ValueError):
                release.verify()
        self.assertFalse(any(method == "PUT" for method, _, _ in self.calls))

    def test_changed_identity_zip_parent_or_source_requirements_block_before_put(self):
        self.prepare()
        self.parent_status = "hidden"
        with self.assertRaisesRegex(ValueError, "published or not_published"):
            release.verify()
        self.parent_status = "not_published"
        with patch.dict(os.environ, {"NEXUS_MOD_ID": "101"}), self.assertRaisesRegex(ValueError, "identity changed"):
            release.verify()
        self.archive.write_bytes(b"changed bytes")
        with self.assertRaisesRegex(ValueError, "ZIP changed"):
            release.verify()
        self.archive.write_bytes(b"accepted release archive fixture")
        self.dependencies["300"][0]["ranges"][0]["min_version"]["id"] = "502"
        with self.assertRaisesRegex(ValueError, "requirements changed"):
            release.verify()
        self.assertFalse(any(method == "PUT" for method, _, _ in self.calls))

    def test_bad_readback_retains_attempt_and_original_api_failure_is_redacted(self):
        self.prepare()
        self.ignore_put = True
        with self.assertRaisesRegex(ValueError, "requirements are missing"):
            release.verify()
        receipt = json.loads(release.RECEIPT.read_text())
        self.assertTrue(receipt["requirements_copy_attempted"])
        self.assertFalse(receipt["requirements_confirmed"])
        cause = draft.urllib.error.HTTPError(draft.BASE + "/mods/batch", 403, "Forbidden", {},
            io.BytesIO(b'{"detail":"denied fixture-secret"}'))
        with patch.object(draft.urllib.request, "urlopen", side_effect=cause), self.assertRaisesRegex(RuntimeError, "Nexus POST /mods/batch: HTTP 403; denied") as caught:
            release.verify()
        self.assertNotIn("fixture-secret", str(caught.exception))
        self.assertIs(caught.exception.__cause__, cause)

    def test_preflight_requires_acceptance_exact_group_and_no_version_overwrite(self):
        self.acceptance.side_effect = ValueError("game acceptance is pending")
        with self.assertRaisesRegex(ValueError, "acceptance is pending"):
            release.preflight(self.archive, "0.1.0")
        self.assertEqual(self.calls, [])
        self.acceptance.side_effect = None
        self.files = [{"id": "999"}]
        with self.assertRaisesRegex(ValueError, "does not belong"):
            release.preflight(self.archive, "0.1.0")
        self.files = [{"id": "200"}]
        self.versions[-1]["version"] = "0.1.0"
        with self.assertRaisesRegex(ValueError, "no automatic overwrite"):
            release.preflight(self.archive, "0.1.0")
        self.assertFalse(release.RECEIPT.exists())

    def test_release_runner_blocks_github_mutation_before_invalid_nexus_target(self):
        self.files = [{"id": "999"}]
        with patch.dict(os.environ, {"PUBLISH_NEXUS": "true"}), patch.object(github_release, "run") as command:
            with self.assertRaisesRegex(ValueError, "does not belong"):
                github_release.main()
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
