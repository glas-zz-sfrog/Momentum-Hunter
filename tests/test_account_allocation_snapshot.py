from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import requests

from momentum_hunter.account_allocation import (
    AccountAllocationContext,
    AccountAllocationPolicy,
    AccountPortfolioSnapshot,
    build_account_allocation_decision,
)
from momentum_hunter.account_allocation_snapshot import (
    PORTFOLIO_SNAPSHOT_SOURCE,
    AccountAllocationBrokerageAnomaly,
    AccountAllocationSnapshotError,
    AccountAllocationSnapshotNetworkError,
    AccountAllocationSnapshotResponseError,
    FreshAccountAllocationSource,
    ParsedSchwabAccountSnapshot,
    SchwabAccountPortfolioSnapshotSource,
    SchwabAccountSnapshotResponse,
    SchwabAccountSnapshotTransport,
    build_shadow_portfolio_snapshot,
    load_shadow_portfolio_snapshot,
    parse_schwab_account_snapshot,
)
from momentum_hunter.schwab_account_discovery import DiscoveredSchwabAccount
from momentum_hunter.schwab_readonly import (
    AccountIsolationError,
    SchwabAccountBinding,
)
from momentum_hunter.shadow_trading import ShadowStateStore, ShadowTradingState


NOW = datetime(2026, 8, 8, 17, 0, 1, tzinfo=timezone.utc)
PROVIDER_AT = datetime(2026, 8, 8, 17, 0, 0, tzinfo=timezone.utc)
ACCOUNT_HASH = "opaque/hash-value"


def binding(**changes: object) -> SchwabAccountBinding:
    values: dict[str, object] = {
        "account_hash": ACCOUNT_HASH,
        "account_number_last_four": "2573",
        "account_type": "INDIVIDUAL_CASH",
    }
    values.update(changes)
    return SchwabAccountBinding(**values)


def account_payload(*, positions: object = None, **balance_changes: object) -> dict[str, object]:
    balances: dict[str, object] = {
        "cashAvailableForTrading": 100.0,
        "liquidationValue": 100.0,
    }
    balances.update(balance_changes)
    account: dict[str, object] = {
        "type": "CASH",
        "accountNumber": "000000002573",
        "currentBalances": balances,
    }
    if positions is not None:
        account["positions"] = positions
    return {"securitiesAccount": account}


def response(*, payload: object | None = None) -> SchwabAccountSnapshotResponse:
    return SchwabAccountSnapshotResponse(
        payload=account_payload() if payload is None else payload,
        provider_timestamp=PROVIDER_AT,
        received_at=NOW,
    )


def policy() -> AccountAllocationPolicy:
    return AccountAllocationPolicy(
        policy_id="synthetic-policy",
        fixed_unit_risk_dollars=10.0,
        max_position_notional_dollars=50.0,
        minimum_cash_reserve_dollars=50.0,
        max_total_open_risk_dollars=10.0,
        daily_loss_limit_dollars=10.0,
        max_open_positions=1,
        max_balance_age_seconds=5,
    )


def allocation_context() -> AccountAllocationContext:
    return AccountAllocationContext(
        binding_fingerprint="a" * 64,
        account_ending="2573",
        account_type="INDIVIDUAL_CASH",
        authorized_account_count=1,
        cash_available=100.0,
        buying_power=100.0,
        liquidation_value=100.0,
        committed_notional=0.0,
        committed_open_risk=0.0,
        open_position_count=0,
        realized_pnl_today=0.0,
        provider_timestamp=PROVIDER_AT.isoformat(),
        portfolio_timestamp=NOW.isoformat(),
        receipt_timestamp=NOW.isoformat(),
        source="SYNTHETIC_ACCOUNT",
        portfolio_source="SYNTHETIC_PORTFOLIO",
    )


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        is_redirect: bool = False,
        date_header: str | None = "Sat, 08 Aug 2026 17:00:00 GMT",
        content: bytes = b"{}",
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.is_redirect = is_redirect
        self.headers = {} if date_header is None else {"Date": date_header}
        self.content = content

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append((url, kwargs))
        if isinstance(self.result, requests.RequestException):
            raise self.result
        return cast(FakeResponse, self.result)


