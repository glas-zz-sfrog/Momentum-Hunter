"""Append-only, restart-safe Strategy Science custody kernel.

The recorder is dormant until explicitly constructed and given caller-owned
bytes.  It has no source reader, provider client, authentication, account,
broker, order, Paper, Shadow, service, scheduler, or runtime integration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path, PurePath
from typing import Callable, Iterable, Mapping

from momentum_hunter.windows_writer_storage import (
    WriterPhysicalStorage,
    WriterPhysicalStorageError,
)

from .canonical import (
    CANONICALIZATION_VERSION,
    CanonicalizationError,
    canonical_json_bytes,
    owner_identity,
    parse_rfc3339,
    recorder_identity,
    require_sha256,
    sha256_hex,
    strict_json_loads,
)
from .contract import (
    AUTHORITY,
    BASE_CANONICAL_SHA,
    EVENT_CHANNEL,
    EXECUTION_AUTHORITY,
    GENESIS_SHA256,
    PREDECESSOR_DIRECTIVE,
    PREDECESSOR_SCHEMA_SHA256,
    PREDECESSOR_SCHEMA_VERSION,
    PREDECESSOR_SIDECAR_SHA256,
    REPAIRED_EXPORT_SCHEMA_VERSION,
    REPAIRED_SOURCE_CONTRACT_VERSION,
    RECORD_FAMILIES,
    RecorderContractError,
    SCHEMA_MAJOR_VERSION,
    SCHEMA_VERSION,
    SOURCE_CONTRACT,
    TIME_NORMALIZATION_RULE,
    ValidatedExportEnvelope,
    evidence_instant,
    parse_export_envelope,
    require_evidence_value,
    require_exact_fields,
    require_instrument_identity,
    require_integer,
    require_identity,
    require_time_evidence,
    require_versioned_reason,
    validate_start_manifest,
)
from .coverage import CoverageSummary, derive_coverage
from .outcomes import ValidatedOutcomeAttachment, parse_outcome_attachment


TOPOLOGY_VERSION = 1
TOPOLOGY_PROFILE = "ARGUS_SCIENCE_RECORDER_CUSTODY_V1"
CURSOR_VERSION = "ARGUS_RECORDER_CURSOR_V1"
RECEIPT_VERSION = "ARGUS_RECORDER_RECEIPT_V1"
MANIFEST_VERSION = "ARGUS_RECORDER_MANIFEST_V1"
SCIENCE_ELIGIBILITY_PROFILE = "ARGUS_SCIENCE_RECEIPT_ELIGIBILITY_V2"
SCIENCE_ELIGIBILITY_RECORD_VERSION = "2.0.0"


class RecorderCustodyError(RuntimeError):
    """Raised when append-only custody cannot prove a safe transition."""


class RecorderConflictError(RecorderCustodyError):
    """Raised after persistent evidence freezes one affected source stream."""


class RecorderRecoveryError(RecorderCustodyError):
    """Raised when persisted bytes do not prove a safe restart cursor."""


class SimulatedRecorderCrash(RecorderCustodyError):
    """Fault-injection exception used only by offline acceptance tests."""


@dataclass(frozen=True)
class AcceptanceResult:
    status: str
    source_kind: str
    source_event_id: str
    source_sequence: int
    record_ids: tuple[str, ...]
    checkpoint_sha256: str


@dataclass(frozen=True)
class VerificationReport:
    session_id: str
    partition_id: str
    source_count: int
    payload_count: int
    receipt_count: int
    checkpoint_count: int
    conflict_count: int
    final_manifest_present: bool
    all_hashes_valid: bool


@dataclass(frozen=True)
class FinalizationResult:
    status: str
    custody_classification: str
    manifest_relative_path: str
    manifest_sha256: str
    checksum_relative_path: str
    checksum_sha256: str
    coverage: CoverageSummary


@dataclass(frozen=True)
class _ChannelState:
    channel: str
    payloads: Mapping[str, tuple[Path, Mapping[str, object], bytes]]
    receipts: Mapping[str, tuple[Path, Mapping[str, object], bytes]]
    orphan_payload_keys: tuple[str, ...]
    last_sequence: int
    last_receipt_sha256: str


@dataclass(frozen=True)
class _StreamState:
    source_kind: str
    stream_id: str
    checkpoints: tuple[Mapping[str, object], ...]
    last_sequence: int
    last_source_sha256: str
    last_checkpoint_sha256: str


def _text(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise RecorderContractError(f"{field} must be a nonempty string.")
    return item


def _positive_or_zero_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RecorderContractError(f"{label} must be a nonnegative integer.")
    return value


def _record_key(recorder_id: str) -> str:
    return sha256_hex(recorder_id.encode("utf-8"))


def _stream_key(source_kind: str, stream_id: str) -> str:
    return sha256_hex(
        canonical_json_bytes({"source_kind": source_kind, "stream_id": stream_id})
    )


def _source_event_key(source_event_id: str) -> str:
    return sha256_hex(source_event_id.encode("utf-8"))


def _capture_time_evidence(value: str) -> dict[str, object]:
    parse_rfc3339(value, "recorder_capture_time")
    offset = "Z" if value.endswith("Z") else value[-6:]
    precision = "subsecond" if "." in value else "second"
    return {
        "authority": "SCIENCE_RECORDER_CLOCK",
        "normalized_rfc3339": value,
        "normalization_rule_version": TIME_NORMALIZATION_RULE,
        "precision": precision,
        "raw_value": value,
        "reason_code": "PRESENT",
        "role": "RECORDER_CAPTURE_TIME",
        "state": "PRESENT",
        "timezone_or_offset": offset,
    }


def science_eligibility_sha256(value: Mapping[str, object]) -> str:
    """Hash the exact Science-owned eligibility material, excluding its self-hash."""

    material = dict(value)
    material.pop("commitment_payload_sha256", None)
    return sha256_hex(canonical_json_bytes(material))


def _present_value(value: object, *, authority: str) -> dict[str, object]:
    return {
        "authority": authority,
        "reason_code": "PRESENT",
        "state": "PRESENT",
        "value": value,
    }


def _not_applicable(reason: str, *, authority: str) -> dict[str, object]:
    return {
        "authority": authority,
        "reason_code": reason,
        "state": "NOT_APPLICABLE",
    }


def _resolve_json_pointer(document: object, pointer: str) -> object:
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        raise RecorderContractError("Evidence field path must be a non-root JSON Pointer.")
    current = document
    for raw_part in pointer[1:].split("/"):
        if "~" in raw_part.replace("~0", "").replace("~1", ""):
            raise RecorderContractError("Evidence field path contains invalid JSON Pointer escaping.")
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if part not in current:
                raise RecorderContractError("Evidence field path does not resolve in parent payload.")
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                raise RecorderContractError("Evidence field path has an invalid array index.")
            index = int(part)
            if index >= len(current):
                raise RecorderContractError("Evidence field path array index is out of bounds.")
            current = current[index]
        else:
            raise RecorderContractError("Evidence field path crosses a scalar value.")
    return current


def _outcome_slot(payload: Mapping[str, object]) -> tuple[str, str, str, str, str]:
    decision = payload.get("decision_id")
    return (
        str(decision.get("recorder_id", "")) if isinstance(decision, Mapping) else "",
        str(payload.get("outcome_semantic", "")),
        str(payload.get("outcome_semantic_version", "")),
        sha256_hex(canonical_json_bytes(payload.get("target_time"))),
        str(payload.get("transform_version", "")),
    )


class StrategyScienceRecorder:
    """Explicit-input offline recorder backed by immutable physical storage."""

    def __init__(
        self,
        science_root: Path,
        *,
        source_root_identity: str,
        writer_instance_id: str,
        clock: Callable[[], str],
    ) -> None:
        self.science_root = Path(science_root)
        try:
            self.source_root_identity = require_sha256(
                source_root_identity, "source_root_identity"
            )
        except CanonicalizationError as exc:
            raise RecorderCustodyError(str(exc)) from exc
        if not isinstance(writer_instance_id, str) or not writer_instance_id:
            raise RecorderCustodyError("writer_instance_id must be a nonempty string.")
        if not callable(clock):
            raise RecorderCustodyError("An explicit recorder clock is required.")
        self._clock = clock
        topology_fingerprint = sha256_hex(
            canonical_json_bytes(
                {
                    "base_canonical": BASE_CANONICAL_SHA,
                    "predecessor_schema_sha256": PREDECESSOR_SCHEMA_SHA256,
                    "profile": TOPOLOGY_PROFILE,
                    "source_root_identity": self.source_root_identity,
                    "topology_version": TOPOLOGY_VERSION,
                }
            )
        )
        self._storage = WriterPhysicalStorage(
            self.science_root,
            writer_instance_id=writer_instance_id,
            topology_fingerprint=topology_fingerprint,
            topology_version=TOPOLOGY_VERSION,
        )
        self._closed = False

    @property
    def owner_evidence(self) -> object:
        return {
            "continuous_runtime_mutated": False,
            "continuous_runtime_owner": False,
            "historical_physical_primitive_label": "continuous-evidence-writer-owner-v1",
            "historical_label_is_runtime_ownership": False,
            "physical_primitive_evidence": asdict(self._storage.owner_evidence),
            "profile": "SCIENCE_CUSTODY_OWNER_PROFILE_V1",
        }

    def __enter__(self) -> "StrategyScienceRecorder":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._storage.close()
        self._closed = True

    def _capture_time(self) -> str:
        value = self._clock()
        try:
            parse_rfc3339(value, "clock()")
        except CanonicalizationError as exc:
            raise RecorderCustodyError(str(exc)) from exc
        return value

    def _capture_time_for_source(
        self,
        partition: PurePath,
        source_envelope_sha256: str,
    ) -> str:
        """Reuse a staged payload's exact custody clock across partial replay."""

        observed: set[str] = set()
        for channel in ("session", "discovery", "decision", "market", "health", "outcome"):
            for path in self._files(partition / "payloads" / channel, ".payload.json"):
                value, _raw = self._read_canonical(path, "staged payload")
                if value.get("source_envelope_sha256") != source_envelope_sha256:
                    continue
                capture = require_time_evidence(
                    value.get("recorder_capture_time"),
                    "recorder_capture_time",
                    role="RECORDER_CAPTURE_TIME",
                )
                if capture["state"] != "PRESENT":
                    raise RecorderRecoveryError("Staged payload lacks a PRESENT capture clock.")
                observed.add(str(capture["normalized_rfc3339"]))
        if len(observed) > 1:
            raise RecorderRecoveryError("One source tail has inconsistent staged capture clocks.")
        return next(iter(observed)) if observed else self._capture_time()

    def _quarantine_partials_with_receipts(self) -> None:
        """Wrap the shared physical quarantine with immutable Science evidence."""

        before = [
            {
                "byte_length": path.stat().st_size,
                "partial_name": path.name,
                "sha256": sha256_hex(path.read_bytes()),
            }
            for path in self._files(PurePath(".partial"), ".tmp")
        ]
        try:
            self._storage.quarantine_partials()
        except WriterPhysicalStorageError as exc:
            raise RecorderRecoveryError(str(exc)) from exc
        if not before:
            return
        after = [
            {
                "byte_length": path.stat().st_size,
                "quarantine_name": path.name,
                "sha256": sha256_hex(path.read_bytes()),
            }
            for path in self._files(PurePath(".quarantine"), ".tmp")
        ]
        for item in before:
            key = sha256_hex(canonical_json_bytes(item))
            receipt_path = PurePath("quarantine-receipts", f"{key}.quarantine.json")
            if self._files(PurePath("quarantine-receipts"), f"{key}.quarantine.json"):
                continue
            matches = [
                candidate
                for candidate in after
                if candidate["sha256"] == item["sha256"]
                and candidate["byte_length"] == item["byte_length"]
            ]
            record: dict[str, object] = {
                "authority": AUTHORITY,
                "execution_authority": EXECUTION_AUTHORITY,
                "observed_at": self._capture_time(),
                "partial_before": item,
                "profile": "SCIENCE_PARTIAL_QUARANTINE_RECEIPT_V1",
                "shared_quarantine_primitive": "WriterPhysicalStorage.quarantine_partials",
            }
            if len(matches) == 1:
                record["post_quarantine_match"] = matches[0]
                record["post_quarantine_match_state"] = "EXACT_BYTES_SURVIVED"
            else:
                record["post_quarantine_match_state"] = "TARGET_METADATA_NOT_PROVEN"
                record["surviving_exact_byte_match_count"] = len(matches)
            self._storage.atomic_create(receipt_path, canonical_json_bytes(record))

    def _files(self, relative: PurePath, suffix: str) -> tuple[Path, ...]:
        try:
            return self._storage.iter_files(relative, suffix=suffix)
        except WriterPhysicalStorageError as exc:
            raise RecorderRecoveryError(str(exc)) from exc

    def _read_canonical(self, path: Path, label: str) -> tuple[Mapping[str, object], bytes]:
        try:
            stat = path.stat(follow_symlinks=False)
            if path.is_symlink() or stat.st_nlink != 1:
                raise RecorderRecoveryError(
                    f"Persisted {label} is a reparse/link alias rather than one custody file."
                )
            raw = path.read_bytes()
            return strict_json_loads(raw), raw
        except (OSError, CanonicalizationError) as exc:
            raise RecorderRecoveryError(f"Invalid persisted {label}: {path.name}.") from exc

    def _relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self._storage.root.resolve()).as_posix()
        except (OSError, ValueError) as exc:
            raise RecorderRecoveryError("Evidence path escaped the configured Science root.") from exc

    def _partition_for_start(self, envelope: ValidatedExportEnvelope) -> PurePath:
        payload = envelope.payload
        validate_start_manifest(
            payload,
            session_id=envelope.session_id,
            source_root_identity=self.source_root_identity,
        )
        date_value = str(payload["exchange_market_date"])
        session_key = "s-" + sha256_hex(
            str(envelope.session_id["recorder_id"]).encode("utf-8")
        )
        return PurePath("sessions", date_value, session_key)

    def _start_records(self) -> tuple[tuple[PurePath, Mapping[str, object]], ...]:
        results: list[tuple[PurePath, Mapping[str, object]]] = []
        for path in self._files(PurePath("sessions"), ".payload.json"):
            value, _raw = self._read_canonical(path, "payload")
            if value.get("record_type") != "session-manifest" or value.get("manifest_phase") != "START":
                continue
            relative = PurePath(self._relative(path))
            if len(relative.parts) < 6:
                raise RecorderRecoveryError("Session-start payload has an invalid partition path.")
            results.append((PurePath(*relative.parts[:3]), value))
        return tuple(results)

    def _locate_partition(self, session_id: Mapping[str, object]) -> PurePath:
        matches = [
            partition
            for partition, record in self._start_records()
            if record.get("session_id") == session_id
        ]
        if len(matches) != 1:
            raise RecorderCustodyError(
                "Exactly one verified START manifest must exist before non-session evidence."
            )
        return matches[0]

    def _start_record(self, partition: PurePath) -> Mapping[str, object]:
        matches: list[Mapping[str, object]] = []
        for path in self._files(partition / "payloads" / "session", ".payload.json"):
            value, _raw = self._read_canonical(path, "session payload")
            if value.get("record_type") == "session-manifest" and value.get("manifest_phase") == "START":
                matches.append(value)
        if len(matches) != 1:
            raise RecorderRecoveryError("Partition does not contain exactly one START manifest.")
        return matches[0]

    def _source_final_records(self, partition: PurePath) -> tuple[Mapping[str, object], ...]:
        matches: list[Mapping[str, object]] = []
        for path in self._files(partition / "payloads" / "session", ".payload.json"):
            value, _raw = self._read_canonical(path, "session payload")
            if value.get("record_type") == "session-manifest" and value.get("manifest_phase") == "FINAL":
                matches.append(value)
        return tuple(matches)

    def _frozen_finalization_cutoff(self, partition: PurePath) -> tuple[str, datetime]:
        start = self._start_record(partition)
        policy = start.get("outcome_followup_policy")
        retry = (
            policy.get("retry_and_finalization_cutoff")
            if isinstance(policy, Mapping)
            else None
        )
        cutoff = retry.get("finalization_cutoff") if isinstance(retry, Mapping) else None
        if not isinstance(cutoff, str):
            raise RecorderRecoveryError(
                "START manifest lacks its frozen outcome finalization cutoff."
            )
        return cutoff, parse_rfc3339(cutoff, "finalization_cutoff")

    def _source_stream_summary(
        self, partition: PurePath
    ) -> tuple[list[dict[str, object]], dict[str, int]]:
        stream_ids: set[str] = set()
        for path in self._files(partition / "sources" / "export", ".source.json"):
            parsed = parse_export_envelope(path.read_bytes())
            stream_ids.add(parsed.stream_id)
        heads: list[dict[str, object]] = []
        counts = {event_type: 0 for event_type in EVENT_CHANNEL}
        for stream_id in sorted(stream_ids):
            state = self._stream_state(partition, "export", stream_id)
            if not state.checkpoints:
                continue
            source_dir, _checkpoint_dir = self._stream_paths(
                partition, "export", stream_id
            )
            for checkpoint in state.checkpoints:
                source_path = source_dir / (
                    f"{_source_event_key(str(checkpoint['source_event_id']))}.source.json"
                )
                parsed = parse_export_envelope(
                    (self._storage.root / Path(source_path)).read_bytes()
                )
                counts[parsed.event_type] += 1
            heads.append(
                {
                    "last_source_envelope_sha256": state.last_source_sha256,
                    "last_source_sequence": state.last_sequence,
                    "stream_id": stream_id,
                }
            )
        return heads, counts

    def _validate_source_final(
        self,
        partition: PurePath,
        envelope: ValidatedExportEnvelope,
    ) -> None:
        payload = envelope.payload
        expected_fields = {
            "close_reason",
            "closed_at",
            "conflict_count",
            "manifest_phase",
            "pending_source_events",
            "session_id",
            "source_event_type_counts_before_final",
            "source_gap_count",
            "source_root_identity",
            "source_stream_heads_before_final",
        }
        if set(payload) != expected_fields or payload.get("manifest_phase") != "FINAL":
            raise RecorderContractError("Source FINAL manifest shape is not the offline profile.")
        if payload.get("session_id") != envelope.session_id:
            raise RecorderContractError("Source FINAL session identity differs from envelope.")
        if payload.get("source_root_identity") != self.source_root_identity:
            raise RecorderContractError("Source FINAL root identity differs from configured source.")
        _text(payload, "close_reason")
        parse_rfc3339(payload.get("closed_at"), "closed_at")
        pending = require_integer(payload.get("pending_source_events"), "pending_source_events")
        gaps = require_integer(payload.get("source_gap_count"), "source_gap_count")
        conflicts = len(self._files(partition / "conflicts", ".conflict.json"))
        if payload.get("conflict_count") != conflicts:
            raise RecorderContractError("Source FINAL conflict count does not reconcile.")
        records = self._all_records(partition)
        terminal_gap_evidence = [
            record
            for record in records
            if record.get("record_type") == "provider-health-event"
            and record.get("event_class") in {"SOURCE_OUTAGE", "SOURCE_RETENTION_GAP"}
            and record.get("terminal") is True
        ]
        if gaps != len(terminal_gap_evidence):
            raise RecorderContractError(
                "Declared source gaps must reconcile to immutable terminal source-gap health evidence."
            )
        if pending and not payload.get("close_reason"):
            raise RecorderContractError("Pending source evidence requires an explicit close reason.")
        for source_kind in ("export", "outcome"):
            paths = self._files(
                partition / "sources" / source_kind, ".source.json"
            )
            stream_ids: set[str] = set()
            for path in paths:
                parsed = (
                    parse_export_envelope(path.read_bytes())
                    if source_kind == "export"
                    else parse_outcome_attachment(path.read_bytes())
                )
                stream_ids.add(parsed.stream_id)
            committed = sum(
                self._stream_state(partition, source_kind, stream_id).last_sequence
                for stream_id in stream_ids
            )
            current_final_source_present = (
                source_kind == "export"
                and any(sha256_hex(path.read_bytes()) == envelope.raw_sha256 for path in paths)
            )
            allowed_uncheckpointed = 1 if current_final_source_present else 0
            if len(paths) - committed != allowed_uncheckpointed:
                raise RecorderContractError(
                    "Source FINAL cannot cross an uncheckpointed source tail."
                )
        heads, counts = self._source_stream_summary(partition)
        if payload.get("source_stream_heads_before_final") != heads:
            raise RecorderContractError("Source FINAL stream heads do not reconcile exact raw chains.")
        if payload.get("source_event_type_counts_before_final") != counts:
            raise RecorderContractError("Source FINAL event counts do not reconcile.")

    def _final_files(self, partition: PurePath) -> tuple[Path, ...]:
        return self._files(partition / "manifests", ".final.json")

    def _ensure_open_partition(self, partition: PurePath) -> None:
        if self._final_files(partition):
            raise RecorderCustodyError("Finalized session is immutable and accepts no new records.")

    def _channel_state(self, partition: PurePath, channel: str) -> _ChannelState:
        payloads: dict[str, tuple[Path, Mapping[str, object], bytes]] = {}
        receipts: dict[str, tuple[Path, Mapping[str, object], bytes]] = {}
        for path in self._files(partition / "payloads" / channel, ".payload.json"):
            value, raw = self._read_canonical(path, f"{channel} payload")
            key = path.name.removesuffix(".payload.json")
            record_id = value.get("record_id")
            if not isinstance(record_id, Mapping) or _record_key(str(record_id.get("recorder_id", ""))) != key:
                raise RecorderRecoveryError("Payload filename does not bind its logical record ID.")
            if value.get("channel") != channel:
                raise RecorderRecoveryError("Payload was stored in the wrong channel.")
            if key in payloads:
                raise RecorderRecoveryError("Duplicate logical payload key detected.")
            payloads[key] = (path, value, raw)
        for path in self._files(partition / "receipts" / channel, ".receipt.json"):
            value, raw = self._read_canonical(path, f"{channel} receipt")
            key = path.name.removesuffix(".receipt.json")
            if value.get("record_key_sha256") != key or key in receipts:
                raise RecorderRecoveryError("Receipt filename/key binding is invalid.")
            receipts[key] = (path, value, raw)
        if set(receipts).difference(payloads):
            raise RecorderRecoveryError("BROKEN_COMMIT: receipt exists without payload.")
        ordered: list[tuple[int, str, Mapping[str, object], bytes]] = []
        for key, (_path, receipt, raw) in receipts.items():
            payload = payloads[key][1]
            payload_raw = payloads[key][2]
            if receipt.get("receipt_version") != RECEIPT_VERSION:
                raise RecorderRecoveryError("Unsupported receipt version.")
            sequence = receipt.get("record_sequence")
            if isinstance(sequence, bool) or not isinstance(sequence, int):
                raise RecorderRecoveryError("Receipt sequence is invalid.")
            if payload.get("record_sequence") != sequence:
                raise RecorderRecoveryError("Payload/receipt sequences differ.")
            if receipt.get("payload_sha256") != sha256_hex(payload_raw):
                raise RecorderRecoveryError("Receipt payload hash does not verify.")
            if receipt.get("record_id") != payload.get("record_id"):
                raise RecorderRecoveryError("Receipt logical ID does not match payload.")
            ordered.append((sequence, key, receipt, raw))
        ordered.sort(key=lambda item: item[0])
        previous = GENESIS_SHA256
        for expected_sequence, (sequence, _key, receipt, raw) in enumerate(ordered, 1):
            if sequence != expected_sequence:
                raise RecorderRecoveryError("Receipt chain sequence is not contiguous from one.")
            previous_evidence = receipt.get("previous_receipt_sha256")
            if expected_sequence == 1:
                if not isinstance(previous_evidence, Mapping) or previous_evidence.get("state") != "NOT_APPLICABLE":
                    raise RecorderRecoveryError("Genesis receipt predecessor is invalid.")
            else:
                if not isinstance(previous_evidence, Mapping) or previous_evidence.get("value") != previous:
                    raise RecorderRecoveryError("Receipt predecessor chain is broken.")
            previous = sha256_hex(raw)
        orphan_keys = tuple(sorted(set(payloads).difference(receipts)))
        for key in orphan_keys:
            sequence = payloads[key][1].get("record_sequence")
            if sequence != len(ordered) + 1:
                raise RecorderRecoveryError("Uncommitted payload is not the unique chain tail.")
        if len(orphan_keys) > 1:
            raise RecorderRecoveryError("More than one uncommitted payload tail exists.")
        return _ChannelState(
            channel=channel,
            payloads=payloads,
            receipts=receipts,
            orphan_payload_keys=orphan_keys,
            last_sequence=len(ordered),
            last_receipt_sha256=previous,
        )

    def _stream_paths(
        self, partition: PurePath, source_kind: str, stream_id: str
    ) -> tuple[PurePath, PurePath]:
        key = _stream_key(source_kind, stream_id)
        return (
            partition / "sources" / source_kind / key,
            partition / "checkpoints" / source_kind / key,
        )

    def _stream_is_frozen(self, partition: PurePath, source_kind: str, stream_id: str) -> bool:
        for path in self._files(partition / "conflicts", ".conflict.json"):
            value, _raw = self._read_canonical(path, "conflict")
            if value.get("source_kind") == source_kind and value.get("stream_id") == stream_id:
                return True
        return False

    def _stream_state(
        self, partition: PurePath, source_kind: str, stream_id: str
    ) -> _StreamState:
        source_dir, checkpoint_dir = self._stream_paths(partition, source_kind, stream_id)
        sources: dict[str, tuple[Path, bytes]] = {}
        for path in self._files(source_dir, ".source.json"):
            raw = path.read_bytes()
            key = path.name.removesuffix(".source.json")
            if key in sources:
                raise RecorderRecoveryError("Duplicate source-event key detected.")
            sources[key] = (path, raw)
        checkpoints: list[tuple[int, Mapping[str, object], bytes]] = []
        for path in self._files(checkpoint_dir, ".checkpoint.json"):
            value, raw = self._read_canonical(path, "checkpoint")
            supplied_hash = value.get("checkpoint_payload_sha256")
            material = dict(value)
            material.pop("checkpoint_payload_sha256", None)
            if supplied_hash != sha256_hex(canonical_json_bytes(material)):
                raise RecorderRecoveryError("Checkpoint self-hash does not verify.")
            if value.get("cursor_version") != CURSOR_VERSION:
                raise RecorderRecoveryError("Unsupported cursor version.")
            if value.get("source_kind") != source_kind or value.get("stream_id") != stream_id:
                raise RecorderRecoveryError("Checkpoint stream binding differs from its path.")
            sequence = value.get("source_sequence")
            if isinstance(sequence, bool) or not isinstance(sequence, int):
                raise RecorderRecoveryError("Checkpoint sequence is invalid.")
            checkpoints.append((sequence, value, raw))
        checkpoints.sort(key=lambda item: item[0])
        previous_source = GENESIS_SHA256
        previous_checkpoint = GENESIS_SHA256
        normalized: list[Mapping[str, object]] = []
        for expected, (sequence, checkpoint, checkpoint_raw) in enumerate(checkpoints, 1):
            if sequence != expected or checkpoint.get("checkpoint_sequence") != expected:
                raise RecorderRecoveryError("Source checkpoints are not contiguous from one.")
            if checkpoint.get("previous_source_envelope_sha256") != previous_source:
                raise RecorderRecoveryError("Checkpoint prior-source hash chain is broken.")
            if checkpoint.get("previous_checkpoint_sha256") != previous_checkpoint:
                raise RecorderRecoveryError("Checkpoint predecessor hash chain is broken.")
            event_id = str(checkpoint.get("source_event_id", ""))
            source_key = _source_event_key(event_id)
            source = sources.get(source_key)
            if source is None or sha256_hex(source[1]) != checkpoint.get("source_envelope_sha256"):
                raise RecorderRecoveryError("Checkpoint does not resolve exact source bytes.")
            if source_kind == "export":
                parsed = parse_export_envelope(source[1])
            elif source_kind == "outcome":
                parsed = parse_outcome_attachment(source[1])
            else:
                raise RecorderRecoveryError("Unknown persisted source kind.")
            if parsed.source_event_id != event_id or parsed.source_sequence != sequence:
                raise RecorderRecoveryError("Checkpoint/source identity or sequence differs.")
            if parsed.previous_record_sha256 != previous_source:
                raise RecorderRecoveryError("Source envelope prior hash is not exact prior raw bytes.")
            record_ids = checkpoint.get("accepted_record_ids")
            record_hashes = checkpoint.get("accepted_payload_sha256s")
            receipt_hashes = checkpoint.get("accepted_receipt_sha256s")
            if not isinstance(record_ids, list) or not isinstance(record_hashes, list) or not isinstance(receipt_hashes, list):
                raise RecorderRecoveryError("Checkpoint accepted-record inventory is malformed.")
            if not (len(record_ids) == len(record_hashes) == len(receipt_hashes)) or not record_ids:
                raise RecorderRecoveryError("Checkpoint accepted-record inventory is incomplete.")
            if (
                checkpoint.get("last_accepted_record_id") != record_ids[-1]
                or checkpoint.get("last_accepted_payload_sha256") != record_hashes[-1]
                or checkpoint.get("last_accepted_receipt_sha256") != receipt_hashes[-1]
            ):
                raise RecorderRecoveryError("Checkpoint last-accepted tuple is inconsistent.")
            channel = str(checkpoint.get("channel", ""))
            state = self._channel_state(partition, channel)
            for record_id, payload_hash, receipt_hash in zip(record_ids, record_hashes, receipt_hashes):
                key = _record_key(str(record_id))
                if key not in state.payloads or key not in state.receipts:
                    raise RecorderRecoveryError("Checkpoint references a missing payload/receipt.")
                if sha256_hex(state.payloads[key][2]) != payload_hash or sha256_hex(state.receipts[key][2]) != receipt_hash:
                    raise RecorderRecoveryError("Checkpoint record hashes do not verify.")
            last_key = _record_key(str(record_ids[-1]))
            if (
                state.receipts[last_key][1].get("record_sequence")
                != checkpoint.get("last_accepted_record_sequence")
            ):
                raise RecorderRecoveryError(
                    "Checkpoint last accepted record sequence does not verify."
                )
            previous_source = str(checkpoint["source_envelope_sha256"])
            previous_checkpoint = sha256_hex(checkpoint_raw)
            normalized.append(checkpoint)
        return _StreamState(
            source_kind=source_kind,
            stream_id=stream_id,
            checkpoints=tuple(normalized),
            last_sequence=len(normalized),
            last_source_sha256=previous_source,
            last_checkpoint_sha256=previous_checkpoint,
        )

    def _existing_source_result(
        self,
        partition: PurePath,
        *,
        source_kind: str,
        stream_id: str,
        source_event_id: str,
        source_sequence: int,
        raw_sha256: str,
        raw_bytes: bytes,
    ) -> AcceptanceResult | None:
        if self._stream_is_frozen(partition, source_kind, stream_id):
            raise RecorderConflictError(
                "Affected source stream is frozen by persistent conflict evidence."
            )
        state = self._stream_state(partition, source_kind, stream_id)
        for checkpoint in state.checkpoints:
            if checkpoint.get("source_event_id") != source_event_id:
                continue
            if checkpoint.get("source_envelope_sha256") != raw_sha256:
                self._persist_conflict(
                    partition,
                    source_kind=source_kind,
                    stream_id=stream_id,
                    source_event_id=source_event_id,
                    conflicting_raw=raw_bytes,
                    reason_code="SOURCE_EVENT_ID_REUSED_WITH_DIFFERENT_BYTES",
                    accepted_sha256=str(checkpoint["source_envelope_sha256"]),
                )
                raise RecorderConflictError("Source event identity conflicts with accepted bytes.")
            return AcceptanceResult(
                status="IDEMPOTENT_ACK",
                source_kind=source_kind,
                source_event_id=source_event_id,
                source_sequence=source_sequence,
                record_ids=tuple(str(item) for item in checkpoint["accepted_record_ids"]),
                checkpoint_sha256=str(checkpoint["checkpoint_payload_sha256"]),
            )
        return None

    def _record_index(
        self, partition: PurePath
    ) -> dict[str, tuple[Mapping[str, object], bytes]]:
        records: dict[str, tuple[Mapping[str, object], bytes]] = {}
        for channel in ("session", "discovery", "decision", "market", "health", "outcome"):
            state = self._channel_state(partition, channel)
            for key in state.receipts:
                _path, payload, raw = state.payloads[key]
                identity = payload.get("record_id")
                recorder_id = str(identity.get("recorder_id", "")) if isinstance(identity, Mapping) else ""
                if not recorder_id or recorder_id in records:
                    raise RecorderRecoveryError("Accepted record identity index is ambiguous.")
                records[recorder_id] = (payload, raw)
        return records

    def _persist_conflict(
        self,
        partition: PurePath,
        *,
        source_kind: str,
        stream_id: str,
        source_event_id: str,
        conflicting_raw: bytes,
        reason_code: str,
        accepted_sha256: str,
        logical_record_id: str = "NOT_APPLICABLE",
    ) -> None:
        conflict_key = sha256_hex(
            canonical_json_bytes(
                {
                    "accepted_sha256": accepted_sha256,
                    "conflicting_sha256": sha256_hex(conflicting_raw),
                    "logical_record_id": logical_record_id,
                    "reason_code": reason_code,
                    "source_event_id": source_event_id,
                    "stream_id": stream_id,
                }
            )
        )
        raw_path = partition / "conflicts" / f"{conflict_key}.conflicting.raw"
        record_path = partition / "conflicts" / f"{conflict_key}.conflict.json"
        existing = self._files(partition / "conflicts", f"{conflict_key}.conflict.json")
        if existing:
            return
        self._storage.atomic_create(raw_path, conflicting_raw)
        record = {
            "accepted_payload_sha256": accepted_sha256,
            "authority": AUTHORITY,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "conflicting_bytes_relative_path": raw_path.as_posix(),
            "conflicting_payload_sha256": sha256_hex(conflicting_raw),
            "execution_authority": EXECUTION_AUTHORITY,
            "logical_record_id": logical_record_id,
            "observed_at": self._capture_time(),
            "reason_code": reason_code,
            "recorder_decision": "FAIL_CLOSED",
            "schema_version": SCHEMA_VERSION,
            "source_event_id": source_event_id,
            "source_kind": source_kind,
            "stream_id": stream_id,
        }
        self._storage.atomic_create(record_path, canonical_json_bytes(record))

    def _base_record(
        self,
        *,
        partition: PurePath,
        record_type: str,
        record_id: Mapping[str, object],
        session_id: Mapping[str, object],
        source_owner: str,
        source_contract: str,
        source_contract_version: str,
        source_interface_identity: str,
        source_event_id: str,
        source_fingerprint_sha256: str,
        source_payload_sha256: str,
        source_envelope_sha256: str,
        capture_time: str,
        core: Mapping[str, object],
    ) -> dict[str, object]:
        reserved = {
            "schema_version",
            "record_type",
            "record_id",
            "session_id",
            "partition_id",
            "record_sequence",
            "channel",
            "source_owner",
            "source_contract",
            "source_contract_version",
            "source_interface_identity",
            "source_record_identity",
            "source_fingerprint_sha256",
            "source_payload_sha256",
            "source_envelope_sha256",
            "recorder_capture_time",
            "authority",
            "execution_authority",
        }
        if reserved.intersection(core):
            raise RecorderContractError("Owner payload attempts to replace recorder custody fields.")
        channel = "session" if record_type == "session-manifest" else {
            family: channel_name
            for family, channel_name in (
                ("discovery-cycle", "discovery"),
                ("candidate-observation", "discovery"),
                ("science-eligibility", "discovery"),
                ("decision-event", "decision"),
                ("reference-plan", "decision"),
                ("market-snapshot", "market"),
                ("provider-health-event", "health"),
                ("outcome-observation", "outcome"),
            )
        }[record_type]
        result = dict(core)
        result.update(
            {
                "authority": AUTHORITY,
                "channel": channel,
                "execution_authority": EXECUTION_AUTHORITY,
                "partition_id": partition.as_posix(),
                "record_id": dict(record_id),
                "record_type": record_type,
                "recorder_capture_time": _capture_time_evidence(capture_time),
                "schema_version": SCHEMA_VERSION,
                "session_id": dict(session_id),
                "source_envelope_sha256": source_envelope_sha256,
                "source_fingerprint_sha256": source_fingerprint_sha256,
                "source_owner": source_owner,
                "source_contract": source_contract,
                "source_contract_version": source_contract_version,
                "source_interface_identity": source_interface_identity,
                "source_payload_sha256": source_payload_sha256,
                "source_record_identity": _present_value(
                    source_event_id, authority=source_owner
                ),
            }
        )
        return result

    def _validate_instrument(self, value: object, label: str) -> Mapping[str, object]:
        return require_instrument_identity(value, label)

    def _validate_discovery(
        self, payload: Mapping[str, object]
    ) -> tuple[Mapping[str, object], tuple[Mapping[str, object], ...]]:
        if set(payload) != {"discovery_cycle", "observations"}:
            raise RecorderContractError("DISCOVERY_CYCLE payload shape is not the offline profile.")
        cycle = payload["discovery_cycle"]
        observations = payload["observations"]
        if not isinstance(cycle, Mapping) or not isinstance(observations, list):
            raise RecorderContractError("Discovery cycle and observations must be structured objects.")
        required_cycle = (
            "discovery_cycle_id",
            "cycle_state",
            "query_or_policy_fingerprint_sha256",
            "discovery_time",
            "provider_received_at",
            "returned_row_count",
            "row_order_complete",
            "observation_ids_in_source_order",
            "provider_health_event_ids",
            "zero_result",
            "completeness",
        )
        for field in required_cycle:
            if field not in cycle:
                raise RecorderContractError(f"Discovery cycle missing {field}.")
        cycle_id = require_identity(
            cycle["discovery_cycle_id"],
            "discovery_cycle_id",
            kinds=frozenset({"DISCOVERY_CYCLE_ID"}),
        )
        if cycle["cycle_state"] not in {"COMPLETE", "ZERO_RESULT", "PARTIAL", "FAILED"}:
            raise RecorderContractError("Discovery cycle state is unsupported.")
        require_sha256(cycle["query_or_policy_fingerprint_sha256"], "query_or_policy_fingerprint_sha256")
        require_time_evidence(cycle["discovery_time"], "discovery_time", role="DISCOVERY_TIME")
        require_time_evidence(
            cycle["provider_received_at"],
            "provider_received_at",
            role="PROVIDER_RECEIVED_AT",
        )
        count = _positive_or_zero_integer(cycle["returned_row_count"], "returned_row_count")
        require_evidence_value(cycle["row_order_complete"], "row_order_complete")
        require_evidence_value(cycle["completeness"], "completeness")
        if not isinstance(cycle["provider_health_event_ids"], list):
            raise RecorderContractError("provider_health_event_ids must be an array.")
        for index, identity in enumerate(cycle["provider_health_event_ids"]):
            require_identity(
                identity,
                f"provider_health_event_ids[{index}]",
                kinds=frozenset({"PROVIDER_HEALTH_EVENT_ID"}),
            )
        if count != len(observations):
            raise RecorderContractError("Returned-row count does not match exact row inventory.")
        if cycle["cycle_state"] == "ZERO_RESULT":
            if count != 0 or cycle["zero_result"] is not True:
                raise RecorderContractError("ZERO_RESULT cycle invariants are false.")
        elif cycle["zero_result"] is not False:
            raise RecorderContractError("Only ZERO_RESULT may set zero_result true.")
        normalized: list[Mapping[str, object]] = []
        ordered_ids: list[Mapping[str, object]] = []
        for index, item in enumerate(observations):
            if not isinstance(item, Mapping):
                raise RecorderContractError("Every observation must be an object.")
            if "outcome_eligibility" in item:
                raise RecorderContractError("Source cannot inject recorder-owned outcome eligibility.")
            required_observation = (
                "observation_id",
                "discovery_cycle_id",
                "source_row_ordinal",
                "source_row_fingerprint_sha256",
                "instrument_identity",
                "candidate_or_setup_identity",
                "rank",
                "discovery_time",
                "candidate_facts",
                "materially_evaluated",
                "rejection_or_gap_reasons",
            )
            for field in required_observation:
                if field not in item:
                    raise RecorderContractError(f"Candidate observation missing {field}.")
            observation_id = require_identity(
                item["observation_id"],
                "observation_id",
                kinds=frozenset({"OBSERVATION_ID"}),
            )
            if item["discovery_cycle_id"] != cycle_id:
                raise RecorderContractError("Observation links a different discovery cycle.")
            if item["source_row_ordinal"] != index:
                raise RecorderContractError("Source row ordinal must preserve exact array order.")
            require_sha256(item["source_row_fingerprint_sha256"], "source_row_fingerprint_sha256")
            self._validate_instrument(item["instrument_identity"], "instrument_identity")
            require_identity(
                item["candidate_or_setup_identity"],
                "candidate_or_setup_identity",
                kinds=frozenset({"CANDIDATE_MEMBER", "SETUP"}),
            )
            require_evidence_value(item["rank"], "rank")
            require_time_evidence(item["discovery_time"], "discovery_time", role="DISCOVERY_TIME")
            if not isinstance(item["candidate_facts"], Mapping):
                raise RecorderContractError("candidate_facts must be an evidence-value mapping.")
            for field, fact in item["candidate_facts"].items():
                require_evidence_value(fact, f"candidate_facts.{field}")
            if not isinstance(item["materially_evaluated"], bool) or not isinstance(
                item["rejection_or_gap_reasons"], list
            ):
                raise RecorderContractError("Observation evaluation fields are malformed.")
            ordered_ids.append(observation_id)
            normalized.append(item)
        if cycle["observation_ids_in_source_order"] != ordered_ids:
            raise RecorderContractError("Cycle observation ID inventory does not match exact row order.")
        return cycle, tuple(normalized)

    def _eligibility_commitment(
        self,
        partition: PurePath,
        observation: Mapping[str, object],
        capture_time: str,
    ) -> Mapping[str, object]:
        start = self._start_record(partition)
        policy = start["outcome_followup_policy"]
        instrument = observation["instrument_identity"]
        fingerprint = str(instrument["instrument_identity_fingerprint_sha256"])
        for record, _raw in self._record_index(partition).values():
            if record.get("record_type") != "candidate-observation":
                continue
            existing_instrument = record.get("instrument_identity")
            if (
                isinstance(existing_instrument, Mapping)
                and existing_instrument.get("instrument_identity_fingerprint_sha256") == fingerprint
            ):
                commitment = record.get("outcome_eligibility")
                if not isinstance(commitment, Mapping):
                    raise RecorderRecoveryError("Existing eligibility commitment is malformed.")
                return commitment
        material: dict[str, object] = {
            "committed_at": _capture_time_evidence(capture_time),
            "commitment_provenance": "SCIENCE_CUSTODY_OFFLINE_SOURCE_CHAIN_ASSERTION",
            "eligibility_basis_time": observation["discovery_time"],
            "eligibility_state": "ELIGIBLE",
            "first_observation_id": observation["observation_id"],
            "instrument_identity_fingerprint_sha256": fingerprint,
            "policy_id": policy["policy_id"],
            "policy_sha256": policy["policy_sha256"],
            "policy_version": policy["policy_version"],
        }
        material["commitment_payload_sha256"] = sha256_hex(canonical_json_bytes(material))
        return material

    def _existing_eligibility_by_instrument(
        self, partition: PurePath
    ) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        for record, _raw in self._record_index(partition).values():
            if record.get("record_type") != "candidate-observation":
                continue
            instrument = record.get("instrument_identity")
            commitment = record.get("outcome_eligibility")
            if isinstance(instrument, Mapping) and isinstance(commitment, Mapping):
                fingerprint = instrument.get("instrument_identity_fingerprint_sha256")
                if isinstance(fingerprint, str):
                    previous = result.get(fingerprint)
                    if previous is not None and previous != commitment:
                        raise RecorderRecoveryError(
                            "One instrument has conflicting eligibility commitments."
                        )
                    result[fingerprint] = commitment
        return result

    def _science_eligibility_record(
        self,
        partition: PurePath,
        observation: Mapping[str, object],
        *,
        observation_payload_sha256: str,
        observation_receipt_sha256: str,
    ) -> dict[str, object]:
        start = self._start_record(partition)
        policy = start["outcome_followup_policy"]
        instrument = observation["instrument_identity"]
        fingerprint = str(instrument["instrument_identity_fingerprint_sha256"])
        producer_known_at = _text(observation, "producer_effective_known_at")
        evaluated_at = observation["recorder_capture_time"]
        if evidence_instant(evaluated_at, "science_evaluated_at") < parse_rfc3339(
            producer_known_at, "producer_effective_known_at"
        ):
            raise RecorderContractError(
                "Science receipt time cannot precede producer effective-known-at."
            )
        eligibility_id = recorder_identity(
            "SCIENCE_ELIGIBILITY_ID",
            {
                "instrument_identity_fingerprint_sha256": fingerprint,
                "profile": SCIENCE_ELIGIBILITY_PROFILE,
                "session_id": observation["session_id"],
            },
        )
        material: dict[str, object] = {
            "commitment_provenance": "SCIENCE_CUSTODY_RECEIPT_DERIVATION",
            "eligibility_basis_time": observation["discovery_time"],
            "eligibility_state": "ELIGIBLE",
            "first_observation_id": observation["observation_id"],
            "instrument_identity_fingerprint_sha256": fingerprint,
            "policy_id": policy["policy_id"],
            "policy_sha256": policy["policy_sha256"],
            "policy_version": policy["policy_version"],
            "producer_content_sha256": observation["source_envelope_sha256"],
            "producer_effective_known_at": producer_known_at,
            "producer_observation_payload_sha256": observation_payload_sha256,
            "science_custody_receipt_sha256": observation_receipt_sha256,
            "science_eligibility_profile": SCIENCE_ELIGIBILITY_PROFILE,
            "science_eligibility_record_version": SCIENCE_ELIGIBILITY_RECORD_VERSION,
            "science_evaluated_at": evaluated_at,
        }
        material["commitment_payload_sha256"] = science_eligibility_sha256(material)
        capture_time = str(evaluated_at["normalized_rfc3339"])
        return self._base_record(
            partition=partition,
            record_type="science-eligibility",
            record_id=eligibility_id,
            session_id=observation["session_id"],
            source_owner="SCIENCE_RECORDER",
            source_contract="ScienceEligibilityV2",
            source_contract_version=SCIENCE_ELIGIBILITY_RECORD_VERSION,
            source_interface_identity="SCIENCE_CUSTODY_INTERNAL_V2",
            source_event_id=str(eligibility_id["recorder_id"]),
            source_fingerprint_sha256=str(material["commitment_payload_sha256"]),
            source_payload_sha256=observation_payload_sha256,
            source_envelope_sha256=str(observation["source_envelope_sha256"]),
            capture_time=capture_time,
            core={
                "eligibility_id": eligibility_id,
                "instrument_identity_fingerprint_sha256": fingerprint,
                "observation_id": observation["observation_id"],
                "science_eligibility": material,
            },
        )

    def _validate_science_eligibility_record(
        self,
        partition: PurePath,
        record: Mapping[str, object],
    ) -> Mapping[str, object]:
        if record.get("record_type") != "science-eligibility":
            raise RecorderContractError("Science eligibility record type is invalid.")
        eligibility_id = require_identity(
            record.get("eligibility_id"),
            "eligibility_id",
            kinds=frozenset({"SCIENCE_ELIGIBILITY_ID"}),
            allow_recorder_allocated=True,
        )
        if record.get("record_id") != eligibility_id:
            raise RecorderContractError("Science eligibility identity is inconsistent.")
        observation_id = require_identity(
            record.get("observation_id"),
            "eligibility.observation_id",
            kinds=frozenset({"OBSERVATION_ID"}),
        )
        value = record.get("science_eligibility")
        if not isinstance(value, Mapping):
            raise RecorderContractError("Science eligibility material is missing.")
        required = {
            "commitment_payload_sha256",
            "commitment_provenance",
            "eligibility_basis_time",
            "eligibility_state",
            "first_observation_id",
            "instrument_identity_fingerprint_sha256",
            "policy_id",
            "policy_sha256",
            "policy_version",
            "producer_content_sha256",
            "producer_effective_known_at",
            "producer_observation_payload_sha256",
            "science_custody_receipt_sha256",
            "science_eligibility_profile",
            "science_eligibility_record_version",
            "science_evaluated_at",
        }
        if set(value) != required:
            raise RecorderContractError("Science eligibility material shape is invalid.")
        for field in (
            "commitment_payload_sha256",
            "instrument_identity_fingerprint_sha256",
            "policy_sha256",
            "producer_content_sha256",
            "producer_observation_payload_sha256",
            "science_custody_receipt_sha256",
        ):
            require_sha256(value.get(field), f"science_eligibility.{field}")
        if (
            value.get("commitment_provenance")
            != "SCIENCE_CUSTODY_RECEIPT_DERIVATION"
            or value.get("eligibility_state") != "ELIGIBLE"
            or value.get("science_eligibility_profile")
            != SCIENCE_ELIGIBILITY_PROFILE
            or value.get("science_eligibility_record_version")
            != SCIENCE_ELIGIBILITY_RECORD_VERSION
        ):
            raise RecorderContractError("Science eligibility authority profile is invalid.")
        require_time_evidence(
            value.get("science_evaluated_at"),
            "science_evaluated_at",
            role="RECORDER_CAPTURE_TIME",
        )
        producer_known_at = parse_rfc3339(
            value.get("producer_effective_known_at"),
            "producer_effective_known_at",
        )
        if evidence_instant(
            value["science_evaluated_at"], "science_evaluated_at"
        ) < producer_known_at:
            raise RecorderContractError(
                "Science eligibility precedes producer effective-known-at."
            )
        if value.get("commitment_payload_sha256") != science_eligibility_sha256(value):
            raise RecorderContractError("Science eligibility self-hash does not verify.")
        first_observation_id = require_identity(
            value.get("first_observation_id"),
            "first_observation_id",
            kinds=frozenset({"OBSERVATION_ID"}),
        )
        if first_observation_id != observation_id:
            raise RecorderContractError("Science eligibility first-observation link differs.")
        observation_entry = self._record_index(partition).get(
            str(observation_id["recorder_id"])
        )
        if (
            observation_entry is None
            or observation_entry[0].get("record_type") != "candidate-observation"
        ):
            raise RecorderContractError("Science eligibility observation parent is missing.")
        observation, observation_raw = observation_entry
        observation_key = _record_key(str(observation_id["recorder_id"]))
        discovery_state = self._channel_state(partition, "discovery")
        observation_receipt = discovery_state.receipts.get(observation_key)
        if observation_receipt is None:
            raise RecorderContractError("Science eligibility custody receipt is missing.")
        start = self._start_record(partition)
        policy = start["outcome_followup_policy"]
        instrument = observation.get("instrument_identity")
        fingerprint = (
            instrument.get("instrument_identity_fingerprint_sha256")
            if isinstance(instrument, Mapping)
            else None
        )
        expected_eligibility_id = recorder_identity(
            "SCIENCE_ELIGIBILITY_ID",
            {
                "instrument_identity_fingerprint_sha256": fingerprint,
                "profile": SCIENCE_ELIGIBILITY_PROFILE,
                "session_id": observation["session_id"],
            },
        )
        if eligibility_id != expected_eligibility_id:
            raise RecorderContractError("Science eligibility logical identity is invalid.")
        exact_links = {
            "eligibility_basis_time": observation.get("discovery_time"),
            "instrument_identity_fingerprint_sha256": fingerprint,
            "policy_id": policy.get("policy_id"),
            "policy_sha256": policy.get("policy_sha256"),
            "policy_version": policy.get("policy_version"),
            "producer_content_sha256": observation.get("source_envelope_sha256"),
            "producer_effective_known_at": observation.get(
                "producer_effective_known_at"
            ),
            "producer_observation_payload_sha256": sha256_hex(observation_raw),
            "science_custody_receipt_sha256": sha256_hex(observation_receipt[2]),
            "science_evaluated_at": observation.get("recorder_capture_time"),
        }
        for field, expected in exact_links.items():
            if value.get(field) != expected:
                raise RecorderContractError(
                    f"Science eligibility {field} does not bind exact custody authority."
                )
        if (
            record.get("instrument_identity_fingerprint_sha256") != fingerprint
            or record.get("source_owner") != "SCIENCE_RECORDER"
            or record.get("source_contract") != "ScienceEligibilityV2"
            or record.get("source_contract_version")
            != SCIENCE_ELIGIBILITY_RECORD_VERSION
            or record.get("source_interface_identity")
            != "SCIENCE_CUSTODY_INTERNAL_V2"
            or record.get("source_fingerprint_sha256")
            != value.get("commitment_payload_sha256")
            or record.get("source_payload_sha256") != sha256_hex(observation_raw)
            or record.get("source_envelope_sha256")
            != observation.get("source_envelope_sha256")
        ):
            raise RecorderContractError(
                "Science eligibility outer custody binding is invalid."
            )
        return value

    def _science_eligibility_by_instrument(
        self,
        partition: PurePath,
    ) -> dict[str, tuple[Mapping[str, object], Mapping[str, object]]]:
        result: dict[
            str, tuple[Mapping[str, object], Mapping[str, object]]
        ] = {}
        for record, _raw in self._record_index(partition).values():
            if record.get("record_type") != "science-eligibility":
                continue
            material = self._validate_science_eligibility_record(partition, record)
            fingerprint = str(material["instrument_identity_fingerprint_sha256"])
            previous = result.get(fingerprint)
            if previous is not None and previous[1] != material:
                raise RecorderRecoveryError(
                    "One instrument has conflicting Science eligibility records."
                )
            result[fingerprint] = (record, material)
        return result

    def _science_eligibility_for_observation(
        self,
        partition: PurePath,
        observation: Mapping[str, object],
    ) -> tuple[Mapping[str, object], Mapping[str, object]]:
        instrument = observation.get("instrument_identity")
        fingerprint = (
            instrument.get("instrument_identity_fingerprint_sha256")
            if isinstance(instrument, Mapping)
            else None
        )
        if not isinstance(fingerprint, str):
            raise RecorderContractError("Observation instrument identity is malformed.")
        eligibility = self._science_eligibility_by_instrument(partition).get(
            fingerprint
        )
        if eligibility is None:
            raise RecorderContractError(
                "Decision observation lacks one Science receipt-bound eligibility record."
            )
        return eligibility

    def _validate_decision(
        self,
        partition: PurePath,
        payload: Mapping[str, object],
        *,
        export_schema_version: str = SCHEMA_VERSION,
    ) -> tuple[Mapping[str, object], Mapping[str, object] | None]:
        if set(payload).difference({"decision_event", "reference_plan"}) or "decision_event" not in payload:
            raise RecorderContractError("DECISION_FACT payload shape is not the offline profile.")
        decision = payload["decision_event"]
        plan = payload.get("reference_plan")
        if not isinstance(decision, Mapping) or (plan is not None and not isinstance(plan, Mapping)):
            raise RecorderContractError("Decision and optional plan must be objects.")
        required = [
            "decision_id",
            "observation_id",
            "candidate_or_setup_identity",
            "decision_state",
            "reason_codes",
            "decision_time",
            "decision_cutoff",
            "known_at_evidence_refs",
            "strategy_identity",
            "decision_policy_fingerprint_sha256",
            "config_fingerprint_sha256",
            "runtime_fingerprint_sha256",
            "market_snapshot_id",
            "tradeplan_id",
            "reference_plan_id",
        ]
        if export_schema_version == SCHEMA_VERSION:
            required.append("outcome_eligibility_commitment_sha256")
        elif export_schema_version != REPAIRED_EXPORT_SCHEMA_VERSION:
            raise RecorderContractError("Unsupported decision export schema version.")
        elif {
            "outcome_eligibility_commitment_sha256",
            "science_eligibility_commitment_sha256",
            "science_eligibility_id",
            "science_receipt_hash",
        }.intersection(decision):
            raise RecorderContractError(
                "V2 producer Decision contains a future Science-owned fact."
            )
        for field in required:
            if field not in decision:
                raise RecorderContractError(f"Decision event missing {field}.")
        require_identity(decision["decision_id"], "decision_id", kinds=frozenset({"DECISION_ID"}))
        observation_id = require_identity(
            decision["observation_id"], "observation_id", kinds=frozenset({"OBSERVATION_ID"})
        )
        require_identity(
            decision["candidate_or_setup_identity"],
            "candidate_or_setup_identity",
            kinds=frozenset({"CANDIDATE_MEMBER", "SETUP"}),
        )
        if decision["decision_state"] not in {"READY", "BLOCKED", "REJECTED", "MISSED", "NO_PLAN", "TRADEPLAN"}:
            raise RecorderContractError("Decision state is unsupported.")
        if not isinstance(decision["reason_codes"], list) or not decision["reason_codes"]:
            raise RecorderContractError("Every material decision requires reason evidence.")
        decision_time = evidence_instant(decision["decision_time"], "decision_time")
        cutoff = evidence_instant(decision["decision_cutoff"], "decision_cutoff")
        require_time_evidence(decision["decision_time"], "decision_time", role="DECISION_TIME")
        require_time_evidence(decision["decision_cutoff"], "decision_cutoff", role="DECISION_CUTOFF")
        if cutoff > decision_time:
            raise RecorderContractError("DECISION_CUTOFF cannot follow DECISION_TIME.")
        refs = decision["known_at_evidence_refs"]
        if not isinstance(refs, list):
            raise RecorderContractError("known_at_evidence_refs must be an array.")
        record_index = self._record_index(partition)
        for ref_index, ref in enumerate(refs):
            if not isinstance(ref, Mapping):
                raise RecorderContractError("Known-at evidence reference must be an object.")
            ref_identity = require_identity(
                ref.get("record_id"), f"known_at_evidence_refs[{ref_index}].record_id"
            )
            require_sha256(ref.get("payload_sha256"), f"known_at_evidence_refs[{ref_index}].payload_sha256")
            pointer = _text(ref, "evidence_field_path")
            known_evidence = require_time_evidence(
                ref.get("known_at"), f"known_at_evidence_refs[{ref_index}].known_at"
            )
            if known_evidence["role"] not in {
                "PROVIDER_KNOWN_AT",
                "PROVIDER_RECEIVED_AT",
            }:
                raise RecorderContractError(
                    "Known-at reference must use a provider-known/received role."
                )
            known = evidence_instant(
                known_evidence, f"known_at_evidence_refs[{ref_index}].known_at"
            )
            if known > cutoff:
                raise RecorderContractError("Later-known evidence cannot enter a frozen decision.")
            resolved = record_index.get(str(ref_identity["recorder_id"]))
            if resolved is None or sha256_hex(resolved[1]) != ref["payload_sha256"]:
                raise RecorderContractError(
                    "Known-at evidence reference does not resolve exact accepted bytes."
                )
            resolved_evidence = _resolve_json_pointer(resolved[0], pointer)
            if resolved_evidence != known_evidence:
                raise RecorderContractError(
                    "Known-at reference value/role differs from the exact hashed parent field."
                )
        require_evidence_value(decision["strategy_identity"], "strategy_identity")
        hash_fields = [
            "decision_policy_fingerprint_sha256",
            "config_fingerprint_sha256",
            "runtime_fingerprint_sha256",
        ]
        if export_schema_version == SCHEMA_VERSION:
            hash_fields.append("outcome_eligibility_commitment_sha256")
        for field in hash_fields:
            require_sha256(decision[field], field)
        for field in ("market_snapshot_id", "tradeplan_id", "reference_plan_id"):
            require_evidence_value(decision[field], field)
        parent = record_index.get(str(observation_id["recorder_id"]))
        if parent is None or parent[0].get("record_type") != "candidate-observation":
            raise RecorderContractError("Decision observation parent is missing.")
        if parent[0].get("candidate_or_setup_identity") != decision["candidate_or_setup_identity"]:
            raise RecorderContractError("Decision setup/candidate identity differs from observation.")
        if evidence_instant(parent[0]["discovery_time"], "observation.discovery_time") > cutoff:
            raise RecorderContractError("Decision cutoff precedes the linked observation discovery.")
        if export_schema_version == SCHEMA_VERSION:
            commitment = parent[0].get("outcome_eligibility")
            if (
                not isinstance(commitment, Mapping)
                or decision["outcome_eligibility_commitment_sha256"]
                != commitment.get("commitment_payload_sha256")
            ):
                raise RecorderContractError(
                    "Decision eligibility hash does not bind its observation."
                )
        else:
            self._science_eligibility_for_observation(partition, parent[0])
        reference_state = decision["reference_plan_id"].get("state")
        market_state = decision["market_snapshot_id"].get("state")
        if market_state == "PRESENT":
            market_identity = require_identity(
                decision["market_snapshot_id"].get("value"),
                "market_snapshot_id.value",
                kinds=frozenset({"MARKET_SNAPSHOT_ID"}),
            )
            market_parent = record_index.get(str(market_identity["recorder_id"]))
            if market_parent is None or market_parent[0].get("record_type") != "market-snapshot":
                raise RecorderContractError("Present market snapshot link does not resolve.")
            snapshot = market_parent[0]
            if snapshot.get("snapshot_kind") != "DECISION_SNAPSHOT":
                raise RecorderContractError("Decision market link must resolve a decision snapshot.")
            if snapshot.get("instrument_identity") != parent[0].get("instrument_identity"):
                raise RecorderContractError("Decision snapshot instrument differs from observation.")
            snapshot_observation = snapshot.get("observation_id")
            if not isinstance(snapshot_observation, Mapping) or snapshot_observation.get("value") != observation_id:
                raise RecorderContractError("Decision snapshot observation link differs from decision.")
            provider_known = snapshot.get("provider_known_at")
            provider_received = snapshot.get("provider_received_at")
            actual_known = (
                provider_known
                if isinstance(provider_known, Mapping) and provider_known.get("state") == "PRESENT"
                else provider_received
            )
            if evidence_instant(actual_known, "decision_snapshot.known_at") > cutoff:
                raise RecorderContractError("Decision snapshot was not actually known by cutoff.")
        if decision["tradeplan_id"].get("state") == "PRESENT":
            require_identity(
                decision["tradeplan_id"].get("value"),
                "tradeplan_id.value",
                kinds=frozenset({"TRADEPLAN_ID"}),
            )
        if reference_state == "PRESENT":
            require_identity(
                decision["reference_plan_id"].get("value"),
                "reference_plan_id.value",
                kinds=frozenset({"REFERENCE_PLAN_ID"}),
            )
        if plan is None and reference_state == "PRESENT":
            raise RecorderContractError("Present reference plan must be supplied contemporaneously.")
        if plan is None and decision["tradeplan_id"].get("state") == "PRESENT":
            raise RecorderContractError("Present TradePlan must be supplied contemporaneously.")
        if plan is not None:
            if reference_state != "PRESENT" or decision["tradeplan_id"].get("state") != "PRESENT":
                raise RecorderContractError("Plan cannot be fabricated for an absent plan decision.")
            self._validate_reference_plan(plan, decision, cutoff)
        return decision, plan

    def _validate_reference_plan(
        self,
        plan: Mapping[str, object],
        decision: Mapping[str, object],
        cutoff: datetime,
    ) -> None:
        required = (
            "reference_plan_id",
            "tradeplan_id",
            "decision_id",
            "candidate_or_setup_identity",
            "plan_owner",
            "plan_schema_version",
            "plan_source_fingerprint_sha256",
            "plan_created_at",
            "entry",
            "stop",
            "t1",
            "t2",
        )
        for field in required:
            if field not in plan:
                raise RecorderContractError(f"Reference plan missing {field}.")
        plan_id = require_identity(
            plan["reference_plan_id"],
            "reference_plan_id",
            kinds=frozenset({"REFERENCE_PLAN_ID"}),
        )
        if decision["reference_plan_id"].get("value") != plan_id:
            raise RecorderContractError("Decision reference plan link differs from supplied plan.")
        tradeplan_id = require_identity(
            plan["tradeplan_id"], "tradeplan_id", kinds=frozenset({"TRADEPLAN_ID"})
        )
        if decision["tradeplan_id"].get("value") != tradeplan_id:
            raise RecorderContractError("Decision TradePlan link differs from supplied plan.")
        if plan["decision_id"] != decision["decision_id"]:
            raise RecorderContractError("Reference plan links another decision.")
        if plan["candidate_or_setup_identity"] != decision["candidate_or_setup_identity"]:
            raise RecorderContractError("Reference plan links another setup/candidate.")
        _text(plan, "plan_owner")
        _text(plan, "plan_schema_version")
        if evidence_instant(plan["plan_created_at"], "plan_created_at") > cutoff:
            raise RecorderContractError("Reference plan created after decision cutoff.")
        require_sha256(plan["plan_source_fingerprint_sha256"], "plan_source_fingerprint_sha256")
        for role in ("entry", "stop", "t1", "t2"):
            level = plan[role]
            if not isinstance(level, Mapping):
                raise RecorderContractError("Reference level must be an object.")
            if level.get("level_role") != role.upper():
                raise RecorderContractError("Reference level role does not match its field.")
            if level["state"] == "PRESENT":
                require_identity(
                    level.get("reference_level_id"),
                    f"{role}.reference_level_id",
                    kinds=frozenset({"REFERENCE_LEVEL_ID"}),
                )
                require_sha256(
                    level.get("level_source_fingerprint_sha256"),
                    f"{role}.level_source_fingerprint_sha256",
                )
                if not isinstance(level.get("value"), str):
                    raise RecorderContractError("Reference level must be a decimal string.")

    def _validate_market(self, partition: PurePath, payload: Mapping[str, object]) -> Mapping[str, object]:
        if set(payload) != {"market_snapshot"} or not isinstance(payload["market_snapshot"], Mapping):
            raise RecorderContractError("MARKET_FACT payload shape is not the offline profile.")
        record = payload["market_snapshot"]
        required = (
            "market_snapshot_id",
            "snapshot_kind",
            "instrument_identity",
            "observation_id",
            "decision_id",
            "outcome_series_id",
            "source_event_time",
            "provider_known_at",
            "provider_received_at",
            "market_facts",
            "market_data_owner",
            "source_market_fact_fingerprint_sha256",
        )
        for field in required:
            if field not in record:
                raise RecorderContractError(f"Market snapshot missing {field}.")
        require_identity(
            record["market_snapshot_id"],
            "market_snapshot_id",
            kinds=frozenset({"MARKET_SNAPSHOT_ID"}),
        )
        self._validate_instrument(record["instrument_identity"], "instrument_identity")
        for field in ("observation_id", "decision_id", "outcome_series_id"):
            require_evidence_value(record[field], field)
        require_time_evidence(record["source_event_time"], "source_event_time", role="SOURCE_EVENT_TIME")
        require_time_evidence(record["provider_known_at"], "provider_known_at", role="PROVIDER_KNOWN_AT")
        require_time_evidence(
            record["provider_received_at"], "provider_received_at", role="PROVIDER_RECEIVED_AT"
        )
        if (
            record["provider_known_at"].get("state") == "PRESENT"
            and record["provider_received_at"].get("state") == "PRESENT"
            and evidence_instant(record["provider_known_at"], "provider_known_at")
            > evidence_instant(record["provider_received_at"], "provider_received_at")
        ):
            raise RecorderContractError("Provider known-at cannot follow provider receipt.")
        if not isinstance(record["market_facts"], Mapping):
            raise RecorderContractError("market_facts must be an evidence-value mapping.")
        for field, fact in record["market_facts"].items():
            if field in {"bar_interval_start", "bar_interval_end"}:
                require_time_evidence(fact, f"market_facts.{field}")
            else:
                require_evidence_value(fact, f"market_facts.{field}")
        require_sha256(record["source_market_fact_fingerprint_sha256"], "source_market_fact_fingerprint_sha256")
        index = self._record_index(partition)
        if record["snapshot_kind"] == "DECISION_SNAPSHOT":
            if record["observation_id"].get("state") != "PRESENT":
                raise RecorderContractError("Decision snapshot requires observation identity.")
            observation = record["observation_id"].get("value")
            require_identity(observation, "observation_id.value", kinds=frozenset({"OBSERVATION_ID"}))
            observation_parent = index.get(str(observation["recorder_id"]))
            if observation_parent is None or observation_parent[0].get("record_type") != "candidate-observation":
                raise RecorderContractError("Market snapshot observation parent is missing.")
            if observation_parent[0].get("instrument_identity") != record["instrument_identity"]:
                raise RecorderContractError("Decision snapshot instrument differs from observation.")
            if record["decision_id"].get("state") == "PRESENT":
                decision_identity = require_identity(
                    record["decision_id"].get("value"),
                    "decision_id.value",
                    kinds=frozenset({"DECISION_ID"}),
                )
                decision_parent = index.get(str(decision_identity["recorder_id"]))
                if decision_parent is None or decision_parent[0].get("record_type") != "decision-event":
                    raise RecorderContractError("Market snapshot decision link does not resolve.")
        elif record["snapshot_kind"] == "CANONICAL_MINUTE_BAR":
            if record["observation_id"].get("state") != "NOT_APPLICABLE" or record[
                "decision_id"
            ].get("state") != "NOT_APPLICABLE":
                raise RecorderContractError(
                    "Canonical bars link through outcomes, not observation/decision inference."
                )
            if record["outcome_series_id"].get("state") != "PRESENT":
                raise RecorderContractError("Canonical bar requires outcome series identity.")
            require_identity(
                record["outcome_series_id"].get("value"),
                "outcome_series_id.value",
                kinds=frozenset({"OUTCOME_SERIES_ID"}),
            )
            required_bar_facts = {
                "bar_open",
                "bar_high",
                "bar_low",
                "bar_close",
                "bar_volume",
                "bar_interval_start",
                "bar_interval_end",
                "bar_complete",
            }
            if not required_bar_facts.issubset(record["market_facts"]):
                raise RecorderContractError("Canonical minute bar is missing complete OHLCV/time facts.")
            complete = record["market_facts"]["bar_complete"]
            if complete.get("state") != "PRESENT" or complete.get("value") is not True:
                raise RecorderContractError("Canonical minute bar must be explicitly complete.")
            start = evidence_instant(
                record["market_facts"]["bar_interval_start"], "bar_interval_start"
            )
            end = evidence_instant(
                record["market_facts"]["bar_interval_end"], "bar_interval_end"
            )
            if (end - start).total_seconds() != 60:
                raise RecorderContractError("Canonical bar must span exactly one minute.")
            if evidence_instant(record["source_event_time"], "source_event_time") != end:
                raise RecorderContractError("Canonical bar source_event_time must equal interval end.")
        else:
            raise RecorderContractError("Unsupported market snapshot kind.")
        return record

    def _validate_health(self, payload: Mapping[str, object]) -> Mapping[str, object]:
        if set(payload) != {"provider_health_event"} or not isinstance(payload["provider_health_event"], Mapping):
            raise RecorderContractError("PROVIDER_HEALTH payload shape is not the offline profile.")
        record = payload["provider_health_event"]
        required = (
            "provider_health_event_id",
            "interface_or_owner",
            "event_class",
            "event_state",
            "reason_code",
            "source_event_time",
            "provider_received_at",
            "affected_record_ids",
            "attempt_number",
            "terminal",
            "secret_material_present",
        )
        for field in required:
            if field not in record:
                raise RecorderContractError(f"Provider health event missing {field}.")
        require_identity(
            record["provider_health_event_id"],
            "provider_health_event_id",
            kinds=frozenset({"PROVIDER_HEALTH_EVENT_ID"}),
        )
        if record["secret_material_present"] is not False:
            raise RecorderContractError("Secret material can never enter Science custody.")
        require_time_evidence(record["source_event_time"], "source_event_time", role="SOURCE_EVENT_TIME")
        require_time_evidence(
            record["provider_received_at"], "provider_received_at", role="PROVIDER_RECEIVED_AT"
        )
        require_evidence_value(record["attempt_number"], "attempt_number")
        if not isinstance(record["affected_record_ids"], list) or not isinstance(record["terminal"], bool):
            raise RecorderContractError("Provider-health linkage fields are malformed.")
        for index, identity in enumerate(record["affected_record_ids"]):
            require_identity(identity, f"affected_record_ids[{index}]")
        return record

    def _normalize_export(
        self,
        envelope: ValidatedExportEnvelope,
        partition: PurePath,
        capture_time: str,
    ) -> tuple[dict[str, object], ...]:
        if envelope.schema_version == REPAIRED_EXPORT_SCHEMA_VERSION:
            received = parse_rfc3339(capture_time, "recorder_capture_time")
            producer_known_at = parse_rfc3339(
                envelope.effective_known_at, "effective_known_at"
            )
            producer_sealed_at = parse_rfc3339(envelope.emitted_at, "emitted_at")
            if received < producer_known_at or received < producer_sealed_at:
                raise RecorderContractError(
                    "Science receipt time cannot precede producer known-at or seal time."
                )
        common = {
            "partition": partition,
            "session_id": envelope.session_id,
            "source_owner": envelope.source_owner_identity,
            "source_contract": envelope.source_contract,
            "source_contract_version": envelope.source_contract_version,
            "source_interface_identity": envelope.source_interface_identity,
            "source_event_id": envelope.source_event_id,
            "source_fingerprint_sha256": envelope.source_event_fingerprint_sha256,
            "source_payload_sha256": envelope.payload_sha256,
            "source_envelope_sha256": envelope.raw_sha256,
            "capture_time": capture_time,
        }
        if envelope.event_type == "SESSION_MANIFEST":
            phase = envelope.payload.get("manifest_phase")
            if phase == "START":
                validate_start_manifest(
                    envelope.payload,
                    session_id=envelope.session_id,
                    source_root_identity=self.source_root_identity,
                )
            elif phase == "FINAL":
                self._validate_source_final(partition, envelope)
            else:
                raise RecorderContractError("Session manifest phase must be START or FINAL.")
            record_id = owner_identity(
                "SESSION_MANIFEST_ID",
                SOURCE_CONTRACT,
                envelope.source_event_id,
                owner_schema_version=PREDECESSOR_SCHEMA_VERSION,
            )
            core = dict(envelope.payload)
            core.pop("session_id", None)
            return (
                self._base_record(
                    record_type="session-manifest",
                    record_id=record_id,
                    core=core,
                    **common,
                ),
            )
        if envelope.event_type == "DISCOVERY_CYCLE":
            cycle, observations = self._validate_discovery(envelope.payload)
            records = [
                self._base_record(
                    record_type="discovery-cycle",
                    record_id=cycle["discovery_cycle_id"],
                    core=cycle,
                    **common,
                )
            ]
            eligibility_by_instrument = self._existing_eligibility_by_instrument(partition)
            for observation in observations:
                core = dict(observation)
                if envelope.schema_version == REPAIRED_EXPORT_SCHEMA_VERSION:
                    core["producer_effective_known_at"] = envelope.effective_known_at
                fingerprint = str(
                    observation["instrument_identity"][
                        "instrument_identity_fingerprint_sha256"
                    ]
                )
                if envelope.schema_version == SCHEMA_VERSION:
                    commitment = eligibility_by_instrument.get(fingerprint)
                    if commitment is None:
                        commitment = self._eligibility_commitment(
                            partition, observation, capture_time
                        )
                        eligibility_by_instrument[fingerprint] = commitment
                    core["outcome_eligibility"] = commitment
                records.append(
                    self._base_record(
                        record_type="candidate-observation",
                        record_id=observation["observation_id"],
                        core=core,
                        **common,
                    )
                )
            return tuple(records)
        if envelope.event_type == "DECISION_FACT":
            decision, plan = self._validate_decision(
                partition,
                envelope.payload,
                export_schema_version=envelope.schema_version,
            )
            decision_core = dict(decision)
            if envelope.schema_version == REPAIRED_EXPORT_SCHEMA_VERSION:
                observation_id = require_identity(
                    decision["observation_id"],
                    "observation_id",
                    kinds=frozenset({"OBSERVATION_ID"}),
                )
                observation = self._record_index(partition)[
                    str(observation_id["recorder_id"])
                ][0]
                eligibility_record, eligibility = (
                    self._science_eligibility_for_observation(
                        partition, observation
                    )
                )
                decision_core["science_eligibility_id"] = eligibility_record[
                    "eligibility_id"
                ]
                decision_core[
                    "science_eligibility_commitment_sha256"
                ] = eligibility["commitment_payload_sha256"]
            records = [
                self._base_record(
                    record_type="decision-event",
                    record_id=decision["decision_id"],
                    core=decision_core,
                    **common,
                )
            ]
            if plan is not None:
                records.append(
                    self._base_record(
                        record_type="reference-plan",
                        record_id=plan["reference_plan_id"],
                        core=plan,
                        **common,
                    )
                )
            return tuple(records)
        if envelope.event_type == "MARKET_FACT":
            record = self._validate_market(partition, envelope.payload)
            return (
                self._base_record(
                    record_type="market-snapshot",
                    record_id=record["market_snapshot_id"],
                    core=record,
                    **common,
                ),
            )
        if envelope.event_type == "PROVIDER_HEALTH":
            record = self._validate_health(envelope.payload)
            return (
                self._base_record(
                    record_type="provider-health-event",
                    record_id=record["provider_health_event_id"],
                    core=record,
                    **common,
                ),
            )
        raise RecorderContractError("Unsupported normalized export event.")

    def _persist_record(
        self,
        partition: PurePath,
        source_kind: str,
        stream_id: str,
        source_event_id: str,
        record: Mapping[str, object],
        *,
        crash_phase: str | None,
        crash_used: bool,
    ) -> tuple[str, str, str, int]:
        channel = str(record["channel"])
        identity = record["record_id"]
        if not isinstance(identity, Mapping):
            raise RecorderContractError("Normalized record identity is malformed.")
        recorder_id = str(identity["recorder_id"])
        key = _record_key(recorder_id)
        state = self._channel_state(partition, channel)
        existing = state.payloads.get(key)
        if existing is not None:
            existing_record = existing[1]
            expected = dict(record)
            expected["record_sequence"] = existing_record.get("record_sequence")
            expected["recorder_capture_time"] = existing_record.get("recorder_capture_time")
            expected_bytes = canonical_json_bytes(expected)
            if expected_bytes != existing[2]:
                self._persist_conflict(
                    partition,
                    source_kind=source_kind,
                    stream_id=stream_id,
                    source_event_id=source_event_id,
                    conflicting_raw=expected_bytes,
                    reason_code="SAME_LOGICAL_ID_DIFFERENT_CANONICAL_BYTES",
                    accepted_sha256=sha256_hex(existing[2]),
                    logical_record_id=recorder_id,
                )
                raise RecorderConflictError("Logical record identity was reused with different bytes.")
            payload = existing_record
            payload_bytes = existing[2]
        else:
            if state.orphan_payload_keys:
                raise RecorderRecoveryError("A different uncommitted payload tail blocks append.")
            payload = dict(record)
            payload["record_sequence"] = state.last_sequence + 1
            payload_bytes = canonical_json_bytes(payload)
            self._storage.atomic_create(
                partition / "payloads" / channel / f"{key}.payload.json",
                payload_bytes,
            )
            if crash_phase == "after_payload" and not crash_used:
                raise SimulatedRecorderCrash("Synthetic interruption after payload install.")
        state = self._channel_state(partition, channel)
        existing_receipt = state.receipts.get(key)
        if existing_receipt is None:
            sequence = int(payload["record_sequence"])
            if sequence != state.last_sequence + 1:
                raise RecorderRecoveryError("Uncommitted payload is not next in its receipt chain.")
            previous_evidence = (
                _not_applicable("GENESIS_RECEIPT", authority="SCIENCE_RECORDER")
                if sequence == 1
                else _present_value(state.last_receipt_sha256, authority="SCIENCE_RECORDER")
            )
            receipt = {
                "canonicalization_version": CANONICALIZATION_VERSION,
                "channel": channel,
                "committed_at": payload["recorder_capture_time"],
                "payload_sha256": sha256_hex(payload_bytes),
                "previous_receipt_sha256": previous_evidence,
                "receipt_version": RECEIPT_VERSION,
                "record_id": identity,
                "record_key_sha256": key,
                "record_sequence": sequence,
                "schema_version": SCHEMA_VERSION,
                "source_envelope_sha256": record["source_envelope_sha256"],
                "source_payload_sha256": record["source_payload_sha256"],
            }
            receipt_bytes = canonical_json_bytes(receipt)
            self._storage.atomic_create(
                partition / "receipts" / channel / f"{key}.receipt.json",
                receipt_bytes,
            )
            if crash_phase == "after_receipt" and not crash_used:
                raise SimulatedRecorderCrash("Synthetic interruption after receipt commit.")
        else:
            receipt_bytes = existing_receipt[2]
        state = self._channel_state(partition, channel)
        if key not in state.receipts or key in state.orphan_payload_keys:
            raise RecorderRecoveryError("Record did not reach a verified receipt commit.")
        return (
            recorder_id,
            sha256_hex(payload_bytes),
            sha256_hex(state.receipts[key][2]),
            int(payload["record_sequence"]),
        )

    def _accept_common(
        self,
        *,
        partition: PurePath,
        source_kind: str,
        stream_id: str,
        source_event_id: str,
        source_sequence: int,
        previous_source_sha256: str,
        raw_bytes: bytes,
        raw_sha256: str,
        channel: str,
        records: tuple[dict[str, object], ...],
        derive_science_eligibility: bool,
        crash_phase: str | None,
    ) -> AcceptanceResult:
        if self._stream_is_frozen(partition, source_kind, stream_id):
            raise RecorderConflictError("Affected source stream is frozen by persistent conflict evidence.")
        state = self._stream_state(partition, source_kind, stream_id)
        for checkpoint in state.checkpoints:
            if checkpoint["source_event_id"] == source_event_id:
                if checkpoint["source_envelope_sha256"] != raw_sha256:
                    self._persist_conflict(
                        partition,
                        source_kind=source_kind,
                        stream_id=stream_id,
                        source_event_id=source_event_id,
                        conflicting_raw=raw_bytes,
                        reason_code="SOURCE_EVENT_ID_REUSED_WITH_DIFFERENT_BYTES",
                        accepted_sha256=str(checkpoint["source_envelope_sha256"]),
                    )
                    raise RecorderConflictError("Source event identity conflicts with accepted bytes.")
                return AcceptanceResult(
                    status="IDEMPOTENT_ACK",
                    source_kind=source_kind,
                    source_event_id=source_event_id,
                    source_sequence=source_sequence,
                    record_ids=tuple(str(item) for item in checkpoint["accepted_record_ids"]),
                    checkpoint_sha256=str(checkpoint["checkpoint_payload_sha256"]),
                )
        expected_sequence = state.last_sequence + 1
        if source_sequence != expected_sequence:
            if source_sequence < expected_sequence:
                self._persist_conflict(
                    partition,
                    source_kind=source_kind,
                    stream_id=stream_id,
                    source_event_id=source_event_id,
                    conflicting_raw=raw_bytes,
                    reason_code="SOURCE_CURSOR_REGRESSION",
                    accepted_sha256=state.last_source_sha256,
                )
                raise RecorderConflictError("Source cursor regressed; stream failed closed.")
            raise RecorderCustodyError("Source sequence gap; stream cannot advance.")
        if previous_source_sha256 != state.last_source_sha256:
            raise RecorderCustodyError("Source prior hash does not bind exact prior raw envelope bytes.")
        source_dir, checkpoint_dir = self._stream_paths(partition, source_kind, stream_id)
        source_key = _source_event_key(source_event_id)
        source_path = source_dir / f"{source_key}.source.json"
        existing_sources = [
            path
            for path in self._files(source_dir, ".source.json")
            if path.name == f"{source_key}.source.json"
        ]
        if existing_sources:
            existing_raw = existing_sources[0].read_bytes()
            if existing_raw != raw_bytes:
                self._persist_conflict(
                    partition,
                    source_kind=source_kind,
                    stream_id=stream_id,
                    source_event_id=source_event_id,
                    conflicting_raw=raw_bytes,
                    reason_code="SOURCE_EVENT_ID_REUSED_WITH_DIFFERENT_BYTES",
                    accepted_sha256=sha256_hex(existing_raw),
                )
                raise RecorderConflictError("Source event identity conflicts with staged bytes.")
        else:
            self._storage.atomic_create(source_path, raw_bytes)
        if crash_phase == "after_source":
            raise SimulatedRecorderCrash("Synthetic interruption after exact source preservation.")
        record_ids: list[str] = []
        payload_hashes: list[str] = []
        receipt_hashes: list[str] = []
        record_sequences: list[int] = []
        crash_used = False
        science_eligibility_by_instrument = (
            self._science_eligibility_by_instrument(partition)
            if derive_science_eligibility
            else {}
        )
        for record in records:
            record_id, payload_hash, receipt_hash, record_sequence = self._persist_record(
                partition,
                source_kind,
                stream_id,
                source_event_id,
                record,
                crash_phase=crash_phase,
                crash_used=crash_used,
            )
            record_ids.append(record_id)
            payload_hashes.append(payload_hash)
            receipt_hashes.append(receipt_hash)
            record_sequences.append(record_sequence)
            crash_used = crash_used or crash_phase in {"after_payload", "after_receipt"}
            if (
                derive_science_eligibility
                and record.get("record_type") == "candidate-observation"
            ):
                instrument = record.get("instrument_identity")
                fingerprint = (
                    instrument.get("instrument_identity_fingerprint_sha256")
                    if isinstance(instrument, Mapping)
                    else None
                )
                if not isinstance(fingerprint, str):
                    raise RecorderContractError(
                        "Candidate observation instrument identity is malformed."
                    )
                if fingerprint not in science_eligibility_by_instrument:
                    eligibility_record = self._science_eligibility_record(
                        partition,
                        record,
                        observation_payload_sha256=payload_hash,
                        observation_receipt_sha256=receipt_hash,
                    )
                    (
                        eligibility_record_id,
                        eligibility_payload_hash,
                        eligibility_receipt_hash,
                        eligibility_record_sequence,
                    ) = self._persist_record(
                        partition,
                        source_kind,
                        stream_id,
                        source_event_id,
                        eligibility_record,
                        crash_phase=crash_phase,
                        crash_used=crash_used,
                    )
                    record_ids.append(eligibility_record_id)
                    payload_hashes.append(eligibility_payload_hash)
                    receipt_hashes.append(eligibility_receipt_hash)
                    record_sequences.append(eligibility_record_sequence)
                    material = self._validate_science_eligibility_record(
                        partition, eligibility_record
                    )
                    science_eligibility_by_instrument[fingerprint] = (
                        eligibility_record,
                        material,
                    )
        if not record_ids:
            raise RecorderCustodyError("Source event normalized to no custody records.")
        checkpoint = {
            "accepted_payload_sha256s": payload_hashes,
            "accepted_receipt_sha256s": receipt_hashes,
            "accepted_record_ids": record_ids,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "channel": channel,
            "checkpoint_sequence": source_sequence,
            "cursor_version": CURSOR_VERSION,
            "last_accepted_payload_sha256": payload_hashes[-1],
            "last_accepted_receipt_sha256": receipt_hashes[-1],
            "last_accepted_record_id": record_ids[-1],
            "last_accepted_record_sequence": record_sequences[-1],
            "partition_id": partition.as_posix(),
            "previous_checkpoint_sha256": state.last_checkpoint_sha256,
            "previous_source_envelope_sha256": previous_source_sha256,
            "schema_major_version": SCHEMA_MAJOR_VERSION,
            "session_id": records[0]["session_id"],
            "source_cursor_or_event_id": source_event_id,
            "source_envelope_sha256": raw_sha256,
            "source_event_id": source_event_id,
            "source_kind": source_kind,
            "source_owner_namespace": records[0]["source_owner"],
            "source_sequence": source_sequence,
            "source_stream_id": stream_id,
            "stream_id": stream_id,
        }
        checkpoint["checkpoint_payload_sha256"] = sha256_hex(canonical_json_bytes(checkpoint))
        checkpoint_bytes = canonical_json_bytes(checkpoint)
        checkpoint_name = f"{source_sequence:020d}-{source_key}.checkpoint.json"
        self._storage.atomic_create(checkpoint_dir / checkpoint_name, checkpoint_bytes)
        verified = self._stream_state(partition, source_kind, stream_id)
        if verified.last_sequence != source_sequence:
            raise RecorderRecoveryError("New immutable checkpoint did not verify.")
        return AcceptanceResult(
            status="ACCEPTED",
            source_kind=source_kind,
            source_event_id=source_event_id,
            source_sequence=source_sequence,
            record_ids=tuple(record_ids),
            checkpoint_sha256=str(checkpoint["checkpoint_payload_sha256"]),
        )

    def accept(
        self, raw_envelope: bytes, *, crash_phase: str | None = None
    ) -> AcceptanceResult:
        """Accept one strict offline export envelope and advance only after proof."""

        if crash_phase not in {None, "after_source", "after_payload", "after_receipt"}:
            raise RecorderCustodyError("Unknown fault-injection phase.")
        envelope = parse_export_envelope(raw_envelope)
        if envelope.event_type == "SESSION_MANIFEST":
            phase = envelope.payload.get("manifest_phase")
            if phase == "START":
                partition = self._partition_for_start(envelope)
            elif phase == "FINAL":
                partition = self._locate_partition(envelope.session_id)
            else:
                raise RecorderContractError("Session manifest phase must be START or FINAL.")
        else:
            partition = self._locate_partition(envelope.session_id)
            self._start_record(partition)
        existing_result = self._existing_source_result(
            partition,
            source_kind="export",
            stream_id=envelope.stream_id,
            source_event_id=envelope.source_event_id,
            source_sequence=envelope.source_sequence,
            raw_sha256=envelope.raw_sha256,
            raw_bytes=envelope.raw_bytes,
        )
        if existing_result is not None:
            return existing_result
        source_finals = self._source_final_records(partition)
        if source_finals:
            same_uncheckpointed_final = (
                envelope.event_type == "SESSION_MANIFEST"
                and envelope.payload.get("manifest_phase") == "FINAL"
                and len(source_finals) == 1
                and isinstance(source_finals[0].get("source_record_identity"), Mapping)
                and source_finals[0]["source_record_identity"].get("value")
                == envelope.source_event_id
            )
            if not same_uncheckpointed_final:
                raise RecorderCustodyError("Source-finalized session accepts no new evidence.")
        self._ensure_open_partition(partition)
        capture_time = self._capture_time_for_source(partition, envelope.raw_sha256)
        with self._storage.transaction():
            records = self._normalize_export(envelope, partition, capture_time)
            result = self._accept_common(
                partition=partition,
                source_kind="export",
                stream_id=envelope.stream_id,
                source_event_id=envelope.source_event_id,
                source_sequence=envelope.source_sequence,
                previous_source_sha256=envelope.previous_record_sha256,
                raw_bytes=envelope.raw_bytes,
                raw_sha256=envelope.raw_sha256,
                channel=envelope.channel,
                records=records,
                derive_science_eligibility=(
                    envelope.schema_version == REPAIRED_EXPORT_SCHEMA_VERSION
                ),
                crash_phase=crash_phase,
            )
        return result

    def _validate_outcome_links(
        self,
        partition: PurePath,
        attachment: ValidatedOutcomeAttachment,
    ) -> None:
        payload = attachment.payload
        index = self._record_index(partition)
        decision_id = str(payload["decision_id"]["recorder_id"])
        observation_id = str(payload["observation_id"]["recorder_id"])
        decision = index.get(decision_id)
        observation = index.get(observation_id)
        if decision is None or decision[0].get("record_type") != "decision-event":
            raise RecorderContractError("Outcome decision parent is missing.")
        if observation is None or observation[0].get("record_type") != "candidate-observation":
            raise RecorderContractError("Outcome observation parent is missing.")
        if decision[0].get("observation_id") != payload["observation_id"]:
            raise RecorderContractError("Outcome observation differs from the decision parent.")
        if decision[0].get("candidate_or_setup_identity") != payload[
            "candidate_or_setup_identity"
        ] or observation[0].get("candidate_or_setup_identity") != payload[
            "candidate_or_setup_identity"
        ]:
            raise RecorderContractError(
                "Outcome candidate/setup identity differs from decision/observation parents."
            )
        if sha256_hex(decision[1]) != payload["decision_payload_sha256"]:
            raise RecorderContractError("Outcome does not bind exact frozen decision bytes.")
        science_eligibility_id = decision[0].get("science_eligibility_id")
        science_eligibility_hash = decision[0].get(
            "science_eligibility_commitment_sha256"
        )
        if science_eligibility_id is not None or science_eligibility_hash is not None:
            eligibility_record, commitment = (
                self._science_eligibility_for_observation(
                    partition, observation[0]
                )
            )
            if (
                science_eligibility_id != eligibility_record.get("eligibility_id")
                or science_eligibility_hash
                != commitment.get("commitment_payload_sha256")
            ):
                raise RecorderContractError(
                    "Science custody decision eligibility linkage is inconsistent."
                )
        else:
            commitment = observation[0].get("outcome_eligibility")
            if (
                not isinstance(commitment, Mapping)
                or commitment.get("eligibility_state") != "ELIGIBLE"
            ):
                raise RecorderContractError(
                    "Outcome observation is not pre-outcome eligible."
                )
            if (
                decision[0].get("outcome_eligibility_commitment_sha256")
                != payload["eligibility_commitment_sha256"]
            ):
                raise RecorderContractError(
                    "Outcome eligibility hash does not bind the decision."
                )
        if (
            commitment.get("commitment_payload_sha256")
            != payload["eligibility_commitment_sha256"]
        ):
            raise RecorderContractError(
                "Outcome eligibility hash does not bind the observation."
            )
        decision_time = evidence_instant(decision[0]["decision_time"], "decision_time")
        target = payload["target_time"]
        target_instant = evidence_instant(target, "target_time")
        start_record = self._start_record(partition)
        official_close = parse_rfc3339(
            start_record["regular_session_close"], "regular_session_close"
        )
        semantic = str(payload["outcome_semantic"])
        minute_offsets = {
            "PLUS_5M": 5,
            "PLUS_15M": 15,
            "PLUS_30M": 30,
            "PLUS_60M": 60,
        }
        expected_target = (
            decision_time + timedelta(minutes=minute_offsets[semantic])
            if semantic in minute_offsets
            else official_close
        )
        if target_instant != expected_target:
            raise RecorderContractError("Outcome target does not match its frozen horizon rule.")
        should_truncate = expected_target > official_close
        if should_truncate and payload["outcome_state"] != "SESSION_TRUNCATED":
            raise RecorderContractError("Beyond-close point horizon must be SESSION_TRUNCATED.")
        if not should_truncate and payload["outcome_state"] == "SESSION_TRUNCATED":
            raise RecorderContractError("SESSION_TRUNCATED is valid only when exact target exceeds close.")
        bar_ids = payload["canonical_bar_record_ids"]
        bar_hashes = payload["canonical_bar_payload_sha256s"]
        bar_intervals: list[tuple[datetime, datetime]] = []
        for identity, expected_hash in zip(bar_ids, bar_hashes):
            record_id = str(identity["recorder_id"])
            bar = index.get(record_id)
            if bar is None or bar[0].get("record_type") != "market-snapshot" or bar[0].get("snapshot_kind") != "CANONICAL_MINUTE_BAR":
                raise RecorderContractError("Outcome canonical bar parent is missing.")
            if sha256_hex(bar[1]) != expected_hash:
                raise RecorderContractError("Outcome canonical bar hash does not verify.")
            series = bar[0].get("outcome_series_id")
            if not isinstance(series, Mapping) or series.get("value") != payload["outcome_series_id"]:
                raise RecorderContractError("Outcome canonical bar belongs to another series.")
            if bar[0].get("instrument_identity") != observation[0].get("instrument_identity"):
                raise RecorderContractError("Outcome canonical bar belongs to another instrument.")
            if bar[0].get("session_id") != attachment.session_id:
                raise RecorderContractError("Outcome canonical bar belongs to another session.")
            facts = bar[0].get("market_facts")
            if not isinstance(facts, Mapping):
                raise RecorderContractError("Outcome canonical bar facts are missing.")
            bar_start = evidence_instant(facts.get("bar_interval_start"), "bar_interval_start")
            bar_end = evidence_instant(facts.get("bar_interval_end"), "bar_interval_end")
            if bar_end < decision_time:
                raise RecorderContractError("Outcome canonical bar precedes frozen decision time.")
            if bar_end > official_close:
                raise RecorderContractError("Outcome canonical bar ends after official close.")
            bar_intervals.append((bar_start, bar_end))
        if payload["outcome_state"] == "PRESENT":
            if semantic in {"MFE", "MAE"}:
                raise RecorderContractError("PRESENT MFE/MAE is not implemented.")
            if len(bar_intervals) != 1:
                raise RecorderContractError("Point outcome must bind exactly one canonical bar.")
            bar_start, bar_end = bar_intervals[0]
            if not (bar_start < target_instant <= bar_end):
                raise RecorderContractError("Point target is not contained in its canonical minute bar.")
            if semantic == "SESSION_CLOSE" and bar_end != official_close:
                raise RecorderContractError("SESSION_CLOSE must bind the bar ending exactly at close.")
            outcome_time = payload["outcome_time"]
            if evidence_instant(outcome_time, "outcome_time") != bar_end:
                raise RecorderContractError("Outcome time differs from its canonical bar time.")
        elif bar_intervals:
            raise RecorderContractError("Non-PRESENT outcome cannot bind canonical bars.")

    def append_outcome(
        self, raw_attachment: bytes, *, crash_phase: str | None = None
    ) -> AcceptanceResult:
        """Append a later outcome through a separate, never-retroactive surface."""

        if crash_phase not in {None, "after_source", "after_payload", "after_receipt"}:
            raise RecorderCustodyError("Unknown fault-injection phase.")
        attachment = parse_outcome_attachment(raw_attachment)
        partition = self._locate_partition(attachment.session_id)
        existing_result = self._existing_source_result(
            partition,
            source_kind="outcome",
            stream_id=attachment.stream_id,
            source_event_id=attachment.source_event_id,
            source_sequence=attachment.source_sequence,
            raw_sha256=attachment.raw_sha256,
            raw_bytes=attachment.raw_bytes,
        )
        if existing_result is not None:
            return existing_result
        if self._source_final_records(partition):
            raise RecorderCustodyError("Source-finalized session accepts no new outcomes.")
        self._ensure_open_partition(partition)
        incoming_slot = _outcome_slot(attachment.payload)
        incoming_identity = str(
            attachment.payload["outcome_observation_id"]["recorder_id"]
        )
        for existing, existing_raw in self._record_index(partition).values():
            if existing.get("record_type") != "outcome-observation":
                continue
            if _outcome_slot(existing) != incoming_slot:
                continue
            existing_identity = str(existing["outcome_observation_id"]["recorder_id"])
            if existing_identity != incoming_identity:
                self._persist_conflict(
                    partition,
                    source_kind="outcome",
                    stream_id=attachment.stream_id,
                    source_event_id=attachment.source_event_id,
                    conflicting_raw=attachment.raw_bytes,
                    reason_code="OUTCOME_SLOT_REUSED_WITH_DISTINCT_IDENTITY",
                    accepted_sha256=sha256_hex(existing_raw),
                    logical_record_id=existing_identity,
                )
                raise RecorderConflictError(
                    "Distinct outcome identity attempts to occupy an immutable semantic slot."
                )
        self._validate_outcome_links(partition, attachment)
        capture_time = self._capture_time_for_source(partition, attachment.raw_sha256)
        record = self._base_record(
            partition=partition,
            record_type="outcome-observation",
            record_id=attachment.payload["outcome_observation_id"],
            session_id=attachment.session_id,
            source_owner=attachment.source_owner,
            source_contract="OutcomeAttachmentV1",
            source_contract_version=SCHEMA_VERSION,
            source_interface_identity=attachment.source_owner,
            source_event_id=attachment.source_event_id,
            source_fingerprint_sha256=attachment.payload_sha256,
            source_payload_sha256=attachment.payload_sha256,
            source_envelope_sha256=attachment.raw_sha256,
            capture_time=capture_time,
            core=attachment.payload,
        )
        with self._storage.transaction():
            return self._accept_common(
                partition=partition,
                source_kind="outcome",
                stream_id=attachment.stream_id,
                source_event_id=attachment.source_event_id,
                source_sequence=attachment.source_sequence,
                previous_source_sha256=attachment.previous_record_sha256,
                raw_bytes=attachment.raw_bytes,
                raw_sha256=attachment.raw_sha256,
                channel="outcome",
                records=(record,),
                derive_science_eligibility=False,
                crash_phase=crash_phase,
            )

    def _all_records(self, partition: PurePath) -> tuple[Mapping[str, object], ...]:
        records: list[Mapping[str, object]] = []
        for channel in ("session", "discovery", "decision", "market", "health", "outcome"):
            state = self._channel_state(partition, channel)
            if state.orphan_payload_keys:
                raise RecorderRecoveryError("Uncommitted payload remains in session.")
            ordered = sorted(
                (item[1] for item in state.payloads.values()),
                key=lambda value: int(value["record_sequence"]),
            )
            records.extend(ordered)
        return tuple(records)

    def _all_stream_heads(self, partition: PurePath) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for source_kind in ("export", "outcome"):
            streams: set[str] = set()
            for path in self._files(
                partition / "sources" / source_kind, ".source.json"
            ):
                raw = path.read_bytes()
                parsed = (
                    parse_export_envelope(raw)
                    if source_kind == "export"
                    else parse_outcome_attachment(raw)
                )
                streams.add(parsed.stream_id)
            for stream_id in sorted(streams):
                state = self._stream_state(partition, source_kind, stream_id)
                result.append(
                    {
                        "last_checkpoint_sha256": state.last_checkpoint_sha256,
                        "last_source_envelope_sha256": state.last_source_sha256,
                        "last_source_sequence": state.last_sequence,
                        "source_kind": source_kind,
                        "stream_id": stream_id,
                    }
                )
        return sorted(result, key=lambda item: (item["source_kind"], item["stream_id"]))

    def _expected_final_checksum_bytes(
        self,
        partition: PurePath,
        manifest_path: Path,
        manifest: Mapping[str, object],
        manifest_raw: bytes,
    ) -> bytes:
        inventory = manifest.get("artifact_inventory")
        if not isinstance(inventory, list):
            raise RecorderRecoveryError("Final manifest inventory is malformed.")
        entries: dict[str, str] = {}
        partition_text = partition.as_posix() + "/"
        for item in inventory:
            if not isinstance(item, Mapping):
                raise RecorderRecoveryError("Final manifest inventory item is malformed.")
            relative = item.get("relative_path")
            digest = item.get("sha256")
            if not isinstance(relative, str) or not relative.startswith(partition_text):
                raise RecorderRecoveryError("Final inventory path escapes its session partition.")
            pure = PurePath(relative)
            if pure.is_absolute() or ".." in pure.parts or relative in entries:
                raise RecorderRecoveryError("Final inventory contains unsafe or duplicate paths.")
            try:
                require_sha256(digest, "artifact_inventory.sha256")
            except CanonicalizationError as exc:
                raise RecorderRecoveryError(str(exc)) from exc
            entries[relative] = str(digest)
        manifest_relative = self._relative(manifest_path)
        if manifest_relative in entries:
            raise RecorderRecoveryError("Final manifest cannot inventory its own final bytes.")
        entries[manifest_relative] = sha256_hex(manifest_raw)
        return "".join(
            f"{digest}  {relative}\n"
            for relative, digest in sorted(entries.items())
        ).encode("ascii")

    def _complete_or_verify_final_sidecar(
        self,
        partition: PurePath,
        manifest_path: Path,
        manifest: Mapping[str, object],
        manifest_raw: bytes,
        *,
        create_missing: bool,
    ) -> tuple[Path, bytes]:
        expected = self._expected_final_checksum_bytes(
            partition, manifest_path, manifest, manifest_raw
        )
        manifest_key = manifest_path.name.removesuffix(".final.json")
        expected_path = partition / "manifests" / f"{manifest_key}.sha256"
        sidecars = self._files(partition / "manifests", ".sha256")
        foreign = [path for path in sidecars if self._relative(path) != expected_path.as_posix()]
        if foreign:
            raise RecorderRecoveryError("Final manifest has an unexpected checksum sidecar.")
        if not sidecars:
            if not create_missing:
                raise RecorderRecoveryError(
                    "Final manifest exists without its detached checksum sidecar."
                )
            self._storage.atomic_create(expected_path, expected)
            sidecars = self._files(partition / "manifests", ".sha256")
        if len(sidecars) != 1:
            raise RecorderRecoveryError("Final manifest detached checksum is ambiguous.")
        actual = sidecars[0].read_bytes()
        if actual != expected:
            raise RecorderRecoveryError("Detached checksum target set or bytes do not verify.")
        return sidecars[0], actual

    def verify(self, session_id: Mapping[str, object]) -> VerificationReport:
        """Mechanically verify persisted source, chains, checkpoints, and final receipt."""

        partition = self._locate_partition(session_id)
        partition_path = self._storage.root / Path(partition)
        try:
            partition_resolved = partition_path.resolve(strict=True)
            partition_resolved.relative_to(self._storage.root.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise RecorderRecoveryError("Session partition escapes the configured custody root.") from exc
        allowed_suffixes = (
            ".source.json",
            ".payload.json",
            ".receipt.json",
            ".checkpoint.json",
            ".conflict.json",
            ".conflicting.raw",
            ".final.json",
            ".sha256",
        )
        unexpected = [
            path
            for path in partition_path.rglob("*")
            if path.is_file() and not path.name.endswith(allowed_suffixes)
        ]
        if unexpected:
            raise RecorderRecoveryError(
                f"Unknown evidence object in session partition: {unexpected[0].name}."
            )
        for path in partition_path.rglob("*"):
            if not path.is_file():
                continue
            try:
                path.resolve(strict=True).relative_to(partition_resolved)
                stat = path.stat(follow_symlinks=False)
            except (OSError, ValueError) as exc:
                raise RecorderRecoveryError("Evidence object escapes its session partition.") from exc
            if path.is_symlink() or stat.st_nlink != 1:
                raise RecorderRecoveryError(
                    "Evidence object is a reparse/link alias rather than one custody file."
                )
        records = self._all_records(partition)
        for record in records:
            if record.get("record_type") == "science-eligibility":
                self._validate_science_eligibility_record(partition, record)
            elif (
                record.get("record_type") == "candidate-observation"
                and record.get("source_contract_version")
                == REPAIRED_SOURCE_CONTRACT_VERSION
            ):
                self._science_eligibility_for_observation(partition, record)
        streams: set[tuple[str, str]] = set()
        source_count = 0
        for source_kind in ("export", "outcome"):
            base = partition / "sources" / source_kind
            for path in self._files(base, ".source.json"):
                raw = path.read_bytes()
                parsed = (
                    parse_export_envelope(raw)
                    if source_kind == "export"
                    else parse_outcome_attachment(raw)
                )
                if parsed.session_id != session_id:
                    raise RecorderRecoveryError("Source session identity differs from partition.")
                streams.add((source_kind, parsed.stream_id))
                source_count += 1
        checkpoint_paths = self._files(partition / "checkpoints", ".checkpoint.json")
        for path in checkpoint_paths:
            checkpoint, _raw = self._read_canonical(path, "checkpoint")
            source_kind = checkpoint.get("source_kind")
            stream_id = checkpoint.get("stream_id")
            if source_kind not in {"export", "outcome"} or not isinstance(stream_id, str):
                raise RecorderRecoveryError("Persisted checkpoint has an unknown stream binding.")
            streams.add((source_kind, stream_id))
        checkpoint_count = 0
        checkpoint_record_ids: list[str] = []
        for source_kind, stream_id in streams:
            state = self._stream_state(partition, source_kind, stream_id)
            checkpoint_count += len(state.checkpoints)
            for checkpoint in state.checkpoints:
                checkpoint_record_ids.extend(
                    str(item) for item in checkpoint["accepted_record_ids"]
                )
        if checkpoint_count != len(checkpoint_paths):
            raise RecorderRecoveryError("Checkpoint path inventory is ambiguous.")
        if checkpoint_count != source_count:
            raise RecorderRecoveryError("Every preserved source must have one verified checkpoint.")
        receipt_count = sum(
            len(self._channel_state(partition, channel).receipts)
            for channel in ("session", "discovery", "decision", "market", "health", "outcome")
        )
        if receipt_count != len(records):
            raise RecorderRecoveryError("Every payload must have exactly one verified receipt.")
        accepted_record_ids = [
            str(record["record_id"]["recorder_id"]) for record in records
        ]
        if (
            len(checkpoint_record_ids) != len(set(checkpoint_record_ids))
            or sorted(checkpoint_record_ids) != sorted(accepted_record_ids)
        ):
            raise RecorderRecoveryError(
                "Checkpoint inventories do not cover each accepted record exactly once."
            )
        conflicts = self._files(partition / "conflicts", ".conflict.json")
        conflict_raw_paths = {
            self._relative(path): path
            for path in self._files(partition / "conflicts", ".conflicting.raw")
        }
        referenced_conflict_raw: set[str] = set()
        for conflict_path in conflicts:
            conflict, _raw = self._read_canonical(conflict_path, "conflict")
            relative = conflict.get("conflicting_bytes_relative_path")
            if not isinstance(relative, str) or relative not in conflict_raw_paths:
                raise RecorderRecoveryError("Conflict evidence does not resolve exact raw bytes.")
            raw_bytes = conflict_raw_paths[relative].read_bytes()
            if conflict.get("conflicting_payload_sha256") != sha256_hex(raw_bytes):
                raise RecorderRecoveryError("Conflict raw-byte hash does not verify.")
            referenced_conflict_raw.add(relative)
        if referenced_conflict_raw != set(conflict_raw_paths):
            raise RecorderRecoveryError("Orphan conflicting raw evidence exists.")
        final_files = self._final_files(partition)
        if len(final_files) > 1:
            raise RecorderRecoveryError("Multiple final manifests exist.")
        if final_files:
            manifest, manifest_raw = self._read_canonical(final_files[0], "final manifest")
            expected_manifest_fields = {
                "artifact_inventory",
                "authority",
                "base_canonical_sha",
                "canonicalization_version",
                "channel_heads",
                "coverage",
                "custody_snapshot_classification",
                "execution_authority",
                "finalized_at",
                "implementation_scope",
                "live_capture_qualification",
                "manifest_phase",
                "manifest_version",
                "partition_id",
                "post_final_addendum",
                "predecessor_directive",
                "predecessor_schema_sha256",
                "predecessor_schema_version",
                "predecessor_sidecar_sha256",
                "producer_provider_evidence_classification",
                "schema_version",
                "science_custody_owner_profile",
                "science_recorder_provider_contact_occurred",
                "scope_limitations",
                "session_id",
                "source_event_type_counts",
                "source_final_payload_sha256",
                "source_final_reconciliation",
                "source_final_record_id",
                "source_root_identity",
                "source_stream_heads",
            }
            if (
                set(manifest) != expected_manifest_fields
                or manifest.get("manifest_phase") != "FINAL"
                or manifest.get("manifest_version") != MANIFEST_VERSION
                or manifest.get("session_id") != session_id
                or manifest.get("source_root_identity") != self.source_root_identity
                or manifest.get("authority") != AUTHORITY
                or manifest.get("execution_authority") != EXECUTION_AUTHORITY
                or manifest.get("science_recorder_provider_contact_occurred") is not False
                or manifest.get("producer_provider_evidence_classification")
                != "OPAQUE_PRODUCER_ASSERTION_ONLY"
                or manifest.get("implementation_scope")
                != "SCIENCE_CUSTODY_OFFLINE_REFERENCE_KERNEL_ONLY"
                or manifest.get("base_canonical_sha") != BASE_CANONICAL_SHA
                or manifest.get("predecessor_schema_sha256")
                != PREDECESSOR_SCHEMA_SHA256
                or manifest.get("predecessor_sidecar_sha256")
                != PREDECESSOR_SIDECAR_SHA256
            ):
                raise RecorderRecoveryError("Final manifest contract lineage is invalid.")
            inventory = manifest.get("artifact_inventory")
            if not isinstance(inventory, list):
                raise RecorderRecoveryError("Final manifest inventory is malformed.")
            actual_artifacts: set[str] = set()
            for suffix in (
                ".source.json",
                ".payload.json",
                ".receipt.json",
                ".checkpoint.json",
                ".conflict.json",
                ".conflicting.raw",
            ):
                actual_artifacts.update(
                    self._relative(path) for path in self._files(partition, suffix)
                )
            declared_artifacts = {
                str(item.get("relative_path"))
                for item in inventory
                if isinstance(item, Mapping)
            }
            if declared_artifacts != actual_artifacts or len(declared_artifacts) != len(inventory):
                raise RecorderRecoveryError(
                    "Final manifest inventory omits or duplicates custody artifacts."
                )
            expected_coverage = derive_coverage(
                records, conflicts=len(conflicts)
            ).to_mapping()
            if manifest.get("coverage") != expected_coverage:
                raise RecorderRecoveryError("Final manifest coverage does not rebuild.")
            source_finals_for_classification = self._source_final_records(partition)
            cutoff_text, cutoff_instant = self._frozen_finalization_cutoff(partition)
            source_final_closed_at = (
                parse_rfc3339(
                    source_finals_for_classification[0]["closed_at"], "closed_at"
                )
                if len(source_finals_for_classification) == 1
                else None
            )
            cutoff_satisfied = (
                source_final_closed_at is not None
                and source_final_closed_at >= cutoff_instant
            )
            expected_classification = (
                "INCOMPLETE_OFFLINE_REFERENCE"
                if (
                    len(source_finals_for_classification) != 1
                    or int(source_finals_for_classification[0]["pending_source_events"]) > 0
                    or int(source_finals_for_classification[0]["source_gap_count"]) > 0
                    or len(conflicts) > 0
                    or int(expected_coverage["unaccounted_outcome_slots"]) > 0
                    or not cutoff_satisfied
                )
                else "CUSTODY_SNAPSHOT_COMPLETE"
            )
            if manifest.get("custody_snapshot_classification") != expected_classification:
                raise RecorderRecoveryError("Final custody completeness classification does not rebuild.")
            owner_profile = manifest.get("science_custody_owner_profile")
            persisted_physical = (
                owner_profile.get("physical_primitive_evidence")
                if isinstance(owner_profile, Mapping)
                else None
            )
            current_physical = asdict(self._storage.owner_evidence)
            if (
                not isinstance(owner_profile, Mapping)
                or owner_profile.get("profile") != "SCIENCE_CUSTODY_OWNER_PROFILE_V1"
                or owner_profile.get("historical_physical_primitive_label")
                != "continuous-evidence-writer-owner-v1"
                or owner_profile.get("historical_label_is_runtime_ownership") is not False
                or owner_profile.get("continuous_runtime_owner") is not False
                or owner_profile.get("continuous_runtime_mutated") is not False
                or not isinstance(persisted_physical, Mapping)
                or set(persisted_physical) != set(current_physical)
                or any(
                    persisted_physical.get(field) != current_physical[field]
                    for field in (
                        "root_identity",
                        "topology_fingerprint",
                        "topology_version",
                        "lease_identity",
                        "lease_name",
                        "storage_profile",
                        "profile",
                    )
                )
            ):
                raise RecorderRecoveryError("Science custody owner profile is invalid.")
            expected_channel_heads = {}
            for channel in (
                "session",
                "discovery",
                "decision",
                "market",
                "health",
                "outcome",
            ):
                channel_state = self._channel_state(partition, channel)
                expected_channel_heads[channel] = {
                    "last_receipt_sha256": channel_state.last_receipt_sha256,
                    "record_count": len(channel_state.receipts),
                }
            if manifest.get("channel_heads") != expected_channel_heads:
                raise RecorderRecoveryError("Final manifest channel heads do not reconcile.")
            export_heads, export_counts = self._source_stream_summary(partition)
            if (
                manifest.get("source_stream_heads") != self._all_stream_heads(partition)
                or manifest.get("source_event_type_counts") != export_counts
            ):
                raise RecorderRecoveryError("Final manifest source heads/counts do not reconcile.")
            source_finals = self._source_final_records(partition)
            if len(source_finals) != 1:
                raise RecorderRecoveryError("Final custody manifest lacks one source FINAL.")
            source_final = source_finals[0]
            source_final_entry = self._record_index(partition).get(
                str(source_final["record_id"]["recorder_id"])
            )
            reconciliation = manifest.get("source_final_reconciliation")
            if (
                source_final_entry is None
                or manifest.get("source_final_record_id") != source_final["record_id"]
                or manifest.get("source_final_payload_sha256")
                != sha256_hex(source_final_entry[1])
                or not isinstance(reconciliation, Mapping)
                or reconciliation.get("reconciled") is not True
                or reconciliation.get("declared_heads_before_final")
                != source_final["source_stream_heads_before_final"]
                or reconciliation.get("declared_pending_source_events")
                != source_final["pending_source_events"]
                or reconciliation.get("declared_source_gap_count")
                != source_final["source_gap_count"]
                or reconciliation.get("declared_closed_at")
                != source_final["closed_at"]
                or reconciliation.get("frozen_finalization_cutoff") != cutoff_text
                or reconciliation.get("finalization_cutoff_satisfied")
                is not cutoff_satisfied
                or reconciliation.get("conflict_count") != len(conflicts)
                or reconciliation.get("verified_export_heads_after_final")
                != export_heads
            ):
                raise RecorderRecoveryError("Source FINAL reconciliation is invalid.")
            manifest_key_material = {
                "artifact_inventory": inventory,
                "channel_heads": expected_channel_heads,
                "session_id": session_id,
            }
            expected_manifest_key = sha256_hex(
                canonical_json_bytes(manifest_key_material)
            )
            if final_files[0].name != f"{expected_manifest_key}.final.json":
                raise RecorderRecoveryError("Final manifest filename identity is invalid.")
            sidecar, _sidecar_raw = self._complete_or_verify_final_sidecar(
                partition,
                final_files[0],
                manifest,
                manifest_raw,
                create_missing=False,
            )
            lines = sidecar.read_text(encoding="ascii").splitlines()
            expected: dict[str, str] = {}
            for line in lines:
                parts = line.split("  ", 1)
                if len(parts) != 2 or parts[1] in expected:
                    raise RecorderRecoveryError("Detached checksum line is malformed or duplicated.")
                expected[parts[1]] = parts[0]
            for item in inventory:
                if not isinstance(item, Mapping):
                    raise RecorderRecoveryError("Final manifest inventory item is malformed.")
                relative = str(item.get("relative_path", ""))
                path = self._storage.root / Path(relative)
                raw = path.read_bytes()
                if (
                    item.get("byte_length") != len(raw)
                    or item.get("sha256") != sha256_hex(raw)
                    or expected.get(relative) != sha256_hex(raw)
                ):
                    raise RecorderRecoveryError("Final inventory/checksum artifact does not verify.")
        return VerificationReport(
            session_id=str(session_id["recorder_id"]),
            partition_id=partition.as_posix(),
            source_count=source_count,
            payload_count=len(records),
            receipt_count=receipt_count,
            checkpoint_count=checkpoint_count,
            conflict_count=len(conflicts),
            final_manifest_present=bool(final_files),
            all_hashes_valid=True,
        )

    def recover(self) -> tuple[VerificationReport, ...]:
        """Rebuild safe cursors from immutable sources; never trusts wall-clock or mtime."""

        self._quarantine_partials_with_receipts()
        pending_by_stream: dict[
            tuple[str, str, str], list[tuple[int, int, str, bytes]]
        ] = {}
        for source_kind in ("export", "outcome"):
            for path in self._files(PurePath("sessions"), ".source.json"):
                relative = self._relative(path)
                if f"/sources/{source_kind}/" not in f"/{relative}":
                    continue
                raw = path.read_bytes()
                parsed = (
                    parse_export_envelope(raw)
                    if source_kind == "export"
                    else parse_outcome_attachment(raw)
                )
                if source_kind == "export":
                    phase = parsed.payload.get("manifest_phase")
                    if parsed.event_type == "SESSION_MANIFEST" and phase == "START":
                        event_priority = 0
                    elif parsed.event_type == "DISCOVERY_CYCLE":
                        event_priority = 1
                    elif parsed.event_type == "PROVIDER_HEALTH":
                        event_priority = 2
                    elif parsed.event_type == "MARKET_FACT":
                        event_priority = 3
                    elif parsed.event_type == "DECISION_FACT":
                        event_priority = 4
                    elif parsed.event_type == "SESSION_MANIFEST" and phase == "FINAL":
                        event_priority = 6
                    else:
                        event_priority = 5
                else:
                    event_priority = 5
                key = (
                    str(parsed.session_id["recorder_id"]),
                    source_kind,
                    parsed.stream_id,
                )
                pending_by_stream.setdefault(key, []).append(
                    (parsed.source_sequence, event_priority, parsed.source_event_id, raw)
                )
        for key, items in pending_by_stream.items():
            items.sort(key=lambda item: item[0])
            sequences = [item[0] for item in items]
            if sequences != list(range(1, len(items) + 1)):
                raise RecorderRecoveryError(
                    f"Persisted source stream is not contiguous from one: {key}."
                )
            event_ids = [item[2] for item in items]
            if len(event_ids) != len(set(event_ids)):
                raise RecorderRecoveryError(
                    f"Persisted source stream repeats a source event identity: {key}."
                )
        while any(pending_by_stream.values()):
            sessions_with_nonfinal_pending = {
                key[0]
                for key, items in pending_by_stream.items()
                if any(item[1] != 6 for item in items)
            }
            candidates = sorted(
                (
                    (items[0][1], key[0], key[1], key[2], items[0])
                    for key, items in pending_by_stream.items()
                    if items
                    and not (
                        items[0][1] == 6
                        and key[0] in sessions_with_nonfinal_pending
                    )
                ),
                key=lambda item: (item[0], item[1], item[2], item[3]),
            )
            progressed = False
            deferred: list[str] = []
            for _priority, _session, source_kind, stream_id, item in candidates:
                _sequence, _item_priority, event_id, raw = item
                try:
                    if source_kind == "export":
                        self.accept(raw)
                    else:
                        self.append_outcome(raw)
                except (RecorderConflictError, RecorderRecoveryError):
                    raise
                except (RecorderContractError, RecorderCustodyError) as exc:
                    deferred.append(f"{source_kind}:{stream_id}:{event_id}:{exc}")
                    continue
                pending_by_stream[(_session, source_kind, stream_id)].pop(0)
                progressed = True
            if not progressed:
                pending_inventory = [
                    f"{key[1]}:{key[2]}:{item[2]}:seq={item[0]}"
                    for key, items in sorted(pending_by_stream.items())
                    for item in items[:1]
                ]
                raise RecorderRecoveryError(
                    "Dependency-aware recovery made no progress; fail closed. "
                    f"pending={pending_inventory}; errors={deferred}"
                )
        starts = self._start_records()
        reports: list[VerificationReport] = []
        seen: set[str] = set()
        for _partition, start in starts:
            session = start["session_id"]
            recorder_id = str(session["recorder_id"])
            if recorder_id not in seen:
                reports.append(self.verify(session))
                seen.add(recorder_id)
        return tuple(reports)

    def finalize(
        self,
        session_id: Mapping[str, object],
        *,
        crash_phase: str | None = None,
    ) -> FinalizationResult:
        """Create one immutable FINAL manifest and detached checksum snapshot."""

        partition = self._locate_partition(session_id)
        if crash_phase not in {None, "after_manifest"}:
            raise RecorderCustodyError("Unknown finalization fault-injection phase.")
        existing = self._final_files(partition)
        if existing:
            manifest, raw = self._read_canonical(existing[0], "final manifest")
            sidecar, sidecar_raw = self._complete_or_verify_final_sidecar(
                partition,
                existing[0],
                manifest,
                raw,
                create_missing=True,
            )
            coverage = CoverageSummary(**manifest["coverage"])
            return FinalizationResult(
                status="IDEMPOTENT_ACK",
                custody_classification=str(manifest["custody_snapshot_classification"]),
                manifest_relative_path=self._relative(existing[0]),
                manifest_sha256=sha256_hex(raw),
                checksum_relative_path=self._relative(sidecar),
                checksum_sha256=sha256_hex(sidecar_raw),
                coverage=coverage,
            )
        report = self.verify(session_id)
        source_finals = self._source_final_records(partition)
        if len(source_finals) != 1:
            raise RecorderCustodyError(
                "Exactly one verified source FINAL manifest is required before custody finalization."
            )
        records = self._all_records(partition)
        coverage = derive_coverage(records, conflicts=report.conflict_count)
        artifact_paths: list[Path] = []
        for suffix in (
            ".source.json",
            ".payload.json",
            ".receipt.json",
            ".checkpoint.json",
            ".conflict.json",
            ".conflicting.raw",
        ):
            artifact_paths.extend(self._files(partition, suffix))
        unique_paths = sorted(set(artifact_paths), key=self._relative)
        inventory = [
            {
                "byte_length": path.stat().st_size,
                "relative_path": self._relative(path),
                "sha256": sha256_hex(path.read_bytes()),
            }
            for path in unique_paths
        ]
        channel_heads = {}
        for channel in ("session", "discovery", "decision", "market", "health", "outcome"):
            state = self._channel_state(partition, channel)
            channel_heads[channel] = {
                "last_receipt_sha256": state.last_receipt_sha256,
                "record_count": len(state.receipts),
            }
        finalized_at = self._capture_time()
        record_index = self._record_index(partition)
        source_final = source_finals[0]
        source_final_id = str(source_final["record_id"]["recorder_id"])
        source_final_entry = record_index.get(source_final_id)
        if source_final_entry is None:
            raise RecorderRecoveryError("Source FINAL payload is not in the accepted index.")
        export_heads, export_counts = self._source_stream_summary(partition)
        stream_heads = self._all_stream_heads(partition)
        cutoff_text, cutoff_instant = self._frozen_finalization_cutoff(partition)
        source_final_closed_at = parse_rfc3339(
            source_final["closed_at"], "closed_at"
        )
        cutoff_satisfied = source_final_closed_at >= cutoff_instant
        incomplete = any(
            (
                int(source_final["pending_source_events"]) > 0,
                int(source_final["source_gap_count"]) > 0,
                report.conflict_count > 0,
                coverage.unaccounted_outcome_slots > 0,
                not cutoff_satisfied,
            )
        )
        custody_classification = (
            "INCOMPLETE_OFFLINE_REFERENCE"
            if incomplete
            else "CUSTODY_SNAPSHOT_COMPLETE"
        )
        manifest = {
            "artifact_inventory": inventory,
            "authority": AUTHORITY,
            "base_canonical_sha": BASE_CANONICAL_SHA,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "channel_heads": channel_heads,
            "coverage": coverage.to_mapping(),
            "custody_snapshot_classification": custody_classification,
            "execution_authority": EXECUTION_AUTHORITY,
            "finalized_at": finalized_at,
            "live_capture_qualification": "NOT_PROVEN",
            "implementation_scope": "SCIENCE_CUSTODY_OFFLINE_REFERENCE_KERNEL_ONLY",
            "manifest_phase": "FINAL",
            "manifest_version": MANIFEST_VERSION,
            "partition_id": partition.as_posix(),
            "predecessor_directive": PREDECESSOR_DIRECTIVE,
            "predecessor_schema_sha256": PREDECESSOR_SCHEMA_SHA256,
            "predecessor_schema_version": PREDECESSOR_SCHEMA_VERSION,
            "predecessor_sidecar_sha256": PREDECESSOR_SIDECAR_SHA256,
            "producer_provider_evidence_classification": "OPAQUE_PRODUCER_ASSERTION_ONLY",
            "science_recorder_provider_contact_occurred": False,
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "source_root_identity": self.source_root_identity,
            "source_stream_heads": stream_heads,
            "source_event_type_counts": export_counts,
            "source_final_record_id": source_final["record_id"],
            "source_final_payload_sha256": sha256_hex(source_final_entry[1]),
            "source_final_reconciliation": {
                "conflict_count": report.conflict_count,
                "declared_closed_at": source_final["closed_at"],
                "declared_heads_before_final": source_final[
                    "source_stream_heads_before_final"
                ],
                "declared_pending_source_events": source_final[
                    "pending_source_events"
                ],
                "declared_source_gap_count": source_final["source_gap_count"],
                "finalization_cutoff_satisfied": cutoff_satisfied,
                "frozen_finalization_cutoff": cutoff_text,
                "reconciled": True,
                "verified_export_heads_after_final": export_heads,
            },
            "science_custody_owner_profile": {
                "continuous_runtime_mutated": False,
                "continuous_runtime_owner": False,
                "historical_physical_primitive_label": "continuous-evidence-writer-owner-v1",
                "historical_label_is_runtime_ownership": False,
                "physical_primitive_evidence": asdict(self._storage.owner_evidence),
                "profile": "SCIENCE_CUSTODY_OWNER_PROFILE_V1",
            },
            "post_final_addendum": {
                "acceptance_test": "AT-024",
                "claim": "NOT_CLAIMED",
                "status": "NOT_IMPLEMENTED",
            },
            "scope_limitations": [
                "NO_EXPORT_ROOT_READER_OR_WORKER",
                "NO_EXTERNAL_OVERLAP_SCAN",
                "NO_SERVICE_OR_SCHEDULER",
                "NO_NATURAL_PRODUCER_COMPATIBILITY_CLAIM",
                "EXTERNAL_RECORDER_DURABLE_ALLOCATED_IDENTITY_NOT_IMPLEMENTED",
                "FIXED_HASH_BUCKET_NOT_IMPLEMENTED",
                "AT_020_NOT_PROVEN",
                "POST_FINAL_ADDENDUM_NOT_IMPLEMENTED",
            ],
        }
        manifest_key = sha256_hex(
            canonical_json_bytes(
                {
                    "channel_heads": channel_heads,
                    "session_id": session_id,
                    "artifact_inventory": inventory,
                }
            )
        )
        manifest_path = partition / "manifests" / f"{manifest_key}.final.json"
        manifest_bytes = canonical_json_bytes(manifest)
        with self._storage.transaction():
            self._storage.atomic_create(manifest_path, manifest_bytes)
        if crash_phase == "after_manifest":
            raise SimulatedRecorderCrash(
                "Synthetic interruption after final manifest before detached checksum."
            )
        manifest_file = self._storage.root / Path(manifest_path)
        checksum_file, checksum_bytes = self._complete_or_verify_final_sidecar(
            partition,
            manifest_file,
            manifest,
            manifest_bytes,
            create_missing=True,
        )
        self.verify(session_id)
        return FinalizationResult(
            status="FINALIZED",
            custody_classification=custody_classification,
            manifest_relative_path=manifest_path.as_posix(),
            manifest_sha256=sha256_hex(manifest_bytes),
            checksum_relative_path=self._relative(checksum_file),
            checksum_sha256=sha256_hex(checksum_bytes),
            coverage=coverage,
        )


__all__ = [
    "AcceptanceResult",
    "FinalizationResult",
    "RecorderConflictError",
    "RecorderCustodyError",
    "RecorderRecoveryError",
    "SCIENCE_ELIGIBILITY_PROFILE",
    "SCIENCE_ELIGIBILITY_RECORD_VERSION",
    "SimulatedRecorderCrash",
    "StrategyScienceRecorder",
    "VerificationReport",
    "science_eligibility_sha256",
]
