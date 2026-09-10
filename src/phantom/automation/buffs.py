"""Periodic in-game buff key sequence."""

BUFF_INTERVAL_SECONDS = 4 * 60.0
BUFF_KEY_HOLD_SECONDS = 0.08
BUFF_SHORT_GAP_SECONDS = 0.12
BUFF_DISMOUNT_DELAY_SECONDS = 0.20
BUFF_ALT_ARM_DELAY_SECONDS = 1.00

# Alt is pressed once before this sequence and released after Alt+F3.
# (key, delay after the key, display label)
BUFF_ALT_SEQUENCE = (
    ("1", 3.00, "ALT+1"),
    ("2", 1.00, "ALT+2"),
    ("3", BUFF_SHORT_GAP_SECONDS, "ALT+3"),
    ("4", BUFF_SHORT_GAP_SECONDS, "ALT+4"),
    ("f1", BUFF_SHORT_GAP_SECONDS, "ALT+F1"),
    ("f2", BUFF_SHORT_GAP_SECONDS, "ALT+F2"),
    ("f3", BUFF_SHORT_GAP_SECONDS, "ALT+F3"),
)

BUFF_AFTER_ALT_SEQUENCE = (
    ("f2", BUFF_SHORT_GAP_SECONDS, "F2"),
    ("f3", BUFF_SHORT_GAP_SECONDS, "F3"),
    ("f4", BUFF_SHORT_GAP_SECONDS, "F4"),
)
