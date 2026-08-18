#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from ai_music_pipeline.assets import archive_and_cleanup


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify, archive, then remove a song temp directory")
    parser.add_argument("--temp-dir", type=Path, required=True)
    parser.add_argument("--resource-dir", type=Path, required=True)
    parser.add_argument("files", nargs="+", help="Files inside temp-dir to archive")
    args = parser.parse_args()
    archive_and_cleanup(args.temp_dir, args.resource_dir, args.files)
    print(f"Archived {len(args.files)} files to {args.resource_dir} and removed {args.temp_dir}")


if __name__ == "__main__":
    main()

