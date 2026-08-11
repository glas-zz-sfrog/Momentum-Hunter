from __future__ import annotations

import ast
import multiprocessing
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

from momentum_hunter.candidate_lifecycle import (
    BREAKOUT_FORMING,
    WATCHING,
    CandidateLifecycleCoordinator,
    CandidateLifecyclePolicy,
    CandidateLifecycleStore,
)
from momentum_hunter.continuous_plan_version import ContinuousPlanLedger
from momentum_hunter.event_driven_decision_cycle import (
    CANDIDATE_STATE_CHANGED,
    DATA_BECAME_STALE,
    PLAN_INVALIDATED,
    PLAN_MATERIAL_REVISION,
)
from momentum_hunter.event_runtime_topology import (
    PYTHON_ENGINE_HOST,
    RUNTIME_SOURCE_ADMISSION_LEDGER,
    artifact_path,
    build_event_runtime_topology,
    build_runtime_writer_claim,
)
from momentum_hunter.event_runtime_writer_session import (
    SESSION_ACTIVE,
    SESSION_CLOSED,
    SESSION_NEW,
    RuntimeSourceAdmissionWriterSession,
    RuntimeWriterSessionError,
    writer_session_target_path,
)
from momentum_hunter.event_source_admission import (
    RuntimeSourceAdmissionError,
    RuntimeSourceAdmissionStore,
    admit_runtime_trigger_source,
)
from momentum_hunter.intraday_trade_plan import CONTINUATION_BREAKOUT
from tests.test_event_driven_decision_cycle import (
    BASE,
    CONFIGURATION,
    synthetic_plan,
    synthetic_policy,
)
from tests.test_event_source_admission import refingerprint_plan, successor_plan


RUNTIME_BUILD = "c" * 64
PROGRAM = "engineering-shadow-025"


def _build_claim(topology, *, host_instance_id: str):
    return build_runtime_writer_claim(
        topology,
        process_role=PYTHON_ENGINE_HOST,
        host_instance_id=host_instance_id,
        process_id=os.getpid(),
        runtime_build_hash=RUNTIME_BUILD,
        configuration_fingerprint=CONFIGURATION,
        claimed_at=BASE,
    )


def _hold_writer_session_worker(
    topology,
    ready_event,
    release_event,
    output_queue,
) -> None:
    try:
        host = f"synthetic-host-{os.getpid()}"
        session = RuntimeSourceAdmissionWriterSession(
            topology=topology,
            writer_claim=_build_claim(topology, host_instance_id=host),
            current_host_instance_id=host,
        )
        with session.activate():
            ready_event.set()
            if not release_event.wait(10):
                raise RuntimeError("Synthetic writer-session release gate timed out.")
        output_queue.put(("OK", session.state))
    except Exception as exc:  # pragma: no cover - asserted by parent process
        output_queue.put(("ERROR", type(exc).__name__, str(exc)))


def _exit_while_holding_writer_session_worker(topology, ready_event) -> None:
    host = f"synthetic-host-{os.getpid()}"
    session = RuntimeSourceAdmissionWriterSession(
        topology=topology,
        writer_claim=_build_claim(topology, host_instance_id=host),
        current_host_instance_id=host,
    )
    with session.activate():
        ready_event.set()
        os._exit(31)


class EventRuntimeWriterSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "runtime-state"
        self.topology = build_event_runtime_topology(
            root_path=self.root,
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
            runtime_build_hash=RUNTIME_BUILD,
        )
        self.host = "synthetic-engine-host-a"
        self.claim = _build_claim(self.topology, host_instance_id=self.host)

    def session(self, **changes):
        values = {
            "topology": self.topology,
            "writer_claim": self.claim,
            "current_host_instance_id": self.host,
            "lease_timeout_seconds": 5.0,
        }
        values.update(changes)
        return RuntimeSourceAdmissionWriterSession(**values)

    def build_initial_admission(self, *, symbol: str, clock_offset: int):
        candidate_policy = CandidateLifecyclePolicy(
            policy_version="synthetic-candidate-v1",
            cooldown_seconds=30,
            hysteresis_profile="synthetic-hysteresis-v1",
            minimum_delta_profile="synthetic-material-delta-v1",
        )
        candidate_store = CandidateLifecycleStore(
            Path(self.temporary.name) / f"candidate-{symbol}.json"
        )
        coordinator = CandidateLifecycleCoordinator(
            candidate_store,
            policy=candidate_policy,
        )
        start = BASE - timedelta(minutes=10 - clock_offset)
        discovered = coordinator.discover(
            symbol=symbol,
            session_date="2026-08-10",
            originating_evidence_family="CONTINUOUS_MONITOR",
            evidence_fingerprint=("1" if symbol == "AAA" else "a") * 64,
            source_identity="synthetic-monitor",
            occurred_at=start,
            provider_timestamp=start - timedelta(seconds=1),
            receipt_timestamp=start,
            reason="Synthetic candidate discovery.",
        )
        opportunity = discovered.snapshot.opportunity_id
        coordinator.transition(
            opportunity_id=opportunity,
            next_state=WATCHING,
            evidence_fingerprint=("2" if symbol == "AAA" else "b") * 64,
            source_identity="synthetic-monitor",
            occurred_at=start + timedelta(minutes=1),
            provider_timestamp=start + timedelta(minutes=1, seconds=-1),
            receipt_timestamp=start + timedelta(minutes=1),
            reason="Synthetic monitoring began.",
            material_delta_kind="MONITORING_ACTIVATED",
        )
        event = coordinator.transition(
            opportunity_id=opportunity,
            next_state=BREAKOUT_FORMING,
            evidence_fingerprint=("4" if symbol == "AAA" else "c") * 64,
            source_identity="synthetic-candles",
            occurred_at=start + timedelta(minutes=2),
            provider_timestamp=start + timedelta(minutes=2, seconds=-1),
            receipt_timestamp=start + timedelta(minutes=2),
            reason="Synthetic breakout structure became material.",
            material_delta_kind="SETUP_IDENTITY_CHANGED",
            setup_family=CONTINUATION_BREAKOUT,
            create_new_setup=True,
        ).event
        plan = synthetic_plan(
            created_at=BASE + timedelta(seconds=clock_offset),
            candidate_state=event.next_state,
            candidate_event_id=event.event_id,
            candidate_evidence=event.evidence_fingerprint,
            opportunity_id=event.opportunity_id,
            setup_id=event.setup_id,
            setup_evidence=event.evidence_fingerprint,
            version_number=1,
        )
        plan = refingerprint_plan(
            replace(
                plan,
                symbol=event.symbol,
                session_date=event.session_date,
                setup_family=event.setup_family,
                setup_sequence=event.setup_sequence,
                candidate_policy_fingerprint=event.policy_fingerprint,
                candidate_updated_at=event.receipt_timestamp,
            )
        )
        policy = synthetic_policy(
            allowed_trigger_types=tuple(
                sorted(
                    {
                        CANDIDATE_STATE_CHANGED,
                        DATA_BECAME_STALE,
                        PLAN_INVALIDATED,
                        PLAN_MATERIAL_REVISION,
                    }
                )
            )
        )
        admission = admit_runtime_trigger_source(
            plan_version=plan,
            plan_ledger=ContinuousPlanLedger(plans=(plan,)),
            event_cycle_policy=policy,
            candidate_event=event,
            candidate_ledger=candidate_store.load(),
        )
        return admission, plan, policy

    def test_construction_is_nonmutating_and_binds_topology_path(self) -> None:
        session = self.session()

        self.assertEqual(SESSION_NEW, session.state)
        self.assertEqual(
            artifact_path(self.topology, RUNTIME_SOURCE_ADMISSION_LEDGER),
            session.source_admission_path,
        )
        self.assertEqual(
            writer_session_target_path(self.topology).with_name(
                ".runtime-writer-session.lock"
            ),
            session.writer_lease_path,
        )
        self.assertFalse(self.root.exists())

    def test_active_session_appends_and_exact_replay_is_idempotent(self) -> None:
        admission, _, _ = self.build_initial_admission(
            symbol="AAA",
            clock_offset=0,
        )
        session = self.session()
        with session.activate() as active:
            self.assertEqual(SESSION_ACTIVE, active.state)
            self.assertEqual(admission, active.append_source_admission(admission))
            before = active.source_admission_path.read_bytes()
            self.assertEqual(admission, active.append_source_admission(admission))
            self.assertEqual(before, active.source_admission_path.read_bytes())

        self.assertEqual(SESSION_CLOSED, session.state)
        stored = RuntimeSourceAdmissionStore(
            session.source_admission_path,
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
        ).load().admissions
        self.assertEqual((admission,), stored)

    def test_append_before_or_after_session_is_denied(self) -> None:
        admission, _, _ = self.build_initial_admission(
            symbol="AAA",
            clock_offset=0,
        )
        session = self.session()
        with self.assertRaisesRegex(RuntimeWriterSessionError, "active writer"):
            session.append_source_admission(admission)
        with session.activate():
            pass
        with self.assertRaisesRegex(RuntimeWriterSessionError, "active writer"):
            session.append_source_admission(admission)
        with self.assertRaisesRegex(RuntimeWriterSessionError, "single-use"):
            with session.activate():
                self.fail("Closed writer session was reactivated.")

    def test_wrong_process_host_or_tampered_claim_fails_before_mutation(self) -> None:
        cases = (
            self.session(writer_claim=replace(self.claim, process_id=os.getpid() + 1)),
            self.session(current_host_instance_id="replacement-host"),
            self.session(writer_claim=replace(self.claim, fingerprint="0" * 64)),
        )
        for session in cases:
            with self.subTest(session=session):
                with self.assertRaises(RuntimeWriterSessionError):
                    with session.activate():
                        self.fail("Invalid writer identity became active.")
        self.assertFalse(self.root.exists())

    def test_cross_configuration_admission_is_denied_before_persistence(self) -> None:
        admission, _, _ = self.build_initial_admission(
            symbol="AAA",
            clock_offset=0,
        )
        other_configuration = "d" * 64
        other_topology = build_event_runtime_topology(
            root_path=self.root,
            evidence_program_id=PROGRAM,
            configuration_fingerprint=other_configuration,
            runtime_build_hash=RUNTIME_BUILD,
        )
        other_claim = build_runtime_writer_claim(
            other_topology,
            process_role=PYTHON_ENGINE_HOST,
            host_instance_id=self.host,
            process_id=os.getpid(),
            runtime_build_hash=RUNTIME_BUILD,
            configuration_fingerprint=other_configuration,
            claimed_at=BASE,
        )
        session = self.session(
            topology=other_topology,
            writer_claim=other_claim,
        )
        with session.activate():
            with self.assertRaisesRegex(
                RuntimeWriterSessionError,
                "different configuration",
            ):
                session.append_source_admission(admission)

        self.assertFalse(session.source_admission_path.exists())

    def test_second_local_session_cannot_reenter_lifetime_lease(self) -> None:
        first = self.session()
        second = self.session()
        with first.activate():
            with self.assertRaisesRegex(RuntimeWriterSessionError, "already active"):
                with second.activate():
                    self.fail("Second local writer session became active.")

    def test_same_session_cannot_activate_twice_across_threads(self) -> None:
        session = self.session()
        first_active = threading.Event()
        release_first = threading.Event()

        def hold_first_activation() -> str:
            with session.activate():
                first_active.set()
                if not release_first.wait(5):
                    raise RuntimeError("Synthetic activation release gate timed out.")
            return session.state

        def attempt_second_activation() -> str:
            if not first_active.wait(5):
                raise RuntimeError("Synthetic activation start gate timed out.")
            try:
                with session.activate():
                    return "UNEXPECTED_ACTIVE"
            except RuntimeWriterSessionError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(hold_first_activation)
            second = pool.submit(attempt_second_activation)
            self.assertTrue(first_active.wait(5))
            release_first.set()
            self.assertEqual(SESSION_CLOSED, first.result(timeout=5))
            self.assertIn("single-use", second.result(timeout=5))

        self.assertEqual(SESSION_CLOSED, session.state)

    def test_failed_append_does_not_end_valid_session(self) -> None:
        initial, plan, policy = self.build_initial_admission(
            symbol="AAA",
            clock_offset=0,
        )
        successor = successor_plan(plan, regime_snapshot_fingerprint="d" * 64)
        orphan = admit_runtime_trigger_source(
            plan_version=successor,
            previous_plan_version=plan,
            plan_ledger=ContinuousPlanLedger(plans=(plan, successor)),
            event_cycle_policy=policy,
        )
        session = self.session()
        with session.activate():
            with self.assertRaisesRegex(
                RuntimeSourceAdmissionError,
                "orphan|out-of-order",
            ):
                session.append_source_admission(orphan)
            self.assertEqual(SESSION_ACTIVE, session.state)
            session.append_source_admission(initial)

        self.assertEqual(
            (initial,),
            RuntimeSourceAdmissionStore(
                session.source_admission_path,
                evidence_program_id=PROGRAM,
                configuration_fingerprint=CONFIGURATION,
            ).load().admissions,
        )

    def test_one_active_session_serializes_distinct_thread_appends(self) -> None:
        first, _, _ = self.build_initial_admission(symbol="AAA", clock_offset=0)
        second, _, _ = self.build_initial_admission(symbol="BBB", clock_offset=1)
        session = self.session()
        with session.activate():
            with ThreadPoolExecutor(max_workers=2) as pool:
                stored = tuple(
                    pool.map(session.append_source_admission, (first, second))
                )

        self.assertEqual({first, second}, set(stored))
        self.assertEqual(
            {first, second},
            set(
                RuntimeSourceAdmissionStore(
                    session.source_admission_path,
                    evidence_program_id=PROGRAM,
                    configuration_fingerprint=CONFIGURATION,
                ).load().admissions
            ),
        )

    def test_replacement_process_times_out_then_acquires_after_release(self) -> None:
        context = multiprocessing.get_context("spawn")
        ready_event = context.Event()
        release_event = context.Event()
        output_queue = context.Queue()
        process = context.Process(
            target=_hold_writer_session_worker,
            args=(self.topology, ready_event, release_event, output_queue),
        )
        process.start()
        self.assertTrue(ready_event.wait(10))
        contender = self.session(lease_timeout_seconds=0.1)
        try:
            with self.assertRaisesRegex(RuntimeWriterSessionError, "lease timed out"):
                with contender.activate():
                    self.fail("Replacement writer acquired an active host lease.")
        finally:
            release_event.set()
            process.join(timeout=15)

        self.assertEqual(("OK", SESSION_CLOSED), output_queue.get(timeout=5))
        self.assertEqual(0, process.exitcode)
        with contender.activate():
            self.assertEqual(SESSION_ACTIVE, contender.state)

    def test_process_exit_releases_lifetime_writer_lease(self) -> None:
        context = multiprocessing.get_context("spawn")
        ready_event = context.Event()
        process = context.Process(
            target=_exit_while_holding_writer_session_worker,
            args=(self.topology, ready_event),
        )
        process.start()
        self.assertTrue(ready_event.wait(10))
        process.join(timeout=15)

        self.assertEqual(31, process.exitcode)
        replacement = self.session(lease_timeout_seconds=1.0)
        with replacement.activate():
            self.assertEqual(SESSION_ACTIVE, replacement.state)

    def test_lease_timeout_must_be_positive_and_finite(self) -> None:
        for timeout in (0, -1, float("nan"), float("inf")):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(
                    RuntimeWriterSessionError,
                    "positive and finite",
                ):
                    self.session(lease_timeout_seconds=timeout)

    def test_module_has_no_network_provider_broker_or_service_capability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module_path = root / "momentum_hunter" / "event_runtime_writer_session.py"
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

    def test_no_existing_runtime_imports_writer_session(self) -> None:
        root = Path(__file__).resolve().parents[1] / "momentum_hunter"
        importers = []
        for path in root.rglob("*.py"):
            if path.name == "event_runtime_writer_session.py":
                continue
            if "event_runtime_writer_session" in path.read_text(encoding="utf-8"):
                importers.append(path.name)
        self.assertEqual([], importers)


if __name__ == "__main__":
    unittest.main()
