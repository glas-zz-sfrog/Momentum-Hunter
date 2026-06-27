from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR
from momentum_hunter.data_quality import DATA_QUALITY_LATEST_JSON
from momentum_hunter.alert_outcome_updater import ALERT_OUTCOME_UPDATE_STATUS_PATH, OPPORTUNITY_MINUTE_BARS_PATH
from momentum_hunter.entry_plans import ENTRY_PLANS_PATH
from momentum_hunter.opportunity_alerts import OPPORTUNITY_ALERTS_PATH
from momentum_hunter.review import REVIEW_DECISIONS_PATH
from momentum_hunter.storage import ANALYSIS_CSV, CAPTURE_INTEGRITY_MANIFEST, CAPTURES_DIR


SOURCE_REGISTRY_VERSION = "source_classification_and_mirror_freshness_v1"


@dataclass(frozen=True)
class SourceDefinition:
    name: str
    category: str
    authority: str
    mutability: str
    path: str
    pattern: str
    sqlite_tables: tuple[str, ...]
    importer: str
    included_in_all_safe: bool
    preservation_rule: str
    cleanup_rule: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sqlite_tables"] = list(self.sqlite_tables)
        return payload


def registered_source_definitions(
    *,
    data_dir: Path = DATA_DIR,
    reports_dir: Path | None = None,
    analysis_captures_path: Path = ANALYSIS_CSV,
    captures_dir: Path = CAPTURES_DIR,
    data_quality_report: Path = DATA_QUALITY_LATEST_JSON,
    alerts_path: Path = OPPORTUNITY_ALERTS_PATH,
    minute_bars_path: Path = OPPORTUNITY_MINUTE_BARS_PATH,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    entry_plans_path: Path = ENTRY_PLANS_PATH,
    integrity_manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
) -> list[SourceDefinition]:
    reports_dir = reports_dir or data_dir / "reports"
    return [
        SourceDefinition(
            name="raw_captures_json",
            category="raw_capture",
            authority="immutable_source_of_truth",
            mutability="immutable",
            path=str(captures_dir),
            pattern="*/*.json",
            sqlite_tables=("captures",),
            importer="import_capture_candidate_index",
            included_in_all_safe=True,
            preservation_rule="Never mutate in place. Quarantine or restore on integrity failure.",
            cleanup_rule="Do not delete. Exclude/quarantine through integrity metadata.",
            notes="Raw capture JSON files are referenced by the capture index but are not rewritten by SQLite imports.",
        ),
        SourceDefinition(
            name="raw_captures_markdown",
            category="raw_capture_human_snapshot",
            authority="immutable_source_of_truth",
            mutability="immutable",
            path=str(captures_dir),
            pattern="*/*.md",
            sqlite_tables=(),
            importer="not_mirrored",
            included_in_all_safe=False,
            preservation_rule="Never mutate in place. Preserve as human-readable raw snapshot companion.",
            cleanup_rule="Do not delete. Quarantine with matching JSON when required.",
            notes="Human-readable capture companions are intentionally outside the SQLite mirror.",
        ),
        SourceDefinition(
            name="analysis_capture_index",
            category="derived_analysis_index",
            authority="file_authoritative_derived",
            mutability="rebuildable",
            path=str(analysis_captures_path),
            pattern="",
            sqlite_tables=("captures", "capture_candidates"),
            importer="import_capture_candidate_index",
            included_in_all_safe=True,
            preservation_rule="May be rebuilt from trusted raw captures. Do not treat as raw history.",
            cleanup_rule="Rebuild from active trusted captures when drift is detected.",
            notes="This CSV is the current file source for the additive capture/candidate SQLite mirror.",
        ),
        SourceDefinition(
            name="provider_quality_report",
            category="derived_report",
            authority="file_authoritative_derived",
            mutability="latest_report",
            path=str(data_quality_report),
            pattern="",
            sqlite_tables=("provider_quality_checks",),
            importer="import_provider_quality_report",
            included_in_all_safe=True,
            preservation_rule="Latest report may be regenerated. SQLite stores additive mirror rows by source hash.",
            cleanup_rule="Regenerate and re-import if stale.",
            notes="Provider field quality report supports data-quality and market-tape trust checks.",
        ),
        SourceDefinition(
            name="opportunity_alerts",
            category="derived_evidence_store",
            authority="file_authoritative_derived",
            mutability="mutable_derived",
            path=str(alerts_path),
            pattern="",
            sqlite_tables=("opportunity_alerts", "alert_outcomes"),
            importer="import_opportunity_alerts",
            included_in_all_safe=True,
            preservation_rule="Preserve alert facts. Outcome metadata may mature but raw captures remain untouched.",
            cleanup_rule="Re-import idempotently after outcome updates.",
            notes="Primary file store for active alert evidence and outcome classifications.",
        ),
        SourceDefinition(
            name="opportunity_minute_bars",
            category="derived_market_data_cache",
            authority="file_authoritative_derived",
            mutability="mutable_cache",
            path=str(minute_bars_path),
            pattern="",
            sqlite_tables=("minute_bars",),
            importer="import_minute_bars",
            included_in_all_safe=True,
            preservation_rule="Preserve as derived evidence cache. It can be rebuilt/refetched separately from raw captures.",
            cleanup_rule="Re-import idempotently after minute-bar refresh.",
            notes="Minute bars support alert outcome validation and later analytics.",
        ),
        SourceDefinition(
            name="evidence_run_reports",
            category="derived_reports",
            authority="file_authoritative_derived",
            mutability="latest_and_timestamped_reports",
            path=str(reports_dir),
            pattern="evidence-autopilot-latest.json; evidence-health-report-*.json; reliability-report-*.json; alert-performance-report-*.json",
            sqlite_tables=("evidence_runs", "evidence_metrics"),
            importer="import_evidence_runs",
            included_in_all_safe=True,
            preservation_rule="Reports may regenerate. Preserve timestamped reports where generated.",
            cleanup_rule="Importer removes stale mirror rows for latest-style source replacements.",
            notes="Evidence report mirror is additive for analysis; source reports remain file authoritative.",
        ),
        SourceDefinition(
            name="system_status_sources",
            category="derived_status_reports",
            authority="file_authoritative_derived",
            mutability="latest_status",
            path=str(data_dir),
            pattern="active-monitor-status.json; evidence-autopilot-status.json; alert-outcome-update-status.json; reports/system-readiness-latest.json; reports/data-quality-latest.json; reports/market-tape-health-*.json",
            sqlite_tables=("system_status_events",),
            importer="import_system_status_events",
            included_in_all_safe=True,
            preservation_rule="Status files may update. Preserve source files and mirror status events separately.",
            cleanup_rule="Importer removes stale mirror events for latest-style source replacements.",
            notes="System status sources power readiness and reliability diagnostics.",
        ),
        SourceDefinition(
            name="review_decisions",
            category="user_state",
            authority="file_authoritative_user_state",
            mutability="mutable_user_authored",
            path=str(review_decisions_path),
            pattern="",
            sqlite_tables=("candidate_reviews",),
            importer="import_user_state",
            included_in_all_safe=False,
            preservation_rule="Back up before migration/cutover. Do not overwrite silently.",
            cleanup_rule="Use user-state safety cage and diff reports before any repair.",
            notes="Not part of all-safe import; requires explicit user-state import/cutover workflow.",
        ),
        SourceDefinition(
            name="watchlists",
            category="user_artifact",
            authority="file_authoritative_user_artifact",
            mutability="mutable_user_artifact",
            path=str(data_dir),
            pattern="watchlist-*.json",
            sqlite_tables=("watchlist_items",),
            importer="import_user_state",
            included_in_all_safe=False,
            preservation_rule="Back up before migration/cutover. Preserve generated watchlist artifacts.",
            cleanup_rule="Use user-state safety cage and diff reports before any repair.",
            notes="Not part of all-safe import; mirrors only during explicit user-state workflows.",
        ),
        SourceDefinition(
            name="entry_plans",
            category="user_state",
            authority="file_authoritative_user_state",
            mutability="mutable_user_authored",
            path=str(entry_plans_path),
            pattern="",
            sqlite_tables=("entry_plans",),
            importer="import_user_state",
            included_in_all_safe=False,
            preservation_rule="Back up before migration/cutover. Do not overwrite silently.",
            cleanup_rule="Use user-state safety cage and diff reports before any repair.",
            notes="Not part of all-safe import; requires explicit user-state import/cutover workflow.",
        ),
        SourceDefinition(
            name="capture_integrity_manifest",
            category="integrity_metadata",
            authority="file_authoritative_integrity_metadata",
            mutability="append_or_rebuild_with_explicit_policy",
            path=str(integrity_manifest_path),
            pattern="",
            sqlite_tables=(),
            importer="not_mirrored",
            included_in_all_safe=False,
            preservation_rule="Do not re-bless modified captures silently. Keep integrity metadata separate from raw captures.",
            cleanup_rule="Use integrity audit and quarantine/recovery policy.",
            notes="Tracks source hashes for immutable raw captures; intentionally separate from raw capture files.",
        ),
    ]


def source_registry_payload(**kwargs: Any) -> dict[str, Any]:
    definitions = registered_source_definitions(**kwargs)
    return {
        "schema_version": 1,
        "engine_version": SOURCE_REGISTRY_VERSION,
        "sources": [definition.to_dict() for definition in definitions],
    }


def definitions_by_table(definitions: list[SourceDefinition]) -> dict[str, list[SourceDefinition]]:
    by_table: dict[str, list[SourceDefinition]] = {}
    for definition in definitions:
        for table in definition.sqlite_tables:
            by_table.setdefault(table, []).append(definition)
    return by_table
