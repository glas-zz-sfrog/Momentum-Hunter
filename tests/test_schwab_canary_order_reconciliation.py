from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
import unittest

import momentum_hunter.schwab_canary_order_reconciliation as reconciliation_module
from momentum_hunter.schwab_canary_order_reconciliation import (
    CURRENT_ORDER_SOURCE,
    CanaryBrokerOrderObservation,
    CanaryOrderIntent,
    CanaryOrderReconciliationPolicy,
    CanarySubmissionAttempt,
    create_account_binding_commitment,
    map_current_schwab_order,
    reconcile_canary_order,
)
from momentum_hunter.schwab_readonly import SchwabOrder


UTC = timezone.utc
INTENT_AT = datetime(2026, 7, 27, 14, 0, tzinfo=UTC)
ATTEMPTED_AT = INTENT_AT + timedelta(seconds=1)
OBSERVED_AT = ATTEMPTED_AT + timedelta(seconds=2)
EVALUATED_AT = OBSERVED_AT + timedelta(seconds=1)
COMPLETE_SOURCE = "SYNTHETIC_BROKER_ORDER_V1"
SYNTHETIC_ACCOUNT_HASH = "synthetic-canary-account-hash"
SYNTHETIC_SALT = "synthetic-test-salt"


class CanaryOrderReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.commitment = create_account_binding_commitment(
            account_hash=SYNTHETIC_ACCOUNT_HASH,
            salt=SYNTHETIC_SALT,
        )
        self.intent = CanaryOrderIntent(
            sequence_id="canary-sequence-001",
            account_binding_commitment=self.commitment,
            symbol="TEST",
            side="BUY",
            quantity=1.0,
            order_type="LIMIT",
            limit_price=10.0,
            created_at=INTENT_AT.isoformat(),
        )
        self.attempt = CanarySubmissionAttempt(
            command_id=self.intent.command_id,
            sequence_id=self.intent.sequence_id,
            account_binding_commitment=self.commitment,
            attempted_at=ATTEMPTED_AT.isoformat(),
        )
        self.policy = CanaryOrderReconciliationPolicy(
            expected_source=COMPLETE_SOURCE,
            max_observation_age_seconds=30,
            max_future_skew_seconds=2,
        )

    def test_command_identity_is_stable_and_change_sensitive(self) -> None:
        duplicate = replace(self.intent)
        changed = replace(self.intent, quantity=2.0)

        self.assertEqual(self.intent.command_id, duplicate.command_id)
        self.assertNotEqual(self.intent.command_id, changed.command_id)
        self.assertTrue(self.intent.command_id.startswith("canary-order-"))

    def test_one_exact_broker_match_resumes_existing_order(self) -> None:
        result = self.reconcile(self.observation())

        self.assertTrue(result.passed)
        self.assertEqual("RESUME_EXISTING_ORDER", result.conclusion)
        self.assertEqual("provider-order-1", result.provider_order_id)
        self.assertFalse(result.to_dict()["retryAllowed"])
        self.assertFalse(result.to_dict()["transmitting"])

    def test_zero_match_after_attempt_is_ambiguous_and_never_retryable(self) -> None:
        result = self.reconcile()

        self.assertFalse(result.passed)
        self.assertEqual(
            "AMBIGUOUS_SUBMISSION_DO_NOT_RETRY",
            result.conclusion,
        )
        self.assertFalse(result.to_dict()["retryAllowed"])

    def test_no_attempt_and_no_order_is_not_submission_authority(self) -> None:
        result = self.reconcile(submission_attempt=None)

        self.assertFalse(result.passed)
        self.assertEqual("NO_PRIOR_SUBMISSION_EVIDENCE", result.conclusion)

    def test_order_without_attempt_is_blocked(self) -> None:
        result = self.reconcile(
            self.observation(),
            submission_attempt=None,
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            "UNEXPECTED_ORDER_WITHOUT_ATTEMPT",
            result.conclusion,
        )
        self.assertIn("ORDER_WITHOUT_SUBMISSION_ATTEMPT", finding_codes(result))

    def test_duplicate_exact_orders_lock_out_the_command(self) -> None:
        first = self.observation(provider_order_id="provider-order-1")
        second = self.observation(provider_order_id="provider-order-2")

        result = self.reconcile(first, second)

        self.assertFalse(result.passed)
        self.assertEqual("DUPLICATE_ORDER_LOCKOUT", result.conclusion)
        self.assertEqual(2, result.exact_match_count)

    def test_missing_provider_order_id_is_blocked(self) -> None:
        result = self.reconcile(self.observation(provider_order_id=""))

        self.assertFalse(result.passed)
        self.assertIn("PROVIDER_ORDER_ID_MISSING", finding_codes(result))

    def test_command_identity_conflict_is_blocked(self) -> None:
        conflict = self.observation(symbol="OTHER")

        result = self.reconcile(conflict)

        self.assertFalse(result.passed)
        self.assertEqual("BROKER_EVIDENCE_INVALID", result.conclusion)
        self.assertIn("COMMAND_IDENTITY_CONFLICT", finding_codes(result))

    def test_partial_fill_is_consistent_and_resumable(self) -> None:
        partial = self.observation(
            status="PARTIALLY_FILLED",
            filled_quantity=0.4,
            remaining_quantity=0.6,
            average_fill_price=9.99,
        )

        result = self.reconcile(partial)

        self.assertTrue(result.passed)
        self.assertEqual("PARTIALLY_FILLED", result.broker_status)

    def test_inconsistent_partial_fill_is_blocked(self) -> None:
        partial = self.observation(
            status="PARTIALLY_FILLED",
            filled_quantity=0.4,
            remaining_quantity=0.7,
            average_fill_price=9.99,
        )

        result = self.reconcile(partial)

        self.assertFalse(result.passed)
        self.assertIn("ORDER_QUANTITY_MISMATCH", finding_codes(result))

    def test_cancel_pending_may_race_to_additional_partial_fill(self) -> None:
        previous = self.observation(
            status="CANCEL_PENDING",
            filled_quantity=0.25,
            remaining_quantity=0.75,
            average_fill_price=9.98,
            updated_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
            observed_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
        )
        current = self.observation(
            status="PARTIALLY_FILLED",
            filled_quantity=0.5,
            remaining_quantity=0.5,
            average_fill_price=9.99,
        )

        result = self.reconcile(current, previous_observation=previous)

        self.assertTrue(result.passed)

    def test_cancel_pending_may_race_to_full_fill(self) -> None:
        previous = self.observation(
            status="CANCEL_PENDING",
            filled_quantity=0.5,
            remaining_quantity=0.5,
            average_fill_price=9.98,
            updated_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
            observed_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
        )
        current = self.observation(
            status="FILLED",
            filled_quantity=1.0,
            remaining_quantity=0.0,
            average_fill_price=9.99,
        )

        result = self.reconcile(current, previous_observation=previous)

        self.assertTrue(result.passed)

    def test_terminal_status_cannot_move_backward(self) -> None:
        previous = self.observation(
            status="FILLED",
            filled_quantity=1.0,
            remaining_quantity=0.0,
            average_fill_price=9.99,
            updated_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
            observed_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
        )
        current = self.observation(status="WORKING")

        result = self.reconcile(current, previous_observation=previous)

        self.assertFalse(result.passed)
        self.assertIn("ORDER_LIFECYCLE_REVERSED", finding_codes(result))

    def test_filled_quantity_cannot_decrease(self) -> None:
        previous = self.observation(
            status="PARTIALLY_FILLED",
            filled_quantity=0.5,
            remaining_quantity=0.5,
            average_fill_price=9.98,
            updated_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
            observed_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
        )
        current = self.observation(
            status="PARTIALLY_FILLED",
            filled_quantity=0.25,
            remaining_quantity=0.75,
            average_fill_price=9.99,
        )

        result = self.reconcile(current, previous_observation=previous)

        self.assertFalse(result.passed)
        self.assertIn("FILLED_QUANTITY_DECREASED", finding_codes(result))
        self.assertIn("REMAINING_QUANTITY_INCREASED", finding_codes(result))

    def test_unknown_status_is_blocked(self) -> None:
        result = self.reconcile(self.observation(status="MYSTERY"))

        self.assertFalse(result.passed)
        self.assertIn("ORDER_STATUS_UNSUPPORTED", finding_codes(result))

    def test_attempt_identity_mismatch_is_blocked(self) -> None:
        wrong = replace(
            self.attempt,
            account_binding_commitment="f" * 64,
        )

        result = self.reconcile(
            self.observation(),
            submission_attempt=wrong,
        )

        self.assertFalse(result.passed)
        self.assertIn("ATTEMPT_ACCOUNT_MISMATCH", finding_codes(result))

    def test_invalid_attempt_without_broker_rows_is_not_generic_ambiguity(
        self,
    ) -> None:
        wrong = replace(self.attempt, command_id="wrong-command")

        result = self.reconcile(submission_attempt=wrong)

        self.assertFalse(result.passed)
        self.assertEqual("BROKER_EVIDENCE_INVALID", result.conclusion)
        self.assertIn("ATTEMPT_COMMAND_MISMATCH", finding_codes(result))

    def test_order_account_mismatch_is_blocked(self) -> None:
        result = self.reconcile(
            self.observation(account_binding_commitment="f" * 64)
        )

        self.assertFalse(result.passed)
        self.assertIn("ORDER_ACCOUNT_MISMATCH", finding_codes(result))

    def test_stale_future_and_reversed_clocks_are_blocked(self) -> None:
        stale = self.reconcile(
            self.observation(
                observed_at=(
                    EVALUATED_AT - timedelta(seconds=31)
                ).isoformat()
            )
        )
        future = self.reconcile(
            self.observation(
                observed_at=(
                    EVALUATED_AT + timedelta(seconds=3)
                ).isoformat()
            )
        )
        reversed_update = self.reconcile(
            self.observation(
                entered_at=OBSERVED_AT.isoformat(),
                updated_at=(
                    OBSERVED_AT - timedelta(seconds=3)
                ).isoformat(),
            )
        )

        self.assertIn("ORDER_OBSERVATION_STALE", finding_codes(stale))
        self.assertIn(
            "ORDER_OBSERVATION_FROM_FUTURE",
            finding_codes(future),
        )
        self.assertIn(
            "ORDER_UPDATE_BEFORE_ENTRY",
            finding_codes(reversed_update),
        )

    def test_current_schwab_order_contract_is_explicitly_incomplete(self) -> None:
        order = SchwabOrder(
            account_hash=SYNTHETIC_ACCOUNT_HASH,
            order_id="provider-order-1",
            symbol="TEST",
            side="BUY",
            quantity=1.0,
            order_type="LIMIT",
            status="WORKING",
            entered_at=ATTEMPTED_AT.isoformat(),
        )
        mapped = map_current_schwab_order(
            order,
            expected_account_hash=SYNTHETIC_ACCOUNT_HASH,
            account_binding_salt=SYNTHETIC_SALT,
            observed_at=OBSERVED_AT.isoformat(),
        )
        current_policy = CanaryOrderReconciliationPolicy(
            expected_source=CURRENT_ORDER_SOURCE,
            max_observation_age_seconds=30,
        )

        result = reconcile_canary_order(
            intent=self.intent,
            submission_attempt=self.attempt,
            observations=(mapped,),
            evaluated_at=EVALUATED_AT,
            policy=current_policy,
        )

        self.assertFalse(result.passed)
        self.assertEqual("BROKER_EVIDENCE_INCOMPLETE", result.conclusion)
        self.assertTrue(
            {
                "CLIENT_COMMAND_ID_UNAVAILABLE",
                "FILLED_QUANTITY_UNAVAILABLE",
                "REMAINING_QUANTITY_UNAVAILABLE",
                "ORDER_UPDATED_TIME_UNAVAILABLE",
            }.issubset(finding_codes(result))
        )

    def test_current_mapper_rejects_a_different_account(self) -> None:
        order = SchwabOrder(
            account_hash="different-account",
            order_id="provider-order-1",
            symbol="TEST",
            side="BUY",
            quantity=1.0,
            order_type="LIMIT",
            status="WORKING",
            entered_at=ATTEMPTED_AT.isoformat(),
        )

        with self.assertRaisesRegex(
            ValueError,
            "different account identity",
        ):
            map_current_schwab_order(
                order,
                expected_account_hash=SYNTHETIC_ACCOUNT_HASH,
                account_binding_salt=SYNTHETIC_SALT,
                observed_at=OBSERVED_AT.isoformat(),
            )

    def test_previous_observation_must_match_command_and_source(self) -> None:
        previous = self.observation(
            client_command_id="different-command",
            source="WRONG_SOURCE",
            updated_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
            observed_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
        )

        result = self.reconcile(
            self.observation(),
            previous_observation=previous,
        )

        self.assertFalse(result.passed)
        self.assertIn(
            "PREVIOUS_ORDER_IDENTITY_MISMATCH",
            finding_codes(result),
        )
        self.assertIn("EVIDENCE_SOURCE_MISMATCH", finding_codes(result))

    def test_terminal_order_economics_cannot_change(self) -> None:
        previous = self.observation(
            status="FILLED",
            filled_quantity=1.0,
            remaining_quantity=0.0,
            average_fill_price=9.98,
            updated_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
            observed_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
        )
        current = self.observation(
            status="FILLED",
            filled_quantity=1.0,
            remaining_quantity=0.0,
            average_fill_price=9.99,
        )

        result = self.reconcile(current, previous_observation=previous)

        self.assertFalse(result.passed)
        self.assertIn("TERMINAL_ORDER_CHANGED", finding_codes(result))

    def test_result_and_repr_do_not_expose_account_hash_or_salt(self) -> None:
        observation = self.observation()
        rendered = json.dumps(self.reconcile(observation).to_dict())

        self.assertNotIn(SYNTHETIC_ACCOUNT_HASH, rendered)
        self.assertNotIn(SYNTHETIC_SALT, rendered)
        self.assertNotIn(self.commitment, repr(self.intent))
        self.assertNotIn(self.commitment, repr(self.attempt))
        self.assertNotIn(self.commitment, repr(observation))

    def test_reconciliation_does_not_mutate_source_observations(self) -> None:
        observations = [self.observation()]
        original = list(observations)

        self.reconcile(*observations)

        self.assertEqual(original, observations)

    def test_module_has_no_network_credential_or_order_action_capability(self) -> None:
        source = inspect.getsource(reconciliation_module)
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
                "schwab_onboarding",
                "schwab_market_data",
            }
        )
        forbidden = {
            "preview_order",
            "submit_order",
            "replace_order",
            "cancel_order",
            "transmit_order",
        }
        self.assertFalse(functions & forbidden)
        self.assertFalse(calls & forbidden)

    def reconcile(
        self,
        *observations: CanaryBrokerOrderObservation,
        submission_attempt: CanarySubmissionAttempt | None = ...,
        previous_observation: CanaryBrokerOrderObservation | None = None,
    ):
        attempt = (
            self.attempt
            if submission_attempt is ...
            else submission_attempt
        )
        return reconcile_canary_order(
            intent=self.intent,
            submission_attempt=attempt,
            observations=observations,
            evaluated_at=EVALUATED_AT,
            policy=self.policy,
            previous_observation=previous_observation,
        )

    def observation(
        self,
        *,
        provider_order_id: str = "provider-order-1",
        client_command_id: str | None = None,
        source: str = COMPLETE_SOURCE,
        account_binding_commitment: str | None = None,
        symbol: str = "TEST",
        side: str = "BUY",
        requested_quantity: float = 1.0,
        filled_quantity: float | None = 0.0,
        remaining_quantity: float | None = 1.0,
        average_fill_price: float | None = None,
        order_type: str = "LIMIT",
        status: str = "WORKING",
        entered_at: str | None = None,
        updated_at: str | None = None,
        observed_at: str | None = None,
    ) -> CanaryBrokerOrderObservation:
        return CanaryBrokerOrderObservation(
            provider_order_id=provider_order_id,
            client_command_id=(
                self.intent.command_id
                if client_command_id is None
                else client_command_id
            ),
            source=source,
            account_binding_commitment=(
                self.commitment
                if account_binding_commitment is None
                else account_binding_commitment
            ),
            symbol=symbol,
            side=side,
            requested_quantity=requested_quantity,
            filled_quantity=filled_quantity,
            remaining_quantity=remaining_quantity,
            average_fill_price=average_fill_price,
            order_type=order_type,
            status=status,
            entered_at=entered_at or ATTEMPTED_AT.isoformat(),
            updated_at=updated_at or OBSERVED_AT.isoformat(),
            observed_at=observed_at or OBSERVED_AT.isoformat(),
        )


def finding_codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


if __name__ == "__main__":
    unittest.main()
