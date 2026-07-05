from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from momentum_hunter import technical_breakouts
from momentum_hunter.daily_ohlc import QUALITY_VALID, DailyOhlcRecord
from momentum_hunter.technical_breakouts import (
    BREAKOUT_FAILED,
    BREAKOUT_PRESENT,
    INSUFFICIENT_DATA,
    BreakoutEvent,
    BreakoutResearchOptions,
    TechnicalPriceBar,
    build_technical_breakout_reports,
    detect_atr_keltner_breakout_at_index,
    detect_bollinger_breakout_at_index,
    detect_breakout_events,
    detect_daily_breakout_events,
    detect_donchian_breakouts_at_index,
    detect_intraday_breakout_events,
    detect_moving_average_events_at_index,
    moving_average_state,
    study_breakout_events,
)


class TechnicalBreakoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-technical-breakouts-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_detects_20_day_high_breakout(self) -> None:
        bars = daily_bars("AAA", [9.5] * 21 + [11.0], high=10.0)

        events = detect_donchian_breakouts_at_index(
            symbol="AAA",
            bars=bars,
            index=21,
            market_regime="bull",
            source_data="test_daily",
            options=BreakoutResearchOptions(),
        )

        self.assertEqual(["donchian_20_day_breakout"], [event.event_type for event in events])
        self.assertEqual(BREAKOUT_PRESENT, events[0].status)
        self.assertEqual(10.0, events[0].prior_high_band_or_moving_average_value)

    def test_detects_30_day_high_breakout(self) -> None:
        bars = daily_bars("AAA", [9.5] * 31 + [12.0], high=10.0)

        events = detect_donchian_breakouts_at_index(
            symbol="AAA",
            bars=bars,
            index=31,
            market_regime=None,
            source_data="test_daily",
            options=BreakoutResearchOptions(),
        )

        self.assertIn("donchian_30_day_breakout", {event.event_type for event in events})

    def test_price_above_moving_average_state(self) -> None:
        bars = daily_bars("AAA", [10.0] * 19 + [12.0])

        state = moving_average_state(bars, 19)

        self.assertTrue(state["price_above_sma_20"])
        self.assertIsNone(state["price_above_sma_50"])

    def test_detects_moving_average_crossover(self) -> None:
        bars = daily_bars("AAA", [10.0] * 50 + [40.0])

        events = detect_moving_average_events_at_index(
            symbol="AAA",
            bars=bars,
            index=50,
            market_regime=None,
            source_data="test_daily",
            options=BreakoutResearchOptions(),
        )

        self.assertIn("sma_20_cross_above_sma_50", {event.event_type for event in events})

    def test_detects_bollinger_upper_band_breakout(self) -> None:
        bars = daily_bars("AAA", [10.0] * 21 + [11.0])

        event = detect_bollinger_breakout_at_index(
            symbol="AAA",
            bars=bars,
            index=21,
            market_regime=None,
            source_data="test_daily",
            options=BreakoutResearchOptions(),
        )

        self.assertIsNotNone(event)
        self.assertEqual("bollinger_upper_band_breakout", event.event_type)
        self.assertEqual(10.0, event.prior_high_band_or_moving_average_value)

    def test_detects_atr_keltner_breakout(self) -> None:
        bars = [
            daily_bar("AAA", offset, close=10.0, high=10.5, low=9.5, volume=100)
            for offset in range(22)
        ]
        bars.append(daily_bar("AAA", 22, close=12.0, high=12.2, low=11.8, volume=250))

        event = detect_atr_keltner_breakout_at_index(
            symbol="AAA",
            bars=bars,
            index=22,
            market_regime=None,
            source_data="test_daily",
            options=BreakoutResearchOptions(),
        )

        self.assertIsNotNone(event)
        self.assertEqual("atr_keltner_breakout", event.event_type)
        self.assertEqual(11.5, event.prior_high_band_or_moving_average_value)

    def test_marks_insufficient_daily_data(self) -> None:
        events = detect_daily_breakout_events(
            symbol="AAA",
            bars=daily_bars("AAA", [10.0] * 5),
            source_data="test_daily",
        )

        self.assertEqual(1, len(events))
        self.assertEqual(INSUFFICIENT_DATA, events[0].status)

    def test_volume_confirmation_uses_prior_average(self) -> None:
        bars = daily_bars("AAA", [10.0] * 21 + [11.0], high=10.0, volume=100)
        bars[-1] = daily_bar("AAA", 21, close=11.0, high=11.0, low=10.8, volume=200)

        events = detect_donchian_breakouts_at_index(
            symbol="AAA",
            bars=bars,
            index=21,
            market_regime=None,
            source_data="test_daily",
            options=BreakoutResearchOptions(),
        )

        self.assertEqual(2.0, events[0].relative_volume)
        self.assertTrue(events[0].volume_confirmed)

    def test_detects_intraday_high_breakout(self) -> None:
        bars = minute_bars("AAA", [9.8] * 16 + [10.6], high=10.0, volume=100)
        bars[-1] = minute_bar("AAA", 16, close=10.6, high=10.7, low=10.5, volume=300)

        events = detect_intraday_breakout_events(symbol="AAA", bars=bars)

        self.assertIn("intraday_15_minute_high_breakout", {event.event_type for event in events})

    def test_event_study_calculates_returns_and_failed_breakout(self) -> None:
        event = present_event("AAA", "2026-01-02T10:00:00-05:00", trigger_price=10.0)
        bars = [
            minute_bar("AAA", 0, close=10.0, high=10.0, low=10.0),
            minute_bar("AAA", 5, close=10.5, high=10.6, low=10.1),
            minute_bar("AAA", 15, close=10.8, high=11.0, low=9.8),
            minute_bar("AAA", 30, close=10.2, high=10.4, low=10.0),
            minute_bar("AAA", 60, close=10.1, high=10.3, low=10.0),
        ]

        studies = study_breakout_events([event], minute_bars_by_symbol={"AAA": bars})

        self.assertEqual(1, len(studies))
        self.assertEqual(5.0, studies[0].forward_returns_pct["5m"])
        self.assertEqual(10.0, studies[0].max_favorable_excursion_pct)
        self.assertEqual(-2.0, studies[0].max_adverse_excursion_pct)
        self.assertTrue(studies[0].failed_back_below_breakout_level)
        self.assertEqual(BREAKOUT_FAILED, studies[0].status)

    def test_daily_event_study_calculates_forward_returns(self) -> None:
        event = daily_present_event("AAA", "2026-01-21", trigger_price=10.0)
        bars = daily_bars("AAA", [10.0] * 21 + [10.5, 11.0, 10.8, 11.2, 12.0])

        studies = study_breakout_events([event], daily_bars_by_symbol={"AAA": bars})

        self.assertEqual(1, len(studies))
        self.assertEqual(5.0, studies[0].forward_returns_pct["1d"])
        self.assertEqual(20.0, studies[0].forward_returns_pct["5d"])
        self.assertEqual(20.0, studies[0].max_favorable_excursion_pct)

    def test_no_daily_source_marks_daily_signals_insufficient(self) -> None:
        events = detect_breakout_events(
            minute_bars_by_symbol={"AAA": minute_bars("AAA", [10.0, 10.1])},
            captures=[{"ticker": "AAA", "market_regime": "bull"}],
        )

        daily_records = [event for event in events if event.event_type == "daily_technical_breakout_scan"]
        self.assertEqual(1, len(daily_records))
        self.assertEqual(INSUFFICIENT_DATA, daily_records[0].status)

    def test_report_builder_does_not_mutate_source_files(self) -> None:
        minute_path = self.root / "opportunity-minute-bars.json"
        payload = {
            "bars": {
                "AAA": [
                    {
                        "symbol": "AAA",
                        "timestamp": "2026-01-02T10:00:00-05:00",
                        "open": 10.0,
                        "high": 10.0,
                        "low": 9.9,
                        "close": 10.0,
                        "volume": 100,
                    },
                    {
                        "symbol": "AAA",
                        "timestamp": "2026-01-02T10:01:00-05:00",
                        "open": 10.0,
                        "high": 10.2,
                        "low": 10.0,
                        "close": 10.2,
                        "volume": 200,
                    },
                ]
            }
        }
        minute_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        before = sha256(minute_path)

        paths = build_technical_breakout_reports(
            captures_path=self.root / "missing-captures.csv",
            outcomes_path=self.root / "missing-outcomes.csv",
            alerts_path=self.root / "missing-alerts.json",
            minute_bars_path=minute_path,
            daily_ohlc_path=None,
            output_dir=self.root / "reports",
            generated_at="2026-01-02T12:00:00-05:00",
        )

        self.assertEqual(before, sha256(minute_path))
        self.assertTrue(paths["events_json"].exists())
        self.assertTrue(paths["events_markdown"].exists())
        self.assertTrue(paths["study_json"].exists())
        self.assertTrue(paths["study_markdown"].exists())

    def test_report_builder_consumes_normalized_daily_ohlc(self) -> None:
        daily_path = self.root / "daily-ohlc-bars.json"
        records = [
            daily_ohlc_record("AAA", offset, close=9.5, high=10.0)
            for offset in range(21)
        ]
        records.append(daily_ohlc_record("AAA", 21, close=11.0, high=11.0, volume=300))
        daily_path.write_text(json.dumps({"records": [record.__dict__ for record in records]}, indent=2), encoding="utf-8")

        paths = build_technical_breakout_reports(
            captures_path=self.root / "missing-captures.csv",
            outcomes_path=self.root / "missing-outcomes.csv",
            alerts_path=self.root / "missing-alerts.json",
            minute_bars_path=self.root / "missing-minute-bars.json",
            daily_ohlc_path=daily_path,
            output_dir=self.root / "reports",
            generated_at="2026-01-23T12:00:00-05:00",
        )
        payload = json.loads(paths["events_json"].read_text(encoding="utf-8"))
        event_types = {event["event_type"] for event in payload["events"]}

        self.assertIn("donchian_20_day_breakout", event_types)
        self.assertTrue(paths["daily_ohlc_coverage_json"].exists())
        self.assertEqual(22, payload["source_counts"]["daily_ohlc_valid_records"])

    def test_module_stays_research_only_by_import_boundary(self) -> None:
        source = inspect.getsource(technical_breakouts)

        forbidden_imports = [
            "from momentum_hunter.scoring",
            "import momentum_hunter.scoring",
            "from momentum_hunter.trade_planning",
            "import momentum_hunter.trade_planning",
            "from momentum_hunter.opportunity_alerts",
            "import momentum_hunter.opportunity_alerts",
            "from momentum_hunter.autonomy",
            "import momentum_hunter.autonomy",
        ]
        for forbidden in forbidden_imports:
            self.assertNotIn(forbidden, source)


