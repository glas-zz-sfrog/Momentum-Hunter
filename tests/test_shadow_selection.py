from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.shadow_selection import (
    SELECTION_ALREADY_PROCESSED,
    SELECTION_CONSTITUTION_NOT_ARMED,
    SELECTION_NO_ELIGIBLE_CANDIDATE,
    SELECTION_NO_REPORT,
    SELECTION_REPORT_NOT_PROSPECTIVE,
    SELECTION_SAMPLE_INACTIVE,
    SELECTION_STARTED,
    AutomaticShadowSelector,
)
from momentum_hunter.shadow_trading import (
    SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
    ShadowStateStore,
    ShadowStateError,
    ShadowTradingService,
    audit_shadow_trade,
    expected_shadow_selection_policy_evidence,
    stable_id,
)
from momentum_hunter.workstation_shadow import (
    ShadowWorkspacePaths,
    ShadowWorkspaceService,
)
from tests.test_shadow_trading import report_payload


class AutomaticShadowSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selector_arm_patch = patch(
            "momentum_hunter.shadow_trading.SHADOW_AUTOMATIC_SELECTOR_ARMED",
            True,
        )
        self.selector_arm_patch.start()
        self.addCleanup(self.selector_arm_patch.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.report_path = (
            self.reports_dir / "trade-plan-briefing-2026-07-23-morning.json"
        )
        self.state_path = self.root / "shadow-state.json"
        self.service = ShadowTradingService(
            store=ShadowStateStore(self.state_path),
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def activate(self) -> None:
        with patch(
            "momentum_hunter.shadow_trading.now_central",
            return_value=at("2026-07-23T09:57:00-05:00"),
        ):
            self.service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
            )

    def write_report(
        self,
        payload: dict | None = None,
        *,
        path: Path | None = None,
    ) -> Path:
        target = path or self.report_path
        target.write_text(
            json.dumps(payload or report_payload()),
            encoding="utf-8",
        )
        return target

    def test_selects_first_clean_risk_approved_candidate_in_report_order(self) -> None:
        self.activate()
        payload = report_payload()
        blocked = copy.deepcopy(payload["candidates"][0])
        blocked["symbol"] = "BLOCK"
        blocked["trade_plan"]["bullish_stop"] = None
        clean = copy.deepcopy(payload["candidates"][0])
        payload["candidates"] = [blocked, clean]
        self.write_report(payload)
        source_before = self.report_path.read_bytes()

        result = AutomaticShadowSelector(self.service).select(
            self.report_path,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )

        self.assertEqual(SELECTION_STARTED, result.status)
        self.assertEqual("TEST", result.selected_symbol)
        self.assertEqual(2, result.selected_rank)
        self.assertEqual(2, result.candidates_evaluated)
        self.assertEqual(source_before, self.report_path.read_bytes())
        state = self.service.store.load()
        self.assertEqual(1, len(state.trades))
        trade = state.trades[0]
        self.assertEqual("COMPLETE", trade.data_quality_state)
        self.assertEqual("pending_entry", trade.status)
        self.assertEqual(
            hashlib.sha256(source_before).hexdigest(),
            trade.evidence.source_sha256,
        )
        expected_policy = expected_shadow_selection_policy_evidence()
        self.assertTrue(self.service.selection_policy_store.path.exists())
        self.assertEqual(
            expected_policy["selection_policy_version"],
            result.selection_policy_version,
        )
        self.assertEqual(
            "2026-07-23T10:00:00-05:00",
            result.selection_policy_recorded_at,
        )
        self.assertEqual(
            expected_policy["selection_policy_fingerprint"],
            result.selection_policy_fingerprint,
        )
        self.assertEqual(
            result.selection_policy_fingerprint,
            trade.selection_policy_fingerprint,
        )
        self.assertEqual(
            result.selection_policy_recorded_at,
            trade.selection_policy_recorded_at,
        )
        self.assertEqual(
            trade.selection_policy_recorded_at,
            trade.ticket.selection_policy_recorded_at,
        )
        self.assertEqual(
            trade.selection_policy_fingerprint,
            trade.ticket.selection_policy_fingerprint,
        )
        self.assertEqual(
            trade.selection_policy_fingerprint,
            trade.ledger_events[0].payload["selection_policy_fingerprint"],
        )
        self.assertEqual(
            trade.selection_policy_recorded_at,
            trade.ledger_events[0].payload["selection_policy_recorded_at"],
        )
        self.assertTrue(audit_shadow_trade(trade).passed)

    def test_repeat_and_non_report_command_cannot_create_second_trade_for_report(
        self,
    ) -> None:
        self.activate()
        self.write_report()
        selector = AutomaticShadowSelector(self.service)

        first = selector.select(
            self.report_path,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )
        repeated = selector.select(
            self.report_path,
            decision_at=at("2026-07-23T10:01:00-05:00"),
        )

        self.assertEqual(SELECTION_STARTED, first.status)
        self.assertEqual(SELECTION_ALREADY_PROCESSED, repeated.status)
        self.assertEqual(first.shadow_trade_id, repeated.shadow_trade_id)
        self.assertEqual(1, len(self.service.store.load().trades))
        with self.assertRaisesRegex(ValueError, "derived from the immutable source"):
            self.service.start_trade(
                self.report_path,
                symbol="TEST",
                simulation_command_id="alternate-command",
                decision_at=at("2026-07-23T10:02:00-05:00"),
                selection_policy_evidence=(
                    expected_shadow_selection_policy_evidence()
                ),
            )
        self.assertEqual(1, len(self.service.store.load().trades))

    def test_manual_official_start_without_policy_evidence_fails_closed(
        self,
    ) -> None:
        self.activate()
        self.write_report()
        self.service.freeze_automatic_selection_policy(
            recorded_at=at("2026-07-23T10:00:00-05:00"),
        )
        source_sha = hashlib.sha256(self.report_path.read_bytes()).hexdigest()

        with self.assertRaisesRegex(ValueError, "exact frozen automatic"):
            self.service.start_trade(
                self.report_path,
                symbol="TEST",
                simulation_command_id=stable_id(
                    "shadow-auto-report",
                    source_sha,
                ),
                decision_at=at("2026-07-23T10:00:00-05:00"),
            )

        self.assertFalse(self.state_path.exists())

    def test_policy_recorded_after_decision_cannot_start_trade(self) -> None:
        self.activate()
        self.write_report()
        self.service.freeze_automatic_selection_policy(
            recorded_at=at("2026-07-23T10:01:00-05:00"),
        )
        source_sha = hashlib.sha256(self.report_path.read_bytes()).hexdigest()

        with self.assertRaisesRegex(ValueError, "recorded after"):
            self.service.start_trade(
                self.report_path,
                symbol="TEST",
                simulation_command_id=stable_id(
                    "shadow-auto-report",
                    source_sha,
                ),
                decision_at=at("2026-07-23T10:00:00-05:00"),
                selection_policy_evidence=(
                    expected_shadow_selection_policy_evidence()
                ),
            )

        self.assertFalse(self.state_path.exists())

    def test_warning_bearing_or_risk_blocked_rows_create_no_trade(self) -> None:
        self.activate()
        payload = report_payload()
        warning_row = copy.deepcopy(payload["candidates"][0])
        warning_row["symbol"] = "WARN"
        warning_row["trade_plan"]["warnings"] = ["QUOTE_HTTP_401"]
        blocked_row = copy.deepcopy(payload["candidates"][0])
        blocked_row["symbol"] = "BLOCK"
        blocked_row["trade_plan"]["bullish_stop"] = None
        payload["candidates"] = [warning_row, blocked_row]
        self.write_report(payload)

        result = AutomaticShadowSelector(self.service).select(
            self.report_path,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )

        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, result.status)
        self.assertEqual(2, result.candidates_evaluated)
        self.assertFalse(self.state_path.exists())
        self.assertTrue(self.service.selection_policy_store.path.exists())

    def test_blank_symbol_is_skipped_before_a_later_clean_candidate(self) -> None:
        self.activate()
        payload = report_payload()
        blank = copy.deepcopy(payload["candidates"][0])
        blank["symbol"] = ""
        clean = copy.deepcopy(payload["candidates"][0])
        payload["candidates"] = [blank, clean]
        self.write_report(payload)

        result = AutomaticShadowSelector(self.service).select(
            self.report_path,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )

        self.assertEqual(SELECTION_STARTED, result.status)
        self.assertEqual("TEST", result.selected_symbol)
        self.assertEqual(2, result.selected_rank)

    def test_inactive_sample_and_missing_report_create_no_trade(self) -> None:
        self.write_report()
        inactive = AutomaticShadowSelector(self.service).select(
            self.report_path,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                self.root / "empty-reports",
                self.root / "observations.json",
                self.state_path,
            ),
            service=self.service,
        )
        no_report = workspace.select_automatic()

        self.assertEqual(SELECTION_SAMPLE_INACTIVE, inactive.status)
        self.assertEqual(SELECTION_NO_REPORT, no_report["status"])
        self.assertFalse(self.state_path.exists())

    def test_activated_sample_remains_fail_closed_when_constitution_is_not_armed(
        self,
    ) -> None:
        self.activate()
        self.write_report()

        with patch(
            "momentum_hunter.shadow_trading.SHADOW_AUTOMATIC_SELECTOR_ARMED",
            False,
        ):
            result = AutomaticShadowSelector(self.service).select(
                self.report_path,
                decision_at=at("2026-07-23T10:00:00-05:00"),
            )
            with self.assertRaisesRegex(
                ShadowStateError,
                "Constitution gates are incomplete",
            ):
                self.service.freeze_automatic_selection_policy(
                    recorded_at=at("2026-07-23T10:00:00-05:00"),
                )

        self.assertEqual(SELECTION_CONSTITUTION_NOT_ARMED, result.status)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.service.selection_policy_store.path.exists())

    def test_existing_policy_cannot_bypass_unarmed_official_trade_boundary(
        self,
    ) -> None:
        self.activate()
        self.write_report()
        decision_at = at("2026-07-23T10:00:00-05:00")
        self.service.freeze_automatic_selection_policy(
            recorded_at=decision_at,
        )
        source_sha = hashlib.sha256(self.report_path.read_bytes()).hexdigest()

        with patch(
            "momentum_hunter.shadow_trading.SHADOW_AUTOMATIC_SELECTOR_ARMED",
            False,
        ):
            with self.assertRaisesRegex(
                ShadowStateError,
                "Constitution gates are incomplete",
            ):
                self.service.start_trade(
                    self.report_path,
                    symbol="TEST",
                    simulation_command_id=stable_id(
                        "shadow-auto-report",
                        source_sha,
                    ),
                    decision_at=decision_at,
                    selection_policy_evidence=(
                        expected_shadow_selection_policy_evidence()
                    ),
                )

        self.assertFalse(self.state_path.exists())

    def test_new_source_report_may_create_one_additional_trade(self) -> None:
        self.activate()
        self.write_report()
        selector = AutomaticShadowSelector(self.service)
        first = selector.select(
            self.report_path,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )
        second_payload = report_payload()
        second_payload["metadata"]["source_capture_time"] = (
            "2026-07-23T10:04:00-05:00"
        )
        second_payload["metadata"]["generated_at"] = "2026-07-23T10:05:00-05:00"
        second_path = self.reports_dir / (
            "trade-plan-briefing-2026-07-23-evening.json"
        )
        self.write_report(second_payload, path=second_path)
        second = selector.select(
            second_path,
            decision_at=at("2026-07-23T10:06:00-05:00"),
        )

        self.assertEqual(SELECTION_STARTED, first.status)
        self.assertEqual(SELECTION_STARTED, second.status)
        self.assertNotEqual(first.report_sha256, second.report_sha256)
        self.assertEqual(2, len(self.service.store.load().trades))

    def test_expected_source_hash_mismatch_fails_before_state_write(self) -> None:
        self.activate()
        self.write_report()
        self.service.freeze_automatic_selection_policy(
            recorded_at=at("2026-07-23T10:00:00-05:00"),
        )
        source_sha = hashlib.sha256(self.report_path.read_bytes()).hexdigest()

        with self.assertRaisesRegex(ValueError, "changed after automatic"):
            self.service.start_trade(
                self.report_path,
                symbol="TEST",
                simulation_command_id=stable_id(
                    "shadow-auto-report",
                    source_sha,
                ),
                decision_at=at("2026-07-23T10:00:00-05:00"),
                expected_source_sha256="0" * 64,
                selection_policy_evidence=(
                    expected_shadow_selection_policy_evidence()
                ),
            )

        self.assertFalse(self.state_path.exists())

    def test_preactivation_report_is_rejected_without_state_write(self) -> None:
        self.activate()
        payload = report_payload()
        payload["metadata"]["source_capture_time"] = (
            "2026-07-23T09:55:00-05:00"
        )
        payload["metadata"]["generated_at"] = "2026-07-23T09:56:00-05:00"
        self.write_report(payload)

        result = AutomaticShadowSelector(self.service).select(
            self.report_path,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )

        self.assertEqual(SELECTION_REPORT_NOT_PROSPECTIVE, result.status)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.service.selection_policy_store.path.exists())

    def test_tampered_selection_policy_blocks_before_trade_state_write(
        self,
    ) -> None:
        self.activate()
        self.write_report()
        self.service.freeze_automatic_selection_policy(
            recorded_at=at("2026-07-23T10:00:00-05:00"),
        )
        policy_path = self.service.selection_policy_store.path
        payload = json.loads(policy_path.read_text(encoding="utf-8"))
        payload["selection_policy_fingerprint"] = "0" * 64
        policy_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ShadowStateError, "frozen automatic rule"):
            AutomaticShadowSelector(self.service).select(
                self.report_path,
                decision_at=at("2026-07-23T10:01:00-05:00"),
            )

        self.assertFalse(self.state_path.exists())

    def test_audit_rejects_tampered_embedded_selection_evidence(self) -> None:
        self.activate()
        self.write_report()
        AutomaticShadowSelector(self.service).select(
            self.report_path,
            decision_at=at("2026-07-23T10:00:00-05:00"),
        )
        trade = self.service.store.load().trades[0]

        tampered_policy = replace(
            trade,
            selection_policy_fingerprint="0" * 64,
        )
        tampered_command = replace(
            trade,
            simulation_command_id="manual-command",
        )
        future_policy = replace(
            trade,
            selection_policy_recorded_at="2026-07-23T10:01:00-05:00",
        )

        self.assertFalse(audit_shadow_trade(tampered_policy).passed)
        self.assertFalse(audit_shadow_trade(tampered_command).passed)
        self.assertFalse(audit_shadow_trade(future_policy).passed)

    def test_workspace_ignores_newer_mutable_event_report(self) -> None:
        self.activate()
        scheduled_payload = report_payload()
        self.write_report(scheduled_payload)
        event_payload = report_payload()
        event_payload["candidates"][0]["symbol"] = "EVENT"
        event_path = self.reports_dir / (
            "event-trade-plan-briefing-2026-07-23-live.json"
        )
        self.write_report(event_payload, path=event_path)
        scheduled_mtime = self.report_path.stat().st_mtime
        os.utime(event_path, (scheduled_mtime + 5, scheduled_mtime + 5))
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                self.reports_dir,
                self.root / "observations.json",
                self.state_path,
            ),
            service=self.service,
        )

        result = workspace.select_automatic()

        self.assertEqual(SELECTION_STARTED, result["status"])
        self.assertEqual("TEST", result["selectedSymbol"])
        self.assertEqual(str(self.report_path), result["reportPath"])
        self.assertFalse(result["transmitting"])
        self.assertEqual("UNAVAILABLE", result["orderTransmission"])


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
