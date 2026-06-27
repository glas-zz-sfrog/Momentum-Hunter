from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.alert_outcome_updater import OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.entry_plans import ENTRY_PLANS_PATH
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH
from momentum_hunter.read_models import READ_MODEL_SOURCE_ENV, build_shadow_compare_read_model, resolve_read_model_source
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.sqlite_store import SQLITE_DB_PATH
from momentum_hunter.sqlite_validation import build_sqlite_validation_report
from momentum_hunter.storage import ANALYSIS_CSV
from momentum_hunter.time_utils import now_central


REPORTS_DIR = DATA_DIR / "reports"
SQLITE_RUNTIME_ADOPTION_LATEST_JSON = REPORTS_DIR / "sqlite-runtime-adoption-dry-run-v1.json"
SQLITE_RUNTIME_ADOPTION_LATEST_MD = REPORTS_DIR / "sqlite-runtime-adoption-dry-run-v1.md"
ENGINE_VERSION = "sqlite_runtime_adoption_dry_run_v1"


@dataclass(frozen=True)
class AdoptionSurface:
    name: str
    classification: str
    current_source: str
    sqlite_source: str
    fallback: str
    risk: str
    recommendation: str
    required_checks: list[str]


SURFACES: list[AdoptionSurface] = [
    AdoptionSurface(
        name="Evidence reports",
        classification="SAFE_OPTIONAL",
        current_source="opportunity-alerts.json, opportunity-minute-bars.json, evidence report JSON",
        sqlite_source="opportunity_alerts, alert_outcomes, minute_bars, evidence_runs",
        fallback="Return to JSON alert/minute-bar stores if SQLite is missing, stale, or mismatched.",
        risk="LOW",
        recommendation="Safe for CLI/report read-only experiments. Runtime default remains file.",
        required_checks=["alert count parity", "outcome class parity", "unscorable preservation", "minute-bar parity"],
    ),
    AdoptionSurface(
        name="System Readiness / Health report summaries",
        classification="SAFE_OPTIONAL",
        current_source="latest readiness/reliability/status JSON files",
        sqlite_source="system_status_events, provider_quality_checks, evidence_runs",
        fallback="Return to latest status JSON files.",
        risk="LOW",
        recommendation="Safe for read-only summaries after validation and freshness checks pass.",
        required_checks=["status normalization parity", "missing status-file warnings", "stale import detection"],
    ),
    AdoptionSurface(
        name="Watchlist / Plans diagnostic reports",
        classification="SAFE_OPTIONAL",
        current_source="review-decisions.json, watchlist artifacts, entry-plans.json",
        sqlite_source="candidate_reviews, watchlist_items, entry_plans",
        fallback="Return to user-authored JSON and watchlist artifacts.",
        risk="MEDIUM",
        recommendation="Safe for diagnostics only. Writes and UI state remain file-authoritative.",
        required_checks=["review-status parity", "entry-plan completeness parity", "backup/diff freshness"],
    ),
    AdoptionSurface(
        name="Candidate Story / Timeline reports",
        classification="SHADOW_ONLY",
        current_source="analysis-captures.csv, active raw captures, outcome CSV, review JSON",
        sqlite_source="captures, capture_candidates, candidate_reviews, entry_plans",
        fallback="Use existing Replay file/raw-capture path for UI and point-in-time views.",
        risk="MEDIUM",
        recommendation="Use SQLite for report-only parity checks. Keep UI in shadow mode.",
        required_checks=["point-in-time identity", "historical row parity", "raw-capture no-mutation"],
    ),
    AdoptionSurface(
        name="Alert Performance analytics",
        classification="SHADOW_ONLY",
        current_source="opportunity-alerts.json and embedded alert outcomes",
        sqlite_source="opportunity_alerts, alert_outcomes, minute_bars",
        fallback="Use alert JSON until grouping/math parity is explicitly tested.",
        risk="MEDIUM",
        recommendation="Keep shadow-only until completed-only math and unscorable exclusion are verified.",
        required_checks=["alert-type grouping parity", "symbol grouping parity", "completed-only return math parity"],
    ),
    AdoptionSurface(
        name="Dashboard summary cards",
        classification="SHADOW_ONLY",
        current_source="live app state, latest JSON reports, active capture context",
        sqlite_source="read-model summaries and status events",
        fallback="Use existing dashboard state and latest JSON files.",
        risk="MEDIUM",
        recommendation="No default UI switch. Use shadow compare only.",
        required_checks=["UI responsiveness", "stale SQLite banner", "missing DB fallback"],
    ),
    AdoptionSurface(
        name="Research Lab",
        classification="DEFERRED",
        current_source="analysis-captures.csv, outcomes CSV, raw captures, clusters, score breakdowns",
        sqlite_source="partial mirrors only",
        fallback="Use existing file/research engines.",
        risk="HIGH",
        recommendation="Defer until full study filter and cluster parity exists.",
        required_checks=["full study filters", "non-study exclusion", "cluster parity", "outcome math parity"],
    ),
    AdoptionSurface(
        name="Opportunity Research",
        classification="DEFERRED",
        current_source="analysis-captures.csv, analysis-outcomes.csv, clusters, score breakdowns, review JSON",
        sqlite_source="partial mirrors only",
        fallback="Use existing file-based research path.",
        risk="HIGH",
        recommendation="Defer until study outcomes and research feature mirrors are complete.",
        required_checks=["grouping parity", "pending exclusion", "sample warning parity", "cluster metric parity"],
    ),
    AdoptionSurface(
        name="Outcome Explorer",
        classification="DEFERRED",
        current_source="analysis-captures.csv, analysis-outcomes.csv, clusters, review JSON",
        sqlite_source="partial mirrors; alert outcomes are mirrored but study outcomes remain CSV-first",
        fallback="Use existing file-based Outcome Explorer.",
        risk="HIGH",
        recommendation="Defer until study outcome parity is proven.",
        required_checks=["study outcome parity", "filter parity", "completed/pending math parity"],
    ),
    AdoptionSurface(
        name="User-state write paths",
        classification="BLOCKED_FOR_WRITES",
        current_source="review-decisions.json, entry-plans.json, watchlist artifacts",
        sqlite_source="candidate_reviews, entry_plans, watchlist_items",
        fallback="User-authored files remain authoritative.",
        risk="HIGH",
        recommendation="Blocked. SQLite must not become user-state authority in this slice.",
        required_checks=["backup/restore", "conflict simulation", "rollback simulation", "explicit cutover approval"],
    ),
]


