from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_music_pipeline.assets import archive_and_cleanup
from ai_music_pipeline.locks import PipelineLock
from ai_music_pipeline.manifest import load_manifest, save_manifest
from ai_music_pipeline.release_registration import (
    build_track_fields,
    load_registration,
    publication_status,
    update_local_release,
)
from scripts.comfy_submit import _safe_output_path
from scripts.prepare_release import prepare_release
from scripts.reconcile_reviews import _pagination_marker, parse_records


class PipelineSafetyTests(unittest.TestCase):
    def test_archive_verifies_before_removing_temp(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            temp = root / "temp" / "SONG-1"
            resource = root / "resource" / "SONG-1"
            temp.mkdir(parents=True)
            (temp / "audio.flac").write_bytes(b"audio")
            save_manifest(temp / "manifest.json", {"song_id": "SONG-1"})
            archive_and_cleanup(temp, resource, ["audio.flac", "manifest.json"])
            self.assertFalse(temp.exists())
            self.assertEqual((resource / "audio.flac").read_bytes(), b"audio")
            self.assertTrue((resource / "manifest.json").is_file())

    def test_lock_blocks_concurrent_run(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "pipeline.lock"
            first = PipelineLock(path)
            first.acquire()
            try:
                with self.assertRaises(RuntimeError):
                    PipelineLock(path).acquire()
            finally:
                first.release()

    def test_output_path_rejects_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                _safe_output_path(Path(root), "", "../outside.wav")

    def test_record_parser_and_pagination_guard(self) -> None:
        payload = {"data": {"items": [{"record_id": "rec1", "fields": {"歌曲ID": "S1"}}]}}
        self.assertEqual([record.record_id for record in parse_records(payload)], ["rec1"])
        self.assertEqual(_pagination_marker(payload), (False, None))
        self.assertEqual(_pagination_marker({"data": {"has_more": True, "page_token": "next"}}), (True, "next"))

    def test_release_blocks_noncommercial_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            song_dir = Path(root)
            save_manifest(
                song_dir / "manifest.json",
                {"song_id": "COVER-1", "status": "approved", "commercial_allowed": False},
            )
            with self.assertRaisesRegex(RuntimeError, "cover/non-commercial"):
                prepare_release(song_dir)

    def test_release_registration_validates_and_builds_fields(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            resource = root / "resource"
            song = resource / "SONG-1"
            song.mkdir(parents=True)
            save_manifest(
                song / "manifest.json",
                {"song_id": "SONG-1", "title": "Track", "artist": "燧燧", "duration_seconds": 123.4},
            )
            release_file = root / "release.json"
            save_manifest(
                release_file,
                {
                    "release_title": "Album",
                    "distributor": "RouteNote",
                    "distributor_status": "In Review",
                    "submitted_at": "2026-08-18",
                    "target_platforms": ["Apple Music"],
                    "tracks": [{"song_id": "SONG-1", "isrc": "GX-J2E-26-46977"}],
                },
            )
            registration = load_registration(release_file)
            fields = build_track_fields(registration, registration.tracks[0], resource)
            self.assertEqual(fields["ISRC"], "GXJ2E2646977")
            self.assertEqual(fields["发布状态"], ["待发布"])
            self.assertEqual(fields["曲目时长（秒）"], 123.4)

    def test_release_registration_updates_local_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            resource = root / "resource"
            song = resource / "SONG-1"
            release_dir = song / "release"
            release_dir.mkdir(parents=True)
            save_manifest(song / "manifest.json", {"song_id": "SONG-1", "title": "Track"})
            save_manifest(
                release_dir / "release_metadata.json",
                {
                    "audio": {"file": "audio.wav"},
                    "artwork": {"file": "cover.jpg"},
                    "release": {"title": "Track", "primary_artist": "燧燧"},
                    "track": {"title": "Track"},
                    "rights": {},
                    "identifiers": {"isrc": None, "upc": None},
                },
            )
            release_file = root / "release.json"
            save_manifest(
                release_file,
                {
                    "release_title": "Album",
                    "distributor": "RouteNote",
                    "distributor_status": "Approved",
                    "submitted_at": "2026-08-18",
                    "target_platforms": ["Apple Music"],
                    "tracks": [{"song_id": "SONG-1", "isrc": "GXJ2E2646977"}],
                },
            )
            registration = load_registration(release_file)
            update_local_release(registration, registration.tracks[0], resource, "rec1")
            manifest = load_manifest(song / "manifest.json")
            metadata = load_manifest(release_dir / "release_metadata.json")
            self.assertEqual(manifest["isrc"], "GXJ2E2646977")
            self.assertEqual(manifest["feishu_release_record_id"], "rec1")
            self.assertEqual(metadata["release"]["title"], "Album")
            self.assertTrue((release_dir / "release_metadata.csv").is_file())
            self.assertEqual(publication_status("Approved"), "待发布")


if __name__ == "__main__":
    unittest.main()
