from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
from pathlib import Path
import tempfile
import unittest

import momentum_hunter.schwab_canary_preflight as preflight_module
from momentum_hunter.schwab_canary_evidence import CanaryPositionEvidenceStore
from momentum_hunter.schwab_canary_funding import (
    RESTRICTIONS_CLEAR,
    RESTRICTIONS_UNAVAILABLE,
    CanaryFundingFinding,
    CanaryFundingResult,
)
from momentum_hunter.schwab_canary_order_reconciliation import (
    CanaryOrderReconciliationResult,
)
from momentum_hunter.schwab_canary_positions import (
    PRE_CANARY,
    CanaryIntent,
    CanaryPositionInvariantResult,
)
from momentum_hunter.schwab_canary_preflight import (
    PREFLIGHT_BLOCKED_CONCLUSION,
    PREFLIGHT_READY_CONCLUSION,
    CanaryPreflightError,
    CanaryPreflightPolicy,
    evaluate_canary_preflight,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CREDENTIAL_REVOKED,
    CanaryStopDrillResult,
)
from momentum_hunter.schwab_readonly import SchwabAccountBinding


UTC = timezone.utc
POSITION_AT = datetime(2026, 7, 27, 15, 0, tzinfo=UTC)
FUNDING_AT = POSITION_AT + timedelta(seconds=2)
ORDER_AT = POSITION_AT + timedelta(seconds=3)
STOP_AT = POSITION_AT + timedelta(seconds=4)
PREFLIGHT_AT = POSITION_AT + timedelta(seconds=5)
ACCOUNT_ENDING = "9001"
ACCOUNT_TYPE = "INDIVIDUAL_CASH"
ACCOUNT_HASH = "synthetic-canary-account-hash"
INTENT_ID = "canary-intent-test-001"
SEQUENCE_ID = "canary-sequence-test-001"
REQUIREMENT_ID = "canary-funding-test-001"
COMMAND_ID = "canary-order-test-001"
STOP_LATCH_SHA256 = "a" * 64


class CanaryPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.evidence_path = (
            Path(self.temporary_directory.name) / "canary-position-evidence.json"
        )
        self.binding = SchwabAccountBinding(
            account_hash=ACCOUNT_HASH,
            account_number_last_four=ACCOUNT_ENDING,
            account_type=ACCOUNT_TYPE,
        )
        self.intent = CanaryIntent(
            intent_id=INTENT_ID,
            symbol="TEST",
            quantity=1.0,
        )
        self.store = CanaryPositionEvidenceStore(
            path=self.evidence_path,
            sequence_id=SEQUENCE_ID,
            binding=self.binding,
            intent=self.intent,
        )
        self.position_result = CanaryPositionInvariantResult(
            phase=PRE_CANARY,
            status="PASS",
            evaluated_at=POSITION_AT.isoformat(),
            request_started_at=(POSITION_AT - timedelta(seconds=2)).isoformat(),
            observed_at=(POSITION_AT - timedelta(seconds=1)).isoformat(),
            collection_duration_seconds=1.0,
            account_ending=ACCOUNT_ENDING,
            account_type=ACCOUNT_TYPE,
            canary_intent_id=INTENT_ID,
            canary_symbol="TEST",
            expected_quantity=1.0,
            observed_canary_quantity=0.0,
            observed_position_count=0,
            findings=(),
        )
        self.store.record(
            self.position_result,
            recorded_at=POSITION_AT + timedelta(seconds=1),
        )
        self.funding_result = CanaryFundingResult(
            status="PASS",
            evaluated_at=FUNDING_AT.isoformat(),
            request_started_at=(FUNDING_AT - timedelta(seconds=2)).isoformat(),
            observed_at=(FUNDING_AT - timedelta(seconds=1)).isoformat(),
            balance_as_of=(FUNDING_AT - timedelta(seconds=1)).isoformat(),
            source="SYNTHETIC_SETTLED_CASH_AND_RESTRICTIONS_V1",
            account_ending=ACCOUNT_ENDING,
            account_type=ACCOUNT_TYPE,
            requirement_id=REQUIREMENT_ID,
            maximum_debit=10.0,
            minimum_cash_reserve=5.0,
            settled_cash_available=True,
            settled_cash_sufficient=True,
            restriction_state=RESTRICTIONS_CLEAR,
            restriction_codes=(),
            findings=(),
        )
        self.order_result = CanaryOrderReconciliationResult(
            status="BLOCK",
            conclusion="NO_PRIOR_SUBMISSION_EVIDENCE",
            command_id=COMMAND_ID,
            sequence_id=SEQUENCE_ID,
            evaluated_at=ORDER_AT.isoformat(),
            attempt_recorded=False,
            exact_match_count=0,
            provider_order_id=None,
            broker_status=None,
            findings=(),
        )
        self.stop_result = CanaryStopDrillResult(
            status="PASS",
            conclusion="INDEPENDENT_STOP_DRILL_PROVEN",
            evaluated_at=STOP_AT.isoformat(),
            latch_id="canary-stop-test-001",
            latch_sha256=STOP_LATCH_SHA256,
            runtime_instance_id="runtime-test-001",
            process_running=False,
            credential_state=CREDENTIAL_REVOKED,
            findings=(),
        )
        self.policy = CanaryPreflightPolicy(
            expected_account_ending=ACCOUNT_ENDING,
            expected_account_type=ACCOUNT_TYPE,
            expected_canary_intent_id=INTENT_ID,
            expected_sequence_id=SEQUENCE_ID,
            expected_funding_requirement_id=REQUIREMENT_ID,
            expected_order_command_id=COMMAND_ID,
            expected_stop_latch_sha256=STOP_LATCH_SHA256,
            max_evidence_age_seconds=30,
            max_future_skew_seconds=2,
        )

    def test_complete_preflight_requires_manual_decision_without_authority(self) -> None:
        result = self.evaluate()
        payload = result.to_dict()

        self.assertTrue(result.ready_for_manual_decision)
        self.assertEqual(PREFLIGHT_READY_CONCLUSION, result.conclusion)
        self.assertEqual(
            {
                "positionInvariant": "PASS",
                "positionEvidenceChain": "PASS",
                "fundingGate": "PASS",
                "orderReconciliation": "PASS",
                "independentStopDrill": "PASS",
            },
            payload["components"],
        )
        self.assertTrue(payload["manualDecisionRequired"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["realOrderApproval"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def test_evaluation_is_read_only_and_redacts_account_identity(self) -> None:
        before = self.evidence_path.read_bytes()

        payload = self.evaluate().to_dict()

        self.assertEqual(before, self.evidence_path.read_bytes())
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(ACCOUNT_HASH, serialized)
        self.assertNotIn(self.store.binding_commitment, serialized)

    def test_missing_or_corrupt_evidence_chain_blocks(self) -> None:
        self.evidence_path.unlink()
        missing = self.evaluate()
        self.assertIn("POSITION_EVIDENCE_INVALID", finding_codes(missing))

        self.evidence_path.write_text('{"not": "a chain"}\n', encoding="ascii")
        corrupt = self.evaluate()
        self.assertIn("POSITION_EVIDENCE_INVALID", finding_codes(corrupt))

    def test_position_phase_identity_or_result_mismatch_blocks(self) -> None:
        cases = (
            (
                replace(self.position_result, phase="CANARY_ACTIVE"),
                "POSITION_PHASE_MISMATCH",
            ),
            (
                replace(self.position_result, account_ending="9002"),
                "POSITION_ACCOUNT_ENDING_MISMATCH",
            ),
            (
                replace(self.position_result, canary_intent_id="other-intent"),
                "POSITION_INTENT_MISMATCH",
            ),
            (
                replace(self.position_result, observed_position_count=1),
                "CHAIN_RESULT_MISMATCH",
            ),
        )
        for position_result, code in cases:
            with self.subTest(code=code):
                result = self.evaluate(position_result=position_result)
                self.assertFalse(result.ready_for_manual_decision)
                self.assertIn(code, finding_codes(result))

    def test_funding_must_prove_settled_cash_and_clear_restrictions(self) -> None:
        unavailable = replace(
            self.funding_result,
            status="BLOCK",
            settled_cash_available=False,
            settled_cash_sufficient=None,
            restriction_state=RESTRICTIONS_UNAVAILABLE,
            findings=(
                CanaryFundingFinding(
                    code="SETTLED_CASH_UNAVAILABLE",
                    message="Synthetic current-contract limitation.",
                ),
            ),
        )

        result = self.evaluate(funding_result=unavailable)

        self.assertFalse(result.ready_for_manual_decision)
        self.assertIn("FUNDING_GATE_NOT_PROVEN", finding_codes(result))
        self.assertIn("SETTLED_CASH_NOT_PROVEN", finding_codes(result))
        self.assertIn("ACCOUNT_RESTRICTIONS_NOT_CLEAR", finding_codes(result))

    def test_every_cross_contract_identity_must_match(self) -> None:
        cases = (
            (
                {"funding_result": replace(self.funding_result, account_type="MARGIN")},
                "FUNDING_ACCOUNT_TYPE_MISMATCH",
            ),
            (
                {
                    "funding_result": replace(
                        self.funding_result,
                        requirement_id="other-requirement",
                    )
                },
                "FUNDING_REQUIREMENT_MISMATCH",
            ),
            (
                {"order_result": replace(self.order_result, command_id="other-command")},
                "ORDER_COMMAND_MISMATCH",
            ),
            (
                {"order_result": replace(self.order_result, sequence_id="other-sequence")},
                "ORDER_SEQUENCE_MISMATCH",
            ),
            (
                {
                    "stop_result": replace(
                        self.stop_result,
                        latch_sha256="b" * 64,
                    )
                },
                "STOP_LATCH_MISMATCH",
            ),
        )
        for changes, code in cases:
            with self.subTest(code=code):
                result = self.evaluate(**changes)
                self.assertIn(code, finding_codes(result))

    def test_order_state_must_be_no_attempt_and_no_match(self) -> None:
        cases = (
            replace(
                self.order_result,
                attempt_recorded=True,
                conclusion="AMBIGUOUS_SUBMISSION_DO_NOT_RETRY",
            ),
            replace(
                self.order_result,
                exact_match_count=2,
                conclusion="DUPLICATE_ORDER_LOCKOUT",
            ),
            replace(
                self.order_result,
                provider_order_id="provider-order-test",
                broker_status="WORKING",
                conclusion="UNEXPECTED_ORDER_WITHOUT_ATTEMPT",
            ),
            replace(
                self.order_result,
                status="PASS",
                conclusion="RESUME_EXISTING_ORDER",
                attempt_recorded=True,
                exact_match_count=1,
                provider_order_id="provider-order-test",
                broker_status="WORKING",
            ),
        )
        for order_result in cases:
            with self.subTest(conclusion=order_result.conclusion):
                result = self.evaluate(order_result=order_result)
                self.assertIn("ORDER_PREFLIGHT_STATE_INVALID", finding_codes(result))

    def test_stop_drill_must_prove_external_stop_and_revocation(self) -> None:
        cases = (
            replace(
                self.stop_result,
                status="BLOCK",
                conclusion="INDEPENDENT_STOP_DRILL_BLOCKED",
            ),
            replace(self.stop_result, process_running=True),
            replace(self.stop_result, credential_state="ACTIVE"),
        )
        expected_codes = (
            "STOP_DRILL_NOT_PROVEN",
            "STOP_PROCESS_STATE_INVALID",
            "STOP_CREDENTIAL_STATE_INVALID",
        )
        for stop_result, code in zip(cases, expected_codes):
            with self.subTest(code=code):
                result = self.evaluate(stop_result=stop_result)
                self.assertIn(code, finding_codes(result))

    def test_stale_and_future_component_evidence_blocks(self) -> None:
        stale = (PREFLIGHT_AT - timedelta(seconds=31)).isoformat()
        future = (PREFLIGHT_AT + timedelta(seconds=3)).isoformat()
        cases = (
            (
                {"funding_result": replace(self.funding_result, evaluated_at=stale)},
                "fundingGate",
                "EVIDENCE_STALE",
            ),
            (
                {"order_result": replace(self.order_result, evaluated_at=future)},
                "orderReconciliation",
                "EVIDENCE_FROM_FUTURE",
            ),
            (
                {"stop_result": replace(self.stop_result, evaluated_at=stale)},
                "independentStopDrill",
                "EVIDENCE_STALE",
            ),
        )
        for changes, component, code in cases:
            with self.subTest(component=component, code=code):
                result = self.evaluate(**changes)
                self.assertIn((component, code), finding_pairs(result))

    def test_stale_chain_blocks_even_when_component_result_is_fresh(self) -> None:
        result = self.evaluate(
            evaluated_at=POSITION_AT + timedelta(seconds=32),
            funding_result=replace(
                self.funding_result,
                evaluated_at=(POSITION_AT + timedelta(seconds=31)).isoformat(),
            ),
            order_result=replace(
                self.order_result,
                evaluated_at=(POSITION_AT + timedelta(seconds=31)).isoformat(),
            ),
            stop_result=replace(
                self.stop_result,
                evaluated_at=(POSITION_AT + timedelta(seconds=31)).isoformat(),
            ),
        )

        self.assertIn(
            ("positionEvidenceChain", "EVIDENCE_STALE"),
            finding_pairs(result),
        )

    def test_policy_rejects_missing_or_malformed_ids(self) -> None:
        for changes in (
            {"expected_canary_intent_id": ""},
            {"expected_order_command_id": "bad command"},
            {"expected_account_ending": "12345"},
            {"expected_stop_latch_sha256": "not-a-sha"},
            {"max_evidence_age_seconds": 0},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(CanaryPreflightError):
                    replace(self.policy, **changes)

    def test_source_has_no_network_process_credential_or_order_capability(self) -> None:
        source = inspect.getsource(preflight_module)
        tree = ast.parse(source)
        imported_roots = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        called_names = {
            (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else ""
            )
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
        }

        self.assertTrue(
            imported_roots.isdisjoint(
                {"requests", "httpx", "socket", "subprocess", "psutil", "signal"}
            )
        )
        self.assertTrue(
            called_names.isdisjoint(
                {
                    "submit_order",
                    "replace_order",
                    "cancel_order",
                    "preview_order",
                    "transmit_order",
                    "kill",
                    "terminate",
                    "revoke",
                    "unlink",
                    "remove",
                }
            )
        )
        self.assertNotIn("schwab_setup", source)
        self.assertNotIn("schwab_onboarding", source)

    def test_blocked_result_is_explicit_and_never_becomes_authority(self) -> None:
        blocked = self.evaluate(
            funding_result=replace(
                self.funding_result,
                status="BLOCK",
                settled_cash_available=False,
                settled_cash_sufficient=None,
                restriction_state=RESTRICTIONS_UNAVAILABLE,
                findings=(
                    CanaryFundingFinding(
                        code="CURRENT_CONTRACT_INCOMPLETE",
                        message="Synthetic evidence remains unavailable.",
                    ),
                ),
            ),
            order_result=replace(
                self.order_result,
                conclusion="BROKER_EVIDENCE_INCOMPLETE",
            ),
            stop_result=replace(
                self.stop_result,
                status="BLOCK",
                conclusion="INDEPENDENT_STOP_DRILL_BLOCKED",
                process_running=None,
                credential_state=None,
            ),
        )
        payload = blocked.to_dict()

        self.assertEqual(PREFLIGHT_BLOCKED_CONCLUSION, blocked.conclusion)
        self.assertFalse(blocked.ready_for_manual_decision)
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["realOrderApproval"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def evaluate(self, **changes: object):
        arguments = {
            "evidence_store": self.store,
            "position_result": self.position_result,
            "funding_result": self.funding_result,
            "order_result": self.order_result,
            "stop_result": self.stop_result,
            "evaluated_at": PREFLIGHT_AT,
            "policy": self.policy,
        }
        arguments.update(changes)
        return evaluate_canary_preflight(**arguments)


def finding_codes(result: object) -> set[str]:
    return {finding.code for finding in result.findings}


def finding_pairs(result: object) -> set[tuple[str, str]]:
    return {(finding.component, finding.code) for finding in result.findings}


if __name__ == "__main__":
    unittest.main()
