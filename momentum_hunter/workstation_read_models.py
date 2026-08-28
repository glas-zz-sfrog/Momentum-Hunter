from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from momentum_hunter.active_monitor import ACTIVE_MONITOR_STATUS_PATH, load_active_monitor_status
from momentum_hunter.candidate_lifecycle import (
    CandidateLifecycleError,
    CandidateLifecycleStore,
    ENTRY_MISSED,
    EXECUTION_ELIGIBLE,
    FAILED_BREAKOUT,
    INVALIDATED,
    expected_opportunity_id,
)
from momentum_hunter.config import DATA_DIR
from momentum_hunter.continuous_tradeplan_producer import (
    ContinuousTradePlanProducerError,
    ContinuousTradePlanProducerStore,
)
from momentum_hunter.hot_universe import HotUniverseError, HotUniverseStore, TRACKED
from momentum_hunter.monitor_targets import latest_trade_report_path
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH
from momentum_hunter.workstation_charts import WorkstationChartPaths, WorkstationChartService


WORKSTATION_SNAPSHOT_SCHEMA_VERSION = 3
READ_ONLY_MODE_LABEL = "READ_ONLY_PERSISTED_EVIDENCE"
COMMAND_CENTER_POPULATION_CONTRACT_VERSION = "command-center-populations-v1"
COMMAND_CENTER_CHART_INTERVAL = "15m"
COMMAND_CENTER_CHART_SESSION_COUNT = 2
COMMAND_CENTER_RANKED_LIMIT = 10
COMMAND_CENTER_DISPOSITION_DISPLAY_LIMIT = 5
COMMAND_CENTER_CHART_SYMBOL_LIMIT = 20
COMMAND_CENTER_CHART_POINT_LIMIT = 128
COMMAND_CENTER_EVENT_LIMIT = 100
CONTINUOUS_HOT_UNIVERSE_FAMILY = "CONTINUOUS_HOT_UNIVERSE"
EASTERN_TZ = ZoneInfo("America/New_York")
ACTIVE_ALERT_STATUSES = frozenset({"PENDING_OUTCOME", "ACTIVE"})
ALERT_ROW_LIMIT = 50
OUTCOME_ROW_LIMIT = 100


@dataclass(frozen=True)
class WorkstationReadModelPaths:
    data_dir: Path
    reports_dir: Path
    monitor_status_path: Path
    alerts_path: Path
    continuous_runtime_state_root: Path | None = None

    @classmethod
    def from_data_dir(
        cls,
        data_dir: Path = DATA_DIR,
        *,
        continuous_runtime_state_root: Path | None = None,
    ) -> "WorkstationReadModelPaths":
        return cls(
            data_dir=data_dir,
            reports_dir=data_dir / "reports",
            monitor_status_path=data_dir / ACTIVE_MONITOR_STATUS_PATH.name,
            alerts_path=data_dir / OPPORTUNITY_ALERTS_PATH.name,
            continuous_runtime_state_root=continuous_runtime_state_root,
        )


