from __future__ import annotations

"""Offline replay of preserved Schwab regular-session evidence."""

import argparse
import copy
import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.alpaca_paper_broker import AlpacaPaperOrderRequest
from momentum_hunter.broker_capabilities import (
    CAPABILITY_FRACTIONAL_MARKET,
    CAPABILITY_FRACTIONAL_PRECISION,
    CAPABILITY_FRACTIONAL_QUANTITY,
    BrokerCapability,
    BrokerCapabilityRegistry,
    CapabilityState,
)
from momentum_hunter.canonical_candle_evidence import CanonicalMinuteBar
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_SUPPORTED,
    DIRECT_ISSUER,
    EXECUTION_ELIGIBLE,
)
from momentum_hunter.intraday_trade_plan import (
    OPENING_BREAKOUT,
    build_intraday_plan_evidence,
)
from momentum_hunter.paper_risk_governor import PaperRiskPolicy, evaluate_paper_candidate
from momentum_hunter.provider_neutral_allocation import (
    AccountSnapshot,
    AllocationRequest,
    ProviderNeutralAllocationPolicy,
    allocate_provider_neutral_position,
    evidence_fingerprint,
)
from momentum_hunter.schwab_candle_contract import (
    EASTERN_TZ,
    SCHWAB_PRICE_HISTORY_SOURCE,
)
from momentum_hunter.schwab_market_data import SCHWAB_QUOTE_SOURCE
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


REPLAY_SCHEMA_VERSION = 1
REPLAY_PROFILE = "real-preserved-regular-session-replay-v1"
REPLAY_MODE = "OFFLINE_TEST_ONLY_NO_HISTORICAL_TRADE_AUTHORITY"
REAL_REPLAY_IDENTITY = "TEST_ONLY_REAL_PRESERVED_SCHWAB_REGULAR_SESSION_REPLAY"
CONSTRUCTED_FIXTURE_IDENTITY = "TEST_ONLY_CONSTRUCTED_REGULAR_SESSION_FIXTURE"
OLD_AMBIGUOUS_IDENTITY = "test-only:canonical-regular-session-replay"
BROKER_BOUNDARY = "DRY_RUN_READY_FOR_PROVIDER_SUBMISSION"
DEFAULT_OUTPUT_ROOT = (
    Path.home()
    / "AppData"
    / "Local"
    / "MomentumHunter"
    / "diagnostics"
    / "real-regular-session-replay-trace"
)


class RegularSessionReplayError(RuntimeError):
    pass


class OfflineSubmissionBoundary:
    """Serialize order intent without owning a network transport."""

    def __init__(self) -> None:
        self.validated_requests: list[dict[str, object]] = []

    def validate(self, request: AlpacaPaperOrderRequest) -> dict[str, object]:
        payload = request.to_payload()
        self.validated_requests.append(copy.deepcopy(payload))
        return payload

    def result(self) -> dict[str, object]:
        reached = bool(self.validated_requests)
        return {
            "classification": (
                BROKER_BOUNDARY if reached else "NOT_REACHED_NO_SERIALIZED_ORDER"
            ),
            "meaning": (
                "Serialization passed; provider submission is prohibited."
                if reached
                else "No request reached serialization; provider submission remains prohibited."
            ),
            "providerCalls": 0,
            "networkTransportPresent": False,
            "mutatingRequestMethods": [],
        }


