"""Synthetic recovery attacks against native classes, never a provider or broker."""
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from momentum_hunter import continuous_operational_admission as admission
from momentum_hunter import continuous_runtime as runtime
from momentum_hunter import modern_operational as modern
from momentum_hunter import modern_shadow_fill_custody as custody
from momentum_hunter import shadow_trading as shadow
from tests import test_modern_operational_handoff as handoff
from tests import test_modern_runtime_checkpoint as checkpoints
from tests import test_continuous_operational_admission as admissions
from tests import test_continuous_runtime as runtime_fixtures
from tests import test_continuous_natural_setup as market_fixtures


def publish_component(publication, name, body, when):
    previous = publication.current()
    snapshot = modern.freeze_snapshot(publication.epoch, kind=publication.kind,
        components=((name, modern.canonical_bytes(body)),),
        sequence=json.loads(previous.manifest_bytes)["sequence"] + 1 if previous else 1,
        predecessor=previous.snapshot_id if previous else None,
        created_at=when, known_at=when, decision_cutoff=when)
    publication.publish(snapshot, expected_previous=previous.snapshot_id if previous else None)
    return snapshot


def checkpoint_body(payload):
    body = deepcopy(payload)
    body.pop("checkpoint_fingerprint", None)
    body["checkpoint_fingerprint"] = runtime._fingerprint("continuous-runtime-checkpoint-v1", body)
    return body


def restore(native, instance):
    native.clock.advance(31)
    return runtime.ContinuousOpportunityRuntime.restore(config=native.config,
        runtime_instance_id=instance, now=native.clock.now(), discovery_source=native.discovery,
        market_data_source=native.market, event_source=native.events,
        composition_source=native.composer, denominator_source=native.denominator,
        writer=native.writer, lease_registry=native.leases, checkpoint_store=native.store)


class FillRecoveryIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.f = handoff.ModernOperationalHandoffTests(
            "test_native_fakebroker_first_fill_persists_exact_upstream_position_and_opened_at")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.epoch = self.f.epoch
        self.store = shadow.ModernShadowPositionStore(self.epoch)

    def initial(self, size=1):
        _, fill, _ = self.f.fill(quote=replace(self.f.quote, available_size=size))
        snapshot = self.store.save(fill, expected_previous=None, recorded_at=self.f.quote.timestamp)
        return fill, snapshot

    def next_fill(self, fill):
        return self.f.fill(order=fill.order, prior=fill,
            quote=replace(self.f.quote, timestamp="2026-08-17T11:21:30-04:00"))

    def contradict(self, fill, quantity):
        return replace(fill, order=replace(fill.order, filled_quantity=quantity,
            remaining_quantity=2-quantity, status="filled" if quantity == 2 else "partially_filled"),
            position=replace(fill.position, quantity=quantity))

    def persisted_attack(self, mutate, *, size=1):
        fill, _ = self.initial(size)
        body = json.loads(self.store.publication.current().component("positions"))
        mutate(body["positions"][0])
        publish_component(self.store.publication, "positions", body, self.f.quote.timestamp)
        before = self.store.publication.pointer.read_bytes()
        with patch.object(self.f.broker, "_fill_entry", side_effect=AssertionError("new fill executed")) as primitive:
            with self.assertRaises(ValueError):
                recovered = shadow.ModernShadowPositionStore(self.epoch).load()[0][0]
                self.next_fill(recovered)
            primitive.assert_not_called()
        self.assertEqual(before, self.store.publication.pointer.read_bytes())
        self.assertEqual(custody.receipt_history(self.epoch, fill.order.order_id)[-1][1]["cumulativeFilledQuantity"], size)

    def test_p1_exact_full_history_underreported_to_one_rejects_before_new_fill(self):
        def mutate(row):
            row["order"].update(filled_quantity=1, remaining_quantity=1, status="partially_filled")
            row["position"]["quantity"] = 1
        self.persisted_attack(mutate, size=2)

    def test_partial_history_underreported_to_zero_rejects(self):
        def mutate(row):
            row["order"].update(filled_quantity=0, remaining_quantity=2)
            row["position"]["quantity"] = 0
        self.persisted_attack(mutate)

    def test_full_history_underreported_to_zero_rejects(self):
        def mutate(row):
            row["order"].update(filled_quantity=0, remaining_quantity=2, status="partially_filled")
            row["position"]["quantity"] = 0
        self.persisted_attack(mutate, size=2)

    def test_partial_history_overreported_to_two_rejects(self):
        def mutate(row):
            row["order"].update(filled_quantity=2, remaining_quantity=0, status="filled")
            row["position"]["quantity"] = 2
        self.persisted_attack(mutate)

    def test_contradictory_live_aggregate_cannot_save_or_reenter(self):
        fill, previous = self.initial(2)
        for quantity in (0, 1, 3):
            altered = self.contradict(fill, quantity)
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValueError):
                    self.store.save(altered, expected_previous=previous, recorded_at=self.f.quote.timestamp)
                with patch.object(self.f.broker, "_fill_entry", side_effect=AssertionError("new fill")) as primitive:
                    with self.assertRaises(ValueError):
                        self.next_fill(altered)
                    primitive.assert_not_called()
        self.assertEqual(self.store.load()[0], (fill,))

    def test_partial_restart_twice_completion_preserves_exact_first_fill_and_ids(self):
        fill, previous = self.initial()
        for _ in range(2):
            recovered, current = shadow.ModernShadowPositionStore(self.epoch).load()
            self.assertEqual((recovered, current), ((fill,), previous))
        order, complete, _ = self.next_fill(recovered[0])
        self.assertEqual((order.filled_quantity, order.remaining_quantity), (2, 0))
        self.assertEqual((complete.identity, complete.first_fill, complete.position.position_id,
                          complete.position.opened_at, complete.order.order_id),
                         (fill.identity, fill.first_fill, fill.position.position_id,
                          fill.position.opened_at, fill.order.order_id))
        self.store.save(complete, expected_previous=previous, recorded_at=order.last_update_at)
        history = custody.receipt_history(self.epoch, order.order_id)
        self.assertEqual([row[1]["incrementalFilledQuantity"] for row in history], [1, 1])
        self.assertEqual(self.store.load()[0], (complete,))

    def test_fully_filled_restart_has_no_additional_quantity(self):
        fill, previous = self.initial(2)
        restored = self.store.load()[0][0]
        order, extra, _ = self.next_fill(restored)
        self.assertIsNone(extra)
        self.assertEqual((order.filled_quantity, order.remaining_quantity), (2, 0))
        self.assertEqual(len(custody.receipt_history(self.epoch, order.order_id)), 1)
        self.assertEqual(self.store.load(), ((fill,), previous))

    def test_exact_duplicate_fill_observation_and_save_are_idempotent(self):
        fill, previous = self.initial()
        order, duplicate, _ = self.f.fill(order=fill.order, prior=fill)
        self.assertEqual((order, duplicate), (fill.order, fill))
        self.assertEqual(len(custody.receipt_history(self.epoch, order.order_id)), 1)
        self.assertEqual(self.store.save(duplicate, expected_previous=previous,
            recorded_at=self.f.quote.timestamp), previous)

    def test_changed_observation_at_same_instant_cannot_masquerade_as_duplicate(self):
        fill, _ = self.initial()
        with self.assertRaises(ValueError):
            self.f.fill(order=fill.order, prior=fill, quote=replace(self.f.quote, available_size=2))
        self.assertEqual(len(custody.receipt_history(self.epoch, fill.order.order_id)), 1)

    def test_same_receipt_identity_changed_bytes_rejects_without_repair(self):
        fill, _ = self.initial()
        publication = modern.SnapshotPublication(self.epoch, "SHADOW_FILL")
        path = publication.root / (fill.fill_snapshot.snapshot_id + ".json")
        changed = path.read_bytes() + b" "
        path.write_bytes(changed)
        with self.assertRaises(ValueError):
            self.store.load()
        self.assertEqual(path.read_bytes(), changed)

    def test_impossible_history_three_against_two_is_not_normalized(self):
        fill, _ = self.initial(2)
        publication = modern.SnapshotPublication(self.epoch, "SHADOW_FILL")
        body = json.loads(fill.fill_snapshot.component("fill"))
        body.update(priorFillSnapshotId=fill.fill_snapshot.snapshot_id, incrementalFilledQuantity=1,
                    cumulativeFilledQuantity=3, quoteFingerprint="f" * 64)
        body["fillId"] = modern.digest(modern.canonical_bytes({"orderId": fill.order.order_id,
            "quoteFingerprint": body["quoteFingerprint"]}))
        body["order"].update(filled_quantity=3, remaining_quantity=-1, last_update_at="2026-08-17T11:21:30-04:00")
        body["position"]["quantity"] = 3
        publish_component(publication, "fill", body, body["order"]["last_update_at"])
        before = publication.pointer.read_bytes()
        with self.assertRaises(ValueError):
            self.store.load()
        self.assertEqual(publication.pointer.read_bytes(), before)

    def test_published_duplicate_receipt_identity_is_rejected_not_doublecounted(self):
        fill, _ = self.initial()
        publication = modern.SnapshotPublication(self.epoch, "SHADOW_FILL")
        body = json.loads(fill.fill_snapshot.component("fill"))
        body.update(priorFillSnapshotId=fill.fill_snapshot.snapshot_id, cumulativeFilledQuantity=2)
        body["order"].update(filled_quantity=2, remaining_quantity=0)
        body["position"]["quantity"] = 2
        publish_component(publication, "fill", body, self.f.quote.timestamp)
        with self.assertRaises(ValueError):
            self.store.load()

    def test_receipt_ahead_crash_fails_public_restore_until_exact_result_is_saved(self):
        first, previous = self.initial()
        order, complete, _ = self.next_fill(first)
        with self.assertRaises(ValueError):
            self.store.load()
        with self.assertRaises(ValueError):
            self.next_fill(first)
        self.store.save(complete, expected_previous=previous, recorded_at=order.last_update_at)
        self.assertEqual(self.store.load()[0], (complete,))

    def test_old_receipt_replay_cannot_reduce_current_cumulative_truth(self):
        first, previous = self.initial()
        order, complete, _ = self.next_fill(first)
        final = self.store.save(complete, expected_previous=previous, recorded_at=order.last_update_at)
        with self.assertRaises(ValueError):
            self.store.save(first, expected_previous=final, recorded_at=order.last_update_at)
        with self.assertRaises(ValueError):
            self.f.fill()
        self.assertEqual(self.store.load()[0], (complete,))

    def test_rolled_back_fill_pointer_cannot_hide_committed_follow_on_receipt(self):
        first, _ = self.initial()
        publication = modern.SnapshotPublication(self.epoch, "SHADOW_FILL")
        old_pointer = publication.pointer.read_bytes()
        self.next_fill(first)
        publication.pointer.write_bytes(old_pointer)
        with self.assertRaises(ValueError):
            self.store.load()
        with self.assertRaises(ValueError):
            self.next_fill(first)
        self.assertEqual(publication.pointer.read_bytes(), old_pointer)

    def test_restored_order_identity_mutation_rejects(self):
        self.persisted_attack(lambda row: row["order"].update(order_id="foreign-order"))

    def test_restored_position_identity_mutation_rejects(self):
        self.persisted_attack(lambda row: row["position"].update(position_id="foreign-position"))

    def test_restored_opened_at_mutation_rejects(self):
        self.persisted_attack(lambda row: row["position"].update(opened_at="2026-08-17T11:21:21-04:00"))

    def test_native_proposed_overfill_rejects_before_receipt_publication(self):
        # Corrupt only the synthetic fill proposal; the real admission and cap remain intact.
        order, position, reason = self.f.broker._fill_entry(self.f.order, self.f.quote,
            received_at=datetime.fromisoformat(self.f.quote.timestamp), committed_notional=0,
            open_position_count=0, realized_pnl_today=0)
        with patch.object(self.f.broker, "_fill_entry", return_value=(
                replace(order, filled_quantity=3, remaining_quantity=-1), replace(position, quantity=3), reason)):
            with self.assertRaises(ValueError):
                self.f.fill()
        self.assertIsNone(modern.SnapshotPublication(self.epoch, "SHADOW_FILL").current())

    def test_native_economics_and_original_allocation_are_unchanged(self):
        before = self.f.admission.validate(self.epoch)[2:5]
        expected, _, _ = self.f.broker._fill_entry(self.f.order, self.f.quote,
            received_at=datetime.fromisoformat(self.f.quote.timestamp), committed_notional=0,
            open_position_count=0, realized_pnl_today=0)
        order, fill, _ = self.f.fill()
        self.assertEqual(order, expected)
        self.assertEqual(before, self.f.admission.validate(self.epoch)[2:5])
        self.assertEqual(fill.position.stop_price, self.f.plan["stop_price"])
        self.assertEqual(fill.position.target_price, self.f.plan["target_prices"][0])
        self.assertFalse(self.f.paper.adapter.mock_calls)


class CheckpointRecoveryIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.f = checkpoints.ModernRuntimeCheckpointTests("test_current_modern_runtime_checkpoint_and_queue_roundtrip")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.f.start_with_work()
        self.native, self.epoch = self.f.native, self.f.cutover.epoch
        self.payload = self.native.store.load(self.native.config.runtime_identity)

    def reject_field(self, key, value=None, *, missing=False):
        payload = deepcopy(self.payload)
        if missing:
            payload.pop(key)
        else:
            payload[key] = value
        before = self.native.store.publication.pointer.read_bytes()
        with self.assertRaises(ValueError):
            self.native.store.save(self.native.config.runtime_identity, payload)
        self.assertEqual(before, self.native.store.publication.pointer.read_bytes())
        publish_component(self.native.store.publication, "checkpoint", checkpoint_body(payload),
                          self.payload["last_heartbeat_at"])
        rejected = self.native.store.publication.pointer.read_bytes()
        with self.assertRaises(ValueError):
            self.native.store.load(self.native.config.runtime_identity)
        with self.assertRaises(ValueError):
            restore(self.native, "new-process")
        self.assertEqual(rejected, self.native.store.publication.pointer.read_bytes())

    def test_foreign_runtime_save_load_restore_reject(self):
        self.reject_field("runtime_identity", "foreign-runtime")

    def test_foreign_profile_save_load_restore_reject(self):
        self.reject_field("runtime_profile", "FOREIGN_PROFILE")

    def test_foreign_runtime_and_profile_reject(self):
        self.payload["runtime_profile"] = "FOREIGN_PROFILE"
        self.reject_field("runtime_identity", "foreign-runtime")

    def test_missing_runtime_reject(self):
        self.reject_field("runtime_identity", missing=True)

    def test_missing_profile_reject(self):
        self.reject_field("runtime_profile", missing=True)

    def test_wrong_epoch_reject(self):
        self.reject_field("operationalEpochId", "f" * 64)

    def test_missing_epoch_reject(self):
        self.reject_field("operationalEpochId", missing=True)

    def test_wrong_configuration_reject(self):
        self.reject_field("config_fingerprint", "f" * 64)

    def test_wrong_source_binding_reject(self):
        self.reject_field("sourceIdentity", "f" * 64)

    def test_legacy_checkpoint_schema_reject(self):
        self.reject_field("checkpoint_schema_version", 2)

    def test_foreign_runtime_contract_reject(self):
        self.reject_field("contract_version", 999)

    def test_store_creation_requires_approved_configuration(self):
        for config in (None, replace(self.native.config, runtime_identity="foreign-runtime")):
            with self.subTest(config=config), self.assertRaises(ValueError):
                runtime.RuntimeCheckpointStore(Path(self.epoch.root) / "runtime",
                    operational_epoch=self.epoch, runtime_config=config)

    def test_checkpoint_cannot_be_selected_by_foreign_runtime_name(self):
        with self.assertRaises(ValueError):
            self.native.store.load("another-runtime")
        with self.assertRaises(ValueError):
            self.native.store.save("another-runtime", self.payload)

    def test_exact_checkpoint_restarts_with_new_process_not_new_logical_runtime(self):
        restored = restore(self.native, "different-process-instance")
        self.assertEqual(restored.runtime_instance_id, "different-process-instance")
        self.assertEqual(restored.config.runtime_identity, self.native.config.runtime_identity)
        self.assertEqual(restored.started_at, self.native.runtime.started_at)
        self.assertEqual(restored._queues[runtime.DISCOVERY_QUEUE].snapshot(),
                         self.native.runtime._queues[runtime.DISCOVERY_QUEUE].snapshot())

    def test_wrong_snapshot_identity_and_bytes_reject(self):
        publication = self.native.store.publication
        current = publication.current()
        with self.assertRaises(ValueError):
            modern.snapshot_from_bytes(current.to_bytes(), self.epoch, kind="CHECKPOINT", expected_id="f" * 64)
        path = publication.root / (current.snapshot_id + ".json")
        changed = path.read_bytes() + b" "
        path.write_bytes(changed)
        with self.assertRaises(ValueError):
            restore(self.native, "after-tamper")
        self.assertEqual(path.read_bytes(), changed)

    def foreign_work(self, field):
        item = deepcopy(self.payload["queues"][runtime.DISCOVERY_QUEUE][0])
        snapshot = modern.snapshot_from_bytes(item["operational_snapshot_json"].encode("ascii"),
            self.epoch, kind="QUEUED_DECISION", expected_id=item["operational_snapshot_id"])
        binding = json.loads(snapshot.component("runtime"))
        binding[field] = "foreign"
        manifest = json.loads(snapshot.manifest_bytes)
        altered = modern.freeze_snapshot(self.epoch, kind="QUEUED_DECISION",
            components=(("work", snapshot.component("work")), ("runtime", modern.canonical_bytes(binding))),
            sequence=manifest["sequence"], predecessor=manifest["predecessorSnapshotId"],
            created_at=manifest["createdAt"], known_at=manifest["knownAt"], decision_cutoff=manifest["decisionCutoff"])
        item.update(operational_snapshot_id=altered.snapshot_id,
                    operational_snapshot_json=altered.to_bytes().decode("ascii"))
        return item

    def test_foreign_queue_runtime_and_profile_block_all_save_and_restore_locations(self):
        for field in ("runtimeIdentity", "runtimeProfile"):
            item = self.foreign_work(field)
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    runtime._restore_work(item, self.epoch, self.native.config.runtime_identity)
                with self.assertRaises(ValueError):
                    self.native.runtime._enqueue(runtime.DISCOVERY_QUEUE, runtime.ModernQueuedWork(**item),
                                                  self.native.clock.now())
                for location in ("queues", "deferred_readiness", "provider_bound_events", "in_flight"):
                    body = deepcopy(self.payload)
                    body[location] = {runtime.DISCOVERY_QUEUE: [item]} if location == "queues" else (
                        item if location == "in_flight" else [item])
                    with self.subTest(location=location), self.assertRaises(ValueError):
                        self.native.store.save(self.native.config.runtime_identity, body)

    def test_current_queue_core_identity_remains_unchanged(self):
        item = self.payload["queues"][runtime.DISCOVERY_QUEUE][0]
        work = runtime._restore_work(item, self.epoch, self.native.config.runtime_identity)
        core = {k: v for k, v in asdict(work).items() if k not in {
            "operational_epoch_id", "operational_snapshot_id", "operational_snapshot_json"}}
        fingerprint = core.pop("fingerprint")
        self.assertEqual(fingerprint, runtime._fingerprint("continuous-runtime-work-v1", core))
        self.assertEqual(work.fingerprint, item["fingerprint"])


