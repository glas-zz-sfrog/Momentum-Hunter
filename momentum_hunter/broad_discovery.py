from __future__ import annotations

"""Immutable, bounded provider-response discovery snapshots.

This module deliberately has no provider transport, scheduler, broker, account,
order, persistence, or UI capability. A caller supplies one verified provider
response as parsed source rows and receives one deterministic snapshot.
"""

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import Iterable, Mapping

from momentum_hunter.models import Candidate, ScannerCriteria
from momentum_hunter.time_utils import CENTRAL_TZ


DISCOVERY_SNAPSHOT_CONTRACT_VERSION = 1
PAGINATED_DISCOVERY_SNAPSHOT_CONTRACT_VERSION = 2
DISCOVERY_ROW_CONTRACT_VERSION = 1
PAGINATED_DISCOVERY_ROW_CONTRACT_VERSION = 2
DISCOVERY_QUERY_CONTRACT_VERSION = 1
DISCOVERY_PAGINATION_POLICY_CONTRACT_VERSION = 1
DISCOVERY_PAGE_RECEIPT_CONTRACT_VERSION = 1
QUALIFICATION_POLICY_ID = "momentum-hunter-candidate-filter-v1"
COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE = "BOUNDED_PROVIDER_RESPONSE"
COVERAGE_SCOPE_FILTERED_PROVIDER_QUERY = "FILTERED_PROVIDER_QUERY"
PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED = "SINGLE_RESPONSE_UNPAGINATED"
PAGINATION_STATE_BOUNDED_OFFSET_PAGES = "BOUNDED_OFFSET_PAGES"
UNSEEN_ROW_COUNT_UNKNOWN = "UNKNOWN"
SNAPSHOT_STATUS_COMPLETE = "COMPLETE_WITHIN_REQUESTED_BOUND"
SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE = "PARTIAL_PROVIDER_FAILURE"
SNAPSHOT_STATUS_REQUEST_BUDGET_EXHAUSTED = "REQUEST_BUDGET_EXHAUSTED"
SNAPSHOT_STATUS_PROVIDER_PAGE_LIMIT = "PROVIDER_PAGE_LIMIT"
COMPLETE_FILTERED_RESULT_SET = "COMPLETE_FILTERED_RESULT_SET"
BOUNDED_PAGE_PREFIX = "BOUNDED_PAGE_PREFIX"
PROVIDER_PAGE_LIMIT = "PROVIDER_PAGE_LIMIT"
REQUEST_BUDGET_EXHAUSTED = "REQUEST_BUDGET_EXHAUSTED"
PARTIAL_PROVIDER_FAILURE = "PARTIAL_PROVIDER_FAILURE"
CROSS_PAGE_ATOMICITY_NOT_GUARANTEED = "NOT_GUARANTEED"
TRUNCATION_MAX_PAGES = "MAX_PAGES_REACHED"
TRUNCATION_MAX_ROWS = "MAX_ROWS_REACHED"
TRUNCATION_MAX_ELAPSED_TIME = "MAXIMUM_ELAPSED_TIME_REACHED"
TRUNCATION_PROVIDER_FAILURE = "PROVIDER_PAGE_FAILURE"
ROW_RELATIONSHIP_UNIQUE = "UNIQUE"
ROW_RELATIONSHIP_DUPLICATE_SOURCE = "DUPLICATE_SOURCE_OBSERVATION"
ROW_DISPOSITION_QUALIFIED = "QUALIFIED"
ROW_DISPOSITION_REJECTED_FILTER = "REJECTED_FILTER"


class DiscoveryPaginationError(ValueError):
    """Raised when a bounded paginated discovery pulse is contradictory."""


@dataclass(frozen=True)
class DiscoveryPaginationPolicy:
    """Versioned engineering bound for one explicit Finviz discovery pulse."""

    max_pages: int
    max_rows: int
    maximum_elapsed_time_seconds: float
    per_page_timeout_seconds: float
    inter_request_delay_seconds: float = 0.0
    policy_version: str = "finviz-pagination-policy-v1"
    contract_version: int = DISCOVERY_PAGINATION_POLICY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.max_pages < 1:
            raise DiscoveryPaginationError("Pagination max_pages must be positive.")
        if self.max_rows < 1:
            raise DiscoveryPaginationError("Pagination max_rows must be positive.")
        if self.maximum_elapsed_time_seconds <= 0:
            raise DiscoveryPaginationError(
                "Pagination maximum_elapsed_time_seconds must be positive."
            )
        if self.per_page_timeout_seconds <= 0:
            raise DiscoveryPaginationError(
                "Pagination per_page_timeout_seconds must be positive."
            )
        if self.inter_request_delay_seconds < 0:
            raise DiscoveryPaginationError(
                "Pagination inter_request_delay_seconds cannot be negative."
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "contractVersion": self.contract_version,
            "policyVersion": self.policy_version,
            "maxPages": self.max_pages,
            "maxRows": self.max_rows,
            "maximumElapsedTimeSeconds": _json_number(
                self.maximum_elapsed_time_seconds
            ),
            "perPageTimeoutSeconds": _json_number(self.per_page_timeout_seconds),
            "interRequestDelaySeconds": _json_number(
                self.inter_request_delay_seconds
            ),
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True)
class DiscoveryPageInput:
    """Verified source evidence for one page supplied to the pure aggregator."""

    page_number: int
    page_offset: int
    requested_at: datetime
    received_at: datetime
    request_duration_milliseconds: int
    source_rows: tuple[DiscoverySourceRow, ...] = ()
    raw_row_count: int = 0
    source_contract_fingerprint: str = ""
    semantic_plausibility_fingerprint: str = ""
    provider_total_results: int | None = None
    provider_page_size: int | None = None
    terminal_page: bool = False
    failure_reason: str | None = None


@dataclass(frozen=True)
class DiscoveryPageReceipt:
    contract_version: int
    page_number: int
    page_offset: int
    requested_at: datetime
    received_at: datetime
    request_duration_milliseconds: int
    raw_row_count: int
    parsed_row_count: int
    provider_total_results: int | None
    provider_page_size: int | None
    terminal_page: bool
    failure_reason: str | None
    source_contract_fingerprint: str
    semantic_plausibility_fingerprint: str
    fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "contractVersion": self.contract_version,
            "pageNumber": self.page_number,
            "pageOffset": self.page_offset,
            "requestedAt": _timestamp(self.requested_at),
            "receivedAt": _timestamp(self.received_at),
            "requestDurationMilliseconds": self.request_duration_milliseconds,
            "rawRowCount": self.raw_row_count,
            "parsedRowCount": self.parsed_row_count,
            "providerTotalResults": self.provider_total_results,
            "providerPageSize": self.provider_page_size,
            "terminalPage": self.terminal_page,
            "failureReason": self.failure_reason,
            "sourceContractFingerprint": self.source_contract_fingerprint,
            "semanticPlausibilityFingerprint": self.semantic_plausibility_fingerprint,
            "fingerprint": self.fingerprint,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DiscoveryPageReceipt":
        receipt = cls(
            contract_version=int(payload["contractVersion"]),
            page_number=int(payload["pageNumber"]),
            page_offset=int(payload["pageOffset"]),
            requested_at=_parse_timestamp(str(payload["requestedAt"])),
            received_at=_parse_timestamp(str(payload["receivedAt"])),
            request_duration_milliseconds=int(payload["requestDurationMilliseconds"]),
            raw_row_count=int(payload["rawRowCount"]),
            parsed_row_count=int(payload["parsedRowCount"]),
            provider_total_results=(
                int(payload["providerTotalResults"])
                if payload.get("providerTotalResults") is not None
                else None
            ),
            provider_page_size=(
                int(payload["providerPageSize"])
                if payload.get("providerPageSize") is not None
                else None
            ),
            terminal_page=bool(payload["terminalPage"]),
            failure_reason=(
                str(payload["failureReason"])
                if payload.get("failureReason") is not None
                else None
            ),
            source_contract_fingerprint=str(payload["sourceContractFingerprint"]),
            semantic_plausibility_fingerprint=str(
                payload["semanticPlausibilityFingerprint"]
            ),
            fingerprint=str(payload["fingerprint"]),
        )
        _validate_page_receipt(receipt)
        return receipt


