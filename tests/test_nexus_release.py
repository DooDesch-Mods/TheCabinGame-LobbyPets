"""Exercise release Nexus contracts without keys or external effects."""
import copy
import importlib.util
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("nexus_release", Path(__file__).resolve().parents[1] / "tools/nexus_release.py")
draft = importlib.util.module_from_spec(spec)
spec.loader.exec_module(draft)

class ApiResponseTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(draft.os.environ, {"NEXUSMODS_API_KEY": "fixture-secret"}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def reply(self, method, path, body, status=200, payload=None):
        response = MagicMock()
        response.status = status
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = body
        response.__enter__.return_value = response
        with patch.object(draft.urllib.request, "urlopen", return_value=response) as opened:
            result = draft.api(method, path, payload)
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), method)
        self.assertEqual(request.full_url, draft.BASE + path)
        if payload is not None:
            self.assertEqual(json.loads(request.data), payload)
        return result

    def test_standard_data_envelopes_are_unwrapped(self):
        for method, path, data in [
            ("POST", "/mods/batch", {"mods": []}),
            ("GET", "/games/thecabingame/mods/6", {"id": "45363444580358", "game_id": "10562", "game_scoped_id": "6"}),
            ("GET", "/mods/45363444580358/files", {"mod_files": []}),
            ("GET", "/mod-files/8138724/versions", {"versions": []}),
        ]:
            with self.subTest(path=path):
                payload = {"mod_ids": ["45363444580358"]} if method == "POST" else None
                self.assertEqual(self.reply(method, path, json.dumps({"data": data}).encode(), payload=payload), data)

    def test_standard_dependency_responses_are_flat(self):
        for suffix, field in [("ranges", "dependency_definitions"), ("dlc", "dlc_dependency_definitions")]:
            with self.subTest(suffix=suffix):
                data = {field: []}
                self.assertEqual(self.reply("GET", "/mod-file-versions/123/dependencies/" + suffix, json.dumps(data).encode()), data)

    def test_204_update_has_no_json_body(self):
        self.assertIsNone(self.reply("PUT", "/mod-file-versions/123/dependencies/ranges", b"", 204, {"dependency_definitions": []}))

    def test_missing_data_and_error_data_do_not_become_success(self):
        for body, reason in [({"mods": []}, "missing or invalid data object"), ({"errorData": {"detail": "fixture-secret"}}, "errorData response")]:
            with self.subTest(reason=reason), self.assertRaisesRegex(RuntimeError, "Nexus POST /mods/batch: " + reason) as caught:
                self.reply("POST", "/mods/batch", json.dumps(body).encode())
            self.assertNotIn("fixture-secret", str(caught.exception))
            self.assertIn("HTTP 200", str(caught.exception))
            self.assertIn("Content-Type=application/json", str(caught.exception))
            self.assertIn("fields=" + json.dumps(sorted(body)), str(caught.exception))

    def test_required_response_array_is_checked_before_caller_access(self):
        for body in [{"data": {}}, {"data": {"mods": None}}, {"data": {"mods": {}}}]:
            with self.subTest(body=body), self.assertRaisesRegex(RuntimeError, "Nexus POST /mods/batch: missing or invalid mods array"):
                self.reply("POST", "/mods/batch", json.dumps(body).encode())
        with self.assertRaisesRegex(RuntimeError, "missing or invalid dependency_definitions array"):
            self.reply("GET", "/mod-file-versions/123/dependencies/ranges", b'{"data": {"dependency_definitions": []}}')

    def test_empty_200_and_invalid_json_remain_visible(self):
        for body, reason in [(b"", "empty response"), (b"{", "invalid response JSON"), (b"[]", "response is not a JSON object")]:
            with self.subTest(reason=reason), self.assertRaisesRegex(RuntimeError, "Nexus POST /mods/batch: " + reason):
                self.reply("POST", "/mods/batch", body)

    def test_problem_details_cannot_be_mistaken_for_success(self):
        problem = {"type": "https://api.nexusmods.com/problems/forbidden", "title": "Forbidden", "status": 403,
                   "detail": "access denied for fixture-secret", "instance": "/mods/batch"}
        with self.assertRaisesRegex(RuntimeError, "Nexus POST /mods/batch: API status=403; access denied") as caught:
            self.reply("POST", "/mods/batch", json.dumps(problem).encode())
        self.assertNotIn("fixture-secret", str(caught.exception))

    def test_http_problem_preserves_status_and_redacted_original_detail(self):
        problem = {"type": "https://api.nexusmods.com/problems/forbidden", "title": "Forbidden", "status": 403,
                   "detail": "access denied for fixture-secret", "instance": "/mods/batch"}
        cause = draft.urllib.error.HTTPError(draft.BASE + "/mods/batch", 403, "Forbidden", {}, io.BytesIO(json.dumps(problem).encode()))
        with patch.object(draft.urllib.request, "urlopen", side_effect=cause):
            with self.assertRaisesRegex(RuntimeError, "Nexus POST /mods/batch: HTTP 403; access denied") as caught:
                draft.api("POST", "/mods/batch")
        self.assertIs(caught.exception.__cause__, cause)
        self.assertNotIn("fixture-secret", str(caught.exception))

    def test_http_non_json_error_stays_an_http_failure(self):
        cause = draft.urllib.error.HTTPError(draft.BASE + "/mods/batch", 502, "Bad Gateway", {}, io.BytesIO(b"not-json"))
        with patch.object(draft.urllib.request, "urlopen", side_effect=cause):
            with self.assertRaisesRegex(RuntimeError, "Nexus POST /mods/batch: HTTP 502; invalid problem JSON"):
                draft.api("POST", "/mods/batch")

    def test_network_failure_preserves_operation_and_original_cause(self):
        cause = draft.urllib.error.URLError("fixture connection failure")
        with patch.object(draft.urllib.request, "urlopen", side_effect=cause):
            with self.assertRaisesRegex(RuntimeError, "Nexus POST /mods/batch: fixture connection failure") as caught:
                draft.api("POST", "/mods/batch")
        self.assertIs(caught.exception.__cause__, cause)

class PublishedReleaseTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.archive = Path(folder.name) / "release.zip"
        self.archive.write_bytes(b"source-verified fixture archive")
        self.receipt = Path(folder.name) / "nexus-release.json"
        self.identity = {"uid": str((10562 << 32) | 3), "scoped": "3", "file": "400"}
        self.previous = {"id": "500", "file": {"id": "400"}, "version": "0.1.2", "category": "main", "position": "1", "is_primary": True}
        self.current = dict(self.previous, id="501", version="0.2.0", position="2", is_primary=False)
        self.rows = [self.previous]
        self.definitions = [{"ranges": [{"target_mod_file": {"id": "600"}, "min_version": {"id": "700", "file": {"id": "600"}}, "max_version": None}]}]
        self.calls = []
        self.puts = 0
        mock = patch.object(draft, "api", side_effect=self.api)
        mock.start()
        self.addCleanup(mock.stop)

    def api(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if method == "PUT":
            self.puts += 1
            return None
        if path == "/mods/batch":
            return {"mods": [{"id": self.identity["uid"], "game_id": "10562", "status": "published"}]}
        if path.startswith("/games/"):
            return {"id": self.identity["uid"], "game_id": "10562", "game_scoped_id": "3"}
        if path.endswith("/files"):
            return {"mod_files": [{"id": "400"}]}
        if path.endswith("/versions"):
            return {"versions": self.rows}
        if path.endswith("/dependencies/ranges"):
            return {"dependency_definitions": self.definitions}
        if path.endswith("/dependencies/dlc"):
            return {"dlc_dependency_definitions": []}
        raise AssertionError((method, path))

    def prepare(self):
        return draft.preflight(self.identity, self.archive, "0.2.0", self.receipt)

    def test_preflight_is_read_only_and_pins_previous_main(self):
        receipt = self.prepare()
        self.assertTrue(receipt["upload_required"])
        self.assertEqual(receipt["previous_version_id"], "500")
        self.assertEqual(self.puts, 0)
        self.assertTrue(all(method in ("GET", "POST") and (method != "POST" or path == "/mods/batch") for method, path, _ in self.calls))

    def test_acknowledged_new_version_preserves_ranges_and_records_primary(self):
        receipt = self.prepare()
        self.rows.append(self.current)
        confirmed = draft.verify(self.identity, self.receipt, "501")
        self.assertEqual(self.puts, 1)
        self.assertIn(("PUT", "/mod-file-versions/501/dependencies/ranges", receipt["dependencies"]), self.calls)
        self.assertTrue(confirmed["requirements_confirmed"])
        self.assertTrue(confirmed["parent_published_confirmed"])
        self.assertFalse(confirmed["primary_readback"])
        self.assertTrue(confirmed["uploaded_archive_hash_unverified"])
        self.assertNotIn("downloaded_archive_sha256", confirmed)

    def test_wrong_or_missing_ack_never_mutates(self):
        self.prepare()
        self.rows.append(self.current)
        for ack in ("", "not-an-id", "500", "999"):
            with self.subTest(ack=ack), self.assertRaises(ValueError):
                draft.verify(self.identity, self.receipt, ack)
        self.assertEqual(self.puts, 0)

    def test_changed_local_archive_sha_never_mutates(self):
        self.prepare()
        self.rows.append(self.current)
        self.archive.write_bytes(b"wrong SHA")
        with self.assertRaisesRegex(ValueError, "archive SHA changed"):
            draft.verify(self.identity, self.receipt, "501")
        self.assertEqual(self.puts, 0)

    def test_existing_release_is_verified_without_second_upload_or_put(self):
        self.rows.append(self.current)
        self.assertFalse(self.prepare()["upload_required"])
        self.assertEqual(draft.verify(self.identity, self.receipt, "")["confirmed_version_id"], "501")
        self.assertEqual(self.puts, 0)

    def test_duplicate_release_rejected_before_mutation(self):
        self.rows.extend([self.current, dict(self.current, id="502", position="3")])
        with self.assertRaisesRegex(ValueError, "duplicated"):
            self.prepare()
        self.assertEqual(self.puts, 0)

    def test_duplicate_after_upload_rejected_before_put(self):
        self.prepare()
        self.rows.extend([self.current, dict(self.current, id="502", position="3")])
        with self.assertRaisesRegex(ValueError, "duplicated"):
            draft.verify(self.identity, self.receipt, "501")
        self.assertEqual(self.puts, 0)

    def test_ambiguous_previous_main_and_wrong_file_rejected(self):
        for row, reason in [(dict(self.previous, id="502"), "ambiguous"), (dict(self.previous, id="502", file={"id": "999"}), "another file")]:
            with self.subTest(reason=reason):
                self.rows = [self.previous, row]
                with self.assertRaisesRegex(ValueError, reason):
                    self.prepare()
        self.assertEqual(self.puts, 0)

    def test_incomplete_ranges_rejected_before_upload(self):
        self.definitions = [{"ranges": [{"target_mod_file": {"id": "600"}}]}]
        with self.assertRaisesRegex(ValueError, "incomplete dependency"):
            self.prepare()
        self.assertEqual(self.puts, 0)

    def test_changed_requirements_readback_fails_and_never_replays_put(self):
        self.prepare()
        self.rows.append(self.current)
        self.definitions[0]["ranges"][0]["min_version"]["id"] = "701"
        for _ in range(2):
            with self.assertRaisesRegex(ValueError, "readback differs"):
                draft.verify(self.identity, self.receipt, "501")
        self.assertEqual(self.puts, 1)
        self.assertTrue(json.loads(self.receipt.read_text())["requirements_put_attempted"])

    def test_wrong_parent_game_and_file_rejected(self):
        original = self.api
        for kind in ("game", "uid", "file", "status"):
            def bad(method, path, payload=None):
                result = copy.deepcopy(original(method, path, payload))
                if path == "/mods/batch" and kind in ("game", "uid", "status"):
                    result["mods"][0][{"game": "game_id", "uid": "id", "status": "status"}[kind]] = "wrong"
                if path.endswith("/files") and kind == "file":
                    result["mod_files"] = [{"id": "999"}]
                return result
            with self.subTest(kind=kind), patch.object(draft, "api", side_effect=bad), self.assertRaises(ValueError):
                self.prepare()
        self.assertEqual(self.puts, 0)

    def test_uid_game_derivation_is_bound_before_network(self):
        with patch.dict(draft.os.environ, {"NEXUS_MOD_ID": self.identity["uid"], "NEXUS_FILE_GROUP_ID": "400"}, clear=True):
            self.assertEqual(draft.identity_from_environment(), self.identity)
        with patch.dict(draft.os.environ, {"NEXUS_MOD_ID": "123", "NEXUS_FILE_GROUP_ID": "400"}, clear=True), self.assertRaisesRegex(ValueError, "UID game differs"):
            draft.identity_from_environment()
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
