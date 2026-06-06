from __future__ import annotations

import argparse
from pathlib import Path

from momentum_hunter.score_breakdowns import rebuild_score_breakdowns


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild Momentum Hunter score breakdowns from active raw captures.")
    parser.add_argument("--output", type=Path, default=None, help="Optional output path for score-breakdowns.json.")
    args = parser.parse_args()

    result = rebuild_score_breakdowns(**({"output_path": args.output} if args.output else {}))
    print("Score breakdown rebuild complete.")
    print(f"Output: {result.output_path}")
    print(f"Backup: {result.backup_path or 'none'}")
    print(f"Total Records: {result.total_records}")
    print(
        "Counts: "
        + ", ".join(f"{status}={count}" for status, count in sorted(result.counts.items()))
    )
    print(f"Failed Records: {len(result.failed_records)}")
    return 1 if result.failed_records else 0


if __name__ == "__main__":
    raise SystemExit(main())
