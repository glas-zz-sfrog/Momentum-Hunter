from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from momentum_hunter.sqlite_queries import (
    alert_evidence_summary,
    candidate_history_for_ticker,
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

        self.assertEqual(6, summary["schema_version"])
        self.assertEqual(1, summary["table_counts"]["captures"])
        self.assertEqual(2, summary["table_counts"]["capture_candidates"])
        self.assertEqual(3, summary["table_counts"]["alert_outcomes"])

    def test_alert_evidence_summary_separates_completed_pending_unscorable(self) -> None:
        summary = alert_evidence_summary(db_path=self.db_path)

        self.assertEqual(1, summary["completed_outcomes"])
        self.assertEqual(1, summary["pending_outcomes"])
        self.assertEqual(1, summary["unscorable_outcomes"])

    def test_candidate_history_for_ticker_orders_by_capture_time(self) -> None:
        rows = candidate_history_for_ticker("aaa", db_path=self.db_path)

        self.assertEqual(1, len(rows))
        self.assertEqual("AAA", rows[0]["ticker"])
        self.assertEqual(91, rows[0]["score"])
        self.assertEqual("morning", rows[0]["session"])

    def test_latest_system_status_can_filter_warnings(self) -> None:
        rows = latest_system_status(db_path=self.db_path, status="warning")

        self.assertEqual(1, len(rows))
        self.assertEqual("WARNING", rows[0]["status"])
        self.assertEqual("market_tape_health", rows[0]["event_type"])


def seed_query_database(connection) -> None:
    connection.execute(
        """
        INSERT INTO captures (
            capture_id, capture_date, capture_time, session, provider, scanner,
            source_path, source_hash, capture_version, is_quarantined,
            capture_session, capture_calendar_status, is_market_open_day,
            is_study_eligible, next_market_session_date, scheduling_policy_version,
            mode, market_regime, source_csv_path, source_csv_hash, imported_at, updated_at
        )
        VALUES (
            'cap-1', '2026-06-25', '2026-06-25T07:00:00-05:00', 'morning', 'finviz', 'Base Momentum',
            'captures/2026-06-25/morning.json', 'hash', '', 0,
            'morning', 'MARKET_OPEN_DAY', 1, 1, '2026-06-25', 'market-calendar-v1',
            'PAPER', 'bull', 'analysis-captures.csv', 'csvhash', '2026-06-25T08:00:00-05:00', '2026-06-25T08:00:00-05:00'
        )
        """
    )
    for candidate_id, ticker, rank, score in [("cand-1", "AAA", 1, 91), ("cand-2", "BBB", 2, 84)]:
        connection.execute(
            """
            INSERT INTO capture_candidates (
                candidate_id, capture_id, ticker, rank, score, price, percent_change, volume,
                relative_volume, market_cap, sector, industry, raw_json, company, freshness,
                freshness_score, article_count, source_csv_path, source_csv_hash, imported_at, updated_at
            )
            VALUES (?, 'cap-1', ?, ?, ?, 10.0, 5.0, 1000000, 1.5, 5000000000,
                'Technology', 'Software', '{}', ?, 'HOT', 99, 3,
                'analysis-captures.csv', 'csvhash', '2026-06-25T08:00:00-05:00', '2026-06-25T08:00:00-05:00')
            """,
            (candidate_id, ticker, rank, score, f"{ticker} Corp"),
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


if __name__ == "__main__":
    unittest.main()
