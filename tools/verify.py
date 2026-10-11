"""Verify release contents and installation boundaries without launching the game."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

import package

def verify(archive):
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None, "ZIP integrity failed"
        assert bundle.namelist() == package.paths, "unexpected archive paths"
        assert all(entry.create_system == 3 for entry in bundle.infolist()), "non-canonical ZIP creator platform"
        for name in package.paths:
            assert bundle.read(name) == (package.root / name).read_bytes(), f"release source mismatch: {name}"
        with tempfile.TemporaryDirectory(dir=package.dist) as temporary:
            assert Path(temporary).resolve().is_relative_to(package.dist.resolve()), "fixture outside package workspace"
            loader = Path(temporary) / "ue4ss"
            mods = loader / "Mods"
            mods.mkdir(parents=True)
            shared = {mods / "mods.txt": b"OtherMod : 1\n", loader / "UE4SS-settings.ini": b"existing configuration\n"}
            for path, content in shared.items():
                path.write_bytes(content)
            for name in bundle.namelist():
                if name.startswith("Mods/"):
                    target = loader / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(bundle.read(name))
            installed = mods / "CabinLobbyPets"
            assert (installed / "enabled.txt").is_file(), "activation file missing"
            assert (installed / "Scripts/main.lua").read_bytes() == (package.root / package.paths[0]).read_bytes()
            for path in installed.rglob("*"):
                if path.is_file():
                    path.unlink()
            for path in sorted(installed.rglob("*"), reverse=True):
                if path.is_dir():
                    path.rmdir()
            installed.rmdir()
            assert all(path.read_bytes() == content for path, content in shared.items()), "shared loader configuration changed"
    print(f"confirmed: {archive.name}; source parity; install/remove preserves shared configuration")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--committed", action="store_true")
    args = parser.parse_args()
    if args.committed:
        for name in package.paths:
            source = subprocess.run(["git", "-C", str(package.root), "show", "HEAD:" + name], capture_output=True, check=True).stdout
            assert source == (package.root / name).read_bytes(), f"checkout differs from committed bytes: {name}"
    assert not args.version or args.version == package.version, f"version mismatch: expected {args.version}, source {package.version}"
    assert (package.root / "README.md").read_text(encoding="utf-8").startswith(f"# Cabin Lobby Pets - {package.version}\n")
    assert f"## {package.version} - " in (package.root / "CHANGELOG.md").read_text(encoding="utf-8"), "release changelog missing"
    subprocess.run([sys.executable, str(package.root / "tools/package.py")], check=True)
    archive = package.dist / f"CabinLobbyPets-{package.version}.zip"
    original = archive.read_bytes()
    subprocess.run([sys.executable, str(package.root / "tools/package.py")], check=True)
    assert original == archive.read_bytes(), "package builds are not reproducible"
    verify(args.archive or archive)
    if args.archive:
        checksum = args.archive.with_name("SHA256SUMS.txt").read_text(encoding="utf-8")
        assert checksum == f"{hashlib.sha256(args.archive.read_bytes()).hexdigest()}  {args.archive.name}\n", "published checksum mismatch"