class StaticBindingStore:
    def __init__(self, value: SchwabAccountBinding) -> None:
        self.value = value

    def load(self) -> SchwabAccountBinding:
        return self.value


class StaticTokenProvider:
    def access_token(self) -> str:
        return "synthetic-access-token"


class StaticDiscovery:
    def __init__(self, accounts: list[DiscoveredSchwabAccount]) -> None:
        self.accounts = accounts
        self.calls = 0

    def discover(self, _token: str) -> list[DiscoveredSchwabAccount]:
        self.calls += 1
        return list(self.accounts)


class StaticSnapshotTransport:
    def __init__(self, value: SchwabAccountSnapshotResponse) -> None:
        self.value = value
        self.calls = 0

    def fetch(self, _token: str, _account_hash: str) -> SchwabAccountSnapshotResponse:
        self.calls += 1
        return self.value


class CountingContextSource:
    def __init__(self, value: AccountAllocationContext) -> None:
        self.value = value
        self.calls = 0

    def capture_context(self) -> AccountAllocationContext:
        self.calls += 1
        return self.value


class SchwabAccountSnapshotTransportTests(unittest.TestCase):
    def test_exact_get_requests_positions_and_preserves_two_clocks(self) -> None:
        session = FakeSession(FakeResponse(account_payload()))
        transport = SchwabAccountSnapshotTransport(session=session, clock=lambda: NOW)

        result = transport.fetch("token", ACCOUNT_HASH)

        self.assertEqual(PROVIDER_AT, result.provider_timestamp)
        self.assertEqual(NOW, result.received_at)
        self.assertEqual(1, len(session.calls))
        url, kwargs = session.calls[0]
        self.assertEqual(
            "https://api.schwabapi.com/trader/v1/accounts/opaque%2Fhash-value",
            url,
        )
        self.assertEqual({"fields": "positions"}, kwargs["params"])
        self.assertFalse(kwargs["allow_redirects"])
        self.assertEqual("Bearer token", kwargs["headers"]["Authorization"])

    def test_transport_rejects_redirect_status_oversize_date_and_network_failure(self) -> None:
        cases = (
            FakeResponse({}, is_redirect=True),
            FakeResponse({}, status_code=500),
            FakeResponse({}, content=b"x" * (512 * 1024 + 1)),
            FakeResponse({}, date_header=None),
            FakeResponse({}, date_header="invalid"),
        )
        for item in cases:
            with self.subTest(item=item):
                with self.assertRaises(AccountAllocationSnapshotResponseError):
                    SchwabAccountSnapshotTransport(
                        session=FakeSession(item),
                        clock=lambda: NOW,
                    ).fetch("token", ACCOUNT_HASH)
        with self.assertRaises(AccountAllocationSnapshotNetworkError):
            SchwabAccountSnapshotTransport(
                session=FakeSession(requests.ConnectionError("secret detail")),
                clock=lambda: NOW,
            ).fetch("token", ACCOUNT_HASH)

    def test_transport_rejects_future_provider_clock_and_invalid_json(self) -> None:
        future = FakeResponse(
            {},
            date_header="Sat, 08 Aug 2026 17:00:02 GMT",
        )
        with self.assertRaises(AccountAllocationSnapshotResponseError):
            SchwabAccountSnapshotTransport(
                session=FakeSession(future),
                clock=lambda: NOW,
            ).fetch("token", ACCOUNT_HASH)
        invalid_json = FakeResponse(ValueError("raw provider detail"))
        with self.assertRaises(AccountAllocationSnapshotResponseError) as caught:
            SchwabAccountSnapshotTransport(
                session=FakeSession(invalid_json),
                clock=lambda: NOW,
            ).fetch("token", ACCOUNT_HASH)
        self.assertNotIn("raw provider detail", str(caught.exception))


