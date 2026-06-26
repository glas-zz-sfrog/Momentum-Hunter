from __future__ import annotations

import shutil
import sqlite3
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.sqlite_analytics import build_sqlite_analytics_report, write_sqlite_analytics_report
from momentum_hunter.sqlite_store import connect_database, initialize_schema


class SQLiteAnalyticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-analytics-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "analytics.sqlite3"
        with connect_database(self.db_path) as connection:
            initialize_schema(connection)
            seed_database(connection)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_query_pack_summarizes_candidates_alerts_watchlist_and_staleness(self) -> None:
        payload = build_sqlite_analytics_report(
            db_path=self.db_path,
            generated_at=datetime.fromisoformat("2026-06-20T08:00:00-05:00"),
            stale_after_hours=24,
        )

        self.assertEqual("WARN", payload["overall_status"])
        candidate = payload["candidate_evidence_summary"][0]
        self.assertEqual("AAA", candidate["symbol"])
        self.assertEqual(2, candidate["capture_count"])
        self.assertEqual(82, candidate["score_peak"])
        self.assertEqual(10.0, candidate["price_move_pct"])
        self.assertEqual(1, candidate["alerts_count"])
        self.assertEqual(1, candidate["outcomes_count"])
        self.assertEqual("watchlist", candidate["latest_review_status"])
        self.assertEqual("incomplete", candidate["entry_plan_status"])

        alerts = payload["alert_performance_sample_summary"]
        self.assertEqual(1, alerts["total_alerts"])
        self.assertEqual(1, alerts["completed"])
        self.assertEqual(0, alerts["pending"])

        watchlist = payload["watchlist_preparedness_summary"]
        self.assertEqual(1, watchlist["watchlist_count"])
        self.assertEqual(0, watchlist["complete_plans"])
        self.assertEqual(1, watchlist["incomplete_plans"])
        self.assertEqual(1, watchlist["missing_stop"])
        self.assertEqual("unavailable_current_schema", watchlist["missing_target"])

        stale = payload["stale_evidence_summary"]
        self.assertGreaterEqual(stale["stale_system_status_event_count"], 1)
        self.assertIn("STALE_SYSTEM_STATUS_EVENTS:1", payload["warnings"])

    def test_missing_database_reports_warning_without_creating_authority(self) -> None:
        missing = self.root / "missing.sqlite3"

        payload = build_sqlite_analytics_report(db_path=missing)

        self.assertEqual("WARN", payload["overall_status"])
        self.assertIn("SQLITE_DATABASE_MISSING", payload["warnings"])
        self.assertFalse(missing.exists())

    def test_missing_tables_warn_cleanly(self) -> None:
        partial = self.root / "partial.sqlite3"
        connection = sqlite3.connect(partial)
        try:
            connection.execute("CREATE TABLE captures (capture_id TEXT)")
            connection.commit()
        finally:
            connection.close()

        payload = build_sqlite_analytics_report(db_path=partial)

        self.assertEqual("WARN", payload["overall_status"])
        self.assertTrue(any(str(item).startswith("MISSING_TABLES:") for item in payload["warnings"]))

    def test_report_generation_writes_json_and_markdown(self) -> None:
        payload = build_sqlite_analytics_report(db_path=self.db_path)

        json_path, markdown_path = write_sqlite_analytics_report(payload, output_dir=self.root / "reports")

        self.assertTrue(json_path.exists())
        self.assertTrue(markdown_path.exists())
        self.assertIn("SQLite Analytics Query Pack", markdown_path.read_text(encoding="utf-8"))


def seed_database(connection) -> None:
    imported_at = "2026-06-19T08:00:00-05:00"
    connection.execute(
        """
        INSERT INTO captures (
            capture_id, capture_date, capture_time, session, provider, scanner, source_path,
            is_quarantined, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("cap1", "2026-06-19", "2026-06-19T07:00:00-05:00", "morning", "finviz", "Basic", "cap1.json", 0, imported_at),
    )
    connection.execute(
        """
        INSERT INTO captures (
            capture_id, capture_date, capture_time, session, provider, scanner, source_path,
            is_quarantined, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("cap2", "2026-06-19", "2026-06-19T19:00:00-05:00", "evening", "finviz", "Basic", "cap2.json", 0, imported_at),
    )
    connection.executemany(
        """
        INSERT INTO capture_candidates (
            candidate_id, capture_id, ticker, rank, score, price, volume, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("cand1", "cap1", "AAA", 1, 80, 10.0, 1000000, imported_at),
            ("cand2", "cap2", "AAA", 1, 82, 11.0, 1200000, imported_at),
        ],
    )
    connection.execute(
        """
        INSERT INTO opportunity_alerts (
            alert_id, symbol, alert_type, timestamp, current_state, entry_price, source_alerts_path, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("alert1", "AAA", "PRICE_EXPANSION", "2026-06-19T09:30:00-05:00", "EXECUTION_READY_TRADE", 10.5, "alerts.json", imported_at),
    )
    connection.execute(
        """
        INSERT INTO alert_outcomes (alert_id, status, classification, return_5m, updated_at, imported_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("alert1", "COMPLETED", "SUCCESSFUL", 1.2, "2026-06-19T10:30:00-05:00", imported_at),
    )
    connection.execute(
        """
        INSERT INTO candidate_reviews (review_id, capture_id, ticker, review_status, decision_timestamp)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("review1", "cap2", "AAA", "watchlist", "2026-06-19T20:00:00-05:00"),
    )
    connection.execute(
        """
        INSERT INTO watchlist_items (watchlist_item_id, capture_id, ticker, watchlist_date, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("watch1", "cap2", "AAA", "2026-06-20", "2026-06-19T20:01:00-05:00"),
    )
    connection.execute(
        """
        INSERT INTO entry_plans (
            entry_plan_id, capture_id, ticker, trigger_condition, stop_price, plan_complete, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("plan1", "cap2", "AAA", "Breakout over 11.25", None, 0, "2026-06-19T20:05:00-05:00"),
    )
    connection.execute(
        """
        INSERT INTO system_status_events (
            event_id, event_type, status, occurred_at, source_path, summary, imported_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("event1", "active_monitor", "WARNING", "2026-06-18T07:00:00-05:00", "status.json", "stale", imported_at),
    )
    connection.execute(
        """
        INSERT INTO provider_quality_checks (
            check_id, generated_at, symbol, provider, usable_market_tape
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        ("provider1", "2026-06-19T07:30:00-05:00", "AAA", "combined", 1),
    )
    connection.commit()


if __name__ == "__main__":
    unittest.main()
