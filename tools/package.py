"""Build and verify the explicit, reproducible Lua mod archive."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[1]
version = "0.3.1"
ROOT = root
MOD = "CabinLobbyPets"
VERSION = version
CONFIG = {"game_build": "26187517", "ue4ss": "v3.0.1-1164-g5e627997"}
REQUIRED = {"single_mod", "settings", "gameplay", "multiplayer", "integration", "installation"}
paths = [
    'Mods/CabinLobbyPets/Scripts/main.lua',
    'Mods/CabinLobbyPets/Scripts/cabin-roaming.lua',
    'Mods/CabinLobbyPets/Scripts/pet-save.lua',
    'Mods/CabinLobbyPets/Scripts/settings.lua',
    'Mods/CabinLobbyPets/Scripts/definition.lua',
    'Mods/CabinLobbyPets/Scripts/cabin_legacy_settings.lua',
    'Mods/CabinLobbyPets/Scripts/cabin_codec.lua',
    'Mods/CabinLobbyPets/Scripts/cabin_registry.lua',
    'Mods/CabinLobbyPets/Scripts/cabin_store.lua',
    'Mods/CabinLobbyPets/Scripts/cabin_host_settings.lua',
    'Mods/CabinLobbyPets/enabled.txt',
    'Mods/CabinLobbyPets/mod-info.ini',
    'README.md',
    'LICENSE.md',
]
dist = root / "dist"

def payload():
    return {path: (ROOT / path).read_bytes() for path in paths if path.startswith("Mods/")}


def fingerprint(files=None):
    files = payload() if files is None else files
    manifest = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def require_acceptance(files=None):
    accepted = json.loads((ROOT / "acceptance.json").read_text(encoding="utf-8"))
    if accepted.get("accepted") is not True:
        raise ValueError("game acceptance is pending; release blocked")
    if accepted.get("payload_sha256") != fingerprint(files):
        raise ValueError("acceptance payload mismatch")
    if accepted.get("game_build") != CONFIG["game_build"] or accepted.get("ue4ss") != CONFIG["ue4ss"]:
        raise ValueError("accepted game/runtime baseline differs from package")
    for name in sorted(REQUIRED):
        check = accepted.get("checks", {}).get(name, {})
        if check.get("passed") is not True or not isinstance(check.get("evidence"), str) or not check["evidence"].strip():
            raise ValueError(f"missing passed acceptance with evidence: {name}")


def contents(candidate=True):
    if not candidate:
        require_acceptance()
    return {path: (ROOT / path).read_bytes() for path in paths}


def verify(archive, candidate=True):
    expected = contents(candidate)
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None or package.namelist() != paths:
            raise ValueError("ZIP integrity or file inventory mismatch")
        for name, data in expected.items():
            if package.read(name) != data:
                raise ValueError(f"archive differs from source: {name}")


def build(candidate=True):
    files = contents(candidate)
    destination = ROOT / "dist"
    destination.mkdir(exist_ok=True)
    archive = destination / f"{MOD}-{VERSION}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as package:
        for path, data in files.items():
            entry = zipfile.ZipInfo(path, (2026, 10, 11, 0, 0, 0))
            entry.create_system = 3
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            package.writestr(entry, data)
    verify(archive, candidate)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8", newline="\n")
    print(f"confirmed: {archive.name}; files={len(paths)}; sha256={digest}")
    return archive

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    try:
        if args.archive:
            verify(args.archive, candidate=not args.release)
            print(f"confirmed: source parity: {args.archive}")
        else:
            build(candidate=not args.release)
    except Exception as cause:
        raise SystemExit(f"error: package {MOD}: {cause}") from cause
