import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.phantom.captcha.solver import CaptchaWatcher, captcha_status_blocks_input


class Rumeli2CaptchaTests(unittest.TestCase):
    def test_missing_calibration_is_not_a_live_captcha_block(self):
        self.assertFalse(captcha_status_blocks_input("rumeli2_kalibrasyon_yok"))
        self.assertFalse(captcha_status_blocks_input("rumeli2_referans_yok"))
        self.assertFalse(captcha_status_blocks_input("rumeli2_dogrulama"))
        self.assertFalse(captcha_status_blocks_input("dialog_yok"))
        self.assertTrue(captcha_status_blocks_input("rumeli2_ocr_bekle"))
        self.assertTrue(captcha_status_blocks_input("rumeli2_belirsiz"))

    @staticmethod
    def _region(x1, y1, x2, y2, width, height):
        return [y1 / height, y2 / height, x1 / width, x2 / width]

    @staticmethod
    def _watcher(question_region=None, option_regions=None):
        watcher = object.__new__(CaptchaWatcher)
        watcher._lock = threading.Lock()
        watcher._client_id = 0
        watcher._rumeli2_question_region = question_region
        watcher._rumeli2_option_regions = list(option_regions or [])
        watcher._rumeli2_panel_ref_key = None
        watcher._rumeli2_panel_ref_gray = None
        watcher._rumeli2_panel_ref_mask = None
        watcher._rumeli2_job_lock = threading.Lock()
        watcher._rumeli2_job_thread = None
        watcher._rumeli2_job_result = None
        watcher._rumeli2_job_started = 0.0
        watcher._rumeli2_job_generation = 0
        watcher._rumeli2_candidate_error = ""
        return watcher

    def test_digit_reader_uses_preprocessing_majority_instead_of_first_result(self):
        watcher = self._watcher()
        watcher._reader = type(
            "Reader",
            (),
            {
                "__init__": lambda self: setattr(
                    self,
                    "outputs",
                    iter((["560956"], ["660956"], ["660956"])),
                ),
                "readtext": lambda self, *_args, **_kwargs: next(self.outputs),
            },
        )()
        crop = np.full((18, 60, 3), 32, dtype=np.uint8)
        mask = np.full((48, 192), 255, dtype=np.uint8)
        watcher._rumeli2_digit_mask = lambda *_args, **_kwargs: mask

        self.assertEqual(watcher._rumeli2_read_digits(crop), "660956")

    def test_digit_reader_refuses_tied_preprocessing_results(self):
        watcher = self._watcher()
        watcher._reader = type(
            "Reader",
            (),
            {
                "__init__": lambda self: setattr(
                    self,
                    "outputs",
                    iter((["560956"], ["660956"], [])),
                ),
                "readtext": lambda self, *_args, **_kwargs: next(self.outputs),
            },
        )()
        crop = np.full((18, 60, 3), 32, dtype=np.uint8)
        mask = np.full((48, 192), 255, dtype=np.uint8)
        watcher._rumeli2_digit_mask = lambda *_args, **_kwargs: mask

        self.assertEqual(watcher._rumeli2_read_digits(crop), "")

    def test_digit_reader_keeps_windows_from_one_extra_digit(self):
        watcher = self._watcher()
        watcher._reader = type(
            "Reader",
            (),
            {
                "__init__": lambda self: setattr(
                    self,
                    "outputs",
                    iter((["1862871"], ["1", "421"], ["1"])),
                ),
                "readtext": lambda self, *_args, **_kwargs: next(self.outputs),
            },
        )()
        crop = np.full((18, 60, 3), 32, dtype=np.uint8)
        mask = np.full((48, 192), 255, dtype=np.uint8)
        watcher._rumeli2_digit_mask = lambda *_args, **_kwargs: mask

        primary, candidates = watcher._rumeli2_read_digits(crop, include_candidates=True)

        self.assertEqual(primary, "")
        self.assertEqual(candidates, ["186287", "862871"])

    @staticmethod
    def _use_frame_as_panel_reference(watcher, frame):
        question_bbox = watcher._rumeli2_region_bbox(watcher._rumeli2_question_region, frame.shape)
        option_bboxes = [
            watcher._rumeli2_region_bbox(region, frame.shape)
            for region in watcher._rumeli2_option_regions
        ]
        panel, mask = watcher._rumeli2_panel_crop(frame, question_bbox, option_bboxes)
        reference_gray = cv2.cvtColor(panel, cv2.COLOR_BGR2GRAY)
        watcher._rumeli2_panel_reference = lambda *_args: (reference_gray, mask)

    def test_clean_region_rejects_invalid_values(self):
        self.assertIsNone(CaptchaWatcher._rumeli2_clean_region(None))
        self.assertIsNone(CaptchaWatcher._rumeli2_clean_region([0.2, 0.2, 0.1, 0.4]))
        self.assertEqual(
            CaptchaWatcher._rumeli2_clean_region([0.4, 0.2, 0.8, 0.3]),
            [0.2, 0.4, 0.3, 0.8],
        )

    def test_digit_shape_similarity_prefers_identical_code(self):
        question = np.full((32, 104, 3), 28, dtype=np.uint8)
        same = question.copy()
        other = question.copy()
        cv2.putText(question, "285879", (5, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 220, 70), 1, cv2.LINE_AA)
        cv2.putText(same, "285879", (5, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (190, 190, 190), 1, cv2.LINE_AA)
        cv2.putText(other, "700821", (5, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (190, 190, 190), 1, cv2.LINE_AA)

        target_mask = CaptchaWatcher._rumeli2_digit_mask(question, prefer_green=True)
        same_score = CaptchaWatcher._rumeli2_mask_similarity(
            target_mask,
            CaptchaWatcher._rumeli2_digit_mask(same),
        )
        other_score = CaptchaWatcher._rumeli2_mask_similarity(
            target_mask,
            CaptchaWatcher._rumeli2_digit_mask(other),
        )
        self.assertGreater(same_score, 0.85)
        self.assertGreater(same_score - other_score, 0.12)

    def test_candidate_uses_static_panel_without_requiring_green_hue(self):
        height, width = 420, 700
        frame = np.full((height, width, 3), (70, 125, 70), dtype=np.uint8)
        cv2.rectangle(frame, (245, 85), (455, 360), (28, 28, 28), -1)
        question_box = (300, 135, 400, 169)
        option_boxes = [
            (300, 196, 400, 226),
            (300, 235, 400, 265),
            (300, 274, 400, 304),
            (300, 313, 400, 343),
        ]
        cv2.putText(frame, "285879", (question_box[0] + 3, question_box[3] - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (230, 230, 230), 1, cv2.LINE_AA)
        for box, text in zip(option_boxes, ("628867", "285879", "700821", "330464")):
            cv2.putText(frame, text, (box[0] + 3, box[3] - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (190, 190, 190), 1, cv2.LINE_AA)

        watcher = self._watcher(
            self._region(*question_box, width, height),
            [self._region(*box, width, height) for box in option_boxes],
        )
        self._use_frame_as_panel_reference(watcher, frame)
        candidate = watcher._rumeli2_candidate(frame)
        self.assertIsInstance(candidate, dict)
        self.assertLess(candidate["green_ratio"], 0.008)
        scores = [
            watcher._rumeli2_mask_similarity(candidate["question_mask"], mask)
            for mask in candidate["option_masks"]
        ]
        self.assertEqual(int(np.argmax(scores)), 1)

    def test_candidate_refuses_to_run_without_panel_reference(self):
        frame = np.full((240, 320, 3), 28, dtype=np.uint8)
        watcher = self._watcher(
            [0.30, 0.36, 0.40, 0.60],
            [[0.42 + index * 0.08, 0.47 + index * 0.08, 0.40, 0.60] for index in range(4)],
        )
        watcher._rumeli2_panel_reference = lambda *_args: (None, None)

        self.assertFalse(watcher._rumeli2_candidate(frame))
        self.assertEqual(watcher._rumeli2_candidate_error, "rumeli2_referans_yok")

    def test_ocr_job_does_not_block_the_vision_caller(self):
        watcher = self._watcher()
        watcher._rumeli2_read_digits = lambda *_args, **_kwargs: "123456"
        crop = np.zeros((16, 48, 3), dtype=np.uint8)
        mask = np.zeros((48, 192), dtype=np.uint8)
        candidate = {
            "question_crop": crop,
            "question_mask": mask,
            "option_crops": [crop.copy() for _ in range(4)],
            "option_masks": [mask.copy() for _ in range(4)],
        }
        original_decision = watcher._rumeli2_ocr_decision
        watcher._rumeli2_ocr_decision = lambda value: (time.sleep(0.15), original_decision(value))[1]

        started = time.perf_counter()
        self.assertTrue(watcher._rumeli2_start_ocr_job(candidate))
        self.assertLess(time.perf_counter() - started, 0.05)
        watcher._rumeli2_job_thread.join(timeout=1.0)
        self.assertIsNotNone(watcher._rumeli2_take_ocr_result())

    def test_single_unread_option_needs_two_matching_elimination_votes(self):
        watcher = self._watcher()
        question = np.zeros((8, 8, 3), dtype=np.uint8)
        options = [np.full_like(question, value) for value in (1, 2, 3, 4)]
        masks = [np.full((8, 8), value, dtype=np.uint8) for value in (1, 2, 3, 4)]
        readings = {
            id(question): "299170",
            id(options[0]): "171307",
            id(options[1]): "340242",
            id(options[2]): "",
            id(options[3]): "541685",
        }
        shape_scores = {id(mask): score for mask, score in zip(masks, (0.25, 0.29, 0.40, 0.24))}
        watcher._rumeli2_read_digits = lambda crop, **_kwargs: readings[id(crop)]
        watcher._rumeli2_mask_similarity = lambda _question, mask: shape_scores[id(mask)]
        candidate = {
            "question_crop": question,
            "question_mask": np.zeros((8, 8), dtype=np.uint8),
            "option_crops": options,
            "option_masks": masks,
        }

        first = watcher._rumeli2_ocr_decision(candidate)
        second = watcher._rumeli2_ocr_decision(candidate)

        self.assertIsNone(first["selected"])
        self.assertEqual(first["elimination_streak"], 1)
        self.assertEqual(second["selected"], 2)
        self.assertEqual(second["reason"], "iki-kare-eleme+sekil")

    def test_unique_one_digit_error_needs_two_matching_votes(self):
        watcher = self._watcher()
        question = np.zeros((8, 8, 3), dtype=np.uint8)
        options = [np.full_like(question, value) for value in (1, 2, 3, 4)]
        masks = [np.full((8, 8), value, dtype=np.uint8) for value in (1, 2, 3, 4)]
        readings = {
            id(question): "660956",
            id(options[0]): "808017",
            id(options[1]): "560956",
            id(options[2]): "478628",
            id(options[3]): "",
        }
        shape_scores = {id(mask): score for mask, score in zip(masks, (0.39, 0.32, 0.30, 0.29))}
        watcher._rumeli2_read_digits = lambda crop, **_kwargs: readings[id(crop)]
        watcher._rumeli2_mask_similarity = lambda _question, mask: shape_scores[id(mask)]
        candidate = {
            "question_crop": question,
            "question_mask": np.zeros((8, 8), dtype=np.uint8),
            "option_crops": options,
            "option_masks": masks,
        }

        first = watcher._rumeli2_ocr_decision(candidate)
        second = watcher._rumeli2_ocr_decision(candidate)

        self.assertIsNone(first["selected"])
        self.assertEqual(first["near_match_streak"], 1)
        self.assertEqual(second["selected"], 1)
        self.assertEqual(second["reason"], "iki-kare-tek-hane+sekil")

    def test_recorded_extra_digit_case_needs_two_candidate_votes(self):
        watcher = self._watcher()
        question = np.zeros((8, 8, 3), dtype=np.uint8)
        options = [np.full_like(question, value) for value in (1, 2, 3, 4)]
        masks = [np.full((8, 8), value, dtype=np.uint8) for value in (1, 2, 3, 4)]
        one_round = [
            ["186287"], [], ["86", "84"],
            ["802305"], ["217412"], [""],
            ["1862871"], ["1", "421"], ["1"],
            ["125273"], ["1423"], ["4", "2"],
            ["544033"], ["12"], ["11", "6"],
        ]
        watcher._reader = type(
            "Reader",
            (),
            {
                "__init__": lambda self: setattr(self, "outputs", iter(one_round * 2)),
                "readtext": lambda self, *_args, **_kwargs: next(self.outputs),
            },
        )()
        watcher._rumeli2_digit_mask = lambda *_args, **_kwargs: np.ones((8, 8), dtype=np.uint8)
        shape_scores = {id(mask): score for mask, score in zip(masks, (0.3193, 0.4005, 0.3702, 0.2875))}
        watcher._rumeli2_mask_similarity = lambda _question, mask: shape_scores[id(mask)]
        candidate = {
            "question_crop": question,
            "question_mask": np.zeros((8, 8), dtype=np.uint8),
            "option_crops": options,
            "option_masks": masks,
        }

        first = watcher._rumeli2_ocr_decision(candidate)
        second = watcher._rumeli2_ocr_decision(candidate)

        self.assertIsNone(first["selected"])
        self.assertEqual(first["candidate_match_streak"], 1)
        self.assertEqual(first["option_candidates"][1], ["186287", "862871"])
        self.assertEqual(second["selected"], 1)
        self.assertEqual(second["reason"], "iki-kare-aday-ocr+sekil")

    def test_candidate_ocr_refuses_target_found_in_multiple_options(self):
        selected = CaptchaWatcher._rumeli2_candidate_ocr_match(
            "186287",
            [["802305"], ["186287", "862871"], ["186287"], ["544033"]],
            [0.31, 0.40, 0.37, 0.28],
        )
        self.assertIsNone(selected)

    def test_candidate_confirmation_survives_realistic_ocr_delay(self):
        watcher = self._watcher()
        options = [["802305"], ["186287", "862871"], ["125273"], ["544033"]]
        scores = [0.3193, 0.4005, 0.3702, 0.2875]

        with patch(
            "src.phantom.captcha.solver.time.monotonic",
            side_effect=(100.0, 110.0),
        ):
            first = watcher._rumeli2_confirm_candidate_match("186287", options, scores)
            second = watcher._rumeli2_confirm_candidate_match("186287", options, scores)

        self.assertEqual(first, (None, 1))
        self.assertEqual(second, (1, 2))

    def test_one_digit_fallback_refuses_ambiguous_candidates(self):
        selected = CaptchaWatcher._rumeli2_near_match_candidate(
            "660956",
            ["560956", "680956", "478628", "314008"],
            [0.36, 0.35, 0.30, 0.29],
        )
        self.assertIsNone(selected)

    def test_one_digit_fallback_refuses_close_competing_option(self):
        selected = CaptchaWatcher._rumeli2_near_match_candidate(
            "660956",
            ["560956", "660996", "478628", "314008"],
            [0.36, 0.34, 0.30, 0.29],
        )
        self.assertIsNone(selected)

    def test_elimination_refuses_unread_option_that_is_not_shape_winner(self):
        selected = CaptchaWatcher._rumeli2_elimination_candidate(
            "352839",
            ["441604", "", "552459", "332454"],
            [0.47, 0.43, 0.48, 0.49],
        )
        self.assertIsNone(selected)

    def test_uncertain_ocr_saves_panel_and_decision_evidence(self):
        watcher = self._watcher()
        watcher._log = lambda *_args: None
        candidate = {
            "panel_crop": np.full((80, 120, 3), 32, dtype=np.uint8),
            "panel_score": 0.99,
            "header_score": 1.0,
        }
        result = {
            "question_digits": "299170",
            "option_digits": ["171307", "340242", "", "541685"],
            "scores": [0.25, 0.29, 0.40, 0.24],
            "detail": "hedef=299170 eleme=1/2",
        }

        with tempfile.TemporaryDirectory() as folder:
            with patch("src.phantom.captcha.solver._RUMELI2_EVIDENCE_DIR", folder):
                watcher._rumeli2_save_uncertain_evidence(candidate, result)
            self.assertEqual(len(list(Path(folder).glob("*.png"))), 1)
            self.assertEqual(len(list(Path(folder).glob("*.json"))), 1)

    def test_panel_similarity_rejects_unrelated_scene(self):
        reference = np.full((120, 180), 28, dtype=np.uint8)
        cv2.rectangle(reference, (2, 2), (177, 117), 95, 2)
        cv2.putText(reference, "Lutfen dogrulayin", (18, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.42, 180, 1)
        mask = np.full(reference.shape, 255, dtype=np.uint8)
        unrelated = np.full((120, 180), 80, dtype=np.uint8)
        cv2.line(unrelated, (0, 0), (179, 119), 220, 4)

        same_score = CaptchaWatcher._rumeli2_panel_similarity(
            reference,
            mask,
            reference,
            mask,
        )
        unrelated_score = CaptchaWatcher._rumeli2_panel_similarity(
            unrelated,
            mask,
            reference,
            mask,
        )

        self.assertGreater(same_score, 0.99)
        self.assertLess(unrelated_score, 0.50)


if __name__ == "__main__":
    unittest.main()
