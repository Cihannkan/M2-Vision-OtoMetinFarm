"""Lightweight visual signals used by the combat state machine."""

from __future__ import annotations

import cv2
import numpy as np


TARGET_DISTANCE_WEIGHT = 0.45
TARGET_SIZE_WEIGHT = 0.30
TARGET_CONFIDENCE_WEIGHT = 0.15
TARGET_STABILITY_WEIGHT = 0.10
TARGET_MAX_BOX_AREA = 25000.0
TARGET_STABLE_RADIUS = 8.0

HP_BAR_RED_MIN = 145
HP_BAR_RED_GREEN_GAP = 55
HP_BAR_RED_BLUE_GAP = 45


def _index_runs(indices, max_gap=2):
    values = [int(value) for value in np.asarray(indices).reshape(-1)]
    if not values:
        return []
    runs = []
    start = previous = values[0]
    for value in values[1:]:
        if value - previous > int(max_gap):
            runs.append((start, previous))
            start = value
        previous = value
    runs.append((start, previous))
    return runs


def _bright_red_mask(frame_bgr: np.ndarray):
    """Return a strict red mask that rejects Rumeli2's brown scenery."""
    blue, green, red = cv2.split(frame_bgr)
    red_i = red.astype(np.int16)
    green_i = green.astype(np.int16)
    blue_i = blue.astype(np.int16)
    mask = (
        (red_i >= HP_BAR_RED_MIN)
        & ((red_i - green_i) >= HP_BAR_RED_GREEN_GAP)
        & ((red_i - blue_i) >= HP_BAR_RED_BLUE_GAP)
    ).astype(np.uint8) * 255
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((1, 3), np.uint8))


