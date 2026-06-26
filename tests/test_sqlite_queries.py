from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_queries import (
    alert_evidence_summary,
    candidate_history_for_ticker,
    get_all_interested_candidates,
    get_all_rejected_candidates,
    get_alerts_by_symbol,
    get_candidate_capture_trail,
    get_candidate_reviews_by_symbol,
    get_complete_entry_plans,
    get_evidence_runs_by_date_range,
    get_first_latest_capture_for_symbol,
    get_incomplete_entry_plans,
    get_latest_provider_quality_checks,
    get_latest_user_state_import_summary,
    get_minute_bars_by_symbol,
    get_outcomes_by_alert_id,
    get_peak_score_capture_for_symbol,
    get_user_state_conflicts,
    get_watchlist_items,
    latest_system_status,
    sqlite_backbone_summary,
)
from momentum_hunter.sqlite_store import connect_database, initialize_schema


class SQLiteQueryHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-queries-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        with connect_database(self.db_path) as connection:
            initialize_schema(connection)
            seed_query_database(connection)
            connection.commit()

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_sqlite_backbone_summary_returns_table_counts(self) -> None:
        summary = sqlite_backbone_summary(db_path=self.db_path)

        self.assertEqual(7, summary["schema_version"])
        self.assertEqual(2, summary["table_counts"]["captures"])
        self.assertEqual(3, summary["table_counts"]["capture_candidates"])
        self.assertEqual(3, summary["table_counts"]["alert_outcomes"])
        self.assertEqual(2, summary["table_counts"]["candidate_reviews"])
        self.assertEqual(1, summary["table_counts"]["watchlist_items"])
        self.assertEqual(2, summary["table_counts"]["entry_plans"])

    def test_alert_evidence_summary_separates_completed_pending_unscorable(self) -> None:
        summary = alert_evidence_summary(db_path=self.db_path)

        self.assertEqual(1, summary["completed_outcomes"])
        self.assertEqual(1, summary["pending_outcomes"])
        self.assertEqual(1, summary["unscorable_outcomes"])

    def test_candidate_history_for_ticker_orders_by_capture_time(self) -> None:
        rows = candidate_history_for_ticker("aaa", db_path=self.db_path)

        self.assertEqual(2, len(rows))
        self.assertEqual("AAA", rows[0]["ticker"])
        self.assertEqual(91, rows[0]["score"])
        self.assertEqual("morning", rows[0]["session"])
        self.assertEqual(97, rows[-1]["score"])

    def test_query_helpers_cover_alerts_outcomes_bars_evidence_and_provider_quality(self) -> None:
        alerts = get_alerts_by_symbol("aaa", db_path=self.db_path)
        outcomes = get_outcomes_by_alert_id("alert-1", db_path=self.db_path)
        bars = get_minute_bars_by_symbol(
            "aaa",
            db_path=self.db_path,
            start="2026-06-25T09:00:00-05:00",
            end="2026-06-25T09:02:00-05:00",
        )
        evidence_runs = get_evidence_runs_by_date_range(
            db_path=self.db_path,
            start="2026-06-25T08:00:00-05:00",
            end="2026-06-25T10:00:00-05:00",
        )
        provider_quality = get_latest_provider_quality_checks(db_path=self.db_path, symbol="aaa")

        self.assertEqual(["alert-1"], [row["alert_id"] for row in alerts])
        self.assertEqual("SUCCESSFUL", outcomes[0]["classification"])
        self.assertEqual(2, len(bars))
        self.assertEqual(10.2, bars[-1]["close"])
        self.assertEqual(["run-1"], [row["run_id"] for row in evidence_runs])
        self.assertEqual("AAA", provider_quality[0]["symbol"])

    def test_capture_trail_first_latest_and_peak_score_helpers(self) -> None:
        trail = get_candidate_capture_trail("AAA", db_path=self.db_path)
        first_latest = get_first_latest_capture_for_symbol("AAA", db_path=self.db_path)
        peak = get_peak_score_capture_for_symbol("AAA", db_path=self.db_path)

        self.assertEqual(2, len(trail))
        self.assertEqual("2026-06-25T07:00:00-05:00", first_latest["first"]["capture_time"])
        self.assertEqual("2026-06-25T09:30:00-05:00", first_latest["latest"]["capture_time"])
        self.assertEqual(97, peak["score"])

    def test_latest_system_status_can_filter_warnings(self) -> None:
        rows = latest_system_status(db_path=self.db_path, status="warning")

        self.assertEqual(1, len(rows))
        self.assertEqual("WARNING", rows[0]["status"])
        self.assertEqual("market_tape_health", rows[0]["event_type"])

    def test_user_state_query_helpers_are_read_only(self) -> None:
        reviews = get_candidate_reviews_by_symbol("aaa", db_path=self.db_path)
        interested = get_all_interested_candidates(db_path=self.db_path)
        rejected = get_all_rejected_candidates(db_path=self.db_path)
        watchlist = get_watchlist_items(db_path=self.db_path, watchlist_date="2026-06-25")
        complete_plans = get_complete_entry_plans(db_path=self.db_path)
        incomplete_plans = get_incomplete_entry_plans(db_path=self.db_path)
        missing_import_summary = get_latest_user_state_import_summary(report_path=self.root / "missing-import.json")
        missing_conflicts = get_user_state_conflicts(report_path=self.root / "missing-diff.json")

        self.assertEqual(1, len(reviews))
        self.assertEqual("AAA", reviews[0]["ticker"])
        self.assertEqual(["AAA"], [row["ticker"] for row in interested])
        self.assertEqual(["BBB"], [row["ticker"] for row in rejected])
        self.assertEqual(["AAA"], [row["ticker"] for row in watchlist])
        self.assertEqual(["AAA"], [row["ticker"] for row in complete_plans])
        self.assertEqual(["BBB"], [row["ticker"] for row in incomplete_plans])
        self.assertFalse(missing_import_summary["exists"])
        self.assertEqual(0, missing_conflicts["conflicts"])


