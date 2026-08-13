from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from momentum_hunter.schwab_candle_observer import GuardedStreamerAccess
from momentum_hunter.schwab_premarket_fidelity import (
    SchwabPremarketFidelityError,
    checkpoints_for,
    load_and_verify,
    require_checkpoint_start,
    run_checkpoint,
    write_json_once,
)
from momentum_hunter.session_fidelity import SYMBOLS


class _Guard:
    def authorize(self, ending: str) -> GuardedStreamerAccess:
        if ending != "2573":
            raise AssertionError("unexpected account ending")
        return GuardedStreamerAccess(
            access_token="synthetic-token",
            account_ending="2573",
            account_type="INDIVIDUAL_CASH",
            balances_present=True,
        )


class _Quotes:
    def __init__(self, now: object) -> None:
        self.now = now

    def fetch_quotes_with_clock(self, token: str, symbols: object) -> object:
        self.token = token
        quotes = {
            symbol: SimpleNamespace(
                provider_quote_timestamp=self.now.isoformat(),
                provider_bid_timestamp=self.now.isoformat(),
                provider_ask_timestamp=self.now.isoformat(),
                bid=100.0,
                ask=100.02,
                last=100.01,
                volume=1000,
                realtime=True,
                security_status="Normal",
                source="schwab_marketdata_v1_quotes:v1",
            )
            for symbol in symbols
        }
        return SimpleNamespace(
            quotes=quotes,
            clock_skew_proof={"responseReceivedAt": self.now.isoformat()},
        )


class _Observer:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def observe(self, options: object) -> dict[str, object]:
        return {
            "candles": [
                {
                    "symbol": symbol,
                    "status": "PASS",
                    "ohlcvComplete": True,
                    "ageAtEvaluationSeconds": 30.0,
                    "volume": 100,
                }
                for symbol in options.symbols
            ],
            "productionDataWritten": False,
        }


class SchwabPremarketFidelityTests(unittest.TestCase):
    def test_checkpoint_identity_names_only_schwab_and_converts_timezones(self) -> None:
        checkpoints = checkpoints_for(date(2026, 8, 14))
        self.assertEqual(tuple(checkpoints), ("BOUNDARY", "ACTIVE"))
        self.assertEqual(
            checkpoints["BOUNDARY"].target_central.isoformat(),
            "2026-08-14T05:55:00-05:00",
        )
        self.assertEqual(
            checkpoints["BOUNDARY"].target_eastern.isoformat(),
            "2026-08-14T06:55:00-04:00",
        )
        self.assertEqual(
            checkpoints["ACTIVE"].target_eastern.isoformat(),
            "2026-08-14T07:05:00-04:00",
        )
        for checkpoint in checkpoints.values():
            self.assertEqual(checkpoint.evidence()["providers"], ["SCHWAB"])
            self.assertEqual(checkpoint.evidence()["providerScope"], "SCHWAB_ONLY")

    def test_start_window_fails_closed(self) -> None:
        checkpoint = checkpoints_for(date(2026, 8, 14))["ACTIVE"]
        require_checkpoint_start(checkpoint, checkpoint.target_central)
        with self.assertRaises(SchwabPremarketFidelityError):
            require_checkpoint_start(checkpoint, checkpoint.target_central - timedelta(seconds=1))
        with self.assertRaises(SchwabPremarketFidelityError):
            require_checkpoint_start(checkpoint, checkpoint.target_central.replace(tzinfo=None))

    def test_schwab_probe_is_sanitized_read_only_and_high_fidelity(self) -> None:
        checkpoint = checkpoints_for(date(2026, 8, 14))["ACTIVE"]
        result = run_checkpoint(
            checkpoint,
            now=checkpoint.target_central,
            utc_clock=lambda: checkpoint.target_central,
            access_guard=_Guard(),
            quote_transport=_Quotes(checkpoint.target_central),
            observer_factory=_Observer,
        )
        self.assertEqual(result["provider"], "SCHWAB")
        self.assertEqual(result["adjudication"]["classification"], "HIGH_FIDELITY")
        self.assertFalse(result["positionsRequested"])
        self.assertFalse(result["ordersRequested"])
        self.assertEqual(result["orderTransmission"], "UNAVAILABLE")
        self.assertNotIn("synthetic-token", json.dumps(result))

    def test_write_once_rejects_tampering_and_provider_mismatch(self) -> None:
        checkpoint = checkpoints_for(date(2026, 8, 14))["ACTIVE"]
        result = run_checkpoint(
            checkpoint,
            now=checkpoint.target_central,
            utc_clock=lambda: checkpoint.target_central,
            access_guard=_Guard(),
            quote_transport=_Quotes(checkpoint.target_central),
            observer_factory=_Observer,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "proof.json"
            write_json_once(result, path)
            self.assertEqual(load_and_verify(path), result)
            with self.assertRaises(SchwabPremarketFidelityError):
                write_json_once(result, path)
            changed = json.loads(path.read_text(encoding="utf-8"))
            changed["provider"] = "ALPACA"
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(SchwabPremarketFidelityError):
                load_and_verify(path)

    def test_symbol_scope_and_runtime_routes_remain_bounded(self) -> None:
        self.assertEqual(SYMBOLS, ("SPY", "QQQ", "NVDA"))
        root = Path(__file__).resolve().parents[1]
        combined = "\n".join(
            (root / relative).read_text(encoding="utf-8")
            for relative in (
                "momentum_hunter/schwab_premarket_fidelity.py",
                "tools/run_schwab_premarket_fidelity.py",
                "tools/run_schwab_premarket_fidelity.ps1",
                "tools/install_schwab_premarket_fidelity_tasks.ps1",
            )
        )
        for forbidden in (
            "submit_order",
            "cancel_order",
            "replace_order",
            "preview_order",
            "/orders",
            "/positions",
            "productionDataWritten = True",
        ):
            self.assertNotIn(forbidden, combined)
        installer = (root / "tools/install_schwab_premarket_fidelity_tasks.ps1").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("New-ScheduledTaskTrigger -Daily", installer)
        self.assertIn('providerScope = "SCHWAB_ONLY"', installer)
        self.assertIn("startWhenAvailable = $false", installer)

    def test_powershell_scripts_parse(self) -> None:
        import subprocess

        root = Path(__file__).resolve().parents[1]
        for relative in (
            "tools/run_schwab_premarket_fidelity.ps1",
            "tools/install_schwab_premarket_fidelity_tasks.ps1",
        ):
            path = root / relative
            command = (
                "$ErrorActionPreference='Stop'; "
                f"[void][scriptblock]::Create((Get-Content -LiteralPath '{path}' -Raw));"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
