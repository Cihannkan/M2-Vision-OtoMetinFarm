import unittest
from unittest import mock
from src.phantom.app.main import ActionThread, State, VisionThread


class CombatEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.state.aktif = True
        self.state.target_generation['w'] = 2
        self.vision = object.__new__(VisionThread)
        self.vision.st = self.state
        self.action = ActionThread(None, self.state)
        self.action._init('w')
        self.action._target_generation['w'] = 2
        self.action._begin_combat_progress('w', .104, 100, damage_confirmed=True)
        self.action._hp_onceki_durum['w'] = True
        self.action.dur['w'] = 'SAVASIYOR'
        self.action._record_kill = mock.Mock()
        self.action._loot_burst_async = mock.Mock()
        self.action._run_combat_recovery = mock.Mock()
        mock.patch('src.phantom.app.main.log_event').start()
        self.addCleanup(mock.patch.stopall)

    def publish(self, fill=.009, ts=102, **changes):
        data = dict(hp_var=True, hp_fill_ready=True, hp_sample_valid=True,
                    hp_fill=fill, ts=ts, target_generation=2)
        data.update(changes)
        self.vision._publish_client_vision('w', data)

    def test_low_hp_survives_missing_frames_and_drives_existing_death_rule(self):
        self.publish(.019, 101)
        self.publish()
        self.publish(None, 103, hp_var=False, hp_sample_valid=False)
        self.assertIsNone(self.state.wdata['w']['hp_fill'])
        self.assertEqual(self.state.target_hp_evidence['w']['fill'], .009)
        for ts in (104, 105, 108):
            self.action._handle_savasiyor('w', False, None, True, {'oto_loot': True}, 123, ts,
                client_idx=1, target_generation=2, sample_ts=ts, hp_sample_valid=False)
            if ts == 104:
                self.action._record_kill.assert_not_called()
        self.action._record_kill.assert_called_once()
        self.action._run_combat_recovery.assert_not_called()

    def test_invalid_or_old_generation_samples_are_not_saved(self):
        for change in ({'hp_sample_valid': False}, {'hp_var': False},
                       {'hp_fill_ready': False}, {'target_generation': 1}, {'hp_fill': float('nan')}):
            self.publish(**change)
        self.assertEqual(self.state.target_hp_evidence, {})

    def test_stale_future_other_generation_or_precombat_evidence_is_ignored(self):
        for gen, ts in ((1, 102), (2, 99), (2, 160), (2, 101)):
            with self.subTest(gen=gen, ts=ts):
                self.state.target_hp_evidence['w'] = dict(generation=gen, ts=ts, fill=.009)
                self.action._consume_target_hp_evidence('w', 2, 150, 150)
                self.assertEqual(self.action._combat_progress['w']['hp_floor'], .104)

    def test_no_confirmed_damage_cannot_gain_death_evidence(self):
        self.publish()
        self.action._combat_progress['w']['damage_confirmed'] = False
        self.action._consume_target_hp_evidence('w', 2, 103, 103)
        self.assertEqual(self.action._combat_progress['w']['hp_floor'], .104)

    def test_new_target_clears_evidence_and_late_frame_cannot_restore_it(self):
        self.publish()
        self.action._start_target_generation('w', 1, 103)
        self.assertNotIn('w', self.state.target_hp_evidence)
        self.publish(ts=104)
        self.assertNotIn('w', self.state.target_hp_evidence)

    def test_invalid_frame_cannot_replace_valid_minimum(self):
        self.publish(.03, 102)
        self.publish(.001, 103, hp_sample_valid=False)
        self.publish(.001, 101)
        self.assertEqual(self.state.target_hp_evidence['w']['fill'], .03)
