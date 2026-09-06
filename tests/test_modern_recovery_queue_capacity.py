"""Offline queue admission must be committed before it can be accepted."""
from copy import deepcopy
from dataclasses import asdict
from dataclasses import replace
from datetime import timedelta
import json
from pathlib import Path
from threading import Event, Thread
import tempfile
import unittest
from unittest.mock import Mock, patch

from momentum_hunter import continuous_runtime as runtime
from momentum_hunter import modern_operational as modern
from momentum_hunter import modern_recovery_integrity as integrity
from tests import test_modern_recovery_integrity as recovery
from tests import test_modern_operational_runtime as startup_fixtures
from tests import test_continuous_natural_setup as natural_fixtures
from tests.test_continuous_runtime import RuntimeFixture
from tests.test_modern_operational import EpochFixture
from tests.test_modern_recovery_capacity import CheckpointFixture, inventory, successor


class QueueCapacityRaceFixture(CheckpointFixture):
    def limit(self, count=3):
        for module in (modern, integrity):
            guard = patch.object(module, "MAX_RETAINED_CHECKPOINTS", count)
            guard.start()
            self.addCleanup(guard.stop)

    def blocked(self):
        r = self.native.runtime
        health = r.health(self.native.clock.now())
        self.assertEqual(r.process_state, runtime.FAILED)
        self.assertFalse(r._accepting_work)
        self.assertIsNone(r.lease)
        self.assertIsNone(self.native.leases.current(self.native.config.runtime_identity))
        self.assertIn(modern.CHECKPOINT_HISTORY_CAPACITY_EXHAUSTED, health.health_flags)
        self.assertNotIn(runtime.PROCESS_ALIVE, health.health_flags)

    def committed_inspection(self):
        expected = deepcopy(self.load())
        actual = json.loads(runtime._canonical_json(
            self.native.runtime._checkpoint_payload(self.native.clock.now())))
        # Process failure is an explicit overlay; append-only attempts remain their own truth.
        overlay = {"checkpoint_fingerprint", "process_state", "pipeline_state", "stall_blocker",
                   "active_degradations", "attempt_ledger_count", "attempt_ledger_head"}
        self.assertEqual({k: v for k, v in actual.items() if k not in overlay},
                         {k: v for k, v in expected.items() if k not in overlay})
        self.assertEqual(self.native.runtime._counters, expected["counters"])

    def publish_final(self, prepared):
        proposed = successor(self.publication)
        if prepared:
            raw = proposed.to_bytes()
            self.publication.pending.write_bytes(modern.canonical_bytes({
                "snapshotId": proposed.snapshot_id, "payloadSha256": modern.digest(raw),
                "snapshot": raw.decode("ascii")}))
            self.assertEqual(self.publication.current(), proposed)
        else:
            self.publication.publish(proposed,
                expected_previous=self.publication.current().snapshot_id)
        return proposed

    def race(self, *, prepared, boundary="enqueue"):
        r = self.native.runtime
        expected = deepcopy(self.load())
        publication = []
        if boundary == "enqueue":
            target, attribute = r._queues[runtime.DISCOVERY_QUEUE], "enqueue"
        else:
            target, attribute = self.store, "save"
        original = getattr(target, attribute)

        def interleave(*args, **kwargs):
            if boundary == "enqueue":
                result = original(*args, **kwargs)
                self.assertEqual(result[0], runtime.REPLACED_OBSOLETE)
                publication.append(self.publish_final(prepared))
                return result
            publication.append(self.publish_final(prepared))
            return original(*args, **kwargs)

        self.native.clock.advance(1)
        with patch.object(target, attribute, side_effect=interleave):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r.request_discovery(self.native.clock.now(), reason="replacement-QB")
        self.blocked()
        self.committed_inspection()
        self.assertEqual(len(publication), 1)
        self.assertEqual(self.publication.current(), publication[0])
        self.assertEqual(self.load(), expected)
        self.assertEqual({name: queue.snapshot() for name, queue in r._queues.items()},
                         expected["queues"])
        self.assertEqual(self.store.checkpoint_capacity()["write_capacity_remaining"], 0)
        self.assertFalse(self.publication.pending.exists())
        before = inventory(self.publication.root)
        for operation in (
            lambda: r.request_discovery(self.native.clock.now(), reason="later-QC"),
            lambda: r.submit_event(None, self.native.clock.now()),
            lambda: r.release_deferred_readiness(self.native.clock.now()),
            lambda: r.admit_evidence_intent(None, self.native.clock.now()),
            lambda: r.tick(self.native.clock.now()),
            lambda: r._process_one(runtime.DISCOVERY_QUEUE, self.native.clock.now()),
            lambda: r._process_evidence(self.native.clock.now()),
        ):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                operation()
            self.blocked()
            self.assertEqual(inventory(self.publication.root), before)
            self.assertEqual({name: queue.snapshot() for name, queue in r._queues.items()},
                             expected["queues"])
        with self.assertRaises(modern.CheckpointHistoryCapacityError):
            recovery.restore(self.native, "restart-after-failed-replacement")
        self.assertEqual(inventory(self.publication.root), before)
        self.assertEqual(self.load(), expected)


