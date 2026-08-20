from __future__ import annotations

import json
import multiprocessing
import os
import tempfile
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

from momentum_hunter.schwab_auth_lock import SchwabAuthStateLock
from momentum_hunter.schwab_candle_observer import SchwabMarketDataOnlyAccessGuard
from momentum_hunter.schwab_candle_backfill import _AuthorizedHistoryReader
from momentum_hunter.schwab_candle_observer import (
    GuardedStreamerAccess,
    SchwabCandleObserverHttpForbiddenError,
    SchwabCandleObserverHttpUnauthorizedError,
)
from momentum_hunter.schwab_market_data import (
    SchwabAuthPersistenceFailed,
    SchwabMarketDataHttpForbiddenError,
    SchwabMarketDataHttpUnauthorizedError,
    SchwabMarketDataQuoteSource,
    SchwabReadOnlyAccessTokenProvider,
    SchwabReauthorizationRequired,
)
from momentum_hunter.schwab_onboarding import (
    SchwabOAuthResponseError,
    SchwabOAuthTokens,
)
from momentum_hunter.schwab_setup import SchwabApplicationCredentials
from momentum_hunter.schwab_readonly import SchwabAccountBinding


def _tokens(access_token: str, *, expired: bool) -> SchwabOAuthTokens:
    now = datetime.now(timezone.utc)
    return SchwabOAuthTokens(
        access_token=access_token,
        refresh_token="SYNTHETIC-REFRESH",
        token_type="Bearer",
        scope="synthetic",
        issued_at=now - timedelta(hours=1),
        expires_at=now - timedelta(seconds=1) if expired else now + timedelta(hours=1),
    )


class _FileSecretsRepository:
    def __init__(self, root: str) -> None:
        self.root = Path(root)
        self.path = self.root / "synthetic-auth.json"

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    def refresh_ownership(self):
        return SchwabAuthStateLock(self.path, timeout_seconds=10.0)

    def load_credentials(self) -> SchwabApplicationCredentials:
        return SchwabApplicationCredentials("SYNTHETIC-ID", "SYNTHETIC-SECRET")

    def load_tokens(self) -> SchwabOAuthTokens:
        payload = json.loads(self.path.read_text(encoding="ascii"))
        return SchwabOAuthTokens(
            access_token=str(payload["accessToken"]),
            refresh_token=str(payload["refreshToken"]),
            token_type="Bearer",
            scope="synthetic",
            issued_at=datetime.fromisoformat(str(payload["issuedAt"])),
            expires_at=datetime.fromisoformat(str(payload["expiresAt"])),
        )

    def save_tokens_under_ownership(self, tokens: SchwabOAuthTokens) -> Path:
        payload = {
            "accessToken": tokens.access_token,
            "refreshToken": tokens.refresh_token,
            "issuedAt": tokens.issued_at.isoformat(),
            "expiresAt": tokens.expires_at.isoformat(),
        }
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True),
            encoding="ascii",
        )
        temporary.replace(self.path)
        return self.path


class _CountingRefreshTransport:
    def __init__(self, root: str) -> None:
        self.counter_path = Path(root) / "refresh-count.txt"

    def refresh(self, credentials, current_tokens) -> SchwabOAuthTokens:
        del credentials, current_tokens
        count = int(self.counter_path.read_text(encoding="ascii")) + 1
        self.counter_path.write_text(str(count), encoding="ascii")
        return _tokens("SYNTHETIC-REFRESHED", expired=False)


def _multiprocess_refresh_worker(root: str, start, results) -> None:
    provider = SchwabReadOnlyAccessTokenProvider(
        secrets_repository=_FileSecretsRepository(root),
        oauth_transport=_CountingRefreshTransport(root),
    )
    start.wait(10)
    try:
        token = provider.access_token()
        results.put(("PASS", token == "SYNTHETIC-REFRESHED"))
    except Exception as exc:  # pragma: no cover - emitted to parent for diagnosis
        results.put(("FAIL", type(exc).__name__))


class _MemorySecrets:
    exists = True

    def __init__(self, tokens: SchwabOAuthTokens, *, fail_save: bool = False) -> None:
        self.tokens = tokens
        self.fail_save = fail_save
        self.save_count = 0

    def refresh_ownership(self):
        return nullcontext()

    def load_tokens(self) -> SchwabOAuthTokens:
        return self.tokens

    def load_credentials(self) -> SchwabApplicationCredentials:
        return SchwabApplicationCredentials("SYNTHETIC-ID", "SYNTHETIC-SECRET")

    def save_tokens_under_ownership(self, tokens: SchwabOAuthTokens) -> Path:
        if self.fail_save:
            raise OSError("synthetic persistence failure")
        self.tokens = tokens
        self.save_count += 1
        return Path("synthetic")