def run_regular_session_replay(
    *,
    quote_proof_path: Path,
    minute_store_path: Path,
    baseline_minute_store_path: Path,
    daily_store_path: Path,
    symbol: str,
    market_date: str,
    prior_session_date: str,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    """Replay one preserved event without provider, broker, or production writes."""

    paths = (
        quote_proof_path,
        minute_store_path,
        baseline_minute_store_path,
        daily_store_path,
    )
    before = {str(path): _sha256_file(path) for path in paths}
    quote_proof = _load_json(quote_proof_path, "quote proof")
    minute_store = _load_json(minute_store_path, "minute store")
    baseline_store = _load_json(baseline_minute_store_path, "baseline minute store")
    daily_store = _load_json(daily_store_path, "daily store")
    normalized_symbol = symbol.strip().upper()

    quote = _select_quote(quote_proof, normalized_symbol)
    original_market_time = _aware_datetime(
        quote_proof.get("checkedAt"), "quote proof checkedAt"
    )
    decision_at = original_market_time
    replay_at = (clock or (lambda: datetime.now(EASTERN_TZ)))()
    if replay_at.tzinfo is None or replay_at.utcoffset() is None:
        raise RegularSessionReplayError("Replay evaluation time must include a UTC offset.")

    opening_bars, opening_ids = _opening_bars(
        minute_store,
        symbol=normalized_symbol,
        session_date=market_date,
    )
    baseline_bars, baseline_ids = _opening_bars(
        baseline_store,
        symbol=normalized_symbol,
        session_date=prior_session_date,
    )
    daily, daily_identity = _daily_bar(
        daily_store,
        symbol=normalized_symbol,
        session_date=prior_session_date,
    )

    observed_price = Decimal(str(opening_bars[-1].close))
    raw_entry = Decimal(str(daily["high"]))
    raw_stop = Decimal(str(daily["low"]))
    if not raw_stop < raw_entry:
        raise RegularSessionReplayError("Completed Daily high/low order is invalid.")

    setup = build_trade_setup_evidence(
        symbol=normalized_symbol,
        observed_price=float(observed_price),
        breakout_level=float(raw_entry),
        invalidation_level=float(raw_stop),
        source="daily_bars",
    )
    if setup.planned_entry is None or setup.invalidation_level is None:
        raise RegularSessionReplayError("Daily setup normalization failed.")
    entry = Decimal(str(setup.planned_entry))
    stop = Decimal(str(setup.invalidation_level))
    risk_per_share = entry - stop
    target_1 = entry + (risk_per_share * Decimal("2"))
    target_2 = entry + (risk_per_share * Decimal("3"))
    source_ids = (daily_identity, *opening_ids)
    intraday = build_intraday_plan_evidence(
        symbol=normalized_symbol,
        setup_family=OPENING_BREAKOUT,
        created_at=decision_at,
        planned_entry=float(entry),
        stop_price=float(stop),
        target_prices=(float(target_1), float(target_2)),
        source_setup_fingerprint=setup.fingerprint,
        source_level_kind="PREVIOUS_COMPLETED_DAILY_HIGH_LOW",
        source_evidence_ids=source_ids,
        observed_price=float(observed_price),
    )
    rvol = _rvol_evidence(
        symbol=normalized_symbol,
        market_date=market_date,
        prior_session_date=prior_session_date,
        current=opening_bars,
        baseline=baseline_bars,
    )
    row = _candidate_row(
        symbol=normalized_symbol,
        observed_price=observed_price,
        entry=entry,
        stop=stop,
        target_1=target_1,
        target_2=target_2,
        setup=setup,
        intraday=intraday,
        rvol=rvol,
    )
    risk_policy = PaperRiskPolicy(
        policy_id="offline-replay-paper-risk-v1",
        maximum_spread_percent=Decimal("3"),
        maximum_entry_extension_percent=Decimal("0.25"),
        minimum_reward_risk=Decimal("1.5"),
    )
    risk, parsed_plan = evaluate_paper_candidate(
        row,
        quote_result=quote,
        decision_at=decision_at,
        policy=risk_policy,
    )
    if parsed_plan is None:
        raise RegularSessionReplayError("DATA-004 TradePlan could not be parsed.")

    cycle_id = "offline-real-replay-" + evidence_fingerprint(
        {
            "quoteProofSha256": before[str(quote_proof_path)],
            "minuteStoreSha256": before[str(minute_store_path)],
            "dailyStoreSha256": before[str(daily_store_path)],
            "symbol": normalized_symbol,
            "decisionAt": decision_at.isoformat(),
        }
    )[:20].lower()
    downstream = _downstream_trace(
        cycle_id=cycle_id,
        risk=risk,
        entry=entry,
        stop=stop,
        target=target_1,
        decision_at=decision_at,
    )

    after = {str(path): _sha256_file(path) for path in paths}
    source_unchanged = before == after
    if not source_unchanged:
        raise RegularSessionReplayError("A preserved source file changed during replay.")
    real_chain_complete = bool(
        risk.authorized
        and downstream["allocationStatus"] == "AUTHORIZED"
        and downstream["submissionBoundary"]["classification"] == BROKER_BOUNDARY
    )
    classification = (
        "REAL_PRESERVED_EVIDENCE_CHAIN_REACHED_BROKER_BOUNDARY"
        if real_chain_complete
        else "REAL_PRESERVED_EVIDENCE_REPLAY_TERMINATED_AT_LEGITIMATE_GATE"
    )
    packet: dict[str, object] = {
        "schemaVersion": REPLAY_SCHEMA_VERSION,
        "profile": REPLAY_PROFILE,
        "mode": REPLAY_MODE,
        "classification": classification,
        "realPreservedMarketEvidenceConsumed": True,
        "entireDecisionChainReachedBrokerBoundary": real_chain_complete,
        "retrospectiveTradeCreated": False,
        "originalMarketTime": {
            "label": "ORIGINAL_MARKET_TIME",
            "decisionEvaluationTime": decision_at.isoformat(),
            "providerQuoteTimestamp": quote["providerQuoteTimestamp"],
            "localQuoteReceiptTimestamp": quote["timestamp"],
            "marketDate": market_date,
        },
        "replayEvaluationTime": {
            "label": "REPLAY_EVALUATION_TIME",
            "timestamp": replay_at.isoformat(),
            "controlsDecisionClock": False,
        },
        "labelAdjudication": {
            "existingIdentity": OLD_AMBIGUOUS_IDENTITY,
            "existingIdentityMeaning": CONSTRUCTED_FIXTURE_IDENTITY,
            "existingArtifactChanged": False,
            "recommendedProspectiveIdentity": CONSTRUCTED_FIXTURE_IDENTITY,
            "thisReplayIdentity": REAL_REPLAY_IDENTITY,
        },
        "sourceFiles": [
            {"role": role, "path": str(path), "sha256": before[str(path)]}
            for role, path in zip(
                ("QUOTE_PROOF", "MARKET_MINUTE_STORE", "BASELINE_MINUTE_STORE", "DAILY_STORE"),
                paths,
            )
        ],
        "sourceMutationCheck": {
            "status": "PASS",
            "allSourceHashesUnchanged": source_unchanged,
        },
        "marketEvidence": {
            "symbol": normalized_symbol,
            "quote": quote,
            "quoteEvidenceFingerprint": evidence_fingerprint(quote),
            "dailyCandle": daily,
            "dailyEvidenceIdentity": daily_identity,
            "openingMinuteBars": [asdict(bar) for bar in opening_bars],
            "openingMinuteEvidenceIds": list(opening_ids),
            "baselineMinuteEvidenceIds": list(baseline_ids),
            "rvolEvidence": rvol,
            "historicalAvailabilityCaveat": (
                "Candle stores were backfilled after ORIGINAL_MARKET_TIME; this replay proves "
                "contract consumption, not contemporaneous historical availability."
            ),
        },
        "decisionChain": {
            "canonicalPriceCandleAuthority": "PASS",
            "data004TradePlan": {
                "status": "PASS",
                "tradePlanId": risk.trade_plan_id,
                "setupId": setup.fingerprint,
                "intradayPlanId": intraday.plan_id,
                "intradayPlanFingerprint": intraday.fingerprint,
                "entry": str(entry),
                "stop": str(stop),
                "targets": [str(target_1), str(target_2)],
                "sourceEvidenceIds": list(source_ids),
            },
            "riskGovernor": risk.to_dict(),
            "data005bAllocation": downstream["allocation"],
            "orderIntent": downstream["orderIntent"],
            "protectiveOrderPlan": downstream["protectiveOrderPlan"],
            "submissionBoundary": downstream["submissionBoundary"],
        },
        "nonMarketScaffolding": {
            "candidateIdentity": "TEST_ONLY_SPY_REPLAY_CANDIDATE",
            "catalyst": "TEST_ONLY_DIRECT_ISSUER_SCAFFOLD_REQUIRED_BY_CURRENT_AUTHORITY_CONTRACT",
            "account": "TEST_ONLY_100_DOLLAR_ZERO_POSITION_SNAPSHOT_IF_RISK_AUTHORIZES",
            "brokerCapabilities": "TEST_ONLY_PROVEN_FRACTIONAL_CONTRACT_IF_RISK_AUTHORIZES",
            "affectsOfficialEvidence": False,
        },
        "safety": {
            "networkCalls": 0,
            "providerCalls": 0,
            "alpacaOrdersSubmitted": 0,
            "paperSampleMutated": False,
            "shadowMutated": False,
            "productionOpeningEvidenceMutated": False,
            "productionRuntimeChanged": False,
        },
    }
    fingerprint_source = copy.deepcopy(packet)
    packet["packetFingerprint"] = evidence_fingerprint(fingerprint_source)
    paths_written = write_replay_packet(packet, output_root=output_root)
    packet["outputPaths"] = {key: str(value) for key, value in paths_written.items()}
    return packet


def _downstream_trace(
    *,
    cycle_id: str,
    risk,
    entry: Decimal,
    stop: Decimal,
    target: Decimal,
    decision_at: datetime,
) -> dict[str, object]:
    boundary = OfflineSubmissionBoundary()
    if not risk.authorized:
        return {
            "allocationStatus": "NOT_REACHED",
            "allocation": {
                "status": "NOT_REACHED",
                "reason": "RISK_GOVERNOR_BLOCKED",
            },
            "orderIntent": {"status": "NOT_CREATED", "reason": "RISK_GOVERNOR_BLOCKED"},
            "protectiveOrderPlan": {
                "status": "NOT_CREATED",
                "reason": "NO_ENTRY_INTENT_OR_FILL",
            },
            "submissionBoundary": boundary.result(),
        }

    policy = ProviderNeutralAllocationPolicy(
        policy_id="offline-replay-allocation-v1",
        fixed_unit_risk_dollars=Decimal("2"),
        max_position_notional_dollars=Decimal("95"),
        minimum_cash_reserve_dollars=Decimal("5"),
        max_total_open_risk_dollars=Decimal("2"),
        daily_loss_limit_dollars=Decimal("4"),
        max_open_positions=1,
        max_snapshot_age_seconds=30,
    )
    capabilities = BrokerCapabilityRegistry.build(
        provider="ALPACA_TRADING_API",
        environment="PAPER_ONLY",
        capabilities=(
            BrokerCapability(
                CAPABILITY_FRACTIONAL_QUANTITY,
                CapabilityState.PROVEN,
                "true",
                ("TEST_ONLY offline replay capability fixture",),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_PRECISION,
                CapabilityState.PROVEN,
                "0.00000001",
                ("TEST_ONLY offline replay capability fixture",),
            ),
            BrokerCapability(
                CAPABILITY_FRACTIONAL_MARKET,
                CapabilityState.PROVEN,
                "day",
                ("TEST_ONLY offline replay capability fixture",),
            ),
        ),
    )
    account_at = decision_at - timedelta(milliseconds=250)
    account = AccountSnapshot(
        snapshot_id=f"offline-replay-account-{cycle_id[-12:]}",
        decision_cycle_id=cycle_id,
        lane="CANARY_REALISTIC",
        provider="ALPACA_TRADING_API",
        environment="PAPER_ONLY",
        binding_fingerprint="0" * 64,
        authorized_account_count=1,
        status="ACTIVE",
        cash_available=Decimal("100"),
        buying_power=Decimal("100"),
        committed_notional=Decimal("0"),
        committed_open_risk=Decimal("0"),
        open_position_count=0,
        realized_pnl_today=Decimal("0"),
        provider_timestamp=account_at.isoformat(),
        portfolio_timestamp=account_at.isoformat(),
        receipt_timestamp=account_at.isoformat(),
        source_identity="TEST_ONLY_OFFLINE_ACCOUNT_SNAPSHOT",
    )
    request = AllocationRequest(
        decision_cycle_id=cycle_id,
        candidate_id=risk.candidate_id,
        canonical_rank=risk.canonical_rank,
        symbol=risk.symbol,
        trade_plan_id=risk.trade_plan_id,
        risk_decision_id=risk.risk_decision_id,
        entry_order_type="market",
        entry_price=risk.execution_price or entry,
        stop_price=stop,
        target_price=target,
        decision_at=decision_at.isoformat(),
    )
    allocation = allocate_provider_neutral_position(
        request=request,
        policy=policy,
        account=account,
        capabilities=capabilities,
    )
    if not allocation.authorized:
        return {
            "allocationStatus": "BLOCKED",
            "allocation": allocation.to_dict(),
            "orderIntent": {"status": "NOT_CREATED", "reason": "ALLOCATION_BLOCKED"},
            "protectiveOrderPlan": {
                "status": "NOT_CREATED",
                "reason": "NO_ENTRY_INTENT_OR_FILL",
            },
            "submissionBoundary": boundary.result(),
        }

    raw_notional = allocation.position_notional
    if raw_notional is None:
        raise RegularSessionReplayError("Authorized allocation omitted notional.")
    submitted_notional = (raw_notional * Decimal("0.99")).quantize(
        Decimal("0.01"), rounding=ROUND_FLOOR
    )
    token = cycle_id.rsplit("-", 1)[-1][:16]
    client_order_id = f"mh-offline-replay-{token}-entry"
    entry_request = AlpacaPaperOrderRequest(
        symbol=risk.symbol,
        side="buy",
        order_type="market",
        time_in_force="day",
        client_order_id=client_order_id,
        notional=submitted_notional,
    )
    entry_shape = boundary.validate(entry_request)
    return {
        "allocationStatus": "AUTHORIZED",
        "allocation": allocation.to_dict(),
        "orderIntent": {
            "status": BROKER_BOUNDARY,
            "request": entry_shape,
            "maximumAuthorizedQuantity": str(allocation.final_authorized_quantity),
            "submittedNotional": str(submitted_notional),
            "providerSubmissionOccurred": False,
        },
        "protectiveOrderPlan": {
            "status": "AWAITING_ACTUAL_FILL",
            "stopPrice": str(stop),
            "quantity": None,
            "maximumAuthorizedQuantity": str(allocation.final_authorized_quantity),
            "quantityRule": "EXACT_ACTUAL_PROVIDER_FILLED_QUANTITY_AFTER_RECONCILIATION",
            "submissionPermittedBeforeFillReconciliation": False,
            "partialFillRule": "RESIZE_TO_EXACT_CURRENT_POSITION_QUANTITY",
            "emergencyFlattenRule": "EXACT_RECONCILED_REMAINING_POSITION_QUANTITY",
        },
        "submissionBoundary": boundary.result(),
    }


def _candidate_row(
    *, symbol, observed_price, entry, stop, target_1, target_2, setup, intraday, rvol
) -> dict[str, object]:
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
        "source_article": "TEST_ONLY replay contract scaffold",
        "source_publisher": "TEST_ONLY",
        "source_url": "",
        "source_published_at": "",
        "mentioned_ticker": symbol,
        "mentioned_company": "SPDR S&P 500 ETF Trust",
        "candidate_ticker": symbol,
        "candidate_company": "SPDR S&P 500 ETF Trust",
        "relationship_type": DIRECT_ISSUER,
        "relationship_evidence": "TEST_ONLY identity scaffold; not market evidence.",
        "score_authority": CATALYST_SCORE_SUPPORTED,
    }
    relative = round(float(rvol["relative_volume"]), 2)
    return {
        "rank": 1,
        "candidate_id": f"offline-replay-{symbol.lower()}",
        "symbol": symbol,
        "company": "SPDR S&P 500 ETF Trust",
        "market_data": {
            "last_price": float(observed_price),
            "current_bid": float(observed_price),
            "current_ask": float(entry),
            "spread_percent": 0.01,
            "relative_volume": relative,
            "rvol_authority": EXECUTION_ELIGIBLE,
            "rvol_session_minute": 5,
            "rvol_baseline_sessions": 1,
        },
        "technical_levels": {
            "previous_day_high": float(entry),
            "previous_day_low": float(stop),
            "previous_day_close": None,
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
            "catalyst_summary": "TEST_ONLY contract scaffold",
            "catalyst_cluster": "TEST_ONLY",
            "catalyst_confidence": 80,
            "authoritative_catalyst_confidence": 80,
            "catalyst_score_contribution": 4.0,
        },
        "evidence_integrity": {
            "schema_version": EVIDENCE_INTEGRITY_SCHEMA_VERSION,
            "price_evidence_status": EXECUTION_ELIGIBLE,
            "price_fields": {},
            "provider_results": {"schwab_preserved_replay": "SUCCESS"},
            "rvol_evidence": rvol,
            "catalyst_attribution": catalyst,
            "authority_blocking_reasons": [],
            "plan_label": REAL_REPLAY_IDENTITY,
            "plan_authority": EXECUTION_ELIGIBLE,
            "setup_evidence": asdict(setup),
            "intraday_plan_evidence": asdict(intraday),
        },
        "trade_plan": plan,
        "opportunity_notes": [REPLAY_MODE],
    }


