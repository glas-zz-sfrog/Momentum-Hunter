from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.run_opening_runtime_d221_review import (
    PreservedFinvizProvider,
    daily_bars_from_store,
    market_regime_from_capture,
    market_tapes_from_report,
    readiness_state_counts,
    secret_scan,
)


class OpeningRuntimeD221ReviewTests(unittest.TestCase):
    def test_preserved_provider_returns_real_candidates_without_news_injection(self) -> None:
        provider = PreservedFinvizProvider(
            {
                "candidates": [
                    {
                        "ticker": "AAA",
                        "company": "Alpha",
                        "price": 12.5,
                        "percent_change": 4.0,
                        "volume": 4_000_000,
                        "relative_volume": 2.0,
                        "market_cap": 6_000_000_000,
                        "news": [],
                    }
                ]
            }
        )
        rows = provider.scan(object())
        self.assertEqual("AAA", rows[0].ticker)
        self.assertEqual(1, provider.scan_calls)
        self.assertEqual([], provider.fetch_news("AAA", as_of=__import__("datetime").datetime.now().astimezone()))

    def test_market_regime_is_reconstructed_from_preserved_capture(self) -> None:
        result = market_regime_from_capture(
            {
                "market": {
                    "regime": "bull",
                    "symbol": "SPY",
                    "close": 10,
                    "sma_50": 9,
                    "sma_200": 8,
                    "reason": "preserved",
                }
            }
        )
        self.assertEqual("bull", result.regime.value)
        self.assertEqual("preserved", result.reason)

    def test_market_tape_round_trip_preserves_authority_objects(self) -> None:
        payload = {
            "candidates": [
                {
                    "symbol": "AAA",
                    "market_tape": {
                        "last_price": 10.0,
                        "rvol_evidence": {
                            "status": "EXECUTION_ELIGIBLE",
                            "symbol": "AAA",
                            "baseline_session_dates": ["2026-08-01"],
                            "findings": ["AVAILABLE"],
                        },
                        "field_provenance": {
                            "last_price": {
                                "label": "FRESH PROVIDER QUOTE",
                                "source": "preserved",
                                "provider_timestamp": "2026-08-14T08:35:00-05:00",
                                "local_receipt_timestamp": "2026-08-14T08:35:01-05:00",
                                "age_seconds": 1.0,
                                "authentication_status": "OAUTH_AUTHENTICATED",
                                "result_status": "SUCCESS",
                                "authority": "EXECUTION_ELIGIBLE",
                            }
                        },
                    },
                }
            ]
        }
        tape = market_tapes_from_report(payload)["AAA"]
        self.assertEqual(10.0, tape.last_price)
        self.assertTrue(tape.rvol_evidence.execution_eligible)
        self.assertEqual("EXECUTION_ELIGIBLE", tape.field_provenance["last_price"].authority)

    def test_daily_store_excludes_same_day_and_future_bars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "AAA.json"
            path.write_text(
                json.dumps(
                    {
                        "bars": [
                            {"canonicalCandle": {"sessionDate": "2026-08-13", "high": 12, "low": 9, "close": 11, "volume": 100}},
                            {"canonicalCandle": {"sessionDate": "2026-08-14", "high": 13, "low": 10, "close": 12, "volume": 200}},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            rows = daily_bars_from_store(path, before_date="2026-08-14")
        self.assertEqual(["2026-08-13"], [row.day for row in rows])

    def test_readiness_counts_preserve_specific_do_not_trade_states(self) -> None:
        result = readiness_state_counts(
            ("EXECUTION_READY_TRADE", "DO_NOT_TRADE_MISSED_ENTRY")
        )
        self.assertEqual(1, result["executionReadyTradeCount"])
        self.assertEqual(1, result["doNotTradeCount"])

    def test_secret_scan_blocks_credential_shaped_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "clean.json").write_text('{"orderTransmission":"UNAVAILABLE"}', encoding="utf-8")
            self.assertEqual("PASS", secret_scan(root)["status"])
            (root / "bad.txt").write_text("sk-" + "x" * 30, encoding="utf-8")
            self.assertEqual("FAIL", secret_scan(root)["status"])

    def test_candidate_builder_seeds_disposable_store_from_predecessor(self) -> None:
        from tools import run_opening_runtime_d221_review as review

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            production = root / "production"
            (production / "channels").mkdir(parents=True)
            (production / "channels" / "opening-capture.json").write_text("{}", encoding="utf-8")
            evidence = root / "evidence"
            context = object()
            fake_release = {
                "releaseId": "OPENING-RUNTIME-NEW",
                "releaseFingerprint": "f",
                "approvedRuntimeFingerprint": "a",
                "runtimeSurfaceFingerprint": "s",
                "configurationFingerprint": "c",
                "environmentFingerprint": "e",
                "dependencyClosureEvidence": {
                    "dependencyClosureFingerprint": "d",
                    "reachablePackageCount": 1,
                    "excludedPackageCount": 0,
                    "explicitRuntimeFiles": [],
                },
                "environmentIdentity": {
                    "serviceHost": {"sha256": "h"},
                    "relevantDistributions": [],
                },
            }
            fake_store = unittest.mock.Mock()
            fake_store.promote.return_value = (
                fake_release,
                {"pointerFingerprint": "p"},
                True,
            )
            with (
                patch.object(review, "parse_manifest", return_value=object()),
                patch.object(review, "_context", return_value=context),
                patch.object(review, "replace", return_value=context),
                patch.object(review, "build_release_record_v2", return_value=fake_release),
                patch.object(review, "OpeningRuntimeReleaseStore", return_value=fake_store),
                patch.object(review, "verify_execution_gate", return_value=unittest.mock.Mock(runtime_match=True)),
            ):
                review.build_d221_candidate(
                    root,
                    root / "manifest.json",
                    production,
                    evidence,
                    {"releaseId": "OPENING-RUNTIME-D220"},
                )
            self.assertTrue(
                (evidence / "isolated-opening-runtime" / "channels" / "opening-capture.json").is_file()
            )


if __name__ == "__main__":
    unittest.main()
