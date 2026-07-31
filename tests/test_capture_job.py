from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from momentum_hunter.config import AppConfig
from momentum_hunter.market import MarketRegimeSnapshot
from momentum_hunter.models import CaptureSession, MarketRegime, TradingMode
from momentum_hunter.scheduling import SkipReason
from momentum_hunter.storage import file_sha256
from tools import capture_job


class CaptureJobTradePlanHandoffTests(unittest.TestCase):
    def test_opening_https_clock_preflight_accepts_bounded_exact_host_time(
        self,
    ) -> None:
        started = datetime(2026, 7, 31, 13, 35, 0, 100000, tzinfo=timezone.utc)
        received = started + timedelta(milliseconds=150)
        observed = iter((started, received))

        class Response:
            headers = {"Date": "Fri, 31 Jul 2026 13:35:00 GMT"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        proof = capture_job.verify_opening_https_clock(
            opener=lambda *_args, **_kwargs: Response(),
            utc_clock=lambda: next(observed),
        )

        self.assertEqual("PASS", proof["status"])
        self.assertEqual("finviz.com:https_date", proof["source"])

    def test_opening_https_clock_preflight_fails_closed_on_large_skew(
        self,
    ) -> None:
        started = datetime(2026, 7, 31, 13, 35, 10, tzinfo=timezone.utc)
        received = started + timedelta(milliseconds=100)
        observed = iter((started, received))

        class Response:
            headers = {"Date": "Fri, 31 Jul 2026 13:35:00 GMT"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with self.assertRaisesRegex(RuntimeError, "failed closed"):
            capture_job.verify_opening_https_clock(
                opener=lambda *_args, **_kwargs: Response(),
                utc_clock=lambda: next(observed),
            )

    def test_opening_capture_clock_failure_prevents_provider_contact(self) -> None:
        args = argparse.Namespace(provider="finviz", scanner=None)
        decision = capture_decision()

        with (
            patch.object(
                capture_job,
                "load_config",
                return_value=AppConfig(provider="finviz"),
            ),
            patch.object(capture_job, "now_central", return_value=decision.run_at),
            patch.object(
                capture_job,
                "evaluate_automatic_capture",
                return_value=decision,
            ),
            patch.object(
                capture_job,
                "verify_opening_https_clock",
                side_effect=RuntimeError("clock failed closed"),
            ),
            patch.object(capture_job, "provider_from_name") as provider_factory,
        ):
            with self.assertRaisesRegex(RuntimeError, "clock failed closed"):
                capture_job.run_capture_with_result(
                    args,
                    session=CaptureSession.OPENING,
                )

        provider_factory.assert_not_called()

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.captures_dir = self.root / "captures"
        self.reports_dir = self.root / "reports"
        self.capture_path = self.captures_dir / "2026-07-24" / "morning.json"
        self.capture_path.parent.mkdir(parents=True)
        self.capture_path.write_text(
            json.dumps(
                {
                    "capture_time": "2026-07-24T07:00:00-05:00",
                    "capture_date": "2026-07-24",
                    "session": "morning",
                    "mode": "paper",
                    "provider": "finviz",
                    "scanner": {"name": "Institutional Momentum"},
                    "scoring": {},
                    "market": {
                        "regime": "neutral",
                        "symbol": "SPY",
                        "reason": "test",
                    },
                    "candidates": [],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def shadow_args(self) -> argparse.Namespace:
        return argparse.Namespace(
            session=CaptureSession.SHADOW.value,
            provider="finviz",
            scanner="Institutional Momentum",
            trigger_shadow_selector=True,
            shadow_opening_proof_only=False,
            selector_proof_bundle=self.root / "selector-proof-bundle",
            task_definition=self.root / "shadow-task.xml",
        )

    def test_derived_trade_plan_report_is_write_once_and_does_not_mutate_capture(self) -> None:
        before = file_sha256(self.capture_path)

        first = capture_job.ensure_trade_planning_report(
            self.capture_path,
            reports_dir=self.reports_dir,
        )
        first_hashes = {name: file_sha256(path) for name, path in first.items()}
        second = capture_job.ensure_trade_planning_report(
            self.capture_path,
            reports_dir=self.reports_dir,
        )

        self.assertEqual(first, second)
        self.assertEqual(before, file_sha256(self.capture_path))
        self.assertEqual(first_hashes, {name: file_sha256(path) for name, path in second.items()})
        payload = json.loads(first["json"].read_text(encoding="utf-8"))
        self.assertEqual("2026-07-24T07:00:00-05:00", payload["metadata"]["source_capture_time"])
        self.assertEqual("morning", payload["metadata"]["source_session"])
        self.assertEqual([], payload["candidates"])

    def test_partial_derived_report_set_fails_without_touching_capture(self) -> None:
        expected = capture_job.trade_planning_report_paths(
            self.capture_path,
            reports_dir=self.reports_dir,
        )
        expected["json"].parent.mkdir(parents=True)
        expected["json"].write_text("{}", encoding="utf-8")
        before = file_sha256(self.capture_path)

        with self.assertRaisesRegex(RuntimeError, "partial derived TradePlan report"):
            capture_job.ensure_trade_planning_report(
                self.capture_path,
                reports_dir=self.reports_dir,
            )

        self.assertEqual(before, file_sha256(self.capture_path))
        self.assertFalse(expected["csv"].exists())
        self.assertFalse(expected["report"].exists())

    def test_invalid_or_offsetless_capture_time_fails_before_report_generation(self) -> None:
        payload = json.loads(self.capture_path.read_text(encoding="utf-8"))
        payload["capture_time"] = "2026-07-24T07:00:00"
        self.capture_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "offset-aware"):
            capture_job.trade_planning_report_paths(
                self.capture_path,
                reports_dir=self.reports_dir,
            )

    def test_invalid_capture_session_cannot_escape_report_directory(self) -> None:
        payload = json.loads(self.capture_path.read_text(encoding="utf-8"))
        payload["session"] = "../../outside"
        self.capture_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "valid session"):
            capture_job.trade_planning_report_paths(
                self.capture_path,
                reports_dir=self.reports_dir,
            )

    def test_shadow_capture_has_distinct_immutable_report_identity(self) -> None:
        payload = json.loads(self.capture_path.read_text(encoding="utf-8"))
        payload["capture_time"] = "2026-07-27T08:35:00-05:00"
        payload["capture_date"] = "2026-07-27"
        payload["session"] = "shadow"
        shadow_path = self.capture_path.with_name("shadow.json")
        shadow_path.write_text(json.dumps(payload), encoding="utf-8")

        paths = capture_job.trade_planning_report_paths(
            shadow_path,
            reports_dir=self.reports_dir,
        )

        self.assertEqual(
            "trade-plan-briefing-2026-07-27-shadow.json",
            paths["json"].name,
        )

    def test_existing_report_must_still_match_capture_identity_and_timing(self) -> None:
        paths = capture_job.ensure_trade_planning_report(
            self.capture_path,
            reports_dir=self.reports_dir,
        )
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        payload["metadata"]["source_session"] = "evening"
        paths["json"].write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "source capture session"):
            capture_job.ensure_trade_planning_report(
                self.capture_path,
                reports_dir=self.reports_dir,
            )

    def test_successful_scheduled_capture_creates_trade_plan_handoff(self) -> None:
        args = argparse.Namespace(provider="finviz", scanner=None)
        decision = capture_decision()
        provider = SimpleNamespace(name="finviz", scan=Mock(return_value=[]), fetch_news=Mock())
        report_paths = {
            "csv": self.reports_dir / "report.csv",
            "json": self.reports_dir / "report.json",
            "report": self.reports_dir / "report.md",
        }

        with (
            patch.object(capture_job, "load_config", return_value=AppConfig(provider="finviz")),
            patch.object(capture_job, "now_central", return_value=decision.run_at),
            patch.object(capture_job, "evaluate_automatic_capture", return_value=decision),
            patch.object(capture_job, "provider_from_name", return_value=provider),
            patch.object(
                capture_job,
                "detect_market_regime",
                return_value=MarketRegimeSnapshot(
                    regime=MarketRegime.NEUTRAL,
                    symbol="SPY",
                ),
            ),
            patch.object(capture_job, "score_candidates", return_value=[]),
            patch.object(
                capture_job,
                "save_daily_capture",
                return_value=(self.capture_path, self.capture_path.with_suffix(".md")),
            ),
            patch.object(
                capture_job,
                "ensure_trade_planning_report",
                return_value=report_paths,
            ) as ensure_report,
            patch.object(capture_job, "upsert_score_breakdowns_for_capture_payload"),
        ):
            result = capture_job.run_capture(args, session=CaptureSession.MORNING)

        self.assertEqual(0, result)
        ensure_report.assert_called_once_with(
            self.capture_path,
            expected_provider="finviz",
            expected_scanner="Institutional Momentum",
        )
        provider.scan.assert_called_once()
        provider.fetch_news.assert_not_called()

    def test_report_failure_does_not_prevent_existing_score_breakdown_update(self) -> None:
        args = argparse.Namespace(provider="finviz", scanner=None)
        decision = capture_decision()
        provider = SimpleNamespace(name="finviz", scan=Mock(return_value=[]), fetch_news=Mock())

        with (
            patch.object(capture_job, "load_config", return_value=AppConfig(provider="finviz")),
            patch.object(capture_job, "now_central", return_value=decision.run_at),
            patch.object(capture_job, "evaluate_automatic_capture", return_value=decision),
            patch(
                "momentum_hunter.storage.CAPTURE_INTEGRITY_MANIFEST",
                self.root / "capture-manifest.json",
            ),
            patch.object(capture_job, "provider_from_name", return_value=provider),
            patch.object(
                capture_job,
                "detect_market_regime",
                return_value=MarketRegimeSnapshot(
                    regime=MarketRegime.NEUTRAL,
                    symbol="SPY",
                ),
            ),
            patch.object(capture_job, "score_candidates", return_value=[]),
            patch.object(
                capture_job,
                "save_daily_capture",
                return_value=(self.capture_path, self.capture_path.with_suffix(".md")),
            ),
            patch.object(
                capture_job,
                "upsert_score_breakdowns_for_capture_payload",
            ) as update_breakdowns,
            patch.object(
                capture_job,
                "ensure_trade_planning_report",
                side_effect=RuntimeError("report handoff failed"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "report handoff failed"):
                capture_job.run_capture(args, session=CaptureSession.MORNING)

        update_breakdowns.assert_called_once()

    def test_duplicate_capture_recovers_missing_report_without_rescanning(self) -> None:
        args = argparse.Namespace(provider=None, scanner=None)
        decision = capture_decision(
            should_capture=False,
            skip_reason=SkipReason.SKIP_DUPLICATE_CAPTURE.value,
        )
        duplicate_path = (
            self.captures_dir
            / decision.run_at.date().isoformat()
            / f"{decision.capture_session.value}.json"
        )
        duplicate_path.parent.mkdir(parents=True, exist_ok=True)
        duplicate_path.write_text(self.capture_path.read_text(encoding="utf-8"), encoding="utf-8")

        with (
            patch.object(capture_job, "CAPTURES_DIR", self.captures_dir),
            patch.object(capture_job, "REPORTS_DIR", self.reports_dir),
            patch.object(capture_job, "load_config", return_value=AppConfig(provider="finviz")),
            patch.object(capture_job, "now_central", return_value=decision.run_at),
            patch.object(capture_job, "evaluate_automatic_capture", return_value=decision),
            patch.object(
                capture_job,
                "ensure_trade_planning_report",
                return_value={
                    "csv": self.reports_dir / "report.csv",
                    "json": self.reports_dir / "report.json",
                    "report": self.reports_dir / "report.md",
                },
            ) as ensure_report,
            patch.object(capture_job, "provider_from_name") as provider_factory,
        ):
            result = capture_job.run_capture_with_result(
                args,
                session=CaptureSession.MORNING,
            )

        self.assertEqual(0, result.exit_code)
        self.assertEqual("REPORT_RECOVERED", result.disposition)
        self.assertTrue(result.should_trigger_shadow_selector)
        ensure_report.assert_called_once_with(
            duplicate_path,
            expected_provider="finviz",
            expected_scanner="Institutional Momentum",
        )
        provider_factory.assert_not_called()

    def test_duplicate_capture_with_complete_report_does_not_trigger_selector(self) -> None:
        args = argparse.Namespace(provider=None, scanner=None)
        decision = capture_decision(
            should_capture=False,
            skip_reason=SkipReason.SKIP_DUPLICATE_CAPTURE.value,
        )
        duplicate_path = (
            self.captures_dir
            / decision.run_at.date().isoformat()
            / f"{decision.capture_session.value}.json"
        )
        duplicate_path.parent.mkdir(parents=True, exist_ok=True)
        duplicate_path.write_text(
            self.capture_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        expected = capture_job.trade_planning_report_paths(
            duplicate_path,
            reports_dir=self.reports_dir,
        )
        for path in expected.values():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("existing", encoding="utf-8")

        with (
            patch.object(capture_job, "CAPTURES_DIR", self.captures_dir),
            patch.object(capture_job, "REPORTS_DIR", self.reports_dir),
            patch.object(
                capture_job,
                "load_config",
                return_value=AppConfig(provider="finviz"),
            ),
            patch.object(
                capture_job,
                "now_central",
                return_value=decision.run_at,
            ),
            patch.object(
                capture_job,
                "evaluate_automatic_capture",
                return_value=decision,
            ),
            patch.object(capture_job, "ensure_raw_capture_artifacts"),
            patch.object(
                capture_job,
                "ensure_trade_planning_report",
                return_value=expected,
            ),
            patch.object(capture_job, "provider_from_name") as provider_factory,
        ):
            result = capture_job.run_capture_with_result(
                args,
                session=CaptureSession.MORNING,
            )

        self.assertEqual("DUPLICATE", result.disposition)
        self.assertFalse(result.should_trigger_shadow_selector)
        provider_factory.assert_not_called()

    def test_main_triggers_one_host_cycle_only_for_new_shadow_report(self) -> None:
        report_path = self.reports_dir / "trade-plan-briefing-shadow.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}", encoding="utf-8")
        args = self.shadow_args()
        run_result = capture_job.CaptureRunResult(
            exit_code=0,
            disposition="CAPTURED",
            report_paths={"json": report_path},
        )
        cycle = SimpleNamespace(
            code="COLLECTION_COMPLETED",
            summary="Background collection cycle completed.",
            snapshot={"hostInstanceId": "host-1"},
        )
        report_hash = file_sha256(report_path)

        with (
            patch.object(capture_job, "parse_args", return_value=args),
            patch.object(
                capture_job,
                "now_central",
                return_value=datetime.fromisoformat(
                    "2026-07-27T08:35:00-05:00"
                ),
            ),
            patch.object(
                capture_job,
                "run_capture_with_result",
                return_value=run_result,
            ),
            patch.object(
                capture_job,
                "ensure_shadow_engine_host_ready",
            ) as preflight,
            patch(
                "momentum_hunter.engine_host_client.run_immediate_collection_cycle",
                return_value=cycle,
            ) as run_cycle,
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "complete_shadow_selector_arm",
            ),
            patch.object(
                capture_job,
                "capture_identity",
                return_value="capture-1",
            ),
            patch.object(
                capture_job,
                "write_shadow_handoff_receipt",
            ) as write_receipt,
        ):
            exit_code = capture_job.main()

        self.assertEqual(0, exit_code)
        preflight.assert_called_once_with()
        run_cycle.assert_called_once_with(
            command_id=f"shadow-opening-capture-{report_hash}",
        )
        write_receipt.assert_called_once_with(
            report_path,
            report_hash=report_hash,
            capture_id="capture-1",
            cycle=cycle,
        )

    def test_main_does_not_trigger_host_cycle_for_duplicate_shadow_report(self) -> None:
        report_path = self.reports_dir / "trade-plan-briefing-shadow.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}", encoding="utf-8")
        args = self.shadow_args()
        run_result = capture_job.CaptureRunResult(
            exit_code=0,
            disposition="DUPLICATE",
            report_paths={"json": report_path},
        )

        with (
            patch.object(capture_job, "parse_args", return_value=args),
            patch.object(
                capture_job,
                "now_central",
                return_value=datetime.fromisoformat(
                    "2026-07-27T08:35:00-05:00"
                ),
            ),
            patch.object(
                capture_job,
                "run_capture_with_result",
                return_value=run_result,
            ),
            patch.object(
                capture_job,
                "shadow_handoff_is_complete",
                return_value=True,
            ),
            patch(
                "momentum_hunter.engine_host_client.run_immediate_collection_cycle",
            ) as run_cycle,
        ):
            exit_code = capture_job.main()

        self.assertEqual(0, exit_code)
        run_cycle.assert_not_called()

    def test_main_completes_arm_ceremony_before_selector_cycle(self) -> None:
        report_path = self.reports_dir / "trade-plan-briefing-shadow.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}", encoding="utf-8")
        bundle = self.root / "selector-proof-bundle"
        args = self.shadow_args()
        args.selector_proof_bundle = bundle
        run_result = capture_job.CaptureRunResult(
            exit_code=0,
            disposition="CAPTURED",
            report_paths={"json": report_path},
        )
        calls: list[str] = []
        ceremony = SimpleNamespace(state="ARMED", candidate="CRWV")
        cycle = SimpleNamespace(
            code="COLLECTION_COMPLETED",
            summary="Background collection cycle completed.",
            snapshot={"hostInstanceId": "host-1"},
        )

        with (
            patch.object(capture_job, "parse_args", return_value=args),
            patch.object(
                capture_job,
                "now_central",
                return_value=datetime.fromisoformat(
                    "2026-07-27T08:35:00-05:00"
                ),
            ),
            patch.object(
                capture_job,
                "run_capture_with_result",
                return_value=run_result,
            ),
            patch.object(
                capture_job,
                "ensure_shadow_engine_host_ready",
                side_effect=lambda: calls.append("preflight"),
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "complete_shadow_selector_arm",
                side_effect=lambda *_args, **_kwargs: (
                    calls.append("arm") or ceremony
                ),
            ) as arm_selector,
            patch(
                "momentum_hunter.engine_host_client."
                "run_immediate_collection_cycle",
                side_effect=lambda **_kwargs: (
                    calls.append("cycle") or cycle
                ),
            ),
            patch.object(
                capture_job,
                "write_shadow_handoff_receipt",
            ),
            patch.object(
                capture_job,
                "capture_identity",
                return_value="capture-1",
            ),
        ):
            exit_code = capture_job.main()

        self.assertEqual(0, exit_code)
        self.assertEqual(["preflight", "arm", "cycle"], calls)
        arm_selector.assert_called_once_with(
            bundle,
            report_path,
            task_definition_path=args.task_definition,
            expected_provider="finviz",
            expected_scanner="Institutional Momentum",
        )

    def test_proof_only_opening_never_arms_or_invokes_host_cycle(self) -> None:
        report_path = self.reports_dir / "trade-plan-briefing-shadow.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}", encoding="utf-8")
        args = self.shadow_args()
        args.shadow_opening_proof_only = True
        run_result = capture_job.CaptureRunResult(
            exit_code=0,
            disposition="CAPTURED",
            report_paths={"json": report_path},
        )
        ceremony = SimpleNamespace(
            state="PROOF_VERIFIED_UNARMED",
            candidate="CRWV",
        )

        with (
            patch.object(capture_job, "parse_args", return_value=args),
            patch.object(
                capture_job,
                "run_capture_with_result",
                return_value=run_result,
            ),
            patch.object(
                capture_job,
                "ensure_shadow_engine_host_ready",
            ) as preflight,
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "verify_shadow_opening_proof",
                return_value=ceremony,
            ) as verify_proof,
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "complete_shadow_selector_arm",
            ) as arm_selector,
            patch(
                "momentum_hunter.engine_host_client."
                "run_immediate_collection_cycle",
            ) as run_cycle,
            patch.object(
                capture_job,
                "write_shadow_handoff_receipt",
            ) as write_receipt,
        ):
            exit_code = capture_job.main()

        self.assertEqual(0, exit_code)
        verify_proof.assert_called_once_with(
            args.selector_proof_bundle,
            report_path,
            task_definition_path=args.task_definition,
            expected_provider="finviz",
            expected_scanner="Institutional Momentum",
        )
        arm_selector.assert_not_called()
        preflight.assert_not_called()
        run_cycle.assert_not_called()
        write_receipt.assert_not_called()

    def test_duplicate_shadow_report_retries_when_receipt_is_missing(self) -> None:
        report_path = self.reports_dir / "trade-plan-briefing-shadow.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}", encoding="utf-8")
        args = self.shadow_args()
        run_result = capture_job.CaptureRunResult(
            exit_code=0,
            disposition="DUPLICATE",
            report_paths={"json": report_path},
        )
        cycle = SimpleNamespace(
            code="COLLECTION_COMPLETED",
            summary="Background collection cycle completed.",
            snapshot={"hostInstanceId": "host-1"},
        )

        with (
            patch.object(capture_job, "parse_args", return_value=args),
            patch.object(
                capture_job,
                "now_central",
                return_value=datetime.fromisoformat(
                    "2026-07-27T08:36:00-05:00"
                ),
            ),
            patch.object(
                capture_job,
                "run_capture_with_result",
                return_value=run_result,
            ),
            patch.object(
                capture_job,
                "shadow_handoff_is_complete",
                return_value=False,
            ),
            patch.object(
                capture_job,
                "ensure_shadow_engine_host_ready",
            ) as preflight,
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "complete_shadow_selector_arm",
            ),
            patch.object(
                capture_job,
                "capture_identity",
                return_value="capture-1",
            ),
            patch(
                "momentum_hunter.engine_host_client.run_immediate_collection_cycle",
                return_value=cycle,
            ) as run_cycle,
            patch.object(
                capture_job,
                "write_shadow_handoff_receipt",
            ) as write_receipt,
        ):
            exit_code = capture_job.main()

        self.assertEqual(0, exit_code)
        preflight.assert_called_once_with()
        run_cycle.assert_called_once()
        write_receipt.assert_called_once()

    def test_shadow_handoff_receipt_is_write_once_and_report_bound(self) -> None:
        report_path = self.reports_dir / "trade-plan-briefing-shadow.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text('{"report": 1}', encoding="utf-8")
        handoffs_dir = self.root / "handoffs"
        report_hash = file_sha256(report_path)
        cycle = SimpleNamespace(
            accepted=True,
            code="COLLECTION_COMPLETED",
            command_id=f"shadow-opening-capture-{report_hash}",
            payload={
                "shadowAutomaticSelection": {
                    "status": "NO_ELIGIBLE_CANDIDATE",
                    "reportSha256": report_hash,
                    "decisionCycleId": "cycle-1",
                    "shadowTradeId": None,
                }
            },
            snapshot={
                "identity": {
                    "hostInstanceId": "host-1",
                    "processId": 123,
                    "protocolVersion": "1",
                    "transport": "loopback-tcp",
                },
                "collection": {
                    "lastCompletedCycleAtUtc": (
                        "2026-07-27T13:35:02+00:00"
                    )
                },
            },
        )

        first = capture_job.write_shadow_handoff_receipt(
            report_path,
            report_hash=report_hash,
            capture_id="capture-1",
            cycle=cycle,
            handoffs_dir=handoffs_dir,
        )
        second = capture_job.write_shadow_handoff_receipt(
            report_path,
            report_hash=report_hash,
            capture_id="capture-1",
            cycle=cycle,
            handoffs_dir=handoffs_dir,
        )

        self.assertEqual(first, second)
        self.assertTrue(
            capture_job.shadow_handoff_is_complete(
                report_path,
                handoffs_dir=handoffs_dir,
            )
        )
        report_path.write_text('{"report": 2}', encoding="utf-8")
        self.assertFalse(
            capture_job.shadow_handoff_is_complete(
                report_path,
                handoffs_dir=handoffs_dir,
            )
        )
        replacement_hash = file_sha256(report_path)
        replacement_cycle = SimpleNamespace(
            **{
                **cycle.__dict__,
                "payload": {
                    "shadowAutomaticSelection": {
                        **cycle.payload["shadowAutomaticSelection"],
                        "reportSha256": replacement_hash,
                    }
                },
            }
        )
        replacement = capture_job.write_shadow_handoff_receipt(
            report_path,
            report_hash=replacement_hash,
            capture_id="capture-2",
            cycle=replacement_cycle,
            handoffs_dir=handoffs_dir,
        )
        self.assertEqual(first, replacement)
        self.assertTrue(
            capture_job.shadow_handoff_is_complete(
                report_path,
                handoffs_dir=handoffs_dir,
            )
        )
        self.assertEqual(
            1,
            len(tuple(handoffs_dir.glob("*.incomplete-*.json"))),
        )

    def test_nonmarket_skip_does_not_generate_report_or_contact_provider(self) -> None:
        args = argparse.Namespace(provider=None, scanner=None)
        decision = capture_decision(
            should_capture=False,
            skip_reason=SkipReason.SKIP_NOT_MARKET_DAY.value,
        )

        with (
            patch.object(capture_job, "load_config", return_value=AppConfig(provider="finviz")),
            patch.object(capture_job, "now_central", return_value=decision.run_at),
            patch.object(capture_job, "evaluate_automatic_capture", return_value=decision),
            patch.object(capture_job, "ensure_trade_planning_report") as ensure_report,
            patch.object(capture_job, "provider_from_name") as provider_factory,
        ):
            result = capture_job.run_capture(args, session=CaptureSession.MORNING)

        self.assertEqual(0, result)
        ensure_report.assert_not_called()
        provider_factory.assert_not_called()

    def test_trade_plan_builder_requests_existing_read_only_market_inputs(self) -> None:
        expected = capture_job.trade_planning_report_paths(
            self.capture_path,
            reports_dir=self.reports_dir,
        )
        report = SimpleNamespace(
            source_capture_time="2026-07-24T07:00:00-05:00",
            source_session="morning",
            event_mode=False,
        )

        with (
            patch.object(capture_job, "now_central", return_value=datetime.fromisoformat("2026-07-24T07:05:00-05:00")),
            patch.object(capture_job, "build_trade_planning_report", return_value=report) as build,
            patch.object(capture_job, "export_trade_planning_report", return_value=expected),
            patch.object(capture_job, "validate_trade_planning_report"),
        ):
            actual = capture_job.ensure_trade_planning_report(
                self.capture_path,
                reports_dir=self.reports_dir,
            )

        self.assertEqual(expected, actual)
        build.assert_called_once_with(
            self.capture_path,
            fetch_bars=True,
            fetch_market_data=True,
            as_of=datetime.fromisoformat("2026-07-24T07:05:00-05:00"),
        )

    def test_windows_task_wires_distinct_shadow_opening_capture(self) -> None:
        project_root = Path(capture_job.__file__).resolve().parents[1]
        installer = (
            project_root / "tools" / "install_capture_tasks.ps1"
        ).read_text(encoding="utf-8")
        runner = (
            project_root / "tools" / "run_capture_job.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("Momentum Hunter Shadow Opening Capture", installer)
        self.assertIn('[string]$ShadowTime = "08:35"', installer)
        self.assertIn('-Session "shadow"', installer)
        self.assertIn("rev-parse --short=7 HEAD", installer)
        self.assertIn("-SelectorProofBundle", installer)
        self.assertNotIn('$settingsArguments["RestartCount"]', installer)
        self.assertNotIn('$settingsArguments["RestartInterval"]', installer)
        self.assertIn("Export-ScheduledTask", installer)
        self.assertIn("[switch]$EnableShadowTask", installer)
        self.assertIn("[switch]$ShadowOnly", installer)
        self.assertIn("[switch]$PlanOnly", installer)
        self.assertIn("New-ScheduledTaskTrigger -Once -At $ShadowRunAt", installer)
        self.assertIn(
            "An armed Shadow task must use an explicit one-time -ShadowRunAt value.",
            installer,
        )
        self.assertIn(
            "An armed Shadow task must be installed with -ShadowOnly.",
            installer,
        )
        self.assertIn(
            "An armed Shadow task must be explicitly enabled with -EnableShadowTask.",
            installer,
        )
        self.assertIn(
            "requires the Windows Central Standard Time zone",
            installer,
        )
        self.assertIn(
            "must use the limited interactive Windows principal",
            installer,
        )
        self.assertIn("Disable-ScheduledTask", installer)
        self.assertIn('-Provider `"$Provider`"', installer)
        self.assertIn('-Scanner `"$Scanner`"', installer)
        self.assertIn('"shadow"', runner)
        self.assertIn("--trigger-shadow-selector", runner)
        self.assertIn("--selector-proof-bundle", runner)
        self.assertIn("--task-definition", runner)
        self.assertIn("--shadow-opening-proof-only", runner)
        self.assertIn("$retryableInfrastructureExit = 75", runner)
        self.assertIn("$ShadowRetryCount = 3", runner)
        self.assertIn("openingResultPreserved", runner)

    def test_armed_shadow_installer_plans_one_future_task_only(self) -> None:
        result = self.run_installer_plan(
            "-ShadowOnly",
            "-ShadowRunAt",
            "2099-07-29T08:35:00-05:00",
            "-EnableShadowTask",
            "-ArmShadowSelector",
        )

        self.assertEqual(0, result.returncode, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual("Momentum Hunter Shadow Opening Capture", plan["taskName"])
        self.assertEqual("shadow", plan["session"])
        self.assertEqual("ONCE", plan["triggerKind"])
        self.assertTrue(plan["runAt"].startswith("2099-07-29T08:35:00"))
        self.assertTrue(plan["enabled"])
        self.assertTrue(plan["armShadowSelector"])
        self.assertFalse(plan["startWhenAvailable"])
        self.assertEqual(0, plan["schedulerRestartCount"])
        self.assertEqual(4, plan["runnerOwnedMaximumAttempts"])
        self.assertEqual("Central Standard Time", plan["requiredWindowsTimeZone"])
        self.assertIn("-ArmShadowSelector", plan["arguments"])
        self.assertNotIn("-Session morning", plan["arguments"])
        self.assertNotIn("-Session evening", plan["arguments"])

    def test_default_installer_plan_preserves_three_daily_unarmed_tasks(
        self,
    ) -> None:
        result = self.run_installer_plan()

        self.assertEqual(0, result.returncode, result.stderr)
        plans = json.loads(result.stdout)
        self.assertEqual(
            ["morning", "shadow", "evening"],
            [plan["session"] for plan in plans],
        )
        self.assertTrue(all(plan["triggerKind"] == "DAILY" for plan in plans))
        self.assertTrue(all(plan["startWhenAvailable"] for plan in plans))
        shadow = plans[1]
        self.assertFalse(shadow["enabled"])
        self.assertFalse(shadow["armShadowSelector"])
        self.assertNotIn("-ArmShadowSelector", shadow["arguments"])

    def test_armed_shadow_installer_rejects_unsafe_shapes_before_registration(
        self,
    ) -> None:
        cases = (
            (
                (
                    "-ShadowRunAt",
                    "2099-07-29T08:35:00-05:00",
                    "-EnableShadowTask",
                    "-ArmShadowSelector",
                ),
                "-ShadowOnly",
            ),
            (
                (
                    "-ShadowOnly",
                    "-EnableShadowTask",
                    "-ArmShadowSelector",
                ),
                "one-time -ShadowRunAt",
            ),
            (
                (
                    "-ShadowOnly",
                    "-ShadowRunAt",
                    "2099-07-29T08:35:00-05:00",
                    "-ArmShadowSelector",
                ),
                "-EnableShadowTask",
            ),
            (
                (
                    "-ShadowRunAt",
                    "2099-07-29T08:35:00-05:00",
                ),
                "may only be used with -ShadowOnly",
            ),
            (
                (
                    "-ShadowOnly",
                    "-ShadowRunAt",
                    "2020-07-29T08:35:00-05:00",
                ),
                "scheduled in the future",
            ),
            (
                (
                    "-ShadowOnly",
                    "-ShadowRunAt",
                    "2099-07-29T08:36:00-05:00",
                    "-EnableShadowTask",
                    "-ArmShadowSelector",
                ),
                "exactly 08:35:00 local Central time",
            ),
            (
                (
                    "-ShadowOnly",
                    "-ShadowRunAt",
                    "2099-07-29T08:35:00-05:00",
                    "-EnableShadowTask",
                    "-ArmShadowSelector",
                    "-RunWhetherLoggedOn",
                ),
                "limited interactive Windows principal",
            ),
        )

        for arguments, expected in cases:
            with self.subTest(arguments=arguments):
                result = self.run_installer_plan(*arguments)
                self.assertNotEqual(0, result.returncode)
                self.assertIn(expected, result.stderr + result.stdout)

    def run_installer_plan(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        project_root = Path(capture_job.__file__).resolve().parents[1]
        installer = project_root / "tools" / "install_capture_tasks.ps1"
        selector_proof = self.root / "selector-proof-installer-plan"
        selector_proof.mkdir(exist_ok=True)
        return subprocess.run(
            (
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(installer),
                "-ProjectRoot",
                str(project_root),
                "-PythonExe",
                sys.executable,
                "-SelectorProofBundle",
                str(selector_proof),
                "-PlanOnly",
                *arguments,
            ),
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )


class ShadowOpeningRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.tools_dir = self.root / "tools"
        self.tools_dir.mkdir()
        self.task_definition = self.root / "shadow-task.xml"
        self.task_definition.write_text("<Task />\n", encoding="utf-8")
        self.selector_proof = self.root / "selector-proof"
        self.selector_proof.mkdir()
        self.runner = (
            Path(capture_job.__file__).resolve().parents[1]
            / "tools"
            / "run_capture_job.ps1"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_three_retries_preserve_one_opening_identity_and_artifact_set(
        self,
    ) -> None:
        (self.tools_dir / "capture_job.py").write_text(
            "\n".join(
                (
                    "import json",
                    "import sys",
                    "from pathlib import Path",
                    "root = Path(__file__).resolve().parents[1]",
                    "counter = root / 'opening-attempts.txt'",
                    "attempt = int(counter.read_text() or '0') + 1 if counter.exists() else 1",
                    "counter.write_text(str(attempt))",
                    "identity = root / 'opening-identity.txt'",
                    "expected = 'stable-capture-report-command-cycle'",
                    "if identity.exists() and identity.read_text() != expected:",
                    "    raise SystemExit(91)",
                    "identity.write_text(expected)",
                    "if attempt <= 3:",
                    "    raise SystemExit(75)",
                    "evidence = root / 'opening-evidence'",
                    "evidence.mkdir(exist_ok=True)",
                    "for name in ('report.json', 'handoff.json', 'cycle.json', 'trade.json'):",
                    "    path = evidence / name",
                    "    if path.exists():",
                    "        raise SystemExit(92)",
                    "    path.write_text(expected)",
                    "raise SystemExit(0)",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (self.tools_dir / "update_outcomes.py").write_text(
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )

        result = self.run_runner()

        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(
            "4",
            (self.root / "opening-attempts.txt").read_text(encoding="utf-8"),
        )
        evidence = self.root / "opening-evidence"
        self.assertEqual(
            ["cycle.json", "handoff.json", "report.json", "trade.json"],
            sorted(path.name for path in evidence.iterdir()),
        )
        self.assertTrue(
            all(
                path.read_text(encoding="utf-8")
                == "stable-capture-report-command-cycle"
                for path in evidence.iterdir()
            )
        )

    def test_outcome_failure_cannot_make_completed_opening_retryable(
        self,
    ) -> None:
        (self.tools_dir / "capture_job.py").write_text(
            "\n".join(
                (
                    "from pathlib import Path",
                    "root = Path(__file__).resolve().parents[1]",
                    "counter = root / 'opening-attempts.txt'",
                    "attempt = int(counter.read_text() or '0') + 1 if counter.exists() else 1",
                    "counter.write_text(str(attempt))",
                    "(root / 'opening-complete.txt').write_text('complete')",
                    "raise SystemExit(0)",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (self.tools_dir / "update_outcomes.py").write_text(
            "raise SystemExit(9)\n",
            encoding="utf-8",
        )

        result = self.run_runner()

        self.assertEqual(0, result.returncode, result.stdout)
        self.assertEqual(
            "1",
            (self.root / "opening-attempts.txt").read_text(encoding="utf-8"),
        )
        self.assertTrue((self.root / "opening-complete.txt").is_file())
        logs = tuple((self.root / "MomentumHunterData" / "logs").glob("capture-shadow-*.log"))
        self.assertEqual(1, len(logs))
        self.assertIn(
            "no opening retry will occur",
            logs[0].read_text(encoding="utf-16"),
        )

    def test_retryable_stderr_is_logged_without_bypassing_retries(self) -> None:
        (self.tools_dir / "capture_job.py").write_text(
            "\n".join(
                (
                    "import sys",
                    "from pathlib import Path",
                    "root = Path(__file__).resolve().parents[1]",
                    "counter = root / 'opening-attempts.txt'",
                    "attempt = int(counter.read_text() or '0') + 1 if counter.exists() else 1",
                    "counter.write_text(str(attempt))",
                    "if attempt <= 3:",
                    "    print('temporary provider failure', file=sys.stderr)",
                    "    raise SystemExit(75)",
                    "raise SystemExit(0)",
                    "",
                )
            ),
            encoding="utf-8",
        )
        (self.tools_dir / "update_outcomes.py").write_text(
            "raise SystemExit(0)\n",
            encoding="utf-8",
        )

        result = self.run_runner()

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            "4",
            (self.root / "opening-attempts.txt").read_text(encoding="utf-8"),
        )
        logs = tuple(
            (self.root / "MomentumHunterData" / "logs").glob(
                "capture-shadow-*.log"
            )
        )
        self.assertEqual(1, len(logs))
        text = logs[0].read_text(encoding="utf-16")
        self.assertEqual(3, text.count("OpeningAttemptExitCode: 75"))
        self.assertIn("OpeningAttemptExitCode: 0", text)
        self.assertIn("ExitCode: 0", text)
        self.assertNotIn("NativeCommandError", text)

    def run_runner(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(self.runner),
                "-Session",
                "shadow",
                "-ProjectRoot",
                str(self.root),
                "-PythonExe",
                sys.executable,
                "-SelectorProofBundle",
                str(self.selector_proof),
                "-TaskDefinitionPath",
                str(self.task_definition),
                "-ShadowRetryDelaySeconds",
                "0",
            ),
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )


def capture_decision(
    *,
    should_capture: bool = True,
    skip_reason: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        should_capture=should_capture,
        is_skip=not should_capture,
        skip_reason=skip_reason,
        requested_session=CaptureSession.MORNING,
        capture_session=CaptureSession.MORNING,
        run_at=datetime.fromisoformat("2026-07-24T07:00:00-05:00"),
        classification=SimpleNamespace(
            capture_calendar_status="MARKET_OPEN_DAY",
            next_market_session_date="2026-07-24",
            scheduling_policy_version="market-calendar-v1",
        ),
    )


if __name__ == "__main__":
    unittest.main()
