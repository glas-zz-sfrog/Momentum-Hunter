from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.time_utils import now_central


REPORT_INDEX_SCHEMA_VERSION = 1
REPORT_INDEX_ENGINE_VERSION = "report_index_v1"
REPORTS_DIR = DATA_DIR / "reports"
REPORT_INDEX_LATEST_JSON = REPORTS_DIR / "report-index-latest.json"
REPORT_INDEX_LATEST_MD = REPORTS_DIR / "report-index-latest.md"
DEFAULT_STALE_AFTER_HOURS = 24


REPORT_DEFINITIONS: list[dict[str, str]] = [
    {
        "name": "SQLite Validation",
        "pattern": "sqlite-validation-latest.json",
        "description": "Validates SQLite mirror counts and status against file-authoritative sources.",
        "recommended_use": "Run before trusting SQLite read models.",
    },
    {
        "name": "SQLite All-Safe Import",
        "pattern": "sqlite-import-all-safe-latest.json",
        "description": "Latest additive all-safe SQLite import report.",
        "recommended_use": "Inspect after refreshing the SQLite mirror.",
    },
    {
        "name": "SQLite Shadow Compare",
        "pattern": "sqlite-shadow-compare-latest.json",
        "description": "Compares file summaries to SQLite read-model summaries.",
        "recommended_use": "Use as guardrail before optional SQLite read-mode experiments.",
    },
    {
        "name": "SQLite Mirror Freshness",
        "pattern": "sqlite-mirror-freshness-latest.json",
        "description": "Validates whether SQLite mirrors are current against file-authoritative source hashes and counts.",
        "recommended_use": "Run after all-safe imports and before trusting SQLite mirrors for offline analysis.",
    },
    {
        "name": "SQLite Query Benchmark",
        "pattern": "sqlite-query-benchmark-latest.json",
        "description": "Read-only query timing benchmark for SQLite evidence and operator analytics.",
        "recommended_use": "Use to detect slow read-model queries before heavier analysis or UI adoption.",
    },
    {
        "name": "Evidence Census",
        "pattern": "evidence-census-latest.json",
        "description": "Read-only census of alerts, captures, minute bars, evidence runs, and user-state mirror rows.",
        "recommended_use": "Use to understand current evidence sample size and coverage.",
    },
    {
        "name": "Candidate Data Completeness",
        "pattern": "candidate-data-completeness-latest.json",
        "description": "Field-completeness report for mirrored capture candidate rows.",
        "recommended_use": "Use before trusting analytics that depend on fields such as relative volume, market cap, or freshness.",
    },
    {
        "name": "System Readiness",
        "pattern": "system-readiness-latest.json",
        "description": "Top-level operator trust and readiness report.",
        "recommended_use": "Open first when deciding whether Momentum Hunter is operationally trustworthy.",
    },
    {
        "name": "Evidence Autopilot Reliability",
        "pattern": "evidence-autopilot-latest.json",
        "description": "Evidence Autopilot status, freshness, and evidence-completion reliability.",
        "recommended_use": "Use to confirm evidence collection is alive and not stale.",
    },
    {
        "name": "Active Alert Reliability",
        "pattern": "active-alert-reliability-latest.json",
        "description": "Alert identity, monitor freshness, outcome handoff, and SQLite alert mirror health.",
        "recommended_use": "Use before trusting active alert evidence.",
    },
    {
        "name": "Provider Field Quality",
        "pattern": "provider-field-quality-latest.json",
        "description": "Scanner/provider field quality audit for missing, zero, impossible, and stale values.",
        "recommended_use": "Use when relative volume, market cap, or provider fields look suspicious.",
    },
    {
        "name": "Market Tape Health",
        "pattern": "market-tape-health-*.json",
        "description": "Provider health checks for live/delayed quote usability.",
        "recommended_use": "Use when Active Monitor lacks market tape.",
    },
    {
        "name": "Candidate Story Read Model",
        "pattern": "sqlite-candidate-story-read-model-latest.json",
        "description": "SQLite-powered candidate-story read-model summary.",
        "recommended_use": "Use for report-only Candidate Story parity checks.",
    },
    {
        "name": "Watchlist Read Model",
        "pattern": "sqlite-watchlist-read-model-latest.json",
        "description": "SQLite-powered watchlist and entry-plan mirror summary.",
        "recommended_use": "Use for diagnostic watchlist/plan parity.",
    },
    {
        "name": "Evidence Read Model",
        "pattern": "sqlite-evidence-read-model-latest.json",
        "description": "SQLite-powered alert/outcome/minute-bar evidence summary.",
        "recommended_use": "Use for evidence mirror sanity checks.",
    },
    {
        "name": "Daily Evidence Brief",
        "pattern": "daily-evidence-brief-*.md",
        "description": "Human-readable daily evidence brief.",
        "recommended_use": "Read for operator-facing evidence status.",
    },
    {
        "name": "User-State Diff",
        "pattern": "sqlite-user-state-diff-latest.json",
        "description": "Compares file-authoritative review/watchlist/entry-plan state with SQLite mirror.",
        "recommended_use": "Run before any user-state cutover work.",
    },
    {
        "name": "User-State Backup",
        "pattern": "user-state-backup-latest.json",
        "description": "Latest user-state backup manifest/status.",
        "recommended_use": "Check before user-state maintenance or restore work.",
    },
    {
        "name": "User-State Cutover Simulation",
        "pattern": "user-state-cutover-simulation-latest.json",
        "description": "Synthetic disaster-recovery and cutover simulation for review decisions, watchlists, and entry plans.",
        "recommended_use": "Run before any SQLite user-state authority or cutover work.",
    },
    {
        "name": "Capture Health",
        "pattern": "capture-health-latest.json",
        "description": "Capture health and scheduled-capture status report.",
        "recommended_use": "Use when captures are missing, failed, or stale.",
    },
    {
        "name": "Operational Reliability",
        "pattern": "operational-reliability-sprint-v1-final-report.json",
        "description": "Classifies provider, evidence, monitor, readiness, capture, and report-index warnings into actionable categories.",
        "recommended_use": "Use as the top-level backend reliability triage before overnight or market-hours proof runs.",
    },
    {
        "name": "Market-Hours Proof Harness",
        "pattern": "market-hours-proof-harness-latest.json",
        "description": "Dry-run-first proof harness for market-hours provider, monitor, evidence, SQLite, and readiness validation.",
        "recommended_use": "Use to plan or execute a bounded market-hours proof cycle without changing trading logic.",
    },
    {
        "name": "SQLite Runtime Adoption Dry-Run",
        "pattern": "sqlite-runtime-adoption-dry-run-v1.json",
        "description": "Read-only cutover readiness report for optional SQLite runtime adoption experiments.",
        "recommended_use": "Use before any CLI/report surface tests SQLite read mode instead of file mode.",
    },
]


