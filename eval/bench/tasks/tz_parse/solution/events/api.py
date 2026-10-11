from .timeparse import parse_ts, parse_ts_aware


def handle(payload):
    s = payload["ts"]
    if "T" in s:
        return {"ts": parse_ts_aware(s).isoformat()}
    return {"ts": parse_ts(s).isoformat()}
