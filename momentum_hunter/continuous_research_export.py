"""Offline Continuous-owned publication for the accepted Science V2 contract.

The publisher creates immutable ``ResearchExportEnvelopeV2`` bytes from facts
already known to the Continuous producer.  It has no provider, runtime, service,
scheduler, account, broker, position, order, Paper, Shadow, or execution
capability.  Science receipt and eligibility facts are deliberately absent.

Only files below ``published`` are externally visible.  Complete canonical bytes
are fsynced under ``staging`` and then hard-linked into ``published`` in one
atomic namespace operation.  Restart derives truth from published bytes rather
than trusting a mutable checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping
import os
import re
import secrets

from momentum_hunter.strategy_science_recorder.canonical import (
    CANONICALIZATION_VERSION,
    canonical_json_v1,
    owner_identity,
    parse_rfc3339,
    require_sha256,
    sha256_hex,
    strict_json_loads,
)
from momentum_hunter.strategy_science_recorder.contract import (
    AUTHORITY,
    EVENT_TYPES,
    EXECUTION_AUTHORITY,
    GENESIS_SHA256,
    HASH_ALGORITHM,
    HASH_UNIT,
    PREVIOUS_HASH_TARGET,
    REPAIRED_EXPORT_SCHEMA_VERSION,
    REPAIRED_SOURCE_CONTRACT,
    REPAIRED_SOURCE_CONTRACT_VERSION,
    SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
    SOURCE_SEQUENCE_SCOPE,
    RecorderContractError,
    ValidatedExportEnvelope,
    evidence_instant,
    parse_export_envelope_v2,
    require_identity,
    validate_start_manifest,
)


EXPORTER_PROFILE = "ARGUS_CONTINUOUS_RESEARCH_EXPORT_V2"
EXPORTER_VERSION = "ARGUS-CONTINUOUS-RESEARCH-EXPORT-002-v1"
CHECKPOINT_VERSION = 1
PUBLICATION_FILE = re.compile(
    r"(?P<ordinal>[0-9]{20})-(?P<stream>[0-9a-f]{16})-"
    r"(?P<sequence>[0-9]{20})\.json"
)
STAGING_FILE = re.compile(r"[0-9a-f]{64}\.json")


class ContinuousResearchExportError(ValueError):
    """Base fail-closed publication error."""


class ContinuousResearchExportConflict(ContinuousResearchExportError):
    """An immutable logical source identity was reused with different bytes."""


class ContinuousResearchExportRecoveryError(ContinuousResearchExportError):
    """Durable source bytes cannot be reconciled safely."""


class SimulatedPublicationCrash(RuntimeError):
    """Synthetic fault used only by offline crash-matrix tests."""


@dataclass(frozen=True)
class PublicationResult:
    status: str
    source_event_id: str
    stream_id: str
    source_sequence: int
    publication_ordinal: int
    raw_sha256: str
    relative_path: str
    raw_bytes: bytes


@dataclass(frozen=True)
class FinalizationResult:
    status: str
    publication: PublicationResult | None
    pending_source_events: int
    source_gap_count: int
    conflict_count: int


@dataclass(frozen=True)
class _Published:
    ordinal: int
    path: Path
    envelope: ValidatedExportEnvelope


def producer_identity(
    identity_kind: str,
    owner_namespace: str,
    owner_id: str,
    *,
    owner_schema_version: str = "1.0.0",
) -> dict[str, object]:
    """Wrap one producer-owned logical identity for the canonical boundary."""

    return owner_identity(
        identity_kind,
        owner_namespace,
        owner_id,
        owner_schema_version=owner_schema_version,
    )


def evidence_present(value: object, authority: str) -> dict[str, object]:
    if not isinstance(authority, str) or not authority:
        raise ContinuousResearchExportError("Evidence authority must be nonempty.")
    return {
        "authority": authority,
        "reason_code": "PRESENT",
        "state": "PRESENT",
        "value": value,
    }


def evidence_unresolved(
    authority: str,
    *,
    state: str = "UNKNOWN",
    reason_code: str = "AUTHORITATIVE_VALUE_UNRESOLVED",
) -> dict[str, object]:
    """Preserve an owner-known gap without manufacturing an instrument fact."""

    for label, value in (("authority", authority), ("state", state), ("reason_code", reason_code)):
        if not isinstance(value, str) or not value:
            raise ContinuousResearchExportError(f"{label} must be nonempty.")
    return {"authority": authority, "reason_code": reason_code, "state": state}


def time_evidence(role: str, timestamp: str, authority: str) -> dict[str, object]:
    """Create exact, non-normalizing producer time evidence."""

    parse_rfc3339(timestamp, "timestamp")
    if not isinstance(authority, str) or not authority:
        raise ContinuousResearchExportError("Time authority must be nonempty.")
    offset = "Z" if timestamp.endswith("Z") else timestamp[-6:]
    time_part = timestamp.split("T", 1)[1]
    without_offset = time_part[:-1] if timestamp.endswith("Z") else time_part[:-6]
    precision = (
        f"fractional-{len(without_offset.rsplit('.', 1)[1])}"
        if "." in without_offset
        else "second"
    )
    return {
        "authority": authority,
        "normalized_rfc3339": timestamp,
        "normalization_rule_version": "ARGUS_TIME_IDENTITY_V1",
        "precision": precision,
        "raw_value": timestamp,
        "reason_code": "PRESENT",
        "role": role,
        "state": "PRESENT",
        "timezone_or_offset": offset,
    }


def instrument_identity(
    *,
    symbol: Mapping[str, object],
    asset_type: Mapping[str, object],
    venue_or_exchange: Mapping[str, object],
    authoritative_security_id: Mapping[str, object],
    currency: Mapping[str, object] | None = None,
    provider_security_ids: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Bind exactly the instrument facts the producer owns, including gaps."""

    material: dict[str, object] = {
        "asset_type": dict(asset_type),
        "authoritative_security_id": dict(authoritative_security_id),
        "symbol": dict(symbol),
        "venue_or_exchange": dict(venue_or_exchange),
    }
    if currency is not None:
        material["currency"] = dict(currency)
    ids = [dict(item) for item in provider_security_ids]
    if ids:
        material["provider_security_ids"] = ids
    material["instrument_identity_fingerprint_sha256"] = sha256_hex(
        canonical_json_v1(material)
    )
    return material


