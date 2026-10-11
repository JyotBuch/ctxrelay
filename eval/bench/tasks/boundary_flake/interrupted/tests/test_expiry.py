import functools
import time

from syncer.expiry import is_expired


def retry(times):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **k):
            for i in range(times):
                try:
                    return fn(*a, **k)
                except AssertionError:
                    if i == times - 1:
                        raise
        return wrapper
    return deco


@retry(3)
def test_token_expires():
    issued = time.time()
    assert is_expired(issued, 10, now=issued + 10.5)


def test_fresh_token_not_expired():
    issued = time.time()
    assert not is_expired(issued, 10, now=issued + 5)
