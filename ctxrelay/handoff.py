"""Render the portable handoff: recorded notes + live git state + graph context."""
import subprocess
from pathlib import Path

from . import graph, state

TITLES = [("constraint", "Constraints"), ("decision", "Decisions made"),
          ("rejected", "Rejected options (don't revisit without new info)"),
          ("open", "Open questions"), ("next", "Next steps")]


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
        for name, kind, line, deps in con.execute(
                """SELECT s.name,s.kind,s.line,(SELECT COUNT(*) FROM edges e WHERE e.dst=s.id)
                   FROM symbols s WHERE s.file=? ORDER BY s.line""", (f,)):
            if deps:
                out.append(f"- `{name}` ({f}:{line}) has {deps} dependent(s)")
    return out[:25]


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
    status = _git("status", "--short")
    parts += ["## Repository state", f"Branch: `{_git('rev-parse', '--abbrev-ref', 'HEAD') or 'n/a'}`", ""]
    parts += ["Recent commits:", "```", _git("log", "-5", "--oneline") or "(none)", "```", ""]
    parts += ["Uncommitted changes:", "```", status or "(clean)", "```"]
    stat = _git("diff", "--stat", "HEAD")
    if stat:
        parts += ["```", stat, "```"]
    parts.append("")
    changed = [l[3:].split(" -> ")[-1] for l in status.splitlines()]
    risky = _changed_symbols(changed)
    if risky:
        parts += ["## Changed symbols other code depends on", *risky, ""]
    if graph.db_path().exists():
        hubs = graph.hubs().splitlines()[:5]
        comms = graph.community().splitlines()[:5]
        parts += ["## Code map (from the index; heuristic, verify before relying on it)",
                  "Most depended-on symbols:", *[f"- {l}" for l in hubs], "",
                  "Largest file clusters:", *[f"- {l}" for l in comms], ""]
    parts += ["## Code graph",
              "If the `ctxrelay` MCP server is connected, use its `graph_*` tools (find, callers, callees, impact, "
              "community, hubs) instead of re-reading files. Otherwise run `ctxrelay q <command>`.", ""]
    return "\n".join(parts)


def write() -> Path:
    p = state.home() / "HANDOFF.md"
    p.write_text(render())
    return p
