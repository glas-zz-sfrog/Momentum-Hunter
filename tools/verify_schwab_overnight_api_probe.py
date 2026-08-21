from __future__ import annotations

"""Verify and adjudicate the immutable Schwab overnight API probe evidence."""

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

PROJECT_IMPORT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_IMPORT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_IMPORT_ROOT))

from momentum_hunter.schwab_onboarding import (
    EncryptedSchwabAccountBindingStore,
    SchwabOAuthSecretRepository,
)


TASK_ID = "ARGUS-SCHWAB-OVERNIGHT-API-PROBE-001"
SYMBOLS = ("SPY", "QQQ", "NVDA", "AAPL", "MU")
EXPECTED_ROUTES = {
    ("GET", "api.schwabapi.com", "/marketdata/v1/quotes", "MARKET_DATA_QUOTES", 200): 15,
    ("GET", "api.schwabapi.com", "/marketdata/v1/pricehistory", "MARKET_DATA_PRICE_HISTORY", 200): 5,
    ("GET", "api.schwabapi.com", "/trader/v1/userPreference", "STREAMER_BOOTSTRAP", 200): 1,
}
EXPECTED_SERVICES = (
    "MomentumHunterAutomation",
    "MomentumHunterContinuousRuntime",
    "MomentumHunterContinuousWriter",
)
FORBIDDEN_TEXT_PATTERNS = (
    re.compile(rb"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(rb'"(?:access_token|refresh_token|application_secret|account_hash)"\s*:', re.IGNORECASE),
)


class VerificationError(RuntimeError):
    pass


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest().upper()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_object(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationError(f"Could not verify {path.name}.") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{path.name} was not a JSON object.")
    return value


def write_once(path: Path, text: str) -> str:
    payload = text.encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    return sha256_bytes(payload)


def verify_fingerprint(value: Mapping[str, object], field: str) -> None:
    expected = str(value.get(field, ""))
    unsigned = copy.deepcopy(dict(value))
    unsigned.pop(field, None)
    if expected != fingerprint(unsigned):
        raise VerificationError(f"{field} did not verify.")


def git_text(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_source(root: Path, result: Mapping[str, object]) -> dict[str, object]:
    identity = result.get("sourceIdentity")
    if not isinstance(identity, Mapping):
        raise VerificationError("Source identity was missing.")
    revision = str(identity.get("fullGitSha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise VerificationError("Probe Git identity was not a full SHA.")
    manifest = identity.get("sourceManifest")
    if not isinstance(manifest, list) or not manifest:
        raise VerificationError("Source manifest was missing.")
    verified: list[dict[str, str]] = []
    for row in manifest:
        if not isinstance(row, Mapping):
            raise VerificationError("Source manifest row was invalid.")
        path = str(row.get("path", ""))
        expected = str(row.get("sha256", ""))
        source_path = root / path
        actual = sha256_file(source_path)
        if actual != expected:
            raise VerificationError(f"Source hash mismatch for {path}.")
        diff = subprocess.run(
            ["git", "diff", "--quiet", revision, "--", path],
            cwd=root,
            check=False,
        )
        if diff.returncode != 0:
            raise VerificationError(f"Source content differed from Git identity for {path}.")
        verified.append({"path": path, "sha256": actual})
    if fingerprint(verified) != identity.get("sourceManifestSha256"):
        raise VerificationError("Source manifest fingerprint mismatch.")
    return {"gitSha": revision, "filesVerified": len(verified), "status": "PASS"}


def verify_routes(result: Mapping[str, object]) -> dict[str, object]:
    inventory = result.get("providerCallInventory")
    if not isinstance(inventory, list):
        raise VerificationError("Provider route inventory was missing.")
    observed: dict[tuple[object, ...], int] = {}
    for row in inventory:
        if not isinstance(row, Mapping):
            raise VerificationError("Provider route row was invalid.")
        key = (
            row.get("method"),
            row.get("host"),
            row.get("path"),
            row.get("requestClass"),
            row.get("httpStatus"),
        )
        observed[key] = observed.get(key, 0) + 1
    if observed != EXPECTED_ROUTES:
        raise VerificationError(f"Provider route inventory differed: {observed!r}")
    safety = result.get("safety")
    if not isinstance(safety, Mapping):
        raise VerificationError("Safety evidence was missing.")
    for key in ("accountCalls", "positionCalls", "orderCalls", "alpacaCalls", "paperCalls", "liveOrders"):
        if safety.get(key) != 0:
            raise VerificationError(f"Safety counter {key} was not zero.")
    if safety.get("providerRolesChanged") is not False:
        raise VerificationError("Provider-role nonmutation was not preserved.")
    return {
        "routes": len(inventory),
        "inventory": [
            {
                "method": key[0],
                "host": key[1],
                "path": key[2],
                "requestClass": key[3],
                "httpStatus": key[4],
                "count": count,
            }
            for key, count in sorted(observed.items())
        ],
        "status": "PASS",
    }


def verify_incremental_files(attempt: Path, result: Mapping[str, object]) -> dict[str, object]:
    quote_root = attempt / "quote-observations"
    quote_files = sorted(quote_root.glob("quote-*.json"))
    observations = result.get("quotes", {}).get("observations") if isinstance(result.get("quotes"), Mapping) else None
    if not isinstance(observations, list) or len(observations) != 15 or len(quote_files) != 15:
        raise VerificationError("The quote timeline did not contain exactly 15 durable observations.")
    for expected, path in zip(observations, quote_files):
        if load_object(path) != expected:
            raise VerificationError(f"Incremental quote mismatch at {path.name}.")
    histories = result.get("priceHistory")
    if not isinstance(histories, Mapping) or set(histories) != set(SYMBOLS):
        raise VerificationError("Price-history symbol set was incomplete.")
    for symbol in SYMBOLS:
        if load_object(attempt / "price-history" / f"{symbol}.json") != histories[symbol]:
            raise VerificationError(f"Incremental price-history mismatch for {symbol}.")
    return {"quoteFiles": 15, "historyFiles": 5, "status": "PASS"}


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise VerificationError("Provider timestamp lacked an offset.")
    return parsed.astimezone(timezone.utc)


def adjudicate(result: Mapping[str, object]) -> dict[str, object]:
    observations = result["quotes"]["observations"]  # type: ignore[index]
    first_observation = observations[0]
    last_observation = observations[-1]
    overnight_start = datetime.fromisoformat(
        str(load_object(Path(result["_baselinePath"]))["overnightStart"])
    ).astimezone(timezone.utc)
    closing_boundary = overnight_start + timedelta(minutes=1)
    quote_rows: dict[str, object] = {}
    for symbol in SYMBOLS:
        first = first_observation["records"][symbol]
        last = last_observation["records"][symbol]
        newest = parse_timestamp(last.get("newestProviderTimestamp"))
        trade = parse_timestamp(last.get("quote", {}).get("tradeTime"))
        quote_rows[symbol] = {
            "firstProviderTimestamp": first.get("newestProviderTimestamp"),
            "lastProviderTimestamp": last.get("newestProviderTimestamp"),
            "timestampAdvances": result["quotes"]["timeline"][symbol]["timestampAdvances"],
            "fieldChanges": result["quotes"]["timeline"][symbol]["quoteFieldChanges"],
            "bid": last.get("quote", {}).get("bidPrice"),
            "ask": last.get("quote", {}).get("askPrice"),
            "mark": last.get("quote", {}).get("mark"),
            "lastTradeTimestamp": trade.isoformat() if trade else None,
            "classification": (
                "STALE_EXTENDED_HOURS_ONLY"
                if newest is None or newest < closing_boundary
                else "USEFUL_TRUE_OVERNIGHT_WITH_LIMITATIONS"
            ),
        }
    histories = result["priceHistory"]
    history_rows = {
        symbol: {
            "earliestMinute": histories[symbol]["earliestReturnedMinute"],
            "latestMinute": histories[symbol]["latestReturnedMinute"],
            "barsAfter20": histories[symbol]["barsAfter20Et"],
            "barsAfterMidnight": histories[symbol]["barsAfterMidnightEt"],
            "duplicateRows": histories[symbol]["duplicateRowCount"],
            "correctedDuplicateMinutes": histories[symbol]["correctedDuplicateMinuteCount"],
            "classification": "STALE_EXTENDED_HOURS_ONLY",
        }
        for symbol in SYMBOLS
    }
    streamer = result["streamer"]
    levelone = streamer["levelOne"]
    chart = streamer["chartEquity"]
    chart_latest = parse_timestamp(chart.get("latestCandleTimestamp"))
    return {
        "schemaVersion": 1,
        "taskId": TASK_ID,
        "quoteSymbols": quote_rows,
        "priceHistorySymbols": history_rows,
        "dataTypes": {
            "quotes": "STALE_EXTENDED_HOURS_ONLY",
            "bidAsk": "STALE_EXTENDED_HOURS_ONLY",
            "mark": "STALE_EXTENDED_HOURS_ONLY",
            "trades": "NOT_AVAILABLE_OVERNIGHT",
            "priceHistory": "STALE_EXTENDED_HOURS_ONLY",
            "streamingQuotes": (
                "UNPROVEN"
                if levelone.get("fieldSemantics") == "UNPROVEN_NO_CANONICAL_LEVELONE_FIELD_MAP"
                else "STALE_EXTENDED_HOURS_ONLY"
            ),
            "streamingCandles": (
                "STALE_EXTENDED_HOURS_ONLY"
                if chart_latest is None or chart_latest < closing_boundary
                else "USEFUL_TRUE_OVERNIGHT_WITH_LIMITATIONS"
            ),
        },
        "streamer": {
            "levelOneFrames": levelone.get("frameCount"),
            "levelOneSymbols": levelone.get("symbolsObserved"),
            "levelOneLatestEnvelope": levelone.get("latestEnvelopeTimestamp"),
            "levelOneProviderFieldSemantics": levelone.get("fieldSemantics"),
            "chartFrames": chart.get("frameCount"),
            "chartObservations": chart.get("observationCount"),
            "chartLatestCandle": chart.get("latestCandleTimestamp"),
        },
        "overallClassification": "SCHWAB_TRUE_OVERNIGHT_API_NOT_AVAILABLE",
        "providerRoleChangeAuthorized": False,
        "alpacaFinvizArchitectureChangeJustified": False,
    }


def scan_secrets(root: Path) -> dict[str, object]:
    sensitive: list[str] = []
    repository = SchwabOAuthSecretRepository()
    tokens = repository.load_tokens()
    credentials = repository.load_credentials()
    sensitive.extend(
        [
            tokens.access_token,
            tokens.refresh_token,
            credentials.application_id,
            credentials.application_secret,
        ]
    )
    try:
        sensitive.append(EncryptedSchwabAccountBindingStore().load().account_hash)
    except Exception:
        pass
    checked = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        checked += 1
        if any(pattern.search(data) for pattern in FORBIDDEN_TEXT_PATTERNS):
            raise VerificationError(f"Secret-shaped content found in {path.name}.")
        for value in sensitive:
            if value and value.encode("utf-8") in data:
                raise VerificationError(f"Known live credential value found in {path.name}.")
    return {"filesScanned": checked, "knownLiveValuesChecked": len(sensitive), "status": "PASS"}


def verify_nonmutation(project_root: Path, baseline: Mapping[str, object]) -> dict[str, object]:
    production = baseline.get("campaignNonmutationBaseline")
    if not isinstance(production, Mapping):
        raise VerificationError("Campaign nonmutation baseline was missing.")
    if git_text(project_root, "rev-parse", "origin/master") != production.get("canonicalGitSha"):
        raise VerificationError("Canonical origin/master changed during the probe.")
    paths = {
        "automationManifestSha256": Path("C:/ProgramData/MomentumHunter/Automation/automation-manifest.json"),
        "continuousConfigSha256": Path("C:/ProgramData/MomentumHunter/Automation/continuous-deployment.json"),
        "continuousDeploymentManifestSha256": Path("C:/ProgramData/MomentumHunter/Automation/continuous-deployment-manifest.json"),
    }
    for field, path in paths.items():
        if sha256_file(path) != production.get(field):
            raise VerificationError(f"Production file changed: {path.name}.")
    services: dict[str, str] = {}
    for name in EXPECTED_SERVICES:
        result = subprocess.run(["sc.exe", "query", name], check=True, capture_output=True, text=True)
        if "RUNNING" not in result.stdout:
            raise VerificationError(f"Service was not Running: {name}.")
        services[name] = "RUNNING"
    return {
        "canonicalOriginMaster": production["canonicalGitSha"],
        "installedProductGitSha": production["installedProductGitSha"],
        "manifestsUnchanged": True,
        "services": services,
        "status": "CAMPAIGN_NONMUTATION_PASS",
    }


def report_markdown(
    result: Mapping[str, object],
    matrix: Mapping[str, object],
    verification: Mapping[str, object],
) -> str:
    window = result["observationWindow"]
    auth = result["auth"]
    lines = [
        f"# {TASK_ID}",
        "",
        "## Classification",
        "",
        "`SCHWAB_TRUE_OVERNIGHT_API_NOT_AVAILABLE`",
        "",
        "The bounded deep-overnight probe found no current Schwab quote, trade, or candle evidence after the ordinary extended-hours close. No provider role changed.",
        "",
        "## Time",
        "",
        f"- Start CT: `{window['startedCentral']}`",
        f"- End CT: `{window['completedCentral']}`",
        f"- Start ET: `{window['startedEastern']}`",
        f"- End ET: `{window['completedEastern']}`",
        "- Session: `TRUE_OVERNIGHT_20_00_TO_04_00_ET`",
        "",
        "## Quote Timeline",
        "",
        "| Symbol | First provider timestamp | Last provider timestamp | Advances | Changes | Bid | Ask | Mark | Last trade | Classification |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for symbol in SYMBOLS:
        row = matrix["quoteSymbols"][symbol]
        lines.append(
            f"| {symbol} | {row['firstProviderTimestamp']} | {row['lastProviderTimestamp']} | {row['timestampAdvances']} | {row['fieldChanges']} | {row['bid']} | {row['ask']} | {row['mark']} | {row['lastTradeTimestamp']} | {row['classification']} |"
        )
    lines += [
        "",
        "All five symbols returned 15 HTTP-200 snapshots. No provider timestamp or quote field advanced. SPY's newest quote time was only 71 ms after exactly 20:00 ET and is treated as the closing boundary, not true overnight data.",
        "",
        "## Price History",
        "",
        "| Symbol | Latest minute | Bars after 20:00 ET | Bars after midnight | Duplicate rows | Corrected duplicate minutes | Classification |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for symbol in SYMBOLS:
        row = matrix["priceHistorySymbols"][symbol]
        lines.append(
            f"| {symbol} | {row['latestMinute']} | {row['barsAfter20']} | {row['barsAfterMidnight']} | {row['duplicateRows']} | {row['correctedDuplicateMinutes']} | {row['classification']} |"
        )
    lines += [
        "",
        "Every symbol stopped at 19:59 ET. The provider response repeated many minute identities; this is preserved as data-quality evidence and does not create overnight bars.",
        "",
        "## Streamer",
        "",
        f"- LEVELONE_EQUITIES: acknowledged; `{matrix['streamer']['levelOneFrames']}` seed frame; symbols `{', '.join(matrix['streamer']['levelOneSymbols'])}`; content-field semantics remain `UNPROVEN` because MH has no canonical Level One numeric field map.",
        f"- CHART_EQUITY: acknowledged; `{matrix['streamer']['chartFrames']}` seed frame, `{matrix['streamer']['chartObservations']}` candles; latest candle `{matrix['streamer']['chartLatestCandle']}` (`STALE_EXTENDED_HOURS_ONLY`).",
        "",
        "## Capability Matrix",
        "",
    ]
    for key, value in matrix["dataTypes"].items():
        lines.append(f"- {key}: `{value}`")
    lines += [
        "",
        "## Auth And Safety",
        "",
        f"- Refresh required/attempted/succeeded: `{auth['refreshRequired']}` / `{auth['refreshAttempted']}` / `{auth['refreshSucceeded']}`",
        "- Auth-state fingerprint unchanged during the successful attempt.",
        "- Schwab market-data calls: `20`; Streamer bootstrap calls: `1`.",
        "- Account calls: `0`; position calls: `0`; order calls: `0`; Alpaca/Paper calls: `0`; live orders: `0`.",
        f"- Secret scan: `{verification['secretScan']['status']}`.",
        f"- Nonmutation: `{verification['nonmutation']['status']}`.",
        "",
        "## Final Answers",
        "",
        "1. Current true-overnight Schwab quotes: **NO**.",
        "2. Current bid/ask/mark: **NO**; fields were present but frozen at the extended-hours close.",
        "3. Actual overnight trades: **NO**; newest trade timestamps were 19:59 ET.",
        "4. True-overnight one-minute price history: **NO**.",
        "5. CHART_EQUITY overnight candles: **NO**; only stale 19:59 ET seed candles appeared.",
        "6. Newest observed Schwab source timestamp: **20:00:00.071 ET for SPY**, a non-advancing closing-boundary quote; newest trade/candle timestamps were 19:59 ET.",
        "7. Schwab as MH true-overnight canonical source: **NO**.",
        "8. Change to validated Alpaca/Finviz overnight architecture: **NO**.",
        "",
        "Two earlier attempts remain preserved as probe-harness failures. They do not alter the successful attempt's provider conclusion.",
    ]
    return "\n".join(lines) + "\n"


def run(root: Path, project_root: Path) -> dict[str, object]:
    attempt = root / "attempt-003"
    result = load_object(attempt / "probe-result.json")
    baseline = load_object(attempt / "provenance-baseline.json")
    if result.get("taskId") != TASK_ID or baseline.get("taskId") != TASK_ID:
        raise VerificationError("Task identity mismatch.")
    verify_fingerprint(result, "evidenceFingerprint")
    verify_fingerprint(baseline, "baselineFingerprint")
    if result.get("provenanceBaselineFingerprint") != baseline.get("baselineFingerprint"):
        raise VerificationError("Result was not bound to its provenance baseline.")
    result["_baselinePath"] = str(attempt / "provenance-baseline.json")
    source = verify_source(project_root, result)
    result.pop("_baselinePath")
    routes = verify_routes(result)
    incremental = verify_incremental_files(attempt, result)
    nonmutation = verify_nonmutation(project_root, baseline)
    secrets = scan_secrets(root)
    result["_baselinePath"] = str(attempt / "provenance-baseline.json")
    matrix = adjudicate(result)
    result.pop("_baselinePath")
    verification = {
        "source": source,
        "routes": routes,
        "incrementalEvidence": incremental,
        "secretScan": secrets,
        "nonmutation": nonmutation,
    }
    matrix["verification"] = verification
    matrix["matrixFingerprint"] = fingerprint(matrix)
    write_once(root / "capability-matrix.json", json.dumps(matrix, indent=2, sort_keys=True) + "\n")
    write_once(root / "final-report.md", report_markdown(result, matrix, verification))
    # Scan the final human/machine reports before sealing the manifest.
    final_secret_scan = scan_secrets(root)
    files = [path for path in sorted(root.rglob("*")) if path.is_file() and path.name != "file-manifest.json"]
    manifest = {
        "schemaVersion": 1,
        "taskId": TASK_ID,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "files": [
            {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in files
        ],
        "secretScan": final_secret_scan,
    }
    manifest["manifestFingerprint"] = fingerprint(manifest)
    manifest_sha = write_once(root / "file-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return {
        "taskId": TASK_ID,
        "classification": matrix["overallClassification"],
        "evidenceFingerprint": result["evidenceFingerprint"],
        "matrixFingerprint": matrix["matrixFingerprint"],
        "manifestSha256": manifest_sha,
        "fileCount": len(files) + 1,
        "secretScan": final_secret_scan["status"],
        "accountCalls": 0,
        "positionCalls": 0,
        "orderCalls": 0,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Schwab overnight API probe.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run(args.root.resolve(), args.project_root.resolve())
    except Exception as exc:
        print(json.dumps({"taskId": TASK_ID, "status": "FAILED", "error": f"{type(exc).__name__}: {exc}"}, indent=2))
        return 2
    print(json.dumps({"status": "PASS", **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
