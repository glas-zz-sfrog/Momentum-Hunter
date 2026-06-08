from __future__ import annotations

import argparse
import csv
import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.outcomes import OUTCOME_FIELDNAMES, OUTCOMES_CSV
from momentum_hunter.quarantine import QUARANTINE_DIR, QuarantineResult, quarantine_raw_capture
from momentum_hunter.rebuild_derived import build_analysis_rows_from_raw_captures
from momentum_hunter.review import REVIEW_DECISIONS_PATH, mark_review_decisions_for_quarantined_capture
from momentum_hunter.scheduling import calendar_fieldnames, classify_capture
from momentum_hunter.storage import (
    ANALYSIS_CSV,
    CAPTURE_INTEGRITY_MANIFEST,
    CAPTURES_DIR,
    write_analysis_rows,
)
from momentum_hunter.time_utils import now_central


DEFAULT_LEGACY_SESSIONS = ("morning", "evening")
DEFAULT_REASON = (
    "Sunday legacy-style capture lacked market-calendar metadata or was non-study-eligible; "
    "valid preopen capture preserved."
)


@dataclass(frozen=True)
class LegacyCaptureCleanupResult:
    capture_date: str
    sessions_checked: list[str]
    quarantine_results: list[QuarantineResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    review_decisions_marked: int = 0
    analysis_rows: int = 0
    outcome_rows: int = 0
    analysis_path: Path = ANALYSIS_CSV
    outcomes_path: Path = OUTCOMES_CSV
    backup_dir: Path | None = None
    backups: list[Path] = field(default_factory=list)

    @property
    def quarantined_sessions(self) -> list[str]:
        return [result.session for result in self.quarantine_results]


def cleanup_legacy_non_study_captures(
    capture_date: str,
    *,
    sessions: tuple[str, ...] = DEFAULT_LEGACY_SESSIONS,
    reason: str = DEFAULT_REASON,
    captures_dir: Path = CAPTURES_DIR,
    manifest_path: Path = CAPTURE_INTEGRITY_MANIFEST,
    quarantine_root: Path = QUARANTINE_DIR,
    analysis_csv: Path = ANALYSIS_CSV,
    outcomes_csv: Path = OUTCOMES_CSV,
    review_decisions_path: Path = REVIEW_DECISIONS_PATH,
    cleaned_at: datetime | None = None,
    backup_dir: Path | None = None,
) -> LegacyCaptureCleanupResult:
    ensure_app_dirs()
    cleaned_at = cleaned_at or now_central()
    quarantine_results: list[QuarantineResult] = []
    skipped: list[str] = []
    marked_decisions = 0
    batch_id = cleaned_at.strftime("%Y%m%d-%H%M%S")
    backup_dir = backup_dir or DATA_DIR / "backups" / "legacy-cleanup" / batch_id
    backups = backup_existing_derived_files([analysis_csv, outcomes_csv], backup_dir)

    for session in sessions:
        payload = load_capture_payload(captures_dir / capture_date / f"{session}.json")
        if not payload:
            skipped.append(f"{session}: missing")
            continue
        if not should_quarantine_legacy_capture(payload, session):
            skipped.append(f"{session}: active/study-eligible")
            continue
        scanner = scanner_name(payload)
        provider = payload.get("provider", "")
        result = quarantine_raw_capture(
            capture_date,
            session,
            reason=reason,
            captures_dir=captures_dir,
            manifest_path=manifest_path,
            quarantine_root=quarantine_root,
            quarantined_at=cleaned_at,
            batch_id=batch_id,
        )
        quarantine_results.append(result)
        marked_decisions += mark_review_decisions_for_quarantined_capture(
            capture_date=capture_date,
            session=session,
            provider=provider,
            scanner=scanner,
            quarantined_at=cleaned_at.isoformat(),
            reason=reason,
            path=review_decisions_path,
        )

    analysis_rows = build_analysis_rows_from_raw_captures(captures_dir)
    write_analysis_rows(analysis_rows, analysis_csv)
    outcome_count = prune_outcomes_to_active_analysis(
        analysis_rows=analysis_rows,
        outcomes_csv=outcomes_csv,
    )
    return LegacyCaptureCleanupResult(
        capture_date=capture_date,
        sessions_checked=list(sessions),
        quarantine_results=quarantine_results,
        skipped=skipped,
        review_decisions_marked=marked_decisions,
        analysis_rows=len(analysis_rows),
        outcome_rows=outcome_count,
        analysis_path=analysis_csv,
        outcomes_path=outcomes_csv,
        backup_dir=backup_dir,
        backups=backups,
    )


def should_quarantine_legacy_capture(payload: dict, session: str) -> bool:
    classification = classify_capture(
        payload.get("capture_time", ""),
        payload.get("session", session),
        capture_date=payload.get("capture_date", ""),
    )
    return (not has_calendar_metadata(payload)) or (not classification.is_study_eligible)


def has_calendar_metadata(payload: dict) -> bool:
    return all(payload.get(field) not in (None, "") for field in calendar_fieldnames())


def prune_outcomes_to_active_analysis(*, analysis_rows: list[dict], outcomes_csv: Path) -> int:
    if not outcomes_csv.exists():
        return 0
    existing_rows = read_csv_rows(outcomes_csv)
    active_keys = {derived_row_key(row) for row in analysis_rows}
    kept_rows = [row for row in existing_rows if derived_row_key(row) in active_keys]
    outcomes_csv.parent.mkdir(parents=True, exist_ok=True)
    with outcomes_csv.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTCOME_FIELDNAMES)
        writer.writeheader()
        for row in kept_rows:
            writer.writerow({field: row.get(field, "") for field in OUTCOME_FIELDNAMES})
    return len(kept_rows)


