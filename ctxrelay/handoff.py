"""Render the portable handoff: recorded notes + live git state + graph context."""
import subprocess
from pathlib import Path

from . import events, graph, state

TITLES = [("constraint", "Constraints"), ("decision", "Decisions made"),
          ("rejected", "Rejected options (don't revisit without new info)"),
          ("hypothesis", "Hypotheses explored"), ("open", "Open questions")]


def _git(*args) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _changed_symbols(files) -> list:
    if not graph.db_path().exists():
        return []
    con = graph.connect()
    out = []
    for f in files:
        for name, _kind, line, deps in con.execute(
                """SELECT s.name,s.kind,s.line,(SELECT COUNT(*) FROM edges e WHERE e.dst=s.id)
                   FROM symbols s WHERE s.file=? ORDER BY s.line""", (f,)):
            if deps:
                out.append(f"- `{name}` ({f}:{line}) has {deps} dependent(s)")
    return out[:25]


def _verified_work(s: dict) -> list:
    """Facts captured from tool use (hooks/transcripts) and git, not from the model's own account."""
    ev = events.summarize()
    out = ["## Verified work (captured automatically)"]
    base = s.get("base_sha")
    commits = _git("log", "--oneline", f"{base}..HEAD") if base else ""
    if commits:
        out += ["Commits since the task started:", "```", *commits.splitlines()[:10], "```"]
    if ev["edited"]:
        out += ["Files edited: " + ", ".join(f"`{f}`" for f in ev["edited"][:15])]
    tests = ev["tests"][-5:]
    if tests:
        out += ["Test runs (newest last):"]
        out += [f"- {'PASS' if t['ok'] else 'FAIL'} `{t['cmd']}`" for t in tests]
        failing = [t for t in tests if not t["ok"]]
        if failing and not tests[-1]["ok"]:
            out += ["Last failing output:", "```", failing[-1].get("summary", ""), "```"]
        elif failing:
            out += ["(the most recent run passed)"]
    else:
        out += ["No test runs recorded."]
    errs = ev["errors"][-3:]
    if errs:
        last = [(e["summary"].splitlines() or [""])[-1][:160] for e in errs]
        out += ["Failed commands:", *[f"- `{e['cmd']}`: {m}" for e, m in zip(errs, last)]]
    if not ev["count"] and not commits:
        out = ["## Verified work (captured automatically)",
               "_nothing captured: hooks not installed and no transcript found (run `ctxrelay init --hooks`)_"]
    return out + [""]


def render() -> str:
    s = state.load()
    parts = ["# Handoff", "",
             "Written by ctxrelay so a different model can continue this task. "
             "It records intent and state, not a chat transcript. Verify against the code before relying on it.", ""]
    parts += ["## Goal", s["goal"] or "_not recorded_", ""]
    for kind, title in TITLES:
        parts.append(f"## {title}")
        parts += [f"{i}. {t}" for i, t in enumerate(s[kind], 1)] or ["_none recorded_"]
        parts.append("")
    parts += _verified_work(s)
    nxt = s["next"]
    parts += ["## Exact next action", f"**{nxt[-1]}**" if nxt else "_not recorded_"]
    parts += [f"Later: {t}" for t in nxt[:-1]] + [""]
    status = _git("status", "--short")
    parts += ["## Repository state", f"Branch: `{_git('rev-parse', '--abbrev-ref', 'HEAD') or 'n/a'}`", ""]
    parts += ["Recent commits:", "```", _git("log", "-5", "--oneline") or "(none)", "```", ""]
    parts += ["Uncommitted changes:", "```", status or "(clean)", "```"]
    stat = _git("diff", "--stat", "HEAD")
    if stat:
        parts += ["```", stat, "```"]
    parts.append("")
    changed = [row[3:].split(" -> ")[-1] for row in status.splitlines()]
    risky = _changed_symbols(changed)
    if risky:
        parts += ["## Changed symbols other code depends on", *risky, ""]
    if graph.db_path().exists():
        hubs = graph.hubs().splitlines()[:5]
        comms = graph.community().splitlines()[:5]
        parts += ["## Code map (from the index; heuristic, verify before relying on it)",
                  "Most depended-on symbols:", *[f"- {row}" for row in hubs], "",
                  "Largest file clusters:", *[f"- {row}" for row in comms], ""]
    parts += ["## Code graph",
              "If the `ctxrelay` MCP server is connected, use its `graph_*` tools (find, callers, callees, impact, "
              "community, hubs) instead of re-reading files. Otherwise run `ctxrelay q <command>`.", ""]
    return "\n".join(parts)


def write() -> Path:
    p = state.home() / "HANDOFF.md"
    p.write_text(render())
    return p
