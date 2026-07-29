from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from momentum_hunter.schwab_canary_stack_release import (  # noqa: E402
    evaluate_final_canary_stack_release,
    render_final_canary_stack_release,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify the clean backed-up current-baseline canary stack "
            "and emit its current manifest without changing Git or runtime state."
        )
    )
    parser.add_argument(
        "--repository",
        type=Path,
        default=ROOT,
        help="Repository root to inspect.",
    )
    args = parser.parse_args()
    result = evaluate_final_canary_stack_release(
        args.repository,
        evaluated_at=datetime.now(timezone.utc),
    )
    print(render_final_canary_stack_release(result))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
