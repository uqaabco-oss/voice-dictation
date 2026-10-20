"""Runtime settings shared by the app, the CLI and the launch agent."""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MODEL = "mlx-community/whisper-large-v3-turbo"
# Size of the default model's weights, shown before the first-run download.
DEFAULT_MODEL_DOWNLOAD = "about 1.6 GB"
SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class Settings:
    # Hugging Face repo id or local directory with MLX Whisper weights.
    model: str = DEFAULT_MODEL
    # Whisper language code; None lets Whisper detect the language.
    language: str | None = "en"
    sounds: bool = True
    verbose: bool = False
    # Recordings shorter than this are treated as accidental taps.
    min_hold_seconds: float = 0.3
    # Safety cap in case a key release is ever missed.
    max_record_seconds: float = 300.0
    # Recordings whose loudest 50 ms stays below this level are not transcribed;
    # Whisper tends to invent text ("Thank you.") for silence.
    silence_dbfs: float = -55.0
    # How long the target app gets to read the clipboard before it is restored.
    clipboard_restore_delay: float = 0.5