def backup_existing_derived_files(paths: list[Path], backup_dir: Path) -> list[Path]:
    backups: list[Path] = []
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        destination = backup_dir / path.name
        shutil.copy2(path, destination)
        backups.append(destination)
    return backups


def read_csv_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def derived_row_key(row: dict) -> str:
    return "|".join(
        [
            row.get("capture_date", ""),
            row.get("capture_time", ""),
            row.get("session", ""),
            row.get("provider", ""),
            row.get("scanner", ""),
            row.get("ticker", ""),
        ]
    ).upper()


def load_capture_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def scanner_name(payload: dict) -> str:
    scanner = payload.get("scanner", {})
    return scanner.get("name", "") if isinstance(scanner, dict) else str(scanner)


def main() -> int:
    parser = argparse.ArgumentParser(description="Quarantine legacy non-study raw captures and rebuild derived rows.")
    parser.add_argument("capture_date", help="Capture date in YYYY-MM-DD format.")
    parser.add_argument("--sessions", nargs="+", default=list(DEFAULT_LEGACY_SESSIONS), help="Sessions to inspect.")
    parser.add_argument("--reason", default=DEFAULT_REASON, help="Recovery note reason.")
    args = parser.parse_args()

    result = cleanup_legacy_non_study_captures(
        args.capture_date,
        sessions=tuple(args.sessions),
        reason=args.reason,
    )
    print("Legacy capture cleanup complete.")
    print(f"Capture Date: {result.capture_date}")
    print(f"Sessions Checked: {', '.join(result.sessions_checked)}")
    print(f"Quarantined Sessions: {', '.join(result.quarantined_sessions) or 'none'}")
    print(f"Skipped: {', '.join(result.skipped) or 'none'}")
    print(f"Review Decisions Marked: {result.review_decisions_marked}")
    print(f"Analysis Rows: {result.analysis_rows}")
    print(f"Outcome Rows: {result.outcome_rows}")
    print(f"Backup Dir: {result.backup_dir}")
    for quarantine_result in result.quarantine_results:
        print(f"Quarantine Dir: {quarantine_result.quarantine_dir}")
        print(f"Recovery Note: {quarantine_result.note_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
