from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.schwab_auth_recovery import (
    main,
    run_read_only_probe,
    windows_service_context,
    write_proof_once,
)
from momentum_hunter.schwab_candle_contract import EASTERN_TZ
from momentum_hunter.schwab_candle_observer import GuardedStreamerAccess
from momentum_hunter.schwab_candle_store import SCHWAB_CANDLE_STORE_ROOT
from momentum_hunter.schwab_onboarding import SchwabOAuthTokens


TOKEN = "SYNTHETIC-RECOVERY-ACCESS"
REFRESH = "SYNTHETIC-RECOVERY-REFRESH"
AS_OF = datetime(2026, 8, 17, 9, 35, 5, tzinfo=EASTERN_TZ)


class FakeSecrets:
    def __init__(self) -> None:
        self.tokens = SchwabOAuthTokens(
            access_token=TOKEN,
            refresh_token=REFRESH,
            token_type="Bearer",
            scope="synthetic",
            issued_at=AS_OF.astimezone(timezone.utc) - timedelta(minutes=1),
            expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        )

    def load_tokens(self) -> SchwabOAuthTokens:
        return self.tokens


class FakeGuard:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def authorize(self, ending: str) -> GuardedStreamerAccess:
        self.calls.append(ending)
        return GuardedStreamerAccess(
            access_token=TOKEN,
            account_ending=ending,
            account_type="INDIVIDUAL_CASH",
            balances_present=True,
        )


class FakeQuoteTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    def fetch_quotes(self, token: str, symbols: tuple[str, ...]):
        self.calls.append((token, symbols))
        return {symbol: object() for symbol in symbols}


class FakeCandleTransport:
    def fetch_price_history(
        self,
        token: str,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
        extended_hours: bool,
    ):
        rows = []
        for session_date in (
            date(2026, 8, 10),
            date(2026, 8, 11),
            date(2026, 8, 12),
            date(2026, 8, 13),
            date(2026, 8, 14),
            date(2026, 8, 17),
        ):
            start = datetime.combine(session_date, time(9, 30), EASTERN_TZ)
            for offset in range(5):
                rows.append(_row(start + timedelta(minutes=offset), 100.0 + offset))
        return {"symbol": symbol, "empty": False, "candles": rows}

    def fetch_daily_price_history(
        self,
        token: str,
        symbol: str,
        *,
        start_at: datetime,
        end_at: datetime,
    ):
        rows = [
            _row(datetime(2026, 7, 1, tzinfo=timezone.utc) + timedelta(days=index), 200.0)
            for index in range(30)
        ]
        return {"symbol": symbol, "empty": False, "candles": rows}


class SchwabAuthRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_probe_uses_real_components_with_disposable_stores_and_redacts_secrets(self) -> None:
        guard = FakeGuard()
        quotes = FakeQuoteTransport()

        result = run_read_only_probe(
            symbols=("MU",),
            expected_account_ending="2573",
            minute_store_root=self.root / "minute",
            daily_store_root=self.root / "daily",
            evidence_as_of=AS_OF,
            secrets_repository=FakeSecrets(),
            token_provider=object(),
            access_guard=guard,
            quote_transport=quotes,
            candle_transport=FakeCandleTransport(),
            context_reader=lambda: {
                "account": "beastcomputer\\steve",
                "sid": "S-1-5-synthetic",
                "sessionId": 0,
                "serviceContext": True,
            },
        )

        self.assertEqual("PASS", result["status"])
        self.assertEqual(["2573", "2573"], guard.calls)
        self.assertEqual([(TOKEN, ("MU",))], quotes.calls)
        self.assertEqual(30, result["candleBackfill"]["minuteRows"])
        self.assertEqual(30, result["candleBackfill"]["dailyRows"])
        self.assertEqual("READY", result["readiness"]["status"])
        self.assertEqual(5, result["readiness"]["symbols"]["MU"]["openingBarCount"])
        self.assertEqual(
            5,
            result["readiness"]["symbols"]["MU"]["baselineSessionCount"],
        )
        rendered = json.dumps(result)
        self.assertNotIn(TOKEN, rendered)
        self.assertNotIn(REFRESH, rendered)
        self.assertFalse(result["boundaries"]["ordersRequested"])
        self.assertEqual("UNAVAILABLE", result["boundaries"]["orderTransmission"])

    def test_probe_refuses_production_candle_store_roots(self) -> None:
        with self.assertRaisesRegex(ValueError, "disposable"):
            run_read_only_probe(
                symbols=("MU",),
                expected_account_ending="2573",
                minute_store_root=SCHWAB_CANDLE_STORE_ROOT,
                daily_store_root=self.root / "daily",
                evidence_as_of=AS_OF,
                secrets_repository=FakeSecrets(),
                token_provider=object(),
                access_guard=FakeGuard(),
                quote_transport=FakeQuoteTransport(),
                candle_transport=FakeCandleTransport(),
            )

    def test_proof_is_write_once(self) -> None:
        path = self.root / "proof.json"
        write_proof_once({"status": "PASS"}, path)
        with self.assertRaises(FileExistsError):
            write_proof_once({"status": "CHANGED"}, path)
        self.assertEqual({"status": "PASS"}, json.loads(path.read_text()))

    def test_windows_context_reports_profile_path_and_session_deterministically(self) -> None:
        profile = str(self.root / "profile")
        with (
            patch.dict(os.environ, {"USERPROFILE": profile}, clear=False),
            patch(
                "momentum_hunter.schwab_auth_recovery._command_output",
                side_effect=(
                    "beastcomputer\\steve",
                    "USER INFORMATION\nbeastcomputer\\steve S-1-5-synthetic",
                ),
            ),
            patch(
                "momentum_hunter.schwab_auth_recovery._process_session_id",
                return_value=0,
            ),
        ):
            context = windows_service_context()

        self.assertEqual("beastcomputer\\steve", context["account"])
        self.assertEqual("S-1-5-synthetic", context["sid"])
        self.assertEqual(0, context["sessionId"])
        self.assertTrue(context["serviceContext"])
        self.assertEqual(profile, context["userProfile"])
        self.assertEqual(str(Path.cwd()), context["workingDirectory"])

    def test_failed_cli_proof_preserves_sanitized_windows_context(self) -> None:
        output = self.root / "failure.json"
        context = {
            "account": "beastcomputer\\steve",
            "sid": "S-1-5-synthetic",
            "sessionId": 0,
            "serviceContext": True,
        }
        with patch(
            "momentum_hunter.schwab_auth_recovery.windows_service_context",
            return_value=context,
        ):
            exit_code = main(
                [
                    "--symbol",
                    "MU",
                    "--expected-account-ending",
                    "2573",
                    "--minute-store-root",
                    str(SCHWAB_CANDLE_STORE_ROOT),
                    "--daily-store-root",
                    str(self.root / "daily"),
                    "--output",
                    str(output),
                ]
            )

        payload = json.loads(output.read_text())
        self.assertEqual(2, exit_code)
        self.assertEqual("FAIL", payload["status"])
        self.assertEqual(context, payload["windowsContext"])
        self.assertFalse(payload["credentialStore"]["credentialMaterialIncluded"])


def _row(timestamp: datetime, price: float) -> dict[str, object]:
    return {
        "open": price,
        "high": price + 0.5,
        "low": price - 0.5,
        "close": price + 0.25,
        "volume": 1000,
        "datetime": int(timestamp.timestamp() * 1000),
    }


if __name__ == "__main__":
    unittest.main()
