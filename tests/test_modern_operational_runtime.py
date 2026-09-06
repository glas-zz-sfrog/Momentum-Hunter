"""Dormant startup using native owners and synthetic transports only."""
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from momentum_hunter import modern_operational as modern
from momentum_hunter.continuous_live_qualification import (
    LiveCompositionSource, LiveDiscoverySource, LiveMarketDataSource, LiveMaterialEvents,
)
from momentum_hunter.continuous_runtime import ContinuousOpportunityRuntime
from momentum_hunter.continuous_tradeplan_producer import ContinuousTradePlanProducerError
from momentum_hunter.modern_operational_runtime import open_modern_runtime
from tests.test_continuous_runtime import RuntimeFixture
from tests.test_modern_operational import EpochFixture, SOURCE


class ModernOperationalRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="mh-modern-start-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.native = RuntimeFixture(self.root / "old-research")
        self.fixture = EpochFixture(self.root, configuration=self.native.config.fingerprint)
        self.addCleanup(self.fixture.patch.stop)
        self.discovery = Mock(name="synthetic-discovery-transport")
        self.market = Mock(name="synthetic-market-only-transport")
        self.preflight = Mock(side_effect=lambda epoch, now: replace(
            self.fixture.assessment(), observed_at=now.isoformat()))

    def open(self, *, fresh=True, **overrides):
        arguments = dict(source_identity=SOURCE, config=self.native.config,
            runtime_instance_id="synthetic-modern-startup", fresh=fresh,
            clock=self.native.clock.now, obligation_preflight=self.preflight,
            discovery_provider=self.discovery, market_data_boundary=self.market,
            writer=self.native.writer)
        arguments.update(overrides)
        return open_modern_runtime(**arguments)

    def assert_no_provider_contact(self):
        self.assertEqual(self.discovery.mock_calls, [])
        self.assertEqual(self.market.mock_calls, [])

    def test_fresh_start_selects_and_binds_native_runtime_sources(self):
        old = self.root / "old-research" / "legacy-producer.json"
        old.parent.mkdir(exist_ok=True)
        old.write_bytes(b'{"schemaVersion":2,"records":["old"]}')
        with self.open() as session:
            self.assertIs(type(session.runtime), ContinuousOpportunityRuntime)
            self.assertIs(type(session.runtime.discovery_source), LiveDiscoverySource)
            self.assertIs(type(session.runtime.market_data_source), LiveMarketDataSource)
            self.assertIs(type(session.runtime.event_source), LiveMaterialEvents)
            self.assertIs(type(session.composition), LiveCompositionSource)
            self.assertEqual(session.runtime.operational_epoch, self.fixture.epoch)
            self.assertEqual(session.composition.producer_store.operational_epoch, self.fixture.epoch)
            self.assertIs(session.runtime.event_source.natural_setup, session.composition.natural_setup)
            self.assertEqual(session.composition.producer_store.load(), ())
            self.assertEqual(session.runtime.checkpoint_store.load(self.native.config.runtime_identity)
                ["operationalEpochId"], self.fixture.epoch.epoch_id)
            self.assertEqual(session.state.root, self.fixture.root / "session")
        self.assertEqual(old.read_bytes(), b'{"schemaVersion":2,"records":["old"]}')
        self.assert_no_provider_contact()

    def test_restore_preserves_start_floor_and_exact_modern_queued_work(self):
        with self.open() as first:
            first.runtime.request_discovery(self.native.clock.now())
            first.runtime._checkpoint(self.native.clock.now())
            started = first.runtime.started_at
            queue = first.runtime._queues["discovery"].snapshot()
        self.native.clock.advance(31)
        with self.open(fresh=False) as restored:
            self.assertEqual(modern.instant(restored.state.launch_at.isoformat()),
                             modern.instant(started.isoformat()))
            self.assertEqual(restored.runtime._queues["discovery"].snapshot(), queue)
            self.assertEqual(restored.runtime.started_at, started)
        self.assertEqual(self.preflight.call_count, 2)
        self.assert_no_provider_contact()

    def test_missing_authority_stops_before_preflight_and_sources(self):
        self.fixture.path.unlink()
        with self.assertRaises(modern.ModernOperationalError), self.open():
            self.fail("Must not start")
        self.preflight.assert_not_called()
        self.assertFalse(self.fixture.root.exists())
        self.assert_no_provider_contact()

    def test_obligations_are_not_imported_abandoned_or_flattened(self):
        for item in (modern.Obligation("old-owned", "f" * 64, False),
                     modern.Obligation("unknown", None, False),
                     modern.Obligation("current-unresolved", self.fixture.epoch.epoch_id, False)):
            with self.subTest(item=item):
                self.preflight.side_effect = lambda epoch, now: replace(
                    self.fixture.assessment((item,)), observed_at=now.isoformat())
                with self.assertRaisesRegex(modern.ModernOperationalError,
                                            "BLOCK_RECONCILIATION_REQUIRED"), self.open():
                    self.fail("Must not start")
                self.assertFalse(self.fixture.root.exists())
        self.assert_no_provider_contact()

    def test_replayed_preflight_is_not_a_new_startup_observation(self):
        self.preflight.side_effect = None
        self.preflight.return_value = self.fixture.assessment()
        with self.assertRaisesRegex(modern.ModernOperationalError,
                                    "BLOCK_RECONCILIATION_REQUIRED"), self.open():
            self.fail("Must not start")
        self.assertFalse(self.fixture.root.exists())
        self.assert_no_provider_contact()

    def test_duplicate_owner_cannot_start_or_restore(self):
        with self.open():
            for fresh in (True, False):
                with self.subTest(fresh=fresh):
                    with self.assertRaisesRegex(modern.ModernOperationalError,
                                                "MODERN_RUNTIME_ALREADY_OWNED"), self.open(fresh=fresh):
                        self.fail("Duplicate must not start")
        self.assertEqual(self.preflight.call_count, 1)
        self.assert_no_provider_contact()

    def test_fresh_cannot_reset_existing_and_restore_cannot_create_missing(self):
        with self.assertRaises(modern.ModernOperationalError), self.open(fresh=False):
            self.fail("Missing state must not be created")
        with self.open() as session:
            pointer = session.runtime.checkpoint_store.publication.pointer
        original = pointer.read_bytes()
        with self.assertRaises(modern.ModernOperationalError), self.open():
            self.fail("Must not reset")
        self.assertEqual(pointer.read_bytes(), original)
        self.assert_no_provider_contact()

    def test_restore_requires_native_modern_producer_not_schema_two(self):
        with self.open() as session:
            producer_path = session.composition.producer_store.path
        tampered = b'{"schemaVersion":2,"records":[]}'
        producer_path.write_bytes(tampered)
        with self.assertRaises((modern.ModernOperationalError,
                                ContinuousTradePlanProducerError)), self.open(fresh=False):
            self.fail("Legacy Producer must not restore")
        self.assertEqual(producer_path.read_bytes(), tampered)
        self.assert_no_provider_contact()

    def test_wrong_config_or_session_never_starts(self):
        with self.assertRaises(modern.ModernOperationalError), self.open(
                source_identity="f" * 64):
            self.fail("Wrong approved source")
        with self.assertRaises(modern.ModernOperationalError), self.open(
                config=replace(self.native.config, session_date="2026-08-19")):
            self.fail("Wrong configuration")
        self.assertFalse(self.fixture.root.exists())
        self.assert_no_provider_contact()