def daily_bars(symbol: str, closes: list[float], *, high: float | None = None, volume: int = 100) -> list[TechnicalPriceBar]:
    return [
        daily_bar(
            symbol,
            offset,
            close=close,
            high=high if high is not None else close,
            low=min(close, high if high is not None else close),
            volume=volume,
        )
        for offset, close in enumerate(closes)
    ]


def daily_bar(
    symbol: str,
    offset: int,
    *,
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: int = 100,
) -> TechnicalPriceBar:
    day = datetime(2026, 1, 1) + timedelta(days=offset)
    high = close if high is None else high
    low = close if low is None else low
    return TechnicalPriceBar(
        symbol=symbol,
        timestamp=day.date().isoformat(),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source="test_daily",
    )


def minute_bars(symbol: str, closes: list[float], *, high: float | None = None, volume: int = 100) -> list[TechnicalPriceBar]:
    return [
        minute_bar(
            symbol,
            offset,
            close=close,
            high=high if high is not None else close,
            low=min(close, high if high is not None else close),
            volume=volume,
        )
        for offset, close in enumerate(closes)
    ]


def minute_bar(
    symbol: str,
    offset_minutes: int,
    *,
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: int = 100,
) -> TechnicalPriceBar:
    timestamp = datetime(2026, 1, 2, 10, 0) + timedelta(minutes=offset_minutes)
    high = close if high is None else high
    low = close if low is None else low
    return TechnicalPriceBar(
        symbol=symbol,
        timestamp=f"{timestamp.isoformat()}-05:00",
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source="test_1m",
    )


