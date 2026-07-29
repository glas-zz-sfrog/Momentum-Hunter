from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest

import momentum_hunter.schwab_canary_preflight_receipt as receipt_module
from momentum_hunter.schwab_canary_credential_remediation import (
    SECRET_ROTATED,
    CanaryCredentialRemediationObservation,
    CanaryCredentialRemediationPolicy,
    evaluate_canary_credential_remediation,
)
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
    CANARY_ACTIVE,
    PRE_CANARY,
    CanaryIntent,
    CanaryPositionInvariantResult,
)
from momentum_hunter.schwab_canary_preflight import CanaryPreflightPolicy
from momentum_hunter.schwab_canary_preflight_receipt import (
    RECEIPT_AWAITING_DECISION,
    RECEIPT_BLOCKED,
    RECEIPT_EXPIRED,
    RECEIPT_MISSING,
    CanaryPreflightReceiptConflict,
    CanaryPreflightReceiptError,
    CanaryPreflightReceiptPolicy,
    CanaryPreflightReceiptStore,
    build_canary_preflight_receipt,
    inspect_canary_preflight_receipt,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CREDENTIAL_REVOKED,
    CanaryStopDrillResult,
)
from momentum_hunter.schwab_readonly import SchwabAccountBinding


UTC = timezone.utc
POSITION_AT = datetime(2026, 7, 27, 16, 0, tzinfo=UTC)
FUNDING_AT = POSITION_AT + timedelta(seconds=2)
CREDENTIAL_AT = POSITION_AT + timedelta(seconds=3)
ORDER_AT = POSITION_AT + timedelta(seconds=4)
STOP_AT = POSITION_AT + timedelta(seconds=5)
PREFLIGHT_AT = POSITION_AT + timedelta(seconds=6)
RECORDED_AT = PREFLIGHT_AT + timedelta(seconds=1)
ACCOUNT_ENDING = "9001"
ACCOUNT_TYPE = "INDIVIDUAL_CASH"
ACCOUNT_HASH = "synthetic-preflight-receipt-account-hash"
INTENT_ID = "canary-intent-receipt-test"
SEQUENCE_ID = "canary-sequence-receipt-test"
REQUIREMENT_ID = "canary-funding-receipt-test"
COMMAND_ID = "canary-order-receipt-test"
STOP_LATCH_SHA256 = "c" * 64
CREDENTIAL_INCIDENT_ID = "SCHWAB-CLIENT-SECRET-2026-07-26"
APPLICATION_COMMITMENT_SHA256 = "d" * 64
CREDENTIAL_EVIDENCE_SHA256 = "e" * 64
CREDENTIAL_INCIDENT_AT = POSITION_AT - timedelta(days=1)


class CanaryPreflightReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        directory = Path(self.temporary_directory.name)
        self.position_path = directory / "position-evidence.json"
        self.receipt_path = directory / "preflight-receipt.json"
        binding = SchwabAccountBinding(
            account_hash=ACCOUNT_HASH,
            account_number_last_four=ACCOUNT_ENDING,
            account_type=ACCOUNT_TYPE,
        )
        intent = CanaryIntent(
            intent_id=INTENT_ID,
            symbol="TEST",
            quantity=1.0,
        )
        self.position_store = CanaryPositionEvidenceStore(
            path=self.position_path,
            sequence_id=SEQUENCE_ID,
            binding=binding,
            intent=intent,
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
        self.position_store.record(
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
        self.credential_result = evaluate_canary_credential_remediation(
            observation=CanaryCredentialRemediationObservation(
                incident_id=CREDENTIAL_INCIDENT_ID,
                application_commitment_sha256=(
                    APPLICATION_COMMITMENT_SHA256
                ),
                remediation_state=SECRET_ROTATED,
                evidence_source="SCHWAB_DEVELOPER_PORTAL",
                evidence_artifact_sha256=CREDENTIAL_EVIDENCE_SHA256,
                observed_at=(POSITION_AT - timedelta(hours=1)).isoformat(),
                old_credential_invalidated=True,
            ),
            evaluated_at=CREDENTIAL_AT,
            policy=CanaryCredentialRemediationPolicy(
                expected_incident_id=CREDENTIAL_INCIDENT_ID,
                expected_application_commitment_sha256=(
                    APPLICATION_COMMITMENT_SHA256
                ),
                expected_evidence_artifact_sha256=(
                    CREDENTIAL_EVIDENCE_SHA256
                ),
                incident_recorded_at=CREDENTIAL_INCIDENT_AT,
            ),
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
            latch_id="canary-stop-receipt-test",
            latch_sha256=STOP_LATCH_SHA256,
            runtime_instance_id="runtime-receipt-test",
            process_running=False,
            credential_state=CREDENTIAL_REVOKED,
            findings=(),
        )
        self.preflight_policy = CanaryPreflightPolicy(
            expected_account_ending=ACCOUNT_ENDING,
            expected_account_type=ACCOUNT_TYPE,
            expected_canary_intent_id=INTENT_ID,
            expected_sequence_id=SEQUENCE_ID,
            expected_funding_requirement_id=REQUIREMENT_ID,
            expected_credential_incident_id=CREDENTIAL_INCIDENT_ID,
            expected_application_commitment_sha256=(
                APPLICATION_COMMITMENT_SHA256
            ),
            expected_credential_evidence_sha256=(
                CREDENTIAL_EVIDENCE_SHA256
            ),
            expected_order_command_id=COMMAND_ID,
            expected_stop_latch_sha256=STOP_LATCH_SHA256,
            max_evidence_age_seconds=30,
        )
        self.receipt_policy = CanaryPreflightReceiptPolicy(
            decision_window_seconds=20,
            max_future_skew_seconds=2,
        )
        self.store = CanaryPreflightReceiptStore(self.receipt_path)

    def test_complete_receipt_is_write_once_and_awaits_manual_decision(self) -> None:
        receipt = self.build()

        payload = self.store.persist(receipt)
        inspection = inspect_canary_preflight_receipt(
            store=self.store,
            position_evidence_store=self.position_store,
            observed_at=RECORDED_AT + timedelta(seconds=1),
            policy=self.receipt_policy,
        )

        self.assertEqual(RECEIPT_AWAITING_DECISION, inspection.status)
        self.assertTrue(inspection.awaiting_manual_decision)
        self.assertEqual(receipt.receipt_id, payload["receiptId"])
        self.assertEqual(receipt.receipt_sha256, payload["receiptSha256"])
        self.assertTrue(payload["oneWay"])
        self.assertFalse(payload["replaceSupported"])
        self.assertFalse(payload["clearSupported"])
        self.assertTrue(payload["manualDecisionRequired"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["realOrderApproval"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        self.assertFalse(inspection.to_dict()["executionPermit"])

    def test_exact_duplicate_persistence_is_byte_idempotent(self) -> None:
        receipt = self.build()
        first = self.store.persist(receipt)
        before = self.receipt_path.read_bytes()

        second = self.store.persist(receipt)

        self.assertEqual(first, second)
        self.assertEqual(before, self.receipt_path.read_bytes())

    def test_conflicting_receipt_is_refused_without_mutation(self) -> None:
        receipt = self.build()
        self.store.persist(receipt)
        before = self.receipt_path.read_bytes()
        changed_funding = replace(
            self.funding_result,
            maximum_debit=9.0,
        )
        conflict = self.build(funding_result=changed_funding)

        with self.assertRaises(CanaryPreflightReceiptConflict):
            self.store.persist(conflict)

        self.assertEqual(before, self.receipt_path.read_bytes())

    def test_tampering_is_detected_without_repair_or_deletion(self) -> None:
        original = self.store.persist(self.build())
        original_bytes = self.receipt_path.read_bytes()
        cases = (
            ("receiptSha256", "0" * 64),
            ("evidenceSetSha256", "1" * 64),
            ("executionPermit", True),
            ("replaceSupported", True),
            ("expiresAt", (PREFLIGHT_AT + timedelta(seconds=40)).isoformat()),
            ("positionChainSha256", "2" * 64),
        )
        for key, value in cases:
            with self.subTest(key=key):
                tampered = json.loads(json.dumps(original))
                tampered[key] = value
                self.receipt_path.write_text(
                    json.dumps(tampered, sort_keys=True),
                    encoding="ascii",
                )
                with self.assertRaises(CanaryPreflightReceiptError):
                    self.store.load()
                self.assertTrue(self.receipt_path.exists())
                self.receipt_path.write_bytes(original_bytes)

    def test_nested_evidence_tampering_and_identity_drift_are_detected(self) -> None:
        original = self.store.persist(self.build())
        cases = (
            (
                ("fundingGate", "settledCashSufficient"),
                False,
            ),
            (
                ("credentialRemediation", "oldCredentialInvalidated"),
                False,
            ),
            (
                ("orderReconciliation", "attemptRecorded"),
                True,
            ),
            (
                ("independentStopDrill", "processRunning"),
                True,
            ),
            (
                ("preflight", "orderCommandId"),
                "different-command",
            ),
            (
                ("positionInvariant", "accountEnding"),
                "9002",
            ),
        )
        for path, value in cases:
            with self.subTest(path=path):
                tampered = json.loads(json.dumps(original))
                tampered["evidence"][path[0]][path[1]] = value
                unsigned = {
                    key: item
                    for key, item in tampered.items()
                    if key != "receiptSha256"
                }
                tampered["receiptSha256"] = sha256_payload(unsigned)
                self.receipt_path.write_text(
                    json.dumps(tampered, sort_keys=True),
                    encoding="ascii",
                )
                with self.assertRaises(CanaryPreflightReceiptError):
                    self.store.load()

    def test_missing_expired_and_future_observations_fail_closed(self) -> None:
        missing = inspect_canary_preflight_receipt(
            store=self.store,
            position_evidence_store=self.position_store,
            observed_at=RECORDED_AT,
            policy=self.receipt_policy,
        )
        self.assertEqual(RECEIPT_MISSING, missing.status)
        self.assertFalse(missing.awaiting_manual_decision)

        self.store.persist(self.build())
        expired = inspect_canary_preflight_receipt(
            store=self.store,
            position_evidence_store=self.position_store,
            observed_at=PREFLIGHT_AT + timedelta(seconds=21),
            policy=self.receipt_policy,
        )
        future = inspect_canary_preflight_receipt(
            store=self.store,
            position_evidence_store=self.position_store,
            observed_at=RECORDED_AT - timedelta(seconds=3),
            policy=self.receipt_policy,
        )

        self.assertEqual(RECEIPT_EXPIRED, expired.status)
        self.assertEqual(RECEIPT_BLOCKED, future.status)
        self.assertFalse(expired.to_dict()["executionPermit"])
        self.assertFalse(future.to_dict()["executionPermit"])

    def test_blocked_preflight_cannot_create_receipt(self) -> None:
        unavailable = replace(
            self.funding_result,
            status="BLOCK",
            settled_cash_available=False,
            settled_cash_sufficient=None,
            restriction_state=RESTRICTIONS_UNAVAILABLE,
            findings=(
                CanaryFundingFinding(
                    code="CURRENT_CONTRACT_INCOMPLETE",
                    message="Synthetic current-contract limitation.",
                ),
            ),
        )

        with self.assertRaises(CanaryPreflightReceiptError):
            self.build(funding_result=unavailable)

        self.assertFalse(self.receipt_path.exists())

    def test_unremediated_credential_cannot_create_receipt(self) -> None:
        unresolved = replace(
            self.credential_result,
            status="BLOCK",
            conclusion="CREDENTIAL_REMEDIATION_REQUIRED",
            old_credential_invalidated=False,
        )

        with self.assertRaises(CanaryPreflightReceiptError):
            self.build(credential_result=unresolved)

        self.assertFalse(self.receipt_path.exists())

    def test_receipt_recording_chronology_and_policy_are_bounded(self) -> None:
        with self.assertRaises(CanaryPreflightReceiptError):
            self.build(recorded_at=PREFLIGHT_AT - timedelta(milliseconds=1))
        with self.assertRaises(CanaryPreflightReceiptError):
            self.build(recorded_at=PREFLIGHT_AT + timedelta(seconds=21))
        for decision_window in (0, 301, float("inf"), float("nan")):
            with self.subTest(decision_window=decision_window):
                with self.assertRaises(CanaryPreflightReceiptError):
                    CanaryPreflightReceiptPolicy(
                        decision_window_seconds=decision_window
                    )

    def test_evidence_change_changes_receipt_identity(self) -> None:
        first = self.build()
        second = self.build(
            funding_result=replace(
                self.funding_result,
                maximum_debit=9.0,
            )
        )

        self.assertNotEqual(first.evidence_set_sha256, second.evidence_set_sha256)
        self.assertNotEqual(first.receipt_id, second.receipt_id)
        self.assertNotEqual(first.receipt_sha256, second.receipt_sha256)

    def test_build_persist_and_inspect_do_not_mutate_source_evidence(self) -> None:
        before = self.position_path.read_bytes()

        receipt = self.build()
        self.store.persist(receipt)
        inspect_canary_preflight_receipt(
            store=self.store,
            position_evidence_store=self.position_store,
            observed_at=RECORDED_AT + timedelta(seconds=1),
            policy=self.receipt_policy,
        )

        self.assertEqual(before, self.position_path.read_bytes())

    def test_receipt_excludes_account_hash_and_binding_commitment(self) -> None:
        receipt = self.build()
        payload = self.store.persist(receipt)
        serialized = json.dumps(payload, sort_keys=True)

        self.assertNotIn(ACCOUNT_HASH, serialized)
        self.assertNotIn(self.position_store.binding_commitment, serialized)
        self.assertNotIn("accountHash", serialized)
        self.assertNotIn("bindingCommitment", serialized)

    def test_external_decision_window_policy_mismatch_blocks(self) -> None:
        self.store.persist(self.build())

        inspection = inspect_canary_preflight_receipt(
            store=self.store,
            position_evidence_store=self.position_store,
            observed_at=RECORDED_AT + timedelta(seconds=1),
            policy=CanaryPreflightReceiptPolicy(
                decision_window_seconds=10,
            ),
        )

        self.assertEqual(RECEIPT_BLOCKED, inspection.status)
        self.assertEqual(
            "CANARY_PREFLIGHT_RECEIPT_POLICY_MISMATCH",
            inspection.conclusion,
        )
        self.assertFalse(inspection.to_dict()["executionPermit"])

    def test_position_chain_advance_after_receipt_blocks_inspection(self) -> None:
        self.store.persist(self.build())
        active_result = replace(
            self.position_result,
            phase=CANARY_ACTIVE,
            evaluated_at=(PREFLIGHT_AT + timedelta(seconds=2)).isoformat(),
            request_started_at=PREFLIGHT_AT.isoformat(),
            observed_at=(PREFLIGHT_AT + timedelta(seconds=1)).isoformat(),
            observed_canary_quantity=1.0,
            observed_position_count=1,
        )
        self.position_store.record(
            active_result,
            recorded_at=PREFLIGHT_AT + timedelta(seconds=3),
        )

        inspection = inspect_canary_preflight_receipt(
            store=self.store,
            position_evidence_store=self.position_store,
            observed_at=PREFLIGHT_AT + timedelta(seconds=4),
            policy=self.receipt_policy,
        )

        self.assertEqual(RECEIPT_BLOCKED, inspection.status)
        self.assertEqual(
            "CANARY_PREFLIGHT_SOURCE_EVIDENCE_CHANGED",
            inspection.conclusion,
        )
        self.assertFalse(inspection.to_dict()["executionPermit"])

    def test_missing_position_source_after_receipt_blocks_inspection(self) -> None:
        self.store.persist(self.build())
        self.position_path.unlink()

        inspection = inspect_canary_preflight_receipt(
            store=self.store,
            position_evidence_store=self.position_store,
            observed_at=RECORDED_AT + timedelta(seconds=1),
            policy=self.receipt_policy,
        )

        self.assertEqual(RECEIPT_BLOCKED, inspection.status)
        self.assertEqual(
            "CANARY_PREFLIGHT_SOURCE_EVIDENCE_INVALID",
            inspection.conclusion,
        )
        self.assertFalse(inspection.to_dict()["executionPermit"])

    def test_directory_path_fails_closed(self) -> None:
        directory_store = CanaryPreflightReceiptStore(
            Path(self.temporary_directory.name)
        )
        with self.assertRaises(CanaryPreflightReceiptError):
            directory_store.load()

    def test_source_has_no_network_process_credential_or_order_capability(self) -> None:
        source = inspect.getsource(receipt_module)
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

    def build(self, **changes: object):
        arguments = {
            "evidence_store": self.position_store,
            "position_result": self.position_result,
            "funding_result": self.funding_result,
            "credential_result": self.credential_result,
            "order_result": self.order_result,
            "stop_result": self.stop_result,
            "preflight_evaluated_at": PREFLIGHT_AT,
            "preflight_policy": self.preflight_policy,
            "recorded_at": RECORDED_AT,
            "receipt_policy": self.receipt_policy,
        }
        arguments.update(changes)
        return build_canary_preflight_receipt(**arguments)


def sha256_payload(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    unittest.main()
