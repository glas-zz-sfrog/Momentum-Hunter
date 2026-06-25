from __future__ import annotations

import shutil
import unittest
import uuid
from dataclasses import replace
from pathlib import Path

from momentum_hunter.opportunity_alerts import AlertOutcome, OpportunityAlert, save_alerts
from momentum_hunter.sqlite_store import (
    alert_outcome_count,
    connect_database,
    import_opportunity_alerts,
    opportunity_alert_count,
    read_alert_outcomes,
    read_opportunity_alerts,
)
from momentum_hunter.storage import file_sha256


class SQLiteEvidenceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-sqlite-evidence-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "momentum-hunter.sqlite3"
        self.alerts_path = self.root / "opportunity-alerts.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_alert_and_outcome_insert_read_round_trip_does_not_mutate_source(self) -> None:
        save_alerts([alert_fixture(outcome=completed_noise_outcome())], self.alerts_path)
        before_hash = file_sha256(self.alerts_path)

        result = import_opportunity_alerts(self.alerts_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            alerts = read_opportunity_alerts(connection)
            outcomes = read_alert_outcomes(connection)

        self.assertEqual(1, result.alerts_seen)
        self.assertEqual(1, result.alerts_inserted)
        self.assertEqual(1, result.outcomes_inserted)
        self.assertEqual(1, result.completed_outcomes)
        self.assertEqual(0, result.pending_outcomes)
        self.assertEqual(0, result.unscorable_outcomes)
        self.assertEqual("AAA", alerts[0]["symbol"])
        self.assertEqual("STATE_PLANNING_TO_READY", alerts[0]["alert_type"])
        self.assertEqual(10.0, alerts[0]["alert_price"])
        self.assertEqual(10.0, alerts[0]["entry_price"])
        self.assertEqual(10.5, alerts[0]["suggested_entry"])
        self.assertEqual("COMPLETED", outcomes[0]["status"])
        self.assertEqual("NOISE", outcomes[0]["classification"])
        self.assertEqual(0.5, outcomes[0]["return_60m"])
        self.assertEqual(before_hash, file_sha256(self.alerts_path))

    def test_repeated_import_is_idempotent(self) -> None:
        save_alerts([alert_fixture(outcome=completed_noise_outcome())], self.alerts_path)

        first = import_opportunity_alerts(self.alerts_path, db_path=self.db_path)
        second = import_opportunity_alerts(self.alerts_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            self.assertEqual(1, opportunity_alert_count(connection))
            self.assertEqual(1, alert_outcome_count(connection))
        self.assertEqual(1, first.alerts_inserted)
        self.assertEqual(0, second.alerts_inserted)
        self.assertEqual(0, second.alerts_updated)
        self.assertEqual(1, second.alerts_skipped)
        self.assertEqual(0, second.outcomes_inserted)
        self.assertEqual(0, second.outcomes_updated)
        self.assertEqual(1, second.outcomes_skipped)

    def test_outcome_import_updates_pending_to_completed(self) -> None:
        pending = alert_fixture(outcome=AlertOutcome())
        save_alerts([pending], self.alerts_path)
        import_opportunity_alerts(self.alerts_path, db_path=self.db_path)

        completed = replace(pending, outcome=completed_success_outcome())
        save_alerts([completed], self.alerts_path)
        result = import_opportunity_alerts(self.alerts_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            outcomes = read_alert_outcomes(connection)

        self.assertEqual(1, result.alerts_updated)
        self.assertEqual(1, result.outcomes_updated)
        self.assertEqual(1, result.completed_outcomes)
        self.assertEqual("COMPLETED", outcomes[0]["status"])
        self.assertEqual("SUCCESSFUL", outcomes[0]["classification"])
        self.assertEqual(4.2, outcomes[0]["return_60m"])
        self.assertEqual(1, outcomes[0]["target_1_hit"])

    def test_unscorable_terminal_state_is_preserved_and_not_pending(self) -> None:
        save_alerts(
            [
                alert_fixture(
                    price=None,
                    outcome=AlertOutcome(
                        status="UNSCORABLE_OUTCOME",
                        classification="UNSCORABLE_MISSING_ENTRY_PRICE",
                        evaluation_notes=["Missing alert price."],
                    ),
                )
            ],
            self.alerts_path,
        )

        result = import_opportunity_alerts(self.alerts_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            outcomes = read_alert_outcomes(connection)

        self.assertEqual(0, result.pending_outcomes)
        self.assertEqual(0, result.completed_outcomes)
        self.assertEqual(1, result.unscorable_outcomes)
        self.assertEqual("UNSCORABLE_OUTCOME", outcomes[0]["status"])
        self.assertEqual("UNSCORABLE_MISSING_ENTRY_PRICE", outcomes[0]["classification"])

    def test_missing_optional_fields_are_imported_defensively(self) -> None:
        sparse = alert_fixture(
            bid=None,
            ask=None,
            spread_percent=None,
            volume=None,
            rvol=None,
            outcome=AlertOutcome(status="PENDING_OUTCOME", classification="PENDING"),
        )
        save_alerts([sparse], self.alerts_path)

        result = import_opportunity_alerts(self.alerts_path, db_path=self.db_path)

        with connect_database(self.db_path) as connection:
            alerts = read_opportunity_alerts(connection)
            outcomes = read_alert_outcomes(connection)

        self.assertEqual(1, result.pending_outcomes)
        self.assertIsNone(alerts[0]["bid"])
        self.assertIsNone(alerts[0]["volume"])
        self.assertIsNone(alerts[0]["rvol"])
        self.assertEqual("PENDING_OUTCOME", outcomes[0]["status"])
        self.assertEqual("PENDING", outcomes[0]["classification"])


def alert_fixture(
    *,
    alert_id: str = "alert-1",
    symbol: str = "AAA",
    price: float | None = 10.0,
    bid: float | None = 9.99,
    ask: float | None = 10.01,
    spread_percent: float | None = 0.2,
    volume: int | None = 1_500_000,
    rvol: float | None = 1.4,
    outcome: AlertOutcome | None = None,
) -> OpportunityAlert:
    return OpportunityAlert(
        alert_id=alert_id,
        symbol=symbol,
        timestamp="2026-06-18T10:00:00-05:00",
        alert_type="STATE_PLANNING_TO_READY",
        current_state="EXECUTION_READY_TRADE",
        previous_state="PLANNING_SCAFFOLD",
        reason="Trade-planning state changed.",
        price=price,
        bid=bid,
        ask=ask,
        spread_percent=spread_percent,
        volume=volume,
        premarket_volume=550_000,
        premarket_percent=2.1,
        rvol=rvol,
        rvol_type="INTRADAY_RVOL",
        suggested_entry=10.5,
        stop=9.5,
        target_1=11.5,
        target_2=12.5,
        news_catalyst="Test catalyst",
        market_regime="bull",
        event_mode=False,
        source_report="reports/event-trade-plan-briefing-test.json",
        outcome=outcome or AlertOutcome(),
    )


def completed_noise_outcome() -> AlertOutcome:
    return AlertOutcome(
        status="COMPLETED",
        five_minute_return_pct=0.1,
        fifteen_minute_return_pct=0.2,
        thirty_minute_return_pct=0.3,
        sixty_minute_return_pct=0.5,
        mfe_15m_pct=0.7,
        mae_15m_pct=-0.2,
        mfe_30m_pct=0.8,
        mae_30m_pct=-0.3,
        mfe_60m_pct=0.9,
        mae_60m_pct=-0.4,
        target_1_hit=False,
        target_2_hit=False,
        stop_hit=False,
        stop_hit_before_target=False,
        classification="NOISE",
        evaluation_notes=["Minute-bar outcome updater v1."],
    )


def completed_success_outcome() -> AlertOutcome:
    return AlertOutcome(
        status="COMPLETED",
        five_minute_return_pct=1.1,
        fifteen_minute_return_pct=2.2,
        thirty_minute_return_pct=3.3,
        sixty_minute_return_pct=4.2,
        mfe_15m_pct=2.5,
        mae_15m_pct=-0.1,
        mfe_30m_pct=4.0,
        mae_30m_pct=-0.2,
        mfe_60m_pct=5.0,
        mae_60m_pct=-0.3,
        target_1_hit=True,
        target_2_hit=False,
        stop_hit=False,
        stop_hit_before_target=False,
        classification="SUCCESSFUL",
        evaluation_notes=["Minute-bar outcome updater v1."],
    )


if __name__ == "__main__":
    unittest.main()
