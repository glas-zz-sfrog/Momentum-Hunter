"""Dormant modern decision custody. Identity never grants execution permission.

The deployment steward owns the independent cutover record. This module only
reads it; synthetic tests substitute its fixed path, never provision real roots.
"""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid
from typing import Mapping

from momentum_hunter.path_transaction import PathTransactionLease


MODERN_CONTRACT = "MODERN_OPERATIONAL_CUTOVER_V1"
MODERN_PRODUCER_SCHEMA = 3
MODERN_PRODUCER_PROFILE = "continuous-authoritative-tradeplan-producer-v1"
CURRENT_CUTOVER = Path(
    r"C:\ProgramData\MomentumHunter\governance\modern-operational-cutover-current.json"
)
_HASH = re.compile(r"[0-9a-f]{64}")
_MAX_BYTES = 64 * 1024 * 1024
_KINDS = frozenset({"COMPOSITION", "CHECKPOINT", "QUEUED_DECISION", "POSITION",
                    "STRATEGY_DECISION", "CONTINUOUS_ADMISSION", "CONTINUOUS_INTENT", "CONTINUOUS_FILL"})
_OBLIGATION_SOURCES = frozenset(
    {"POSITIONS", "WORKING_ORDERS", "BROKER_STATE", "PERSISTED_EXECUTION"}
)


class ModernOperationalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.diagnostic_code = code


def deny(message: str, code: str = "MODERN_OPERATIONAL_ADMISSION_DENIED") -> None:
    raise ModernOperationalError(code, message)


def digest(raw: bytes) -> str:
    if type(raw) is not bytes:
        deny("Snapshot content must be immutable bytes.")
    return hashlib.sha256(raw).hexdigest()


def canonical_bytes(value: object) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ModernOperationalError("INVALID_JSON", "Cannot encode evidence.") from exc


def parse_bytes(raw: bytes) -> dict:
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
        deny("Invalid or oversized immutable document.")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                deny("Repeated JSON key.")
            result[key] = value
        return result

    try:
        def finite_float(text):
            number = float(text)
            if not math.isfinite(number):
                deny("Nonfinite JSON number.")
            return number

        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_float=finite_float,
                           parse_constant=lambda _: deny("Nonfinite JSON value."))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, ModernOperationalError):
            raise
        raise ModernOperationalError("INVALID_JSON", "Unreadable document.") from exc
    if type(value) is not dict:
        deny("Document is not an object.")
    return value


def require_hash(value: object, label: str) -> str:
    if type(value) is not str or not _HASH.fullmatch(value):
        deny(f"{label} must be an exact lowercase SHA-256.")
    return value


def instant(value: str) -> datetime:
    if type(value) is not str:
        deny("Missing exact timestamp.")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ModernOperationalError("INVALID_TIME", "Invalid timestamp.") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        deny("Timestamp lacks timezone.")
    return result.astimezone(timezone.utc)


def require_schema(value: object, expected: int) -> None:
    if type(value) is not int or value != expected:
        deny("Unsupported exact schema type/version.")


@dataclass(frozen=True)
class OperationalEpoch:
    epoch_id: str
    source_identity: str
    configuration_identity: str
    root: str
    not_before: str
    authority_sha256: str

    def require_current(self) -> None:
        current = load_current_epoch(
            source_identity=self.source_identity,
            configuration_identity=self.configuration_identity,
        )
        if current != self:
            deny("Independent cutover authority changed.")

    def wire(self) -> dict:
        return {"operationalContract": MODERN_CONTRACT,
                "operationalEpochId": self.epoch_id,
                "sourceIdentity": self.source_identity,
                "configurationIdentity": self.configuration_identity,
                "cutoverAuthoritySha256": self.authority_sha256}

    def validate_binding(self, value: Mapping) -> None:
        if not isinstance(value, Mapping):
            deny("Missing epoch binding.")
        if any(value.get(key) != item for key, item in self.wire().items()):
            deny("Missing, foreign, or contradictory operational epoch binding.")

    def require_time(self, value: str) -> None:
        if instant(value) < instant(self.not_before):
            deny("Operational identity predates the prospective cutover floor.")

    @contextmanager
    def transaction(self):
        # The deployment steward must use this same lease when replacing the
        # independent cutover record. Consumers also revalidate after commit.
        with PathTransactionLease(CURRENT_CUTOVER).transaction():
            self.require_current()
            yield
            self.require_current()


