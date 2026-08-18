from __future__ import annotations

import hashlib
import os
import shutil
import uuid
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


def _safe_member(root: Path, name: str) -> Path:
    candidate = (root / name).resolve()
    root = root.resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Asset path escapes its directory: {name}")
    return candidate


def archive_and_cleanup(temp_dir: Path, resource_dir: Path, files: list[str]) -> None:
    if not temp_dir.is_dir():
        raise FileNotFoundError(temp_dir)
    temp_dir = temp_dir.resolve()
    resource_dir = resource_dir.resolve()
    if temp_dir == resource_dir:
        raise ValueError("Temporary and resource directories must be different")

    staging = resource_dir.parent / f".{resource_dir.name}.staging-{uuid.uuid4().hex}"
    try:
        for name in files:
            source = _safe_member(temp_dir, name)
            destination = staging / name
            _safe_member(staging, name)
            copy_verified(source, destination)

        # Only expose files after every source has been copied and verified.
        for name in files:
            staged = _safe_member(staging, name)
            destination = _safe_member(resource_dir, name)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, destination)
        shutil.rmtree(temp_dir)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
