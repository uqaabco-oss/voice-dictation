import pytest

from voice_dictation import app, cli, launch_agent
from voice_dictation.config import DEFAULT_MODEL, Settings
from voice_dictation.launch_agent import AgentPaths


@pytest.fixture
def captured_run(monkeypatch):
    seen = []
    monkeypatch.setattr(app, "run", lambda settings: seen.append(settings) or 0)
    return seen


def test_no_arguments_runs_with_defaults(captured_run):
    assert cli.main([]) == 0
    assert captured_run == [Settings()]
    assert captured_run[0].model == DEFAULT_MODEL
    assert captured_run[0].language == "en"


def test_run_options_without_command(captured_run):
    cli.main(["--no-sounds", "--language", "auto", "--silence-db", "-70", "-v"])
    settings = captured_run[0]
    assert settings.sounds is False
    assert settings.language is None
    assert settings.silence_dbfs == -70
    assert settings.verbose is True


def test_explicit_run_command(captured_run):
    cli.main(["run", "--model", "/models/whisper"])
    assert captured_run[0].model == "/models/whisper"


def test_unknown_option_is_rejected(captured_run):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--bogus"])
    assert exc.value.code == 2
    assert captured_run == []


def test_install_launch_agent_keeps_run_options(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_install(python, run_args):
        calls.append((python, list(run_args)))
        return AgentPaths.for_home(tmp_path)

    monkeypatch.setattr(launch_agent, "install", fake_install)
    assert cli.main(["install-launch-agent", "--language", "auto", "--no-sounds"]) == 0
    python, run_args = calls[0]
    assert run_args == ["--language", "auto", "--no-sounds"]
    out = capsys.readouterr().out
    assert "Accessibility and Input Monitoring" in out
    assert "launchctl kickstart -k" in out


def test_install_launch_agent_validates_options(monkeypatch):
    monkeypatch.setattr(launch_agent, "install", lambda *a: pytest.fail("should not install"))
    with pytest.raises(SystemExit):
        cli.main(["install-launch-agent", "--bogus"])


def test_install_failure_is_reported(monkeypatch, capsys):
    def failing_install(python, run_args):
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(launch_agent, "install", failing_install)
    assert cli.main(["install-launch-agent"]) == 1
    assert "bootstrap failed" in capsys.readouterr().err


@pytest.mark.parametrize(("existed", "message"), [(True, "Removed"), (False, "not installed")])
def test_uninstall_launch_agent(monkeypatch, tmp_path, capsys, existed, message):
    monkeypatch.setattr(launch_agent, "uninstall", lambda: (AgentPaths.for_home(tmp_path), existed))
    assert cli.main(["uninstall-launch-agent"]) == 0
    assert message in capsys.readouterr().out
