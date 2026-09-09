from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from momentum_hunter.automation_guardian_liveness import (
    ObservationClock, automation_heartbeat, wait_for_heartbeat,
)
from momentum_hunter.automation_preopen_guardian import continuous_phase_liveness
from momentum_hunter.automation_state_recovery import digest
from tests import test_automation_preopen_guardian as guardian_fixtures
from tests import test_automation_preopen_session as session_fixtures


class HeartbeatTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
        self.born = self.now-timedelta(seconds=20)
        self.started = self.born+timedelta(seconds=1)
        self.state = {"schema_version": 1, "jobs": {}, "state_version": 3,
                      "service_instance_id": "new-instance", "service_started_at": self.started.isoformat(),
                      "last_heartbeat_at": self.now.isoformat(),
                      "prospective_epoch": {"epochId": "epoch", "boundaryAt": (self.now-timedelta(hours=12)).isoformat()}}
        self.service = {"State": "Running", "ProcessId": 123, "ProcessCreatedAt": self.born.isoformat()}
        self.binding = {"wrapperProcessId": 123, "wrapperCreatedAt": self.born.isoformat(),
                        "serviceInstanceId": "new-instance", "serviceStartedAt": self.started.isoformat(),
                        "minimumStateVersion": 2, "epochId": "epoch"}

    def inspect(self, **kw):
        return automation_heartbeat(self.state, self.service, self.binding,
                                    now=kw.get("now", self.now), read_at=kw.get("read_at", self.now),
                                    source_sha256=kw.get("source_sha256"))

    def test_real_current_heartbeat_is_healthy(self):
        self.assertTrue(self.inspect()["ready"])
        self.assertEqual("SUPERVISOR_TICK_COMPLETION", self.inspect()["heartbeatType"])

    def test_stale_running_service_is_red(self):
        self.assertEqual("STALE", self.inspect(now=self.now+timedelta(seconds=121))["state"])

    def test_stopped_service_is_red(self):
        self.service["State"] = "Stopped"
        self.assertEqual("SERVICE_STOPPED", self.inspect()["state"])

    def test_foreign_instance_is_red(self):
        self.state["service_instance_id"] = "foreign"
        self.assertEqual("RUNTIME_INSTANCE_MISMATCH", self.inspect()["state"])

    def test_foreign_scm_generation_is_red(self):
        for k, v in (("ProcessId", 124), ("ProcessCreatedAt", self.started.isoformat())):
            old = self.service[k]
            self.service[k] = v
            self.assertEqual("RUNTIME_INSTANCE_MISMATCH", self.inspect()["state"])
            self.service[k] = old

    def test_unbound_runtime_is_never_green(self):
        self.binding.pop("serviceInstanceId")
        self.assertFalse(self.inspect()["ready"])

    def test_missing_binding_is_red(self):
        self.binding = {}
        self.assertEqual("RUNTIME_INSTANCE_MISMATCH", self.inspect()["state"])

    def test_prior_epoch_heartbeat_is_red(self):
        self.state["last_heartbeat_at"] = (self.now-timedelta(days=1)).isoformat()
        self.assertEqual("EPOCH_MISMATCH", self.inspect()["state"])

    def test_wrong_epoch_is_red(self):
        self.binding["epochId"] = "foreign-epoch"
        self.assertEqual("EPOCH_MISMATCH", self.inspect()["state"])

    def test_future_heartbeat_relative_to_actual_read_is_red(self):
        self.state["last_heartbeat_at"] = (self.now+timedelta(microseconds=1)).isoformat()
        self.assertEqual("CLOCK_ANOMALY", self.inspect(now=self.now+timedelta(seconds=1))["state"])

    def test_clock_regression_is_red(self):
        self.assertEqual("CLOCK_ANOMALY", self.inspect(now=self.now-timedelta(seconds=1))["state"])

    def test_state_generation_rollback_is_red(self):
        self.state["state_version"] = 1
        self.assertFalse(self.inspect()["ready"])

    def initial_epoch(self):
        for name in ("last_heartbeat_at", "service_started_at", "service_instance_id"):
            self.state.pop(name)

    def test_epoch_initializer_is_not_a_heartbeat(self):
        self.initial_epoch()
        result = self.inspect()
        self.assertEqual("WAITING_FOR_FIRST_HEARTBEAT", result["state"])
        self.assertTrue(result["pending"])
        self.assertFalse(result["ready"])

    def test_start_pending_is_not_green(self):
        self.initial_epoch()
        self.service["State"] = "Start Pending"
        self.assertEqual("STARTING", self.inspect()["state"])
        self.assertFalse(self.inspect()["ready"])

    def test_first_heartbeat_never_arrives_timeout_is_red(self):
        self.initial_epoch()
        self.assertEqual("STARTUP_TIMEOUT", self.inspect(now=self.born+timedelta(seconds=120))["state"])

    def test_partially_populated_foreign_state_not_excused_as_startup(self):
        self.state.pop("last_heartbeat_at")
        self.assertEqual("RUNTIME_INSTANCE_MISMATCH", self.inspect()["state"])

    def test_exact_prestart_state_can_wait_but_cannot_pass(self):
        self.state.update(service_started_at=(self.born-timedelta(hours=1)).isoformat(),
                          last_heartbeat_at=(self.born-timedelta(minutes=1)).isoformat())
        self.binding["preStartStateSha256"] = "a"*64
        pending = self.inspect(source_sha256="a"*64)
        self.assertEqual("WAITING_FOR_FIRST_HEARTBEAT", pending["state"])
        self.assertFalse(pending["ready"])
        self.assertFalse(self.inspect(source_sha256="b"*64)["pending"])
        expired = self.inspect(source_sha256="a"*64, now=self.born+timedelta(seconds=120))
        self.assertEqual("STARTUP_TIMEOUT", expired["state"])


