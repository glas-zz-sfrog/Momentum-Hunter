from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from momentum_hunter.pending_foundation_release_gate import (  # noqa: E402
    evaluate_pending_foundation_release,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the pending nontransmitting foundation without modifying Git "
            "state or runtime evidence."
        )
    )
    parser.add_argument(
        "--repository",
        type=Path,
        default=ROOT,
        help="Repository root to inspect.",
    )
    args = parser.parse_args()
    result = evaluate_pending_foundation_release(
        args.repository,
        evaluated_at=datetime.now(timezone.utc),
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