@dataclass(frozen=True)
class DiscoveryQueryIdentity:
    """The exact request and qualification policy that define one bounded pulse."""

    contract_version: int
    source_query: str
    criteria_name: str
    min_volume: int
    min_percent_change: float
    min_market_cap: int
    min_price: float
    min_relative_volume: float
    sort_order: str
    page_bound: str
    qualification_policy_id: str = QUALIFICATION_POLICY_ID

    @classmethod
    def from_criteria(
        cls,
        criteria: ScannerCriteria,
        *,
        source_query: str,
        sort_order: str,
        page_bound: str = PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED,
    ) -> "DiscoveryQueryIdentity":
        return cls(
            contract_version=DISCOVERY_QUERY_CONTRACT_VERSION,
            source_query=source_query,
            criteria_name=criteria.name,
            min_volume=criteria.min_volume,
            min_percent_change=criteria.min_percent_change,
            min_market_cap=criteria.min_market_cap,
            min_price=criteria.min_price,
            min_relative_volume=criteria.min_relative_volume,
            sort_order=sort_order,
            page_bound=page_bound,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "contractVersion": self.contract_version,
            "sourceQuery": self.source_query,
            "criteriaName": self.criteria_name,
            "minVolume": self.min_volume,
            "minPercentChange": _json_number(self.min_percent_change),
            "minMarketCap": self.min_market_cap,
            "minPrice": _json_number(self.min_price),
            "minRelativeVolume": _json_number(self.min_relative_volume),
            "sortOrder": self.sort_order,
            "pageBound": self.page_bound,
            "qualificationPolicyId": self.qualification_policy_id,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DiscoveryQueryIdentity":
        return cls(
            contract_version=int(payload["contractVersion"]),
            source_query=str(payload["sourceQuery"]),
            criteria_name=str(payload["criteriaName"]),
            min_volume=int(payload["minVolume"]),
            min_percent_change=float(payload["minPercentChange"]),
            min_market_cap=int(payload["minMarketCap"]),
            min_price=float(payload["minPrice"]),
            min_relative_volume=float(payload["minRelativeVolume"]),
            sort_order=str(payload["sortOrder"]),
            page_bound=str(payload["pageBound"]),
            qualification_policy_id=str(payload["qualificationPolicyId"]),
        )

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.to_dict())


@dataclass(frozen=True)
class DiscoverySourceRow:
    """Transient parsed source evidence supplied to the pure snapshot builder."""

    source_row_ordinal: int
    source_row_identity: str
    source_values: tuple[tuple[str, str], ...]
    candidate: Candidate

    @classmethod
    def from_mapping(
        cls,
        *,
        source_row_ordinal: int,
        source_row_identity: str,
        source_values: Mapping[str, str],
        candidate: Candidate,
    ) -> "DiscoverySourceRow":
        return cls(
            source_row_ordinal=source_row_ordinal,
            source_row_identity=source_row_identity,
            source_values=tuple(
                (str(key), str(value)) for key, value in source_values.items()
            ),
            candidate=candidate,
        )


@dataclass(frozen=True)
class DiscoveryRow:
    contract_version: int
    row_id: str
    source_row_ordinal: int
    source_row_identity: str
    symbol: str
    source_values: tuple[tuple[str, str], ...]
    parsed_values: tuple[tuple[str, object], ...]
    disposition: str
    disposition_reasons: tuple[str, ...]
    candidate_identity: str | None
    fingerprint: str
    source_page_number: int | None = None
    source_page_offset: int | None = None
    source_page_ordinal: int | None = None
    global_observation_ordinal: int | None = None
    source_relationship: str | None = None

    def source_values_dict(self) -> dict[str, str]:
        return dict(self.source_values)

    def parsed_values_dict(self) -> dict[str, object]:
        return dict(self.parsed_values)

    def candidate(self) -> Candidate:
        values = self.parsed_values_dict()
        return Candidate(
            ticker=str(values["ticker"]),
            company=str(values["company"]),
            price=float(values["price"]),
            percent_change=float(values["percentChange"]),
            volume=int(values["volume"]),
            relative_volume=float(values["relativeVolume"]),
            market_cap=int(values["marketCap"]),
            sector=str(values["sector"]),
            industry=str(values["industry"]),
            float_shares=(
                int(values["floatShares"])
                if values["floatShares"] is not None
                else None
            ),
            atr=float(values["atr"]) if values["atr"] is not None else None,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "contractVersion": self.contract_version,
            "rowId": self.row_id,
            "sourceRowOrdinal": self.source_row_ordinal,
            "sourceRowIdentity": self.source_row_identity,
            "symbol": self.symbol,
            "sourceValues": self.source_values_dict(),
            "parsedValues": self.parsed_values_dict(),
            "disposition": self.disposition,
            "dispositionReasons": list(self.disposition_reasons),
            "candidateIdentity": self.candidate_identity,
            "fingerprint": self.fingerprint,
        }
        if self.contract_version == PAGINATED_DISCOVERY_ROW_CONTRACT_VERSION:
            payload.update(
                {
                    "sourcePageNumber": self.source_page_number,
                    "sourcePageOffset": self.source_page_offset,
                    "sourcePageOrdinal": self.source_page_ordinal,
                    "globalObservationOrdinal": self.global_observation_ordinal,
                    "sourceRelationship": self.source_relationship,
                }
            )
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DiscoveryRow":
        source_values = _string_pairs(payload["sourceValues"])
        parsed_values = _parsed_pairs(payload["parsedValues"])
        row = cls(
            contract_version=int(payload["contractVersion"]),
            row_id=str(payload["rowId"]),
            source_row_ordinal=int(payload["sourceRowOrdinal"]),
            source_row_identity=str(payload["sourceRowIdentity"]),
            symbol=str(payload["symbol"]),
            source_values=source_values,
            parsed_values=parsed_values,
            disposition=str(payload["disposition"]),
            disposition_reasons=tuple(
                str(item) for item in _list_value(payload["dispositionReasons"])
            ),
            candidate_identity=(
                str(payload["candidateIdentity"])
                if payload.get("candidateIdentity") is not None
                else None
            ),
            fingerprint=str(payload["fingerprint"]),
            source_page_number=(
                int(payload["sourcePageNumber"])
                if payload.get("sourcePageNumber") is not None
                else None
            ),
            source_page_offset=(
                int(payload["sourcePageOffset"])
                if payload.get("sourcePageOffset") is not None
                else None
            ),
            source_page_ordinal=(
                int(payload["sourcePageOrdinal"])
                if payload.get("sourcePageOrdinal") is not None
                else None
            ),
            global_observation_ordinal=(
                int(payload["globalObservationOrdinal"])
                if payload.get("globalObservationOrdinal") is not None
                else None
            ),
            source_relationship=(
                str(payload["sourceRelationship"])
                if payload.get("sourceRelationship") is not None
                else None
            ),
        )
        if row.contract_version not in {
            DISCOVERY_ROW_CONTRACT_VERSION,
            PAGINATED_DISCOVERY_ROW_CONTRACT_VERSION,
        }:
            raise ValueError("Unsupported discovery row contract version.")
        if row.disposition not in {
            ROW_DISPOSITION_QUALIFIED,
            ROW_DISPOSITION_REJECTED_FILTER,
        }:
            raise ValueError("Unknown discovery row disposition.")
        _validate_discovery_row(row)
        return row


