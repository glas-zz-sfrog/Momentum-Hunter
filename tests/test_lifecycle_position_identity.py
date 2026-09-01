from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest

from momentum_hunter.lifecycle_position_identity import (
    IDENTITY_LINKAGE_PROVEN,
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

    def _open(
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
        self.assertEqual("pending_entry", trade.status)
        updated = service.process_quote(
            quote(
                (decision_at.replace(second=0, microsecond=0)).isoformat(),
                bid=9.94,
                ask=9.95,
            ),
            received_at=decision_at.replace(second=0, microsecond=0),
        )
        # Same-timestamp quotes remain behind the prospective fill delay.
        if not updated or updated[0].position is None:
            fill_at = decision_at.replace(second=2, microsecond=0)
            updated = service.process_quote(
                quote(fill_at.isoformat(), bid=9.94, ask=9.95),
                received_at=fill_at,
            )
        opened = next(item for item in updated if item.shadow_trade_id == trade.shadow_trade_id)
        self.assertIsNotNone(opened.position)
        return report_path, state_path, opened

    def test_accepted_setup_to_tradeplan_to_position_exact_chain_passes(self) -> None:
        _, _, trade = self._open(name="exact")
        identity = authoritative_lifecycle_identity_from_report_row(
            trade.evidence.candidate_payload()
        )
        self.assertEqual(
            (identity.opportunity_id, identity.setup_id, identity.trade_plan_id),
            (trade.opportunity_id, trade.setup_id, trade.trade_plan_id),
        )
        self.assertEqual(
            (trade.opportunity_id, trade.setup_id, trade.trade_plan_id),
            (
                trade.position.opportunity_id,
                trade.position.setup_id,
                trade.position.trade_plan_id,
            ),
        )
        self.assertEqual(IDENTITY_LINKAGE_PROVEN, shadow_identity_linkage_status(trade))

    def test_two_setups_same_symbol_remain_distinct(self) -> None:
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
        self.assertNotEqual(first.position.position_id, second.position.position_id)
        self.assertEqual(first.setup_id, first.position.setup_id)
        self.assertEqual(second.setup_id, second.position.setup_id)

    def test_two_tradeplans_same_symbol_bind_the_exact_plan(self) -> None:
        first_payload = report_payload()
        second_payload = report_payload()
        bind_setup_identity(
            second_payload["candidates"][0],
            created_at=at("2026-07-23T10:03:00-05:00"),
            setup_sequence=2,
        )
        _, _, first = self._open(name="plan-1", payload=first_payload)
        _, _, second = self._open(
            name="plan-2",
            payload=second_payload,
            decision_at=at("2026-07-23T10:04:00-05:00"),
        )
        self.assertNotEqual(first.trade_plan_id, second.trade_plan_id)
        self.assertEqual(first.trade_plan_id, first.position.trade_plan_id)
        self.assertEqual(second.trade_plan_id, second.position.trade_plan_id)

    def test_legacy_position_without_setup_is_unknown(self) -> None:
        _, state_path, trade = self._open(name="legacy")
        legacy_position = replace(
            trade.position,
            opportunity_id="",
            setup_id="",
            trade_plan_id="",
        )
        legacy_trade = replace(
            trade,
            opportunity_id="",
            setup_id="",
            shadow_selection_id="",
            position=legacy_position,
        )
        ShadowStateStore(state_path).save(
            replace(ShadowStateStore(state_path).load(), trades=(legacy_trade,))
        )
        restored = ShadowStateStore(state_path).load().trades[0]
        self.assertEqual(IDENTITY_LINKAGE_UNKNOWN, shadow_identity_linkage_status(restored))

    def test_missing_tradeplan_id_has_no_active_linkage(self) -> None:
        _, state_path, trade = self._open(name="missing-plan")
        incomplete = replace(trade, position=replace(trade.position, trade_plan_id=""))
        self.assertEqual(IDENTITY_LINKAGE_UNKNOWN, shadow_identity_linkage_status(incomplete))
        with self.assertRaises(ShadowStateError):
            ShadowStateStore(state_path).save(
                replace(ShadowStateStore(state_path).load(), trades=(incomplete,))
            )

    def test_mismatched_setup_or_tradeplan_fails_closed(self) -> None:
        _, state_path, trade = self._open(name="mismatch")
        mismatched = replace(
            trade,
            position=replace(trade.position, setup_id="f" * 64),
        )
        with self.assertRaises(ShadowStateError):
            ShadowStateStore(state_path).save(
                replace(ShadowStateStore(state_path).load(), trades=(mismatched,))
            )

    def test_symbol_match_with_different_ids_never_joins(self) -> None:
        _, _, trade = self._open(name="symbol-only")
        same_symbol_wrong_identity = replace(
            trade,
            position=replace(trade.position, opportunity_id="e" * 64),
        )
        self.assertEqual(
            IDENTITY_LINKAGE_UNKNOWN,
            shadow_identity_linkage_status(same_symbol_wrong_identity),
        )

    def test_exact_ids_join_and_read_boundary_exposes_chronology(self) -> None:
        _, _, trade = self._open(name="read")
        payload = shadow_review_trade_to_dict(
            trade,
            audit_shadow_trade(trade),
            sample_definition=trade.sample_metadata,
        )
        self.assertEqual(IDENTITY_LINKAGE_PROVEN, payload["identityLinkage"])
        self.assertEqual(trade.opportunity_id, payload["opportunityId"])
        self.assertEqual(trade.setup_id, payload["setupId"])
        self.assertEqual(trade.trade_plan_id, payload["tradePlanId"])
        self.assertEqual(trade.position.position_id, payload["positionId"])
        self.assertEqual(trade.position.opened_at, payload["openedAt"])

    def test_opened_at_and_identity_chain_survive_restart(self) -> None:
        _, state_path, trade = self._open(name="restart")
        restored = ShadowStateStore(state_path).load().trades[0]
        self.assertEqual(trade.position.opened_at, restored.position.opened_at)
        self.assertEqual(
            (
                trade.opportunity_id,
                trade.setup_id,
                trade.trade_plan_id,
                trade.position.position_id,
            ),
            (
                restored.opportunity_id,
                restored.setup_id,
                restored.trade_plan_id,
                restored.position.position_id,
            ),
        )
        self.assertEqual(IDENTITY_LINKAGE_PROVEN, shadow_identity_linkage_status(restored))

    def test_position_id_is_immutable_across_read_refresh(self) -> None:
        _, state_path, trade = self._open(name="refresh")
        first = shadow_review_trade_to_dict(
            trade,
            audit_shadow_trade(trade),
            sample_definition=trade.sample_metadata,
        )
        restored = ShadowStateStore(state_path).load().trades[0]
        second = shadow_review_trade_to_dict(
            restored,
            audit_shadow_trade(restored),
            sample_definition=restored.sample_metadata,
        )
        self.assertEqual(first["positionId"], second["positionId"])
        tampered = replace(
            restored,
            position=replace(restored.position, position_id="shadow-position-wrong"),
        )
        self.assertEqual(
            IDENTITY_LINKAGE_UNKNOWN,
            shadow_identity_linkage_status(tampered),
        )

    def test_successor_setup_does_not_rewrite_open_position(self) -> None:
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

    def test_report_binding_rejects_plan_identity_tamper(self) -> None:
        row = report_payload()["candidates"][0]
        row[REPORT_IDENTITY_FIELD]["trade_plan_id"] = "a" * 64
        with self.assertRaises(LifecyclePositionIdentityError):
            authoritative_lifecycle_identity_from_report_row(row)


if __name__ == "__main__":
    unittest.main()
