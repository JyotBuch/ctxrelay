"""Eval 1: graph speed and accuracy against independent ground truth.

usage: python eval/graph_eval.py <repo-name> [--n 40] [--seed 1]
Ground truth is file-level: the set of files that reference a symbol, from jedi (Python) or the
TypeScript language service. Comparing at file level avoids depending on ctxrelay's own
enclosing-symbol logic. Defining file is excluded on both sides.
"""
import argparse
import json
import os
import random
import resource
import subprocess
import sys
import time
from pathlib import Path

import tomllib

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from ctxrelay import graph, state  # noqa: E402

NON_SOURCE_DIRS = {"test", "tests", "testing", "doc", "docs", "bench", "benchmarks", "scripts", "extra", "example",
                   "examples", "sample", "samples", "e2e", "integration", "fixtures", "scratch"}


def is_test(path):
    """True for tests, docs, examples and tooling: we only score library source symbols."""
    parts = Path(path).parts
    name = parts[-1].lower()
    return (bool(NON_SOURCE_DIRS & {p.lower() for p in parts[:-1]})
            or name.startswith(("test_", "conftest")) or any(s in name for s in (".spec.", ".test.", "_test.")))


def word_file_counts(con, root):
    """name -> number of files containing it as a word. Independent of the graph's edges, so sampling is stable."""
    import re
    from collections import Counter
    c = Counter()
    for (f,) in con.execute("SELECT path FROM files"):
        c.update(set(re.findall(r"[A-Za-z_]\w{2,}", (root / f).read_text(errors="ignore"))))
    return c


