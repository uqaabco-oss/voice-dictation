"""Push-to-talk state machine and the transcribe -> clean -> paste pipeline.

``DictationController`` reacts to key events on the main thread and hands
finished recordings to a single ``Worker`` thread, which owns the Whisper model
and processes dictations strictly in order.
"""

from __future__ import annotations

import logging
import math
import queue
import threading
import time
from collections.abc import Callable
from typing import Protocol

import numpy as np

from .audio import loudest_frame_dbfs
from .cleanup import clean_transcript
from .config import SAMPLE_RATE, Settings
from .transcriber import Transcript

log = logging.getLogger(__name__)

# The start sound can leak into the first moments of a recording, so it is left
# out of the silence check.
_IGNORE_START_SECONDS = 0.2


class RecorderLike(Protocol):
    def start(self) -> None: ...
    def stop(self) -> np.ndarray: ...


class TranscriberLike(Protocol):
    def load(self) -> None: ...
    def transcribe(self, audio: np.ndarray) -> Transcript: ...


class PasterLike(Protocol):
    def paste(self, text: str) -> bool: ...


class SoundsLike(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def error(self) -> None: ...


class DictationPipeline:
    """Turns one recording into pasted text."""

    def __init__(
        self,
        transcriber: TranscriberLike,
        paster: PasterLike,
        sounds: SoundsLike,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transcriber = transcriber
        self._paster = paster
        self._sounds = sounds
        self._settings = settings
        self._clock = clock

    def process(self, audio: np.ndarray) -> str | None:
        """Transcribe, clean and paste ``audio``; returns the pasted text, if any."""
        seconds = audio.size / SAMPLE_RATE
        skip = int(_IGNORE_START_SECONDS * SAMPLE_RATE)
        level = loudest_frame_dbfs(audio[skip:] if audio.size > 2 * skip else audio)
        if level == -math.inf:
            log.warning(
                "The microphone delivered only silence (all zeros). If this keeps happening, "
                "check that the app running voice-dictation has Microphone access (see README)."
            )
            self._sounds.error()
            return None
        if level < self._settings.silence_dbfs:
            log.info(
                "Skipped %.1f s recording: too quiet (%.0f dBFS, threshold %.0f).",
                seconds,
                level,
                self._settings.silence_dbfs,
            )
            return None

        started = self._clock()
        transcript = self._transcriber.transcribe(audio)
        elapsed = self._clock() - started
        text = clean_transcript(transcript.text)
        if self._settings.verbose:
            log.info("Raw transcript: %r -> cleaned: %r", transcript.text, text)
        if not text:
            log.info("Nothing to paste (%.1f s recording, %.2f s to transcribe).", seconds, elapsed)
            return None

        if not self._paster.paste(text):
            self._sounds.error()
        log.info(
            "Dictated %d characters (%.1f s recording, %.2f s to transcribe).",
            len(text),
            seconds,
            elapsed,
        )
        return text


class Worker:
    """Single background thread that loads the model and runs the pipeline."""

    def __init__(self, transcriber: TranscriberLike, pipeline: DictationPipeline) -> None:
        self._transcriber = transcriber
        self._pipeline = pipeline
        self._jobs: queue.Queue[np.ndarray | None] = queue.Queue()
        self.ready = threading.Event()
        self.load_error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="dictation-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(self, audio: np.ndarray) -> None:
        self._jobs.put(audio)

    def stop(self, timeout: float = 5.0) -> None:
        self._jobs.put(None)
        self._thread.join(timeout)

    def _run(self) -> None:
        try:
            self._transcriber.load()
        except BaseException as exc:  # reported by the main thread
            self.load_error = exc
            return
        finally:
            self.ready.set()
        while (audio := self._jobs.get()) is not None:
            try:
                self._pipeline.process(audio)
            except Exception:
                log.exception("Dictation failed")


class DictationController:
    """Push-to-talk state machine; call its methods from the main thread only."""

    def __init__(
        self,
        recorder: RecorderLike,
        submit: Callable[[np.ndarray], None],
        sounds: SoundsLike,
        settings: Settings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._recorder = recorder
        self._submit = submit
        self._sounds = sounds
        self._settings = settings
        self._clock = clock
        self._started_at: float | None = None

    @property
    def recording(self) -> bool:
        return self._started_at is not None

    def press(self) -> None:
        if self.recording:
            return
        try:
            self._recorder.start()
        except Exception:
            log.exception("Could not start recording from the microphone")
            self._sounds.error()
            return
        self._started_at = self._clock()
        self._sounds.start()

    def release(self) -> None:
        if self._started_at is None:
            return
        held = self._clock() - self._started_at
        self._started_at = None
        audio = self._recorder.stop()
        if held < self._settings.min_hold_seconds:
            log.debug("Ignored a %.2f s tap.", held)
            return
        self._sounds.stop()
        self._submit(audio)

    def cancel(self, reason: str = "another key was pressed with Right Option") -> None:
        """Discard the current recording (by default: Right Option was used in a shortcut)."""
        if self._started_at is None:
            return
        self._started_at = None
        self._recorder.stop()
        log.info("Dictation cancelled: %s.", reason)

    def tick(self) -> None:
        """Called periodically; ends recordings that hit the length limit."""
        if self._started_at is None:
            return
        if self._clock() - self._started_at >= self._settings.max_record_seconds:
            log.warning(
                "Recording reached %.0f s; stopping and transcribing it.",
                self._settings.max_record_seconds,
            )
            self.release()
