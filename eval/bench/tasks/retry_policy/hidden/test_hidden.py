import pytest
from net.client import TransientError, fetch_with_retry


def flaky(n):
    calls = []

    def t(m, u):
        calls.append(m)
        if len(calls) <= n:
            raise TransientError()
        return "ok"
    t.calls = calls
    return t


def test_get_retries_up_to_three_attempts_with_backoff():
    sleeps, t = [], flaky(2)
    assert fetch_with_retry("GET", "u", t, sleep=sleeps.append) == "ok"
    assert len(t.calls) == 3 and sleeps == [1, 2]


def test_gives_up_after_three_attempts():
    t = flaky(5)
    with pytest.raises(TransientError):
        fetch_with_retry("GET", "u", t, sleep=lambda s: None)
    assert len(t.calls) == 3


def test_post_is_never_retried():
    t = flaky(1)
    with pytest.raises(TransientError):
        fetch_with_retry("POST", "u", t, sleep=lambda s: None)
    assert len(t.calls) == 1


def test_non_transient_errors_are_not_retried():
    calls = []

    def bad(m, u):
        calls.append(1)
        raise PermissionError()
    with pytest.raises(PermissionError):
        fetch_with_retry("GET", "u", bad, sleep=lambda s: None)
    assert len(calls) == 1
