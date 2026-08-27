from __future__ import annotations

import ast
import json
import tempfile
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from momentum_hunter.continuous_attempt_ledger import (
    ATTEMPT_FAILED,
    ATTEMPT_STARTED,
    ATTEMPT_SUCCEEDED,
)
from momentum_hunter.continuous_runtime import (
    CANONICAL_BAR_COMPLETED,
    COALESCED_DUPLICATE,
    COMPOSITION_STALE,
    DEGRADED,
    DENOMINATOR_DEGRADED,
    DISCOVERY_STALE,
    ENQUEUED,
    EVIDENCE_QUEUE,
    FAILED,
    MEMBER_PROMOTED,
    PROCESS_ALIVE,
    READY,
    REJECTED_CAPACITY,
    REPLACED_OBSOLETE,
    RUNNING,
    STOPPED,
    WRITER_ACCEPTED,
    WRITER_DUPLICATE,
    WRITER_SLOW,
    WRITER_UNAVAILABLE,
    BoundedWorkQueue,
    CompositionRequest,
    CompositionResult,
    ContinuousOpportunityRuntime,
    ContinuousRuntimeConfig,
    ContinuousRuntimeError,
    DenominatorRequest,
    DenominatorResult,
    DiscoveryPulse,
    DiscoveryRequest,
    LogicalRuntimeLeaseRegistry,
    ManualClock,
    QueueCapacities,
    ReadinessRequest,
    ReadinessResult,
    RuntimeCadence,
    RuntimeCheckpointError,
    RuntimeCheckpointStore,
    RuntimeLeaseError,
    RuntimeSequenceError,
    RuntimeTriggerEvent,
    build_evidence_write_intent,
    build_work,
    measure_runtime_operation,
)
from momentum_hunter.continuous_time_identity import canonical_instant


ET = ZoneInfo("America/New_York")


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 8, 18, hour, minute, second, tzinfo=ET)


def fp(label: object) -> str:
    import hashlib

    return hashlib.sha256(str(label).encode("ascii")).hexdigest()


