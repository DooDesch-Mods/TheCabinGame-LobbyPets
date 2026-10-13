import json
import os
import urllib.error
import urllib.request

BASE = 'https://api.nexusmods.com/v3'

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

