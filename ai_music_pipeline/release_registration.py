from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ai_music_pipeline.manifest import load_manifest, save_manifest


ISRC_PATTERN = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
ALLOWED_DISTRIBUTOR_STATUSES = {"In Review", "Approved", "Needs Changes", "Rejected"}
ALLOWED_PUBLICATION_STATUSES = {"待发布", "已发布", "发布失败", "需要修改"}

RELEASE_FIELD_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"name": "发行项目", "type": "text"},
    {"name": "艺人", "type": "text"},
    {"name": "发行商", "type": "text"},
    {
        "name": "发行商状态",
        "type": "select",
        "multiple": False,
        "options": [{"name": value} for value in ("In Review", "Approved", "Needs Changes", "Rejected")],
    },
    {"name": "ISRC", "type": "text"},
    {"name": "曲目时长（秒）", "type": "number"},
    {"name": "发行曲目数", "type": "number"},
    {"name": "发行提交时间", "type": "datetime", "style": {"format": "yyyy/MM/dd"}},
    {"name": "目标平台", "type": "text"},
    {"name": "UPC", "type": "text"},
    {"name": "发行备注", "type": "text"},
)


@dataclass(frozen=True)
class TrackRegistration:
    song_id: str
    isrc: str
    title: str | None = None
    artist: str | None = None
    tags: str = ""


@dataclass(frozen=True)
class ReleaseRegistration:
    release_title: str
    distributor: str
    distributor_status: str
    submitted_at: str
    target_platforms: tuple[str, ...]
    tracks: tuple[TrackRegistration, ...]
    upc: str = ""
    notes: str = ""
    publication_status: str = "待发布"
    published_at: str = ""
    release_link: str = ""


def _clean_isrc(value: str) -> str:
    normalized = value.replace("-", "").replace(" ", "").upper()
    if not ISRC_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid ISRC: {value!r}")
    return normalized


def _validate_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"submitted_at must use YYYY-MM-DD: {value!r}") from error
    return parsed.isoformat()


def _validate_optional_datetime(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"published_at must use YYYY-MM-DD or YYYY-MM-DD HH:MM: {value!r}") from error
    if parsed.tzinfo is None:
        return parsed.strftime("%Y-%m-%d %H:%M")
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def load_registration(path: Path) -> ReleaseRegistration:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Release registration must be a JSON object")

    release_title = str(payload.get("release_title", "")).strip()
    distributor = str(payload.get("distributor", "")).strip()
    status = str(payload.get("distributor_status", "")).strip()
    if not release_title or not distributor:
        raise ValueError("release_title and distributor are required")
    if status not in ALLOWED_DISTRIBUTOR_STATUSES:
        raise ValueError(
            f"distributor_status must be one of {sorted(ALLOWED_DISTRIBUTOR_STATUSES)}"
        )
    publication = str(payload.get("publication_status", "")).strip() or publication_status(status)
    if publication not in ALLOWED_PUBLICATION_STATUSES:
        raise ValueError(
            f"publication_status must be one of {sorted(ALLOWED_PUBLICATION_STATUSES)}"
        )

    raw_platforms = payload.get("target_platforms", [])
    if isinstance(raw_platforms, str):
        raw_platforms = [raw_platforms]
    if not isinstance(raw_platforms, list):
        raise ValueError("target_platforms must be a string or array of strings")
    platforms = tuple(str(item).strip() for item in raw_platforms if str(item).strip())
    upc = str(payload.get("upc", "")).replace(" ", "").strip()
    if upc and (not upc.isdigit() or len(upc) not in {12, 13}):
        raise ValueError("upc must contain 12 or 13 digits")
    published_at = _validate_optional_datetime(str(payload.get("published_at", "")).strip())
    release_link = str(payload.get("release_link", "")).strip()
    if release_link and not release_link.startswith(("https://", "http://")):
        raise ValueError("release_link must start with https:// or http://")
    if publication == "已发布" and (not published_at or not release_link):
        raise ValueError("published_at and release_link are required when publication_status is 已发布")

    raw_tracks = payload.get("tracks")
    if not isinstance(raw_tracks, list) or not raw_tracks:
        raise ValueError("tracks must be a non-empty array")
    tracks: list[TrackRegistration] = []
    song_ids: set[str] = set()
    isrcs: set[str] = set()
    for item in raw_tracks:
        if not isinstance(item, dict):
            raise ValueError("Each track must be a JSON object")
        song_id = str(item.get("song_id", "")).strip()
        if not song_id or Path(song_id).name != song_id or song_id in {".", ".."}:
            raise ValueError(f"Invalid song_id: {song_id!r}")
        isrc = _clean_isrc(str(item.get("isrc", "")))
        if song_id in song_ids:
            raise ValueError(f"Duplicate song_id: {song_id}")
        if isrc in isrcs:
            raise ValueError(f"Duplicate ISRC: {isrc}")
        song_ids.add(song_id)
        isrcs.add(isrc)
        tracks.append(
            TrackRegistration(
                song_id=song_id,
                isrc=isrc,
                title=str(item["title"]).strip() if item.get("title") else None,
                artist=str(item["artist"]).strip() if item.get("artist") else None,
                tags=str(item.get("tags", "")).strip(),
            )
        )

    return ReleaseRegistration(
        release_title=release_title,
        distributor=distributor,
        distributor_status=status,
        submitted_at=_validate_date(str(payload.get("submitted_at", ""))),
        target_platforms=platforms,
        tracks=tuple(tracks),
        upc=upc,
        notes=str(payload.get("notes", "")).strip(),
        publication_status=publication,
        published_at=published_at,
        release_link=release_link,
    )


