from __future__ import annotations

import csv
import json
import shutil
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.outcomes import OUTCOME_FIELDNAMES
from momentum_hunter.replay import (
    OUTCOME_LABEL,
    RAW_CAPTURE,
    REPLAY_BANNER,
    REVIEW_DECISION,
    build_candidate_timeline,
    build_replay_view_model,
)
from momentum_hunter.review import CandidateIdentity, ReviewDecision, ReviewStatus, make_capture_id, save_review_decisions
from momentum_hunter.score_breakdowns import SCORE_ENGINE_VERSION, build_score_breakdown_for_raw_candidate, score_breakdown_identity_key
from momentum_hunter.storage import file_sha256, save_capture_integrity_manifest
from momentum_hunter.time_utils import CENTRAL_TZ


class ReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / "_test_replay"
        shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True)
        self.captures_dir = self.root / "captures"
        self.quarantine_dir = self.root / "quarantine" / "raw-captures" / "20260606-120000"
        self.manifest_path = self.root / "integrity" / "capture_manifest.json"
        self.score_path = self.root / "score-breakdowns.json"
        self.review_path = self.root / "review-decisions.json"
        self.outcomes_csv = self.root / "analysis-outcomes.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_timeline_orders_multiple_sessions_and_classifies_sources(self) -> None:
        morning = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        evening = capture_payload("2026-06-05T19:00:00-05:00", "evening", "Institutional Momentum", price=84.0, score=94)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", morning)
        write_capture(self.captures_dir / "2026-06-05" / "evening.json", evening)
        write_score_store(self.score_path, [morning, evening])
        write_review_decision(self.review_path, morning, "COO")
        write_outcomes(self.outcomes_csv, morning, "COO")

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(["morning", "evening"], [row.session for row in rows])
        self.assertEqual(["Base Momentum", "Institutional Momentum"], [row.scanner for row in rows])
        self.assertIn("2026", rows[0].capture_time_text)
        self.assertEqual(RAW_CAPTURE, rows[0].fields["price"].source)
        self.assertEqual(REVIEW_DECISION, rows[0].fields["review_status"].source)
        self.assertEqual(OUTCOME_LABEL, rows[0].fields["next_day_return_pct"].source)
        self.assertEqual("bull", rows[0].fields["market_regime"].value)
        self.assertEqual(SCORE_ENGINE_VERSION, rows[0].fields["score_engine_version"].value)
        self.assertIn(rows[0].fields["score_breakdown_status"].value, {"complete", "legacy"})
        self.assertEqual("watchlist", rows[0].fields["review_status"].value)
        self.assertEqual("3.2500", rows[0].fields["next_day_return_pct"].value)

        newest = build_candidate_timeline(
            "COO",
            newest_first=True,
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertEqual(["evening", "morning"], [row.session for row in newest])

    def test_replay_view_model_uses_stored_score_breakdown_statuses(self) -> None:
        complete = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=100)
        legacy = capture_payload("2026-06-05T19:00:00-05:00", "evening", "Base Momentum", price=83.0, score=1)
        incomplete = capture_payload("2026-06-08T07:00:00-05:00", "morning", "Institutional Momentum", price=85.0, score=96)
        incomplete["candidates"][0].pop("score_profile")
        incomplete["candidates"][0].pop("relative_volume")
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", complete)
        write_capture(self.captures_dir / "2026-06-05" / "evening.json", legacy)
        write_capture(self.captures_dir / "2026-06-08" / "morning.json", incomplete)
        write_score_store(self.score_path, [complete, legacy, incomplete])

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        statuses = [row.score_breakdown["status"] for row in rows]
        self.assertIn("complete", statuses)
        self.assertIn("legacy", statuses)
        self.assertIn("incomplete", statuses)
        self.assertTrue(any("Score breakdown is legacy" in row.warnings for row in rows))
        self.assertTrue(any("Score breakdown is incomplete" in row.warnings for row in rows))
        view_model = build_replay_view_model(rows[0])
        self.assertTrue(view_model.read_only)
        self.assertEqual(REPLAY_BANNER, view_model.banner)

    def test_missing_score_breakdown_and_duplicate_identity_warnings(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)
        duplicate = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertEqual(["Missing stored score breakdown", "Missing later outcome label"], duplicate[0].warnings)

        payload["candidates"].append(dict(payload["candidates"][0]))
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)
        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertTrue(all("Duplicate replay identity" in row.warnings for row in rows))

    def test_timeline_marks_legacy_zero_relative_volume_as_unavailable(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        payload["candidates"][0]["relative_volume"] = 0.0
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual("N/A (legacy zero)", rows[0].fields["relative_volume"].value)
        self.assertIn("Relative volume unavailable in raw capture - displayed as N/A, not 0.0", rows[0].warnings)

    def test_timeline_warns_on_repeated_signal_fingerprint_across_captures(self) -> None:
        first = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        second = capture_payload("2026-06-05T19:00:00-05:00", "evening", "Base Momentum", price=82.0, score=90)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", first)
        write_capture(self.captures_dir / "2026-06-05" / "evening.json", second)

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(2, len(rows))
        self.assertTrue(
            all("Repeated signal fingerprint across captures - timestamp distinguishes this row" in row.warnings for row in rows)
        )
        self.assertNotEqual(rows[0].capture_time_text, rows[1].capture_time_text)

    def test_quarantined_captures_are_excluded_by_default_and_warn_when_visible(self) -> None:
        active = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        quarantined = capture_payload("2026-06-06T07:00:00-05:00", "morning", "Base Momentum", price=88.0, score=91)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", active)
        quarantine_path = self.quarantine_dir / "2026-06-06-morning.json"
        write_capture(quarantine_path, quarantined)
        save_capture_integrity_manifest(
            {
                "schema_version": 2,
                "records": {},
                "quarantined_records": {
                    "captures/2026-06-06/morning.json": {
                        "kind": "raw_capture_json",
                        "capture_date": "2026-06-06",
                        "session": "morning",
                        "provider": "finviz",
                        "scanner": "Base Momentum",
                        "quarantine_path": quarantine_path.resolve().as_posix(),
                    }
                },
            },
            self.manifest_path,
        )

        default_rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertEqual(1, len(default_rows))

        visible_rows = build_candidate_timeline(
            "COO",
            include_quarantined=True,
            include_non_trading_day=True,
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        self.assertEqual(2, len(visible_rows))
        quarantined_rows = [row for row in visible_rows if row.quarantined]
        self.assertEqual("Quarantined - Not Trusted for Study Use", quarantined_rows[0].trust_label)
        self.assertIn("Quarantined - Not Trusted for Study Use", quarantined_rows[0].warnings)

    def test_non_trading_day_rows_are_hidden_by_default_and_preopen_is_labeled(self) -> None:
        market_day = capture_payload("2026-06-08T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        weekend = capture_payload("2026-06-06T07:00:00-05:00", "morning", "Base Momentum", price=83.0, score=91)
        preopen = capture_payload("2026-06-07T19:00:00-05:00", "preopen", "Base Momentum", price=84.0, score=92)
        manual = capture_payload("2026-06-08T10:00:00-05:00", "manual", "Base Momentum", price=85.0, score=93)
        write_capture(self.captures_dir / "2026-06-08" / "morning.json", market_day)
        write_capture(self.captures_dir / "2026-06-06" / "morning.json", weekend)
        write_capture(self.captures_dir / "2026-06-07" / "preopen.json", preopen)
        write_capture(self.captures_dir / "2026-06-08" / "manual.json", manual)

        default_rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        all_rows = build_candidate_timeline(
            "COO",
            include_non_trading_day=True,
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(["preopen", "morning"], [row.session for row in default_rows])
        self.assertEqual("Pre-Open Gap Review", default_rows[0].calendar_label)
        self.assertEqual(4, len(all_rows))
        weekend_rows = [row for row in all_rows if row.capture_date == "2026-06-06"]
        self.assertEqual("Non-Trading-Day Observation", weekend_rows[0].calendar_label)
        self.assertTrue(weekend_rows[0].is_ordinary_non_trading_day)
        manual_rows = [row for row in all_rows if row.session == "manual"]
        self.assertEqual("Non-Study-Eligible Observation", manual_rows[0].trust_label)
        self.assertTrue(manual_rows[0].is_ordinary_non_trading_day)

    def test_replay_does_not_mutate_raw_capture_or_recalculate_scores(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        capture_path = self.captures_dir / "2026-06-05" / "morning.json"
        write_capture(capture_path, payload)
        records = {}
        record = build_score_breakdown_for_raw_candidate(payload, payload["candidates"][0])
        record["final_score"] = 12
        record["computed_final_score"] = 12
        record["status"] = "complete"
        records[record["identity_key"]] = record
        self.score_path.write_text(
            json.dumps({"schema_version": 1, "score_engine_version": SCORE_ENGINE_VERSION, "records": records}, indent=2),
            encoding="utf-8",
        )
        before_hash = file_sha256(capture_path)

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        view_model = build_replay_view_model(rows[0])
        after_hash = file_sha256(capture_path)

        self.assertEqual(before_hash, after_hash)
        self.assertTrue(view_model.read_only)
        self.assertEqual(90, rows[0].fields["score"].value)
        self.assertEqual(12, view_model.score_breakdown["final_score"])

    def test_missing_derived_data_is_warned_not_invented(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertIsNone(rows[0].score_breakdown)
        self.assertIsNone(rows[0].outcome)
        self.assertEqual("missing", rows[0].fields["score_breakdown_status"].value)
        self.assertEqual("missing", rows[0].fields["outcome_status"].value)
        self.assertIn("Missing stored score breakdown", rows[0].warnings)
        self.assertIn("Missing later outcome label", rows[0].warnings)

    def test_replay_html_labels_outcomes_as_post_capture_data(self) -> None:
        payload = capture_payload("2026-06-05T07:00:00-05:00", "morning", "Base Momentum", price=82.0, score=90)
        write_capture(self.captures_dir / "2026-06-05" / "morning.json", payload)
        write_score_store(self.score_path, [payload])
        write_outcomes(self.outcomes_csv, payload, "COO")
        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        from momentum_hunter.app import format_replay_html

        html = format_replay_html(build_replay_view_model(rows[0]))

        self.assertIn("POINT-IN-TIME REPLAY", html)
        self.assertIn("Outcome Calculated After Capture", html)
        self.assertIn("They were not known during the replayed moment", html)

    def test_timeline_exposes_outcome_maturity_dates_and_reason(self) -> None:
        payload = capture_payload("2026-06-18T19:00:00-05:00", "evening", "Base Momentum", price=100.0, score=90)
        write_capture(self.captures_dir / "2026-06-18" / "evening.json", payload)
        write_outcomes(
            self.outcomes_csv,
            payload,
            "COO",
            extra={
                "next_day_return_pct": "4.0000",
                "five_day_return_pct": "",
                "max_gain_pct": "8.0000",
                "max_drawdown_pct": "-2.0000",
                "outcome_start_date": "2026-06-22",
                "outcome_end_date": "2026-06-23",
                "expected_next_day_session_date": "2026-06-22",
                "expected_five_day_session_date": "2026-06-26",
                "next_day_outcome_state": "complete",
                "five_day_outcome_state": "pending_not_mature",
                "outcome_reason": "pending_not_mature: no price bar for expected five-day session 2026-06-26",
                "outcome_calculation_version": "outcome-session-v1",
                "outcome_status": "pending_five_day",
            },
        )
        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual("2026-06-22", rows[0].fields["expected_next_day_session_date"].value)
        self.assertEqual("2026-06-26", rows[0].fields["expected_five_day_session_date"].value)
        self.assertEqual("complete", rows[0].fields["next_day_outcome_state"].value)
        self.assertEqual("pending_not_mature", rows[0].fields["five_day_outcome_state"].value)

        from momentum_hunter.app import format_timeline_detail_html

        detail = format_timeline_detail_html(rows[0])
        self.assertIn("Expected Next Day", detail)
        self.assertIn("2026-06-22", detail)
        self.assertIn("pending_not_mature", detail)

    def test_legacy_juneteenth_outcome_rows_infer_maturity_context(self) -> None:
        payload = capture_payload("2026-06-18T19:00:00-05:00", "evening", "Base Momentum", price=100.0, score=90)
        write_capture(self.captures_dir / "2026-06-18" / "evening.json", payload)
        write_outcomes(
            self.outcomes_csv,
            payload,
            "COO",
            extra={
                "next_day_return_pct": "4.0000",
                "five_day_return_pct": "",
                "max_gain_pct": "8.0000",
                "max_drawdown_pct": "-2.0000",
                "outcome_start_date": "2026-06-22",
                "outcome_end_date": "2026-06-23",
                "outcome_status": "pending_five_day",
            },
        )

        with patch("momentum_hunter.replay.now_central", return_value=datetime(2026, 6, 24, 12, 0, tzinfo=CENTRAL_TZ)):
            rows = build_candidate_timeline(
                "COO",
                captures_dir=self.captures_dir,
                manifest_path=self.manifest_path,
                score_breakdowns_path=self.score_path,
                review_decisions_path=self.review_path,
                outcomes_csv=self.outcomes_csv,
            )

        self.assertEqual("2026-06-22", rows[0].fields["expected_next_day_session_date"].value)
        self.assertEqual("2026-06-26", rows[0].fields["expected_five_day_session_date"].value)
        self.assertEqual("complete", rows[0].fields["next_day_outcome_state"].value)
        self.assertEqual("pending_not_mature", rows[0].fields["five_day_outcome_state"].value)
        self.assertEqual(
            "next-day complete for 2026-06-22; five-day pending until 2026-06-26",
            rows[0].fields["outcome_reason"].value,
        )

    def test_replay_selection_identity_changes_between_june_17_and_june_18(self) -> None:
        june17 = capture_payload("2026-06-17T19:00:00-05:00", "evening", "Base Momentum", price=90.0, score=81)
        june18 = capture_payload("2026-06-18T19:00:00-05:00", "evening", "Base Momentum", price=100.0, score=92)
        write_capture(self.captures_dir / "2026-06-17" / "evening.json", june17)
        write_capture(self.captures_dir / "2026-06-18" / "evening.json", june18)
        write_outcome_rows(
            self.outcomes_csv,
            [
                outcome_row(
                    june17,
                    "COO",
                    next_day_return_pct="2.0000",
                    outcome_start_date="2026-06-18",
                    outcome_end_date="2026-06-22",
                    expected_next_day_session_date="2026-06-18",
                    expected_five_day_session_date="2026-06-24",
                    next_day_outcome_state="complete",
                    five_day_outcome_state="pending_not_mature",
                    outcome_reason="june17 row",
                    outcome_status="pending_five_day",
                ),
                outcome_row(
                    june18,
                    "COO",
                    next_day_return_pct="4.0000",
                    outcome_start_date="2026-06-22",
                    outcome_end_date="2026-06-23",
                    expected_next_day_session_date="2026-06-22",
                    expected_five_day_session_date="2026-06-26",
                    next_day_outcome_state="complete",
                    five_day_outcome_state="pending_not_mature",
                    outcome_reason="june18 row",
                    outcome_status="pending_five_day",
                ),
            ],
        )

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual(["2026-06-17", "2026-06-18"], [row.capture_date for row in rows])
        self.assertNotEqual(rows[0].capture_id, rows[1].capture_id)
        self.assertNotEqual(rows[0].candidate_row_id, rows[1].candidate_row_id)
        self.assertNotEqual(rows[0].outcome_record_id, rows[1].outcome_record_id)
        self.assertIn("2026-06-17", rows[0].capture_path)
        self.assertIn("2026-06-18", rows[1].capture_path)

        from momentum_hunter.app import format_replay_html, format_timeline_detail_html, selected_timeline_row

        first_detail = format_timeline_detail_html(selected_timeline_row(rows, 0))
        second_detail = format_timeline_detail_html(selected_timeline_row(rows, 1))
        self.assertIn("Replay Audit Identity", first_detail)
        self.assertIn("2026-06-17", first_detail)
        self.assertIn("june17 row", first_detail)
        self.assertIn("2026-06-18", second_detail)
        self.assertIn("june18 row", second_detail)
        self.assertNotEqual(first_detail, second_detail)

        first_replay = format_replay_html(build_replay_view_model(rows[0]))
        second_replay = format_replay_html(build_replay_view_model(rows[1]))
        self.assertIn(rows[0].candidate_row_id, first_replay)
        self.assertIn(rows[1].candidate_row_id, second_replay)
        self.assertNotEqual(first_replay, second_replay)
        self.assertIsNone(selected_timeline_row(rows, 99))

        switch_sequence = [
            format_timeline_detail_html(selected_timeline_row(rows, index))
            for index in [0, 1, 0, 1]
        ]
        self.assertIn("2026-06-17", switch_sequence[0])
        self.assertIn("2026-06-18", switch_sequence[1])
        self.assertEqual(switch_sequence[0], switch_sequence[2])
        self.assertEqual(switch_sequence[1], switch_sequence[3])
        self.assertNotEqual(switch_sequence[2], switch_sequence[3])

    def test_replay_ticker_selection_uses_selected_candidate_symbol(self) -> None:
        payload = capture_payload("2026-06-18T19:00:00-05:00", "evening", "Base Momentum", price=100.0, score=90)
        other = dict(payload["candidates"][0])
        other["ticker"] = "FROG"
        other["price"] = 42.0
        other["score"] = 77
        payload["candidates"].append(other)
        write_capture(self.captures_dir / "2026-06-18" / "evening.json", payload)

        coo_rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )
        frog_rows = build_candidate_timeline(
            "FROG",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        self.assertEqual("COO", coo_rows[0].ticker)
        self.assertEqual("FROG", frog_rows[0].ticker)
        self.assertNotEqual(coo_rows[0].candidate_row_id, frog_rows[0].candidate_row_id)

        from momentum_hunter.app import format_timeline_detail_html

        self.assertIn("Selected symbol: COO", format_timeline_detail_html(coo_rows[0]))
        self.assertIn("Selected symbol: FROG", format_timeline_detail_html(frog_rows[0]))

    def test_empty_replay_selection_shows_reason_instead_of_defaulting(self) -> None:
        from momentum_hunter.app import format_timeline_detail_html, selected_timeline_row

        self.assertIsNone(selected_timeline_row([], 0))
        html = format_timeline_detail_html(None, reason="No Replay rows found for XYZ.")

        self.assertIn("No Replay rows found for XYZ.", html)
        self.assertNotIn("2026-06-17", html)

    def test_candidate_story_summary_tracks_first_latest_and_peak(self) -> None:
        first = capture_payload("2026-06-17T07:00:00-05:00", "morning", "Base Momentum", price=100.0, score=80)
        peak = capture_payload("2026-06-18T19:00:00-05:00", "evening", "Base Momentum", price=112.0, score=96)
        latest = capture_payload("2026-06-22T07:00:00-05:00", "morning", "Base Momentum", price=110.0, score=89)
        write_capture(self.captures_dir / "2026-06-17" / "morning.json", first)
        write_capture(self.captures_dir / "2026-06-18" / "evening.json", peak)
        write_capture(self.captures_dir / "2026-06-22" / "morning.json", latest)

        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        from momentum_hunter.app import build_candidate_story_summary, format_candidate_story_header_html, story_marker_specs

        summary = build_candidate_story_summary(rows)
        header = format_candidate_story_header_html(summary)

        self.assertEqual("COO", summary.ticker)
        self.assertEqual("Cool Corp", summary.company)
        self.assertEqual(3, summary.trusted_capture_count)
        self.assertEqual(100.0, summary.first_price)
        self.assertEqual(110.0, summary.latest_price)
        self.assertAlmostEqual(10.0, summary.move_since_first_pct or 0.0)
        self.assertEqual(80.0, summary.first_score)
        self.assertEqual(89.0, summary.latest_score)
        self.assertEqual(96.0, summary.peak_score)
        self.assertEqual("Holding", summary.status)
        self.assertIn("Jun 18", summary.peak_score_text)
        self.assertIn("Score", header)
        self.assertIn("$100.00", header)
        self.assertIn("+10.0%", header)
        self.assertIn("Holding", header)
        self.assertIn("First seen", summary.points[0].note)
        self.assertIn("Peak score", summary.points[1].note)
        self.assertIn("Latest capture", summary.points[2].note)
        self.assertEqual([("First seen", 0), ("Peak score", 1), ("Latest capture", 2)], story_marker_specs(summary))

    def test_candidate_story_single_capture_is_insufficient_data(self) -> None:
        payload = capture_payload("2026-06-17T07:00:00-05:00", "morning", "Base Momentum", price=100.0, score=80)
        write_capture(self.captures_dir / "2026-06-17" / "morning.json", payload)
        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        from momentum_hunter.app import build_candidate_story_summary

        summary = build_candidate_story_summary(rows)

        self.assertEqual("Insufficient data", summary.status)
        self.assertEqual(1, len(summary.points))
        self.assertTrue(any("Only one capture" in warning for warning in summary.warnings))

    def test_candidate_story_missing_prices_warns_without_inventing_points(self) -> None:
        payload = capture_payload("2026-06-17T07:00:00-05:00", "morning", "Base Momentum", price=100.0, score=80)
        payload["candidates"][0]["price"] = ""
        write_capture(self.captures_dir / "2026-06-17" / "morning.json", payload)
        rows = build_candidate_timeline(
            "COO",
            captures_dir=self.captures_dir,
            manifest_path=self.manifest_path,
            score_breakdowns_path=self.score_path,
            review_decisions_path=self.review_path,
            outcomes_csv=self.outcomes_csv,
        )

        from momentum_hunter.app import build_candidate_story_summary

        summary = build_candidate_story_summary(rows)

        self.assertIsNone(summary.first_price)
        self.assertEqual([], summary.chartable_price_points)
        self.assertTrue(any("stored prices are missing" in warning for warning in summary.warnings))


def capture_payload(capture_time: str, session: str, scanner: str, *, price: float, score: int) -> dict:
    return {
        "schema_version": 2,
        "capture_time": capture_time,
        "capture_date": capture_time[:10],
        "session": session,
        "mode": "PAPER",
        "provider": "finviz",
        "scanner": {"name": scanner},
        "scoring": {"profile": "regime-aware-v1", "regime": "bull"},
        "market": {"regime": "bull", "symbol": "SPY"},
        "candidates": [
            {
                "rank": 1,
                "ticker": "COO",
                "company": "Cool Corp",
                "price": price,
                "percent_change": 6.5,
                "volume": 35_000_000,
                "relative_volume": 2.2,
                "market_cap": 75_000_000_000,
                "sector": "Technology",
                "industry": "Software",
                "score": score,
                "score_profile": "regime-aware-v1",
                "score_regime": "bull",
                "news": [
                    {
                        "headline": "Cool beats earnings and raises AI server guidance",
                        "source": "Finviz",
                        "published_at": capture_time,
                        "url": "",
                        "summary": "",
                    }
                ],
            }
        ],
    }


def write_capture(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_score_store(path: Path, captures: list[dict]) -> None:
    records = {}
    for capture in captures:
        record = build_score_breakdown_for_raw_candidate(capture, capture["candidates"][0])
        records[record["identity_key"]] = record
    path.write_text(json.dumps({"schema_version": 1, "score_engine_version": SCORE_ENGINE_VERSION, "records": records}, indent=2), encoding="utf-8")


def write_review_decision(path: Path, capture: dict, ticker: str) -> None:
    scanner = capture["scanner"]["name"]
    identity = CandidateIdentity(
        capture_id=make_capture_id(capture["capture_date"], capture["session"], capture["provider"], scanner),
        capture_date=capture["capture_date"],
        session=capture["session"],
        provider=capture["provider"],
        scanner=scanner,
        ticker=ticker,
    )
    save_review_decisions(
        {
            identity.key: ReviewDecision(
                identity=identity,
                review_status=ReviewStatus.WATCHLIST,
                decision_timestamp=datetime(2026, 6, 6, 8, 0, tzinfo=CENTRAL_TZ),
                decision_note="Later user decision.",
            )
        },
        path=path,
    )


def write_outcomes(path: Path, capture: dict, ticker: str, extra: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = outcome_row(capture, ticker)
    if extra:
        row.update(extra)
    write_outcome_rows(path, [row])


def outcome_row(capture: dict, ticker: str, **extra: str) -> dict:
    row = {field: "" for field in OUTCOME_FIELDNAMES}
    row.update(
        {
            "capture_date": capture["capture_date"],
            "capture_time": capture["capture_time"],
            "session": capture["session"],
            "mode": capture["mode"],
            "provider": capture["provider"],
            "scanner": capture["scanner"]["name"],
            "ticker": ticker,
            "next_day_return_pct": "3.2500",
            "five_day_return_pct": "8.5000",
            "max_gain_pct": "10.0000",
            "max_drawdown_pct": "-2.0000",
            "outcome_status": "complete",
        }
    )
    row.update(extra)
    return row


def write_outcome_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OUTCOME_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
