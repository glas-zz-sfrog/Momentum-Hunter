from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from momentum_hunter.lifecycle_position_identity import (
    REPORT_IDENTITY_FIELD, REPORT_LINEAGE_FIELD, LifecyclePositionIdentityError,
    authoritative_lifecycle_identity_from_report_row, validate_authoritative_lifecycle_identity,
)
from momentum_hunter.shadow_trading import (
    ShadowStateError, ShadowStateStore, ShadowTradingService, ShadowExecutionPolicy,
    shadow_identity_linkage_status, shadow_state_from_dict, shadow_trade_from_dict,
    shadow_review_trade_to_dict, audit_shadow_trade,
)
from tests.test_shadow_trading import report_payload, at, quote, allocation_for_report


class ShadowIdentityIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="MomentumHunter-Identity-Repair002-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = ShadowStateStore(self.root / "state.json")
        self.policy = ShadowExecutionPolicy(slippage_bps=10, minimum_fill_delay_seconds=1, buying_power=10000, max_open_positions=3)
        self.service = ShadowTradingService(store=self.store, policy=self.policy)

    def start(self, payload=None):
        report = self.root / "report.json"
        report.write_text(json.dumps(payload or report_payload()), encoding="utf-8")
        decision = at("2026-07-23T10:00:00-05:00")
        return self.service.start_trade(report, symbol="TEST", simulation_command_id="integrity", decision_at=decision, account_allocation=allocation_for_report(report, symbol="TEST", decision_at=decision))

    def open(self):
        self.start()
        timestamp = at("2026-07-23T10:00:02-05:00")
        return self.service.process_quote(quote(timestamp.isoformat(), bid=9.94, ask=9.95), received_at=timestamp)[0]

    def raw(self):
        return json.loads(self.store.path.read_text(encoding="utf-8"))

    def assert_reload_rejected(self, raw):
        self.store.path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises((ShadowStateError, ValueError, TypeError)):
            ShadowStateStore(self.store.path).load()

    def test_strict_binding_version_at_parser_and_dataclass_boundary(self):
        row = report_payload()["candidates"][0]
        valid = authoritative_lifecycle_identity_from_report_row(row)
        for value in (True, False, 1.0, 1.5, "1", None, -1, 2, {}, []):
            with self.subTest(value=value):
                changed = copy.deepcopy(row)
                changed[REPORT_IDENTITY_FIELD]["schema_version"] = value
                with self.assertRaises(LifecyclePositionIdentityError):
                    authoritative_lifecycle_identity_from_report_row(changed)
                with self.assertRaises(LifecyclePositionIdentityError):
                    validate_authoritative_lifecycle_identity(replace(valid, schema_version=value))
        del row[REPORT_IDENTITY_FIELD]["schema_version"]
        with self.assertRaises(LifecyclePositionIdentityError):
            authoritative_lifecycle_identity_from_report_row(row)

    def test_complete_envelope_rejects_every_contradiction_or_partial_field(self):
        row = report_payload()["candidates"][0]
        binding = row[REPORT_IDENTITY_FIELD]
        for key in ("opportunity_id", "setup_id", "trade_plan_id"):
            row[key] = binding[key]
        row[REPORT_LINEAGE_FIELD] = 1
        authoritative_lifecycle_identity_from_report_row(row)
        for key in ("opportunity_id", "setup_id", "trade_plan_id", "producer_record_id", "producer_record_fingerprint"):
            with self.subTest(key=key):
                changed = copy.deepcopy(row)
                changed[key] = "f" * 64
                with self.assertRaises(LifecyclePositionIdentityError):
                    authoritative_lifecycle_identity_from_report_row(changed)
        for key in ("opportunity_id", "setup_id", "trade_plan_id"):
            changed = copy.deepcopy(row)
            del changed[key]
            with self.assertRaises(LifecyclePositionIdentityError):
                authoritative_lifecycle_identity_from_report_row(changed)

    def test_contradictory_persisted_row_fails_restart_and_read_boundary(self):
        self.open()
        original = self.raw()
        for key in ("opportunity_id", "setup_id", "trade_plan_id"):
            with self.subTest(key=key):
                raw = copy.deepcopy(original)
                evidence = raw["trades"][0]["evidence"]
                row = json.loads(evidence["candidate_json"])
                row[key] = "f" * 64
                evidence["candidate_json"] = json.dumps(row)
                trade = shadow_trade_from_dict(raw["trades"][0])
                self.assertEqual("UNKNOWN", shadow_identity_linkage_status(trade))
                self.assert_reload_rejected(raw)

    def test_first_fill_open_identity_is_bound_and_preserved(self):
        self.start()
        positions = []
        bindings = []
        for second in (2, 4):
            service = ShadowTradingService(store=self.store, policy=self.policy)
            timestamp = at(f"2026-07-23T10:00:0{second}-05:00")
            trade = service.process_quote(quote(timestamp.isoformat(), bid=9.94, ask=9.95, available_size=1), received_at=timestamp)[0]
            self.assertEqual("PROVEN", shadow_identity_linkage_status(trade))
            positions.append((trade.position.position_id, trade.position.opened_at))
            bindings.append(trade.position_identity_json)
        self.assertEqual(positions[0], positions[1])
        self.assertEqual(bindings[0], bindings[1])
        self.assertEqual("2026-07-23T10:00:02-05:00", positions[0][1])
        self.assertEqual("open", self.store.load().trades[0].status)

    def test_raw_timestamp_position_and_combined_tamper_rejected(self):
        self.open()
        original = self.raw()
        for fields in (("opened_at",), ("position_id",), ("opened_at", "position_id")):
            with self.subTest(fields=fields):
                raw = copy.deepcopy(original)
                for name in fields:
                    raw["trades"][0]["position"][name] = "2026-07-23T09:00:00-05:00" if name == "opened_at" else "shadow-position-rewritten"
                trade = shadow_trade_from_dict(raw["trades"][0])
                self.assertEqual("UNKNOWN", shadow_identity_linkage_status(trade))
                self.assert_reload_rejected(raw)

    def test_first_fill_event_or_binding_corruption_rejected(self):
        self.open()
        original = self.raw()
        for variant in ("event", "binding", "delete", "schema"):
            with self.subTest(variant=variant):
                raw = copy.deepcopy(original)
                trade = raw["trades"][0]
                if variant == "event":
                    event = next(e for e in trade["ledger_events"] if e["requested_action"] == "fake_order_filled")
                    event["timestamp"] = "2026-07-23T09:00:00-05:00"
                elif variant == "delete":
                    del trade["position_identity_json"]
                else:
                    binding = json.loads(trade["position_identity_json"])
                    binding["fingerprint" if variant == "binding" else "schema_version"] = "f" * 64 if variant == "binding" else True
                    trade["position_identity_json"] = json.dumps(binding)
                self.assert_reload_rejected(raw)

    def test_modern_stripping_and_time_tamper_cannot_masquerade_as_legacy(self):
        self.open()
        original = self.raw()
        for variant in ("binding", "all_trade_ids", "lineage", "all_markers", "downgrade_state"):
            with self.subTest(variant=variant):
                raw = copy.deepcopy(original)
                trade = raw["trades"][0]
                row = json.loads(trade["evidence"]["candidate_json"])
                row.pop(REPORT_IDENTITY_FIELD)
                trade["evidence"]["candidate_json"] = json.dumps(row)
                trade["position"]["opened_at"] = "2026-07-23T09:00:00-05:00"
                if variant == "all_trade_ids":
                    for key in ("opportunity_id", "setup_id", "trade_plan_id"):
                        trade.pop(key)
                        trade["position"].pop(key)
                if variant in ("lineage", "all_markers", "downgrade_state"):
                    trade.pop("identity_lineage")
                if variant in ("all_markers", "downgrade_state"):
                    trade.pop("identity_record_version")
                if variant == "downgrade_state":
                    raw["schema_version"] = 1
                self.assert_reload_rejected(raw)

    def test_missing_modern_version_fails_without_other_tampering(self):
        self.open()
        raw = self.raw()
        del raw["trades"][0]["identity_record_version"]
        self.assert_reload_rejected(raw)

    def test_schema_strict_in_state_and_record(self):
        self.open()
        original = self.raw()
        for field in ("schema_version", "identity_record_version"):
            for value in (True, False, 1.0, 1.5, "1", None, -1, 99, {}, []):
                with self.subTest(field=field, value=value):
                    raw = copy.deepcopy(original)
                    (raw if field == "schema_version" else raw["trades"][0])[field] = value
                    self.assert_reload_rejected(raw)

    def test_actual_precontract_executable_fixture_stays_legacy_without_rewriting(self):
        root = Path(__file__).parent / "fixtures/identity_precontract"
        raw = (root / "state.json").read_bytes()
        origin = json.loads((root / "origin.json").read_text())
        self.assertEqual(origin["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual("2bceeeadd06f5ed85943942f1c0f81b7094620f7", origin["sourceGit"])
        self.store.path.write_bytes(raw)
        trade = self.store.load().trades[0]
        self.assertEqual("LEGACY_UNBOUND", shadow_identity_linkage_status(trade))
        self.assertEqual(0, trade.identity_record_version)
        self.assertEqual(raw, self.store.path.read_bytes())
        view = shadow_review_trade_to_dict(trade, audit_shadow_trade(trade), sample_definition=trade.sample_metadata)
        self.assertEqual("LEGACY_UNBOUND", view["linkageStatus"])

    def test_save_rejects_rebinding_existing_first_fill(self):
        original = self.open()
        state = self.store.load()
        rewritten = replace(original, position_identity_json="{}")
        with self.assertRaises(ShadowStateError):
            self.store.save(replace(state, trades=(rewritten,)))
        self.assertEqual(original.position_identity_json, self.store.load().trades[0].position_identity_json)


if __name__ == "__main__":
    unittest.main()
