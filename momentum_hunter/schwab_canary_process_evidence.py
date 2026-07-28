from __future__ import annotations

"""Immutable persistence for canary process-target and liveness evidence."""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Final

from momentum_hunter.schwab_canary_process_observer import (
    CANARY_PROCESS_OBSERVER_SCHEMA_VERSION,
    CanaryProcessLivenessEvidence,
    CanaryProcessObserverError,
    CanaryProcessTarget,
)


CANARY_PROCESS_EVIDENCE_CHAIN_SCHEMA_VERSION: Final = (
    "SCHWAB_CANARY_PROCESS_EVIDENCE_CHAIN_V1"
)
PROCESS_TARGET_FILENAME: Final = "process-target.json"
PROCESS_OBSERVATIONS_DIRECTORY: Final = "observations"
PROCESS_EVIDENCE_NOT_CREATED: Final = "NOT_CREATED"
PROCESS_EVIDENCE_TARGET_ONLY: Final = "TARGET_ONLY"
PROCESS_EVIDENCE_RECORDED: Final = "EVIDENCE_RECORDED"

_MAX_RECORD_BYTES = 32_768
_MAX_OBSERVATIONS = 256
_OBSERVATION_FILENAME = re.compile(r"^(?P<sequence>[0-9]{6})\.json$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CanaryProcessEvidenceError(RuntimeError):
    pass


class CanaryProcessEvidenceConflict(CanaryProcessEvidenceError):
    pass


@dataclass(frozen=True)
class CanaryProcessObservationRecord:
    sequence: int
    previous_record_sha256: str | None
    evidence: CanaryProcessLivenessEvidence

    def __post_init__(self) -> None:
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence <= 0
            or self.sequence > _MAX_OBSERVATIONS
        ):
            raise CanaryProcessEvidenceError(
                "Process observation sequence is invalid."
            )
        if self.sequence == 1:
            if self.previous_record_sha256 is not None:
                raise CanaryProcessEvidenceError(
                    "The first process observation cannot have a predecessor."
                )
        elif (
            self.previous_record_sha256 is None
            or not _SHA256.fullmatch(self.previous_record_sha256)
        ):
            raise CanaryProcessEvidenceError(
                "A later process observation requires a predecessor hash."
            )

    @property
    def record_sha256(self) -> str:
        return _sha256(self.payload())

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": CANARY_PROCESS_EVIDENCE_CHAIN_SCHEMA_VERSION,
            "recordType": "CANARY_PROCESS_OBSERVATION_RECORD",
            "sequence": self.sequence,
            "targetSha256": self.evidence.target_sha256,
            "previousRecordSha256": self.previous_record_sha256,
            "evidenceSha256": self.evidence.record_sha256,
            "evidence": self.evidence.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self.payload(),
            "recordSha256": self.record_sha256,
            "appendOnly": True,
            "replaceSupported": False,
            "clearSupported": False,
            "rawExecutablePathRetained": False,
            "processMutationPerformed": False,
            "credentialMutationPerformed": False,
            "brokerActionAllowed": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }


