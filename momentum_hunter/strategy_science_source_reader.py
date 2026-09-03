"""Offline Science reader for the canonical Continuous V2 publication surface.

The reader is deliberately narrow: it reads immutable files from one
``published`` directory, validates each exact byte string with the canonical V2
parser, gives those same bytes to :class:`StrategyScienceRecorder`, and only
then appends a Science-owned reader cursor.  It has no provider, service,
scheduler, account, broker, Paper, Shadow, or execution capability.

Publication delivery ordinals are used only as the producer's delivery order.
They are not represented as universal source chronology.  Semantic clocks stay
inside the producer envelope; the recorder creates the separate Science receipt
clock during custody.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Mapping
import os
import re
import uuid

from momentum_hunter.continuous_research_export import PUBLICATION_FILE
from momentum_hunter.strategy_science_recorder.canonical import (
    canonical_json_v1,
    sha256_hex,
    strict_json_loads,
)
from momentum_hunter.strategy_science_recorder.contract import (
    AUTHORITY,
    EXECUTION_AUTHORITY,
    GENESIS_SHA256,
    REPAIRED_EXPORT_SCHEMA_VERSION,
    REPAIRED_SOURCE_CONTRACT,
    REPAIRED_SOURCE_CONTRACT_VERSION,
    RecorderContractError,
    ValidatedExportEnvelope,
    parse_export_envelope_v2,
)
from momentum_hunter.strategy_science_recorder.custody import (
    AcceptanceResult,
    RecorderCustodyError,
    StrategyScienceRecorder,
)


READER_PROFILE = "ARGUS_SCIENCE_ALWAYS_ON_SOURCE_READER_V2"
READER_VERSION = "ARGUS-SCIENCE-ALWAYS-ON-SOURCE-READER-002-v1"
CURSOR_VERSION = 1
CURSOR_FILE = re.compile(
    r"(?P<ordinal>[0-9]{20})-(?P<sha256>[0-9a-f]{64})\.reader-cursor\.json"
)
CURSOR_PARTIAL_DIRECTORY = ".partial"
CURSOR_FIELDS = {
    "authority",
    "custody_checkpoint_sha256",
    "custody_status",
    "cursor_version",
    "delivery_order_semantic",
    "execution_authority",
    "final_disposition",
    "manifest_phase",
    "previous_reader_cursor_sha256",
    "previous_source_envelope_sha256",
    "profile",
    "publication_file",
    "publication_ordinal",
    "reader_version",
    "schema_version",
    "session_id",
    "source_contract",
    "source_contract_version",
    "source_effective_known_at",
    "source_emitted_at",
    "source_envelope_sha256",
    "source_event_id",
    "source_interface_identity",
    "source_owner_identity",
    "source_publication_identity_sha256",
    "source_sequence",
    "source_stream_id",
    "terminal",
}


class SourceReaderError(RuntimeError):
    """Base fail-closed source-reader error."""


class SourceReaderPublicationError(SourceReaderError):
    """The public producer namespace is malformed or no longer immutable."""


class SourceReaderCursorError(SourceReaderError):
    """Science reader cursor evidence is incomplete or contradictory."""


class SimulatedSourceReaderCrash(SourceReaderError):
    """Synthetic interruption used only by offline restart tests."""


@dataclass(frozen=True)
class ReaderCursorState:
    final_disposition: str
    last_publication_ordinal: int
    last_reader_cursor_sha256: str
    session_id: Mapping[str, object] | None
    stream_heads: Mapping[str, tuple[int, str]]
    terminal: bool


@dataclass(frozen=True)
class SourceReaderAdmission:
    custody: AcceptanceResult
    cursor_sha256: str
    publication_ordinal: int
    publication_file: str
    source_envelope_sha256: str
    terminal: bool


@dataclass(frozen=True)
class SourceReaderRun:
    admissions: tuple[SourceReaderAdmission, ...]
    cursor: ReaderCursorState
    status: str


class _ReaderLock:
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
            raise SourceReaderError("Another reader owns this Science state root.") from exc
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


class StrategyScienceSourceReaderV2:
    """Read exact canonical publications into the existing custody boundary."""

    def __init__(
        self,
        publication_root: Path,
        state_root: Path,
        *,
        recorder: StrategyScienceRecorder,
    ) -> None:
        if not isinstance(recorder, StrategyScienceRecorder):
            raise SourceReaderError(
                "The source reader requires the canonical StrategyScienceRecorder."
            )
        self.publication_root = Path(publication_root)
        self.state_root = Path(state_root)
        if self.publication_root.name != "published":
            raise SourceReaderPublicationError(
                "Reader input must be the canonical public 'published' directory."
            )
        if not self.publication_root.is_dir():
            raise SourceReaderPublicationError("Publication root does not exist.")
        publication_resolved = self.publication_root.resolve(strict=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        state_resolved = self.state_root.resolve(strict=True)
        try:
            state_resolved.relative_to(publication_resolved)
        except ValueError:
            pass
        else:
            raise SourceReaderError("Science cursor state cannot live under Producer bytes.")
        try:
            publication_resolved.relative_to(state_resolved)
        except ValueError:
            pass
        else:
            raise SourceReaderError("Producer bytes cannot live under Science cursor state.")
        self.cursor_root = self.state_root / "cursors"
        self.cursor_root.mkdir(parents=True, exist_ok=True)
        self.cursor_partial_root = self.cursor_root / CURSOR_PARTIAL_DIRECTORY
        self.cursor_partial_root.mkdir(exist_ok=True)
        if not self.cursor_partial_root.is_dir() or self.cursor_partial_root.is_symlink():
            raise SourceReaderCursorError("Reader cursor partial namespace is invalid.")
        self.recorder = recorder
        self._closed = False
        self._lock = _ReaderLock(self.state_root / ".reader.lock")
        self._lock.acquire()
        try:
            self._load_state()
        except BaseException:
            self._lock.release()
            raise

    def __enter__(self) -> "StrategyScienceSourceReaderV2":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._lock.release()

    def _ensure_open(self) -> None:
        if self._closed:
            raise SourceReaderError("Source reader is closed.")

    @staticmethod
    def _invoke(crash_phase: str | None, phase: str) -> None:
        if crash_phase == phase:
            raise SimulatedSourceReaderCrash(phase)

    def _directory_entries(self) -> tuple[Path, ...]:
        return tuple(self.publication_root.iterdir())

    def _inventory(self) -> dict[int, Path]:
        publications: dict[int, Path] = {}
        for path in self._directory_entries():
            match = PUBLICATION_FILE.fullmatch(path.name)
            if (
                match is None
                or not path.is_file()
                or path.is_symlink()
                or path.stat(follow_symlinks=False).st_nlink != 1
                or path.parent.resolve(strict=True) != self.publication_root.resolve(strict=True)
            ):
                raise SourceReaderPublicationError(
                    "Public namespace contains a staging, partial, linked, or unknown object."
                )
            ordinal = int(match.group("ordinal"))
            if ordinal < 1 or ordinal in publications:
                raise SourceReaderPublicationError(
                    "Publication delivery ordinal is invalid or duplicated."
                )
            publications[ordinal] = path
        return publications

    @staticmethod
    def _publication_identity(
        publication_file: str, ordinal: int, raw_sha256: str
    ) -> str:
        return sha256_hex(
            canonical_json_v1(
                {
                    "publication_file": publication_file,
                    "publication_ordinal": ordinal,
                    "source_envelope_sha256": raw_sha256,
                }
            )
        )

    @staticmethod
    def _manifest_phase(envelope: ValidatedExportEnvelope) -> str:
        if envelope.event_type != "SESSION_MANIFEST":
            return "NOT_APPLICABLE"
        phase = envelope.payload.get("manifest_phase")
        return str(phase) if phase in {"START", "FINAL"} else "INVALID"

    @staticmethod
    def _final_disposition(envelope: ValidatedExportEnvelope) -> str:
        if (
            envelope.event_type != "SESSION_MANIFEST"
            or envelope.payload.get("manifest_phase") != "FINAL"
        ):
            return "NOT_APPLICABLE"
        incomplete = any(
            int(envelope.payload[field]) > 0
            for field in (
                "conflict_count",
                "pending_source_events",
                "source_gap_count",
            )
        )
        return (
            "INCOMPLETE_SOURCE_FINAL"
            if incomplete
            else "COMPLETE_SOURCE_FINAL"
        )

    @staticmethod
    def _stream_token(stream_id: str) -> str:
        return sha256_hex(canonical_json_v1({"stream_id": stream_id}))[:16]

    def _read_publication(
        self, path: Path, *, expected_ordinal: int
    ) -> tuple[bytes, ValidatedExportEnvelope]:
        match = PUBLICATION_FILE.fullmatch(path.name)
        if match is None or int(match.group("ordinal")) != expected_ordinal:
            raise SourceReaderPublicationError("Publication filename identity is invalid.")
        try:
            before = path.stat(follow_symlinks=False)
            raw = path.read_bytes()
            after = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise SourceReaderPublicationError("Publication bytes are not durably readable.") from exc
        if (
            path.is_symlink()
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise SourceReaderPublicationError("Publication changed while it was being read.")
        try:
            envelope = parse_export_envelope_v2(raw)
        except (RecorderContractError, ValueError) as exc:
            raise SourceReaderPublicationError(
                "Publication does not validate through the canonical V2 parser."
            ) from exc
        if (
            int(match.group("sequence")) != envelope.source_sequence
            or match.group("stream") != self._stream_token(envelope.stream_id)
        ):
            raise SourceReaderPublicationError(
                "Publication filename does not bind its source stream and sequence."
            )
        return raw, envelope

    @staticmethod
    def _validate_cursor_value(value: Mapping[str, object]) -> None:
        if set(value) != CURSOR_FIELDS:
            raise SourceReaderCursorError("Reader cursor has missing or unknown fields.")
        expected = {
            "authority": AUTHORITY,
            "cursor_version": CURSOR_VERSION,
            "delivery_order_semantic": (
                "PUBLICATION_DELIVERY_ONLY_NOT_UNIVERSAL_SOURCE_CHRONOLOGY"
            ),
            "execution_authority": EXECUTION_AUTHORITY,
            "profile": READER_PROFILE,
            "reader_version": READER_VERSION,
            "schema_version": REPAIRED_EXPORT_SCHEMA_VERSION,
            "source_contract": REPAIRED_SOURCE_CONTRACT,
            "source_contract_version": REPAIRED_SOURCE_CONTRACT_VERSION,
        }
        for field, required in expected.items():
            if value.get(field) != required:
                raise SourceReaderCursorError(f"Reader cursor lineage differs at {field}.")
        ordinal = value.get("publication_ordinal")
        sequence = value.get("source_sequence")
        if (
            isinstance(ordinal, bool)
            or not isinstance(ordinal, int)
            or ordinal < 1
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
        ):
            raise SourceReaderCursorError("Reader cursor sequence fields are invalid.")
        for field in (
            "custody_checkpoint_sha256",
            "previous_reader_cursor_sha256",
            "previous_source_envelope_sha256",
            "source_envelope_sha256",
            "source_publication_identity_sha256",
        ):
            text = value.get(field)
            if not isinstance(text, str) or re.fullmatch(r"[0-9a-f]{64}", text) is None:
                raise SourceReaderCursorError(f"Reader cursor {field} is not SHA-256.")
        for field in (
            "publication_file",
            "source_effective_known_at",
            "source_emitted_at",
            "source_event_id",
            "source_interface_identity",
            "source_owner_identity",
            "source_stream_id",
        ):
            if not isinstance(value.get(field), str) or not value[field]:
                raise SourceReaderCursorError(f"Reader cursor {field} is empty.")
        if value.get("custody_status") not in {"ACCEPTED", "IDEMPOTENT_ACK"}:
            raise SourceReaderCursorError("Reader cursor custody status is invalid.")
        if value.get("manifest_phase") not in {
            "START",
            "FINAL",
            "NOT_APPLICABLE",
        } or not isinstance(value.get("terminal"), bool):
            raise SourceReaderCursorError("Reader cursor manifest state is invalid.")
        if value.get("final_disposition") not in {
            "NOT_APPLICABLE",
            "COMPLETE_SOURCE_FINAL",
            "INCOMPLETE_SOURCE_FINAL",
        }:
            raise SourceReaderCursorError("Reader cursor final disposition is invalid.")
        if not isinstance(value.get("session_id"), Mapping):
            raise SourceReaderCursorError("Reader cursor session identity is invalid.")

    def _cursor_entries(self) -> tuple[tuple[Path, Mapping[str, object], bytes], ...]:
        entries: list[tuple[Path, Mapping[str, object], bytes]] = []
        for path in self.cursor_root.iterdir():
            if path == self.cursor_partial_root:
                if not path.is_dir() or path.is_symlink():
                    raise SourceReaderCursorError(
                        "Reader cursor partial namespace is invalid."
                    )
                continue
            match = CURSOR_FILE.fullmatch(path.name)
            if match is None or not path.is_file() or path.is_symlink():
                raise SourceReaderCursorError("Science cursor namespace contains an unknown object.")
            raw = path.read_bytes()
            if sha256_hex(raw) != match.group("sha256"):
                raise SourceReaderCursorError("Reader cursor filename hash does not verify.")
            try:
                value = strict_json_loads(raw)
            except ValueError as exc:
                raise SourceReaderCursorError("Reader cursor is not strict JSON.") from exc
            if canonical_json_v1(value) != raw:
                raise SourceReaderCursorError("Reader cursor bytes are not canonical JSON.")
            self._validate_cursor_value(value)
            if value["publication_ordinal"] != int(match.group("ordinal")):
                raise SourceReaderCursorError("Reader cursor filename ordinal does not verify.")
            entries.append((path, value, raw))
        entries.sort(key=lambda item: int(item[1]["publication_ordinal"]))
        return tuple(entries)

    def _load_state(self) -> ReaderCursorState:
        inventory = self._inventory()
        cursors = self._cursor_entries()
        previous_cursor = GENESIS_SHA256
        session_id: Mapping[str, object] | None = None
        stream_heads: dict[str, tuple[int, str]] = {}
        terminal = False
        final_disposition = "NOT_APPLICABLE"
        for expected_ordinal, (_path, cursor, cursor_raw) in enumerate(cursors, start=1):
            ordinal = int(cursor["publication_ordinal"])
            if ordinal != expected_ordinal:
                raise SourceReaderCursorError("Reader cursor has a delivery gap or reorder.")
            if cursor["previous_reader_cursor_sha256"] != previous_cursor:
                raise SourceReaderCursorError("Reader cursor hash chain is invalid.")
            if terminal:
                raise SourceReaderCursorError("Reader cursor advances after Producer FINAL.")
            source_path = inventory.get(ordinal)
            if source_path is None or source_path.name != cursor["publication_file"]:
                raise SourceReaderCursorError("Acknowledged publication is missing or renamed.")
            raw, envelope = self._read_publication(
                source_path, expected_ordinal=ordinal
            )
            if (
                sha256_hex(raw) != cursor["source_envelope_sha256"]
                or envelope.source_event_id != cursor["source_event_id"]
                or envelope.stream_id != cursor["source_stream_id"]
                or envelope.source_sequence != cursor["source_sequence"]
                or envelope.previous_record_sha256
                != cursor["previous_source_envelope_sha256"]
                or envelope.effective_known_at != cursor["source_effective_known_at"]
                or envelope.emitted_at != cursor["source_emitted_at"]
                or envelope.session_id != cursor["session_id"]
                or envelope.source_owner_identity != cursor["source_owner_identity"]
                or envelope.source_interface_identity
                != cursor["source_interface_identity"]
                or self._manifest_phase(envelope) != cursor["manifest_phase"]
                or self._final_disposition(envelope)
                != cursor["final_disposition"]
                or self._publication_identity(
                    source_path.name, ordinal, envelope.raw_sha256
                )
                != cursor["source_publication_identity_sha256"]
            ):
                raise SourceReaderCursorError("Reader cursor no longer binds exact Producer bytes.")
            if expected_ordinal == 1:
                if self._manifest_phase(envelope) != "START":
                    raise SourceReaderCursorError("First reader cursor is not Producer START.")
                session_id = envelope.session_id
            elif envelope.session_id != session_id or self._manifest_phase(envelope) == "START":
                raise SourceReaderCursorError("Reader cursor changes session or repeats START.")
            prior_sequence, prior_hash = stream_heads.get(
                envelope.stream_id, (0, GENESIS_SHA256)
            )
            if (
                envelope.source_sequence != prior_sequence + 1
                or envelope.previous_record_sha256 != prior_hash
            ):
                raise SourceReaderCursorError("Reader cursor source stream has a gap or bad hash.")
            stream_heads[envelope.stream_id] = (
                envelope.source_sequence,
                envelope.raw_sha256,
            )
            terminal = self._manifest_phase(envelope) == "FINAL"
            final_disposition = self._final_disposition(envelope)
            if cursor["terminal"] is not terminal:
                raise SourceReaderCursorError("Reader cursor terminal state is contradictory.")
            previous_cursor = sha256_hex(cursor_raw)
        if session_id is not None:
            try:
                report = self.recorder.verify(session_id)
            except (RecorderCustodyError, RecorderContractError, ValueError) as exc:
                raise SourceReaderCursorError(
                    "Reader cursor cannot be proven against canonical Science custody."
                ) from exc
            if not report.all_hashes_valid:
                raise SourceReaderCursorError("Canonical Science custody does not verify.")
        return ReaderCursorState(
            final_disposition=final_disposition,
            last_publication_ordinal=len(cursors),
            last_reader_cursor_sha256=previous_cursor,
            session_id=session_id,
            stream_heads=dict(stream_heads),
            terminal=terminal,
        )

    @staticmethod
    def _atomic_create(path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        partial_root = path.parent / CURSOR_PARTIAL_DIRECTORY
        partial_root.mkdir(exist_ok=True)
        temp = partial_root / f"{uuid.uuid4().hex}.reader-cursor.tmp"
        try:
            with temp.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp, path)
            except FileExistsError:
                if path.read_bytes() != raw:
                    raise SourceReaderCursorError(
                        "Reader cursor path contains conflicting bytes."
                    )
        finally:
            temp.unlink(missing_ok=True)

    def admit(
        self,
        raw_bytes: bytes,
        *,
        publication_ordinal: int,
        publication_file: str,
        crash_phase: str | None = None,
    ) -> SourceReaderAdmission:
        """Use the one semantic ingress shared by filesystem and sealed replay sources."""

        self._ensure_open()
        if crash_phase not in {
            None,
            "after_read_before_custody",
            "after_custody_before_cursor",
            "after_cursor_commit",
        }:
            raise SourceReaderError("Unknown source-reader fault-injection phase.")
        state = self._load_state()
        if state.terminal:
            raise SourceReaderError("Producer FINAL already made the reader terminal.")
        if publication_ordinal != state.last_publication_ordinal + 1:
            raise SourceReaderError("Reader delivery cursor cannot skip or reorder publication.")
        inventory = self._inventory()
        public_path = inventory.get(publication_ordinal)
        if public_path is None or public_path.name != publication_file:
            raise SourceReaderPublicationError(
                "Semantic ingress accepts only a visible canonical publication."
            )
        visible_raw, visible_envelope = self._read_publication(
            public_path, expected_ordinal=publication_ordinal
        )
        if visible_raw != raw_bytes:
            raise SourceReaderPublicationError(
                "Ingress bytes differ from the visible immutable publication."
            )
        match = PUBLICATION_FILE.fullmatch(publication_file)
        if match is None or int(match.group("ordinal")) != publication_ordinal:
            raise SourceReaderPublicationError("Publication identity is malformed.")
        try:
            envelope = parse_export_envelope_v2(raw_bytes)
        except (RecorderContractError, ValueError) as exc:
            raise SourceReaderPublicationError(
                "Publication does not validate through the canonical V2 parser."
            ) from exc
        if envelope != visible_envelope:
            raise SourceReaderPublicationError(
                "Repeated canonical parsing produced contradictory source identity."
            )
        if (
            int(match.group("sequence")) != envelope.source_sequence
            or match.group("stream") != self._stream_token(envelope.stream_id)
        ):
            raise SourceReaderPublicationError(
                "Publication filename does not bind its source stream and sequence."
            )
        phase = self._manifest_phase(envelope)
        if publication_ordinal == 1:
            if phase != "START":
                raise SourceReaderError("A valid Producer START is required before evidence.")
        elif state.session_id is None or envelope.session_id != state.session_id:
            raise SourceReaderError("Publication session differs from admitted Producer START.")
        elif phase == "START":
            raise SourceReaderError("Producer START cannot be repeated after admission.")
        prior_sequence, prior_hash = state.stream_heads.get(
            envelope.stream_id, (0, GENESIS_SHA256)
        )
        if envelope.source_sequence != prior_sequence + 1:
            raise SourceReaderError("Source stream has a sequence gap or reorder.")
        if envelope.previous_record_sha256 != prior_hash:
            raise SourceReaderError("Source stream previous raw-envelope hash is invalid.")
        self._invoke(crash_phase, "after_read_before_custody")
        try:
            custody = self.recorder.accept(raw_bytes)
        except (RecorderCustodyError, RecorderContractError, ValueError) as exc:
            raise SourceReaderError(
                "Canonical Science custody rejected the exact Producer bytes."
            ) from exc
        try:
            verification = self.recorder.verify(envelope.session_id)
        except (RecorderCustodyError, RecorderContractError, ValueError) as exc:
            raise SourceReaderError("Science custody commit did not verify.") from exc
        if not verification.all_hashes_valid:
            raise SourceReaderError("Science custody commit did not verify.")
        self._invoke(crash_phase, "after_custody_before_cursor")
        cursor = {
            "authority": AUTHORITY,
            "custody_checkpoint_sha256": custody.checkpoint_sha256,
            "custody_status": custody.status,
            "cursor_version": CURSOR_VERSION,
            "delivery_order_semantic": (
                "PUBLICATION_DELIVERY_ONLY_NOT_UNIVERSAL_SOURCE_CHRONOLOGY"
            ),
            "execution_authority": EXECUTION_AUTHORITY,
            "final_disposition": self._final_disposition(envelope),
            "manifest_phase": phase,
            "previous_reader_cursor_sha256": state.last_reader_cursor_sha256,
            "previous_source_envelope_sha256": envelope.previous_record_sha256,
            "profile": READER_PROFILE,
            "publication_file": publication_file,
            "publication_ordinal": publication_ordinal,
            "reader_version": READER_VERSION,
            "schema_version": envelope.schema_version,
            "session_id": envelope.session_id,
            "source_contract": envelope.source_contract,
            "source_contract_version": envelope.source_contract_version,
            "source_effective_known_at": envelope.effective_known_at,
            "source_emitted_at": envelope.emitted_at,
            "source_envelope_sha256": envelope.raw_sha256,
            "source_event_id": envelope.source_event_id,
            "source_interface_identity": envelope.source_interface_identity,
            "source_owner_identity": envelope.source_owner_identity,
            "source_publication_identity_sha256": self._publication_identity(
                publication_file, publication_ordinal, envelope.raw_sha256
            ),
            "source_sequence": envelope.source_sequence,
            "source_stream_id": envelope.stream_id,
            "terminal": phase == "FINAL",
        }
        raw_cursor = canonical_json_v1(cursor)
        cursor_sha = sha256_hex(raw_cursor)
        cursor_path = self.cursor_root / (
            f"{publication_ordinal:020d}-{cursor_sha}.reader-cursor.json"
        )
        self._atomic_create(cursor_path, raw_cursor)
        loaded = self._load_state()
        if loaded.last_publication_ordinal != publication_ordinal:
            raise SourceReaderCursorError("Durable reader cursor did not verify after commit.")
        self._invoke(crash_phase, "after_cursor_commit")
        return SourceReaderAdmission(
            custody=custody,
            cursor_sha256=cursor_sha,
            publication_ordinal=publication_ordinal,
            publication_file=publication_file,
            source_envelope_sha256=envelope.raw_sha256,
            terminal=phase == "FINAL",
        )

    def consume_available(
        self,
        *,
        max_items: int | None = None,
        crash_phase: str | None = None,
    ) -> SourceReaderRun:
        """Consume public objects in Producer delivery order, never filesystem order."""

        self._ensure_open()
        if max_items is not None and (
            isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 0
        ):
            raise SourceReaderError("max_items must be an integer >= 0.")
        admissions: list[SourceReaderAdmission] = []
        while max_items is None or len(admissions) < max_items:
            state = self._load_state()
            inventory = self._inventory()
            expected = state.last_publication_ordinal + 1
            if state.terminal:
                if any(ordinal >= expected for ordinal in inventory):
                    raise SourceReaderPublicationError(
                        "Public evidence exists after Producer FINAL."
                    )
                break
            path = inventory.get(expected)
            if path is None:
                if any(ordinal > expected for ordinal in inventory):
                    raise SourceReaderPublicationError(
                        "Publication delivery gap stops the reader before later evidence."
                    )
                break
            raw, _envelope = self._read_publication(
                path, expected_ordinal=expected
            )
            admissions.append(
                self.admit(
                    raw,
                    publication_ordinal=expected,
                    publication_file=path.name,
                    crash_phase=crash_phase,
                )
            )
            crash_phase = None
        cursor = self._load_state()
        return SourceReaderRun(
            admissions=tuple(admissions),
            cursor=cursor,
            status=(
                "TERMINAL_INCOMPLETE_FINAL_ADMITTED"
                if cursor.final_disposition == "INCOMPLETE_SOURCE_FINAL"
                else "TERMINAL_FINAL_ADMITTED"
                if cursor.final_disposition == "COMPLETE_SOURCE_FINAL"
                else "INCOMPLETE_AWAITING_PUBLICATION"
            ),
        )


__all__ = [
    "ReaderCursorState",
    "SimulatedSourceReaderCrash",
    "SourceReaderAdmission",
    "SourceReaderCursorError",
    "SourceReaderError",
    "SourceReaderPublicationError",
    "SourceReaderRun",
    "StrategyScienceSourceReaderV2",
]
