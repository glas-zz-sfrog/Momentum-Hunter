from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping
from unittest.mock import patch

import requests

from momentum_hunter.schwab_account_discovery import DiscoveredSchwabAccount
from momentum_hunter.schwab_candle_contract import SchwabCandleContractError
from momentum_hunter.schwab_candle_observer import (
    EXPECTED_WEBSOCKET_CLIENT_VERSION,
    EXPECTED_STREAMER_HOST,
    EXPECTED_STREAMER_PATH,
    GuardedStreamerAccess,
    CandleObservationOptions,
    SchwabCandleAccessGuard,
    SchwabCandleHttpTransport,
    SchwabCandleMarketHoursObserver,
    SchwabCandleObserverAuthorizationError,
    SchwabCandleObserverError,
    SchwabCandleObserverNetworkError,
    SchwabCandleObserverReauthorizationRequired,
    SchwabCandleObserverResponseError,
    StreamerBootstrap,
    WebSocketClientConnection,
    WebSocketClientFactory,
    build_observation_plan,
    build_streamer_login,
    main,
    parse_streamer_bootstrap,
    require_safe_output_path,
    require_streamer_acknowledgement,
    write_proof_once,
)
from momentum_hunter.schwab_market_data import SchwabMarketDataAuthorizationError
from momentum_hunter.schwab_onboarding import SchwabOAuthResponseError
from momentum_hunter.schwab_readonly import SchwabAccountBinding


ACCESS_TOKEN = "SYNTHETIC-OBSERVER-ACCESS-TOKEN"
ACCOUNT_NUMBER = "12342573"
ACCOUNT_ENDING = "2573"
ACCOUNT_HASH = "SYNTHETIC/OPAQUE+ACCOUNT=HASH"
OBSERVED_MINUTE = datetime(2026, 8, 3, 14, 35, tzinfo=timezone.utc)


def bootstrap_payload(
    *,
    accounts: list[dict[str, object]] | None = None,
    socket_url: str = f"wss://{EXPECTED_STREAMER_HOST}{EXPECTED_STREAMER_PATH}",
) -> dict[str, object]:
    return {
        "accounts": (
            accounts
            if accounts is not None
            else [{"accountNumber": ACCOUNT_NUMBER, "primaryAccount": True}]
        ),
        "streamerInfo": [
            {
                "streamerSocketUrl": socket_url,
                "schwabClientCustomerId": "SYNTHETIC-CUSTOMER",
                "schwabClientCorrelId": "SYNTHETIC-CORRELATION",
                "schwabClientChannel": "SYNTHETIC-CHANNEL",
                "schwabClientFunctionId": "SYNTHETIC-FUNCTION",
            }
        ],
        "offers": [{"mktDataPermission": "SYNTHETIC-PERMISSION"}],
    }


def ack(service: str, command: str, request_id: str, *, code: int = 0) -> dict[str, object]:
    return {
        "response": [
            {
                "service": service,
                "command": command,
                "requestid": request_id,
                "content": [{"code": code, "msg": "synthetic"}],
            }
        ]
    }


def stream_payload(
    symbol: str,
    *,
    timestamp: datetime = OBSERVED_MINUTE,
    close: float = 101.0,
    volume: int = 12_000,
    sequence: int = 7,
) -> dict[str, object]:
    return {
        "data": [
            {
                "service": "CHART_EQUITY",
                "timestamp": int((timestamp + timedelta(seconds=1)).timestamp() * 1000),
                "command": "SUBS",
                "content": [
                    {
                        "key": symbol,
                        "1": sequence,
                        "2": 100.0,
                        "3": max(101.5, close),
                        "4": 99.5,
                        "5": close,
                        "6": volume,
                        "7": int(timestamp.timestamp() * 1000),
                        "8": 20_308,
                    }
                ],
            }
        ]
    }


def history_payload(
    symbol: str,
    *,
    close: float = 101.0,
    volume: int = 12_000,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "empty": False,
        "candles": [
            {
                "open": 100.0,
                "high": max(101.5, close),
                "low": 99.5,
                "close": close,
                "volume": volume,
                "datetime": int(OBSERVED_MINUTE.timestamp() * 1000),
            }
        ],
    }


