"""Make sure only one dictation process listens at a time (no double pastes)."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from typing import IO

DEFAULT_LOCK_PATH = (
    Path.home() / "Library" / "Application Support" / "voice-dictation" / "voice-dictation.lock"
)


def acquire(path: Path = DEFAULT_LOCK_PATH) -> IO[str] | None:
    """Take an exclusive lock; returns the open lock file, or None if already held.

    Keep the returned file open for the life of the process; the OS releases the
    lock automatically when the process exits, even after a crash.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle
