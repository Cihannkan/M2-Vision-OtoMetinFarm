import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from src.phantom.diagnostic_video import (
    DiagnosticVideoRecorder,
    annotate_diagnostic_frame,
    fit_even_frame_size,
    prune_diagnostic_recordings,
    segment_paths,
)


class DiagnosticVideoTests(unittest.TestCase):
    def test_default_recording_rotates_after_one_minute(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = DiagnosticVideoRecorder(folder, enabled=True)
            self.assertEqual(recorder.segment_seconds, 60)
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            monitor = {"left": 0, "top": 0, "width": 320, "height": 240}
            try:
                recorder._write_frame(frame, 1700000000.0, monitor, {})
                first = recorder.status()["current_file"]
                recorder._write_frame(frame, 1700000059.5, monitor, {})
                self.assertEqual(recorder.status()["current_file"], first)
                recorder._write_frame(frame, 1700000060.0, monitor, {})
                self.assertNotEqual(recorder.status()["current_file"], first)
                self.assertGreater(Path(first).stat().st_size, 0)
            finally:
                recorder._close_segment()

    def test_frame_size_is_bounded_and_even(self):
        self.assertEqual(fit_even_frame_size(2048, 833, 1280, 720), (1280, 520))
        width, height = fit_even_frame_size(801, 601, 1280, 720)
        self.assertEqual(width % 2, 0)
        self.assertEqual(height % 2, 0)
        self.assertLessEqual(width, 1280)
        self.assertLessEqual(height, 720)

    def test_segment_video_and_metadata_names_match(self):
        video, metadata = segment_paths("C:/temp/videos", "20260910_120000", 3)
        self.assertEqual(video.name, "phantom_diag_20260910_120000_part003.mp4")
        self.assertEqual(metadata.name, "phantom_diag_20260910_120000_part003.jsonl")

    def test_pruning_never_deletes_unrelated_files(self):
        with tempfile.TemporaryDirectory() as folder:
            old_video = Path(folder) / "phantom_diag_old_part001.mp4"
            unrelated = Path(folder) / "user_video.mp4"
            old_video.write_bytes(b"old")
            unrelated.write_bytes(b"keep")
            old_epoch = time.time() - (3 * 86400)
            os.utime(old_video, (old_epoch, old_epoch))

            removed = prune_diagnostic_recordings(
                folder,
                retention_days=2,
                max_total_bytes=1024,
            )

            self.assertIn(str(old_video), removed)
            self.assertFalse(old_video.exists())
            self.assertTrue(unrelated.exists())

    def test_overlay_draws_timestamp_and_client_routing(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        context = {
            "bot_active": True,
            "foreground_hwnd": 123,
            "clients": [{
                "client": 1,
                "hwnd": 123,
                "rect": [10, 40, 300, 220],
                "state": "SAVASIYOR",
                "generation": 7,
                "hp_fill": 0.42,
                "hp_sample_valid": True,
            }],
        }

        result = annotate_diagnostic_frame(
            frame,
            1_700_000_000.125,
            context,
            {"left": 0, "top": 0},
        )

        self.assertIs(result, frame)
        self.assertGreater(int(frame.sum()), 0)

    def test_synthetic_frame_creates_video_and_timestamp_sidecar(self):
        with tempfile.TemporaryDirectory() as folder:
            recorder = DiagnosticVideoRecorder(
                folder,
                enabled=True,
                fps=2.0,
                segment_seconds=10.0,
                max_width=320,
                max_height=240,
            )
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            context = {"bot_active": False, "foreground_hwnd": 0, "clients": []}

            recorder._write_frame(
                frame,
                1_700_000_000.0,
                {"left": 0, "top": 0, "width": 320, "height": 240},
                context,
            )
            active_status = recorder.status()
            recorder._close_segment()

            video_path = Path(active_status["current_file"])
            metadata_path = Path(active_status["current_metadata"])
            self.assertTrue(video_path.exists())
            self.assertGreater(video_path.stat().st_size, 0)
            self.assertTrue(metadata_path.exists())
            records = [json.loads(line) for line in metadata_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["type"], "segment")
            self.assertEqual(records[1]["type"], "frame")
            self.assertEqual(records[1]["epoch"], 1_700_000_000.0)

if __name__ == "__main__":
    unittest.main()
