from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.broad_discovery import (
    DiscoveryQueryIdentity,
    DiscoverySourceRow,
    build_discovery_snapshot,
)
from momentum_hunter.continuous_composition import (
    CompositionMemberInput,
    ContinuousCompositionPolicy,
)
from momentum_hunter.continuous_live_qualification import (
    LiveCompositionSource,
    QualificationState,
)
from momentum_hunter.continuous_runtime import (
    ATTEMPT_FAILED,
    ATTEMPT_SUCCEEDED,
    CANONICAL_BAR_COMPLETED,
    COMPOSITION_QUEUE,
    CompositionRequest,
    ContinuousOpportunityRuntime,
    ContinuousRuntimeConfig,
    DenominatorResult,
    LogicalRuntimeLeaseRegistry,
    QueueCapacities,
    RuntimeCadence,
    RuntimeCheckpointStore,
    WRITER_ACCEPTED,
    build_work,
)
from momentum_hunter.continuous_time_identity import (
    canonical_instant,
    canonical_known_at,
)
from momentum_hunter.continuous_tradeplan_producer import (
    build_current_market_evidence,
    inspect_historical_context,
    unavailable_instrument_admission,
)
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE
from momentum_hunter.hot_universe import HotUniversePolicy, HotUniverseStore
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabDailyCandle,
    SchwabMinuteCandle,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.schwab_daily_candle_store import SchwabDailyCandleStore
from momentum_hunter.time_normalized_rvol import TimeNormalizedRvolEvidence


PROFILE = "producer-001c-physical-atomicity-proof-v1"
SESSION_DATE = "2026-08-17"
CONFIGURATION_FINGERPRINT = "a" * 64


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 8, 17, hour, minute, second, tzinfo=EASTERN_TZ)


