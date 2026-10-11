from net.client import TransientError, fetch_with_retry


def test_success():
    assert fetch_with_retry("GET", "u", lambda m, u: "ok") == "ok"


def test_retries_transient():
    calls = []

    def flaky(m, u):
        calls.append(1)
        if len(calls) < 3:
            raise TransientError()
        return "ok"
    assert fetch_with_retry("GET", "u", flaky) == "ok"
