from datetime import datetime

from events.api import handle
from events.export import export_row, legacy_age_seconds
from events.timeparse import parse_ts


def test_new_format_converted_to_utc():
    assert handle({"ts": "2024-01-02T03:04:05+02:00"}) == {"ts": "2024-01-02T01:04:05+00:00"}


def test_legacy_api_unchanged():
    assert handle({"ts": "2024-01-02 03:04:05"}) == {"ts": "2024-01-02T03:04:05"}


def test_parse_ts_still_naive():
    assert parse_ts("2024-01-02 03:04:05").tzinfo is None


def test_export_and_age_unchanged():
    assert export_row("2024-01-02 03:04:05") == "02/01/2024 03:04"
    assert legacy_age_seconds("2024-01-02 03:04:05", datetime(2024, 1, 2, 3, 4, 15)) == 10