def build_read_only_workspace_snapshot(
    *,
    paths: WorkstationReadModelPaths | None = None,
    observed_at: datetime | None = None,
    chart_service: WorkstationChartService | None = None,
) -> dict[str, Any]:
    """Return a wire-safe, read-only view of persisted Momentum Hunter evidence.

    This mapper deliberately reads precomputed reports and status files only. It does not
    rescore candidates, recalculate readiness, select replay identities, call providers,
    or write any source artifact.
    """

    paths = paths or WorkstationReadModelPaths.from_data_dir()
    observed_at = as_utc(observed_at or datetime.now(timezone.utc))
    report_path = latest_trade_report_path(paths.reports_dir)
    report_payload = load_json_object(report_path) if report_path else None
    report_metadata = object_value(report_payload, "metadata")
    report_observed_at = parse_timestamp(str(report_metadata.get("generated_at", "")), observed_at)

    candidates: list[dict[str, Any]] = []
    activity: list[dict[str, Any]] = []
    health_components: list[dict[str, Any]] = []
    if report_path is None:
        report_summary = "No persisted trade-planning report is available. Candidate data is unavailable; no fallback data was created."
        health_components.append(health_component("Trade planning report", "Unavailable", report_summary, observed_at))
        activity.append(activity_event(observed_at, "Research", report_summary, "", "Unavailable"))
    elif report_payload is None:
        report_summary = f"The persisted trade-planning report '{report_path.name}' could not be read. Candidate data is unavailable."
        health_components.append(health_component("Trade planning report", "Unavailable", report_summary, observed_at))
        activity.append(activity_event(observed_at, "Research", report_summary, "", "Unavailable"))
    else:
        source_rows = list_value(report_payload, "candidates")
        candidates = [
            candidate_snapshot(item, report_path=report_path, observed_at=report_observed_at)
            for item in source_rows
            if isinstance(item, dict) and str(item.get("symbol", "")).strip()
        ]
        report_summary = (
            f"Read-only persisted trade-planning report '{report_path.name}' loaded with {len(candidates)} candidate(s). "
            "Scores and readiness labels are displayed from the source report without recalculation."
        )
        health_components.append(health_component("Trade planning report", "Healthy", report_summary, report_observed_at))
        activity.append(activity_event(report_observed_at, "Research", report_summary, "", "Healthy"))

    monitor_status = load_active_monitor_status(paths.monitor_status_path)
    if monitor_status is None:
        monitor_summary = "No active-monitor status file is available. Collection state is unavailable."
        health_components.append(health_component("Active monitor", "Unavailable", monitor_summary, observed_at))
        activity.append(activity_event(observed_at, "Monitoring", monitor_summary, "", "Unavailable"))
    else:
        monitor_checked_at = parse_timestamp(monitor_status.updated_at or monitor_status.started_at, observed_at)
        monitor_state = monitor_health_state(monitor_status.state)
        monitor_summary = (
            f"Active monitor {monitor_status.state or 'UNKNOWN'}: "
            f"{monitor_status.cycles_completed}/{monitor_status.cycles_requested} cycle(s) completed."
        )
        if monitor_status.last_error:
            monitor_summary = f"{monitor_summary} Last error: {monitor_status.last_error}"
        if monitor_status.warnings:
            monitor_summary = f"{monitor_summary} Warnings: {'; '.join(monitor_status.warnings[:2])}"
        health_components.append(health_component("Active monitor", monitor_state, monitor_summary, monitor_checked_at))
        activity.append(activity_event(monitor_checked_at, "Monitoring", monitor_summary, "", monitor_state))

    alerts_payload = load_json_object(paths.alerts_path)
    if alerts_payload is None:
        alerts_summary = "No readable opportunity-alert store is available. Evidence alert counts are unavailable."
        alert_evidence = unavailable_alert_evidence(alerts_summary, observed_at)
        health_components.append(health_component("Evidence alerts", "Unavailable", alerts_summary, observed_at))
        activity.append(activity_event(observed_at, "Evidence", alerts_summary, "", "Unavailable"))
    elif not isinstance(alerts_payload.get("alerts"), list) or any(
        not isinstance(item, dict) for item in alerts_payload["alerts"]
    ):
        alerts_checked_at = file_timestamp(paths.alerts_path, observed_at)
        alerts_summary = (
            "The opportunity-alert store is readable, but its alerts collection is structurally invalid. "
            "Evidence alert counts and rows are unavailable."
        )
        alert_evidence = unavailable_alert_evidence(alerts_summary, alerts_checked_at)
        health_components.append(health_component("Evidence alerts", "Unavailable", alerts_summary, alerts_checked_at))
        activity.append(activity_event(alerts_checked_at, "Evidence", alerts_summary, "", "Unavailable"))
    else:
        alerts = alerts_payload["alerts"]
        active_alerts = [
            alert
            for alert in alerts
            if alert_outcome_status(alert) in ACTIVE_ALERT_STATUSES
        ]
        alerts_summary = f"Read-only alert store contains {len(alerts)} alert(s), including {len(active_alerts)} active or pending outcome(s)."
        alerts_checked_at = file_timestamp(paths.alerts_path, observed_at)
        alert_evidence = build_alert_evidence_snapshot(alerts, alerts_checked_at)
        health_components.append(health_component("Evidence alerts", "Healthy", alerts_summary, alerts_checked_at))
        activity.append(activity_event(alerts_checked_at, "Evidence", alerts_summary, "", "Healthy"))

    replay = replay_snapshot(report_metadata, report_path, report_observed_at)
    replay_health = "Healthy" if report_payload is not None else "Unavailable"
    health_components.append(health_component("Replay context", replay_health, replay["summary"], report_observed_at))

    command_center = build_command_center_snapshot(
        paths=paths,
        observed_at=observed_at,
        report_path=report_path,
        report_payload=report_payload,
        report_observed_at=report_observed_at,
        chart_service=chart_service,
    )
    snapshot_summary = (
        "Read-only Python evidence snapshot with a bounded Command Center projection. "
        "Ranking, lifecycle, stored history, risk, broker, order, and execution authority remain source-owned."
    )
    return {
        "schemaVersion": WORKSTATION_SNAPSHOT_SCHEMA_VERSION,
        "mode": READ_ONLY_MODE_LABEL,
        "observedAt": timestamp_text(observed_at),
        "summary": snapshot_summary,
        "candidates": candidates,
        "activity": activity,
        "health": {
            "checkedAt": timestamp_text(observed_at),
            "components": health_components,
        },
        "alertEvidence": alert_evidence,
        "replay": replay,
        "commandCenter": command_center,
        "planningAvailable": False,
    }


