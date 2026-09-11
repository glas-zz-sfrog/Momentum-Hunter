"""Dormant, explicit-input continuous Science custody over the accepted V2 reader.

One source root/session is the canonical reader's unit. Call ``poll`` repeatedly;
there is no worker, provider, scheduler or runtime callback. First-arrival bytes
and clocks live in a separate immutable Science ledger. Canonical eligibility
continues to use the recorder's actual admission clock, never the earlier arrival.
All windows are half open. Missing lateness policy means UNKNOWN.
"""

from __future__ import annotations

import base64
from collections import Counter
from pathlib import Path, PurePath
import re
from typing import Callable, Mapping

from momentum_hunter.continuous_research_export import PUBLICATION_FILE
from momentum_hunter.strategy_science_recorder.canonical import (
    canonical_json_v1, parse_rfc3339, require_sha256, sha256_hex, strict_json_loads,
)
from momentum_hunter.strategy_science_recorder.contract import (
    GENESIS_SHA256, parse_export_envelope_v2,
)
from momentum_hunter.strategy_science_recorder.coverage import derive_coverage
from momentum_hunter.strategy_science_recorder.custody import (
    RecorderCustodyError, SimulatedRecorderCrash, StrategyScienceRecorder,
    VerifiedReads, VerifiedReadError, continuous_public_operation, build_incremental_support,
)
from momentum_hunter.strategy_science_recorder.outcomes import parse_outcome_attachment
from momentum_hunter.strategy_science_source_reader import (
    SimulatedSourceReaderCrash, StrategyScienceSourceReaderV2,
)
from momentum_hunter.windows_writer_storage import WriterPhysicalStorage, WriterPhysicalStorageError


PROFILE = "SCIENCE_CONTINUOUS_RECEIPT_LEDGER_V1"
EVENT_FILE = re.compile(r"(?P<sequence>[0-9]{20})-(?P<hash>[0-9a-f]{64})\.event\.json")
CRASH_PHASES = frozenset({
    None, "after_arrival_temp", "after_arrival", "after_persistence_marker",
    "after_custody_before_cursor", "after_cursor_commit", "after_admission",
})
FAMILIES = (
    "discovery-cycle", "candidate-observation", "decision-event", "market-snapshot",
    "reference-plan", "provider-health-event", "outcome-observation",
)


class ContinuousRecorderError(RuntimeError):
    """Local custody or source proof failed; no new authority is granted."""


class ContinuousRecorderConflict(ContinuousRecorderError):
    """Immutable identity conflict freezes further admission in this root."""


class SimulatedContinuousCrash(ContinuousRecorderError):
    """Bounded offline fault injection; never a runtime control callback."""


