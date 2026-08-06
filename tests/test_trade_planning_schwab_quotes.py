from __future__ import annotations

import json
import shutil
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.evidence_integrity import (
    EXECUTION_ELIGIBLE,
    EXECUTION_INELIGIBLE,
    RESEARCH_ONLY,
)
from momentum_hunter.schwab_market_data import (
    SCHWAB_QUOTE_SOURCE,
    SchwabMarketDataAuthorizationError,
    SchwabQuoteEvidenceBatch,
)
from momentum_hunter.shadow_opening import build_https_clock_skew_proof
from momentum_hunter.storage import file_sha256
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import (
    MarketTape,
    PRICE_EVIDENCE_EXECUTION_INELIGIBLE,
    build_trade_planning_report,
    execution_price_evidence_status,
    fetch_schwab_authoritative_market_tapes,
)


class TradePlanningSchwabQuoteTests(unittest.TestCase):
    def setUp(self) -> None:
        parent = Path.cwd() / "MomentumHunterData" / "data"
        parent.mkdir(parents=True, exist_ok=True)
        self.root = parent / f"_test-trade-planning-schwab-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_one_fresh_batch_grants_exact_schwab_price_authority(self) -> None:
        checked_at = datetime(2026, 8, 5, 14, 35, tzinfo=timezone.utc)
        source = ProofQuoteSource()

        tapes = fetch_schwab_authoritative_market_tapes(
            ["aaa", "BBB", "AAA"],
            quote_source=source,
            checked_at=checked_at,
        )

        self.assertEqual(1, len(source.calls))
        self.assertEqual(("AAA", "BBB"), source.calls[0][0])
        self.assertEqual({"AAA", "BBB"}, set(tapes))
        tape = tapes["AAA"]
        self.assertEqual(SCHWAB_QUOTE_SOURCE, tape.source)
        self.assertEqual(100.0, tape.current_bid)
        self.assertEqual(100.05, tape.current_ask)
        self.assertEqual("SUCCESS", tape.provider_results["schwab_quote"])
        self.assertEqual(
            EXECUTION_ELIGIBLE,
            execution_price_evidence_status(tape, as_of=checked_at),
        )
        for field_name in ("last_price", "current_bid", "current_ask"):
            evidence = tape.field_provenance[field_name]
            self.assertEqual(SCHWAB_QUOTE_SOURCE, evidence.source)
            self.assertEqual(EXECUTION_ELIGIBLE, evidence.authority)
            self.assertEqual("OAUTH_AUTHENTICATED", evidence.authentication_status)

    def test_stale_quote_is_blocked_and_cannot_be_reused_as_fresh(self) -> None:
        checked_at = datetime(2026, 8, 5, 14, 35, tzinfo=timezone.utc)
        source = ProofQuoteSource(age_seconds=31)

        tape = fetch_schwab_authoritative_market_tapes(
            ["AAA"],
            quote_source=source,
            checked_at=checked_at,
        )["AAA"]

        self.assertIn("SCHWAB_QUOTE_QUOTE_STALE", tape.warnings)
        self.assertEqual(
            EXECUTION_INELIGIBLE,
            execution_price_evidence_status(tape, as_of=checked_at),
        )

        fresh_tape = fetch_schwab_authoritative_market_tapes(
            ["AAA"],
            quote_source=ProofQuoteSource(age_seconds=1),
            checked_at=checked_at,
        )["AAA"]
        self.assertEqual(
            EXECUTION_INELIGIBLE,
            execution_price_evidence_status(
                fresh_tape,
                as_of=checked_at + timedelta(seconds=31),
            ),
        )

    def test_extended_delayed_missing_last_and_clock_failures_block(self) -> None:
        checked_at = datetime(2026, 8, 5, 14, 35, tzinfo=timezone.utc)
        cases = {
            "extended": ProofQuoteSource(session="extended"),
            "delayed": ProofQuoteSource(realtime=False),
            "missing_last": ProofQuoteSource(last=None),
            "clock": ProofQuoteSource(remote_offset_seconds=10),
        }

        for label, source in cases.items():
            with self.subTest(label=label):
                tape = fetch_schwab_authoritative_market_tapes(
                    ["AAA"],
                    quote_source=source,
                    checked_at=checked_at,
                )["AAA"]
                self.assertEqual(
                    EXECUTION_INELIGIBLE,
                    execution_price_evidence_status(tape, as_of=checked_at),
                )
                self.assertTrue(tape.warnings)
                self.assertTrue(
                    all(warning.startswith("SCHWAB_QUOTE_") for warning in tape.warnings)
                )

    def test_authorization_failure_is_sanitized_and_fails_closed(self) -> None:
        checked_at = datetime(2026, 8, 5, 14, 35, tzinfo=timezone.utc)
        source = FailingQuoteSource(
            SchwabMarketDataAuthorizationError("synthetic secret should not escape")
        )

        tape = fetch_schwab_authoritative_market_tapes(
            ["AAA"],
            quote_source=source,
            checked_at=checked_at,
        )["AAA"]

        serialized = json.dumps(tape.provider_results) + json.dumps(tape.warnings)
        self.assertIn("AUTHORIZATION_FAILED", serialized)
        self.assertNotIn("synthetic secret", serialized)
        self.assertEqual(EXECUTION_INELIGIBLE, execution_price_evidence_status(tape, as_of=checked_at))

    def test_report_uses_one_schwab_batch_and_preserves_raw_capture(self) -> None:
        generated_at = now_central()
        capture = self.write_capture(generated_at)
        before = file_sha256(capture)
        source = ProofQuoteSource()
        research_tape = MarketTape(
            last_price=99.0,
            current_bid=98.9,
            current_ask=99.1,
            spread_percent=0.2,
            intraday_volume=2_000_000,
            average_daily_volume_20=1_000_000,
            relative_volume=2.0,
            source="nasdaq+yahoo_chart",
            provider_results={"nasdaq_info": "SUCCESS", "yahoo_chart": "SUCCESS"},
        )

        with (
            patch("momentum_hunter.trade_planning.build_http_session", return_value=object()),
            patch("momentum_hunter.trade_planning.fetch_price_bars", return_value=[]),
            patch("momentum_hunter.trade_planning.fetch_market_tape", return_value=research_tape),
        ):
            report = build_trade_planning_report(
                capture,
                fetch_bars=True,
                fetch_market_data=True,
                as_of=generated_at,
                schwab_quote_source=source,
            )

        self.assertEqual(1, len(source.calls))
        self.assertEqual(("AAA", "BBB"), source.calls[0][0])
        self.assertEqual(before, file_sha256(capture))
        for row in report.rows:
            self.assertEqual(EXECUTION_ELIGIBLE, row.price_evidence_status)
            self.assertNotIn(
                PRICE_EVIDENCE_EXECUTION_INELIGIBLE,
                row.trade_plan.blocking_reasons,
            )
            self.assertEqual(SCHWAB_QUOTE_SOURCE, row.price_evidence["current_bid"].source)
            self.assertEqual(RESEARCH_ONLY, row.price_evidence["resistance_level"].authority)
            self.assertNotIn("yahoo_quote", row.market_tape.provider_results)

    def test_failed_schwab_batch_never_promotes_research_fallback(self) -> None:
        generated_at = now_central()
        capture = self.write_capture(generated_at, symbols=("AAA",))
        research_tape = MarketTape(
            last_price=99.0,
            current_bid=98.9,
            current_ask=99.1,
            spread_percent=0.2,
            intraday_volume=2_000_000,
            average_daily_volume_20=1_000_000,
            relative_volume=2.0,
            source="nasdaq+yahoo_chart",
        )
        source = FailingQuoteSource(
            SchwabMarketDataAuthorizationError("synthetic authorization failure")
        )

        with (
            patch("momentum_hunter.trade_planning.build_http_session", return_value=object()),
            patch("momentum_hunter.trade_planning.fetch_price_bars", return_value=[]),
            patch("momentum_hunter.trade_planning.fetch_market_tape", return_value=research_tape),
        ):
            row = build_trade_planning_report(
                capture,
                fetch_market_data=True,
                as_of=generated_at,
                schwab_quote_source=source,
            ).rows[0]

        self.assertEqual(98.9, row.current_bid)
        self.assertEqual(EXECUTION_INELIGIBLE, row.price_evidence_status)
        self.assertEqual(RESEARCH_ONLY, row.price_evidence["current_bid"].authority)
        self.assertIn("SCHWAB_QUOTE_AUTHORIZATION_FAILED", row.market_tape.warnings)
        self.assertIn(
            PRICE_EVIDENCE_EXECUTION_INELIGIBLE,
            row.trade_plan.blocking_reasons,
        )

    def write_capture(
        self,
        captured_at: datetime,
        *,
        symbols: tuple[str, ...] = ("AAA", "BBB"),
    ) -> Path:
        path = self.root / "opening.json"
        path.write_text(
            json.dumps(
                {
                    "capture_time": captured_at.isoformat(),
                    "session": "opening",
                    "provider": "finviz",
                    "scanner": {"name": "Institutional Momentum"},
                    "candidates": [candidate_payload(symbol) for symbol in symbols],
                }
            ),
            encoding="utf-8",
        )
        return path


