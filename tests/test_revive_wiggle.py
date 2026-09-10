import unittest
from unittest import mock
from src.phantom.app.main import ActionThread, State


class ReviveWiggleTests(unittest.TestCase):
    def test_right_left_center_uses_smooth_movement(self):
        action = ActionThread(None, State())
        action._move_revive_cursor = mock.Mock(return_value=True)
        self.assertTrue(action._wiggle_revive_cursor("w", 123, (150, 110)))
        self.assertEqual(action._move_revive_cursor.call_args_list, [
            mock.call("w", 123, (158, 110), click_midway=True), mock.call("w", 123, (142, 110), click_midway=True),
            mock.call("w", 123, (150, 110), click_midway=False),
        ])

    def test_interruption_stops_remaining_movement(self):
        action = ActionThread(None, State())
        action._move_revive_cursor = mock.Mock(side_effect=[True, False])
        self.assertFalse(action._wiggle_revive_cursor("w", 123, (150, 110)))
        self.assertEqual(action._move_revive_cursor.call_count, 2)