class WaitTests(unittest.TestCase):
    def run_wait(self, observations):
        elapsed = [0.0]
        calls = []
        def observe():
            value = observations[min(len(calls), len(observations)-1)]
            calls.append(value)
            return value
        def pause(seconds):
            elapsed[0] += seconds
        result = wait_for_heartbeat(observe, poll_interval_seconds=1,
                                   monotonic=lambda: elapsed[0], pause=pause)
        return result, calls, elapsed[0]

    def healthy(self, version, second, instance="instance"):
        return {"state": "HEALTHY", "ready": True, "pending": False,
                "serviceInstanceId": instance, "serviceStartedAt": "2026-09-10T07:00:00-05:00",
                "stateVersion": version, "heartbeatAt": f"2026-09-10T07:00:{second:02d}-05:00"}

    def test_wait_advancing_real_heartbeat(self):
        pending = {"state": "WAITING_FOR_FIRST_HEARTBEAT", "pending": True, "ready": False}
        result, calls, elapsed = self.run_wait([pending, self.healthy(2, 1), self.healthy(3, 2)])
        self.assertEqual("HEARTBEAT_ADVANCEMENT_PROVEN", result["status"])
        self.assertEqual(3, len(calls))
        self.assertEqual(2, elapsed)

    def test_no_heartbeat_bounded_timeout(self):
        result, calls, elapsed = self.run_wait([{"state": "STARTING", "pending": True, "ready": False}])
        self.assertEqual("STARTUP_TIMEOUT", result["reason"])
        self.assertEqual(120, len(calls))
        self.assertEqual(120, elapsed)

    def test_one_static_heartbeat_not_advancement(self):
        result, _, _ = self.run_wait([self.healthy(2, 1)])
        self.assertEqual("STARTUP_TIMEOUT", result["reason"])

    def test_restart_during_wait_requires_new_binding_not_reuse(self):
        result, _, _ = self.run_wait([self.healthy(2, 1), self.healthy(3, 2, "foreign")])
        self.assertEqual("RUNTIME_INSTANCE_MISMATCH", result["reason"])

    def test_red_cannot_be_retried_into_green(self):
        result, calls, _ = self.run_wait([{"state": "EPOCH_MISMATCH", "ready": False}, self.healthy(3, 2)])
        self.assertEqual(1, len(calls))
        self.assertEqual("RED_NOT_READY", result["status"])

    def test_slow_observation_cannot_exceed_deadline_and_succeed(self):
        clock = [0.0]
        def observe():
            clock[0] += 121
            return self.healthy(3, 2)
        result = wait_for_heartbeat(observe, poll_interval_seconds=1, monotonic=lambda: clock[0], pause=lambda _: None)
        self.assertEqual("STARTUP_TIMEOUT", result["reason"])

    def test_nonadvancing_test_clock_still_bounded(self):
        result = wait_for_heartbeat(lambda: {"state": "STARTING", "pending": True},
                                    poll_interval_seconds=1, monotonic=lambda: 0, pause=lambda _: None)
        self.assertEqual("CLOCK_ANOMALY", result["reason"])
        self.assertLessEqual(len(result["observations"]), 121)

    def test_regression_cannot_recover_into_acceptance(self):
        for sequence in ([self.healthy(5, 10), self.healthy(6, 9), self.healthy(7, 11)],
                         [self.healthy(5, 10), self.healthy(4, 11), self.healthy(6, 12)],
                         [self.healthy(5, 10), self.healthy(6, 10), self.healthy(5, 11)]):
            result, calls, _ = self.run_wait(sequence)
            self.assertEqual("HEARTBEAT_GENERATION_REGRESSION", result["reason"])
            self.assertEqual("RED_NOT_READY", result["status"])
            self.assertLessEqual(len(calls), 3)

    def test_same_generation_cannot_change_heartbeat(self):
        result, _, _ = self.run_wait([self.healthy(5, 10), self.healthy(5, 11)])
        self.assertEqual("HEARTBEAT_GENERATION_REGRESSION", result["reason"])

    def test_frozen_clock_cannot_accept_advancing_real_heartbeats(self):
        sequence = iter([self.healthy(5, 10), self.healthy(6, 11)])
        result = wait_for_heartbeat(lambda: next(sequence), poll_interval_seconds=1,
                                   monotonic=lambda: 0, pause=lambda _: None)
        self.assertEqual("CLOCK_ANOMALY", result["reason"])
        self.assertEqual("RED_NOT_READY", result["status"])

    def test_startup_identity_acquisition_time_consumes_same_deadline(self):
        calls = []
        result = wait_for_heartbeat(lambda: calls.append(True), poll_interval_seconds=1,
                                    startup_elapsed_seconds=120, monotonic=lambda: 0, pause=lambda _: None)
        self.assertEqual("STARTUP_TIMEOUT", result["reason"])
        self.assertEqual([], calls)


