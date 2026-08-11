from __future__ import annotations

"""Run one bounded Alpaca premarket comparison without importing order routes."""

import argparse
import hashlib
import importlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

import momentum_hunter
from momentum_hunter.session_fidelity import (
    SYMBOLS,
    TASK_ID,
    fingerprint,
    get_checkpoint,
    require_checkpoint_start,
    require_sanitized,
    write_json_once,
)


FEED = "iex"
SNAPSHOT_PATH = "/v2/stocks/snapshots"
HISTORY_LOOKBACK_MINUTES = 15
QUOTE_FRESH_SECONDS = 30.0
BAR_FRESH_SECONDS = 120.0
ALLOWED_TASK_IDS = frozenset({TASK_ID, "SESSION-FIDELITY-003"})
FROZEN_PROBE_MODULES = (
    "momentum_hunter.schwab_setup",
    "momentum_hunter.alpaca_paper_onboarding",
    "momentum_hunter.alpaca_overnight_probe",
)
_MISSING = object()


def _load_frozen_probe(source_root: Path) -> object:
    root = source_root.expanduser().resolve()
    package = root / "momentum_hunter"
    module = package / "alpaca_overnight_probe.py"
    if not module.is_file():
        raise RuntimeError("The frozen Alpaca market-data probe is unavailable.")
    expected_paths = {
        name: package / f"{name.rsplit('.', 1)[1]}.py"
        for name in FROZEN_PROBE_MODULES
    }
    if any(not path.is_file() for path in expected_paths.values()):
        raise RuntimeError("A frozen Alpaca probe dependency is unavailable.")

    # session_fidelity imports the host Schwab stack before this adapter runs. Load
    # the frozen Alpaca dependency set as one unit so Python cannot combine that
    # host stack with the pinned provider branch.
    saved_modules = {name: sys.modules.get(name, _MISSING) for name in FROZEN_PROBE_MODULES}
    saved_attributes = {
        name.rsplit(".", 1)[1]: getattr(momentum_hunter, name.rsplit(".", 1)[1], _MISSING)
        for name in FROZEN_PROBE_MODULES
    }
    saved_package_path = list(momentum_hunter.__path__)
    package_path = str(package)
    loaded: dict[str, object] = {}
    try:
        for name in FROZEN_PROBE_MODULES:
            sys.modules.pop(name, None)
        momentum_hunter.__path__.insert(0, package_path)
        importlib.invalidate_caches()
        for name in FROZEN_PROBE_MODULES:
            loaded[name] = importlib.import_module(name)
        for name, loaded_module in loaded.items():
            origin = Path(str(getattr(loaded_module, "__file__", ""))).resolve()
            if origin != expected_paths[name].resolve():
                raise RuntimeError("A frozen Alpaca probe dependency resolved outside its pinned root.")
        return loaded["momentum_hunter.alpaca_overnight_probe"]
    finally:
        for name in FROZEN_PROBE_MODULES:
            sys.modules.pop(name, None)
        for name, saved in saved_modules.items():
            if saved is not _MISSING:
                sys.modules[name] = saved
        for attribute, saved in saved_attributes.items():
            if saved is _MISSING:
                try:
                    delattr(momentum_hunter, attribute)
                except AttributeError:
                    pass
            else:
                setattr(momentum_hunter, attribute, saved)
        momentum_hunter.__path__[:] = saved_package_path
        importlib.invalidate_caches()


def _snapshot(probe: object, client: object, secret: object) -> tuple[dict[str, object], dict[str, object]]:
    observation, payload = client.get(
        SNAPSHOT_PATH,
        params={"symbols": ",".join(SYMBOLS), "feed": FEED, "currency": "USD"},
        credentials=secret,
        feed=FEED,
        data_type="snapshot",
    )
    receipt = probe._parse_timestamp(str(observation["responseReceipt"]))
    parsed = probe._parse_latest_payload(
        "snapshot",
        payload,
        symbols=SYMBOLS,
        receipt=receipt,
        feed=FEED,
    )
    _normalize_premarket_latency(parsed)
    observation["records"] = parsed
    return observation, parsed


