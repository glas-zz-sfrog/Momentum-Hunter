from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR
from momentum_hunter.entry_plans import ENTRY_PLANS_PATH
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.sqlite_store import SQLITE_DB_PATH, normalize_status
from momentum_hunter.storage import ANALYSIS_CSV
from momentum_hunter.time_utils import now_central


READ_MODEL_SOURCE_ENV = "MOMENTUM_HUNTER_READ_MODEL_SOURCE"
READ_MODEL_SOURCES = {"file", "sqlite", "shadow"}
READ_MODEL_REPORTS = {"candidate-story", "evidence", "watchlist", "system-readiness"}


def resolve_read_model_source(source: str | None = None) -> str:
    value = (source or os.environ.get(READ_MODEL_SOURCE_ENV) or "file").strip().lower()
    return value if value in READ_MODEL_SOURCES else "file"


def build_read_model_summary(
    report_name: str,
    *,
    source: str | None = None,
    db_path: Path | None = None,
    data_dir: Path = DATA_DIR,
    analysis_captures_path: Path = ANALYSIS_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    alerts_path: Path | None = None,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
) -> dict[str, Any]:
    mode = resolve_read_model_source(source)
    if report_name not in READ_MODEL_REPORTS:
        return {
            "schema_version": 1,
            "engine_version": "read_model_provider_v1",
            "generated_at": now_central().isoformat(),
            "source_mode": mode,
            "report_name": report_name,
            "overall_status": "WARN",
            "warnings": [f"UNKNOWN_READ_MODEL_REPORT:{report_name}"],
        }
    if mode == "sqlite":
        return sqlite_read_model_summary(report_name, db_path=db_path)
    if mode == "shadow":
        return build_shadow_compare_read_model(
            db_path=db_path,
            data_dir=data_dir,
            analysis_captures_path=analysis_captures_path,
            review_decisions_path=review_decisions_path,
            entry_plans_path=entry_plans_path,
            alerts_path=alerts_path,
            minute_bars_path=minute_bars_path,
            reports=[report_name],
        )
    return file_read_model_summary(
        report_name,
        data_dir=data_dir,
        analysis_captures_path=analysis_captures_path,
        review_decisions_path=review_decisions_path,
        entry_plans_path=entry_plans_path,
        alerts_path=alerts_path,
        minute_bars_path=minute_bars_path,
    )


def file_read_model_summary(
    report_name: str,
    *,
    data_dir: Path = DATA_DIR,
    analysis_captures_path: Path = ANALYSIS_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    alerts_path: Path | None = None,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
) -> dict[str, Any]:
    if report_name == "candidate-story":
        return file_candidate_story_summary(analysis_captures_path)
    if report_name == "evidence":
        return file_evidence_summary(alerts_path=alerts_path, minute_bars_path=minute_bars_path)
    if report_name == "watchlist":
        return file_watchlist_summary(
            data_dir=data_dir,
            review_decisions_path=review_decisions_path,
            entry_plans_path=entry_plans_path,
        )
    if report_name == "system-readiness":
        return file_system_readiness_summary(data_dir=data_dir)
    return {
        "schema_version": 1,
        "engine_version": "file_read_model_summary_v1",
        "generated_at": now_central().isoformat(),
        "source_mode": "file",
        "report_name": report_name,
        "overall_status": "WARN",
        "warnings": [f"UNKNOWN_READ_MODEL_REPORT:{report_name}"],
    }


def sqlite_read_model_summary(report_name: str, *, db_path: Path | None = None) -> dict[str, Any]:
    database = db_path or SQLITE_DB_PATH
    try:
        from momentum_hunter.sqlite_reports import build_report

        payload = build_report(report_name, db_path=database)
    except Exception as exc:  # pragma: no cover - defensive guard for runtime callers
        return {
            "schema_version": 1,
            "engine_version": "sqlite_read_model_provider_v1",
            "generated_at": now_central().isoformat(),
            "source_mode": "sqlite",
            "report_name": report_name,
            "database_path": str(database),
            "overall_status": "WARN",
            "warnings": [f"SQLITE_READ_MODEL_FAILED:{type(exc).__name__}:{exc}"],
        }
    payload = dict(payload)
    payload["source_mode"] = "sqlite"
    payload["report_name"] = report_name
    return payload


