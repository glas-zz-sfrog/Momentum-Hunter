from __future__ import annotations

"""Immutable, bounded provider-response discovery snapshots.

This module deliberately has no provider transport, scheduler, broker, account,
order, persistence, or UI capability. A caller supplies one verified provider
response as parsed source rows and receives one deterministic snapshot.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time
from typing import Iterable, Mapping

from momentum_hunter.models import Candidate, ScannerCriteria
from momentum_hunter.time_utils import CENTRAL_TZ


DISCOVERY_SNAPSHOT_CONTRACT_VERSION = 1
DISCOVERY_ROW_CONTRACT_VERSION = 1
DISCOVERY_QUERY_CONTRACT_VERSION = 1
QUALIFICATION_POLICY_ID = "momentum-hunter-candidate-filter-v1"
COVERAGE_SCOPE_BOUNDED_PROVIDER_RESPONSE = "BOUNDED_PROVIDER_RESPONSE"
PAGINATION_STATE_SINGLE_RESPONSE_UNPAGINATED = "SINGLE_RESPONSE_UNPAGINATED"
UNSEEN_ROW_COUNT_UNKNOWN = "UNKNOWN"
SNAPSHOT_STATUS_COMPLETE = "COMPLETE_WITHIN_REQUESTED_BOUND"
ROW_DISPOSITION_QUALIFIED = "QUALIFIED"
ROW_DISPOSITION_REJECTED_FILTER = "REJECTED_FILTER"


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
        return {
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
        )
        if row.contract_version != DISCOVERY_ROW_CONTRACT_VERSION:
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
    unseen_row_count: str
    raw_row_count: int
    parsed_row_count: int
    represented_row_count: int
    qualified_count: int
    rejected_count: int
    rows: tuple[DiscoveryRow, ...]
    status: str
    failure_reason: str | None
    fingerprint: str

    def qualified_candidates(self) -> tuple[Candidate, ...]:
        qualified = [
            row.candidate()
            for row in self.rows
            if row.disposition == ROW_DISPOSITION_QUALIFIED
        ]
        return tuple(_sort_candidates(qualified))

    def to_dict(self) -> dict[str, object]:
        return {
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

    def canonical_json(self) -> str:
        return _canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "DiscoverySnapshot":
        rows = tuple(
            DiscoveryRow.from_dict(_mapping_value(item))
            for item in _list_value(payload["rows"])
        )
        snapshot = cls(
            contract_version=int(payload["contractVersion"]),
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
            unseen_row_count=str(payload["unseenRowCount"]),
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
        _build_row(row, criteria=query_identity, query_fingerprint=query_fingerprint)
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


def _build_row(
    source_row: DiscoverySourceRow,
    *,
    criteria: DiscoveryQueryIdentity,
    query_fingerprint: str,
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
    evidence_fingerprint = _fingerprint(identity_payload)
    candidate_identity = (
        f"candidate-{evidence_fingerprint[:24]}"
        if disposition == ROW_DISPOSITION_QUALIFIED
        else None
    )
    row_without_identity = {
        "contractVersion": DISCOVERY_ROW_CONTRACT_VERSION,
        "sourceRowOrdinal": source_row.source_row_ordinal,
        "sourceRowIdentity": source_row.source_row_identity,
        "symbol": candidate.ticker.strip().upper(),
        "sourceValues": dict(source_row.source_values),
        "parsedValues": parsed_values,
        "disposition": disposition,
        "dispositionReasons": list(reasons),
        "candidateIdentity": candidate_identity,
    }
    fingerprint = _fingerprint(row_without_identity)
    row = DiscoveryRow(
        contract_version=DISCOVERY_ROW_CONTRACT_VERSION,
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
    if snapshot.contract_version != DISCOVERY_SNAPSHOT_CONTRACT_VERSION:
        raise ValueError("Unsupported discovery snapshot contract version.")
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


def _string_pairs(value: object) -> tuple[tuple[str, str], ...]:
    mapping = _mapping_value(value)
    return tuple((str(key), str(item)) for key, item in mapping.items())


def _parsed_pairs(value: object) -> tuple[tuple[str, object], ...]:
    mapping = _mapping_value(value)
    return tuple((str(key), item) for key, item in mapping.items())
