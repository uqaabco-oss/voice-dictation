"""Install or remove a per-user LaunchAgent that starts dictation at login."""

from __future__ import annotations

import os
import plistlib
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

LABEL = "com.uqaabco.voice-dictation"

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, check=False)


@dataclass(frozen=True)
class AgentPaths:
    plist: Path
    log: Path

    @classmethod
    def for_home(cls, home: Path) -> AgentPaths:
        return cls(
            plist=home / "Library" / "LaunchAgents" / f"{LABEL}.plist",
            log=home / "Library" / "Logs" / "voice-dictation.log",
        )


def build_plist(python: str, run_args: Sequence[str], log_path: Path) -> dict:
    """The LaunchAgent definition: run ``python -m voice_dictation run ...`` at login."""
    return {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "voice_dictation", "run", *run_args],
        "RunAtLoad": True,
        # Restart only after a crash (killed by a signal). An error exit, such as
        # another copy already running or the model failing to load, stays down.
        "KeepAlive": {"Crashed": True},
        "ThrottleInterval": 30,
        # Interactive: don't let macOS throttle it, it must react to key presses.
        "ProcessType": "Interactive",
        # Only in a logged-in GUI session, where there is a keyboard and a focused app.
        "LimitLoadToSessionType": "Aqua",
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def install(
    python: str,
    run_args: Sequence[str] = (),
    *,
    home: Path | None = None,
    uid: int | None = None,
    run: Runner = _run,
    sleep: Callable[[float], None] = time.sleep,
) -> AgentPaths:
    """Write the plist and (re)load it so it starts now and at every login."""
    paths = AgentPaths.for_home(home or Path.home())
    domain = f"gui/{os.getuid() if uid is None else uid}"

    # Replace any previous version so changed options take effect.
    run(["launchctl", "bootout", f"{domain}/{LABEL}"])
    paths.plist.parent.mkdir(parents=True, exist_ok=True)
    paths.log.parent.mkdir(parents=True, exist_ok=True)
    with paths.plist.open("wb") as fh:
        plistlib.dump(build_plist(python, run_args, paths.log), fh)

    run(["launchctl", "enable", f"{domain}/{LABEL}"])
    # bootout finishes asynchronously; bootstrap can briefly fail until it has.
    for attempt in range(5):
        result = run(["launchctl", "bootstrap", domain, str(paths.plist)])
        if result.returncode == 0:
            return paths
        if attempt < 4:
            sleep(1.0)
    detail = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(f"launchctl bootstrap failed ({result.returncode}): {detail}")


def uninstall(
    *, home: Path | None = None, uid: int | None = None, run: Runner = _run
) -> tuple[AgentPaths, bool]:
    """Stop the agent and delete its plist; returns (paths, whether a plist existed)."""
    paths = AgentPaths.for_home(home or Path.home())
    domain = f"gui/{os.getuid() if uid is None else uid}"
    run(["launchctl", "bootout", f"{domain}/{LABEL}"])
    existed = paths.plist.exists()
    paths.plist.unlink(missing_ok=True)
    return paths, existed
