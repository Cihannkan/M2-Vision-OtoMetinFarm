import unittest
from unittest import mock
import numpy as np
from src.phantom.app.main import State, VisionThread


class DeathPublicationTests(unittest.TestCase):
    def test_death_result_survives_complete_vision_round(self):
        for clients in ((2,), (1, 2, 3)):
            with self.subTest(clients=clients):
                state = State()
                state.aktif = True
                cfg = mock.Mock()
                cfg.client.side_effect = lambda ci: {
                    "aktif": ci in clients,
                    "pencere": f"Game (ID: {ci})",
                    "captcha": False,
                }
                vision = VisionThread(cfg, state)
                vision._stop_event = mock.Mock()
                vision._stop_event.is_set.side_effect = [False, True]
                vision._clear_orphaned_input_locks = mock.Mock()
                vision._watch_global_pause = mock.Mock()
                vision._warn_duplicate_client_windows = mock.Mock()
                vision._measure_scene_motion = mock.Mock()
                with mock.patch("src.phantom.app.main.preferred_backend", return_value="cpu"), \
                     mock.patch("src.phantom.app.main.log_event"), \
                     mock.patch("src.phantom.app.main.time.sleep"), \
                     mock.patch("src.phantom.app.main.mss.mss") as capture, \
                     mock.patch("src.phantom.app.main.win32gui.GetWindowRect", return_value=(0, 0, 1296, 840)), \
                     mock.patch("src.phantom.app.main.win32gui.GetForegroundWindow", return_value=2), \
                     mock.patch("src.phantom.app.main.detect_death_menu", side_effect=lambda _: {"visible": True}):
                    capture.return_value.monitors = [{}, {}]
                    capture.return_value.grab.return_value = np.zeros((840, 1296, 4), dtype=np.uint8)
                    vision.run()
                for ci in clients:
                    key = f"Game (ID: {ci})"
                    self.assertIn(key, state.wdata)
                    self.assertTrue(state.life_data[key]["visible"])
                    self.assertGreater(state.wdata[key]["ts"], 0)
                    self.assertEqual(state.wdata[key]["client_idx"], ci)
                vision._measure_scene_motion.assert_not_called()

    def test_captcha_is_checked_when_death_menu_is_visible_in_same_frame(self):
        state = State()
        state.aktif = True
        cfg = mock.Mock()
        cfg.client.side_effect = lambda ci: {
            "aktif": ci == 2,
            "pencere": f"Game (ID: {ci})",
            "captcha": True,
            "captcha_rumeli2": True,
            "debug_on": False,
        }
        vision = VisionThread(cfg, state)
        vision._stop_event = mock.Mock()
        vision._stop_event.is_set.side_effect = [False, True]
        vision._clear_orphaned_input_locks = mock.Mock()
        vision._watch_global_pause = mock.Mock()
        vision._warn_duplicate_client_windows = mock.Mock()
        vision._measure_scene_motion = mock.Mock()

        watcher = mock.Mock()
        watcher.hazir = True
        watcher.last_status = "dialog_yok"
        watcher.last_detail = ""

        def solve(*_args):
            watcher.last_status = "tiklandi"
            watcher.last_detail = "rumeli2:2:828766"
            return True

        watcher.kontrol_et.side_effect = solve
        vision.captcha_w[2] = watcher

        with mock.patch("src.phantom.app.main.preferred_backend", return_value="cpu"), \
             mock.patch("src.phantom.app.main.log_event"), \
             mock.patch("src.phantom.app.main.time.sleep"), \
             mock.patch("src.phantom.app.main.mss.mss") as capture, \
             mock.patch("src.phantom.app.main.win32gui.GetWindowRect", return_value=(0, 0, 1296, 840)), \
             mock.patch("src.phantom.app.main.win32gui.GetForegroundWindow", return_value=2), \
             mock.patch("src.phantom.app.main.detect_death_menu", return_value={"visible": True}):
            capture.return_value.monitors = [{}, {}]
            capture.return_value.grab.return_value = np.zeros((840, 1296, 4), dtype=np.uint8)
            vision.run()

        key = "Game (ID: 2)"
        watcher.kontrol_et.assert_called_once()
        vision._measure_scene_motion.assert_not_called()
        self.assertTrue(state.life_data[key]["visible"])
        self.assertTrue(state.captcha_state[key])
        self.assertEqual(state.captcha_global_owner, key)