def _rvol_evidence(*, symbol, market_date, prior_session_date, current, baseline):
    current_volume = sum(bar.volume for bar in current)
    baseline_volume = sum(bar.volume for bar in baseline)
    if baseline_volume <= 0:
        raise RegularSessionReplayError("Baseline opening volume must be positive.")
    start = datetime.fromisoformat(current[0].timestamp)
    end = datetime.fromisoformat(current[-1].timestamp)
    return {
        "schema_version": TIME_NORMALIZED_RVOL_SCHEMA_VERSION,
        "profile": TIME_NORMALIZED_RVOL_PROFILE,
        "status": EXECUTION_ELIGIBLE,
        "source": SCHWAB_PRICE_HISTORY_SOURCE,
        "symbol": symbol,
        "rvol_type": "INTRADAY_RVOL",
        "session_name": "REGULAR",
        "session_date": market_date,
        "session_minute": 5,
        "window_start": start.isoformat(),
        "through_minute": end.isoformat(),
        "observed_volume": current_volume,
        "expected_volume": baseline_volume,
        "relative_volume": current_volume / baseline_volume,
        "current_bar_count": 5,
        "expected_current_bar_count": 5,
        "baseline_session_count": 1,
        "minimum_baseline_sessions": 1,
        "target_baseline_sessions": 1,
        "baseline_session_dates": [prior_session_date],
        "formula": TIME_NORMALIZED_RVOL_FORMULA,
        "findings": ["TIME_NORMALIZED_RVOL_AVAILABLE"],
    }


