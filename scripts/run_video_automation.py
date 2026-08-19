#!/usr/bin/env python3
"""Generate social videos for Feishu-approved songs that do not have one yet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_music_pipeline.assets import copy_verified
from ai_music_pipeline.comfyui import ComfyUIClient
from ai_music_pipeline.locks import PipelineLock
from ai_music_pipeline.manifest import load_manifest, save_manifest
from ai_music_pipeline.video_workflow import build_flux_workflow, build_h3_workflow, choose_preset, get_preset
from scripts.prepare_video import _duration, _probe, prepare_video
from scripts.reconcile_reviews import APPROVED_VALUES, REJECTED_VALUES, Record, _text, list_records


def _workflow_hash(workflow: dict[str, Any]) -> str:
    encoded = json.dumps(workflow, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _output_items(history: dict[str, Any], suffix: str) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    for node in (history.get("outputs") or {}).values():
        if not isinstance(node, dict):
            continue
        for values in node.values():
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename") or "")
                if filename.casefold().endswith(suffix.casefold()):
                    matches.append(
                        {
                            "filename": filename,
                            "subfolder": str(item.get("subfolder") or ""),
                            "type": str(item.get("type") or "output"),
                        }
                    )
    return matches


def _validate_media(
    path: Path,
    *,
    kind: str,
    width: int | None = None,
    height: int | None = None,
    min_duration: float = 0,
) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing or empty {kind}: {path}")
    probe = _probe(path)
    streams = [stream for stream in probe.get("streams", []) if stream.get("codec_type") == kind]
    if not streams:
        raise RuntimeError(f"No {kind} stream in {path}")
    if width and int(streams[0].get("width") or 0) != width:
        raise RuntimeError(f"Unexpected width for {path}")
    if height and int(streams[0].get("height") or 0) != height:
        raise RuntimeError(f"Unexpected height for {path}")
    if min_duration and _duration(path) < min_duration:
        raise RuntimeError(f"Loop source is unexpectedly short: {path}")


def _run_stage(
    client: ComfyUIClient,
    state: dict[str, Any],
    stage_name: str,
    workflow: dict[str, Any],
    destination: Path,
    suffix: str,
) -> str:
    digest = _workflow_hash(workflow)
    stage = state.setdefault(stage_name, {})
    if stage.get("workflow_hash") != digest:
        stage.clear()
        stage["workflow_hash"] = digest
    prompt_id = stage.get("prompt_id")
    if not prompt_id:
        prompt_id = client.submit(workflow, f"ai-music-video-{stage_name}-{uuid.uuid4()}")
        stage.update({"prompt_id": prompt_id, "status": "submitted"})
        save_manifest(Path(state["state_file"]), state)

    history = client.wait_for_success(str(prompt_id), poll_seconds=10, timeout_seconds=7200)
    items = _output_items(history, suffix)
    if not items:
        raise RuntimeError(f"ComfyUI stage {stage_name} returned no {suffix} output")
    item = items[0]
    client.download(item["filename"], destination, item["subfolder"], item["type"])
    stage.update({"status": "success", "output": item, "downloaded": str(destination)})
    save_manifest(Path(state["state_file"]), state)
    return str(prompt_id)


def _video_path(song_dir: Path, manifest: dict[str, Any]) -> Path:
    video = manifest.get("video") or {}
    name = video.get("file") if isinstance(video, dict) else None
    return song_dir / str(name or "video_music_1080p.mp4")


def video_is_complete(song_dir: Path) -> bool:
    manifest_path = song_dir / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = load_manifest(manifest_path)
        path = _video_path(song_dir, manifest)
        _validate_media(path, kind="video", width=1920, height=1080, min_duration=30)
        return True
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError, subprocess.SubprocessError):
        return False


def _record_by_song(records: list[Record]) -> dict[str, Record]:
    result: dict[str, Record] = {}
    for record in records:
        song_id = _text(record.fields.get("歌曲ID"))
        if song_id:
            result[song_id] = record
    return result


def approved_records(records: list[Record]) -> list[Record]:
    return [record for record in records if _text(record.fields.get("审听结果")).casefold() in APPROVED_VALUES]


def _upsert_video_record(
    *,
    cli: str,
    base_token: str,
    table_id: str,
    existing: Record | None,
    music_record: Record,
    song_dir: Path,
    manifest: dict[str, Any],
) -> None:
    song_id = _text(music_record.fields.get("歌曲ID"))
    title = _text(music_record.fields.get("歌曲标题")) or str(manifest.get("title") or song_id)
    artist = _text(music_record.fields.get("艺术家")) or str(manifest.get("artist") or "燧燧")
    video = manifest.get("video") or {}
    duration = float(video.get("duration_seconds") or _duration(_video_path(song_dir, manifest)))
    preset = str(video.get("visual_preset") or "cinematic")
    fields = {
        "视频项目": f"{title}·全曲视频·1080p",
        "AI标注": True,
        "生成方式": ["H3首尾帧循环"],
        "发布文案": f"《{title}》｜{artist}。适合在安静、通勤或放松时播放。音乐由 MiniMax-Music3 生成，电影感关键帧由 Flux 生成，动态画面由 MiniMax H3 生成。",
        "歌曲ID": song_id,
        "歌曲标题": title,
        "发布标题": f"{title}｜治愈系全曲音乐视频｜{artist}",
        "视频类型": ["横版长视频"],
        "画面规格": ["1920x1080"],
        "发布平台": ["B站", "抖音", "小红书", "YouTube"],
        "发布状态": ["待发布"],
        "视频时长（秒）": round(duration, 3),
        "备注": f"Flux 16:9 关键帧；H3 官方 FL2VA 首尾同帧；8-step Turbo；视觉预设 {preset}；接入原始歌曲音轨。",
        "艺人": artist,
        "本地视频路径": str(_video_path(song_dir, manifest).resolve()),
    }
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
        "--json",
        json.dumps(fields, ensure_ascii=False),
    ]
    if existing:
        command.extend(["--record-id", existing.record_id])
    subprocess.run(command, check=True, capture_output=True, text=True)


def _safe_remove_job(job_dir: Path, jobs_root: Path) -> None:
    job_dir.resolve().relative_to(jobs_root.resolve())
    shutil.rmtree(job_dir, ignore_errors=True)


def generate_song_video(
    client: ComfyUIClient,
    music_record: Record,
    *,
    song_dir: Path,
    job_dir: Path,
    video_record: Record | None,
    cli: str,
    base_token: str,
    video_table_id: str,
    preset_name: str | None = None,
    force: bool = False,
) -> None:
    song_id = _text(music_record.fields.get("歌曲ID"))
    manifest_path = song_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    preset = get_preset(preset_name) if preset_name else choose_preset({**manifest, **music_record.fields})
    job_dir.mkdir(parents=True, exist_ok=True)
    state_path = job_dir / "state.json"
    state = load_manifest(state_path) if state_path.is_file() else {}
    state.update({"state_file": str(state_path), "song_id": song_id, "status": "running", "updated_at": datetime.now(timezone.utc).isoformat()})
    save_manifest(state_path, state)

    keyframe_temp = job_dir / "video_keyframe_1344x768.png"
    flux_id = _run_stage(client, state, "flux", build_flux_workflow(song_id, preset), keyframe_temp, ".png")
    _validate_media(keyframe_temp, kind="video", width=1344, height=768)
    uploaded = client.upload_input(
        keyframe_temp,
        filename="video_keyframe_1344x768.png",
        subfolder=f"ai_music_pipeline/{song_id}",
    )
    loop_temp = job_dir / "video_loop_source_1344x768.mp4"
    h3_id = _run_stage(client, state, "h3", build_h3_workflow(song_id, uploaded, preset), loop_temp, ".mp4")
    _validate_media(loop_temp, kind="video", width=1344, height=768, min_duration=10)

    keyframe_final = song_dir / keyframe_temp.name
    loop_final = song_dir / loop_temp.name
    copy_verified(keyframe_temp, keyframe_final)
    copy_verified(loop_temp, loop_final)
    output = song_dir / "video_music_1080p.mp4"
    if output.exists() and not video_is_complete(song_dir):
        output.unlink()
    if force or not output.exists():
        prepare_video(song_dir, source=loop_final, output=output, force=force)

    manifest = load_manifest(manifest_path)
    assets = manifest.setdefault("assets", {})
    assets["video_keyframe"] = keyframe_final.name
    assets["video_loop_source"] = loop_final.name
    assets["video_music_1920x1080"] = output.name
    manifest["video"].update(
        {
            "generation_method": "flux_keyframe_h3_fl2va_loop_muxed_with_song_audio",
            "visual_preset": preset.name,
            "keyframe_prompt_id": flux_id,
            "h3_prompt_id": h3_id,
            "h3_acceleration": "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors",
            "h3_steps": 8,
            "h3_prompt_skill": "MiniMax official h3-prompt-writing FL2VA structure",
        }
    )
    save_manifest(manifest_path, manifest)
    _upsert_video_record(
        cli=cli,
        base_token=base_token,
        table_id=video_table_id,
        existing=video_record,
        music_record=music_record,
        song_dir=song_dir,
        manifest=manifest,
    )
    _safe_remove_job(job_dir, job_dir.parent)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate videos for approved Feishu music records")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-songs", type=int, default=0, help="0 processes every eligible song")
    parser.add_argument("--song-id", help="Only inspect and process this exact song ID")
    parser.add_argument("--preset", help="Override the visual preset; requires --song-id")
    parser.add_argument("--force", action="store_true", help="Regenerate an existing video; requires --song-id")
    parser.add_argument("--lock-file", type=Path, default=Path(".ai_music_pipeline.lock"))
    args = parser.parse_args()
    if (args.force or args.preset) and not args.song_id:
        raise SystemExit("--force and --preset require --song-id")

    config = json.loads(args.config.read_text(encoding="utf-8"))
    root = args.config.resolve().parent
    feishu = config.get("feishu") or {}
    base_token = str(feishu.get("base_token") or os.getenv("FEISHU_BASE_TOKEN") or "")
    if not base_token:
        raise SystemExit("Set feishu.base_token in config.json or FEISHU_BASE_TOKEN")
    cli = str(feishu.get("cli") or "lark-cli")
    music_table_id = str(feishu.get("music_table_id") or "")
    video_table_id = str(feishu.get("video_table_id") or "")
    resource_root = (root / str(config.get("resource_library") or "resource_library")).resolve()
    jobs_root = root / "temp" / "video_jobs"

    with PipelineLock(args.lock_file):
        music_records = list_records(cli, base_token, music_table_id, None)
        video_records = list_records(cli, base_token, video_table_id, None)
        videos_by_song = _record_by_song(video_records)

        for record in music_records:
            song_id = _text(record.fields.get("歌曲ID"))
            review = _text(record.fields.get("审听结果")).casefold()
            generation = _text(record.fields.get("生成状态")).casefold()
            if review in REJECTED_VALUES or generation in REJECTED_VALUES:
                job_dir = jobs_root / song_id
                if args.apply and song_id and job_dir.is_dir():
                    _safe_remove_job(job_dir, jobs_root)

        eligible: list[Record] = []
        for record in approved_records(music_records):
            song_id = _text(record.fields.get("歌曲ID"))
            if args.song_id and song_id != args.song_id:
                continue
            song_dir = resource_root / song_id
            if video_is_complete(song_dir) and not args.force:
                if args.apply and song_id not in videos_by_song:
                    _upsert_video_record(
                        cli=cli,
                        base_token=base_token,
                        table_id=video_table_id,
                        existing=None,
                        music_record=record,
                        song_dir=song_dir,
                        manifest=load_manifest(song_dir / "manifest.json"),
                    )
                print(f"SKIP {song_id}: complete video already exists")
            elif (song_dir / "manifest.json").is_file():
                eligible.append(record)
                print(f"QUEUE {song_id}: approved and missing video")
            else:
                print(f"BLOCKED {song_id}: local resource manifest is missing")

        if not args.apply:
            print("DRY-RUN: no generation or Feishu writes were performed")
            return
        if not eligible:
            print("No approved songs need video generation")
            return
        client = ComfyUIClient(str(config.get("comfyui_url") or "http://127.0.0.1:8188"), timeout=30, retries=2)
        if not client.is_available():
            status = {
                "status": "waiting_for_comfyui",
                "songs": [_text(record.fields.get("歌曲ID")) for record in eligible],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            save_manifest(root / "temp" / "video_automation_status.json", status)
            print("WAIT: ComfyUI is offline; the next scheduled run will retry")
            return

        failures = 0
        selected = eligible[: args.max_songs] if args.max_songs > 0 else eligible
        for record in selected:
            song_id = _text(record.fields.get("歌曲ID"))
            try:
                generate_song_video(
                    client,
                    record,
                    song_dir=resource_root / song_id,
                    job_dir=jobs_root / song_id,
                    video_record=videos_by_song.get(song_id),
                    cli=cli,
                    base_token=base_token,
                    video_table_id=video_table_id,
                    preset_name=args.preset,
                    force=args.force,
                )
                print(f"DONE {song_id}: video archived and Feishu updated")
            except Exception as error:
                failures += 1
                job_dir = jobs_root / song_id
                job_dir.mkdir(parents=True, exist_ok=True)
                state_path = job_dir / "state.json"
                state = load_manifest(state_path) if state_path.is_file() else {}
                state.update({"status": "retry", "error": str(error), "updated_at": datetime.now(timezone.utc).isoformat()})
                save_manifest(state_path, state)
                print(f"RETRY {song_id}: {error}")
        if failures:
            raise SystemExit(f"{failures} video job(s) need retry")


if __name__ == "__main__":
    main()
