import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock

from phantom_supervisor import Supervisor, snapshot, verify_snapshot
from src.phantom.lifecycle import write_json, read_json


class SupervisorTests(unittest.TestCase):
    def test_real_child_startup_failure_returns_to_previous_release(self):
        # These children only exchange JSON. They import no game/GUI modules.
        stub = '''import json,os,time
from pathlib import Path
r=Path(os.environ['PHANTOM_MANAGED_RUN'])
def write(name,data):
 p=r/name; t=p.with_suffix('.tmp'); t.write_text(json.dumps(data))
 for _ in range(10):
  try: os.replace(t,p); return
  except PermissionError: time.sleep(.01)
for _ in range(100):
 write('health.json',{'pid':os.getpid(),'run_id':r.name,'ts':time.time(),'status':'ready'})
 try: q=json.loads((r/'shutdown.json').read_text())
 except (OSError,ValueError): q={}
 if q.get('pid')==os.getpid():
  write('ack.json',{'ok':True,'request_id':q['id'],'resume':{'active':False}})
  break
 time.sleep(.1)
'''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "metin_bot_webview.py").write_text(stub, encoding="utf-8")
            old = snapshot(root, root / "releases")
            (root / "metin_bot_webview.py").write_text("raise SystemExit(7)", encoding="utf-8")
            bad = snapshot(root, root / "releases")
            supervisor = Supervisor(root)
            supervisor.python = Path(sys.executable)
            try:
                supervisor.launch(old, {})
                self.assertTrue(supervisor.await_ready(timeout=5), f"stub exit={supervisor.child.poll()}, health={read_json(supervisor.run_dir / 'health.json')}")
                original_pid = supervisor.child.pid
                with mock.patch("phantom_supervisor.snapshot", return_value=bad), mock.patch("phantom_supervisor.test_release"):
                    supervisor.update()
                self.assertEqual(supervisor.release, old)
                self.assertNotEqual(supervisor.child.pid, original_pid)
                self.assertIsNone(supervisor.child.poll())
                self.assertIn("previous release restored", read_json(supervisor.control / "status.json")["detail"])
            finally:
                if supervisor.child and supervisor.child.poll() is None:
                    write_json(supervisor.run_dir / "shutdown.json", {
                        "pid": supervisor.worker_pid, "id": "cleanup"})
                    supervisor.child.wait(timeout=5)

    def test_snapshot_excludes_settings_and_recordings_and_detects_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "metin_bot_webview.py").write_text("pass", encoding="utf-8")
            (root / "config_phantom.json").write_text("private", encoding="utf-8")
            (root / "runtime").mkdir()
            (root / "runtime" / "video.mp4").write_bytes(b"private")
            release = snapshot(root, root / "runtime" / "releases")
            verify_snapshot(release)
            self.assertFalse((release / "config_phantom.json").exists())
            self.assertFalse((release / "runtime").exists())
            (release / "metin_bot_webview.py").write_text("changed", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_snapshot(release)

    def test_manifest_cannot_reference_outside_release(self):
        with tempfile.TemporaryDirectory() as folder:
            write_json(Path(folder) / "manifest.json", {"metin_bot_webview.py": "bad", "../outside": "bad"})
            with self.assertRaises(ValueError):
                verify_snapshot(folder)

    def test_launch_refuses_second_live_process(self):
        supervisor = Supervisor()
        supervisor.child = mock.Mock()
        supervisor.child.poll.return_value = None
        with self.assertRaises(RuntimeError):
            supervisor.launch(Path("unused"), {})

    @mock.patch("phantom_supervisor.test_release", side_effect=RuntimeError("failed test"))
    @mock.patch("phantom_supervisor.snapshot")
    def test_failed_tests_never_request_shutdown(self, snapshot_mock, test):
        with tempfile.TemporaryDirectory() as folder:
            supervisor = Supervisor(folder)
            supervisor.run_dir = Path(folder) / "run"
            supervisor.release = Path(folder) / "old"
            supervisor.child = mock.Mock(pid=123)
            with self.assertRaises(RuntimeError):
                supervisor.update()
            self.assertFalse((supervisor.run_dir / "shutdown.json").exists())
            supervisor.child.wait.assert_not_called()

    @mock.patch("phantom_supervisor.test_release")
    @mock.patch("phantom_supervisor.snapshot")
    def test_failed_candidate_rolls_back_once_after_old_process_exits(self, snapshot_mock, test):
        with tempfile.TemporaryDirectory() as folder:
            supervisor = Supervisor(folder)
            supervisor.run_dir = Path(folder) / "run"
            supervisor.release = Path(folder) / "old"
            supervisor.child = mock.Mock()
            supervisor.child.pid = 123
            supervisor.child.poll.side_effect = [None, 1]
            write_json(supervisor.run_dir / "ack.json", {"ok": True, "request_id": "test", "resume": {"active": True}})
            supervisor.launch = mock.Mock()
            supervisor.await_ready = mock.Mock(side_effect=[False, True])
            with mock.patch("phantom_supervisor.uuid.uuid4", return_value=mock.Mock(hex="test")):
                supervisor.update()
            self.assertEqual(supervisor.launch.call_count, 2)
            self.assertEqual(supervisor.launch.call_args_list[-1].args[0], Path(folder) / "old")
            self.assertEqual(read_json(supervisor.control / "status.json")["status"], "running")
            supervisor.child.wait.assert_called_once_with(timeout=20)
            supervisor.child.kill.assert_not_called()

    @mock.patch("phantom_supervisor.test_release")
    @mock.patch("phantom_supervisor.snapshot")
    def test_hung_candidate_is_not_killed_or_overlapped(self, snapshot_mock, test):
        with tempfile.TemporaryDirectory() as folder:
            supervisor = Supervisor(folder)
            supervisor.run_dir = Path(folder) / "run"
            supervisor.release = Path(folder) / "old"
            supervisor.child = mock.Mock(pid=123)
            supervisor.child.poll.return_value = None
            write_json(supervisor.run_dir / "ack.json", {"ok": True, "request_id": "test", "resume": {}})
            supervisor.launch = mock.Mock()
            supervisor.await_ready = mock.Mock(return_value=False)
            with mock.patch("phantom_supervisor.uuid.uuid4", return_value=mock.Mock(hex="test")):
                supervisor.update()
            self.assertEqual(supervisor.launch.call_count, 1)
            supervisor.child.kill.assert_not_called()
            self.assertEqual(read_json(supervisor.control / "status.json")["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