def _select_quote(payload: Mapping[str, object], symbol: str) -> dict[str, object]:
    if payload.get("proofStatus") != "PASS":
        raise RegularSessionReplayError("Preserved quote proof did not pass.")
    quotes = payload.get("quotes")
    if not isinstance(quotes, list):
        raise RegularSessionReplayError("Preserved quote proof omitted quotes.")
    for value in quotes:
        if isinstance(value, Mapping) and str(value.get("symbol", "")).upper() == symbol:
            quote = dict(value)
            if quote.get("source") != SCHWAB_QUOTE_SOURCE:
                raise RegularSessionReplayError("Quote source is not canonical Schwab.")
            return quote
    raise RegularSessionReplayError(f"Preserved quote proof omitted {symbol}.")


def _opening_bars(payload: Mapping[str, object], *, symbol: str, session_date: str):
    if payload.get("symbol") != symbol or payload.get("legacySourceMixed") is not False:
        raise RegularSessionReplayError("Minute-store identity is invalid or mixed.")
    selected: list[CanonicalMinuteBar] = []
    identities: list[str] = []
    for item in payload.get("bars", []):
        if not isinstance(item, Mapping) or item.get("state") not in {
            "RECONCILED",
            "CORRECTED",
            "HISTORY_ONLY_GAP_FILL",
        }:
            continue
        candle = item.get("canonicalCandle")
        if not isinstance(candle, Mapping) or candle.get("sessionDate") != session_date:
            continue
        if candle.get("source") != SCHWAB_PRICE_HISTORY_SOURCE:
            raise RegularSessionReplayError(
                "Opening candle source is not canonical Schwab price history."
            )
        timestamp = _aware_datetime(candle.get("timestamp"), "minute timestamp")
        eastern = timestamp.astimezone(EASTERN_TZ)
        if not (eastern.hour == 9 and 30 <= eastern.minute <= 34):
            continue
        selected.append(
            CanonicalMinuteBar(
                symbol=symbol,
                timestamp=timestamp.isoformat(),
                open=float(candle["open"]),
                high=float(candle["high"]),
                low=float(candle["low"]),
                close=float(candle["close"]),
                volume=float(candle["volume"]),
                source=str(candle["source"]),
                state=str(item["state"]),
                session_date=session_date,
            )
        )
        versions = item.get("historyVersions")
        version_id = versions[0].get("versionId") if isinstance(versions, list) and versions else ""
        identities.append(f"{item.get('minuteIdentity')}|version:{version_id}")
    selected.sort(key=lambda item: item.timestamp)
    if len(selected) != 5 or len({item.timestamp for item in selected}) != 5:
        raise RegularSessionReplayError("Exactly five canonical opening bars are required.")
    return selected, tuple(identities)


