import time
import unittest
from collections import deque
from unittest import mock

from src.phantom.app.main import (
    ActionThread,
    COMBAT_PANEL_LOST_TIMEOUT_SN,
    COMBAT_RECOVERY_MAX,
    State,
    VisionThread,
)


class CombatStateTests(unittest.TestCase):
    def test_visible_panel_in_search_waits_for_damage_confirmation(self):
        window = "client-1"
        action = object.__new__(ActionThread)
        action.st = State()
        action._hp_ignore_until = {}
        action._combat_progress = {}
        action._combat_diag_t = {}
        action._approach = {}
        action._approach_diag_t = {}
        action._hp_onceki_durum = {}
        action._hp_kayip_t = {}
        action._araniyor_baslat_t = {}
        action.dogr_t = {}
        action.dogr_n = {}
        action.dur = {window: "ARANIYOR"}

        with mock.patch("src.phantom.app.main.log_event"):
            action._handle_araniyor(
                window, [], True, 500, 400, 123, {}, 0, 0,
                data_ts=100.0, client_idx=1,
            )

        self.assertEqual(action.dur[window], "DOGRULAMA")
        self.assertIn(window, action._approach)
        self.assertNotIn(window, action._combat_progress)

    def test_same_vision_frame_is_consumed_only_once(self):
        action = object.__new__(ActionThread)
        action._target_generation = {"client-1": 4}
        action._last_target_sample = {}

        self.assertTrue(action._target_sample_is_new("client-1", 4, 100.0))
        self.assertFalse(action._target_sample_is_new("client-1", 4, 100.0))
        self.assertTrue(action._target_sample_is_new("client-1", 4, 101.0))

    def test_old_target_generation_cannot_drive_combat(self):
        action = object.__new__(ActionThread)
        action._target_generation = {"client-2": 8}
        action._last_target_sample = {}

        self.assertFalse(action._target_sample_is_new("client-2", 7, 101.0))
        self.assertTrue(action._target_sample_is_new("client-2", 8, 102.0))

    def test_vision_generation_change_clears_hp_history_and_votes(self):
        vision = object.__new__(VisionThread)
        vision._hp_generation_seen = {"client-1": 2}
        vision._hp_fill_hist = {"client-1": deque([0.20, 0.18], maxlen=5)}
        vision._hp_accepted_floor = {"client-1": 0.18}
        vision._hp_presence_hist = {"client-1": deque([True, True], maxlen=3)}
        vision._hp_reject_t = {"client-1": 100.0}

        self.assertTrue(vision._sync_hp_generation("client-1", 3))
        self.assertNotIn("client-1", vision._hp_fill_hist)
        self.assertNotIn("client-1", vision._hp_accepted_floor)
        self.assertNotIn("client-1", vision._hp_presence_hist)
        self.assertNotIn("client-1", vision._hp_reject_t)
        self.assertFalse(vision._sync_hp_generation("client-1", 3))

    def test_damage_confirmation_requires_a_second_vision_frame(self):
        window = "client-1"
        action = object.__new__(ActionThread)
        action.st = State()
        action._target_generation = {window: 1}
        action._last_target_sample = {}
        action._approach = {
            window: {
                "started": 90.0,
                "max_fill": 1.0,
                "drop_since": 0.0,
                "still_since": 0.0,
                "recoveries": 0,
                "check_after": 90.0,
                "warned_no_fill": False,
            }
        }
        action._approach_diag_t = {}
        action._combat_progress = {}
        action._combat_diag_t = {}
        action._hp_onceki_durum = {}
        action.dogr_t = {window: 90.0}
        action.dogr_n = {window: 0}
        action.dur = {window: "DOGRULAMA"}

        with mock.patch("src.phantom.app.main.time.time", return_value=100.0):
            action._handle_dogrulama(
                window, True, 0.90, True, False, False, {}, 123,
                target_generation=1, sample_ts=10.0, client_idx=1,
            )
        self.assertEqual(action.dur[window], "DOGRULAMA")

        # Aksiyon dongusu ayni kareyi tekrar gorurse, zaman gecmis olsa bile
        # bunu ikinci bir gorsel kanit olarak kabul etmemeli.
        with mock.patch("src.phantom.app.main.time.time", return_value=101.0):
            action._handle_dogrulama(
                window, True, 0.90, True, False, False, {}, 123,
                target_generation=1, sample_ts=10.0, client_idx=1,
            )
        self.assertEqual(action.dur[window], "DOGRULAMA")

        with mock.patch("src.phantom.app.main.time.time", return_value=101.0), mock.patch(
            "src.phantom.app.main.log_event"
        ):
            action._handle_dogrulama(
                window, True, 0.90, True, False, False, {}, 123,
                target_generation=1, sample_ts=11.0, client_idx=1,
            )
        self.assertEqual(action.dur[window], "SAVASIYOR")

    def test_death_confirmation_requires_a_new_absent_frame(self):
        window = "client-1"
        action = object.__new__(ActionThread)
        action.st = State()
        action._target_generation = {window: 2}
        action._last_target_sample = {}
        action._hp_onceki_durum = {window: True}
        action._hp_kayip_t = {}
        action._combat_progress = {
            window: {
                "hp_floor": 0.05,
                "start_fill": 0.90,
                "last_progress": 99.0,
                "damage_confirmed": True,
                "recoveries": 0,
            }
        }
        action._combat_diag_t = {}
        action._araniyor_baslat_t = {}
        action._son_tiklama_t = {}
        action._son_tiklama_zamani = {}
        action.dur = {window: "SAVASIYOR"}

        with mock.patch("src.phantom.app.main.log_event"):
            action._handle_savasiyor(
                window, False, None, True, {"oto_loot": False}, 123, 100.0,
                client_idx=1, target_generation=2, sample_ts=20.0,
            )
            action._handle_savasiyor(
                window, False, None, True, {"oto_loot": False}, 123, 100.5,
                client_idx=1, target_generation=2, sample_ts=20.0,
            )
        self.assertEqual(action.dur[window], "SAVASIYOR")

        with mock.patch("src.phantom.app.main.log_event"):
            action._handle_savasiyor(
                window, False, None, True, {"oto_loot": False}, 123, 100.5,
                client_idx=1, target_generation=2, sample_ts=21.0,
            )
        self.assertEqual(action.dur[window], "SAVASIYOR")

        with mock.patch("src.phantom.app.main.log_event"):
            action._handle_savasiyor(
                window, False, None, True, {"oto_loot": False}, 123, 101.0,
                client_idx=1, target_generation=2, sample_ts=22.0,
            )
        self.assertEqual(action.dur[window], "ARANIYOR")
        self.assertEqual(action.st.kill_counts.get("c1"), 1)

    def test_high_hp_panel_loss_is_not_a_fast_kill(self):
        window = "client-2"
        action = object.__new__(ActionThread)
        action.st = State()
        action._target_generation = {window: 4}
        action._last_target_sample = {}
        action._hp_onceki_durum = {window: True}
        action._hp_kayip_t = {}
        action._combat_progress = {
            window: {
                "hp_floor": 0.972,
                "start_fill": 0.981,
                "last_progress": 99.0,
                "damage_confirmed": True,
                "recoveries": 0,
            }
        }
        action._combat_diag_t = {}
        action._araniyor_baslat_t = {}
        action._son_tiklama_t = {}
        action._son_tiklama_zamani = {}
        action.dur = {window: "SAVASIYOR"}
        action._run_combat_recovery = mock.Mock(return_value=False)

        with mock.patch("src.phantom.app.main.log_event"):
            for now, sample_ts in (
                (100.0, 40.0),
                (100.5, 41.0),
                (101.0, 42.0),
                (103.0, 43.0),
                (106.0, 44.0),
                (112.0, 45.0),
            ):
                action._handle_savasiyor(
                    window, False, None, True, {"oto_loot": False}, 123, now,
                    client_idx=2, target_generation=4, sample_ts=sample_ts,
                )

        self.assertEqual(action.dur[window], "SAVASIYOR")
        self.assertEqual(action.st.kill_counts.get("c2", 0), 0)
        action._run_combat_recovery.assert_called()

    def test_long_high_hp_panel_loss_recovers_then_resumes_without_kill_or_loot(self):
        for floor in (0.509, 0.868, None):
            with self.subTest(floor=floor):
                window = "client-1"
                action = object.__new__(ActionThread)
                action.st = State()
                action._target_generation = {window: 4}
                action._last_target_sample = {}
                action._hp_onceki_durum = {window: True}
                action._hp_kayip_t = {}
                action._combat_progress = {window: {
                    "hp_floor": floor, "damage_confirmed": True,
                }}
                action._combat_diag_t = {}
                action._araniyor_baslat_t = {}
                action._son_tiklama_t = {}
                action._hp_ignore_until = {}
                action._kilitli_hedef = {window: (100, 200)}
                action._approach_blocked_target = {}
                action.dur = {window: "SAVASIYOR"}
                action._record_kill = mock.Mock()
                action._loot_burst_async = mock.Mock()
                action._run_combat_recovery = mock.Mock(return_value=True)
                with mock.patch("src.phantom.app.main.log_event"), mock.patch(
                    "src.phantom.app.main.time.time",
                    side_effect=(106.0, 112.0, 118.0),
                ):
                    # Her kurtarmadan sonra panelin hâlâ kayıp olduğuna dair
                    # üç yeni Vision karesi gerekir. Canlı akışta bu kareler
                    # yaklaşık saniyenin onda biri aralıklarla gelir.
                    for now, sample_ts in (
                        (100, 1), (101, 2), (106, 3),
                        (107, 4), (108, 5), (112, 6),
                        (113, 7), (114, 8), (118, 9),
                    ):
                        action._handle_savasiyor(
                            window, False, None, True, {"oto_loot": True},
                            123, now, client_idx=1, target_generation=4,
                            sample_ts=sample_ts,
                        )
                    self.assertEqual(action.dur[window], "SAVASIYOR")
                    # Re-reading an old frame cannot release the target.
                    action._handle_savasiyor(
                        window, False, None, True, {}, 123, 124,
                        target_generation=4, sample_ts=9,
                    )
                    self.assertEqual(action.dur[window], "SAVASIYOR")
                    for now, sample_ts in ((119, 10), (120, 11), (124, 12)):
                        action._handle_savasiyor(
                            window, False, None, True, {"oto_loot": True}, 123, now,
                            target_generation=4, sample_ts=sample_ts,
                        )
                self.assertEqual(action.dur[window], "ARANIYOR")
                self.assertNotIn(window, action._hp_kayip_t)
                self.assertNotIn(window, action._combat_progress)
                self.assertEqual(action._approach_blocked_target[window]["until"], 135)
                self.assertEqual(action._run_combat_recovery.call_count, 3)
                action._record_kill.assert_not_called()
                action._loot_burst_async.assert_not_called()

    def test_blocked_panel_recovery_still_has_an_absolute_timeout(self):
        window = "client-3"
        action = object.__new__(ActionThread)
        action.st = State()
        action._target_generation = {window: 9}
        action._last_target_sample = {}
        action._hp_onceki_durum = {window: True}
        action._hp_kayip_t = {}
        action._combat_progress = {window: {
            "hp_floor": 0.868,
            "damage_confirmed": True,
            "recoveries": 0,
            "check_after": 0.0,
        }}
        action._combat_diag_t = {}
        action._araniyor_baslat_t = {}
        action._son_tiklama_t = {}
        action._hp_ignore_until = {}
        action._kilitli_hedef = {window: (100, 200)}
        action._approach_blocked_target = {}
        action.dur = {window: "SAVASIYOR"}
        action._record_kill = mock.Mock()
        action._loot_burst_async = mock.Mock()
        # Örneğin global bir duraklama yüzünden giriş gönderilemese bile
        # client aynı hedefte sonsuza kadar kalmamalı.
        action._run_combat_recovery = mock.Mock(return_value=False)

        with mock.patch("src.phantom.app.main.log_event"):
            for now, sample_ts in (
                (100.0, 1.0),
                (101.0, 2.0),
                (106.0, 3.0),
                (100.0 + COMBAT_PANEL_LOST_TIMEOUT_SN, 4.0),
            ):
                action._handle_savasiyor(
                    window, False, None, True, {"oto_loot": True}, 123, now,
                    client_idx=3, target_generation=9, sample_ts=sample_ts,
                )

        self.assertEqual(action.dur[window], "ARANIYOR")
        action._record_kill.assert_not_called()
        action._loot_burst_async.assert_not_called()

    def test_panel_disappearance_without_damage_is_not_a_kill(self):
        window = "client-1"
        action = object.__new__(ActionThread)
        action.st = State()
        action._target_generation = {window: 3}
        action._last_target_sample = {}
        action._hp_onceki_durum = {window: True}
        action._hp_kayip_t = {}
        action._combat_progress = {
            window: {
                "hp_floor": 0.90,
                "start_fill": 0.90,
                "last_progress": 99.0,
                "damage_confirmed": False,
                "recoveries": 0,
            }
        }
        action._combat_diag_t = {}
        action._araniyor_baslat_t = {}
        action._son_tiklama_t = {}
        action._son_tiklama_zamani = {}
        action.dur = {window: "SAVASIYOR"}

        with mock.patch("src.phantom.app.main.log_event") as event_log:
            action._handle_savasiyor(
                window, False, None, True, {"oto_loot": True}, 123, 100.0,
                client_idx=1, target_generation=3, sample_ts=30.0,
            )
            action._handle_savasiyor(
                window, False, None, True, {"oto_loot": True}, 123, 101.0,
                client_idx=1, target_generation=3, sample_ts=31.0,
            )
            action._handle_savasiyor(
                window, False, None, True, {"oto_loot": True}, 123, 103.0,
                client_idx=1, target_generation=3, sample_ts=32.0,
            )

        self.assertEqual(action.dur[window], "SAVASIYOR")
        self.assertEqual(action.st.kill_counts.get("c1", 0), 0)
        self.assertTrue(any("karar bekletildi" in call.args[2] for call in event_log.call_args_list))

    def test_impossible_hp_growth_does_not_trigger_recovery_or_target_change(self):
        window = "client-2"
        action = object.__new__(ActionThread)
        action.st = State()
        action._target_generation = {window: 11}
        action._last_target_sample = {}
        action._hp_onceki_durum = {window: True}
        action._hp_kayip_t = {}
        action._araniyor_baslat_t = {}
        action._combat_progress = {
            window: {
                "hp_floor": 0.236,
                "start_fill": 0.90,
                "last_progress": 90.0,
                "damage_confirmed": True,
                "recoveries": 0,
                "check_after": 0.0,
            }
        }
        action._combat_diag_t = {}
        action.dur = {window: "SAVASIYOR"}
        action._run_combat_recovery = lambda *_args: self.fail(
            "Rejected HP growth must not run recovery"
        )
        action._abandon_combat_target = lambda *_args: self.fail(
            "Rejected HP growth must keep the current target"
        )

        with mock.patch("src.phantom.app.main.log_event") as event_log:
            action._handle_savasiyor(
                window,
                hp_var=True,
                hp_fill=0.755,
                hp_fill_ready=True,
                cc={},
                hwnd=123,
                now=100.0,
                client_idx=2,
                target_generation=11,
                sample_ts=50.0,
                hp_sample_valid=True,
            )

        self.assertEqual(action.dur[window], "SAVASIYOR")
        self.assertEqual(action._combat_progress[window]["hp_floor"], 0.236)
        self.assertEqual(action._combat_progress[window]["recoveries"], 0)
        self.assertTrue(any("imkansiz can artisi" in call.args[2] for call in event_log.call_args_list))

    def test_vision_result_is_published_per_client_without_overwriting_others(self):
        state = State()
        vision = object.__new__(VisionThread)
        vision.st = state

        with mock.patch("src.phantom.app.main.time.time", side_effect=[100.0, 101.0]):
            first = vision._publish_client_vision("client-1", {"ts": 90.0})
            second = vision._publish_client_vision("client-2", {"ts": 91.0})

        self.assertEqual(first["publish_ts"], 100.0)
        self.assertEqual(second["publish_ts"], 101.0)
        self.assertEqual(state.wdata["client-1"]["ts"], 90.0)
        self.assertEqual(state.wdata["client-2"]["ts"], 91.0)

    @mock.patch("src.phantom.app.main._send_keyboard_scancode_tap", return_value=True)
    def test_loot_uses_verified_scancode_sendinput_fallback(self, send_tap):
        action = object.__new__(ActionThread)
        with mock.patch("src.phantom.app.main.INTERCEPTION_OK", False), mock.patch(
            "src.phantom.app.main._ikdev", None
        ):
            result = action._loot_tap()

        self.assertTrue(result["ok"])
        self.assertTrue(result["delivered"])
        self.assertEqual(result["method"], "sendinput_scancode")
        send_tap.assert_called_once()

    def test_loot_burst_reports_focus_and_os_delivery_counts(self):
        state = State()
        state.aktif = True
        action = ActionThread(None, state)
        action._loot_tap = mock.Mock(
            return_value={"ok": True, "delivered": True, "method": "sendinput_scancode"}
        )

        with mock.patch("src.phantom.app.main.pencere_odakla", return_value=True), mock.patch(
            "src.phantom.app.main.win32gui.GetForegroundWindow", return_value=123
        ), mock.patch("src.phantom.app.main.log_event") as event_log:
            result = action._loot_burst(
                "client-1", 123, {"oto_loot": True},
                reason="test", taps=2, delay=0.0, interval=0.03,
            )

        self.assertTrue(result)
        self.assertEqual(action._loot_tap.call_count, 2)
        final_message = event_log.call_args.args[2]
        self.assertIn("OS_teslim=2/2", final_message)
        self.assertIn("odak_son=evet", final_message)

    def test_visible_hp_panel_keeps_target_locked_after_recovery(self):
        window = "client-2"
        now = time.time()
        action = object.__new__(ActionThread)
        action._hp_onceki_durum = {}
        action._hp_kayip_t = {}
        action._araniyor_baslat_t = {}
        action._combat_progress = {
            window: {
                "hp_floor": 0.50,
                "last_progress": now - 7.0,
                "recoveries": 1,
                "check_after": 0.0,
            }
        }
        action.dur = {window: "SAVASIYOR"}
        action._run_combat_recovery = lambda _window, _hwnd: True
        action._abandon_combat_target = lambda *_args, **_kwargs: self.fail(
            "Visible HP panel must not abandon the combat target"
        )

        action._handle_savasiyor(
            window,
            hp_var=True,
            hp_fill=0.50,
            hp_fill_ready=True,
            cc={},
            hwnd=123,
            now=now,
            client_idx=2,
        )

        progress = action._combat_progress[window]
        self.assertEqual(action.dur[window], "SAVASIYOR")
        self.assertEqual(progress["recoveries"], 2)
        self.assertGreaterEqual(progress["last_progress"], now)

    def test_combat_target_is_abandoned_after_three_failed_recoveries(self):
        window = "client-1"
        now = time.time()
        action = object.__new__(ActionThread)
        action._hp_onceki_durum = {}
        action._hp_kayip_t = {}
        action._araniyor_baslat_t = {}
        action._combat_progress = {
            window: {
                "hp_floor": 0.50,
                "last_progress": now - 7.0,
                "recoveries": COMBAT_RECOVERY_MAX,
                "check_after": 0.0,
            }
        }
        action.dur = {window: "SAVASIYOR"}
        action._run_combat_recovery = lambda *_args: self.fail(
            "Recovery limit must be checked before another input"
        )
        abandoned = []
        action._abandon_combat_target = (
            lambda _window, _cc, _now, reason: abandoned.append(reason)
        )

        action._handle_savasiyor(
            window,
            hp_var=True,
            hp_fill=0.50,
            hp_fill_ready=True,
            cc={},
            hwnd=123,
            now=now,
            client_idx=1,
        )

        self.assertEqual(len(abandoned), 1)
        self.assertIn("3 kurtarma", abandoned[0])

    def test_hp_progress_resets_failed_recovery_count(self):
        window = "client-1"
        now = time.time()
        action = object.__new__(ActionThread)
        action._hp_onceki_durum = {}
        action._hp_kayip_t = {}
        action._araniyor_baslat_t = {}
        action._combat_progress = {
            window: {
                "hp_floor": 0.50,
                "last_progress": now - 7.0,
                "recoveries": COMBAT_RECOVERY_MAX,
                "check_after": 0.0,
            }
        }
        action.dur = {window: "SAVASIYOR"}
        action._run_combat_recovery = lambda *_args: self.fail(
            "HP progress must not trigger recovery"
        )
        action._abandon_combat_target = lambda *_args: self.fail(
            "HP progress must keep the current target"
        )

        action._handle_savasiyor(
            window,
            hp_var=True,
            hp_fill=0.45,
            hp_fill_ready=True,
            cc={},
            hwnd=123,
            now=now,
            client_idx=1,
        )

        self.assertEqual(action._combat_progress[window]["recoveries"], 0)
        self.assertTrue(action._combat_progress[window]["damage_confirmed"])


if __name__ == "__main__":
    unittest.main()
