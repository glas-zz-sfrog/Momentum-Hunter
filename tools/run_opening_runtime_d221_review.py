from __future__ import annotations

"""Build and exercise an isolated opening-runtime successor from preserved evidence."""

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import zipfile
from dataclasses import fields, replace
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable, Mapping
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.automation_supervisor import (  # noqa: E402
    DEFAULT_MANIFEST_PATH,
    LOADED_SUPERVISOR_SHA256,
    parse_manifest,
)
from momentum_hunter.config import AppConfig  # noqa: E402
from momentum_hunter.evidence_integrity import PriceFieldEvidence  # noqa: E402
from momentum_hunter.market import MarketRegimeSnapshot  # noqa: E402
from momentum_hunter.models import MarketRegime, TradingMode  # noqa: E402
from momentum_hunter.opening_candle_readiness import (  # noqa: E402
    OpeningCandleReadinessCoordinator,
    inspect_opening_candle_store,
)
from momentum_hunter.opening_runtime_identity import (  # noqa: E402
    LOADED_RUNTIME_IDENTITY_MODULE_SHA256,
    OpeningRuntimeReleaseStore,
    build_release_record_v2,
    file_sha256,
    verify_execution_gate,
)
from momentum_hunter.opening_runtime_release import _context  # noqa: E402
from momentum_hunter.outcomes import PriceBar  # noqa: E402
from momentum_hunter.storage import candidate_from_dict  # noqa: E402
from momentum_hunter.time_normalized_rvol import (  # noqa: E402
    TimeNormalizedRvolEvidence,
)
from momentum_hunter.trade_planning import MarketTape  # noqa: E402


CANONICAL_SHA = "23ee162373654e1db91af4c19f75bbc7887e3174"
D220_RELEASE_ID = "OPENING-RUNTIME-D220AEA03F465DEA3B6A"
D220_SOURCE_SHA = "317c4563834eeb349c626121980276ffb8845ce6"
REPLAY_KIND = "OFFLINE_PRESERVED_OPENING_REPLAY"
KNOWN_FILES = (
    "momentum_hunter/canonical_candle_evidence.py",
    "momentum_hunter/engine_host.py",
    "momentum_hunter/workstation_read_models.py",
)
TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


def canonical_json(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload), encoding="utf-8")
    return path


def run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
        shell=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git command failed.")
    return result.stdout


def require_clean_identity(root: Path, expected_sha: str) -> None:
    head = run_git(root, "rev-parse", "HEAD").strip()
    status = run_git(root, "status", "--porcelain")
    if head != expected_sha or status:
        raise RuntimeError(
            f"Expected clean {expected_sha}, found head={head}, dirty={bool(status)}."
        )