def build_shadow_compare_read_model(
    *,
    db_path: Path | None = None,
    data_dir: Path = DATA_DIR,
    analysis_captures_path: Path = ANALYSIS_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    alerts_path: Path | None = None,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    reports: list[str] | None = None,
    validate_sqlite: bool = True,
) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    database = db_path or SQLITE_DB_PATH
    report_names = [name for name in (reports or sorted(READ_MODEL_REPORTS)) if name in READ_MODEL_REPORTS]
    comparisons: list[dict[str, Any]] = []
    missing_data: list[str] = []
    warnings: list[str] = []

    validation_status = "UNAVAILABLE"
    validation_warnings: list[str] = []
    missing_slices: list[str] = []
    if validate_sqlite:
        try:
            from momentum_hunter.sqlite_validation import build_sqlite_validation_report

            validation = build_sqlite_validation_report(db_path=database)
            validation_status = str(validation.get("overall_status") or "UNKNOWN")
            validation_warnings = [str(item) for item in (validation.get("warnings") or [])]
            missing_slices = [str(item) for item in (validation.get("missing_slices") or [])]
        except Exception as exc:
            validation_warnings.append(f"SQLITE_VALIDATION_UNAVAILABLE:{type(exc).__name__}:{exc}")
    else:
        validation_status = "SKIPPED"

    validation_ok_statuses = {"PASS", "UNAVAILABLE", "SKIPPED"}
    if validation_status not in validation_ok_statuses:
        warnings.append(f"SQLITE_VALIDATION_NOT_PASS:{validation_status}")
    warnings.extend(validation_warnings)
    if missing_slices:
        warnings.append("SQLITE_MISSING_SLICES:" + ",".join(missing_slices))

    for report_name in report_names:
        file_payload = file_read_model_summary(
            report_name,
            data_dir=data_dir,
            analysis_captures_path=analysis_captures_path,
            review_decisions_path=review_decisions_path,
            entry_plans_path=entry_plans_path,
            alerts_path=alerts_path,
            minute_bars_path=minute_bars_path,
        )
        sqlite_payload = sqlite_read_model_summary(report_name, db_path=database)
        for field in comparable_fields(report_name):
            comparisons.append(compare_shadow_field(report_name, field, file_payload, sqlite_payload))
        missing_data.extend(
            f"{report_name}:{warning}"
            for warning in (file_payload.get("warnings") or [])
            if "MISSING" in str(warning).upper() or "UNAVAILABLE" in str(warning).upper()
        )
        missing_data.extend(
            f"{report_name}:{warning}"
            for warning in (sqlite_payload.get("warnings") or [])
            if "MISSING" in str(warning).upper() or "UNAVAILABLE" in str(warning).upper()
        )

    mismatches = [item for item in comparisons if item["status"] == "MISMATCH"]
    unavailable = [item for item in comparisons if item["status"] == "UNAVAILABLE"]
    stale_sqlite_data = bool(mismatches or validation_status not in validation_ok_statuses)
    overall_status = "WARN" if warnings or mismatches or unavailable or missing_data else "PASS"
    return {
        "schema_version": 1,
        "engine_version": "sqlite_shadow_compare_v1",
        "generated_at": generated_at,
        "source_mode": "shadow",
        "database_path": str(database),
        "reports_compared": report_names,
        "validation_status": validation_status,
        "missing_slices": missing_slices,
        "overall_status": overall_status,
        "matching_fields": sum(1 for item in comparisons if item["status"] == "PASS"),
        "mismatches": len(mismatches),
        "unavailable": len(unavailable),
        "stale_sqlite_data": stale_sqlite_data,
        "fallback_reason": shadow_fallback_reason(overall_status, stale_sqlite_data, unavailable, missing_data),
        "recommended_action": shadow_recommended_action(overall_status, stale_sqlite_data),
        "comparisons": comparisons,
        "missing_data": sorted(set(missing_data)),
        "warnings": sorted(set(warnings)),
    }


def file_candidate_story_summary(path: Path) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    from momentum_hunter.sqlite_reports import file_capture_candidate_counts
    from momentum_hunter.sqlite_store import read_analysis_capture_rows

    if not path.exists():
        return base_file_payload(
            "candidate-story",
            "file_candidate_story_read_model_v1",
            generated_at,
            [f"ANALYSIS_CAPTURE_SOURCE_MISSING:{path}"],
            candidate_count=0,
            capture_count=0,
            capture_candidate_count=0,
        )
    rows, read_warnings = read_analysis_capture_rows(path)
    tickers = sorted({str(row.get("ticker", "")).upper() for row in rows if str(row.get("ticker", "")).strip()})
    counts = file_capture_candidate_counts(path)
    return base_file_payload(
        "candidate-story",
        "file_candidate_story_read_model_v1",
        generated_at,
        read_warnings,
        candidate_count=len(tickers),
        capture_count=counts.get("captures") or 0,
        capture_candidate_count=counts.get("capture_candidates") or 0,
    )