@dataclass(frozen=True)
class ReportIndexEntry:
    name: str
    latest_path: str
    exists: bool
    modified_at: str
    age_hours: float | None
    freshness: str
    status: str
    description: str
    recommended_use: str
    warnings: list[str]


def build_report_index(
    *,
    reports_dir: Path = REPORTS_DIR,
    generated_at: datetime | None = None,
    stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
) -> dict[str, Any]:
    generated_at = generated_at or now_central()
    entries = [
        build_entry(definition, reports_dir=reports_dir, generated_at=generated_at, stale_after_hours=stale_after_hours)
        for definition in REPORT_DEFINITIONS
    ]
    missing = sum(1 for entry in entries if not entry.exists)
    stale = sum(1 for entry in entries if entry.freshness == "STALE")
    warnings: list[str] = []
    if missing:
        warnings.append(f"MISSING_REPORTS:{missing}")
    if stale:
        warnings.append(f"STALE_REPORTS:{stale}")
    return {
        "schema_version": REPORT_INDEX_SCHEMA_VERSION,
        "engine_version": REPORT_INDEX_ENGINE_VERSION,
        "generated_at": generated_at.isoformat(),
        "reports_dir": str(reports_dir),
        "stale_after_hours": stale_after_hours,
        "overall_status": "WARN" if warnings else "PASS",
        "report_count": len(entries),
        "missing_report_count": missing,
        "stale_report_count": stale,
        "entries": [asdict(entry) for entry in entries],
        "warnings": warnings,
    }


