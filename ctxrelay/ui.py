"""Terminal output: colour, a banner, checklists and the status screen. Plain ANSI, stdlib only.

Colour turns off when stdout isn't a terminal, NO_COLOR is set or TERM=dumb; FORCE_COLOR turns it on.
"""
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from . import __version__, events, graph

STYLES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "magenta": "35", "cyan": "36"}
LOGO = ("╭─╮ ctx", "╰─╯ relay")


def color_on() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def unicode_ok() -> bool:
    return (getattr(sys.stdout, "encoding", "") or "").lower().replace("-", "") in ("utf8", "utf8sig")


def paint(text: str, *styles: str) -> str:
    if not color_on() or not styles:
        return text
    return "\033[" + ";".join(STYLES[s] for s in styles) + "m" + text + "\033[0m"


def width() -> int:
    return min(shutil.get_terminal_size((80, 24)).columns, 88)


def banner(subtitle: str = "") -> str:
    logo = LOGO if unicode_ok() else ("ctx", "relay")
    sub = subtitle or "hand your task to another AI coding CLI without losing context"
    return "\n".join([paint(logo[0], "bold", "cyan") + "  " + paint(f"v{__version__}", "dim"),
                      paint(logo[1], "bold", "magenta") + "  " + paint(sub, "dim"), ""])


MARKS = {"ok": ("✓", "ok", "green"), "bad": ("✗", "FAIL", "red"), "warn": ("!", "warn", "yellow"),
         "info": ("•", "-", "cyan")}


def line(kind: str, text: str, detail: str = "") -> str:
    sym, plain, col = MARKS[kind]
    out = f"  {paint(sym if unicode_ok() else plain, 'bold', col)} {text}"
    return out + (f"  {paint(detail, 'dim')}" if detail else "")


def heading(text: str) -> str:
    rule = ("─" if unicode_ok() else "-") * min(len(text) + 2, width())
    return "\n" + paint(text, "bold") + "\n" + paint(rule, "dim")


def clip(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


# ---- status screen (read-only: never creates .ctxrelay) ---------------------

def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def peek(root: Path) -> dict[str, Any]:
    """Inspect a project without changing it (state.home() would create .ctxrelay, so don't use it here)."""
    d = root / ".ctxrelay"
    agents, settings = root / "AGENTS.md", root / ".claude" / "settings.json"
    info: dict[str, Any] = {
        "initialized": d.is_dir(),
        "rules": agents.exists() and "ctxrelay:start" in agents.read_text(errors="ignore"),
        "hooks": settings.exists() and "ctxrelay record" in settings.read_text(errors="ignore"),
        "state": _read_json(d / "state.json"), "graph": "none", "events": None}
    old = Path.cwd()
    os.chdir(root)  # graph/events locate .ctxrelay relative to the cwd
    try:
        if (d / "graph.db").exists():
            try:
                info["graph"] = "stale" if graph.stale(root) else "fresh"
            except Exception:
                info["graph"] = "unknown"
        if (d / "events.jsonl").exists():
            evs = events.read()
            info["events"] = {"edited": len({e["file"] for e in evs if e.get("kind") == "edit"}),
                              "pass": sum(1 for e in evs if e.get("kind") == "test" and e.get("ok")),
                              "fail": sum(1 for e in evs if e.get("kind") == "test" and not e.get("ok"))}
    finally:
        os.chdir(old)
    return info


def status_screen(root: Path, which=shutil.which) -> str:
    i = peek(root)
    out = [banner()]
    if not i["initialized"]:
        init, sw = paint("ctxrelay init --hooks", "bold", "cyan"), paint("ctxrelay switch codex", "bold", "cyan")
        out += [line("warn", "ctxrelay isn't set up in this folder yet"), "",
                f"  Run {init} to set it up, then {sw} when your usage limit hits.", ""]
        return "\n".join(out)
    s = i["state"] or {}
    out.append(heading("Task"))
    out.append(line("ok" if s.get("goal") else "warn", "goal", clip(s.get("goal", "")) or "not recorded"))
    nxt = (s.get("next") or [""])[-1]
    out.append(line("ok" if nxt else "warn", "next action", clip(nxt) or "not recorded"))
    counts = [f"{len(s.get(k, []))} {label}" for k, label in
              (("decision", "decisions"), ("rejected", "rejected options"), ("open", "open questions"))]
    out.append(line("info", ", ".join(counts)))
    out.append(heading("Captured automatically"))
    e = i["events"]
    if e:
        out.append(line("ok", f"{e['edited']} files edited, {e['pass']} passing / {e['fail']} failing test runs"))
    else:
        out.append(line("warn", "nothing captured yet", "install hooks: ctxrelay init --hooks"))
    out.append(heading("Setup"))
    out.append(line("ok" if i["rules"] else "warn", "agent rules in AGENTS.md"))
    out.append(line("ok" if i["hooks"] else "warn", "Claude Code capture hooks",
                    "" if i["hooks"] else "ctxrelay init --hooks"))
    g = i["graph"]
    out.append(line("ok" if g == "fresh" else "warn", f"code graph: {g}", "" if g == "fresh" else "ctxrelay index"))
    for cli in ("claude", "codex", "gemini"):
        out.append(line("ok" if which(cli) else "info", f"{cli} CLI " + ("found" if which(cli) else "not installed")))
    ready = [c for c in ("claude", "codex") if which(c)]
    out += ["", "  Next: " + paint(f"ctxrelay switch {ready[0] if ready else 'print'}", "bold", "cyan")
            + paint("   (add --dry-run to preview)", "dim"), ""]
    return "\n".join(out)