def locate_hp_bar(
    frame_bgr: np.ndarray,
    expected_box=None,
    search_margin=10,
    horizontal_search_margin=None,
):
    """Locate Rumeli2's thin red target-HP bar and estimate its fill.

    With no ``expected_box`` this is the calibration pass and requires a long
    horizontal bar.  During runtime the calibrated full-width box is supplied;
    a short remaining red segment is then enough, provided that its left edge
    and vertical position are close to the calibrated bar.  Coordinates are
    returned relative to ``frame_bgr``.
    """
    result = {
        "found": False,
        "fill": None,
        "score": 0.0,
        "bar_box": None,
        "red_box": None,
    }
    if frame_bgr is None or frame_bgr.size == 0:
        return result
    height, width = frame_bgr.shape[:2]
    if height < 4 or width < 12:
        return result

    expected = None
    if expected_box is not None:
        try:
            ex, ey, ew, eh = [int(round(float(value))) for value in expected_box]
        except (TypeError, ValueError):
            return result
        if ew < 8 or eh < 2:
            return result
        expected = (ex, ey, ew, eh)
        margin = max(2, int(round(float(search_margin))))
        horizontal_margin = margin
        if horizontal_search_margin is not None:
            horizontal_margin = max(
                margin,
                int(round(float(horizontal_search_margin))),
            )
        sx1 = max(0, ex - horizontal_margin)
        sy1 = max(0, ey - margin)
        sx2 = min(width, ex + ew + horizontal_margin)
        sy2 = min(height, ey + eh + margin)
    else:
        sx1 = sy1 = 0
        sx2, sy2 = width, height

    search = frame_bgr[sy1:sy2, sx1:sx2]
    if search.size == 0:
        return result
    red_mask = _bright_red_mask(search)
    # Rumeli2 cubugunun ince dis cizgisi ve altin/kirmizi uclari canla
    # birlikte degismez. Yalniz en az uc satir boyunca devam eden kalin ic
    # dolguyu aday say; boylece sabit cerceve %100 can gibi olculmez.
    min_rows = 3 if red_mask.shape[0] >= 5 else max(1, red_mask.shape[0] // 2)
    active_columns = np.flatnonzero(np.count_nonzero(red_mask, axis=0) >= min_rows)
    runs = _index_runs(active_columns, max_gap=2)
    if not runs:
        return result

    candidates = []
    for first, last in runs:
        run_width = int(last - first + 1)
        gx = int(sx1 + first)
        column_slice = red_mask[:, first:last + 1]
        row_min_pixels = max(1, min(run_width, int(np.ceil(run_width * 0.30))))
        active_rows = np.flatnonzero(np.count_nonzero(column_slice, axis=1) >= row_min_pixels)
        if active_rows.size == 0:
            continue
        gy1 = int(sy1 + active_rows[0])
        gy2 = int(sy1 + active_rows[-1] + 1)
        run_height = max(1, gy2 - gy1)

        if expected is None:
            minimum_width = max(24, int(round(width * 0.15)))
            if run_width < minimum_width or run_width < run_height * 4:
                continue
            center_y = (gy1 + gy2) / 2.0
            if not (height * 0.12 <= center_y <= height * 0.88):
                continue
            right_bias = float(np.clip((gx + run_width) / max(1, width), 0.0, 1.0))
            score = float(np.clip((run_width / max(1, width)) * 2.2 + right_bias * 0.35, 0.0, 1.0))
            full_box = (
                gx,
                max(0, gy1 - 2),
                run_width,
                min(height, gy2 + 2) - max(0, gy1 - 2),
            )
            fill = 1.0
        else:
            ex, ey, ew, eh = expected
            margin = max(2, int(round(float(search_margin))))
            horizontal_margin = margin
            if horizontal_search_margin is not None:
                horizontal_margin = max(
                    margin,
                    int(round(float(horizontal_search_margin))),
                )
            start_delta = abs(gx - ex)
            expected_cy = ey + (eh / 2.0)
            actual_cy = (gy1 + gy2) / 2.0
            y_delta = abs(actual_cy - expected_cy)
            if start_delta > horizontal_margin + 4 or y_delta > margin + max(2.0, eh / 2.0):
                continue
            if run_width > int(round(ew * 1.25)) + 3:
                continue
            fill = float(np.clip(run_width / max(1, ew), 0.0, 1.0))
            align_x = 1.0 - min(1.0, start_delta / max(1.0, horizontal_margin + 4.0))
            align_y = 1.0 - min(1.0, y_delta / max(1.0, margin + (eh / 2.0)))
            score = float(np.clip(0.50 * align_x + 0.30 * align_y + 0.20 * min(1.0, fill * 4.0), 0.0, 1.0))
            dx = gx - ex
            dy = int(round(actual_cy - expected_cy))
            full_box = (ex + dx, ey + dy, ew, eh)

        candidates.append({
            "found": True,
            "fill": fill,
            "score": score,
            "bar_box": tuple(int(value) for value in full_box),
            "red_box": (gx, gy1, run_width, run_height),
        })

    if not candidates:
        return result
    candidates.sort(key=lambda item: (item["score"], item["red_box"][2]), reverse=True)
    return candidates[0]


def is_credible_hp_bar(bar_result, was_confirmed=False, min_initial_fill=0.08):
    """Reject tiny red fragments until a real HP panel has been confirmed."""
    if not isinstance(bar_result, dict) or not bar_result.get("found"):
        return False
    if was_confirmed:
        return True
    try:
        fill = float(bar_result.get("fill"))
    except (TypeError, ValueError):
        return False
    return fill >= float(min_initial_fill)


def match_hp_panel_anchor(roi_bgr, template_gray, min_score=0.72):
    """Match the target panel's stable right edge/X anchor.

    Rumeli2 changes the panel width with the target name, while its right frame
    and close button remain stable.  Matching only this anchor avoids dynamic
    text and HP fill without accepting an unrelated red line as a panel.
    """
    result = {"matched": False, "score": 0.0, "x": 0, "y": 0, "w": 0, "h": 0}
    if roi_bgr is None or getattr(roi_bgr, "size", 0) == 0:
        return result
    if template_gray is None or getattr(template_gray, "size", 0) == 0:
        return result

    if len(template_gray.shape) == 3:
        template_gray = cv2.cvtColor(template_gray, cv2.COLOR_BGR2GRAY)
    roi_gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY) if len(roi_bgr.shape) == 3 else roi_bgr
    template_height, template_width = template_gray.shape[:2]
    anchor_width = min(template_width, max(36, int(round(template_width * 0.12))))
    anchor = template_gray[:, template_width - anchor_width:]
    if roi_gray.shape[0] < template_height or roi_gray.shape[1] < anchor_width:
        return result

    scores = cv2.matchTemplate(roi_gray, anchor, cv2.TM_CCOEFF_NORMED)
    scores = np.nan_to_num(scores, nan=0.0, posinf=0.0, neginf=0.0)
    _minimum, score, _minimum_location, location = cv2.minMaxLoc(scores)
    score = float(score)
    # The outer edge is translucent. A second, stricter vote uses the close
    # glyph together with its surrounding button, at the SAME candidate offset.
    # A red bar alone still cannot establish panel presence.
    if template_width >= 80 and 28 <= template_height <= 60 and score < float(min_score):
        scale = template_height / 38.0
        gx = template_width - anchor_width
        symbol_box = (template_width - round(28 * scale), round(14 * scale),
                      template_width - round(14 * scale), round(28 * scale))
        context_box = (gx + round(8 * scale), round(6 * scale),
                       template_width - round(8 * scale), template_height - round(6 * scale))
        smooth = cv2.GaussianBlur(roi_gray, (3, 3), .7)
        maps = []
        out_h, out_w = scores.shape
        for x1, y1, x2, y2 in (symbol_box, context_box):
            patch = template_gray[y1:y2, x1:x2]
            if patch.size == 0 or float(np.std(patch)) < 5:
                maps = []
                break
            patch = cv2.GaussianBlur(patch, (3, 3), .7)
            mask = None
            if maps:
                mask = np.full(patch.shape, 255, dtype=np.uint8)
                sx1, sy1, sx2, sy2 = symbol_box
                mask[max(0, sy1-y1-1):min(patch.shape[0], sy2-y1+1),
                     max(0, sx1-x1-1):min(patch.shape[1], sx2-x1+1)] = 0
            values = cv2.matchTemplate(smooth, patch, cv2.TM_CCOEFF_NORMED, mask=mask)
            maps.append(np.nan_to_num(values[y1:y1+out_h, x1-gx:x1-gx+out_w], nan=0, posinf=0, neginf=0))
        if len(maps) == 2 and maps[0].shape == maps[1].shape == scores.shape:
            qualified = np.where((maps[0] >= .85) & (maps[1] >= .50), maps[0], 0)
            _, local_score, _, local_position = cv2.minMaxLoc(qualified)
            if local_score > score:
                score, location = float(local_score), local_position
    return {
        "matched": score >= float(min_score),
        "score": score,
        "x": int(location[0]),
        "y": int(location[1]),
        "w": int(anchor_width),
        "h": int(template_height),
    }


