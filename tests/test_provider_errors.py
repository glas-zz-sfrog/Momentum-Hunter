from __future__ import annotations

import unittest

import requests

from momentum_hunter.providers import FinvizProvider, ProviderUnavailableError, is_dns_failure


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


if __name__ == "__main__":
    unittest.main()
