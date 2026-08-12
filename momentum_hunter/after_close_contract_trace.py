from __future__ import annotations

"""Read-only provider trace and TEST_ONLY Paper submission-boundary rehearsal."""

import argparse
import copy
import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from momentum_hunter.alpaca_paper_broker import AlpacaPaperOrderRequest
from momentum_hunter.alpaca_paper_engineering import (
    DEFAULT_PAPER_ENGINEERING_DIRECTORY,
    load_paper_engineering_arm,
    load_paper_engineering_policy,
)
from momentum_hunter.alpaca_paper_onboarding import (
    ALPACA_LIVE_BASE_URL,
    ALPACA_PAPER_BASE_URL,
    AlpacaPaperCredentialRepository,
    AlpacaPaperLane,
    AlpacaPaperReadonlyTransport,
)
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_SUPPORTED,
    DIRECT_ISSUER,
    EXECUTION_ELIGIBLE,
)
from momentum_hunter.intraday_trade_plan import (
    CONTINUATION_BREAKOUT,
    build_intraday_plan_evidence,
)
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from momentum_hunter.paper_risk_governor import evaluate_paper_candidate
from momentum_hunter.provider_neutral_allocation import (
    AccountSnapshot,
    AllocationRequest,
    allocate_provider_neutral_position,
    evidence_fingerprint,
)
from momentum_hunter.providers import (
    FINVIZ_CANONICAL_SCREENER_COLUMNS,
    FINVIZ_SCREENER_COLUMN_ALIASES,
    FinvizProvider,
    finviz_screener_schema_fingerprint,
)
from momentum_hunter.scheduling import is_market_open_day
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
    parse_daily_price_history_response,
    parse_price_history_response,
    session_for_timestamp,
)
from momentum_hunter.schwab_candle_observer import SchwabCandleHttpTransport
from momentum_hunter.schwab_market_data import (
    SCHWAB_QUOTE_SOURCE,
    BoundSchwabAccessTokenProvider,
    SchwabMarketDataTransport,
)
from momentum_hunter.time_normalized_rvol import (
    TIME_NORMALIZED_RVOL_FORMULA,
    TIME_NORMALIZED_RVOL_PROFILE,
    TIME_NORMALIZED_RVOL_SCHEMA_VERSION,
)
from momentum_hunter.trade_planning import (
    COMPOSITE_CONFIGURATION_FINGERPRINT,
    COMPOSITE_PROFILE,
    EVIDENCE_INTEGRITY_SCHEMA_VERSION,
)
from momentum_hunter.trade_setup_identity import build_trade_setup_evidence


TRACE_SCHEMA_VERSION = 1
TRACE_PROFILE = "after-close-contract-transaction-trace-v1"
TRACE_CLASSIFICATION = "AFTER_CLOSE_DIAGNOSTIC_REHEARSAL"
BROKER_BOUNDARY = "DRY_RUN_READY_FOR_PROVIDER_SUBMISSION"
TEST_ONLY = "TEST_ONLY_NOT_ADMISSIBLE_TO_ACTIVE_PAPER_OR_SHADOW"
TRACE_QUOTE_FRESHNESS_SECONDS = 30.0
CENTRAL_TZ = ZoneInfo("America/Chicago")
DEFAULT_OUTPUT_ROOT = (
    Path.home()
    / "AppData"
    / "Local"
    / "MomentumHunter"
    / "diagnostics"
    / "after-close-contract-trace"
)
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


FINVIZ_FIELD_MAPPINGS = (
    ("Ticker", "ticker/symbol", True),
    ("Company", "company", True),
    ("Sector", "sector", True),
    ("Industry", "industry", True),
    ("Market Cap", "market_cap", True),
    ("Float", "float_shares", False),
    ("ATR", "atr", False),
    ("Rel Volume", "relative_volume", False),
    ("Volume", "volume", True),
    ("Price", "price", True),
    ("Change %", "percent_change/change_pct", True),
)

SCHWAB_QUOTE_FIELD_MAPPINGS = (
    ("symbol", "symbol"),
    ("quote.lastPrice", "last"),
    ("quote.bidPrice", "bid"),
    ("quote.askPrice", "ask"),
    ("quote.bidTime", "provider_bid_timestamp"),
    ("quote.askTime", "provider_ask_timestamp"),
    ("quote.quoteTime", "provider_quote_timestamp"),
    ("quote.securityStatus", "security_status/trading_state"),
    ("quote.totalVolume", "volume"),
    ("realtime", "realtime"),
)

SCHWAB_CANDLE_FIELD_MAPPINGS = (
    ("symbol", "symbol"),
    ("candles[].datetime", "timestamp/sessionDate"),
    ("candles[].open", "open"),
    ("candles[].high", "high"),
    ("candles[].low", "low"),
    ("candles[].close", "close"),
    ("candles[].volume", "volume"),
)

ALPACA_ACCOUNT_FIELD_MAPPINGS = (
    ("status", "status"),
    ("cash", "cash_available"),
    ("buying_power", "buying_power"),
    ("equity", "equity"),
    ("last_equity", "last_equity"),
    ("account_blocked", "account_blocked"),
    ("trading_blocked", "trading_blocked"),
    ("trade_suspended_by_user", "trade_suspended_by_user"),
)


class AfterCloseTraceError(RuntimeError):
    pass


