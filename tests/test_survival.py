import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from src.phantom.app.main import ActionThread, State
from src.phantom.vision.survival import detect_death_menu, remember_failed_target, filter_failed_targets


class SurvivalTests(unittest.TestCase):
    def test_user_images_and_missed_1947_frames(self):
        with np.load(Path(__file__).with_name("death_menu_user_replay.npz")) as samples:
            for index, crop in enumerate(samples["frames"]):
                with self.subTest(frame=index):
                    frame = np.zeros((840, 1296), dtype=np.uint8)
                    frame[:320, :400] = crop
                    result = detect_death_menu(frame)
                    self.assertTrue(result["visible"], result)
                    self.assertTrue(100 <= result["button"][1] <= 130)

    def test_only_one_button_or_wrong_order_never_matches(self):
        path = Path(__file__).resolve().parents[1] / "templates" / "revive_buttons_native.png"
        tpl = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), 0)
        for mode in ("upper_only", "lower_only", "swapped", "wrong_gap"):
            with self.subTest(mode=mode):
                frame = np.zeros((840, 1296), dtype=np.uint8)
                upper, lower = tpl[22:43, 12:188], tpl[52:73, 12:188]
                if mode != "lower_only":
                    frame[100:121, 60:236] = lower if mode == "swapped" else upper
                if mode != "upper_only":
                    y = 180 if mode == "wrong_gap" else 130
                    frame[y:y+21, 60:236] = upper if mode == "swapped" else lower
                self.assertFalse(detect_death_menu(frame)["visible"])

    def test_recorded_menu_variants_and_normal_game_frames(self):
        path = Path(__file__).with_name("death_menu_replay.npz")
        with np.load(path) as samples:
            for index, (crop, expected) in enumerate(zip(samples["frames"], samples["expected"])):
                with self.subTest(frame=index):
                    frame = np.zeros((840, 1296), dtype=np.uint8)
                    frame[:320, :400] = crop
                    result = detect_death_menu(frame)
                    self.assertEqual(result["visible"], bool(expected))
                    if expected:
                        self.assertTrue(90 <= result["button"][1] <= 125)

    def test_death_button_points_to_upper_button_only(self):
        template_path = Path(__file__).resolve().parents[1] / "templates" / "revive_buttons_native.png"
        tpl = cv2.imdecode(np.fromfile(str(template_path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        frame = np.zeros((840, 1296), dtype=np.uint8)
        frame[80:80+tpl.shape[0], 60:60+tpl.shape[1]] = tpl
        result = detect_death_menu(frame)
        self.assertTrue(result["visible"])
        self.assertTrue(60 < result["button"][0] < 254)
        self.assertTrue(100 < result["button"][1] < 132)
        self.assertFalse(detect_death_menu(np.zeros_like(frame))["visible"])

    def test_failed_targets_accumulate_expire_and_are_bounded(self):
        history = []
        remember_failed_target(history, (100, 100), 100)
        remember_failed_target(history, (300, 100), 110)
        self.assertEqual(filter_failed_targets([(100, 100), (300, 100), (600, 100)], history, 120), [(600, 100)])
        self.assertEqual(filter_failed_targets([(100, 100), (300, 100)], history, 161), [(100, 100)])
        for i in range(20):
            remember_failed_target(history, (i * 100, 500), 180)
        self.assertEqual(len(history), 8)

    def action(self):
        action = ActionThread(None, State())
        action.st.aktif = True
        action._init("w")
        action._start_target_generation = mock.Mock()
        action._mount_after_revive = mock.Mock(return_value=True)
        action._restore_revive_buffs = mock.Mock(return_value=True)
        action._prepare_revive_buffs = mock.Mock(return_value=True)
        return action

    @mock.patch("src.phantom.app.main.log_event")
    def test_death_blocks_normal_input_and_old_frames_do_not_confirm(self, *_):
        action = self.action()
        action.st.life_data = {"w": {"visible": True, "ts": 100, "hwnd": 123}}
        with mock.patch("src.phantom.app.main.time.time", return_value=100):
            self.assertTrue(action._handle_player_life("w", 123, 1))
            self.assertTrue(action._handle_player_life("w", 123, 1))
        self.assertEqual(action._revive_state["w"]["seen"], 1)
        self.assertTrue(action._input_blocked("w"))
        self.assertFalse(action._input_blocked("w", allow_revive=True))
        action.st.captcha_global_active = True
        self.assertTrue(action._input_blocked("w", allow_revive=True))

    @mock.patch("src.phantom.app.main.log_event")
    def test_revive_requires_three_fresh_alive_frames_and_resets_target(self, *_):
        action = self.action()
        action._revive_state = {"w": {"seen": 2, "absent": 0, "tries": 1, "next": 100, "last": 99}}
        action._combat_progress["w"] = {"hp_floor": .2}
        action.st.target_memory["w"] = {"confirmed": True}
        for ts in (100, 101):
            action.st.life_data = {"w": {"visible": False, "own_hp": True, "foreground": True, "ts": ts, "hwnd": 123}}
            with mock.patch("src.phantom.app.main.time.time", return_value=ts):
                action._handle_player_life("w", 123, 1)
            self.assertIn("w", action._revive_state)
        action.st.life_data["w"]["ts"] = 102
        with mock.patch("src.phantom.app.main.time.time", return_value=102):
            action._handle_player_life("w", 123, 1)
        self.assertNotIn("w", action._revive_state)
        self.assertNotIn("w", action._combat_progress)
        self.assertNotIn("w", action.st.target_memory)
        self.assertEqual(action.dur["w"], "ARANIYOR")
        action._mount_after_revive.assert_called_once_with("w", 123)
        action._restore_revive_buffs.assert_called_once()
        self.assertFalse(action._buff_needs_remount["w"])
        self.assertGreater(action._buff_next_t["w"], 102)

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.pencere_odakla", return_value=True)
    @mock.patch("src.phantom.app.main.win32gui.IsWindow", return_value=True)
    def test_occluded_window_cannot_confirm_respawn(self, *_):
        action = self.action()
        action._refresh_revive_life = mock.Mock(return_value=None)
        action._revive_state = {"w": {"seen": 2, "absent": 2, "tries": 1, "next": 100, "last": 99}}
        action.st.life_data = {"w": {"visible": False, "own_hp": True, "foreground": False, "ts": 100, "hwnd": 123}}
        with mock.patch("src.phantom.app.main.time.time", return_value=100):
            self.assertTrue(action._handle_player_life("w", 123, 1))
        self.assertIn("w", action._revive_state)
        self.assertEqual(action._revive_state["w"]["absent"], 2)

    def test_background_frame_preserves_center_timer_and_alive_progress(self):
        action = self.action()
        action._refresh_revive_life = mock.Mock()
        pending = {"seen": 2, "absent": 2, "tries": 1, "next": 110,
                   "last": 99, "cursor_centered": True}
        action._revive_state = {"w": pending}
        action.st.life_data = {"w": {"visible": False, "own_hp": False,
            "foreground": False, "ts": 100, "hwnd": 123}}
        with mock.patch("src.phantom.app.main.time.time", return_value=100):
            action._handle_player_life("w", 123, 1)
        self.assertTrue(pending["cursor_centered"])
        self.assertEqual((pending["next"], pending["absent"]), (110, 2))
        action._refresh_revive_life.assert_not_called()

    @mock.patch("src.phantom.app.main.log_event")
    def test_focused_alive_burst_finishes_respawn_despite_background_rounds(self, *_):
        action = self.action()
        action._revive_state = {"w": {"seen": 2, "absent": 0, "tries": 1, "next": 100, "last": 99}}
        action.st.life_data = {"w": {"visible": False, "own_hp": True,
            "foreground": False, "ts": 100, "hwnd": 123}}
        action._refresh_revive_life = mock.Mock(return_value={"visible": False,
            "own_hp": True, "foreground": True, "ts": 100.6, "hwnd": 123, "confirmed_alive": True})
        with mock.patch("src.phantom.app.main.time.time", return_value=100):
            action._handle_player_life("w", 123, 1)
        self.assertNotIn("w", action._revive_state)
        action._prepare_revive_buffs.assert_called_once()
        action._restore_revive_buffs.assert_called_once()
        action._mount_after_revive.assert_called_once()
        self.assertEqual(action.dur["w"], "ARANIYOR")

    def test_refocused_death_does_not_erase_center_checkpoint(self):
        action = self.action()
        pending = {"seen": 0, "absent": 0, "tries": 0, "next": 100,
                   "last": 99, "cursor_centered": True}
        action._revive_state = {"w": pending}
        action.st.life_data = {"w": {"visible": False, "foreground": False, "ts": 100, "hwnd": 123}}
        action._refresh_revive_life = mock.Mock(return_value={"visible": True,
            "foreground": True, "ts": 100.2, "hwnd": 123})
        with mock.patch("src.phantom.app.main.time.time", return_value=100):
            action._handle_player_life("w", 123, 1)
        self.assertTrue(pending["cursor_centered"])
        self.assertEqual(pending["next"], 100)

    @mock.patch("src.phantom.app.main.own_hp_visible", return_value=True)
    @mock.patch("src.phantom.app.main.detect_death_menu")
    @mock.patch("src.phantom.app.main.mss.mss")
    @mock.patch("src.phantom.app.main.win32gui.GetWindowRect", return_value=(0, 0, 100, 100))
    @mock.patch("src.phantom.app.main.win32gui.GetForegroundWindow", return_value=123)
    @mock.patch("src.phantom.app.main.win32gui.IsWindow", return_value=True)
    @mock.patch("src.phantom.app.main.pencere_odakla", return_value=True)
    def test_focused_capture_requires_three_alive_frames_and_aborts_on_focus_loss(self, focus, valid, foreground, rect, capture, detect, hp):
        action = self.action()
        action._stop_event = mock.Mock()
        action._stop_event.is_set.return_value = False
        action._stop_event.wait.return_value = False
        grab = capture.return_value.__enter__.return_value.grab
        grab.return_value = np.zeros((100, 100, 4), dtype=np.uint8)
        detect.side_effect = lambda frame: {"visible": False}
        result = action._refresh_revive_life("w", 123)
        self.assertTrue(result["confirmed_alive"])
        self.assertEqual(grab.call_count, 3)
        grab.reset_mock()
        detect.side_effect = lambda frame: {"visible": True}
        self.assertFalse(action._refresh_revive_life("w", 123)["confirmed_alive"])
        self.assertEqual(grab.call_count, 1)
        grab.reset_mock()
        foreground.return_value = 456
        self.assertIsNone(action._refresh_revive_life("w", 123))
        grab.assert_not_called()

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.sol_tik_hw")
    def test_retry_waits_ten_seconds_even_after_three_attempts(self, click, *_):
        action = self.action()
        action._revive_state = {"w": {"seen": 2, "absent": 0, "tries": 3, "next": 103, "last": 99}}
        action.st.life_data = {"w": {"visible": True, "ts": 100, "hwnd": 123}}
        with mock.patch("src.phantom.app.main.time.time", return_value=100):
            action._handle_player_life("w", 123, 1)
        click.assert_not_called()
        self.assertEqual(action._revive_state["w"]["tries"], 3)

    @mock.patch("src.phantom.app.main.ActionThread._wait_revive_hover", return_value=True)
    @mock.patch("src.phantom.app.main.win32api.SetCursorPos")
    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.sol_tik_hw", return_value="sendinput")
    @mock.patch("src.phantom.app.main.detect_death_menu", return_value={"visible": True, "button": (150, 110)})
    @mock.patch("src.phantom.app.main.mss.mss")
    @mock.patch("src.phantom.app.main.win32gui.GetWindowRect", return_value=(1000, 500, 2296, 1340))
    @mock.patch("src.phantom.app.main.win32gui.GetForegroundWindow", return_value=123)
    @mock.patch("src.phantom.app.main.win32gui.IsWindow", return_value=True)
    @mock.patch("src.phantom.app.main.pencere_odakla", return_value=True)
    def test_click_is_revalidated_and_routed_to_upper_button(self, focus, valid, foreground, rect, capture, detect, click, log, move, hover):
        action = self.action()
        action._stop_event = mock.Mock()
        action._stop_event.is_set.return_value = False
        action._stop_event.wait.return_value = False
        capture.return_value.__enter__.return_value.grab.return_value = np.zeros((840, 1296, 4), dtype=np.uint8)
        action._move_revive_cursor = mock.Mock(return_value=True)
        action._wiggle_revive_cursor = mock.Mock(return_value=True)
        action._revive_state = {"w": {"seen": 1, "absent": 0, "tries": 0, "next": 100, "last": 99}}
        action.st.life_data = {"w": {"visible": True, "ts": 100, "hwnd": 123}}
        for ts, expected_clicks in ((100, 0), (103, 0), (109.9, 0), (110, 1),
                                    (111, 1), (120.9, 1), (121, 2)):
            action.st.life_data["w"]["ts"] = ts
            with mock.patch("src.phantom.app.main.time.time", return_value=ts):
                action._handle_player_life("w", 123, 1)
            self.assertEqual(action._wiggle_revive_cursor.call_count, expected_clicks)
        self.assertEqual(move.call_args_list, [mock.call((1648, 920))] * 2)
        self.assertEqual(action._move_revive_cursor.call_args_list, [mock.call("w", 123, (1150, 610))] * 2)
        self.assertEqual(hover.call_args_list, [mock.call("w", 123, (1150, 610))] * 2)
        self.assertEqual(action._wiggle_revive_cursor.call_args_list, [mock.call("w", 123, (1150, 610))] * 2)
        click.assert_not_called()  # Clicks now belong to the movement helper.
        self.assertEqual(action._revive_state["w"]["tries"], 2)
        # Every center and every click was checked against a fresh capture.
        self.assertEqual(detect.call_count, 6)
        self.assertNotIn("cursor_centered", action._revive_state["w"])

    @mock.patch("src.phantom.app.main.pencere_odakla", return_value=True)
    @mock.patch("src.phantom.app.main.win32gui.IsWindow", return_value=True)
    @mock.patch("src.phantom.app.main.keyboard")
    def test_mount_sends_one_ctrl_g_and_releases_on_stop(self, keys, *_):
        action = ActionThread(None, State())
        action.st.aktif = True
        action._stop_event = mock.Mock()
        action._stop_event.is_set.return_value = False
        action._stop_event.wait.return_value = True
        action._revive_state = {"w": {}}
        self.assertTrue(action._mount_after_revive("w", 123))
        self.assertEqual(keys.press.call_args_list, [mock.call("ctrl"), mock.call("g")])
        self.assertEqual(keys.release.call_args_list, [mock.call("g"), mock.call("ctrl")])

    @mock.patch("src.phantom.app.main.log_event")
    def test_missing_hp_reaches_recovery_instead_of_five_second_abandon(self, *_):
        action = self.action()
        action._target_generation["w"] = 1
        action._begin_approach("w", 100)
        action._run_approach_recovery = mock.Mock(return_value=True)
        action._abandon_approach_target = mock.Mock()
        for ts in (100, 105, 107.9, 108):
            with mock.patch("src.phantom.app.main.time.time", return_value=ts):
                action._handle_dogrulama("w", False, None, True, False, True, {}, 123,
                    target_generation=1, sample_ts=ts, client_idx=1, hp_sample_valid=False)
        action._abandon_approach_target.assert_not_called()
        action._run_approach_recovery.assert_called_once_with("w", 123, 1)


if __name__ == "__main__":
    unittest.main()
