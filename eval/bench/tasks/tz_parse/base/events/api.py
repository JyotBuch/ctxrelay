from .timeparse import parse_ts


def handle(payload):
    return {"ts": parse_ts(payload["ts"]).isoformat()}
