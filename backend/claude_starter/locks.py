from __future__ import annotations

import fcntl
import os
import time
from pathlib import Path
from types import TracebackType

from .errors import AppError, ErrorCode


class FileLock:
    def __init__(
        self,
        path: Path,
        *,
        timeout: float = 0,
        error_code: ErrorCode = ErrorCode.LOCK_UNAVAILABLE,
    ) -> None:
        self.path = path
        self.timeout = timeout
        self.error_code = error_code
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                os.ftruncate(self._fd, 0)
                os.write(self._fd, str(os.getpid()).encode("ascii"))
                return
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    self._fd = None
                    raise AppError(self.error_code) from exc
                time.sleep(0.1)

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "FileLock":
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
