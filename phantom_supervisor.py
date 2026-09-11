"""PHANTOM local release supervisor: run / update / status.

Only this supervisor's child can be stopped. Game processes are never touched.
Source snapshots are immutable during execution; rollback changes a pointer,
never overwrites the user's working tree. No automatic download or git push.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from src.phantom.lifecycle import InstanceLock, read_json, write_json

ROOT = Path(__file__).resolve().parent
CONTROL = ROOT / "runtime" / "manager"
TEST_PATTERNS = (
    "test_lifecycle.py", "test_supervisor.py", "test_diagnostic_video.py",
    "test_death_publication.py", "test_revive*.py", "test_window_locks.py",
    "test_survival.py", "test_combat*.py", "test_recovery_sequence.py",
    "test_search_sequence.py", "test_client_routing.py", "test_buff_sequence.py",
    "test_directml_backend.py", "test_rumeli2_captcha.py",
)


def release_files(root):
    root = Path(root).resolve()
    candidates = [root / "metin_bot_webview.py", root / "index.html", root / "phantom_supervisor.py"]
    for directory, suffixes in (("src", {".py"}), ("tests", {".py", ".npz", ".png"}),
                                ("templates", {".png"})):
        for path in (root / directory).rglob("*"):
            relative = path.relative_to(root)
            if any(p in {"__pycache__", "hp_templates", "rumeli2_captcha"} for p in relative.parts):
                continue
            if path.is_file() and path.suffix in suffixes:
                candidates.append(path)
    for path in sorted(candidates):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Snapshot path escapes project")
        if path.is_file():
            yield path


def snapshot(root, releases):
    root, releases = Path(root), Path(releases)
    folder = releases / uuid.uuid4().hex
    folder.mkdir(parents=True)
    manifest = {}
    for source in release_files(root):
        relative = source.relative_to(root)
        target = folder / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        target.write_bytes(data)
        manifest[relative.as_posix()] = hashlib.sha256(data).hexdigest()
    write_json(folder / "manifest.json", manifest)
    return folder


def verify_snapshot(folder):
    folder = Path(folder).resolve()
    manifest = read_json(folder / "manifest.json")
    if not manifest or "metin_bot_webview.py" not in manifest:
        raise ValueError("Missing release manifest")
    for name, digest in manifest.items():
        path = (folder / name).resolve()
        if not path.is_relative_to(folder) or not path.is_file():
            raise ValueError("Invalid release path")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Release changed after tests: " + name)


def test_release(folder, python, log_path):
    verify_snapshot(folder)
    # Explicit local tests only; no shell or request-supplied commands.
    script = (
        "import pathlib,unittest; "
        "[compile(p.read_bytes(),str(p),'exec') for p in pathlib.Path('src').rglob('*.py')]; "
        f"s=unittest.TestSuite(unittest.defaultTestLoader.discover('tests',pattern=p) for p in {TEST_PATTERNS!r}); "
        "n=s.countTestCases(); r=unittest.TextTestRunner(verbosity=2).run(s); "
        "raise SystemExit(not(r.wasSuccessful() and n>0))"
    )
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for name in ("PHANTOM_MANAGED_RUN", "PHANTOM_DATA_ROOT"):
        env.pop(name, None)
    with Path(log_path).open("w", encoding="utf-8") as output:
        result = subprocess.run([str(python), "-B", "-c", script], cwd=folder,
            env=env, stdout=output, stderr=subprocess.STDOUT, timeout=180,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    verify_snapshot(folder)
    if result.returncode:
        raise RuntimeError("Tests failed; running bot was not touched. " + str(log_path))


class Supervisor:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.control = self.root / "runtime" / "manager"
        self.python = self.root / ".venv" / "Scripts" / "python.exe"
        self.gui_python = self.root / ".venv" / "Scripts" / "pythonw.exe"
        self.child = None
        self.worker_pid = None
        self.run_dir = None
        self.release = None
        self.session = uuid.uuid4().hex
        self.owns_lock = False

    def status(self, status, detail=""):
        write_json(self.control / "status.json", {
            "pid": os.getpid(), "session": self.session, "ts": time.time(),
            "status": status, "detail": detail,
            "child_pid": self.child.pid if self.child else None,
            "worker_pid": self.worker_pid,
            "run_dir": str(self.run_dir or ""), "release": str(self.release or ""),
        })

    def launch(self, release, resume):
        if self.child and self.child.poll() is None:
            raise RuntimeError("Old process still alive; new process refused")
        verify_snapshot(release)
        self.run_dir = self.control / "runs" / uuid.uuid4().hex
        self.worker_pid = None
        self.run_dir.mkdir(parents=True)
        write_json(self.run_dir / "resume.json", resume)
        env = dict(os.environ, PHANTOM_DATA_ROOT=str(self.root),
            PHANTOM_MANAGED_RUN=str(self.run_dir), PHANTOM_GUI_LAUNCH="1",
            PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
        executable = self.gui_python if self.gui_python.exists() else self.python
        self.child = subprocess.Popen([str(executable), "-B", str(release / "metin_bot_webview.py")],
            cwd=self.root, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.release = release

    def await_ready(self, timeout=90):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.child.poll() is not None:
                return False
            health = read_json(self.run_dir / "health.json")
            if (health.get("run_id") == self.run_dir.name and health.get("pid", 0) > 0
                    and time.time()-health.get("ts", 0) < 5
                    and health.get("status") in ("ready", "paused")):
                # Windows venv redirector PID can differ from the Python worker PID.
                self.worker_pid = health["pid"]
                # 'paused' intentionally does not bypass changed client/config checks.
                return True
            if health.get("status") == "error":
                return False
            time.sleep(.25)
        return False

    def update(self):
        old_release = self.release
        self.status("testing")
        candidate = snapshot(self.root, self.control / "releases")
        test_release(candidate, self.python, self.control / "tests_latest.log")
        if self.child.poll() is not None:
            raise RuntimeError("Application was closed during tests; update cancelled")
        self.status("waiting_safe_point")
        request_id = uuid.uuid4().hex
        write_json(self.run_dir / "shutdown.json", {
            "pid": self.worker_pid, "operation": "update", "deadline": time.time()+120, "id": request_id,
        })
        deadline = time.monotonic()+125
        ack = {}
        while time.monotonic() < deadline:
            if (self.run_dir / "user_closed.json").exists():
                raise RuntimeError("User closed application; automatic resume cancelled")
            ack = read_json(self.run_dir / "ack.json")
            if ack and ack.get("request_id") == request_id:
                break
            ack = {}
            if self.child.poll() is not None:
                raise RuntimeError("Old application exited without safe acknowledgement")
            time.sleep(.25)
        if not ack.get("ok"):
            raise RuntimeError("Safe shutdown not confirmed; no replacement started")
        try:
            self.child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            raise RuntimeError("Old process did not exit; no forced kill or second bot")
        resume = ack.get("resume", {})
        self.launch(candidate, resume)
        self.status("starting_candidate")
        if self.await_ready():
            write_json(self.control / "current.json", {"release": str(candidate), "previous": str(old_release)})
            self.status("running", "Update loaded; live gameplay still requires observation")
            return
        # Never force-kill an unresponsive process or start a concurrent bot.
        if self.child.poll() is None:
            self.status("blocked", "Candidate is unresponsive; manual intervention required, no second bot started")
            return
        if (self.run_dir / "user_closed.json").exists():
            self.status("stopped", "User closed candidate; no automatic restart")
            return
        self.launch(old_release, resume)
        self.status("rolling_back")
        if not self.await_ready():
            self.status("blocked", "Rollback did not become ready; no retry loop")
            return
        self.status("running", "Candidate startup failed; previous release restored")

    def run(self):
        lock = InstanceLock(self.control / "supervisor.lock").acquire()
        self.owns_lock = True
        try:
            saved = read_json(self.control / "current.json")
            release = Path(saved.get("release", ""))
            if not saved or not release.resolve().is_relative_to((self.control / "releases").resolve()):
                release = snapshot(self.root, self.control / "releases")
                test_release(release, self.python, self.control / "tests_latest.log")
            self.launch(release, {})  # Manual first launch remains idle.
            self.status("starting")
            if not self.await_ready():
                self.status("blocked", "Initial application did not become ready")
                return
            write_json(self.control / "current.json", {"release": str(release)})
            self.status("running")
            handled = None
            while self.child.poll() is None:
                request = read_json(self.control / "request.json")
                if (request.get("session") == self.session and request.get("operation") == "update"
                        and request.get("id") != handled and time.time()-request.get("ts", 0) < 30):
                    handled = request["id"]
                    try:
                        self.update()
                    except Exception as exc:
                        self.status("update_failed", str(exc))
                current = read_json(self.control / "status.json")
                self.status(current.get("status", "running"), current.get("detail", ""))
                time.sleep(.5)
            self.status("stopped", "Application exited; not restarted without an update request")
        finally:
            lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "update", "status"), nargs="?", default="run")
    args = parser.parse_args()
    if args.command == "run":
        supervisor = Supervisor()
        try:
            supervisor.run()
        except Exception as exc:
            # pythonw has no console; preserve startup errors for the operator.
            if supervisor.owns_lock:
                supervisor.status("error", str(exc))
            raise
    elif args.command == "status":
        print(json.dumps(read_json(CONTROL / "status.json"), ensure_ascii=False, indent=2))
    else:
        status = read_json(CONTROL / "status.json")
        if time.time()-status.get("ts", 0) > 5 or status.get("status") not in ("running", "update_failed"):
            raise SystemExit("Supervisor hazir degil; PHANTOM.bat ile baslatin")
        write_json(CONTROL / "request.json", {"operation": "update", "session": status["session"],
            "id": uuid.uuid4().hex, "ts": time.time()})
        print("Guncelleme istendi; sonuc icin status komutunu kullanin.")


if __name__ == "__main__":
    main()