def build_sqlite_runtime_adoption_dry_run(
    *,
    db_path: Path | None = None,
    data_dir: Path = DATA_DIR,
    data_quality_report: Path = DATA_QUALITY_LATEST_JSON,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    analysis_captures_path: Path = ANALYSIS_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    evidence_run_source_paths: list[Path] | None = None,
    system_status_source_paths: list[Path] | None = None,
    reports: list[str] | None = None,
    validate_shadow_sqlite: bool = True,
    validation_payload: dict[str, Any] | None = None,
    shadow_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generated_at = now_central().isoformat()
    database = db_path or SQLITE_DB_PATH
    warnings: list[str] = []

    if validation_payload is None:
        validation_payload = build_sqlite_validation_report(
            db_path=database,
            data_quality_report=data_quality_report,
            alerts_path=alerts_path,
            minute_bars_path=minute_bars_path,
            analysis_captures_path=analysis_captures_path,
            evidence_run_source_paths=evidence_run_source_paths,
            system_status_source_paths=system_status_source_paths,
        )
    if shadow_payload is None:
        shadow_payload = build_shadow_compare_read_model(
            db_path=database,
            data_dir=data_dir,
            analysis_captures_path=analysis_captures_path,
            review_decisions_path=review_decisions_path,
            entry_plans_path=entry_plans_path,
            alerts_path=alerts_path,
            minute_bars_path=minute_bars_path,
            reports=reports,
            validate_sqlite=validate_shadow_sqlite,
        )

    validation_status = str(validation_payload.get("overall_status") or "UNKNOWN")
    shadow_status = str(shadow_payload.get("overall_status") or "UNKNOWN")
    stale_sqlite_data = bool(shadow_payload.get("stale_sqlite_data", False))
    missing_slices = list(validation_payload.get("missing_slices") or [])

    if not database.exists():
        warnings.append(f"SQLITE_DATABASE_MISSING:{database}")
    if validation_status != "PASS":
        warnings.append(f"SQLITE_VALIDATION_NOT_PASS:{validation_status}")
    if shadow_status != "PASS":
        warnings.append(f"SQLITE_SHADOW_COMPARE_NOT_PASS:{shadow_status}")
    if stale_sqlite_data:
        warnings.append("SQLITE_STALE_OR_MISMATCHED")
    if missing_slices:
        warnings.append("SQLITE_MISSING_SLICES:" + ",".join(str(item) for item in missing_slices))

    classification_counts = surface_classification_counts(SURFACES)
    cutover_status = "BLOCKED" if warnings else "NOT_REQUESTED"
    optional_read_mode_status = "READY_FOR_CLI_REPORTS" if validation_status == "PASS" and shadow_status == "PASS" else "USE_FILE_FALLBACK"
    return {
        "schema_version": 1,
        "engine_version": ENGINE_VERSION,
        "generated_at": generated_at,
        "database_path": str(database),
        "database_exists": database.exists(),
        "read_model_env_var": READ_MODEL_SOURCE_ENV,
        "runtime_default_source": "file",
        "configured_source_mode": resolve_read_model_source(),
        "sqlite_authoritative": False,
        "validation_status": validation_status,
        "shadow_compare_status": shadow_status,
        "shadow_reports_compared": shadow_payload.get("reports_compared", []),
        "shadow_mismatches": int(shadow_payload.get("mismatches", 0) or 0),
        "shadow_unavailable": int(shadow_payload.get("unavailable", 0) or 0),
        "stale_sqlite_data": stale_sqlite_data,
        "missing_slices": missing_slices,
        "fallback_behavior": fallback_behavior(database.exists(), stale_sqlite_data, validation_status, shadow_status),
        "cutover_status": cutover_status,
        "optional_read_mode_status": optional_read_mode_status,
        "adoption_surfaces": [asdict(surface) for surface in SURFACES],
        "surface_classification_counts": classification_counts,
        "safe_optional_surfaces": [surface.name for surface in SURFACES if surface.classification == "SAFE_OPTIONAL"],
        "shadow_only_surfaces": [surface.name for surface in SURFACES if surface.classification == "SHADOW_ONLY"],
        "deferred_surfaces": [surface.name for surface in SURFACES if surface.classification == "DEFERRED"],
        "blocked_write_surfaces": [surface.name for surface in SURFACES if surface.classification == "BLOCKED_FOR_WRITES"],
        "sqlite_can_help_now": sqlite_can_help_now(),
        "sqlite_cannot_help_yet": sqlite_cannot_help_yet(),
        "safety_notes": safety_notes(),
        "recommended_next_action": recommended_next_action(warnings),
        "validation_summary": {
            "table_counts": validation_payload.get("table_counts", {}),
            "warnings": validation_payload.get("warnings", []),
        },
        "shadow_summary": {
            "fallback_reason": shadow_payload.get("fallback_reason", ""),
            "recommended_action": shadow_payload.get("recommended_action", ""),
            "warnings": shadow_payload.get("warnings", []),
            "missing_data": shadow_payload.get("missing_data", []),
        },
        "warnings": sorted(set(str(item) for item in warnings)),
    }


def write_sqlite_runtime_adoption_report(
    payload: dict[str, Any],
    *,
    json_path: Path = SQLITE_RUNTIME_ADOPTION_LATEST_JSON,
    markdown_path: Path = SQLITE_RUNTIME_ADOPTION_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# SQLite Runtime Adoption Dry-Run v1",
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Database: `{payload.get('database_path', '')}`",
        f"- Runtime default source: `{payload.get('runtime_default_source', 'file')}`",
        f"- Configured source mode: `{payload.get('configured_source_mode', 'file')}`",
        f"- SQLite authoritative: `{payload.get('sqlite_authoritative', False)}`",
        f"- Validation status: `{payload.get('validation_status', 'UNKNOWN')}`",
        f"- Shadow compare status: `{payload.get('shadow_compare_status', 'UNKNOWN')}`",
        f"- Stale SQLite data: `{payload.get('stale_sqlite_data', False)}`",
        f"- Optional read mode status: `{payload.get('optional_read_mode_status', 'UNKNOWN')}`",
        f"- Cutover status: `{payload.get('cutover_status', 'UNKNOWN')}`",
        "",
        "## Decision",
        "",
        payload.get("recommended_next_action", ""),
        "",
        "## Fallback Behavior",
        "",
        payload.get("fallback_behavior", ""),
        "",
        "## Surface Matrix",
        "",
        "| Surface | Classification | Risk | Recommendation |",
        "| --- | --- | --- | --- |",
    ]
    for surface in payload.get("adoption_surfaces", []):
        lines.append(
            f"| {surface.get('name', '')} | {surface.get('classification', '')} | "
            f"{surface.get('risk', '')} | {surface.get('recommendation', '')} |"
        )
    lines.extend(
        [
            "",
            "## SQLite Can Help Now",
            "",
            *[f"- {item}" for item in payload.get("sqlite_can_help_now", [])],
            "",
            "## SQLite Cannot Help Yet",
            "",
            *[f"- {item}" for item in payload.get("sqlite_cannot_help_yet", [])],
            "",
            "## Safety Notes",
            "",
            *[f"- {item}" for item in payload.get("safety_notes", [])],
        ]
    )
    warnings = payload.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines) + "\n"


