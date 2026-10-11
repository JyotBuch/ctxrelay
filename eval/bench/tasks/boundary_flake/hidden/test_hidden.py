from syncer.expiry import is_expired


def test_fraction_boundaries():
    assert is_expired(100.9, 10, now=110.95)      # 10.05s elapsed
    assert not is_expired(100.9, 10, now=110.85)  # 9.95s elapsed
    assert not is_expired(100.0, 10, now=110.0)   # exactly ttl is not expired
    assert is_expired(100.0, 10, now=110.01)


def test_no_retry_hack_in_tests():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "tests" / "test_expiry.py").read_text()
    assert "retry" not in src
