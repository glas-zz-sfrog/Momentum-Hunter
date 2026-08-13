from __future__ import annotations

"""Run one provider-correct Schwab premarket checkpoint."""

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from momentum_hunter.schwab_premarket_fidelity import (
    TASK_ID,
    checkpoints_for,
    load_and_verify,
    parse_session_date,
    run_checkpoint,
    write_json_once,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one read-only Schwab premarket authority checkpoint."
    )
    parser.add_argument("--checkpoint", choices=("BOUNDARY", "ACTIVE"), required=True)
    parser.add_argument("--session-date", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        checkpoint = checkpoints_for(parse_session_date(args.session_date))[args.checkpoint]
        if args.verify_existing:
            result = load_and_verify(args.output)
            status = "DUPLICATE_VERIFIED"
        else:
            result = run_checkpoint(checkpoint)
            write_json_once(result, args.output)
            status = "CAPTURED"
        print(
            json.dumps(
                {
                    "taskId": TASK_ID,
                    "checkpoint": checkpoint.code,
                    "status": status,
                    "classification": result["adjudication"]["classification"],
                    "provider": "SCHWAB",
                    "output": str(args.output),
                    "positionsRequested": False,
                    "ordersRequested": False,
                    "orderTransmission": "UNAVAILABLE",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "taskId": TASK_ID,
                    "classification": "SCHWAB_PREMARKET_PROBE_FAILED_SAFE",
                    "errorType": type(exc).__name__,
                    "credentialMaterialIncluded": False,
                    "positionsRequested": False,
                    "ordersRequested": False,
                    "orderTransmission": "UNAVAILABLE",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
