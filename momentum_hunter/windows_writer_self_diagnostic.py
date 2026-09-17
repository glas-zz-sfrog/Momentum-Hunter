"""016J qualification-only own-token observations, never an admission policy.

Native opens request one right and immediately close without exercising it.
The compact stderr transport is decoded into review evidence by the supervisor.
"""
from __future__ import annotations

import base64
import ctypes as c
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys
import time
import zlib

from momentum_hunter import windows_writer_profile as profile_api


MARKER = "WRITER_SELF_AUTHORITY_016J="
STAGE_MARKER = "WRITER_ASSUMPTION_016J="
TASK = "ARGUS-013B-FIRST-FALSE-ASSUMPTION-LADDER-016J"
MAX_SECONDS = 12
MAX_TARGETS = 64
MAX_PROBES = 1000
MAX_REPORT_BYTES = 262144
MAX_TRANSPORT_BYTES = 24000
TOKEN_FIELDS = (
    "thread_token", "user", "owner", "integrity", "token_type", "elevation",
    "elevation_type", "ui_access", "virtualization", "session_id", "has_restrictions",
    "group_attributes", "restricting_attributes", "privilege_attributes",
    "token_id", "authentication_id", "modified_id",
)
PRODUCTION_SERVICES = (
    "MomentumHunterAutomation", "MomentumHunterContinuousRuntime", "MomentumHunterContinuousWriter",
)


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def outcome(success, error):
    if success:
        return "GRANTED" if error == 0 else "UNKNOWN_API_CONTRADICTION"
    return {5: "SECURITY_DENIED", 32: "SHARING_CONFLICT", 33: "LOCK_CONFLICT",
            2: "OBJECT_MISSING", 3: "PATH_MISSING", 1060: "SERVICE_MISSING",
            87: "INVALID_PARAMETER", 123: "MALFORMED_PATH"}.get(error, "OTHER_API_FAILURE")


def row(right, success, error, identity=None):
    return {"right": right, "apiSuccess": bool(success), "win32": error,
            "accessGranted": bool(success), "classification": outcome(success, error),
            "objectIdentity": identity}


def admission(token, binding):
    try:
        profile_api._validate_token(token, "writer", binding)
    except profile_api.WriterProfileError as exc:
        return {"result": "REJECT", "predicate": exc.args[0]}
    return {"result": "ACCEPT", "predicate": None}


def token_envelope(token):
    # No environment, handle value or arbitrary exception message enters evidence.
    value = {key: token.get(key) for key in TOKEN_FIELDS}
    for key in ("user", "owner", "integrity"):
        if type(value[key]) is not str or not re.fullmatch(r"S-1-(?:[0-9]{1,10}-){1,16}[0-9]{1,10}", value[key]):
            raise ValueError("TOKEN_SID_SHAPE")
    for key in ("group_attributes", "restricting_attributes", "privilege_attributes"):
        entries = value[key]
        if type(entries) is not tuple or len(entries) > 128:
            raise ValueError("TOKEN_ENTRY_BOUND")
        pattern = r"Se[A-Za-z]{1,64}Privilege" if key == "privilege_attributes" else r"S-1-(?:[0-9]{1,10}-){1,16}[0-9]{1,10}"
        if any(type(entry) is not tuple or len(entry) != 2 or type(entry[0]) is not str or
               re.fullmatch(pattern, entry[0]) is None or type(entry[1]) is not int or
               not 0 <= entry[1] <= 0xFFFFFFFF for entry in entries):
            raise ValueError("TOKEN_ENTRY_SHAPE")
    for key in set(TOKEN_FIELDS) - {"user", "owner", "integrity", "group_attributes", "restricting_attributes", "privilege_attributes"}:
        item = value[key]
        if key in {"token_id", "authentication_id", "modified_id"}:
            valid = type(item) is tuple and len(item) == 2 and all(type(x) is int and 0 <= x <= 0xFFFFFFFF for x in item)
        elif key == "thread_token":
            valid = type(item) is bool
        else:
            valid = type(item) is int and 0 <= item <= 0xFFFFFFFF
        if not valid:
            raise ValueError("TOKEN_SCALAR_SHAPE")
    if len(canonical(value)) > 16384:
        raise ValueError("TOKEN_ENVELOPE_BOUND")
    value["denyOnlyGroups"] = tuple((sid, attrs) for sid, attrs in token.get("group_attributes", ()) if attrs & 16)
    return value