class ProofQuoteSource:
    def __init__(
        self,
        *,
        age_seconds: int = 1,
        session: str = "regular",
        realtime: bool = True,
        last: float | None = 100.02,
        remote_offset_seconds: int = 0,
    ) -> None:
        self.age_seconds = age_seconds
        self.session = session
        self.realtime = realtime
        self.last = last
        self.remote_offset_seconds = remote_offset_seconds
        self.calls: list[tuple[tuple[str, ...], datetime]] = []

    def quotes_with_clock(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime | None = None,
    ) -> SchwabQuoteEvidenceBatch:
        assert decision_at is not None
        self.calls.append((tuple(symbols), decision_at))
        observed_at = decision_at - timedelta(seconds=self.age_seconds)
        return SchwabQuoteEvidenceBatch(
            quotes={
                symbol: proof_quote(
                    symbol,
                    observed_at,
                    session=self.session,
                    realtime=self.realtime,
                    last=self.last,
                )
                for symbol in symbols
            },
            clock_skew_proof=build_https_clock_skew_proof(
                request_started_at=decision_at,
                response_received_at=decision_at,
                remote_date_header=format_datetime(
                    decision_at + timedelta(seconds=self.remote_offset_seconds)
                ),
                source_identity="synthetic-test-https-date",
            ),
        )


