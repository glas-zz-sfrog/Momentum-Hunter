from __future__ import annotations

import ast
import inspect
import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import momentum_hunter.schwab_canary_funding as funding_module
from momentum_hunter.schwab_canary_funding import (
    CURRENT_BALANCE_SOURCE,
    RESTRICTIONS_BLOCKED,
    RESTRICTIONS_CLEAR,
    RESTRICTIONS_UNAVAILABLE,
    CanaryFundingGateError,
    CanaryFundingObservation,
    CanaryFundingPolicy,
    CanaryFundingRequirement,
    evaluate_canary_funding,
    read_current_schwab_funding_observation,
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
    SchwabReadOnlyAdapter,
)


OBSERVED_AT = datetime(2026, 7, 27, 15, 0, tzinfo=timezone.utc)
EVALUATED_AT = OBSERVED_AT + timedelta(seconds=1)
COMPLETE_SOURCE = "SCHWAB_SETTLED_CASH_RESTRICTIONS_V1"


class SchwabCanaryFundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = synthetic_source()
        self.source.balances = replace(
            self.source.balances,
            as_of=OBSERVED_AT.isoformat(),
        )
        self.binding = AccountIsolationPolicy().create_binding(
            self.source.list_authorized_accounts(),
            manually_confirmed_last_four=SYNTHETIC_ACCOUNT_LAST_FOUR,
        )
        self.adapter = SchwabReadOnlyAdapter(
            source=self.source,
            binding=self.binding,
        )
        self.requirement = CanaryFundingRequirement(
            requirement_id="PLUMBING-CANARY-FUNDING-0001",
            maximum_debit=25.0,
            minimum_cash_reserve=10.0,
        )
        self.policy = CanaryFundingPolicy(
            expected_source=COMPLETE_SOURCE,
            max_observation_age_seconds=30.0,
            max_collection_duration_seconds=5.0,
        )

    def test_complete_settled_cash_and_clear_restrictions_pass(self) -> None:
        result = self.evaluate(self.observation(settled_cash=35.0))
        payload = result.to_dict()

        self.assertTrue(result.passed)
        self.assertEqual("PASS", result.status)
        self.assertEqual(35.0, payload["requiredSettledCash"])
        self.assertTrue(payload["settledCashSufficient"])
        self.assertFalse(payload["cashAvailableSubstitutionAllowed"])
        self.assertFalse(payload["buyingPowerSubstitutionAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def test_current_balance_contract_is_honestly_unavailable(self) -> None:
        clock_values = iter(
            (
                OBSERVED_AT - timedelta(seconds=1),
                OBSERVED_AT,
            )
        )
        observation = read_current_schwab_funding_observation(
            self.adapter,
            clock=lambda: next(clock_values),
        )
        result = evaluate_canary_funding(
            binding=self.binding,
            requirement=self.requirement,
            observation=observation,
            evaluated_at=EVALUATED_AT,
            policy=replace(
                self.policy,
                expected_source=CURRENT_BALANCE_SOURCE,
            ),
        )

        self.assertFalse(result.passed)
        self.assertEqual(
            {"SETTLED_CASH_UNAVAILABLE", "RESTRICTIONS_UNAVAILABLE"},
            finding_codes(result),
        )
        self.assertIsNone(result.settled_cash_sufficient)

    def test_high_cash_available_or_buying_power_never_substitutes(self) -> None:
        balances = replace(
            self.source.balances,
            cash_available=1_000_000.0,
            buying_power=1_000_000.0,
        )
        result = self.evaluate(
            replace(
                self.observation(settled_cash=None),
                balances=balances,
            )
        )

        self.assertFalse(result.passed)
        self.assertIn("SETTLED_CASH_UNAVAILABLE", finding_codes(result))
        self.assertIsNone(result.settled_cash_sufficient)

    def test_settled_cash_must_cover_maximum_debit_plus_reserve(self) -> None:
        insufficient = self.evaluate(self.observation(settled_cash=34.99))
        exact = self.evaluate(self.observation(settled_cash=35.0))

        self.assertIn("SETTLED_CASH_INSUFFICIENT", finding_codes(insufficient))
        self.assertFalse(insufficient.settled_cash_sufficient)
        self.assertTrue(exact.passed)

    def test_unavailable_blocked_and_contradictory_restrictions_block(self) -> None:
        cases = {
            "unavailable": (
                RESTRICTIONS_UNAVAILABLE,
                (),
                {"RESTRICTIONS_UNAVAILABLE"},
            ),
            "blocked": (
                RESTRICTIONS_BLOCKED,
                ("GOOD_FAITH_RESTRICTION",),
                {"ACCOUNT_RESTRICTED"},
            ),
            "blocked_no_code": (
                RESTRICTIONS_BLOCKED,
                (),
                {"ACCOUNT_RESTRICTED", "RESTRICTION_EVIDENCE_CONTRADICTORY"},
            ),
            "clear_with_code": (
                RESTRICTIONS_CLEAR,
                ("UNEXPECTED_CODE",),
                {"RESTRICTION_EVIDENCE_CONTRADICTORY"},
            ),
            "unknown": (
                "MAYBE",
                (),
                {"RESTRICTION_STATE_INVALID"},
            ),
        }
        for label, (state, codes, expected) in cases.items():
            with self.subTest(label=label):
                result = self.evaluate(
                    self.observation(
                        settled_cash=100.0,
                        restriction_state=state,
                        restriction_codes=codes,
                    )
                )
                self.assertFalse(result.passed)
                self.assertTrue(expected.issubset(finding_codes(result)))

    def test_duplicate_or_invalid_restriction_codes_block(self) -> None:
        for codes in (
            ("CODE", "CODE"),
            ("bad code",),
            ("../escape",),
        ):
            with self.subTest(codes=codes):
                result = self.evaluate(
                    self.observation(
                        settled_cash=100.0,
                        restriction_state=RESTRICTIONS_BLOCKED,
                        restriction_codes=codes,
                    )
                )
                self.assertIn("RESTRICTION_CODES_INVALID", finding_codes(result))

    def test_account_count_identity_cash_type_status_and_balance_hash_block(self) -> None:
        account = self.source.accounts[0]
        observation = self.observation(settled_cash=100.0)
        cases = {
            "zero_accounts": replace(observation, authorized_accounts=()),
            "multiple_accounts": replace(
                observation,
                authorized_accounts=(
                    account,
                    SchwabAuthorizedAccount(
                        account_hash="SYNTHETIC-EXTRA-HASH",
                        account_number_last_four="9999",
                        account_type="INDIVIDUAL_CASH",
                        cash_only=True,
                    ),
                ),
            ),
            "account_hash": replace(
                observation,
                account=replace(
                    observation.account,
                    account_hash="SYNTHETIC-OTHER-HASH",
                ),
            ),
            "not_cash": replace(
                observation,
                account=replace(observation.account, cash_only=False),
            ),
            "not_open": replace(
                observation,
                account=replace(observation.account, status="CLOSED"),
            ),
            "balance_hash": replace(
                observation,
                balances=replace(
                    observation.balances,
                    account_hash="SYNTHETIC-OTHER-HASH",
                ),
            ),
        }
        for label, candidate in cases.items():
            with self.subTest(label=label):
                result = self.evaluate(candidate)
                self.assertFalse(result.passed)
                expected = (
                    "ACCOUNT_NOT_OPEN"
                    if label == "not_open"
                    else "ACCOUNT_ISOLATION_FAILED"
                )
                self.assertIn(expected, finding_codes(result))

    def test_source_mismatch_blocks(self) -> None:
        result = self.evaluate(
            replace(
                self.observation(settled_cash=100.0),
                source="UNAPPROVED_SOURCE",
            )
        )

        self.assertIn("EVIDENCE_SOURCE_MISMATCH", finding_codes(result))

    def test_stale_future_slow_reversed_and_balance_clocks_block(self) -> None:
        base = self.observation(settled_cash=100.0)
        cases = {
            "observation_stale": (
                replace(
                    base,
                    observed_at=(OBSERVED_AT - timedelta(seconds=31)).isoformat(),
                ),
                "OBSERVATION_STALE",
            ),
            "observation_future": (
                replace(
                    base,
                    observed_at=(EVALUATED_AT + timedelta(seconds=3)).isoformat(),
                ),
                "OBSERVATION_FROM_FUTURE",
            ),
            "slow": (
                replace(
                    base,
                    request_started_at=(
                        OBSERVED_AT - timedelta(seconds=6)
                    ).isoformat(),
                ),
                "COLLECTION_TOO_SLOW",
            ),
            "reversed": (
                replace(
                    base,
                    request_started_at=(
                        OBSERVED_AT + timedelta(seconds=1)
                    ).isoformat(),
                ),
                "COLLECTION_CLOCK_REVERSED",
            ),
            "balance_stale": (
                replace(
                    base,
                    balances=replace(
                        base.balances,
                        as_of=(
                            OBSERVED_AT - timedelta(seconds=31)
                        ).isoformat(),
                    ),
                ),
                "BALANCE_STALE",
            ),
            "balance_future": (
                replace(
                    base,
                    balances=replace(
                        base.balances,
                        as_of=(
                            EVALUATED_AT + timedelta(seconds=3)
                        ).isoformat(),
                    ),
                ),
                "BALANCE_FROM_FUTURE",
            ),
        }
        for label, (observation, expected) in cases.items():
            with self.subTest(label=label):
                result = self.evaluate(observation)
                self.assertFalse(result.passed)
                self.assertIn(expected, finding_codes(result))

    def test_invalid_and_naive_timestamps_block(self) -> None:
        base = self.observation(settled_cash=100.0)
        cases = (
            (replace(base, request_started_at="bad"), "REQUEST_START_INVALID"),
            (
                replace(base, observed_at="2026-07-27T15:00:00"),
                "OBSERVATION_TIME_NAIVE",
            ),
            (
                replace(
                    base,
                    balances=replace(base.balances, as_of="bad"),
                ),
                "BALANCE_TIME_INVALID",
            ),
        )
        for observation, expected in cases:
            with self.subTest(expected=expected):
                self.assertIn(expected, finding_codes(self.evaluate(observation)))

    def test_nonfinite_negative_balance_and_settled_cash_values_block(self) -> None:
        for field in ("cash_available", "buying_power", "liquidation_value"):
            for value in (-1.0, float("nan"), float("inf")):
                with self.subTest(field=field, value=value):
                    base = self.observation(settled_cash=100.0)
                    result = self.evaluate(
                        replace(
                            base,
                            balances=replace(base.balances, **{field: value}),
                        )
                    )
                    self.assertIn("BALANCE_FIELD_INVALID", finding_codes(result))
        for value in (-1.0, float("nan"), float("inf")):
            with self.subTest(settled_cash=value):
                result = self.evaluate(self.observation(settled_cash=value))
                self.assertIn("SETTLED_CASH_INVALID", finding_codes(result))
        malformed = self.observation(settled_cash=100.0)
        result = self.evaluate(
            replace(
                malformed,
                balances=replace(malformed.balances, cash_available="100"),
                settled_cash="100",
            )
        )
        self.assertIn("BALANCE_FIELD_INVALID", finding_codes(result))
        self.assertIn("SETTLED_CASH_INVALID", finding_codes(result))

    def test_reader_revalidates_account_after_read_and_does_not_mutate_source(self) -> None:
        before_account = repr(self.source.accounts)
        before_balances = repr(self.source.balances)
        calls_before = self.source.calls
        observation = read_current_schwab_funding_observation(
            self.adapter,
            clock=lambda: OBSERVED_AT,
        )

        self.assertEqual(CURRENT_BALANCE_SOURCE, observation.source)
        self.assertIsNone(observation.settled_cash)
        self.assertEqual(RESTRICTIONS_UNAVAILABLE, observation.restriction_state)
        self.assertEqual(calls_before + 6, self.source.calls)
        self.assertEqual(before_account, repr(self.source.accounts))
        self.assertEqual(before_balances, repr(self.source.balances))

    def test_account_change_during_reader_stops_before_observation(self) -> None:
        self.source.changed_account_hash_after_calls = self.source.calls + 5

        with self.assertRaisesRegex(AccountIsolationError, "hash changed"):
            read_current_schwab_funding_observation(
                self.adapter,
                clock=lambda: OBSERVED_AT,
            )

    def test_observation_and_result_do_not_expose_account_hash_or_balances(self) -> None:
        observation = self.observation(settled_cash=100.0)
        result = self.evaluate(observation)
        rendered = json.dumps(result.to_dict(), sort_keys=True)

        self.assertNotIn(SYNTHETIC_ACCOUNT_HASH, repr(observation))
        self.assertNotIn("100.0", repr(observation))
        self.assertNotIn(SYNTHETIC_ACCOUNT_HASH, rendered)
        self.assertNotIn('"cashAvailable":', rendered)
        self.assertNotIn('"buyingPower":', rendered)
        self.assertNotIn('"liquidationValue":', rendered)
        self.assertNotIn('"settledCashObserved":', rendered)

    def test_invalid_requirement_policy_and_evaluation_clock_are_rejected(self) -> None:
        for values in (
            {
                "requirement_id": "",
                "maximum_debit": 1.0,
                "minimum_cash_reserve": 0.0,
            },
            {
                "requirement_id": "ID",
                "maximum_debit": 0.0,
                "minimum_cash_reserve": 0.0,
            },
            {
                "requirement_id": "ID",
                "maximum_debit": 1.0,
                "minimum_cash_reserve": -1.0,
            },
            {
                "requirement_id": "ID",
                "maximum_debit": "1",
                "minimum_cash_reserve": 0.0,
            },
        ):
            with self.subTest(values=values), self.assertRaises(CanaryFundingGateError):
                CanaryFundingRequirement(**values)
        for field, value in (
            ("expected_source", ""),
            ("max_observation_age_seconds", 0.0),
            ("max_collection_duration_seconds", -1.0),
            ("max_future_skew_seconds", float("nan")),
        ):
            values = {
                "expected_source": COMPLETE_SOURCE,
                "max_observation_age_seconds": 30.0,
                "max_collection_duration_seconds": 5.0,
                "max_future_skew_seconds": 2.0,
            }
            values[field] = value
            with self.subTest(field=field), self.assertRaises(CanaryFundingGateError):
                CanaryFundingPolicy(**values)
        with self.assertRaises(CanaryFundingGateError):
            evaluate_canary_funding(
                binding=self.binding,
                requirement=self.requirement,
                observation=self.observation(settled_cash=100.0),
                evaluated_at=datetime(2026, 7, 27, 15, 0),
                policy=self.policy,
            )

    def test_module_has_no_network_credential_position_or_order_capability(self) -> None:
        source = inspect.getsource(funding_module)
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
        forbidden = {
            "get_positions",
            "preview_order",
            "submit_order",
            "replace_order",
            "cancel_order",
            "transmit_order",
        }
        self.assertFalse(functions & forbidden)
        self.assertFalse(calls & forbidden)

    def evaluate(self, observation: CanaryFundingObservation):
        return evaluate_canary_funding(
            binding=self.binding,
            requirement=self.requirement,
            observation=observation,
            evaluated_at=EVALUATED_AT,
            policy=self.policy,
        )

    def observation(
        self,
        *,
        settled_cash: float | None,
        restriction_state: str = RESTRICTIONS_CLEAR,
        restriction_codes: tuple[str, ...] = (),
    ) -> CanaryFundingObservation:
        account = self.source.get_account(SYNTHETIC_ACCOUNT_HASH)
        return CanaryFundingObservation(
            request_started_at=(
                OBSERVED_AT - timedelta(seconds=1)
            ).isoformat(),
            observed_at=OBSERVED_AT.isoformat(),
            source=COMPLETE_SOURCE,
            authorized_accounts=tuple(self.source.accounts),
            account=account,
            balances=self.source.balances,
            settled_cash=settled_cash,
            restriction_state=restriction_state,
            restriction_codes=restriction_codes,
        )


def finding_codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


if __name__ == "__main__":
    unittest.main()
