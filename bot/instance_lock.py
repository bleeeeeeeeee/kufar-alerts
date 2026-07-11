from __future__ import annotations

import fcntl
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def single_instance_lock(lock_path: str | Path | None = None) -> Iterator[None]:
    lock_file = Path(lock_path or Path.cwd() / ".bot.lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise RuntimeError(f"Bot is already running (lock: {lock_file})") from exc

    try:
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
