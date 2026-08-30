"""Run and package the bounded STAT-DATA-002 prospective canary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from momentum_hunter.continuous_evidence_writer import build_continuous_writer_topology_v2
from momentum_hunter.continuous_live_qualification import (
    _acquire_qualification_resources,
    _resource_cleanup_receipt,
    run_live_qualification,
)
from momentum_hunter.continuous_runtime import (
    ContinuousOpportunityRuntime,
    ContinuousRuntimeConfig,
    LogicalRuntimeLeaseRegistry,
    QueueCapacities,
    RuntimeCadence,
)
from momentum_hunter.prospective_denominator import (
    ProspectiveDenominatorStore,
    build_activation_record,
    load_activation_record,
)
from momentum_hunter.preserved_provider_replay import (
    PROFILE as PRESERVED_PROVIDER_REPLAY,
    load_preserved_provider_replay,
)
from momentum_hunter.schwab_candle_backfill import (
    CandleBackfillOptions,
    SchwabHistoricalCandleBackfiller,
    explicit_universe,
)
from momentum_hunter.schwab_candle_observer import (
    SchwabMarketDataOnlyAccessGuard,
)
from momentum_hunter.schwab_candle_store import SchwabCandleStore
from momentum_hunter.schwab_daily_candle_store import SchwabDailyCandleStore
from momentum_hunter.schwab_market_data import (
    SchwabMarketDataQuoteSource,
    SchwabReadOnlyAccessTokenProvider,
    build_regular_market_quote_proof,
)


TASK_BRANCH = "codex/ARGUS-STAT-DATA-002D"
PRODUCTION_BASE = "23ee162373654e1db91af4c19f75bbc7887e3174"
EASTERN = ZoneInfo("America/New_York")
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
AUTHORITY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY = "NONE"
SCHWAB_PREFLIGHT_MAX_AGE_SECONDS = 900
FOCUSED_MODULES = (
    "tests.test_prospective_denominator",
    "tests.test_opportunity_denominator",
    "tests.test_continuous_denominator",
    "tests.test_continuous_live_qualification",
    "tests.test_stat_data_002_canary",
    "tests.test_preserved_provider_replay",
)
FIXTURE_MODULES = (
    "test_continuous_composition.py",
    "test_discovery_pagination.py",
)


class StatDataCanaryError(RuntimeError):
    pass


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(_canonical_bytes({"domain": domain, "value": value})).hexdigest()


def _write_once(path: Path, value: object) -> None:
    content = value if isinstance(value, bytes) else _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise StatDataCanaryError(f"Conflicting write-once evidence: {path}")
        return
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _new_ephemeral_runtime_root() -> Path:
    temporary_root = Path(tempfile.gettempdir()).resolve()
    root = temporary_root / f"MomentumHunter-StatData002D-{uuid.uuid4().hex}"
    if root.exists():
        raise StatDataCanaryError("Ephemeral runtime root unexpectedly already exists.")
    return root


def _runtime_root_is_ephemeral(root: Path) -> bool:
    try:
        root.resolve().relative_to(Path(tempfile.gettempdir()).resolve())
    except ValueError:
        return False
    return True


def _tree_identity(root: Path) -> list[dict[str, object]]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        }
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    ]


def _resource_release_proof(runtime_root: Path) -> dict[str, object]:
    path = runtime_root / "resource-cleanup.json"
    try:
        receipt = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StatDataCanaryError(
            "Runtime resource-cleanup evidence is unavailable."
        ) from exc
    fingerprint = receipt.get("fingerprint")
    unsigned = dict(receipt)
    unsigned.pop("fingerprint", None)
    if fingerprint != _fingerprint(
        "live-qualification-resource-cleanup-v1", unsigned
    ):
        raise StatDataCanaryError(
            "Runtime resource-cleanup evidence fingerprint is invalid."
        )
    required = (
        receipt.get("status") == "PASS"
        and receipt.get("writerReleaseSatisfied") is True
        and receipt.get("capabilityReleaseSatisfied") is True
        and receipt.get("runtimeShutdownSatisfied") is True
    )
    if not required:
        raise StatDataCanaryError(
            "Runtime resources were not proven released before forensic export."
        )
    return receipt


def _export_ephemeral_runtime(
    *,
    runtime_root: Path,
    evidence_root: Path,
    export_name: str = "natural-runtime-forensic",
) -> dict[str, object]:
    if not _runtime_root_is_ephemeral(runtime_root):
        raise StatDataCanaryError("Runtime root is not beneath the canonical temp root.")
    if not runtime_root.is_dir():
        raise StatDataCanaryError("Ephemeral runtime root is unavailable for export.")
    cleanup = _resource_release_proof(runtime_root)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", export_name):
        raise StatDataCanaryError("Forensic export name is invalid.")
    export_root = evidence_root / export_name
    payload_root = export_root / "payload"
    if export_root.exists():
        raise StatDataCanaryError("Durable runtime forensic export must be new.")
    source_identity = _tree_identity(runtime_root)
    export_root.mkdir(parents=True)
    shutil.copytree(runtime_root, payload_root)
    destination_identity = _tree_identity(payload_root)
    source_fingerprint = _fingerprint("ephemeral-runtime-tree-v1", source_identity)
    destination_fingerprint = _fingerprint(
        "ephemeral-runtime-tree-v1", destination_identity
    )
    verified = source_identity == destination_identity
    _write_once(
        export_root / "source-manifest.json",
        {
            "root": str(runtime_root),
            "files": source_identity,
            "fingerprint": source_fingerprint,
        },
    )
    _write_once(
        export_root / "destination-manifest.json",
        {
            "root": "payload",
            "files": destination_identity,
            "fingerprint": destination_fingerprint,
        },
    )
    marker = {
        "classification": "FORENSIC_COPY_ONLY",
        "runtimeAuthority": False,
        "restoreOrResumeAuthorized": False,
        "sourceRootWasTemporary": True,
        "resourceCleanupStatus": cleanup.get("status"),
    }
    marker["fingerprint"] = _fingerprint("forensic-runtime-copy-v1", marker)
    _write_once(export_root / "FORENSIC_COPY_ONLY.json", marker)
    if not verified or source_fingerprint != destination_fingerprint:
        raise StatDataCanaryError("Ephemeral runtime forensic export verification failed.")
    retirement_error: str | None = None
    try:
        shutil.rmtree(runtime_root)
    except OSError as exc:
        retirement_error = type(exc).__name__
    retired = not runtime_root.exists()
    receipt: dict[str, object] = {
        "status": "PASS" if retired else "FAIL",
        "sourceRoot": str(runtime_root),
        "destinationRoot": str(export_root),
        "sourceFileCount": len(source_identity),
        "destinationFileCount": len(destination_identity),
        "sourceFingerprint": source_fingerprint,
        "destinationFingerprint": destination_fingerprint,
        "hashManifestVerified": verified,
        "resourceCleanupStatus": cleanup.get("status"),
        "writerClosed": cleanup.get("writerClosed"),
        "capabilityClosed": cleanup.get("capabilityClosed"),
        "runtimeShutdownSatisfied": cleanup.get("runtimeShutdownSatisfied"),
        "forensicCopyOnly": True,
        "runtimeAuthority": False,
        "sourceRetired": retired,
        "sourceRetirementError": retirement_error,
        "exportedAt": datetime.now().astimezone().isoformat(),
    }
    receipt["fingerprint"] = _fingerprint(
        "ephemeral-runtime-forensic-export-v1", receipt
    )
    receipt_name = (
        "ephemeral-runtime-export.json"
        if export_name == "natural-runtime-forensic"
        else f"{export_name}-export.json"
    )
    _write_once(evidence_root / receipt_name, receipt)
    return receipt


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_identity(root: Path) -> dict[str, str]:
    return {
        "head": _git(root, "rev-parse", "HEAD"),
        "branch": _git(root, "branch", "--show-current"),
        "status": _git(root, "status", "--porcelain"),
    }


def _configuration(
    *,
    task_root: Path,
    production_root: Path,
    evidence_root: Path,
    session_date: str,
    duration_seconds: int,
    discovery_cadence_seconds: int,
    schwab_preflight_fingerprint: str | None = None,
    offline_rehearsal: bool = False,
    preserved_provider_package: Path | None = None,
) -> dict[str, object]:
    task = _git_identity(task_root)
    production = _git_identity(production_root)
    if task["branch"] != TASK_BRANCH or task["status"]:
        raise StatDataCanaryError("Task branch identity is wrong or dirty.")
    if production != {
        "head": PRODUCTION_BASE,
        "branch": "master",
        "status": "",
    }:
        raise StatDataCanaryError("Canonical production baseline is wrong or dirty.")
    if _git(production_root, "rev-parse", "origin/master") != PRODUCTION_BASE:
        raise StatDataCanaryError("Canonical origin/master drifted.")
    remote_task = _git(task_root, "rev-parse", f"origin/{TASK_BRANCH}")
    if remote_task != task["head"]:
        raise StatDataCanaryError("Task branch is not pushed at its exact head.")
    replay = (
        load_preserved_provider_replay(preserved_provider_package)
        if preserved_provider_package is not None
        else None
    )
    current_session = datetime.now(EASTERN).date().isoformat()
    if replay is None and session_date != current_session:
        raise StatDataCanaryError(
            f"Requested session {session_date} differs from current Eastern date {current_session}."
        )
    if replay is not None and session_date != replay.session_date:
        raise StatDataCanaryError(
            "Replay session date differs from the preserved provider chronology."
        )
    payload: dict[str, object] = {
        "schemaVersion": 1,
        "task": "ARGUS-STAT-DATA-002D",
        "taskGit": task,
        "productionGit": production,
        "sessionDate": session_date,
        "durationSeconds": duration_seconds,
        "discoveryCadenceSeconds": discovery_cadence_seconds,
        "evidenceRoot": str(evidence_root.resolve()),
        "authority": AUTHORITY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "accountValuesRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "paperRequested": False,
        "shadowRequested": False,
        "schwabPreflightRequired": schwab_preflight_fingerprint is not None,
        "schwabPreflightFingerprint": schwab_preflight_fingerprint,
        "offlineRehearsal": offline_rehearsal or replay is not None,
        "providerMode": replay.mode if replay is not None else "LIVE_PROVIDER",
        "preservedProviderPackagePath": (
            str(replay.package_path) if replay is not None else None
        ),
        "preservedProviderPackageSha256": (
            replay.package_sha256 if replay is not None else None
        ),
        "preservedProviderSourceFingerprint": (
            replay.source_fingerprint if replay is not None else None
        ),
        "preservedProviderLaunchAt": (
            replay.launch_at.isoformat() if replay is not None else None
        ),
        "countsAsNewProspectiveLiveEvidence": False if replay is not None else True,
    }
    payload["fingerprint"] = _fingerprint("stat-data-002-canary-configuration-v1", payload)
    return payload


def prepare(
    *,
    task_root: Path,
    production_root: Path,
    evidence_root: Path,
    session_date: str,
    duration_seconds: int,
    discovery_cadence_seconds: int,
    schwab_preflight_proof: Path | None = None,
    require_schwab_preflight: bool = True,
    preserved_provider_package: Path | None = None,
) -> dict[str, object]:
    if evidence_root.exists():
        raise StatDataCanaryError("Canary evidence root must be new.")
    validated_preflight = (
        _validate_schwab_preflight(
            schwab_preflight_proof,
            task_root=task_root,
            production_root=production_root,
        )
        if require_schwab_preflight
        else None
    )
    if require_schwab_preflight and preserved_provider_package is not None:
        raise StatDataCanaryError(
            "Offline preserved-provider replay cannot require live Schwab preflight."
        )
    replay = (
        load_preserved_provider_replay(preserved_provider_package)
        if preserved_provider_package is not None
        else None
    )
    configuration = _configuration(
        task_root=task_root,
        production_root=production_root,
        evidence_root=evidence_root,
        session_date=session_date,
        duration_seconds=duration_seconds,
        discovery_cadence_seconds=discovery_cadence_seconds,
        schwab_preflight_fingerprint=(
            str(validated_preflight["fingerprint"])
            if validated_preflight is not None
            else None
        ),
        offline_rehearsal=not require_schwab_preflight,
        preserved_provider_package=preserved_provider_package,
    )
    evidence_root.mkdir(parents=True)
    activated_at = (
        replay.activation_at.isoformat()
        if replay is not None
        else datetime.now().astimezone().isoformat()
    )
    activation = build_activation_record(
        activated_at=activated_at,
        first_eligible_session_date=session_date,
        source_git_sha=str(configuration["taskGit"]["head"]),
        configuration_fingerprint=str(configuration["fingerprint"]),
    )
    _write_once(evidence_root / "configuration.json", configuration)
    if validated_preflight is not None:
        _write_once(
            evidence_root / "provider-preflight" / "schwab-readiness.json",
            validated_preflight,
        )
    _write_once(
        evidence_root / "activation.json",
        {
            "recordType": "STAT_DATA_002_ACTIVATION",
            "payload": asdict(activation),
        },
    )
    preflight = {
        "status": "PASS",
        "preparedAt": activated_at,
        "activationFingerprint": activation.fingerprint,
        "taskHead": configuration["taskGit"]["head"],
        "productionHead": configuration["productionGit"]["head"],
        "providerContact": False,
        "schwabPreflight": (
            "PASS"
            if validated_preflight is not None
            else "OFFLINE_PRESERVED_PROVIDER_REPLAY"
            if replay is not None
            else "OFFLINE_REHEARSAL_NOT_REQUIRED"
        ),
        "providerMode": replay.mode if replay is not None else "LIVE_PROVIDER",
        "preservedProviderSourceFingerprint": (
            replay.source_fingerprint if replay is not None else None
        ),
        "authority": AUTHORITY,
        "executionAuthority": EXECUTION_AUTHORITY,
    }
    preflight["fingerprint"] = _fingerprint("stat-data-002-preflight-v1", preflight)
    _write_once(evidence_root / "preflight.json", preflight)
    return preflight


def execute(
    *,
    task_root: Path,
    production_root: Path,
    evidence_root: Path,
    expected_account_ending: str,
) -> dict[str, object]:
    started = datetime.now().astimezone().isoformat()
    regular_session_started: str | None = None
    provider_contact_attempted = False
    failure_stage = "LOAD_CONFIGURATION"
    activation = None
    summary: dict[str, object] | None = None
    runtime_root: Path | None = None
    forensic_export: dict[str, object] | None = None
    forensic_export_error: dict[str, str] | None = None
    preserved_replay = None
    preserved_provider_boundary_attempted = False
    try:
        configuration = json.loads(
            (evidence_root / "configuration.json").read_text(encoding="ascii")
        )
        if configuration.get("providerMode") == PRESERVED_PROVIDER_REPLAY:
            failure_stage = "LOAD_PRESERVED_PROVIDER_EVIDENCE"
            preserved_path = Path(
                str(configuration.get("preservedProviderPackagePath", ""))
            )
            preserved_replay = load_preserved_provider_replay(preserved_path)
            if (
                preserved_replay.package_sha256
                != configuration.get("preservedProviderPackageSha256")
                or preserved_replay.source_fingerprint
                != configuration.get("preservedProviderSourceFingerprint")
            ):
                raise StatDataCanaryError(
                    "Preserved provider evidence changed after activation."
                )
        failure_stage = "VERIFY_SCHWAB_PREFLIGHT"
        if (
            configuration.get("schwabPreflightRequired") is not True
            and configuration.get("offlineRehearsal") is not True
        ):
            raise StatDataCanaryError(
                "Live canary configuration omitted the required Schwab preflight."
            )
        if configuration.get("schwabPreflightRequired") is True:
            preserved_preflight = json.loads(
                (
                    evidence_root
                    / "provider-preflight"
                    / "schwab-readiness.json"
                ).read_text(encoding="ascii")
            )
            if (
                preserved_preflight.get("fingerprint")
                != configuration.get("schwabPreflightFingerprint")
                or preserved_preflight.get("status") != "PASS"
            ):
                raise StatDataCanaryError(
                    "Schwab provider readiness proof changed or is not passing."
                )
        failure_stage = "LOAD_ACTIVATION"
        activation = load_activation_record(evidence_root / "activation.json")
        failure_stage = "VERIFY_TASK_IDENTITY"
        if _git_identity(task_root) != configuration["taskGit"]:
            raise StatDataCanaryError("Task source changed after activation.")
        failure_stage = "VERIFY_PRODUCTION_IDENTITY"
        if _git_identity(production_root) != configuration["productionGit"]:
            raise StatDataCanaryError("Canonical production changed after activation.")
        failure_stage = "VALIDATE_MARKET_DATA_IDENTITY"
        if preserved_replay is None and (
            len(expected_account_ending) != 4 or not expected_account_ending.isdigit()
        ):
            raise StatDataCanaryError("Expected market-data identity ending is invalid.")
        if preserved_replay is not None and expected_account_ending:
            raise StatDataCanaryError(
                "Offline preserved-provider replay received an account identity."
            )
        failure_stage = "ASSERT_MARKET_WINDOW"
        regular_session_started = (
            preserved_replay.launch_at.isoformat()
            if preserved_replay is not None
            else _assert_regular_session()
        )
        failure_stage = "RUN_NATURAL_PROVIDER_PATH"
        provider_contact_attempted = preserved_replay is None
        preserved_provider_boundary_attempted = preserved_replay is not None
        runtime_root = _new_ephemeral_runtime_root()
        provider_error: Exception | None = None
        try:
            summary = run_live_qualification(
                generation_root=runtime_root,
                canonical_root=task_root,
                expected_account_ending=expected_account_ending,
                duration_seconds=int(configuration["durationSeconds"]),
                discovery_cadence_seconds=int(configuration["discoveryCadenceSeconds"]),
                prospective_activation=activation,
                prospective_root=evidence_root / "prospective-denominator",
                preserved_provider_replay=preserved_replay,
            )
        except Exception as exc:
            provider_error = exc
        failure_stage = "EXPORT_EPHEMERAL_RUNTIME"
        try:
            forensic_export = _export_ephemeral_runtime(
                runtime_root=runtime_root,
                evidence_root=evidence_root,
            )
            if forensic_export.get("status") != "PASS":
                forensic_export_error = {
                    "exceptionClass": "StatDataCanaryError",
                    "exceptionMessage": "Ephemeral runtime root could not be retired.",
                }
                if provider_error is None:
                    raise StatDataCanaryError(
                        "Ephemeral runtime root could not be retired."
                    )
        except Exception as exc:
            forensic_export_error = {
                "exceptionClass": type(exc).__name__,
                "exceptionMessage": _sanitized_message(
                    str(exc), expected_account_ending
                ),
            }
            if provider_error is None:
                raise
        if provider_error is not None:
            failure_stage = "RUN_NATURAL_PROVIDER_PATH"
            raise provider_error
        terminal: dict[str, object] = {
            "status": "PASS" if summary.get("status") == "PASS" else "FAIL",
            "startedAt": started,
            "regularSessionStartedAt": regular_session_started,
            "completedAt": datetime.now().astimezone().isoformat(),
            "qualificationSummary": summary,
            "failureStage": None,
            "exceptionClass": None,
            "exceptionMessage": None,
        }
    except Exception as exc:  # terminal evidence must survive every failure
        terminal = {
            "status": "FAIL",
            "startedAt": started,
            "regularSessionStartedAt": regular_session_started,
            "completedAt": datetime.now().astimezone().isoformat(),
            "qualificationSummary": None,
            "failureStage": failure_stage,
            "exceptionClass": type(exc).__name__,
            "exceptionMessage": _sanitized_message(str(exc), expected_account_ending),
        }
    provider_contact = (
        {
            "providerContact": False,
            "providerContactEvidence": [],
            "providerContactByProvider": {
                "finviz": {"contact": False, "evidence": []},
                "schwab": {
                    "contact": False,
                    "quoteData": False,
                    "historyData": False,
                    "evidence": [],
                },
            },
        }
        if preserved_replay is not None
        else _provider_contact_report(evidence_root, summary)
    )
    prospective_summary = (
        summary.get("prospectiveDenominator") if summary is not None else None
    )
    prospective_summary_error: dict[str, str] | None = None
    prospective_root = evidence_root / "prospective-denominator"
    if prospective_summary is None and activation is not None and prospective_root.exists():
        try:
            prospective_summary = asdict(
                ProspectiveDenominatorStore(
                    prospective_root,
                    activation=activation,
                ).summary()
            )
        except Exception as exc:
            prospective_summary_error = {
                "exceptionClass": type(exc).__name__,
                "exceptionMessage": _sanitized_message(
                    str(exc),
                    expected_account_ending,
                ),
            }
    if (
        prospective_summary is None
        and not provider_contact_attempted
        and prospective_summary_error is None
    ):
        prospective_summary = _zero_prospective_summary()
    terminal.update(
        {
            "providerContactAttempted": provider_contact_attempted,
            "providerContact": provider_contact["providerContact"],
            "providerContactEvidence": provider_contact["providerContactEvidence"],
            "providerContactByProvider": provider_contact["providerContactByProvider"],
            "preservedProviderBoundaryAttempted": (
                preserved_provider_boundary_attempted
            ),
            "preservedProviderEvidenceConsumed": (
                preserved_replay.receipt() if preserved_replay is not None else None
            ),
            "countsAsNewProspectiveLiveEvidence": preserved_replay is None,
            "ephemeralRuntimeRoot": str(runtime_root) if runtime_root else None,
            "ephemeralRuntimeUnderTemp": (
                _runtime_root_is_ephemeral(runtime_root) if runtime_root else None
            ),
            "forensicRuntimeExport": forensic_export,
            "forensicRuntimeExportError": forensic_export_error,
            "prospectiveSummary": prospective_summary,
            "prospectiveSummaryError": prospective_summary_error,
            "authority": AUTHORITY,
            "executionAuthority": EXECUTION_AUTHORITY,
            "accountValuesRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "ordersTransmitted": 0,
        }
    )
    terminal["fingerprint"] = _fingerprint("stat-data-002-terminal-v1", terminal)
    _write_once(evidence_root / "terminal-result.json", terminal)
    return terminal


def run_schwab_preflight(
    *,
    task_root: Path,
    production_root: Path,
    evidence_root: Path,
    expected_account_ending: str,
) -> dict[str, object]:
    if evidence_root.exists():
        raise StatDataCanaryError("Schwab preflight evidence root must be new.")
    if len(expected_account_ending) != 4 or not expected_account_ending.isdigit():
        raise StatDataCanaryError("Expected market-data identity ending is invalid.")
    task = _git_identity(task_root)
    production = _git_identity(production_root)
    if task["branch"] != TASK_BRANCH or task["status"]:
        raise StatDataCanaryError("Task branch identity is wrong or dirty.")
    if _git(task_root, "rev-parse", f"origin/{TASK_BRANCH}") != task["head"]:
        raise StatDataCanaryError("Task branch is not pushed at its exact head.")
    if production != {
        "head": PRODUCTION_BASE,
        "branch": "master",
        "status": "",
    } or _git(production_root, "rev-parse", "origin/master") != PRODUCTION_BASE:
        raise StatDataCanaryError("Canonical production baseline is wrong or dirty.")

    evidence_root.mkdir(parents=True)
    disposable = Path(tempfile.gettempdir()) / f"MomentumHunter-StatData002C-Preflight-{uuid.uuid4().hex}"
    quote_proof: dict[str, object] | None = None
    history_proof: dict[str, object] | None = None
    diagnostic_code: str | None = None
    exception_class: str | None = None
    try:
        token_provider = SchwabReadOnlyAccessTokenProvider()
        access_guard = SchwabMarketDataOnlyAccessGuard(token_provider=token_provider)
        access_guard.authorize(expected_account_ending)
        quote_proof = build_regular_market_quote_proof(
            SchwabMarketDataQuoteSource(token_provider=token_provider),
            ("SPY",),
            require_clock_proof=True,
        )
        backfill = SchwabHistoricalCandleBackfiller(
            minute_store=SchwabCandleStore(disposable / "minute"),
            daily_store=SchwabDailyCandleStore(disposable / "daily"),
            access_guard=access_guard,
            utc_clock=lambda: datetime.now(timezone.utc),
        ).backfill(
            explicit_universe(("SPY",)),
            CandleBackfillOptions(
                expected_account_ending=expected_account_ending,
                minute_lookback_days=5,
                daily_lookback_days=30,
                history_attempts=1,
            ),
        )
        minute_rows = sum(
            int(item.get("minute", {}).get("rows", 0))
            for item in backfill.get("symbols", [])
        )
        daily_rows = sum(
            int(item.get("daily", {}).get("rows", 0))
            for item in backfill.get("symbols", [])
        )
        history_proof = {
            "status": (
                "PASS"
                if backfill.get("status") == "COMPLETE"
                and minute_rows > 0
                and daily_rows > 0
                else "FAIL"
            ),
            "provider": "SCHWAB_PRICE_HISTORY",
            "symbol": "SPY",
            "minuteRows": minute_rows,
            "dailyRows": daily_rows,
            "resultFingerprint": backfill.get("resultFingerprint"),
            "disposableStore": True,
            "productionStoreWritten": False,
        }
    except Exception as exc:
        diagnostic_code = _provider_failure_code(exc)
        exception_class = type(exc).__name__
    finally:
        try:
            if disposable.exists():
                shutil.rmtree(disposable)
        except OSError:
            pass

    quote_status = (
        quote_proof.get("proofStatus") if isinstance(quote_proof, dict) else "FAIL"
    )
    history_status = (
        history_proof.get("status") if isinstance(history_proof, dict) else "FAIL"
    )
    retired = not disposable.exists()
    status = (
        "PASS"
        if quote_status == "PASS"
        and history_status == "PASS"
        and retired
        and diagnostic_code is None
        else "FAIL"
    )
    result: dict[str, object] = {
        "schemaVersion": 1,
        "task": "ARGUS-STAT-DATA-002C",
        "status": status,
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "taskGit": task,
        "productionGit": production,
        "symbol": "SPY",
        "schwabAuthState": "READY" if status == "PASS" else "NOT_READY",
        "schwabQuotePreflight": quote_status,
        "schwabHistoryPreflight": history_status,
        "schwabInteractiveReauthRequired": (
            diagnostic_code == "SCHWAB_INTERACTIVE_REAUTH_REQUIRED"
        ),
        "diagnosticCode": diagnostic_code,
        "exceptionClass": exception_class,
        "quoteProof": quote_proof,
        "historyProof": history_proof,
        "providerContactAttempted": True,
        "providerContact": quote_proof is not None or history_proof is not None,
        "disposableStoresRetired": retired,
        "authority": AUTHORITY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "accountValuesRequested": False,
        "balancesRequested": False,
        "positionsRequested": False,
        "paperRequested": False,
        "shadowRequested": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
        "credentialMaterialIncluded": False,
    }
    result["fingerprint"] = _fingerprint("stat-data-002c-schwab-preflight-v1", result)
    _write_once(evidence_root / "schwab-preflight.json", result)
    return result


def _provider_failure_code(exc: BaseException) -> str:
    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        diagnostic = getattr(current, "diagnostic_code", None)
        if diagnostic == "SCHWAB_REAUTH_REQUIRED" or "ReauthorizationRequired" in type(current).__name__:
            return "SCHWAB_INTERACTIVE_REAUTH_REQUIRED"
        if isinstance(diagnostic, str) and diagnostic:
            return diagnostic
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return type(exc).__name__


def _validate_schwab_preflight(
    proof_path: Path | None,
    *,
    task_root: Path,
    production_root: Path,
) -> dict[str, object]:
    if proof_path is None:
        raise StatDataCanaryError("A passing Schwab provider preflight is required.")
    try:
        proof = json.loads(proof_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StatDataCanaryError("Schwab provider preflight evidence is unavailable.") from exc
    expected_fingerprint = proof.get("fingerprint")
    unsigned = dict(proof)
    unsigned.pop("fingerprint", None)
    if expected_fingerprint != _fingerprint(
        "stat-data-002c-schwab-preflight-v1", unsigned
    ):
        raise StatDataCanaryError("Schwab provider preflight fingerprint is invalid.")
    observed_at = datetime.fromisoformat(str(proof.get("observedAt", "")))
    age = (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
    if age < 0 or age > SCHWAB_PREFLIGHT_MAX_AGE_SECONDS:
        raise StatDataCanaryError("Schwab provider preflight is outside the freshness window.")
    required = (
        proof.get("status") == "PASS"
        and proof.get("schwabAuthState") == "READY"
        and proof.get("schwabQuotePreflight") == "PASS"
        and proof.get("schwabHistoryPreflight") == "PASS"
        and proof.get("schwabInteractiveReauthRequired") is False
        and proof.get("disposableStoresRetired") is True
        and proof.get("accountValuesRequested") is False
        and proof.get("positionsRequested") is False
        and proof.get("ordersRequested") is False
        and proof.get("executionAuthority") == EXECUTION_AUTHORITY
        and proof.get("taskGit") == _git_identity(task_root)
        and proof.get("productionGit") == _git_identity(production_root)
    )
    if not required:
        raise StatDataCanaryError("Schwab provider preflight did not satisfy the live gate.")
    return proof


def _verified_export_files(evidence_root: Path) -> list[str]:
    export_root = evidence_root / "natural-runtime-forensic"
    payload_root = export_root / "payload"
    manifest_path = export_root / "destination-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    verified: list[str] = []
    for item in manifest.get("files", []):
        if not isinstance(item, dict):
            continue
        relative_text = str(item.get("path", ""))
        relative = Path(relative_text)
        path = payload_root / relative
        if not path.is_file():
            continue
        if path.stat().st_size != int(item.get("size", -1)):
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest().upper() != str(
            item.get("sha256", "")
        ):
            continue
        verified.append(path.relative_to(evidence_root).as_posix())
    return sorted(verified)


def _provider_contact_evidence(evidence_root: Path) -> list[str]:
    return [
        item
        for item in _verified_export_files(evidence_root)
        if "/source-evidence/" in f"/{item}"
    ]


def _provider_contact_report(
    evidence_root: Path,
    qualification_summary: dict[str, object] | None,
) -> dict[str, object]:
    evidence = _provider_contact_evidence(evidence_root)
    verified_files = set(_verified_export_files(evidence_root))
    finviz_evidence = [
        item for item in evidence if "/source-evidence/finviz/" in f"/{item}"
    ]
    schwab_evidence = [
        item for item in evidence if "/source-evidence/schwab/" in f"/{item}"
    ]
    summary = qualification_summary or {}
    quote_symbols = int(summary.get("schwabQuoteSymbols", 0) or 0)
    minute_rows = int(summary.get("schwabMinuteRows", 0) or 0)
    daily_rows = int(summary.get("schwabDailyRows", 0) or 0)
    summary_path = (
        evidence_root
        / "natural-runtime-forensic"
        / "payload"
        / "qualification-summary.json"
    )
    summary_identity = summary_path.relative_to(evidence_root).as_posix()
    schwab_summary_evidence: list[str] = []
    if summary_identity in verified_files and quote_symbols > 0:
        schwab_summary_evidence.append(
            summary_identity + "#schwabQuoteSymbols"
        )
    if summary_identity in verified_files and minute_rows + daily_rows > 0:
        schwab_summary_evidence.append(
            summary_identity + "#schwabMinuteRows,schwabDailyRows"
        )
    schwab_contact_evidence = sorted(
        dict.fromkeys((*schwab_evidence, *schwab_summary_evidence))
    )
    all_evidence = sorted(dict.fromkeys((*evidence, *schwab_summary_evidence)))
    providers = {
        "finviz": {
            "contact": bool(finviz_evidence),
            "evidence": finviz_evidence,
        },
        "schwab": {
            "contact": bool(schwab_contact_evidence),
            "quoteData": quote_symbols > 0,
            "historyData": minute_rows + daily_rows > 0,
            "evidence": schwab_contact_evidence,
        },
    }
    return {
        "providerContact": any(item["contact"] for item in providers.values()),
        "providerContactEvidence": all_evidence,
        "providerContactByProvider": providers,
    }


def _zero_prospective_summary() -> dict[str, object]:
    return {
        "prospective_observations_seen": 0,
        "unique_prospective_members": 0,
        "duplicate_observations_suppressed": 0,
        "outcome_complete_members": 0,
        "outcome_pending_members": 0,
        "population_counts": {},
    }


def _parsed_timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StatDataCanaryError("Chronology timestamp omitted timezone evidence.")
    return parsed


def _anti_hindsight_proof(
    evidence_root: Path,
    *,
    activation_at: str,
) -> dict[str, object]:
    activation = _parsed_timestamp(activation_at)
    prospective = evidence_root / "prospective-denominator"
    attempt_paths = tuple(
        (evidence_root / "natural-runtime-forensic" / "payload").glob(
            "checkpoint/*-attempts/attempt-events.jsonl"
        )
    )
    attempt_count = 0
    known_at_count = 0
    violations: list[dict[str, str]] = []
    for path in attempt_paths:
        for line_number, line in enumerate(
            path.read_text(encoding="ascii").splitlines(),
            start=1,
        ):
            event = json.loads(line)
            cutoff = _parsed_timestamp(event["canonical_request_cutoff"])
            attempt_count += 1
            for label, known_at in event.get("canonical_evidence_known_at", []):
                known_at_count += 1
                if _parsed_timestamp(known_at) > cutoff:
                    violations.append(
                        {
                            "path": path.relative_to(evidence_root).as_posix(),
                            "record": str(line_number),
                            "field": str(label),
                            "reason": "EVIDENCE_AFTER_DECISION_CUTOFF",
                        }
                    )
    prospective_records = 0
    prospective_floor_violations = 0
    for family in ("cycles", "opportunities"):
        for path in prospective.rglob(f"{family}/*.json"):
            record = json.loads(path.read_text(encoding="ascii"))
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                continue
            prospective_records += 1
            observed_at = _parsed_timestamp(payload.get("observed_at"))
            if observed_at < activation:
                prospective_floor_violations += 1
                violations.append(
                    {
                        "path": path.relative_to(evidence_root).as_posix(),
                        "record": str(prospective_records),
                        "field": "observed_at",
                        "reason": "PROSPECTIVE_RECORD_BEFORE_ACTIVATION",
                    }
                )
            cutoff_value = payload.get("decision_cutoff")
            for reference in payload.get("evidence_refs", []):
                if (
                    cutoff_value is not None
                    and isinstance(reference, dict)
                    and reference.get("as_of") is not None
                    and _parsed_timestamp(reference["as_of"])
                    > _parsed_timestamp(cutoff_value)
                ):
                    violations.append(
                        {
                            "path": path.relative_to(evidence_root).as_posix(),
                            "record": str(prospective_records),
                            "field": "evidence_refs.as_of",
                            "reason": "EVIDENCE_REFERENCE_AFTER_DECISION_CUTOFF",
                        }
                    )
    result: dict[str, object] = {
        "status": "PASS" if not violations and attempt_count > 0 else "FAIL",
        "activationAt": activation_at,
        "attemptRecordsChecked": attempt_count,
        "knownAtValuesChecked": known_at_count,
        "prospectiveRecordsChecked": prospective_records,
        "prospectiveFloorViolations": prospective_floor_violations,
        "violations": violations,
    }
    result["fingerprint"] = _fingerprint(
        "stat-data-002d-anti-hindsight-proof-v1",
        result,
    )
    return result


def verify(evidence_root: Path) -> dict[str, object]:
    activation = load_activation_record(evidence_root / "activation.json")
    terminal = json.loads((evidence_root / "terminal-result.json").read_text(encoding="ascii"))
    root = evidence_root / "prospective-denominator"
    if root.exists():
        summary = asdict(ProspectiveDenominatorStore(root, activation=activation).summary())
    else:
        summary = None
    anti_hindsight = _anti_hindsight_proof(
        evidence_root,
        activation_at=activation.activated_at,
    )
    membership_precedes_outcome = (
        summary is not None
        and int(summary["outcome_complete_members"])
        + int(summary["outcome_pending_members"])
        == int(summary["unique_prospective_members"])
    )
    result: dict[str, object] = {
        "status": (
            "PASS"
            if terminal.get("status") == "PASS"
            and summary is not None
            and int(summary["unique_prospective_members"]) >= 1
            and membership_precedes_outcome
            and anti_hindsight["status"] == "PASS"
            else "FAIL"
        ),
        "terminalStatus": terminal.get("status"),
        "prospectiveSummary": summary,
        "activationFingerprint": activation.fingerprint,
        "membershipPrecedesOutcome": membership_precedes_outcome,
        "antiHindsight": anti_hindsight,
        "authority": AUTHORITY,
        "executionAuthority": EXECUTION_AUTHORITY,
    }
    result["fingerprint"] = _fingerprint("stat-data-002-verification-v1", result)
    _write_once(evidence_root / "verification.json", result)
    return result


def package(
    *,
    task_root: Path,
    evidence_root: Path,
    python_executable: Path,
) -> dict[str, object]:
    terminal = json.loads(
        (evidence_root / "terminal-result.json").read_text(encoding="ascii")
    )
    if (
        terminal.get("providerContactAttempted") is True
        or terminal.get("preservedProviderBoundaryAttempted") is True
    ):
        export = terminal.get("forensicRuntimeExport")
        if not isinstance(export, dict) or (
            export.get("hashManifestVerified") is not True
            or export.get("resourceCleanupStatus") != "PASS"
        ):
            raise StatDataCanaryError(
                "Packaging cannot begin before verified runtime export and release."
            )
        if export.get("writerClosed") is not True or export.get("capabilityClosed") is not True:
            raise StatDataCanaryError(
                "Packaging cannot begin while writer resources may remain active."
            )
    stage = evidence_root.parent / f"{evidence_root.name}-SECOND-EYE-STAGE"
    zip_path = evidence_root.parent / f"{evidence_root.name}-SECOND-EYE.zip"
    if stage.exists() or zip_path.exists():
        raise StatDataCanaryError("Second-eye stage or ZIP already exists.")
    stage.mkdir(parents=True)
    source_root = stage / "source"
    shutil.copytree(
        task_root / "momentum_hunter",
        source_root / "momentum_hunter",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    tests_root = source_root / "tests"
    tests_root.mkdir(parents=True)
    _write_once(tests_root / "__init__.py", b"")
    selected = [f"{item.split('.')[-1]}.py" for item in FOCUSED_MODULES]
    for name in tuple(selected) + FIXTURE_MODULES:
        shutil.copy2(task_root / "tests" / name, tests_root / name)
    packaged_tools = source_root / "tools"
    packaged_tools.mkdir()
    shutil.copy2(Path(__file__), packaged_tools / Path(__file__).name)
    shutil.copytree(evidence_root, stage / "evidence")
    configuration = json.loads(
        (evidence_root / "configuration.json").read_text(encoding="ascii")
    )
    preserved_package = configuration.get("preservedProviderPackagePath")
    if preserved_package:
        inputs_root = stage / "inputs"
        inputs_root.mkdir()
        preserved_source = Path(str(preserved_package)).resolve(strict=True)
        if (
            hashlib.sha256(preserved_source.read_bytes()).hexdigest().upper()
            != configuration.get("preservedProviderPackageSha256")
        ):
            raise StatDataCanaryError(
                "Preserved provider package changed before packaging."
            )
        shutil.copy2(
            preserved_source,
            inputs_root / "preserved-provider-evidence.zip",
        )
    docs_root = stage / "docs"
    docs_root.mkdir()
    for source in (
        task_root / "docs" / "argus-office" / "goal-charters" / "ARGUS-STAT-DATA-002D.md",
        task_root / "docs" / "research" / "stat-data-002-prospective-activation-v2.md",
    ):
        shutil.copy2(source, docs_root / source.name)

    prezip = _run_focused(python_executable, source_root)
    _write_once(stage / "PRE_ZIP_VERIFICATION.json", prezip)
    scan = _secret_scan(stage)
    _write_once(stage / "SECRET_SCAN.json", scan)
    if scan["status"] != "PASS":
        raise StatDataCanaryError("Sanitization failed; unsafe ZIP was not emitted.")
    index = (
        "# ARGUS-STAT-DATA-002D Exact Run-All Second-Eye Packet\n\n"
        "- `evidence/`: immutable terminal canary evidence and denominator records.\n"
        "- `source/momentum_hunter/`: complete Python Product package for dependency closure.\n"
        "- `source/tests/`: focused tests plus required fixtures.\n"
        "- `source/tools/run_stat_data_002_canary.py`: exact canary/packaging wrapper.\n"
        "- `inputs/preserved-provider-evidence.zip`: accepted 001D/001E V4 market packet.\n"
        "- `docs/`: frozen Goal Charter and inventory.\n\n"
        "Run from `source/` with an approved Python 3.12 environment:\n\n"
        f"`python -B -m unittest {' '.join(FOCUSED_MODULES)}`\n\n"
        "The terminal evidence records the exact `run-all` command, preserved-source "
        "identity, replay chronology, restart, denominator records, and package result.\n"
    ).encode("ascii")
    _write_once(stage / "INDEX.md", index)
    manifest = _manifest(stage)
    _write_once(stage / "MANIFEST.json", manifest)
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in stage.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(stage).as_posix())
    zip_hash = hashlib.sha256(zip_path.read_bytes()).hexdigest().upper()

    with tempfile.TemporaryDirectory(prefix="stat-data-002-extracted-") as directory:
        extracted = Path(directory)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(extracted)
        manifest_status = _verify_manifest(extracted)
        extracted_verification = _run_focused(python_executable, extracted / "source")
    result: dict[str, object] = {
        "status": (
            "PASS"
            if prezip["status"] == "PASS"
            and manifest_status == "PASS"
            and extracted_verification["status"] == "PASS"
            else "FAIL"
        ),
        "zipPath": str(zip_path),
        "zipSha256": zip_hash,
        "fileCount": sum(1 for item in stage.rglob("*") if item.is_file()),
        "manifestCount": len(manifest["files"]),
        "secretScan": scan["status"],
        "preZipVerification": prezip,
        "manifestVerification": manifest_status,
        "extractedZipVerification": extracted_verification,
    }
    result["fingerprint"] = _fingerprint("stat-data-002-package-result-v1", result)
    _write_once(evidence_root / "package-result.json", result)
    return result


def _manifest(root: Path) -> dict[str, object]:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "MANIFEST.json":
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
            }
        )
    return {"schemaVersion": 1, "files": files}


def _verify_manifest(root: Path) -> str:
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="ascii"))
    for item in manifest.get("files", []):
        path = root / str(item["path"])
        if not path.is_file():
            return "FAIL"
        if path.stat().st_size != int(item["size"]):
            return "FAIL"
        if hashlib.sha256(path.read_bytes()).hexdigest().upper() != item["sha256"]:
            return "FAIL"
    return "PASS"


def _run_focused(python_executable: Path, source_root: Path) -> dict[str, object]:
    command = (
        str(python_executable),
        "-B",
        "-m",
        "unittest",
        *FOCUSED_MODULES,
    )
    completed = subprocess.run(
        command,
        cwd=source_root,
        capture_output=True,
        text=True,
        timeout=900,
    )
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returnCode": completed.returncode,
        "command": list(command),
        "stdoutTail": completed.stdout[-4000:],
        "stderrTail": completed.stderr[-4000:],
    }


def _secret_scan(root: Path) -> dict[str, object]:
    findings: list[dict[str, str]] = []
    patterns = (
        ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
        ("ALPACA_KEY", re.compile(r"\bPK[A-Z0-9]{18,}\b")),
        ("BEARER_TOKEN", re.compile(r"\bBearer\s+[A-Za-z0-9._~-]{24,}")),
        (
            "TOKEN_VALUE",
            re.compile(
                r'"(?:access_token|refresh_token|client_secret|secret_key)"\s*:\s*"(?!<|REDACTED|null)[^"\s]{16,}"',
                re.IGNORECASE,
            ),
        ),
        (
            "CREDENTIAL_ASSIGNMENT",
            re.compile(
                r"\b(?:access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|secret[_ -]?key)"
                r"\b\s*(?:=|:)\s*[\"']?(?!<|REDACTED|null)[A-Za-z0-9._~+/=-]{16,}",
                re.IGNORECASE,
            ),
        ),
    )
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.suffix.lower() not in {".py", ".json", ".md", ".txt", ".csv"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for name, pattern in patterns:
            if name == "CREDENTIAL_ASSIGNMENT" and path.suffix.lower() == ".py":
                continue
            if pattern.search(text):
                findings.append(
                    {"path": path.relative_to(root).as_posix(), "pattern": name}
                )
    return {"status": "PASS" if not findings else "FAIL", "findings": findings}


def _sanitized_message(message: str, expected_ending: str) -> str:
    value = str(message)
    if expected_ending:
        value = value.replace(expected_ending, "<REDACTED_ENDING>")
    value = re.sub(r"\bPK[A-Z0-9]{18,}\b", "<REDACTED_KEY>", value)
    value = re.sub(
        r"\b(Bearer)\s+[A-Za-z0-9._~-]{16,}",
        r"\1 <REDACTED_TOKEN>",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|secret[_ -]?key)"
        r"(\s*(?:=|:)\s*)[\"']?[^\s,\"']{16,}",
        r"\1\2<REDACTED_CREDENTIAL>",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b[A-Fa-f0-9]{48,}\b", "<REDACTED_HEX>", value)
    return value[:2000]


def _assert_regular_session(now: datetime | None = None) -> str:
    observed = now or datetime.now(EASTERN)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise StatDataCanaryError("Canary launch timestamp must be timezone-aware.")
    eastern = observed.astimezone(EASTERN)
    if eastern.weekday() > 4 or not (
        REGULAR_OPEN <= eastern.time().replace(tzinfo=None) < REGULAR_CLOSE
    ):
        raise StatDataCanaryError(
            "Live prospective canary may run only during the regular session."
        )
    return eastern.isoformat()


def _offline_runtime_rehearsal(evidence_root: Path) -> dict[str, object]:
    started = datetime.now().astimezone()
    config = ContinuousRuntimeConfig(
        runtime_identity="stat-data-002c-offline-runtime",
        session_date=started.astimezone(EASTERN).date().isoformat(),
        cadence=RuntimeCadence(
            broad_discovery_seconds=300,
            housekeeping_seconds=30,
            discovery_stale_seconds=600,
            composition_stale_seconds=180,
        ),
        queues=QueueCapacities(),
        lease_ttl_seconds=30,
        shutdown_timeout_seconds=2,
    )
    sources = {
        "discovery": object(),
        "market": object(),
        "events": object(),
        "composition": object(),
        "denominator": object(),
    }

    runtime_root = _new_ephemeral_runtime_root()
    runtime_root.mkdir(parents=True)
    topology = build_continuous_writer_topology_v2(
        root_path=runtime_root / "writer",
        evidence_program_id="stat-data-002c-offline-rehearsal",
        configuration_fingerprint=config.fingerprint,
        runtime_build_hash="b" * 64,
    )
    leases = LogicalRuntimeLeaseRegistry()
    resources = _acquire_qualification_resources(
        root=runtime_root,
        topology=topology,
        runtime_id="stat-data-002c-offline-instance",
        config=config,
        leases=leases,
        launch_at=started,
        **sources,
    )
    try:
        resources.shutdown_current(started + timedelta(seconds=1))
        restored = ContinuousOpportunityRuntime.restore(
            config=config,
            runtime_instance_id="stat-data-002c-offline-instance",
            now=started + timedelta(seconds=2),
            discovery_source=sources["discovery"],
            market_data_source=sources["market"],
            event_source=sources["events"],
            composition_source=sources["composition"],
            denominator_source=sources["denominator"],
            writer=resources.client,
            lease_registry=leases,
            checkpoint_store=resources.checkpoints,
        )
        resources.replace_runtime(restored)
        resources.shutdown_current(started + timedelta(seconds=3))
    finally:
        resources.close()
        _write_once(
            runtime_root / "resource-cleanup.json",
            _resource_cleanup_receipt(resources.audit),
        )
    successful_export = _export_ephemeral_runtime(
        runtime_root=runtime_root,
        evidence_root=evidence_root,
        export_name="offline-runtime-forensic",
    )

    failure_root = _new_ephemeral_runtime_root()
    failure_root.mkdir(parents=True)
    failure_topology = build_continuous_writer_topology_v2(
        root_path=failure_root / "writer",
        evidence_program_id="stat-data-002c-offline-init-failure",
        configuration_fingerprint=config.fingerprint,
        runtime_build_hash="c" * 64,
    )

    def fail_checkpoint(_root: Path):
        raise RuntimeError("injected checkpoint initialization failure")

    failure_class = None
    try:
        _acquire_qualification_resources(
            root=failure_root,
            topology=failure_topology,
            runtime_id="stat-data-002c-offline-failure-instance",
            config=config,
            leases=LogicalRuntimeLeaseRegistry(),
            launch_at=started,
            checkpoint_store_factory=fail_checkpoint,
            **sources,
        )
    except RuntimeError as exc:
        failure_class = type(exc).__name__
    failure_export = _export_ephemeral_runtime(
        runtime_root=failure_root,
        evidence_root=evidence_root,
        export_name="offline-init-failure-forensic",
    )
    result: dict[str, object] = {
        "status": (
            "PASS"
            if successful_export["status"] == "PASS"
            and failure_export["status"] == "PASS"
            and failure_class == "RuntimeError"
            else "FAIL"
        ),
        "runtimeCheckpointUnderTemp": True,
        "restartRestoreExercised": True,
        "normalResourceCleanup": successful_export,
        "initializationFailureClass": failure_class,
        "initializationFailureCleanup": failure_export,
        "durableCheckpointAuthorityCreated": False,
        "forensicCopiesUsedAsRuntimeAuthority": False,
    }
    result["fingerprint"] = _fingerprint("stat-data-002c-offline-rehearsal-v1", result)
    _write_once(evidence_root / "offline-runtime-rehearsal.json", result)
    return result


def rehearse(
    *,
    task_root: Path,
    production_root: Path,
    evidence_root: Path,
    session_date: str,
    duration_seconds: int,
    discovery_cadence_seconds: int,
    python_executable: Path,
    preserved_failed_activation: Path,
) -> dict[str, object]:
    prepare(
        task_root=task_root,
        production_root=production_root,
        evidence_root=evidence_root,
        session_date=session_date,
        duration_seconds=duration_seconds,
        discovery_cadence_seconds=discovery_cadence_seconds,
        require_schwab_preflight=False,
    )
    activation = load_activation_record(evidence_root / "activation.json")
    ProspectiveDenominatorStore(
        evidence_root / "prospective-denominator",
        activation=activation,
    )
    runtime_rehearsal = _offline_runtime_rehearsal(evidence_root)
    preserved_payload = json.loads(preserved_failed_activation.read_text(encoding="ascii"))[
        "payload"
    ]
    preserved = load_activation_record(preserved_failed_activation)
    preserved_proof = {
        "status": "PASS",
        "sourcePath": str(preserved_failed_activation),
        "activationIdPreserved": preserved.activation_id
        == preserved_payload["activation_id"],
        "activationFingerprintPreserved": preserved.fingerprint
        == preserved_payload["fingerprint"],
        "populationDefinitionsCanonicalTuple": isinstance(
            preserved.population_definitions, tuple
        ),
    }
    if not all(
        value is True
        for key, value in preserved_proof.items()
        if key not in {"status", "sourcePath"}
    ):
        preserved_proof["status"] = "FAIL"
    _write_once(evidence_root / "preserved-activation-reload-proof.json", preserved_proof)
    terminal = execute(
        task_root=task_root,
        production_root=production_root,
        evidence_root=evidence_root,
        expected_account_ending="",
    )
    verification = verify(evidence_root)
    package_result = package(
        task_root=task_root,
        evidence_root=evidence_root,
        python_executable=python_executable,
    )
    status = (
        "PASS"
        if preserved_proof["status"] == "PASS"
        and runtime_rehearsal["status"] == "PASS"
        and terminal["status"] == "FAIL"
        and terminal["failureStage"] == "VALIDATE_MARKET_DATA_IDENTITY"
        and terminal["providerContact"] is False
        and verification["status"] == "FAIL"
        and package_result["status"] == "PASS"
        else "FAIL"
    )
    return {
        "status": status,
        "activationId": activation.activation_id,
        "activationFingerprint": activation.fingerprint,
        "terminal": terminal,
        "verification": verification,
        "preservedActivationReload": preserved_proof,
        "runtimeRehearsal": runtime_rehearsal,
        "package": package_result,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "schwab-preflight",
            "prepare",
            "execute",
            "verify",
            "package",
            "run-all",
            "rehearse",
        ),
    )
    parser.add_argument("--task-root", type=Path, required=True)
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--session-date")
    parser.add_argument("--duration-seconds", type=int, default=1800)
    parser.add_argument("--discovery-cadence-seconds", type=int, default=300)
    parser.add_argument("--python-executable", type=Path, required=True)
    parser.add_argument("--preserved-failed-activation", type=Path)
    parser.add_argument("--preserved-provider-package", type=Path)
    parser.add_argument("--schwab-preflight-proof", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    ending = os.environ.get("MH_CANARY_EXPECTED_ACCOUNT_ENDING", "")
    if args.action == "schwab-preflight":
        result = run_schwab_preflight(
            task_root=args.task_root,
            production_root=args.production_root,
            evidence_root=args.evidence_root,
            expected_account_ending=ending,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    if args.action == "rehearse":
        if not args.session_date or args.preserved_failed_activation is None:
            raise SystemExit(
                "--session-date and --preserved-failed-activation are required for rehearsal"
            )
        result = rehearse(
            task_root=args.task_root,
            production_root=args.production_root,
            evidence_root=args.evidence_root,
            session_date=args.session_date,
            duration_seconds=args.duration_seconds,
            discovery_cadence_seconds=args.discovery_cadence_seconds,
            python_executable=args.python_executable,
            preserved_failed_activation=args.preserved_failed_activation,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    terminal_result: dict[str, object] | None = None
    verification_result: dict[str, object] | None = None
    verification_error: dict[str, object] | None = None
    package_result: dict[str, object] | None = None
    if args.action in {"prepare", "run-all"}:
        if not args.session_date:
            raise SystemExit("--session-date is required for preparation")
        replay_requested = args.preserved_provider_package is not None
        prepare(
            task_root=args.task_root,
            production_root=args.production_root,
            evidence_root=args.evidence_root,
            session_date=args.session_date,
            duration_seconds=args.duration_seconds,
            discovery_cadence_seconds=args.discovery_cadence_seconds,
            schwab_preflight_proof=args.schwab_preflight_proof,
            require_schwab_preflight=not replay_requested,
            preserved_provider_package=args.preserved_provider_package,
        )
        if args.action == "run-all":
            _write_once(
                args.evidence_root / "exact-run-all-invocation.json",
                {
                    "action": "run-all",
                    "taskRoot": str(args.task_root.resolve()),
                    "productionRoot": str(args.production_root.resolve()),
                    "evidenceRoot": str(args.evidence_root.resolve()),
                    "sessionDate": args.session_date,
                    "durationSeconds": args.duration_seconds,
                    "discoveryCadenceSeconds": args.discovery_cadence_seconds,
                    "pythonExecutable": str(args.python_executable.resolve()),
                    "providerMode": (
                        PRESERVED_PROVIDER_REPLAY
                        if replay_requested
                        else "LIVE_PROVIDER"
                    ),
                    "preservedProviderPackage": (
                        str(args.preserved_provider_package.resolve())
                        if replay_requested
                        else None
                    ),
                    "schwabPreflightProof": (
                        str(args.schwab_preflight_proof.resolve())
                        if args.schwab_preflight_proof is not None
                        else None
                    ),
                    "accountIdentitySupplied": bool(ending),
                    "newProspectiveLiveEvidence": not replay_requested,
                    "authority": AUTHORITY,
                    "executionAuthority": EXECUTION_AUTHORITY,
                },
            )
    if args.action in {"execute", "run-all"}:
        terminal_result = execute(
            task_root=args.task_root,
            production_root=args.production_root,
            evidence_root=args.evidence_root,
            expected_account_ending=ending,
        )
    if args.action in {"verify", "run-all"}:
        try:
            verification_result = verify(args.evidence_root)
        except Exception as exc:
            if args.action != "run-all":
                raise
            verification_error = {
                "status": "FAIL",
                "exceptionClass": type(exc).__name__,
                "exceptionMessage": _sanitized_message(str(exc), ending),
                "recordedAt": datetime.now().astimezone().isoformat(),
                "authority": AUTHORITY,
                "executionAuthority": EXECUTION_AUTHORITY,
            }
            verification_error["fingerprint"] = _fingerprint(
                "stat-data-002-verification-failure-v1",
                verification_error,
            )
            _write_once(
                args.evidence_root / "verification-failure.json",
                verification_error,
            )
    if args.action in {"package", "run-all"}:
        package_result = package(
            task_root=args.task_root,
            evidence_root=args.evidence_root,
            python_executable=args.python_executable,
        )
    results = {
        "terminal": terminal_result,
        "verification": verification_result,
        "verificationError": verification_error,
        "package": package_result,
    }
    selected = [item for item in results.values() if item is not None]
    if selected:
        print(json.dumps(results, indent=2, sort_keys=True))
    return 0 if all(item.get("status") == "PASS" for item in selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
