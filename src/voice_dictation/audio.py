"""Microphone capture and simple level measurement."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import Any

import numpy as np

from .config import SAMPLE_RATE

# Creates a started-on-demand input stream: (sample_rate, callback) -> stream.
StreamFactory = Callable[[int, Callable[..., None]], Any]


def _sounddevice_stream(sample_rate: int, callback: Callable[..., None]) -> Any:
    import sounddevice

    return sounddevice.InputStream(
        samplerate=sample_rate, channels=1, dtype="float32", callback=callback
    )


class Recorder:
    """Records mono float32 audio between ``start()`` and ``stop()``.

    The input stream is only open while recording, so the macOS microphone
    indicator is only lit while you hold the key.
    """

    def __init__(
        self, sample_rate: int = SAMPLE_RATE, stream_factory: StreamFactory | None = None
    ) -> None:
        self.sample_rate = sample_rate
        self._stream_factory = stream_factory or _sounddevice_stream
        self._stream: Any = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        with self._lock:
            self._chunks = []
        stream = self._stream_factory(self.sample_rate, self._on_audio)
        try:
            stream.start()
        except BaseException:
            stream.close()
            raise
        self._stream = stream

    def stop(self) -> np.ndarray:
        """Stop recording and return the captured samples."""
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
            finally:
                stream.close()
        with self._lock:
            chunks, self._chunks = self._chunks, []
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32, copy=False)

    def _on_audio(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        # Runs on the audio thread: copy, because the buffer is reused.
        mono = np.array(indata[:, 0] if indata.ndim > 1 else indata, dtype=np.float32)
        with self._lock:
            self._chunks.append(mono)


def loudest_frame_dbfs(
    audio: np.ndarray, sample_rate: int = SAMPLE_RATE, frame_seconds: float = 0.05
) -> float:
    """Level of the loudest short frame in dBFS (``-inf`` for digital silence)."""
    if audio.size == 0:
        return -math.inf
    frame = max(1, int(sample_rate * frame_seconds))
    usable = (audio.size // frame) * frame
    frames = audio[:usable].reshape(-1, frame) if usable else audio.reshape(1, -1)
    rms = float(np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1)).max())
    return 20 * math.log10(rms) if rms > 0 else -math.inf
