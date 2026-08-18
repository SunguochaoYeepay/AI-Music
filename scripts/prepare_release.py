#!/usr/bin/env python3
"""Build an Apple Music/distributor-ready package from a resource-library song."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from ai_music_pipeline.manifest import load_manifest, save_manifest
from ai_music_pipeline.locks import PipelineLock

RELEASE_SCHEMA_VERSION = 2


def _value(manifest: dict[str, Any], credits: dict[str, Any], key: str, default: Any = "") -> Any:
    return credits.get(key) or manifest.get(key) or default


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_fingerprint(values: dict[str, Any], source: Path, cover: Path) -> str:
    digest = hashlib.sha256()
    digest.update(_file_hash(source).encode("ascii"))
    digest.update(_file_hash(cover).encode("ascii"))
    digest.update(json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return digest.hexdigest()


def _run_ffprobe(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_name,sample_rate,bits_per_sample,channels,duration",
        "-of",
        "json",
        str(path),
    ]
    return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)


def _run_image_probe(path: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_name,width,height,pix_fmt",
        "-of",
        "json",
        str(path),
    ]
    return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)


def _check_wav(path: Path) -> dict[str, Any]:
    streams = _run_ffprobe(path).get("streams", [])
    if not streams:
        raise RuntimeError(f"No audio stream found in {path}")
    stream = streams[0]
    codec = stream.get("codec_name", "")
    sample_rate = int(stream.get("sample_rate", 0))
    bits = int(stream.get("bits_per_sample", 0))
    channels = int(stream.get("channels", 0))
    if codec not in {"pcm_s16le", "pcm_s24le", "pcm_s32le"}:
        raise RuntimeError(f"WAV is not uncompressed PCM: {codec}")
    if sample_rate < 44100 or bits < 16 or channels not in {1, 2}:
        raise RuntimeError(f"Unsupported delivery audio parameters: {stream}")
    return {
        "codec": codec,
        "sample_rate_hz": sample_rate,
        "bits_per_sample": bits,
        "channels": channels,
        "duration_seconds": float(stream.get("duration", 0)),
    }


def _source_sample_rate(path: Path) -> int:
    streams = _run_ffprobe(path).get("streams", [])
    if not streams or not streams[0].get("sample_rate"):
        raise RuntimeError(f"Could not read source sample rate: {path}")
    source_rate = int(streams[0]["sample_rate"])
    return source_rate if source_rate >= 44100 else 44100


def _check_artwork(path: Path) -> dict[str, Any]:
    streams = _run_image_probe(path).get("streams", [])
    if not streams:
        raise RuntimeError(f"No image stream found in {path}")
    stream = streams[0]
    if stream.get("codec_name") != "mjpeg" or stream.get("width") != 3000 or stream.get("height") != 3000:
        raise RuntimeError(f"Artwork must be a 3000x3000 JPEG: {stream}")
    return {
        "file": path.name,
        "format": "JPEG",
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "pixel_format": stream.get("pix_fmt", ""),
    }


def _write_csv(path: Path, metadata: dict[str, Any]) -> None:
    release = metadata["release"]
    track = metadata["track"]
    rights = metadata["rights"]
    row = {
        "audio_file": metadata["audio"]["file"],
        "artwork_file": metadata["artwork"]["file"],
        "track_title": track["title"],
        "version": track["version"],
        "primary_artist": release["primary_artist"],
        "performer": track["performer"],
        "composer": track["composer"],
        "lyricist": track["lyricist"],
        "producer": track["producer"],
        "genre": release["genre"],
        "language": release["language"],
        "explicit": str(release["explicit"]).lower(),
        "release_date": release["release_date"],
        "copyright": rights["copyright"],
        "publisher": rights["publisher"],
        "isrc": metadata["identifiers"]["isrc"] or "",
        "upc": metadata["identifiers"]["upc"] or "",
    }
    with path.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def prepare_release(
    song_dir: Path,
    *,
    output_dir: Path | None = None,
    allow_unapproved: bool = False,
    allow_noncommercial: bool = False,
    allow_short: bool = False,
    force: bool = False,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest_path = song_dir / "manifest.json"
    manifest = load_manifest(manifest_path)
    if manifest.get("status") != "approved" and not allow_unapproved:
        raise RuntimeError("Song is not approved; pass --allow-unapproved only for a deliberate test")
    content_type = str(manifest.get("content_type", "")).casefold()
    if (
        not allow_noncommercial
        and (
            manifest.get("commercial_allowed") is False
            or manifest.get("is_cover") is True
            or content_type in {"cover", "翻唱", "非商用", "noncommercial"}
        )
    ):
        raise RuntimeError("This manifest is marked as cover/non-commercial and cannot be packaged for release")

    overrides = overrides or {}
    credits = manifest.get("credits", {})
    if not isinstance(credits, dict):
        credits = {}
    title = overrides.get("title") or manifest.get("title") or manifest.get("song_id") or song_dir.name
    artist = overrides.get("artist") or manifest.get("artist") or "燧燧"
    performer = overrides.get("performer") or _value(manifest, credits, "performer", artist)
    composer = overrides.get("composer") if overrides.get("composer") is not None else _value(manifest, credits, "composer")
    lyricist = overrides.get("lyricist") if overrides.get("lyricist") is not None else _value(manifest, credits, "lyricist")
    producer = overrides.get("producer") or _value(manifest, credits, "producer")
    genre = overrides.get("genre") or _value(manifest, credits, "genre")
    language = overrides.get("language") or _value(manifest, credits, "language")
    release_date = overrides.get("release_date") or manifest.get("release_date") or ""
    copyright_line = overrides.get("copyright") or manifest.get("copyright") or ""
    publisher = overrides.get("publisher") or manifest.get("publisher") or ""
    version = overrides.get("version") or manifest.get("version") or ""
    explicit = bool(overrides.get("explicit", manifest.get("explicit", False)))
    ai_attribution = overrides.get("ai_attribution") or manifest.get("ai_attribution") or "MiniMax-Music3"
    source_name = manifest.get("assets", {}).get("master_flac", "audio_master.flac")
    source = song_dir / source_name
    if not source.is_file():
        raise FileNotFoundError(source)
    cover_source = song_dir / manifest.get("assets", {}).get("cover_png", "cover_1024.png")
    if not cover_source.is_file():
        raise FileNotFoundError(cover_source)

    output_dir = output_dir or song_dir / "release"
    output_dir.mkdir(parents=True, exist_ok=True)
    input_values = {
        "title": title,
        "artist": artist,
        "performer": performer,
        "composer": composer,
        "lyricist": lyricist,
        "producer": producer,
        "genre": genre,
        "language": language,
        "release_date": release_date,
        "copyright": copyright_line,
        "publisher": publisher,
        "version": version,
        "explicit": explicit,
        "ai_attribution": ai_attribution,
    }
    fingerprint = _input_fingerprint(input_values, source, cover_source)
    existing_metadata = output_dir / "release_metadata.json"
    existing_wav = output_dir / "audio_apple_24bit.wav"
    existing_cover = output_dir / "cover_3000.jpg"
    if not force and existing_metadata.is_file() and existing_wav.is_file() and existing_cover.is_file():
        try:
            cached = load_manifest(existing_metadata)
            if cached.get("schema_version") == RELEASE_SCHEMA_VERSION and cached.get("input_fingerprint") == fingerprint:
                _check_wav(existing_wav)
                _check_artwork(existing_cover)
                return cached
        except (OSError, ValueError, json.JSONDecodeError, RuntimeError, KeyError):
            pass
    wav_name = "audio_apple_24bit.wav"
    wav_path = output_dir / wav_name
    temp_wav = output_dir / f".{wav_name}.part"
    target_sample_rate = _source_sample_rate(source)
    comment = f"AI-assisted production; attribution: {ai_attribution}"
    bext_description = (
        f"Title: {title}; Artist: {artist}; Composer: {composer or '未填写'}; "
        f"Lyricist: {lyricist or '未填写'}; Producer: {producer or '未填写'}"
    )[:256]
    ffmpeg = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a:0",
        "-c:a",
        "pcm_s24le",
        "-ar",
        str(target_sample_rate),
        "-ac",
        "2",
        "-write_bext",
        "1",
        "-metadata",
        f"title={title}",
        "-metadata",
        f"artist={artist}",
        "-metadata",
        f"album={title}",
        "-metadata",
        f"album_artist={artist}",
        "-metadata",
        f"composer={composer}",
        "-metadata",
        f"lyricist={lyricist}",
        "-metadata",
        f"producer={producer}",
        "-metadata",
        f"genre={genre}",
        "-metadata",
        f"date={release_date}",
        "-metadata",
        f"copyright={copyright_line}",
        "-metadata",
        f"publisher={publisher}",
        "-metadata",
        f"comment={comment}",
        "-metadata",
        f"description={bext_description}",
        "-metadata",
        f"originator={artist}",
        "-f",
        "wav",
        str(temp_wav),
    ]
    try:
        subprocess.run(ffmpeg, check=True, capture_output=True, text=True)
        audio = _check_wav(temp_wav)
        if audio["duration_seconds"] < 30 and not allow_short:
            raise RuntimeError("Audio is shorter than 30 seconds; pass --allow-short only for a deliberate test")
        temp_wav.replace(wav_path)
    finally:
        temp_wav.unlink(missing_ok=True)

    cover_name = "cover_3000.jpg"
    cover_path = output_dir / cover_name
    temp_cover = output_dir / f".{cover_name}.part"
    upscale = [
        "ffmpeg",
        "-y",
        "-i",
        str(cover_source),
        "-vf",
        "scale=3000:3000:flags=lanczos",
        "-frames:v",
        "1",
        "-c:v",
        "mjpeg",
        "-q:v",
        "2",
        "-pix_fmt",
        "yuvj444p",
        "-f",
        "image2",
        str(temp_cover),
    ]
    try:
        subprocess.run(upscale, check=True, capture_output=True, text=True)
        artwork = _check_artwork(temp_cover)
        artwork["file"] = cover_name
        temp_cover.replace(cover_path)
    finally:
        temp_cover.unlink(missing_ok=True)

    metadata = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "input_fingerprint": fingerprint,
        "platform": "Apple Music (via distributor)",
        "audio": {"file": wav_name, "format": "WAV", **audio},
        "artwork": artwork,
        "release": {
            "title": title,
            "primary_artist": artist,
            "genre": genre,
            "language": language,
            "explicit": explicit,
            "release_date": release_date,
        },
        "track": {
            "title": title,
            "version": version,
            "performer": performer,
            "composer": composer,
            "lyricist": lyricist,
            "producer": producer,
        },
        "rights": {
            "copyright": copyright_line,
            "publisher": publisher,
            "license_note": manifest.get("license", ""),
        },
        "identifiers": {"isrc": manifest.get("isrc"), "upc": manifest.get("upc")},
        "rights_review_required": not bool(manifest.get("commercial_allowed")),
        "delivery_notes": [
            "The WAV contains common RIFF metadata, but the distributor's metadata form is authoritative.",
            "ISRC and UPC must come from the distributor; do not invent them.",
            "Confirm composer/lyricist/publisher credits before submission when those fields are blank.",
        ],
    }
    metadata_path = output_dir / "release_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_csv(output_dir / "release_metadata.csv", metadata)

    manifest.setdefault("release", {})
    manifest["release"].update(
        {
            "audio_wav": f"release/{wav_name}",
            "artwork_jpeg": "release/cover_3000.jpg",
            "metadata_json": "release/release_metadata.json",
            "metadata_csv": "release/release_metadata.csv",
        }
    )
    save_manifest(manifest_path, manifest)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a WAV and metadata package for Apple Music delivery")
    parser.add_argument("--song-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--allow-unapproved", action="store_true")
    parser.add_argument("--allow-noncommercial", action="store_true")
    parser.add_argument("--allow-short", action="store_true")
    parser.add_argument("--force", action="store_true", help="Rebuild even when the input fingerprint is unchanged")
    parser.add_argument("--lock-file", type=Path, default=Path(".ai_music_pipeline.lock"))
    parser.add_argument("--no-lock", action="store_true")
    for name in ("title", "artist", "performer", "composer", "lyricist", "producer", "genre", "language", "release-date", "copyright", "publisher", "version", "ai-attribution"):
        parser.add_argument(f"--{name}", dest=name.replace("-", "_"))
    parser.add_argument("--explicit", action="store_true", default=None)
    args = parser.parse_args()
    overrides = {
        key: value for key, value in vars(args).items() if key not in {"song_dir", "output_dir", "allow_unapproved", "explicit"} and value is not None
    }
    if args.explicit is not None:
        overrides["explicit"] = args.explicit
    def run() -> None:
        metadata = prepare_release(
            args.song_dir,
            output_dir=args.output_dir,
            allow_unapproved=args.allow_unapproved,
            allow_noncommercial=args.allow_noncommercial,
            allow_short=args.allow_short,
            force=args.force,
            overrides=overrides,
        )
        print(json.dumps({"audio": metadata["audio"], "artwork": metadata["artwork"], "metadata": "release_metadata.json", "csv": "release_metadata.csv"}, ensure_ascii=False, indent=2))

    if args.no_lock:
        run()
    else:
        with PipelineLock(args.lock_file):
            run()


if __name__ == "__main__":
    main()