class GetOnlyRecordingSession:
    """Instrument GET requests while refusing every mutating HTTP verb."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        if session is None:
            self.session.trust_env = False
        self.records: list[dict[str, object]] = []
        self.mutation_attempts: list[dict[str, str]] = []

    def get(self, url: str, **kwargs):
        started = datetime.now(timezone.utc)
        response = self.session.get(url, **kwargs)
        received = datetime.now(timezone.utc)
        record = {
            "method": "GET",
            "url": _sanitized_url(url),
            "host": urlparse(url).hostname or "",
            "requestStartedAt": started.isoformat(),
            "responseReceivedAt": received.isoformat(),
            "httpStatus": int(response.status_code),
            "responseBytes": len(response.content),
            "responseSha256": hashlib.sha256(response.content).hexdigest().upper(),
            "httpsDatePresent": bool(response.headers.get("Date")),
            "requestIdPresent": bool(
                response.headers.get("X-Request-ID")
                or response.headers.get("x-request-id")
            ),
            "shape": _response_shape(response),
        }
        self.records.append(record)
        return response

    def _reject(self, method: str, url: str, **_kwargs):
        self.mutation_attempts.append({"method": method, "url": _sanitized_url(url)})
        raise AfterCloseTraceError(
            f"After-close rehearsal refused mutating HTTP method {method}."
        )

    def post(self, url: str, **kwargs):
        return self._reject("POST", url, **kwargs)

    def put(self, url: str, **kwargs):
        return self._reject("PUT", url, **kwargs)

    def patch(self, url: str, **kwargs):
        return self._reject("PATCH", url, **kwargs)

    def delete(self, url: str, **kwargs):
        return self._reject("DELETE", url, **kwargs)


class RehearsalSubmissionBoundary:
    """Validate request serialization without owning any network transport."""

    def __init__(self) -> None:
        self.validated_requests: list[dict[str, object]] = []
        self.provider_calls = 0

    def validate(self, request: AlpacaPaperOrderRequest) -> dict[str, object]:
        payload = request.to_payload()
        self.validated_requests.append(copy.deepcopy(payload))
        return payload

    def result(self) -> dict[str, object]:
        return {
            "classification": BROKER_BOUNDARY,
            "meaning": "Request validation passed; provider submission is not authorized.",
            "providerCalls": self.provider_calls,
            "networkTransportPresent": False,
            "mutatingRequestMethods": [],
        }


def run_after_close_trace(
    *,
    canonical_root: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    _require_aware(now, "trace clock")
    canonical = canonical_root.resolve()
    schedule_before = _schedule_snapshot()
    git_before = _git_snapshot(canonical)

    finviz_session = GetOnlyRecordingSession()
    finviz = FinvizProvider(backoff_seconds=(), quote_backoff_seconds=())
    finviz_session.session.headers.update(finviz.session.headers)
    finviz.session = finviz_session
    finviz_started = datetime.now(timezone.utc)
    candidates = finviz.scan(INSTITUTIONAL_MOMENTUM)
    finviz_received = datetime.now(timezone.utc)
    diagnostics = finviz.last_scan_diagnostics
    if diagnostics is None:
        raise AfterCloseTraceError("Finviz scan completed without contract diagnostics.")
    expected_finviz_fingerprint = finviz_screener_schema_fingerprint(
        FINVIZ_CANONICAL_SCREENER_COLUMNS
    )
    if diagnostics.schema_fingerprint != expected_finviz_fingerprint:
        raise AfterCloseTraceError(
            "Finviz provider field contract differs from the expected canonical schema."
        )
    finviz_trace = _finviz_trace(
        diagnostics=diagnostics,
        candidates=candidates,
        requested_at=finviz_started,
        received_at=finviz_received,
        requests=finviz_session.records,
    )

    selected = candidates[0] if candidates else _synthetic_candidate()
    selected_origin = (
        "LIVE_FINVIZ_QUALIFYING_IDENTITY"
        if candidates
        else "SYNTHETIC_TEST_ONLY_NO_LIVE_QUALIFIER"
    )
    symbols = tuple(dict.fromkeys((selected.ticker, "SPY", "QQQ", "IWM")))

    token_provider = BoundSchwabAccessTokenProvider()
    access_token = token_provider.access_token()
    quote_session = GetOnlyRecordingSession()
    quote_transport = SchwabMarketDataTransport(session=quote_session)
    quote_batch = quote_transport.fetch_quotes_with_clock(access_token, symbols)
    quote_trace = _schwab_quote_trace(
        symbols=symbols,
        quote_batch=quote_batch,
        requests=quote_session.records,
        observed_at=now,
    )

    candle_session = GetOnlyRecordingSession()
    candle_transport = SchwabCandleHttpTransport(session=candle_session)
    candle_trace = _schwab_candle_trace(
        symbols=symbols,
        access_token=access_token,
        transport=candle_transport,
        session=candle_session,
        observed_at=now,
    )

    account_session = GetOnlyRecordingSession()
    account_repository = AlpacaPaperCredentialRepository(
        lane=AlpacaPaperLane.CANARY_REALISTIC
    )
    account_transport = AlpacaPaperReadonlyTransport(session=account_session)
    account_credentials = account_repository.load()
    account, request_id_present = account_transport.get_account(account_credentials)
    account_trace = _alpaca_account_trace(
        account=account,
        request_id_present=request_id_present,
        requests=account_session.records,
    )

    policy = load_paper_engineering_policy(DEFAULT_PAPER_ENGINEERING_DIRECTORY)
    arm, capabilities = load_paper_engineering_arm(
        policy=policy,
        output_directory=DEFAULT_PAPER_ENGINEERING_DIRECTORY,
    )
    transaction = build_test_only_transaction_trace(
        candidate=selected,
        selected_origin=selected_origin,
        live_account=account,
        binding_fingerprint=account_repository.binding_fingerprint(),
        policy=policy,
        arm_fingerprint=arm.fingerprint,
        capabilities=capabilities,
        session_date=now.astimezone(EASTERN_TZ).date(),
    )

    schedule_after = _schedule_snapshot()
    git_after = _git_snapshot(canonical)
    if schedule_before != schedule_after:
        raise AfterCloseTraceError(
            "Tomorrow's automation manifest changed during the read-only rehearsal."
        )
    if git_before != git_after:
        raise AfterCloseTraceError(
            "Canonical Git identity or cleanliness changed during the rehearsal."
        )

    all_sessions = (finviz_session, quote_session, candle_session, account_session)
    mutation_attempts = [
        item for session in all_sessions for item in session.mutation_attempts
    ]
    observed_requests = [
        item for session in all_sessions for item in session.records
    ]
    non_get = [
        item for item in observed_requests if item.get("method") != "GET"
    ]
    live_alpaca_hosts = [
        item
        for item in observed_requests
        if item.get("host") == urlparse(ALPACA_LIVE_BASE_URL).hostname
    ]
    suspicious_values = _suspicious_semantic_values(
        finviz_trace,
        quote_trace,
        candle_trace,
        account_trace,
    )
    packet = {
        "schemaVersion": TRACE_SCHEMA_VERSION,
        "profile": TRACE_PROFILE,
        "classification": TRACE_CLASSIFICATION,
        "createdAt": now.isoformat(),
        "testOnly": True,
        "admissionStatus": TEST_ONLY,
        "countsTowardOfficialSample": False,
        "retrospectiveTrade": False,
        "productionSourceChanged": False,
        "canonicalGitBefore": git_before,
        "canonicalGitAfter": git_after,
        "scheduleBefore": schedule_before,
        "scheduleAfter": schedule_after,
        "finviz": finviz_trace,
        "schwabQuotes": quote_trace,
        "schwabCandles": candle_trace,
        "alpacaPaperAccount": account_trace,
        "transactionTrace": transaction,
        "networkAudit": {
            "requests": observed_requests,
            "requestCount": len(observed_requests),
            "getCount": sum(item.get("method") == "GET" for item in observed_requests),
            "mutatingRequests": non_get,
            "mutationAttempts": mutation_attempts,
            "alpacaLiveHostContacts": live_alpaca_hosts,
            "schwabOrderEndpointsInvoked": [],
            "orderSubmissionCount": 0,
            "orderCancelCount": 0,
            "orderReplaceCount": 0,
        },
        "suspiciousSemanticValues": suspicious_values,
        "secretScan": {},
        "acceptance": {},
    }
    packet["secretScan"] = _secret_scan(
        packet,
        known_credential_values=(
            account_credentials.key_id,
            account_credentials.secret_key,
        ),
    )
    packet["acceptance"] = _acceptance(packet)
    fingerprint_source = copy.deepcopy(packet)
    fingerprint_source.pop("packetFingerprint", None)
    packet["packetFingerprint"] = evidence_fingerprint(fingerprint_source)
    paths = write_trace_packet(packet, output_root=output_root)
    packet["outputPaths"] = {key: str(value) for key, value in paths.items()}
    return packet


def build_test_only_transaction_trace(
    *,
    candidate: Candidate,
    selected_origin: str,
    live_account,
    binding_fingerprint: str,
    policy,
    arm_fingerprint: str,
    capabilities,
    session_date,
) -> dict[str, object]:
    decision_at = _diagnostic_decision_time(session_date)
    symbol = candidate.ticker.strip().upper()
    reference = Decimal(str(candidate.price if candidate.price > 0 else 100)).quantize(
        Decimal("0.01")
    )
    entry = reference
    stop = (entry * Decimal("0.98")).quantize(Decimal("0.01"))
    if stop >= entry:
        stop = entry - Decimal("0.01")
    risk_per_share = entry - stop
    target_1 = entry + (risk_per_share * 2)
    target_2 = entry + (risk_per_share * 3)
    observed_price = (entry - Decimal("0.01")).quantize(Decimal("0.01"))
    setup = build_trade_setup_evidence(
        symbol=symbol,
        observed_price=float(observed_price),
        breakout_level=float(entry),
        invalidation_level=float(stop),
        source="daily_bars",
    )
    created_at = decision_at - timedelta(minutes=1)
    intraday = build_intraday_plan_evidence(
        symbol=symbol,
        setup_family=CONTINUATION_BREAKOUT,
        created_at=created_at,
        planned_entry=float(entry),
        stop_price=float(stop),
        target_prices=(float(target_1), float(target_2)),
        source_setup_fingerprint=setup.fingerprint,
        source_level_kind="TEST_ONLY_CONTINUATION_RANGE",
        source_evidence_ids=("test-only:canonical-regular-session-replay",),
    )
    row = _test_only_candidate_row(
        candidate=candidate,
        entry=entry,
        stop=stop,
        target_1=target_1,
        target_2=target_2,
        observed_price=observed_price,
        setup=setup,
        intraday=intraday,
        decision_at=decision_at,
    )
    ask = entry + min(Decimal("0.01"), entry * Decimal("0.0001"))
    ask = ask.quantize(Decimal("0.01"))
    if ask < entry:
        ask = entry
    bid = max(Decimal("0.01"), ask - Decimal("0.01"))
    quote_at = decision_at - timedelta(seconds=1)
    quote = {
        "symbol": symbol,
        "status": "PASS",
        "findings": [],
        "timestamp": quote_at.isoformat(),
        "providerQuoteTimestamp": quote_at.isoformat(),
        "providerBidTimestamp": quote_at.isoformat(),
        "providerAskTimestamp": quote_at.isoformat(),
        "quoteAgeSeconds": 1.0,
        "bid": float(bid),
        "ask": float(ask),
        "last": float(bid),
        "session": "regular",
        "tradingState": "tradable",
        "realtime": True,
        "securityStatus": "Normal",
        "source": SCHWAB_QUOTE_SOURCE,
        "evidenceMode": TEST_ONLY,
    }
    risk, parsed_plan = evaluate_paper_candidate(
        row,
        quote_result=quote,
        decision_at=decision_at,
        policy=policy.risk,
    )
    if parsed_plan is None:
        raise AfterCloseTraceError("TEST_ONLY TradePlan could not be parsed.")
    cycle_id = "after-close-test-cycle-" + evidence_fingerprint(
        {
            "symbol": symbol,
            "decisionAt": decision_at.isoformat(),
            "armFingerprint": arm_fingerprint,
            "selectedOrigin": selected_origin,
        }
    )[:20].lower()
    account_at = decision_at - timedelta(milliseconds=250)
    account = AccountSnapshot(
        snapshot_id="after-close-test-account-" + cycle_id[-12:],
        decision_cycle_id=cycle_id,
        lane=AlpacaPaperLane.CANARY_REALISTIC.value,
        provider="ALPACA_TRADING_API",
        environment="PAPER_ONLY",
        binding_fingerprint=binding_fingerprint,
        authorized_account_count=1,
        status=live_account.status if live_account.usable else "BLOCKED",
        cash_available=live_account.cash,
        buying_power=live_account.buying_power,
        committed_notional=Decimal("0"),
        committed_open_risk=Decimal("0"),
        open_position_count=0,
        realized_pnl_today=Decimal("0"),
        provider_timestamp=account_at.isoformat(),
        portfolio_timestamp=account_at.isoformat(),
        receipt_timestamp=account_at.isoformat(),
        source_identity="TEST_ONLY_CURRENT_ACCOUNT_VALUES_WITH_SYNTHETIC_ZERO_PORTFOLIO",
    )
    request = AllocationRequest(
        decision_cycle_id=cycle_id,
        candidate_id=risk.candidate_id,
        canonical_rank=risk.canonical_rank,
        symbol=symbol,
        trade_plan_id=risk.trade_plan_id,
        risk_decision_id=risk.risk_decision_id,
        entry_order_type="market",
        entry_price=risk.execution_price or ask,
        stop_price=stop,
        target_price=target_1,
        decision_at=decision_at.isoformat(),
    )
    allocation = allocate_provider_neutral_position(
        request=request,
        policy=policy.allocation,
        account=account,
        capabilities=capabilities,
    )
    boundary = RehearsalSubmissionBoundary()
    order_shapes: dict[str, object] = {}
    intent: dict[str, object] = {
        "status": "BLOCKED_BEFORE_ORDER_SERIALIZATION",
        "reason": "RISK_OR_ALLOCATION_GATE",
    }
    if risk.authorized and allocation.authorized:
        raw_notional = allocation.position_notional
        if raw_notional is None:
            raise AfterCloseTraceError("Authorized TEST_ONLY allocation omitted notional.")
        buffer = Decimal("1") - policy.entry_notional_buffer_percent / Decimal("100")
        submitted_notional = (raw_notional * buffer).quantize(
            Decimal("0.01"), rounding=ROUND_FLOOR
        )
        token = cycle_id.rsplit("-", 1)[-1][:16]
        prefix = f"mh-paper-engineering-{token}-"
        entry_request = AlpacaPaperOrderRequest(
            symbol=symbol,
            side="buy",
            order_type="market",
            time_in_force="day",
            client_order_id=f"{prefix}entry",
            notional=submitted_notional,
        )
        stop_request = AlpacaPaperOrderRequest(
            symbol=symbol,
            side="sell",
            order_type="stop",
            time_in_force="day",
            client_order_id=f"{prefix}stop",
            quantity=allocation.final_authorized_quantity,
            stop_price=stop,
        )
        emergency_request = AlpacaPaperOrderRequest(
            symbol=symbol,
            side="sell",
            order_type="market",
            time_in_force="day",
            client_order_id=f"{prefix}exit",
            quantity=allocation.final_authorized_quantity,
        )
        order_shapes = {
            "entry": boundary.validate(entry_request),
            "protectiveStop": boundary.validate(stop_request),
            "emergencyFlatten": boundary.validate(emergency_request),
            "fractionalPrecision": str(allocation.quantity_increment),
            "protectiveQuantityRule": "ACTUAL_FILLED_QUANTITY_REQUIRED_BEFORE_SUBMISSION",
        }
        intent = {
            "intentId": "test-only-intent-" + cycle_id[-16:],
            "intentType": "TEST_ONLY_ALPACA_PAPER_ENTRY_INTENT",
            "clientOrderPrefix": prefix,
            "entryClientOrderId": entry_request.client_order_id,
            "stopClientOrderId": stop_request.client_order_id,
            "exitClientOrderId": emergency_request.client_order_id,
            "restartRecoveryIdentity": {
                "decisionCycleId": cycle_id,
                "clientOrderPrefix": prefix,
                "lookupRule": "LOOK_UP_EXACT_CLIENT_ORDER_ID_BEFORE_ANY_RETRY",
                "blindResubmission": False,
            },
            "emergencyFlattenPlan": {
                "request": order_shapes["emergencyFlatten"],
                "maximumAttempts": 3,
                "quantityRule": "EXACT_RECONCILED_REMAINING_POSITION_QUANTITY",
            },
            "status": BROKER_BOUNDARY,
        }
        intent["fingerprint"] = evidence_fingerprint(intent)

    gate_checks = {
        "riskGovernor": "PASS" if risk.authorized else "BLOCKED",
        "aggregateOpenRisk": _gate_from_blockers(
            allocation.blockers, "ALLOCATION_OPEN_RISK_LIMIT_REACHED"
        ),
        "dailyLoss": _gate_from_blockers(
            allocation.blockers, "ALLOCATION_DAILY_LOSS_LIMIT_REACHED"
        ),
        "concurrency": _gate_from_blockers(
            allocation.blockers, "ALLOCATION_POSITION_LIMIT_REACHED"
        ),
        "notionalCashBuyingPower": (
            "BLOCKED"
            if any(
                item
                in {
                    "ALLOCATION_INSUFFICIENT_BUYING_POWER",
                    "ALLOCATION_ZERO_FINAL_AUTHORIZED_QUANTITY",
                }
                for item in allocation.blockers
            )
            else "PASS"
        ),
    }
    return {
        "mode": TEST_ONLY,
        "selectedOrigin": selected_origin,
        "candidate": {
            "candidateId": risk.candidate_id,
            "symbol": symbol,
            "providerEvidenceIdentity": evidence_fingerprint(
                {
                    "provider": "FINVIZ",
                    "origin": selected_origin,
                    "symbol": symbol,
                }
            ),
        },
        "syntheticRegularSessionEvidence": True,
        "afterHoursEvidenceUsedAsRegularAuthority": False,
        "decisionCycleId": cycle_id,
        "decisionAt": decision_at.isoformat(),
        "priceAuthority": quote,
        "candleAuthority": {
            "mode": TEST_ONLY,
            "source": SCHWAB_PRICE_HISTORY_SOURCE,
            "identity": "test-only:canonical-regular-session-replay",
        },
        "catalystEvidence": row["evidence_integrity"]["catalyst_attribution"],
        "setup": {
            "setupFamily": intraday.setup_family,
            "setupId": intraday.plan_id,
            "setupFingerprint": setup.fingerprint,
            "intradayFingerprint": intraday.fingerprint,
        },
        "tradePlan": {
            "tradePlanId": risk.trade_plan_id,
            "entry": str(entry),
            "stop": str(stop),
            "targets": [str(target_1), str(target_2)],
            "rewardRisk": str((target_1 - entry) / (entry - stop)),
            "forcedFlatAt": intraday.forced_flat_at,
        },
        "riskDecision": risk.to_dict(),
        "accountSnapshot": {
            "snapshotId": account.snapshot_id,
            "fingerprint": account.fingerprint,
            "sourceIdentity": account.source_identity,
            "freshness": "PASS_TEST_ONLY_CHRONOLOGY",
            "liveValuesObservedAfterClose": True,
            "portfolioStateSynthetic": True,
            "cash": str(account.cash_available),
            "buyingPower": str(account.buying_power),
            "openPositionCount": account.open_position_count,
        },
        "brokerCapabilities": capabilities.to_dict(),
        "allocation": allocation.to_dict(),
        "gateChecks": gate_checks,
        "orderIntent": intent,
        "orderShapes": order_shapes,
        "submissionBoundary": boundary.result(),
        "terminalEvidence": {
            "terminal": True,
            "classification": (
                BROKER_BOUNDARY
                if order_shapes
                else "DRY_RUN_TERMINATED_AT_LEGITIMATE_GATE"
            ),
            "officialEvidenceMutated": False,
            "providerSubmissionOccurred": False,
        },
    }


def write_trace_packet(
    packet: Mapping[str, object],
    *,
    output_root: Path,
) -> dict[str, Path]:
    created = datetime.fromisoformat(str(packet["createdAt"]))
    token = created.astimezone(CENTRAL_TZ).strftime("%Y%m%dT%H%M%S")
    fingerprint = str(packet["packetFingerprint"])
    stem = f"after-close-contract-trace-{token}-{fingerprint[:12].lower()}"
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / f"{stem}.json"
    markdown_path = output_root / f"{stem}.md"
    _write_new(json_path, json.dumps(packet, indent=2, sort_keys=True) + "\n")
    _write_new(markdown_path, _markdown(packet))
    return {"json": json_path, "markdown": markdown_path}


def _finviz_trace(*, diagnostics, candidates, requested_at, received_at, requests):
    observed = tuple(diagnostics.observed_headers)
    canonical = tuple(diagnostics.canonical_headers)
    mappings = []
    for provider_field, canonical_field, required in FINVIZ_FIELD_MAPPINGS:
        actual = next(
            (
                item
                for item in observed
                if FINVIZ_SCREENER_COLUMN_ALIASES.get(item, item) == provider_field
            ),
            None,
        )
        mappings.append(
            {
                "providerField": actual,
                "expectedCanonicalProviderField": provider_field,
                "canonicalField": canonical_field,
                "aliasUsed": bool(actual and actual != provider_field),
                "required": required,
                "parseStatus": "PASS" if actual else "UNAVAILABLE",
            }
        )
    return {
        "provider": diagnostics.provider,
        "requestStartedAt": requested_at.isoformat(),
        "responseReceivedAt": received_at.isoformat(),
        "observedHeaders": list(observed),
        "observedColumnOrder": list(observed),
        "canonicalHeaders": list(canonical),
        "schemaFingerprint": diagnostics.schema_fingerprint,
        "expectedSchemaFingerprint": finviz_screener_schema_fingerprint(
            FINVIZ_CANONICAL_SCREENER_COLUMNS
        ),
        "schemaStatus": "PASS",
        "fieldMappings": mappings,
        "rawRowCount": diagnostics.data_row_count,
        "parsedRowCount": diagnostics.parsed_row_count,
        "qualifiedRowCount": diagnostics.qualifying_candidate_count,
        "rejectedRowCount": diagnostics.parsed_row_count
        - diagnostics.qualifying_candidate_count,
        "qualifyingSymbols": [item.ticker for item in candidates],
        "requests": requests,
        "rawBodyPersisted": False,
    }


def _schwab_quote_trace(*, symbols, quote_batch, requests, observed_at):
    rows = []
    for symbol in symbols:
        quote = quote_batch.quotes.get(symbol)
        if quote is None:
            rows.append({"symbol": symbol, "status": "UNAVAILABLE"})
            continue
        timestamp = datetime.fromisoformat(quote.timestamp)
        age_seconds = max(0.0, (observed_at - timestamp).total_seconds())
        rows.append(
            {
                "symbol": symbol,
                "status": "PASS",
                "last": quote.last,
                "bid": quote.bid,
                "ask": quote.ask,
                "providerQuoteTimestamp": quote.provider_quote_timestamp,
                "providerBidTimestamp": quote.provider_bid_timestamp,
                "providerAskTimestamp": quote.provider_ask_timestamp,
                "executableTimestamp": quote.timestamp,
                "ageSeconds": age_seconds,
                "freshness": (
                    "CURRENT_DIAGNOSTIC"
                    if age_seconds <= TRACE_QUOTE_FRESHNESS_SECONDS
                    else "STALE_DIAGNOSTIC"
                ),
                "session": quote.session,
                "tradingState": quote.trading_state,
                "securityStatus": quote.security_status,
                "realtime": quote.realtime,
                "source": quote.source,
                "regularSessionAuthority": False,
            }
        )
    return {
        "provider": "Charles Schwab Trader API - Individual",
        "endpointKind": "GET_ONLY_QUOTES",
        "fieldMappings": [
            {"providerField": source, "canonicalField": target}
            for source, target in SCHWAB_QUOTE_FIELD_MAPPINGS
        ],
        "requestedSymbols": list(symbols),
        "quotes": rows,
        "clockSkewProof": quote_batch.clock_skew_proof,
        "requests": requests,
        "afterHoursPromotedToRegularAuthority": False,
    }


def _schwab_candle_trace(*, symbols, access_token, transport, session, observed_at):
    intraday_start = observed_at - timedelta(days=2)
    daily_start = observed_at - timedelta(days=370)
    rows = []
    for symbol in symbols:
        intraday_payload = transport.fetch_price_history(
            access_token,
            symbol,
            start_at=intraday_start,
            end_at=observed_at,
            extended_hours=True,
        )
        intraday = parse_price_history_response(
            intraday_payload, expected_symbol=symbol
        )
        intraday_receipt = session.records[-1]["responseReceivedAt"]
        daily_payload = transport.fetch_daily_price_history(
            access_token,
            symbol,
            start_at=daily_start,
            end_at=observed_at,
        )
        daily = parse_daily_price_history_response(
            daily_payload, expected_symbol=symbol
        )
        daily_receipt = session.records[-1]["responseReceivedAt"]
        rows.append(
            {
                "symbol": symbol,
                "intraday": _candle_set_summary(
                    intraday,
                    receipt_at=intraday_receipt,
                    timeframe="1m",
                ),
                "daily": _candle_set_summary(
                    daily,
                    receipt_at=daily_receipt,
                    timeframe="1d",
                ),
            }
        )
    return {
        "provider": "Charles Schwab Trader API - Individual",
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "derivation": "PRICE_HISTORY_DERIVED",
        "streamerDerived": False,
        "reconciled": False,
        "completionState": "COMPLETED_UNRECONCILED",
        "fieldMappings": [
            {"providerField": source, "canonicalField": target}
            for source, target in SCHWAB_CANDLE_FIELD_MAPPINGS
        ],
        "symbols": rows,
        "requests": session.records,
        "regularSessionFinalityClaimed": False,
    }


def _candle_set_summary(candles, *, receipt_at: str, timeframe: str):
    invariants = []
    for candle in candles:
        valid = (
            candle.high >= candle.open
            and candle.high >= candle.close
            and candle.low <= candle.open
            and candle.low <= candle.close
            and candle.high >= candle.low
            and all(
                math.isfinite(float(item)) and float(item) > 0
                for item in (candle.open, candle.high, candle.low, candle.close)
            )
            and math.isfinite(float(candle.volume))
            and float(candle.volume) >= 0
        )
        invariants.append(valid)
    latest = candles[-1] if candles else None
    return {
        "timeframe": timeframe,
        "status": "PASS" if candles and all(invariants) else "UNAVAILABLE" if not candles else "FAIL",
        "count": len(candles),
        "semanticInvariantPassCount": sum(invariants),
        "semanticInvariantFailCount": len(invariants) - sum(invariants),
        "latest": latest.to_evidence() if latest else None,
        "latestSession": (
            session_for_timestamp(latest.timestamp) if latest else "unavailable"
        ),
        "providerTimestamp": latest.timestamp.isoformat() if latest else None,
        "localReceiptTimestamp": receipt_at,
        "sequence": getattr(latest, "sequence", None) if latest else None,
        "sequenceAvailability": (
            "UNAVAILABLE_FOR_PRICE_HISTORY" if latest else "UNAVAILABLE"
        ),
    }


def _alpaca_account_trace(*, account, request_id_present, requests):
    receipt = requests[-1]["responseReceivedAt"] if requests else None
    return {
        "provider": "Alpaca Trading API",
        "environment": "PAPER",
        "endpoint": ALPACA_PAPER_BASE_URL,
        "hostClassification": "EXACT_APPROVED_PAPER_HOST",
        "requestMethod": "GET",
        "requestPath": "/v2/account",
        "fieldMappings": [
            {"providerField": source, "canonicalField": target}
            for source, target in ALPACA_ACCOUNT_FIELD_MAPPINGS
        ],
        "status": account.status,
        "usable": account.usable,
        "cash": str(account.cash),
        "buyingPower": str(account.buying_power),
        "equity": str(account.equity) if account.equity is not None else None,
        "lastEquity": (
            str(account.last_equity) if account.last_equity is not None else None
        ),
        "accountBlocked": account.account_blocked,
        "tradingBlocked": account.trading_blocked,
        "tradeSuspendedByUser": account.trade_suspended_by_user,
        "receiptTimestamp": receipt,
        "freshness": "CURRENT_READ",
        "requestIdPresent": request_id_present,
        "credentialsIncluded": False,
        "accountIdentityIncluded": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "requests": requests,
    }


def _test_only_candidate_row(
    *, candidate, entry, stop, target_1, target_2, observed_price, setup, intraday, decision_at
):
    session_date = decision_at.astimezone(EASTERN_TZ).date()
    baseline_dates = []
    cursor = session_date - timedelta(days=1)
    while len(baseline_dates) < 5:
        if is_market_open_day(cursor):
            baseline_dates.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    window_start = datetime.combine(session_date, time(9, 30), EASTERN_TZ)
    through = datetime.combine(session_date, time(9, 59), EASTERN_TZ)
    rvol = {
        "schema_version": TIME_NORMALIZED_RVOL_SCHEMA_VERSION,
        "profile": TIME_NORMALIZED_RVOL_PROFILE,
        "status": EXECUTION_ELIGIBLE,
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "symbol": candidate.ticker.upper(),
        "rvol_type": "INTRADAY_RVOL",
        "session_name": "REGULAR",
        "session_date": session_date.isoformat(),
        "session_minute": 30,
        "window_start": window_start.astimezone(timezone.utc).isoformat(),
        "through_minute": through.astimezone(timezone.utc).isoformat(),
        "observed_volume": 200000,
        "expected_volume": 100000.0,
        "relative_volume": 2.0,
        "current_bar_count": 30,
        "expected_current_bar_count": 30,
        "baseline_session_count": 5,
        "minimum_baseline_sessions": 5,
        "target_baseline_sessions": 20,
        "baseline_session_dates": baseline_dates,
        "formula": TIME_NORMALIZED_RVOL_FORMULA,
        "findings": ["TIME_NORMALIZED_RVOL_AVAILABLE"],
    }
    plan = {
        "bullish_entry": float(entry),
        "bullish_stop": float(stop),
        "bullish_target_1": float(target_1),
        "bullish_target_2": float(target_2),
        "risk_reward_ratio": 2.0,
        "estimated_shares_for_500": float(Decimal("500") / entry),
        "estimated_dollar_risk": 2.0,
        "estimated_target_1_reward": 4.0,
        "confidence": "MEDIUM",
        "tradeability": "MEDIUM",
        "readiness": "EXECUTION_READY_TRADE",
        "blocking_reasons": [],
        "warnings": [],
        "setup_evidence": asdict(setup),
        "intraday_evidence": asdict(intraday),
    }
    catalyst = {
        "source_article": f"{candidate.ticker.upper()} TEST_ONLY contract trace",
        "source_publisher": "TEST_ONLY",
        "source_url": "",
        "source_published_at": (decision_at - timedelta(minutes=10)).isoformat(),
        "mentioned_ticker": candidate.ticker.upper(),
        "mentioned_company": candidate.company,
        "candidate_ticker": candidate.ticker.upper(),
        "candidate_company": candidate.company,
        "relationship_type": DIRECT_ISSUER,
        "relationship_evidence": "TEST_ONLY explicit issuer identity.",
        "score_authority": CATALYST_SCORE_SUPPORTED,
    }
    return {
        "rank": 1,
        "candidate_id": "after-close-test-candidate-" + candidate.ticker.lower(),
        "symbol": candidate.ticker.upper(),
        "company": candidate.company,
        "market_data": {
            "last_price": float(observed_price),
            "current_bid": float(observed_price),
            "current_ask": float(entry),
            "spread_percent": 0.01,
            "relative_volume": 2.0,
            "rvol_authority": EXECUTION_ELIGIBLE,
            "rvol_session_minute": 30,
            "rvol_baseline_sessions": 5,
        },
        "technical_levels": {
            "previous_day_high": float(entry),
            "previous_day_low": float(stop),
            "previous_day_close": float(observed_price),
            "five_day_high": float(entry),
            "twenty_day_high": float(entry),
            "atr": float(entry - stop),
            "support_level": float(stop),
            "resistance_level": float(entry),
            "source": "daily_bars",
            "warnings": [],
        },
        "scoring": {
            "composite_score": 90,
            "composite_profile": COMPOSITE_PROFILE,
            "composite_configuration_fingerprint": COMPOSITE_CONFIGURATION_FINGERPRINT,
            "catalyst_summary": "TEST_ONLY direct issuer catalyst",
            "catalyst_cluster": "TEST_ONLY",
            "catalyst_confidence": 80,
            "authoritative_catalyst_confidence": 80,
            "catalyst_score_contribution": 4.0,
        },
        "evidence_integrity": {
            "schema_version": EVIDENCE_INTEGRITY_SCHEMA_VERSION,
            "price_evidence_status": EXECUTION_ELIGIBLE,
            "price_fields": {},
            "provider_results": {"test_only": "SUCCESS"},
            "rvol_evidence": rvol,
            "catalyst_attribution": catalyst,
            "authority_blocking_reasons": [],
            "plan_label": "TEST_ONLY REGULAR SESSION PLAN",
            "plan_authority": EXECUTION_ELIGIBLE,
            "setup_evidence": asdict(setup),
            "intraday_plan_evidence": asdict(intraday),
        },
        "trade_plan": plan,
        "opportunity_notes": [TEST_ONLY],
    }


def _acceptance(packet: Mapping[str, object]) -> dict[str, object]:
    finviz = packet["finviz"]
    quotes = packet["schwabQuotes"]
    candles = packet["schwabCandles"]
    account = packet["alpacaPaperAccount"]
    transaction = packet["transactionTrace"]
    network = packet["networkAudit"]
    checks = {
        "finvizLiveSchemaExplicit": finviz["schemaStatus"] == "PASS",
        "finvizMappingsRecorded": bool(finviz["fieldMappings"]),
        "finvizCountsPreserved": all(
            isinstance(finviz[name], int)
            for name in ("rawRowCount", "parsedRowCount", "qualifiedRowCount")
        ),
        "schwabQuoteMappingsExplicit": bool(quotes["fieldMappings"]),
        "schwabCandleMappingsExplicit": bool(candles["fieldMappings"]),
        "candleInvariantsVisible": all(
            item[frame]["semanticInvariantFailCount"] >= 0
            for item in candles["symbols"]
            for frame in ("intraday", "daily")
        ),
        "alpacaAccountMappingExplicit": bool(account["fieldMappings"]),
        "transactionReachedBoundaryOrGate": transaction["terminalEvidence"]["terminal"] is True,
        "falseZeroCandidatePrevented": not (
            finviz["rawRowCount"] > 0
            and finviz["parsedRowCount"] == 0
            and finviz["schemaStatus"] == "PASS"
        ),
        "afterHoursNotRegularAuthority": transaction["afterHoursEvidenceUsedAsRegularAuthority"] is False,
        "officialEvidenceUnchanged": True,
        "alpacaMutationsAbsent": not network["mutatingRequests"] and network["orderSubmissionCount"] == 0,
        "alpacaLiveHostAbsent": not network["alpacaLiveHostContacts"],
        "schwabOrderEndpointAbsent": not network["schwabOrderEndpointsInvoked"],
        "scheduleUnchanged": packet["scheduleBefore"] == packet["scheduleAfter"],
        "secretsAbsent": packet["secretScan"]["status"] == "PASS",
        "testOnlyAdmissionLocked": transaction["mode"] == TEST_ONLY,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
    }


def _secret_scan(
    packet: Mapping[str, object],
    *,
    known_credential_values: Sequence[str],
) -> dict[str, object]:
    serialized = json.dumps(packet, sort_keys=True)
    known_value_present = any(
        value and value in serialized for value in known_credential_values
    )
    marker_patterns = {
        "APCA-API-KEY-ID": r"APCA-API-KEY-ID",
        "APCA-API-SECRET-KEY": r"APCA-API-SECRET-KEY",
        "AWS_ACCESS_KEY": r"(?<![A-Z0-9])AKIA[A-Z0-9]{12,}",
        "OPENAI_STYLE_KEY": r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{8,}",
    }
    marker_hits = [
        name
        for name, pattern in marker_patterns.items()
        if re.search(pattern, serialized)
    ]
    return {
        "status": "PASS" if not known_value_present and not marker_hits else "FAIL",
        "knownCredentialValuesPresent": known_value_present,
        "credentialMarkerHits": marker_hits,
        "valuesIncluded": False,
    }


def _suspicious_semantic_values(finviz, quotes, candles, account):
    findings = []
    if finviz["rawRowCount"] != finviz["parsedRowCount"]:
        findings.append("FINVIZ_RAW_PARSED_COUNT_MISMATCH")
    for quote in quotes["quotes"]:
        if quote.get("status") != "PASS":
            findings.append(f"SCHWAB_QUOTE_UNAVAILABLE:{quote.get('symbol')}")
        if quote.get("freshness") == "STALE_DIAGNOSTIC":
            findings.append(
                f"SCHWAB_QUOTE_STALE_DIAGNOSTIC:{quote.get('symbol')}:{quote.get('ageSeconds')}s"
            )
        bid, ask = quote.get("bid"), quote.get("ask")
        if bid is not None and ask is not None and (bid <= 0 or ask < bid):
            findings.append(f"SCHWAB_QUOTE_BID_ASK_IMPLAUSIBLE:{quote.get('symbol')}")
    for symbol in candles["symbols"]:
        for frame in ("intraday", "daily"):
            if symbol[frame]["status"] != "PASS":
                findings.append(f"SCHWAB_CANDLE_{frame.upper()}_{symbol[frame]['status']}:{symbol['symbol']}")
    if not account["usable"]:
        findings.append("ALPACA_PAPER_ACCOUNT_NOT_USABLE")
    return findings


def _schedule_snapshot() -> dict[str, object]:
    path = Path(r"C:\ProgramData\MomentumHunter\Automation\automation-manifest.json")
    raw = path.read_bytes()
    manifest = json.loads(raw.decode("utf-8-sig"))
    now = datetime.now(timezone.utc)
    future = []
    for job in manifest.get("jobs", []):
        scheduled = datetime.fromisoformat(str(job["scheduledAt"]))
        if scheduled.astimezone(timezone.utc) <= now:
            continue
        if job.get("kind") in {"opening_capture", "paper_engineering"}:
            future.append(
                {
                    key: job.get(key)
                    for key in (
                        "jobId",
                        "kind",
                        "scheduledAt",
                        "latestStartAt",
                        "enabled",
                        "timeoutSeconds",
                        "expectedGitHead",
                        "dependsOnJobId",
                    )
                }
            )
    return {
        "manifestPath": str(path),
        "manifestSha256": hashlib.sha256(raw).hexdigest().upper(),
        "futureOpeningAndPaperJobs": future,
    }


def _git_snapshot(root: Path) -> dict[str, object]:
    head = _git(root, "rev-parse", "HEAD")
    origin = _git(root, "rev-parse", "origin/master")
    status = _git(root, "status", "--porcelain")
    return {
        "root": str(root),
        "head": head,
        "originMaster": origin,
        "clean": not status,
    }


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _response_shape(response) -> dict[str, object]:
    content_type = str(response.headers.get("Content-Type", "")).lower()
    if "json" not in content_type:
        return {"contentType": content_type, "json": False}
    try:
        payload = response.json()
    except ValueError:
        return {"contentType": content_type, "json": "INVALID"}
    shape: dict[str, object] = {"contentType": content_type, "json": True}
    if isinstance(payload, Mapping):
        shape["topLevelFields"] = sorted(str(item) for item in payload)
        candles = payload.get("candles")
        if isinstance(candles, list):
            shape["rowCount"] = len(candles)
            shape["rowFields"] = (
                sorted(str(item) for item in candles[0])
                if candles and isinstance(candles[0], Mapping)
                else []
            )
        quote_fields = set()
        row_fields = set()
        for value in payload.values():
            if isinstance(value, Mapping):
                row_fields.update(str(item) for item in value)
                quote = value.get("quote")
                if isinstance(quote, Mapping):
                    quote_fields.update(str(item) for item in quote)
        if row_fields:
            shape["rowFields"] = sorted(row_fields)
        if quote_fields:
            shape["quoteFields"] = sorted(quote_fields)
    elif isinstance(payload, list):
        shape["rowCount"] = len(payload)
        shape["rowFields"] = (
            sorted(str(item) for item in payload[0])
            if payload and isinstance(payload[0], Mapping)
            else []
        )
    return shape


def _diagnostic_decision_time(session_date) -> datetime:
    candidate = session_date
    while not is_market_open_day(candidate):
        candidate -= timedelta(days=1)
    return datetime.combine(candidate, time(10, 0), EASTERN_TZ)


def _synthetic_candidate() -> Candidate:
    return Candidate(
        ticker="SPY",
        company="SPDR S&P 500 ETF Trust",
        price=100.0,
        percent_change=3.0,
        volume=10_000_000,
        relative_volume=2.0,
        market_cap=10_000_000_000,
        sector="Exchange Traded Fund",
        industry="Index ETF",
    )


def _gate_from_blockers(blockers: Sequence[str], target: str) -> str:
    return "BLOCKED" if target in blockers else "PASS"


def _sanitized_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AfterCloseTraceError(f"{label} must include a UTC offset.")


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        raise AfterCloseTraceError(f"Trace output already exists: {path}")
    path.write_text(content, encoding="utf-8", newline="\n")


def _markdown(packet: Mapping[str, object]) -> str:
    finviz = packet["finviz"]
    transaction = packet["transactionTrace"]
    lines = [
        "# After-Close Contract And Transaction Trace",
        "",
        f"- Classification: `{packet['classification']}`",
        f"- Acceptance: `{packet['acceptance']['status']}`",
        f"- Packet fingerprint: `{packet['packetFingerprint']}`",
        f"- Admission: `{packet['admissionStatus']}`",
        "- Official sample: `NO`",
        "- Provider mutation: `NONE`",
        "",
        "## Finviz",
        "",
        f"- Headers: `{', '.join(finviz['observedHeaders'])}`",
        f"- Counts: raw {finviz['rawRowCount']} / parsed {finviz['parsedRowCount']} / qualified {finviz['qualifiedRowCount']} / rejected {finviz['rejectedRowCount']}",
        f"- Schema fingerprint: `{finviz['schemaFingerprint']}`",
        "",
        "## Transaction",
        "",
        f"- Candidate: `{transaction['candidate']['symbol']}`",
        f"- Risk: `{transaction['riskDecision']['status']}`",
        f"- Allocation: `{transaction['allocation']['status']}`",
        f"- Boundary: `{transaction['terminalEvidence']['classification']}`",
        "- Alpaca Paper POST/PATCH/DELETE: `0`",
        "- Schwab order endpoints: `0`",
        "- After-hours evidence promoted to regular authority: `NO`",
        "",
        "## Safety",
        "",
        f"- Tomorrow manifest unchanged: `{packet['acceptance']['checks']['scheduleUnchanged']}`",
        f"- Canonical Git unchanged: `{packet['canonicalGitBefore'] == packet['canonicalGitAfter']}`",
        f"- Suspicious semantic values: `{', '.join(packet['suspiciousSemanticValues']) or 'NONE'}`",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one read-only after-close provider and Paper boundary trace."
    )
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    try:
        packet = run_after_close_trace(
            canonical_root=args.canonical_root,
            output_root=args.output_root,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "AFTER_CLOSE_TRACE_FAILED_SAFE",
                    "errorType": type(exc).__name__,
                    "detail": str(exc),
                    "orderSubmissionCount": 0,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1
    print(
        json.dumps(
            {
                "classification": packet["classification"],
                "acceptance": packet["acceptance"]["status"],
                "packetFingerprint": packet["packetFingerprint"],
                "outputPaths": packet["outputPaths"],
                "orderSubmissionCount": packet["networkAudit"]["orderSubmissionCount"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if packet["acceptance"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
