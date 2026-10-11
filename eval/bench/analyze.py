"""Statistics for benchmark result dirs (stdlib only): success rates with Wilson intervals, Fisher exact tests between
conditions, bootstrap intervals for cost ratios, and the pre-registered decision rule from PREREGISTRATION.md.

usage: python eval/bench/analyze.py eval/results/bench_v3_big [--tasks a,b] [--rule]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def fisher(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact p for [[a, b], [c, d]] (a,c = successes of group 1,2; b,d = failures)."""
    n1, n2, k = a + b, c + d, a + c
    total = math.comb(n1 + n2, k)

    def pr(x: int) -> float:
        return math.comb(n1, x) * math.comb(n2, k - x) / total
    p_obs = pr(a)
    lo, hi = max(0, k - n2), min(n1, k)
    return min(1.0, sum(pr(x) for x in range(lo, hi + 1) if pr(x) <= p_obs + 1e-12))


def boot_ratio(x: list[float], y: list[float], iters: int = 5000, seed: int = 0) -> tuple[float, float, float]:
    """Median(x)/median(y) with a 95% bootstrap interval."""
    rng = random.Random(seed)
    if not x or not y or statistics.median(y) == 0:
        return (float("nan"),) * 3
    rs = []
    for _ in range(iters):
        bx = [rng.choice(x) for _ in x]
        by = [rng.choice(y) for _ in y]
        m = statistics.median(by)
        if m:
            rs.append(statistics.median(bx) / m)
    rs.sort()
    return statistics.median(x) / statistics.median(y), rs[int(0.025 * len(rs))], rs[int(0.975 * len(rs))]


def load(dirs: list[str], tasks: set[str]) -> list[dict]:
    rows = []
    for d in dirs:
        for f in sorted(Path(d).glob("*.json")):
            r = json.loads(f.read_text())
            if "cond" in r and (not tasks or r["task"] in tasks):
                rows.append(r)
    return rows


def vals(rows, cond, key):
    return [r[key] for r in rows if r["cond"] == cond and isinstance(r.get(key), (int, float))]


def report(rows: list[dict], rule: bool) -> str:
    conds = sorted({r["cond"] for r in rows})
    out = ["condition | runs | success (95% Wilson) | median tool calls | median uncached tok | median wall s"]
    succ = {}
    for c in conds:
        g = [r for r in rows if r["cond"] == c]
        k = sum(r["success"] for r in g)
        succ[c] = (k, len(g))
        lo, hi = wilson(k, len(g))
        med = lambda key, c=c: round(statistics.median(vals(rows, c, key)), 1) if vals(rows, c, key) else "-"
        out.append(f"{c} | {len(g)} | {k}/{len(g)} ({lo:.2f}-{hi:.2f}) | {med('tool_calls')} | {med('uncached_tokens')} | {med('wall_s')}")
    out.append("\nsuccess, Fisher exact two-sided p (small samples: treat p>0.05 as 'no detectable difference')")
    for i, a in enumerate(conds):
        for b in conds[i + 1:]:
            (ka, na), (kb, nb) = succ[a], succ[b]
            out.append(f"{a} vs {b}: {ka}/{na} vs {kb}/{nb}  p={fisher(ka, na - ka, kb, nb - kb):.3f}")
    if "C3" in conds and "C4" in conds:
        out.append("\ncost ratio C3/C4, median with 95% bootstrap interval")
        for key in ("tool_calls", "uncached_tokens", "wall_s"):
            m, lo, hi = boot_ratio(vals(rows, "C3", key), vals(rows, "C4", key))
            out.append(f"{key}: {m:.2f}x ({lo:.2f}-{hi:.2f})")
    if rule and "C3" in succ and "C4" in succ:
        (k3, n3), (k4, n4) = succ["C3"], succ["C4"]
        tc, _, _ = boot_ratio(vals(rows, "C3", "tool_calls"), vals(rows, "C4", "tool_calls"))
        ut, _, _ = boot_ratio(vals(rows, "C3", "uncached_tokens"), vals(rows, "C4", "uncached_tokens"))
        better_success = k3 / n3 > k4 / n4
        fewer_calls = tc <= 0.75
        out.append("\npre-registered rule (eval/bench/PREREGISTRATION.md)")
        if not better_success and not fewer_calls:
            out.append("RULE 1 TRIGGERED: C3 neither succeeds more often nor uses >=25% fewer tool calls than C4 -> "
                       "MCP/graph not shown to help; demote to optional.")
        elif ut > 1.5:
            out.append(f"RULE 2: C3 helps on {'success' if better_success else 'tool calls'} but costs {ut:.2f}x uncached tokens -> trade-off.")
        else:
            out.append("C3 beats C4 on the registered criteria without the token penalty.")
        if "C0" in succ and max(succ["C3"][0] / succ["C3"][1], succ["C4"][0] / succ["C4"][1]) <= succ["C0"][0] / succ["C0"][1]:
            out.append("RULE 3: handoffs are not better than cold start here; benchmark has not shown they help on large repos.")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--rule", action="store_true")
    a = ap.parse_args()
    print(report(load(a.dirs, set(filter(None, a.tasks.split(",")))), a.rule))


if __name__ == "__main__":
    main()