class QueueCapacityRaceTests(QueueCapacityRaceFixture):
    def test_reduced_direct_queue_replacement_does_not_gain_authority(self):
        self.limit()
        self.race(prepared=False)

    def test_reduced_prepared_queue_replacement_does_not_gain_authority(self):
        self.limit()
        self.race(prepared=True)

    def test_reduced_direct_save_rejection_restores_committed_queue(self):
        self.limit()
        self.race(prepared=False, boundary="save")

    def test_reduced_prepared_save_rejection_restores_committed_queue(self):
        self.limit()
        self.race(prepared=True, boundary="save")

    def test_successful_replacement_is_durable_before_return(self):
        self.native.clock.advance(1)
        r = self.native.runtime
        self.assertEqual(r.request_discovery(self.native.clock.now(), reason="durable-QB"),
                         runtime.REPLACED_OBSOLETE)
        self.assertEqual({name: queue.snapshot() for name, queue in r._queues.items()},
                         self.load()["queues"])
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 3)

    def test_successful_last_slot_keeps_new_committed_queue_but_blocks(self):
        self.limit()
        self.native.clock.advance(1)
        r = self.native.runtime
        with self.assertRaises(modern.CheckpointHistoryCapacityError):
            r.request_discovery(self.native.clock.now(), reason="committed-last-slot-QB")
        self.blocked()
        self.assertEqual({name: queue.snapshot() for name, queue in r._queues.items()},
                         self.load()["queues"])
        self.assertNotEqual(self.load()["queues"], self.payload["queues"])

    def test_event_and_its_queued_work_commit_together(self):
        r = self.native.runtime
        event = self.native.event("AAA")
        r.submit_event(event, self.native.clock.now())
        committed = self.load()
        self.assertEqual(committed["event_records"], [asdict(event)])
        self.assertEqual(committed["queues"][runtime.READINESS_QUEUE],
                         r._queues[runtime.READINESS_QUEUE].snapshot())
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 3)

    def test_failed_event_does_not_leave_phantom_seen_identity(self):
        self.limit()
        r = self.native.runtime
        expected = self.load()
        original = self.store.save

        def interleave(*args, **kwargs):
            self.publish_final(False)
            return original(*args, **kwargs)

        with patch.object(self.store, "save", side_effect=interleave):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r.submit_event(self.native.event("AAA"), self.native.clock.now())
        self.blocked()
        self.assertEqual(dict(r._seen_events), dict(expected["seen_events"]))
        self.assertEqual(list(r._event_records.values()), expected["event_records"])
        self.assertEqual({name: queue.snapshot() for name, queue in r._queues.items()},
                         expected["queues"])

    def intent(self):
        return runtime.build_evidence_write_intent(
            runtime_instance_id=self.native.runtime.runtime_instance_id, sequence=1,
            evidence_type="SYSTEM_FAILURE", record_identity="test-record",
            record_fingerprint="a" * 64, predecessor_identity=None,
            requested_at=self.native.clock.now().isoformat(), payload_fingerprint="b" * 64)

    def test_intent_sequence_and_queue_commit_together(self):
        r = self.native.runtime
        intent = self.intent()
        r.admit_evidence_intent(intent, self.native.clock.now())
        committed = self.load()
        self.assertEqual(committed["intents"], [asdict(intent)])
        self.assertEqual(committed["last_intent_id"], intent.intent_id)
        self.assertEqual(committed["sequence"], 1)
        self.assertEqual(committed["queues"][runtime.EVIDENCE_QUEUE],
                         r._queues[runtime.EVIDENCE_QUEUE].snapshot())
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 3)

    def test_failed_intent_does_not_advance_sequence_or_current_queue(self):
        self.limit()
        r = self.native.runtime
        original = self.store.save

        def interleave(*args, **kwargs):
            self.publish_final(True)
            return original(*args, **kwargs)

        with patch.object(self.store, "save", side_effect=interleave):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r.admit_evidence_intent(self.intent(), self.native.clock.now())
        self.blocked()
        self.assertEqual(r._sequence, 0)
        self.assertIsNone(r._last_intent_id)
        self.assertEqual(r.evidence_intents, ())
        self.assertEqual(len(r._queues[runtime.EVIDENCE_QUEUE]), 0)
        self.assertEqual(r._capacity_failure_proposal["authority"], "NONE")
        self.assertEqual(len(r._capacity_failure_proposal["intents"]), 1)

    def test_capacity_exception_from_source_is_not_downgraded_to_provider_failure(self):
        r = self.native.runtime
        before = inventory(self.publication.root)
        with patch.object(self.native.discovery, "discover",
                          side_effect=modern.CheckpointHistoryCapacityError()):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r._process_one(runtime.DISCOVERY_QUEUE, self.native.clock.now())
        self.blocked()
        self.assertEqual(r._counters["discovery_failures"], 0)
        self.assertEqual(inventory(self.publication.root), before)
        # An earlier positive capacity reading must not clear the terminal process latch.
        with patch.object(self.store, "require_write_capacity", return_value=None):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r.request_discovery(self.native.clock.now())
        self.blocked()

    def test_second_thread_cannot_admit_work_during_failed_queue_commit(self):
        self.limit()
        r = self.native.runtime
        entered, release, second_started, second_finished = Event(), Event(), Event(), Event()
        results = []
        original = self.store.save

        def interleave(*args, **kwargs):
            entered.set()
            if not release.wait(10):
                raise AssertionError("test thread was not released")
            self.publish_final(False)
            return original(*args, **kwargs)

        def request(reason, *, second=False):
            if second:
                second_started.set()
            try:
                results.append(r.request_discovery(self.native.clock.now(), reason=reason))
            except Exception as exc:
                results.append(type(exc))
            finally:
                if second:
                    second_finished.set()

        self.native.clock.advance(1)
        with patch.object(self.store, "save", side_effect=interleave):
            first = Thread(target=request, args=("QB",))
            second = Thread(target=request, args=("QC",), kwargs={"second": True})
            first.start()
            try:
                self.assertTrue(entered.wait(10))
                second.start()
                self.assertTrue(second_started.wait(10))
                self.assertFalse(second_finished.wait(0.05))
            finally:
                release.set()
                first.join(15)
                if second.ident is not None:
                    second.join(15)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
        self.assertEqual(results, [modern.CheckpointHistoryCapacityError] * 2)
        self.blocked()
        self.assertEqual({name: queue.snapshot() for name, queue in r._queues.items()},
                         self.payload["queues"])

    def test_deferred_release_and_deletion_commit_as_one_transition(self):
        r = self.native.runtime
        r.submit_event(self.native.event("AAA"), self.native.clock.now())
        work = r._queues[runtime.READINESS_QUEUE].pop()
        r._deferred_readiness[work.key] = work
        r._checkpoint(self.native.clock.now())
        before = self.store.checkpoint_capacity()["retained_checkpoints"]
        self.native.clock.advance(1)
        self.assertEqual(r.release_deferred_readiness(self.native.clock.now()), 1)
        committed = self.load()
        self.assertEqual(committed["deferred_readiness"], [])
        self.assertEqual(committed["queues"][runtime.READINESS_QUEUE],
                         r._queues[runtime.READINESS_QUEUE].snapshot())
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], before + 1)

    def test_failed_deferred_release_retains_committed_obligation(self):
        r = self.native.runtime
        r.submit_event(self.native.event("AAA"), self.native.clock.now())
        work = r._queues[runtime.READINESS_QUEUE].pop()
        r._deferred_readiness[work.key] = work
        r._checkpoint(self.native.clock.now())
        expected = self.load()
        self.limit(self.store.checkpoint_capacity()["retained_checkpoints"] + 1)
        original = self.store.save

        def interleave(*args, **kwargs):
            self.publish_final(True)
            return original(*args, **kwargs)

        with patch.object(self.store, "save", side_effect=interleave):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r.release_deferred_readiness(self.native.clock.now())
        self.blocked()
        self.assertEqual([asdict(item) for item in r._deferred_readiness.values()],
                         expected["deferred_readiness"])
        self.assertEqual(r._queues[runtime.READINESS_QUEUE].snapshot(), [])
        self.committed_inspection()

    def test_failed_compact_rejection_restores_all_checkpoint_coupled_diagnostics(self):
        self.limit()
        r = self.native.runtime
        rejected = runtime.WriterPreflight(accepted=False, payload_bytes=600000,
            encoded_envelope_bytes=600100, protocol_ceiling_bytes=524288,
            failure_class=runtime.PAYLOAD_TOO_LARGE)
        accepted = runtime.WriterPreflight(accepted=True, payload_bytes=500,
            encoded_envelope_bytes=600, protocol_ceiling_bytes=524288)
        original = self.store.save

        def interleave(*args, **kwargs):
            self.publish_final(False)
            return original(*args, **kwargs)

        with patch.object(self.native.writer, "preflight_intent",
                          Mock(side_effect=[rejected, accepted]), create=True), \
             patch.object(self.store, "save", side_effect=interleave):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r.admit_evidence_intent(self.intent(), self.native.clock.now())
        self.blocked()
        self.assertEqual(r.evidence_rejections, ())
        self.committed_inspection()
        self.assertEqual(r._evidence_retry_counts, {})
        self.assertEqual(r._evidence_retry_failure_class, {})
        self.assertEqual(r._evidence_retry_not_before, {})
        self.assertEqual(len(r._capacity_failure_proposal["evidence_rejections"]), 1)

    def drained(self):
        r = self.native.runtime
        r._queues[runtime.DISCOVERY_QUEUE].pop()
        r.next_discovery_at = self.native.clock.now() + timedelta(seconds=300)
        r.next_housekeeping_at = self.native.clock.now() + timedelta(seconds=60)
        r._checkpoint(self.native.clock.now())
        return r

    def test_empty_parent_operations_do_not_consume_history(self):
        r = self.drained()
        before = inventory(self.publication.root)
        now = self.native.clock.now()
        r._schedule_due_work(now)
        r._flush_provider_bound_cycle(now)
        self.assertEqual(r.release_deferred_readiness(now), 0)
        self.assertFalse(r._process_one(runtime.HEALTH_QUEUE, now))
        self.assertFalse(r._process_evidence(now))
        self.assertEqual(inventory(self.publication.root), before)

    def test_idle_tick_uses_only_its_required_checkpoint(self):
        r = self.drained()
        before = self.store.checkpoint_capacity()["retained_checkpoints"]
        self.native.clock.advance(1)
        r.tick(self.native.clock.now())
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], before + 1)
        self.assertTrue(r._accepting_work)

    def test_retry_delay_and_duplicate_admission_do_not_publish(self):
        r = self.native.runtime
        intent = self.intent()
        r.admit_evidence_intent(intent, self.native.clock.now())
        r._evidence_retry_not_before[intent.intent_id] = self.native.clock.now() + timedelta(seconds=30)
        r._checkpoint(self.native.clock.now())
        before = inventory(self.publication.root)
        self.assertFalse(r._process_evidence(self.native.clock.now()))
        self.assertEqual(r.admit_evidence_intent(intent, self.native.clock.now()), runtime.WRITER_DUPLICATE)
        self.assertEqual(inventory(self.publication.root), before)
        self.assertEqual(self.native.writer.intents, [])

    def test_nested_discovery_admissions_commit_once_with_parent_completion(self):
        r = self.native.runtime
        before = self.store.checkpoint_capacity()["retained_checkpoints"]
        r._process_one(runtime.DISCOVERY_QUEUE, self.native.clock.now())
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], before + 1)
        body = self.load()
        self.assertIsNone(body["in_flight"])
        self.assertEqual(body["queues"][runtime.DISCOVERY_QUEUE], [])
        self.assertEqual(len(body["queues"][runtime.READINESS_QUEUE]), 10)
        self.assertEqual(len(body["intents"]), 1)

    def test_failed_committed_inspection_uses_cache_without_proposal_authority(self):
        self.limit()
        r = self.native.runtime
        original = self.store.save
        final_bytes = []

        def interleave(*args, **kwargs):
            self.publish_final(False)
            final_bytes.append(inventory(self.publication.root))
            return original(*args, **kwargs)

        with patch.object(self.store, "load", side_effect=OSError("disposable inspection failure")), \
             patch.object(self.store, "save", side_effect=interleave):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                r.request_discovery(self.native.clock.now(), reason="uncommitted-QB")
        self.blocked()
        self.committed_inspection()
        self.assertEqual(r._capacity_failure_proposal["authority"], "NONE")
        self.assertNotEqual(r._capacity_failure_proposal["queues"], self.load()["queues"])
        self.assertIn("BLOCKED_COMMITTED_WORK_INSPECTION_UNAVAILABLE",
                      r.health(self.native.clock.now()).health_flags)
        self.assertEqual(inventory(self.publication.root), final_bytes[0])