@dataclass(frozen=True)
class DiscoverySnapshot:
    contract_version: int
    snapshot_id: str
    source: str
    source_version: str
    requested_at: datetime
    received_at: datetime
    evaluated_at: datetime
    session_date: str
    session_context: str
    query_identity: DiscoveryQueryIdentity
    query_fingerprint: str
    source_contract_fingerprint: str
    semantic_plausibility_fingerprint: str
    coverage_scope: str
    pagination_state: str
    pages_requested: int
    pages_received: int
    unseen_row_count: int | str
    raw_row_count: int
    parsed_row_count: int
    represented_row_count: int
    qualified_count: int
    rejected_count: int
    rows: tuple[DiscoveryRow, ...]
    status: str
    failure_reason: str | None
    fingerprint: str
    pagination_policy_version: str = ""
    pagination_policy_fingerprint: str = ""
    total_results_reported_by_provider: int | None = None
    total_pages_reported_by_provider: int | None = None
    page_size: int | None = None
    first_page: int | None = None
    last_page_requested: int | None = None
    pages_available: int | None = None
    coverage_state: str = ""
    truncation_reason: str | None = None
    cross_page_atomicity: str = ""
    first_request_at: datetime | None = None
    final_request_at: datetime | None = None
    pulse_duration_milliseconds: int | None = None
    page_receipts: tuple[DiscoveryPageReceipt, ...] = ()

    def qualified_candidates(self) -> tuple[Candidate, ...]:
        qualified = [
            row.candidate()
            for row in self.rows
            if row.disposition == ROW_DISPOSITION_QUALIFIED
        ]
        return tuple(_sort_candidates(qualified))

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "contractVersion": self.contract_version,
            "snapshotId": self.snapshot_id,
            "source": self.source,
            "sourceVersion": self.source_version,
            "requestedAt": _timestamp(self.requested_at),
            "receivedAt": _timestamp(self.received_at),
            "evaluatedAt": _timestamp(self.evaluated_at),
            "sessionDate": self.session_date,
            "sessionContext": self.session_context,
            "queryIdentity": self.query_identity.to_dict(),
            "queryFingerprint": self.query_fingerprint,
            "sourceContractFingerprint": self.source_contract_fingerprint,
            "semanticPlausibilityFingerprint": self.semantic_plausibility_fingerprint,
            "coverageScope": self.coverage_scope,
            "paginationState": self.pagination_state,
            "pagesRequested": self.pages_requested,
            "pagesReceived": self.pages_received,
            "unseenRowCount": self.unseen_row_count,
            "rawRowCount": self.raw_row_count,
            "parsedRowCount": self.parsed_row_count,
            "representedRowCount": self.represented_row_count,
            "qualifiedCount": self.qualified_count,
            "rejectedCount": self.rejected_count,
            "rows": [row.to_dict() for row in self.rows],
            "status": self.status,
            "failureReason": self.failure_reason,
            "fingerprint": self.fingerprint,
        }
        if self.contract_version == PAGINATED_DISCOVERY_SNAPSHOT_CONTRACT_VERSION:
            payload.update(
                {
                    "paginationPolicyVersion": self.pagination_policy_version,
                    "paginationPolicyFingerprint": self.pagination_policy_fingerprint,
                    "totalResultsReportedByProvider": self.total_results_reported_by_provider,
                    "totalPagesReportedByProvider": self.total_pages_reported_by_provider,
                    "pageSize": self.page_size,
                    "firstPage": self.first_page,
                    "lastPageRequested": self.last_page_requested,
                    "pagesAvailable": self.pages_available,
                    "coverageState": self.coverage_state,
                    "truncationReason": self.truncation_reason,
                    "crossPageAtomicity": self.cross_page_atomicity,
                    "firstRequestAt": (
                        _timestamp(self.first_request_at)
                        if self.first_request_at is not None
                        else None
                    ),
                    "finalRequestAt": (
                        _timestamp(self.final_request_at)
                        if self.final_request_at is not None
                        else None
                    ),
                    "pulseDurationMilliseconds": self.pulse_duration_milliseconds,
                    "pageReceipts": [item.to_dict() for item in self.page_receipts],
                }
            )
        return payload

    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DiscoverySnapshot":
        rows = tuple(
            DiscoveryRow.from_dict(_mapping_value(item))
            for item in _list_value(payload["rows"])
        )
        contract_version = int(payload["contractVersion"])
        page_receipts = tuple(
            DiscoveryPageReceipt.from_dict(_mapping_value(item))
            for item in _list_value(payload.get("pageReceipts", []))
        )
        snapshot = cls(
            contract_version=contract_version,
            snapshot_id=str(payload["snapshotId"]),
            source=str(payload["source"]),
            source_version=str(payload["sourceVersion"]),
            requested_at=_parse_timestamp(str(payload["requestedAt"])),
            received_at=_parse_timestamp(str(payload["receivedAt"])),
            evaluated_at=_parse_timestamp(str(payload["evaluatedAt"])),
            session_date=str(payload["sessionDate"]),
            session_context=str(payload["sessionContext"]),
            query_identity=DiscoveryQueryIdentity.from_dict(
                _mapping_value(payload["queryIdentity"])
            ),
            query_fingerprint=str(payload["queryFingerprint"]),
            source_contract_fingerprint=str(payload["sourceContractFingerprint"]),
            semantic_plausibility_fingerprint=str(
                payload["semanticPlausibilityFingerprint"]
            ),
            coverage_scope=str(payload["coverageScope"]),
            pagination_state=str(payload["paginationState"]),
            pages_requested=int(payload["pagesRequested"]),
            pages_received=int(payload["pagesReceived"]),
            unseen_row_count=_unseen_row_count(payload["unseenRowCount"]),
            raw_row_count=int(payload["rawRowCount"]),
            parsed_row_count=int(payload["parsedRowCount"]),
            represented_row_count=int(payload["representedRowCount"]),
            qualified_count=int(payload["qualifiedCount"]),
            rejected_count=int(payload["rejectedCount"]),
            rows=rows,
            status=str(payload["status"]),
            failure_reason=(
                str(payload["failureReason"])
                if payload.get("failureReason") is not None
                else None
            ),
            fingerprint=str(payload["fingerprint"]),
            pagination_policy_version=str(payload.get("paginationPolicyVersion", "")),
            pagination_policy_fingerprint=str(
                payload.get("paginationPolicyFingerprint", "")
            ),
            total_results_reported_by_provider=(
                int(payload["totalResultsReportedByProvider"])
                if payload.get("totalResultsReportedByProvider") is not None
                else None
            ),
            total_pages_reported_by_provider=(
                int(payload["totalPagesReportedByProvider"])
                if payload.get("totalPagesReportedByProvider") is not None
                else None
            ),
            page_size=(
                int(payload["pageSize"])
                if payload.get("pageSize") is not None
                else None
            ),
            first_page=(
                int(payload["firstPage"])
                if payload.get("firstPage") is not None
                else None
            ),
            last_page_requested=(
                int(payload["lastPageRequested"])
                if payload.get("lastPageRequested") is not None
                else None
            ),
            pages_available=(
                int(payload["pagesAvailable"])
                if payload.get("pagesAvailable") is not None
                else None
            ),
            coverage_state=str(payload.get("coverageState", "")),
            truncation_reason=(
                str(payload["truncationReason"])
                if payload.get("truncationReason") is not None
                else None
            ),
            cross_page_atomicity=str(payload.get("crossPageAtomicity", "")),
            first_request_at=(
                _parse_timestamp(str(payload["firstRequestAt"]))
                if payload.get("firstRequestAt") is not None
                else None
            ),
            final_request_at=(
                _parse_timestamp(str(payload["finalRequestAt"]))
                if payload.get("finalRequestAt") is not None
                else None
            ),
            pulse_duration_milliseconds=(
                int(payload["pulseDurationMilliseconds"])
                if payload.get("pulseDurationMilliseconds") is not None
                else None
            ),
            page_receipts=page_receipts,
        )
        _validate_snapshot(snapshot)
        return snapshot


def candidate_rejection_reasons(
    candidate: Candidate,
    criteria: ScannerCriteria,
) -> tuple[str, ...]:
    """Return every stable filter reason for one parsed candidate."""

    reasons: list[str] = []
    if candidate.volume < criteria.min_volume:
        reasons.append("BELOW_MIN_VOLUME")
    if candidate.percent_change < criteria.min_percent_change:
        reasons.append("BELOW_MIN_PERCENT_CHANGE")
    if candidate.market_cap < criteria.min_market_cap:
        reasons.append("BELOW_MIN_MARKET_CAP")
    if candidate.price < criteria.min_price:
        reasons.append("BELOW_MIN_PRICE")
    if (
        candidate.relative_volume != 0.0
        and candidate.relative_volume < criteria.min_relative_volume
    ):
        reasons.append("BELOW_MIN_RELATIVE_VOLUME")
    return tuple(reasons)


def filter_discovery_candidates(
    candidates: Iterable[Candidate],
    criteria: ScannerCriteria,
) -> list[Candidate]:
    qualifying = [
        candidate
        for candidate in candidates
        if not candidate_rejection_reasons(candidate, criteria)
    ]
    return _sort_candidates(qualifying)


