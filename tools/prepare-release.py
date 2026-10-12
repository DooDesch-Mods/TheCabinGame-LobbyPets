"""Validate an existing GitHub release and resolve its explicit Nexus upload target."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nexus_release

def resolve_tag(event_tag, input_tag):
    tag = input_tag or event_tag
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError(f"invalid release tag: {tag!r}")
    return tag

def nexus_target(event, requested, file_id, key):
    if event != "release" and not requested:
        return False, "manual run did not request a Nexus upload"
    missing = [name for name, value in [("NEXUS_FILE_GROUP_ID", file_id), ("NEXUSMODS_API_KEY", key)] if not value]
    if missing:
        message = "missing " + ", ".join(missing)
        if event == "release":
            return False, message
        raise ValueError(f"Nexus upload requested but {message}")
    if not re.fullmatch(r"[0-9]+", file_id):
        raise ValueError("NEXUS_FILE_GROUP_ID must be the numeric API File ID")
    return True, "Nexus upload configured"

def lookup_mod_id(file_id, key, mod_id):
    if not mod_id.isdecimal():
        raise ValueError("NEXUS_MOD_ID must be the numeric Unique Mod ID")
    request = urllib.request.Request("https://api.nexusmods.com/v3/mods/" + mod_id + "/files", headers={"apikey": key, "accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        files = json.load(response)["data"]["mod_files"]
    if not any(str(file["id"]) == file_id for file in files):
        raise ValueError(f"Nexus file {file_id} does not belong to mod {mod_id}")
    return mod_id

def run():
    tag = resolve_tag(os.environ.get("RELEASE_TAG", ""), os.environ.get("INPUT_TAG", ""))
    version = tag[1:]
    source = Path(os.environ.get("RELEASE_SOURCE", ".")).resolve()
    verify = source / "tools/verify.py"
    subprocess.run([sys.executable, str(verify), "--version", version, "--committed"], cwd=source, check=True)
    destination = Path("release-download").resolve()
    destination.mkdir(exist_ok=True)
    asset = f"CabinLobbyPets-{version}.zip"
    subprocess.run(["gh", "release", "download", tag, "--repo", os.environ["GITHUB_REPOSITORY"], "--pattern", asset, "--pattern", "SHA256SUMS.txt", "--dir", str(destination)], check=True)
    subprocess.run([sys.executable, str(verify), "--version", version, "--committed", "--archive", str(destination / asset)], cwd=source, check=True)
    ready, reason = nexus_target(os.environ["GITHUB_EVENT_NAME"], os.environ.get("PUBLISH_NEXUS") == "true", os.environ.get("NEXUS_FILE_GROUP_ID", ""), os.environ.get("NEXUSMODS_API_KEY", ""))
    section = (source / "CHANGELOG.md").read_text(encoding="utf-8").split(f"## {version} - ", 1)[1].split("\n", 1)[1].split("\n## ", 1)[0].strip()
    notes = "[list]\n" + "\n".join("[*]" + line[2:] for line in section.splitlines() if line.startswith("- ")) + "\n[/list]"
    mod_id = ""
    file_id = os.environ.get("NEXUS_FILE_GROUP_ID", "")
    key = os.environ.get("NEXUSMODS_API_KEY", "")
    lookup = "not attempted: Nexus upload was not requested or configured"
    receipt_path = destination / "nexus-release.json"
    contract_ready = False
    if ready:
        identity = nexus_release.identity_from_environment()
        receipt = nexus_release.preflight(identity, destination / asset, version, receipt_path)
        contract_ready = True
        ready = receipt["upload_required"]
        mod_id = identity["uid"]
        lookup = f"confirmed: file group {identity['file']} belongs to Nexus mod {mod_id}; requirements pinned"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"receipt={receipt_path}\nnexus_contract_ready={str(contract_ready).lower()}\nversion={version}\nasset={destination / asset}\nnexus_ready={str(ready).lower()}\nmod_id={mod_id}\nnotes<<PETS_CHANGELOG\n{notes}\nPETS_CHANGELOG\n")
    print(f"info: {reason}; verified GitHub release {tag}")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write(f"Verified {tag}: ZIP integrity, source bytes, checksum, installation boundaries.\n\nNexus: {reason}.\n\nTarget lookup: {lookup}.\n")

if __name__ == "__main__":
    try:
        run()
    except Exception as error:
        raise SystemExit(f"error: release preparation failed: {error}") from error
