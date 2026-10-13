"""Check changelog selection and the actual announcement content boundaries."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import release_notes


class Notes(unittest.TestCase):
    def test_selects_only_requested_version(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as folder:
            path = Path(folder)
            (path / "CHANGELOG.md").write_text("# Changelog\n\n## 2.0.0 - today\n\n### Fixed\n\n- Keep quotes \" and backticks ` intact.\n\n## [1.0.0] - yesterday\n\n- Older change.\n", encoding="utf-8")
            notes = release_notes.section("2.0.0", path)
            self.assertIn("### Fixed", notes)
            self.assertIn('quotes " and backticks `', notes)
            self.assertNotIn("Older", notes)
            self.assertEqual(release_notes.section("1.0.0", path), "- Older change.")
            self.assertIn("[b]Fixed[/b]", release_notes.nexus("2.0.0", path))
            self.assertIn("[list]", release_notes.nexus("2.0.0", path))

    def test_missing_empty_and_duplicate_sections_fail(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "tests") as folder:
            path = Path(folder)
            for text in ("## 1.0.0\n", "## 2.0.0\n\n## 1.0.0\n- old", "## 2.0.0\n- a\n## 2.0.0\n- b"):
                (path / "CHANGELOG.md").write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(ValueError):
                    release_notes.section("2.0.0", path)

    def test_discord_uses_changes_without_release_body_boilerplate(self):
        spec = importlib.util.spec_from_file_location("announcement", ROOT / "tools/announce-release.py")
        announcement = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(announcement)
        release = {"draft": False, "published_at": "today", "prerelease": False, "tag_name": "v0.3.0", "html_url": "https://example.test/release", "body": "Duplicate title, support, install and build details"}
        payload = announcement.build_payload(release, "Test", "Summary", "https://example.test/support", "https://example.test/icon.png", "https://www.nexusmods.com/thecabingame/mods/6", "DooDesch-Mods/TheCabinGame-Test")
        embed = payload["embeds"][0]
        self.assertEqual(embed["description"], release_notes.section("0.3.0"))
        self.assertNotIn("Duplicate title", embed["description"])
        self.assertNotIn("Installing", embed["description"])
        self.assertEqual(len(embed["fields"]), 1)
        self.assertNotIn("Thunderstore", embed["fields"][0]["value"])


if __name__ == "__main__":
    unittest.main()
