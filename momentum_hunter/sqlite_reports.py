from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.entry_plans import ENTRY_PLANS_PATH
from momentum_hunter.opportunity_alerts import (
    OPPORTUNITY_ALERTS_PATH,
    is_completed_alert,
    is_pending_alert,
    is_unscorable_alert,
    load_alerts,
)
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.sqlite_queries import alert_evidence_summary, sqlite_backbone_summary
from momentum_hunter.sqlite_store import (
    SQLITE_DB_PATH,
    connect_database,
    current_schema_version,
    load_entry_plan_source_records,
    load_review_source_records,
    load_watchlist_source_records,
    parse_minute_bar_source,
    read_analysis_capture_rows,
)
from momentum_hunter.sqlite_validation import build_sqlite_validation_report
from momentum_hunter.storage import ANALYSIS_CSV
from momentum_hunter.time_utils import now_central


REPORTS_DIR = DATA_DIR / "reports"

REPORT_PATHS = {
    "candidate-story": (
        "sqlite-candidate-story-read-model-latest.json",
        "sqlite-candidate-story-read-model-latest.md",
    ),
    "evidence": (
        "sqlite-evidence-read-model-latest.json",
        "sqlite-evidence-read-model-latest.md",
    ),
    "watchlist": (
        "sqlite-watchlist-read-model-latest.json",
        "sqlite-watchlist-read-model-latest.md",
    ),
    "system-readiness": (
        "sqlite-system-readiness-read-model-latest.json",
        "sqlite-system-readiness-read-model-latest.md",
    ),
    "comparison": (
        "sqlite-read-model-comparison-latest.json",
        "sqlite-read-model-comparison-latest.md",
    ),
    "shadow-compare": (
        "sqlite-shadow-compare-latest.json",
        "sqlite-shadow-compare-latest.md",
    ),
}

REPORT_ORDER = ["candidate-story", "evidence", "watchlist", "system-readiness", "comparison", "shadow-compare"]


