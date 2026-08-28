"""Prospective activation and immutable membership index for STAT-DATA-002.

The base opportunity and Continuous denominator stores remain authoritative.
This module binds their natural records to one immutable activation, preserves
every cycle as an attempt, and indexes unique opportunity membership without
adding provider, strategy, broker, account, order, service, scheduler, or UI
capability.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Mapping

from momentum_hunter.continuous_denominator import (
    CURRENTLY_OBSERVED,
    SOURCE_ROW_BLOCKED_DATA,
    SOURCE_ROW_REJECTED,
    ContinuousDenominatorPolicy,
    ContinuousDenominatorResult,
    ContinuousDenominatorStore,
    MemberDispositionRecord,
    SourceRowDispositionRecord,
    reference_continuous_denominator_policy,
    validate_continuous_denominator_result,
)
from momentum_hunter.opportunity_denominator import (
    EXECUTION_AUTHORITY_NONE,
    PROSPECTIVE,
    RESEARCH_ONLY,
    SAMPLE_IDENTITY,
    DenominatorPolicy,
    MarketPathOutcomeRecord,
    OpportunityRecord,
)


SCHEMA_VERSION = 1
ACTIVE_PROSPECTIVE = "ACTIVE_PROSPECTIVE"
HISTORICAL_CONTEXT_ONLY = "HISTORICAL_CONTEXT_ONLY"
PROSPECTIVE_OBSERVATION = "PROSPECTIVE_OBSERVATION"
STATISTICAL_OBSERVATION_ELIGIBLE = "STATISTICAL_OBSERVATION_ELIGIBLE"
EXECUTION_ELIGIBILITY_BLOCKED = "EXECUTION_ELIGIBILITY_BLOCKED"

DISCOVERED = "DISCOVERED"
HOT_UNIVERSE = "HOT_UNIVERSE"
READY = "READY"
COMPOSITION = "COMPOSITION"
TRADEPLAN = "TRADEPLAN"
NO_PLAN = "NO_PLAN"
STRATEGY_REJECT = "STRATEGY_REJECT"
DATA_BLOCKED = "DATA_BLOCKED"
PROVIDER_BOUND = "PROVIDER_BOUND"
MISSED_ENTRY = "MISSED_ENTRY"
SUCCESSOR_SETUP = "SUCCESSOR_SETUP"
POPULATIONS = (
    DISCOVERED,
    HOT_UNIVERSE,
    READY,
    COMPOSITION,
    TRADEPLAN,
    NO_PLAN,
    STRATEGY_REJECT,
    DATA_BLOCKED,
    PROVIDER_BOUND,
    MISSED_ENTRY,
    SUCCESSOR_SETUP,
)

SETUP_UNIT = "SETUP"
UNIVERSE_MEMBER_UNIT = "UNIVERSE_MEMBER"
DISCOVERY_ROW_UNIT = "DISCOVERY_ROW"
UNIT_KINDS = frozenset({SETUP_UNIT, UNIVERSE_MEMBER_UNIT, DISCOVERY_ROW_UNIT})

_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_SHA = re.compile(r"[0-9a-f]{40}")


class ProspectiveDenominatorError(RuntimeError):
    """Raised when prospective membership is incomplete or contradictory."""


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes({"domain": domain, "value": value})
    ).hexdigest()


def _record_fingerprint(value: object) -> str:
    payload = dict(value) if isinstance(value, Mapping) else asdict(value)
    payload.pop("fingerprint", None)
    return _fingerprint("stat-data-002-record-v1", payload)


def _timestamp(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProspectiveDenominatorError(f"{label} is malformed.") from exc
    if parsed.tzinfo is None:
        raise ProspectiveDenominatorError(f"{label} must include timezone evidence.")
    return parsed.isoformat()


def _parsed(value: str, label: str) -> datetime:
    return datetime.fromisoformat(_timestamp(value, label))


def _require_sha(value: str, label: str) -> str:
    normalized = str(value).strip().lower()
    if not _SHA256.fullmatch(normalized):
        raise ProspectiveDenominatorError(f"{label} must be SHA-256.")
    return normalized


@dataclass(frozen=True)
class ProspectiveActivationRecord:
    schema_version: int
    activation_id: str
    sample_identity: str
    status: str
    activated_at: str
    first_eligible_session_date: str
    source_git_sha: str
    configuration_fingerprint: str
    population_definitions: tuple[str, ...]
    historical_backfill_allowed: bool
    authority: str
    execution_authority: str
    fingerprint: str

    @property
    def policy(self) -> DenominatorPolicy:
        return DenominatorPolicy(
            status=ACTIVE_PROSPECTIVE,
            activated_at=self.activated_at,
            first_eligible_session_date=self.first_eligible_session_date,
        )

    @property
    def producer_policy(self) -> ContinuousDenominatorPolicy:
        return reference_continuous_denominator_policy(
            denominator_policy=self.policy,
            activation_fingerprint=self.fingerprint,
        )


@dataclass(frozen=True)
class ProspectiveMembershipRecord:
    schema_version: int
    activation_fingerprint: str
    membership_id: str
    unit_kind: str
    unit_identity: str
    symbol: str
    session_date: str
    first_observed_at: str
    first_decision_cutoff: str
    first_cycle_id: str
    first_cycle_fingerprint: str
    first_opportunity_id: str
    first_opportunity_fingerprint: str
    statistical_eligibility: str
    execution_eligibility: str
    execution_blockers: tuple[str, ...]
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class ProspectiveAttemptRecord:
    schema_version: int
    activation_fingerprint: str
    attempt_id: str
    membership_id: str
    cycle_id: str
    cycle_fingerprint: str
    opportunity_id: str
    opportunity_fingerprint: str
    observed_at: str
    decision_cutoff: str
    duplicate_membership: bool
    observation_class: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class ProspectivePopulationRecord:
    schema_version: int
    activation_fingerprint: str
    population_id: str
    membership_id: str
    population: str
    first_observed_at: str
    source_cycle_id: str
    source_opportunity_id: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class HistoricalContextRecord:
    schema_version: int
    activation_fingerprint: str
    context_record_id: str
    source_context_id: str
    symbol: str
    observed_at: str
    evidence_fingerprint: str
    observation_class: str
    creates_prospective_membership: bool
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class MembershipOutcomeLinkRecord:
    schema_version: int
    activation_fingerprint: str
    link_id: str
    membership_id: str
    opportunity_id: str
    opportunity_fingerprint: str
    outcome_id: str
    outcome_fingerprint: str
    attached_at: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class ProspectiveCycleReceipt:
    schema_version: int
    activation_fingerprint: str
    cycle_id: str
    cycle_fingerprint: str
    attempt_ids: tuple[str, ...]
    membership_ids: tuple[str, ...]
    population_ids: tuple[str, ...]
    completed_at: str
    authority: str
    execution_authority: str
    fingerprint: str


@dataclass(frozen=True)
class ProspectiveDenominatorSummary:
    activation_fingerprint: str
    prospective_observations_seen: int
    unique_prospective_members: int
    duplicate_observations_suppressed: int
    historical_context_only_records: int
    ready_members: int
    composition_members: int
    tradeplan_members: int
    no_plan_members: int
    outcome_complete_members: int
    outcome_pending_members: int
    population_counts: Mapping[str, int]


def build_activation_record(
    *,
    activated_at: str,
    first_eligible_session_date: str,
    source_git_sha: str,
    configuration_fingerprint: str,
) -> ProspectiveActivationRecord:
    activated = _timestamp(activated_at, "Activation timestamp")
    try:
        first_session = date.fromisoformat(first_eligible_session_date).isoformat()
    except ValueError as exc:
        raise ProspectiveDenominatorError(
            "First eligible session date is malformed."
        ) from exc
    source_sha = str(source_git_sha).strip().lower()
    if not _GIT_SHA.fullmatch(source_sha):
        raise ProspectiveDenominatorError("Activation source Git SHA is invalid.")
    configuration = _require_sha(
        configuration_fingerprint, "Activation configuration fingerprint"
    )
    identity_payload = {
        "sampleIdentity": SAMPLE_IDENTITY,
        "status": ACTIVE_PROSPECTIVE,
        "activatedAt": activated,
        "firstEligibleSessionDate": first_session,
        "sourceGitSha": source_sha,
        "configurationFingerprint": configuration,
        "populationDefinitions": POPULATIONS,
        "historicalBackfillAllowed": False,
        "authority": RESEARCH_ONLY,
        "executionAuthority": EXECUTION_AUTHORITY_NONE,
    }
    activation_id = _fingerprint("stat-data-002-activation-identity-v1", identity_payload)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "activation_id": activation_id,
        "sample_identity": SAMPLE_IDENTITY,
        "status": ACTIVE_PROSPECTIVE,
        "activated_at": activated,
        "first_eligible_session_date": first_session,
        "source_git_sha": source_sha,
        "configuration_fingerprint": configuration,
        "population_definitions": POPULATIONS,
        "historical_backfill_allowed": False,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(payload)
    record = ProspectiveActivationRecord(**payload)
    validate_activation(record)
    return record


def validate_activation(record: ProspectiveActivationRecord) -> None:
    if not isinstance(record, ProspectiveActivationRecord):
        raise ProspectiveDenominatorError("Activation record is malformed.")
    if record.schema_version != SCHEMA_VERSION:
        raise ProspectiveDenominatorError("Activation schema is unsupported.")
    if record.sample_identity != SAMPLE_IDENTITY or record.status != ACTIVE_PROSPECTIVE:
        raise ProspectiveDenominatorError("Activation sample identity or status drifted.")
    _timestamp(record.activated_at, "Activation timestamp")
    date.fromisoformat(record.first_eligible_session_date)
    if not _GIT_SHA.fullmatch(record.source_git_sha):
        raise ProspectiveDenominatorError("Activation source Git SHA is invalid.")
    _require_sha(record.configuration_fingerprint, "Activation configuration fingerprint")
    if record.population_definitions != POPULATIONS:
        raise ProspectiveDenominatorError("Activation population definitions drifted.")
    if record.historical_backfill_allowed:
        raise ProspectiveDenominatorError("Activation attempted historical backfill.")
    if record.authority != RESEARCH_ONLY or record.execution_authority != EXECUTION_AUTHORITY_NONE:
        raise ProspectiveDenominatorError("Activation attempted execution authority.")
    expected_activation_id = _fingerprint(
        "stat-data-002-activation-identity-v1",
        {
            "sampleIdentity": record.sample_identity,
            "status": record.status,
            "activatedAt": record.activated_at,
            "firstEligibleSessionDate": record.first_eligible_session_date,
            "sourceGitSha": record.source_git_sha,
            "configurationFingerprint": record.configuration_fingerprint,
            "populationDefinitions": record.population_definitions,
            "historicalBackfillAllowed": record.historical_backfill_allowed,
            "authority": record.authority,
            "executionAuthority": record.execution_authority,
        },
    )
    if record.activation_id != expected_activation_id:
        raise ProspectiveDenominatorError("Activation identity is invalid.")
    if record.fingerprint != _record_fingerprint(record):
        raise ProspectiveDenominatorError("Activation fingerprint is invalid.")


def load_activation_record(path: Path) -> ProspectiveActivationRecord:
    payload = _load_envelope(path, "STAT_DATA_002_ACTIVATION")
    try:
        record = ProspectiveActivationRecord(**payload)
    except TypeError as exc:
        raise ProspectiveDenominatorError("Activation payload is malformed.") from exc
    validate_activation(record)
    return record


class ProspectiveDenominatorStore:
    """Terminal prospective index over the authoritative denominator stores."""

    def __init__(self, root: Path, *, activation: ProspectiveActivationRecord) -> None:
        if not isinstance(root, Path):
            raise ProspectiveDenominatorError("Persistence root must be an explicit Path.")
        validate_activation(activation)
        self.root = root.resolve()
        self.activation = activation
        self.policy = activation.policy
        self.producer_policy = activation.producer_policy
        self.sample_root = self.root / SAMPLE_IDENTITY
        self.continuous = ContinuousDenominatorStore(
            self.root,
            denominator_policy=self.policy,
            producer_policy=self.producer_policy,
        )
        self._persist_record(
            self.sample_root / "activation" / "activation.json",
            "STAT_DATA_002_ACTIVATION",
            activation,
        )

    def persist_result(
        self,
        result: ContinuousDenominatorResult,
        *,
        completed_at: str,
    ) -> ProspectiveCycleReceipt:
        validate_continuous_denominator_result(result)
        if result.cycle.observation_mode != PROSPECTIVE:
            raise ProspectiveDenominatorError(
                "Only prospective Continuous evidence can enter the active sample."
            )
        if result.cycle.sample_identity != SAMPLE_IDENTITY:
            raise ProspectiveDenominatorError("Prospective cycle sample identity drifted.")
        observed = _parsed(result.cycle.observed_at, "Cycle observation timestamp")
        activated = _parsed(self.activation.activated_at, "Activation timestamp")
        if observed < activated:
            raise ProspectiveDenominatorError("Prospective cycle predates activation.")
        if date.fromisoformat(result.cycle.session_date) < date.fromisoformat(
            self.activation.first_eligible_session_date
        ):
            raise ProspectiveDenominatorError("Historical session cannot enter the prospective sample.")

        self.continuous.persist(result)
        opportunities = {item.opportunity_id: item for item in result.opportunities}
        rows = {item.opportunity_id: item for item in result.linkage.source_rows}
        members: dict[str, MemberDispositionRecord] = {}
        for member in result.linkage.members:
            for reference in member.opportunity_refs:
                members[reference.opportunity_id] = member

        attempt_ids: list[str] = []
        membership_ids: set[str] = set()
        population_ids: set[str] = set()
        for opportunity in result.opportunities:
            row = rows.get(opportunity.opportunity_id)
            member = members.get(opportunity.opportunity_id)
            unit_kind, unit_identity = _membership_unit(opportunity, row, member)
            membership_id = _fingerprint(
                "stat-data-002-membership-identity-v1",
                {
                    "activationFingerprint": self.activation.fingerprint,
                    "unitKind": unit_kind,
                    "unitIdentity": unit_identity,
                    "symbol": opportunity.symbol,
                },
            )
            member_path = self._path("prospective-members", membership_id)
            existing = self._read_optional(
                member_path, "PROSPECTIVE_MEMBERSHIP", ProspectiveMembershipRecord
            )
            if existing is None:
                membership = _membership_record(
                    activation=self.activation,
                    membership_id=membership_id,
                    unit_kind=unit_kind,
                    unit_identity=unit_identity,
                    opportunity=opportunity,
                    cycle_fingerprint=result.cycle.fingerprint,
                )
                self._persist_record(
                    member_path, "PROSPECTIVE_MEMBERSHIP", membership
                )
            else:
                membership = existing
                if (
                    membership.unit_kind != unit_kind
                    or membership.unit_identity != unit_identity
                    or membership.symbol != opportunity.symbol
                ):
                    raise ProspectiveDenominatorError("Membership identity drifted.")
                if _parsed(opportunity.observed_at, "Opportunity observation timestamp") < _parsed(
                    membership.first_observed_at, "First membership timestamp"
                ):
                    raise ProspectiveDenominatorError(
                        "Out-of-order replay predates immutable first membership."
                    )

            attempt = _attempt_record(
                activation=self.activation,
                membership=membership,
                opportunity=opportunity,
                cycle_fingerprint=result.cycle.fingerprint,
            )
            self._persist_record(
                self._path("prospective-attempts", attempt.attempt_id),
                "PROSPECTIVE_ATTEMPT",
                attempt,
            )
            attempt_ids.append(attempt.attempt_id)
            membership_ids.add(membership_id)
            for population in _populations(opportunity, row, member):
                population_id = _fingerprint(
                    "stat-data-002-population-identity-v1",
                    {
                        "activationFingerprint": self.activation.fingerprint,
                        "membershipId": membership_id,
                        "population": population,
                    },
                )
                path = self._path("prospective-populations", population_id)
                if not path.exists():
                    record = _population_record(
                        activation=self.activation,
                        population_id=population_id,
                        membership_id=membership_id,
                        population=population,
                        opportunity=opportunity,
                    )
                    self._persist_record(path, "PROSPECTIVE_POPULATION", record)
                else:
                    self._read_record(path, "PROSPECTIVE_POPULATION", ProspectivePopulationRecord)
                population_ids.add(population_id)

        receipt_payload = {
            "schema_version": SCHEMA_VERSION,
            "activation_fingerprint": self.activation.fingerprint,
            "cycle_id": result.cycle.cycle_id,
            "cycle_fingerprint": result.cycle.fingerprint,
            "attempt_ids": tuple(sorted(attempt_ids)),
            "membership_ids": tuple(sorted(membership_ids)),
            "population_ids": tuple(sorted(population_ids)),
            "completed_at": _timestamp(completed_at, "Cycle completion timestamp"),
            "authority": RESEARCH_ONLY,
            "execution_authority": EXECUTION_AUTHORITY_NONE,
        }
        receipt_payload["fingerprint"] = _record_fingerprint(receipt_payload)
        receipt = ProspectiveCycleReceipt(**receipt_payload)
        self._persist_record(
            self._path("prospective-cycle-receipts", receipt.cycle_id),
            "PROSPECTIVE_CYCLE_RECEIPT",
            receipt,
        )
        return receipt

    def persist_historical_context(
        self,
        *,
        source_context_id: str,
        symbol: str,
        observed_at: str,
        evidence_fingerprint: str,
    ) -> HistoricalContextRecord:
        observed = _timestamp(observed_at, "Historical context observation timestamp")
        evidence = _require_sha(evidence_fingerprint, "Historical context fingerprint")
        identity = _fingerprint(
            "stat-data-002-historical-context-identity-v1",
            {
                "activationFingerprint": self.activation.fingerprint,
                "sourceContextId": str(source_context_id),
                "symbol": str(symbol).upper(),
                "evidenceFingerprint": evidence,
            },
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "activation_fingerprint": self.activation.fingerprint,
            "context_record_id": identity,
            "source_context_id": str(source_context_id),
            "symbol": str(symbol).upper(),
            "observed_at": observed,
            "evidence_fingerprint": evidence,
            "observation_class": HISTORICAL_CONTEXT_ONLY,
            "creates_prospective_membership": False,
            "authority": RESEARCH_ONLY,
            "execution_authority": EXECUTION_AUTHORITY_NONE,
        }
        payload["fingerprint"] = _record_fingerprint(payload)
        record = HistoricalContextRecord(**payload)
        self._persist_record(
            self._path("historical-context", identity),
            "HISTORICAL_CONTEXT",
            record,
        )
        return record

    def persist_market_outcome(
        self,
        *,
        membership_id: str,
        outcome: MarketPathOutcomeRecord,
        attached_at: str,
    ) -> MembershipOutcomeLinkRecord:
        membership = self._read_record(
            self._path("prospective-members", membership_id),
            "PROSPECTIVE_MEMBERSHIP",
            ProspectiveMembershipRecord,
        )
        attempt = next(
            (
                item
                for item in self._records("prospective-attempts", "PROSPECTIVE_ATTEMPT", ProspectiveAttemptRecord)
                if item.membership_id == membership_id
                and item.opportunity_id == outcome.opportunity_id
                and item.opportunity_fingerprint == outcome.opportunity_fingerprint
            ),
            None,
        )
        if attempt is None:
            raise ProspectiveDenominatorError(
                "Outcome does not reference a persisted membership attempt."
            )
        attached = _timestamp(attached_at, "Outcome attachment timestamp")
        if _parsed(attached, "Outcome attachment timestamp") < _parsed(
            membership.first_observed_at, "First membership timestamp"
        ):
            raise ProspectiveDenominatorError("Outcome predates prospective membership.")
        self.continuous.denominator.persist_outcome(outcome)
        link_id = _fingerprint(
            "stat-data-002-outcome-link-identity-v1",
            {
                "activationFingerprint": self.activation.fingerprint,
                "membershipId": membership_id,
                "outcomeId": outcome.outcome_id,
            },
        )
        payload = {
            "schema_version": SCHEMA_VERSION,
            "activation_fingerprint": self.activation.fingerprint,
            "link_id": link_id,
            "membership_id": membership_id,
            "opportunity_id": outcome.opportunity_id,
            "opportunity_fingerprint": outcome.opportunity_fingerprint,
            "outcome_id": outcome.outcome_id,
            "outcome_fingerprint": outcome.fingerprint,
            "attached_at": attached,
            "authority": RESEARCH_ONLY,
            "execution_authority": EXECUTION_AUTHORITY_NONE,
        }
        payload["fingerprint"] = _record_fingerprint(payload)
        link = MembershipOutcomeLinkRecord(**payload)
        self._persist_record(
            self._path("membership-outcomes", link_id),
            "MEMBERSHIP_OUTCOME_LINK",
            link,
        )
        return link

    def summary(self) -> ProspectiveDenominatorSummary:
        receipts = self._records(
            "prospective-cycle-receipts",
            "PROSPECTIVE_CYCLE_RECEIPT",
            ProspectiveCycleReceipt,
        )
        attempt_ids = {identity for item in receipts for identity in item.attempt_ids}
        membership_ids = {identity for item in receipts for identity in item.membership_ids}
        population_ids = {identity for item in receipts for identity in item.population_ids}
        attempts = {
            item.attempt_id: item
            for item in self._records(
                "prospective-attempts", "PROSPECTIVE_ATTEMPT", ProspectiveAttemptRecord
            )
            if item.attempt_id in attempt_ids
        }
        if set(attempts) != attempt_ids:
            raise ProspectiveDenominatorError("Terminal receipt attempt set is incomplete.")
        members = {
            item.membership_id: item
            for item in self._records(
                "prospective-members", "PROSPECTIVE_MEMBERSHIP", ProspectiveMembershipRecord
            )
            if item.membership_id in membership_ids
        }
        if set(members) != membership_ids:
            raise ProspectiveDenominatorError("Terminal receipt membership set is incomplete.")
        populations = {
            item.population_id: item
            for item in self._records(
                "prospective-populations", "PROSPECTIVE_POPULATION", ProspectivePopulationRecord
            )
            if item.population_id in population_ids
        }
        if set(populations) != population_ids:
            raise ProspectiveDenominatorError("Terminal receipt population set is incomplete.")
        population_members: dict[str, set[str]] = {name: set() for name in POPULATIONS}
        for record in populations.values():
            if record.membership_id not in membership_ids:
                raise ProspectiveDenominatorError("Population references a nonterminal member.")
            population_members[record.population].add(record.membership_id)
        outcome_links = [
            item
            for item in self._records(
                "membership-outcomes", "MEMBERSHIP_OUTCOME_LINK", MembershipOutcomeLinkRecord
            )
            if item.membership_id in membership_ids
        ]
        outcome_members = {item.membership_id for item in outcome_links}
        historical = self._records(
            "historical-context", "HISTORICAL_CONTEXT", HistoricalContextRecord
        )
        return ProspectiveDenominatorSummary(
            activation_fingerprint=self.activation.fingerprint,
            prospective_observations_seen=len(attempts),
            unique_prospective_members=len(members),
            duplicate_observations_suppressed=sum(
                item.duplicate_membership for item in attempts.values()
            ),
            historical_context_only_records=len(historical),
            ready_members=len(population_members[READY]),
            composition_members=len(population_members[COMPOSITION]),
            tradeplan_members=len(population_members[TRADEPLAN]),
            no_plan_members=len(population_members[NO_PLAN]),
            outcome_complete_members=len(outcome_members),
            outcome_pending_members=len(membership_ids - outcome_members),
            population_counts={
                name: len(population_members[name]) for name in POPULATIONS
            },
        )

    def _path(self, folder: str, identity: str) -> Path:
        _require_sha(identity, "Record identity")
        return self.sample_root / folder / f"{identity}.json"

    def _records(self, folder: str, record_type: str, cls: type) -> list:
        root = self.sample_root / folder
        return [
            self._read_record(path, record_type, cls)
            for path in sorted(root.glob("*.json"))
        ] if root.exists() else []

    def _read_optional(self, path: Path, record_type: str, cls: type):
        return self._read_record(path, record_type, cls) if path.exists() else None

    def _read_record(self, path: Path, record_type: str, cls: type):
        payload = _load_envelope(path, record_type)
        try:
            record = cls(**payload)
        except TypeError as exc:
            raise ProspectiveDenominatorError(
                f"Persisted {record_type} payload is malformed."
            ) from exc
        _validate_index_record(record, self.activation.fingerprint)
        return record

    def _persist_record(self, path: Path, record_type: str, record: object) -> None:
        payload = asdict(record)
        if payload.get("fingerprint") != _record_fingerprint(payload):
            raise ProspectiveDenominatorError(f"{record_type} fingerprint is invalid.")
        content = _canonical_bytes({"recordType": record_type, "payload": payload})
        if path.exists():
            existing = path.read_bytes()
            _load_envelope(path, record_type)
            if existing != content:
                raise ProspectiveDenominatorError(
                    f"Conflicting write-once {record_type} record exists."
                )
            return
        _atomic_write(path, content)


def _membership_unit(
    opportunity: OpportunityRecord,
    row: SourceRowDispositionRecord | None,
    member: MemberDispositionRecord | None,
) -> tuple[str, str]:
    if member is not None and member.setup_id:
        return SETUP_UNIT, _require_sha(member.setup_id, "Setup identity")
    if member is not None:
        return UNIVERSE_MEMBER_UNIT, member.universe_member_id
    if row is not None:
        return DISCOVERY_ROW_UNIT, row.row_id
    raise ProspectiveDenominatorError(
        f"Opportunity {opportunity.opportunity_id} lacks canonical membership lineage."
    )


def _membership_record(
    *,
    activation: ProspectiveActivationRecord,
    membership_id: str,
    unit_kind: str,
    unit_identity: str,
    opportunity: OpportunityRecord,
    cycle_fingerprint: str,
) -> ProspectiveMembershipRecord:
    if unit_kind not in UNIT_KINDS:
        raise ProspectiveDenominatorError("Membership unit kind is unsupported.")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "activation_fingerprint": activation.fingerprint,
        "membership_id": membership_id,
        "unit_kind": unit_kind,
        "unit_identity": unit_identity,
        "symbol": opportunity.symbol,
        "session_date": opportunity.session_date,
        "first_observed_at": opportunity.observed_at,
        "first_decision_cutoff": opportunity.decision_cutoff,
        "first_cycle_id": opportunity.cycle_id,
        "first_cycle_fingerprint": cycle_fingerprint,
        "first_opportunity_id": opportunity.opportunity_id,
        "first_opportunity_fingerprint": opportunity.fingerprint,
        "statistical_eligibility": STATISTICAL_OBSERVATION_ELIGIBLE,
        "execution_eligibility": EXECUTION_ELIGIBILITY_BLOCKED,
        "execution_blockers": ("INSTRUMENT_CLASSIFICATION_UNAVAILABLE",),
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(payload)
    return ProspectiveMembershipRecord(**payload)


def _attempt_record(
    *,
    activation: ProspectiveActivationRecord,
    membership: ProspectiveMembershipRecord,
    opportunity: OpportunityRecord,
    cycle_fingerprint: str,
) -> ProspectiveAttemptRecord:
    attempt_id = _fingerprint(
        "stat-data-002-attempt-identity-v1",
        {
            "activationFingerprint": activation.fingerprint,
            "cycleId": opportunity.cycle_id,
            "opportunityId": opportunity.opportunity_id,
        },
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "activation_fingerprint": activation.fingerprint,
        "attempt_id": attempt_id,
        "membership_id": membership.membership_id,
        "cycle_id": opportunity.cycle_id,
        "cycle_fingerprint": cycle_fingerprint,
        "opportunity_id": opportunity.opportunity_id,
        "opportunity_fingerprint": opportunity.fingerprint,
        "observed_at": opportunity.observed_at,
        "decision_cutoff": opportunity.decision_cutoff,
        "duplicate_membership": (
            opportunity.opportunity_id != membership.first_opportunity_id
        ),
        "observation_class": PROSPECTIVE_OBSERVATION,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(payload)
    return ProspectiveAttemptRecord(**payload)


def _population_record(
    *,
    activation: ProspectiveActivationRecord,
    population_id: str,
    membership_id: str,
    population: str,
    opportunity: OpportunityRecord,
) -> ProspectivePopulationRecord:
    if population not in POPULATIONS:
        raise ProspectiveDenominatorError("Population is unsupported.")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "activation_fingerprint": activation.fingerprint,
        "population_id": population_id,
        "membership_id": membership_id,
        "population": population,
        "first_observed_at": opportunity.observed_at,
        "source_cycle_id": opportunity.cycle_id,
        "source_opportunity_id": opportunity.opportunity_id,
        "authority": RESEARCH_ONLY,
        "execution_authority": EXECUTION_AUTHORITY_NONE,
    }
    payload["fingerprint"] = _record_fingerprint(payload)
    return ProspectivePopulationRecord(**payload)


def _populations(
    opportunity: OpportunityRecord,
    row: SourceRowDispositionRecord | None,
    member: MemberDispositionRecord | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if row is not None:
        values.append(DISCOVERED)
        if row.treatment == SOURCE_ROW_REJECTED:
            values.append(STRATEGY_REJECT)
        if row.treatment == SOURCE_ROW_BLOCKED_DATA:
            values.append(DATA_BLOCKED)
    if member is not None:
        values.append(HOT_UNIVERSE)
        if member.readiness_status == READY:
            values.append(READY)
        if member.composition_disposition != "SYSTEM_FAILURE":
            values.append(COMPOSITION)
            values.append(TRADEPLAN if member.trade_plan_id else NO_PLAN)
        if member.composition_disposition == "MISSED_ENTRY_RECORDED":
            values.append(MISSED_ENTRY)
        if member.predecessor_setup_id:
            values.append(SUCCESSOR_SETUP)
        if member.composition_disposition in {
            "PROVIDER_BOUND",
            "NOT_EVALUATED_PROVIDER_BOUND",
        }:
            values.append(PROVIDER_BOUND)
        if member.blocker_reasons or member.composition_disposition in {
            "BLOCKED_DATA",
            "DATA_FAILURE",
            "SYSTEM_FAILURE",
        }:
            values.append(DATA_BLOCKED)
    return tuple(dict.fromkeys(values))


def _validate_index_record(record: object, activation_fingerprint: str) -> None:
    payload = asdict(record)
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ProspectiveDenominatorError("Prospective record schema drifted.")
    if payload.get("activation_fingerprint") != activation_fingerprint:
        raise ProspectiveDenominatorError("Prospective record activation drifted.")
    if payload.get("authority") != RESEARCH_ONLY or payload.get("execution_authority") != EXECUTION_AUTHORITY_NONE:
        raise ProspectiveDenominatorError("Prospective record attempted execution authority.")
    if payload.get("fingerprint") != _record_fingerprint(payload):
        raise ProspectiveDenominatorError("Prospective record fingerprint is invalid.")


def _load_envelope(path: Path, expected_type: str) -> dict[str, object]:
    try:
        value = json.loads(
            path.read_text(encoding="ascii"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProspectiveDenominatorError(
            f"Persisted {expected_type} record is malformed."
        ) from exc
    if not isinstance(value, dict) or set(value) != {"recordType", "payload"}:
        raise ProspectiveDenominatorError(f"Persisted {expected_type} envelope is invalid.")
    if value["recordType"] != expected_type or not isinstance(value["payload"], dict):
        raise ProspectiveDenominatorError(f"Persisted {expected_type} type is invalid.")
    return value["payload"]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ProspectiveDenominatorError(
                f"Persisted record contains duplicate key: {key}"
            )
        value[key] = item
    return value


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
