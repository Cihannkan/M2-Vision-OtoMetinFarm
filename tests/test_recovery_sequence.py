import unittest
from unittest import mock

from src.phantom.app.main import ActionThread, State


class RecoverySequenceTests(unittest.TestCase):
    def make_action(self):
        action = ActionThread(None, State())
        action.st.aktif = True
        action._hold_recovery_key = mock.Mock(return_value=True)
        action._stop_event = mock.Mock()
        action._stop_event.is_set.return_value = False
        action._stop_event.wait.return_value = False
        return action

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.pencere_odakla", return_value=True)
    def test_actual_recoveries_use_skill_then_back_right_then_back_left(self, *_):
        for phase in ("approach", "combat"):
            action = self.make_action()
            for attempt in (1, 2, 3):
                if phase == "approach":
                    self.assertTrue(action._run_approach_recovery("w", 123, attempt))
                else:
                    action._combat_progress["w"] = {"recoveries": attempt - 1}
                    self.assertTrue(action._run_combat_recovery("w", 123))
            self.assertEqual(action._hold_recovery_key.call_args_list, [
                mock.call("w", "1", 0.10, 123),
                mock.call("w", "s", 1.0, 123), mock.call("w", "d", 2.0, 123),
                mock.call("w", "s", 1.0, 123), mock.call("w", "a", 4.0, 123),
            ])
            if phase == "approach":
                self.assertFalse(action._run_approach_recovery("w", 123, 4))
            else:
                action._combat_progress["w"] = {"recoveries": 3}
                self.assertFalse(action._run_combat_recovery("w", 123))
            self.assertEqual(action._hold_recovery_key.call_count, 5)
            self.assertEqual(action._recovery_reclick["w"]["attempt"], 3)

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.pencere_odakla", return_value=True)
    def test_interrupted_skill_never_sends_direction(self, *_):
        action = self.make_action()
        action._hold_recovery_key.return_value = False
        self.assertFalse(action._run_approach_recovery("w", 123, 1))
        action._hold_recovery_key.assert_called_once_with("w", "1", 0.10, 123)

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.pencere_odakla", return_value=True)
    def test_interrupted_backward_does_not_send_sideways_or_queue_click(self, *_):
        action = self.make_action()
        action._hold_recovery_key.return_value = False
        self.assertFalse(action._run_approach_recovery("w", 123, 2))
        action._hold_recovery_key.assert_called_once_with("w", "s", 1.0, 123)
        self.assertFalse(action._recovery_reclick)

    def setup_reclick(self, phase="DOGRULAMA", attempt=2):
        action = self.setup_approach()
        action.dur["w"] = phase
        action._kilitli_hedef = {"w": (200, 200)}
        action._recovery_reclick["w"] = dict(
            after=110.0, attempt=attempt, hwnd=123, phase=phase,
            generation=1, started=100.0, pos=(200, 200),
        )
        return action

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main._tiklama_yap", return_value="default")
    def test_reclick_uses_new_detection_and_preserves_attempts_in_both_phases(self, click, *_):
        for phase in ("DOGRULAMA", "SAVASIYOR"):
            action = self.setup_reclick(phase, 3)
            action.st.target_generation["w"] = 1
            action.st.target_hp_evidence["w"] = {"old": True}
            targets = [{"cx": 260, "cy": 220, "stable_click": True}]
            with mock.patch("src.phantom.app.main.time.time", return_value=111):
                self.assertTrue(action._handle_recovery_reclick("w", 123, {}, targets, 110.5, 1000, 500, 1))
            click.assert_called_with(None, 1260, 720, 123)
            self.assertEqual(action.dur["w"], "DOGRULAMA")
            self.assertEqual(action._approach["w"]["recoveries"], 3)
            self.assertEqual(action._approach["w"]["check_after"], 115)
            self.assertEqual(action._approach["w"]["started"], 100)
            self.assertEqual(action._target_generation["w"], 2)
            self.assertNotIn("w", action.st.target_hp_evidence)
            self.assertFalse(action._recovery_reclick)

    @mock.patch("src.phantom.app.main._tiklama_yap")
    def test_old_unstable_far_or_ambiguous_detection_never_clicked(self, click):
        cases = [
            (109, [{"cx": 205, "cy": 200, "stable_click": True}]),
            (110.5, [{"cx": 205, "cy": 200, "stable_click": False}]),
            (110.5, [{"cx": 900, "cy": 200, "stable_click": True}]),
            (110.5, [{"cx": 210, "cy": 200, "stable_click": True},
                     {"cx": 220, "cy": 200, "stable_click": True}]),
        ]
        for ts, targets in cases:
            action = self.setup_reclick()
            with mock.patch("src.phantom.app.main.time.time", return_value=111):
                self.assertTrue(action._handle_recovery_reclick("w", 123, {}, targets, ts, 0, 0))
            click.assert_not_called()

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main._tiklama_yap")
    def test_reclick_timeout_abandons_and_blocks_old_target(self, click, *_):
        action = self.setup_reclick()
        # Restore real abandonment, which setup_approach normally mocks.
        action._abandon_approach_target = ActionThread._abandon_approach_target.__get__(action)
        with mock.patch("src.phantom.app.main.time.time", return_value=114):
            action._handle_recovery_reclick("w", 123, {}, [], 113.9, 0, 0)
        self.assertEqual(action.dur["w"], "ARANIYOR")
        self.assertFalse(action._recovery_reclick)
        self.assertEqual(action._approach_blocked_target["w"]["pos"], (200, 200))
        self.assertGreater(action._approach_blocked_target["w"]["until"], 114)
        click.assert_not_called()

    @mock.patch("src.phantom.app.main._tiklama_yap")
    def test_paused_or_replaced_target_cannot_reclick(self, click):
        action = self.setup_reclick()
        action.st.global_pause_active = True
        with mock.patch("src.phantom.app.main.time.time", return_value=111):
            self.assertTrue(action._handle_recovery_reclick("w", 123, {}, [], 110.5, 0, 0))
        action.st.global_pause_active = False
        action._target_generation["w"] = 2
        self.assertFalse(action._handle_recovery_reclick("w", 123, {}, [], 110.5, 0, 0))
        self.assertFalse(action._recovery_reclick)
        click.assert_not_called()

    def setup_approach(self):
        action = self.make_action()
        action._init("w")
        action.dur["w"] = "DOGRULAMA"
        action._target_generation["w"] = 1
        action._begin_approach("w", 100.0)
        action._run_approach_recovery = mock.Mock(return_value=True)
        action._abandon_approach_target = mock.Mock()
        return action

    def feed(self, action, now, fill=1.0, moving=False, valid=True):
        with mock.patch("src.phantom.app.main.time.time", return_value=now), mock.patch(
            "src.phantom.app.main.log_event"
        ):
            action._handle_dogrulama(
                "w", True, fill, True, moving, True, {}, 123,
                target_generation=1, sample_ts=now, client_idx=1,
                hp_sample_valid=valid,
            )

    def test_eight_second_trigger_then_damage_checks_between_attempts(self):
        action = self.setup_approach()
        self.feed(action, 100)
        self.feed(action, 107.9)
        action._run_approach_recovery.assert_not_called()
        self.feed(action, 108)
        self.feed(action, 111.9, moving=True)
        self.assertEqual(action._run_approach_recovery.call_count, 1)
        # Motion alone is not damage; retry the skill after four seconds.
        self.feed(action, 112, moving=True)
        self.feed(action, 115.9, moving=True)
        self.assertEqual(action._run_approach_recovery.call_count, 2)
        self.feed(action, 116, moving=True)
        self.assertEqual(action._run_approach_recovery.call_args_list, [
            mock.call("w", 123, 1), mock.call("w", 123, 2), mock.call("w", 123, 3),
        ])
        action._abandon_approach_target.assert_not_called()
        self.feed(action, 119.9, moving=True)
        action._abandon_approach_target.assert_not_called()
        self.feed(action, 120, moving=True)
        action._abandon_approach_target.assert_called_once()

    def test_confirmed_damage_stops_remaining_approach_maneuvers(self):
        action = self.setup_approach()
        self.feed(action, 100)
        self.feed(action, 108)
        self.feed(action, 111, fill=0.95)
        self.assertEqual(action._run_approach_recovery.call_count, 1)
        self.feed(action, 111.3, fill=0.95)
        self.assertEqual(action.dur["w"], "SAVASIYOR")
        self.assertEqual(action._run_approach_recovery.call_count, 1)
        self.assertEqual(action._combat_progress["w"]["recoveries"], 0)
        action._abandon_approach_target.assert_not_called()

    def test_invalid_hp_cannot_advance_next_maneuver(self):
        action = self.setup_approach()
        self.feed(action, 100)
        self.feed(action, 108)
        self.feed(action, 111, valid=False)
        self.assertEqual(action._run_approach_recovery.call_count, 1)

    @mock.patch("src.phantom.app.main.log_event")
    def test_missing_approach_panel_retries_every_four_seconds(self, *_):
        action = self.setup_approach()
        for now, expected in ((100, 0), (107.9, 0), (108, 1), (111.9, 1),
                              (112, 2), (115.9, 2), (116, 3), (119.9, 3), (120, 3)):
            with mock.patch("src.phantom.app.main.time.time", return_value=now):
                action._handle_dogrulama(
                    "w", False, None, True, False, True, {}, 123,
                    target_generation=1, sample_ts=now, client_idx=1,
                    hp_sample_valid=False,
                )
            self.assertEqual(action._run_approach_recovery.call_count, expected)
        action._abandon_approach_target.assert_called_once()

    @mock.patch("src.phantom.app.main.log_event")
    def test_combat_first_wait_six_then_four_between_skill_attempts(self, *_):
        action = self.make_action()
        action._init("w")
        action.dur["w"] = "SAVASIYOR"
        action._combat_progress["w"] = {
            "hp_floor": 0.5, "last_progress": 100.0,
            "recoveries": 0, "check_after": 0.0,
        }
        action._run_combat_recovery = mock.Mock(return_value=True)
        action._abandon_combat_target = mock.Mock()
        for now, expected in ((105.9, 0), (106, 1), (109.9, 1), (110, 2),
                              (113.9, 2), (114, 3), (117.9, 3), (118, 3)):
            with mock.patch("src.phantom.app.main.time.time", return_value=now):
                action._handle_savasiyor(
                    "w", hp_var=True, hp_fill=0.5, hp_fill_ready=True,
                    cc={}, hwnd=123, now=now, client_idx=1,
                )
            self.assertEqual(action._run_combat_recovery.call_count, expected)
        action._abandon_combat_target.assert_called_once()


if __name__ == "__main__":
    unittest.main()
