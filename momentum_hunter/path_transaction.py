"""Cross-process transaction lease for explicit append-only evidence paths."""

from __future__ import annotations

import math
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


_PATH_LOCKS_GUARD = threading.Lock()
_PATH_LOCKS: dict[Path, threading.RLock] = {}
_PATH_LEASE_STATE = threading.local()


class PathTransactionLeaseError(ValueError):
    """Raised when a path transaction lease is configured incorrectly."""


class PathTransactionLeaseTimeoutError(PathTransactionLeaseError):
    """Raised when another process retains the lease past the bounded timeout."""


class PathTransactionLease:
    """Serialize one full read/validate/append/write transaction by target path."""

    def __init__(self, target_path: Path, *, timeout_seconds: float = 5.0) -> None:
        self.target_path = Path(target_path)
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise PathTransactionLeaseError(
                "Path transaction lease timeout must be positive and finite."
            )
        self.timeout_seconds = timeout
        self.resolved_target_path = self.target_path.resolve()
        self.lease_path = self.resolved_target_path.with_name(
            f".{self.resolved_target_path.name}.lock"
        )
        self.thread_lock = _path_lock(self.resolved_target_path)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.thread_lock:
            depths = _lease_depths()
            current_depth = depths.get(self.resolved_target_path, 0)
            if current_depth:
                depths[self.resolved_target_path] = current_depth + 1
                try:
                    yield
                finally:
                    depths[self.resolved_target_path] -= 1
                return

            with _exclusive_path_lease(
                self.lease_path,
                timeout_seconds=self.timeout_seconds,
            ):
                depths[self.resolved_target_path] = 1
                try:
                    yield
                finally:
                    depths.pop(self.resolved_target_path, None)


def _path_lock(path: Path) -> threading.RLock:
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[path] = lock
        return lock


def _lease_depths() -> dict[Path, int]:
    depths = getattr(_PATH_LEASE_STATE, "depths", None)
    if depths is None:
        depths = {}
        _PATH_LEASE_STATE.depths = depths
    return depths


@contextmanager
def _exclusive_path_lease(
    path: Path,
    *,
    timeout_seconds: float,
) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    acquired = False
    last_error: OSError | None = None
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        while not acquired:
            try:
                _lock_file_handle(handle)
                acquired = True
            except OSError as exc:
                last_error = exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PathTransactionLeaseTimeoutError(
                        "Path transaction lease timed out."
                    ) from last_error
                time.sleep(min(0.01, remaining))
        try:
            yield
        finally:
            if acquired:
                _unlock_file_handle(handle)


def _lock_file_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file_handle(handle) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
