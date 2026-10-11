"""Eval 3: does a handoff help a different model finish an interrupted task?

Each task (eval/bench/tasks/<name>) is a tiny Python repo with a *scripted* interruption: the working tree holds partial
work (the `interrupted` overlay) and the notes/events a previous session would have left. Hidden tests decide success.
Conditions, all starting from identical working trees:
  C0 cold      the task statement only
  C1 git       C0 + `git status` / `git diff --stat` (AGENTS.md exists in every condition)
  C2 naive     a generated HANDOFF.md: prose summary of the previous session + full `git diff` + last commands
  C3 ctxrelay  the real ctxrelay handoff (notes + captured events + git + graph) and MCP tools
  C4 file only the same ctxrelay handoff file, but no MCP server and no ctxrelay rules in AGENTS.md
LIMITATION: the previous session is scripted, so C2 and C3 get the same facts; this isolates how the information is
delivered (structure, graph, tools), not whether a real agent would have recorded it. Tasks are small and Python-only.

usage: python eval/bench/bench.py --validate | --agent codex|claude|stub [--tasks a,b] [--conds C0,C1,C2,C3] [--reps N]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASKS = HERE / "tasks"
OUT = Path(os.environ.get("BENCH_OUT", HERE.parents[0] / "results" / "bench"))
WORK = Path(os.environ.get("BENCH_WORK", HERE.parents[0] / ".cache" / "bench"))
BIN = Path(sys.executable).parent
CONDS = ("C0", "C1", "C2", "C3", "C4")
NOISE = ("AGENTS.md", "CLAUDE.md", "GEMINI.md", ".ctxrelay", "HANDOFF.md", "mcp.json", "__pycache__", ".pytest_cache", "hidden")
GIT = ["git", "-c", "user.name=bench", "-c", "user.email=b@b"]


def sh(cmd, cwd, timeout=300, env=None, **kw):
    e = {**os.environ, "PATH": f"{BIN}:{os.environ['PATH']}", "PYTHONDONTWRITEBYTECODE": "1", **(env or {})}
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=e, **kw)


def load(name: str) -> dict:
    return json.loads((TASKS / name / "task.json").read_text())


def overlay(task: str, layer: str, dest: Path) -> list[str]:
    src = TASKS / task / layer
    files = []
    for p in sorted(src.rglob("*")):
        if p.is_file():
            rel = p.relative_to(src)
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(p, dest / rel)
            files.append(str(rel))
    return files


def make_work(task: str, cond: str, tag: str) -> Path:
    w = WORK / f"{task}_{cond}_{tag}"
    if w.exists():
        shutil.rmtree(w)
    repo = load(task).get("repo")
    if repo:  # a real pinned checkout from eval/.cache (see eval/fetch.sh), already a clean git repo
        shutil.copytree(HERE.parents[0] / ".cache" / repo, w, symlinks=True,
                        ignore=shutil.ignore_patterns(".ctxrelay", "__pycache__", ".pytest_cache"))
    else:
        w.mkdir(parents=True)
        overlay(task, "base", w)
        sh(["git", "init", "-q"], w)
        sh([*GIT, "add", "-A"], w)
        sh([*GIT, "commit", "-q", "-m", "base"], w)
    overlay(task, "interrupted", w)  # partial work stays uncommitted
    return w


def naive_handoff(t: dict, w: Path) -> str:
    cmds = "\n".join(f"- `{e['cmd']}` -> {'ok' if e['ok'] else 'FAILED'}" for e in t["events"] if e["kind"] == "test")
    return (f"# Handoff\n\n## Summary of the previous session\n{t['summary']}\n\n## Last commands\n{cmds or '(none)'}\n\n"
            f"## git diff\n```diff\n{sh(['git', 'diff'], w).stdout}```\n")


def setup(task: str, cond: str, w: Path) -> tuple[str, list[str]]:
    """Prepare the working tree for a condition; returns (prompt, extra codex -c args)."""
    t = load(task)
    hint = t.get("run_hint", "python -m pytest -q tests")
    base = ("A previous session may have started this task and been interrupted, so the repository may contain partial "
            f"work. Finish the task. Run `{hint}` when done.\n\nTask: " + t["statement"])
    if cond == "C0":
        return base, []
    if cond == "C1":
        return (base + "\n\n`git status --short`:\n" + sh(["git", "status", "--short"], w).stdout +
                "\n`git diff --stat`:\n" + sh(["git", "diff", "--stat"], w).stdout), []
    if cond == "C2":
        (w / "HANDOFF.md").write_text(naive_handoff(t, w))
        return ("You are continuing a task another session started. Read HANDOFF.md first, check it against the code, then "
                f"finish the task. Run `{hint}` when done.\n\nTask: " + t["statement"]), []
    # C3: real ctxrelay state, as the hooks and notes would have left it
    from ctxrelay import state
    cwd = os.getcwd()
    os.chdir(w)
    try:
        state.home()
        s = state.load()
        s.update(t["notes"])
        s["base_sha"] = state.git_head()
        state.save(s)
        with (w / ".ctxrelay" / "events.jsonl").open("w") as fh:
            for e in t["events"]:
                fh.write(json.dumps({"ts": "t", "src": "hook", **e}) + "\n")
    finally:
        os.chdir(cwd)
    if cond == "C4":
        sh(["ctxrelay", "switch", "print"], w)
        return ("You are continuing a task started in another session, possibly with a different model. Read "
                ".ctxrelay/HANDOFF.md first, check it against the actual code, then continue from 'Exact next action'. "
                f"Finish the task. Run `{hint}` when done."), []
    sh(["ctxrelay", "init"], w)
    sh(["ctxrelay", "switch", "print"], w)
    (w / "mcp.json").write_text(json.dumps({"mcpServers": {"ctxrelay": {"command": str(BIN / "ctxrelay"), "args": ["serve"]}}}))
    cfg = ["-c", f'mcp_servers.ctxrelay.command="{BIN / "ctxrelay"}"', "-c", 'mcp_servers.ctxrelay.args=["serve"]',
           "-c", 'mcp_servers.ctxrelay.default_tools_approval_mode="approve"']
    return ("You are continuing a task started in another session, possibly with a different model. Read "
            ".ctxrelay/HANDOFF.md first, check it against the actual code, then continue from 'Exact next action'. "
            f"Finish the task. Run `{hint}` when done."), cfg


def check(task: str, w: Path) -> dict:
    solution = set(overlay_names(task, "solution"))
    shutil.rmtree(w / "hidden", ignore_errors=True)
    overlay_hidden(task, w)
    t = load(task)
    big = bool(t.get("repo"))
    env = {"PYTHONPATH": f"{w / 'src'}:{w}" if big else str(w)}
    isolate = ["-c", os.devnull, "--rootdir", str(w / "hidden"), "--noconftest"] if big else []
    hidden = sh([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *isolate, "hidden"], w, 600, env=env)
    visible = sh([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *t.get("visible_args", ["tests", "-q"])],
                 w, 900, env=env)
    shutil.rmtree(w / "hidden", ignore_errors=True)
    changed = sorted(line[3:] for line in sh(["git", "status", "--porcelain", "-uall"], w).stdout.splitlines()
                     if not any(n in line[3:] for n in NOISE))
    allowed = solution | set(overlay_names(task, "interrupted")) | {p for p in changed if p.startswith("tests/")}
    return {"success": hidden.returncode == 0 and visible.returncode == 0, "hidden_pass": hidden.returncode == 0,
            "regression": visible.returncode != 0, "collateral": [p for p in changed if p not in allowed],
            "hidden_tail": (hidden.stdout.strip().splitlines() or [""])[-1]}


def overlay_names(task: str, layer: str) -> list[str]:
    src = TASKS / task / layer
    return [str(p.relative_to(src)) for p in src.rglob("*") if p.is_file()]


def overlay_hidden(task: str, w: Path) -> None:
    (w / "hidden").mkdir(exist_ok=True)
    for p in (TASKS / task / "hidden").glob("*.py"):
        shutil.copy(p, w / "hidden" / p.name)


def parse_codex(out: str) -> dict:
    ev = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    kinds = [e["item"]["type"] for e in ev if e.get("type") == "item.completed"]
    u = next((e["usage"] for e in reversed(ev) if e.get("type") == "turn.completed"), {})
    inp, cached = u.get("input_tokens") or 0, u.get("cached_input_tokens") or 0
    return {"tool_calls": kinds.count("command_execution") + kinds.count("mcp_tool_call") + kinds.count("file_change"),
            "mcp_calls": kinds.count("mcp_tool_call"), "input_tokens": inp, "cached_tokens": cached,
            "uncached_tokens": inp - cached, "output_tokens": u.get("output_tokens") or 0}


def parse_claude(out: str) -> dict:
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        return {"unparsed": True}
    u = d.get("usage", {})
    uncached = (u.get("input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
    return {"tool_calls": d.get("num_turns"), "input_tokens": uncached + (u.get("cache_read_input_tokens") or 0),
            "cached_tokens": u.get("cache_read_input_tokens") or 0, "uncached_tokens": uncached,
            "output_tokens": u.get("output_tokens") or 0, "cost_usd": d.get("total_cost_usd")}


def run_agent(agent: str, prompt: str, cfg: list[str], w: Path, task: str, stub_layer: str) -> tuple[dict, str]:
    if agent == "stub":
        overlay(task, stub_layer, w)
        return {}, ""
    if agent == "codex":
        r = sh(["codex", "exec", "-C", str(w), "--skip-git-repo-check", "-s", "workspace-write", "--json", *cfg, prompt],
               w, 900, stdin=subprocess.DEVNULL)
        return parse_codex(r.stdout), r.stdout
    cmd = ["claude", "-p", prompt, "--permission-mode", "acceptEdits", "--output-format", "json",
           "--allowedTools", "Read,Edit,Write,Grep,Glob,Bash(python:*),Bash(git:*),Bash(ls:*),Bash(grep:*),mcp__ctxrelay"]
    if cfg:
        cmd += ["--mcp-config", "mcp.json", "--strict-mcp-config"]
    r = sh(cmd, w, 900, stdin=subprocess.DEVNULL)
    return parse_claude(r.stdout), r.stdout


def run_one(agent, task, cond, rep, stub_layer="solution") -> dict:
    w = make_work(task, cond, f"{agent}{rep}")
    prompt, cfg = setup(task, cond, w)
    t0 = time.time()
    metrics, raw = run_agent(agent, prompt, cfg, w, task, stub_layer)
    wall = round(time.time() - t0, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{task}_{cond}_{agent}{rep}.raw").write_text(raw)
    res = {"task": task, "cond": cond, "agent": agent, "rep": rep, "wall_s": wall, **metrics, **check(task, w)}
    (OUT / f"{task}_{cond}_{agent}{rep}.json").write_text(json.dumps(res, indent=1))
    return res


def validate() -> list[str]:
    """Harness self-test, no model: interrupted state fails, the solution passes, the trap fails the hidden tests."""
    problems = []
    for name in sorted(p.name for p in TASKS.iterdir() if p.is_dir()):
        w = make_work(name, "C0", "validate")
        before = check(name, w)
        if before["hidden_pass"]:
            problems.append(f"{name}: interrupted state already passes hidden tests")
        overlay(name, "solution", w)
        after = check(name, w)
        if not after["success"] or after["collateral"]:
            problems.append(f"{name}: reference solution fails ({after})")
        w = make_work(name, "C0", "validate_trap")
        overlay(name, "trap", w)
        if check(name, w)["hidden_pass"]:
            problems.append(f"{name}: the naive 'trap' solution passes hidden tests (task doesn't test the constraint)")
    return problems


def summarize(rows: list[dict]) -> str:
    keys = sorted({(r["task"], r["cond"]) for r in rows})
    out = ["task | cond | n | success | median wall s | median tool calls | median uncached tok | regressions"]
    for task, cond in keys:
        g = [r for r in rows if r["task"] == task and r["cond"] == cond]

        def med(k, g=g):
            v = [r[k] for r in g if isinstance(r.get(k), (int, float))]
            return round(statistics.median(v), 1) if v else "-"
        out.append(f"{task} | {cond} | {len(g)} | {sum(r['success'] for r in g)}/{len(g)} | {med('wall_s')} | "
                   f"{med('tool_calls')} | {med('uncached_tokens')} | {sum(r['regression'] for r in g)}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--agent", choices=["codex", "claude", "stub"], default="stub")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--conds", default=",".join(CONDS))
    ap.add_argument("--reps", type=int, default=1)
    a = ap.parse_args(argv)
    if a.validate:
        problems = validate()
        print("\n".join(problems) or "all tasks valid")
        return 1 if problems else 0
    names = a.tasks.split(",") if a.tasks else sorted(p.name for p in TASKS.iterdir() if p.is_dir())
    rows = []
    for name in names:
        for cond in a.conds.split(","):
            for rep in range(a.reps):
                r = run_one(a.agent, name, cond, rep)
                rows.append(r)
                print(f"{name} {cond} rep{rep}: success={r['success']} wall={r['wall_s']}s tools={r.get('tool_calls')} "
                      f"uncached={r.get('uncached_tokens')}", flush=True)
    print("\n" + summarize(rows))
    (OUT / "summary.md").write_text(summarize(rows) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
