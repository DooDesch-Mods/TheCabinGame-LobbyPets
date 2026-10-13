"""Preserve existing file requirements on the acknowledged accepted release version."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path

import package
from nexus_api import api, ranges, require

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "dist/nexus-release.json"


def identity():
    result = {"uid": os.environ.get("NEXUS_MOD_ID", ""), "file": os.environ.get("NEXUS_FILE_GROUP_ID", "")}
    require(all(value.isascii() and value.isdecimal() and int(value) > 0 for value in result.values()), "release Nexus target IDs are missing or invalid")
    return result


def parent(target):
    rows = api("POST", "/mods/batch", {"mod_ids": [target["uid"]]})["mods"]
    require(len(rows) == 1 and str(rows[0].get("id")) == target["uid"], "release Nexus parent UID is unconfirmed")
    require(str(rows[0].get("game_id")) == "10562", "release Nexus game differs from The Cabin Game")
    require(rows[0].get("status") in {"published", "not_published"}, "release Nexus parent must be published or not_published")
    files = api("GET", f"/mods/{target['uid']}/files")["mod_files"]
    require(sum(str(row.get("id")) == target["file"] for row in files) == 1, "release Nexus file group does not belong to the configured mod")
    return rows[0]


def latest_main(target):
    versions = api("GET", f"/mod-files/{target['file']}/versions")["versions"]
    active = [row for row in versions if row.get("category") == "main"]
    require(bool(active), "release Nexus file has no Main version")
    require(all(str(row.get("file", {}).get("id")) == target["file"] for row in active), "release Nexus Main version belongs to another file group")
    try:
        positions = [Decimal(row["position"]) for row in active]
        require(all(value.is_finite() for value in positions), "release Nexus Main position is not finite")
        latest = [row for row, position in zip(active, positions) if position == max(positions)]
    except (InvalidOperation, KeyError, TypeError, ValueError) as cause:
        raise ValueError("release Nexus Main position is invalid") from cause
    require(len(latest) == 1, "release Nexus latest Main version is ambiguous")
    return latest[0], versions


def save(receipt):
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def read_ranges(version_id, allow_missing=False):
    definitions = api("GET", f"/mod-file-versions/{version_id}/dependencies/ranges")["dependency_definitions"]
    if allow_missing and not definitions:
        return None
    try:
        return ranges(definitions)
    except (ValueError, KeyError, TypeError) as cause:
        raise ValueError(f"release Nexus requirements version={version_id}: {cause}") from cause


def release_archive():
    package.require_acceptance()
    archive = ROOT / "dist" / f"{package.MOD}-{package.VERSION}.zip"
    package.verify(archive, candidate=False)
    return archive


def preflight(archive, version):
    require(archive.resolve() == release_archive().resolve() and version == package.VERSION, "release Nexus archive/version differs from the accepted package")
    require(not RECEIPT.exists(), "release Nexus preflight receipt already exists; inspect current state before retry")
    target = identity()
    current_parent = parent(target)
    previous, versions = latest_main(target)
    require(not any(row.get("version") == version for row in versions), "release Nexus version already exists; no automatic overwrite or upload replay")
    previous_id = str(previous.get("id", ""))
    require(previous_id.isascii() and previous_id.isdecimal() and int(previous_id) > 0, "release Nexus previous Main version ID is invalid")
    dependencies = read_ranges(previous_id)
    dlc = api("GET", f"/mod-file-versions/{previous['id']}/dependencies/dlc")["dlc_dependency_definitions"]
    require(not dlc, "release Nexus DLC dependencies need an explicit supported mapping")
    receipt = {"identity": target, "archive": str(archive), "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "version": version, "previous_version_id": str(previous["id"]), "dependencies": dependencies,
        "status": current_parent["status"], "accepted": True, "requirements_confirmed": False,
        "requirements_copy_attempted": False, "remote_archive_sha256_confirmed": False}
    save(receipt)
    print(f"info: release Nexus preflight confirmed mod={target['uid']} file_group={target['file']}; previous Main requirements captured")
    return receipt


def verify():
    target = identity()
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    require(receipt["identity"] == target, "release Nexus identity changed after preflight")
    require(receipt.get("accepted") is True and receipt["version"] == package.VERSION, "release Nexus receipt is not for the accepted current release")
    archive = release_archive()
    require(str(archive) == receipt["archive"] and hashlib.sha256(archive.read_bytes()).hexdigest() == receipt["sha256"], "release Nexus ZIP changed after preflight")
    uploaded_id = os.environ.get("NEXUS_VERSION_ID", "")
    require(uploaded_id.isascii() and uploaded_id.isdecimal() and int(uploaded_id) > 0, "release Nexus upload returned no valid version acknowledgement; inspect Nexus before retry")
    require(uploaded_id != receipt["previous_version_id"], "release Nexus acknowledgement names the previous version")
    parent(target)
    latest, versions = latest_main(target)
    matches = [row for row in versions if str(row.get("id")) == uploaded_id]
    require(len(matches) == 1, "release Nexus acknowledged version is unconfirmed")
    uploaded = matches[0]
    require(uploaded.get("version") == receipt["version"] and uploaded.get("category") == "main"
        and str(uploaded.get("file", {}).get("id")) == target["file"], "release Nexus acknowledged version/file/category differs")
    require(str(latest["id"]) == uploaded_id, "release Nexus acknowledgement is not the latest Main version")
    source = read_ranges(receipt["previous_version_id"])
    require(source == receipt["dependencies"], "release Nexus previous requirements changed after preflight")
    path = f"/mod-file-versions/{uploaded_id}/dependencies/ranges"
    actual = read_ranges(uploaded_id, allow_missing=True)
    if receipt["requirements_confirmed"]:
        require(str(receipt["confirmed_version_id"]) == uploaded_id and actual == receipt["dependencies"], "release Nexus confirmed requirements/version changed; no automatic overwrite")
    elif actual != receipt["dependencies"]:
        receipt["requirements_copy_attempted"] = True
        save(receipt)
        api("PUT", path, receipt["dependencies"])
        actual = read_ranges(uploaded_id)
    require(actual == receipt["dependencies"], "release Nexus file-to-file requirements readback differs")
    current_parent = parent(target)
    receipt.update({"confirmed_version_id": uploaded_id, "requirements_confirmed": True,
        "parent_identity_confirmed": True, "status": current_parent["status"]})
    save(receipt)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"Nexus confirmed release version ID: {uploaded_id}; file-to-file requirements preserved.\nLocal release ZIP SHA256: {receipt['sha256']}\n")
    print(f"info: release Nexus version={uploaded_id} confirmed; file-to-file requirements read back")
    return receipt


if __name__ == "__main__":
    try:
        verify()
    except Exception as cause:
        raise SystemExit(f"error: release Nexus verification: {cause}") from cause
