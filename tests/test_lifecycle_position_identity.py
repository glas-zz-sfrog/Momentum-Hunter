from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import copy
import json
from pathlib import Path
import tempfile
import unittest

from momentum_hunter.lifecycle_position_identity import (
    IDENTITY_LINKAGE_LEGACY_UNBOUND,
    IDENTITY_LINKAGE_PROVEN,
    IDENTITY_LINKAGE_STATES,
    IDENTITY_LINKAGE_UNAVAILABLE,
    IDENTITY_LINKAGE_UNKNOWN,
    LifecyclePositionIdentityError,
    REPORT_IDENTITY_FIELD,
    authoritative_lifecycle_identity_from_report_row,
)
from momentum_hunter.shadow_trading import (
    ShadowExecutionPolicy,
    ShadowStateError,
    ShadowStateStore,
    ShadowTradingService,
    audit_shadow_trade,
    shadow_identity_linkage_status,
    shadow_review_trade_to_dict,
)
from tests.test_shadow_trading import (
    allocation_for_report,
    at,
    bind_setup_identity,
    quote,
    report_payload,
)


class LifecyclePositionIdentityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy = ShadowExecutionPolicy(
            slippage_bps=10,
            minimum_fill_delay_seconds=1,
            buying_power=10_000,
            max_open_positions=3,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _start(
        self,
        *,
        name: str,
        payload: dict | None = None,
        decision_at: datetime | None = None,
    ):
        payload = payload or report_payload()
        decision_at = decision_at or at("2026-07-23T10:00:00-05:00")
        report_path = self.root / f"{name}.json"
        state_path = self.root / f"{name}-state.json"
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        service = ShadowTradingService(
            store=ShadowStateStore(state_path),
            policy=self.policy,
        )
        trade = service.start_trade(
            report_path,
            symbol="TEST",
            simulation_command_id=f"identity-{name}",
            decision_at=decision_at,
            account_allocation=allocation_for_report(
                report_path,
                symbol="TEST",
                decision_at=decision_at,
            ),
        )
        return report_path, state_path, service, trade

    def _open(self, **kwargs):
        report_path, state_path, service, trade = self._start(**kwargs)
        fill_at = datetime.fromisoformat(trade.decision_timestamp).replace(
            second=2,
            microsecond=0,
        )
        updated = service.process_quote(
            quote(fill_at.isoformat(), bid=9.94, ask=9.95),
            received_at=fill_at,
        )
        opened = next(
            item for item in updated if item.shadow_trade_id == trade.shadow_trade_id
        )
        self.assertIsNotNone(opened.position)
        return report_path, state_path, opened

    def test_linkage_status_contract_is_exact(self) -> None:
        self.assertEqual(
            {"PROVEN", "UNKNOWN", "UNAVAILABLE", "LEGACY_UNBOUND"},
            set(IDENTITY_LINKAGE_STATES),
        )

    def test_bound_trade_is_unavailable_until_position_exists(self) -> None:
        _, _, _, trade = self._start(name="pending")
        self.assertEqual(
            IDENTITY_LINKAGE_UNAVAILABLE,
            shadow_identity_linkage_status(trade),
        )

    def test_accepted_setup_to_tradeplan_to_position_exact_chain_passes(self) -> None:
        _, _, trade = self._open(name="exact")
        identity = authoritative_lifecycle_identity_from_report_row(
            trade.evidence.candidate_payload()
        )
        expected = (
            identity.opportunity_id,
            identity.setup_id,
            identity.trade_plan_id,
        )
        self.assertEqual(expected, (trade.opportunity_id, trade.setup_id, trade.trade_plan_id))
        self.assertEqual(
            expected,
            (
                trade.position.opportunity_id,
                trade.position.setup_id,
                trade.position.trade_plan_id,
            ),
        )
        self.assertEqual(IDENTITY_LINKAGE_PROVEN, shadow_identity_linkage_status(trade))

    def test_two_setups_for_same_symbol_remain_distinct(self) -> None:
        first_payload = report_payload()
        second_payload = report_payload()
        bind_setup_identity(
            second_payload["candidates"][0],
            created_at=at("2026-07-23T10:03:00-05:00"),
            setup_sequence=2,
        )
        _, _, first = self._open(name="setup-1", payload=first_payload)
        _, _, second = self._open(
            name="setup-2",
            payload=second_payload,
            decision_at=at("2026-07-23T10:04:00-05:00"),
        )
        self.assertEqual(first.symbol, second.symbol)
        self.assertEqual(first.opportunity_id, second.opportunity_id)
        self.assertNotEqual(first.setup_id, second.setup_id)
        self.assertNotEqual(first.trade_plan_id, second.trade_plan_id)
        self.assertNotEqual(first.position.position_id, second.position.position_id)

    def test_legacy_record_remains_explicitly_unbound(self) -> None:
        payload = report_payload()
        payload["candidates"][0].pop(REPORT_IDENTITY_FIELD)
        _, state_path, trade = self._open(name="legacy", payload=payload)
        self.assertEqual("", trade.opportunity_id)
        self.assertEqual("", trade.setup_id)
        self.assertEqual("", trade.position.opportunity_id)
        self.assertEqual(
            IDENTITY_LINKAGE_LEGACY_UNBOUND,
            shadow_identity_linkage_status(trade),
        )
        restored = ShadowStateStore(state_path).load().trades[0]
        self.assertEqual(
            IDENTITY_LINKAGE_LEGACY_UNBOUND,
            shadow_identity_linkage_status(restored),
        )

    def test_partial_or_mismatched_provenance_is_unknown_and_fails_persistence(self) -> None:
        _, state_path, trade = self._open(name="mismatch")
        mismatched = replace(
            trade,
            position=replace(trade.position, setup_id="f" * 64),
        )
        self.assertEqual(IDENTITY_LINKAGE_UNKNOWN, shadow_identity_linkage_status(mismatched))
        with self.assertRaises(ShadowStateError):
            ShadowStateStore(state_path).save(
                replace(ShadowStateStore(state_path).load(), trades=(mismatched,))
            )

    def test_missing_or_malformed_binding_cannot_claim_authoritative_identity(self) -> None:
        missing = report_payload()
        identity = missing["candidates"][0].pop(REPORT_IDENTITY_FIELD)
        report_path = self.root / "missing.json"
        report_path.write_text(json.dumps(missing), encoding="utf-8")
        service = ShadowTradingService(
            store=ShadowStateStore(self.root / "missing-state.json"),
            policy=self.policy,
        )
        with self.assertRaisesRegex(ValueError, "require a persisted Producer binding"):
            service.start_trade(
                report_path,
                symbol="TEST",
                simulation_command_id="missing-binding",
                decision_at=at("2026-07-23T10:00:00-05:00"),
                setup_id=identity["setup_id"],
                authoritative_trade_plan_id=identity["trade_plan_id"],
                account_allocation=allocation_for_report(
                    report_path,
                    symbol="TEST",
                    decision_at=at("2026-07-23T10:00:00-05:00"),
                ),
            )
        malformed = report_payload()
        malformed["candidates"][0][REPORT_IDENTITY_FIELD].pop("setup_id")
        with self.assertRaises(LifecyclePositionIdentityError):
            authoritative_lifecycle_identity_from_report_row(malformed["candidates"][0])

    def test_repeated_symbol_rows_are_not_heuristically_joined(self) -> None:
        payload = report_payload()
        payload["candidates"].append(copy.deepcopy(payload["candidates"][0]))
        report_path = self.root / "ambiguous.json"
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        service = ShadowTradingService(
            store=ShadowStateStore(self.root / "ambiguous-state.json"),
            policy=self.policy,
        )
        with self.assertRaisesRegex(ValueError, "exactly one persisted candidate row"):
            service.start_trade(
                report_path,
                symbol="TEST",
                simulation_command_id="ambiguous",
                decision_at=at("2026-07-23T10:00:00-05:00"),
                account_allocation=allocation_for_report(
                    report_path,
                    symbol="TEST",
                    decision_at=at("2026-07-23T10:00:00-05:00"),
                ),
            )

    def test_exact_opened_at_and_position_id_survive_restart_and_read_boundary(self) -> None:
        _, state_path, trade = self._open(name="restart")
        restored = ShadowStateStore(state_path).load().trades[0]
        self.assertEqual(trade.position.position_id, restored.position.position_id)
        self.assertEqual(trade.position.opened_at, restored.position.opened_at)
        payload = shadow_review_trade_to_dict(
            restored,
            audit_shadow_trade(restored),
            sample_definition=restored.sample_metadata,
        )
        self.assertEqual(restored.opportunity_id, payload["opportunityId"])
        self.assertEqual(restored.setup_id, payload["setupId"])
        self.assertEqual(restored.trade_plan_id, payload["tradePlanId"])
        self.assertEqual(restored.position.position_id, payload["positionId"])
        self.assertEqual(restored.position.opened_at, payload["openedAt"])
        self.assertEqual(IDENTITY_LINKAGE_PROVEN, payload["linkageStatus"])

    def test_partial_fills_preserve_first_open_time_and_exact_position_chain(self) -> None:
        _, state_path, service, trade = self._start(name="partial")
        first_fill_at = datetime.fromisoformat(trade.decision_timestamp).replace(
            second=2,
            microsecond=0,
        )
        partial = next(
            item
            for item in service.process_quote(
                quote(
                    first_fill_at.isoformat(),
                    bid=9.94,
                    ask=9.95,
                    available_size=1,
                ),
                received_at=first_fill_at,
            )
            if item.shadow_trade_id == trade.shadow_trade_id
        )
        self.assertEqual("partially_filled", partial.status)
        self.assertEqual(1, partial.position.quantity)
        self.assertEqual(first_fill_at.isoformat(), partial.position.opened_at)
        self.assertEqual(IDENTITY_LINKAGE_PROVEN, shadow_identity_linkage_status(partial))

        restarted = ShadowTradingService(
            store=ShadowStateStore(state_path),
            policy=self.policy,
        )
        second_fill_at = first_fill_at.replace(second=4)
        completed = next(
            item
            for item in restarted.process_quote(
                quote(
                    second_fill_at.isoformat(),
                    bid=9.94,
                    ask=9.95,
                    available_size=1,
                ),
                received_at=second_fill_at,
            )
            if item.shadow_trade_id == trade.shadow_trade_id
        )
        self.assertEqual("open", completed.status)
        self.assertEqual(2, completed.position.quantity)
        self.assertEqual(partial.position.position_id, completed.position.position_id)
        self.assertEqual(partial.position.opened_at, completed.position.opened_at)
        self.assertEqual(
            (
                completed.opportunity_id,
                completed.setup_id,
                completed.trade_plan_id,
            ),
            (
                completed.position.opportunity_id,
                completed.position.setup_id,
                completed.position.trade_plan_id,
            ),
        )

    def test_successor_report_cannot_rewrite_an_open_position(self) -> None:
        report_path, state_path, original = self._open(name="successor")
        successor = report_payload()
        bind_setup_identity(
            successor["candidates"][0],
            created_at=at("2026-07-23T10:05:00-05:00"),
            setup_sequence=2,
        )
        report_path.write_text(json.dumps(successor), encoding="utf-8")
        restored = ShadowStateStore(state_path).load().trades[0]
        self.assertEqual(original.setup_id, restored.setup_id)
        self.assertEqual(original.trade_plan_id, restored.trade_plan_id)
        self.assertEqual(original.position.position_id, restored.position.position_id)
        self.assertNotEqual(
            original.setup_id,
            successor["candidates"][0][REPORT_IDENTITY_FIELD]["setup_id"],
        )


if __name__ == "__main__":
    unittest.main()
