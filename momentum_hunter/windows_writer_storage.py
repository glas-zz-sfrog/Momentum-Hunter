"""Physical storage boundary for the dedicated continuous evidence writer."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import threading
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePath
from typing import Iterator

from momentum_hunter.path_transaction import PathTransactionLease


OWNER_LEASE_NAME = ".writer-owner.lock"
OWNER_PROFILE = "continuous-evidence-writer-owner-v1"
PHYSICAL_STORAGE_PROFILE = "windows-handle-pinned-writer-storage-v1"


class WriterPhysicalStorageError(RuntimeError):
    """Raised when the writer cannot preserve its physical storage boundary."""


class WriterOwnershipConflictError(WriterPhysicalStorageError):
    """Raised when another process owns the exact evidence root."""


class WriterStorageCrashAfterTemp(WriterPhysicalStorageError):
    """Synthetic test interruption after a durable temporary write."""


@dataclass(frozen=True)
class WriterOwnerEvidence:
    writer_instance_id: str
    process_id: int
    acquired_at: str
    root_identity: str
    topology_fingerprint: str
    topology_version: int
    lease_identity: str
    lease_name: str = OWNER_LEASE_NAME
    storage_profile: str = PHYSICAL_STORAGE_PROFILE
    profile: str = OWNER_PROFILE


class WriterPhysicalStorage:
    """Hold one root for a process lifetime and commit immutable files safely."""

    def __init__(
        self,
        root: Path,
        *,
        writer_instance_id: str,
        topology_fingerprint: str,
        topology_version: int,
    ) -> None:
        self.root = Path(root)
        self.writer_instance_id = str(writer_instance_id)
        self.topology_fingerprint = str(topology_fingerprint)
        self._lock = threading.RLock()
        self._closed = False
        self._backend: _WindowsStorageBackend | _PortableStorageBackend
        if os.name == "nt":
            self._backend = _WindowsStorageBackend(
                self.root,
                writer_instance_id=self.writer_instance_id,
                topology_fingerprint=self.topology_fingerprint,
                topology_version=topology_version,
            )
        else:
            self._backend = _PortableStorageBackend(
                self.root,
                writer_instance_id=self.writer_instance_id,
                topology_fingerprint=self.topology_fingerprint,
                topology_version=topology_version,
            )

    @property
    def owner_evidence(self) -> WriterOwnerEvidence:
        return self._backend.owner_evidence

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._closed:
            raise WriterPhysicalStorageError("Writer physical storage is closed.")
        with self._lock:
            yield

    def atomic_create(
        self,
        relative_path: PurePath,
        data: bytes,
        *,
        crash_after_temp: bool = False,
    ) -> bool:
        if self._closed:
            raise WriterPhysicalStorageError("Writer physical storage is closed.")
        return self._backend.atomic_create(
            _validated_relative_file(relative_path),
            bytes(data),
            crash_after_temp=crash_after_temp,
        )

    def iter_files(self, relative_directory: PurePath, *, suffix: str) -> tuple[Path, ...]:
        if self._closed:
            raise WriterPhysicalStorageError("Writer physical storage is closed.")
        directory = _validated_relative_directory(relative_directory)
        return self._backend.iter_files(directory, suffix=str(suffix))

    def quarantine_partials(self) -> None:
        if self._closed:
            raise WriterPhysicalStorageError("Writer physical storage is closed.")
        self._backend.quarantine_partials()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._backend.close()


class _PortableStorageBackend:
    """Non-Windows test fallback; Windows is the deployment authority."""

    def __init__(
        self,
        root: Path,
        *,
        writer_instance_id: str,
        topology_fingerprint: str,
        topology_version: int,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lease = PathTransactionLease(
            self.root / "writer-process-lifetime",
            timeout_seconds=0.1,
        )
        self._lease_context = self._lease.transaction()
        try:
            self._lease_context.__enter__()
        except Exception as exc:
            raise WriterOwnershipConflictError(
                "Another physical writer owns this evidence root."
            ) from exc
        for name in (".partial", ".quarantine", "sessions"):
            (self.root / name).mkdir(exist_ok=True)
        self.owner_evidence = _owner_evidence(
            root=self.root,
            writer_instance_id=writer_instance_id,
            topology_fingerprint=topology_fingerprint,
            topology_version=topology_version,
            physical_identity=None,
        )

    def atomic_create(
        self,
        relative_path: PurePath,
        data: bytes,
        *,
        crash_after_temp: bool,
    ) -> bool:
        target = self.root.joinpath(*relative_path.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = self.root / ".partial" / f"{uuid.uuid4().hex}.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if crash_after_temp:
                raise WriterStorageCrashAfterTemp(
                    "Writer crashed after temporary file completion."
                )
            created = True
            try:
                os.link(temp, target)
            except FileExistsError:
                created = False
                if target.read_bytes() != data:
                    raise WriterPhysicalStorageError(
                        "Write-once target already conflicts."
                    )
            temp.unlink(missing_ok=True)
            return created
        except WriterPhysicalStorageError:
            raise
        except Exception:
            temp.unlink(missing_ok=True)
            raise

    def quarantine_partials(self) -> None:
        partial = self.root / ".partial"
        quarantine = self.root / ".quarantine"
        for path in sorted(partial.glob("*.tmp")):
            target = quarantine / path.name
            if target.exists():
                target = quarantine / f"{path.stem}-{uuid.uuid4().hex}.tmp"
            os.replace(path, target)

    def iter_files(self, relative_directory: PurePath, *, suffix: str) -> tuple[Path, ...]:
        root = self.root.joinpath(*relative_directory.parts)
        root.mkdir(parents=True, exist_ok=True)
        return tuple(sorted(path for path in root.rglob(f"*{suffix}") if path.is_file()))

    def close(self) -> None:
        self._lease_context.__exit__(None, None, None)


if os.name == "nt":
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    _GENERIC_READ = 0x80000000
    _GENERIC_WRITE = 0x40000000
    _FILE_LIST_DIRECTORY = 0x0001
    _FILE_TRAVERSE = 0x0020
    _FILE_READ_ATTRIBUTES = 0x0080
    _SYNCHRONIZE = 0x00100000
    _FILE_SHARE_READ = 0x00000001
    _FILE_SHARE_WRITE = 0x00000002
    _FILE_SHARE_DELETE = 0x00000004
    _CREATE_NEW = 1
    _OPEN_EXISTING = 3
    _OPEN_ALWAYS = 4
    _FILE_ATTRIBUTE_DIRECTORY = 0x00000010
    _FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
    _FILE_FLAG_WRITE_THROUGH = 0x80000000
    _FILE_FLAG_SEQUENTIAL_SCAN = 0x08000000
    _FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
    _FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
    _ERROR_FILE_NOT_FOUND = 2
    _ERROR_PATH_NOT_FOUND = 3
    _ERROR_SHARING_VIOLATION = 32
    _ERROR_FILE_EXISTS = 80
    _ERROR_ALREADY_EXISTS = 183
    _FILE_BEGIN = 0

    class _FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", _FILETIME),
            ("ftLastAccessTime", _FILETIME),
            ("ftLastWriteTime", _FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    _KERNEL32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _KERNEL32.CreateFileW.restype = wintypes.HANDLE
    _KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _KERNEL32.CloseHandle.restype = wintypes.BOOL
    _KERNEL32.GetFileInformationByHandle.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
    )
    _KERNEL32.GetFileInformationByHandle.restype = wintypes.BOOL
    _KERNEL32.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _KERNEL32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _KERNEL32.WriteFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _KERNEL32.WriteFile.restype = wintypes.BOOL
    _KERNEL32.ReadFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _KERNEL32.ReadFile.restype = wintypes.BOOL
    _KERNEL32.FlushFileBuffers.argtypes = (wintypes.HANDLE,)
    _KERNEL32.FlushFileBuffers.restype = wintypes.BOOL
    _KERNEL32.SetFilePointerEx.argtypes = (
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    )
    _KERNEL32.SetFilePointerEx.restype = wintypes.BOOL
    _KERNEL32.SetEndOfFile.argtypes = (wintypes.HANDLE,)
    _KERNEL32.SetEndOfFile.restype = wintypes.BOOL
    _KERNEL32.CreateHardLinkW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
    )
    _KERNEL32.CreateHardLinkW.restype = wintypes.BOOL


class _WindowsHandle:
    def __init__(self, value: int, path: Path) -> None:
        self.value = int(value)
        self.path = path
        self.closed = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if not _KERNEL32.CloseHandle(self.value):
            raise _windows_error("CloseHandle failed")


class _WindowsStorageBackend:
    def __init__(
        self,
        root: Path,
        *,
        writer_instance_id: str,
        topology_fingerprint: str,
        topology_version: int,
    ) -> None:
        if os.name != "nt":
            raise WriterPhysicalStorageError("Windows storage requires Windows.")
        self.root = Path(os.path.abspath(root))
        self._directories: dict[tuple[str, ...], _WindowsHandle] = {}
        self._owner_handle: _WindowsHandle | None = None
        try:
            self.root.parent.mkdir(parents=True, exist_ok=True)
            self._base = _open_directory(self.root.parent)
            try:
                self.root.mkdir(exist_ok=True)
            except FileExistsError:
                pass
            root_handle = _open_directory(self.root)
            self._directories[()] = root_handle
            self._owner_handle = self._acquire_owner()
            self.owner_evidence = _owner_evidence(
                root=self.root,
                writer_instance_id=writer_instance_id,
                topology_fingerprint=topology_fingerprint,
                topology_version=topology_version,
                physical_identity=_file_identity(root_handle),
            )
            _rewrite_handle(self._owner_handle, _canonical_owner_bytes(self.owner_evidence))
            for parts in ((".partial",), (".quarantine",), ("sessions",)):
                self._ensure_directory(parts)
        except Exception:
            self.close()
            raise

    def _acquire_owner(self) -> _WindowsHandle:
        path = self.root / OWNER_LEASE_NAME
        try:
            handle = _create_file_handle(
                path,
                desired_access=_GENERIC_READ | _GENERIC_WRITE,
                share_mode=0,
                creation_disposition=_OPEN_ALWAYS,
                flags=_FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_WRITE_THROUGH,
            )
        except OSError as exc:
            if exc.winerror == _ERROR_SHARING_VIOLATION:
                raise WriterOwnershipConflictError(
                    "Another physical writer owns this evidence root."
                ) from exc
            raise
        info = _handle_information(handle)
        if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            handle.close()
            raise WriterPhysicalStorageError("Writer owner lease is a reparse point.")
        if info.nNumberOfLinks != 1:
            handle.close()
            raise WriterPhysicalStorageError(
                "Writer owner lease has an external hard-link alias."
            )
        _require_final_path(handle, path)
        return handle

    def _ensure_directory(self, parts: tuple[str, ...]) -> _WindowsHandle:
        if parts in self._directories:
            return self._directories[parts]
        parent_parts = parts[:-1]
        parent = self._ensure_directory(parent_parts)
        name = _validated_component(parts[-1])
        path = parent.path / name
        try:
            path.mkdir()
        except FileExistsError:
            pass
        handle = _open_directory(path)
        self._directories[parts] = handle
        return handle

    def atomic_create(
        self,
        relative_path: PurePath,
        data: bytes,
        *,
        crash_after_temp: bool,
    ) -> bool:
        parent_parts = tuple(relative_path.parts[:-1])
        target_name = _validated_component(relative_path.parts[-1])
        target_parent = self._ensure_directory(parent_parts)
        target = target_parent.path / target_name
        partial = self._directories[(".partial",)]
        temp = partial.path / f"{uuid.uuid4().hex}.tmp"
        temp_handle: _WindowsHandle | None = None
        try:
            temp_handle = _create_file_handle(
                temp,
                desired_access=_GENERIC_READ | _GENERIC_WRITE,
                share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
                creation_disposition=_CREATE_NEW,
                flags=(
                    _FILE_FLAG_OPEN_REPARSE_POINT
                    | _FILE_FLAG_SEQUENTIAL_SCAN
                    | _FILE_FLAG_WRITE_THROUGH
                ),
            )
            _write_handle(temp_handle, data)
            if crash_after_temp:
                raise WriterStorageCrashAfterTemp(
                    "Writer crashed after temporary file completion."
                )
            created = True
            if not _KERNEL32.CreateHardLinkW(str(target), str(temp), None):
                error = ctypes.get_last_error()
                if error not in {_ERROR_FILE_EXISTS, _ERROR_ALREADY_EXISTS}:
                    raise _windows_error("CreateHardLinkW failed", error)
                created = False
                if self._read_existing(target_parent, target_name) != data:
                    raise WriterPhysicalStorageError(
                        "Write-once target already conflicts."
                    )
            if created:
                target_handle = self._open_existing_file(target_parent, target_name)
                try:
                    target_info = _handle_information(target_handle)
                    if target_info.nNumberOfLinks != 2:
                        raise WriterPhysicalStorageError(
                            "New canonical target has an unexpected hard-link count."
                        )
                    if _file_identity(target_handle) != _file_identity(temp_handle):
                        raise WriterPhysicalStorageError(
                            "Committed target does not identify the completed temporary file."
                        )
                    if _read_handle(target_handle) != data:
                        raise WriterPhysicalStorageError(
                            "Committed target bytes differ from the completed temporary file."
                        )
                finally:
                    target_handle.close()
            temp_handle.close()
            temp_handle = None
            temp.unlink(missing_ok=True)
            committed = self._open_existing_file(target_parent, target_name)
            try:
                if _handle_information(committed).nNumberOfLinks != 1:
                    raise WriterPhysicalStorageError(
                        "Canonical target retains an external hard-link alias."
                    )
            finally:
                committed.close()
            return created
        except WriterPhysicalStorageError:
            if temp_handle is not None:
                temp_handle.close()
            raise
        except Exception:
            if temp_handle is not None:
                temp_handle.close()
            temp.unlink(missing_ok=True)
            raise

    def _open_existing_file(
        self,
        parent: _WindowsHandle,
        name: str,
    ) -> _WindowsHandle:
        path = parent.path / _validated_component(name)
        handle = _create_file_handle(
            path,
            desired_access=_GENERIC_READ | _FILE_READ_ATTRIBUTES,
            share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            creation_disposition=_OPEN_EXISTING,
            flags=_FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_SEQUENTIAL_SCAN,
        )
        info = _handle_information(handle)
        if info.dwFileAttributes & (
            _FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_DIRECTORY
        ):
            handle.close()
            raise WriterPhysicalStorageError(
                "Write-once target is not a regular non-reparse file."
            )
        _require_final_path(handle, path)
        return handle

    def _read_existing(self, parent: _WindowsHandle, name: str) -> bytes:
        handle = self._open_existing_file(parent, name)
        try:
            if _handle_information(handle).nNumberOfLinks != 1:
                raise WriterPhysicalStorageError(
                    "Existing canonical target has an external hard-link alias."
                )
            return _read_handle(handle)
        finally:
            handle.close()

    def quarantine_partials(self) -> None:
        partial = self._directories[(".partial",)]
        quarantine = self._directories[(".quarantine",)]
        for entry in sorted(os.scandir(partial.path), key=lambda item: item.name):
            if not entry.name.endswith(".tmp"):
                continue
            attributes = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
            if attributes & _FILE_ATTRIBUTE_REPARSE_POINT or not entry.is_file(
                follow_symlinks=False
            ):
                raise WriterPhysicalStorageError(
                    "Partial storage contains a non-regular or reparse entry."
                )
            target = quarantine.path / entry.name
            if target.exists():
                target = quarantine.path / f"{Path(entry.name).stem}-{uuid.uuid4().hex}.tmp"
            os.replace(entry.path, target)

    def iter_files(self, relative_directory: PurePath, *, suffix: str) -> tuple[Path, ...]:
        parts = tuple(relative_directory.parts)
        self._ensure_directory(parts)
        results: list[Path] = []

        def visit(current_parts: tuple[str, ...]) -> None:
            current = self._ensure_directory(current_parts)
            for entry in sorted(os.scandir(current.path), key=lambda item: item.name):
                attributes = getattr(
                    entry.stat(follow_symlinks=False), "st_file_attributes", 0
                )
                if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
                    raise WriterPhysicalStorageError(
                        "Writer evidence tree contains a reparse entry."
                    )
                if entry.is_dir(follow_symlinks=False):
                    visit((*current_parts, _validated_component(entry.name)))
                elif entry.is_file(follow_symlinks=False) and entry.name.endswith(suffix):
                    results.append(current.path / entry.name)

        visit(parts)
        return tuple(results)

    def close(self) -> None:
        errors: list[Exception] = []
        if self._owner_handle is not None:
            try:
                self._owner_handle.close()
            except Exception as exc:
                errors.append(exc)
            self._owner_handle = None
        for _parts, handle in sorted(
            self._directories.items(), key=lambda item: len(item[0]), reverse=True
        ):
            try:
                handle.close()
            except Exception as exc:
                errors.append(exc)
        self._directories.clear()
        base = getattr(self, "_base", None)
        if base is not None:
            try:
                base.close()
            except Exception as exc:
                errors.append(exc)
            self._base = None
        if errors:
            raise WriterPhysicalStorageError("Windows writer handles did not close cleanly.")


def _open_directory(path: Path) -> _WindowsHandle:
    handle = _create_file_handle(
        path,
        desired_access=_FILE_LIST_DIRECTORY | _FILE_TRAVERSE | _FILE_READ_ATTRIBUTES | _SYNCHRONIZE,
        share_mode=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        creation_disposition=_OPEN_EXISTING,
        flags=_FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
    )
    info = _handle_information(handle)
    if info.dwFileAttributes & _FILE_ATTRIBUTE_REPARSE_POINT:
        handle.close()
        raise WriterPhysicalStorageError(f"Writer directory is a reparse point: {path.name}.")
    if not info.dwFileAttributes & _FILE_ATTRIBUTE_DIRECTORY:
        handle.close()
        raise WriterPhysicalStorageError(f"Writer directory is not a directory: {path.name}.")
    _require_final_path(handle, path)
    return handle


def _create_file_handle(
    path: Path,
    *,
    desired_access: int,
    share_mode: int,
    creation_disposition: int,
    flags: int,
) -> _WindowsHandle:
    value = _KERNEL32.CreateFileW(
        str(path),
        desired_access,
        share_mode,
        None,
        creation_disposition,
        flags,
        None,
    )
    numeric = ctypes.cast(value, ctypes.c_void_p).value
    if numeric == _INVALID_HANDLE_VALUE:
        raise _windows_error(f"CreateFileW failed for {path.name}")
    return _WindowsHandle(int(numeric), path)


def _handle_information(handle: _WindowsHandle) -> _BY_HANDLE_FILE_INFORMATION:
    info = _BY_HANDLE_FILE_INFORMATION()
    if not _KERNEL32.GetFileInformationByHandle(handle.value, ctypes.byref(info)):
        raise _windows_error("GetFileInformationByHandle failed")
    return info


def _file_identity(handle: _WindowsHandle) -> tuple[int, int, int]:
    info = _handle_information(handle)
    return (
        int(info.dwVolumeSerialNumber),
        int(info.nFileIndexHigh),
        int(info.nFileIndexLow),
    )


def _require_final_path(handle: _WindowsHandle, expected: Path) -> None:
    buffer = ctypes.create_unicode_buffer(32768)
    length = _KERNEL32.GetFinalPathNameByHandleW(handle.value, buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise _windows_error("GetFinalPathNameByHandleW failed")
    actual = _normalized_windows_path(buffer.value)
    wanted = _normalized_windows_path(str(expected))
    if actual != wanted:
        raise WriterPhysicalStorageError(
            f"Writer handle resolved outside its expected path: {expected.name}."
        )


def _normalized_windows_path(value: str) -> str:
    normalized = value
    if normalized.startswith("\\\\?\\UNC\\"):
        normalized = "\\\\" + normalized[8:]
    elif normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return os.path.normcase(os.path.abspath(normalized))


def _write_handle(handle: _WindowsHandle, data: bytes) -> None:
    if len(data) > 0xFFFFFFFF:
        raise WriterPhysicalStorageError("Writer payload exceeds the Windows write limit.")
    if data:
        buffer = ctypes.create_string_buffer(data)
        written = wintypes.DWORD()
        if not _KERNEL32.WriteFile(
            handle.value,
            buffer,
            len(data),
            ctypes.byref(written),
            None,
        ):
            raise _windows_error("WriteFile failed")
        if written.value != len(data):
            raise WriterPhysicalStorageError("WriteFile completed only a partial write.")
    if not _KERNEL32.FlushFileBuffers(handle.value):
        raise _windows_error("FlushFileBuffers failed")


def _rewrite_handle(handle: _WindowsHandle, data: bytes) -> None:
    if not _KERNEL32.SetFilePointerEx(handle.value, 0, None, _FILE_BEGIN):
        raise _windows_error("SetFilePointerEx failed")
    if not _KERNEL32.SetEndOfFile(handle.value):
        raise _windows_error("SetEndOfFile failed")
    _write_handle(handle, data)


def _read_handle(handle: _WindowsHandle) -> bytes:
    info = _handle_information(handle)
    size = (int(info.nFileSizeHigh) << 32) | int(info.nFileSizeLow)
    if size > 64 * 1024 * 1024:
        raise WriterPhysicalStorageError("Writer file exceeds the bounded read limit.")
    if not _KERNEL32.SetFilePointerEx(handle.value, 0, None, _FILE_BEGIN):
        raise _windows_error("SetFilePointerEx failed")
    if not size:
        return b""
    buffer = ctypes.create_string_buffer(size)
    read = wintypes.DWORD()
    if not _KERNEL32.ReadFile(
        handle.value,
        buffer,
        size,
        ctypes.byref(read),
        None,
    ):
        raise _windows_error("ReadFile failed")
    if read.value != size:
        raise WriterPhysicalStorageError("ReadFile returned an incomplete file.")
    return buffer.raw[: read.value]


def _windows_error(label: str, error: int | None = None) -> OSError:
    code = ctypes.get_last_error() if error is None else int(error)
    return OSError(code, f"{label}: {ctypes.FormatError(code).strip()}", None, code)


def _validated_relative_file(path: PurePath) -> PurePath:
    candidate = PurePath(path)
    if candidate.is_absolute() or not candidate.parts:
        raise WriterPhysicalStorageError("Writer target must be a relative file path.")
    for part in candidate.parts:
        _validated_component(part)
    return candidate


def _validated_relative_directory(path: PurePath) -> PurePath:
    candidate = PurePath(path)
    if candidate.is_absolute():
        raise WriterPhysicalStorageError("Writer directory must be relative.")
    for part in candidate.parts:
        _validated_component(part)
    return candidate


def _validated_component(value: str) -> str:
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        "clock$",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
    stem = value.split(".", 1)[0].casefold() if isinstance(value, str) else ""
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or value != value.strip()
        or "/" in value
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or value.endswith((".", " "))
        or not value.isascii()
        or unicodedata.normalize("NFKC", value) != value
        or stem in reserved
    ):
        raise WriterPhysicalStorageError("Writer path component is invalid.")
    return value


def _owner_evidence(
    *,
    root: Path,
    writer_instance_id: str,
    topology_fingerprint: str,
    topology_version: int,
    physical_identity: tuple[int, int, int] | None,
) -> WriterOwnerEvidence:
    root_material = {
        "normalizedPath": os.path.normcase(os.path.abspath(root)),
        "physicalIdentity": physical_identity,
        "topologyFingerprint": topology_fingerprint,
    }
    root_identity = hashlib.sha256(
        json.dumps(root_material, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()
    lease_identity = hashlib.sha256(
        f"{root_identity}:{topology_version}:{OWNER_LEASE_NAME}".encode("ascii")
    ).hexdigest()
    return WriterOwnerEvidence(
        writer_instance_id=writer_instance_id,
        process_id=os.getpid(),
        acquired_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        root_identity=root_identity,
        topology_fingerprint=topology_fingerprint,
        topology_version=int(topology_version),
        lease_identity=lease_identity,
    )


def _canonical_owner_bytes(owner: WriterOwnerEvidence) -> bytes:
    return (
        json.dumps(asdict(owner), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


__all__ = [
    "OWNER_LEASE_NAME",
    "PHYSICAL_STORAGE_PROFILE",
    "WriterOwnerEvidence",
    "WriterOwnershipConflictError",
    "WriterPhysicalStorage",
    "WriterPhysicalStorageError",
    "WriterStorageCrashAfterTemp",
]
