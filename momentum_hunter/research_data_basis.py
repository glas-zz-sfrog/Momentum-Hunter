"""Provider-neutral security identity and research price-basis contracts.

This module is research-only. It has no provider, network, account, broker,
order, scheduler, service, UI, scoring, or execution capability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from statistics import fmean
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
ENGINE_VERSION = "research-data-basis-v1"
TRANSFORMATION_VERSION = "split-adjustment-v1"
EXECUTION_AUTHORITY = "NONE"
RESEARCH_AUTHORITY = "RESEARCH_DATA_ADMISSION_ONLY"

ACTIVE = "ACTIVE"
DELISTED = "DELISTED"
ACQUIRED = "ACQUIRED"
RENAMED = "RENAMED"
INACTIVE = "INACTIVE"
UNKNOWN_SECURITY_STATE = "UNKNOWN"
SECURITY_STATES = frozenset(
    {ACTIVE, DELISTED, ACQUIRED, RENAMED, INACTIVE, UNKNOWN_SECURITY_STATE}
)

IDENTITY_VERIFIED = "VERIFIED"
IDENTITY_PARTIAL = "PARTIAL"
IDENTITY_UNRESOLVED = "UNRESOLVED"
IDENTITY_STATUSES = frozenset(
    {IDENTITY_VERIFIED, IDENTITY_PARTIAL, IDENTITY_UNRESOLVED}
)

RESOLVED = "RESOLVED"
AMBIGUOUS = "AMBIGUOUS"
UNRESOLVED = "UNRESOLVED"

FORWARD_SPLIT = "FORWARD_SPLIT"
REVERSE_SPLIT = "REVERSE_SPLIT"
SYMBOL_CHANGE = "SYMBOL_CHANGE"
MERGER = "MERGER"
SPINOFF = "SPINOFF"
SPECIAL_DISTRIBUTION = "SPECIAL_DISTRIBUTION"
OTHER_ACTION = "OTHER"
CORPORATE_ACTION_TYPES = frozenset(
    {
        FORWARD_SPLIT,
        REVERSE_SPLIT,
        SYMBOL_CHANGE,
        MERGER,
        SPINOFF,
        SPECIAL_DISTRIBUTION,
        OTHER_ACTION,
    }
)
TRANSFORMABLE_ACTION_TYPES = frozenset(
    {FORWARD_SPLIT, REVERSE_SPLIT, SYMBOL_CHANGE}
)

ACTION_VERIFIED = "VERIFIED"
ACTION_PROVISIONAL = "PROVISIONAL"
ACTION_UNVERIFIED = "UNVERIFIED"
ACTION_VERIFICATION_STATUSES = frozenset(
    {ACTION_VERIFIED, ACTION_PROVISIONAL, ACTION_UNVERIFIED}
)

RAW_PROVIDER = "RAW_PROVIDER"
SPLIT_ADJUSTED = "SPLIT_ADJUSTED"
TOTAL_RETURN_ADJUSTED = "TOTAL_RETURN_ADJUSTED"
UNKNOWN_PRICE_BASIS = "UNKNOWN"
PRICE_BASES = frozenset(
    {RAW_PROVIDER, SPLIT_ADJUSTED, TOTAL_RETURN_ADJUSTED, UNKNOWN_PRICE_BASIS}
)

BASIS_VERIFIED = "VERIFIED"
BASIS_ASSERTED = "ASSERTED"
BASIS_UNKNOWN = "UNKNOWN"
BASIS_VERIFICATION_STATUSES = frozenset(
    {BASIS_VERIFIED, BASIS_ASSERTED, BASIS_UNKNOWN}
)

SURVIVORSHIP_CONTROLLED = "CONTROLLED"
SURVIVORSHIP_PARTIAL = "PARTIAL"
SURVIVORSHIP_UNCONTROLLED = "UNCONTROLLED"
SURVIVORSHIP_UNKNOWN = "UNKNOWN"
SURVIVORSHIP_STATUSES = frozenset(
    {
        SURVIVORSHIP_CONTROLLED,
        SURVIVORSHIP_PARTIAL,
        SURVIVORSHIP_UNCONTROLLED,
        SURVIVORSHIP_UNKNOWN,
    }
)

POINT_IN_TIME = "POINT_IN_TIME"
CURRENT_ONLY = "CURRENT_ONLY"
EVIDENCE_DERIVED = "EVIDENCE_DERIVED"
UNKNOWN_MEMBERSHIP = "UNKNOWN"

SAFE_FOR_RAW_ANALYSIS = "SAFE_FOR_RAW_ANALYSIS"
SAFE_FOR_SPLIT_ADJUSTED_ANALYSIS = "SAFE_FOR_SPLIT_ADJUSTED_ANALYSIS"
DATA_BASIS_UNCERTAIN = "DATA_BASIS_UNCERTAIN"
CORPORATE_ACTION_UNRESOLVED = "CORPORATE_ACTION_UNRESOLVED"
SECURITY_IDENTITY_UNRESOLVED = "SECURITY_IDENTITY_UNRESOLVED"
SURVIVORSHIP_STATUS_UNCONTROLLED = "SURVIVORSHIP_STATUS_UNCONTROLLED"
ADMISSION_OUTCOMES = frozenset(
    {
        SAFE_FOR_RAW_ANALYSIS,
        SAFE_FOR_SPLIT_ADJUSTED_ANALYSIS,
        DATA_BASIS_UNCERTAIN,
        CORPORATE_ACTION_UNRESOLVED,
        SECURITY_IDENTITY_UNRESOLVED,
        SURVIVORSHIP_STATUS_UNCONTROLLED,
    }
)

CORPORATE_ACTION_FEATURE_FAMILY = "CORPORATE_ACTION"
SPECIALIST_ABSTENTION_CODE = DATA_BASIS_UNCERTAIN

_SHA256 = re.compile(r"[0-9A-Fa-f]{64}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,31}")
_MAX_JSON_BYTES = 128 * 1024 * 1024


class ResearchDataBasisError(ValueError):
    """Raised when identity or price-basis evidence is contradictory."""


@dataclass(frozen=True)
class SymbolAlias:
    symbol: str
    effective_from: str
    effective_to: str | None
    exchange: str | None
    source: str
    evidence_fingerprint: str


@dataclass(frozen=True)
class SecurityIdentity:
    schema_version: int
    security_id: str
    current_symbol: str
    aliases: tuple[SymbolAlias, ...]
    security_state: str
    issuer_id: str | None
    issuer_name: str | None
    identity_sources: tuple[str, ...]
    identity_status: str
    fingerprint: str = ""


@dataclass(frozen=True)
class SecurityResolution:
    status: str
    observed_symbol: str
    observed_on: str
    security_id: str | None
    alias: SymbolAlias | None
    findings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CorporateAction:
    schema_version: int
    action_id: str
    security_id: str
    action_type: str
    announcement_at: str | None
    effective_at: str
    ratio_numerator: int | None
    ratio_denominator: int | None
    old_symbol: str | None
    new_symbol: str | None
    source: str
    evidence_fingerprint: str
    verification_status: str
    fingerprint: str = ""


@dataclass(frozen=True)
class ResearchPriceBar:
    schema_version: int
    bar_id: str
    security_id: str
    symbol: str
    timestamp: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    source: str
    price_basis: str
    basis_verification: str
    evidence_fingerprint: str
    fingerprint: str = ""


@dataclass(frozen=True)
class OhlcvSnapshot:
    open: str
    high: str
    low: str
    close: str
    volume: str


@dataclass(frozen=True)
class PriceTransformationLineage:
    schema_version: int
    raw_bar_id: str
    raw_bar_fingerprint: str
    security_id: str
    security_identity_fingerprint: str
    original_symbol: str
    original_timestamp: str
    original_ohlcv: OhlcvSnapshot
    corporate_action_ids: tuple[str, ...]
    corporate_action_fingerprints: tuple[str, ...]
    cumulative_price_factor: str
    cumulative_volume_factor: str
    transformation_version: str
    target_basis: str
    transformed_ohlcv: OhlcvSnapshot
    transformed_evidence_fingerprint: str
    fingerprint: str = ""


@dataclass(frozen=True)
class SurvivorshipAssessment:
    status: str
    membership_basis: str
    inactive_security_coverage: str
    findings: tuple[str, ...]
    execution_authority: str = EXECUTION_AUTHORITY


@dataclass(frozen=True)
class ResearchBasisAdmission:
    status: str
    requested_basis: str
    observed_basis: str
    findings: tuple[str, ...]
    allowed_uses: tuple[str, ...]
    specialist_feature_family: str = CORPORATE_ACTION_FEATURE_FAMILY
    specialist_abstention_code: str = SPECIALIST_ABSTENTION_CODE
    authority: str = RESEARCH_AUTHORITY
    execution_authority: str = EXECUTION_AUTHORITY


def build_symbol_alias(
    *,
    symbol: str,
    effective_from: date | str,
    effective_to: date | str | None,
    exchange: str | None,
    source: str,
    evidence_fingerprint: str,
) -> SymbolAlias:
    start = _date_text(effective_from, "Alias effective-from")
    end = _date_text(effective_to, "Alias effective-to") if effective_to else None
    if end is not None and end < start:
        raise ResearchDataBasisError("Alias effective-to preceded effective-from.")
    return SymbolAlias(
        symbol=_symbol(symbol),
        effective_from=start,
        effective_to=end,
        exchange=_optional_identifier(exchange, "Alias exchange"),
        source=_identifier(source, "Alias source"),
        evidence_fingerprint=_sha256(evidence_fingerprint, "Alias evidence fingerprint"),
    )


def build_security_identity(
    *,
    security_id: str,
    current_symbol: str,
    aliases: Sequence[SymbolAlias],
    security_state: str,
    issuer_id: str | None,
    issuer_name: str | None,
    identity_sources: Sequence[str],
    identity_status: str,
) -> SecurityIdentity:
    normalized_aliases = tuple(
        sorted(aliases, key=lambda item: (item.effective_from, item.symbol))
    )
    if not normalized_aliases:
        raise ResearchDataBasisError("Security identity requires symbol history.")
    _validate_alias_timeline(normalized_aliases)
    state = str(security_state).strip().upper()
    if state not in SECURITY_STATES:
        raise ResearchDataBasisError("Security state was unsupported.")
    status = str(identity_status).strip().upper()
    if status not in IDENTITY_STATUSES:
        raise ResearchDataBasisError("Identity status was unsupported.")
    current = _symbol(current_symbol)
    if state == ACTIVE:
        open_aliases = [item for item in normalized_aliases if item.effective_to is None]
        if len(open_aliases) != 1 or open_aliases[0].symbol != current:
            raise ResearchDataBasisError(
                "An active security requires one open alias matching current symbol."
            )
    identity = SecurityIdentity(
        schema_version=SCHEMA_VERSION,
        security_id=_identifier(security_id, "Security identity"),
        current_symbol=current,
        aliases=normalized_aliases,
        security_state=state,
        issuer_id=_optional_identifier(issuer_id, "Issuer identity"),
        issuer_name=_optional_text(issuer_name, "Issuer name"),
        identity_sources=tuple(
            sorted({_identifier(item, "Identity source") for item in identity_sources})
        ),
        identity_status=status,
    )
    if not identity.identity_sources:
        raise ResearchDataBasisError("Security identity requires source lineage.")
    return _with_security_fingerprint(identity)


def validate_security_identity(identity: SecurityIdentity) -> None:
    expected = security_identity_fingerprint(identity)
    if identity.fingerprint != expected:
        raise ResearchDataBasisError("Security identity fingerprint did not match.")
    rebuilt = build_security_identity(
        security_id=identity.security_id,
        current_symbol=identity.current_symbol,
        aliases=identity.aliases,
        security_state=identity.security_state,
        issuer_id=identity.issuer_id,
        issuer_name=identity.issuer_name,
        identity_sources=identity.identity_sources,
        identity_status=identity.identity_status,
    )
    if rebuilt != identity:
        raise ResearchDataBasisError("Security identity was not canonical.")


def security_identity_fingerprint(identity: SecurityIdentity) -> str:
    return _fingerprint(asdict(replace(identity, fingerprint="")))


def resolve_security_identity(
    identities: Sequence[SecurityIdentity],
    *,
    symbol: str,
    observed_on: date | str,
    exchange: str | None = None,
) -> SecurityResolution:
    observed = _date_text(observed_on, "Observation date")
    normalized_symbol = _symbol(symbol)
    normalized_exchange = _optional_identifier(exchange, "Observation exchange")
    matches: list[tuple[SecurityIdentity, SymbolAlias]] = []
    seen_ids: set[str] = set()
    for identity in identities:
        validate_security_identity(identity)
        if identity.security_id in seen_ids:
            raise ResearchDataBasisError("Security registry contained a duplicate identity.")
        seen_ids.add(identity.security_id)
        for alias in identity.aliases:
            if alias.symbol != normalized_symbol:
                continue
            if normalized_exchange and alias.exchange not in (None, normalized_exchange):
                continue
            if alias.effective_from <= observed and (
                alias.effective_to is None or observed <= alias.effective_to
            ):
                matches.append((identity, alias))
    if not matches:
        return SecurityResolution(
            status=UNRESOLVED,
            observed_symbol=normalized_symbol,
            observed_on=observed,
            security_id=None,
            alias=None,
            findings=("SECURITY_IDENTITY_UNRESOLVED",),
        )
    if len(matches) > 1:
        return SecurityResolution(
            status=AMBIGUOUS,
            observed_symbol=normalized_symbol,
            observed_on=observed,
            security_id=None,
            alias=None,
            findings=("SYMBOL_REUSED_OR_ALIAS_OVERLAP",),
        )
    identity, alias = matches[0]
    return SecurityResolution(
        status=RESOLVED,
        observed_symbol=normalized_symbol,
        observed_on=observed,
        security_id=identity.security_id,
        alias=alias,
    )


def load_security_identity_json(text: str) -> SecurityIdentity:
    payload = _loads_no_duplicate_keys(text)
    if not isinstance(payload, Mapping):
        raise ResearchDataBasisError("Serialized security identity was not an object.")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ResearchDataBasisError("Serialized security identity schema was unsupported.")
    raw_aliases = payload.get("aliases")
    if not isinstance(raw_aliases, list):
        raise ResearchDataBasisError("Serialized security aliases were missing.")
    aliases = tuple(
        build_symbol_alias(
            symbol=str(item.get("symbol") or ""),
            effective_from=str(item.get("effective_from") or ""),
            effective_to=(
                str(item["effective_to"]) if item.get("effective_to") is not None else None
            ),
            exchange=(str(item["exchange"]) if item.get("exchange") else None),
            source=str(item.get("source") or ""),
            evidence_fingerprint=str(item.get("evidence_fingerprint") or ""),
        )
        for item in raw_aliases
        if isinstance(item, Mapping)
    )
    if len(aliases) != len(raw_aliases):
        raise ResearchDataBasisError("Serialized security alias was malformed.")
    identity = build_security_identity(
        security_id=str(payload.get("security_id") or ""),
        current_symbol=str(payload.get("current_symbol") or ""),
        aliases=aliases,
        security_state=str(payload.get("security_state") or ""),
        issuer_id=(str(payload["issuer_id"]) if payload.get("issuer_id") else None),
        issuer_name=(str(payload["issuer_name"]) if payload.get("issuer_name") else None),
        identity_sources=tuple(payload.get("identity_sources") or ()),
        identity_status=str(payload.get("identity_status") or ""),
    )
    supplied = _sha256(
        payload.get("fingerprint"), "Serialized security identity fingerprint"
    )
    if supplied != identity.fingerprint:
        raise ResearchDataBasisError("Serialized security identity was tampered.")
    return identity


def build_corporate_action(
    *,
    action_id: str,
    security_id: str,
    action_type: str,
    announcement_at: datetime | str | None,
    effective_at: datetime | str,
    ratio_numerator: int | None,
    ratio_denominator: int | None,
    old_symbol: str | None,
    new_symbol: str | None,
    source: str,
    evidence_fingerprint: str,
    verification_status: str,
) -> CorporateAction:
    kind = str(action_type).strip().upper()
    if kind not in CORPORATE_ACTION_TYPES:
        raise ResearchDataBasisError("Corporate-action type was unsupported.")
    verification = str(verification_status).strip().upper()
    if verification not in ACTION_VERIFICATION_STATUSES:
        raise ResearchDataBasisError("Corporate-action verification was unsupported.")
    effective = _timestamp_text(effective_at, "Action effective timestamp")
    announcement = (
        _timestamp_text(announcement_at, "Action announcement timestamp")
        if announcement_at is not None
        else None
    )
    if announcement is not None and announcement > effective:
        raise ResearchDataBasisError("Action announcement followed its effective time.")
    numerator = _optional_positive_int(ratio_numerator, "Split numerator")
    denominator = _optional_positive_int(ratio_denominator, "Split denominator")
    old = _optional_symbol(old_symbol)
    new = _optional_symbol(new_symbol)
    if kind in (FORWARD_SPLIT, REVERSE_SPLIT):
        if numerator is None or denominator is None:
            raise ResearchDataBasisError("Split action requires a positive ratio.")
        if kind == FORWARD_SPLIT and numerator <= denominator:
            raise ResearchDataBasisError("Forward split ratio did not increase shares.")
        if kind == REVERSE_SPLIT and numerator >= denominator:
            raise ResearchDataBasisError("Reverse split ratio did not reduce shares.")
        if old is not None or new is not None:
            raise ResearchDataBasisError("Split action cannot invent a symbol change.")
    elif kind == SYMBOL_CHANGE:
        if numerator is not None or denominator is not None:
            raise ResearchDataBasisError("Symbol change cannot carry a split ratio.")
        if old is None or new is None or old == new:
            raise ResearchDataBasisError("Symbol change requires distinct old/new symbols.")
    elif numerator is not None or denominator is not None:
        raise ResearchDataBasisError(
            "Unsupported action semantics cannot carry transformation parameters."
        )
    action = CorporateAction(
        schema_version=SCHEMA_VERSION,
        action_id=_identifier(action_id, "Corporate-action identity"),
        security_id=_identifier(security_id, "Security identity"),
        action_type=kind,
        announcement_at=announcement,
        effective_at=effective,
        ratio_numerator=numerator,
        ratio_denominator=denominator,
        old_symbol=old,
        new_symbol=new,
        source=_identifier(source, "Corporate-action source"),
        evidence_fingerprint=_sha256(
            evidence_fingerprint, "Corporate-action evidence fingerprint"
        ),
        verification_status=verification,
    )
    return _with_action_fingerprint(action)


def validate_corporate_action(action: CorporateAction) -> None:
    expected = corporate_action_fingerprint(action)
    if action.fingerprint != expected:
        raise ResearchDataBasisError("Corporate-action fingerprint did not match.")
    rebuilt = build_corporate_action(
        action_id=action.action_id,
        security_id=action.security_id,
        action_type=action.action_type,
        announcement_at=action.announcement_at,
        effective_at=action.effective_at,
        ratio_numerator=action.ratio_numerator,
        ratio_denominator=action.ratio_denominator,
        old_symbol=action.old_symbol,
        new_symbol=action.new_symbol,
        source=action.source,
        evidence_fingerprint=action.evidence_fingerprint,
        verification_status=action.verification_status,
    )
    if rebuilt != action:
        raise ResearchDataBasisError("Corporate action was not canonical.")


def corporate_action_fingerprint(action: CorporateAction) -> str:
    return _fingerprint(asdict(replace(action, fingerprint="")))


def build_research_price_bar(
    *,
    bar_id: str,
    security_id: str,
    symbol: str,
    timestamp: datetime | str,
    open_value: Decimal | int | float | str,
    high: Decimal | int | float | str,
    low: Decimal | int | float | str,
    close: Decimal | int | float | str,
    volume: Decimal | int | float | str,
    source: str,
    price_basis: str,
    basis_verification: str,
    evidence_fingerprint: str,
) -> ResearchPriceBar:
    values = {
        "open": _positive_decimal(open_value, "Open"),
        "high": _positive_decimal(high, "High"),
        "low": _positive_decimal(low, "Low"),
        "close": _positive_decimal(close, "Close"),
    }
    volume_value = _nonnegative_decimal(volume, "Volume")
    if values["high"] < max(values.values()):
        raise ResearchDataBasisError("Price bar high contradicted OHLC values.")
    if values["low"] > min(values.values()):
        raise ResearchDataBasisError("Price bar low contradicted OHLC values.")
    basis = str(price_basis).strip().upper()
    verification = str(basis_verification).strip().upper()
    if basis not in PRICE_BASES:
        raise ResearchDataBasisError("Price basis was unsupported.")
    if verification not in BASIS_VERIFICATION_STATUSES:
        raise ResearchDataBasisError("Basis verification was unsupported.")
    if basis == UNKNOWN_PRICE_BASIS and verification == BASIS_VERIFIED:
        raise ResearchDataBasisError("Unknown price basis cannot be verified.")
    bar = ResearchPriceBar(
        schema_version=SCHEMA_VERSION,
        bar_id=_identifier(bar_id, "Bar identity"),
        security_id=_identifier(security_id, "Security identity"),
        symbol=_symbol(symbol),
        timestamp=_timestamp_text(timestamp, "Bar timestamp"),
        open=_decimal_text(values["open"]),
        high=_decimal_text(values["high"]),
        low=_decimal_text(values["low"]),
        close=_decimal_text(values["close"]),
        volume=_decimal_text(volume_value),
        source=_identifier(source, "Bar source"),
        price_basis=basis,
        basis_verification=verification,
        evidence_fingerprint=_sha256(evidence_fingerprint, "Bar evidence fingerprint"),
    )
    return _with_bar_fingerprint(bar)


def validate_research_price_bar(bar: ResearchPriceBar) -> None:
    if bar.fingerprint != research_price_bar_fingerprint(bar):
        raise ResearchDataBasisError("Research price bar fingerprint did not match.")
    rebuilt = build_research_price_bar(
        bar_id=bar.bar_id,
        security_id=bar.security_id,
        symbol=bar.symbol,
        timestamp=bar.timestamp,
        open_value=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
        source=bar.source,
        price_basis=bar.price_basis,
        basis_verification=bar.basis_verification,
        evidence_fingerprint=bar.evidence_fingerprint,
    )
    if rebuilt != bar:
        raise ResearchDataBasisError("Research price bar was not canonical.")


def research_price_bar_fingerprint(bar: ResearchPriceBar) -> str:
    return _fingerprint(asdict(replace(bar, fingerprint="")))


def transform_split_adjusted_bar(
    raw_bar: ResearchPriceBar,
    *,
    identity: SecurityIdentity,
    actions: Sequence[CorporateAction],
    target_as_of: datetime | str,
) -> PriceTransformationLineage:
    validate_research_price_bar(raw_bar)
    validate_security_identity(identity)
    if raw_bar.price_basis != RAW_PROVIDER or raw_bar.basis_verification != BASIS_VERIFIED:
        raise ResearchDataBasisError(
            "Split transformation requires verified raw provider evidence."
        )
    if raw_bar.security_id != identity.security_id:
        raise ResearchDataBasisError("Raw bar used the wrong security identity.")
    resolution = resolve_security_identity(
        (identity,), symbol=raw_bar.symbol, observed_on=raw_bar.timestamp[:10]
    )
    if resolution.status != RESOLVED:
        raise ResearchDataBasisError("Raw bar symbol was not valid at its timestamp.")
    raw_time = _parse_timestamp(raw_bar.timestamp, "Bar timestamp")
    target_time = _parse_timestamp(target_as_of, "Transformation target")
    if target_time <= raw_time:
        raise ResearchDataBasisError("Transformation target must follow the raw bar.")
    action_ids: set[str] = set()
    price_factor = Decimal("1")
    volume_factor = Decimal("1")
    current_symbol = raw_bar.symbol
    ordered = sorted(actions, key=lambda item: (item.effective_at, item.action_id))
    for action in ordered:
        validate_corporate_action(action)
        if action.action_id in action_ids:
            raise ResearchDataBasisError("Corporate action was applied twice.")
        action_ids.add(action.action_id)
        if action.security_id != raw_bar.security_id:
            raise ResearchDataBasisError("Corporate action belonged to another security.")
        action_time = _parse_timestamp(action.effective_at, "Action effective timestamp")
        if not (raw_time < action_time <= target_time):
            raise ResearchDataBasisError("Corporate action was outside the valid range.")
        if action.verification_status != ACTION_VERIFIED:
            raise ResearchDataBasisError("Unverified corporate action cannot transform data.")
        if action.action_type not in TRANSFORMABLE_ACTION_TYPES:
            raise ResearchDataBasisError(
                "Unsupported corporate action has no transformation semantics."
            )
        if action.action_type in (FORWARD_SPLIT, REVERSE_SPLIT):
            assert action.ratio_numerator is not None
            assert action.ratio_denominator is not None
            price_factor *= Decimal(action.ratio_denominator) / Decimal(
                action.ratio_numerator
            )
            volume_factor *= Decimal(action.ratio_numerator) / Decimal(
                action.ratio_denominator
            )
        elif action.action_type == SYMBOL_CHANGE:
            if action.old_symbol != current_symbol:
                raise ResearchDataBasisError(
                    "Symbol-change action did not continue the observed alias chain."
                )
            assert action.new_symbol is not None
            transition_date = action_time.date().isoformat()
            target_resolution = resolve_security_identity(
                (identity,), symbol=action.new_symbol, observed_on=transition_date
            )
            if (
                target_resolution.status != RESOLVED
                or target_resolution.alias is None
                or target_resolution.alias.effective_from != transition_date
            ):
                raise ResearchDataBasisError(
                    "Symbol-change target did not match the identity transition."
                )
            current_symbol = action.new_symbol
    target_resolution = resolve_security_identity(
        (identity,), symbol=current_symbol, observed_on=target_time.date()
    )
    if target_resolution.status != RESOLVED:
        raise ResearchDataBasisError(
            "Corporate-action chain did not reach the target identity state."
        )
    original = _bar_ohlcv(raw_bar)
    transformed = OhlcvSnapshot(
        open=_decimal_text(Decimal(raw_bar.open) * price_factor),
        high=_decimal_text(Decimal(raw_bar.high) * price_factor),
        low=_decimal_text(Decimal(raw_bar.low) * price_factor),
        close=_decimal_text(Decimal(raw_bar.close) * price_factor),
        volume=_decimal_text(Decimal(raw_bar.volume) * volume_factor),
    )
    transformed_evidence = _fingerprint(
        {
            "rawBarFingerprint": raw_bar.fingerprint,
            "actions": [item.fingerprint for item in ordered],
            "priceFactor": _decimal_text(price_factor),
            "volumeFactor": _decimal_text(volume_factor),
            "transformationVersion": TRANSFORMATION_VERSION,
            "transformed": asdict(transformed),
        }
    )
    lineage = PriceTransformationLineage(
        schema_version=SCHEMA_VERSION,
        raw_bar_id=raw_bar.bar_id,
        raw_bar_fingerprint=raw_bar.fingerprint,
        security_id=raw_bar.security_id,
        security_identity_fingerprint=identity.fingerprint,
        original_symbol=raw_bar.symbol,
        original_timestamp=raw_bar.timestamp,
        original_ohlcv=original,
        corporate_action_ids=tuple(item.action_id for item in ordered),
        corporate_action_fingerprints=tuple(item.fingerprint for item in ordered),
        cumulative_price_factor=_decimal_text(price_factor),
        cumulative_volume_factor=_decimal_text(volume_factor),
        transformation_version=TRANSFORMATION_VERSION,
        target_basis=SPLIT_ADJUSTED,
        transformed_ohlcv=transformed,
        transformed_evidence_fingerprint=transformed_evidence,
    )
    return replace(lineage, fingerprint=transformation_lineage_fingerprint(lineage))


def validate_transformation_lineage(
    lineage: PriceTransformationLineage,
    *,
    raw_bar: ResearchPriceBar,
    identity: SecurityIdentity,
    actions: Sequence[CorporateAction],
    target_as_of: datetime | str,
) -> None:
    if lineage.fingerprint != transformation_lineage_fingerprint(lineage):
        raise ResearchDataBasisError("Transformation lineage fingerprint did not match.")
    if lineage.raw_bar_fingerprint != raw_bar.fingerprint:
        raise ResearchDataBasisError("Transformation lineage used another raw bar.")
    validate_security_identity(identity)
    if lineage.security_identity_fingerprint != identity.fingerprint:
        raise ResearchDataBasisError("Transformation lineage used another security identity.")
    by_id = {item.action_id: item for item in actions}
    if len(by_id) != len(actions):
        raise ResearchDataBasisError("Transformation action list contained duplicates.")
    selected: list[CorporateAction] = []
    for action_id, action_fingerprint in zip(
        lineage.corporate_action_ids, lineage.corporate_action_fingerprints
    ):
        action = by_id.get(action_id)
        if action is None or action.fingerprint != action_fingerprint:
            raise ResearchDataBasisError("Transformation action lineage mismatched.")
        selected.append(action)
    expected = transform_split_adjusted_bar(
        raw_bar, identity=identity, actions=selected, target_as_of=target_as_of
    )
    comparable_expected = replace(expected, fingerprint="")
    comparable_actual = replace(lineage, fingerprint="")
    if comparable_expected != comparable_actual:
        raise ResearchDataBasisError("Raw/transformed lineage did not reconcile.")


def transformation_lineage_fingerprint(lineage: PriceTransformationLineage) -> str:
    return _fingerprint(asdict(replace(lineage, fingerprint="")))


def assess_survivorship_bias(
    *,
    membership_basis: str,
    inactive_security_coverage: str,
    declared_status: str | None = None,
) -> SurvivorshipAssessment:
    membership = str(membership_basis).strip().upper()
    coverage = str(inactive_security_coverage).strip().upper()
    if membership not in {POINT_IN_TIME, CURRENT_ONLY, EVIDENCE_DERIVED, UNKNOWN_MEMBERSHIP}:
        raise ResearchDataBasisError("Universe membership basis was unsupported.")
    if coverage not in {"COMPLETE", "PARTIAL", "NONE", "UNKNOWN"}:
        raise ResearchDataBasisError("Inactive-security coverage was unsupported.")
    findings: list[str] = []
    if membership == POINT_IN_TIME and coverage == "COMPLETE":
        status = SURVIVORSHIP_CONTROLLED
    elif membership == POINT_IN_TIME or coverage == "PARTIAL":
        status = SURVIVORSHIP_PARTIAL
        findings.append("SURVIVORSHIP_CONTROL_PARTIAL")
    elif membership in {CURRENT_ONLY, EVIDENCE_DERIVED} and coverage in {"NONE", "UNKNOWN"}:
        status = SURVIVORSHIP_UNCONTROLLED
        findings.append("CURRENT_OR_EVIDENCE_DERIVED_UNIVERSE")
    else:
        status = SURVIVORSHIP_UNKNOWN
        findings.append("SURVIVORSHIP_STATUS_UNKNOWN")
    if declared_status is not None:
        declared = str(declared_status).strip().upper()
        if declared not in SURVIVORSHIP_STATUSES:
            raise ResearchDataBasisError("Declared survivorship status was unsupported.")
        if declared != status:
            findings.append("FALSE_SURVIVORSHIP_ASSERTION")
    return SurvivorshipAssessment(
        status=status,
        membership_basis=membership,
        inactive_security_coverage=coverage,
        findings=tuple(findings),
    )


def assess_research_price_basis(
    *,
    requested_basis: str,
    observed_basis: str,
    basis_verification: str,
    identity_status: str,
    corporate_action_status: str,
    applicable_action_count: int,
    transformation_lineage_valid: bool,
    survivorship_status: str,
    require_survivorship_control: bool,
) -> ResearchBasisAdmission:
    requested = str(requested_basis).strip().upper()
    observed = str(observed_basis).strip().upper()
    verification = str(basis_verification).strip().upper()
    identity = str(identity_status).strip().upper()
    action_status = str(corporate_action_status).strip().upper()
    survivorship = str(survivorship_status).strip().upper()
    if requested not in {RAW_PROVIDER, SPLIT_ADJUSTED}:
        raise ResearchDataBasisError("Requested analysis basis was unsupported.")
    if observed not in PRICE_BASES or verification not in BASIS_VERIFICATION_STATUSES:
        raise ResearchDataBasisError("Observed basis evidence was unsupported.")
    if identity not in IDENTITY_STATUSES:
        raise ResearchDataBasisError("Identity status was unsupported.")
    if action_status not in {RESOLVED, UNRESOLVED}:
        raise ResearchDataBasisError("Corporate-action status was unsupported.")
    if survivorship not in SURVIVORSHIP_STATUSES:
        raise ResearchDataBasisError("Survivorship status was unsupported.")
    if not isinstance(applicable_action_count, int) or isinstance(
        applicable_action_count, bool
    ) or applicable_action_count < 0:
        raise ResearchDataBasisError("Applicable action count was invalid.")
    findings: list[str] = []
    if identity != IDENTITY_VERIFIED:
        findings.append(SECURITY_IDENTITY_UNRESOLVED)
    if observed == UNKNOWN_PRICE_BASIS or verification != BASIS_VERIFIED:
        findings.append(DATA_BASIS_UNCERTAIN)
    if action_status != RESOLVED:
        findings.append(CORPORATE_ACTION_UNRESOLVED)
    if require_survivorship_control and survivorship != SURVIVORSHIP_CONTROLLED:
        findings.append(SURVIVORSHIP_STATUS_UNCONTROLLED)
    if not findings:
        if requested == RAW_PROVIDER and observed == RAW_PROVIDER:
            return ResearchBasisAdmission(
                status=SAFE_FOR_RAW_ANALYSIS,
                requested_basis=requested,
                observed_basis=observed,
                findings=(),
                allowed_uses=("RAW_PROVIDER_EVIDENCE_INSPECTION",),
            )
        split_safe = observed == SPLIT_ADJUSTED and transformation_lineage_valid
        no_adjustment_needed = observed == RAW_PROVIDER and applicable_action_count == 0
        if requested == SPLIT_ADJUSTED and (split_safe or no_adjustment_needed):
            return ResearchBasisAdmission(
                status=SAFE_FOR_SPLIT_ADJUSTED_ANALYSIS,
                requested_basis=requested,
                observed_basis=observed,
                findings=(),
                allowed_uses=("CORPORATE_ACTION_SAFE_TECHNICAL_RESEARCH",),
            )
        findings.append(DATA_BASIS_UNCERTAIN)
    priority = (
        SECURITY_IDENTITY_UNRESOLVED,
        DATA_BASIS_UNCERTAIN,
        CORPORATE_ACTION_UNRESOLVED,
        SURVIVORSHIP_STATUS_UNCONTROLLED,
    )
    status = next(item for item in priority if item in findings)
    return ResearchBasisAdmission(
        status=status,
        requested_basis=requested,
        observed_basis=observed,
        findings=tuple(dict.fromkeys(findings)),
        allowed_uses=(),
    )


def technical_basis_diagnostics(bars: Sequence[ResearchPriceBar]) -> dict[str, Any]:
    if len(bars) < 5:
        raise ResearchDataBasisError("Technical-basis diagnostic requires five bars.")
    for bar in bars:
        validate_research_price_bar(bar)
    ordered = sorted(bars, key=lambda item: item.timestamp)
    closes = [float(item.close) for item in ordered]
    highs = [float(item.high) for item in ordered]
    lows = [float(item.low) for item in ordered]
    opens = [float(item.open) for item in ordered]
    true_ranges: list[float] = []
    gaps: list[float] = []
    for index, item in enumerate(ordered):
        if index == 0:
            true_ranges.append(float(item.high) - float(item.low))
            continue
        previous_close = closes[index - 1]
        true_ranges.append(
            max(
                float(item.high) - float(item.low),
                abs(float(item.high) - previous_close),
                abs(float(item.low) - previous_close),
            )
        )
        gaps.append(abs(opens[index] - previous_close))
    entry = closes[0]
    normalized = tuple(round(value / entry, 8) for value in closes)
    left, head, right = closes[1], closes[2], closes[3]
    return {
        "periodReturn": round(closes[-1] / closes[0] - 1.0, 8),
        "averageTrueRange": round(fmean(true_ranges), 8),
        "movingAverage": round(fmean(closes), 8),
        "largestGap": round(max(gaps), 8),
        "support": round(min(lows), 8),
        "resistance": round(max(highs), 8),
        "headShouldersGeometry": {
            "leftShoulderToHead": round(abs(head - left) / head, 8),
            "rightShoulderToHead": round(abs(head - right) / head, 8),
            "shoulderAsymmetry": round(abs(left - right) / max(left, right), 8),
        },
        "breakoutLevel": round(max(highs[:-1]), 8),
        "mfe": round(max(highs) / entry - 1.0, 8),
        "mae": round(min(lows) / entry - 1.0, 8),
        "analogSignature": normalized,
    }


def compare_technical_basis(
    raw_bars: Sequence[ResearchPriceBar],
    adjusted_bars: Sequence[ResearchPriceBar],
) -> dict[str, Any]:
    if len(raw_bars) != len(adjusted_bars):
        raise ResearchDataBasisError("Basis comparison requires aligned bar counts.")
    if any(
        raw.security_id != adjusted.security_id
        or raw.timestamp != adjusted.timestamp
        for raw, adjusted in zip(raw_bars, adjusted_bars)
    ):
        raise ResearchDataBasisError("Basis comparison required aligned identities and times.")
    raw = technical_basis_diagnostics(raw_bars)
    adjusted = technical_basis_diagnostics(adjusted_bars)
    return {
        "raw": raw,
        "adjusted": adjusted,
        "contaminated": {
            "returns": raw["periodReturn"] != adjusted["periodReturn"],
            "atr": raw["averageTrueRange"] != adjusted["averageTrueRange"],
            "movingAverage": raw["movingAverage"] != adjusted["movingAverage"],
            "gaps": raw["largestGap"] != adjusted["largestGap"],
            "supportResistance": (
                raw["support"] != adjusted["support"]
                or raw["resistance"] != adjusted["resistance"]
            ),
            "headAndShoulders": (
                raw["headShouldersGeometry"] != adjusted["headShouldersGeometry"]
            ),
            "breakout": raw["breakoutLevel"] != adjusted["breakoutLevel"],
            "mfeMae": raw["mfe"] != adjusted["mfe"] or raw["mae"] != adjusted["mae"],
            "historicalAnalog": raw["analogSignature"] != adjusted["analogSignature"],
        },
    }


def build_dataset_compatibility_report(
    inventory: Mapping[str, Any],
    *,
    as_of: datetime | str,
) -> dict[str, Any]:
    _validate_inventory(inventory)
    datasets: list[dict[str, Any]] = []
    for item in inventory["datasets"]:
        price_basis = _compatibility_price_basis(str(item.get("priceBasis") or ""))
        security_identity = bool(item.get("stableSecurityIdentity"))
        action_lineage = bool(item.get("corporateActionLineage"))
        dataset_id = str(item["datasetId"])
        if dataset_id == "successorSetupProspective":
            safe_for = ["PROSPECTIVE_SETUP_EVIDENCE_ONLY"]
        elif dataset_id == "candidateOutcomeHistory":
            safe_for = ["POINT_IN_TIME_CANDIDATE_EVIDENCE_INSPECTION_ONLY"]
        else:
            safe_for = ["SOURCE_EVIDENCE_INSPECTION_ONLY"]
        datasets.append(
            {
                "datasetId": dataset_id,
                "authority": item.get("authority"),
                "recordCount": item.get("recordCount", 0),
                "symbolCount": item.get("symbolCount", 0),
                "dateRange": {
                    "first": item.get("firstTimestamp") or item.get("firstDate"),
                    "last": item.get("lastTimestamp") or item.get("lastDate"),
                },
                "stableSecurityIdentity": security_identity,
                "historicalAliases": False,
                "delistedSecurityCoverage": False,
                "pointInTimeMembership": False,
                "priceBasis": price_basis,
                "priceBasisVerified": False,
                "corporateActionMetadata": action_lineage,
                "survivorshipBiasStatus": SURVIVORSHIP_UNCONTROLLED,
                "safeFor": safe_for,
                "unsafeFor": [
                    "CORPORATE_ACTION_SENSITIVE_RETURNS",
                    "CROSS_ACTION_TECHNICAL_LEVELS",
                    "SURVIVORSHIP_SAFE_STATISTICS",
                    "HISTORICAL_ANALOG_MODELING",
                ],
                "admissionStatus": (
                    SECURITY_IDENTITY_UNRESOLVED
                    if not security_identity
                    else DATA_BASIS_UNCERTAIN
                ),
            }
        )
    report: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "engineVersion": ENGINE_VERSION,
        "task": "ARGUS-RESEARCH-DATA-002",
        "asOf": _timestamp_text(as_of, "Compatibility as-of"),
        "sourceInventoryFingerprint": inventory["inventoryFingerprint"],
        "classification": "IDENTITY_AND_PRICE_BASIS_FOUNDATION_DEFINED_GAPS_REMAIN",
        "authority": RESEARCH_AUTHORITY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "providerSelection": "NOT_PERFORMED",
        "pointInTimeUniverseCapability": "INSUFFICIENT",
        "survivorshipBiasStatus": SURVIVORSHIP_UNCONTROLLED,
        "datasets": datasets,
        "gaps": [
            _compatibility_gap(
                "DURABLE_SECURITY_IDENTITY",
                "Stable issuer/security ID with point-in-time aliases and inactive states.",
                "No inspected dataset contains durable identity or alias history.",
                "Historical records cannot prove economic-security continuity.",
                prospective=False,
                provider_maybe=True,
            ),
            _compatibility_gap(
                "CORPORATE_ACTION_EVENT_CHAIN",
                "Verified split/symbol-change events with effective time, ratio, and source fingerprint.",
                "No inspected dataset contains event-level action lineage.",
                "Returns, ATR, gaps, levels, patterns, excursions, and analogs can be corrupted.",
                prospective=True,
                provider_maybe=True,
            ),
            _compatibility_gap(
                "PRICE_BASIS_VERIFICATION",
                "Explicit raw/split-adjusted/total-return basis and transformation lineage.",
                "Schwab basis is unspecified and broad Daily adjustment method lacks event lineage.",
                "Corporate-action-sensitive analysis must abstain.",
                prospective=True,
                provider_maybe=False,
            ),
            _compatibility_gap(
                "POINT_IN_TIME_UNIVERSE",
                "Historical membership including renamed, inactive, acquired, and delisted securities.",
                "Current evidence is ticker-keyed and evidence-derived.",
                "Historical statistics remain exposed to survivorship bias.",
                prospective=False,
                provider_maybe=True,
            ),
        ],
    }
    report["reportFingerprint"] = _fingerprint(report)
    return report


def render_dataset_compatibility_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# ARGUS-RESEARCH-DATA-002 Dataset Compatibility",
        "",
        f"- As of: `{report['asOf']}`",
        f"- Classification: `{report['classification']}`",
        f"- Fingerprint: `{report['reportFingerprint']}`",
        f"- Point-in-time universe: `{report['pointInTimeUniverseCapability']}`",
        f"- Survivorship status: `{report['survivorshipBiasStatus']}`",
        f"- Provider selection: `{report['providerSelection']}`",
        "",
        "## Dataset Matrix",
        "",
        "| Dataset | Records | Symbols | Security ID | Price basis | Survivorship | Admission |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for item in report["datasets"]:
        lines.append(
            f"| {item['datasetId']} | {item['recordCount']} | {item['symbolCount']} | "
            f"{item['stableSecurityIdentity']} | {item['priceBasis']} | "
            f"{item['survivorshipBiasStatus']} | {item['admissionStatus']} |"
        )
    lines.extend(["", "## Unresolved Gaps", ""])
    for gap in report["gaps"]:
        lines.extend(
            [
                f"### {gap['gapId']}",
                "",
                f"- Requirement: {gap['requirement']}",
                f"- Existing capability: {gap['existingSourceCapability']}",
                f"- Missing capability: {gap['missingCapability']}",
                f"- Research consequence: {gap['researchConsequence']}",
                f"- Prospective collection can close: `{gap['prospectiveCollectionCanClose']}`",
                f"- Another provider might eventually be required: `{gap['providerMightEventuallyBeRequired']}`",
                "",
            ]
        )
    lines.extend(
        [
            "No provider is selected or procured by this task.",
            "",
            "This compatibility report grants no scoring, selection, Paper, Shadow, broker, or execution authority.",
        ]
    )
    return "\n".join(lines) + "\n"


def write_dataset_compatibility_outputs(
    report: Mapping[str, Any], *, json_path: Path, markdown_path: Path
) -> None:
    _write_once(
        json_path,
        (json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode(
            "ascii"
        ),
    )
    _write_once(markdown_path, render_dataset_compatibility_markdown(report).encode("ascii"))


def _compatibility_gap(
    gap_id: str,
    requirement: str,
    current: str,
    consequence: str,
    *,
    prospective: bool,
    provider_maybe: bool,
) -> dict[str, Any]:
    return {
        "gapId": gap_id,
        "requirement": requirement,
        "existingSourceCapability": current,
        "missingCapability": requirement,
        "researchConsequence": consequence,
        "prospectiveCollectionCanClose": prospective,
        "providerMightEventuallyBeRequired": provider_maybe,
    }


def _compatibility_price_basis(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in PRICE_BASES:
        return normalized
    return UNKNOWN_PRICE_BASIS


def _validate_inventory(inventory: Mapping[str, Any]) -> None:
    if not isinstance(inventory.get("datasets"), list):
        raise ResearchDataBasisError("DATA-001 inventory datasets were missing.")
    supplied = str(inventory.get("inventoryFingerprint") or "")
    _sha256(supplied, "DATA-001 inventory fingerprint")
    payload = dict(inventory)
    payload.pop("inventoryFingerprint", None)
    if _fingerprint(payload) != supplied:
        raise ResearchDataBasisError("DATA-001 inventory fingerprint did not match.")


def _validate_alias_timeline(aliases: Sequence[SymbolAlias]) -> None:
    for index, current in enumerate(aliases):
        _symbol(current.symbol)
        _date_text(current.effective_from, "Alias effective-from")
        if current.effective_to:
            _date_text(current.effective_to, "Alias effective-to")
        _sha256(current.evidence_fingerprint, "Alias evidence fingerprint")
        for later in aliases[index + 1 :]:
            current_end = current.effective_to or "9999-12-31"
            later_end = later.effective_to or "9999-12-31"
            if current.effective_from <= later_end and later.effective_from <= current_end:
                raise ResearchDataBasisError("Security aliases overlapped in time.")


def _with_security_fingerprint(identity: SecurityIdentity) -> SecurityIdentity:
    return replace(identity, fingerprint=security_identity_fingerprint(identity))


def _with_action_fingerprint(action: CorporateAction) -> CorporateAction:
    return replace(action, fingerprint=corporate_action_fingerprint(action))


def _with_bar_fingerprint(bar: ResearchPriceBar) -> ResearchPriceBar:
    return replace(bar, fingerprint=research_price_bar_fingerprint(bar))


def _bar_ohlcv(bar: ResearchPriceBar) -> OhlcvSnapshot:
    return OhlcvSnapshot(
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest().upper()


def _identifier(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise ResearchDataBasisError(f"{label} was invalid.")
    return text


def _optional_identifier(value: object, label: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    return _identifier(value, label)


def _optional_text(value: object, label: str) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    if len(text) > 512 or any(ord(char) < 32 for char in text):
        raise ResearchDataBasisError(f"{label} was invalid.")
    return text


def _symbol(value: object) -> str:
    text = str(value or "").strip().upper()
    if not _SYMBOL.fullmatch(text):
        raise ResearchDataBasisError("Symbol was invalid.")
    return text


def _optional_symbol(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    return _symbol(value)


def _sha256(value: object, label: str) -> str:
    text = str(value or "").strip().upper()
    if not _SHA256.fullmatch(text):
        raise ResearchDataBasisError(f"{label} was invalid.")
    return text


def _date_text(value: date | str, label: str) -> str:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        try:
            parsed = date.fromisoformat(str(value))
        except ValueError as exc:
            raise ResearchDataBasisError(f"{label} was invalid.") from exc
    return parsed.isoformat()


def _parse_timestamp(value: datetime | str, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ResearchDataBasisError(f"{label} was invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchDataBasisError(f"{label} lacked an explicit offset.")
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: datetime | str, label: str) -> str:
    return _parse_timestamp(value, label).isoformat()


def _optional_positive_int(value: object, label: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ResearchDataBasisError(f"{label} must be a positive integer.")
    return value


def _positive_decimal(value: object, label: str) -> Decimal:
    result = _decimal(value, label)
    if result <= 0:
        raise ResearchDataBasisError(f"{label} must be positive.")
    return result


def _nonnegative_decimal(value: object, label: str) -> Decimal:
    result = _decimal(value, label)
    if result < 0:
        raise ResearchDataBasisError(f"{label} cannot be negative.")
    return result


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool):
        raise ResearchDataBasisError(f"{label} was invalid.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ResearchDataBasisError(f"{label} was invalid.") from exc
    if not result.is_finite():
        raise ResearchDataBasisError(f"{label} was non-finite.")
    return result


def _decimal_text(value: Decimal) -> str:
    with localcontext() as context:
        context.prec = 40
        normalized = value.normalize()
    text = format(normalized, "f")
    return "0" if text in {"-0", ""} else text


def _loads_no_duplicate_keys(text: str) -> Any:
    def pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ResearchDataBasisError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        return json.loads(text, object_pairs_hook=pairs_hook)
    except json.JSONDecodeError as exc:
        raise ResearchDataBasisError("Serialized evidence was invalid JSON.") from exc


def _read_inventory(path: Path) -> Mapping[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ResearchDataBasisError("DATA-001 inventory was unreadable.") from exc
    if len(raw) > _MAX_JSON_BYTES:
        raise ResearchDataBasisError("DATA-001 inventory exceeded its size bound.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ResearchDataBasisError("DATA-001 inventory was not UTF-8 JSON.") from exc
    payload = _loads_no_duplicate_keys(text)
    if not isinstance(payload, Mapping):
        raise ResearchDataBasisError("DATA-001 inventory was not an object.")
    return payload


def _write_once(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == content:
            return
        raise ResearchDataBasisError("Conflicting compatibility output already exists.")
    try:
        with path.open("xb") as handle:
            handle.write(content)
    except OSError as exc:
        raise ResearchDataBasisError("Compatibility output could not be written.") from exc


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    inventory = _read_inventory(args.inventory)
    report = build_dataset_compatibility_report(inventory, as_of=args.as_of)
    write_dataset_compatibility_outputs(
        report, json_path=args.output_json, markdown_path=args.output_md
    )
    print(
        json.dumps(
            {
                "classification": report["classification"],
                "reportFingerprint": report["reportFingerprint"],
                "providerSelection": report["providerSelection"],
                "executionAuthority": report["executionAuthority"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