def present_event(symbol: str, timestamp: str, *, trigger_price: float) -> BreakoutEvent:
    return BreakoutEvent(
        event_id="event-1",
        symbol=symbol,
        event_timestamp=timestamp,
        event_type="intraday_15_minute_high_breakout",
        timeframe="intraday",
        trigger_price=trigger_price,
        reference_label="prior_15_minute_high",
        prior_high_band_or_moving_average_value=trigger_price,
        distance_above_trigger_pct=0.0,
        volume=100,
        relative_volume=2.0,
        market_regime="bull",
        source_data="test",
        data_sufficiency="Sufficient",
        quality_flag="HIGH",
        status=BREAKOUT_PRESENT,
        volume_confirmed=True,
    )


def daily_present_event(symbol: str, timestamp: str, *, trigger_price: float) -> BreakoutEvent:
    return BreakoutEvent(
        event_id="daily-event-1",
        symbol=symbol,
        event_timestamp=timestamp,
        event_type="donchian_20_day_breakout",
        timeframe="daily",
        trigger_price=trigger_price,
        reference_label="prior_20_day_high",
        prior_high_band_or_moving_average_value=trigger_price,
        distance_above_trigger_pct=0.0,
        volume=100,
        relative_volume=2.0,
        market_regime="bull",
        source_data="test",
        data_sufficiency="Sufficient",
        quality_flag="HIGH",
        status=BREAKOUT_PRESENT,
        volume_confirmed=True,
    )


def daily_ohlc_record(
    symbol: str,
    offset: int,
    *,
    close: float,
    high: float,
    low: float | None = None,
    volume: int = 100,
) -> DailyOhlcRecord:
    day = datetime(2026, 1, 1) + timedelta(days=offset)
    low = close if low is None else low
    return DailyOhlcRecord(
        symbol=symbol,
        date=day.date().isoformat(),
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source="test_daily_ohlc",
        adjusted=True,
        imported_at="2026-01-23T12:00:00-05:00",
        quality_status=QUALITY_VALID,
        warnings=[],
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
