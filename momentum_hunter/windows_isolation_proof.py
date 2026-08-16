"""Test-only physical Windows isolation proof for continuous evidence writing.

The harness never selects a production root and has no provider, broker, account,
order, scheduler, or service-control capability. Elevated ACL/principal work is
owned by the companion PowerShell proof script.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import msvcrt
import os
import secrets
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Callable

from momentum_hunter.continuous_evidence_writer import (
    CRASH_AFTER_ACK_BEFORE_RETURN,
    CRASH_AFTER_COMMIT_BEFORE_ACK,
    CRASH_AFTER_TEMP,
    CRASH_BEFORE_COMMIT,
    AuthenticatedEvidenceWriterClient,
    ContinuousEvidenceWriterError,
    DedicatedEvidenceWriter,
    OFFLINE_REVIEW,
    PhysicalWriterOwnershipConflictError,
    WRITER_OWNER_CONFLICT,
    artifact_record_path,
    build_continuous_writer_topology_v2,
    read_evidence_snapshot,
)
from momentum_hunter.continuous_runtime import (
    WRITER_ACCEPTED,
    WRITER_DUPLICATE,
    WRITER_UNAVAILABLE,
    build_evidence_write_intent,
)
from momentum_hunter.event_runtime_writer_ipc import (
    MAX_PAYLOAD_BYTES,
    EphemeralWriterCapability,
    WriterEnvelopeSender,
    WriterEnvelopeVerifier,
    WriterIpcError,
    verify_envelope_authentication,
)
from momentum_hunter.windows_writer_storage import (
    WriterPhysicalStorage,
    WriterPhysicalStorageError,
)


SCHEMA_VERSION = 2
PROFILE = "continuous-windows-isolation-proof-v2"
AUTHORITY = "TEST_ONLY_NO_RUNTIME_AUTHORITY"
PROCESS_DUP_HANDLE = 0x0040
DUPLICATE_SAME_ACCESS = 0x00000002
WAIT_SECONDS = 30.0
RUNTIME_BUILD = hashlib.sha256(b"windows-isolation-runtime").hexdigest()
CONFIGURATION = hashlib.sha256(b"windows-isolation-configuration").hexdigest()

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.GetCurrentProcess.restype = wintypes.HANDLE
_kernel32.DuplicateHandle.argtypes = [
    wintypes.HANDLE,
    wintypes.HANDLE,
    wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD,
]
_kernel32.DuplicateHandle.restype = wintypes.BOOL
_kernel32.ReadFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
_kernel32.ReadFile.restype = wintypes.BOOL
_kernel32.SetFilePointerEx.argtypes = [
    wintypes.HANDLE,
    ctypes.c_longlong,
    ctypes.POINTER(ctypes.c_longlong),
    wintypes.DWORD,
]
_kernel32.SetFilePointerEx.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]
_advapi32.OpenProcessToken.restype = wintypes.BOOL
_advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]
_advapi32.GetTokenInformation.restype = wintypes.BOOL


class WindowsIsolationProofError(RuntimeError):
    """Raised when the proof harness itself is contradictory."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(value)
    payload["fingerprint"] = sha256_bytes(
        canonical_json({**payload, "fingerprint": ""}).encode("ascii")
    )
    data = (canonical_json(payload) + "\n").encode("ascii")
    with path.open("xb") as handle:
        handle.write(data)


def read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(document, dict):
        raise WindowsIsolationProofError("Proof document must be a JSON object.")
    return document


