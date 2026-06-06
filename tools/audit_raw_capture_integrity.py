from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.integrity import audit_raw_captures, write_integrity_audit_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Momentum Hunter raw capture file integrity.")
    parser.add_argument("--csv", type=Path, default=None, help="Optional CSV output path.")
    parser.add_argument("--md", type=Path, default=None, help="Optional Markdown output path.")
    args = parser.parse_args()

    rows = audit_raw_captures()
    csv_path, markdown_path = write_integrity_audit_report(
        rows,
        **{key: value for key, value in {"csv_path": args.csv, "markdown_path": args.md}.items() if value is not None},
    )
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    summary = ", ".join(f"{status}={count}" for status, count in sorted(counts.items())) or "no raw captures found"
    print(f"Raw capture integrity audit complete: {summary}")
    print(f"CSV: {csv_path}")
    print(f"Report: {markdown_path}")
    return 1 if any(row.status not in {"OK", "UNTRACKED"} for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
