import subprocess

from ctxrelay import cli, doctor


def fake_which(names):
    return lambda n: f"/bin/{n}" if n in names else None


def test_uninitialised_project_reports_fixes(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    rows = doctor.diagnose(tmp_path, which=fake_which(set()))
    kinds = {text: kind for kind, text, _ in rows}
    assert kinds["project set up (.ctxrelay exists)"] == "bad"
    assert any("nothing to switch to" in t for _, t, _ in rows)
    assert not (tmp_path / ".ctxrelay").exists()          # diagnosing must not modify the project
    out = doctor.render(rows)
    assert "ctxrelay init --hooks" in out and "problem(s) to fix" in out


def test_missing_cli_is_info_not_failure(tmp_path):
    rows = doctor.diagnose(tmp_path, which=fake_which(set()))
    assert ("info", "codex CLI not installed", "") in rows


def test_doctor_exits_nonzero_when_broken(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    try:
        cli.main(["doctor"])
        raised = False
    except SystemExit as e:
        raised = e.code == 1
    assert raised


def test_init_gitignores_ctxrelay_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], check=True)
    (tmp_path / ".gitignore").write_text("node_modules/")
    cli.main(["init"])
    cli.main(["init"])
    assert (tmp_path / ".gitignore").read_text() == "node_modules/\n.ctxrelay/\n"
