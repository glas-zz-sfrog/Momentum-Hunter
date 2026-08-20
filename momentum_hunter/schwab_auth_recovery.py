"""Sanitized read-only proof for production-context Schwab candle authorization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping

from momentum_hunter.opening_candle_readiness import inspect_opening_candle_store
from momentum_hunter.schwab_candle_backfill import (
    CandleBackfillOptions,
    SchwabHistoricalCandleBackfiller,
)
from momentum_hunter.schwab_candle_collector import CandleSymbolUniverse
from momentum_hunter.schwab_candle_contract import normalize_symbols
from momentum_hunter.schwab_candle_observer import (
    SchwabCandleAccessGuard,
    SchwabCandleHttpTransport,
    sanitized_candle_failure,
)
from momentum_hunter.schwab_candle_store import (
    SCHWAB_CANDLE_STORE_ROOT,
    SchwabCandleStore,
)
from momentum_hunter.schwab_daily_candle_store import (
    SCHWAB_DAILY_CANDLE_STORE_ROOT,
    SchwabDailyCandleStore,
)
from momentum_hunter.schwab_market_data import (
    BoundSchwabAccessTokenProvider,
    SchwabMarketDataTransport,
)
from momentum_hunter.schwab_onboarding import SchwabOAuthSecretRepository
from momentum_hunter.schwab_setup import DEFAULT_SECRET_PATH


PROBE_SCHEMA_VERSION = 1
PROBE_MODE = "SCHWAB_AUTH_RECOVERY_001_DIAGNOSTIC"
MAX_PROBE_SYMBOLS = 2


def run_read_only_probe(
    *,
    symbols: tuple[str, ...],
    expected_account_ending: str,
    minute_store_root: Path,
    daily_store_root: Path,
    evidence_as_of: datetime,
    secrets_repository: SchwabOAuthSecretRepository | None = None,
    token_provider: object | None = None,
    access_guard: object | None = None,
    quote_transport: object | None = None,
    candle_transport: object | None = None,
    context_reader: Callable[[], Mapping[str, object]] | None = None,
) -> dict[str, object]:
    normalized = tuple(normalize_symbols(symbols))
    if not normalized or len(normalized) > MAX_PROBE_SYMBOLS:
        raise ValueError("Schwab auth recovery requires one or two symbols.")
    if len(expected_account_ending) != 4 or not expected_account_ending.isdigit():
        raise ValueError("Expected account ending must contain exactly four digits.")
    if evidence_as_of.tzinfo is None or evidence_as_of.utcoffset() is None:
        raise ValueError("Schwab auth recovery requires an aware evidence timestamp.")
    _require_disposable_root(minute_store_root, SCHWAB_CANDLE_STORE_ROOT)
    _require_disposable_root(daily_store_root, SCHWAB_DAILY_CANDLE_STORE_ROOT)

    secrets = secrets_repository or SchwabOAuthSecretRepository()
    provider = token_provider or BoundSchwabAccessTokenProvider(
        secrets_repository=secrets,
    )
    try:
        before = secrets.load_tokens()
    except Exception:
        provider.access_token()
        raise
    before_expired = before.expired
    secret_path = Path(
        getattr(getattr(secrets, "store", None), "path", DEFAULT_SECRET_PATH)
    )
    guard = access_guard or SchwabCandleAccessGuard(token_provider=provider)
    access = guard.authorize(expected_account_ending)
    quotes = (quote_transport or SchwabMarketDataTransport()).fetch_quotes(
        access.access_token,
        normalized,
    )

    universe = CandleSymbolUniverse(
        symbols=normalized,
        sources_by_symbol={symbol: ("AUTH_RECOVERY_DIAGNOSTIC",) for symbol in normalized},
        excluded_symbols=(),
        warnings=(),
        input_fingerprints={},
    )
    backfill = SchwabHistoricalCandleBackfiller(
        minute_store=SchwabCandleStore(minute_store_root),
        daily_store=SchwabDailyCandleStore(daily_store_root),
        access_guard=guard,
        http_transport=candle_transport or SchwabCandleHttpTransport(),
        utc_clock=lambda: evidence_as_of.astimezone(timezone.utc),
    ).backfill(
        universe,
        CandleBackfillOptions(
            expected_account_ending=expected_account_ending,
            history_attempts=1,
        ),
    )
    _bars, _rvol, readiness, readiness_findings = inspect_opening_candle_store(
        normalized,
        evidence_as_of=evidence_as_of,
        minute_store_root=minute_store_root,
    )
    after = secrets.load_tokens()
    context = dict((context_reader or windows_service_context)())
    refreshed = before.issued_at != after.issued_at
    result: dict[str, object] = {
        "schemaVersion": PROBE_SCHEMA_VERSION,
        "mode": PROBE_MODE,
        "status": (
            "PASS"
            if backfill.get("status") == "COMPLETE"
            and len(quotes) == len(normalized)
            and all(item.get("status") == "READY" for item in readiness.values())
            else "FAIL"
        ),
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "evidenceAsOf": evidence_as_of.isoformat(),
        "symbols": list(normalized),
        "windowsContext": context,
        "credentialStore": {
            "path": str(secret_path),
            "exists": secret_path.is_file(),
            "dpapiDecryptSuccess": True,
            "accessTokenPresent": bool(before.access_token),
            "accessTokenExpiresAt": before.expires_at.isoformat(),
            "accessTokenStateBefore": "EXPIRED" if before_expired else "ACTIVE",
            "refreshTokenPresent": bool(before.refresh_token),
            "refreshAttempted": before_expired or refreshed,
            "refreshSucceeded": refreshed and not after.expired,
            "reauthorizationRequired": False,
            "credentialMaterialIncluded": False,
        },
        "accountRead": {
            "status": "PASS",
            "authorizedAccountCount": 1,
            "accountEnding": access.account_ending,
            "accountType": access.account_type,
            "balanceValuesIncluded": False,
            "positionsRequested": False,
            "ordersRequested": False,
        },
        "quoteRead": {
            "status": "PASS" if len(quotes) == len(normalized) else "FAIL",
            "symbolCount": len(quotes),
            "valuesIncluded": False,
        },
        "candleBackfill": {
            "status": backfill.get("status"),
            "minuteRows": sum(
                int(item["minute"]["rows"]) for item in backfill.get("symbols", [])
            ),
            "dailyRows": sum(
                int(item["daily"]["rows"]) for item in backfill.get("symbols", [])
            ),
            "resultFingerprint": str(backfill.get("resultFingerprint", "")),
            "productionStoreWritten": False,
        },
        "readiness": {
            "status": (
                "READY"
                if all(item.get("status") == "READY" for item in readiness.values())
                else "NOT_READY"
            ),
            "symbols": {
                symbol: {
                    "status": readiness[symbol].get("status"),
                    "openingBarCount": readiness[symbol].get("openingBarCount"),
                    "baselineSessionCount": readiness[symbol].get(
                        "baselineSessionCount"
                    ),
                }
                for symbol in normalized
            },
            "findings": list(readiness_findings),
        },
        "boundaries": {
            "diagnosticOnly": True,
            "sourceCaptureMutated": False,
            "productionCandleStoreMutated": False,
            "paperStateMutated": False,
            "shadowStateMutated": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        },
    }
    result["resultFingerprint"] = _fingerprint(result)
    return result


def windows_service_context() -> dict[str, object]:
    identity = _command_output(("whoami.exe",))
    sid_output = _command_output(("whoami.exe", "/user"))
    sid = ""
    for line in sid_output.splitlines():
        if "S-1-" in line:
            sid = line.split()[-1]
            break
    return {
        "account": identity,
        "sid": sid,
        "processId": os.getpid(),
        "sessionId": _process_session_id(),
        "serviceContext": _process_session_id() == 0,
        "userProfile": os.environ.get("USERPROFILE", ""),
        "workingDirectory": str(Path.cwd()),
        "credentialStorePath": str(DEFAULT_SECRET_PATH),
    }


def write_proof_once(result: Mapping[str, object], output_path: Path) -> Path:
    target = output_path.expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(result), indent=2, sort_keys=True) + "\n").encode("utf-8")
    with target.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a sanitized Schwab read-only recovery proof.")
    parser.add_argument("--symbol", action="append", required=True)
    parser.add_argument("--expected-account-ending", required=True)
    parser.add_argument("--minute-store-root", type=Path, required=True)
    parser.add_argument("--daily-store-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_read_only_probe(
            symbols=tuple(args.symbol),
            expected_account_ending=args.expected_account_ending,
            minute_store_root=args.minute_store_root,
            daily_store_root=args.daily_store_root,
            evidence_as_of=datetime.now().astimezone(),
        )
    except Exception as exc:
        context = windows_service_context()
        result = {
            "schemaVersion": PROBE_SCHEMA_VERSION,
            "mode": PROBE_MODE,
            "status": "FAIL",
            "failure": sanitized_candle_failure(exc),
            "windowsContext": context,
            "credentialStore": {
                "path": str(DEFAULT_SECRET_PATH),
                "exists": DEFAULT_SECRET_PATH.is_file(),
                "dpapiDecryptSuccess": None,
                "credentialMaterialIncluded": False,
            },
            "credentialMaterialIncluded": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }
    write_proof_once(result, args.output)
    print(json.dumps({
        "status": result["status"],
        "outputPath": str(args.output.resolve(strict=False)),
        "credentialMaterialIncluded": False,
        "ordersRequested": False,
    }, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 2


def _require_disposable_root(candidate: Path, protected: Path) -> None:
    resolved = candidate.expanduser().resolve(strict=False)
    protected_resolved = protected.expanduser().resolve(strict=False)
    if (
        resolved == protected_resolved
        or protected_resolved in resolved.parents
        or resolved in protected_resolved.parents
    ):
        raise ValueError("The recovery proof requires a disposable candle-store root.")


def _process_session_id() -> int:
    if os.name != "nt":
        return -1
    import ctypes

    session_id = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(
        os.getpid(),
        ctypes.byref(session_id),
    ):
        return -1
    return int(session_id.value)


def _command_output(command: tuple[str, ...]) -> str:
    try:
        result = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _fingerprint(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest().upper()


if __name__ == "__main__":
    raise SystemExit(main())
