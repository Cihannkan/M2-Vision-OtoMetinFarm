"""Visual death-menu detection and bounded per-client target failure history."""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


@lru_cache(maxsize=1)
def _template():
    path = Path(__file__).resolve().parents[3] / "templates" / "revive_here.png"
    if not path.is_file():
        return None
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)


@lru_cache(maxsize=1)
def _templates():
    variants = []
    for name in ("revive_buttons_native.png",):
        path = Path(__file__).resolve().parents[3] / "templates" / name
        if path.is_file():
            variants.append(cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_GRAYSCALE))
    return [item for item in variants if item is not None]


def detect_death_menu(frame, template=None):
    variants = _templates() if template is None else [template]
    results = [_match_death_menu(frame, item) for item in variants]
    return max(results, key=lambda item: item["score"]) if results else {"visible": False, "score": 0.0, "ready": False}


def _match_death_menu(frame, template):
    """Match both labelled buttons; return only the upper, local-revive button."""
    if template is None or frame is None or frame.size == 0:
        return {"visible": False, "score": 0.0, "ready": template is not None}
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    search = gray[:int(gray.shape[0] * .4), :int(gray.shape[1] * .4)]
    search = cv2.GaussianBlur(search, (3, 3), .7)
    best = {"visible": False, "score": 0.0, "ready": True}
    # Compare the two button interiors separately. The transparent panel and
    # gap show the moving world and must not contribute to the score.
    upper = template[22:43, 12:188]
    lower = template[52:73, 12:188]
    if upper.size == 0 or lower.size == 0:
        return best
    for scale in (.9, 1.0, 1.1):
        top = cv2.GaussianBlur(cv2.resize(upper, None, fx=scale, fy=scale), (3, 3), .7)
        bottom = cv2.GaussianBlur(cv2.resize(lower, (top.shape[1], top.shape[0])), (3, 3), .7)
        h, w = top.shape
        separation = round(30 * scale)
        if search.shape[0] < h + separation or search.shape[1] < w:
            continue
        top_scores = cv2.matchTemplate(search, top, cv2.TM_CCOEFF_NORMED)
        bottom_scores = cv2.matchTemplate(search, bottom, cv2.TM_CCOEFF_NORMED)
        # Both labels must match at the same x and expected vertical spacing.
        # Half-size capture rounds button spacing by up to one pixel.
        candidates = []
        for gap in (separation - 1, separation, separation + 1):
            paired = np.minimum(top_scores[:-gap], bottom_scores[gap:])
            _, value, _, location = cv2.minMaxLoc(paired)
            candidates.append((value, location))
        score, pos = max(candidates, key=lambda item: item[0])
        if score > best["score"]:
            best = {"visible": score >= .85, "score": float(score), "ready": True,
                    "button": (int(pos[0] + w / 2), int(pos[1] + h / 2))}
    return best


def own_hp_visible(frame):
    """Positive red health-bar signal near the lower-left HUD, not target HP."""
    if frame is None or frame.size == 0:
        return False
    h, w = frame.shape[:2]
    roi = frame[max(0, h - 65):h, :min(w, 210)].astype(np.int16)
    b, g, r = cv2.split(roi)
    red = (r > 100) & (r - g > 45) & (r - b > 40)
    return bool(np.max(np.sum(red, axis=1), initial=0) >= 25)


def remember_failed_target(history, pos, now, seconds=60.0):
    history[:] = [item for item in history if item["until"] > now]
    if pos is not None:
        history[:] = [item for item in history if np.hypot(item["pos"][0] - pos[0], item["pos"][1] - pos[1]) > 60]
        history.append({"pos": (float(pos[0]), float(pos[1])), "until": now + seconds})
    del history[:-8]


def filter_failed_targets(targets, history, now):
    history[:] = [item for item in history if item["until"] > now]
    return [p for p in targets if all(np.hypot(p[0] - item["pos"][0], p[1] - item["pos"][1]) > 60 for item in history)]