class SchwabAccountSnapshotParsingTests(unittest.TestCase):
    def test_cash_balance_without_buying_power_uses_cash_available(self) -> None:
        parsed = parse_schwab_account_snapshot(response(), binding=binding())

        self.assertIsInstance(parsed, ParsedSchwabAccountSnapshot)
        self.assertEqual(100.0, parsed.balances.cash_available)
        self.assertEqual(100.0, parsed.balances.buying_power)
        self.assertEqual(100.0, parsed.balances.liquidation_value)
        self.assertEqual(PROVIDER_AT.isoformat(), parsed.balances.as_of)
        self.assertEqual((), parsed.positions)
        self.assertNotIn(ACCOUNT_HASH, repr(parsed.authorized_account))
        self.assertNotIn(ACCOUNT_HASH, repr(parsed))
        self.assertNotIn("000000002573", repr(response()))

    def test_position_is_parsed_for_fail_closed_account_anomaly_handling(self) -> None:
        payload = account_payload(
            positions=[
                {
                    "longQuantity": 1.0,
                    "shortQuantity": 0.0,
                    "averagePrice": 25.0,
                    "marketValue": 26.0,
                    "instrument": {"symbol": "NVDA", "assetType": "EQUITY"},
                }
            ]
        )
        parsed = parse_schwab_account_snapshot(
            response(payload=payload),
            binding=binding(),
        )

        self.assertEqual(1, len(parsed.positions))
        self.assertEqual("NVDA", parsed.positions[0].symbol)
        self.assertEqual(1.0, parsed.positions[0].quantity)

    def test_wrong_account_or_malformed_financial_values_fail_closed(self) -> None:
        wrong = account_payload()
        wrong["securitiesAccount"]["accountNumber"] = "000000009999"
        with self.assertRaises(AccountIsolationError):
            parse_schwab_account_snapshot(response(payload=wrong), binding=binding())
        for changes in (
            {"cashAvailableForTrading": True},
            {"cashAvailableForTrading": -1.0},
            {"liquidationValue": float("nan")},
        ):
            with self.subTest(changes=changes):
                with self.assertRaises(AccountAllocationSnapshotResponseError):
                    parse_schwab_account_snapshot(
                        response(payload=account_payload(**changes)),
                        binding=binding(),
                    )


