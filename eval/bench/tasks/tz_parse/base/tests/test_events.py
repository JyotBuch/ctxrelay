from datetime import datetime

from events.api import handle
from events.export import export_row, legacy_age_seconds


def test_legacy():
    assert handle({"ts": "2024-01-02 03:04:05"}) == {"ts": "2024-01-02T03:04:05"}
    assert export_row("2024-01-02 03:04:05") == "02/01/2024 03:04"
    assert legacy_age_seconds("2024-01-02 03:04:05", datetime(2024, 1, 2, 3, 4, 15)) == 10