def surface_classification_counts(surfaces: list[AdoptionSurface]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for surface in surfaces:
        counts[surface.classification] = counts.get(surface.classification, 0) + 1
    return counts


def fallback_behavior(database_exists: bool, stale_sqlite_data: bool, validation_status: str, shadow_status: str) -> str:
    if not database_exists:
        return "SQLite database is missing. Runtime must stay on file mode and report surfaces should warn cleanly."
    if validation_status != "PASS":
        return "SQLite validation is not PASS. Runtime must stay on file mode until import/validation is repaired."
    if shadow_status != "PASS" or stale_sqlite_data:
        return "SQLite shadow compare is not clean. Runtime must stay on file mode and use shadow output for diagnostics."
    return "SQLite appears current for supported read models, but runtime still remains file-default until explicit cutover approval."


def sqlite_can_help_now() -> list[str]:
    return [
        "Read-only CLI/report summaries for evidence, readiness, watchlist diagnostics, and Candidate Story parity checks.",
        "Shadow comparison before any future runtime read adoption.",
        "Offline analysis where file sources remain authoritative and JSON/CSV outputs remain available.",
    ]


def sqlite_cannot_help_yet() -> list[str]:
    return [
        "User-state writes, including review decisions, watchlists, and entry plans.",
        "Research Lab, Outcome Explorer, and Opportunity Research runtime replacement.",
        "Any source-of-truth migration for raw captures, score breakdowns, alert logic, readiness, or trade planning.",
    ]


def safety_notes() -> list[str]:
    return [
        "This dry-run is read-only except for derived report output under MomentumHunterData/data/reports.",
        "Raw captures are not read-modified-written by this module.",
        "JSON/CSV/Markdown file outputs remain available and file fallback remains mandatory.",
        "SQLite is additive and not authoritative in this milestone.",
    ]


def recommended_next_action(warnings: list[str]) -> str:
    if warnings:
        return "Keep runtime file-based. Refresh SQLite imports and inspect validation/shadow warnings before any optional read-mode test."
    return "Keep runtime file-based. Optional SQLite read mode is limited to CLI/report surfaces with file fallback and shadow compare guardrails."


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the SQLite runtime adoption dry-run report.")
    parser.add_argument("--db", type=Path, default=SQLITE_DB_PATH, help="SQLite database path.")
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR, help="Directory for generated reports.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = build_sqlite_runtime_adoption_dry_run(db_path=args.db)
    write_sqlite_runtime_adoption_report(
        payload,
        json_path=args.output_dir / SQLITE_RUNTIME_ADOPTION_LATEST_JSON.name,
        markdown_path=args.output_dir / SQLITE_RUNTIME_ADOPTION_LATEST_MD.name,
    )
    print(json.dumps({"status": payload["optional_read_mode_status"], "warnings": payload["warnings"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