def _load_cli_json(stdout: str) -> dict[str, Any]:
    text = stdout.strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("lark-cli did not return a JSON object")


def run_cli_json(command: list[str]) -> dict[str, Any]:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = _load_cli_json(result.stdout)
    if payload.get("ok") is False:
        raise RuntimeError(json.dumps(payload.get("error", payload), ensure_ascii=False))
    return payload


def resolve_base_token(cli: str, base_url: str) -> str:
    payload = run_cli_json([cli, "base", "+url-resolve", "--as", "user", "--url", base_url])
    token = payload.get("data", {}).get("base_token")
    if not token:
        raise RuntimeError("Could not resolve a Base token from the configured Feishu URL")
    return str(token)


def list_field_names(cli: str, base_token: str, table_id: str) -> set[str]:
    payload = run_cli_json(
        [
            cli,
            "base",
            "+field-list",
            "--as",
            "user",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--format",
            "json",
        ]
    )
    return {
        str(field.get("name"))
        for field in payload.get("data", {}).get("fields", [])
        if isinstance(field, dict) and field.get("name")
    }


def ensure_release_fields(
    cli: str,
    base_token: str,
    table_id: str,
    existing_fields: set[str],
) -> list[str]:
    missing = [definition for definition in RELEASE_FIELD_DEFINITIONS if definition["name"] not in existing_fields]
    if not missing:
        return []
    run_cli_json(
        [
            cli,
            "base",
            "+field-create",
            "--as",
            "user",
            "--base-token",
            base_token,
            "--table-id",
            table_id,
            "--json",
            json.dumps(missing, ensure_ascii=False),
        ]
    )
    return [str(definition["name"]) for definition in missing]


def list_release_record_ids(cli: str, base_token: str, table_id: str) -> dict[str, str]:
    payload = run_cli_json(
        [
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
            "--field-id",
            "歌曲ID",
            "--limit",
            "200",
        ]
    )
    data = payload.get("data", {})
    if data.get("has_more") is True:
        raise RuntimeError("Release table contains more than 200 records; refusing a partial idempotency check")
    rows = data.get("data", [])
    record_ids = data.get("record_id_list", [])
    result: dict[str, str] = {}
    for record_id, row in zip(record_ids, rows):
        if not isinstance(row, list) or not row:
            continue
        song_id = str(row[0]).strip()
        if not song_id:
            continue
        if song_id in result:
            raise RuntimeError(f"Duplicate 歌曲ID in release table: {song_id}")
        result[song_id] = str(record_id)
    return result


def publication_status(distributor_status: str) -> str:
    return {
        "Needs Changes": "需要修改",
        "Rejected": "发布失败",
    }.get(distributor_status, "待发布")


def build_track_fields(
    registration: ReleaseRegistration,
    track: TrackRegistration,
    resource_root: Path,
) -> dict[str, Any]:
    song_dir = resource_root / track.song_id
    manifest_path = song_dir / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = load_manifest(manifest_path)
    title = track.title or str(manifest.get("title") or track.song_id)
    artist = track.artist or str(manifest.get("artist") or "燧燧")
    duration = float(manifest.get("duration_seconds") or 0)
    if duration <= 0:
        raise ValueError(f"Missing duration_seconds in {manifest_path}")
    platforms = "、".join(registration.target_platforms)
    notes = registration.notes or (
        f"{registration.distributor} 后台状态为 {registration.distributor_status}；"
        "尚未确认各流媒体平台正式上线。"
        if registration.distributor_status == "In Review"
        else ""
    )
    fields: dict[str, Any] = {
        "歌曲ID": track.song_id,
        "发布标题": title,
        "发行项目": registration.release_title,
        "艺人": artist,
        "发行商": registration.distributor,
        "发行商状态": [registration.distributor_status],
        "ISRC": track.isrc,
        "曲目时长（秒）": duration,
        "发行曲目数": len(registration.tracks),
        "发行提交时间": f"{registration.submitted_at} 00:00",
        "目标平台": platforms,
        "UPC": registration.upc,
        "发行备注": notes,
        "发布状态": [registration.publication_status],
        "AI标注": True,
        "MiniMax-Music3署名": True,
    }
    if track.tags:
        fields["标签"] = track.tags
    if registration.published_at:
        fields["发布时间"] = registration.published_at
    if registration.release_link:
        fields["发布链接"] = registration.release_link
    return fields