class ParentOperationCheckpointTests(QueueCapacityRaceFixture):
    def operation(self, kind):
        r = self.native.runtime
        if kind == "discovery":
            return lambda: r._process_one(runtime.DISCOVERY_QUEUE, self.native.clock.now())
        r.submit_event(self.native.event("AAA"), self.native.clock.now())
        work = r._queues[runtime.READINESS_QUEUE].pop()
        r._provider_bound_events[work.key] = work
        r._checkpoint(self.native.clock.now())
        return lambda: r._flush_provider_bound_cycle(self.native.clock.now())

    def complete(self, kind):
        body = self.load()
        self.assertIsNone(body["in_flight"])
        if kind == "discovery":
            self.assertEqual(body["queues"][runtime.DISCOVERY_QUEUE], [])
            self.assertEqual(len(body["queues"][runtime.READINESS_QUEUE]), 10)
            self.assertEqual(self.native.discovery.calls, 1)
        else:
            self.assertEqual(body["provider_bound_events"], [])
            self.assertEqual(len(self.native.denominator.calls), 1)
        self.assertEqual(len(body["intents"]), 1)
        self.assertEqual(body["sequence"], 1)
        return body

    def stopped_after_save(self, kind):
        operation = self.operation(kind)
        original = self.store.save
        saves = []
        class ProcessStopped(BaseException):
            pass

        def stop(*args, **kwargs):
            original(*args, **kwargs)
            saves.append(1)
            raise ProcessStopped()

        with patch.object(self.store, "save", side_effect=stop):
            with self.assertRaises(ProcessStopped):
                operation()
        self.assertEqual(saves, [1])
        committed = self.complete(kind)
        restored = recovery.restore(self.native, "parent-phase-restart")
        if kind == "discovery":
            self.assertFalse(restored._process_one(runtime.DISCOVERY_QUEUE, self.native.clock.now()))
        else:
            restored._flush_provider_bound_cycle(self.native.clock.now())
        self.assertEqual(self.complete(kind)["intents"], committed["intents"])

    def final_slot(self, kind):
        operation = self.operation(kind)
        self.limit(self.store.checkpoint_capacity()["retained_checkpoints"] + 1)
        with self.assertRaises(modern.CheckpointHistoryCapacityError):
            operation()
        self.blocked()
        self.complete(kind)
        self.committed_inspection()

    def test_discovery_stop_after_commit_has_no_replayable_parent(self):
        self.stopped_after_save("discovery")

    def test_provider_bound_stop_after_commit_has_no_duplicate_output(self):
        self.stopped_after_save("provider-bound")

    def test_final_slot_contains_whole_discovery_and_readiness_batch(self):
        self.final_slot("discovery")

    def test_final_slot_contains_provider_bound_result_and_consumed_input(self):
        self.final_slot("provider-bound")


class CompositionParentCheckpointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mh-capacity-composition-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.native = RuntimeFixture(self.root / "fixture")
        self.native.config = replace(self.native.config, session_date=natural_fixtures.SESSION)
        self.native.clock = runtime.ManualClock(natural_fixtures.at(11, 21))
        configuration = patch.object(natural_fixtures, "CONFIGURATION", self.native.config.fingerprint)
        configuration.start()
        self.addCleanup(configuration.stop)
        market = natural_fixtures.ContinuousNaturalSetupTests(
            "test_natural_runtime_owns_missed_entry_and_distinct_pullback_successor")
        market.setUp()
        self.addCleanup(market.doCleanups)
        self.epoch_fixture = EpochFixture(self.root, configuration=self.native.config.fingerprint)
        self.addCleanup(self.epoch_fixture.patch.stop)
        self.epoch_fixture.start()
        self.epoch = self.epoch_fixture.epoch
        from momentum_hunter.continuous_tradeplan_producer import ContinuousTradePlanProducerStore
        ContinuousTradePlanProducerStore(self.epoch_fixture.root / "state/continuous-tradeplan-producer.json",
            operational_epoch=self.epoch).initialize_modern()
        market._prepare(self.native.clock.now(), generation=1)
        self.native.composer = natural_fixtures.LiveCompositionSource(market.state,
            configuration_fingerprint=self.native.config.fingerprint, operational_epoch=self.epoch)
        self.native.store = runtime.RuntimeCheckpointStore(self.epoch_fixture.root / "runtime",
            operational_epoch=self.epoch, runtime_config=self.native.config)
        self.native.runtime = self.native.new_runtime("composition-parent")
        self.r = self.native.runtime
        self.r.start(self.native.clock.now())
        request = market._request(self.native.clock.now(), generation=1)
        self.r._enqueue(runtime.COMPOSITION_QUEUE, self.r._new_work(kind="COMPOSITION",
            key=request.symbol, priority=1, requested_at=request.requested_at,
            payload=asdict(request)), self.native.clock.now())

    def assert_complete(self):
        body = self.native.store.load(self.native.config.runtime_identity)
        self.assertIsNone(body["in_flight"])
        self.assertEqual(body["queues"][runtime.COMPOSITION_QUEUE], [])
        self.assertEqual(len(body["terminal_cycle_ids"]), 1)
        self.assertEqual(body["counters"]["composition_cycles"], 1)
        self.assertEqual(body["counters"]["denominator_cycles"], 1)
        self.assertEqual([item["evidence_type"] for item in body["intents"]],
                         ["COMPOSITION_CYCLE", "OPPORTUNITY_DENOMINATOR"])
        self.assertEqual(len(self.native.denominator.calls), 1)
        return body

    def test_composition_stop_after_checkpoint_cannot_skip_denominator_on_restart(self):
        original = self.native.store.save
        class ProcessStopped(BaseException):
            pass

        def stop(*args, **kwargs):
            original(*args, **kwargs)
            raise ProcessStopped()

        with patch.object(self.native.store, "save", side_effect=stop):
            with self.assertRaises(ProcessStopped):
                self.r._process_one(runtime.COMPOSITION_QUEUE, self.native.clock.now())
        body = self.assert_complete()
        restored = recovery.restore(self.native, "composition-restart")
        self.assertFalse(restored._process_one(runtime.COMPOSITION_QUEUE, self.native.clock.now()))
        self.assertEqual(self.assert_complete()["intents"], body["intents"])

    def test_composition_final_slot_contains_required_denominator(self):
        with patch.object(modern, "MAX_RETAINED_CHECKPOINTS", 3), \
             patch.object(integrity, "MAX_RETAINED_CHECKPOINTS", 3):
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                self.r._process_one(runtime.COMPOSITION_QUEUE, self.native.clock.now())
            self.assert_complete()
            self.assertEqual(self.r.process_state, runtime.FAILED)
            self.assertIsNone(self.r.lease)
            self.assertFalse(self.r._accepting_work)


