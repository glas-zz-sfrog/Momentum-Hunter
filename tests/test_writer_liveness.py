from __future__ import annotations

import bisect
import json
import math
import secrets
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.continuous_runtime import (
    ContinuousOpportunityRuntime, EVIDENCE_QUEUE, FAILED, REJECTED_STALE,
    REJECTED_CAPACITY, QueueCapacities, RuntimeCheckpointError,
    WRITER_ACCEPTED, WRITER_DUPLICATE, WRITER_UNAVAILABLE, WriterWriteResult,
    build_evidence_write_intent,
)
from momentum_hunter.continuous_evidence_writer import (
    CRASH_AFTER_COMMIT_BEFORE_ACK, ContinuousEvidenceWriterError,
)
from momentum_hunter.continuous_production import ProductionRemoteWriter, ProductionWriterServer
from momentum_hunter.continuous_production import _write_runtime_status
from momentum_hunter.event_runtime_writer_ipc import WriterEnvelope
from momentum_hunter.writer_liveness import (
    ACK_SLOW_HEALTH_THRESHOLD_SECONDS, WRITER_CORRECTNESS_FAILED, WriterLiveness,
)
from momentum_hunter.windows_writer_storage import WriterPhysicalStorageError
from tests.test_continuous_evidence_writer import WriterFixture
from tests.test_continuous_runtime import RuntimeFixture
from tests import test_continuous_production as production_fixtures


def catchup_report(latencies, arrival_seconds):
    """Replay measured service times against a declared producer arrival rate."""
    finishes, clock, peak, max_age = [], 0.0, 0, 0.0
    backlog_start, longest_recovery = None, 0.0
    for index, elapsed in enumerate(latencies):
        arrival = index * arrival_seconds
        if backlog_start is not None and clock <= arrival:
            longest_recovery = max(longest_recovery, clock - backlog_start)
            backlog_start = None
        if backlog_start is None and max(clock, arrival) + elapsed > arrival + arrival_seconds:
            backlog_start = arrival
        peak = max(peak, index + 1 - bisect.bisect_right(finishes, arrival))
        clock = max(clock, arrival) + elapsed
        finishes.append(clock)
        max_age = max(max_age, clock - arrival)
    if backlog_start is not None:
        longest_recovery = max(longest_recovery, clock - backlog_start)
    ordered = sorted(latencies)
    percentile = lambda q: ordered[max(0, math.ceil(len(ordered) * q) - 1)]
    return {
        "over500ms": sum(x > .5 for x in latencies),
        "over1s": sum(x > 1 for x in latencies),
        "maxAckSeconds": max(latencies), "p50": percentile(.5),
        "p95": percentile(.95), "p99": percentile(.99),
        "queuePeak": peak, "oldestPendingMaxAgeSeconds": max_age,
        "backlogRecoverySeconds": longest_recovery,
        "finalResidualDrainSeconds": max(0.0, clock - (len(latencies) - 1) * arrival_seconds),
        "queueModel": "SERIAL_REPLAY_OF_MEASURED_OR_DECLARED_SERVICE_TIMES",
        "producerArrivalRate": 1 / arrival_seconds,
        "effectiveDrainRate": len(latencies) / sum(latencies),
    }


