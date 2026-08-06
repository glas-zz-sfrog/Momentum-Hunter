from __future__ import annotations

import json
import shutil
import unittest
import uuid
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_BLOCKED,
    CATALYST_SCORE_SUPPORTED,
    DIRECT_ISSUER,
    EXECUTION_INELIGIBLE,
    RESEARCH_ONLY,
    UNRESOLVED,
    classify_catalyst_attribution,
    extract_mentioned_ticker,
    make_price_evidence,
)
from momentum_hunter.models import Candidate, NewsItem, NewsStack
from momentum_hunter.outcomes import PriceBar
from momentum_hunter.trade_planning import (
    CATALYST_ATTRIBUTION_UNRESOLVED,
    COMPOSITE_CONFIGURATION_FINGERPRINT,
    COMPOSITE_PROFILE,
    DO_NOT_TRADE_UNTRUSTED_EVIDENCE,
    EVIDENCE_INTEGRITY_SCHEMA_VERSION,
    MarketTape,
    PRICE_EVIDENCE_EXECUTION_INELIGIBLE,
    build_trade_planning_report,
    composite_score,
    export_trade_planning_report,
    fetch_market_tape,
    overlay_tapes,
    risk_on_score,
)


class EvidenceIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        parent = Path.cwd() / "MomentumHunterData" / "data"
        parent.mkdir(parents=True, exist_ok=True)
        self.root = parent / f"_test-evidence-integrity-{uuid.uuid4().hex}"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_direct_issuer_catalyst_is_supported(self) -> None:
        candidate = candidate_for(
            "MSFT",
            "Microsoft Corp",
            "Microsoft raises cloud guidance",
        )

        attribution = classify_catalyst_attribution(
            candidate,
            candidate.news_stack.freshest_headline,
        )

        self.assertEqual(DIRECT_ISSUER, attribution.relationship_type)
        self.assertEqual(CATALYST_SCORE_SUPPORTED, attribution.score_authority)
        self.assertEqual("Finviz", attribution.source_publisher)
        self.assertEqual("MSFT", attribution.candidate_ticker)

    def test_unrelated_company_catalyst_is_unresolved_and_blocked(self) -> None:
        candidate = candidate_for(
            "GOOGL",
            "Alphabet Inc",
            "Absolutely the right time for geothermal Q&A with Baker Hughes Geothermal VP",
        )

        attribution = classify_catalyst_attribution(
            candidate,
            candidate.news_stack.freshest_headline,
        )

        self.assertEqual(UNRESOLVED, attribution.relationship_type)
        self.assertEqual(CATALYST_SCORE_BLOCKED, attribution.score_authority)
        self.assertIsNone(attribution.mentioned_ticker)
        self.assertIn("does not prove", attribution.relationship_evidence)

    def test_foreign_ticker_is_preserved_without_claiming_peer_relationship(self) -> None:
        candidate = candidate_for(
            "CMCSA",
            "Comcast Corp",
            "DIS Stock Eyes Three-Month Losing Streak Ahead Of Earnings",
        )

        attribution = classify_catalyst_attribution(
            candidate,
            candidate.news_stack.freshest_headline,
        )

        self.assertEqual("DIS", attribution.mentioned_ticker)
        self.assertEqual(UNRESOLVED, attribution.relationship_type)
        self.assertEqual(CATALYST_SCORE_BLOCKED, attribution.score_authority)

    def test_mixed_case_company_word_is_not_invented_as_ticker(self) -> None:
        self.assertIsNone(extract_mentioned_ticker("Google shares rise after product update"))

    def test_successful_nasdaq_fields_do_not_inherit_yahoo_401(self) -> None:
        provider_time = "2026-08-03T08:35:01-05:00"
        received_at = "2026-08-03T08:35:02-05:00"
        nasdaq = MarketTape(
            last_price=368.24,
            current_bid=368.12,
            current_ask=368.26,
            source="nasdaq",
            field_provenance={
                name: make_price_evidence(
                    label="FRESH PROVIDER QUOTE",
                    source="nasdaq_info",
                    provider_timestamp=provider_time,
                    local_receipt_timestamp=received_at,
                    authentication_status="NOT_REQUIRED",
                    result_status="SUCCESS",
                )
                for name in ("last_price", "current_bid", "current_ask")
            },
            provider_results={
                "nasdaq_info": "SUCCESS",
                "nasdaq_summary": "SUCCESS",
            },
        )
        yahoo = MarketTape(
            source="yahoo_quote+yahoo_chart",
            warnings=["QUOTE_HTTP_401"],
            provider_results={
                "yahoo_quote": "HTTP_401",
                "yahoo_chart": "SUCCESS",
            },
        )

        merged = overlay_tapes(primary=nasdaq, fallback=yahoo)

        self.assertEqual(368.12, merged.current_bid)
        self.assertEqual("nasdaq_info", merged.field_provenance["current_bid"].source)
        self.assertEqual("SUCCESS", merged.field_provenance["current_bid"].result_status)
        self.assertEqual(RESEARCH_ONLY, merged.field_provenance["current_bid"].authority)
        self.assertEqual("HTTP_401", merged.provider_results["yahoo_quote"])
        self.assertIn("QUOTE_HTTP_401", merged.warnings)

    def test_fetch_market_tape_does_not_call_unsupported_yahoo_quote_endpoint(self) -> None:
        session = CombinedProviderSession()
        tape = fetch_market_tape(session, "GOOGL")

        self.assertEqual(368.12, tape.current_bid)
        self.assertEqual(368.26, tape.current_ask)
        self.assertEqual("nasdaq_info", tape.field_provenance["current_bid"].source)
        self.assertEqual("SUCCESS", tape.field_provenance["current_bid"].result_status)
        self.assertEqual("SUCCESS", tape.provider_results["nasdaq_info"])
        self.assertNotIn("yahoo_quote", tape.provider_results)
        self.assertNotIn("QUOTE_HTTP_401", tape.warnings)
        self.assertFalse(any("/v7/finance/quote" in url for url in session.urls))

    def test_report_enforces_blocked_catalyst_and_price_authority(self) -> None:
        capture = self.write_capture(
            "GOOGL",
            "Alphabet Inc",
            "Absolutely the right time for geothermal Q&A with Baker Hughes Geothermal VP",
        )
        tape = MarketTape(
            last_price=368.24,
            current_bid=368.12,
            current_ask=368.26,
            spread_percent=0.04,
            intraday_volume=1_500_000,
            average_daily_volume_20=1_000_000,
            relative_volume=1.5,
            source="nasdaq+yahoo_quote+yahoo_chart",
            warnings=["QUOTE_HTTP_401"],
            provider_results={
                "nasdaq_info": "SUCCESS",
                "yahoo_quote": "HTTP_401",
                "yahoo_chart": "SUCCESS",
            },
            field_provenance={
                name: make_price_evidence(
                    label="FRESH PROVIDER QUOTE",
                    source="nasdaq_info",
                    provider_timestamp="2026-08-03T08:35:01-05:00",
                    local_receipt_timestamp="2026-08-03T08:35:02-05:00",
                    authentication_status="NOT_REQUIRED",
                    result_status="SUCCESS",
                )
                for name in ("last_price", "current_bid", "current_ask")
            },
        )
        report = build_trade_planning_report(
            capture,
            bars_by_ticker={
                "GOOGL": [
                    PriceBar(
                        "2026-07-31",
                        high=370.0,
                        low=360.0,
                        close=365.0,
                        volume=1_000_000,
                    )
                ]
            },
            market_tape_by_ticker={"GOOGL": tape},
            as_of=datetime.fromisoformat("2026-08-03T08:35:04-05:00"),
        )
        row = report.rows[0]

        self.assertEqual(EXECUTION_INELIGIBLE, row.price_evidence_status)
        self.assertEqual(UNRESOLVED, row.catalyst_attribution.relationship_type)
        self.assertEqual(CATALYST_SCORE_BLOCKED, row.catalyst_attribution.score_authority)
        self.assertEqual(0, row.authoritative_catalyst_confidence)
        self.assertEqual(0.0, row.catalyst_score_contribution)
        self.assertEqual(
            composite_score(
                candidate_for(
                    "GOOGL",
                    "Alphabet Inc",
                    "Absolutely the right time for geothermal Q&A with Baker Hughes Geothermal VP",
                ),
                row.technical_levels,
                row.trade_plan,
                0,
            ),
            row.composite_score,
        )
        self.assertEqual(DO_NOT_TRADE_UNTRUSTED_EVIDENCE, row.trade_plan.readiness)
        self.assertIn(
            PRICE_EVIDENCE_EXECUTION_INELIGIBLE,
            row.trade_plan.blocking_reasons,
        )
        self.assertIn(
            CATALYST_ATTRIBUTION_UNRESOLVED,
            row.trade_plan.blocking_reasons,
        )
        required_fields = {
            "last_price",
            "premarket_price",
            "current_bid",
            "current_ask",
            "previous_day_high",
            "previous_day_low",
            "previous_day_close",
            "five_day_high",
            "twenty_day_high",
            "support_level",
            "resistance_level",
            "bullish_entry",
            "bullish_stop",
            "bullish_target_1",
            "bullish_target_2",
        }
        self.assertEqual(required_fields, set(row.price_evidence))
        for evidence in row.price_evidence.values():
            payload = asdict(evidence)
            self.assertIn("provider_timestamp", payload)
            self.assertIn("local_receipt_timestamp", payload)
            self.assertIn("age_seconds", payload)
            self.assertTrue(payload["authentication_status"])
            self.assertTrue(payload["result_status"])
            self.assertEqual(RESEARCH_ONLY, payload["authority"])

    def test_direct_issuer_retains_authorized_catalyst_points(self) -> None:
        capture = self.write_capture(
            "MSFT",
            "Microsoft Corp",
            "Microsoft raises cloud guidance",
        )

        row = build_trade_planning_report(
            capture,
            as_of=datetime.fromisoformat("2026-08-03T08:35:04-05:00"),
        ).rows[0]

        self.assertEqual(CATALYST_SCORE_SUPPORTED, row.catalyst_attribution.score_authority)
        self.assertEqual(row.catalyst_confidence, row.authoritative_catalyst_confidence)
        self.assertEqual(
            round(row.catalyst_confidence * 0.05, 2),
            row.catalyst_score_contribution,
        )
        self.assertNotIn(
            CATALYST_ATTRIBUTION_UNRESOLVED,
            row.trade_plan.blocking_reasons,
        )
        self.assertIn(
            PRICE_EVIDENCE_EXECUTION_INELIGIBLE,
            row.trade_plan.blocking_reasons,
        )

    def test_blocked_ai_cluster_adds_no_risk_on_bonus(self) -> None:
        capture = self.write_capture(
            "AMZN",
            "Amazon.com Inc",
            "Goldman Sachs has stark message for AI stock investors",
        )

        row = build_trade_planning_report(
            capture,
            as_of=datetime.fromisoformat("2026-08-03T08:35:04-05:00"),
        ).rows[0]

        self.assertEqual(CATALYST_SCORE_BLOCKED, row.catalyst_attribution.score_authority)
        self.assertIn("AI", row.catalyst_cluster)
        self.assertEqual(row.composite_score + 8, risk_on_score(row))
        self.assertFalse(row.likely_outperform_smh)
        self.assertIn("research-only", row.opportunity_notes[0])

    def test_export_uses_unambiguous_research_only_labels(self) -> None:
        capture = self.write_capture(
            "GOOGL",
            "Alphabet Inc",
            "Baker Hughes discusses geothermal investment",
        )
        report = build_trade_planning_report(
            capture,
            as_of=datetime.fromisoformat("2026-08-03T08:35:04-05:00"),
        )

        paths = export_trade_planning_report(report, self.root / "reports")
        markdown = paths["report"].read_text(encoding="utf-8")
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        candidate = payload["candidates"][0]

        self.assertIn("CAPTURED PRICE", markdown)
        self.assertIn("HYPOTHETICAL PLAN | EXECUTION-INELIGIBLE", markdown)
        self.assertIn("Catalyst Attribution: UNRESOLVED", markdown)
        self.assertIn("Catalyst Score Authority: BLOCKED", markdown)
        self.assertIn("Authorized Catalyst Confidence: 0", markdown)
        self.assertEqual(COMPOSITE_PROFILE, payload["metadata"]["composite_profile"])
        self.assertEqual(
            COMPOSITE_CONFIGURATION_FINGERPRINT,
            payload["metadata"]["composite_configuration_fingerprint"],
        )
        self.assertEqual(
            EVIDENCE_INTEGRITY_SCHEMA_VERSION,
            payload["metadata"]["evidence_integrity_schema_version"],
        )
        self.assertEqual(0, candidate["scoring"]["authoritative_catalyst_confidence"])
        self.assertEqual(0.0, candidate["scoring"]["catalyst_score_contribution"])
        self.assertEqual(
            EXECUTION_INELIGIBLE,
            candidate["evidence_integrity"]["price_evidence_status"],
        )
        self.assertEqual(
            "CAPTURED PRICE",
            candidate["evidence_integrity"]["price_fields"]["last_price"]["label"],
        )
        self.assertEqual(
            "HYPOTHETICAL PLAN",
            candidate["evidence_integrity"]["plan_label"],
        )

    def write_capture(self, ticker: str, company: str, headline: str) -> Path:
        path = self.root / "opening.json"
        candidate = candidate_for(ticker, company, headline)
        path.write_text(
            json.dumps(
                {
                    "capture_time": "2026-08-03T08:35:02-05:00",
                    "session": "opening",
                    "provider": "finviz",
                    "scanner": {"name": "Institutional Momentum"},
                    "candidates": [
                        {
                            "ticker": candidate.ticker,
                            "company": candidate.company,
                            "price": candidate.price,
                            "percent_change": candidate.percent_change,
                            "volume": candidate.volume,
                            "relative_volume": candidate.relative_volume,
                            "market_cap": candidate.market_cap,
                            "sector": candidate.sector,
                            "industry": candidate.industry,
                            "score": candidate.score,
                            "freshness_score": candidate.freshness_score,
                            "news_stack": {
                                "article_count": 1,
                                "freshest_headline": headline,
                                "freshness_score": candidate.freshness_score,
                            },
                            "news": [
                                {
                                    "headline": headline,
                                    "source": "Finviz",
                                    "published_at": "2026-08-03T08:00:00-05:00",
                                    "url": "https://example.test/story",
                                    "summary": "",
                                }
                            ],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path


def candidate_for(ticker: str, company: str, headline: str) -> Candidate:
    published = datetime.fromisoformat("2026-08-03T08:00:00-05:00")
    return Candidate(
        ticker=ticker,
        company=company,
        price=368.63,
        percent_change=2.0,
        volume=2_000_000,
        relative_volume=1.5,
        market_cap=100_000_000_000,
        sector="Technology",
        industry="Internet Content & Information",
        score=89,
        freshness_score=80,
        news=[
            NewsItem(
                headline=headline,
                source="Finviz",
                published_at=published,
                url="https://example.test/story",
            )
        ],
        news_stack=NewsStack(
            article_count=1,
            freshest_headline=headline,
            latest_article_published_at=published,
            freshness_score=80,
        ),
    )


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


class CombinedProviderSession:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def get(
        self,
        url: str,
        headers: dict | None = None,
        timeout: float = 20.0,
    ) -> FakeResponse:
        self.urls.append(url)
        if "api.nasdaq.com" in url and "/info" in url:
            return FakeResponse(
                {
                    "data": {
                        "marketStatus": "Open",
                        "primaryData": {
                            "lastSalePrice": "$368.24",
                            "bidPrice": "$368.12",
                            "askPrice": "$368.26",
                            "volume": "2,000,000",
                            "lastTradeTimestamp": "2026-08-03T08:35:01-05:00",
                        },
                    }
                }
            )
        if "api.nasdaq.com" in url and "/summary" in url:
            return FakeResponse(
                {
                    "data": {
                        "summaryData": {
                            "ShareVolume": {"value": "2,000,000"},
                            "AverageVolume": {"value": "10,000,000"},
                        }
                    }
                }
            )
        if "api.nasdaq.com" in url and "/extended-trading" in url:
            return FakeResponse({"data": {"infoTable": {"rows": []}}})
        if "/v7/finance/quote" in url:
            return FakeResponse({}, status_code=401)
        if "/v8/finance/chart" in url:
            return FakeResponse({"chart": {"result": []}})
        raise AssertionError(f"Unexpected URL: {url}")


if __name__ == "__main__":
    unittest.main()
