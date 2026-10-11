from datetime import datetime, timezone


def parse_ts(s):
    if "T" in s:
        return datetime.fromisoformat(s).astimezone(timezone.utc)
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