def _fingerprint(label: str, value: object) -> str:
    payload = json.dumps(
        {"label": label, "value": value},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _sha256_bytes(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def _path_state(paths: dict[str, Path]) -> dict[str, dict[str, object]]:
    result = {}
    for name, path in sorted(paths.items()):
        payload = path.read_bytes() if path.exists() else None
        result[name] = {
            "exists": payload is not None,
            "sha256": _sha256_bytes(payload),
            "size": len(payload) if payload is not None else 0,
        }
    return result


def _checkpoint_authoritative_projection(
    payload: dict[str, object],
) -> dict[str, object]:
    counters = dict(payload.get("counters", {}))
    return {
        "setupIdentities": list(payload.get("setup_identities", ())),
        "planIdentities": list(payload.get("plan_identities", ())),
        "terminalCycleIds": list(payload.get("terminal_cycle_ids", ())),
        "compositionCycles": int(counters.get("composition_cycles", 0)),
        "lifecycleTransitions": int(counters.get("lifecycle_transitions", 0)),
        "setupsCreated": int(counters.get("setups_created", 0)),
        "plansCreated": int(counters.get("plans_created", 0)),
        "noPlanRecordsCommitted": int(
            counters.get("no_plan_records_committed", 0)
        ),
        "tradePlansCommitted": int(counters.get("trade_plans_committed", 0)),
    }


class _UnusedDiscovery:
    def discover(self, request):  # pragma: no cover - defensive tripwire.
        raise AssertionError("Atomicity proof unexpectedly requested discovery.")


class _UnusedMarketData:
    def evaluate(self, request):  # pragma: no cover - defensive tripwire.
        raise AssertionError("Atomicity proof unexpectedly requested market data.")


class _NoEvents:
    def poll(self, now):
        return ()


class _CompleteDenominator:
    def produce(self, request):
        return DenominatorResult(
            cycle_id=f"denominator-{request.composition_cycle_id}",
            fingerprint=_fingerprint("denominator", asdict(request)),
            complete=True,
            opportunity_count=1,
            incomplete_reasons=(),
        )


class _MemoryWriter:
    def __init__(self) -> None:
        self.intents = []

    def write_intent(self, intent):
        self.intents.append(intent)
        return WRITER_ACCEPTED


def _build_state(root: Path) -> tuple[QualificationState, object]:
    observed = _at(11, 0)
    row = DiscoverySourceRow.from_mapping(
        source_row_ordinal=1,
        source_row_identity=f"finviz:AAA:{observed.isoformat()}",
        source_values={"Ticker": "AAA", "No.": "1"},
        candidate=Candidate(
            ticker="AAA",
            company="AAA Incorporated",
            price=100.0,
            percent_change=5.0,
            volume=5_000_000,
            relative_volume=2.0,
            market_cap=10_000_000_000,
            sector="Technology",
            industry="Software",
        ),
    )
    snapshot = build_discovery_snapshot(
        source="finviz",
        source_version=PROFILE,
        requested_at=observed - timedelta(seconds=2),
        received_at=observed - timedelta(seconds=1),
        evaluated_at=observed,
        query_identity=DiscoveryQueryIdentity.from_criteria(
            INSTITUTIONAL_MOMENTUM,
            source_query="synthetic://producer-001c-atomicity",
            sort_order="-volume",
        ),
        source_contract_fingerprint="b" * 64,
        semantic_plausibility_fingerprint="c" * 64,
        source_rows=(row,),
    )
    state = QualificationState(
        root=root,
        launch_at=observed,
        configuration_fingerprint=CONFIGURATION_FINGERPRINT,
    )
    state.snapshot = snapshot
    state.universe = HotUniverseStore(
        root / "state" / "hot-universe.json", allow_persistent=True
    ).apply_snapshot(
        policy=HotUniversePolicy(maximum_hot_symbols=1),
        snapshot=snapshot,
        recorded_at=observed,
    )
    discovery_path = root / "source-evidence" / "finviz" / f"{snapshot.snapshot_id}.json"
    discovery_path.parent.mkdir(parents=True, exist_ok=True)
    discovery_path.write_text(snapshot.canonical_json(), encoding="ascii")
    return state, state.universe.state.members[0]


def _seed_history(root: Path) -> None:
    minute_root = root / "market-data" / "minute"
    daily_root = root / "market-data" / "daily"
    prior = tuple(
        datetime(2026, 8, day, 11, 0, tzinfo=EASTERN_TZ)
        for day in (11, 12, 13, 14)
    )
    minute_store = SchwabCandleStore(minute_root)
    minute_store.append_history(
        tuple(
            SchwabMinuteCandle(
                symbol="AAA",
                timestamp=value,
                open=95.0,
                high=95.2,
                low=94.8,
                close=95.0,
                volume=100.0,
                source=SCHWAB_PRICE_HISTORY_SOURCE,
            )
            for value in prior
        ),
        received_at=_at(11, 0),
    )
    SchwabDailyCandleStore(daily_root).append_history(
        tuple(
            SchwabDailyCandle(
                symbol="AAA",
                timestamp=value.replace(hour=16),
                session_date=value.date().isoformat(),
                open=94.0,
                high=96.0,
                low=93.0,
                close=95.0,
                volume=1_000_000,
                source=SCHWAB_PRICE_HISTORY_SOURCE,
            )
            for value in prior
        ),
        received_at=_at(11, 0),
    )
    bars = [
        SchwabMinuteCandle(
            symbol="AAA",
            timestamp=_at(11, minute),
            open=99.9,
            high=100.0,
            low=99.8,
            close=99.9,
            volume=100.0,
            source=SCHWAB_PRICE_HISTORY_SOURCE,
        )
        for minute in range(20)
    ]
    bars.append(
        SchwabMinuteCandle(
            symbol="AAA",
            timestamp=_at(11, 20),
            open=100.15,
            high=100.3,
            low=100.11,
            close=100.2,
            volume=200.0,
            source=SCHWAB_PRICE_HISTORY_SOURCE,
        )
    )
    minute_store.append_history(tuple(bars), received_at=_at(11, 21))


def _prepare(
    state: QualificationState,
    member,
    *,
    root: Path,
    cutoff: datetime,
) -> CompositionRequest:
    context, canonical = inspect_historical_context(
        minute_store_root=root / "market-data" / "minute",
        daily_store_root=root / "market-data" / "daily",
        symbol="AAA",
        session_date=SESSION_DATE,
        cutoff=cutoff,
        policy=ContinuousCompositionPolicy(required_recent_minute_bars=1),
    )
    state.historical_contexts["AAA"] = context
    state.current_market_evidence["AAA"] = build_current_market_evidence(
        symbol="AAA",
        provider_timestamp=(cutoff - timedelta(seconds=5)).isoformat(),
        receipt_timestamp=cutoff.isoformat(),
        source_identity="synthetic-read-only-current-market",
        market_payload={"symbol": "AAA", "generation": 1},
    )
    state.instrument_admissions["AAA"] = unavailable_instrument_admission(
        "AAA", observed_at=cutoff
    )
    state.readiness_inputs["AAA"] = CompositionMemberInput(
        universe_member_id=member.member_id,
        canonical_evidence=canonical,
        rvol_evidence=TimeNormalizedRvolEvidence(
            status=EXECUTION_ELIGIBLE,
            symbol="AAA",
            session_date=SESSION_DATE,
            through_minute=(cutoff - timedelta(minutes=1)).isoformat(),
            baseline_session_count=5,
            minimum_baseline_sessions=5,
            target_baseline_sessions=20,
            observed_volume=2_200,
            expected_volume=1_800.0,
            relative_volume=1.22,
        ),
    )
    material = _fingerprint("material", 1)
    state.material_event_fingerprints["AAA"] = material
    state.material_event_known_at["AAA"] = cutoff.isoformat()
    chronology = (
        ("universeMember", member.first_observed_at),
        ("historicalContext", context.evidence_cutoff),
        ("canonicalMinute", canonical.receipt_timestamp),
        ("currentMarket", state.current_market_evidence["AAA"].receipt_timestamp),
        ("instrumentAdmission", state.instrument_admissions["AAA"].observed_at),
        ("rvolAssessment", cutoff.isoformat()),
        ("materialEvent", cutoff.isoformat()),
    )
    return CompositionRequest(
        request_id="producer-001c-atomicity-request-1",
        symbol="AAA",
        trigger=CANONICAL_BAR_COMPLETED,
        requested_at=canonical_instant(cutoff),
        readiness_fingerprint=_fingerprint("readiness", 1),
        decision_cutoff=canonical_instant(cutoff),
        evidence_known_at=canonical_known_at(chronology),
        opportunity_id=member.member_id,
        original_decision_cutoff=cutoff.isoformat(),
        original_evidence_known_at=chronology,
    )


def _composition_work(request: CompositionRequest):
    return build_work(
        kind="COMPOSITION",
        key=request.symbol,
        requested_at=request.requested_at,
        priority=50,
        payload={
            "request_id": request.request_id,
            "symbol": request.symbol,
            "trigger": request.trigger,
            "readiness_fingerprint": request.readiness_fingerprint,
            "decision_cutoff": request.decision_cutoff,
            "evidence_known_at": [list(item) for item in request.evidence_known_at],
            "opportunity_id": request.opportunity_id,
            "original_decision_cutoff": request.original_decision_cutoff,
            "original_evidence_known_at": [
                list(item) for item in request.original_evidence_known_at
            ],
        },
    )


def _config() -> ContinuousRuntimeConfig:
    return ContinuousRuntimeConfig(
        runtime_identity="producer-001c-physical-atomicity-runtime",
        session_date=SESSION_DATE,
        cadence=RuntimeCadence(
            broad_discovery_seconds=300,
            housekeeping_seconds=30,
            discovery_stale_seconds=600,
            composition_stale_seconds=180,
        ),
        queues=QueueCapacities(),
        lease_ttl_seconds=30,
        shutdown_timeout_seconds=2,
        processed_event_capacity=256,
        diagnostic_capacity=64,
        maximum_tracked_symbols=8,
    )


def _runtime(
    *,
    instance: str,
    source: LiveCompositionSource,
    store: RuntimeCheckpointStore,
    leases: LogicalRuntimeLeaseRegistry,
    writer: _MemoryWriter,
    restore_at: datetime | None = None,
) -> ContinuousOpportunityRuntime:
    values = {
        "config": _config(),
        "runtime_instance_id": instance,
        "discovery_source": _UnusedDiscovery(),
        "market_data_source": _UnusedMarketData(),
        "event_source": _NoEvents(),
        "composition_source": source,
        "denominator_source": _CompleteDenominator(),
        "writer": writer,
        "lease_registry": leases,
        "checkpoint_store": store,
    }
    if restore_at is None:
        return ContinuousOpportunityRuntime(**values)
    return ContinuousOpportunityRuntime.restore(now=restore_at, **values)


def run_physical_atomicity_proof(runtime_root: Path) -> dict[str, object]:
    runtime_root = runtime_root.resolve(strict=False)
    temp_parent = Path(tempfile.gettempdir()).resolve()
    if runtime_root == temp_parent or temp_parent not in runtime_root.parents:
        raise ValueError("Physical proof runtime root must be a disposable TEMP child.")
    if runtime_root.exists():
        raise FileExistsError(f"Physical proof runtime root already exists: {runtime_root}")
    runtime_root.mkdir(parents=True)
    state, member = _build_state(runtime_root)
    _seed_history(runtime_root)
    cutoff = _at(11, 21)
    request = _prepare(state, member, root=runtime_root, cutoff=cutoff)
    work = _composition_work(request)
    source = LiveCompositionSource(state)
    paths = source.natural_setup._authoritative_paths()
    before = _path_state(paths)
    store = RuntimeCheckpointStore(runtime_root / "runtime-checkpoint")
    leases = LogicalRuntimeLeaseRegistry()
    writer = _MemoryWriter()
    runtime = _runtime(
        instance="producer-001c-atomicity-process-1",
        source=source,
        store=store,
        leases=leases,
        writer=writer,
    )
    runtime.start(cutoff)
    runtime._checkpoint(cutoff)
    checkpoint_before_failure = _checkpoint_authoritative_projection(
        store.load(_config().runtime_identity)
    )
    original = source.producer.evaluate.__func__
    calls = 0

    def fail_after_staging(producer, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("producer-001c physical staged failure")
        return original(producer, **kwargs)

    with patch(
        "momentum_hunter.continuous_live_qualification."
        "ContinuousTradePlanProducer.evaluate",
        new=fail_after_staging,
    ):
        runtime._process_composition(work, cutoff)
    after_failure = _path_state(paths)
    runtime._checkpoint(cutoff)
    checkpoint_after_failure = _checkpoint_authoritative_projection(
        store.load(_config().runtime_identity)
    )
    failure_events = tuple(asdict(item) for item in runtime.attempt_history)
    failed = [item for item in failure_events if item["event_type"] == ATTEMPT_FAILED]
    runtime.shutdown(cutoff + timedelta(seconds=1))
    restarted_source = LiveCompositionSource(state)
    restarted = _runtime(
        instance="producer-001c-atomicity-process-2",
        source=restarted_source,
        store=store,
        leases=leases,
        writer=writer,
        restore_at=cutoff + timedelta(seconds=2),
    )
    after_restart = _path_state(paths)
    restarted._process_composition(work, cutoff + timedelta(seconds=3))
    restarted._checkpoint(cutoff + timedelta(seconds=3))
    after_success = _path_state(paths)
    producer_count = len(restarted_source.producer_store.load())
    lifecycle_count = len(restarted_source.natural_setup.lifecycle.store.load().events)
    breakout_count = len(restarted_source.natural_setup.breakouts.load().events)
    restarted._process_composition(work, cutoff + timedelta(seconds=4))
    restarted._checkpoint(cutoff + timedelta(seconds=4))
    after_duplicate = _path_state(paths)
    terminal_events = tuple(asdict(item) for item in restarted.attempt_history)
    succeeded = [
        item for item in terminal_events if item["event_type"] == ATTEMPT_SUCCEEDED
    ]
    result = {
        "schemaVersion": 1,
        "profile": PROFILE,
        "classification": "ATOMIC_COMPOSITION_PHYSICAL_PROOF_PASSED",
        "runtimeRoot": str(runtime_root),
        "request": asdict(request),
        "authoritativeState": {
            "before": before,
            "afterFailure": after_failure,
            "afterRestart": after_restart,
            "afterSuccess": after_success,
            "afterDuplicate": after_duplicate,
        },
        "checkpointAuthoritativeProjection": {
            "beforeFailure": checkpoint_before_failure,
            "afterFailure": checkpoint_after_failure,
        },
        "attemptEvents": terminal_events,
        "counts": {
            "producerRecords": producer_count,
            "lifecycleEvents": lifecycle_count,
            "breakoutEvents": breakout_count,
            "attemptEvents": len(terminal_events),
            "failedAttemptEvents": len(failed),
            "succeededAttemptEvents": len(succeeded),
            "writerIntents": len(writer.intents),
        },
        "proof": {
            "stagingWasReached": bool(failed and failed[-1]["staging_began"]),
            "failureAppended": len(failed) == 1,
            "failureChangedAuthoritativeState": bool(
                failed and failed[-1]["authoritative_state_changed"]
            ),
            "failureWasByteIdentical": before == after_failure,
            "failureCheckpointProjectionWasIdentical": (
                checkpoint_before_failure == checkpoint_after_failure
            ),
            "restartRecoveredNoPhantomState": before == after_restart,
            "validCompositionCommitted": after_success != before,
            "validCompositionCommittedOnce": (
                producer_count > 0 and after_duplicate == after_success
            ),
            "duplicateReplayWasIdempotent": after_duplicate == after_success,
            "failureChronologySurvivedRestart": any(
                item["event_id"] == failed[-1]["event_id"]
                for item in terminal_events
            ) if failed else False,
            "paperAuthorityUsed": False,
            "shadowAuthorityUsed": False,
            "brokerAuthorityUsed": False,
            "orderAuthorityUsed": False,
        },
    }
    required = (
        result["proof"]["stagingWasReached"],
        result["proof"]["failureAppended"],
        not result["proof"]["failureChangedAuthoritativeState"],
        result["proof"]["failureWasByteIdentical"],
        result["proof"]["failureCheckpointProjectionWasIdentical"],
        result["proof"]["restartRecoveredNoPhantomState"],
        result["proof"]["validCompositionCommitted"],
        result["proof"]["validCompositionCommittedOnce"],
        result["proof"]["duplicateReplayWasIdempotent"],
        result["proof"]["failureChronologySurvivedRestart"],
    )
    if not all(required):
        result["classification"] = "ATOMIC_COMPOSITION_PHYSICAL_PROOF_FAILED"
    result["fingerprint"] = _fingerprint(PROFILE, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Producer-001C disposable physical atomicity proof."
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite physical proof: {args.output}")
    result = run_physical_atomicity_proof(args.runtime_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="",
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["classification"].endswith("PASSED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