def build_candidate_story_read_model(*, db_path: Path | None = None) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    database = db_path or SQLITE_DB_PATH
    if not database.exists():
        return empty_payload("sqlite_candidate_story_read_model_v1", generated_at, database, ["SQLITE_DATABASE_MISSING"])
    with connect_database(database) as connection:
        capture_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    c.capture_id,
                    c.capture_date,
                    c.capture_time,
                    c.session,
                    c.provider,
                    c.scanner,
                    COALESCE(c.is_quarantined, 0) AS is_quarantined,
                    cc.ticker,
                    cc.company,
                    cc.score,
                    cc.price,
                    cc.relative_volume,
                    cc.volume,
                    cc.sector,
                    cc.industry
                FROM capture_candidates cc
                JOIN captures c ON c.capture_id = cc.capture_id
                WHERE COALESCE(c.is_quarantined, 0) = 0
                ORDER BY cc.ticker, c.capture_time
                """
            ).fetchall()
        ]
        reviews = latest_rows_by_ticker(
            [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT ticker, review_status, decision_timestamp, capture_id
                    FROM candidate_reviews
                    ORDER BY decision_timestamp, ticker
                    """
                ).fetchall()
            ],
            timestamp_key="decision_timestamp",
        )
        plans = latest_rows_by_ticker(
            [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT ticker, capture_id, plan_complete, updated_at, warnings_json
                    FROM entry_plans
                    ORDER BY updated_at, ticker
                    """
                ).fetchall()
            ],
            timestamp_key="updated_at",
        )
        schema_version = current_schema_version(connection)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in capture_rows:
        grouped.setdefault(str(row.get("ticker", "")).upper(), []).append(row)
    stories = []
    for ticker, rows in sorted(grouped.items()):
        if not ticker or not rows:
            continue
        first = rows[0]
        latest = rows[-1]
        peak = max(rows, key=lambda item: (optional_number(item.get("score"), -1), str(item.get("capture_time", ""))))
        first_price = optional_number(first.get("price"))
        latest_price = optional_number(latest.get("price"))
        first_score = optional_number(first.get("score"))
        latest_score = optional_number(latest.get("score"))
        review = reviews.get(ticker, {})
        plan = plans.get(ticker, {})
        stories.append(
            {
                "ticker": ticker,
                "company": latest.get("company") or first.get("company") or "",
                "sector": latest.get("sector") or "",
                "industry": latest.get("industry") or "",
                "first_seen": first.get("capture_time") or "",
                "latest_capture": latest.get("capture_time") or "",
                "first_price": first_price,
                "latest_price": latest_price,
                "move_since_first_seen_pct": pct_change(first_price, latest_price),
                "peak_score": optional_number(peak.get("score")),
                "peak_score_capture": peak.get("capture_time") or "",
                "first_score": first_score,
                "latest_score": latest_score,
                "score_trend": score_trend(first_score, latest_score),
                "trusted_capture_count": len(rows),
                "candidate_status": review.get("review_status", ""),
                "candidate_status_timestamp": review.get("decision_timestamp", ""),
                "entry_plan_status": entry_plan_status(plan),
                "entry_plan_updated_at": plan.get("updated_at", ""),
            }
        )
    stories.sort(key=lambda item: (-int(item["trusted_capture_count"]), item["ticker"]))
    return {
        "schema_version": 1,
        "engine_version": "sqlite_candidate_story_read_model_v1",
        "generated_at": generated_at,
        "database_path": str(database),
        "sqlite_schema_version": schema_version,
        "candidate_count": len(stories),
        "stories": stories,
        "warnings": [],
    }


def build_evidence_read_model(*, db_path: Path | None = None) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    database = db_path or SQLITE_DB_PATH
    if not database.exists():
        return empty_payload("sqlite_evidence_read_model_v1", generated_at, database, ["SQLITE_DATABASE_MISSING"])
    with connect_database(database) as connection:
        schema_version = current_schema_version(connection)
        alert_count = int(connection.execute("SELECT COUNT(*) AS count FROM opportunity_alerts").fetchone()["count"])
        evidence = alert_evidence_summary(db_path=database)
        minute_bar_count = int(connection.execute("SELECT COUNT(*) AS count FROM minute_bars").fetchone()["count"])
        minute_bar_symbols = [
            dict(row)
            for row in connection.execute(
                """
                SELECT symbol, COUNT(*) AS count, MIN(timestamp) AS first_timestamp, MAX(timestamp) AS latest_timestamp
                FROM minute_bars
                GROUP BY symbol
                ORDER BY symbol
                """
            ).fetchall()
        ]
        symbols_with_evidence = sorted(
            {
                str(row["symbol"]).upper()
                for row in connection.execute("SELECT DISTINCT symbol FROM opportunity_alerts").fetchall()
            }
            | {str(row["symbol"]).upper() for row in minute_bar_symbols}
        )
        latest_run_row = connection.execute(
            """
            SELECT *
            FROM evidence_runs
            ORDER BY generated_at DESC, imported_at DESC
            LIMIT 1
            """
        ).fetchone()
    completed = int(evidence["completed_outcomes"])
    return {
        "schema_version": 1,
        "engine_version": "sqlite_evidence_read_model_v1",
        "generated_at": generated_at,
        "database_path": str(database),
        "sqlite_schema_version": schema_version,
        "alert_count": alert_count,
        "completed_outcomes": completed,
        "pending_outcomes": evidence["pending_outcomes"],
        "unscorable_outcomes": evidence["unscorable_outcomes"],
        "classification_distribution": evidence["classification_counts"],
        "available_minute_bars": minute_bar_count,
        "minute_bar_symbols": minute_bar_symbols,
        "symbols_with_evidence": symbols_with_evidence,
        "latest_evidence_run": dict(latest_run_row) if latest_run_row else None,
        "evidence_sample_size_status": evidence_sample_status(completed),
        "warnings": [] if alert_count else ["NO_ALERTS_IN_SQLITE"],
    }


def build_watchlist_read_model(*, db_path: Path | None = None) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    database = db_path or SQLITE_DB_PATH
    if not database.exists():
        return empty_payload("sqlite_watchlist_read_model_v1", generated_at, database, ["SQLITE_DATABASE_MISSING"])
    with connect_database(database) as connection:
        schema_version = current_schema_version(connection)
        review_counts = {
            str(row["review_status"]): int(row["count"])
            for row in connection.execute(
                """
                SELECT review_status, COUNT(*) AS count
                FROM candidate_reviews
                GROUP BY review_status
                ORDER BY review_status
                """
            ).fetchall()
        }
        watchlist_items = [dict(row) for row in connection.execute("SELECT * FROM watchlist_items").fetchall()]
        entry_plans = [dict(row) for row in connection.execute("SELECT * FROM entry_plans").fetchall()]
    plan_keys = {identity_key(row): row for row in entry_plans}
    watchlist_keys = {identity_key(row): row for row in watchlist_items}
    complete_plans = [row for row in entry_plans if int(row.get("plan_complete") or 0) == 1]
    incomplete_plans = [row for row in entry_plans if int(row.get("plan_complete") or 0) != 1]
    candidates_with_plans_no_watchlist = sorted(plan_keys[key]["ticker"] for key in plan_keys.keys() - watchlist_keys.keys())
    watchlist_without_complete_plan = sorted(
        watchlist_keys[key]["ticker"]
        for key in watchlist_keys
        if int(plan_keys.get(key, {}).get("plan_complete") or 0) != 1
    )
    return {
        "schema_version": 1,
        "engine_version": "sqlite_watchlist_read_model_v1",
        "generated_at": generated_at,
        "database_path": str(database),
        "sqlite_schema_version": schema_version,
        "interested_count": int(review_counts.get("interested", 0)),
        "rejected_count": int(review_counts.get("rejected", 0)),
        "review_watchlist_count": int(review_counts.get("watchlist", 0)),
        "watchlist_count": len(watchlist_items),
        "complete_plans": len(complete_plans),
        "incomplete_plans": len(incomplete_plans),
        "candidates_with_plans_but_no_watchlist": candidates_with_plans_no_watchlist,
        "watchlist_candidates_without_complete_plans": watchlist_without_complete_plan,
        "review_status_counts": review_counts,
        "warnings": [] if watchlist_items else ["NO_WATCHLIST_ITEMS_IN_SQLITE"],
    }


def build_system_readiness_read_model(
    *,
    db_path: Path | None = None,
    validation_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    database = db_path or SQLITE_DB_PATH
    if not database.exists():
        return empty_payload("sqlite_system_readiness_read_model_v1", generated_at, database, ["SQLITE_DATABASE_MISSING"])
    warnings: list[str] = []
    with connect_database(database) as connection:
        schema_version = current_schema_version(connection)
        latest_provider_at = connection.execute(
            "SELECT MAX(generated_at) AS generated_at FROM provider_quality_checks"
        ).fetchone()["generated_at"]
        provider_quality = []
        if latest_provider_at:
            provider_quality = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT symbol, provider, usable_market_tape, last_price, bid, ask, spread_percent, warnings
                    FROM provider_quality_checks
                    WHERE generated_at = ?
                    ORDER BY symbol, provider
                    """,
                    (latest_provider_at,),
                ).fetchall()
            ]
        status_events = [
            dict(row)
            for row in connection.execute(
                """
                SELECT event_type, status, occurred_at, summary, recommended_action, source_path
                FROM system_status_events
                ORDER BY occurred_at DESC, event_type
                LIMIT 10
                """
            ).fetchall()
        ]
        autopilot_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT *
                FROM evidence_runs
                WHERE run_type LIKE '%autopilot%' OR source_path LIKE '%evidence-autopilot%'
                ORDER BY generated_at DESC, imported_at DESC
                LIMIT 3
                """
            ).fetchall()
        ]
    if validation_payload is None:
        try:
            validation_payload = build_sqlite_validation_report(db_path=database)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            validation_payload = {
                "overall_status": "WARN",
                "missing_slices": [],
                "warnings": [f"SQLITE_VALIDATION_FAILED:{type(exc).__name__}:{exc}"],
            }
    validation_warnings = validation_payload.get("warnings", []) if isinstance(validation_payload, dict) else []
    if isinstance(validation_warnings, list):
        warnings.extend(str(item) for item in validation_warnings)
    validation_status = validation_payload.get("overall_status", "UNKNOWN") if isinstance(validation_payload, dict) else "UNKNOWN"
    return {
        "schema_version": 1,
        "engine_version": "sqlite_system_readiness_read_model_v1",
        "generated_at": generated_at,
        "database_path": str(database),
        "sqlite_schema_version": schema_version,
        "latest_provider_quality_generated_at": latest_provider_at or "",
        "latest_provider_quality": provider_quality,
        "latest_system_status_events": status_events,
        "latest_evidence_autopilot_status": autopilot_rows,
        "validation_status": validation_status,
        "missing_slices": validation_payload.get("missing_slices", []) if isinstance(validation_payload, dict) else [],
        "warnings": sorted(set(warnings)),
        "recommended_next_action": readiness_recommendation(validation_status, warnings),
    }


def build_sqlite_read_model_comparison(
    *,
    db_path: Path | None = None,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    analysis_captures_path: Path = ANALYSIS_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    data_dir: Path = DATA_DIR,
) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    database = db_path or SQLITE_DB_PATH
    comparisons: list[dict[str, Any]] = []
    warnings: list[str] = []
    if database.exists():
        sqlite_counts = sqlite_backbone_summary(db_path=database)["table_counts"]
        sqlite_review_counts = sqlite_review_status_counts(database)
        sqlite_plan_counts = sqlite_entry_plan_counts(database)
        sqlite_alert_counts = sqlite_alert_state_counts(database)
    else:
        sqlite_counts = {}
        sqlite_review_counts = {}
        sqlite_plan_counts = {}
        sqlite_alert_counts = {}
        warnings.append(f"SQLITE_DATABASE_MISSING:{database}")

    file_alert_counts = file_alert_state_counts(alerts_path)
    comparisons.extend(
        [
            compare_count("opportunity_alerts", file_alert_counts.get("alerts"), sqlite_counts.get("opportunity_alerts")),
            compare_count("alert_outcomes", file_alert_counts.get("outcomes"), sqlite_counts.get("alert_outcomes")),
            compare_count("completed_alert_outcomes", file_alert_counts.get("completed"), sqlite_alert_counts.get("completed")),
            compare_count("pending_alert_outcomes", file_alert_counts.get("pending"), sqlite_alert_counts.get("pending")),
            compare_count("unscorable_alert_outcomes", file_alert_counts.get("unscorable"), sqlite_alert_counts.get("unscorable")),
        ]
    )

    file_bar_count = file_minute_bar_count(minute_bars_path)
    comparisons.append(compare_count("minute_bars", file_bar_count, sqlite_counts.get("minute_bars")))

    file_capture_counts = file_capture_candidate_counts(analysis_captures_path)
    comparisons.append(compare_count("captures", file_capture_counts.get("captures"), sqlite_counts.get("captures")))
    comparisons.append(
        compare_count("capture_candidates", file_capture_counts.get("capture_candidates"), sqlite_counts.get("capture_candidates"))
    )

    file_review_counts = file_review_status_counts(review_decisions_path)
    for status in sorted(set(file_review_counts) | set(sqlite_review_counts)):
        comparisons.append(
            compare_count(f"review_status:{status}", file_review_counts.get(status), sqlite_review_counts.get(status))
        )

    file_watchlist_count = file_watchlist_item_count(data_dir)
    comparisons.append(compare_count("watchlist_items", file_watchlist_count, sqlite_counts.get("watchlist_items")))

    file_plan_counts = file_entry_plan_counts(entry_plans_path)
    comparisons.append(compare_count("entry_plans", file_plan_counts.get("total"), sqlite_counts.get("entry_plans")))
    comparisons.append(compare_count("complete_entry_plans", file_plan_counts.get("complete"), sqlite_plan_counts.get("complete")))
    comparisons.append(compare_count("incomplete_entry_plans", file_plan_counts.get("incomplete"), sqlite_plan_counts.get("incomplete")))

    unavailable = [item for item in comparisons if item["status"] == "UNAVAILABLE"]
    mismatches = [item for item in comparisons if item["status"] == "MISMATCH"]
    overall = "WARN" if warnings or unavailable or mismatches else "PASS"
    return {
        "schema_version": 1,
        "engine_version": "sqlite_read_model_comparison_v1",
        "generated_at": generated_at,
        "database_path": str(database),
        "overall_status": overall,
        "comparisons": comparisons,
        "matching_counts": sum(1 for item in comparisons if item["status"] == "PASS"),
        "mismatches": len(mismatches),
        "unavailable": len(unavailable),
        "warnings": sorted(set(warnings)),
    }


def write_report(report_name: str, payload: dict[str, Any], *, output_dir: Path = REPORTS_DIR) -> dict[str, Path]:
    ensure_app_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_name, markdown_name = REPORT_PATHS[report_name]
    json_path = output_dir / json_name
    markdown_path = output_dir / markdown_name
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_report_markdown(report_name, payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def build_report(report_name: str, *, db_path: Path | None = None) -> dict[str, Any]:
    if report_name == "candidate-story":
        return build_candidate_story_read_model(db_path=db_path)
    if report_name == "evidence":
        return build_evidence_read_model(db_path=db_path)
    if report_name == "watchlist":
        return build_watchlist_read_model(db_path=db_path)
    if report_name == "system-readiness":
        return build_system_readiness_read_model(db_path=db_path)
    if report_name == "comparison":
        return build_sqlite_read_model_comparison(db_path=db_path)
    if report_name == "shadow-compare":
        from momentum_hunter.read_models import build_shadow_compare_read_model

        return build_shadow_compare_read_model(db_path=db_path)
    raise ValueError(f"Unknown report: {report_name}")


def generate_reports(
    report_names: list[str],
    *,
    db_path: Path | None = None,
    output_dir: Path = REPORTS_DIR,
) -> dict[str, Any]:
    generated: dict[str, Any] = {}
    for report_name in report_names:
        payload = build_report(report_name, db_path=db_path)
        paths = write_report(report_name, payload, output_dir=output_dir)
        generated[report_name] = {
            "json": str(paths["json"]),
            "markdown": str(paths["markdown"]),
            "status": payload.get("overall_status") or payload.get("validation_status") or "OK",
            "warnings": payload.get("warnings", []),
        }
    return {
        "schema_version": 1,
        "engine_version": "sqlite_reports_cli_v1",
        "generated_at": now_central().isoformat(),
        "database_path": str(db_path or SQLITE_DB_PATH),
        "reports": generated,
    }


def format_report_markdown(report_name: str, payload: dict[str, Any]) -> str:
    if report_name == "candidate-story":
        return candidate_story_markdown(payload)
    if report_name == "evidence":
        return evidence_markdown(payload)
    if report_name == "watchlist":
        return watchlist_markdown(payload)
    if report_name == "system-readiness":
        return system_readiness_markdown(payload)
    if report_name == "comparison":
        return comparison_markdown(payload)
    if report_name == "shadow-compare":
        return shadow_compare_markdown(payload)
    return generic_markdown(report_name, payload)


def candidate_story_markdown(payload: dict[str, Any]) -> str:
    lines = header("SQLite Candidate Story Read Model", payload)
    lines.extend(
        [
            f"- Candidate count: {payload.get('candidate_count', 0)}",
            "",
            "## Top Candidate Stories",
            "",
            "| Ticker | First Seen | Latest Capture | Move | Peak Score | Score Trend | Trusted Captures | Review | Plan |",
            "| --- | --- | --- | ---: | ---: | --- | ---: | --- | --- |",
        ]
    )
    for story in payload.get("stories", [])[:50]:
        if not isinstance(story, dict):
            continue
        lines.append(
            "| {ticker} | {first_seen} | {latest_capture} | {move} | {peak} | {trend} | {trusted} | {status} | {plan} |".format(
                ticker=story.get("ticker", ""),
                first_seen=short_dt(story.get("first_seen")),
                latest_capture=short_dt(story.get("latest_capture")),
                move=format_pct(story.get("move_since_first_seen_pct")),
                peak=story.get("peak_score", ""),
                trend=story.get("score_trend", ""),
                trusted=story.get("trusted_capture_count", 0),
                status=story.get("candidate_status", "") or "n/a",
                plan=story.get("entry_plan_status", "") or "none",
            )
        )
    append_warnings(lines, payload)
    return "\n".join(lines) + "\n"


def evidence_markdown(payload: dict[str, Any]) -> str:
    lines = header("SQLite Evidence Read Model", payload)
    lines.extend(
        [
            f"- Alert count: {payload.get('alert_count', 0)}",
            f"- Completed outcomes: {payload.get('completed_outcomes', 0)}",
            f"- Pending outcomes: {payload.get('pending_outcomes', 0)}",
            f"- Unscorable outcomes: {payload.get('unscorable_outcomes', 0)}",
            f"- Available minute bars: {payload.get('available_minute_bars', 0)}",
            f"- Evidence sample-size status: {payload.get('evidence_sample_size_status', '')}",
            "",
            "## Classification Distribution",
            "",
        ]
    )
    for row in payload.get("classification_distribution", []):
        if isinstance(row, dict):
            lines.append(f"- {row.get('classification', '')}: {row.get('count', 0)} ({row.get('status', '')})")
    lines.extend(["", "## Symbols With Evidence", "", ", ".join(payload.get("symbols_with_evidence", []) or []) or "None"])
    append_warnings(lines, payload)
    return "\n".join(lines) + "\n"


def watchlist_markdown(payload: dict[str, Any]) -> str:
    lines = header("SQLite Watchlist / Plans Read Model", payload)
    lines.extend(
        [
            f"- Interested count: {payload.get('interested_count', 0)}",
            f"- Rejected count: {payload.get('rejected_count', 0)}",
            f"- Review watchlist count: {payload.get('review_watchlist_count', 0)}",
            f"- Watchlist item count: {payload.get('watchlist_count', 0)}",
            f"- Complete plans: {payload.get('complete_plans', 0)}",
            f"- Incomplete plans: {payload.get('incomplete_plans', 0)}",
            "",
            "## Gaps",
            "",
            "- Candidates with plans but no watchlist: "
            + (", ".join(payload.get("candidates_with_plans_but_no_watchlist", []) or []) or "None"),
            "- Watchlist candidates without complete plans: "
            + (", ".join(payload.get("watchlist_candidates_without_complete_plans", []) or []) or "None"),
        ]
    )
    append_warnings(lines, payload)
    return "\n".join(lines) + "\n"


def system_readiness_markdown(payload: dict[str, Any]) -> str:
    lines = header("SQLite System Readiness Read Model", payload)
    lines.extend(
        [
            f"- Validation status: {payload.get('validation_status', 'UNKNOWN')}",
            f"- Latest provider quality generated at: {payload.get('latest_provider_quality_generated_at', '')}",
            f"- Missing slices: {', '.join(payload.get('missing_slices', []) or []) or 'None'}",
            f"- Recommended next action: {payload.get('recommended_next_action', '')}",
            "",
            "## Latest System Status Events",
            "",
        ]
    )
    for event in payload.get("latest_system_status_events", [])[:10]:
        if isinstance(event, dict):
            lines.append(
                f"- {event.get('occurred_at', '')}: {event.get('event_type', '')} "
                f"{event.get('status', '')} - {event.get('summary', '')}"
            )
    append_warnings(lines, payload)
    return "\n".join(lines) + "\n"


def comparison_markdown(payload: dict[str, Any]) -> str:
    lines = header("SQLite Read Model Comparison", payload)
    lines.extend(
        [
            f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
            f"- Matching counts: {payload.get('matching_counts', 0)}",
            f"- Mismatches: {payload.get('mismatches', 0)}",
            f"- Unavailable comparisons: {payload.get('unavailable', 0)}",
            "",
            "| Check | Status | File Count | SQLite Count | Message |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for item in payload.get("comparisons", []):
        if isinstance(item, dict):
            lines.append(
                f"| {item.get('name', '')} | {item.get('status', '')} | "
                f"{display_count(item.get('file_count'))} | {display_count(item.get('sqlite_count'))} | "
                f"{item.get('message', '')} |"
            )
    append_warnings(lines, payload)
    return "\n".join(lines) + "\n"


def shadow_compare_markdown(payload: dict[str, Any]) -> str:
    lines = header("SQLite Shadow Compare", payload)
    lines.extend(
        [
            f"- Overall status: {payload.get('overall_status', 'UNKNOWN')}",
            f"- Validation status: {payload.get('validation_status', 'UNKNOWN')}",
            f"- Matching fields: {payload.get('matching_fields', 0)}",
            f"- Mismatches: {payload.get('mismatches', 0)}",
            f"- Unavailable fields: {payload.get('unavailable', 0)}",
            f"- Stale SQLite data: {payload.get('stale_sqlite_data', False)}",
            f"- Fallback reason: {payload.get('fallback_reason', '')}",
            f"- Recommended action: {payload.get('recommended_action', '')}",
            "",
            "| Surface | Field | Status | File Value | SQLite Value | Message |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("comparisons", []):
        if isinstance(item, dict):
            lines.append(
                f"| {item.get('surface', '')} | {item.get('field', '')} | {item.get('status', '')} | "
                f"{item.get('file_value', '')} | {item.get('sqlite_value', '')} | {item.get('message', '')} |"
            )
    missing = payload.get("missing_data", []) or []
    lines.extend(["", "## Missing Data", ""])
    if missing:
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("- None.")
    append_warnings(lines, payload)
    return "\n".join(lines) + "\n"


def generic_markdown(report_name: str, payload: dict[str, Any]) -> str:
    lines = header(f"SQLite {report_name} Read Model", payload)
    lines.extend(["", "```json", json.dumps(payload, indent=2), "```"])
    return "\n".join(lines) + "\n"


def header(title: str, payload: dict[str, Any]) -> list[str]:
    return [
        f"# Momentum Hunter {title}",
        "",
        f"- Generated at: {payload.get('generated_at', '')}",
        f"- Database: `{payload.get('database_path', '')}`",
        f"- SQLite schema version: {payload.get('sqlite_schema_version', 'n/a')}",
        "",
    ]


def append_warnings(lines: list[str], payload: dict[str, Any]) -> None:
    lines.extend(["", "## Warnings", ""])
    warnings = payload.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- None.")


def latest_rows_by_ticker(rows: list[dict[str, Any]], *, timestamp_key: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        if not ticker:
            continue
        if ticker not in latest or str(row.get(timestamp_key, "")) >= str(latest[ticker].get(timestamp_key, "")):
            latest[ticker] = row
    return latest


def optional_number(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def pct_change(first: float | None, latest: float | None) -> float | None:
    if first in (None, 0) or latest is None:
        return None
    return round(((latest - first) / first) * 100.0, 2)


def score_trend(first: float | None, latest: float | None) -> str:
    if first is None or latest is None:
        return "unknown"
    delta = latest - first
    if delta > 0:
        return f"up {int(delta)}"
    if delta < 0:
        return f"down {abs(int(delta))}"
    return "flat"


def entry_plan_status(plan: dict[str, Any]) -> str:
    if not plan:
        return "none"
    return "complete" if int(plan.get("plan_complete") or 0) == 1 else "incomplete"


def identity_key(row: dict[str, Any]) -> str:
    return f"{row.get('capture_id', '')}|{str(row.get('ticker', '')).upper()}"


def evidence_sample_status(completed: int) -> str:
    if completed < 25:
        return f"COLLECTING ({completed}/25 completed alerts)"
    if completed < 50:
        return f"PATTERN_REVIEW_ALLOWED ({completed}/50 completed alerts)"
    if completed < 100:
        return f"INVESTIGATION_ALLOWED ({completed}/100 completed alerts)"
    return f"STRATEGY_RESEARCH_READY ({completed}+ completed alerts)"


def readiness_recommendation(validation_status: str, warnings: list[str]) -> str:
    if validation_status == "PASS" and not warnings:
        return "No action required. SQLite read models are consistent with current validation inputs."
    if validation_status == "PASS":
        return "Review warnings before relying on this read model."
    return "Run SQLite import/validation and inspect warnings before relying on this read model."


def file_alert_state_counts(path: Path) -> dict[str, int | None]:
    if not path.exists():
        return {"alerts": None, "outcomes": None, "completed": None, "pending": None, "unscorable": None}
    alerts = load_alerts(path)
    return {
        "alerts": len(alerts),
        "outcomes": sum(1 for alert in alerts if alert.outcome is not None),
        "completed": sum(1 for alert in alerts if is_completed_alert(alert)),
        "pending": sum(1 for alert in alerts if is_pending_alert(alert)),
        "unscorable": sum(1 for alert in alerts if is_unscorable_alert(alert)),
    }


def file_minute_bar_count(path: Path) -> int | None:
    if not path.exists():
        return None
    parsed = parse_minute_bar_source(path)
    return len({(bar.symbol, bar.timestamp, bar.source) for bar in parsed["bars"]})


def file_capture_candidate_counts(path: Path) -> dict[str, int | None]:
    if not path.exists():
        return {"captures": None, "capture_candidates": None}
    rows, _warnings = read_analysis_capture_rows(path)
    capture_keys = {
        (
            row.get("capture_date", ""),
            row.get("capture_time", ""),
            row.get("session", ""),
            row.get("provider", ""),
            row.get("scanner", ""),
        )
        for row in rows
    }
    return {"captures": len(capture_keys), "capture_candidates": len(rows)}


def file_review_status_counts(path: Path) -> dict[str, int]:
    records, _warnings = load_review_source_records(path)
    counts: dict[str, int] = {}
    for record in records:
        status = record["decision"].review_status.value
        counts[status] = counts.get(status, 0) + 1
    return counts


def file_watchlist_item_count(data_dir: Path) -> int:
    count = 0
    for path in sorted(data_dir.glob("watchlist-*.json")):
        records, _warnings = load_watchlist_source_records(path)
        count += len(records)
    return count


def file_entry_plan_counts(path: Path) -> dict[str, int]:
    records, _warnings = load_entry_plan_source_records(path)
    complete = sum(1 for record in records if record["plan"].plan_complete)
    return {"total": len(records), "complete": complete, "incomplete": len(records) - complete}


def sqlite_review_status_counts(db_path: Path) -> dict[str, int]:
    with connect_database(db_path) as connection:
        return {
            str(row["review_status"]): int(row["count"])
            for row in connection.execute(
                "SELECT review_status, COUNT(*) AS count FROM candidate_reviews GROUP BY review_status"
            ).fetchall()
        }


def sqlite_entry_plan_counts(db_path: Path) -> dict[str, int]:
    with connect_database(db_path) as connection:
        total = int(connection.execute("SELECT COUNT(*) AS count FROM entry_plans").fetchone()["count"])
        complete = int(
            connection.execute("SELECT COUNT(*) AS count FROM entry_plans WHERE plan_complete = 1").fetchone()["count"]
        )
    return {"total": total, "complete": complete, "incomplete": total - complete}


def sqlite_alert_state_counts(db_path: Path) -> dict[str, int]:
    evidence = alert_evidence_summary(db_path=db_path)
    return {
        "completed": int(evidence["completed_outcomes"]),
        "pending": int(evidence["pending_outcomes"]),
        "unscorable": int(evidence["unscorable_outcomes"]),
    }


def compare_count(name: str, file_count: int | None, sqlite_count: int | None) -> dict[str, Any]:
    if file_count is None:
        return {
            "name": name,
            "status": "UNAVAILABLE",
            "file_count": None,
            "sqlite_count": sqlite_count,
            "message": "File source unavailable.",
        }
    if sqlite_count is None:
        return {
            "name": name,
            "status": "UNAVAILABLE",
            "file_count": file_count,
            "sqlite_count": None,
            "message": "SQLite source unavailable.",
        }
    status = "PASS" if int(file_count) == int(sqlite_count) else "MISMATCH"
    return {
        "name": name,
        "status": status,
        "file_count": int(file_count),
        "sqlite_count": int(sqlite_count),
        "message": f"file={file_count}, sqlite={sqlite_count}",
    }


def empty_payload(engine_version: str, generated_at: str, database: Path, warnings: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "engine_version": engine_version,
        "generated_at": generated_at,
        "database_path": str(database),
        "sqlite_schema_version": 0,
        "overall_status": "WARN",
        "warnings": warnings,
    }


def short_dt(value: Any) -> str:
    text = str(value or "")
    return text.replace("T", " ")[:16]


def format_pct(value: Any) -> str:
    number = optional_number(value)
    if number is None:
        return "n/a"
    return f"{number:.1f}%"


def display_count(value: Any) -> str:
    return "n/a" if value is None else str(value)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate read-only Momentum Hunter SQLite read model reports.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH)
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--all", action="store_true", help="Generate every SQLite read model report.")
    parser.add_argument(
        "--shadow-compare",
        action="store_true",
        help="Generate only the read-only file-vs-SQLite shadow comparison report.",
    )
    parser.add_argument(
        "--report",
        choices=REPORT_ORDER,
        action="append",
        help="Generate one report. Can be repeated. Defaults to all reports when omitted.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.shadow_compare and not args.all and not args.report:
        report_names = ["shadow-compare"]
    else:
        report_names = REPORT_ORDER if args.all or not args.report else args.report
        if args.shadow_compare and "shadow-compare" not in report_names:
            report_names = [*report_names, "shadow-compare"]
    payload = generate_reports(report_names, db_path=args.db, output_dir=args.output_dir)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
