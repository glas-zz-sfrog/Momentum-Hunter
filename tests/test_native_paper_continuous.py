from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.continuous_runtime import ContinuousOpportunityRuntime, RuntimeCheckpointError
from momentum_hunter.native_paper_intake import DisabledPaperIntake
from tests.test_continuous_runtime import RuntimeFixture


class DisabledContinuousPaperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.f = RuntimeFixture(self.root)
        self.intake = DisabledPaperIntake(root=self.root / "disabled-paper", runtime_fingerprint=self.f.config.fingerprint)
        self.runtime = ContinuousOpportunityRuntime(**self.arguments("one"), disabled_paper_intake=self.intake)

    def arguments(self, instance):
        f = self.f
        return dict(config=f.config, runtime_instance_id=instance, discovery_source=f.discovery,
                    market_data_source=f.market, event_source=f.events, composition_source=f.composer,
                    denominator_source=f.denominator, writer=f.writer, lease_registry=f.leases,
                    checkpoint_store=f.store)

    def run_cycle(self):
        self.runtime.start(self.f.clock.now())
        self.runtime.tick(self.f.clock.now())

    def test_normal_pipeline_records_disabled_plan_and_no_plan_without_adapter(self):
        self.f.composer.no_plan_symbols.add("S00")
        with patch("socket.socket", side_effect=AssertionError("NETWORK_FORBIDDEN")):
            self.run_cycle()
        rows = list(self.intake.store.load()[0]["disabled_intents"].values())
        self.assertEqual(10, len(rows))
        self.assertTrue(any(row["result"]["plan_id"] is None for row in rows))
        self.assertTrue(any(row["result"]["plan_id"] for row in rows))
        self.assertTrue(all(row["state"] == "DISABLED" and row["execution_authority"] == "NONE" for row in rows))
        self.assertEqual(10, len(self.f.denominator.calls))
        self.assertFalse(hasattr(self.intake, "qualification_entry"))
        self.assertFalse(hasattr(self.intake, "arm"))

    def test_default_constructor_does_not_create_paper_root_or_binding(self):
        self.f.runtime.start(self.f.clock.now())
        self.f.runtime.tick(self.f.clock.now())
        self.assertNotIn("disabled_paper", self.f.store.load(self.f.config.runtime_identity))
        self.assertIsNone(self.f.runtime.disabled_paper_intake)

    def test_sink_failure_preserves_pending_and_does_not_block_research(self):
        with patch.object(self.intake, "record", side_effect=OSError("TEST_DISK_UNAVAILABLE")):
            self.run_cycle()
        checkpoint = self.f.store.load(self.f.config.runtime_identity)
        self.assertTrue(checkpoint["disabled_paper"]["pending"])
        self.assertTrue(checkpoint["disabled_paper"]["failure"])
        self.assertEqual(10, len(self.f.denominator.calls))

    def test_crash_after_sink_commit_before_checkpoint_is_idempotent(self):
        original = self.intake.record
        class Crash(BaseException):
            pass
        def crash(payload, at):
            original(payload, at)
            raise Crash
        self.runtime.start(self.f.clock.now())
        with patch.object(self.intake, "record", side_effect=crash), self.assertRaises(Crash):
            self.runtime.tick(self.f.clock.now())
        self.assertEqual(1, len(self.intake.store.load()[0]["disabled_intents"]))
        self.f.clock.advance(31)
        recovered = ContinuousOpportunityRuntime.restore(
            **self.arguments("two"), now=self.f.clock.now(), disabled_paper_intake=self.intake)
        recovered.tick(self.f.clock.now())
        rows = self.intake.store.load()[0]["disabled_intents"]
        self.assertEqual(10, len(rows))
        self.assertFalse(recovered._disabled_paper_pending)

    def test_restart_cannot_detach_or_rebind_disabled_custody(self):
        self.run_cycle()
        self.f.clock.advance(31)
        with self.assertRaises(RuntimeCheckpointError):
            ContinuousOpportunityRuntime.restore(**self.arguments("two"), now=self.f.clock.now())

    def test_duplicate_source_different_payload_fails_not_reinterpreted(self):
        self.run_cycle()
        row = next(iter(self.intake.store.load()[0]["disabled_intents"].values()))
        self.intake.record(row, self.f.clock.now())
        row["result"]["plan_id"] = "different"
        with self.assertRaises(ValueError):
            self.intake.record(row, self.f.clock.now())


if __name__ == "__main__":
    unittest.main()