def build_command_center_snapshot(
    *,
    paths: WorkstationReadModelPaths,
    observed_at: datetime,
    report_path: Path | None,
    report_payload: dict[str, Any] | None,
    report_observed_at: datetime,
    chart_service: WorkstationChartService | None,
) -> dict[str, Any]:
    """Project source-owned Command Center facts without creating machine policy."""

    limitations: list[str] = []
    source_identities: dict[str, str] = {}
    report_rows = [
        item
        for item in list_value(report_payload, "candidates")
        if isinstance(item, dict) and str(item.get("symbol", "")).strip()
    ]
    report_session_date = report_source_session_date(object_value(report_payload, "metadata"))
    report_source_identity = file_sha256(report_path) if report_path else ""
    if report_source_identity:
        source_identities["tradePlanningReport"] = report_source_identity

    population = load_command_center_populations(paths, observed_at=observed_at)
    limitations.extend(population["limitations"])
    source_identities.update(population["sourceIdentities"])
    session_date = str(population["sessionDate"])

    ranked_candidates = build_ranked_candidates(
        report_rows,
        report_path=report_path,
        report_session_date=report_session_date,
        report_source_identity=report_source_identity,
        population_session_date=session_date,
        radar_members=population["radarMembers"],
        accepted=population["acceptedDispositions"],
        rejected=population["rejectedDispositions"],
        latest_state_changes=population["latestStateChanges"],
        limitations=limitations,
    )
    ranked_coverage_state = (
        "UNAVAILABLE"
        if report_payload is None
        else "PARTIAL"
        if any(item.get("score") is None for item in ranked_candidates)
        else "AVAILABLE"
    )

    chart_symbols = bounded_chart_symbols(
        ranked_candidates,
        population["acceptedDispositions"],
        population["rejectedDispositions"],
    )
    safe_chart_service = chart_service or WorkstationChartService(
        paths=WorkstationChartPaths(
            schwab_candle_store_root=paths.data_dir / "schwab-candles-v1",
            schwab_daily_candle_store_root=paths.data_dir / "schwab-daily-candles-v1",
        ),
        max_candles=360,
        backfill_coordinator=None,
    )
    mini_charts = {
        symbol: command_center_mini_chart(
            safe_chart_service.snapshot(symbol, COMMAND_CENTER_CHART_INTERVAL, observed_at=observed_at),
            observed_at=observed_at,
        )
        for symbol in chart_symbols
    }
    chart_states = {str(item.get("state", "UNAVAILABLE")) for item in mini_charts.values()}
    if not mini_charts or chart_states == {"UNAVAILABLE"}:
        chart_coverage_state = "UNAVAILABLE"
    elif chart_states == {"AVAILABLE"}:
        chart_coverage_state = "AVAILABLE"
    else:
        chart_coverage_state = "PARTIAL"
    unavailable_chart_count = sum(
        1 for item in mini_charts.values() if item.get("state") == "UNAVAILABLE"
    )
    partial_chart_count = sum(
        1 for item in mini_charts.values() if item.get("state") == "PARTIAL"
    )
    if unavailable_chart_count or partial_chart_count:
        limitations.append(
            f"Stored 15m history is partial for {partial_chart_count} and unavailable for {unavailable_chart_count} bounded symbol(s)."
        )

    if report_payload is None:
        limitations.append("Ranked candidate source is unavailable; no candidate rows were inferred.")
    elif not report_session_date:
        limitations.append("Trade-planning report session identity is unavailable; lifecycle context joins were disabled.")
    elif session_date and report_session_date != session_date:
        limitations.append(
            f"Trade-planning report session {report_session_date} does not match lifecycle session {session_date}; context joins were disabled."
        )

    source_states = [
        population["radarState"],
        population["acceptedState"],
        population["rejectedState"],
        ranked_coverage_state,
        chart_coverage_state,
    ]
    projection_state = (
        "UNAVAILABLE"
        if all(item == "UNAVAILABLE" for item in source_states)
        else "PARTIAL"
        if any(item != "AVAILABLE" for item in source_states) or limitations
        else "AVAILABLE"
    )
    return {
        "observedAt": timestamp_text(observed_at),
        "sessionDate": session_date,
        "projectionState": projection_state,
        "sourceCoverage": {
            "radar": population["radarState"],
            "accepted": population["acceptedState"],
            "rejected": population["rejectedState"],
            "rankedCandidates": ranked_coverage_state,
            "miniCharts": chart_coverage_state,
        },
        "limitations": ordered_unique(limitations),
        "populationContractVersion": COMMAND_CENTER_POPULATION_CONTRACT_VERSION,
        "sourceIdentities": source_identities,
        "radarMembers": population["radarMembers"],
        "acceptedDispositions": population["acceptedDispositions"],
        "rejectedDispositions": population["rejectedDispositions"],
        "rankedCandidates": ranked_candidates,
        "lifecycleEvents": population["lifecycleEvents"][:COMMAND_CENTER_EVENT_LIMIT],
        "miniChartsBySymbol": mini_charts,
        "reportObservedAt": timestamp_text(report_observed_at),
        "radarMapGeometryState": "NOT_YET_AUTHORIZED",
    }


