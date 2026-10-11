import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("bench", Path(__file__).resolve().parents[1] / "eval" / "bench" / "bench.py")
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)


def test_every_task_is_a_valid_experiment(tmp_path, monkeypatch):
    """Interrupted state fails hidden tests, reference solution passes, the naive 'trap' fix fails them."""
    monkeypatch.setattr(bench, "WORK", tmp_path)
    assert bench.validate() == []


def test_stub_run_covers_all_conditions(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, "WORK", tmp_path / "w")
    monkeypatch.setattr(bench, "OUT", tmp_path / "out")
    rows = [bench.run_one("stub", "stale_cache", c, 0) for c in bench.CONDS]
    assert all(r["success"] for r in rows)
    assert "stale_cache | C3 | 1 | 1/1" in bench.summarize(rows)
