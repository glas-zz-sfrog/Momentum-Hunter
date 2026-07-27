from __future__ import annotations

"""Safety contracts for the Official Shadow opening ceremony."""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


CLOCK_PROOF_SCHEMA_VERSION = 1
CLOCK_PROOF_TYPE = "HTTPS_DATE_CLOCK_SKEW"
MAX_CLOCK_SKEW_MILLISECONDS = 5_000
MAX_CLOCK_PROOF_AGE_SECONDS = 300

SHADOW_HANDOFF_SCHEMA_VERSION = 2
SHADOW_HANDOFF_COMPLETE_STATUSES = frozenset(
    {
        "CYCLE_COMPLETED_NO_TRADE",
        "CYCLE_COMPLETED_TRADE_CREATED",
    }
)
SHADOW_TRADE_TERMINAL_OUTCOMES = frozenset({"TRADE_STARTED"})
SHADOW_NO_TRADE_TERMINAL_OUTCOMES = frozenset(
    {
        "NO_ELIGIBLE_CANDIDATE",
        "REPORT_NOT_PROSPECTIVE",
        "SOURCE_CAPTURE_ALREADY_PROCESSED",
    }
)
SHADOW_IDEMPOTENT_OUTCOME = "REPORT_ALREADY_PROCESSED"
SHADOW_OPENING_AUDIT_SCHEMA_VERSION = 1
SHADOW_OPENING_AUDIT_CATEGORIES = (
    "git_build_identity",
    "scheduled_task_definition",
    "scheduled_task_run",
    "source_capture",
    "tradeplan_report",
    "fresh_quote_proof",
    "clock_skew_proof",
    "frozen_configuration",
    "schwab_account_invariant",
    "selector_arm",
    "decision_cycle_handoff",
    "engine_host_chronology",
)


class ShadowOpeningSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpeningHeartbeatState:
    outcome: str
    reason: str
    retire_heartbeat: bool


@dataclass(frozen=True)
class AuditArtifact:
    name: str
    purpose: str
    required: bool
    status: str
    path: Path | None = None
    not_created_reason: str = ""
    schema_version: int | str = 1
    created_at: str = ""
    manifest_location: str = ""


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ShadowOpeningSafetyError(
            f"{field_name} must include a UTC offset."
        )
    return value