def seed_query_database(connection) -> None:
    for capture_id, capture_time, session in [
        ("cap-1", "2026-06-25T07:00:00-05:00", "morning"),
        ("cap-2", "2026-06-25T09:30:00-05:00", "manual"),
    ]:
        connection.execute(
            """
            INSERT INTO captures (
                capture_id, capture_date, capture_time, session, provider, scanner,
                source_path, source_hash, capture_version, is_quarantined,
                capture_session, capture_calendar_status, is_market_open_day,
                is_study_eligible, next_market_session_date, scheduling_policy_version,
                mode, market_regime, source_csv_path, source_csv_hash, imported_at, updated_at
            )
            VALUES (?, '2026-06-25', ?, ?, 'finviz', 'Base Momentum',
                ?, 'hash', '', 0,
                ?, 'MARKET_OPEN_DAY', 1, 1, '2026-06-25', 'market-calendar-v1',
                'PAPER', 'bull', 'analysis-captures.csv', 'csvhash', '2026-06-25T08:00:00-05:00', '2026-06-25T08:00:00-05:00')
            """,
            (capture_id, capture_time, session, f"captures/2026-06-25/{session}.json", session),
        )
    for candidate_id, capture_id, ticker, rank, score in [
        ("cand-1", "cap-1", "AAA", 1, 91),
        ("cand-2", "cap-1", "BBB", 2, 84),
        ("cand-3", "cap-2", "AAA", 1, 97),
    ]:
        connection.execute(
            """
            INSERT INTO capture_candidates (
                candidate_id, capture_id, ticker, rank, score, price, percent_change, volume,
                relative_volume, market_cap, sector, industry, raw_json, company, freshness,
                freshness_score, article_count, source_csv_path, source_csv_hash, imported_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 10.0, 5.0, 1000000, 1.5, 5000000000,
                'Technology', 'Software', '{}', ?, 'HOT', 99, 3,
                'analysis-captures.csv', 'csvhash', '2026-06-25T08:00:00-05:00', '2026-06-25T08:00:00-05:00')
            """,
            (candidate_id, capture_id, ticker, rank, score, f"{ticker} Corp"),
        )
    connection.execute(
        """
        INSERT INTO opportunity_alerts (
            alert_id, symbol, alert_type, timestamp, current_state, entry_price,
            source_alerts_path, source_alerts_hash, imported_at, updated_at
        )
        VALUES ('alert-1', 'AAA', 'TEST_ALERT', '2026-06-25T09:00:00-05:00', 'PLANNING_SCAFFOLD', 10.0,
            'opportunity-alerts.json', 'alerthash', '2026-06-25T09:00:00-05:00', '2026-06-25T09:00:00-05:00')
        """
    )
    for timestamp, close in [("2026-06-25T09:00:00-05:00", 10.1), ("2026-06-25T09:01:00-05:00", 10.2)]:
        connection.execute(
            """
            INSERT INTO minute_bars (
                symbol, timestamp, open, high, low, close, volume, source,
                granularity, source_file_path, source_file_hash, imported_at, updated_at
            )
            VALUES ('AAA', ?, 10.0, 10.5, 9.9, ?, 1000, 'test_1m',
                '1m', 'opportunity-minute-bars.json', 'barhash', '2026-06-25T09:02:00-05:00', '2026-06-25T09:02:00-05:00')
            """,
            (timestamp, close),
        )
    connection.execute(
        """
        INSERT INTO evidence_runs (
            run_id, run_type, generated_at, source_path, source_hash, summary_json,
            status, imported_at, updated_at
        )
        VALUES ('run-1', 'evidence_health', '2026-06-25T09:05:00-05:00',
            'evidence-health.json', 'evidencehash', '{}', 'READY',
            '2026-06-25T09:05:00-05:00', '2026-06-25T09:05:00-05:00')
        """
    )
    connection.execute(
        """
        INSERT INTO provider_quality_checks (
            check_id, generated_at, symbol, provider, usable_market_tape,
            source_report_path, source_report_hash
        )
        VALUES ('quality-1', '2026-06-25T09:06:00-05:00', 'AAA', 'combined', 1,
            'data-quality-latest.json', 'qualityhash')
        """
    )
    for alert_id, status, classification in [
        ("alert-1", "COMPLETED", "SUCCESSFUL"),
        ("alert-2", "PENDING_OUTCOME", "PENDING"),
        ("alert-3", "UNSCORABLE_OUTCOME", "UNSCORABLE_MISSING_ENTRY_PRICE"),
    ]:
        connection.execute(
            """
            INSERT INTO alert_outcomes (alert_id, status, classification, updated_at)
            VALUES (?, ?, ?, '2026-06-25T08:00:00-05:00')
            """,
            (alert_id, status, classification),
        )
    connection.execute(
        """
        INSERT INTO system_status_events (
            event_id, event_type, status, occurred_at, source_path, source_module,
            source_hash, summary, recommended_action, details_json, imported_at, updated_at
        )
        VALUES (
            'status-1', 'market_tape_health', 'WARNING', '2026-06-25T08:00:00-05:00',
            'market-tape-health.json', 'market_tape_health_v1', 'hash',
            'Market tape warning', 'Repair provider access.', '{}',
            '2026-06-25T08:00:00-05:00', '2026-06-25T08:00:00-05:00'
        )
        """
    )
    for ticker, status, timestamp in [
        ("AAA", "interested", "2026-06-25T09:10:00-05:00"),
        ("BBB", "rejected", "2026-06-25T09:12:00-05:00"),
    ]:
        connection.execute(
            """
            INSERT INTO candidate_reviews (
                review_id, capture_id, ticker, review_status, decision_timestamp,
                decision_note, review_context_state, delayed_review, identity_key,
                capture_date, session, provider, scanner, source_path, source_hash,
                source_json, imported_at, updated_at
            )
            VALUES (?, 'cap-1', ?, ?, ?, '', '', 0, ?, '2026-06-25',
                'morning', 'finviz', 'Base Momentum', 'review-decisions.json',
                'reviewhash', '{}', '2026-06-25T09:15:00-05:00',
                '2026-06-25T09:15:00-05:00')
            """,
            (f"review-{ticker}", ticker, status, timestamp, f"cap-1|2026-06-25|morning|finviz|Base Momentum|{ticker}"),
        )
    connection.execute(
        """
        INSERT INTO watchlist_items (
            watchlist_item_id, capture_id, ticker, watchlist_date, created_at,
            source_review_id, company, score, price, source_path, source_hash,
            source_json, imported_at, updated_at
        )
        VALUES ('watchlist-AAA', 'cap-1', 'AAA', '2026-06-25',
            '2026-06-25T09:20:00-05:00', '', 'AAA Corp', 91, 10.0,
            'watchlist-2026-06-25.json', 'watchlisthash', '{}',
            '2026-06-25T09:20:00-05:00', '2026-06-25T09:20:00-05:00')
        """
    )
    for ticker, complete in [("AAA", 1), ("BBB", 0)]:
        connection.execute(
            """
            INSERT INTO entry_plans (
                entry_plan_id, capture_id, ticker, trigger_condition, stop_price,
                thesis, invalidation, max_loss, position_size_idea, planned_hold_time,
                notes, plan_complete, updated_at, identity_key, capture_date, session,
                provider, scanner, stop_text, warnings_json, source_path, source_hash,
                source_json, imported_at
            )
            VALUES (?, 'cap-1', ?, 'above 10', 9.5, 'continuation',
                'loses support', '$20', '$100', '1 day', '', ?,
                '2026-06-25T09:30:00-05:00', ?, '2026-06-25', 'morning',
                'finviz', 'Base Momentum', '9.50', ?, 'entry-plans.json',
                'entryhash', '{}', '2026-06-25T09:30:00-05:00')
            """,
            (
                f"entry-{ticker}",
                ticker,
                complete,
                f"cap-1|2026-06-25|morning|finviz|Base Momentum|{ticker}",
                "[]" if complete else '["missing trigger"]',
            ),
        )


if __name__ == "__main__":
    unittest.main()
