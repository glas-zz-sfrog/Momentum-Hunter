from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal

from momentum_hunter.after_close_contract_trace import (
    BROKER_BOUNDARY,
    TEST_ONLY,
    AfterCloseTraceError,
    GetOnlyRecordingSession,
    RehearsalSubmissionBoundary,
    _acceptance,
    _secret_scan,
    _suspicious_semantic_values,
    build_test_only_transaction_trace,
)
from momentum_hunter.alpaca_paper_broker import AlpacaPaperOrderRequest
from momentum_hunter.alpaca_paper_engineering import PaperEngineeringPolicy
from momentum_hunter.alpaca_paper_onboarding import AlpacaPaperAccount
from momentum_hunter.broker_capabilities import (
    CAPABILITY_FRACTIONAL_MARKET,
    CAPABILITY_FRACTIONAL_PRECISION,
    CAPABILITY_FRACTIONAL_QUANTITY,
    BrokerCapability,
    BrokerCapabilityRegistry,
    CapabilityState,
)
from momentum_hunter.models import Candidate
from momentum_hunter.paper_risk_governor import PaperRiskPolicy
from momentum_hunter.provider_neutral_allocation import ProviderNeutralAllocationPolicy


def _policy() -> PaperEngineeringPolicy:
    return PaperEngineeringPolicy(
        policy_id="test-paper-policy",
        sample_id="test-sample-v2",
        allocation=ProviderNeutralAllocationPolicy(
            policy_id="test-allocation-policy",
            fixed_unit_risk_dollars=Decimal("2"),
            max_position_notional_dollars=Decimal("95"),
            minimum_cash_reserve_dollars=Decimal("5"),
            max_total_open_risk_dollars=Decimal("2"),
            daily_loss_limit_dollars=Decimal("4"),
            max_open_positions=1,
            max_snapshot_age_seconds=30,
        ),
        risk=PaperRiskPolicy(
            policy_id="test-risk-policy",
            maximum_spread_percent=Decimal("3"),
            maximum_entry_extension_percent=Decimal("0.25"),
            minimum_reward_risk=Decimal("1.5"),
        ),
        entry_notional_buffer_percent=Decimal("1"),
        minimum_entry_notional_dollars=Decimal("1"),
        order_poll_attempts=2,
        order_poll_interval_seconds=0,
    )


def _capabilities() -> BrokerCapabilityRegistry:
    return BrokerCapabilityRegistry.build(
        provider="ALPACA_TRADING_API",
        environment="PAPER_ONLY",
        capabilities=(
            BrokerCapability(
                CAPABILITY_FRACTIONAL_QUANTITY,
                CapabilityState.PROVEN,
                "true",
                ("synthetic test proof",),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_PRECISION,
                CapabilityState.PROVEN,
                "0.00000001",
                ("synthetic test proof",),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_MARKET,
                CapabilityState.PROVEN,
                "day",
                ("synthetic test proof",),
            ),
        ),
    )


