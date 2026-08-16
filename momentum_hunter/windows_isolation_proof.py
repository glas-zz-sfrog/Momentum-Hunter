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


SCHEMA_VERSION = 1
PROFILE = "continuous-windows-isolation-proof-v1"
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
        for process in processes:
            _stdout, _stderr = process.communicate(timeout=WAIT_SECONDS)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                _stdout, _stderr = process.communicate(timeout=5)
    outcomes = [read_json(path) for path in result_paths]
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
        "statuses": [item.get("status") for item in outcomes],
        "bothAccepted": all(item.get("status") == WRITER_ACCEPTED for item in outcomes),
        "recordFiles": len(records),
        "restartValidationFailed": restart_validation_failed,
    }


def duplicate_writer_worker(
    root: Path,
    index: int,
    ready: Path,
    start: Path,
    result: Path,
) -> int:
    topology = _topology(root)
    writer = DedicatedEvidenceWriter(topology)
    capability = EphemeralWriterCapability.create()
    runtime_id = f"physical-runtime-{index}"
    try:
        writer.activate_session(capability=capability, source_identity=runtime_id)
        client = AuthenticatedEvidenceWriterClient(
            topology=topology,
            capability=capability,
            runtime_instance_id=runtime_id,
            writer=writer,
        )
        intent = _intent(runtime_id, record=f"writer-{index}")
        ready.parent.mkdir(parents=True, exist_ok=True)
        ready.touch()
        _wait_for(start)
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
    finally:
        writer.close()
        capability.close()
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
        "recordShardRedirect": _record_shard_redirect(root / "record-redirect"),
        "partialRedirect": _partial_redirect(root / "partial-redirect"),
    }


def _root_substitution_attack(root: Path) -> dict[str, object]:
    authority = root / "authority"
    escape = root / "escape"
    backup = root / "authority-backup"
    topology = _topology(authority)
    writer, client, capability = _writer_client(topology, "root-swap-runtime")
    try:
        authority.rename(backup)
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
        "writeRejected": rejected,
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


def _partial_redirect(root: Path) -> dict[str, object]:
    topology = _topology(root / "authority")
    writer, client, capability = _writer_client(topology, "partial-redirect-runtime")
    partial = Path(topology.root_path) / topology.namespace / ".partial"
    escape = root / "escape"
    shutil.rmtree(partial)
    escape.mkdir(parents=True)
    _junction(partial, escape)
    try:
        writer.arm_crash(CRASH_AFTER_TEMP)
        status = client.write_intent(_intent("partial-redirect-runtime", record="partial-redirect"))
        escaped_temps = list(escape.glob("*.tmp"))
    finally:
        writer.close()
        capability.close()
        _remove_junction(partial)
    return {
        "writerStatus": status,
        "escapedTemporaryCount": len(escaped_temps),
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


def run_non_elevated_proof(output_path: Path) -> dict[str, object]:
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
            "writerCrashRestart": crash_restart_matrix(root / "writer-crash"),
            "runtimeRestartReplay": runtime_restart_replay_proof(root / "runtime-restart"),
            "reparseAttacks": reparse_attack_matrix(root / "reparse"),
            "sameSidCommittedEvidenceAttack": same_sid_ransom_proof(root / "ransom"),
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
    duplicate_writer = bool(non_elevated["duplicateWriter"]["bothAccepted"])
    reparse = non_elevated["reparseAttacks"]
    reparse_escape = bool(
        reparse["rootSubstitution"]["escapedRecordCount"]
        or reparse["partialRedirect"]["escapedTemporaryCount"]
    )
    limited = elevated["actors"]["limitedNonwriter"]
    writer = elevated["actors"]["localServiceWriter"]
    limited_mutation = any(
        item["allowed"] for item in limited["attempts"].values()
    )
    writer_required = (
        "create",
        "overwrite",
        "append",
        "rename",
        "delete",
        "directoryCreate",
    )
    writer_can_mutate = all(writer["attempts"][name]["allowed"] for name in writer_required)
    classification = []
    if same_sid_mutation:
        classification.append("SAME_SID_FILESYSTEM_ISOLATION_INSUFFICIENT")
    if duplicate_writer:
        classification.append("DUPLICATE_WRITER_EXCLUSION_INSUFFICIENT")
    if reparse_escape:
        classification.append("REPARSE_POINT_BOUNDARY_INSUFFICIENT")
    if limited_mutation or not writer_can_mutate:
        classification.append("WINDOWS_TRUST_BOUNDARY_REQUIRES_ARCHITECTURE_CHANGE")
    elif classification:
        classification.append("WINDOWS_ISOLATION_REQUIRES_DEDICATED_PRINCIPAL_AND_HARDENING")
    else:
        classification.append("WINDOWS_ISOLATION_PROVEN_WITH_DEDICATED_PRINCIPAL")
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
            "duplicateWriterPhysicalExclusionProven": not duplicate_writer,
            "reparseBoundaryProven": not reparse_escape,
            "administratorResistanceClaimed": False,
            "productionRuntimeActivated": False,
        },
    }
    write_json(output_json, report)
    lines = [
        "# CONTINUOUS-WINDOWS-ISOLATION-001 Physical Proof",
        "",
        f"- Classification: `{', '.join(classification)}`",
        f"- Same-SID direct mutation allowed: `{same_sid_mutation}`",
        f"- Dedicated LOCAL SERVICE writer mutations passed: `{writer_can_mutate}`",
        f"- Limited nonwriter mutation allowed: `{limited_mutation}`",
        f"- Two physical writers both accepted sequence 1: `{duplicate_writer}`",
        f"- Reparse/root substitution escaped the logical root: `{reparse_escape}`",
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
    commands.add_parser("crash-worker")
    non_elevated = commands.add_parser("non-elevated")
    non_elevated.add_argument("--output", type=Path, required=True)
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
        )
    if arguments.command == "crash-worker":
        return crash_worker_command()
    if arguments.command == "non-elevated":
        run_non_elevated_proof(arguments.output.resolve())
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