class _RefreshTransport:
    def __init__(self, *, rejected: bool = False) -> None:
        self.rejected = rejected
        self.calls = 0

    def refresh(self, credentials, current_tokens) -> SchwabOAuthTokens:
        del credentials, current_tokens
        self.calls += 1
        if self.rejected:
            raise SchwabOAuthResponseError("synthetic rejected refresh")
        return _tokens("SYNTHETIC-REFRESHED", expired=False)


class _HttpTransport:
    def __init__(self, failures: list[type[Exception]]) -> None:
        self.failures = list(failures)
        self.calls = 0

    def fetch_quotes(self, access_token, symbols):
        del access_token, symbols
        self.calls += 1
        if self.failures:
            raise self.failures.pop()("synthetic HTTP failure")
        return {}


class _RejectedTokenProvider:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.forbidden = 0

    def access_token(self) -> str:
        return "SYNTHETIC-REJECTED"

    def refresh_after_rejection(self, *, rejected_access_token=None) -> str:
        self.refresh_calls += 1
        if rejected_access_token != "SYNTHETIC-REJECTED":
            raise AssertionError("rejected token identity was not preserved")
        return "SYNTHETIC-REFRESHED"

    def record_http_forbidden(self) -> None:
        self.forbidden += 1


class _LocalBindingStore:
    def load(self) -> SchwabAccountBinding:
        return SchwabAccountBinding(
            account_hash="SYNTHETIC-HASH",
            account_number_last_four="2573",
            account_type="INDIVIDUAL_CASH",
        )


class _HistoryGuard:
    def __init__(self) -> None:
        self.forbidden = 0

    def refresh_after_rejection(self, expected_account_ending):
        return GuardedStreamerAccess(
            access_token="SYNTHETIC-REFRESHED",
            account_ending=expected_account_ending,
            account_type="INDIVIDUAL_CASH",
            balances_present=False,
        )

    def record_http_forbidden(self) -> None:
        self.forbidden += 1


