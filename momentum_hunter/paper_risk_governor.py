from __future__ import annotations

"""Fail-closed risk authorization for the Alpaca Paper engineering lane."""

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from momentum_hunter.autonomy.view_models import stable_trade_plan_id
from momentum_hunter.continuous_paper_contract import ContinuousPaperAdmissionIntent
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE
from momentum_hunter.intraday_trade_plan import intraday_plan_decision_findings
from momentum_hunter.provider_neutral_allocation import evidence_fingerprint
from momentum_hunter.schwab_market_data import SCHWAB_QUOTE_SOURCE
from momentum_hunter.shadow_selection import candidate_evidence_authority_findings
from momentum_hunter.trade_planning import TradePlan, trade_plan_from_dict


PAPER_RISK_SCHEMA_VERSION = 1
PAPER_RISK_PROFILE = "alpaca-paper-engineering-risk-v1"
PAPER_RISK_MODE = "ALPACA_PAPER_ENGINEERING"


@dataclass(frozen=True)
class PaperRiskPolicy:
    policy_id: str
    maximum_spread_percent: Decimal
    maximum_entry_extension_percent: Decimal
    minimum_reward_risk: Decimal
    schema_version: int = PAPER_RISK_SCHEMA_VERSION
    profile: str = PAPER_RISK_PROFILE

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))


@dataclass(frozen=True)
class PaperRiskDecision:
    risk_decision_id: str
    candidate_id: str
    symbol: str
    canonical_rank: int
    trade_plan_id: str
    setup_id: str
    decision_at: str
    mode: str
    status: str
    execution_price: Decimal | None
    spread_percent: Decimal | None
    reward_risk_at_execution: Decimal | None
    blockers: tuple[str, ...]
    policy_fingerprint: str
    source_evidence_fingerprint: str
    quote_evidence_fingerprint: str
    schema_version: int = PAPER_RISK_SCHEMA_VERSION
    profile: str = PAPER_RISK_PROFILE

    @property
    def authorized(self) -> bool:
        return self.status == "AUTHORIZED" and not self.blockers

    @property
    def fingerprint(self) -> str:
        return evidence_fingerprint(asdict(self))

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "profile": self.profile,
            "riskDecisionId": self.risk_decision_id,
            "candidateId": self.candidate_id,
            "symbol": self.symbol,
            "canonicalRank": self.canonical_rank,
            "tradePlanId": self.trade_plan_id,
            "setupId": self.setup_id,
            "decisionAt": self.decision_at,
            "mode": self.mode,
            "status": self.status,
            "executionPrice": _decimal_text(self.execution_price),
            "spreadPercent": _decimal_text(self.spread_percent),
            "rewardRiskAtExecution": _decimal_text(
                self.reward_risk_at_execution
            ),
            "blockers": list(self.blockers),
            "policyFingerprint": self.policy_fingerprint,
            "sourceEvidenceFingerprint": self.source_evidence_fingerprint,
            "quoteEvidenceFingerprint": self.quote_evidence_fingerprint,
            "fingerprint": self.fingerprint,
        }


