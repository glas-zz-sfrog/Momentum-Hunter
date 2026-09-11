"""Science-local, fail-closed raw-read reuse; no durable authority or writer API.

A Windows R oplock is acquired BEFORE reading. It protects cached content, not
the filename or link count. Default/full-audit scopes check each retained path
and singleton identity. Explicit aggregate mode provides bounded content-only
invalidation; its owner separately reconciles namespace notifications and
touched identities. Global historical singleton audits remain explicit.
There is no timestamp-only content cache, background worker, or silent fallback.
Raw files/checkpoints remain authority; every new process rebuilds from them.
"""

from __future__ import annotations

from contextlib import contextmanager
import ctypes as ct
from ctypes import wintypes as wt
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import threading
import time
from typing import Iterator


class VerifiedReadError(RuntimeError):
    """The cached generation cannot prove exact raw/path identity."""


class _Overlapped(ct.Structure):
    _fields_ = [("Internal", ct.c_size_t), ("InternalHigh", ct.c_size_t),
                ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", wt.HANDLE)]


class _Request(ct.Structure):
    _fields_ = [("version", wt.WORD), ("length", wt.WORD),
                ("level", wt.DWORD), ("flags", wt.DWORD)]


class _Response(ct.Structure):
    _fields_ = [("version", wt.WORD), ("length", wt.WORD), ("original", wt.DWORD),
                ("new", wt.DWORD), ("flags", wt.DWORD), ("access", wt.DWORD), ("share", wt.WORD)]


class _FileInfo(ct.Structure):
    _fields_ = [("attributes", wt.DWORD), ("created", wt.FILETIME),
                ("accessed", wt.FILETIME), ("written", wt.FILETIME),
                ("volume", wt.DWORD), ("size_high", wt.DWORD), ("size_low", wt.DWORD),
                ("links", wt.DWORD), ("index_high", wt.DWORD), ("index_low", wt.DWORD)]


# Never free native request memory if an exceptional OS cancellation did not
# complete. This is fail-closed process-lifetime retention, not a valid cache.
_unretired_requests: list[object] = []


def _kernel():
    if os.name != "nt":
        raise VerifiedReadError("Optimized raw-read reuse requires proven local Windows R oplocks.")
    kernel = ct.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateFileW": ([wt.LPCWSTR, wt.DWORD, wt.DWORD, ct.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE], wt.HANDLE),
        "CreateEventW": ([ct.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR], wt.HANDLE),
        "DeviceIoControl": ([wt.HANDLE, wt.DWORD, ct.c_void_p, wt.DWORD, ct.c_void_p, wt.DWORD, ct.c_void_p, ct.POINTER(_Overlapped)], wt.BOOL),
        "GetOverlappedResult": ([wt.HANDLE, ct.POINTER(_Overlapped), ct.POINTER(wt.DWORD), wt.BOOL], wt.BOOL),
        "CancelIoEx": ([wt.HANDLE, ct.POINTER(_Overlapped)], wt.BOOL),
        "WaitForSingleObject": ([wt.HANDLE, wt.DWORD], wt.DWORD),
        "CloseHandle": ([wt.HANDLE], wt.BOOL),
        "GetFileInformationByHandle": ([wt.HANDLE, ct.POINTER(_FileInfo)], wt.BOOL),
        "CreateIoCompletionPort": ([wt.HANDLE, wt.HANDLE, ct.c_size_t, wt.DWORD], wt.HANDLE),
        "GetQueuedCompletionStatus": ([wt.HANDLE, ct.POINTER(wt.DWORD), ct.POINTER(ct.c_size_t), ct.POINTER(ct.c_void_p), wt.DWORD], wt.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


class _CompletionPort:
    """Aggregate content invalidation, NOT a namespace or singleton audit.

    Every request retains its own event and storage until its exact completion
    is dequeued. Only timeout with a NULL request means no queued invalidation.
    No callbacks, threads, shared-reset event, or timestamp coherence inference.
    """

    def __init__(self, kernel) -> None:
        self.kernel = kernel
        self.handle = kernel.CreateIoCompletionPort(wt.HANDLE(-1), None, 0, 0)
        if not self.handle:
            raise VerifiedReadError('Content completion port is unavailable.')
        self.requests = {}
        self.failed = False
        self.checks = 0

    def attach(self, lease) -> None:
        if not self.kernel.CreateIoCompletionPort(lease.handle, self.handle, 0, 0):
            raise VerifiedReadError('Could not associate exact read lease with completion port.')
        self.requests[ct.addressof(lease.overlapped)] = lease

    def _take(self, milliseconds: int = 0) -> bool:
        count, key, address = wt.DWORD(), ct.c_size_t(), ct.c_void_p()
        ok = self.kernel.GetQueuedCompletionStatus(self.handle, ct.byref(count), ct.byref(key), ct.byref(address), milliseconds)
        error = ct.get_last_error()
        if address.value is None:
            if not ok and error == 258:  # WAIT_TIMEOUT, and no request dequeued.
                return False
            self.failed = True
            raise VerifiedReadError('Ambiguous or failed completion-port operation.')
        if key.value != 0:
            self.failed = True
            raise VerifiedReadError('Unexpected content completion key.')
        lease = self.requests.get(address.value)
        if lease is None or lease.completion_dequeued:
            self.failed = True
            raise VerifiedReadError('Unknown or repeated content completion identity.')
        lease.completion_dequeued = True
        self.failed = True  # Successful break, failed I/O and cancellation all invalidate.
        return True

    def check(self) -> None:
        self.checks += 1
        if self.failed:
            raise VerifiedReadError('Content generation invalidated; explicit recovery required.')
        if self._take():
            raise VerifiedReadError('Content generation lost R-coherence; explicit recovery required.')

    def retire(self, lease) -> None:
        deadline = time.monotonic() + 5.0
        while not lease.completion_dequeued:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self._take(max(1, int(remaining * 1000))):
                raise VerifiedReadError('Exact native completion retirement is unproven.')
        self.requests.pop(ct.addressof(lease.overlapped), None)

    def discard_unissued(self, lease) -> None:
        self.requests.pop(ct.addressof(lease.overlapped), None)

    def close(self) -> None:
        if self.requests:
            _unretired_requests.append(self)
            raise VerifiedReadError('Completion port still owns unretired native requests.')
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _handle_identity(kernel, handle) -> tuple[int, int, int]:
    value = _FileInfo()
    if not kernel.GetFileInformationByHandle(handle, ct.byref(value)):
        raise VerifiedReadError("Guarded file-handle identity unavailable.")
    return value.volume, value.index_high << 32 | value.index_low, value.links


class _ReadLease:
    """Private R-only request, held until explicit cancellation completion."""

    def __init__(self, path: Path, kernel, port=None) -> None:
        self.kernel = kernel
        self.handle = None
        self.event = None
        self.pending_request = False
        self.closed = False
        self.port = port
        self.completion_dequeued = False
        self.request = _Request(1, ct.sizeof(_Request), 1, 1)
        self.response = _Response()
        self.overlapped = _Overlapped()
        try:
            # GENERIC_READ, all sharing, OPEN_EXISTING, OVERLAPPED|OPEN_REPARSE_POINT.
            self.handle = kernel.CreateFileW(str(path), 0x80000000, 7, None, 3, 0x40200000, None)
            if self.handle == wt.HANDLE(-1).value:
                self.handle = None
                raise VerifiedReadError(f"Raw read handle unavailable: WinError {ct.get_last_error()}.")
            self.event = kernel.CreateEventW(None, True, False, None)
            if not self.event:
                raise VerifiedReadError(f"Raw read event unavailable: WinError {ct.get_last_error()}.")
            self.overlapped.hEvent = self.event
            if self.port is not None:
                self.port.attach(self)
            ok = kernel.DeviceIoControl(self.handle, 0x00090240, ct.byref(self.request), ct.sizeof(self.request),
                ct.byref(self.response), ct.sizeof(self.response), None, ct.byref(self.overlapped))
            error = ct.get_last_error()
            if ok or error != 997:  # ERROR_IO_PENDING is the documented grant.
                raise VerifiedReadError(f"R-oplock was not granted: WinError {error}; no cache fallback.")
            self.pending_request = True
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self) -> None:
        if self.closed or not self.pending_request:
            raise VerifiedReadError("Raw read lease is closed or absent.")
        if self.port is not None:
            self.port.check()
        count = wt.DWORD()
        completed = self.kernel.GetOverlappedResult(self.handle, ct.byref(self.overlapped), ct.byref(count), False)
        error = ct.get_last_error()
        if completed or error != 996:  # ERROR_IO_INCOMPLETE, not callback timing.
            raise VerifiedReadError("Cached raw generation lost kernel R-coherence; reopen/audit required.")

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.handle is not None and self.pending_request:
            self.kernel.CancelIoEx(self.handle, ct.byref(self.overlapped))
            if self.port is not None:
                try:
                    self.port.retire(self)
                except BaseException:
                    _unretired_requests.append(self)
                    self.kernel.CloseHandle(self.handle)
                    self.handle = None
                    raise
            # A completed break is also signalled. No R-break acknowledgment.
            waited = self.kernel.WaitForSingleObject(self.event, 5000)
            if waited != 0:
                _unretired_requests.append(self)
                self.kernel.CloseHandle(self.handle)
                self.handle = None
                raise VerifiedReadError("Read-lease cancellation not proven; native request retained, fail closed.")
            count = wt.DWORD()
            complete = self.kernel.GetOverlappedResult(self.handle, ct.byref(self.overlapped), ct.byref(count), False)
            if not complete and ct.get_last_error() == 996:
                _unretired_requests.append(self)
                self.kernel.CloseHandle(self.handle)
                self.handle = None
                raise VerifiedReadError("Signalled read lease remained pending; native request retained.")
        elif self.port is not None:
            self.port.discard_unissued(self)
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
        if self.event:
            self.kernel.CloseHandle(self.event)
            self.event = None


def _identity(path: Path) -> tuple[int, ...]:
    value = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or getattr(value, "st_file_attributes", 0) & 0x400:
        raise VerifiedReadError("Raw evidence is not one regular, non-reparse custody file.")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)


