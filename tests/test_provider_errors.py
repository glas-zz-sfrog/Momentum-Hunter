from __future__ import annotations

import unittest

import requests

from momentum_hunter.models import BASE_MOMENTUM, INSTITUTIONAL_MOMENTUM
from momentum_hunter.providers import (
    FINVIZ_CANONICAL_SCREENER_COLUMNS,
    FINVIZ_CUSTOM_COLUMN_IDS,
    FinvizProvider,
    ProviderContractError,
    ProviderUnavailableError,
    canonicalize_finviz_screener_headers,
    finviz_screener_schema_fingerprint,
    is_dns_failure,
    parse_finviz_snapshot_values,
)


class ProviderErrorTests(unittest.TestCase):
    def test_dns_failure_is_classified(self) -> None:
        exc = requests.ConnectionError("Failed to resolve 'finviz.com' ([Errno 11001] getaddrinfo failed)")

        self.assertTrue(is_dns_failure(exc))

    def test_finviz_retries_with_expected_backoff_before_friendly_error(self) -> None:
        sleeps: list[int] = []
        provider = FinvizProvider(sleeper=lambda seconds: sleeps.append(seconds))

        def fail_get(*args, **kwargs):
            raise requests.ConnectionError("Failed to resolve 'finviz.com' ([Errno 11001] getaddrinfo failed)")

        provider.session.get = fail_get

        with self.assertRaises(ProviderUnavailableError) as context:
            provider._get_with_retries("https://finviz.com/screener.ashx", action="scan")

        self.assertEqual([10, 30, 60], sleeps)
        self.assertEqual("dns_failure", context.exception.reason)
        self.assertEqual("Provider unavailable / DNS failure while running finviz scan.", context.exception.user_message)

    def test_finviz_snapshot_values_parse_relative_volume(self) -> None:
        values = parse_finviz_snapshot_values(["Index", "S&P 500", "Rel Volume", "2.14", "Avg Volume", "10.2M"])

        self.assertEqual("2.14", values["rel volume"])

    def test_finviz_scan_reads_required_fields_from_one_custom_screener_response(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())
        screener = """
            <table class="screener_table">
                <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Market Cap</td><td>Shs Float</td><td>ATR</td><td>Rel Volume</td><td>Volume</td><td>Price</td><td>Change</td></tr>
                <tr><td>1</td><td data-boxover-ticker="CRWV">CRWV CRWV</td><td>CoreWeave</td><td>Technology</td><td>Software</td><td>10B</td><td>450M</td><td>8.64</td><td>2.37</td><td>50,000,000</td><td>100.00</td><td>5.5%</td></tr>
            </table>
        """
        requests_seen: list[str] = []

        class FakeResponse:
            def __init__(self, text: str) -> None:
                self.text = text

            def raise_for_status(self) -> None:
                return None

        def fake_get(url: str, **_kwargs):
            requests_seen.append(url)
            if "screener.ashx" in url:
                return FakeResponse(screener)
            raise AssertionError(url)

        provider.session.get = fake_get

        candidates = provider.scan(BASE_MOMENTUM)

        self.assertEqual(1, len(candidates))
        self.assertEqual("CRWV", candidates[0].ticker)
        self.assertEqual(2.37, candidates[0].relative_volume)
        self.assertEqual(450_000_000, candidates[0].float_shares)
        self.assertEqual(8.64, candidates[0].atr)
        self.assertEqual(1, len(requests_seen))
        self.assertIn("v=151", requests_seen[0])
        self.assertIn(
            "c=" + ",".join(str(item) for item in FINVIZ_CUSTOM_COLUMN_IDS),
            requests_seen[0],
        )

    def test_finviz_scan_accepts_current_change_and_float_headers(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())
        screener = """
            <table class="screener_table">
                <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Market Cap</td><td>Float</td><td>ATR</td><td>Rel Volume</td><td>Volume</td><td>Price</td><td>Change %</td></tr>
                <tr><td>1</td><td data-boxover-ticker="SMCI">SMCI SMCI</td><td>Super Micro Computer</td><td>Technology</td><td>Computer Hardware</td><td>23.37B</td><td>563.39M</td><td>2.46</td><td>7.02</td><td>57,422,617</td><td>36.13</td><td>14.34%</td></tr>
            </table>
        """

        class FakeResponse:
            text = screener

            def raise_for_status(self) -> None:
                return None

        provider.session.get = lambda _url, **_kwargs: FakeResponse()

        candidates = provider.scan(INSTITUTIONAL_MOMENTUM)

        self.assertEqual(1, len(candidates))
        self.assertEqual("SMCI", candidates[0].ticker)
        self.assertEqual(14.34, candidates[0].percent_change)
        self.assertEqual(563_390_000, candidates[0].float_shares)
        self.assertIsNotNone(provider.last_scan_diagnostics)
        diagnostics = provider.last_scan_diagnostics
        assert diagnostics is not None
        self.assertEqual(1, diagnostics.data_row_count)
        self.assertEqual(1, diagnostics.parsed_row_count)
        self.assertEqual(1, diagnostics.qualifying_candidate_count)
        self.assertEqual(
            FINVIZ_CANONICAL_SCREENER_COLUMNS,
            diagnostics.canonical_headers,
        )

    def test_finviz_scan_rejects_missing_required_change_column(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

        class FakeResponse:
            text = """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Market Cap</td><td>Volume</td><td>Price</td></tr>
                    <tr><td>1</td><td>SMCI</td><td>Super Micro Computer</td><td>23.37B</td><td>57,422,617</td><td>36.13</td></tr>
                </table>
            """

            def raise_for_status(self) -> None:
                return None

        provider.session.get = lambda _url, **_kwargs: FakeResponse()

        with self.assertRaisesRegex(
            ProviderContractError,
            "Finviz screener schema drift detected: missing=.*Change %",
        ):
            provider.scan(INSTITUTIONAL_MOMENTUM)

    def test_finviz_scan_allows_legitimate_empty_current_schema(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

        class FakeResponse:
            text = """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Market Cap</td><td>Float</td><td>ATR</td><td>Rel Volume</td><td>Volume</td><td>Price</td><td>Change %</td></tr>
                </table>
            """

            def raise_for_status(self) -> None:
                return None

        provider.session.get = lambda _url, **_kwargs: FakeResponse()

        self.assertEqual([], provider.scan(INSTITUTIONAL_MOMENTUM))
        diagnostics = provider.last_scan_diagnostics
        assert diagnostics is not None
        self.assertEqual(0, diagnostics.data_row_count)
        self.assertEqual(0, diagnostics.parsed_row_count)
        self.assertEqual(0, diagnostics.qualifying_candidate_count)

    def test_finviz_scan_rejects_missing_requested_custom_fields(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

        class FakeResponse:
            text = """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Market Cap</td><td>Volume</td><td>Price</td><td>Change</td></tr>
                    <tr><td>1</td><td>CRWV</td><td>CoreWeave</td><td>Technology</td><td>Software</td><td>10B</td><td>50,000,000</td><td>100.00</td><td>5.5%</td></tr>
                </table>
            """

            def raise_for_status(self) -> None:
                return None

        def fake_get(url: str, **_kwargs):
            if "screener.ashx" in url:
                return FakeResponse()
            raise requests.ConnectionError("quote page failed")

        provider.session.get = fake_get

        with self.assertRaisesRegex(
            ProviderContractError,
            "missing=Float,ATR,Rel Volume",
        ):
            provider.scan(BASE_MOMENTUM)

    def test_finviz_schema_fingerprint_normalizes_known_aliases(self) -> None:
        legacy = [
            "No.", "Ticker", "Company", "Sector", "Industry", "Market Cap",
            "Shs Float", "ATR", "Rel Volume", "Volume", "Price", "Change",
        ]
        current = [
            "No.", "Ticker", "Company", "Sector", "Industry", "Market Cap",
            "Float", "ATR", "Rel Volume", "Volume", "Price", "Change %",
        ]

        self.assertEqual(
            FINVIZ_CANONICAL_SCREENER_COLUMNS,
            canonicalize_finviz_screener_headers(legacy),
        )
        self.assertEqual(
            finviz_screener_schema_fingerprint(legacy),
            finviz_screener_schema_fingerprint(current),
        )

    def test_finviz_scan_rejects_reordered_schema(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

        class FakeResponse:
            text = """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Market Cap</td><td>Float</td><td>ATR</td><td>Rel Volume</td><td>Price</td><td>Volume</td><td>Change %</td></tr>
                </table>
            """

            def raise_for_status(self) -> None:
                return None

        provider.session.get = lambda _url, **_kwargs: FakeResponse()

        with self.assertRaisesRegex(ProviderContractError, "column-order-changed"):
            provider.scan(INSTITUTIONAL_MOMENTUM)

    def test_finviz_scan_rejects_row_width_drift(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

        class FakeResponse:
            text = """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Market Cap</td><td>Float</td><td>ATR</td><td>Rel Volume</td><td>Volume</td><td>Price</td><td>Change %</td></tr>
                    <tr><td>1</td><td>NVDA</td><td>NVIDIA</td></tr>
                </table>
            """

            def raise_for_status(self) -> None:
                return None

        provider.session.get = lambda _url, **_kwargs: FakeResponse()

        with self.assertRaisesRegex(ProviderContractError, "row shape changed"):
            provider.scan(INSTITUTIONAL_MOMENTUM)

    def test_finviz_scan_rejects_malformed_required_numeric_value(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

        class FakeResponse:
            text = """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Market Cap</td><td>Float</td><td>ATR</td><td>Rel Volume</td><td>Volume</td><td>Price</td><td>Change %</td></tr>
                    <tr><td>1</td><td>NVDA</td><td>NVIDIA</td><td>Technology</td><td>Semiconductors</td><td>4.4T</td><td>24.1B</td><td>5.2</td><td>2.1</td><td>not-a-number</td><td>182.00</td><td>4.2%</td></tr>
                </table>
            """

            def raise_for_status(self) -> None:
                return None

        provider.session.get = lambda _url, **_kwargs: FakeResponse()

        with self.assertRaisesRegex(ProviderContractError, "invalid Volume"):
            provider.scan(INSTITUTIONAL_MOMENTUM)

    def test_finviz_scan_rejects_malformed_rvol_instead_of_defaulting_to_zero(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

        class FakeResponse:
            text = """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Market Cap</td><td>Float</td><td>ATR</td><td>Rel Volume</td><td>Volume</td><td>Price</td><td>Change %</td></tr>
                    <tr><td>1</td><td>NVDA</td><td>NVIDIA</td><td>Technology</td><td>Semiconductors</td><td>4.4T</td><td>24.1B</td><td>5.2</td><td>renamed-value</td><td>42,000,000</td><td>182.00</td><td>4.2%</td></tr>
                </table>
            """

            def raise_for_status(self) -> None:
                return None

        provider.session.get = lambda _url, **_kwargs: FakeResponse()

        with self.assertRaisesRegex(ProviderContractError, "invalid Rel Volume"):
            provider.scan(INSTITUTIONAL_MOMENTUM)

    def test_finviz_quote_page_failure_does_not_repeat_screener_backoff(self) -> None:
        sleeps: list[int] = []
        provider = FinvizProvider(
            sleeper=lambda seconds: sleeps.append(seconds),
            backoff_seconds=(10, 30, 60),
        )
        request_count = 0

        def fail_get(*_args, **_kwargs):
            nonlocal request_count
            request_count += 1
            raise requests.ConnectionError("quote page failed")

        provider.session.get = fail_get

        with self.assertRaises(ProviderUnavailableError):
            provider.fetch_news("CRWV")

        self.assertEqual(1, request_count)
        self.assertEqual([], sleeps)


if __name__ == "__main__":
    unittest.main()