def build_discovery_snapshot(
    *,
    source: str,
    source_version: str,
    requested_at: datetime,
    received_at: datetime,
    evaluated_at: datetime,
    query_identity: DiscoveryQueryIdentity,
    source_contract_fingerprint: str,
    semantic_plausibility_fingerprint: str,
    source_rows: Iterable[DiscoverySourceRow],
    raw_row_count: int | None = None,
    session_context: str | None = None,
    coverage_scope: str = COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE,
    pagination_state: str = PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED,
    pages_requested: int = 1,
    pages_received: int = 1,
    unseen_row_count: str = UNSEEN_ROW_COUNT_UNKNOWN,
) -> DiscoverySnapshot:
    """Build one complete bounded observation from already-verified source rows."""

    row_inputs = tuple(source_rows)
    if pages_requested < 1 or pages_received < 1:
        raise ValueError("Discovery pagination pages must be positive.")
    if coverage_scope != COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE:
        raise ValueError("Discovery coverage must be a bounded provider response.")
    if pagination_state != PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED:
        raise ValueError("Unsupported discovery pagination state.")
    if unseen_row_count != UNSEEN_ROW_COUNT_UNKNOWN:
        raise ValueError("Unseen row count must remain UNKNOWN without provider evidence.")
    if not source_contract_fingerprint or not semantic_plausibility_fingerprint:
        raise ValueError("Discovery snapshots require verified source and semantic fingerprints.")
    if raw_row_count is None:
        raw_row_count = len(row_inputs)
    if raw_row_count != len(row_inputs):
        raise ValueError("Raw row count must equal the complete represented response.")

    ordinals = [row.source_row_ordinal for row in row_inputs]
    if any(ordinal <= 0 for ordinal in ordinals) or len(set(ordinals)) != len(ordinals):
        raise ValueError("Discovery source row ordinals must be unique positive values.")

    requested_at = _normalize_datetime(requested_at)
    received_at = _normalize_datetime(received_at)
    evaluated_at = _normalize_datetime(evaluated_at)
    query_fingerprint = query_identity.fingerprint
    rows = tuple(
        _build_row(
            row,
            criteria=query_identity,
            query_fingerprint=query_fingerprint,
            row_contract_version=DISCOVERY_ROW_CONTRACT_VERSION,
        )
        for row in row_inputs
    )
    qualified_count = sum(
        row.disposition == ROW_DISPOSITION_QUALIFIED for row in rows
    )
    rejected_count = sum(
        row.disposition == ROW_DISPOSITION_REJECTED_FILTER for row in rows
    )
    session_central = evaluated_at.astimezone(CENTRAL_TZ)
    snapshot_without_identity = {
        "contractVersion": DISCOVERY_SNAPSHOT_CONTRACT_VERSION,
        "source": source.strip().lower(),
        "sourceVersion": source_version,
        "requestedAt": _timestamp(requested_at),
        "receivedAt": _timestamp(received_at),
        "evaluatedAt": _timestamp(evaluated_at),
        "sessionDate": session_central.date().isoformat(),
        "sessionContext": session_context or _session_context(session_central),
        "queryIdentity": query_identity.to_dict(),
        "queryFingerprint": query_fingerprint,
        "sourceContractFingerprint": source_contract_fingerprint,
        "semanticPlausibilityFingerprint": semantic_plausibility_fingerprint,
        "coverageScope": coverage_scope,
        "paginationState": pagination_state,
        "pagesRequested": pages_requested,
        "pagesReceived": pages_received,
        "unseenRowCount": unseen_row_count,
        "rawRowCount": raw_row_count,
        "parsedRowCount": len(rows),
        "representedRowCount": len(rows),
        "qualifiedCount": qualified_count,
        "rejectedCount": rejected_count,
        "rows": [row.to_dict() for row in rows],
        "status": SNAPSHOT_STATUS_COMPLETE,
        "failureReason": None,
    }
    fingerprint = _fingerprint(snapshot_without_identity)
    snapshot = DiscoverySnapshot(
        contract_version=DISCOVERY_SNAPSHOT_CONTRACT_VERSION,
        snapshot_id=f"discovery-{fingerprint[:24]}",
        source=source.strip().lower(),
        source_version=source_version,
        requested_at=requested_at,
        received_at=received_at,
        evaluated_at=evaluated_at,
        session_date=session_central.date().isoformat(),
        session_context=session_context or _session_context(session_central),
        query_identity=query_identity,
        query_fingerprint=query_fingerprint,
        source_contract_fingerprint=source_contract_fingerprint,
        semantic_plausibility_fingerprint=semantic_plausibility_fingerprint,
        coverage_scope=coverage_scope,
        pagination_state=pagination_state,
        pages_requested=pages_requested,
        pages_received=pages_received,
        unseen_row_count=unseen_row_count,
        raw_row_count=raw_row_count,
        parsed_row_count=len(rows),
        represented_row_count=len(rows),
        qualified_count=qualified_count,
        rejected_count=rejected_count,
        rows=rows,
        status=SNAPSHOT_STATUS_COMPLETE,
        failure_reason=None,
        fingerprint=fingerprint,
    )
    _validate_snapshot(snapshot)
    return snapshot


def pagination_page_bound(policy: DiscoveryPaginationPolicy) -> str:
    """Return the explicit query-identity marker for one bounded page policy."""

    return f"PAGINATED_POLICY:{policy.fingerprint}"


