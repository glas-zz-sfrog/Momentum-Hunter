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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from momentum_hunter.broad_discovery import DiscoveryPaginationPolicy, DiscoverySnapshot
from momentum_hunter.canonical_candle_evidence import load_canonical_minute_bars
from momentum_hunter.continuous_composition import (
    READY,
    CanonicalEvidenceInput,
    CompositionMemberInput,
    ContinuousCompositionCycle,
    ContinuousCompositionPolicy,
    assess_readiness,
    build_readiness_request,
    compose_cycle,
)
from momentum_hunter.continuous_denominator import (
    ContinuousDenominatorResult,
    produce_continuous_denominator,
)
from momentum_hunter.continuous_paper_contract import (
    build_continuous_paper_admission_intent,
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
)
from momentum_hunter.hot_universe import (
    HOT,
    TRACKED,
    HotUniversePolicy,
    HotUniverseResult,
    HotUniverseStore,
)
from momentum_hunter.models import INSTITUTIONAL_MOMENTUM
from momentum_hunter.opportunity_denominator import LIVE_READ_ONLY_QUALIFICATION
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
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


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
    allow_persistent: bool = False
    runtime_configuration_fingerprint: str = ""
    product_sha: str = ""
    metrics: QualificationMetrics = field(default_factory=QualificationMetrics)
    snapshot: DiscoverySnapshot | None = None
    universe: HotUniverseResult | None = None
    readiness_inputs: dict[str, CompositionMemberInput] = field(default_factory=dict)
    cycles: dict[str, ContinuousCompositionCycle] = field(default_factory=dict)
    denominator_results: dict[str, ContinuousDenominatorResult] = field(
        default_factory=dict
    )
    refreshed_snapshot_id: str = ""


