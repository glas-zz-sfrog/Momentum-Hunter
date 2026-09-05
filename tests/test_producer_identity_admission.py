"""Repair-003: natural Product inputs and exact canonical historical bytes."""

import copy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from momentum_hunter.continuous_live_qualification import LiveCompositionSource
from momentum_hunter.continuous_tradeplan_producer import (
    ContinuousTradePlanProducerError, ContinuousTradePlanProducerStore,
    producer_bound_report_row,
)
from momentum_hunter.lifecycle_position_identity import REPORT_IDENTITY_FIELD
from momentum_hunter.shadow_trading import (
    ShadowExecutionPolicy, ShadowStateError, ShadowStateStore, ShadowTradingService,
    shadow_identity_linkage_status,
)
from tests import test_continuous_natural_setup as natural


FIXTURE = Path(__file__).parent / "fixtures/identity_precontract/producer.json"
FIXTURE_SHA = "664885014323AC60819AA2BCEA5178003344E81DD60871FE7ADA7E4F995E2596"


class ProducerIdentityAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = natural.ContinuousNaturalSetupTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.source = LiveCompositionSource(self.fixture.state)
        self.fixture._prepare(natural.at(11, 21), generation=1)
        self.source.compose(self.fixture._request(natural.at(11, 21), generation=1))
        records = self.source.producer.store.load()
        self.record = next(r for r in records if producer_bound_report_row(r) is not None)
        self.store = ContinuousTradePlanProducerStore(self.root / "single.json")
        self.store.append(self.record)
        self.document = json.loads(self.store.path.read_bytes())
        self.state = self.root / "shadow.json"

    def start(self, document, **ids):
        self.store.path.write_text(json.dumps(document), encoding="ascii")
        return ShadowTradingService(
            store=ShadowStateStore(self.state), policy=ShadowExecutionPolicy(),
        ).start_trade(self.store.path, symbol=self.record.symbol,
                      simulation_command_id="repair003-offline", decision_at=natural.at(11, 22), **ids)

    def rejected(self, document):
        self.store.path.write_text(json.dumps(document), encoding="ascii")
        original = self.store.path.read_bytes()
        with self.assertRaises(ContinuousTradePlanProducerError):
            self.store.load()
        with self.assertRaises((ValueError, ShadowStateError)):
            self.start(document)
        self.assertFalse(self.state.exists())
        self.assertEqual(original, self.store.path.read_bytes())

    def test_independent_f1_row_field_deletion_matrix(self):
        for names in (
            (REPORT_IDENTITY_FIELD,), ("opportunity_id",), ("setup_id",),
            ("trade_plan_id",), ("opportunity_id", "setup_id"),
            (REPORT_IDENTITY_FIELD, "opportunity_id", "setup_id"),
            (REPORT_IDENTITY_FIELD, "opportunity_id", "setup_id", "trade_plan_id"),
        ):
            with self.subTest(removed=names):
                document = copy.deepcopy(self.document)
                for name in names:
                    document["candidates"][0].pop(name)
                self.rejected(document)

    def test_valid_upstream_without_position_is_unavailable_and_restarts(self):
        trade = self.start(self.document)
        self.assertIsNone(trade.position)
        self.assertEqual("UNAVAILABLE", shadow_identity_linkage_status(trade))
        restored = ShadowStateStore(self.state).load().trades[0]
        self.assertEqual(trade, restored)
        self.assertEqual("UNAVAILABLE", shadow_identity_linkage_status(restored))

    def test_missing_or_rejected_producer_record_cannot_authorize_shadow(self):
        for mode in ("empty", "removed", "record_fingerprint", "partial", "contradictory"):
            with self.subTest(mode=mode):
                document = copy.deepcopy(self.document)
                if mode == "empty":
                    document["records"] = []
                elif mode == "removed":
                    document.pop("records")
                elif mode == "record_fingerprint":
                    document["records"][0]["fingerprint"] = "0" * 64
                elif mode == "partial":
                    document["records"][0].pop("opportunity_id")
                else:
                    document["candidates"][0]["setup_id"] = "f" * 64
                self.rejected(document)

    def test_exact_valid_row_beside_stripped_same_symbol_never_uses_symbol_fallback(self):
        document = copy.deepcopy(self.document)
        stripped = copy.deepcopy(document["candidates"][0])
        for name in (REPORT_IDENTITY_FIELD, "opportunity_id", "setup_id", "trade_plan_id"):
            stripped.pop(name)
        document["candidates"].insert(0, stripped)
        with self.assertRaises(ValueError):
            self.start(document)
        self.assertFalse(self.state.exists())
        binding = document["candidates"][1][REPORT_IDENTITY_FIELD]
        trade = self.start(document, opportunity_id=binding["opportunity_id"],
                           setup_id=binding["setup_id"],
                           authoritative_trade_plan_id=binding["trade_plan_id"])
        self.assertEqual(document["candidates"][1], trade.evidence.candidate_payload())
        self.assertEqual("UNAVAILABLE", shadow_identity_linkage_status(trade))
        self.assertEqual(trade, ShadowStateStore(self.state).load().trades[0])

    def test_stripped_modern_frozen_source_with_tampered_time_is_unknown(self):
        trade = self.start(self.document)
        stripped = copy.deepcopy(self.document)
        for name in (REPORT_IDENTITY_FIELD, "opportunity_id", "setup_id", "trade_plan_id"):
            stripped["candidates"][0].pop(name)
        corrupted = replace(trade, decision_timestamp="2026-08-26T00:00:00-05:00",
            evidence=replace(trade.evidence, source_report_json=json.dumps(stripped)))
        self.assertEqual("UNKNOWN", shadow_identity_linkage_status(corrupted))
        state = ShadowStateStore(self.state).load()
        with self.assertRaises(ShadowStateError):
            ShadowStateStore(self.state).save(replace(state, trades=(corrupted,)))

    def test_schema_types_are_strict_on_document_and_record(self):
        for value in (True, False, 1.0, 1.5, 2.0, "2", None, 99):
            for scope in ("document", "record"):
                with self.subTest(value=value, scope=scope):
                    document = copy.deepcopy(self.document)
                    if scope == "document":
                        document["schemaVersion"] = value
                    else:
                        document["records"][0]["schema_version"] = value
                    self.rejected(document)

    def test_modern_cache_cannot_downgrade_by_stripping_all_modern_fields(self):
        document = copy.deepcopy(self.document)
        document.pop("candidates")
        record = document["records"][0]
        record.pop("opportunity_id")
        payload = json.loads(record["payload_json"])
        for name in ("opportunityId", "setupId", "tradePlanId", "reportRowContract", "lifecycleSnapshot"):
            payload.pop(name)
        record["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        record["payload_fingerprint"] = hashlib.sha256(record["payload_json"].encode("ascii")).hexdigest()
        # Changing the inner bytes cannot inherit the original outer commitment.
        self.rejected(document)


class PrecontractProducerCompatibilityTests(unittest.TestCase):
    def test_exact_canonical_fixture_loads_without_rewrite_or_identity_fabrication(self):
        raw = FIXTURE.read_bytes()
        self.assertEqual(FIXTURE_SHA, hashlib.sha256(raw).hexdigest().upper())
        with tempfile.TemporaryDirectory(prefix="repair003-legacy-") as temporary:
            path = Path(temporary) / "producer.json"
            path.write_bytes(raw)
            store = ContinuousTradePlanProducerStore(path)
            records = store.load()
            self.assertEqual(3, len(records))
            self.assertTrue(any(r.setup_id for r in records))
            self.assertTrue(all(not r.opportunity_id for r in records))
            self.assertTrue(all(producer_bound_report_row(r) is None for r in records))
            self.assertEqual(raw, path.read_bytes())
            self.assertEqual(records, store.load())
            for record in records:
                self.assertEqual(record, store.append(record))
            self.assertEqual(raw, path.read_bytes())
            copied = ContinuousTradePlanProducerStore(Path(temporary) / "resaved.json")
            for record in records:
                copied.append(record)
            self.assertEqual(records, copied.load())
            saved = copied.path.read_bytes()
            for record in records:
                copied.append(record)
            self.assertEqual(saved, copied.path.read_bytes())
        self.assertEqual(raw, FIXTURE.read_bytes())

    def test_historical_cache_cannot_gain_modern_marker_privilege(self):
        document = json.loads(FIXTURE.read_bytes())
        record = document["records"][0]
        payload = json.loads(record["payload_json"])
        payload["reportRowContract"] = 1
        record["payload_json"] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        record["payload_fingerprint"] = hashlib.sha256(record["payload_json"].encode("ascii")).hexdigest()
        core = {k:v for k,v in record.items() if k not in {"record_id", "fingerprint"}}
        record["fingerprint"] = hashlib.sha256((json.dumps(core, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")).hexdigest()
        with self.assertRaises(ContinuousTradePlanProducerError):
            ContinuousTradePlanProducerStore.validate_document(document)

    def test_legacy_looking_malformed_cache_is_not_historical_lineage(self):
        for mode in ("fingerprint", "payload", "profile", "version"):
            document = json.loads(FIXTURE.read_bytes())
            with self.subTest(mode=mode):
                if mode == "fingerprint":
                    document["records"][0]["fingerprint"] = "0" * 64
                elif mode == "payload":
                    document["records"][0]["payload_json"] = "{}"
                elif mode == "profile":
                    document["records"][0]["profile"] = "LEGACY"
                else:
                    document["schemaVersion"] = True
                with self.assertRaises(ContinuousTradePlanProducerError):
                    ContinuousTradePlanProducerStore.validate_document(document)