class SyntheticDiscovery:
    def __init__(self, symbols: tuple[str, ...] = tuple(f"S{i:02d}" for i in range(30))) -> None:
        self.symbols = symbols
        self.calls = 0
        self.failures: list[BaseException] = []

    def discover(self, request: DiscoveryRequest) -> DiscoveryPulse:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        active = self.symbols[:10]
        return DiscoveryPulse(
            pulse_id=f"pulse-{self.calls}",
            fingerprint=fp((request.request_id, self.calls)),
            source_rows_represented=len(self.symbols),
            symbols_for_readiness=active,
            new_symbols=self.symbols if self.calls == 1 else (),
            retained_symbols=() if self.calls == 1 else self.symbols,
            provider_bound_symbols=self.symbols[10:],
            evidence_payload_json=json.dumps(
                {
                    "schemaVersion": 1,
                    "profile": "synthetic-discovery-evidence-v1",
                    "sourcePopulation": list(self.symbols),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


class SyntheticMarketData:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_symbols: set[str] = set()
        self.exception_symbols: set[str] = set()
        self.mismatch_symbols: set[str] = set()

    def evaluate(self, request: ReadinessRequest) -> ReadinessResult:
        self.calls.append(request.symbol)
        if request.symbol in self.exception_symbols:
            raise RuntimeError("synthetic readiness exception")
        failed = request.symbol in self.fail_symbols
        chronology = (("syntheticReadiness", request.requested_at),)
        return ReadinessResult(
            request_id=("wrong-request" if request.symbol in self.mismatch_symbols else request.request_id),
            symbol=("WRONG" if request.symbol in self.mismatch_symbols else request.symbol),
            status="DATA_FAILURE" if failed else "READY",
            fingerprint=fp((request.request_id, failed)),
            ready=not failed,
            failure_reason="SYNTHETIC_DATA_FAILURE" if failed else None,
            decision_cutoff=request.requested_at,
            evidence_known_at=chronology,
        )


class SyntheticEvents:
    def __init__(self) -> None:
        self.events: list[RuntimeTriggerEvent] = []

    def poll(self, now: datetime):
        ready = [event for event in self.events if datetime.fromisoformat(event.occurred_at) <= now]
        self.events = [event for event in self.events if event not in ready]
        return tuple(ready)


class SyntheticComposer:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_symbols: set[str] = set()
        self.mismatch_symbols: set[str] = set()
        self.no_plan_symbols: set[str] = set()
        self.evidence_payload_json: str | None = None

    def compose(self, request: CompositionRequest) -> CompositionResult:
        self.calls.append(request.symbol)
        if request.symbol in self.fail_symbols:
            raise RuntimeError("synthetic composition exception")
        identity = fp((request.request_id, request.readiness_fingerprint))
        return CompositionResult(
            request_id=("wrong-request" if request.symbol in self.mismatch_symbols else request.request_id),
            symbol=("WRONG" if request.symbol in self.mismatch_symbols else request.symbol),
            cycle_id=f"cycle-{identity[:24]}",
            fingerprint=identity,
            lifecycle_transitions=1,
            setup_id=f"setup-{request.symbol}",
            plan_id=(
                None
                if request.symbol in self.no_plan_symbols
                else f"plan-{request.symbol}"
            ),
            evidence_payload_json=self.evidence_payload_json,
        )


class SyntheticDenominator:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.incomplete_symbols: set[str] = set()
        self.raise_symbols: set[str] = set()

    def produce(self, request: DenominatorRequest) -> DenominatorResult:
        self.calls.append(request.symbol)
        if request.symbol in self.raise_symbols:
            raise RuntimeError("synthetic denominator exception")
        complete = request.symbol not in self.incomplete_symbols
        return DenominatorResult(
            cycle_id=f"denominator-{request.composition_cycle_id}",
            fingerprint=fp((request.request_id, complete)),
            complete=complete,
            opportunity_count=(len(request.provider_bound_symbols) or 1),
            incomplete_reasons=() if complete else ("SYNTHETIC_INCOMPLETE",),
        )


class SyntheticWriter:
    def __init__(self) -> None:
        self.mode = WRITER_ACCEPTED
        self.receipts: dict[int, str] = {}
        self.intents = []

    def write_intent(self, intent):
        if self.mode in {WRITER_UNAVAILABLE, WRITER_SLOW}:
            return self.mode
        previous = self.receipts.get(intent.sequence)
        if previous is not None:
            if previous != intent.fingerprint:
                raise RuntimeError("writer sequence conflict")
            return WRITER_DUPLICATE
        self.receipts[intent.sequence] = intent.fingerprint
        self.intents.append(intent)
        return WRITER_ACCEPTED


class RuntimeFixture:
    def __init__(
        self,
        root: Path,
        *,
        identity: str = "synthetic-continuous-runtime",
        queues: QueueCapacities | None = None,
    ) -> None:
        self.clock = ManualClock(at(9, 25))
        self.discovery = SyntheticDiscovery()
        self.market = SyntheticMarketData()
        self.events = SyntheticEvents()
        self.composer = SyntheticComposer()
        self.denominator = SyntheticDenominator()
        self.writer = SyntheticWriter()
        self.leases = LogicalRuntimeLeaseRegistry()
        self.store = RuntimeCheckpointStore(root / "checkpoint")
        self.config = ContinuousRuntimeConfig(
            runtime_identity=identity,
            session_date="2026-08-18",
            cadence=RuntimeCadence(
                broad_discovery_seconds=300,
                housekeeping_seconds=30,
                discovery_stale_seconds=600,
                composition_stale_seconds=180,
            ),
            queues=queues or QueueCapacities(),
            lease_ttl_seconds=30,
            shutdown_timeout_seconds=2,
            processed_event_capacity=20000,
            diagnostic_capacity=256,
            maximum_tracked_symbols=128,
        )
        self.runtime = self.new_runtime("runtime-instance-1")

    def new_runtime(self, instance: str) -> ContinuousOpportunityRuntime:
        return ContinuousOpportunityRuntime(
            config=self.config,
            runtime_instance_id=instance,
            discovery_source=self.discovery,
            market_data_source=self.market,
            event_source=self.events,
            composition_source=self.composer,
            denominator_source=self.denominator,
            writer=self.writer,
            lease_registry=self.leases,
            checkpoint_store=self.store,
        )

    def event(self, symbol: str, *, suffix: str = "1", priority: int = 50):
        now = self.clock.now()
        source = fp((symbol, suffix, now.isoformat()))
        return RuntimeTriggerEvent(
            event_id=f"event-{symbol}-{suffix}",
            trigger=CANONICAL_BAR_COMPLETED,
            occurred_at=now.isoformat(),
            symbol=symbol,
            source_fingerprint=source,
            priority=priority,
            provider_timestamp=(now - timedelta(minutes=1)).isoformat(),
        )


class ContinuousRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.fixture = RuntimeFixture(self.root)

    def start(self):
        return self.fixture.runtime.start(self.fixture.clock.now())

    def test_process_contract_starts_ready_and_heartbeat_is_independent(self) -> None:
        health = self.start()
        self.assertEqual(READY, health.process_state)
        self.assertIn(PROCESS_ALIVE, health.health_flags)
        self.assertIn(DISCOVERY_STALE, health.health_flags)
        self.assertIn(COMPOSITION_STALE, health.health_flags)
        before = health.last_heartbeat_at
        self.fixture.discovery.failures.append(TimeoutError("synthetic timeout"))
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(DEGRADED, health.process_state)
        self.assertEqual(1, health.discovery_failures)
        self.fixture.clock.advance(30)
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertGreaterEqual(health.last_heartbeat_at, before)
        self.assertIn(PROCESS_ALIVE, health.health_flags)

    def test_two_speed_event_processing_does_not_require_discovery(self) -> None:
        self.start()
        self.fixture.runtime.tick(self.fixture.clock.now())
        discovery_calls = self.fixture.discovery.calls
        self.fixture.clock.advance(60)
        event = self.fixture.event("MIDDAY")
        self.fixture.runtime.submit_event(event, self.fixture.clock.now())
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(discovery_calls, self.fixture.discovery.calls)
        self.assertIn("MIDDAY", self.fixture.composer.calls)
        self.assertGreater(health.composition_cycles, 0)

    def test_composition_producer_payload_reaches_writer_unchanged(self) -> None:
        producer_payload = json.dumps(
            {
                "payloadType": "CONTINUOUS_TRADEPLAN_PRODUCER",
                "producerFingerprint": fp("producer"),
                "executionAuthority": "NONE",
                "orderCapability": "UNAVAILABLE",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        self.fixture.composer.evidence_payload_json = producer_payload
        self.start()
        self.fixture.runtime.submit_event(
            self.fixture.event("AAA"), self.fixture.clock.now()
        )
        self.fixture.runtime.tick(self.fixture.clock.now())
        composition_intents = tuple(
            item
            for item in self.fixture.writer.intents
            if item.evidence_type == "COMPOSITION_CYCLE"
        )
        self.assertTrue(composition_intents)
        self.assertTrue(
            all(item.payload_json == producer_payload for item in composition_intents)
        )

    def test_queue_coalescing_replacement_and_saturation_are_explicit(self) -> None:
        queue = BoundedWorkQueue("readiness", 2)
        now = self.fixture.clock.now()
        first = build_work(kind="READINESS", key="AAA", requested_at=now.isoformat(), priority=1, payload={"v": 1})
        duplicate = first
        newer = build_work(kind="READINESS", key="AAA", requested_at=(now + timedelta(seconds=1)).isoformat(), priority=1, payload={"v": 2})
        second = build_work(kind="READINESS", key="BBB", requested_at=now.isoformat(), priority=1, payload={"v": 1})
        rejected = build_work(kind="READINESS", key="CCC", requested_at=now.isoformat(), priority=1, payload={"v": 1})
        self.assertEqual(ENQUEUED, queue.enqueue(first, now)[0])
        self.assertEqual(COALESCED_DUPLICATE, queue.enqueue(duplicate, now)[0])
        self.assertEqual(REPLACED_OBSOLETE, queue.enqueue(newer, now)[0])
        self.assertEqual(ENQUEUED, queue.enqueue(second, now)[0])
        self.assertEqual(REJECTED_CAPACITY, queue.enqueue(rejected, now)[0])
        metrics = queue.metrics(now)
        self.assertEqual((2, 2, 1, 1, 1), (
            metrics.configured_capacity,
            metrics.high_water_mark,
            metrics.coalesced_count,
            metrics.replaced_count,
            metrics.rejected_count,
        ))
        self.assertEqual(0, metrics.dropped_count)

    def test_runtime_queue_saturation_preserves_observable_backpressure(self) -> None:
        fixture = RuntimeFixture(
            self.root / "small",
            queues=QueueCapacities(discovery=1, readiness=2, composition=2, evidence=4, health=2),
        )
        fixture.runtime.start(fixture.clock.now())
        decisions = [
            fixture.runtime.submit_event(fixture.event(symbol, suffix=symbol), fixture.clock.now())
            for symbol in ("AAA", "BBB", "CCC", "DDD")
        ]
        self.assertEqual(2, decisions.count(REJECTED_CAPACITY))
        self.assertEqual(2, len(fixture.runtime.backpressure_decisions))
        self.assertEqual(READY, fixture.runtime.process_state)
        self.assertEqual(0, fixture.runtime.queue_metrics(fixture.clock.now())["readiness"].dropped_count)
        health = fixture.runtime.tick(fixture.clock.now())
        self.assertGreaterEqual(health.provider_bound_denominator_cycles, 1)
        self.assertEqual(0, health.incomplete_denominator_cycles)

    def test_symbol_failure_isolation_does_not_starve_other_member(self) -> None:
        self.start()
        self.fixture.market.exception_symbols.add("POISON")
        self.fixture.runtime.submit_event(self.fixture.event("POISON"), self.fixture.clock.now())
        self.fixture.runtime.submit_event(self.fixture.event("HEALTHY"), self.fixture.clock.now())
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertIn("HEALTHY", self.fixture.composer.calls)
        self.assertNotIn("POISON", self.fixture.composer.calls)
        self.assertEqual("POISON", self.fixture.runtime.symbol_failures[-1].symbol)
        self.assertEqual(1, health.readiness_failures)

    def test_discovery_failure_preserves_runtime_and_hot_event_lane(self) -> None:
        self.start()
        self.fixture.discovery.failures.append(RuntimeError("schema failure"))
        self.fixture.runtime.submit_event(self.fixture.event("RETAINED"), self.fixture.clock.now())
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(1, health.discovery_failures)
        self.assertIn("RETAINED", self.fixture.composer.calls)
        self.assertEqual(DEGRADED, health.process_state)
        self.fixture.clock.advance(300)
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(RUNNING, health.process_state)

    def test_discovery_cycle_persists_bounded_source_population(self) -> None:
        self.start()

        self.fixture.runtime.tick(self.fixture.clock.now())

        discovery = next(
            intent
            for intent in self.fixture.writer.intents
            if intent.evidence_type == "DISCOVERY_CYCLE"
        )
        payload = json.loads(discovery.payload_json)
        self.assertEqual("DISCOVERY_CYCLE", payload["payloadType"])
        self.assertEqual(30, payload["pulse"]["source_rows_represented"])
        self.assertEqual(
            [f"S{i:02d}" for i in range(30)],
            payload["sourceEvidence"]["sourcePopulation"],
        )
        self.assertEqual("RESEARCH_ONLY", payload["authority"])
        self.assertEqual("EXECUTION_AUTHORITY_NONE", payload["executionAuthority"])

    def test_discovery_failure_persists_system_failure_evidence(self) -> None:
        self.start()
        self.fixture.discovery.failures.append(RuntimeError("schema failure"))

        self.fixture.runtime.tick(self.fixture.clock.now())

        failure = next(
            intent
            for intent in self.fixture.writer.intents
            if intent.evidence_type == "SYSTEM_FAILURE"
        )
        payload = json.loads(failure.payload_json)
        self.assertEqual("SYSTEM_FAILURE", payload["payloadType"])
        self.assertEqual("DISCOVERY", payload["stage"])
        self.assertEqual("RuntimeError", payload["reason"])
        self.assertEqual("RESEARCH_ONLY", payload["authority"])
        self.assertEqual("EXECUTION_AUTHORITY_NONE", payload["executionAuthority"])

    def test_resolved_discovery_cadence_changes_without_restarting_runtime(self) -> None:
        self.start()
        self.fixture.runtime.tick(
            self.fixture.clock.now(), discovery_cadence_seconds=600
        )
        self.assertEqual(1, self.fixture.discovery.calls)
        self.fixture.clock.advance(300)
        self.fixture.runtime.tick(
            self.fixture.clock.now(), discovery_cadence_seconds=600
        )
        self.assertEqual(1, self.fixture.discovery.calls)
        self.fixture.clock.advance(300)
        self.fixture.runtime.tick(
            self.fixture.clock.now(), discovery_cadence_seconds=300
        )
        self.assertEqual(2, self.fixture.discovery.calls)

    def test_adapter_identity_mismatch_is_symbol_scoped_and_fails_closed(self) -> None:
        self.start()
        self.fixture.market.mismatch_symbols.add("BADREADY")
        self.fixture.composer.mismatch_symbols.add("BADCOMPOSE")
        for symbol in ("BADREADY", "BADCOMPOSE", "GOOD"):
            self.fixture.runtime.submit_event(self.fixture.event(symbol), self.fixture.clock.now())
        self.fixture.runtime.tick(self.fixture.clock.now())
        failures = {item.symbol: item.reason for item in self.fixture.runtime.symbol_failures}
        self.assertEqual("ADAPTER_IDENTITY_MISMATCH", failures["BADREADY"])
        self.assertEqual("ADAPTER_IDENTITY_MISMATCH", failures["BADCOMPOSE"])
        self.assertIn("GOOD", self.fixture.denominator.calls)

    def test_composition_failure_preserves_exact_exception_and_chronology(self) -> None:
        self.start()
        self.fixture.composer.fail_symbols.add("FAIL")
        event = self.fixture.event("FAIL")
        self.fixture.runtime.submit_event(event, self.fixture.clock.now())
        self.fixture.runtime.tick(self.fixture.clock.now())

        failure = next(
            item
            for item in self.fixture.runtime.symbol_failures
            if item.symbol == "FAIL"
        )
        self.assertEqual("COMPOSITION", failure.stage)
        self.assertEqual("RuntimeError", failure.exception_class)
        self.assertEqual("RuntimeError", failure.diagnostic_code)
        self.assertEqual("synthetic composition exception", failure.message)
        self.assertEqual(canonical_instant(event.occurred_at), failure.request_cutoff)
        self.assertEqual(
            (("syntheticReadiness", canonical_instant(event.occurred_at)),),
            failure.evidence_known_at,
        )
        failed_attempt = next(
            item
            for item in self.fixture.runtime.attempt_history
            if item.event_id == failure.attempt_event_id
        )
        self.assertEqual(ATTEMPT_FAILED, failed_attempt.event_type)
        self.assertEqual("COMPOSITION", failed_attempt.stage)
        self.assertEqual("RuntimeError", failed_attempt.exception_class)
        self.assertFalse(failed_attempt.authoritative_state_changed)
        checkpoint = self.fixture.store.load(self.fixture.config.runtime_identity)
        persisted = next(
            item for item in checkpoint["symbol_failures"] if item["symbol"] == "FAIL"
        )
        self.assertEqual("RuntimeError", persisted["exception_class"])
        self.assertEqual(
            [["syntheticReadiness", canonical_instant(event.occurred_at)]],
            persisted["evidence_known_at"],
        )

    def test_attempt_chronology_survives_restart_and_later_success(self) -> None:
        self.start()
        self.fixture.composer.fail_symbols.add("AAA")
        self.fixture.runtime.submit_event(
            self.fixture.event("AAA", suffix="failed"), self.fixture.clock.now()
        )
        self.fixture.runtime.tick(self.fixture.clock.now())
        before = self.fixture.runtime.attempt_history
        before_health = self.fixture.runtime.health(self.fixture.clock.now())
        failed = tuple(
            item
            for item in before
            if item.stage == "COMPOSITION" and item.event_type == ATTEMPT_FAILED
        )
        self.assertEqual(1, len(failed))

        self.fixture.composer.fail_symbols.clear()
        self.fixture.clock.advance(31)
        restored = ContinuousOpportunityRuntime.restore(
            config=self.fixture.config,
            runtime_instance_id="runtime-instance-2",
            now=self.fixture.clock.now(),
            discovery_source=self.fixture.discovery,
            market_data_source=self.fixture.market,
            event_source=self.fixture.events,
            composition_source=self.fixture.composer,
            denominator_source=self.fixture.denominator,
            writer=self.fixture.writer,
            lease_registry=self.fixture.leases,
            checkpoint_store=self.fixture.store,
        )
        self.assertEqual(before, restored.attempt_history)
        restored.submit_event(
            self.fixture.event("AAA", suffix="success"), self.fixture.clock.now()
        )
        health = restored.tick(self.fixture.clock.now())
        history = restored.attempt_history
        composition_starts = tuple(
            item
            for item in history
            if item.stage == "COMPOSITION"
            and item.symbol == "AAA"
            and item.event_type == ATTEMPT_STARTED
        )
        composition_successes = tuple(
            item
            for item in history
            if item.stage == "COMPOSITION"
            and item.symbol == "AAA"
            and item.event_type == ATTEMPT_SUCCEEDED
        )
        self.assertEqual(2, len(composition_starts))
        self.assertEqual(1, len(composition_successes))
        self.assertEqual(1, health.composition_attempts_failed)
        self.assertEqual(before_health.composition_cycles + 1, health.composition_cycles)
        self.assertEqual(
            before_health.trade_plans_committed + 1,
            health.trade_plans_committed,
        )
        self.assertEqual(failed[0], next(item for item in history if item == failed[0]))

    def test_later_readiness_failure_does_not_erase_composition_failure(self) -> None:
        self.start()
        self.fixture.composer.fail_symbols.add("AAA")
        self.fixture.runtime.submit_event(
            self.fixture.event("AAA", suffix="composition"),
            self.fixture.clock.now(),
        )
        self.fixture.runtime.tick(self.fixture.clock.now())
        composition_failure = next(
            item
            for item in self.fixture.runtime.attempt_history
            if item.symbol == "AAA"
            and item.stage == "COMPOSITION"
            and item.event_type == ATTEMPT_FAILED
        )

        self.fixture.composer.fail_symbols.clear()
        self.fixture.market.fail_symbols.add("AAA")
        self.fixture.runtime.submit_event(
            self.fixture.event("AAA", suffix="readiness"),
            self.fixture.clock.now(),
        )
        self.fixture.runtime.tick(self.fixture.clock.now())

        failures = tuple(
            item
            for item in self.fixture.runtime.attempt_history
            if item.symbol == "AAA" and item.event_type == ATTEMPT_FAILED
        )
        self.assertIn(composition_failure, failures)
        self.assertEqual(
            {"READINESS", "COMPOSITION"},
            {item.stage for item in failures},
        )
        latest = next(
            item
            for item in self.fixture.runtime.symbol_failures
            if item.symbol == "AAA"
        )
        self.assertEqual("READINESS", latest.stage)
        self.assertEqual(failures[-1].event_id, latest.attempt_event_id)

    def test_truthful_ready_and_composition_stage_counters(self) -> None:
        self.start()
        self.fixture.runtime.tick(self.fixture.clock.now())
        baseline = self.fixture.runtime.health(self.fixture.clock.now())

        self.fixture.runtime.submit_event(
            self.fixture.event("ZZZ", suffix="first"), self.fixture.clock.now()
        )
        first = self.fixture.runtime.tick(self.fixture.clock.now())
        self.fixture.runtime.submit_event(
            self.fixture.event("ZZZ", suffix="second"), self.fixture.clock.now()
        )
        second = self.fixture.runtime.tick(self.fixture.clock.now())

        self.assertEqual(baseline.unique_ready_symbols + 1, first.unique_ready_symbols)
        self.assertEqual(first.unique_ready_symbols, second.unique_ready_symbols)
        self.assertEqual(
            first.repeated_ready_assessments + 1,
            second.repeated_ready_assessments,
        )
        self.assertEqual(
            baseline.readiness_assessments + 2,
            second.readiness_assessments,
        )
        self.assertEqual(
            baseline.composition_attempts_started + 2,
            second.composition_attempts_started,
        )

        self.fixture.composer.no_plan_symbols.add("NOPLAN")
        before_results = second
        for symbol in ("NOPLAN", "PLAN"):
            self.fixture.runtime.submit_event(
                self.fixture.event(symbol, suffix="result"), self.fixture.clock.now()
            )
        results = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(
            before_results.no_plan_records_committed + 1,
            results.no_plan_records_committed,
        )
        self.assertEqual(
            before_results.trade_plans_committed + 1,
            results.trade_plans_committed,
        )

    def test_nonready_result_preserves_cutoff_and_chronology(self) -> None:
        self.start()
        self.fixture.market.fail_symbols.add("NOTREADY")
        event = self.fixture.event("NOTREADY")
        self.fixture.runtime.submit_event(event, self.fixture.clock.now())
        self.fixture.runtime.tick(self.fixture.clock.now())

        failure = next(
            item
            for item in self.fixture.runtime.symbol_failures
            if item.symbol == "NOTREADY"
        )
        self.assertEqual("READINESS", failure.stage)
        self.assertEqual("DATA_FAILURE", failure.diagnostic_code)
        self.assertEqual("SYNTHETIC_DATA_FAILURE", failure.message)
        self.assertEqual(event.occurred_at, failure.request_cutoff)
        self.assertEqual(
            (("syntheticReadiness", event.occurred_at),),
            failure.evidence_known_at,
        )

    def test_completed_bar_event_accounting_is_persisted_in_checkpoint(self) -> None:
        self.start()
        event = self.fixture.event("AAA", suffix="accounting")
        self.fixture.runtime.submit_event(event, self.fixture.clock.now())
        health = self.fixture.runtime.tick(self.fixture.clock.now())

        self.assertEqual(1, health.completed_bar_events)
        checkpoint = self.fixture.store.load(self.fixture.config.runtime_identity)
        self.assertEqual(1, checkpoint["counters"]["completed_bar_events"])
        self.assertEqual(
            [event.event_id],
            [
                item["event_id"]
                for item in checkpoint["event_records"]
                if item["trigger"] == CANONICAL_BAR_COMPLETED
            ],
        )
        completed = next(
            item
            for item in checkpoint["event_records"]
            if item["trigger"] == CANONICAL_BAR_COMPLETED
        )
        self.assertEqual(event.provider_timestamp, completed["provider_timestamp"])

    def test_legacy_checkpoint_event_without_provider_time_restores_as_unknown(self) -> None:
        self.start()
        event = self.fixture.event("AAA", suffix="legacy-clock")
        self.fixture.runtime.submit_event(event, self.fixture.clock.now())
        self.fixture.runtime.tick(self.fixture.clock.now())
        checkpoint = self.fixture.store.load(self.fixture.config.runtime_identity)
        checkpoint.pop("checkpoint_fingerprint", None)
        checkpoint["checkpoint_schema_version"] = 2
        for item in checkpoint["event_records"]:
            item.pop("provider_timestamp", None)
        self.fixture.store.save(self.fixture.config.runtime_identity, checkpoint)

        self.fixture.clock.advance(31)
        restored = ContinuousOpportunityRuntime.restore(
            config=self.fixture.config,
            runtime_instance_id="runtime-instance-legacy-clock",
            now=self.fixture.clock.now(),
            discovery_source=self.fixture.discovery,
            market_data_source=self.fixture.market,
            event_source=self.fixture.events,
            composition_source=self.fixture.composer,
            denominator_source=self.fixture.denominator,
            writer=self.fixture.writer,
            lease_registry=self.fixture.leases,
            checkpoint_store=self.fixture.store,
        )

        restored_event = next(
            item for item in restored._event_records.values() if item.event_id == event.event_id
        )
        self.assertIsNone(restored_event.provider_timestamp)

    def test_new_completed_bar_event_without_provider_time_fails_closed(self) -> None:
        self.start()
        event = replace(
            self.fixture.event("AAA", suffix="missing-provider-clock"),
            provider_timestamp=None,
        )

        with self.assertRaisesRegex(
            ContinuousRuntimeError,
            "require an authoritative provider timestamp",
        ):
            self.fixture.runtime.submit_event(event, self.fixture.clock.now())

    def test_denominator_incomplete_is_visible_without_stopping_runtime(self) -> None:
        self.start()
        self.fixture.denominator.incomplete_symbols.add("AAA")
        self.fixture.runtime.submit_event(self.fixture.event("AAA"), self.fixture.clock.now())
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(11, health.denominator_cycles)
        self.assertEqual(1, health.incomplete_denominator_cycles)
        self.assertIn(DENOMINATOR_DEGRADED, health.health_flags)

    def test_writer_unavailable_and_slow_leave_intent_queued(self) -> None:
        self.start()
        self.fixture.writer.mode = WRITER_UNAVAILABLE
        self.fixture.runtime.submit_event(self.fixture.event("AAA"), self.fixture.clock.now())
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertGreater(self.fixture.runtime.queue_metrics(self.fixture.clock.now())[EVIDENCE_QUEUE].current_depth, 0)
        self.assertEqual(1, health.writer_unavailable_events)
        self.fixture.writer.mode = WRITER_SLOW
        self.fixture.clock.advance(5)
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(1, health.writer_slow_events)
        self.fixture.writer.mode = WRITER_ACCEPTED
        self.fixture.clock.advance(10)
        health = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(0, dict(health.queue_depths)[EVIDENCE_QUEUE])
        self.assertEqual(RUNNING, health.process_state)

    def test_evidence_sequence_duplicate_conflict_and_gap_fail_closed(self) -> None:
        self.start()
        now = self.fixture.clock.now().isoformat()
        first = build_evidence_write_intent(
            runtime_instance_id="runtime-instance-1",
            sequence=1,
            evidence_type="TEST",
            record_identity="record-1",
            record_fingerprint=fp("record-1"),
            predecessor_identity=None,
            requested_at=now,
            payload_fingerprint=fp("payload-1"),
        )
        self.assertEqual(ENQUEUED, self.fixture.runtime.admit_evidence_intent(first, self.fixture.clock.now()))
        self.assertEqual(WRITER_DUPLICATE, self.fixture.runtime.admit_evidence_intent(first, self.fixture.clock.now()))
        conflict = replace(first, record_identity="changed")
        with self.assertRaisesRegex(RuntimeSequenceError, "Conflicting duplicate"):
            self.fixture.runtime.admit_evidence_intent(conflict, self.fixture.clock.now())
        gap = build_evidence_write_intent(
            runtime_instance_id="runtime-instance-1",
            sequence=3,
            evidence_type="TEST",
            record_identity="record-3",
            record_fingerprint=fp("record-3"),
            predecessor_identity=first.intent_id,
            requested_at=now,
            payload_fingerprint=fp("payload-3"),
        )
        with self.assertRaisesRegex(RuntimeSequenceError, "sequence gap"):
            self.fixture.runtime.admit_evidence_intent(gap, self.fixture.clock.now())

    def test_evidence_history_capacity_fails_closed_without_growth(self) -> None:
        self.fixture.config = replace(self.fixture.config, evidence_history_capacity=1)
        self.fixture.runtime = self.fixture.new_runtime("bounded-history-instance")
        self.start()
        now = self.fixture.clock.now().isoformat()
        first = build_evidence_write_intent(
            runtime_instance_id="bounded-history-instance",
            sequence=1,
            evidence_type="TEST",
            record_identity="record-1",
            record_fingerprint=fp("record-1"),
            predecessor_identity=None,
            requested_at=now,
            payload_fingerprint=fp("payload-1"),
        )
        self.fixture.runtime.admit_evidence_intent(first, self.fixture.clock.now())
        second = build_evidence_write_intent(
            runtime_instance_id="bounded-history-instance",
            sequence=2,
            evidence_type="TEST",
            record_identity="record-2",
            record_fingerprint=fp("record-2"),
            predecessor_identity=first.intent_id,
            requested_at=now,
            payload_fingerprint=fp("payload-2"),
        )
        self.assertEqual(
            REJECTED_CAPACITY,
            self.fixture.runtime.admit_evidence_intent(second, self.fixture.clock.now()),
        )
        self.assertEqual(1, len(self.fixture.runtime.evidence_intents))
        self.assertEqual(DEGRADED, self.fixture.runtime.process_state)

    def test_competing_runtime_rejected_and_stale_lease_takeover_is_explicit(self) -> None:
        self.start()
        competitor = self.fixture.new_runtime("runtime-instance-2")
        with self.assertRaisesRegex(RuntimeLeaseError, "already owned"):
            competitor.start(self.fixture.clock.now())
        self.fixture.clock.advance(31)
        health = competitor.start(self.fixture.clock.now())
        self.assertEqual(READY, health.process_state)
        self.assertEqual(2, self.fixture.leases.current(self.fixture.config.runtime_identity).generation)

    def test_crash_restart_requeues_incomplete_work_and_preserves_lineage(self) -> None:
        self.start()
        event = self.fixture.event("AAA")
        self.fixture.runtime.submit_event(event, self.fixture.clock.now())
        self.fixture.runtime.crash_with_in_flight("readiness", self.fixture.clock.now())
        self.assertEqual(FAILED, self.fixture.runtime.process_state)
        self.fixture.clock.advance(31)
        restored = ContinuousOpportunityRuntime.restore(
            config=self.fixture.config,
            runtime_instance_id="runtime-instance-2",
            now=self.fixture.clock.now(),
            discovery_source=self.fixture.discovery,
            market_data_source=self.fixture.market,
            event_source=self.fixture.events,
            composition_source=self.fixture.composer,
            denominator_source=self.fixture.denominator,
            writer=self.fixture.writer,
            lease_registry=self.fixture.leases,
            checkpoint_store=self.fixture.store,
        )
        health = restored.tick(self.fixture.clock.now())
        self.assertIn("AAA", self.fixture.composer.calls)
        self.assertEqual(1, health.restart_count)
        self.assertEqual(len(self.fixture.composer.calls), health.denominator_cycles)
        self.assertEqual(1, self.fixture.composer.calls.count("AAA"))
        self.assertEqual(len(set(item.sequence for item in restored.evidence_intents)), len(restored.evidence_intents))

    def test_duplicate_replay_after_restart_does_not_create_late_cycle(self) -> None:
        self.start()
        event = self.fixture.event("AAA")
        self.fixture.runtime.submit_event(event, self.fixture.clock.now())
        first = self.fixture.runtime.tick(self.fixture.clock.now())
        cycles = first.composition_cycles
        self.assertEqual(COALESCED_DUPLICATE, self.fixture.runtime.submit_event(event, self.fixture.clock.now()))
        second = self.fixture.runtime.tick(self.fixture.clock.now())
        self.assertEqual(cycles, second.composition_cycles)

    def test_clean_shutdown_is_bounded_checkpoints_and_releases_lease(self) -> None:
        self.start()
        self.fixture.writer.mode = WRITER_UNAVAILABLE
        self.fixture.runtime.submit_event(self.fixture.event("AAA"), self.fixture.clock.now())
        self.fixture.runtime.tick(self.fixture.clock.now())
        started = time.perf_counter()
        health = self.fixture.runtime.shutdown(self.fixture.clock.now(), work_budget=10)
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertEqual(STOPPED, health.process_state)
        self.assertIsNone(self.fixture.leases.current(self.fixture.config.runtime_identity))
        payload = self.fixture.store.load(self.fixture.config.runtime_identity)
        self.assertEqual(STOPPED, payload["process_state"])

    def test_checkpoint_corruption_and_config_change_fail_closed(self) -> None:
        self.start()
        path = self.fixture.store.path_for(self.fixture.config.runtime_identity)
        path.write_text("{}", encoding="ascii")
        with self.assertRaisesRegex(RuntimeCheckpointError, "fingerprint"):
            self.fixture.store.load(self.fixture.config.runtime_identity)

        other = RuntimeFixture(self.root / "other", identity="other-runtime")
        other.runtime.start(other.clock.now())
        changed = replace(other.config, policy_version="changed-policy")
        other.clock.advance(31)
        with self.assertRaisesRegex(RuntimeCheckpointError, "configuration identity"):
            ContinuousOpportunityRuntime.restore(
                config=changed,
                runtime_instance_id="other-instance-2",
                now=other.clock.now(),
                discovery_source=other.discovery,
                market_data_source=other.market,
                event_source=other.events,
                composition_source=other.composer,
                denominator_source=other.denominator,
                writer=other.writer,
                lease_registry=other.leases,
                checkpoint_store=other.store,
            )

    def test_production_checkpoint_roots_are_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeCheckpointError, "temporary"):
            RuntimeCheckpointStore(Path.cwd() / "MomentumHunterData" / "data")

    def test_failure_injection_matrix_has_explicit_blast_radii(self) -> None:
        injections = {
            "discovery timeout": lambda: self.fixture.discovery.failures.append(TimeoutError()),
            "discovery contract failure": lambda: self.fixture.discovery.failures.append(ValueError()),
            "repeated discovery failure": lambda: self.fixture.discovery.failures.extend([RuntimeError(), RuntimeError()]),
            "readiness failure": lambda: self.fixture.market.fail_symbols.add("AAA"),
            "one-symbol exception": lambda: self.fixture.market.exception_symbols.add("AAA"),
            "composition exception": lambda: self.fixture.composer.fail_symbols.add("AAA"),
            "denominator incomplete": lambda: self.fixture.denominator.incomplete_symbols.add("AAA"),
            "writer unavailable": lambda: setattr(self.fixture.writer, "mode", WRITER_UNAVAILABLE),
            "writer slow": lambda: setattr(self.fixture.writer, "mode", WRITER_SLOW),
        }
        for name, inject in injections.items():
            with self.subTest(name=name):
                isolated = RuntimeFixture(self.root / name.replace(" ", "-"), identity="runtime-" + fp(name)[:12])
                isolated.runtime.start(isolated.clock.now())
                if name.startswith("discovery") or name.startswith("repeated"):
                    target = isolated.discovery
                    if name == "discovery timeout": target.failures.append(TimeoutError())
                    elif name == "discovery contract failure": target.failures.append(ValueError())
                    else: target.failures.extend([RuntimeError(), RuntimeError()])
                elif name == "readiness failure": isolated.market.fail_symbols.add("AAA")
                elif name == "one-symbol exception": isolated.market.exception_symbols.add("AAA")
                elif name == "composition exception": isolated.composer.fail_symbols.add("AAA")
                elif name == "denominator incomplete": isolated.denominator.incomplete_symbols.add("AAA")
                elif name == "writer unavailable": isolated.writer.mode = WRITER_UNAVAILABLE
                elif name == "writer slow": isolated.writer.mode = WRITER_SLOW
                isolated.runtime.submit_event(isolated.event("AAA"), isolated.clock.now())
                health = isolated.runtime.tick(isolated.clock.now())
                self.assertIn(health.process_state, {RUNNING, DEGRADED})
                self.assertIn(PROCESS_ALIVE, health.health_flags)

    def test_accelerated_full_session_soak_is_bounded_and_reconciles(self) -> None:
        fixture = RuntimeFixture(
            self.root / "soak",
            identity="full-session-soak",
            queues=QueueCapacities(discovery=2, readiness=10, composition=10, evidence=64, health=4),
        )
        fixture.runtime.start(fixture.clock.now())
        observation = measure_runtime_operation(
            fixture.runtime,
            fixture.clock,
            simulated_minutes=390,
            symbols=tuple(f"S{i:02d}" for i in range(30)),
        )
        self.assertTrue(observation.all_queues_drained)
        self.assertTrue(observation.evidence_intents_reconciled)
        self.assertTrue(observation.denominator_cycles_reconciled)
        self.assertTrue(observation.heartbeat_continuous)
        self.assertTrue(observation.bounded_state)
        self.assertEqual(30, observation.tracked_symbols)
        self.assertEqual(10, observation.readiness_slots)
        self.assertLessEqual(observation.maximum_queue_depth, 64)
        self.assertGreater(observation.composition_throughput_per_second, 0)

    def test_no_provider_broker_service_scheduler_or_paper_capability(self) -> None:
        source_path = Path("momentum_hunter/continuous_runtime.py")
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        forbidden_imports = (
            "requests",
            "urllib",
            "httpx",
            "socket",
            "subprocess",
            "schwab",
            "finviz",
            "alpaca",
            "broker",
            "automation",
            "engine_host",
            "wpf",
            "paper",
        )
        self.assertFalse(
            any(any(token in item.lower() for token in forbidden_imports) for item in imports)
        )
        lowered = source.lower()
        for token in (
            "submit_order",
            "cancel_order",
            "replace_order",
            "query_account",
            "automationsupervisor.tick",
            "paper_position",
        ):
            self.assertNotIn(token, lowered)


if __name__ == "__main__":
    unittest.main()
