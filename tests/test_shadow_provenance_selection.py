from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from momentum_hunter.autonomy.view_models import stable_trade_plan_id
from momentum_hunter.candidate_lifecycle import expected_opportunity_id, expected_setup_id
from momentum_hunter.intraday_trade_plan import CONTINUATION_BREAKOUT
from momentum_hunter.lifecycle_position_identity import (
    REPORT_IDENTITY_FIELD,
    authoritative_lifecycle_identity_from_report_row,
    bind_report_row_to_producer_identity,
)
from momentum_hunter.shadow_trading import (
    ShadowExecutionPolicy,
    ShadowStateStore,
    ShadowTradingService,
    audit_shadow_trade,
    frozen_evidence_findings,
    shadow_identity_linkage_status,
)
from momentum_hunter.trade_planning import trade_plan_from_dict
from tests.test_account_allocation import synthetic_quantity_allocation_decision
from tests.test_shadow_trading import at, bind_setup_identity, report_payload


class ShadowProvenanceSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="shadow-provenance-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.report_path = self.root / "report.json"
        self.state_path = self.root / "state.json"
        self.decision_at = at("2026-07-23T10:00:00-05:00")
        self.policy = ShadowExecutionPolicy(
            slippage_bps=10,
            minimum_fill_delay_seconds=1,
            buying_power=10_000,
            max_open_positions=3,
        )
        self.row_a = self._bound_row("A", sequence=1)
        self.row_b = self._bound_row("B", sequence=2)

    def _bound_row(self, label: str, *, sequence: int) -> dict:
        row = copy.deepcopy(report_payload()["candidates"][0])
        bind_setup_identity(
            row,
            symbol="MU",
            setup_sequence=sequence,
            created_at=at(f"2026-07-23T09:5{sequence}:00-05:00"),
        )
        row["company"] = f"Synthetic MU plan {label}"
        opportunity_id = expected_opportunity_id(
            "MU", "2026-07-23", f"SYNTHETIC_SELECTOR_{label}"
        )
        record = SimpleNamespace(
            opportunity_id=opportunity_id,
            setup_id=expected_setup_id(opportunity_id, CONTINUATION_BREAKOUT, sequence),
            trade_plan_id=row["trade_plan"]["intraday_evidence"]["plan_id"],
            record_id=f"synthetic-selector-producer-{label}",
            fingerprint=hashlib.sha256(label.encode("ascii")).hexdigest(),
        )
        return json.loads(json.dumps(bind_report_row_to_producer_identity(row, record)))

    def _identity_args(self, row: dict) -> dict:
        identity = authoritative_lifecycle_identity_from_report_row(row)
        return {
            "opportunity_id": identity.opportunity_id,
            "setup_id": identity.setup_id,
            "authoritative_trade_plan_id": identity.trade_plan_id,
        }

    def _persist(self, rows: list, *, collection: str = "candidates") -> None:
        payload = report_payload()
        payload.pop("candidates")
        payload.pop("top_5_for_capital")
        payload[collection] = rows
        self.report_path.write_text(json.dumps(payload), encoding="utf-8")

    def _start(self, *, allocation_row: dict | None = None, **identity_args):
        allocation_row = allocation_row if allocation_row is not None else self.row_b
        plan = trade_plan_from_dict(allocation_row["trade_plan"])
        plan_id = (
            allocation_row[REPORT_IDENTITY_FIELD]["trade_plan_id"]
            if REPORT_IDENTITY_FIELD in allocation_row
            else stable_trade_plan_id("MU", plan)
        )
        allocation = synthetic_quantity_allocation_decision(
            trade_plan_id=plan_id,
            entry_price=plan.bullish_entry,
            stop_price=plan.bullish_stop,
            target_price=plan.bullish_target_1,
            decision_at=self.decision_at,
            quantity=2,
        )
        return ShadowTradingService(
            store=ShadowStateStore(self.state_path), policy=self.policy
        ).start_trade(
            self.report_path,
            symbol="MU",
            simulation_command_id="synthetic-provenance-selection",
            decision_at=self.decision_at,
            account_allocation=allocation,
            **identity_args,
        )

    def _assert_rejected(self, rows: list, **identity_args) -> None:
        self._persist(rows)
        source_bytes = self.report_path.read_bytes()
        with self.assertRaises(ValueError):
            self._start(**identity_args)
        self.assertFalse(self.state_path.exists())
        self.assertEqual(source_bytes, self.report_path.read_bytes())

    def test_exact_b_is_selected_before_symbol_and_survives_reload_and_audit(self) -> None:
        identity = self._identity_args(self.row_b)
        self.assertTrue(all(
            value != self._identity_args(self.row_a)[key]
            for key, value in identity.items()
        ))
        for collection in ("candidates", "top_5_for_capital"):
            for rows in ([self.row_a, self.row_b], [self.row_b, self.row_a]):
                with self.subTest(collection=collection, b_index=rows.index(self.row_b)):
                    self.state_path = self.root / f"{collection}-{rows.index(self.row_b)}.json"
                    self._persist(rows, collection=collection)
                    source_bytes = self.report_path.read_bytes()
                    trade = self._start(**identity)
                    self.assertEqual(self.row_b, trade.evidence.candidate_payload())
                    self.assertEqual(
                        tuple(identity.values()),
                        (trade.opportunity_id, trade.setup_id, trade.trade_plan_id),
                    )
                    self.assertEqual("pending_entry", trade.status)
                    self.assertEqual(trade_plan_from_dict(self.row_b["trade_plan"]), trade.trade_plan())
                    self.assertEqual(2, trade.order.quantity)
                    self.assertEqual(10.0, trade.order.limit_price)
                    self.assertEqual("UNAVAILABLE", shadow_identity_linkage_status(trade))
                    self.assertEqual(source_bytes, self.report_path.read_bytes())
                    self.assertTrue(audit_shadow_trade(trade).passed)
                    restored = ShadowStateStore(self.state_path).load().trades[0]
                    self.assertEqual(trade, restored)
                    self.assertTrue(audit_shadow_trade(restored).passed)

    def test_single_bound_row_still_accepts_implicit_identity(self) -> None:
        self._persist([self.row_b])
        trade = self._start()
        self.assertEqual(self.row_b, trade.evidence.candidate_payload())
        self.assertEqual(self._identity_args(self.row_b)["setup_id"], trade.setup_id)
        self.assertTrue(audit_shadow_trade(trade).passed)

    def test_exact_chain_requires_every_id_and_does_not_guess(self) -> None:
        identity = self._identity_args(self.row_b)
        keys = tuple(identity)
        for mask in range(7):
            supplied = {key: identity[key] for index, key in enumerate(keys) if mask & (1 << index)}
            with self.subTest(supplied=tuple(supplied)):
                self._assert_rejected([self.row_a, self.row_b], **supplied)
                if supplied:
                    self._assert_rejected([self.row_b], **supplied)

    def test_no_exact_row_and_contradictory_chains_fail_closed(self) -> None:
        identity = self._identity_args(self.row_b)
        for key in identity:
            for value in ("f" * 64, self._identity_args(self.row_a)[key], "malformed"):
                with self.subTest(key=key, value=value):
                    self._assert_rejected(
                        [self.row_a, self.row_b], **{**identity, key: value}
                    )

    def test_duplicate_exact_chain_cannot_be_disambiguated_by_symbol(self) -> None:
        for symbol in ("MU", "NVDA"):
            duplicate = copy.deepcopy(self.row_b)
            duplicate["symbol"] = symbol
            with self.subTest(symbol=symbol):
                self._assert_rejected(
                    [self.row_b, duplicate], **self._identity_args(self.row_b)
                )

    def test_exact_selection_checks_symbol_without_falling_back(self) -> None:
        wrong_symbol = copy.deepcopy(self.row_b)
        wrong_symbol["symbol"] = "NVDA"
        self._assert_rejected(
            [self.row_a, wrong_symbol], **self._identity_args(self.row_b)
        )

    def test_claimed_malformed_binding_never_downgrades_to_legacy(self) -> None:
        identity = self._identity_args(self.row_b)
        malformed = [None, {}, [], "invalid"]
        for field, value in (
            ("setup_id", None),
            ("binding_fingerprint", "f" * 64),
            ("authority", "NOT_PRODUCER"),
            ("schema_version", "invalid"),
            ("producer_record_fingerprint", "malformed"),
        ):
            binding = copy.deepcopy(self.row_b[REPORT_IDENTITY_FIELD])
            binding[field] = value
            malformed.append(binding)
        missing_field = copy.deepcopy(self.row_b[REPORT_IDENTITY_FIELD])
        missing_field.pop("setup_id")
        malformed.append(missing_field)
        for binding in malformed:
            row = copy.deepcopy(self.row_b)
            row[REPORT_IDENTITY_FIELD] = binding
            for supplied in ({}, identity):
                with self.subTest(binding=binding, exact=bool(supplied)):
                    self._assert_rejected([row], **supplied)
        mismatched_plan = copy.deepcopy(self.row_b)
        mismatched_plan["trade_plan"]["intraday_evidence"]["plan_id"] = "f" * 64
        self._assert_rejected([mismatched_plan], **identity)

    def test_binding_is_validated_before_symbol_sanity(self) -> None:
        row = copy.deepcopy(self.row_b)
        row["symbol"] = "NVDA"
        row[REPORT_IDENTITY_FIELD]["binding_fingerprint"] = "f" * 64
        self._persist([self.row_a, row])
        with self.assertRaisesRegex(ValueError, "invalid authoritative lifecycle identity"):
            self._start(**self._identity_args(self.row_b))
        self.assertFalse(self.state_path.exists())

    def test_unrelated_malformed_binding_does_not_hide_exact_b(self) -> None:
        row = copy.deepcopy(self.row_a)
        row[REPORT_IDENTITY_FIELD] = None
        self._persist([row, self.row_b])
        trade = self._start(**self._identity_args(self.row_b))
        self.assertEqual(self.row_b, trade.evidence.candidate_payload())
        self.assertTrue(audit_shadow_trade(trade).passed)

    def test_stripped_modern_row_cannot_become_legacy_through_selection_alias(self) -> None:
        legacy = copy.deepcopy(self.row_b)
        legacy.pop(REPORT_IDENTITY_FIELD)
        for selection_id in ("", "historical-shadow-selection"):
            with self.subTest(selection_id=selection_id):
                self.state_path = self.root / f"legacy-{selection_id}.json"
                self._persist([legacy])
                with self.assertRaisesRegex(ValueError, "persisted Producer binding"):
                    self._start(allocation_row=legacy, opportunity_id=selection_id)

    def test_legacy_rows_cannot_satisfy_exact_or_ambiguous_selection(self) -> None:
        legacy = copy.deepcopy(self.row_b)
        legacy.pop(REPORT_IDENTITY_FIELD)
        self._assert_rejected([legacy], **self._identity_args(self.row_b))
        self._assert_rejected([legacy, copy.deepcopy(legacy)])

    def test_frozen_evidence_rejects_wrong_selected_row_or_chain(self) -> None:
        self._persist([self.row_a, self.row_b])
        trade = self._start(**self._identity_args(self.row_b))
        wrong_row = replace(
            trade,
            evidence=replace(
                trade.evidence,
                candidate_json=json.dumps(self.row_a, sort_keys=True, separators=(",", ":")),
            ),
        )
        wrong_chain = replace(trade, setup_id=self._identity_args(self.row_a)["setup_id"])
        self.assertTrue(frozen_evidence_findings(wrong_row))
        self.assertTrue(frozen_evidence_findings(wrong_chain))


if __name__ == "__main__":
    unittest.main()