class FailingQuoteSource:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def quotes_with_clock(self, symbols, *, decision_at=None):
        del symbols, decision_at
        raise self.error


def proof_quote(
    symbol: str,
    observed_at: datetime,
    *,
    session: str,
    realtime: bool,
    last: float | None,
) -> dict[str, object]:
    timestamp = observed_at.isoformat()
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "provider_quote_timestamp": timestamp,
        "provider_bid_timestamp": timestamp,
        "provider_ask_timestamp": timestamp,
        "bid": 100.0,
        "ask": 100.05,
        "last": last,
        "volume": 10_000,
        "session": session,
        "trading_state": "tradable",
        "realtime": realtime,
        "security_status": "Normal",
        "source": SCHWAB_QUOTE_SOURCE,
    }


def candidate_payload(symbol: str) -> dict[str, object]:
    return {
        "ticker": symbol,
        "company": f"{symbol} Corp",
        "price": 99.0,
        "percent_change": 5.0,
        "volume": 2_000_000,
        "relative_volume": 2.0,
        "market_cap": 5_000_000_000,
        "sector": "Technology",
        "industry": "Software",
        "score": 80,
        "freshness_score": 90,
        "news": [
            {
                "headline": f"{symbol} raises guidance",
                "source": "Finviz",
                "published_at": "2026-08-05T08:30:00-05:00",
                "url": "https://example.test/story",
                "summary": "",
            }
        ],
        "news_stack": {
            "article_count": 1,
            "freshest_headline": f"{symbol} raises guidance",
            "freshness_score": 90,
            "freshness": "HOT",
        },
    }


if __name__ == "__main__":
    unittest.main()