def load_command_center_populations(
    paths: WorkstationReadModelPaths,
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "sessionDate": "",
        "radarState": "UNAVAILABLE",
        "acceptedState": "UNAVAILABLE",
        "rejectedState": "UNAVAILABLE",
        "radarMembers": [],
        "acceptedDispositions": [],
        "rejectedDispositions": [],
        "lifecycleEvents": [],
        "latestStateChanges": {},
        "sourceIdentities": {},
        "limitations": [],
    }
    runtime_root = paths.continuous_runtime_state_root
    if runtime_root is None:
        result["limitations"].append(
            "Continuous runtime evidence path is not configured; Radar, Accepted, and Rejected are unavailable."
        )
        return result
    runtime_root = Path(runtime_root).resolve()
    hot_path = runtime_root / "session" / "state" / "hot-universe.json"
    lifecycle_path = (
        runtime_root
        / "session"
        / "state"
        / "continuous-natural-setup"
        / "candidate-lifecycle.json"
    )
    producer_path = (
        runtime_root
        / "session"
        / "state"
        / "continuous-tradeplan-producer.json"
    )
    if not hot_path.is_file():
        result["limitations"].append(
            f"Hot Universe evidence is missing at the configured read-only runtime root ({hot_path.name}); lifecycle populations are unavailable."
        )
        return result
    try:
        hot_state = HotUniverseStore(hot_path, allow_persistent=True).load()
    except (HotUniverseError, OSError, ValueError) as exc:
        result["limitations"].append(
            f"Hot Universe evidence is unreadable or untrusted: {type(exc).__name__}; lifecycle populations are unavailable."
        )
        return result
    session_date = str(hot_state.current_session_date).strip()
    if not session_date:
        result["limitations"].append(
            "Hot Universe has no authoritative current session; lifecycle populations are unavailable."
        )
        return result
    result["sessionDate"] = session_date
    result["sourceIdentities"]["hotUniverse"] = hot_state.fingerprint
    session_members = {
        item.member_id: item
        for item in hot_state.members
        if item.session_date == session_date
    }
    members_by_lifecycle_opportunity = {
        expected_opportunity_id(
            item.symbol,
            item.session_date,
            CONTINUOUS_HOT_UNIVERSE_FAMILY,
        ): item
        for item in session_members.values()
    }
    radar_members = [
        {
            "radarPresentationIdentity": item.member_id,
            "membershipGeneration": item.membership_generation,
            "derivedLifecycleOpportunityId": expected_opportunity_id(
                item.symbol,
                item.session_date,
                CONTINUOUS_HOT_UNIVERSE_FAMILY,
            ),
            "symbol": item.symbol,
            "sessionDate": item.session_date,
            "firstSurfacedAt": optional_timestamp_text(item.first_observed_at),
            "lastObservedAt": optional_timestamp_text(item.last_observed_at),
            "currentState": item.current_state,
            "currentTier": item.current_tier,
            "sourceSnapshotIdentity": item.latest_discovery_snapshot_id,
            "dataLineage": f"Validated Hot Universe {hot_state.profile}; member fingerprint {item.fingerprint}.",
        }
        for item in session_members.values()
        if item.current_state == TRACKED
    ]
    result["radarMembers"] = sorted(radar_members, key=lambda item: (item["symbol"], item["radarPresentationIdentity"]))
    result["radarState"] = "AVAILABLE"

    if not lifecycle_path.is_file():
        result["limitations"].append(
            "Candidate Lifecycle evidence is missing; Radar remains available while Accepted and Rejected are unavailable."
        )
        return result
    try:
        ledger = CandidateLifecycleStore(lifecycle_path).load()
    except (CandidateLifecycleError, OSError, ValueError) as exc:
        result["limitations"].append(
            f"Candidate Lifecycle evidence is unreadable or untrusted: {type(exc).__name__}; Accepted and Rejected are unavailable."
        )
        return result
    result["sourceIdentities"]["candidateLifecycle"] = file_sha256(lifecycle_path)
    if producer_path.is_file():
        try:
            producer_records = ContinuousTradePlanProducerStore(producer_path).load()
            _, producer_limitations = producer_setup_corroboration(
                producer_records,
                session_date=session_date,
                members_by_id=session_members,
            )
        except (ContinuousTradePlanProducerError, OSError, ValueError) as exc:
            result["limitations"].append(
                f"Continuous Producer evidence is unreadable or untrusted: {type(exc).__name__}; setup dispositions are unavailable."
            )
            return result
        result["sourceIdentities"]["continuousProducer"] = file_sha256(producer_path)
        if producer_limitations:
            result["limitations"].extend(producer_limitations)
            return result
    accepted_by_setup: dict[tuple[str, str], dict[str, Any]] = {}
    rejected_by_setup: dict[tuple[str, str], dict[str, Any]] = {}
    latest_state_changes: dict[str, str] = {}
    lifecycle_events: list[dict[str, Any]] = []
    lifecycle_limitations: list[str] = []
    rejected_states = {ENTRY_MISSED, FAILED_BREAKOUT, INVALIDATED}
    session_symbols = {item.symbol for item in session_members.values()}
    for event in ledger.events:
        if event.session_date != session_date:
            continue
        if event.originating_evidence_family != CONTINUOUS_HOT_UNIVERSE_FAMILY:
            if event.symbol in session_symbols:
                lifecycle_limitations.append(
                    f"Lifecycle event {event.event_id} for a current-session Hot Universe symbol has a non-authoritative originating family."
                )
            continue
        member = members_by_lifecycle_opportunity.get(event.opportunity_id)
        if member is None:
            lifecycle_limitations.append(
                f"Lifecycle event {event.event_id} does not match the deterministic current-session Hot Universe opportunity identity."
            )
            continue
        if event.symbol != member.symbol:
            lifecycle_limitations.append(
                f"Lifecycle event {event.event_id} symbol does not match its Hot Universe member."
            )
            continue
        if event.previous_state == event.next_state:
            continue
        occurred_at = optional_timestamp_text(event.occurred_at)
        if occurred_at:
            latest_state_changes[event.opportunity_id] = occurred_at
        lifecycle_events.append(
            {
                "eventIdentity": event.event_id,
                "sourceKind": "CANDIDATE_LIFECYCLE",
                "symbol": event.symbol,
                "occurredAt": occurred_at,
                "previousState": event.previous_state,
                "nextState": event.next_state,
                "reason": event.reason,
                "opportunityId": event.opportunity_id,
                "radarMemberIdentity": None,
                "derivedLifecycleOpportunityId": None,
                "setupId": event.setup_id,
            }
        )
        if event.next_state not in rejected_states | {EXECUTION_ELIGIBLE}:
            continue
        if not event.setup_id:
            lifecycle_limitations.append(
                f"Qualifying lifecycle event {event.event_id} has no setup identity."
            )
            continue
        key = (event.opportunity_id, event.setup_id)
        # Producer evidence is corroborative only.  A validated direct lifecycle
        # transition may have no producer proposal; when a proposal exists, the
        # helper above has already required exact identity agreement.
        if event.next_state == EXECUTION_ELIGIBLE and key not in accepted_by_setup:
            accepted_by_setup[key] = disposition_snapshot(event, "ACCEPTED")
        if event.next_state in rejected_states and key not in rejected_by_setup:
            rejected_by_setup[key] = disposition_snapshot(event, "REJECTED")

    for transition in hot_state.transitions:
        if transition.session_date != session_date:
            continue
        lifecycle_events.append(
            {
                "eventIdentity": transition.transition_id,
                "sourceKind": "HOT_UNIVERSE",
                "symbol": transition.symbol,
                "occurredAt": optional_timestamp_text(transition.recorded_at),
                "previousState": transition.previous_state,
                "nextState": transition.next_state,
                "reason": transition.reason,
                "opportunityId": "",
                "radarMemberIdentity": transition.member_id,
                "derivedLifecycleOpportunityId": expected_opportunity_id(
                    transition.symbol,
                    transition.session_date,
                    CONTINUOUS_HOT_UNIVERSE_FAMILY,
                ),
                "setupId": "",
            }
        )
    if lifecycle_limitations:
        result["limitations"].extend(lifecycle_limitations)
        return result
    result["acceptedDispositions"] = sorted(
        accepted_by_setup.values(),
        key=lambda item: (item["occurredAt"] or "", item["dispositionEventId"]),
        reverse=True,
    )
    result["rejectedDispositions"] = sorted(
        rejected_by_setup.values(),
        key=lambda item: (item["occurredAt"] or "", item["dispositionEventId"]),
        reverse=True,
    )
    result["lifecycleEvents"] = sorted(
        lifecycle_events,
        key=lambda item: (item["occurredAt"] or "", item["eventIdentity"]),
        reverse=True,
    )
    result["latestStateChanges"] = latest_state_changes
    result["acceptedState"] = "AVAILABLE"
    result["rejectedState"] = "AVAILABLE"
    return result


