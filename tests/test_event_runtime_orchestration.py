from __future__ import annotations

import ast
import hashlib
import os
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter.candidate_lifecycle import CandidateLifecycleStore
from momentum_hunter.continuous_plan_version import ContinuousPlanStore
from momentum_hunter.event_driven_decision_cycle import EventDecisionCycleStore
from momentum_hunter.event_runtime_evidence_chain import (
    RuntimeEvidenceChainWriterSession,
)
from momentum_hunter.event_runtime_orchestration import (
    CREATED,
    DUPLICATE_REPLAY,
    RECOVERED,
    RuntimeEvidenceOrchestrationError,
    RuntimeEvidenceOrchestrationRequest,
    RuntimeEvidenceOrchestrationResult,
    RuntimeEvidenceOrchestrator,
    validate_runtime_orchestration_result,
)
from momentum_hunter.event_runtime_topology import (
    PYTHON_ENGINE_HOST,
    build_runtime_writer_claim,
)
from momentum_hunter.event_runtime_writer_session import RuntimeWriterSessionError
from momentum_hunter.event_source_admission import RuntimeSourceAdmissionStore
from tests.test_event_driven_decision_cycle import BASE, CONFIGURATION, synthetic_decision
from tests.test_event_runtime_writer_session import (
    PROGRAM,
    RUNTIME_BUILD,
    build_runtime_writer_test_fixture,
)
from tests.test_event_source_admission import successor_plan


class EventRuntimeOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = build_runtime_writer_test_fixture()
        self.addCleanup(self.fixture.doCleanups)
        self.topology = self.fixture.topology
        self.host = self.fixture.host
        self.claim = self.fixture.claim

    def evidence(self, *, symbol: str = "AAA", clock_offset: int = 0):
        return self.fixture.build_chain_evidence(
            symbol=symbol,
            clock_offset=clock_offset,
        )

    def request(self, *, symbol: str = "AAA", clock_offset: int = 0):
        events, admission, plan, policy = self.evidence(
            symbol=symbol,
            clock_offset=clock_offset,
        )
        decision = synthetic_decision(
            plan,
            authorized=False,
            nonce=str(plan.version_number),
        )
        trigger_received = datetime.fromisoformat(admission.trigger.receipt_timestamp)
        plan_created = datetime.fromisoformat(plan.created_at)
        return RuntimeEvidenceOrchestrationRequest(
            candidate_events=events,
            plan_version=plan,
            source_admission=admission,
            policy=policy,
            decision=decision,
            cycle_started_at=max(
                trigger_received,
                plan_created - timedelta(seconds=1),
            ),
            recorded_at=datetime.fromisoformat(decision.decided_at)
            + timedelta(seconds=1),
        )

    def orchestrator(self, **changes) -> RuntimeEvidenceOrchestrator:
        values = {
            "topology": self.topology,
            "writer_claim": self.claim,
            "current_host_instance_id": self.host,
            "lease_timeout_seconds": 5.0,
        }
        values.update(changes)
        return RuntimeEvidenceOrchestrator(**values)

    def chain(self) -> RuntimeEvidenceChainWriterSession:
        return RuntimeEvidenceChainWriterSession(
            topology=self.topology,
            writer_claim=self.claim,
            current_host_instance_id=self.host,
        )

    def test_construction_is_nonmutating(self) -> None:
        self.orchestrator()

        self.assertFalse(self.fixture.root.exists())

    def test_empty_prefix_creates_complete_target_chain(self) -> None:
        request = self.request()
        result = self.orchestrator().execute(request)

        self.assertEqual(CREATED, result.status)
        self.assertEqual((), result.stages_present_before)
        self.assertEqual(
            request.source_admission.admission_id,
            result.after_snapshot.completed_admission_ids[0],
        )
        self.assertNotIn(
            request.plan_version.plan_version_id,
            result.after_snapshot.pending_plan_version_ids,
        )
        self.assertEqual(request.plan_version.plan_version_id, result.target_plan_version_id)
        self.assertRegex(result.fingerprint, r"^[0-9a-f]{64}$")

    def test_candidate_prefix_resumes_without_duplicate_events(self) -> None:
        request = self.request()
        chain = self.chain()
        with chain.activate():
            for event in request.candidate_events:
                chain.append_candidate_event(event)

        result = self.orchestrator().execute(request)

        self.assertEqual(RECOVERED, result.status)
        self.assertEqual(("CANDIDATE",), result.stages_present_before)
        self.assertEqual(
            request.candidate_events,
            CandidateLifecycleStore(chain.candidate_path).load().events,
        )

    def test_partial_candidate_batch_is_classified_as_recovery(self) -> None:
        request = self.request()
        chain = self.chain()
        with chain.activate():
            chain.append_candidate_event(request.candidate_events[0])

        result = self.orchestrator().execute(request)

        self.assertEqual(RECOVERED, result.status)
        self.assertEqual(("CANDIDATE",), result.stages_present_before)
        self.assertEqual(
            request.candidate_events,
            CandidateLifecycleStore(chain.candidate_path).load().events,
        )

    def test_plan_prefix_resumes_at_source_admission(self) -> None:
        request = self.request()
        chain = self.chain()
        with chain.activate():
            for event in request.candidate_events:
                chain.append_candidate_event(event)
            chain.append_plan_version(request.plan_version)

        result = self.orchestrator().execute(request)

        self.assertEqual(RECOVERED, result.status)
        self.assertEqual(("CANDIDATE", "PLAN"), result.stages_present_before)
        self.assertEqual(
            (request.plan_version,),
            ContinuousPlanStore(chain.plan_path).load().plans,
        )

    def test_admission_prefix_resumes_at_decision_cycle(self) -> None:
        request = self.request()
        chain = self.chain()
        with chain.activate():
            for event in request.candidate_events:
                chain.append_candidate_event(event)
            chain.append_plan_version(request.plan_version)
            chain.append_source_admission(request.source_admission)

        result = self.orchestrator().execute(request)

        self.assertEqual(RECOVERED, result.status)
        self.assertEqual(
            ("CANDIDATE", "PLAN", "SOURCE_ADMISSION"),
            result.stages_present_before,
        )
        self.assertEqual(
            (request.source_admission,),
            RuntimeSourceAdmissionStore(
                chain.source_admission_path,
                evidence_program_id=PROGRAM,
                configuration_fingerprint=CONFIGURATION,
            ).load().admissions,
        )

    def test_exact_complete_replay_is_byte_stable(self) -> None:
        request = self.request()
        first = self.orchestrator().execute(request)
        hashes_before = self._artifact_hashes()

        replay = self.orchestrator().execute(request)

        self.assertEqual(CREATED, first.status)
        self.assertEqual(DUPLICATE_REPLAY, replay.status)
        self.assertEqual(
            ("CANDIDATE", "PLAN", "SOURCE_ADMISSION", "DECISION_CYCLE"),
            replay.stages_present_before,
        )
        self.assertEqual(hashes_before, self._artifact_hashes())
        self.assertEqual(first.decision_result.receipt, replay.decision_result.receipt)
        self.assertEqual(first.decision_result.cycle, replay.decision_result.cycle)

    def test_invalid_decision_binding_fails_before_any_artifact_write(self) -> None:
        request = self.request()
        other = self.request(symbol="BBB")

        with self.assertRaisesRegex(ValueError, "does not match|does not bind"):
            self.orchestrator().execute(
                replace(request, decision=other.decision)
            )

        self.assertEqual({}, self._artifact_hashes())

    def test_invalid_cycle_chronology_fails_before_any_artifact_write(self) -> None:
        request = self.request()

        with self.assertRaisesRegex(ValueError, "chronology"):
            self.orchestrator().execute(
                replace(
                    request,
                    cycle_started_at=request.recorded_at + timedelta(seconds=1),
                )
            )

        self.assertEqual({}, self._artifact_hashes())

    def test_wrong_writer_identity_fails_before_any_artifact_write(self) -> None:
        request = self.request()
        invalid_claim = replace(self.claim, process_id=os.getpid() + 1)

        with self.assertRaises(RuntimeWriterSessionError):
            self.orchestrator(writer_claim=invalid_claim).execute(request)

        self.assertEqual({}, self._artifact_hashes())

    def test_target_completion_does_not_claim_unrelated_pending_plan_complete(self) -> None:
        target = self.request()
        pending = successor_plan(
            target.plan_version,
            regime_snapshot_fingerprint="d" * 64,
        )
        chain = self.chain()
        with chain.activate():
            for event in target.candidate_events:
                chain.append_candidate_event(event)
            chain.append_plan_version(target.plan_version)
            chain.append_plan_version(pending)

        result = self.orchestrator().execute(target)

        self.assertEqual(RECOVERED, result.status)
        self.assertIn(
            pending.plan_version_id,
            result.after_snapshot.pending_plan_version_ids,
        )
        self.assertIn(
            target.source_admission.admission_id,
            result.after_snapshot.completed_admission_ids,
        )

    def test_tampered_result_fingerprint_is_rejected(self) -> None:
        result = self.orchestrator().execute(self.request())

        with self.assertRaisesRegex(
            RuntimeEvidenceOrchestrationError,
            "fingerprint",
        ):
            validate_runtime_orchestration_result(
                replace(result, fingerprint="0" * 64)
            )

    def test_module_has_no_network_provider_account_broker_or_service_capability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module_path = root / "momentum_hunter" / "event_runtime_orchestration.py"
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
                    "start_host",
                }
            )
        )

    def test_no_existing_runtime_imports_orchestration(self) -> None:
        root = Path(__file__).resolve().parents[1] / "momentum_hunter"
        importers = []
        for path in root.rglob("*.py"):
            if path.name == "event_runtime_orchestration.py":
                continue
            if "event_runtime_orchestration" in path.read_text(encoding="utf-8"):
                importers.append(path.name)
        self.assertEqual([], importers)

    def _artifact_hashes(self) -> dict[str, str]:
        if not self.fixture.root.exists():
            return {}
        return {
            str(path.relative_to(self.fixture.root)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(self.fixture.root.rglob("*"))
            if path.is_file() and not path.name.startswith(".runtime-writer-session")
        }


if __name__ == "__main__":
    unittest.main()
