"""Dormant, owner-neutral family facade for canonical V2 research publication.

The caller supplies facts, identities and clocks. Explicit ``initialize`` is
the only initialization entry point. ContinuousResearchExporterV2 remains the
sole implementation of wire bytes, persistence, recovery, conflicts and FINAL;
its exporter profile records implementation provenance, not factual ownership.

Root admission rejects static filesystem aliases in a trusted isolated operator
workspace. It is not an OS sandbox against malicious concurrent path changes.
Science custody, eligibility, outcome attachment and runtime control are absent.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Mapping, Sequence
import os
import stat

from momentum_hunter.continuous_research_export import (
    PUBLICATION_FILE,
    STAGING_FILE,
    ContinuousResearchExportError,
    ContinuousResearchExporterV2,
    FinalizationResult,
    PublicationResult,
)
from momentum_hunter.strategy_science_recorder.canonical import require_sha256
from momentum_hunter.strategy_science_recorder.contract import (
    REPAIRED_EXPORT_SCHEMA_VERSION,
    REPAIRED_SOURCE_CONTRACT,
    REPAIRED_SOURCE_CONTRACT_VERSION,
    SCIENCE_OFFLINE_EXPORT_PROFILE_V2,
    require_identity,
    validate_export_payload_profile,
)


class ResearchFactExportError(ContinuousResearchExportError):
    """A producer descriptor, family composition or root was not admitted."""


def _absolute_root(value: Path, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path == Path(path.anchor):
        raise ResearchFactExportError(f"{label} must be an explicit non-volume absolute root without traversal.")
    if os.name == "nt" and (
        str(path).startswith(("\\\\?\\", "\\\\.\\"))
        or any(":" in part or part.endswith((".", " ")) for part in path.parts[1:])
    ):
        raise ResearchFactExportError(f"{label} contains an ambiguous Windows path component.")
    for ancestor in (*reversed(path.parents), path):
        try:
            info = ancestor.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ResearchFactExportError(f"{label} contains a symlink or reparse point.")
        if not stat.S_ISDIR(info.st_mode):
            raise ResearchFactExportError(f"{label} contains a non-directory component.")
    return path.resolve()


def _admit_roots(root: Path, custody: tuple[Path, ...], protected: tuple[Path, ...]) -> None:
    admitted = _absolute_root(root, "export_root")
    for label, paths in (("science_custody_roots", custody), ("protected_roots", protected)):
        if not paths:
            raise ResearchFactExportError(f"{label} must explicitly declare at least one root.")
        for path in paths:
            other = _absolute_root(path, label)
            if admitted.is_relative_to(other) or other.is_relative_to(admitted):
                raise ResearchFactExportError(f"export_root overlaps {label}.")
    if not admitted.exists():
        return
    links: dict[tuple[int, int], list[tuple[Path, os.stat_result]]] = {}
    pending = [admitted]
    while pending:
        for path in pending.pop().iterdir():
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ResearchFactExportError("export_root contains a symlink or reparse point.")
            if stat.S_ISDIR(info.st_mode):
                pending.append(path)
            elif stat.S_ISREG(info.st_mode):
                if info.st_nlink > 1:
                    links.setdefault((info.st_dev, info.st_ino), []).append((path, info))
            else:
                raise ResearchFactExportError("export_root contains a nonregular filesystem object.")
    for aliases in links.values():
        # The existing publisher may crash between link and unlink. Only that
        # internal staging/publication pair is admissible; recovery stays its job.
        names = [path.relative_to(admitted) for path, _info in aliases]
        stage = [p for p in names if p.parent == Path("staging") and STAGING_FILE.fullmatch(p.name)]
        published = [p for p in names if p.parent == Path("published") and PUBLICATION_FILE.fullmatch(p.name)]
        if len(aliases) != 2 or any(info.st_nlink != 2 for _p, info in aliases) or len(stage) != 1 or len(published) != 1:
            raise ResearchFactExportError("export_root contains an external or unrecognized hardlink alias.")


class ResearchFactExporterV2:
    """Compose named owner facts; never accept raw envelopes or Science input.

    Every descriptor/version and both isolation-root sets are explicit. The
    descriptor is privately copied at construction and bound durably by the
    existing publisher at initialization/restart. No service or runtime is wired.
    """

    def __init__(
        self, export_root: Path, *, session_id: Mapping[str, object],
        source_owner_identity: str, source_interface_identity: str,
        source_root_identity: str, schema_version: str, source_contract: str,
        source_contract_version: str, offline_reference_profile: str,
        science_custody_roots: Sequence[Path], protected_roots: Sequence[Path],
    ) -> None:
        expected = (
            (schema_version, REPAIRED_EXPORT_SCHEMA_VERSION),
            (source_contract, REPAIRED_SOURCE_CONTRACT),
            (source_contract_version, REPAIRED_SOURCE_CONTRACT_VERSION),
            (offline_reference_profile, SCIENCE_OFFLINE_EXPORT_PROFILE_V2),
        )
        if any(value != canonical for value, canonical in expected):
            raise ResearchFactExportError("Only the exact canonical V2 producer profile is admitted.")
        for value in (source_owner_identity, source_interface_identity):
            if not isinstance(value, str) or not value.strip():
                raise ResearchFactExportError("Source owner and interface identities must be explicit nonempty text.")
        require_identity(session_id, "session_id", kinds=frozenset({"SESSION_ID"}))
        require_sha256(source_root_identity, "source_root_identity")
        self._root = Path(export_root)
        self._custody = tuple(Path(path) for path in science_custody_roots)
        self._protected = tuple(Path(path) for path in protected_roots)
        _admit_roots(self._root, self._custody, self._protected)
        self._descriptor = deepcopy({
            "session_id": session_id,
            "source_owner_identity": source_owner_identity,
            "source_interface_identity": source_interface_identity,
            "source_root_identity": source_root_identity,
        })
        self._publisher: ContinuousResearchExporterV2 | None = None

    def initialize(self) -> "ResearchFactExporterV2":
        """Explicitly acquire this export root and recover its canonical bytes."""
        if self._publisher is not None:
            raise ResearchFactExportError("This facade has already been initialized; construct a new facade to restart.")
        _admit_roots(self._root, self._custody, self._protected)
        self._publisher = ContinuousResearchExporterV2(self._root, **deepcopy(self._descriptor))
        return self

    def _writer(self) -> ContinuousResearchExporterV2:
        if self._publisher is None:
            raise ResearchFactExportError("Explicit initialize is required before publication.")
        _admit_roots(self._root, self._custody, self._protected)
        return self._publisher

    def start(
        self, manifest: Mapping[str, object], *, stream_id: str,
        source_event_id: str, emitted_at: str, event_time: str, effective_known_at: str,
    ) -> PublicationResult:
        if not event_time or not effective_known_at:
            raise ResearchFactExportError("START requires explicit source clocks; no clock fallback is admitted.")
        return self._writer().start(
            deepcopy(manifest), stream_id=stream_id, source_event_id=source_event_id,
            emitted_at=emitted_at, event_time=event_time, effective_known_at=effective_known_at,
        )

    def discovery_cycle(
        self, cycle: Mapping[str, object], observations: Sequence[Mapping[str, object]],
        *, stream_id: str, source_event_id: str, emitted_at: str,
    ) -> PublicationResult:
        """Publish all supplied rows against the owner's independent declaration.

        Count/order are never inferred or repaired. A PARTIAL/FAILED cycle still
        carries every row it actually returned; zero rows remain an explicit fact.
        """
        payload = deepcopy({"discovery_cycle": cycle, "observations": list(observations)})
        validate_export_payload_profile("DISCOVERY_CYCLE", payload, export_schema_version=REPAIRED_EXPORT_SCHEMA_VERSION)
        declared = payload["discovery_cycle"]
        rows = payload["observations"]
        ids = [row["observation_id"] for row in rows]
        if declared["returned_row_count"] != len(rows) or declared["observation_ids_in_source_order"] != ids:
            raise ResearchFactExportError("Discovery denominator differs from the owner's declared count or order.")
        if any(row["discovery_cycle_id"] != declared["discovery_cycle_id"] or row["source_row_ordinal"] != index for index, row in enumerate(rows)):
            raise ResearchFactExportError("Discovery rows must retain their declared cycle and contiguous source ordinals.")
        if len({identity["recorder_id"] for identity in ids}) != len(ids):
            raise ResearchFactExportError("Discovery repeats an observation identity.")
        if declared["zero_result"] != (declared["cycle_state"] == "ZERO_RESULT") or (declared["zero_result"] and rows):
            raise ResearchFactExportError("Discovery zero-result state contradicts its explicit rows or state.")
        return self._writer().publish_event("DISCOVERY_CYCLE", payload, stream_id=stream_id, source_event_id=source_event_id, emitted_at=emitted_at)

    def decision(
        self, decision_event: Mapping[str, object], *,
        reference_plan: Mapping[str, object] | None = None,
        stream_id: str, source_event_id: str, emitted_at: str,
    ) -> PublicationResult:
        """Compose only the decision and an optional actual owner-created plan."""
        payload = {"decision_event": deepcopy(decision_event)}
        if reference_plan is not None:
            payload["reference_plan"] = deepcopy(reference_plan)
        return self._writer().publish_event("DECISION_FACT", payload, stream_id=stream_id, source_event_id=source_event_id, emitted_at=emitted_at)

    def market_snapshot(
        self, market_snapshot: Mapping[str, object], *,
        stream_id: str, source_event_id: str, emitted_at: str,
    ) -> PublicationResult:
        return self._writer().publish_event("MARKET_FACT", {"market_snapshot": deepcopy(market_snapshot)}, stream_id=stream_id, source_event_id=source_event_id, emitted_at=emitted_at)

    def provider_health(
        self, provider_health_event: Mapping[str, object], *,
        stream_id: str, source_event_id: str, emitted_at: str,
    ) -> PublicationResult:
        return self._writer().publish_event("PROVIDER_HEALTH", {"provider_health_event": deepcopy(provider_health_event)}, stream_id=stream_id, source_event_id=source_event_id, emitted_at=emitted_at)

    def finalize(
        self, *, stream_id: str, source_event_id: str, closed_at: str,
        close_reason: str, terminal_proven: bool, pending_source_events: int,
        source_gap_count: int, upstream_conflict_count: int,
    ) -> FinalizationResult:
        return self._writer().finalize(
            stream_id=stream_id, source_event_id=source_event_id, closed_at=closed_at,
            close_reason=close_reason, terminal_proven=terminal_proven,
            pending_source_events=pending_source_events, source_gap_count=source_gap_count,
            upstream_conflict_count=upstream_conflict_count,
        )

    def published(self) -> tuple[PublicationResult, ...]:
        return self._writer().published()

    def close(self) -> None:
        """Close through the publisher after root readmission.

        If a root alias appeared, fail closed and retain the existing lock:
        canonical close writes a checkpoint, so an ambiguous path cannot be
        touched. The operator must resolve that anomaly before retrying close.
        """
        if self._publisher is not None:
            self._writer().close()


__all__ = ["ResearchFactExportError", "ResearchFactExporterV2"]
