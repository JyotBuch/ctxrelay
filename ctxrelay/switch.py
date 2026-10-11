"""Pre-flight for `ctxrelay switch`: check the destination CLI, verify the handoff, summarise what moves."""
import subprocess
from pathlib import Path

from . import events

MCP_ADD = {"claude": "claude mcp add ctxrelay -- ctxrelay serve",
           "codex": "codex mcp add ctxrelay -- ctxrelay serve",
           "gemini": "gemini mcp add ctxrelay ctxrelay serve"}


def _run(argv, timeout=15):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def check_destination(target: str, which) -> tuple:
    """Return (fatal_error or "", warnings). `which` is shutil.which (injected for tests)."""
    if not which(target):
        return f"{target} not found on PATH", []
    warns = []
    code, out = _run([target, "--version"])
    if code != 0:
        return f"`{target} --version` failed: {out[:200]}", []
    code, out = _run([target, "mcp", "list"])
    if code != 0:
        warns.append(f"could not check MCP servers (`{target} mcp list` failed); the handoff file still works")
    elif "ctxrelay" not in out:
        warns.append(f"ctxrelay MCP server is not registered in {target}; graph tools will be missing. "
                     f"Fix: {MCP_ADD[target]}")
    return "", warns


def verify(s: dict, root: Path) -> list:
    """Problems that would make the receiving model's start worse. Empty list = good handoff."""
    missing = []
    if not s["goal"]:
        missing.append("no goal recorded (`ctxrelay note goal \"...\"`)")
    if not s["next"]:
        missing.append("no exact next action recorded (`ctxrelay note next \"...\"`)")
    base = s.get("base_sha")
    if base and subprocess.run(["git", "cat-file", "-e", base], cwd=root, capture_output=True).returncode != 0:
        missing.append("base commit no longer exists (history rewritten?): 'commits since start' is unavailable")
    ev = events.summarize()
    gone = [f for f in ev["edited"] if not (root / f).exists()]
    if gone:
        missing.append(f"{len(gone)} edited file(s) no longer exist (deleted/renamed): {', '.join(gone[:3])}")
    if not ev["count"]:
        missing.append("no edits/test runs captured (run `ctxrelay init --hooks` for Claude Code)")
    return missing


def summary(s: dict) -> str:
    ev = events.summarize()
    tests = ev["tests"]
    passed = sum(1 for t in tests if t["ok"])
    parts = [f"{len(s['decision'])} decisions", f"{len(s['rejected'])} rejected options",
             f"{len(s['open'])} open questions", f"{len(ev['edited'])} edited files",
             f"{passed} passing / {len(tests) - passed} failing test runs"]
    return "transferred: " + ", ".join(parts)