def file_evidence_summary(*, alerts_path: Path | None, minute_bars_path: Path) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH
    from momentum_hunter.sqlite_reports import file_alert_state_counts, file_minute_bar_count

    alerts_source = alerts_path or OPPORTUNITY_ALERTS_PATH
    alert_counts = file_alert_state_counts(alerts_source)
    minute_count = file_minute_bar_count(minute_bars_path)
    warnings = []
    if not alerts_source.exists():
        warnings.append(f"OPPORTUNITY_ALERTS_SOURCE_MISSING:{alerts_source}")
    if not minute_bars_path.exists():
        warnings.append(f"MINUTE_BARS_SOURCE_MISSING:{minute_bars_path}")
    return base_file_payload(
        "evidence",
        "file_evidence_read_model_v1",
        generated_at,
        warnings,
        alert_count=alert_counts.get("alerts") or 0,
        completed_outcomes=alert_counts.get("completed") or 0,
        pending_outcomes=alert_counts.get("pending") or 0,
        unscorable_outcomes=alert_counts.get("unscorable") or 0,
        available_minute_bars=minute_count or 0,
    )


def file_watchlist_summary(
    *,
    data_dir: Path,
    review_decisions_path: Path,
    entry_plans_path: Path,
) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    from momentum_hunter.sqlite_reports import file_entry_plan_counts, file_review_status_counts, file_watchlist_item_count

    review_counts = file_review_status_counts(review_decisions_path)
    plan_counts = file_entry_plan_counts(entry_plans_path)
    watchlist_count = file_watchlist_item_count(data_dir)
    warnings = []
    if not review_decisions_path.exists():
        warnings.append(f"REVIEW_DECISIONS_SOURCE_MISSING:{review_decisions_path}")
    if not entry_plans_path.exists():
        warnings.append(f"ENTRY_PLANS_SOURCE_MISSING:{entry_plans_path}")
    return base_file_payload(
        "watchlist",
        "file_watchlist_read_model_v1",
        generated_at,
        warnings,
        interested_count=review_counts.get("interested", 0),
        rejected_count=review_counts.get("rejected", 0),
        review_watchlist_count=review_counts.get("watchlist", 0),
        watchlist_count=watchlist_count,
        complete_plans=plan_counts.get("complete", 0),
        incomplete_plans=plan_counts.get("incomplete", 0),
    )


def file_system_readiness_summary(*, data_dir: Path = DATA_DIR) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    reports_dir = data_dir / "reports"
    readiness_path = reports_dir / "system-readiness-latest.json"
    data_quality_path = reports_dir / "data-quality-latest.json"
    autopilot_path = data_dir / "evidence-autopilot-status.json"
    warnings = []
    readiness_status = file_report_status(readiness_path, nested_report=True)
    data_quality_warnings = file_report_warning_count(data_quality_path, nested_report=True)
    autopilot_state = file_autopilot_state(autopilot_path)
    if readiness_status == "UNAVAILABLE":
        warnings.append(f"SYSTEM_READINESS_SOURCE_MISSING:{readiness_path}")
    if data_quality_warnings is None:
        warnings.append(f"DATA_QUALITY_SOURCE_MISSING:{data_quality_path}")
    if autopilot_state == "UNAVAILABLE":
        warnings.append(f"EVIDENCE_AUTOPILOT_STATUS_MISSING:{autopilot_path}")
    return base_file_payload(
        "system-readiness",
        "file_system_readiness_read_model_v1",
        generated_at,
        warnings,
        system_readiness_status=readiness_status,
        data_quality_warning_count=data_quality_warnings if data_quality_warnings is not None else 0,
        evidence_autopilot_state=autopilot_state,
    )


def base_file_payload(report_name: str, engine_version: str, generated_at: str, warnings: list[str], **values: Any) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "engine_version": engine_version,
        "generated_at": generated_at,
        "source_mode": "file",
        "report_name": report_name,
        "overall_status": "WARN" if warnings else "OK",
        "warnings": warnings,
    }
    payload.update(values)
    return payload


def comparable_fields(report_name: str) -> list[tuple[str, str | None]]:
    if report_name == "candidate-story":
        return [("candidate_count", "candidate_count")]
    if report_name == "evidence":
        return [
            ("alert_count", "alert_count"),
            ("completed_outcomes", "completed_outcomes"),
            ("pending_outcomes", "pending_outcomes"),
            ("unscorable_outcomes", "unscorable_outcomes"),
            ("available_minute_bars", "available_minute_bars"),
        ]
    if report_name == "watchlist":
        return [
            ("interested_count", "interested_count"),
            ("rejected_count", "rejected_count"),
            ("review_watchlist_count", "review_watchlist_count"),
            ("watchlist_count", "watchlist_count"),
            ("complete_plans", "complete_plans"),
            ("incomplete_plans", "incomplete_plans"),
        ]
    if report_name == "system-readiness":
        return [
            ("system_readiness_status", "latest_system_readiness_status"),
            ("evidence_autopilot_state", "latest_evidence_autopilot_state"),
        ]
    return []


