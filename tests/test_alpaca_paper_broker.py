from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import requests

from momentum_hunter.alpaca_fractional_proof import (
    AlpacaFractionalProofError,
    FractionalLimitCancelPlan,
    documented_capability_registry,
    run_fractional_limit_cancel_proof,
    run_readonly_capability_preflight,
)
from momentum_hunter.alpaca_paper_broker import (
    ALPACA_LIVE_BASE_URL,
    ALPACA_PAPER_BASE_URL,
    PAPER_PROBE_CONFIRMATION,
    AlpacaPaperBrokerAdapter,
    AlpacaPaperBrokerEndpointError,
    AlpacaPaperBrokerRequestError,
    AlpacaPaperBrokerResponseError,
    AlpacaPaperOrderRequest,
    authorize_paper_capability_probe,
)
from momentum_hunter.alpaca_paper_onboarding import (
    AlpacaPaperCredentials,
    AlpacaPaperLane,
)
from momentum_hunter.broker_capabilities import (
    CAPABILITY_FRACTIONAL_LIMIT,
    BrokerCapability,
    BrokerCapabilityError,
    BrokerCapabilityRegistry,
    CapabilityState,
)


KEY_ID = "SYNTHETICPAPERKEY123456789"
SECRET_KEY = "SYNTHETICPAPERSECRET12345678901234567890"
ORDER_ID = "11111111-1111-4111-8111-111111111111"
REPLACEMENT_ID = "22222222-2222-4222-8222-222222222222"
CLIENT_ID = "mh-paper-capability-synthetic"


class _Credentials:
    lane = AlpacaPaperLane.CANARY_REALISTIC

    def load(self) -> AlpacaPaperCredentials:
        return AlpacaPaperCredentials(KEY_ID, SECRET_KEY)


