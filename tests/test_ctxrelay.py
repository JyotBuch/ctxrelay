import json
import os
import subprocess
import sys
import textwrap

import pytest

from ctxrelay import graph, handoff, state


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text(textwrap.dedent("""
        def helper(): return 1
        def main(): return helper()
        class Svc:
            def run(self): return main()
    """))
    (tmp_path / "b.ts").write_text("export function render() { return helper(); }\nconst go = () => render();\n")
    return tmp_path


def test_graph_queries(proj):
    assert "symbols" in graph.build(proj)
    assert "helper" in graph.callers("main") + graph.callees("main")
    assert "main" in graph.callers("helper")
    assert "run" in graph.impact("helper")          # helper <- main <- run
    assert "render" in graph.callers("helper")      # cross-language name match
    assert "helper" in graph.hubs()


def test_notes_and_handoff(proj):
    state.add_note("goal", "ship it")
    state.add_note("rejected", "use redis")
    graph.build(proj)
    doc = handoff.render()
    assert "ship it" in doc and "use redis" in doc
    with pytest.raises(ValueError):
        state.add_note("bogus", "x")


def test_mcp_roundtrip(proj):
    graph.build(proj)
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "graph_callers", "arguments": {"name": "helper"}}},
    ]
    out = subprocess.run([sys.executable, "-m", "ctxrelay", "serve"], input="\n".join(map(json.dumps, reqs)),
                         capture_output=True, text=True, cwd=proj,
                         env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(__file__))}).stdout
    replies = [json.loads(l) for l in out.splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert "main" in replies[2]["result"]["content"][0]["text"]


def _rpc(cwd, *reqs, raw=()):
    lines = list(raw) + [json.dumps({"jsonrpc": "2.0", "id": i, **r}) for i, r in enumerate(reqs, 1)]
    out = subprocess.run([sys.executable, "-m", "ctxrelay", "serve"], input="\n".join(lines), capture_output=True,
                         text=True, cwd=cwd, env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(__file__))})
    assert out.returncode == 0, out.stderr
    return [json.loads(l) for l in out.stdout.splitlines()]


def call(tool, **args):
    return {"method": "tools/call", "params": {"name": tool, "arguments": args}}


def test_mcp_errors_do_not_crash(proj):
    # no index built, junk input, unknown tool/method, bad enum: server must answer every request and survive
    replies = _rpc(proj, call("graph_callers", name="x"), call("nope"), {"method": "bogus"},
                   call("handoff_note", kind="bogus", text="t"), call("graph_find", name="x"), raw=["not json", ""])
    assert "no index yet" in replies[0]["result"]["content"][0]["text"] and replies[0]["result"]["isError"]
    assert replies[1]["error"]["code"] == -32602
    assert replies[2]["error"]["code"] == -32601
    assert replies[3]["result"]["isError"]
    assert len(replies) == 5


def test_every_tool_listed_is_callable(proj):
    graph.build(proj)
    listed = _rpc(proj, {"method": "tools/list"})[0]["result"]["tools"]
    reqs = [call(t["name"], **{k: ("helper" if v["type"] == "string" else 1) for k, v in t["inputSchema"]["properties"].items()
                               if k in t["inputSchema"]["required"]}) for t in listed if t["name"] not in ("handoff_note", "search_code")]  # search needs colgrep: tested separately
    for r in _rpc(proj, *reqs):
        assert not r["result"]["isError"], r


def test_search_requires_colgrep(proj, monkeypatch):
    monkeypatch.setenv("PATH", str(proj))  # nothing runnable on PATH
    with pytest.raises(RuntimeError, match="colgrep"):
        graph.search("anything")


def test_search_delegates_to_colgrep(proj, monkeypatch):
    fake = proj / "bin"
    fake.mkdir()
    exe = fake / "colgrep"
    exe.write_text('#!/bin/sh\necho "a.py:1-2  helper"\necho "args: $@"\n')
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    out = graph.search("do the thing", k=3)
    assert "a.py:1-2  helper" in out and "-k 3 do the thing" in out


def test_search_401_hint(proj, monkeypatch):
    fake = proj / "bin"
    fake.mkdir()
    exe = fake / "colgrep"
    exe.write_text('#!/bin/sh\necho "status code 401" >&2\nexit 1\n')
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}:{os.environ['PATH']}")
    with pytest.raises(RuntimeError, match="HF_HOME"):
        graph.search("x")


def test_handoff_includes_code_map(proj):
    graph.build(proj)
    doc = handoff.render()
    assert "Most depended-on symbols" in doc and "helper" in doc