def hp_panel_presence_vote(credible_bar, structure_matched, was_confirmed=False):
    """Accept panel presence only from the stable frame/anchor structure.

    The changing red fill is useful for measuring damage, but it is not a
    trustworthy presence signal on its own.  World effects and other red UI
    elements can otherwise keep a missing panel alive.  Multi-frame voting in
    the caller already provides the required one-frame hysteresis.
    """
    del credible_bar, was_confirmed
    return bool(structure_matched)


def is_plausible_hp_sample(previous_fill, current_fill, max_increase=0.04):
    """Reject impossible HP growth while tracking the same target generation.

    Metin stones do not heal during the tracked fight.  A small upward change
    is tolerated for pixel/median noise, but a larger jump indicates that the
    bar detector saw another red element or another target/client frame.
    """
    if current_fill is None:
        return False
    try:
        current = float(current_fill)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(current) or current < 0.0 or current > 1.0:
        return False
    if previous_fill is None:
        return True
    try:
        previous = float(previous_fill)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(previous):
        return False
    return current <= previous + float(max_increase)


def hp_panel_structure_mask(shape, bar_box=None):
    """Build a mask that keeps the fixed frame/corners and ignores text/fill."""
    height, width = int(shape[0]), int(shape[1])
    if height < 4 or width < 12:
        return np.ones((max(1, height), max(1, width)), dtype=np.uint8) * 255
    mask = np.zeros((height, width), dtype=np.uint8)
    border_y = max(3, int(round(height * 0.16)))
    border_x = max(5, int(round(width * 0.035)))
    right_anchor = max(24, int(round(width * 0.13)))
    mask[:border_y, :] = 255
    mask[-border_y:, :] = 255
    mask[:, :border_x] = 255
    mask[:, -right_anchor:] = 255
    if bar_box is not None:
        try:
            x, y, w, h = [int(round(float(value))) for value in bar_box]
            x1, y1 = max(0, x - 3), max(0, y - 3)
            x2, y2 = min(width, x + w + 3), min(height, y + h + 3)
            mask[y1:y2, x1:x2] = 0
        except (TypeError, ValueError):
            pass
    return mask