def build_paginated_discovery_snapshot(
    *,
    source: str,
    source_version: str,
    evaluated_at: datetime,
    query_identity: DiscoveryQueryIdentity,
    pagination_policy: DiscoveryPaginationPolicy,
    page_inputs: Iterable[DiscoveryPageInput],
    termination_reason: str | None = None,
    session_context: str | None = None,
) -> DiscoverySnapshot:
    """Aggregate verified Finviz pages into one bounded, coverage-aware snapshot.

    This is deliberately transport-free.  Each supplied page has already passed
    the provider's structural and semantic validation, or is an explicit failed
    request.  A failed page remains visible as a failed pulse rather than being
    relabeled as a smaller intentional prefix.
    """

    inputs = tuple(page_inputs)
    if not inputs:
        raise DiscoveryPaginationError("Paginated discovery requires at least one page.")
    if query_identity.page_bound != pagination_page_bound(pagination_policy):
        raise DiscoveryPaginationError(
            "Paginated discovery query identity must bind the pagination policy."
        )
    _validate_page_inputs(inputs, pagination_policy)

    successful = tuple(item for item in inputs if item.failure_reason is None)
    first_request_at = _normalize_datetime(inputs[0].requested_at)
    final_request_at = _normalize_datetime(inputs[-1].requested_at)
    final_received_at = _normalize_datetime(inputs[-1].received_at)
    evaluated_at = _normalize_datetime(evaluated_at)
    page_size = _page_size_from_inputs(successful)
    total_results = _consistent_provider_total(successful)
    pages_available = (
        _ceil_div(total_results, page_size)
        if total_results is not None and page_size is not None
        else None
    )
    if pages_available is not None and inputs[-1].page_number > pages_available:
        raise DiscoveryPaginationError(
            "Provider total results imply fewer pages than the supplied pulse."
        )

    page_receipts = tuple(_page_receipt(item) for item in inputs)
    source_contracts = {
        item.source_contract_fingerprint
        for item in successful
        if item.source_contract_fingerprint
    }
    if len(source_contracts) > 1:
        raise DiscoveryPaginationError(
            "Paginated discovery pages disagree on source contract identity."
        )
    source_contract_fingerprint = next(iter(source_contracts), "UNAVAILABLE")
    semantic_plausibility_fingerprint = _fingerprint(
        [
            item.semantic_plausibility_fingerprint
            for item in successful
            if item.semantic_plausibility_fingerprint
        ]
    )
    query_fingerprint = query_identity.fingerprint

    row_inputs: list[tuple[DiscoverySourceRow, DiscoveryPageInput, int, str]] = []
    source_signature_by_symbol: dict[str, str] = {}
    relationship_by_coordinate: dict[tuple[int, int], str] = {}
    for page in successful:
        for page_ordinal, source_row in enumerate(page.source_rows, start=1):
            coordinate = (page.page_number, page_ordinal)
            signature = _source_row_signature(source_row)
            symbol = source_row.candidate.ticker.strip().upper()
            existing_signature = source_signature_by_symbol.get(symbol)
            if existing_signature is None:
                source_signature_by_symbol[symbol] = signature
                relationship_by_coordinate[coordinate] = ROW_RELATIONSHIP_UNIQUE
            elif existing_signature == signature:
                relationship_by_coordinate[coordinate] = ROW_RELATIONSHIP_DUPLICATE_SOURCE
                for prior_coordinate, relationship in tuple(
                    relationship_by_coordinate.items()
                ):
                    if relationship == ROW_RELATIONSHIP_UNIQUE:
                        prior_page, prior_ordinal = prior_coordinate
                        prior = next(
                            (
                                row
                                for row, source_page, ordinal, _ in row_inputs
                                if source_page.page_number == prior_page
                                and ordinal == prior_ordinal
                                and row.candidate.ticker.strip().upper() == symbol
                            ),
                            None,
                        )
                        if prior is not None:
                            relationship_by_coordinate[prior_coordinate] = (
                                ROW_RELATIONSHIP_DUPLICATE_SOURCE
                            )
            else:
                raise DiscoveryPaginationError(
                    "Conflicting duplicate symbol observations across Finviz pages."
                )
            row_inputs.append((source_row, page, page_ordinal, signature))

    if len(row_inputs) > pagination_policy.max_rows:
        raise DiscoveryPaginationError(
            "Supplied discovery rows exceed the frozen pagination max_rows policy."
        )
    rows = tuple(
        _build_row(
            replace(source_row, source_row_ordinal=global_ordinal),
            criteria=query_identity,
            query_fingerprint=query_fingerprint,
            row_contract_version=PAGINATED_DISCOVERY_ROW_CONTRACT_VERSION,
            source_page_number=page.page_number,
            source_page_offset=page.page_offset,
            source_page_ordinal=page_ordinal,
            global_observation_ordinal=global_ordinal,
            source_relationship=relationship_by_coordinate[
                (page.page_number, page_ordinal)
            ],
        )
        for global_ordinal, (source_row, page, page_ordinal, _signature) in enumerate(
            row_inputs,
            start=1,
        )
    )
    coverage_state, status, truncation_reason = _coverage_from_inputs(
        inputs=inputs,
        successful=successful,
        pagination_policy=pagination_policy,
        pages_available=pages_available,
        page_size=page_size,
        represented_row_count=len(rows),
        explicit_termination_reason=termination_reason,
    )
    unseen_row_count: int | str = (
        total_results - len(rows)
        if total_results is not None
        else UNSEEN_ROW_COUNT_UNKNOWN
    )
    if isinstance(unseen_row_count, int) and unseen_row_count < 0:
        raise DiscoveryPaginationError(
            "Provider total results cannot be smaller than represented rows."
        )
    qualified_count = sum(
        row.disposition == ROW_DISPOSITION_QUALIFIED for row in rows
    )
    rejected_count = sum(
        row.disposition == ROW_DISPOSITION_REJECTED_FILTER for row in rows
    )
    session_central = evaluated_at.astimezone(CENTRAL_TZ)
    pulse_duration_milliseconds = max(
        0,
        int((final_request_at - first_request_at).total_seconds() * 1000),
    )
    snapshot_without_identity = {
        "contractVersion": PAGINATED_DISCOVERY_SNAPSHOT_CONTRACT_VERSION,
        "source": source.strip().lower(),
        "sourceVersion": source_version,
        "requestedAt": _timestamp(first_request_at),
        "receivedAt": _timestamp(final_received_at),
        "evaluatedAt": _timestamp(evaluated_at),
        "sessionDate": session_central.date().isoformat(),
        "sessionContext": session_context or _session_context(session_central),
        "queryIdentity": query_identity.to_dict(),
        "queryFingerprint": query_fingerprint,
        "sourceContractFingerprint": source_contract_fingerprint,
        "semanticPlausibilityFingerprint": semantic_plausibility_fingerprint,
        "coverageScope": COVERAGE_SCOPE_FILTERED_PROVIDER_QUERY,
        "paginationState": PAGINATION_STATE_BOUNDED_OFFSET_PAGES,
        "pagesRequested": len(inputs),
        "pagesReceived": len(successful),
        "unseenRowCount": unseen_row_count,
        "rawRowCount": sum(item.raw_row_count for item in successful),
        "parsedRowCount": len(rows),
        "representedRowCount": len(rows),
        "qualifiedCount": qualified_count,
        "rejectedCount": rejected_count,
        "rows": [row.to_dict() for row in rows],
        "status": status,
        "failureReason": (
            inputs[-1].failure_reason
            if status == SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE
            else None
        ),
        "paginationPolicyVersion": pagination_policy.policy_version,
        "paginationPolicyFingerprint": pagination_policy.fingerprint,
        "totalResultsReportedByProvider": total_results,
        "totalPagesReportedByProvider": None,
        "pageSize": page_size,
        "firstPage": inputs[0].page_number,
        "lastPageRequested": inputs[-1].page_number,
        "pagesAvailable": pages_available,
        "coverageState": coverage_state,
        "truncationReason": truncation_reason,
        "crossPageAtomicity": CROSS_PAGE_ATOMICITY_NOT_GUARANTEED,
        "firstRequestAt": _timestamp(first_request_at),
        "finalRequestAt": _timestamp(final_request_at),
        "pulseDurationMilliseconds": pulse_duration_milliseconds,
        "pageReceipts": [item.to_dict() for item in page_receipts],
    }
    fingerprint = _fingerprint(snapshot_without_identity)
    snapshot = DiscoverySnapshot(
        contract_version=PAGINATED_DISCOVERY_SNAPSHOT_CONTRACT_VERSION,
        snapshot_id=f"discovery-{fingerprint[:24]}",
        source=source.strip().lower(),
        source_version=source_version,
        requested_at=first_request_at,
        received_at=final_received_at,
        evaluated_at=evaluated_at,
        session_date=session_central.date().isoformat(),
        session_context=session_context or _session_context(session_central),
        query_identity=query_identity,
        query_fingerprint=query_fingerprint,
        source_contract_fingerprint=source_contract_fingerprint,
        semantic_plausibility_fingerprint=semantic_plausibility_fingerprint,
        coverage_scope=COVERAGE_SCOPE_FILTERED_PROVIDER_QUERY,
        pagination_state=PAGINATION_STATE_BOUNDED_OFFSET_PAGES,
        pages_requested=len(inputs),
        pages_received=len(successful),
        unseen_row_count=unseen_row_count,
        raw_row_count=sum(item.raw_row_count for item in successful),
        parsed_row_count=len(rows),
        represented_row_count=len(rows),
        qualified_count=qualified_count,
        rejected_count=rejected_count,
        rows=rows,
        status=status,
        failure_reason=(
            inputs[-1].failure_reason
            if status == SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE
            else None
        ),
        fingerprint=fingerprint,
        pagination_policy_version=pagination_policy.policy_version,
        pagination_policy_fingerprint=pagination_policy.fingerprint,
        total_results_reported_by_provider=total_results,
        total_pages_reported_by_provider=None,
        page_size=page_size,
        first_page=inputs[0].page_number,
        last_page_requested=inputs[-1].page_number,
        pages_available=pages_available,
        coverage_state=coverage_state,
        truncation_reason=truncation_reason,
        cross_page_atomicity=CROSS_PAGE_ATOMICITY_NOT_GUARANTEED,
        first_request_at=first_request_at,
        final_request_at=final_request_at,
        pulse_duration_milliseconds=pulse_duration_milliseconds,
        page_receipts=page_receipts,
    )
    _validate_snapshot(snapshot)
    return snapshot


def _validate_page_inputs(
    inputs: tuple[DiscoveryPageInput, ...],
    policy: DiscoveryPaginationPolicy,
) -> None:
    if len(inputs) > policy.max_pages:
        raise DiscoveryPaginationError(
            "Supplied page count exceeds the frozen pagination max_pages policy."
        )
    previous_received: datetime | None = None
    known_page_size: int | None = None
    for expected_page, item in enumerate(inputs, start=1):
        if item.page_number != expected_page:
            raise DiscoveryPaginationError(
                "Paginated discovery pages must start at one and remain consecutive."
            )
        if item.page_offset < 1:
            raise DiscoveryPaginationError("Finviz page offsets must be positive.")
        if expected_page == 1 and item.page_offset != 1:
            raise DiscoveryPaginationError("The first Finviz page must use offset one.")
        if known_page_size is not None and item.page_offset != 1 + (
            (expected_page - 1) * known_page_size
        ):
            raise DiscoveryPaginationError(
                "Finviz page offsets must advance by the established page size."
            )
        requested_at = _normalize_datetime(item.requested_at)
        received_at = _normalize_datetime(item.received_at)
        if received_at < requested_at:
            raise DiscoveryPaginationError(
                "Page receipt time cannot precede request time."
            )
        if previous_received is not None and requested_at < previous_received:
            raise DiscoveryPaginationError(
                "Paginated discovery pages must retain observed request order."
            )
        if item.request_duration_milliseconds < 0:
            raise DiscoveryPaginationError("Page request duration cannot be negative.")
        if item.provider_total_results is not None and item.provider_total_results < 0:
            raise DiscoveryPaginationError("Provider total result count cannot be negative.")
        if item.provider_page_size is not None and item.provider_page_size < 1:
            raise DiscoveryPaginationError("Provider page size must be positive.")
        if item.failure_reason is not None:
            if item.source_rows or item.raw_row_count != 0:
                raise DiscoveryPaginationError(
                    "A failed page cannot silently carry source rows."
                )
            if expected_page != len(inputs):
                raise DiscoveryPaginationError(
                    "No page may follow a failed paginated discovery request."
                )
        else:
            if item.raw_row_count != len(item.source_rows):
                raise DiscoveryPaginationError(
                    "Every successful page must reconcile raw and parsed source rows."
                )
            if not item.source_contract_fingerprint or not item.semantic_plausibility_fingerprint:
                raise DiscoveryPaginationError(
                    "Successful pages require verified contract and semantic fingerprints."
                )
            if item.provider_page_size is not None:
                if known_page_size is None:
                    known_page_size = item.provider_page_size
                elif known_page_size != item.provider_page_size:
                    raise DiscoveryPaginationError(
                        "Paginated discovery pages disagree on page size."
                    )
            elif item.source_rows and known_page_size is None:
                known_page_size = len(item.source_rows)
        if item.terminal_page and expected_page != len(inputs):
            raise DiscoveryPaginationError(
                "No page may follow an explicitly terminal provider page."
            )
        previous_received = received_at


