"""Preserve published Nexus requirements and confirm release version identity."""
from decimal import Decimal
from pathlib import Path
import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request

BASE = "https://api.nexusmods.com/v3"

def require(condition, message):
    if not condition:
        raise ValueError(message)

def api(method, path, payload=None):
    key = os.environ.get("NEXUSMODS_API_KEY")
    require(bool(key), "NEXUSMODS_API_KEY is missing")
    request = urllib.request.Request(BASE + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"apikey": key, "accept": "application/json", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            body = response.read()
            response_type = str(response.headers.get("Content-Type", "missing")).replace(key, "[redacted]")
            context = f"HTTP {response.status}; Content-Type={response_type}; fields=unavailable"
            if not body:
                if response.status == 204:
                    return None
                raise RuntimeError(f"error: Nexus {method} {path}: empty response; required=JSON object; {context}")
            try:
                answer = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError) as cause:
                reason = cause.msg if isinstance(cause, json.JSONDecodeError) else cause.reason
                raise RuntimeError(f"error: Nexus {method} {path}: invalid response JSON: {reason}; {context}") from cause
            if not isinstance(answer, dict):
                raise RuntimeError(f"error: Nexus {method} {path}: response is not a JSON object; {context}")
            fields = json.dumps(sorted(answer)).replace(key, "[redacted]")
            context = f"HTTP {response.status}; Content-Type={response_type}; fields={fields}"
            if all(name in answer for name in ("type", "title", "status", "detail", "instance")):
                detail = str(answer["detail"]).replace(key, "[redacted]")[:400]
                raise RuntimeError(f"error: Nexus {method} {path}: API status={answer['status']}; {detail}; {context}")
            flat = path.endswith(("/dependencies/ranges", "/dependencies/dlc"))
            data = answer if flat else answer.get("data")
            if not isinstance(data, dict):
                shape = "errorData response" if "errorData" in answer else "missing or invalid data object"
                raise RuntimeError(f"error: Nexus {method} {path}: {shape}; {context}; inspect Nexus before retry")
            field = ("dependency_definitions" if path.endswith("/dependencies/ranges") else
                     "dlc_dependency_definitions" if path.endswith("/dependencies/dlc") else
                     "mods" if path == "/mods/batch" else
                     "mod_files" if path.endswith("/files") else
                     "versions" if path.endswith("/versions") else None)
            if field and not isinstance(data.get(field), list):
                raise RuntimeError(f"error: Nexus {method} {path}: missing or invalid {field} array; {context}")
            return data
    except urllib.error.HTTPError as cause:
        try:
            problem = json.loads(cause.read())
        except (json.JSONDecodeError, UnicodeDecodeError) as decode:
            reason = decode.msg if isinstance(decode, json.JSONDecodeError) else decode.reason
            raise RuntimeError(f"error: Nexus {method} {path}: HTTP {cause.code}; invalid problem JSON: {reason}") from cause
        detail = problem.get("detail") if isinstance(problem, dict) else None
        reason = (detail if isinstance(detail, str) else str(cause.reason)).replace(key, "[redacted]")[:400]
        raise RuntimeError(f"error: Nexus {method} {path}: HTTP {cause.code}; {reason}; inspect Nexus before retry") from cause
    except urllib.error.URLError as cause:
        raise RuntimeError(f"error: Nexus {method} {path}: {cause.reason}; inspect Nexus before retry") from cause

def ranges(definitions):
    require(bool(definitions), "file-to-file requirements are missing")
    result = []
    for definition in definitions:
        values = []
        for value in definition["ranges"]:
            minimum = value["min_version"]
            maximum = value["max_version"]
            target = value["target_mod_file"]
            require(str(minimum["file"]["id"]) == str(target["id"]), "dependency minimum belongs to another file")
            if maximum:
                require(str(maximum["file"]["id"]) == str(target["id"]), "dependency maximum belongs to another file")
            values.append({"min_version_id": str(minimum["id"]), "max_version_id": str(maximum["id"]) if maximum else None})
        require(bool(values), "dependency definition has no ranges")
        result.append({"ranges": values})
    return {"dependency_definitions": result}

def identity_from_environment():
    uid = os.environ.get("NEXUS_MOD_ID", "")
    file_id = os.environ.get("NEXUS_FILE_GROUP_ID", "")
    require(uid.isdecimal() and file_id.isdecimal() and int(file_id) > 0, "Nexus UID/file group is missing or invalid")
    require(int(uid) >> 32 == 10562, "Nexus UID game differs from The Cabin Game")
    return {"uid": uid, "file": file_id, "scoped": str(int(uid) & 0xFFFFFFFF)}


def parent(identity):
    rows = api("POST", "/mods/batch", {"mod_ids": [identity["uid"]]})["mods"]
    require(len(rows) == 1, "Nexus parent lookup requires exactly one row")
    row = rows[0]
    require(str(row.get("id")) == identity["uid"] and str(row.get("game_id")) == "10562", "Nexus parent UID/game differs")
    require(row.get("status") == "published", "Nexus release parent must be published")
    details = api("GET", f"/games/thecabingame/mods/{identity['scoped']}")
    require(str(details.get("id")) == identity["uid"] and str(details.get("game_id")) == "10562" and str(details.get("game_scoped_id")) == identity["scoped"], "Nexus scoped parent identity differs")
    files = api("GET", f"/mods/{identity['uid']}/files")["mod_files"]
    require(len([row for row in files if str(row.get("id")) == identity["file"]]) == 1, "Nexus file group does not belong to configured parent")
    return row


