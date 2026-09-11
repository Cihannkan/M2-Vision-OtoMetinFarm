"""PHANTOM v6 â€” Metin2 AI Bot (Tam Yeniden YapÄ±landÄ±rma)"""
import os
import sys
import time
import json
import copy
import random
import base64
import ctypes
import threading
import re
import difflib
import unicodedata
import glob
import hashlib
import subprocess
from collections import deque

import cv2
import mss
import keyboard
import numpy as np
import win32gui
import win32api
import webview
import tkinter as tk
from tkinter import filedialog

import torch

from ..diagnostic_video import DiagnosticVideoRecorder
from ..lifecycle import InstanceLock, ManagedLifecycle
from ..vision.directml import create_detection_model, preferred_backend
from ..vision.survival import detect_death_menu, own_hp_visible, remember_failed_target, filter_failed_targets
from ..vision.combat import (
    estimate_red_fill,
    estimate_scene_motion,
    filter_targets_away_from,
    hp_panel_structure_mask,
    hp_panel_presence_vote,
    is_credible_hp_bar,
    is_hp_panel_authoritative,
    is_plausible_hp_sample,
    locate_hp_bar,
    match_hp_panel_anchor,
    prepare_scene_frame,
    rank_target_candidates,
    track_hp_progress,
)
from ..automation.buffs import (
    BUFF_AFTER_ALT_SEQUENCE,
    BUFF_ALT_ARM_DELAY_SECONDS,
    BUFF_ALT_SEQUENCE,
    BUFF_DISMOUNT_DELAY_SECONDS,
    BUFF_INTERVAL_SECONDS,
    BUFF_KEY_HOLD_SECONDS,
)
from .client_routing import (
    CLIENT_IDS,
    duplicate_client_ids,
    shared_rumeli2_calibration_updates,
    validate_client_assignment,
)

# Windows fare/klavye girdileri sistem genelidir. Tum istemci islemleri ayni
# yeniden-girilebilir kilidi kullanir; boylece odak bir client'tayken baska bir
# thread o client'a ait tus veya tiklamayi araya sokamaz.
input_transaction_lock = threading.RLock()
sol_tik_lock = threading.Lock()

try:
    from ..captcha.solver import CaptchaWatcher, captcha_status_blocks_input
    CAPTCHA_OK = True
except ImportError:
    CAPTCHA_OK = False

    def captcha_status_blocks_input(status):
        return bool(status and status != "dialog_yok")

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
RELEASE_ROOT = os.path.abspath(os.path.join(PACKAGE_DIR, "..", "..", ".."))
PROJECT_ROOT = os.path.abspath(os.environ.get("PHANTOM_DATA_ROOT", RELEASE_ROOT))
SCRIPT_DIR = PROJECT_ROOT
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config_phantom.json")
HTML_FILE = os.path.join(RELEASE_ROOT, "index.html")
HP_TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "templates", "hp_templates")
MESSAGE_TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "templates", "message_templates")
RUMELI2_CALIBRATION_DIR = os.path.join(PROJECT_ROOT, "templates", "rumeli2_captcha")
RUNTIME_DIR = os.path.join(PROJECT_ROOT, "runtime")
LOG_DIR = os.path.join(RUNTIME_DIR, "logs")
EVIDENCE_DIR = os.path.join(RUNTIME_DIR, "evidence")
DIAGNOSTIC_VIDEO_DIR = os.path.join(EVIDENCE_DIR, "videos")
HP_TEMPLATE_SCALES = [1.0, 0.75, 0.50, 0.25]
HP_TEMPLATE_MIN_SCORE = 0.70
HP_TEMPLATE_MIN_WIDTH = 8
HP_PANEL_SEARCH_MARGIN = 12
HP_PANEL_CONFIRM_FRAMES = 3
HP_PANEL_CONFIRM_VOTES = 2
HP_PANEL_MIN_INITIAL_FILL = 0.08
MESSAGE_TEMPLATE_SCALES = [1.0, 0.90, 0.80, 1.10]
MESSAGE_TEMPLATE_MIN_SCORE = 0.68
MESSAGE_REPLY_TEXTS = [
    "selam",
    "efendim",
    "buyur",
    "nasıl yardımcı olayım",
    "bir sorun mu var",
    "buradayım sorun mu var",
    "yardımcı olayım mı",
    "dinliyorum",
]
MESSAGE_ACTION_COOLDOWN = 6.0
MESSAGE_OCR_MIN_CONF = 0.20
MESSAGE_FARM_PAUSE_SECONDS = 0.0
LOOT_BURST_TAPS = 6
LOOT_TAP_INTERVAL = 0.08
LOOT_POST_KILL_DELAY = 0.12
LOOT_KEY_HOLD_SECONDS = 0.08
LOOT_KILL_TAPS = 12
LOOT_KILL_DELAY = 0.55
LOOT_KILL_INTERVAL = 0.14
DEFAULT_TARGET_FRAME_MAX_AGE = 1.20
CAPTCHA_OCR_INIT_GRACE_SECONDS = 3.0
TARGET_STABLE_RADIUS = 8
TARGET_STABLE_MAX_FRAME_GAP = 0.20
GLOBAL_PAUSE_WARN_AFTER = 20.0
GLOBAL_PAUSE_WARN_EVERY = 15.0
WINDOW_ISSUE_LOG_INTERVAL = 8.0
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024
LOG_RETENTION_DAYS = 7
EVIDENCE_RETENTION_DAYS = 14
TERMINAL_HIDDEN_INFO_PREFIXES = (
    "[LOOT] hedef sonrasi",
    "Client 1 captcha status:",
    "Client 2 captcha status:",
    "Client 3 captcha status:",
)
FIXED_CONF_ESIK = 0.50
FIXED_DOGRULAMA_SN = 5.0
FIXED_HP_BEKLEME_SN = 0.80
FIXED_ANTI_HAREKETSIZ_SN = 4.0
FIXED_ANTI_KURTARMA_BEKLEME_SN = 3.0
SCENE_SAMPLE_INTERVAL_SN = 0.20
APPROACH_HP_DROP_MIN = 0.018
APPROACH_HP_DROP_CONFIRM_SN = 0.25
APPROACH_INITIAL_STILL_SN = 8.0
APPROACH_NO_PANEL_TIMEOUT_SN = 5.0
RECOVERY_SKILL_KEY = "1"
RECOVERY_SKILL_TAP_SN = 0.10
RECOVERY_SKILL_WAIT_SN = 4.0
RECOVERY_RECLICK_TIMEOUT_SN = 4.0
RECOVERY_RECLICK_RADIUS = 240.0
# Uc manevra ve aralarindaki hasar kontrolleri icin yeterli sure tani.
APPROACH_MAX_SN = 45.0
APPROACH_RECOVERY_MAX = 3
APPROACH_POST_RECOVERY_WAIT_SN = RECOVERY_SKILL_WAIT_SN
APPROACH_BLOCKED_TARGET_SN = 11.0
VISION_STALE_FRAME_SN = 2.0
VISION_STALE_LOG_EVERY_SN = 5.0
# 106 px'lik Rumeli2 cubugunda tek piksel yaklasik %0.94'tur. Eski %1.2
# esigi iki piksel bekledigi icin dusuk hasarda 6sn'lik sahte takilma uretiyordu.
COMBAT_HP_PROGRESS_MIN = 0.006
COMBAT_NO_PROGRESS_SN = 6.0
COMBAT_POST_RECOVERY_WAIT_SN = RECOVERY_SKILL_WAIT_SN
COMBAT_RECOVERY_MAX = 3
# Son gorulen can sifira cok yakinsa panelin kapanmasi olum kanitidir. Daha
# yuksek canda kaybolan panel belirsizdir; loot veya hedef degisimi uretmez.
COMBAT_DEATH_LOW_HP_MAX = 0.06
COMBAT_DEATH_MIN_ABSENT_SAMPLES = 3
# Ust uste binen oyun pencerelerinde mss alttaki client'in HP paneli yerine
# ustteki pencerenin piksellerini gorebilir. Kisa kaybi tolere et; sonra hedef
# client'i odaga alip mevcut kademeli kurtarma dizisini uygula. Uc deneme veya
# mutlak sure siniri sonunda yanlis kill/loot uretmeden hedefi birak.
COMBAT_PANEL_LOST_RECOVERY_SN = 6.0
COMBAT_PANEL_LOST_TIMEOUT_SN = 45.0
HP_MAX_UPWARD_JUMP = 0.04
HP_DIAGNOSTIC_INTERVAL_SN = 1.50
COMBAT_DIAGNOSTIC_INTERVAL_SN = 1.50
METIN_SEARCH_Q_ATTEMPTS = 4
METIN_SEARCH_Q_HOLD_SN = 1.0
METIN_SEARCH_Q_SETTLE_SN = 0.40
METIN_SEARCH_KEYS = ("q",) * METIN_SEARCH_Q_ATTEMPTS + ("g", "t")
os.makedirs(HP_TEMPLATE_DIR, exist_ok=True)
os.makedirs(MESSAGE_TEMPLATE_DIR, exist_ok=True)
os.makedirs(RUMELI2_CALIBRATION_DIR, exist_ok=True)
os.makedirs(RUNTIME_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(EVIDENCE_DIR, exist_ok=True)

_log_file_lock = threading.Lock()

def _cleanup_runtime_dir(path, max_age_days, keep_suffixes=None):
    keep_suffixes = tuple(keep_suffixes or ())
    try:
        cutoff = time.time() - (float(max_age_days) * 86400.0)
        for name in os.listdir(path):
            full = os.path.join(path, name)
            if not os.path.isfile(full):
                continue
            if keep_suffixes and not name.lower().endswith(keep_suffixes):
                continue
            try:
                if os.path.getmtime(full) < cutoff:
                    os.remove(full)
            except Exception:
                pass
    except Exception:
        pass

def _rotated_log_path():
    path = os.path.join(LOG_DIR, f"events_{time.strftime('%Y%m%d')}.jsonl")
    try:
        if os.path.exists(path) and os.path.getsize(path) >= MAX_LOG_FILE_BYTES:
            idx = 1
            while True:
                rotated = os.path.join(LOG_DIR, f"events_{time.strftime('%Y%m%d')}_{idx}.jsonl")
                if not os.path.exists(rotated):
                    os.replace(path, rotated)
                    break
                idx += 1
    except Exception:
        pass
    return path

def _safe_file_part(text, limit=48):
    cleaned = "".join(ch if ch.isalnum() or ch in ("_", "-", "+", "=") else "_" for ch in str(text or ""))
    cleaned = cleaned.strip("_") or "event"
    return cleaned[:limit]

def _should_show_terminal_log(level, message):
    lvl = str(level or "").lower()
    msg = str(message or "")
    if lvl == "debug":
        return False
    if lvl in ("error", "critical", "kritik", "warn", "warning"):
        return True
    if any(msg.startswith(prefix) for prefix in TERMINAL_HIDDEN_INFO_PREFIXES):
        return False
    return True

def log_event(state, level, message):
    event_epoch = time.time()
    local_time = time.localtime(event_epoch)
    milliseconds = int((event_epoch - int(event_epoch)) * 1000)
    entry = {
        "ts": f"{time.strftime('%H:%M:%S', local_time)}.{milliseconds:03d}",
        "epoch": round(event_epoch, 3),
        "level": level,
        "message": message,
    }
    if _should_show_terminal_log(level, message):
        with state.lk:
            state.logs.append(entry)
    try:
        line = dict(entry)
        line["date"] = time.strftime("%Y-%m-%d", local_time)
        path = _rotated_log_path()
        with _log_file_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        pass

def save_evidence_capture(event, client_label, image=None, hwnd=None, bbox=None, meta=None, state=None):
    """Kritik olaylar icin PNG + JSON kanit kaydi olusturur."""
    crop = None
    source = "none"
    if image is not None and getattr(image, "size", 0):
        try:
            if bbox:
                x1, y1, x2, y2 = [int(v) for v in bbox]
                h, w = image.shape[:2]
                x1 = max(0, min(x1, w - 1)); y1 = max(0, min(y1, h - 1))
                x2 = max(x1 + 1, min(x2, w)); y2 = max(y1 + 1, min(y2, h))
                crop = image[y1:y2, x1:x2].copy()
                source = "frame_crop"
            else:
                crop = image.copy()
                source = "frame"
        except Exception:
            crop = None
    if (crop is None or crop.size == 0) and hwnd:
        try:
            r = win32gui.GetWindowRect(hwnd)
            if r[0] >= -32000 and r[2] > r[0] and r[3] > r[1]:
                with mss.mss() as sct:
                    shot = np.array(sct.grab({
                        "left": int(r[0]), "top": int(r[1]),
                        "width": int(r[2] - r[0]), "height": int(r[3] - r[1])
                    }), dtype=np.uint8)
                crop = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
                source = "live_window"
        except Exception:
            crop = None
    if crop is None or crop.size == 0:
        if state:
            log_event(state, "warn", f"[KANIT] {event} goruntusu kaydedilemedi ({client_label})")
        return None

    ts = time.strftime("%Y%m%d_%H%M%S")
    ms = int((time.time() % 1.0) * 1000)
    event_part = _safe_file_part(event, 24)
    client_part = _safe_file_part(client_label, 28)
    base = f"{event_part}_{client_part}_{ts}_{ms:03d}"
    img_path = os.path.join(EVIDENCE_DIR, base + ".png")
    json_path = os.path.join(EVIDENCE_DIR, base + ".json")
    if not cv2.imwrite(img_path, crop):
        if state:
            log_event(state, "warn", f"[KANIT] {event} goruntusu yazilamadi: {img_path}")
        return None
    payload = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "client": client_label,
        "source": source,
        "image": img_path,
        "meta": meta or {},
    }
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    if state:
        log_event(state, "info", f"[KANIT] {event} kaydedildi: {img_path}")
    return img_path

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  SendInput YapÄ±larÄ± (DonanÄ±msal TÄ±klama â€” Anti-Cheat Bypass)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
PUL = ctypes.POINTER(ctypes.c_ulong)
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx",ctypes.c_long),("dy",ctypes.c_long),("mouseData",ctypes.c_ulong),
                ("dwFlags",ctypes.c_ulong),("time",ctypes.c_ulong),("dwExtraInfo",PUL)]
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk",ctypes.c_ushort),("wScan",ctypes.c_ushort),
                ("dwFlags",ctypes.c_ulong),("time",ctypes.c_ulong),("dwExtraInfo",PUL)]
class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi",MOUSEINPUT),("ki",KEYBDINPUT)]
class INPUT(ctypes.Structure):
    _fields_ = [("type",ctypes.c_ulong),("iu",INPUT_UNION)]

_extra = ctypes.c_ulong(0)
def _send_mouse(flags):
    iu = INPUT_UNION(); iu.mi = MOUSEINPUT(0,0,0,flags,0,ctypes.pointer(_extra))
    cmd = INPUT(0, iu)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(cmd), ctypes.sizeof(cmd))

def _send_keyboard_scancode(scancode, key_up=False):
    """Windows SendInput ile fiziksel tarama kodu gonder; teslim sayisini dondur."""
    flags = 0x0008 | (0x0002 if key_up else 0)  # SCANCODE | KEYUP
    iu = INPUT_UNION()
    iu.ki = KEYBDINPUT(0, int(scancode), flags, 0, ctypes.pointer(_extra))
    cmd = INPUT(1, iu)  # INPUT_KEYBOARD
    try:
        sent = ctypes.windll.user32.SendInput(1, ctypes.pointer(cmd), ctypes.sizeof(cmd))
        return int(sent) == 1
    except Exception:
        return False

def _send_keyboard_scancode_tap(scancode, delay=0.05):
    down_ok = _send_keyboard_scancode(scancode, key_up=False)
    time.sleep(max(0.0, float(delay)))
    up_ok = _send_keyboard_scancode(scancode, key_up=True)
    return bool(down_ok and up_ok)

def _sol_tik_sendinput(x, y):
    bx, by = win32api.GetCursorPos()
    dist = np.hypot(x-bx, y-by)
    if dist >= 10:
        steps = max(10, min(int(dist/20), 55))
        for i in range(steps):
            t = 1-(1-i/steps)**2
            ctypes.windll.user32.SetCursorPos(int(bx+(x-bx)*t), int(by+(y-by)*t))
            time.sleep(random.uniform(0.002, 0.005))
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(random.uniform(0.08, 0.12))
    _send_mouse(0x0002)  # LEFTDOWN
    time.sleep(random.uniform(0.06, 0.10))
    _send_mouse(0x0004)  # LEFTUP

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Interception Kernel Driver â€” Ã–ncelikli GiriÅŸ
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class _IMouseStroke(ctypes.Structure):
    _fields_ = [
        ("state",       ctypes.c_ushort),
        ("flags",       ctypes.c_ushort),
        ("rolling",     ctypes.c_short),
        ("x",           ctypes.c_int),
        ("y",           ctypes.c_int),
        ("information", ctypes.c_uint),
    ]

class _IKeyStroke(ctypes.Structure):
    """Interception klavye stroke yapÄ±sÄ± (InterceptionKeyStroke)."""
    _fields_ = [
        ("code",        ctypes.c_ushort),   # PS/2 scan kodu
        ("state",       ctypes.c_ushort),   # 0=down 1=up 2=e0_down 3=e0_up
        ("information", ctypes.c_ulong),
    ]

# Interception klavye state sabitleri
_IKDOWN = 0x00   # key down
_IKUP   = 0x01   # key up

# PS/2 scan kodlarÄ± (Interception set-1)
_SC = {
    'ctrl':  0x1D,   # Left Ctrl
    'g':     0x22,
    'v':     0x2F,
    'enter': 0x1C,
    '1':     0x02,
    '2':     0x03,
    's':     0x1F,
    'a':     0x1E,
    'd':     0x20,
    'q':     0x10,
    'z':     0x2C,
    'space': 0x39,   # Space bar
}

_IMDN  = 0x0001   # LEFT_BUTTON_DOWN
_IMUP  = 0x0002   # LEFT_BUTTON_UP
_IMRDN = 0x0004   # RIGHT_BUTTON_DOWN
_IMRUP = 0x0008   # RIGHT_BUTTON_UP
_IMABS = 0x0001   # MOVE_ABSOLUTE
_IMVD  = 0x0002   # VIRTUAL_DESKTOP (Ã§ok monitÃ¶r desteÄŸi)

_ilib = None
_icx  = None
_idev = 11        # Interception mouse device (11-20)
_ikdev = None     # Interception keyboard device (1-10)
INTERCEPTION_OK = False

def _interception_init():
    global _ilib, _icx, _idev, _ikdev, INTERCEPTION_OK
    for path in [os.path.join(SCRIPT_DIR, "interception.dll"), "interception.dll"]:
        try:
            lib = ctypes.WinDLL(path)
            lib.interception_create_context.restype  = ctypes.c_void_p
            lib.interception_create_context.argtypes = []
            lib.interception_destroy_context.restype  = None
            lib.interception_destroy_context.argtypes = [ctypes.c_void_p]
            lib.interception_send.restype  = ctypes.c_int
            lib.interception_send.argtypes = [
                ctypes.c_void_p, ctypes.c_int,
                ctypes.c_void_p, ctypes.c_uint,   # void* â€” hem mouse hem klavye stroke geÃ§er
            ]
            lib.interception_is_invalid.restype  = ctypes.c_int
            lib.interception_is_invalid.argtypes = [ctypes.c_int]
            ctx = lib.interception_create_context()
            if not ctx:
                continue
            # Mouse device bul (11-20)
            found_mouse = 11
            for dev in range(11, 21):
                if lib.interception_is_invalid(dev) == 0:
                    found_mouse = dev
                    break
            # Klavye device bul (1-10)
            found_kb = None
            for dev in range(1, 11):
                if lib.interception_is_invalid(dev) == 0:
                    found_kb = dev
                    break
            _ilib, _icx, _idev, _ikdev = lib, ctx, found_mouse, found_kb
            INTERCEPTION_OK = True
            return True
        except Exception:
            pass
    return False

_interception_init()

def _ik_send(scancode, state):
    """Interception Ã¼zerinden tek bir klavye olayÄ± gÃ¶nder."""
    if not _ilib or not _icx or _ikdev is None:
        return False
    try:
        s = _IKeyStroke(code=scancode, state=state, information=0)
        sent = _ilib.interception_send(_icx, _ikdev, ctypes.byref(s), 1)
        return int(sent) == 1
    except Exception:
        return False

def _ik_tap(scancode, delay=0.05):
    """Bir tuÅŸa basÄ±p bÄ±rak (Interception Ã¼zerinden)."""
    _ik_send(scancode, _IKDOWN)
    time.sleep(delay)
    _ik_send(scancode, _IKUP)

def _ik_ctrl_tap(key_scancode, delay=0.05):
    """Ctrl+<tuÅŸ> kombinasyonu (Interception Ã¼zerinden)."""
    _ik_send(_SC['ctrl'], _IKDOWN)
    time.sleep(0.03)
    _ik_send(key_scancode, _IKDOWN)
    time.sleep(delay)
    _ik_send(key_scancode, _IKUP)
    time.sleep(0.03)
    _ik_send(_SC['ctrl'], _IKUP)

def _virtual_screen_rect():
    vx = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    vy = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    vw = ctypes.windll.user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    vh = ctypes.windll.user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if vw <= 0 or vh <= 0:
        vx, vy = 0, 0
        vw = ctypes.windll.user32.GetSystemMetrics(0)
        vh = ctypes.windll.user32.GetSystemMetrics(1)
    return vx, vy, vw, vh

def _interception_abs_coords(px, py):
    vx, vy, vw, vh = _virtual_screen_rect()
    nx = int((int(px) - vx) * 65535 / max(vw - 1, 1))
    ny = int((int(py) - vy) * 65535 / max(vh - 1, 1))
    return max(0, min(65535, nx)), max(0, min(65535, ny))

def _cursor_near(x, y, tolerance=25):
    try:
        cx, cy = win32api.GetCursorPos()
        return np.hypot(cx - int(x), cy - int(y)) <= tolerance
    except Exception:
        return True

def _interception_send_mouse(stroke):
    if not _ilib or not _icx:
        return False
    try:
        return _ilib.interception_send(_icx, _idev, ctypes.byref(stroke), 1) > 0
    except Exception:
        return False

def _sol_tik_interception(x, y):

    def _move(px, py):
        nx, ny = _interception_abs_coords(px, py)
        s = _IMouseStroke(state=0, flags=_IMABS | _IMVD, rolling=0, x=nx, y=ny, information=0)
        return _interception_send_mouse(s)

    bx, by = win32api.GetCursorPos()
    dist = np.hypot(x - bx, y - by)
    if dist >= 10:
        steps = max(10, min(int(dist / 20), 55))
        for i in range(steps):
            t = 1 - (1 - i / steps) ** 2
            if not _move(int(bx + (x - bx) * t), int(by + (y - by) * t)):
                return False
            time.sleep(random.uniform(0.002, 0.005))
    if not _move(int(x), int(y)):
        return False
    time.sleep(random.uniform(0.08, 0.12))
    if not _cursor_near(x, y):
        return False
    if not _interception_send_mouse(_IMouseStroke(state=_IMDN, flags=0, rolling=0, x=0, y=0, information=0)):
        return False
    time.sleep(random.uniform(0.06, 0.10))
    return _interception_send_mouse(_IMouseStroke(state=_IMUP, flags=0, rolling=0, x=0, y=0, information=0))

def _sag_tik_sendinput(x, y):
    bx, by = win32api.GetCursorPos()
    dist = np.hypot(x-bx, y-by)
    if dist >= 10:
        steps = max(10, min(int(dist/20), 55))
        for i in range(steps):
            t = 1-(1-i/steps)**2
            ctypes.windll.user32.SetCursorPos(int(bx+(x-bx)*t), int(by+(y-by)*t))
            time.sleep(random.uniform(0.002, 0.005))
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    time.sleep(random.uniform(0.08, 0.12))
    _send_mouse(0x0008)  # RIGHTDOWN
    time.sleep(random.uniform(0.06, 0.10))
    _send_mouse(0x0010)  # RIGHTUP

def _sag_tik_interception(x, y):

    def _move(px, py):
        nx, ny = _interception_abs_coords(px, py)
        s = _IMouseStroke(state=0, flags=_IMABS | _IMVD, rolling=0, x=nx, y=ny, information=0)
        return _interception_send_mouse(s)

    bx, by = win32api.GetCursorPos()
    dist = np.hypot(x - bx, y - by)
    if dist >= 10:
        steps = max(10, min(int(dist / 20), 55))
        for i in range(steps):
            t = 1 - (1 - i / steps) ** 2
            if not _move(int(bx + (x - bx) * t), int(by + (y - by) * t)):
                return False
            time.sleep(random.uniform(0.002, 0.005))
    if not _move(int(x), int(y)):
        return False
    time.sleep(random.uniform(0.08, 0.12))
    if not _cursor_near(x, y):
        return False
    if not _interception_send_mouse(_IMouseStroke(state=_IMRDN, flags=0, rolling=0, x=0, y=0, information=0)):
        return False
    time.sleep(random.uniform(0.06, 0.10))
    return _interception_send_mouse(_IMouseStroke(state=_IMRUP, flags=0, rolling=0, x=0, y=0, information=0))

_sag_tik_lock = threading.Lock()

def sag_tik_hw(x, y, hwnd=None):
    """SaÄŸ tÄ±k â€” Interception driver yÃ¼klÃ¼yse kernel-level, yoksa SendInput."""
    with input_transaction_lock:
        if hwnd and not pencere_odakla(hwnd):
            return "focus_failed"
        if not _sag_tik_lock.acquire(blocking=False):
            return "blocked"
        try:
            if INTERCEPTION_OK and not _force_sendinput:
                if _sag_tik_interception(x, y):
                    return "interception"
                _sag_tik_sendinput(x, y)
                return "sendinput_fallback"
            _sag_tik_sendinput(x, y)
            return "sendinput"
        finally:
            _sag_tik_lock.release()

_force_sendinput = False  # TÄ±klama modu otomatik: Interception varsa kullanÄ±lÄ±r, yoksa SendInput.

def sol_tik_hw(x, y, hwnd=None):
    """Interception driver yÃ¼klÃ¼yse kernel-level tÄ±klama yapar, yoksa SendInput kullanÄ±r."""
    with input_transaction_lock:
        if hwnd and not pencere_odakla(hwnd):
            return "focus_failed"
        if not sol_tik_lock.acquire(blocking=False):
            return "blocked"
        try:
            if INTERCEPTION_OK and not _force_sendinput:
                if _sol_tik_interception(x, y):
                    return "interception"
                _sol_tik_sendinput(x, y)
                return "sendinput_fallback"
            _sol_tik_sendinput(x, y)
            return "sendinput"
        finally:
            sol_tik_lock.release()

def sol_tik_hw_shift_callback():
    """SHIFT+LeftClick iÃ§in callback."""
    x, y = win32api.GetCursorPos()
    sol_tik_hw(x, y)

_shift_tik_lock = threading.Lock()

def shift_sol_tik_hw(x, y, hwnd=None):
    """Shift+Sol tÄ±k."""
    with input_transaction_lock:
        if hwnd and not pencere_odakla(hwnd):
            return "focus_failed"
        if not _shift_tik_lock.acquire(blocking=False):
            return "blocked"
        try:
            keyboard.press('shift')
            try:
                if INTERCEPTION_OK and not _force_sendinput:
                    if _sol_tik_interception(x, y):
                        return "interception"
                    _sol_tik_sendinput(x, y)
                    return "sendinput_fallback"
                _sol_tik_sendinput(x, y)
                return "sendinput"
            finally:
                keyboard.release('shift')
        finally:
            _shift_tik_lock.release()

def shift_sag_tik_hw(x, y, hwnd=None):
    """Shift+SaÄŸ tÄ±k."""
    with input_transaction_lock:
        if hwnd and not pencere_odakla(hwnd):
            return "focus_failed"
        if not _shift_tik_lock.acquire(blocking=False):
            return "blocked"
        try:
            keyboard.press('shift')
            try:
                if INTERCEPTION_OK and not _force_sendinput:
                    if _sag_tik_interception(x, y):
                        return "interception"
                    _sag_tik_sendinput(x, y)
                    return "sendinput_fallback"
                _sag_tik_sendinput(x, y)
                return "sendinput"
            finally:
                keyboard.release('shift')
        finally:
            _shift_tik_lock.release()

def _tiklama_yap(cfg, x, y, hwnd=None):
    """Config'deki tiklama_turu'na gÃ¶re doÄŸru tÄ±klama fonksiyonunu Ã§aÄŸÄ±rÄ±r."""
    turu = cfg.g("tiklama_turu") or "default"
    if turu == "right":
        return sag_tik_hw(x, y, hwnd)
    elif turu == "shift_left":
        return shift_sol_tik_hw(x, y, hwnd)
    elif turu == "shift_right":
        return shift_sag_tik_hw(x, y, hwnd)
    else:  # default / left â€” sol tÄ±k (mevcut davranÄ±ÅŸ)
        return sol_tik_hw(x, y, hwnd)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Pencere YardÄ±mcÄ±larÄ±
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def pencereleri_getir():
    lst = ["Yok","TÃ¼m Ekran"]
    def cb(h,r):
        if win32gui.IsWindowVisible(h):
            t = win32gui.GetWindowText(h)
            if t and t != "Program Manager": r.append(f"{t} (ID: {h})")
    win32gui.EnumWindows(cb, lst); return lst

def hwnd_al(val):
    if not val or val in ("Yok","TÃ¼m Ekran"): return None
    try: return int(val.split("(ID: ")[1].replace(")",""))
    except: return None


