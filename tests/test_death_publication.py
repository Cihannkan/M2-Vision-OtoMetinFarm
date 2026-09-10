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
                cfg.client.side_effect = lambda ci: {"aktif": ci in clients, "pencere": f"Game (ID: {ci})"}
                vision = VisionThread(cfg, state)
                vision._stop_event = mock.Mock()
                vision._stop_event.is_set.side_effect = [False, True]
                vision._clear_orphaned_input_locks = mock.Mock()
                vision._watch_global_pause = mock.Mock()
                vision._warn_duplicate_client_windows = mock.Mock()
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
