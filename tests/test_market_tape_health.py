from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime
from pathlib import Path

from momentum_hunter.market_tape_health import (
    build_market_tape_health_report,
    export_market_tape_health_report,
)
from momentum_hunter.outcomes import build_http_session
from momentum_hunter.storage import file_sha256


class MarketTapeHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path.cwd() / "MomentumHunterData" / "data" / f"_test-market-tape-health-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)
        self.raw_capture = self.root / "morning.json"
        self.raw_capture.write_text(json.dumps({"capture_time": "2026-06-18T07:00:00-05:00"}), encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_market_data_session_ignores_dead_environment_proxy(self) -> None:
        session = build_http_session()

        self.assertFalse(session.trust_env)

    def test_provider_health_report_marks_nasdaq_tape_usable_when_yahoo_quote_is_401(self) -> None:
        report = build_market_tape_health_report(
            ["AAA"],
            session=HealthSession(),
            generated_at=datetime.fromisoformat("2026-06-18T07:00:00-05:00"),
        )

        self.assertEqual(1, report.usable_symbol_count)
        self.assertEqual(0, report.missing_symbol_count)
        combined = next(item for item in report.attempts if item.provider == "combined")
        nasdaq = next(item for item in report.attempts if item.provider == "nasdaq")
        yahoo = next(item for item in report.attempts if item.provider == "yahoo_quote_plus_chart")

        self.assertTrue(combined.usable_for_alerting)
        self.assertEqual("SUCCESS", combined.status)
        self.assertIn("QUOTE_HTTP_401", combined.warnings)
        self.assertTrue(nasdaq.usable_for_alerting)
        self.assertEqual([], nasdaq.warnings)
        self.assertIn("last_price", nasdaq.fields_returned)
        self.assertEqual("PARTIAL", yahoo.status)
        self.assertIn("QUOTE_HTTP_401", yahoo.warnings)

    def test_provider_health_export_is_deterministic_and_does_not_mutate_raw_capture(self) -> None:
        before = file_sha256(self.raw_capture)
        report = build_market_tape_health_report(
            ["AAA", "AAA", "bbb"],
            session=HealthSession(),
            generated_at=datetime.fromisoformat("2026-06-18T07:00:00-05:00"),
        )
        paths = export_market_tape_health_report(report, self.root / "reports")

        payload = json.loads(paths["json"].read_text(encoding="utf-8"))

        self.assertEqual(["AAA", "BBB"], payload["report"]["symbols"])
        self.assertEqual("market_tape_health_v1", payload["engine_version"])
        self.assertEqual(8, len(payload["attempts"]))
        self.assertTrue(paths["csv"].exists())
        self.assertTrue(paths["report"].exists())
        self.assertEqual(before, file_sha256(self.raw_capture))


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload


class HealthSession:
    def get(self, url: str, headers: dict | None = None, timeout: int = 20) -> FakeResponse:
        if "api.nasdaq.com" in url and "/info" in url:
            return FakeResponse(nasdaq_info_payload())
        if "api.nasdaq.com" in url and "/summary" in url:
            return FakeResponse(nasdaq_summary_payload())
        if "api.nasdaq.com" in url and "/extended-trading" in url:
            return FakeResponse(nasdaq_extended_payload())
        if "/v7/finance/quote" in url:
            return FakeResponse({"finance": {"error": {"code": "Unauthorized"}}}, status_code=401)
        if "/v8/finance/chart" in url:
            return FakeResponse(yahoo_chart_payload())
        return FakeResponse({}, status_code=404)


def nasdaq_info_payload() -> dict:
    return {
        "data": {
            "marketStatus": "Pre-Market",
            "primaryData": {
                "lastSalePrice": "$10.20",
                "percentageChange": "+2.00%",
                "bidPrice": "$10.19",
                "askPrice": "$10.21",
                "volume": "1,000,000",
            },
        }
    }


def nasdaq_summary_payload() -> dict:
    return {
        "data": {
            "summaryData": {
                "ShareVolume": {"value": "1,000,000"},
                "AverageVolume": {"value": "2,000,000"},
            },
            "bidAsk": {
                "Bid * Size": {"value": "$10.19 * 1"},
                "Ask * Size": {"value": "$10.21 * 2"},
            },
        }
    }


def nasdaq_extended_payload() -> dict:
    return {
        "data": {
            "infoTable": {
                "rows": [
                    {
                        "consolidated": "$10.40 +0.20 (+2.00%)",
                        "volume": "600,000",
                    }
                ]
            }
        }
    }


def yahoo_chart_payload() -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": 10.25,
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
                                "close": [10.2, 10.3, 10.25],
                                "volume": [1000, 2000, 3000],
                            }
                        ]
                    },
                }
            ]
        }
    }


if __name__ == "__main__":
    unittest.main()