def _directory_identity(path: Path) -> tuple[int, int]:
    value = path.stat(follow_symlinks=False)
    if not stat.S_ISDIR(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400:
        raise VerifiedReadError('Guarded raw parent is a reparse/non-directory object.')
    return value.st_dev, value.st_ino


@dataclass
class _Entry:
    raw: bytes
    digest: str
    identity: tuple[int, ...]
    lease: _ReadLease


class VerifiedReads:
    """Rebuildable raw-byte cache for one explicitly supplied local root.

    It does NOT certify a complete directory inventory. Owners must still check
    unknown/new objects and directory identities. Existing registered paths are
    checked individually, including hard-link aliases outside this root.
    """

    def __init__(self, root: Path, *, aggregate_content: bool = False) -> None:
        self.root = Path(root).resolve(strict=True)
        if str(self.root).startswith("\\\\"):
            raise VerifiedReadError("Remote roots are outside R-oplock qualification.")
        self._kernel = _kernel()
        self._port = _CompletionPort(self._kernel) if aggregate_content else None
        self._entries: dict[Path, _Entry] = {}
        self._parents: dict[Path, tuple[int, int]] = {}
        self._closed = False
        self._failed = False
        self._lock = threading.RLock()
        self._depth = 0
        self.counters = {"raw_file_reads": 0, "raw_bytes_read": 0, "cache_hits": 0,
                         "metadata_checks": 0, "boundary_audits": 0}

    def _path(self, path: Path) -> Path:
        path = Path(path).absolute()
        try:
            path.relative_to(self.root)
            if path.resolve(strict=True) != path:
                raise VerifiedReadError("Raw path alias is outside verified identity.")
            parent = path.parent
            while True:
                identity = _directory_identity(parent)
                if parent in self._parents and self._parents[parent] != identity:
                    raise VerifiedReadError('Known raw parent directory identity changed.')
                self._parents[parent] = identity
                if parent == self.root:
                    break
                parent = parent.parent
        except (ValueError, OSError) as exc:
            raise VerifiedReadError("Raw path is missing or escapes its configured root.") from exc
        return path

    def _ensure_open(self) -> None:
        if self._closed or self._failed:
            raise VerifiedReadError("Verified raw generation is closed or failed.")

    def audit_known(self) -> None:
        """Fresh O(known paths) physical audit; never labelled constant-time."""
        with self._lock:
            self._ensure_open()
            self.counters["boundary_audits"] += 1
            try:
                # Parent identity is independent of directory mtime (own append
                # legitimately changes mtime). Audit each shared parent once,
                # then every file identity and kernel R status individually.
                for parent, identity in self._parents.items():
                    if _directory_identity(parent) != identity:
                        raise VerifiedReadError('Known raw parent directory identity changed.')
                for path, entry in self._entries.items():
                    entry.lease.check()
                    if _identity(path) != entry.identity:
                        raise VerifiedReadError("Known raw pathname, metadata or singleton identity changed.")
                    self.counters["metadata_checks"] += 1
                    entry.lease.check()
            except OSError as exc:
                self._failed = True
                raise VerifiedReadError('Known raw file or parent metadata is unavailable.') from exc
            except BaseException:
                self._failed = True
                raise

    def check_content(self) -> None:
        """Bounded aggregate content check; no global path/singleton claim."""
        with self._lock:
            self._ensure_open()
            if self._port is None:
                raise VerifiedReadError('Aggregate content mode was not explicitly selected.')
            try:
                self._port.check()
            except BaseException:
                self._failed = True
                raise

    @contextmanager
    def operation(self) -> Iterator[None]:
        with self._lock:
            outer = self._depth == 0
            if outer:
                self.audit_known()
            self._depth += 1
            try:
                yield
                if outer:
                    self.audit_known()
            finally:
                self._depth -= 1

    def read(self, path: Path) -> bytes:
        with self._lock:
            self._ensure_open()
            path = Path(path).absolute()
            entry = self._entries.get(path)
            try:
                # Inside a guarded operation the shared parent identities are
                # checked at both boundaries; still check this file and its R
                # status for every actual read. Standalone reads validate the
                # full path immediately, as do all first-time cache grants.
                if entry is None or not self._depth:
                    path = self._path(path)
                if entry is not None:
                    entry.lease.check()
                    if _identity(path) != entry.identity:
                        raise VerifiedReadError("Cached raw physical identity changed.")
                    self.counters["metadata_checks"] += 1
                    entry.lease.check()
                    self.counters["cache_hits"] += 1
                    return entry.raw
                before = _identity(path)
                lease = _ReadLease(path, self._kernel, self._port)
                try:
                    import msvcrt

                    # Bind the actual read handle to the guarded object. Stat
                    # before/after alone cannot cover name replacement between
                    # acquisition and opening the subsequent read handle.
                    with path.open("rb") as stream:
                        if _handle_identity(self._kernel, msvcrt.get_osfhandle(stream.fileno())) != _handle_identity(self._kernel, lease.handle):
                            raise VerifiedReadError("Read handle differs from R-guarded raw object.")
                        raw = stream.read()
                    after = _identity(path)
                    lease.check()
                    if before != after or len(raw) != after[2]:
                        raise VerifiedReadError("Raw identity changed during guarded initial read.")
                    self._entries[path] = _Entry(raw, hashlib.sha256(raw).hexdigest(), after, lease)
                except BaseException:
                    lease.close()
                    raise
                self.counters["raw_file_reads"] += 1
                self.counters["raw_bytes_read"] += len(raw)
                return raw
            except OSError as exc:
                self._failed = True
                raise VerifiedReadError('Guarded raw file is missing or unreadable.') from exc
            except BaseException:
                self._failed = True
                raise

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            errors = []
            for entry in self._entries.values():
                try:
                    entry.lease.close()
                except VerifiedReadError as exc:
                    errors.append(exc)
            self._entries.clear()
            self._parents.clear()
            if self._port is not None:
                try:
                    self._port.close()
                except VerifiedReadError as exc:
                    errors.append(exc)
            if errors:
                raise errors[0]

    def __enter__(self) -> "VerifiedReads":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
