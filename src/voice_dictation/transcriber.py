"""Local Whisper transcription with mlx-whisper (Apple Silicon GPU)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .config import DEFAULT_MODEL, DEFAULT_MODEL_DOWNLOAD, SAMPLE_RATE

LANGUAGE = "en"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Transcript:
    text: str


def resolve_model_dir(model: str) -> str:
    """Return a local directory for ``model``, downloading it on first use.

    Once the weights are cached, transcription never touches the network:
    mlx-whisper is handed the local directory instead of the repo id.
    """
    from huggingface_hub import snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError

    try:
        return snapshot_download(repo_id=model, local_files_only=True)
    except LocalEntryNotFoundError:
        size = DEFAULT_MODEL_DOWNLOAD if model == DEFAULT_MODEL else "a large file"
        log.info("Downloading Whisper model %s (%s, first run only)...", model, size)
        return snapshot_download(repo_id=model)


class WhisperTranscriber:
    """Loads the model once, then transcribes 16 kHz mono float32 audio.

    MLX keeps per-thread GPU state, so call ``load()`` and ``transcribe()`` from
    the same thread.
    """

    def __init__(self, model: str) -> None:
        self.model = model
        self._model_dir: str | None = None

    def load(self) -> None:
        self._model_dir = resolve_model_dir(self.model)
        log.info("Loading Whisper model %s...", self.model)
        # mlx-whisper caches the loaded model; a short silent clip loads it and
        # warms up the GPU kernels so the first real dictation is fast.
        self.transcribe(np.zeros(SAMPLE_RATE // 2, dtype=np.float32))

    def transcribe(self, audio: np.ndarray) -> Transcript:
        import mlx_whisper

        if self._model_dir is None:
            self._model_dir = resolve_model_dir(self.model)
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=self._model_dir,
            language=LANGUAGE,
            verbose=None,
            # Each dictation is independent; this also avoids repetition loops.
            condition_on_previous_text=False,
        )
        return Transcript(text=str(result.get("text", "")).strip())
