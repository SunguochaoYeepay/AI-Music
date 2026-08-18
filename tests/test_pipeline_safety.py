from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_music_pipeline.assets import archive_and_cleanup
from ai_music_pipeline.locks import PipelineLock
from ai_music_pipeline.manifest import save_manifest
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


if __name__ == "__main__":
    unittest.main()
