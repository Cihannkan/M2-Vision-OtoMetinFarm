import unittest
from unittest import mock

from src.phantom.app.main import ActionThread, State


class SearchSequenceTests(unittest.TestCase):
    def make_action(self):
        action = ActionThread(None, State())
        action.st.aktif = True
        action._stop_event = mock.Mock()
        action._stop_event.is_set.return_value = False
        action._stop_event.wait.return_value = False
        action._hold_recovery_key = mock.Mock(return_value=True)
        return action

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.time.time", return_value=100.0)
    def test_no_target_runs_all_six_steps_and_resets_search_timer(self, *_):
        action = self.make_action()
        self.assertTrue(action._anti_sucuk_araniyor_manevra("w", 123, 100))
        self.assertEqual(action._hold_recovery_key.call_args_list, [
            mock.call("w", key, 1.0, 123) for key in ("q", "q", "q", "q", "g", "t")
        ])
        self.assertEqual(action._araniyor_baslat_t["w"], 100)
        self.assertFalse(action._s_basmis["w"])
        self.assertEqual(action._stop_event.wait.call_args_list, [mock.call(0.4)] * 6)

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.time.time", return_value=100.0)
    def test_target_at_each_step_skips_remaining_keys(self, *_):
        for found_at in range(1, 7):
            with self.subTest(found_at=found_at):
                action = self.make_action()
                def hold(*args):
                    if action._hold_recovery_key.call_count == found_at:
                        action.st.wdata["w"] = {
                            "publish_ts": 100, "merkezler": [(100, 100)],
                            "ekran_merkez": (0, 0),
                        }
                    return True
                action._hold_recovery_key.side_effect = hold
                self.assertTrue(action._anti_sucuk_araniyor_manevra("w", 123, 100))
                self.assertEqual(action._hold_recovery_key.call_count, found_at)

    @mock.patch("src.phantom.app.main.log_event")
    def test_interrupted_g_never_sends_t(self, *_):
        action = self.make_action()
        action._hold_recovery_key.side_effect = [True, True, True, True, False]
        self.assertFalse(action._anti_sucuk_araniyor_manevra("w", 123, 100))
        self.assertEqual(action._hold_recovery_key.call_count, 5)
        self.assertFalse(action._s_basmis["w"])


if __name__ == "__main__":
    unittest.main()
