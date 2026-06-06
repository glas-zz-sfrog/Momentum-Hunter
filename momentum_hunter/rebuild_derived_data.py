from __future__ import annotations

import argparse

from momentum_hunter.rebuild_derived import rebuild_derived_data_from_raw_captures


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Momentum Hunter derived CSVs from immutable raw captures.")
    parser.add_argument(
        "--skip-outcomes",
        action="store_true",
        help="Only rebuild analysis-captures.csv; leave analysis-outcomes.csv absent after backup.",
    )
    args = parser.parse_args()

    result = rebuild_derived_data_from_raw_captures(rebuild_outcomes=not args.skip_outcomes)
    print("Derived data rebuild complete.")
    print(f"Before Audit: {result.before_status}")
    print(f"After Audit: {result.after_status}")
    print(f"Analysis Rows: {result.analysis_rows}")
    print(f"Outcome Rows: {result.outcome_rows}")
    print(f"Manifest Entries Added: {result.manifest_entries_added}")
    print(f"Backup Dir: {result.backup_dir}")
    print(f"Analysis CSV: {result.analysis_path}")
    print(f"Outcomes CSV: {result.outcomes_path}")
    print(f"Before Report: {result.before_audit_report}")
    print(f"After Report: {result.after_audit_report}")
    return 1 if result.after_status == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
