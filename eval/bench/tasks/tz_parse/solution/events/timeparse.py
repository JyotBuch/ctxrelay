from datetime import datetime, timezone


def parse_ts(s):
    """'2024-01-02 03:04:05' -> naive datetime (local time; legacy callers rely on this)."""
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


def parse_ts_aware(s):
    return datetime.fromisoformat(s).astimezone(timezone.utc)
