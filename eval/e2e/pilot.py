"""Eval 3 pilot: does a ctxrelay handoff help a *different* model finish an interrupted task?

Stage A: Claude Code starts the task on a fresh copy of a pinned repo and is cut off by a turn cap, recording notes
         through ctxrelay's MCP tool. The interrupted working tree and notes are snapshotted once per task.
Stage B: Codex continues from identical copies of that snapshot under three conditions:
    C0 cold      the user re-states the task; nothing else
    C1 git       C0 plus `git status` / `git diff --stat` pasted in
    C3 ctxrelay  short prompt pointing at the generated handoff; ctxrelay AGENTS.md rules + MCP graph tools
Success is decided by an automatic check (no leftovers, definition present, tests pass, no collateral edits).

usage: python eval/e2e/pilot.py [--stub] [--tasks t1,t2] [--conds C0,C1,C3] [--turns 6] [--stage-a-only]
Env: E2E_WORK (scratch dir for working copies; default eval/.cache/e2e)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "eval" / ".cache" / "pytest"
WORK = Path(os.environ.get("E2E_WORK", ROOT / "eval" / ".cache" / "e2e"))
OUT = ROOT / "eval" / "results" / "e2e"
BIN = Path(sys.executable).parent  # venv with ctxrelay installed
IGNORED = ("src/_pytest/_version.py", "AGENTS.md", "CLAUDE.md", "GEMINI.md", ".ctxrelay", ".mcp", "mcp.json",
           "__pycache__", ".pytest_cache")

TASKS = {
    "move_fnmatch": dict(
        symbol="fnmatch_ex", old_mod="_pytest.pathlib", old_file="src/_pytest/pathlib.py",
        new_mod="_pytest._globmatch", new_file="src/_pytest/_globmatch.py",
        tests=["testing/test_pathlib.py", "-k", "fnmatch"],
        statement=("Move the function `fnmatch_ex` out of src/_pytest/pathlib.py into a new module "
                   "src/_pytest/_globmatch.py (module name `_pytest._globmatch`). Update every import and use of it in src/ "
                   "and testing/ so each file imports it from `_pytest._globmatch`. Do NOT leave a re-export or alias in "
                   "pathlib.py. Don't touch other files or change behavior.")),
    "move_abspath": dict(
        symbol="absolutepath", old_mod="_pytest.pathlib", old_file="src/_pytest/pathlib.py",
        new_mod="_pytest._abspath", new_file="src/_pytest/_abspath.py",
        tests=["testing/test_config.py", "-x", "-q"],
        statement=("Move the function `absolutepath` out of src/_pytest/pathlib.py into a new module "
                   "src/_pytest/_abspath.py (module name `_pytest._abspath`). Update every import and use of it in src/ "
                   "and testing/ so each file imports it from `_pytest._abspath`. Do NOT leave a re-export or alias in "
                   "pathlib.py. Don't touch other files or change behavior.")),
}
CONDS = ("C0", "C1", "C3")


def sh(cmd, cwd, timeout=120, env=None, **kw):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "PATH": f"{BIN}:{os.environ['PATH']}", **(env or {})}, **kw)


def word_files(work, word):
    pat = re.compile(rf"\b{re.escape(word)}\b")
    return sorted(str(p.relative_to(work)) for d in ("src", "testing") for p in (work / d).rglob("*.py")
                  if pat.search(p.read_text(errors="ignore")))


def fresh_copy(dest):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(CACHE, dest, symlinks=True, ignore=shutil.ignore_patterns(".ctxrelay", "__pycache__", ".pytest_cache"))
    return dest


def changed_files(work):
    out = sh(["git", "status", "--porcelain", "-uall"], work).stdout.splitlines()
    return sorted(l[3:] for l in out if not any(i in l[3:] for i in IGNORED))


def imported_from(tree, module):
    """Names a file imports from `module` (absolute `from _pytest.x import n`, or relative `from .x import n`)."""
    import ast
    short = module.split(".")[-1]
    names = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and (n.module == module or (n.level and n.module == short)):
            names |= {a.name for a in n.names}
    return names


def check(task, work, expected):
    import ast
    sym = task["symbol"]
    new_path = work / task["new_file"]
    defined_new = new_path.exists() and re.search(rf"^def {sym}\b", new_path.read_text(), re.M) is not None
    defined_old = re.search(rf"^def {sym}\b", (work / task["old_file"]).read_text(), re.M) is not None
    bad = []
    for f in expected:
        if f in (task["old_file"], task["new_file"]):
            continue
        src = (work / f).read_text(errors="ignore")
        if not re.search(rf"\b{sym}\b", src):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            bad.append(f + " (syntax error)")
            continue
        if sym not in imported_from(tree, task["new_mod"]) or sym in imported_from(tree, task["old_mod"]):
            bad.append(f)
    allowed = set(expected) | {task["new_file"]}
    collateral = [f for f in changed_files(work) if f not in allowed]
    imp = sh([sys.executable, "-c", "import _pytest.config, _pytest.main, _pytest.doctest, _pytest.python, _pytest.terminal"],
             work, 120, env={"PYTHONPATH": str(work / "src")})
    tests = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *task["tests"]], work, 600,
               env={"PYTHONPATH": str(work / "src")})
    ok = (defined_new and not defined_old and not bad and not collateral and imp.returncode == 0 and tests.returncode == 0)
    return dict(success=ok, defined_in_new_module=bool(defined_new), still_defined_in_old=bool(defined_old),
                files_with_wrong_imports=bad, collateral=collateral, imports_ok=imp.returncode == 0,
                tests_pass=tests.returncode == 0, tests_tail=tests.stdout.strip().splitlines()[-1:] if tests.stdout else [])


def apply_move(task, work, files):
    """Stub helper: perform the move in `files` (defining file first creates the new module)."""
    sym = task["symbol"]
    old = (work / task["old_file"]).read_text()
    m = re.search(rf"^def {sym}\b.*?(?=^def |\Z)", old, re.M | re.S)
    if m and not (work / task["new_file"]).exists():
        (work / task["new_file"]).write_text("from __future__ import annotations\nimport fnmatch\nimport os\nfrom os.path import sep\n"
                                              "from pathlib import Path, PurePath\nfrom posixpath import sep as posix_sep\nimport sys\n\n\n" + m.group(0).rstrip() + "\n")
        (work / task["old_file"]).write_text(old.replace(m.group(0), ""))
    for f in files:
        if f == task["old_file"]:
            continue
        p = work / f
        s = p.read_text()
        s = re.sub(rf"(from _pytest\.pathlib import ){sym}\n", rf"from {task['new_mod']} import {sym}\n", s)
        p.write_text(s)


def stage_a(name, task, turns, stub):
    a = fresh_copy(WORK / f"{name}_A")
    snap = OUT / f"{name}_snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    expected = word_files(a, task["symbol"])
    sh(["ctxrelay", "init"], a)
    (a / "mcp.json").write_text(json.dumps({"mcpServers": {"ctxrelay": {"command": str(BIN / "ctxrelay"), "args": ["serve"]}}}))
    prompt = (task["statement"] + "\n\nYou are on a tight budget and may be cut off at any moment. First record the goal with "
              "the ctxrelay handoff_note tool, then record constraints, decisions, rejected options and next steps as you go.")
    t0 = time.time()
    if stub:  # simulate being cut off: finish only the definition and one caller file
        apply_move(task, a, expected[:3])
        sh(["ctxrelay", "note", "goal", task["statement"]], a)
        sh(["ctxrelay", "note", "constraint", "No re-export or alias in pathlib.py."], a)
        sh(["ctxrelay", "note", "next", f"Update remaining imports of {task['symbol']}."], a)
        raw = {"stub": True}
    else:
        r = sh(["claude", "-p", prompt, "--mcp-config", "mcp.json", "--strict-mcp-config", "--permission-mode", "acceptEdits",
                "--allowedTools", "Read,Edit,Write,Grep,Glob,mcp__ctxrelay,Bash(grep:*),Bash(sed:*),Bash(git:*),Bash(ls:*)",
                "--max-turns", str(turns), "--output-format", "json"], a, 900, stdin=subprocess.DEVNULL)
        try:
            raw = json.loads(r.stdout)
        except json.JSONDecodeError:
            raw = {"unparsed": r.stdout[-2000:], "stderr": r.stderr[-1000:]}
    dt = time.time() - t0
    sh(["git", "add", "-A", "--", ".", *[f":!{i}" for i in IGNORED]], a)
    (snap / "interrupted.patch").write_text(sh(["git", "diff", "--cached"], a).stdout)
    shutil.copy(a / ".ctxrelay" / "state.json", snap / "state.json")
    sh(["git", "reset", "-q"], a)
    chk = check(task, a, expected)
    info = dict(expected_files=expected, wall_s=dt, stage_a_raw=raw, interrupted_check=chk,
                notes=json.loads((snap / "state.json").read_text()))
    (snap / "stage_a.json").write_text(json.dumps(info, indent=1))
    return info


def parse_codex(jsonl):
    ev = [json.loads(l) for l in jsonl.splitlines() if l.startswith("{")]
    items = [e["item"] for e in ev if e.get("type") == "item.completed"]
    usage = next((e["usage"] for e in reversed(ev) if e.get("type") == "turn.completed"), {})
    kinds = [i["type"] for i in items]
    first_edit = next((n for n, k in enumerate(kinds) if k == "file_change"), None)
    return dict(input_tokens=usage.get("input_tokens"), cached_input_tokens=usage.get("cached_input_tokens"),
                output_tokens=usage.get("output_tokens"), commands=kinds.count("command_execution"),
                mcp_calls=kinds.count("mcp_tool_call"), file_changes=kinds.count("file_change"),
                steps_before_first_edit=first_edit, errors=[e for e in ev if e.get("type") == "error"][:3])


def stage_b(name, task, cond, expected, stub):
    snap = OUT / f"{name}_snapshot"
    w = fresh_copy(WORK / f"{name}_{cond}")
    sh(["git", "apply", str(snap / "interrupted.patch")], w)
    codex_cfg = []
    if cond == "C3":
        (w / ".ctxrelay").mkdir()
        shutil.copy(snap / "state.json", w / ".ctxrelay" / "state.json")
        sh(["ctxrelay", "init"], w)  # AGENTS.md rules + graph index of the interrupted tree
        sh(["ctxrelay", "switch", "print"], w)  # writes .ctxrelay/HANDOFF.md
        prompt = ("You are continuing a task started in another session, possibly with a different model. Read "
                  ".ctxrelay/HANDOFF.md first, check it against the actual code, then continue from 'Next steps'. "
                  "Finish the task.")
        codex_cfg = ["-c", f'mcp_servers.ctxrelay.command="{BIN / "ctxrelay"}"', "-c", 'mcp_servers.ctxrelay.args=["serve"]',
                     "-c", 'mcp_servers.ctxrelay.default_tools_approval_mode="approve"']
    else:
        prompt = ("A previous session may have started this task and been interrupted, so the repository may contain "
                  "partial work. Finish the task.\n\nTask: " + task["statement"])
        if cond == "C1":
            prompt += ("\n\n`git status --short`:\n" + sh(["git", "status", "--short"], w).stdout +
                       "\n`git diff --stat`:\n" + sh(["git", "diff", "--stat"], w).stdout)
    t0 = time.time()
    if stub:
        apply_move(task, w, expected)
        metrics, raw = dict(stub=True), ""
    else:
        r = sh(["codex", "exec", "-C", str(w), "--skip-git-repo-check", "-s", "workspace-write", "--json", *codex_cfg, prompt],
               w, 900, stdin=subprocess.DEVNULL)
        raw, metrics = r.stdout, parse_codex(r.stdout)
    dt = time.time() - t0
    (OUT / f"{name}_{cond}.jsonl").write_text(raw)
    res = dict(task=name, cond=cond, wall_s=round(dt, 1), **metrics, **check(task, w, expected))
    (OUT / f"{name}_{cond}.json").write_text(json.dumps(res, indent=1))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stub", action="store_true")
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--conds", default=",".join(CONDS))
    ap.add_argument("--turns", type=int, default=6)
    ap.add_argument("--stage-a-only", action="store_true")
    ap.add_argument("--reuse-a", action="store_true", help="reuse existing snapshots")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    rows = []
    for name in a.tasks.split(","):
        task = TASKS[name]
        if a.reuse_a and (OUT / f"{name}_snapshot" / "stage_a.json").exists():
            info = json.loads((OUT / f"{name}_snapshot" / "stage_a.json").read_text())
        else:
            info = stage_a(name, task, a.turns, a.stub)
        ic = info["interrupted_check"]
        print(f"[{name}] stage A done in {info['wall_s']:.0f}s; interrupted state success={ic['success']} "
              f"(wrong/unmoved files: {len(ic['files_with_wrong_imports'])}, of {len(info['expected_files'])} expected)")
        if ic["success"] or not ic["defined_in_new_module"]:
            print(f"  WARNING: stage A {'finished the task' if ic['success'] else 'never created the new module'}; "
                  "not a valid interruption. Adjust --turns.")
            continue
        if a.stage_a_only:
            continue
        for cond in a.conds.split(","):
            r = stage_b(name, task, cond, info["expected_files"], a.stub)
            rows.append(r)
            print(f"  {cond}: success={r['success']} wall={r['wall_s']}s in={r.get('input_tokens')} out={r.get('output_tokens')} "
                  f"cmds={r.get('commands')} mcp={r.get('mcp_calls')} wrong_imports={len(r['files_with_wrong_imports'])} collateral={r['collateral']} tests={r['tests_pass']}")
    (OUT / "summary.json").write_text(json.dumps(rows, indent=1))


main()