def compare_shadow_field(
    report_name: str,
    field_pair: tuple[str, str | None],
    file_payload: dict[str, Any],
    sqlite_payload: dict[str, Any],
) -> dict[str, Any]:
    file_field, sqlite_field = field_pair
    sqlite_key = sqlite_field or file_field
    file_value = normalized_comparison_value(file_payload.get(file_field))
    sqlite_value = normalized_comparison_value(extract_sqlite_shadow_value(sqlite_payload, sqlite_key))
    if file_value is None:
        status = "UNAVAILABLE"
        message = "File read-model value unavailable."
    elif sqlite_value is None:
        status = "UNAVAILABLE"
        message = "SQLite read-model value unavailable."
    else:
        status = "PASS" if file_value == sqlite_value else "MISMATCH"
        message = f"file={file_value}, sqlite={sqlite_value}"
    return {
        "surface": report_name,
        "field": file_field,
        "sqlite_field": sqlite_key,
        "status": status,
        "file_value": file_value,
        "sqlite_value": sqlite_value,
        "message": message,
    }


def extract_sqlite_shadow_value(payload: dict[str, Any], key: str) -> Any:
    if key in payload:
        return payload.get(key)
    if key == "latest_system_readiness_status":
        for event in payload.get("latest_system_status_events", []) or []:
            if isinstance(event, dict) and event.get("event_type") == "system_readiness:overall":
                return normalize_status(str(event.get("status") or ""))
    if key == "latest_evidence_autopilot_state":
        rows = payload.get("latest_evidence_autopilot_status") or []
        if rows and isinstance(rows[0], dict):
            details = safe_json_loads(rows[0].get("summary_json")) or safe_json_loads(rows[0].get("details_json"))
            state = nested_first(details, ["status", "state"]) or details.get("state") if isinstance(details, dict) else None
            return normalize_status(str(state or rows[0].get("status") or ""))
    return None


def normalized_comparison_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        if value.strip().upper() in {"OK", "PASS", "PASSED", "READY", "SUCCESS", "SUCCESSFUL", "COMPLETE", "COMPLETED"}:
            return "READY"
        return normalize_status(value)
    return value


def file_report_status(path: Path, *, nested_report: bool) -> str:
    payload = load_json(path)
    if not payload:
        return "UNAVAILABLE"
    body = payload.get("report", payload) if nested_report else payload
    return normalize_status(str(body.get("overall_status") or body.get("status") or body.get("state") or "UNKNOWN"))


def file_report_warning_count(path: Path, *, nested_report: bool) -> int | None:
    payload = load_json(path)
    if not payload:
        return None
    body = payload.get("report", payload) if nested_report else payload
    warnings = body.get("warnings", [])
    return len(warnings) if isinstance(warnings, list) else 0


def file_autopilot_state(path: Path) -> str:
    payload = load_json(path)
    if not payload:
        return "UNAVAILABLE"
    state = nested_first(payload, ["status", "state"]) or payload.get("state") or payload.get("status")
    return normalize_status(str(state or "UNKNOWN"))


def load_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def safe_json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        data = json.loads(str(value))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def nested_first(payload: dict[str, Any], keys: list[str]) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def shadow_fallback_reason(
    overall_status: str,
    stale_sqlite_data: bool,
    unavailable: list[dict[str, Any]],
    missing_data: list[str],
) -> str:
    if overall_status == "PASS":
        return "No fallback required for diagnostic shadow report; runtime should still default to file mode."
    if stale_sqlite_data:
        return "SQLite mirror differs from file-authoritative sources; keep file fallback active."
    if unavailable or missing_data:
        return "One or more read-model fields are unavailable; keep file fallback active."
    return "Warnings present; keep file fallback active until reviewed."


def shadow_recommended_action(overall_status: str, stale_sqlite_data: bool) -> str:
    if overall_status == "PASS":
        return "SQLite optional read mode is safe to test for report-only surfaces; keep runtime default as file."
    if stale_sqlite_data:
        return "Run SQLite import/validation before testing SQLite read mode."
    return "Review missing/unavailable shadow fields before relying on SQLite reports."
