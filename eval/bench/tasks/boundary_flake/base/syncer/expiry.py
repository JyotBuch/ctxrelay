import time


def is_expired(issued_at, ttl, now=None):
    now = time.time() if now is None else now
    return int(now) - int(issued_at) > ttl
