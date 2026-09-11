"""Local supervisor protocol. No network endpoint and no game inputs here."""
import json
import os
import threading
import time
from pathlib import Path


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.{threading.get_ident()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    for attempt in range(10):
        try:
            os.replace(temporary, path)
            break
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(.01)  # Windows reader may briefly hold the old file open.


def read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


class InstanceLock:
    """OS-owned lock, released even if a process exits unexpectedly."""
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        import msvcrt
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if os.fstat(self.handle.fileno()).st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            self.handle = None
            raise RuntimeError("PHANTOM zaten acik; ikinci kopya baslatilmadi")
        return self

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None


class ManagedLifecycle:
    def __init__(self, api, window, run_dir):
        self.api = api
        self.window = window
        self.run_dir = Path(run_dir)
        self.stop_event = threading.Event()
        self.loaded = threading.Event()
        self.thread = None
        self.status = "loading"
        self.detail = ""
        self.restarting = False

    def on_loaded(self):
        self.loaded.set()

    def on_closing(self):
        if not self.restarting:
            write_json(self.run_dir / "user_closed.json", {"pid": os.getpid()})
        # Cancel window closure if workers have not released their input paths.
        return self.api.quiesce_for_update(force=True).get("ok", False)

    def start(self):
        self.thread = threading.Thread(target=self.run, name="PHANTOM-lifecycle", daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.stop_event.wait(.25):
                if self.loaded.is_set() and self.status == "loading":
                    resume = read_json(self.run_dir / "resume.json")
                    outcome = self.api.resume_after_update(resume)
                    self.status = "ready" if outcome.get("ok") else "paused"
                    self.detail = outcome.get("reason", "")
                write_json(self.run_dir / "health.json", {
                    "pid": os.getpid(), "ts": time.time(), "status": self.status,
                    "run_id": self.run_dir.name,
                    "detail": self.detail, "active": bool(self.api.st.aktif),
                })
                request = read_json(self.run_dir / "shutdown.json")
                if request.get("pid") != os.getpid() or request.get("operation") != "update":
                    continue
                if time.time() > request.get("deadline", 0):
                    write_json(self.run_dir / "ack.json", {"ok": False, "request_id": request.get("id"), "reason": "safe-point timeout"})
                    continue
                outcome = self.api.quiesce_for_update()
                if not outcome.get("ok"):
                    self.detail = outcome.get("reason", "safe point bekleniyor")
                    continue
                self.restarting = True
                outcome["request_id"] = request.get("id")
                write_json(self.run_dir / "ack.json", outcome)
                self.window.destroy()
                return
        except Exception as exc:
            write_json(self.run_dir / "health.json", {
                "pid": os.getpid(), "ts": time.time(), "status": "error", "detail": str(exc),
                "run_id": self.run_dir.name,
            })

    def close(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
