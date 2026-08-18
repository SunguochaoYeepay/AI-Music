from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_verified(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if sha256(source) != sha256(destination):
        destination.unlink(missing_ok=True)
        raise IOError(f"Checksum mismatch after copying {source}")


def archive_and_cleanup(temp_dir: Path, resource_dir: Path, files: list[str]) -> None:
    if not temp_dir.is_dir():
        raise FileNotFoundError(temp_dir)
    for name in files:
        copy_verified(temp_dir / name, resource_dir / name)
    shutil.rmtree(temp_dir)

