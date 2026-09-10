import os
import unittest

import numpy as np

from src.phantom.vision.directml import (
    AutoDetectionModel,
    _numpy_non_max_suppression,
    directml_available,
    onnx_path_for,
)


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PT_MODEL = os.path.join(PROJECT_ROOT, "models", "best.pt")
ONNX_MODEL = os.path.join(PROJECT_ROOT, "models", "best.onnx")


class DirectMLBackendTests(unittest.TestCase):
    def test_onnx_companion_path(self):
        self.assertEqual(
            onnx_path_for(os.path.join("models", "best.pt")),
            os.path.abspath(os.path.join("models", "best.onnx")),
        )

    def test_numpy_nms_suppresses_overlapping_same_class_boxes(self):
        prediction = np.zeros((1, 5, 3), dtype=np.float32)
        prediction[0, :4, 0] = [50, 50, 40, 40]
        prediction[0, 4, 0] = 0.90
        prediction[0, :4, 1] = [52, 52, 40, 40]
        prediction[0, 4, 1] = 0.80
        prediction[0, :4, 2] = [150, 150, 20, 20]
        prediction[0, 4, 2] = 0.70

        detections = _numpy_non_max_suppression(prediction, 0.25, 0.45)

        self.assertEqual(detections.shape, (2, 6))
        np.testing.assert_allclose(detections[:, 4], [0.90, 0.70], atol=1e-6)
        np.testing.assert_allclose(detections[0, :4], [30, 30, 70, 70], atol=1e-6)

    def test_numpy_nms_keeps_overlapping_boxes_from_different_classes(self):
        prediction = np.zeros((1, 6, 2), dtype=np.float32)
        prediction[0, :4, 0] = [50, 50, 40, 40]
        prediction[0, 4:, 0] = [0.90, 0.10]
        prediction[0, :4, 1] = [50, 50, 40, 40]
        prediction[0, 4:, 1] = [0.10, 0.80]

        detections = _numpy_non_max_suppression(prediction, 0.25, 0.45)

        self.assertEqual(detections.shape, (2, 6))
        self.assertEqual(set(detections[:, 5].astype(int)), {0, 1})

    def test_numpy_nms_preserves_embedded_nms_output(self):
        prediction = np.array(
            [[
                [10, 20, 30, 40, 0.90, 0],
                [50, 60, 70, 80, 0.20, 0],
                [90, 100, 110, 120, 0.75, 1],
            ]],
            dtype=np.float32,
        )

        detections = _numpy_non_max_suppression(prediction, 0.25, 0.45)

        np.testing.assert_allclose(detections, prediction[0, [0, 2]], atol=1e-6)

    @unittest.skipUnless(
        directml_available() and os.path.isfile(PT_MODEL) and os.path.isfile(ONNX_MODEL),
        "DirectML provider or local test model is unavailable",
    )
    def test_directml_model_preserves_result_interface(self):
        model = AutoDetectionModel(PT_MODEL)
        self.assertEqual(model.backend_name, "directml")
        results = model(np.zeros((640, 640, 3), dtype=np.uint8), conf=0.10, imgsz=640)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].boxes.xyxy.shape[1], 4)
        self.assertEqual(results[0].boxes.conf.ndim, 1)


if __name__ == "__main__":
    unittest.main()
