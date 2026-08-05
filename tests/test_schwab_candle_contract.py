from __future__ import annotations

import inspect
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.schwab_candle_contract import (
    SCHWAB_CANDLE_CONTRACT_SCHEMA_VERSION,
    SCHWAB_CHART_EQUITY_FIELDS,
    SCHWAB_CHART_EQUITY_SERVICE,
    SCHWAB_CHART_EQUITY_SOURCE,
    SCHWAB_PRICE_HISTORY_SOURCE,
    SCHWAB_PRICE_HISTORY_URL,
    SCHWAB_USER_PREFERENCE_URL,
    SchwabCandleContractError,
    build_chart_equity_subscription,
    build_nonpersisting_stream_proof,
    build_price_history_parameters,
    compare_stream_observations_to_price_history,
    inspect_chart_equity_observations,
    main,
    official_candle_contract,
    parse_chart_equity_messages,
    parse_price_history_response,
    session_for_timestamp,
)


class SchwabCandleContractTests(unittest.TestCase):
    def test_official_contract_separates_stream_from_history(self) -> None:
        contract = official_candle_contract()

        self.assertEqual(
            SCHWAB_CANDLE_CONTRACT_SCHEMA_VERSION,
            contract["schemaVersion"],
        )
        self.assertEqual(
            SCHWAB_CHART_EQUITY_SERVICE,
            contract["stream"]["service"],
        )
        self.assertEqual("All Sequence", contract["stream"]["deliveryType"])
        self.assertTrue(contract["stream"]["regularHoursUpdates"])
        self.assertTrue(contract["stream"]["extendedHoursUpdates"])
        self.assertEqual(1, contract["stream"]["maximumConnectionsPerUser"])
        self.assertIsNone(contract["stream"]["numericSymbolLimit"])
        self.assertIsNone(
            contract["stream"]["authoritativeConsolidatedVolume"]
        )
        self.assertFalse(contract["stream"]["haltStatusIncludedInCandle"])
        self.assertEqual(
            SCHWAB_USER_PREFERENCE_URL,
            contract["stream"]["bootstrap"]["endpoint"],
        )
        self.assertTrue(
            contract["stream"]["bootstrap"][
                "responseAlsoContainsAccountMetadata"
            ]
        )
        self.assertTrue(
            contract["stream"]["bootstrap"][
                "requiresSingleAccountInvariantValidation"
            ]
        )
        self.assertEqual(
            SCHWAB_PRICE_HISTORY_URL,
            contract["history"]["endpoint"],
        )
        self.assertEqual(1, contract["history"]["symbolsPerRequest"])
        self.assertEqual(
            10,
            contract["history"]["maximumDocumentedMinutePeriodDays"],
        )
        self.assertEqual(
            [1, 5, 10, 15, 30],
            contract["history"]["minuteFrequencies"],
        )
        self.assertIn(
            "stream candle completion/finality semantics",
            contract["notDocumented"],
        )
        self.assertEqual(
            "UNAVAILABLE",
            contract["runtimeBoundary"]["orderTransmission"],
        )

    def test_subscription_uses_exact_chart_contract(self) -> None:
        request = build_chart_equity_subscription(
            ["aapl", "SPY", "aapl"],
            customer_id="SYNTHETIC-CUSTOMER",
            correlation_id="SYNTHETIC-CORRELATION",
            request_id="7",
        )

        row = request["requests"][0]
        self.assertEqual(SCHWAB_CHART_EQUITY_SERVICE, row["service"])
        self.assertEqual("SUBS", row["command"])
        self.assertEqual("7", row["requestid"])
        self.assertEqual("AAPL,SPY", row["parameters"]["keys"])
        self.assertEqual(
            SCHWAB_CHART_EQUITY_FIELDS,
            row["parameters"]["fields"],
        )
        serialized = json.dumps(request).lower()
        self.assertNotIn("access_token", serialized)
        self.assertNotIn("account", serialized)
        self.assertNotIn("order", serialized)

    def test_subscription_rejects_missing_streamer_identity(self) -> None:
        with self.assertRaises(SchwabCandleContractError):
            build_chart_equity_subscription(
                ["AAPL"],
                customer_id="",
                correlation_id="SYNTHETIC",
            )

    def test_price_history_parameters_force_explicit_minute_window(self) -> None:
        start = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
        end = start + timedelta(hours=4)

        params = build_price_history_parameters(
            "aapl",
            start_at=start,
            end_at=end,
            extended_hours=True,
        )

        self.assertEqual("AAPL", params["symbol"])
        self.assertEqual("day", params["periodType"])
        self.assertEqual("minute", params["frequencyType"])
        self.assertEqual(1, params["frequency"])
        self.assertEqual(int(start.timestamp() * 1000), params["startDate"])
        self.assertEqual(int(end.timestamp() * 1000), params["endDate"])
        self.assertTrue(params["needExtendedHoursData"])
        self.assertTrue(params["needPreviousClose"])

        with self.assertRaisesRegex(SchwabCandleContractError, "must be after"):
            build_price_history_parameters(
                "AAPL",
                start_at=start,
                end_at=start,
                extended_hours=False,
            )

    def test_stream_parser_reads_minute_ohlcv_and_sequence(self) -> None:
        candles = parse_chart_equity_messages(
            [stream_payload()],
            expected_symbols=["AAPL"],
        )

        self.assertEqual(1, len(candles))
        candle = candles[0]
        self.assertEqual("AAPL", candle.symbol)
        self.assertEqual(100.0, candle.open)
        self.assertEqual(101.0, candle.high)
        self.assertEqual(99.5, candle.low)
        self.assertEqual(100.75, candle.close)
        self.assertEqual(12_345.0, candle.volume)
        self.assertEqual(7, candle.sequence)
        self.assertEqual(
            datetime(2026, 7, 31, 14, 31, tzinfo=timezone.utc),
            candle.timestamp,
        )
        self.assertEqual(SCHWAB_CHART_EQUITY_SOURCE, candle.source)

    def test_stream_parser_accepts_keyed_symbol_and_rejects_conflict(self) -> None:
        keyed = stream_payload()
        row = keyed["data"][0]["content"][0]
        row["1"] = 0

        candles = parse_chart_equity_messages(
            [keyed],
            expected_symbols=["AAPL"],
        )

        self.assertEqual("AAPL", candles[0].symbol)
        self.assertEqual(0, candles[0].sequence)

        conflicting = stream_payload()
        conflicting["data"][0]["content"][0]["0"] = "AAPL"
        conflicting["data"][0]["content"][0]["key"] = "MSFT"
        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "conflicting symbol identities",
        ):
            parse_chart_equity_messages(
                [conflicting],
                expected_symbols=["AAPL"],
            )

        invalid_sequence = stream_payload(sequence=-1)
        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "nonnegative integer",
        ):
            parse_chart_equity_messages(
                [invalid_sequence],
                expected_symbols=["AAPL"],
            )

    def test_stream_parser_ignores_heartbeat_and_other_services(self) -> None:
        payload = {
            "notify": [{"heartbeat": "1785508260000"}],
            "data": [
                {
                    "service": "LEVELONE_EQUITIES",
                    "content": [{"key": "AAPL"}],
                },
                stream_payload()["data"][0],
            ],
        }

        candles = parse_chart_equity_messages(
            [payload],
            expected_symbols=["AAPL"],
        )

        self.assertEqual(1, len(candles))

    def test_stream_parser_rejects_unexpected_symbol(self) -> None:
        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "unexpected symbol",
        ):
            parse_chart_equity_messages(
                [stream_payload(symbol="MSFT")],
                expected_symbols=["AAPL"],
            )

    def test_stream_parser_rejects_missing_and_nonfinite_fields(self) -> None:
        missing = stream_payload()
        del missing["data"][0]["content"][0]["6"]
        with self.assertRaisesRegex(SchwabCandleContractError, "field 6"):
            parse_chart_equity_messages(
                [missing],
                expected_symbols=["AAPL"],
            )

        nonfinite = stream_payload()
        nonfinite["data"][0]["content"][0]["2"] = float("nan")
        with self.assertRaisesRegex(SchwabCandleContractError, "finite"):
            parse_chart_equity_messages(
                [nonfinite],
                expected_symbols=["AAPL"],
            )

    def test_stream_parser_rejects_invalid_ohlc(self) -> None:
        invalid = stream_payload()
        invalid["data"][0]["content"][0]["3"] = 99.0

        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "high was below",
        ):
            parse_chart_equity_messages(
                [invalid],
                expected_symbols=["AAPL"],
            )

    def test_stream_observations_preserve_replay_revision_and_late_arrival(
        self,
    ) -> None:
        minute = datetime(2026, 7, 31, 14, 31, tzinfo=timezone.utc)
        later_minute = minute + timedelta(minutes=1)
        receipts = [
            minute + timedelta(seconds=1),
            minute + timedelta(seconds=2),
            minute + timedelta(seconds=3),
            later_minute + timedelta(seconds=1),
            later_minute + timedelta(seconds=2),
        ]
        observations = inspect_chart_equity_observations(
            [
                stream_payload(timestamp=minute),
                stream_payload(timestamp=minute),
                stream_payload(timestamp=minute, close=100.9, volume=13_000),
                stream_payload(timestamp=later_minute, sequence=8),
                stream_payload(timestamp=minute, close=101.0, volume=13_500),
            ],
            expected_symbols=["AAPL"],
            received_at_by_payload=receipts,
        )

        self.assertEqual(5, len(observations))
        self.assertEqual("FIRST_OBSERVATION", observations[0].update_kind)
        self.assertEqual("IDENTICAL_REPLAY", observations[1].update_kind)
        self.assertEqual("REVISION", observations[2].update_kind)
        self.assertEqual(
            ("close", "volume"),
            observations[2].changed_fields,
        )
        self.assertEqual("FIRST_OBSERVATION", observations[3].update_kind)
        self.assertEqual("REVISION", observations[4].update_kind)
        self.assertTrue(observations[4].out_of_order)
        self.assertEqual(-1, observations[4].sequence_delta_from_previous_arrival)
        self.assertIn(
            "schwab_streamer_chart_equity:v1|AAPL|2026-07-31|",
            observations[0].minute_identity,
        )
        self.assertEqual(
            "2026-07-31",
            observations[0].to_evidence()["candle"]["sessionDate"],
        )

        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "receipt timestamps",
        ):
            inspect_chart_equity_observations(
                [stream_payload(), stream_payload()],
                expected_symbols=["AAPL"],
                received_at_by_payload=list(reversed(receipts[:2])),
            )

    def test_price_history_parser_reads_strict_ordered_candles(self) -> None:
        payload = price_history_payload()
        payload["candles"].append(
            history_row(
                datetime(2026, 7, 31, 14, 32, tzinfo=timezone.utc),
                close=101.0,
            )
        )

        candles = parse_price_history_response(
            payload,
            expected_symbol="aapl",
        )

        self.assertEqual(2, len(candles))
        self.assertEqual(SCHWAB_PRICE_HISTORY_SOURCE, candles[0].source)
        self.assertIsNone(candles[0].sequence)

    def test_price_history_empty_state_is_honest(self) -> None:
        self.assertEqual(
            (),
            parse_price_history_response(
                {"symbol": "AAPL", "empty": True, "candles": []},
                expected_symbol="AAPL",
            ),
        )
        with self.assertRaisesRegex(SchwabCandleContractError, "contradicted"):
            parse_price_history_response(
                {
                    "symbol": "AAPL",
                    "empty": True,
                    "candles": [history_row()],
                },
                expected_symbol="AAPL",
            )

    def test_price_history_rejects_symbol_mismatch_and_false_nonempty(self) -> None:
        with self.assertRaisesRegex(SchwabCandleContractError, "identity"):
            parse_price_history_response(
                price_history_payload(symbol="MSFT"),
                expected_symbol="AAPL",
            )
        with self.assertRaisesRegex(SchwabCandleContractError, "no candles"):
            parse_price_history_response(
                {"symbol": "AAPL", "empty": False, "candles": []},
                expected_symbol="AAPL",
            )

    def test_price_history_rejects_duplicate_and_out_of_order_minutes(self) -> None:
        first = datetime(2026, 7, 31, 14, 31, tzinfo=timezone.utc)
        duplicate = price_history_payload()
        duplicate["candles"] = [history_row(first), history_row(first)]
        with self.assertRaisesRegex(SchwabCandleContractError, "duplicate"):
            parse_price_history_response(
                duplicate,
                expected_symbol="AAPL",
            )

        out_of_order = price_history_payload()
        out_of_order["candles"] = [
            history_row(first + timedelta(minutes=1)),
            history_row(first),
        ]
        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "chronological",
        ):
            parse_price_history_response(
                out_of_order,
                expected_symbol="AAPL",
            )

    def test_nonpersisting_proof_reports_observed_facts_and_unknown_finality(
        self,
    ) -> None:
        requested = datetime(2026, 7, 31, 14, 31, 1, tzinfo=timezone.utc)
        received = requested + timedelta(milliseconds=240)
        evaluated = requested + timedelta(seconds=5)

        proof = build_nonpersisting_stream_proof(
            [stream_payload()],
            expected_symbols=["AAPL"],
            request_started_at=requested,
            response_received_at=received,
            evaluated_at=evaluated,
        )

        self.assertEqual("PARTIAL", proof["proofStatus"])
        self.assertEqual("PASS", proof["shapeStatus"])
        self.assertEqual("UNVERIFIED", proof["completionStatus"])
        self.assertEqual(0.24, proof["providerResponseSeconds"])
        self.assertEqual(
            "2026-07-31T10:31:00-04:00",
            proof["currentMarketMinute"],
        )
        self.assertEqual(
            "2026-07-31T14:31:00+00:00",
            proof["newestCandleTimestamp"],
        )
        self.assertEqual(6.0, proof["newestObservedCandleAgeSeconds"])
        self.assertIsNone(proof["newestCompletedBarTimestamp"])
        self.assertIsNone(proof["newestCompletedBarAgeSeconds"])
        self.assertFalse(proof["extendedHoursObserved"])
        self.assertTrue(proof["candles"][0]["ohlcvComplete"])
        self.assertEqual(SCHWAB_CHART_EQUITY_SOURCE, proof["sourceIdentity"])
        self.assertTrue(proof["nonPersisting"])
        self.assertFalse(proof["networkCalledByProofBuilder"])
        self.assertFalse(proof["accountDataIncluded"])
        self.assertEqual("UNAVAILABLE", proof["orderTransmission"])

    def test_nonpersisting_proof_reports_missing_symbol(self) -> None:
        observed = datetime(2026, 7, 31, 14, 31, tzinfo=timezone.utc)
        proof = build_nonpersisting_stream_proof(
            [stream_payload()],
            expected_symbols=["AAPL", "SPY"],
            request_started_at=observed,
            response_received_at=observed,
        )

        self.assertEqual("FAIL", proof["proofStatus"])
        self.assertEqual(["SPY"], proof["missingSymbols"])
        self.assertEqual("MISSING", proof["candles"][1]["status"])

    def test_nonpersisting_proof_records_transport_updates_and_gaps(self) -> None:
        first = datetime(2026, 7, 31, 14, 31, tzinfo=timezone.utc)
        third = first + timedelta(minutes=2)
        proof = build_nonpersisting_stream_proof(
            [
                stream_payload(timestamp=first),
                stream_payload(timestamp=first, close=100.9, volume=13_000),
                stream_payload(timestamp=third, sequence=9),
            ],
            expected_symbols=["AAPL"],
            request_started_at=first,
            response_received_at=third + timedelta(seconds=1),
            evaluated_at=third + timedelta(seconds=5),
            received_at_by_payload=[
                first + timedelta(seconds=1),
                first + timedelta(seconds=10),
                third + timedelta(seconds=1),
            ],
            transport_events=[
                {"kind": "CONNECTED", "timestamp": first.isoformat()},
                {
                    "kind": "SUBSCRIPTION_ACKNOWLEDGED",
                    "timestamp": (first + timedelta(milliseconds=100)).isoformat(),
                },
                {
                    "kind": "DISCONNECTED",
                    "timestamp": (third + timedelta(milliseconds=250)).isoformat(),
                },
                {
                    "kind": "RECONNECTED",
                    "timestamp": (third + timedelta(milliseconds=500)).isoformat(),
                },
            ],
        )

        self.assertEqual(3, len(proof["updateObservations"]))
        self.assertEqual("REVISION", proof["updateObservations"][1]["updateKind"])
        self.assertEqual(2, len(proof["minuteSummaries"]))
        first_summary = next(
            row
            for row in proof["minuteSummaries"]
            if row["candleTimestamp"] == first.isoformat()
        )
        self.assertEqual(2, first_summary["updateCount"])
        self.assertEqual(1, first_summary["revisionCount"])
        self.assertEqual(
            (first + timedelta(seconds=10)).isoformat(),
            first_summary["lastChangedAt"],
        )
        self.assertEqual(1, len(proof["observedTimestampGaps"]))
        self.assertEqual(
            1,
            proof["observedTimestampGaps"][0]["observedMissingMinuteCount"],
        )
        self.assertFalse(
            proof["observedTimestampGaps"][0]["dataLossProven"]
        )
        self.assertEqual(4, len(proof["transportEvents"]))
        self.assertIn(
            "INTRA_MINUTE_STREAM_REVISION_OBSERVED",
            proof["findings"],
        )
        self.assertIn(
            "OBSERVED_TIMESTAMP_GAP_REQUIRES_RECONCILIATION",
            proof["findings"],
        )

    def test_stream_history_reconciliation_preserves_both_versions(self) -> None:
        first = datetime(2026, 7, 31, 14, 31, tzinfo=timezone.utc)
        second = first + timedelta(minutes=1)
        observations = inspect_chart_equity_observations(
            [
                stream_payload(timestamp=first),
                stream_payload(timestamp=first, close=100.9, volume=13_000),
                stream_payload(timestamp=second, sequence=8),
            ],
            expected_symbols=["AAPL"],
            received_at_by_payload=[
                first + timedelta(seconds=1),
                first + timedelta(seconds=10),
                second + timedelta(seconds=1),
            ],
        )
        history = price_history_payload()
        history["candles"] = [
            history_row(first, close=101.0, volume=13_500),
            history_row(second),
        ]

        comparison = compare_stream_observations_to_price_history(
            observations,
            price_history_payloads={"AAPL": history},
        )

        self.assertFalse(comparison["allComparableMinutesMatch"])
        self.assertEqual(2, comparison["comparableMinuteCount"])
        self.assertEqual(1, comparison["matchingMinuteCount"])
        self.assertEqual(1, comparison["differentMinuteCount"])
        corrected = next(
            row
            for row in comparison["rows"]
            if row["status"] == "CORRECTED_OR_DIFFERENT"
        )
        self.assertEqual(["close", "volume"], corrected["changedFields"])
        self.assertEqual(100.9, corrected["stream"]["close"])
        self.assertEqual(101.0, corrected["priceHistory"]["close"])
        self.assertFalse(comparison["canonicalityGranted"])

    def test_stream_history_reconciliation_labels_unmatched_minutes(self) -> None:
        first = datetime(2026, 7, 31, 14, 31, tzinfo=timezone.utc)
        second = first + timedelta(minutes=1)
        observations = inspect_chart_equity_observations(
            [stream_payload(timestamp=first)],
            expected_symbols=["AAPL"],
            received_at_by_payload=[first + timedelta(seconds=1)],
        )
        history = price_history_payload()
        history["candles"] = [history_row(second)]

        comparison = compare_stream_observations_to_price_history(
            observations,
            price_history_payloads={"AAPL": history},
        )

        self.assertEqual(0, comparison["comparableMinuteCount"])
        self.assertEqual(1, comparison["streamOnlyMinuteCount"])
        self.assertEqual(1, comparison["historyOnlyMinuteCount"])
        self.assertEqual(
            ["STREAM_ONLY", "HISTORY_ONLY"],
            [row["status"] for row in comparison["rows"]],
        )

    def test_enriched_cli_input_preserves_receipts_and_reconciliation(self) -> None:
        first = datetime(2026, 7, 31, 14, 31, tzinfo=timezone.utc)
        received = first + timedelta(seconds=1)
        enriched = {
            "transportEvents": [
                {"kind": "CONNECTED", "timestamp": first.isoformat()},
                {
                    "kind": "SUBSCRIPTION_ACKNOWLEDGED",
                    "timestamp": (first + timedelta(milliseconds=100)).isoformat(),
                },
            ],
            "messages": [
                {
                    "receivedAt": received.isoformat(),
                    "payload": stream_payload(timestamp=first),
                }
            ],
            "priceHistory": {"AAPL": price_history_payload()},
        }
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "proof.json"
            source.write_text(json.dumps(enriched), encoding="utf-8")
            before = source.read_bytes()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "inspect-stream",
                        "--input",
                        str(source),
                        "--symbols",
                        "AAPL",
                        "--request-started-at",
                        first.isoformat(),
                        "--response-received-at",
                        received.isoformat(),
                        "--evaluated-at",
                        (received + timedelta(seconds=5)).isoformat(),
                    ]
                )

            self.assertEqual(0, result)
            proof = json.loads(stdout.getvalue())
            self.assertEqual(received.isoformat(), proof["updateObservations"][0]["receivedAt"])
            self.assertEqual(
                1,
                proof["streamHistoryReconciliation"]["matchingMinuteCount"],
            )
            self.assertEqual(before, source.read_bytes())

    def test_session_classification_distinguishes_extended_and_closed(self) -> None:
        self.assertEqual(
            "extended",
            session_for_timestamp(
                datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
            ),
        )
        self.assertEqual(
            "regular",
            session_for_timestamp(
                datetime(2026, 7, 31, 15, 0, tzinfo=timezone.utc)
            ),
        )
        self.assertEqual(
            "closed",
            session_for_timestamp(
                datetime(2026, 7, 31, 1, 0, tzinfo=timezone.utc)
            ),
        )
        self.assertEqual(
            "closed",
            session_for_timestamp(
                datetime(2026, 8, 1, 15, 0, tzinfo=timezone.utc)
            ),
        )

    def test_cli_is_read_only_deterministic_and_redacted(self) -> None:
        requested = "2026-07-31T14:31:01+00:00"
        received = "2026-07-31T14:31:01.240000+00:00"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "stream.json"
            source.write_text(
                json.dumps(stream_payload()),
                encoding="utf-8",
            )
            before = source.read_bytes()
            outputs: list[str] = []
            for _ in range(2):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "inspect-stream",
                            "--input",
                            str(source),
                            "--symbols",
                            "AAPL",
                            "--request-started-at",
                            requested,
                            "--response-received-at",
                            received,
                        ]
                    )
                self.assertEqual(0, result)
                outputs.append(stdout.getvalue())

            self.assertEqual(outputs[0], outputs[1])
            self.assertEqual(before, source.read_bytes())
            self.assertEqual(["stream.json"], [path.name for path in root.iterdir()])
            payload = json.loads(outputs[0])
            self.assertTrue(payload["nonPersisting"])
            serialized = outputs[0].lower()
            for forbidden in (
                "access_token",
                "refresh_token",
                "client_secret",
                "account_hash",
                "submit_order",
            ):
                self.assertNotIn(forbidden, serialized)

    def test_module_has_no_network_broker_or_persistence_capability(self) -> None:
        import momentum_hunter.schwab_candle_contract as module

        source = inspect.getsource(module)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import websocket", source)
        self.assertNotIn("api_key", source.lower())
        self.assertNotIn("client_secret", source.lower())
        self.assertNotIn("access_token", source.lower())
        self.assertNotIn("refresh_token", source.lower())
        self.assertNotIn("submit_order", source)
        self.assertNotIn("cancel_order", source)
        self.assertNotIn("replace_order", source)
        self.assertNotIn("write_text(", source)
        self.assertNotIn("open(\"w", source)


