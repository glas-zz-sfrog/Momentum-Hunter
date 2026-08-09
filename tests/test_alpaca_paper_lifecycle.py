from __future__ import annotations

import inspect
import json
from copy import deepcopy
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from momentum_hunter.alpaca_paper_broker import (
    AlpacaPaperAsset,
    AlpacaPaperBrokerResponseError,
    AlpacaPaperOrder,
    AlpacaPaperOrderRequest,
    AlpacaPaperPosition,
    PaperOrderResolution,
    PaperOrderResolutionState,
)
from momentum_hunter.alpaca_paper_lifecycle import (
    PAPER_LIFECYCLE_CONFIRMATION,
    AlpacaPaperLifecycleError,
    _report_fingerprint,
    adjudicate_lifecycle_capabilities,
    create_lifecycle_plan,
    load_lifecycle_plan,
    run_paper_lifecycle_proof,
    write_lifecycle_plan,
)
from momentum_hunter.broker_capabilities import (
    CAPABILITY_BROKER_RESIDENT_PROTECTION,
    CAPABILITY_FRACTIONAL_BRACKET,
    CAPABILITY_FRACTIONAL_LIMIT,
    CAPABILITY_FRACTIONAL_MARKET,
    CAPABILITY_FRACTIONAL_OCO,
    CAPABILITY_FRACTIONAL_OTO,
    CAPABILITY_FRACTIONAL_QUANTITY,
    CAPABILITY_FRACTIONAL_REPLACE,
    CAPABILITY_FRACTIONAL_STOP,
    CAPABILITY_FRACTIONAL_STOP_LIMIT,
    CAPABILITY_ORDER_STATUS_STREAM,
    CapabilityState,
)
from momentum_hunter.alpaca_paper_onboarding import AlpacaPaperAccount
from momentum_hunter.time_utils import CENTRAL_TZ


MARKET_TIME = datetime(2026, 8, 10, 10, 0, tzinfo=CENTRAL_TZ)
WEEKEND_TIME = datetime(2026, 8, 9, 10, 0, tzinfo=CENTRAL_TZ)


def _receipt(method: str, path: str, status: int) -> dict[str, object]:
    return {
        "method": method,
        "path": path,
        "httpStatus": status,
        "requestId": "synthetic-request-id",
        "requestIdPresent": True,
        "receivedAt": "2026-08-10T15:00:00+00:00",
        "payload": None,
    }


