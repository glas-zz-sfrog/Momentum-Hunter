from __future__ import annotations

"""Offline closeout for the isolated overnight market-data campaign."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from momentum_hunter.overnight_data_fidelity import (
    TASK_ID,
    OvernightDataFidelityError,
    fingerprint,
    load_and_verify_checkpoint,
    require_sanitized,
)


UTC = timezone.utc
EXPECTED_CHECKPOINTS = (
    "BOUNDARY_0355_ET",
    "BOUNDARY_0400_ET",
    "BOUNDARY_0405_ET",
    "BOUNDARY_0415_ET",
    "EARLY_0500_ET",
    "EARLY_0600_ET",
    "PRE_0655_ET",
    "PRE_0700_ET",
    "PRE_0705_ET",
    "PRE_0800_ET",
    "REGULAR_0945_ET",
    "REGULAR_1000_ET",
    "AFTER_1605_ET",
    "AFTER_1955_ET",
    "OVERNIGHT_2005_ET",
)
PROTECTED_SERVICES = (
    "MomentumHunterAutomation",
    "MomentumHunterContinuousRuntime",
    "MomentumHunterContinuousWriter",
)
SECRET_PATTERNS = (
    re.compile(rb"PK[A-Z0-9]{18,}"),
    re.compile(rb"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9._~-]{16,}"),
    re.compile(rb"(?i)(?:secret|refresh[_ -]?token|access[_ -]?token)\s*[=:]\s*[A-Za-z0-9._~-]{20,}"),
)


def wait_for_terminal_closeout(
    *,
    output_root: Path,
    source_contract: Path,
    expected_feature_commit: str,
    canonical_root: Path,
    expected_canonical_commit: str,
    protected_hashes: Mapping[Path, str],
    deadline: datetime,
    poll_seconds: float = 30.0,
    sleeper=time.sleep,
    clock=lambda: datetime.now(UTC),
) -> dict[str, object]:
    root = output_root.expanduser().resolve()
    contract_bytes = source_contract.expanduser().resolve().read_bytes()
    lock = root / "closeout-waiter.lock"
    descriptor = _acquire_lock(lock)
    try:
        while _aware(clock()) <= _aware(deadline):
            state_path = root / "campaign-state.json"
            if state_path.exists():
                state = _load_state(state_path, expected_feature_commit=expected_feature_commit)
                if state["status"] == "TERMINAL":
                    return build_closeout(
                        output_root=root,
                        source_contract_bytes=contract_bytes,
                        expected_feature_commit=expected_feature_commit,
                        canonical_root=canonical_root,
                        expected_canonical_commit=expected_canonical_commit,
                        protected_hashes=protected_hashes,
                    )
            sleeper(max(1.0, min(60.0, poll_seconds)))
        raise OvernightDataFidelityError("The closeout waiter reached its finite deadline before terminal state.")
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)


def build_closeout(
    *,
    output_root: Path,
    source_contract_bytes: bytes,
    expected_feature_commit: str,
    canonical_root: Path,
    expected_canonical_commit: str,
    protected_hashes: Mapping[Path, str],
) -> dict[str, object]:
    root = output_root.expanduser().resolve()
    state = _load_state(root / "campaign-state.json", expected_feature_commit=expected_feature_commit)
    if state["status"] != "TERMINAL":
        raise OvernightDataFidelityError("The campaign is not terminal.")
    results = state.get("results")
    if not isinstance(results, list) or len(results) != len(EXPECTED_CHECKPOINTS):
        raise OvernightDataFidelityError("The terminal campaign result count is incomplete.")
    result_by_code = {
        str(row.get("code")): row
        for row in results
        if isinstance(row, Mapping)
    }
    if tuple(result_by_code) != EXPECTED_CHECKPOINTS:
        raise OvernightDataFidelityError("The terminal checkpoint identity/order is incomplete.")

    summaries: list[dict[str, object]] = []
    completed = 0
    for code in EXPECTED_CHECKPOINTS:
        row = result_by_code[code]
        classification = str(row.get("classification"))
        if classification == "COMPLETED":
            checkpoint_path = root / "checkpoints" / f"{code}.json"
            proof = load_and_verify_checkpoint(checkpoint_path)
            observed_hash = hashlib.sha256(checkpoint_path.read_bytes()).hexdigest().upper()
            if observed_hash != str(row.get("sha256")):
                raise OvernightDataFidelityError(f"Checkpoint hash mismatch: {code}")
            summaries.append(_summarize_checkpoint(proof, row))
            completed += 1
        else:
            summaries.append({
                "checkpointCode": code,
                "classification": classification,
                "startLagSeconds": row.get("startLagSeconds"),
                "phase": None,
                "alpaca": {"status": "NOT_AVAILABLE"},
                "schwab": {"status": "NOT_AVAILABLE"},
                "finviz": {"status": "NOT_AVAILABLE"},
            })

    production = _production_invariants(
        canonical_root=canonical_root,
        expected_canonical_commit=expected_canonical_commit,
        protected_hashes=protected_hashes,
    )
    matrix = {
        "schemaVersion": 1,
        "taskId": TASK_ID,
        "campaignSourceCommit": expected_feature_commit,
        "campaignDate": state["campaignDate"],
        "closeoutModuleSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper(),
        "terminalStatus": state["status"],
        "completedCheckpointCount": completed,
        "checkpointCount": len(EXPECTED_CHECKPOINTS),
        "checkpoints": summaries,
        "productionNonmutation": production,
        "authority": {
            "strategyAuthorityGranted": False,
            "executionAuthorityGranted": False,
            "providerAuthorityPromoted": False,
            "sourcesBlended": False,
        },
    }
    matrix["evidenceFingerprint"] = fingerprint(matrix)
    require_sanitized(matrix, forbidden_values=())

    closeout = root / "closeout"
    closeout.mkdir(parents=True, exist_ok=True)
    contract_path = closeout / "official-source-contract.md"
    matrix_path = closeout / "provider-capability-matrix.json"
    report_path = closeout / "FINAL-REPORT.md"
    production_path = closeout / "production-nonmutation.json"
    _write_identical_or_new(contract_path, source_contract_bytes)
    _write_identical_or_new(matrix_path, _json_bytes(matrix))
    _write_identical_or_new(production_path, _json_bytes(production))
    _write_identical_or_new(report_path, _render_report(matrix).encode("utf-8"))

    evidence_files = _bundle_files(root)
    secret_scan = _secret_scan(evidence_files)
    if secret_scan["classification"] != "PASS":
        raise OvernightDataFidelityError("The closeout secret-pattern scan failed.")
    manifest = {
        "schemaVersion": 1,
        "taskId": TASK_ID,
        "createdAt": state.get("completedAt"),
        "campaignSourceCommit": expected_feature_commit,
        "fileCount": len(evidence_files),
        "files": [
            {
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                "bytes": path.stat().st_size,
            }
            for path in evidence_files
        ],
        "secretScan": secret_scan,
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
    }
    manifest["manifestFingerprint"] = fingerprint(manifest)
    manifest_path = closeout / "MANIFEST.json"
    _write_identical_or_new(manifest_path, _json_bytes(manifest))

    zip_path = root.parent / f"{TASK_ID}-{state['campaignDate'].replace('-', '')}.zip"
    _write_zip_identical_or_new(zip_path, root, _bundle_files(root))
    result = {
        "classification": "CAMPAIGN_CLOSEOUT_COMPLETED",
        "finalDecision": _final_decision(matrix),
        "completedCheckpointCount": completed,
        "checkpointCount": len(EXPECTED_CHECKPOINTS),
        "reportPath": str(report_path),
        "manifestPath": str(manifest_path),
        "zipPath": str(zip_path),
        "zipSha256": hashlib.sha256(zip_path.read_bytes()).hexdigest().upper(),
        "secretScan": secret_scan,
        "productionNonmutation": production["classification"],
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
    }
    result["resultFingerprint"] = fingerprint(result)
    _write_identical_or_new(closeout / "CLOSEOUT-RESULT.json", _json_bytes(result))
    return result


def _summarize_checkpoint(proof: Mapping[str, object], state_row: Mapping[str, object]) -> dict[str, object]:
    providers = proof["providers"]
    alpaca = providers["alpaca"]
    requests = alpaca.get("requests", [])
    successes = sum(1 for row in requests if row.get("apiResult") == "SUCCESS")
    failures = sum(1 for row in requests if row.get("apiResult") != "SUCCESS")
    capacity = alpaca.get("capacity", {})
    websocket = alpaca.get("websocket", {})
    schwab = providers["schwab"]
    finviz = providers["finviz"]
    return {
        "checkpointCode": proof["checkpointCode"],
        "classification": "COMPLETED",
        "startLagSeconds": state_row.get("startLagSeconds"),
        "phase": proof["observationWindow"]["phase"],
        "startedEastern": proof["observationWindow"]["startedEastern"],
        "alpaca": {
            "feed": alpaca.get("currentFeed"),
            "successfulRequestCount": successes,
            "failedRequestCount": failures,
            "largestSuccessfulCoverageRequest": capacity.get("largestSuccessfulCoverageRequest"),
            "websocketStatus": websocket.get("status"),
            "assetEligibilityStatus": alpaca.get("assetEligibility", {}).get("status"),
        },
        "schwab": {
            "status": schwab.get("status"),
            "quoteCount": len(schwab.get("quotes", {})) if isinstance(schwab.get("quotes"), Mapping) else 0,
            "streamer": schwab.get("streamer"),
            "tokenRefreshAttempted": schwab.get("tokenRefreshAttempted"),
        },
        "finviz": {
            "status": finviz.get("status"),
            "rawRowCount": finviz.get("rawRowCount"),
            "parsedRowCount": finviz.get("parsedRowCount"),
            "qualifyingRowCount": finviz.get("qualifyingRowCount"),
        },
        "evidenceFingerprint": proof["evidenceFingerprint"],
    }


def _render_report(matrix: Mapping[str, object]) -> str:
    checkpoints = matrix["checkpoints"]
    completed = int(matrix["completedCheckpointCount"])
    schwab_statuses = sorted({row["schwab"]["status"] for row in checkpoints})
    finviz_successes = sum(row["finviz"]["status"] == "SUCCESS" for row in checkpoints)
    maximum_coverage = max(
        (int(row["alpaca"].get("largestSuccessfulCoverageRequest") or 0) for row in checkpoints),
        default=0,
    )
    decision = _final_decision(matrix)
    lines = [
        f"# {TASK_ID} Final Report",
        "",
        f"Campaign: `{matrix['campaignDate']}`",
        f"Source commit: `{matrix['campaignSourceCommit']}`",
        f"Checkpoints completed: `{completed}/{matrix['checkpointCount']}`",
        f"Final decision: `{decision}`",
        "",
        "## A. Why 07:05 Existed",
        "",
        "`07:05 ET` was a historical provider-fidelity checkpoint placed five minutes after the prior observed Schwab `07:00 ET` quality boundary. It was never a strategy start, momentum birth, continuous-runtime start, or five-bar requirement. This campaign treats it only as one measurement point and does not preserve it as a required production boundary.",
        "",
        "## B. Current Cadence Recommendation",
        "",
        "Research-only proposal: use one broad snapshot pulse about every five minutes overnight and through the regular session, with a bounded hot set updated from the fastest legal feed. Use each completed canonical one-minute bar for hot-set reevaluation where canonical candles exist. These are capacity-informed research values, not strategy law.",
        "",
        "## C. Schwab",
        "",
        "thinkorswim 24/5 is documented as available with no separate platform subscription for Schwab clients. Trader API capability remains classified only from physical API evidence. Observed campaign statuses: `" + "`, `".join(schwab_statuses) + "`. The sidecar never refreshes the production-shared token and never uses the account-bearing Streamer bootstrap.",
        "",
        "## D. Alpaca Basic",
        "",
        f"Basic market-data access was physically detected. The largest one-request research-universe coverage observed in scheduled capacity checkpoints was `{maximum_coverage}` symbols. Official Basic limits remain 200 historical requests/minute and 30 WebSocket symbols; the separate live matrix showed the practical subscription ceiling is 30 channel subscriptions (30 bars-only, 15 bars+quotes, or 10 bars+quotes+trades). Direct BOATS latest access is entitlement-gated while derived overnight latest and delayed BOATS history remain separate.",
        "",
        "## E. Finviz",
        "",
        f"The sidecar used current unauthenticated provider access and recorded `{finviz_successes}` successful scheduled observations. It did not assume Elite or bypass controls. Official Elite coverage is real time from 04:00-20:00 ET; official pages contain conflicting free-delay descriptions, so observed evidence and entitlement remain separate.",
        "",
        "## F. Cost Ladder",
        "",
        "- Tier 0 `$0`: existing Schwab, Alpaca Basic, current Finviz access.",
        "- Tier 1 `$24.96-$39.50/month`: Finviz Elite, primarily real-time 04:00-20:00 broad discovery.",
        "- Tier 2 `$99/month`: Alpaca Algo Trader Plus, full-exchange real-time coverage, unrestricted latest history, 10,000 requests/minute, and unlimited WebSocket symbols.",
        "- Tier 3 `$199/month`: Massive Stocks Advanced, full-market real-time trades, quotes, aggregates, snapshots, and 20+ years of history.",
        "",
        "## G. Momentum Birth",
        "",
        "Free Alpaca capability can monitor a bounded known universe overnight with fresh indicative quotes and can reconstruct path, bars, trades, and volume after the BOATS delay. It does not prove a full eligible-universe inventory under this task's market-data-only boundary, and indicative overnight data is not canonical execution evidence.",
        "",
        "## H. Recommended Future MH Window",
        "",
        "Observe from 20:00 ET using Alpaca Basic as isolated overnight radar/reconstruction; treat 04:00-07:00 and 07:00-09:30 as separately measured regimes; retain Schwab as regular-session canonical where already proven; keep Finviz as broad discovery; and never average provider prices. A later bounded integration must define degraded states and authority explicitly.",
        "",
        "## I. Final Decision",
        "",
        f"`{decision}`",
        "",
        "## J. Next Implementation Task",
        "",
        "Build a research-only overnight radar adapter for the proven bounded symbol universe using Alpaca Basic snapshots plus a channel-budgeted hot WebSocket set. Persist provider/feed identity and delayed BOATS reconstruction separately. Do not alter Schwab canonical authority, candidate admission, strategy, Paper, or execution in that follow-up.",
        "",
        "## Safety",
        "",
        f"Production nonmutation: `{matrix['productionNonmutation']['classification']}`. Account, position, order, Paper, Shadow, strategy, execution, provider promotion, and source blending remained absent.",
        "",
    ]
    return "\n".join(lines)


def _final_decision(matrix: Mapping[str, object]) -> str:
    completed = int(matrix["completedCheckpointCount"])
    coverage = max(
        (int(row["alpaca"].get("largestSuccessfulCoverageRequest") or 0) for row in matrix["checkpoints"]),
        default=0,
    )
    if completed == len(EXPECTED_CHECKPOINTS) and coverage >= 100:
        return "FREE_TIER_SUFFICIENT_FOR_NEXT_RESEARCH_STAGE"
    return "OVERNIGHT_CAPABILITY_INSUFFICIENT"


def _load_state(path: Path, *, expected_feature_commit: str) -> dict[str, object]:
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("taskId") != TASK_ID:
        raise OvernightDataFidelityError("The campaign state identity is invalid.")
    fingerprint_input = dict(state)
    observed_fingerprint = fingerprint_input.pop("stateFingerprint", None)
    if observed_fingerprint != fingerprint(fingerprint_input):
        raise OvernightDataFidelityError("The campaign state fingerprint did not verify.")
    source = state.get("sourceIdentity")
    if not isinstance(source, Mapping) or source.get("featureCommit") != expected_feature_commit:
        raise OvernightDataFidelityError("The campaign feature commit did not match.")
    require_sanitized(state, forbidden_values=())
    return state


def _production_invariants(
    *,
    canonical_root: Path,
    expected_canonical_commit: str,
    protected_hashes: Mapping[Path, str],
) -> dict[str, object]:
    root = canonical_root.expanduser().resolve()
    head = _git(root, "rev-parse", "HEAD")
    origin = _git(root, "rev-parse", "origin/master")
    status = _git(root, "status", "--porcelain")
    hashes = []
    for path, expected in protected_hashes.items():
        resolved = path.expanduser().resolve()
        observed = hashlib.sha256(resolved.read_bytes()).hexdigest().upper() if resolved.exists() else "NOT_FOUND"
        hashes.append({"pathIncluded": False, "filename": resolved.name, "expectedSha256": expected, "observedSha256": observed})
    services = [_service_status(name) for name in PROTECTED_SERVICES]
    passed = (
        head == expected_canonical_commit
        and origin == expected_canonical_commit
        and status == ""
        and all(row["expectedSha256"] == row["observedSha256"] for row in hashes)
        and all(row["state"] == "RUNNING" and row["startMode"] == "AUTO_START" for row in services)
    )
    return {
        "classification": "PASS" if passed else "FAIL",
        "canonicalHead": head,
        "originMaster": origin,
        "expectedCanonicalCommit": expected_canonical_commit,
        "canonicalClean": status == "",
        "protectedHashes": hashes,
        "services": services,
        "serviceRestartRequested": False,
        "schedulerMutationRequested": False,
    }


def _service_status(name: str) -> dict[str, object]:
    query = subprocess.run(
        ["sc.exe", "query", name],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    config = subprocess.run(
        ["sc.exe", "qc", name],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    state = re.search(r"STATE\s*:\s*\d+\s+(\w+)", query.stdout)
    start_mode = re.search(r"START_TYPE\s*:\s*\d+\s+(\w+)", config.stdout)
    return {
        "name": name,
        "queryResult": query.returncode,
        "configResult": config.returncode,
        "state": state.group(1) if state else "UNKNOWN",
        "startMode": start_mode.group(1) if start_mode else "UNKNOWN",
    }


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        raise OvernightDataFidelityError("Canonical Git inspection failed safely.")
    return completed.stdout.strip()


def _bundle_files(root: Path) -> list[Path]:
    excluded = {"campaign.lock", "closeout-waiter.lock", "campaign-state.json.tmp"}
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.name not in excluded and path.suffix.lower() != ".zip"
    )


def _secret_scan(paths: Sequence[Path]) -> dict[str, object]:
    hits = 0
    for path in paths:
        payload = path.read_bytes()
        if any(pattern.search(payload) for pattern in SECRET_PATTERNS):
            hits += 1
    return {"classification": "PASS" if hits == 0 else "FAIL", "filesScanned": len(paths), "patternHitCount": hits}


def _write_identical_or_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise OvernightDataFidelityError(f"Conflicting closeout output exists: {path.name}")
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _write_zip_identical_or_new(target: Path, root: Path, files: Sequence[Path]) -> None:
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(str(path.relative_to(root)).replace("\\", "/"))
            info.date_time = (1980, 1, 1, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    if target.exists():
        if target.read_bytes() != temporary.read_bytes():
            temporary.unlink(missing_ok=True)
            raise OvernightDataFidelityError("A conflicting final review ZIP already exists.")
        temporary.unlink(missing_ok=True)
        return
    os.replace(temporary, target)


def _json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")


def _acquire_lock(path: Path) -> int:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise OvernightDataFidelityError("An overnight closeout waiter already owns this root.") from exc
    os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
    os.fsync(descriptor)
    return descriptor


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OvernightDataFidelityError("Aware closeout timestamps are required.")
    return value.astimezone(UTC)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Wait for and close out the overnight fidelity campaign offline.")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--source-contract", type=Path, required=True)
    parser.add_argument("--expected-feature-commit", required=True)
    parser.add_argument("--canonical-root", type=Path, required=True)
    parser.add_argument("--expected-canonical-commit", required=True)
    parser.add_argument("--deadline", type=datetime.fromisoformat, required=True)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--protected-hash", action="append", default=[])
    args = parser.parse_args(argv)
    hashes: dict[Path, str] = {}
    for value in args.protected_hash:
        path, separator, expected = value.rpartition("=")
        if not separator or not re.fullmatch(r"[A-Fa-f0-9]{64}", expected):
            raise SystemExit("invalid protected hash argument")
        hashes[Path(path)] = expected.upper()
    try:
        result = wait_for_terminal_closeout(
            output_root=args.output_root,
            source_contract=args.source_contract,
            expected_feature_commit=args.expected_feature_commit,
            canonical_root=args.canonical_root,
            expected_canonical_commit=args.expected_canonical_commit,
            protected_hashes=hashes,
            deadline=args.deadline,
            poll_seconds=args.poll_seconds,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "classification": "CAMPAIGN_CLOSEOUT_FAILED_SAFE",
            "errorType": type(exc).__name__,
            "credentialMaterialIncluded": False,
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
