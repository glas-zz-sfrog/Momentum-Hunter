from __future__ import annotations

"""Run one prospective Alpaca-only replacement for a failed premarket checkpoint."""

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

# Task Scheduler does not guarantee a repository working directory. Pin imports
# to the feature worktree that owns this runner instead of an installed checkout.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.session_fidelity import write_json_once
from momentum_hunter.session_fidelity_premarket_retry import (
    TASK_ID,
    load_existing_retry,
    program_context,
    require_checkpoint_start,
)


def _load_adapter(project_root: Path) -> object:
    path = project_root.expanduser().resolve() / "tools" / "run_session_fidelity_alpaca.py"
    if not path.is_file():
        raise RuntimeError("The repaired Alpaca session adapter is unavailable.")
    spec = importlib.util.spec_from_file_location("session_fidelity_retry_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The repaired Alpaca session adapter cannot be loaded.")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    return adapter


def run_retry(
    checkpoint_code: str,
    *,
    project_root: Path,
    source_root: Path,
    now: datetime | None = None,
    sleeper: object = time.sleep,
    adapter: object | None = None,
) -> dict[str, object]:
    observed = now or datetime.now(timezone.utc)
    checkpoint = require_checkpoint_start(checkpoint_code, observed)
    provider_adapter = adapter or _load_adapter(project_root)
    return provider_adapter._run_checkpoint_observation(
        checkpoint,
        task_id=TASK_ID,
        source_root=source_root,
        sleeper=sleeper,
        program_context=program_context(checkpoint.code),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an Alpaca premarket fidelity retry.")
    parser.add_argument("--checkpoint", choices=("A", "B", "C"), required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.is_file():
            result = load_existing_retry(
                args.output,
                checkpoint_code=args.checkpoint,
            )
            print(
                json.dumps(
                    {
                        "taskId": TASK_ID,
                        "checkpoint": args.checkpoint,
                        "status": "DUPLICATE_VERIFIED",
                        "classification": result["adjudication"]["classification"],
                        "output": str(args.output),
                        "accountRequested": False,
                        "positionsRequested": False,
                        "ordersRequested": False,
                        "orderTransmission": "UNAVAILABLE",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        result = run_retry(
            args.checkpoint,
            project_root=args.project_root,
            source_root=args.source_root,
        )
        proof_hash = write_json_once(result, args.output)
        print(
            json.dumps(
                {
                    "taskId": TASK_ID,
                    "checkpoint": args.checkpoint,
                    "classification": result["adjudication"]["classification"],
                    "output": str(args.output),
                    "sha256": proof_hash,
                    "accountRequested": False,
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
                    "classification": "SESSION_FIDELITY_PREMARKET_RETRY_FAILED_SAFE",
                    "credentialMaterialIncluded": False,
                    "errorType": type(exc).__name__,
                    "accountRequested": False,
                    "positionsRequested": False,
                    "ordersRequested": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
