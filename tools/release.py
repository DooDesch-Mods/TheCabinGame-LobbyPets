"""Publish verified release bytes and resolve an explicit existing Nexus target."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import package
import nexus_release
import release_notes


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"{' '.join(args[:3])} failed ({result.returncode}): {result.stderr.strip()}")
    return result.stdout


def require_tag_target(repository, tag, commit):
    refs = json.loads(run("gh", "api", f"repos/{repository}/git/matching-refs/tags/{tag}"))
    if any(ref["ref"] == "refs/tags/" + tag for ref in refs):
        actual = json.loads(run("gh", "api", f"repos/{repository}/commits/{tag}"))["sha"]
        if actual != commit:
            raise ValueError(f"existing tag {tag} targets {actual}, expected {commit}; release blocked")


def main():
    package.require_acceptance()
    release_body = release_notes.body(package.VERSION)
    nexus_notes = release_notes.nexus(package.VERSION)
    archive = package.ROOT / "dist" / f"{package.MOD}-{package.VERSION}.zip"
    package.verify(archive, candidate=False)
    nexus = os.environ.get("PUBLISH_NEXUS") == "true"
    if nexus:
        file_id = os.environ.get("NEXUS_FILE_GROUP_ID", "")
        mod_id = os.environ.get("NEXUS_MOD_ID", "")
        key = os.environ.get("NEXUSMODS_API_KEY", "")
        if not file_id.isdecimal() or not mod_id.isdecimal() or not key:
            raise ValueError("Nexus upload requested but numeric target IDs or organization secret are missing")
        nexus_release.preflight(archive, package.VERSION)
        print(f"info: confirmed Nexus target mod={mod_id} file_group={file_id}")
    else:
        print("info: Nexus upload not requested")
    repository = os.environ["GITHUB_REPOSITORY"]
    tag = "v" + package.VERSION
    require_tag_target(repository, tag, os.environ["GITHUB_SHA"])
    pages = json.loads(run("gh", "api", f"repos/{repository}/releases", "--paginate", "--slurp"))
    releases = [release for page in pages for release in page]
    existing = next((release for release in releases if release["tag_name"] == tag), None)
    if existing is None:
        notes = archive.parent / "release-notes.md"
        notes.write_text(release_body, encoding="utf-8")
        run("gh", "release", "create", tag, str(archive), str(archive.parent / "SHA256SUMS.txt"),
            "--repo", repository, "--target", os.environ["GITHUB_SHA"],
            "--title", f"{package.MOD} {package.VERSION}", "--notes-file", str(notes))
        print(f"info: published GitHub release {repository}/{tag}")
    elif existing["draft"] or existing["prerelease"]:
        raise ValueError(f"existing {tag} is draft/prerelease; no automatic overwrite")
    release = json.loads(run("gh", "api", f"repos/{repository}/releases/tags/{tag}"))
    target_sha = json.loads(run("gh", "api", f"repos/{repository}/commits/{tag}"))["sha"]
    if target_sha != os.environ["GITHUB_SHA"]:
        raise ValueError(f"release {tag} targets {target_sha}, expected {os.environ['GITHUB_SHA']}")
    with tempfile.TemporaryDirectory() as temporary:
        run("gh", "release", "download", tag, "--repo", repository, "--pattern", archive.name,
            "--pattern", "SHA256SUMS.txt", "--dir", temporary)
        downloaded = Path(temporary) / archive.name
        package.verify(downloaded, candidate=False)
        checksum = (Path(temporary) / "SHA256SUMS.txt").read_text().strip()
        if checksum != f"{hashlib.sha256(downloaded.read_bytes()).hexdigest()}  {archive.name}":
            raise ValueError("uploaded release checksum differs from verified ZIP")
    print(f"info: confirmed published tag, ZIP and checksum: {release['html_url']}")
    notes = nexus_notes
    if any("\n" in value for value in [package.MOD, package.VERSION, str(archive)]):
        raise ValueError("invalid multiline workflow output")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"version={package.VERSION}\nasset={archive}\ndisplay_name={package.MOD} {package.VERSION}\nnexus_ready={str(nexus).lower()}\nnotes<<NEXUS_NOTES\n{notes}\nNEXUS_NOTES\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write(f"Confirmed release: {release['html_url']}\n\nNexus upload requested: {nexus}\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"error: release {package.MOD}: {error}") from error
