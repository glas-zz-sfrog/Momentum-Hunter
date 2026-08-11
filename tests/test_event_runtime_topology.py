from __future__ import annotations

import ast
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.event_runtime_topology import (
    APPEND,
    CANDIDATE_LIFECYCLE_LEDGER,
    CONTINUOUS_PLAN_LEDGER,
    DORMANT_UNINSTALLED,
    EVENT_DECISION_CYCLE_LEDGER,
    OFFLINE_REVIEW,
    ORDER_TRANSMISSION_UNAVAILABLE,
    PYTHON_ENGINE_HOST,
    READ,
    REQUIRED_ARTIFACTS,
    RUNTIME_SOURCE_ADMISSION_LEDGER,
    WINDOWS_AUTOMATION_SERVICE,
    WPF_WORKSTATION,
    EventRuntimeTopologyError,
    artifact_path,
    authorize_runtime_artifact_access,
    build_event_runtime_topology,
    build_runtime_writer_claim,
    validate_event_runtime_topology,
    validate_runtime_writer_claim,
)


CONFIGURATION = "a" * 64
RUNTIME_BUILD = "b" * 64
PROGRAM = "continuous-engineering-v1"
NOW = datetime(2026, 8, 11, 8, 30, tzinfo=timezone.utc)


class EventRuntimeTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "runtime-state"
        self.topology = build_event_runtime_topology(
            root_path=self.root,
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
            runtime_build_hash=RUNTIME_BUILD,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def claim(self, **changes):
        values = {
            "process_role": PYTHON_ENGINE_HOST,
            "host_instance_id": "engine-host-instance-1",
            "process_id": 1234,
            "runtime_build_hash": RUNTIME_BUILD,
            "configuration_fingerprint": CONFIGURATION,
            "claimed_at": NOW,
        }
        values.update(changes)
        return build_runtime_writer_claim(self.topology, **values)

    def test_topology_is_deterministic_dormant_and_nontransmitting(self) -> None:
        duplicate = build_event_runtime_topology(
            root_path=self.root,
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
            runtime_build_hash=RUNTIME_BUILD,
        )
        self.assertEqual(self.topology, duplicate)
        self.assertEqual(DORMANT_UNINSTALLED, self.topology.activation_state)
        self.assertEqual(
            ORDER_TRANSMISSION_UNAVAILABLE, self.topology.order_transmission
        )
        self.assertEqual(PYTHON_ENGINE_HOST, self.topology.writer_role)
        self.assertEqual(
            WINDOWS_AUTOMATION_SERVICE, self.topology.supervisor_role
        )

    def test_artifact_layout_is_complete_distinct_and_configuration_scoped(self) -> None:
        self.assertEqual(
            REQUIRED_ARTIFACTS,
            {item.artifact_name for item in self.topology.artifacts},
        )
        paths = {
            artifact_path(self.topology, name)
            for name in REQUIRED_ARTIFACTS
        }
        self.assertEqual(4, len(paths))
        for path in paths:
            self.assertTrue(path.is_relative_to(self.root / self.topology.namespace))
            self.assertEqual(".json", path.suffix)
        self.assertEqual(
            self.root
            / self.topology.namespace
            / "evidence"
            / "runtime-source-admissions.json",
            artifact_path(self.topology, RUNTIME_SOURCE_ADMISSION_LEDGER),
        )

    def test_building_and_validating_topology_does_not_create_source_paths(self) -> None:
        self.assertFalse(self.root.exists())
        validate_event_runtime_topology(self.topology)
        for name in REQUIRED_ARTIFACTS:
            artifact_path(self.topology, name)
        self.assertFalse(self.root.exists())

    def test_relative_or_forbidden_roots_fail_closed(self) -> None:
        with self.assertRaisesRegex(EventRuntimeTopologyError, "absolute"):
            build_event_runtime_topology(
                root_path=Path("relative-state"),
                evidence_program_id=PROGRAM,
                configuration_fingerprint=CONFIGURATION,
                runtime_build_hash=RUNTIME_BUILD,
            )
        for root in (
            self.root / ".git" / "runtime",
            self.root / ".venv" / "runtime",
            self.root / "tests" / "runtime",
            self.root / "momentum_hunter" / "runtime",
        ):
            with self.subTest(root=root):
                with self.assertRaisesRegex(EventRuntimeTopologyError, "source"):
                    build_event_runtime_topology(
                        root_path=root,
                        evidence_program_id=PROGRAM,
                        configuration_fingerprint=CONFIGURATION,
                        runtime_build_hash=RUNTIME_BUILD,
                    )
        with self.assertRaisesRegex(EventRuntimeTopologyError, "parent traversal"):
            build_event_runtime_topology(
                root_path=self.root / ".." / "escaped-runtime",
                evidence_program_id=PROGRAM,
                configuration_fingerprint=CONFIGURATION,
                runtime_build_hash=RUNTIME_BUILD,
            )

    def test_configuration_changes_use_a_distinct_namespace_and_identity(self) -> None:
        changed = build_event_runtime_topology(
            root_path=self.root,
            evidence_program_id=PROGRAM,
            configuration_fingerprint="c" * 64,
            runtime_build_hash=RUNTIME_BUILD,
        )
        self.assertNotEqual(self.topology.namespace, changed.namespace)
        self.assertNotEqual(self.topology.topology_id, changed.topology_id)
        self.assertTrue(
            set(
                artifact_path(self.topology, name) for name in REQUIRED_ARTIFACTS
            ).isdisjoint(
                artifact_path(changed, name) for name in REQUIRED_ARTIFACTS
            )
        )

    def test_evidence_programs_never_share_a_namespace(self) -> None:
        official = build_event_runtime_topology(
            root_path=self.root,
            evidence_program_id="official-continuous-shadow-v1",
            configuration_fingerprint=CONFIGURATION,
            runtime_build_hash=RUNTIME_BUILD,
        )
        self.assertNotEqual(self.topology.namespace, official.namespace)
        self.assertNotEqual(self.topology.topology_id, official.topology_id)
        self.assertTrue(
            {
                artifact_path(self.topology, name) for name in REQUIRED_ARTIFACTS
            }.isdisjoint(
                artifact_path(official, name) for name in REQUIRED_ARTIFACTS
            )
        )

    def test_runtime_build_change_preserves_namespace_but_rotates_authority(self) -> None:
        changed = build_event_runtime_topology(
            root_path=self.root,
            evidence_program_id=PROGRAM,
            configuration_fingerprint=CONFIGURATION,
            runtime_build_hash="c" * 64,
        )
        self.assertEqual(self.topology.namespace, changed.namespace)
        self.assertNotEqual(self.topology.topology_id, changed.topology_id)
        with self.assertRaisesRegex(EventRuntimeTopologyError, "topology"):
            validate_runtime_writer_claim(self.claim(), changed)

    def test_invalid_or_noncanonical_evidence_program_fails_closed(self) -> None:
        for program in ("", "bad program", "../escape", "x" * 65):
            with self.subTest(program=program):
                with self.assertRaisesRegex(EventRuntimeTopologyError, "program"):
                    build_event_runtime_topology(
                        root_path=self.root,
                        evidence_program_id=program,
                        configuration_fingerprint=CONFIGURATION,
                        runtime_build_hash=RUNTIME_BUILD,
                    )
        with self.assertRaisesRegex(EventRuntimeTopologyError, "canonical"):
            validate_event_runtime_topology(
                replace(self.topology, evidence_program_id=PROGRAM.upper())
            )

    def test_topology_tampering_fails_closed(self) -> None:
        cases = (
            replace(self.topology, writer_role=WINDOWS_AUTOMATION_SERVICE),
            replace(self.topology, supervisor_role=PYTHON_ENGINE_HOST),
            replace(self.topology, activation_state="ACTIVE"),
            replace(self.topology, observation_mode="HISTORICAL_REPLAY"),
            replace(self.topology, order_transmission="AVAILABLE"),
            replace(self.topology, namespace="wrong"),
            replace(self.topology, root_path=f"{self.root}\\"),
            replace(self.topology, configuration_fingerprint="A" * 64),
            replace(self.topology, runtime_build_hash="B" * 64),
            replace(self.topology, fingerprint="0" * 64),
        )
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(EventRuntimeTopologyError):
                    validate_event_runtime_topology(case)

    def test_artifact_path_ownership_collision_and_escape_fail_closed(self) -> None:
        first = self.topology.artifacts[0]
        second = self.topology.artifacts[1]
        mutations = (
            replace(
                self.topology,
                artifacts=(
                    replace(first, writer_role=WINDOWS_AUTOMATION_SERVICE),
                    *self.topology.artifacts[1:],
                ),
            ),
            replace(
                self.topology,
                artifacts=(first, replace(second, relative_path=first.relative_path), *self.topology.artifacts[2:]),
            ),
            replace(
                self.topology,
                artifacts=(replace(first, relative_path="../escape.json"), *self.topology.artifacts[1:]),
            ),
            replace(self.topology, artifacts=self.topology.artifacts[:-1]),
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                with self.assertRaises(EventRuntimeTopologyError):
                    validate_event_runtime_topology(mutation)

    def test_engine_host_writer_claim_is_deterministic_and_exact(self) -> None:
        first = self.claim()
        second = self.claim()
        self.assertEqual(first, second)
        validate_runtime_writer_claim(first, self.topology)
        self.assertEqual(self.topology.topology_id, first.topology_id)
        self.assertEqual(PYTHON_ENGINE_HOST, first.process_role)

    def test_service_wpf_and_offline_review_cannot_claim_write_authority(self) -> None:
        for role in (
            WINDOWS_AUTOMATION_SERVICE,
            WPF_WORKSTATION,
            OFFLINE_REVIEW,
        ):
            with self.subTest(role=role):
                with self.assertRaisesRegex(EventRuntimeTopologyError, "writer role"):
                    self.claim(process_role=role)

    def test_wrong_build_configuration_pid_or_timestamp_cannot_claim(self) -> None:
        cases = (
            {"runtime_build_hash": "c" * 64},
            {"configuration_fingerprint": "d" * 64},
            {"process_id": 0},
            {"process_id": True},
            {"process_id": 1.5},
            {"process_id": "1234"},
            {"claimed_at": datetime(2026, 8, 11, 8, 30)},
            {"host_instance_id": ""},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(EventRuntimeTopologyError):
                    self.claim(**changes)

    def test_tampered_writer_claim_fails_closed(self) -> None:
        claim = self.claim()
        for changed in (
            replace(claim, process_id=9999),
            replace(claim, process_id=str(claim.process_id)),
            replace(claim, host_instance_id=f" {claim.host_instance_id}"),
            replace(claim, runtime_build_hash=RUNTIME_BUILD.upper()),
            replace(claim, claimed_at="2026-08-11T08:30:00Z"),
            replace(claim, topology_fingerprint="0" * 64),
            replace(claim, process_role=WINDOWS_AUTOMATION_SERVICE),
            replace(claim, fingerprint="0" * 64),
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(EventRuntimeTopologyError):
                    validate_runtime_writer_claim(changed, self.topology)

    def test_engine_host_append_requires_exact_writer_claim(self) -> None:
        for artifact in REQUIRED_ARTIFACTS:
            with self.subTest(artifact=artifact):
                missing = authorize_runtime_artifact_access(
                    self.topology,
                    artifact_name=artifact,
                    operation=APPEND,
                    process_role=PYTHON_ENGINE_HOST,
                )
                self.assertFalse(missing.allowed)
                self.assertEqual("WRITER_CLAIM_REQUIRED", missing.reason)
                claim = self.claim()
                allowed = authorize_runtime_artifact_access(
                    self.topology,
                    artifact_name=artifact,
                    operation=APPEND,
                    process_role=PYTHON_ENGINE_HOST,
                    writer_claim=claim,
                    current_host_instance_id=claim.host_instance_id,
                    current_process_id=claim.process_id,
                )
                self.assertTrue(allowed.allowed)
                self.assertEqual("APPEND_AUTHORIZED", allowed.reason)

    def test_nonwriter_roles_are_logically_blocked_from_append(self) -> None:
        for role in (
            WINDOWS_AUTOMATION_SERVICE,
            WPF_WORKSTATION,
            OFFLINE_REVIEW,
        ):
            decision = authorize_runtime_artifact_access(
                self.topology,
                artifact_name=EVENT_DECISION_CYCLE_LEDGER,
                operation=APPEND,
                process_role=role,
                writer_claim=self.claim(),
            )
            self.assertFalse(decision.allowed)
            self.assertEqual("SOLE_WRITER_ROLE_REQUIRED", decision.reason)

    def test_stale_or_mismatched_engine_host_claim_cannot_append(self) -> None:
        claim = self.claim()
        cases = (
            ("", 0, "CURRENT_WRITER_IDENTITY_REQUIRED"),
            (claim.host_instance_id, 0, "CURRENT_WRITER_IDENTITY_REQUIRED"),
            ("replacement-host", claim.process_id, "CURRENT_WRITER_IDENTITY_MISMATCH"),
            (claim.host_instance_id, claim.process_id + 1, "CURRENT_WRITER_IDENTITY_MISMATCH"),
        )
        for host, pid, expected in cases:
            with self.subTest(host=host, pid=pid):
                decision = authorize_runtime_artifact_access(
                    self.topology,
                    artifact_name=EVENT_DECISION_CYCLE_LEDGER,
                    operation=APPEND,
                    process_role=PYTHON_ENGINE_HOST,
                    writer_claim=claim,
                    current_host_instance_id=host,
                    current_process_id=pid,
                )
                self.assertFalse(decision.allowed)
                self.assertEqual(expected, decision.reason)

    def test_engine_host_and_offline_review_can_read_canonical_artifacts(self) -> None:
        for role in (OFFLINE_REVIEW, PYTHON_ENGINE_HOST):
            decision = authorize_runtime_artifact_access(
                self.topology,
                artifact_name=CONTINUOUS_PLAN_LEDGER,
                operation=READ,
                process_role=role,
            )
            self.assertTrue(decision.allowed)

    def test_service_and_wpf_cannot_read_canonical_artifacts_directly(self) -> None:
        for role in (WINDOWS_AUTOMATION_SERVICE, WPF_WORKSTATION):
            with self.subTest(role=role):
                decision = authorize_runtime_artifact_access(
                    self.topology,
                    artifact_name=CONTINUOUS_PLAN_LEDGER,
                    operation=READ,
                    process_role=role,
                )
                self.assertFalse(decision.allowed)
                self.assertEqual("ROLE_NOT_A_READER", decision.reason)

    def test_unknown_artifact_operation_or_role_fails_closed(self) -> None:
        cases = (
            ("UNKNOWN", READ, WPF_WORKSTATION, "UNKNOWN_ARTIFACT"),
            (CANDIDATE_LIFECYCLE_LEDGER, "DELETE", WPF_WORKSTATION, "UNKNOWN_OPERATION"),
            (CANDIDATE_LIFECYCLE_LEDGER, READ, "CODEX", "UNKNOWN_PROCESS_ROLE"),
        )
        for artifact, operation, role, reason in cases:
            decision = authorize_runtime_artifact_access(
                self.topology,
                artifact_name=artifact,
                operation=operation,
                process_role=role,
            )
            self.assertFalse(decision.allowed)
            self.assertEqual(reason, decision.reason)

    def test_invalid_writer_claim_returns_denial_without_mutation(self) -> None:
        bad_claim = replace(self.claim(), fingerprint="0" * 64)
        decision = authorize_runtime_artifact_access(
            self.topology,
            artifact_name=RUNTIME_SOURCE_ADMISSION_LEDGER,
            operation=APPEND,
            process_role=PYTHON_ENGINE_HOST,
            writer_claim=bad_claim,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual("WRITER_CLAIM_INVALID", decision.reason)
        self.assertFalse(self.root.exists())

    def test_module_has_no_network_broker_order_or_persistence_capability(self) -> None:
        module_path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "event_runtime_topology.py"
        )
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
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
                    "open",
                    "mkdir",
                    "touch",
                    "unlink",
                    "write_text",
                    "write_bytes",
                    "submit_order",
                    "cancel_order",
                    "replace_order",
                    "get_account",
                }
            )
        )

    def test_no_existing_runtime_imports_topology_contract(self) -> None:
        root = Path(__file__).resolve().parents[1] / "momentum_hunter"
        importers = []
        for path in root.rglob("*.py"):
            if path.name in {
                "event_runtime_topology.py",
                "event_runtime_writer_session.py",
                "event_runtime_evidence_chain.py",
            }:
                continue
            if "event_runtime_topology" in path.read_text(encoding="utf-8"):
                importers.append(path.name)
        self.assertEqual([], importers)


if __name__ == "__main__":
    unittest.main()
