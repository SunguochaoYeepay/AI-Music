from __future__ import annotations

import os
import shutil
import time
from pathlib import Path


class PipelineLock:
    """Cross-platform directory lock for one local pipeline run."""

    def __init__(self, path: Path, stale_after_seconds: int = 3 * 60 * 60) -> None:
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self.acquired = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.mkdir()
        except FileExistsError:
            age = time.time() - self.path.stat().st_mtime
            if age <= self.stale_after_seconds:
                owner = self.path / "owner"
                detail = owner.read_text(encoding="utf-8") if owner.is_file() else "unknown owner"
                raise RuntimeError(f"Another pipeline run holds {self.path}: {detail}")
            shutil.rmtree(self.path)
            self.path.mkdir()
        (self.path / "owner").write_text(f"pid={os.getpid()}\n", encoding="utf-8")
        self.acquired = True

    def release(self) -> None:
        if self.acquired:
            shutil.rmtree(self.path, ignore_errors=True)
            self.acquired = False

    def __enter__(self) -> "PipelineLock":
        self.acquire()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()