class PaperFirstFillCapTests(unittest.TestCase):
    def check_consumer(self, consumer):
        f = admissions.ContinuousAdmissionTests("test_paper_first_fill_exact_position_open_time_and_restart")
        f.setUp()
        self.addCleanup(f.doCleanups)
        accepted = f.admit()
        intent = admission.prepare_continuous_intent(accepted, f.epoch, consumer=consumer, recorded_at=f.when)
        first = {**json.loads(f.f.fill), "localOrderId": json.loads(intent.snapshot.component("intent"))["localOrderId"]}
        for quantity in (3, 0, -1, True, "1"):
            with self.subTest(consumer=consumer, quantity=quantity), self.assertRaises(ValueError):
                admission.bind_continuous_first_fill(intent, f.epoch, consumer=consumer,
                    first_fill=modern.canonical_bytes({**first, "filledQuantity": quantity}),
                    recorded_at=first["filledAt"])
        self.assertFalse(f.paper.adapter.mock_calls)
        bound = admission.bind_continuous_first_fill(intent, f.epoch, consumer=consumer,
            first_fill=modern.canonical_bytes({**first, "filledQuantity": 2}), recorded_at=first["filledAt"])
        bound.validate(f.epoch, consumer=consumer)

    def test_paper_first_fill_cap_without_execution(self):
        self.check_consumer("PAPER")

    def test_shadow_lineage_first_fill_cap_without_execution(self):
        self.check_consumer("SHADOW")


class CrossDefectRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mh-modern-cross-")
        self.addCleanup(temporary.cleanup)
        self.native = runtime_fixtures.RuntimeFixture(Path(temporary.name))
        self.f = handoff.ModernOperationalHandoffTests(
            "test_native_fakebroker_first_fill_persists_exact_upstream_position_and_opened_at")
        # Both real recovery owners share one independently selected synthetic epoch/configuration.
        with patch.object(market_fixtures, "CONFIGURATION", self.native.config.fingerprint):
            self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.epoch = self.f.epoch
        self.native.store = runtime.RuntimeCheckpointStore(Path(self.epoch.root) / "runtime",
            operational_epoch=self.epoch, runtime_config=self.native.config)
        self.native.runtime = self.native.new_runtime("cross-original")
        self.native.runtime.start(self.native.clock.now())
        self.native.runtime.request_discovery(self.native.clock.now())
        self.native.runtime._checkpoint(self.native.clock.now())
        self.store = shadow.ModernShadowPositionStore(self.epoch)

    def recover(self):
        # The runtime is nontransmitting and has no position-resume orchestration.
        # Compose the two native read gates; do not invent a production resume API.
        checkpoint = self.native.store.load(self.native.config.runtime_identity)
        fills, snapshot = self.store.load()
        return checkpoint, fills, snapshot

    def scenario(self, *, quantity=1, aggregate=None, runtime_name=None, profile=None):
        _, fill, _ = self.f.fill(quote=replace(self.f.quote, available_size=quantity))
        self.store.save(fill, expected_previous=None, recorded_at=self.f.quote.timestamp)
        if aggregate is not None:
            body = json.loads(self.store.publication.current().component("positions"))
            body["positions"][0]["order"].update(filled_quantity=aggregate, remaining_quantity=2-aggregate,
                status="filled" if aggregate == 2 else "partially_filled")
            body["positions"][0]["position"]["quantity"] = aggregate
            publish_component(self.store.publication, "positions", body, self.f.quote.timestamp)
        payload = self.native.store.load(self.native.config.runtime_identity)
        if runtime_name is not None or profile is not None:
            payload.update(runtime_identity=runtime_name or payload["runtime_identity"],
                           runtime_profile=profile or payload["runtime_profile"])
            publish_component(self.native.store.publication, "checkpoint", checkpoint_body(payload),
                              payload["last_heartbeat_at"])
        return fill

    def test_foreign_runtime_and_underreported_fill_fail(self):
        self.scenario(quantity=2, aggregate=1, runtime_name="foreign")
        with self.assertRaises(ValueError):
            self.recover()

    def test_exact_runtime_and_underreported_fill_fail(self):
        self.scenario(quantity=2, aggregate=1)
        with self.assertRaises(ValueError):
            self.recover()

    def test_valid_fill_with_foreign_profile_fails(self):
        self.scenario(profile="foreign")
        with self.assertRaises(ValueError):
            self.recover()

    def test_fully_filled_foreign_runtime_has_no_recovery_authority(self):
        self.scenario(quantity=2, runtime_name="foreign")
        with self.assertRaises(ValueError):
            self.recover()

    def test_partial_fill_exact_checkpoint_and_strategy_replay_keep_custody(self):
        first = self.scenario()
        checkpoint, fills, previous = self.recover()
        self.assertEqual(fills, (first,))
        restored = restore(self.native, "cross-restart")
        self.assertEqual(restored.started_at.isoformat(), checkpoint["started_at"])
        strategy = modern.SnapshotPublication(self.epoch, "STRATEGY_DECISION").current()
        decision, _, risk, request, allocation, _ = self.f.admission.validate(self.epoch)
        replay = admission.publish_strategy_result(decision=decision, epoch=self.epoch, risk=risk,
            request=request, allocation=allocation, recorded_at=risk.decision_at)
        self.assertEqual(replay, strategy)
        self.assertEqual(admission.admit_continuous(epoch=self.epoch, strategy_snapshot=replay,
            admitted_at=risk.decision_at), self.f.admission)
        order, complete, _ = self.f.fill(order=first.order, prior=first,
            quote=replace(self.f.quote, timestamp="2026-08-17T11:21:30-04:00"))
        self.store.save(complete, expected_previous=previous, recorded_at=order.last_update_at)
        self.assertEqual((order.order_id, order.filled_quantity, order.remaining_quantity),
                         (first.order.order_id, 2, 0))
        self.assertEqual(complete.first_fill, first.first_fill)

    def test_exact_runtime_mutated_snapshot_fails_with_valid_fill(self):
        self.scenario()
        publication = self.native.store.publication
        current = publication.current()
        path = publication.root / (current.snapshot_id + ".json")
        changed = path.read_bytes() + b" "
        path.write_bytes(changed)
        with self.assertRaises(ValueError):
            self.recover()
        self.assertEqual(path.read_bytes(), changed)


if __name__ == "__main__":
    unittest.main()