def targets(config, profile):
    profile_api.validate_profile_paths(config, profile)
    root = PureWindowsPath(config["host"]["instanceRoot"])
    result = []
    for binding in profile.resources:
        needed, forbidden = profile_api.resource_rights(binding.name, binding.directory)
        result.append(dict(name=binding.name, path=binding.path, directory=binding.directory,
                           needed=needed, forbidden=forbidden, frozenIdentity=binding.file_identity,
                           policy="016D_RESOURCE_RULES"))
    for name, relative, transport in (("claims", "claims", False), ("receipts", "receipts", False),
            ("arrivals", "arrivals", False), ("custody", "custody", False),
            ("cursors", "reader/cursors", False), ("private", "private", False),
            ("staging", "staging", True), ("requests", "requests", True)):
        result.append(dict(name="custody_" + name, path=str(root / "science" / relative), directory=True,
            needed=profile_api._READ if transport else profile_api.FILE_RIGHTS,
            forbidden=profile_api.MUTATION_RIGHTS if transport else (), frozenIdentity=None,
            policy="016E_TRUSTED_FINALIZER_NOT_OS_WORM"))
    explicit = {PureWindowsPath(item["path"]) for item in result}
    ancestors = {parent for path in explicit for parent in path.parents} - explicit
    for path in sorted(ancestors):
        result.append(dict(name="ancestor", path=str(path), directory=True, needed=(32, 128, 131072),
            forbidden=profile_api.MUTATION_RIGHTS, frozenIdentity=None, policy="016D_SUPPORT_ANCESTOR"))
    # Root rights do not establish leaf readability/confidentiality. Use finite
    # code and replica leaves already supplied by the qualification installer.
    paths = profile_api.expected_resource_paths(config)
    leaves = [("runtime_source", "momentum_hunter/windows_writer_profile.py"),
              ("runtime_source", "momentum_hunter/windows_writer_self_diagnostic.py"),
              ("runtime_source", "momentum_hunter/continuous_production.py"),
              ("host_image_root", "MomentumHunter.ContinuousServiceHost.exe"),
              ("python_base", "python.exe"), ("python_root", "Scripts/python.exe")]
    leaves.extend((name, "qualification-only.json") for name in (
        "unrelated_host", "unrelated_repository", "unrelated_profile", "provider_replica",
        "account_replica", "paper_replica", "scheduler_replica"))
    leaves.append(("science_derived", ".custody-transport.tmp"))
    for name, relative in leaves:
        needed, forbidden = profile_api.resource_rights(name, False, relative)
        result.append(dict(name=name + ":" + relative, path=str(paths[name] / relative), directory=False,
            needed=needed, forbidden=forbidden, frozenIdentity=None, policy="016D_EXPLICIT_LEAF"))
    if not 30 <= len(result) <= MAX_TARGETS or len(explicit) != 30:
        raise ValueError("TARGET_INVENTORY_BOUND")
    return result


