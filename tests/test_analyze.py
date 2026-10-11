import importlib.util
import math
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("analyze", Path(__file__).resolve().parents[1] / "eval" / "bench" / "analyze.py")
an = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(an)


def test_fisher_known_values():
    assert math.isclose(an.fisher(1, 0, 0, 1), 1.0)
    assert math.isclose(an.fisher(3, 0, 0, 3), 0.1, rel_tol=1e-6)       # classic 3/3 vs 0/3
    assert math.isclose(an.fisher(8, 2, 1, 5), 0.0350, abs_tol=0.001)    # textbook example (p = 0.035)


def test_wilson_bounds():
    lo, hi = an.wilson(4, 4)
    assert 0.5 < lo < 1.0 and hi == 1.0
    assert an.wilson(0, 0) == (0.0, 1.0)


def test_rule_one_triggers_when_graph_adds_nothing():
    rows = [{"cond": c, "success": True, "tool_calls": t, "uncached_tokens": u, "wall_s": 1, "task": "x"}
            for c, t, u in (("C3", 10, 9000), ("C4", 9, 5000)) for _ in range(3)]
    assert "RULE 1 TRIGGERED" in an.report(rows, rule=True)