class CapacityOwnerCleanupTests(unittest.TestCase):
    def test_native_context_retains_only_cleanup_exclusion_then_releases_it(self):
        from momentum_hunter import modern_operational_runtime as startup
        from momentum_hunter import path_transaction
        f = startup_fixtures.ModernOperationalRuntimeTests(
            "test_fresh_start_selects_and_binds_native_runtime_sources")
        f.setUp()
        self.addCleanup(f.doCleanups)
        session = None
        with self.assertRaises(modern.CheckpointHistoryCapacityError):
            with f.open() as session:
                r = session.runtime
                r.request_discovery(f.native.clock.now())
                publication = r.checkpoint_store.publication
                original = r.checkpoint_store.save

                def interleave(*args, **kwargs):
                    publication.publish(successor(publication),
                        expected_previous=publication.current().snapshot_id)
                    return original(*args, **kwargs)

                with patch.object(modern, "MAX_RETAINED_CHECKPOINTS", 3), \
                     patch.object(integrity, "MAX_RETAINED_CHECKPOINTS", 3), \
                     patch.object(r.checkpoint_store, "save", side_effect=interleave):
                    with self.assertRaises(modern.CheckpointHistoryCapacityError):
                        r.request_discovery(f.native.clock.now(), reason="QB")
                    self.assertEqual(r.process_state, runtime.FAILED)
                    self.assertFalse(r._accepting_work)
                    self.assertIsNone(r.lease)
                    self.assertIsNone(r.lease_registry.current(r.config.runtime_identity))
                    self.assertIn(Path(session.epoch.root), startup._OWNED_ROOTS)
                    # The lifetime context still excludes another owner, but cannot do work.
                    with self.assertRaises(modern.CheckpointHistoryCapacityError):
                        r.tick(f.native.clock.now())
        self.assertIsNotNone(session)
        self.assertNotIn(Path(session.epoch.root), startup._OWNED_ROOTS)
        self.assertEqual(path_transaction._lease_depths(), {})
        f.assert_no_provider_contact()