class CanaryProcessEvidenceStore:
    """Write one target and an immutable, hash-linked observation sequence."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @property
    def target_path(self) -> Path:
        return self.root / PROCESS_TARGET_FILENAME

    @property
    def observations_path(self) -> Path:
        return self.root / PROCESS_OBSERVATIONS_DIRECTORY

    def persist_target(
        self,
        target: CanaryProcessTarget,
    ) -> CanaryProcessTarget:
        self._ensure_root()
        if (
            self.observations_path.exists()
            or self.observations_path.is_symlink()
        ):
            self._validate_observations_directory()
            if any(self.observations_path.iterdir()):
                raise CanaryProcessEvidenceConflict(
                    "Process observations exist without an immutable target."
                )
        payload = target.to_dict()
        encoded = _encode_payload(payload)
        try:
            _create_exclusive_file(self.target_path, encoded)
        except FileExistsError:
            try:
                existing = self.load_target()
            except CanaryProcessEvidenceError as exc:
                raise CanaryProcessEvidenceConflict(
                    "A different or invalid process target already exists."
                ) from exc
            if existing == target:
                return existing
            raise CanaryProcessEvidenceConflict(
                "A different or invalid process target already exists."
            ) from None
        persisted = self.load_target()
        if persisted != target:
            raise CanaryProcessEvidenceError(
                "Persisted process target failed validation."
            )
        return persisted

    def load_target(self) -> CanaryProcessTarget | None:
        self._validate_root_if_present()
        if self.target_path.is_symlink():
            raise CanaryProcessEvidenceError(
                "Process target must be a regular non-symlink file."
            )
        if not self.target_path.exists():
            return None
        payload = _load_payload(self.target_path, label="Process target")
        return _parse_target(payload)

    def append_observation(
        self,
        evidence: CanaryProcessLivenessEvidence,
    ) -> CanaryProcessObservationRecord:
        target = self.load_target()
        if target is None:
            raise CanaryProcessEvidenceError(
                "A process target must be persisted before observations."
            )
        _validate_evidence_against_target(evidence, target)
        self._ensure_observations_directory()
        records = self._load_observations_for_append(target)
        for record in records:
            if record.evidence.record_sha256 == evidence.record_sha256:
                if record.evidence != evidence:
                    raise CanaryProcessEvidenceError(
                        "A process observation hash collision was detected."
                    )
                return record
        if len(records) >= _MAX_OBSERVATIONS:
            raise CanaryProcessEvidenceError(
                "Process observation limit has been reached."
            )
        if records:
            latest_at = _parse_timestamp(
                records[-1].evidence.observed_at,
                field="latest process observation",
            )
            observed_at = _parse_timestamp(
                evidence.observed_at,
                field="new process observation",
            )
            if observed_at < latest_at:
                raise CanaryProcessEvidenceError(
                    "Process observation chronology cannot move backward."
                )
            if (
                records[-1].evidence.process_running is False
                and evidence.process_running is True
            ):
                raise CanaryProcessEvidenceError(
                    "A conclusively stopped target cannot become running."
                )
        sequence = len(records) + 1
        record = CanaryProcessObservationRecord(
            sequence=sequence,
            previous_record_sha256=(
                records[-1].record_sha256 if records else None
            ),
            evidence=evidence,
        )
        path = self.observations_path / f"{sequence:06d}.json"
        try:
            _create_exclusive_file(path, _encode_payload(record.to_dict()))
        except FileExistsError:
            current = self.load_observations()
            for persisted in current:
                if persisted.evidence.record_sha256 == evidence.record_sha256:
                    if persisted.evidence == evidence:
                        return persisted
                    raise CanaryProcessEvidenceError(
                        "A process observation hash collision was detected."
                    )
            raise CanaryProcessEvidenceConflict(
                "A concurrent process observation claimed the next sequence."
            ) from None
        persisted = self.load_observations()
        if len(persisted) < sequence or persisted[sequence - 1] != record:
            raise CanaryProcessEvidenceError(
                "Persisted process observation failed validation."
            )
        return persisted[sequence - 1]

    def load_observations(self) -> tuple[CanaryProcessObservationRecord, ...]:
        target = self.load_target()
        if target is None:
            if (
                self.observations_path.exists()
                or self.observations_path.is_symlink()
            ):
                raise CanaryProcessEvidenceError(
                    "Process observations cannot exist without a target."
                )
            return ()
        if not self.observations_path.exists():
            return ()
        self._validate_observations_directory()
        paths = sorted(self.observations_path.iterdir())
        if len(paths) > _MAX_OBSERVATIONS:
            raise CanaryProcessEvidenceError(
                "Process observation limit was exceeded."
            )
        records: list[CanaryProcessObservationRecord] = []
        previous_hash: str | None = None
        previous_time: datetime | None = None
        evidence_hashes: set[str] = set()
        for expected_sequence, path in enumerate(paths, start=1):
            if path.is_symlink() or not path.is_file():
                raise CanaryProcessEvidenceError(
                    "Process observations must be regular non-symlink files."
                )
            match = _OBSERVATION_FILENAME.fullmatch(path.name)
            if (
                match is None
                or int(match.group("sequence")) != expected_sequence
            ):
                raise CanaryProcessEvidenceError(
                    "Process observation filenames must form a contiguous sequence."
                )
            record = _parse_observation_record(
                _load_payload(path, label="Process observation")
            )
            if record.sequence != expected_sequence:
                raise CanaryProcessEvidenceError(
                    "Process observation sequence does not match its filename."
                )
            if record.previous_record_sha256 != previous_hash:
                raise CanaryProcessEvidenceError(
                    "Process observation hash chain is invalid."
                )
            _validate_evidence_against_target(record.evidence, target)
            observed_at = _parse_timestamp(
                record.evidence.observed_at,
                field="process observation",
            )
            if previous_time is not None and observed_at < previous_time:
                raise CanaryProcessEvidenceError(
                    "Process observation chronology moved backward."
                )
            evidence_hash = record.evidence.record_sha256
            if evidence_hash in evidence_hashes:
                raise CanaryProcessEvidenceError(
                    "Duplicate process observation evidence was persisted."
                )
            evidence_hashes.add(evidence_hash)
            records.append(record)
            previous_hash = record.record_sha256
            previous_time = observed_at
        return tuple(records)

    def inspect(self) -> dict[str, object]:
        target = self.load_target()
        if target is None:
            return _inspection_payload(
                status=PROCESS_EVIDENCE_NOT_CREATED,
                target_sha256=None,
                records=(),
            )
        records = self.load_observations()
        return _inspection_payload(
            status=(
                PROCESS_EVIDENCE_RECORDED
                if records
                else PROCESS_EVIDENCE_TARGET_ONLY
            ),
            target_sha256=target.target_sha256,
            records=records,
        )

    def _load_observations_for_append(
        self,
        target: CanaryProcessTarget,
    ) -> tuple[CanaryProcessObservationRecord, ...]:
        del target
        return self.load_observations()

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            raise CanaryProcessEvidenceError(
                "Process evidence root cannot be a symlink."
            )
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise CanaryProcessEvidenceError(
                "Process evidence root cannot be created safely."
            ) from exc
        if not self.root.is_dir() or self.root.is_symlink():
            raise CanaryProcessEvidenceError(
                "Process evidence root must be a regular directory."
            )

    def _validate_root_if_present(self) -> None:
        if self.root.is_symlink():
            raise CanaryProcessEvidenceError(
                "Process evidence root cannot be a symlink."
            )
        if self.root.exists() and not self.root.is_dir():
            raise CanaryProcessEvidenceError(
                "Process evidence root must be a regular directory."
            )

    def _ensure_observations_directory(self) -> None:
        self._ensure_root()
        if self.observations_path.is_symlink():
            raise CanaryProcessEvidenceError(
                "Process observations directory cannot be a symlink."
            )
        try:
            self.observations_path.mkdir(exist_ok=True)
        except OSError as exc:
            raise CanaryProcessEvidenceError(
                "Process observations directory cannot be created safely."
            ) from exc
        self._validate_observations_directory()

    def _validate_observations_directory(self) -> None:
        if (
            not self.observations_path.is_dir()
            or self.observations_path.is_symlink()
        ):
            raise CanaryProcessEvidenceError(
                "Process observations must use a regular directory."
            )


def _inspection_payload(
    *,
    status: str,
    target_sha256: str | None,
    records: tuple[CanaryProcessObservationRecord, ...],
) -> dict[str, object]:
    latest = records[-1] if records else None
    return {
        "schemaVersion": CANARY_PROCESS_EVIDENCE_CHAIN_SCHEMA_VERSION,
        "status": status,
        "targetSha256": target_sha256,
        "observationCount": len(records),
        "latestRecordSha256": (
            latest.record_sha256 if latest is not None else None
        ),
        "latestConclusion": (
            latest.evidence.conclusion if latest is not None else None
        ),
        "latestProcessRunning": (
            latest.evidence.process_running if latest is not None else None
        ),
        "immutableEvidence": True,
        "rawExecutablePathRetained": False,
        "processMutationPerformed": False,
        "credentialMutationPerformed": False,
        "brokerActionAllowed": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }


def _validate_evidence_against_target(
    evidence: CanaryProcessLivenessEvidence,
    target: CanaryProcessTarget,
) -> None:
    if (
        evidence.target_sha256 != target.target_sha256
        or evidence.observer_id != target.observer_id
        or evidence.source != target.source
        or evidence.runtime_instance_id != target.runtime_instance_id
        or evidence.process_id != target.process_id
    ):
        raise CanaryProcessEvidenceError(
            "Process observation does not match the immutable target."
        )
    if _parse_timestamp(
        evidence.observed_at,
        field="process observation",
    ) < _parse_timestamp(target.captured_at, field="process target capture"):
        raise CanaryProcessEvidenceError(
            "Process observation predates target capture."
        )


def _parse_target(payload: dict[str, object]) -> CanaryProcessTarget:
    expected_keys = {
        "schemaVersion",
        "recordType",
        "observerId",
        "source",
        "runtimeInstanceId",
        "processId",
        "processCreatedAt",
        "executablePathSha256",
        "capturedAt",
        "targetSha256",
        "rawExecutablePathRetained",
        "processMutationPerformed",
        "credentialMutationPerformed",
        "brokerActionAllowed",
        "transmitting",
        "orderTransmission",
    }
    if set(payload) != expected_keys:
        raise CanaryProcessEvidenceError(
            "Process target fields do not match the frozen schema."
        )
    _validate_observer_safety_flags(payload)
    try:
        target = CanaryProcessTarget(
            observer_id=_require_string(
                payload["observerId"],
                field="observerId",
            ),
            source=_require_string(payload["source"], field="source"),
            runtime_instance_id=_require_string(
                payload["runtimeInstanceId"],
                field="runtimeInstanceId",
            ),
            process_id=_require_integer(
                payload["processId"],
                field="processId",
            ),
            process_created_at=_require_string(
                payload["processCreatedAt"],
                field="processCreatedAt",
            ),
            executable_path_sha256=_require_string(
                payload["executablePathSha256"],
                field="executablePathSha256",
            ),
            captured_at=_require_string(
                payload["capturedAt"],
                field="capturedAt",
            ),
        )
    except CanaryProcessObserverError as exc:
        raise CanaryProcessEvidenceError(
            "Process target content is invalid."
        ) from exc
    if payload != target.to_dict():
        raise CanaryProcessEvidenceError(
            "Process target content or hash is invalid."
        )
    return target


def _parse_observation_record(
    payload: dict[str, object],
) -> CanaryProcessObservationRecord:
    expected_keys = {
        "schemaVersion",
        "recordType",
        "sequence",
        "targetSha256",
        "previousRecordSha256",
        "evidenceSha256",
        "evidence",
        "recordSha256",
        "appendOnly",
        "replaceSupported",
        "clearSupported",
        "rawExecutablePathRetained",
        "processMutationPerformed",
        "credentialMutationPerformed",
        "brokerActionAllowed",
        "transmitting",
        "orderTransmission",
    }
    if set(payload) != expected_keys:
        raise CanaryProcessEvidenceError(
            "Process observation record fields do not match the frozen schema."
        )
    if (
        payload["schemaVersion"]
        != CANARY_PROCESS_EVIDENCE_CHAIN_SCHEMA_VERSION
        or payload["recordType"] != "CANARY_PROCESS_OBSERVATION_RECORD"
        or payload["appendOnly"] is not True
        or payload["replaceSupported"] is not False
        or payload["clearSupported"] is not False
    ):
        raise CanaryProcessEvidenceError(
            "Process observation record metadata is invalid."
        )
    _validate_observer_safety_flags(payload)
    evidence_payload = payload["evidence"]
    if not isinstance(evidence_payload, dict):
        raise CanaryProcessEvidenceError(
            "Process observation evidence must be a JSON object."
        )
    evidence = _parse_liveness_evidence(evidence_payload)
    previous = payload["previousRecordSha256"]
    if previous is not None and not isinstance(previous, str):
        raise CanaryProcessEvidenceError(
            "Process observation predecessor hash is invalid."
        )
    record = CanaryProcessObservationRecord(
        sequence=_require_integer(payload["sequence"], field="sequence"),
        previous_record_sha256=previous,
        evidence=evidence,
    )
    if payload != record.to_dict():
        raise CanaryProcessEvidenceError(
            "Process observation record content or hash is invalid."
        )
    return record


def _parse_liveness_evidence(
    payload: dict[str, object],
) -> CanaryProcessLivenessEvidence:
    expected_keys = {
        "schemaVersion",
        "recordType",
        "targetSha256",
        "observerId",
        "source",
        "runtimeInstanceId",
        "processId",
        "observedAt",
        "observationState",
        "processRunning",
        "pidReused",
        "observedProcessCreatedAt",
        "observedExecutablePathSha256",
        "conclusion",
        "recordSha256",
        "independentObservation",
        "rawExecutablePathRetained",
        "processMutationPerformed",
        "credentialMutationPerformed",
        "brokerActionAllowed",
        "transmitting",
        "orderTransmission",
    }
    if set(payload) != expected_keys:
        raise CanaryProcessEvidenceError(
            "Process liveness evidence fields do not match the frozen schema."
        )
    if (
        payload["schemaVersion"] != CANARY_PROCESS_OBSERVER_SCHEMA_VERSION
        or payload["recordType"] != "CANARY_PROCESS_LIVENESS_EVIDENCE"
        or payload["independentObservation"] is not True
    ):
        raise CanaryProcessEvidenceError(
            "Process liveness evidence metadata is invalid."
        )
    _validate_observer_safety_flags(payload)
    process_running = payload["processRunning"]
    if process_running is not None and not isinstance(process_running, bool):
        raise CanaryProcessEvidenceError(
            "Process running state must be boolean or unavailable."
        )
    pid_reused = payload["pidReused"]
    if not isinstance(pid_reused, bool):
        raise CanaryProcessEvidenceError(
            "Process PID-reuse state must be boolean."
        )
    try:
        evidence = CanaryProcessLivenessEvidence(
            target_sha256=_require_string(
                payload["targetSha256"],
                field="targetSha256",
            ),
            observer_id=_require_string(
                payload["observerId"],
                field="observerId",
            ),
            source=_require_string(payload["source"], field="source"),
            runtime_instance_id=_require_string(
                payload["runtimeInstanceId"],
                field="runtimeInstanceId",
            ),
            process_id=_require_integer(
                payload["processId"],
                field="processId",
            ),
            observed_at=_require_string(
                payload["observedAt"],
                field="observedAt",
            ),
            observation_state=_require_string(
                payload["observationState"],
                field="observationState",
            ),
            process_running=process_running,
            pid_reused=pid_reused,
            observed_process_created_at=_optional_string(
                payload["observedProcessCreatedAt"],
                field="observedProcessCreatedAt",
            ),
            observed_executable_path_sha256=_optional_string(
                payload["observedExecutablePathSha256"],
                field="observedExecutablePathSha256",
            ),
            conclusion=_require_string(
                payload["conclusion"],
                field="conclusion",
            ),
        )
    except CanaryProcessObserverError as exc:
        raise CanaryProcessEvidenceError(
            "Process liveness evidence content is invalid."
        ) from exc
    if payload != evidence.to_dict():
        raise CanaryProcessEvidenceError(
            "Process liveness evidence content or hash is invalid."
        )
    return evidence


def _validate_observer_safety_flags(payload: dict[str, object]) -> None:
    if (
        payload.get("rawExecutablePathRetained") is not False
        or payload.get("processMutationPerformed") is not False
        or payload.get("credentialMutationPerformed") is not False
        or payload.get("brokerActionAllowed") is not False
        or payload.get("transmitting") is not False
        or payload.get("orderTransmission") != "UNAVAILABLE"
    ):
        raise CanaryProcessEvidenceError(
            "Process evidence safety flags are invalid."
        )


def _create_exclusive_file(path: Path, encoded: bytes) -> None:
    if len(encoded) <= 0 or len(encoded) > _MAX_RECORD_BYTES:
        raise CanaryProcessEvidenceError(
            "Process evidence record has an invalid size."
        )
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        # Partial evidence remains fail-closed and is never removed or repaired.
        raise


def _load_payload(path: Path, *, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise CanaryProcessEvidenceError(
            f"{label} must be a regular non-symlink file."
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CanaryProcessEvidenceError(f"{label} is unavailable.") from exc
    if size <= 0 or size > _MAX_RECORD_BYTES:
        raise CanaryProcessEvidenceError(f"{label} has an invalid size.")
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanaryProcessEvidenceError(
            f"{label} is unreadable or malformed."
        ) from exc
    if not isinstance(payload, dict):
        raise CanaryProcessEvidenceError(
            f"{label} must contain a JSON object."
        )
    return payload


def _encode_payload(payload: dict[str, object]) -> bytes:
    try:
        return (
            json.dumps(
                payload,
                indent=2,
                sort_keys=True,
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise CanaryProcessEvidenceError(
            "Process evidence cannot be encoded safely."
        ) from exc


def _parse_timestamp(value: str, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise CanaryProcessEvidenceError(
            f"{field} must be a valid ISO 8601 timestamp."
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CanaryProcessEvidenceError(
            f"{field} must include a UTC offset."
        )
    return parsed


def _require_string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise CanaryProcessEvidenceError(f"{field} must be a string.")
    return value


def _optional_string(value: object, *, field: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field=field)


def _require_integer(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanaryProcessEvidenceError(f"{field} must be an integer.")
    return value


def _sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
