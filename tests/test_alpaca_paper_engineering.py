from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from momentum_hunter.alpaca_paper_broker import (
    ALPACA_PAPER_BASE_URL,
    PAPER_ENGINEERING_CONFIRMATION,
    AlpacaPaperAsset,
    AlpacaPaperBrokerError,
    AlpacaPaperOrder,
    AlpacaPaperOrderRequest,
    AlpacaPaperPosition,
    AlpacaPaperProviderReceipt,
    PaperOrderResolution,
    PaperOrderResolutionState,
    authorize_paper_engineering_order,
)
from momentum_hunter.alpaca_paper_engineering import (
    NO_TRADE,
    PAPER_ENGINEERING_DECISION_CONFIRMATION,
    PAPER_ENGINEERING_ROLLOVER_CONFIRMATION,
    PAPER_ENGINEERING_SAMPLE_CONFIRMATION,
    PAPER_TRADE_CREATED,
    AlpacaPaperEngineeringEngine,
    PaperEngineeringAnomaly,
    PaperEngineeringError,
    PaperEngineeringPolicy,
    _exclusive_paper_session,
    freeze_paper_engineering_sample,
    load_paper_engineering_policy,
    rollover_invalidated_paper_engineering_sample,
)
from momentum_hunter.alpaca_paper_onboarding import AlpacaPaperAccount
from momentum_hunter.broker_capabilities import (
    CAPABILITY_FRACTIONAL_MARKET,
    CAPABILITY_FRACTIONAL_PRECISION,
    CAPABILITY_FRACTIONAL_QUANTITY,
    BrokerCapability,
    BrokerCapabilityRegistry,
    CapabilityState,
)
from momentum_hunter.paper_risk_governor import (
    PaperRiskPolicy,
    evaluate_paper_candidate,
)
from momentum_hunter.provider_neutral_allocation import (
    ProviderNeutralAllocationPolicy,
    evidence_fingerprint,
)
from momentum_hunter.schwab_market_data import (
    SCHWAB_QUOTE_SOURCE,
    SchwabQuoteEvidenceBatch,
)
from momentum_hunter.shadow_opening import build_https_clock_skew_proof
from tests.test_shadow_trading import bind_setup_identity, report_payload


DECISION_AT = datetime.fromisoformat("2026-07-23T10:00:00-05:00")


def registry() -> BrokerCapabilityRegistry:
    return BrokerCapabilityRegistry.build(
        provider="ALPACA_TRADING_API",
        environment="PAPER_ONLY",
        capabilities=(
            BrokerCapability(
                CAPABILITY_FRACTIONAL_QUANTITY,
                CapabilityState.PROVEN,
                "true",
                ("synthetic A003 evidence",),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_PRECISION,
                CapabilityState.PROVEN,
                "0.00000001",
                ("synthetic A003 evidence",),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_MARKET,
                CapabilityState.PROVEN,
                "day",
                ("synthetic A003 evidence",),
            ),
        ),
    )


def policy() -> PaperEngineeringPolicy:
    return PaperEngineeringPolicy(
        policy_id="alpaca-paper-engineering-policy-test-v1",
        sample_id="alpaca-paper-engineering-test-v1",
        allocation=ProviderNeutralAllocationPolicy(
            policy_id="alpaca-paper-allocation-test-v1",
            fixed_unit_risk_dollars=Decimal("2"),
            max_position_notional_dollars=Decimal("95"),
            minimum_cash_reserve_dollars=Decimal("5"),
            max_total_open_risk_dollars=Decimal("2"),
            daily_loss_limit_dollars=Decimal("4"),
            max_open_positions=1,
            max_snapshot_age_seconds=30,
        ),
        risk=PaperRiskPolicy(
            policy_id="alpaca-paper-risk-test-v1",
            maximum_spread_percent=Decimal("3"),
            maximum_entry_extension_percent=Decimal("0.25"),
            minimum_reward_risk=Decimal("1.5"),
        ),
        entry_notional_buffer_percent=Decimal("1"),
        minimum_entry_notional_dollars=Decimal("1"),
        order_poll_attempts=2,
        order_poll_interval_seconds=0,
    )


def eligible_report(*, rows: bool = True) -> dict:
    payload = report_payload()
    payload["metadata"]["source_capture_time"] = (
        DECISION_AT - timedelta(minutes=2)
    ).isoformat()
    payload["metadata"]["generated_at"] = (
        DECISION_AT - timedelta(seconds=30)
    ).isoformat()
    if not rows:
        payload["candidates"] = []
        payload["top_5_for_capital"] = []
        return payload
    row = payload["candidates"][0]
    row["candidate_id"] = "candidate-test-1"
    row["trade_plan"]["bullish_target_1"] = 11.0
    row["trade_plan"]["bullish_target_2"] = 11.5
    row["trade_plan"]["risk_reward_ratio"] = 2.0
    bind_setup_identity(
        row,
        created_at=DECISION_AT - timedelta(minutes=1),
    )
    payload["top_5_for_capital"] = [copy.deepcopy(row)]
    return payload


def quote_result(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "symbol": "TEST",
        "status": "PASS",
        "findings": [],
        "timestamp": (DECISION_AT - timedelta(seconds=1)).isoformat(),
        "providerQuoteTimestamp": (DECISION_AT - timedelta(seconds=1)).isoformat(),
        "providerBidTimestamp": (DECISION_AT - timedelta(seconds=1)).isoformat(),
        "providerAskTimestamp": (DECISION_AT - timedelta(seconds=1)).isoformat(),
        "quoteAgeSeconds": 1.0,
        "bid": 10.0,
        "ask": 10.01,
        "last": 10.0,
        "session": "regular",
        "tradingState": "tradable",
        "realtime": True,
        "securityStatus": "Normal",
        "source": SCHWAB_QUOTE_SOURCE,
    }
    value.update(changes)
    return value


