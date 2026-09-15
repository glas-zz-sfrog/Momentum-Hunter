"""Offline process-death fixture. Explicit disposable root; never production."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--point", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    temporary = Path(tempfile.gettempdir()).resolve()
    if not root.is_relative_to(temporary) or not root.name.startswith("mh-native-paper-crash-"):
        raise RuntimeError("DISPOSABLE_TEST_ROOT_REQUIRED")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from momentum_hunter.native_paper_broker import SimulatedPaperBroker
    from momentum_hunter.native_paper_execution import NativePaperExecutionEngine
    from tests.test_native_paper_execution import decision
    from tests.test_native_paper_mechanics import NOW, account, policy

    broker = SimulatedPaperBroker("fixture")
    reached = False
    def death(point):
        nonlocal reached
        if point != args.point:
            return
        reached = True
        path = root / "simulator-at-death.json"
        with path.open("xb") as stream:
            stream.write(json.dumps(broker.snapshot(), sort_keys=True).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os._exit(73)

    engine = NativePaperExecutionEngine(root=root / "audit", namespace="fixture", policy=policy(), simulator=broker, fault=death)
    trade = engine.qualification_entry(decision(), at=NOW, account=account(), requested_quantity="10")
    qty = "3" if args.point == "after_partial_fill" else "10"
    broker.fill(trade["order_id"], fill_id="entry", quantity=qty, price="99.9", at=NOW.isoformat())
    if qty == "10":
        broker.seal_order(trade["order_id"], at=NOW.isoformat())
    engine.reconcile(at=NOW)
    broker.fill(trade["exit_contract"]["target_order_id"], fill_id="exit", quantity="10", price="102", at=NOW.isoformat())
    for role in ("stop", "target", "forced_flat"):
        broker.seal_order(trade["exit_contract"][role + "_order_id"], at=NOW.isoformat())
    engine.qualification_exit(scope=trade["scope"], reason="TARGET", at=NOW)
    if not reached:
        raise RuntimeError("CRASH_POINT_NOT_REACHED")


if __name__ == "__main__":
    main()
