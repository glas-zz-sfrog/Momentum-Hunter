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

import momentum_hunter.schwab_canary_manual_decision as decision_module
from momentum_hunter.schwab_canary_credential_remediation import (
    SECRET_ROTATED,
    CanaryCredentialRemediationObservation,
    CanaryCredentialRemediationPolicy,
    evaluate_canary_credential_remediation,
)
from momentum_hunter.schwab_canary_evidence import CanaryPositionEvidenceStore
from momentum_hunter.schwab_canary_funding import (
    RESTRICTIONS_CLEAR,
    CanaryFundingResult,
)
from momentum_hunter.schwab_canary_manual_decision import (
    APPROVE_EXACT_CANARY_ORDER,
    DECLINE_CANARY_ORDER,
    DECISION_BLOCKED,
    DECISION_DECLINED,
    DECISION_MISSING,
    DECISION_RECORDED,
    CanaryManualDecisionConflict,
    CanaryManualDecisionError,
    CanaryManualDecisionPolicy,
    CanaryManualDecisionStore,
    build_canary_manual_decision,
    inspect_canary_manual_decision,
)
from momentum_hunter.schwab_canary_order_reconciliation import (
    CanaryOrderIntent,
    CanaryOrderReconciliationResult,
    create_account_binding_commitment,
)
from momentum_hunter.schwab_canary_positions import (
    CANARY_ACTIVE,
    PRE_CANARY,
    CanaryIntent,
    CanaryPositionInvariantResult,
)
from momentum_hunter.schwab_canary_preflight import CanaryPreflightPolicy
from momentum_hunter.schwab_canary_preflight_receipt import (
    CanaryPreflightReceiptPolicy,
    CanaryPreflightReceiptStore,
    build_canary_preflight_receipt,
)
from momentum_hunter.schwab_canary_stop_evidence import (
    CREDENTIAL_REVOKED,
    CanaryStopDrillResult,
)
from momentum_hunter.schwab_readonly import SchwabAccountBinding


UTC = timezone.utc
POSITION_AT = datetime(2026, 7, 27, 17, 0, tzinfo=UTC)
FUNDING_AT = POSITION_AT + timedelta(seconds=2)
CREDENTIAL_AT = POSITION_AT + timedelta(seconds=3)
ORDER_AT = POSITION_AT + timedelta(seconds=4)
STOP_AT = POSITION_AT + timedelta(seconds=5)
PREFLIGHT_AT = POSITION_AT + timedelta(seconds=6)
RECEIPT_AT = POSITION_AT + timedelta(seconds=7)
DECISION_AT = POSITION_AT + timedelta(seconds=8)
ACCOUNT_ENDING = "9001"
ACCOUNT_TYPE = "INDIVIDUAL_CASH"
ACCOUNT_HASH = "synthetic-manual-decision-account-hash"
ACCOUNT_SALT = "synthetic-manual-decision-salt"
ACTOR_ID = "STEVEN_SYNTHETIC_TEST"
INTENT_ID = "canary-intent-decision-test"
SEQUENCE_ID = "canary-sequence-decision-test"
REQUIREMENT_ID = "canary-funding-decision-test"
STOP_LATCH_SHA256 = "d" * 64
CREDENTIAL_INCIDENT_ID = "SCHWAB-CLIENT-SECRET-2026-07-26"
APPLICATION_COMMITMENT_SHA256 = "e" * 64
CREDENTIAL_EVIDENCE_SHA256 = "f" * 64
CREDENTIAL_INCIDENT_AT = POSITION_AT - timedelta(days=1)


class CanaryManualDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        directory = Path(self.temporary_directory.name)
        self.position_path = directory / "position-evidence.json"
        self.receipt_path = directory / "preflight-receipt.json"
        self.decision_path = directory / "manual-decision.json"
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
        self.order_account_commitment = create_account_binding_commitment(
            account_hash=ACCOUNT_HASH,
            salt=ACCOUNT_SALT,
        )
        self.order_intent = CanaryOrderIntent(
            sequence_id=SEQUENCE_ID,
            account_binding_commitment=self.order_account_commitment,
            symbol="TEST",
            side="BUY",
            quantity=1.0,
            order_type="LIMIT",
            limit_price=9.0,
            created_at=POSITION_AT.isoformat(),
        )
        self.order_result = CanaryOrderReconciliationResult(
            status="BLOCK",
            conclusion="NO_PRIOR_SUBMISSION_EVIDENCE",
            command_id=self.order_intent.command_id,
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
            latch_id="canary-stop-decision-test",
            latch_sha256=STOP_LATCH_SHA256,
            runtime_instance_id="runtime-decision-test",
            process_running=False,
            credential_state=CREDENTIAL_REVOKED,
            findings=(),
        )
        preflight_policy = CanaryPreflightPolicy(
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
            expected_order_command_id=self.order_intent.command_id,
            expected_stop_latch_sha256=STOP_LATCH_SHA256,
            max_evidence_age_seconds=30,
        )
        self.receipt_policy = CanaryPreflightReceiptPolicy(
            decision_window_seconds=20,
            max_future_skew_seconds=2,
        )
        receipt = build_canary_preflight_receipt(
            evidence_store=self.position_store,
            position_result=self.position_result,
            funding_result=self.funding_result,
            credential_result=self.credential_result,
            order_result=self.order_result,
            stop_result=self.stop_result,
            preflight_evaluated_at=PREFLIGHT_AT,
            preflight_policy=preflight_policy,
            recorded_at=RECEIPT_AT,
            receipt_policy=self.receipt_policy,
        )
        self.receipt_store = CanaryPreflightReceiptStore(self.receipt_path)
        self.receipt_store.persist(receipt)
        self.policy = CanaryManualDecisionPolicy(
            expected_actor_id=ACTOR_ID,
            expected_order_account_binding_commitment=(
                self.order_account_commitment
            ),
            max_order_intent_age_seconds=30,
            max_future_skew_seconds=2,
        )
        self.store = CanaryManualDecisionStore(self.decision_path)

    def test_exact_approval_records_decision_without_execution_authority(self) -> None:
        record = self.build(APPROVE_EXACT_CANARY_ORDER)

        payload = self.store.persist(record)
        inspection = self.inspect()

        self.assertEqual(DECISION_RECORDED, inspection.status)
        self.assertEqual(
            "EXACT_CANARY_INTENT_APPROVAL_RECORDED_NO_EXECUTION_AUTHORITY",
            inspection.conclusion,
        )
        self.assertEqual(self.order_intent.command_id, payload["orderCommandId"])
        self.assertEqual("BUY", payload["side"])
        self.assertEqual("LIMIT", payload["orderType"])
        self.assertEqual(9.0, payload["limitPrice"])
        self.assertEqual(10.0, payload["maximumDebit"])
        self.assertTrue(payload["decisionRecorded"])
        self.assertEqual("UNAVAILABLE", payload["actorAuthentication"])
        self.assertFalse(payload["operatorPresenceProven"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        self.assertFalse(inspection.to_dict()["executionPermit"])

    def test_exact_decline_is_terminal_evidence_without_authority(self) -> None:
        record = self.build(DECLINE_CANARY_ORDER)
        self.store.persist(record)

        inspection = self.inspect()

        self.assertEqual(DECISION_DECLINED, inspection.status)
        self.assertEqual("EXACT_CANARY_INTENT_DECLINED", inspection.conclusion)
        self.assertFalse(inspection.to_dict()["brokerActionAllowed"])
        self.assertFalse(inspection.to_dict()["transmitting"])

    def test_missing_decision_is_truthful_and_nontransmitting(self) -> None:
        inspection = self.inspect()

        self.assertEqual(DECISION_MISSING, inspection.status)
        self.assertFalse(inspection.decision_recorded)
        self.assertFalse(inspection.to_dict()["executionPermit"])
        self.assertFalse(inspection.to_dict()["brokerActionAllowed"])

    def test_decision_and_actor_must_match_frozen_policy_exactly(self) -> None:
        for changes in (
            {"decision": "APPROVE"},
            {"decision": ""},
            {"actor_id": "OTHER_ACTOR"},
            {"reason_code": "bad reason"},
        ):
            with self.subTest(changes=changes):
                selected_decision = str(
                    changes.get("decision", APPROVE_EXACT_CANARY_ORDER)
                )
                remaining = {
                    key: value
                    for key, value in changes.items()
                    if key != "decision"
                }
                with self.assertRaises(CanaryManualDecisionError):
                    self.build(selected_decision, **remaining)

    def test_account_binding_and_order_identity_mismatches_block(self) -> None:
        different_commitment = create_account_binding_commitment(
            account_hash="different-synthetic-account",
            salt=ACCOUNT_SALT,
        )
        cases = (
            replace(
                self.order_intent,
                account_binding_commitment=different_commitment,
            ),
            replace(self.order_intent, sequence_id="different-sequence"),
            replace(self.order_intent, symbol="OTHER"),
            replace(self.order_intent, quantity=2.0),
            replace(self.order_intent, side="SELL"),
            replace(self.order_intent, order_type="MARKET", limit_price=None),
            replace(self.order_intent, limit_price=11.0),
        )
        for order_intent in cases:
            with self.subTest(command_id=order_intent.command_id):
                with self.assertRaises(CanaryManualDecisionError):
                    self.build(
                        APPROVE_EXACT_CANARY_ORDER,
                        order_intent=order_intent,
                    )

    def test_order_intent_must_be_fresh_and_not_future_dated(self) -> None:
        stale = replace(
            self.order_intent,
            created_at=(DECISION_AT - timedelta(seconds=31)).isoformat(),
        )
        future = replace(
            self.order_intent,
            created_at=(DECISION_AT + timedelta(seconds=3)).isoformat(),
        )
        for order_intent in (stale, future):
            with self.subTest(created_at=order_intent.created_at):
                with self.assertRaises(CanaryManualDecisionError):
                    self.build(
                        APPROVE_EXACT_CANARY_ORDER,
                        order_intent=order_intent,
                    )

    def test_expired_or_missing_receipt_cannot_create_decision(self) -> None:
        with self.assertRaises(CanaryManualDecisionError):
            self.build(
                APPROVE_EXACT_CANARY_ORDER,
                decided_at=PREFLIGHT_AT + timedelta(seconds=21),
            )
        self.receipt_path.unlink()
        with self.assertRaises(CanaryManualDecisionError):
            self.build(APPROVE_EXACT_CANARY_ORDER)

    def test_position_chain_advance_blocks_decision_creation(self) -> None:
        self.advance_position_chain()

        with self.assertRaises(CanaryManualDecisionError):
            self.build(APPROVE_EXACT_CANARY_ORDER)

    def test_exact_duplicate_is_byte_idempotent_and_conflict_is_refused(self) -> None:
        approval = self.build(APPROVE_EXACT_CANARY_ORDER)
        self.store.persist(approval)
        before = self.decision_path.read_bytes()

        duplicate = self.store.persist(approval)

        self.assertEqual(approval.to_dict(), duplicate)
        self.assertEqual(before, self.decision_path.read_bytes())
        decline = self.build(DECLINE_CANARY_ORDER)
        with self.assertRaises(CanaryManualDecisionConflict):
            self.store.persist(decline)
        self.assertEqual(before, self.decision_path.read_bytes())

    def test_root_and_order_tampering_are_detected_without_repair(self) -> None:
        original = self.store.persist(
            self.build(APPROVE_EXACT_CANARY_ORDER)
        )
        original_bytes = self.decision_path.read_bytes()
        cases = (
            ("recordSha256", "0" * 64),
            ("executionPermit", True),
            ("brokerActionAllowed", True),
            ("replaceSupported", True),
            ("actorAuthentication", "PROVEN"),
            ("operatorPresenceProven", True),
            ("symbol", "OTHER"),
            ("limitPrice", 8.0),
            ("maximumDebit", 100.0),
            ("receiptSha256", "1" * 64),
        )
        for key, value in cases:
            with self.subTest(key=key):
                tampered = json.loads(json.dumps(original))
                tampered[key] = value
                self.decision_path.write_text(
                    json.dumps(tampered, sort_keys=True),
                    encoding="ascii",
                )
                with self.assertRaises(CanaryManualDecisionError):
                    self.store.load()
                self.assertTrue(self.decision_path.exists())
                self.decision_path.write_bytes(original_bytes)

    def test_rehashed_order_tamper_is_blocked_by_external_order_intent(self) -> None:
        payload = self.store.persist(
            self.build(APPROVE_EXACT_CANARY_ORDER)
        )
        tampered = json.loads(json.dumps(payload))
        tampered["symbol"] = "OTHER"
        tampered["decisionId"] = decision_id_for(tampered)
        tampered["recordSha256"] = record_sha256_for(tampered)
        self.decision_path.write_text(
            json.dumps(tampered, sort_keys=True),
            encoding="ascii",
        )

        inspection = self.inspect()

        self.assertEqual(DECISION_BLOCKED, inspection.status)
        self.assertEqual(
            "CANARY_MANUAL_DECISION_ORDER_INTENT_MISMATCH",
            inspection.conclusion,
        )
        self.assertFalse(inspection.to_dict()["executionPermit"])

    def test_decision_and_inspection_cannot_predate_their_evidence(self) -> None:
        with self.assertRaises(CanaryManualDecisionError):
            self.build(
                APPROVE_EXACT_CANARY_ORDER,
                decided_at=RECEIPT_AT - timedelta(milliseconds=1),
            )
        self.store.persist(self.build(APPROVE_EXACT_CANARY_ORDER))

        inspection = self.inspect(
            observed_at=DECISION_AT - timedelta(seconds=3)
        )

        self.assertEqual(DECISION_BLOCKED, inspection.status)
        self.assertEqual(
            "CANARY_MANUAL_DECISION_CLOCK_INVALID",
            inspection.conclusion,
        )
        self.assertFalse(inspection.to_dict()["executionPermit"])

    def test_receipt_expiry_or_source_advance_invalidates_recorded_decision(self) -> None:
        self.store.persist(self.build(APPROVE_EXACT_CANARY_ORDER))

        expired = self.inspect(
            observed_at=PREFLIGHT_AT + timedelta(seconds=21)
        )
        self.advance_position_chain()
        advanced = self.inspect(
            observed_at=PREFLIGHT_AT + timedelta(seconds=9)
        )

        self.assertEqual(DECISION_BLOCKED, expired.status)
        self.assertEqual(DECISION_BLOCKED, advanced.status)
        self.assertEqual(
            "CANARY_MANUAL_DECISION_RECEIPT_INVALID",
            advanced.conclusion,
        )
        self.assertFalse(expired.to_dict()["brokerActionAllowed"])
        self.assertFalse(advanced.to_dict()["brokerActionAllowed"])

    def test_changed_external_actor_or_account_policy_blocks_inspection(self) -> None:
        self.store.persist(self.build(APPROVE_EXACT_CANARY_ORDER))
        different_actor = replace(
            self.policy,
            expected_actor_id="DIFFERENT_ACTOR",
        )
        different_commitment = replace(
            self.policy,
            expected_order_account_binding_commitment="e" * 64,
        )
        for policy in (different_actor, different_commitment):
            with self.subTest(policy=repr(policy)):
                inspection = self.inspect(decision_policy=policy)
                self.assertEqual(DECISION_BLOCKED, inspection.status)
                self.assertEqual(
                    "CANARY_MANUAL_DECISION_POLICY_MISMATCH",
                    inspection.conclusion,
                )

    def test_decision_excludes_account_hash_and_full_commitment(self) -> None:
        payload = self.store.persist(
            self.build(APPROVE_EXACT_CANARY_ORDER)
        )
        serialized = json.dumps(payload, sort_keys=True)

        self.assertNotIn(ACCOUNT_HASH, serialized)
        self.assertNotIn(self.order_account_commitment, serialized)
        self.assertNotIn(self.position_store.binding_commitment, serialized)
        self.assertNotIn("accountHash", serialized)
        self.assertNotIn("accountBindingCommitment", serialized)
        self.assertIn(self.policy.order_account_binding_tag, serialized)
        self.assertNotIn(self.order_account_commitment, repr(self.policy))

    def test_build_persist_and_inspect_do_not_mutate_source_evidence(self) -> None:
        position_before = self.position_path.read_bytes()
        receipt_before = self.receipt_path.read_bytes()

        record = self.build(APPROVE_EXACT_CANARY_ORDER)
        self.store.persist(record)
        self.inspect()

        self.assertEqual(position_before, self.position_path.read_bytes())
        self.assertEqual(receipt_before, self.receipt_path.read_bytes())

    def test_policy_rejects_invalid_actor_commitment_and_clocks(self) -> None:
        for changes in (
            {"expected_actor_id": ""},
            {"expected_actor_id": "bad actor"},
            {"expected_order_account_binding_commitment": "not-a-hash"},
            {"max_order_intent_age_seconds": 0},
            {"max_future_skew_seconds": -1},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(CanaryManualDecisionError):
                    replace(self.policy, **changes)

    def test_source_has_no_network_process_credential_or_order_capability(self) -> None:
        source = inspect.getsource(decision_module)
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

    def build(self, decision: str, **changes: object):
        arguments = {
            "receipt_store": self.receipt_store,
            "position_evidence_store": self.position_store,
            "receipt_policy": self.receipt_policy,
            "order_intent": self.order_intent,
            "decision": decision,
            "actor_id": ACTOR_ID,
            "reason_code": "SYNTHETIC_TEST_DECISION",
            "decided_at": DECISION_AT,
            "policy": self.policy,
        }
        arguments.update(changes)
        return build_canary_manual_decision(**arguments)

    def inspect(self, **changes: object):
        arguments = {
            "decision_store": self.store,
            "receipt_store": self.receipt_store,
            "position_evidence_store": self.position_store,
            "receipt_policy": self.receipt_policy,
            "decision_policy": self.policy,
            "order_intent": self.order_intent,
            "observed_at": DECISION_AT + timedelta(seconds=1),
        }
        arguments.update(changes)
        return inspect_canary_manual_decision(**arguments)

    def advance_position_chain(self) -> None:
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


def decision_id_for(payload: dict[str, object]) -> str:
    identity = {
        "decision": payload["decision"],
        "decidedAt": payload["decidedAt"],
        "actorId": payload["actorId"],
        "receiptId": payload["receiptId"],
        "receiptSha256": payload["receiptSha256"],
        "orderCommandId": payload["orderCommandId"],
        "symbol": payload["symbol"],
        "side": payload["side"],
        "quantity": payload["quantity"],
        "orderType": payload["orderType"],
        "limitPrice": payload["limitPrice"],
        "maximumDebit": payload["maximumDebit"],
    }
    return f"canary-decision-{sha256_payload(identity)[:24]}"


def record_sha256_for(payload: dict[str, object]) -> str:
    unsigned = {
        key: value
        for key, value in payload.items()
        if key != "recordSha256"
    }
    return sha256_payload(unsigned)


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