class ContinuousScienceRecorder:
    """Preserve exact first arrival, then use the unchanged ordered ingress.

    Roots must be trusted, disjoint local directories. Normal operations verify
    new custody deltas, touched identities and aggregate content coherence.
    Startup/recovery and explicit historical reads retain full history audits,
    including singleton metadata. This is not hostile-filesystem containment.
    Retention is append-only, with no deletion or background activation.
    The injected clock is the same explicit clock contract as canonical custody.
    """

    _frozen_error = ContinuousRecorderConflict
    _read_integrity_error = ContinuousRecorderError

    def __init__(
        self, publication_root: Path, science_root: Path, *,
        source_root_identity: str, writer_instance_id: str,
        clock: Callable[[], str], lateness_seconds: int | None = None,
    ) -> None:
        self.publication_root = Path(publication_root).resolve(strict=True)
        self.science_root = Path(science_root).resolve()
        if self.publication_root.name != "published" or not self.publication_root.is_dir():
            raise ContinuousRecorderError("Input must be the canonical published directory.")
        # The entire producer root, including nonpublic metadata, is read-only.
        producer_root = self.publication_root.parent
        if (self.science_root == producer_root
                or self.science_root.is_relative_to(producer_root)
                or producer_root.is_relative_to(self.science_root)):
            raise ContinuousRecorderError("Science and producer roots must be disjoint.")
        require_sha256(source_root_identity, "source_root_identity")
        if not callable(clock) or not isinstance(writer_instance_id, str) or not writer_instance_id:
            raise ContinuousRecorderError("Explicit clock and writer identity are required.")
        if lateness_seconds is not None and (
            isinstance(lateness_seconds, bool) or not isinstance(lateness_seconds, int)
            or lateness_seconds < 0
        ):
            raise ContinuousRecorderError("Lateness policy must be explicit nonnegative seconds.")
        self._clock = clock
        self._closed = False
        self._events: list[dict[str, object]] = []
        self._hashes: list[str] = []
        self._operation_depth = 0
        self._ledger_loaded = False
        self._indexed_events = 0
        self._support = None
        self._bad_arrival_seen = False
        self._arrivals = {}
        self._persisted = {}
        self._admitted = {}
        self._rejected = {}
        self._arrival_by_raw = {}
        self._arrival_by_publication = {}
        self._arrival_by_delivery = {}
        self.lateness_seconds = lateness_seconds
        descriptor = {
            "publication_root": str(self.publication_root),
            "source_root_identity": source_root_identity,
            "lateness_seconds": lateness_seconds if lateness_seconds is not None else "UNKNOWN",
            "window_bounds": "START_INCLUSIVE_END_EXCLUSIVE",
            "retention": "APPEND_ONLY_NO_DELETION",
            "execution_authority": "NONE",
        }
        self._storage = WriterPhysicalStorage(
            self.science_root / "arrivals", writer_instance_id=writer_instance_id,
            topology_fingerprint=sha256_hex(canonical_json_v1(descriptor)), topology_version=1,
        )
        self.recorder: StrategyScienceRecorder | None = None
        self.reader: StrategyScienceSourceReaderV2 | None = None
        self._ledger_reads = None
        try:
            self._ledger_reads = VerifiedReads(self._storage.root, aggregate_content=True)
            self._load()
            if self._events:
                if self._events[0]["type"] != "CONFIG" or self._events[0]["data"] != descriptor:
                    raise ContinuousRecorderError("Recorder source identity or policy changed.")
            else:
                self._append("CONFIG", descriptor)
            partials = [{"name": p.name, "sha256": sha256_hex(p.read_bytes()),
                         "byte_length": p.stat().st_size}
                        for p in self._storage.iter_files(PurePath(".partial"), suffix=".tmp")]
            if partials:
                self._append("PARTIALS", {"classification": "NOT_ADMITTED", "files": partials})
                self._storage.quarantine_partials()
            self._reindex()
            self.recorder = StrategyScienceRecorder(
                self.science_root / "custody", source_root_identity=source_root_identity,
                writer_instance_id=writer_instance_id, clock=clock,
                reuse_verified_history=True,
            )
            # Canonical recovery supports legacy profiles, so check every exact
            # source through this adapter's narrower ingress BEFORE that replay.
            for source in self.recorder.science_root.rglob("*.source.json"):
                raw = self.recorder._read_raw(source)
                arrival = self._arrival_by_raw.get(sha256_hex(raw))
                if arrival is None or arrival["disposition"] != "RECEIVED":
                    raise ContinuousRecorderError("Recovery source lacks valid first-arrival custody.")
                self._metadata(raw, arrival["kind"])
            self.recorder.recover()
            self._support = build_incremental_support(self)
            self.reader = self._support.create_reader()
            self._synchronize(recovery=True)
            self._append("RESTART", {"previous_events": len(self._events),
                                     "classification": "PROCESS_OPEN_NOT_CONTINUOUS_COVERAGE"})
            self._reindex()
            self._support.finish_open()
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> "ContinuousScienceRecorder":
        return self

    @property
    def custody_root(self) -> Path:
        return self.science_root / "custody"

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.reader is not None:
                self.reader.close()
        finally:
            try:
                if self.recorder is not None:
                    self.recorder.close()
            finally:
                try:
                    try:
                        if self._support is not None:
                            self._support.close()
                    finally:
                        if self._ledger_reads is not None:
                            self._ledger_reads.close()
                finally:
                    self._storage.close()

    def _now(self) -> str:
        if self._closed:
            raise ContinuousRecorderError("Recorder is closed.")
        value = self._clock()
        parse_rfc3339(value, "Science physical clock")
        return value

    @staticmethod
    def _crash(requested: str | None, phase: str) -> None:
        if requested == phase:
            raise SimulatedContinuousCrash(phase)

    @staticmethod
    def _storage_interruption(exc: BaseException) -> bool:
        """I/O interruption leaves recoverable primary custody, not a semantic reject."""
        while exc is not None:
            if isinstance(exc, (OSError, WriterPhysicalStorageError, SimulatedRecorderCrash,
                                SimulatedSourceReaderCrash, SimulatedContinuousCrash)):
                return True
            exc = exc.__cause__
        return False

    def _append(self, kind: str, data: Mapping[str, object], *, partial: bool = False) -> str:
        entry = {"profile": PROFILE, "sequence": len(self._events) + 1,
                 "previous_sha256": self._hashes[-1] if self._hashes else GENESIS_SHA256,
                 "type": kind, "at": self._now(), "data": dict(data)}
        raw = canonical_json_v1(entry)
        digest = sha256_hex(raw)
        self._storage.atomic_create(
            PurePath("ledger", f"{entry['sequence']:020d}-{digest}.event.json"), raw,
            crash_after_temp=partial,
        )
        assert self._ledger_reads is not None
        installed = self._storage.root / 'ledger' / f"{entry['sequence']:020d}-{digest}.event.json"
        if self._ledger_reads.read(installed) != raw:
            raise ContinuousRecorderError('Installed ledger entry differs from exact receipt bytes.')
        if self._storage.read_committed(PurePath('ledger', installed.name)) != raw:
            raise ContinuousRecorderError('Writer005 ledger readback differs from exact receipt bytes.')
        if self._support is not None:
            self._support.ledger_published(installed)
        self._events.append(entry)
        self._hashes.append(digest)
        return digest

    def _load(self, *, force: bool = False) -> None:
        if self._operation_depth and self._ledger_loaded and not force:
            return
        events: list[dict[str, object]] = []
        hashes: list[str] = []
        for path in sorted(self._storage.iter_files(PurePath("ledger"), suffix="")):
            match = EVENT_FILE.fullmatch(path.name)
            if match is None or path.parent != self._storage.root / "ledger":
                raise ContinuousRecorderError("Unknown authoritative ledger object.")
            assert self._ledger_reads is not None
            try:
                raw = self._ledger_reads.read(path)
            except VerifiedReadError as exc:
                raise ContinuousRecorderError(str(exc)) from exc
            digest = sha256_hex(raw)
            index = len(events)
            if index < len(self._hashes):
                if (self._hashes[index] != digest or int(match.group('sequence')) != index + 1
                        or match.group('hash') != digest):
                    raise ContinuousRecorderError('Known immutable ledger prefix changed.')
                events.append(self._events[index])
                hashes.append(digest)
                continue
            try:
                entry = strict_json_loads(raw)
                valid = (
                    canonical_json_v1(entry) == raw and match.group("hash") == digest
                    and set(entry) == {"profile", "sequence", "previous_sha256", "type", "at", "data"}
                    and entry["profile"] == PROFILE and entry["sequence"] == len(events) + 1
                    and int(match.group("sequence")) == entry["sequence"]
                    and entry["previous_sha256"] == (hashes[-1] if hashes else GENESIS_SHA256)
                    and entry["type"] in {"CONFIG", "ARRIVAL", "PERSISTED", "ADMITTED", "REJECTED",
                                           "DUPLICATE", "RESTART", "GAPS", "PARTIALS"}
                    and isinstance(entry["data"], dict)
                )
                parse_rfc3339(entry["at"], "ledger clock")
            except (ValueError, TypeError, KeyError) as exc:
                raise ContinuousRecorderError("Corrupt or truncated authoritative ledger.") from exc
            if not valid:
                raise ContinuousRecorderError("Ledger hash, sequence or identity is invalid.")
            events.append(entry)
            hashes.append(digest)
        if self._hashes and hashes[:len(self._hashes)] != self._hashes:
            raise ContinuousRecorderError("Known immutable ledger tail disappeared or changed.")
        self._events, self._hashes = events, hashes
        self._ledger_loaded = True

    @staticmethod
    def _metadata(raw: bytes, kind: str) -> dict[str, object]:
        if kind == "PUBLICATION":
            parsed = parse_export_envelope_v2(raw)
            return {"schema_version": parsed.schema_version, "source_contract": parsed.source_contract,
                    "session_id": parsed.session_id, "stream_id": parsed.stream_id,
                    "source_sequence": parsed.source_sequence, "source_event_id": parsed.source_event_id,
                    "source_owner_identity": parsed.source_owner_identity,
                    "source_interface_identity": parsed.source_interface_identity,
                    "event_time": parsed.event_time, "producer_time": parsed.emitted_at,
                    "effective_known_at": parsed.effective_known_at, "event_type": parsed.event_type,
                    "previous_record_sha256": parsed.previous_record_sha256}
        parsed = parse_outcome_attachment(raw)
        return {"schema_version": "1.0.0", "source_contract": "OutcomeAttachmentV1",
                "session_id": parsed.session_id, "stream_id": parsed.stream_id,
                "source_sequence": parsed.source_sequence, "source_event_id": parsed.source_event_id,
                "source_owner_identity": parsed.source_owner,
                "event_time": parsed.observed_at, "producer_time": parsed.observed_at,
                "previous_record_sha256": parsed.previous_record_sha256,
                "event_type": "OUTCOME_ATTACHMENT"}

    def _reindex(self) -> None:
        if self._indexed_events > len(self._events):
            raise ContinuousRecorderError('Derived arrival index is ahead of authoritative ledger.')
        for entry, digest in zip(self._events[self._indexed_events:], self._hashes[self._indexed_events:]):
            kind, data = entry["type"], entry["data"]
            if kind == "ARRIVAL":
                try:
                    raw = base64.b64decode(data["raw_base64"], validate=True)
                    if sha256_hex(raw) != data["raw_sha256"]:
                        raise ValueError("raw hash mismatch")
                    if data["disposition"] != "INVALID" and self._metadata(raw, data["kind"]) != data["metadata"]:
                        raise ValueError("raw metadata mismatch")
                    parse_rfc3339(data["receipt_time"], "first receipt")
                    parse_rfc3339(data["persistence_begin"], "persistence attempt")
                except (ValueError, TypeError, KeyError) as exc:
                    raise ContinuousRecorderError("Arrival does not bind raw bytes and receipt.") from exc
                self._arrivals[digest] = dict(data, arrival_id=digest)
                self._bad_arrival_seen |= data['disposition'] != 'RECEIVED'
                arrival = self._arrivals[digest]
                self._arrival_by_raw.setdefault(data['raw_sha256'], arrival)
                self._arrival_by_publication.setdefault(data['publication_file'], arrival)
                self._arrival_by_delivery.setdefault((data['kind'], data['raw_sha256'], data['publication_file']), arrival)
            elif kind in {"PERSISTED", "ADMITTED", "REJECTED", "DUPLICATE"}:
                key = data.get("arrival_id")
                if key not in self._arrivals:
                    raise ContinuousRecorderError("Ledger marker references a missing arrival.")
                if kind != "DUPLICATE":
                    target = {"PERSISTED": self._persisted, "ADMITTED": self._admitted,
                              "REJECTED": self._rejected}[kind]
                    if key in target:
                        raise ContinuousRecorderError("Immutable arrival marker repeated.")
                    target[key] = dict(data)
        self._indexed_events = len(self._events)
        if self._support is not None:
            self._support.sync_events()

    def _frozen(self) -> bool:
        return self._bad_arrival_seen or bool(self._rejected)

    def _stage(self, raw: bytes, kind: str, publication_file: str,
               crash_phase: str | None, *, count_duplicate: bool) -> dict[str, object]:
        digest = sha256_hex(raw)
        arrival = self._arrival_by_delivery.get((kind, digest, publication_file))
        if arrival is not None:
            if count_duplicate:
                self._append("DUPLICATE", {"arrival_id": arrival["arrival_id"]})
            return arrival
        receipt = self._now()
        disposition, reason, meta = "RECEIVED", "VALIDATED_RAW_PENDING_ADMISSION", {}
        try:
            meta = self._metadata(raw, kind)
            if kind == "PUBLICATION":
                match = PUBLICATION_FILE.fullmatch(publication_file or "")
                token = sha256_hex(canonical_json_v1({"stream_id": meta["stream_id"]}))[:16]
                if (match is None or int(match.group("ordinal")) < 1
                        or int(match.group("sequence")) != meta["source_sequence"]
                        or match.group("stream") != token):
                    raise ValueError("Publication filename does not bind V2 stream and sequence.")
        except ValueError as exc:
            disposition, reason = "INVALID", str(exc)
        if disposition == "RECEIVED":
            assert self._support is not None
            if self._support.collision(kind, meta, publication_file):
                disposition, reason = "CONFLICT", "IMMUTABLE_SOURCE_IDENTITY_COLLISION_OR_DRIFT"
        data = {"kind": kind, "publication_file": publication_file,
                "raw_sha256": digest, "raw_base64": base64.b64encode(raw).decode("ascii"),
                "byte_length": len(raw), "metadata": meta, "receipt_time": receipt,
                "persistence_begin": self._now(), "disposition": disposition, "reason": reason}
        arrival_id = self._append("ARRIVAL", data, partial=crash_phase == "after_arrival_temp")
        self._reindex()
        self._crash(crash_phase, "after_arrival")
        self._mark_persistence(arrival_id, recovery=False)
        self._crash(crash_phase, "after_persistence_marker")
        return self._arrivals[arrival_id]

    def _mark_persistence(self, arrival_id: str, *, recovery: bool) -> None:
        completed = self._now()
        regressed = parse_rfc3339(completed, "completion") < parse_rfc3339(
            self._arrivals[arrival_id]["persistence_begin"], "persistence begin")
        self._append("PERSISTED", {"arrival_id": arrival_id,
                     "persistence_time": "UNKNOWN" if recovery or regressed else completed,
                     "completion_observed_at": completed,
                     "classification": "RECOVERED_ORIGINAL_TIME_UNKNOWN" if recovery else
                         "CLOCK_REGRESSION_UNKNOWN" if regressed else "POST_COMMIT_CLOCK_BOUND"})
        self._reindex()

    def _synchronize(self, *, recovery: bool) -> None:
        for key in tuple(self._arrivals):
            if key not in self._persisted:
                self._mark_persistence(key, recovery=recovery)
        assert self.reader is not None and self.recorder is not None
        cursor = self.reader.consume_available(max_items=0).cursor
        by_hash = {a["raw_sha256"]: key for key, a in self._arrivals.items()}
        for source in self.recorder.science_root.rglob("*.source.json"):
            raw = self.recorder._read_raw(source)
            key = by_hash.get(sha256_hex(raw))
            if key is None:
                raise ContinuousRecorderError("Canonical source lacks immutable first-arrival custody.")
            arrival = self._arrivals[key]
            self._metadata(raw, arrival["kind"])
            ordinal = (int(PUBLICATION_FILE.fullmatch(arrival["publication_file"]).group("ordinal"))
                       if arrival["kind"] == "PUBLICATION" else 0)
            if key not in self._admitted and ordinal <= cursor.last_publication_ordinal:
                self.recorder.verify(arrival["metadata"]["session_id"])
                self._append("ADMITTED", {"arrival_id": key, "checkpoint_sha256": "UNKNOWN",
                             "admission_persistence_time": "UNKNOWN",
                             "completion_observed_at": self._now(),
                             "classification": "RECOVERED_ORIGINAL_TIME_UNKNOWN"})
                self._reindex()

    @continuous_public_operation
    def poll(self, *, max_items: int = 100, crash_phase: str | None = None) -> dict[str, object]:
        """Observe at most max_items new arrivals and admit that many ordered files.

        Already observed files are checked for mutation, without counting normal
        polling as duplicate delivery. Future publications remain raw pending gaps.
        """
        if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 0:
            raise ContinuousRecorderError("max_items must be a nonnegative integer.")
        if crash_phase not in CRASH_PHASES:
            raise ContinuousRecorderError("Unknown fault-injection phase.")
        with self._storage.transaction():
            self._load()
            self._reindex()
            assert self._support is not None
            observed, inventory, vanished = self._support.observe(max_items, crash_phase)
            if self._frozen():
                raise ContinuousRecorderConflict("Persisted invalid/conflicting input freezes this recorder root.")
            assert self.reader is not None
            if any(gap["arrival_id"] in self._admitted for gap in vanished):
                self._append("GAPS", {"gaps": vanished, "cadence_coverage": "UNKNOWN_NO_DECLARED_CADENCE"})
                raise ContinuousRecorderError('Acknowledged publication disappeared; explicit recovery required.')
            admitted = 0
            gaps: list[dict[str, object]] = list(vanished)
            while admitted < max_items:
                state = self.reader.consume_available(max_items=0).cursor
                expected = state.last_publication_ordinal + 1
                if state.terminal:
                    future_ordinal = self._support.future(expected)
                    if future_ordinal is not None:
                        later = self._arrival_by_publication[inventory[future_ordinal].name]
                        self._append("REJECTED", {"arrival_id": later["arrival_id"],
                                     "reason": "PUBLICATION_AFTER_PRODUCER_FINAL"})
                        self._reindex()
                        raise ContinuousRecorderError("Publications follow canonical Producer FINAL.")
                    break
                path = inventory.get(expected)
                if path is None:
                    future = self._support.future(expected)
                    if future is not None:
                        gaps.append({"kind": "PUBLICATION", "first_missing": expected,
                                     "next_observed": future})
                    break
                arrival = self._arrival_by_publication[path.name]
                meta = arrival["metadata"]
                prior_sequence, _prior_hash = state.stream_heads.get(meta["stream_id"], (0, GENESIS_SHA256))
                if meta["source_sequence"] > prior_sequence + 1:
                    gaps.append({"kind": "SOURCE_SEQUENCE", "stream_id": meta["stream_id"],
                                 "first_missing": prior_sequence + 1,
                                 "next_observed": meta["source_sequence"]})
                    break
                try:
                    result = self.reader.admit(
                        self.raw_bytes(arrival["arrival_id"]), publication_ordinal=expected,
                        publication_file=path.name,
                        crash_phase=crash_phase if crash_phase in {"after_custody_before_cursor", "after_cursor_commit"} else None,
                    )
                except Exception as exc:
                    if self._storage_interruption(exc):
                        raise
                    self._append("REJECTED", {"arrival_id": arrival["arrival_id"], "reason": str(exc)})
                    self._reindex()
                    raise ContinuousRecorderError("Canonical admission rejected preserved raw input.") from exc
                self._support.apply_records(self.reader.last_delta)
                self._crash(crash_phase, "after_admission")
                self._append("ADMITTED", {"arrival_id": arrival["arrival_id"],
                             "checkpoint_sha256": result.custody.checkpoint_sha256,
                             "admission_persistence_time": self._now(),
                             "classification": "POST_COMMIT_CLOCK_BOUND"})
                self._reindex()
                admitted += 1
            # Admission budget exhaustion is not evidence that a gap resolved.
            # Inspect the current boundary even for a zero-budget observation.
            state = self.reader.consume_available(max_items=0).cursor
            expected = state.last_publication_ordinal + 1
            gaps = list(vanished)
            next_path = inventory.get(expected)
            if not state.terminal:
                future = self._support.future(expected)
                if next_path is None and future is not None:
                    gaps.append({"kind": "PUBLICATION", "first_missing": expected,
                                 "next_observed": future})
                elif next_path is not None:
                    meta = self._arrival_by_publication[next_path.name]['metadata']
                    previous_sequence = state.stream_heads.get(meta["stream_id"], (0, GENESIS_SHA256))[0]
                    if meta["source_sequence"] > previous_sequence + 1:
                        gaps.append({"kind": "SOURCE_SEQUENCE", "stream_id": meta["stream_id"],
                                     "first_missing": previous_sequence + 1,
                                     "next_observed": meta["source_sequence"]})
            previous_gaps = self._support.last_gaps if self._support.type_counts['GAPS'] else None
            if previous_gaps != gaps:
                self._append("GAPS", {"gaps": gaps, "cadence_coverage": "UNKNOWN_NO_DECLARED_CADENCE"})
            return {"observed": observed, "admitted": admitted, "coverage": self._support.summary(FAMILIES)}

    def run(self, *, polls: int, max_items: int = 100) -> tuple[dict[str, object], ...]:
        """Execute only the caller's finite polling budget; never install a worker."""
        if isinstance(polls, bool) or not isinstance(polls, int) or polls < 0:
            raise ContinuousRecorderError("polls must be a nonnegative integer.")
        return tuple(self.poll(max_items=max_items) for _ in range(polls))

    @continuous_public_operation
    def append_outcome(self, raw_bytes: bytes, *, crash_phase: str | None = None) -> dict[str, object]:
        if crash_phase not in {None, "after_arrival_temp", "after_arrival", "after_persistence_marker", "after_admission"}:
            raise ContinuousRecorderError("Unknown fault-injection phase.")
        with self._storage.transaction():
            self._load()
            self._reindex()
            arrival = self._stage(raw_bytes, "OUTCOME", "NOT_APPLICABLE", crash_phase, count_duplicate=True)
            key = arrival["arrival_id"]
            if self._frozen():
                raise ContinuousRecorderConflict("Persisted invalid/conflicting input freezes this recorder root.")
            if key in self._admitted:
                return {"status": "IDEMPOTENT_ACK", "arrival_id": key}
            assert self.recorder is not None
            try:
                result = self.recorder.append_outcome(raw_bytes)
                pairs = self.recorder.verify_commit_delta(parse_outcome_attachment(raw_bytes), result)
            except (RecorderCustodyError, ValueError) as exc:
                if self._storage_interruption(exc):
                    raise
                self._append("REJECTED", {"arrival_id": key, "reason": str(exc)})
                self._reindex()
                raise ContinuousRecorderError("Outcome rejected; exact raw and reason retained.") from exc
            self._support.apply_records(pairs)
            self._crash(crash_phase, "after_admission")
            self._append("ADMITTED", {"arrival_id": key, "checkpoint_sha256": result.checkpoint_sha256,
                         "admission_persistence_time": self._now(), "classification": "POST_COMMIT_CLOCK_BOUND"})
            self._reindex()
            return {"status": result.status, "arrival_id": key}

    @continuous_public_operation
    def raw_bytes(self, arrival_id: str) -> bytes:
        self._load()
        self._reindex()
        return base64.b64decode(self._arrivals[arrival_id]["raw_base64"], validate=True)

    @continuous_public_operation
    def arrivals(self) -> tuple[dict[str, object], ...]:
        self._load()
        self._reindex()
        return tuple(strict_json_loads(canonical_json_v1(dict(
            a, persistence=self._persisted.get(key, {"classification": "UNKNOWN"}),
            admission=self._admitted.get(key, {"classification": "NOT_ADMITTED"}),
            rejection=self._rejected.get(key, {"classification": "NOT_REJECTED"}),
        ))) for key, a in self._arrivals.items())

    @continuous_public_operation
    def records(self) -> tuple[Mapping[str, object], ...]:
        self._load()
        self._reindex()
        assert self.recorder is not None
        sessions = {}
        for source in self.recorder.science_root.rglob("*.source.json"):
            raw = self.recorder._read_raw(source)
            arrival = self._arrival_by_raw.get(sha256_hex(raw))
            if arrival is None or arrival["disposition"] != "RECEIVED":
                raise ContinuousRecorderError("Readback source lacks valid first-arrival custody.")
            metadata = self._metadata(raw, arrival["kind"])
            sessions[str(metadata["session_id"]["recorder_id"])] = metadata["session_id"]
        # Include admitted sessions even if their entire source segment vanished.
        sessions.update({str(a["metadata"]["session_id"]["recorder_id"]): a["metadata"]["session_id"]
                         for key, a in self._arrivals.items() if key in self._admitted})
        for session in sessions.values():
            if not self.recorder.verify(session).all_hashes_valid:
                raise ContinuousRecorderError("Canonical records do not verify.")
        return tuple(strict_json_loads(self.recorder._read_raw(path)) for path in sorted(
            self.recorder.science_root.rglob("*.payload.json")))

    @continuous_public_operation
    def coverage(self) -> dict[str, object]:
        records = self.records()
        arrivals = self.arrivals()
        family_counts = Counter(str(r["record_type"]) for r in records)
        valid = [a for a in arrivals if a["metadata"]]
        receipt_times = [a["receipt_time"] for a in arrivals]
        event_times = [a["metadata"]["event_time"] for a in valid]
        instant = lambda value: parse_rfc3339(value, "coverage time")
        late = []
        clock_anomalies = []
        disordered = []
        largest = None
        for a in valid:
            event = instant(a["metadata"]["event_time"])
            lag = (instant(a["receipt_time"]) - event).total_seconds()
            if lag < 0:
                clock_anomalies.append({"arrival_id": a["arrival_id"], "reason": "RECEIPT_BEFORE_EVENT",
                                        "delta_seconds": lag})
            if self.lateness_seconds is not None and lag > self.lateness_seconds:
                late.append({"arrival_id": a["arrival_id"], "delta_seconds": lag})
            if largest is not None and event < largest:
                disordered.append(a["arrival_id"])
            largest = event if largest is None else max(largest, event)
        conflicts = sum(a["disposition"] == "CONFLICT" for a in arrivals)
        return {
            "family_counts": {family: family_counts[family] for family in FAMILIES},
            "normalized_record_count": len(records), "raw_arrival_count": len(arrivals),
            "admitted_arrival_count": len(self._admitted),
            "pending_count": sum(key not in self._admitted and key not in self._rejected
                                 and a["disposition"] == "RECEIVED" for key, a in self._arrivals.items()),
            "conflicts": conflicts, "rejected_count": len(self._rejected),
            "invalid_count": sum(a["disposition"] == "INVALID" for a in arrivals),
            "admission_frozen": self._frozen(),
            "duplicate_deliveries": sum(e["type"] == "DUPLICATE" for e in self._events),
            "first_receipt_time": min(receipt_times, key=instant) if receipt_times else None,
            "last_receipt_time": max(receipt_times, key=instant) if receipt_times else None,
            "first_event_time": min(event_times, key=instant) if event_times else None,
            "last_event_time": max(event_times, key=instant) if event_times else None,
            "late_arrivals": late, "lateness_policy_seconds": self.lateness_seconds,
            "clock_anomalies": clock_anomalies,
            "capture_classification": "UNKNOWN_NO_SCHEDULER_TARGET_POLICY",
            "lateness_classification": "UNKNOWN" if self.lateness_seconds is None else "EXPLICIT_POLICY",
            "event_time_disordered_arrivals": disordered,
            "gaps": next((e["data"]["gaps"] for e in reversed(self._events) if e["type"] == "GAPS"), []),
            "gap_history": [dict(e["data"], at=e["at"]) for e in self._events if e["type"] == "GAPS"],
            "restart_boundaries": [e["at"] for e in self._events if e["type"] == "RESTART"],
            "schemas_observed": sorted({a["metadata"]["source_contract"] + ":" + a["metadata"]["schema_version"] for a in valid}),
            "source_identities": [strict_json_loads(raw) for raw in sorted({canonical_json_v1({
                field: a["metadata"].get(field, "UNKNOWN") for field in ("session_id", "source_owner_identity", "source_interface_identity")
            }) for a in valid})],
            "session_contexts": [{
                field: strict_json_loads(self.raw_bytes(a["arrival_id"]))["payload"].get(field, "UNKNOWN")
                for field in ("session_id", "source_runtime_activation_id", "source_root_identity",
                              "exchange_market_date", "session_kind", "market_timezone")
            } for a in valid if a["metadata"]["event_type"] == "SESSION_MANIFEST"
                and strict_json_loads(self.raw_bytes(a["arrival_id"]))["payload"].get("manifest_phase") == "START"],
            "canonical": derive_coverage(records, conflicts=conflicts).to_mapping(),
            "retention": "APPEND_ONLY_NO_DELETION", "continuous_coverage": "NOT_PROVEN",
            "independent_sample_count": "NOT_PROVEN", "execution_authority": "NONE",
        }

    def query_window(self, start: str, end: str, *, axis: str = "receipt",
                     session_id: Mapping[str, object] | None = None) -> tuple[dict[str, object], ...]:
        low, high = parse_rfc3339(start, "window start"), parse_rfc3339(end, "window end")
        if low >= high or axis not in {"receipt", "event"}:
            raise ContinuousRecorderError("Require increasing half-open bounds and receipt/event axis.")
        results = []
        for arrival in self.arrivals():
            meta = arrival["metadata"]
            if session_id is not None and meta.get("session_id") != session_id:
                continue
            value = arrival["receipt_time"] if axis == "receipt" else meta.get("event_time")
            if value is not None and low <= parse_rfc3339(value, "window record") < high:
                results.append(arrival)
        return tuple(results)