def producer_setup_corroboration(
    records: tuple[Any, ...],
    *,
    session_date: str,
    members_by_id: dict[str, Any],
) -> tuple[set[tuple[str, str]], list[str]]:
    """Validate optional setup-bearing producer proposals without making them authoritative."""

    corroborated: set[tuple[str, str]] = set()
    limitations: list[str] = []
    for record in records:
        if record.session_date != session_date:
            continue
        try:
            payload = json.loads(record.payload_json)
        except (TypeError, json.JSONDecodeError):
            limitations.append(
                f"Producer record {record.record_id} has an unreadable embedded payload."
            )
            continue
        cycle = payload.get("compositionCycle") if isinstance(payload, dict) else None
        member_results = cycle.get("member_results") if isinstance(cycle, dict) else None
        if not isinstance(member_results, list):
            limitations.append(
                f"Producer record {record.record_id} has no valid embedded member-result collection."
            )
            continue
        matching = [
            item
            for item in member_results
            if isinstance(item, dict)
            and item.get("universe_member_id") == record.member_id
        ]
        proposals = [
            item.get("lifecycle_proposal")
            for item in matching
            if isinstance(item.get("lifecycle_proposal"), dict)
            and str(item["lifecycle_proposal"].get("setup_id", "")).strip()
        ]
        if not record.setup_id and not proposals:
            # Direct/no-change producer records intentionally have no proposal.
            continue
        if len(matching) != 1 or len(proposals) != 1:
            limitations.append(
                f"Producer record {record.record_id} does not contain exactly one setup-bearing result for its member identity."
            )
            continue
        proposal = proposals[0]
        member = members_by_id.get(record.member_id)
        if member is None:
            limitations.append(
                f"Producer record {record.record_id} references no authoritative current-session Hot Universe membership."
            )
            continue
        derived_opportunity = expected_opportunity_id(
            member.symbol,
            member.session_date,
            CONTINUOUS_HOT_UNIVERSE_FAMILY,
        )
        result = matching[0]
        exact = (
            record.symbol == member.symbol
            and record.session_date == member.session_date
            and record.setup_id == str(proposal.get("setup_id", ""))
            and str(result.get("symbol", "")) == member.symbol
            and str(result.get("session_date", "")) == member.session_date
            and str(proposal.get("opportunity_id", "")) == derived_opportunity
            and str(proposal.get("symbol", "")) == member.symbol
            and str(proposal.get("session_date", "")) == member.session_date
            and str(proposal.get("setup_id", "")) == record.setup_id
        )
        if not exact:
            limitations.append(
                f"Producer record {record.record_id} contradicts its member, setup, or deterministically derived lifecycle identity."
            )
            continue
        corroborated.add((derived_opportunity, record.setup_id))
    return corroborated, limitations


def disposition_snapshot(event: Any, kind: str) -> dict[str, Any]:
    identity = "|".join((event.session_date, event.opportunity_id, event.setup_id, kind))
    return {
        "dispositionPresentationIdentity": identity,
        "dispositionEventId": event.event_id,
        "kind": kind,
        "opportunityId": event.opportunity_id,
        "setupId": event.setup_id,
        "setupFamily": event.setup_family,
        "setupSequence": event.setup_sequence,
        "symbol": event.symbol,
        "sessionDate": event.session_date,
        "previousState": event.previous_state,
        "reachedState": event.next_state,
        "occurredAt": optional_timestamp_text(event.occurred_at),
        "reason": event.reason,
        "sourceIdentity": event.source_identity,
        "evidenceFingerprint": event.evidence_fingerprint,
        "dataLineage": f"First qualifying {kind.lower()} transition retained from Candidate Lifecycle event {event.event_id}.",
    }