class WriterHealthPolicyTests(unittest.TestCase):
    def test_exact_threshold_matrix_a_through_e(self):
        self.assertEqual(.500, ACK_SLOW_HEALTH_THRESHOLD_SECONDS)
        for elapsed in (.007, .490, .500, .510, .900, 1.500):
            with self.subTest(elapsed=elapsed):
                result = WriterWriteResult(WRITER_ACCEPTED, acknowledgement_seconds=elapsed)
                self.assertEqual(elapsed > .5, result.slow_ack_health_warning)
                self.assertEqual(WRITER_ACCEPTED, result.status)

    def test_nonfinite_or_negative_latency_rejected(self):
        for elapsed in (float('nan'), float('inf'), -.01):
            with self.subTest(elapsed=elapsed), self.assertRaises(ValueError):
                WriterWriteResult(WRITER_ACCEPTED, acknowledgement_seconds=elapsed)

    def test_physical_client_exact_slow_matrix_retains_fixed_health_signal(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WriterFixture(Path(temporary))
            try:
                prior = None
                for sequence, elapsed in enumerate((.007, .490, .510, .900, 1.500, 1.044, .007), 1):
                    intent = fixture.intent(sequence, predecessor_identity=prior)
                    with patch('momentum_hunter.continuous_evidence_writer.time.perf_counter', side_effect=[0, elapsed]):
                        result = fixture.client.write_intent_with_health(intent)
                    self.assertEqual(WRITER_ACCEPTED, result.status)
                    self.assertEqual(elapsed > .5, result.slow_ack_health_warning)
                    self.assertIsNone(fixture.client._pending_intent)
                    prior = intent.intent_id
            finally:
                fixture.close()

    def test_one_off_and_burst_recover_and_samples_are_bounded(self):
        state = WriterLiveness()
        for value in [1.044, .007, .007, .510, .900, 1.5] + [.007] * 150:
            state.record_ack(value)
        self.assertEqual(4, state.slow_acks)
        self.assertEqual(2, state.over_one_second)
        self.assertEqual(0, state.consecutive_slow_acks)
        self.assertEqual(128, len(state.latencies))
        self.assertEqual(1.5, state.maximum_ack_seconds)
        self.assertEqual(state, WriterLiveness.restore(json.loads(json.dumps(state.snapshot()))))

    def observe(self, state, now, depth, age=0):
        return state.observe(now=now, depth=depth, capacity=10, oldest_age=age, horizon=30)

    def test_no_progress_is_bounded_and_survives_restart(self):
        state = WriterLiveness(arrivals=1)
        self.assertIsNone(self.observe(state, 100, 1))
        self.assertIsNone(self.observe(state, 129, 1, 29))
        state = WriterLiveness.restore(json.loads(json.dumps(state.snapshot())))
        self.assertEqual('NO_PROGRESS', self.observe(state, 130, 1, 30))
        self.assertEqual('NO_PROGRESS', self.observe(state, 131, 0))

    def test_incomplete_checkpoint_cannot_reset_liveness_and_bounds_are_finite(self):
        state = WriterLiveness(arrivals=1)
        self.observe(state, 100, 1)
        raw = state.snapshot()
        del raw['pending_since']
        with self.assertRaises(ValueError):
            WriterLiveness.restore(raw)
        for horizon in (float('inf'), float('nan'), 0, -1):
            with self.subTest(horizon=horizon), self.assertRaises(ValueError):
                state.observe(now=101, depth=1, capacity=10, oldest_age=1, horizon=horizon)

    def test_persistent_slow_but_durable_growth_fails_closed(self):
        state = WriterLiveness(arrivals=3)
        self.observe(state, 100, 3)
        for now, depth in ((110, 4), (120, 6), (130, 8)):
            state.arrivals += 3
            state.drains += 1
            state.last_progress = now
            state.record_ack(1.5)
            result = self.observe(state, now, depth, now - 100)
        self.assertEqual('SUSTAINED_BACKPRESSURE', result)

    def test_capacity_rejection_pressure_has_bound_even_with_young_advancing_head(self):
        state = WriterLiveness(arrivals=10)
        self.observe(state, 100, 10)
        for now in range(101, 132):
            state.drains += 1
            state.last_progress = now
            state.record_ack(.9)
            self.observe(state, now, 9, 9)
            state.arrivals += 1
            state.capacity_rejections += 1
            result = self.observe(state, now, 10, 9)
            if now == 115:
                state = WriterLiveness.restore(json.loads(json.dumps(state.snapshot())))
        self.assertEqual('SUSTAINED_CAPACITY_PRESSURE', result)
        self.assertGreater(state.recent_offered_rate, state.recent_drain_rate)

    def test_transient_capacity_pressure_recovers_after_full_rejection_free_horizon(self):
        state = WriterLiveness(arrivals=10)
        self.observe(state, 100, 10)
        state.capacity_rejections += 1
        self.observe(state, 110, 10, 10)
        state.drains = 3
        state.last_progress = 120
        self.assertIsNone(self.observe(state, 120, 7, 20))
        self.assertEqual(110, state.rejection_started_at)
        state.drains = 10
        state.last_progress = 125
        self.assertIsNone(self.observe(state, 125, 0))
        self.assertIsNone(self.observe(state, 140, 0))
        self.assertEqual(110, state.rejection_started_at)
        state.arrivals += 10
        state.capacity_rejections += 1
        self.assertIsNone(self.observe(state, 141, 10))
        self.assertEqual(141, state.rejection_started_at)

    def test_rejection_history_survives_burst_dips_and_empty_queue_restart(self):
        for drained_depth in (8, 0):
            state = WriterLiveness(arrivals=10)
            self.observe(state, 100, 10)
            result = None
            for now in range(102, 135, 2):
                count = 10 - drained_depth
                state.drains += count
                state.last_progress = now
                self.observe(state, now, drained_depth, 8 if drained_depth else 0)
                state.arrivals += count
                state.capacity_rejections += 1
                result = self.observe(state, now, 10, 8)
                if now == 116:
                    state = WriterLiveness.restore(json.loads(json.dumps(state.snapshot())))
                if result:
                    break
            self.assertEqual('SUSTAINED_CAPACITY_PRESSURE', result)
            self.assertEqual(132, now)

    def test_monitor_restore_rejects_types_and_terminal_contradictions(self):
        for key, value in (('pending_since', '100'), ('arrivals', True), ('failure', 'lost'),
                           ('classification', WRITER_CORRECTNESS_FAILED), ('window_arrivals', 1),
                           ('last_progress', 100), ('maximum_ack_seconds', float('nan'))):
            raw = WriterLiveness().snapshot()
            raw[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                WriterLiveness.restore(raw)

    def test_retained_rejection_crosscheck_allows_real_quiet_recovery_not_erased_history(self):
        state = WriterLiveness(arrivals=10)
        for now in (100, 110, 120):
            state.capacity_rejections += 1
            state.last_progress = now
            self.observe(state, now, 10, 8)
        state.validate_rejection_history([100,110,120], horizon=30)
        state.drains = 10
        state.last_progress = 125
        self.observe(state, 125, 0)
        self.observe(state, 150, 0)
        restored = WriterLiveness.restore(json.loads(json.dumps(state.snapshot())))
        restored.validate_rejection_history([100,110,120], horizon=30)
        self.assertEqual(100, restored.rejection_started_at)
        restored.arrivals += 10
        restored.capacity_rejections += 1
        self.observe(restored, 160, 10)
        restored.validate_rejection_history([100,110,120,160], horizon=30)
        self.assertEqual(160, restored.rejection_started_at)

    def test_slow_durable_writer_that_keeps_up_is_not_failed_for_latency(self):
        state = WriterLiveness()
        for now in range(100, 500, 5):
            state.arrivals += 1
            self.observe(state, now, 1)
            state.drains += 1
            state.last_progress = now + 1.5
            state.record_ack(1.5)
            self.assertIsNone(self.observe(state, now + 1.5, 0))
        self.assertGreater(state.slow_acks, 50)

    def test_near_capacity_warns_and_transient_queue_drains(self):
        state = WriterLiveness(arrivals=9)
        self.assertIsNone(self.observe(state, 100, 9))
        self.assertEqual('CAPACITY_PRESSURE', state.classification)
        for now, depth in ((110, 7), (120, 4), (130, 2), (135, 0)):
            state.drains = 9 - depth
            state.last_progress = now
            self.assertIsNone(self.observe(state, now, depth, now - 100 if depth else 0))
        self.assertEqual(35, state.recovery_seconds)
        self.assertEqual(9, state.queue_peak)

    def test_transient_burst_service_time_model_measures_full_recovery(self):
        latencies = [.007] * 100 + [1.044, .900, 1.5] + [.007] * 4197
        report = catchup_report(latencies, 120 / 4300)
        self.assertEqual(4300, len(latencies))
        self.assertLessEqual(report['queuePeak'], 128)
        self.assertGreater(report['backlogRecoverySeconds'], 3.4)
        self.assertLess(report['backlogRecoverySeconds'], 5)
        self.assertLess(report['finalResidualDrainSeconds'], .03)
        self.assertEqual(3, report['over500ms'])
        print('WRITER_CATCHUP=' + json.dumps(report, sort_keys=True))

    def test_durable_record_missing_ack_stays_pending(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = WriterFixture(Path(temporary))
            try:
                intent = fixture.intent()
                fixture.writer.arm_crash(CRASH_AFTER_COMMIT_BEFORE_ACK)
                self.assertEqual(WRITER_UNAVAILABLE, fixture.client.write_intent(intent))
                self.assertIsNotNone(fixture.client._pending_intent)
                self.assertEqual(WRITER_DUPLICATE, fixture.client.write_intent(intent))
                self.assertEqual(1, len(list((fixture.root / fixture.topology.namespace / 'records').rglob('*.json'))))
            finally:
                fixture.close()

    def test_missing_ack_missing_record_corruption_and_false_receipt_fail(self):
        for mutation in ('ack-delete', 'record-delete', 'record-corrupt', 'false-ack'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                fixture = WriterFixture(Path(temporary))
                real_accept = fixture.writer.accept
                def damaged(envelope):
                    ack = real_accept(envelope)
                    if mutation == 'false-ack':
                        return replace(ack, sequence=ack.sequence + 1)
                    pattern = '*.ack.json' if mutation == 'ack-delete' else '*.json'
                    directory = 'sessions' if mutation == 'ack-delete' else 'records'
                    path = next((fixture.root / fixture.topology.namespace / directory).rglob(pattern))
                    if mutation == 'record-corrupt':
                        path.write_bytes(b'corrupt')
                    else:
                        path.unlink()
                    return ack
                try:
                    with patch.object(fixture.writer, 'accept', side_effect=damaged):
                        with self.assertRaises((ValueError, OSError, WriterPhysicalStorageError)):
                            fixture.client.write_intent(fixture.intent())
                    self.assertIsNotNone(fixture.client._pending_intent)
                finally:
                    fixture.close()


class RuntimeWriterLivenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = RuntimeFixture(Path(self.temp.name))
        self.runtime = self.fixture.runtime
        self.now = self.fixture.clock.now()
        self.runtime.start(self.now)

    def intent(self, sequence, at=None):
        return build_evidence_write_intent(
            runtime_instance_id=self.runtime.runtime_instance_id, sequence=sequence,
            evidence_type='COMPOSITION_CYCLE', record_identity=f'record-{sequence}',
            record_fingerprint=f'{sequence:064x}',
            predecessor_identity=self.runtime._last_intent_id,
            requested_at=(at or self.now).isoformat(), payload_fingerprint=f'{sequence:064x}')

    def restore(self, now):
        f = self.fixture
        return ContinuousOpportunityRuntime.restore(
            config=f.config, runtime_instance_id='runtime-instance-2', now=now,
            discovery_source=f.discovery, market_data_source=f.market, event_source=f.events,
            composition_source=f.composer, denominator_source=f.denominator, writer=f.writer,
            lease_registry=f.leases, checkpoint_store=f.store)

    def test_one_1044_ack_followed_by_normal_progress_no_backoff(self):
        for sequence in range(1, 5):
            self.runtime.admit_evidence_intent(self.intent(sequence), self.now)
        results = [WriterWriteResult(WRITER_ACCEPTED, acknowledgement_seconds=x)
                   for x in (1.044, .007, .007, .007)]
        with patch.object(self.fixture.writer, 'write_intent', side_effect=results):
            for _ in results:
                self.assertTrue(self.runtime._process_evidence(self.now))
        health = self.runtime.health(self.now)
        self.assertEqual(0, dict(health.queue_depths)[EVIDENCE_QUEUE])
        self.assertEqual(1, health.writer_slow_events)
        self.assertEqual(4, health.evidence_accepted_count)
        self.assertEqual({}, self.runtime._evidence_retry_not_before)
        self.assertIsNone(health.writer_health['failure'])

    def test_pending_restart_preserves_finite_deadline_and_terminal_state(self):
        self.runtime.admit_evidence_intent(self.intent(1), self.now)
        self.fixture.writer.mode = WRITER_UNAVAILABLE
        self.assertFalse(self.runtime._process_evidence(self.now))
        self.runtime._checkpoint(self.now)
        restored = self.restore(self.now + timedelta(seconds=31))
        deadline = self.now + timedelta(seconds=restored._stall_threshold_seconds())
        self.assertFalse(restored._process_evidence(deadline))
        self.assertEqual(FAILED, restored.process_state)
        self.assertEqual(1, len(restored._queues[EVIDENCE_QUEUE]))
        restored._checkpoint(deadline)
        twice = self.restore(deadline + timedelta(seconds=31))
        self.assertEqual(FAILED, twice.process_state)
        self.assertEqual(REJECTED_STALE, twice.admit_evidence_intent(self.intent(2), deadline))

    def test_corrupt_ack_terminal_without_head_loss_or_replacement(self):
        self.runtime.admit_evidence_intent(self.intent(1), self.now)
        with patch.object(self.fixture.writer, 'write_intent', return_value=WriterWriteResult(
                WRITER_CORRECTNESS_FAILED, detail_code='ACK_RECORD_HASH_MISMATCH')):
            self.assertFalse(self.runtime._process_evidence(self.now))
        self.assertEqual(FAILED, self.runtime.process_state)
        self.assertEqual(1, len(self.runtime._queues[EVIDENCE_QUEUE]))
        self.assertEqual(0, self.runtime.health(self.now).evidence_accepted_count)
        self.runtime._check_writer_liveness(self.now + timedelta(seconds=1))
        self.assertEqual(WRITER_CORRECTNESS_FAILED, self.runtime._writer_liveness.classification)
        self.runtime._checkpoint(self.now + timedelta(seconds=1))
        restored = self.restore(self.now + timedelta(seconds=31))
        self.assertEqual(WRITER_CORRECTNESS_FAILED, restored._writer_liveness.classification)
        for suggested in ('RUNNING', 'IDLE_OUT_OF_SESSION', 'STOPPED'):
            status = Path(self.temp.name) / (suggested + '.json')
            _write_runtime_status(status, restored.health(self.now + timedelta(seconds=2)),
                                  state=suggested, config={})
            self.assertEqual('FAILED', json.loads(status.read_text())['state'])

    def test_hash_valid_malformed_checkpoint_fails_before_writer_contact(self):
        self.runtime.admit_evidence_intent(self.intent(1), self.now)
        self.runtime._fail_writer(WRITER_CORRECTNESS_FAILED, 'ACK_RECORD_HASH_MISMATCH', self.now)
        self.runtime._checkpoint(self.now)
        original = self.fixture.store.load(self.fixture.config.runtime_identity)
        for mutation in ('empty', 'missing-monitor', 'missing-failure', 'clear-failure',
                         'wrong-count', 'missing-pending', 'future'):
            raw = json.loads(json.dumps(original))
            if mutation == 'empty':
                raw['writer_liveness'] = {}
            elif mutation == 'missing-monitor':
                del raw['writer_liveness']
            elif mutation == 'missing-failure':
                del raw['writer_liveness']['failure']
            elif mutation == 'clear-failure':
                raw['writer_liveness']['failure'] = None
            elif mutation == 'wrong-count':
                raw['writer_liveness']['arrivals'] += 1
            elif mutation == 'missing-pending':
                raw['writer_liveness']['pending_since'] = None
            else:
                raw['writer_liveness']['last_observation'] += 999999
            self.fixture.store.save(self.fixture.config.runtime_identity, raw)
            with self.subTest(mutation=mutation), patch.object(self.fixture.writer, 'write_intent') as writer:
                with self.assertRaises(RuntimeCheckpointError):
                    self.restore(self.now + timedelta(seconds=31))
                writer.assert_not_called()

    def test_real_runtime_capacity_rejections_escalate_across_restart(self):
        self.fixture = RuntimeFixture(Path(self.temp.name) / 'small', queues=QueueCapacities(evidence=4))
        self.runtime = self.fixture.runtime
        self.runtime.start(self.now)
        for sequence in range(1, 5):
            self.runtime.admit_evidence_intent(self.intent(sequence), self.now)
        horizon = self.runtime._stall_threshold_seconds()
        for seconds in range(1, int(horizon) + 2):
            at = self.now + timedelta(seconds=seconds)
            if seconds < horizon + 1:
                with patch('momentum_hunter.continuous_runtime.time.perf_counter', return_value=0.0):
                    self.assertTrue(self.runtime._process_evidence(at))
                self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence + 1, at), at)
            rejected = self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence + 1, at), at)
            self.assertEqual(REJECTED_CAPACITY, rejected)
            if seconds == 300:
                self.runtime._checkpoint(at)
                self.runtime = self.restore(at + timedelta(milliseconds=500))
        self.assertEqual('SUSTAINED_CAPACITY_PRESSURE', self.runtime._writer_liveness.failure)
        self.assertEqual(FAILED, self.runtime.process_state)

    def test_rejection_anchor_must_match_retained_runtime_admission_evidence(self):
        self.fixture = RuntimeFixture(Path(self.temp.name)/'anchors', queues=QueueCapacities(evidence=4))
        self.runtime = self.fixture.runtime
        self.runtime.start(self.now)
        for sequence in range(1,5):
            self.runtime.admit_evidence_intent(self.intent(sequence),self.now)
        with patch('momentum_hunter.continuous_runtime.time.perf_counter',return_value=0.0):
            for seconds in (1,10,20):
                at=self.now+timedelta(seconds=seconds)
                for _ in range(2):
                    self.runtime._process_evidence(at)
                for _ in range(2):
                    self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
                self.assertEqual(REJECTED_CAPACITY,self.runtime.admit_evidence_intent(
                    self.intent(self.runtime._sequence+1,at),at))
        self.runtime._checkpoint(self.now+timedelta(seconds=20))
        original=self.fixture.store.load(self.fixture.config.runtime_identity)
        for mutation in ('clear-episode','advance-first','erase-count','corrupt-decision',
                         'nonnumeric-selector','queue-selector','decision-selector','selector-type'):
            raw=json.loads(json.dumps(original))
            monitor=raw['writer_liveness']
            if mutation=='clear-episode':
                monitor['rejection_started_at']=monitor['rejection_last_at']=None
            elif mutation=='advance-first':
                monitor['rejection_started_at']=monitor['rejection_last_at']
            elif mutation=='erase-count':
                monitor['capacity_rejections']=monitor['observed_rejections']=0
            elif mutation=='corrupt-decision':
                raw['backpressure'][0]['fingerprint']='0'*64
            else:
                monitor['rejection_started_at']=monitor['rejection_last_at']=None
                for decision in raw['backpressure']:
                    if mutation=='nonnumeric-selector':
                        decision['work_key'] += 'x'
                    elif mutation=='queue-selector':
                        decision['queue_name']='not-evidence'
                    elif mutation=='decision-selector':
                        decision['decision']='not-rejected'
                    else:
                        decision['work_key']=17
            self.fixture.store.save(self.fixture.config.runtime_identity,raw)
            with self.subTest(mutation=mutation), patch.object(self.fixture.writer,'write_intent') as writer, \
                    patch.object(self.fixture.store,'save') as save:
                with self.assertRaises(RuntimeCheckpointError):
                    self.restore(self.now+timedelta(seconds=31))
                writer.assert_not_called()
                save.assert_not_called()
        # A legitimate history-capacity record is validated but is not a queue rejection.
        self.runtime._record_backpressure(EVIDENCE_QUEUE, 'continuous-intent-history',
            REJECTED_CAPACITY, self.now+timedelta(seconds=20), '1'*64)
        self.runtime._checkpoint(self.now+timedelta(seconds=20))
        original=self.fixture.store.load(self.fixture.config.runtime_identity)
        self.fixture.store.save(self.fixture.config.runtime_identity,original)
        self.runtime=self.restore(self.now+timedelta(seconds=31))
        deadline=self.now+timedelta(seconds=631)
        self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,deadline),deadline)
        self.assertEqual('SUSTAINED_CAPACITY_PRESSURE',self.runtime._writer_liveness.failure)

    def test_completion_quiet_boundary_and_recorded_admission_clock_restore(self):
        for elapsed in (.0005, .001, .002, 1.044):
            for fresh_admission in (False, True):
                with self.subTest(elapsed=elapsed, fresh_admission=fresh_admission):
                    self.fixture = RuntimeFixture(Path(self.temp.name)/f'clock-{elapsed}-{fresh_admission}',
                                                  queues=QueueCapacities(evidence=4))
                    self.runtime = self.fixture.runtime
                    self.runtime.start(self.now)
                    with patch('momentum_hunter.continuous_runtime.time.perf_counter',return_value=0.0):
                        for _ in range(4):
                            self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1),self.now)
                        for seconds in (1,10,20):
                            at=self.now+timedelta(seconds=seconds)
                            for _ in range(2):
                                self.runtime._process_evidence(at)
                            for _ in range(2):
                                self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
                            self.assertEqual(REJECTED_CAPACITY,self.runtime.admit_evidence_intent(
                                self.intent(self.runtime._sequence+1,at),at))
                        at=self.now+timedelta(seconds=600)
                        for _ in range(4):
                            self.runtime._process_evidence(at)
                        for _ in range(4):
                            self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
                    at=self.now+timedelta(seconds=649.999)
                    with patch('momentum_hunter.continuous_runtime.time.perf_counter',side_effect=[0.0,elapsed]):
                        self.assertTrue(self.runtime._process_evidence(at))
                    admission=self.now+timedelta(seconds=650.002+elapsed) if fresh_admission else at
                    self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,admission),admission)
                    self.assertEqual(REJECTED_CAPACITY,self.runtime.admit_evidence_intent(
                        self.intent(self.runtime._sequence+1,admission),admission))
                    self.runtime._checkpoint(self.now+timedelta(seconds=652))
                    restored=self.restore(self.now+timedelta(seconds=653))
                    self.assertEqual(4,len(restored._queues[EVIDENCE_QUEUE]))
                    self.assertEqual(None if fresh_admission else 'SUSTAINED_CAPACITY_PRESSURE',
                                     restored._writer_liveness.failure)

    def test_runtime_burst_drains_each_exact_identity_once_in_order(self):
        expected = []
        for sequence in range(1, 33):
            item = self.intent(sequence)
            expected.append(item)
            self.runtime.admit_evidence_intent(item, self.now)
        depths, ages, delivered = [], [], []
        def accepted(intent):
            delivered.append(intent)
            elapsed = (1.044, .9, 1.5)[len(delivered)-1] if len(delivered) <= 3 else .007
            return WriterWriteResult(WRITER_ACCEPTED, acknowledgement_seconds=elapsed)
        with patch.object(self.fixture.writer, 'write_intent', side_effect=accepted):
            for step in range(32):
                at = self.now + timedelta(seconds=step + 1)
                self.assertTrue(self.runtime._process_evidence(at))
                metric = self.runtime._queues[EVIDENCE_QUEUE].metrics(at)
                depths.append(len(self.runtime._queues[EVIDENCE_QUEUE]))
                ages.append(metric.oldest_age_seconds)
        self.assertEqual(expected, delivered)
        self.assertEqual(list(range(31, -1, -1)), depths)
        self.assertGreater(max(ages), ages[-1])
        self.assertEqual(0, ages[-1])
        self.assertEqual(32, self.runtime.health(self.now).evidence_accepted_count)

    def test_tick_completion_cannot_erase_same_tick_rejection_deadline(self):
        self.fixture=RuntimeFixture(Path(self.temp.name)/'tick-clock',queues=QueueCapacities(evidence=4))
        self.runtime=self.fixture.runtime
        self.runtime.start(self.now)
        with patch('momentum_hunter.continuous_runtime.time.perf_counter',return_value=0.0):
            for _ in range(4):
                self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1),self.now)
            for seconds in (1,10,20):
                at=self.now+timedelta(seconds=seconds)
                for _ in range(2):
                    self.runtime._process_evidence(at)
                for _ in range(3):
                    self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
            at=self.now+timedelta(seconds=600)
            for _ in range(4):
                self.runtime._process_evidence(at)
            for _ in range(4):
                self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
        def upstream(queue, at):
            self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
            self.assertEqual(REJECTED_CAPACITY,self.runtime.admit_evidence_intent(
                self.intent(self.runtime._sequence+1,at),at))
            return True
        with patch.object(self.runtime,'_schedule_due_work'), \
                patch.object(self.runtime,'_next_queue_with_work',side_effect=[EVIDENCE_QUEUE,'COMPOSITION',EVIDENCE_QUEUE]), \
                patch.object(self.runtime,'_process_one',side_effect=upstream), \
                patch('momentum_hunter.continuous_runtime.time.perf_counter',side_effect=[0,0,0,.002,.002]):
            self.runtime.tick(self.now+timedelta(seconds=649.999),work_budget=2)
        # tick renewed its existing lease; restart waits for that lease to expire.
        restored=self.restore(self.now+timedelta(seconds=650+self.fixture.config.lease_ttl_seconds))
        self.assertEqual(FAILED,restored.process_state)
        self.assertEqual('SUSTAINED_CAPACITY_PRESSURE',restored._writer_liveness.failure)
        self.assertEqual(4,len(restored._queues[EVIDENCE_QUEUE]))

    def test_runtime_persistent_success_with_growing_backlog_is_bounded(self):
        for sequence in range(1, 4):
            self.runtime.admit_evidence_intent(self.intent(sequence), self.now)
        sequence = 4
        with patch.object(self.fixture.writer, 'write_intent', return_value=WriterWriteResult(
                WRITER_ACCEPTED, acknowledgement_seconds=1.5)):
            for seconds in (200, 400):
                now = self.now + timedelta(seconds=seconds)
                for _ in range(3):
                    self.runtime.admit_evidence_intent(self.intent(sequence, now), now)
                    sequence += 1
                self.assertTrue(self.runtime._process_evidence(now))
            self.assertIn('WRITER_BACKPRESSURE', self.runtime._active_degradations)
            self.assertFalse(self.runtime._process_evidence(self.now + timedelta(seconds=630)))
        self.assertEqual(FAILED, self.runtime.process_state)
        self.assertEqual('SUSTAINED_BACKPRESSURE', self.runtime._writer_liveness.failure)
        self.assertEqual(7, len(self.runtime._queues[EVIDENCE_QUEUE]))
        self.assertEqual(2, self.runtime.health(self.now).evidence_accepted_count)

    def test_configured_writer_horizon_survives_schedule_cadence_changes(self):
        for configured in (60,300):
            for cadences in ((60,300),(300,60),(300,300)):
                for gap_delta in (-1,0,1):
                    for empty_at_change in (False,True):
                        with self.subTest(configured=configured,cadences=cadences,gap=gap_delta,empty=empty_at_change):
                            name=f'cadence-{configured}-{cadences[0]}-{cadences[1]}-{gap_delta}-{empty_at_change}'
                            f=RuntimeFixture(Path(self.temp.name)/name,queues=QueueCapacities(evidence=4))
                            f.config=replace(f.config,cadence=replace(f.config.cadence,broad_discovery_seconds=configured))
                            f.runtime=f.new_runtime('runtime-instance-1')
                            self.fixture,self.runtime=f,f.runtime
                            self.runtime.start(self.now)
                            horizon=2*configured+f.config.cadence.housekeeping_seconds
                            def tick(seconds,cadence):
                                with patch.object(self.runtime,'_schedule_due_work'), \
                                        patch.object(self.runtime,'_next_queue_with_work',return_value=None):
                                    self.runtime.tick(self.now+timedelta(seconds=seconds),work_budget=1,
                                                      discovery_cadence_seconds=cadence)
                            with patch('momentum_hunter.continuous_runtime.time.perf_counter',return_value=0.0):
                                tick(0,cadences[0])
                                for _ in range(4):
                                    self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1),self.now)
                                at=self.now+timedelta(seconds=1)
                                self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
                                for _ in range(4):
                                    self.runtime._process_evidence(self.now+timedelta(seconds=2))
                                second=1+horizon+gap_delta
                                at=self.now+timedelta(seconds=second)
                                for _ in range(5):
                                    self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
                                if empty_at_change:
                                    for _ in range(4):
                                        self.runtime._process_evidence(self.now+timedelta(seconds=second+1))
                                tick(second+2,cadences[1])
                                restored=self.restore(self.now+timedelta(seconds=second+3+f.config.lease_ttl_seconds))
                            self.assertEqual(horizon,restored._writer_liveness_horizon_seconds())
                            self.assertIsNone(restored._writer_liveness.failure)
                            self.assertEqual((1 if gap_delta<0 else second)+self.now.timestamp(),
                                             restored._writer_liveness.rejection_started_at)
                            self.runtime=restored
                            later=second+3+f.config.lease_ttl_seconds
                            at=self.now+timedelta(seconds=later)
                            for _ in range(5):
                                self.runtime.admit_evidence_intent(self.intent(self.runtime._sequence+1,at),at)
                            self.assertEqual('SUSTAINED_CAPACITY_PRESSURE' if gap_delta<0 else None,
                                             self.runtime._writer_liveness.failure)

    def test_uncertain_head_recovery_before_deadline_drains_exact_sequence(self):
        for sequence in range(1, 5):
            self.runtime.admit_evidence_intent(self.intent(sequence), self.now)
        self.fixture.writer.mode = WRITER_UNAVAILABLE
        self.assertFalse(self.runtime._process_evidence(self.now))
        self.fixture.writer.mode = WRITER_ACCEPTED
        for _ in range(4):
            self.assertTrue(self.runtime._process_evidence(self.now + timedelta(seconds=6)))
        self.assertEqual([1, 2, 3, 4], [i.sequence for i in self.fixture.writer.intents])
        self.assertEqual(0, len(self.runtime._queues[EVIDENCE_QUEUE]))
        self.assertEqual({}, self.runtime._evidence_retry_counts)
        self.assertIsNone(self.runtime._writer_liveness.failure)