class SelfNative:
    """No mutation APIs, impersonation, duplication or privilege adjustment."""
    def __init__(self, native):
        from momentum_hunter import windows_writer_storage as storage
        self.native = native
        w = native.w
        # The kernel library is shared with storage; preserve its existing ABI.
        self.info_type = storage._BY_HANDLE_FILE_INFORMATION
        native.bind(native.a, "OpenSCManagerW", [w.LPCWSTR, w.LPCWSTR, w.DWORD], w.HANDLE)
        native.bind(native.a, "OpenServiceW", [w.HANDLE, w.LPCWSTR, w.DWORD], w.HANDLE)
        native.bind(native.a, "CloseServiceHandle", [w.HANDLE], w.BOOL)

    def own_token(self):
        result = self.native.token()
        if result.get("thread_token") is not False or result.get("token_type") != 1:
            raise ValueError("OWN_PRIMARY_CONTEXT_UNPROVEN")
        return result

    def mandatory_policy(self, expected):
        native, w = self.native, self.native.w
        handle = w.HANDLE()
        native.checked(native.a.OpenProcessToken(native.k.GetCurrentProcess(), 8, c.byref(handle)),
                       "Own process TOKEN_QUERY only")
        try:
            extended = {}
            profile_api._extended_token(native, handle, extended)
            if any(extended[key] != expected[key] for key in ("token_id", "authentication_id", "modified_id")):
                raise ValueError("SELF_TOKEN_QUERY_IDENTITY_CHANGED")
            policy, size = w.DWORD(), w.DWORD()
            native.checked(native.a.GetTokenInformation(handle, 27, c.byref(policy), c.sizeof(policy),
                                                        c.byref(size)), "Own mandatory policy")
            if size.value != c.sizeof(policy):
                raise ValueError("MANDATORY_POLICY_SIZE")
            return policy.value
        finally:
            native.checked(native.k.CloseHandle(handle), "Close own query token")

    def process_binding(self, binding):
        current = profile_api._process(self.native, os.getpid())
        parent = profile_api._process(self.native, os.getppid())
        scm = profile_api._scm(self.native, binding)
        matched = (scm["pid"] == parent["pid"] and
                   PureWindowsPath(current["image"]) == PureWindowsPath(binding.python_path) and
                   PureWindowsPath(parent["image"]) == PureWindowsPath(binding.host_path))
        return dict(process=current, parent=parent, scm=scm, matched=matched)

    def file(self, target, right):
        if right not in (0, *profile_api.FILE_RIGHTS) or type(right) is not int:
            raise ValueError("INDIVIDUAL_FILE_RIGHT_REQUIRED")
        profile_api.absolute_path(target["path"])
        # OPEN_EXISTING, all share modes, no inheritance, no delete-on-close.
        # BACKUP_SEMANTICS permits directory opens; no backup privilege is enabled.
        flags = 0x00200000 | (0x02000000 if target["directory"] else 0)
        c.set_last_error(0)
        handle = self.native.k.CreateFileW(target["path"], right, 7, None, 3, flags, None)
        success = c.cast(handle, c.c_void_p).value not in {None, c.c_void_p(-1).value}
        error = 0 if success else c.get_last_error()
        identity = None
        metadata_error = None
        if success:
            try:
                info = self.info_type()
                if self.native.k.GetFileInformationByHandle(handle, c.byref(info)):
                    identity = dict(fileId=(info.dwVolumeSerialNumber, info.nFileIndexHigh, info.nFileIndexLow),
                                    attributes=info.dwFileAttributes, links=info.nNumberOfLinks)
                    metadata_error = 0
                else:
                    metadata_error = c.get_last_error()
            finally:
                self.native.checked(self.native.k.CloseHandle(handle), "Close self-probe file")
        result = row(right, success, error, identity)
        result["metadataWin32"] = metadata_error
        return result

    def services(self, names, deadline, clock):
        c.set_last_error(0)
        manager = self.native.a.OpenSCManagerW(None, None, 1)
        if not manager:
            return {"managerError": c.get_last_error(), "rows": []}
        result = []
        try:
            for name in names:
                for right in profile_api.SERVICE_CONTROL_RIGHTS:
                    if clock() >= deadline:
                        return {"boundedStop": True, "rows": result}
                    c.set_last_error(0)
                    handle = self.native.a.OpenServiceW(manager, name, right)
                    error = 0 if handle else c.get_last_error()
                    item = row(right, bool(handle), error)
                    item.update(service=name, api="OpenServiceW")
                    result.append(item)
                    if handle:
                        self.native.checked(self.native.a.CloseServiceHandle(handle), "Close self-probe service")
            return {"rows": result}
        finally:
            self.native.checked(self.native.a.CloseServiceHandle(manager), "Close self-probe SCM")


def complete_stage(report, stage, status, **detail):
    value = dict(status=status, **detail)
    report["assumptions"][stage] = value
    if status == "FALSE" and report["firstFalseAssumption"] == "NONE_REACHED":
        report["firstFalseAssumption"] = stage
    try:
        sys.stderr.write(STAGE_MARKER + canonical(dict(stage=stage, **value)).decode("ascii") + "\n")
        sys.stderr.flush()
    except Exception:
        report["progressOutputUnavailable"] = True


def required_rights(target):
    # Directory traverse requests are not a necessary operation in isolation
    # (SeChangeNotifyPrivilege bypasses traversal). Custody ACL administration
    # is also not a finalization prerequisite. Neither is silently admitted.
    if target["name"] == "ancestor":
        return ()
    rights = target["needed"]
    if target["name"].startswith("custody_") and target["name"] not in {"custody_staging", "custody_requests"}:
        rights = (*profile_api._MODIFY, 64)
    return tuple(right for right in rights if not (target["directory"] and right == 32))