def parse_aware_datetime(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def build_https_clock_skew_proof(
    *,
    request_started_at: datetime,
    response_received_at: datetime,
    remote_date_header: str,
    source_identity: str,
) -> dict[str, object]:
    findings: list[str] = []
    try:
        request_started_at = require_aware_datetime(
            request_started_at,
            "Clock request start",
        )
        response_received_at = require_aware_datetime(
            response_received_at,
            "Clock response time",
        )
    except ShadowOpeningSafetyError as exc:
        findings.append(str(exc))

    remote_at: datetime | None = None
    try:
        remote_at = parsedate_to_datetime(remote_date_header)
    except (TypeError, ValueError, OverflowError):
        findings.append("Trusted HTTPS Date header is missing or invalid.")
    if remote_at is not None and (
        remote_at.tzinfo is None or remote_at.utcoffset() is None
    ):
        findings.append("Trusted HTTPS Date header lacks a UTC offset.")
        remote_at = None

    request_duration_ms: float | None = None
    midpoint: datetime | None = None
    signed_skew_ms: float | None = None
    absolute_skew_ms: float | None = None
    uncertainty_ms: float | None = None
    if not findings:
        request_duration_ms = (
            response_received_at - request_started_at
        ).total_seconds() * 1_000
        if request_duration_ms < 0:
            findings.append(
                "Clock response time precedes the request start."
            )
        else:
            midpoint = request_started_at + (
                response_received_at - request_started_at
            ) / 2
            assert remote_at is not None
            signed_skew_ms = (
                midpoint - remote_at
            ).total_seconds() * 1_000
            absolute_skew_ms = abs(signed_skew_ms)
            # HTTP Date has one-second precision. The full request duration is
            # retained as uncertainty because response-path asymmetry is unknown.
            uncertainty_ms = request_duration_ms + 1_000
            if (
                not math.isfinite(absolute_skew_ms)
                or not math.isfinite(uncertainty_ms)
            ):
                findings.append("Clock measurement is non-finite.")
            elif (
                absolute_skew_ms + uncertainty_ms
                > MAX_CLOCK_SKEW_MILLISECONDS
            ):
                findings.append(
                    "Clock skew plus measurement uncertainty exceeds "
                    f"{MAX_CLOCK_SKEW_MILLISECONDS} milliseconds."
                )

    return {
        "schemaVersion": CLOCK_PROOF_SCHEMA_VERSION,
        "proofType": CLOCK_PROOF_TYPE,
        "status": "PASS" if not findings else "BLOCKED",
        "findings": findings,
        "source": source_identity,
        "requestStartedAt": request_started_at.isoformat(),
        "responseReceivedAt": response_received_at.isoformat(),
        "checkedAt": response_received_at.isoformat(),
        "localMidpointUtc": midpoint.isoformat() if midpoint else None,
        "trustedRemoteUtc": remote_at.isoformat() if remote_at else None,
        "signedSkewMilliseconds": (
            round(signed_skew_ms, 3)
            if signed_skew_ms is not None
            else None
        ),
        "absoluteSkewMilliseconds": (
            round(absolute_skew_ms, 3)
            if absolute_skew_ms is not None
            else None
        ),
        "requestDurationMilliseconds": (
            round(request_duration_ms, 3)
            if request_duration_ms is not None
            else None
        ),
        "measurementUncertaintyMilliseconds": (
            round(uncertainty_ms, 3)
            if uncertainty_ms is not None
            else None
        ),
        "maximumAbsoluteSkewMilliseconds": (
            MAX_CLOCK_SKEW_MILLISECONDS
        ),
    }


def clock_skew_findings(
    proof: object,
    *,
    evaluated_at: datetime,
    maximum_age_seconds: int = MAX_CLOCK_PROOF_AGE_SECONDS,
) -> tuple[str, ...]:
    findings: list[str] = []
    if not isinstance(proof, Mapping):
        return ("Clock-skew proof is missing.",)
    try:
        evaluated_at = require_aware_datetime(
            evaluated_at,
            "Clock-proof evaluation time",
        )
    except ShadowOpeningSafetyError as exc:
        return (str(exc),)

    checked_at = parse_aware_datetime(proof.get("checkedAt"))
    request_started_at = parse_aware_datetime(
        proof.get("requestStartedAt")
    )
    response_received_at = parse_aware_datetime(
        proof.get("responseReceivedAt")
    )
    local_midpoint = parse_aware_datetime(proof.get("localMidpointUtc"))
    trusted_remote = parse_aware_datetime(proof.get("trustedRemoteUtc"))
    signed_skew = finite_number(proof.get("signedSkewMilliseconds"))
    absolute_skew = finite_number(
        proof.get("absoluteSkewMilliseconds")
    )
    request_duration = finite_number(
        proof.get("requestDurationMilliseconds")
    )
    uncertainty = finite_number(
        proof.get("measurementUncertaintyMilliseconds")
    )
    if proof.get("schemaVersion") != CLOCK_PROOF_SCHEMA_VERSION:
        findings.append("Clock-skew proof schema is unsupported.")
    if proof.get("proofType") != CLOCK_PROOF_TYPE:
        findings.append("Clock-skew proof type is invalid.")
    if proof.get("status") != "PASS" or proof.get("findings") != []:
        findings.append("Clock-skew proof did not pass.")
    if not str(proof.get("source", "")).strip():
        findings.append("Clock-skew source identity is missing.")
    if checked_at is None:
        findings.append("Clock-skew proof timestamp is invalid.")
    else:
        age_seconds = (evaluated_at - checked_at).total_seconds()
        if age_seconds < 0:
            findings.append("Clock-skew proof is future-dated.")
        elif age_seconds > maximum_age_seconds:
            findings.append(
                f"Clock-skew proof is older than {maximum_age_seconds} seconds."
            )
    if (
        request_started_at is None
        or response_received_at is None
        or local_midpoint is None
        or trusted_remote is None
    ):
        findings.append("Clock-skew timestamp evidence is incomplete.")
    else:
        expected_duration = (
            response_received_at - request_started_at
        ).total_seconds() * 1_000
        expected_midpoint = request_started_at + (
            response_received_at - request_started_at
        ) / 2
        expected_signed_skew = (
            expected_midpoint - trusted_remote
        ).total_seconds() * 1_000
        if expected_duration < 0:
            findings.append(
                "Clock response time precedes the request start."
            )
        if checked_at != response_received_at:
            findings.append(
                "Clock-skew checked time does not match response receipt."
            )
        if abs((local_midpoint - expected_midpoint).total_seconds()) > 0.001:
            findings.append(
                "Clock-skew midpoint does not match request chronology."
            )
        if (
            request_duration is None
            or abs(request_duration - expected_duration) > 1.0
        ):
            findings.append(
                "Clock-skew request duration does not match chronology."
            )
        if (
            signed_skew is None
            or abs(signed_skew - expected_signed_skew) > 1.0
        ):
            findings.append(
                "Clock-skew signed measurement does not match chronology."
            )
        if (
            absolute_skew is None
            or abs(absolute_skew - abs(expected_signed_skew)) > 1.0
        ):
            findings.append(
                "Clock-skew absolute measurement does not match chronology."
            )
        if (
            uncertainty is None
            or abs(uncertainty - (expected_duration + 1_000)) > 1.0
        ):
            findings.append(
                "Clock-skew uncertainty does not match frozen calculation."
            )
    if (
        signed_skew is None
        or absolute_skew is None
        or request_duration is None
        or uncertainty is None
    ):
        findings.append("Clock-skew measurement is incomplete.")
    elif (
        absolute_skew < 0
        or uncertainty < 0
        or absolute_skew + uncertainty
        > MAX_CLOCK_SKEW_MILLISECONDS
    ):
        findings.append(
            "Clock skew plus uncertainty exceeds the five-second gate."
        )
    if (
        proof.get("maximumAbsoluteSkewMilliseconds")
        != MAX_CLOCK_SKEW_MILLISECONDS
    ):
        findings.append("Clock-skew limit does not match frozen policy.")
    return tuple(dict.fromkeys(findings))


def terminal_selector_outcome(
    selection: Mapping[str, object],
) -> tuple[str, str]:
    status = str(selection.get("status", "")).strip()
    terminal_status = status
    if status == SHADOW_IDEMPOTENT_OUTCOME:
        terminal_status = str(
            selection.get("terminalCycleStatus", "")
        ).strip()
    if terminal_status in SHADOW_TRADE_TERMINAL_OUTCOMES:
        return "CYCLE_COMPLETED_TRADE_CREATED", terminal_status
    if terminal_status in SHADOW_NO_TRADE_TERMINAL_OUTCOMES:
        return "CYCLE_COMPLETED_NO_TRADE", terminal_status
    raise ShadowOpeningSafetyError(
        "Engine Host selection outcome is not an allowed terminal state: "
        f"{terminal_status or status or 'UNKNOWN_OUTCOME'}."
    )


def build_shadow_handoff_receipt(
    *,
    report_path: Path,
    report_sha256: str,
    capture_id: str,
    cycle: object,
    recorded_at: datetime,
) -> dict[str, object]:
    recorded_at = require_aware_datetime(recorded_at, "Handoff record time")
    if getattr(cycle, "accepted", None) is not True:
        raise ShadowOpeningSafetyError(
            "Engine Host did not accept the collection cycle."
        )
    if str(getattr(cycle, "code", "")).strip() != "COLLECTION_COMPLETED":
        raise ShadowOpeningSafetyError(
            "Engine Host did not return COLLECTION_COMPLETED."
        )
    payload = getattr(cycle, "payload", None)
    if not isinstance(payload, Mapping):
        raise ShadowOpeningSafetyError(
            "Engine Host cycle payload is missing."
        )
    selection = payload.get("shadowAutomaticSelection")
    if not isinstance(selection, Mapping):
        raise ShadowOpeningSafetyError(
            "Engine Host selection result is missing."
        )
    receipt_status, terminal_outcome = terminal_selector_outcome(selection)

    snapshot = getattr(cycle, "snapshot", None)
    identity = (
        snapshot.get("identity")
        if isinstance(snapshot, Mapping)
        else None
    )
    collection = (
        snapshot.get("collection")
        if isinstance(snapshot, Mapping)
        else None
    )
    if not isinstance(identity, Mapping):
        raise ShadowOpeningSafetyError(
            "Verified Engine Host identity is missing."
        )
    host_instance_id = str(identity.get("hostInstanceId", "")).strip()
    protocol_version = str(identity.get("protocolVersion", "")).strip()
    process_id = positive_int(identity.get("processId"))
    command_id = str(getattr(cycle, "command_id", "")).strip()
    completion_at = parse_aware_datetime(
        collection.get("lastCompletedCycleAtUtc")
        if isinstance(collection, Mapping)
        else None
    )
    if (
        not host_instance_id
        or not protocol_version
        or process_id is None
        or not command_id
        or completion_at is None
    ):
        raise ShadowOpeningSafetyError(
            "Complete handoff requires host instance, process, protocol, "
            "command, and completion identities."
        )

    decision_cycle_id = str(
        selection.get("decisionCycleId", "")
    ).strip()
    selection_report_sha = str(
        selection.get("reportSha256", "")
    ).strip()
    shadow_trade_id = str(selection.get("shadowTradeId") or "").strip()
    if (
        not capture_id.strip()
        or not decision_cycle_id
        or selection_report_sha != report_sha256
    ):
        raise ShadowOpeningSafetyError(
            "Complete handoff requires matching capture, report, and "
            "decision-cycle identities."
        )
    if (
        receipt_status == "CYCLE_COMPLETED_TRADE_CREATED"
        and not shadow_trade_id
    ):
        raise ShadowOpeningSafetyError(
            "Trade-created handoff is missing the Shadow Trade identity."
        )
    if (
        receipt_status == "CYCLE_COMPLETED_NO_TRADE"
        and shadow_trade_id
    ):
        raise ShadowOpeningSafetyError(
            "No-trade handoff unexpectedly contains a Shadow Trade identity."
        )

    receipt = {
        "schemaVersion": SHADOW_HANDOFF_SCHEMA_VERSION,
        "status": receipt_status,
        "terminalOutcome": terminal_outcome,
        "recordedAt": recorded_at.isoformat(),
        "completionTimestamp": completion_at.isoformat(),
        "reportPath": str(report_path.resolve()),
        "reportSha256": report_sha256,
        "captureId": capture_id,
        "decisionCycleId": decision_cycle_id,
        "commandId": command_id,
        "shadowTradeId": shadow_trade_id or None,
        "engineHost": {
            "hostInstanceId": host_instance_id,
            "processId": process_id,
            "protocolVersion": protocol_version,
            "transport": str(identity.get("transport", "")).strip(),
        },
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }
    findings = shadow_handoff_findings(
        receipt,
        expected_report_sha256=report_sha256,
    )
    if findings:
        raise ShadowOpeningSafetyError(" | ".join(findings))
    return receipt


def shadow_handoff_findings(
    receipt: object,
    *,
    expected_report_sha256: str = "",
) -> tuple[str, ...]:
    if not isinstance(receipt, Mapping):
        return ("Handoff receipt is missing or malformed.",)
    findings: list[str] = []
    status = str(receipt.get("status", ""))
    terminal = str(receipt.get("terminalOutcome", ""))
    host = receipt.get("engineHost")
    if receipt.get("schemaVersion") != SHADOW_HANDOFF_SCHEMA_VERSION:
        findings.append("Handoff receipt schema is unsupported.")
    if status not in SHADOW_HANDOFF_COMPLETE_STATUSES:
        findings.append("Handoff status is not semantically complete.")
    if status == "CYCLE_COMPLETED_TRADE_CREATED":
        if terminal not in SHADOW_TRADE_TERMINAL_OUTCOMES:
            findings.append("Trade handoff terminal outcome is invalid.")
        if not str(receipt.get("shadowTradeId") or "").strip():
            findings.append("Trade handoff lacks a Shadow Trade identity.")
    elif status == "CYCLE_COMPLETED_NO_TRADE":
        if terminal not in SHADOW_NO_TRADE_TERMINAL_OUTCOMES:
            findings.append("No-trade handoff terminal outcome is invalid.")
        if receipt.get("shadowTradeId") not in {None, ""}:
            findings.append(
                "No-trade handoff contains a Shadow Trade identity."
            )
    for field_name in (
        "captureId",
        "decisionCycleId",
        "commandId",
        "reportSha256",
    ):
        if not str(receipt.get(field_name, "")).strip():
            findings.append(f"Handoff receipt lacks {field_name}.")
    if (
        expected_report_sha256
        and receipt.get("reportSha256") != expected_report_sha256
    ):
        findings.append("Handoff report fingerprint does not match.")
    if parse_aware_datetime(receipt.get("recordedAt")) is None:
        findings.append("Handoff recorded timestamp is invalid.")
    if parse_aware_datetime(receipt.get("completionTimestamp")) is None:
        findings.append("Handoff completion timestamp is invalid.")
    if not isinstance(host, Mapping):
        findings.append("Handoff Engine Host identity is missing.")
    else:
        if not str(host.get("hostInstanceId", "")).strip():
            findings.append("Handoff HostInstanceId is missing.")
        if positive_int(host.get("processId")) is None:
            findings.append("Handoff Engine Host process identity is invalid.")
        if not str(host.get("protocolVersion", "")).strip():
            findings.append("Handoff protocol version is missing.")
    if receipt.get("transmitting") is not False:
        findings.append("Handoff transmitting flag is unsafe.")
    if receipt.get("orderTransmission") != "UNAVAILABLE":
        findings.append("Handoff order-transmission boundary is unsafe.")
    return tuple(dict.fromkeys(findings))


def classify_opening_heartbeat(
    *,
    task_running: bool,
    process_alive: bool,
    retry_pending: bool,
    final_result_available: bool,
    final_result_succeeded: bool,
    proof_complete: bool,
    handoff_complete: bool,
) -> OpeningHeartbeatState:
    if task_running or process_alive or retry_pending:
        return OpeningHeartbeatState(
            outcome="IN_PROGRESS",
            reason=(
                "Opening work or its bounded infrastructure retry is still active."
            ),
            retire_heartbeat=False,
        )
    if (
        final_result_available
        and final_result_succeeded
        and proof_complete
        and handoff_complete
    ):
        return OpeningHeartbeatState(
            outcome="COMPLETED",
            reason=(
                "The task ended successfully with complete proof and a "
                "semantically terminal handoff."
            ),
            retire_heartbeat=True,
        )
    return OpeningHeartbeatState(
        outcome="FAILED",
        reason=(
            "No task or retry remains active, and final result, proof, or "
            "semantic handoff evidence is absent or failed."
        ),
        retire_heartbeat=False,
    )


def build_opening_audit_manifest(
    artifacts: Sequence[AuditArtifact],
    *,
    created_at: datetime,
) -> dict[str, object]:
    created_at = require_aware_datetime(
        created_at,
        "Opening audit manifest timestamp",
    )
    by_name = {item.name: item for item in artifacts}
    if set(by_name) != set(SHADOW_OPENING_AUDIT_CATEGORIES):
        raise ShadowOpeningSafetyError(
            "Opening audit manifest artifact set is incomplete."
        )
    entries: list[dict[str, object]] = []
    for name in SHADOW_OPENING_AUDIT_CATEGORIES:
        item = by_name[name]
        if item.status == "PRESENT":
            if item.path is None:
                raise ShadowOpeningSafetyError(
                    f"Present audit artifact lacks a path: {name}."
                )
            resolved = item.path.resolve(strict=True)
            if not resolved.is_file():
                raise ShadowOpeningSafetyError(
                    f"Audit artifact is not a file: {name}."
                )
            content = resolved.read_bytes()
            manifest_location = (
                item.manifest_location.strip()
                or resolved.name
            )
            location_path = Path(manifest_location)
            if (
                location_path.is_absolute()
                or ".." in location_path.parts
            ):
                raise ShadowOpeningSafetyError(
                    f"Audit artifact location is not relative: {name}."
                )
            entry = {
                "name": name,
                "purpose": item.purpose,
                "location": location_path.as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "createdAt": item.created_at or created_at.isoformat(),
                "schemaVersion": item.schema_version,
                "required": item.required,
                "status": "PRESENT",
                "notCreatedReason": None,
            }
        elif item.status == "NOT_CREATED":
            if item.path is not None and item.path.exists():
                raise ShadowOpeningSafetyError(
                    f"NOT_CREATED audit artifact exists: {name}."
                )
            if not item.not_created_reason.strip():
                raise ShadowOpeningSafetyError(
                    f"NOT_CREATED audit artifact lacks a reason: {name}."
                )
            entry = {
                "name": name,
                "purpose": item.purpose,
                "location": None,
                "sha256": None,
                "createdAt": created_at.isoformat(),
                "schemaVersion": item.schema_version,
                "required": item.required,
                "status": "NOT_CREATED",
                "notCreatedReason": item.not_created_reason,
            }
        else:
            raise ShadowOpeningSafetyError(
                f"Audit artifact status is invalid: {name}."
            )
        entries.append(entry)
    manifest_hash = hashlib.sha256(
        canonical_json(entries).encode("ascii")
    ).hexdigest()
    return {
        "schemaVersion": SHADOW_OPENING_AUDIT_SCHEMA_VERSION,
        "manifestType": "OFFICIAL_SHADOW_OPENING_AUDIT",
        "createdAt": created_at.isoformat(),
        "signatureMode": "SHA256_CONTENT_ADDRESS",
        "manifestSha256": manifest_hash,
        "artifacts": entries,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