class _FakeLifecycleAdapter:
    def __init__(
        self,
        *,
        partial_entry: bool = False,
        partial_first_exit: bool = False,
        fail_order_type: str | None = None,
        unexpected_position: bool = False,
        unexpected_order: bool = False,
        available_cash: Decimal = Decimal("100"),
    ) -> None:
        self.partial_entry = partial_entry
        self.partial_first_exit = partial_first_exit
        self.fail_order_type = fail_order_type
        self.available_cash = available_cash
        self.evidence_sink = None
        self.orders: dict[str, AlpacaPaperOrder] = {}
        self.position: AlpacaPaperPosition | None = None
        self.calls: list[str] = []
        self.submit_calls: list[AlpacaPaperOrderRequest] = []
        self.cancel_calls: list[str] = []
        self.replace_calls: list[str] = []
        if unexpected_position:
            self.position = _position(symbol="AAPL", quantity=Decimal("0.01"))
        if unexpected_order:
            order = _order(
                client_order_id="foreign-paper-order",
                order_type="limit",
                side="buy",
                status="new",
                quantity=Decimal("0.01"),
                limit_price=Decimal("1.00"),
            )
            self.orders[order.client_order_id] = order

    def seed_owned_entry_and_position(self, client_order_id: str) -> None:
        quantity = Decimal("0.004")
        entry = _order(
            client_order_id=client_order_id,
            order_type="market",
            side="buy",
            status="filled",
            quantity=quantity,
            notional=Decimal("1.00"),
            filled_quantity=quantity,
            filled_average_price=Decimal("250.00"),
        )
        self.orders[client_order_id] = entry
        self.position = _position(quantity=quantity)

    def seed_owned_open_order(
        self,
        client_order_id: str,
        *,
        order_type: str,
    ) -> None:
        self.orders[client_order_id] = _order(
            client_order_id=client_order_id,
            order_type=order_type,
            side="sell",
            status="new",
            quantity=Decimal("0.004"),
            limit_price=Decimal("500.00") if order_type == "limit" else None,
            stop_price=Decimal("125.00") if order_type == "stop" else None,
        )

    def get_account(self) -> AlpacaPaperAccount:
        self.calls.append("get_account")
        return AlpacaPaperAccount(
            status="ACTIVE",
            cash=self.available_cash,
            buying_power=self.available_cash,
            account_blocked=False,
            trading_blocked=False,
            trade_suspended_by_user=False,
        )

    def get_asset(self, symbol: str) -> AlpacaPaperAsset:
        self.calls.append("get_asset")
        return AlpacaPaperAsset(
            symbol=symbol,
            asset_class="us_equity",
            exchange="ARCA",
            status="active",
            tradable=True,
            fractionable=True,
            marginable=True,
            shortable=True,
            easy_to_borrow=True,
            attributes=(),
            request_id_present=True,
        )

    def list_positions(self) -> list[AlpacaPaperPosition]:
        self.calls.append("list_positions")
        return [] if self.position is None else [self.position]

    def list_orders(
        self,
        *,
        status: str = "open",
        symbols: tuple[str, ...] = (),
    ) -> list[AlpacaPaperOrder]:
        del symbols
        self.calls.append(f"list_orders:{status}")
        values = list(self.orders.values())
        if status == "open":
            return [item for item in values if not item.terminal]
        return values

    def try_get_order_by_client_id(
        self,
        client_order_id: str,
    ) -> AlpacaPaperOrder | None:
        self.calls.append(f"get_client:{client_order_id}")
        return self.orders.get(client_order_id)

    def get_order(self, order_id: str) -> AlpacaPaperOrder:
        self.calls.append(f"get_order:{order_id}")
        for item in self.orders.values():
            if item.order_id == order_id:
                return item
        raise AssertionError(f"Unknown synthetic order {order_id}")

    def submit_order_idempotently(
        self,
        request: AlpacaPaperOrderRequest,
        *,
        authorization,
    ) -> PaperOrderResolution:
        authorization.validate(request)
        self.calls.append(f"submit:{request.client_order_id}")
        existing = self.orders.get(request.client_order_id)
        if existing is not None:
            return PaperOrderResolution(PaperOrderResolutionState.RECOVERED, existing)
        if request.order_type == self.fail_order_type:
            raise AlpacaPaperBrokerResponseError(
                "Synthetic provider interruption without sensitive values."
            )
        self.submit_calls.append(request)
        if request.side == "buy" and request.order_type == "market":
            quantity = Decimal("0.002") if self.partial_entry else Decimal("0.004")
            status = "partially_filled" if self.partial_entry else "filled"
            order = _order_from_request(
                request,
                status=status,
                quantity=quantity,
                filled_quantity=quantity,
                filled_average_price=Decimal("250.00"),
            )
            self.position = _position(quantity=quantity)
        elif request.side == "sell" and request.order_type == "market":
            assert self.position is not None
            if self.partial_first_exit and request.client_order_id.endswith("exit-1"):
                fill = (self.position.quantity / Decimal("2")).quantize(
                    Decimal("0.000000001")
                )
                remaining = self.position.quantity - fill
                order = _order_from_request(
                    request,
                    status="partially_filled",
                    quantity=request.quantity,
                    filled_quantity=fill,
                    filled_average_price=Decimal("250.00"),
                )
                self.position = _position(quantity=remaining)
            else:
                order = _order_from_request(
                    request,
                    status="filled",
                    quantity=request.quantity,
                    filled_quantity=request.quantity or Decimal("0"),
                    filled_average_price=Decimal("250.00"),
                )
                self.position = None
        else:
            order = _order_from_request(
                request,
                status="new",
                quantity=request.quantity,
            )
        self.orders[request.client_order_id] = order
        return PaperOrderResolution(PaperOrderResolutionState.SUBMITTED, order)

    def replace_order_idempotently(
        self,
        order_id: str,
        *,
        limit_price: Decimal,
        client_order_id: str,
        authorization,
    ) -> PaperOrderResolution:
        self.calls.append(f"replace:{client_order_id}")
        existing = self.orders.get(client_order_id)
        if existing is not None:
            return PaperOrderResolution(PaperOrderResolutionState.RECOVERED, existing)
        original = self.get_order(order_id)
        assert original.quantity is not None
        request = AlpacaPaperOrderRequest(
            symbol=original.symbol,
            side=original.side,
            order_type=original.order_type,
            time_in_force=original.time_in_force,
            client_order_id=client_order_id,
            quantity=original.quantity,
            limit_price=limit_price,
        )
        authorization.validate(request)
        replacement = _order_from_request(
            request,
            status="new",
            quantity=original.quantity,
            replaces=original.order_id,
        )
        self.orders[original.client_order_id] = replace(
            original,
            status="replaced",
            replaced_by=replacement.order_id,
            replaced_at="2026-08-10T15:00:05Z",
            updated_at="2026-08-10T15:00:05Z",
        )
        self.orders[client_order_id] = replacement
        self.replace_calls.append(client_order_id)
        return PaperOrderResolution(PaperOrderResolutionState.SUBMITTED, replacement)

    def cancel_order(self, order_id: str, *, authorization) -> AlpacaPaperOrder:
        self.calls.append(f"cancel:{order_id}")
        order = self.get_order(order_id)
        authorization.validate(_request_from_order(order))
        if order.terminal:
            return order
        canceled = replace(
            order,
            status="canceled",
            canceled_at="2026-08-10T15:00:10Z",
            updated_at="2026-08-10T15:00:10Z",
        )
        self.orders[order.client_order_id] = canceled
        self.cancel_calls.append(order.client_order_id)
        return canceled


