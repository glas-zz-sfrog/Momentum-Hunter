from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from momentum_hunter.native_paper_broker import SimulatedPaperBroker
from momentum_hunter.native_paper_execution import NativePaperExecutionEngine
from momentum_hunter.native_paper_store import NativePaperError
from tests.test_native_paper_execution import decision
from tests.test_native_paper_mechanics import NOW, account, policy


POINTS = ("before_intent_persistence", "after_intent_persistence", "before_submit", "after_ack",
          "before_fill_persistence", "after_partial_fill", "after_full_fill", "before_exit_reconciliation",
          "after_exit_reconciliation", "after_position_closure")


class PhysicalNativeRestartTests(unittest.TestCase):
    def run_death(self, point):
        with tempfile.TemporaryDirectory(prefix="mh-native-paper-crash-") as name:
            root = Path(name)
            environment = {key: value for key, value in os.environ.items()
                           if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"}}
            child = subprocess.run([sys.executable, "-B", "tools/native_paper_crash_probe.py", "--root", str(root), "--point", point],
                                   capture_output=True, text=True, timeout=30, env=environment)
            self.assertEqual(73, child.returncode, child.stderr)
            broker = SimulatedPaperBroker("fixture", restored=json.loads((root / "simulator-at-death.json").read_bytes()))
            engine = NativePaperExecutionEngine(root=root / "audit", namespace="fixture", policy=policy(),
                                                simulator=broker, require_existing=True)
            before = engine.inspect()
            engine.reconcile(at=NOW)
            result = engine.qualification_entry(decision(), at=NOW, account=account(), requested_quantity="10")
            self.assertLessEqual(broker.submit_calls, 1)
            if before["trades"]:
                old = next(iter(before["trades"].values()))
                self.assertEqual(old["order_id"], result["order_id"])
                self.assertEqual(old["position_id"], result["position_id"])
            if point in {"before_exit_reconciliation", "after_exit_reconciliation", "after_position_closure"}:
                self.assertEqual("0", result["position_quantity"])
                self.assertEqual("POSITION_CLOSED", result["state"])

    def test_missing_recovery_root_is_not_fresh_genesis(self):
        with tempfile.TemporaryDirectory() as name:
            with self.assertRaisesRegex(NativePaperError, "RECOVERY_CUSTODY_MISSING"):
                NativePaperExecutionEngine(root=Path(name) / "missing", namespace="fixture", policy=policy(), require_existing=True)

    def test_deleted_audit_tail_is_detected_by_anchor(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            engine = NativePaperExecutionEngine(root=root, namespace="fixture", policy=policy())
            engine.record_disabled_decision(source_identity="one", payload={}, at=NOW)
            engine.record_disabled_decision(source_identity="two", payload={}, at=NOW)
            sorted(root.glob("*.json"))[-1].unlink()
            with self.assertRaisesRegex(NativePaperError, "ANCHOR_CONFLICT"):
                engine.inspect()


for _point in POINTS:
    def _test(self, point=_point):
        self.run_death(point)
    setattr(PhysicalNativeRestartTests, "test_physical_death_" + _point, _test)


if __name__ == "__main__":
    unittest.main()
