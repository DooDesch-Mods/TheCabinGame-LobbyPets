"""Check release routing without credentials, network calls or publication."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location("release", Path(__file__).resolve().parents[1] / "tools/prepare-release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

class ReleaseRouting(unittest.TestCase):
    def test_event_and_manual_tags(self):
        self.assertEqual(release.resolve_tag("v0.1.0", ""), "v0.1.0")
        self.assertEqual(release.resolve_tag("", "v0.1.1"), "v0.1.1")

    def test_invalid_tags(self):
        for tag in ["", "main", "v0.1.0; echo bad", "v0.1.0-alpha", "../v0.1.0"]:
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release.resolve_tag(tag, "")

    def test_manual_check_never_uploads(self):
        self.assertFalse(release.nexus_target("workflow_dispatch", False, "123", "present")[0])

    def test_first_release_skips_unconfigured_nexus(self):
        ready, reason = release.nexus_target("release", True, "", "present")
        self.assertFalse(ready)
        self.assertIn("NEXUS_FILE_GROUP_ID", reason)

    def test_explicit_upload_missing_configuration_fails(self):
        with self.assertRaisesRegex(ValueError, "NEXUSMODS_API_KEY"):
            release.nexus_target("workflow_dispatch", True, "123", "")

    def test_configured_release_and_manual_upload(self):
        for event in ["release", "workflow_dispatch"]:
            self.assertTrue(release.nexus_target(event, True, "123", "present")[0])

    def test_wrong_file_id_fails(self):
        with self.assertRaisesRegex(ValueError, "numeric API File ID"):
            release.nexus_target("release", True, "page-url", "present")

    def test_target_lookup_confirms_file_belongs_to_mod(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data":{"mod_files":[{"id":"8127345"}]}}'
        with patch.object(release.urllib.request, "urlopen", return_value=response) as fetch:
            self.assertEqual(release.lookup_mod_id("8127345", "test-key", "123456"), "123456")
            request = fetch.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.nexusmods.com/v3/mods/123456/files")

    def test_file_on_wrong_mod_fails(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data":{"mod_files":[{"id":"999999"}]}}'
        with patch.object(release.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(ValueError, "does not belong"):
                release.lookup_mod_id("8127345", "test-key", "123456")

    def test_invalid_mod_id_fails_before_network(self):
        with patch.object(release.urllib.request, "urlopen") as fetch:
            with self.assertRaisesRegex(ValueError, "numeric Unique Mod ID"):
                release.lookup_mod_id("8127345", "test-key", "invalid")
            fetch.assert_not_called()

if __name__ == "__main__":
    unittest.main()
