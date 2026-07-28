from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import inspect
import json
import unittest

import momentum_hunter.schwab_canary_order_emulator as emulator_module
from momentum_hunter.schwab_canary_order_emulator import (
    SYNTHETIC_ORDER_SOURCE,
    SyntheticOrderContractError,
    SyntheticSchwabOrderContractEmulator,
)
from momentum_hunter.schwab_canary_order_reconciliation import (
    CanaryOrderIntent,
    CanaryOrderReconciliationPolicy,
    create_account_binding_commitment,
    reconcile_canary_order,
)


UTC = timezone.utc
INTENT_AT = datetime(2026, 7, 27, 15, 0, tzinfo=UTC)
ATTEMPT_AT = INTENT_AT + timedelta(seconds=1)
ACK_AT = ATTEMPT_AT + timedelta(seconds=1)
FILL_ONE_AT = ACK_AT + timedelta(seconds=1)
FILL_TWO_AT = FILL_ONE_AT + timedelta(seconds=1)
CANCEL_AT = FILL_TWO_AT + timedelta(seconds=1)
FINAL_AT = CANCEL_AT + timedelta(seconds=1)
ACCOUNT_COMMITMENT = create_account_binding_commitment(
    account_hash="synthetic-account-hash",
    salt="synthetic-account-salt",
)


class SyntheticSchwabOrderContractEmulatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.intent = CanaryOrderIntent(
            sequence_id="canary-sequence-009",
            account_binding_commitment=ACCOUNT_COMMITMENT,
            symbol="TEST",
            side="BUY",
            quantity=1.0,
            order_type="LIMIT",
            limit_price=10.0,
            created_at=INTENT_AT.isoformat(),
        )
        self.policy = CanaryOrderReconciliationPolicy(
            expected_source=SYNTHETIC_ORDER_SOURCE,
            max_observation_age_seconds=30,
            max_future_skew_seconds=2,
        )
        self.emulator = SyntheticSchwabOrderContractEmulator()

    def test_accepted_attempt_and_acknowledgement_reconcile_exactly(self) -> None:
        attempt = self.accept()
        pending = self.observe(ATTEMPT_AT)
        working = self.emulator.record_synthetic_acknowledgement(
            command_id=self.intent.command_id,
            updated_at=ACK_AT.isoformat(),
        )
        current = working.observation(observed_at=ACK_AT.isoformat())

        result = reconcile_canary_order(
            intent=self.intent,
            submission_attempt=attempt,
            observations=(current,),
            evaluated_at=ACK_AT,
            policy=self.policy,
            previous_observation=pending,
        )

        self.assertTrue(result.passed)
        self.assertEqual("RESUME_EXISTING_ORDER", result.conclusion)
        self.assertEqual("WORKING", result.broker_status)
        self.assertFalse(result.to_dict()["retryAllowed"])
        self.assertFalse(result.to_dict()["transmitting"])

    def test_ack_lost_is_ambiguous_and_duplicate_attempt_cannot_retry(self) -> None:
        attempt = self.emulator.record_synthetic_attempt(
            intent=self.intent,
            attempted_at=ATTEMPT_AT.isoformat(),
            outcome="ACK_LOST",
        )

        result = reconcile_canary_order(
            intent=self.intent,
            submission_attempt=attempt,
            observations=(),
            evaluated_at=ACK_AT,
            policy=self.policy,
        )

        self.assertFalse(result.passed)
        self.assertEqual("AMBIGUOUS_SUBMISSION_DO_NOT_RETRY", result.conclusion)
        self.assertFalse(result.to_dict()["retryAllowed"])
        with self.assertRaisesRegex(
            SyntheticOrderContractError,
            "cannot be retried or changed",
        ):
            self.emulator.record_synthetic_attempt(
                intent=self.intent,
                attempted_at=ACK_AT.isoformat(),
                outcome="ACCEPTED",
            )

    def test_exact_duplicate_attempt_is_byte_idempotent(self) -> None:
        first = self.accept()
        snapshot = self.emulator.snapshot_json()
        second = self.accept()

        self.assertEqual(first, second)
        self.assertEqual(snapshot, self.emulator.snapshot_json())
        self.assertEqual(1, len(self.emulator.snapshot()["attempts"]))
        self.assertEqual(1, len(self.emulator.snapshot()["orders"]))

    def test_partial_fills_are_monotonic_and_weighted(self) -> None:
        attempt = self.accept()
        self.emulator.record_synthetic_acknowledgement(
            command_id=self.intent.command_id,
            updated_at=ACK_AT.isoformat(),
        )
        first = self.emulator.record_synthetic_fill(
            command_id=self.intent.command_id,
            fill_quantity=0.25,
            fill_price=9.90,
            updated_at=FILL_ONE_AT.isoformat(),
        )
        previous = first.observation(observed_at=FILL_ONE_AT.isoformat())
        second = self.emulator.record_synthetic_fill(
            command_id=self.intent.command_id,
            fill_quantity=0.25,
            fill_price=10.00,
            updated_at=FILL_TWO_AT.isoformat(),
        )
        current = second.observation(observed_at=FILL_TWO_AT.isoformat())

        result = reconcile_canary_order(
            intent=self.intent,
            submission_attempt=attempt,
            observations=(current,),
            evaluated_at=FILL_TWO_AT,
            policy=self.policy,
            previous_observation=previous,
        )

        self.assertTrue(result.passed)
        self.assertEqual("PARTIALLY_FILLED", result.broker_status)
        self.assertAlmostEqual(0.5, second.filled_quantity)
        self.assertAlmostEqual(0.5, second.remaining_quantity)
        self.assertAlmostEqual(9.95, second.average_fill_price)
        with self.assertRaisesRegex(
            SyntheticOrderContractError,
            "exceeds the remaining",
        ):
            self.emulator.record_synthetic_fill(
                command_id=self.intent.command_id,
                fill_quantity=0.75,
                fill_price=10.00,
                updated_at=CANCEL_AT.isoformat(),
            )

    def test_cancel_pending_may_race_to_full_fill_but_cannot_change_terminal(self) -> None:
        attempt = self.accept()
        self.emulator.record_synthetic_acknowledgement(
            command_id=self.intent.command_id,
            updated_at=ACK_AT.isoformat(),
        )
        cancel_pending = self.emulator.record_synthetic_cancel_request(
            command_id=self.intent.command_id,
            updated_at=FILL_ONE_AT.isoformat(),
        )
        previous = cancel_pending.observation(
            observed_at=FILL_ONE_AT.isoformat()
        )
        filled = self.emulator.record_synthetic_fill(
            command_id=self.intent.command_id,
            fill_quantity=1.0,
            fill_price=9.99,
            updated_at=FILL_TWO_AT.isoformat(),
        )
        current = filled.observation(observed_at=FILL_TWO_AT.isoformat())

        result = reconcile_canary_order(
            intent=self.intent,
            submission_attempt=attempt,
            observations=(current,),
            evaluated_at=FILL_TWO_AT,
            policy=self.policy,
            previous_observation=previous,
        )

        self.assertTrue(result.passed)
        self.assertEqual("FILLED", result.broker_status)
        with self.assertRaisesRegex(
            SyntheticOrderContractError,
            "cannot follow FILLED",
        ):
            self.emulator.record_synthetic_cancel_confirmation(
                command_id=self.intent.command_id,
                updated_at=CANCEL_AT.isoformat(),
            )

    def test_partial_fill_then_cancel_preserves_terminal_economics(self) -> None:
        self.accept()
        self.emulator.record_synthetic_fill(
            command_id=self.intent.command_id,
            fill_quantity=0.4,
            fill_price=9.95,
            updated_at=ACK_AT.isoformat(),
        )
        self.emulator.record_synthetic_cancel_request(
            command_id=self.intent.command_id,
            updated_at=FILL_ONE_AT.isoformat(),
        )
        canceled = self.emulator.record_synthetic_cancel_confirmation(
            command_id=self.intent.command_id,
            updated_at=FILL_TWO_AT.isoformat(),
        )

        self.assertEqual("CANCELED", canceled.status)
        self.assertAlmostEqual(0.4, canceled.filled_quantity)
        self.assertAlmostEqual(0.6, canceled.remaining_quantity)
        self.assertAlmostEqual(9.95, canceled.average_fill_price)
        repeated = self.emulator.record_synthetic_cancel_confirmation(
            command_id=self.intent.command_id,
            updated_at=FILL_TWO_AT.isoformat(),
        )
        self.assertIs(repeated, canceled)

    def test_rejection_and_expiration_are_deterministic_terminal_states(self) -> None:
        rejected_emulator = SyntheticSchwabOrderContractEmulator()
        rejected_emulator.record_synthetic_attempt(
            intent=self.intent,
            attempted_at=ATTEMPT_AT.isoformat(),
            outcome="REJECTED",
        )
        rejected = rejected_emulator.order_for(self.intent.command_id)
        self.assertIsNotNone(rejected)
        self.assertEqual("REJECTED", rejected.status)
        self.assertEqual(1.0, rejected.remaining_quantity)

        self.accept()
        expired = self.emulator.record_synthetic_expiration(
            command_id=self.intent.command_id,
            updated_at=ACK_AT.isoformat(),
        )
        self.assertEqual("EXPIRED", expired.status)
        with self.assertRaisesRegex(
            SyntheticOrderContractError,
            "terminal synthetic order",
        ):
            self.emulator.record_synthetic_fill(
                command_id=self.intent.command_id,
                fill_quantity=1.0,
                fill_price=9.99,
                updated_at=FILL_ONE_AT.isoformat(),
            )

    def test_snapshot_round_trip_preserves_identity_and_blocks_restart_retry(self) -> None:
        self.accept()
        self.emulator.record_synthetic_acknowledgement(
            command_id=self.intent.command_id,
            updated_at=ACK_AT.isoformat(),
        )
        self.emulator.record_synthetic_fill(
            command_id=self.intent.command_id,
            fill_quantity=0.5,
            fill_price=9.98,
            updated_at=FILL_ONE_AT.isoformat(),
        )
        serialized = self.emulator.snapshot_json()

        restored = SyntheticSchwabOrderContractEmulator.from_snapshot_json(
            serialized
        )

        self.assertEqual(serialized, restored.snapshot_json())
        self.assertEqual(
            self.intent.command_id,
            restored.attempt_for(self.intent.command_id).command_id,
        )
        self.assertEqual(
            "PARTIALLY_FILLED",
            restored.order_for(self.intent.command_id).status,
        )
        with self.assertRaisesRegex(
            SyntheticOrderContractError,
            "cannot be retried or changed",
        ):
            restored.record_synthetic_attempt(
                intent=self.intent,
                attempted_at=ACK_AT.isoformat(),
                outcome="ACCEPTED",
            )

    def test_ack_lost_snapshot_survives_restart_without_inventing_an_order(self) -> None:
        self.emulator.record_synthetic_attempt(
            intent=self.intent,
            attempted_at=ATTEMPT_AT.isoformat(),
            outcome="ACK_LOST",
        )

        restored = SyntheticSchwabOrderContractEmulator.from_snapshot_json(
            self.emulator.snapshot_json()
        )

        self.assertIsNotNone(restored.attempt_for(self.intent.command_id))
        self.assertIsNone(restored.order_for(self.intent.command_id))
        self.assertEqual(self.emulator.snapshot_json(), restored.snapshot_json())

    def test_snapshot_tamper_and_authority_escalation_fail_closed(self) -> None:
        self.accept()
        snapshot = self.emulator.snapshot()
        variants = []
        for field, value in (
            ("brokerActionAllowed", True),
            ("transmitting", True),
            ("networkAccess", True),
            ("orderTransmission", "AVAILABLE"),
        ):
            changed = deepcopy(snapshot)
            changed[field] = value
            variants.append(changed)
        changed_command = deepcopy(snapshot)
        changed_command["orders"][0]["commandId"] = "changed-command"
        variants.append(changed_command)
        changed_provider = deepcopy(snapshot)
        changed_provider["orders"][0]["providerOrderId"] = "changed-provider"
        variants.append(changed_provider)
        changed_quantity = deepcopy(snapshot)
        changed_quantity["orders"][0]["remainingQuantity"] = 2.0
        variants.append(changed_quantity)
        changed_lifecycle = deepcopy(snapshot)
        changed_lifecycle["orders"][0]["status"] = "CANCELED"
        variants.append(changed_lifecycle)

        for variant in variants:
            with self.subTest(variant=variant):
                with self.assertRaises(SyntheticOrderContractError):
                    SyntheticSchwabOrderContractEmulator.from_snapshot(variant)

    def test_snapshot_copy_cannot_mutate_live_emulator(self) -> None:
        self.accept()
        snapshot = self.emulator.snapshot()
        snapshot["orders"][0]["status"] = "FILLED"

        current = self.emulator.order_for(self.intent.command_id)

        self.assertEqual("PENDING_ACK", current.status)

    def test_capabilities_and_source_are_unmistakably_synthetic(self) -> None:
        capabilities = self.emulator.capabilities

        self.assertEqual(
            "SANITIZED_SYNTHETIC_CONTRACT_ONLY",
            capabilities["mode"],
        )
        self.assertFalse(capabilities["networkAccess"])
        self.assertFalse(capabilities["credentialsAccepted"])
        self.assertFalse(capabilities["brokerActionAllowed"])
        self.assertFalse(capabilities["transmitting"])
        self.assertFalse(capabilities["retryAllowed"])
        self.assertEqual("UNAVAILABLE", capabilities["orderTransmission"])
        self.assertIn("SYNTHETIC", SYNTHETIC_ORDER_SOURCE)

    def test_module_has_no_network_credentials_or_broker_action_methods(self) -> None:
        source = inspect.getsource(emulator_module)
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
        attributes = {
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
            "place_order",
            "replace_order",
            "cancel_order",
            "transmit_order",
            "transfer_money",
            "withdraw",
        }
        self.assertFalse(functions & forbidden)
        self.assertFalse(attributes & forbidden)
        lowered = source.lower()
        self.assertNotIn("api_key", lowered)
        self.assertNotIn("client_secret", lowered)
        self.assertNotIn("access_token", lowered)
        self.assertNotIn("refresh_token", lowered)

    def accept(self):
        return self.emulator.record_synthetic_attempt(
            intent=self.intent,
            attempted_at=ATTEMPT_AT.isoformat(),
            outcome="ACCEPTED",
        )

    def observe(self, observed_at: datetime):
        return self.emulator.observe_synthetic_order(
            command_id=self.intent.command_id,
            observed_at=observed_at.isoformat(),
        )


if __name__ == "__main__":
    unittest.main()