def cutover_latch_path() -> Path:
    return CURRENT_CUTOVER.with_name("modern-operational-cutover-established.json")


def require_cutover_latch() -> None:
    try:
        latch = parse_bytes(cutover_latch_path().read_bytes())
    except OSError as exc:
        raise ModernOperationalError("CUTOVER_LATCH_UNAVAILABLE",
                                     "Independent permanent cutover latch is required.") from exc
    require_schema(latch.get("schemaVersion"), 1)
    if latch != {"schemaVersion": 1, "operationalContract": MODERN_CONTRACT,
                 "legacyOperationalAuthority": "PROHIBITED"}:
        deny("Invalid permanent cutover latch.")


def load_current_epoch(*, source_identity: str,
                       configuration_identity: str) -> OperationalEpoch:
    """Read independent authority, never mint it from a caller or artifact."""
    require_hash(source_identity, "Running source identity")
    require_hash(configuration_identity, "Running configuration identity")
    require_cutover_latch()
    try:
        raw = CURRENT_CUTOVER.read_bytes()
    except OSError as exc:
        raise ModernOperationalError("CUTOVER_AUTHORITY_UNAVAILABLE",
                                     "Independent deployment record is required.") from exc
    value = parse_bytes(raw)
    if set(value) != {"schemaVersion", "operationalContract", "operationalEpochId",
                      "sourceIdentity", "configurationIdentity", "operationalRoot",
                      "notBefore", "namespaceGeneration"}:
        deny("Invalid independent cutover record.")
    require_schema(value["schemaVersion"], 1)
    require_hash(value["operationalEpochId"], "Independent operational epoch")
    require_hash(value["namespaceGeneration"], "Independent namespace generation")
    if (value["operationalContract"] != MODERN_CONTRACT
            or value["sourceIdentity"] != source_identity
            or value["configurationIdentity"] != configuration_identity):
        deny("Running source/configuration differs from accepted cutover.")
    instant(value["notBefore"])
    root = value["operationalRoot"]
    if type(root) is not str or not Path(root).is_absolute():
        deny("Cutover root must be independently selected and absolute.")
    resolved = str(Path(root).resolve())
    if Path(root) != Path(resolved) or Path(root).is_symlink():
        deny("Cutover root is redirected.")
    if CURRENT_CUTOVER.read_bytes() != raw:
        deny("Cutover changed while loading.")
    return OperationalEpoch(value["operationalEpochId"], source_identity,
                            configuration_identity, resolved, value["notBefore"], digest(raw))


@dataclass(frozen=True)
class Obligation:
    identity: str
    epoch_id: str | None
    resolved: bool


@dataclass(frozen=True)
class ObligationAssessment:
    observed_at: str
    inspected_sources: tuple[str, ...]
    obligations: tuple[Obligation, ...]

    def require_clear(self, epoch: OperationalEpoch, *, fresh: bool) -> None:
        if (type(self.inspected_sources) is not tuple
                or frozenset(self.inspected_sources) != _OBLIGATION_SOURCES
                or len(self.inspected_sources) != len(_OBLIGATION_SOURCES)
                or type(self.obligations) is not tuple):
            deny("Incomplete obligation preflight.", "BLOCK_RECONCILIATION_REQUIRED")
        epoch.require_time(self.observed_at)
        for item in self.obligations:
            if (type(item) is not Obligation or type(item.resolved) is not bool
                    or type(item.identity) is not str or not item.identity
                    or item.epoch_id != epoch.epoch_id or fresh):
                deny("An obligation cannot be silently imported or abandoned.",
                     "BLOCK_RECONCILIATION_REQUIRED")
            if not item.resolved:
                deny("Unresolved obligation requires exact owned recovery.",
                     "BLOCK_RECONCILIATION_REQUIRED")