def build_ranked_candidates(
    report_rows: list[dict[str, Any]],
    *,
    report_path: Path | None,
    report_session_date: str,
    report_source_identity: str,
    population_session_date: str,
    radar_members: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    latest_state_changes: dict[str, str],
    limitations: list[str],
) -> list[dict[str, Any]]:
    radar_by_symbol = group_by_symbol(radar_members)
    accepted_by_symbol = group_by_symbol(accepted)
    rejected_by_symbol = group_by_symbol(rejected)
    same_session = bool(report_session_date and report_session_date == population_session_date)
    ranked: list[dict[str, Any]] = []
    seen_ranks: set[int] = set()
    seen_symbols: set[str] = set()
    for row in report_rows:
        symbol = str(row.get("symbol", "")).strip().upper()
        source_rank = integer_or_none(row.get("rank"))
        if source_rank is None or source_rank <= 0 or source_rank in seen_ranks:
            limitations.append(f"Ranked report row {symbol or 'UNKNOWN'} has a missing, invalid, or duplicate source rank and was not projected.")
            continue
        if symbol in seen_symbols:
            limitations.append(f"Ranked report contains duplicate symbol {symbol}; lifecycle context join is unavailable for that symbol.")
        seen_ranks.add(source_rank)
        seen_symbols.add(symbol)
        scoring = object_value(row, "scoring")
        score = integer_or_none(scoring.get("composite_score"))
        if score is None:
            limitations.append(
                f"Ranked report row {symbol} has no valid source composite score; score remains unavailable."
            )
        market_data = object_value(row, "market_data")
        trade_plan = object_value(row, "trade_plan")
        radar = radar_by_symbol.get(symbol, []) if same_session else []
        accepted_rows = accepted_by_symbol.get(symbol, []) if same_session else []
        rejected_rows = rejected_by_symbol.get(symbol, []) if same_session else []
        radar_identity = radar[0]["radarPresentationIdentity"] if len(radar) == 1 else None
        opportunity_id = radar[0]["derivedLifecycleOpportunityId"] if len(radar) == 1 else None
        first_surfaced_at = radar[0]["firstSurfacedAt"] if len(radar) == 1 else None
        raw_state = radar[0]["currentState"] if len(radar) == 1 else None
        ranked.append(
            {
                "stableCandidateIdentity": stable_hash(report_source_identity or str(report_path or ""), str(source_rank), symbol),
                "symbol": symbol,
                "company": str(row.get("company", "")).strip() or "Company unavailable",
                "sourceRank": source_rank,
                "score": score,
                "relativeVolume": number_or_none(market_data.get("relative_volume")),
                "lastPrice": number_or_none(market_data.get("last_price")),
                "changePercent": number_or_none(market_data.get("premarket_percent")),
                "catalystSummary": str(scoring.get("catalyst_summary", "")).strip() or "Catalyst unavailable",
                "radarMemberIdentity": radar_identity,
                "acceptedDispositionIds": [item["dispositionPresentationIdentity"] for item in accepted_rows],
                "rejectedDispositionIds": [item["dispositionPresentationIdentity"] for item in rejected_rows],
                "rawMachineState": raw_state,
                "displayFirstSurfacedAt": first_surfaced_at,
                "displayStateChangedAt": latest_state_changes.get(str(opportunity_id or "")),
                "dataLineage": f"Source-ranked persisted report row from {report_path.name if report_path else 'unavailable report'}; no WPF reranking.",
                "sourceIdentity": report_source_identity,
                "miniChartSymbolKey": symbol,
                "hypotheticalEntry": first_number(trade_plan, "bullish_entry", "entry"),
                "hypotheticalStop": first_number(trade_plan, "bullish_stop", "stop"),
                "hypotheticalTarget": first_number(trade_plan, "bullish_target_1", "target"),
            }
        )
    return sorted(ranked, key=lambda item: item["sourceRank"])


