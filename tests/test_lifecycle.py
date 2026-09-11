import threading
import os
import time
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.phantom.app.main import API, State
from src.phantom.lifecycle import ManagedLifecycle, read_json, write_json, InstanceLock


class LifecycleTests(unittest.TestCase):
    def api(self, active=True):
        state = State()
        state.aktif = active
        cfg = mock.Mock()
        cfg.lk = threading.Lock()
        cfg.d = {"example": 1}
        recorder = mock.Mock()
        recorder.is_alive.return_value = False
        api = API(cfg, state, recorder)
        api._resume_clients = mock.Mock(return_value=[{"client": 1, "hwnd": 123}])
        for name in ("_at", "_vt"):
            worker = mock.Mock()
            worker.is_alive.return_value = False
            setattr(api, name, worker)
        api._at.dur = {"w": "ARANIYOR"}
        api._at._revive_state = {}
        api._at._buff_running = {}
        api._at._loot_running = {}
        api._at._buff_needs_remount = {}
        api._at._buff_next_t = {"w": 123456}
        api._vt.captcha_w = {}
        return api

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.keyboard.release")
    def test_safe_shutdown_joins_workers_closes_video_and_preserves_resume(self, release, log):
        api = self.api()
        action, vision = api._at, api._vt
        result = api.quiesce_for_update()
        self.assertTrue(result["ok"])
        self.assertTrue(result["resume"]["active"])
        self.assertEqual(result["resume"]["buff_next"], {"w": 123456})
        action.stop.assert_called_once()
        vision.stop.assert_called_once()
        action.join.assert_called_once()
        self.assertFalse(api.st.aktif)
        self.assertIsNone(api._at)
        self.assertTrue(release.called)
        api._diagnostic_recorder.stop.assert_called_once()
        self.assertFalse(api._toggle())

    @mock.patch("src.phantom.app.main.keyboard.release")
    def test_live_worker_prevents_success_and_does_not_discard_thread(self, release):
        api = self.api()
        action = api._at
        action.is_alive.return_value = True
        result = api.quiesce_for_update()
        self.assertFalse(result["ok"])
        self.assertIs(api._at, action)
        self.assertTrue(api._maintenance)
        release.assert_not_called()

    def test_combat_or_revive_defers_update_without_stopping(self):
        for state in ("SAVASIYOR", "YENIDEN DOGMA", "DOGRULAMA"):
            with self.subTest(state=state):
                api = self.api()
                api._at.dur = {"w": state}
                self.assertFalse(api.quiesce_for_update()["ok"])
                self.assertTrue(api.st.aktif)
                api._at.stop.assert_not_called()

    def test_global_pause_defers_update(self):
        api = self.api()
        api.st.global_pause_active = True
        self.assertFalse(api.quiesce_for_update()["ok"])
        self.assertTrue(api.st.aktif)

    @mock.patch("src.phantom.app.main.log_event")
    @mock.patch("src.phantom.app.main.keyboard.release")
    def test_manual_closure_does_not_request_auto_resume(self, *_):
        api = self.api()
        result = api.quiesce_for_update(force=True)
        self.assertTrue(result["ok"])
        self.assertFalse(result["resume"]["active"])

    @mock.patch("src.phantom.app.main.log_event")
    def test_changed_config_or_windows_blocks_auto_resume(self, *_):
        for change in ("config", "clients"):
            api = self.api(False)
            api._toggle = mock.Mock()
            resume = {"active": True, "config": api._config_signature(), "clients": api._resume_clients()}
            resume[change] = "different"
            self.assertFalse(api.resume_after_update(resume)["ok"])
            api._toggle.assert_not_called()

    def test_idle_restart_never_activates_bot(self):
        api = self.api(False)
        api._toggle = mock.Mock()
        self.assertTrue(api.resume_after_update({"active": False})["ok"])
        api._toggle.assert_not_called()

    @mock.patch("src.phantom.app.main.log_event")
    def test_normal_stop_retains_live_workers_and_rejects_restart(self, *_):
        api = self.api()
        action = api._at
        action.is_alive.return_value = True
        self.assertTrue(api._toggle(source="UI"))
        self.assertFalse(api.st.aktif)
        self.assertIs(api._at, action)
        self.assertFalse(api._toggle(source="UI"))
        self.assertFalse(api.st.aktif)

    def test_startup_gate_blocks_manual_toggle_until_loaded(self):
        api = self.api(False)
        api._startup_gate = True
        self.assertFalse(api._toggle(source="F5"))
        self.assertFalse(api.st.aktif)
        api.resume_after_update({})
        self.assertFalse(api._startup_gate)

    def test_matching_resume_uses_existing_buff_schedule(self):
        api = self.api(False)
        resume = {"active": True, "config": api._config_signature(), "clients": api._resume_clients(), "buff_next": {"w": 789}}
        def toggle(**kwargs):
            self.assertEqual(api._pending_resume["buff_next"], {"w": 789})
            return True
        api._toggle = mock.Mock(side_effect=toggle)
        self.assertTrue(api.resume_after_update(resume)["ok"])
        self.assertIsNone(api._pending_resume)

    def test_atomic_json_and_invalid_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.json"
            self.assertEqual(read_json(path), {})
            write_json(path, {"state": "hazir"})
            self.assertEqual(read_json(path), {"state": "hazir"})

    def test_protocol_acks_only_after_successful_drain(self):
        with tempfile.TemporaryDirectory() as folder:
            api = mock.Mock()
            api.resume_after_update.return_value = {"ok": True}
            api.quiesce_for_update.return_value = {"ok": True, "resume": {"active": False}}
            life = ManagedLifecycle(api, mock.Mock(), folder)
            life.loaded.set()
            life.stop_event = mock.Mock()
            life.stop_event.wait.return_value = False
            write_json(Path(folder) / "shutdown.json", {
                "pid": os.getpid(), "operation": "update", "id": "request-one", "deadline": time.time()+10})
            life.run()
            api.quiesce_for_update.assert_called_once()
            ack = read_json(Path(folder) / "ack.json")
            self.assertTrue(ack["ok"])
            self.assertEqual(ack["request_id"], "request-one")
            life.window.destroy.assert_called_once()

    def test_expired_request_never_drains_or_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            api = mock.Mock()
            life = ManagedLifecycle(api, mock.Mock(), folder)
            life.stop_event = mock.Mock()
            life.stop_event.wait.side_effect = [False, True]
            write_json(Path(folder) / "shutdown.json", {
                "pid": os.getpid(), "operation": "update", "id": "old", "deadline": 0})
            life.run()
            api.quiesce_for_update.assert_not_called()
            life.window.destroy.assert_not_called()
            self.assertFalse(read_json(Path(folder) / "ack.json")["ok"])

    def test_instance_lock_rejects_second_copy_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "app.lock"
            first = InstanceLock(path).acquire()
            try:
                with self.assertRaises(RuntimeError):
                    InstanceLock(path).acquire()
            finally:
                first.close()
            InstanceLock(path).acquire().close()

    def test_manual_close_marks_user_intent_and_honors_failed_drain(self):
        with tempfile.TemporaryDirectory() as folder:
            api = mock.Mock()
            api.quiesce_for_update.return_value = {"ok": False}
            life = ManagedLifecycle(api, mock.Mock(), folder)
            self.assertFalse(life.on_closing())
            self.assertTrue(read_json(Path(folder) / "user_closed.json"))


if __name__ == "__main__":
    unittest.main()
