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
        del missing["data"][0]["content"][0]["5"]
        with self.assertRaisesRegex(SchwabCandleContractError, "field 5"):
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
        invalid["data"][0]["content"][0]["2"] = 99.0

        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "high was below",
        ):
            parse_chart_equity_messages(
                [invalid],
                expected_symbols=["AAPL"],
            )

    def test_stream_parser_rejects_duplicate_and_out_of_order_events(self) -> None:
        duplicate = stream_payload()
        with self.assertRaisesRegex(SchwabCandleContractError, "duplicate"):
            parse_chart_equity_messages(
                [duplicate, duplicate],
                expected_symbols=["AAPL"],
            )

        later = stream_payload(
            timestamp=datetime(2026, 7, 31, 14, 32, tzinfo=timezone.utc),
            sequence=8,
        )
        with self.assertRaisesRegex(
            SchwabCandleContractError,
            "chronological",
        ):
            parse_chart_equity_messages(
                [later, stream_payload()],
                expected_symbols=["AAPL"],
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
                        "0": symbol,
                        "1": 100.0,
                        "2": 101.0,
                        "3": 99.5,
                        "4": 100.75,
                        "5": 12_345,
                        "6": sequence,
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
        "volume": 12_345,
        "datetime": int(observed.timestamp() * 1000),
    }


if __name__ == "__main__":
    unittest.main()
