"""DirectML-backed YOLO inference with a safe PyTorch fallback."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np
import torch
from ultralytics import YOLO
from ultralytics.data.augment import LetterBox
from ultralytics.utils.ops import scale_boxes


LogCallback = Callable[[str, str], None]


def _noop_log(_level: str, _message: str) -> None:
    pass


def onnx_path_for(model_path: str) -> str:
    """Return the ONNX companion path used for a selected model."""
    root, extension = os.path.splitext(os.path.abspath(model_path))
    return os.path.abspath(model_path) if extension.lower() == ".onnx" else root + ".onnx"


def directml_available() -> bool:
    """Return whether ONNX Runtime exposes the DirectML provider."""
    if torch.cuda.is_available():
        return False
    try:
        import onnxruntime as ort

        return "DmlExecutionProvider" in ort.get_available_providers()
    except Exception:
        return False


def preferred_backend() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if directml_available():
        return "directml"
    return "cpu"


def _nms_indices(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> np.ndarray:
    """Return score-ordered NMS indices without waking PyTorch's CPU thread pool."""
    if boxes.size == 0:
        return np.empty((0,), dtype=np.int64)

    x1, y1, x2, y2 = boxes.T
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = np.argsort(scores)[::-1]
    keep: list[int] = []

    while order.size:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break

        remaining = order[1:]
        xx1 = np.maximum(x1[current], x1[remaining])
        yy1 = np.maximum(y1[current], y1[remaining])
        xx2 = np.minimum(x2[current], x2[remaining])
        yy2 = np.minimum(y2[current], y2[remaining])
        intersection = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        union = areas[current] + areas[remaining] - intersection
        overlap = np.divide(
            intersection,
            union,
            out=np.zeros_like(intersection, dtype=np.float32),
            where=union > 0,
        )
        order = remaining[overlap <= iou_threshold]

    return np.asarray(keep, dtype=np.int64)


def _numpy_non_max_suppression(
    prediction: np.ndarray,
    conf_threshold: float,
    iou_threshold: float,
    max_detections: int = 300,
) -> np.ndarray:
    """Convert a YOLO ONNX output to ``xyxy, confidence, class`` detections."""
    if prediction.ndim != 3 or prediction.shape[0] != 1:
        raise RuntimeError(f"Beklenmeyen ONNX tahmin sekli: {prediction.shape}")

    # Models exported with embedded NMS return [batch, max_detections, 6].
    # Ultralytics only confidence-filters this format; do the same in NumPy.
    if prediction.shape[-1] == 6 and prediction.shape[1] <= max_detections:
        detections = prediction[0]
        valid = np.isfinite(detections).all(axis=1) & (
            detections[:, 4] >= float(conf_threshold)
        )
        return detections[valid][:max_detections].astype(np.float32, copy=True)

    sample = prediction[0]
    # Ultralytics detection exports are normally [batch, 4 + classes, anchors].
    # Accept anchors-last too so a future ONNX export does not silently break.
    if sample.shape[0] >= 5 and sample.shape[1] < 5:
        candidates = sample.T
    elif sample.shape[1] >= 5 and sample.shape[0] < 5:
        candidates = sample
    else:
        candidates = sample.T if sample.shape[0] <= sample.shape[1] else sample
    if candidates.ndim != 2 or candidates.shape[1] < 5:
        raise RuntimeError(f"Beklenmeyen ONNX tahmin sekli: {prediction.shape}")

    class_scores = candidates[:, 4:]
    class_ids = np.argmax(class_scores, axis=1).astype(np.int64)
    scores = class_scores[np.arange(class_scores.shape[0]), class_ids]
    xywh = candidates[:, :4]
    valid = (
        np.isfinite(xywh).all(axis=1)
        & np.isfinite(scores)
        & (scores >= float(conf_threshold))
        & (xywh[:, 2] > 0)
        & (xywh[:, 3] > 0)
    )
    if not np.any(valid):
        return np.empty((0, 6), dtype=np.float32)

    xywh = xywh[valid].astype(np.float32, copy=False)
    scores = scores[valid].astype(np.float32, copy=False)
    class_ids = class_ids[valid]
    boxes = np.empty_like(xywh, dtype=np.float32)
    half_width = xywh[:, 2] * 0.5
    half_height = xywh[:, 3] * 0.5
    boxes[:, 0] = xywh[:, 0] - half_width
    boxes[:, 1] = xywh[:, 1] - half_height
    boxes[:, 2] = xywh[:, 0] + half_width
    boxes[:, 3] = xywh[:, 1] + half_height

    # Bound the quadratic NMS stage on malformed or unexpectedly noisy output.
    max_candidates = 30000
    if scores.size > max_candidates:
        top = np.argpartition(scores, -max_candidates)[-max_candidates:]
        boxes, scores, class_ids = boxes[top], scores[top], class_ids[top]

    kept: list[int] = []
    for class_id in np.unique(class_ids):
        class_positions = np.flatnonzero(class_ids == class_id)
        local_keep = _nms_indices(
            boxes[class_positions],
            scores[class_positions],
            float(iou_threshold),
        )
        kept.extend(class_positions[local_keep].tolist())

    if not kept:
        return np.empty((0, 6), dtype=np.float32)

    kept_array = np.asarray(kept, dtype=np.int64)
    kept_array = kept_array[np.argsort(scores[kept_array])[::-1]][:max_detections]
    return np.column_stack(
        (boxes[kept_array], scores[kept_array], class_ids[kept_array].astype(np.float32))
    ).astype(np.float32, copy=False)