def _page_size_from_inputs(
    successful: tuple[DiscoveryPageInput, ...],
) -> int | None:
    sizes = {
        item.provider_page_size
        for item in successful
        if item.provider_page_size is not None
    }
    if len(sizes) > 1:
        raise DiscoveryPaginationError("Paginated discovery pages disagree on page size.")
    if sizes:
        return next(iter(sizes))
    nonempty = [len(item.source_rows) for item in successful if item.source_rows]
    return nonempty[0] if nonempty else None


def _consistent_provider_total(
    successful: tuple[DiscoveryPageInput, ...],
) -> int | None:
    totals = {
        item.provider_total_results
        for item in successful
        if item.provider_total_results is not None
    }
    if len(totals) > 1:
        raise DiscoveryPaginationError(
            "Cross-page Finviz total result metadata changed during one pulse."
        )
    return next(iter(totals), None)


def _coverage_from_inputs(
    *,
    inputs: tuple[DiscoveryPageInput, ...],
    successful: tuple[DiscoveryPageInput, ...],
    pagination_policy: DiscoveryPaginationPolicy,
    pages_available: int | None,
    page_size: int | None,
    represented_row_count: int,
    explicit_termination_reason: str | None,
) -> tuple[str, str, str | None]:
    failed = next((item for item in inputs if item.failure_reason is not None), None)
    if failed is not None:
        if failed.failure_reason == PROVIDER_PAGE_LIMIT:
            return (
                PROVIDER_PAGE_LIMIT,
                SNAPSHOT_STATUS_PROVIDER_PAGE_LIMIT,
                PROVIDER_PAGE_LIMIT,
            )
        return (
            PARTIAL_PROVIDER_FAILURE,
            SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE,
            TRUNCATION_PROVIDER_FAILURE,
        )
    if not successful:
        raise DiscoveryPaginationError("A successful paginated snapshot needs one page.")
    last = successful[-1]
    if last.terminal_page or (
        pages_available is not None and last.page_number == pages_available
    ):
        if explicit_termination_reason is not None:
            raise DiscoveryPaginationError(
                "Terminal provider evidence cannot also claim local truncation."
            )
        return COMPLETE_FILTERED_RESULT_SET, SNAPSHOT_STATUS_COMPLETE, None
    if explicit_termination_reason == TRUNCATION_MAX_ELAPSED_TIME:
        return (
            REQUEST_BUDGET_EXHAUSTED,
            SNAPSHOT_STATUS_REQUEST_BUDGET_EXHAUSTED,
            TRUNCATION_MAX_ELAPSED_TIME,
        )
    if explicit_termination_reason == TRUNCATION_MAX_ROWS:
        return BOUNDED_PAGE_PREFIX, SNAPSHOT_STATUS_COMPLETE, TRUNCATION_MAX_ROWS
    if explicit_termination_reason == TRUNCATION_MAX_PAGES:
        return BOUNDED_PAGE_PREFIX, SNAPSHOT_STATUS_COMPLETE, TRUNCATION_MAX_PAGES
    if explicit_termination_reason is not None:
        raise DiscoveryPaginationError("Unknown paginated discovery termination reason.")
    if len(inputs) >= pagination_policy.max_pages:
        return BOUNDED_PAGE_PREFIX, SNAPSHOT_STATUS_COMPLETE, TRUNCATION_MAX_PAGES
    if represented_row_count >= pagination_policy.max_rows:
        return BOUNDED_PAGE_PREFIX, SNAPSHOT_STATUS_COMPLETE, TRUNCATION_MAX_ROWS
    first_request = _normalize_datetime(inputs[0].requested_at)
    final_request = _normalize_datetime(inputs[-1].requested_at)
    elapsed = (final_request - first_request).total_seconds()
    if elapsed >= pagination_policy.maximum_elapsed_time_seconds:
        return (
            REQUEST_BUDGET_EXHAUSTED,
            SNAPSHOT_STATUS_REQUEST_BUDGET_EXHAUSTED,
            TRUNCATION_MAX_ELAPSED_TIME,
        )
    if page_size is None:
        raise DiscoveryPaginationError(
            "No page size or terminal evidence was available to end pagination."
        )
    raise DiscoveryPaginationError(
        "Paginated discovery stopped without terminal or bounded-policy evidence."
    )


def _page_receipt(item: DiscoveryPageInput) -> DiscoveryPageReceipt:
    payload = {
        "contractVersion": DISCOVERY_PAGE_RECEIPT_CONTRACT_VERSION,
        "pageNumber": item.page_number,
        "pageOffset": item.page_offset,
        "requestedAt": _timestamp(item.requested_at),
        "receivedAt": _timestamp(item.received_at),
        "requestDurationMilliseconds": item.request_duration_milliseconds,
        "rawRowCount": item.raw_row_count,
        "parsedRowCount": len(item.source_rows),
        "providerTotalResults": item.provider_total_results,
        "providerPageSize": item.provider_page_size,
        "terminalPage": item.terminal_page,
        "failureReason": item.failure_reason,
        "sourceContractFingerprint": item.source_contract_fingerprint,
        "semanticPlausibilityFingerprint": item.semantic_plausibility_fingerprint,
    }
    receipt = DiscoveryPageReceipt(
        contract_version=DISCOVERY_PAGE_RECEIPT_CONTRACT_VERSION,
        page_number=item.page_number,
        page_offset=item.page_offset,
        requested_at=_normalize_datetime(item.requested_at),
        received_at=_normalize_datetime(item.received_at),
        request_duration_milliseconds=item.request_duration_milliseconds,
        raw_row_count=item.raw_row_count,
        parsed_row_count=len(item.source_rows),
        provider_total_results=item.provider_total_results,
        provider_page_size=item.provider_page_size,
        terminal_page=item.terminal_page,
        failure_reason=item.failure_reason,
        source_contract_fingerprint=item.source_contract_fingerprint,
        semantic_plausibility_fingerprint=item.semantic_plausibility_fingerprint,
        fingerprint=_fingerprint(payload),
    )
    _validate_page_receipt(receipt)
    return receipt


def _validate_page_receipt(receipt: DiscoveryPageReceipt) -> None:
    if receipt.contract_version != DISCOVERY_PAGE_RECEIPT_CONTRACT_VERSION:
        raise ValueError("Unsupported discovery page receipt contract version.")
    if receipt.page_number < 1 or receipt.page_offset < 1:
        raise ValueError("Discovery page receipt coordinates must be positive.")
    if receipt.request_duration_milliseconds < 0:
        raise ValueError("Discovery page receipt duration cannot be negative.")
    if receipt.raw_row_count < 0 or receipt.parsed_row_count < 0:
        raise ValueError("Discovery page receipt row counts cannot be negative.")
    if receipt.raw_row_count != receipt.parsed_row_count:
        raise ValueError("Discovery page receipt raw and parsed counts must reconcile.")
    if receipt.failure_reason is not None and receipt.parsed_row_count:
        raise ValueError("Failed discovery page receipts cannot carry parsed rows.")
    payload = receipt.to_dict()
    payload.pop("fingerprint")
    if receipt.fingerprint != _fingerprint(payload):
        raise ValueError("Discovery page receipt fingerprint does not match its content.")


def _source_row_signature(source_row: DiscoverySourceRow) -> str:
    return _fingerprint(
        {
            "symbol": source_row.candidate.ticker.strip().upper(),
            "sourceValues": {
                key: value
                for key, value in source_row.source_values
                if key != "No."
            },
            "candidate": _candidate_values(source_row.candidate),
        }
    )


def _ceil_div(numerator: int, denominator: int) -> int:
    if numerator == 0:
        return 1
    return (numerator + denominator - 1) // denominator


