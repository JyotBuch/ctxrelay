"""Code graph in SQLite. Heuristic (name-based), not a compiler-grade resolver.

Definitions come from `ast` for Python and regexes for other languages.
Edges are drawn from identifier tokens that match a defined symbol name, so
comments, strings and same-named symbols can produce false edges. Names defined
in more than MAX_AMBIGUOUS places are skipped to keep the noise down.
"""
from __future__ import annotations

import ast
import io
import json
import re
import shutil
import sqlite3
import subprocess
import tokenize
from collections import Counter, defaultdict
from pathlib import Path

from . import state

EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb",
        ".c", ".h", ".cpp", ".cc", ".hpp", ".cs", ".php", ".kt", ".swift"}
SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
        "target", ".next", ".ctxrelay", "vendor"}
MAX_AMBIGUOUS = 5
MAX_FILE_BYTES = 1_000_000
DEF_RE = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:pub(?:\([^)]*\))?\s+)?(?:(?:public|private|protected|static|final|abstract|async|unsafe|extern)\s+)*"
    r"(function\*?|func|fn|def|class|struct|interface|enum|trait|type)\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)")
ARROW_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_]\w*)\s*=>")
TOKEN_RE = re.compile(r"(\.\s*)?([A-Za-z_]\w{2,})")
# comments and string literals, matched leftmost-first so quotes inside comments (and vice versa) are skipped
STRIP_RE = re.compile(r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`", re.S)
HASH_STRIP_RE = re.compile(r"#[^\n]*|\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'")

SCHEMA = """
DROP TABLE IF EXISTS symbols; DROP TABLE IF EXISTS edges; DROP TABLE IF EXISTS files;
CREATE TABLE files(path TEXT PRIMARY KEY, community INTEGER);
CREATE TABLE symbols(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, file TEXT, line INTEGER, method INTEGER);
CREATE TABLE edges(src INTEGER, dst INTEGER, PRIMARY KEY(src, dst));
CREATE INDEX sym_name ON symbols(name); CREATE INDEX edge_dst ON edges(dst);
"""


def db_path() -> Path:
    return state.home() / "graph.db"


def connect() -> sqlite3.Connection:
    return sqlite3.connect(db_path())


def _source_files(root: Path):
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=root,
                             capture_output=True, text=True, check=True).stdout.split("\n")
        paths = [root / p for p in out if p]
    except (OSError, subprocess.CalledProcessError):
        paths = [p for p in root.rglob("*") if p.is_file()]
    for p in sorted(paths):
        rel = p.relative_to(root)
        if (p.suffix in EXTS and not SKIP & set(rel.parts) and p.is_file()
                and p.stat().st_size <= MAX_FILE_BYTES):
            yield rel


def _defs(rel: Path, text: str):
    """Yield (name, kind, line, is_method). Methods are only reachable as `x.name`, other defs as bare `name`."""
    if rel.suffix == ".py":
        try:
            tree = ast.parse(text)
            for parent in ast.walk(tree):
                for n in ast.iter_child_nodes(parent):
                    in_class = isinstance(parent, ast.ClassDef)
                    if isinstance(n, ast.ClassDef):
                        yield n.name, "class", n.lineno, False
                    elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        yield n.name, "function", n.lineno, in_class
            return
        except SyntaxError:
            pass  # fall through to regex
    for i, line in enumerate(text.splitlines(), 1):
        indented = line[:1].isspace()
        m = DEF_RE.match(line)
        if m:
            yield m.group(2), m.group(1), i, indented
            continue
        m = ARROW_RE.match(line)
        if m:
            yield m.group(1), "function", i, indented


def _blank(m) -> str:
    return "\n" * m.group(0).count("\n")  # drop comment/string text but keep line numbers


def _tokens(rel: Path, text: str):
    """Yield (line, name, is_attr) for identifiers in code only, never in comments or strings."""
    if rel.suffix == ".py":
        try:
            prev = None
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.NAME and len(tok.string) >= 3:
                    yield tok.start[0], tok.string, prev is not None and prev.type == tokenize.OP and prev.string == "."
                if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT):
                    prev = tok
            return
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
    code = (HASH_STRIP_RE if rel.suffix in (".py", ".rb") else STRIP_RE).sub(_blank, text)
    for i, line in enumerate(code.splitlines(), 1):
        for m in TOKEN_RE.finditer(line):
            yield i, m.group(2), bool(m.group(1))


CACHE_SCHEMA = "CREATE TABLE IF NOT EXISTS parse_cache(path TEXT PRIMARY KEY, sig TEXT, defs TEXT, toks TEXT)"


def _sig(root: Path, rel: Path) -> str:
    st = (root / rel).stat()
    return f"{st.st_mtime_ns}:{st.st_size}"


def stale(root: Path) -> bool:
    """True if the index is missing or any source file was added, removed or modified since it was built."""
    if not db_path().exists():
        return True
    con = connect()
    try:
        cached = dict(con.execute("SELECT path, sig FROM parse_cache"))
    except sqlite3.OperationalError:
        return True
    finally:
        con.close()
    now = {str(rel): _sig(root, rel) for rel in _source_files(root)}
    return now != cached


def refresh(root: Path) -> str:
    """Rebuild only if something changed (unchanged files are not re-parsed). Returns a one-line status."""
    return build(root) if stale(root) else "index up to date"


def build(root: Path) -> str:
    """Rebuild the graph. Per-file parse results are cached by (mtime, size), so unchanged files are not re-parsed;
    edges and communities depend on every file's names, so they are always recomputed (cheap) to match a full build."""
    con = connect()
    con.execute(CACHE_SCHEMA)
    cache = {p: (sig, d, t) for p, sig, d, t in con.execute("SELECT path, sig, defs, toks FROM parse_cache")}
    parsed = {}  # rel -> (defs sorted by line, tokens by line)
    fresh = []
    for rel in _source_files(root):
        try:
            sig = _sig(root, rel)
            hit = cache.get(str(rel))
            if hit and hit[0] == sig:
                parsed[str(rel)] = ([tuple(d) for d in json.loads(hit[1])], [tuple(t) for t in json.loads(hit[2])])
                continue
            text = (root / rel).read_text(errors="ignore")
        except OSError:
            continue
        defs = sorted(set(_defs(rel, text)), key=lambda d: d[2])
        toks = list(_tokens(rel, text))
        parsed[str(rel)] = (defs, toks)
        fresh.append((str(rel), sig, json.dumps(defs), json.dumps(toks)))

    con.executescript(SCHEMA)
    con.execute("DELETE FROM parse_cache")
    fresh_paths = {f[0] for f in fresh}
    con.executemany("INSERT INTO parse_cache VALUES (?,?,?,?)",
                    fresh + [(p, *cache[p]) for p in parsed if p not in fresh_paths])
    by_name = defaultdict(list)
    method_of = {}
    per_file = {}
    for f, (defs, _) in parsed.items():
        con.execute("INSERT INTO files(path) VALUES (?)", (f,))
        ids = []
        for name, kind, line, is_method in defs:
            cur = con.execute("INSERT INTO symbols(name,kind,file,line,method) VALUES (?,?,?,?,?)",
                              (name, kind, f, line, int(is_method)))
            sid = cur.lastrowid
            assert sid is not None  # an INSERT always sets it
            method_of[sid] = is_method
            ids.append((line, sid))
            by_name[name].append(sid)
        per_file[f] = ids

    edges: set[tuple[int, int]] = set()
    for f, (defs, toks) in parsed.items():
        ids = per_file[f]
        starts = [d[0] for d in ids]
        local = {sid for _, sid in ids}
        for line, w, is_attr in toks:
            # enclosing symbol = last def starting at or before this line
            k = max((j for j, s in enumerate(starts) if s <= line), default=None)
            if k is None or (starts[k] == line and defs[k][0] == w):  # not in a def / the def's own name
                continue
            src = ids[k][1]
            # `x.name` may be a method or a module-qualified top-level def (`mod.func()`); a bare `name` can't be
            # a method, so it only links to top-level defs or local (nested) ones in this file
            targets = [t for t in by_name.get(w, ()) if is_attr or not method_of[t] or t in local]
            if 0 < len(targets) <= MAX_AMBIGUOUS:
                edges.update((src, t) for t in targets if t != src)
    con.executemany("INSERT INTO edges VALUES (?,?)", edges)

    # communities: label propagation over the file-level graph
    file_of = dict(con.execute("SELECT id, file FROM symbols"))
    nbrs: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for s, d in edges:
        a, b = file_of[s], file_of[d]
        if a != b:
            nbrs[a][b] += 1
            nbrs[b][a] += 1
    label = {f: f for f in parsed}
    for _ in range(20):
        changed = False
        for f in sorted(parsed):
            if not nbrs[f]:
                continue
            score: Counter[str] = Counter()
            for g, w in nbrs[f].items():
                score[label[g]] += w
            best = min(score, key=lambda lab: (-score[lab], lab))
            if best != label[f]:
                label[f], changed = best, True
        if not changed:
            break
    community_ids = {lab: i for i, lab in enumerate(sorted(set(label.values())), 1)}
    con.executemany("UPDATE files SET community=? WHERE path=?", [(community_ids[label[f]], f) for f in parsed])
    con.commit()
    con.close()
    return (f"indexed {len(parsed)} files ({len(fresh)} parsed), {len(file_of)} symbols, {len(edges)} edges, "
            f"{len(set(label.values()))} communities")


# ---- queries (all output is capped so results stay cheap in tokens) ----
LIMIT = 30


def _need_db():
    if not db_path().exists():
        raise RuntimeError("no index yet: run `ctxrelay index`")


def _fmt(rows, empty="(none)"):
    rows = list(rows)
    if not rows:
        return empty
    extra = f"\n… {len(rows) - LIMIT} more" if len(rows) > LIMIT else ""
    return "\n".join(f"{n} [{k}] {f}:{line}" for n, k, f, line in rows[:LIMIT]) + extra


def find(name: str) -> str:
    _need_db()
    return _fmt(connect().execute(
        "SELECT name,kind,file,line FROM symbols WHERE name LIKE ? ORDER BY name LIMIT 200", (f"%{name}%",)))


def callers(name: str) -> str:
    _need_db()
    return _fmt(connect().execute(
        """SELECT DISTINCT s.name,s.kind,s.file,s.line FROM edges e
           JOIN symbols s ON s.id=e.src JOIN symbols t ON t.id=e.dst WHERE t.name=?""", (name,)))


def callees(name: str) -> str:
    _need_db()
    return _fmt(connect().execute(
        """SELECT DISTINCT t.name,t.kind,t.file,t.line FROM edges e
           JOIN symbols s ON s.id=e.src JOIN symbols t ON t.id=e.dst WHERE s.name=?""", (name,)))


def impact(name: str, depth: int = 3) -> str:
    """Transitive callers: what could break if `name` changes."""
    _need_db()
    return _fmt(connect().execute(
        """WITH RECURSIVE r(id, d) AS (
             SELECT id, 0 FROM symbols WHERE name=?
             UNION SELECT e.src, r.d+1 FROM edges e JOIN r ON e.dst=r.id WHERE r.d < ?)
           SELECT s.name,s.kind,s.file,s.line FROM symbols s
           WHERE s.id IN (SELECT id FROM r WHERE d>0) ORDER BY s.file, s.line""", (name, depth)))


def community(num: int | None = None) -> str:
    _need_db()
    con = connect()
    if num is None:
        rows = con.execute(
            "SELECT community, COUNT(*), MIN(path) FROM files GROUP BY community ORDER BY 2 DESC").fetchall()
        out = []
        for c, n, _ in rows[:LIMIT]:
            paths = con.execute("SELECT path FROM files WHERE community=?", (c,))
            dirs = Counter(str(Path(p).parent) for (p,) in paths)
            out.append(f"community {c}: {n} files, mostly {dirs.most_common(1)[0][0]}/")
        return "\n".join(out) or "(empty)"
    files = [p for (p,) in con.execute("SELECT path FROM files WHERE community=? ORDER BY path", (num,))]
    if not files:
        return "(none)"
    return "\n".join(files[:LIMIT]) + (f"\n… {len(files) - LIMIT} more" if len(files) > LIMIT else "")


def hubs() -> str:
    """Most-depended-on symbols: where a change ripples furthest."""
    _need_db()
    rows = connect().execute(
        """SELECT s.name,s.kind,s.file,s.line,COUNT(*) c FROM edges e JOIN symbols s ON s.id=e.dst
           GROUP BY s.id ORDER BY c DESC LIMIT ?""", (LIMIT,)).fetchall()
    return "\n".join(f"{n} [{k}] {f}:{line}  ← {c} dependents" for n, k, f, line, c in rows) or "(none)"


def file_summary(path: str) -> str:
    _need_db()
    con = connect()
    syms = con.execute("SELECT name,kind,file,line FROM symbols WHERE file=? ORDER BY line", (path,)).fetchall()
    return _fmt(syms, "(file not indexed)")


def search(query: str, k: int = 10) -> str:
    """Find code by description. Delegates to colgrep (https://github.com/lightonai/next-plaid) when installed:
    in our eval it found the right file far more often than name matching does (see eval/RESULTS.md)."""
    exe = shutil.which("colgrep")
    if not exe:
        raise RuntimeError("semantic search needs colgrep (brew install lightonai/tap/colgrep). "
                           "Without it, use `find` for name matches or grep.")
    out = subprocess.run([exe, "-k", str(k), query], cwd=state.root(), capture_output=True, text=True)
    if out.returncode:
        err = out.stderr.strip()[-300:]
        hint = ""
        if "401" in out.stderr:
            hint = " A stale Hugging Face token can cause this: retry with HF_HOME set to an empty directory."
        raise RuntimeError(f"colgrep failed: {err}{hint}")
    lines = out.stdout.strip().splitlines()
    if not lines:
        return "(no results)"
    return "\n".join(lines[:LIMIT]) + (f"\n… {len(lines) - LIMIT} more" if len(lines) > LIMIT else "")