class RealQueueCapacityRaceTests(QueueCapacityRaceFixture):
    def real_boundary(self, *, prepared):
        self.assertEqual(modern.MAX_RETAINED_CHECKPOINTS, 4096)
        self.assertEqual(integrity.MAX_RETAINED_CHECKPOINTS, 4096)
        current = self.publication.current()
        while modern.parse_bytes(current.manifest_bytes)["sequence"] < 4095:
            proposed = successor(self.publication)
            self.publication.publish(proposed, expected_previous=current.snapshot_id)
            current = proposed
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 4095)
        prior = inventory(self.publication.root)
        self.race(prepared=prepared, boundary="save")
        self.assertEqual(self.store.checkpoint_capacity()["retained_checkpoints"], 4096)
        after = inventory(self.publication.root)
        self.assertEqual({name: after[name] for name in prior if name != "current.json"},
                         {name: value for name, value in prior.items() if name != "current.json"})
        for offset in (1, 2):
            proposed = successor(self.publication, offset=offset)
            self.assertEqual(modern.parse_bytes(proposed.manifest_bytes)["sequence"], 4096 + offset)
            with self.assertRaises(modern.CheckpointHistoryCapacityError):
                self.publication.publish(proposed,
                    expected_previous=self.publication.current().snapshot_id)
            self.assertEqual(inventory(self.publication.root), after)
        self.assertEqual(self.load(), self.payload)

    def test_exact_4096_direct_queue_replacement_race(self):
        self.real_boundary(prepared=False)

    def test_exact_4096_prepared_queue_replacement_race(self):
        self.real_boundary(prepared=True)
