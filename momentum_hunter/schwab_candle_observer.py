"""One-shot, nonpersisting Schwab market-hours candle observation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence
from urllib.parse import urlparse

import requests

from momentum_hunter import schwab_candle_contract as candle_contract_module
from momentum_hunter.schwab_account_discovery import (
    SchwabAccountDiscoveryError,
    SchwabAccountNumbersTransport,
)
from momentum_hunter.schwab_account_validation import (
    SchwabAccountDetailsTransport,
    SchwabAccountValidationError,
    build_unpersisted_binding_candidate,
    parse_account_identity,
    require_single_expected_account,
)
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    MAX_INPUT_BYTES,
    MAX_PROOF_MESSAGES,
    SCHWAB_CHART_EQUITY_SERVICE,
    SCHWAB_PRICE_HISTORY_URL,
    SCHWAB_USER_PREFERENCE_URL,
    SchwabCandleContractError,
    build_chart_equity_subscription,
    build_nonpersisting_stream_proof,
    build_price_history_parameters,
    normalize_symbols,
    parse_chart_equity_messages,
    session_for_timestamp,
)
from momentum_hunter.scheduling import is_market_open_day
from momentum_hunter.schwab_market_data import (
    BoundSchwabAccessTokenProvider,
    SchwabMarketDataAuthorizationError,
)
from momentum_hunter.schwab_onboarding import (
    EncryptedSchwabAccountBindingStore,
    SchwabOAuthError,
    SchwabOAuthResponseError,
)
from momentum_hunter.schwab_readonly import (
    EXPECTED_ACCOUNT_TYPE,
    AccountIsolationError,
)
from momentum_hunter.schwab_setup import SchwabSetupError


OBSERVER_SCHEMA_VERSION = 1
OBSERVER_MODE = "SCHWAB_CHART_EQUITY_MARKET_HOURS_OBSERVER"
EXPECTED_CANDIDATE_REPORT_SESSION = "opening"
EXPECTED_STREAMER_HOST = "streamer-api.schwab.com"
EXPECTED_STREAMER_PATH = "/ws"
MAX_HTTP_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_STREAM_FRAME_BYTES = 1024 * 1024
MAX_OBSERVER_SYMBOLS = 10
MIN_OBSERVATION_SECONDS = 180
MAX_OBSERVATION_SECONDS = 900
DEFAULT_OBSERVATION_SECONDS = 300
HTTP_TIMEOUT = (5.0, 30.0)
ACK_TIMEOUT_SECONDS = 15.0
EXPECTED_WEBSOCKET_CLIENT_VERSION = "1.9.0"


class SchwabCandleObserverError(RuntimeError):
    pass


class SchwabCandleObserverAuthorizationError(SchwabCandleObserverError):
    pass


class SchwabCandleObserverReauthorizationRequired(
    SchwabCandleObserverAuthorizationError
):
    pass


class SchwabCandleObserverNetworkError(SchwabCandleObserverError):
    pass


class SchwabCandleObserverResponseError(SchwabCandleObserverError):
    pass


@dataclass(frozen=True)
class CandidateSourceEvidence:
    report_name: str
    report_sha256: str
    schema_version: int
    generated_at: datetime
    source_session: str
    candidate_symbol: str
    candidate_rank: int

    def evidence(self) -> dict[str, object]:
        return {
            "reportName": self.report_name,
            "reportSha256": self.report_sha256,
            "schemaVersion": self.schema_version,
            "generatedAt": self.generated_at.isoformat(),
            "sourceSession": self.source_session,
            "selectionRule": "LOWEST_UNIQUE_POSITIVE_RANK",
            "candidateSymbol": self.candidate_symbol,
            "candidateRank": self.candidate_rank,
            "reportPathIncluded": False,
        }


@dataclass(frozen=True, repr=False)
class GuardedStreamerAccess:
    access_token: str
    account_ending: str
    account_type: str
    balances_present: bool

    def __repr__(self) -> str:
        return (
            "GuardedStreamerAccess(access_token='[redacted]', "
            f"account_ending={self.account_ending!r}, "
            f"account_type={self.account_type!r}, "
            f"balances_present={self.balances_present!r})"
        )

    def evidence(self) -> dict[str, object]:
        return {
            "authorizedAccountCount": 1,
            "accountEnding": self.account_ending,
            "accountType": self.account_type,
            "bindingMatch": True,
            "accountHashIncluded": False,
            "accountDetailsRequested": True,
            "balancesReturnedByContract": self.balances_present,
            "balanceValuesSuppressed": True,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }


@dataclass(frozen=True, repr=False)
class StreamerBootstrap:
    socket_url: str
    customer_id: str
    correlation_id: str
    channel: str
    function_id: str
    account_ending: str
    permission_count: int

    def __repr__(self) -> str:
        return (
            "StreamerBootstrap(socket_url='[validated Schwab WSS]', "
            "customer_id='[redacted]', correlation_id='[redacted]', "
            f"account_ending={self.account_ending!r}, "
            f"permission_count={self.permission_count!r})"
        )

    def evidence(self) -> dict[str, object]:
        return {
            "socketHost": EXPECTED_STREAMER_HOST,
            "socketPath": EXPECTED_STREAMER_PATH,
            "streamerIdentityPresent": True,
            "authorizedAccountCount": 1,
            "accountEnding": self.account_ending,
            "marketDataPermissionCount": self.permission_count,
            "rawAccountMetadataIncluded": False,
            "streamerIdentifiersIncluded": False,
        }


@dataclass(frozen=True)
class CandleObservationOptions:
    symbols: tuple[str, ...]
    expected_account_ending: str
    duration_seconds: int = DEFAULT_OBSERVATION_SECONDS
    extended_hours: bool = False
    candidate_source: CandidateSourceEvidence | None = None

    @classmethod
    def create(
        cls,
        symbols: Sequence[str],
        *,
        expected_account_ending: str,
        duration_seconds: int = DEFAULT_OBSERVATION_SECONDS,
        extended_hours: bool = False,
        candidate_source: CandidateSourceEvidence | None = None,
    ) -> "CandleObservationOptions":
        normalized = normalize_symbols(symbols)
        if len(normalized) > MAX_OBSERVER_SYMBOLS:
            raise SchwabCandleObserverError(
                f"Candle observation is limited to {MAX_OBSERVER_SYMBOLS} symbols."
            )
        ending = expected_account_ending.strip()
        if len(ending) != 4 or not ending.isdigit():
            raise SchwabCandleObserverAuthorizationError(
                "Expected account ending must contain exactly four digits."
            )
        if not MIN_OBSERVATION_SECONDS <= duration_seconds <= MAX_OBSERVATION_SECONDS:
            raise SchwabCandleObserverError(
                "Observation duration must be between "
                f"{MIN_OBSERVATION_SECONDS} and {MAX_OBSERVATION_SECONDS} seconds."
            )
        return cls(
            symbols=normalized,
            expected_account_ending=ending,
            duration_seconds=duration_seconds,
            extended_hours=extended_hours,
            candidate_source=candidate_source,
        )

    def evidence(self) -> dict[str, object]:
        evidence: dict[str, object] = {
            "symbols": list(self.symbols),
            "expectedAccountEnding": self.expected_account_ending,
            "durationSeconds": self.duration_seconds,
            "extendedHoursAllowed": self.extended_hours,
        }
        if self.candidate_source is not None:
            evidence["candidateSource"] = self.candidate_source.evidence()
        return evidence


def load_candidate_source(report_path: Path) -> CandidateSourceEvidence:
    source = report_path.expanduser().resolve()
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise SchwabCandleObserverError(
            "Hunter candidate report could not be read."
        ) from exc
    if not raw or len(raw) > MAX_INPUT_BYTES:
        raise SchwabCandleObserverError(
            "Hunter candidate report was empty or exceeded the size limit."
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabCandleObserverError(
            "Hunter candidate report was not valid JSON."
        ) from exc
    if not isinstance(payload, Mapping):
        raise SchwabCandleObserverError(
            "Hunter candidate report must be a JSON object."
        )
    metadata = payload.get("metadata")
    rows = payload.get("candidates")
    if not isinstance(metadata, Mapping) or not isinstance(rows, list) or not rows:
        raise SchwabCandleObserverError(
            "Hunter candidate report omitted metadata or candidate rows."
        )
    source_session = str(metadata.get("source_session", "")).strip().lower()
    if source_session != EXPECTED_CANDIDATE_REPORT_SESSION:
        raise SchwabCandleObserverError(
            "Hunter candidate report was not an opening-session report."
        )
    raw_generated_at = metadata.get("generated_at")
    try:
        generated_at = datetime.fromisoformat(str(raw_generated_at))
    except (TypeError, ValueError) as exc:
        raise SchwabCandleObserverError(
            "Hunter candidate report generation timestamp was invalid."
        ) from exc
    generated_at = _aware_now(generated_at)

    ranked: list[tuple[int, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise SchwabCandleObserverError(
                "Hunter candidate report contained an invalid candidate row."
            )
        rank = row.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise SchwabCandleObserverError(
                "Hunter candidate report contained an invalid candidate rank."
            )
        symbol = normalize_symbols((str(row.get("symbol", "")),))[0]
        ranked.append((rank, symbol))
    ranked.sort(key=lambda item: (item[0], item[1]))
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        raise SchwabCandleObserverError(
            "Hunter candidate report did not have a unique top-ranked candidate."
        )
    candidate_rank, candidate_symbol = ranked[0]
    if candidate_symbol in {"SPY", "IWM"}:
        raise SchwabCandleObserverError(
            "Hunter candidate report selected a benchmark instead of a candidate."
        )
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise SchwabCandleObserverError(
            "Hunter candidate report schema version was invalid."
        )
    return CandidateSourceEvidence(
        report_name=source.name,
        report_sha256=hashlib.sha256(raw).hexdigest().upper(),
        schema_version=schema_version,
        generated_at=generated_at,
        source_session=source_session,
        candidate_symbol=candidate_symbol,
        candidate_rank=candidate_rank,
    )


class StreamConnection(Protocol):
    def send_json(self, payload: Mapping[str, object]) -> None: ...

    def receive_json(self, timeout_seconds: float) -> Mapping[str, object] | None: ...

    def close(self) -> None: ...


class StreamConnectionFactory(Protocol):
    def connect(self, socket_url: str) -> StreamConnection: ...


class SchwabCandleAccessGuard:
    """Revalidate the immutable sole-CASH binding before Streamer bootstrap."""

    def __init__(
        self,
        *,
        token_provider: object | None = None,
        binding_store: EncryptedSchwabAccountBindingStore | None = None,
        discovery_transport: SchwabAccountNumbersTransport | None = None,
        details_transport: SchwabAccountDetailsTransport | None = None,
    ) -> None:
        self.token_provider = token_provider or BoundSchwabAccessTokenProvider()
        self.bindings = binding_store or EncryptedSchwabAccountBindingStore()
        self.discovery = discovery_transport or SchwabAccountNumbersTransport()
        self.details = details_transport or SchwabAccountDetailsTransport()

    def authorize(self, expected_account_ending: str) -> GuardedStreamerAccess:
        try:
            binding = self.bindings.load()
            if binding.account_number_last_four != expected_account_ending:
                raise SchwabCandleObserverAuthorizationError(
                    "Pinned Schwab account ending did not match the expected observer account."
                )
            if binding.account_type != EXPECTED_ACCOUNT_TYPE:
                raise SchwabCandleObserverAuthorizationError(
                    "Pinned Schwab account type was not the required individual cash account."
                )
            access_token = self.token_provider.access_token()
            accounts = self.discovery.discover(access_token)
            if len(accounts) != 1:
                raise SchwabCandleObserverAuthorizationError(
                    "Schwab account revalidation expected one authorized account; "
                    f"observed {len(accounts)}. Streamer remains locked."
                )
            discovered = require_single_expected_account(
                accounts,
                expected_account_ending,
            )
            if discovered.account_hash != binding.account_hash:
                raise SchwabCandleObserverAuthorizationError(
                    "Authorized Schwab account identity changed; Streamer remains locked."
                )
            identity = parse_account_identity(
                self.details.fetch(access_token, discovered.account_hash),
                discovered,
            )
            if build_unpersisted_binding_candidate(identity) != binding:
                raise SchwabCandleObserverAuthorizationError(
                    "Authorized Schwab cash identity changed; Streamer remains locked."
                )
        except SchwabCandleObserverAuthorizationError:
            raise
        except SchwabMarketDataAuthorizationError as exc:
            if _exception_chain_contains(exc, SchwabOAuthResponseError):
                raise SchwabCandleObserverReauthorizationRequired(
                    "Schwab OAuth refresh was rejected; interactive reauthorization is required."
                ) from exc
            raise SchwabCandleObserverAuthorizationError(
                "Schwab Streamer account revalidation failed safely."
            ) from exc
        except (
            SchwabAccountDiscoveryError,
            SchwabAccountValidationError,
            SchwabOAuthError,
            SchwabSetupError,
            AccountIsolationError,
        ) as exc:
            raise SchwabCandleObserverAuthorizationError(
                "Schwab Streamer account revalidation failed safely."
            ) from exc
        return GuardedStreamerAccess(
            access_token=access_token,
            account_ending=binding.account_number_last_four,
            account_type=binding.account_type,
            balances_present=identity.balances_present,
        )


class SchwabCandleHttpTransport:
    """Exact-host GET-only transport for bootstrap and bounded history."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = HTTP_TIMEOUT,
    ) -> None:
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.timeout = timeout

    def fetch_bootstrap(self, access_token: str) -> object:
        return self._get_json(
            SCHWAB_USER_PREFERENCE_URL,
            access_token=access_token,
            params=None,
        )

    def fetch_price_history(
        self,
        access_token: str,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        extended_hours: bool,
    ) -> object:
        return self._get_json(
            SCHWAB_PRICE_HISTORY_URL,
            access_token=access_token,
            params=build_price_history_parameters(
                symbol,
                start_at=start_at,
                end_at=end_at,
                extended_hours=extended_hours,
            ),
        )

    def _get_json(
        self,
        url: str,
        *,
        access_token: str,
        params: Mapping[str, object] | None,
    ) -> object:
        if not access_token.strip():
            raise SchwabCandleObserverAuthorizationError(
                "Schwab candle observation requires an active OAuth token."
            )
        if url not in {SCHWAB_USER_PREFERENCE_URL, SCHWAB_PRICE_HISTORY_URL}:
            raise SchwabCandleObserverNetworkError(
                "Schwab candle observation refused an unrecognized HTTP endpoint."
            )
        try:
            response = self.session.get(
                url,
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {access_token}",
                    "Cache-Control": "no-store",
                },
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise SchwabCandleObserverNetworkError(
                "Schwab candle observation could not reach its exact GET endpoint."
            ) from None
        if response.is_redirect:
            raise SchwabCandleObserverResponseError(
                "Schwab candle observation refused an HTTP redirect."
            )
        if response.status_code != 200:
            raise SchwabCandleObserverResponseError(
                f"Schwab candle observation failed safely with HTTP {response.status_code}."
            )
        if len(response.content) > MAX_HTTP_RESPONSE_BYTES:
            raise SchwabCandleObserverResponseError(
                "Schwab candle observation response exceeded its size limit."
            )
        try:
            return response.json()
        except ValueError:
            raise SchwabCandleObserverResponseError(
                "Schwab candle observation response was not valid JSON."
            ) from None