class AfterCloseContractTraceTests(unittest.TestCase):
    def test_get_only_session_rejects_every_mutating_verb(self) -> None:
        session = GetOnlyRecordingSession()
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method), self.assertRaises(AfterCloseTraceError):
                getattr(session, method)("https://paper-api.alpaca.markets/v2/orders")
        self.assertEqual(4, len(session.mutation_attempts))
        self.assertEqual([], session.records)

    def test_submission_boundary_serializes_without_network_transport(self) -> None:
        boundary = RehearsalSubmissionBoundary()
        request = AlpacaPaperOrderRequest(
            symbol="SPY",
            side="buy",
            order_type="market",
            time_in_force="day",
            client_order_id="mh-paper-engineering-test-entry",
            notional=Decimal("10"),
        )
        payload = boundary.validate(request)

        self.assertEqual("10", payload["notional"])
        self.assertEqual(BROKER_BOUNDARY, boundary.result()["classification"])
        self.assertEqual(0, boundary.result()["providerCalls"])
        self.assertFalse(boundary.result()["networkTransportPresent"])

    def test_secret_scan_fails_on_known_value_and_passes_sanitized_packet(self) -> None:
        sanitized = _secret_scan(
            {
                "endpoint": "https://paper-api.alpaca.markets",
                "credential": "[redacted]",
                "riskDecisionId": "paper-risk-bf4f0e0b30a05c2be5d0ae0f",
            },
            known_credential_values=("paper-key-value", "paper-secret-value"),
        )
        leaked = _secret_scan(
            {"unexpected": "paper-secret-value"},
            known_credential_values=("paper-key-value", "paper-secret-value"),
        )

        self.assertEqual("PASS", sanitized["status"])
        self.assertEqual("FAIL", leaked["status"])
        self.assertTrue(leaked["knownCredentialValuesPresent"])

        shaped = _secret_scan(
            {"unexpected": "sk-exampleCredential123"},
            known_credential_values=(),
        )
        self.assertEqual("FAIL", shaped["status"])

    def test_acceptance_returns_structured_result(self) -> None:
        packet = {
            "finviz": {
                "schemaStatus": "PASS",
                "fieldMappings": [{}],
                "rawRowCount": 1,
                "parsedRowCount": 1,
                "qualifiedRowCount": 1,
            },
            "schwabQuotes": {"fieldMappings": [{}]},
            "schwabCandles": {
                "fieldMappings": [{}],
                "symbols": [
                    {
                        "intraday": {"semanticInvariantFailCount": 0},
                        "daily": {"semanticInvariantFailCount": 0},
                    }
                ],
            },
            "alpacaPaperAccount": {"fieldMappings": [{}]},
            "transactionTrace": {
                "terminalEvidence": {"terminal": True},
                "afterHoursEvidenceUsedAsRegularAuthority": False,
                "mode": TEST_ONLY,
            },
            "networkAudit": {
                "mutatingRequests": [],
                "orderSubmissionCount": 0,
                "alpacaLiveHostContacts": [],
                "schwabOrderEndpointsInvoked": [],
            },
            "scheduleBefore": {"hash": "same"},
            "scheduleAfter": {"hash": "same"},
            "secretScan": {"status": "PASS"},
        }

        result = _acceptance(packet)

        self.assertEqual("PASS", result["status"])
        self.assertTrue(all(result["checks"].values()))

    def test_stale_after_hours_quote_is_reported_as_suspicious(self) -> None:
        findings = _suspicious_semantic_values(
            {"rawRowCount": 1, "parsedRowCount": 1},
            {
                "quotes": [
                    {
                        "symbol": "IWM",
                        "status": "PASS",
                        "freshness": "STALE_DIAGNOSTIC",
                        "ageSeconds": 270.0,
                        "bid": 100.0,
                        "ask": 100.1,
                    }
                ]
            },
            {"symbols": []},
            {"usable": True},
        )

        self.assertEqual(["SCHWAB_QUOTE_STALE_DIAGNOSTIC:IWM:270.0s"], findings)

    def test_transaction_trace_reaches_boundary_and_remains_test_only(self) -> None:
        candidate = Candidate(
            ticker="NVDA",
            company="NVIDIA Corporation",
            price=Decimal("180"),
            percent_change=4.0,
            volume=10_000_000,
            relative_volume=2.0,
            market_cap=1_000_000_000_000,
        )
        account = AlpacaPaperAccount(
            status="ACTIVE",
            cash=Decimal("100"),
            buying_power=Decimal("100"),
            account_blocked=False,
            trading_blocked=False,
            trade_suspended_by_user=False,
            equity=Decimal("100"),
            last_equity=Decimal("100"),
        )
        trace = build_test_only_transaction_trace(
            candidate=candidate,
            selected_origin="LIVE_FINVIZ_QUALIFYING_IDENTITY",
            live_account=account,
            binding_fingerprint="A" * 64,
            policy=_policy(),
            arm_fingerprint="B" * 64,
            capabilities=_capabilities(),
            session_date=date(2026, 8, 12),
        )

        self.assertEqual(TEST_ONLY, trace["mode"])
        self.assertTrue(trace["riskDecision"]["status"] == "AUTHORIZED")
        self.assertTrue(trace["allocation"]["status"] == "AUTHORIZED")
        self.assertEqual(BROKER_BOUNDARY, trace["submissionBoundary"]["classification"])
        self.assertEqual(0, trace["submissionBoundary"]["providerCalls"])
        self.assertEqual("market", trace["orderShapes"]["entry"]["type"])
        self.assertEqual("stop", trace["orderShapes"]["protectiveStop"]["type"])
        self.assertFalse(trace["afterHoursEvidenceUsedAsRegularAuthority"])
        self.assertFalse(trace["terminalEvidence"]["providerSubmissionOccurred"])


if __name__ == "__main__":
    unittest.main()
