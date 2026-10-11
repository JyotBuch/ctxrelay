"""Fail if graph accuracy or speed regressed below eval/thresholds.json.

usage: python eval/check_thresholds.py pytest nest      (after eval/graph_eval.py wrote eval/results/graph_<repo>.json)
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent


def metrics(path):
    d = json.loads(path.read_text())
    rows = d["rows"]
    unamb = [r for r in rows if not r["ambiguous"]]
    mean = lambda xs, k: sum(x[k] for x in xs) / len(xs) if xs else 0.0
    return {"recall": mean(rows, "recall"), "precision": mean(rows, "precision"),
            "f1_unambiguous": mean(unamb, "f1"), "build_seconds": d["build_seconds"], "n": len(rows)}


def main(repos):
    limits = json.loads((HERE / "thresholds.json").read_text())
    failed = False
    print(f"{'repo':<8}{'metric':<18}{'value':>9}{'limit':>9}  status")
    for repo in repos:
        m = metrics(HERE / "results" / f"graph_{repo}.json")
        if m["n"] < 40:
            print(f"{repo}: only {m['n']} scored symbols; the sample is too small to trust")
            failed = True
        for key, limit in limits[repo].items():
            name, kind = key.rsplit("_", 1)
            value = m[name]
            ok = value >= limit if kind == "min" else value <= limit
            failed |= not ok
            print(f"{repo:<8}{name:<18}{value:>9.2f}{limit:>9.2f}  {'ok' if ok else 'REGRESSION'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["pytest", "nest"]))