def parse_streamer_bootstrap(
    payload: object,
    *,
    expected_account_ending: str,
) -> StreamerBootstrap:
    if not isinstance(payload, Mapping):
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer bootstrap had an invalid shape."
        )
    accounts = payload.get("accounts")
    if not isinstance(accounts, list) or len(accounts) != 1:
        count = len(accounts) if isinstance(accounts, list) else 0
        raise SchwabCandleObserverAuthorizationError(
            "Schwab Streamer bootstrap did not contain exactly one authorized "
            f"account; observed {count}."
        )
    account = accounts[0]
    if not isinstance(account, Mapping):
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer bootstrap account metadata had an invalid shape."
        )
    account_number = account.get("accountNumber")
    if not isinstance(account_number, str) or len(account_number.strip()) < 4:
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer bootstrap omitted the account identity."
        )
    account_ending = account_number.strip()[-4:]
    if account_ending != expected_account_ending:
        raise SchwabCandleObserverAuthorizationError(
            "Schwab Streamer bootstrap account did not match the pinned ending."
        )

    streamer_rows = payload.get("streamerInfo")
    if not isinstance(streamer_rows, list) or len(streamer_rows) != 1:
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer bootstrap did not contain exactly one Streamer identity."
        )
    streamer = streamer_rows[0]
    if not isinstance(streamer, Mapping):
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer identity had an invalid shape."
        )
    values: dict[str, str] = {}
    for key in (
        "streamerSocketUrl",
        "schwabClientCustomerId",
        "schwabClientCorrelId",
        "schwabClientChannel",
        "schwabClientFunctionId",
    ):
        value = streamer.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > 2048:
            raise SchwabCandleObserverResponseError(
                "Schwab Streamer bootstrap omitted required identity metadata."
            )
        values[key] = value.strip()
    _validate_streamer_url(values["streamerSocketUrl"])

    offers = payload.get("offers")
    if not isinstance(offers, list) or not offers:
        raise SchwabCandleObserverAuthorizationError(
            "Schwab Streamer bootstrap omitted market-data permission evidence."
        )
    permissions = {
        str(offer.get("mktDataPermission", "")).strip()
        for offer in offers
        if isinstance(offer, Mapping)
        and str(offer.get("mktDataPermission", "")).strip()
    }
    if not permissions:
        raise SchwabCandleObserverAuthorizationError(
            "Schwab Streamer bootstrap did not grant a visible market-data permission."
        )
    return StreamerBootstrap(
        socket_url=values["streamerSocketUrl"],
        customer_id=values["schwabClientCustomerId"],
        correlation_id=values["schwabClientCorrelId"],
        channel=values["schwabClientChannel"],
        function_id=values["schwabClientFunctionId"],
        account_ending=account_ending,
        permission_count=len(permissions),
    )


