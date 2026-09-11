from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.continuous_live_qualification import LiveCompositionSource
from momentum_hunter.continuous_research_export import SimulatedPublicationCrash
from momentum_hunter.continuous_v2_producer import ContinuousV2Producer
from momentum_hunter.continuous_v2_projection import OWNER, fingerprint, identity
from momentum_hunter.strategy_science_recorder.contract import parse_export_envelope_v2
from tests import test_continuous_natural_setup as natural_fixture
from tests.test_continuous_research_export_v2 import policy

at = natural_fixture.at


def runtime_config():
    from momentum_hunter.continuous_runtime import ContinuousRuntimeConfig, RuntimeCadence, QueueCapacities
    return ContinuousRuntimeConfig(runtime_identity="native-v2-offline", session_date="2026-08-17",
        cadence=RuntimeCadence(300, 30, 600, 180), queues=QueueCapacities(evidence=256))


def manifest():
    followup = policy()
    followup["retry_and_finalization_cutoff"]["finalization_cutoff"] = "2026-08-17T21:00:00Z"
    followup.pop("policy_sha256")
    followup["policy_sha256"] = fingerprint(followup)
    return {"exchange_market_date": "2026-08-17", "manifest_phase": "START",
            "market_timezone": "America/New_York", "outcome_followup_policy": followup,
            "regular_session_close": "2026-08-17T20:00:00Z",
            "regular_session_open": "2026-08-17T13:30:00Z",
            "session_id": identity("SESSION_ID", "fixture-20260817"), "session_kind": "REGULAR_SESSION",
            "source_owner_namespace": OWNER, "source_root_identity": "a" * 64,
            "source_runtime_activation_id": "offline-native-engine010"}