@dataclass
class _DetectionBoxes:
    xyxy: torch.Tensor
    conf: torch.Tensor

    def __bool__(self) -> bool:
        return bool(self.xyxy.shape[0])


@dataclass
class _DetectionResult:
    boxes: _DetectionBoxes


class DirectMLDetectionModel:
    """Small adapter that preserves the subset of the YOLO result API PHANTOM uses."""

    backend_name = "directml"

    def __init__(self, onnx_path: str):
        import onnxruntime as ort

        if "DmlExecutionProvider" not in ort.get_available_providers():
            raise RuntimeError("DmlExecutionProvider bulunamadi")

        options = ort.SessionOptions()
        # DirectML requires sequential execution and does not support memory patterns.
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(
            onnx_path,
            sess_options=options,
            providers=["DmlExecutionProvider", "CPUExecutionProvider"],
        )
        active = self.session.get_providers()
        if not active or active[0] != "DmlExecutionProvider":
            raise RuntimeError(f"DirectML etkinlesmedi: {active}")

        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or not outputs:
            raise RuntimeError("Beklenmeyen ONNX giris/cikis yapisi")

        shape = inputs[0].shape
        if len(shape) != 4 or not isinstance(shape[-2], int) or not isinstance(shape[-1], int):
            raise RuntimeError(f"Sabit ONNX goruntu boyutu bulunamadi: {shape}")

        self.input_name = inputs[0].name
        self.output_name = outputs[0].name
        self.input_height = int(shape[-2])
        self.input_width = int(shape[-1])
        self._run_lock = threading.Lock()

    def __call__(
        self,
        image,
        stream: bool = False,
        verbose: bool = False,
        conf: float = 0.25,
        imgsz: int = 640,
        iou: float = 0.45,
        **_kwargs,
    ):
        del stream, verbose, imgsz
        if not isinstance(image, np.ndarray) or image.ndim != 3:
            raise TypeError("DirectML modeli tek bir BGR numpy goruntusu bekliyor")

        letterboxed = LetterBox(
            new_shape=(self.input_height, self.input_width),
            auto=False,
            stride=32,
        )(image=image)
        input_tensor = np.ascontiguousarray(
            letterboxed[:, :, ::-1].transpose(2, 0, 1)[None],
            dtype=np.float32,
        )
        input_tensor /= 255.0

        with self._run_lock:
            prediction = self.session.run(
                [self.output_name],
                {self.input_name: input_tensor},
            )[0]

        detections = _numpy_non_max_suppression(
            prediction,
            conf_threshold=float(conf),
            iou_threshold=float(iou),
        )
        if len(detections):
            detections[:, :4] = scale_boxes(
                letterboxed.shape[:2],
                detections[:, :4],
                image.shape[:2],
            )

        boxes = _DetectionBoxes(
            xyxy=torch.from_numpy(np.ascontiguousarray(detections[:, :4])),
            conf=torch.from_numpy(np.ascontiguousarray(detections[:, 4])),
        )
        return [_DetectionResult(boxes=boxes)]


class AutoDetectionModel:
    """Prefer CUDA/DirectML and fall back to the existing Ultralytics CPU path."""

    def __init__(self, model_path: str, log_cb: LogCallback | None = None):
        self.model_path = os.path.abspath(model_path)
        self.log = log_cb or _noop_log
        self.backend_name = "cpu"
        self._model = None
        self._directml_failed = False
        self._load_initial_backend()

    def _activate_yolo(self) -> None:
        self._model = YOLO(self.model_path)
        self.backend_name = "cuda" if torch.cuda.is_available() else "cpu"

    def _load_initial_backend(self) -> None:
        if torch.cuda.is_available():
            self._activate_yolo()
            self.log("info", "Model cihazi: CUDA")
            return

        onnx_path = onnx_path_for(self.model_path)
        onnx_ready = os.path.isfile(onnx_path)
        if onnx_ready and self.model_path.lower().endswith(".pt"):
            onnx_ready = os.path.getmtime(onnx_path) >= os.path.getmtime(self.model_path)

        if directml_available() and onnx_ready:
            try:
                self._model = DirectMLDetectionModel(onnx_path)
                self.backend_name = "directml"
                self.log("info", f"Model cihazi: AMD DirectML ({os.path.basename(onnx_path)})")
                return
            except Exception as exc:
                self._directml_failed = True
                self.log("warn", f"DirectML baslatilamadi, CPU kullanilacak: {exc}")
        elif directml_available():
            self.log(
                "warn",
                f"DirectML icin guncel ONNX model bulunamadi, CPU kullanilacak: {onnx_path}",
            )

        self._activate_yolo()
        self.log("info", "Model cihazi: CPU")

    def __call__(self, *args, **kwargs):
        try:
            return self._model(*args, **kwargs)
        except Exception as exc:
            if self.backend_name != "directml" or self._directml_failed:
                raise
            self._directml_failed = True
            self.log("error", f"DirectML tahmini basarisiz, CPU'ya donuluyor: {exc}")
            self._activate_yolo()
            return self._model(*args, **kwargs)


def create_detection_model(model_path: str, log_cb: LogCallback | None = None) -> AutoDetectionModel:
    return AutoDetectionModel(model_path, log_cb=log_cb)