def sample(con, n, rnd, root):
    """Stratified: hubs, mid, leaves; unique-name and ambiguous-name symbols."""
    rows = con.execute(
        """SELECT s.id,s.name,s.file,s.line,s.kind,
                  0, (SELECT COUNT(*) FROM symbols t WHERE t.name=s.name)
           FROM symbols s WHERE s.kind IN ('class','function','def','func','fn','interface')
           ORDER BY s.file, s.line""").fetchall()
    wc = word_file_counts(con, root)
    rows = [(*r[:5], wc[r[1]], r[6]) for r in rows]
    cache = {}

    def top_level(r):
        # Methods and attributes are out: jedi/tsc can't type-infer dynamic receivers, so their ground truth
        # is incomplete and would flatter or punish us arbitrarily. Top-level defs resolve via imports.
        lines = cache.setdefault(r[2], (root / r[2]).read_text(errors="ignore").splitlines())
        return r[3] <= len(lines) and not lines[r[3] - 1][:1].isspace()

    rows = [r for r in rows if not is_test(r[2]) and len(r[1]) >= 4 and not r[1].startswith("__") and top_level(r)]
    rows.sort(key=lambda r: (-r[5], r[2], r[3]))
    tiers = {"hub": rows[: max(1, len(rows) // 20)],
             "mid": rows[len(rows) // 20: len(rows) // 3],
             "leaf": [r for r in rows[len(rows) // 3:] if r[5] > 1]}
    out = []
    for tier, pool in tiers.items():
        rnd.shuffle(pool)
        out += [(tier, *r) for r in pool[: n // 3]]
    return out


def python_truth(root, targets):
    import jedi
    extra = [str(root / "src")] if (root / "src").is_dir() else []  # src layouts need this or imports don't resolve
    proj = jedi.Project(str(root), added_sys_path=extra)
    res = {}
    for key, file, line, name in targets:
        src = (root / file).read_text(errors="ignore").splitlines()
        col = src[line - 1].find(name) if line - 1 < len(src) else -1
        if col < 0:
            res[key] = None
            continue
        try:
            refs = jedi.Script(path=str(root / file), project=proj).get_references(line, col)
        except Exception:
            res[key] = None
            continue
        rel = {os.path.relpath(r.module_path, root) for r in refs if r.module_path}
        res[key] = sorted(f for f in rel if not f.startswith(".."))  # drop site-packages copies
    return res


def ts_truth(root, targets, tmp):
    p = tmp / "targets.json"
    p.write_text(json.dumps([{"key": k, "file": f, "line": l, "name": n} for k, f, l, n in targets]))
    nm = os.environ.get("TS_NODE_PATH", "")
    out = subprocess.run(["node", str(HERE / "ts_refs.js"), str(root), str(p)], capture_output=True,
                         text=True, env={**os.environ, "NODE_PATH": nm})
    if out.returncode:
        sys.exit(out.stderr[-2000:])
    return json.loads(out.stdout)


def classify(root, file, name):
    """Why did we draw an edge into `file` that ground truth says is false? Look at how `name` appears there."""
    import re
    kinds = set()
    for line in (root / file).read_text(errors="ignore").splitlines():
        if name not in line:
            continue
        s = line.strip()
        if s.startswith(("#", "//", "*", "/*", '"""', "'''")):
            kinds.add("comment/docstring")
        elif re.search(r"\." + re.escape(name) + r"\b", line):
            kinds.add("attribute-access (x.%s)" % "name")
        elif re.search(r"([\"\'])[^\"\']*\b" + re.escape(name) + r"\b[^\"\']*\1", line):
            kinds.add("inside string")
        elif re.search(r"\b" + re.escape(name) + r"\b", line):
            kinds.add("bare identifier (collision/other binding)")
    return sorted(kinds) or ["substring only"]


def prf(pred, truth):
    pred, truth = set(pred), set(truth)
    tp = len(pred & truth)
    p = tp / len(pred) if pred else (1.0 if not truth else 0.0)
    r = tp / len(truth) if truth else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    cfg = next(r for r in tomllib.load(open(HERE / "repos.toml", "rb"))["repo"] if r["name"] == a.repo)
    root = (HERE / ".cache" / a.repo).resolve()
    os.chdir(root)  # graph.db lands in <repo>/.ctxrelay (git-ignored by our own .gitignore? local clone only)

    t0 = time.time()
    summary = graph.build(root)
    dt = time.time() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)  # bytes on macOS
    size = graph.db_path().stat().st_size / 1e6
    print(f"[{a.repo}] {summary}\n  build {dt:.1f}s, peak RSS {rss:.0f} MB, db {size:.1f} MB")

    con = graph.connect()
    picks = sample(con, a.n, random.Random(a.seed), root)
    targets = [(f"{s[1]}", s[3], s[4], s[2]) for s in picks]
    t0 = time.time()
    truth = python_truth(root, targets) if cfg["lang"] == "python" else ts_truth(root, targets, state.home())
    # Score only files the ground-truth tool could see (tsc's tsconfig may exclude e.g. integration/).
    scope = set(truth.pop("__scope", None) or [f for (f,) in con.execute("SELECT path FROM files")])
    print(f"  ground truth for {len(targets)} symbols in {time.time() - t0:.0f}s")

    rows = []
    for (tier, sid, name, file, line, kind, deps, same), (key, *_rest) in zip(picks, targets):
        t = truth.get(key)
        if t is None:
            continue
        ours = ({f for (f,) in con.execute(
            "SELECT DISTINCT s.file FROM edges e JOIN symbols s ON s.id=e.src WHERE e.dst=?", (sid,))} & scope) - {file}
        t = set(t) - {file}
        p, r, f1 = prf(ours, t)
        rows.append({"tier": tier, "name": name, "file": file, "ambiguous": same > 1, "n_ours": len(ours),
                     "n_truth": len(t), "precision": p, "recall": r, "f1": f1,
                     "false_kinds": [classify(root, f, name) for f in sorted(ours - t)[:10]],
                     "false_files": sorted(ours - t)[:5], "missed_files": sorted(t - ours)[:5]})

    def agg(sel, label):
        sel = list(sel)
        if sel:
            m = lambda k: sum(x[k] for x in sel) / len(sel)
            print(f"  {label:<22} n={len(sel):<3} P={m('precision'):.2f} R={m('recall'):.2f} F1={m('f1'):.2f}")
    print("  callers (file-level) vs ground truth:")
    agg(rows, "all")
    agg((x for x in rows if not x["ambiguous"]), "unambiguous names")
    agg((x for x in rows if x["ambiguous"]), "ambiguous names")
    for tier in ("hub", "mid", "leaf"):
        agg((x for x in rows if x["tier"] == tier), f"tier={tier}")
    from collections import Counter
    tax = Counter(k for x in rows for ks in x["false_kinds"] for k in ks)
    if tax:
        print("  false-edge taxonomy (sampled, a file can match several):", dict(tax.most_common()))
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    (out / f"graph_{a.repo}.json").write_text(json.dumps(
        {"repo": cfg, "build_seconds": dt, "peak_rss_mb": rss, "db_mb": size, "summary": summary, "rows": rows}, indent=1))


main()
