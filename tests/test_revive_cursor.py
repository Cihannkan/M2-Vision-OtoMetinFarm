import unittest
from unittest import mock
from src.phantom.app.main import ActionThread, State


class ReviveCursorTests(unittest.TestCase):
    def test_smooth_path_and_safety_interruptions(self):
        for case in ("normal", "stop", "focus", "pause"):
            with self.subTest(case=case):
                action = ActionThread(None, State())
                action.st.aktif = True
                action.st.global_pause_active = case == "pause"
                action._stop_event = mock.Mock()
                action._stop_event.is_set.return_value = False
                action._stop_event.wait.return_value = case == "stop"
                with mock.patch("src.phantom.app.main.win32api.GetCursorPos", return_value=(1600, 900)), \
                     mock.patch("src.phantom.app.main.win32api.SetCursorPos") as move, \
                     mock.patch("src.phantom.app.main.win32gui.GetForegroundWindow", return_value=9 if case == "focus" else 123):
                    self.assertEqual(action._move_revive_cursor("w", 123, (1100, 600)), case == "normal")
                if case == "normal":
                    points = [call.args[0] for call in move.call_args_list]
                    self.assertEqual(len(points), 30)
                    self.assertEqual(points[-1], (1100, 600))
                    self.assertNotEqual(points[0], points[-1])
                    self.assertTrue(all(a[0] >= b[0] and a[1] >= b[1] for a, b in zip(points, points[1:])))
                    self.assertEqual(action._stop_event.wait.call_args_list, [mock.call(.02)] * 30)
                else:
                    move.assert_not_called()