def bounded_chart_symbols(
    ranked: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> list[str]:
    requested = [item["symbol"] for item in ranked[:COMMAND_CENTER_RANKED_LIMIT]]
    requested.extend(item["symbol"] for item in accepted[:COMMAND_CENTER_DISPOSITION_DISPLAY_LIMIT])
    requested.extend(item["symbol"] for item in rejected[:COMMAND_CENTER_DISPOSITION_DISPLAY_LIMIT])
    return ordered_unique(requested)[:COMMAND_CENTER_CHART_SYMBOL_LIMIT]


def command_center_mini_chart(snapshot: dict[str, Any], *, observed_at: datetime) -> dict[str, Any]:
    symbol = str(snapshot.get("symbol", "")).strip().upper()
    candles = [item for item in list_value(snapshot, "candles") if isinstance(item, dict)]
    source_dates = sorted({str(item.get("sessionDate", "")) for item in candles if str(item.get("sessionDate", ""))})
    selected_dates = source_dates[-COMMAND_CENTER_CHART_SESSION_COUNT:]
    selected = [item for item in candles if str(item.get("sessionDate", "")) in selected_dates]
    selected = selected[-COMMAND_CENTER_CHART_POINT_LIMIT:]
    quality = object_value(snapshot, "quality")
    points = [
        {
            "timestamp": optional_timestamp_text(item.get("timestamp")),
            "close": number_or_none(item.get("close")),
        }
        for item in selected
        if optional_timestamp_text(item.get("timestamp")) is not None
        and number_or_none(item.get("close")) is not None
    ]
    source_state = str(snapshot.get("state", "UNAVAILABLE")).strip().upper()
    gap_count = integer_or_none(quality.get("gapCount")) or 0
    correction_count = integer_or_none(quality.get("correctionCount")) or 0
    findings = [str(item) for item in list_value(quality, "findings")]
    if not points:
        state = "UNAVAILABLE"
        limitation = str(snapshot.get("summary", "No stored 15m history is available."))
    elif len(selected_dates) < COMMAND_CENTER_CHART_SESSION_COUNT or source_state != "AVAILABLE" or gap_count:
        state = "PARTIAL"
        limitation = (
            f"Stored history contains {len(selected_dates)} of {COMMAND_CENTER_CHART_SESSION_COUNT} requested source sessions; "
            f"source state {source_state}, gaps {gap_count}."
        )
    else:
        state = "AVAILABLE"
        limitation = ""
    lineage = object_value(snapshot, "lineage")
    return {
        "state": state,
        "symbol": symbol,
        "interval": COMMAND_CENTER_CHART_INTERVAL,
        "requestedSessionCount": COMMAND_CENTER_CHART_SESSION_COUNT,
        "sourceSessionDates": selected_dates,
        "points": points,
        "sourceLabel": str(lineage.get("sourceLabel", "Stored canonical Schwab minute evidence")),
        "asOf": timestamp_text(observed_at),
        "gapCount": gap_count,
        "correctionCount": correction_count,
        "findings": findings,
        "limitation": limitation,
    }


def report_source_session_date(metadata: dict[str, Any]) -> str:
    raw = str(metadata.get("source_capture_time", "")).strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        return ""
    return parsed.astimezone(EASTERN_TZ).date().isoformat()


def group_by_symbol(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        grouped.setdefault(str(item.get("symbol", "")).strip().upper(), []).append(item)
    return grouped


def first_number(payload: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = number_or_none(payload.get(key))
        if value is not None:
            return value
    return None


def file_sha256(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def stable_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def candidate_snapshot(row: dict[str, Any], *, report_path: Path, observed_at: datetime) -> dict[str, Any]:
    market_data = object_value(row, "market_data")
    scoring = object_value(row, "scoring")
    trade_plan = object_value(row, "trade_plan")
    readiness = str(trade_plan.get("readiness", "UNAVAILABLE")).strip() or "UNAVAILABLE"
    last_price = number_or_none(market_data.get("last_price"))
    relative_volume = number_or_none(market_data.get("relative_volume"))
    liquidity = liquidity_summary(market_data)
    quality_parts = ["Persisted report"]
    if last_price is None:
        quality_parts.append("last price unavailable")
    if relative_volume is None:
        quality_parts.append("relative volume unavailable")
    if readiness == "UNAVAILABLE":
        quality_parts.append("readiness unavailable")
    catalyst = str(scoring.get("catalyst_summary", "")).strip() or "No stored catalyst summary"
    lineage = {
        "sourceLabel": "Persisted trade-planning report",
        "asOf": timestamp_text(observed_at),
        "summary": f"Read-only source: {report_path.name}. No score or readiness recalculation occurred.",
    }
    return {
        "symbol": str(row.get("symbol", "")).strip().upper(),
        "company": str(row.get("company", "")).strip() or "Company unavailable",
        "lastPrice": last_price,
        "changePercent": number_or_none(market_data.get("premarket_percent")),
        "volume": integer_or_none(market_data.get("intraday_volume")) or integer_or_none(market_data.get("premarket_volume")),
        "relativeVolume": relative_volume,
        "catalyst": catalyst,
        "sourceReadinessLabel": readiness,
        "qualityLabel": "; ".join(quality_parts),
        "observedAt": timestamp_text(observed_at),
        "score": integer_or_none(scoring.get("composite_score")) or 0,
        "liquidity": liquidity,
        "catalystSummary": {
            "headline": catalyst,
            "sourceLabel": "Persisted trade-planning report",
            "observedAt": timestamp_text(observed_at),
        },
        "dataLineage": lineage,
        "notes": [str(note) for note in list_value(row, "opportunity_notes") if str(note).strip()],
    }


def replay_snapshot(metadata: dict[str, Any], report_path: Path | None, observed_at: datetime) -> dict[str, Any]:
    if report_path is None:
        return {
            "replayId": "UNAVAILABLE",
            "asOf": timestamp_text(observed_at),
            "symbol": "",
            "interval": "source capture",
            "summary": "Replay context is unavailable because no persisted source report is available.",
        }
    source_capture_path = str(metadata.get("source_capture_path", "")).strip()
    source_capture_time = str(metadata.get("source_capture_time", "")).strip()
    return {
        "replayId": "NOT_SELECTED",
        "asOf": timestamp_text(parse_timestamp(source_capture_time, observed_at)),
        "symbol": "",
        "interval": "source capture",
        "summary": (
            f"Replay remains read-only. Source capture: {Path(source_capture_path).name if source_capture_path else 'not recorded'}. "
            "No candidate replay identity was synthesized by the workstation boundary."
        ),
    }


def health_component(name: str, state: str, summary: str, checked_at: datetime) -> dict[str, Any]:
    return {"name": name, "state": state, "summary": summary, "checkedAt": timestamp_text(checked_at)}


def activity_event(timestamp: datetime, category: str, message: str, symbol: str, state: str) -> dict[str, Any]:
    return {
        "timestamp": timestamp_text(timestamp),
        "category": category,
        "message": message,
        "symbol": symbol,
        "state": state,
    }


def unavailable_alert_evidence(summary: str, observed_at: datetime) -> dict[str, Any]:
    return {
        "state": "UNAVAILABLE",
        "asOf": timestamp_text(observed_at),
        "summary": summary,
        "totalAlertCount": 0,
        "activeAlertCount": 0,
        "recordedOutcomeCount": 0,
        "unscorableOutcomeCount": 0,
        "activeAlerts": [],
        "outcomes": [],
    }


def build_alert_evidence_snapshot(alerts: list[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
    ordered = sorted(alerts, key=alert_timestamp_sort_key, reverse=True)
    active = [item for item in ordered if alert_outcome_status(item) in ACTIVE_ALERT_STATUSES]
    outcomes = [item for item in ordered if alert_outcome_status(item) not in ACTIVE_ALERT_STATUSES]
    unscorable_count = sum(
        1
        for item in outcomes
        if alert_outcome_status(item) == "UNSCORABLE_OUTCOME"
        or str(object_value(item, "outcome").get("classification", "")).strip().upper().startswith("UNSCORABLE")
    )
    if not alerts:
        state = "EMPTY"
        summary = (
            "The persisted opportunity-alert store is readable but contains no alerts. "
            "Outcome evidence is insufficient; no analytics or classifications were inferred."
        )
    else:
        state = "AVAILABLE"
        summary = (
            f"Persisted alert evidence: {len(alerts)} total, {len(active)} active or pending, "
            f"{len(outcomes)} recorded outcome(s), {unscorable_count} unscorable. "
            f"Stored alert states and outcome classifications are displayed without recalculation. "
            f"Counts cover the full store; row detail is limited to the newest {ALERT_ROW_LIMIT} active alerts "
            f"and {OUTCOME_ROW_LIMIT} outcomes."
        )
    return {
        "state": state,
        "asOf": timestamp_text(as_of),
        "summary": summary,
        "totalAlertCount": len(alerts),
        "activeAlertCount": len(active),
        "recordedOutcomeCount": len(outcomes),
        "unscorableOutcomeCount": unscorable_count,
        "activeAlerts": [alert_event_snapshot(item) for item in active[:ALERT_ROW_LIMIT]],
        "outcomes": [alert_outcome_snapshot(item) for item in outcomes[:OUTCOME_ROW_LIMIT]],
    }


def alert_event_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    outcome = object_value(item, "outcome")
    return {
        "alertId": str(item.get("alert_id", "")).strip(),
        "timestamp": optional_timestamp_text(item.get("timestamp")),
        "symbol": str(item.get("symbol", "")).strip().upper(),
        "alertType": str(item.get("alert_type", "")).strip(),
        "state": str(item.get("current_state", "")).strip() or str(outcome.get("status", "")).strip() or "UNAVAILABLE",
        "summary": str(item.get("reason", "")).strip() or "No alert reason was recorded.",
    }


def alert_outcome_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    outcome = object_value(item, "outcome")
    status = str(outcome.get("status", "")).strip() or "UNAVAILABLE"
    classification = str(outcome.get("classification", "")).strip() or "UNAVAILABLE"
    return {
        "alertId": str(item.get("alert_id", "")).strip(),
        "symbol": str(item.get("symbol", "")).strip().upper(),
        "alertTimestamp": optional_timestamp_text(item.get("timestamp")),
        "status": status,
        "classification": classification,
        "summary": stored_outcome_summary(outcome, status=status, classification=classification),
    }


def alert_outcome_status(item: dict[str, Any]) -> str:
    return str(object_value(item, "outcome").get("status", "PENDING_OUTCOME")).strip().upper() or "PENDING_OUTCOME"


def alert_timestamp_sort_key(item: dict[str, Any]) -> tuple[bool, str]:
    timestamp = optional_timestamp_text(item.get("timestamp"))
    return timestamp is not None, timestamp or ""


def stored_outcome_summary(outcome: dict[str, Any], *, status: str, classification: str) -> str:
    details = [f"Stored status {status}", f"classification {classification}"]
    for key, label in (
        ("five_minute_return_pct", "5m"),
        ("fifteen_minute_return_pct", "15m"),
        ("thirty_minute_return_pct", "30m"),
        ("sixty_minute_return_pct", "60m"),
        ("mfe_30m_pct", "MFE 30m"),
        ("mae_30m_pct", "MAE 30m"),
    ):
        value = number_or_none(outcome.get(key))
        if value is not None:
            details.append(f"{label} {value:+.2f}%")
    for key, label in (
        ("target_1_hit", "target 1"),
        ("target_2_hit", "target 2"),
        ("stop_hit", "stop"),
    ):
        value = outcome.get(key)
        if isinstance(value, bool):
            details.append(f"{label} {'hit' if value else 'not hit'}")
    return "; ".join(details) + "."


def optional_timestamp_text(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return timestamp_text(datetime.fromisoformat(text.replace("Z", "+00:00")))
    except ValueError:
        return None


def load_json_object(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def object_value(payload: dict[str, Any] | None, key: str) -> dict[str, Any]:
    value = payload.get(key) if payload else None
    return value if isinstance(value, dict) else {}


def list_value(payload: dict[str, Any] | None, key: str) -> list[Any]:
    value = payload.get(key) if payload else None
    return value if isinstance(value, list) else []


def number_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer_or_none(value: object) -> int | None:
    numeric = number_or_none(value)
    return int(numeric) if numeric is not None else None


def liquidity_summary(market_data: dict[str, Any]) -> str:
    details: list[str] = []
    relative_volume = number_or_none(market_data.get("relative_volume"))
    spread_percent = number_or_none(market_data.get("spread_percent"))
    if relative_volume is not None:
        details.append(f"RVOL {relative_volume:.2f}x")
    if spread_percent is not None:
        details.append(f"spread {spread_percent:.2f}%")
    return " | ".join(details) or "Liquidity data unavailable"


def monitor_health_state(state: str) -> str:
    normalized = state.strip().upper()
    if normalized in {"FAILED", "BLOCKED"}:
        return "Degraded"
    if normalized in {"", "UNKNOWN"}:
        return "Unavailable"
    return "Healthy"


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_timestamp(value: str, fallback: datetime) -> datetime:
    if not value.strip():
        return fallback
    try:
        return as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return fallback


def file_timestamp(path: Path, fallback: datetime) -> datetime:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except OSError:
        return fallback


def timestamp_text(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")
