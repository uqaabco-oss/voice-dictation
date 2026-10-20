"""Single-instance lock, model resolution, transcriber wiring and permission hints."""

import sys
import types

import numpy as np
import pytest

from voice_dictation import app, single_instance
from voice_dictation.launch_agent import LABEL
from voice_dictation.transcriber import WhisperTranscriber, resolve_model_dir


def test_single_instance_lock(tmp_path):
    path = tmp_path / "nested" / "voice-dictation.lock"
    first = single_instance.acquire(path)
    assert first is not None
    assert single_instance.acquire(path) is None
    first.close()
    again = single_instance.acquire(path)
    assert again is not None
    again.close()


def test_cached_model_skips_network(monkeypatch):
    hub = pytest.importorskip("huggingface_hub")
    calls = []

    def fake_download(repo_id, local_files_only=False):
        calls.append(local_files_only)
        return "/cache/model"

    monkeypatch.setattr(hub, "snapshot_download", fake_download)
    assert resolve_model_dir("org/model") == "/cache/model"
    assert calls == [True]


def test_missing_model_is_downloaded_once(monkeypatch):
    hub = pytest.importorskip("huggingface_hub")
    from huggingface_hub.errors import LocalEntryNotFoundError

    calls = []

    def fake_download(repo_id, local_files_only=False):
        calls.append(local_files_only)
        if local_files_only:
            raise LocalEntryNotFoundError("not cached")
        return "/cache/model"

    monkeypatch.setattr(hub, "snapshot_download", fake_download)
    assert resolve_model_dir("org/model") == "/cache/model"
    assert calls == [True, False]


def test_transcriber_loads_once_and_passes_options(monkeypatch):
    hub = pytest.importorskip("huggingface_hub")
    monkeypatch.setattr(hub, "snapshot_download", lambda repo_id, local_files_only=False: "/m")
    calls = []

    def fake_transcribe(audio, **kwargs):
        calls.append((audio.size, kwargs))
        return {"text": "  hello  ", "language": "en"}

    monkeypatch.setitem(
        sys.modules, "mlx_whisper", types.SimpleNamespace(transcribe=fake_transcribe)
    )
    transcriber = WhisperTranscriber("org/model")
    transcriber.load()
    result = transcriber.transcribe(np.ones(16000, dtype=np.float32))

    assert result.text == "hello"
    assert len(calls) == 2  # warm-up, then the real clip
    kwargs = calls[1][1]
    assert kwargs["path_or_hf_repo"] == "/m"
    assert kwargs["language"] == "en"
    assert kwargs["condition_on_previous_text"] is False


def test_permission_target_for_launch_agent(monkeypatch):
    monkeypatch.setenv("XPC_SERVICE_NAME", LABEL)
    assert "Python binary" in app.permission_target()


def test_permission_target_for_terminal(monkeypatch):
    monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    assert "iTerm.app" in app.permission_target()


def test_permission_target_inside_tmux(monkeypatch):
    monkeypatch.delenv("XPC_SERVICE_NAME", raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "tmux")
    assert "started the tmux server" in app.permission_target()
