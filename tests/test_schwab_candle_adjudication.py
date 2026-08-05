from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.schwab_candle_adjudication import (
    ALLOWED_RECOMMENDATIONS,
    ALLOWED_STATUSES,
    SchwabCandleAdjudicationError,
    _fingerprint,
    build_adjudication,
    load_observation_proof,
    render_markdown,
    write_adjudication_bundle,
)
from momentum_hunter.schwab_candle_observer import (
    CandleObservationOptions,
    CandidateSourceEvidence,
    SchwabCandleObserverError,
    SchwabCandleMarketHoursObserver,
    build_observation_plan,
    load_candidate_source,
)


def candidate_report() -> dict[str, object]:
    return {
        "schema_version": 2,
        "metadata": {
            "generated_at": "2026-08-05T08:35:06-05:00",
            "source_session": "opening",
        },
        "candidates": [
            {"rank": 2, "symbol": "MRVL"},
            {"rank": 1, "symbol": "NOK"},
        ],
    }


def complete_proof() -> dict[str, object]:
    symbols = ["SPY", "IWM", "NOK"]
    candidate = CandidateSourceEvidence(
        report_name="trade-plan-briefing-2026-08-05-opening.json",
        report_sha256="A" * 64,
        schema_version=2,
        generated_at=datetime(2026, 8, 5, 8, 35, 6, tzinfo=timezone.utc),
        source_session="opening",
        candidate_symbol="NOK",
        candidate_rank=1,
    ).evidence()
    candles = []
    summaries = []
    updates = []
    rows = []
    for symbol_index, symbol in enumerate(symbols):
        for minute_index in range(2):
            timestamp = f"2026-08-05T14:3{5 + minute_index}:00+00:00"
            identity = f"schwab|{symbol}|{timestamp}"
            volume = 1000 + symbol_index * 100 + minute_index * 50
            for update_index in range(2):
                candle = {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "sessionDate": "2026-08-05",
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.5,
                    "close": 100.5 + update_index * 0.1,
                    "volume": volume + update_index * 10,
                    "sequence": update_index + 1,
                    "source": "schwab_streamer_chart_equity:v1",
                    "ohlcvComplete": True,
                }
                updates.append(
                    {
                        "arrivalIndex": len(updates),
                        "payloadIndex": len(updates),
                        "receivedAt": f"2026-08-05T14:3{5 + minute_index}:0{2 + update_index}+00:00",
                        "minuteIdentity": identity,
                        "updateKind": "FIRST_SEEN" if update_index == 0 else "REVISION",
                        "changedFields": [] if update_index == 0 else ["close", "volume"],
                        "outOfOrder": False,
                        "sequenceDeltaFromPreviousArrival": 1,
                        "candle": candle,
                    }
                )
            summaries.append(
                {
                    "minuteIdentity": identity,
                    "symbol": symbol,
                    "candleTimestamp": timestamp,
                    "firstObservedAt": f"2026-08-05T14:3{5 + minute_index}:02+00:00",
                    "lastObservedAt": f"2026-08-05T14:3{5 + minute_index}:03+00:00",
                    "lastChangedAt": f"2026-08-05T14:3{5 + minute_index}:03+00:00",
                    "observedStableForSeconds": 60.0,
                    "updateCount": 2,
                    "revisionCount": 1,
                    "identicalReplayCount": 0,
                    "outOfOrderArrivalCount": 0,
                    "latestObservedCandle": updates[-1]["candle"],
                    "completionState": "UNVERIFIED",
                }
            )
            rows.append(
                {
                    "minuteIdentity": identity,
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "status": "MATCH",
                    "changedFields": [],
                    "stream": updates[-1]["candle"],
                    "priceHistory": updates[-1]["candle"],
                }
            )
        candles.append({**updates[-1]["candle"], "status": "PASS"})
    proof: dict[str, object] = {
        "schemaVersion": 1,
        "proofType": "SCHWAB_CHART_EQUITY_NONPERSISTING_SHAPE_LATENCY",
        "proofStatus": "PARTIAL",
        "shapeStatus": "PASS",
        "requestStartedAt": "2026-08-05T14:35:00+00:00",
        "responseReceivedAt": "2026-08-05T14:35:02+00:00",
        "evaluatedAt": "2026-08-05T14:37:04+00:00",
        "sourceIdentity": "schwab_streamer_chart_equity:v1",
        "requestedSymbols": symbols,
        "missingSymbols": [],
        "candles": candles,
        "transportEvents": [],
        "updateObservations": updates,
        "minuteSummaries": summaries,
        "observedTimestampGaps": [],
        "streamHistoryReconciliation": {
            "comparableMinuteCount": 6,
            "matchingMinuteCount": 6,
            "differentMinuteCount": 0,
            "streamOnlyMinuteCount": 0,
            "historyOnlyMinuteCount": 0,
            "allComparableMinutesMatch": True,
            "rows": rows,
        },
        "findings": [],
        "nonPersisting": True,
        "observerSchemaVersion": 1,
        "observerMode": "SCHWAB_CHART_EQUITY_MARKET_HOURS_OBSERVER",
        "liveNetworkCalled": True,
        "observationOptions": {
            "symbols": symbols,
            "expectedAccountEnding": "2573",
            "durationSeconds": 300,
            "extendedHoursAllowed": False,
            "candidateSource": candidate,
        },
        "accountInvariant": {"authorizedAccountCount": 1, "accountEnding": "2573"},
        "subscription": {
            "service": "CHART_EQUITY",
            "command": "SUBS",
            "requestId": "1",
            "symbols": symbols,
            "requestFingerprint": "B" * 64,
            "acknowledged": True,
        },
        "streamStatus": "PASS",
        "priceHistoryStatus": "PASS",
        "credentialMaterialIncluded": False,
        "rawAccountMetadataIncluded": False,
        "productionDataWritten": False,
        "serviceInvoked": False,
        "engineHostInvoked": False,
        "wpfInvoked": False,
        "orderTransmission": "UNAVAILABLE",
    }
    proof["proofFingerprint"] = _fingerprint(proof)
    return proof


