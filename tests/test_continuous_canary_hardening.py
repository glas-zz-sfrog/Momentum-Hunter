from __future__ import annotations

import json
import secrets
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from momentum_hunter.broad_discovery import (
    DiscoveryQueryIdentity,
    DiscoverySourceRow,
    build_discovery_snapshot,
)
from momentum_hunter.continuous_live_qualification import (
    LiveDiscoverySource,
    LiveMarketDataSource,
    QualificationState,
)
from momentum_hunter.continuous_production import (
    ProductionRemoteWriter,
    _fingerprint,
    deployment_configuration_fingerprint,
)
from momentum_hunter.continuous_runtime import (
    EVIDENCE_REJECTED_PERMANENT,
    FAILED_FORWARD_PROGRESS,
    MEMBER_PROMOTED,
    PAYLOAD_TOO_LARGE,
    PIPELINE_STALLED,
    PREMARKET_DEFERRED,
    PROCESS_ALIVE,
    REGULAR_SESSION_ROLLOVER,
    SCHEMA_INVALID,
    WRITER_ACCEPTED,
    WRITER_UNAVAILABLE,
    ContinuousOpportunityRuntime,
    LogicalRuntimeLeaseRegistry,
    ReadinessResult,
    WriterPreflight,
    build_evidence_write_intent,
)
from momentum_hunter.event_runtime_writer_ipc import MAX_PAYLOAD_BYTES
from momentum_hunter.models import Candidate, INSTITUTIONAL_MOMENTUM
from tests.test_continuous_runtime import RuntimeFixture, fp


CENTRAL = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")
SOURCE_CONTRACT = "a" * 64
SEMANTIC = "b" * 64


def discovery_snapshot(
    observed: datetime, *, count: int, generation: int = 0
):
    rows = []
    for ordinal in range(1, count + 1):
        symbol = "SKHY" if count == 1 else f"S{ordinal:03d}"
        rows.append(
            DiscoverySourceRow.from_mapping(
                source_row_ordinal=ordinal,
                source_row_identity=(
                    f"{symbol}-{generation}-{ordinal}-{observed.isoformat()}"
                ),
                source_values={
                    "Ticker": symbol,
                    "No.": str(ordinal),
                    "Change %": "5.0%",
                    "Price": f"{20 + ordinal / 10:.2f}",
                    "Volume": str((ordinal + 3) * 1_000_000),
                    "Relative Volume": "2.0",
                },
                candidate=Candidate(
                    ticker=symbol,
                    company=f"{symbol} Incorporated",
                    price=20 + ordinal / 10,
                    percent_change=5.0,
                    volume=(ordinal + 3) * 1_000_000,
                    relative_volume=2.0,
                    market_cap=10_000_000_000,
                    sector="Technology",
                    industry="Semiconductors",
                ),
            )
        )
    return build_discovery_snapshot(
        source="finviz",
        source_version="synthetic-production-shaped-finviz-v1",
        requested_at=observed - timedelta(seconds=2),
        received_at=observed - timedelta(seconds=1),
        evaluated_at=observed,
        query_identity=DiscoveryQueryIdentity.from_criteria(
            INSTITUTIONAL_MOMENTUM,
            source_query="synthetic://production-shaped-bounded-discovery",
            sort_order="-volume",
        ),
        source_contract_fingerprint=SOURCE_CONTRACT,
        semantic_plausibility_fingerprint=SEMANTIC,
        source_rows=rows,
    )


class FixedProvider:
    def __init__(self) -> None:
        self.current = None

    def discover_paginated(self, *args, **kwargs):
        if self.current is None:
            raise AssertionError("Synthetic provider snapshot was not selected.")
        return self.current


class DeferredThenReadyMarket:
    def __init__(self) -> None:
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        deferred = request.trigger != REGULAR_SESSION_ROLLOVER
        return ReadinessResult(
            request_id=request.request_id,
            symbol=request.symbol,
            status=PREMARKET_DEFERRED if deferred else "READY",
            fingerprint=fp((request.request_id, request.requested_at, deferred)),
            ready=not deferred,
            deferred=deferred,
        )