def _position(
    *,
    symbol: str = "SPY",
    quantity: Decimal = Decimal("0.004"),
) -> AlpacaPaperPosition:
    return AlpacaPaperPosition(
        symbol=symbol,
        quantity=quantity,
        side="long",
        average_entry_price=Decimal("250.00"),
        market_value=quantity * Decimal("250.00"),
        current_price=Decimal("250.00"),
    )


def _order(
    *,
    client_order_id: str,
    order_type: str,
    side: str,
    status: str,
    quantity: Decimal | None,
    notional: Decimal | None = None,
    filled_quantity: Decimal = Decimal("0"),
    filled_average_price: Decimal | None = None,
    limit_price: Decimal | None = None,
    stop_price: Decimal | None = None,
    replaces: str | None = None,
) -> AlpacaPaperOrder:
    ordinal = abs(hash(client_order_id)) % (10**12)
    order_id = f"00000000-0000-4000-8000-{ordinal:012d}"
    UUID(order_id)
    return AlpacaPaperOrder(
        order_id=order_id,
        client_order_id=client_order_id,
        symbol="SPY",
        asset_class="us_equity",
        side=side,
        order_type=order_type,
        order_class="simple",
        time_in_force="day",
        status=status,
        quantity=quantity,
        notional=notional,
        filled_quantity=filled_quantity,
        filled_average_price=filled_average_price,
        limit_price=limit_price,
        stop_price=stop_price,
        submitted_at="2026-08-10T15:00:00Z",
        updated_at="2026-08-10T15:00:01Z",
        filled_at="2026-08-10T15:00:02Z" if filled_quantity > 0 else None,
        canceled_at=None,
        replaced_at=None,
        replaced_by=None,
        replaces=replaces,
        request_id_present=True,
    )


def _order_from_request(
    request: AlpacaPaperOrderRequest,
    *,
    status: str,
    quantity: Decimal | None,
    filled_quantity: Decimal = Decimal("0"),
    filled_average_price: Decimal | None = None,
    replaces: str | None = None,
) -> AlpacaPaperOrder:
    return _order(
        client_order_id=request.client_order_id,
        order_type=request.order_type,
        side=request.side,
        status=status,
        quantity=quantity,
        notional=request.notional,
        filled_quantity=filled_quantity,
        filled_average_price=filled_average_price,
        limit_price=request.limit_price,
        stop_price=request.stop_price,
        replaces=replaces,
    )


def _request_from_order(order: AlpacaPaperOrder) -> AlpacaPaperOrderRequest:
    return AlpacaPaperOrderRequest(
        symbol=order.symbol,
        side=order.side,
        order_type=order.order_type,
        time_in_force=order.time_in_force,
        client_order_id=order.client_order_id,
        quantity=order.quantity if order.notional is None else None,
        notional=order.notional,
        limit_price=order.limit_price,
        stop_price=order.stop_price,
    )


