import unittest
from unittest import mock
from src.phantom.app.main import ActionThread, State


class ReviveBuffTests(unittest.TestCase):
    def setUp(self):
        self.action = ActionThread(None, State())
        self.action.st.aktif = True
        self.action._init("w")
        self.action.st.life_data = {"w": {"visible": False, "own_hp": True,
            "foreground": True, "ts": 100, "hwnd": 123}}
        self.pending = {"seen": 2, "absent": 2, "tries": 1, "next": 100, "last": 99}
        self.action._revive_state = {"w": self.pending}
        self.action._start_target_generation = mock.Mock()
        self.action._wait_revive_buff = mock.Mock(return_value=True)
        self.keys = mock.patch("src.phantom.app.main.keyboard").start()
        mock.patch("src.phantom.app.main.time.time", return_value=100).start()
        mock.patch("src.phantom.app.main.pencere_odakla", return_value=True).start()
        mock.patch("src.phantom.app.main.win32gui.IsWindow", return_value=True).start()
        mock.patch("src.phantom.app.main.win32gui.GetForegroundWindow", return_value=123).start()
        mock.patch("src.phantom.app.main.log_event").start()
        self.addCleanup(mock.patch.stopall)

    def test_move_dismount_buffs_and_final_mount_order(self):
        self.action._stop_event = mock.Mock()
        self.action._stop_event.is_set.return_value = False
        self.action._handle_player_life("w", 123, 2)
        self.assertEqual(self.keys.press.call_args_list, [mock.call(k) for k in
            ("d", "ctrl", "g", "alt", "1", "2", "3", "4", "f1", "f2", "f3", "f2", "f3", "f4", "ctrl", "g")])
        self.action._wait_revive_buff.assert_any_call("w", 3.0)
        self.keys.release.assert_any_call("d")
        self.assertNotIn("w", self.action._revive_state)

    def test_interruption_releases_keys_and_resumes_after_sent_key(self):
        self.action._wait_revive_buff.side_effect = [True, False]
        self.assertFalse(self.action._restore_revive_buffs("w", 123, self.pending))
        self.assertEqual(self.pending["buff_step"], 1)
        self.keys.release.assert_any_call("1")
        self.keys.release.assert_any_call("alt")
        self.action._wait_revive_buff.side_effect = None
        self.assertTrue(self.action._restore_revive_buffs("w", 123, self.pending))
        self.assertEqual(self.keys.press.call_args_list.count(mock.call("1")), 1)
        self.assertNotIn(mock.call("g"), self.keys.press.call_args_list)

    def test_dead_stale_or_globally_blocked_state_sends_no_buffs(self):
        for update in ({"visible": True}, {"ts": 1}, {"own_hp": False}):
            with self.subTest(update=update):
                previous = dict(self.action.st.life_data["w"])
                self.action.st.life_data["w"].update(update)
                self.assertFalse(self.action._restore_revive_buffs("w", 123, self.pending))
                self.action.st.life_data["w"] = previous
        self.action.st.captcha_global_active = True
        self.assertFalse(self.action._restore_revive_buffs("w", 123, self.pending))
        self.keys.press.assert_not_called()

    def test_incomplete_buffs_never_mount(self):
        self.action._prepare_revive_buffs = mock.Mock(return_value=True)
        self.action._restore_revive_buffs = mock.Mock(return_value=False)
        self.action._mount_after_revive = mock.Mock()
        self.action._handle_player_life("w", 123, 2)
        self.action._mount_after_revive.assert_not_called()
        self.assertIn("w", self.action._revive_state)

    def test_interrupted_move_releases_d_and_does_not_repeat_mount(self):
        self.action._mount_after_revive = mock.Mock(return_value=True)
        self.action._wait_revive_buff.side_effect = [False]
        with mock.patch("src.phantom.app.main.time.monotonic", side_effect=[10, 11]):
            self.assertFalse(self.action._prepare_revive_buffs("w", 123, self.pending))
        self.assertEqual(self.pending["pre_buff_move_remaining"], 2)
        self.keys.release.assert_called_with("d")
        self.action._mount_after_revive.assert_not_called()
        self.action._wait_revive_buff.side_effect = None
        self.assertTrue(self.action._prepare_revive_buffs("w", 123, self.pending))
        self.action._wait_revive_buff.assert_any_call("w", 2.0)
        self.assertEqual(self.action._mount_after_revive.call_count, 1)
        self.assertTrue(self.pending["pre_buff_dismounted"])
        self.assertTrue(self.action._prepare_revive_buffs("w", 123, self.pending))
        self.assertEqual(self.action._mount_after_revive.call_count, 1)

    def test_mount_retry_does_not_repeat_completed_buffs(self):
        self.pending["buffs_done"] = True
        self.action._restore_revive_buffs = mock.Mock()
        self.action._mount_after_revive = mock.Mock(return_value=False)
        self.action._handle_player_life("w", 123, 2)
        self.action._restore_revive_buffs.assert_not_called()
        self.action._mount_after_revive.assert_called_once()

    def test_new_death_resets_buff_progress(self):
        self.pending.update(buffs_done=True, buff_step=10, mounted=True, next=110)
        self.action.st.life_data["w"]["visible"] = True
        self.action._handle_player_life("w", 123, 2)
        self.assertNotIn("buff_step", self.pending)
        self.assertNotIn("buffs_done", self.pending)
        self.assertNotIn("mounted", self.pending)