class LiveDiscoverySource:
    def __init__(self, state: QualificationState) -> None:
        self.state = state
        self.provider = FinvizProvider(backoff_seconds=())
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
                evaluated_at=_aware_now(),
            )
            universe = self.store.apply_snapshot(
                policy=self.policy,
                snapshot=snapshot,
                recorded_at=_aware_now(),
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


class LiveMarketDataSource:
    def __init__(
        self,
        state: QualificationState,
        *,
        expected_account_ending: str,
    ) -> None:
        self.state = state
        self.expected_account_ending = expected_account_ending
        self.minute_root = state.root / "market-data" / "minute"
        self.daily_root = state.root / "market-data" / "daily"
        self.token_provider = SchwabReadOnlyAccessTokenProvider()
        self.access_guard = SchwabMarketDataOnlyAccessGuard(
            token_provider=self.token_provider,
        )
        self.quote_source = SchwabMarketDataQuoteSource(
            token_provider=self.token_provider,
        )
        self.composition_policy = ContinuousCompositionPolicy()

    def _sync_auth_metrics(self) -> None:
        self.state.metrics.auth_health = self.token_provider.metrics_snapshot()

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

    def _refresh(self) -> None:
        if self.state.snapshot is None or self.state.universe is None:
            raise LiveQualificationError(
                "Schwab refresh has no discovery generation."
            )
        snapshot_id = self.state.snapshot.snapshot_id
        if self.state.refreshed_snapshot_id == snapshot_id:
            return
        symbols = tuple(
            item.symbol
            for item in self.state.universe.state.members
            if item.current_state == TRACKED and item.current_tier == HOT
        )[:MAX_READY_SYMBOLS]
        if not symbols:
            raise LiveQualificationError(
                "Discovery produced no hot symbols for Schwab qualification."
            )
        quote_batch = None
        try:
            quote_batch = self.quote_source.quotes_with_clock(symbols)
            self.state.metrics.schwab_quote_symbols += len(quote_batch.quotes)
            self.state.metrics.schwab_market_data_successes += 1
            self.state.metrics.last_successful_schwab_read = _aware_now().isoformat()
        except Exception as exc:
            self.state.metrics.provider_failures.append(
                f"SCHWAB_QUOTES:{self._failure_code(exc)}"
            )
        try:
            result = SchwabHistoricalCandleBackfiller(
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
        self.state.metrics.last_successful_schwab_read = _aware_now().isoformat()
        sanitized = {
            "snapshotId": snapshot_id,
            "symbols": list(symbols),
            "quoteStatus": "PASS" if quote_batch is not None else "FAILED_LOCALIZED",
            "quoteSymbolCount": len(quote_batch.quotes) if quote_batch else 0,
            "candleStatus": result.get("status"),
            "minuteRows": minute_rows,
            "dailyRows": daily_rows,
            "resultFingerprint": result.get("resultFingerprint"),
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": ORDER_CAPABILITY,
        }
        _write_once(
            self.state.root
            / "source-evidence"
            / "schwab"
            / f"{snapshot_id}.json",
            _canonical_bytes(sanitized),
        )
        self.state.refreshed_snapshot_id = snapshot_id

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
        evaluated = _aware_now()
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
            )
        self._refresh()
        all_bars = load_canonical_minute_bars(
            store_root=self.minute_root,
            symbols=(request.symbol,),
        ).get(request.symbol, [])
        completed_cutoff = evaluated - timedelta(
            seconds=self.composition_policy.minimum_completed_bar_lag_seconds
        )
        regular_bars = tuple(
            item
            for item in all_bars
            if _parse_timestamp(item.timestamp) <= completed_cutoff
            and item.session_date == member.session_date
            and REGULAR_OPEN
            <= _parse_timestamp(item.timestamp).astimezone(EASTERN_TZ).time()
            < REGULAR_CLOSE
        )
        daily = SchwabDailyCandleStore(self.daily_root).canonical_bars(
            request.symbol
        )
        evidence = CanonicalEvidenceInput(
            evidence_id=(
                f"qualification-minute:{request.symbol}:{member.session_date}:"
                f"{self.state.snapshot.snapshot_id}"
            ),
            symbol=request.symbol,
            session_date=member.session_date,
            provider_timestamp=(
                regular_bars[-1].timestamp
                if regular_bars
                else evaluated.isoformat()
            ),
            receipt_timestamp=evaluated.isoformat(),
            bars=regular_bars,
            daily_evidence_id=(
                f"qualification-daily:{request.symbol}:"
                f"{daily[0]['sessionDate'] if daily else 'missing'}:"
                f"{daily[-1]['sessionDate'] if daily else 'missing'}"
            ),
            daily_evidence_fingerprint=_fingerprint(
                "qualification-daily-evidence-v1", daily
            ),
            history_depth_sessions=len({item.session_date for item in all_bars}),
        )
        rvol = load_time_normalized_rvol_evidence(
            (request.symbol,),
            as_of=evaluated,
            store_root=self.minute_root,
        )[request.symbol]
        exact_request = build_readiness_request(
            member,
            requested_at=evaluated,
            policy=self.composition_policy,
            source_reason=request.trigger,
        )
        assessment = assess_readiness(
            exact_request,
            evidence=evidence,
            rvol_evidence=rvol,
            evaluated_at=evaluated,
            policy=self.composition_policy,
        )
        self.state.metrics.candle_readiness_successes += 1
        self.state.metrics.last_successful_schwab_read = _aware_now().isoformat()
        self._sync_auth_metrics()
        self.state.readiness_inputs[request.symbol] = CompositionMemberInput(
            universe_member_id=member.member_id,
            canonical_evidence=evidence,
            rvol_evidence=rvol,
        )
        ready = assessment.status == READY
        if ready:
            self.state.metrics.canonical_ready_symbols.add(request.symbol)
        return ReadinessResult(
            request_id=request.request_id,
            symbol=request.symbol,
            status=assessment.status,
            fingerprint=assessment.fingerprint,
            ready=ready,
            failure_reason=(
                None if ready else ";".join(assessment.blocker_reasons)
            ),
        )


class LiveCompositionSource:
    def __init__(self, state: QualificationState) -> None:
        self.state = state
        self.policy = ContinuousCompositionPolicy()

    def compose(self, request: CompositionRequest) -> CompositionResult:
        if self.state.universe is None:
            raise LiveQualificationError("Composition has no hot-universe state.")
        cutoff = _aware_now()
        cycle = compose_cycle(
            universe_state=self.state.universe.state,
            member_inputs=tuple(self.state.readiness_inputs.values()),
            started_at=cutoff - timedelta(microseconds=1),
            evidence_cutoff=cutoff,
            policy=self.policy,
        )
        self.state.cycles[cycle.cycle_id] = cycle
        self.state.metrics.composition_cycles.add(cycle.cycle_id)
        member = next(
            item for item in cycle.member_results if item.symbol == request.symbol
        )
        universe_member = next(
            item
            for item in self.state.universe.state.members
            if item.member_id == member.universe_member_id
        )
        admission = build_continuous_paper_admission_intent(
            cycle=cycle,
            member=member,
            universe_member=universe_member,
            runtime_configuration_fingerprint=(
                self.state.runtime_configuration_fingerprint
            ),
            product_sha=self.state.product_sha,
        )
        if member.intraday_plan is not None:
            self.state.metrics.research_plans.add(member.intraday_plan.plan_id)
        if (
            member.lifecycle_proposal is not None
            and member.lifecycle_proposal.create_new_setup
        ):
            self.state.metrics.successor_setups.add(
                member.lifecycle_proposal.setup_id
            )
        return CompositionResult(
            request_id=request.request_id,
            symbol=request.symbol,
            cycle_id=cycle.cycle_id,
            fingerprint=cycle.fingerprint,
            lifecycle_transitions=int(member.lifecycle_proposal is not None),
            setup_id=(
                member.lifecycle_proposal.setup_id
                if member.lifecycle_proposal
                else None
            ),
            plan_id=(member.intraday_plan.plan_id if member.intraday_plan else None),
            admission_payload_json=(
                json.dumps(
                    admission.to_dict(),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                if admission is not None
                else None
            ),
        )


class LiveDenominatorSource:
    def __init__(self, state: QualificationState) -> None:
        self.state = state

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
            observation_mode=LIVE_READ_ONLY_QUALIFICATION,
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


def run_live_qualification(
    *,
    generation_root: Path,
    canonical_root: Path,
    expected_account_ending: str,
    duration_seconds: int,
    discovery_cadence_seconds: int,
) -> dict[str, object]:
    if not 180 <= duration_seconds <= 1800:
        raise LiveQualificationError(
            "Qualification duration must be between 180 and 1800 seconds."
        )
    if not 60 <= discovery_cadence_seconds <= 600:
        raise LiveQualificationError(
            "Discovery cadence must be between 60 and 600 seconds."
        )
    if len(expected_account_ending) != 4 or not expected_account_ending.isdigit():
        raise LiveQualificationError(
            "Expected account ending must contain four digits."
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
    launch_at = _aware_now()
    state = QualificationState(root=root, launch_at=launch_at)
    git_before = _git_identity(canonical_root)
    discovery = LiveDiscoverySource(state)
    market = LiveMarketDataSource(
        state,
        expected_account_ending=expected_account_ending,
    )
    composition = LiveCompositionSource(state)
    denominator = LiveDenominatorSource(state)
    events = NoEvents()
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
    capability = create_ephemeral_writer_capability()
    writer = DedicatedEvidenceWriter(topology)
    writer.activate_session(
        capability=capability,
        source_identity=runtime_id,
    )
    client = AuthenticatedEvidenceWriterClient(
        topology=topology,
        capability=capability,
        runtime_instance_id=runtime_id,
        writer=writer,
        maximum_ack_seconds=2.0,
    )
    leases = LogicalRuntimeLeaseRegistry()
    checkpoints = RuntimeCheckpointStore(root / "checkpoint")
    runtime = ContinuousOpportunityRuntime(
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
    runtime.start(launch_at)
    restart_done = False
    started_monotonic = time.monotonic()
    deadline = started_monotonic + duration_seconds
    restart_after = started_monotonic + (duration_seconds / 2)
    try:
        while time.monotonic() < deadline:
            now = _aware_now()
            runtime.tick(now, work_budget=512)
            if not restart_done and time.monotonic() >= restart_after:
                before_universe = discovery.store.load().fingerprint
                before_records = read_evidence_snapshot(
                    topology,
                    reader_role=OFFLINE_REVIEW,
                ).record_count
                runtime.shutdown(now)
                runtime = ContinuousOpportunityRuntime.restore(
                    config=config,
                    runtime_instance_id=runtime_id,
                    now=_aware_now(),
                    discovery_source=discovery,
                    market_data_source=market,
                    event_source=events,
                    composition_source=composition,
                    denominator_source=denominator,
                    writer=client,
                    lease_registry=leases,
                    checkpoint_store=checkpoints,
                )
                restart_done = True
                receipt = {
                    "restartedAt": _aware_now().isoformat(),
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
            time.sleep(
                min(5.0, max(0.0, deadline - time.monotonic()))
            )
        final_now = _aware_now()
        health = runtime.shutdown(final_now)
        evidence = read_evidence_snapshot(
            topology,
            reader_role=OFFLINE_REVIEW,
        )
        git_after = _git_identity(canonical_root)
        metrics = state.metrics
        status = "PASS" if all(
            (
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
            )
        ) else "FAIL"
        summary: dict[str, object] = {
            "schemaVersion": 1,
            "mode": MODE,
            "status": status,
            "liveQualificationStart": launch_at.isoformat(),
            "completedAt": final_now.isoformat(),
            "durationSeconds": round(
                time.monotonic() - started_monotonic,
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
            "compositionCycles": len(metrics.composition_cycles),
            "denominatorCycles": len(state.denominator_results),
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
        writer.close()
        capability.close()


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
    args = parser.parse_args(argv)
    if not args.execute_read_only:
        raise SystemExit(
            "Refusing live qualification without --execute-read-only."
        )
    result = run_live_qualification(
        generation_root=args.generation_root,
        canonical_root=args.canonical_root,
        expected_account_ending=args.expected_account_ending,
        duration_seconds=args.duration_seconds,
        discovery_cadence_seconds=args.discovery_cadence_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