def file_versions(identity):
    rows = api("GET", f"/mod-files/{identity['file']}/versions")["versions"]
    ids = [str(row.get("id", "")) for row in rows]
    require(all(value.isdecimal() for value in ids) and len(ids) == len(set(ids)), "Nexus version IDs are invalid or duplicated")
    require(all(str(row.get("file", {}).get("id")) == identity["file"] for row in rows), "Nexus version belongs to another file group")
    return rows


def latest_main(rows):
    active = [row for row in rows if row.get("category") == "main"]
    require(bool(active), "Nexus configured file has no Main version")
    positions = [Decimal(row["position"]) for row in active]
    require(all(value.is_finite() for value in positions), "Nexus Main position is not finite")
    newest = max(positions)
    matches = [row for row, position in zip(active, positions) if position == newest]
    require(len(matches) == 1, "Nexus previous Main version is ambiguous")
    return matches[0]


def dependencies(version_id):
    definitions = api("GET", f"/mod-file-versions/{version_id}/dependencies/ranges")["dependency_definitions"]
    try:
        payload = ranges(definitions)
    except (KeyError, TypeError) as cause:
        raise ValueError(f"Nexus version {version_id}: incomplete dependency ranges") from cause
    require(not api("GET", f"/mod-file-versions/{version_id}/dependencies/dlc")["dlc_dependency_definitions"], "Nexus DLC dependencies require an explicit supported mapping")
    return payload


def save(path, receipt):
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def preflight(identity, archive, version, receipt_path):
    require(archive.is_file(), "source-verified GitHub release archive is missing")
    parent(identity)
    rows = file_versions(identity)
    previous = latest_main(rows)
    existing = [row for row in rows if row.get("version") == version]
    require(len(existing) <= 1, "Nexus release version is duplicated; inspect before retry")
    if existing:
        require(existing[0] == previous, "Nexus release version already exists outside latest Main; inspect before retry")
    payload = dependencies(previous["id"])
    receipt = {"identity": identity, "archive": str(archive), "source_verified_archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "version": version, "previous_version_id": str(previous["id"]), "dependencies": payload,
        "upload_required": not bool(existing), "parent_status": "published", "uploaded_archive_hash_unverified": True}
    save(receipt_path, receipt)
    print(f"info: Nexus preflight mod={identity['uid']} file={identity['file']} previous={previous['id']}; upload_required={receipt['upload_required']}")
    return receipt


def verify(identity, receipt_path, uploaded_id):
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    require(receipt["identity"] == identity, "Nexus identity changed after preflight")
    archive = Path(receipt["archive"])
    require(hashlib.sha256(archive.read_bytes()).hexdigest() == receipt["source_verified_archive_sha256"], "GitHub release archive SHA changed after preflight")
    if receipt["upload_required"]:
        require(bool(uploaded_id) and uploaded_id.isdecimal(), "Nexus upload returned no valid version acknowledgement; inspect before retry")
        require(uploaded_id != receipt["previous_version_id"], "Nexus upload acknowledged previous version; inspect before retry")
    else:
        require(not uploaded_id, "Nexus acknowledgement supplied when upload was not required")
    parent(identity)
    rows = file_versions(identity)
    matches = [row for row in rows if row.get("version") == receipt["version"]]
    require(len(matches) == 1, "Nexus uploaded release version is missing or duplicated; inspect before retry")
    current = matches[0]
    require(current == latest_main(rows), "Nexus uploaded release is not latest Main")
    require(not uploaded_id or str(current["id"]) == uploaded_id, "Nexus uploaded version ID differs from acknowledgement")
    require(isinstance(current.get("is_primary", False), bool), "Nexus primary state is invalid")
    if receipt.get("requirements_put_attempted"):
        print("info: prior requirements PUT attempt retained; verify readback without replay")
    elif receipt["upload_required"]:
        parent(identity)
        receipt["requirements_put_attempted"] = True
        save(receipt_path, receipt)
        api("PUT", f"/mod-file-versions/{current['id']}/dependencies/ranges", receipt["dependencies"])
    require(dependencies(current["id"]) == receipt["dependencies"], "Nexus file-to-file requirements readback differs")
    parent(identity)
    receipt.update({"confirmed_version_id": str(current["id"]), "requirements_confirmed": True, "parent_published_confirmed": True,
        "category_confirmed": current["category"], "primary_readback": current.get("is_primary", False), "uploaded_archive_hash_unverified": True})
    save(receipt_path, receipt)
    summary = f"Nexus version {current['id']} confirmed; file-to-file requirements preserved; primary={receipt['primary_readback']}."
    print("info: " + summary)
    print("warn: uploaded_archive_hash_unverified: available v3 download is repacked; no proven original response contract")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write(summary + "\nActual Nexus ZIP SHA256 remains unverified.\n")
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["verify"])
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    verify(identity_from_environment(), args.receipt, os.environ.get("NEXUS_VERSION_ID", ""))


if __name__ == "__main__":
    try:
        main()
    except Exception as cause:
        raise SystemExit(f"error: Nexus release verification failed: {cause}; inspect before retry") from cause