class ContinuousV2ProducerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = at(8, 0)
        self.native = natural_fixture.ContinuousNaturalSetupTests()
        self.native.setUp()
        self.addCleanup(self.native.doCleanups)
        self.producer = self.opened()
        self.addCleanup(lambda: self.producer.close())

    def opened(self, **kwargs):
        return ContinuousV2Producer(export_root=self.root / "export", manifest=manifest(),
            source_root_identity="a" * 64, runtime_fingerprint=runtime_config().fingerprint,
            science_custody_roots=(self.root / "science",), protected_roots=(self.native.root,),
            clock=lambda: self.now, **kwargs).initialize(self.now)

    def native_composition(self):
        self.now = at(11, 21)
        self.native._prepare(self.now, generation=1)
        request = replace(self.native._request(self.now, generation=1), opportunity_id=self.native.member.member_id)
        return LiveCompositionSource(self.native.state).compose(request)

    def discovery(self):
        self.now = at(11, 0)
        source = {"sourceEvidence": {"snapshot": self.native.snapshot.to_dict()}}
        return self.producer.capture(stage="DISCOVERY", source_id=self.native.snapshot.snapshot_id,
                                     source=source, observed_at=self.now.isoformat())

    def composition(self, result=None):
        result = result or self.native_composition()
        return self.producer.capture(stage="COMPOSITION", source_id=result.cycle_id,
                                     source=json.loads(result.evidence_payload_json), observed_at=self.now.isoformat())

    def records(self):
        return [parse_export_envelope_v2(p.raw_bytes) for p in self.producer.exporter.published()]

    def test_natural_six_families_and_manifests_preserve_source(self):
        self.discovery()
        result = self.native_composition()
        self.composition(result)
        self.producer.capture(stage="HEALTH", source_id="failure-1", source={
            "event_id": "failure-1", "stage": "READINESS", "event_class": "READINESS_FAILURE",
            "reason": "MISSING_CANDLE"}, observed_at=self.now.isoformat())
        records = self.records()
        self.assertEqual({"SESSION_MANIFEST", "DISCOVERY_CYCLE", "DECISION_FACT", "MARKET_FACT", "PROVIDER_HEALTH"},
                         {r.event_type for r in records})
        plans = [r.payload["reference_plan"] for r in records if "reference_plan" in r.payload]
        self.assertTrue(plans)
        source_steps = json.loads(result.evidence_payload_json)["naturalSteps"]
        original_plan_ids = {m["intraday_plan"]["plan_id"] for step in source_steps
                             for m in step["producerRecord"]["compositionCycle"]["member_results"] if m["intraday_plan"]}
        self.assertEqual(original_plan_ids, {p["tradeplan_id"]["owner_id"] for p in plans})
        self.assertTrue(all(p["entry"]["state"] == "UNKNOWN" for p in plans))
        self.assertFalse(any("outcome-observation" in str(r.payload) for r in records))
        final = self.producer.finalize(at(17, 1), terminal_proven=True, pending_source_events=0)
        self.assertEqual("FINAL_PUBLISHED", final.status)

    def test_restart_and_duplicate_preserve_exact_publication_bytes(self):
        self.discovery()
        native = self.native_composition()
        self.composition(native)
        before = [p.raw_bytes for p in self.producer.exporter.published()]
        self.producer.close()
        self.now += timedelta(minutes=1)
        self.producer = self.opened()
        self.composition(native)
        self.assertEqual(before, [p.raw_bytes for p in self.producer.exporter.published()])

    def test_captured_source_recovers_after_crash_before_publication(self):
        with patch.object(self.producer, "_dispatch", side_effect=SimulatedPublicationCrash("before")):
            with self.assertRaises(SimulatedPublicationCrash):
                self.discovery()
        self.assertEqual(1, len(self.records()))
        self.producer.close()
        self.now = at(12, 0)
        self.producer = self.opened()
        self.assertEqual(3, len(self.records()))  # START, bounded discovery, partial-coverage health.
        for publication in self.producer.exporter.published()[1:]:
            self.assertEqual(self.now.isoformat(), json.loads(publication.raw_bytes)["emitted_at"])
        self.assertEqual(self.native.snapshot.received_at.isoformat(),
                         self.records()[1].payload["discovery_cycle"]["discovery_time"]["raw_value"])

    def test_partial_multi_publication_recovers_idempotently(self):
        native = self.native_composition()
        original = self.producer._dispatch
        calls = 0

        def crash(item, observed):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise SimulatedPublicationCrash("mid-batch")
            return original(item, observed)

        with patch.object(self.producer, "_dispatch", side_effect=crash):
            with self.assertRaises(SimulatedPublicationCrash):
                self.composition(native)
        partial = [p.raw_bytes for p in self.producer.exporter.published()]
        self.producer.close()
        self.now = at(13, 0)
        self.producer = self.opened()
        final = [p.raw_bytes for p in self.producer.exporter.published()]
        self.assertEqual(partial, final[:len(partial)])
        self.assertGreater(len(final), len(partial))
        self.assertTrue(all(json.loads(raw)["emitted_at"] == self.now.isoformat()
                            for raw in final[len(partial):]))

    def test_start_checkpoint_does_not_backdate_first_publication(self):
        self.producer.close()
        options = dict(export_root=self.root / "start-recovery", manifest=manifest(),
            source_root_identity="a" * 64, runtime_fingerprint=runtime_config().fingerprint,
            science_custody_roots=(self.root / "science",), protected_roots=(self.native.root,),
            clock=lambda: self.now)
        candidate = ContinuousV2Producer(**options)
        with patch.object(candidate.exporter, "start", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                candidate.initialize(self.now)
        self.now = at(9, 0)
        candidate = ContinuousV2Producer(**options)
        candidate.initialize(self.now)
        try:
            raw = json.loads(candidate.exporter.published()[0].raw_bytes)
            self.assertEqual(self.now.isoformat(), raw["emitted_at"])
            self.assertEqual(at(8, 0).isoformat(), raw["event_time"])
        finally:
            candidate.close()

    def _interrupted_capture_finality(self, stop_after):
        original = self.producer._dispatch
        calls = 0

        def interrupt(item, observed):
            nonlocal calls
            if calls == stop_after:
                raise KeyboardInterrupt
            calls += 1
            return original(item, observed)

        with patch.object(self.producer, "_dispatch", side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.discovery()
        self.assertIsNone(self.producer.failure)
        self.assertEqual("IDLE", self.producer._control()["state"])
        before = [p.raw_bytes for p in self.producer.exporter.published()]
        self.assertEqual(1 + stop_after, len(before))
        self.assertEqual("INCOMPLETE_NO_FINAL", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=0).status)
        self.assertEqual(before, [p.raw_bytes for p in self.producer.exporter.published()])
        self.producer.close()
        self.now = at(13, 0)
        self.producer = self.opened()
        recovered = [p.raw_bytes for p in self.producer.exporter.published()]
        self.assertEqual(before, recovered[:len(before)])
        self.assertEqual(3, len(recovered))
        self.assertTrue(all(json.loads(raw)["emitted_at"] == self.now.isoformat()
                            for raw in recovered[len(before):]))
        self.assertEqual("FINAL_PUBLISHED", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=0).status)

    def test_standalone_hard_interruption_before_publication_cannot_finalize(self):
        self._interrupted_capture_finality(0)

    def test_standalone_hard_interruption_mid_publication_cannot_finalize(self):
        self._interrupted_capture_finality(1)

    def test_restart_after_final_preserves_exact_bytes_and_remains_terminal(self):
        self.discovery()
        self.producer.finalize(at(17, 1), terminal_proven=True, pending_source_events=0)
        before = [p.raw_bytes for p in self.producer.exporter.published()]
        self.producer.close()
        self.now = at(17, 2)
        self.producer = self.opened()
        self.assertTrue(self.producer.terminal)
        self.assertEqual(before, [p.raw_bytes for p in self.producer.exporter.published()])
        with self.assertRaisesRegex(ValueError, "active admitted session"):
            self.discovery()

    def test_native_health_intent_uses_native_known_at_not_recovery_clock(self):
        from types import SimpleNamespace
        self.now = at(12, 0)
        for kind in ("SYSTEM_FAILURE", "READINESS_DEFERRED"):
            with self.subTest(kind=kind):
                intent = SimpleNamespace(evidence_type=kind, record_identity=kind,
                    payload_fingerprint="b" * 64, payload_json=json.dumps({"knownAt": at(10, 0).isoformat()}))
                self.producer.capture_intent(intent, self.now.isoformat())
                raw = json.loads(self.producer.exporter.published()[-1].raw_bytes)
                self.assertEqual(at(10, 0).isoformat(), raw["payload"]["provider_health_event"]
                                 ["source_event_time"]["raw_value"])
                self.assertEqual(self.now.isoformat(), raw["emitted_at"])
        intent.payload_json = "{}"
        with self.assertRaises(KeyError):
            self.producer.capture_intent(intent, self.now.isoformat())

    def test_conflicting_source_fails_closed(self):
        self.discovery()
        changed = {"sourceEvidence": {"snapshot": self.native.snapshot.to_dict(), "changed": True}}
        with self.assertRaisesRegex(ValueError, "CONFLICTING_SOURCE_IDENTITY"):
            self.producer.capture(stage="DISCOVERY", source_id=self.native.snapshot.snapshot_id,
                                  source=changed, observed_at=self.now.isoformat())
        self.assertEqual("INCOMPLETE_NO_FINAL", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=0).status)

    def test_missing_or_corrupt_source_checkpoint_rejects_recovery(self):
        self.discovery()
        path = next(self.producer.store.root.glob("source-*.json"))
        self.producer.close()
        path.write_text("{}", encoding="ascii")
        with self.assertRaises(ValueError):
            self.opened()

    def test_manifest_and_runtime_binding_change_rejected(self):
        self.producer.close()
        changed = manifest()
        changed["source_runtime_activation_id"] = "not-the-frozen-session"
        candidate = ContinuousV2Producer(export_root=self.root / "export", manifest=changed,
            source_root_identity="a" * 64, runtime_fingerprint="b" * 64,
            science_custody_roots=(self.root / "science",), protected_roots=(self.native.root,))
        with self.assertRaises(ValueError):
            candidate.initialize(self.now)

    def test_no_final_before_cutoff_or_with_pending_source(self):
        self.assertEqual("INCOMPLETE_NO_FINAL", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=1).status)
        with self.assertRaises(ValueError):
            self.producer.finalize(at(12, 0), terminal_proven=True, pending_source_events=0)

    def test_science_input_or_new_family_not_admitted(self):
        with self.assertRaises(ValueError):
            self.producer.capture(stage="OUTCOME", source_id="future", source={}, observed_at=self.now.isoformat())
        self.assertEqual(1, len(self.records()))

    def test_source_clock_later_than_publication_fails_without_slack(self):
        source = {"sourceEvidence": {"snapshot": self.native.snapshot.to_dict()}}
        with self.assertRaises(ValueError):
            self.producer.capture(stage="DISCOVERY", source_id="future-clock", source=source,
                                  observed_at=self.now.isoformat())

    def test_source_mapping_does_not_mutate_native_payload(self):
        native = self.native_composition()
        payload = json.loads(native.evidence_payload_json)
        before = deepcopy(payload)
        self.producer.capture(stage="COMPOSITION", source_id=native.cycle_id, source=payload,
                              observed_at=self.now.isoformat())
        self.assertEqual(before, payload)

    def test_exact_bytes_are_accepted_by_unchanged_science_contract(self):
        from momentum_hunter.strategy_science_recorder import StrategyScienceRecorder

        self.discovery()
        self.composition()
        recorder = StrategyScienceRecorder(self.root / "science", source_root_identity="a" * 64,
                    writer_instance_id="offline-contract-verification", clock=lambda: at(12, 0).isoformat())
        try:
            for record in self.producer.exporter.published():
                self.assertEqual("ACCEPTED", recorder.accept(record.raw_bytes).status)
        finally:
            recorder.close()

    def runtime(self, producer=None):
        from momentum_hunter.continuous_runtime import (
            ContinuousOpportunityRuntime, ContinuousRuntimeConfig, RuntimeCadence, QueueCapacities,
            LogicalRuntimeLeaseRegistry, RuntimeCheckpointStore, DiscoveryPulse, ReadinessResult)
        from momentum_hunter.continuous_live_qualification import LiveDenominatorSource
        from tests.test_continuous_runtime import SyntheticWriter, SyntheticEvents
        owner = self

        class Discovery:
            def discover(self, request):
                return DiscoveryPulse(pulse_id=owner.native.snapshot.snapshot_id,
                    fingerprint=owner.native.snapshot.fingerprint, source_rows_represented=1,
                    symbols_for_readiness=("AAA",), new_symbols=("AAA",), retained_symbols=(),
                    provider_bound_symbols=(), evidence_payload_json=json.dumps({"snapshot": owner.native.snapshot.to_dict()}))

        class Market:
            def evaluate(self, request):
                owner.native._prepare(owner.now, generation=1)
                owner.native.state.material_event_fingerprints["AAA"] = "c" * 64
                owner.native.state.material_event_known_at["AAA"] = owner.now.isoformat()
                return ReadinessResult(request_id=request.request_id, symbol="AAA", status="READY",
                    fingerprint="c" * 64, ready=True, decision_cutoff=owner.now.isoformat(),
                    evidence_known_at=owner.native._known_at(owner.now), opportunity_id=owner.native.member.member_id)

        kwargs = dict(config=runtime_config(),
                      runtime_instance_id="native-v2-instance", discovery_source=Discovery(),
                      market_data_source=Market(), event_source=SyntheticEvents(),
                      composition_source=LiveCompositionSource(self.native.state),
                      denominator_source=LiveDenominatorSource(self.native.state), writer=SyntheticWriter(),
                      lease_registry=LogicalRuntimeLeaseRegistry(),
                      checkpoint_store=RuntimeCheckpointStore(self.root / "runtime-checkpoint"),
                      research_producer=producer)
        return ContinuousOpportunityRuntime(**kwargs), kwargs

    def test_real_runtime_dispatches_native_chain_without_an_extra_writer_intent(self):
        self.now = at(11, 21)
        runtime, _ = self.runtime(self.producer)
        runtime.start(self.now)
        try:
            health = runtime.tick(self.now, work_budget=512)
            self.assertIsNone(runtime.research_publication_failure)
            self.assertGreater(health.composition_cycles, 0)
            self.assertTrue(any("reference_plan" in r.payload for r in self.records()))
            self.assertEqual(256, runtime.config.queues.evidence)
            self.assertTrue(all(i.evidence_type in {"DISCOVERY_CYCLE", "COMPOSITION_CYCLE", "OPPORTUNITY_DENOMINATOR"}
                                for i in runtime.writer.intents))
        finally:
            runtime.shutdown(self.now)

    def test_publication_failure_does_not_rewrite_native_decision_or_queue(self):
        self.now = at(11, 21)
        runtime, _ = self.runtime(self.producer)
        runtime.start(self.now)
        try:
            with patch.object(self.producer, "capture_intent", side_effect=OSError("offline storage failure")):
                health = runtime.tick(self.now, work_budget=512)
            self.assertEqual("OSError", runtime.research_publication_failure)
            self.assertGreater(health.composition_cycles, 0)
            self.assertTrue(runtime.writer.intents)
            self.assertEqual("OSError", runtime.checkpoint_store.load(runtime.config.runtime_identity)
                             ["research_producer"]["runtime_failure"])
        finally:
            runtime.shutdown(self.now)

    def test_runtime_identity_mismatch_rejected(self):
        self.producer.runtime_fingerprint = "0" * 64
        with self.assertRaisesRegex(ValueError, "runtime identity"):
            self.runtime(self.producer)

    def test_serialization_and_storage_failures_are_terminally_honest(self):
        with self.assertRaises(ValueError):
            self.producer.capture(stage="HEALTH", source_id="nan", source={"value": float("nan")},
                                  observed_at=self.now.isoformat())
        self.assertIsNotNone(self.producer.failure)
        with patch.object(self.producer.store, "save", side_effect=OSError("disposable storage fault")):
            with self.assertRaises(OSError):
                self.discovery()
        self.assertEqual(1, len(self.records()))

    def test_late_source_retains_event_clock_not_publication_clock(self):
        source = {"event_id": "late-readiness", "stage": "READINESS", "event_class": "READINESS_FAILURE",
                  "reason": "MISSING", "source_observed_at": at(10, 0).isoformat()}
        self.now = at(12, 0)
        self.producer.capture(stage="HEALTH", source_id="late-readiness", source=source,
                              observed_at=self.now.isoformat())
        raw = json.loads(self.producer.exporter.published()[-1].raw_bytes)
        self.assertEqual(self.now.isoformat(), raw["emitted_at"])
        self.assertEqual(at(10, 0).isoformat(), raw["payload"]["provider_health_event"]
                         ["source_event_time"]["raw_value"])

    def test_runtime_restart_before_source_capture_replays_pending_intent(self):
        from momentum_hunter.continuous_runtime import ContinuousOpportunityRuntime
        self.now = at(11, 21)
        runtime, kwargs = self.runtime(self.producer)
        runtime.start(self.now)
        original_capture = self.producer.capture_intent
        def interrupt_composition(intent, observed_at):
            if intent.evidence_type == "COMPOSITION_CYCLE":
                raise KeyboardInterrupt
            return original_capture(intent, observed_at)
        with patch.object(self.producer, "capture_intent", side_effect=interrupt_composition):
            with self.assertRaises(KeyboardInterrupt):
                runtime.tick(self.now, work_budget=512)
        self.assertIsNotNone(runtime.checkpoint_store.load(runtime.config.runtime_identity)
                             ["research_producer"]["pending_intent"])
        runtime.lease_registry.release(runtime.lease)
        self.producer.close()
        self.now += timedelta(seconds=31)
        self.producer = self.opened()
        kwargs["research_producer"] = self.producer
        restored = ContinuousOpportunityRuntime.restore(now=self.now, **kwargs)
        try:
            self.assertIsNone(restored.research_publication_failure)
            self.assertIsNone(restored._research_pending_intent)
            self.assertGreater(len(self.records()), 1)
            before = [p.raw_bytes for p in self.producer.exporter.published()]
            for intent in restored.evidence_intents:
                restored._publish_research_intent(intent)
            self.assertEqual(before, [p.raw_bytes for p in self.producer.exporter.published()])
        finally:
            restored.shutdown(self.now)

    def test_native_commit_before_emit_recovers_exact_record_ids_without_recomposition(self):
        from momentum_hunter.continuous_runtime import ContinuousOpportunityRuntime
        self.now = at(11, 21)
        runtime, kwargs = self.runtime(self.producer)
        runtime.start(self.now)
        original_emit = runtime._emit_intent
        def crash_before_emit(**arguments):
            if arguments["evidence_type"] == "COMPOSITION_CYCLE":
                raise KeyboardInterrupt
            return original_emit(**arguments)
        with patch.object(runtime, "_emit_intent", side_effect=crash_before_emit):
            with self.assertRaises(KeyboardInterrupt):
                runtime.tick(self.now, work_budget=512)
        native = kwargs["composition_source"].producer_store.load()
        self.assertTrue(native)
        expected = {r.record_id for r in native}
        self.assertFalse(any(r.event_type == "DECISION_FACT" for r in self.records()))
        self.assertEqual("INCOMPLETE_NO_FINAL", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=0).status)
        runtime.lease_registry.release(runtime.lease)
        self.producer.close()
        self.now = at(12, 0)
        self.producer = self.opened()
        kwargs["research_producer"] = self.producer
        with patch.object(kwargs["composition_source"], "compose", side_effect=AssertionError("No re-evaluation")):
            restored = ContinuousOpportunityRuntime.restore(now=self.now, **kwargs)
        try:
            self.assertIsNone(restored.research_publication_failure)
            actual = {r.payload["decision_event"]["decision_id"]["owner_id"]
                      for r in self.records() if r.event_type == "DECISION_FACT"}
            self.assertEqual(expected, actual)
            self.assertEqual(native, kwargs["composition_source"].producer_store.load())
            before = [p.raw_bytes for p in self.producer.exporter.published()]
            restored._finish_research_handoff(recovered=True)
            self.assertEqual(before, [p.raw_bytes for p in self.producer.exporter.published()])
        finally:
            restored.shutdown(self.now)

    def test_interrupted_native_handoff_without_custody_blocks_final(self):
        self.producer.begin_native_operation("DISCOVERY", "no-native-custody", object())
        with self.assertRaisesRegex(ValueError, "CUSTODY_UNAVAILABLE"):
            self.producer.finish_native_operation({"DISCOVERY": object()}, recovered=True)
        self.assertEqual("INCOMPLETE_NO_FINAL", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=0).status)

    def test_empty_interrupted_handoff_is_not_false_success(self):
        source = LiveCompositionSource(self.native.state)
        self.producer.begin_native_operation("COMPOSITION", "pre-call-crash", source)
        with self.assertRaisesRegex(ValueError, "COMPLETION_UNPROVEN"):
            self.producer.finish_native_operation({"COMPOSITION": source}, recovered=True)
        self.assertEqual("INCOMPLETE_NO_FINAL", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=0).status)

    def test_deleted_control_and_unpublished_source_cannot_be_silent_empty_recovery(self):
        self.producer.close()
        self.producer.store.path_for("native-handoff").unlink()
        with self.assertRaises((ValueError, OSError)):
            self.opened()

    def test_deleted_unpublished_source_is_still_required_by_index(self):
        with patch.object(self.producer, "_dispatch", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.discovery()
        source_path = next(self.producer.store.root.glob("source-*.json"))
        self.producer.close()
        source_path.unlink()
        with self.assertRaisesRegex(ValueError, "INDEX_INCOMPLETE"):
            self.opened()

    def test_preexisting_native_record_is_not_republished_as_new_prospective_evaluation(self):
        result = self.native_composition()
        self.runtime(self.producer)
        self.composition(result)
        self.assertFalse(any(r.event_type == "DECISION_FACT" for r in self.records()))

    def test_unexplained_native_change_and_cache_loss_block_final(self):
        source = LiveCompositionSource(self.native.state)
        self.producer.bind_native_sources({"DISCOVERY": object(), "COMPOSITION": source})
        self.native_composition()
        self.assertEqual("INCOMPLETE_NO_FINAL", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=0).status)
        with self.assertRaisesRegex(ValueError, "UNEXPLAINED_NATIVE"):
            self.producer.begin_native_operation("COMPOSITION", "unexplained", source)

    def discovery_custody(self):
        from types import SimpleNamespace
        from momentum_hunter.hot_universe import HotUniverseStore, HotUniversePolicy
        root = self.root / "discovery-native"
        source = SimpleNamespace(store=HotUniverseStore(root / "state.json"), state=SimpleNamespace(root=root))
        self.producer.bind_native_sources({"DISCOVERY": source, "COMPOSITION": object()})
        self.producer.begin_native_operation("DISCOVERY", "native-discovery", source)
        source.store.apply_snapshot(policy=HotUniversePolicy(maximum_hot_symbols=1),
            snapshot=self.native.snapshot, recorded_at=at(11, 0))
        return source

    def test_discovery_receipt_plus_original_file_recovers_without_provider(self):
        source = self.discovery_custody()
        path = source.state.root / "source-evidence" / "finviz" / (self.native.snapshot.snapshot_id + ".json")
        path.parent.mkdir(parents=True)
        path.write_text(self.native.snapshot.canonical_json(), encoding="ascii")
        self.now = at(12, 0)
        self.producer.finish_native_operation({"DISCOVERY": source}, recovered=True)
        record = next(r for r in self.records() if r.event_type == "DISCOVERY_CYCLE")
        self.assertEqual("discovery:" + self.native.snapshot.snapshot_id, record.payload["discovery_cycle"]
                         ["discovery_cycle_id"]["owner_id"])
        before = [p.raw_bytes for p in self.producer.exporter.published()]
        self.producer.finish_native_operation({"DISCOVERY": source}, recovered=True)
        self.assertEqual(before, [p.raw_bytes for p in self.producer.exporter.published()])

    def test_discovery_receipt_without_original_file_blocks_final(self):
        source = self.discovery_custody()
        with self.assertRaises(OSError):
            self.producer.finish_native_operation({"DISCOVERY": source}, recovered=True)
        self.assertEqual("INCOMPLETE_NO_FINAL", self.producer.finalize(
            at(17, 1), terminal_proven=True, pending_source_events=0).status)

    def test_startup_factory_positive_descriptor_uses_canonical_runtime_binding(self):
        from momentum_hunter.continuous_production import build_research_fact_producer, _runtime_config
        config = {"runtimeBuildHash": "a" * 64, "runtimeStateRoot": str(self.root / "runtime"),
            "evidenceRoot": str(self.root / "writer"), "runtimeIdentity": "production-test",
            "broadDiscoverySeconds": 300, "researchFactExportV2": {
                "exportRoot": str(self.root / "factory"), "startManifest": manifest(),
                "scienceCustodyRoots": [str(self.root / "science-factory")]}}
        before = deepcopy(config)
        producer = build_research_fact_producer(config, self.now)
        try:
            self.assertEqual(_runtime_config(config).fingerprint, producer.runtime_fingerprint)
            self.assertEqual("NONE", producer.status()["executionAuthority"])
            self.assertEqual(before, config)
        finally:
            producer.close()

    def test_recovery_rejects_other_member_even_with_same_symbol(self):
        source = LiveCompositionSource(self.native.state)
        self.producer.begin_native_operation("COMPOSITION", "wrong-member", source,
                                            {"symbol": "AAA", "opportunity_id": "different-member"})
        self.native_composition()
        with self.assertRaisesRegex(ValueError, "REQUEST_IDENTITY_MISMATCH"):
            self.producer.finish_native_operation({"COMPOSITION": source}, recovered=True)

    def test_native_session_mismatch_fails_without_relabeling(self):
        native = self.native_composition()
        self.producer.manifest["exchange_market_date"] = "2026-08-18"
        with self.assertRaisesRegex(ValueError, "SESSION_MISMATCH"):
            self.composition(native)

    def test_missing_preoperation_store_is_not_empty_success(self):
        self.native_composition()
        source = LiveCompositionSource(self.native.state)
        self.producer.begin_native_operation("COMPOSITION", "lost-store", source)
        source.producer_store.path.unlink()
        with self.assertRaisesRegex(ValueError, "STORE_DISAPPEARED"):
            self.producer.finish_native_operation({"COMPOSITION": source}, recovered=True)

    def test_production_factory_dormant_and_malformed_descriptor_fail_closed(self):
        from momentum_hunter.continuous_production import build_research_fact_producer, ProductionDeploymentError
        self.assertIsNone(build_research_fact_producer({}, self.now))
        with self.assertRaises(ProductionDeploymentError):
            build_research_fact_producer({"researchFactExportV2": {}}, self.now)

    def test_finalization_storage_failure_does_not_raise_into_runtime(self):
        from momentum_hunter.continuous_production import finalize_research_session, SESSION_CLOSED
        runtime, _ = self.runtime(self.producer)
        runtime.start(self.now)
        try:
            with patch.object(self.producer, "finalize", side_effect=OSError("disposable final fault")):
                finalize_research_session(runtime, SESSION_CLOSED, at(17, 1))
            self.assertEqual("OSError", runtime.research_publication_failure)
            self.assertFalse(self.producer.terminal)
        finally:
            runtime.shutdown(self.now)

    def run_day(self):
        """Synthetic inputs, real runtime, composition, V2 and dedicated storage."""
        import time
        from dataclasses import asdict
        from momentum_hunter.continuous_runtime import (ContinuousOpportunityRuntime, DiscoveryPulse,
            ReadinessResult, WRITER_UNAVAILABLE)
        from momentum_hunter.broad_discovery import build_discovery_snapshot, DiscoverySourceRow
        from momentum_hunter.models import Candidate
        from momentum_hunter.continuous_production import finalize_research_session, SESSION_CLOSED
        from tests.test_continuous_evidence_writer import WriterFixture

        owner = self
        runtime, kwargs = self.runtime(self.producer)
        market = kwargs["market_data_source"]
        physical = WriterFixture(self.root / "writer", runtime_id=runtime.runtime_instance_id)
        self.addCleanup(physical.close)
        samples, durations = [], []

        class Discovery:
            def discover(self, request):
                now = owner.now
                if now == at(10, 0):
                    raise OSError("offline provider outage")
                rows = []
                if now >= at(11, 0):
                    # The independently admitted AAA member is retained from
                    # the canonical natural-setup fixture, not joined by symbol.
                    rows.append(DiscoverySourceRow.from_mapping(source_row_ordinal=1,
                        source_row_identity="AAA:" + now.isoformat(), source_values={"Ticker": "AAA"},
                        candidate=Candidate(ticker="AAA", price=100, percent_change=5, volume=5000000,
                                            relative_volume=2, market_cap=10000000000)))
                rows.append(DiscoverySourceRow.from_mapping(source_row_ordinal=len(rows) + 1,
                    source_row_identity="BBB:" + now.isoformat(), source_values={"Ticker": "BBB"},
                    candidate=Candidate(ticker="BBB", price=1, percent_change=0, volume=100,
                                        relative_volume=0.1, market_cap=100000)))
                snap = build_discovery_snapshot(source="finviz", source_version="offline-engine010",
                    requested_at=now - timedelta(seconds=2), received_at=now - timedelta(seconds=1),
                    evaluated_at=now, query_identity=owner.native.snapshot.query_identity,
                    source_contract_fingerprint="b" * 64, semantic_plausibility_fingerprint="c" * 64,
                    source_rows=tuple(rows))
                ready = ("AAA",) if now >= at(11, 21) else (("BAD",) if now == at(9, 30) else ())
                return DiscoveryPulse(pulse_id=snap.snapshot_id, fingerprint=snap.fingerprint,
                    source_rows_represented=len(rows), symbols_for_readiness=ready, new_symbols=ready,
                    retained_symbols=(), provider_bound_symbols=(),
                    evidence_payload_json=json.dumps({"snapshot": snap.to_dict()}))

        class Market:
            def evaluate(self, request):
                if request.symbol == "BAD":
                    return ReadinessResult(request_id=request.request_id, symbol="BAD", status="FAILED",
                        fingerprint="d" * 64, ready=False, reason="MISSING_CANDLES")
                return market.evaluate(request)

        class Writer:
            delayed = False

            def write_intent(self, intent):
                if self.delayed:
                    return WRITER_UNAVAILABLE
                return physical.client.write_intent(intent)

        writer = Writer()
        kwargs.update(discovery_source=Discovery(), market_data_source=Market(), writer=writer)
        runtime = ContinuousOpportunityRuntime(**kwargs)
        runtime.start(self.now)
        try:
            for stamp in (at(8, 0), at(9, 29), at(9, 30), at(10, 0), at(11, 21), at(11, 26), at(11, 26, 5), at(12, 0)):
                self.now = stamp
                writer.delayed = stamp == at(11, 26)
                begun = time.perf_counter()
                health = runtime.tick(stamp, work_budget=512)
                durations.append(time.perf_counter() - begun)
                self.assertIsNone(runtime.research_publication_failure)
                samples.append({"time": stamp.isoformat(), "health": asdict(health),
                                "publication_count": len(self.records())})
            before = [p.raw_bytes for p in self.producer.exporter.published()]
            runtime.shutdown(self.now)
            self.producer.close()
            self.now = at(12, 1)
            self.producer = self.opened()
            kwargs["research_producer"] = self.producer
            runtime = ContinuousOpportunityRuntime.restore(now=self.now, **kwargs)
            self.assertIsNone(runtime.research_publication_failure)
            self.assertEqual(before, [p.raw_bytes for p in self.producer.exporter.published()])
            self.producer.capture(stage="HEALTH", source_id="late-native-health",
                source={"event_id": "late-native-health", "stage": "READINESS", "event_class": "PARTIAL",
                        "reason": "OFFLINE_DELAYED_RECEIPT", "source_observed_at": at(11, 59).isoformat()},
                observed_at=self.now.isoformat())
            runtime.shutdown(self.now)
            self.now = at(17, 1)
            finalize_research_session(runtime, SESSION_CLOSED, self.now)
            self.assertTrue(self.producer.terminal, {"producer": self.producer.status(),
                "runtime_failure": runtime.research_publication_failure,
                "pending_work": runtime.pending_work, "health": asdict(runtime.health(self.now))})
            records = self.records()
            family_counts = {name: sum(len(r.payload.get(name, [])) if name == "observations"
                                      else int(name in r.payload) for r in records)
                for name in ("discovery_cycle", "observations", "decision_event", "market_snapshot",
                             "reference_plan", "provider_health_event")}
            self.assertTrue(all(family_counts.values()), family_counts)
            phases = [r.payload["manifest_phase"] for r in records
                      if r.event_type == "SESSION_MANIFEST"]
            self.assertEqual(["START", "FINAL"], phases)
            self.assertEqual(256, runtime.config.queues.evidence)
            self.assertEqual(len(records), len({p.source_event_id for p in self.producer.exporter.published()}))
            native_ids = {r.record_id for r in kwargs["composition_source"].producer_store.load()}
            decision_ids = {r.payload["decision_event"]["decision_id"]["owner_id"]
                            for r in records if r.event_type == "DECISION_FACT"}
            self.assertEqual(native_ids, decision_ids)
            report = {"status": "PASS", "synthetic_only": True, "provider_contact": False,
                "family_counts": family_counts, "manifest_phases": phases,
                "total_v2_publications": len(records), "total_source_checkpoints": len(self.producer._records()),
                "duplicate_publications": 0, "engine_outcome_publications": 0,
                "maximum_tick_seconds": max(durations), "tick_seconds": durations, "chronology": samples,
                "queue_capacity": 256, "writer": "DedicatedEvidenceWriter/AuthenticatedEvidenceWriterClient",
                "installed_or_unbounded_performance_claim": False}
            report["native_record_to_decision_reconciliation"] = {
                "native_ids": sorted(native_ids), "v2_decision_ids": sorted(decision_ids), "status": "PASS"}
            return report
        finally:
            runtime.shutdown(self.now)

    def test_synthetic_continuous_day(self):
        self.run_day()


if __name__ == "__main__":
    unittest.main()