class ShadowPortfolioSnapshotTests(unittest.TestCase):
    def test_empty_state_is_a_fresh_zero_commitment_snapshot(self) -> None:
        snapshot = build_shadow_portfolio_snapshot(
            ShadowTradingState(),
            observed_at=NOW,
        )

        self.assertEqual(0.0, snapshot.committed_notional)
        self.assertEqual(0.0, snapshot.committed_open_risk)
        self.assertEqual(0, snapshot.open_position_count)
        self.assertEqual(0.0, snapshot.realized_pnl_today)
        self.assertEqual(PORTFOLIO_SNAPSHOT_SOURCE, snapshot.source)

    def test_active_allocation_and_terminal_outcome_are_derived_without_mutation(self) -> None:
        decision = build_account_allocation_decision(
            trade_plan_id="plan-1",
            entry_price=10.0,
            stop_price=9.0,
            target_price=12.0,
            policy=policy(),
            context=allocation_context(),
            decision_at=NOW,
        )
        active = SimpleNamespace(
            shadow_trade_id="active",
            status="open",
            outcome=None,
            position=SimpleNamespace(quantity=5, average_entry_price=10.0),
            order=None,
            account_allocation_json=json.dumps(asdict(decision), sort_keys=True),
            account_allocation_fingerprint=decision.fingerprint,
        )
        terminal = SimpleNamespace(
            shadow_trade_id="closed",
            status="completed",
            outcome=SimpleNamespace(
                executable_pnl=-2.5,
                exit_timestamp="2026-08-08T16:45:00+00:00",
            ),
            position=None,
            order=None,
            account_allocation_json="",
            account_allocation_fingerprint="",
        )
        state = SimpleNamespace(trades=(active, terminal))

        snapshot = build_shadow_portfolio_snapshot(state, observed_at=NOW)

        self.assertEqual(50.0, snapshot.committed_notional)
        self.assertEqual(decision.evidence.total_risk, snapshot.committed_open_risk)
        self.assertEqual(1, snapshot.open_position_count)
        self.assertEqual(-2.5, snapshot.realized_pnl_today)

    def test_active_trade_without_valid_frozen_allocation_fails_closed(self) -> None:
        active = SimpleNamespace(
            shadow_trade_id="active",
            status="open",
            outcome=None,
            position=SimpleNamespace(quantity=1, average_entry_price=10.0),
            order=None,
            account_allocation_json="",
            account_allocation_fingerprint="",
        )
        with self.assertRaises(AccountAllocationSnapshotError):
            build_shadow_portfolio_snapshot(
                SimpleNamespace(trades=(active,)),
                observed_at=NOW,
            )

    def test_partial_fill_counts_position_and_unfilled_order_commitment(self) -> None:
        decision = build_account_allocation_decision(
            trade_plan_id="plan-1",
            entry_price=10.0,
            stop_price=9.0,
            target_price=12.0,
            policy=policy(),
            context=allocation_context(),
            decision_at=NOW,
        )
        partial = SimpleNamespace(
            shadow_trade_id="partial",
            status="partially_filled",
            outcome=None,
            position=SimpleNamespace(quantity=2, average_entry_price=10.0),
            order=SimpleNamespace(remaining_quantity=3, limit_price=10.0),
            account_allocation_json=json.dumps(asdict(decision), sort_keys=True),
            account_allocation_fingerprint=decision.fingerprint,
        )

        snapshot = build_shadow_portfolio_snapshot(
            SimpleNamespace(trades=(partial,)),
            observed_at=NOW,
        )

        self.assertEqual(50.0, snapshot.committed_notional)
        self.assertEqual(5.0, snapshot.committed_open_risk)
        self.assertEqual(1, snapshot.open_position_count)

    def test_pending_order_occupies_position_limit_before_fill(self) -> None:
        decision = build_account_allocation_decision(
            trade_plan_id="plan-1",
            entry_price=10.0,
            stop_price=9.0,
            target_price=12.0,
            policy=policy(),
            context=allocation_context(),
            decision_at=NOW,
        )
        pending = SimpleNamespace(
            shadow_trade_id="pending",
            status="pending_entry",
            outcome=None,
            position=None,
            order=SimpleNamespace(remaining_quantity=5, limit_price=10.0),
            account_allocation_json=json.dumps(asdict(decision), sort_keys=True),
            account_allocation_fingerprint=decision.fingerprint,
        )

        snapshot = build_shadow_portfolio_snapshot(
            SimpleNamespace(trades=(pending,)),
            observed_at=NOW,
        )

        self.assertEqual(50.0, snapshot.committed_notional)
        self.assertEqual(5.0, snapshot.committed_open_risk)
        self.assertEqual(1, snapshot.open_position_count)

    def test_realized_pnl_uses_central_trading_date(self) -> None:
        observed_at = datetime(2026, 8, 9, 0, 30, tzinfo=timezone.utc)
        terminal = SimpleNamespace(
            shadow_trade_id="closed",
            status="completed",
            outcome=SimpleNamespace(
                executable_pnl=3.0,
                exit_timestamp="2026-08-08T19:15:00-05:00",
            ),
            position=None,
            order=None,
            account_allocation_json="",
            account_allocation_fingerprint="",
        )

        snapshot = build_shadow_portfolio_snapshot(
            SimpleNamespace(trades=(terminal,)),
            observed_at=observed_at,
        )

        self.assertEqual(3.0, snapshot.realized_pnl_today)

    def test_loading_shadow_state_does_not_mutate_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shadow-state.json"
            ShadowStateStore(path).save(ShadowTradingState())
            before = path.read_bytes()

            snapshot = load_shadow_portfolio_snapshot(NOW, state_path=path)

            self.assertEqual(0, snapshot.open_position_count)
            self.assertEqual(before, path.read_bytes())


