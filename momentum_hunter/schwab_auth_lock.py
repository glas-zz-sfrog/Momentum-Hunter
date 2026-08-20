from __future__ import annotations

"""Cross-process ownership for the user-bound Schwab OAuth state."""

import os
import time
from pathlib import Path
from types import TracebackType


class SchwabAuthLockError(RuntimeError):
    pass


class SchwabAuthStateLock:
    """Hold one byte of a dedicated lock file for one bounded refresh owner."""

    def __init__(
        self,
        secret_path: Path,
        *,
        timeout_seconds: float = 45.0,
        poll_seconds: float = 0.05,
    ) -> None:
        if timeout_seconds <= 0 or poll_seconds <= 0:
            raise ValueError("Schwab auth lock timing must be positive.")
        self.path = secret_path.with_name(f"{secret_path.name}.refresh.lock")
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds
        self._handle = None

    def __enter__(self) -> "SchwabAuthStateLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b", buffering=0)
        if self.path.stat().st_size == 0:
            handle.write(b"0")
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                self._lock(handle)
                self._handle = handle
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    handle.close()
                    raise SchwabAuthLockError(
                        "Timed out waiting for Schwab auth refresh ownership."
                    ) from None
                time.sleep(self.poll_seconds)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        handle = self._handle
        self._handle = None
        if handle is None:
            return
        try:
            self._unlock(handle)
        finally:
            handle.close()

    @staticmethod
    def _lock(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