class SyntheticQuoteSource:
    def __init__(self, values: dict[str, dict[str, object]]) -> None:
        self.values = values
        self.calls: list[tuple[str, ...]] = []

    def quotes_with_clock(self, symbols, *, decision_at=None):
        self.calls.append(tuple(symbols))
        clock_at = decision_at or DECISION_AT
        return SchwabQuoteEvidenceBatch(
            quotes={
                symbol: {
                    "symbol": symbol,
                    "timestamp": self.values[symbol]["timestamp"],
                    "provider_quote_timestamp": self.values[symbol]["providerQuoteTimestamp"],
                    "provider_bid_timestamp": self.values[symbol]["providerBidTimestamp"],
                    "provider_ask_timestamp": self.values[symbol]["providerAskTimestamp"],
                    "bid": self.values[symbol]["bid"],
                    "ask": self.values[symbol]["ask"],
                    "last": self.values[symbol]["last"],
                    "volume": 1000,
                    "session": "regular",
                    "trading_state": "tradable",
                    "source": SCHWAB_QUOTE_SOURCE,
                    "realtime": True,
                    "security_status": "Normal",
                }
                for symbol in symbols
            },
            clock_skew_proof=build_https_clock_skew_proof(
                request_started_at=clock_at,
                response_received_at=clock_at,
                remote_date_header=format_datetime(clock_at),
                source_identity="synthetic-paper-clock",
            ),
        )


class SequenceClock:
    def __init__(self, *values: datetime) -> None:
        self.values = list(values)
        self.last = values[-1]

    def __call__(self) -> datetime:
        if self.values:
            self.last = self.values.pop(0)
        return self.last


class SequenceQuoteSource(SyntheticQuoteSource):
    def __init__(self, snapshots: list[dict[str, dict[str, object]]]) -> None:
        super().__init__(snapshots[0])
        self.snapshots = snapshots

    def quotes_with_clock(self, symbols, *, decision_at=None):
        self.values = self.snapshots[min(len(self.calls), len(self.snapshots) - 1)]
        return super().quotes_with_clock(symbols, decision_at=decision_at)


class BindingRepository:
    def binding_fingerprint(self) -> str:
        return "B" * 64


class SyntheticAdapter:
    def __init__(self) -> None:
        self.evidence_sink = None
        self.credentials = BindingRepository()
        self.positions: list[AlpacaPaperPosition] = []
        self.orders: dict[str, AlpacaPaperOrder] = {}
        self.calls: list[str] = []
        self.fail_asset_once = False
        self.interrupt_before_stop_once = False
        self.entry_fills = True
        self.entry_fill_price = Decimal("10")
        self.stop_fails = False
        self.stop_response_quantity: Decimal | None = None
        self.market_exit_fraction = Decimal("1")
        self.account_override: AlpacaPaperAccount | None = None
        self.account_receipt_payload: object = {"status": "ACTIVE"}

    def _receipt(self, method: str, path: str, payload: object = None) -> None:
        self.calls.append(f"{method} {path}")
        if self.evidence_sink:
            self.evidence_sink(
                AlpacaPaperProviderReceipt(
                    method=method,
                    path=path,
                    http_status=200,
                    request_id="request-id",
                    request_id_present=True,
                    received_at=(DECISION_AT - timedelta(milliseconds=100)).isoformat(),
                    payload=payload,
                )
            )

    def get_account(self) -> AlpacaPaperAccount:
        self._receipt("GET", "/v2/account", self.account_receipt_payload)
        return self.account_override or AlpacaPaperAccount(
            status="ACTIVE",
            cash=Decimal("100"),
            buying_power=Decimal("100"),
            account_blocked=False,
            trading_blocked=False,
            trade_suspended_by_user=False,
            equity=Decimal("100"),
            last_equity=Decimal("100"),
        )

    def get_asset(self, symbol: str) -> AlpacaPaperAsset:
        if self.fail_asset_once:
            self.fail_asset_once = False
            raise RuntimeError("synthetic interruption before entry submission")
        self._receipt("GET", f"/v2/assets/{symbol}")
        return AlpacaPaperAsset(
            symbol=symbol,
            asset_class="us_equity",
            exchange="NYSE",
            status="active",
            tradable=True,
            fractionable=True,
            marginable=False,
            shortable=False,
            easy_to_borrow=False,
            attributes=(),
            request_id_present=True,
        )

    def list_positions(self) -> list[AlpacaPaperPosition]:
        self._receipt("GET", "/v2/positions")
        return list(self.positions)

    def list_orders(self, *, status="open", symbols=()):
        self._receipt("GET", "/v2/orders")
        values = list(self.orders.values())
        if status == "open":
            values = [item for item in values if not item.terminal]
        if symbols:
            values = [item for item in values if item.symbol in symbols]
        return values

    def get_order(self, order_id: str) -> AlpacaPaperOrder:
        self._receipt("GET", f"/v2/orders/{order_id}")
        return self.orders[order_id]

    def try_get_order_by_client_id(self, client_order_id: str):
        return next(
            (item for item in self.orders.values() if item.client_order_id == client_order_id),
            None,
        )

    def submit_order_idempotently(self, request: AlpacaPaperOrderRequest, *, authorization):
        authorization.validate(request)
        existing = self.try_get_order_by_client_id(request.client_order_id)
        if existing:
            return PaperOrderResolution(PaperOrderResolutionState.RECOVERED, existing)
        if request.order_type == "stop" and self.interrupt_before_stop_once:
            self.interrupt_before_stop_once = False
            raise RuntimeError("synthetic interruption before stop submission")
        if request.order_type == "stop" and self.stop_fails:
            raise AlpacaPaperBrokerError("synthetic stop rejection")
        self._receipt("POST", "/v2/orders")
        if request.side == "buy":
            quantity = (
                (request.notional or Decimal("0")) / self.entry_fill_price
            ).quantize(Decimal("0.000000001"), rounding=ROUND_FLOOR)
            status = "filled" if self.entry_fills else "new"
            filled = quantity if self.entry_fills else Decimal("0")
            average = self.entry_fill_price if self.entry_fills else None
            if self.entry_fills:
                self.positions = [
                    AlpacaPaperPosition(
                        symbol=request.symbol,
                        quantity=quantity,
                        side="long",
                        average_entry_price=average,
                        market_value=quantity * average,
                        current_price=average,
                    )
                ]
        elif request.order_type == "market":
            quantity = request.quantity or Decimal("0")
            filled_quantity = (quantity * self.market_exit_fraction).quantize(
                Decimal("0.000000001"),
                rounding=ROUND_FLOOR,
            )
            status = "filled"
            filled = filled_quantity
            average = Decimal("10")
            remaining = (quantity - filled_quantity).quantize(
                Decimal("0.000000001"),
                rounding=ROUND_FLOOR,
            )
            if remaining > 0:
                self.positions = [
                    AlpacaPaperPosition(
                        symbol=request.symbol,
                        quantity=remaining,
                        side="long",
                        average_entry_price=Decimal("10"),
                        market_value=remaining * Decimal("10"),
                        current_price=Decimal("10"),
                    )
                ]
            else:
                self.positions = []
        else:
            quantity = (
                self.stop_response_quantity
                if request.order_type == "stop"
                and self.stop_response_quantity is not None
                else request.quantity or Decimal("0")
            )
            status = "new"
            filled = Decimal("0")
            average = None
        order = order_value(
            str(len(self.orders) + 1).zfill(32),
            request,
            status=status,
            filled=filled,
            average=average,
            quantity=quantity,
        )
        self.orders[order.order_id] = order
        return PaperOrderResolution(PaperOrderResolutionState.SUBMITTED, order)

    def cancel_order(self, order_id: str, *, authorization):
        current = self.orders[order_id]
        request = AlpacaPaperOrderRequest(
            symbol=current.symbol,
            side=current.side,
            order_type=current.order_type,
            time_in_force=current.time_in_force,
            client_order_id=current.client_order_id,
            quantity=current.quantity,
            notional=current.notional,
            limit_price=current.limit_price,
            stop_price=current.stop_price,
        )
        authorization.validate(request)
        self._receipt("DELETE", f"/v2/orders/{order_id}")
        canceled = AlpacaPaperOrder(
            **{
                **current.__dict__,
                "status": "canceled",
                "canceled_at": DECISION_AT.isoformat(),
            }
        )
        self.orders[order_id] = canceled
        return canceled