def build_entry(
    definition: dict[str, str],
    *,
    reports_dir: Path,
    generated_at: datetime,
    stale_after_hours: int,
) -> ReportIndexEntry:
    path = latest_matching_path(reports_dir, definition["pattern"])
    if path is None:
        return ReportIndexEntry(
            name=definition["name"],
            latest_path="",
            exists=False,
            modified_at="",
            age_hours=None,
            freshness="MISSING",
            status="MISSING",
            description=definition["description"],
            recommended_use=definition["recommended_use"],
            warnings=["REPORT_MISSING"],
        )
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=generated_at.tzinfo)
    age_hours = max(0.0, (generated_at - modified).total_seconds() / 3600.0)
    freshness = "STALE" if age_hours > stale_after_hours else "FRESH"
    status = extract_status(path)
    warnings = []
    if freshness == "STALE":
        warnings.append("REPORT_STALE")
    if status in {"FAIL", "FAILED", "WARN", "WARNING", "UNKNOWN", "MISSING"}:
        warnings.append(f"REPORT_STATUS_{status}")
    return ReportIndexEntry(
        name=definition["name"],
        latest_path=str(path),
        exists=True,
        modified_at=modified.isoformat(),
        age_hours=round(age_hours, 3),
        freshness=freshness,
        status=status,
        description=definition["description"],
        recommended_use=definition["recommended_use"],
        warnings=warnings,
    )


def latest_matching_path(reports_dir: Path, pattern: str) -> Path | None:
    matches = [path for path in reports_dir.glob(pattern) if path.is_file()]
    if not matches:
        return None
    return max(matches, key=lambda path: path.stat().st_mtime)


def extract_status(path: Path) -> str:
    if path.suffix.lower() != ".json":
        return "AVAILABLE"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return "UNREADABLE"
    if not isinstance(payload, dict):
        return "UNREADABLE"
    raw = payload.get("report", payload)
    if isinstance(raw, dict):
        for key in ("overall_status", "status", "state", "latest_run_state"):
            value = raw.get(key)
            if value:
                return str(value)
    for key in ("overall_status", "status", "state", "latest_run_state"):
        value = payload.get(key)
        if value:
            return str(value)
    return "AVAILABLE"


def write_report_index(payload: dict[str, Any], *, output_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    ensure_app_dirs()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "report-index-latest.json"
    markdown_path = output_dir / "report-index-latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_report_index_markdown(payload), encoding="utf-8")
    return json_path, markdown_path


def format_report_index_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Momentum Hunter Report Index",
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Reports indexed: {payload.get('report_count', 0)}",
        f"- Missing reports: {payload.get('missing_report_count', 0)}",
        f"- Stale reports: {payload.get('stale_report_count', 0)}",
        "",
        "| Report | Status | Freshness | Age Hours | Latest Path | Use |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for entry in payload.get("entries", []):
        lines.append(
            f"| {entry.get('name', '')} | {entry.get('status', '')} | {entry.get('freshness', '')} | "
            f"{entry.get('age_hours', '') if entry.get('age_hours') is not None else ''} | "
            f"`{entry.get('latest_path', '')}` | {entry.get('recommended_use', '')} |"
        )
    warnings = payload.get("warnings") or []
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] if warnings else ["- None"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Momentum Hunter latest report/artifact index.")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR)
    parser.add_argument("--stale-after-hours", type=int, default=DEFAULT_STALE_AFTER_HOURS)
    args = parser.parse_args(argv)

    payload = build_report_index(reports_dir=args.reports_dir, stale_after_hours=args.stale_after_hours)
    json_path, markdown_path = write_report_index(payload, output_dir=args.output_dir)
    summary = {
        "overall_status": payload.get("overall_status"),
        "report_count": payload.get("report_count"),
        "missing_report_count": payload.get("missing_report_count"),
        "stale_report_count": payload.get("stale_report_count"),
        "warnings": payload.get("warnings", []),
        "report_paths": {"json": str(json_path), "markdown": str(markdown_path)},
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
