import json
import subprocess
import sys

import pytest

from ctxrelay import cli, events, handoff, state


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    return tmp_path


def hook(tool, tool_input, resp="", event="PostToolUse", cwd=None):
    return events.record_hook({"hook_event_name": event, "tool_name": tool, "tool_input": tool_input,
                               "tool_response": resp, "cwd": str(cwd or ".")})


def test_test_detection():
    assert events.is_test_cmd("cd x && python -m pytest -q")
    assert events.is_test_cmd("npm run test")
    assert not events.is_test_cmd("git status")


def test_hook_records_edits_tests_and_errors(proj):
    hook("Edit", {"file_path": str(proj / "a.py")})
    hook("Bash", {"command": "pytest -q"}, {"stdout": "3 passed"})
    hook("Bash", {"command": "pytest -q"}, {"stdout": "1 failed, 2 passed"})
    hook("Bash", {"command": "make build"}, "boom", event="PostToolUseFailure")
    hook("Bash", {"command": "ls"}, "fine")  # uninteresting: not recorded
    s = events.summarize()
    assert s["edited"] == ["a.py"]
    assert [t["ok"] for t in s["tests"]] == [True, False]
    assert len(s["errors"]) == 1 and s["count"] == 4


def test_hook_never_raises_and_truncates(proj):
    assert events.record_hook({"tool_name": 5, "tool_input": "junk"}) == 0
    hook("Bash", {"command": "pytest"}, {"stdout": "x" * 5000 + " 1 failed"})
    assert len(events.read()[0]["summary"]) <= events.MAX_FIELD + 1


def test_handoff_shows_verified_work(proj):
    state.add_note("next", "later step")
    state.add_note("next", "fix test_foo")
    hook("Edit", {"file_path": "a.py"})
    hook("Bash", {"command": "pytest"}, "FAILED test_foo - assert 1 == 2")
    doc = handoff.render()
    assert "`a.py`" in doc and "FAIL `pytest`" in doc and "FAILED test_foo" in doc
    assert "**fix test_foo**" in doc and "Later: later step" in doc


def test_commits_since_base(proj):
    state.add_note("goal", "x")
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "work"], check=True)
    assert "work" in handoff.render()


def test_claude_transcript_ingest(proj, tmp_path):
    home = tmp_path / "home"
    d = home / ".claude" / "projects" / "".join(c if c.isalnum() else "-" for c in str(proj.resolve()))
    d.mkdir(parents=True)
    rows = [{"timestamp": "t", "message": {"content": [
                {"type": "tool_use", "id": "u1", "name": "Bash", "input": {"command": "pytest"}},
                {"type": "tool_use", "id": "u2", "name": "Write", "input": {"file_path": str(proj / "n.py")}}]}},
            {"message": {"content": [
                {"type": "tool_result", "tool_use_id": "u1", "content": "Exit code 1\n2 failed"},
                {"type": "tool_result", "tool_use_id": "u2", "content": "ok"}]}}, "not json"]
    (d / "s.jsonl").write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in rows))
    assert events.ingest(home) == 2
    assert events.ingest(home) == 0  # idempotent
    s = events.summarize()
    assert s["edited"] == ["n.py"] and not s["tests"][0]["ok"]


def test_codex_transcript_ingest(proj, tmp_path):
    home = tmp_path / "home"
    d = home / ".codex" / "sessions" / "2026" / "01" / "01"
    d.mkdir(parents=True)
    rows = [{"type": "session_meta", "payload": {"cwd": str(proj.resolve())}},
            {"payload": {"type": "function_call", "call_id": "c1", "arguments": json.dumps({"cmd": "pytest -q"})}},
            {"payload": {"type": "function_call_output", "call_id": "c1",
                         "output": "Process exited with code 1\n1 failed"}},
            {"payload": {"type": "custom_tool_call", "call_id": "c2", "input": "*** Update File: src/x.py\n"}},
            {"payload": {"type": "custom_tool_call_output", "call_id": "c2", "output": "done"}}]
    (d / "r.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
    assert events.ingest(home) == 2
    s = events.summarize()
    assert s["edited"] == ["src/x.py"] and s["tests"][0]["ok"] is False


def test_install_hooks_idempotent(tmp_path):
    f = tmp_path / ".claude" / "settings.json"
    f.parent.mkdir()
    f.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
    cli._install_hooks(f)
    cli._install_hooks(f)
    data = json.loads(f.read_text())
    assert data["permissions"]["allow"] == ["Bash(ls)"]
    assert len(data["hooks"]["PostToolUse"]) == 1 and len(data["hooks"]["PostToolUseFailure"]) == 1


def test_record_cli_swallows_bad_stdin(proj, monkeypatch):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    cli.cmd_record(None)


def test_heredoc_mentioning_pytest_is_not_a_test_and_outside_edits_ignored(proj):
    hook("Bash", {"command": "cat <<EOF\nrun pytest later\nEOF"}, "")
    hook("Edit", {"file_path": "/somewhere/else/plan.md"})
    assert events.read() == []
