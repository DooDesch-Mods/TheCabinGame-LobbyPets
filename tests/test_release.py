"""Check candidate compatibility and accepted-release package boundaries offline."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import package


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in package.paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((package.ROOT / name).read_bytes())
        scope = patch.object(package, "ROOT", self.root)
        scope.start()
        self.addCleanup(scope.stop)
        self.acceptance = {"accepted": False, "payload_sha256": package.fingerprint(),
            **package.CONFIG, "checks": {name: {"passed": False, "evidence": ""} for name in package.REQUIRED}}
        self.save()

    def save(self):
        (self.root / "acceptance.json").write_text(json.dumps(self.acceptance), encoding="utf-8")

    def accept_fixture(self):
        self.acceptance["accepted"] = True
        self.acceptance["checks"] = {name: {"passed": True, "evidence": "offline package fixture only"} for name in package.REQUIRED}
        self.save()

    def test_candidate_remains_reproducible_without_acceptance_or_new_members(self):
        archive = package.build()
        original = archive.read_bytes()
        self.assertEqual(package.build().read_bytes(), original)
        package.verify(archive)
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(bundle.namelist(), package.paths)
            self.assertEqual(len(bundle.namelist()), 13)
        self.assertFalse(self.acceptance["accepted"])

    def test_unaccepted_release_stops_before_any_package_write(self):
        with self.assertRaisesRegex(ValueError, "acceptance is pending"):
            package.build(candidate=False)
        self.assertFalse((self.root / "dist").exists())

    def test_exact_accepted_release_is_verified_against_source(self):
        self.accept_fixture()
        archive = package.build(candidate=False)
        package.verify(archive, candidate=False)
        source = self.root / package.paths[0]
        source.write_bytes(source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "payload mismatch"):
            package.verify(archive, candidate=False)

    def test_changed_runtime_and_missing_multiplayer_evidence_block(self):
        self.accept_fixture()
        changed = package.payload()
        changed[package.paths[1]] += b"changed"
        with self.assertRaisesRegex(ValueError, "payload mismatch"):
            package.require_acceptance(changed)
        self.acceptance["checks"]["multiplayer"]["evidence"] = ""
        self.save()
        with self.assertRaisesRegex(ValueError, "multiplayer"):
            package.require_acceptance()

    def test_wrong_baseline_and_not_applicable_do_not_bypass_release(self):
        self.accept_fixture()
        self.acceptance["game_build"] = "different"
        self.save()
        with self.assertRaisesRegex(ValueError, "baseline differs"):
            package.require_acceptance()
        self.acceptance["game_build"] = package.CONFIG["game_build"]
        self.acceptance["checks"]["multiplayer"] = {"passed": False, "status": "not_applicable", "evidence": "fixture"}
        self.save()
        with self.assertRaisesRegex(ValueError, "multiplayer"):
            package.require_acceptance()


if __name__ == "__main__":
    unittest.main()
