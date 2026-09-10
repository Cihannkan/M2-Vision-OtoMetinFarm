"""Low-rate desktop video evidence synchronized with PHANTOM event logs."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import mss
import numpy as np


DIAGNOSTIC_VIDEO_FPS = 2.0
DIAGNOSTIC_VIDEO_SEGMENT_SECONDS = 5 * 60
DIAGNOSTIC_VIDEO_MAX_WIDTH = 1280
DIAGNOSTIC_VIDEO_MAX_HEIGHT = 720
DIAGNOSTIC_VIDEO_RETENTION_DAYS = 2
DIAGNOSTIC_VIDEO_MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
DIAGNOSTIC_VIDEO_PREFIX = "phantom_diag_"
DIAGNOSTIC_VIDEO_SUFFIXES = {".mp4", ".avi", ".jsonl"}


def fit_even_frame_size(width, height, max_width=1280, max_height=720):
    """Fit a frame inside the limit and return codec-friendly even dimensions."""
    width = max(2, int(width))
    height = max(2, int(height))
    scale = min(1.0, float(max_width) / width, float(max_height) / height)
    target_width = max(2, int(round(width * scale)))
    target_height = max(2, int(round(height * scale)))
    target_width -= target_width % 2
    target_height -= target_height % 2
    return target_width, target_height


def segment_paths(output_dir, session_id, part, extension=".mp4"):
    """Return matching video and timestamp-sidecar paths for a segment."""
    output = Path(output_dir)
    stem = f"{DIAGNOSTIC_VIDEO_PREFIX}{session_id}_part{int(part):03d}"
    return output / f"{stem}{extension}", output / f"{stem}.jsonl"


def prune_diagnostic_recordings(
    output_dir,
    retention_days=DIAGNOSTIC_VIDEO_RETENTION_DAYS,
    max_total_bytes=DIAGNOSTIC_VIDEO_MAX_TOTAL_BYTES,
    now=None,
):
    """Delete only PHANTOM diagnostic recordings outside retention limits."""
    output = Path(output_dir)
    if not output.exists():
        return []
    now = time.time() if now is None else float(now)
    cutoff = now - max(0.0, float(retention_days)) * 86400.0
    candidates = [
        path
        for path in output.iterdir()
        if path.is_file()
        and path.name.startswith(DIAGNOSTIC_VIDEO_PREFIX)
        and path.suffix.lower() in DIAGNOSTIC_VIDEO_SUFFIXES
    ]
    removed = []

    for path in list(candidates):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(str(path))
                candidates.remove(path)
        except OSError:
            continue

    sized = []
    for path in candidates:
        try:
            stat = path.stat()
            sized.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            continue
    total = sum(item[1] for item in sized)
    limit = max(0, int(max_total_bytes))
    for _mtime, size, path in sorted(sized):
        if total <= limit:
            break
        try:
            path.unlink()
            removed.append(str(path))
            total -= size
        except OSError:
            continue
    return removed


def annotate_diagnostic_frame(frame, epoch, context=None, monitor=None):
    """Overlay wall-clock and per-client routing data without changing the desktop."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return frame
    context = dict(context or {})
    monitor = dict(monitor or {})
    left = int(monitor.get("left", 0) or 0)
    top = int(monitor.get("top", 0) or 0)
    height, width = frame.shape[:2]

    local_stamp = datetime.fromtimestamp(float(epoch)).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S.%f"
    )[:-3]
    bot_text = "BOT ON" if context.get("bot_active") else "BOT OFF"
    foreground = int(context.get("foreground_hwnd", 0) or 0)
    header = f"PHANTOM DIAG  {local_stamp}  {bot_text}  FG={foreground}"
    cv2.rectangle(frame, (5, 5), (min(width - 5, 790), 34), (0, 0, 0), -1)
    cv2.putText(
        frame,
        header,
        (12, 26),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
        cv2.LINE_AA,
    )

    cursor = context.get("cursor")
    if isinstance(cursor, (list, tuple)) and len(cursor) == 2:
        try:
            cursor_x = int(cursor[0]) - left
            cursor_y = int(cursor[1]) - top
            if 0 <= cursor_x < width and 0 <= cursor_y < height:
                cv2.drawMarker(
                    frame,
                    (cursor_x, cursor_y),
                    (255, 255, 255),
                    cv2.MARKER_CROSS,
                    18,
                    2,
                    cv2.LINE_AA,
                )
                cv2.circle(frame, (cursor_x, cursor_y), 9, (0, 0, 0), 1, cv2.LINE_AA)
        except (TypeError, ValueError):
            pass

    colors = ((46, 204, 113), (246, 164, 59), (92, 141, 255))
    for item in context.get("clients", []) or []:
        try:
            client_id = int(item.get("client", 0) or 0)
            rect = item.get("rect")
            if not rect or len(rect) != 4:
                continue
            x1, y1, x2, y2 = [int(value) for value in rect]
            x1 -= left
            x2 -= left
            y1 -= top
            y2 -= top
            if x2 <= 0 or y2 <= 0 or x1 >= width or y1 >= height:
                continue
            x1, x2 = max(0, x1), min(width - 1, x2)
            y1, y2 = max(0, y1), min(height - 1, y2)
            color = colors[(max(1, client_id) - 1) % len(colors)]
            thickness = 3 if int(item.get("hwnd", 0) or 0) == foreground else 1
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
            hp_fill = item.get("hp_fill")
            hp_text = "--" if hp_fill is None else f"{float(hp_fill) * 100:.1f}%"
            label = (
                f"C{client_id} H={int(item.get('hwnd', 0) or 0)} "
                f"{item.get('state', '?')} G{int(item.get('generation', 0) or 0)} "
                f"HP={hp_text} V={int(bool(item.get('hp_sample_valid', False)))}"
            )
            label_y = min(height - 8, max(48, y1 + 20))
            cv2.putText(
                frame,
                label,
                (max(5, x1 + 6), label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                (0, 0, 0),
                3,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                label,
                (max(5, x1 + 6), label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.48,
                color,
                1,
                cv2.LINE_AA,
            )
        except (TypeError, ValueError):
            continue
    return frame


class DiagnosticVideoRecorder(threading.Thread):
    """Record low-FPS, rotating desktop evidence while the PHANTOM app is open."""

    def __init__(
        self,
        output_dir,
        context_provider=None,
        log_callback=None,
        enabled=True,
        fps=DIAGNOSTIC_VIDEO_FPS,
        segment_seconds=DIAGNOSTIC_VIDEO_SEGMENT_SECONDS,
        max_width=DIAGNOSTIC_VIDEO_MAX_WIDTH,
        max_height=DIAGNOSTIC_VIDEO_MAX_HEIGHT,
        retention_days=DIAGNOSTIC_VIDEO_RETENTION_DAYS,
        max_total_bytes=DIAGNOSTIC_VIDEO_MAX_TOTAL_BYTES,
        capture_factory=None,
        writer_factory=None,
    ):
        super().__init__(daemon=True, name="PHANTOM-DiagnosticVideo")
        self.output_dir = os.path.abspath(str(output_dir))
        self.context_provider = context_provider
        self.log_callback = log_callback
        self.fps = max(0.2, float(fps))
        self.segment_seconds = max(10.0, float(segment_seconds))
        self.max_width = max(320, int(max_width))
        self.max_height = max(240, int(max_height))
        self.retention_days = max(0.0, float(retention_days))
        self.max_total_bytes = max(0, int(max_total_bytes))
        self.capture_factory = capture_factory or mss.mss
        self.writer_factory = writer_factory or cv2.VideoWriter
        started = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        self.session_id = f"{started}_p{os.getpid()}"

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._enabled = bool(enabled)
        self._writer = None
        self._metadata_file = None
        self._segment_started = 0.0
        self._segment_part = 0
        self._segment_frames = 0
        self._frame_size = None
        self._current_video = ""
        self._current_metadata = ""
        self._last_video = ""
        self._last_error = ""
        self._last_error_log = 0.0
        self._total_frames = 0

    def _log(self, level, message):
        if self.log_callback is None:
            return
        try:
            self.log_callback(level, message)
        except Exception:
            pass

    def set_enabled(self, enabled):
        with self._lock:
            self._enabled = bool(enabled)
        return self.status()

    def is_enabled(self):
        with self._lock:
            return self._enabled

    def stop(self):
        self._stop_event.set()

    def status(self):
        with self._lock:
            return {
                "enabled": self._enabled,
                "recording": self._writer is not None,
                "current_file": self._current_video,
                "current_metadata": self._current_metadata,
                "last_file": self._last_video,
                "last_error": self._last_error,
                "fps": self.fps,
                "segment_seconds": self.segment_seconds,
                "total_frames": self._total_frames,
                "output_dir": self.output_dir,
            }

    def _set_error(self, message):
        message = str(message or "bilinmeyen hata")
        with self._lock:
            self._last_error = message
        now = time.time()
        if now - self._last_error_log >= 10.0:
            self._last_error_log = now
            self._log("warn", f"[VIDEO] tani kaydi hatasi: {message}")

    def _close_segment(self):
        writer = self._writer
        metadata = self._metadata_file
        self._writer = None
        self._metadata_file = None
        if writer is not None:
            try:
                writer.release()
            except Exception:
                pass
        if metadata is not None:
            try:
                metadata.flush()
                metadata.close()
            except Exception:
                pass
        with self._lock:
            if self._current_video:
                self._last_video = self._current_video
            self._current_video = ""
            self._current_metadata = ""
            self._frame_size = None

    def _open_segment(self, frame_size, epoch):
        self._close_segment()
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        self._segment_part += 1
        choices = ((".mp4", "mp4v"), (".avi", "MJPG"))
        writer = None
        video_path = None
        metadata_path = None
        for extension, codec in choices:
            candidate, sidecar = segment_paths(
                self.output_dir,
                self.session_id,
                self._segment_part,
                extension,
            )
            try:
                candidate_writer = self.writer_factory(
                    str(candidate),
                    cv2.VideoWriter_fourcc(*codec),
                    self.fps,
                    tuple(frame_size),
                )
                if candidate_writer is not None and candidate_writer.isOpened():
                    writer = candidate_writer
                    video_path = candidate
                    metadata_path = sidecar
                    break
                if candidate_writer is not None:
                    candidate_writer.release()
            except Exception:
                continue
        if writer is None or video_path is None or metadata_path is None:
            raise RuntimeError("MP4 ve AVI video yazicisi acilamadi")

        metadata_file = open(metadata_path, "w", encoding="utf-8", buffering=1)
        header = {
            "type": "segment",
            "session": self.session_id,
            "part": self._segment_part,
            "video": video_path.name,
            "fps": self.fps,
            "size": list(frame_size),
            "started_epoch": float(epoch),
            "started_local": datetime.fromtimestamp(float(epoch)).astimezone().isoformat(),
        }
        metadata_file.write(json.dumps(header, ensure_ascii=False) + "\n")

        self._writer = writer
        self._metadata_file = metadata_file
        self._segment_started = float(epoch)
        self._segment_frames = 0
        with self._lock:
            self._frame_size = tuple(frame_size)
            self._current_video = str(video_path)
            self._current_metadata = str(metadata_path)
            self._last_error = ""
        self._log(
            "info",
            f"[VIDEO] tani kaydi basladi: {video_path.name} "
            f"({self.fps:.1f} FPS, {frame_size[0]}x{frame_size[1]}, ses yok)",
        )
        prune_diagnostic_recordings(
            self.output_dir,
            retention_days=self.retention_days,
            max_total_bytes=self.max_total_bytes,
            now=epoch,
        )

    def _context(self):
        if self.context_provider is None:
            return {}
        try:
            return dict(self.context_provider() or {})
        except Exception as exc:
            self._set_error(f"durum bilgisi alinamadi: {exc}")
            return {}

    def _write_frame(self, frame, epoch, monitor, context):
        height, width = frame.shape[:2]
        frame_size = fit_even_frame_size(
            width,
            height,
            self.max_width,
            self.max_height,
        )
        if (width, height) != frame_size:
            frame = cv2.resize(frame, frame_size, interpolation=cv2.INTER_AREA)
        if (
            self._writer is None
            or self._frame_size != tuple(frame_size)
            or float(epoch) - self._segment_started >= self.segment_seconds
        ):
            self._open_segment(frame_size, epoch)

        self._writer.write(frame)
        self._segment_frames += 1
        self._total_frames += 1
        metadata = {
            "type": "frame",
            "frame": self._segment_frames - 1,
            "epoch": float(epoch),
            "local": datetime.fromtimestamp(float(epoch)).astimezone().isoformat(),
            "monitor": {
                "left": int(monitor.get("left", 0) or 0),
                "top": int(monitor.get("top", 0) or 0),
                "width": int(monitor.get("width", width) or width),
                "height": int(monitor.get("height", height) or height),
            },
            "context": context,
        }
        self._metadata_file.write(json.dumps(metadata, ensure_ascii=False) + "\n")
        with self._lock:
            self._total_frames = int(self._total_frames)

    def run(self):
        try:
            Path(self.output_dir).mkdir(parents=True, exist_ok=True)
            prune_diagnostic_recordings(
                self.output_dir,
                retention_days=self.retention_days,
                max_total_bytes=self.max_total_bytes,
            )
        except Exception as exc:
            self._set_error(f"video klasoru hazirlanamadi: {exc}")
            return
        next_frame = time.monotonic()
        try:
            with self.capture_factory() as capture:
                while not self._stop_event.is_set():
                    if not self.is_enabled():
                        self._close_segment()
                        next_frame = time.monotonic()
                        self._stop_event.wait(0.25)
                        continue

                    now_mono = time.monotonic()
                    if now_mono < next_frame:
                        self._stop_event.wait(min(0.25, next_frame - now_mono))
                        continue
                    next_frame = now_mono + (1.0 / self.fps)

                    try:
                        monitor = dict(capture.monitors[0])
                        raw = np.asarray(capture.grab(monitor), dtype=np.uint8)
                        frame = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
                        epoch = time.time()
                        context = self._context()
                        annotate_diagnostic_frame(frame, epoch, context, monitor)
                        self._write_frame(frame, epoch, monitor, context)
                    except Exception as exc:
                        self._set_error(str(exc))
                        self._close_segment()
                        self._stop_event.wait(1.0)
        finally:
            self._close_segment()
