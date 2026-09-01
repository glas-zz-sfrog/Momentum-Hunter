"""Rebuildable custody coverage derived only from immutable record identities."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

from .contract import HORIZONS, TERMINAL_OUTCOME_STATES


METRIC_IDS = (
    "DISCOVERY_CYCLE_COVERAGE",
    "DENOMINATOR_ROW_COVERAGE",
    "DECISION_IDENTITY_COVERAGE",
    "QUOTE_SNAPSHOT_COVERAGE",
    "SCORE_COVERAGE",
    "CATALYST_IDENTITY_COVERAGE",
    "REFERENCE_LEVEL_COVERAGE",
    "OUTCOME_ELIGIBILITY_ACCOUNTING_COVERAGE",
    "OUTCOME_ATTEMPT_OR_GAP_RECEIPT_COVERAGE",
    "OUTCOME_ELIGIBLE_SYMBOL_COVERAGE",
    "OUTCOME_ELIGIBLE_DECISION_COVERAGE",
    "OUTCOME_HORIZON_COVERAGE",
    "KNOWN_AT_COVERAGE",
    "RESTART_RECOVERY_SUCCESS",
    "RECEIPT_CHAIN_VERIFICATION",
    "RECORDER_LAG",
)


class CoverageReconciliationError(ValueError):
    """Raised when immutable records cannot produce one unambiguous coverage view."""


@dataclass(frozen=True)
class CoverageSummary:
    discovery_cycles: int
    returned_rows_declared: int
    candidate_observations: int
    unique_instruments: int
    eligible_instruments: int
    material_decisions: int
    expected_outcome_slots: int
    received_outcome_slots: int
    accounted_outcome_slots: int
    nonterminal_outcome_slots: int
    unaccounted_outcome_slots: int
    usable_outcome_slots: int
    terminal_gap_slots: int
    outcome_accounting_rate_ppm: int
    outcome_accounting_rate_state: str
    usable_outcome_rate_ppm: int
    usable_outcome_rate_state: str
    by_horizon: Mapping[str, Mapping[str, object]]
    metrics: Mapping[str, Mapping[str, object]]
    conflicts: int

    def to_mapping(self) -> dict[str, object]:
        return asdict(self)


def _recorder_id(value: object) -> str:
    if isinstance(value, Mapping) and isinstance(value.get("recorder_id"), str):
        return str(value["recorder_id"])
    return ""


def _ratio(numerator: int, denominator: int) -> dict[str, object]:
    if numerator < 0 or denominator < 0 or numerator > denominator:
        raise CoverageReconciliationError(
            "Coverage numerator must be between zero and its declared denominator."
        )
    if denominator == 0:
        return {
            "denominator": 0,
            "numerator": numerator,
            "rate_ppm": 0,
            "state": "NOT_APPLICABLE",
        }
    return {
        "denominator": denominator,
        "numerator": numerator,
        "rate_ppm": numerator * 1_000_000 // denominator,
        "state": "AVAILABLE",
    }


def _not_proven(reason: str) -> dict[str, object]:
    return {"denominator": 0, "numerator": 0, "reason": reason, "state": "NOT_PROVEN"}


def derive_coverage(
    records: Iterable[Mapping[str, object]],
    *,
    conflicts: int = 0,
) -> CoverageSummary:
    """Compute custody accounting and usability without symbol/time inference."""

    items = tuple(records)
    cycles = [item for item in items if item.get("record_type") == "discovery-cycle" and _recorder_id(item.get("record_id"))]
    observations = [item for item in items if item.get("record_type") == "candidate-observation" and _recorder_id(item.get("observation_id"))]
    decisions = [item for item in items if item.get("record_type") == "decision-event" and _recorder_id(item.get("decision_id"))]
    outcomes = [item for item in items if item.get("record_type") == "outcome-observation" and _recorder_id(item.get("outcome_observation_id"))]
    science_eligibility_records = [
        item
        for item in items
        if item.get("record_type") == "science-eligibility"
        and _recorder_id(item.get("eligibility_id"))
    ]
    observations_by_id: dict[str, Mapping[str, object]] = {}
    for item in observations:
        observation_id = _recorder_id(item.get("observation_id"))
        if observation_id in observations_by_id:
            raise CoverageReconciliationError(
                "Duplicate immutable observation identity detected."
            )
        observations_by_id[observation_id] = item
    decisions_by_id: dict[str, Mapping[str, object]] = {}
    for item in decisions:
        decision_id = _recorder_id(item.get("decision_id"))
        if decision_id in decisions_by_id:
            raise CoverageReconciliationError(
                "Duplicate immutable decision identity detected."
            )
        decisions_by_id[decision_id] = item
    instruments = {
        str(item["instrument_identity"]["instrument_identity_fingerprint_sha256"])
        for item in observations
        if isinstance(item.get("instrument_identity"), Mapping)
        and isinstance(item["instrument_identity"].get("instrument_identity_fingerprint_sha256"), str)
        and item["instrument_identity"].get("instrument_identity_fingerprint_sha256")
    }
    science_eligibility_by_instrument: dict[
        str, tuple[Mapping[str, object], Mapping[str, object]]
    ] = {}
    for record in science_eligibility_records:
        material = record.get("science_eligibility")
        fingerprint = record.get("instrument_identity_fingerprint_sha256")
        if (
            not isinstance(material, Mapping)
            or material.get("eligibility_state") != "ELIGIBLE"
            or not isinstance(material.get("commitment_payload_sha256"), str)
            or not isinstance(fingerprint, str)
            or material.get("instrument_identity_fingerprint_sha256") != fingerprint
        ):
            raise CoverageReconciliationError(
                "Science eligibility record is malformed."
            )
        previous = science_eligibility_by_instrument.get(fingerprint)
        if previous is not None and previous[1] != material:
            raise CoverageReconciliationError(
                "One instrument has conflicting Science eligibility records."
            )
        science_eligibility_by_instrument[fingerprint] = (record, material)
    eligible_observations: dict[str, Mapping[str, object]] = {}
    eligibility_hash_by_observation: dict[str, str] = {}
    eligibility_id_by_observation: dict[str, object] = {}
    for observation_id, item in observations_by_id.items():
        commitment = item.get("outcome_eligibility")
        eligibility_id: object = None
        if not isinstance(commitment, Mapping):
            instrument = item.get("instrument_identity")
            fingerprint = (
                instrument.get("instrument_identity_fingerprint_sha256")
                if isinstance(instrument, Mapping)
                else None
            )
            science_entry = (
                science_eligibility_by_instrument.get(str(fingerprint))
                if isinstance(fingerprint, str)
                else None
            )
            if science_entry is not None:
                eligibility_id = science_entry[0].get("eligibility_id")
                commitment = science_entry[1]
        if (
            isinstance(commitment, Mapping)
            and commitment.get("eligibility_state") == "ELIGIBLE"
            and isinstance(commitment.get("commitment_payload_sha256"), str)
            and commitment.get("commitment_payload_sha256")
        ):
            eligible_observations[observation_id] = item
            eligibility_hash_by_observation[observation_id] = str(
                commitment["commitment_payload_sha256"]
            )
            if eligibility_id is not None:
                eligibility_id_by_observation[observation_id] = eligibility_id
    eligible = {
        str(item["instrument_identity"]["instrument_identity_fingerprint_sha256"])
        for item in eligible_observations.values()
        if isinstance(item.get("instrument_identity"), Mapping)
        and isinstance(
            item["instrument_identity"].get(
                "instrument_identity_fingerprint_sha256"
            ),
            str,
        )
        and item["instrument_identity"].get(
            "instrument_identity_fingerprint_sha256"
        )
    }
    eligible_decisions_by_id: dict[str, Mapping[str, object]] = {}
    for decision_id, item in decisions_by_id.items():
        observation_id = _recorder_id(item.get("observation_id"))
        observation = eligible_observations.get(observation_id)
        if observation is None:
            raise CoverageReconciliationError(
                "Decision lacks one exact eligible observation parent."
            )
        commitment = eligibility_hash_by_observation[observation_id]
        candidate_mismatch = (
            item.get("candidate_or_setup_identity")
            != observation.get("candidate_or_setup_identity")
        )
        science_link = item.get("science_eligibility_commitment_sha256")
        if science_link is not None:
            linkage_mismatch = (
                science_link != commitment
                or item.get("science_eligibility_id")
                != eligibility_id_by_observation.get(observation_id)
            )
        else:
            linkage_mismatch = (
                item.get("outcome_eligibility_commitment_sha256") != commitment
            )
        if candidate_mismatch or linkage_mismatch:
            raise CoverageReconciliationError(
                "Decision does not exactly bind its eligible observation."
            )
        eligible_decisions_by_id[decision_id] = item
    eligible_decisions = tuple(eligible_decisions_by_id.values())
    decision_ids = set(eligible_decisions_by_id)
    unique_slots: dict[tuple[str, str, str, str, str], Mapping[str, object]] = {}
    decision_horizons: dict[tuple[str, str], Mapping[str, object]] = {}
    for item in outcomes:
        target = item.get("target_time")
        target_text = (
            str(target.get("normalized_rfc3339"))
            if isinstance(target, Mapping) and target.get("state") == "PRESENT"
            else str(target.get("reason_code", "")) if isinstance(target, Mapping) else ""
        )
        slot = (
            _recorder_id(item.get("decision_id")),
            str(item.get("outcome_semantic", "")),
            str(item.get("outcome_semantic_version", "")),
            target_text,
            str(item.get("transform_version", "")),
        )
        if not slot[0] or slot[1] not in HORIZONS:
            continue
        decision = eligible_decisions_by_id.get(slot[0])
        if decision is None:
            raise CoverageReconciliationError(
                "Outcome lacks one exact eligible decision parent."
            )
        observation_id = _recorder_id(decision.get("observation_id"))
        observation = eligible_observations[observation_id]
        if (
            item.get("observation_id") != decision.get("observation_id")
            or item.get("candidate_or_setup_identity")
            != decision.get("candidate_or_setup_identity")
            or item.get("eligibility_commitment_sha256")
            != eligibility_hash_by_observation[observation_id]
        ):
            raise CoverageReconciliationError(
                "Outcome does not exactly bind its decision and observation parents."
            )
        if slot in unique_slots:
            raise CoverageReconciliationError("Duplicate immutable outcome slot detected.")
        decision_horizon = (slot[0], slot[1])
        if decision_horizon in decision_horizons:
            raise CoverageReconciliationError("More than one outcome identity occupies one decision/horizon slot.")
        unique_slots[slot] = item
        decision_horizons[decision_horizon] = item
    received_items = {
        key: item for key, item in decision_horizons.items() if key[0] in decision_ids
    }
    accounted_items = {
        key: item
        for key, item in received_items.items()
        if item.get("outcome_state") == "PRESENT"
        or item.get("outcome_state") in TERMINAL_OUTCOME_STATES
    }
    received = len(received_items)
    accounted = len(accounted_items)
    usable = sum(
        1 for item in accounted_items.values()
        if item.get("outcome_state") == "PRESENT"
        and isinstance(item.get("outcome_value"), Mapping)
        and item["outcome_value"].get("state") == "PRESENT"
    )
    terminal = sum(
        1
        for item in accounted_items.values()
        if item.get("outcome_state") in TERMINAL_OUTCOME_STATES
    )
    expected = len(decision_ids) * len(HORIZONS)
    accounting = _ratio(accounted, expected)
    usable_rate = _ratio(usable, expected)
    by_horizon: dict[str, Mapping[str, object]] = {}
    for horizon in HORIZONS:
        horizon_received = {
            decision_id: item
            for (decision_id, semantic), item in received_items.items()
            if semantic == horizon
        }
        horizon_items = {
            decision_id: item
            for decision_id, item in horizon_received.items()
            if item.get("outcome_state") == "PRESENT"
            or item.get("outcome_state") in TERMINAL_OUTCOME_STATES
        }
        present_count = sum(1 for item in horizon_items.values() if item.get("outcome_state") == "PRESENT")
        metric = _ratio(present_count, len(decision_ids))
        metric["received_slots"] = len(horizon_received)
        metric["accounted_slots"] = len(horizon_items)
        metric["nonterminal_slots"] = len(horizon_received) - len(horizon_items)
        metric["terminal_gap_slots"] = sum(
            1
            for item in horizon_items.values()
            if item.get("outcome_state") in TERMINAL_OUTCOME_STATES
        )
        metric["unaccounted_slots"] = len(decision_ids) - len(horizon_items)
        by_horizon[horizon] = metric

    rows_declared = sum(
        item["returned_row_count"] for item in cycles
        if isinstance(item.get("returned_row_count"), int) and not isinstance(item.get("returned_row_count"), bool)
    )
    observation_ids = {_recorder_id(item.get("observation_id")) for item in observations}
    observation_ids.discard("")
    observation_count = len(observation_ids)
    metrics: dict[str, Mapping[str, object]] = {
        "DISCOVERY_CYCLE_COVERAGE": _not_proven("Natural source attempt denominator is not declared by this offline input profile."),
        "DENOMINATOR_ROW_COVERAGE": _ratio(observation_count, rows_declared),
        "DECISION_IDENTITY_COVERAGE": _not_proven("Producing-owner total material-decision denominator is not declared."),
        "QUOTE_SNAPSHOT_COVERAGE": _not_proven("Producing-owner quote applicability and total denominator are not declared."),
        "SCORE_COVERAGE": _not_proven("Producing-owner score applicability and total denominator are not declared."),
        "CATALYST_IDENTITY_COVERAGE": _not_proven("Catalyst applicability denominator is owner-defined and unavailable."),
        "REFERENCE_LEVEL_COVERAGE": _not_proven("Producing-owner reference-level applicability and total denominator are not declared."),
        "OUTCOME_ELIGIBILITY_ACCOUNTING_COVERAGE": _ratio(len(eligible), len(instruments)),
        "OUTCOME_ATTEMPT_OR_GAP_RECEIPT_COVERAGE": accounting,
        "OUTCOME_ELIGIBLE_SYMBOL_COVERAGE": _not_proven("Full usable path by eligible instrument is not implemented by the bounded kernel."),
        "OUTCOME_ELIGIBLE_DECISION_COVERAGE": usable_rate,
        "OUTCOME_HORIZON_COVERAGE": {"by_horizon": by_horizon, "denominator": expected, "numerator": usable, "state": "AVAILABLE" if expected else "NOT_APPLICABLE"},
        "KNOWN_AT_COVERAGE": _not_proven("Producing-owner known-at applicability and total denominator are not declared."),
        "RESTART_RECOVERY_SUCCESS": _not_proven("Natural process/reboot/outage qualification attempts are external to a session corpus."),
        "RECEIPT_CHAIN_VERIFICATION": _not_proven("Final verifier reports custody-chain validity outside pure coverage derivation."),
        "RECORDER_LAG": _not_proven("Cross-clock natural producer lag qualification is not established offline."),
    }
    if tuple(metrics) != METRIC_IDS:
        raise CoverageReconciliationError("Coverage view does not define all predecessor metrics.")
    return CoverageSummary(
        discovery_cycles=len(cycles), returned_rows_declared=rows_declared,
        candidate_observations=observation_count, unique_instruments=len(instruments),
        eligible_instruments=len(eligible), material_decisions=len(decision_ids),
        expected_outcome_slots=expected, received_outcome_slots=received,
        accounted_outcome_slots=accounted,
        nonterminal_outcome_slots=received - accounted,
        unaccounted_outcome_slots=max(0, expected - accounted), usable_outcome_slots=usable,
        terminal_gap_slots=terminal, outcome_accounting_rate_ppm=int(accounting["rate_ppm"]),
        outcome_accounting_rate_state=str(accounting["state"]),
        usable_outcome_rate_ppm=int(usable_rate["rate_ppm"]),
        usable_outcome_rate_state=str(usable_rate["state"]), by_horizon=by_horizon,
        metrics=metrics, conflicts=int(conflicts),
    )


__all__ = ["CoverageReconciliationError", "CoverageSummary", "METRIC_IDS", "derive_coverage"]
