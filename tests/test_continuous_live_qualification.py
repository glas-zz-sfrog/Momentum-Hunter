from __future__ import annotations

import ast
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from momentum_hunter.continuous_live_qualification import (
    LiveMaterialEvents,
    LiveQualificationError,
    QualificationState,
    _backfill_accounting,
    validate_qualification_root,
)
from momentum_hunter.continuous_runtime import DATA_RECOVERED
from momentum_hunter.continuous_tradeplan_producer import HISTORY_BACKFILL_PENDING
from momentum_hunter.opportunity_denominator import (
    LIVE_READ_ONLY_QUALIFICATION,
    OBSERVATION_MODES,
)


class ContinuousLiveQualificationTests(unittest.TestCase):
    def test_disposable_root_rejects_production_and_canonical_paths(self) -> None:
        canonical = Path("C:/Users/steve/OneDrive/Documents/Investing")
        with self.assertRaises(LiveQualificationError):
            validate_qualification_root(
                canonical / "qualification",
                canonical_root=canonical,
            )
        with self.assertRaises(LiveQualificationError):
            validate_qualification_root(
                Path("C:/ProgramData/MomentumHunter/qualification"),
                canonical_root=canonical,
            )
        with self.assertRaises(LiveQualificationError):
            validate_qualification_root(
                Path("C:/temp/MomentumHunterData/qualification"),
                canonical_root=canonical,
            )

    def test_disposable_user_local_root_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "generation-1"
            self.assertEqual(root.resolve(), validate_qualification_root(root))

    def test_live_qualification_mode_is_distinct_and_nonprospective(self) -> None:
        self.assertIn(LIVE_READ_ONLY_QUALIFICATION, OBSERVATION_MODES)
        self.assertNotEqual("PROSPECTIVE", LIVE_READ_ONLY_QUALIFICATION)

    def test_terminal_backfill_emits_one_bounded_data_recovered_event(self) -> None:
        class Backfill:
            status_value = "QUEUED"

            def status(self, symbol: str):
                return {
                    "symbol": symbol,
                    "status": self.status_value,
                    "completedAt": (
                        "2026-08-18T10:05:00-04:00"
                        if self.status_value == "COMPLETE"
                        else None
                    ),
                    "attemptCount": 1,
                }

        with tempfile.TemporaryDirectory() as temporary:
            now = datetime(
                2026, 8, 18, 10, 5, tzinfo=ZoneInfo("America/New_York")
            )
            state = QualificationState(root=Path(temporary), launch_at=now)
            state.historical_contexts["AAA"] = SimpleNamespace(
                status=HISTORY_BACKFILL_PENDING,
                context_id="continuous-history-pending",
            )
            backfill = Backfill()
            events = LiveMaterialEvents(state, backfill)
            self.assertEqual((), events.poll(now))
            backfill.status_value = "COMPLETE"
            emitted = events.poll(now)
            self.assertEqual(1, len(emitted))
            self.assertEqual(DATA_RECOVERED, emitted[0].trigger)
            self.assertEqual("AAA", emitted[0].symbol)
            self.assertEqual((), events.poll(now))

    def test_backfill_accounting_distinguishes_attempts_from_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "backfill.json"
            path.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "records": {
                            "AAA": {
                                "symbol": "AAA",
                                "status": "COMPLETE",
                                "attemptCount": 2,
                                "requestedAt": "2026-08-18T10:00:00-04:00",
                                "startedAt": "2026-08-18T10:00:01-04:00",
                                "completedAt": "2026-08-18T10:00:02-04:00",
                            },
                            "BBB": {
                                "symbol": "BBB",
                                "status": "FAILED",
                                "attemptCount": 1,
                                "requestedAt": "2026-08-18T10:01:00-04:00",
                                "startedAt": "2026-08-18T10:01:01-04:00",
                                "completedAt": "2026-08-18T10:01:02-04:00",
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )

            accounting = _backfill_accounting(path)

        self.assertEqual(3, accounting["attempts"])
        self.assertEqual(1, accounting["successful"])
        self.assertEqual(1, accounting["failed"])
        self.assertEqual(0, accounting["active"])

    def test_module_has_no_order_or_broker_capability(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "continuous_live_qualification.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(
            imports.intersection(
                {
                    "momentum_hunter.alpaca_paper_broker",
                    "momentum_hunter.alpaca_paper_engineering",
                    "momentum_hunter.shadow_selection",
                    "momentum_hunter.shadow_opening",
                }
            )
        )
        calls = {
            node.func.attr.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(
            calls.intersection({"submit_order", "cancel_order", "replace_order"})
        )
        self.assertNotIn(
            "momentum_hunter.event_runtime_writer_ipc",
            source.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