def _build_row(
    source_row: DiscoverySourceRow,
    *,
    criteria: DiscoveryQueryIdentity,
    query_fingerprint: str,
    row_contract_version: int,
    source_page_number: int | None = None,
    source_page_offset: int | None = None,
    source_page_ordinal: int | None = None,
    global_observation_ordinal: int | None = None,
    source_relationship: str | None = None,
) -> DiscoveryRow:
    candidate = source_row.candidate
    parsed_values = _candidate_values(candidate)
    reasons = candidate_rejection_reasons(
        candidate,
        ScannerCriteria(
            name=criteria.criteria_name,
            min_volume=criteria.min_volume,
            min_percent_change=criteria.min_percent_change,
            min_market_cap=criteria.min_market_cap,
            min_price=criteria.min_price,
            min_relative_volume=criteria.min_relative_volume,
        ),
    )
    disposition = (
        ROW_DISPOSITION_REJECTED_FILTER if reasons else ROW_DISPOSITION_QUALIFIED
    )
    identity_payload = {
        "sourceRowOrdinal": source_row.source_row_ordinal,
        "sourceRowIdentity": source_row.source_row_identity,
        "symbol": candidate.ticker.strip().upper(),
        "sourceValues": dict(source_row.source_values),
        "parsedValues": parsed_values,
        "queryFingerprint": query_fingerprint,
    }
    if row_contract_version == PAGINATED_DISCOVERY_ROW_CONTRACT_VERSION:
        identity_payload.update(
            {
                "contractVersion": row_contract_version,
                "sourcePageNumber": source_page_number,
                "sourcePageOffset": source_page_offset,
                "sourcePageOrdinal": source_page_ordinal,
                "globalObservationOrdinal": global_observation_ordinal,
                "sourceRelationship": source_relationship,
            }
        )
    evidence_fingerprint = _fingerprint(identity_payload)
    candidate_identity = (
        f"candidate-{evidence_fingerprint[:24]}"
        if disposition == ROW_DISPOSITION_QUALIFIED
        else None
    )
    row_without_identity = {
        "contractVersion": row_contract_version,
        "sourceRowOrdinal": source_row.source_row_ordinal,
        "sourceRowIdentity": source_row.source_row_identity,
        "symbol": candidate.ticker.strip().upper(),
        "sourceValues": dict(source_row.source_values),
        "parsedValues": parsed_values,
        "disposition": disposition,
        "dispositionReasons": list(reasons),
        "candidateIdentity": candidate_identity,
    }
    if row_contract_version == PAGINATED_DISCOVERY_ROW_CONTRACT_VERSION:
        row_without_identity.update(
            {
                "sourcePageNumber": source_page_number,
                "sourcePageOffset": source_page_offset,
                "sourcePageOrdinal": source_page_ordinal,
                "globalObservationOrdinal": global_observation_ordinal,
                "sourceRelationship": source_relationship,
            }
        )
    fingerprint = _fingerprint(row_without_identity)
    row = DiscoveryRow(
        contract_version=row_contract_version,
        row_id=f"row-{fingerprint[:24]}",
        source_row_ordinal=source_row.source_row_ordinal,
        source_row_identity=source_row.source_row_identity,
        symbol=candidate.ticker.strip().upper(),
        source_values=source_row.source_values,
        parsed_values=tuple(parsed_values.items()),
        disposition=disposition,
        disposition_reasons=reasons,
        candidate_identity=candidate_identity,
        fingerprint=fingerprint,
        source_page_number=source_page_number,
        source_page_offset=source_page_offset,
        source_page_ordinal=source_page_ordinal,
        global_observation_ordinal=global_observation_ordinal,
        source_relationship=source_relationship,
    )
    _validate_discovery_row(row)
    return row


def _candidate_values(candidate: Candidate) -> dict[str, object]:
    return {
        "ticker": candidate.ticker.strip().upper(),
        "company": candidate.company,
        "sector": candidate.sector,
        "industry": candidate.industry,
        "marketCap": candidate.market_cap,
        "price": _json_number(candidate.price),
        "percentChange": _json_number(candidate.percent_change),
        "volume": candidate.volume,
        "relativeVolume": _json_number(candidate.relative_volume),
        "floatShares": candidate.float_shares,
        "atr": _json_number(candidate.atr),
    }


def _sort_candidates(candidates: Iterable[Candidate]) -> list[Candidate]:
    return sorted(
        candidates,
        key=lambda item: (item.score, item.volume, item.percent_change),
        reverse=True,
    )


def _validate_discovery_row(row: DiscoveryRow) -> None:
    row_without_identity = {
        "contractVersion": row.contract_version,
        "sourceRowOrdinal": row.source_row_ordinal,
        "sourceRowIdentity": row.source_row_identity,
        "symbol": row.symbol,
        "sourceValues": row.source_values_dict(),
        "parsedValues": row.parsed_values_dict(),
        "disposition": row.disposition,
        "dispositionReasons": list(row.disposition_reasons),
        "candidateIdentity": row.candidate_identity,
    }
    if row.contract_version == PAGINATED_DISCOVERY_ROW_CONTRACT_VERSION:
        if (
            row.source_page_number is None
            or row.source_page_offset is None
            or row.source_page_ordinal is None
            or row.global_observation_ordinal is None
            or row.source_relationship not in {
                ROW_RELATIONSHIP_UNIQUE,
                ROW_RELATIONSHIP_DUPLICATE_SOURCE,
            }
        ):
            raise ValueError("Paginated discovery rows require complete page identity.")
        if (
            row.source_page_number < 1
            or row.source_page_offset < 1
            or row.source_page_ordinal < 1
            or row.global_observation_ordinal < 1
        ):
            raise ValueError("Paginated discovery row coordinates must be positive.")
        row_without_identity.update(
            {
                "sourcePageNumber": row.source_page_number,
                "sourcePageOffset": row.source_page_offset,
                "sourcePageOrdinal": row.source_page_ordinal,
                "globalObservationOrdinal": row.global_observation_ordinal,
                "sourceRelationship": row.source_relationship,
            }
        )
    elif any(
        value is not None
        for value in (
            row.source_page_number,
            row.source_page_offset,
            row.source_page_ordinal,
            row.global_observation_ordinal,
            row.source_relationship,
        )
    ):
        raise ValueError("Legacy discovery rows cannot carry paginated coordinates.")
    expected_fingerprint = _fingerprint(row_without_identity)
    if row.fingerprint != expected_fingerprint:
        raise ValueError("Discovery row fingerprint does not match its content.")
    if row.row_id != f"row-{expected_fingerprint[:24]}":
        raise ValueError("Discovery row identity does not match its content.")
    if row.disposition == ROW_DISPOSITION_QUALIFIED:
        if row.disposition_reasons or row.candidate_identity is None:
            raise ValueError("Qualified discovery rows require one candidate identity.")
    elif row.candidate_identity is not None:
        raise ValueError("Rejected discovery rows cannot carry a candidate identity.")


def _validate_snapshot(snapshot: DiscoverySnapshot) -> None:
    if snapshot.contract_version == DISCOVERY_SNAPSHOT_CONTRACT_VERSION:
        _validate_legacy_snapshot(snapshot)
        return
    if snapshot.contract_version == PAGINATED_DISCOVERY_SNAPSHOT_CONTRACT_VERSION:
        _validate_paginated_snapshot(snapshot)
        return
    raise ValueError("Unsupported discovery snapshot contract version.")


def _validate_legacy_snapshot(snapshot: DiscoverySnapshot) -> None:
    if snapshot.status != SNAPSHOT_STATUS_COMPLETE or snapshot.failure_reason is not None:
        raise ValueError("Only complete bounded discovery snapshots are valid.")
    if snapshot.coverage_scope != COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE:
        raise ValueError("Discovery snapshots cannot claim whole-market coverage.")
    if snapshot.pagination_state != PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED:
        raise ValueError("Unsupported discovery snapshot pagination state.")
    if snapshot.unseen_row_count != UNSEEN_ROW_COUNT_UNKNOWN:
        raise ValueError("Unseen row count requires explicit provider evidence.")
    if snapshot.pages_requested != 1 or snapshot.pages_received != 1:
        raise ValueError("Single-response discovery requires exactly one requested and received page.")
    if snapshot.query_fingerprint != snapshot.query_identity.fingerprint:
        raise ValueError("Discovery query fingerprint does not match its identity.")
    if snapshot.query_identity.contract_version != DISCOVERY_QUERY_CONTRACT_VERSION:
        raise ValueError("Unsupported discovery query contract version.")
    if snapshot.raw_row_count != snapshot.parsed_row_count:
        raise ValueError("Raw and parsed discovery rows must reconcile exactly.")
    if snapshot.parsed_row_count != snapshot.represented_row_count:
        raise ValueError("Parsed and represented discovery rows must reconcile exactly.")
    if snapshot.represented_row_count != len(snapshot.rows):
        raise ValueError("Every represented discovery row must have one row record.")
    qualified_count = sum(
        row.disposition == ROW_DISPOSITION_QUALIFIED for row in snapshot.rows
    )
    rejected_count = sum(
        row.disposition == ROW_DISPOSITION_REJECTED_FILTER for row in snapshot.rows
    )
    if snapshot.qualified_count != qualified_count or snapshot.rejected_count != rejected_count:
        raise ValueError("Discovery disposition counts do not match the row records.")
    if snapshot.represented_row_count != snapshot.qualified_count + snapshot.rejected_count:
        raise ValueError("Discovery row dispositions must reconcile exactly once.")
    snapshot_without_identity = snapshot.to_dict()
    snapshot_without_identity.pop("snapshotId")
    snapshot_without_identity.pop("fingerprint")
    expected_fingerprint = _fingerprint(snapshot_without_identity)
    if snapshot.fingerprint != expected_fingerprint:
        raise ValueError("Discovery snapshot fingerprint does not match its content.")
    if snapshot.snapshot_id != f"discovery-{expected_fingerprint[:24]}":
        raise ValueError("Discovery snapshot identity does not match its content.")


