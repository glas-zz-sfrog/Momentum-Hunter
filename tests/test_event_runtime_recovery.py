from __future__ import annotations

import ast
import hashlib
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.candidate_lifecycle import (
    CandidateLifecycleLedger,
    CandidateLifecycleStore,
    lifecycle_event_fingerprint,
)
from momentum_hunter.continuous_plan_version import (
    ContinuousPlanLedger,
    ContinuousPlanStore,
)
from momentum_hunter.event_driven_decision_cycle import (
    EventDecisionCycleLedger,
    EventDecisionCycleStore,
)
from momentum_hunter.event_runtime_evidence_chain import (
    RuntimeEvidenceChainWriterSession,
    validate_runtime_evidence_chain_prefix,
)
from momentum_hunter.event_runtime_recovery import (
    APPEND_SOURCE_ADMISSION,
    COMPLETE,
    EMPTY,
    NO_ACTION,
    PROCESS_DECISION_CYCLE,
    RESUME_DECISION_CYCLE,
    RESUME_IN_STAGE_ORDER,
    RESUME_MULTIPLE_STAGES,
    RESUME_SOURCE_ADMISSION,
    WAITING_FOR_PLAN,
    WAIT_FOR_PLAN,
    RuntimeEvidenceRecoveryError,
    RuntimeEvidenceRecoveryPlanner,
    runtime_recovery_snapshot_fingerprint,
    validate_runtime_recovery_snapshot,
)
from momentum_hunter.event_runtime_topology import (
    OFFLINE_REVIEW,
    PYTHON_ENGINE_HOST,
    WINDOWS_AUTOMATION_SERVICE,
    artifact_path,
    build_event_runtime_topology,
)
from momentum_hunter.event_source_admission import (
    RuntimeSourceAdmissionStore,
    build_runtime_source_admission_ledger,
)
from tests.test_event_driven_decision_cycle import synthetic_decision
from tests.test_event_runtime_writer_session import (
    PROGRAM,
    RUNTIME_BUILD,
    build_runtime_writer_test_fixture,
)


class EventRuntimeRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_runtime_writer_test_fixture()
        self.addCleanup(self.fixture.doCleanups)
        self.topology = self.fixture.topology

    def chain(self) -> RuntimeEvidenceChainWriterSession:
        return RuntimeEvidenceChainWriterSession(
            topology=self.topology,
            writer_claim=self.fixture.claim,
            current_host_instance_id=self.fixture.host,
        )

    def planner(self, **changes) -> RuntimeEvidenceRecoveryPlanner:
        values = {
            "topology": self.topology,
            "process_role": OFFLINE_REVIEW,
        }
        values.update(changes)
        return RuntimeEvidenceRecoveryPlanner(**values)

    def evidence(self):
        return self.fixture.build_chain_evidence(symbol="AAA", clock_offset=0)

    @staticmethod
    def append_candidates(chain, events) -> None:
        for event in events:
            chain.append_candidate_event(event)

    @staticmethod
    def process_cycle(chain, admission, plan, policy):
        decision = synthetic_decision(
            plan,
            authorized=False,
            nonce=str(plan.version_number),
        )
        trigger_received = datetime.fromisoformat(admission.trigger.receipt_timestamp)
        plan_created = datetime.fromisoformat(plan.created_at)
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

    def test_construction_and_empty_inspection_are_nonmutating(self) -> None:
        planner = self.planner()

        self.assertFalse(self.fixture.root.exists())
        snapshot = planner.inspect()

        self.assertEqual(EMPTY, snapshot.status)
        self.assertEqual(NO_ACTION, snapshot.next_action)
        self.assertEqual(OFFLINE_REVIEW, snapshot.process_role)
        self.assertFalse(self.fixture.root.exists())
        self.assertEqual(4, len(planner.paths))
        validate_runtime_recovery_snapshot(snapshot)

    def test_engine_host_read_role_is_authorized_without_writer_claim(self) -> None:
        snapshot = self.planner(process_role=PYTHON_ENGINE_HOST).inspect()

        self.assertEqual(EMPTY, snapshot.status)
        self.assertEqual(PYTHON_ENGINE_HOST, snapshot.process_role)

    def test_service_role_is_denied_before_filesystem_inspection(self) -> None:
        with self.assertRaisesRegex(RuntimeEvidenceRecoveryError, "denied"):
            self.planner(process_role=WINDOWS_AUTOMATION_SERVICE)

        self.assertFalse(self.fixture.root.exists())

    def test_candidate_only_prefix_waits_for_plan(self) -> None:
        events, _, _, _ = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)

        snapshot = self.planner().inspect()

        self.assertEqual(WAITING_FOR_PLAN, snapshot.status)
        self.assertEqual(WAIT_FOR_PLAN, snapshot.next_action)
        self.assertEqual(len(events), snapshot.candidate_event_count)
        self.assertEqual(0, snapshot.plan_count)

    def test_plan_prefix_resumes_source_admission(self) -> None:
        events, _, plan, _ = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)
            chain.append_plan_version(plan)

        snapshot = self.planner().inspect()

        self.assertEqual(RESUME_SOURCE_ADMISSION, snapshot.status)
        self.assertEqual(APPEND_SOURCE_ADMISSION, snapshot.next_action)
        self.assertEqual((plan.plan_version_id,), snapshot.pending_plan_version_ids)

    def test_admission_prefix_resumes_decision_cycle(self) -> None:
        events, admission, plan, _ = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)
            chain.append_plan_version(plan)
            chain.append_source_admission(admission)

        snapshot = self.planner().inspect()

        self.assertEqual(RESUME_DECISION_CYCLE, snapshot.status)
        self.assertEqual(PROCESS_DECISION_CYCLE, snapshot.next_action)
        self.assertEqual((admission.admission_id,), snapshot.pending_admission_ids)

    def test_independent_partial_prefixes_resume_in_stage_order(self) -> None:
        events_a, admission_a, plan_a, _ = self.fixture.build_chain_evidence(
            symbol="AAA",
            clock_offset=0,
        )
        events_b, _, plan_b, _ = self.fixture.build_chain_evidence(
            symbol="BBB",
            clock_offset=0,
        )
        events_b = tuple(
            replace(
                resequenced,
                fingerprint=lifecycle_event_fingerprint(resequenced),
            )
            for resequenced in (
                replace(event, sequence=len(events_a) + offset, fingerprint="")
                for offset, event in enumerate(events_b, start=1)
            )
        )
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events_a)
            self.append_candidates(chain, events_b)
            chain.append_plan_version(plan_a)
            chain.append_source_admission(admission_a)
            chain.append_plan_version(plan_b)

        snapshot = self.planner().inspect()

        self.assertEqual(RESUME_MULTIPLE_STAGES, snapshot.status)
        self.assertEqual(RESUME_IN_STAGE_ORDER, snapshot.next_action)
        self.assertEqual((plan_b.plan_version_id,), snapshot.pending_plan_version_ids)
        self.assertEqual(
            (admission_a.admission_id,),
            snapshot.pending_admission_ids,
        )

    def test_complete_chain_has_no_recovery_action(self) -> None:
        events, admission, plan, policy = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)
            chain.append_plan_version(plan)
            chain.append_source_admission(admission)
            result = self.process_cycle(chain, admission, plan, policy)

        snapshot = self.planner().inspect()

        self.assertIsNotNone(result.cycle)
        self.assertEqual(COMPLETE, snapshot.status)
        self.assertEqual(NO_ACTION, snapshot.next_action)
        self.assertEqual((admission.admission_id,), snapshot.completed_admission_ids)
        self.assertEqual(1, snapshot.receipt_count)
        self.assertEqual(1, snapshot.cycle_count)

    def test_snapshot_is_deterministic_and_does_not_mutate_source_files(self) -> None:
        events, admission, plan, _ = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)
            chain.append_plan_version(plan)
            chain.append_source_admission(admission)
        before = self._source_hashes()

        first = self.planner().inspect()
        second = self.planner().inspect()

        self.assertEqual(first, second)
        self.assertEqual(before, self._source_hashes())

    def test_refingerprinted_contradictory_classification_is_rejected(self) -> None:
        snapshot = self.planner().inspect()
        contradictory = replace(
            snapshot,
            status=COMPLETE,
            fingerprint="",
        )
        contradictory = replace(
            contradictory,
            fingerprint=runtime_recovery_snapshot_fingerprint(contradictory),
        )

        with self.assertRaisesRegex(
            RuntimeEvidenceRecoveryError,
            "classification",
        ):
            validate_runtime_recovery_snapshot(contradictory)

    def test_artifact_change_during_inspection_fails_closed(self) -> None:
        events, _, plan, _ = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)
        planner = self.planner()
        original_load = planner._candidate_store.load

        def load_then_advance_plan():
            ledger = original_load()
            ContinuousPlanStore(chain.plan_path).append(plan)
            return ledger

        planner._candidate_store.load = load_then_advance_plan

        with self.assertRaisesRegex(
            RuntimeEvidenceRecoveryError,
            "changed during",
        ):
            planner.inspect()

    def test_raw_plan_without_candidate_chain_is_rejected(self) -> None:
        _, _, plan, _ = self.evidence()
        plan_path = artifact_path(self.topology, "CONTINUOUS_PLAN_LEDGER")
        ContinuousPlanStore(plan_path).append(plan)

        with self.assertRaisesRegex(
            RuntimeEvidenceRecoveryError,
            "RuntimeEvidenceChainError",
        ):
            self.planner().inspect()

    def test_public_prefix_validator_rejects_unvalidated_ledger_input(self) -> None:
        events, _, _, _ = self.evidence()
        tampered = replace(events[-1], evidence_fingerprint="f" * 64)
        candidate_ledger = CandidateLifecycleLedger(
            events=events[:-1] + (tampered,)
        )

        with self.assertRaises(ValueError):
            validate_runtime_evidence_chain_prefix(
                self.topology,
                candidate_ledger=candidate_ledger,
                plan_ledger=ContinuousPlanLedger(),
                admission_ledger=build_runtime_source_admission_ledger(
                    evidence_program_id=PROGRAM,
                    configuration_fingerprint=self.topology.configuration_fingerprint,
                ),
                cycle_ledger=EventDecisionCycleLedger(),
            )

    def test_cycle_without_admission_is_rejected(self) -> None:
        events, admission, plan, policy = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)
            chain.append_plan_version(plan)
            chain.append_source_admission(admission)
            self.process_cycle(chain, admission, plan, policy)
        chain.source_admission_path.unlink()

        with self.assertRaisesRegex(
            RuntimeEvidenceRecoveryError,
            "RuntimeEvidenceChainError",
        ):
            self.planner().inspect()

    def test_cross_program_admission_ledger_is_rejected(self) -> None:
        events, admission, plan, _ = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)
            chain.append_plan_version(plan)
            chain.append_source_admission(admission)
        other = build_event_runtime_topology(
            root_path=Path(self.fixture.temporary.name) / "other-root",
            evidence_program_id="other-program",
            configuration_fingerprint=self.topology.configuration_fingerprint,
            runtime_build_hash=RUNTIME_BUILD,
        )
        target = artifact_path(other, "RUNTIME_SOURCE_ADMISSION_LEDGER")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(chain.source_admission_path.read_bytes())

        with self.assertRaisesRegex(
            RuntimeEvidenceRecoveryError,
            "RuntimeSourceAdmissionError",
        ):
            self.planner(topology=other).inspect()

    def test_malformed_ledger_error_is_redacted_and_fail_closed(self) -> None:
        path = artifact_path(self.topology, "CANDIDATE_LIFECYCLE_LEDGER")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json", encoding="utf-8")

        with self.assertRaisesRegex(
            RuntimeEvidenceRecoveryError,
            "CandidateLifecycleError",
        ) as caught:
            self.planner().inspect()

        self.assertNotIn(str(path), str(caught.exception))

    def test_artifact_hashes_change_when_valid_prefix_advances(self) -> None:
        before = self.planner().inspect()
        events, _, _, _ = self.evidence()
        chain = self.chain()
        with chain.activate():
            self.append_candidates(chain, events)
        after = self.planner().inspect()

        self.assertNotEqual(before.fingerprint, after.fingerprint)
        self.assertEqual("", before.artifact_hashes[0][1])
        self.assertRegex(after.artifact_hashes[0][1], r"^[0-9a-f]{64}$")

    def test_module_has_no_external_or_mutating_capability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module_path = root / "momentum_hunter" / "event_runtime_recovery.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
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
                    "append",
                    "append_event",
                    "save",
                    "submit_order",
                    "cancel_order",
                    "replace_order",
                    "get_account",
                    "get_positions",
                    "start_service",
                }
            )
        )

    def test_no_existing_runtime_imports_recovery_planner(self) -> None:
        root = Path(__file__).resolve().parents[1] / "momentum_hunter"
        importers = []
        for path in root.rglob("*.py"):
            if path.name == "event_runtime_recovery.py":
                continue
            if "event_runtime_recovery" in path.read_text(encoding="utf-8"):
                importers.append(path.name)
        self.assertEqual([], importers)

    def _source_hashes(self) -> dict[str, str]:
        if not self.fixture.root.exists():
            return {}
        return {
            str(path.relative_to(self.fixture.root)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(self.fixture.root.rglob("*"))
            if path.is_file()
        }


if __name__ == "__main__":
    unittest.main()