def rank_target_candidates(candidates, screen_center):
    """Rank detected targets using screen distance, size, confidence and stability.

    Distance is screen-space distance, while box area is only a perspective
    proxy for proximity. Candidates are expected to have already passed the
    detector's shape, confidence and temporal-stability filters.
    """
    ecx, ecy = (float(screen_center[0]), float(screen_center[1]))
    max_distance = max(1.0, float(np.hypot(ecx, ecy)))
    ranked = []

    for target in candidates or []:
        if not isinstance(target, dict):
            continue
        try:
            cx = float(target.get("cx", target.get("x", 0)))
            cy = float(target.get("cy", target.get("y", 0)))
            box = target.get("box") or (cx, cy, cx, cy)
            x1, y1, x2, y2 = [float(value) for value in box]
            area = max(0.0, (x2 - x1) * (y2 - y1))
            confidence = float(np.clip(float(target.get("conf", 0.0) or 0.0), 0.0, 1.0))
            stable_distance = max(0.0, float(target.get("stable_distance", TARGET_STABLE_RADIUS) or 0.0))
        except (TypeError, ValueError):
            continue

        distance = float(np.hypot(cx - ecx, cy - ecy))
        distance_score = float(np.clip(1.0 - (distance / max_distance), 0.0, 1.0))
        # Square-root scaling keeps one very large box from dominating all
        # other evidence while still favoring targets that appear nearer.
        size_score = float(np.sqrt(np.clip(area / TARGET_MAX_BOX_AREA, 0.0, 1.0)))
        stability_score = float(np.clip(1.0 - (stable_distance / TARGET_STABLE_RADIUS), 0.0, 1.0))
        score = (
            distance_score * TARGET_DISTANCE_WEIGHT
            + size_score * TARGET_SIZE_WEIGHT
            + confidence * TARGET_CONFIDENCE_WEIGHT
            + stability_score * TARGET_STABILITY_WEIGHT
        )
        ranked.append({
            "target": target,
            "score": float(score),
            "distance": distance,
            "distance_score": distance_score,
            "size_score": size_score,
            "confidence_score": confidence,
            "stability_score": stability_score,
        })

    ranked.sort(
        key=lambda item: (
            item["score"],
            -item["distance"],
            item["confidence_score"],
        ),
        reverse=True,
    )
    return ranked


def filter_targets_away_from(candidates, blocked_position, min_distance=60.0):
    """Return target centers that are not the temporarily blocked target."""
    if not blocked_position:
        return list(candidates or [])

    bx, by = blocked_position
    result = []
    for candidate in candidates or []:
        x, y = candidate
        if float(np.hypot(float(x) - float(bx), float(y) - float(by))) >= float(min_distance):
            result.append(candidate)
    return result


def track_hp_progress(previous_floor, current_fill, min_drop=0.012):
    """Track cumulative HP decrease and report meaningful combat progress."""
    if current_fill is None:
        return previous_floor, False

    current = float(np.clip(float(current_fill), 0.0, 1.0))
    if previous_floor is None:
        return current, False

    floor = float(previous_floor)
    if floor - current >= float(min_drop):
        return current, True
    return floor, False


def is_hp_panel_authoritative(hp_visible, now, ignore_until=0.0):
    """Return whether the visible HP panel may drive the current state."""
    return bool(hp_visible and float(now) >= float(ignore_until or 0.0))