def _validate_paginated_snapshot(snapshot: DiscoverySnapshot) -> None:
    if snapshot.coverage_scope != COVERAGE_SCOPE_FILTERED_PROVIDER_QUERY:
        raise ValueError("Paginated snapshots must identify the filtered provider query.")
    if snapshot.pagination_state != PAGINATION_STATE_BOUNDED_OFFSET_PAGES:
        raise ValueError("Unsupported paginated discovery state.")
    if not snapshot.pagination_policy_version or not snapshot.pagination_policy_fingerprint:
        raise ValueError("Paginated snapshots require a versioned pagination policy.")
    if snapshot.query_identity.page_bound != (
        f"PAGINATED_POLICY:{snapshot.pagination_policy_fingerprint}"
    ):
        raise ValueError("Paginated query identity does not bind the policy fingerprint.")
    if snapshot.query_fingerprint != snapshot.query_identity.fingerprint:
        raise ValueError("Discovery query fingerprint does not match its identity.")
    if snapshot.query_identity.contract_version != DISCOVERY_QUERY_CONTRACT_VERSION:
        raise ValueError("Unsupported discovery query contract version.")
    if snapshot.pages_requested < 1 or snapshot.pages_received < 0:
        raise ValueError("Paginated discovery page counts are invalid.")
    if len(snapshot.page_receipts) != snapshot.pages_requested:
        raise ValueError("Paginated discovery receipts must match requested pages.")
    received_count = sum(item.failure_reason is None for item in snapshot.page_receipts)
    if snapshot.pages_received != received_count:
        raise ValueError("Paginated discovery received page count is inconsistent.")
    if snapshot.first_page != 1 or snapshot.last_page_requested != snapshot.pages_requested:
        raise ValueError("Paginated discovery page range is inconsistent.")
    if snapshot.first_request_at is None or snapshot.final_request_at is None:
        raise ValueError("Paginated discovery requires pulse request timestamps.")
    if snapshot.pulse_duration_milliseconds is None or snapshot.pulse_duration_milliseconds < 0:
        raise ValueError("Paginated discovery requires a nonnegative pulse duration.")
    if snapshot.cross_page_atomicity != CROSS_PAGE_ATOMICITY_NOT_GUARANTEED:
        raise ValueError("Cross-page atomicity cannot be claimed without provider proof.")
    if snapshot.total_pages_reported_by_provider is not None:
        raise ValueError("This Finviz contract does not expose authoritative total pages.")
    if snapshot.page_size is not None and snapshot.page_size < 1:
        raise ValueError("Paginated discovery page size must be positive.")
    if snapshot.total_results_reported_by_provider is not None:
        if snapshot.total_results_reported_by_provider < snapshot.represented_row_count:
            raise ValueError("Provider total results cannot be below represented rows.")
        if snapshot.page_size is not None:
            expected_available = _ceil_div(
                snapshot.total_results_reported_by_provider,
                snapshot.page_size,
            )
            if snapshot.pages_available != expected_available:
                raise ValueError("Paginated available page count is inconsistent.")
        if snapshot.unseen_row_count != (
            snapshot.total_results_reported_by_provider - snapshot.represented_row_count
        ):
            raise ValueError("Paginated unseen row count is inconsistent.")
    elif snapshot.unseen_row_count != UNSEEN_ROW_COUNT_UNKNOWN:
        raise ValueError("Unseen rows require provider total metadata or UNKNOWN.")
    if snapshot.raw_row_count != snapshot.parsed_row_count:
        raise ValueError("Raw and parsed paginated rows must reconcile exactly.")
    if snapshot.parsed_row_count != snapshot.represented_row_count:
        raise ValueError("Every parsed paginated row must be represented.")
    if snapshot.represented_row_count != len(snapshot.rows):
        raise ValueError("Every represented paginated row must have one row record.")
    if any(
        row.contract_version != PAGINATED_DISCOVERY_ROW_CONTRACT_VERSION
        for row in snapshot.rows
    ):
        raise ValueError("Paginated snapshots require paginated row identities.")
    global_ordinals = [row.global_observation_ordinal for row in snapshot.rows]
    if global_ordinals != list(range(1, len(snapshot.rows) + 1)):
        raise ValueError("Paginated global row ordinals must be complete and ordered.")
    qualified_count = sum(
        row.disposition == ROW_DISPOSITION_QUALIFIED for row in snapshot.rows
    )
    rejected_count = sum(
        row.disposition == ROW_DISPOSITION_REJECTED_FILTER for row in snapshot.rows
    )
    if snapshot.qualified_count != qualified_count or snapshot.rejected_count != rejected_count:
        raise ValueError("Paginated discovery disposition counts do not match rows.")
    if snapshot.represented_row_count != snapshot.qualified_count + snapshot.rejected_count:
        raise ValueError("Paginated row dispositions must reconcile exactly once.")
    if snapshot.coverage_state == COMPLETE_FILTERED_RESULT_SET:
        if snapshot.status != SNAPSHOT_STATUS_COMPLETE or snapshot.truncation_reason is not None:
            raise ValueError("Complete filtered coverage cannot be truncated or failed.")
    elif snapshot.coverage_state == BOUNDED_PAGE_PREFIX:
        if snapshot.status != SNAPSHOT_STATUS_COMPLETE or snapshot.truncation_reason not in {
            TRUNCATION_MAX_PAGES,
            TRUNCATION_MAX_ROWS,
        }:
            raise ValueError("Bounded page prefixes require an explicit local bound.")
    elif snapshot.coverage_state == REQUEST_BUDGET_EXHAUSTED:
        if (
            snapshot.status != SNAPSHOT_STATUS_REQUEST_BUDGET_EXHAUSTED
            or snapshot.truncation_reason != TRUNCATION_MAX_ELAPSED_TIME
        ):
            raise ValueError("Request-budget exhaustion must remain explicit.")
    elif snapshot.coverage_state == PARTIAL_PROVIDER_FAILURE:
        if (
            snapshot.status != SNAPSHOT_STATUS_PARTIAL_PROVIDER_FAILURE
            or snapshot.truncation_reason != TRUNCATION_PROVIDER_FAILURE
            or not snapshot.failure_reason
        ):
            raise ValueError("Partial provider failure must preserve its failure reason.")
    elif snapshot.coverage_state == PROVIDER_PAGE_LIMIT:
        if (
            snapshot.status != SNAPSHOT_STATUS_PROVIDER_PAGE_LIMIT
            or snapshot.truncation_reason != PROVIDER_PAGE_LIMIT
            or not snapshot.failure_reason
        ):
            raise ValueError("Provider page limits must remain explicit.")
    else:
        raise ValueError("Unknown paginated discovery coverage state.")
    snapshot_without_identity = snapshot.to_dict()
    snapshot_without_identity.pop("snapshotId")
    snapshot_without_identity.pop("fingerprint")
    expected_fingerprint = _fingerprint(snapshot_without_identity)
    if snapshot.fingerprint != expected_fingerprint:
        raise ValueError("Discovery snapshot fingerprint does not match its content.")
    if snapshot.snapshot_id != f"discovery-{expected_fingerprint[:24]}":
        raise ValueError("Discovery snapshot identity does not match its content.")


def _session_context(value: datetime) -> str:
    local_time = value.timetz().replace(tzinfo=None)
    if time(3, 0) <= local_time < time(8, 30):
        return "PREMARKET"
    if time(8, 30) <= local_time < time(15, 0):
        return "REGULAR"
    if time(15, 0) <= local_time < time(19, 0):
        return "AFTER_HOURS"
    return "CLOSED"


def _timestamp(value: datetime) -> str:
    return _normalize_datetime(value).isoformat()


def _parse_timestamp(value: str) -> datetime:
    return _normalize_datetime(datetime.fromisoformat(value))


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=CENTRAL_TZ)
    return value.astimezone(CENTRAL_TZ)


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _json_number(value: float | int | None) -> float | int | None:
    return value


def _mapping_value(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("Discovery contract requires an object.")
    return value


def _list_value(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Discovery contract requires a list.")
    return value


def _unseen_row_count(value: object) -> int | str:
    if value == UNSEEN_ROW_COUNT_UNKNOWN:
        return UNSEEN_ROW_COUNT_UNKNOWN
    if isinstance(value, bool):
        raise ValueError("Discovery unseen row count must be an integer or UNKNOWN.")
    parsed = int(value)
    if parsed < 0:
        raise ValueError("Discovery unseen row count cannot be negative.")
    return parsed


def _string_pairs(value: object) -> tuple[tuple[str, str], ...]:
    mapping = _mapping_value(value)
    return tuple((str(key), str(item)) for key, item in mapping.items())


def _parsed_pairs(value: object) -> tuple[tuple[str, object], ...]:
    mapping = _mapping_value(value)
    return tuple((str(key), item) for key, item in mapping.items())
