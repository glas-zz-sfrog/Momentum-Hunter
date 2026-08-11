from __future__ import annotations

import ast
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.candidate_lifecycle import (
    AVAILABILITY_FAILED,
    DISCOVERY_SCOPE,
    CandidateLifecycleCoordinator,
    CandidateLifecycleLedger,
    CandidateLifecyclePolicy,
    CandidateLifecycleStore,
)
from momentum_hunter.continuous_plan_version import (
    ContinuousPlanLedger,
    ContinuousPlanStore,
)
from momentum_hunter.event_driven_decision_cycle import (
    DUPLICATE,
    EventDecisionCycleStore,
)
from momentum_hunter.event_runtime_evidence_chain import (
    RuntimeEvidenceChainError,
    RuntimeEvidenceChainWriterSession,
)
from momentum_hunter.event_runtime_topology import (
    CANDIDATE_LIFECYCLE_LEDGER,
    CONTINUOUS_PLAN_LEDGER,
    EVENT_DECISION_CYCLE_LEDGER,
    RUNTIME_SOURCE_ADMISSION_LEDGER,
    PYTHON_ENGINE_HOST,
    artifact_path,
    build_runtime_writer_claim,
)
from momentum_hunter.event_runtime_writer_session import (
    SESSION_ACTIVE,
    SESSION_CLOSED,
    SESSION_NEW,
    RuntimeWriterSessionError,
)
from momentum_hunter.event_source_admission import (
    RuntimeSourceAdmissionStore,
    admit_runtime_trigger_source,
)
from tests.test_event_driven_decision_cycle import (
    BASE,
    CONFIGURATION,
    synthetic_decision,
)
from tests.test_event_runtime_writer_session import (
    PROGRAM,
    RUNTIME_BUILD,
    build_runtime_writer_test_fixture,
)
from tests.test_event_source_admission import refingerprint_plan, successor_plan


class EventRuntimeEvidenceChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_runtime_writer_test_fixture()
        self.addCleanup(self.fixture.doCleanups)
        self.topology = self.fixture.topology
        self.host = self.fixture.host
        self.claim = self.fixture.claim

    def chain(self, **changes) -> RuntimeEvidenceChainWriterSession:
        values = {
            "topology": self.topology,
            "writer_claim": self.claim,
            "current_host_instance_id": self.host,
            "lease_timeout_seconds": 5.0,
        }
        values.update(changes)
        return RuntimeEvidenceChainWriterSession(**values)

    def evidence(self, *, symbol: str = "AAA", clock_offset: int = 0):
        return self.fixture.build_chain_evidence(
            symbol=symbol,
            clock_offset=clock_offset,
        )

    def process_cycle(self, chain, admission, plan, policy):
        decision = synthetic_decision(
            plan,
            authorized=False,
            nonce=str(plan.version_number),
        )
        plan_created = datetime.fromisoformat(plan.created_at)
        trigger_received = datetime.fromisoformat(admission.trigger.receipt_timestamp)
        return chain.process_decision_cycle(
            admission,
            policy=policy,
            cycle_started_at=max(
                trigger_received,
                plan_created - timedelta(seconds=1),
            ),
            plan_version=plan,
            decision=decision,
            recorded_at=datetime.fromisoformat(decision.decided_at)
            + timedelta(seconds=1),
        )

    @staticmethod
    def append_candidate_events(chain, events):
        for event in events:
            chain.append_candidate_event(event)
        return events[-1]

    def test_construction_is_nonmutating_and_binds_all_topology_paths(self) -> None:
        chain = self.chain()

        self.assertEqual(SESSION_NEW, chain.state)
        self.assertEqual(
            artifact_path(self.topology, CANDIDATE_LIFECYCLE_LEDGER),
            chain.candidate_path,
        )
        self.assertEqual(
            artifact_path(self.topology, CONTINUOUS_PLAN_LEDGER),
            chain.plan_path,
        )
        self.assertEqual(
            artifact_path(self.topology, RUNTIME_SOURCE_ADMISSION_LEDGER),
            chain.source_admission_path,
        )
        self.assertEqual(
            artifact_path(self.topology, EVENT_DECISION_CYCLE_LEDGER),
            chain.cycle_path,
        )
        self.assertFalse(self.fixture.root.exists())

    def test_complete_chain_is_ordered_persisted_and_idempotent(self) -> None:
        events, admission, plan, policy = self.evidence()
        event = events[-1]
        chain = self.chain()
        with chain.activate():
            self.assertEqual(SESSION_ACTIVE, chain.state)
            self.assertEqual(event, self.append_candidate_events(chain, events))
            self.assertEqual(plan, chain.append_plan_version(plan))
            self.assertEqual(admission, chain.append_source_admission(admission))
            created = self.process_cycle(chain, admission, plan, policy)

            self.assertEqual(event, self.append_candidate_events(chain, events))
            self.assertEqual(plan, chain.append_plan_version(plan))
            self.assertEqual(admission, chain.append_source_admission(admission))
            duplicate = self.process_cycle(chain, admission, plan, policy)

        self.assertEqual(SESSION_CLOSED, chain.state)
        self.assertIsNotNone(created.cycle)
        self.assertEqual(DUPLICATE, duplicate.status)
        self.assertEqual(created.receipt, duplicate.receipt)
        self.assertEqual(created.cycle, duplicate.cycle)
        self.assertEqual(
            events,
            CandidateLifecycleStore(chain.candidate_path).load().events,
        )
        self.assertEqual(
            (plan,),
            ContinuousPlanStore(chain.plan_path).load().plans,
        )
        self.assertEqual(
            (admission,),
            RuntimeSourceAdmissionStore(
                chain.source_admission_path,
                evidence_program_id=PROGRAM,
                configuration_fingerprint=CONFIGURATION,
            ).load().admissions,
        )
        cycle_ledger = EventDecisionCycleStore(chain.cycle_path).load()
        self.assertEqual((created.receipt,), cycle_ledger.receipts)
        self.assertEqual((created.cycle,), cycle_ledger.cycles)

    def test_stage_order_fails_closed_without_later_artifacts(self) -> None:
        events, admission, plan, policy = self.evidence()

        plan_first = self.chain()
        with plan_first.activate():
            with self.assertRaisesRegex(RuntimeEvidenceChainError, "candidate event"):
                plan_first.append_plan_version(plan)
        self.assertFalse(plan_first.plan_path.exists())

        source_first = self.chain()
        with source_first.activate():
            self.append_candidate_events(source_first, events)
            with self.assertRaisesRegex(RuntimeEvidenceChainError, "persisted plan"):
                source_first.append_source_admission(admission)
        self.assertFalse(source_first.source_admission_path.exists())

        cycle_first = self.chain()
        with cycle_first.activate():
            self.append_candidate_events(cycle_first, events)
            cycle_first.append_plan_version(plan)
            with self.assertRaisesRegex(RuntimeWriterSessionError, "not persisted"):
                self.process_cycle(cycle_first, admission, plan, policy)
        self.assertFalse(cycle_first.cycle_path.exists())

    def test_restart_replays_partial_chain_without_duplicate_evidence(self) -> None:
        events, admission, plan, policy = self.evidence()
        first = self.chain()
        with first.activate():
            self.append_candidate_events(first, events)

        replacement_host = "synthetic-engine-host-replacement"
        replacement_claim = build_runtime_writer_claim(
            self.topology,
            process_role=PYTHON_ENGINE_HOST,
            host_instance_id=replacement_host,
            process_id=os.getpid(),
            runtime_build_hash=RUNTIME_BUILD,
            configuration_fingerprint=CONFIGURATION,
            claimed_at=BASE + timedelta(minutes=1),
        )
        replacement = self.chain(
            writer_claim=replacement_claim,
            current_host_instance_id=replacement_host,
        )
        with replacement.activate():
            self.append_candidate_events(replacement, events)
            replacement.append_plan_version(plan)
            replacement.append_source_admission(admission)
            result = self.process_cycle(replacement, admission, plan, policy)

        self.assertIsNotNone(result.cycle)
        self.assertEqual(
            len(events),
            len(CandidateLifecycleStore(replacement.candidate_path).load().events),
        )
        self.assertEqual(
            1,
            len(ContinuousPlanStore(replacement.plan_path).load().plans),
        )
        self.assertEqual(
            1,
            len(EventDecisionCycleStore(replacement.cycle_path).load().cycles),
        )

    def test_plan_successor_source_extends_the_same_ordered_chain(self) -> None:
        events, _, initial_plan, policy = self.evidence()
        policy = replace(policy, cooldown_seconds=0)
        initial_admission = admit_runtime_trigger_source(
            plan_version=initial_plan,
            plan_ledger=ContinuousPlanLedger(plans=(initial_plan,)),
            event_cycle_policy=policy,
            candidate_event=events[-1],
            candidate_ledger=CandidateLifecycleLedger(events=events),
        )
        successor = successor_plan(
            initial_plan,
            regime_snapshot_fingerprint="d" * 64,
        )
        successor_admission = admit_runtime_trigger_source(
            plan_version=successor,
            previous_plan_version=initial_plan,
            plan_ledger=ContinuousPlanLedger(plans=(initial_plan, successor)),
            event_cycle_policy=policy,
        )
        chain = self.chain()

        with chain.activate():
            self.append_candidate_events(chain, events)
            chain.append_plan_version(initial_plan)
            chain.append_source_admission(initial_admission)
            initial_result = self.process_cycle(
                chain,
                initial_admission,
                initial_plan,
                policy,
            )
            chain.append_plan_version(successor)
            chain.append_source_admission(successor_admission)
            successor_result = self.process_cycle(
                chain,
                successor_admission,
                successor,
                policy,
            )

        self.assertIsNotNone(initial_result.cycle)
        self.assertIsNotNone(successor_result.cycle)
        self.assertEqual(
            initial_result.cycle.cycle_id,
            successor_result.cycle.predecessor_cycle_id,
        )
        self.assertEqual(
            (initial_plan, successor),
            ContinuousPlanStore(chain.plan_path).load().plans,
        )
        self.assertEqual(
            (initial_admission, successor_admission),
            RuntimeSourceAdmissionStore(
                chain.source_admission_path,
                evidence_program_id=PROGRAM,
                configuration_fingerprint=CONFIGURATION,
            ).load().admissions,
        )

    def test_raw_plan_bypass_cannot_admit_without_candidate_chain(self) -> None:
        _, admission, plan, _ = self.evidence()
        chain = self.chain()
        ContinuousPlanStore(chain.plan_path).append(plan)

        with chain.activate():
            with self.assertRaisesRegex(RuntimeEvidenceChainError, "candidate event"):
                chain.append_source_admission(admission)

        self.assertFalse(chain.source_admission_path.exists())

    def test_cross_configuration_plan_and_policy_are_rejected(self) -> None:
        events, admission, plan, policy = self.evidence()
        other_plan = refingerprint_plan(
            replace(plan, configuration_fingerprint="d" * 64)
        )
        chain = self.chain()
        with chain.activate():
            self.append_candidate_events(chain, events)
            with self.assertRaisesRegex(
                RuntimeEvidenceChainError,
                "different runtime configuration",
            ):
                chain.append_plan_version(other_plan)
            chain.append_plan_version(plan)
            chain.append_source_admission(admission)
            with self.assertRaisesRegex(
                RuntimeEvidenceChainError,
                "policy does not match",
            ):
                chain.process_decision_cycle(
                    admission,
                    policy=replace(policy, configuration_fingerprint="d" * 64),
                    recorded_at=BASE + timedelta(seconds=3),
                )

        self.assertFalse(chain.cycle_path.exists())

    def test_existing_mixed_configuration_plan_ledger_fails_closed(self) -> None:
        events, _, plan, _ = self.evidence()
        other_plan = refingerprint_plan(
            replace(plan, configuration_fingerprint="d" * 64)
        )
        chain = self.chain()
        ContinuousPlanStore(chain.plan_path).append(other_plan)

        with chain.activate():
            self.append_candidate_events(chain, events)
            with self.assertRaisesRegex(
                RuntimeEvidenceChainError,
                "ledger contains a different",
            ):
                chain.append_plan_version(plan)

        self.assertEqual(
            (other_plan,),
            ContinuousPlanStore(chain.plan_path).load().plans,
        )

    def test_availability_event_uses_same_candidate_artifact_authority(self) -> None:
        policy = CandidateLifecyclePolicy(
            policy_version="synthetic-candidate-v1",
            cooldown_seconds=30,
            hysteresis_profile="synthetic-hysteresis-v1",
            minimum_delta_profile="synthetic-material-delta-v1",
        )
        fixture_store = CandidateLifecycleStore(
            Path(self.fixture.temporary.name) / "availability-fixture.json"
        )
        availability = CandidateLifecycleCoordinator(
            fixture_store,
            policy=policy,
        ).record_availability(
            scope=DISCOVERY_SCOPE,
            status=AVAILABILITY_FAILED,
            occurred_at=BASE,
            source_identity="synthetic-monitor",
            evidence_fingerprint="a" * 64,
            reason="Synthetic discovery outage.",
        )
        chain = self.chain()

        with chain.activate():
            self.assertEqual(
                availability,
                chain.append_availability_event(availability),
            )
            self.assertEqual(
                availability,
                chain.append_availability_event(availability),
            )

        self.assertEqual(
            (availability,),
            CandidateLifecycleStore(chain.candidate_path).load().availability_events,
        )

    def test_store_path_rebinding_is_rejected_before_write(self) -> None:
        events, _, plan, _ = self.evidence()
        chain = self.chain()
        chain._plan_store.path = chain.candidate_path
        with chain.activate():
            self.append_candidate_events(chain, events)
            with self.assertRaisesRegex(RuntimeEvidenceChainError, "escaped"):
                chain.append_plan_version(plan)

        self.assertFalse(chain.plan_path.exists())

    def test_operations_require_active_current_writer_session(self) -> None:
        events, admission, plan, policy = self.evidence()
        event = events[-1]
        chain = self.chain()
        operations = (
            lambda: chain.append_candidate_event(event),
            lambda: chain.append_plan_version(plan),
            lambda: chain.append_source_admission(admission),
            lambda: self.process_cycle(chain, admission, plan, policy),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaises(RuntimeWriterSessionError):
                    operation()

    def test_module_has_no_network_provider_broker_service_or_order_capability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module_path = root / "momentum_hunter" / "event_runtime_evidence_chain.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
                    imports.add(alias.name.rsplit(".", 1)[-1])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
                imports.add(node.module.rsplit(".", 1)[-1])
        self.assertTrue(
            imports.isdisjoint(
                {
                    "requests",
                    "urllib",
                    "httpx",
                    "socket",
                    "websocket",
                    "subprocess",
                    "alpaca_paper",
                    "schwab_market_data",
                    "shadow_trading",
                    "automation_supervisor",
                    "engine_host",
                }
            )
        )
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            calls.isdisjoint(
                {
                    "submit_order",
                    "cancel_order",
                    "replace_order",
                    "get_account",
                    "get_positions",
                    "start_service",
                }
            )
        )

    def test_no_existing_runtime_imports_evidence_chain(self) -> None:
        root = Path(__file__).resolve().parents[1] / "momentum_hunter"
        importers = []
        for path in root.rglob("*.py"):
            if path.name == "event_runtime_evidence_chain.py":
                continue
            if path.name == "event_runtime_recovery.py":
                continue
            if path.name == "event_runtime_orchestration.py":
                continue
            if "event_runtime_evidence_chain" in path.read_text(encoding="utf-8"):
                importers.append(path.name)
        self.assertEqual([], importers)


if __name__ == "__main__":
    unittest.main()