class FakeResponse:
    def __init__(
        self,
        payload: object,
        *,
        status_code: int = 200,
        is_redirect: bool = False,
        content: bytes | None = None,
        invalid_json: bool = False,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.is_redirect = is_redirect
        self.content = content if content is not None else json.dumps(payload).encode()
        self.invalid_json = invalid_json

    def json(self) -> object:
        if self.invalid_json:
            raise ValueError("synthetic invalid json")
        return self.payload


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None, *, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


class FakeTokenProvider:
    def __init__(self, token: str = ACCESS_TOKEN) -> None:
        self.token = token
        self.calls = 0

    def access_token(self) -> str:
        self.calls += 1
        return self.token


class FakeBindingStore:
    def __init__(self, binding: SchwabAccountBinding) -> None:
        self.binding = binding
        self.calls = 0

    def load(self) -> SchwabAccountBinding:
        self.calls += 1
        return self.binding


class FakeDiscovery:
    def __init__(self, accounts: list[DiscoveredSchwabAccount]) -> None:
        self.accounts = accounts
        self.tokens: list[str] = []

    def discover(self, token: str) -> list[DiscoveredSchwabAccount]:
        self.tokens.append(token)
        return self.accounts


class FakeDetails:
    def __init__(self, *, account_number: str = ACCOUNT_NUMBER, account_type: str = "CASH") -> None:
        self.account_number = account_number
        self.account_type = account_type
        self.calls: list[tuple[str, str]] = []

    def fetch(self, token: str, account_hash: str) -> dict[str, object]:
        self.calls.append((token, account_hash))
        return {
            "securitiesAccount": {
                "type": self.account_type,
                "accountNumber": self.account_number,
                "currentBalances": {"cashAvailableForTrading": 100.0},
            }
        }


class FakeAccessGuard:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def authorize(self, ending: str) -> GuardedStreamerAccess:
        self.calls.append(ending)
        return GuardedStreamerAccess(
            access_token=ACCESS_TOKEN,
            account_ending=ACCOUNT_ENDING,
            account_type="INDIVIDUAL_CASH",
            balances_present=True,
        )


class FakeHttpTransport:
    def __init__(self) -> None:
        self.bootstrap_calls: list[str] = []
        self.history_calls: list[dict[str, object]] = []

    def fetch_bootstrap(self, token: str) -> object:
        self.bootstrap_calls.append(token)
        return bootstrap_payload()

    def fetch_price_history(
        self,
        token: str,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        extended_hours: bool,
    ) -> object:
        self.history_calls.append(
            {
                "token": token,
                "symbol": symbol,
                "start": start_at,
                "end": end_at,
                "extended": extended_hours,
            }
        )
        return history_payload(
            symbol,
            close=101.2 if symbol == "SPY" else 101.0,
            volume=12_500 if symbol == "SPY" else 12_000,
        )


class FakeStream:
    def __init__(
        self,
        payloads: list[Mapping[str, object] | Exception | None],
    ) -> None:
        self.payloads = list(payloads)
        self.sent: list[dict[str, object]] = []
        self.closed = False

    def send_json(self, payload: Mapping[str, object]) -> None:
        self.sent.append(dict(payload))

    def receive_json(self, _timeout_seconds: float) -> Mapping[str, object] | None:
        if not self.payloads:
            return None
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return payload

    def close(self) -> None:
        self.closed = True


class FakeStreamFactory:
    def __init__(self, stream: FakeStream) -> None:
        self.stream = stream
        self.urls: list[str] = []

    def connect(self, url: str) -> FakeStream:
        self.urls.append(url)
        return self.stream


class SteppingClock:
    def __init__(self, start: datetime) -> None:
        self.current = start

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(milliseconds=250)
        return value


class SteppingMonotonic:
    def __init__(self, step: float = 1.0) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        self.value += self.step
        return self.value


class FakeWebSocketTimeout(Exception):
    pass


class FakeWebSocketModule:
    WebSocketTimeoutException = FakeWebSocketTimeout


class FakeWebSocket:
    def __init__(self, frames: list[object] | None = None) -> None:
        self.frames = list(frames or [])
        self.timeouts: list[float] = []
        self.sent: list[str] = []
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)

    def recv(self) -> object:
        if not self.frames:
            raise FakeWebSocketTimeout()
        frame = self.frames.pop(0)
        if isinstance(frame, Exception):
            raise frame
        return frame

    def send(self, value: str) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.closed = True


