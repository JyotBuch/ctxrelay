"""Compare colgrep with ctxrelay's graph (and plain baselines) on the pinned pytest repo, src/ only.

  python eval/colgrep_eval.py make-queries   # one `claude -p` call paraphrases docstrings into search intents
  python eval/colgrep_eval.py discovery      # find the code from a natural-language description
  python eval/colgrep_eval.py structure      # callers of a symbol vs jedi ground truth
Needs colgrep on PATH, and HF_HOME pointing at a clean dir if a stale Hugging Face token gives 401s.
"""
import ast
import json
import math
import os
import random
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
REPO = (HERE / ".cache" / "pytest").resolve()
SRC = REPO / "src"
RES = HERE / "results"
QUERIES = RES / "colgrep_queries.json"
STOP = set("the a an of to in for and or with from that this is are be by on as at it its into when which not if "
           "using use used given each any all can will should".split())


def src_files():
    return sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py") if "_version" not in p.name)


def colgrep(query, k=10):
    out = subprocess.run(["colgrep", "--json", "-k", str(k), query, "src"], cwd=REPO, capture_output=True, text=True)
    if out.returncode:
        sys.exit(f"colgrep failed: {out.stderr[-500:]}")
    return json.loads(out.stdout or "[]")


def rel(f):
    return f.split("/src/", 1)[-1] if "/src/" in f else f