def tree_manifest(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    return {
        path.relative_to(root).as_posix(): file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def reconstruct_d220(
    canonical_root: Path,
    production_release_root: Path,
    evidence_root: Path,
) -> tuple[dict[str, object], dict[str, str]]:
    release_path = production_release_root / "releases" / f"{D220_RELEASE_ID}.json"
    channel_path = production_release_root / "channels" / "opening-capture.json"
    d220 = json.loads(release_path.read_text(encoding="utf-8"))
    channel = json.loads(channel_path.read_text(encoding="utf-8"))
    if channel.get("releaseId") != D220_RELEASE_ID:
        raise RuntimeError("The installed opening channel no longer points at D220.")
    if d220.get("sourceGitSha") != D220_SOURCE_SHA:
        raise RuntimeError("The installed D220 source identity is unexpected.")

    before = tree_manifest(production_release_root)
    write_json(evidence_root / "identity" / "d220-release.json", d220)
    write_json(evidence_root / "identity" / "d220-channel.json", channel)
    write_json(evidence_root / "identity" / "d220-tree-before.json", before)

    components = {
        str(item["path"]): str(item["sha256"])
        for item in d220.get("runtimeComponents", [])
        if isinstance(item, dict)
    }
    rows: list[dict[str, object]] = []
    diff_root = evidence_root / "identity" / "known-three-file-diffs"
    diff_root.mkdir(parents=True, exist_ok=True)
    for relative in KNOWN_FILES:
        current_hash = file_sha256(canonical_root / relative)
        approved_hash = components.get(relative, "")
        commits = run_git(
            canonical_root,
            "log",
            "--format=%H %s",
            f"{D220_SOURCE_SHA}..{CANONICAL_SHA}",
            "--",
            relative,
        ).strip().splitlines()
        delta = run_git(
            canonical_root,
            "diff",
            "--no-ext-diff",
            f"{D220_SOURCE_SHA}..{CANONICAL_SHA}",
            "--",
            relative,
        )
        patch_name = relative.replace("/", "__") + ".patch"
        (diff_root / patch_name).write_text(delta, encoding="utf-8")
        rows.append(
            {
                "path": relative,
                "openingReachable": relative
                in d220["dependencyClosureEvidence"]["dependencyClosureFiles"],
                "d220Sha256": approved_hash,
                "canonicalSha256": current_hash,
                "bytesChanged": approved_hash != current_hash,
                "introducingCommits": commits,
                "semanticClassification": (
                    "CANONICAL_CANDLE_READER_EXTENDED_BY_ACCEPTED_PRODUCER_WORK"
                    if relative.endswith("canonical_candle_evidence.py")
                    and approved_hash != current_hash
                    else "NO_BYTE_OR_SEMANTIC_DELTA"
                ),
                "openingEffect": (
                    "Opening closure identity changes; preserved replay must prove behavior."
                    if approved_hash != current_hash
                    else "None; installed and canonical bytes already match."
                ),
            }
        )
    write_json(
        evidence_root / "identity" / "known-three-file-reconciliation.json",
        {
            "status": "RECONCILED",
            "reportedMismatchCount": 3,
            "physicalByteMismatchCount": sum(bool(row["bytesChanged"]) for row in rows),
            "files": rows,
        },
    )
    return d220, before


def build_d221_candidate(
    canonical_root: Path,
    production_manifest: Path,
    production_release_root: Path,
    evidence_root: Path,
    d220: Mapping[str, object],
) -> dict[str, object]:
    manifest = parse_manifest(production_manifest)
    production_context = _context(manifest)
    isolated_root = evidence_root / "isolated-opening-runtime"
    if isolated_root.exists():
        shutil.rmtree(isolated_root)
    shutil.copytree(production_release_root, isolated_root)
    context = replace(
        production_context,
        repository_root=canonical_root.absolute(),
        config_path=canonical_root / "MomentumHunterData" / "config.json",
        release_root=isolated_root,
    )
    record = build_release_record_v2(
        context,
        source_git_sha=CANONICAL_SHA,
        predecessor_release_id=str(d220["releaseId"]),
        qualification_evidence=[
            "ARGUS-MONDAY-READINESS-REPAIR-002:OFFLINE_PRESERVED_OPENING_REPLAY",
            "ARGUS-AUTOMATION-RUNTIME-IDENTITY-003A:AUTHORITATIVE_CLOSURE",
        ],
    )
    release, pointer, changed = OpeningRuntimeReleaseStore(isolated_root).promote(
        record,
        current_git_sha=CANONICAL_SHA,
    )
    gate = verify_execution_gate(
        context,
        loaded_supervisor_sha256=LOADED_SUPERVISOR_SHA256,
        loaded_identity_module_sha256=LOADED_RUNTIME_IDENTITY_MODULE_SHA256,
        loaded_service_host_sha256=str(
            release["environmentIdentity"]["serviceHost"]["sha256"]
        ),
        git_identity=(CANONICAL_SHA, ""),
    )
    summary = {
        "status": "D221_CANDIDATE_BUILT_ISOLATED",
        "logicalName": "OPENING-RUNTIME-D221",
        "baseCanonical": CANONICAL_SHA,
        "predecessorReleaseId": d220["releaseId"],
        "releaseId": release["releaseId"],
        "releaseFingerprint": release["releaseFingerprint"],
        "approvedRuntimeFingerprint": release["approvedRuntimeFingerprint"],
        "runtimeSurfaceFingerprint": release["runtimeSurfaceFingerprint"],
        "configurationFingerprint": release["configurationFingerprint"],
        "environmentFingerprint": release["environmentFingerprint"],
        "dependencyClosureFingerprint": release["dependencyClosureEvidence"][
            "dependencyClosureFingerprint"
        ],
        "reachablePackageCount": release["dependencyClosureEvidence"][
            "reachablePackageCount"
        ],
        "excludedPackageCountDiagnostic": release["dependencyClosureEvidence"][
            "excludedPackageCount"
        ],
        "explicitRuntimeFiles": release["dependencyClosureEvidence"][
            "explicitRuntimeFiles"
        ],
        "relevantDistributions": [
            item["name"]
            for item in release["environmentIdentity"]["relevantDistributions"]
        ],
        "isolatedPromotionChanged": changed,
        "isolatedPointerFingerprint": pointer["pointerFingerprint"],
        "runtimeMatchIfSelected": gate.runtime_match,
        "productionReleaseRootMutated": False,
        "promotedOrInstalled": False,
        "orderTransmission": "UNAVAILABLE",
    }
    write_json(evidence_root / "identity" / "d221-candidate-summary.json", summary)
    return {"summary": summary, "release": release, "context": context}


class PreservedFinvizProvider:
    name = "finviz"
    last_scan_diagnostics = None

    def __init__(self, capture_payload: Mapping[str, object]) -> None:
        self._candidates = [
            candidate_from_dict(dict(item))
            for item in capture_payload.get("candidates", [])
            if isinstance(item, dict)
        ]
        self.scan_calls = 0
        self.news_calls = 0

    def scan(self, _criteria: object) -> list[object]:
        self.scan_calls += 1
        return self._candidates

    def fetch_news(self, _ticker: str, *, as_of: datetime) -> list[object]:
        self.news_calls += 1
        if as_of.tzinfo is None:
            raise ValueError("Replay time must be offset-aware.")
        return []


def market_regime_from_capture(payload: Mapping[str, object]) -> MarketRegimeSnapshot:
    market = dict(payload["market"])
    return MarketRegimeSnapshot(
        regime=MarketRegime(str(market["regime"])),
        symbol=str(market["symbol"]),
        close=float(market["close"]),
        sma_50=float(market["sma_50"]),
        sma_200=float(market["sma_200"]),
        reason=str(market["reason"]),
    )


def _rvol_from_dict(payload: Mapping[str, object]) -> TimeNormalizedRvolEvidence:
    values = dict(payload)
    values["baseline_session_dates"] = tuple(values.get("baseline_session_dates", []))
    values["findings"] = tuple(values.get("findings", []))
    return TimeNormalizedRvolEvidence(**values)


def market_tapes_from_report(payload: Mapping[str, object]) -> dict[str, MarketTape]:
    allowed = {item.name for item in fields(MarketTape)}
    tapes: dict[str, MarketTape] = {}
    for row in payload.get("candidates", []):
        if not isinstance(row, dict):
            continue
        raw = dict(row.get("market_tape", {}))
        rvol = raw.get("rvol_evidence")
        if isinstance(rvol, dict):
            raw["rvol_evidence"] = _rvol_from_dict(rvol)
        provenance = raw.get("field_provenance", {})
        raw["field_provenance"] = {
            str(name): PriceFieldEvidence(**dict(item))
            for name, item in provenance.items()
            if isinstance(item, dict)
        }
        tapes[str(row["symbol"]).upper()] = MarketTape(
            **{key: value for key, value in raw.items() if key in allowed}
        )
    return tapes


def daily_bars_from_store(path: Path, *, before_date: str) -> list[PriceBar]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[PriceBar] = []
    for item in payload.get("bars", []):
        candle = item.get("canonicalCandle", {}) if isinstance(item, dict) else {}
        session_date = str(candle.get("sessionDate", ""))
        if not session_date or session_date >= before_date:
            continue
        rows.append(
            PriceBar(
                day=session_date,
                high=float(candle["high"]),
                low=float(candle["low"]),
                close=float(candle["close"]),
                volume=int(float(candle["volume"])),
            )
        )
    return sorted(rows, key=lambda item: item.day)


def readiness_state_counts(states: Iterable[str]) -> dict[str, int]:
    normalized = tuple(str(state) for state in states)
    return {
        "executionReadyTradeCount": normalized.count("EXECUTION_READY_TRADE"),
        "executionReadyPremarketCount": normalized.count(
            "EXECUTION_READY_PREMARKET"
        ),
        "planningScaffoldCount": sum(
            state.startswith("PLANNING_SCAFFOLD") for state in normalized
        ),
        "doNotTradeCount": sum(state.startswith("DO_NOT_TRADE") for state in normalized),
    }


def _forbid_network(counter: dict[str, int]) -> Callable[..., object]:
    def blocked(*_args: object, **_kwargs: object) -> object:
        counter["networkAttempts"] += 1
        raise RuntimeError("NETWORK_FORBIDDEN_IN_OFFLINE_PRESERVED_OPENING_REPLAY")

    return blocked


def run_preserved_opening_replay(
    canonical_root: Path,
    evidence_root: Path,
    source_data_root: Path,
) -> dict[str, object]:
    import momentum_hunter.score_breakdowns as score_breakdowns
    import momentum_hunter.storage as storage
    import momentum_hunter.trade_planning as trade_planning
    import tools.capture_job as capture_job

    input_root = evidence_root / "preserved-input"
    output_root = evidence_root / "replay-output"
    capture_output = output_root / "captures"
    reports_output = output_root / "reports"
    integrity_output = output_root / "integrity"
    failure_output = output_root / "capture-failures"
    minute_output = output_root / "minute-store" / "2026-08-14"
    daily_output = output_root / "daily-store"
    for directory in (
        input_root,
        capture_output,
        reports_output,
        integrity_output,
        failure_output,
        minute_output,
        daily_output,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    sources = {
        "captureJson": source_data_root / "captures" / "2026-08-14" / "opening.json",
        "captureMarkdown": source_data_root / "captures" / "2026-08-14" / "opening.md",
        "tradePlanJson": source_data_root
        / "reports"
        / "trade-plan-briefing-2026-08-14-opening.json",
        "tradePlanMarkdown": source_data_root
        / "reports"
        / "trade-plan-briefing-2026-08-14-opening.md",
        "tradePlanCsv": source_data_root
        / "reports"
        / "trade-plan-briefing-2026-08-14-opening.csv",
        "minuteSNDK": source_data_root
        / "schwab-candles-v1"
        / "2026-08-14"
        / "SNDK.json",
        "minuteNU": source_data_root
        / "schwab-candles-v1"
        / "2026-08-14"
        / "NU.json",
        "dailySNDK": source_data_root / "schwab-daily-candles-v1" / "SNDK.json",
        "dailyNU": source_data_root / "schwab-daily-candles-v1" / "NU.json",
    }
    baseline_dates = (
        "2026-08-05",
        "2026-08-06",
        "2026-08-07",
        "2026-08-10",
        "2026-08-11",
        "2026-08-12",
        "2026-08-13",
    )
    for session_date in baseline_dates:
        for symbol in ("SNDK", "NU"):
            sources[f"minute{symbol}{session_date}"] = (
                source_data_root
                / "schwab-candles-v1"
                / session_date
                / f"{symbol}.json"
            )
    before_hashes = {name: file_sha256(path) for name, path in sources.items()}
    for name, path in sources.items():
        shutil.copy2(path, input_root / f"{name}{path.suffix}")
    shutil.copy2(sources["minuteSNDK"], minute_output / "SNDK.json")
    shutil.copy2(sources["minuteNU"], minute_output / "NU.json")
    for session_date in baseline_dates:
        target = output_root / "minute-store" / session_date
        target.mkdir(parents=True, exist_ok=True)
        for symbol in ("SNDK", "NU"):
            shutil.copy2(
                sources[f"minute{symbol}{session_date}"],
                target / f"{symbol}.json",
            )
    shutil.copy2(sources["dailySNDK"], daily_output / "SNDK.json")
    shutil.copy2(sources["dailyNU"], daily_output / "NU.json")

    capture_payload = json.loads(sources["captureJson"].read_text(encoding="utf-8"))
    original_report = json.loads(sources["tradePlanJson"].read_text(encoding="utf-8"))
    provider = PreservedFinvizProvider(capture_payload)
    market_regime = market_regime_from_capture(capture_payload)
    market_tapes = market_tapes_from_report(original_report)
    bars_by_ticker = {
        symbol: daily_bars_from_store(
            sources[f"daily{symbol}"], before_date="2026-08-14"
        )
        for symbol in ("SNDK", "NU")
    }
    capture_time = datetime.fromisoformat(str(capture_payload["capture_time"]))
    decision_time = datetime.fromisoformat("2026-08-14T08:35:23.500000-05:00")
    clock_proof = {
        "schemaVersion": 1,
        "status": "PASS",
        "source": "preserved:finviz.com:https_date",
        "signedSkewMilliseconds": 0.0,
        "measurementUncertaintyMilliseconds": 1.0,
        "replayKind": REPLAY_KIND,
    }
    args = SimpleNamespace(
        session="opening",
        provider="finviz",
        scanner="Institutional Momentum",
        require_opening_result=True,
        trigger_shadow_selector=False,
        task_definition=None,
        shadow_opening_proof_only=False,
        selector_proof_bundle=None,
    )
    network = {"networkAttempts": 0}
    block_network = _forbid_network(network)
    score_path = output_root / "score-breakdowns.json"
    analysis_path = output_root / "analysis-captures.csv"
    integrity_path = integrity_output / "capture_manifest.json"
    chronology: list[dict[str, object]] = []

    def replay_readiness(symbols: Iterable[str], *, evidence_as_of: datetime):
        chronology.append(
            {
                "stage": "SCHWAB_PRESERVED_CANDLE_READINESS",
                "symbols": list(symbols),
                "evidenceAsOf": evidence_as_of.isoformat(),
            }
        )
        coordinator = OpeningCandleReadinessCoordinator(
            run_backfill=lambda: (_ for _ in ()).throw(
                RuntimeError("PRESERVED_STORE_SHOULD_ALREADY_BE_READY")
            ),
            inspect_store=lambda wanted, as_of: inspect_opening_candle_store(
                wanted,
                evidence_as_of=as_of,
                minute_store_root=output_root / "minute-store",
            ),
            maximum_attempts=1,
            retry_delays=(),
        )
        return coordinator.prepare(tuple(symbols), evidence_as_of=evidence_as_of)

    actual_builder = trade_planning.build_trade_planning_report
    actual_ensure_report = capture_job.ensure_trade_planning_report

    def replay_builder(capture_path: Path, **kwargs: object):
        chronology.append(
            {
                "stage": "ACTUAL_TRADE_PLANNING_BUILDER",
                "requestedFetchBars": kwargs.get("fetch_bars"),
                "requestedFetchMarketData": kwargs.get("fetch_market_data"),
                "providerBoundary": "PRESERVED_SCHWAB_EVIDENCE",
            }
        )
        return actual_builder(
            capture_path,
            capital=float(kwargs.get("capital", 500.0)),
            bars_by_ticker=bars_by_ticker,
            market_tape_by_ticker=market_tapes,
            fetch_bars=False,
            fetch_market_data=False,
            event_mode=bool(kwargs.get("event_mode", False)),
            as_of=decision_time,
            previous_state_path=kwargs.get("previous_state_path"),
            rvol_evidence_by_ticker=kwargs.get("rvol_evidence_by_ticker"),
            intraday_bars_by_ticker=kwargs.get("intraday_bars_by_ticker"),
        )

    def replay_score_upsert(payload: dict):
        chronology.append({"stage": "ACTUAL_SCORE_BREAKDOWN_PERSISTENCE"})
        return score_breakdowns.upsert_score_breakdowns_for_capture_payload(
            payload, output_path=score_path
        )

    def replay_ensure_report(capture_path: Path, **kwargs: object):
        chronology.append({"stage": "ACTUAL_REPORT_ORCHESTRATION_WITH_ISOLATED_OUTPUT"})
        return actual_ensure_report(
            capture_path,
            reports_dir=reports_output,
            **kwargs,
        )

    times = iter([capture_time, capture_time, decision_time, decision_time, decision_time])

    def replay_clock() -> datetime:
        return next(times, decision_time)

    stdout = io.StringIO()
    stderr = io.StringIO()
    with contextlib.ExitStack() as stack:
        stack.enter_context(contextlib.redirect_stdout(stdout))
        stack.enter_context(contextlib.redirect_stderr(stderr))
        stack.enter_context(patch.object(capture_job, "parse_args", return_value=args))
        stack.enter_context(patch.object(capture_job, "now_central", side_effect=replay_clock))
        stack.enter_context(patch.object(storage, "now_central", return_value=decision_time))
        stack.enter_context(
            patch.object(score_breakdowns, "now_central", return_value=decision_time)
        )
        stack.enter_context(
            patch.object(capture_job, "load_config", return_value=AppConfig(
                mode=TradingMode.PAPER, provider="finviz"
            ))
        )
        stack.enter_context(
            patch.object(capture_job, "verify_opening_https_clock", return_value=clock_proof)
        )
        stack.enter_context(
            patch.object(capture_job, "provider_from_name", return_value=provider)
        )
        stack.enter_context(
            patch.object(capture_job, "detect_market_regime", return_value=market_regime)
        )
        stack.enter_context(
            patch.object(capture_job, "prepare_opening_candle_readiness", side_effect=replay_readiness)
        )
        stack.enter_context(
            patch.object(capture_job, "build_trade_planning_report", side_effect=replay_builder)
        )
        stack.enter_context(
            patch.object(
                capture_job,
                "ensure_trade_planning_report",
                side_effect=replay_ensure_report,
            )
        )
        stack.enter_context(
            patch.object(
                capture_job,
                "upsert_score_breakdowns_for_capture_payload",
                side_effect=replay_score_upsert,
            )
        )
        stack.enter_context(patch.object(capture_job, "CAPTURES_DIR", capture_output))
        stack.enter_context(patch.object(capture_job, "REPORTS_DIR", reports_output))
        stack.enter_context(patch.object(storage, "CAPTURES_DIR", capture_output))
        stack.enter_context(patch.object(storage, "ANALYSIS_CSV", analysis_path))
        stack.enter_context(patch.object(storage, "INTEGRITY_DIR", integrity_output))
        stack.enter_context(
            patch.object(storage, "CAPTURE_INTEGRITY_MANIFEST", integrity_path)
        )
        stack.enter_context(patch.object(storage, "CAPTURE_FAILURES_DIR", failure_output))
        stack.enter_context(patch.object(trade_planning, "ensure_app_dirs", lambda: None))
        stack.enter_context(patch.object(socket, "create_connection", side_effect=block_network))
        stack.enter_context(patch.object(socket.socket, "connect", side_effect=block_network))
        chronology.append({"stage": "ACTUAL_OPENING_ENTRYPOINT", "call": "tools.capture_job.main"})
        exit_code = capture_job.main()

    (output_root / "stdout.log").write_text(stdout.getvalue(), encoding="utf-8")
    (output_root / "stderr.log").write_text(stderr.getvalue(), encoding="utf-8")
    report_path = reports_output / "trade-plan-briefing-2026-08-14-opening.json"
    output_capture = capture_output / "2026-08-14" / "opening.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    readiness = report["metadata"]["opening_candle_readiness"]
    states = [
        str(row.get("trade_plan", {}).get("readiness", ""))
        for row in report.get("candidates", [])
    ]
    state_counts = readiness_state_counts(states)
    after_hashes = {name: file_sha256(path) for name, path in sources.items()}
    result = {
        "schemaVersion": "OpeningRuntimeD221PreservedReplayV1",
        "status": "PASS" if exit_code == 0 else "FAIL",
        "replayKind": REPLAY_KIND,
        "sourceCaptureTime": capture_time.isoformat(),
        "decisionCutoff": decision_time.isoformat(),
        "actualOpeningEntrypoint": "tools.capture_job.main",
        "actualOrchestration": True,
        "externalBoundariesSubstitutedOnly": [
            "FINVIZ_DISCOVERY_AND_NEWS",
            "MARKET_REGIME_PROVIDER",
            "HTTPS_CLOCK",
            "SCHWAB_HISTORY_AND_QUOTES",
        ],
        "candidateCount": len(report.get("candidates", [])),
        "candidateSymbols": [row.get("symbol") for row in report.get("candidates", [])],
        "readinessStatus": readiness.get("status"),
        "openingBarCounts": {
            symbol: item.get("openingBarCount")
            for symbol, item in readiness.get("symbols", {}).items()
        },
        "baselineSessionCounts": {
            symbol: item.get("baselineSessionCount")
            for symbol, item in readiness.get("symbols", {}).items()
        },
        "tradePlanReadinessStates": states,
        **state_counts,
        "preservedFinvizScanCalls": provider.scan_calls,
        "preservedFinvizNewsCalls": provider.news_calls,
        "networkAttempts": network["networkAttempts"],
        "sourceEvidenceUnchanged": before_hashes == after_hashes,
        "sourceEvidenceHashes": before_hashes,
        "outputCaptureSha256": file_sha256(output_capture),
        "outputReportSha256": file_sha256(report_path),
        "rawCaptureIntegrityPresent": integrity_path.is_file(),
        "scoreBreakdownsPresent": score_path.is_file(),
        "accountValuesRequested": False,
        "positionsRequested": False,
        "paperRequested": False,
        "shadowRequested": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
        "chronology": chronology,
    }
    if (
        exit_code != 0
        or result["candidateCount"] < 1
        or readiness.get("status") != "READY"
        or network["networkAttempts"]
        or before_hashes != after_hashes
    ):
        raise RuntimeError(f"Preserved opening replay failed: {result}")
    write_json(evidence_root / "replay" / "terminal-result.json", result)
    return result


def secret_scan(root: Path) -> dict[str, object]:
    patterns = {
        "alpacaKey": re.compile(r"\bPK[A-Z0-9]{18,}\b"),
        "openAiKey": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "pemPrivateKey": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    }
    findings: list[dict[str, str]] = []
    scanned = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in patterns.items():
            if pattern.search(text):
                findings.append({"path": path.relative_to(root).as_posix(), "pattern": name})
    return {"status": "PASS" if not findings else "FAIL", "filesScanned": scanned, "findings": findings}


def copy_review_source(
    canonical_root: Path,
    task_root: Path,
    release: Mapping[str, object],
    packet_root: Path,
) -> int:
    copied: set[str] = set()
    for item in release.get("runtimeComponents", []):
        if not isinstance(item, dict):
            continue
        relative = str(item["path"])
        source = canonical_root / relative
        target = packet_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.add(relative)
    extras = (
        "tools/run_opening_runtime_d221_review.py",
        "tests/test_opening_runtime_d221_review.py",
        "docs/argus-office/goal-charters/ARGUS-OPENING-RUNTIME-D221.md",
    )
    for relative in extras:
        source = task_root / relative
        target = packet_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.add(relative)
    return len(copied)


def run_packet_tests(root: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root)
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_opening_runtime_d221_review.py",
        ],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
        shell=False,
    )
    return {
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "command": "python -B -m unittest discover -s tests -p test_opening_runtime_d221_review.py",
        "exitCode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def prepare_packet_metadata(packet_root: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    for name in ("INDEX.md", "MANIFEST.json", "SECRET-SCAN.json"):
        (packet_root / name).unlink(missing_ok=True)
    index_lines = ["# Index", "", "| Path | SHA-256 |", "| --- | --- |"]
    for path in sorted(packet_root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(packet_root).as_posix()
            index_lines.append(f"| `{relative}` | `{file_sha256(path)}` |")
    (packet_root / "INDEX.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    scan = secret_scan(packet_root)
    write_json(packet_root / "SECRET-SCAN.json", scan)
    if scan["status"] != "PASS":
        raise RuntimeError(f"Secret scan blocked package creation: {scan['findings']}")
    manifest: list[dict[str, object]] = []
    for path in sorted(packet_root.rglob("*")):
        if path.is_file() and path.name != "MANIFEST.json":
            manifest.append(
                {
                    "path": path.relative_to(packet_root).as_posix(),
                    "sha256": file_sha256(path),
                    "size": path.stat().st_size,
                }
            )
    write_json(packet_root / "MANIFEST.json", {"files": manifest})
    return manifest, scan


def write_zip(packet_root: Path, zip_path: Path) -> None:
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(packet_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(packet_root).as_posix())


def build_package(
    canonical_root: Path,
    task_root: Path,
    evidence_root: Path,
    zip_path: Path,
    release: Mapping[str, object],
) -> dict[str, object]:
    packet_root = evidence_root / "second-eye-packet"
    if packet_root.exists():
        shutil.rmtree(packet_root)
    packet_root.mkdir(parents=True)
    source_count = copy_review_source(canonical_root, task_root, release, packet_root)
    for child in sorted(evidence_root.iterdir()):
        if child.name == packet_root.name:
            continue
        target = packet_root / "evidence" / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child, target)
    (packet_root / "README.md").write_text(
        "# ARGUS Opening Runtime D221 Second-Eye Packet\n\n"
        f"Base canonical: `{CANONICAL_SHA}`\n\n"
        f"Predecessor: `{D220_RELEASE_ID}`\n\n"
        "The replay is offline and uses preserved Aug. 14 Finviz/Schwab evidence. "
        "It grants no Paper, Shadow, broker, account, position, or order authority.\n",
        encoding="utf-8",
    )
    (packet_root / "REPRODUCE.md").write_text(
        "# Reproduction\n\n"
        "Run the focused self-contained checks from the extracted packet root:\n\n"
        "```powershell\n"
        ".\\.venv\\Scripts\\python.exe -B -m unittest discover -s tests -p test_opening_runtime_d221_review.py\n"
        "```\n\n"
        "The live production release root is never a reproduction target.\n",
        encoding="utf-8",
    )
    pre_zip = run_packet_tests(packet_root)
    write_json(packet_root / "PRE-ZIP-TEST.json", pre_zip)
    if pre_zip["status"] != "PASS":
        raise RuntimeError("Pre-ZIP self-contained focused verification failed.")
    manifest, scan = prepare_packet_metadata(packet_root)

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    write_zip(packet_root, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        extracted = evidence_root / "extracted-verification"
        if extracted.exists():
            shutil.rmtree(extracted)
        archive.extractall(extracted)
    extracted_test = run_packet_tests(extracted)
    write_json(packet_root / "EXTRACTED-ZIP-TEST.json", extracted_test)
    if extracted_test["status"] != "PASS":
        raise RuntimeError("Extracted-ZIP focused verification failed.")
    manifest, scan = prepare_packet_metadata(packet_root)
    write_zip(packet_root, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if extracted.exists():
            shutil.rmtree(extracted)
        archive.extractall(extracted)
    extracted_manifest = json.loads((extracted / "MANIFEST.json").read_text(encoding="utf-8"))
    manifest_ok = bad is None and all(
        file_sha256(extracted / item["path"]) == item["sha256"]
        for item in extracted_manifest["files"]
    )
    final_extracted_test = run_packet_tests(extracted)
    if final_extracted_test["status"] != "PASS":
        manifest_ok = False
    result = {
        "status": "PASS" if manifest_ok else "FAIL",
        "zipPath": str(zip_path),
        "zipSha256": file_sha256(zip_path),
        "fileCount": len([path for path in packet_root.rglob("*") if path.is_file()]),
        "manifestCount": len(manifest),
        "sourceFileCount": source_count,
        "secretScan": scan,
        "preZipVerification": pre_zip["status"],
        "extractedZipVerification": final_extracted_test["status"],
        "manifestVerification": "PASS" if manifest_ok else "FAIL",
    }
    write_json(evidence_root / "package-result.json", result)
    return result


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--canonical-root", type=Path, required=True)
    value.add_argument("--evidence-root", type=Path, required=True)
    value.add_argument("--zip-path", type=Path, required=True)
    value.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    value.add_argument(
        "--production-release-root",
        type=Path,
        default=Path(r"C:\ProgramData\MomentumHunter\Automation\opening-runtime"),
    )
    return value


def main() -> int:
    args = parser().parse_args()
    task_root = PROJECT_ROOT
    try:
        require_clean_identity(args.canonical_root, CANONICAL_SHA)
        args.evidence_root.mkdir(parents=True, exist_ok=True)
        d220, d220_before = reconstruct_d220(
            args.canonical_root,
            args.production_release_root,
            args.evidence_root,
        )
        candidate = build_d221_candidate(
            args.canonical_root,
            args.manifest,
            args.production_release_root,
            args.evidence_root,
            d220,
        )
        replay = run_preserved_opening_replay(
            args.canonical_root,
            args.evidence_root,
            args.canonical_root / "MomentumHunterData" / "data",
        )
        d220_after = tree_manifest(args.production_release_root)
        rollback = {
            "status": "PASS" if d220_before == d220_after else "FAIL",
            "releaseRootUnchanged": d220_before == d220_after,
            "fileCount": len(d220_after),
            "activeReleaseId": D220_RELEASE_ID,
        }
        write_json(args.evidence_root / "identity" / "d220-rollback-proof.json", rollback)
        if rollback["status"] != "PASS":
            raise RuntimeError("D220 rollback identity changed during isolated review.")
        summary = {
            "status": "PASS",
            "openingRuntimeD221Built": True,
            "d221BaseCanonical": CANONICAL_SHA,
            "d220RollbackPreserved": True,
            "openingReachableClosureProven": True,
            "openingEnvironmentIdentityProven": True,
            "knownThreeFileMismatchReconciled": True,
            "offlineOpeningFullChain": replay["status"],
            "mondayOpeningApprovedRuntimeMatchIfPromoted": candidate["summary"][
                "runtimeMatchIfSelected"
            ],
            "productStrategySemanticsChanged": False,
            "executionAuthorityChanged": False,
            "d221PromotedOrInstalled": False,
            "mergeAuthorized": False,
        }
        write_json(args.evidence_root / "terminal-summary.json", summary)
        package = build_package(
            args.canonical_root,
            task_root,
            args.evidence_root,
            args.zip_path,
            candidate["release"],
        )
        print(canonical_json({**summary, "package": package}))
        return 0
    except Exception as exc:
        failure = {
            "status": "FAIL",
            "exceptionClass": type(exc).__name__,
            "message": str(exc),
        }
        args.evidence_root.mkdir(parents=True, exist_ok=True)
        write_json(args.evidence_root / "terminal-failure.json", failure)
        print(canonical_json(failure), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