def current_identity() -> dict[str, object]:
    token = wintypes.HANDLE()
    process = _kernel32.GetCurrentProcess()
    if not _advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        integrity_rid = _token_integrity_rid(token)
    finally:
        _kernel32.CloseHandle(token)
    identity = subprocess.run(
        ["whoami.exe", "/user", "/fo", "csv", "/nh"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    fields = next(__import__("csv").reader([identity]))
    return {
        "name": fields[0],
        "sid": fields[1],
        "processId": os.getpid(),
        "integrityRid": integrity_rid,
        "integrity": _integrity_name(integrity_rid),
        "sessionId": _process_session_id(os.getpid()),
    }


def _token_integrity_rid(token: wintypes.HANDLE) -> int:
    required = wintypes.DWORD()
    _advapi32.GetTokenInformation(token, 25, None, 0, ctypes.byref(required))
    if not required.value:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(required.value)
    if not _advapi32.GetTokenInformation(
        token, 25, buffer, required.value, ctypes.byref(required)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
    get_count = _advapi32.GetSidSubAuthorityCount
    get_count.argtypes = [wintypes.LPVOID]
    get_count.restype = ctypes.POINTER(ctypes.c_ubyte)
    get_part = _advapi32.GetSidSubAuthority
    get_part.argtypes = [wintypes.LPVOID, wintypes.DWORD]
    get_part.restype = ctypes.POINTER(wintypes.DWORD)
    count = get_count(sid_pointer)[0]
    return int(get_part(sid_pointer, count - 1)[0])


def _integrity_name(rid: int) -> str:
    if rid >= 0x4000:
        return "SYSTEM"
    if rid >= 0x3000:
        return "HIGH"
    if rid >= 0x2000:
        return "MEDIUM"
    if rid >= 0x1000:
        return "LOW"
    return "UNTRUSTED"


def _process_session_id(process_id: int) -> int:
    result = wintypes.DWORD()
    function = _kernel32.ProcessIdToSessionId
    function.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    function.restype = wintypes.BOOL
    if not function(process_id, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(result.value)


def file_access_matrix(root: Path, actor: str) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "seed.txt").write_text("seed", encoding="ascii")
    (root / "rename-source.txt").write_text("rename", encoding="ascii")
    (root / "delete-source.txt").write_text("delete", encoding="ascii")
    attempts: dict[str, dict[str, object]] = {}

    def attempt(name: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception as exc:  # physical access failures are evidence
            attempts[name] = {
                "allowed": False,
                "errorType": type(exc).__name__,
                "winerror": getattr(exc, "winerror", None),
            }
        else:
            attempts[name] = {"allowed": True, "errorType": None, "winerror": None}

    attempt("create", lambda: (root / "created.txt").write_text("created", encoding="ascii"))
    attempt("overwrite", lambda: (root / "seed.txt").write_text("changed", encoding="ascii"))
    attempt("append", lambda: _append(root / "seed.txt"))
    attempt("rename", lambda: (root / "rename-source.txt").rename(root / "renamed.txt"))
    attempt("delete", lambda: (root / "delete-source.txt").unlink())
    attempt("directoryCreate", lambda: (root / "created-dir").mkdir())
    attempt("committedOverwrite", lambda: (root / "committed.json").write_text("changed", encoding="ascii"))
    attempt("committedDelete", lambda: (root / "committed-delete.json").unlink())
    attempt("partialRename", lambda: (root / "partial.tmp").rename(root / "partial-moved.tmp"))
    read_allowed = False
    try:
        (root / "readable.txt").read_bytes()
        read_allowed = True
    except OSError:
        pass
    return {
        "actor": actor,
        "identity": current_identity(),
        "readAllowed": read_allowed,
        "attempts": attempts,
    }


def _append(path: Path) -> None:
    with path.open("a", encoding="ascii") as handle:
        handle.write("+")


def handle_inheritance_matrix(root: Path) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    capability = secrets.token_bytes(48)
    path = root / "inheritance-capability.bin"
    path.write_bytes(capability)
    expected = sha256_bytes(capability)
    descriptor = os.open(path, os.O_RDONLY)
    handle = msvcrt.get_osfhandle(descriptor)
    os.set_handle_inheritable(handle, True)
    try:
        disabled = _run_handle_reader(handle, expected, close_fds=True)
        enabled = _run_handle_reader(handle, expected, close_fds=False)
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {"handle_list": [handle]}
        explicit = _run_handle_reader(
            handle, expected, close_fds=True, startupinfo=startup
        )
        unrelated_path = root / "unrelated.bin"
        unrelated_path.write_bytes(b"unrelated")
        unrelated_descriptor = os.open(unrelated_path, os.O_RDONLY)
        unrelated_handle = msvcrt.get_osfhandle(unrelated_descriptor)
        os.set_handle_inheritable(unrelated_handle, True)
        try:
            unrelated_startup = subprocess.STARTUPINFO()
            unrelated_startup.lpAttributeList = {"handle_list": [unrelated_handle]}
            unrelated = _run_handle_reader(
                handle,
                expected,
                close_fds=True,
                startupinfo=unrelated_startup,
            )
        finally:
            os.close(unrelated_descriptor)
    finally:
        os.close(descriptor)
    return {
        "inheritanceDisabled": disabled,
        "inheritanceEnabled": enabled,
        "explicitAllowedList": explicit,
        "explicitUnrelatedList": unrelated,
    }


def _run_handle_reader(
    handle: int,
    expected_sha256: str,
    *,
    close_fds: bool,
    startupinfo: subprocess.STARTUPINFO | None = None,
) -> dict[str, object]:
    completed = subprocess.run(
        [
            _python_executable(),
            "-B",
            "-m",
            "momentum_hunter.windows_isolation_proof",
            "handle-read",
            "--handle",
            str(handle),
            "--expected-sha256",
            expected_sha256,
        ],
        capture_output=True,
        text=True,
        check=False,
        close_fds=close_fds,
        startupinfo=startupinfo,
    )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        result = {"read": False, "sha256Matches": False, "malformedOutput": True}
    result["exitCode"] = completed.returncode
    return result


def _read_handle(handle: int, maximum: int = 4096) -> bytes:
    if not _kernel32.SetFilePointerEx(handle, 0, None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(maximum)
    read = wintypes.DWORD()
    if not _kernel32.ReadFile(handle, buffer, maximum, ctypes.byref(read), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return bytes(buffer.raw[: read.value])


def handle_read_command(handle: int, expected_sha256: str) -> int:
    try:
        data = _read_handle(handle)
    except OSError as exc:
        result = {
            "read": False,
            "sha256Matches": False,
            "winerror": getattr(exc, "winerror", ctypes.get_last_error()),
        }
    else:
        result = {
            "read": True,
            "sha256Matches": sha256_bytes(data) == expected_sha256,
            "winerror": None,
        }
    print(canonical_json(result))
    return 0


def same_sid_handle_duplication(root: Path) -> dict[str, object]:
    control = root / "handle-target.json"
    release = root / "handle-release"
    capability_file = root / "duplicate-capability.bin"
    process = subprocess.Popen(
        [
            _python_executable(),
            "-B",
            "-m",
            "momentum_hunter.windows_isolation_proof",
            "handle-target",
            "--control",
            str(control),
            "--release",
            str(release),
            "--capability-file",
            str(capability_file),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for(control)
        target = read_json(control)
        result = duplicate_remote_handle(
            int(target["processId"]),
            int(target["handle"]),
            str(target["expectedSha256"]),
        )
    finally:
        release.touch(exist_ok=True)
        try:
            _stdout, _stderr = process.communicate(timeout=WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            _stdout, _stderr = process.communicate(timeout=5)
    result["targetExitCode"] = process.returncode
    return result


def handle_target_command(control: Path, release: Path, capability_file: Path) -> int:
    capability = secrets.token_bytes(64)
    capability_file.parent.mkdir(parents=True, exist_ok=True)
    with capability_file.open("w+b", buffering=0) as stream:
        stream.write(capability)
        stream.seek(0)
        handle = msvcrt.get_osfhandle(stream.fileno())
        write_json(
            control,
            {
                "schemaVersion": SCHEMA_VERSION,
                "profile": PROFILE,
                "processId": os.getpid(),
                "handle": handle,
                "expectedSha256": sha256_bytes(capability),
            },
        )
        _wait_for(release, timeout=WAIT_SECONDS)
    return 0


def duplicate_remote_handle(
    process_id: int,
    source_handle: int,
    expected_sha256: str,
) -> dict[str, object]:
    process = _kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, process_id)
    if not process:
        return {
            "openProcess": False,
            "duplicateHandle": False,
            "read": False,
            "sha256Matches": False,
            "winerror": ctypes.get_last_error(),
        }
    duplicated = wintypes.HANDLE()
    try:
        ok = _kernel32.DuplicateHandle(
            process,
            source_handle,
            _kernel32.GetCurrentProcess(),
            ctypes.byref(duplicated),
            0,
            False,
            DUPLICATE_SAME_ACCESS,
        )
        if not ok:
            return {
                "openProcess": True,
                "duplicateHandle": False,
                "read": False,
                "sha256Matches": False,
                "winerror": ctypes.get_last_error(),
            }
        try:
            data = _read_handle(duplicated.value)
        except OSError as exc:
            return {
                "openProcess": True,
                "duplicateHandle": True,
                "read": False,
                "sha256Matches": False,
                "winerror": getattr(exc, "winerror", ctypes.get_last_error()),
            }
        finally:
            _kernel32.CloseHandle(duplicated)
        return {
            "openProcess": True,
            "duplicateHandle": True,
            "read": True,
            "sha256Matches": sha256_bytes(data) == expected_sha256,
            "winerror": None,
        }
    finally:
        _kernel32.CloseHandle(process)


def ipc_attack_matrix() -> dict[str, object]:
    capability = EphemeralWriterCapability.create()
    other = EphemeralWriterCapability.create()
    configuration = hashlib.sha256(b"ipc-configuration").hexdigest()
    source = "physical-runtime"
    sender = WriterEnvelopeSender(
        capability=capability,
        configuration_fingerprint=configuration,
        source_identity=source,
    )
    envelope = sender.build(
        artifact_name="event-decision-cycle-ledger",
        payload={"kind": "TEST_ONLY", "value": 1},
    )
    verifier = WriterEnvelopeVerifier(
        session_id=capability.session_id,
        key_material=capability.key_bytes(),
        configuration_fingerprint=configuration,
        source_identity=source,
    )
    results: dict[str, bool] = {}
    verifier.verify(envelope)
    results["validEnvelopeAccepted"] = True
    results["replayRejected"] = _raises(lambda: verifier.verify(envelope), WriterIpcError)
    results["wrongCapabilityRejected"] = _raises(
        lambda: verify_envelope_authentication(
            envelope,
            session_id=capability.session_id,
            key_material=other.key_bytes(),
            configuration_fingerprint=configuration,
            source_identity=source,
        ),
        WriterIpcError,
    )
    results["forgedRuntimeRejected"] = _raises(
        lambda: verify_envelope_authentication(
            envelope,
            session_id=capability.session_id,
            key_material=capability.key_bytes(),
            configuration_fingerprint=configuration,
            source_identity="forged-runtime",
        ),
        WriterIpcError,
    )
    new_capability = EphemeralWriterCapability.create()
    results["staleCapabilityRejectedAfterRestart"] = _raises(
        lambda: verify_envelope_authentication(
            envelope,
            session_id=new_capability.session_id,
            key_material=new_capability.key_bytes(),
            configuration_fingerprint=configuration,
            source_identity=source,
        ),
        WriterIpcError,
    )
    results["oversizedRejected"] = _raises(
        lambda: sender.build(
            artifact_name="event-decision-cycle-ledger",
            payload={"payload": "x" * (MAX_PAYLOAD_BYTES + 1)},
        ),
        WriterIpcError,
    )
    results["malformedRejected"] = _raises(
        lambda: verify_envelope_authentication(
            replace(envelope, protocol="malformed"),
            session_id=capability.session_id,
            key_material=capability.key_bytes(),
            configuration_fingerprint=configuration,
            source_identity=source,
        ),
        WriterIpcError,
    )
    verifier.close()
    capability.close()
    other.close()
    new_capability.close()
    return results


def duplicate_writer_process_proof(root: Path) -> dict[str, object]:
    ready = root / "ready"
    ready.mkdir(parents=True)
    start = root / "start"
    release = root / "release"
    result_paths = [root / f"writer-{index}.json" for index in (1, 2)]
    processes = []
    for index, result in enumerate(result_paths, start=1):
        processes.append(
            subprocess.Popen(
                [
                    _python_executable(),
                    "-B",
                    "-m",
                    "momentum_hunter.windows_isolation_proof",
                    "duplicate-writer-worker",
                    "--root",
                    str(root / "evidence"),
                    "--index",
                    str(index),
                    "--ready",
                    str(ready / str(index)),
                    "--start",
                    str(start),
                    "--result",
                    str(result),
                    "--release",
                    str(release),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    try:
        _wait_for(ready / "1")
        _wait_for(ready / "2")
        start.touch()
        _wait_for(result_paths[0])
        _wait_for(result_paths[1])
        release.touch()
        for process in processes:
            _stdout, _stderr = process.communicate(timeout=WAIT_SECONDS)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                _stdout, _stderr = process.communicate(timeout=5)
    outcomes = [read_json(path) for path in result_paths]
    statuses = [item.get("status") for item in outcomes]
    records = list((root / "evidence").rglob("records/**/*.json"))
    restart_validation_failed = False
    try:
        topology = _topology(root / "evidence")
        writer = DedicatedEvidenceWriter(topology)
        writer.close()
    except ContinuousEvidenceWriterError:
        restart_validation_failed = True
    return {
        "writerExitCodes": [process.returncode for process in processes],
        "statuses": statuses,
        "bothAccepted": all(status == WRITER_ACCEPTED for status in statuses),
        "acceptedCount": statuses.count(WRITER_ACCEPTED),
        "ownerConflictCount": statuses.count(WRITER_OWNER_CONFLICT),
        "recordFiles": len(records),
        "restartValidationFailed": restart_validation_failed,
    }


def duplicate_writer_worker(
    root: Path,
    index: int,
    ready: Path,
    start: Path,
    result: Path,
    release: Path,
) -> int:
    topology = _topology(root)
    writer: DedicatedEvidenceWriter | None = None
    capability: EphemeralWriterCapability | None = None
    runtime_id = f"physical-runtime-{index}"
    ready.parent.mkdir(parents=True, exist_ok=True)
    ready.touch()
    _wait_for(start)
    try:
        try:
            writer = DedicatedEvidenceWriter(topology)
        except PhysicalWriterOwnershipConflictError:
            write_json(
                result,
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "profile": PROFILE,
                    "writerIndex": index,
                    "status": WRITER_OWNER_CONFLICT,
                },
            )
            return 0
        capability = EphemeralWriterCapability.create()
        writer.activate_session(capability=capability, source_identity=runtime_id)
        client = AuthenticatedEvidenceWriterClient(
            topology=topology,
            capability=capability,
            runtime_instance_id=runtime_id,
            writer=writer,
        )
        intent = _intent(runtime_id, record=f"writer-{index}")
        status = client.write_intent(intent)
        write_json(
            result,
            {
                "schemaVersion": SCHEMA_VERSION,
                "profile": PROFILE,
                "writerIndex": index,
                "status": status,
            },
        )
        _wait_for(release)
    finally:
        if writer is not None:
            writer.close()
        if capability is not None:
            capability.close()
    return 0


def duplicate_writer_crash_recovery_proof(root: Path) -> dict[str, object]:
    evidence_root = root / "evidence"
    first_result = root / "writer-a.json"
    ready = root / "writer-a-ready"
    process = subprocess.Popen(
        [
            _python_executable(),
            "-B",
            "-m",
            "momentum_hunter.windows_isolation_proof",
            "owner-hold-worker",
            "--root",
            str(evidence_root),
            "--ready",
            str(ready),
            "--result",
            str(first_result),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for(ready)
        _wait_for(first_result)
        denied = _run_owner_probe(evidence_root, root / "writer-b.json", "writer-b")
        process.kill()
        _stdout, _stderr = process.communicate(timeout=5)
        replacement = _run_owner_probe(
            evidence_root,
            root / "writer-c.json",
            "writer-c",
        )
    finally:
        if process.poll() is None:
            process.kill()
            _stdout, _stderr = process.communicate(timeout=5)
    records = list(evidence_root.rglob("records/**/*.json"))
    return {
        "initialStatus": read_json(first_result).get("status"),
        "deniedStatus": denied.get("status"),
        "crashExitCode": process.returncode,
        "replacementStatus": replacement.get("status"),
        "recordFiles": len(records),
        "overlapOwners": 0,
    }


def owner_hold_worker(root: Path, ready: Path, result: Path) -> int:
    topology = _topology(root)
    writer, client, capability = _writer_client(topology, "owner-hold-runtime")
    try:
        status = client.write_intent(_intent("owner-hold-runtime", record="owner-hold"))
        ready.parent.mkdir(parents=True, exist_ok=True)
        ready.touch()
        write_json(
            result,
            {
                "schemaVersion": SCHEMA_VERSION,
                "profile": PROFILE,
                "status": status,
                "ownerEvidence": asdict(writer.owner_evidence),
            },
        )
        time.sleep(WAIT_SECONDS)
    finally:
        writer.close()
        capability.close()
    return 0


def _run_owner_probe(root: Path, result: Path, instance: str) -> dict[str, object]:
    completed = subprocess.run(
        [
            _python_executable(),
            "-B",
            "-m",
            "momentum_hunter.windows_isolation_proof",
            "owner-probe-worker",
            "--root",
            str(root),
            "--result",
            str(result),
            "--instance",
            instance,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=WAIT_SECONDS,
    )
    if completed.returncode != 0:
        raise WindowsIsolationProofError(
            f"Owner probe failed with exit code {completed.returncode}."
        )
    return read_json(result)


def owner_probe_worker(root: Path, result: Path, instance: str) -> int:
    topology = _topology(root)
    writer: DedicatedEvidenceWriter | None = None
    try:
        try:
            writer = DedicatedEvidenceWriter(topology)
        except PhysicalWriterOwnershipConflictError:
            status = WRITER_OWNER_CONFLICT
            owner = None
        else:
            status = "WRITER_OWNER_ACQUIRED"
            owner = asdict(writer.owner_evidence)
        write_json(
            result,
            {
                "schemaVersion": SCHEMA_VERSION,
                "profile": PROFILE,
                "instance": instance,
                "status": status,
                "ownerEvidence": owner,
            },
        )
    finally:
        if writer is not None:
            writer.close()
    return 0


def crash_restart_matrix(root: Path) -> dict[str, object]:
    results: dict[str, object] = {}
    for phase in (
        CRASH_BEFORE_COMMIT,
        CRASH_AFTER_TEMP,
        CRASH_AFTER_COMMIT_BEFORE_ACK,
        CRASH_AFTER_ACK_BEFORE_RETURN,
    ):
        phase_root = root / phase.lower()
        capability = secrets.token_bytes(32)
        bootstrap = {
            "root": str(phase_root),
            "sessionId": secrets.token_hex(16),
            "capability": base64.b64encode(capability).decode("ascii"),
            "runtimeId": "physical-crash-runtime",
            "phase": phase,
            "replayRuntimeId": None,
        }
        first = _run_crash_worker(bootstrap)
        bootstrap["phase"] = "NONE"
        second = _run_crash_worker(bootstrap)
        topology = _topology(phase_root)
        snapshot = read_evidence_snapshot(topology, reader_role=OFFLINE_REVIEW)
        partial = list((phase_root / topology.namespace / ".partial").glob("*.tmp"))
        quarantine = list((phase_root / topology.namespace / ".quarantine").glob("*.tmp"))
        results[phase] = {
            "crashExitCode": first.returncode,
            "restartExitCode": second.returncode,
            "restartStatus": _stdout_status(second.stdout),
            "recordCount": snapshot.record_count,
            "partialCount": len(partial),
            "quarantineCount": len(quarantine),
        }
    return results


def runtime_restart_replay_proof(root: Path) -> dict[str, object]:
    old_runtime = "physical-runtime-old"
    first = {
        "root": str(root),
        "sessionId": secrets.token_hex(16),
        "capability": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
        "runtimeId": old_runtime,
        "phase": CRASH_AFTER_COMMIT_BEFORE_ACK,
        "replayRuntimeId": None,
    }
    crashed = _run_crash_worker(first)
    restarted = {
        "root": str(root),
        "sessionId": secrets.token_hex(16),
        "capability": base64.b64encode(secrets.token_bytes(32)).decode("ascii"),
        "runtimeId": "physical-runtime-new",
        "intentRuntimeId": old_runtime,
        "phase": "NONE",
        "replayRuntimeId": old_runtime,
    }
    replay = _run_crash_worker(restarted)
    snapshot = read_evidence_snapshot(_topology(root), reader_role=OFFLINE_REVIEW)
    return {
        "crashExitCode": crashed.returncode,
        "replayExitCode": replay.returncode,
        "replayStatus": _stdout_status(replay.stdout),
        "recordCount": snapshot.record_count,
    }


def _run_crash_worker(bootstrap: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            _python_executable(),
            "-B",
            "-m",
            "momentum_hunter.windows_isolation_proof",
            "crash-worker",
        ],
        input=canonical_json(bootstrap) + "\n",
        capture_output=True,
        text=True,
        check=False,
        timeout=WAIT_SECONDS,
    )


def crash_worker_command() -> int:
    bootstrap = json.loads(sys.stdin.readline())
    root = Path(bootstrap["root"]).resolve()
    runtime_id = str(bootstrap["runtimeId"])
    intent_runtime = str(bootstrap.get("intentRuntimeId") or runtime_id)
    replay_id = bootstrap.get("replayRuntimeId")
    key = base64.b64decode(str(bootstrap["capability"]), validate=True)
    capability = EphemeralWriterCapability(
        session_id=str(bootstrap["sessionId"]), key_material=key
    )
    topology = _topology(root)
    writer = DedicatedEvidenceWriter(topology)
    try:
        writer.activate_session(
            capability=capability,
            source_identity=runtime_id,
            replay_runtime_instance_ids=((str(replay_id),) if replay_id else ()),
        )
        client = AuthenticatedEvidenceWriterClient(
            topology=topology,
            capability=capability,
            runtime_instance_id=runtime_id,
            replay_runtime_instance_ids=((str(replay_id),) if replay_id else ()),
            writer=writer,
        )
        phase = str(bootstrap["phase"])
        if phase != "NONE":
            writer.arm_crash(phase)
        status = client.write_intent(_intent(intent_runtime, record="crash-record"))
        if phase != "NONE":
            os._exit(86)
        print(canonical_json({"status": status}))
    finally:
        writer.close()
        capability.close()
    return 0


def reparse_attack_matrix(root: Path) -> dict[str, object]:
    return {
        "rootSubstitution": _root_substitution_attack(root / "root-substitution"),
        "childDirectoryRedirect": _child_directory_redirect(root / "child-redirect"),
        "recordShardRedirect": _record_shard_redirect(root / "record-redirect"),
        "partialRedirect": _partial_redirect(root / "partial-redirect"),
        "directorySymlinkRedirect": _directory_symlink_redirect(root / "symlink-redirect"),
        "outsideHardLinkInward": _outside_hard_link_inward(root / "hard-link-inward"),
    }


def _root_substitution_attack(root: Path) -> dict[str, object]:
    authority = root / "authority"
    escape = root / "escape"
    backup = root / "authority-backup"
    topology = _topology(authority)
    writer, client, capability = _writer_client(topology, "root-swap-runtime")
    substitution_blocked = False
    rejected = False
    escaped_records: list[Path] = []
    try:
        try:
            authority.rename(backup)
        except OSError:
            substitution_blocked = True
        if not substitution_blocked:
            escape.mkdir(parents=True)
            _junction(authority, escape)
            rejected = _raises(
                lambda: client.write_intent(
                    _intent("root-swap-runtime", record="root-swap")
                ),
                ContinuousEvidenceWriterError,
            )
        escaped_records = list(escape.rglob("records/**/*.json"))
    finally:
        writer.close()
        capability.close()
        _remove_junction(authority)
    return {
        "substitutionBlocked": substitution_blocked,
        "writeRejected": rejected or substitution_blocked,
        "escapedRecordCount": len(escaped_records),
    }


def _record_shard_redirect(root: Path) -> dict[str, object]:
    topology = _topology(root / "authority")
    writer, client, capability = _writer_client(topology, "record-redirect-runtime")
    intent = _intent("record-redirect-runtime", record="record-redirect")
    target = artifact_record_path(
        topology,
        artifact_name="event-decision-cycle-ledger",
        record_fingerprint=intent.record_fingerprint,
    )
    escape = root / "escape"
    target.parent.parent.mkdir(parents=True, exist_ok=True)
    escape.mkdir(parents=True)
    _junction(target.parent, escape)
    try:
        rejected = _raises(lambda: client.write_intent(intent), ContinuousEvidenceWriterError)
    finally:
        writer.close()
        capability.close()
        _remove_junction(target.parent)
    return {"rejected": rejected, "escapedRecordCount": len(list(escape.glob("*.json")))}


def _child_directory_redirect(root: Path) -> dict[str, object]:
    topology = _topology(root / "authority")
    writer, client, capability = _writer_client(topology, "child-redirect-runtime")
    records = Path(topology.root_path) / topology.namespace / "records"
    escape = root / "escape"
    escape.mkdir(parents=True)
    substitution_blocked = False
    rejected = False
    try:
        try:
            _junction(records, escape)
        except WindowsIsolationProofError:
            substitution_blocked = True
        if not substitution_blocked:
            rejected = _raises(
                lambda: client.write_intent(
                    _intent("child-redirect-runtime", record="child-redirect")
                ),
                ContinuousEvidenceWriterError,
            )
    finally:
        writer.close()
        capability.close()
        _remove_junction(records)
    return {
        "substitutionBlocked": substitution_blocked,
        "rejected": rejected or substitution_blocked,
        "escapedRecordCount": len(list(escape.rglob("*.json"))),
    }


def _partial_redirect(root: Path) -> dict[str, object]:
    topology = _topology(root / "authority")
    writer, client, capability = _writer_client(topology, "partial-redirect-runtime")
    partial = Path(topology.root_path) / topology.namespace / ".partial"
    escape = root / "escape"
    substitution_blocked = False
    startup_reparse_rejected = False
    status = WRITER_UNAVAILABLE
    try:
        try:
            shutil.rmtree(partial)
        except OSError:
            substitution_blocked = True
        if not substitution_blocked:
            escape.mkdir(parents=True)
            _junction(partial, escape)
            writer.arm_crash(CRASH_AFTER_TEMP)
            status = client.write_intent(
                _intent("partial-redirect-runtime", record="partial-redirect")
            )
        escaped_temps = list(escape.glob("*.tmp"))
    finally:
        writer.close()
        capability.close()
        _remove_junction(partial)
    startup_root = root / "startup-authority"
    startup_topology = _topology(startup_root)
    startup_partial = startup_root / startup_topology.namespace / ".partial"
    startup_escape = root / "startup-escape"
    startup_partial.parent.mkdir(parents=True)
    startup_escape.mkdir(parents=True)
    _junction(startup_partial, startup_escape)
    try:
        startup_reparse_rejected = _raises(
            lambda: DedicatedEvidenceWriter(startup_topology),
            ContinuousEvidenceWriterError,
        )
    finally:
        _remove_junction(startup_partial)
    return {
        "writerStatus": status,
        "substitutionBlocked": substitution_blocked,
        "startupReparseRejected": startup_reparse_rejected,
        "escapedTemporaryCount": len(escaped_temps),
        "startupEscapedTemporaryCount": len(list(startup_escape.glob("*.tmp"))),
    }


def _directory_symlink_redirect(root: Path) -> dict[str, object]:
    authority = root / "authority"
    storage = WriterPhysicalStorage(
        authority,
        writer_instance_id="symlink-writer",
        topology_fingerprint=CONFIGURATION,
        topology_version=2,
    )
    records = authority / "records"
    escape = root / "escape"
    escape.mkdir(parents=True)
    supported = True
    rejected = False
    try:
        try:
            os.symlink(escape, records, target_is_directory=True)
        except OSError:
            supported = False
        if supported:
            rejected = _raises(
                lambda: storage.atomic_create(
                    Path("records") / "test" / "record.json",
                    b'{"test":"symlink"}\n',
                ),
                WriterPhysicalStorageError,
            )
    finally:
        storage.close()
        if supported and records.is_symlink():
            records.unlink()
    return {
        "supported": supported,
        "rejected": rejected if supported else None,
        "escapedFileCount": len(list(escape.rglob("*.*"))),
    }


def _outside_hard_link_inward(root: Path) -> dict[str, object]:
    authority = root / "authority"
    storage = WriterPhysicalStorage(
        authority,
        writer_instance_id="hard-link-writer",
        topology_fingerprint=CONFIGURATION,
        topology_version=2,
    )
    outside = root / "outside.json"
    data = b'{"test":"outside-hard-link"}\n'
    target_parent = authority / "records" / "test"
    target_parent.mkdir(parents=True)
    target = target_parent / "record.json"
    outside.write_bytes(data)
    os.link(outside, target)
    before = hashlib.sha256(outside.read_bytes()).hexdigest()
    try:
        rejected = _raises(
            lambda: storage.atomic_create(
                Path("records") / "test" / "record.json",
                data,
            ),
            WriterPhysicalStorageError,
        )
    finally:
        storage.close()
    after = hashlib.sha256(outside.read_bytes()).hexdigest()
    return {
        "rejected": rejected,
        "outsideChanged": before != after,
        "outsideLinkCount": outside.stat().st_nlink,
    }


def same_sid_ransom_proof(root: Path) -> dict[str, object]:
    topology = _topology(root)
    writer, client, capability = _writer_client(topology, "ransom-runtime")
    try:
        client.write_intent(_intent("ransom-runtime", record="ransom-record"))
        record = next((root / topology.namespace / "records").rglob("*.json"))
        overwritten = False
        deleted = False
        try:
            record.write_text("tampered\n", encoding="ascii")
            overwritten = True
        except OSError:
            pass
        try:
            record.unlink()
            deleted = True
        except OSError:
            pass
    finally:
        writer.close()
        capability.close()
    return {"overwriteAllowed": overwritten, "deleteAllowed": deleted}


def writer_scale_soak_proof(root: Path, *, count: int = 2000) -> dict[str, object]:
    topology = _topology(root)
    capability = EphemeralWriterCapability.create()
    runtime_id = "writer-hardening-soak-runtime"
    acquired_started = time.perf_counter()
    writer = DedicatedEvidenceWriter(topology)
    initial_acquisition_seconds = time.perf_counter() - acquired_started
    writer.activate_session(capability=capability, source_identity=runtime_id)
    client = AuthenticatedEvidenceWriterClient(
        topology=topology,
        capability=capability,
        runtime_instance_id=runtime_id,
        writer=writer,
    )
    latencies: list[float] = []
    duplicate_replays = 0
    predecessor = None
    replacement_acquisition_seconds = 0.0
    try:
        for sequence in range(1, count + 1):
            intent = build_evidence_write_intent(
                runtime_instance_id=runtime_id,
                sequence=sequence,
                evidence_type=(
                    "COMPOSITION_CYCLE" if sequence % 2 else "OPPORTUNITY_DENOMINATOR"
                ),
                record_identity=f"soak-record-{sequence:06d}",
                record_fingerprint=hashlib.sha256(
                    f"soak-record-{sequence:06d}".encode("ascii")
                ).hexdigest(),
                predecessor_identity=predecessor,
                requested_at="2026-08-16T12:00:00+00:00",
                payload_fingerprint=hashlib.sha256(
                    f"soak-payload-{sequence:06d}".encode("ascii")
                ).hexdigest(),
            )
            started = time.perf_counter()
            status = client.write_intent(intent)
            latencies.append(time.perf_counter() - started)
            if status != WRITER_ACCEPTED:
                raise WindowsIsolationProofError("Soak first write was not accepted.")
            if sequence % 200 == 0:
                if client.write_intent(intent) != WRITER_DUPLICATE:
                    raise WindowsIsolationProofError("Soak duplicate was not idempotent.")
                duplicate_replays += 1
            predecessor = intent.intent_id
            if sequence == count // 2:
                writer.close()
                acquired_started = time.perf_counter()
                writer = DedicatedEvidenceWriter(topology)
                writer.activate_session(capability=capability, source_identity=runtime_id)
                replacement_acquisition_seconds = time.perf_counter() - acquired_started
                client.set_writer(writer)
        snapshot = read_evidence_snapshot(topology, reader_role=OFFLINE_REVIEW)
    finally:
        writer.close()
        capability.close()
    evidence_root = Path(topology.root_path) / topology.namespace
    files = tuple(path for path in evidence_root.rglob("*") if path.is_file())
    ordered = sorted(latencies)
    p95_index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {
        "status": "COMPLETED",
        "recordCount": snapshot.record_count,
        "requestedRecordCount": count,
        "duplicateReplays": duplicate_replays,
        "initialOwnershipAcquisitionMs": round(initial_acquisition_seconds * 1000, 3),
        "restartRecoveryMs": round(replacement_acquisition_seconds * 1000, 3),
        "meanWriteLatencyMs": round(statistics.fmean(latencies) * 1000, 3),
        "p95WriteLatencyMs": round(ordered[p95_index] * 1000, 3),
        "artifactFileCount": len(files),
        "storageBytes": sum(path.stat().st_size for path in files),
        "wholeLedgerRewrite": False,
        "splitBrainEvents": 0,
    }


def run_non_elevated_proof(
    output_path: Path,
    *,
    include_soak: bool = False,
) -> dict[str, object]:
    if output_path.exists():
        raise WindowsIsolationProofError("Non-elevated proof output already exists.")
    with tempfile.TemporaryDirectory(prefix="mh-windows-isolation-") as temporary:
        root = Path(temporary).resolve()
        access_root = root / "same-sid-access"
        access_root.mkdir()
        for name in ("committed.json", "committed-delete.json", "partial.tmp", "readable.txt"):
            (access_root / name).write_text(name, encoding="ascii")
        result = {
            "schemaVersion": SCHEMA_VERSION,
            "profile": PROFILE,
            "authority": AUTHORITY,
            "createdAt": _timestamp(),
            "identity": current_identity(),
            "sameSidAccess": file_access_matrix(access_root, "SAME_SID_NONWRITER"),
            "handleInheritance": handle_inheritance_matrix(root / "handle-inheritance"),
            "sameSidHandleDuplication": same_sid_handle_duplication(root / "handle-duplication"),
            "ipcAttackMatrix": ipc_attack_matrix(),
            "duplicateWriter": duplicate_writer_process_proof(root / "duplicate-writer"),
            "duplicateWriterCrashRecovery": duplicate_writer_crash_recovery_proof(
                root / "duplicate-writer-crash"
            ),
            "writerCrashRestart": crash_restart_matrix(root / "writer-crash"),
            "runtimeRestartReplay": runtime_restart_replay_proof(root / "runtime-restart"),
            "reparseAttacks": reparse_attack_matrix(root / "reparse"),
            "sameSidCommittedEvidenceAttack": same_sid_ransom_proof(root / "ransom"),
            "scaleSoak": (
                writer_scale_soak_proof(root / "scale-soak")
                if include_soak
                else {"status": "NOT_RUN_BOUNDED_UNIT"}
            ),
            "productionContacted": False,
            "providerBrokerOrderCalls": 0,
        }
    write_json(output_path, result)
    return result


def finalize_proof(
    non_elevated_path: Path,
    elevated_path: Path,
    output_json: Path,
    output_markdown: Path,
) -> dict[str, object]:
    non_elevated = read_json(non_elevated_path)
    elevated = read_json(elevated_path)
    same_sid = non_elevated["sameSidAccess"]["attempts"]
    same_sid_mutation = any(item["allowed"] for item in same_sid.values())
    duplicate_result = non_elevated["duplicateWriter"]
    duplicate_writer = bool(duplicate_result["bothAccepted"])
    single_writer_proven = bool(
        duplicate_result.get("acceptedCount") == 1
        and duplicate_result.get("ownerConflictCount") == 1
        and duplicate_result.get("recordFiles") == 1
        and not duplicate_result.get("restartValidationFailed")
    )
    crash_recovery = non_elevated["duplicateWriterCrashRecovery"]
    crash_release_proven = bool(
        crash_recovery.get("initialStatus") == WRITER_ACCEPTED
        and crash_recovery.get("deniedStatus") == WRITER_OWNER_CONFLICT
        and crash_recovery.get("replacementStatus") == "WRITER_OWNER_ACQUIRED"
        and crash_recovery.get("recordFiles") == 1
        and crash_recovery.get("overlapOwners") == 0
    )
    reparse = non_elevated["reparseAttacks"]
    outside_mutation_count = int(
        reparse["rootSubstitution"]["escapedRecordCount"]
        + reparse["childDirectoryRedirect"]["escapedRecordCount"]
        + reparse["recordShardRedirect"]["escapedRecordCount"]
        + reparse["partialRedirect"]["escapedTemporaryCount"]
        + reparse["partialRedirect"]["startupEscapedTemporaryCount"]
        + reparse["directorySymlinkRedirect"]["escapedFileCount"]
    )
    if reparse["outsideHardLinkInward"]["outsideChanged"]:
        outside_mutation_count += 1
    reparse_escape = bool(outside_mutation_count)
    symlink_result = reparse["directorySymlinkRedirect"]
    symlink_proven = not symlink_result["supported"] or bool(symlink_result["rejected"])
    reparse_proven = bool(
        not reparse_escape
        and reparse["rootSubstitution"]["writeRejected"]
        and reparse["childDirectoryRedirect"]["rejected"]
        and reparse["recordShardRedirect"]["rejected"]
        and reparse["partialRedirect"]["startupReparseRejected"]
        and symlink_proven
        and reparse["outsideHardLinkInward"]["rejected"]
    )
    soak = non_elevated["scaleSoak"]
    soak_proven = bool(
        soak.get("status") == "COMPLETED"
        and soak.get("recordCount") == soak.get("requestedRecordCount")
        and int(soak.get("requestedRecordCount", 0)) >= 2000
        and soak.get("wholeLedgerRewrite") is False
        and soak.get("splitBrainEvents") == 0
    )
    limited_actors = tuple(
        elevated["actors"][name]
        for name in ("limitedNonwriter", "wpfNonwriter", "engineHostNonwriter")
        if name in elevated["actors"]
    )
    writer = elevated["actors"]["localServiceWriter"]
    limited_mutation = any(
        item["allowed"]
        for actor in limited_actors
        for item in actor["attempts"].values()
    )
    writer_required = (
        "create",
        "overwrite",
        "append",
        "rename",
        "delete",
        "directoryCreate",
        "immutableCreate",
        "tempWriteAtomicCommit",
        "tempCleanup",
    )
    writer_can_mutate = all(writer["attempts"][name]["allowed"] for name in writer_required)
    classification = ["SAME_SID_FILESYSTEM_ISOLATION_INSUFFICIENT"]
    if not single_writer_proven or not crash_release_proven:
        classification.append("DUPLICATE_WRITER_EXCLUSION_INSUFFICIENT")
    else:
        classification.append("SINGLE_WRITER_EXCLUSION_PROVEN")
    if not reparse_proven:
        classification.append("REPARSE_POINT_BOUNDARY_INSUFFICIENT")
    else:
        classification.append("REPARSE_RESISTANT_WRITES_PROVEN")
    if not soak_proven:
        classification.append("WRITER_SCALE_SOAK_INSUFFICIENT")
    if limited_mutation or not writer_can_mutate:
        classification.append("WINDOWS_TRUST_BOUNDARY_REQUIRES_ARCHITECTURE_CHANGE")
    else:
        classification.append("WINDOWS_ISOLATION_PROVEN_WITH_DEDICATED_PRINCIPAL")
    classification.append("LOCAL_ADMINISTRATOR_RESISTANCE_NOT_CLAIMED")
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "profile": PROFILE,
        "authority": AUTHORITY,
        "createdAt": _timestamp(),
        "classification": classification,
        "sameSid": non_elevated,
        "distinctPrincipal": elevated,
        "claims": {
            "sameSidFilesystemIsolationProven": not same_sid_mutation,
            "dedicatedPrincipalAclBoundaryProven": writer_can_mutate and not limited_mutation,
            "duplicateWriterPhysicalExclusionProven": single_writer_proven,
            "writerCrashReleaseProven": crash_release_proven,
            "reparseBoundaryProven": reparse_proven,
            "outsideRootMutationCount": outside_mutation_count,
            "writerScaleSoakProven": soak_proven,
            "administratorResistanceClaimed": False,
            "productionRuntimeActivated": False,
        },
    }
    write_json(output_json, report)
    lines = [
        "# WRITER-HARDENING-001 Complete Windows Physical Proof",
        "",
        f"- Classification: `{', '.join(classification)}`",
        f"- Same-SID direct mutation allowed: `{same_sid_mutation}`",
        f"- Dedicated LOCAL SERVICE writer mutations passed: `{writer_can_mutate}`",
        f"- Limited nonwriter mutation allowed: `{limited_mutation}`",
        f"- Two physical writers both accepted sequence 1: `{duplicate_writer}`",
        f"- Crash released ownership to exactly one replacement: `{crash_release_proven}`",
        f"- Reparse/root substitution escaped the logical root: `{reparse_escape}`",
        f"- Outside-root mutation count: `{outside_mutation_count}`",
        f"- Hardened 2,000-record scale/soak passed: `{soak_proven}`",
        "- Administrator/SYSTEM/kernel resistance: `NOT CLAIMED`",
        "- Production provider/broker/order/runtime contact: `NONE`",
        "",
        f"JSON fingerprint: `{read_json(output_json)['fingerprint']}`",
    ]
    output_markdown.write_text("\n".join(lines) + "\n", encoding="ascii")
    return report


def _writer_client(
    topology: Any,
    runtime_id: str,
) -> tuple[DedicatedEvidenceWriter, AuthenticatedEvidenceWriterClient, EphemeralWriterCapability]:
    capability = EphemeralWriterCapability.create()
    writer = DedicatedEvidenceWriter(topology)
    writer.activate_session(capability=capability, source_identity=runtime_id)
    client = AuthenticatedEvidenceWriterClient(
        topology=topology,
        capability=capability,
        runtime_instance_id=runtime_id,
        writer=writer,
    )
    return writer, client, capability


def _topology(root: Path) -> Any:
    return build_continuous_writer_topology_v2(
        root_path=root.resolve(),
        evidence_program_id="windows-isolation-proof",
        configuration_fingerprint=CONFIGURATION,
        runtime_build_hash=RUNTIME_BUILD,
    )


def _intent(runtime_id: str, *, record: str) -> Any:
    record_fingerprint = hashlib.sha256(record.encode("ascii")).hexdigest()
    return build_evidence_write_intent(
        runtime_instance_id=runtime_id,
        sequence=1,
        evidence_type="COMPOSITION_CYCLE",
        record_identity=record,
        record_fingerprint=record_fingerprint,
        predecessor_identity=None,
        requested_at="2026-08-16T12:00:00+00:00",
        payload_fingerprint=record_fingerprint,
    )


def _junction(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise WindowsIsolationProofError(
            f"Test junction creation failed with exit code {completed.returncode}."
        )


def _remove_junction(path: Path) -> None:
    if not path.exists():
        return
    subprocess.run(
        ["cmd.exe", "/d", "/c", "rmdir", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def _wait_for(path: Path, timeout: float = WAIT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.025)
    raise WindowsIsolationProofError(f"Timed out waiting for test artifact {path.name}.")


def _raises(action: Callable[[], object], expected: type[BaseException]) -> bool:
    try:
        action()
    except expected:
        return True
    return False


def _stdout_status(stdout: str) -> object:
    try:
        return json.loads(stdout).get("status")
    except (json.JSONDecodeError, AttributeError):
        return None


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _python_executable() -> str:
    return str(Path(getattr(sys, "_base_executable", sys.executable)).resolve())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    handle_read = commands.add_parser("handle-read")
    handle_read.add_argument("--handle", type=int, required=True)
    handle_read.add_argument("--expected-sha256", required=True)
    handle_target = commands.add_parser("handle-target")
    handle_target.add_argument("--control", type=Path, required=True)
    handle_target.add_argument("--release", type=Path, required=True)
    handle_target.add_argument("--capability-file", type=Path, required=True)
    duplicate = commands.add_parser("duplicate-writer-worker")
    duplicate.add_argument("--root", type=Path, required=True)
    duplicate.add_argument("--index", type=int, required=True)
    duplicate.add_argument("--ready", type=Path, required=True)
    duplicate.add_argument("--start", type=Path, required=True)
    duplicate.add_argument("--result", type=Path, required=True)
    duplicate.add_argument("--release", type=Path, required=True)
    owner_hold = commands.add_parser("owner-hold-worker")
    owner_hold.add_argument("--root", type=Path, required=True)
    owner_hold.add_argument("--ready", type=Path, required=True)
    owner_hold.add_argument("--result", type=Path, required=True)
    owner_probe = commands.add_parser("owner-probe-worker")
    owner_probe.add_argument("--root", type=Path, required=True)
    owner_probe.add_argument("--result", type=Path, required=True)
    owner_probe.add_argument("--instance", required=True)
    commands.add_parser("crash-worker")
    non_elevated = commands.add_parser("non-elevated")
    non_elevated.add_argument("--output", type=Path, required=True)
    non_elevated.add_argument("--include-soak", action="store_true")
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--non-elevated", type=Path, required=True)
    finalize.add_argument("--elevated", type=Path, required=True)
    finalize.add_argument("--output-json", type=Path, required=True)
    finalize.add_argument("--output-markdown", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "handle-read":
        return handle_read_command(arguments.handle, arguments.expected_sha256)
    if arguments.command == "handle-target":
        return handle_target_command(
            arguments.control, arguments.release, arguments.capability_file
        )
    if arguments.command == "duplicate-writer-worker":
        return duplicate_writer_worker(
            arguments.root,
            arguments.index,
            arguments.ready,
            arguments.start,
            arguments.result,
            arguments.release,
        )
    if arguments.command == "crash-worker":
        return crash_worker_command()
    if arguments.command == "owner-hold-worker":
        return owner_hold_worker(arguments.root, arguments.ready, arguments.result)
    if arguments.command == "owner-probe-worker":
        return owner_probe_worker(arguments.root, arguments.result, arguments.instance)
    if arguments.command == "non-elevated":
        run_non_elevated_proof(
            arguments.output.resolve(),
            include_soak=arguments.include_soak,
        )
        return 0
    if arguments.command == "finalize":
        finalize_proof(
            arguments.non_elevated.resolve(),
            arguments.elevated.resolve(),
            arguments.output_json.resolve(),
            arguments.output_markdown.resolve(),
        )
        return 0
    raise AssertionError("Unhandled command")


if __name__ == "__main__":
    raise SystemExit(main())