def bound_metadata(target, observation):
    identity = observation.get("objectIdentity")
    if observation["classification"] != "GRANTED" or not identity:
        return False
    if identity.get("attributes", 0) & 0x400:
        return False
    if bool(identity.get("attributes", 0) & 16) != target["directory"]:
        return False
    expected = target["frozenIdentity"]
    return expected is None or tuple(identity["fileId"]) == tuple(expected)


def file_matrix(api, expected, phase, report, deadline, clock):
    result = []
    for target in expected:
        rights = required_rights(target) if phase == "A5" else target["forbidden"]
        if not rights:
            continue
        item = {**target, "assumption": phase, "api": "CreateFileW_OPEN_EXISTING", "rows": []}
        report["files"].append(item)
        for right in (0, *rights):
            if clock() >= deadline or report["probeCount"] >= MAX_PROBES:
                raise ValueError("PROBE_BUDGET_EXHAUSTED")
            observation = api.file(target, right)
            item["rows"].append(observation)
            report["probeCount"] += 1
        item["identityBound"] = bound_metadata(target, item["rows"][0])
        for observation in item["rows"][1:]:
            if observation["accessGranted"] and observation.get("objectIdentity") != item["rows"][0].get("objectIdentity"):
                item["identityBound"] = False
        result.append(item)
    return result


def matrix_status(matrix, required):
    if not matrix:
        return "BLOCKED", 0, 0
    failures = unknown = 0
    for item in matrix:
        if not item["identityBound"]:
            unknown += 1
            continue
        for observation in item["rows"][1:]:
            kind = observation["classification"]
            if kind == ("SECURITY_DENIED" if required else "GRANTED"):
                failures += 1
            elif kind != ("GRANTED" if required else "SECURITY_DENIED"):
                unknown += 1
    return ("FALSE" if failures else "BLOCKED" if unknown else "PASS"), failures, unknown


