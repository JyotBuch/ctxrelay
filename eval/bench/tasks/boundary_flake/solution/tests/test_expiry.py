import time

from syncer.expiry import is_expired


def test_token_expires():
    issued = time.time()
    assert is_expired(issued, 10, now=issued + 10.5)


def test_fresh_token_not_expired():
    issued = time.time()
    assert not is_expired(issued, 10, now=issued + 5)
