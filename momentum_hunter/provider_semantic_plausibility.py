from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Iterable

from momentum_hunter.models import Candidate, ScannerCriteria


SEMANTIC_PLAUSIBILITY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ProviderSemanticPolicy:
    policy_id: str = "provider-semantic-plausibility-v1"
    maximum_price: float = 1_000_000.0
    maximum_absolute_change_percent: float = 1_000.0
    maximum_volume: int = 100_000_000_000
    maximum_relative_volume: float = 1_000.0
    maximum_market_cap: int = 100_000_000_000_000
    maximum_float_shares: int = 10_000_000_000_000
    maximum_atr_to_price_ratio: float = 10.0
    maximum_float_value_to_market_cap_ratio: float = 10.0
    repeated_signature_symbol_count: int = 4
    maximum_reference_price_difference_fraction: float = 0.20
    maximum_reference_age_seconds: float = 120.0
    maximum_future_timestamp_seconds: float = 5.0
    cumulative_volume_tolerance_fraction: float = 0.01
    minimum_distribution_sample_size: int = 5
    maximum_distribution_price_ratio: float = 100.0
    maximum_distribution_change_ratio: float = 50.0
    maximum_distribution_volume_ratio: float = 100.0
    maximum_distribution_relative_volume_ratio: float = 50.0


@dataclass(frozen=True)
class ProviderSemanticReference:
    symbol: str
    source: str
    observed_at: datetime
    session: str
    price: float
    cumulative_volume: int | None = None
    cumulative_volume_comparable: bool = False
    authoritative: bool = True


@dataclass(frozen=True)
class ProviderSemanticBaseline:
    source: str
    sample_size: int
    median_price: float | None = None
    median_absolute_change_percent: float | None = None
    median_volume: float | None = None
    median_relative_volume: float | None = None


@dataclass(frozen=True)
class ProviderSemanticIssue:
    code: str
    message: str
    symbols: tuple[str, ...] = ()
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderSemanticCandidateFacts:
    ticker: str
    price: float
    percent_change: float
    volume: int
    relative_volume: float
    market_cap: int
    float_shares: int | None
    atr: float | None


@dataclass(frozen=True)
class ProviderSemanticDiagnostics:
    schema_version: int
    policy_id: str
    provider: str
    status: str
    input_row_count: int
    parsed_candidate_count: int
    qualifying_candidate_count: int
    rejected_candidate_count: int
    rejection_reason_counts: tuple[tuple[str, int], ...]
    reference_count: int
    compared_reference_count: int
    evaluated_candidates: tuple[ProviderSemanticCandidateFacts, ...]
    evaluated_references: tuple[ProviderSemanticReference, ...]
    evaluated_baseline: ProviderSemanticBaseline | None
    issue_codes: tuple[str, ...]
    issues: tuple[ProviderSemanticIssue, ...]
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": self.schema_version,
            "policyId": self.policy_id,
            "provider": self.provider,
            "status": self.status,
            "inputRowCount": self.input_row_count,
            "parsedCandidateCount": self.parsed_candidate_count,
            "qualifyingCandidateCount": self.qualifying_candidate_count,
            "rejectedCandidateCount": self.rejected_candidate_count,
            "rejectionReasonCounts": dict(self.rejection_reason_counts),
            "referenceCount": self.reference_count,
            "comparedReferenceCount": self.compared_reference_count,
            "evaluatedCandidates": [
                _candidate_facts_payload(candidate)
                for candidate in self.evaluated_candidates
            ],
            "evaluatedReferences": [
                _reference_payload(reference)
                for reference in self.evaluated_references
            ],
            "evaluatedBaseline": (
                {
                    key: _json_number(value)
                    for key, value in self.evaluated_baseline.__dict__.items()
                }
                if self.evaluated_baseline is not None
                else None
            ),
            "issueCodes": list(self.issue_codes),
            "issues": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "symbols": list(issue.symbols),
                    "fields": list(issue.fields),
                }
                for issue in self.issues
            ],
            "fingerprint": self.fingerprint,
        }


