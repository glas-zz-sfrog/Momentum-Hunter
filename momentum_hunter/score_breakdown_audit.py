from __future__ import annotations

import argparse
from pathlib import Path

from momentum_hunter.config import DATA_DIR
from momentum_hunter.integrity import audit_score_breakdowns, overall_audit_status, write_integrity_audit_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Momentum Hunter score breakdown integrity.")
    parser.add_argument("--csv", type=Path, default=DATA_DIR / "integrity" / "score_breakdown_audit.csv")
    parser.add_argument("--md", type=Path, default=DATA_DIR / "integrity" / "score_breakdown_audit.md")
    args = parser.parse_args()

    rows = audit_score_breakdowns()
    csv_path, markdown_path = write_integrity_audit_report(rows, csv_path=args.csv, markdown_path=args.md)
    overall = overall_audit_status(rows)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    summary = ", ".join(f"{status}={count}" for status, count in sorted(counts.items())) or "no score breakdown rows found"
    print(f"Overall Status: {overall}")
    print(f"Score breakdown audit: {summary}")
    print(f"CSV: {csv_path}")
    print(f"Report: {markdown_path}")
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
