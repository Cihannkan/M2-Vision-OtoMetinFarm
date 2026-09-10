import unittest
from unittest import mock

from src.phantom.app.main import ActionThread, State, VisionThread


class WindowLockTests(unittest.TestCase):
    def setUp(self):
        self.owner = "Rumeli2 (ID: 123)"
        self.other = "Rumeli2 (ID: 456)"
        self.state = State()
        self.state.aktif = True
        self.vision = VisionThread(mock.Mock(), self.state)
        self.vision._active_client_pks = mock.Mock(return_value=[self.owner, self.other])
        self.state.captcha_global_active = True
        self.state.captcha_global_owner = self.owner
        self.state.captcha_block[self.owner] = True
        self.action = ActionThread(None, self.state)
        self.probe = mock.patch("src.phantom.app.main.win32gui.IsWindow", return_value=False).start()
        mock.patch("src.phantom.app.main.log_event").start()
        self.addCleanup(mock.patch.stopall)

    def test_closed_owner_unblocks_other_client(self):
        self.assertTrue(self.action._input_blocked(self.other))
        self.vision._clear_orphaned_input_locks()
        self.assertFalse(self.state.captcha_global_active)
        self.assertIsNone(self.state.captcha_global_owner)
        self.assertFalse(self.action._input_blocked(self.other))

    def test_live_owner_keeps_lock_even_if_minimized(self):
        self.probe.return_value = True
        self.vision._clear_orphaned_input_locks()
        self.assertTrue(self.action._input_blocked(self.other))

    def test_probe_error_preserves_lock(self):
        self.probe.side_effect = OSError("probe failed")
        self.vision._clear_orphaned_input_locks()
        self.assertTrue(self.state.captcha_global_active)

    def test_unparseable_owner_preserves_lock(self):
        self.state.captcha_global_owner = "unknown"
        self.vision._active_client_pks.return_value.append("unknown")
        self.vision._clear_orphaned_input_locks()
        self.assertTrue(self.state.captcha_global_active)
        self.probe.assert_not_called()

    def test_removed_owner_clears_lock(self):
        self.vision._active_client_pks.return_value = [self.other]
        self.vision._clear_orphaned_input_locks()
        self.assertFalse(self.state.captcha_global_active)
        self.probe.assert_not_called()

    def test_other_clients_local_lock_is_preserved(self):
        self.state.captcha_block[self.other] = True
        self.vision._clear_orphaned_input_locks()
        self.assertTrue(self.action._input_blocked(self.other))

    def test_closed_message_owner_is_cleared(self):
        self.state.message_global_active = True
        self.state.message_global_owner = self.owner
        self.vision._clear_orphaned_input_locks()
        self.assertFalse(self.state.message_global_active)
        self.assertFalse(self.action._input_blocked(self.other))

    def test_live_message_owner_survives_other_owner_closure(self):
        self.state.message_global_active = True
        self.state.message_global_owner = self.other
        self.probe.side_effect = lambda hwnd: hwnd == 456
        self.vision._clear_orphaned_input_locks()
        self.assertFalse(self.state.captcha_global_active)
        self.assertTrue(self.state.message_global_active)
        self.assertTrue(self.action._input_blocked(self.other))

    def test_bot_stop_is_preserved(self):
        self.state.aktif = False
        self.vision._clear_orphaned_input_locks()
        self.assertTrue(self.action._input_blocked(self.other))


if __name__ == "__main__":
    unittest.main()
