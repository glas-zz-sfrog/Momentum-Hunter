"""Isolated live, read-only qualification for the continuous research stack.

This module is intentionally absent from production scheduling. It may read
Finviz and Schwab market data, but it has no broker, position, order, Shadow,
service, scheduler, or production-store capability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from contextlib import ExitStack
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Protocol
from zoneinfo import ZoneInfo

from momentum_hunter.automatic_candle_backfill import (
    ACTIVE_STATES,
    TERMINAL_STATES,
    AutomaticCandleBackfillCoordinator,
)
from momentum_hunter.broad_discovery import DiscoveryPaginationPolicy, DiscoverySnapshot
from momentum_hunter.continuous_composition import (
    READY,
    CompositionMemberInput,
    ContinuousCompositionCycle,
    ContinuousCompositionPolicy,
    assess_readiness,
    build_readiness_request,
)
from momentum_hunter.continuous_denominator import (
    ContinuousDenominatorResult,
    produce_continuous_denominator,
)
from momentum_hunter.continuous_natural_setup import (
    ContinuousNaturalSetupCoordinator,
)
from momentum_hunter.continuous_evidence_writer import (
    OFFLINE_REVIEW,
    AuthenticatedEvidenceWriterClient,
    DedicatedEvidenceWriter,
    build_continuous_writer_topology_v2,
    create_ephemeral_writer_capability,
    read_evidence_snapshot,
)
from momentum_hunter.continuous_runtime import (
    CANONICAL_BAR_COMPLETED,
    DATA_RECOVERED,
    READINESS_CHANGED,
    CompositionRequest,
    CompositionResult,
    ContinuousOpportunityRuntime,
    ContinuousRuntimeConfig,
    DenominatorRequest,
    DenominatorResult,
    DiscoveryPulse,
    DiscoveryRequest,
    LogicalRuntimeLeaseRegistry,
    QueueCapacities,
    PREMARKET_DEFERRED,
    ReadinessRequest,
    ReadinessResult,
    RuntimeCadence,
    RuntimeCheckpointStore,
    RuntimeTriggerEvent,
)
from momentum_hunter.continuous_time_identity import (
    canonical_instant,
    canonical_known_at,
    parse_instant,
)
from momentum_hunter.continuous_tradeplan_producer import (
    HISTORY_BACKFILL_PENDING,
    ContinuousHistoryAdmissionCoordinator,
    ContinuousTradePlanProducer,
    ContinuousTradePlanProducerStore,
    CurrentMarketEvidence,
    HistoricalContextEvidence,
    InstrumentAdmissionEvidence,
    build_current_market_evidence,
    unavailable_instrument_admission,
)
from momentum_hunter.hot_universe import (
    DUPLICATE,
    EXPIRED,
    HOT,
    PROTECTED,
    PROVIDER_BOUND,
    TRACKED,
    WARM,
    HotUniversePolicy,
    HotUniverseResult,
    HotUniverseSummary,
    HotUniverseStore,
)
from momentum_hunter.models import INSTITUTIONAL_MOMENTUM
from momentum_hunter.opportunity_denominator import (
    LIVE_READ_ONLY_QUALIFICATION,
    PROSPECTIVE,
)
from momentum_hunter.prospective_denominator import (
    ProspectiveActivationRecord,
    ProspectiveDenominatorStore,
    load_activation_record,
)
from momentum_hunter.providers import FinvizProvider
from momentum_hunter.schwab_candle_backfill import (
    CandleBackfillOptions,
    SchwabHistoricalCandleBackfiller,
    explicit_universe,
)
from momentum_hunter.schwab_candle_contract import EASTERN_TZ
from momentum_hunter.schwab_candle_observer import SchwabMarketDataOnlyAccessGuard
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.schwab_daily_candle_store import SchwabDailyCandleStore
from momentum_hunter.schwab_market_data import (
    SchwabMarketDataQuoteSource,
    SchwabReadOnlyAccessTokenProvider,
)
from momentum_hunter.time_normalized_rvol import load_time_normalized_rvol_evidence


MODE = "AUG17_INTEGRATION_LIVE_READ_ONLY_QUALIFICATION"
AUTHORITY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY = "NONE"
ORDER_CAPABILITY = "UNAVAILABLE"
CENTRAL = ZoneInfo("America/Chicago")
MAX_READY_SYMBOLS = 3
REGULAR_OPEN = datetime.strptime("09:30", "%H:%M").time()
REGULAR_CLOSE = datetime.strptime("16:00", "%H:%M").time()


class LiveQualificationError(RuntimeError):
    """Raised when the qualification boundary or evidence fails closed."""


class LiveSchwabAuthFailure(LiveQualificationError):
    def __init__(self, diagnostic_code: str) -> None:
        super().__init__(
            "Schwab canonical evidence was unavailable because authentication failed."
        )
        self.diagnostic_code = diagnostic_code


class LiveCompositionEvidenceError(LiveQualificationError):
    def __init__(
        self,
        diagnostic_code: str,
        message: str,
        *,
        request_cutoff: str,
        evidence_known_at: tuple[tuple[str, str], ...],
    ) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code
        self.request_cutoff = request_cutoff
        self.evidence_known_at = evidence_known_at


@dataclass
class _QualificationResourceBundle:
    stack: ExitStack
    capability: object
    writer: DedicatedEvidenceWriter
    client: AuthenticatedEvidenceWriterClient
    checkpoints: RuntimeCheckpointStore
    runtime_holder: dict[str, object]
    audit: dict[str, object]

    @property
    def runtime(self) -> ContinuousOpportunityRuntime:
        runtime = self.runtime_holder.get("runtime")
        if runtime is None:
            raise LiveQualificationError("Qualification runtime resource is unavailable.")
        return runtime  # type: ignore[return-value]

    def replace_runtime(self, runtime: ContinuousOpportunityRuntime) -> None:
        self.runtime_holder["runtime"] = runtime
        self.runtime_holder["active"] = True

    def shutdown_current(self, now: datetime):
        self.audit["runtimeShutdownAttempted"] = True
        try:
            health = self.runtime.shutdown(now)
        except Exception as exc:
            self.audit["runtimeShutdownError"] = type(exc).__name__
            raise
        else:
            self.audit["runtimeShutdownCompleted"] = True
            return health
        finally:
            self.runtime_holder["active"] = False

    def close(self) -> None:
        self.stack.close()


def _resource_cleanup_receipt(audit: Mapping[str, object]) -> dict[str, object]:
    receipt = dict(audit)
    writer_required = receipt.get("writerCreated") is True
    capability_required = receipt.get("capabilityCreated") is True
    runtime_required = receipt.get("runtimeCreated") is True
    writer_released = not writer_required or (
        receipt.get("writerReleaseAttempted") is True
        and receipt.get("writerClosed") is True
    )
    capability_released = not capability_required or (
        receipt.get("capabilityReleaseAttempted") is True
        and receipt.get("capabilityClosed") is True
    )
    runtime_released = (
        not runtime_required or receipt.get("runtimeShutdownAttempted") is True
    )
    receipt["writerReleaseRequired"] = writer_required
    receipt["capabilityReleaseRequired"] = capability_required
    receipt["runtimeShutdownRequired"] = runtime_required
    receipt["writerReleaseSatisfied"] = writer_released
    receipt["capabilityReleaseSatisfied"] = capability_released
    receipt["runtimeShutdownSatisfied"] = runtime_released
    receipt["status"] = (
        "PASS"
        if writer_released and capability_released and runtime_released
        else "FAIL"
    )
    receipt["recordedAt"] = _aware_now().isoformat()
    receipt["authority"] = AUTHORITY
    receipt["executionAuthority"] = EXECUTION_AUTHORITY
    receipt["fingerprint"] = _fingerprint(
        "live-qualification-resource-cleanup-v1",
        receipt,
    )
    return receipt


def _acquire_qualification_resources(
    *,
    root: Path,
    topology,
    runtime_id: str,
    config: ContinuousRuntimeConfig,
    discovery,
    market,
    events,
    composition,
    denominator,
    leases: LogicalRuntimeLeaseRegistry,
    launch_at: datetime,
    checkpoint_store_factory=RuntimeCheckpointStore,
    runtime_factory=ContinuousOpportunityRuntime,
) -> _QualificationResourceBundle:
    audit: dict[str, object] = {
        "capabilityCreated": False,
        "capabilityReleaseAttempted": False,
        "capabilityClosed": False,
        "writerCreated": False,
        "writerActivated": False,
        "writerReleaseAttempted": False,
        "writerClosed": False,
        "checkpointStoreCreated": False,
        "runtimeCreated": False,
        "runtimeStartAttempted": False,
        "runtimeStarted": False,
        "runtimeShutdownAttempted": False,
        "runtimeShutdownCompleted": False,
    }
    stack = ExitStack()
    capability = create_ephemeral_writer_capability()
    audit["capabilityCreated"] = True

    def close_capability() -> None:
        audit["capabilityReleaseAttempted"] = True
        try:
            capability.close()
        finally:
            audit["capabilityClosed"] = capability.closed

    stack.callback(close_capability)
    try:
        writer = DedicatedEvidenceWriter(topology)
        audit["writerCreated"] = True

        def close_writer() -> None:
            audit["writerReleaseAttempted"] = True
            try:
                writer.close()
            finally:
                audit["writerClosed"] = writer.closed

        stack.callback(close_writer)
        writer.activate_session(
            capability=capability,
            source_identity=runtime_id,
        )
        audit["writerActivated"] = True
        client = AuthenticatedEvidenceWriterClient(
            topology=topology,
            capability=capability,
            runtime_instance_id=runtime_id,
            writer=writer,
            maximum_ack_seconds=2.0,
        )
        checkpoints = checkpoint_store_factory(root / "checkpoint")
        audit["checkpointStoreCreated"] = True
        runtime = runtime_factory(
            config=config,
            runtime_instance_id=runtime_id,
            discovery_source=discovery,
            market_data_source=market,
            event_source=events,
            composition_source=composition,
            denominator_source=denominator,
            writer=client,
            lease_registry=leases,
            checkpoint_store=checkpoints,
        )
        audit["runtimeCreated"] = True
        holder: dict[str, object] = {"runtime": runtime, "active": True}

        def shutdown_runtime() -> None:
            if holder.get("active") is not True:
                return
            audit["runtimeShutdownAttempted"] = True
            try:
                runtime_value = holder.get("runtime")
                if runtime_value is not None:
                    runtime_value.shutdown(_aware_now())
                    audit["runtimeShutdownCompleted"] = True
            except Exception as exc:
                audit["runtimeShutdownError"] = type(exc).__name__
            finally:
                holder["active"] = False

        stack.callback(shutdown_runtime)
        bundle = _QualificationResourceBundle(
            stack=stack,
            capability=capability,
            writer=writer,
            client=client,
            checkpoints=checkpoints,
            runtime_holder=holder,
            audit=audit,
        )
        audit["runtimeStartAttempted"] = True
        runtime.start(launch_at)
        audit["runtimeStarted"] = True
        return bundle
    except Exception:
        try:
            stack.close()
        finally:
            _write_once(
                root / "resource-cleanup.json",
                _canonical_bytes(_resource_cleanup_receipt(audit)),
            )
        raise


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes({"domain": domain, "value": value})
    ).hexdigest()


def _aware_now() -> datetime:
    return datetime.now().astimezone()


def _parse_timestamp(value: str) -> datetime:
    return parse_instant(value)


def _backfill_accounting(path: Path) -> dict[str, object]:
    if not path.exists():
        return {
            "ledgerPresent": False,
            "symbolsRepresented": 0,
            "attempts": 0,
            "successful": 0,
            "failed": 0,
            "active": 0,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveQualificationError(
            "Continuous backfill ledger is unreadable."
        ) from exc
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(records, Mapping):
        raise LiveQualificationError(
            "Continuous backfill ledger omitted its records."
        )
    values = tuple(
        item for item in records.values() if isinstance(item, Mapping)
    )
    if len(values) != len(records):
        raise LiveQualificationError(
            "Continuous backfill ledger contains an invalid record."
        )
    statuses = tuple(str(item.get("status", "")).upper() for item in values)
    return {
        "ledgerPresent": True,
        "symbolsRepresented": len(values),
        "attempts": sum(int(item.get("attemptCount", 0)) for item in values),
        "successful": sum(item in {"COMPLETE", "PARTIAL"} for item in statuses),
        "failed": sum(item == "FAILED" for item in statuses),
        "active": sum(item in ACTIVE_STATES for item in statuses),
        "records": [
            {
                "symbol": str(item.get("symbol", "")),
                "status": str(item.get("status", "")),
                "attemptCount": int(item.get("attemptCount", 0)),
                "requestedAt": item.get("requestedAt"),
                "startedAt": item.get("startedAt"),
                "completedAt": item.get("completedAt"),
            }
            for item in values
        ],
    }


def validate_qualification_root(
    root: Path,
    *,
    canonical_root: Path | None = None,
) -> Path:
    resolved = root.expanduser().resolve(strict=False)
    lowered = str(resolved).lower()
    if any(
        item in lowered
        for item in ("momentumhunterdata", "programdata\\momentumhunter", "\\.git")
    ):
        raise LiveQualificationError(
            "Qualification output overlaps a protected or production path."
        )
    if canonical_root is not None:
        canonical = canonical_root.expanduser().resolve(strict=False)
        if (
            resolved == canonical
            or canonical in resolved.parents
            or resolved in canonical.parents
        ):
            raise LiveQualificationError(
                "Qualification output overlaps the canonical checkout."
            )
    return resolved


def _write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise LiveQualificationError(
                f"Conflicting write-once evidence exists: {path.name}"
            )
        return
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _git_identity(root: Path) -> dict[str, object]:
    def run(*arguments: str) -> str:
        completed = subprocess.run(
            ("git", *arguments),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status": run("status", "--porcelain"),
    }


@dataclass
class QualificationMetrics:
    discovery_cycles: int = 0
    finviz_pages: int = 0
    finviz_rows: int = 0
    unique_symbols: set[str] = field(default_factory=set)
    midday_new_symbols: set[str] = field(default_factory=set)
    tier_transitions: int = 0
    schwab_refreshes: int = 0
    schwab_quote_symbols: int = 0
    schwab_minute_rows: int = 0
    schwab_daily_rows: int = 0
    schwab_market_data_successes: int = 0
    candle_readiness_successes: int = 0
    last_successful_schwab_read: str | None = None
    auth_health: dict[str, object] = field(default_factory=dict)
    canonical_ready_symbols: set[str] = field(default_factory=set)
    readiness_deferred: int = 0
    composition_cycles: set[str] = field(default_factory=set)
    research_plans: set[str] = field(default_factory=set)
    successor_setups: set[str] = field(default_factory=set)
    system_failed_cycles: int = 0
    provider_recovery_events: int = 0
    writer_errors: int = 0
    provider_failures: list[str] = field(default_factory=list)


@dataclass
class QualificationState:
    root: Path
    launch_at: datetime
    now_provider: Callable[[], datetime] | None = None
    allow_persistent: bool = False
    metrics: QualificationMetrics = field(default_factory=QualificationMetrics)
    snapshot: DiscoverySnapshot | None = None
    universe: HotUniverseResult | None = None
    readiness_inputs: dict[str, CompositionMemberInput] = field(default_factory=dict)
    historical_contexts: dict[str, HistoricalContextEvidence] = field(default_factory=dict)
    current_market_evidence: dict[str, CurrentMarketEvidence] = field(default_factory=dict)
    instrument_admissions: dict[str, InstrumentAdmissionEvidence] = field(default_factory=dict)
    material_event_fingerprints: dict[str, str] = field(default_factory=dict)
    material_event_known_at: dict[str, str] = field(default_factory=dict)
    cycles: dict[str, ContinuousCompositionCycle] = field(default_factory=dict)
    denominator_results: dict[str, ContinuousDenominatorResult] = field(
        default_factory=dict
    )
    refreshed_snapshot_id: str = ""
    configuration_fingerprint: str = ""

    def now(self) -> datetime:
        return self.now_provider() if self.now_provider is not None else _aware_now()


class LiveDiscoverySource:
    def __init__(self, state: QualificationState, *, provider: object | None = None) -> None:
        self.state = state
        self.provider = provider or FinvizProvider(backoff_seconds=())
        self.pagination = DiscoveryPaginationPolicy(
            max_pages=3,
            max_rows=60,
            maximum_elapsed_time_seconds=30.0,
            per_page_timeout_seconds=8.0,
            inter_request_delay_seconds=0.5,
            policy_version="aug17-live-qualification-pagination-v1",
        )
        self.policy = HotUniversePolicy(
            policy_version="aug17-live-qualification-hot-universe-v1",
            maximum_tracked_symbols=60,
            maximum_hot_symbols=MAX_READY_SYMBOLS,
            maximum_warm_symbols=12,
            fairness_promotion_after_provider_bound_observations=3,
        )
        self.store = HotUniverseStore(
            state.root / "state" / "hot-universe.json",
            allow_persistent=state.allow_persistent,
        )
        self._restore_current_generation()

    def _restore_current_generation(self) -> None:
        restored = self.store.load()
        session_date = self.state.launch_at.astimezone(EASTERN_TZ).date().isoformat()
        if restored.current_session_date != session_date or not restored.snapshot_receipts:
            return
        receipt = restored.snapshot_receipts[-1]
        path = (
            self.state.root
            / "source-evidence"
            / "finviz"
            / f"{receipt.snapshot_id}.json"
        )
        try:
            snapshot_payload = json.loads(path.read_text(encoding="ascii"))
            snapshot = DiscoverySnapshot.from_dict(snapshot_payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise LiveQualificationError(
                "Persisted hot-universe generation omitted its trusted discovery snapshot."
            ) from exc
        if (
            snapshot.snapshot_id != receipt.snapshot_id
            or snapshot.fingerprint != receipt.snapshot_fingerprint
        ):
            raise LiveQualificationError(
                "Persisted hot-universe and discovery identities conflict."
            )
        tracked = tuple(
            item for item in restored.members if item.current_state == TRACKED
        )
        summary = HotUniverseSummary(
            total_members=len(restored.members),
            protected=sum(item.current_tier == PROTECTED for item in tracked),
            hot=sum(item.current_tier == HOT for item in tracked),
            warm=sum(item.current_tier == WARM for item in tracked),
            provider_bound=sum(
                item.current_tier == PROVIDER_BOUND for item in tracked
            ),
            expired_this_session=sum(
                item.current_tier == EXPIRED for item in restored.members
            ),
            admitted_this_pulse=0,
            rediscovered_this_pulse=0,
            rejected_observations_this_pulse=0,
            source_absent_observations_this_pulse=0,
            discovery_failures_this_pulse=0,
            promotions_this_pulse=0,
            demotions_this_pulse=0,
            expirations_this_pulse=0,
        )
        self.state.snapshot = snapshot
        self.state.universe = HotUniverseResult(
            status=DUPLICATE,
            state=restored,
            transitions=(),
            summary=summary,
        )
        self.state.refreshed_snapshot_id = snapshot.snapshot_id

    def discover(self, request: DiscoveryRequest) -> DiscoveryPulse:
        predecessor_state = self.store.load()
        previous = {
            item.symbol
            for item in predecessor_state.members
            if item.current_state == TRACKED
        }
        try:
            snapshot = self.provider.discover_paginated(
                INSTITUTIONAL_MOMENTUM,
                pagination_policy=self.pagination,
                requested_at=_parse_timestamp(request.requested_at),
                evaluated_at=self.state.now(),
            )
            universe = self.store.apply_snapshot(
                policy=self.policy,
                snapshot=snapshot,
                recorded_at=self.state.now(),
            )
        except Exception as exc:
            self.state.metrics.provider_failures.append(
                f"FINVIZ:{type(exc).__name__}"
            )
            raise
        active = {
            item.symbol
            for item in universe.state.members
            if item.current_state == TRACKED
        }
        new = active.difference(previous)
        if self.state.metrics.discovery_cycles:
            self.state.metrics.midday_new_symbols.update(new)
        hot = tuple(
            item.symbol
            for item in universe.state.members
            if item.current_state == TRACKED and item.current_tier == HOT
        )
        self.state.snapshot = snapshot
        self.state.universe = universe
        self.state.readiness_inputs.clear()
        self.state.refreshed_snapshot_id = ""
        metrics = self.state.metrics
        metrics.discovery_cycles += 1
        metrics.finviz_pages += snapshot.pages_received
        metrics.finviz_rows += snapshot.represented_row_count
        metrics.unique_symbols.update(item.symbol for item in snapshot.rows)
        metrics.tier_transitions += len(universe.transitions)
        _write_once(
            self.state.root
            / "source-evidence"
            / "finviz"
            / f"{snapshot.snapshot_id}.json",
            snapshot.canonical_json().encode("ascii"),
        )
        return DiscoveryPulse(
            pulse_id=snapshot.snapshot_id,
            fingerprint=snapshot.fingerprint,
            source_rows_represented=snapshot.represented_row_count,
            symbols_for_readiness=hot,
            new_symbols=tuple(sorted(new)),
            retained_symbols=tuple(sorted(active.intersection(previous))),
            provider_bound_symbols=(),
            evidence_payload_json=_canonical_bytes(
                {
                    "schemaVersion": 2,
                    "profile": "continuous-live-discovery-evidence-v2",
                    "snapshot": snapshot.to_dict(),
                    "universe": {
                        "status": universe.status,
                        "state": {
                            "schemaVersion": universe.state.schema_version,
                            "profile": universe.state.profile,
                            "policyVersion": universe.state.policy_version,
                            "policyFingerprint": universe.state.policy_fingerprint,
                            "currentSessionDate": universe.state.current_session_date,
                            "members": [
                                asdict(item) for item in universe.state.members
                            ],
                            "transitionCount": len(universe.state.transitions),
                            "snapshotReceiptCount": len(
                                universe.state.snapshot_receipts
                            ),
                            "failureReceiptCount": len(
                                universe.state.failure_receipts
                            ),
                            "fingerprint": universe.state.fingerprint,
                        },
                        "transitionDelta": [
                            asdict(item) for item in universe.transitions
                        ],
                        "summary": asdict(universe.summary),
                        "predecessor": {
                            "universeFingerprint": predecessor_state.fingerprint,
                            "snapshotId": (
                                predecessor_state.snapshot_receipts[-1].snapshot_id
                                if predecessor_state.snapshot_receipts
                                else None
                            ),
                            "snapshotFingerprint": (
                                predecessor_state.snapshot_receipts[-1].snapshot_fingerprint
                                if predecessor_state.snapshot_receipts
                                else None
                            ),
                        },
                    },
                    "authority": AUTHORITY,
                    "executionAuthority": EXECUTION_AUTHORITY,
                    "orderCapability": ORDER_CAPABILITY,
                }
            ).decode("ascii"),
        )


class QualificationMarketDataBoundary(Protocol):
    def auth_health(self) -> dict[str, object]: ...

    def current_evidence(
        self,
        symbol: str,
        cutoff: datetime,
    ) -> CurrentMarketEvidence: ...

    def decision_cutoff(self) -> datetime: ...

    def backfill(
        self,
        symbols: tuple[str, ...],
        *,
        minute_store_root: Path,
        daily_store_root: Path,
    ) -> Mapping[str, object]: ...


class LiveMarketDataSource:
    def __init__(
        self,
        state: QualificationState,
        *,
        expected_account_ending: str,
        provider_boundary: QualificationMarketDataBoundary | None = None,
    ) -> None:
        self.state = state
        self.expected_account_ending = expected_account_ending
        self.provider_boundary = provider_boundary
        self.minute_root = state.root / "market-data" / "minute"
        self.daily_root = state.root / "market-data" / "daily"
        self.token_provider = (
            SchwabReadOnlyAccessTokenProvider()
            if provider_boundary is None
            else None
        )
        self.access_guard = (
            SchwabMarketDataOnlyAccessGuard(token_provider=self.token_provider)
            if self.token_provider is not None
            else None
        )
        self.quote_source = (
            SchwabMarketDataQuoteSource(token_provider=self.token_provider)
            if self.token_provider is not None
            else None
        )
        self.composition_policy = ContinuousCompositionPolicy(
            required_recent_minute_bars=1,
        )
        self.backfill = AutomaticCandleBackfillCoordinator(
            state_path=state.root / "state" / "continuous-history-backfill.json",
            minute_store_root=self.minute_root,
            daily_store_root=self.daily_root,
            run_backfill=self._run_bounded_backfill,
            utc_clock=self.state.now,
        )
        self.history_admission = ContinuousHistoryAdmissionCoordinator(
            minute_store_root=self.minute_root,
            daily_store_root=self.daily_root,
            backfill=self.backfill,
            policy=self.composition_policy,
        )

    def _sync_auth_metrics(self) -> None:
        self.state.metrics.auth_health = (
            self.provider_boundary.auth_health()
            if self.provider_boundary is not None
            else self.token_provider.metrics_snapshot()
        )

    @staticmethod
    def _failure_code(exc: BaseException) -> str:
        current: BaseException | None = exc
        visited: set[int] = set()
        while current is not None and id(current) not in visited:
            code = getattr(current, "diagnostic_code", None)
            if isinstance(code, str) and code:
                return (
                    "SCHWAB_INTERACTIVE_REAUTH_REQUIRED"
                    if code == "SCHWAB_REAUTH_REQUIRED"
                    else code
                )
            visited.add(id(current))
            current = current.__cause__ or current.__context__
        return type(exc).__name__

    @staticmethod
    def _history_failure_code(error: object) -> str:
        mapping = {
            "SchwabCandleObserverReauthorizationRequired": "SCHWAB_INTERACTIVE_REAUTH_REQUIRED",
            "SchwabCandleObserverAuthStateMissingError": "SCHWAB_AUTH_STATE_MISSING",
            "SchwabCandleObserverSecureStoreError": "SCHWAB_AUTH_SECURE_STORE_FAILED",
            "SchwabCandleObserverRefreshFailed": "SCHWAB_AUTH_REFRESH_FAILED",
            "SchwabCandleObserverHttpUnauthorizedError": "SCHWAB_HTTP_UNAUTHORIZED",
            "SchwabCandleObserverHttpForbiddenError": "SCHWAB_HTTP_FORBIDDEN",
        }
        value = str(error or "").strip()
        return mapping.get(value, value)

    def _run_bounded_backfill(self, symbols: tuple[str, ...]) -> dict[str, object]:
        try:
            result = (
                self.provider_boundary.backfill(
                    symbols,
                    minute_store_root=self.minute_root,
                    daily_store_root=self.daily_root,
                )
                if self.provider_boundary is not None
                else SchwabHistoricalCandleBackfiller(
                    minute_store=SchwabCandleStore(self.minute_root),
                    daily_store=SchwabDailyCandleStore(self.daily_root),
                    access_guard=self.access_guard,
                ).backfill(
                    explicit_universe(symbols),
                    CandleBackfillOptions(
                        expected_account_ending=self.expected_account_ending,
                        minute_lookback_days=10,
                        daily_lookback_days=365,
                        history_attempts=2,
                    ),
                )
            )
        except Exception as exc:
            self.state.metrics.provider_failures.append(
                f"SCHWAB_CANDLES:{self._failure_code(exc)}"
            )
            raise
        finally:
            self._sync_auth_metrics()
        auth_failure_codes: set[str] = set()
        for item in result.get("symbols", []):
            for timeframe in ("minute", "daily"):
                evidence = item.get(timeframe, {})
                error = self._history_failure_code(evidence.get("error"))
                if (
                    error.startswith("SCHWAB_AUTH")
                    or error.startswith("SCHWAB_HTTP")
                    or error == "SCHWAB_INTERACTIVE_REAUTH_REQUIRED"
                ):
                    auth_failure_codes.add(error)
                    self.state.metrics.provider_failures.append(
                        f"SCHWAB_CANDLES:{error}"
                    )
        if auth_failure_codes:
            raise LiveSchwabAuthFailure(sorted(auth_failure_codes)[0])
        minute_rows = sum(
            int(item["minute"]["rows"]) for item in result.get("symbols", [])
        )
        daily_rows = sum(
            int(item["daily"]["rows"]) for item in result.get("symbols", [])
        )
        self.state.metrics.schwab_refreshes += 1
        self.state.metrics.schwab_minute_rows += minute_rows
        self.state.metrics.schwab_daily_rows += daily_rows
        self.state.metrics.schwab_market_data_successes += 1
        self.state.metrics.last_successful_schwab_read = (
            self.state.now().isoformat()
        )
        return result

    def _load_current_market_evidence(
        self, symbol: str, cutoff: datetime
    ) -> CurrentMarketEvidence:
        if self.provider_boundary is not None:
            current = self.provider_boundary.current_evidence(symbol, cutoff)
            self.state.metrics.schwab_quote_symbols += 1
            self.state.metrics.schwab_market_data_successes += 1
            self.state.metrics.last_successful_schwab_read = (
                current.receipt_timestamp
            )
            self._sync_auth_metrics()
            return current
        del cutoff
        try:
            quote_batch = self.quote_source.quotes_with_clock((symbol,))
        except Exception as exc:
            self.state.metrics.provider_failures.append(
                f"SCHWAB_QUOTES:{self._failure_code(exc)}"
            )
            self._sync_auth_metrics()
            raise
        quote = quote_batch.quotes.get(symbol)
        if not isinstance(quote, dict):
            raise LiveQualificationError(
                "Schwab current evidence omitted the requested symbol."
            )
        received = self.state.now()
        evidence_payload = {
            "symbol": symbol,
            "quote": quote,
            "clockSkewProof": quote_batch.clock_skew_proof,
        }
        self.state.metrics.schwab_quote_symbols += 1
        self.state.metrics.schwab_market_data_successes += 1
        self.state.metrics.last_successful_schwab_read = received.isoformat()
        self._sync_auth_metrics()
        return build_current_market_evidence(
            symbol=symbol,
            provider_timestamp=str(quote.get("timestamp", "")),
            receipt_timestamp=received.isoformat(),
            source_identity=str(quote.get("source", "")),
            market_payload=evidence_payload,
        )

    def _preserve_admission(
        self,
        *,
        symbol: str,
        context: HistoricalContextEvidence,
        current: CurrentMarketEvidence,
        backfill_evidence: Mapping[str, object] | None,
    ) -> None:
        sanitized = {
            "symbol": symbol,
            "currentMarketEvidence": asdict(current),
            "historicalContext": asdict(context),
            "backfill": dict(backfill_evidence) if backfill_evidence else None,
            "accountValuesRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": ORDER_CAPABILITY,
        }
        admission_fingerprint = _fingerprint(
            "continuous-history-admission-v1", sanitized
        )
        _write_once(
            self.state.root
            / "source-evidence"
            / "schwab"
            / f"continuous-history-admission-{admission_fingerprint[:24]}.json",
            _canonical_bytes(sanitized),
        )

    def evaluate(self, request: ReadinessRequest) -> ReadinessResult:
        if self.state.universe is None or self.state.snapshot is None:
            raise LiveQualificationError("Readiness has no hot-universe state.")
        member = next(
            (
                item
                for item in self.state.universe.state.members
                if item.symbol == request.symbol and item.current_state == TRACKED
            ),
            None,
        )
        if member is None:
            raise LiveQualificationError(
                "Readiness symbol is absent from the current universe."
            )
        evaluated = self.state.now()
        self.state.material_event_fingerprints[request.symbol] = request.source_fingerprint
        self.state.material_event_known_at[request.symbol] = request.requested_at
        eastern = evaluated.astimezone(EASTERN_TZ)
        if (
            eastern.date().isoformat() == member.session_date
            and eastern.time() < REGULAR_OPEN
        ):
            deferred_payload = {
                "requestId": request.request_id,
                "symbol": request.symbol,
                "trigger": request.trigger,
                "sourceFingerprint": request.source_fingerprint,
                "memberId": member.member_id,
                "memberFingerprint": member.fingerprint,
                "snapshotId": self.state.snapshot.snapshot_id,
                "snapshotFingerprint": self.state.snapshot.fingerprint,
                "evaluatedAt": evaluated.isoformat(),
                "sessionDate": member.session_date,
                "status": PREMARKET_DEFERRED,
            }
            self.state.metrics.readiness_deferred += 1
            return ReadinessResult(
                request_id=request.request_id,
                symbol=request.symbol,
                status=PREMARKET_DEFERRED,
                fingerprint=_fingerprint(
                    "continuous-premarket-readiness-deferred-v1",
                    deferred_payload,
                ),
                ready=False,
                failure_reason=None,
                deferred=True,
                opportunity_id=member.member_id,
            )
        admission = self.history_admission.admit(
            member=member,
            cutoff=evaluated,
            current_evidence_loader=self._load_current_market_evidence,
            decision_cutoff_provider=(
                self.provider_boundary.decision_cutoff
                if self.provider_boundary is not None
                else self.state.now
            ),
        )
        decision_cutoff = _parse_timestamp(admission.decision_cutoff)
        evidence = admission.canonical_evidence
        self.state.historical_contexts[request.symbol] = admission.context
        self.state.current_market_evidence[request.symbol] = (
            admission.current_market_evidence
        )
        self.state.instrument_admissions[request.symbol] = (
            unavailable_instrument_admission(
                request.symbol, observed_at=decision_cutoff
            )
        )
        self._preserve_admission(
            symbol=request.symbol,
            context=admission.context,
            current=admission.current_market_evidence,
            backfill_evidence=admission.backfill_evidence,
        )
        rvol = load_time_normalized_rvol_evidence(
            (request.symbol,),
            as_of=decision_cutoff,
            store_root=self.minute_root,
        )[request.symbol]
        exact_request = build_readiness_request(
            member,
            requested_at=decision_cutoff,
            policy=self.composition_policy,
            source_reason=request.trigger,
        )
        assessment = assess_readiness(
            exact_request,
            evidence=evidence,
            rvol_evidence=rvol,
            evaluated_at=decision_cutoff,
            policy=self.composition_policy,
        )
        self.state.metrics.candle_readiness_successes += 1
        self.state.metrics.last_successful_schwab_read = (
            self.state.now().isoformat()
        )
        self._sync_auth_metrics()
        self.state.readiness_inputs[request.symbol] = CompositionMemberInput(
            universe_member_id=member.member_id,
            canonical_evidence=evidence,
            rvol_evidence=rvol,
        )
        ready = assessment.status == READY
        if ready:
            self.state.metrics.canonical_ready_symbols.add(request.symbol)
        evidence_known_at = tuple(
            dict.fromkeys(
                (
                    ("universeMember", member.first_observed_at),
                    *admission.evidence_known_at,
                    (
                        "instrumentAdmission",
                        self.state.instrument_admissions[
                            request.symbol
                        ].observed_at,
                    ),
                    ("rvolAssessment", assessment.evaluated_at),
                    (
                        "materialEvent",
                        self.state.material_event_known_at[request.symbol],
                    ),
                )
            )
        )
        readiness_fingerprint = _fingerprint(
            "continuous-live-readiness-result-v2",
            {
                "assessmentFingerprint": assessment.fingerprint,
                "decisionCutoff": canonical_instant(decision_cutoff),
                "evidenceKnownAt": canonical_known_at(evidence_known_at),
                "sourceFingerprint": request.source_fingerprint,
            },
        )
        return ReadinessResult(
            request_id=request.request_id,
            symbol=request.symbol,
            status=assessment.status,
            fingerprint=readiness_fingerprint,
            ready=ready,
            failure_reason=(
                None if ready else ";".join(assessment.blocker_reasons)
            ),
            decision_cutoff=decision_cutoff.isoformat(),
            evidence_known_at=evidence_known_at,
            opportunity_id=member.member_id,
        )


class LiveCompositionSource:
    def __init__(
        self,
        state: QualificationState,
        *,
        configuration_fingerprint: str | None = None,
        natural_setup: ContinuousNaturalSetupCoordinator | None = None,
    ) -> None:
        self.state = state
        self.policy = ContinuousCompositionPolicy(
            required_recent_minute_bars=1,
        )
        resolved_configuration = (
            str(configuration_fingerprint or state.configuration_fingerprint).strip()
            or _fingerprint(
                "continuous-qualification-producer-configuration-v1",
                {"root": str(state.root.resolve(strict=False))},
            )
        )
        self.producer_store = ContinuousTradePlanProducerStore(
            state.root / "state" / "continuous-tradeplan-producer.json"
        )
        self.producer = ContinuousTradePlanProducer(
            store=self.producer_store,
            configuration_fingerprint=resolved_configuration,
            policy=self.policy,
        )
        self.natural_setup = natural_setup or ContinuousNaturalSetupCoordinator(
            root=state.root / "state" / "continuous-natural-setup",
            minute_store_root=state.root / "market-data" / "minute",
            producer_store=self.producer_store,
            runtime_started_at=state.launch_at,
        )

    def compose(self, request: CompositionRequest) -> CompositionResult:
        if self.state.universe is None:
            raise LiveQualificationError("Composition has no hot-universe state.")
        cutoff_text = str(request.decision_cutoff or request.requested_at)
        cutoff = _parse_timestamp(cutoff_text)
        member_input = self.state.readiness_inputs.get(request.symbol)
        history_context = self.state.historical_contexts.get(request.symbol)
        current_market = self.state.current_market_evidence.get(request.symbol)
        instrument = self.state.instrument_admissions.get(request.symbol)
        if (
            member_input is None
            or history_context is None
            or current_market is None
            or instrument is None
        ):
            raise LiveQualificationError(
                "Composition omitted producer readiness or admission evidence."
            )
        universe_member = next(
            item
            for item in self.state.universe.state.members
            if item.member_id == member_input.universe_member_id
        )
        material_source = self.state.material_event_fingerprints.get(
            request.symbol, request.readiness_fingerprint
        )
        actual_known_at = tuple(
            dict.fromkeys(
                (
                    ("universeMember", universe_member.first_observed_at),
                    ("historicalContext", history_context.evidence_cutoff),
                    *(
                        (("canonicalMinute", member_input.canonical_evidence.receipt_timestamp),)
                        if member_input.canonical_evidence is not None
                        else ()
                    ),
                    ("currentMarket", current_market.receipt_timestamp),
                    ("instrumentAdmission", instrument.observed_at),
                    ("rvolAssessment", cutoff_text),
                    (
                        "materialEvent",
                        self.state.material_event_known_at.get(
                            request.symbol, request.requested_at
                        ),
                    ),
                )
            )
        )
        request_known_at = canonical_known_at(request.evidence_known_at)
        actual_known_at_identity = canonical_known_at(actual_known_at)
        if request_known_at != actual_known_at_identity:
            raise LiveCompositionEvidenceError(
                "COMPOSITION_KNOWN_AT_IDENTITY_MISMATCH",
                "Composition evidence chronology changed after readiness.",
                request_cutoff=canonical_instant(cutoff),
                evidence_known_at=actual_known_at,
            )
        for label, known_at in actual_known_at:
            if _parse_timestamp(known_at) > cutoff:
                raise LiveCompositionEvidenceError(
                    "COMPOSITION_EVIDENCE_AFTER_DECISION_CUTOFF",
                    f"{label} became known after the decision cutoff.",
                    request_cutoff=cutoff_text,
                    evidence_known_at=actual_known_at,
                )

        evaluations = []
        lifecycle_transitions = 0
        latest_setup_id: str | None = None
        latest_plan_id: str | None = None
        with self.natural_setup.preview() as preview:
            staged_producer = ContinuousTradePlanProducer(
                store=preview.producer_store,
                configuration_fingerprint=self.producer.configuration_fingerprint,
                policy=self.policy,
            )
            for _ in range(128):
                step = preview.coordinator.next_step(
                    member=universe_member,
                    base_input=member_input,
                    cutoff=cutoff,
                    readiness_fingerprint=request.readiness_fingerprint,
                    request_material_fingerprint=material_source,
                )
                evaluation = staged_producer.evaluate(
                    universe_state=self.state.universe.state,
                    member_input=step.member_input,
                    history_context=history_context,
                    current_market_evidence=current_market,
                    instrument_admission=instrument,
                    evidence_cutoff=cutoff,
                    trigger=request.trigger,
                    material_evidence_fingerprints=step.material_fingerprints,
                )
                if evaluation.cycle is None or evaluation.member_result is None:
                    raise LiveQualificationError(
                        "Producer did not return a reconstructable composition cycle."
                    )
                lifecycle_transitions += preview.coordinator.commit(
                    step=step,
                    evaluation=evaluation,
                )
                evaluations.append((step, evaluation))
                member = evaluation.member_result
                if member.intraday_plan is not None:
                    latest_plan_id = member.intraday_plan.plan_id
                if member.lifecycle_proposal is not None:
                    latest_setup_id = member.lifecycle_proposal.setup_id
                if not step.event_id:
                    break
            else:
                raise LiveQualificationError(
                    "Natural setup event processing exceeded its bounded cycle limit."
                )
            _, final_evaluation = evaluations[-1]
            cycle = final_evaluation.cycle
            evidence_payload = {
                "schemaVersion": 1,
                "profile": "continuous-natural-composition-chain-v1",
                "payloadType": "CONTINUOUS_NATURAL_COMPOSITION_CHAIN",
                "request": asdict(request),
                "naturalSteps": [
                    {
                        "eventId": step.event_id,
                        "eventType": step.event_type,
                        "eventFingerprint": step.event_fingerprint,
                        "materialFingerprints": list(step.material_fingerprints),
                        "producerRecord": json.loads(evaluation.record.payload_json),
                        "producerRecordId": evaluation.record.record_id,
                        "producerRecordFingerprint": evaluation.record.fingerprint,
                        "duplicate": evaluation.duplicate,
                    }
                    for step, evaluation in evaluations
                ],
                "finalCycleId": cycle.cycle_id,
                "finalCycleFingerprint": cycle.fingerprint,
                "decisionCutoff": canonical_instant(cutoff),
                "originalDecisionCutoff": cutoff_text,
                "evidenceKnownAt": [
                    {"evidence": name, "knownAt": value}
                    for name, value in actual_known_at
                ],
                "canonicalEvidenceKnownAt": [
                    {"evidence": name, "knownAt": value}
                    for name, value in actual_known_at_identity
                ],
                "knownAt": canonical_instant(cutoff),
                "authority": AUTHORITY,
                "executionAuthority": EXECUTION_AUTHORITY,
                "orderCapability": ORDER_CAPABILITY,
                "accountValuesRequested": False,
                "positionsRequested": False,
                "ordersRequested": False,
            }
            result = CompositionResult(
                request_id=request.request_id,
                symbol=request.symbol,
                cycle_id=cycle.cycle_id,
                fingerprint=cycle.fingerprint,
                lifecycle_transitions=lifecycle_transitions,
                setup_id=latest_setup_id,
                plan_id=latest_plan_id,
                evidence_payload_json=_canonical_bytes(evidence_payload).decode(
                    "ascii"
                ),
            )
            preview.commit()

        for _, evaluation in evaluations:
            committed_cycle = evaluation.cycle
            if committed_cycle is None or evaluation.member_result is None:
                raise LiveQualificationError(
                    "Committed composition omitted its reconstructable cycle."
                )
            self.state.cycles[committed_cycle.cycle_id] = committed_cycle
            self.state.metrics.composition_cycles.add(committed_cycle.cycle_id)
            member = evaluation.member_result
            if member.intraday_plan is not None:
                self.state.metrics.research_plans.add(member.intraday_plan.plan_id)
            if (
                member.lifecycle_proposal is not None
                and member.lifecycle_proposal.create_new_setup
            ):
                self.state.metrics.successor_setups.add(
                    member.lifecycle_proposal.setup_id
                )
        return result


class LiveDenominatorSource:
    def __init__(
        self,
        state: QualificationState,
        *,
        prospective_store: ProspectiveDenominatorStore | None = None,
    ) -> None:
        self.state = state
        self.prospective_store = prospective_store

    def produce(self, request: DenominatorRequest) -> DenominatorResult:
        if self.state.snapshot is None or self.state.universe is None:
            raise LiveQualificationError(
                "Denominator has no discovery/universe generation."
            )
        cycle = self.state.cycles[request.composition_cycle_id]
        result = produce_continuous_denominator(
            discovery_snapshot=self.state.snapshot,
            universe_result=self.state.universe,
            composition_cycle=cycle,
            observation_mode=(
                PROSPECTIVE
                if self.prospective_store is not None
                else LIVE_READ_ONLY_QUALIFICATION
            ),
            policy=(
                self.prospective_store.producer_policy
                if self.prospective_store is not None
                else None
            ),
            denominator_policy=(
                self.prospective_store.policy
                if self.prospective_store is not None
                else None
            ),
        )
        if self.prospective_store is not None:
            for context in self.state.historical_contexts.values():
                self.prospective_store.persist_historical_context(
                    source_context_id=context.context_id,
                    symbol=context.symbol,
                    observed_at=context.evidence_cutoff,
                    evidence_fingerprint=context.fingerprint,
                )
            self.prospective_store.persist_result(
                result,
                completed_at=request.requested_at,
            )
        self.state.denominator_results[result.cycle.cycle_id] = result
        if not result.linkage.complete_denominator:
            self.state.metrics.system_failed_cycles += 1
        return DenominatorResult(
            cycle_id=result.cycle.cycle_id,
            fingerprint=result.cycle.fingerprint,
            complete=result.linkage.complete_denominator,
            opportunity_count=len(result.opportunities),
            incomplete_reasons=result.linkage.incomplete_reasons,
        )


class NoEvents:
    def poll(self, _now: datetime) -> tuple[()]:
        return ()


class LiveMaterialEvents:
    """Dispatch history recovery and newly completed canonical-bar evidence."""

    def __init__(
        self,
        state: QualificationState,
        backfill: AutomaticCandleBackfillCoordinator,
        natural_setup: ContinuousNaturalSetupCoordinator | None = None,
    ) -> None:
        self.state = state
        self.backfill = backfill
        producer_store = ContinuousTradePlanProducerStore(
            state.root / "state" / "continuous-tradeplan-producer.json"
        )
        self.natural_setup = natural_setup or ContinuousNaturalSetupCoordinator(
            root=state.root / "state" / "continuous-natural-setup",
            minute_store_root=state.root / "market-data" / "minute",
            producer_store=producer_store,
            runtime_started_at=state.launch_at,
        )
        self._last_status: dict[str, str] = {}
        self._emitted: set[str] = set()

    def poll(self, now: datetime) -> tuple[RuntimeTriggerEvent, ...]:
        observed = now if now.tzinfo is not None and now.utcoffset() is not None else _aware_now()
        events: list[RuntimeTriggerEvent] = []
        if self.state.universe is not None:
            for member in self.state.universe.state.members:
                if member.current_state == TRACKED and member.current_tier == HOT:
                    self.backfill.request(
                        member.symbol,
                        reason="CONTINUOUS_COMPLETED_CANONICAL_BAR_REFRESH",
                    )
        for symbol, context in sorted(self.state.historical_contexts.items()):
            evidence = self.backfill.status(symbol)
            if evidence is None:
                continue
            status = str(evidence.get("status", "")).upper()
            previous = self._last_status.get(symbol, "")
            self._last_status[symbol] = status
            if context.status != HISTORY_BACKFILL_PENDING or status not in TERMINAL_STATES:
                continue
            source = _fingerprint(
                "continuous-history-terminal-event-v1",
                {
                    "symbol": symbol,
                    "status": status,
                    "completedAt": evidence.get("completedAt"),
                    "attemptCount": evidence.get("attemptCount"),
                    "contextId": context.context_id,
                },
            )
            if source in self._emitted:
                continue
            if previous and previous not in ACTIVE_STATES and previous == status:
                continue
            self._emitted.add(source)
            events.append(
                RuntimeTriggerEvent(
                    event_id=f"continuous-history-event-{source[:24]}",
                    trigger=(DATA_RECOVERED if status in {"COMPLETE", "PARTIAL"} else READINESS_CHANGED),
                    occurred_at=observed.isoformat(),
                    symbol=symbol,
                    source_fingerprint=source,
                    priority=80,
                )
            )
        universe_state = self.state.universe.state if self.state.universe else None
        for material in self.natural_setup.completed_bar_events(
            universe_state=universe_state,
            cutoff=observed,
        ):
            if material.event_id in self._emitted:
                continue
            self._emitted.add(material.event_id)
            events.append(
                RuntimeTriggerEvent(
                    event_id=material.event_id,
                    trigger=CANONICAL_BAR_COMPLETED,
                    occurred_at=material.receipt_timestamp,
                    symbol=material.symbol,
                    source_fingerprint=material.source_fingerprint,
                    priority=90,
                    provider_timestamp=material.provider_timestamp,
                )
            )
        return tuple(events)


def run_live_qualification(
    *,
    generation_root: Path,
    canonical_root: Path,
    expected_account_ending: str,
    duration_seconds: int,
    discovery_cadence_seconds: int,
    prospective_activation: ProspectiveActivationRecord | None = None,
    prospective_root: Path | None = None,
    preserved_provider_replay: object | None = None,
) -> dict[str, object]:
    if not 180 <= duration_seconds <= 1800:
        raise LiveQualificationError(
            "Qualification duration must be between 180 and 1800 seconds."
        )
    if not 60 <= discovery_cadence_seconds <= 600:
        raise LiveQualificationError(
            "Discovery cadence must be between 60 and 600 seconds."
        )
    if preserved_provider_replay is None and (
        len(expected_account_ending) != 4 or not expected_account_ending.isdigit()
    ):
        raise LiveQualificationError(
            "Expected account ending must contain four digits."
        )
    if preserved_provider_replay is not None and expected_account_ending:
        raise LiveQualificationError(
            "Offline preserved-provider replay must not receive an account identity."
        )
    if (prospective_activation is None) != (prospective_root is None):
        raise LiveQualificationError(
            "Prospective activation and persistence root must be supplied together."
        )
    root = validate_qualification_root(
        generation_root,
        canonical_root=canonical_root,
    )
    if root.exists():
        raise LiveQualificationError(
            "Qualification generation root must be new and write-once."
        )
    root.mkdir(parents=True)
    now_provider = (
        preserved_provider_replay.clock.now
        if preserved_provider_replay is not None
        else _aware_now
    )
    monotonic_provider = (
        preserved_provider_replay.clock.monotonic
        if preserved_provider_replay is not None
        else time.monotonic
    )
    sleep_provider = (
        preserved_provider_replay.clock.sleep
        if preserved_provider_replay is not None
        else time.sleep
    )
    launch_at = now_provider()
    state = QualificationState(
        root=root,
        launch_at=launch_at,
        now_provider=now_provider,
    )
    git_before = _git_identity(canonical_root)
    discovery = LiveDiscoverySource(
        state,
        provider=(
            preserved_provider_replay.discovery_provider
            if preserved_provider_replay is not None
            else None
        ),
    )
    market = LiveMarketDataSource(
        state,
        expected_account_ending=expected_account_ending,
        provider_boundary=(
            preserved_provider_replay.market_boundary
            if preserved_provider_replay is not None
            else None
        ),
    )
    composition = LiveCompositionSource(state)
    prospective_store = (
        ProspectiveDenominatorStore(
            prospective_root,
            activation=prospective_activation,
        )
        if prospective_activation is not None and prospective_root is not None
        else None
    )
    denominator = LiveDenominatorSource(
        state,
        prospective_store=prospective_store,
    )
    events = LiveMaterialEvents(
        state,
        market.backfill,
        natural_setup=composition.natural_setup,
    )
    runtime_id = (
        f"aug17-live-qualification-{launch_at.strftime('%Y%m%d%H%M%S')}"
    )
    config = ContinuousRuntimeConfig(
        runtime_identity="aug17-integration-live-read-only-qualification",
        session_date=launch_at.astimezone(EASTERN_TZ).date().isoformat(),
        cadence=RuntimeCadence(
            broad_discovery_seconds=discovery_cadence_seconds,
            housekeeping_seconds=15,
            discovery_stale_seconds=discovery_cadence_seconds * 2,
            composition_stale_seconds=discovery_cadence_seconds * 2,
        ),
        queues=QueueCapacities(
            discovery=2,
            readiness=16,
            composition=16,
            evidence=128,
            health=16,
        ),
        lease_ttl_seconds=30,
        shutdown_timeout_seconds=10,
        maximum_tracked_symbols=60,
    )
    worktree_root = Path(__file__).resolve().parents[1]
    topology = build_continuous_writer_topology_v2(
        root_path=root / "writer",
        evidence_program_id="aug17-integration-qualification-001",
        configuration_fingerprint=config.fingerprint,
        runtime_build_hash=_fingerprint(
            "qualification-runtime-build",
            _git_identity(worktree_root)["head"],
        ),
    )
    leases = LogicalRuntimeLeaseRegistry()
    resources = _acquire_qualification_resources(
        root=root,
        topology=topology,
        runtime_id=runtime_id,
        config=config,
        discovery=discovery,
        market=market,
        events=events,
        composition=composition,
        denominator=denominator,
        leases=leases,
        launch_at=launch_at,
    )
    runtime = resources.runtime
    client = resources.client
    checkpoints = resources.checkpoints
    restart_done = False
    started_monotonic = monotonic_provider()
    deadline = started_monotonic + duration_seconds
    restart_after = started_monotonic + (duration_seconds / 2)
    try:
        while monotonic_provider() < deadline:
            now = now_provider()
            runtime.tick(now, work_budget=512)
            if not restart_done and monotonic_provider() >= restart_after:
                before_universe = discovery.store.load().fingerprint
                before_records = read_evidence_snapshot(
                    topology,
                    reader_role=OFFLINE_REVIEW,
                ).record_count
                resources.shutdown_current(now)
                runtime = ContinuousOpportunityRuntime.restore(
                    config=config,
                    runtime_instance_id=runtime_id,
                    now=now_provider(),
                    discovery_source=discovery,
                    market_data_source=market,
                    event_source=events,
                    composition_source=composition,
                    denominator_source=denominator,
                    writer=client,
                    lease_registry=leases,
                    checkpoint_store=checkpoints,
                )
                resources.replace_runtime(runtime)
                restart_done = True
                receipt = {
                    "restartedAt": now_provider().isoformat(),
                    "universeFingerprintBefore": before_universe,
                    "universeFingerprintAfter": discovery.store.load().fingerprint,
                    "evidenceRecordsBefore": before_records,
                    "checkpointRestore": "PASS",
                }
                receipt["fingerprint"] = _fingerprint(
                    "qualification-restart-v1",
                    receipt,
                )
                _write_once(
                    root / "restart-receipt.json",
                    _canonical_bytes(receipt),
                )
            sleep_provider(
                min(5.0, max(0.0, deadline - monotonic_provider()))
            )
        final_now = now_provider()
        health = resources.shutdown_current(final_now)
        checkpoint = checkpoints.load(config.runtime_identity)
        runtime_bar_events = tuple(
            item
            for item in checkpoint.get("event_records", [])
            if isinstance(item, Mapping)
            and item.get("trigger") == CANONICAL_BAR_COMPLETED
        )
        backfill_accounting = _backfill_accounting(
            root / "state" / "continuous-history-backfill.json"
        )
        evidence = read_evidence_snapshot(
            topology,
            reader_role=OFFLINE_REVIEW,
        )
        git_after = _git_identity(canonical_root)
        metrics = state.metrics
        prospective_summary = (
            prospective_store.summary() if prospective_store is not None else None
        )
        acceptance = [
                metrics.discovery_cycles >= 2,
                metrics.finviz_pages >= 2,
                metrics.finviz_rows > 0,
                metrics.schwab_refreshes >= 1,
                len(metrics.canonical_ready_symbols) >= 1,
                len(metrics.composition_cycles) >= 1,
                len(state.denominator_results) >= 1,
                evidence.record_count >= 2,
                restart_done,
                git_before == git_after,
        ]
        if prospective_summary is not None:
            acceptance.extend(
                (
                    prospective_summary.prospective_observations_seen >= 1,
                    prospective_summary.unique_prospective_members >= 1,
                )
            )
        status = "PASS" if all(acceptance) else "FAIL"
        summary: dict[str, object] = {
            "schemaVersion": 1,
            "mode": MODE,
            "status": status,
            "liveQualificationStart": launch_at.isoformat(),
            "completedAt": final_now.isoformat(),
            "durationSeconds": round(
                monotonic_provider() - started_monotonic,
                3,
            ),
            "runtimeIdentity": runtime_id,
            "gitIdentityBefore": git_before,
            "gitIdentityAfter": git_after,
            "broadDiscoveryCycles": metrics.discovery_cycles,
            "finvizPagesObserved": metrics.finviz_pages,
            "finvizRowsObserved": metrics.finviz_rows,
            "uniqueSymbolsObserved": sorted(metrics.unique_symbols),
            "newlyAdmittedMiddaySymbols": sorted(metrics.midday_new_symbols),
            "candidateTierTransitions": metrics.tier_transitions,
            "schwabRefreshes": metrics.schwab_refreshes,
            "schwabQuoteSymbols": metrics.schwab_quote_symbols,
            "schwabMinuteRows": metrics.schwab_minute_rows,
            "schwabDailyRows": metrics.schwab_daily_rows,
            "canonicalSchwabReadySymbols": sorted(
                metrics.canonical_ready_symbols
            ),
            "completedBarEvents": len(runtime_bar_events),
            "completedBarEventRecords": runtime_bar_events,
            "backfillAccounting": backfill_accounting,
            "compositionCycles": len(metrics.composition_cycles),
            "denominatorCycles": len(state.denominator_results),
            "prospectiveDenominator": (
                asdict(prospective_summary)
                if prospective_summary is not None
                else None
            ),
            "prospectiveActivationFingerprint": (
                prospective_activation.fingerprint
                if prospective_activation is not None
                else None
            ),
            "researchOnlyTradePlans": len(metrics.research_plans),
            "successorSetups": len(metrics.successor_setups),
            "systemFailedCycles": metrics.system_failed_cycles,
            "providerRecoveryEvents": metrics.provider_recovery_events,
            "providerFailures": metrics.provider_failures,
            "restartRecovery": "PASS" if restart_done else "NOT_RUN",
            "evidenceRecordsWritten": evidence.record_count,
            "writerErrors": metrics.writer_errors,
            "runtimeHealth": asdict(health),
            "authority": AUTHORITY,
            "executionAuthority": EXECUTION_AUTHORITY,
            "positionsRequested": False,
            "ordersRequested": False,
            "ordersTransmitted": 0,
            "orderCapability": ORDER_CAPABILITY,
            "productionMutation": False,
        }
        if preserved_provider_replay is not None:
            summary["providerMode"] = preserved_provider_replay.mode
            summary["preservedProviderReplay"] = preserved_provider_replay.receipt()
        summary["fingerprint"] = _fingerprint(
            "aug17-live-qualification-summary-v1",
            summary,
        )
        payload = _canonical_bytes(summary)
        _write_once(root / "qualification-summary.json", payload)
        _write_once(
            root / "qualification-summary.sha256",
            (hashlib.sha256(payload).hexdigest().upper() + "\n").encode("ascii"),
        )
        return summary
    finally:
        try:
            resources.close()
        finally:
            _write_once(
                root / "resource-cleanup.json",
                _canonical_bytes(_resource_cleanup_receipt(resources.audit)),
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the isolated continuous live read-only qualification sidecar."
        )
    )
    parser.add_argument("--execute-read-only", action="store_true")
    parser.add_argument("--generation-root", type=Path, required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--expected-account-ending", required=True)
    parser.add_argument("--duration-seconds", type=int, default=360)
    parser.add_argument("--discovery-cadence-seconds", type=int, default=120)
    parser.add_argument("--activation-record", type=Path)
    parser.add_argument("--prospective-root", type=Path)
    args = parser.parse_args(argv)
    if not args.execute_read_only:
        raise SystemExit(
            "Refusing live qualification without --execute-read-only."
        )
    activation = (
        load_activation_record(args.activation_record)
        if args.activation_record is not None
        else None
    )
    result = run_live_qualification(
        generation_root=args.generation_root,
        canonical_root=args.canonical_root,
        expected_account_ending=args.expected_account_ending,
        duration_seconds=args.duration_seconds,
        discovery_cadence_seconds=args.discovery_cadence_seconds,
        prospective_activation=activation,
        prospective_root=args.prospective_root,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