def _validate_streamer_url(value: str) -> None:
    parsed = urlparse(value)
    if (
        parsed.scheme.lower() != "wss"
        or parsed.hostname != EXPECTED_STREAMER_HOST
        or parsed.path != EXPECTED_STREAMER_PATH
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer bootstrap returned an unexpected socket endpoint."
        )


def build_streamer_login(
    access_token: str,
    bootstrap: StreamerBootstrap,
    *,
    request_id: str = "0",
) -> dict[str, object]:
    if not access_token.strip():
        raise SchwabCandleObserverAuthorizationError(
            "Schwab Streamer login requires an active OAuth token."
        )
    return {
        "requests": [
            {
                "service": "ADMIN",
                "command": "LOGIN",
                "requestid": str(request_id),
                "SchwabClientCustomerId": bootstrap.customer_id,
                "SchwabClientCorrelId": bootstrap.correlation_id,
                "parameters": {
                    "Authorization": access_token,
                    "SchwabClientChannel": bootstrap.channel,
                    "SchwabClientFunctionId": bootstrap.function_id,
                },
            }
        ]
    }


def require_streamer_acknowledgement(
    payload: object,
    *,
    service: str,
    command: str,
    request_id: str,
) -> None:
    if not isinstance(payload, Mapping):
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer acknowledgement had an invalid shape."
        )
    responses = payload.get("response")
    if not isinstance(responses, list):
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer acknowledgement omitted its response."
        )
    matching = [
        row
        for row in responses
        if isinstance(row, Mapping)
        and str(row.get("service", "")) == service
        and str(row.get("command", "")) == command
        and str(row.get("requestid", "")) == request_id
    ]
    if len(matching) != 1:
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer acknowledgement did not match the expected request."
        )
    content = matching[0].get("content")
    if isinstance(content, Mapping):
        acknowledgement = content
    elif (
        isinstance(content, list)
        and len(content) == 1
        and isinstance(content[0], Mapping)
    ):
        acknowledgement = content[0]
    else:
        raise SchwabCandleObserverResponseError(
            "Schwab Streamer acknowledgement content had an invalid shape."
        )
    code = acknowledgement.get("code")
    if code not in (0, "0"):
        raise SchwabCandleObserverAuthorizationError(
            "Schwab Streamer rejected the requested read-only operation."
        )