def _diagnostic_video_context(cfg, state):
    """Build JSON-safe routing state for the timestamp sidecar and overlay."""
    try:
        foreground_hwnd = int(win32gui.GetForegroundWindow() or 0)
        foreground_title = win32gui.GetWindowText(foreground_hwnd) if foreground_hwnd else ""
    except Exception:
        foreground_hwnd = 0
        foreground_title = ""
    try:
        cursor = [int(value) for value in win32api.GetCursorPos()]
    except Exception:
        cursor = None

    with state.lk:
        bot_active = bool(state.aktif)
        device = str(state.cihaz or "")
        states = dict(state.durum)
        target_generations = dict(state.target_generation)
        vision_data = dict(state.wdata)
        pause = {
            "active": bool(state.global_pause_active),
            "kind": str(state.global_pause_kind or ""),
            "owner": str(state.global_pause_owner or ""),
        }

    clients = []
    for client_id in CLIENT_IDS:
        client_cfg = cfg.client(client_id)
        window_key = str(client_cfg.get("pencere", "Yok") or "Yok")
        hwnd = int(hwnd_al(window_key) or 0)
        rect = None
        visible = False
        iconic = False
        if hwnd:
            try:
                visible = bool(win32gui.IsWindowVisible(hwnd))
                iconic = bool(win32gui.IsIconic(hwnd))
                raw_rect = win32gui.GetWindowRect(hwnd)
                rect = [int(value) for value in raw_rect]
            except Exception:
                rect = None
        data = vision_data.get(window_key, {}) or {}
        hp_fill = data.get("hp_fill")
        clients.append({
            "client": int(client_id),
            "active": bool(client_cfg.get("aktif", True)),
            "window": window_key,
            "hwnd": hwnd,
            "rect": rect,
            "visible": visible,
            "minimized": iconic,
            "foreground": hwnd != 0 and hwnd == foreground_hwnd,
            "state": str(states.get(window_key, "BEKLIYOR")),
            "generation": int(target_generations.get(window_key, 0) or 0),
            "hp_visible": bool(data.get("hp_var", False)),
            "hp_fill": None if hp_fill is None else float(hp_fill),
            "hp_sample_valid": bool(data.get("hp_sample_valid", False)),
            "hp_anchor_score": float(data.get("hp_anchor_score", 0.0) or 0.0),
            "hp_bar_score": float(data.get("hp_bar_score", 0.0) or 0.0),
            "targets": len(data.get("merkezler", []) or []),
            "frame_epoch": float(data.get("ts", 0.0) or 0.0),
        })
    return {
        "bot_active": bot_active,
        "device": device,
        "foreground_hwnd": foreground_hwnd,
        "foreground_title": str(foreground_title or ""),
        "cursor": cursor,
        "global_pause": pause,
        "clients": clients,
    }