class RemoteWriterHealthTests(unittest.TestCase):
    def test_lost_response_reconnect_replays_one_record_without_skipping(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'ipc.key').write_bytes(secrets.token_bytes(32))
            helper = production_fixtures.ContinuousProductionTests()
            config = helper._config(root)
            server = ProductionWriterServer(config)
            remote = ProductionRemoteWriter(config, source_identity='production-continuous-runtime-retry')
            lost = False
            def request(frame):
                nonlocal lost
                if frame['frameType'] == 'HELLO':
                    return server._handshake(frame)
                response = server._persist(WriterEnvelope(**frame['envelope']))
                if not lost:
                    lost = True
                    raise TimeoutError('Synthetic response lost after durable commit')
                return response
            try:
                intent = helper._intent(remote.source_identity)
                with patch.object(remote, '_request', side_effect=request):
                    self.assertEqual(WRITER_UNAVAILABLE, remote.write_intent(intent).status)
                    self.assertIsNone(remote.sender)
                    self.assertEqual(WRITER_DUPLICATE, remote.write_intent(intent).status)
                self.assertEqual(1, len(list((server.root / 'records').rglob('*.json'))))
                self.assertEqual(2, len(list((server.root / 'sessions').rglob('*.ack.json'))))
            finally:
                server.close()

    def test_remote_production_class_latency_and_receipt_reconciliation(self):
        for mutation in (None, 'ack-delete', 'record-delete', 'record-corrupt', 'false-ack'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'ipc.key').write_bytes(secrets.token_bytes(32))
                helper = production_fixtures.ContinuousProductionTests()
                config = helper._config(root)
                server = ProductionWriterServer(config)
                remote = ProductionRemoteWriter(config, source_identity='production-continuous-runtime-health-test')
                def request(frame):
                    if frame['frameType'] == 'HELLO':
                        return server._handshake(frame)
                    ack = server._persist(WriterEnvelope(**frame['envelope']))
                    if mutation == 'false-ack':
                        return {**ack, 'sequence': ack['sequence'] + 1}
                    if mutation == 'ack-delete':
                        next((server.root / 'sessions').rglob('*.ack.json')).unlink()
                    elif mutation == 'record-delete':
                        next((server.root / 'records').rglob('*.json')).unlink()
                    elif mutation == 'record-corrupt':
                        next((server.root / 'records').rglob('*.json')).write_bytes(b'corrupt')
                    return ack
                try:
                    with patch.object(remote, '_request', side_effect=request), patch(
                            'momentum_hunter.continuous_production.time.perf_counter', side_effect=[0, 1.044] if mutation is None else [0]):
                        result = remote.write_intent(helper._intent(remote.source_identity))
                    if mutation is None:
                        self.assertEqual(WRITER_ACCEPTED, result.status)
                        self.assertTrue(result.slow_ack_health_warning)
                    else:
                        self.assertEqual(WRITER_CORRECTNESS_FAILED, result.status)
                finally:
                    server.close()
