import unittest
from unittest import mock
from src.phantom.app.main import ActionThread, State


class ReviveHoverTests(unittest.TestCase):
    def test_hover_waits_two_seconds_and_aborts_on_interference(self):
        for case in ("normal", "stop", "focus", "cursor", "pause"):
            with self.subTest(case=case):
                action = ActionThread(None, State())
                action.st.aktif = True
                action.st.global_pause_active = case == "pause"
                action._stop_event = mock.Mock()
                action._stop_event.is_set.return_value = False
                action._stop_event.wait.return_value = case == "stop"
                with mock.patch("src.phantom.app.main.win32gui.GetForegroundWindow", return_value=9 if case == "focus" else 123), \
                     mock.patch("src.phantom.app.main.win32api.GetCursorPos", return_value=(0, 0) if case == "cursor" else (150, 110)):
                    result = action._wait_revive_hover("w", 123, (150, 110))
                self.assertEqual(result, case == "normal")
                if case == "normal":
                    self.assertEqual(action._stop_event.wait.call_args_list, [mock.call(.05)] * 40)
