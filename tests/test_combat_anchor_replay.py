import unittest
from pathlib import Path
import cv2
import numpy as np
from src.phantom.vision.combat import match_hp_panel_anchor, hp_panel_presence_vote


class AnchorReplayTests(unittest.TestCase):
    def test_client2_visible_and_absent_panels(self):
        root = Path(__file__).resolve().parents[1]
        tpl = cv2.imdecode(np.fromfile(str(root / 'templates/hp_templates/client_2.png'), dtype=np.uint8), 0)
        with np.load(Path(__file__).with_name('hp_client2_replay.npz')) as samples:
            for i, (frame, expected) in enumerate(zip(samples['frames'], samples['expected'])):
                with self.subTest(frame=i):
                    result = match_hp_panel_anchor(frame, tpl)
                    self.assertEqual(result['matched'], bool(expected), result)
                    self.assertEqual(hp_panel_presence_vote(True, result['matched']), bool(expected))

    def test_isolated_close_glyph_without_button_context_is_not_panel(self):
        root = Path(__file__).resolve().parents[1]
        tpl = cv2.imdecode(np.fromfile(str(root / 'templates/hp_templates/client_2.png'), dtype=np.uint8), 0)
        roi = np.full((150, 560), 100, dtype=np.uint8)
        roi[50:64, 100:114] = tpl[14:28, -28:-14]
        self.assertFalse(match_hp_panel_anchor(roi, tpl)['matched'])