class SchwabCandleObserverTests(unittest.TestCase):
    def options(self, **kwargs: object) -> CandleObservationOptions:
        values: dict[str, object] = {
            "expected_account_ending": ACCOUNT_ENDING,
            "duration_seconds": 180,
        }
        values.update(kwargs)
        return CandleObservationOptions.create(["SPY", "IWM"], **values)

    def test_options_bound_symbols_account_and_duration(self) -> None:
        options = CandleObservationOptions.create(
            ["spy", "IWM", "spy"],
            expected_account_ending=ACCOUNT_ENDING,
            duration_seconds=300,
        )
        self.assertEqual(("SPY", "IWM"), options.symbols)
        with self.assertRaisesRegex(SchwabCandleObserverError, "limited"):
            CandleObservationOptions.create(
                [f"S{index}" for index in range(11)],
                expected_account_ending=ACCOUNT_ENDING,
            )
        with self.assertRaises(SchwabCandleObserverAuthorizationError):
            CandleObservationOptions.create(["SPY"], expected_account_ending="25")
        with self.assertRaisesRegex(SchwabCandleObserverError, "duration"):
            CandleObservationOptions.create(
                ["SPY"],
                expected_account_ending=ACCOUNT_ENDING,
                duration_seconds=30,
            )

    def test_plan_is_deterministic_and_has_no_runtime_authority(self) -> None:
        first = build_observation_plan(self.options())
        second = build_observation_plan(self.options())
        self.assertEqual(first, second)
        self.assertFalse(first["execute"])
        self.assertFalse(first["networkCalled"])
        self.assertFalse(first["productionDataWritten"])
        self.assertFalse(first["serviceInvoked"])
        self.assertFalse(first["engineHostInvoked"])
        self.assertFalse(first["wpfInvoked"])
        self.assertEqual("UNAVAILABLE", first["orderTransmission"])

    def test_cli_defaults_to_plan_without_constructing_observer(self) -> None:
        stdout = io.StringIO()
        with (
            patch(
                "momentum_hunter.schwab_candle_observer.SchwabCandleMarketHoursObserver",
                side_effect=AssertionError("observer must not be constructed"),
            ),
            redirect_stdout(stdout),
        ):
            result = main(
                [
                    "--symbols",
                    "SPY",
                    "IWM",
                    "--expected-account-ending",
                    ACCOUNT_ENDING,
                ]
            )
        self.assertEqual(0, result)
        report = json.loads(stdout.getvalue())
        self.assertFalse(report["networkCalled"])

    def test_access_guard_revalidates_exact_binding_without_positions_or_orders(self) -> None:
        binding = SchwabAccountBinding(
            account_hash=ACCOUNT_HASH,
            account_number_last_four=ACCOUNT_ENDING,
            account_type="INDIVIDUAL_CASH",
        )
        token = FakeTokenProvider()
        store = FakeBindingStore(binding)
        discovery = FakeDiscovery(
            [DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH)]
        )
        details = FakeDetails()
        guard = SchwabCandleAccessGuard(
            token_provider=token,
            binding_store=store,
            discovery_transport=discovery,
            details_transport=details,
        )
        access = guard.authorize(ACCOUNT_ENDING)
        self.assertEqual(ACCESS_TOKEN, access.access_token)
        self.assertEqual(1, token.calls)
        self.assertEqual([ACCESS_TOKEN], discovery.tokens)
        self.assertEqual([(ACCESS_TOKEN, ACCOUNT_HASH)], details.calls)
        evidence = access.evidence()
        self.assertEqual(1, evidence["authorizedAccountCount"])
        self.assertFalse(evidence["positionsRequested"])
        self.assertFalse(evidence["ordersRequested"])
        self.assertTrue(evidence["balancesReturnedByContract"])
        self.assertTrue(evidence["balanceValuesSuppressed"])
        self.assertNotIn(ACCOUNT_HASH, json.dumps(evidence))
        self.assertNotIn(ACCESS_TOKEN, repr(access))

    def test_access_guard_fails_on_multiple_or_changed_accounts(self) -> None:
        binding = SchwabAccountBinding(
            account_hash=ACCOUNT_HASH,
            account_number_last_four=ACCOUNT_ENDING,
            account_type="INDIVIDUAL_CASH",
        )
        multiple = SchwabCandleAccessGuard(
            token_provider=FakeTokenProvider(),
            binding_store=FakeBindingStore(binding),
            discovery_transport=FakeDiscovery(
                [
                    DiscoveredSchwabAccount(ACCOUNT_ENDING, ACCOUNT_HASH),
                    DiscoveredSchwabAccount("9999", "OTHER-HASH"),
                ]
            ),
            details_transport=FakeDetails(),
        )
        with self.assertRaises(SchwabCandleObserverAuthorizationError):
            multiple.authorize(ACCOUNT_ENDING)
        try:
            multiple.authorize(ACCOUNT_ENDING)
        except SchwabCandleObserverAuthorizationError as exc:
            self.assertIn("observed 2", str(exc))

        changed = SchwabCandleAccessGuard(
            token_provider=FakeTokenProvider(),
            binding_store=FakeBindingStore(binding),
            discovery_transport=FakeDiscovery(
                [DiscoveredSchwabAccount(ACCOUNT_ENDING, "CHANGED-HASH")]
            ),
            details_transport=FakeDetails(),
        )
        with self.assertRaisesRegex(
            SchwabCandleObserverAuthorizationError,
            "identity changed",
        ):
            changed.authorize(ACCOUNT_ENDING)

    def test_access_guard_classifies_rejected_refresh_as_reauthorization_required(self) -> None:
        class RejectedRefreshTokenProvider:
            def access_token(self) -> str:
                root = SchwabOAuthResponseError(
                    "Synthetic Schwab OAuth token exchange HTTP 400."
                )
                raise SchwabMarketDataAuthorizationError(
                    "Synthetic guarded refresh failed."
                ) from root

        guard = SchwabCandleAccessGuard(
            token_provider=RejectedRefreshTokenProvider(),
            binding_store=FakeBindingStore(
                SchwabAccountBinding(
                    account_hash=ACCOUNT_HASH,
                    account_number_last_four=ACCOUNT_ENDING,
                    account_type="INDIVIDUAL_CASH",
                )
            ),
            discovery_transport=FakeDiscovery([]),
            details_transport=FakeDetails(),
        )
        with self.assertRaisesRegex(
            SchwabCandleObserverReauthorizationRequired,
            "interactive reauthorization",
        ):
            guard.authorize(ACCOUNT_ENDING)

    def test_bootstrap_requires_one_account_expected_host_and_permission(self) -> None:
        parsed = parse_streamer_bootstrap(
            bootstrap_payload(),
            expected_account_ending=ACCOUNT_ENDING,
        )
        self.assertEqual(ACCOUNT_ENDING, parsed.account_ending)
        self.assertEqual(1, parsed.permission_count)
        evidence = parsed.evidence()
        self.assertFalse(evidence["rawAccountMetadataIncluded"])
        self.assertFalse(evidence["streamerIdentifiersIncluded"])

        with self.assertRaisesRegex(
            SchwabCandleObserverAuthorizationError,
            "exactly one",
        ):
            parse_streamer_bootstrap(
                bootstrap_payload(
                    accounts=[
                        {"accountNumber": ACCOUNT_NUMBER},
                        {"accountNumber": "12349999"},
                    ]
                ),
                expected_account_ending=ACCOUNT_ENDING,
            )
        with self.assertRaisesRegex(
            SchwabCandleObserverResponseError,
            "unexpected socket",
        ):
            parse_streamer_bootstrap(
                bootstrap_payload(socket_url="wss://example.com/ws"),
                expected_account_ending=ACCOUNT_ENDING,
            )
        missing_permission = bootstrap_payload()
        missing_permission["offers"] = []
        with self.assertRaisesRegex(
            SchwabCandleObserverAuthorizationError,
            "permission",
        ):
            parse_streamer_bootstrap(
                missing_permission,
                expected_account_ending=ACCOUNT_ENDING,
            )

    def test_login_and_ack_contracts_fail_closed(self) -> None:
        bootstrap = parse_streamer_bootstrap(
            bootstrap_payload(),
            expected_account_ending=ACCOUNT_ENDING,
        )
        login = build_streamer_login(ACCESS_TOKEN, bootstrap)
        row = login["requests"][0]
        self.assertEqual("ADMIN", row["service"])
        self.assertEqual("LOGIN", row["command"])
        self.assertEqual(ACCESS_TOKEN, row["parameters"]["Authorization"])
        require_streamer_acknowledgement(
            ack("ADMIN", "LOGIN", "0"),
            service="ADMIN",
            command="LOGIN",
            request_id="0",
        )
        object_content_ack = ack("ADMIN", "LOGIN", "0")
        object_content_ack["response"][0]["content"] = {
            "code": 0,
            "msg": "synthetic",
        }
        require_streamer_acknowledgement(
            object_content_ack,
            service="ADMIN",
            command="LOGIN",
            request_id="0",
        )
        with self.assertRaises(SchwabCandleObserverAuthorizationError):
            require_streamer_acknowledgement(
                ack("ADMIN", "LOGIN", "0", code=12),
                service="ADMIN",
                command="LOGIN",
                request_id="0",
            )
        with self.assertRaises(SchwabCandleObserverResponseError):
            require_streamer_acknowledgement(
                ack("ADMIN", "LOGIN", "9"),
                service="ADMIN",
                command="LOGIN",
                request_id="0",
            )

    def test_observer_ignores_heartbeat_before_acknowledgement(self) -> None:
        stream = FakeStream(
            [
                {"notify": [{"heartbeat": "synthetic"}]},
                ack("ADMIN", "LOGIN", "0"),
                {"notify": [{"heartbeat": "synthetic"}]},
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_payload("SPY"),
                stream_payload("IWM"),
            ]
        )
        observer = SchwabCandleMarketHoursObserver(
            access_guard=FakeAccessGuard(),
            http_transport=FakeHttpTransport(),
            stream_factory=FakeStreamFactory(stream),
            utc_clock=SteppingClock(OBSERVED_MINUTE + timedelta(seconds=1)),
            monotonic_clock=SteppingMonotonic(step=1.0),
        )
        proof = observer.observe(self.options())
        self.assertEqual("PASS", proof["shapeStatus"])
        self.assertTrue(stream.closed)

    def test_observer_preserves_data_delivered_with_subscription_ack(self) -> None:
        combined = ack("CHART_EQUITY", "SUBS", "1")
        combined["data"] = stream_payload("SPY")["data"]
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                combined,
                stream_payload("IWM"),
            ]
        )
        observer = SchwabCandleMarketHoursObserver(
            access_guard=FakeAccessGuard(),
            http_transport=FakeHttpTransport(),
            stream_factory=FakeStreamFactory(stream),
            utc_clock=SteppingClock(OBSERVED_MINUTE + timedelta(seconds=1)),
            monotonic_clock=SteppingMonotonic(step=10.0),
        )
        proof = observer.observe(self.options())
        self.assertEqual("PASS", proof["shapeStatus"])
        self.assertEqual(2, len(proof["updateObservations"]))
        self.assertEqual(
            proof["responseReceivedAt"],
            proof["updateObservations"][0]["receivedAt"],
        )

    def test_http_transport_uses_only_exact_get_endpoints(self) -> None:
        session = FakeSession(
            [
                FakeResponse(bootstrap_payload()),
                FakeResponse(history_payload("SPY")),
                FakeResponse(history_payload("SPY")),
            ]
        )
        transport = SchwabCandleHttpTransport(session=session)
        self.assertEqual(bootstrap_payload(), transport.fetch_bootstrap(ACCESS_TOKEN))
        transport.fetch_price_history(
            ACCESS_TOKEN,
            "SPY",
            start_at=OBSERVED_MINUTE - timedelta(minutes=10),
            end_at=OBSERVED_MINUTE + timedelta(minutes=1),
            extended_hours=False,
        )
        transport.fetch_daily_price_history(
            ACCESS_TOKEN,
            "SPY",
            start_at=OBSERVED_MINUTE - timedelta(days=365),
            end_at=OBSERVED_MINUTE + timedelta(minutes=1),
        )
        self.assertEqual(3, len(session.calls))
        for call in session.calls:
            self.assertFalse(call["allow_redirects"])
            self.assertEqual(f"Bearer {ACCESS_TOKEN}", call["headers"]["Authorization"])
        self.assertEqual("SPY", session.calls[1]["params"]["symbol"])
        self.assertEqual("daily", session.calls[2]["params"]["frequencyType"])
        self.assertFalse(session.calls[2]["params"]["needExtendedHoursData"])

    def test_http_transport_rejects_redirect_status_and_network_error(self) -> None:
        with self.assertRaises(SchwabCandleObserverResponseError):
            SchwabCandleHttpTransport(
                session=FakeSession([FakeResponse({}, is_redirect=True)])
            ).fetch_bootstrap(ACCESS_TOKEN)

    def test_websocket_connection_handles_json_timeout_and_close(self) -> None:
        socket = FakeWebSocket([json.dumps({"notify": [{"heartbeat": "x"}]})])
        connection = WebSocketClientConnection(socket, FakeWebSocketModule)
        connection.send_json({"z": 2, "a": 1})
        self.assertEqual('{"a":1,"z":2}', socket.sent[0])
        self.assertEqual(
            {"notify": [{"heartbeat": "x"}]},
            connection.receive_json(2.5),
        )
        self.assertIsNone(connection.receive_json(1.0))
        self.assertEqual([2.5, 1.0], socket.timeouts)
        connection.close()
        self.assertTrue(socket.closed)

    def test_websocket_connection_rejects_bad_or_oversize_frames(self) -> None:
        invalid = WebSocketClientConnection(FakeWebSocket(["not-json"]), FakeWebSocketModule)
        with self.assertRaisesRegex(SchwabCandleObserverResponseError, "valid JSON"):
            invalid.receive_json(1.0)
        oversize = WebSocketClientConnection(
            FakeWebSocket(["x" * (1024 * 1024 + 1)]),
            FakeWebSocketModule,
        )
        with self.assertRaisesRegex(SchwabCandleObserverResponseError, "exceeded"):
            oversize.receive_json(1.0)

    def test_websocket_factory_uses_exact_tls_endpoint_and_bypasses_proxy(self) -> None:
        socket = FakeWebSocket()
        fake_module = type(
            "FakeModule",
            (),
            {
                "WebSocketTimeoutException": FakeWebSocketTimeout,
                "__version__": EXPECTED_WEBSOCKET_CLIENT_VERSION,
                "create_connection": staticmethod(lambda *args, **kwargs: socket),
            },
        )
        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def create_connection(*args: object, **kwargs: object) -> FakeWebSocket:
            calls.append((args, kwargs))
            return socket

        fake_module.create_connection = create_connection
        factory = WebSocketClientFactory()
        with patch.dict("sys.modules", {"websocket": fake_module}):
            connection = factory.connect(
                f"wss://{EXPECTED_STREAMER_HOST}{EXPECTED_STREAMER_PATH}"
            )
        self.assertIsInstance(connection, WebSocketClientConnection)
        self.assertEqual(
            (f"wss://{EXPECTED_STREAMER_HOST}{EXPECTED_STREAMER_PATH}",),
            calls[0][0],
        )
        self.assertIsNone(calls[0][1]["http_proxy_host"])
        self.assertEqual([EXPECTED_STREAMER_HOST], calls[0][1]["http_no_proxy"])
        self.assertTrue(calls[0][1]["sslopt"]["check_hostname"])
        self.assertEqual(
            EXPECTED_WEBSOCKET_CLIENT_VERSION,
            connection.module.__version__,
        )
        self.assertEqual(
            EXPECTED_WEBSOCKET_CLIENT_VERSION,
            factory.dependency_version,
        )
        with self.assertRaisesRegex(SchwabCandleObserverResponseError, "unexpected"):
            WebSocketClientFactory().connect("wss://example.com/ws")

        wrong_version = type(
            "WrongVersionModule",
            (),
            {
                "WebSocketTimeoutException": FakeWebSocketTimeout,
                "__version__": "0.0.0",
                "create_connection": staticmethod(create_connection),
            },
        )
        with (
            patch.dict("sys.modules", {"websocket": wrong_version}),
            self.assertRaisesRegex(
                SchwabCandleObserverNetworkError,
                "unexpected websocket-client version",
            ),
        ):
            WebSocketClientFactory().connect(
                f"wss://{EXPECTED_STREAMER_HOST}{EXPECTED_STREAMER_PATH}"
            )
        with self.assertRaisesRegex(SchwabCandleObserverResponseError, "HTTP 503"):
            SchwabCandleHttpTransport(
                session=FakeSession([FakeResponse({}, status_code=503)])
            ).fetch_bootstrap(ACCESS_TOKEN)
        with self.assertRaises(SchwabCandleObserverNetworkError):
            SchwabCandleHttpTransport(
                session=FakeSession(error=requests.ConnectionError("synthetic"))
            ).fetch_bootstrap(ACCESS_TOKEN)

    def test_observer_preserves_updates_reconciles_and_redacts(self) -> None:
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_payload("SPY"),
                stream_payload("IWM"),
                stream_payload("SPY", close=101.2, volume=12_500, sequence=8),
            ]
        )
        factory = FakeStreamFactory(stream)
        http = FakeHttpTransport()
        guard = FakeAccessGuard()
        observer = SchwabCandleMarketHoursObserver(
            access_guard=guard,
            http_transport=http,
            stream_factory=factory,
            utc_clock=SteppingClock(OBSERVED_MINUTE + timedelta(seconds=1)),
            monotonic_clock=SteppingMonotonic(step=10.0),
        )
        proof = observer.observe(self.options())

        self.assertEqual("PARTIAL", proof["proofStatus"])
        self.assertEqual("PASS", proof["shapeStatus"])
        self.assertEqual(3, len(proof["updateObservations"]))
        self.assertIn("INTRA_MINUTE_STREAM_REVISION_OBSERVED", proof["findings"])
        reconciliation = proof["streamHistoryReconciliation"]
        self.assertEqual(2, reconciliation["matchingMinuteCount"])
        self.assertTrue(reconciliation["allComparableMinutesMatch"])
        self.assertEqual([ACCOUNT_ENDING], guard.calls)
        self.assertEqual([ACCESS_TOKEN], http.bootstrap_calls)
        self.assertEqual({"SPY", "IWM"}, {row["symbol"] for row in http.history_calls})
        self.assertEqual(2, len(stream.sent))
        self.assertTrue(stream.closed)
        serialized = json.dumps(proof, sort_keys=True)
        self.assertNotIn(ACCESS_TOKEN, serialized)
        self.assertNotIn(ACCOUNT_HASH, serialized)
        self.assertFalse(proof["productionDataWritten"])
        self.assertFalse(proof["serviceInvoked"])
        self.assertFalse(proof["engineHostInvoked"])
        self.assertFalse(proof["wpfInvoked"])
        self.assertEqual("UNAVAILABLE", proof["orderTransmission"])
        self.assertRegex(proof["proofFingerprint"], r"^[0-9A-F]{64}$")
        identity = proof["implementationIdentity"]
        self.assertRegex(identity["observerModuleSha256"], r"^[0-9A-F]{64}$")
        self.assertRegex(identity["candleContractModuleSha256"], r"^[0-9A-F]{64}$")
        self.assertEqual(
            EXPECTED_WEBSOCKET_CLIENT_VERSION,
            identity["expectedWebsocketClientVersion"],
        )
        self.assertEqual(2, len(proof["priceHistoryRequests"]))
        self.assertTrue(
            all(row["responseSeconds"] >= 0 for row in proof["priceHistoryRequests"])
        )

    def test_history_failure_preserves_stream_proof_and_is_visible(self) -> None:
        class PartialHistory(FakeHttpTransport):
            def fetch_price_history(
                self,
                token: str,
                symbol: str,
                *,
                start_at: datetime,
                end_at: datetime,
                extended_hours: bool,
            ) -> object:
                if symbol == "IWM":
                    raise SchwabCandleObserverNetworkError(
                        "Synthetic history endpoint unavailable."
                    )
                return super().fetch_price_history(
                    token,
                    symbol,
                    start_at=start_at,
                    end_at=end_at,
                    extended_hours=extended_hours,
                )

        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_payload("SPY"),
                stream_payload("IWM"),
            ]
        )
        proof = SchwabCandleMarketHoursObserver(
            access_guard=FakeAccessGuard(),
            http_transport=PartialHistory(),
            stream_factory=FakeStreamFactory(stream),
            utc_clock=SteppingClock(OBSERVED_MINUTE + timedelta(seconds=1)),
            monotonic_clock=SteppingMonotonic(step=10.0),
        ).observe(self.options())
        self.assertEqual("PASS", proof["shapeStatus"])
        self.assertEqual("PARTIAL", proof["priceHistoryStatus"])
        self.assertIn("PRICE_HISTORY_RECONCILIATION_INCOMPLETE", proof["findings"])
        failed = [row for row in proof["priceHistoryRequests"] if row["status"] == "FAIL"]
        self.assertEqual(["IWM"], [row["symbol"] for row in failed])
        self.assertEqual(2, len(proof["updateObservations"]))

    def test_observer_rejects_invalid_live_frame_before_history(self) -> None:
        invalid = stream_payload("SPY")
        del invalid["data"][0]["content"][0]["6"]
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                invalid,
            ]
        )
        http = FakeHttpTransport()

        with self.assertRaisesRegex(SchwabCandleContractError, "field 6"):
            SchwabCandleMarketHoursObserver(
                access_guard=FakeAccessGuard(),
                http_transport=http,
                stream_factory=FakeStreamFactory(stream),
                utc_clock=SteppingClock(OBSERVED_MINUTE + timedelta(seconds=1)),
                monotonic_clock=SteppingMonotonic(step=10.0),
            ).observe(self.options())

        self.assertEqual([], http.history_calls)
        self.assertTrue(stream.closed)

    def test_stream_disconnect_preserves_received_candles_and_failure(self) -> None:
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_payload("SPY"),
                stream_payload("IWM"),
                SchwabCandleObserverNetworkError("Synthetic disconnect."),
            ]
        )
        proof = SchwabCandleMarketHoursObserver(
            access_guard=FakeAccessGuard(),
            http_transport=FakeHttpTransport(),
            stream_factory=FakeStreamFactory(stream),
            utc_clock=SteppingClock(OBSERVED_MINUTE + timedelta(seconds=1)),
            monotonic_clock=SteppingMonotonic(step=10.0),
        ).observe(self.options())
        self.assertEqual("PASS", proof["shapeStatus"])
        self.assertEqual("FAIL", proof["streamStatus"])
        self.assertIn("STREAM_DISCONNECTED_DURING_OBSERVATION", proof["findings"])
        self.assertEqual(2, len(proof["updateObservations"]))
        self.assertTrue(stream.closed)

    def test_observer_rejects_source_identity_change_during_run(self) -> None:
        stream = FakeStream(
            [
                ack("ADMIN", "LOGIN", "0"),
                ack("CHART_EQUITY", "SUBS", "1"),
                stream_payload("SPY"),
                stream_payload("IWM"),
            ]
        )
        observer = SchwabCandleMarketHoursObserver(
            access_guard=FakeAccessGuard(),
            http_transport=FakeHttpTransport(),
            stream_factory=FakeStreamFactory(stream),
            utc_clock=SteppingClock(OBSERVED_MINUTE + timedelta(seconds=1)),
            monotonic_clock=SteppingMonotonic(step=10.0),
        )
        with (
            patch(
                "momentum_hunter.schwab_candle_observer."
                "_implementation_source_identity",
                side_effect=[
                    {
                        "observerModuleSha256": "A" * 64,
                        "candleContractModuleSha256": "B" * 64,
                    },
                    {
                        "observerModuleSha256": "C" * 64,
                        "candleContractModuleSha256": "B" * 64,
                    },
                ],
            ),
            self.assertRaisesRegex(
                SchwabCandleObserverError,
                "source identity changed",
            ),
        ):
            observer.observe(self.options())
        self.assertTrue(stream.closed)

    def test_observer_rejects_closed_session_before_authorization(self) -> None:
        guard = FakeAccessGuard()
        observer = SchwabCandleMarketHoursObserver(
            access_guard=guard,
            http_transport=FakeHttpTransport(),
            stream_factory=FakeStreamFactory(FakeStream([])),
            utc_clock=lambda: datetime(2026, 8, 1, 14, 0, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(SchwabCandleObserverError, "market session"):
            observer.observe(self.options())
        self.assertEqual([], guard.calls)

        holiday_guard = FakeAccessGuard()
        holiday = SchwabCandleMarketHoursObserver(
            access_guard=holiday_guard,
            http_transport=FakeHttpTransport(),
            stream_factory=FakeStreamFactory(FakeStream([])),
            utc_clock=lambda: datetime(2026, 7, 3, 15, 0, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(SchwabCandleObserverError, "market session"):
            holiday.observe(self.options())
        self.assertEqual([], holiday_guard.calls)

    def test_write_once_output_stays_outside_repository_and_never_overwrites(self) -> None:
        proof = {"proofStatus": "PARTIAL", "orderTransmission": "UNAVAILABLE"}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candle-proof.json"
            written = write_proof_once(proof, path)
            before = written.read_bytes()
            self.assertEqual(proof, json.loads(before))
            with self.assertRaisesRegex(SchwabCandleObserverError, "already exists"):
                write_proof_once({"changed": True}, path)
            self.assertEqual(before, written.read_bytes())
            self.assertEqual([], list(Path(temporary).glob("*.tmp")))

        repo_output = Path(__file__).resolve().parents[1] / "forbidden-proof.json"
        with self.assertRaisesRegex(SchwabCandleObserverError, "outside"):
            require_safe_output_path(repo_output)

    def test_module_defers_websocket_dependency_and_has_no_order_capability(self) -> None:
        import inspect
        import momentum_hunter.schwab_candle_observer as module

        source = inspect.getsource(module)
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)
        self.assertNotIn("replace_order", source)
        self.assertNotIn("/orders", source)
        self.assertNotIn("MomentumHunterData", source)
        self.assertNotIn("engine_host", source.lower())
        self.assertNotIn("automation_supervisor", source)

    def test_powershell_runner_is_plan_first_and_has_no_runtime_authority(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runner = root / "tools" / "run_schwab_candle_observer.ps1"
        source = runner.read_text(encoding="utf-8")
        self.assertIn('[switch]$Execute', source)
        self.assertIn('"SPY"', source)
        self.assertIn('"IWM"', source)
        self.assertIn('R031-websocket-client-1.9.0', source)
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)
        self.assertNotIn("replace_order", source)
        self.assertNotIn("automation-manifest", source)
        self.assertNotIn("MomentumHunterData", source)

    def test_powershell_runner_parses_and_executes_zero_network_plan(self) -> None:
        root = Path(__file__).resolve().parents[1]
        runner = root / "tools" / "run_schwab_candle_observer.ps1"
        parse = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                (
                    "$errors=$null; [System.Management.Automation.Language.Parser]"
                    f"::ParseFile('{runner}', [ref]$null, [ref]$errors) | Out-Null; "
                    "if($errors.Count){$errors | Out-String; exit 1}"
                ),
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, parse.returncode, parse.stdout + parse.stderr)
        with tempfile.TemporaryDirectory() as unrelated_directory:
            stale_package = Path(unrelated_directory) / "momentum_hunter"
            stale_package.mkdir()
            (stale_package / "__init__.py").write_text(
                'STALE_CALLER_PACKAGE = True\n',
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(runner),
                    "-CandidateSymbol",
                    "CRWV",
                    "-ProjectRoot",
                    str(root),
                ],
                cwd=unrelated_directory,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        plan = json.loads(result.stdout)
        self.assertFalse(plan["networkCalled"])
        self.assertFalse(plan["productionDataWritten"])
        self.assertEqual(["SPY", "IWM", "CRWV"], plan["symbols"])
        self.assertEqual("UNAVAILABLE", plan["orderTransmission"])


if __name__ == "__main__":
    unittest.main()