def evaluate_provider_semantics(
    candidates: Iterable[Candidate],
    criteria: ScannerCriteria,
    *,
    provider: str,
    input_row_count: int | None = None,
    evaluation_time: datetime | None = None,
    expected_session: str | None = None,
    references: Iterable[ProviderSemanticReference] = (),
    baseline: ProviderSemanticBaseline | None = None,
    policy: ProviderSemanticPolicy = ProviderSemanticPolicy(),
) -> ProviderSemanticDiagnostics:
    candidate_list = list(candidates)
    reference_list = list(references)
    candidate_facts = tuple(
        ProviderSemanticCandidateFacts(
            ticker=_symbol(candidate.ticker),
            price=candidate.price,
            percent_change=candidate.percent_change,
            volume=candidate.volume,
            relative_volume=candidate.relative_volume,
            market_cap=candidate.market_cap,
            float_shares=candidate.float_shares,
            atr=candidate.atr,
        )
        for candidate in candidate_list
    )
    issues: list[ProviderSemanticIssue] = []
    rejection_reasons: Counter[str] = Counter()
    qualified = 0

    if input_row_count is None:
        input_row_count = len(candidate_list)
    if input_row_count < 0:
        issues.append(
            ProviderSemanticIssue(
                code="INPUT_ROW_COUNT_INVALID",
                message="Provider input row count cannot be negative.",
                fields=("input_row_count",),
            )
        )
    if input_row_count != len(candidate_list):
        issues.append(
            ProviderSemanticIssue(
                code="UNEXPLAINED_ROW_COUNT_COLLAPSE",
                message=(
                    f"Provider supplied {input_row_count} input rows but semantic evaluation "
                    f"received {len(candidate_list)} parsed candidates."
                ),
                fields=("input_row_count", "parsed_candidate_count"),
            )
        )

    ticker_counts = Counter(_symbol(candidate.ticker) for candidate in candidate_list)
    duplicates = tuple(sorted(ticker for ticker, count in ticker_counts.items() if count > 1))
    if duplicates:
        issues.append(
            ProviderSemanticIssue(
                code="DUPLICATE_SYMBOL_ROWS",
                message="Provider returned more than one economic row for the same symbol.",
                symbols=duplicates,
                fields=("ticker",),
            )
        )

    signatures: defaultdict[tuple[float, float, int, float], list[str]] = defaultdict(list)
    for candidate in candidate_list:
        symbol = _symbol(candidate.ticker)
        _check_candidate(candidate, symbol=symbol, policy=policy, issues=issues)
        signatures[
            (
                candidate.price,
                candidate.percent_change,
                candidate.volume,
                candidate.relative_volume,
            )
        ].append(symbol)
        reasons = _criteria_rejection_reasons(candidate, criteria)
        if reasons:
            rejection_reasons.update(reasons)
        else:
            qualified += 1

    for symbols in signatures.values():
        unique_symbols = tuple(sorted(set(symbols)))
        if len(unique_symbols) >= policy.repeated_signature_symbol_count:
            issues.append(
                ProviderSemanticIssue(
                    code="SUSPICIOUS_REPEATED_ECONOMIC_SIGNATURE",
                    message=(
                        "Distinct symbols share the exact same price, change, volume, and "
                        "relative-volume values."
                    ),
                    symbols=unique_symbols,
                    fields=("price", "percent_change", "volume", "relative_volume"),
                )
            )

    compared_reference_count = _check_references(
        candidate_list,
        reference_list,
        evaluation_time=evaluation_time,
        expected_session=expected_session,
        policy=policy,
        issues=issues,
    )
    if baseline is not None:
        _check_distribution(candidate_list, baseline=baseline, policy=policy, issues=issues)

    issues = sorted(
        issues,
        key=lambda item: (item.code, item.symbols, item.fields, item.message),
    )
    issue_codes = tuple(sorted({issue.code for issue in issues}))
    fingerprint_payload = {
        "schemaVersion": SEMANTIC_PLAUSIBILITY_SCHEMA_VERSION,
        "policy": policy.__dict__,
        "provider": provider.strip().lower(),
        "inputRowCount": input_row_count,
        "evaluationTime": (
            evaluation_time.isoformat()
            if evaluation_time is not None and reference_list
            else None
        ),
        "expectedSession": expected_session if reference_list else None,
        "candidates": [_candidate_facts_payload(candidate) for candidate in candidate_facts],
        "references": [_reference_payload(reference) for reference in reference_list],
        "baseline": (
            {
                key: _json_number(value)
                for key, value in baseline.__dict__.items()
            }
            if baseline is not None
            else None
        ),
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "symbols": issue.symbols,
                "fields": issue.fields,
            }
            for issue in issues
        ],
    }
    fingerprint = hashlib.sha256(
        json.dumps(
            fingerprint_payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    rejected = len(candidate_list) - qualified
    return ProviderSemanticDiagnostics(
        schema_version=SEMANTIC_PLAUSIBILITY_SCHEMA_VERSION,
        policy_id=policy.policy_id,
        provider=provider.strip().lower(),
        status="FAIL" if issues else "PASS",
        input_row_count=input_row_count,
        parsed_candidate_count=len(candidate_list),
        qualifying_candidate_count=qualified,
        rejected_candidate_count=rejected,
        rejection_reason_counts=tuple(sorted(rejection_reasons.items())),
        reference_count=len(reference_list),
        compared_reference_count=compared_reference_count,
        evaluated_candidates=candidate_facts,
        evaluated_references=tuple(reference_list),
        evaluated_baseline=baseline,
        issue_codes=issue_codes,
        issues=tuple(issues),
        fingerprint=fingerprint,
    )


def _check_candidate(
    candidate: Candidate,
    *,
    symbol: str,
    policy: ProviderSemanticPolicy,
    issues: list[ProviderSemanticIssue],
) -> None:
    numeric_checks = (
        ("price", candidate.price, 0.0, policy.maximum_price, False),
        (
            "percent_change",
            candidate.percent_change,
            -policy.maximum_absolute_change_percent,
            policy.maximum_absolute_change_percent,
            True,
        ),
        ("volume", candidate.volume, 0, policy.maximum_volume, False),
        (
            "relative_volume",
            candidate.relative_volume,
            0.0,
            policy.maximum_relative_volume,
            True,
        ),
        ("market_cap", candidate.market_cap, 0, policy.maximum_market_cap, False),
    )
    for field, value, minimum, maximum, minimum_inclusive in numeric_checks:
        if not _finite(value):
            issues.append(_field_issue("NONFINITE_VALUE", symbol, field, value))
        elif value > maximum or value < minimum or (not minimum_inclusive and value == minimum):
            issues.append(_field_issue("ECONOMIC_VALUE_OUT_OF_BOUNDS", symbol, field, value))

    if _finite(candidate.percent_change) and candidate.percent_change <= -100.0:
        issues.append(
            ProviderSemanticIssue(
                code="IMPOSSIBLE_PRICE_CHANGE_RELATIONSHIP",
                message=(
                    f"{symbol} percent change {candidate.percent_change} cannot imply a "
                    "positive prior close."
                ),
                symbols=(symbol,),
                fields=("price", "percent_change"),
            )
        )
    elif _finite(candidate.price) and _finite(candidate.percent_change):
        denominator = 1.0 + candidate.percent_change / 100.0
        implied_prior_close = candidate.price / denominator if denominator else math.nan
        if not _finite(implied_prior_close) or implied_prior_close <= 0:
            issues.append(
                ProviderSemanticIssue(
                    code="IMPOSSIBLE_PRICE_CHANGE_RELATIONSHIP",
                    message=f"{symbol} has no finite positive implied prior close.",
                    symbols=(symbol,),
                    fields=("price", "percent_change"),
                )
            )

    if candidate.float_shares is not None:
        if candidate.float_shares <= 0 or candidate.float_shares > policy.maximum_float_shares:
            issues.append(
                _field_issue(
                    "ECONOMIC_VALUE_OUT_OF_BOUNDS",
                    symbol,
                    "float_shares",
                    candidate.float_shares,
                )
            )
        elif candidate.market_cap > 0 and candidate.price > 0:
            ratio = candidate.float_shares * candidate.price / candidate.market_cap
            if ratio > policy.maximum_float_value_to_market_cap_ratio:
                issues.append(
                    ProviderSemanticIssue(
                        code="FLOAT_MARKET_CAP_INCONSISTENCY",
                        message=f"{symbol} float value exceeds market cap by an implausible factor.",
                        symbols=(symbol,),
                        fields=("float_shares", "price", "market_cap"),
                    )
                )
    if candidate.atr is not None:
        if not _finite(candidate.atr) or candidate.atr <= 0:
            issues.append(_field_issue("ECONOMIC_VALUE_OUT_OF_BOUNDS", symbol, "atr", candidate.atr))
        elif candidate.price > 0 and candidate.atr / candidate.price > policy.maximum_atr_to_price_ratio:
            issues.append(
                ProviderSemanticIssue(
                    code="ATR_PRICE_INCONSISTENCY",
                    message=f"{symbol} ATR is implausibly large relative to price.",
                    symbols=(symbol,),
                    fields=("atr", "price"),
                )
            )


def _check_references(
    candidates: list[Candidate],
    references: list[ProviderSemanticReference],
    *,
    evaluation_time: datetime | None,
    expected_session: str | None,
    policy: ProviderSemanticPolicy,
    issues: list[ProviderSemanticIssue],
) -> int:
    if not references:
        return 0
    if evaluation_time is None or evaluation_time.tzinfo is None:
        issues.append(
            ProviderSemanticIssue(
                code="REFERENCE_EVALUATION_TIME_UNAVAILABLE",
                message="Authoritative references require an offset-aware evaluation time.",
                fields=("evaluation_time",),
            )
        )
        return 0

    candidate_by_symbol = {_symbol(candidate.ticker): candidate for candidate in candidates}
    compared = 0
    seen: set[str] = set()
    for reference in references:
        symbol = _symbol(reference.symbol)
        if symbol in seen:
            issues.append(
                ProviderSemanticIssue(
                    code="DUPLICATE_AUTHORITATIVE_REFERENCE",
                    message=f"More than one authoritative reference was supplied for {symbol}.",
                    symbols=(symbol,),
                )
            )
            continue
        seen.add(symbol)
        source_name = " ".join(reference.source.lower().split())
        source_is_schwab = source_name.startswith("schwab") or source_name.startswith(
            "momentum hunter canonical schwab"
        )
        if not reference.authoritative or not source_is_schwab:
            issues.append(
                ProviderSemanticIssue(
                    code="REFERENCE_SOURCE_NOT_AUTHORIZED",
                    message=f"{symbol} comparison source is not authoritative Schwab evidence.",
                    symbols=(symbol,),
                    fields=("source", "authoritative"),
                )
            )
            continue
        if reference.observed_at.tzinfo is None:
            issues.append(
                ProviderSemanticIssue(
                    code="REFERENCE_TIMESTAMP_INVALID",
                    message=f"{symbol} reference timestamp is not offset-aware.",
                    symbols=(symbol,),
                    fields=("observed_at",),
                )
            )
            continue
        age_seconds = (evaluation_time - reference.observed_at).total_seconds()
        if age_seconds < -policy.maximum_future_timestamp_seconds:
            issues.append(
                ProviderSemanticIssue(
                    code="REFERENCE_TIMESTAMP_IN_FUTURE",
                    message=f"{symbol} reference timestamp is later than evaluation time.",
                    symbols=(symbol,),
                    fields=("observed_at", "evaluation_time"),
                )
            )
            continue
        if age_seconds > policy.maximum_reference_age_seconds:
            issues.append(
                ProviderSemanticIssue(
                    code="REFERENCE_STALE",
                    message=f"{symbol} authoritative reference is too old for comparison.",
                    symbols=(symbol,),
                    fields=("observed_at",),
                )
            )
            continue
        if (
            expected_session is not None
            and reference.session.strip().upper() != expected_session.strip().upper()
        ):
            issues.append(
                ProviderSemanticIssue(
                    code="REFERENCE_SESSION_MISMATCH",
                    message=f"{symbol} reference session does not match the evaluation session.",
                    symbols=(symbol,),
                    fields=("session",),
                )
            )
            continue
        candidate = candidate_by_symbol.get(symbol)
        if candidate is None:
            continue
        if not _finite(reference.price) or reference.price <= 0:
            issues.append(_field_issue("REFERENCE_VALUE_INVALID", symbol, "reference.price", reference.price))
            continue
        difference = abs(candidate.price - reference.price) / reference.price
        if difference > policy.maximum_reference_price_difference_fraction:
            issues.append(
                ProviderSemanticIssue(
                    code="AUTHORITATIVE_PRICE_DISAGREEMENT",
                    message=f"{symbol} provider price severely disagrees with authoritative Schwab price.",
                    symbols=(symbol,),
                    fields=("price", "reference.price"),
                )
            )
        if reference.cumulative_volume is not None and reference.cumulative_volume_comparable:
            if reference.cumulative_volume < 0:
                issues.append(
                    _field_issue(
                        "REFERENCE_VALUE_INVALID",
                        symbol,
                        "reference.cumulative_volume",
                        reference.cumulative_volume,
                    )
                )
            elif candidate.volume < reference.cumulative_volume * (
                1.0 - policy.cumulative_volume_tolerance_fraction
            ):
                issues.append(
                    ProviderSemanticIssue(
                        code="AUTHORITATIVE_VOLUME_CONTRADICTION",
                        message=(
                            f"{symbol} provider cumulative volume is below the time-aligned "
                            "authoritative candle volume."
                        ),
                        symbols=(symbol,),
                        fields=("volume", "reference.cumulative_volume"),
                    )
                )
        compared += 1
    return compared


def _check_distribution(
    candidates: list[Candidate],
    *,
    baseline: ProviderSemanticBaseline,
    policy: ProviderSemanticPolicy,
    issues: list[ProviderSemanticIssue],
) -> None:
    if (
        len(candidates) < policy.minimum_distribution_sample_size
        or baseline.sample_size < policy.minimum_distribution_sample_size
    ):
        return
    comparisons = (
        (
            "price",
            median(candidate.price for candidate in candidates),
            baseline.median_price,
            policy.maximum_distribution_price_ratio,
        ),
        (
            "absolute_change_percent",
            median(abs(candidate.percent_change) for candidate in candidates),
            baseline.median_absolute_change_percent,
            policy.maximum_distribution_change_ratio,
        ),
        (
            "volume",
            median(candidate.volume for candidate in candidates),
            baseline.median_volume,
            policy.maximum_distribution_volume_ratio,
        ),
        (
            "relative_volume",
            median(candidate.relative_volume for candidate in candidates),
            baseline.median_relative_volume,
            policy.maximum_distribution_relative_volume_ratio,
        ),
    )
    for field, current_value, baseline_value, maximum_ratio in comparisons:
        if baseline_value is None or baseline_value <= 0 or current_value <= 0:
            continue
        ratio = max(current_value / baseline_value, baseline_value / current_value)
        if ratio > maximum_ratio:
            issues.append(
                ProviderSemanticIssue(
                    code="EXTREME_DISTRIBUTION_SHIFT",
                    message=f"Provider {field} distribution changed by an implausible factor.",
                    fields=(field, f"baseline.{field}"),
                )
            )


def _criteria_rejection_reasons(
    candidate: Candidate,
    criteria: ScannerCriteria,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if candidate.volume < criteria.min_volume:
        reasons.append("BELOW_MIN_VOLUME")
    if candidate.percent_change < criteria.min_percent_change:
        reasons.append("BELOW_MIN_PERCENT_CHANGE")
    if candidate.market_cap < criteria.min_market_cap:
        reasons.append("BELOW_MIN_MARKET_CAP")
    if candidate.price < criteria.min_price:
        reasons.append("BELOW_MIN_PRICE")
    if candidate.relative_volume != 0.0 and candidate.relative_volume < criteria.min_relative_volume:
        reasons.append("BELOW_MIN_RELATIVE_VOLUME")
    return tuple(reasons)


def _field_issue(code: str, symbol: str, field: str, value: object) -> ProviderSemanticIssue:
    return ProviderSemanticIssue(
        code=code,
        message=f"{symbol} {field} has an implausible value: {value!r}.",
        symbols=(symbol,),
        fields=(field,),
    )


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _symbol(value: str) -> str:
    return value.strip().upper()


def _reference_payload(reference: ProviderSemanticReference) -> dict[str, object]:
    observed_at = reference.observed_at
    if observed_at.tzinfo is not None:
        observed_at = observed_at.astimezone(timezone.utc)
    return {
        "symbol": _symbol(reference.symbol),
        "source": reference.source,
        "observedAt": observed_at.isoformat(),
        "session": reference.session,
        "price": _json_number(reference.price),
        "cumulativeVolume": _json_number(reference.cumulative_volume),
        "cumulativeVolumeComparable": reference.cumulative_volume_comparable,
        "authoritative": reference.authoritative,
    }


def _candidate_facts_payload(
    candidate: ProviderSemanticCandidateFacts,
) -> dict[str, object]:
    return {
        "ticker": candidate.ticker,
        "price": _json_number(candidate.price),
        "percentChange": _json_number(candidate.percent_change),
        "volume": _json_number(candidate.volume),
        "relativeVolume": _json_number(candidate.relative_volume),
        "marketCap": _json_number(candidate.market_cap),
        "floatShares": _json_number(candidate.float_shares),
        "atr": _json_number(candidate.atr),
    }


def _json_number(value: object) -> object:
    if value is None or isinstance(value, str):
        return value
    if _finite(value):
        return value
    return repr(value)
