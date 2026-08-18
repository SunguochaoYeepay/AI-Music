#!/usr/bin/env python3
"""Register a distributor submission in Feishu and the local resource library."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from ai_music_pipeline.locks import PipelineLock
from ai_music_pipeline.release_registration import (
    RELEASE_FIELD_DEFINITIONS,
    build_track_fields,
    ensure_release_fields,
    list_field_names,
    list_release_record_ids,
    load_registration,
    resolve_base_token,
    sync_feishu_records,
    update_local_release,
)


def _load_config(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync one distributor release to Feishu and local manifests")
    parser.add_argument("--release-file", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--base-url", default=os.getenv("FEISHU_BASE_URL"))
    parser.add_argument("--base-token", default=os.getenv("FEISHU_BASE_TOKEN"))
    parser.add_argument("--table-id", default=os.getenv("FEISHU_RELEASE_TABLE_ID"))
    parser.add_argument("--cli", default="lark-cli")
    parser.add_argument("--resource-root", type=Path, default=Path("resource_library"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--lock-file", type=Path, default=Path(".ai_music_pipeline.lock"))
    parser.add_argument("--no-lock", action="store_true")
    args = parser.parse_args()

    config = _load_config(args.config)
    feishu = config.get("feishu", {}) if isinstance(config.get("feishu", {}), dict) else {}
    base_url = args.base_url or feishu.get("base_url")
    base_token = args.base_token or feishu.get("base_token")
    table_id = args.table_id or feishu.get("release_table_id")
    cli = str(feishu.get("cli") or args.cli)
    resource_root = Path(config.get("resource_library") or args.resource_root)
    if not table_id:
        raise SystemExit("Set --table-id, FEISHU_RELEASE_TABLE_ID, or feishu.release_table_id in config.json")
    if not base_token and not base_url:
        raise SystemExit("Set --base-url/--base-token or configure feishu.base_url/base_token")

    def run() -> None:
        registration = load_registration(args.release_file)
        token = str(base_token or resolve_base_token(cli, str(base_url)))
        fields = list_field_names(cli, token, str(table_id))
        missing_fields = [
            str(definition["name"])
            for definition in RELEASE_FIELD_DEFINITIONS
            if definition["name"] not in fields
        ]
        required_existing = {"歌曲ID", "发布标题", "发布状态", "AI标注", "MiniMax-Music3署名"}
        absent_core = sorted(required_existing - fields)
        if absent_core:
            raise RuntimeError(f"Release table is missing core fields: {', '.join(absent_core)}")

        track_fields = [
            build_track_fields(registration, track, resource_root) for track in registration.tracks
        ]
        existing_records = list_release_record_ids(cli, token, str(table_id))
        for item in track_fields:
            action = "UPDATE" if item["歌曲ID"] in existing_records else "CREATE"
            print(f"{action} {item['歌曲ID']}: {item['ISRC']} / {registration.distributor_status}")
        if missing_fields:
            print(f"CREATE FIELDS: {', '.join(missing_fields)}")
        if not args.apply:
            print("DRY-RUN: no Feishu or local files were changed; pass --apply to execute.")
            return

        ensure_release_fields(cli, token, str(table_id), fields)
        synced = sync_feishu_records(
            cli=cli,
            base_token=token,
            table_id=str(table_id),
            records_by_song_id=existing_records,
            track_fields=track_fields,
        )
        for track in registration.tracks:
            update_local_release(registration, track, resource_root, synced[track.song_id])
        print(f"SYNCED {len(synced)} tracks to Feishu and local release metadata")

    if args.no_lock:
        run()
    else:
        with PipelineLock(args.lock_file):
            run()


if __name__ == "__main__":
    main()
