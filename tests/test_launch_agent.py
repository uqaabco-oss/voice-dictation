import plistlib
import subprocess

import pytest

from voice_dictation import launch_agent
from voice_dictation.launch_agent import LABEL, AgentPaths, build_plist


class FakeLaunchctl:
    def __init__(self, bootstrap_failures=0):
        self.calls = []
        self.bootstrap_failures = bootstrap_failures

    def __call__(self, cmd):
        self.calls.append(list(cmd))
        code = 0
        if cmd[1] == "bootstrap" and self.bootstrap_failures:
            self.bootstrap_failures -= 1
            code = 5
        return subprocess.CompletedProcess(cmd, code, "", "Input/output error" if code else "")


def test_plist_runs_module_at_login(tmp_path):
    log = tmp_path / "x.log"
    plist = build_plist("/repo/.venv/bin/python", ["--language", "auto"], log)
    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == [
        "/repo/.venv/bin/python",
        "-m",
        "voice_dictation",
        "run",
        "--language",
        "auto",
    ]
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] == {"SuccessfulExit": False}
    assert plist["ProcessType"] == "Interactive"
    assert plist["LimitLoadToSessionType"] == "Aqua"
    assert plist["StandardOutPath"] == plist["StandardErrorPath"] == str(log)
    plistlib.dumps(plist)  # serialisable


def test_install_writes_plist_and_loads_it(tmp_path):
    launchctl = FakeLaunchctl()
    paths = launch_agent.install(
        "/repo/.venv/bin/python", ["--no-sounds"], home=tmp_path, uid=501, run=launchctl
    )
    assert paths == AgentPaths.for_home(tmp_path)
    assert paths.plist == tmp_path / "Library/LaunchAgents" / f"{LABEL}.plist"
    assert paths.log.parent.is_dir()
    written = plistlib.loads(paths.plist.read_bytes())
    assert written["ProgramArguments"][-1] == "--no-sounds"
    assert launchctl.calls == [
        ["launchctl", "bootout", f"gui/501/{LABEL}"],
        ["launchctl", "enable", f"gui/501/{LABEL}"],
        ["launchctl", "bootstrap", "gui/501", str(paths.plist)],
    ]


def test_install_retries_while_previous_agent_shuts_down(tmp_path):
    launchctl = FakeLaunchctl(bootstrap_failures=2)
    launch_agent.install("py", home=tmp_path, uid=501, run=launchctl, sleep=lambda s: None)
    assert [c[1] for c in launchctl.calls].count("bootstrap") == 3


def test_install_reports_persistent_failure(tmp_path):
    launchctl = FakeLaunchctl(bootstrap_failures=99)
    with pytest.raises(RuntimeError, match="Input/output error"):
        launch_agent.install("py", home=tmp_path, uid=501, run=launchctl, sleep=lambda s: None)


def test_install_replaces_existing_agent(tmp_path):
    launchctl = FakeLaunchctl()
    launch_agent.install("py", ["--no-sounds"], home=tmp_path, uid=501, run=launchctl)
    paths = launch_agent.install("py", [], home=tmp_path, uid=501, run=launchctl)
    written = plistlib.loads(paths.plist.read_bytes())
    assert written["ProgramArguments"] == ["py", "-m", "voice_dictation", "run"]


def test_uninstall_stops_and_removes(tmp_path):
    launchctl = FakeLaunchctl()
    launch_agent.install("py", home=tmp_path, uid=501, run=launchctl)
    launchctl.calls.clear()

    paths, existed = launch_agent.uninstall(home=tmp_path, uid=501, run=launchctl)
    assert existed is True
    assert not paths.plist.exists()
    assert launchctl.calls == [["launchctl", "bootout", f"gui/501/{LABEL}"]]

    _, existed_again = launch_agent.uninstall(home=tmp_path, uid=501, run=launchctl)
    assert existed_again is False
