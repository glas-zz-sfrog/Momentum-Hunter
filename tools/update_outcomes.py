from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.outcomes import update_outcomes


def main() -> int:
    path, count = update_outcomes()
    print(f"Updated {count} outcome rows")
    print(f"Output: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