def stream_payload(
    *,
    symbol: str = "AAPL",
    timestamp: datetime | None = None,
    sequence: int = 7,
    close: float = 100.75,
    volume: int = 12_345,
) -> dict[str, object]:
    observed = timestamp or datetime(
        2026,
        7,
        31,
        14,
        31,
        tzinfo=timezone.utc,
    )
    return {
        "data": [
            {
                "service": "CHART_EQUITY",
                "timestamp": int(observed.timestamp() * 1000) + 200,
                "command": "SUBS",
                "content": [
                    {
                        "key": symbol,
                        "1": sequence,
                        "2": 100.0,
                        "3": max(101.0, close),
                        "4": 99.5,
                        "5": close,
                        "6": volume,
                        "7": int(observed.timestamp() * 1000),
                        "8": 12_345,
                    }
                ],
            }
        ]
    }


def price_history_payload(*, symbol: str = "AAPL") -> dict[str, object]:
    return {
        "symbol": symbol,
        "empty": False,
        "previousClose": 99.0,
        "previousCloseDate": 1785427200000,
        "candles": [history_row()],
    }


def history_row(
    timestamp: datetime | None = None,
    *,
    close: float = 100.75,
    volume: int = 12_345,
) -> dict[str, object]:
    observed = timestamp or datetime(
        2026,
        7,
        31,
        14,
        31,
        tzinfo=timezone.utc,
    )
    return {
        "open": 100.0,
        "high": max(101.0, close),
        "low": 99.5,
        "close": close,
        "volume": volume,
        "datetime": int(observed.timestamp() * 1000),
    }


if __name__ == "__main__":
    unittest.main()
