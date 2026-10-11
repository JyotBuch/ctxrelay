"""Structural invariants: things that should stay true as features are added."""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import ctxrelay
from ctxrelay import cli, mcp_server, state

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "ctxrelay"
README = (ROOT / "README.md").read_text()


def test_version_matches_pyproject():
    m = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    assert m and m.group(1) == ctxrelay.__version__


def test_no_runtime_dependencies():
    text = (ROOT / "pyproject.toml").read_text()
    assert re.search(r"^dependencies\s*=\s*\[\s*\]", text, re.M), "ctxrelay is stdlib-only by design; discuss before adding"


NETWORK_MODULES = {"socket", "urllib", "http", "requests", "httpx", "aiohttp", "ftplib", "smtplib", "ssl", "websockets"}


def test_package_makes_no_network_calls():
    """Everything runs locally; a handoff tool that phones home would be a trust problem."""
    for f in PKG.glob("*.py"):
        for node in ast.walk(ast.parse(f.read_text())):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            for m in mods:
                assert m.split(".")[0] not in NETWORK_MODULES, f"{f.name} imports {m}"


def test_mcp_tool_definitions_are_well_formed():
    seen = set()
    for key, (tool, fn) in mcp_server.TOOLS.items():
        assert tool["name"] == key and key not in seen
        seen.add(key)
        assert len(tool["description"]) > 20, f"{key}: describe the tool so models know when to use it"
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert set(schema["required"]) <= set(schema["properties"]), key
        assert callable(fn)


def test_agent_rules_only_mention_tools_that_exist():
    rules = cli.RULES
    for tool in re.findall(r"`((?:graph_|handoff_|search_)\w+)`", rules):
        assert tool in mcp_server.TOOLS, f"AGENTS.md rules mention missing tool {tool}"
    for kind in state.KINDS:
        assert kind in rules


def test_readme_commands_exist():
    subcommands = set(cli.build_parser()._subparsers._group_actions[0].choices)
    mentioned = set(re.findall(r"^\s*ctxrelay (\w[\w-]*)", README, re.M)) | set(re.findall(r"`ctxrelay (\w[\w-]*)", README))
    unknown = {m for m in mentioned if m not in subcommands and m not in ("is", "works", "more")}
    assert not unknown, f"README mentions ctxrelay subcommands that don't exist: {unknown}"


def test_every_subcommand_has_help():
    subcommands = cli.build_parser()._subparsers._group_actions[0].choices
    for name in subcommands:
        out = subprocess.run([sys.executable, "-m", "ctxrelay", name, "--help"], capture_output=True, text=True,
                             env={**os.environ, "PYTHONPATH": str(ROOT)})
        assert out.returncode == 0 and "usage" in out.stdout.lower(), name


def test_eval_results_referenced_in_readme_exist():
    for rel in re.findall(r"`(eval/[\w./-]+)`", README):
        if not any(c in rel for c in "*<>"):
            assert (ROOT / rel).exists(), f"README references missing {rel}"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m.py").write_text("def alpha():\n    return beta()\ndef beta():\n    return 1\n")
    return tmp_path


def test_init_is_idempotent_and_preserves_user_content(project):
    (project / "AGENTS.md").write_text("# My own rules\nBe terse.\n")
    cli.main(["init"])
    first = (project / "AGENTS.md").read_text()
    cli.main(["init"])
    second = (project / "AGENTS.md").read_text()
    assert first == second
    assert "Be terse." in second and second.count(cli.MARK_START) == 1
    assert (project / "CLAUDE.md").read_text().count("@AGENTS.md") == 1


def test_init_keeps_existing_claude_md(project):
    (project / "CLAUDE.md").write_text("# project notes\n")
    cli.main(["init"])
    text = (project / "CLAUDE.md").read_text()
    assert "# project notes" in text and "@AGENTS.md" in text


def test_notes_roundtrip_and_drop(project):
    state.add_note("decision", "a")
    state.add_note("decision", "b")
    state.drop_note("decision", 1)
    assert state.load()["decision"] == ["b"]
    with pytest.raises(ValueError):
        state.drop_note("decision", 5)
    with pytest.raises(ValueError):
        state.drop_note("goal", 1)


def test_switch_print_works_without_git_or_index(project):
    cli.main(["switch", "print"])      # must not raise
