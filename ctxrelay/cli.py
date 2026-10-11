import argparse
import contextlib
import json
import os
import shutil
import sys
from pathlib import Path

from . import events, graph, handoff, mcp_server, state, switch

MARK_START, MARK_END = "<!-- ctxrelay:start -->", "<!-- ctxrelay:end -->"
RULES = f"""{MARK_START}
## Context handoff (ctxrelay)
- At the start of a session, read `.ctxrelay/HANDOFF.md` if it exists.
- Edits, test runs and failures are captured automatically. Record a note with the `handoff_note` MCP tool (or
  `ctxrelay note <kind> "<text>"`) only for what a successor could not see from the code and git: the goal, a hard
  requirement from the user, a decision with its reason, an option you ruled out and why. Kinds: goal, constraint,
  decision, rejected, hypothesis, open, next. Do not log progress or completion; at most one `next` note,
  an exact action.
- Before reading many files to understand structure, query the code graph (`graph_*` MCP tools or `ctxrelay q ...`).
  If you don't know a symbol's name, describe what you want with `search_code` (or `ctxrelay q search "..."`).
{MARK_END}
"""
CLIS = {  # name -> argv builder for "start interactive session with this first prompt"
    "claude": lambda p: ["claude", p],
    "codex": lambda p: ["codex", p],
    "gemini": lambda p: ["gemini", "-i", p],
}
PROMPT = ("You are continuing a task started in another session, possibly with a different model. "
          "Read .ctxrelay/HANDOFF.md first, check it against the actual code, then continue from 'Next steps'.")


def _write_managed(path: Path, block: str, create_with: str = ""):
    text = path.read_text() if path.exists() else create_with
    if MARK_START in text:
        head, rest = text.split(MARK_START, 1)
        tail = rest.split(MARK_END, 1)[1] if MARK_END in rest else ""
        text = head + block.rstrip("\n") + tail
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    path.write_text(text)


HOOK_CMD = "ctxrelay record"


def _install_hooks(settings: Path) -> None:
    """Merge ctxrelay's capture hooks into a Claude Code settings file (idempotent)."""
    data = json.loads(settings.read_text()) if settings.exists() else {}
    hooks = data.setdefault("hooks", {})
    for event in ("PostToolUse", "PostToolUseFailure"):
        groups = hooks.setdefault(event, [])
        if not any(h.get("command") == HOOK_CMD for g in groups for h in g.get("hooks", [])):
            groups.append({"matcher": "Bash|Edit|Write|MultiEdit|NotebookEdit",
                           "hooks": [{"type": "command", "command": HOOK_CMD}]})
    settings.parent.mkdir(exist_ok=True)
    settings.write_text(json.dumps(data, indent=2) + "\n")


def cmd_record(_):
    with contextlib.suppress(Exception):  # a capture hook must never break the session
        events.record_hook(json.load(sys.stdin))


def cmd_ingest(_):
    print(f"recovered {events.ingest()} event(s) from session transcripts")


def cmd_init(a):
    _write_managed(Path("AGENTS.md"), RULES)
    for name in ("CLAUDE.md", "GEMINI.md"):  # both support @file imports
        p = Path(name)
        if not p.exists():
            p.write_text("@AGENTS.md\n")
        elif "@AGENTS.md" not in p.read_text():
            p.write_text(p.read_text().rstrip("\n") + "\n\n@AGENTS.md\n")
    state.home()
    state.ensure_base()
    if a.hooks:
        _install_hooks(Path(".claude") / "settings.json")
        print("Installed Claude Code capture hooks in .claude/settings.json")
    print(graph.build(state.root()))
    print("\nConnect the MCP server once per tool:\n"
          "  claude mcp add ctxrelay -- ctxrelay serve\n"
          "  codex mcp add ctxrelay -- ctxrelay serve\n"
          "  gemini mcp add ctxrelay ctxrelay serve")


def cmd_switch(a):
    if a.print_only or a.target == "print":
        events.ingest()
        print(handoff.write().read_text())
        return
    argv = CLIS[a.target](PROMPT)
    fatal, warns = switch.check_destination(a.target, shutil.which)
    if fatal and not a.dry_run:
        sys.exit(f"{fatal}. Handoff not launched; `ctxrelay switch print` shows it, or install {a.target} and retry.")
    print("graph:", graph.refresh(state.root()))  # unchanged files are not re-parsed
    print(f"transcripts: recovered {events.ingest()} new event(s)")
    path = handoff.write()
    problems = switch.verify(state.load(), state.root())
    print(switch.summary(state.load()))
    for w in [fatal, *warns]:
        if w:
            print("warning:", w)
    for m in problems:
        print("missing:", m)
    print(f"handoff: {path} ({len(path.read_text().splitlines())} lines)")
    if a.dry_run:
        print("dry run: not launching")
        return
    print(f"launching {a.target}…")
    os.execvp(argv[0], argv)


def cmd_note(a):
    print(state.add_note(a.kind, " ".join(a.text)))


def cmd_query(a):
    fns = {"find": graph.find, "callers": graph.callers, "callees": graph.callees, "impact": graph.impact,
           "file": graph.file_summary, "search": graph.search}
    if a.what in fns:
        if not a.arg:
            sys.exit(f"{a.what} needs an argument")
        print(fns[a.what](a.arg))
    elif a.what == "community":
        print(graph.community(int(a.arg) if a.arg else None))
    elif a.what == "hubs":
        print(graph.hubs())


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ctxrelay", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="write AGENTS.md/CLAUDE.md/GEMINI.md rules, build the graph")
    i.add_argument("--hooks", action="store_true", help="also install Claude Code hooks (edits, test runs)")
    i.set_defaults(fn=cmd_init)
    sub.add_parser("record", help="(hook) record one tool call from stdin").set_defaults(fn=cmd_record)
    sub.add_parser("ingest", help="recover edits/test runs from session transcripts").set_defaults(fn=cmd_ingest)
    sub.add_parser("index", help="rebuild the code graph").set_defaults(fn=lambda _: print(graph.build(state.root())))
    sub.add_parser("serve", help="run the MCP server (stdio)").set_defaults(fn=lambda _: mcp_server.serve())
    n = sub.add_parser("note", help="record task state")
    n.add_argument("kind", choices=state.KINDS)
    n.add_argument("text", nargs="+")
    n.set_defaults(fn=cmd_note)
    d = sub.add_parser("drop", help="remove a recorded note")
    d.add_argument("kind", choices=state.LISTS)
    d.add_argument("index", type=int)
    d.set_defaults(fn=lambda a: print(state.drop_note(a.kind, a.index)))
    sub.add_parser("handoff", help="print the handoff").set_defaults(fn=lambda _: print(handoff.render()))
    s = sub.add_parser("switch", help="write the handoff and launch another CLI")
    s.add_argument("target", choices=[*CLIS, "print"])
    s.add_argument("--reindex", action="store_true", help="(deprecated: the graph is always refreshed)")
    s.add_argument("--dry-run", action="store_true", help="run all checks and write the handoff, don't launch")
    s.add_argument("--print-only", action="store_true")
    s.set_defaults(fn=cmd_switch)
    q = sub.add_parser("q", help="query the code graph")
    q.add_argument("what", choices=["find", "callers", "callees", "impact", "file", "community", "hubs", "search"])
    q.add_argument("arg", nargs="?")
    q.set_defaults(fn=cmd_query)
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        a.fn(a)
    except (RuntimeError, ValueError) as e:
        sys.exit(f"ctxrelay: {e}")
