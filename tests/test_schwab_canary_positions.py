from __future__ import annotations

import ast
import inspect
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import momentum_hunter.schwab_canary_positions as canary_module
from momentum_hunter.schwab_canary_positions import (
    CANARY_ACTIVE,
    POST_CANARY,
    PRE_CANARY,
    CanaryIntent,
    CanaryPositionInvariantError,
    CanaryPositionObservation,
    CanaryPositionPolicy,
    evaluate_canary_position_invariant,
    read_canary_position_observation,
)
from momentum_hunter.schwab_emulator import (
    SYNTHETIC_ACCOUNT_HASH,
    SYNTHETIC_ACCOUNT_LAST_FOUR,
    synthetic_source,
)
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    AccountIsolationPolicy,
    SchwabAuthorizedAccount,
    SchwabPosition,
    SchwabReadOnlyAdapter,
)


OBSERVED_AT = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)
EVALUATED_AT = OBSERVED_AT + timedelta(seconds=1)


class SchwabCanaryPositionInvariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = synthetic_source()
        self.binding = AccountIsolationPolicy().create_binding(
            self.source.list_authorized_accounts(),
            manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR,
        )
        self.adapter = SchwabReadOnlyAdapter(
            source=self.source,
            binding=self.binding,
        )
        self.intent = CanaryIntent(
            intent_id="PLUMBING-CANARY-0001",
            symbol="TEST",
            quantity=1.0,
        )
        self.policy = CanaryPositionPolicy(
            max_observation_age_seconds=30.0,
            max_collection_duration_seconds=5.0,
        )

    def test_pre_canary_passes_only_with_zero_positions(self) -> None:
        result = self.evaluate(PRE_CANARY, self.observation())

        self.assertTrue(result.passed)
        self.assertEqual("PASS", result.status)
        self.assertEqual("POSITION_INVARIANT_PASS", result.to_dict()["conclusion"])
        self.assertFalse(result.to_dict()["transmitting"])
        self.assertEqual("UNAVAILABLE", result.to_dict()["orderTransmission"])

    def test_active_canary_passes_only_with_exact_long_position(self) -> None:
        position = self.position(symbol="test", quantity=1.0)
        result = self.evaluate(CANARY_ACTIVE, self.observation(position))

        self.assertTrue(result.passed)
        self.assertEqual(1.0, result.observed_canary_quantity)
        self.assertEqual(1, result.observed_position_count)

    def test_post_canary_passes_only_after_return_to_zero_positions(self) -> None:
        result = self.evaluate(POST_CANARY, self.observation())

        self.assertTrue(result.passed)
        failed = self.evaluate(
            POST_CANARY,
            self.observation(self.position(symbol="TEST", quantity=1.0)),
        )
        self.assertFalse(failed.passed)
        self.assertIn("ZERO_POSITION_INVARIANT_FAILED", finding_codes(failed))

    def test_pre_canary_blocks_any_existing_position(self) -> None:
        result = self.evaluate(
            PRE_CANARY,
            self.observation(self.position(symbol="SPY", quantity=1.0)),
        )

        self.assertFalse(result.passed)
        self.assertIn("ZERO_POSITION_INVARIANT_FAILED", finding_codes(result))

    def test_active_canary_blocks_missing_extra_wrong_and_short_positions(self) -> None:
        cases = {
            "missing": (
                self.observation(),
                {"ACTIVE_POSITION_COUNT_FAILED", "CANARY_POSITION_MISSING"},
            ),
            "extra": (
                self.observation(
                    self.position(symbol="TEST", quantity=1.0),
                    self.position(symbol="SPY", quantity=1.0),
                ),
                {"ACTIVE_POSITION_COUNT_FAILED", "UNEXPECTED_POSITION"},
            ),
            "wrong": (
                self.observation(self.position(symbol="SPY", quantity=1.0)),
                {"CANARY_POSITION_MISSING", "UNEXPECTED_POSITION"},
            ),
            "short": (
                self.observation(self.position(symbol="TEST", quantity=-1.0)),
                {"CANARY_POSITION_NOT_LONG", "CANARY_QUANTITY_MISMATCH"},
            ),
        }
        for label, (observation, expected_codes) in cases.items():
            with self.subTest(label=label):
                result = self.evaluate(CANARY_ACTIVE, observation)
                self.assertFalse(result.passed)
                self.assertTrue(expected_codes.issubset(finding_codes(result)))

    def test_active_canary_blocks_quantity_drift_and_duplicate_symbol_rows(self) -> None:
        drift = self.evaluate(
            CANARY_ACTIVE,
            self.observation(self.position(symbol="TEST", quantity=2.0)),
        )
        duplicate = self.evaluate(
            CANARY_ACTIVE,
            self.observation(
                self.position(symbol="TEST", quantity=0.5),
                self.position(symbol="TEST", quantity=0.5),
            ),
        )

        self.assertIn("CANARY_QUANTITY_MISMATCH", finding_codes(drift))
        self.assertIn("DUPLICATE_POSITION_SYMBOL", finding_codes(duplicate))
        self.assertIn("CANARY_POSITION_MISSING", finding_codes(duplicate))

    def test_account_count_hash_type_and_cash_only_anomalies_block(self) -> None:
        expected_account = self.source.accounts[0]
        cases = {
            "zero": (),
            "multiple": (
                expected_account,
                SchwabAuthorizedAccount(
                    account_hash="SYNTHETIC-EXTRA-HASH",
                    account_number_last_four="9999",
                    account_type="INDIVIDUAL_CASH",
                    cash_only=True,
                ),
            ),
            "hash": (replace(expected_account, account_hash="SYNTHETIC-CHANGED-HASH"),),
            "type": (replace(expected_account, account_type="MARGIN"),),
            "cash": (replace(expected_account, cash_only=False),),
        }
        for label, accounts in cases.items():
            with self.subTest(label=label):
                result = self.evaluate(
                    PRE_CANARY,
                    replace(self.observation(), authorized_accounts=accounts),
                )
                self.assertFalse(result.passed)
                self.assertIn("ACCOUNT_ISOLATION_FAILED", finding_codes(result))

    def test_position_from_other_account_blocks_without_exposing_hash(self) -> None:
        result = self.evaluate(
            CANARY_ACTIVE,
            self.observation(
                replace(
                    self.position(symbol="TEST", quantity=1.0),
                    account_hash="SYNTHETIC-OTHER-ACCOUNT-HASH",
                )
            ),
        )
        rendered = json.dumps(result.to_dict(), sort_keys=True)

        self.assertFalse(result.passed)
        self.assertIn("POSITION_ACCOUNT_MISMATCH", finding_codes(result))
        self.assertNotIn("SYNTHETIC-OTHER-ACCOUNT-HASH", rendered)
        self.assertNotIn(SYNTHETIC_ACCOUNT_HASH, rendered)

    def test_stale_future_naive_and_invalid_observation_times_block(self) -> None:
        cases = {
            "stale": (
                (OBSERVED_AT - timedelta(seconds=31)).isoformat(),
                "OBSERVATION_STALE",
            ),
            "future": (
                (EVALUATED_AT + timedelta(seconds=3)).isoformat(),
                "OBSERVATION_FROM_FUTURE",
            ),
            "naive": ("2026-07-27T15:00:00", "OBSERVATION_TIME_NAIVE"),
            "invalid": ("not-a-time", "OBSERVATION_TIME_INVALID"),
        }
        for label, (observed_at, expected_code) in cases.items():
            with self.subTest(label=label):
                result = self.evaluate(
                    PRE_CANARY,
                    replace(self.observation(), observed_at=observed_at),
                )
                self.assertFalse(result.passed)
                self.assertIn(expected_code, finding_codes(result))

    def test_slow_and_reversed_collection_clocks_block(self) -> None:
        slow = self.evaluate(
            PRE_CANARY,
            replace(
                self.observation(),
                request_started_at=(OBSERVED_AT - timedelta(seconds=6)).isoformat(),
            ),
        )
        reversed_clock = self.evaluate(
            PRE_CANARY,
            replace(
                self.observation(),
                request_started_at=(OBSERVED_AT + timedelta(seconds=1)).isoformat(),
            ),
        )

        self.assertIn("COLLECTION_TOO_SLOW", finding_codes(slow))
        self.assertIn("COLLECTION_CLOCK_REVERSED", finding_codes(reversed_clock))

    def test_invalid_request_start_time_blocks(self) -> None:
        for value, expected_code in (
            ("not-a-time", "REQUEST_START_INVALID"),
            ("2026-07-27T15:00:00", "REQUEST_START_NAIVE"),
        ):
            with self.subTest(value=value):
                result = self.evaluate(
                    PRE_CANARY,
                    replace(self.observation(), request_started_at=value),
                )
                self.assertFalse(result.passed)
                self.assertIn(expected_code, finding_codes(result))

    def test_nonfinite_position_quantities_block(self) -> None:
        for quantity in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(quantity=quantity):
                result = self.evaluate(
                    CANARY_ACTIVE,
                    self.observation(self.position(symbol="TEST", quantity=quantity)),
                )
                self.assertFalse(result.passed)
                self.assertIn("POSITION_QUANTITY_INVALID", finding_codes(result))

    def test_read_observation_uses_only_existing_read_only_adapter(self) -> None:
        calls_before = self.source.calls
        clock_values = iter(
            (
                OBSERVED_AT - timedelta(seconds=1),
                OBSERVED_AT,
            )
        )
        observation = read_canary_position_observation(
            self.adapter,
            clock=lambda: next(clock_values),
        )

        self.assertEqual((), observation.positions)
        self.assertEqual(1, len(observation.authorized_accounts))
        self.assertEqual(
            (OBSERVED_AT - timedelta(seconds=1)).isoformat(),
            observation.request_started_at,
        )
        self.assertEqual(OBSERVED_AT.isoformat(), observation.observed_at)
        self.assertEqual(calls_before + 4, self.source.calls)

    def test_observation_repr_never_exposes_account_or_position_hashes(self) -> None:
        observation = self.observation(
            self.position(symbol="TEST", quantity=1.0)
        )

        rendered = repr(observation)

        self.assertNotIn(SYNTHETIC_ACCOUNT_HASH, rendered)
        self.assertIn("authorized_account_count=1", rendered)
        self.assertIn("position_count=1", rendered)

    def test_adapter_account_change_stops_read_before_observation_is_returned(self) -> None:
        self.source.changed_account_hash_after_calls = self.source.calls

        with self.assertRaisesRegex(AccountIsolationError, "hash changed"):
            read_canary_position_observation(
                self.adapter,
                clock=lambda: OBSERVED_AT,
            )

    def test_account_change_at_end_of_collection_is_not_returned(self) -> None:
        self.source.changed_account_hash_after_calls = self.source.calls + 3

        with self.assertRaisesRegex(AccountIsolationError, "hash changed"):
            read_canary_position_observation(
                self.adapter,
                clock=lambda: OBSERVED_AT,
            )

    def test_evaluator_does_not_mutate_source_inputs(self) -> None:
        observation = self.observation(self.position(symbol="TEST", quantity=1.0))
        before = repr(observation)

        result = self.evaluate(CANARY_ACTIVE, observation)

        self.assertTrue(result.passed)
        self.assertEqual(before, repr(observation))
        self.assertEqual(1, len(observation.positions))

    def test_invalid_phase_intent_policy_and_naive_evaluation_are_rejected(self) -> None:
        with self.assertRaises(CanaryPositionInvariantError):
            self.evaluate("LIVE", self.observation())
        for values in (
            {"intent_id": "", "symbol": "TEST", "quantity": 1.0},
            {"intent_id": "bad intent", "symbol": "TEST", "quantity": 1.0},
            {"intent_id": "id", "symbol": "", "quantity": 1.0},
            {"intent_id": "id", "symbol": "TEST", "quantity": 0.0},
            {"intent_id": "id", "symbol": "TEST", "quantity": float("nan")},
        ):
            with self.subTest(values=values), self.assertRaises(CanaryPositionInvariantError):
                CanaryIntent(**values)
        for field, value in (
            ("max_observation_age_seconds", 0.0),
            ("max_observation_age_seconds", -1.0),
            ("max_observation_age_seconds", float("nan")),
            ("max_collection_duration_seconds", 0.0),
            ("max_collection_duration_seconds", -1.0),
            ("max_collection_duration_seconds", float("nan")),
        ):
            values = {
                "max_observation_age_seconds": 30.0,
                "max_collection_duration_seconds": 5.0,
            }
            values[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(
                CanaryPositionInvariantError
            ):
                CanaryPositionPolicy(**values)
        with self.assertRaises(CanaryPositionInvariantError):
            evaluate_canary_position_invariant(
                phase=PRE_CANARY,
                binding=self.binding,
                intent=self.intent,
                observation=self.observation(),
                evaluated_at=datetime(2026, 7, 27, 15, 0),
                policy=self.policy,
            )

    def test_module_has_no_network_credential_or_order_capability(self) -> None:
        source = inspect.getsource(canary_module)
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
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
        self.assertFalse(
            functions
            & {
                "preview_order",
                "submit_order",
                "replace_order",
                "cancel_order",
                "transmit_order",
            }
        )
        self.assertFalse(
            calls
            & {
                "preview_order",
                "submit_order",
                "replace_order",
                "cancel_order",
                "transmit_order",
            }
        )

    def evaluate(
        self,
        phase: str,
        observation: CanaryPositionObservation,
    ):
        return evaluate_canary_position_invariant(
            phase=phase,
            binding=self.binding,
            intent=self.intent,
            observation=observation,
            evaluated_at=EVALUATED_AT,
            policy=self.policy,
        )

    def observation(
        self,
        *positions: SchwabPosition,
    ) -> CanaryPositionObservation:
        return CanaryPositionObservation(
            request_started_at=(OBSERVED_AT - timedelta(seconds=1)).isoformat(),
            observed_at=OBSERVED_AT.isoformat(),
            authorized_accounts=tuple(self.source.accounts),
            positions=tuple(positions),
        )

    @staticmethod
    def position(*, symbol: str, quantity: float) -> SchwabPosition:
        return SchwabPosition(
            account_hash=SYNTHETIC_ACCOUNT_HASH,
            symbol=symbol,
            quantity=quantity,
            average_price=10.0,
            market_value=quantity * 10.0,
        )


def finding_codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


if __name__ == "__main__":
    unittest.main()