def collect(native, config, profile, initial, *, clock=time.monotonic):
    started = clock()
    report = dict(task=TASK, schema=2,
        phase="PRE_GENERATION_ADMISSION", service=profile.writer.service_name,
        serviceSid=profile_api.service_sid(profile.writer.service_name), pid=os.getpid(),
        utcUnixNs=time.time_ns(), profileSha256=digest(asdict(profile)), configurationSha256=digest(config),
        admissionBefore=admission(initial, profile.writer), token=token_envelope(initial),
        scope="FIXED_ROOTS_CODE_AND_REPLICA_LEAVES; NO_COMPLETE_DESCENDANT_OR_GLOBAL_HOST_ATTESTATION",
        qualificationInstance=config["host"]["instanceRoot"], serviceRole="writer",
        actions="HANDLE_ACQUISITION_ONLY_NO_IO_OR_CONTROLS", files=[], services={}, errors=[],
        assumptions={}, firstFalseAssumption="NONE_REACHED", probeCount=0, completed=False)
    phase = "A4"
    try:
        report["step"] = "BOUND_QUALIFICATION"
        profile_api.validate_profile_paths(config, profile)
        api = SelfNative(native)
        report["step"] = "OWN_PRIMARY_QUERY"
        own = api.own_token()
        if own != initial:
            raise ValueError("INITIAL_TOKEN_CHANGED")
        report["step"] = "MANDATORY_POLICY_QUERY"
        report["token"]["mandatory_policy"] = api.mandatory_policy(own)
        report["step"] = "PROCESS_SCM_BINDING"
        report["binding"] = api.process_binding(profile.writer)
        report["step"] = "DIAGNOSTIC_SOURCE_IDENTITY"
        report["sourceSha256"] = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ("windows_writer_self_diagnostic.py", "windows_writer_profile.py", "windows_science_custody.py")}
        if not report["binding"]["matched"]:
            raise ValueError("SCM_WRITER_PARENT_IDENTITY_MISMATCH")
        report["tokenUnchanged"] = api.own_token() == own
        if not report["tokenUnchanged"]:
            raise ValueError("A4_TOKEN_CHANGED")
        complete_stage(report, "A4", "PASS", actualWriterTokenEnvelopeComplete=True,
                       actualWriterProcess=True, tokenUnchanged=True)
        phase = "A5"
        report["step"] = "REQUIRED_RIGHTS"
        expected = targets(config, profile)
        report["expectedFileTargets"] = len(expected)
        required = file_matrix(api, expected, phase, report, started + MAX_SECONDS, clock)
        status, failures, unknown = matrix_status(required, True)
        report["tokenUnchanged"] = api.own_token() == own
        if not report["tokenUnchanged"]:
            status = "BLOCKED"
        complete_stage(report, phase, status, targets=len(required), requiredDenials=failures,
                       unknown=unknown, tokenUnchanged=report["tokenUnchanged"])
        if status != "PASS":
            return report
        phase = "A6"
        report["step"] = "FORBIDDEN_RIGHTS"
        forbidden = file_matrix(api, expected, phase, report, started + MAX_SECONDS, clock)
        status, failures, unknown = matrix_status(forbidden, False)
        if status == "FALSE":
            report["tokenUnchanged"] = api.own_token() == own
            if not report["tokenUnchanged"]:
                status = "BLOCKED"
            complete_stage(report, phase, status, forbiddenGrants=failures, unknown=unknown,
                           tokenUnchanged=report["tokenUnchanged"],
                           servicesNotAttempted="STOP_AFTER_BOUND_FORBIDDEN_FILESYSTEM_GRANT")
            return report
        prefix = profile.writer.service_name.rsplit("-", 1)[0]
        names = [prefix + "-" + role for role in ("Automation", "Runtime", "Writer", "Science")]
        names.extend(PRODUCTION_SERVICES)
        report["expectedServiceTargets"] = names
        report["step"] = "SERVICE_HANDLES"
        report["services"] = api.services(names, started + MAX_SECONDS, clock)
        rows = report["services"].get("rows", [])
        failures += sum(row["classification"] == "GRANTED" for row in rows)
        unknown += sum(row["classification"] not in {"GRANTED", "SECURITY_DENIED"} for row in rows)
        unknown += abs(len(names) * len(profile_api.SERVICE_CONTROL_RIGHTS) - len(rows))
        report["step"] = "FINAL_OWN_TOKEN_QUERY"
        final = api.own_token()
        report["tokenUnchanged"] = final == own
        report["admissionAfterObservation"] = admission(final, profile.writer)
        status = "FALSE" if failures else "BLOCKED"
        if final != own:
            status = "BLOCKED"
        # Finite replica/root opens do not establish every descendant, inherited
        # future object, real scheduler or provider authority. Never invent A7.
        complete_stage(report, phase, status, forbiddenGrants=failures, unknown=unknown,
                       tokenUnchanged=final == own, completeAuthorityDomainProven=False,
                       limitation="FIXED_ROOTS_AND_REPLICA_LEAVES_NOT_GLOBAL_AUTHORITY_PROOF")
        report["completed"] = len(rows) == len(names) * len(profile_api.SERVICE_CONTROL_RIGHTS) and final == own
    except Exception as exc:
        report["completed"] = False
        code = str(exc) if type(exc) is ValueError and re.fullmatch(r"[A-Z0-9_]{1,80}", str(exc)) else None
        report["errors"].append({"type": type(exc).__name__, "step": report.get("step"),
                                "diagnosticCode": code, "win32": getattr(exc, "winerror", None)})
        complete_stage(report, phase, "BLOCKED", operation=report.get("step"), diagnosticCode=code)
    finally:
        report["elapsedSeconds"] = round(clock() - started, 6)
    return report


def emit(report, admission_error):
    """Emit after the real classifier decision; never suppress/replace rejection."""
    try:
        report["admissionAfter"] = ({"result": "REJECT", "predicate": admission_error.args[0]}
                                    if admission_error is not None else {"result": "ACCEPT", "predicate": None})
        report["admissionIdentical"] = report.get("admissionBefore") == report["admissionAfter"]
        raw = canonical(report)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("REPORT_BOUND")
        transport = canonical({"encoding": "zlib-base64-json", "sha256": hashlib.sha256(raw).hexdigest(),
            "rawBytes": len(raw), "payload": base64.b64encode(zlib.compress(raw, 9)).decode("ascii")})
        if len(transport) > MAX_TRANSPORT_BYTES:
            raise ValueError("TRANSPORT_BOUND")
        sys.stderr.write(MARKER + transport.decode("ascii") + "\n")
        sys.stderr.flush()
    except Exception:
        try:
            sys.stderr.write(MARKER + '{"status":"DIAGNOSTIC_OUTPUT_UNAVAILABLE"}\n')
        except Exception:
            pass


def begin(native, config, profile, token):
    try:
        return collect(native, config, profile, token)
    except Exception as exc:
        return {"task": TASK, "completed": False,
                "assumptions": {"A4": {"status": "BLOCKED"}}, "firstFalseAssumption": "NONE_REACHED",
                "errors": [{"type": type(exc).__name__}], "pid": os.getpid()}
