"""Wire everything together and run the macOS event loop."""

from __future__ import annotations

import logging
import os
import platform
import signal
import sys
import threading

from . import single_instance
from .config import Settings
from .launch_agent import LABEL

log = logging.getLogger(__name__)

EXIT_ALREADY_RUNNING = 3


def permission_target() -> str:
    """Describe which app macOS attributes this process's permissions to."""
    if os.environ.get("XPC_SERVICE_NAME") == LABEL:
        return f"the Python binary {os.path.realpath(sys.executable)} (used by the LaunchAgent)"
    terminal = os.environ.get("TERM_PROGRAM")
    if terminal == "tmux":
        return "the terminal app that started the tmux server"
    if terminal:
        return f"your terminal app ({terminal})"
    return "the app you started voice-dictation from"


def _check_permissions() -> None:
    from .hotkey import input_monitoring_granted
    from .paste import accessibility_trusted

    target = permission_target()
    if not accessibility_trusted(prompt=True):
        log.warning(
            "Accessibility is not granted, so text will be left on the clipboard instead of "
            "pasted. Allow %s in System Settings > Privacy & Security > Accessibility.",
            target,
        )
    if not input_monitoring_granted(prompt=True):
        log.warning(
            "Input Monitoring is not granted, so Right Option cannot be detected yet. "
            "Allow %s in System Settings > Privacy & Security > Input Monitoring.",
            target,
        )


def run(settings: Settings) -> int:
    if sys.platform != "darwin" or platform.machine() != "arm64":
        log.error("voice-dictation needs macOS on Apple Silicon.")
        return 1

    lock = single_instance.acquire()
    if lock is None:
        log.error(
            "voice-dictation is already running (perhaps the login LaunchAgent). Stop it "
            "with `uv run voice-dictation uninstall-launch-agent` or quit the other copy."
        )
        return EXIT_ALREADY_RUNNING

    import Quartz

    from .audio import Recorder
    from .controller import DictationController, DictationPipeline, Worker
    from .hotkey import RightOptionTap
    from .paste import ClipboardPaster
    from .sounds import Sounds
    from .transcriber import WhisperTranscriber

    stop = threading.Event()
    # Handle Ctrl+C and launchd's SIGTERM by stopping the loop between run-loop
    # slices, never by raising inside a macOS callback.
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())

    sounds = Sounds()
    transcriber = WhisperTranscriber(settings.model)
    paster = ClipboardPaster(restore_delay=settings.clipboard_restore_delay)
    pipeline = DictationPipeline(transcriber, paster, sounds, settings)
    worker = Worker(transcriber, pipeline)
    controller = DictationController(Recorder(), worker.submit, sounds, settings)
    tap = RightOptionTap(controller.press, controller.release, controller.cancel)

    _check_permissions()
    worker.start()
    tap_started = False
    try:
        while not worker.ready.wait(0.25):
            if stop.is_set():
                return 0
        if worker.load_error is not None:
            log.error("Could not load the Whisper model: %s", worker.load_error)
            return 1

        warned = False
        while not (tap_started := tap.start()):
            if not warned:
                log.warning(
                    "Waiting for Input Monitoring permission for %s "
                    "(System Settings > Privacy & Security > Input Monitoring)...",
                    permission_target(),
                )
                warned = True
            if stop.wait(2.0):
                return 0

        log.info("Ready. Hold Right Option to dictate, release to paste. Ctrl+C quits.")
        while not stop.is_set():
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.25, False)
            controller.tick()
        log.info("Stopping.")
        return 0
    finally:
        if tap_started:
            tap.stop()
        controller.cancel("shutting down")
        worker.stop()
        lock.close()
