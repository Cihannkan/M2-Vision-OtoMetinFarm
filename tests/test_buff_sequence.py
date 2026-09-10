import unittest

from src.phantom.automation.buffs import (
    BUFF_AFTER_ALT_SEQUENCE,
    BUFF_ALT_ARM_DELAY_SECONDS,
    BUFF_ALT_SEQUENCE,
    BUFF_INTERVAL_SECONDS,
)


class BuffSequenceTests(unittest.TestCase):
    def test_alt_is_armed_for_one_second_before_first_slot(self):
        self.assertEqual(BUFF_ALT_ARM_DELAY_SECONDS, 1.0)

    def test_buff_runs_every_four_minutes(self):
        self.assertEqual(BUFF_INTERVAL_SECONDS, 240.0)

    def test_buff_key_order_matches_game_slots(self):
        self.assertEqual(
            [key for key, _delay, _label in BUFF_ALT_SEQUENCE],
            ["1", "2", "3", "4", "f1", "f2", "f3"],
        )
        self.assertEqual(
            [key for key, _delay, _label in BUFF_AFTER_ALT_SEQUENCE],
            ["f2", "f3", "f4"],
        )

    def test_alt_one_and_two_have_configured_long_waits(self):
        delays = {label: delay for _key, delay, label in BUFF_ALT_SEQUENCE}
        self.assertEqual(delays["ALT+1"], 3.0)
        self.assertEqual(delays["ALT+2"], 1.0)
        self.assertLess(delays["ALT+3"], 0.2)
        self.assertLess(delays["ALT+4"], 0.2)


if __name__ == "__main__":
    unittest.main()