class AccountPortfolioSnapshotSourceTests(unittest.TestCase):
    def build_source(
        self,
        *,
        discovered: list[DiscoveredSchwabAccount] | None = None,
        snapshot_response: SchwabAccountSnapshotResponse | None = None,
    ) -> tuple[SchwabAccountPortfolioSnapshotSource, StaticSnapshotTransport]:
        discovery = StaticDiscovery(
            discovered
            if discovered is not None
            else [DiscoveredSchwabAccount("2573", ACCOUNT_HASH)]
        )
        transport = StaticSnapshotTransport(snapshot_response or response())
        source = SchwabAccountPortfolioSnapshotSource(
            token_provider=StaticTokenProvider(),
            binding_store=StaticBindingStore(binding()),
            discovery_transport=discovery,
            snapshot_transport=transport,
            portfolio_loader=lambda observed_at: AccountPortfolioSnapshot(
                committed_notional=0.0,
                committed_open_risk=0.0,
                open_position_count=0,
                realized_pnl_today=0.0,
                observed_at=observed_at.isoformat(),
                source=PORTFOLIO_SNAPSHOT_SOURCE,
            ),
        )
        return source, transport

    def test_capture_context_is_redacted_fresh_and_nontransmitting(self) -> None:
        source, transport = self.build_source()

        context = source.capture_context()

        self.assertEqual(1, transport.calls)
        self.assertEqual("2573", context.account_ending)
        self.assertEqual("INDIVIDUAL_CASH", context.account_type)
        self.assertEqual(1, context.authorized_account_count)
        self.assertEqual(100.0, context.cash_available)
        self.assertEqual(PROVIDER_AT.isoformat(), context.provider_timestamp)
        self.assertEqual(NOW.isoformat(), context.receipt_timestamp)
        self.assertEqual(PORTFOLIO_SNAPSHOT_SOURCE, context.portfolio_source)
        self.assertEqual("UNAVAILABLE", context.order_transmission)
        self.assertNotIn(ACCOUNT_HASH, json.dumps(asdict(context)))

    def test_changed_or_multiple_account_stops_before_snapshot_request(self) -> None:
        cases = (
            [DiscoveredSchwabAccount("9999", "other-hash")],
            [
                DiscoveredSchwabAccount("2573", ACCOUNT_HASH),
                DiscoveredSchwabAccount("9999", "other-hash"),
            ],
        )
        for discovered in cases:
            source, transport = self.build_source(discovered=discovered)
            with self.subTest(discovered=discovered):
                with self.assertRaises(AccountAllocationBrokerageAnomaly) as caught:
                    source.capture_context()
                self.assertEqual(0, transport.calls)
                self.assertNotIn(ACCOUNT_HASH, str(caught.exception))

    def test_unexpected_broker_position_blocks_context(self) -> None:
        payload = account_payload(
            positions=[
                {
                    "longQuantity": 1.0,
                    "shortQuantity": 0.0,
                    "averagePrice": 10.0,
                    "marketValue": 10.0,
                    "instrument": {"symbol": "TEST"},
                }
            ]
        )
        source, _ = self.build_source(snapshot_response=response(payload=payload))

        with self.assertRaises(AccountAllocationBrokerageAnomaly):
            source.capture_context()

    def test_fresh_allocation_source_captures_again_for_every_decision(self) -> None:
        context_source = CountingContextSource(allocation_context())
        source = FreshAccountAllocationSource(
            policy=policy(),
            snapshot_source=context_source,
        )

        first = source.allocate(
            symbol="TEST",
            trade_plan_id="plan-1",
            entry_price=10.0,
            stop_price=9.0,
            target_price=12.0,
            decision_at=NOW,
        )
        second = source.allocate(
            symbol="TEST",
            trade_plan_id="plan-1",
            entry_price=10.0,
            stop_price=9.0,
            target_price=12.0,
            decision_at=NOW,
        )

        self.assertEqual(2, context_source.calls)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertTrue(first.evidence.authorized)
        self.assertEqual(5, first.evidence.quantity)

    def test_module_exposes_no_order_or_transmission_method(self) -> None:
        source = Path(__file__).parents[1] / "momentum_hunter" / "account_allocation_snapshot.py"
        text = source.read_text(encoding="utf-8")
        for forbidden in (
            "submit_order",
            "cancel_order",
            "replace_order",
            "list_orders",
            "get_order_status",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