def prepare_scene_frame(frame_bgr: np.ndarray, size=(192, 108)):
    """Return a small grayscale world crop and a mask that avoids the player."""
    if frame_bgr is None or frame_bgr.size == 0:
        return None, None

    height, width = frame_bgr.shape[:2]
    x1, x2 = int(width * 0.08), int(width * 0.92)
    y1, y2 = int(height * 0.18), int(height * 0.78)
    if x2 - x1 < 16 or y2 - y1 < 16:
        return None, None

    gray = cv2.cvtColor(frame_bgr[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)

    mask = np.full(gray.shape, 255, dtype=np.uint8)
    mh, mw = mask.shape
    # Karakter, hedef ve saldiri efektlerinin en yogun oldugu orta-alt bolge.
    cv2.rectangle(
        mask,
        (int(mw * 0.35), int(mh * 0.35)),
        (int(mw * 0.65), int(mh * 0.95)),
        0,
        -1,
    )
    return gray, mask


def estimate_scene_motion(previous_gray: np.ndarray, current_gray: np.ndarray, mask=None):
    """Estimate coherent world motion with sparse optical flow.

    Local mob/skill animations should not count as movement.  We therefore
    require tracked features to agree on one affine motion across several
    spatial cells.
    """
    result = {
        "ready": False,
        "moving": False,
        "score": 0.0,
        "confidence": 0.0,
        "points": 0,
    }
    if previous_gray is None or current_gray is None:
        return result
    if previous_gray.shape != current_gray.shape or previous_gray.size == 0:
        return result

    points = cv2.goodFeaturesToTrack(
        previous_gray,
        maxCorners=90,
        qualityLevel=0.02,
        minDistance=5,
        blockSize=5,
        mask=mask,
    )
    if points is None or len(points) < 8:
        return result

    tracked, status, errors = cv2.calcOpticalFlowPyrLK(
        previous_gray,
        current_gray,
        points,
        None,
        winSize=(15, 15),
        maxLevel=2,
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 18, 0.02),
    )
    if tracked is None or status is None:
        return result

    valid = status.reshape(-1).astype(bool)
    if errors is not None:
        valid &= errors.reshape(-1) < 30.0
    old = points.reshape(-1, 2)[valid]
    new = tracked.reshape(-1, 2)[valid]
    if len(old) < 8:
        return result

    _matrix, inlier_mask = cv2.estimateAffinePartial2D(
        old,
        new,
        method=cv2.RANSAC,
        ransacReprojThreshold=1.5,
        maxIters=200,
        confidence=0.95,
        refineIters=5,
    )
    if inlier_mask is None:
        return result

    inliers = inlier_mask.reshape(-1).astype(bool)
    count = int(np.count_nonzero(inliers))
    if count < 6:
        return result

    old_inliers = old[inliers]
    displacement = np.linalg.norm(new[inliers] - old_inliers, axis=1)
    score = float(np.median(displacement)) if displacement.size else 0.0
    confidence = float(count / max(1, len(old)))

    height, width = previous_gray.shape
    cells = {
        (min(2, int(x * 3 / max(1, width))), min(1, int(y * 2 / max(1, height))))
        for x, y in old_inliers
    }
    spatially_spread = len(cells) >= 3
    moving = score >= 0.70 and confidence >= 0.45 and spatially_spread
    return {
        "ready": True,
        "moving": bool(moving),
        "score": score,
        "confidence": confidence,
        "points": count,
    }


def estimate_red_fill(frame_bgr: np.ndarray):
    """Return the red HP fill extent (0..1) for a tightly selected bar ROI."""
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    height, width = frame_bgr.shape[:2]
    if height < 3 or width < 8:
        return None

    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    low_red = cv2.inRange(hsv, (0, 75, 45), (17, 255, 255))
    high_red = cv2.inRange(hsv, (165, 75, 45), (179, 255, 255))
    red = cv2.bitwise_or(low_red, high_red)
    red = cv2.morphologyEx(red, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((1, 3), np.uint8))

    # Ince yatay/dusey cerceve piksellerini dolgu sanma. Gercek dolgu, cubuk
    # yuksekliginin belirgin bir bolumunu kaplar.
    min_rows = max(3, int(np.ceil(height * 0.35)))
    active_columns = np.flatnonzero(np.count_nonzero(red, axis=0) >= min_rows)
    if active_columns.size < 2:
        return None

    # Sag cerceve ayri bir kirmizi sutun olabilir. Soldan baslayan en genis
    # kesintisiz kirmizi parcayi secerek cerceveyi dolgu hesabindan cikar.
    runs = []
    start = previous = int(active_columns[0])
    for value in active_columns[1:]:
        value = int(value)
        if value - previous > 2:
            runs.append((start, previous))
            start = value
        previous = value
    runs.append((start, previous))

    left_runs = [run for run in runs if run[0] <= int(width * 0.30)]
    if not left_runs:
        return None
    first, last = max(left_runs, key=lambda run: run[1] - run[0])
    if last - first + 1 < 2:
        return None
    return float(np.clip((last + 1) / max(1, width), 0.0, 1.0))