class WebSocketClientConnection:
    def __init__(self, socket: object, module: object) -> None:
        self.socket = socket
        self.module = module

    def send_json(self, payload: Mapping[str, object]) -> None:
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        try:
            self.socket.send(serialized)
        except Exception:
            raise SchwabCandleObserverNetworkError(
                "Schwab Streamer send failed safely."
            ) from None

    def receive_json(self, timeout_seconds: float) -> Mapping[str, object] | None:
        try:
            self.socket.settimeout(timeout_seconds)
            raw = self.socket.recv()
        except self.module.WebSocketTimeoutException:
            return None
        except Exception:
            raise SchwabCandleObserverNetworkError(
                "Schwab Streamer receive failed safely."
            ) from None
        if raw in (None, "", b""):
            raise SchwabCandleObserverNetworkError(
                "Schwab Streamer closed before observation completed."
            )
        if isinstance(raw, bytes):
            try:
                raw = raw.decode("utf-8")
            except UnicodeDecodeError:
                raise SchwabCandleObserverResponseError(
                    "Schwab Streamer returned non-UTF-8 data."
                ) from None
        if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_STREAM_FRAME_BYTES:
            raise SchwabCandleObserverResponseError(
                "Schwab Streamer frame exceeded the allowed shape or size."
            )
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise SchwabCandleObserverResponseError(
                "Schwab Streamer frame was not valid JSON."
            ) from None
        if not isinstance(payload, Mapping):
            raise SchwabCandleObserverResponseError(
                "Schwab Streamer frame was not a JSON object."
            )
        return payload

    def close(self) -> None:
        try:
            self.socket.close()
        except Exception:
            pass