def _normalize_premarket_latency(records: Mapping[str, object]) -> None:
    for record in records.values():
        if not isinstance(record, dict):
            continue
        for key, fresh_limit in (
            ("latestQuote", QUOTE_FRESH_SECONDS),
            ("latestTrade", QUOTE_FRESH_SECONDS),
            ("minuteBar", BAR_FRESH_SECONDS),
        ):
            value = record.get(key)
            if not isinstance(value, dict):
                continue
            value["sourceParserLatencyClassification"] = value.get(
                "latencyClassification"
            )
            age = _age(value.get("observedAgeSeconds"))
            value["latencyClassification"] = (
                "FRESH_CONTEXT" if age <= fresh_limit else "STALE"
            )


def _history(
    probe: object,
    client: object,
    secret: object,
    *,
    target: datetime,
    end: datetime,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    requests: list[dict[str, object]] = []
    evidence: dict[str, object] = {}
    start = target - timedelta(minutes=HISTORY_LOOKBACK_MINUTES)
    for symbol in SYMBOLS:
        path = f"/v2/stocks/{symbol}/bars"
        observation, payload = client.get(
            path,
            params={
                "timeframe": "1Min",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "feed": FEED,
                "adjustment": "raw",
                "sort": "asc",
                "limit": 1000,
            },
            credentials=secret,
            feed=FEED,
            data_type="historicalBars",
        )
        bars = probe._parse_historical_bars(payload, symbol=symbol)
        analysis = probe.analyze_bars(
            bars,
            receipt=probe._parse_timestamp(str(observation["responseReceipt"])),
        )
        observation["records"] = bars
        observation["analysis"] = analysis
        requests.append(observation)
        evidence[symbol] = analysis
    return requests, evidence


def _adjudicate(snapshots: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
    fresh_quotes: set[str] = set()
    fresh_bars: set[str] = set()
    volume_symbols: set[str] = set()
    any_records = False
    for symbol, record in snapshots.items():
        if not isinstance(record, Mapping):
            continue
        any_records = True
        quote = record.get("latestQuote")
        if isinstance(quote, Mapping) and quote.get("bid") is not None and quote.get("ask") is not None:
            if _age(quote.get("observedAgeSeconds")) <= QUOTE_FRESH_SECONDS:
                fresh_quotes.add(symbol)
        bar = record.get("minuteBar")
        if isinstance(bar, Mapping):
            if _age(bar.get("observedAgeSeconds")) <= BAR_FRESH_SECONDS:
                fresh_bars.add(symbol)
            if bar.get("volume") is not None:
                volume_symbols.add(symbol)
    expected = set(SYMBOLS)
    if fresh_quotes == expected and fresh_bars == expected:
        classification = "HIGH_FIDELITY"
    elif fresh_quotes or fresh_bars:
        classification = "USEFUL_WITH_LIMITATIONS"
    elif any_records:
        classification = "STALE"
    else:
        classification = "UNAVAILABLE"
    return {
        "classification": classification,
        "freshQuoteSymbols": sorted(fresh_quotes),
        "freshCandleSymbols": sorted(fresh_bars),
        "volumeSymbols": sorted(volume_symbols),
        "QUOTE_AUTHORITY": "RESEARCH_CONTEXT_ONLY" if fresh_quotes else "NOT_PROVEN",
        "CANDLE_AUTHORITY": "RESEARCH_CONTEXT_ONLY" if fresh_bars else "NOT_PROVEN",
        "VOLUME_AUTHORITY": "RESEARCH_CONTEXT_ONLY" if volume_symbols else "NOT_PROVEN",
        "strategyAuthorityGranted": False,
        "executionAuthorityGranted": False,
    }


def _age(value: object) -> float:
    if value is None or isinstance(value, bool):
        return float("inf")
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float("inf")
    return parsed if parsed >= 0 else float("inf")


def _run_checkpoint_observation(
    checkpoint: object,
    *,
    task_id: str,
    source_root: Path,
    sleeper: object = time.sleep,
    program_context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if task_id not in ALLOWED_TASK_IDS:
        raise RuntimeError("The Alpaca session observer received an unsupported task identity.")
    if checkpoint.code not in {"A", "B", "C"} or not checkpoint.alpaca:
        raise RuntimeError("This adapter is limited to the three premarket comparisons.")
    probe = _load_frozen_probe(source_root)
    repository = probe.AlpacaPaperCredentialRepository(
        lane=probe.AlpacaPaperLane.CANARY_REALISTIC
    )
    secret = repository.load()
    client = probe.AlpacaOvernightTransport()
    started_at = datetime.now(timezone.utc)
    first_request, first = _snapshot(probe, client, secret)
    wait_seconds = max(0.0, float(checkpoint.duration_seconds - 15))
    sleeper(wait_seconds)
    final_request, final = _snapshot(probe, client, secret)
    completed_at = datetime.now(timezone.utc)
    history_requests, history = _history(
        probe,
        client,
        secret,
        target=checkpoint.target_eastern.astimezone(timezone.utc),
        end=completed_at,
    )
    result = {
        "schemaVersion": 1,
        "taskId": task_id,
        "mode": "READ_ONLY_NONPERSISTING_SESSION_FIDELITY",
        "checkpoint": checkpoint.evidence(),
        "provider": "ALPACA",
        "feed": FEED,
        "credentialLane": "CANARY_REALISTIC_PAPER",
        "symbols": list(SYMBOLS),
        "observationWindow": {
            "startedAt": started_at.isoformat(),
            "completedAt": completed_at.isoformat(),
            "durationSeconds": round((completed_at - started_at).total_seconds(), 6),
        },
        "requests": [first_request, final_request, *history_requests],
        "firstSnapshot": first,
        "finalSnapshot": final,
        "historicalBars": history,
        "adjudication": _adjudicate(final),
        "productionPersistence": False,
        "accountValuesIncluded": False,
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "previewsRequested": False,
        "mutatingRequestAttempted": False,
        "liveEndpointReachable": False,
        "orderTransmission": "UNAVAILABLE",
        "strategyAuthorityGranted": False,
        "executionAuthorityGranted": False,
        "credentialMaterialIncluded": False,
        "frozenProviderModule": {
            "pathIncluded": False,
            "moduleSha256": hashlib.sha256(
                (source_root.resolve() / "momentum_hunter" / "alpaca_overnight_probe.py").read_bytes()
            ).hexdigest().upper(),
        },
    }
    if program_context is not None:
        result["programContext"] = dict(program_context)
    result["evidenceFingerprint"] = fingerprint(result)
    require_sanitized(
        result,
        forbidden_values=(secret.key_id, secret.secret_key),
    )
    probe._assert_sanitized(result, secret)
    return result


def run(
    checkpoint_code: str,
    *,
    source_root: Path,
    now: datetime | None = None,
    sleeper: object = time.sleep,
) -> dict[str, object]:
    observed = now or datetime.now(timezone.utc)
    checkpoint = require_checkpoint_start(checkpoint_code, observed)
    return _run_checkpoint_observation(
        checkpoint,
        task_id=TASK_ID,
        source_root=source_root,
        sleeper=sleeper,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one read-only Alpaca premarket comparison.")
    parser.add_argument("--checkpoint", choices=("A", "B", "C"), required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.checkpoint, source_root=args.source_root)
        proof_hash = write_json_once(result, args.output)
        print(
            json.dumps(
                {
                    "checkpoint": args.checkpoint,
                    "classification": result["adjudication"]["classification"],
                    "feed": FEED,
                    "output": str(args.output),
                    "sha256": proof_hash,
                    "ordersRequested": False,
                    "positionsRequested": False,
                    "orderTransmission": "UNAVAILABLE",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "SESSION_FIDELITY_ALPACA_FAILED_SAFE",
                    "credentialMaterialIncluded": False,
                    "errorType": type(exc).__name__,
                    "ordersRequested": False,
                    "positionsRequested": False,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