class ObservationTests(unittest.TestCase):
    def fixture(self):
        f = guardian_fixtures.GuardianTests()
        f.session_date = "2026-09-10"
        f.setUp()
        self.addCleanup(f.tearDown)
        return f

    def test_published_after_inspection_start_before_read_is_not_future(self):
        f = self.fixture()
        initial = f.now-timedelta(seconds=1)
        calls = []
        def clock():
            calls.append(True)
            return initial if len(calls) == 1 else f.now
        old = f.inspect(now=initial)
        self.assertFalse(old["gates"]["STATE_HEARTBEAT_CURRENT"])
        self.assertFalse(old["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])
        new = f.inspect(clock=clock)
        self.assertEqual("GREEN_READY", new["status"], new["failedGates"])
        self.assertEqual(digest(f.fixture.path.read_bytes()), new["automationHeartbeatEvidence"]["sourceSha256"])
        self.assertEqual(f.state().service_instance_id, new["automationHeartbeatEvidence"]["serviceInstanceId"])

    def test_evidence_that_becomes_stale_while_verifying_cannot_pass(self):
        f = self.fixture()
        times = iter([f.now]*5 + [f.now+timedelta(seconds=121)])
        result = f.inspect(clock=lambda: next(times))
        self.assertFalse(result["gates"]["STATE_HEARTBEAT_CURRENT"])
        self.assertFalse(result["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_backward_clock_during_reads_never_green(self):
        f = self.fixture()
        times = iter([f.now+timedelta(seconds=1)] + [f.now]*5)
        result = f.inspect(clock=lambda: next(times))
        self.assertFalse(result["gates"]["OBSERVATION_CLOCK_ORDERED"])
        self.assertEqual("RED_NOT_READY", result["status"])

    def test_naive_injected_clock_is_rejected(self):
        clock = ObservationClock(lambda: datetime(2026, 9, 10))
        with self.assertRaises(ValueError):
            clock.take("bad")

    def test_scm_replacement_during_verification_never_green(self):
        f = self.fixture()
        result = f.inspect(service_reader=lambda: {})
        self.assertFalse(result["gates"]["SERVICE_OBSERVATION_STABLE"])

    def test_foreign_automation_state_cannot_borrow_release_hashes(self):
        f = self.fixture()
        state = f.state()
        state.service_instance_id = "foreign-instance"
        f.fixture.store().save(state)
        result = f.inspect()
        self.assertTrue(result["gates"]["OPENING_LOADED_BYTES_MATCH"])
        self.assertFalse(result["gates"]["STATE_HEARTBEAT_CURRENT"])

    def test_unbound_expectation_never_green(self):
        f = self.fixture()
        f.expectations.pop("automationRuntime")
        self.assertEqual("RED_NOT_READY", f.inspect()["status"])

    def test_initializer_only_epoch_stays_pending_without_fake_loaded_bytes(self):
        f = self.fixture()
        state = asdict(f.state())
        for key in ("service_instance_id", "service_started_at", "last_heartbeat_at",
                    "loaded_supervisor_sha256", "loaded_runtime_identity_module_sha256", "loaded_service_host_sha256"):
            state.pop(key)
        f.fixture.store().storage.save(state)
        result = f.inspect()
        self.assertEqual("PENDING_NOT_READY", result["status"], result["failedGates"])
        self.assertFalse(result["gates"]["STATE_HEARTBEAT_CURRENT"])

    def test_loaded_hash_failure_is_not_hidden_by_starting_claim(self):
        f = self.fixture()
        state = f.state()
        state.loaded_supervisor_sha256 = "wrong"
        f.fixture.store().save(state)
        self.assertEqual("RED_NOT_READY", f.inspect()["status"])

    def test_closed_weekend_holiday_dst_phases_follow_actual_calendar(self):
        fixture_builder = session_fixtures.SessionTests()
        self.addCleanup(fixture_builder.doCleanups)
        # The production calendar, not target-session date, selects present phase.
        for when, phase in (("2026-09-12T12:00:00-05:00", "SESSION_CLOSED"),
                            ("2026-09-07T10:00:00-05:00", "SESSION_CLOSED"),
                            ("2026-11-02T07:25:00-06:00", "PREMARKET"),
                            ("2026-11-02T08:35:00-06:00", "REGULAR_SESSION"),
                            ("2026-09-10T01:30:00-05:00", "SESSION_CLOSED"),
                            ("2026-09-10T15:21:47-05:00", "SESSION_CLOSED")):
            f = fixture_builder.phase_fixture(phase, datetime.fromisoformat(when))
            raw = json.loads(f.status_path.read_bytes())
            valid, evidence = continuous_phase_liveness(raw, json.loads(f.continuous.read_bytes()),
                                                        f.expectations["continuous"], f.now)
            self.assertTrue(valid, (when, evidence))

    def test_closed_missing_start_heartbeat_is_not_invented(self):
        f = self.fixture()
        status = json.loads(f.status_path.read_bytes())
        status["health"].pop("last_heartbeat_at")
        f.write_status(status)
        self.assertFalse(f.inspect()["gates"]["CONTINUOUS_EXPECTED_LIVENESS"])

    def test_concurrent_state_publish_retries_coherently(self):
        from momentum_hunter.automation_state_recovery import DurableStateStorage
        f = self.fixture()
        original = DurableStateStorage.load
        calls = []
        def changing(store, **kwargs):
            result = original(store, **kwargs)
            if store.path == f.fixture.path:
                calls.append(True)
                if len(calls) == 1:
                    f.fixture.store().save(f.state())
            return result
        with patch.object(DurableStateStorage, "load", changing):
            result = f.inspect()
        self.assertEqual("GREEN_READY", result["status"], result["failedGates"])
        attempts = result["automationHeartbeatEvidence"]["readAttempts"]
        self.assertEqual([False, True], [a["stable"] for a in attempts])
        self.assertEqual(digest(f.fixture.path.read_bytes()), result["automationHeartbeatEvidence"]["sourceSha256"])

    def test_continuously_changing_state_is_bounded_red(self):
        from momentum_hunter.automation_state_recovery import DurableStateStorage
        f = self.fixture()
        original = DurableStateStorage.load
        def changing(store, **kwargs):
            result = original(store, **kwargs)
            if store.path == f.fixture.path:
                f.fixture.store().save(f.state())
            return result
        with patch.object(DurableStateStorage, "load", changing):
            result = f.inspect()
        self.assertFalse(result["gates"]["STATE_SNAPSHOT_STABLE"])
        self.assertEqual("RED_NOT_READY", result["status"])
        self.assertEqual(3, len(result["automationHeartbeatEvidence"]["readAttempts"]))
