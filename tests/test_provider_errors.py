from __future__ import annotations

import unittest

import requests

from momentum_hunter.models import BASE_MOMENTUM
from momentum_hunter.providers import FinvizProvider, ProviderUnavailableError, is_dns_failure, parse_finviz_snapshot_values


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

    def test_finviz_scan_enriches_relative_volume_from_quote_snapshot(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())
        responses = {
            "screener": """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Country</td><td>Market Cap</td><td>P/E</td><td>Price</td><td>Change</td><td>Volume</td></tr>
                    <tr><td>1</td><td>CRWV</td><td>CoreWeave</td><td>Technology</td><td>Software</td><td>USA</td><td>10B</td><td>-</td><td>100.00</td><td>5.5%</td><td>50,000,000</td></tr>
                </table>
            """,
            "quote": """
                <table class="snapshot-table2">
                    <tr><td>Index</td><td>S&P 500</td><td>Rel Volume</td><td>2.37</td></tr>
                </table>
                <table id="news-table"></table>
            """,
        }

        class FakeResponse:
            def __init__(self, text: str) -> None:
                self.text = text

            def raise_for_status(self) -> None:
                return None

        def fake_get(url: str, **_kwargs):
            if "screener.ashx" in url:
                return FakeResponse(responses["screener"])
            if "quote.ashx" in url:
                return FakeResponse(responses["quote"])
            raise AssertionError(url)

        provider.session.get = fake_get

        candidates = provider.scan(BASE_MOMENTUM)

        self.assertEqual(1, len(candidates))
        self.assertEqual("CRWV", candidates[0].ticker)
        self.assertEqual(2.37, candidates[0].relative_volume)

    def test_finviz_scan_keeps_candidate_when_relative_volume_enrichment_fails(self) -> None:
        provider = FinvizProvider(sleeper=lambda _seconds: None, backoff_seconds=())

        class FakeResponse:
            text = """
                <table class="screener_table">
                    <tr><td>No.</td><td>Ticker</td><td>Company</td><td>Sector</td><td>Industry</td><td>Country</td><td>Market Cap</td><td>P/E</td><td>Price</td><td>Change</td><td>Volume</td></tr>
                    <tr><td>1</td><td>CRWV</td><td>CoreWeave</td><td>Technology</td><td>Software</td><td>USA</td><td>10B</td><td>-</td><td>100.00</td><td>5.5%</td><td>50,000,000</td></tr>
                </table>
            """

            def raise_for_status(self) -> None:
                return None

        def fake_get(url: str, **_kwargs):
            if "screener.ashx" in url:
                return FakeResponse()
            raise requests.ConnectionError("quote page failed")

        provider.session.get = fake_get

        candidates = provider.scan(BASE_MOMENTUM)

        self.assertEqual(1, len(candidates))
        self.assertEqual("CRWV", candidates[0].ticker)
        self.assertEqual(0.0, candidates[0].relative_volume)


if __name__ == "__main__":
    unittest.main()