def evaluate_paper_candidate(
    row: Mapping[str, object],
    *,
    quote_result: Mapping[str, object] | None,
    decision_at: datetime,
    policy: PaperRiskPolicy,
) -> tuple[PaperRiskDecision, TradePlan | None]:
    """Authorize one long Paper candidate without granting live authority."""

    candidate = dict(row)
    symbol = str(candidate.get("symbol", "")).strip().upper()
    candidate_id = str(candidate.get("candidate_id") or symbol).strip()
    rank = _positive_int(candidate.get("rank")) or 0
    blockers = _policy_findings(policy)
    blockers.extend(candidate_evidence_authority_findings(candidate))

    raw_plan = candidate.get("trade_plan")
    plan: TradePlan | None = None
    if isinstance(raw_plan, Mapping):
        try:
            plan = trade_plan_from_dict(raw_plan)
        except (TypeError, ValueError):
            blockers.append("PAPER_TRADE_PLAN_INVALID")
    else:
        blockers.append("PAPER_TRADE_PLAN_MISSING")

    trade_plan_id = ""
    setup_id = ""
    entry: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    if plan is not None:
        trade_plan_id = stable_trade_plan_id(symbol, plan)
        setup_id = str(plan.setup_evidence.fingerprint or "")
        entry = _positive_decimal(plan.bullish_entry)
        stop = _positive_decimal(plan.bullish_stop)
        target = _positive_decimal(plan.bullish_target_1)
        if not plan.readiness.startswith("EXECUTION_READY"):
            blockers.append("PAPER_TRADE_PLAN_NOT_EXECUTION_READY")
        if plan.blocking_reasons:
            blockers.extend(
                f"PAPER_TRADE_PLAN_BLOCKER:{item}"
                for item in plan.blocking_reasons
            )
        blockers.extend(
            f"PAPER_INTRADAY_PLAN:{item}"
            for item in intraday_plan_decision_findings(
                plan.intraday_evidence,
                decision_at=decision_at,
            )
        )
        if not (entry and stop and target and stop < entry < target):
            blockers.append("PAPER_TRADE_PLAN_LEVELS_INVALID")

    quote = dict(quote_result or {})
    quote_fingerprint = evidence_fingerprint(quote)
    execution_price, spread, quote_blockers = _quote_findings(
        quote,
        symbol=symbol,
        decision_at=decision_at,
        entry=entry,
        stop=stop,
        target=target,
        policy=policy,
    )
    blockers.extend(quote_blockers)

    reward_risk: Decimal | None = None
    if execution_price is not None and stop is not None and target is not None:
        risk = execution_price - stop
        reward = target - execution_price
        if risk <= 0 or reward <= 0:
            blockers.append("PAPER_EXECUTION_LEVELS_INVALID")
        else:
            reward_risk = reward / risk
            if reward_risk < policy.minimum_reward_risk:
                blockers.append("PAPER_EXECUTION_REWARD_RISK_TOO_LOW")

    blockers = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    source_fingerprint = evidence_fingerprint(candidate)
    identity = {
        "schemaVersion": PAPER_RISK_SCHEMA_VERSION,
        "profile": PAPER_RISK_PROFILE,
        "candidateId": candidate_id,
        "symbol": symbol,
        "canonicalRank": rank,
        "tradePlanId": trade_plan_id,
        "setupId": setup_id,
        "decisionAt": decision_at.isoformat(),
        "policyFingerprint": policy.fingerprint,
        "sourceEvidenceFingerprint": source_fingerprint,
        "quoteEvidenceFingerprint": quote_fingerprint,
    }
    risk_id = "paper-risk-" + evidence_fingerprint(identity)[:24].lower()
    return (
        PaperRiskDecision(
            risk_decision_id=risk_id,
            candidate_id=candidate_id,
            symbol=symbol,
            canonical_rank=rank,
            trade_plan_id=trade_plan_id,
            setup_id=setup_id,
            decision_at=decision_at.isoformat(),
            mode=PAPER_RISK_MODE,
            status="BLOCKED" if blockers else "AUTHORIZED",
            execution_price=execution_price,
            spread_percent=spread,
            reward_risk_at_execution=reward_risk,
            blockers=tuple(blockers),
            policy_fingerprint=policy.fingerprint,
            source_evidence_fingerprint=source_fingerprint,
            quote_evidence_fingerprint=quote_fingerprint,
        ),
        plan,
    )


def evaluate_continuous_paper_admission(
    admission: ContinuousPaperAdmissionIntent,
    *,
    quote_result: Mapping[str, object] | None,
    decision_at: datetime,
    policy: PaperRiskPolicy,
) -> PaperRiskDecision:
    """Apply the existing Paper execution gates to one continuous TradePlan."""

    plan = admission.trade_plan
    blockers = _policy_findings(policy)
    blockers.extend(
        f"PAPER_INTRADAY_PLAN:{item}"
        for item in intraday_plan_decision_findings(
            plan,
            decision_at=decision_at,
        )
    )
    entry = _positive_decimal(plan.planned_entry)
    stop = _positive_decimal(plan.stop_price)
    target = _positive_decimal(plan.target_prices[0] if plan.target_prices else None)
    if not (entry and stop and target and stop < entry < target):
        blockers.append("PAPER_TRADE_PLAN_LEVELS_INVALID")

    quote = dict(quote_result or {})
    quote_fingerprint = evidence_fingerprint(quote)
    execution_price, spread, quote_blockers = _quote_findings(
        quote,
        symbol=admission.symbol,
        decision_at=decision_at,
        entry=entry,
        stop=stop,
        target=target,
        policy=policy,
    )
    blockers.extend(quote_blockers)

    reward_risk: Decimal | None = None
    if execution_price is not None and stop is not None and target is not None:
        risk = execution_price - stop
        reward = target - execution_price
        if risk <= 0 or reward <= 0:
            blockers.append("PAPER_EXECUTION_LEVELS_INVALID")
        else:
            reward_risk = reward / risk
            if reward_risk < policy.minimum_reward_risk:
                blockers.append("PAPER_EXECUTION_REWARD_RISK_TOO_LOW")

    blockers = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    identity = {
        "schemaVersion": PAPER_RISK_SCHEMA_VERSION,
        "profile": PAPER_RISK_PROFILE,
        "admissionId": admission.admission_id,
        "candidateId": admission.candidate_id,
        "symbol": admission.symbol,
        "canonicalRank": admission.canonical_rank,
        "tradePlanId": admission.trade_plan_id,
        "setupId": admission.setup_id,
        "decisionAt": decision_at.isoformat(),
        "policyFingerprint": policy.fingerprint,
        "sourceEvidenceFingerprint": admission.fingerprint,
        "quoteEvidenceFingerprint": quote_fingerprint,
    }
    return PaperRiskDecision(
        risk_decision_id=(
            "paper-risk-" + evidence_fingerprint(identity)[:24].lower()
        ),
        candidate_id=admission.candidate_id,
        symbol=admission.symbol,
        canonical_rank=admission.canonical_rank,
        trade_plan_id=admission.trade_plan_id,
        setup_id=admission.setup_id,
        decision_at=decision_at.isoformat(),
        mode=PAPER_RISK_MODE,
        status="BLOCKED" if blockers else "AUTHORIZED",
        execution_price=execution_price,
        spread_percent=spread,
        reward_risk_at_execution=reward_risk,
        blockers=tuple(blockers),
        policy_fingerprint=policy.fingerprint,
        source_evidence_fingerprint=admission.fingerprint,
        quote_evidence_fingerprint=quote_fingerprint,
    )


