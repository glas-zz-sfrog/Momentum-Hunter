"""Versioned same-session lifecycle evidence for prospective TradePlans."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, time, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from momentum_hunter.canonical_candle_evidence import CANONICAL_OUTCOME_STATES
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_SUPPORTED,
    CUSTOMER_SUPPLIER,
    DIRECT_ISSUER,
    EXECUTION_ELIGIBLE,
    EXECUTION_INELIGIBLE,
    MACRO,
    PEER,
    SECTOR,
)
from momentum_hunter.schwab_candle_contract import SCHWAB_PRICE_HISTORY_SOURCE
from momentum_hunter.scheduling import is_market_open_day


EASTERN_TZ = ZoneInfo("America/New_York")
INTRADAY_PLAN_SCHEMA_VERSION = 1
INTRADAY_PLAN_PROFILE = "same-session-intraday-plan-v1"
INTRADAY_HORIZON = "INTRADAY"

OPENING_BREAKOUT = "OPENING_BREAKOUT"
CONTINUATION_BREAKOUT = "CONTINUATION_BREAKOUT"
PULLBACK = "PULLBACK"
RECLAIM = "RECLAIM"
SETUP_FAMILY_UNAVAILABLE = "UNAVAILABLE"
SUPPORTED_SETUP_FAMILIES = frozenset(
    {OPENING_BREAKOUT, CONTINUATION_BREAKOUT, PULLBACK, RECLAIM}
)

TECHNICAL_DRIVER = "TECHNICAL"
CATALYST_DRIVER = "CATALYST"
SUPPORTED_CATALYST_RELATIONSHIPS = frozenset(
    {DIRECT_ISSUER, SECTOR, PEER, CUSTOMER_SUPPLIER, MACRO}
)

PENDING_ENTRY = "PENDING_ENTRY"
TRIGGERED = "TRIGGERED"
MISSED_ENTRY = "MISSED_ENTRY"
EXPIRED = "EXPIRED"
INVALIDATED = "INVALIDATED"
UNAVAILABLE = "UNAVAILABLE"
TERMINAL_PLAN_STATES = frozenset({MISSED_ENTRY, EXPIRED, INVALIDATED})
ACTIVE_PLAN_STATES = frozenset({PENDING_ENTRY, TRIGGERED})
ALLOWED_LIFECYCLE_TRANSITIONS = {
    PENDING_ENTRY: frozenset(
        {PENDING_ENTRY, TRIGGERED, MISSED_ENTRY, EXPIRED, INVALIDATED}
    ),
    TRIGGERED: frozenset({TRIGGERED, EXPIRED, INVALIDATED}),
    MISSED_ENTRY: frozenset({MISSED_ENTRY}),
    EXPIRED: frozenset({EXPIRED}),
    INVALIDATED: frozenset({INVALIDATED}),
}

INTRADAY_PLAN_EXECUTION_INELIGIBLE = "INTRADAY_PLAN_EXECUTION_INELIGIBLE"
DO_NOT_TRADE_MISSED_ENTRY = "DO_NOT_TRADE_MISSED_ENTRY"

REGULAR_ENTRY_CUTOFF = time(15, 30)
REGULAR_FORCED_FLAT = time(15, 55)
REGULAR_SESSION_OPEN = time(9, 30)
EARLY_CLOSE_ENTRY_CUTOFF = time(12, 30)
EARLY_CLOSE_FORCED_FLAT = time(12, 55)
OPENING_ENTRY_START = time(9, 35)
OPENING_ENTRY_CUTOFF = time(10, 30)
SETUP_LIFETIME_MINUTES = {
    CONTINUATION_BREAKOUT: 45,
    PULLBACK: 30,
    RECLAIM: 30,
}


@dataclass(frozen=True)
class IntradayPlanEvidence:
    schema_version: int = INTRADAY_PLAN_SCHEMA_VERSION
    profile: str = INTRADAY_PLAN_PROFILE
    status: str = EXECUTION_INELIGIBLE
    horizon: str = INTRADAY_HORIZON
    plan_id: str = ""
    symbol: str = ""
    session_date: str = ""
    setup_family: str = SETUP_FAMILY_UNAVAILABLE
    setup_driver: str = TECHNICAL_DRIVER
    lifecycle_status: str = UNAVAILABLE
    lifecycle_updated_at: str = ""
    created_at: str = ""
    entry_valid_from: str = ""
    entry_expires_at: str = ""
    forced_flat_at: str = ""
    planned_entry: float | None = None
    stop_price: float | None = None
    target_prices: tuple[float, ...] = field(default_factory=tuple)
    trigger_rule: str = ""
    stop_rule: str = ""
    target_rule: str = ""
    forced_flat_rule: str = ""
    source_setup_fingerprint: str = ""
    source_level_kind: str = ""
    source_evidence_ids: tuple[str, ...] = field(default_factory=tuple)
    catalyst_relationship_type: str = ""
    catalyst_score_authority: str = ""
    catalyst_attribution_fingerprint: str = ""
    predecessor_plan_id: str = ""
    predecessor_plan_fingerprint: str = ""
    replacement_reason: str = ""
    findings: tuple[str, ...] = field(default_factory=tuple)
    fingerprint: str = ""

    @property
    def execution_eligible(self) -> bool:
        """Plan-horizon authority only; this does not approve sizing or execution."""

        return (
            self.status == EXECUTION_ELIGIBLE
            and self.lifecycle_status in ACTIVE_PLAN_STATES
        )


def build_intraday_plan_evidence(
    *,
    symbol: str,
    setup_family: str,
    created_at: datetime,
    planned_entry: float,
    stop_price: float,
    target_prices: Iterable[float],
    source_setup_fingerprint: str,
    source_level_kind: str,
    source_evidence_ids: Iterable[str] = (),
    observed_price: float | None = None,
    setup_driver: str = TECHNICAL_DRIVER,
    catalyst_relationship_type: str = "",
    catalyst_score_authority: str = "",
    catalyst_attribution_fingerprint: str = "",
    entry_valid_from: datetime | None = None,
    entry_expires_at: datetime | None = None,
    forced_flat_at: datetime | None = None,
    early_close: bool = False,
    predecessor: IntradayPlanEvidence | None = None,
    replacement_reason: str = "",
    lifecycle_status: str | None = None,
) -> IntradayPlanEvidence:
    """Build one immutable same-session plan identity and its current lifecycle state."""

    normalized_symbol = str(symbol).strip().upper()
    normalized_family = str(setup_family).strip().upper()
    normalized_driver = str(setup_driver).strip().upper() or TECHNICAL_DRIVER
    targets = tuple(_rounded_price(item) for item in target_prices)
    targets = tuple(item for item in targets if item is not None)
    created = _aware(created_at)
    findings: list[str] = []

    if not normalized_symbol:
        findings.append("INTRADAY_PLAN_SYMBOL_MISSING")
    if normalized_family not in SUPPORTED_SETUP_FAMILIES:
        findings.append("INTRADAY_SETUP_FAMILY_UNSUPPORTED")
    if normalized_driver not in {TECHNICAL_DRIVER, CATALYST_DRIVER}:
        findings.append("INTRADAY_SETUP_DRIVER_UNSUPPORTED")
    if normalized_driver == CATALYST_DRIVER:
        if (
            catalyst_relationship_type not in SUPPORTED_CATALYST_RELATIONSHIPS
            or catalyst_score_authority != CATALYST_SCORE_SUPPORTED
        ):
            findings.append("CATALYST_DRIVEN_SETUP_ATTRIBUTION_UNSUPPORTED")
        if not _sha256(catalyst_attribution_fingerprint):
            findings.append("CATALYST_DRIVEN_SETUP_ATTRIBUTION_IDENTITY_MISSING")
    if not _sha256(source_setup_fingerprint):
        findings.append("INTRADAY_SOURCE_SETUP_FINGERPRINT_INVALID")
    if not str(source_level_kind).strip():
        findings.append("INTRADAY_SOURCE_LEVEL_KIND_MISSING")
    normalized_source_ids = tuple(
        dict.fromkeys(
            str(item).strip() for item in source_evidence_ids if str(item).strip()
        )
    )
    if not normalized_source_ids:
        findings.append("INTRADAY_SOURCE_EVIDENCE_IDS_MISSING")
    if not _positive_finite(planned_entry):
        findings.append("INTRADAY_ENTRY_INVALID")
    if not _positive_finite(stop_price):
        findings.append("INTRADAY_STOP_INVALID")
    if (
        _positive_finite(planned_entry)
        and _positive_finite(stop_price)
        and float(stop_price) >= float(planned_entry)
    ):
        findings.append("INTRADAY_STOP_NOT_BELOW_ENTRY")
    if not targets or any(
        not _positive_finite(target) or float(target) <= float(planned_entry)
        for target in targets
    ):
        findings.append("INTRADAY_TARGETS_INVALID")

    valid_from, expires, forced_flat = _plan_deadlines(
        created,
        normalized_family,
        entry_valid_from=entry_valid_from,
        entry_expires_at=entry_expires_at,
        forced_flat_at=forced_flat_at,
        early_close=early_close,
    )
    eastern_created = created.astimezone(EASTERN_TZ)
    session_date = eastern_created.date().isoformat()
    session_open = datetime.combine(
        eastern_created.date(), REGULAR_SESSION_OPEN, tzinfo=EASTERN_TZ
    )
    if not session_open <= created < forced_flat:
        findings.append("INTRADAY_PLAN_CREATED_OUTSIDE_REGULAR_SESSION")
    if not is_market_open_day(eastern_created.date()):
        findings.append("INTRADAY_PLAN_SESSION_IS_NOT_MARKET_DAY")
    if not (
        created <= valid_from <= expires < forced_flat
        and all(
            item.astimezone(EASTERN_TZ).date() == eastern_created.date()
            for item in (valid_from, expires, forced_flat)
        )
    ):
        findings.append("INTRADAY_PLAN_TIMING_INVALID")

    predecessor_id = ""
    predecessor_fingerprint = ""
    normalized_replacement_reason = str(replacement_reason).strip()
    if predecessor is not None:
        predecessor_findings = intraday_plan_validation_findings(predecessor)
        if predecessor_findings:
            findings.append("INTRADAY_PREDECESSOR_INVALID")
        if predecessor.lifecycle_status not in TERMINAL_PLAN_STATES:
            findings.append("INTRADAY_PREDECESSOR_NOT_TERMINAL")
        if predecessor.symbol != normalized_symbol:
            findings.append("INTRADAY_PREDECESSOR_SYMBOL_MISMATCH")
        if predecessor.session_date != session_date:
            findings.append("INTRADAY_PREDECESSOR_SESSION_MISMATCH")
        if not normalized_replacement_reason:
            findings.append("INTRADAY_REPLACEMENT_REASON_MISSING")
        predecessor_id = predecessor.plan_id
        predecessor_fingerprint = predecessor.fingerprint
    elif normalized_family == RECLAIM:
        findings.append("RECLAIM_PREDECESSOR_REQUIRED")
    if predecessor is None and normalized_replacement_reason:
        findings.append("INTRADAY_REPLACEMENT_PREDECESSOR_REQUIRED")
    if (
        normalized_family == RECLAIM
        and predecessor is not None
        and predecessor.setup_family not in {OPENING_BREAKOUT, CONTINUATION_BREAKOUT}
    ):
        findings.append("RECLAIM_BREAKOUT_PREDECESSOR_REQUIRED")

    state = lifecycle_status or _initial_lifecycle_state(
        family=normalized_family,
        created_at=created,
        expires_at=expires,
        observed_price=observed_price,
        entry=float(planned_entry) if _positive_finite(planned_entry) else None,
        stop=float(stop_price) if _positive_finite(stop_price) else None,
    )
    if state not in ACTIVE_PLAN_STATES | TERMINAL_PLAN_STATES:
        findings.append("INTRADAY_LIFECYCLE_STATUS_UNSUPPORTED")
        state = UNAVAILABLE
    if state == MISSED_ENTRY:
        findings.append("INTRADAY_ENTRY_MISSED_IMMUTABLY")
    elif state == EXPIRED:
        findings.append("INTRADAY_ENTRY_EXPIRED")
    elif state == INVALIDATED:
        findings.append("INTRADAY_PLAN_INVALIDATED")

    core = {
        "schema_version": INTRADAY_PLAN_SCHEMA_VERSION,
        "profile": INTRADAY_PLAN_PROFILE,
        "horizon": INTRADAY_HORIZON,
        "symbol": normalized_symbol,
        "session_date": session_date,
        "setup_family": normalized_family,
        "setup_driver": normalized_driver,
        "created_at": created.isoformat(),
        "entry_valid_from": valid_from.isoformat(),
        "entry_expires_at": expires.isoformat(),
        "forced_flat_at": forced_flat.isoformat(),
        "planned_entry": _rounded_price(planned_entry),
        "stop_price": _rounded_price(stop_price),
        "target_prices": targets,
        "source_setup_fingerprint": source_setup_fingerprint,
        "source_level_kind": str(source_level_kind).strip(),
        "source_evidence_ids": normalized_source_ids,
        "catalyst_relationship_type": str(catalyst_relationship_type).strip(),
        "catalyst_score_authority": str(catalyst_score_authority).strip(),
        "catalyst_attribution_fingerprint": str(
            catalyst_attribution_fingerprint
        ).strip(),
        "predecessor_plan_id": predecessor_id,
        "predecessor_plan_fingerprint": predecessor_fingerprint,
        "replacement_reason": normalized_replacement_reason,
    }
    plan_id = _stable_hash("intraday-plan-v1", _canonical_json(core))
    evidence = IntradayPlanEvidence(
        status=(
            EXECUTION_ELIGIBLE
            if not findings and state in ACTIVE_PLAN_STATES
            else EXECUTION_INELIGIBLE
        ),
        plan_id=plan_id,
        lifecycle_status=state,
        lifecycle_updated_at=created.isoformat(),
        trigger_rule=_trigger_rule(normalized_family),
        stop_rule=_stop_rule(normalized_family),
        target_rule=_target_rule(normalized_family),
        forced_flat_rule="EXIT_NO_LATER_THAN_PERSISTED_SAME_SESSION_DEADLINE",
        findings=tuple(dict.fromkeys(findings)),
        **core,
    )
    return _with_fingerprint(evidence)


def build_opening_breakout_plan_evidence(
    *,
    symbol: str,
    created_at: datetime,
    planned_entry: float,
    source_setup_fingerprint: str,
    minute_bars: Iterable[object],
    setup_driver: str = TECHNICAL_DRIVER,
    catalyst_relationship_type: str = "",
    catalyst_score_authority: str = "",
    catalyst_attribution_fingerprint: str = "",
    early_close: bool = False,
) -> IntradayPlanEvidence:
    """Build an opening-family plan from the five completed 09:30-09:34 ET bars."""

    created = _aware(created_at)
    eastern = created.astimezone(EASTERN_TZ)
    opening_start = datetime.combine(eastern.date(), time(9, 30), tzinfo=EASTERN_TZ)
    opening_end = datetime.combine(eastern.date(), OPENING_ENTRY_START, tzinfo=EASTERN_TZ)
    if created < opening_end:
        return unavailable_intraday_plan(
            symbol=symbol,
            finding="OPENING_RANGE_NOT_COMPLETE",
            source_setup_fingerprint=source_setup_fingerprint,
        )
    normalized: dict[datetime, object] = {}
    for bar in minute_bars:
        try:
            timestamp = _aware_datetime(str(getattr(bar, "timestamp")))
        except (AttributeError, ValueError):
            continue
        eastern_timestamp = timestamp.astimezone(EASTERN_TZ)
        if opening_start <= eastern_timestamp < opening_end:
            if not _canonical_opening_bar(
                bar,
                symbol=str(symbol).strip().upper(),
                session_date=eastern.date().isoformat(),
                eastern_timestamp=eastern_timestamp,
            ):
                return unavailable_intraday_plan(
                    symbol=symbol,
                    finding="OPENING_RANGE_CANONICAL_BAR_REQUIRED",
                    source_setup_fingerprint=source_setup_fingerprint,
                )
            identity = eastern_timestamp.replace(second=0, microsecond=0)
            if identity in normalized:
                return unavailable_intraday_plan(
                    symbol=symbol,
                    finding="OPENING_RANGE_DUPLICATE_BAR_IDENTITY",
                    source_setup_fingerprint=source_setup_fingerprint,
                )
            normalized[identity] = bar
    expected = tuple(opening_start + timedelta(minutes=index) for index in range(5))
    if tuple(sorted(normalized)) != expected:
        return unavailable_intraday_plan(
            symbol=symbol,
            finding="OPENING_RANGE_FIVE_COMPLETED_BARS_REQUIRED",
            source_setup_fingerprint=source_setup_fingerprint,
        )
    lows = tuple(_bar_value(normalized[item], "low") for item in expected)
    highs = tuple(_bar_value(normalized[item], "high") for item in expected)
    if any(value is None for value in (*lows, *highs)):
        return unavailable_intraday_plan(
            symbol=symbol,
            finding="OPENING_RANGE_OHLC_INVALID",
            source_setup_fingerprint=source_setup_fingerprint,
        )
    stop = min(float(value) for value in lows if value is not None)
    entry = float(planned_entry)
    risk = entry - stop
    if risk <= 0:
        return unavailable_intraday_plan(
            symbol=symbol,
            finding="OPENING_RANGE_STOP_NOT_BELOW_DAILY_BREAKOUT",
            source_setup_fingerprint=source_setup_fingerprint,
        )
    opening_high = max(float(value) for value in highs if value is not None)
    source_ids = tuple(
        f"{getattr(normalized[item], 'source', 'UNKNOWN')}:{getattr(normalized[item], 'timestamp', '')}"
        for item in expected
    )
    return build_intraday_plan_evidence(
        symbol=symbol,
        setup_family=OPENING_BREAKOUT,
        created_at=created,
        planned_entry=entry,
        stop_price=stop,
        target_prices=(entry + risk, entry + (risk * 2)),
        source_setup_fingerprint=source_setup_fingerprint,
        source_level_kind="DAILY_BREAKOUT_WITH_OPENING_RANGE_RISK",
        source_evidence_ids=source_ids,
        observed_price=opening_high,
        setup_driver=setup_driver,
        catalyst_relationship_type=catalyst_relationship_type,
        catalyst_score_authority=catalyst_score_authority,
        catalyst_attribution_fingerprint=catalyst_attribution_fingerprint,
        early_close=early_close,
    )


def transition_intraday_plan(
    evidence: IntradayPlanEvidence,
    *,
    lifecycle_status: str,
    observed_at: datetime,
) -> IntradayPlanEvidence:
    """Advance lifecycle state without changing the persisted plan identity or levels."""

    validation = intraday_plan_validation_findings(evidence)
    if validation:
        raise ValueError("Cannot transition invalid intraday plan evidence: " + " | ".join(validation))
    normalized = str(lifecycle_status).strip().upper()
    if normalized not in ACTIVE_PLAN_STATES | TERMINAL_PLAN_STATES:
        raise ValueError("Unsupported intraday plan lifecycle transition.")
    if evidence.lifecycle_status in TERMINAL_PLAN_STATES and normalized != evidence.lifecycle_status:
        raise ValueError("Terminal intraday plan evidence is immutable.")
    allowed = ALLOWED_LIFECYCLE_TRANSITIONS.get(evidence.lifecycle_status, frozenset())
    if normalized not in allowed:
        raise ValueError(
            f"Invalid intraday plan lifecycle transition: "
            f"{evidence.lifecycle_status} -> {normalized}."
        )
    observed = _aware(observed_at)
    if observed < _aware_datetime(evidence.created_at):
        raise ValueError("Intraday plan observation predates plan creation.")
    if observed.astimezone(EASTERN_TZ).date().isoformat() != evidence.session_date:
        raise ValueError("Intraday plan observation crosses the session boundary.")
    valid_from = _aware_datetime(evidence.entry_valid_from)
    expires = _aware_datetime(evidence.entry_expires_at)
    forced_flat = _aware_datetime(evidence.forced_flat_at)
    if normalized in {TRIGGERED, MISSED_ENTRY} and not valid_from <= observed <= expires:
        raise ValueError("Entry-state transition is outside the persisted validity window.")
    if normalized == EXPIRED and observed < expires:
        raise ValueError("Intraday plan cannot expire before its persisted deadline.")
    if normalized in ACTIVE_PLAN_STATES and observed >= forced_flat:
        raise ValueError("Intraday plan cannot remain active at or after forced flat.")
    findings = [
        item
        for item in evidence.findings
        if item
        not in {
            "INTRADAY_ENTRY_MISSED_IMMUTABLY",
            "INTRADAY_ENTRY_EXPIRED",
            "INTRADAY_PLAN_INVALIDATED",
        }
    ]
    finding = {
        MISSED_ENTRY: "INTRADAY_ENTRY_MISSED_IMMUTABLY",
        EXPIRED: "INTRADAY_ENTRY_EXPIRED",
        INVALIDATED: "INTRADAY_PLAN_INVALIDATED",
    }.get(normalized)
    if finding:
        findings.append(finding)
    transitioned = replace(
        evidence,
        status=(
            EXECUTION_ELIGIBLE
            if normalized in ACTIVE_PLAN_STATES
            else EXECUTION_INELIGIBLE
        ),
        lifecycle_status=normalized,
        lifecycle_updated_at=observed.isoformat(),
        findings=tuple(dict.fromkeys(findings)),
        fingerprint="",
    )
    return _with_fingerprint(transitioned)


def intraday_plan_validation_findings(
    evidence: IntradayPlanEvidence,
) -> tuple[str, ...]:
    findings: list[str] = []
    if evidence.schema_version != INTRADAY_PLAN_SCHEMA_VERSION:
        findings.append("INTRADAY_PLAN_SCHEMA_UNSUPPORTED")
    if evidence.profile != INTRADAY_PLAN_PROFILE:
        findings.append("INTRADAY_PLAN_PROFILE_UNSUPPORTED")
    if evidence.horizon != INTRADAY_HORIZON:
        findings.append("INTRADAY_PLAN_HORIZON_UNSUPPORTED")
    if evidence.setup_family not in SUPPORTED_SETUP_FAMILIES:
        findings.append("INTRADAY_SETUP_FAMILY_UNSUPPORTED")
    if evidence.setup_driver not in {TECHNICAL_DRIVER, CATALYST_DRIVER}:
        findings.append("INTRADAY_SETUP_DRIVER_UNSUPPORTED")
    if evidence.setup_driver == CATALYST_DRIVER:
        if (
            evidence.catalyst_relationship_type not in SUPPORTED_CATALYST_RELATIONSHIPS
            or evidence.catalyst_score_authority != CATALYST_SCORE_SUPPORTED
        ):
            findings.append("CATALYST_DRIVEN_SETUP_ATTRIBUTION_UNSUPPORTED")
        if not _sha256(evidence.catalyst_attribution_fingerprint):
            findings.append("CATALYST_DRIVEN_SETUP_ATTRIBUTION_IDENTITY_MISSING")
    if not _sha256(evidence.source_setup_fingerprint):
        findings.append("INTRADAY_SOURCE_SETUP_FINGERPRINT_INVALID")
    if not _sha256(evidence.plan_id):
        findings.append("INTRADAY_PLAN_ID_INVALID")
    elif evidence.plan_id != expected_intraday_plan_id(evidence):
        findings.append("INTRADAY_PLAN_ID_CONTRADICTS_CONTENT")
    if not evidence.source_evidence_ids:
        findings.append("INTRADAY_SOURCE_EVIDENCE_IDS_MISSING")
    if not _positive_finite(evidence.planned_entry) or not _positive_finite(evidence.stop_price):
        findings.append("INTRADAY_PLAN_LEVELS_INVALID")
    elif float(evidence.stop_price) >= float(evidence.planned_entry):
        findings.append("INTRADAY_STOP_NOT_BELOW_ENTRY")
    if not evidence.target_prices or any(
        not _positive_finite(item) or float(item) <= float(evidence.planned_entry or 0)
        for item in evidence.target_prices
    ):
        findings.append("INTRADAY_TARGETS_INVALID")
    try:
        created = _aware_datetime(evidence.created_at)
        valid_from = _aware_datetime(evidence.entry_valid_from)
        expires = _aware_datetime(evidence.entry_expires_at)
        forced_flat = _aware_datetime(evidence.forced_flat_at)
        lifecycle_updated = _aware_datetime(evidence.lifecycle_updated_at)
    except ValueError:
        findings.append("INTRADAY_PLAN_TIMESTAMPS_INVALID")
    else:
        eastern_created = created.astimezone(EASTERN_TZ)
        session_open = datetime.combine(
            eastern_created.date(), REGULAR_SESSION_OPEN, tzinfo=EASTERN_TZ
        )
        if not (
            created <= valid_from <= expires < forced_flat
            and created.astimezone(EASTERN_TZ).date().isoformat() == evidence.session_date
            and all(
                item.astimezone(EASTERN_TZ).date().isoformat() == evidence.session_date
                for item in (valid_from, expires, forced_flat)
            )
            and created <= lifecycle_updated
            and lifecycle_updated.astimezone(EASTERN_TZ).date().isoformat()
            == evidence.session_date
        ):
            findings.append("INTRADAY_PLAN_TIMING_INVALID")
        if not session_open <= created < forced_flat:
            findings.append("INTRADAY_PLAN_CREATED_OUTSIDE_REGULAR_SESSION")
        if not is_market_open_day(eastern_created.date()):
            findings.append("INTRADAY_PLAN_SESSION_IS_NOT_MARKET_DAY")
    if evidence.lifecycle_status not in ACTIVE_PLAN_STATES | TERMINAL_PLAN_STATES:
        findings.append("INTRADAY_LIFECYCLE_STATUS_UNSUPPORTED")
    expected_status = (
        EXECUTION_ELIGIBLE
        if evidence.lifecycle_status in ACTIVE_PLAN_STATES
        and not tuple(item for item in evidence.findings if item not in {"INTRADAY_ENTRY_MISSED_IMMUTABLY", "INTRADAY_ENTRY_EXPIRED", "INTRADAY_PLAN_INVALIDATED"})
        else EXECUTION_INELIGIBLE
    )
    if evidence.status != expected_status:
        findings.append("INTRADAY_PLAN_AUTHORITY_CONTRADICTS_LIFECYCLE")
    if evidence.setup_family == RECLAIM and (
        not evidence.predecessor_plan_id
        or not evidence.predecessor_plan_fingerprint
        or not evidence.replacement_reason
    ):
        findings.append("RECLAIM_PREDECESSOR_REQUIRED")
    if evidence.predecessor_plan_id and not _sha256(evidence.predecessor_plan_id):
        findings.append("INTRADAY_PREDECESSOR_PLAN_ID_INVALID")
    if evidence.predecessor_plan_fingerprint and not _sha256(
        evidence.predecessor_plan_fingerprint
    ):
        findings.append("INTRADAY_PREDECESSOR_FINGERPRINT_INVALID")
    if evidence.replacement_reason and not evidence.predecessor_plan_id:
        findings.append("INTRADAY_REPLACEMENT_PREDECESSOR_REQUIRED")
    if evidence.fingerprint != intraday_plan_fingerprint(evidence):
        findings.append("INTRADAY_PLAN_FINGERPRINT_INVALID")
    return tuple(dict.fromkeys(findings))


def intraday_plan_decision_findings(
    evidence: IntradayPlanEvidence,
    *,
    decision_at: datetime,
) -> tuple[str, ...]:
    findings = list(intraday_plan_validation_findings(evidence))
    if findings:
        return tuple(findings)
    decision = _aware(decision_at)
    valid_from = _aware_datetime(evidence.entry_valid_from)
    expires = _aware_datetime(evidence.entry_expires_at)
    forced_flat = _aware_datetime(evidence.forced_flat_at)
    if decision.astimezone(EASTERN_TZ).date().isoformat() != evidence.session_date:
        findings.append("INTRADAY_DECISION_SESSION_MISMATCH")
    if not valid_from <= decision <= expires:
        findings.append("INTRADAY_DECISION_OUTSIDE_ENTRY_VALIDITY")
    if decision >= forced_flat:
        findings.append("INTRADAY_DECISION_AT_OR_AFTER_FORCED_FLAT")
    if evidence.lifecycle_status not in ACTIVE_PLAN_STATES:
        findings.append("INTRADAY_PLAN_NOT_ACTIVE")
    return tuple(dict.fromkeys(findings))


def intraday_plan_fingerprint(evidence: IntradayPlanEvidence) -> str:
    payload = asdict(replace(evidence, fingerprint=""))
    return _stable_hash("intraday-plan-record-v1", _canonical_json(payload))


def expected_intraday_plan_id(evidence: IntradayPlanEvidence) -> str:
    """Recompute immutable plan identity independently of lifecycle state."""

    core = {
        "schema_version": evidence.schema_version,
        "profile": evidence.profile,
        "horizon": evidence.horizon,
        "symbol": evidence.symbol,
        "session_date": evidence.session_date,
        "setup_family": evidence.setup_family,
        "setup_driver": evidence.setup_driver,
        "created_at": evidence.created_at,
        "entry_valid_from": evidence.entry_valid_from,
        "entry_expires_at": evidence.entry_expires_at,
        "forced_flat_at": evidence.forced_flat_at,
        "planned_entry": evidence.planned_entry,
        "stop_price": evidence.stop_price,
        "target_prices": evidence.target_prices,
        "source_setup_fingerprint": evidence.source_setup_fingerprint,
        "source_level_kind": evidence.source_level_kind,
        "source_evidence_ids": evidence.source_evidence_ids,
        "catalyst_relationship_type": evidence.catalyst_relationship_type,
        "catalyst_score_authority": evidence.catalyst_score_authority,
        "catalyst_attribution_fingerprint": evidence.catalyst_attribution_fingerprint,
        "predecessor_plan_id": evidence.predecessor_plan_id,
        "predecessor_plan_fingerprint": evidence.predecessor_plan_fingerprint,
        "replacement_reason": evidence.replacement_reason,
    }
    return _stable_hash("intraday-plan-v1", _canonical_json(core))


def unavailable_intraday_plan(
    *,
    symbol: str,
    finding: str,
    source_setup_fingerprint: str = "",
) -> IntradayPlanEvidence:
    evidence = IntradayPlanEvidence(
        symbol=str(symbol).strip().upper(),
        source_setup_fingerprint=source_setup_fingerprint,
        findings=(str(finding).strip() or "INTRADAY_PLAN_UNAVAILABLE",),
    )
    return _with_fingerprint(evidence)


def _plan_deadlines(
    created_at: datetime,
    setup_family: str,
    *,
    entry_valid_from: datetime | None,
    entry_expires_at: datetime | None,
    forced_flat_at: datetime | None,
    early_close: bool,
) -> tuple[datetime, datetime, datetime]:
    eastern = created_at.astimezone(EASTERN_TZ)
    entry_cutoff = EARLY_CLOSE_ENTRY_CUTOFF if early_close else REGULAR_ENTRY_CUTOFF
    flat_time = EARLY_CLOSE_FORCED_FLAT if early_close else REGULAR_FORCED_FLAT
    session_entry_cutoff = datetime.combine(eastern.date(), entry_cutoff, tzinfo=EASTERN_TZ)
    forced_flat = _aware(forced_flat_at) if forced_flat_at is not None else datetime.combine(
        eastern.date(), flat_time, tzinfo=EASTERN_TZ
    )
    if entry_valid_from is not None:
        valid_from = _aware(entry_valid_from)
    elif setup_family == OPENING_BREAKOUT:
        valid_from = max(
            created_at,
            datetime.combine(eastern.date(), OPENING_ENTRY_START, tzinfo=EASTERN_TZ),
        )
    else:
        valid_from = created_at
    if entry_expires_at is not None:
        expires = _aware(entry_expires_at)
    elif setup_family == OPENING_BREAKOUT:
        opening_cutoff = datetime.combine(
            eastern.date(),
            min(OPENING_ENTRY_CUTOFF, entry_cutoff),
            tzinfo=EASTERN_TZ,
        )
        expires = opening_cutoff
    else:
        lifetime = SETUP_LIFETIME_MINUTES.get(setup_family, 0)
        expires = min(valid_from + timedelta(minutes=lifetime), session_entry_cutoff)
    return valid_from, expires, forced_flat


def _initial_lifecycle_state(
    *,
    family: str,
    created_at: datetime,
    expires_at: datetime,
    observed_price: float | None,
    entry: float | None,
    stop: float | None,
) -> str:
    if created_at > expires_at:
        return EXPIRED
    if observed_price is not None and stop is not None and observed_price <= stop:
        return INVALIDATED
    if (
        family in {OPENING_BREAKOUT, CONTINUATION_BREAKOUT}
        and observed_price is not None
        and entry is not None
        and observed_price > entry
    ):
        return MISSED_ENTRY
    return PENDING_ENTRY


def _trigger_rule(family: str) -> str:
    return {
        OPENING_BREAKOUT: "PRICE_CROSSES_ABOVE_OPENING_BREAKOUT_LEVEL_BEFORE_EXPIRY",
        CONTINUATION_BREAKOUT: "PRICE_CROSSES_ABOVE_LATER_SESSION_RANGE_BEFORE_EXPIRY",
        PULLBACK: "PRICE_PULLS_BACK_TO_SUPPORT_THEN_CONFIRMS_BEFORE_EXPIRY",
        RECLAIM: "PRICE_TRADES_AT_OR_BELOW_PRIOR_TRIGGER_THEN_RECROSSES_BEFORE_EXPIRY",
    }.get(family, "")


def _stop_rule(family: str) -> str:
    return {
        OPENING_BREAKOUT: "HARD_STOP_AT_PERSISTED_OPENING_RANGE_LOW",
        CONTINUATION_BREAKOUT: "HARD_STOP_BELOW_PERSISTED_LATER_SESSION_RANGE",
        PULLBACK: "HARD_STOP_BELOW_PERSISTED_PULLBACK_STRUCTURE",
        RECLAIM: "HARD_STOP_BELOW_PERSISTED_RECLAIM_STRUCTURE",
    }.get(family, "")


def _target_rule(family: str) -> str:
    return {
        OPENING_BREAKOUT: "PERSISTED_OPENING_RANGE_R_MULTIPLE_TARGETS",
        CONTINUATION_BREAKOUT: "PERSISTED_CONTINUATION_R_MULTIPLE_TARGETS",
        PULLBACK: "PERSISTED_PULLBACK_STRUCTURE_TARGETS",
        RECLAIM: "PERSISTED_RECLAIM_STRUCTURE_TARGETS",
    }.get(family, "")


def _with_fingerprint(evidence: IntradayPlanEvidence) -> IntradayPlanEvidence:
    return replace(evidence, fingerprint=intraday_plan_fingerprint(evidence))


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Intraday plan timestamps must include a UTC offset.")
    return value


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Intraday plan timestamp is invalid.") from exc
    return _aware(parsed)


def _positive_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) > 0
    )


def _rounded_price(value: object) -> float | None:
    return round(float(value), 4) if _positive_finite(value) else None


def _bar_value(bar: object, name: str) -> float | None:
    value = getattr(bar, name, None)
    return float(value) if _positive_finite(value) else None


def _canonical_opening_bar(
    bar: object,
    *,
    symbol: str,
    session_date: str,
    eastern_timestamp: datetime,
) -> bool:
    if eastern_timestamp.second != 0 or eastern_timestamp.microsecond != 0:
        return False
    if str(getattr(bar, "symbol", "")).strip().upper() != symbol:
        return False
    if str(getattr(bar, "session_date", "")) != session_date:
        return False
    if str(getattr(bar, "source", "")) != SCHWAB_PRICE_HISTORY_SOURCE:
        return False
    if str(getattr(bar, "state", "")) not in CANONICAL_OUTCOME_STATES:
        return False
    values = {
        name: _bar_value(bar, name)
        for name in ("open", "high", "low", "close")
    }
    volume = getattr(bar, "volume", None)
    if any(value is None for value in values.values()):
        return False
    if (
        not isinstance(volume, (int, float))
        or isinstance(volume, bool)
        or not math.isfinite(float(volume))
        or float(volume) < 0
    ):
        return False
    return bool(
        float(values["high"]) >= max(float(values["open"]), float(values["close"]))
        and float(values["low"]) <= min(float(values["open"]), float(values["close"]))
        and float(values["low"]) <= float(values["high"])
    )


def _sha256(value: object) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _stable_hash(namespace: str, payload: str) -> str:
    return hashlib.sha256(f"{namespace}\x1f{payload}".encode("utf-8")).hexdigest()