class _Response:
    def __init__(
        self,
        payload: object | None,
        *,
        status_code: int = 200,
        request_id: str = "synthetic-request-id",
        redirect: bool = False,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = {"X-Request-ID": request_id} if request_id else {}
        self.is_redirect = redirect
        self.content = b"" if payload is None else json.dumps(payload).encode("utf-8")

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no body")
        return self._payload


class _Session:
    def __init__(self, responses: list[_Response | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _Response:
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected request: {method} {url}")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _account_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "ACTIVE",
        "cash": "100",
        "buying_power": "100",
        "account_blocked": False,
        "trading_blocked": False,
        "trade_suspended_by_user": False,
    }
    payload.update(overrides)
    return payload


def _asset_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "SPY",
        "class": "us_equity",
        "exchange": "ARCA",
        "status": "active",
        "tradable": True,
        "fractionable": True,
        "marginable": True,
        "shortable": True,
        "easy_to_borrow": True,
        "attributes": ["fractional_eh_enabled", "overnight_tradable"],
    }
    payload.update(overrides)
    return payload


def _order_payload(
    *,
    order_id: str = ORDER_ID,
    client_order_id: str = CLIENT_ID,
    status: str = "accepted",
    qty: str | None = "0.5",
    limit_price: str | None = "2.00",
    canceled_at: str | None = None,
    replaces: str | None = None,
) -> dict[str, object]:
    return {
        "id": order_id,
        "client_order_id": client_order_id,
        "symbol": "SPY",
        "asset_class": "us_equity",
        "side": "buy",
        "type": "limit",
        "order_class": "simple",
        "time_in_force": "day",
        "status": status,
        "qty": qty,
        "notional": None,
        "filled_qty": "0",
        "filled_avg_price": None,
        "limit_price": limit_price,
        "stop_price": None,
        "submitted_at": "2026-08-09T12:00:00Z",
        "updated_at": "2026-08-09T12:00:01Z",
        "filled_at": None,
        "canceled_at": canceled_at,
        "replaced_at": None,
        "replaced_by": None,
        "replaces": replaces,
    }


def _adapter(session: _Session) -> AlpacaPaperBrokerAdapter:
    return AlpacaPaperBrokerAdapter(
        lane=AlpacaPaperLane.CANARY_REALISTIC,
        credentials=_Credentials(),  # type: ignore[arg-type]
        session=session,  # type: ignore[arg-type]
    )


def _request(**overrides: object) -> AlpacaPaperOrderRequest:
    values: dict[str, object] = {
        "symbol": "SPY",
        "side": "buy",
        "order_type": "limit",
        "time_in_force": "day",
        "client_order_id": CLIENT_ID,
        "quantity": Decimal("0.5"),
        "limit_price": Decimal("2.00"),
    }
    values.update(overrides)
    return AlpacaPaperOrderRequest(**values)  # type: ignore[arg-type]


def _authorization():
    return authorize_paper_capability_probe(
        confirmation=PAPER_PROBE_CONFIRMATION,
        maximum_notional=Decimal("1.00"),
    )


class BrokerCapabilityTests(unittest.TestCase):
    def test_registry_is_deterministic_and_unknown_fails_closed(self) -> None:
        first = documented_capability_registry()
        second = documented_capability_registry()
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(
            CapabilityState.DOCUMENTED_UNPROVEN,
            first.get(CAPABILITY_FRACTIONAL_LIMIT).state,
        )
        with self.assertRaises(BrokerCapabilityError):
            first.require_proven(CAPABILITY_FRACTIONAL_LIMIT)
        self.assertEqual(CapabilityState.UNKNOWN, first.get("futureCapability").state)

    def test_registry_rejects_duplicate_capabilities(self) -> None:
        item = BrokerCapability(
            name="supportsThing",
            state=CapabilityState.UNKNOWN,
            value="UNKNOWN",
            evidence=("synthetic",),
        )
        with self.assertRaises(BrokerCapabilityError):
            BrokerCapabilityRegistry.build(
                provider="SYNTHETIC",
                environment="PAPER_ONLY",
                capabilities=(item, item),
            )


class AlpacaPaperBrokerTests(unittest.TestCase):
    def test_live_host_research_lane_and_trailing_slash_are_rejected(self) -> None:
        for lane, endpoint in (
            (AlpacaPaperLane.CANARY_REALISTIC, ALPACA_LIVE_BASE_URL),
            (AlpacaPaperLane.CANARY_REALISTIC, f"{ALPACA_PAPER_BASE_URL}/"),
            (AlpacaPaperLane.STRATEGY_RESEARCH, ALPACA_PAPER_BASE_URL),
        ):
            with self.subTest(lane=lane, endpoint=endpoint), self.assertRaises(
                AlpacaPaperBrokerEndpointError
            ):
                AlpacaPaperBrokerAdapter(lane=lane, base_url=endpoint)

    def test_fractional_request_validation_is_fail_closed(self) -> None:
        invalid = (
            {"quantity": Decimal("0.1234567891")},
            {"quantity": None, "notional": None},
            {"notional": Decimal("1.00")},
            {"order_class": "bracket"},
            {"extended_hours": True},
            {"time_in_force": "gtc"},
        )
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(
                AlpacaPaperBrokerRequestError
            ):
                _request(**changes)
        market = _request(
            order_type="market",
            quantity=None,
            notional=Decimal("1.00"),
            limit_price=None,
        )
        self.assertEqual("1.00", market.to_payload()["notional"])

    def test_authorization_requires_exact_phrase_owned_id_and_one_dollar_cap(self) -> None:
        with self.assertRaises(AlpacaPaperBrokerRequestError):
            authorize_paper_capability_probe(confirmation="authorize")
        authorization = _authorization()
        authorization.validate(_request())
        with self.assertRaises(AlpacaPaperBrokerRequestError):
            authorization.validate(_request(client_order_id="foreign-order"))
        with self.assertRaises(AlpacaPaperBrokerRequestError):
            authorization.validate(_request(limit_price=Decimal("2.01")))

    def test_readonly_requests_use_exact_host_headers_and_no_redirect(self) -> None:
        session = _Session(
            [
                _Response(_account_payload()),
                _Response(_asset_payload()),
                _Response([]),
                _Response([]),
            ]
        )
        adapter = _adapter(session)
        self.assertEqual("ACTIVE", adapter.get_account().status)
        self.assertTrue(adapter.get_asset("spy").fractionable)
        self.assertEqual([], adapter.list_positions())
        self.assertEqual([], adapter.list_orders())
        self.assertEqual(4, len(session.calls))
        for _method, url, kwargs in session.calls:
            self.assertTrue(url.startswith(ALPACA_PAPER_BASE_URL))
            self.assertNotIn(ALPACA_LIVE_BASE_URL, url)
            self.assertFalse(kwargs["allow_redirects"])
            self.assertEqual(KEY_ID, kwargs["headers"]["APCA-API-KEY-ID"])
            self.assertEqual(SECRET_KEY, kwargs["headers"]["APCA-API-SECRET-KEY"])

    def test_provider_errors_and_network_failures_are_redacted(self) -> None:
        session = _Session(
            [
                _Response(
                    {"code": 401, "message": f"bad {KEY_ID} {SECRET_KEY}"},
                    status_code=401,
                )
            ]
        )
        with self.assertRaises(AlpacaPaperBrokerResponseError) as observed:
            _adapter(session).get_account()
        rendered = str(observed.exception)
        self.assertNotIn(KEY_ID, rendered)
        self.assertNotIn(SECRET_KEY, rendered)
        self.assertIn("[redacted]", rendered)

        with self.assertRaises(AlpacaPaperBrokerResponseError):
            _adapter(_Session([requests.ConnectionError(f"{KEY_ID} {SECRET_KEY}")])).get_account()

    def test_submit_uses_exact_fractional_payload_and_owned_client_id(self) -> None:
        session = _Session([_Response(_order_payload())])
        order = _adapter(session).submit_order(_request(), authorization=_authorization())
        self.assertEqual(Decimal("0.5"), order.quantity)
        method, url, kwargs = session.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual(f"{ALPACA_PAPER_BASE_URL}/v2/orders", url)
        self.assertEqual("0.5", kwargs["json"]["qty"])
        self.assertEqual("2.00", kwargs["json"]["limit_price"])
        self.assertEqual(CLIENT_ID, kwargs["json"]["client_order_id"])

    def test_simple_order_accepts_provider_empty_order_class(self) -> None:
        payload = _order_payload()
        payload["order_class"] = ""
        order = _adapter(_Session([_Response(payload)])).submit_order(
            _request(),
            authorization=_authorization(),
        )
        self.assertEqual("simple", order.order_class)

    def test_submit_rejects_provider_client_id_contradiction(self) -> None:
        contradictory = "mh-paper-capability-provider-contradiction"
        session = _Session([_Response(_order_payload(client_order_id=contradictory))])
        with self.assertRaises(AlpacaPaperBrokerResponseError):
            _adapter(session).submit_order(_request(), authorization=_authorization())

    def test_ambiguous_submit_failure_is_not_retried(self) -> None:
        session = _Session([requests.ConnectionError("ambiguous write failure")])
        with self.assertRaises(AlpacaPaperBrokerResponseError):
            _adapter(session).submit_order(_request(), authorization=_authorization())
        self.assertEqual(1, len(session.calls))

    def test_cancel_checks_ownership_and_reads_terminal_order(self) -> None:
        canceled = _order_payload(
            status="canceled",
            canceled_at="2026-08-09T12:01:00Z",
        )
        session = _Session(
            [
                _Response(_order_payload()),
                _Response(None, status_code=204),
                _Response(canceled),
            ]
        )
        order = _adapter(session).cancel_order(ORDER_ID, authorization=_authorization())
        self.assertEqual("canceled", order.status)
        self.assertEqual(["GET", "DELETE", "GET"], [call[0] for call in session.calls])

    def test_cancel_is_idempotent_for_terminal_owned_order(self) -> None:
        canceled = _order_payload(
            status="canceled",
            canceled_at="2026-08-09T12:01:00Z",
        )
        session = _Session([_Response(canceled)])
        order = _adapter(session).cancel_order(ORDER_ID, authorization=_authorization())
        self.assertEqual("canceled", order.status)
        self.assertEqual(["GET"], [call[0] for call in session.calls])

    def test_replace_is_price_only_owned_and_within_bound(self) -> None:
        replacement_client = "mh-paper-capability-replacement"
        replacement = _order_payload(
            order_id=REPLACEMENT_ID,
            client_order_id=replacement_client,
            status="new",
            limit_price="1.50",
            replaces=ORDER_ID,
        )
        session = _Session([_Response(_order_payload(status="new")), _Response(replacement)])
        order = _adapter(session).replace_order(
            ORDER_ID,
            limit_price=Decimal("1.50"),
            client_order_id=replacement_client,
            authorization=_authorization(),
        )
        self.assertEqual(REPLACEMENT_ID, order.order_id)
        self.assertEqual("PATCH", session.calls[1][0])
        self.assertNotIn("qty", session.calls[1][2]["json"])

    def test_restart_reconciles_owned_order_by_client_id_without_mutation(self) -> None:
        first_process = _adapter(_Session([_Response(_order_payload())]))
        submitted = first_process.submit_order(_request(), authorization=_authorization())
        restarted_session = _Session([_Response(_order_payload())])
        restarted_process = _adapter(restarted_session)
        recovered = restarted_process.get_order_by_client_id(CLIENT_ID)
        self.assertEqual(submitted.order_id, recovered.order_id)
        self.assertEqual(CLIENT_ID, recovered.client_order_id)
        self.assertEqual(["GET"], [call[0] for call in restarted_session.calls])

    def test_adapter_is_not_wired_into_existing_runtime(self) -> None:
        import momentum_hunter.autonomy.simulation as simulation
        import momentum_hunter.engine_host as engine_host

        self.assertNotIn("AlpacaPaperBrokerAdapter", inspect.getsource(simulation))
        self.assertNotIn("AlpacaPaperBrokerAdapter", inspect.getsource(engine_host))


class AlpacaFractionalProofTests(unittest.TestCase):
    def test_readonly_preflight_requires_empty_account_and_fractionable_asset(self) -> None:
        session = _Session(
            [
                _Response(_account_payload()),
                _Response(_asset_payload()),
                _Response([]),
                _Response([]),
            ]
        )
        report = run_readonly_capability_preflight(_adapter(session))
        self.assertTrue(report["fractionable"])
        self.assertEqual(0, report["positions"])
        self.assertEqual(0, report["openOrders"])
        self.assertFalse(report["mutatingRequestAttempted"])

    def test_readonly_preflight_rejects_existing_order(self) -> None:
        session = _Session(
            [
                _Response(_account_payload()),
                _Response(_asset_payload()),
                _Response([]),
                _Response([_order_payload()]),
            ]
        )
        with self.assertRaisesRegex(AlpacaFractionalProofError, "open order"):
            run_readonly_capability_preflight(_adapter(session))

    def test_fractional_limit_cancel_proof_is_clean_and_write_once(self) -> None:
        proof_uuid = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        client_uuid = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
        proof_client_id = f"mh-paper-capability-{client_uuid.hex}"
        canceled = _order_payload(
            client_order_id=proof_client_id,
            status="canceled",
            canceled_at="2026-08-09T12:01:00Z",
        )
        session = _Session(
            [
                _Response(_account_payload()),
                _Response(_asset_payload()),
                _Response([]),
                _Response([]),
                _Response(_order_payload(client_order_id=proof_client_id)),
                _Response(_order_payload(client_order_id=proof_client_id)),
                _Response(_order_payload(client_order_id=proof_client_id)),
                _Response(None, status_code=204),
                _Response(canceled),
                _Response([]),
                _Response([]),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "momentum_hunter.alpaca_fractional_proof.uuid4",
                side_effect=(proof_uuid, client_uuid),
            ):
                report = run_fractional_limit_cancel_proof(
                    _adapter(session),
                    confirmation=PAPER_PROBE_CONFIRMATION,
                    output_directory=Path(directory),
                    plan=FractionalLimitCancelPlan(poll_interval_seconds=0),
                    sleep=lambda _seconds: None,
                )
            self.assertEqual("FRACTIONAL_LIMIT_CANCEL_PROVEN", report["classification"])
            self.assertTrue(report["providerAcceptedFractionalQuantity"])
            self.assertTrue(report["cleanAfterProof"])
            self.assertTrue(report["finalStateVerified"])
            self.assertEqual("canceled", report["terminalStatus"])
            self.assertEqual(64, len(report["implementationFingerprint"]))
            self.assertEqual(64, len(report["providerEvidenceFingerprint"]))
            proven = {
                item["name"]: item["state"]
                for item in report["capabilityRegistryAfter"]["capabilities"]
            }
            self.assertEqual("PROVEN", proven["supportsPaperEnvironment"])
            self.assertEqual("PROVEN", proven["supportsFractionalQuantity"])
            self.assertEqual("PROVEN", proven["supportsFractionalLimit"])
            self.assertEqual("PROVEN", proven["supportsCancel"])
            self.assertEqual("PROVEN", proven["supportsClientOrderId"])
            self.assertEqual(
                "DOCUMENTED_UNPROVEN",
                proven["fractionalQuantityPrecision"],
            )
            output = Path(report["outputPath"])
            self.assertTrue(output.is_file())
            rendered = output.read_text(encoding="utf-8")
            self.assertNotIn(KEY_ID, rendered)
            self.assertNotIn(SECRET_KEY, rendered)
            self.assertNotIn("account_number", rendered)

    def test_final_state_network_failure_writes_failed_evidence_without_retry(self) -> None:
        proof_uuid = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")
        client_uuid = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
        proof_client_id = f"mh-paper-capability-{client_uuid.hex}"
        canceled = _order_payload(
            client_order_id=proof_client_id,
            status="canceled",
            canceled_at="2026-08-09T12:01:00Z",
        )
        session = _Session(
            [
                _Response(_account_payload()),
                _Response(_asset_payload()),
                _Response([]),
                _Response([]),
                _Response(_order_payload(client_order_id=proof_client_id)),
                _Response(_order_payload(client_order_id=proof_client_id)),
                _Response(_order_payload(client_order_id=proof_client_id)),
                _Response(None, status_code=204),
                _Response(canceled),
                requests.ConnectionError("final verification unavailable"),
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "momentum_hunter.alpaca_fractional_proof.uuid4",
                side_effect=(proof_uuid, client_uuid),
            ), self.assertRaises(AlpacaFractionalProofError):
                run_fractional_limit_cancel_proof(
                    _adapter(session),
                    confirmation=PAPER_PROBE_CONFIRMATION,
                    output_directory=Path(directory),
                    plan=FractionalLimitCancelPlan(poll_interval_seconds=0),
                    sleep=lambda _seconds: None,
                )
            evidence = json.loads(next(Path(directory).glob("*.json")).read_text())
            self.assertFalse(evidence["finalStateVerified"])
            self.assertFalse(evidence["cleanAfterProof"])
            self.assertEqual("FRACTIONAL_LIMIT_CANCEL_FAILED", evidence["classification"])
            self.assertIn("Final Paper state verification failed", evidence["failure"])
            self.assertEqual(1, sum(call[0] == "POST" for call in session.calls))

    def test_proof_plan_is_fixed_to_one_dollar_nonmarketable_limit(self) -> None:
        with self.assertRaises(AlpacaFractionalProofError):
            FractionalLimitCancelPlan(limit_price=Decimal("3.00"))


if __name__ == "__main__":
    unittest.main()