class _DirectoryLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: object | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise ContinuousResearchExportError(
                "Another writer owns this research-export root."
            ) from exc
        self.handle = handle

    def release(self) -> None:
        handle = self.handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self.handle = None


class ContinuousResearchExporterV2:
    """Single-writer, offline publisher for canonical V2 source envelopes."""

    def __init__(
        self,
        root: Path,
        *,
        session_id: Mapping[str, object],
        source_owner_identity: str,
        source_interface_identity: str,
        source_root_identity: str,
        crash_hook: Callable[[str], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.published_root = self.root / "published"
        self.staging_root = self.root / "staging"
        self.conflict_root = self.root / "conflicts"
        self.checkpoint_root = self.root / "checkpoint"
        self.metadata_path = self.root / "publication-identity.json"
        self.checkpoint_path = self.checkpoint_root / "state.json"
        self.lock = _DirectoryLock(self.root / ".writer.lock")
        self.crash_hook = crash_hook
        self.closed = False
        self.incomplete_finalization: object = False
        self.session_id = dict(session_id)
        self.source_owner_identity = self._text(
            source_owner_identity, "source_owner_identity"
        )
        self.source_interface_identity = self._text(
            source_interface_identity, "source_interface_identity"
        )
        try:
            require_identity(
                self.session_id,
                "session_id",
                kinds=frozenset({"SESSION_ID"}),
            )
            require_sha256(source_root_identity, "source_root_identity")
        except (RecorderContractError, ValueError) as exc:
            raise ContinuousResearchExportError(str(exc)) from exc
        self.source_root_identity = source_root_identity
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock.acquire()
        try:
            for path in (
                self.published_root,
                self.staging_root,
                self.conflict_root,
                self.checkpoint_root,
            ):
                path.mkdir(parents=True, exist_ok=True)
            self._bind_metadata()
            self._load_checkpoint_disposition()
            self._recover_staging()
            self._write_checkpoint(incomplete=None)
        except BaseException:
            self.lock.release()
            raise

    def __enter__(self) -> "ContinuousResearchExporterV2":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @staticmethod
    def _text(value: object, label: str) -> str:
        if not isinstance(value, str) or not value:
            raise ContinuousResearchExportError(f"{label} must be nonempty text.")
        return value

    def _ensure_open(self) -> None:
        if self.closed:
            raise ContinuousResearchExportError("Exporter is closed.")

    def _invoke(self, phase: str) -> None:
        if self.crash_hook is not None:
            self.crash_hook(phase)

    def _metadata(self) -> dict[str, object]:
        return {
            "authority": AUTHORITY,
            "execution_authority": EXECUTION_AUTHORITY,
            "exporter_profile": EXPORTER_PROFILE,
            "exporter_version": EXPORTER_VERSION,
            "schema_version": REPAIRED_EXPORT_SCHEMA_VERSION,
            "session_id": self.session_id,
            "source_contract": REPAIRED_SOURCE_CONTRACT,
            "source_contract_version": REPAIRED_SOURCE_CONTRACT_VERSION,
            "source_interface_identity": self.source_interface_identity,
            "source_owner_identity": self.source_owner_identity,
            "source_root_identity": self.source_root_identity,
        }

    def _bind_metadata(self) -> None:
        raw = canonical_json_v1(self._metadata())
        self._write_once(self.metadata_path, raw)

    def _load_checkpoint_disposition(self) -> None:
        if not self.checkpoint_path.exists():
            return
        try:
            value = strict_json_loads(self.checkpoint_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise ContinuousResearchExportRecoveryError(
                "Exporter checkpoint is unreadable or noncanonical."
            ) from exc
        if (
            value.get("checkpoint_version") != CHECKPOINT_VERSION
            or value.get("profile") != EXPORTER_PROFILE
            or value.get("session_id") != self.session_id
            or value.get("metadata_sha256")
            != sha256_hex(canonical_json_v1(self._metadata()))
        ):
            raise ContinuousResearchExportRecoveryError(
                "Exporter checkpoint identity is inconsistent."
            )
        self.incomplete_finalization = value.get("incomplete_finalization", False)

    @staticmethod
    def _write_once(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
        except FileExistsError:
            if path.read_bytes() != raw:
                raise ContinuousResearchExportConflict(
                    f"Write-once path contains conflicting bytes: {path.name}."
                )

    @staticmethod
    def _atomic_replace(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    @staticmethod
    def _stream_token(stream_id: str) -> str:
        return sha256_hex(canonical_json_v1({"stream_id": stream_id}))[:16]

    def _published_path(
        self, ordinal: int, stream_id: str, source_sequence: int
    ) -> Path:
        return self.published_root / (
            f"{ordinal:020d}-{self._stream_token(stream_id)}-"
            f"{source_sequence:020d}.json"
        )

    def _validate_descriptor(self, envelope: ValidatedExportEnvelope) -> None:
        if dict(envelope.session_id) != self.session_id:
            raise ContinuousResearchExportRecoveryError(
                "Published envelope belongs to another session."
            )
        if envelope.source_owner_identity != self.source_owner_identity:
            raise ContinuousResearchExportRecoveryError(
                "Published envelope has another source owner."
            )
        if envelope.source_interface_identity != self.source_interface_identity:
            raise ContinuousResearchExportRecoveryError(
                "Published envelope has another source interface."
            )
        if envelope.event_type == "SESSION_MANIFEST":
            phase = envelope.payload.get("manifest_phase")
            if phase == "START":
                validate_start_manifest(
                    envelope.payload,
                    session_id=self.session_id,
                    source_root_identity=self.source_root_identity,
                )
            elif phase == "FINAL" and envelope.payload.get(
                "source_root_identity"
            ) != self.source_root_identity:
                raise ContinuousResearchExportRecoveryError(
                    "FINAL source root identity differs from publication identity."
                )

    def _scan_published(self) -> tuple[_Published, ...]:
        records: list[_Published] = []
        for path in sorted(self.published_root.iterdir(), key=lambda item: item.name):
            if not path.is_file() or PUBLICATION_FILE.fullmatch(path.name) is None:
                raise ContinuousResearchExportRecoveryError(
                    "Published namespace contains an unrecognized object."
                )
            match = PUBLICATION_FILE.fullmatch(path.name)
            assert match is not None
            try:
                envelope = parse_export_envelope_v2(path.read_bytes())
                self._validate_descriptor(envelope)
            except (OSError, RecorderContractError, ValueError) as exc:
                raise ContinuousResearchExportRecoveryError(
                    f"Published envelope does not verify: {path.name}."
                ) from exc
            ordinal = int(match.group("ordinal"))
            if match.group("stream") != self._stream_token(envelope.stream_id):
                raise ContinuousResearchExportRecoveryError(
                    "Published filename does not bind its stream identity."
                )
            if int(match.group("sequence")) != envelope.source_sequence:
                raise ContinuousResearchExportRecoveryError(
                    "Published filename does not bind its source sequence."
                )
            records.append(_Published(ordinal, path, envelope))
        records.sort(key=lambda item: item.ordinal)
        if [item.ordinal for item in records] != list(range(1, len(records) + 1)):
            raise ContinuousResearchExportRecoveryError(
                "Publication delivery ordinals are not contiguous from one."
            )
        by_stream: dict[str, list[_Published]] = {}
        by_event: dict[str, _Published] = {}
        starts: list[_Published] = []
        finals: list[_Published] = []
        for item in records:
            prior = by_event.get(item.envelope.source_event_id)
            if prior is not None:
                raise ContinuousResearchExportRecoveryError(
                    "A source event identity appears more than once."
                )
            by_event[item.envelope.source_event_id] = item
            by_stream.setdefault(item.envelope.stream_id, []).append(item)
            if item.envelope.event_type == "SESSION_MANIFEST":
                phase = item.envelope.payload.get("manifest_phase")
                if phase == "START":
                    starts.append(item)
                elif phase == "FINAL":
                    finals.append(item)
        for stream_id, items in by_stream.items():
            expected_previous = GENESIS_SHA256
            for expected_sequence, item in enumerate(items, start=1):
                if item.envelope.source_sequence != expected_sequence:
                    raise ContinuousResearchExportRecoveryError(
                        f"Stream {stream_id} has a sequence gap or reorder."
                    )
                if item.envelope.previous_record_sha256 != expected_previous:
                    raise ContinuousResearchExportRecoveryError(
                        f"Stream {stream_id} previous-envelope chain is invalid."
                    )
                expected_previous = item.envelope.raw_sha256
        if records:
            if len(starts) != 1 or starts[0].ordinal != 1:
                raise ContinuousResearchExportRecoveryError(
                    "Exactly one START must be the first visible publication."
                )
        if len(finals) > 1 or (finals and finals[0].ordinal != len(records)):
            raise ContinuousResearchExportRecoveryError(
                "FINAL must be unique and the last visible publication."
            )
        if finals:
            self._verify_final(finals[0], tuple(records[:-1]))
        return tuple(records)

    @staticmethod
    def _counts(records: Iterable[_Published]) -> dict[str, int]:
        counts = {event_type: 0 for event_type in sorted(EVENT_TYPES)}
        for item in records:
            counts[item.envelope.event_type] += 1
        return counts

    @staticmethod
    def _heads(records: Iterable[_Published]) -> list[dict[str, object]]:
        heads: dict[str, _Published] = {}
        for item in records:
            heads[item.envelope.stream_id] = item
        return [
            {
                "last_source_envelope_sha256": item.envelope.raw_sha256,
                "last_source_sequence": item.envelope.source_sequence,
                "stream_id": stream_id,
            }
            for stream_id, item in sorted(heads.items())
        ]

    def _verify_final(
        self, final: _Published, before_final: tuple[_Published, ...]
    ) -> None:
        payload = final.envelope.payload
        if payload.get("session_id") != self.session_id:
            raise ContinuousResearchExportRecoveryError(
                "FINAL session identity is inconsistent."
            )
        if payload.get("source_event_type_counts_before_final") != self._counts(
            before_final
        ):
            raise ContinuousResearchExportRecoveryError(
                "FINAL event counts do not bind prior immutable publications."
            )
        if payload.get("source_stream_heads_before_final") != self._heads(
            before_final
        ):
            raise ContinuousResearchExportRecoveryError(
                "FINAL stream heads do not bind prior immutable publications."
            )
        if any(
            int(payload.get(field, -1)) != 0
            for field in ("conflict_count", "pending_source_events", "source_gap_count")
        ):
            raise ContinuousResearchExportRecoveryError(
                "This exporter publishes FINAL only for proven complete sessions."
            )

    def _recover_staging(self) -> None:
        stages = sorted(self.staging_root.iterdir(), key=lambda item: item.name)
        if len(stages) > 1:
            raise ContinuousResearchExportRecoveryError(
                "More than one staged publication exists; ordering is ambiguous."
            )
        if not stages:
            self._scan_published()
            return
        stage = stages[0]
        if not stage.is_file() or STAGING_FILE.fullmatch(stage.name) is None:
            raise ContinuousResearchExportRecoveryError(
                "Staging namespace contains an unrecognized object."
            )
        raw = stage.read_bytes()
        try:
            envelope = parse_export_envelope_v2(raw)
            self._validate_descriptor(envelope)
        except (OSError, RecorderContractError, ValueError) as exc:
            raise ContinuousResearchExportRecoveryError(
                "Staged publication does not verify."
            ) from exc
        if stage.stem != envelope.source_event_fingerprint_sha256:
            raise ContinuousResearchExportRecoveryError(
                "Staged filename does not bind the source event identity."
            )
        records = self._scan_published()
        existing = next(
            (
                item
                for item in records
                if item.envelope.source_event_id == envelope.source_event_id
            ),
            None,
        )
        if existing is not None:
            if existing.envelope.raw_bytes != raw:
                raise ContinuousResearchExportConflict(
                    "Staged source identity conflicts with published bytes."
                )
            stage.unlink()
            return
        if records and records[-1].envelope.event_type == "SESSION_MANIFEST" and records[
            -1
        ].envelope.payload.get("manifest_phase") == "FINAL":
            raise ContinuousResearchExportRecoveryError(
                "A nonpublished stage remains after FINAL."
            )
        expected_sequence, expected_previous = self._next_stream(records, envelope.stream_id)
        if (
            envelope.source_sequence != expected_sequence
            or envelope.previous_record_sha256 != expected_previous
        ):
            raise ContinuousResearchExportRecoveryError(
                "Staged publication no longer matches its durable stream head."
            )
        if envelope.event_type != "SESSION_MANIFEST" or envelope.payload.get(
            "manifest_phase"
        ) != "START":
            if not records:
                raise ContinuousResearchExportRecoveryError(
                    "Ordinary staged publication has no durable START."
                )
            self._validate_dependencies(envelope.event_type, envelope.payload, records)
        target = self._published_path(
            len(records) + 1, envelope.stream_id, envelope.source_sequence
        )
        self._atomic_publish(stage, target, raw)
        self._scan_published()

    @staticmethod
    def _next_stream(
        records: Iterable[_Published], stream_id: str
    ) -> tuple[int, str]:
        items = [item for item in records if item.envelope.stream_id == stream_id]
        if not items:
            return 1, GENESIS_SHA256
        last = items[-1]
        return last.envelope.source_sequence + 1, last.envelope.raw_sha256

    @staticmethod
    def _atomic_publish(stage: Path, target: Path, raw: bytes) -> None:
        try:
            os.link(stage, target)
        except FileExistsError:
            if target.read_bytes() != raw:
                raise ContinuousResearchExportConflict(
                    "Publication target already contains conflicting bytes."
                )
        except OSError as exc:
            raise ContinuousResearchExportRecoveryError(
                "Atomic publication link could not be created."
            ) from exc
        stage.unlink(missing_ok=True)

    def _conflict_count(self) -> int:
        files = list(self.conflict_root.glob("*.json"))
        if any(not item.is_file() for item in files):
            raise ContinuousResearchExportRecoveryError(
                "Conflict namespace contains an invalid object."
            )
        return len(files)

    def _record_conflict(
        self,
        *,
        source_event_id: str,
        accepted_sha256: str,
        conflicting_sha256: str,
    ) -> None:
        identity = sha256_hex(
            canonical_json_v1(
                {
                    "accepted_sha256": accepted_sha256,
                    "conflicting_sha256": conflicting_sha256,
                    "source_event_id": source_event_id,
                }
            )
        )
        payload = {
            "accepted_sha256": accepted_sha256,
            "authority": AUTHORITY,
            "conflicting_sha256": conflicting_sha256,
            "execution_authority": EXECUTION_AUTHORITY,
            "reason_code": "SOURCE_EVENT_IDENTITY_REUSED_WITH_CONFLICTING_BYTES",
            "source_event_id": source_event_id,
        }
        self._write_once(self.conflict_root / f"{identity}.json", canonical_json_v1(payload))
        self._write_checkpoint(incomplete="CONFLICT_RECORDED")

    @staticmethod
    def _identity_key(value: object) -> tuple[str, str, str, str] | None:
        if not isinstance(value, Mapping):
            return None
        fields = (
            value.get("identity_kind"),
            value.get("owner_namespace"),
            value.get("owner_schema_version"),
            value.get("recorder_id"),
        )
        if all(isinstance(field, str) and field for field in fields):
            return (str(fields[0]), str(fields[1]), str(fields[2]), str(fields[3]))
        return None

    @classmethod
    def _published_identities(
        cls, records: Iterable[_Published]
    ) -> dict[tuple[str, str, str, str], object]:
        identities: dict[tuple[str, str, str, str], object] = {}

        def walk(value: object) -> None:
            if isinstance(value, Mapping):
                key = cls._identity_key(value)
                if key is not None:
                    identities[key] = value
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        for item in records:
            walk(item.envelope.payload)
        return identities

    def _validate_dependencies(
        self,
        event_type: str,
        payload: Mapping[str, object],
        records: Iterable[_Published],
    ) -> None:
        identities = self._published_identities(records)
        if event_type == "DECISION_FACT":
            decision = payload.get("decision_event")
            if not isinstance(decision, Mapping):
                return
            observation = self._identity_key(decision.get("observation_id"))
            if observation is None or observation not in identities:
                raise ContinuousResearchExportError(
                    "Decision publication requires its producer-published observation."
                )
            for ref in decision.get("known_at_evidence_refs", []):
                if not isinstance(ref, Mapping):
                    continue
                record_id = self._identity_key(ref.get("record_id"))
                if record_id is None or record_id not in identities:
                    raise ContinuousResearchExportError(
                        "Decision known-at dependency is not producer-published."
                    )
        elif event_type == "MARKET_FACT":
            market = payload.get("market_snapshot")
            if not isinstance(market, Mapping):
                return
            for field in ("observation_id", "decision_id"):
                evidence = market.get(field)
                if not isinstance(evidence, Mapping) or evidence.get("state") != "PRESENT":
                    continue
                record_id = self._identity_key(evidence.get("value"))
                if record_id is None or record_id not in identities:
                    raise ContinuousResearchExportError(
                        f"Market publication requires its producer-published {field}."
                    )

    @staticmethod
    def _semantic_clocks(
        event_type: str,
        payload: Mapping[str, object],
        emitted_at: str,
        start_event_time: str | None,
        start_effective_known_at: str | None,
    ) -> tuple[str, str, str]:
        parse_rfc3339(emitted_at, "emitted_at")
        if event_type == "DISCOVERY_CYCLE":
            cycle = payload["discovery_cycle"]
            event_time = str(cycle["discovery_time"]["normalized_rfc3339"])
            effective = str(cycle["provider_received_at"]["normalized_rfc3339"])
        elif event_type == "DECISION_FACT":
            decision = payload["decision_event"]
            event_time = str(decision["decision_time"]["normalized_rfc3339"])
            effective = str(decision["decision_cutoff"]["normalized_rfc3339"])
        elif event_type == "MARKET_FACT":
            market = payload["market_snapshot"]
            event_time = str(market["source_event_time"]["normalized_rfc3339"])
            known = market["provider_known_at"]
            effective_source = (
                known if known.get("state") == "PRESENT" else market["provider_received_at"]
            )
            effective = str(effective_source["normalized_rfc3339"])
        elif event_type == "PROVIDER_HEALTH":
            health = payload["provider_health_event"]
            event_time = str(health["source_event_time"]["normalized_rfc3339"])
            effective = str(health["provider_received_at"]["normalized_rfc3339"])
        elif event_type == "SESSION_MANIFEST" and payload.get("manifest_phase") == "FINAL":
            event_time = str(payload["closed_at"])
            effective = event_time
        elif event_type == "SESSION_MANIFEST" and payload.get("manifest_phase") == "START":
            event_time = start_event_time or emitted_at
            effective = start_effective_known_at or event_time
        else:
            raise ContinuousResearchExportError("Unsupported publication event type.")
        parse_rfc3339(event_time, "event_time")
        parse_rfc3339(effective, "effective_known_at")
        return event_time, effective, emitted_at

    def _build_raw(
        self,
        *,
        event_type: str,
        payload: Mapping[str, object],
        stream_id: str,
        source_event_id: str,
        source_sequence: int,
        previous_record_sha256: str,
        emitted_at: str,
        start_event_time: str | None = None,
        start_effective_known_at: str | None = None,
    ) -> bytes:
        event_time, effective, emitted = self._semantic_clocks(
            event_type,
            payload,
            emitted_at,
            start_event_time,
            start_effective_known_at,
        )
        event_fingerprint = sha256_hex(
            canonical_json_v1(
                {
                    "event_type": event_type,
                    "session_id": self.session_id,
                    "source_event_id": source_event_id,
                    "source_owner_identity": self.source_owner_identity,
                    "stream_id": stream_id,
                }
            )
        )
        frozen_payload = dict(payload)
        envelope = {
            "authority": AUTHORITY,
            "canonicalization_version": CANONICALIZATION_VERSION,
            "effective_known_at": effective,
            "emitted_at": emitted,
            "event_time": event_time,
            "event_type": event_type,
            "execution_authority": EXECUTION_AUTHORITY,
            "hash_algorithm": HASH_ALGORITHM,
            "hash_unit": HASH_UNIT,
            "offline_reference_profile": SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
            "payload": frozen_payload,
            "payload_sha256": sha256_hex(canonical_json_v1(frozen_payload)),
            "previous_record_hash_target": PREVIOUS_HASH_TARGET,
            "previous_record_sha256": previous_record_sha256,
            "schema_version": REPAIRED_EXPORT_SCHEMA_VERSION,
            "session_id": self.session_id,
            "source_contract": REPAIRED_SOURCE_CONTRACT,
            "source_contract_version": REPAIRED_SOURCE_CONTRACT_VERSION,
            "source_event_fingerprint_sha256": event_fingerprint,
            "source_event_id": source_event_id,
            "source_interface_identity": self.source_interface_identity,
            "source_owner_identity": self.source_owner_identity,
            "source_sequence": source_sequence,
            "source_sequence_scope": SOURCE_SEQUENCE_SCOPE,
            "stream_id": stream_id,
        }
        raw = canonical_json_v1(envelope)
        try:
            parsed = parse_export_envelope_v2(raw)
            self._validate_descriptor(parsed)
        except (RecorderContractError, ValueError) as exc:
            raise ContinuousResearchExportError(str(exc)) from exc
        return raw

    def _result(self, item: _Published, *, status: str) -> PublicationResult:
        return PublicationResult(
            status=status,
            source_event_id=item.envelope.source_event_id,
            stream_id=item.envelope.stream_id,
            source_sequence=item.envelope.source_sequence,
            publication_ordinal=item.ordinal,
            raw_sha256=item.envelope.raw_sha256,
            relative_path=item.path.relative_to(self.root).as_posix(),
            raw_bytes=item.envelope.raw_bytes,
        )

    def _publish(
        self,
        *,
        event_type: str,
        payload: Mapping[str, object],
        stream_id: str,
        source_event_id: str,
        emitted_at: str,
        start_event_time: str | None = None,
        start_effective_known_at: str | None = None,
    ) -> PublicationResult:
        self._ensure_open()
        stream_id = self._text(stream_id, "stream_id")
        source_event_id = self._text(source_event_id, "source_event_id")
        records = self._scan_published()
        terminal = bool(
            records
            and records[-1].envelope.event_type == "SESSION_MANIFEST"
            and records[-1].envelope.payload.get("manifest_phase") == "FINAL"
        )
        existing = next(
            (
                item
                for item in records
                if item.envelope.source_event_id == source_event_id
            ),
            None,
        )
        if existing is not None:
            expected = self._build_raw(
                event_type=event_type,
                payload=payload,
                stream_id=stream_id,
                source_event_id=source_event_id,
                source_sequence=existing.envelope.source_sequence,
                previous_record_sha256=existing.envelope.previous_record_sha256,
                emitted_at=emitted_at,
                start_event_time=start_event_time,
                start_effective_known_at=start_effective_known_at,
            )
            if expected == existing.envelope.raw_bytes:
                return self._result(existing, status="IDEMPOTENT_ACK")
            self._record_conflict(
                source_event_id=source_event_id,
                accepted_sha256=existing.envelope.raw_sha256,
                conflicting_sha256=sha256_hex(expected),
            )
            raise ContinuousResearchExportConflict(
                "Source event identity was reused with conflicting bytes."
            )
        if terminal:
            raise ContinuousResearchExportError("FINAL prohibits later publication.")
        phase = payload.get("manifest_phase") if event_type == "SESSION_MANIFEST" else None
        is_start = event_type == "SESSION_MANIFEST" and phase == "START"
        is_final = event_type == "SESSION_MANIFEST" and phase == "FINAL"
        if is_start:
            if records:
                raise ContinuousResearchExportError(
                    "START must be the first publication and cannot be reconstructed late."
                )
        elif not records:
            raise ContinuousResearchExportError(
                "START must be published before the first session event."
            )
        if not is_start and not is_final:
            self._validate_dependencies(event_type, payload, records)
        sequence, previous = self._next_stream(records, stream_id)
        raw = self._build_raw(
            event_type=event_type,
            payload=payload,
            stream_id=stream_id,
            source_event_id=source_event_id,
            source_sequence=sequence,
            previous_record_sha256=previous,
            emitted_at=emitted_at,
            start_event_time=start_event_time,
            start_effective_known_at=start_effective_known_at,
        )
        parsed = parse_export_envelope_v2(raw)
        stage = self.staging_root / f"{parsed.source_event_fingerprint_sha256}.json"
        if is_start:
            self._invoke("before_start_commit")
        elif is_final:
            self._invoke("before_final")
        self._write_once(stage, raw)
        if is_start:
            self._invoke("after_start_raw_before_publication")
        elif is_final:
            self._invoke("after_final_raw_before_publication")
        else:
            self._invoke("after_event_raw_before_publication")
        target = self._published_path(len(records) + 1, stream_id, sequence)
        self._atomic_publish(stage, target, raw)
        if is_start:
            self._invoke("after_start_publication_before_checkpoint")
        elif is_final:
            self._invoke("after_final_publication_before_checkpoint")
        else:
            self._invoke("after_event_publication_before_checkpoint")
        self._write_checkpoint(incomplete=None)
        verified = self._scan_published()
        item = verified[-1]
        if item.envelope.raw_bytes != raw:
            raise ContinuousResearchExportRecoveryError(
                "New publication did not verify after checkpoint."
            )
        if not is_start and not is_final:
            self._invoke("after_event_checkpoint")
        return self._result(item, status="PUBLISHED")

    def start(
        self,
        payload: Mapping[str, object],
        *,
        stream_id: str,
        source_event_id: str,
        emitted_at: str,
        event_time: str | None = None,
        effective_known_at: str | None = None,
    ) -> PublicationResult:
        """Publish the required producer-owned START before every other event."""

        try:
            validate_start_manifest(
                payload,
                session_id=self.session_id,
                source_root_identity=self.source_root_identity,
            )
        except (RecorderContractError, ValueError) as exc:
            raise ContinuousResearchExportError(str(exc)) from exc
        return self._publish(
            event_type="SESSION_MANIFEST",
            payload=payload,
            stream_id=stream_id,
            source_event_id=source_event_id,
            emitted_at=emitted_at,
            start_event_time=event_time,
            start_effective_known_at=effective_known_at,
        )

    def publish_event(
        self,
        event_type: str,
        payload: Mapping[str, object],
        *,
        stream_id: str,
        source_event_id: str,
        emitted_at: str,
    ) -> PublicationResult:
        """Publish one ordinary producer event through the exact V2 parser."""

        if event_type not in EVENT_TYPES or event_type == "SESSION_MANIFEST":
            raise ContinuousResearchExportError(
                "publish_event accepts only ordinary canonical V2 event families."
            )
        return self._publish(
            event_type=event_type,
            payload=payload,
            stream_id=stream_id,
            source_event_id=source_event_id,
            emitted_at=emitted_at,
        )

    def finalize(
        self,
        *,
        stream_id: str,
        source_event_id: str,
        closed_at: str,
        close_reason: str,
        terminal_proven: bool,
        pending_source_events: int = 0,
        source_gap_count: int = 0,
        upstream_conflict_count: int = 0,
    ) -> FinalizationResult:
        """Publish truthful FINAL or retain an explicit incomplete checkpoint."""

        self._ensure_open()
        for label, value in (
            ("pending_source_events", pending_source_events),
            ("source_gap_count", source_gap_count),
            ("upstream_conflict_count", upstream_conflict_count),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContinuousResearchExportError(f"{label} must be an integer >= 0.")
        if not isinstance(terminal_proven, bool):
            raise ContinuousResearchExportError("terminal_proven must be boolean.")
        close_reason = self._text(close_reason, "close_reason")
        parse_rfc3339(closed_at, "closed_at")
        records = self._scan_published()
        existing = next(
            (
                item
                for item in records
                if item.envelope.event_type == "SESSION_MANIFEST"
                and item.envelope.payload.get("manifest_phase") == "FINAL"
            ),
            None,
        )
        conflicts = self._conflict_count() + upstream_conflict_count
        if existing is not None and (
            not terminal_proven
            or pending_source_events
            or source_gap_count
            or conflicts
        ):
            raise ContinuousResearchExportConflict(
                "Published FINAL is immutable and cannot be downgraded to incomplete."
            )
        if (
            not terminal_proven
            or pending_source_events
            or source_gap_count
            or conflicts
        ):
            self._write_checkpoint(
                incomplete={
                    "close_reason": close_reason,
                    "closed_at": closed_at,
                    "conflict_count": conflicts,
                    "pending_source_events": pending_source_events,
                    "source_gap_count": source_gap_count,
                    "terminal_proven": terminal_proven,
                }
            )
            return FinalizationResult(
                status="INCOMPLETE_NO_FINAL",
                publication=None,
                pending_source_events=pending_source_events,
                source_gap_count=source_gap_count,
                conflict_count=conflicts,
            )
        before_final = records[:-1] if existing is not None else records
        if not before_final:
            raise ContinuousResearchExportError("Cannot finalize a session without START.")
        latest_source_instant = max(
            max(
                parse_rfc3339(item.envelope.event_time, "event_time"),
                parse_rfc3339(item.envelope.effective_known_at, "effective_known_at"),
                parse_rfc3339(item.envelope.emitted_at, "emitted_at"),
            )
            for item in before_final
        )
        closed_instant = parse_rfc3339(closed_at, "closed_at")
        if closed_instant < latest_source_instant:
            raise ContinuousResearchExportError(
                "FINAL closed_at cannot precede a producer-published fact."
            )
        start = before_final[0].envelope.payload
        cutoff = start["outcome_followup_policy"]["retry_and_finalization_cutoff"][
            "finalization_cutoff"
        ]
        if closed_instant < parse_rfc3339(cutoff, "finalization_cutoff"):
            raise ContinuousResearchExportError(
                "FINAL cannot precede the producer-frozen finalization cutoff."
            )
        payload = {
            "close_reason": close_reason,
            "closed_at": closed_at,
            "conflict_count": 0,
            "manifest_phase": "FINAL",
            "pending_source_events": 0,
            "session_id": self.session_id,
            "source_event_type_counts_before_final": self._counts(before_final),
            "source_gap_count": 0,
            "source_root_identity": self.source_root_identity,
            "source_stream_heads_before_final": self._heads(before_final),
        }
        publication = self._publish(
            event_type="SESSION_MANIFEST",
            payload=payload,
            stream_id=stream_id,
            source_event_id=source_event_id,
            emitted_at=closed_at,
        )
        self.incomplete_finalization = False
        self._write_checkpoint(incomplete=False)
        return FinalizationResult(
            status=(
                "IDEMPOTENT_ACK"
                if publication.status == "IDEMPOTENT_ACK"
                else "FINAL_PUBLISHED"
            ),
            publication=publication,
            pending_source_events=0,
            source_gap_count=0,
            conflict_count=0,
        )

    def _write_checkpoint(self, incomplete: object) -> None:
        records = self._scan_published()
        if incomplete is not None:
            self.incomplete_finalization = incomplete
        payload = {
            "checkpoint_version": CHECKPOINT_VERSION,
            "conflict_count": self._conflict_count(),
            "delivery_order_semantic": "PUBLICATION_DELIVERY_ONLY_NOT_UNIVERSAL_SOURCE_CHRONOLOGY",
            "event_type_counts": self._counts(records),
            "incomplete_finalization": self.incomplete_finalization,
            "last_publication_ordinal": len(records),
            "metadata_sha256": sha256_hex(canonical_json_v1(self._metadata())),
            "profile": EXPORTER_PROFILE,
            "session_id": self.session_id,
            "stream_heads": self._heads(records),
            "terminal": bool(
                records
                and records[-1].envelope.event_type == "SESSION_MANIFEST"
                and records[-1].envelope.payload.get("manifest_phase") == "FINAL"
            ),
        }
        self._atomic_replace(self.checkpoint_path, canonical_json_v1(payload))

    def published(self) -> tuple[PublicationResult, ...]:
        """Return visible immutable V2 envelopes in delivery order."""

        self._ensure_open()
        return tuple(self._result(item, status="PUBLISHED") for item in self._scan_published())

    def close(self) -> None:
        if self.closed:
            return
        try:
            self._write_checkpoint(incomplete=None)
        finally:
            self.closed = True
            self.lock.release()


__all__ = [
    "ContinuousResearchExportConflict",
    "ContinuousResearchExportError",
    "ContinuousResearchExportRecoveryError",
    "ContinuousResearchExporterV2",
    "EXPORTER_PROFILE",
    "EXPORTER_VERSION",
    "FinalizationResult",
    "PublicationResult",
    "SimulatedPublicationCrash",
    "evidence_present",
    "evidence_unresolved",
    "instrument_identity",
    "producer_identity",
    "time_evidence",
]
