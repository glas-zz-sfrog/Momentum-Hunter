"""Durable Automation state custody. No provider, executor, or service authority.

Generations are bounded checkpoints; immutable job claims are separate execution
authority. Missing history is quarantined, never converted to a completion.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from momentum_hunter.path_transaction import PathTransactionLease

TERMINAL = frozenset({"COMPLETED", "FAILED", "MISSED", "BLOCKED_DEPENDENCY", "DISABLED"})
STATUSES = TERMINAL | {"PENDING", "RUNNING"}
RETAINED_GENERATIONS = 5


class StateRecoveryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise StateRecoveryError("SCHEMA_INVALID_STATE")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StateRecoveryError("SCHEMA_INVALID_STATE") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise StateRecoveryError("SCHEMA_INVALID_STATE")
    return result


def decode(raw: bytes) -> dict:
    if not raw:
        raise StateRecoveryError("ZERO_LENGTH_STATE")
    if not any(raw):
        raise StateRecoveryError("ALL_ZERO_STATE")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise StateRecoveryError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    try:
        result = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError) as exc:
        raise StateRecoveryError("MALFORMED_OR_TRUNCATED_JSON") from exc
    validate(result)
    return result


def validate(payload: object) -> None:
    if not isinstance(payload, dict) or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise StateRecoveryError("SCHEMA_INVALID_STATE")
    strings = {"service_instance_id", "service_started_at", "last_heartbeat_at",
               "engine_host_state", "engine_host_detail", "engine_host_observed_at",
               "loaded_supervisor_sha256", "loaded_runtime_identity_module_sha256",
               "loaded_service_host_sha256", "recovery_floor_at"}
    allowed = strings | {"schema_version", "jobs", "state_version", "prospective_epoch"}
    if set(payload) - allowed or any(not isinstance(payload[k], str) for k in strings & payload.keys()):
        raise StateRecoveryError("SCHEMA_INVALID_STATE")
    for key in ("service_started_at", "last_heartbeat_at", "engine_host_observed_at", "recovery_floor_at"):
        if payload.get(key):
            timestamp(payload[key])
    version = payload.get("state_version", 0)
    if type(version) is not int or version < 0 or not isinstance(payload.get("jobs"), dict):
        raise StateRecoveryError("SCHEMA_INVALID_STATE")
    epoch = payload.get("prospective_epoch", {})
    if not isinstance(epoch, dict):
        raise StateRecoveryError("EPOCH_INVALID")
    if epoch:
        validate_epoch(epoch)
        if not payload.get("recovery_floor_at") or timestamp(payload["recovery_floor_at"]) < timestamp(epoch["boundaryAt"]):
            raise StateRecoveryError("EPOCH_REPLAY_FLOOR_INVALID")
    receipt_strings = {"job_id", "kind", "status", "scheduled_at", "latest_start_at", "observed_at",
                       "started_at", "completed_at", "reason", "log_path", "depends_on_job_id",
                       "runtime_identity_mode", "approved_runtime_channel", "approved_release_id",
                       "approved_release_fingerprint", "runtime_surface_fingerprint", "configuration_fingerprint",
                       "environment_fingerprint", "approved_runtime_fingerprint", "release_source_git_sha",
                       "current_git_sha_at_execution", "runtime_identity_failure_code", "job_definition_sha256"}
    for key, receipt in payload["jobs"].items():
        if not isinstance(receipt, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", key):
            raise StateRecoveryError("SCHEMA_INVALID_STATE")
        if set(receipt) - (receipt_strings | {"exit_code", "runtime_match"}):
            raise StateRecoveryError("SCHEMA_INVALID_STATE")
        if any(not isinstance(receipt[k], str) for k in receipt_strings & receipt.keys()):
            raise StateRecoveryError("SCHEMA_INVALID_STATE")
        if receipt.get("job_id") != key or receipt.get("status") not in STATUSES or not receipt.get("kind"):
            raise StateRecoveryError("JOB_IDENTITY_OR_STATUS_MISMATCH")
        scheduled = timestamp(receipt.get("scheduled_at"))
        latest = timestamp(receipt.get("latest_start_at"))
        timestamp(receipt.get("observed_at"))
        if latest < scheduled:
            raise StateRecoveryError("JOB_CHRONOLOGY_INVALID")
        for name in ("started_at", "completed_at"):
            if receipt.get(name):
                timestamp(receipt[name])
        if receipt.get("exit_code") is not None and type(receipt["exit_code"]) is not int:
            raise StateRecoveryError("SCHEMA_INVALID_STATE")
        if receipt.get("runtime_match") is not None and type(receipt["runtime_match"]) is not bool:
            raise StateRecoveryError("SCHEMA_INVALID_STATE")
        if receipt.get("job_definition_sha256") and not re.fullmatch(r"[0-9a-f]{64}", receipt["job_definition_sha256"]):
            raise StateRecoveryError("JOB_DEFINITION_MISMATCH")
        if receipt["status"] == "COMPLETED" and (receipt.get("exit_code") != 0 or not receipt.get("completed_at")):
            raise StateRecoveryError("COMPLETION_AUTHORITY_INVALID")


def receipt_identity(receipt: dict) -> tuple:
    return tuple(receipt.get(k, "") for k in
                 ("job_id", "kind", "scheduled_at", "latest_start_at", "depends_on_job_id", "approved_runtime_channel"))


def equivalent_receipt(left: dict, right: dict) -> bool:
    # V1 had no definition-hash field. Absence stays unbound, never inferred.
    return (dict(left, job_definition_sha256=left.get("job_definition_sha256", ""))
            == dict(right, job_definition_sha256=right.get("job_definition_sha256", "")))


def sync_directory(path: Path) -> None:
    # Windows fsync flushes file data; directory handles are not supported here.
    if os.name != "nt":
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def durable_new(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise StateRecoveryError("WRITTEN_BYTES_MISMATCH")
    sync_directory(path.parent)


def validate_epoch(epoch: dict) -> None:
    fields = {"schemaVersion", "epochId", "boundaryAt", "firstProspectiveSession",
              "manifestSha256", "corruptSourceSha256", "legacyHistory", "preEpochReplayBlocked"}
    if set(epoch) != fields or type(epoch.get("schemaVersion")) is not int or epoch["schemaVersion"] != 1:
        raise StateRecoveryError("EPOCH_INVALID")
    if epoch["legacyHistory"] != "UNKNOWN" or epoch["preEpochReplayBlocked"] is not True:
        raise StateRecoveryError("EPOCH_HISTORY_AUTHORITY_INVALID")
    if any(not isinstance(epoch[k], str) or not re.fullmatch(r"[0-9a-f]{64}", epoch[k])
           for k in ("manifestSha256", "corruptSourceSha256")):
        raise StateRecoveryError("EPOCH_SOURCE_IDENTITY_INVALID")
    boundary = timestamp(epoch["boundaryAt"])
    try:
        session = date.fromisoformat(epoch["firstProspectiveSession"])
        opening = datetime.fromisoformat(session.isoformat() + "T08:35:00-05:00")
    except (ValueError, TypeError) as exc:
        raise StateRecoveryError("EPOCH_SESSION_INVALID") from exc
    if not opening - timedelta(days=1) <= boundary < opening:
        raise StateRecoveryError("EPOCH_BOUNDARY_INVALID")
    body = {k: v for k, v in epoch.items() if k != "epochId"}
    if epoch["epochId"] != "AUTOMATION-PROSPECTIVE-" + digest(encoded(body)):
        raise StateRecoveryError("EPOCH_ID_INVALID")


def prospective_epoch(*, floor: datetime, first_session: str,
                      manifest_sha256: str, corrupt_sha256: str) -> dict:
    body = {"schemaVersion": 1, "boundaryAt": floor.isoformat(),
            "firstProspectiveSession": first_session, "manifestSha256": manifest_sha256.lower(),
            "corruptSourceSha256": corrupt_sha256.lower(), "legacyHistory": "UNKNOWN",
            "preEpochReplayBlocked": True}
    result = dict(body, epochId="AUTOMATION-PROSPECTIVE-" + digest(encoded(body)))
    validate_epoch(result)
    return result


def prepare_quarantined_epoch(*, output: Path, corrupt_bytes: bytes,
                              expected_corrupt_sha256: str, manifest_sha256: str,
                              floor: datetime, first_session: str | None = None) -> dict:
    """Prepare a NEW disposable proposal, never recover or replace a source path.

    The caller's adoption authority is deliberately not inferred. This artifact
    preserves unavailable legacy history, not reconstructed completion receipts.
    """
    import tempfile
    allowed = [Path(tempfile.gettempdir()).resolve(),
               Path.home() / "OneDrive/Documents/ArgusReviewBundles/LANE-OPENING-ENGINE"]
    resolved = output.resolve()
    if not any(resolved.is_relative_to(root.resolve()) and resolved != root.resolve() for root in allowed):
        raise StateRecoveryError("PROPOSAL_OUTPUT_OUTSIDE_DISPOSABLE_ROOT")
    if digest(corrupt_bytes) != expected_corrupt_sha256.lower():
        raise StateRecoveryError("CORRUPT_SOURCE_HASH_MISMATCH")
    try:
        decode(corrupt_bytes)
    except StateRecoveryError as exc:
        diagnosis = exc.code
    else:
        raise StateRecoveryError("SOURCE_NOT_CORRUPT")
    timestamp(floor.isoformat())
    if not re.fullmatch(r"[0-9a-fA-F]{64}", manifest_sha256):
        raise StateRecoveryError("MANIFEST_IDENTITY_INVALID")
    if first_session is None:
        opening = floor.replace(hour=8, minute=35, second=0, microsecond=0)
        first_session = (floor.date() + timedelta(days=int(floor >= opening))).isoformat()
    epoch = prospective_epoch(floor=floor, first_session=first_session,
                              manifest_sha256=manifest_sha256, corrupt_sha256=digest(corrupt_bytes))
    output.mkdir(parents=True, exist_ok=False)
    custody = output / "legacy-state.bin"
    durable_new(custody, corrupt_bytes)
    boundary = {"schemaVersion": 1, "classification": "PROPOSAL_REQUIRES_EXPLICIT_INTEGRATION_ADOPTION",
                "recoverySource": "NONE_ADMISSIBLE", "legacyHistory": "UNKNOWN",
                "corruptSourceSha256": digest(corrupt_bytes), "corruption": diagnosis,
                "manifestSha256": manifest_sha256.lower(), "prospectiveFloor": floor.isoformat(),
                "completionReceiptsFabricated": 0, "productionAdopted": False,
                "prospectiveEpoch": epoch}
    durable_new(output / "PROSPECTIVE-EPOCH-PROPOSAL.json", encoded(boundary))
    path = output / "state" / "automation-service-state.json"
    storage = DurableStateStorage(path, lambda source, target: source.replace(target))
    storage.save({"schema_version": 1, "jobs": {}, "recovery_floor_at": floor.isoformat(),
                  "prospective_epoch": epoch})
    return boundary


class DurableStateStorage:
    def __init__(self, path: Path, replace: Callable[[Path, Path], None]):
        self.path = path
        self.root = path.with_name(path.name + ".recovery")
        self.generations = self.root / "generations"
        self.claims = self.root / "claims"
        self.custody = self.root / "corrupt"
        self.anchor = self.root / "admission-head.json"
        self.replace = replace
        self.expected = self._current_digest()
        self.report: dict = {}

    def _current_digest(self):
        try:
            return digest(self.path.read_bytes())
        except FileNotFoundError:
            return None

    def preserve(self, path: Path, raw: bytes) -> None:
        self.custody.mkdir(parents=True, exist_ok=True)
        target = self.custody / (digest(raw) + ".bin")
        if target.exists():
            if target.read_bytes() != raw:
                raise StateRecoveryError("CORRUPT_CUSTODY_CONFLICT")
        else:
            durable_new(target, raw)

    def _generations(self, *, custody: bool) -> tuple[list[dict], list[str]]:
        valid, invalid = [], []
        for path in sorted(self.generations.glob("*.json")):
            raw = path.read_bytes()
            try:
                item = decode(raw)
                expected = f"{item.get('state_version', 0):020d}-{digest(raw)}.json"
                if path.name != expected:
                    raise StateRecoveryError("GENERATION_HASH_IDENTITY_MISMATCH")
                valid.append(item)
            except StateRecoveryError:
                invalid.append(path.name)
                if custody:
                    self.preserve(path, raw)
        return valid, invalid

    def _claims(self) -> dict:
        result = {}
        for path in sorted(self.claims.glob("*.json")):
            raw = path.read_bytes()
            item = decode(raw)
            if path.stem != digest(raw) or len(item["jobs"]) != 1:
                raise StateRecoveryError("CLAIM_HASH_IDENTITY_MISMATCH")
            receipt = next(iter(item["jobs"].values()))
            if receipt["status"] not in TERMINAL | {"RUNNING"}:
                raise StateRecoveryError("CLAIM_STATUS_INVALID")
            self._merge_receipt(result, receipt)
        return result

    def _anchor(self, *, required: bool) -> dict | None:
        try:
            raw = self.anchor.read_bytes()
        except FileNotFoundError:
            if required:
                raise StateRecoveryError("ADMISSION_ANCHOR_MISSING")
            return None
        try:
            value = json.loads(raw)
            if (not isinstance(value, dict) or set(value) != {"schema", "version", "generation", "claims", "sha256"}
                    or value["schema"] != 1 or type(value["version"]) is not int or value["version"] < 1
                    or not isinstance(value["claims"], list)
                    or any(not isinstance(x, str) or not re.fullmatch(r"[0-9a-f]{64}\.json", x) for x in value["claims"])
                    or len(value["claims"]) != len(set(value["claims"]))
                    or not isinstance(value["generation"], str)
                    or not re.fullmatch(r"[0-9]{20}-[0-9a-f]{64}\.json", value["generation"])):
                raise ValueError("shape")
            body = {k:v for k,v in value.items() if k != "sha256"}
            if value["sha256"] != digest(encoded(body)):
                raise ValueError("hash")
            if int(value["generation"].split("-", 1)[0]) != value["version"]:
                raise ValueError("version")
            for name in value["claims"]:
                claim = self.claims / name
                if not claim.is_file() or digest(claim.read_bytes()) + ".json" != name:
                    raise StateRecoveryError("ADMITTED_CLAIM_MISSING_OR_CORRUPT")
            return value
        except (ValueError, UnicodeError, KeyError, TypeError) as exc:
            raise StateRecoveryError("ADMISSION_ANCHOR_INVALID") from exc

    @staticmethod
    def _merge_receipt(jobs: dict, receipt: dict) -> None:
        old = jobs.get(receipt["job_id"])
        if old:
            if receipt_identity(old) != receipt_identity(receipt):
                raise StateRecoveryError("JOB_IDENTITY_MISMATCH")
            if (old.get("job_definition_sha256") and receipt.get("job_definition_sha256")
                    and old["job_definition_sha256"] != receipt["job_definition_sha256"]):
                raise StateRecoveryError("JOB_DEFINITION_MISMATCH")
            if old["status"] in TERMINAL:
                if receipt["status"] in TERMINAL and not equivalent_receipt(old, receipt):
                    raise StateRecoveryError("TERMINAL_AUTHORITY_CONFLICT")
                return
        jobs[receipt["job_id"]] = receipt

    def load(self, *, now: datetime, custody: bool = False) -> dict | None:
        raw = None
        current = None
        error = ""
        try:
            raw = self.path.read_bytes()
            current = decode(raw)
        except FileNotFoundError:
            error = "MISSING_STATE"
        except StateRecoveryError as exc:
            error = exc.code
            if custody and raw is not None:
                self.preserve(self.path, raw)
        generations, bad = self._generations(custody=custody)
        anchor = self._anchor(required=bool(generations or bad or (current and current.get("state_version", 0))))
        claims = self._claims()
        if current is None and not generations:
            self.report = {"state": error, "recovery_source": "NONE_ADMISSIBLE", "invalid_generations": bad}
            if raw is None and not self.root.exists() and not self.path.parent.exists():
                return None
            raise StateRecoveryError("NONE_ADMISSIBLE:" + error)
        candidates = generations + ([current] if current else [])
        epochs = [item["prospective_epoch"] for item in candidates if item.get("prospective_epoch")]
        if epochs and (any(epoch != epochs[0] for epoch in epochs)
                       or current is not None and current.get("prospective_epoch") != epochs[0]):
            raise StateRecoveryError("EPOCH_HISTORY_CONFLICT")
        if epochs:
            first_epoch_version = min(item.get("state_version", 0) for item in candidates if item.get("prospective_epoch"))
            if any(item.get("state_version", 0) >= first_epoch_version and item.get("prospective_epoch") != epochs[0]
                   for item in candidates):
                raise StateRecoveryError("EPOCH_HISTORY_CONFLICT")
        versions = {}
        for item in candidates:
            version = item.get("state_version", 0)
            if version and version in versions and versions[version] != item:
                raise StateRecoveryError("STATE_VERSION_CONFLICT")
            versions[version] = item
        selected = max(candidates, key=lambda x: x.get("state_version", 0))
        selected = json.loads(json.dumps(selected))
        current_admitted = bool(current is not None and anchor
                                and self._generation_name(current) == anchor["generation"])
        # Every retained completion is authoritative, not just the newest JSON.
        for item in candidates:
            for receipt in item["jobs"].values():
                if receipt["status"] in TERMINAL | {"RUNNING"}:
                    self._merge_receipt(claims, receipt)
        for receipt in claims.values():
            self._merge_receipt(selected["jobs"], receipt)
        recovered = (current is None or selected != current
                     or bool(anchor and self._generation_name(selected) != anchor["generation"]))
        if recovered and not current_admitted:
            floor = timestamp(selected["recovery_floor_at"]) if selected.get("recovery_floor_at") else now
            selected["recovery_floor_at"] = max(now, floor).isoformat()
        self.expected = digest(raw) if raw is not None else None
        self.report = {"state": error or "VALID", "recovery_source": "RECONCILED_GENERATIONS_AND_CLAIMS" if recovered else "CURRENT",
                       "invalid_generations": bad, "valid_generations": len(generations),
                       "classifications": {k: ("PROVEN_COMPLETE" if v["status"] == "COMPLETED" else
                           "PROVEN_INCOMPLETE" if v["status"] == "RUNNING" else
                           "PROVEN_NOT_RUN" if v["status"] in {"MISSED", "DISABLED", "BLOCKED_DEPENDENCY"} else "UNKNOWN")
                           for k, v in selected["jobs"].items()}}
        validate(selected)
        return selected

    def save(self, payload: dict) -> int:
        validate(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with PathTransactionLease(self.path).transaction():
            if self._current_digest() != self.expected:
                raise StateRecoveryError("CONCURRENT_STATE_CHANGED")
            try:
                current = decode(self.path.read_bytes()) if self.path.exists() else None
            except StateRecoveryError:
                if self.report.get("recovery_source") != "RECONCILED_GENERATIONS_AND_CLAIMS":
                    raise
                self.preserve(self.path, self.path.read_bytes())
                current = None
            generations, bad = self._generations(custody=True)
            anchor = self._anchor(required=bool(generations or bad or (current and current.get("state_version", 0))))
            old_jobs = self._claims()
            for item in generations + ([current] if current else []):
                for receipt in item["jobs"].values():
                    if receipt["status"] in TERMINAL | {"RUNNING"}:
                        self._merge_receipt(old_jobs, receipt)
            for key, old in old_jobs.items():
                new = payload["jobs"].get(key)
                if new is None or receipt_identity(new) != receipt_identity(old):
                    raise StateRecoveryError("PROVEN_HISTORY_LOSS")
                if old.get("job_definition_sha256") and new.get("job_definition_sha256") != old["job_definition_sha256"]:
                    raise StateRecoveryError("JOB_DEFINITION_MISMATCH")
                if old["status"] in TERMINAL and not equivalent_receipt(new, old):
                    raise StateRecoveryError("TERMINAL_HISTORY_REWRITE")
                if old["status"] == "RUNNING" and new["status"] == "PENDING":
                    raise StateRecoveryError("RUNNING_HISTORY_ROLLBACK")
            prior_floor = max((timestamp(x["recovery_floor_at"]) for x in generations + ([current] if current else []) if x.get("recovery_floor_at")), default=None)
            for previous in generations + ([current] if current else []):
                if previous.get("prospective_epoch") and payload.get("prospective_epoch") != previous["prospective_epoch"]:
                    raise StateRecoveryError("EPOCH_HISTORY_REWRITE")
            if prior_floor and (not payload.get("recovery_floor_at") or timestamp(payload["recovery_floor_at"]) < prior_floor):
                raise StateRecoveryError("RECOVERY_FLOOR_ROLLBACK")
            version = max([x.get("state_version", 0) for x in generations + ([current] if current else [])] + [anchor["version"] if anchor else 0]) + 1
            payload = dict(payload, state_version=version)
            raw = encoded(payload)
            self.generations.mkdir(parents=True, exist_ok=True)
            self.claims.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                durable_new(temporary, raw)
                decode(temporary.read_bytes())
                if current:
                    self._retain(current)
                # Claims become durable before execution can follow RUNNING save.
                for receipt in payload["jobs"].values():
                    if receipt["status"] not in TERMINAL | {"RUNNING"}:
                        continue
                    claim = encoded({"schema_version": 1, "jobs": {receipt["job_id"]: receipt}})
                    claim_path = self.claims / (digest(claim) + ".json")
                    if not claim_path.exists():
                        durable_new(claim_path, claim)
                self._retain(payload)
                anchor_value = {"schema": 1, "version": version, "generation": self._generation_name(payload),
                                "claims": sorted(p.name for p in self.claims.glob("*.json"))}
                anchor_raw = encoded(dict(anchor_value, sha256=digest(encoded(anchor_value))))
                anchor_temp = self.root / (uuid.uuid4().hex + ".tmp")
                try:
                    durable_new(anchor_temp, anchor_raw)
                    self.replace(anchor_temp, self.anchor)
                    sync_directory(self.root)
                finally:
                    anchor_temp.unlink(missing_ok=True)
                self.replace(temporary, self.path)
                sync_directory(self.path.parent)
                self.expected = digest(raw)
                # Remove only validated surplus generations after successful promotion.
                valid, _ = self._generations(custody=True)
                keep = sorted(valid, key=lambda x: x.get("state_version", 0), reverse=True)[:RETAINED_GENERATIONS]
                keep_names = {self._generation_name(x) for x in keep}
                for item in valid:
                    name = self._generation_name(item)
                    if name not in keep_names:
                        (self.generations / name).unlink()
                for name in bad:
                    damaged = self.generations / name
                    if damaged.resolve().parent != self.generations.resolve():
                        raise StateRecoveryError("GENERATION_PATH_ESCAPE")
                    self.preserve(damaged, damaged.read_bytes())
                    damaged.unlink()
                return version
            finally:
                temporary.unlink(missing_ok=True)

    @staticmethod
    def _generation_name(payload: dict) -> str:
        return f"{payload.get('state_version', 0):020d}-{digest(encoded(payload))}.json"

    def _retain(self, payload: dict) -> None:
        path = self.generations / self._generation_name(payload)
        raw = encoded(payload)
        if path.exists():
            if path.read_bytes() != raw:
                raise StateRecoveryError("GENERATION_CONFLICT")
        else:
            durable_new(path, raw)
