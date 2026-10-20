"""Short macOS system sounds for start, stop and error feedback."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

START_SOUND = "Tink"
STOP_SOUND = "Pop"
ERROR_SOUND = "Basso"


class Sounds:
    def __init__(self) -> None:
        self._sounds: dict[str, Any] = {}
        try:
            from AppKit import NSSound
        except ImportError:
            log.warning("AppKit is unavailable; sounds are disabled.")
            return
        for name in (START_SOUND, STOP_SOUND, ERROR_SOUND):
            sound = NSSound.soundNamed_(name)
            if sound is not None:
                self._sounds[name] = sound

    def start(self) -> None:
        self._play(START_SOUND)

    def stop(self) -> None:
        self._play(STOP_SOUND)

    def error(self) -> None:
        self._play(ERROR_SOUND)

    def _play(self, name: str) -> None:
        sound = self._sounds.get(name)
        if sound is not None:
            sound.stop()  # restart if it is still playing
            sound.play()
