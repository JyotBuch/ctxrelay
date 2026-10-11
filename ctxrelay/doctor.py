"""`ctxrelay doctor`: one place that says what's wrong with a setup and the exact command to fix it."""
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__, switch, ui

CLIS = ("claude", "codex", "gemini")


def diagnose(root: Path, which=shutil.which) -> list:
    """Return (kind, text, fix) rows; kind is ok / warn / bad / info (see ui.MARKS)."""
    py_ok = sys.version_info >= (3, 9)
    rows = [("ok" if py_ok else "bad", f"python {sys.version.split()[0]}, ctxrelay {__version__}", "")]
    git = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True)
    inside_git = git.returncode == 0
    rows.append(("ok" if inside_git else "warn", "inside a git repository",
                 "" if inside_git else "git init (the handoff's git state needs a repo)"))
    i = ui.peek(root)
    rows.append(("ok" if i["initialized"] else "bad", "project set up (.ctxrelay exists)",
                 "" if i["initialized"] else "ctxrelay init --hooks"))
    rows.append(("ok" if i["rules"] else "warn", "agent rules in AGENTS.md", "" if i["rules"] else "ctxrelay init"))
    rows.append(("ok" if i["hooks"] else "warn", "Claude Code capture hooks",
                 "" if i["hooks"] else "ctxrelay init --hooks (Codex sessions are recovered from transcripts instead)"))
    g = i["graph"]
    rows.append(("ok" if g == "fresh" else "warn", f"code graph: {g}", "" if g == "fresh" else "ctxrelay index"))
    found = 0
    for name in CLIS:
        fatal, warns = switch.check_destination(name, which)
        if fatal.endswith("not found on PATH"):
            rows.append(("info", f"{name} CLI not installed", ""))
            continue
        found += 1
        if fatal:
            rows.append(("bad", f"{name}: {fatal}", f"reinstall or update {name}"))
            continue
        rows.append(("ok", f"{name} CLI works", ""))
        for w in warns:
            text, _, fix = w.partition("Fix: ")
            rows.append(("warn", text.strip(), fix))
    if found < 2:
        rows.append(("warn", "fewer than two coding CLIs installed: there is nothing to switch to",
                     "install both Claude Code and Codex CLI"))
    return rows


def render(rows: list) -> str:
    out = [ui.banner("doctor")]
    for kind, text, fix in rows:
        out.append(ui.line(kind, text, f"fix: {fix}" if fix else ""))
    bad = sum(1 for k, _, _ in rows if k == "bad")
    warn = sum(1 for k, _, _ in rows if k == "warn")
    out.append("\n  " + (f"{bad} problem(s) to fix" if bad else f"no blocking problems, {warn} warning(s)") + "\n")
    return "\n".join(out)