def _daily_bar(payload: Mapping[str, object], *, symbol: str, session_date: str):
    if payload.get("symbol") != symbol or payload.get("legacySourceMixed") is not False:
        raise RegularSessionReplayError("Daily-store identity is invalid or mixed.")
    for item in payload.get("bars", []):
        if not isinstance(item, Mapping) or item.get("sessionDate") != session_date:
            continue
        if item.get("state") != "CANONICAL":
            raise RegularSessionReplayError("Completed Daily candle is not canonical.")
        candle = item.get("canonicalCandle")
        versions = item.get("historyVersions")
        if not isinstance(candle, Mapping) or candle.get("source") != SCHWAB_PRICE_HISTORY_SOURCE:
            raise RegularSessionReplayError("Daily candle source is not canonical Schwab history.")
        version_id = versions[0].get("versionId") if isinstance(versions, list) and versions else ""
        identity = f"{item.get('dailyIdentity')}|version:{version_id}"
        return dict(candle), identity
    raise RegularSessionReplayError("Required completed Daily candle is missing.")


def write_replay_packet(packet: Mapping[str, object], *, output_root: Path) -> dict[str, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    fingerprint = str(packet["packetFingerprint"])
    stem = f"real-regular-session-replay-{fingerprint[:16].lower()}"
    json_path = output_root / f"{stem}.json"
    markdown_path = output_root / f"{stem}.md"
    _write_new(json_path, json.dumps(packet, indent=2, sort_keys=True) + "\n")
    _write_new(markdown_path, _markdown(packet))
    return {"json": json_path, "markdown": markdown_path}


def _markdown(packet: Mapping[str, object]) -> str:
    chain = packet["decisionChain"]
    risk = chain["riskGovernor"]
    lines = [
        "# Real Preserved Regular-Session Replay Trace",
        "",
        f"- Classification: `{packet['classification']}`",
        f"- Entire chain reached boundary: `{packet['entireDecisionChainReachedBrokerBoundary']}`",
        f"- Original market time: `{packet['originalMarketTime']['decisionEvaluationTime']}`",
        f"- Replay evaluation time: `{packet['replayEvaluationTime']['timestamp']}`",
        f"- Risk status: `{risk['status']}`",
        f"- Risk blockers: `{', '.join(risk['blockers']) or 'None'}`",
        f"- Allocation: `{chain['data005bAllocation']['status']}`",
        f"- Order intent: `{chain['orderIntent']['status']}`",
        f"- Provider calls: `{chain['submissionBoundary']['providerCalls']}`",
        "",
        "## Evidence distinction",
        "",
        f"The older `{OLD_AMBIGUOUS_IDENTITY}` label describes a constructed fixture. "
        f"The clearer prospective identity is `{CONSTRUCTED_FIXTURE_IDENTITY}`. "
        f"This packet uses `{REAL_REPLAY_IDENTITY}`.",
        "",
        "## Source identities",
        "",
    ]
    lines.extend(
        f"- `{item['role']}` `{item['sha256']}` `{item['path']}`"
        for item in packet["sourceFiles"]
    )
    lines.extend(
        [
            "",
            "No order was submitted, no official sample was changed, and no historical trade was created.",
            "",
        ]
    )
    return "\n".join(lines)


def _load_json(path: Path, label: str) -> Mapping[str, object]:
    if not path.is_file():
        raise RegularSessionReplayError(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RegularSessionReplayError(f"{label} is invalid: {path}") from exc
    if not isinstance(value, Mapping):
        raise RegularSessionReplayError(f"{label} must be a JSON object.")
    return value


def _sha256_file(path: Path) -> str:
    if not path.is_file():
        raise RegularSessionReplayError(f"Preserved source is missing: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _aware_datetime(value: object, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise RegularSessionReplayError(f"{label} is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RegularSessionReplayError(f"{label} must include a UTC offset.")
    return parsed


def _write_new(path: Path, content: str) -> None:
    if path.exists():
        raise RegularSessionReplayError(f"Replay output already exists: {path}")
    path.write_text(content, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quote-proof", type=Path, required=True)
    parser.add_argument("--minute-store", type=Path, required=True)
    parser.add_argument("--baseline-minute-store", type=Path, required=True)
    parser.add_argument("--daily-store", type=Path, required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market-date", required=True)
    parser.add_argument("--prior-session-date", required=True)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args(argv)
    packet = run_regular_session_replay(
        quote_proof_path=args.quote_proof,
        minute_store_path=args.minute_store,
        baseline_minute_store_path=args.baseline_minute_store,
        daily_store_path=args.daily_store,
        symbol=args.symbol,
        market_date=args.market_date,
        prior_session_date=args.prior_session_date,
        output_root=args.output_dir,
    )
    print(json.dumps(packet, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
