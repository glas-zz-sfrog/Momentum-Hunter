from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from momentum_hunter.config import DATA_DIR
from momentum_hunter.integrity import MODIFIED, audit_manifest_records, audit_raw_captures, overall_audit_status, write_integrity_audit_report
from momentum_hunter.outcomes import OUTCOMES_CSV
from momentum_hunter.quarantine import (
    QUARANTINE_DIR,
    QuarantineResult,
    normalize_existing_quarantine_layout,
    quarantine_batch_id,
    quarantine_raw_capture,
)
from momentum_hunter.rebuild_derived import RebuildResult, rebuild_derived_data_from_raw_captures
from momentum_hunter.review import REVIEW_DECISIONS_PATH, mark_review_decisions_for_quarantined_capture
from momentum_hunter.storage import ANALYSIS_CSV, CAPTURE_INTEGRITY_MANIFEST, CAPTURES_DIR, load_capture_integrity_manifest
from momentum_hunter.time_utils import now_central


DEFAULT_REASON = (
    "Raw capture hash differs from integrity manifest. Original file was not available; "
    "quarantined instead of silently re-baselining."
)


@dataclass(frozen=True)
class ModifiedCaptureGroup:
    capture_date: str
    session: str
    provider: str
    scanner: str
    modified_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ModifiedCaptureRecoveryResult:
    before_status: str
    after_status: str
    before_summary: str
    after_summary: str
    quarantine_results: list[QuarantineResult]
    migrated_quarantines: list[QuarantineResult]
    rebuild_result: RebuildResult | None
    review_decisions_marked: int
    before_audit_report: Path
    after_audit_report: Path


def recover_modified_raw_captures(
    *,
    reason: str = DEFAULT_REASON,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    quarantine_root: Path = QUARANTINE_DIR,
    analysis_csv: Path = ANALYSIS_CSV,
    outcomes_csv: Path = OUTCOMES_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    outcome_session: requests.Session | None = None,
    rebuild_outcomes: bool = True,
    normalize_existing_quarantines: bool = False,
    recovered_at: datetime | None = None,
    before_audit_csv: Path | None = None,
    before_audit_report: Path | None = None,
    after_audit_csv: Path | None = None,
    after_audit_report: Path | None = None,
) -> ModifiedCaptureRecoveryResult:
    recovered_at = recovered_at or now_central()
    batch_id = quarantine_batch_id(recovered_at)

    before_rows = audit_raw_captures(
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        analysis_csv=analysis_csv,
        outcomes_csv=outcomes_csv,
        review_decisions_path=review_decisions_path,
    )
    before_csv, before_report = write_integrity_audit_report(
        before_rows,
        csv_path=before_audit_csv or DATA_DIR / "integrity" / "modified_capture_recovery_before.csv",
        markdown_path=before_audit_report or DATA_DIR / "integrity" / "modified_capture_recovery_before.md",
    )
    del before_csv

    migrated = normalize_existing_quarantine_layout(manifest_path=manifest_path, quarantine_root=quarantine_root) if normalize_existing_quarantines else []
    quarantine_results: list[QuarantineResult] = []
    review_decisions_marked = 0
    for group in modified_capture_groups(manifest_path):
        result = quarantine_raw_capture(
            group.capture_date,
            group.session,
            reason=reason,
            captures_dir=captures_dir,
            manifest_path=manifest_path,
            quarantine_root=quarantine_root,
            quarantined_at=recovered_at,
            batch_id=batch_id,
        )
        quarantine_results.append(result)
        review_decisions_marked += mark_review_decisions_for_quarantined_capture(
            capture_date=group.capture_date,
            session=group.session,
            provider=group.provider,
            scanner=group.scanner,
            quarantined_at=recovered_at.isoformat(),
            reason=reason,
            path=review_decisions_path,
        )

    rebuild_result: RebuildResult | None = None
    if quarantine_results or migrated:
        rebuild_result = rebuild_derived_data_from_raw_captures(
            captures_dir=captures_dir,
            analysis_csv=analysis_csv,
            outcomes_csv=outcomes_csv,
            manifest_path=manifest_path,
            review_decisions_path=review_decisions_path,
            outcome_session=outcome_session,
            rebuild_outcomes=rebuild_outcomes,
        )

    after_rows = audit_raw_captures(
        captures_dir=captures_dir,
        manifest_path=manifest_path,
        analysis_csv=analysis_csv,
        outcomes_csv=outcomes_csv,
        review_decisions_path=review_decisions_path,
    )
    after_csv, after_report = write_integrity_audit_report(
        after_rows,
        csv_path=after_audit_csv or DATA_DIR / "integrity" / "modified_capture_recovery_after.csv",
        markdown_path=after_audit_report or DATA_DIR / "integrity" / "modified_capture_recovery_after.md",
    )
    del after_csv

    return ModifiedCaptureRecoveryResult(
        before_status=overall_audit_status(before_rows),
        after_status=overall_audit_status(after_rows),
        before_summary=audit_summary(before_rows),
        after_summary=audit_summary(after_rows),
        quarantine_results=quarantine_results,
        migrated_quarantines=migrated,
        rebuild_result=rebuild_result,
        review_decisions_marked=review_decisions_marked,
        before_audit_report=before_report,
        after_audit_report=after_report,
    )


