import argparse
import os
import shutil
import sys
from pathlib import Path

from . import graph, handoff, mcp_server, state

MARK_START, MARK_END = "<!-- ctxrelay:start -->", "<!-- ctxrelay:end -->"
RULES = f"""{MARK_START}
## Context handoff (ctxrelay)
- At the start of a session, read `.ctxrelay/HANDOFF.md` if it exists.
- When you make a decision, rule out an option, hit a constraint or leave a question open, record it with the
  `handoff_note` MCP tool (or `ctxrelay note <kind> "<text>"`). Kinds: goal, constraint, decision, rejected, open, next.
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


def cmd_init(_):
    _write_managed(Path("AGENTS.md"), RULES)
    for name in ("CLAUDE.md", "GEMINI.md"):  # both support @file imports
        p = Path(name)
        if not p.exists():
            p.write_text("@AGENTS.md\n")
        elif "@AGENTS.md" not in p.read_text():
            p.write_text(p.read_text().rstrip("\n") + "\n\n@AGENTS.md\n")
    state.home()
    print(graph.build(state.root()))
    print("\nConnect the MCP server once per tool:\n"
          "  claude mcp add ctxrelay -- ctxrelay serve\n"
          "  codex mcp add ctxrelay -- ctxrelay serve\n"
          "  gemini mcp add ctxrelay ctxrelay serve")


def cmd_switch(a):
    path = handoff.write()
    if a.print_only or a.target == "print":
        print(path.read_text())
        return
    argv = CLIS[a.target](PROMPT)
    if not shutil.which(argv[0]):
        sys.exit(f"{argv[0]} not found on PATH. Handoff is at {path}; start it manually and say: {PROMPT}")
    if a.reindex:
        print(graph.build(state.root()))
    print(f"Handoff written to {path}; launching {a.target}…")
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
    sub.add_parser("init", help="write AGENTS.md/CLAUDE.md/GEMINI.md rules, build the graph").set_defaults(fn=cmd_init)
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
    s.add_argument("--reindex", action="store_true", help="refresh the graph first")
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