def sync_feishu_records(
    *,
    cli: str,
    base_token: str,
    table_id: str,
    records_by_song_id: dict[str, str],
    track_fields: list[dict[str, Any]],
) -> dict[str, str]:
    synced: dict[str, str] = {}
    creates: list[dict[str, Any]] = []
    for fields in track_fields:
        song_id = str(fields["歌曲ID"])
        record_id = records_by_song_id.get(song_id)
        if not record_id:
            creates.append(fields)
            continue
        run_cli_json(
            [
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
        )
        synced[song_id] = record_id

    if creates:
        payload = run_cli_json(
            [
                cli,
                "base",
                "+record-batch-create",
                "--as",
                "user",
                "--base-token",
                base_token,
                "--table-id",
                table_id,
                "--json",
                json.dumps({"create_records": creates}, ensure_ascii=False),
            ]
        )
        ids = payload.get("data", {}).get("record_id_list", [])
        if len(ids) != len(creates):
            raise RuntimeError("Feishu did not return one record ID for every created track")
        for fields, record_id in zip(creates, ids):
            synced[str(fields["歌曲ID"])] = str(record_id)
    return synced


def write_release_csv(path: Path, metadata: dict[str, Any]) -> None:
    release = metadata.get("release", {})
    track = metadata.get("track", {})
    rights = metadata.get("rights", {})
    audio = metadata.get("audio", {})
    artwork = metadata.get("artwork", {})
    identifiers = metadata.get("identifiers", {})
    distribution = metadata.get("distribution", {})
    row = {
        "audio_file": audio.get("file", ""),
        "artwork_file": artwork.get("file", ""),
        "release_title": release.get("title", ""),
        "track_title": track.get("title", ""),
        "version": track.get("version", ""),
        "primary_artist": release.get("primary_artist", ""),
        "performer": track.get("performer", ""),
        "composer": track.get("composer", ""),
        "lyricist": track.get("lyricist", ""),
        "producer": track.get("producer", ""),
        "genre": release.get("genre", ""),
        "language": release.get("language", ""),
        "explicit": str(bool(release.get("explicit", False))).lower(),
        "release_date": release.get("release_date", ""),
        "copyright": rights.get("copyright", ""),
        "publisher": rights.get("publisher", ""),
        "isrc": identifiers.get("isrc", "") or "",
        "upc": identifiers.get("upc", "") or "",
        "distributor": distribution.get("distributor", ""),
        "distributor_status": distribution.get("status", ""),
        "submitted_at": distribution.get("submitted_at", ""),
        "publication_status": distribution.get("publication_status", ""),
        "published_at": distribution.get("published_at", "") or "",
        "release_link": distribution.get("release_link", "") or "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".part", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def update_local_release(
    registration: ReleaseRegistration,
    track: TrackRegistration,
    resource_root: Path,
    feishu_record_id: str,
) -> None:
    song_dir = resource_root / track.song_id
    manifest_path = song_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    manifest["isrc"] = track.isrc
    if registration.upc:
        manifest["upc"] = registration.upc
    manifest["release_title"] = registration.release_title
    manifest["feishu_release_record_id"] = feishu_record_id
    manifest["distribution"] = {
        "distributor": registration.distributor,
        "status": registration.distributor_status,
        "submitted_at": registration.submitted_at,
        "target_platforms": list(registration.target_platforms),
        "upc": registration.upc or None,
        "publication_status": registration.publication_status,
        "published_at": registration.published_at or None,
        "release_link": registration.release_link or None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    save_manifest(manifest_path, manifest)

    metadata_path = song_dir / "release" / "release_metadata.json"
    if not metadata_path.is_file():
        return
    metadata = load_manifest(metadata_path)
    metadata.setdefault("identifiers", {})
    metadata["identifiers"]["isrc"] = track.isrc
    metadata["identifiers"]["upc"] = registration.upc or None
    metadata.setdefault("release", {})
    metadata["release"]["title"] = registration.release_title
    metadata["distribution"] = {
        "distributor": registration.distributor,
        "status": registration.distributor_status,
        "submitted_at": registration.submitted_at,
        "target_platforms": list(registration.target_platforms),
        "publication_status": registration.publication_status,
        "published_at": registration.published_at or None,
        "release_link": registration.release_link or None,
    }
    save_manifest(metadata_path, metadata)
    write_release_csv(metadata_path.with_name("release_metadata.csv"), metadata)
