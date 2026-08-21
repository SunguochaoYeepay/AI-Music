#!/usr/bin/env python3
"""Build a full-length social video from a loop source and a song asset."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ai_music_pipeline.manifest import load_manifest, save_manifest


def _probe(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height,avg_frame_rate",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _duration(path: Path) -> float:
    value = (_probe(path).get("format") or {}).get("duration")
    if value is None or float(value) <= 0:
        raise RuntimeError(f"Could not read a positive duration from {path}")
    return float(value)


def _validate_video(path: Path) -> None:
    streams = [stream for stream in _probe(path).get("streams", []) if stream.get("codec_type") == "video"]
    if not streams:
        raise RuntimeError(f"No video stream found in {path}")


def _video_encoder_args(crf: int) -> list[str]:
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if "h264_videotoolbox" in probe:
        return ["-c:v", "h264_videotoolbox", "-b:v", "8M", "-allow_sw", "1"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf)]


def _resolve_asset(song_dir: Path, manifest: dict[str, Any], key: str, fallback: str) -> Path:
    assets = manifest.get("assets", {})
    name = assets.get(key, fallback) if isinstance(assets, dict) else fallback
    path = (song_dir / str(name)).resolve()
    if not path.is_file() or song_dir.resolve() not in path.parents:
        raise FileNotFoundError(path)
    return path


def prepare_video(
    song_dir: Path,
    *,
    source: Path | None = None,
    audio: Path | None = None,
    output: Path | None = None,
    width: int = 1920,
    height: int = 1080,
    fps: int = 24,
    crf: int = 18,
    force: bool = False,
) -> dict[str, Any]:
    manifest_path = song_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    song_dir = song_dir.resolve()
    source = source.resolve() if source else _resolve_asset(song_dir, manifest, "video_loop_source", "video_loop_source_864x480.mp4")
    audio = audio.resolve() if audio else _resolve_asset(song_dir, manifest, "distribution_mp3", "audio_320k.mp3")
    output = output.resolve() if output else song_dir / f"video_music_{width}x{height}.mp4"
    if output.parent != song_dir:
        raise ValueError("Output must be inside the song resource directory")
    if source == output or audio == output:
        raise ValueError("Source and output files must be different")
    _validate_video(source)
    duration = _duration(audio)
    if width <= 0 or height <= 0 or fps <= 0 or not 0 <= crf <= 51:
        raise ValueError("Invalid video encoding parameters")
    if output.exists() and not force:
        raise FileExistsError(f"Output exists; pass --force to replace it: {output}")

    temp_name = f".{output.name}.part"
    with tempfile.NamedTemporaryFile(prefix=temp_name, dir=output.parent, delete=False) as handle:
        temp_output = Path(handle.name)
    temp_output.unlink(missing_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-stream_loop",
        "-1",
        "-i",
        str(source),
        "-i",
        str(audio),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-vf",
        f"scale={width}:{height}:flags=lanczos",
        "-r",
        str(fps),
        *_video_encoder_args(crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "320k",
        "-t",
        f"{duration:.6f}",
        "-movflags",
        "+faststart",
        "-f",
        "mp4",
        str(temp_output),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        if _duration(temp_output) <= 0:
            raise RuntimeError("Generated video has no duration")
        temp_output.replace(output)
    finally:
        temp_output.unlink(missing_ok=True)

    assets = manifest.setdefault("assets", {})
    assets["video_loop_source"] = source.name
    assets[f"video_music_{width}x{height}"] = output.name
    manifest["video"] = {
        "source": source.name,
        "file": output.name,
        "width": width,
        "height": height,
        "fps": fps,
        "duration_seconds": round(duration, 3),
        "audio_source": audio.name,
        "audio_replaced": True,
        "generation_method": "loop_source_muxed_with_song_audio",
    }
    save_manifest(manifest_path, manifest)
    return manifest["video"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Loop a video source to the full song duration")
    parser.add_argument("--song-dir", type=Path, required=True)
    parser.add_argument("--source", type=Path, help="Loop source video; defaults to manifest asset")
    parser.add_argument("--audio", type=Path, help="Song audio; defaults to manifest distribution MP3")
    parser.add_argument("--output", type=Path, help="Output filename inside song directory")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--crf", type=int, default=18, help="Reserved for software encoders; VideoToolbox uses bitrate")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = prepare_video(
        args.song_dir,
        source=args.source,
        audio=args.audio,
        output=args.output,
        width=args.width,
        height=args.height,
        fps=args.fps,
        crf=args.crf,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
