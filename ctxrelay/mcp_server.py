"""Minimal MCP server over stdio (newline-delimited JSON-RPC). No dependencies."""
import json
import sys

from . import __version__, graph, handoff, state

STR = {"type": "string"}


def _tool(name, desc, props=None, required=()):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props or {}, "required": list(required)}}


TOOLS = {
    "graph_find": (_tool("graph_find", "Find symbols whose name contains a substring.", {"name": STR}, ["name"]),
                   lambda a: graph.find(a["name"])),
    "graph_callers": (_tool("graph_callers", "Symbols that reference the given symbol.", {"name": STR}, ["name"]),
                      lambda a: graph.callers(a["name"])),
    "graph_callees": (_tool("graph_callees", "Symbols referenced by the given symbol.", {"name": STR}, ["name"]),
                      lambda a: graph.callees(a["name"])),
    "graph_impact": (_tool("graph_impact", "Transitive callers: what may break if this symbol changes.",
                           {"name": STR, "depth": {"type": "integer"}}, ["name"]),
                     lambda a: graph.impact(a["name"], int(a.get("depth", 3)))),
    "graph_community": (_tool("graph_community", "With no number, list communities (file clusters). "
                              "With a number, list its files.",
                              {"number": {"type": "integer"}}),
                        lambda a: graph.community(a.get("number"))),
    "graph_hubs": (_tool("graph_hubs", "Most-depended-on symbols."), lambda a: graph.hubs()),
    "graph_file": (_tool("graph_file", "Symbols defined in a file.", {"path": STR}, ["path"]),
                   lambda a: graph.file_summary(a["path"])),
    "search_code": (_tool("search_code", "Find code by natural-language description (needs colgrep installed). "
                                      "Use when you don't know the name; use graph_* when you do.",
                                      {"query": STR}, ["query"]),
                    lambda a: graph.search(a["query"])),
    "graph_reindex": (_tool("graph_reindex", "Rebuild the code graph."), lambda a: graph.build(state.root())),
    "handoff_note": (_tool("handoff_note",
                           "Record durable task state for a future model: goal, constraint, decision, rejected, "
                           "hypothesis, open, next (keep the last `next` an exact action). "
                           "Call this whenever you make a decision or rule something out.",
                           {"kind": {"type": "string", "enum": list(state.KINDS)}, "text": STR}, ["kind", "text"]),
                     lambda a: state.add_note(a["kind"], a["text"])),
    "handoff_get": (_tool("handoff_get", "Return the current handoff document."), lambda a: handoff.render()),
}


def _reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    msg["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def serve():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, id_ = req.get("method"), req.get("id")
        if id_ is None:  # notification
            continue
        if method == "initialize":
            _reply(id_, {"protocolVersion": req.get("params", {}).get("protocolVersion", "2025-03-26"),
                         "capabilities": {"tools": {}}, "serverInfo": {"name": "ctxrelay", "version": __version__}})
        elif method == "tools/list":
            _reply(id_, {"tools": [t for t, _ in TOOLS.values()]})
        elif method == "tools/call":
            p = req.get("params", {})
            entry = TOOLS.get(p.get("name"))
            if not entry:
                _reply(id_, error={"code": -32602, "message": f"unknown tool {p.get('name')}"})
                continue
            try:
                text, err = entry[1](p.get("arguments") or {}), False
            except Exception as e:  # surface to the model rather than crash the server
                text, err = f"error: {e}", True
            _reply(id_, {"content": [{"type": "text", "text": str(text)}], "isError": err})
        elif method == "ping":
            _reply(id_, {})
        else:
            _reply(id_, error={"code": -32601, "message": f"unknown method {method}"})
