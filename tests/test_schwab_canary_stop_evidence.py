from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import tempfile
import threading
import unittest

import momentum_hunter.schwab_canary_stop_evidence as stop_module
from momentum_hunter.schwab_canary_stop_evidence import (
    CREDENTIAL_REVOKED,
    RUNTIME_STOPPED,
    CanaryCredentialRevocationObservation,
    CanaryIndependentProcessObservation,
    CanaryRuntimeStopAcknowledgement,
    CanaryStopDrillPolicy,
    CanaryStopEvidenceError,
    CanaryStopLatchConflict,
    CanaryStopLatchStore,
    CanaryStopRequest,
    evaluate_canary_stop_drill,
)


UTC = timezone.utc
REQUESTED_AT = datetime(2026, 7, 27, 20, 0, tzinfo=UTC)
ACKNOWLEDGED_AT = REQUESTED_AT + timedelta(seconds=2)
PROCESS_OBSERVED_AT = REQUESTED_AT + timedelta(seconds=3)
REVOKED_AT = REQUESTED_AT + timedelta(seconds=4)
EVALUATED_AT = REQUESTED_AT + timedelta(seconds=5)
ACCOUNT_COMMITMENT = "a" * 64


class CanaryStopEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = CanaryStopRequest(
            latch_id="canary-stop-001",
            controller_id="external-stop-controller",
            account_binding_commitment=ACCOUNT_COMMITMENT,
            requested_at=REQUESTED_AT.isoformat(),
            reason_code="OPERATOR_DRILL",
        )
        self.acknowledgement = CanaryRuntimeStopAcknowledgement(
            latch_sha256=self.request.record_sha256,
            runtime_instance_id="runtime-instance-001",
            account_binding_commitment=ACCOUNT_COMMITMENT,
            acknowledged_at=ACKNOWLEDGED_AT.isoformat(),
            state=RUNTIME_STOPPED,
            execution_disabled=True,
            outstanding_command_count=0,
        )
        self.process_observation = CanaryIndependentProcessObservation(
            observer_id="external-process-observer",
            source="WINDOWS_PROCESS_OBSERVER_V1",
            runtime_instance_id="runtime-instance-001",
            observed_at=PROCESS_OBSERVED_AT.isoformat(),
            process_running=False,
        )
        self.revocation = CanaryCredentialRevocationObservation(
            source="PROVIDER_REVOCATION_PROOF_V1",
            account_binding_commitment=ACCOUNT_COMMITMENT,
            observed_at=REVOKED_AT.isoformat(),
            credential_state=CREDENTIAL_REVOKED,
        )
        self.policy = CanaryStopDrillPolicy(
            expected_controller_id="external-stop-controller",
            expected_process_observer_id="external-process-observer",
            expected_process_source="WINDOWS_PROCESS_OBSERVER_V1",
            expected_revocation_source="PROVIDER_REVOCATION_PROOF_V1",
            max_evidence_age_seconds=30,
            max_shutdown_latency_seconds=10,
            max_revocation_latency_seconds=15,
        )

    def test_complete_independent_stop_drill_passes_without_authority(self) -> None:
        result = self.evaluate()

        self.assertTrue(result.passed)
        self.assertEqual("INDEPENDENT_STOP_DRILL_PROVEN", result.conclusion)
        self.assertFalse(result.to_dict()["executionPermit"])
        self.assertFalse(result.to_dict()["latchClearSupported"])
        self.assertFalse(result.to_dict()["credentialMutationPerformed"])
        self.assertFalse(result.to_dict()["processMutationPerformed"])
        self.assertEqual("UNAVAILABLE", result.to_dict()["orderTransmission"])

    def test_missing_each_required_evidence_item_blocks(self) -> None:
        cases = (
            ("STOP_REQUEST_MISSING", {"stop_request": None}),
            (
                "RUNTIME_ACKNOWLEDGEMENT_MISSING",
                {"runtime_acknowledgement": None},
            ),
            (
                "PROCESS_OBSERVATION_MISSING",
                {"process_observation": None},
            ),
            (
                "REVOCATION_OBSERVATION_MISSING",
                {"revocation_observation": None},
            ),
        )
        for code, changes in cases:
            with self.subTest(code=code):
                result = self.evaluate(**changes)
                self.assertFalse(result.passed)
                self.assertIn(code, finding_codes(result))

    def test_runtime_must_disable_execution_stop_and_drain_commands(self) -> None:
        acknowledgement = replace(
            self.acknowledgement,
            state="RUNNING",
            execution_disabled=False,
            outstanding_command_count=1,
        )

        result = self.evaluate(runtime_acknowledgement=acknowledgement)

        self.assertFalse(result.passed)
        self.assertTrue(
            {
                "RUNTIME_NOT_STOPPED",
                "EXECUTION_NOT_DISABLED",
                "OUTSTANDING_COMMANDS_REMAIN",
            }.issubset(finding_codes(result))
        )

    def test_independent_observer_must_report_process_not_running(self) -> None:
        observation = replace(
            self.process_observation,
            observer_id=self.acknowledgement.runtime_instance_id,
            process_running=True,
        )
        policy = replace(
            self.policy,
            expected_process_observer_id=self.acknowledgement.runtime_instance_id,
        )

        result = self.evaluate(
            process_observation=observation,
            policy=policy,
        )

        self.assertFalse(result.passed)
        self.assertIn(
            "PROCESS_OBSERVER_NOT_INDEPENDENT",
            finding_codes(result),
        )
        self.assertIn("PROCESS_STILL_RUNNING", finding_codes(result))

    def test_runtime_cannot_be_its_own_stop_controller(self) -> None:
        request = replace(
            self.request,
            controller_id=self.acknowledgement.runtime_instance_id,
        )
        acknowledgement = replace(
            self.acknowledgement,
            latch_sha256=request.record_sha256,
        )
        policy = replace(
            self.policy,
            expected_controller_id=self.acknowledgement.runtime_instance_id,
        )

        result = self.evaluate(
            stop_request=request,
            runtime_acknowledgement=acknowledgement,
            policy=policy,
        )

        self.assertFalse(result.passed)
        self.assertIn(
            "STOP_CONTROLLER_NOT_INDEPENDENT",
            finding_codes(result),
        )

    def test_revocation_must_be_provider_observed_and_revoked(self) -> None:
        revocation = replace(
            self.revocation,
            source="LOCAL_GUESS",
            credential_state="ACTIVE",
        )

        result = self.evaluate(revocation_observation=revocation)

        self.assertFalse(result.passed)
        self.assertIn("REVOCATION_SOURCE_MISMATCH", finding_codes(result))
        self.assertIn("CREDENTIAL_NOT_REVOKED", finding_codes(result))

    def test_account_and_latch_identity_mismatches_block(self) -> None:
        acknowledgement = replace(
            self.acknowledgement,
            latch_sha256="b" * 64,
            account_binding_commitment="c" * 64,
        )
        revocation = replace(
            self.revocation,
            account_binding_commitment="d" * 64,
        )

        result = self.evaluate(
            runtime_acknowledgement=acknowledgement,
            revocation_observation=revocation,
        )

        self.assertFalse(result.passed)
        self.assertTrue(
            {
                "RUNTIME_LATCH_MISMATCH",
                "RUNTIME_ACCOUNT_MISMATCH",
                "REVOCATION_ACCOUNT_MISMATCH",
            }.issubset(finding_codes(result))
        )

    def test_process_observation_must_match_runtime_and_expected_source(
        self,
    ) -> None:
        observation = replace(
            self.process_observation,
            runtime_instance_id="different-runtime",
            observer_id="wrong-observer",
            source="WRONG_SOURCE",
        )

        result = self.evaluate(process_observation=observation)

        self.assertFalse(result.passed)
        self.assertTrue(
            {
                "PROCESS_OBSERVER_MISMATCH",
                "PROCESS_SOURCE_MISMATCH",
                "PROCESS_RUNTIME_MISMATCH",
            }.issubset(finding_codes(result))
        )

    def test_stale_future_reversed_and_slow_evidence_blocks(self) -> None:
        stale = self.evaluate(
            process_observation=replace(
                self.process_observation,
                observed_at=(
                    EVALUATED_AT - timedelta(seconds=31)
                ).isoformat(),
            )
        )
        future = self.evaluate(
            revocation_observation=replace(
                self.revocation,
                observed_at=(
                    EVALUATED_AT + timedelta(seconds=3)
                ).isoformat(),
            )
        )
        reversed_ack = self.evaluate(
            runtime_acknowledgement=replace(
                self.acknowledgement,
                acknowledged_at=(
                    REQUESTED_AT - timedelta(seconds=3)
                ).isoformat(),
            )
        )
        slow = self.evaluate(
            runtime_acknowledgement=replace(
                self.acknowledgement,
                acknowledged_at=(
                    REQUESTED_AT + timedelta(seconds=11)
                ).isoformat(),
            )
        )

        self.assertIn("PROCESS_OBSERVATION_STALE", finding_codes(stale))
        self.assertIn(
            "REVOCATION_OBSERVATION_FROM_FUTURE",
            finding_codes(future),
        )
        self.assertIn("RUNTIME_ACK_BEFORE_REQUEST", finding_codes(reversed_ack))
        self.assertIn("RUNTIME_ACK_TOO_SLOW", finding_codes(slow))

    def test_stop_latch_is_write_once_and_exact_duplicate_is_idempotent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary-stop.json"
            store = CanaryStopLatchStore(path)

            first = store.engage(self.request)
            original = path.read_bytes()
            second = store.engage(self.request)

            self.assertEqual(first, second)
            self.assertEqual(original, path.read_bytes())
            self.assertEqual(self.request, store.load())

    def test_conflicting_stop_latch_is_preserved_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary-stop.json"
            store = CanaryStopLatchStore(path)
            store.engage(self.request)
            original = path.read_bytes()
            conflict = replace(self.request, reason_code="DIFFERENT_REASON")

            with self.assertRaises(CanaryStopLatchConflict):
                store.engage(conflict)

            self.assertEqual(original, path.read_bytes())

    def test_tampered_latch_fails_without_repair_or_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary-stop.json"
            store = CanaryStopLatchStore(path)
            store.engage(self.request)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["reasonCode"] = "TAMPERED"
            path.write_text(json.dumps(payload), encoding="utf-8")
            tampered = path.read_bytes()

            with self.assertRaisesRegex(
                CanaryStopEvidenceError,
                "hash does not match",
            ):
                store.load()
            with self.assertRaises(CanaryStopLatchConflict):
                store.engage(self.request)

            self.assertTrue(path.exists())
            self.assertEqual(tampered, path.read_bytes())

    def test_concurrent_engage_never_overwrites_the_latch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "canary-stop.json"
            barrier = threading.Barrier(2)
            outcomes: list[str] = []

            def engage(request: CanaryStopRequest) -> None:
                barrier.wait()
                try:
                    CanaryStopLatchStore(path).engage(request)
                except CanaryStopEvidenceError:
                    outcomes.append("BLOCK")
                else:
                    outcomes.append("PERSISTED")

            competing = replace(self.request, reason_code="COMPETING_STOP")
            threads = (
                threading.Thread(target=engage, args=(self.request,)),
                threading.Thread(target=engage, args=(competing,)),
            )
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)

            self.assertEqual(2, len(outcomes))
            self.assertIn("PERSISTED", outcomes)
            persisted = CanaryStopLatchStore(path).load()
            self.assertIn(persisted, (self.request, competing))

    def test_repr_and_result_do_not_expose_full_account_commitment(self) -> None:
        rendered = json.dumps(self.evaluate().to_dict())

        self.assertNotIn(ACCOUNT_COMMITMENT, repr(self.request))
        self.assertNotIn(ACCOUNT_COMMITMENT, repr(self.acknowledgement))
        self.assertNotIn(ACCOUNT_COMMITMENT, repr(self.revocation))
        self.assertNotIn(ACCOUNT_COMMITMENT, rendered)

    def test_module_has_no_process_kill_revocation_network_or_order_capability(
        self,
    ) -> None:
        source = inspect.getsource(stop_module)
        tree = ast.parse(source)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        functions = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        self.assertFalse(
            imports
            & {
                "requests",
                "httpx",
                "urllib",
                "socket",
                "subprocess",
                "psutil",
                "signal",
                "schwab_onboarding",
                "schwab_setup",
            }
        )
        forbidden = {
            "kill",
            "terminate",
            "unlink",
            "remove",
            "revoke",
            "clear",
            "enable",
            "preview_order",
            "submit_order",
            "replace_order",
            "cancel_order",
            "transmit_order",
        }
        self.assertFalse(functions & forbidden)
        self.assertFalse(calls & forbidden)

    def evaluate(
        self,
        *,
        stop_request: CanaryStopRequest | None | object = ...,
        runtime_acknowledgement: (
            CanaryRuntimeStopAcknowledgement | None | object
        ) = ...,
        process_observation: (
            CanaryIndependentProcessObservation | None | object
        ) = ...,
        revocation_observation: (
            CanaryCredentialRevocationObservation | None | object
        ) = ...,
        policy: CanaryStopDrillPolicy | None = None,
    ):
        return evaluate_canary_stop_drill(
            stop_request=(
                self.request if stop_request is ... else stop_request
            ),
            runtime_acknowledgement=(
                self.acknowledgement
                if runtime_acknowledgement is ...
                else runtime_acknowledgement
            ),
            process_observation=(
                self.process_observation
                if process_observation is ...
                else process_observation
            ),
            revocation_observation=(
                self.revocation
                if revocation_observation is ...
                else revocation_observation
            ),
            evaluated_at=EVALUATED_AT,
            policy=policy or self.policy,
        )


def finding_codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


if __name__ == "__main__":
    unittest.main()