class RecordSelectiveWriter:
    def __init__(
        self,
        rejected_record: str | None = None,
        legacy_rejected_record: str | None = None,
    ) -> None:
        self.rejected_record = rejected_record
        self.legacy_rejected_record = legacy_rejected_record
        self.intents = []
        self.mode = WRITER_ACCEPTED

    def preflight_intent(self, intent):
        payload_bytes = len((intent.payload_json or "").encode("utf-8"))
        rejected = intent.record_identity == self.rejected_record
        return WriterPreflight(
            accepted=not rejected,
            payload_bytes=payload_bytes,
            encoded_envelope_bytes=(MAX_PAYLOAD_BYTES + 1 if rejected else payload_bytes),
            protocol_ceiling_bytes=MAX_PAYLOAD_BYTES,
            failure_class=PAYLOAD_TOO_LARGE if rejected else None,
        )

    def write_intent(self, intent):
        if self.mode == WRITER_UNAVAILABLE:
            return WRITER_UNAVAILABLE
        self.intents.append(intent)
        return WRITER_ACCEPTED

    def preflight_legacy_intent(self, intent):
        rejected = intent.record_identity == self.legacy_rejected_record
        payload_bytes = len((intent.payload_json or "").encode("utf-8"))
        return WriterPreflight(
            accepted=not rejected,
            payload_bytes=payload_bytes,
            encoded_envelope_bytes=(MAX_PAYLOAD_BYTES + 1 if rejected else payload_bytes),
            protocol_ceiling_bytes=MAX_PAYLOAD_BYTES,
            failure_class=PAYLOAD_TOO_LARGE if rejected else None,
        )


class ContinuousCanaryHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def _production_writer(self) -> ProductionRemoteWriter:
        config: dict[str, object] = {
            "activationProfile": "research-only-continuous-deployment-v1",
            "mode": "RESEARCH_ONLY",
            "orderCapability": "UNAVAILABLE",
            "runtimeIdentity": "production-continuous-runtime-v1",
            "runtimeBuildHash": "a" * 64,
            "evidenceProgramId": "continuous-opportunity-production",
            "evidenceRoot": str(self.root / "evidence"),
            "runtimeStateRoot": str(self.root / "runtime"),
            "ipcKeyPath": str(self.root / "ipc.key"),
            "ipcHost": "127.0.0.1",
            "ipcPort": 49281,
            "expectedAccountEnding": "2573",
            "broadDiscoverySeconds": 300,
        }
        Path(str(config["ipcKeyPath"])).write_bytes(secrets.token_bytes(32))
        config["configurationFingerprint"] = deployment_configuration_fingerprint(
            config
        )
        return ProductionRemoteWriter(
            config, source_identity="production-continuous-runtime-hardening-test"
        )

    def test_live_premarket_readiness_is_deferred_without_schwab_fetch(self) -> None:
        observed = datetime(2026, 8, 19, 7, 5, tzinfo=EASTERN)
        state = QualificationState(root=self.root / "premarket", launch_at=observed)
        discovery = LiveDiscoverySource(state)
        provider = FixedProvider()
        provider.current = discovery_snapshot(observed, count=1)
        discovery.provider = provider
        with patch(
            "momentum_hunter.continuous_live_qualification._aware_now",
            return_value=observed,
        ):
            pulse = discovery.discover(
                type("Request", (), {
                    "request_id": "premarket-request",
                    "requested_at": observed.isoformat(),
                    "reason": "CADENCE",
                })()
            )
            request = type("Readiness", (), {
                "request_id": "readiness-request",
                "symbol": "SKHY",
                "trigger": MEMBER_PROMOTED,
                "requested_at": observed.isoformat(),
                "source_fingerprint": pulse.fingerprint,
            })()
            result = LiveMarketDataSource(
                state, expected_account_ending="2573"
            ).evaluate(request)
        self.assertEqual(PREMARKET_DEFERRED, result.status)
        self.assertTrue(result.deferred)
        self.assertFalse(result.ready)
        self.assertIsNone(result.failure_reason)
        self.assertEqual(0, state.metrics.schwab_refreshes)
        self.assertEqual(1, state.metrics.readiness_deferred)

    def test_premarket_candidate_rolls_prospectively_without_rediscovery(self) -> None:
        fixture = RuntimeFixture(self.root / "rollover")
        fixture.clock.current = datetime(2026, 8, 19, 6, 5, tzinfo=CENTRAL)
        fixture.discovery.symbols = ("SKHY",)
        market = DeferredThenReadyMarket()
        fixture.runtime.market_data_source = market
        fixture.runtime.start(fixture.clock.now())
        fixture.runtime.tick(
            fixture.clock.now(), discovery_cadence_seconds=600
        )
        self.assertEqual(("SKHY",), fixture.runtime.deferred_readiness_symbols)
        self.assertEqual(0, fixture.runtime.health(fixture.clock.now()).readiness_failures)
        self.assertEqual([], fixture.composer.calls)
        premarket_known_at = market.requests[-1].requested_at
        fixture.runtime.next_discovery_at = fixture.clock.now() + timedelta(hours=4)
        fixture.clock.advance(145 * 60)
        self.assertEqual(1, fixture.runtime.release_deferred_readiness(fixture.clock.now()))
        fixture.runtime.tick(
            fixture.clock.now(), discovery_cadence_seconds=300
        )
        self.assertEqual(1, fixture.discovery.calls)
        self.assertEqual(REGULAR_SESSION_ROLLOVER, market.requests[-1].trigger)
        self.assertGreater(market.requests[-1].requested_at, premarket_known_at)
        self.assertIn("SKHY", fixture.composer.calls)
        self.assertEqual(0, fixture.runtime.health(fixture.clock.now()).readiness_failures)

    def test_long_premarket_soak_defers_without_poison_or_stall(self) -> None:
        fixture = RuntimeFixture(self.root / "premarket-soak")
        fixture.clock.current = datetime(2026, 8, 19, 6, 5, tzinfo=CENTRAL)
        fixture.discovery.symbols = ("SKHY",)
        fixture.runtime.market_data_source = DeferredThenReadyMarket()
        fixture.runtime.start(fixture.clock.now())
        for _ in range(15):
            health = fixture.runtime.tick(
                fixture.clock.now(), discovery_cadence_seconds=600
            )
            self.assertNotIn(FAILED_FORWARD_PROGRESS, health.health_flags)
            fixture.clock.advance(600)
        self.assertEqual(0, health.readiness_failures)
        self.assertGreaterEqual(health.readiness_deferred, 15)
        self.assertEqual(("SKHY",), fixture.runtime.deferred_readiness_symbols)
        self.assertEqual(0, len(fixture.runtime.evidence_rejections))

    def test_empty_premarket_does_not_block_regular_midday_discovery(self) -> None:
        fixture = RuntimeFixture(self.root / "empty-premarket")
        fixture.clock.current = datetime(2026, 8, 19, 6, 5, tzinfo=CENTRAL)
        fixture.discovery.symbols = ()
        fixture.runtime.start(fixture.clock.now())
        fixture.runtime.tick(fixture.clock.now(), discovery_cadence_seconds=600)
        fixture.discovery.symbols = ("MIDDAY",)
        fixture.clock.current = datetime(2026, 8, 19, 10, 5, tzinfo=CENTRAL)
        fixture.runtime.next_discovery_at = fixture.clock.now()
        health = fixture.runtime.tick(
            fixture.clock.now(), discovery_cadence_seconds=300
        )
        self.assertIn("MIDDAY", fixture.composer.calls)
        self.assertGreater(health.composition_cycles, 0)
        self.assertNotIn(FAILED_FORWARD_PROGRESS, health.health_flags)

    def test_one_hundred_production_shaped_discovery_records_remain_bounded(self) -> None:
        state = QualificationState(
            root=self.root / "soak",
            launch_at=datetime(2026, 8, 19, 9, 30, tzinfo=EASTERN),
        )
        discovery = LiveDiscoverySource(state)
        provider = FixedProvider()
        discovery.provider = provider
        writer = self._production_writer()
        encoded_sizes = []
        payload_sizes = []
        predecessor = None
        prior_universe_fingerprint = None
        for cycle in range(1, 101):
            observed = datetime(2026, 8, 19, 9, 30, tzinfo=EASTERN) + timedelta(
                minutes=cycle - 1
            )
            provider.current = discovery_snapshot(
                observed, count=30, generation=cycle
            )
            with patch(
                "momentum_hunter.continuous_live_qualification._aware_now",
                return_value=observed,
            ):
                pulse = discovery.discover(
                    type("Request", (), {
                        "request_id": f"cycle-{cycle}",
                        "requested_at": observed.isoformat(),
                        "reason": "CADENCE",
                    })()
                )
            payload = json.loads(pulse.evidence_payload_json or "{}")
            universe_payload = payload["universe"]
            self.assertNotIn("transitions", universe_payload["state"])
            self.assertNotIn("snapshot_receipts", universe_payload["state"])
            self.assertNotIn("failure_receipts", universe_payload["state"])
            if prior_universe_fingerprint is not None:
                self.assertEqual(
                    prior_universe_fingerprint,
                    universe_payload["predecessor"]["universeFingerprint"],
                )
            prior_universe_fingerprint = universe_payload["state"]["fingerprint"]
            payload_fingerprint = _fingerprint(
                "continuous-evidence-payload-v1", payload
            )
            intent = build_evidence_write_intent(
                runtime_instance_id=writer.source_identity,
                sequence=cycle,
                evidence_type="DISCOVERY_CYCLE",
                record_identity=pulse.pulse_id,
                record_fingerprint=pulse.fingerprint,
                predecessor_identity=predecessor,
                requested_at=observed.isoformat(),
                payload_fingerprint=payload_fingerprint,
                payload=payload,
            )
            preflight = writer.preflight_intent(intent)
            self.assertTrue(preflight.accepted)
            outer = writer._writer_payload(intent)
            self.assertNotIn("payload_json", outer["intent"])
            self.assertEqual(payload, outer["payload"])
            encoded_sizes.append(preflight.encoded_envelope_bytes)
            payload_sizes.append(preflight.payload_bytes)
            predecessor = intent.intent_id

        stable_sizes = encoded_sizes[9:]
        self.assertLess(max(stable_sizes), MAX_PAYLOAD_BYTES * 0.70)
        self.assertLess(max(stable_sizes) - min(stable_sizes), 12_000)
        self.assertLess(encoded_sizes[-1], encoded_sizes[49] + 12_000)
        self.assertEqual(100, len(encoded_sizes))
        self.assertGreater(min(payload_sizes), 0)

    def test_permanent_poison_is_terminal_and_later_record_advances(self) -> None:
        fixture = RuntimeFixture(self.root / "poison")
        writer = RecordSelectiveWriter(rejected_record="record-b")
        fixture.runtime.writer = writer
        fixture.runtime.start(fixture.clock.now())
        fixture.runtime.next_discovery_at = fixture.clock.now() + timedelta(hours=1)
        fixture.runtime.next_housekeeping_at = fixture.clock.now() + timedelta(hours=1)

        def emit(name: str, body: str):
            return fixture.runtime._emit_intent(
                evidence_type="SYSTEM_FAILURE",
                record_identity=f"record-{name.lower()}",
                record_fingerprint=fp(f"record-{name}"),
                payload_fingerprint=fp(f"payload-{name}"),
                payload={"payloadType": "SYSTEM_FAILURE", "body": body},
                now=fixture.clock.now(),
            )

        emit("A", "valid")
        fixture.runtime.tick(fixture.clock.now())
        rejected_at = fixture.clock.now().isoformat()
        self.assertEqual(EVIDENCE_REJECTED_PERMANENT, emit("B", "x" * 600_000))
        fixture.runtime.tick(fixture.clock.now())
        emit("C", "valid")
        fixture.runtime.tick(fixture.clock.now())

        identities = [item.record_identity for item in writer.intents]
        self.assertIn("record-a", identities)
        self.assertNotIn("record-b", identities)
        self.assertIn("record-c", identities)
        self.assertTrue(any(item.startswith("evidence-rejection-") for item in identities))
        self.assertEqual(1, len(fixture.runtime.evidence_rejections))
        self.assertEqual(rejected_at, fixture.runtime.evidence_rejections[0].known_at)
        self.assertEqual(0, dict(fixture.runtime.health(fixture.clock.now()).queue_depths)["evidence"])

    def test_production_preflight_classifies_size_and_schema_before_queueing(self) -> None:
        writer = self._production_writer()
        requested_at = datetime(2026, 8, 19, 10, 0, tzinfo=EASTERN).isoformat()

        def intent(evidence_type: str, payload: dict[str, object]):
            payload_fingerprint = _fingerprint(
                "continuous-evidence-payload-v1", payload
            )
            return build_evidence_write_intent(
                runtime_instance_id=writer.source_identity,
                sequence=1,
                evidence_type=evidence_type,
                record_identity="preflight-record",
                record_fingerprint="c" * 64,
                predecessor_identity=None,
                requested_at=requested_at,
                payload_fingerprint=payload_fingerprint,
                payload=payload,
            )

        accepted = writer.preflight_intent(
            intent("DISCOVERY_CYCLE", {"payloadType": "DISCOVERY_CYCLE"})
        )
        self.assertTrue(accepted.accepted)
        oversized = writer.preflight_intent(
            intent(
                "DISCOVERY_CYCLE",
                {"payloadType": "DISCOVERY_CYCLE", "body": "x" * 600_000},
            )
        )
        self.assertFalse(oversized.accepted)
        self.assertEqual(PAYLOAD_TOO_LARGE, oversized.failure_class)
        self.assertGreater(oversized.encoded_envelope_bytes, MAX_PAYLOAD_BYTES)
        unsupported = writer.preflight_intent(
            intent("NOT_ALLOWLISTED", {"payloadType": "NOT_ALLOWLISTED"})
        )
        self.assertFalse(unsupported.accepted)
        self.assertEqual(SCHEMA_INVALID, unsupported.failure_class)
        historical_shape = intent(
            "DISCOVERY_CYCLE",
            {"payloadType": "DISCOVERY_CYCLE", "body": "x" * 300_000},
        )
        self.assertTrue(writer.preflight_intent(historical_shape).accepted)
        legacy = writer.preflight_legacy_intent(historical_shape)
        self.assertFalse(legacy.accepted)
        self.assertEqual(PAYLOAD_TOO_LARGE, legacy.failure_class)

    def test_writer_stall_reports_pipeline_failure_while_process_is_alive(self) -> None:
        fixture = RuntimeFixture(self.root / "watchdog")
        writer = RecordSelectiveWriter()
        writer.mode = WRITER_UNAVAILABLE
        fixture.runtime.writer = writer
        fixture.runtime.start(fixture.clock.now())
        fixture.runtime.submit_event(
            fixture.event("AAA"), fixture.clock.now()
        )
        fixture.runtime.tick(fixture.clock.now())
        fixture.clock.advance(631)
        health = fixture.runtime.tick(fixture.clock.now())
        self.assertIn(PROCESS_ALIVE, health.health_flags)
        self.assertIn(FAILED_FORWARD_PROGRESS, health.health_flags)
        self.assertEqual(PIPELINE_STALLED, health.pipeline_state)
        self.assertEqual("WRITER_UNAVAILABLE", health.stall_blocker)
        self.assertGreater(health.queue_head_retry_count, 0)
        self.assertEqual(630, health.stall_threshold_seconds)

    def test_restart_migrates_historical_poison_once_and_does_not_resurrect_it(self) -> None:
        fixture = RuntimeFixture(self.root / "restart-poison")
        old_writer = RecordSelectiveWriter()
        old_writer.mode = WRITER_UNAVAILABLE
        fixture.runtime.writer = old_writer
        fixture.runtime.start(fixture.clock.now())
        fixture.runtime.next_discovery_at = fixture.clock.now() + timedelta(hours=1)
        fixture.runtime.next_housekeeping_at = fixture.clock.now() + timedelta(hours=1)
        fixture.runtime._emit_intent(
            evidence_type="SYSTEM_FAILURE",
            record_identity="record-b",
            record_fingerprint=fp("restart-record-b"),
            payload_fingerprint=fp("restart-payload-b"),
            payload={"payloadType": "SYSTEM_FAILURE", "body": "x" * 600_000},
            now=fixture.clock.now(),
        )
        fixture.runtime.tick(fixture.clock.now())
        old_checkpoint = fixture.store.load(fixture.config.runtime_identity)
        old_checkpoint["checkpoint_schema_version"] = 1
        for key in (
            "evidence_rejections",
            "evidence_retry_counts",
            "evidence_retry_failure_class",
            "evidence_retry_not_before",
        ):
            old_checkpoint.pop(key, None)
        fixture.store.save(fixture.config.runtime_identity, old_checkpoint)

        fixture.clock.advance(31)
        new_writer = RecordSelectiveWriter(legacy_rejected_record="record-b")
        restored = ContinuousOpportunityRuntime.restore(
            config=fixture.config,
            runtime_instance_id="runtime-instance-after-poison",
            now=fixture.clock.now(),
            discovery_source=fixture.discovery,
            market_data_source=fixture.market,
            event_source=fixture.events,
            composition_source=fixture.composer,
            denominator_source=fixture.denominator,
            writer=new_writer,
            lease_registry=fixture.leases,
            checkpoint_store=fixture.store,
        )
        compact = restored.evidence_intents[-1]
        fixture.store.save(fixture.config.runtime_identity, old_checkpoint)
        fixture.clock.advance(60)
        second_writer = RecordSelectiveWriter(legacy_rejected_record="record-b")
        restored_again = ContinuousOpportunityRuntime.restore(
            config=fixture.config,
            runtime_instance_id="runtime-instance-after-second-poison",
            now=fixture.clock.now(),
            discovery_source=fixture.discovery,
            market_data_source=fixture.market,
            event_source=fixture.events,
            composition_source=fixture.composer,
            denominator_source=fixture.denominator,
            writer=second_writer,
            lease_registry=LogicalRuntimeLeaseRegistry(),
            checkpoint_store=fixture.store,
        )
        second_compact = restored_again.evidence_intents[-1]
        self.assertEqual(compact.intent_id, second_compact.intent_id)
        self.assertEqual(compact.record_identity, second_compact.record_identity)
        self.assertEqual(compact.record_fingerprint, second_compact.record_fingerprint)
        self.assertEqual(compact.payload_fingerprint, second_compact.payload_fingerprint)
        restored = restored_again
        new_writer = second_writer
        restored.next_discovery_at = fixture.clock.now() + timedelta(hours=1)
        restored.next_housekeeping_at = fixture.clock.now() + timedelta(hours=1)
        restored.tick(fixture.clock.now())
        self.assertTrue(compact.record_identity.startswith("evidence-rejection-"))
        self.assertEqual(1, len(restored.evidence_rejections))
        self.assertNotIn("record-b", [item.record_identity for item in new_writer.intents])
        restored._emit_intent(
            evidence_type="SYSTEM_FAILURE",
            record_identity="record-c",
            record_fingerprint=fp("restart-record-c"),
            payload_fingerprint=fp("restart-payload-c"),
            payload={"payloadType": "SYSTEM_FAILURE", "body": "valid"},
            now=fixture.clock.now(),
        )
        restored.tick(fixture.clock.now())
        self.assertIn("record-c", [item.record_identity for item in new_writer.intents])
        self.assertEqual(0, dict(restored.health(fixture.clock.now()).queue_depths)["evidence"])


if __name__ == "__main__":
    unittest.main()
