#!/usr/bin/env python3
"""Classify resource-library songs by listening/use scenario."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from ai_music_pipeline.classification import classify_manifest
from ai_music_pipeline.locks import PipelineLock
from ai_music_pipeline.manifest import load_manifest, save_manifest
from scripts.reconcile_reviews import parse_records


def _list_records(cli: str, base_token: str, table_id: str) -> dict[str, str]:
    command = [
        cli,
        "base",
        "+record-list",
        "--as",
        "user",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--format",
        "json",
        "--limit",
        "200",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    return {
        str(record.fields.get("歌曲ID")): record.record_id
        for record in parse_records(payload)
        if record.fields.get("歌曲ID")
    }


def _sync_record(cli: str, base_token: str, table_id: str, record_id: str, scenes: list[str], direction: str) -> None:
    fields: dict[str, Any] = {"使用场景": scenes}
    if direction:
        fields["音乐方向"] = [direction]
    command = [
        cli,
        "base",
        "+record-upsert",
        "--as",
        "user",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--record-id",
        record_id,
        "--json",
        json.dumps(fields, ensure_ascii=False),
    ]
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify resource-library songs by usage scene")
    parser.add_argument("--resource-root", type=Path, default=Path("resource_library"))
    parser.add_argument("--song-dir", type=Path, action="append")
    parser.add_argument("--base-token", default=os.getenv("FEISHU_BASE_TOKEN"))
    parser.add_argument("--table-id", default=os.getenv("FEISHU_MUSIC_TABLE_ID", "tblISTSXQok9Cc48"))
    parser.add_argument("--cli", default="lark-cli")
    parser.add_argument("--sync-feishu", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--lock-file", type=Path, default=Path(".ai_music_pipeline.lock"))
    args = parser.parse_args()
    if args.sync_feishu and not args.base_token:
        raise SystemExit("FEISHU_BASE_TOKEN or --base-token is required with --sync-feishu")

    songs = args.song_dir or sorted(path.parent for path in args.resource_root.glob("*/manifest.json"))

    def run() -> None:
        records = _list_records(args.cli, args.base_token, args.table_id) if args.sync_feishu else {}
        for song_dir in songs:
            manifest_path = song_dir / "manifest.json"
            manifest = load_manifest(manifest_path)
            scenes = classify_manifest(manifest)
            direction = str(manifest.get("music_direction") or "")
            print(f"{manifest.get('song_id', song_dir.name)}: {', '.join(scenes)}")
            if not args.apply:
                continue
            manifest["usage_scenes"] = scenes
            save_manifest(manifest_path, manifest)
            if args.sync_feishu:
                record_id = records.get(str(manifest.get("song_id")))
                if record_id:
                    _sync_record(args.cli, args.base_token or "", args.table_id, record_id, scenes, direction)

    with PipelineLock(args.lock_file):
        run()


if __name__ == "__main__":
    main()
