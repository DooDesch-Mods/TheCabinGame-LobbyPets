"""Verify that target mistakes stop before external publication."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import release


class PublishTests(unittest.TestCase):
    def test_new_tag_requires_no_existing_target(self):
        with patch.object(release, "run", return_value="[]") as command:
            release.require_tag_target("org/mod", "v0.1.0", "accepted-commit")
            self.assertEqual(command.call_count, 1)

    def test_existing_tag_must_target_accepted_commit(self):
        for actual, valid in [("accepted-commit", True), ("old-commit", False)]:
            responses = [json.dumps([{"ref": "refs/tags/v0.1.0"}]), json.dumps({"sha": actual})]
            with patch.object(release, "run", side_effect=responses):
                if valid:
                    release.require_tag_target("org/mod", "v0.1.0", "accepted-commit")
                else:
                    with self.assertRaisesRegex(ValueError, "existing tag.*release blocked"):
                        release.require_tag_target("org/mod", "v0.1.0", "accepted-commit")

    def test_missing_nexus_target_blocks_before_github_mutation(self):
        with patch.object(release.package, "require_acceptance"), patch.object(release.package, "verify"), patch.object(release, "run") as command, patch.dict(os.environ, {"PUBLISH_NEXUS": "true", "NEXUS_FILE_GROUP_ID": "", "NEXUS_MOD_ID": "", "NEXUSMODS_API_KEY": ""}):
            with self.assertRaisesRegex(ValueError, "numeric target IDs"):
                release.main()
            command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