class AlpacaPaperLifecyclePlanTests(unittest.TestCase):
    def test_plan_is_write_once_and_tamper_evident(self) -> None:
        plan = create_lifecycle_plan(MARKET_TIME, poll_attempts=2, poll_interval_seconds=0)
        with tempfile.TemporaryDirectory() as temp:
            path = write_lifecycle_plan(plan, Path(temp))
            self.assertEqual(plan, load_lifecycle_plan(path))
            with self.assertRaises(AlpacaPaperLifecycleError):
                write_lifecycle_plan(plan, Path(temp))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["entryNotional"] = "2.00"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(AlpacaPaperLifecycleError, "frozen scope"):
                load_lifecycle_plan(path)

    def test_plan_rejects_repository_output(self) -> None:
        plan = create_lifecycle_plan(MARKET_TIME)
        repository_output = Path(__file__).resolve().parents[1] / ".tmp-proof"
        with self.assertRaisesRegex(AlpacaPaperLifecycleError, "outside"):
            write_lifecycle_plan(plan, repository_output)


class AlpacaPaperLifecycleRunnerTests(unittest.TestCase):
    def _run(
        self,
        adapter: _FakeLifecycleAdapter,
        directory: Path,
        *,
        plan_path: Path | None = None,
    ) -> dict[str, object]:
        return run_paper_lifecycle_proof(
            adapter,  # type: ignore[arg-type]
            confirmation=PAPER_LIFECYCLE_CONFIRMATION,
            output_directory=directory,
            plan_path=plan_path,
            current_time=MARKET_TIME,
            sleep=lambda _seconds: None,
        )

    def _direct_report(self, directory: Path) -> dict[str, object]:
        report = self._run(_FakeLifecycleAdapter(), directory)
        execution = report["execution"]
        assert isinstance(execution, dict)
        stop_id = execution["protectiveStop"]["orderId"]
        stop_limit_id = execution["protectiveStopLimit"]["orderId"]
        replacement_id = execution["targetReplacement"]["orderId"]
        report["providerReceipts"] = [
            _receipt("GET", "/v2/account", 200),
            _receipt("GET", "/v2/assets/SPY", 200),
            _receipt("GET", "/v2/positions", 200),
            _receipt("GET", "/v2/orders", 200),
            _receipt("GET", "/v2/orders:by_client_order_id", 404),
            *[_receipt("POST", "/v2/orders", 200) for _index in range(5)],
            _receipt("PATCH", f"/v2/orders/{replacement_id}", 200),
            _receipt("DELETE", f"/v2/orders/{stop_id}", 204),
            _receipt("DELETE", f"/v2/orders/{stop_limit_id}", 204),
            _receipt("DELETE", f"/v2/orders/{replacement_id}", 204),
        ]
        report["fingerprint"] = _report_fingerprint(report)
        return report

    def test_direct_report_promotes_only_observed_lifecycle_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._direct_report(Path(temp))
            before = deepcopy(report)
            registry = adjudicate_lifecycle_capabilities(report)
            self.assertEqual(before, report)
            for capability in (
                CAPABILITY_FRACTIONAL_QUANTITY,
                CAPABILITY_FRACTIONAL_MARKET,
                CAPABILITY_FRACTIONAL_LIMIT,
                CAPABILITY_FRACTIONAL_STOP,
                CAPABILITY_FRACTIONAL_STOP_LIMIT,
                CAPABILITY_FRACTIONAL_REPLACE,
            ):
                self.assertEqual(CapabilityState.PROVEN, registry.get(capability).state)
            for capability in (
                CAPABILITY_FRACTIONAL_BRACKET,
                CAPABILITY_FRACTIONAL_OCO,
                CAPABILITY_FRACTIONAL_OTO,
                CAPABILITY_ORDER_STATUS_STREAM,
                CAPABILITY_BROKER_RESIDENT_PROTECTION,
            ):
                self.assertIsNot(CapabilityState.PROVEN, registry.get(capability).state)

    def test_adjudication_rejects_tampered_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._direct_report(Path(temp))
            report["finalPositions"] = 1
            with self.assertRaisesRegex(AlpacaPaperLifecycleError, "fingerprint"):
                adjudicate_lifecycle_capabilities(report)

    def test_adjudication_rejects_dirty_final_state_even_with_new_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._direct_report(Path(temp))
            report["finalOpenOrders"] = 1
            report["fingerprint"] = _report_fingerprint(report)
            with self.assertRaisesRegex(AlpacaPaperLifecycleError, "clean Paper-only"):
                adjudicate_lifecycle_capabilities(report)

    def test_adjudication_rejects_missing_direct_provider_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._direct_report(Path(temp))
            report["providerReceipts"] = []
            report["fingerprint"] = _report_fingerprint(report)
            with self.assertRaisesRegex(AlpacaPaperLifecycleError, "provider receipts"):
                adjudicate_lifecycle_capabilities(report)

    def test_adjudication_rejects_incomplete_lifecycle_event_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report = self._direct_report(Path(temp))
            report["events"] = [
                item
                for item in report["events"]
                if item["event"] != "PROTECTIVE_STOP_HOSTED"
            ]
            report["fingerprint"] = _report_fingerprint(report)
            with self.assertRaisesRegex(
                AlpacaPaperLifecycleError, "PROTECTIVE_STOP_HOSTED"
            ):
                adjudicate_lifecycle_capabilities(report)

    def test_closed_market_gate_blocks_before_network_or_files(self) -> None:
        adapter = _FakeLifecycleAdapter()
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(AlpacaPaperLifecycleError, "regular market"):
                run_paper_lifecycle_proof(
                    adapter,  # type: ignore[arg-type]
                    confirmation=PAPER_LIFECYCLE_CONFIRMATION,
                    output_directory=Path(temp),
                    current_time=WEEKEND_TIME,
                )
            self.assertEqual([], adapter.calls)
            self.assertEqual([], list(Path(temp).iterdir()))

    def test_complete_fractional_lifecycle_is_flat_and_write_once(self) -> None:
        adapter = _FakeLifecycleAdapter()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            report = self._run(adapter, output)
            self.assertEqual("ALPACA_PAPER_LIFECYCLE_PROVEN", report["classification"])
            self.assertTrue(report["cleanAfterProof"])
            self.assertTrue(report["execution"]["exactLiquidation"])
            order_types = [item.order_type for item in adapter.submit_calls]
            self.assertEqual(
                ["market", "stop", "stop_limit", "limit", "market"],
                order_types,
            )
            self.assertEqual(1, len(adapter.replace_calls))
            self.assertIsNone(adapter.position)
            plan_path = next(output.glob("*-plan.json"))
            calls_before_duplicate = len(adapter.calls)
            duplicate = self._run(adapter, output, plan_path=plan_path)
            self.assertEqual(report["fingerprint"], duplicate["fingerprint"])
            self.assertEqual(calls_before_duplicate, len(adapter.calls))

    def test_restart_recovers_entry_position_without_second_entry(self) -> None:
        adapter = _FakeLifecycleAdapter()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            plan = create_lifecycle_plan(MARKET_TIME, poll_attempts=2, poll_interval_seconds=0)
            plan_path = write_lifecycle_plan(plan, output)
            adapter.seed_owned_entry_and_position(plan.entry_client_order_id)
            report = self._run(adapter, output, plan_path=plan_path)
            self.assertTrue(report["execution"]["restartRecoveryUsed"])
            entry_mutations = [
                request
                for request in adapter.submit_calls
                if request.client_order_id == plan.entry_client_order_id
            ]
            self.assertEqual([], entry_mutations)

    def test_restart_recovery_does_not_require_new_entry_buying_power(self) -> None:
        adapter = _FakeLifecycleAdapter(available_cash=Decimal("0"))
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            plan = create_lifecycle_plan(
                MARKET_TIME,
                poll_attempts=2,
                poll_interval_seconds=0,
            )
            plan_path = write_lifecycle_plan(plan, output)
            adapter.seed_owned_entry_and_position(plan.entry_client_order_id)
            report = self._run(adapter, output, plan_path=plan_path)
            self.assertTrue(report["execution"]["restartRecoveryUsed"])
            self.assertTrue(report["execution"]["exactLiquidation"])
            self.assertIsNone(adapter.position)

    def test_partial_entry_is_recorded_and_remainder_canceled(self) -> None:
        adapter = _FakeLifecycleAdapter(partial_entry=True)
        with tempfile.TemporaryDirectory() as temp:
            report = self._run(adapter, Path(temp))
            self.assertTrue(report["execution"]["partialFillObserved"])
            events = [item["event"] for item in report["events"]]
            self.assertIn("PARTIAL_FILL_OBSERVED", events)
            self.assertTrue(
                any(value.endswith("-entry") for value in adapter.cancel_calls)
            )

    def test_partial_exit_uses_next_frozen_id_and_reaches_flat(self) -> None:
        adapter = _FakeLifecycleAdapter(partial_first_exit=True)
        with tempfile.TemporaryDirectory() as temp:
            report = self._run(adapter, Path(temp))
            self.assertTrue(report["execution"]["partialFillObserved"])
            exit_requests = [
                item for item in adapter.submit_calls if "-exit-" in item.client_order_id
            ]
            self.assertEqual(2, len(exit_requests))
            self.assertIsNone(adapter.position)

    def test_unexpected_position_blocks_without_mutating_provider_state(self) -> None:
        adapter = _FakeLifecycleAdapter(unexpected_position=True)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(AlpacaPaperLifecycleError):
                self._run(adapter, Path(temp))
            self.assertEqual([], adapter.submit_calls)
            self.assertEqual([], adapter.cancel_calls)
            reports = list(Path(temp).glob("*-attempt-*.json"))
            self.assertEqual(1, len(reports))
            payload = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertTrue(payload["anomaly"])

    def test_unexpected_open_order_blocks_without_cancellation(self) -> None:
        adapter = _FakeLifecycleAdapter(unexpected_order=True)
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(AlpacaPaperLifecycleError):
                self._run(adapter, Path(temp))
            self.assertEqual([], adapter.submit_calls)
            self.assertEqual([], adapter.cancel_calls)

    def test_owned_protective_order_without_entry_or_position_is_anomaly(self) -> None:
        adapter = _FakeLifecycleAdapter()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            plan = create_lifecycle_plan(MARKET_TIME, poll_attempts=2, poll_interval_seconds=0)
            plan_path = write_lifecycle_plan(plan, output)
            adapter.seed_owned_open_order(plan.stop_client_order_id, order_type="stop")
            with self.assertRaises(AlpacaPaperLifecycleError):
                self._run(adapter, output, plan_path=plan_path)
            self.assertEqual([], adapter.submit_calls)
            self.assertEqual([], adapter.cancel_calls)

    def test_provider_interruption_preserves_failure_and_flattens(self) -> None:
        adapter = _FakeLifecycleAdapter(fail_order_type="stop")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(AlpacaPaperLifecycleError):
                self._run(adapter, Path(temp))
            self.assertIsNone(adapter.position)
            reports = list(Path(temp).glob("*-attempt-*.json"))
            self.assertEqual(1, len(reports))
            payload = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertFalse(payload["cleanAfterProof"] is False)
            self.assertIn("interruption", payload["failure"])

    def test_plan_source_is_not_mutated_during_resume(self) -> None:
        adapter = _FakeLifecycleAdapter()
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            plan = create_lifecycle_plan(MARKET_TIME, poll_attempts=2, poll_interval_seconds=0)
            plan_path = write_lifecycle_plan(plan, output)
            before = plan_path.read_bytes()
            self._run(adapter, output, plan_path=plan_path)
            self.assertEqual(before, plan_path.read_bytes())

    def test_output_has_no_secret_or_account_identity_fields(self) -> None:
        adapter = _FakeLifecycleAdapter()
        with tempfile.TemporaryDirectory() as temp:
            report = self._run(adapter, Path(temp))
            encoded = json.dumps(report, sort_keys=True).lower()
            self.assertNotIn("account_number", encoded)
            self.assertNotIn("account_id", encoded)
            self.assertNotIn("secret_key", encoded)
            self.assertNotIn("api_key", encoded)
            self.assertNotIn("bearer", encoded)

    def test_lifecycle_lab_is_not_wired_into_runtime(self) -> None:
        import momentum_hunter.autonomy.simulation as simulation
        import momentum_hunter.engine_host as engine_host

        self.assertNotIn("alpaca_paper_lifecycle", inspect.getsource(simulation))
        self.assertNotIn("alpaca_paper_lifecycle", inspect.getsource(engine_host))


if __name__ == "__main__":
    unittest.main()