def _quote_findings(
    quote: Mapping[str, object],
    *,
    symbol: str,
    decision_at: datetime,
    entry: Decimal | None,
    stop: Decimal | None,
    target: Decimal | None,
    policy: PaperRiskPolicy,
) -> tuple[Decimal | None, Decimal | None, list[str]]:
    blockers: list[str] = []
    if quote.get("status") != "PASS":
        blockers.append("PAPER_SCHWAB_QUOTE_PROOF_FAILED")
    if str(quote.get("symbol", "")).strip().upper() != symbol:
        blockers.append("PAPER_QUOTE_SYMBOL_MISMATCH")
    if str(quote.get("source", "")).strip() != SCHWAB_QUOTE_SOURCE:
        blockers.append("PAPER_QUOTE_SOURCE_NOT_SCHWAB")
    if str(quote.get("session", "")).strip().lower() != "regular":
        blockers.append("PAPER_QUOTE_SESSION_NOT_REGULAR")
    if str(quote.get("tradingState", "")).strip().lower() not in {
        "open",
        "tradable",
    }:
        blockers.append("PAPER_QUOTE_NOT_TRADABLE")
    if quote.get("realtime") is not True:
        blockers.append("PAPER_QUOTE_NOT_REALTIME")
    quote_at = _aware_datetime(quote.get("timestamp"))
    if quote_at is None or quote_at > decision_at:
        blockers.append("PAPER_QUOTE_TIMESTAMP_INVALID")
    age = _decimal(quote.get("quoteAgeSeconds"))
    if age is None or age < 0 or age > Decimal("30"):
        blockers.append("PAPER_QUOTE_STALE")
    bid = _positive_decimal(quote.get("bid"))
    ask = _positive_decimal(quote.get("ask"))
    spread: Decimal | None = None
    if bid is None or ask is None or ask < bid:
        blockers.append("PAPER_QUOTE_BID_ASK_INVALID")
    else:
        spread = (ask - bid) / ask * Decimal("100")
        if spread > policy.maximum_spread_percent:
            blockers.append("PAPER_QUOTE_SPREAD_TOO_WIDE")
    if ask is not None and entry is not None:
        if ask < entry:
            blockers.append("PAPER_ENTRY_TRIGGER_NOT_REACHED")
        else:
            extension = (ask - entry) / entry * Decimal("100")
            if extension > policy.maximum_entry_extension_percent:
                blockers.append("PAPER_ENTRY_EXTENSION_TOO_LARGE")
    if bid is not None and stop is not None and bid <= stop:
        blockers.append("PAPER_PRICE_AT_OR_BELOW_STOP")
    if ask is not None and target is not None and ask >= target:
        blockers.append("PAPER_PRICE_AT_OR_ABOVE_TARGET")
    return ask, spread, blockers


def _policy_findings(policy: PaperRiskPolicy) -> list[str]:
    findings: list[str] = []
    if (
        policy.schema_version != PAPER_RISK_SCHEMA_VERSION
        or policy.profile != PAPER_RISK_PROFILE
        or not policy.policy_id.strip()
    ):
        findings.append("PAPER_RISK_POLICY_UNSUPPORTED")
    if _positive_decimal(policy.maximum_spread_percent) is None:
        findings.append("PAPER_RISK_MAXIMUM_SPREAD_INVALID")
    if _positive_decimal(policy.maximum_entry_extension_percent) is None:
        findings.append("PAPER_RISK_ENTRY_EXTENSION_INVALID")
    if _positive_decimal(policy.minimum_reward_risk) is None:
        findings.append("PAPER_RISK_MINIMUM_REWARD_RISK_INVALID")
    return findings


def _positive_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _decimal(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _positive_decimal(value: object) -> Decimal | None:
    parsed = _decimal(value)
    return parsed if parsed is not None and parsed > 0 else None


def _aware_datetime(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")