def order_value(
    order_id: str,
    request: AlpacaPaperOrderRequest,
    *,
    status: str,
    filled: Decimal,
    average: Decimal | None,
    quantity: Decimal,
) -> AlpacaPaperOrder:
    return AlpacaPaperOrder(
        order_id=order_id,
        client_order_id=request.client_order_id,
        symbol=request.symbol,
        asset_class="us_equity",
        side=request.side,
        order_type=request.order_type,
        order_class="simple",
        time_in_force="day",
        status=status,
        quantity=quantity if request.quantity is not None else None,
        notional=request.notional,
        filled_quantity=filled,
        filled_average_price=average,
        limit_price=request.limit_price,
        stop_price=request.stop_price,
        submitted_at=DECISION_AT.isoformat(),
        updated_at=DECISION_AT.isoformat(),
        filled_at=DECISION_AT.isoformat() if status == "filled" else None,
        canceled_at=None,
        replaced_at=None,
        replaced_by=None,
        replaces=None,
        request_id_present=True,
    )


class AlpacaPaperEngineeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.lifecycle = self.root / "lifecycle-final.json"
        self.lifecycle.write_text(json.dumps({"fingerprint": "A" * 64}), encoding="utf-8")
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            freeze_paper_engineering_sample(
                policy=policy(),
                lifecycle_proof_path=self.lifecycle,
                output_directory=self.root / "paper",
                confirmation=PAPER_ENGINEERING_SAMPLE_CONFIRMATION,
                activated_at=DECISION_AT - timedelta(minutes=5),
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def engine(self, adapter: SyntheticAdapter | None = None):
        return AlpacaPaperEngineeringEngine(
            adapter=adapter or SyntheticAdapter(),
            quote_source=SyntheticQuoteSource({"TEST": quote_result()}),
            output_directory=self.root / "paper",
            clock=lambda: DECISION_AT,
            sleep=lambda _seconds: None,
        )

    def write_report(self, payload: dict) -> Path:
        path = self.root / "report.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def run_case(self, payload: dict, adapter: SyntheticAdapter | None = None):
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            return self.engine(adapter).run_decision(
                self.write_report(payload),
                confirmation=PAPER_ENGINEERING_DECISION_CONFIRMATION,
            )

    def test_no_candidate_is_terminal_without_provider_call(self) -> None:
        adapter = SyntheticAdapter()
        result = self.run_case(eligible_report(rows=False), adapter)

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertIn("PAPER_NO_CANDIDATES_IN_PROSPECTIVE_REPORT", result["reasons"])
        self.assertEqual([], adapter.calls)
        self.assertFalse(result["paperOrderCreated"])

    def test_decision_clock_freezes_after_fresh_quote_and_account_evidence(self) -> None:
        quote_at = DECISION_AT + timedelta(seconds=1, milliseconds=500)
        quote = quote_result(
            bid=9.98,
            ask=9.99,
            last=9.99,
            timestamp=quote_at.isoformat(),
            providerQuoteTimestamp=quote_at.isoformat(),
            providerBidTimestamp=quote_at.isoformat(),
            providerAskTimestamp=quote_at.isoformat(),
            quoteAgeSeconds=0.5,
        )
        clock = SequenceClock(
            DECISION_AT,
            DECISION_AT + timedelta(seconds=1),
            DECISION_AT + timedelta(seconds=2),
            DECISION_AT + timedelta(seconds=3),
        )
        engine = AlpacaPaperEngineeringEngine(
            adapter=SyntheticAdapter(),
            quote_source=SyntheticQuoteSource({"TEST": quote}),
            output_directory=self.root / "paper",
            clock=clock,
            sleep=lambda _seconds: None,
        )

        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            result = engine.run_decision(
                self.write_report(eligible_report()),
                confirmation=PAPER_ENGINEERING_DECISION_CONFIRMATION,
            )

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertEqual(DECISION_AT.isoformat(), result["decisionStartedAt"])
        self.assertEqual(
            (DECISION_AT + timedelta(seconds=3)).isoformat(),
            result["decisionAt"],
        )
        self.assertEqual(
            (DECISION_AT + timedelta(seconds=1)).isoformat(),
            result["quoteProof"]["requestedAt"],
        )
        blockers = result["candidateEvaluations"][0]["blockers"]
        self.assertNotIn("PAPER_QUOTE_TIMESTAMP_INVALID", blockers)
        self.assertIn("PAPER_ENTRY_TRIGGER_NOT_REACHED", blockers)

    def test_opening_candle_timeout_stops_before_quote_or_account(self) -> None:
        payload = eligible_report()
        payload["metadata"]["opening_candle_readiness"] = {
            "status": "CANONICAL_CANDLE_READINESS_TIMEOUT"
        }
        adapter = SyntheticAdapter()

        result = self.run_case(payload, adapter)

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertIn("CANONICAL_CANDLE_READINESS_TIMEOUT", result["reasons"])
        self.assertEqual([], adapter.calls)
        self.assertFalse(result["paperOrderCreated"])

    def test_report_that_ages_out_during_evidence_collection_cannot_trade(self) -> None:
        adapter = SyntheticAdapter()
        clock = SequenceClock(
            DECISION_AT,
            DECISION_AT + timedelta(seconds=1),
            DECISION_AT + timedelta(seconds=2),
            DECISION_AT + timedelta(seconds=62),
        )
        engine = AlpacaPaperEngineeringEngine(
            adapter=adapter,
            quote_source=SyntheticQuoteSource({"TEST": quote_result()}),
            output_directory=self.root / "paper",
            clock=clock,
            sleep=lambda _seconds: None,
        )

        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            result = engine.run_decision(
                self.write_report(eligible_report()),
                confirmation=PAPER_ENGINEERING_DECISION_CONFIRMATION,
            )

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertTrue(
            any("report-to-selection" in reason.lower() for reason in result["reasons"]),
            result["reasons"],
        )
        self.assertTrue(any(call == "GET /v2/account" for call in adapter.calls))
        self.assertFalse(any(call.startswith("POST ") for call in adapter.calls))

    def test_invalidated_no_order_sample_rolls_to_v2_without_policy_change(self) -> None:
        adapter = SyntheticAdapter()
        original = load_paper_engineering_policy(self.root / "paper")
        decision = self.run_case(eligible_report(rows=False), adapter)
        decision_path = (
            self.root / "paper" / "decisions" / f"{decision['decisionCycleId']}.json"
        )
        decision_bytes = decision_path.read_bytes()
        adjudication = {
            "schemaVersion": 1,
            "classification": "SYSTEM_DATA_CONTRACT_FAILURE",
            "decisionState": "DECISION_NOT_REACHED",
            "cases": [
                {
                    "paperDecisions": [
                        {
                            "decisionCycleId": decision["decisionCycleId"],
                            "sampleId": original.sample_id,
                            "originalFingerprint": decision["fingerprint"],
                        }
                    ]
                }
            ],
        }
        adjudication["fingerprint"] = evidence_fingerprint(adjudication)
        adjudication_path = self.root / "adjudication.json"
        adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")

        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            result = rollover_invalidated_paper_engineering_sample(
                expected_sample_id=original.sample_id,
                new_sample_id="alpaca-paper-engineering-20260813-v2",
                new_identity_date="20260813",
                adjudication_path=adjudication_path,
                confirmation=PAPER_ENGINEERING_ROLLOVER_CONFIRMATION,
                output_directory=self.root / "paper",
                archive_root=self.root / "archive",
                closed_at=DECISION_AT,
            )

        archived = self.root / "archive" / original.sample_id
        replacement = load_paper_engineering_policy(self.root / "paper")
        self.assertEqual("PAPER_ENGINEERING_SAMPLE_ROLLED_OVER", result["classification"])
        self.assertEqual(
            decision_bytes,
            (archived / "decisions" / decision_path.name).read_bytes(),
        )
        closure = json.loads((archived / "sample-closure.json").read_text())
        self.assertEqual(
            "CLOSED_INVALIDATED_SYSTEM_DATA_CONTRACT_FAILURE",
            closure["classification"],
        )
        self.assertIn("policy.json", {item["path"] for item in closure["sourceFiles"]})
        self.assertIn(
            f"decisions/{decision_path.name}",
            {item["path"] for item in closure["sourceFiles"]},
        )
        self.assertEqual("alpaca-paper-engineering-20260813-v2", replacement.sample_id)
        self.assertEqual(
            original.allocation.fixed_unit_risk_dollars,
            replacement.allocation.fixed_unit_risk_dollars,
        )
        self.assertEqual(
            original.risk.maximum_spread_percent,
            replacement.risk.maximum_spread_percent,
        )
        self.assertFalse(result["policyValuesChanged"])
        self.assertEqual([], adapter.calls)

    def test_rollover_rejects_any_entry_intent(self) -> None:
        original = load_paper_engineering_policy(self.root / "paper")
        decision = self.run_case(eligible_report(rows=False))
        intent = self.root / "paper" / "intents" / "unsafe.json"
        intent.parent.mkdir(parents=True)
        intent.write_text("{}", encoding="utf-8")
        adjudication = {
            "classification": "SYSTEM_DATA_CONTRACT_FAILURE",
            "decisionState": "DECISION_NOT_REACHED",
            "cases": [
                {
                    "paperDecisions": [
                        {
                            "decisionCycleId": decision["decisionCycleId"],
                            "sampleId": original.sample_id,
                            "originalFingerprint": decision["fingerprint"],
                        }
                    ]
                }
            ],
        }
        adjudication["fingerprint"] = evidence_fingerprint(adjudication)
        adjudication_path = self.root / "adjudication.json"
        adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")

        with (
            patch(
                "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
                return_value=registry(),
            ),
            self.assertRaisesRegex(PaperEngineeringAnomaly, "entry intent"),
        ):
            rollover_invalidated_paper_engineering_sample(
                expected_sample_id=original.sample_id,
                new_sample_id="alpaca-paper-engineering-20260813-v2",
                new_identity_date="20260813",
                adjudication_path=adjudication_path,
                confirmation=PAPER_ENGINEERING_ROLLOVER_CONFIRMATION,
                output_directory=self.root / "paper",
                archive_root=self.root / "archive",
                closed_at=DECISION_AT,
            )

    def test_rollover_archive_conflict_does_not_modify_active_sample(self) -> None:
        original = load_paper_engineering_policy(self.root / "paper")
        decision = self.run_case(eligible_report(rows=False))
        before = {
            path.relative_to(self.root / "paper"): path.read_bytes()
            for path in (self.root / "paper").rglob("*")
            if path.is_file()
        }
        adjudication = {
            "classification": "SYSTEM_DATA_CONTRACT_FAILURE",
            "decisionState": "DECISION_NOT_REACHED",
            "cases": [
                {
                    "paperDecisions": [
                        {
                            "decisionCycleId": decision["decisionCycleId"],
                            "sampleId": original.sample_id,
                            "originalFingerprint": decision["fingerprint"],
                        }
                    ]
                }
            ],
        }
        adjudication["fingerprint"] = evidence_fingerprint(adjudication)
        adjudication_path = self.root / "adjudication.json"
        adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")
        archive = self.root / "archive" / original.sample_id
        archive.mkdir(parents=True)

        with (
            patch(
                "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
                return_value=registry(),
            ),
            self.assertRaisesRegex(PaperEngineeringAnomaly, "archive already exists"),
        ):
            rollover_invalidated_paper_engineering_sample(
                expected_sample_id=original.sample_id,
                new_sample_id="alpaca-paper-engineering-20260813-v2",
                new_identity_date="20260813",
                adjudication_path=adjudication_path,
                confirmation=PAPER_ENGINEERING_ROLLOVER_CONFIRMATION,
                output_directory=self.root / "paper",
                archive_root=self.root / "archive",
                closed_at=DECISION_AT,
            )

        after = {
            path.relative_to(self.root / "paper"): path.read_bytes()
            for path in (self.root / "paper").rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse((self.root / "paper" / "sample-closure.json").exists())

    def test_rollover_rejects_adjudication_for_another_decision(self) -> None:
        original = load_paper_engineering_policy(self.root / "paper")
        self.run_case(eligible_report(rows=False))
        adjudication = {
            "classification": "SYSTEM_DATA_CONTRACT_FAILURE",
            "decisionState": "DECISION_NOT_REACHED",
            "cases": [
                {
                    "paperDecisions": [
                        {
                            "decisionCycleId": "paper-cycle-unrelated",
                            "sampleId": original.sample_id,
                            "originalFingerprint": "A" * 64,
                        }
                    ]
                }
            ],
        }
        adjudication["fingerprint"] = evidence_fingerprint(adjudication)
        adjudication_path = self.root / "adjudication.json"
        adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")

        with (
            patch(
                "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
                return_value=registry(),
            ),
            self.assertRaisesRegex(PaperEngineeringError, "exact active Paper decisions"),
        ):
            rollover_invalidated_paper_engineering_sample(
                expected_sample_id=original.sample_id,
                new_sample_id="alpaca-paper-engineering-20260813-v2",
                new_identity_date="20260813",
                adjudication_path=adjudication_path,
                confirmation=PAPER_ENGINEERING_ROLLOVER_CONFIRMATION,
                output_directory=self.root / "paper",
                archive_root=self.root / "archive",
                closed_at=DECISION_AT,
            )

        self.assertEqual(original, load_paper_engineering_policy(self.root / "paper"))
        self.assertFalse((self.root / "paper" / "sample-closure.json").exists())

    def test_rollover_restores_original_sample_when_activation_move_fails(self) -> None:
        original = load_paper_engineering_policy(self.root / "paper")
        decision = self.run_case(eligible_report(rows=False))
        before = {
            path.relative_to(self.root / "paper"): path.read_bytes()
            for path in (self.root / "paper").rglob("*")
            if path.is_file()
        }
        adjudication = {
            "classification": "SYSTEM_DATA_CONTRACT_FAILURE",
            "decisionState": "DECISION_NOT_REACHED",
            "cases": [
                {
                    "paperDecisions": [
                        {
                            "decisionCycleId": decision["decisionCycleId"],
                            "sampleId": original.sample_id,
                            "originalFingerprint": decision["fingerprint"],
                        }
                    ]
                }
            ],
        }
        adjudication["fingerprint"] = evidence_fingerprint(adjudication)
        adjudication_path = self.root / "adjudication.json"
        adjudication_path.write_text(json.dumps(adjudication), encoding="utf-8")
        real_replace = os.replace
        calls = 0

        def fail_activation(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic activation failure")
            return real_replace(source, destination)

        with (
            patch(
                "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
                return_value=registry(),
            ),
            patch(
                "momentum_hunter.alpaca_paper_engineering.os.replace",
                side_effect=fail_activation,
            ),
            self.assertRaisesRegex(PaperEngineeringError, "original sample was restored"),
        ):
            rollover_invalidated_paper_engineering_sample(
                expected_sample_id=original.sample_id,
                new_sample_id="alpaca-paper-engineering-20260813-v2",
                new_identity_date="20260813",
                adjudication_path=adjudication_path,
                confirmation=PAPER_ENGINEERING_ROLLOVER_CONFIRMATION,
                output_directory=self.root / "paper",
                archive_root=self.root / "archive",
                closed_at=DECISION_AT,
            )

        after = {
            path.relative_to(self.root / "paper"): path.read_bytes()
            for path in (self.root / "paper").rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertFalse((self.root / "archive" / original.sample_id).exists())
        self.assertFalse(
            (self.root / "paper-alpaca-paper-engineering-20260813-v2-staging").exists()
        )

    def test_authorized_candidate_creates_fractional_entry_and_stop(self) -> None:
        adapter = SyntheticAdapter()
        result = self.run_case(eligible_report(), adapter)

        self.assertEqual(PAPER_TRADE_CREATED, result["classification"])
        self.assertEqual("TEST", result["selectedSymbol"])
        self.assertTrue(result["paperOrderCreated"])
        self.assertTrue(result["positionProtected"])
        self.assertFalse(result["positionFlat"])
        self.assertEqual("filled", result["entryOrder"]["status"])
        self.assertEqual("new", result["protectiveStopOrder"]["status"])
        self.assertEqual("PASS", result["postFillRisk"]["status"])
        self.assertLessEqual(
            Decimal(result["postFillRisk"]["actualDollarRisk"]),
            Decimal(result["postFillRisk"]["maximumUnitRisk"]),
        )
        self.assertGreaterEqual(
            Decimal(result["postFillRisk"]["actualRewardRisk"]),
            Decimal(result["postFillRisk"]["minimumRewardRisk"]),
        )
        self.assertLessEqual(
            Decimal(result["postFillRisk"]["entryExtensionPercent"]),
            Decimal(result["postFillRisk"]["maximumEntryExtensionPercent"]),
        )
        self.assertEqual(
            result["postFillRisk"]["confirmedPositionQuantity"],
            result["protectiveStopOrder"]["quantity"],
        )
        self.assertNotIn("https://api.alpaca.markets", json.dumps(result))
        self.assertFalse(any("https://api.alpaca.markets" in value for value in adapter.calls))

    def test_exact_duplicate_returns_same_final_without_second_order(self) -> None:
        adapter = SyntheticAdapter()
        first = self.run_case(eligible_report(), adapter)
        calls = list(adapter.calls)
        second = self.run_case(eligible_report(), adapter)

        self.assertEqual(first, second)
        self.assertEqual(calls, adapter.calls)

    def test_restart_before_submission_closes_as_no_trade_without_late_entry(self) -> None:
        adapter = SyntheticAdapter()
        adapter.fail_asset_once = True
        payload = eligible_report()
        with self.assertRaisesRegex(RuntimeError, "before entry submission"):
            self.run_case(payload, adapter)

        result = self.run_case(payload, adapter)

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertEqual(["PAPER_RECOVERY_UNSUBMITTED_INTENT"], result["reasons"])
        self.assertTrue(result["recoveredAfterInterruption"])
        self.assertFalse(result["paperOrderCreated"])
        self.assertFalse(any(call == "POST /v2/orders" for call in adapter.calls))

    def test_restart_after_entry_fill_installs_stop_and_recovers_trade(self) -> None:
        adapter = SyntheticAdapter()
        adapter.interrupt_before_stop_once = True
        payload = eligible_report()
        with self.assertRaisesRegex(RuntimeError, "before stop submission"):
            self.run_case(payload, adapter)
        self.assertEqual(1, len(adapter.positions))
        self.assertEqual(1, len(adapter.orders))

        result = self.run_case(payload, adapter)

        self.assertEqual(PAPER_TRADE_CREATED, result["classification"])
        self.assertEqual(["PAPER_RECOVERED_AFTER_INTERRUPTION"], result["reasons"])
        self.assertTrue(result["recoveredAfterInterruption"])
        self.assertTrue(result["positionProtected"])
        self.assertEqual(2, len(adapter.orders))

    def test_restart_after_active_record_reuses_owned_stop(self) -> None:
        adapter = SyntheticAdapter()
        payload = eligible_report()
        engine = self.engine(adapter)
        original_write = engine._write_final

        def interrupt_final(path, record):
            if record.get("classification") == PAPER_TRADE_CREATED:
                raise RuntimeError("synthetic interruption after active evidence")
            return original_write(path, record)

        engine._write_final = interrupt_final
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ), self.assertRaisesRegex(RuntimeError, "after active evidence"):
            engine.run_decision(
                self.write_report(payload),
                confirmation=PAPER_ENGINEERING_DECISION_CONFIRMATION,
            )
        self.assertEqual(2, len(adapter.orders))

        result = self.run_case(payload, adapter)

        self.assertEqual(PAPER_TRADE_CREATED, result["classification"])
        self.assertTrue(result["recoveredAfterInterruption"])
        self.assertEqual(2, len(adapter.orders))

    def test_recovery_rejects_unrelated_open_order(self) -> None:
        adapter = SyntheticAdapter()
        adapter.fail_asset_once = True
        payload = eligible_report()
        with self.assertRaises(RuntimeError):
            self.run_case(payload, adapter)
        request = AlpacaPaperOrderRequest(
            symbol="SPY",
            side="buy",
            order_type="limit",
            time_in_force="day",
            client_order_id="unrelated-paper-order",
            quantity=Decimal("1"),
            limit_price=Decimal("1"),
        )
        unrelated = order_value(
            "9" * 32,
            request,
            status="new",
            filled=Decimal("0"),
            average=None,
            quantity=Decimal("1"),
        )
        adapter.orders[unrelated.order_id] = unrelated

        with self.assertRaisesRegex(PaperEngineeringAnomaly, "unrelated open order"):
            self.run_case(payload, adapter)

    def test_stale_report_fails_before_quote_or_account(self) -> None:
        payload = eligible_report()
        payload["metadata"]["generated_at"] = (DECISION_AT - timedelta(minutes=20)).isoformat()
        adapter = SyntheticAdapter()
        result = self.run_case(payload, adapter)

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertTrue(any("stale" in reason.lower() for reason in result["reasons"]))
        self.assertEqual([], adapter.calls)

    def test_unusable_account_blocks_before_asset_or_order(self) -> None:
        adapter = SyntheticAdapter()
        adapter.account_override = AlpacaPaperAccount(
            status="ACCOUNT_BLOCKED",
            cash=Decimal("100"),
            buying_power=Decimal("100"),
            account_blocked=True,
            trading_blocked=True,
            trade_suspended_by_user=False,
            equity=Decimal("100"),
            last_equity=Decimal("100"),
        )

        result = self.run_case(eligible_report(), adapter)

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertIn("PAPER_ACCOUNT_PREFLIGHT_FAILED:PaperEngineeringAnomaly", result["reasons"])
        self.assertFalse(any(call.startswith("POST ") for call in adapter.calls))

    def test_missing_daily_loss_evidence_blocks_allocation(self) -> None:
        adapter = SyntheticAdapter()
        adapter.account_override = AlpacaPaperAccount(
            status="ACTIVE",
            cash=Decimal("100"),
            buying_power=Decimal("100"),
            account_blocked=False,
            trading_blocked=False,
            trade_suspended_by_user=False,
            equity=None,
            last_equity=None,
        )

        result = self.run_case(eligible_report(), adapter)

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertFalse(any(call.startswith("POST ") for call in adapter.calls))
        self.assertTrue(
            any("ALLOCATION_REALIZED_PNL_INVALID" in reason for reason in result["reasons"]),
            result["reasons"],
        )

    def test_unfilled_entry_is_terminal_no_trade_and_flat(self) -> None:
        adapter = SyntheticAdapter()
        adapter.entry_fills = False

        result = self.run_case(eligible_report(), adapter)

        self.assertEqual(NO_TRADE, result["classification"])
        self.assertEqual(["PAPER_ENTRY_UNFILLED"], result["reasons"])
        self.assertEqual("canceled", result["entryOrder"]["status"])
        self.assertEqual([], adapter.positions)

    def test_stop_failure_emergency_flattens_owned_position(self) -> None:
        adapter = SyntheticAdapter()
        adapter.stop_fails = True

        result = self.run_case(eligible_report(), adapter)

        self.assertEqual(PAPER_TRADE_CREATED, result["classification"])
        self.assertEqual(["PAPER_PROTECTION_FAILED_EMERGENCY_EXIT"], result["reasons"])
        self.assertTrue(result["positionFlat"])
        self.assertFalse(result["positionProtected"])
        self.assertEqual([], adapter.positions)

    def test_adverse_actual_fill_rechecks_risk_and_flattens_before_stop(self) -> None:
        adapter = SyntheticAdapter()
        adapter.entry_fill_price = Decimal("10.04")

        result = self.run_case(eligible_report(), adapter)

        self.assertEqual(PAPER_TRADE_CREATED, result["classification"])
        self.assertEqual(
            ["PAPER_POST_FILL_RISK_FAILED_EMERGENCY_EXIT"],
            result["reasons"],
        )
        self.assertEqual("BLOCKED", result["postFillRisk"]["status"])
        self.assertIn(
            "PAPER_POST_FILL_UNIT_RISK_EXCEEDED",
            result["postFillRisk"]["blockers"],
        )
        self.assertIn(
            "PAPER_POST_FILL_ENTRY_EXTENSION_TOO_LARGE",
            result["postFillRisk"]["blockers"],
        )
        self.assertFalse(result["positionProtected"])
        self.assertTrue(result["positionFlat"])
        self.assertFalse(any(order.order_type == "stop" for order in adapter.orders.values()))

    def test_fresh_stop_quantity_mismatch_is_canceled_and_position_flattened(self) -> None:
        adapter = SyntheticAdapter()
        adapter.stop_response_quantity = Decimal("99")

        result = self.run_case(eligible_report(), adapter)

        self.assertEqual(
            ["PAPER_PROTECTION_MISMATCH_EMERGENCY_EXIT"],
            result["reasons"],
        )
        self.assertEqual("canceled", result["protectiveStopOrder"]["status"])
        self.assertEqual("99", result["protectiveStopOrder"]["quantity"])
        self.assertFalse(result["positionProtected"])
        self.assertTrue(result["positionFlat"])
        self.assertEqual([], adapter.positions)

    def test_recovery_stop_quantity_mismatch_is_not_reused(self) -> None:
        adapter = SyntheticAdapter()
        payload = eligible_report()
        engine = self.engine(adapter)
        original_write = engine._write_final

        def interrupt_final(path, record):
            if record.get("classification") == PAPER_TRADE_CREATED:
                raise RuntimeError("synthetic interruption after active evidence")
            return original_write(path, record)

        engine._write_final = interrupt_final
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ), self.assertRaisesRegex(RuntimeError, "after active evidence"):
            engine.run_decision(
                self.write_report(payload),
                confirmation=PAPER_ENGINEERING_DECISION_CONFIRMATION,
            )

        stop_id = next(
            order_id
            for order_id, order in adapter.orders.items()
            if order.order_type == "stop"
        )
        original_stop = adapter.orders[stop_id]
        adapter.orders[stop_id] = AlpacaPaperOrder(
            **{
                **original_stop.__dict__,
                "quantity": original_stop.quantity + Decimal("0.01"),
            }
        )

        result = self.run_case(payload, adapter)

        self.assertEqual(
            ["PAPER_RECOVERY_PROTECTION_MISMATCH_EMERGENCY_EXIT"],
            result["reasons"],
        )
        self.assertTrue(result["recoveredAfterInterruption"])
        self.assertFalse(result["positionProtected"])
        self.assertTrue(result["positionFlat"])
        self.assertEqual("canceled", result["protectiveStopOrder"]["status"])
        self.assertEqual([], adapter.positions)

    def test_partial_emergency_exit_never_claims_flat_and_recovery_protects_remainder(self) -> None:
        adapter = SyntheticAdapter()
        adapter.stop_fails = True
        adapter.market_exit_fraction = Decimal("0.5")
        payload = eligible_report()

        with self.assertRaisesRegex(PaperEngineeringAnomaly, "did not reconcile"):
            self.run_case(payload, adapter)
        self.assertEqual(1, len(adapter.positions))
        adapter.stop_fails = False

        result = self.run_case(payload, adapter)

        self.assertEqual(PAPER_TRADE_CREATED, result["classification"])
        self.assertTrue(result["recoveredAfterInterruption"])
        self.assertTrue(result["positionProtected"])
        self.assertFalse(result["positionFlat"])

    def test_credential_shaped_provider_evidence_fails_secret_scan(self) -> None:
        adapter = SyntheticAdapter()
        adapter.account_receipt_payload = {"api_key": "synthetic-redacted-value"}

        with self.assertRaisesRegex(PaperEngineeringAnomaly, "secret scan"):
            self.run_case(eligible_report(), adapter)

    def test_capability_disappearance_blocks_before_provider_calls(self) -> None:
        adapter = SyntheticAdapter()
        incomplete = BrokerCapabilityRegistry.build(
            provider="ALPACA_TRADING_API",
            environment="PAPER_ONLY",
            capabilities=(
                BrokerCapability(
                    CAPABILITY_FRACTIONAL_QUANTITY,
                    CapabilityState.PROVEN,
                    "true",
                    ("synthetic evidence",),
                ),
            ),
        )
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=incomplete,
        ), self.assertRaisesRegex(Exception, "capability identity is inconsistent"):
            self.engine(adapter).run_decision(
                self.write_report(eligible_report()),
                confirmation=PAPER_ENGINEERING_DECISION_CONFIRMATION,
            )

        self.assertEqual([], adapter.calls)

    def test_tampered_final_fails_closed(self) -> None:
        result = self.run_case(eligible_report(rows=False))
        path = self.root / "paper" / "decisions" / f"{result['decisionCycleId']}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["classification"] = PAPER_TRADE_CREATED
        path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(PaperEngineeringAnomaly, "fingerprint"):
            self.run_case(eligible_report(rows=False))

    def test_reconcile_target_cancels_stop_and_flattens(self) -> None:
        adapter = SyntheticAdapter()
        created = self.run_case(eligible_report(), adapter)
        reconciled_at = DECISION_AT + timedelta(minutes=1)
        quote_source = SyntheticQuoteSource(
            {
                "TEST": quote_result(
                    bid=11.1,
                    ask=11.11,
                    last=11.1,
                    timestamp=(reconciled_at - timedelta(seconds=1)).isoformat(),
                    providerQuoteTimestamp=(reconciled_at - timedelta(seconds=1)).isoformat(),
                    providerBidTimestamp=(reconciled_at - timedelta(seconds=1)).isoformat(),
                    providerAskTimestamp=(reconciled_at - timedelta(seconds=1)).isoformat(),
                )
            }
        )
        engine = AlpacaPaperEngineeringEngine(
            adapter=adapter,
            quote_source=quote_source,
            output_directory=self.root / "paper",
            clock=lambda: reconciled_at,
            sleep=lambda _seconds: None,
        )
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            outcomes = engine.reconcile_active()

        self.assertEqual(1, len(outcomes))
        self.assertEqual("POSITION_CLOSED", outcomes[0]["classification"])
        self.assertEqual("TARGET_REACHED", outcomes[0]["exitReason"])
        self.assertTrue(outcomes[0]["positionFlat"])
        self.assertEqual([], adapter.positions)
        self.assertEqual(PAPER_TRADE_CREATED, created["classification"])

    def test_active_reconciliation_never_claims_protected_after_position_drift(self) -> None:
        adapter = SyntheticAdapter()
        result = self.run_case(eligible_report(), adapter)
        self.assertTrue(result["positionProtected"])
        original = adapter.positions[0]
        reduced = (original.quantity - Decimal("0.01")).quantize(
            Decimal("0.000000001")
        )
        adapter.positions = [
            AlpacaPaperPosition(
                symbol=original.symbol,
                quantity=reduced,
                side=original.side,
                average_entry_price=original.average_entry_price,
                market_value=reduced * original.current_price,
                current_price=original.current_price,
            )
        ]

        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            outcomes = self.engine(adapter).reconcile_active()

        self.assertEqual(1, len(outcomes))
        self.assertEqual("POSITION_CLOSED", outcomes[0]["classification"])
        self.assertEqual(
            "PROTECTION_QUANTITY_MISMATCH",
            outcomes[0]["exitReason"],
        )
        self.assertFalse(outcomes[0]["positionProtected"])
        self.assertTrue(outcomes[0]["positionFlat"])
        self.assertEqual("canceled", outcomes[0]["stopOrder"]["status"])
        self.assertEqual(str(reduced), outcomes[0]["exitOrder"]["filledQuantity"])
        self.assertEqual([], adapter.positions)

    def test_run_session_supervises_trade_to_terminal_outcome(self) -> None:
        adapter = SyntheticAdapter()
        quote_source = SequenceQuoteSource(
            [
                {"TEST": quote_result()},
                {"TEST": quote_result(bid=11.1, ask=11.11, last=11.1)},
            ]
        )
        engine = AlpacaPaperEngineeringEngine(
            adapter=adapter,
            quote_source=quote_source,
            output_directory=self.root / "paper",
            clock=lambda: DECISION_AT,
            sleep=lambda _seconds: None,
        )
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            result = engine.run_session(
                self.write_report(eligible_report()),
                confirmation=PAPER_ENGINEERING_DECISION_CONFIRMATION,
                reconcile_interval_seconds=0.1,
                maximum_runtime_seconds=1,
            )

        self.assertEqual("PAPER_ENGINEERING_SESSION_TERMINAL", result["classification"])
        self.assertEqual(PAPER_TRADE_CREATED, result["decision"]["classification"])
        self.assertEqual("POSITION_CLOSED", result["outcome"]["classification"])
        self.assertEqual("TARGET_REACHED", result["outcome"]["exitReason"])
        self.assertEqual([], adapter.positions)

    def test_process_wide_session_mutex_rejects_second_manager(self) -> None:
        with _exclusive_paper_session():
            with self.assertRaisesRegex(PaperEngineeringAnomaly, "already active"):
                with _exclusive_paper_session():
                    self.fail("A second Paper session acquired the same mutex.")

    def test_paper_authorization_rejects_other_symbol_and_live_scope(self) -> None:
        authorization = authorize_paper_engineering_order(
            confirmation=PAPER_ENGINEERING_CONFIRMATION,
            maximum_notional=Decimal("10"),
            allowed_sides=("buy",),
            allowed_symbols=("TEST",),
            client_order_prefix="mh-paper-engineering-test-",
        )
        with self.assertRaisesRegex(Exception, "symbol"):
            authorization.validate(
                AlpacaPaperOrderRequest(
                    symbol="SPY",
                    side="buy",
                    order_type="market",
                    time_in_force="day",
                    client_order_id="mh-paper-engineering-test-entry",
                    notional=Decimal("1"),
                )
            )
        self.assertEqual("https://paper-api.alpaca.markets", ALPACA_PAPER_BASE_URL)


class PaperRiskGovernorTests(unittest.TestCase):
    def test_authorizes_only_execution_ready_schwab_candidate(self) -> None:
        row = eligible_report()["candidates"][0]
        decision, parsed = evaluate_paper_candidate(
            row,
            quote_result=quote_result(),
            decision_at=DECISION_AT,
            policy=policy().risk,
        )

        self.assertTrue(decision.authorized, decision.blockers)
        self.assertIsNotNone(parsed)
        self.assertEqual("ALPACA_PAPER_ENGINEERING", decision.mode)
        self.assertGreater(decision.reward_risk_at_execution, Decimal("1.5"))

    def test_blocks_quote_above_extension_limit(self) -> None:
        row = eligible_report()["candidates"][0]
        decision, _ = evaluate_paper_candidate(
            row,
            quote_result=quote_result(bid=10.10, ask=10.11, last=10.10),
            decision_at=DECISION_AT,
            policy=policy().risk,
        )

        self.assertFalse(decision.authorized)
        self.assertIn("PAPER_ENTRY_EXTENSION_TOO_LARGE", decision.blockers)


if __name__ == "__main__":
    unittest.main()
