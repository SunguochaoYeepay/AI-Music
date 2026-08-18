#!/usr/bin/env python3
"""Reconcile reviewed songs in the Feishu production table.

The default mode is a dry-run.  Pass ``--apply`` only from a trusted
automation or after reviewing the proposed actions.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ai_music_pipeline.assets import archive_and_cleanup
from ai_music_pipeline.manifest import load_manifest, save_manifest


APPROVED_VALUES = {"通过", "合格", "保留", "approved", "approve", "passed", "pass"}
REJECTED_VALUES = {"废弃", "淘汰", "弃用", "删除", "rejected", "reject", "discarded", "discard"}
DEFAULT_ASSETS = ("audio_master.flac", "audio_320k.mp3", "cover_1024.png", "manifest.json")


@dataclass(frozen=True)
class Record:
    record_id: str
    fields: dict[str, Any]


def _text(value: Any) -> str:
    """Convert common Feishu cell shapes to comparable display text."""
    if value is None:
        return ""
    if isinstance(value, str | int | float | bool):
        return str(value).strip()
    if isinstance(value, list):
        return ", ".join(part for part in (_text(item) for item in value) if part)
    if isinstance(value, dict):
        for key in ("text", "name", "value", "display_value"):
            if key in value:
                return _text(value[key])
        return ""
    return str(value).strip()


def _walk_records(value: Any) -> Iterable[Record]:
    if isinstance(value, dict):
        record_id = value.get("record_id") or value.get("id")
        fields = value.get("fields")
        if record_id and isinstance(fields, dict):
            yield Record(str(record_id), fields)
        for child in value.values():
            yield from _walk_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_records(child)


def parse_records(payload: Any) -> list[Record]:
    """Parse both raw API data and lark-cli JSON envelopes."""
    seen: set[str] = set()
    records: list[Record] = []
    for record in _walk_records(payload):
        if record.record_id not in seen:
            seen.add(record.record_id)
            records.append(record)
    return records


def _load_cli_json(stdout: str) -> Any:
    """Accept JSON plus harmless CLI notices printed before/after it."""
    text = stdout.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("lark-cli did not return JSON")


def list_records(cli: str, base_token: str, table_id: str, records_file: Path | None) -> list[Record]:
    if records_file:
        return parse_records(json.loads(records_file.read_text(encoding="utf-8")))
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
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return parse_records(_load_cli_json(result.stdout))


def _run_update(cli: str, base_token: str, table_id: str, record_id: str, fields: dict[str, Any]) -> None:
    if not fields:
        return
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


def _run_delete(cli: str, base_token: str, table_id: str, record_id: str) -> None:
    command = [
        cli,
        "base",
        "+record-delete",
        "--as",
        "user",
        "--base-token",
        base_token,
        "--table-id",
        table_id,
        "--record-id",
        record_id,
        "--yes",
    ]
    subprocess.run(command, check=True)


def _find_field(fields: dict[str, Any], names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in fields:
            return name
    return None


def _safe_song_id(song_id: str) -> bool:
    path = Path(song_id)
    return bool(song_id) and not path.is_absolute() and path.name == song_id and song_id not in {".", ".."}


def _asset_names(temp_dir: Path) -> list[str]:
    manifest_path = temp_dir / "manifest.json"
    if manifest_path.is_file():
        manifest = load_manifest(manifest_path)
        assets = manifest.get("assets", {})
        names = [str(value) for value in assets.values() if isinstance(value, str)]
        if "manifest.json" not in names:
            names.append("manifest.json")
        if names:
            return names
    return list(DEFAULT_ASSETS)


def _resource_is_complete(resource_dir: Path) -> bool:
    manifest_path = resource_dir / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        names = _asset_names(resource_dir)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return all((resource_dir / name).is_file() for name in names)


def _mark_manifest_approved(resource_dir: Path) -> None:
    manifest_path = resource_dir / "manifest.json"
    if not manifest_path.is_file():
        return
    manifest = load_manifest(manifest_path)
    if manifest.get("status") == "approved" and manifest.get("reviewed_at"):
        return
    manifest["status"] = "approved"
    manifest["reviewed_at"] = datetime.now(timezone.utc).isoformat()
    save_manifest(manifest_path, manifest)


def reconcile(
    records: list[Record],
    *,
    temp_root: Path,
    resource_root: Path,
    apply: bool,
    cli: str,
    base_token: str,
    table_id: str,
) -> list[str]:
    actions: list[str] = []
    for record in records:
        fields = record.fields
        song_id = _text(fields.get("歌曲ID") or fields.get("song_id") or fields.get("Song ID"))
        if not _safe_song_id(song_id):
            actions.append(f"SKIP {record.record_id}: invalid or missing 歌曲ID")
            continue

        review = _text(fields.get("审听结果") or fields.get("review_result")).casefold()
        generation = _text(fields.get("生成状态") or fields.get("generation_status")).casefold()
        temp_dir = temp_root / song_id
        resource_dir = resource_root / song_id

        if review in APPROVED_VALUES:
            if _resource_is_complete(resource_dir):
                actions.append(f"APPROVED {song_id}: resource already complete")
                if apply:
                    _mark_manifest_approved(resource_dir)
            elif not temp_dir.is_dir():
                actions.append(f"BLOCKED {song_id}: approved but temp/resource assets are missing")
                continue
            else:
                names = _asset_names(temp_dir)
                missing = [name for name in names if not (temp_dir / name).is_file()]
                if missing:
                    actions.append(f"BLOCKED {song_id}: missing {', '.join(missing)}")
                    continue
                actions.append(f"ARCHIVE {song_id}: {', '.join(names)}")
                if apply:
                    archive_and_cleanup(temp_dir, resource_dir, names)
                    _mark_manifest_approved(resource_dir)

            updates: dict[str, Any] = {}
            state_field = _find_field(fields, ("生成状态", "generation_status"))
            if state_field and _text(fields.get(state_field)) != "通过":
                updates[state_field] = "通过"
            final_field = _find_field(fields, ("最终版本", "final_version"))
            if final_field and fields.get(final_field) is not True:
                updates[final_field] = True
            path_field = _find_field(fields, ("资源库路径", "本地资源路径", "resource_path"))
            if path_field:
                updates[path_field] = str(resource_dir)
            if updates:
                actions.append(f"UPDATE {song_id}: {', '.join(updates)}")
                if apply:
                    _run_update(cli, base_token, table_id, record.record_id, updates)
            continue

        if review in REJECTED_VALUES or generation in REJECTED_VALUES:
            actions.append(f"DELETE {song_id}: review={review or '-'} generation={generation or '-'}")
            if apply:
                if temp_dir.is_dir():
                    # The path is constructed from a single ID below the configured temp root.
                    temp_dir.resolve().relative_to(temp_root.resolve())
                    import shutil

                    shutil.rmtree(temp_dir)
                _run_delete(cli, base_token, table_id, record.record_id)
            continue

        actions.append(f"WAIT {song_id}: review={review or '-'} generation={generation or '-'}")
    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive approved songs and delete rejected review rows")
    parser.add_argument("--base-token", default=os.getenv("FEISHU_BASE_TOKEN"))
    parser.add_argument("--table-id", default=os.getenv("FEISHU_MUSIC_TABLE_ID", "tblISTSXQok9Cc48"))
    parser.add_argument("--cli", default="lark-cli")
    parser.add_argument("--temp-root", type=Path, default=Path("temp"))
    parser.add_argument("--resource-root", type=Path, default=Path("resource_library"))
    parser.add_argument("--records-file", type=Path, help="Local CLI JSON fixture for testing")
    parser.add_argument("--apply", action="store_true", help="Perform archive/update/delete actions")
    args = parser.parse_args()
    if not args.records_file and not args.base_token:
        raise SystemExit("FEISHU_BASE_TOKEN or --base-token is required")

    records = list_records(args.cli, args.base_token or "", args.table_id, args.records_file)
    actions = reconcile(
        records,
        temp_root=args.temp_root,
        resource_root=args.resource_root,
        apply=args.apply,
        cli=args.cli,
        base_token=args.base_token or "",
        table_id=args.table_id,
    )
    print("\n".join(actions) if actions else "No review records found")
    if not args.apply:
        print("DRY-RUN: no local files or Feishu records were changed; pass --apply to execute.")


if __name__ == "__main__":
    main()
