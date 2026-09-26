from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter import continuous_host_contract as contract
from momentum_hunter.continuous_host_lifecycle import retained_inputs
from momentum_hunter.continuous_runtime import (
    ContinuousOpportunityRuntime, LogicalRuntimeLeaseRegistry,
    RuntimeCheckpointError, build_evidence_write_intent,
)
from momentum_hunter.preserved_provider_replay import ReplayClock
from momentum_hunter.writer_liveness import WriterLiveness
from tests.test_continuous_runtime import RuntimeFixture


class RetainedClockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = {"schemaVersion": 2, "inputMode": contract.OFFLINE,
                       "offlineInput": {"packagePath": str(self.root / "replay.zip")},
                       "runtimeStateRoot": str(self.root)}
        self.now = datetime(2026, 8, 27, 16, 25, 30, 979821, tzinfo=timezone.utc)

    def replay(self, checkpoint):
        replay = SimpleNamespace(clock=ReplayClock(self.now),
                                 discovery_provider=SimpleNamespace(snapshots=(), index=0))
        with patch("momentum_hunter.preserved_provider_replay.load_preserved_provider_replay",
                   return_value=replay):
            return retained_inputs(self.config, checkpoint)

    def checkpoint(self, observed):
        monitor = WriterLiveness()
        monitor.observe(now=observed.timestamp(), depth=0, capacity=4, oldest_age=0, horizon=30)
        return {"last_heartbeat_at": self.now.isoformat(), "writer_liveness": monitor.snapshot()}

    def restore(self, fixture, now):
        return ContinuousOpportunityRuntime.restore(
            config=fixture.config, runtime_instance_id="runtime-instance-2", now=now,
            discovery_source=fixture.discovery, market_data_source=fixture.market,
            event_source=fixture.events, composition_source=fixture.composer,
            denominator_source=fixture.denominator, writer=fixture.writer,
            lease_registry=LogicalRuntimeLeaseRegistry(), checkpoint_store=fixture.store)

    def test_durable_ack_completion_clock_survives_offline_restart(self):
        fixture = RuntimeFixture(self.root / "runtime")
        now = fixture.clock.now()
        runtime = fixture.runtime
        runtime.start(now)
        intent = build_evidence_write_intent(
            runtime_instance_id=runtime.runtime_instance_id, sequence=1,
            evidence_type="COMPOSITION_CYCLE", record_identity="clock-regression",
            record_fingerprint="1" * 64, predecessor_identity=None,
            requested_at=now.isoformat(), payload_fingerprint="2" * 64)
        runtime.admit_evidence_intent(intent, now)
        with patch("momentum_hunter.continuous_runtime.time.perf_counter", side_effect=[0.0, 0.033548]):
            self.assertTrue(runtime._process_evidence(now))
        runtime.shutdown(now)
        checkpoint = fixture.store.load(fixture.config.runtime_identity)
        self.now = now
        replay = self.replay(checkpoint)
        observed = checkpoint["writer_liveness"]["last_observation"]
        self.assertGreater(observed, now.timestamp())
        restored = self.restore(fixture, replay.clock.now())
        self.assertIsNone(restored._writer_liveness.failure)
        self.assertEqual(1, restored._writer_liveness.drains)
        self.assertEqual(0, len(restored._queues["evidence"]))
        self.assertEqual([intent], fixture.writer.intents)
        self.assertGreaterEqual(replay.clock.now().timestamp(), observed)
        repeated = self.replay(fixture.store.load(fixture.config.runtime_identity))
        self.restore(fixture, repeated.clock.now())
        self.assertEqual([intent], fixture.writer.intents)

    def test_exact_r25_time_delta_and_input_immutability(self):
        observed = datetime(2026, 8, 27, 16, 25, 31, 13369, tzinfo=timezone.utc)
        checkpoint = self.checkpoint(observed)
        original = deepcopy(checkpoint)
        self.assertEqual(observed, self.replay(checkpoint).clock.now())
        self.assertEqual(original, checkpoint)

    def test_empty_and_legacy_monitor_do_not_change_replay_clock(self):
        for checkpoint in (None, {"last_heartbeat_at": self.now.isoformat()},
                           {"writer_liveness": WriterLiveness().snapshot()}):
            with self.subTest(checkpoint=checkpoint):
                self.assertEqual(self.now, self.replay(checkpoint).clock.now())

    def test_writer_observation_does_not_rewind_newer_runtime_time(self):
        checkpoint = self.checkpoint(self.now)
        later = self.now + timedelta(seconds=5)
        checkpoint["last_discovery_completed_at"] = later.isoformat()
        self.assertEqual(later, self.replay(checkpoint).clock.now())

    def test_invalid_writer_chronology_fails_closed(self):
        for value in (True, "1787847931.013369", -1, float("nan"), float("inf")):
            checkpoint = self.checkpoint(self.now)
            checkpoint["writer_liveness"]["last_observation"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.replay(checkpoint)

    def test_incomplete_or_contradictory_writer_snapshot_fails_closed(self):
        for mutation in ("missing", "progress", "terminal"):
            checkpoint = self.checkpoint(self.now)
            monitor = checkpoint["writer_liveness"]
            if mutation == "missing":
                del monitor["arrivals"]
            elif mutation == "progress":
                monitor["last_progress"] = self.now.timestamp() + 1
            else:
                monitor["failure"] = "NO_PROGRESS"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.replay(checkpoint)

    def test_live_mode_does_not_load_replay_or_adjust_real_clock(self):
        with patch("momentum_hunter.continuous_host_lifecycle.input_mode", return_value=contract.LIVE), \
                patch("momentum_hunter.preserved_provider_replay.load_preserved_provider_replay") as load:
            self.assertIsNone(retained_inputs(self.config, self.checkpoint(self.now)))
        load.assert_not_called()

    def test_runtime_future_observation_guard_remains_blocking(self):
        fixture = RuntimeFixture(self.root / "future")
        now = fixture.clock.now()
        fixture.runtime.start(now)
        checkpoint = fixture.store.load(fixture.config.runtime_identity)
        checkpoint["writer_liveness"] = self.checkpoint(now + timedelta(seconds=1))["writer_liveness"]
        fixture.store.save(fixture.config.runtime_identity, checkpoint)
        with self.assertRaisesRegex(RuntimeCheckpointError, "Writer liveness checkpoint"):
            self.restore(fixture, now)


if __name__ == "__main__":
    unittest.main()
