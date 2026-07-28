from __future__ import annotations

import copy
import inspect
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import momentum_hunter.schwab_account_shape_evidence as shape_module
from momentum_hunter.schwab_account_discovery import DiscoveredSchwabAccount
from momentum_hunter.schwab_account_shape_evidence import (
    ACCOUNT_SHAPE_CONFIRMATION,
    ACCOUNT_SHAPE_SCHEMA_VERSION,
    MAX_DISTINCT_ARRAY_SHAPES,
    MAX_FIELD_NAME_LENGTH,
    SchwabAccountShapeEvidenceError,
    SchwabAccountShapeInspector,
    canonical_shape_json,
    describe_json_shape,
    main,
)
from momentum_hunter.schwab_onboarding import SchwabOAuthTokens
from momentum_hunter.schwab_readonly import (
    EXPECTED_ACCOUNT_TYPE,
    AccountIsolationError,
    SchwabAccountBinding,
)


ACCOUNT_HASH = "test-bound-account-hash-never-render"
ACCOUNT_ENDING = "2573"
ACCESS_TOKEN = "test-access-token-never-render"
BALANCE_VALUE = 123.45
OBSERVED_AT = datetime(2026, 7, 28, 5, 0, tzinfo=timezone.utc)


def account_payload() -> dict[str, object]:
    return {
        "securitiesAccount": {
            "type": "CASH",
            "accountNumber": "000000002573",
            "roundTrips": 0,
            "isDayTrader": False,
            "initialBalances": {
                "cashAvailableForTrading": BALANCE_VALUE,
            },
            "currentBalances": {
                "cashAvailableForTrading": BALANCE_VALUE,
                "liquidationValue": BALANCE_VALUE,
            },
            "projectedBalances": {
                "cashAvailableForTrading": BALANCE_VALUE,
            },
        }
    }


@dataclass
class FakeSecrets:
    expired: bool = False

    def load_tokens(self) -> SchwabOAuthTokens:
        return SchwabOAuthTokens(
            access_token=ACCESS_TOKEN,
            refresh_token="test-refresh-token-never-render",
            token_type="Bearer",
            scope="readonly",
            issued_at=OBSERVED_AT - timedelta(minutes=5),
            expires_at=(
                datetime.now(timezone.utc) - timedelta(seconds=1)
                if self.expired
                else datetime.now(timezone.utc) + timedelta(hours=1)
            ),
        )

    def status(self) -> dict[str, object]:
        return {
            "credentialsStored": True,
            "oauthAuthorized": True,
            "tokenState": "EXPIRED" if self.expired else "ACTIVE",
        }


@dataclass
class FakeBindings:
    binding: SchwabAccountBinding

    @property
    def exists(self) -> bool:
        return True

    def load(self) -> SchwabAccountBinding:
        return self.binding


@dataclass
class FakeDiscovery:
    accounts: list[DiscoveredSchwabAccount]
    observed_token: str = ""

    def discover(self, access_token: str) -> list[DiscoveredSchwabAccount]:
        self.observed_token = access_token
        return list(self.accounts)


@dataclass
class FakeDetails:
    payload: object
    observed_token: str = ""
    observed_hash: str = ""
    calls: int = 0

    def fetch(self, access_token: str, account_hash: str) -> object:
        self.calls += 1
        self.observed_token = access_token
        self.observed_hash = account_hash
        return copy.deepcopy(self.payload)


class SchwabAccountShapeEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.binding = SchwabAccountBinding(
            account_hash=ACCOUNT_HASH,
            account_number_last_four=ACCOUNT_ENDING,
            account_type=EXPECTED_ACCOUNT_TYPE,
        )
        self.discovery = FakeDiscovery(
            [
                DiscoveredSchwabAccount(
                    account_number_last_four=ACCOUNT_ENDING,
                    account_hash=ACCOUNT_HASH,
                )
            ]
        )
        self.details = FakeDetails(account_payload())
        self.inspector = SchwabAccountShapeInspector(
            secrets_repository=FakeSecrets(),
            binding_store=FakeBindings(self.binding),
            discovery_transport=self.discovery,
            details_transport=self.details,
            clock=lambda: OBSERVED_AT,
        )

    def test_live_path_revalidates_binding_and_retains_shape_only(self) -> None:
        evidence = self.inspector.inspect(confirmation=ACCOUNT_SHAPE_CONFIRMATION)
        payload = evidence.to_dict()

        self.assertEqual(ACCOUNT_SHAPE_SCHEMA_VERSION, payload["schemaVersion"])
        self.assertEqual("SCHWAB_ACCOUNT_SHAPE_READ_ONLY", payload["mode"])
        self.assertEqual(ACCOUNT_ENDING, payload["accountEnding"])
        self.assertEqual("CASH", payload["accountType"])
        self.assertTrue(payload["bindingRevalidated"])
        self.assertTrue(payload["providerEvidence"])
        self.assertFalse(payload["valuesRetained"])
        self.assertFalse(payload["rawPayloadRetained"])
        self.assertFalse(payload["rawPayloadHashRetained"])
        self.assertFalse(payload["positionsRequested"])
        self.assertFalse(payload["ordersRequested"])
        self.assertEqual("UNAVAILABLE", payload["semanticFieldMapping"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        self.assertEqual(ACCESS_TOKEN, self.discovery.observed_token)
        self.assertEqual(ACCESS_TOKEN, self.details.observed_token)
        self.assertEqual(ACCOUNT_HASH, self.details.observed_hash)
        self.assertEqual(1, self.details.calls)

        shape = payload["payloadShape"]
        current = shape["fields"]["securitiesAccount"]["fields"]["currentBalances"]
        self.assertEqual("object", current["type"])
        self.assertEqual(
            {"cashAvailableForTrading", "liquidationValue"},
            set(current["fields"]),
        )
        self.assertEqual(
            {"type": "number"},
            current["fields"]["cashAvailableForTrading"],
        )

    def test_rendered_evidence_contains_no_provider_values_or_secrets(self) -> None:
        rendered = json.dumps(
            self.inspector.inspect(
                confirmation=ACCOUNT_SHAPE_CONFIRMATION
            ).to_dict(),
            sort_keys=True,
        )

        for forbidden in (
            ACCOUNT_HASH,
            ACCESS_TOKEN,
            "test-refresh-token-never-render",
            "000000002573",
            str(BALANCE_VALUE),
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertIn('"accountNumber"', rendered)
        self.assertIn('"cashAvailableForTrading"', rendered)

    def test_inspection_does_not_mutate_source_payload(self) -> None:
        before = copy.deepcopy(self.details.payload)

        self.inspector.inspect(confirmation=ACCOUNT_SHAPE_CONFIRMATION)

        self.assertEqual(before, self.details.payload)

    def test_shape_and_digest_are_deterministic_across_values_and_key_order(self) -> None:
        first = account_payload()
        second = {
            "securitiesAccount": {
                "projectedBalances": {"cashAvailableForTrading": 999.0},
                "currentBalances": {
                    "liquidationValue": 1.0,
                    "cashAvailableForTrading": 2.0,
                },
                "initialBalances": {"cashAvailableForTrading": 3.0},
                "isDayTrader": True,
                "roundTrips": 4,
                "accountNumber": "different-value",
                "type": "MARGIN",
            }
        }

        first_shape = canonical_shape_json(describe_json_shape(first))
        second_shape = canonical_shape_json(describe_json_shape(second))

        self.assertEqual(first_shape, second_shape)

    def test_exact_confirmation_is_required_before_any_provider_call(self) -> None:
        with self.assertRaisesRegex(
            SchwabAccountShapeEvidenceError,
            "exact confirmation",
        ):
            self.inspector.inspect(confirmation="yes")

        self.assertEqual("", self.discovery.observed_token)
        self.assertEqual(0, self.details.calls)

    def test_expired_token_blocks_before_discovery(self) -> None:
        inspector = SchwabAccountShapeInspector(
            secrets_repository=FakeSecrets(expired=True),
            binding_store=FakeBindings(self.binding),
            discovery_transport=self.discovery,
            details_transport=self.details,
            clock=lambda: OBSERVED_AT,
        )

        with self.assertRaisesRegex(
            SchwabAccountShapeEvidenceError,
            "expired",
        ):
            inspector.inspect(confirmation=ACCOUNT_SHAPE_CONFIRMATION)

        self.assertEqual("", self.discovery.observed_token)
        self.assertEqual(0, self.details.calls)

    def test_zero_or_multiple_accounts_fail_before_details_request(self) -> None:
        for accounts in (
            [],
            self.discovery.accounts
            + [
                DiscoveredSchwabAccount(
                    account_number_last_four="9999",
                    account_hash="unexpected-account",
                )
            ],
        ):
            with self.subTest(account_count=len(accounts)):
                details = FakeDetails(account_payload())
                inspector = SchwabAccountShapeInspector(
                    secrets_repository=FakeSecrets(),
                    binding_store=FakeBindings(self.binding),
                    discovery_transport=FakeDiscovery(accounts),
                    details_transport=details,
                    clock=lambda: OBSERVED_AT,
                )
                with self.assertRaisesRegex(
                    AccountIsolationError,
                    "exactly one",
                ):
                    inspector.inspect(confirmation=ACCOUNT_SHAPE_CONFIRMATION)
                self.assertEqual(0, details.calls)

    def test_changed_hash_or_ending_fails_before_details_request(self) -> None:
        variants = (
            DiscoveredSchwabAccount(
                account_number_last_four=ACCOUNT_ENDING,
                account_hash="changed-hash",
            ),
            DiscoveredSchwabAccount(
                account_number_last_four="9999",
                account_hash=ACCOUNT_HASH,
            ),
        )
        for discovered in variants:
            with self.subTest(discovered=repr(discovered)):
                details = FakeDetails(account_payload())
                inspector = SchwabAccountShapeInspector(
                    secrets_repository=FakeSecrets(),
                    binding_store=FakeBindings(self.binding),
                    discovery_transport=FakeDiscovery([discovered]),
                    details_transport=details,
                    clock=lambda: OBSERVED_AT,
                )
                with self.assertRaises(AccountIsolationError):
                    inspector.inspect(confirmation=ACCOUNT_SHAPE_CONFIRMATION)
                self.assertEqual(0, details.calls)

    def test_changed_account_type_fails_closed(self) -> None:
        changed = account_payload()
        changed["securitiesAccount"]["type"] = "MARGIN"
        inspector = SchwabAccountShapeInspector(
            secrets_repository=FakeSecrets(),
            binding_store=FakeBindings(self.binding),
            discovery_transport=self.discovery,
            details_transport=FakeDetails(changed),
            clock=lambda: OBSERVED_AT,
        )

        with self.assertRaises(AccountIsolationError):
            inspector.inspect(confirmation=ACCOUNT_SHAPE_CONFIRMATION)

    def test_naive_clock_fails_without_rendering_evidence(self) -> None:
        inspector = SchwabAccountShapeInspector(
            secrets_repository=FakeSecrets(),
            binding_store=FakeBindings(self.binding),
            discovery_transport=self.discovery,
            details_transport=self.details,
            clock=lambda: OBSERVED_AT.replace(tzinfo=None),
        )

        with self.assertRaisesRegex(
            SchwabAccountShapeEvidenceError,
            "timezone-aware",
        ):
            inspector.inspect(confirmation=ACCOUNT_SHAPE_CONFIRMATION)

    def test_shape_rejects_unsafe_or_oversized_structures(self) -> None:
        cases = (
            {1: "non-string"},
            {"": "empty-key"},
            {" leading": "unsafe-key"},
            {"x" * (MAX_FIELD_NAME_LENGTH + 1): "long-key"},
            {"value": float("nan")},
            {"value": object()},
        )
        for payload in cases:
            with self.subTest(payload=repr(payload)[:80]):
                with self.assertRaises(SchwabAccountShapeEvidenceError):
                    describe_json_shape(payload)

        nested: object = "leaf"
        for _ in range(shape_module.MAX_SHAPE_DEPTH + 2):
            nested = {"nested": nested}
        with self.assertRaisesRegex(
            SchwabAccountShapeEvidenceError,
            "depth limit",
        ):
            describe_json_shape(nested)

        variants = [
            {f"field{index}": index}
            for index in range(MAX_DISTINCT_ARRAY_SHAPES + 1)
        ]
        with self.assertRaisesRegex(
            SchwabAccountShapeEvidenceError,
            "shape-variation limit",
        ):
            describe_json_shape(variants)

    def test_arrays_expose_shapes_not_lengths_or_values(self) -> None:
        shape = describe_json_shape(
            {
                "items": [
                    {"symbol": "AAA", "quantity": 1},
                    {"symbol": "BBB", "quantity": 999},
                ]
            }
        )
        rendered = canonical_shape_json(shape)

        self.assertIn('"itemShapes"', rendered)
        self.assertNotIn('"length"', rendered)
        self.assertNotIn("AAA", rendered)
        self.assertNotIn("BBB", rendered)
        self.assertNotIn("999", rendered)

    def test_status_is_nonnetwork_and_nontransmitting(self) -> None:
        status = self.inspector.status()

        self.assertEqual("PINNED", status["accountBinding"])
        self.assertEqual(ACCOUNT_ENDING, status["accountEnding"])
        self.assertEqual(
            "LOCKED_EXACT_CONFIRMATION_REQUIRED",
            status["shapeInspection"],
        )
        self.assertFalse(status["valuesRetained"])
        self.assertEqual("NONE", status["persistence"])
        self.assertFalse(status["positionsRequested"])
        self.assertFalse(status["ordersRequested"])
        self.assertFalse(status["executionPermit"])
        self.assertFalse(status["brokerActionAllowed"])
        self.assertFalse(status["transmitting"])
        self.assertEqual("UNAVAILABLE", status["orderTransmission"])
        self.assertEqual("", self.discovery.observed_token)
        self.assertEqual(0, self.details.calls)

    def test_cli_output_is_sanitized_and_invalid_arguments_are_generic(self) -> None:
        report = self.inspector.inspect(
            confirmation=ACCOUNT_SHAPE_CONFIRMATION
        ).to_dict()
        stdout = io.StringIO()
        with (
            patch.object(
                shape_module,
                "SchwabAccountShapeInspector",
                return_value=self.inspector,
            ),
            patch("builtins.input", return_value=ACCOUNT_SHAPE_CONFIRMATION),
            redirect_stdout(stdout),
        ):
            self.assertEqual(0, main(["inspect"]))
        self.assertEqual(report, json.loads(stdout.getvalue()))

        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit):
            main(["--secret-looking-value"])
        self.assertIn("invalid arguments", stderr.getvalue())
        self.assertNotIn("--secret-looking-value", stderr.getvalue())

    def test_module_has_no_order_or_persistence_capability(self) -> None:
        source = inspect.getsource(shape_module)
        functions = {
            node.name
            for node in __import__("ast").walk(__import__("ast").parse(source))
            if isinstance(node, (__import__("ast").FunctionDef, __import__("ast").AsyncFunctionDef))
        }
        forbidden = {
            "submit_order",
            "place_order",
            "replace_order",
            "cancel_order",
            "preview_order",
            "save",
            "delete",
            "write_text",
            "write_bytes",
        }

        self.assertFalse(functions & forbidden)
        self.assertNotIn("/orders", source)
        self.assertNotIn("session.post", source)
        self.assertNotIn("session.put", source)
        self.assertNotIn("session.delete", source)


if __name__ == "__main__":
    unittest.main()