def _replace(path: Path, raw: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_epoch(epoch: OperationalEpoch, assessment: ObligationAssessment) -> None:
    """Initialize only an independently selected empty namespace, no migration."""
    epoch.require_current()
    assessment.require_clear(epoch, fresh=True)
    root = Path(epoch.root)
    with PathTransactionLease(root.with_name(root.name + ".startup")).transaction():
        epoch.require_current()
        if root.exists() and any(root.iterdir()):
            deny("Selected root is not empty; refusing restore, migration, or reset.")
        root.mkdir(parents=True, exist_ok=True)
        _replace(root / "epoch.json", canonical_bytes({"schemaVersion": 1,
                 **epoch.wire(), "startedAt": assessment.observed_at}))


def require_epoch_started(epoch: OperationalEpoch) -> None:
    epoch.require_current()
    try:
        value = parse_bytes((Path(epoch.root) / "epoch.json").read_bytes())
    except OSError as exc:
        raise ModernOperationalError("EPOCH_NOT_STARTED", "No accepted epoch state.") from exc
    require_schema(value.get("schemaVersion"), 1)
    if set(value) != {"schemaVersion", *epoch.wire(), "startedAt"}:
        deny("Invalid persisted epoch state.")
    epoch.validate_binding(value)
    epoch.require_time(value.get("startedAt"))


def reject_legacy_operation(path: Path, *, epoch: OperationalEpoch | None = None) -> None:
    """Do not let an Opening/legacy entrypoint write a Continuous namespace.

    Independently admitted Opening operation is a separate contract. A global
    latch is not permission to disable that contract. Modern entrypoints always
    load independent authority, even when the selected root is unavailable.
    """
    path = Path(path).resolve()
    selected = False
    if CURRENT_CUTOVER.exists():
        authority = parse_bytes(CURRENT_CUTOVER.read_bytes())
        root = authority.get("operationalRoot")
        if type(root) is not str or not Path(root).is_absolute():
            deny("Cannot establish the selected Continuous namespace.")
        selected = path.is_relative_to(Path(root).resolve())
    if (epoch is not None or selected
            or any((parent / "epoch.json").exists() for parent in (path, *path.parents))):
        deny("Legacy report/state is not an operational adapter for the modern epoch.",
             "LEGACY_OPERATIONAL_ADOPTION_PROHIBITED")


@dataclass(frozen=True)
class OperationalSnapshot:
    """All persisted components are immutable bytes, never mutable dictionaries."""
    manifest_bytes: bytes
    components: tuple[tuple[str, bytes], ...]

    @property
    def snapshot_id(self) -> str:
        return digest(self.manifest_bytes)

    def component(self, name: str) -> bytes:
        matches = tuple(raw for key, raw in self.components if key == name)
        if len(matches) != 1:
            deny("Snapshot component is missing or ambiguous.")
        return matches[0]

    def validate(self, epoch: OperationalEpoch, *, kind: str,
                 expected_id: str | None = None) -> dict:
        require_epoch_started(epoch)
        if expected_id is not None and self.snapshot_id != expected_id:
            deny("Consumed bytes differ from the authorized snapshot.")
        value = parse_bytes(self.manifest_bytes)
        if set(value) != {"schemaVersion", *epoch.wire(), "kind", "sequence",
                          "predecessorSnapshotId", "createdAt", "knownAt",
                          "decisionCutoff", "components"}:
            deny("Snapshot manifest shape is invalid.")
        require_schema(value.get("schemaVersion"), 1)
        epoch.validate_binding(value)
        if value.get("kind") != kind or kind not in _KINDS:
            deny("Snapshot is not authorized for this consumer.")
        if type(value.get("sequence")) is not int or value["sequence"] < 1:
            deny("Invalid snapshot sequence.")
        previous = value.get("predecessorSnapshotId")
        if value["sequence"] == 1:
            if previous is not None:
                deny("First snapshot has a predecessor.")
        else:
            require_hash(previous, "Predecessor snapshot")
        epoch.require_time(value.get("createdAt"))
        if not (instant(value["createdAt"]) <= instant(value.get("knownAt"))
                <= instant(value.get("decisionCutoff"))):
            deny("Snapshot chronology is contradictory.")
        if type(self.components) is not tuple or not self.components:
            deny("Snapshot components are not immutable.")
        expected = []
        names = set()
        for entry in self.components:
            if type(entry) is not tuple or len(entry) != 2:
                deny("Invalid snapshot component.")
            name, raw = entry
            if (type(name) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", name)
                    or name in names or type(raw) is not bytes):
                deny("Invalid snapshot component identity.")
            names.add(name)
            expected.append({"name": name, "sha256": digest(raw), "size": len(raw)})
        if value.get("components") != expected:
            deny("Snapshot component bytes do not match manifest.")
        return value

    def to_bytes(self) -> bytes:
        return canonical_bytes({"manifest": self.manifest_bytes.decode("ascii"),
                                "components": [[name, raw.decode("ascii")]
                                               for name, raw in self.components]})


def snapshot_from_bytes(raw: bytes, epoch: OperationalEpoch, *, kind: str,
                        expected_id: str) -> OperationalSnapshot:
    value = parse_bytes(raw)
    if set(value) != {"manifest", "components"} or type(value["manifest"]) is not str:
        deny("Invalid snapshot envelope.")
    if type(value["components"]) is not list:
        deny("Invalid snapshot component list.")
    components = []
    for item in value["components"]:
        if type(item) is not list or len(item) != 2 or any(type(x) is not str for x in item):
            deny("Invalid snapshot component encoding.")
        components.append((item[0], item[1].encode("ascii")))
    snapshot = OperationalSnapshot(value["manifest"].encode("ascii"), tuple(components))
    snapshot.validate(epoch, kind=kind, expected_id=expected_id)
    return snapshot


def freeze_snapshot(epoch: OperationalEpoch, *, kind: str,
                    components: tuple[tuple[str, bytes], ...], sequence: int,
                    predecessor: str | None, created_at: str, known_at: str,
                    decision_cutoff: str) -> OperationalSnapshot:
    manifest = {"schemaVersion": 1, **epoch.wire(), "kind": kind,
                "sequence": sequence, "predecessorSnapshotId": predecessor,
                "createdAt": created_at, "knownAt": known_at,
                "decisionCutoff": decision_cutoff,
                "components": [{"name": name, "sha256": digest(raw), "size": len(raw)}
                               for name, raw in components]}
    snapshot = OperationalSnapshot(canonical_bytes(manifest), components)
    snapshot.validate(epoch, kind=kind)
    return snapshot


def exact_chain(value: Mapping) -> tuple[str, str, str]:
    if not isinstance(value, Mapping):
        deny("Authoritative chain is absent.")
    return tuple(require_hash(value.get(name), name)
                 for name in ("opportunity_id", "setup_id", "trade_plan_id"))


def select_exact_row(rows: list, chain: tuple[str, str, str]) -> dict:
    if type(chain) is not tuple or len(chain) != 3:
        deny("Explicit complete identity is required; no symbol fallback.")
    for value in chain:
        require_hash(value, "Selected identity")
    if type(rows) is not list:
        deny("Invalid operational rows.")
    matches = []
    identities = set()
    for row in rows:
        row_chain = exact_chain(row)
        if row_chain in identities:
            deny("Duplicate authoritative identity.")
        identities.add(row_chain)
        if row_chain == chain:
            matches.append(row)
    if len(matches) != 1:
        deny("Exact operational identity is missing or ambiguous.")
    return matches[0]


class SnapshotPublication:
    """Exact immutable payload plus a compare-and-swap current reference.

    The selected epoch root has one cooperating owner. Callers keep the returned
    snapshot ID across handoff; a current filename is never that identity.
    """
    def __init__(self, epoch: OperationalEpoch, kind: str) -> None:
        require_epoch_started(epoch)
        if kind not in _KINDS:
            deny("Unsupported publication kind.")
        self.epoch = epoch
        self.kind = kind
        self.root = Path(epoch.root) / "snapshots" / kind.lower()
        self.pointer = self.root / "current.json"
        self.pending = self.root / "pending.json"
        self.lease = PathTransactionLease(self.pointer)

    def current(self) -> OperationalSnapshot | None:
        require_epoch_started(self.epoch)
        with self.epoch.transaction(), self.lease.transaction():
            self._recover_pending()
            return self._read_current()

    def _read_current(self, *, prepared: bool = False) -> OperationalSnapshot | None:
            if not self.pointer.exists():
                if not prepared and self.root.exists() and any(self.root.glob("*.json")):
                    deny("Snapshot reference is missing; refusing reset.")
                return None
            reference = parse_bytes(self.pointer.read_bytes())
            if set(reference) != {"schemaVersion", *self.epoch.wire(), "snapshotId", "payloadSha256"}:
                deny("Invalid current snapshot reference.")
            require_schema(reference["schemaVersion"], 1)
            self.epoch.validate_binding(reference)
            identity = require_hash(reference["snapshotId"], "Current snapshot")
            raw = (self.root / (identity + ".json")).read_bytes()
            if digest(raw) != reference["payloadSha256"]:
                deny("Published snapshot bytes differ from current reference.")
            return snapshot_from_bytes(raw, self.epoch, kind=self.kind, expected_id=identity)

    def _recover_pending(self) -> None:
        if not self.pending.exists():
            return
        value = parse_bytes(self.pending.read_bytes())
        if set(value) != {"snapshotId", "payloadSha256", "snapshot"} or type(value["snapshot"]) is not str:
            deny("Invalid prepared publication.")
        raw = value["snapshot"].encode("ascii")
        if digest(raw) != value["payloadSha256"]:
            deny("Prepared publication payload was changed.")
        snapshot = snapshot_from_bytes(raw, self.epoch, kind=self.kind,
                                       expected_id=value["snapshotId"])
        if self.kind == "COMPOSITION":
            from momentum_hunter.lifecycle_position_identity import validate_composition_snapshot
            validate_composition_snapshot(snapshot, self.epoch)
        manifest = parse_bytes(snapshot.manifest_bytes)
        previous = self._read_current(prepared=True)
        if previous != snapshot:
            actual = previous.snapshot_id if previous else None
            sequence = parse_bytes(previous.manifest_bytes)["sequence"] if previous else 0
            if manifest["predecessorSnapshotId"] != actual or manifest["sequence"] != sequence + 1:
                deny("Prepared publication no longer owns the current generation.")
            destination = self.root / (snapshot.snapshot_id + ".json")
            if destination.exists() and destination.read_bytes() != raw:
                deny("Prepared publication conflicts with archived bytes.")
            if not destination.exists():
                # Atomic replacement prevents a crash from sealing a partial archive.
                _replace(destination, raw)
            _replace(self.pointer, canonical_bytes({"schemaVersion": 1,
                **self.epoch.wire(), "snapshotId": snapshot.snapshot_id,
                "payloadSha256": digest(raw)}))
        self.pending.unlink()

    def publish(self, snapshot: OperationalSnapshot, *, expected_previous: str | None) -> None:
        if type(snapshot) is not OperationalSnapshot:
            deny("Publication requires the exact native immutable snapshot type.")
        manifest = snapshot.validate(self.epoch, kind=self.kind)
        if self.kind == "COMPOSITION":
            from momentum_hunter.lifecycle_position_identity import validate_composition_snapshot
            validate_composition_snapshot(snapshot, self.epoch)
        # Encoding happens once before touching persistence; everything below
        # receives this same immutable buffer, including the write-once journal.
        raw = snapshot.to_bytes()
        if snapshot_from_bytes(raw, self.epoch, kind=self.kind, expected_id=snapshot.snapshot_id) != snapshot:
            deny("Serialized publication is not the snapshot that was validated.")
        with self.epoch.transaction(), self.lease.transaction():
            previous = self.current()
            actual_previous = previous.snapshot_id if previous is not None else None
            if actual_previous != expected_previous or manifest["predecessorSnapshotId"] != actual_previous:
                deny("Snapshot publication predecessor changed.")
            prior_sequence = parse_bytes(previous.manifest_bytes)["sequence"] if previous else 0
            if manifest["sequence"] != prior_sequence + 1:
                deny("Snapshot publication sequence is not contiguous.")
            self.root.mkdir(parents=True, exist_ok=True)
            _replace(self.pending, canonical_bytes({"snapshotId": snapshot.snapshot_id,
                "payloadSha256": digest(raw), "snapshot": raw.decode("ascii")}))
            self._recover_pending()

    def require_consumed(self, snapshot: OperationalSnapshot, *, expected_id: str) -> None:
        snapshot.validate(self.epoch, kind=self.kind, expected_id=expected_id)
        current = self.current()
        if current != snapshot:
            deny("Operational consumer did not receive the current published snapshot.")

    def require_committed(self, snapshot: OperationalSnapshot, *, expected_id: str) -> None:
        """Owned position recovery may use a committed predecessor, never an orphan."""
        snapshot.validate(self.epoch, kind=self.kind, expected_id=expected_id)
        candidate = self.current()
        for _ in range(4096):
            if candidate is None:
                break
            if candidate.snapshot_id == expected_id:
                if candidate != snapshot:
                    deny("Committed snapshot bytes disagree with position provenance.")
                return
            manifest = parse_bytes(candidate.manifest_bytes)
            previous = manifest["predecessorSnapshotId"]
            if previous is None:
                break
            raw = (self.root / (require_hash(previous, "Predecessor") + ".json")).read_bytes()
            predecessor = snapshot_from_bytes(raw, self.epoch, kind=self.kind, expected_id=previous)
            if parse_bytes(predecessor.manifest_bytes)["sequence"] != manifest["sequence"] - 1:
                deny("Committed snapshot ancestry is inconsistent.")
            candidate = predecessor
        deny("Position snapshot is not a proven committed ancestor.")
