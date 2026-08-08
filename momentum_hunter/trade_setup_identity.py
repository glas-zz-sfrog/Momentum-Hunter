"""Deterministic breakout-versus-reclaim identity for prospective TradePlans."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace

from momentum_hunter.evidence_integrity import (
    EXECUTION_ELIGIBLE,
    EXECUTION_INELIGIBLE,
)


TRADE_SETUP_SCHEMA_VERSION = 1
TRADE_SETUP_PROFILE = "breakout-reclaim-identity-v1"
BREAKOUT_SETUP = "BREAKOUT"
RECLAIM_REQUIRED_SETUP = "RECLAIM_REQUIRED"
SETUP_UNAVAILABLE = "UNAVAILABLE"
PENDING_BREAKOUT = "PENDING_BREAKOUT"
RECLAIM_NOT_CONFIRMED = "RECLAIM_NOT_CONFIRMED"
CONFIRMATION_UNAVAILABLE = "UNAVAILABLE"
SETUP_IDENTITY_EXECUTION_INELIGIBLE = "SETUP_IDENTITY_EXECUTION_INELIGIBLE"
RECLAIM_CONFIRMATION_REQUIRED = "RECLAIM_CONFIRMATION_REQUIRED"
DO_NOT_TRADE_SETUP_UNCONFIRMED = "DO_NOT_TRADE_SETUP_UNCONFIRMED"
DAILY_LEVEL_SOURCE = "daily_bars"
BREAKOUT_CONFIRMATION_RULE = "PRICE_CROSSES_ABOVE_BREAKOUT_LEVEL"
RECLAIM_CONFIRMATION_RULE = (
    "PRICE_TRADES_AT_OR_BELOW_BREAKOUT_LEVEL_THEN_RECROSSES_ABOVE"
)
INVALIDATION_RULE = "PRICE_TRADES_AT_OR_BELOW_INVALIDATION_LEVEL"


@dataclass(frozen=True)
class TradeSetupEvidence:
    schema_version: int = TRADE_SETUP_SCHEMA_VERSION
    profile: str = TRADE_SETUP_PROFILE
    status: str = EXECUTION_INELIGIBLE
    symbol: str = ""
    setup_type: str = SETUP_UNAVAILABLE
    source: str = ""
    observed_price: float | None = None
    breakout_level: float | None = None
    planned_entry: float | None = None
    confirmation_status: str = CONFIRMATION_UNAVAILABLE
    confirmation_rule: str = ""
    invalidation_level: float | None = None
    invalidation_rule: str = ""
    requires_pullback: bool = False
    findings: tuple[str, ...] = field(default_factory=tuple)
    fingerprint: str = ""

    @property
    def execution_eligible(self) -> bool:
        """Identity authority only; this is not trade or entry approval."""

        return self.status == EXECUTION_ELIGIBLE


def build_trade_setup_evidence(
    *,
    symbol: str,
    observed_price: float | None,
    breakout_level: float | None,
    invalidation_level: float | None,
    source: str,
) -> TradeSetupEvidence:
    """Classify a plan without converting an already-broken level into a chase."""

    normalized_symbol = str(symbol).strip().upper()
    findings: list[str] = []
    if not normalized_symbol:
        findings.append("SETUP_SYMBOL_MISSING")
    if source != DAILY_LEVEL_SOURCE:
        findings.append("AUTHORITATIVE_DAILY_LEVELS_UNAVAILABLE")
    if not _positive_finite(observed_price):
        findings.append("SETUP_OBSERVED_PRICE_INVALID")
    if not _positive_finite(breakout_level):
        findings.append("SETUP_BREAKOUT_LEVEL_INVALID")
    if not _positive_finite(invalidation_level):
        findings.append("SETUP_INVALIDATION_LEVEL_INVALID")
    if (
        _positive_finite(breakout_level)
        and _positive_finite(invalidation_level)
        and float(invalidation_level) >= float(breakout_level)
    ):
        findings.append("SETUP_LEVEL_ORDER_INVALID")

    if findings:
        return _with_fingerprint(
            TradeSetupEvidence(
                symbol=normalized_symbol,
                source=source,
                observed_price=_rounded(observed_price),
                breakout_level=_rounded(breakout_level),
                planned_entry=_rounded(breakout_level),
                invalidation_level=_rounded(invalidation_level),
                invalidation_rule=(
                    INVALIDATION_RULE if _positive_finite(invalidation_level) else ""
                ),
                findings=tuple(findings),
            )
        )

    observed = float(_rounded(observed_price))
    breakout = float(_rounded(breakout_level))
    if observed > breakout:
        setup_type = RECLAIM_REQUIRED_SETUP
        confirmation_status = RECLAIM_NOT_CONFIRMED
        confirmation_rule = RECLAIM_CONFIRMATION_RULE
        requires_pullback = True
        findings.append("PRICE_ALREADY_ABOVE_BREAKOUT_LEVEL")
        findings.append(RECLAIM_CONFIRMATION_REQUIRED)
    else:
        setup_type = BREAKOUT_SETUP
        confirmation_status = PENDING_BREAKOUT
        confirmation_rule = BREAKOUT_CONFIRMATION_RULE
        requires_pullback = False
        findings.append("BREAKOUT_LEVEL_AHEAD")
    return _with_fingerprint(
        TradeSetupEvidence(
            status=EXECUTION_ELIGIBLE,
            symbol=normalized_symbol,
            setup_type=setup_type,
            source=source,
            observed_price=_rounded(observed),
            breakout_level=_rounded(breakout),
            planned_entry=_rounded(breakout),
            confirmation_status=confirmation_status,
            confirmation_rule=confirmation_rule,
            invalidation_level=_rounded(invalidation_level),
            invalidation_rule=INVALIDATION_RULE,
            requires_pullback=requires_pullback,
            findings=tuple(findings),
        )
    )


def trade_setup_fingerprint(evidence: TradeSetupEvidence) -> str:
    payload = asdict(replace(evidence, fingerprint=""))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _with_fingerprint(evidence: TradeSetupEvidence) -> TradeSetupEvidence:
    return replace(evidence, fingerprint=trade_setup_fingerprint(evidence))


def _positive_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _rounded(value: object) -> float | None:
    if not _positive_finite(value):
        return None
    return round(float(value), 2)
