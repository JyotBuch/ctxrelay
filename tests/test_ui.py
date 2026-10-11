import re

from ctxrelay import cli, state, ui

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_plain_when_not_a_tty(monkeypatch):
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert ui.paint("x", "red") == "x"          # pytest captures stdout, so not a tty


def test_colour_forced_and_no_color_wins(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert ANSI.search(ui.paint("x", "red"))
    monkeypatch.setenv("NO_COLOR", "1")
    assert ui.paint("x", "red") == "x"


def test_status_screen_uninitialised_creates_nothing(tmp_path):
    out = ui.status_screen(tmp_path)
    assert "isn't set up" in out and "ctxrelay init --hooks" in out
    assert not (tmp_path / ".ctxrelay").exists()


def test_status_screen_shows_task_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state.add_note("goal", "ship the thing")
    state.add_note("next", "write the tests")
    out = ui.status_screen(tmp_path, which=lambda n: "/bin/" + n if n == "codex" else None)
    assert "ship the thing" in out and "write the tests" in out
    assert "codex CLI found" in out and "claude CLI not installed" in out and "ctxrelay switch codex" in out


def test_bare_invocation_and_status_command(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    cli.main([])
    cli.main(["status"])
    assert capsys.readouterr().out.count("isn't set up") == 2


def test_init_output_is_a_checklist(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.py").write_text("def foo(): pass\n")
    cli.main(["init", "--hooks"])
    out = capsys.readouterr().out
    assert "agent rules written" in out and "capture hooks installed" in out and "code graph built" in out
