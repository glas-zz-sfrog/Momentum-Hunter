from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.outcomes import PriceBar
from momentum_hunter.storage import file_sha256
from momentum_hunter.trade_planning import (
    MarketTape,
    build_trade_planning_report,
    event_polling_interval_seconds,
    export_trade_planning_report,
    fetch_nasdaq_market_tape,
    fetch_yahoo_market_tape,
    rvol_type_for_time,
)


class TradePlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_parent = Path.cwd() / "MomentumHunterData" / "data"
        self.tmp_parent.mkdir(parents=True, exist_ok=True)
        self.root = self.tmp_parent / f"_test-trade-planning-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.capture_path = self.root / "morning.json"
        self.capture_path.write_text(
            json.dumps(
                {
                    "capture_time": "2026-06-17T07:00:00-05:00",
                    "session": "morning",
                    "provider": "finviz",
                    "scanner": {"name": "Institutional Momentum"},
                    "candidates": [
                        candidate_payload(
                            "AAA",
                            price=10.0,
                            score=90,
                            freshness_score=95,
                            volume=30_000_000,
                            market_cap=15_000_000_000,
                            sector="Technology",
                            industry="Software",
                            headline="AAA raises guidance after Fed rate cut and AI partnership",
                        ),
                        candidate_payload(
                            "BBB",
                            price=20.0,
                            score=70,
                            freshness_score=50,
                            volume=4_000_000,
                            market_cap=3_000_000_000,
                            sector="Healthcare",
                            industry="Medical Devices",
                            headline="BBB shares rise on analyst note",
                        ),
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_trade_plan_uses_daily_bars_for_levels_and_risk_reward(self) -> None:
        report = build_trade_planning_report(
            self.capture_path,
            bars_by_ticker={
                "AAA": [
                    PriceBar("2026-06-12", high=9.8, low=9.1, close=9.5),
                    PriceBar("2026-06-15", high=10.2, low=9.4, close=10.0, volume=100_000),
                    PriceBar("2026-06-16", high=10.4, low=9.8, close=10.1, volume=100_000),
                ]
            },
            market_tape_by_ticker={
                "AAA": MarketTape(
                    last_price=10.15,
                    premarket_price=10.25,
                    premarket_percent=1.49,
                    premarket_volume=600_000,
                    intraday_volume=600_000,
                    average_daily_volume_20=100_000,
                    current_bid=10.24,
                    current_ask=10.26,
                    spread_percent=0.2,
                    relative_volume=1.8,
                    source="test",
                    warnings=["QUOTE_HTTP_401"],
                )
            },
            as_of=parse_dt("2026-06-17T07:00:00-05:00"),
        )

        top = report.rows[0]
        self.assertEqual("AAA", top.symbol)
        self.assertEqual(10.4, top.technical_levels.previous_day_high)
        self.assertEqual(9.8, top.technical_levels.previous_day_low)
        self.assertEqual(10.1, top.technical_levels.previous_day_close)
        self.assertEqual(10.4, top.trade_plan.bullish_entry)
        self.assertEqual(9.8, top.trade_plan.bullish_stop)
        self.assertEqual(2.0, top.trade_plan.risk_reward_ratio)
        self.assertEqual("EXECUTION_READY_PREMARKET", top.trade_plan.readiness)
        self.assertEqual("HIGH", top.trade_plan.confidence)
        self.assertEqual("PREMARKET_RVOL", top.rvol_type)
        self.assertEqual(6.0, top.relative_volume)
        self.assertIn("QUOTE_HTTP_401", top.trade_plan.warnings)

    def test_missing_daily_bars_warns_and_still_builds_scaffold(self) -> None:
        report = build_trade_planning_report(self.capture_path, as_of=parse_dt("2026-06-17T07:00:00-05:00"))

        top = report.rows[0]
        self.assertIn("DATA_REQUIRED_DAILY_BARS", top.trade_plan.warnings)
        self.assertIn("TECHNICAL_LEVELS_ESTIMATED", top.trade_plan.warnings)
        self.assertIsNotNone(top.trade_plan.bullish_entry)
        self.assertEqual("LOW", top.trade_plan.confidence)
        self.assertEqual("DO_NOT_TRADE_MISSING_DATA", top.trade_plan.readiness)
        self.assertIn("MISSING_PREMARKET_VOLUME", top.trade_plan.blocking_reasons)

    def test_report_generation_does_not_mutate_raw_capture(self) -> None:
        before = file_sha256(self.capture_path)

        report = build_trade_planning_report(self.capture_path)
        export_trade_planning_report(report, self.root / "reports")

        self.assertEqual(before, file_sha256(self.capture_path))

    def test_exports_csv_json_and_markdown(self) -> None:
        report = build_trade_planning_report(self.capture_path)
        paths = export_trade_planning_report(report, self.root / "reports")

        self.assertTrue(paths["csv"].exists())
        self.assertTrue(paths["json"].exists())
        self.assertTrue(paths["report"].exists())
        self.assertIn("Top 5 Opportunities For $500", paths["report"].read_text(encoding="utf-8"))
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        self.assertEqual("trade-planning-composite-v1", payload["metadata"]["composite_profile"])
        self.assertIn("market_tape", payload["candidates"][0])
        self.assertIn("state_transition_log", payload)
        self.assertIn("fed_news_summary", payload)

    def test_rvol_type_splits_by_market_time(self) -> None:
        self.assertEqual("PREMARKET_RVOL", rvol_type_for_time(parse_dt("2026-06-17T07:00:00-05:00")))
        self.assertEqual("INTRADAY_RVOL", rvol_type_for_time(parse_dt("2026-06-17T09:00:00-05:00")))
        self.assertEqual("DAILY_RVOL", rvol_type_for_time(parse_dt("2026-06-17T15:10:00-05:00")))

    def test_event_mode_polling_schedule(self) -> None:
        self.assertEqual(900, event_polling_interval_seconds(parse_dt("2026-06-17T12:54:00-05:00")))
        self.assertEqual(60, event_polling_interval_seconds(parse_dt("2026-06-17T12:55:00-05:00")))
        self.assertEqual(120, event_polling_interval_seconds(parse_dt("2026-06-17T13:10:00-05:00")))
        self.assertEqual(60, event_polling_interval_seconds(parse_dt("2026-06-17T13:30:00-05:00")))
        self.assertEqual(900, event_polling_interval_seconds(parse_dt("2026-06-17T14:30:00-05:00")))

    def test_event_report_logs_state_transitions_and_fed_news(self) -> None:
        state_path = self.root / "state.json"
        state_path.write_text(
            json.dumps({"states": [{"symbol": "AAA", "state": "PLANNING_SCAFFOLD"}]}),
            encoding="utf-8",
        )
        report = build_trade_planning_report(
            self.capture_path,
            bars_by_ticker={
                "AAA": [PriceBar("2026-06-16", high=10.4, low=9.8, close=10.1, volume=100_000)],
            },
            market_tape_by_ticker={
                "AAA": MarketTape(
                    last_price=10.45,
                    premarket_price=10.25,
                    premarket_percent=1.49,
                    premarket_volume=250_000,
                    intraday_volume=250_000,
                    average_daily_volume_20=100_000,
                    current_bid=10.24,
                    current_ask=10.26,
                    spread_percent=0.2,
                    source="test",
                )
            },
            event_mode=True,
            as_of=parse_dt("2026-06-17T13:35:00-05:00"),
            previous_state_path=state_path,
        )

        self.assertEqual(60, report.polling_interval_seconds)
        self.assertTrue(report.event_mode)
        self.assertEqual("AAA", report.state_transition_log[0]["symbol"])
        self.assertEqual("PLANNING_SCAFFOLD", report.state_transition_log[0]["old_state"])
        self.assertEqual("EXECUTION_READY_TRADE", report.state_transition_log[0]["new_state"])
        self.assertTrue(any("rate" in item["matched_keywords"] or "fed" in item["matched_keywords"] for item in report.fed_news_summary))

    def test_price_already_above_entry_generates_reclaim_entry_warning(self) -> None:
        report = build_trade_planning_report(
            self.capture_path,
            bars_by_ticker={
                "AAA": [PriceBar("2026-06-16", high=10.4, low=9.8, close=10.1, volume=100_000)],
            },
            market_tape_by_ticker={
                "AAA": MarketTape(
                    last_price=10.7,
                    premarket_price=10.7,
                    premarket_percent=6.0,
                    premarket_volume=700_000,
                    intraday_volume=700_000,
                    average_daily_volume_20=100_000,
                    current_bid=10.69,
                    current_ask=10.71,
                    spread_percent=0.19,
                    source="test",
                )
            },
            as_of=parse_dt("2026-06-17T07:00:00-05:00"),
        )

        top = next(row for row in report.rows if row.symbol == "AAA")
        self.assertIn("PRICE_ALREADY_ABOVE_ENTRY", top.trade_plan.warnings)
        self.assertGreater(top.trade_plan.bullish_entry or 0, 10.7)

    def test_empty_event_sections_use_explicit_messages(self) -> None:
        quiet_capture = self.root / "quiet-morning.json"
        quiet_capture.write_text(
            json.dumps(
                {
                    "capture_time": "2026-06-17T07:00:00-05:00",
                    "session": "morning",
                    "provider": "finviz",
                    "scanner": {"name": "Institutional Momentum"},
                    "candidates": [
                        candidate_payload(
                            "CCC",
                            price=10.0,
                            score=70,
                            freshness_score=50,
                            volume=5_000_000,
                            market_cap=3_000_000_000,
                            sector="Technology",
                            industry="Software",
                            headline="CCC shares rise on product update",
                        )
                    ],
                }
            ),
            encoding="utf-8",
        )
        report = build_trade_planning_report(
            quiet_capture,
            bars_by_ticker={"CCC": [PriceBar("2026-06-16", high=10.4, low=9.8, close=10.1, volume=100_000)]},
            market_tape_by_ticker={
                "CCC": MarketTape(
                    last_price=10.15,
                    premarket_price=10.2,
                    premarket_percent=0.5,
                    premarket_volume=100_000,
                    intraday_volume=100_000,
                    average_daily_volume_20=100_000,
                    current_bid=10.19,
                    current_ask=10.21,
                    spread_percent=0.2,
                    source="test",
                )
            },
            event_mode=True,
            as_of=parse_dt("2026-06-17T07:00:00-05:00"),
            previous_state_path=self.root / "missing-state.json",
        )
        paths = export_trade_planning_report(report, self.root / "reports")
        text = paths["report"].read_text(encoding="utf-8")

        self.assertIn("STATE TRANSITIONS: NONE YET", text)
        self.assertIn("FED NEWS SUMMARY: NO FED HEADLINES DETECTED", text)

    def test_yahoo_quote_tape_parser_calculates_spread_and_relative_volume(self) -> None:
        tape = fetch_yahoo_market_tape(
            FakeSession(
                {
                    "quoteResponse": {
                        "result": [
                            {
                                "regularMarketPrice": 10.2,
                                "regularMarketPreviousClose": 10.0,
                                "preMarketPrice": 10.4,
                                "preMarketVolume": 300000,
                                "bid": 10.39,
                                "ask": 10.41,
                                "regularMarketVolume": 1800000,
                                "averageDailyVolume10Day": 1000000,
                            }
                        ]
                    }
                }
            ),
            "AAA",
        )

        self.assertEqual(10.4, tape.premarket_price)
        self.assertEqual(4.0, tape.premarket_percent)
        self.assertEqual(300000, tape.premarket_volume)
        self.assertEqual(0.19, tape.spread_percent)
        self.assertEqual(1.8, tape.relative_volume)
        self.assertEqual([], tape.warnings)

    def test_nasdaq_tape_parser_returns_bid_ask_premarket_volume_and_relative_volume(self) -> None:
        tape = fetch_nasdaq_market_tape(
            RouteSession(
                {
                    "info": {
                        "data": {
                            "marketStatus": "Pre-Market",
                            "primaryData": {
                                "lastSalePrice": "$331.30",
                                "percentageChange": "+0.05%",
                                "bidPrice": "$330.70",
                                "askPrice": "$331.00",
                                "volume": "190,946.183652",
                            },
                        }
                    },
                    "summary": {
                        "data": {
                            "summaryData": {
                                "ShareVolume": {"value": "190,946.183652"},
                                "AverageVolume": {"value": "19,163,627"},
                            },
                            "bidAsk": {
                                "Bid * Size": {"value": "$330.70 * 2"},
                                "Ask * Size": {"value": "$331.00 * 3"},
                            },
                        }
                    },
                    "extended": {
                        "data": {
                            "infoTable": {
                                "rows": [
                                    {
                                        "consolidated": "$330.3379 -0.8021 (-0.24%)",
                                        "volume": "191,018",
                                    }
                                ]
                            }
                        }
                    },
                }
            ),
            "JPM",
        )

        self.assertEqual(330.34, tape.premarket_price)
        self.assertEqual(-0.24, tape.premarket_percent)
        self.assertEqual(191018, tape.premarket_volume)
        self.assertEqual(330.7, tape.current_bid)
        self.assertEqual(331.0, tape.current_ask)
        self.assertEqual(0.09, tape.spread_percent)
        self.assertEqual(0.01, tape.relative_volume)
        self.assertEqual([], tape.warnings)

    def test_yahoo_chart_fallback_recovers_premarket_when_quote_is_unauthorized(self) -> None:
        tape = fetch_yahoo_market_tape(
            FakeSession(
                {
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "regularMarketPrice": 10.5,
                                    "previousClose": 10.0,
                                    "currentTradingPeriod": {
                                        "pre": {"start": 1000},
                                        "regular": {"start": 2000},
                                    },
                                },
                                "timestamp": [1100, 1200, 2100],
                                "indicators": {
                                    "quote": [
                                        {
                                            "close": [10.2, 10.4, 10.6],
                                            "volume": [1000, 2000, 3000],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                },
                quote_status=401,
            ),
            "AAA",
        )

        self.assertEqual(10.4, tape.premarket_price)
        self.assertEqual(4.0, tape.premarket_percent)
        self.assertEqual(3000, tape.premarket_volume)
        self.assertIn("MISSING_BID_ASK", tape.warnings)
        self.assertIn("QUOTE_HTTP_401", tape.warnings)

    def test_wide_spread_blocks_tradeability(self) -> None:
        report = build_trade_planning_report(
            self.capture_path,
            bars_by_ticker={
                "AAA": [
                    PriceBar("2026-06-16", high=10.4, low=9.8, close=10.1),
                ]
            },
            market_tape_by_ticker={
                "AAA": MarketTape(
                    last_price=10.15,
                    premarket_price=10.25,
                    premarket_percent=1.49,
                    premarket_volume=250_000,
                    average_daily_volume_20=100_000,
                    current_bid=10.0,
                    current_ask=10.5,
                    spread_percent=4.88,
                    relative_volume=1.8,
                    source="test",
                    warnings=["WIDE_SPREAD"],
                )
            },
            as_of=parse_dt("2026-06-17T07:00:00-05:00"),
        )

        top = next(row for row in report.rows if row.symbol == "AAA")
        self.assertEqual("DO_NOT_TRADE_POOR_DATA", top.trade_plan.readiness)
        self.assertEqual("LOW", top.trade_plan.tradeability)
        self.assertIn("SPREAD_TOO_WIDE", top.trade_plan.blocking_reasons)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self, payload: dict, quote_status: int = 200) -> None:
        self.payload = payload
        self.quote_status = quote_status

    def get(self, url: str, timeout: int = 20) -> FakeResponse:
        if "/v7/finance/quote" in url:
            return FakeResponse(self.payload, self.quote_status)
        return FakeResponse(self.payload)


class RouteSession:
    def __init__(self, payloads: dict[str, dict]) -> None:
        self.payloads = payloads

    def get(self, url: str, headers: dict | None = None, timeout: int = 20) -> FakeResponse:
        if "/info" in url:
            return FakeResponse(self.payloads["info"])
        if "/summary" in url:
            return FakeResponse(self.payloads["summary"])
        if "/extended-trading" in url:
            return FakeResponse(self.payloads["extended"])
        return FakeResponse({})


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def candidate_payload(
    ticker: str,
    *,
    price: float,
    score: int,
    freshness_score: int,
    volume: int,
    market_cap: int,
    sector: str,
    industry: str,
    headline: str,
) -> dict:
    return {
        "ticker": ticker,
        "company": f"{ticker} Corp",
        "price": price,
        "percent_change": 5.0,
        "volume": volume,
        "relative_volume": 1.5,
        "market_cap": market_cap,
        "sector": sector,
        "industry": industry,
        "float_shares": 10_000_000,
        "premarket_volume": None,
        "gap_percent": None,
        "atr": None,
        "news": [
            {
                "headline": headline,
                "source": "Finviz",
                "published_at": "2026-06-17T06:00:00-05:00",
                "url": "https://example.test/story",
                "summary": "",
            }
        ],
        "score": score,
        "news_stack": {
            "article_count": 1,
            "known_timestamp_count": 1,
            "freshest_headline": headline,
            "freshness_score": freshness_score,
            "freshness": "HOT",
        },
        "freshness_score": freshness_score,
        "freshness": "HOT",
    }


if __name__ == "__main__":
    unittest.main()
