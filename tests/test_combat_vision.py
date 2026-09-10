import unittest

import cv2
import numpy as np

from src.phantom.vision.combat import (
    estimate_red_fill,
    estimate_scene_motion,
    filter_targets_away_from,
    hp_panel_presence_vote,
    hp_panel_structure_mask,
    is_credible_hp_bar,
    is_hp_panel_authoritative,
    is_plausible_hp_sample,
    locate_hp_bar,
    match_hp_panel_anchor,
    rank_target_candidates,
    track_hp_progress,
)


class CombatVisionTests(unittest.TestCase):
    def test_hybrid_ranking_prefers_nearer_equal_target(self):
        targets = [
            {"cx": 510, "cy": 400, "box": (490, 370, 530, 430), "conf": 0.80, "stable_distance": 2.0},
            {"cx": 700, "cy": 400, "box": (680, 370, 720, 430), "conf": 0.80, "stable_distance": 2.0},
        ]
        ranked = rank_target_candidates(targets, (500, 400))
        self.assertIs(ranked[0]["target"], targets[0])

    def test_hybrid_ranking_can_prefer_much_larger_nearby_target(self):
        centered_but_tiny = {
            "cx": 510, "cy": 400, "box": (500, 390, 520, 410),
            "conf": 0.80, "stable_distance": 2.0,
        }
        moderately_offset_and_large = {
            "cx": 650, "cy": 400, "box": (600, 350, 700, 450),
            "conf": 0.80, "stable_distance": 2.0,
        }
        ranked = rank_target_candidates(
            [centered_but_tiny, moderately_offset_and_large],
            (500, 400),
        )
        self.assertIs(ranked[0]["target"], moderately_offset_and_large)

    def test_hybrid_ranking_exposes_normalized_score_components(self):
        target = {
            "cx": 500, "cy": 400, "box": (470, 360, 530, 440),
            "conf": 0.90, "stable_distance": 0.0,
        }
        selected = rank_target_candidates([target], (500, 400))[0]
        self.assertGreater(selected["score"], 0.0)
        for key in ("distance_score", "size_score", "confidence_score", "stability_score"):
            self.assertGreaterEqual(selected[key], 0.0)
            self.assertLessEqual(selected[key], 1.0)

    def test_temporarily_blocked_target_is_not_usable(self):
        targets = [(100, 100)]
        self.assertEqual(filter_targets_away_from(targets, (104, 97), 60.0), [])

    def test_distant_target_remains_usable(self):
        targets = [(100, 100), (205, 100)]
        self.assertEqual(
            filter_targets_away_from(targets, (103, 99), 60.0),
            [(205, 100)],
        )

    def test_hp_progress_accumulates_until_meaningful_drop(self):
        floor, advanced = track_hp_progress(0.90, 0.895, 0.012)
        self.assertEqual(floor, 0.90)
        self.assertFalse(advanced)

        floor, advanced = track_hp_progress(floor, 0.887, 0.012)
        self.assertAlmostEqual(floor, 0.887)
        self.assertTrue(advanced)

    def test_hp_progress_does_not_accept_bar_growth(self):
        floor, advanced = track_hp_progress(0.60, 0.64, 0.012)
        self.assertEqual(floor, 0.60)
        self.assertFalse(advanced)

    def test_one_pixel_drop_on_rumeli2_bar_counts_as_progress(self):
        one_pixel = 1.0 / 106.0
        floor, advanced = track_hp_progress(0.80, 0.80 - one_pixel, 0.006)
        self.assertTrue(advanced)
        self.assertAlmostEqual(floor, 0.80 - one_pixel)

    def test_ignored_open_hp_panel_does_not_block_search(self):
        self.assertFalse(is_hp_panel_authoritative(True, 100.0, float("inf")))
        self.assertTrue(is_hp_panel_authoritative(True, 100.0, 99.0))
        self.assertFalse(is_hp_panel_authoritative(False, 100.0, 0.0))

    def test_identical_scene_is_stationary(self):
        rng = np.random.default_rng(42)
        frame = rng.integers(0, 256, size=(108, 192), dtype=np.uint8)
        result = estimate_scene_motion(frame, frame.copy())
        self.assertTrue(result["ready"])
        self.assertFalse(result["moving"])

    def test_global_shift_is_movement(self):
        rng = np.random.default_rng(7)
        frame = rng.integers(0, 256, size=(108, 192), dtype=np.uint8)
        matrix = np.float32([[1, 0, 3], [0, 1, 1]])
        shifted = cv2.warpAffine(frame, matrix, (192, 108), borderMode=cv2.BORDER_REFLECT)
        result = estimate_scene_motion(frame, shifted)
        self.assertTrue(result["ready"])
        self.assertTrue(result["moving"])
        self.assertGreater(result["score"], 1.0)

    def test_local_animation_does_not_count_as_world_motion(self):
        rng = np.random.default_rng(11)
        frame = rng.integers(0, 256, size=(108, 192), dtype=np.uint8)
        changed = frame.copy()
        changed[45:65, 85:105] = 255 - changed[45:65, 85:105]
        result = estimate_scene_motion(frame, changed)
        self.assertTrue(result["ready"])
        self.assertFalse(result["moving"])

    def test_red_fill_extent_tracks_right_edge(self):
        full = np.zeros((12, 100, 3), dtype=np.uint8)
        half = np.zeros((12, 100, 3), dtype=np.uint8)
        full[2:10, :90] = (0, 0, 220)
        half[2:10, :45] = (0, 0, 220)
        self.assertAlmostEqual(estimate_red_fill(full), 0.90, delta=0.02)
        self.assertAlmostEqual(estimate_red_fill(half), 0.45, delta=0.02)

    def test_red_fill_returns_none_without_bar(self):
        frame = np.full((12, 100, 3), 80, dtype=np.uint8)
        self.assertIsNone(estimate_red_fill(frame))

    def test_red_border_does_not_force_full_health(self):
        frame = np.zeros((16, 100, 3), dtype=np.uint8)
        frame[4:12, 2:45] = (0, 0, 220)
        frame[:, 98:100] = (0, 0, 180)
        frame[:2, :] = (0, 0, 180)
        frame[-2:, :] = (0, 0, 180)
        self.assertAlmostEqual(estimate_red_fill(frame), 0.45, delta=0.03)

    def test_full_panel_calibration_finds_bright_red_bar_on_brown_scene(self):
        panel = np.full((46, 400, 3), (55, 92, 138), dtype=np.uint8)
        panel[21:26, 235:341] = (25, 45, 225)
        detected = locate_hp_bar(panel)
        self.assertTrue(detected["found"])
        x, _y, width, _height = detected["bar_box"]
        self.assertAlmostEqual(x, 235, delta=2)
        self.assertAlmostEqual(width, 106, delta=2)

    def test_runtime_bar_detection_tolerates_shift_and_tracks_half_fill(self):
        panel = np.full((70, 430, 3), (45, 78, 128), dtype=np.uint8)
        expected = (247, 23, 106, 9)
        panel[28:33, 253:306] = (20, 40, 225)
        detected = locate_hp_bar(panel, expected_box=expected, search_margin=12)
        self.assertTrue(detected["found"])
        self.assertAlmostEqual(detected["fill"], 0.50, delta=0.03)

    def test_runtime_bar_detection_can_search_full_panel_width(self):
        panel = np.full((70, 430, 3), (45, 78, 128), dtype=np.uint8)
        expected = (247, 23, 106, 9)
        panel[28:33, 180:233] = (20, 40, 225)

        narrow = locate_hp_bar(panel, expected_box=expected, search_margin=12)
        wide = locate_hp_bar(
            panel,
            expected_box=expected,
            search_margin=12,
            horizontal_search_margin=panel.shape[1],
        )

        self.assertFalse(narrow["found"])
        self.assertTrue(wide["found"])
        self.assertAlmostEqual(wide["fill"], 0.50, delta=0.03)

    def test_wide_horizontal_search_keeps_vertical_search_narrow(self):
        panel = np.full((90, 430, 3), (45, 78, 128), dtype=np.uint8)
        expected = (247, 23, 106, 9)
        panel[67:72, 207:260] = (20, 40, 225)

        detected = locate_hp_bar(
            panel,
            expected_box=expected,
            search_margin=12,
            horizontal_search_margin=panel.shape[1],
        )

        self.assertFalse(detected["found"])

    def test_runtime_bar_detection_rejects_brown_background(self):
        panel = np.full((46, 400, 3), (55, 92, 138), dtype=np.uint8)
        detected = locate_hp_bar(panel, expected_box=(235, 20, 106, 9), search_margin=12)
        self.assertFalse(detected["found"])
        self.assertIsNone(detected["fill"])

    def test_runtime_fill_ignores_two_pixel_static_red_outline(self):
        panel = np.full((50, 400, 3), (55, 92, 138), dtype=np.uint8)
        expected = (220, 18, 120, 10)
        panel[20:22, 220:340] = (20, 40, 225)
        panel[24:28, 220:280] = (20, 40, 225)

        detected = locate_hp_bar(
            panel,
            expected_box=expected,
            search_margin=12,
            horizontal_search_margin=panel.shape[1],
        )

        self.assertTrue(detected["found"])
        self.assertAlmostEqual(detected["fill"], 0.50, delta=0.02)

    def test_static_red_outline_without_inner_fill_is_not_hp_progress(self):
        panel = np.full((50, 400, 3), (55, 92, 138), dtype=np.uint8)
        expected = (220, 18, 120, 10)
        panel[20:22, 220:340] = (20, 40, 225)

        detected = locate_hp_bar(
            panel,
            expected_box=expected,
            search_margin=12,
            horizontal_search_margin=panel.shape[1],
        )

        self.assertFalse(detected["found"])
        self.assertIsNone(detected["fill"])

    def test_tiny_red_fragment_cannot_open_unconfirmed_panel(self):
        fragment = {"found": True, "fill": 1.0 / 106.0}
        self.assertFalse(is_credible_hp_bar(fragment, was_confirmed=False, min_initial_fill=0.08))
        self.assertTrue(is_credible_hp_bar(fragment, was_confirmed=True, min_initial_fill=0.08))

    def test_normal_red_bar_can_open_unconfirmed_panel(self):
        self.assertTrue(
            is_credible_hp_bar(
                {"found": True, "fill": 0.75},
                was_confirmed=False,
                min_initial_fill=0.08,
            )
        )

    def test_panel_presence_uses_structure_not_changing_red_fill(self):
        self.assertFalse(hp_panel_presence_vote(True, False, was_confirmed=False))
        self.assertTrue(hp_panel_presence_vote(False, True, was_confirmed=False))
        self.assertTrue(hp_panel_presence_vote(True, True, was_confirmed=False))

    def test_confirmed_red_bar_cannot_replace_missing_panel_structure(self):
        self.assertFalse(hp_panel_presence_vote(True, False, was_confirmed=True))
        self.assertFalse(hp_panel_presence_vote(False, False, was_confirmed=True))
        self.assertTrue(hp_panel_presence_vote(False, True, was_confirmed=True))

    def test_hp_sample_allows_small_pixel_noise_but_rejects_large_growth(self):
        self.assertTrue(is_plausible_hp_sample(0.50, 0.53, max_increase=0.04))
        self.assertFalse(is_plausible_hp_sample(0.50, 0.55, max_increase=0.04))

    def test_hp_sample_rejects_missing_and_out_of_range_values(self):
        self.assertFalse(is_plausible_hp_sample(0.50, None))
        self.assertFalse(is_plausible_hp_sample(0.50, 1.10))
        self.assertTrue(is_plausible_hp_sample(None, 0.90))

    def test_panel_anchor_rejects_red_line_without_frame(self):
        template = np.zeros((38, 390), dtype=np.uint8)
        cv2.rectangle(template, (0, 0), (389, 37), 150, 1)
        cv2.line(template, (365, 12), (376, 23), 235, 2)
        cv2.line(template, (376, 12), (365, 23), 235, 2)
        roi = np.full((62, 414, 3), (55, 92, 138), dtype=np.uint8)
        roi[28:33, 180:286] = (20, 40, 225)

        result = match_hp_panel_anchor(roi, template)

        self.assertFalse(result["matched"])

    def test_panel_anchor_matches_shifted_frame_and_close_button(self):
        template = np.zeros((38, 390), dtype=np.uint8)
        cv2.rectangle(template, (0, 0), (389, 37), 150, 1)
        cv2.line(template, (365, 12), (376, 23), 235, 2)
        cv2.line(template, (376, 12), (365, 23), 235, 2)
        roi = np.full((62, 430), 35, dtype=np.uint8)
        shifted_anchor = template[:, -max(36, int(round(template.shape[1] * 0.12))):]
        roi[12:50, 344:344 + shifted_anchor.shape[1]] = shifted_anchor

        result = match_hp_panel_anchor(roi, template)

        self.assertTrue(result["matched"])

    def test_panel_structure_mask_excludes_dynamic_bar(self):
        mask = hp_panel_structure_mask((46, 400), (235, 20, 106, 9))
        self.assertEqual(int(mask[23, 250]), 0)
        self.assertEqual(int(mask[1, 200]), 255)
        self.assertEqual(int(mask[23, 390]), 255)


if __name__ == "__main__":
    unittest.main()
