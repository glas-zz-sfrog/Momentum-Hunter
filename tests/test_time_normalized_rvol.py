from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path

from momentum_hunter.canonical_candle_evidence import CanonicalMinuteBar
from momentum_hunter.evidence_integrity import EXECUTION_ELIGIBLE, EXECUTION_INELIGIBLE
from momentum_hunter.outcomes import PriceBar
from momentum_hunter.schwab_candle_contract import EASTERN_TZ, SCHWAB_PRICE_HISTORY_SOURCE
from momentum_hunter.storage import file_sha256
from momentum_hunter.time_normalized_rvol import (
    INTRADAY_RVOL,
    LEGACY_RVOL_RESEARCH_ONLY,
    RVOL_EVIDENCE_EXECUTION_INELIGIBLE,
    TimeNormalizedRvolEvidence,
    calculate_time_normalized_rvol,
)
from momentum_hunter.trade_planning import (
    MarketTape,
    build_trade_planning_report,
    export_trade_planning_report,
)


class TimeNormalizedRvolTests(unittest.TestCase):
    def test_opening_rvol_compares_identical_elapsed_session_windows(self) -> None:
        as_of = eastern("2026-08-07", 9, 35)
        bars = opening_history(current_volume=200, baseline_volume=100)

        result = calculate_time_normalized_rvol("AAA", bars, as_of=as_of)

        self.assertEqual(EXECUTION_ELIGIBLE, result.status)
        self.assertEqual(INTRADAY_RVOL, result.rvol_type)
        self.assertEqual("REGULAR", result.session_name)
        self.assertEqual(5, result.session_minute)
        self.assertEqual(5, result.current_bar_count)
        self.assertEqual(5, result.baseline_session_count)
        self.assertEqual(1000, result.observed_volume)
        self.assertEqual(500.0, result.expected_volume)
        self.assertEqual(2.0, result.relative_volume)

    def test_current_incomplete_window_fails_closed(self) -> None:
        bars = opening_history(current_volume=200, baseline_volume=100)
        bars = [bar for bar in bars if not (
            bar.session_date == "2026-08-07"
            and bar.timestamp == eastern("2026-08-07", 9, 33).isoformat()
        )]

        result = calculate_time_normalized_rvol(
            "AAA",
            bars,
            as_of=eastern("2026-08-07", 9, 35),
        )

        self.assertEqual(EXECUTION_INELIGIBLE, result.status)
        self.assertIsNone(result.relative_volume)
        self.assertIn("MISSING_CURRENT_SESSION_BARS", result.findings)
        self.assertIn("CURRENT_SESSION_MISSING_MINUTES:1", result.findings)

    def test_premarket_uses_same_elapsed_premarket_window(self) -> None:
        baseline_dates = (
            date(2026, 7, 31),
            date(2026, 8, 3),
            date(2026, 8, 4),
            date(2026, 8, 5),
            date(2026, 8, 6),
        )
        bars: list[CanonicalMinuteBar] = []
        for session_date in baseline_dates:
            bars.extend(
                minute_bars(
                    "AAA",
                    session_date,
                    time(4, 0),
                    count=240,
                    volume=10,
                )
            )
        bars.extend(
            minute_bars(
                "AAA",
                date(2026, 8, 7),
                time(4, 0),
                count=240,
                volume=20,
            )
        )

        result = calculate_time_normalized_rvol(
            "AAA",
            bars,
            as_of=eastern("2026-08-07", 8, 0),
        )

        self.assertEqual(EXECUTION_ELIGIBLE, result.status)
        self.assertEqual("PREMARKET_RVOL", result.rvol_type)
        self.assertEqual(240, result.session_minute)
        self.assertEqual(2.0, result.relative_volume)

    def test_insufficient_prior_sessions_fails_closed(self) -> None:
        bars = opening_history(
            current_volume=200,
            baseline_volume=100,
            baseline_dates=(date(2026, 8, 3), date(2026, 8, 4)),
        )

        result = calculate_time_normalized_rvol(
            "AAA",
            bars,
            as_of=eastern("2026-08-07", 9, 35),
        )

        self.assertEqual(EXECUTION_INELIGIBLE, result.status)
        self.assertEqual(2, result.baseline_session_count)
        self.assertIn("INSUFFICIENT_COMPARABLE_BASELINE_SESSIONS", result.findings)

    def test_current_minute_and_later_minutes_do_not_leak_into_result(self) -> None:
        bars = opening_history(current_volume=200, baseline_volume=100)
        bars.extend(
            minute_bars(
                "AAA",
                date(2026, 8, 7),
                time(9, 35),
                count=3,
                volume=9_999_999,
            )
        )

        result = calculate_time_normalized_rvol(
            "AAA",
            bars,
            as_of=eastern("2026-08-07", 9, 35),
        )

        self.assertEqual(1000, result.observed_volume)
        self.assertEqual(2.0, result.relative_volume)

    def test_incomplete_historical_session_is_excluded_from_baseline(self) -> None:
        bars = opening_history(
            current_volume=200,
            baseline_volume=100,
            baseline_dates=(
                date(2026, 7, 30),
                date(2026, 7, 31),
                date(2026, 8, 3),
                date(2026, 8, 4),
                date(2026, 8, 5),
                date(2026, 8, 6),
            ),
        )
        bars = [bar for bar in bars if not (
            bar.session_date == "2026-08-06"
            and bar.timestamp == eastern("2026-08-06", 9, 34).isoformat()
        )]

        result = calculate_time_normalized_rvol(
            "AAA",
            bars,
            as_of=eastern("2026-08-07", 9, 35),
        )

        self.assertEqual(EXECUTION_ELIGIBLE, result.status)
        self.assertEqual(5, result.baseline_session_count)
        self.assertNotIn("2026-08-06", result.baseline_session_dates)


class TimeNormalizedRvolTradePlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        parent = Path.cwd() / "MomentumHunterData" / "data"
        parent.mkdir(parents=True, exist_ok=True)
        self.root = parent / f"_test-time-rvol-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.capture = self.root / "opening.json"
        self.capture.write_text(
            json.dumps(
                {
                    "capture_time": "2026-08-07T08:35:03-05:00",
                    "session": "opening",
                    "provider": "finviz",
                    "scanner": {"name": "Institutional Momentum"},
                    "candidates": [
                        {
                            "ticker": "AAA",
                            "company": "AAA Corp",
                            "price": 10.0,
                            "percent_change": 3.0,
                            "volume": 1_000_000,
                            "relative_volume": 7.5,
                            "market_cap": 1_000_000_000,
                            "sector": "Technology",
                            "industry": "Software",
                            "score": 80,
                            "freshness_score": 50,
                            "news_stack": {
                                "article_count": 1,
                                "freshest_headline": "AAA raises guidance",
                                "freshness_score": 50,
                            },
                            "news": [
                                {
                                    "headline": "AAA raises guidance",
                                    "source": "Test",
                                    "published_at": "2026-08-07T08:00:00-05:00",
                                    "url": "https://example.test/aaa",
                                    "summary": "",
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_authoritative_rvol_replaces_legacy_ratio_and_is_exported(self) -> None:
        evidence = eligible_evidence("AAA", relative_volume=2.0)
        report = self.build_report(evidence=evidence)
        row = report.rows[0]

        self.assertEqual(2.0, row.relative_volume)
        self.assertEqual(10.0, row.research_relative_volume)
        self.assertEqual(EXECUTION_ELIGIBLE, row.rvol_evidence.status)
        self.assertNotIn(
            RVOL_EVIDENCE_EXECUTION_INELIGIBLE,
            row.trade_plan.blocking_reasons,
        )

        output = export_trade_planning_report(report, self.root / "reports")
        payload = json.loads(output["json"].read_text(encoding="utf-8"))
        candidate = payload["candidates"][0]
        self.assertEqual(2.0, candidate["market_data"]["relative_volume"])
        self.assertEqual(10.0, candidate["market_data"]["research_relative_volume"])
        self.assertEqual(
            EXECUTION_ELIGIBLE,
            candidate["evidence_integrity"]["rvol_evidence"]["status"],
        )

    def test_legacy_ratio_is_visible_but_cannot_grant_execution_authority(self) -> None:
        report = self.build_report(evidence=None)
        row = report.rows[0]

        self.assertIsNone(row.relative_volume)
        self.assertEqual(10.0, row.research_relative_volume)
        self.assertIn(LEGACY_RVOL_RESEARCH_ONLY, row.market_tape.warnings)
        self.assertIn(
            RVOL_EVIDENCE_EXECUTION_INELIGIBLE,
            row.trade_plan.blocking_reasons,
        )

    def test_cross_symbol_evidence_fails_closed_at_report_boundary(self) -> None:
        report = self.build_report(
            evidence=eligible_evidence("BBB", relative_volume=2.0)
        )
        row = report.rows[0]

        self.assertIsNone(row.relative_volume)
        self.assertEqual(EXECUTION_INELIGIBLE, row.rvol_evidence.status)
        self.assertIn("RVOL_EVIDENCE_SYMBOL_MISMATCH", row.rvol_evidence.findings)
        self.assertIn(
            RVOL_EVIDENCE_EXECUTION_INELIGIBLE,
            row.trade_plan.blocking_reasons,
        )

    def test_rvol_authority_does_not_rewrite_discovery_score_or_capture(self) -> None:
        before = file_sha256(self.capture)
        unavailable = self.build_report(evidence=None).rows[0]
        available = self.build_report(evidence=eligible_evidence("AAA", relative_volume=2.0)).rows[0]

        self.assertEqual(unavailable.momentum_score, available.momentum_score)
        self.assertEqual(unavailable.composite_score, available.composite_score)
        self.assertEqual(before, file_sha256(self.capture))

    def build_report(
        self,
        *,
        evidence: TimeNormalizedRvolEvidence | None,
    ):
        tape = MarketTape(
            last_price=10.5,
            premarket_price=10.4,
            premarket_percent=4.0,
            premarket_volume=100_000,
            intraday_volume=1_000_000,
            average_daily_volume_20=100_000,
            current_bid=10.49,
            current_ask=10.51,
            spread_percent=0.19,
            relative_volume=7.5,
            source="test",
        )
        return build_trade_planning_report(
            self.capture,
            bars_by_ticker={
                "AAA": [
                    PriceBar(
                        "2026-08-06",
                        high=10.2,
                        low=9.8,
                        close=10.0,
                        volume=100_000,
                    )
                ]
            },
            market_tape_by_ticker={"AAA": tape},
            rvol_evidence_by_ticker=({"AAA": evidence} if evidence is not None else {}),
            as_of=datetime.fromisoformat("2026-08-07T08:35:03-05:00"),
        )


def eligible_evidence(symbol: str, *, relative_volume: float) -> TimeNormalizedRvolEvidence:
    return TimeNormalizedRvolEvidence(
        status=EXECUTION_ELIGIBLE,
        symbol=symbol,
        rvol_type=INTRADAY_RVOL,
        session_name="REGULAR",
        session_date="2026-08-07",
        session_minute=5,
        window_start=eastern("2026-08-07", 9, 30).isoformat(),
        through_minute=eastern("2026-08-07", 9, 34).isoformat(),
        observed_volume=1000,
        expected_volume=500.0,
        relative_volume=relative_volume,
        current_bar_count=5,
        expected_current_bar_count=5,
        baseline_session_count=5,
        baseline_session_dates=(
            "2026-07-31",
            "2026-08-03",
            "2026-08-04",
            "2026-08-05",
            "2026-08-06",
        ),
        findings=("TIME_NORMALIZED_RVOL_AVAILABLE",),
    )


def opening_history(
    *,
    current_volume: int,
    baseline_volume: int,
    baseline_dates: tuple[date, ...] = (
        date(2026, 7, 31),
        date(2026, 8, 3),
        date(2026, 8, 4),
        date(2026, 8, 5),
        date(2026, 8, 6),
    ),
) -> list[CanonicalMinuteBar]:
    bars: list[CanonicalMinuteBar] = []
    for session_date in baseline_dates:
        bars.extend(
            minute_bars(
                "AAA",
                session_date,
                time(9, 30),
                count=5,
                volume=baseline_volume,
            )
        )
    bars.extend(
        minute_bars(
            "AAA",
            date(2026, 8, 7),
            time(9, 30),
            count=5,
            volume=current_volume,
        )
    )
    return bars


def minute_bars(
    symbol: str,
    session_date: date,
    start: time,
    *,
    count: int,
    volume: int,
) -> list[CanonicalMinuteBar]:
    first = datetime.combine(session_date, start, EASTERN_TZ)
    return [
        CanonicalMinuteBar(
            symbol=symbol,
            timestamp=(first + timedelta(minutes=index)).isoformat(),
            open=10.0,
            high=10.2,
            low=9.9,
            close=10.1,
            volume=float(volume),
            source=SCHWAB_PRICE_HISTORY_SOURCE,
            state="RECONCILED",
            session_date=session_date.isoformat(),
        )
        for index in range(count)
    ]


def eastern(day: str, hour: int, minute: int) -> datetime:
    return datetime.combine(date.fromisoformat(day), time(hour, minute), EASTERN_TZ)


if __name__ == "__main__":
    unittest.main()