class SchwabAuthLifecycleTests(unittest.TestCase):
    def test_valid_token_reads_without_refresh(self) -> None:
        secrets = _MemorySecrets(_tokens("SYNTHETIC-ACTIVE", expired=False))
        transport = _RefreshTransport()
        provider = SchwabReadOnlyAccessTokenProvider(
            secrets_repository=secrets,
            oauth_transport=transport,
        )

        self.assertEqual("SYNTHETIC-ACTIVE", provider.access_token())
        self.assertEqual(0, transport.calls)
        self.assertEqual(0, secrets.save_count)

    def test_expired_token_refreshes_persists_and_restarts(self) -> None:
        secrets = _MemorySecrets(_tokens("SYNTHETIC-EXPIRED", expired=True))
        transport = _RefreshTransport()
        provider = SchwabReadOnlyAccessTokenProvider(
            secrets_repository=secrets,
            oauth_transport=transport,
        )

        self.assertEqual("SYNTHETIC-REFRESHED", provider.access_token())
        restarted = SchwabReadOnlyAccessTokenProvider(
            secrets_repository=secrets,
            oauth_transport=_RefreshTransport(),
        )
        self.assertEqual("SYNTHETIC-REFRESHED", restarted.access_token())
        self.assertEqual(1, transport.calls)
        self.assertEqual(1, secrets.save_count)

    def test_rejected_refresh_requires_interactive_reauthorization(self) -> None:
        provider = SchwabReadOnlyAccessTokenProvider(
            secrets_repository=_MemorySecrets(
                _tokens("SYNTHETIC-EXPIRED", expired=True)
            ),
            oauth_transport=_RefreshTransport(rejected=True),
        )

        with self.assertRaises(SchwabReauthorizationRequired):
            provider.access_token()
        self.assertEqual(1, provider.metrics.interactive_reauth_required)

    def test_stale_rejected_token_adopts_newer_persisted_state(self) -> None:
        secrets = _MemorySecrets(_tokens("SYNTHETIC-NEWER", expired=False))
        transport = _RefreshTransport()
        provider = SchwabReadOnlyAccessTokenProvider(
            secrets_repository=secrets,
            oauth_transport=transport,
        )

        self.assertEqual(
            "SYNTHETIC-NEWER",
            provider.refresh_after_rejection(
                rejected_access_token="SYNTHETIC-STALE",
            ),
        )
        self.assertEqual(0, transport.calls)
        self.assertEqual(0, secrets.save_count)

    def test_persistence_failure_fails_closed(self) -> None:
        provider = SchwabReadOnlyAccessTokenProvider(
            secrets_repository=_MemorySecrets(
                _tokens("SYNTHETIC-EXPIRED", expired=True),
                fail_save=True,
            ),
            oauth_transport=_RefreshTransport(),
        )

        with self.assertRaises(SchwabAuthPersistenceFailed):
            provider.access_token()

    def test_two_processes_share_one_refresh_and_adopt_persisted_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = _FileSecretsRepository(temporary)
            repository.path.write_text(
                json.dumps(
                    {
                        "accessToken": "SYNTHETIC-EXPIRED",
                        "refreshToken": "SYNTHETIC-REFRESH",
                        "issuedAt": _tokens("x", expired=True).issued_at.isoformat(),
                        "expiresAt": _tokens("x", expired=True).expires_at.isoformat(),
                    }
                ),
                encoding="ascii",
            )
            (root / "refresh-count.txt").write_text("0", encoding="ascii")
            context = multiprocessing.get_context("spawn")
            start = context.Event()
            results = context.Queue()
            processes = [
                context.Process(
                    target=_multiprocess_refresh_worker,
                    args=(temporary, start, results),
                )
                for _ in range(2)
            ]
            for process in processes:
                process.start()
            start.set()
            observed = [results.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)

            self.assertEqual([0, 0], [process.exitcode for process in processes])
            self.assertEqual([("PASS", True), ("PASS", True)], sorted(observed))
            self.assertEqual("1", (root / "refresh-count.txt").read_text(encoding="ascii"))
            self.assertEqual("SYNTHETIC-REFRESHED", repository.load_tokens().access_token)

    def test_http_401_retries_once_and_second_401_fails_closed(self) -> None:
        provider = _RejectedTokenProvider()
        transport = _HttpTransport(
            [
                SchwabMarketDataHttpUnauthorizedError,
                SchwabMarketDataHttpUnauthorizedError,
            ]
        )
        source = SchwabMarketDataQuoteSource(
            token_provider=provider,
            transport=transport,
        )

        with self.assertRaises(SchwabMarketDataHttpUnauthorizedError):
            source.quotes(("SPY",))
        self.assertEqual(2, transport.calls)
        self.assertEqual(1, provider.refresh_calls)

    def test_http_403_never_refreshes(self) -> None:
        provider = _RejectedTokenProvider()
        source = SchwabMarketDataQuoteSource(
            token_provider=provider,
            transport=_HttpTransport([SchwabMarketDataHttpForbiddenError]),
        )

        with self.assertRaises(SchwabMarketDataHttpForbiddenError):
            source.quotes(("SPY",))
        self.assertEqual(0, provider.refresh_calls)
        self.assertEqual(1, provider.forbidden)

    def test_candle_403_after_401_refresh_is_recorded_and_fails_closed(self) -> None:
        guard = _HistoryGuard()
        reader = _AuthorizedHistoryReader(
            access_guard=guard,
            access=GuardedStreamerAccess(
                access_token="SYNTHETIC-REJECTED",
                account_ending="2573",
                account_type="INDIVIDUAL_CASH",
                balances_present=False,
            ),
            expected_account_ending="2573",
        )
        calls = 0

        def operation(_access_token):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise SchwabCandleObserverHttpUnauthorizedError("synthetic 401")
            raise SchwabCandleObserverHttpForbiddenError("synthetic 403")

        with self.assertRaises(SchwabCandleObserverHttpForbiddenError):
            reader.fetch(operation)
        self.assertEqual(2, calls)
        self.assertEqual(1, guard.forbidden)

    def test_market_data_guard_uses_local_binding_without_account_reads(self) -> None:
        guard = SchwabMarketDataOnlyAccessGuard(
            token_provider=_RejectedTokenProvider(),
            binding_store=_LocalBindingStore(),
        )

        evidence = guard.authorize("2573").evidence()
        self.assertIsNone(evidence["authorizedAccountCount"])
        self.assertFalse(evidence["accountDetailsRequested"])
        self.assertFalse(evidence["positionsRequested"])
        self.assertFalse(evidence["ordersRequested"])

    def test_metrics_never_contain_token_values(self) -> None:
        provider = SchwabReadOnlyAccessTokenProvider(
            secrets_repository=_MemorySecrets(
                _tokens("SYNTHETIC-NEVER-LEAK", expired=False)
            ),
            oauth_transport=_RefreshTransport(),
        )
        provider.access_token()

        serialized = json.dumps(provider.metrics_snapshot(), sort_keys=True)
        self.assertNotIn("SYNTHETIC-NEVER-LEAK", serialized)
        self.assertNotIn("SYNTHETIC-REFRESH", serialized)


if __name__ == "__main__":
    unittest.main()