def candidates(n, seed=7):
    """Top-level defs in src/ with a real docstring and a name unique in src."""
    names = Counter()
    found = []
    for f in src_files():
        tree = ast.parse((SRC / f).read_text(errors="ignore"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names[node.name] += 1
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node)
                if doc and len(doc) >= 60 and len(node.name) >= 5 and not node.name.startswith("_"):
                    found.append(dict(name=node.name, file=f, doc=doc[:400]))
    found = [c for c in found if names[c["name"]] == 1]
    random.Random(seed).shuffle(found)
    return found[:n]


def make_queries():
    cands = candidates(50)
    prompt = ("For each item below, write ONE short search request (5-14 words) that a developer who does not know the "
              "code might type into a code search tool to find it. Describe what it does or what problem it solves. "
              "Do NOT use the function/class name or any of its words, and do not copy phrases from the docstring. "
              "Reply with ONLY a JSON object mapping each name to its request.\n\n" +
              "\n".join(f"- {c['name']}: {c['doc'][:300]!r}" for c in cands))
    out = subprocess.run(["claude", "-p", prompt, "--max-turns", "1", "--output-format", "json"], capture_output=True,
                         text=True, stdin=subprocess.DEVNULL)
    text = json.loads(out.stdout)["result"]
    m = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
    for c in cands:
        c["query"] = m.get(c["name"])
    cands = [c for c in cands if c["query"]]
    RES.mkdir(exist_ok=True)
    QUERIES.write_text(json.dumps(cands, indent=1))
    print(f"{len(cands)} queries written to {QUERIES}")


def words(q):
    return [w for w in re.findall(r"[a-z]{3,}", q.lower()) if w not in STOP]


def bm25_rank(files_text, q, k1=1.5, b=0.75):
    docs = {f: Counter(re.findall(r"[a-z]{3,}", t.lower())) for f, t in files_text.items()}
    lens = {f: sum(d.values()) for f, d in docs.items()}
    avg = sum(lens.values()) / len(lens)
    df = Counter(w for d in docs.values() for w in d)
    N = len(docs)
    score = {}
    for f, d in docs.items():
        s = 0.0
        for w in set(words(q)):
            if w in d:
                s += math.log(1 + (N - df[w] + 0.5) / (df[w] + 0.5)) * d[w] * (k1 + 1) / (d[w] + k1 * (1 - b + b * lens[f] / avg))
        score[f] = s
    return [f for f, s in sorted(score.items(), key=lambda x: -x[1]) if s > 0]


def graph_find_rank(con, q):
    """ctxrelay's only name-based discovery: symbols whose NAME contains a query word; files ranked by words matched."""
    hits = Counter()
    for w in set(words(q)):
        if len(w) < 4:
            continue
        for (f,) in con.execute("SELECT DISTINCT file FROM symbols WHERE lower(name) LIKE ? AND file LIKE 'src/%'", (f"%{w}%",)):
            hits[f[4:]] += 1
    return [f for f, _ in hits.most_common()]


def discovery():
    qs = json.loads(QUERIES.read_text())
    import sqlite3
    con = sqlite3.connect(REPO / ".ctxrelay" / "graph.db")
    text = {f: (SRC / f).read_text(errors="ignore") for f in src_files()}
    systems = {"colgrep": [], "colgrep (symbol-level)": [], "BM25 over files": [], "ctxrelay graph find": []}
    for c in qs:
        res = colgrep(c["query"], 10)
        files = []
        for r in res:
            f = rel(r["unit"]["file"])
            if f not in files:
                files.append(f)
        sym_rank = next((i for i, r in enumerate(res) if r["unit"]["name"] == c["name"]), None)
        for name, ranked in (("colgrep", files), ("BM25 over files", bm25_rank(text, c["query"])),
                             ("ctxrelay graph find", graph_find_rank(con, c["query"]))):
            systems[name].append(ranked.index(c["file"]) if c["file"] in ranked else None)
        systems["colgrep (symbol-level)"].append(sym_rank)
    n = len(qs)
    print(f"discovery: {n} paraphrased queries over {len(src_files())} src files (target = file defining the symbol)")
    print(f"{'system':<26}{'hit@1':>7}{'hit@3':>7}{'hit@5':>7}{'hit@10':>8}{'MRR':>7}")
    out = {}
    for name, ranks in systems.items():
        h = lambda k: sum(r is not None and r < k for r in ranks) / n
        mrr = sum(1 / (r + 1) for r in ranks if r is not None) / n
        print(f"{name:<26}{h(1):>7.2f}{h(3):>7.2f}{h(5):>7.2f}{h(10):>8.2f}{mrr:>7.2f}")
        out[name] = dict(h1=h(1), h3=h(3), h5=h(5), h10=h(10), mrr=mrr)
    (RES / "colgrep_discovery.json").write_text(json.dumps(dict(n=n, systems=out, queries=qs, ranks=systems), indent=1))


def prf(pred, truth):
    pred, truth = set(pred), set(truth)
    tp = len(pred & truth)
    p = tp / len(pred) if pred else (1.0 if not truth else 0.0)
    r = tp / len(truth) if truth else 1.0
    return p, r, (2 * p * r / (p + r) if p + r else 0.0)


def structure():
    import sqlite3
    import jedi
    con = sqlite3.connect(REPO / ".ctxrelay" / "graph.db")
    rows = json.loads((RES / "graph_pytest.json").read_text())["rows"]
    proj = jedi.Project(str(REPO), added_sys_path=[str(SRC)])
    srcset = {f"src/{f}" for f in src_files()}
    names_to_files = {}
    for n, f in con.execute("SELECT name, file FROM symbols WHERE file LIKE 'src/%'"):
        names_to_files.setdefault(n, set()).add(f)
    word_re = lambda w: re.compile(rf"\b{re.escape(w)}\b")
    tot = {k: [] for k in ("colgrep called_by", "ctxrelay graph", "plain grep -w")}
    for r in rows:
        name, file = r["name"], r["file"]
        if file not in srcset:
            continue
        line = con.execute("SELECT line, id FROM symbols WHERE name=? AND file=?", (name, file)).fetchone()
        if not line:
            continue
        src = (REPO / file).read_text(errors="ignore").splitlines()
        col = src[line[0] - 1].find(name)
        try:
            refs = jedi.Script(path=str(REPO / file), project=proj).get_references(line[0], col)
        except Exception:
            continue
        truth = {os.path.relpath(x.module_path, REPO) for x in refs if x.module_path} & srcset
        truth.discard(file)
        res = colgrep(name, 10)
        unit = next((x["unit"] for x in res if x["unit"]["name"] == name and rel(x["unit"]["file"]) == file[4:]), None)
        cg = set()
        for caller in (unit or {}).get("called_by", []):
            cg |= names_to_files.get(caller, set())
        cg.discard(file)
        ours = {f for (f,) in con.execute("SELECT DISTINCT s.file FROM edges e JOIN symbols s ON s.id=e.src WHERE e.dst=?", (line[1],))}
        ours = (ours & srcset) - {file}
        pat = word_re(name)
        grep = {f for f in srcset if f != file and pat.search((REPO / f).read_text(errors="ignore"))}
        for k, pred in (("colgrep called_by", cg), ("ctxrelay graph", ours), ("plain grep -w", grep)):
            tot[k].append(prf(pred, truth) + (unit is not None,))
    n = len(tot["ctxrelay graph"])
    print(f"structure: callers (file-level, src/ only) vs jedi for {n} symbols from the Eval 1 sample")
    print(f"{'system':<22}{'precision':>10}{'recall':>8}{'F1':>7}   notes")
    out = {}
    for k, v in tot.items():
        m = lambda i: sum(x[i] for x in v) / len(v)
        note = f"symbol found by colgrep in {sum(x[3] for x in v)}/{len(v)}" if k.startswith("colgrep") else ""
        print(f"{k:<22}{m(0):>10.2f}{m(1):>8.2f}{m(2):>7.2f}   {note}")
        out[k] = dict(precision=m(0), recall=m(1), f1=m(2))
    (RES / "colgrep_structure.json").write_text(json.dumps(dict(n=n, systems=out), indent=1))


if __name__ == "__main__":
    {"make-queries": make_queries, "discovery": discovery, "structure": structure}[sys.argv[1]]()
