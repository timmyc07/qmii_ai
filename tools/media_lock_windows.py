#!/usr/bin/env python3
"""Cross-platform process lock used to serialize local media generation."""
from __future__ import annotations

import contextlib
import os
import tempfile
import time
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

LOCK_FILE = Path(os.environ.get("MEDIA_LOCK_FILE", str(Path(tempfile.gettempdir()) / "media-task.lock")))


class MediaLockError(RuntimeError):
    """Raised when the media lock cannot be acquired in time."""


@contextlib.contextmanager
def media_lock(exclusive: bool, wait_timeout: int = 3600):
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    acquired = False
    try:
        deadline = time.monotonic() + wait_timeout
        while True:
            try:
                if os.name == "nt":
                    os.lseek(handle, 0, os.SEEK_SET)
                    if os.path.getsize(LOCK_FILE) == 0:
                        os.write(handle, b"0")
                    os.lseek(handle, 0, os.SEEK_SET)
                    msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
                else:
                    mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                    fcntl.flock(handle, mode | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise MediaLockError(f"media lock busy after {wait_timeout}s") from None
                time.sleep(2)
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    os.lseek(handle, 0, os.SEEK_SET)
                    msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            os.close(handle)