class SchwabCandleAdjudicationTests(unittest.TestCase):
    def test_candidate_source_selects_unique_lowest_rank_and_hashes_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "opening.json"
            raw = (json.dumps(candidate_report(), indent=2) + "\n").encode("utf-8")
            path.write_bytes(raw)
            before = path.read_bytes()
            evidence = load_candidate_source(path)
            self.assertEqual("NOK", evidence.candidate_symbol)
            self.assertEqual(1, evidence.candidate_rank)
            self.assertEqual(hashlib.sha256(raw).hexdigest().upper(), evidence.report_sha256)
            self.assertEqual(before, path.read_bytes())
            plan = build_observation_plan(
                CandleObservationOptions.create(
                    ["SPY", "IWM", "NOK"],
                    expected_account_ending="2573",
                    candidate_source=evidence,
                )
            )
            self.assertEqual("NOK", plan["candidateSource"]["candidateSymbol"])
            self.assertEqual(evidence.report_sha256, plan["candidateSource"]["reportSha256"])

    def test_candidate_source_rejects_wrong_session_duplicate_rank_and_benchmark(self) -> None:
        variants = []
        wrong_session = candidate_report()
        wrong_session["metadata"]["source_session"] = "live"
        variants.append(wrong_session)
        duplicate = candidate_report()
        duplicate["candidates"][0]["rank"] = 1
        variants.append(duplicate)
        benchmark = candidate_report()
        benchmark["candidates"] = [{"rank": 1, "symbol": "SPY"}]
        variants.append(benchmark)
        with tempfile.TemporaryDirectory() as temporary:
            for index, payload in enumerate(variants):
                path = Path(temporary) / f"bad-{index}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(SchwabCandleObserverError):
                    load_candidate_source(path)

    def test_live_observer_rejects_stale_candidate_source_before_account_access(self) -> None:
        class ForbiddenAccess:
            def authorize(self, expected_account_ending: str) -> object:
                raise AssertionError("account access must not occur")

        source = CandidateSourceEvidence(
            report_name="opening.json",
            report_sha256="A" * 64,
            schema_version=1,
            generated_at=datetime(2026, 8, 4, 13, 35, tzinfo=timezone.utc),
            source_session="opening",
            candidate_symbol="NOK",
            candidate_rank=1,
        )
        options = CandleObservationOptions.create(
            ["SPY", "IWM", "NOK"],
            expected_account_ending="2573",
            duration_seconds=180,
            candidate_source=source,
        )
        observer = SchwabCandleMarketHoursObserver(
            access_guard=ForbiddenAccess(),
            utc_clock=lambda: datetime(2026, 8, 5, 14, 35, tzinfo=timezone.utc),
        )
        with self.assertRaisesRegex(SchwabCandleObserverError, "market date"):
            observer.observe(options)

    def test_adjudication_covers_all_questions_and_accepts_with_limits(self) -> None:
        adjudication = build_adjudication(complete_proof())
        self.assertEqual(12, len(adjudication["questions"]))
        self.assertTrue(
            all(row["status"] in ALLOWED_STATUSES for row in adjudication["questions"])
        )
        self.assertIn(adjudication["recommendation"], ALLOWED_RECOMMENDATIONS)
        self.assertEqual("ACCEPTED_WITH_LIMITATIONS", adjudication["recommendation"])
        self.assertEqual("VERIFIED", adjudication["questions"][0]["status"])
        self.assertEqual("VERIFIED", adjudication["questions"][1]["status"])
        self.assertEqual("VERIFIED", adjudication["questions"][6]["status"])
        self.assertEqual("UNVERIFIED", adjudication["questions"][8]["status"])
        self.assertEqual("UNAVAILABLE", adjudication["orderTransmission"])
        markdown = render_markdown(adjudication)
        self.assertIn("ACCEPTED_WITH_LIMITATIONS", markdown)
        self.assertIn("No production candle persistence", markdown)

    def test_reconciliation_difference_is_disproven_but_keeps_design_limited(self) -> None:
        proof = complete_proof()
        reconciliation = proof["streamHistoryReconciliation"]
        reconciliation["differentMinuteCount"] = 1
        reconciliation["matchingMinuteCount"] = 5
        reconciliation["allComparableMinutesMatch"] = False
        reconciliation["rows"][0]["status"] = "CORRECTED_OR_DIFFERENT"
        proof["proofFingerprint"] = _fingerprint(
            {key: value for key, value in proof.items() if key != "proofFingerprint"}
        )
        adjudication = build_adjudication(proof)
        self.assertEqual("DISPROVEN", adjudication["questions"][6]["status"])
        self.assertEqual("ACCEPTED_WITH_LIMITATIONS", adjudication["recommendation"])

    def test_tampered_proof_fails_closed(self) -> None:
        proof = complete_proof()
        proof["requestedSymbols"][-1] = "MRVL"
        with self.assertRaisesRegex(SchwabCandleAdjudicationError, "bind"):
            build_adjudication(proof)

    def test_bundle_is_write_once_hashed_sanitized_and_outside_repo(self) -> None:
        proof = complete_proof()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            proof_path = root / "proof.json"
            proof_path.write_text(
                json.dumps(proof, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            loaded, before = load_observation_proof(proof_path)
            self.assertEqual(proof, loaded)
            result = write_adjudication_bundle(proof_path, root)
            self.assertEqual("PASS", result["status"])
            self.assertEqual(before, proof_path.read_bytes())
            for key in ("adjudicationPath", "markdownPath", "manifestPath"):
                self.assertTrue(Path(result[key]).is_file())
            manifest = json.loads(Path(result["manifestPath"]).read_text(encoding="utf-8"))
            self.assertEqual(2, len(manifest["inputs"]))
            self.assertEqual(2, len(manifest["outputs"]))
            serialized = json.dumps(manifest).lower()
            self.assertNotIn("access_token", serialized)
            self.assertNotIn("account_hash", serialized)
            with self.assertRaisesRegex(SchwabCandleAdjudicationError, "already exists"):
                write_adjudication_bundle(proof_path, root)

    def test_live_cli_requires_candidate_source_before_observer_construction(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch

        from momentum_hunter.schwab_candle_observer import main

        output = StringIO()
        with (
            patch(
                "momentum_hunter.schwab_candle_observer.SchwabCandleMarketHoursObserver",
                side_effect=AssertionError("observer must not be constructed"),
            ),
            redirect_stdout(output),
        ):
            result = main(
                [
                    "--symbols",
                    "SPY",
                    "IWM",
                    "NOK",
                    "--expected-account-ending",
                    "2573",
                    "--execute",
                    "--output",
                    str(Path(tempfile.gettempdir()) / "unused-r031b-proof.json"),
                ]
            )
        self.assertEqual(2, result)
        self.assertIn("requires a frozen Hunter candidate report", output.getvalue())

    def test_powershell_live_launch_requires_candidate_report_before_python(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "tools" / "run_schwab_candle_observer.ps1"),
                "-CandidateSymbol",
                "NOK",
                "-ProjectRoot",
                str(root),
                "-Execute",
            ],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("requires CandidateReportPath", result.stdout + result.stderr)

    def test_source_module_has_no_network_or_broker_capability(self) -> None:
        import inspect
        import momentum_hunter.schwab_candle_adjudication as module

        source = inspect.getsource(module)
        self.assertNotIn("requests", source)
        self.assertNotIn("websocket", source)
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)
        self.assertNotIn("replace_order", source)
        self.assertNotIn("MomentumHunterData", source)


if __name__ == "__main__":
    unittest.main()
