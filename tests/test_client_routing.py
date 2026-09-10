import json
from pathlib import Path
import unittest

from src.phantom.app.client_routing import (
    CLIENT_IDS,
    duplicate_client_ids,
    shared_rumeli2_calibration_updates,
    validate_client_assignment,
)


class ClientRoutingTests(unittest.TestCase):
    def test_rumeli2_calibration_is_shared_with_independent_copies(self):
        question = [0.1, 0.2, 0.3, 0.4]
        options = [[0.2, 0.3, 0.4, 0.5] for _ in range(4)]
        updates = shared_rumeli2_calibration_updates(question, options, [1280, 720])

        self.assertEqual(set(updates), {1, 2, 3})
        self.assertEqual(updates[2]["rumeli2_question_region"], question)
        updates[1]["rumeli2_question_region"][0] = 9.0
        updates[1]["rumeli2_option_regions"][0][0] = 8.0
        self.assertEqual(updates[2]["rumeli2_question_region"][0], 0.1)
        self.assertEqual(updates[2]["rumeli2_option_regions"][0][0], 0.2)

    def test_three_clients_are_supported(self):
        self.assertEqual(CLIENT_IDS, (1, 2, 3))

    def test_different_windows_are_allowed(self):
        configs = {
            1: {"aktif": True, "pencere": "Game A (ID: 1)"},
            2: {"aktif": True, "pencere": "Game B (ID: 2)"},
            3: {"aktif": False, "pencere": "Yok"},
        }
        self.assertIsNone(validate_client_assignment(2, configs[2], configs))

    def test_same_active_window_is_rejected(self):
        configs = {
            1: {"aktif": True, "pencere": "Game (ID: 9)"},
            2: {"aktif": False, "pencere": "Yok"},
            3: {"aktif": False, "pencere": "Yok"},
        }
        proposed = {"aktif": True, "pencere": "Game (ID: 9)"}
        self.assertIn("Client 1", validate_client_assignment(2, proposed, configs))

    def test_inactive_client_does_not_reserve_window(self):
        configs = {
            1: {"aktif": False, "pencere": "Game (ID: 9)"},
            2: {"aktif": True, "pencere": "Game (ID: 9)"},
            3: {"aktif": False, "pencere": "Yok"},
        }
        self.assertIsNone(validate_client_assignment(2, configs[2], configs))

    def test_duplicate_status_marks_all_owners(self):
        configs = {
            1: {"aktif": True, "pencere": "Game (ID: 9)"},
            2: {"aktif": True, "pencere": "Game (ID: 9)"},
            3: {"aktif": True, "pencere": "Other (ID: 10)"},
        }
        self.assertEqual(duplicate_client_ids(configs), {1, 2})

        configs[1]["pencere"] = "Tüm Ekran"
        self.assertEqual(duplicate_client_ids(configs), {1, 2, 3})

    def test_full_screen_is_rejected_with_another_active_client(self):
        configs = {
            1: {"aktif": True, "pencere": "Game (ID: 9)"},
            2: {"aktif": False, "pencere": "Yok"},
            3: {"aktif": False, "pencere": "Yok"},
        }
        proposed = {"aktif": True, "pencere": "Tüm Ekran"}
        self.assertIn("Tum Ekran", validate_client_assignment(2, proposed, configs))

        configs[1]["pencere"] = "Tüm Ekran"
        proposed["pencere"] = "Game (ID: 10)"
        self.assertIn("Tum Ekran", validate_client_assignment(2, proposed, configs))

    def test_client_three_ui_and_default_config_exist(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "index.html").read_text(encoding="utf-8-sig")
        config = json.loads((root / "config_phantom.json").read_text(encoding="utf-8-sig"))
        self.assertIn("const CLIENT_IDS = [1, 2, 3]", html)
        for element_id in (
            "client3Toggle", "win3", "mdl3", "hpReady3", "hpFillReady3",
            "dbg3", "cfeed3", "coff3", "cov3", "rumeli2Cal3", "sK3", "sKU3",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn("c3", config)
        # config_phantom.json calisan kullanici ayaridir; Client 3 kullanici
        # tarafindan acilmis olabilir. Test bu tercihi kapaliya zorlamamali.
        self.assertIsInstance(config["c3"].get("aktif"), bool)


if __name__ == "__main__":
    unittest.main()