def modified_capture_groups(manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST) -> list[ModifiedCaptureGroup]:
    modified_paths = {row.path for row in audit_manifest_records(manifest_path) if row.status == MODIFIED}
    if not modified_paths:
        return []
    manifest = load_capture_integrity_manifest(manifest_path)
    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for path in sorted(modified_paths):
        record = manifest.get("records", {}).get(path, {})
        capture_date = record.get("capture_date", "")
        session = record.get("session", "")
        provider = record.get("provider", "")
        scanner = record.get("scanner", "")
        grouped.setdefault((capture_date, session, provider, scanner), []).append(path)
    return [
        ModifiedCaptureGroup(
            capture_date=capture_date,
            session=session,
            provider=provider,
            scanner=scanner,
            modified_paths=paths,
        )
        for (capture_date, session, provider, scanner), paths in sorted(grouped.items())
        if capture_date and session
    ]


def audit_summary(rows) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    if not counts:
        return "No rows"
    return ", ".join(f"{status}={count}" for status, count in sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Recover modified Momentum Hunter raw captures by quarantining them.")
    parser.add_argument("--reason", default=DEFAULT_REASON, help="Recovery reason written to notes.")
    parser.add_argument("--skip-outcomes", action="store_true", help="Rebuild analysis CSV only; skip outcome refresh.")
    parser.add_argument(
        "--normalize-existing-quarantine",
        action="store_true",
        help="Move existing quarantined raw files into timestamped quarantine folders.",
    )
    args = parser.parse_args()

    result = recover_modified_raw_captures(
        reason=args.reason,
        rebuild_outcomes=not args.skip_outcomes,
        normalize_existing_quarantines=args.normalize_existing_quarantine,
    )
    print(f"Before Audit: {result.before_status} ({result.before_summary})")
    print(f"After Audit: {result.after_status} ({result.after_summary})")
    print(f"Before Report: {result.before_audit_report}")
    print(f"After Report: {result.after_audit_report}")
    for item in [*result.quarantine_results, *result.migrated_quarantines]:
        print(f"Quarantine Dir: {item.quarantine_dir}")
        print(f"Recovery Note: {item.note_path}")
        print(f"Files Moved: {len(item.moved_paths)}")
    if result.rebuild_result:
        print(f"Analysis Rows: {result.rebuild_result.analysis_rows}")
        print(f"Outcome Rows: {result.rebuild_result.outcome_rows}")
        print(f"Rebuild Backup Dir: {result.rebuild_result.backup_dir}")
    else:
        print("No modified active raw captures found; rebuild not required.")
    print(f"Review Decisions Marked: {result.review_decisions_marked}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