def pencere_odakla(hwnd):
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    try:
        if win32gui.GetForegroundWindow() == hwnd:
            return True
        # Minimize ise geri ac.
        if win32gui.IsIconic(hwnd):
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            time.sleep(0.05)
        # Foreground lock sÃ¼resini 0 yap (baÅŸka pencereye geÃ§iÅŸi zorla)
        ctypes.windll.user32.SystemParametersInfoW(0x2001, 0, None, 0)  # SPI_SETFOREGROUNDLOCKTIMEOUT
        ctypes.windll.user32.AllowSetForegroundWindow(-1)
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        deadline = time.time() + 0.35
        while time.time() < deadline:
            if win32gui.GetForegroundWindow() == hwnd:
                return True
            time.sleep(0.025)
        return win32gui.GetForegroundWindow() == hwnd
    except Exception:
        return False

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Config (per-client ayÄ±rÄ±mlÄ±)
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
def _clipboard_set_text(text):
    """Unicode metni Windows panosuna koyar."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    GMEM_ZEROINIT = 0x0040

    data = ctypes.create_unicode_buffer(str(text) + "\0")
    size = ctypes.sizeof(data)

    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_int
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    hmem = kernel32.GlobalAlloc(GMEM_MOVEABLE | GMEM_ZEROINIT, size)
    if not hmem:
        return False
    locked = kernel32.GlobalLock(hmem)
    if not locked:
        kernel32.GlobalFree(hmem)
        return False
    ctypes.memmove(locked, ctypes.addressof(data), size)
    kernel32.GlobalUnlock(hmem)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(hmem)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, hmem):
            kernel32.GlobalFree(hmem)
            return False
        hmem = None
        return True
    finally:
        user32.CloseClipboard()
        if hmem:
            kernel32.GlobalFree(hmem)

def _normalize_outgoing_text(text):
    replacements = {
        "Ä±": "ı",
        "Ä°": "İ",
        "Ã§": "ç",
        "Ã‡": "Ç",
        "Ã¶": "ö",
        "Ã–": "Ö",
        "Ã¼": "ü",
        "Ãœ": "Ü",
        "ÄŸ": "ğ",
        "Äž": "Ğ",
        "ÅŸ": "ş",
        "Åž": "Ş",
    }
    value = str(text or "")
    for bad, good in replacements.items():
        value = value.replace(bad, good)
    return value

def _paste_text_and_enter(text, hwnd=None):
    text = _normalize_outgoing_text(text)
    with input_transaction_lock:
        if hwnd and not pencere_odakla(hwnd):
            return False
        if not _clipboard_set_text(text):
            return False
        time.sleep(0.08)
        if _ikdev is not None and INTERCEPTION_OK and not _force_sendinput:
            _ik_ctrl_tap(_SC['v'], delay=0.05)
            time.sleep(0.10)
            _ik_tap(_SC['enter'], delay=0.04)
        else:
            keyboard.send('ctrl+v')
            time.sleep(0.10)
            keyboard.send('enter')
        return True

def _client_varsayilan():
    return {
        "aktif":True,"pencere":"Yok","conf_esik":FIXED_CONF_ESIK,"oto_loot":True,
        "hp_region":[0.02,0.07,0.30,0.70],"hp_bekleme_sn":FIXED_HP_BEKLEME_SN,"hp_stuck_timeout":20,
        "hp_fill_region":None,"hp_fill_region_custom":False,
        "hp_panel_auto":False,"hp_auto_bar_region":None,"hp_panel_calibration_size":None,
        "ignore_radius":35,"captcha":False,"debug_on":True,"message_captcha":True,
        "loot_taps":LOOT_BURST_TAPS,"loot_interval":LOOT_TAP_INTERVAL,"loot_delay":LOOT_POST_KILL_DELAY,
        "captcha_tip1":False,"captcha_tip2":False,"captcha_tip3":False,"captcha_tip4":False,
        "captcha_rumeli2":False,"rumeli2_question_region":None,"rumeli2_option_regions":[],
        "rumeli2_calibration_size":None,
        "cember_yaricap":200,
        "cember_aktif":True,
    }

VARSAYILAN = {
    "model_yolu":"",
    "eco_mode":False,
    "conf_esik":FIXED_CONF_ESIK,
    "dogrulama_sn":FIXED_DOGRULAMA_SN,
    "hp_bekleme_sn":FIXED_HP_BEKLEME_SN,
    "oto_loot":True,
    "loot_taps":LOOT_BURST_TAPS,
    "loot_interval":LOOT_TAP_INTERVAL,
    "loot_delay":LOOT_POST_KILL_DELAY,
    "captcha":False,
    "message_captcha":True,
    "captcha_tip1":False,
    "captcha_tip2":False,
    "captcha_tip3":False,
    "captcha_tip4":False,
    "captcha_rumeli2":False,
    "cember_yaricap":200,
    "cember_aktif":True,
    "mesafe_kontrol_aktif":True,
    "anti_sucuk":False,
    "diagnostic_video_enabled":True,
    "c1":_client_varsayilan(),
    "c2":_client_varsayilan(),
    "c3":{**_client_varsayilan(), "aktif":False},
}

SHARED_CLIENT_SETTINGS = {
    "conf_esik", "dogrulama_sn", "hp_bekleme_sn", "oto_loot",
    "loot_taps", "loot_interval", "loot_delay", "captcha",
    "message_captcha", "captcha_tip1", "captcha_tip2", "captcha_tip3",
    "captcha_tip4", "captcha_rumeli2", "anti_sucuk",
}

class Cfg:
    def __init__(self):
        self.d = copy.deepcopy(VARSAYILAN)
        self.lk = threading.Lock()
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE,"r",encoding="utf-8") as f:
                    saved = json.load(f)
                    for k in saved:
                        if k in self.d and isinstance(self.d[k], dict) and isinstance(saved[k], dict):
                            self.d[k].update(saved[k])
                        else:
                            self.d[k] = saved[k]
            except: pass
        self._force_fixed_values()

    def _force_fixed_values(self):
        self.d["conf_esik"] = FIXED_CONF_ESIK
        self.d["dogrulama_sn"] = FIXED_DOGRULAMA_SN
        self.d["hp_bekleme_sn"] = FIXED_HP_BEKLEME_SN
        anti_on = bool(self.d.get("anti_sucuk", False))
        for stale_key in (
            "anti_aranma_aktif", "anti_aranma_sn", "anti_stuck_sn",
            "anti_hareketsiz_sn", "anti_kurtarma_bekleme_sn",
        ):
            self.d.pop(stale_key, None)
        self.d.pop("hedef_kuyruk_aktif", None)
        self.d.pop("hedef_kuyruk_sayisi", None)
        for key in (f"c{ci}" for ci in CLIENT_IDS):
            self.d.setdefault(key, _client_varsayilan())
            for shared_key in SHARED_CLIENT_SETTINGS:
                if shared_key in self.d:
                    self.d[key][shared_key] = self.d[shared_key]
            self.d[key]["conf_esik"] = FIXED_CONF_ESIK
            self.d[key]["dogrulama_sn"] = FIXED_DOGRULAMA_SN
            self.d[key]["hp_bekleme_sn"] = FIXED_HP_BEKLEME_SN
            self.d[key]["anti_sucuk"] = anti_on
            for stale_key in (
                "anti_aranma_aktif", "anti_aranma_sn", "anti_stuck_sn",
                "anti_hareketsiz_sn", "anti_kurtarma_bekleme_sn",
            ):
                self.d[key].pop(stale_key, None)
            self.d[key].pop("hedef_kuyruk_aktif", None)
            self.d[key].pop("hedef_kuyruk_sayisi", None)

    def save(self):
        with self.lk:
            self._force_fixed_values()
            with open(CONFIG_FILE,"w",encoding="utf-8") as f:
                json.dump(self.d, f, indent=2, ensure_ascii=False)

    def g(self, *keys):
        with self.lk:
            o = self.d
            for k in keys:
                if not isinstance(o, dict):
                    return None
                o = o.get(k)
                if o is None:
                    return None
            return o

    def s(self, val, *keys):
        with self.lk:
            o = self.d
            for k in keys[:-1]: o = o.setdefault(k, {})
            o[keys[-1]] = val
        self.save()

    def client(self, idx):
        """Istenen istemcinin ayarlarini kopya olarak dondurur."""
        k = f"c{idx}"
        with self.lk:
            self._force_fixed_values()
            return dict(self.d.get(k, _client_varsayilan()))

    def update_client(self, idx, data):
        k = f"c{idx}"
        with self.lk:
            if k not in self.d: self.d[k] = _client_varsayilan()
            self.d[k].update(data)
            self._force_fixed_values()
        self.save()

    def update_clients(self, updates_by_client):
        """Birden fazla client ayarini tek config yaziminda atomik gunceller."""
        with self.lk:
            for idx, data in dict(updates_by_client or {}).items():
                if idx not in CLIENT_IDS:
                    continue
                key = f"c{idx}"
                if key not in self.d:
                    self.d[key] = _client_varsayilan()
                self.d[key].update(dict(data or {}))
            self._force_fixed_values()
        self.save()

    def update_global(self, data):
        data = dict(data or {})
        for stale_key in (
            "anti_aranma_aktif", "anti_aranma_sn", "anti_stuck_sn",
            "anti_hareketsiz_sn", "anti_kurtarma_bekleme_sn",
        ):
            data.pop(stale_key, None)
        data.pop("hedef_kuyruk_aktif", None)
        data.pop("hedef_kuyruk_sayisi", None)
        with self.lk:
            for key, value in data.items():
                self.d[key] = value
                if key in SHARED_CLIENT_SETTINGS:
                    for ci in CLIENT_IDS:
                        self.d.setdefault(f"c{ci}", _client_varsayilan())[key] = value
            self._force_fixed_values()
        self.save()

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PaylaÅŸÄ±lan Durum
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class State:
    def __init__(self):
        self.lk = threading.Lock()
        self.aktif = False
        self.started_at = 0.0
        self.wdata = {}
        self.target_hp_evidence = {}
        self.frame_b64 = {}
        self.cihaz = "cpu"
        self.durum = {}
        self.captcha_block = {}
        self.captcha_cd = {}
        self.captcha_state = {}
        self.captcha_global_active = False
        self.captcha_global_owner = None
        self.captcha_global_since = 0.0
        self.message_global_active = False
        self.message_global_owner = None
        self.message_global_since = 0.0
        self.global_pause_active = False
        self.global_pause_kind = ""
        self.global_pause_owner = None
        self.global_pause_reason = ""
        self.global_pause_since = 0.0
        self.logs = deque(maxlen=500)
        self.target_memory = {}  # w â†’ {"positions": [(x,y),...], "consecutive_found": int, "confirmed": bool, "last_confirmed_pos": (x,y)}
        self.kill_counts = {}  # c1/c2/c3 -> int; eski pencere anahtarlari fallback olarak desteklenir
        self.message_farm_pause_until = {}
        # Her basarili hedef tiklamasi bu sayaci artirir. VisionThread kareyi
        # yakaladigi andaki nesli etiketler; boylece eski hedefin HP ornekleri
        # yeni hedefin can gecmisine karisamaz.
        self.target_generation = {}

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  Aksiyon Thread
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class ActionThread(threading.Thread):
    def __init__(self, cfg, state):
        super().__init__(daemon=True)
        self.cfg, self.st = cfg, state
        self._stop_event = threading.Event()
        self.dur = {}
        self.dogr_t = {}
        self.dogr_n = {}
        self._hp_onceki_durum = {}
        self._son_tiklama_t = {}
        self._hp_ignore_until = {}
        self._hp_kayip_t = {}
        self._loot_last_t = {}
        self._loot_log_t = {}
        self._loot_running = {}
        self._son_tiklama_zamani = {}
        self._default_fresh_log_t = {}
        self._araniyor_baslat_t = {}
        self._son_manevra_t = {}
        self._s_basmis = {}
        self._anti_sucuk_diag_t = {}
        self._approach = {}
        self._recovery_reclick = {}
        self._approach_diag_t = {}
        self._approach_blocked_target = {}
        self._stale_frame_diag_t = {}
        self._combat_progress = {}
        self._target_generation = {}
        self._last_target_sample = {}
        self._combat_diag_t = {}
        self._buff_next_t = {}
        self._buff_running = {}
        self._buff_needs_remount = {}
        self._buff_diag_t = {}

    def stop(self):
        self._stop_event.set()

    def _init(self, w):
        if w not in self.dur:
            self.dur[w]="ARANIYOR"
            self.dogr_t[w]=0; self.dogr_n[w]=0

    def _kill_count_key(self, client_idx=None):
        try:
            ci = int(client_idx)
        except (TypeError, ValueError):
            return None
        return f"c{ci}" if ci in CLIENT_IDS else None

    def _record_kill(self, w, client_idx=None):
        key = self._kill_count_key(client_idx) or w
        if not key:
            return
        with self.st.lk:
            self.st.kill_counts[key] = self.st.kill_counts.get(key, 0) + 1

    def _input_blocked(self, w=None, allow_revive=False):
        with self.st.lk:
            if self._stop_event.is_set() or not self.st.aktif:
                return True
            # CAPTCHA veya mesaj cevabi ekranda oldugunda fare/klavye sadece
            # ilgili watcher tarafindan kullanilir. Diger client aksiyonlari
            # pencere odagini arada degistiremez.
            if self.st.captcha_global_active or self.st.message_global_active:
                return True
            if w is not None and self.st.captcha_block.get(w, False):
                return True
            if w is not None and not allow_revive:
                life = getattr(self.st, "life_data", {}).get(w, {})
                if life.get("visible") or w in getattr(self, "_revive_state", {}):
                    return True
        return False

    def _handle_player_life(self, w, hwnd, client_idx):
        if not hasattr(self, "_revive_state"):
            self._revive_state = {}
        with self.st.lk:
            life = dict(getattr(self.st, "life_data", {}).get(w, {}))
        now = time.time()
        ts = float(life.get("ts", 0))
        pending = self._revive_state.get(w)
        if not life.get("visible") and pending is None:
            return False
        if pending is None:
            pending = self._revive_state[w] = {"seen": 0, "absent": 0, "tries": 0, "next": now, "last": 0}
            log_event(self.st, "warn", f"[CAN-C{client_idx}] karakter olum menusu goruldu; islemler durdu ({w})")
        self.dur[w] = "YENIDEN DOGMA"
        with self.st.lk:
            self.st.durum[w] = "YENIDEN DOGMA"
        if ts <= pending["last"] or now - ts > VISION_STALE_FRAME_SN or life.get("hwnd") != hwnd:
            return True
        if not life.get("foreground", True):
            # Occluded pixels say nothing about this client's life/menu state.
            # Keep the cursor timer, buff checkpoint and alive counter intact.
            if now < max(pending["next"], pending.get("focus_retry_at", 0)):
                return True
            refreshed = self._refresh_revive_life(w, hwnd)
            if refreshed is None:
                pending["focus_retry_at"] = time.time() + 2
                return True
            life = refreshed
            ts = float(life["ts"])
            if life.get("confirmed_alive"):
                pending["absent"] = 2  # Three fresh foreground captures below.
        pending["last"] = ts
        if life.get("visible"):
            pending.pop("buffs_done", None)
            pending.pop("buff_step", None)
            pending.pop("mounted", None)
            pending.pop("pre_buff_move_remaining", None)
            pending.pop("pre_buff_dismounted", None)
            pending["seen"] += 1
            pending["absent"] = 0
            if pending["seen"] < 2 or now < pending["next"]:
                return True
            if self._input_blocked(w, allow_revive=True) or self.st.global_pause_active:
                return True
            # Focus and capture again under the same input lock; never click stale coordinates.
            with input_transaction_lock:
                if not hwnd or not win32gui.IsWindow(hwnd) or not pencere_odakla(hwnd):
                    pending["next"] = now + 3
                    return True
                if (self._stop_event.wait(.2) or self._input_blocked(w, allow_revive=True)
                        or self.st.global_pause_active):
                    return True
                try:
                    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                    with mss.mss() as capture:
                        frame = cv2.cvtColor(np.array(capture.grab({"left": left, "top": top,
                            "width": right-left, "height": bottom-top})), cv2.COLOR_BGRA2BGR)
                    check = detect_death_menu(frame)
                    if not check.get("visible") or win32gui.GetForegroundWindow() != hwnd:
                        pending.pop("cursor_centered", None)
                        pending["next"] = now + 3
                        return True
                    if not pending.get("cursor_centered"):
                        win32api.SetCursorPos(((left + right) // 2, (top + bottom) // 2))
                        pending["cursor_centered"] = True
                        pending["next"] = time.time() + 10
                        log_event(self.st, "info", f"[CAN-C{client_idx}] imlec pencere merkezine tasindi; tiklama oncesi 10sn bekleniyor ({w})")
                        return True
                    x, y = check["button"]
                    if not self._move_revive_cursor(w, hwnd, (left + x, top + y)):
                        pending.pop("cursor_centered", None)
                        return True
                    log_event(self.st, "info", f"[CAN-C{client_idx}] imlec yeniden basla uzerinde; tiklama oncesi 2sn bekleniyor ({w})")
                    if not self._wait_revive_hover(w, hwnd, (left + x, top + y)):
                        pending.pop("cursor_centered", None)
                        return True
                    if win32gui.GetWindowRect(hwnd) != (left, top, right, bottom):
                        pending.pop("cursor_centered", None)
                        return True
                    with mss.mss() as capture:
                        frame = cv2.cvtColor(np.array(capture.grab({"left": left, "top": top,
                            "width": right-left, "height": bottom-top})), cv2.COLOR_BGRA2BGR)
                    final_check = detect_death_menu(frame)
                    if (not final_check.get("visible")
                            or max(abs(a-b) for a, b in zip(final_check.get("button", (0, 0)), (x, y))) > 4
                            or self._input_blocked(w, allow_revive=True) or self.st.global_pause_active
                            or win32gui.GetForegroundWindow() != hwnd):
                        pending.pop("cursor_centered", None)
                        return True
                    if not self._wiggle_revive_cursor(w, hwnd, (left + x, top + y)):
                        pending.pop("cursor_centered", None)
                        return True
                    mode = "wiggle_clicks"
                except Exception as exc:
                    pending.pop("cursor_centered", None)
                    log_event(self.st, "warn", f"[CAN-C{client_idx}] yeniden dogma kontrol hatasi: {exc}")
                    pending["next"] = now + 3
                    return True
            pending.pop("cursor_centered", None)
            pending["next"] = time.time()
            if mode not in ("blocked", "focus_failed"):
                pending["tries"] += 1
                log_event(self.st, "warn", f"[CAN-C{client_idx}] Burada yeniden basla tiklandi (deneme {pending['tries']}); menu kalirsa merkez ve 10sn bekleme tekrarlanacak")
            return True
        pending.pop("cursor_centered", None)
        pending["absent"] = pending["absent"] + 1 if life.get("own_hp") else 0
        if pending["absent"] < 3 or now < pending["next"]:
            return True
        if not pending.get("buffs_done"):
            if not self._prepare_revive_buffs(w, hwnd, pending):
                pending["next"] = time.time() + 3
                return True
            if not self._restore_revive_buffs(w, hwnd, pending):
                pending["next"] = time.time() + 3
                return True
            pending["buffs_done"] = True
            log_event(self.st, "info", f"[CAN-C{client_idx}] yeniden dogma guclendirme tuslari gonderildi ({w})")
        if not pending.get("mounted"):
            if self._revive_buff_blocked(w):
                return True
            if not self._mount_after_revive(w, hwnd):
                pending["next"] = now + 3
                return True
            pending["mounted"] = True
            self._buff_needs_remount[w] = False
            log_event(self.st, "info", f"[CAN-C{client_idx}] yeniden dogma sonrasi CTRL+G binis gonderildi ({w})")
        self._clear_approach(w)
        self._clear_combat_progress(w)
        self._hp_onceki_durum.pop(w, None)
        self._hp_kayip_t.pop(w, None)
        getattr(self, "_kilitli_hedef", {}).pop(w, None)
        self._hp_ignore_until[w] = float("inf")
        self._approach_blocked_target.pop(w, None)
        getattr(self, "_failed_targets", {}).pop(w, None)
        self._start_target_generation(w, client_idx, now)
        with self.st.lk:
            self.st.target_memory.pop(w, None)
        self._revive_state.pop(w, None)
        self.dur[w] = "ARANIYOR"
        self._araniyor_baslat_t[w] = now
        # Avoid an immediate dismount/remount from the buff cycle after mounting.
        self._buff_next_t[w] = time.time() + BUFF_INTERVAL_SECONDS
        log_event(self.st, "info", f"[CAN-C{client_idx}] yeniden dogma dogrulandi; eski hedef temizlendi ({w})")
        return True

    def _refresh_revive_life(self, w, hwnd):
        """Briefly own focus and collect fresh life evidence, never click here."""
        with input_transaction_lock:
            if (self._input_blocked(w, allow_revive=True) or self.st.global_pause_active
                    or not hwnd or not win32gui.IsWindow(hwnd) or not pencere_odakla(hwnd)):
                return None
            try:
                rect = win32gui.GetWindowRect(hwnd)
                left, top, right, bottom = rect
                alive = 0
                with mss.mss() as capture:
                    for _ in range(3):
                        if (self._stop_event.wait(.2) or self._input_blocked(w, allow_revive=True)
                                or self.st.global_pause_active or win32gui.GetForegroundWindow() != hwnd
                                or win32gui.GetWindowRect(hwnd) != rect):
                            return None
                        frame = cv2.cvtColor(np.array(capture.grab({"left": left, "top": top,
                            "width": right-left, "height": bottom-top})), cv2.COLOR_BGRA2BGR)
                        life = detect_death_menu(frame)
                        life.update(ts=time.time(), hwnd=hwnd, own_hp=own_hp_visible(frame), foreground=True)
                        if win32gui.GetForegroundWindow() != hwnd:
                            return None
                        if life.get("visible"):
                            break
                        alive = alive + 1 if life["own_hp"] else 0
                life["confirmed_alive"] = alive == 3
                with self.st.lk:
                    if not hasattr(self.st, "life_data"):
                        self.st.life_data = {}
                    if float(self.st.life_data.get(w, {}).get("ts", 0)) <= life["ts"]:
                        self.st.life_data[w] = dict(life)
                return life
            except Exception as exc:
                log_event(self.st, "warn", f"[CAN] odakli yeniden dogma kontrolu basarisiz: {exc} ({w})")
                return None

    def _move_revive_cursor(self, w, hwnd, position, click_midway=False):
        """Move to the revive button over ~0.6 seconds, without clicking."""
        start_x, start_y = win32api.GetCursorPos()
        for step in range(1, 31):
            if (self._stop_event.wait(.02) or self._input_blocked(w, allow_revive=True)
                    or self.st.global_pause_active or win32gui.GetForegroundWindow() != hwnd):
                return False
            fraction = step / 30.0
            fraction = fraction * fraction * (3 - 2 * fraction)
            point = (
                round(start_x + (position[0] - start_x) * fraction),
                round(start_y + (position[1] - start_y) * fraction),
            )
            win32api.SetCursorPos(point)
            if click_midway and step == 15:
                if not self._click_revive_at(w, hwnd, point):
                    return False
        return True

    def _click_revive_at(self, w, hwnd, point):
        # A previous click can dismiss the menu; never send the next one blindly.
        if (self._input_blocked(w, allow_revive=True) or self.st.global_pause_active
                or win32gui.GetForegroundWindow() != hwnd):
            return False
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        with mss.mss() as capture:
            frame = cv2.cvtColor(np.array(capture.grab({"left": left, "top": top,
                "width": right-left, "height": bottom-top})), cv2.COLOR_BGRA2BGR)
        check = detect_death_menu(frame)
        if not check.get("visible"):
            return False
        x, y = check["button"]
        if abs(point[0] - left - x) > 12 or abs(point[1] - top - y) > 6:
            return False
        if (self._input_blocked(w, allow_revive=True) or self.st.global_pause_active
                or win32gui.GetForegroundWindow() != hwnd):
            return False
        return sol_tik_hw(*point, hwnd) not in ("blocked", "focus_failed")

    def _wiggle_revive_cursor(self, w, hwnd, position):
        """Small horizontal sweep inside the button, ending at its center."""
        x, y = position
        for offset in (8, -8, 0):
            if not self._move_revive_cursor(w, hwnd, (x + offset, y), click_midway=offset != 0):
                return False
        return True

    def _wait_revive_hover(self, w, hwnd, position):
        # Keep the shared input lock at the caller only during this short hover.
        # The preceding ten-second wait remains non-blocking for other clients.
        for _ in range(40):
            if (self._stop_event.wait(.05) or self._input_blocked(w, allow_revive=True)
                    or self.st.global_pause_active or win32gui.GetForegroundWindow() != hwnd):
                return False
            cursor = win32api.GetCursorPos()
            if max(abs(a-b) for a, b in zip(cursor, position)) > 3:
                return False
        return True

    def _revive_buff_blocked(self, w):
        if self._input_blocked(w, allow_revive=True) or self.st.global_pause_active:
            return True
        with self.st.lk:
            life = dict(getattr(self.st, "life_data", {}).get(w, {}))
        return bool(life.get("visible") or not life.get("own_hp")
                    or time.time() - float(life.get("ts", 0)) > VISION_STALE_FRAME_SN)

    def _prepare_revive_buffs(self, w, hwnd, pending):
        """Revival is already mounted: move right, then dismount before buffs."""
        if pending.get("pre_buff_dismounted"):
            return True
        with input_transaction_lock:
            if self._revive_buff_blocked(w) or not hwnd or not pencere_odakla(hwnd):
                return False
            remaining = float(pending.get("pre_buff_move_remaining", 3.0))
            if remaining > 0:
                if self._revive_buff_blocked(w) or win32gui.GetForegroundWindow() != hwnd:
                    return False
                started = time.monotonic()
                try:
                    keyboard.press("d")
                    completed = self._wait_revive_buff(w, remaining)
                finally:
                    keyboard.release("d")
                    pending["pre_buff_move_remaining"] = max(0, remaining - (time.monotonic() - started))
                if not completed:
                    return False
                pending["pre_buff_move_remaining"] = 0
                log_event(self.st, "info", f"[CAN] guclendirme oncesi D 3sn tamamlandi ({w})")
            if self._revive_buff_blocked(w) or not self._mount_after_revive(w, hwnd):
                return False
            pending["pre_buff_dismounted"] = True
            log_event(self.st, "info", f"[CAN] guclendirme oncesi CTRL+G inis gonderildi ({w})")
            return self._wait_revive_buff(w, .2)

    def _restore_revive_buffs(self, w, hwnd, pending):
        """Restore buffs on foot, checkpointing sent keys; mount is a separate step."""
        steps = list(BUFF_ALT_SEQUENCE) + list(BUFF_AFTER_ALT_SEQUENCE)
        with input_transaction_lock:
            if self._revive_buff_blocked(w) or not hwnd or not pencere_odakla(hwnd):
                return False
            alt_pressed = False
            try:
                start = int(pending.get("buff_step", 0))
                if start < len(BUFF_ALT_SEQUENCE):
                    keyboard.press("alt")
                    alt_pressed = True
                    if not self._wait_revive_buff(w, BUFF_ALT_ARM_DELAY_SECONDS):
                        return False
                for index in range(start, len(steps)):
                    if index == len(BUFF_ALT_SEQUENCE) and alt_pressed:
                        keyboard.release("alt")
                        alt_pressed = False
                    if self._revive_buff_blocked(w) or win32gui.GetForegroundWindow() != hwnd:
                        return False
                    key, delay_after, _label = steps[index]
                    try:
                        keyboard.press(key)
                        # Never repeat a sent toggle if a later wait is interrupted.
                        pending["buff_step"] = index + 1
                        if not self._wait_revive_buff(w, BUFF_KEY_HOLD_SECONDS):
                            return False
                    finally:
                        keyboard.release(key)
                    if delay_after and not self._wait_revive_buff(w, delay_after):
                        return False
                return True
            finally:
                if alt_pressed:
                    keyboard.release("alt")

    def _wait_revive_buff(self, w, seconds):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self._stop_event.wait(min(.05, max(0, deadline - time.time()))):
                return False
            if self._revive_buff_blocked(w):
                return False
        return not self._revive_buff_blocked(w)

    def _mount_after_revive(self, w, hwnd):
        """Send one mount toggle after confirmed revival; always release keys."""
        with input_transaction_lock:
            if self._input_blocked(w, allow_revive=True) or self.st.global_pause_active:
                return False
            if not hwnd or not win32gui.IsWindow(hwnd) or not pencere_odakla(hwnd):
                return False
            pressed = []
            sent = False
            try:
                if self._input_blocked(w, allow_revive=True):
                    return False
                keyboard.press("ctrl")
                pressed.append("ctrl")
                keyboard.press("g")
                pressed.append("g")
                sent = True
                self._stop_event.wait(BUFF_KEY_HOLD_SECONDS)
            finally:
                for key in reversed(pressed):
                    try:
                        keyboard.release(key)
                    except Exception:
                        pass
            # Once sent, a stop request must not cause a second toggle on resume.
            return sent

    def _remember_target_failure(self, w, now):
        if not hasattr(self, "_failed_targets"):
            self._failed_targets = {}
        history = self._failed_targets.setdefault(w, [])
        remember_failed_target(history, getattr(self, "_kilitli_hedef", {}).get(w), now)

    def _filter_target_failures(self, w, targets, now):
        history = getattr(self, "_failed_targets", {}).get(w, [])
        return filter_failed_targets(targets, history, now)

    def _anti_sucuk_log_throttled(self, w, reason, message, now=None, interval=3.0):
        now = now or time.time()
        key = (w, reason)
        last = float(self._anti_sucuk_diag_t.get(key, 0) or 0)
        if now - last >= interval:
            self._anti_sucuk_diag_t[key] = now
            log_event(self.st, "debug", message)

    def _anti_sucuk_state_allowed(self, state, hp_var):
        if state in ("DOGRULAMA", "CAPTCHA", "CAPTCHA BEKLE", "MESAJ", "MESAJ BEKLE"):
            return False
        if hp_var:
            return state == "SAVASIYOR"
        return state in ("ARANIYOR", "SAVASIYOR")

    def _hp_bitis_gecikmesi(self, cc):
        return FIXED_HP_BEKLEME_SN

    def _clear_target_click_cooldown(self, w, cc, now=None):
        now = time.time() if now is None else now
        self._son_tiklama_t[w] = now - self._hp_bitis_gecikmesi(cc)

    def _begin_approach(self, w, now=None):
        now = time.time() if now is None else now
        self._approach[w] = {
            "started": now,
            "max_fill": None,
            "drop_since": 0.0,
            "still_since": 0.0,
            "recoveries": 0,
            "check_after": now,
            "warned_no_fill": False,
        }

    def _start_target_generation(self, w, client_idx=None, now=None):
        """Yeni tiklanan hedef icin HP zaman serisini atomik olarak ayir."""
        now = time.time() if now is None else float(now)
        with self.st.lk:
            generation = int(self.st.target_generation.get(w, 0) or 0) + 1
            self.st.target_generation[w] = generation
            self.st.target_hp_evidence.pop(w, None)
        self._target_generation[w] = generation
        self._last_target_sample.pop(w, None)
        label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
        log_event(
            self.st,
            "debug",
            f"[HP-{label}] yeni hedef G{generation}; eski HP ornekleri gecersiz ({w})",
        )
        return generation

    def _target_sample_is_new(self, w, generation, sample_ts):
        """Ayni Vision karesinin 50 Hz aksiyon dongusunde tekrar islenmesini engelle."""
        if not hasattr(self, "_target_generation"):
            self._target_generation = {}
        if not hasattr(self, "_last_target_sample"):
            self._last_target_sample = {}
        try:
            sample_generation = int(generation or 0)
            sample_time = float(sample_ts or 0.0)
        except (TypeError, ValueError):
            return False
        if sample_time <= 0:
            # Dogrudan cagiran eski test/entegrasyonlar icin uyumluluk. Canli
            # dongu her zaman Vision kare zamanini gonderir.
            sample_time = time.time()
        expected = int(self._target_generation.get(w, sample_generation) or 0)
        self._target_generation.setdefault(w, expected)
        if sample_generation != expected:
            return False
        token = (sample_generation, sample_time)
        if self._last_target_sample.get(w) == token:
            return False
        self._last_target_sample[w] = token
        return True

    def _clear_approach(self, w):
        self._approach.pop(w, None)

    def _begin_combat_progress(self, w, hp_fill=None, now=None, damage_confirmed=False):
        now = time.time() if now is None else now
        if not hasattr(self, "_last_damage_t"):
            self._last_damage_t = {}
        if damage_confirmed:
            self._last_damage_t[w] = now
        initial = None if hp_fill is None else float(hp_fill)
        self._combat_progress[w] = {
            "hp_floor": initial,
            "start_fill": initial,
            "last_fill": initial,
            "last_progress": now,
            "started": now,
            "samples": 1 if initial is not None else 0,
            "progress_events": 0,
            "damage_confirmed": bool(damage_confirmed),
            "recoveries": 0,
            "check_after": now,
            "missing_samples": 0,
            "missing_started": 0.0,
        }

    def _clear_combat_progress(self, w):
        self._combat_progress.pop(w, None)
        if hasattr(self, "_combat_diag_t"):
            self._combat_diag_t.pop(w, None)

    def _combat_log_throttled(self, w, client_idx, progress, hp_fill, now, force=False):
        if not getattr(self, "st", None):
            return
        if not hasattr(self, "_combat_diag_t"):
            self._combat_diag_t = {}
        if not hasattr(self, "_target_generation"):
            self._target_generation = {}
        last = float(self._combat_diag_t.get(w, 0) or 0)
        if not force and now - last < COMBAT_DIAGNOSTIC_INTERVAL_SN:
            return
        self._combat_diag_t[w] = now
        floor = progress.get("hp_floor")
        fill_text = "--" if hp_fill is None else f"{float(hp_fill) * 100:.1f}"
        floor_text = "--" if floor is None else f"{float(floor) * 100:.1f}"
        progress_age = now - float(progress.get("last_progress", now) or now)
        generation = int(self._target_generation.get(w, 0) or 0)
        label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
        log_event(
            self.st,
            "debug",
            f"[SAVAS-{label}] G{generation} can=%{fill_text} taban=%{floor_text} "
            f"ilerlemesiz={progress_age:.1f}sn ornek={int(progress.get('samples', 0) or 0)} "
            f"olay={int(progress.get('progress_events', 0) or 0)} "
            f"hasar={'evet' if progress.get('damage_confirmed') else 'hayir'} "
            f"kurtarma={int(progress.get('recoveries', 0) or 0)}/{COMBAT_RECOVERY_MAX} ({w})",
        )

    def _approach_log_throttled(self, w, reason, message, now=None, interval=2.0):
        now = time.time() if now is None else now
        key = (w, reason)
        last = float(self._approach_diag_t.get(key, 0) or 0)
        if now - last >= interval:
            self._approach_diag_t[key] = now
            log_event(self.st, "debug", message)

    def _recovery_input_blocked(self, w):
        if self._input_blocked(w):
            return True
        with self.st.lk:
            return bool(self.st.global_pause_active)

    def _hold_recovery_key(self, w, key, seconds, hwnd=None):
        with input_transaction_lock:
            pressed = False
            try:
                if self._recovery_input_blocked(w):
                    return False
                if hwnd and not pencere_odakla(hwnd):
                    log_event(self.st, "warn", f"Tus atlandi: hedef pencere odaklanamadi ({w})")
                    return False
                keyboard.press(key)
                pressed = True
                deadline = time.time() + max(0.0, float(seconds))
                while time.time() < deadline:
                    if self._stop_event.wait(min(0.05, max(0.0, deadline - time.time()))):
                        return False
                    if self._recovery_input_blocked(w):
                        return False
                return True
            finally:
                if pressed:
                    try:
                        keyboard.release(key)
                    except Exception:
                        pass

    def _wait_buff_delay(self, w, seconds):
        deadline = time.time() + max(0.0, float(seconds))
        while time.time() < deadline:
            if self._stop_event.wait(min(0.05, max(0.0, deadline - time.time()))):
                return False
            if self._recovery_input_blocked(w):
                return False
        return True

    def _tap_buff_hotkey(self, w, keys, hwnd=None):
        with input_transaction_lock:
            pressed = []
            try:
                if self._recovery_input_blocked(w):
                    return False
                if hwnd and not pencere_odakla(hwnd):
                    log_event(self.st, "warn", f"BUFF atlandi: hedef pencere odaklanamadi ({w})")
                    return False
                for key in keys:
                    keyboard.press(key)
                    pressed.append(key)
                return self._wait_buff_delay(w, BUFF_KEY_HOLD_SECONDS)
            finally:
                for key in reversed(pressed):
                    try:
                        keyboard.release(key)
                    except Exception:
                        pass

    def _buff_log_throttled(self, w, reason, message, interval=5.0):
        now = time.time()
        key = (w, reason)
        if now - float(self._buff_diag_t.get(key, 0) or 0) >= interval:
            self._buff_diag_t[key] = now
            log_event(self.st, "debug", message)

    def _run_held_alt_buff_sequence(self, w, hwnd):
        # ALT basili kalirken baska client'a gecilirse tuslar karisabilir;
        # bu diziyi tek bir input islemi olarak tamamla.
        with input_transaction_lock:
            alt_pressed = False
            try:
                if self._recovery_input_blocked(w):
                    return False
                if hwnd and not pencere_odakla(hwnd):
                    log_event(self.st, "warn", f"BUFF atlandi: hedef pencere odaklanamadi ({w})")
                    return False
                keyboard.press("alt")
                alt_pressed = True
                log_event(
                    self.st,
                    "debug",
                    f"[BUFF] ALT basili; ilk tus oncesi {BUFF_ALT_ARM_DELAY_SECONDS:.0f}sn bekleniyor ({w})",
                )
                if not self._wait_buff_delay(w, BUFF_ALT_ARM_DELAY_SECONDS):
                    return False
                log_event(self.st, "debug", f"[BUFF] ALT basili; 1 2 3 4 F1 F2 F3 gonderiliyor ({w})")

                for key, delay_after, label in BUFF_ALT_SEQUENCE:
                    if not self._tap_buff_hotkey(w, (key,), hwnd):
                        log_event(self.st, "warn", f"[BUFF] {label} sirasinda ertelendi ({w})")
                        return False
                    if delay_after and not self._wait_buff_delay(w, delay_after):
                        log_event(self.st, "warn", f"[BUFF] {label} sonrasinda ertelendi ({w})")
                        return False
                return True
            finally:
                if alt_pressed:
                    try:
                        keyboard.release("alt")
                    except Exception:
                        pass

    def _run_buff_cycle(self, w, hwnd):
        if not hwnd or self._recovery_input_blocked(w):
            return False
        if self._loot_running.get(w, False):
            self._buff_log_throttled(w, "loot", f"[BUFF] loot bitene kadar ertelendi ({w})")
            return False
        if self._buff_running.get(w, False):
            return False

        self._buff_running[w] = True
        completed = False
        try:
            if not pencere_odakla(hwnd):
                log_event(self.st, "warn", f"[BUFF] hedef pencere odaklanamadi ({w})")
                return False
            if self._recovery_input_blocked(w):
                return False

            if self._buff_needs_remount.get(w, False):
                log_event(self.st, "warn", f"[BUFF] yarim kalan dongu: once ata biniliyor ({w})")
                if not self._tap_buff_hotkey(w, ("ctrl", "g"), hwnd):
                    return False
                self._buff_needs_remount[w] = False
                log_event(self.st, "info", f"[BUFF] yarim kalan dongu icin CTRL+G binis gonderildi ({w})")
                if not self._wait_buff_delay(w, 0.20):
                    return False

            with self.st.lk:
                self.st.durum[w] = "GUCLENDIRME"
            log_event(self.st, "info", f"[BUFF] guclendirme dongusu basladi ({w})")

            # Ilk CTRL+G karakteri attan indirir. Dongu yarida kesilirse
            # sonraki guvenli denemede once ata binmek gerekir.
            self._buff_needs_remount[w] = True
            if not self._tap_buff_hotkey(w, ("ctrl", "g"), hwnd):
                log_event(self.st, "warn", f"[BUFF] ilk CTRL+G sirasinda ertelendi ({w})")
                return False
            log_event(self.st, "info", f"[BUFF] ilk CTRL+G inis gonderildi ({w})")
            if not self._wait_buff_delay(w, BUFF_DISMOUNT_DELAY_SECONDS):
                return False

            if not self._run_held_alt_buff_sequence(w, hwnd):
                return False

            for key, delay_after, label in BUFF_AFTER_ALT_SEQUENCE:
                if not self._tap_buff_hotkey(w, (key,), hwnd):
                    log_event(self.st, "warn", f"[BUFF] {label} sirasinda ertelendi ({w})")
                    return False
                if delay_after and not self._wait_buff_delay(w, delay_after):
                    return False

            if not self._tap_buff_hotkey(w, ("ctrl", "g"), hwnd):
                log_event(self.st, "warn", f"[BUFF] son CTRL+G sirasinda ertelendi ({w})")
                return False
            self._buff_needs_remount[w] = False
            log_event(self.st, "info", f"[BUFF] son CTRL+G binis gonderildi ({w})")

            completed = True
            log_event(
                self.st,
                "info",
                f"[BUFF] tamamlandi; sonraki dongu {BUFF_INTERVAL_SECONDS / 60:.0f} dakika sonra ({w})",
            )
            return True
        except Exception as exc:
            log_event(self.st, "error", f"[BUFF] tus dizisi hatasi: {exc} ({w})")
            return False
        finally:
            self._buff_running[w] = False
            if not completed:
                pending = "; CTRL+G binis bekliyor" if self._buff_needs_remount.get(w, False) else ""
                self._buff_log_throttled(w, "deferred", f"[BUFF] guvenli ana ertelendi{pending} ({w})")

    def _run_approach_recovery(self, w, hwnd, attempt):
        if not 1 <= attempt <= APPROACH_RECOVERY_MAX:
            return False
        if self._recovery_input_blocked(w):
            return False
        if not pencere_odakla(hwnd):
            log_event(self.st, "warn", f"Yaklasma kurtarmasi: hedef pencere odaklanamadi ({w})")
            return False
        if self._recovery_input_blocked(w):
            return False
        log_event(
            self.st,
            "warn",
            f"Yaklasma kurtarmasi {attempt}/{APPROACH_RECOVERY_MAX}: {self._recovery_description(attempt)} ({w})",
        )
        if not self._run_obstacle_recovery(w, hwnd, attempt):
            log_event(self.st, "warn", f"Yaklasma kurtarmasi iptal edildi ({w})")
            return False
        log_event(self.st, "info", f"Yaklasma kurtarmasi tamamlandi; hareket/hasar yeniden kontrol ediliyor ({w})")
        return True

    def _run_combat_recovery(self, w, hwnd):
        if self._recovery_input_blocked(w):
            return False
        if not pencere_odakla(hwnd):
            log_event(self.st, "warn", f"Savas kurtarmasi: hedef pencere odaklanamadi ({w})")
            return False
        if self._recovery_input_blocked(w):
            return False
        progress = self._combat_progress.get(w) or {}
        last_fill = progress.get("last_fill")
        hp_floor = progress.get("hp_floor")
        fill_text = "--" if last_fill is None else f"{float(last_fill) * 100:.1f}"
        floor_text = "--" if hp_floor is None else f"{float(hp_floor) * 100:.1f}"
        no_progress = time.time() - float(progress.get("last_progress", time.time()) or time.time())
        attempt = int(progress.get("recoveries", 0) or 0) + 1
        if not 1 <= attempt <= COMBAT_RECOVERY_MAX:
            return False
        log_event(
            self.st,
            "warn",
            f"Savas ilerlemiyor: can=%{fill_text}, taban=%{floor_text}, "
            f"{no_progress:.1f}sn yeni dusus yok; kurtarma {attempt}/{COMBAT_RECOVERY_MAX}: "
            f"{self._recovery_description(attempt)} ({w})",
        )
        if not self._run_obstacle_recovery(w, hwnd, attempt):
            log_event(self.st, "warn", f"Savas kurtarmasi iptal edildi ({w})")
            return False
        log_event(self.st, "info", f"Savas kurtarmasi tamamlandi; can ilerlemesi yeniden kontrol ediliyor ({w})")
        return True

    @staticmethod
    def _recovery_description(attempt):
        return {1: "at yetenegi 1; 4sn hasar kontrolu",
                2: "S 1sn + D 2sn; taze hedefi yeniden tikla",
                3: "S 1sn + A 4sn; taze hedefi yeniden tikla"}[attempt]

    def _run_obstacle_recovery(self, w, hwnd, attempt):
        if attempt == 1:
            return self._hold_recovery_key(w, RECOVERY_SKILL_KEY, RECOVERY_SKILL_TAP_SN, hwnd)
        if attempt not in (2, 3):
            return False
        if not self._hold_recovery_key(w, "s", 1.0, hwnd):
            return False
        key, seconds = ("d", 2.0) if attempt == 2 else ("a", 4.0)
        if not self._hold_recovery_key(w, key, seconds, hwnd):
            return False
        finished = time.time()
        # Never reuse pre-movement screen coordinates. The action loop waits
        # for a post-movement capture, without blocking the other clients.
        self._recovery_reclick[w] = {
            "after": finished, "attempt": attempt, "hwnd": hwnd,
            "phase": self.dur.get(w),
            "generation": self._target_generation.get(w, 0),
            "started": self._approach.get(w, {}).get("started", finished),
            "pos": getattr(self, "_kilitli_hedef", {}).get(w),
        }
        return True

    def _handle_recovery_reclick(self, w, hwnd, cc, targets, data_ts, ox, oy, client_idx=None):
        pending = self._recovery_reclick.get(w)
        if not pending:
            return False
        if (pending["hwnd"] != hwnd or pending["phase"] != self.dur.get(w)
                or pending["generation"] != self._target_generation.get(w, 0)):
            self._recovery_reclick.pop(w, None)
            return False
        now = time.time()
        if self._recovery_input_blocked(w):
            return True
        if now - pending["after"] >= RECOVERY_RECLICK_TIMEOUT_SN:
            abandon = self._abandon_combat_target if pending["phase"] == "SAVASIYOR" else self._abandon_approach_target
            abandon(w, cc, now, "manevra sonrasi metin taze goruntude yeniden bulunamadi")
            return True
        if data_ts <= pending["after"] or not self._default_frame_fresh(w, data_ts, now):
            return True
        previous = pending.get("pos")
        if not previous:
            return True
        # Screen-space association is conservative, not persistent world ID.
        # Require current two-frame-confirmed detections, not target memory.
        candidates = []
        for target in targets or []:
            if not isinstance(target, dict) or not target.get("stable_click"):
                continue
            center = self._target_center_xy(target)
            distance = ((center[0] - previous[0]) ** 2 + (center[1] - previous[1]) ** 2) ** 0.5
            if distance <= RECOVERY_RECLICK_RADIUS and self._filter_target_failures(w, [center], now):
                candidates.append((distance, center))
        if not candidates:
            return True
        candidates.sort(key=lambda item: item[0])
        # Two equally plausible stones: do not guess which was the old target.
        if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < 40.0:
            return True
        center = candidates[0][1]
        x, y = int(round(center[0] + ox)), int(round(center[1] + oy))
        with input_transaction_lock:
            if self._recovery_input_blocked(w):
                return True
            click_mode = _tiklama_yap(self.cfg, x, y, hwnd)
        self._log_click_result(w, click_mode, x=x, y=y, client_idx=client_idx)
        if click_mode in ("blocked", "focus_failed"):
            return True
        clicked_at = time.time()
        self._kilitli_hedef[w] = center
        self._start_target_generation(w, client_idx, clicked_at)
        self._clear_combat_progress(w)
        self._begin_approach(w, clicked_at)
        self._approach[w].update(
            started=pending["started"], recoveries=pending["attempt"],
            check_after=clicked_at + RECOVERY_SKILL_WAIT_SN,
        )
        self._hp_onceki_durum.pop(w, None)
        self._hp_kayip_t.pop(w, None)
        self._hp_ignore_until.pop(w, None)
        self._son_tiklama_t[w] = clicked_at
        self.dur[w] = "DOGRULAMA"
        self.dogr_t[w] = clicked_at
        self.dogr_n[w] = 0
        self._recovery_reclick.pop(w, None)
        log_event(self.st, "info", f"Manevra sonrasi metin yeniden tiklandi; 4sn hasar kontrolu, deneme sayaci korundu ({w})")
        return True

    def _abandon_approach_target(self, w, cc, now, reason):
        getattr(self, "_recovery_reclick", {}).pop(w, None)
        self._remember_target_failure(w, now)
        locked = getattr(self, "_kilitli_hedef", {}).get(w)
        if locked:
            self._approach_blocked_target[w] = {
                "pos": (float(locked[0]), float(locked[1])),
                # Metin-yok sayaci ve dort Q taramasi tamamlanana kadar ayni
                # hedefi yeniden secme.
                "until": now + APPROACH_BLOCKED_TARGET_SN,
            }
        self._clear_approach(w)
        self._clear_combat_progress(w)
        self._hp_ignore_until[w] = float("inf")
        self._hp_onceki_durum.pop(w, None)
        self._hp_kayip_t.pop(w, None)
        self._son_tiklama_t[w] = now
        self.dur[w] = "ARANIYOR"
        log_event(
            self.st,
            "warn",
            f"Yaklasma birakildi: {reason}; hedef {APPROACH_BLOCKED_TARGET_SN:.0f}sn beklemeye alindi ({w})",
        )

    def _abandon_combat_target(self, w, cc, now, reason):
        getattr(self, "_recovery_reclick", {}).pop(w, None)
        self._remember_target_failure(w, now)
        locked = getattr(self, "_kilitli_hedef", {}).get(w)
        if locked:
            self._approach_blocked_target[w] = {
                "pos": (float(locked[0]), float(locked[1])),
                "until": now + APPROACH_BLOCKED_TARGET_SN,
            }
        self._clear_combat_progress(w)
        self._hp_ignore_until[w] = float("inf")
        self._hp_onceki_durum.pop(w, None)
        self._hp_kayip_t.pop(w, None)
        self._son_tiklama_t[w] = now
        self._araniyor_baslat_t.pop(w, None)
        self.dur[w] = "ARANIYOR"
        log_event(
            self.st,
            "warn",
            f"Savas hedefi birakildi: {reason}; hedef {APPROACH_BLOCKED_TARGET_SN:.0f}sn beklemeye alindi ({w})",
        )

    def _target_center_xy(self, target):
        if isinstance(target, dict):
            return float(target.get("cx", target.get("x", 0))), float(target.get("cy", target.get("y", 0)))
        return float(target[0]), float(target[1])

    def _default_frame_fresh(self, w, data_ts, now=None):
        now = now or time.time()
        if not data_ts:
            return False
        age = now - float(data_ts)
        fresh = age <= DEFAULT_TARGET_FRAME_MAX_AGE
        if not fresh:
            last = self._default_fresh_log_t.get(w, 0)
            if now - last > 2.0:
                self._default_fresh_log_t[w] = now
                log_event(self.st, "warn", f"[HEDEF] goruntu gecikti, tiklama atlandi: {age:.2f}s ({w})")
        return fresh

    def _log_click_result(self, w, click_mode, x=None, y=None, client_idx=None):
        if click_mode == "sendinput_fallback":
            log_event(self.st, "warn", f"Tiklama fallback: Interception uygulanmadi, SendInput denendi ({w})")
        elif click_mode == "blocked":
            log_event(self.st, "warn", f"Tiklama atlandi: input kilitli ({w})")
        elif click_mode == "focus_failed":
            log_event(self.st, "warn", f"Tiklama atlandi: hedef pencere odaklanamadi ({w})")
        if click_mode not in ("blocked", "focus_failed"):
            label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
            coordinate = "--" if x is None or y is None else f"({int(x)},{int(y)})"
            log_event(
                self.st,
                "debug",
                f"[CLICK-{label}] hedef={coordinate} yontem={click_mode or 'bilinmiyor'} ({w})",
            )

    def _loot_tap(self):
        """Z basisini gonder ve Windows/driver teslim sonucunu raporla."""
        if _ikdev is not None and INTERCEPTION_OK and not _force_sendinput:
            down_ok = _ik_send(_SC['z'], _IKDOWN)
            time.sleep(LOOT_KEY_HOLD_SECONDS)
            up_ok = _ik_send(_SC['z'], _IKUP)
            return {
                "ok": bool(down_ok and up_ok),
                "delivered": bool(down_ok and up_ok),
                "method": "interception",
            }

        if _send_keyboard_scancode_tap(_SC['z'], delay=LOOT_KEY_HOLD_SECONDS):
            return {"ok": True, "delivered": True, "method": "sendinput_scancode"}

        # Son geri donus: kutuphane olayi. API basari sayisi vermedigi icin
        # bunu yalniz "denendi" olarak raporlariz, teslim edildi saymayiz.
        try:
            keyboard.press('z')
            time.sleep(LOOT_KEY_HOLD_SECONDS)
            keyboard.release('z')
            return {"ok": True, "delivered": False, "method": "keyboard_fallback"}
        except Exception as exc:
            try:
                keyboard.release('z')
            except Exception:
                pass
            return {
                "ok": False,
                "delivered": False,
                "method": "failed",
                "error": str(exc),
            }

    def _loot_burst(
        self, w, hwnd, cc, reason="loot", taps=None, delay=None,
        interval=None, set_status=True,
    ):
        if not cc.get("oto_loot", True) or self._input_blocked(w):
            return False
        now = time.time()
        min_gap = 0.25
        if now - self._loot_last_t.get(w, 0) < min_gap:
            return False

        try:
            tap_count = int(taps if taps is not None else cc.get("loot_taps", LOOT_BURST_TAPS))
        except Exception:
            tap_count = LOOT_BURST_TAPS
        tap_count = max(1, min(tap_count, 12))

        try:
            tap_interval = float(
                interval if interval is not None
                else (cc.get("loot_interval", LOOT_TAP_INTERVAL) or LOOT_TAP_INTERVAL)
            )
        except Exception:
            tap_interval = LOOT_TAP_INTERVAL
        tap_interval = max(0.03, min(tap_interval, 0.25))

        try:
            start_delay = float(delay if delay is not None else cc.get("loot_delay", LOOT_POST_KILL_DELAY))
        except Exception:
            start_delay = LOOT_POST_KILL_DELAY
        start_delay = max(0.0, min(start_delay, 0.6))

        # Beklerken global input kilidini tutma. Ozellikle iki client'ta diger
        # pencerenin goruntu/aksiyon zincirini gereksiz yere donduruyordu.
        if start_delay and self._stop_event.wait(start_delay):
            return False

        started = time.time()
        sent_count = 0
        delivered_count = 0
        refocus_count = 0
        methods = {}
        aborted = ""

        with input_transaction_lock:
            if self._input_blocked(w):
                return False
            if hwnd and not pencere_odakla(hwnd):
                log_event(self.st, "warn", f"[LOOT] hedef pencere odaklanamadi ({w})")
                return False

            if set_status:
                with self.st.lk:
                    self.st.durum[w] = "LOOT"
            for tap_index in range(1, tap_count + 1):
                if self._input_blocked(w):
                    aborted = "input_bloklu"
                    break
                if hwnd and win32gui.GetForegroundWindow() != hwnd:
                    refocus_count += 1
                    if not pencere_odakla(hwnd):
                        aborted = f"odak_kaybi_tap_{tap_index}"
                        break
                result = self._loot_tap()
                method = str(result.get("method", "unknown"))
                methods[method] = methods.get(method, 0) + 1
                if result.get("ok"):
                    sent_count += 1
                if result.get("delivered"):
                    delivered_count += 1
                if not result.get("ok"):
                    aborted = f"gonderim_hatasi_tap_{tap_index}:{result.get('error', '')}"
                    break
                if tap_index < tap_count and self._stop_event.wait(tap_interval):
                    aborted = "bot_durduruldu"
                    break

        self._loot_last_t[w] = time.time()
        elapsed = time.time() - started
        foreground_ok = bool(not hwnd or win32gui.GetForegroundWindow() == hwnd)
        method_text = "+".join(f"{name}:{count}" for name, count in sorted(methods.items())) or "yok"
        level = "info" if sent_count == tap_count and not aborted else "warn"
        log_event(
            self.st,
            level,
            f"[LOOT] {reason}: Z deneme={sent_count}/{tap_count} "
            f"OS_teslim={delivered_count}/{tap_count} yontem={method_text} "
            f"odak_son={'evet' if foreground_ok else 'hayir'} yeniden_odak={refocus_count} "
            f"sure={elapsed:.2f}sn iptal={aborted or 'yok'} ({w})",
        )
        self._loot_log_t[w] = time.time()
        return bool(sent_count == tap_count and not aborted)

    def _loot_burst_async(
        self, w, hwnd, cc, reason="loot", taps=None, delay=None, interval=None,
    ):
        if not cc.get("oto_loot", True) or self._input_blocked(w):
            return False
        if self._loot_running.get(w, False):
            return False

        self._loot_running[w] = True
        cc_copy = dict(cc or {})

        def _run():
            try:
                self._loot_burst(
                    w, hwnd, cc_copy, reason,
                    taps=taps, delay=delay, interval=interval, set_status=False,
                )
            finally:
                self._loot_running[w] = False

        threading.Thread(target=_run, daemon=True).start()
        return True

    def _handle_araniyor(self, w, gecerli, hp_var, ecx, ecy, hwnd, cc, ox, oy, hedefler=None, data_ts=0, client_idx=None):
        import numpy as np
        now = time.time()

        hp_authoritative = is_hp_panel_authoritative(
            hp_var,
            now,
            self._hp_ignore_until.get(w, 0),
        )
        if hp_authoritative:
            # Acik panel yalnizca bir hedefin secili oldugunu kanitlar. Kirmizi
            # dolgu yeni karelerde gercekten azalmadan SAVASIYOR durumuna gecme.
            self.dur[w] = "DOGRULAMA"
            self.dogr_t[w] = now
            self.dogr_n[w] = 0
            self._clear_combat_progress(w)
            self._clear_approach(w)
            self._begin_approach(w, now)
            self._hp_onceki_durum.pop(w, None)
            self._hp_kayip_t.pop(w, None)
            self._araniyor_baslat_t.pop(w, None)
            label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
            log_event(
                self.st,
                "debug",
                f"[HP-{label}] ust hedef paneli goruldu; kirmizi can azalmasi bekleniyor ({w})",
            )
            return

        gecerli = self._filter_target_failures(w, gecerli, now)
        blocked = self._approach_blocked_target.get(w)
        if blocked:
            if now >= float(blocked.get("until", 0) or 0):
                self._approach_blocked_target.pop(w, None)
            else:
                bx, by = blocked.get("pos", (0.0, 0.0))
                alternatives = filter_targets_away_from(gecerli, (bx, by), 60.0)
                if alternatives:
                    gecerli = alternatives
                elif gecerli:
                    # Algilayici ayni hedefi gormeye devam etse bile o hedef
                    # su anda kullanilabilir degil. Bunu "Metin yok" gibi
                    # isleyerek Hareketli Metin Arama sayacini calistir.
                    gecerli = []

        if not gecerli:
            anti_sucuk = bool(self.cfg.g("anti_sucuk"))
            if anti_sucuk and self._anti_sucuk_state_allowed("ARANIYOR", hp_authoritative):
                baslangic = float(self._araniyor_baslat_t.get(w, 0) or 0)
                if not baslangic:
                    self._araniyor_baslat_t[w] = now
                elif now - baslangic >= FIXED_ANTI_HAREKETSIZ_SN:
                    if self._anti_sucuk_araniyor_manevra(w, hwnd, now):
                        self._araniyor_baslat_t[w] = time.time()
            else:
                self._araniyor_baslat_t.pop(w, None)
            return

        if now - self._son_tiklama_t.get(w, 0) < self._hp_bitis_gecikmesi(cc):
            return

        self._araniyor_baslat_t.pop(w, None)
        # Gecerli merkezleri ayrintili YOLO hedefleriyle eslestir. Boylece
        # yalnizca ekran uzakligi degil; gorunen boyut, guven ve iki kare
        # arasindaki kararlilik da hedef secimine katilir.
        detailed_candidates = []
        for target in hedefler or []:
            tcx, tcy = self._target_center_xy(target)
            if any(np.hypot(tcx - gx, tcy - gy) <= 3.0 for gx, gy in gecerli):
                detailed_candidates.append(target)

        ranked_targets = rank_target_candidates(detailed_candidates, (ecx, ecy))
        if ranked_targets:
            selected = ranked_targets[0]
            h = self._target_center_xy(selected["target"])
            log_event(
                self.st,
                "debug",
                "[HEDEF] karma secim: "
                f"aday={len(ranked_targets)} puan={selected['score']:.3f} "
                f"merkez={selected['distance_score']:.2f} "
                f"boyut={selected['size_score']:.2f} "
                f"guven={selected['confidence_score']:.2f} "
                f"kararlilik={selected['stability_score']:.2f} ({w})",
            )
        else:
            # Kisa YOLO kacirmalarinda bellekte kalan merkezlerde kutu/guven
            # bilgisi yoktur; bu durumda eski yakinlik davranisi guvenli geri donustur.
            h = gecerli[np.argmin([np.hypot(m[0]-ecx, m[1]-ecy) for m in gecerli])]
        self._kilitli_hedef = getattr(self, '_kilitli_hedef', {})
        self._kilitli_hedef[w] = (float(h[0]), float(h[1]))

        click_x = int(round(h[0] + ox))
        click_y = int(round(h[1] + oy))
        with input_transaction_lock:
            if self._input_blocked(w):
                return
            click_mode = _tiklama_yap(self.cfg, click_x, click_y, hwnd)
        self._log_click_result(
            w,
            click_mode,
            x=click_x,
            y=click_y,
            client_idx=client_idx,
        )
        if click_mode in ("blocked", "focus_failed"):
            return
        click_at = time.time()
        self._start_target_generation(w, client_idx=client_idx, now=click_at)
        if cc.get("oto_loot", True):
            self._loot_burst(w, hwnd, cc, "hedef sonrasi", taps=1, delay=0.0, set_status=False)
        self._son_tiklama_t[w] = click_at
        self._hp_ignore_until.pop(w, None)
        self._clear_combat_progress(w)
        self.dur[w] = "DOGRULAMA"
        self.dogr_t[w] = time.time()
        self.dogr_n[w] = 0
        self._begin_approach(w, self.dogr_t[w])
        self._son_tiklama_zamani[w] = time.time()
    def _handle_dogrulama(
        self, w, hp_var, hp_fill, hp_fill_ready, scene_moving,
        scene_motion_ready, cc, hwnd, target_generation=0, sample_ts=0,
        client_idx=None, hp_sample_valid=True,
    ):
        now = time.time()
        if not self._target_sample_is_new(w, target_generation, sample_ts):
            expected = int(self._target_generation.get(w, 0) or 0)
            if int(target_generation or 0) != expected:
                label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
                self._approach_log_throttled(
                    w,
                    "old_generation",
                    f"[HP-{label}] eski kare atlandi: kare=G{int(target_generation or 0)} "
                    f"hedef=G{expected} ({w})",
                    now,
                    2.0,
                )
            return
        approach = self._approach.get(w)
        if approach is None:
            self._begin_approach(w, self.dogr_t.get(w, now) or now)
            approach = self._approach[w]

        elapsed = now - float(approach.get("started", now) or now)

        # Can panelinin acilmasi yalnizca hedefin secildigini gosterir. Gercek
        # savas icin secilen kirmizi dolgunun kalici olarak azalmasini bekle.
        if hp_var and hp_fill_ready and hp_sample_valid and hp_fill is not None:
            fill = float(hp_fill)
            max_fill = approach.get("max_fill")
            if max_fill is None:
                approach["max_fill"] = fill
                self._approach_log_throttled(w, "hp_baseline", f"Yaklasma: can referansi alindi %{fill * 100:.1f} ({w})", now, 10.0)
            else:
                max_fill = max(float(max_fill), fill)
                approach["max_fill"] = max_fill
                drop = max_fill - fill
                if drop >= APPROACH_HP_DROP_MIN:
                    if not approach.get("drop_since"):
                        approach["drop_since"] = now
                    elif now - float(approach["drop_since"]) >= APPROACH_HP_DROP_CONFIRM_SN:
                        self.dur[w] = "SAVASIYOR"
                        self.dogr_n[w] = 0
                        self._hp_onceki_durum[w] = True
                        self._begin_combat_progress(w, fill, now, damage_confirmed=True)
                        self._clear_approach(w)
                        label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
                        log_event(
                            self.st,
                            "info",
                            f"Hasar basladi: {label} G{int(target_generation or 0)} "
                            f"referans=%{max_fill * 100:.1f} simdi=%{fill * 100:.1f} "
                            f"azalma=%{drop * 100:.1f}; SAVASIYOR ({w})",
                        )
                        return
                else:
                    approach["drop_since"] = 0.0

        if scene_motion_ready:
            if scene_moving:
                approach["still_since"] = 0.0
                self._approach_log_throttled(w, "moving", f"Yaklasma: sahne hareketli, hedefe gidiliyor ({w})", now, 3.0)
            elif not approach.get("still_since"):
                approach["still_since"] = now

        # Eski kurulumlar can dolgu alanini secmeden de acilabilsin. Bu geri
        # donus yolu eski davranisi korur; guvenilir savas onayi icin yeni alan gerekir.
        if not hp_fill_ready:
            if not approach.get("warned_no_fill"):
                approach["warned_no_fill"] = True
                log_event(self.st, "warn", f"Can cubugu secilmedi; eski HP panel dogrulamasi kullaniliyor ({w})")
            if elapsed >= FIXED_DOGRULAMA_SN:
                if hp_var:
                    self.dur[w] = "SAVASIYOR"
                    self.dogr_n[w] = 0
                    self._clear_approach(w)
                else:
                    self._abandon_approach_target(w, cc, now, "HP paneli acilmadi")
            return

        # Panel hic acilmadiysa tiklama hedefe ulasmamis olabilir.
        if not hp_var:
            # Invalid/hidden HP must not skip the 8-second approach recovery.
            missing_since = approach.setdefault("panel_missing_since", now)
            retries = int(approach.get("recoveries", 0))
            wait_for = APPROACH_INITIAL_STILL_SN if not retries else RECOVERY_SKILL_WAIT_SN
            if now - missing_since < wait_for or now < approach.get("check_after", 0):
                return
            if retries >= APPROACH_RECOVERY_MAX or elapsed >= APPROACH_MAX_SN:
                self._abandon_approach_target(w, cc, now, "HP paneli tekrar kontrol ve 3 kurtarmada dogrulanamadi")
                return
            if self._run_approach_recovery(w, hwnd, retries + 1):
                resumed = time.time()
                approach["recoveries"] = retries + 1
                approach["panel_missing_since"] = resumed
                approach["check_after"] = resumed + RECOVERY_SKILL_WAIT_SN
            return
        approach.pop("panel_missing_since", None)

        if elapsed >= APPROACH_MAX_SN:
            self._abandon_approach_target(w, cc, now, f"{APPROACH_MAX_SN:.0f}sn icinde hasar baslamadi")
            return

        still_since = float(approach.get("still_since", 0) or 0)
        recoveries = int(approach.get("recoveries", 0) or 0)
        check_after = float(approach.get("check_after", 0) or 0)
        if recoveries:
            # Manevradan sonra sahnenin hareketi basari sayilmaz. Yukaridaki
            # HP dususu savasi dogrulamadiysa yeni ve gecerli olcumle ilerle.
            # Ilk dususun ikinci kareyle dogrulanmasina da zaman tani.
            stuck = (
                hp_var and hp_sample_valid and hp_fill is not None
                and now >= check_after and not approach.get("drop_since")
            )
        else:
            stuck = (
                hp_var
                and scene_motion_ready
                and not scene_moving
                and still_since > 0
                and now >= check_after
                and now - still_since >= APPROACH_INITIAL_STILL_SN
            )
        if not stuck:
            return

        if recoveries >= APPROACH_RECOVERY_MAX:
            self._abandon_approach_target(w, cc, now, "at yetenegi ve geri/sag/sol kurtarmasi sonrasinda hasar yok")
            return

        attempt = recoveries + 1
        if self._run_approach_recovery(w, hwnd, attempt):
            resumed = time.time()
            approach["recoveries"] = attempt
            approach["still_since"] = 0.0
            approach["check_after"] = resumed + APPROACH_POST_RECOVERY_WAIT_SN
            approach["drop_since"] = 0.0

    def _consume_target_hp_evidence(self, w, generation, sample_ts, now):
        progress = self._combat_progress.get(w)
        if not progress or not progress.get("damage_confirmed"):
            return
        with self.st.lk:
            evidence = dict(self.st.target_hp_evidence.get(w, {}))
        ts = float(evidence.get("ts", 0))
        if (evidence.get("generation") != generation or ts > sample_ts
                or ts < float(progress.get("started", now))
                or now - ts > COMBAT_PANEL_LOST_TIMEOUT_SN
                or ts <= float(progress.get("evidence_consumed", 0))):
            return
        progress["evidence_consumed"] = ts
        floor = progress.get("hp_floor")
        value = evidence.get("fill")
        if floor is not None and value is not None and 0 <= value < floor:
            progress["hp_floor"] = value
            progress["last_fill"] = value
            log_event(self.st, "info", f"[HP-HAFIZA] G{generation} arada gorulen gecerli can alindi: %{floor*100:.1f} -> %{value*100:.1f} ({w})")

    def _handle_savasiyor(
        self, w, hp_var, hp_fill, hp_fill_ready, cc, hwnd, now,
        client_idx=None, target_generation=0, sample_ts=0,
        hp_sample_valid=True,
    ):
        if not self._target_sample_is_new(w, target_generation, sample_ts):
            return
        if not hp_var and hp_fill_ready:
            self._consume_target_hp_evidence(w, target_generation, sample_ts, now)
        if hp_var:
            self._hp_onceki_durum[w] = True
            self._hp_kayip_t.pop(w, None)
            self._araniyor_baslat_t.pop(w, None)
            visible_progress = self._combat_progress.get(w)
            if visible_progress is not None:
                visible_progress["missing_samples"] = 0
                visible_progress["missing_started"] = 0.0

            if hp_fill_ready and hp_sample_valid and hp_fill is not None:
                progress = self._combat_progress.get(w)
                if progress is None:
                    self._begin_combat_progress(w, hp_fill, now, damage_confirmed=False)
                    progress = self._combat_progress[w]
                else:
                    progress["samples"] = int(progress.get("samples", 0) or 0) + 1

                previous_floor = progress.get("hp_floor")
                if not is_plausible_hp_sample(
                    previous_floor,
                    hp_fill,
                    HP_MAX_UPWARD_JUMP,
                ):
                    # Vision bu kareyi normalde zaten reddeder. Bu ikinci
                    # kontrol, eski/harici bir veri yolu imkansiz bir can
                    # sicrama degeri gonderirse kurtarma veya hedef degisimi
                    # uretilmesini de engeller.
                    progress["check_after"] = now + COMBAT_POST_RECOVERY_WAIT_SN
                    last_reject = float(progress.get("last_rejected_log", 0) or 0)
                    if now - last_reject >= HP_DIAGNOSTIC_INTERVAL_SN:
                        progress["last_rejected_log"] = now
                        label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
                        previous_text = (
                            "--" if previous_floor is None
                            else f"{float(previous_floor) * 100:.1f}"
                        )
                        log_event(
                            self.st,
                            "warn",
                            f"[SAVAS-{label}] G{int(target_generation or 0)} imkansiz can "
                            f"artisi yok sayildi: taban=%{previous_text} "
                            f"simdi=%{float(hp_fill) * 100:.1f}; hedef korundu ({w})",
                        )
                    return
                progress["last_fill"] = float(hp_fill)

                hp_floor, advanced = track_hp_progress(
                    progress.get("hp_floor"),
                    hp_fill,
                    COMBAT_HP_PROGRESS_MIN,
                )
                progress["hp_floor"] = hp_floor
                if advanced:
                    if not hasattr(self, "_last_damage_t"):
                        self._last_damage_t = {}
                    self._last_damage_t[w] = now
                    progress["damage_confirmed"] = True
                    progress["last_progress"] = now
                    progress["check_after"] = now
                    progress["progress_events"] = int(progress.get("progress_events", 0) or 0) + 1
                    # Kurtarmalar yalnizca ardisik ilerlememe durumunu saysin.
                    # Can tekrar azaldiginda hedef normal sekilde calisiyor.
                    progress["recoveries"] = 0
                    self._combat_log_throttled(w, client_idx, progress, hp_fill, now, force=True)
                    return

                self._combat_log_throttled(w, client_idx, progress, hp_fill, now)

                last_progress = float(progress.get("last_progress", now) or now)
                check_after = float(progress.get("check_after", now) or now)
                recovery_wait = RECOVERY_SKILL_WAIT_SN if progress.get("recoveries", 0) else COMBAT_NO_PROGRESS_SN
                if now < check_after or now - last_progress < recovery_wait:
                    return

                recoveries = int(progress.get("recoveries", 0) or 0)
                if recoveries >= COMBAT_RECOVERY_MAX:
                    fill_text = f"{float(hp_fill) * 100:.1f}"
                    floor = progress.get("hp_floor")
                    floor_text = "--" if floor is None else f"{float(floor) * 100:.1f}"
                    no_progress = now - float(progress.get("last_progress", now) or now)
                    self._abandon_combat_target(
                        w,
                        cc,
                        now,
                        f"can=%{fill_text}, taban=%{floor_text}, {no_progress:.1f}sn yeni dusus yok; "
                        f"{COMBAT_RECOVERY_MAX} kurtarma sonrasinda azalmadi",
                    )
                    return

                # Kisa sureli ilerlememede hedefi koru ve kurtarma uygula.
                # Uc ardisik kurtarma da sonuc vermezse yukaridaki sinir,
                # acik kalan HP panelinin client'i sonsuza kadar kilitlemesini
                # engeller.
                if self._run_combat_recovery(w, hwnd):
                    recovered_at = time.time()
                    progress["recoveries"] = recoveries + 1
                    progress["last_progress"] = recovered_at
                    progress["check_after"] = recovered_at + COMBAT_POST_RECOVERY_WAIT_SN
                return
            return

        else:
            onceki_hp = self._hp_onceki_durum.get(w, None)
            hp_bekleme_sn = self._hp_bitis_gecikmesi(cc)
            progress = self._combat_progress.get(w)
            if progress is None:
                # Can dolgu alani bulunmayan eski kalibrasyon yolu da
                # SAVASIYOR durumuna girebilir. Kayip zamanini ve kurtarma
                # sayisini mutlaka kalici client durumunda tut.
                self._begin_combat_progress(
                    w, None, now, damage_confirmed=False,
                )
                progress = self._combat_progress[w]

            if onceki_hp is True:
                if w not in self._hp_kayip_t:
                    self._hp_kayip_t[w] = now
                    progress["missing_started"] = now
                    progress["missing_samples"] = 0

                progress["missing_samples"] = int(progress.get("missing_samples", 0) or 0) + 1
                missing_since = float(self._hp_kayip_t.get(w, now) or now)
                missing_for = now - missing_since
                floor = progress.get("hp_floor")
                near_zero = floor is not None and float(floor) <= COMBAT_DEATH_LOW_HP_MAX
                required_missing = hp_bekleme_sn
                missing_samples = int(progress.get("missing_samples", 0) or 0)
                if not near_zero:
                    # Yuksek canda panel kaybi olum degildir. Ancak pencere
                    # ortulmesi veya gercek bir takilma hedefi sonsuza kadar
                    # SAVASIYOR durumunda tutmamali. Once hedef client'i odaga
                    # getiren kademeli kurtarma dizisini sinirli sayida dene.
                    total_missing_since = float(
                        progress.get("missing_started", missing_since) or missing_since
                    )
                    total_missing_for = now - total_missing_since
                    recoveries = int(progress.get("recoveries", 0) or 0)
                    check_after = float(progress.get("check_after", 0) or 0)
                    recovery_wait = RECOVERY_SKILL_WAIT_SN if recoveries else COMBAT_PANEL_LOST_RECOVERY_SN

                    if (
                        missing_samples >= COMBAT_DEATH_MIN_ABSENT_SAMPLES
                        and (
                            total_missing_for >= COMBAT_PANEL_LOST_TIMEOUT_SN
                            or (
                                recoveries >= COMBAT_RECOVERY_MAX
                                and missing_for >= recovery_wait
                            )
                        )
                    ):
                        self._abandon_combat_target(
                            w, cc, now,
                            f"HP paneli toplam {total_missing_for:.1f}sn kayip; "
                            f"{recoveries}/{COMBAT_RECOVERY_MAX} kurtarma sonucu panel donmedi; "
                            "olum dogrulanmadi, kill/loot uygulanmadan aramaya donuluyor",
                        )
                        return

                    if (
                        missing_samples >= COMBAT_DEATH_MIN_ABSENT_SAMPLES
                        and missing_for >= recovery_wait
                        and now >= check_after
                    ):
                        if self._run_combat_recovery(w, hwnd):
                            recovered_at = time.time()
                            progress["recoveries"] = recoveries + 1
                            progress["last_progress"] = recovered_at
                            progress["check_after"] = (
                                recovered_at + COMBAT_POST_RECOVERY_WAIT_SN
                            )
                            # Bir sonraki deneme icin kesintisiz kayip fazini
                            # sifirla; toplam kayip zamani missing_started ile
                            # korunur ve mutlak sure siniri calismaya devam eder.
                            self._hp_kayip_t[w] = recovered_at
                            progress["missing_samples"] = 0
                            label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
                            log_event(
                                self.st,
                                "info",
                                f"[HP-{label}] kayip panel kurtarmasi "
                                f"{recoveries + 1}/{COMBAT_RECOVERY_MAX} tamamlandi; "
                                "panel yeniden kontrol ediliyor "
                                f"({w})",
                            )
                        else:
                            # Gecici CAPTCHA/global duraklama veya odak hatasi
                            # ayni aksiyonun her karede tekrar denenmesine yol
                            # acmasin.
                            progress["check_after"] = now + COMBAT_POST_RECOVERY_WAIT_SN
                        return

                    label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
                    last_uncertain = float(progress.get("last_uncertain_log", 0) or 0)
                    if missing_samples == 1 or now - last_uncertain >= 5.0:
                        progress["last_uncertain_log"] = now
                        floor_text = "--" if floor is None else f"{float(floor) * 100:.1f}"
                        log_event(
                            self.st,
                            "warn",
                            f"[OLUM-{label}] karar bekletildi: son_can=%{floor_text} > "
                            f"%{COMBAT_DEATH_LOW_HP_MAX * 100:.0f}, panel_yok={missing_for:.2f}sn "
                            f"toplam_yok={total_missing_for:.2f}sn yok_kare={missing_samples} "
                            f"kurtarma={recoveries}/{COMBAT_RECOVERY_MAX}; "
                            f"hedef/loot degismedi ({w})",
                        )
                    return
                if missing_samples == 1:
                    label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
                    floor_text = "--" if floor is None else f"{float(floor) * 100:.1f}"
                    log_event(
                        self.st,
                        "debug",
                        f"[SAVAS-{label}] HP paneli kayip; son_can=%{floor_text}, olum icin "
                        f"{required_missing:.2f}sn ve {COMBAT_DEATH_MIN_ABSENT_SAMPLES} taze "
                        f"yok-kare bekleniyor ({w})",
                    )
                if (
                    missing_for < required_missing
                    or missing_samples < COMBAT_DEATH_MIN_ABSENT_SAMPLES
                ):
                    return

            missing_since = float(self._hp_kayip_t.get(w, now) or now)
            self._hp_kayip_t.pop(w, None)
            self._hp_onceki_durum.pop(w, None)

            damage_confirmed = bool(progress.get("damage_confirmed"))
            if onceki_hp is True and damage_confirmed:
                start_fill = progress.get("start_fill")
                floor = progress.get("hp_floor")
                missing_for = now - missing_since
                missing_samples = int(progress.get("missing_samples", 0) or 0)
                label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
                start_text = "--" if start_fill is None else f"{float(start_fill) * 100:.1f}"
                floor_text = "--" if floor is None else f"{float(floor) * 100:.1f}"
                log_event(
                    self.st,
                    "info",
                    f"Mob oldu: {w} [{label} G{int(self._target_generation.get(w, 0) or 0)} "
                    f"baslangic=%{start_text} en_dusuk=%{floor_text} "
                    f"panel_yok={missing_for:.2f}sn yok_kare={missing_samples} hasar=evet]",
                )
                self._clear_target_click_cooldown(w, cc, now)
                self._son_tiklama_zamani[w] = now
                self._record_kill(w, client_idx)
                if cc.get("oto_loot", True):
                    self._loot_burst_async(
                        w,
                        hwnd,
                        cc,
                        "mob oldu",
                        taps=LOOT_KILL_TAPS,
                        delay=LOOT_KILL_DELAY,
                        interval=LOOT_KILL_INTERVAL,
                    )
            elif onceki_hp is True:
                label = f"C{client_idx}" if client_idx in CLIENT_IDS else "C?"
                missing_for = now - missing_since
                missing_samples = int(progress.get("missing_samples", 0) or 0)
                log_event(
                    self.st,
                    "warn",
                    f"[OLUM-{label}] ust hedef paneli {missing_for:.2f}sn kayip fakat "
                    f"kirmizi can azalmasi dogrulanmadi (yok_kare={missing_samples}); "
                    f"olum ve loot iptal ({w})",
                )
                self._son_tiklama_t[w] = now
            else:
                self._son_tiklama_t[w] = now

            self._clear_combat_progress(w)

            self.dur[w] = "ARANIYOR"
            with self.st.lk:
                if w in self.st.target_memory:
                    self.st.target_memory[w] = {"positions": [], "consecutive_found": 0,
                                                 "confirmed": False, "last_confirmed_pos": None, "misses": 0}

    def _anti_sucuk_cooldown_ready(self, w, now=None, kind="genel"):
        now = now or time.time()
        bekleme = FIXED_ANTI_KURTARMA_BEKLEME_SN
        son = float(self._son_manevra_t.get((w, kind), 0) or 0)
        return bekleme <= 0 or now - son >= bekleme

    def _mark_anti_sucuk_manevra(self, w, when=None, kind="genel"):
        t = when or time.time()
        self._son_manevra_t[(w, kind)] = t

    def _anti_sucuk_araniyor_manevra(self, w, hwnd, now):
        if not self._anti_sucuk_cooldown_ready(w, now, "hedef_yoksa"):
            self._anti_sucuk_log_throttled(w, "hedef_yoksa_cooldown", f"Hareketli Metin Arama bekliyor: cooldown ({w})", now)
            return False
        if self._s_basmis.get(w, False):
            self._anti_sucuk_log_throttled(w, "hedef_yoksa_reentry", f"Hareketli Metin Arama zaten calisiyor ({w})", now)
            return False
        if self._input_blocked(w):
            self._anti_sucuk_log_throttled(w, "hedef_yoksa_input", f"Hareketli Metin Arama atlandi: input bloklu ({w})", now)
            return False
        self._s_basmis[w] = True
        try:
            for attempt, search_key in enumerate(METIN_SEARCH_KEYS, 1):
                log_event(
                    self.st,
                    "info",
                    f"Hareketli Metin Arama: {search_key.upper()} {METIN_SEARCH_Q_HOLD_SN:.0f}sn basili ({attempt}/{len(METIN_SEARCH_KEYS)}, {w})",
                )
                if not self._hold_recovery_key(w, search_key, METIN_SEARCH_Q_HOLD_SN, hwnd):
                    return False
                if self._stop_event.wait(METIN_SEARCH_Q_SETTLE_SN) or self._recovery_input_blocked(w):
                    return False
                with self.st.lk:
                    latest = dict(self.st.wdata.get(w, {}))
                latest_ts = float(latest.get("publish_ts", latest.get("ts", 0)) or 0)
                ecx, ecy = latest.get("ekran_merkez", (0, 0))
                ignore_radius = latest.get("client_cfg", {}).get("ignore_radius", 35)
                centers = self._filter_target_failures(w, latest.get("merkezler", []), time.time())
                blocked = self._approach_blocked_target.get(w)
                if blocked:
                    centers = filter_targets_away_from(
                        centers,
                        blocked.get("pos"),
                        60.0,
                    )
                target_found = (
                    latest_ts > 0
                    and time.time() - latest_ts <= DEFAULT_TARGET_FRAME_MAX_AGE
                    and any(np.hypot(x - ecx, y - ecy) > ignore_radius for x, y in centers)
                )
                if target_found:
                    log_event(
                        self.st,
                        "info",
                        f"Hareketli Metin Arama: {attempt}. adim {search_key.upper()} sonrasi Metin bulundu ({w})",
                    )
                    break
            t = time.time()
            self._araniyor_baslat_t[w] = t
            self._mark_anti_sucuk_manevra(w, t, "hedef_yoksa")
            log_event(self.st, "info", f"Hareketli Metin Arama tamamlandi ({w})")
            return True
        finally:
            self._s_basmis[w] = False

    def run(self):
        while not self._stop_event.is_set():
            if self._stop_event.wait(0.02):
                break
            with self.st.lk:
                aktif = self.st.aktif
                wd = dict(self.st.wdata)
                captcha_cd = dict(self.st.captcha_cd)

            if not aktif:
                self.dur.clear(); self.dogr_t.clear(); self.dogr_n.clear()
                self._hp_onceki_durum.clear(); self._son_tiklama_t.clear()
                self._hp_ignore_until.clear(); self._hp_kayip_t.clear()
                self._approach.clear(); self._approach_blocked_target.clear()
                self._recovery_reclick.clear()
                self._stale_frame_diag_t.clear()
                self._combat_progress.clear()
                self._target_generation.clear(); self._last_target_sample.clear()
                self._combat_diag_t.clear()
                self._buff_next_t.clear(); self._buff_running.clear()
                self._buff_needs_remount.clear(); self._buff_diag_t.clear()
                continue

            ordered_wd = []
            seen_w = set()
            for ci in CLIENT_IDS:
                cw = self.cfg.client(ci).get("pencere", "Yok")
                if cw in wd and cw not in seen_w:
                    ordered_wd.append((cw, wd[cw]))
                    seen_w.add(cw)
            for item in wd.items():
                if item[0] not in seen_w:
                    ordered_wd.append(item)
                    seen_w.add(item[0])
            for w, data in ordered_wd:
                # Onceki client uzun bir buff/kurtarma hareketi yaptiysa dongu
                # basinda alinan snapshot eskimis olabilir. Her client kararindan
                # hemen once VisionThread'in en son yayinini tekrar al.
                with self.st.lk:
                    latest_data = self.st.wdata.get(w)
                if latest_data is None:
                    continue
                data = dict(latest_data)
                data_ts = float(data.get("ts", 0) or 0)
                publish_ts = float(data.get("publish_ts", data_ts) or 0)
                if data_ts and time.time() - data_ts > VISION_STALE_FRAME_SN:
                    stale_age = time.time() - data_ts
                    last_stale_log = float(self._stale_frame_diag_t.get(w, 0) or 0)
                    if time.time() - last_stale_log >= VISION_STALE_LOG_EVERY_SN:
                        self._stale_frame_diag_t[w] = time.time()
                        with self.st.lk:
                            self.st.durum[w] = "GORUNTU DONDU"
                        log_event(
                            self.st,
                            "warn",
                            f"[GORUNTU] yeni kare gelmiyor ({stale_age:.1f}sn); hareket uygulanmadi ({w})",
                        )
                    continue
                self._stale_frame_diag_t.pop(w, None)
                if time.time() < captcha_cd.get(w, 0):
                    with self.st.lk:
                        self.st.durum[w] = "CAPTCHA"
                        self.st.captcha_block[w] = True
                        self.st.captcha_state[w] = True
                    continue
                with self.st.lk:
                    if self.st.captcha_block.get(w, False):
                        if time.time() >= self.st.captcha_cd.get(w, 0):
                            self.st.captcha_block[w] = False
                            self.st.captcha_state[w] = False

                now = time.time()
                self._init(w)
                mrk = data.get("merkezler",[])
                hedefler = data.get("hedefler", [])
                hp_var = data.get("hp_var",False)
                hp_fill = data.get("hp_fill")
                hp_fill_ready = bool(data.get("hp_fill_ready", False))
                hp_sample_valid = bool(data.get("hp_sample_valid", True))
                scene_moving = bool(data.get("scene_moving", False))
                scene_motion_ready = bool(data.get("scene_motion_ready", False))
                target_generation = int(data.get("target_generation", 0) or 0)
                ecx,ecy = data.get("ekran_merkez",(0,0))
                ox,oy = data.get("offset",(0,0))
                hwnd = data.get("hwnd")
                cc = data.get("client_cfg",{})
                client_idx = data.get("client_idx")
                try:
                    if self._handle_player_life(w, hwnd, client_idx):
                        continue
                except Exception as exc:
                    self._anti_sucuk_log_throttled(w, "revive_error", f"Yeniden dogma kontrol hatasi; islem bekletildi: {exc}", now)
                    continue
                if not hasattr(self, "_last_damage_t"):
                    self._last_damage_t, self._no_damage_warn_t = {}, {}
                if not hasattr(self, "_no_damage_warn_t"):
                    self._no_damage_warn_t = {}
                last_damage = self._last_damage_t.setdefault(w, now)
                if now - last_damage >= 120 and now - self._no_damage_warn_t.get(w, 0) >= 60:
                    self._no_damage_warn_t[w] = now
                    log_event(self.st, "warn", f"[ILERLEME-C{client_idx}] {now-last_damage:.0f}sn hasar dogrulanamadi; pencere/HP/hedef kontrolu gerekiyor ({w})")
                ign = cc.get("ignore_radius",35)

                gecerli = [m for m in mrk if np.hypot(m[0]-ecx,m[1]-ecy) > ign]

                with self.st.lk:
                    self.st.durum[w] = self.dur.get(w,"?")

                state = self.dur[w]

                # Olumden sonraki Z serisi tamamlanmadan ayni client yeni bir
                # hedefe tiklamasin. Diger client'lar dongude ilerlemeye devam eder.
                if self._loot_running.get(w, False):
                    with self.st.lk:
                        self.st.durum[w] = "LOOT"
                    continue

                if now >= float(self._buff_next_t.get(w, 0) or 0):
                    if self._run_buff_cycle(w, hwnd):
                        self._buff_next_t[w] = time.time() + BUFF_INTERVAL_SECONDS
                        continue

                # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

                try:
                    action_ts = publish_ts or data_ts
                    if self._handle_recovery_reclick(w, hwnd, cc, hedefler, data_ts, ox, oy, client_idx):
                        continue
                    if state == "ARANIYOR":
                        if not hp_var and not self._default_frame_fresh(w, action_ts, now):
                            continue
                        self._handle_araniyor(w, gecerli, hp_var, ecx, ecy, hwnd, cc, ox, oy, hedefler, action_ts, client_idx=client_idx)
                    elif state == "DOGRULAMA":
                        self._handle_dogrulama(
                            w, hp_var, hp_fill, hp_fill_ready,
                            scene_moving, scene_motion_ready, cc, hwnd,
                            target_generation=target_generation,
                            sample_ts=data_ts,
                            client_idx=client_idx,
                            hp_sample_valid=hp_sample_valid,
                        )
                    elif state == "SAVASIYOR":
                        self._handle_savasiyor(
                            w, hp_var, hp_fill, hp_fill_ready,
                            cc, hwnd, now,
                            client_idx=client_idx,
                            target_generation=target_generation,
                            sample_ts=data_ts,
                            hp_sample_valid=hp_sample_valid,
                        )
                except Exception as e:
                    log_event(self.st, "error", f"ActionThread hatasi ({state}): {e}")
                    self.dur[w] = "ARANIYOR"  # gÃ¼venli sÄ±fÄ±rlama

class VisionThread(threading.Thread):
    def __init__(self, cfg, state):
        super().__init__(daemon=True)
        self.cfg, self.st = cfg, state
        self._stop_event = threading.Event()
        self.captcha_w = {ci: None for ci in CLIENT_IDS}
        self.model_cache = {}
        self._captcha_last_log = {}
        self._captcha_watcher_started_t = {}
        self._last_debug_encode = {}
        self._message_last_action = {}
        self._message_last_reply = {}
        self._message_last_ocr = {}
        self._message_last_handled_incoming = {}
        self._message_handled_signatures = {}
        self._message_pending_signature = {}
        self._message_baseline_pending = {}
        self._message_window_answered = {}
        self._message_seen_since = {}
        self._message_open_allowed = {}
        self._message_global_reply_buffer = deque(maxlen=10)
        self._duplicate_window_warn_t = {}
        self._window_issue_last_log = {}
        self._global_pause_last_warn = 0.0
        self._debug_encode_interval = 0.30
        self._started_at = time.time()
        self._hp_templates = {}  # ci â†’ {"gray": template_gray, "edges": template_edges, "w": w, "h": h}
        self._hp_template_cache = {}  # (ci, scale_key) â†’ scaled variant
        self._message_templates = []
        self._message_template_cache = {}
        self._message_notify_last_debug = 0.0
        self._message_notify_best_template_score = 0.0
        self._message_notify_color_candidates = 0
        self._prev_det = {}  # pk â†’ [(cx,cy),...] Ã¶nceki karedeki ham tespitler (ardÄ±ÅŸÄ±k kare doÄŸrulamasÄ± iÃ§in)
        self._prev_target_centers = {}  # pk -> {"ts": float, "centers": [(cx,cy),...]} iki kare hareket filtresi
        self._prev_scene_roi = {}  # pk â†’ son frame'in merkez ROI'si (hareketsiz tespiti iÃ§in)
        self._scene_sample_t = {}
        self._scene_motion_state = {}
        self._scene_motion_votes = {}
        self._hp_fill_hist = {}
        self._hp_accepted_floor = {}
        self._hp_presence_hist = {}
        self._hp_generation_seen = {}
        self._hp_diag_t = {}
        self._hp_diag_signature = {}
        self._hp_reject_t = {}
        self._load_hp_templates()
        self._load_message_templates()

    def stop(self):
        self._stop_event.set()

    def _publish_client_vision(self, pk, data):
        """Bir client sonucunu diger client'larin inference'ini bekletmeden yayinla."""
        published = dict(data or {})
        published["publish_ts"] = time.time()
        with self.st.lk:
            generation = int(published.get("target_generation", 0) or 0)
            ts = float(published.get("ts", 0) or 0)
            fill = published.get("hp_fill")
            if (generation == int(self.st.target_generation.get(pk, 0) or 0)
                    and ts > 0 and published.get("hp_var")
                    and published.get("hp_fill_ready") and published.get("hp_sample_valid")
                    and fill is not None and np.isfinite(fill) and 0 <= fill <= 1):
                previous = self.st.target_hp_evidence.get(pk)
                if previous is None or previous["generation"] != generation:
                    self.st.target_hp_evidence[pk] = {"generation": generation, "fill": float(fill), "ts": ts}
                elif ts > previous["ts"] and float(fill) < previous["fill"]:
                    self.st.target_hp_evidence[pk] = {"generation": generation, "fill": float(fill), "ts": ts}
            self.st.wdata[pk] = published
        return published

    def _publish_debug_frame(self, pk, encoded_frame):
        if not encoded_frame:
            return
        with self.st.lk:
            self.st.frame_b64[pk] = encoded_frame

    def _sync_hp_generation(self, pk, frame_target_generation):
        """Hedef degistiginde Vision tarafindaki tum HP oylarini sifirla."""
        if not hasattr(self, "_hp_accepted_floor"):
            self._hp_accepted_floor = {}
        if not hasattr(self, "_hp_reject_t"):
            self._hp_reject_t = {}
        generation = int(frame_target_generation or 0)
        if self._hp_generation_seen.get(pk) == generation:
            return False
        self._hp_generation_seen[pk] = generation
        self._hp_fill_hist.pop(pk, None)
        self._hp_accepted_floor.pop(pk, None)
        self._hp_presence_hist.pop(pk, None)
        self._hp_reject_t.pop(pk, None)
        return True

    def _measure_scene_motion(self, pk, image, now):
        current = self._scene_motion_state.get(pk, {
            "ready": False,
            "moving": False,
            "score": 0.0,
            "confidence": 0.0,
            "points": 0,
        })
        if now - float(self._scene_sample_t.get(pk, 0) or 0) < SCENE_SAMPLE_INTERVAL_SN:
            return dict(current)

        gray, mask = prepare_scene_frame(image)
        if gray is None:
            return dict(current)
        previous = self._prev_scene_roi.get(pk)
        self._prev_scene_roi[pk] = gray
        self._scene_sample_t[pk] = now
        measured = estimate_scene_motion(previous, gray, mask)
        if not measured.get("ready"):
            self._scene_motion_state[pk] = measured
            return dict(measured)

        votes = self._scene_motion_votes.setdefault(pk, deque(maxlen=3))
        votes.append(bool(measured.get("moving", False)))
        # Iki olumlu ornek hareketi baslatir; iki olumsuz ornek durdurur.
        if len(votes) >= 2:
            measured["moving"] = sum(1 for vote in votes if vote) >= 2
        self._scene_motion_state[pk] = measured
        return dict(measured)

    def _ensure_captcha_watcher(self, ci):
        cw = self.captcha_w.get(ci)
        if cw:
            return cw
        if not CAPTCHA_OK:
            key = (ci, "captcha_import_failed")
            now = time.time()
            if now - self._captcha_last_log.get(key, 0) > 10:
                log_event(self.st, "warn", "captcha_solver.py yuklenemedi")
                self._captcha_last_log[key] = now
            return None

        def _cb(level, msg):
            log_event(self.st, level, msg)

        self.captcha_w[ci] = CaptchaWatcher(
            client_id=ci,
            log_cb=_cb,
            input_lock=input_transaction_lock,
        )
        self._captcha_watcher_started_t[ci] = time.time()
        log_event(self.st, "info", f"Client {ci} captcha solver yukleniyor")
        return self.captcha_w[ci]

    def _load_message_templates(self):
        self._message_templates = []
        self._message_template_cache = {}
        try:
            files = [f for f in os.listdir(MESSAGE_TEMPLATE_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))]
        except Exception:
            files = []
        for name in sorted(files):
            path = os.path.join(MESSAGE_TEMPLATE_DIR, name)
            img = cv2.imread(path, cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                log_event(self.st, "warn", f"Mesaj template okunamadi: {name}")
                continue
            h, w = img.shape[:2]
            if h < 8 or w < 8:
                log_event(self.st, "warn", f"Mesaj template cok kucuk: {name} ({w}x{h})")
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 50, 150)
            self._message_templates.append({"name": name, "gray": gray, "edges": edges, "w": w, "h": h})
            log_event(self.st, "info", f"Mesaj template yuklendi: {name} ({w}x{h})")
        if not self._message_templates:
            log_event(self.st, "info", "Mesaj template yok; siki renk filtresi kullanilacak")

    def _get_scaled_message_template(self, tpl, scale):
        key = (tpl.get("name", ""), int(round(scale * 1000)))
        cached = self._message_template_cache.get(key)
        if cached is not None:
            return cached
        if abs(scale - 1.0) < 0.001:
            result = {"gray": tpl["gray"], "edges": tpl["edges"], "w": tpl["w"], "h": tpl["h"], "name": tpl.get("name", "")}
        else:
            tw = max(8, int(round(tpl["w"] * scale)))
            th = max(8, int(round(tpl["h"] * scale)))
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            gray = cv2.resize(tpl["gray"], (tw, th), interpolation=interp)
            edges = cv2.resize(tpl["edges"], (tw, th), interpolation=interp)
            result = {"gray": gray, "edges": edges, "w": tw, "h": th, "name": tpl.get("name", "")}
        self._message_template_cache[key] = result
        return result

    def _load_hp_templates(self):
        self._hp_templates = {}
        self._hp_template_cache = {}
        for ci in CLIENT_IDS:
            tpl_path = os.path.join(HP_TEMPLATE_DIR, f"client_{ci}.png")
            if os.path.exists(tpl_path):
                img = cv2.imread(tpl_path, cv2.IMREAD_COLOR)
                if img is not None and img.size > 0:
                    h, w = img.shape[:2]
                    if h >= 4 and w >= HP_TEMPLATE_MIN_WIDTH:
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        edges = cv2.Canny(gray, 50, 150)
                        cc = self.cfg.client(ci)
                        bar_box = None
                        auto_bar = cc.get("hp_auto_bar_region")
                        if cc.get("hp_panel_auto") and isinstance(auto_bar, (list, tuple)) and len(auto_bar) == 4:
                            bar_box = (
                                int(round(float(auto_bar[2]) * w)),
                                int(round(float(auto_bar[0]) * h)),
                                int(round((float(auto_bar[3]) - float(auto_bar[2])) * w)),
                                int(round((float(auto_bar[1]) - float(auto_bar[0])) * h)),
                            )
                        mask = hp_panel_structure_mask((h, w), bar_box)
                        self._hp_templates[ci] = {
                            "gray": gray, "edges": edges, "mask": mask,
                            "w": w, "h": h,
                        }
                        log_event(self.st, "info", f"Client {ci} HP template yuklendi: {w}x{h}")
                        if not cc.get("hp_panel_auto"):
                            log_event(
                                self.st,
                                "warn",
                                f"Client {ci} eski HP secimini kullaniyor; can %100 iken panelin tamamini yeniden secin",
                            )
                    else:
                        log_event(self.st, "warn", f"Client {ci} HP template cok kucuk: {w}x{h}")
                else:
                    log_event(self.st, "warn", f"Client {ci} HP template okunamadi")
            else:
                log_event(self.st, "info", f"Client {ci} HP template yok (once HP bar secin)")

    def _get_scaled_template(self, ci, scale):
        scale_key = int(round(scale * 1000))
        cache_key = (ci, scale_key)
        cached = self._hp_template_cache.get(cache_key)
        if cached is not None:
            return cached
        tpl = self._hp_templates.get(ci)
        if tpl is None:
            return None
        if abs(scale - 1.0) < 0.001:
            result = {
                "gray": tpl["gray"], "edges": tpl["edges"], "mask": tpl.get("mask"),
                "w": tpl["w"], "h": tpl["h"],
            }
        else:
            tw = max(HP_TEMPLATE_MIN_WIDTH, int(round(tpl["w"] * scale)))
            th = max(4, int(round(tpl["h"] * scale)))
            interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            gray = cv2.resize(tpl["gray"], (tw, th), interpolation=interp)
            edges = cv2.Canny(gray, 50, 150)
            mask = tpl.get("mask")
            if mask is not None:
                mask = cv2.resize(mask, (tw, th), interpolation=cv2.INTER_NEAREST)
            result = {"gray": gray, "edges": edges, "mask": mask, "w": tw, "h": th}
        self._hp_template_cache[cache_key] = result
        return result

    def _match_hp_template(self, roi, ci):
        tpl = self._hp_templates.get(ci)
        if tpl is None or roi is None or roi.size == 0:
            return {"matched": False, "score": 0.0, "anchor_matched": False, "anchor_score": 0.0, "x": 0, "y": 0, "w": 0, "h": 0}
        roi_h, roi_w = roi.shape[:2]
        if roi_h < 4 or roi_w < HP_TEMPLATE_MIN_WIDTH:
            return {"matched": False, "score": 0.0, "anchor_matched": False, "anchor_score": 0.0, "x": 0, "y": 0, "w": 0, "h": 0}
        best = {
            "matched": False, "score": 0.0,
            "structure_matched": False, "structure_score": 0.0,
            "anchor_matched": False, "anchor_score": 0.0,
            "x": 0, "y": 0, "w": 0, "h": 0,
        }
        best_structure_score = 0.0
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        roi_edges = cv2.Canny(roi_gray, 50, 150)
        
        scales = (1.0,) if int(tpl.get("w", 0)) >= 80 else HP_TEMPLATE_SCALES
        for scale in scales:
            variant = self._get_scaled_template(ci, scale)
            if variant is None:
                continue
            th, tw = variant["h"], variant["w"]
            if th > roi_h or tw > roi_w or th < 4 or tw < HP_TEMPLATE_MIN_WIDTH:
                continue
            gray_scores = cv2.matchTemplate(roi_gray, variant["gray"], cv2.TM_CCOEFF_NORMED)
            _gray_min, score_gray, _gray_min_loc, gray_loc = cv2.minMaxLoc(gray_scores)

            edge_loc = gray_loc
            score_edges = 0.0
            mask = variant.get("mask")
            try:
                if mask is not None and np.count_nonzero(mask) >= 8:
                    edge_scores = cv2.matchTemplate(
                        roi_edges,
                        variant["edges"],
                        cv2.TM_CCORR_NORMED,
                        mask=mask,
                    )
                else:
                    edge_scores = cv2.matchTemplate(roi_edges, variant["edges"], cv2.TM_CCOEFF_NORMED)
                edge_scores = np.nan_to_num(edge_scores, nan=0.0, posinf=0.0, neginf=0.0)
                _edge_min, score_edges, _edge_min_loc, edge_loc = cv2.minMaxLoc(edge_scores)
            except cv2.error:
                score_edges = 0.0

            score_gray = float(np.nan_to_num(score_gray, nan=0.0, posinf=0.0, neginf=0.0))
            score_edges = float(score_edges)
            best_structure_score = max(best_structure_score, score_edges)
            if score_edges >= score_gray:
                score, best_loc = score_edges, edge_loc
            else:
                score, best_loc = score_gray, gray_loc
            if score > best["score"]:
                best = {
                    "matched": score >= HP_TEMPLATE_MIN_SCORE,
                    "score": score,
                    "anchor_matched": False,
                    "anchor_score": 0.0,
                    "x": int(best_loc[0]), "y": int(best_loc[1]),
                    "w": tw, "h": th,
                }

        anchor_result = match_hp_panel_anchor(roi, tpl.get("gray"))
        best["anchor_matched"] = bool(anchor_result.get("matched"))
        best["anchor_score"] = float(anchor_result.get("score", 0.0) or 0.0)
        best["structure_score"] = max(best_structure_score, best["anchor_score"])
        best["structure_matched"] = bool(
            best_structure_score >= HP_TEMPLATE_MIN_SCORE or best["anchor_matched"]
        )
        best["matched"] = bool(best.get("matched") or best["anchor_matched"])
        best["score"] = max(float(best.get("score", 0.0) or 0.0), best["anchor_score"])
        return best

    def _unload_ocr(self):
        for ci in CLIENT_IDS:
            cw = self.captcha_w.get(ci)
            if cw:
                with cw._lock:
                    cw._reader = None
                    cw._hazir = False
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _active_client_pks(self):
        keys = []
        for ci in CLIENT_IDS:
            cc = self.cfg.client(ci)
            if not cc.get("aktif", True):
                continue
            pk = cc.get("pencere", "Yok")
            if pk != "Yok":
                keys.append(pk)
        return keys

    def _clear_orphaned_input_locks(self):
        """Release only locks owned by a removed or definitively closed window."""
        active_keys = set(self._active_client_pks())
        with self.st.lk:
            owners = (
                (self.st.captcha_global_active, self.st.captcha_global_owner,
                 self._clear_global_captcha),
                (self.st.message_global_active, self.st.message_global_owner,
                 self._clear_global_message),
            )
        for active, owner, clear in owners:
            if not active or not owner:
                continue
            if owner not in active_keys:
                clear("owner inactive")
                continue
            try:
                hwnd = hwnd_al(owner)
                closed = bool(hwnd) and not win32gui.IsWindow(hwnd)
            except Exception:
                # A failed probe is not proof of closure. Keep the safety lock.
                continue
            if closed:
                clear("owner window closed")

    def _log_window_issue(self, ci, pk, issue, message):
        key = (ci, pk, issue)
        now = time.time()
        if now - self._window_issue_last_log.get(key, 0) >= WINDOW_ISSUE_LOG_INTERVAL:
            log_event(self.st, "warn", message)
            self._window_issue_last_log[key] = now

    def _watch_global_pause(self):
        with self.st.lk:
            active = self.st.global_pause_active
            since = self.st.global_pause_since
            kind = self.st.global_pause_kind
            owner = self.st.global_pause_owner
            reason = self.st.global_pause_reason
        if not active or not since:
            return
        now = time.time()
        elapsed = now - since
        if elapsed >= GLOBAL_PAUSE_WARN_AFTER and now - self._global_pause_last_warn >= GLOBAL_PAUSE_WARN_EVERY:
            log_event(self.st, "warn", f"[PAUSE] {kind} {elapsed:.0f}s devam ediyor owner={owner} reason={reason}")
            self._global_pause_last_warn = now

    def _set_global_captcha(self, owner_pk, owner_ci=None, reason="CAPTCHA"):
        now = time.time()
        should_log = False
        with input_transaction_lock:
            with self.st.lk:
                prev_active = self.st.captcha_global_active
                prev_owner = self.st.captcha_global_owner
                self.st.captcha_global_active = True
                self.st.captcha_global_owner = owner_pk
                if not self.st.captcha_global_since:
                    self.st.captcha_global_since = now
                self.st.captcha_block[owner_pk] = True
                self.st.captcha_state[owner_pk] = True
                self.st.durum[owner_pk] = "CAPTCHA"
                should_log = (not prev_active) or (prev_owner != owner_pk)
        if should_log:
            label = f"Client {owner_ci}" if owner_ci else owner_pk
            log_event(self.st, "warn", f"{label} captcha islemi aktif: {reason}")

    def _clear_global_captcha(self, reason=""):
        now = time.time()
        with self.st.lk:
            was_active = self.st.captcha_global_active
            owner_pk = self.st.captcha_global_owner
            self.st.captcha_global_active = False
            self.st.captcha_global_owner = None
            self.st.captcha_global_since = 0.0
            if owner_pk and now >= self.st.captcha_cd.get(owner_pk, 0):
                self.st.captcha_block[owner_pk] = False
                self.st.captcha_state[owner_pk] = False
                if self.st.durum.get(owner_pk) in ("CAPTCHA", "CAPTCHA BEKLE", "CAPTCHA OCR"):
                    self.st.durum[owner_pk] = "BEKLIYOR"
        if was_active:
            suffix = f": {reason}" if reason else ""
            log_event(self.st, "info", f"Captcha islemi temizlendi{suffix}")

    def _message_captcha_enabled(self, cc):
        if "message_captcha" in cc:
            return bool(cc.get("message_captcha"))
        global_value = self.cfg.g("message_captcha")
        return True if global_value is None else bool(global_value)

    def _message_key(self, ci, pk):
        return f"{int(ci)}::{pk}"

    def _warn_duplicate_client_windows(self):
        pairs = []
        for ci in CLIENT_IDS:
            cc = self.cfg.client(ci)
            if not cc.get("aktif", True):
                continue
            pk = cc.get("pencere", "Yok")
            if pk != "Yok":
                pairs.append((ci, pk))
        seen = {}
        now = time.time()
        for ci, pk in pairs:
            if pk not in seen:
                seen[pk] = ci
                continue
            key = pk
            if now - self._duplicate_window_warn_t.get(key, 0) >= 15.0:
                log_event(self.st, "error", f"Client {seen[pk]} ve Client {ci} ayni pencereye bagli: {pk}")
                self._duplicate_window_warn_t[key] = now

    def _set_global_message(self, owner_pk, owner_ci=None, reason="MESAJ"):
        now = time.time()
        should_log = False
        with input_transaction_lock:
            with self.st.lk:
                prev_active = self.st.message_global_active
                prev_owner = self.st.message_global_owner
                self.st.message_global_active = True
                self.st.message_global_owner = owner_pk
                if not self.st.message_global_since:
                    self.st.message_global_since = now
                self.st.captcha_block[owner_pk] = True
                self.st.captcha_state[owner_pk] = True
                self.st.durum[owner_pk] = "MESAJ"
                should_log = (not prev_active) or (prev_owner != owner_pk)
        if should_log:
            label = f"Client {owner_ci}" if owner_ci else owner_pk
            log_event(self.st, "warn", f"{label} [MESAJ] islemi aktif: {reason}")

    def _clear_global_message(self, reason=""):
        now = time.time()
        with self.st.lk:
            was_active = self.st.message_global_active
            owner_pk = self.st.message_global_owner
            self.st.message_global_active = False
            self.st.message_global_owner = None
            self.st.message_global_since = 0.0
            if owner_pk:
                if now < self.st.captcha_cd.get(owner_pk, 0):
                    self.st.captcha_block[owner_pk] = True
                    self.st.captcha_state[owner_pk] = True
                    self.st.durum[owner_pk] = "CAPTCHA"
                else:
                    self.st.captcha_block[owner_pk] = False
                    self.st.captcha_state[owner_pk] = False
                    if self.st.durum.get(owner_pk) in ("MESAJ", "MESAJ BEKLE"):
                        self.st.durum[owner_pk] = "BEKLIYOR"
        if was_active:
            suffix = f": {reason}" if reason else ""
            log_event(self.st, "info", f"[MESAJ] islemi temizlendi{suffix}")

    def _detect_message_notification(self, img):
        if img is None or img.size == 0:
            return None
        h, w = img.shape[:2]
        if h < 300 or w < 400:
            return None
        x1, y1 = int(w * 0.86), int(h * 0.18)
        x2, y2 = w, int(h * 0.55)
        roi = img[y1:y2, x1:x2]
        if roi.size == 0:
            return None
        template_hit = self._detect_message_notification_template(roi, x1, y1)
        if template_hit:
            return template_hit
        color_hit = self._detect_message_notification_color(roi, x1, y1, w)
        if color_hit:
            return color_hit
        now = time.time()
        if now - self._message_notify_last_debug > 3.0:
            log_event(
                self.st,
                "debug",
                "Mesaj bildirimi yok: "
                f"roi=({x1},{y1},{x2},{y2}) "
                f"template={self._message_notify_best_template_score:.2f} "
                f"renk_aday={self._message_notify_color_candidates}",
            )
            self._message_notify_last_debug = now
        return None

    def _detect_message_notification_template(self, roi, ox=0, oy=0):
        if not self._message_templates:
            self._message_notify_best_template_score = 0.0
            return None
        roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        roi_edges = cv2.Canny(roi_gray, 50, 150)
        rh, rw = roi_gray.shape[:2]
        best = None
        best_score = 0.0
        for tpl in self._message_templates:
            for scale in MESSAGE_TEMPLATE_SCALES:
                variant = self._get_scaled_message_template(tpl, scale)
                tw, th = int(variant["w"]), int(variant["h"])
                if tw > rw or th > rh:
                    continue
                score_gray = cv2.matchTemplate(roi_gray, variant["gray"], cv2.TM_CCOEFF_NORMED)
                _, max_gray, _, loc_gray = cv2.minMaxLoc(score_gray)
                score_edges = cv2.matchTemplate(roi_edges, variant["edges"], cv2.TM_CCOEFF_NORMED)
                _, max_edges, _, loc_edges = cv2.minMaxLoc(score_edges)
                if max_edges > max_gray:
                    score, loc = float(max_edges), loc_edges
                else:
                    score, loc = float(max_gray), loc_gray
                best_score = max(best_score, float(score))
                if score < MESSAGE_TEMPLATE_MIN_SCORE:
                    continue
                x, y = int(loc[0]), int(loc[1])
                cx, cy = ox + x + tw // 2, oy + y + th // 2
                if best is None or score > best["score"]:
                    best = {
                        "x": int(cx), "y": int(cy), "area": int(tw * th), "score": float(score),
                        "template": variant.get("name", ""), "mode": "template",
                    }
        self._message_notify_best_template_score = best_score
        return best

    def _detect_message_notification_color(self, roi, ox=0, oy=0, full_w=0):
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([16, 70, 110]), np.array([48, 255, 255]))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 7), np.uint8))
        mask = cv2.dilate(mask, np.ones((3, 5), np.uint8), iterations=1)
        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        for i in range(1, n):
            x, y, ww, hh, area = stats[i]
            if area < 70 or area > 2500:
                continue
            if ww < 8 or hh < 10 or ww > 90 or hh > 90:
                continue
            fill = float(area) / float(max(ww * hh, 1))
            if fill < 0.08 or fill > 1.0:
                continue
            abs_x = int(x) + ox
            if full_w and abs_x < int(full_w * 0.86):
                continue
            cx = float(cents[i][0]) + ox
            cy = float(cents[i][1]) + oy
            right_bias = (float(cx) / float(max(full_w, 1))) * 220.0 if full_w else 0.0
            score = float(area) + float(hh * 12) + float(ww * 2) + right_bias
            candidates.append({"x": int(cx), "y": int(cy), "area": int(area), "score": score, "mode": "color"})
        self._message_notify_color_candidates = len(candidates)
        if not candidates:
            return None
        return max(candidates, key=lambda c: c.get("score", 0))

    def _detect_message_window(self, img):
        if img is None or img.size == 0:
            return False
        h, w = img.shape[:2]
        if h < 300 or w < 400:
            return False
        x1, y1, x2, y2 = int(w * 0.04), int(h * 0.10), int(w * 0.26), int(h * 0.34)
        roi = img[y1:y2, x1:x2]
        ix1, iy1, ix2, iy2 = int(w * 0.045), int(h * 0.255), int(w * 0.235), int(h * 0.31)
        input_roi = img[iy1:iy2, ix1:ix2]
        if roi.size == 0 or input_roi.size == 0:
            return False
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        input_gray = cv2.cvtColor(input_roi, cv2.COLOR_BGR2GRAY)
        dark_ratio = float(np.mean(gray < 65))
        input_dark = float(np.mean(input_gray < 55))
        if dark_ratio > 0.55 and input_dark > 0.45:
            return True
        return self._detect_message_input_focus_point(img) is not None

    def _detect_message_send_button(self, img):
        if img is None or img.size == 0:
            return None
        h, w = img.shape[:2]
        if h < 180 or w < 300:
            return None
        search_w = int(w * (0.92 if w < 800 else 0.68))
        search_h = int(h * (0.88 if h < 650 else 0.50))
        roi = img[:max(1, search_h), :max(1, search_w)]
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        red1 = cv2.inRange(hsv, np.array([0, 80, 70]), np.array([18, 255, 255]))
        red2 = cv2.inRange(hsv, np.array([165, 80, 70]), np.array([180, 255, 255]))
        mask = cv2.bitwise_or(red1, red2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n, _labels, stats, _cents = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        min_x = int(w * (0.20 if w < 800 else 0.24))
        max_x = int(w * (0.90 if w < 800 else 0.60))
        min_y = int(h * 0.18)
        max_y = int(h * (0.86 if h < 650 else 0.42))
        for i in range(1, n):
            x, y, ww, hh, area = stats[i]
            if ww < 36 or ww > 95 or hh < 22 or hh > 58:
                continue
            if x < min_x or x > max_x or y < min_y or y > max_y:
                continue
            fill = float(area) / float(max(ww * hh, 1))
            if fill < 0.25 or fill > 0.92:
                continue
            score = float(area) + float(ww * 6) + float(hh * 4)
            candidates.append((score, int(x), int(y), int(ww), int(hh)))
        if not candidates:
            return None
        _score, x, y, ww, hh = max(candidates, key=lambda item: item[0])
        return x, y, ww, hh

    def _detect_message_input_focus_point(self, img):
        if img is None or img.size == 0:
            return None
        h, w = img.shape[:2]
        button = self._detect_message_send_button(img)
        if button:
            x, y, ww, hh = button
            click_x = int(max(8, x - (w * 0.29)))
            click_y = int(y + (hh * 0.50))
            return click_x, click_y, "button"

        search_w = int(w * (0.92 if w < 800 else 0.68))
        search_h = int(h * (0.88 if h < 650 else 0.50))
        roi = img[:max(1, search_h), :max(1, search_w)]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        dark = cv2.inRange(gray, 0, 85)
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((7, 23), np.uint8))
        n, _labels, stats, _cents = cv2.connectedComponentsWithStats(dark, 8)
        candidates = []
        for i in range(1, n):
            x, y, ww, hh, area = stats[i]
            if ww < max(90, int(w * 0.20)) or ww > int(w * 0.68):
                continue
            if hh < max(18, int(h * 0.035)) or hh > int(h * 0.16):
                continue
            if x > int(w * 0.28):
                continue
            if y < int(h * 0.18) or y > int(h * (0.86 if h < 650 else 0.46)):
                continue
            fill = float(area) / float(max(ww * hh, 1))
            if fill < 0.25:
                continue
            candidates.append((int(y), int(area), int(x), int(ww), int(hh)))
        if not candidates:
            return None
        y, _area, x, ww, hh = max(candidates, key=lambda item: (item[0], item[1]))
        click_x = int(x + min(max(22, ww * 0.10), ww * 0.35))
        click_y = int(y + (hh * 0.50))
        return click_x, click_y, "input"

    def _message_chat_roi(self, img):
        if img is None or img.size == 0:
            return None, (0, 0)
        h, w = img.shape[:2]
        if h < 300 or w < 400:
            return None, (0, 0)
        x1, y1 = int(w * 0.04), int(h * 0.17)
        x2, y2 = int(w * 0.90), int(h * 0.79)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return None, (0, 0)
        roi = img[y1:y2, x1:x2]
        return roi, (x1, y1)

    def _message_yellow_line_bands(self, yellow):
        if yellow is None or yellow.size == 0:
            return []
        expanded = cv2.dilate(yellow, np.ones((2, 5), np.uint8), iterations=1)
        row_counts = np.count_nonzero(expanded, axis=1)
        rows = np.where(row_counts >= 3)[0]
        if len(rows) == 0:
            return []
        bands = []
        start = prev = int(rows[0])
        for raw_y in rows[1:]:
            y = int(raw_y)
            if y - prev <= 3:
                prev = y
                continue
            if prev - start >= 4:
                bands.append((start, prev))
            start = prev = y
        if prev - start >= 4:
            bands.append((start, prev))
        return bands

    def _message_line_signature(self, text, y_center):
        clean = self._clean_message_text(text).lower()
        times = re.findall(r"\[(\d{1,2}:\d{2})\]", clean)
        clean = re.sub(r"\[\d{1,2}:\d{2}\]", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        return {
            "text": clean,
            "time": times[-1] if times else "",
            "y": int(round(float(y_center) / 14.0) * 14),
        }

    def _message_signature_seen(self, pk, sig):
        if not sig or not sig.get("text"):
            return True
        seen = self._message_handled_signatures.setdefault(pk, deque(maxlen=24))
        sig_text = sig.get("text", "")
        sig_time = sig.get("time", "")
        for old in seen:
            old_text = old.get("text", "") if isinstance(old, dict) else str(old)
            old_time = old.get("time", "") if isinstance(old, dict) else ""
            old_y = int(old.get("y", 0) or 0) if isinstance(old, dict) else 0
            sim = self._message_text_similarity(sig_text, old_text)
            if sig_time and old_time and sig_time != old_time:
                continue
            if sim >= 0.96:
                return True
            if abs(int(sig.get("y", 0)) - old_y) <= 18 and sim >= 0.90:
                return True
        return False

    def _message_content_text(self, text):
        clean = self._clean_message_text(text)
        clean = re.sub(r"\[\d{1,2}:\d{2}\]", " ", clean)
        clean = re.sub(r"^\s*\[[^\]]+\]\s*", " ", clean)
        clean = re.sub(r"^\s*[A-Za-z0-9_ğüşöçıİĞÜŞÖÇ\[\]\-]+(?:\s*\(Lv\.?\s*\d+\))?\s*[:;]\s*", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" :;.-")
        return clean

    def _is_system_message_line(self, text):
        low = self._clean_message_text(text).lower()
        normalized = _normalize_outgoing_text(low)
        ascii_norm = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode("ascii")
        system_phrases = (
            "bağlı değil", "bagli degil", "baqli deyil", "bağli degil",
            "offline", "not connected", "disconnected", "çevrimdışı", "cevrimdisi",
            "connected değil", "bagli deil",
        )
        if any(p in normalized for p in system_phrases) or any(p in ascii_norm for p in ("bagli degil", "bagli deil", "cevrimdisi")):
            return True
        return bool(re.search(r"\bba[ğgq]l[ıi]\b.{0,12}\bde[ğgq]il\b", normalized) or re.search(r"\bbagli\b.{0,12}\bdegil\b", ascii_norm))

    def _is_valid_incoming_message_line(self, text):
        clean = self._clean_message_text(text)
        if not clean:
            return False, "bos"
        if self._is_system_message_line(clean):
            return False, "sistem satiri"
        content = self._message_content_text(clean)
        if not content:
            return False, "icerik yok"
        low = content.lower()
        if len(low) < 2 and "?" not in low:
            return False, "cok kisa"
        if not re.search(r"[a-zA-Z0-9ğüşöçıİĞÜŞÖÇ]", low) and "?" not in low:
            return False, "anlamsiz"
        if re.fullmatch(r"\?+", low.strip()):
            return True, ""
        if re.fullmatch(r"[\[\]\(\)\-_:;.,!?\s]+", low):
            return False, "anlamsiz"
        return True, ""

    def _read_yellow_message_lines(self, ci, pk, img, include_seen=False):
        cw = self._message_ocr_reader(ci)
        if not cw:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: OCR hazir degil")
            return []
        roi, _ = self._message_chat_roi(img)
        if roi is None or roi.size == 0:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: ROI yok")
            return []
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        yellow = cv2.inRange(hsv, np.array([12, 55, 95]), np.array([45, 255, 255]))
        yellow = cv2.morphologyEx(yellow, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        if int(cv2.countNonZero(yellow)) < 18:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: sari satir yok")
            return []
        bands = self._message_yellow_line_bands(yellow)
        if not bands:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: sari band yok")
            return []
        candidates = []
        pad_x, pad_y = 6, 4
        for y1, y2 in sorted(bands, key=lambda b: b[1], reverse=True):
            band_mask = yellow[max(0, y1 - pad_y):min(yellow.shape[0], y2 + pad_y + 1), :]
            ys, xs = np.where(band_mask > 0)
            if len(xs) < 18:
                continue
            x1 = max(0, int(xs.min()) - pad_x)
            x2 = min(yellow.shape[1], int(xs.max()) + pad_x)
            cy_abs = (float(y1) + float(y2)) / 2.0
            crop_mask = yellow[max(0, y1 - pad_y):min(yellow.shape[0], y2 + pad_y + 1), x1:x2]
            if crop_mask.size == 0:
                continue
            crop = np.zeros_like(crop_mask)
            crop[crop_mask > 0] = 255
            large = cv2.resize(crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
            try:
                with cw._lock:
                    reader = cw._reader
                    if not reader:
                        return []
                    results = reader.readtext(large, detail=1, paragraph=False)
            except Exception:
                continue
            pieces = []
            total_conf = 0.0
            for item in results or []:
                try:
                    text, conf = item[1], float(item[2])
                except Exception:
                    continue
                clean = self._clean_message_text(text)
                if not clean or conf < MESSAGE_OCR_MIN_CONF:
                    continue
                pieces.append(clean)
                total_conf += conf
            text = self._clean_message_text(" ".join(pieces))
            if not text:
                continue
            valid, reason = self._is_valid_incoming_message_line(text)
            if not valid:
                log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: {reason} {text}")
                continue
            sig = self._message_line_signature(text, cy_abs)
            if not include_seen and self._message_signature_seen(pk, sig):
                log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] atlandi: tekrar satir {text}")
                continue
            candidates.append({"text": text, "sig": sig, "y": cy_abs, "conf": total_conf / max(len(pieces), 1)})
        return candidates

    def _prime_message_yellow_baseline(self, ci, pk, img):
        lines = self._read_yellow_message_lines(ci, pk, img, include_seen=True)
        if not lines:
            return False
        seen = self._message_handled_signatures.setdefault(pk, deque(maxlen=24))
        for line in lines:
            sig = line.get("sig")
            if sig and not self._message_signature_seen(pk, sig):
                seen.append(sig)
        log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] baseline sari satir: {len(lines)}")
        return True

    def _mark_visible_yellow_messages_handled(self, ci, pk, img):
        lines = self._read_yellow_message_lines(ci, pk, img, include_seen=True)
        if not lines:
            return
        seen = self._message_handled_signatures.setdefault(pk, deque(maxlen=24))
        added = 0
        for line in lines:
            sig = line.get("sig")
            if sig and not self._message_signature_seen(pk, sig):
                seen.append(sig)
                added += 1
        if added:
            log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] gorunen sari satir islendi: {added}")

    def _message_ocr_reader(self, ci):
        cw = self.captcha_w.get(ci) or self._ensure_captcha_watcher(ci)
        if not cw or not getattr(cw, "hazir", False):
            return None
        return cw

    def _capture_window_image(self, hwnd):
        if not hwnd:
            return None
        try:
            r = win32gui.GetWindowRect(hwnd)
            if r[0] < -32000 or r[2] <= r[0] or r[3] <= r[1]:
                return None
            with mss.mss() as sct:
                shot = np.array(sct.grab({
                    "left": int(r[0]),
                    "top": int(r[1]),
                    "width": int(r[2] - r[0]),
                    "height": int(r[3] - r[1])
                }), dtype=np.uint8)
            return cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
        except Exception:
            return None

    def _clean_message_text(self, text):
        text = _normalize_outgoing_text(str(text or ""))
        text = text.replace("\n", " ").replace("\r", " ")
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _message_text_similarity(self, a, b):
        aa = self._clean_message_text(a).lower()
        bb = self._clean_message_text(b).lower()
        if not aa or not bb:
            return 0.0
        return difflib.SequenceMatcher(None, aa, bb).ratio()

    def _extract_incoming_message_text(self, ci, pk, img):
        candidates = self._read_yellow_message_lines(ci, pk, img, include_seen=False)
        if not candidates:
            return None
        selected = sorted(candidates, key=lambda item: item["y"], reverse=True)[0]
        text = selected["text"]
        self._message_pending_signature[pk] = selected["sig"]
        self._message_last_ocr[pk] = {"text": text, "ts": time.time(), "sig": selected["sig"]}
        log_event(self.st, "debug", f"Client {ci} [MESAJ OCR] yeni sari satir: {text}")
        return text

    def _message_language(self, text):
        low = self._clean_message_text(text).lower()
        tr_chars = set("çğıöşü")
        tr_words = ("selam", "sa", "teşekkür", "tesekkur", "yardım", "yardim", "mı", "mi", "nasıl", "nasil", "kanka", "abi")
        en_words = ("hello", "hi", "thanks", "thank", "help", "how", "you", "what", "ok", "yes", "no")
        tr_score = sum(1 for ch in low if ch in tr_chars) + sum(1 for w in tr_words if w in low)
        en_score = sum(1 for w in en_words if re.search(rf"\b{re.escape(w)}\b", low))
        if en_score > tr_score:
            return "en"
        if tr_score > 0:
            return "tr"
        return "unknown"

    def _choose_contextual_message_reply(self, pk, incoming_text=None):
        text = self._clean_message_text(incoming_text)
        if not text:
            return self._choose_message_reply(pk)
        low = text.lower()
        lang = self._message_language(text)
        if any(w in low for w in ("bot", "auto", "macro", "otomatik")):
            replies = ["no, I am here", "I am here", "no bot"] if lang == "en" else ["buradayım", "hayır buradayım", "burdayım"]
        elif any(w in low for w in ("thank", "thanks", "ty", "teşekkür", "tesekkur", "sağol", "sagol")):
            replies = ["you're welcome", "no problem", "ok, no problem"] if lang == "en" else ["rica ederim", "sorun değil", "tamam sorun yok"]
        elif any(re.search(rf"\b{re.escape(w)}\b", low) for w in ("hello", "hi", "hey", "selam", "merhaba", "sa")):
            replies = ["hello, how can I help", "hi, I am here", "hello"] if lang == "en" else ["selam, nasıl yardımcı olayım", "selam buradayım", "merhaba"]
        elif any(w in low for w in ("help", "how can", "yardım", "yardim", "soru")) or "?" in low:
            replies = ["how can I help", "what do you need", "tell me"] if lang == "en" else ["nasıl yardımcı olayım", "ne lazım", "söyle"]
        elif lang == "en":
            replies = ["ok", "one sec", "I am here", "yes"]
        elif lang == "tr":
            replies = ["tamam", "buradayım", "dinliyorum", "evet"]
        else:
            replies = ["ok", "one sec", "I'm here", "yes"]
        return self._pick_message_reply(pk, replies)

    def _pick_message_reply(self, pk, replies):
        replies = [str(r).strip() for r in (replies or []) if str(r).strip()]
        if not replies:
            replies = ["ok"]
        last_local = self._message_last_reply.get(pk)
        global_recent = set(self._message_global_reply_buffer)
        choices = [r for r in replies if r != last_local and r not in global_recent]
        if not choices:
            choices = [r for r in replies if r != last_local]
        if not choices:
            choices = replies
        reply = random.choice(choices)
        self._message_last_reply[pk] = reply
        self._message_global_reply_buffer.append(reply)
        return reply

    def _choose_message_reply(self, pk):
        replies = [r for r in MESSAGE_REPLY_TEXTS if str(r).strip()]
        if not replies:
            return "selam"
        return self._pick_message_reply(pk, replies)

    def _focus_message_input(self, img, ox, oy, hwnd):
        if img is None or img.size == 0:
            return False
        h, w = img.shape[:2]
        if hwnd:
            pencere_odakla(hwnd)
        focus = self._detect_message_input_focus_point(img)
        if focus:
            fx, fy, mode = focus
            input_x = ox + int(fx)
            input_y = oy + int(fy)
            log_event(self.st, "debug", f"[MESAJ] input odak noktasi: {mode} ({int(fx)},{int(fy)})")
        else:
            input_x = ox + int(w * 0.145)
            input_y = oy + int(h * 0.323)
            log_event(self.st, "debug", "[MESAJ] input odak fallback")
        sol_tik_hw(input_x, input_y, hwnd)
        time.sleep(0.18)
        return True

    def _send_message_reply(self, img, ox, oy, hwnd, notification=None, reply_text=None):
        h, w = img.shape[:2]
        if hwnd:
            pencere_odakla(hwnd)
        if notification:
            sol_tik_hw(ox + notification["x"], oy + notification["y"], hwnd)
            time.sleep(0.45)
        else:
            self._focus_message_input(img, ox, oy, hwnd)
        return _paste_text_and_enter(reply_text or self._choose_message_reply(hwnd or ""), hwnd)

    def _set_message_farm_pause(self, ci, pk, seconds=MESSAGE_FARM_PAUSE_SECONDS):
        if float(seconds or 0) <= 0:
            with self.st.lk:
                self.st.message_farm_pause_until.pop(pk, None)
            return
        until = time.time() + float(seconds)
        with self.st.lk:
            self.st.message_farm_pause_until[pk] = until
        log_event(self.st, "warn", f"Client {ci} [MESAJ] farm {int(seconds)} sn duraklatildi")

    def _message_farm_pause_remaining(self, pk, now=None):
        now = now or time.time()
        with self.st.lk:
            until = float(self.st.message_farm_pause_until.get(pk, 0) or 0)
            if until <= now:
                if pk in self.st.message_farm_pause_until:
                    self.st.message_farm_pause_until.pop(pk, None)
                return 0.0
            return until - now

    def _handle_message_request(self, ci, pk, img, ox, oy, hwnd, cc):
        mk = self._message_key(ci, pk)
        if not self._message_captcha_enabled(cc):
            return False
        if time.time() - self._started_at < 1.0:
            self._message_seen_since.pop(mk, None)
            return False
        window_open = self._detect_message_window(img)
        notification = None if window_open else self._detect_message_notification(img)
        if not window_open:
            self._message_window_answered[mk] = False
            if not notification:
                self._message_open_allowed[mk] = False
        if notification:
            first_seen = self._message_seen_since.get(mk)
            now_seen = time.time()
            if first_seen is None:
                self._message_seen_since[mk] = now_seen
                return True
            if now_seen - first_seen < 0.75:
                return True
        else:
            self._message_seen_since.pop(mk, None)
        answered_open = bool(window_open and self._message_window_answered.get(mk, False))
        if not notification and (not window_open or (not self._message_open_allowed.get(mk, False) and not answered_open)):
            return False
        pre_incoming_text = None
        if answered_open and not notification:
            baseline_since = float(self._message_baseline_pending.get(mk, 0) or 0)
            if baseline_since:
                if self._prime_message_yellow_baseline(ci, mk, img):
                    self._message_baseline_pending.pop(mk, None)
                    return False
                if time.time() - baseline_since < 2.0:
                    return False
                self._message_baseline_pending.pop(mk, None)
                return False
            pre_incoming_text = self._extract_incoming_message_text(ci, mk, img)
            if not pre_incoming_text:
                return False
        now = time.time()
        if now - self._message_last_action.get(mk, 0) < MESSAGE_ACTION_COOLDOWN:
            return True

        reason = "bildirim" if notification else "pencere acik"
        self._set_global_message(pk, ci, reason)
        ok = False
        try:
            if notification:
                incoming_text = None
                reply_text = self._choose_message_reply(mk)
                ok = self._send_message_reply(img, ox, oy, hwnd, notification, reply_text)
            else:
                incoming_text = pre_incoming_text or self._extract_incoming_message_text(ci, mk, img)
                reply_text = self._choose_contextual_message_reply(mk, incoming_text)
                ok = self._send_message_reply(img, ox, oy, hwnd, None, reply_text)
            self._message_last_action[mk] = time.time()
            if notification:
                self._message_open_allowed[mk] = True
            if ok:
                if incoming_text:
                    self._message_last_handled_incoming[mk] = incoming_text
                    pending_sig = self._message_pending_signature.pop(mk, None)
                    if pending_sig:
                        self._message_handled_signatures.setdefault(mk, deque(maxlen=24)).append(pending_sig)
                    self._mark_visible_yellow_messages_handled(ci, mk, img)
                self._message_window_answered[mk] = True
                self._message_seen_since.pop(mk, None)
                self._message_open_allowed[mk] = True
                if notification:
                    fresh_img = self._capture_window_image(hwnd)
                    if fresh_img is not None and fresh_img.size:
                        self._mark_visible_yellow_messages_handled(ci, mk, fresh_img)
                    else:
                        self._message_baseline_pending[mk] = time.time()
                self._set_message_farm_pause(ci, pk)
                log_event(self.st, "warn", f"Client {ci} [MESAJ] yanit gonderildi")
            else:
                log_event(self.st, "warn", f"Client {ci} [MESAJ] yazi gonderilemedi")
        finally:
            time.sleep(0.25)
            self._clear_global_message("yanitlandi" if ok else "deneme bitti")
        return True

    def run(self):
        try:
            dev = preferred_backend()
            with self.st.lk: self.st.cihaz = dev
            log_event(self.st, "info", f"Vision cihazi: {dev}")
        except:
            return

        _sct = mss.mss()

        while not self._stop_event.is_set():
            loop_start = time.time()

            with self.st.lk:
                aktif = self.st.aktif

            if not aktif:
                with self.st.lk:
                    self.st.captcha_global_active = False
                    self.st.captcha_global_owner = None
                    self.st.captcha_global_since = 0.0
                    self.st.message_global_active = False
                    self.st.message_global_owner = None
                    self.st.message_global_since = 0.0
                    self.st.global_pause_active = False
                    self.st.global_pause_kind = ""
                    self.st.global_pause_owner = None
                    self.st.global_pause_reason = ""
                    self.st.global_pause_since = 0.0
                    self.st.message_farm_pause_until.clear()
                    for pk in list(self.st.captcha_block.keys()):
                        self.st.captcha_block[pk] = False
                        self.st.captcha_state[pk] = False
                if self._stop_event.wait(0.1):
                    break
                continue

            self._clear_orphaned_input_locks()
            self._watch_global_pause()

            guncel = {}
            with self.st.lk:
                b64_frames = dict(self.st.frame_b64)
            active_keys = set()
            self._warn_duplicate_client_windows()
            runtime_client_configs = {ci: self.cfg.client(ci) for ci in CLIENT_IDS}
            blocked_client_ids = duplicate_client_ids(runtime_client_configs)

            for ci in CLIENT_IDS:
                cc = runtime_client_configs[ci]
                if not cc.get("aktif", True):
                    continue
                pk = cc.get("pencere","Yok")
                if pk == "Yok": continue
                # Eski/elle duzenlenmis ayarlarda cakisma bulunursa hicbir
                # tarafa oncelik verme; boylece yanlis client'a input gidemez.
                if ci in blocked_client_ids:
                    self._log_window_issue(
                        ci,
                        pk,
                        "duplicate",
                        f"Client {ci} atlandi: pencere baska aktif Client ile cakismali ({pk})",
                    )
                    continue
                active_keys.add(pk)
                # Bu etiket ekran yakalanmadan once okunur. Hedef tiklamasi
                # inference devam ederken olursa, eski kare yeni hedefe aitmis
                # gibi kullanilmaz.
                with self.st.lk:
                    frame_target_generation = int(self.st.target_generation.get(pk, 0) or 0)

                hwnd = hwnd_al(pk)
                mon = _sct.monitors[1]; ox,oy = 0,0
                if hwnd:
                    try: r = win32gui.GetWindowRect(hwnd)
                    except:
                        self._log_window_issue(ci, pk, "getrect", f"Client {ci} GetWindowRect basarisiz: {pk}")
                        with self.st.lk:
                            self.st.durum[pk] = "PENCERE HATA"
                        continue
                    if r[0] < -32000:
                        self._log_window_issue(ci, pk, "minimized", f"Client {ci} pencere minimize: {pk}")
                        with self.st.lk:
                            self.st.durum[pk] = "PENCERE MINIMIZE"
                        continue
                    ox,oy = r[0],r[1]
                    mon = {"top":r[1],"left":r[0],"width":r[2]-r[0],"height":r[3]-r[1]}
                else:
                    self._log_window_issue(ci, pk, "hwnd", f"Client {ci} hwnd bulunamadi: {pk}")
                    with self.st.lk:
                        self.st.durum[pk] = "PENCERE YOK"

                ecx, ecy = mon["width"]//2, mon["height"]//2
                hp_region = cc.get("hp_region", [0.02, 0.07, 0.30, 0.70])
                y1h = max(0, min(mon["height"], int(hp_region[0] * mon["height"])))
                y2h = max(0, min(mon["height"], int(hp_region[1] * mon["height"])))
                x1h = max(0, min(mon["width"], int(hp_region[2] * mon["width"])))
                x2h = max(0, min(mon["width"], int(hp_region[3] * mon["width"])))
                panel_width = max(0, x2h - x1h)
                panel_height = max(0, y2h - y1h)

                auto_bar_region = cc.get("hp_auto_bar_region")
                hp_panel_auto_ready = bool(
                    cc.get("hp_panel_auto")
                    and isinstance(auto_bar_region, (list, tuple))
                    and len(auto_bar_region) == 4
                    and panel_width >= 40
                    and panel_height >= 12
                )
                auto_bar_local = None
                if hp_panel_auto_ready:
                    aby1 = max(0, min(panel_height, int(round(float(auto_bar_region[0]) * panel_height))))
                    aby2 = max(0, min(panel_height, int(round(float(auto_bar_region[1]) * panel_height))))
                    abx1 = max(0, min(panel_width, int(round(float(auto_bar_region[2]) * panel_width))))
                    abx2 = max(0, min(panel_width, int(round(float(auto_bar_region[3]) * panel_width))))
                    if aby2 > aby1 and abx2 > abx1:
                        auto_bar_local = (abx1, aby1, abx2 - abx1, aby2 - aby1)
                    else:
                        hp_panel_auto_ready = False

                hp_fill_region = cc.get("hp_fill_region")
                hp_fill_ready = hp_panel_auto_ready or bool(
                    cc.get("hp_fill_region_custom")
                    and isinstance(hp_fill_region, (list, tuple))
                    and len(hp_fill_region) == 4
                )
                fill_box = None
                if hp_panel_auto_ready and auto_bar_local:
                    abx, aby, abw, abh = auto_bar_local
                    fill_box = (x1h + abx, y1h + aby, x1h + abx + abw, y1h + aby + abh)
                elif hp_fill_ready:
                    fy1 = max(0, min(mon["height"], int(hp_fill_region[0] * mon["height"])))
                    fy2 = max(0, min(mon["height"], int(hp_fill_region[1] * mon["height"])))
                    fx1 = max(0, min(mon["width"], int(hp_fill_region[2] * mon["width"])))
                    fx2 = max(0, min(mon["width"], int(hp_fill_region[3] * mon["width"])))
                    if fy2 > fy1 and fx2 > fx1:
                        fill_box = (fx1, fy1, fx2, fy2)
                    else:
                        hp_fill_ready = False
                try: img = cv2.cvtColor(np.array(_sct.grab(mon),dtype=np.uint8), cv2.COLOR_BGRA2BGR)
                except:
                    self._log_window_issue(ci, pk, "capture", f"Client {ci} ekran capture basarisiz")
                    with self.st.lk:
                        self.st.durum[pk] = "CAPTURE HATA"
                    continue
                frame_capture_ts = time.time()
                death = detect_death_menu(img)
                death.update(ts=frame_capture_ts, hwnd=hwnd, own_hp=own_hp_visible(img),
                             foreground=bool(hwnd and win32gui.GetForegroundWindow() == hwnd))
                with self.st.lk:
                    if not hasattr(self.st, "life_data"):
                        self.st.life_data = {}
                    self.st.life_data[pk] = death
                death_visible = bool(death.get("visible"))
                if death_visible:
                    guncel[pk] = self._publish_client_vision(pk, {"merkezler": [], "hp_var": False,
                        "hwnd": hwnd, "client_cfg": cc, "client_idx": ci,
                        "ts": frame_capture_ts, "target_generation": frame_target_generation})

                # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

                # â”€â”€ CAPTCHA â”€â”€
                # Global captcha baska client'ta aktif olsa bile bu client'in
                # frame'i okunur. Fiziksel mesaj cevabi yine asagidaki global
                # captcha kapisindan gecmeden yapilmaz.
                captcha_waiting_for_ocr = False
                cw = self.captcha_w.get(ci)
                enabled_tips = {
                    "tip1": bool(cc.get("captcha_tip1", False)),
                    "tip2": bool(cc.get("captcha_tip2", False)),
                    "tip3": bool(cc.get("captcha_tip3", False)),
                    "tip4": bool(cc.get("captcha_tip4", False)),
                    "rumeli2": bool(cc.get("captcha_rumeli2", False)),
                }
                base_captcha_enabled = bool(cc.get("captcha", True))
                captcha_enabled = base_captcha_enabled or any(enabled_tips.values())
                if not base_captcha_enabled and any(enabled_tips.values()):
                    warn_key = (ci, "captcha_tip_without_master")
                    last_warn = self._captcha_last_log.get(warn_key, 0)
                    if time.time() - last_warn > 10:
                        active_tips = ",".join(k for k, v in enabled_tips.items() if v)
                        log_event(self.st, "warn", f"Client {ci} {active_tips} acik ama ana captcha kapaliydi, captcha solver aktif edildi")
                        self._captcha_last_log[warn_key] = time.time()
                if not captcha_enabled:
                    with self.st.lk:
                        self.st.captcha_block[pk] = False
                        self.st.captcha_state[pk] = False
                        is_global_owner = self.st.captcha_global_owner == pk
                    if is_global_owner:
                        self._clear_global_captcha("owner captcha kapali")
                elif captcha_enabled:
                    cw = cw or self._ensure_captcha_watcher(ci)
                    if not cw:
                        continue
                    try:
                        cw.set_enabled_tips(enabled_tips)
                        cw.set_rumeli2_regions(
                            cc.get("rumeli2_question_region"),
                            cc.get("rumeli2_option_regions", []),
                        )
                    except Exception:
                        pass
                    status = getattr(cw, "last_status", "")
                    if not cw.hazir:
                        with self.st.lk:
                            self.st.durum[pk] = "CAPTCHA OCR"
                        last = self._captcha_last_log.get((ci, "not_ready"), 0)
                        started_t = float(self._captcha_watcher_started_t.get(ci, 0.0) or 0.0)
                        init_age = time.time() - started_t if started_t else CAPTCHA_OCR_INIT_GRACE_SECONDS
                        if init_age >= CAPTCHA_OCR_INIT_GRACE_SECONDS and time.time() - last > 10:
                            detail = getattr(cw, "last_detail", "") or "ocr hazir degil"
                            log_event(self.st, "warn", f"Client {ci} captcha OCR hazir degil: {detail}")
                            self._captcha_last_log[(ci, "not_ready")] = time.time()
                        captcha_waiting_for_ocr = True
                    else:
                        captcha_bulundu = cw.kontrol_et(img, ox, oy, hwnd)
                        status = getattr(cw, "last_status", "")
                        detail = getattr(cw, "last_detail", "")
                        config_only_status = status in (
                            "rumeli2_kalibrasyon_yok",
                            "rumeli2_referans_yok",
                            "template_yok",
                        )
                        # Her loop'ta status log'la (throttled)
                        if status not in (
                            "dialog_yok",
                            "rumeli2_kalibrasyon_yok",
                            "rumeli2_referans_yok",
                            "template_yok",
                        ):
                            log_key = (ci, "status_check")
                            last_log = self._captcha_last_log.get(log_key, 0)
                            if time.time() - last_log > 5:
                                log_event(self.st, "info", f"Client {ci} captcha status: {status}{(' - ' + detail) if detail else ''}")
                                self._captcha_last_log[log_key] = time.time()
                        elif config_only_status:
                            log_key = (ci, "captcha_config")
                            last_log = self._captcha_last_log.get(log_key, 0)
                            if time.time() - last_log > 30:
                                log_event(
                                    self.st,
                                    "warn",
                                    f"Client {ci} CAPTCHA kullanima hazir degil: {status}"
                                    f"{(' - ' + detail) if detail else ''}; "
                                    "farm ve canli goruntu engellenmeden devam ediyor",
                                )
                                self._captcha_last_log[log_key] = time.time()
                        if status in ("hedef_yok", "eslesme_yok", "ocr_yok", "ocr_hata", "tip_yok", "grid_yok", "grid_az", "farkli_yok", "rumeli2_belirsiz"):
                            key = (ci, status, detail)
                            last = self._captcha_last_log.get(key, 0)
                            if time.time() - last > 3:
                                log_event(self.st, "warn", f"Client {ci} captcha cozulmedi: {status}{(' - ' + detail) if detail else ''}")
                                self._captcha_last_log[key] = time.time()
                        if captcha_bulundu:
                            log_event(self.st, "warn", f"Client {ci} captcha bulundu â€” tiklandi")
                            with self.st.lk:
                                self.st.captcha_cd[pk] = time.time() + 1.5
                            self._set_global_captcha(pk, ci, f"cozuldu:{status}")
                            if cc.get("debug_on", True):
                                now = time.time()
                                if now - self._last_debug_encode.get(pk, 0) >= self._debug_encode_interval:
                                    try:
                                        small = cv2.resize(img, (640,360)) if img.shape[1] > 700 else img
                                        _,buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 30])
                                        b64_frames[pk] = base64.b64encode(buf.tobytes()).decode()
                                        self._publish_debug_frame(pk, b64_frames[pk])
                                        self._last_debug_encode[pk] = now
                                    except:
                                        pass
                            continue
                    if captcha_waiting_for_ocr:
                        continue
                    if not captcha_status_blocks_input(status):
                        with self.st.lk:
                            cooldown_finished = time.time() >= self.st.captcha_cd.get(pk, 0)
                            if config_only_status or cooldown_finished:
                                self.st.captcha_block[pk] = False
                                self.st.captcha_state[pk] = False
                                is_global_owner = self.st.captcha_global_owner == pk
                            else:
                                is_global_owner = False
                        if is_global_owner:
                            self._clear_global_captcha(f"owner non-blocking status: {status or 'bos'}")
                    else:
                        self._set_global_captcha(pk, ci, status or "captcha kontrol")
                        continue

                # Olum menusu ile CAPTCHA ayni karede gorunebilir. CAPTCHA'nin
                # zaman asimina ugramamasi icin once solver'a bu kareyi ver;
                # CAPTCHA yoksa eski davranisla model ve mesaj akisini atla.
                if death_visible:
                    continue

                # Dunyadaki sabit detaylari seyrek optik akisla izle. Yerel mob ve
                # beceri animasyonlari yerine genis alana yayilan tutarli kayma aranir.
                try:
                    scene_motion = self._measure_scene_motion(pk, img, time.time())
                except Exception:
                    scene_motion = {
                        "ready": False, "moving": False, "score": 0.0,
                        "confidence": 0.0, "points": 0,
                    }

                if self._handle_message_request(ci, pk, img, ox, oy, hwnd, cc):
                    continue

                farm_pause_remaining = self._message_farm_pause_remaining(pk)
                if farm_pause_remaining > 0:
                    with self.st.lk:
                        self.st.captcha_block[pk] = False
                        self.st.captcha_state[pk] = False
                        self.st.durum[pk] = "FARM BEKLEME"
                    continue

                # Model inference parametreleri
                model_path = cc.get("model_yolu") or self.cfg.g("model_yolu")
                if not model_path or not os.path.exists(model_path):
                    continue
                model = self.model_cache.get(model_path)
                if model is None:
                    try:
                        model = create_detection_model(
                            model_path,
                            log_cb=lambda level, message: log_event(self.st, level, message),
                        )
                        dummy_size = 640
                        model(np.zeros((dummy_size,dummy_size,3),dtype=np.uint8), verbose=False)
                        self.model_cache[model_path] = model
                        with self.st.lk:
                            self.st.cihaz = model.backend_name
                    except:
                        continue

                conf = FIXED_CONF_ESIK
                imgsz = 640
                quantize = 16 if getattr(model, "backend_name", "cpu") == "cuda" else None
                
                res = model(img, stream=True, verbose=False, conf=conf, quantize=quantize, imgsz=imgsz, iou=0.45)
                mrk, kut, hedefler = [], [], []
                stable_mrk = []
                tum_ham_pos = []  # Bu karedeki TÃœM ham tespitler (ardÄ±ÅŸÄ±k doÄŸrulama iÃ§in saklanÄ±r)
                frame_ts = frame_capture_ts
                prev_target = self._prev_target_centers.get(pk) or {}
                prev_target_ts = float(prev_target.get("ts", 0.0) or 0.0)
                prev_target_centers = prev_target.get("centers") or []
                stable_frame_gap = bool(prev_target_centers) and (frame_ts - prev_target_ts) <= TARGET_STABLE_MAX_FRAME_GAP

                for rr in res:
                    if not rr.boxes: continue
                    bxs = rr.boxes.xyxy.cpu().numpy().astype(int)
                    cfs = rr.boxes.conf.cpu().numpy()
                    for i,(b1,b2,b3,b4) in enumerate(bxs):
                        w_box = b3 - b1
                        h_box = b4 - b2
                        a = w_box * h_box
                        cx, cy = (b1+b3)//2, (b2+b4)//2

                        # 1) Alan filtresi â€” devasa veya Ã§ok minik kutularÄ± at
                        if not (200 < a < 25000):
                            continue

                        # 2) Aspect ratio filtresi â€” Ã§ok ince (UI Ã§ubuklarÄ±) veya aÅŸÄ±rÄ± basÄ±k at
                        ar = w_box / h_box if h_box > 0 else 999
                        if not (0.3 < ar < 2.5):
                            continue

                        stable_dist = min((np.hypot(cx - px, cy - py) for px, py in prev_target_centers), default=999999.0)
                        stable_click = stable_frame_gap and stable_dist <= TARGET_STABLE_RADIUS
                        click_x = int((b1 + b3) / 2)
                        click_y = int(b2 + (h_box * 0.56))

                        # Tum tespitleri debug icin goster; tiklama adaylari asagida iki karede dogrulanir.
                        tum_ham_pos.append((cx, cy))
                        mrk.append((cx, cy))
                        kut.append((b1,b2,b3,b4,float(cfs[i])))
                        if stable_click:
                            stable_mrk.append((cx, cy))
                            hedefler.append({
                                "x": click_x, "y": click_y,
                                "cx": int(cx), "cy": int(cy),
                                "box": (int(b1), int(b2), int(b3), int(b4)),
                                "conf": float(cfs[i]),
                                "stable_click": True,
                                "stable_distance": float(stable_dist),
                            })

                # Sonraki kare iÃ§in ham tespitleri sakla
                # Miss durumunda bellekteki pozisyonu da ekle â†’ mob yeniden gÃ¶rÃ¼nÃ¼nce anÄ±nda doÄŸrulanÄ±r
                with self.st.lk:
                    tm_now = self.st.target_memory.get(pk, {})
                    mem_pos = tm_now.get("last_confirmed_pos")
                if not tum_ham_pos and mem_pos:
                    self._prev_det[pk] = [mem_pos]
                else:
                    self._prev_det[pk] = tum_ham_pos
                self._prev_target_centers[pk] = {"ts": frame_ts, "centers": list(tum_ham_pos)}

                # Tiklama adaylari yalnizca iki karede sabit kalan hedef merkezlerinden gelir.
                temiz = list(stable_mrk)

                # Model memory gÃ¼ncelle (temporal smoothing - takip sistemi)
                MISS_TOLERANS = 8  # ~0.27s @ 30fps â€” kaÃ§ kare kaÃ§Ä±rÄ±lÄ±rsa takip silinsin
                with self.st.lk:
                    if pk not in self.st.target_memory:
                        self.st.target_memory[pk] = {
                            "positions": [],
                            "consecutive_found": 0,
                            "confirmed": False,
                            "last_confirmed_pos": None,
                            "misses": 0
                        }

                    tm = self.st.target_memory[pk]
                    if temiz:
                        # Yeni konumu ekle (en yakÄ±n hedefi al)
                        closest = min(temiz, key=lambda p: np.hypot(p[0]-ecx, p[1]-ecy))
                        tm["positions"].append(closest)
                        if len(tm["positions"]) > 5:
                            tm["positions"].pop(0)
                        tm["consecutive_found"] += 1
                        tm["confirmed"] = True
                        tm["misses"] = 0
                        avg_x = int(sum(p[0] for p in tm["positions"]) / len(tm["positions"]))
                        avg_y = int(sum(p[1] for p in tm["positions"]) / len(tm["positions"]))
                        tm["last_confirmed_pos"] = (avg_x, avg_y)
                    else:
                        # YOLO kaÃ§Ä±rdÄ± â€” tolerans dahilinde belleÄŸi koru
                        tm["misses"] = tm.get("misses", 0) + 1
                        if tm["misses"] >= MISS_TOLERANS:
                            # Mob gerÃ§ekten gitti, takibi temizle
                            tm["positions"] = []
                            tm["consecutive_found"] = 0
                            tm["confirmed"] = False
                            tm["last_confirmed_pos"] = None
                            tm["misses"] = 0

                    # Tolerans dahilinde miss varsa bellekteki pozisyonu hedef olarak kullan
                    if not temiz and not mrk and tm.get("last_confirmed_pos") and tm["misses"] < MISS_TOLERANS:
                        temiz = [tm["last_confirmed_pos"]]

                self._sync_hp_generation(pk, frame_target_generation)

                search_margin = HP_PANEL_SEARCH_MARGIN if hp_panel_auto_ready else 3
                hsx1 = max(0, x1h - search_margin)
                hsy1 = max(0, y1h - search_margin)
                hsx2 = min(mon["width"], x2h + search_margin)
                hsy2 = min(mon["height"], y2h + search_margin)
                roi = img[hsy1:hsy2, hsx1:hsx2]
                hp_result = self._match_hp_template(roi, ci)
                structure_matched = bool(hp_result.get("structure_matched"))

                auto_bar_result = None
                credible_bar = False
                raw_visible = False
                was_confirmed = False
                presence_votes = 0
                presence_total = 0
                if hp_panel_auto_ready and auto_bar_local:
                    abx, aby, abw, abh = auto_bar_local
                    expected_bar = (
                        (x1h - hsx1) + abx,
                        (y1h - hsy1) + aby,
                        abw,
                        abh,
                    )
                    auto_bar_result = locate_hp_bar(
                        roi,
                        expected_box=expected_bar,
                        search_margin=search_margin,
                        # Rumeli2 hedef panelinin yatay yerlesimi hedef adina
                        # gore degisebiliyor. Dikey hizada kal, fakat kirmizi
                        # cubugu secilen panelin tum genisliginde ara.
                        horizontal_search_margin=panel_width,
                    )

                    presence_hist = self._hp_presence_hist.setdefault(
                        pk,
                        deque(maxlen=HP_PANEL_CONFIRM_FRAMES),
                    )
                    was_confirmed = sum(1 for value in presence_hist if value) >= HP_PANEL_CONFIRM_VOTES
                    credible_bar = is_credible_hp_bar(
                        auto_bar_result,
                        was_confirmed=was_confirmed,
                        min_initial_fill=HP_PANEL_MIN_INITIAL_FILL,
                    )
                    raw_visible = hp_panel_presence_vote(
                        credible_bar,
                        structure_matched,
                        was_confirmed=was_confirmed,
                    )
                    presence_hist.append(raw_visible)
                    presence_votes = sum(1 for value in presence_hist if value)
                    presence_total = len(presence_hist)
                    hp_var = (
                        len(presence_hist) >= HP_PANEL_CONFIRM_VOTES
                        and presence_votes >= HP_PANEL_CONFIRM_VOTES
                    )
                    hp_result["score"] = max(
                        float(hp_result.get("score", 0.0) or 0.0),
                        float(auto_bar_result.get("score", 0.0) or 0.0),
                    )
                    hp_result["matched"] = hp_var
                else:
                    self._hp_presence_hist.pop(pk, None)
                    hp_var = bool(hp_result.get("matched", False))

                self._hp_last_result = getattr(self, '_hp_last_result', {})
                self._hp_last_result[pk] = hp_result
                self._hp_score_hist = getattr(self, '_hp_score_hist', {})
                self._hp_score_hist.pop(pk, None)
                hp_px = int(hp_result["score"] * 10000)  # score -> px format (UI uyumu)

                hp_fill = None
                hp_fill_raw = None
                hp_fill_samples = 0
                hp_sample_valid = False
                hp_sample_rejected_reason = ""
                hp_previous_accepted = self._hp_accepted_floor.get(pk)
                if hp_panel_auto_ready and auto_bar_result is not None:
                    if auto_bar_result.get("bar_box"):
                        bx, by, bw, bh = auto_bar_result["bar_box"]
                        fill_box = (hsx1 + bx, hsy1 + by, hsx1 + bx + bw, hsy1 + by + bh)
                    # Dolgu yalnizca ayni karede sabit panel cercevesi de
                    # dogrulandiysa kullanilir. Cerceve kayipken gorulen kirmizi
                    # dunya/UI parcalari HP zaman serisini kirletemez.
                    candidate_fill = (
                        auto_bar_result.get("fill")
                        if credible_bar and structure_matched
                        else None
                    )
                    hist = self._hp_fill_hist.setdefault(pk, deque(maxlen=5))
                    if candidate_fill is not None:
                        if is_plausible_hp_sample(
                            hp_previous_accepted,
                            candidate_fill,
                            HP_MAX_UPWARD_JUMP,
                        ):
                            hp_fill_raw = float(candidate_fill)
                            hist.append(hp_fill_raw)
                            self._hp_accepted_floor[pk] = (
                                hp_fill_raw if hp_previous_accepted is None
                                else min(float(hp_previous_accepted), hp_fill_raw)
                            )
                            hp_sample_valid = True
                        else:
                            hp_sample_rejected_reason = "imkansiz_can_artisi"
                    if hist and hp_var:
                        hp_fill = float(np.median(np.asarray(hist, dtype=np.float32)))
                    hp_fill_samples = len(hist)
                elif hp_var and hp_fill_ready and fill_box:
                    fx1, fy1, fx2, fy2 = fill_box
                    candidate_fill = estimate_red_fill(img[fy1:fy2, fx1:fx2])
                    hist = self._hp_fill_hist.setdefault(pk, deque(maxlen=5))
                    if candidate_fill is not None and is_plausible_hp_sample(
                        hp_previous_accepted,
                        candidate_fill,
                        HP_MAX_UPWARD_JUMP,
                    ):
                        hp_fill_raw = float(candidate_fill)
                        hist.append(hp_fill_raw)
                        self._hp_accepted_floor[pk] = (
                            hp_fill_raw if hp_previous_accepted is None
                            else min(float(hp_previous_accepted), hp_fill_raw)
                        )
                        hp_sample_valid = True
                        hp_fill = float(np.median(np.asarray(hist, dtype=np.float32)))
                    elif candidate_fill is not None:
                        hp_sample_rejected_reason = "imkansiz_can_artisi"
                    hp_fill_samples = len(hist)
                else:
                    self._hp_fill_hist.pop(pk, None)

                red_box = (auto_bar_result or {}).get("red_box") or (0, 0, 0, 0)
                expected_bar_width = int(auto_bar_local[2]) if auto_bar_local else 0
                detected_bar_width = int(red_box[2]) if len(red_box) >= 3 else 0
                hp_bar_score = float((auto_bar_result or {}).get("score", 0.0) or 0.0)
                hp_anchor_score = float(hp_result.get("structure_score", 0.0) or 0.0)
                raw_text = "--" if hp_fill_raw is None else f"{float(hp_fill_raw) * 100:.1f}"
                median_text = "--" if hp_fill is None else f"{float(hp_fill) * 100:.1f}"
                signature = (
                    bool(hp_var), bool(raw_visible), round(float(hp_fill_raw or -1.0), 3),
                    bool(hp_sample_valid), hp_sample_rejected_reason,
                    presence_votes, presence_total, frame_target_generation,
                )
                diag_now = time.time()
                if hp_sample_rejected_reason:
                    last_reject = float(self._hp_reject_t.get(pk, 0) or 0)
                    if diag_now - last_reject >= HP_DIAGNOSTIC_INTERVAL_SN:
                        self._hp_reject_t[pk] = diag_now
                        previous_text = (
                            "--" if hp_previous_accepted is None
                            else f"{float(hp_previous_accepted) * 100:.1f}"
                        )
                        candidate_text = (
                            "--" if candidate_fill is None
                            else f"{float(candidate_fill) * 100:.1f}"
                        )
                        log_event(
                            self.st,
                            "warn",
                            f"[HP-C{ci}] G{frame_target_generation} imkansiz can artisi "
                            f"reddedildi: once=%{previous_text} simdi=%{candidate_text}; "
                            f"karar uretilmedi ({pk})",
                        )
                with self.st.lk:
                    action_state = self.st.durum.get(pk, "?")
                diag_active = action_state in ("DOGRULAMA", "SAVASIYOR", "LOOT") or hp_var or was_confirmed
                signature_changed = self._hp_diag_signature.get(pk) != signature
                if diag_active and (
                    signature_changed
                    or diag_now - float(self._hp_diag_t.get(pk, 0) or 0) >= HP_DIAGNOSTIC_INTERVAL_SN
                ):
                    self._hp_diag_t[pk] = diag_now
                    self._hp_diag_signature[pk] = signature
                    log_event(
                        self.st,
                        "debug",
                        f"[HP-C{ci}] G{frame_target_generation} durum={action_state} "
                        f"panel={int(hp_var)} oy={presence_votes}/{presence_total} "
                        f"ham=%{raw_text} medyan=%{median_text} ornek={hp_fill_samples} "
                        f"ornek_gecerli={int(hp_sample_valid)} "
                        f"dolgu_px={detected_bar_width}/{expected_bar_width} "
                        f"bar_skor={hp_bar_score:.2f} cerceve_skor={hp_anchor_score:.2f} ({pk})",
                    )

                client_data = {"merkezler":temiz,"live_merkezler":list(mrk),"hedefler":hedefler,"hp_var":hp_var,"hp_piksel":hp_px,
                               "hp_fill":hp_fill,"hp_fill_raw":hp_fill_raw,
                               "hp_fill_samples":hp_fill_samples,"hp_fill_ready":hp_fill_ready,
                               "hp_sample_valid":hp_sample_valid,
                               "hp_sample_rejected_reason":hp_sample_rejected_reason,
                               "hp_structure_matched":structure_matched,
                               "hp_bar_width":detected_bar_width,"hp_bar_expected_width":expected_bar_width,
                               "hp_bar_score":hp_bar_score,"hp_anchor_score":hp_anchor_score,
                               "hp_presence_votes":presence_votes,"hp_presence_total":presence_total,
                               "scene_moving":bool(scene_motion.get("moving", False)),
                               "scene_motion_ready":bool(scene_motion.get("ready", False)),
                               "scene_motion_score":float(scene_motion.get("score", 0.0) or 0.0),
                               "ekran_merkez":(ecx,ecy),"offset":(ox,oy),
                               "hwnd":hwnd,"client_cfg":cc, "client_idx": ci,
                               "target_generation":frame_target_generation,
                               "ts": frame_capture_ts}
                guncel[pk] = self._publish_client_vision(pk, client_data)

                # Debug frame
                if cc.get("debug_on", True):
                    now = time.time()
                    last_encode = self._last_debug_encode.get(pk, 0)
                    if now - last_encode >= self._debug_encode_interval:
                        vis = img.copy()
                        
                        # Mevcut algÄ±lanan modeller (yeÅŸil)
                        for b1,b2,b3,b4,cf in kut:
                            cv2.rectangle(vis,(b1,b2),(b3,b4),(0,255,0),2)
                            cv2.drawMarker(vis,((b1+b3)//2,(b2+b4)//2),(0,255,255),cv2.MARKER_CROSS,14,1)
                            cv2.putText(vis,f"{cf:.0%}",(b1,b2-6),cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,255,0),1)
                        
                        # Bellekte onaylÄ± hedef varsa her zaman gÃ¶ster (YOLO kaÃ§Ä±rsa da)
                        tm = self.st.target_memory.get(pk, {})
                        if tm.get("last_confirmed_pos"):
                            lx, ly = tm["last_confirmed_pos"]
                            is_memory = not bool(kut)  # YOLO kaÃ§Ä±rdÄ±, bellekten gÃ¶steriliyor
                            if is_memory:
                                cv2.rectangle(vis,(lx-20,ly-20),(lx+20,ly+20), (0, 180, 255), 2)
                                cv2.putText(vis,"MEM",(lx-18,ly-22),cv2.FONT_HERSHEY_SIMPLEX,0.35,(0,180,255),1)
                        
                        cv2.circle(vis,(ecx,ecy),cc.get("ignore_radius",35),(75,0,130),2)
                        hclr = (0,255,0) if hp_var else (0,0,255)
                        cv2.rectangle(vis,(x1h,y1h),(x2h,y2h),hclr,2)
                        cv2.putText(vis,f"HP:{hp_px}",(x1h,y1h-6),cv2.FONT_HERSHEY_SIMPLEX,0.4,hclr,1)
                        if fill_box:
                            fx1, fy1, fx2, fy2 = fill_box
                            fclr = (0, 255, 255) if hp_fill is not None else (0, 140, 255)
                            cv2.rectangle(vis, (fx1, fy1), (fx2, fy2), fclr, 2)
                            ftxt = "CAN:--" if hp_fill is None else f"CAN:{hp_fill * 100:.1f}%"
                            cv2.putText(vis, ftxt, (fx1, max(12, fy1 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, fclr, 1)
                        motion_text = "HAREKET" if scene_motion.get("moving") else "SABIT"
                        cv2.putText(vis, f"{motion_text}:{scene_motion.get('score', 0.0):.2f}", (8, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 220, 0), 1)

                        # KÃ¼Ã§Ã¼lt + JPEG encode (dÃ¼ÅŸÃ¼k kalite â€” hÄ±z iÃ§in)
                        try:
                            small = cv2.resize(vis, (640,360)) if img.shape[1] > 700 else vis
                            _,buf = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 30])
                            b64_frames[pk] = base64.b64encode(buf.tobytes()).decode()
                            self._publish_debug_frame(pk, b64_frames[pk])
                            self._last_debug_encode[pk] = now
                        except: pass

            # Client sonuclari yukarida tek tek yayinlandi. Burada yalnizca o
            # turda uretilemeyen/eski client verilerini temizle.
            with self.st.lk:
                self.st.wdata.update(guncel)
                stale_data_keys = [
                    key for key in self.st.wdata
                    if key not in active_keys or key not in guncel
                ]
                for key in stale_data_keys:
                    del self.st.wdata[key]
                # Inaktif client'larÄ±n frame'lerini temizle
                stale_keys = [pk for pk in self.st.frame_b64 if pk not in active_keys]
                for pk in stale_keys:
                    del self.st.frame_b64[pk]
                self.st.frame_b64.update(b64_frames)
                now = time.time()
                for pk in active_keys:
                    if pk not in guncel and now >= self.st.captcha_cd.get(pk, 0):
                        self.st.captcha_block[pk] = False
                        self.st.captcha_state[pk] = False
                        if self.st.durum.get(pk) == "CAPTCHA":
                            self.st.durum[pk] = "BEKLIYOR"

            # FPS limiti â€” Normal: ~20fps
            elapsed = time.time() - loop_start
            time.sleep(max(0, 0.050 - elapsed))  # 20 FPS

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
#  PyWebView API
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
class API:
    def __init__(self, cfg, state, diagnostic_recorder=None):
        self.cfg, self.st = cfg, state
        self._diagnostic_recorder = diagnostic_recorder
        self._vt = None; self._at = None
        self._toggle_lock = threading.Lock()
        self._toggle_busy_log_t = 0.0
        self._terminal_logs = deque(maxlen=800)
        self._terminal_file_offsets = {}
        self._terminal_lock = threading.Lock()
        self._maintenance = False
        self._maintenance_resume = None
        self._maintenance_complete = False
        self._pending_resume = None
        self._startup_gate = bool(os.environ.get("PHANTOM_MANAGED_RUN"))

    def _config_signature(self):
        with self.cfg.lk:
            value = json.dumps(self.cfg.d, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _resume_clients(self):
        import win32process
        clients = []
        configs = {ci: self.cfg.client(ci) for ci in CLIENT_IDS}
        if duplicate_client_ids(configs):
            raise ValueError("Ayni pencere birden fazla client'a atanmis")
        for ci, cc in configs.items():
            if not cc.get("aktif", True):
                continue
            hwnd = hwnd_al(cc.get("pencere"))
            if not hwnd or not win32gui.IsWindow(hwnd) or win32gui.IsIconic(hwnd):
                raise ValueError(f"Client {ci} penceresi hazir degil")
            model = cc.get("model_yolu") or self.cfg.g("model_yolu")
            if not model or not os.path.isfile(model):
                raise ValueError(f"Client {ci} modeli bulunamadi")
            if not (cc.get("hp_region_custom") and cc.get("hp_region")):
                raise ValueError(f"Client {ci} HP ayari eksik")
            clients.append({"client": ci, "hwnd": hwnd,
                "pid": win32process.GetWindowThreadProcessId(hwnd)[1],
                "title": win32gui.GetWindowText(hwnd),
                "rect": list(win32gui.GetWindowRect(hwnd))})
        if not clients:
            raise ValueError("Aktif istemci yok")
        return clients

    def quiesce_for_update(self, force=False):
        """Stop bot workers cooperatively. Never terminate game processes."""
        if not self._toggle_lock.acquire(blocking=False):
            return {"ok": False, "reason": "Baslat/durdur islemi mesgul"}
        try:
            if self._maintenance_complete:
                return {"ok": True, "resume": self._maintenance_resume or {}}
            if not input_transaction_lock.acquire(timeout=.1):
                return {"ok": False, "reason": "Giris isleminin bitmesi bekleniyor"}
            try:
                if not self._maintenance:
                    with self.st.lk:
                        active = self.st.aktif
                        blocked = (self.st.global_pause_active or self.st.captcha_global_active
                                   or self.st.message_global_active)
                    action = self._at
                    busy = action and (
                        getattr(action, "_revive_state", {})
                        or any(action._buff_running.values())
                        or any(action._loot_running.values())
                        or any(action._buff_needs_remount.values())
                        or any(state not in ("ARANIYOR", "BEKLIYOR") for state in action.dur.values()))
                    if not force and active and (blocked or busy):
                        return {"ok": False, "reason": "Savas/canlanma/giris islemi bitince guncellenecek"}
                    resume = {"active": bool(active and not force)}
                    if resume["active"]:
                        resume.update(clients=self._resume_clients(), config=self._config_signature(),
                            buff_next=dict(action._buff_next_t) if action else {},
                            kills=dict(self.st.kill_counts))
                    self._maintenance_resume = resume
                    self._maintenance = True
                with self.st.lk:
                    self.st.aktif = False
                    self.st.started_at = 0
                workers = [worker for worker in (self._at, self._vt) if worker]
                for worker in workers:
                    worker.stop()
            finally:
                input_transaction_lock.release()
            deadline = time.monotonic() + 12
            for worker in workers:
                worker.join(timeout=max(0, deadline-time.monotonic()))
            if any(worker.is_alive() for worker in workers):
                return {"ok": False, "reason": "Eski bot is parcacigi henuz kapanmadi; yeni bot acilmayacak"}
            if self._vt:
                for watcher in getattr(self._vt, "captcha_w", {}).values():
                    job = getattr(watcher, "_rumeli2_job_thread", None)
                    if job and job.is_alive():
                        return {"ok": False, "reason": "Arka plan isi henuz kapanmadi"}
            with input_transaction_lock:
                for key in ("space", "w", "a", "s", "d", "q", "g", "t", "z",
                            "1", "2", "3", "4", "f1", "f2", "f3", "f4", "ctrl", "alt", "shift"):
                    keyboard.release(key)
            if self._diagnostic_recorder:
                self._diagnostic_recorder.stop()
                self._diagnostic_recorder.join(timeout=5)
                if self._diagnostic_recorder.is_alive():
                    return {"ok": False, "reason": "Video kaydinin kapanmasi bekleniyor"}
            self._at = self._vt = None
            self._maintenance_complete = True
            log_event(self.st, "info", "[UPDATE] Bot ve kayit guvenle durduruldu")
            return {"ok": True, "resume": self._maintenance_resume}
        except Exception as exc:
            return {"ok": False, "reason": str(exc)}
        finally:
            self._toggle_lock.release()

    def resume_after_update(self, resume):
        if not resume.get("active"):
            self._startup_gate = False
            return {"ok": True}
        try:
            if resume.get("config") != self._config_signature():
                raise ValueError("Ayarlar degisti; otomatik devam edilmedi")
            if resume.get("clients") != self._resume_clients():
                raise ValueError("Oyun pencereleri degisti; otomatik devam edilmedi")
            self._pending_resume = resume
            if not self._toggle(source="guvenli guncelleme"):
                raise ValueError("Bot baslatilamadi")
            return {"ok": True}
        except Exception as exc:
            log_event(self.st, "warn", f"[UPDATE] {exc}")
            return {"ok": False, "reason": str(exc)}
        finally:
            self._pending_resume = None
            self._startup_gate = False

    def _append_terminal_log(self, level, message, ts=None):
        entry = {
            "ts": ts or time.strftime("%H:%M:%S"),
            "level": level,
            "message": str(message or ""),
            "source": "terminal",
        }
        with self._terminal_lock:
            self._terminal_logs.append(entry)
        return entry

    def _terminal_log_files(self):
        patterns = [
            os.path.join(LOG_DIR, "phantom_stdout_*.log"),
            os.path.join(LOG_DIR, "phantom_stderr_*.log"),
            os.path.join(LOG_DIR, "kurulum_*.log"),
        ]
        files = []
        for pattern in patterns:
            files.extend(glob.glob(pattern))
        try:
            stdout_name = getattr(sys.stdout, "name", "")
            stderr_name = getattr(sys.stderr, "name", "")
            for name in (stdout_name, stderr_name):
                if name and isinstance(name, str) and os.path.exists(name):
                    files.append(name)
        except Exception:
            pass
        unique = sorted(set(files), key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0)
        return unique[-6:]

    def _poll_terminal_files(self):
        for path in self._terminal_log_files():
            try:
                size = os.path.getsize(path)
                offset = self._terminal_file_offsets.get(path)
                if offset is None:
                    offset = max(0, size - 12000)
                if size < offset:
                    offset = 0
                if size == offset:
                    self._terminal_file_offsets[path] = offset
                    continue
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    f.seek(offset)
                    lines = f.readlines()
                    self._terminal_file_offsets[path] = f.tell()
                source = os.path.basename(path)
                level = "stderr" if "stderr" in source.lower() else "cmd"
                for line in lines[-120:]:
                    text = line.rstrip()
                    if text:
                        self._append_terminal_log(level, f"{source}: {text}")
            except Exception:
                continue

    def run_terminal_command(self, command):
        command = str(command or "").strip()
        if not command:
            return {"ok": False, "output": ""}
        if command.lower() in ("cls", "clear"):
            with self._terminal_lock:
                self._terminal_logs.clear()
            return {"ok": True, "cleared": True, "output": ""}
        self._append_terminal_log("cmd", f"> {command}")
        try:
            env = os.environ.copy()
            exe_dir = os.path.dirname(sys.executable or "")
            if exe_dir:
                env["PATH"] = exe_dir + os.pathsep + env.get("PATH", "")
            env["PYTHONUTF8"] = "1"
            completed = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                shell=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
                env=env,
            )
            output = (completed.stdout or "") + (completed.stderr or "")
            for line in output.splitlines()[-240:]:
                if line.strip():
                    self._append_terminal_log("cmd", line)
            self._append_terminal_log(
                "cmd",
                f"[exit {completed.returncode}]",
            )
            return {"ok": completed.returncode == 0, "code": completed.returncode, "output": output[-8000:]}
        except subprocess.TimeoutExpired as e:
            parts = []
            for part in (e.stdout, e.stderr):
                if isinstance(part, bytes):
                    parts.append(part.decode("utf-8", errors="replace"))
                elif isinstance(part, str):
                    parts.append(part)
            output = "".join(parts)
            self._append_terminal_log("error", "Komut zaman asimina ugradi (20 sn)")
            return {"ok": False, "code": -1, "output": output}
        except Exception as e:
            self._append_terminal_log("error", f"Komut calistirilamadi: {e}")
            return {"ok": False, "code": -1, "output": str(e)}

    def get_config(self):
        result = dict(self.cfg.d)
        result['interception_ok'] = INTERCEPTION_OK
        return result
    def get_client(self, idx): return self.cfg.client(idx)
    def save_client(self, idx, data):
        if self._maintenance:
            return {"ok": False, "error": "Guncelleme icin kapaniliyor"}
        try:
            ci = int(idx)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Gecersiz istemci"}
        if ci not in CLIENT_IDS:
            return {"ok": False, "error": "Gecersiz istemci"}

        incoming = dict(data or {})
        proposed = self.cfg.client(ci)
        proposed.update(incoming)
        clients = {other_ci: self.cfg.client(other_ci) for other_ci in CLIENT_IDS}
        error = validate_client_assignment(ci, proposed, clients)
        if error:
            return {"ok": False, "error": error}

        self.cfg.update_client(ci, incoming)
        return {"ok": True}
    def save_global(self, data):
        global _force_sendinput
        if self._maintenance:
            return {"ok": False, "error": "Guncelleme icin kapaniliyor"}
        incoming = dict(data or {})
        self.cfg.update_global(incoming)
        if "diagnostic_video_enabled" in incoming and self._diagnostic_recorder is not None:
            enabled = bool(incoming.get("diagnostic_video_enabled"))
            self._diagnostic_recorder.set_enabled(enabled)
            log_event(
                self.st,
                "info",
                f"[VIDEO] otomatik tani kaydi {'acildi' if enabled else 'kapatildi'} (UI)",
            )
        _force_sendinput = False
        return {"ok": True}
    def set_model(self, path): self.cfg.s(path, "model_yolu"); return True
    def get_windows(self): return pencereleri_getir()

    def select_model(self, idx=None):
        root=tk.Tk(); root.withdraw(); root.attributes('-topmost',True)
        p=filedialog.askopenfilename(filetypes=[("YOLO","*.pt")]); root.destroy()
        if p:
            if idx in CLIENT_IDS:
                self.cfg.update_client(idx, {"model_yolu": p})
            else:
                self.cfg.s(p,"model_yolu")
            if self._vt is not None and hasattr(self._vt, "model_cache"):
                self._vt.model_cache.clear()
            return {"ok": True, "path": p}
        return {"ok": False, "path": ""}

    def select_hp_bar(self, client_idx):
        threading.Thread(target=self._hp_sec, args=(client_idx,), daemon=True).start()
        return True

    def select_hp_fill(self, client_idx):
        threading.Thread(target=self._hp_fill_sec, args=(client_idx,), daemon=True).start()
        return True

    def select_rumeli2_captcha(self, client_idx):
        """Secili istemci penceresini dondurup soru + 4 secenek alani toplar."""
        try:
            ci = int(client_idx)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Gecersiz istemci"}
        if ci not in CLIENT_IDS:
            return {"ok": False, "error": "Gecersiz istemci"}

        cc = self.cfg.client(ci)
        window_title = cc.get("pencere", "Yok")
        if not window_title or window_title == "Yok":
            return {"ok": False, "error": f"Once Istemciler sayfasindan Client {ci} penceresini sec"}

        hwnd = hwnd_al(window_title)
        if not hwnd or not win32gui.IsWindow(hwnd):
            return {"ok": False, "error": f"Client {ci} penceresi bulunamadi; Istemciler sayfasindan yeniden sec"}

        try:
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                time.sleep(0.15)
            try:
                win32gui.SetForegroundWindow(hwnd)
                time.sleep(0.12)
            except Exception:
                pass

            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = int(right - left)
            height = int(bottom - top)
            if left <= -32000 or top <= -32000 or width <= 0 or height <= 0:
                return {"ok": False, "error": f"Client {ci} penceresi yakalanamadi; pencereyi gorunur duruma getir"}
            monitor = {"top": int(top), "left": int(left), "width": width, "height": height}
            with mss.mss() as sct:
                image = cv2.cvtColor(
                    np.array(sct.grab(monitor), dtype=np.uint8),
                    cv2.COLOR_BGRA2BGR,
                )
        except Exception as exc:
            return {"ok": False, "error": f"Client {ci} penceresi yakalanamadi: {exc}"}
        if image is None or image.size == 0:
            return {"ok": False, "error": f"Client {ci} penceresinden goruntu alinamadi"}

        steps = [
            ("1/5 - YESIL SORU KODUNU SEC", (46, 204, 113)),
            ("2/5 - 1. SECENEK KODUNU SEC", (246, 164, 59)),
            ("3/5 - 2. SECENEK KODUNU SEC", (246, 164, 59)),
            ("4/5 - 3. SECENEK KODUNU SEC", (246, 164, 59)),
            ("5/5 - 4. SECENEK KODUNU SEC", (246, 164, 59)),
        ]
        selected = []
        window_name = "RUMELI2 CAPTCHA Kalibrasyonu"
        try:
            for label, color in steps:
                preview = image.copy()
                for idx, (x, y, width, height) in enumerate(selected):
                    previous_color = (46, 204, 113) if idx == 0 else (246, 164, 59)
                    cv2.rectangle(preview, (x, y), (x + width, y + height), previous_color, 2)
                cv2.rectangle(preview, (8, 8), (min(preview.shape[1] - 8, 430), 42), (8, 8, 8), -1)
                cv2.putText(preview, label, (18, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.58, color, 2, cv2.LINE_AA)
                cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
                cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
                roi = cv2.selectROI(window_name, preview, showCrosshair=True, fromCenter=False)
                cv2.destroyWindow(window_name)
                x, y, width, height = [int(value) for value in roi]
                if width <= 0 or height <= 0:
                    return {"ok": False, "cancelled": True}
                selected.append((x, y, width, height))
        except Exception as exc:
            try:
                cv2.destroyWindow(window_name)
            except Exception:
                pass
            return {"ok": False, "error": f"Alan secimi basarisiz: {exc}"}

        height, width = image.shape[:2]

        def _normalize(roi):
            x, y, roi_w, roi_h = roi
            return [
                y / height,
                (y + roi_h) / height,
                x / width,
                (x + roi_w) / width,
            ]

        question_region = _normalize(selected[0])
        option_rois = sorted(selected[1:], key=lambda item: (item[1], item[0]))
        option_regions = [_normalize(roi) for roi in option_rois]
        shared_updates = shared_rumeli2_calibration_updates(
            question_region,
            option_regions,
            [width, height],
        )
        self.cfg.update_clients(shared_updates)

        annotated = image.copy()
        cv2.rectangle(
            annotated,
            (selected[0][0], selected[0][1]),
            (selected[0][0] + selected[0][2], selected[0][1] + selected[0][3]),
            (46, 204, 113),
            2,
        )
        for roi in option_rois:
            x, y, roi_w, roi_h = roi
            cv2.rectangle(annotated, (x, y), (x + roi_w, y + roi_h), (246, 164, 59), 2)
        preview_path = os.path.join(RUMELI2_CALIBRATION_DIR, f"client_{ci}.png")
        try:
            raw_ok, raw_buffer = cv2.imencode(".png", image)
            if raw_ok:
                raw_buffer.tofile(os.path.join(RUMELI2_CALIBRATION_DIR, "shared.png"))
            preview_ok, buffer = cv2.imencode(".png", annotated)
            if preview_ok:
                for client_id in CLIENT_IDS:
                    buffer.tofile(os.path.join(RUMELI2_CALIBRATION_DIR, f"client_{client_id}.png"))
        except Exception:
            preview_path = ""

        log_event(
            self.st,
            "info",
            f"RUMELI2 CAPTCHA ortak kalibrasyonu Client {ci} penceresinden Client 1/2/3 icin kaydedildi: 1 soru + 4 secenek",
        )
        return {
            "ok": True,
            "client": ci,
            "clients": list(CLIENT_IDS),
            "shared": True,
            "question_region": question_region,
            "option_regions": option_regions,
            "calibration_size": [width, height],
            "preview_path": preview_path,
        }

    def _hp_sec(self, ci):
        cc = self.cfg.client(ci)
        hwnd = hwnd_al(cc.get("pencere","Yok"))
        with mss.mss() as sct:
            m = sct.monitors[1]
            if hwnd:
                try:
                    r = win32gui.GetWindowRect(hwnd)
                    if r[0]>=-32000: m={"top":r[1],"left":r[0],"width":r[2]-r[0],"height":r[3]-r[1]}
                except: pass
            img = cv2.cvtColor(np.array(sct.grab(m),dtype=np.uint8), cv2.COLOR_BGRA2BGR)
            window_name = "HP Panelinin Tamamini Sec (Can %100 iken)"
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
            roi = cv2.selectROI(window_name, img, showCrosshair=True, fromCenter=False)
            cv2.destroyWindow(window_name)
            if roi[2]>0 and roi[3]>0:
                h,w = img.shape[:2]
                roi_img = img[roi[1]:roi[1]+roi[3], roi[0]:roi[0]+roi[2]]
                bar_result = locate_hp_bar(roi_img)
                if not bar_result.get("found") or not bar_result.get("bar_box"):
                    log_event(
                        self.st,
                        "error",
                        f"Client {ci} HP panel secimi kaydedilmedi: kirmizi can cubugu bulunamadi; paneli can %100 iken tam secin",
                    )
                    return

                bx, by, bw, bh = bar_result["bar_box"]
                panel_w, panel_h = int(roi[2]), int(roi[3])
                hp_region = [
                    roi[1]/h, (roi[1]+panel_h)/h,
                    roi[0]/w, (roi[0]+panel_w)/w,
                ]
                hp_auto_bar_region = [
                    by/panel_h, (by+bh)/panel_h,
                    bx/panel_w, (bx+bw)/panel_w,
                ]
                hp_fill_region = [
                    (roi[1]+by)/h, (roi[1]+by+bh)/h,
                    (roi[0]+bx)/w, (roi[0]+bx+bw)/w,
                ]
                calibration_update = {
                    "hp_region": hp_region,
                    "hp_region_custom": True,
                    "hp_panel_auto": True,
                    "hp_auto_bar_region": hp_auto_bar_region,
                    "hp_panel_calibration_size": [w, h],
                    "hp_fill_region": hp_fill_region,
                    "hp_fill_region_custom": True,
                }

                # Ayni cozunurlukteki Rumeli2 pencerelerinde panel koordinatlari
                # aynidir. Secimi yalnizca gercek pencere boyutu birebir ayni
                # client'larla paylas; farkli cozunurluge asla kopyalama.
                shared_clients = []
                for target_ci in CLIENT_IDS:
                    target_cfg = self.cfg.client(target_ci)
                    target_hwnd = hwnd_al(target_cfg.get("pencere", "Yok"))
                    if target_ci == ci:
                        shared_clients.append(target_ci)
                        continue
                    if not target_hwnd or not win32gui.IsWindow(target_hwnd):
                        continue
                    try:
                        tr = win32gui.GetWindowRect(target_hwnd)
                        target_size = (int(tr[2] - tr[0]), int(tr[3] - tr[1]))
                    except Exception:
                        continue
                    if target_size == (w, h):
                        shared_clients.append(target_ci)

                self.cfg.update_clients({
                    target_ci: dict(calibration_update)
                    for target_ci in shared_clients
                })
                for target_ci in shared_clients:
                    tpl_path = os.path.join(HP_TEMPLATE_DIR, f"client_{target_ci}.png")
                    cv2.imwrite(tpl_path, roi_img)
                log_event(
                    self.st,
                    "info",
                    f"Client {ci} tam HP paneli kaydedildi: {panel_w}x{panel_h}; "
                    f"can cubugu otomatik bulundu: {bw}x{bh}; ayni boyuttaki client'lar="
                    f"{','.join(str(value) for value in shared_clients)}",
                )
                if self._vt is not None:
                    self._vt._load_hp_templates()
                    for target_ci in shared_clients:
                        target_window = self.cfg.client(target_ci).get("pencere", "Yok")
                        self._vt._hp_presence_hist.pop(target_window, None)
                        self._vt._hp_fill_hist.pop(target_window, None)
                        self._vt._hp_accepted_floor.pop(target_window, None)

    def _hp_fill_sec(self, ci):
        cc = self.cfg.client(ci)
        hwnd = hwnd_al(cc.get("pencere", "Yok"))
        with mss.mss() as sct:
            monitor = sct.monitors[1]
            if hwnd:
                try:
                    rect = win32gui.GetWindowRect(hwnd)
                    if rect[0] >= -32000:
                        monitor = {
                            "top": rect[1], "left": rect[0],
                            "width": rect[2] - rect[0], "height": rect[3] - rect[1],
                        }
                except Exception:
                    pass
            image = cv2.cvtColor(np.array(sct.grab(monitor), dtype=np.uint8), cv2.COLOR_BGRA2BGR)
            window_name = "Can Cubugu Sec"
            cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
            cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
            roi = cv2.selectROI(window_name, image, showCrosshair=True, fromCenter=False)
            cv2.destroyWindow(window_name)
            if roi[2] <= 0 or roi[3] <= 0:
                return
            height, width = image.shape[:2]
            self.cfg.update_client(ci, {
                "hp_fill_region": [
                    roi[1] / height,
                    (roi[1] + roi[3]) / height,
                    roi[0] / width,
                    (roi[0] + roi[2]) / width,
                ],
                "hp_fill_region_custom": True,
            })
            if self._vt is not None:
                target_window = cc.get("pencere", "Yok")
                self._vt._hp_fill_hist.pop(target_window, None)
                self._vt._hp_accepted_floor.pop(target_window, None)
            log_event(self.st, "info", f"Client {ci} can cubugu alani kaydedildi: {roi[2]}x{roi[3]}")

    def get_status(self):
        self._poll_terminal_files()
        with self.st.lk:
            aktif = self.st.aktif
            started_at = self.st.started_at
            cihaz = self.st.cihaz
            durum = dict(self.st.durum)
            wdata = dict(self.st.wdata)
            b64 = dict(self.st.frame_b64)  # zaten base64, encoding yok
            logs = list(self.st.logs)
            captcha_state = dict(self.st.captcha_state)
            now_status = time.time()
            global_pause = {
                "active": self.st.global_pause_active,
                "kind": self.st.global_pause_kind,
                "owner": self.st.global_pause_owner,
                "reason": self.st.global_pause_reason,
                "since": self.st.global_pause_since,
                "elapsed": round(now_status - self.st.global_pause_since, 1) if self.st.global_pause_active and self.st.global_pause_since else 0.0,
            }

        with self.st.lk:
            kill_counts = dict(self.st.kill_counts)
        with self._terminal_lock:
            terminal_logs = list(self._terminal_logs)
        video_status = (
            self._diagnostic_recorder.status()
            if self._diagnostic_recorder is not None
            else {"enabled": False, "recording": False}
        )
        result = {"aktif":aktif, "started_at":started_at, "cihaz":cihaz, "vision_fps": 0.0, "logs": logs + terminal_logs, "global_pause": global_pause, "diagnostic_video": video_status, "checklist": {"clients": {}}, "clients":{}}
        client_configs = {ci: self.cfg.client(ci) for ci in CLIENT_IDS}
        duplicate_clients = duplicate_client_ids(client_configs)
        for ci in CLIENT_IDS:
            cc = client_configs[ci]
            pk = cc.get("pencere", "Yok")
            client_kill_key = f"c{ci}"
            kill_count = kill_counts.get(client_kill_key)
            if kill_count is None:
                kill_count = kill_counts.get(pk, 0)
            client_aktif = cc.get("aktif", True)
            hp_ready = bool(cc.get("hp_region_custom") and cc.get("hp_region"))
            hp_fill_ready = bool(cc.get("hp_fill_region_custom") and cc.get("hp_fill_region"))
            hp_panel_auto = bool(cc.get("hp_panel_auto") and cc.get("hp_auto_bar_region"))
            duplicate_window = ci in duplicate_clients
            window_ready = client_aktif and pk != "Yok" and not duplicate_window
            model_ready = bool(cc.get("model_yolu") or self.cfg.g("model_yolu"))
            
            result["checklist"]["clients"][str(ci)] = {
                "window_ready": window_ready,
                "model_ready": model_ready,
                "hp_ready": hp_ready
            }
            
            live_seen = pk in wdata or pk in b64
            
            # Daha dÃ¼zenli bir return objesi
            cd = {
                "durum": (
                    "PASIF" if not client_aktif else
                    "PENCERE CAKISMASI" if duplicate_window else
                    (durum.get(pk, "BEKLIYOR") if live_seen else "BEKLIYOR")
                ),
                "hp_var": False,
                "hedef": 0,
                "frame": "",
                "aktif": client_aktif,
                "window": pk,
                "hp_px": 0,
                "captcha": (captcha_state.get(pk, False) if live_seen else False),
                "hp_template": hp_ready,
                "hp_panel_auto": hp_panel_auto,
                "hp_fill_ready": hp_fill_ready,
                "hp_fill": None,
                "hp_template_score": 1.0 if hp_ready else 0.0,
                "kill_count": kill_count
            }
            if not client_aktif:
                result["clients"][str(ci)] = cd
                continue
            if pk in wdata:
                d = wdata[pk]
                cd["hp_var"] = d.get("hp_var",False)
                cd["hedef"] = len(d.get("merkezler",[]))
                cd["hp_px"] = d.get("hp_piksel",0)
                cd["hp_fill"] = d.get("hp_fill")
            if pk in b64 and aktif:
                cd["frame"] = b64[pk]  # pre-encoded, anÄ±nda dÃ¶ner
            result["clients"][str(ci)] = cd
        return result

    def toggle_bot(self):
        self._toggle(source="UI")
        with self.st.lk:
            return {"aktif": self.st.aktif}

    def reset_kills(self):
        with self.st.lk:
            self.st.kill_counts.clear()
        return {"ok": True}

    def _toggle(self, source="UI"):
        if not self._toggle_lock.acquire(blocking=False):
            now = time.time()
            if now - self._toggle_busy_log_t >= 1.0:
                self._toggle_busy_log_t = now
                log_event(self.st, "warn", f"Toggle meÅŸgul, {source} isteÄŸi atlandÄ±")
            return False
        try:
            return self._toggle_locked(source)
        finally:
            self._toggle_lock.release()

    def _toggle_locked(self, source="UI"):
        if self._maintenance:
            return False
        if self._startup_gate and source != "guvenli guncelleme":
            return False
        if not self.st.aktif and any(th and th.is_alive() for th in (self._at, self._vt)):
            log_event(self.st, "warn", "Onceki bot is parcacigi kapanmadan yeniden baslatilamaz")
            return False
        with self.st.lk:
            was_active = self.st.aktif
            self.st.aktif = not self.st.aktif
            a = self.st.aktif
            self.st.started_at = time.time() if a else 0.0
        log_event(self.st, "info", f"{'Bot baslatildi' if a else 'Bot durduruldu'} ({source})")
        if not was_active and a:
            with self.st.lk:
                self.st.wdata.clear()
                self.st.frame_b64.clear()
                self.st.target_memory.clear()
                self.st.captcha_block.clear()
                self.st.captcha_state.clear()
                self.st.captcha_cd.clear()
                self.st.durum.clear()
                self.st.message_global_active = False
                self.st.message_global_owner = None
                self.st.message_global_since = 0.0
                self.st.captcha_global_active = False
                self.st.captcha_global_owner = None
                self.st.captcha_global_since = 0.0
                self.st.global_pause_active = False
                self.st.global_pause_kind = ""
                self.st.global_pause_owner = None
                self.st.global_pause_reason = ""
                self.st.global_pause_since = 0.0
                self.st.message_farm_pause_until.clear()
            if INTERCEPTION_OK:
                kb_info = f"klavye cihaz {_ikdev}" if _ikdev is not None else "klavye cihaz YOK"
                log_event(self.st, "info", f"Giris: Interception kernel driver (mouse {_idev}, {kb_info})")
                log_event(self.st, "info", "Tiklama modu: Interception")
            else:
                log_event(self.st, "info", "Giris: SendInput (Interception bulunamadi)")
                log_event(self.st, "info", "Tiklama modu: SendInput")
            self._vt   = VisionThread(self.cfg, self.st)
            self._at   = ActionThread(self.cfg, self.st)
            if self._pending_resume:
                self._at._buff_next_t.update(self._pending_resume.get("buff_next", {}))
                with self.st.lk:
                    self.st.kill_counts.update(self._pending_resume.get("kills", {}))
            self._vt.start(); self._at.start()
        elif was_active and not a:
            for th in (self._at, self._vt):
                if th:
                    th.stop()
            for th in (self._at, self._vt):
                if th:
                    th.join(timeout=1.5)
            if self._vt and not self._vt.is_alive():
                self._vt._unload_ocr()
                self._vt = None
            if self._at and not self._at.is_alive():
                self._at = None
        return True

def main():
    print("[STARTUP] Uygulama ana baslangicina girdi.", flush=True)
    instance_lock = InstanceLock(os.path.join(RUNTIME_DIR, "manager", "app.lock")).acquire()
    _cleanup_runtime_dir(LOG_DIR, LOG_RETENTION_DAYS, keep_suffixes=(".jsonl",))
    _cleanup_runtime_dir(EVIDENCE_DIR, EVIDENCE_RETENTION_DAYS, keep_suffixes=(".png", ".json"))
    cfg = Cfg(); state = State()
    diagnostic_recorder = DiagnosticVideoRecorder(
        DIAGNOSTIC_VIDEO_DIR,
        context_provider=lambda: _diagnostic_video_context(cfg, state),
        log_callback=lambda level, message: log_event(state, level, message),
        enabled=cfg.g("diagnostic_video_enabled") is not False,
    )
    api = API(cfg, state, diagnostic_recorder=diagnostic_recorder)
    diagnostic_recorder.start()
    # F5 hotkey - key-up olayÄ±na baÄŸlÄ± kalmadan debounce ile Ã§alÄ±ÅŸÄ±r.
    _f5_last_t = 0.0
    _f5_lock = threading.Lock()
    app_stopping = threading.Event()
    def _trigger_f5_toggle(source):
        nonlocal _f5_last_t
        if app_stopping.is_set() or api._maintenance:
            return
        now = time.time()
        with _f5_lock:
            if now - _f5_last_t < 0.35:
                return
            _f5_last_t = now
        log_event(state, "info", f"F5 algilandi ({source})")
        threading.Thread(target=api._toggle, kwargs={"source": "F5"}, daemon=True).start()

    def _on_f5(event):
        if event.name != 'f5' or event.event_type != 'down':
            return
        _trigger_f5_toggle("hook")
    keyboard.hook(_on_f5)

    def _f5_poll_loop():
        was_down = False
        while not app_stopping.is_set():
            try:
                down = bool(win32api.GetAsyncKeyState(0x74) & 0x8000)
                if down and not was_down:
                    _trigger_f5_toggle("poll")
                was_down = down
                time.sleep(0.025)
            except Exception as e:
                log_event(state, "warn", f"F5 poll hata: {e}")
                time.sleep(1.0)
    threading.Thread(target=_f5_poll_loop, daemon=True).start()
    # SHIFT+SOL TIK iÃ§in hotkey (normal tÄ±klamayÄ± engelle, bot tÄ±klamasÄ±nÄ± kullan)
    def _safe_shift_click():
        if not app_stopping.is_set() and not api._maintenance:
            sol_tik_hw_shift_callback()
    keyboard.add_hotkey('shift+left', _safe_shift_click, suppress=True)
    print("[STARTUP] WebView penceresi tanimlaniyor.", flush=True)
    window = webview.create_window(
        title="PHANTOM",
        url=HTML_FILE,
        js_api=api,
        width=1120,
        height=620,
        resizable=True,
    )
    managed_run = os.environ.get("PHANTOM_MANAGED_RUN")
    lifecycle = ManagedLifecycle(api, window, managed_run) if managed_run else None
    if lifecycle:
        window.events.loaded += lifecycle.on_loaded
        window.events.closing += lifecycle.on_closing
        lifecycle.start()
    else:
        def _on_closing():
            return api.quiesce_for_update(force=True).get("ok", False)
        window.events.closing += _on_closing
    print("[STARTUP] WebView olay dongusu baslatiliyor.", flush=True)
    try:
        webview.start(debug=False)
    finally:
        app_stopping.set()
        keyboard.unhook_all()
        if lifecycle:
            lifecycle.close()
        api.quiesce_for_update(force=True)
        diagnostic_recorder.stop()
        diagnostic_recorder.join(timeout=3.0)
        instance_lock.close()

if __name__ == '__main__':
    main()
