import os
import stat
import subprocess

import pytest

from ctxrelay import cli, graph, state, switch


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "b"],
                   check=True)
    (tmp_path / "a.py").write_text("def helper(): return 1\ndef main(): return helper()\n")
    return tmp_path


def fake_cli(dir_, name, mcp_out="ctxrelay: ok", version_code=0, mcp_code=0):
    f = dir_ / name
    f.write_text(f'#!/bin/sh\ncase "$1" in --version) echo 1.0; exit {version_code};; '
                 f'mcp) echo "{mcp_out}"; exit {mcp_code};; esac\n')
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return f


def which_in(dir_):
    return lambda n: str(dir_ / n) if (dir_ / n).exists() else None


def test_destination_missing_binary(tmp_path):
    fatal, _ = switch.check_destination("codex", which_in(tmp_path))
    assert "not found" in fatal


def test_destination_ok_and_mcp_warning(tmp_path):
    fake_cli(tmp_path, "codex")
    fake_cli(tmp_path, "claude", mcp_out="other: ok")
    env = os.environ.copy()
    os.environ["PATH"] = f"{tmp_path}:{env['PATH']}"
    try:
        assert switch.check_destination("codex", which_in(tmp_path)) == ("", [])
        fatal, warns = switch.check_destination("claude", which_in(tmp_path))
        assert not fatal and "claude mcp add ctxrelay" in warns[0]
    finally:
        os.environ["PATH"] = env["PATH"]


def test_destination_broken_version(tmp_path, monkeypatch):
    fake_cli(tmp_path, "codex", version_code=2)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert "failed" in switch.check_destination("codex", which_in(tmp_path))[0]


def test_verify_reports_gaps_then_clean(proj):
    problems = switch.verify(state.load(), proj)
    assert any("goal" in p for p in problems) and any("next action" in p for p in problems)
    state.add_note("goal", "g")
    state.add_note("next", "do x")
    from ctxrelay import events
    events.append([{"ts": "t", "kind": "edit", "file": "a.py"}])
    assert switch.verify(state.load(), proj) == []
    events.append([{"ts": "t", "kind": "edit", "file": "gone.py"}])
    assert "no longer exist" in switch.verify(state.load(), proj)[0]


def test_verify_detects_rewritten_history(proj):
    state.add_note("goal", "g")
    s = state.load()
    s["base_sha"] = "0" * 40
    assert any("base commit" in p for p in switch.verify(s, proj))


def test_dry_run_switch(proj, monkeypatch, capsys):
    fake_cli(proj, "codex")
    monkeypatch.setenv("PATH", f"{proj}:{os.environ['PATH']}")
    state.add_note("goal", "g")
    cli.main(["switch", "codex", "--dry-run"])
    out = capsys.readouterr().out
    assert "graph:" in out and "transferred:" in out and "dry run" in out
    assert (proj / ".ctxrelay" / "HANDOFF.md").exists()


def test_switch_missing_cli_exits(proj, monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(SystemExit):
        cli.main(["switch", "codex"])


def test_incremental_index_matches_full_build(proj):
    (proj / "b.py").write_text("def other(): return helper()\n")
    graph.build(proj)
    assert graph.stale(proj) is False
    assert graph.refresh(proj) == "index up to date"

    def snapshot():
        con = graph.connect()
        syms = sorted(con.execute("SELECT name,file,line FROM symbols"))
        names = dict(con.execute("SELECT id,name FROM symbols"))
        edges = sorted((names[a], names[b]) for a, b in con.execute("SELECT src,dst FROM edges"))
        comm = sorted(con.execute("SELECT path,community FROM files"))
        con.close()
        return syms, edges, comm

    (proj / "a.py").write_text("def helper(): return 1\ndef main(): return helper() + other()\ndef newfn(): pass\n")
    (proj / "b.py").unlink()
    (proj / "c.py").write_text("def another(): return newfn()\n")
    assert graph.stale(proj) is True
    assert "parsed" in graph.refresh(proj)
    incremental = snapshot()
    graph.db_path().unlink()
    graph.build(proj)  # cold cache = full build
    assert snapshot() == incremental
