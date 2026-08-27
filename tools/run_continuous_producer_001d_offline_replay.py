from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.continuous_composition import (
    READY,
    ContinuousCompositionPolicy,
    assess_readiness,
    build_readiness_request,
)
from momentum_hunter.continuous_live_qualification import LiveCompositionSource
from momentum_hunter.continuous_tradeplan_producer import inspect_historical_context
from momentum_hunter.schwab_candle_contract import (
    SCHWAB_PRICE_HISTORY_SOURCE,
    SchwabMinuteCandle,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from tools.run_continuous_producer_001c_atomicity_proof import (
    SESSION_DATE,
    _at,
    _build_state,
    _prepare,
    _seed_history,
    run_physical_atomicity_proof,
)


PROFILE = "producer-001d-offline-exact-path-replay-v1"


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def run_offline_replay(runtime_root: Path) -> dict[str, object]:
    runtime_root = runtime_root.resolve(strict=False)
    if runtime_root.exists():
        raise FileExistsError(f"Offline replay root already exists: {runtime_root}")
    runtime_root.mkdir(parents=True)
    state, member = _build_state(runtime_root)
    _seed_history(runtime_root)
    cutoff = _at(11, 21)
    policy = ContinuousCompositionPolicy(required_recent_minute_bars=1)

    context_before, _ = inspect_historical_context(
        minute_store_root=runtime_root / "market-data" / "minute",
        daily_store_root=runtime_root / "market-data" / "daily",
        symbol="AAA",
        session_date=SESSION_DATE,
        cutoff=cutoff,
        policy=policy,
    )
    SchwabCandleStore(runtime_root / "market-data" / "minute").append_history(
        (
            SchwabMinuteCandle(
                symbol="AAA",
                timestamp=cutoff,
                open=100.2,
                high=100.4,
                low=100.1,
                close=100.3,
                volume=50.0,
                source=SCHWAB_PRICE_HISTORY_SOURCE,
            ),
        ),
        received_at=cutoff,
    )
    request = _prepare(state, member, root=runtime_root, cutoff=cutoff)
    context_after = state.historical_contexts["AAA"]
    member_input = state.readiness_inputs["AAA"]
    readiness_request = build_readiness_request(
        member,
        requested_at=cutoff,
        policy=policy,
        source_reason="CANONICAL_BAR_COMPLETED",
    )
    readiness = assess_readiness(
        readiness_request,
        evidence=member_input.canonical_evidence,
        rvol_evidence=member_input.rvol_evidence,
        evaluated_at=cutoff,
        policy=policy,
    )

    source = LiveCompositionSource(state)
    first = source.compose(request)
    producer_path = runtime_root / "state" / "continuous-tradeplan-producer.json"
    producer_after_first = producer_path.read_bytes()
    restarted_source = LiveCompositionSource(state)
    replayed = restarted_source.compose(request)
    producer_after_replay = producer_path.read_bytes()
    records = restarted_source.producer_store.load()
    final_record = records[-1]

    atomicity_root = runtime_root.parent / f"{runtime_root.name}-atomicity"
    atomicity = run_physical_atomicity_proof(atomicity_root)
    proof = {
        "observedProvisionalVersionCount": (
            context_after.observed_provisional_version_count
        ),
        "admittedProvisionalBarCount": context_after.admitted_provisional_bar_count,
        "discardedProvisionalDidNotChangeContextIdentity": (
            context_before.context_id == context_after.context_id
            and context_before.fingerprint == context_after.fingerprint
            and context_before.content_fingerprint
            == context_after.content_fingerprint
        ),
        "readinessStatus": readiness.status,
        "naturalCompositionCycleId": first.cycle_id,
        "naturalCompositionPlanId": first.plan_id,
        "naturalCompositionOutcome": "TRADEPLAN" if first.plan_id else "NO_PLAN",
        "restartCycleIdentityStable": first.cycle_id == replayed.cycle_id,
        "restartFingerprintStable": first.fingerprint == replayed.fingerprint,
        "restartPersistenceByteStable": producer_after_first == producer_after_replay,
        "producerRecordCount": len(records),
        "producerRecordId": final_record.record_id,
        "producerRecordFingerprint": final_record.fingerprint,
        "atomicCompositionClassification": atomicity["classification"],
        "accountValuesRequested": False,
        "positionsRequested": False,
        "paperAuthorityUsed": False,
        "shadowAuthorityUsed": False,
        "ordersRequested": False,
        "orderCapability": "UNAVAILABLE",
    }
    accepted = (
        proof["observedProvisionalVersionCount"] > 0
        and proof["admittedProvisionalBarCount"] == 0
        and proof["discardedProvisionalDidNotChangeContextIdentity"]
        and proof["readinessStatus"] == READY
        and proof["restartCycleIdentityStable"]
        and proof["restartFingerprintStable"]
        and proof["restartPersistenceByteStable"]
        and proof["producerRecordCount"] > 0
        and proof["atomicCompositionClassification"]
        == "ATOMIC_COMPOSITION_PHYSICAL_PROOF_PASSED"
    )
    result = {
        "schemaVersion": 1,
        "profile": PROFILE,
        "classification": (
            "OFFLINE_EXACT_PATH_REPLAY_PASSED"
            if accepted
            else "OFFLINE_EXACT_PATH_REPLAY_FAILED"
        ),
        "runtimeRoot": str(runtime_root),
        "readinessRequest": asdict(readiness_request),
        "readinessAssessment": asdict(readiness),
        "compositionRequest": asdict(request),
        "compositionResult": asdict(first),
        "replayedCompositionResult": asdict(replayed),
        "historicalContextBeforeProvisional": asdict(context_before),
        "historicalContextAfterProvisional": asdict(context_after),
        "proof": proof,
        "physicalAtomicityProof": atomicity,
    }
    result["fingerprint"] = _fingerprint(result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Producer-001D disposable offline exact-path replay."
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite offline replay: {args.output}")
    result = run_offline_replay(args.runtime_root)
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
