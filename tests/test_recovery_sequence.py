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
    def test_actual_maneuvers_use_d2_a4_d6_for_both_states(self, *_):
        for phase in ("approach", "combat"):
            action = self.make_action()
            for attempt in (1, 2, 3):
                if phase == "approach":
                    self.assertTrue(action._run_approach_recovery("w", 123, attempt))
                else:
                    action._combat_progress["w"] = {"recoveries": attempt - 1}
                    self.assertTrue(action._run_combat_recovery("w", 123))
            self.assertEqual(action._hold_recovery_key.call_args_list, [
                mock.call("w", "space", 1.0, 123), mock.call("w", "d", 2.0, 123),
                mock.call("w", "space", 1.0, 123), mock.call("w", "a", 4.0, 123),
                mock.call("w", "space", 1.0, 123), mock.call("w", "d", 6.0, 123),
            ])

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.pencere_odakla", return_value=True)
    def test_interrupted_space_never_sends_direction(self, *_):
        action = self.make_action()
        action._hold_recovery_key.return_value = False
        self.assertFalse(action._run_approach_recovery("w", 123, 2))
        action._hold_recovery_key.assert_called_once_with("w", "space", 1.0, 123)

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
        self.feed(action, 110.9, moving=True)
        self.assertEqual(action._run_approach_recovery.call_count, 1)
        # Motion alone is not damage; after the wait advance to A4.
        self.feed(action, 111, moving=True)
        self.feed(action, 114, moving=True)
        self.assertEqual(action._run_approach_recovery.call_args_list, [
            mock.call("w", 123, 1), mock.call("w", 123, 2), mock.call("w", 123, 3),
        ])
        action._abandon_approach_target.assert_not_called()
        self.feed(action, 117, moving=True)
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


if __name__ == "__main__":
    unittest.main()