class WebSocketClientFactory:
    dependency_version: str | None = None

    def connect(self, socket_url: str) -> WebSocketClientConnection:
        _validate_streamer_url(socket_url)
        try:
            import websocket
        except ImportError:
            raise SchwabCandleObserverNetworkError(
                "The isolated candle observer requires websocket-client."
            ) from None
        version = str(getattr(websocket, "__version__", "")).strip()
        if version != EXPECTED_WEBSOCKET_CLIENT_VERSION:
            raise SchwabCandleObserverNetworkError(
                "The isolated candle observer found an unexpected websocket-client version."
            )
        self.dependency_version = version
        try:
            socket = websocket.create_connection(
                socket_url,
                timeout=ACK_TIMEOUT_SECONDS,
                enable_multithread=False,
                sslopt={
                    "cert_reqs": ssl.CERT_REQUIRED,
                    "check_hostname": True,
                },
                http_proxy_host=None,
                http_no_proxy=[EXPECTED_STREAMER_HOST],
            )
        except Exception:
            raise SchwabCandleObserverNetworkError(
                "Schwab Streamer TLS connection failed safely."
            ) from None
        return WebSocketClientConnection(socket, websocket)


class SchwabCandleMarketHoursObserver:
    def __init__(
        self,
        *,
        access_guard: object | None = None,
        http_transport: object | None = None,
        stream_factory: StreamConnectionFactory | None = None,
        utc_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.access_guard = access_guard or SchwabCandleAccessGuard()
        self.http = http_transport or SchwabCandleHttpTransport()
        self.stream_factory = stream_factory or WebSocketClientFactory()
        self.utc_clock = utc_clock or (lambda: datetime.now(timezone.utc))
        self.monotonic_clock = monotonic_clock or time.monotonic

    def observe(self, options: CandleObservationOptions) -> dict[str, object]:
        source_identity = _implementation_source_identity()
        request_started_at = _aware_now(self.utc_clock())
        observed_session = session_for_timestamp(request_started_at)
        market_date = request_started_at.astimezone(EASTERN_TZ).date()
        if options.candidate_source is not None:
            if options.candidate_source.generated_at.astimezone(EASTERN_TZ).date() != market_date:
                raise SchwabCandleObserverError(
                    "Hunter candidate report did not match the live market date."
                )
            expected_symbols = (
                "SPY",
                "IWM",
                options.candidate_source.candidate_symbol,
            )
            if options.symbols != expected_symbols:
                raise SchwabCandleObserverError(
                    "Observed symbols did not match the frozen Hunter candidate source."
                )
        if (
            not is_market_open_day(market_date)
            or observed_session == "closed"
            or (observed_session == "extended" and not options.extended_hours)
        ):
            raise SchwabCandleObserverError(
                "Live candle observation requires an allowed U.S. equity market session."
            )
        access = self.access_guard.authorize(options.expected_account_ending)
        bootstrap = parse_streamer_bootstrap(
            self.http.fetch_bootstrap(access.access_token),
            expected_account_ending=options.expected_account_ending,
        )
        stream = self.stream_factory.connect(bootstrap.socket_url)
        transport_events: list[dict[str, object]] = [
            {"kind": "CONNECTED", "timestamp": self.utc_clock().isoformat()}
        ]
        messages: list[object] = []
        receipts: list[datetime] = []
        try:
            stream.send_json(build_streamer_login(access.access_token, bootstrap))
            self._receive_ack(
                stream,
                service="ADMIN",
                command="LOGIN",
                request_id="0",
            )
            subscription = build_chart_equity_subscription(
                options.symbols,
                customer_id=bootstrap.customer_id,
                correlation_id=bootstrap.correlation_id,
                request_id="1",
            )
            stream.send_json(subscription)
            subscription_fingerprint = hashlib.sha256(
                json.dumps(
                    subscription,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest().upper()
            self._receive_ack(
                stream,
                service=SCHWAB_CHART_EQUITY_SERVICE,
                command="SUBS",
                request_id="1",
                buffered_messages=messages,
                buffered_receipts=receipts,
            )
            subscription_acknowledged_at = _aware_now(self.utc_clock())
            transport_events.append(
                {
                    "kind": "SUBSCRIPTION_ACKNOWLEDGED",
                    "timestamp": subscription_acknowledged_at.isoformat(),
                }
            )
            observation_started = self.monotonic_clock()
            stream_failure: str | None = None
            while self.monotonic_clock() - observation_started < options.duration_seconds:
                if len(messages) >= MAX_PROOF_MESSAGES:
                    raise SchwabCandleObserverResponseError(
                        "Schwab candle observation exceeded the proof message limit."
                    )
                remaining = options.duration_seconds - (
                    self.monotonic_clock() - observation_started
                )
                try:
                    payload = stream.receive_json(max(0.1, min(5.0, remaining)))
                except (
                    SchwabCandleObserverNetworkError,
                    SchwabCandleObserverResponseError,
                ) as exc:
                    stream_failure = f"{type(exc).__name__}: {exc}"
                    transport_events.append(
                        {
                            "kind": "DISCONNECTED",
                            "timestamp": _aware_now(self.utc_clock()).isoformat(),
                        }
                    )
                    break
                if payload is None:
                    continue
                if "data" in payload:
                    parse_chart_equity_messages(
                        [payload],
                        expected_symbols=options.symbols,
                    )
                    messages.append(payload)
                    receipts.append(_aware_now(self.utc_clock()))
            evaluated_at = _aware_now(self.utc_clock())
            transport_events.append(
                {
                    "kind": "OBSERVATION_STOPPED",
                    "timestamp": evaluated_at.isoformat(),
                }
            )
        finally:
            stream.close()

        response_received_at = receipts[0] if receipts else evaluated_at

        history_start = request_started_at - timedelta(minutes=10)
        history_end = evaluated_at + timedelta(minutes=1)
        histories: dict[str, object] = {}
        history_observations: list[dict[str, object]] = []
        for symbol in options.symbols:
            history_requested_at = _aware_now(self.utc_clock())
            failure: str | None = None
            try:
                histories[symbol] = self.http.fetch_price_history(
                    access.access_token,
                    symbol,
                    start_at=history_start,
                    end_at=history_end,
                    extended_hours=options.extended_hours,
                )
            except (SchwabCandleContractError, SchwabCandleObserverError) as exc:
                failure = f"{type(exc).__name__}: {exc}"
            history_received_at = _aware_now(self.utc_clock())
            history_observations.append(
                {
                    "symbol": symbol,
                    "status": "FAIL" if failure else "PASS",
                    "failure": failure,
                    "requestStartedAt": history_requested_at.isoformat(),
                    "responseReceivedAt": history_received_at.isoformat(),
                    "responseSeconds": round(
                        (history_received_at - history_requested_at).total_seconds(),
                        6,
                    ),
                    "explicitStartAt": history_start.isoformat(),
                    "explicitEndAt": history_end.isoformat(),
                    "extendedHoursRequested": options.extended_hours,
                }
            )
        if source_identity != _implementation_source_identity():
            raise SchwabCandleObserverError(
                "Candle observer source identity changed during observation."
            )
        proof = build_nonpersisting_stream_proof(
            messages,
            expected_symbols=options.symbols,
            request_started_at=request_started_at,
            response_received_at=response_received_at,
            evaluated_at=evaluated_at,
            received_at_by_payload=receipts,
            transport_events=transport_events,
            price_history_payloads=histories,
        )
        proof.update(
            {
                "observerSchemaVersion": OBSERVER_SCHEMA_VERSION,
                "observerMode": OBSERVER_MODE,
                "liveNetworkCalled": True,
                "observationOptions": options.evidence(),
                "accountInvariant": access.evidence(),
                "streamerBootstrap": bootstrap.evidence(),
                "subscription": {
                    "service": SCHWAB_CHART_EQUITY_SERVICE,
                    "command": "SUBS",
                    "requestId": "1",
                    "symbols": list(options.symbols),
                    "requestFingerprint": subscription_fingerprint,
                    "acknowledged": True,
                    "rawIdentifiersIncluded": False,
                },
                "implementationIdentity": {
                    **source_identity,
                    "expectedWebsocketClientVersion": (
                        EXPECTED_WEBSOCKET_CLIENT_VERSION
                    ),
                    "observedWebsocketClientVersion": getattr(
                        self.stream_factory,
                        "dependency_version",
                        None,
                    ),
                },
                "streamStatus": "FAIL" if stream_failure else "PASS",
                "streamFailure": stream_failure,
                "priceHistoryRequests": history_observations,
                "priceHistoryStatus": (
                    "PASS"
                    if all(row["status"] == "PASS" for row in history_observations)
                    else "PARTIAL"
                ),
                "credentialMaterialIncluded": False,
                "rawAccountMetadataIncluded": False,
                "productionDataWritten": False,
                "serviceInvoked": False,
                "engineHostInvoked": False,
                "wpfInvoked": False,
            }
        )
        if proof["priceHistoryStatus"] != "PASS":
            proof["findings"].append("PRICE_HISTORY_RECONCILIATION_INCOMPLETE")
        if proof["streamStatus"] != "PASS":
            proof["findings"].append("STREAM_DISCONNECTED_DURING_OBSERVATION")
        proof["proofFingerprint"] = _proof_fingerprint(proof)
        _require_sanitized_proof(
            proof,
            forbidden_values=(access.access_token,),
        )
        return proof

    def _receive_ack(
        self,
        stream: StreamConnection,
        *,
        service: str,
        command: str,
        request_id: str,
        buffered_messages: list[object] | None = None,
        buffered_receipts: list[datetime] | None = None,
    ) -> None:
        deadline = self.monotonic_clock() + ACK_TIMEOUT_SECONDS
        while self.monotonic_clock() < deadline:
            payload = stream.receive_json(
                max(0.1, min(2.0, deadline - self.monotonic_clock()))
            )
            if payload is None:
                continue
            has_data = "data" in payload
            if has_data:
                if buffered_messages is None or buffered_receipts is None:
                    raise SchwabCandleObserverResponseError(
                        "Schwab Streamer sent candle data before authorization completed."
                    )
                buffered_messages.append(payload)
                buffered_receipts.append(_aware_now(self.utc_clock()))
            if "response" in payload:
                require_streamer_acknowledgement(
                    payload,
                    service=service,
                    command=command,
                    request_id=request_id,
                )
                return
            if _is_stream_notification(payload) or has_data:
                continue
            raise SchwabCandleObserverResponseError(
                "Schwab Streamer returned an unexpected frame before acknowledgement."
            )
        raise SchwabCandleObserverNetworkError(
            "Schwab Streamer acknowledgement timed out."
        )


def build_observation_plan(options: CandleObservationOptions) -> dict[str, object]:
    plan: dict[str, object] = {
        "schemaVersion": OBSERVER_SCHEMA_VERSION,
        "mode": f"{OBSERVER_MODE}_PLAN",
        "execute": False,
        "networkCalled": False,
        "productionDataWritten": False,
        "symbols": list(options.symbols),
        "durationSeconds": options.duration_seconds,
        "extendedHoursAllowed": options.extended_hours,
        "accountInvariant": {
            "expectedAccountEnding": options.expected_account_ending,
            "requiredAccountCount": 1,
            "requiredAccountType": EXPECTED_ACCOUNT_TYPE,
            "bindingRevalidationRequired": True,
            "positionsRequested": False,
            "ordersRequested": False,
        },
        "httpEndpoints": [
            SCHWAB_USER_PREFERENCE_URL,
            SCHWAB_PRICE_HISTORY_URL,
        ],
        "streamService": SCHWAB_CHART_EQUITY_SERVICE,
        "outputBoundary": "EXPLICIT_JSON_OUTSIDE_REPOSITORY_NO_OVERWRITE",
        "serviceInvoked": False,
        "engineHostInvoked": False,
        "wpfInvoked": False,
        "orderTransmission": "UNAVAILABLE",
    }
    if options.candidate_source is not None:
        plan["candidateSource"] = options.candidate_source.evidence()
    return plan


def write_proof_once(proof: Mapping[str, object], output_path: Path) -> Path:
    destination = require_safe_output_path(output_path)
    serialized = json.dumps(proof, indent=2, sort_keys=True) + "\n"
    if len(serialized.encode("utf-8")) > MAX_INPUT_BYTES:
        raise SchwabCandleObserverError(
            "Candle observation proof exceeded the output size limit."
        )
    temporary = destination.with_name(
        f".{destination.name}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
    except FileExistsError:
        raise SchwabCandleObserverError(
            "Candle observation proof already exists; overwrite is forbidden."
        ) from None
    except OSError as exc:
        raise SchwabCandleObserverError(
            "Candle observation proof could not be written safely."
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def require_safe_output_path(output_path: Path) -> Path:
    if output_path.suffix.lower() != ".json":
        raise SchwabCandleObserverError(
            "Candle observation output must use a .json filename."
        )
    destination = output_path.expanduser().resolve()
    repository_root = Path(__file__).resolve().parents[1]
    try:
        destination.relative_to(repository_root)
    except ValueError:
        pass
    else:
        raise SchwabCandleObserverError(
            "Candle observation output must remain outside the repository."
        )
    if not destination.parent.is_dir():
        raise SchwabCandleObserverError(
            "Candle observation output directory does not exist."
        )
    if destination.exists():
        raise SchwabCandleObserverError(
            "Candle observation proof already exists; overwrite is forbidden."
        )
    return destination


def _proof_fingerprint(proof: Mapping[str, object]) -> str:
    payload = json.dumps(proof, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest().upper()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _implementation_source_identity() -> dict[str, str]:
    return {
        "observerModuleSha256": _file_sha256(Path(__file__)),
        "candleContractModuleSha256": _file_sha256(
            Path(candle_contract_module.__file__)
        ),
    }


def _require_sanitized_proof(
    proof: Mapping[str, object],
    *,
    forbidden_values: Sequence[str],
) -> None:
    serialized = json.dumps(proof, separators=(",", ":"), sort_keys=True)
    lowered = serialized.lower()
    forbidden_terms = (
        "authorization",
        "access_token",
        "refresh_token",
        "client_secret",
        "accountnumber",
        "account_hash",
        "hashvalue",
    )
    if any(term in lowered for term in forbidden_terms) or any(
        value and value in serialized for value in forbidden_values
    ):
        raise SchwabCandleObserverError(
            "Candle observation proof failed credential and account-identity redaction."
        )


def _aware_now(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabCandleObserverError(
            "Candle observer clock must include a UTC offset."
        )
    return value


def _exception_chain_contains(
    error: BaseException,
    expected: type[BaseException],
) -> bool:
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        if isinstance(current, expected):
            return True
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def _is_stream_notification(payload: Mapping[str, object]) -> bool:
    return "notify" in payload and "response" not in payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Plan or run one nonpersisting Schwab CHART_EQUITY market-hours proof."
        )
    )
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--expected-account-ending", required=True)
    parser.add_argument(
        "--duration-seconds",
        type=int,
        default=DEFAULT_OBSERVATION_SECONDS,
    )
    parser.add_argument("--allow-extended-hours", action="store_true")
    parser.add_argument("--candidate-source-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    try:
        candidate_source = (
            load_candidate_source(args.candidate_source_report)
            if args.candidate_source_report is not None
            else None
        )
        symbols = normalize_symbols(args.symbols)
        if args.execute and candidate_source is None:
            raise SchwabCandleObserverError(
                "Live observation requires a frozen Hunter candidate report."
            )
        if candidate_source is not None and symbols != (
            "SPY",
            "IWM",
            candidate_source.candidate_symbol,
        ):
            raise SchwabCandleObserverError(
                "Requested symbols did not match the frozen Hunter candidate report."
            )
        options = CandleObservationOptions.create(
            symbols,
            expected_account_ending=args.expected_account_ending,
            duration_seconds=args.duration_seconds,
            extended_hours=args.allow_extended_hours,
            candidate_source=candidate_source,
        )
        if not args.execute:
            result = build_observation_plan(options)
        else:
            if args.output is None:
                raise SchwabCandleObserverError(
                    "Live observation requires an explicit output path."
                )
            proof = SchwabCandleMarketHoursObserver().observe(options)
            path = write_proof_once(proof, args.output)
            result = {
                "schemaVersion": OBSERVER_SCHEMA_VERSION,
                "mode": OBSERVER_MODE,
                "status": proof["proofStatus"],
                "shapeStatus": proof["shapeStatus"],
                "proofFingerprint": proof["proofFingerprint"],
                "outputPath": str(path),
                "credentialMaterialIncluded": False,
                "rawAccountMetadataIncluded": False,
                "productionDataWritten": False,
                "positionsRequested": False,
                "ordersRequested": False,
                "orderTransmission": "UNAVAILABLE",
            }
    except (
        SchwabCandleContractError,
        SchwabCandleObserverError,
        ValueError,
    ) as exc:
        result = {
            "schemaVersion": OBSERVER_SCHEMA_VERSION,
            "mode": OBSERVER_MODE,
            "status": "FAIL",
            "failure": f"{type(exc).__name__}: {exc}",
            "reauthorizationRequired": isinstance(
                exc,
                SchwabCandleObserverReauthorizationRequired,
            ),
            "credentialMaterialIncluded": False,
            "rawAccountMetadataIncluded": False,
            "productionDataWritten": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 2 if result.get("status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
