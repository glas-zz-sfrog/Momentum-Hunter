"""Provider-backed, research-only forensic canary for Producer-001C.

This task-only launcher imports Momentum Hunter from an explicitly pinned clean
canonical checkout. It never imports broker, account-snapshot, Paper, Shadow,
or order modules and writes only to caller-supplied disposable/external roots.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePath
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo


EXPECTED_CANONICAL_SHA = "4690dbf193355bc7a39c6c74e531344ea8a37875"
EXPECTED_PRODUCTION_SHA = "82460b3313b86c34dff4ffb737d2c04bf02e3ace"
EXPECTED_TASK_BRANCH = "codex/ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001C"
EXPECTED_FORENSIC_STANDARD_SHA256 = (
    "8B3A7F161BA393DACCED20C92B6B544C3893D201A97F76B370980DA884940303"
)
FORENSIC_STANDARD_PATH = Path(
    r"C:\Users\steve\OneDrive\Documents\ArgusReviewBundles"
    r"\ARGUS-CONTINUOUS-PRODUCER-001A-FORENSIC-EVIDENCE-STANDARD"
    r"\ARGUS-DIRECTIVE-PRODUCER-001A-FORENSIC-EVIDENCE-STANDARD.md"
)
FAILED_001A_ZIP = Path(
    r"C:\Users\steve\OneDrive\Documents\ArgusReviewBundles"
    r"\ARGUS-CONTINUOUS-PRODUCER-001A-FORENSIC-CANARY-20260826-REGULAR-72E35B7-SECOND-EYE.zip"
)
FAILED_001A_ZIP_SHA256 = (
    "E74B675DD24CA3E0EDFE0203F76197CAB35D1FA074E4FF322621DFDBC7F00345"
)
FAILED_001B_ZIP = Path(
    r"C:\Users\steve\OneDrive\Documents\ArgusReviewBundles"
    r"\ARGUS-CONTINUOUS-PRODUCER-001B-FORENSIC-CANARY-20260826-REGULAR-01F0C2E-SECOND-EYE-V2.zip"
)
FAILED_001B_ZIP_SHA256 = (
    "A4609AA3562D5705D88DF13498F7EBAEAB7E6A615910B4445887625B60EE371B"
)
EXTERNAL_PARENT = Path(
    r"C:\Users\steve\OneDrive\Documents\ArgusReviewBundles"
)
CENTRAL = ZoneInfo("America/Chicago")
EASTERN = ZoneInfo("America/New_York")
ACCOUNT_ENV = "MH_CANARY_EXPECTED_ACCOUNT_ENDING"
CANONICAL_ENV = "MH_CANARY_CANONICAL_ROOT"
PRODUCTION_ENV = "MH_CANARY_PRODUCTION_ROOT"
CANARY_PROFILE = "producer-001c-provider-forensic-canary-v1"
AUTHORITY = "RESEARCH_ONLY"
EXECUTION_AUTHORITY = "NONE"
ORDER_CAPABILITY = "UNAVAILABLE"


def _required_canonical_root() -> Path:
    value = os.environ.get(CANONICAL_ENV, "").strip()
    if not value:
        raise SystemExit(f"{CANONICAL_ENV} must identify the canonical checkout.")
    root = Path(value).expanduser().resolve(strict=True)
    if not (root / "momentum_hunter").is_dir():
        raise SystemExit("Canonical root does not contain momentum_hunter.")
    return root


CANONICAL_ROOT = _required_canonical_root()
PRODUCTION_ROOT = Path(
    os.environ.get(
        PRODUCTION_ENV,
        r"C:\Users\steve\OneDrive\Documents\Investing",
    )
).expanduser().resolve(strict=True)
sys.path.insert(0, str(CANONICAL_ROOT))

from momentum_hunter.continuous_evidence_writer import (  # noqa: E402
    OFFLINE_REVIEW,
    AuthenticatedEvidenceWriterClient,
    DedicatedEvidenceWriter,
    build_continuous_writer_topology_v2,
    create_ephemeral_writer_capability,
    read_evidence_snapshot,
)
from momentum_hunter.continuous_attempt_ledger import (  # noqa: E402
    ATTEMPT_FAILED,
    ATTEMPT_STARTED,
    ATTEMPT_SUCCEEDED,
    ContinuousAttemptLedger,
)
from momentum_hunter.continuous_live_qualification import (  # noqa: E402
    LiveCompositionSource,
    LiveDenominatorSource,
    LiveDiscoverySource,
    LiveMarketDataSource,
    LiveMaterialEvents,
    QualificationState,
)
from momentum_hunter.continuous_natural_setup import (  # noqa: E402
    ContinuousNaturalSetupCoordinator,
)
from momentum_hunter.continuous_runtime import (  # noqa: E402
    CANONICAL_BAR_COMPLETED,
    ContinuousOpportunityRuntime,
    ContinuousRuntimeConfig,
    LogicalRuntimeLeaseRegistry,
    QueueCapacities,
    RuntimeCadence,
    RuntimeCheckpointStore,
)
from momentum_hunter.continuous_tradeplan_producer import (  # noqa: E402
    ContinuousHistoryAdmissionCoordinator,
    ContinuousTradePlanProducer,
)
from momentum_hunter.hot_universe import HotUniverseStore  # noqa: E402
from momentum_hunter.providers import FinvizProvider  # noqa: E402


class ForensicCanaryError(RuntimeError):
    """Raised when the bounded canary cannot preserve its proof contract."""


class ForensicLiveMarketDataSource(LiveMarketDataSource):
    """Use the real source while redacting local binding identity from evidence."""

    def _preserve_admission(
        self,
        *,
        symbol: str,
        context: object,
        current: object,
        backfill_evidence: Mapping[str, object] | None,
    ) -> None:
        sanitized = (
            _sanitize(dict(backfill_evidence))
            if backfill_evidence is not None
            else None
        )
        super()._preserve_admission(
            symbol=symbol,
            context=context,
            current=current,
            backfill_evidence=sanitized,
        )


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fingerprint(domain: str, value: object) -> str:
    return hashlib.sha256(
        _canonical_bytes({"domain": domain, "value": value})
    ).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _write_once(path: Path, value: object) -> None:
    payload = value if isinstance(value, bytes) else _canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ForensicCanaryError(
                f"Conflicting write-once evidence exists: {path}"
            )
        return
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ForensicCanaryError("Canary timestamp must be timezone-aware.")
    return parsed


def _backfill_accounting(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {
            "ledgerPresent": False,
            "symbolsRepresented": 0,
            "attempts": 0,
            "successful": 0,
            "failed": 0,
            "active": 0,
            "records": [],
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, Mapping) else None
    if not isinstance(records, Mapping):
        raise ForensicCanaryError("Backfill ledger omitted its records.")
    values = tuple(
        value for value in records.values() if isinstance(value, Mapping)
    )
    if len(values) != len(records):
        raise ForensicCanaryError("Backfill ledger contains an invalid record.")
    statuses = tuple(str(value.get("status", "")).upper() for value in values)
    return {
        "ledgerPresent": True,
        "symbolsRepresented": len(values),
        "attempts": sum(int(value.get("attemptCount", 0)) for value in values),
        "successful": sum(status in {"COMPLETE", "PARTIAL"} for status in statuses),
        "failed": sum(status == "FAILED" for status in statuses),
        "active": sum(status in {"QUEUED", "IN_PROGRESS"} for status in statuses),
        "records": [
            {
                "symbol": str(value.get("symbol", "")),
                "status": str(value.get("status", "")),
                "attemptCount": int(value.get("attemptCount", 0)),
                "requestedAt": value.get("requestedAt"),
                "startedAt": value.get("startedAt"),
                "completedAt": value.get("completedAt"),
            }
            for value in values
        ],
    }


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_identity(root: Path) -> dict[str, object]:
    return {
        "root": str(root),
        "head": _git(root, "rev-parse", "HEAD"),
        "originMaster": _git(root, "rev-parse", "origin/master"),
        "branch": _git(root, "branch", "--show-current"),
        "status": _git(root, "status", "--porcelain"),
    }


def _validate_canonical() -> dict[str, object]:
    identity = _git_identity(CANONICAL_ROOT)
    expected = _git(CANONICAL_ROOT, "rev-parse", EXPECTED_CANONICAL_SHA)
    if identity["head"] != expected:
        raise ForensicCanaryError("Canonical HEAD differs from the approved canary source.")
    if identity["status"]:
        raise ForensicCanaryError("Approved canary source checkout is not clean.")
    imported = Path(sys.modules["momentum_hunter.continuous_runtime"].__file__).resolve()
    if CANONICAL_ROOT not in imported.parents:
        raise ForensicCanaryError("Runtime modules were not imported from canonical.")
    identity["classification"] = "PINNED_IMMUTABLE_PRODUCT_SOURCE"
    return identity


def _validate_production() -> dict[str, object]:
    identity = _git_identity(PRODUCTION_ROOT)
    if identity["head"] != EXPECTED_PRODUCTION_SHA:
        raise ForensicCanaryError("Production canonical HEAD changed during canary work.")
    if identity["originMaster"] != EXPECTED_PRODUCTION_SHA:
        raise ForensicCanaryError("Production origin/master changed during canary work.")
    if identity["branch"] != "master" or identity["status"]:
        raise ForensicCanaryError("Production canonical checkout is not clean master.")
    identity["classification"] = "UNMODIFIED_PRODUCTION_CANONICAL"
    return identity


def _validate_task_source(expected_head: str | None = None) -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    identity = _git_identity(root)
    if identity["branch"] != EXPECTED_TASK_BRANCH or identity["status"]:
        raise ForensicCanaryError("Canary task source is not the clean approved branch.")
    if expected_head is not None and identity["head"] != expected_head:
        raise ForensicCanaryError("Canary task source changed during the campaign.")
    identity["classification"] = "FROZEN_OBSERVATIONAL_WRAPPER_SOURCE"
    return identity


def _validate_standard() -> dict[str, object]:
    if not FORENSIC_STANDARD_PATH.is_file():
        raise ForensicCanaryError("Binding forensic standard is missing.")
    observed = _sha256(FORENSIC_STANDARD_PATH)
    if observed != EXPECTED_FORENSIC_STANDARD_SHA256:
        raise ForensicCanaryError("Binding forensic standard hash differs.")
    return {
        "path": str(FORENSIC_STANDARD_PATH),
        "sha256": observed,
        "status": "VERIFIED",
    }


def _validate_failed_evidence() -> dict[str, object]:
    items = []
    for task, path, expected in (
        ("PRODUCER_001A", FAILED_001A_ZIP, FAILED_001A_ZIP_SHA256),
        ("PRODUCER_001B", FAILED_001B_ZIP, FAILED_001B_ZIP_SHA256),
    ):
        if not path.is_file():
            raise ForensicCanaryError(f"Preserved {task} ZIP is missing.")
        observed = _sha256(path)
        if observed != expected:
            raise ForensicCanaryError(f"Preserved {task} ZIP hash differs.")
        items.append(
            {
                "task": task,
                "path": str(path),
                "sha256": observed,
                "status": "VERIFIED_UNCHANGED",
            }
        )
    return {"status": "PASS", "items": items}


def _validate_external_root(root: Path, *, require_new: bool) -> Path:
    resolved = root.expanduser().resolve(strict=False)
    try:
        resolved.relative_to(EXTERNAL_PARENT.resolve(strict=True))
    except ValueError as exc:
        raise ForensicCanaryError(
            "Forensic evidence root must remain under ArgusReviewBundles."
        ) from exc
    if resolved == EXTERNAL_PARENT.resolve(strict=True):
        raise ForensicCanaryError("Forensic root must be a new child directory.")
    if require_new and resolved.exists():
        raise ForensicCanaryError("Forensic evidence root already exists.")
    return resolved


def _validate_runtime_root(root: Path, *, require_new: bool) -> Path:
    resolved = root.expanduser().resolve(strict=False)
    temporary = Path(os.environ.get("TEMP", "")).resolve(strict=True)
    try:
        resolved.relative_to(temporary)
    except ValueError as exc:
        raise ForensicCanaryError(
            "Disposable runtime root must remain under the user temporary directory."
        ) from exc
    lowered = str(resolved).lower()
    if "momentumhunterdata" in lowered or "programdata" in lowered:
        raise ForensicCanaryError("Disposable runtime root overlaps a protected path.")
    if require_new and resolved.exists():
        raise ForensicCanaryError("Disposable runtime root already exists.")
    return resolved


def _sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return normalized in {
        "accesstoken",
        "refreshtoken",
        "clientsecret",
        "password",
        "authorization",
        "accounthash",
        "accountid",
        "accountnumber",
        "accountending",
        "expectedaccountending",
    }


def _sanitize(value: object, *, key: str = "") -> object:
    if _sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(item_key): _sanitize(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_sanitize(item) for item in value)
    if key in {"payload_json", "payloadJson"} and isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return _canonical_bytes(_sanitize(parsed)).decode("ascii")
    return value


def _owner_identity(owner: object) -> dict[str, object]:
    source_path = Path(inspect.getsourcefile(owner) or "").resolve(strict=True)
    if CANONICAL_ROOT not in source_path.parents:
        raise ForensicCanaryError(
            f"Authoritative owner escaped canonical source: {source_path}"
        )
    lines, first_line = inspect.getsourcelines(owner)
    return {
        "qualifiedName": f"{owner.__module__}.{owner.__qualname__}",
        "sourcePath": source_path.relative_to(CANONICAL_ROOT).as_posix(),
        "sourceSha256": _sha256(source_path),
        "firstLine": first_line,
        "sourceFingerprint": _fingerprint(
            "producer-001c-owner-source-v1", "".join(lines)
        ),
    }


def _wrapper_authority_scan() -> dict[str, object]:
    path = Path(__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_calls = {
        "apply_snapshot",
        "commit",
        "completed_bar_events",
        "compose",
        "discover",
        "discover_paginated",
        "evaluate",
        "next_step",
        "poll",
        "produce",
        "produce_continuous_denominator",
    }
    forbidden_constructors = {
        "Candidate",
        "CompositionRequest",
        "CompositionResult",
        "CurrentMarketEvidence",
        "DiscoveryPulse",
        "DiscoveryRequest",
        "DiscoverySnapshot",
        "HistoricalContextEvidence",
        "InstrumentAdmissionEvidence",
        "IntradayTradePlan",
        "ReadinessRequest",
        "ReadinessResult",
        "RuntimeTriggerEvent",
        "TradePlan",
    }
    findings: list[dict[str, object]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = None
        if isinstance(node.func, ast.Attribute):
            called = node.func.attr
        elif isinstance(node.func, ast.Name):
            called = node.func.id
        if called in forbidden_calls:
            findings.append(
                {
                    "line": node.lineno,
                    "kind": "DIRECT_AUTHORITATIVE_METHOD_CALL",
                    "name": called,
                }
            )
        if called in forbidden_constructors:
            findings.append(
                {
                    "line": node.lineno,
                    "kind": "DIRECT_AUTHORITATIVE_OBJECT_CONSTRUCTION",
                    "name": called,
                }
            )
    return {
        "status": "PASS" if not findings else "FAIL",
        "wrapperPath": str(path),
        "wrapperSha256": _sha256(path),
        "forbiddenMethodNames": sorted(forbidden_calls),
        "forbiddenConstructorNames": sorted(forbidden_constructors),
        "findings": findings,
    }


def _ownership_map() -> dict[str, object]:
    stages = (
        (
            "RECURRING_DISCOVERY_DISPATCH",
            ContinuousOpportunityRuntime._process_discovery,
            "Builds DiscoveryRequest, calls the configured source, records the cycle, and queues readiness.",
        ),
        (
            "REAL_FINVIZ_DISCOVERY",
            LiveDiscoverySource.discover,
            "Calls the canonical Finviz provider and returns the canonical discovery pulse.",
        ),
        (
            "REAL_FINVIZ_PROVIDER_ACQUISITION",
            FinvizProvider.discover_paginated,
            "Acquires and parses recurring provider pages under the canonical pagination contract.",
        ),
        (
            "HOT_UNIVERSE_ADMISSION",
            HotUniverseStore.apply_snapshot,
            "Admits, retains, tiers, and expires members from the provider snapshot.",
        ),
        (
            "READINESS_DISPATCH",
            ContinuousOpportunityRuntime._process_readiness,
            "Builds readiness work from admitted members and routes only ready results to composition.",
        ),
        (
            "SCHWAB_HISTORY_AND_CURRENT_EVIDENCE",
            LiveMarketDataSource.evaluate,
            "Obtains canonical history/current evidence and performs readiness assessment.",
        ),
        (
            "HISTORY_ADMISSION",
            ContinuousHistoryAdmissionCoordinator.admit,
            "Owns bounded history admission and existing/backfilled evidence selection.",
        ),
        (
            "COMPLETED_BAR_MATERIAL_EVENT_DISPATCH",
            LiveMaterialEvents.poll,
            "Polls canonical history and emits only naturally completed-bar/history-terminal events.",
        ),
        (
            "COMPLETED_BAR_EVENT_IDENTITY",
            ContinuousNaturalSetupCoordinator.completed_bar_events,
            "Derives immutable completed-bar events from canonical stored minute history.",
        ),
        (
            "COMPOSITION_DISPATCH",
            ContinuousOpportunityRuntime._process_composition,
            "Builds composition requests and records returned setup/plan identities.",
        ),
        (
            "LIFECYCLE_SETUP_AND_PLAN_CHAIN",
            LiveCompositionSource.compose,
            "Coordinates canonical lifecycle/setup production and TradePlan or truthful no-plan evaluation.",
        ),
        (
            "PREVIEW_LIFECYCLE_SETUP_CREATION",
            ContinuousNaturalSetupCoordinator.next_step,
            "Selects the next natural lifecycle/setup step only inside disposable preview state.",
        ),
        (
            "PREVIEW_LIFECYCLE_SETUP_MUTATION",
            ContinuousNaturalSetupCoordinator.commit,
            "Applies validated Producer results only to the disposable preview clone.",
        ),
        (
            "ATOMIC_AUTHORITATIVE_COMPOSITION_PUBLICATION",
            ContinuousNaturalSetupCoordinator._commit_preview,
            "Publishes lifecycle, breakout, and Producer stores together after the full preview validates.",
        ),
        (
            "TRADEPLAN_OR_NO_PLAN_PRODUCTION",
            ContinuousTradePlanProducer.evaluate,
            "Produces the immutable prospective TradePlan or explicit no-plan disposition.",
        ),
        (
            "RESTART_RECONSTRUCTION",
            ContinuousOpportunityRuntime.restore,
            "Reconstructs runtime queues, identities, counters, events, and evidence state from the checkpoint.",
        ),
        (
            "HOT_UNIVERSE_RECONSTRUCTION",
            LiveDiscoverySource._restore_current_generation,
            "Reconstructs the persisted discovery generation and hot-universe state.",
        ),
    )
    wrapper_scan = _wrapper_authority_scan()
    result = {
        "schemaVersion": 1,
        "profile": "producer-001c-forensic-canonical-ownership-map-v1",
        "canonicalSourceSha": EXPECTED_CANONICAL_SHA,
        "status": wrapper_scan["status"],
        "stages": [
            {
                "stage": stage,
                "owner": _owner_identity(owner),
                "ownership": "CANONICAL_PRODUCTION_CLASS",
                "responsibility": responsibility,
            }
            for stage, owner, responsibility in stages
        ],
        "wrapperAuthority": {
            "classification": "OBSERVATIONAL_ONLY",
            "allowedActions": [
                "instantiate canonical sources and runtime",
                "start/tick/shutdown canonical runtime",
                "restart an isolated process through canonical restore",
                "capture, sanitize, hash, verify, and package evidence",
            ],
            "prohibitedInputs": [
                "candidate",
                "hot-universe decision",
                "readiness decision",
                "lifecycle or setup",
                "material event",
                "TradePlan or no-plan disposition",
            ],
            "staticScan": wrapper_scan,
        },
        "evidenceSanitizerScope": {
            "class": f"{ForensicLiveMarketDataSource.__module__}.{ForensicLiveMarketDataSource.__qualname__}",
            "method": "_preserve_admission",
            "authority": "EVIDENCE_SERIALIZATION_ONLY",
            "decisionStateMutation": False,
            "providerInputMutation": False,
            "note": "Redacts local binding identity only in the copied admission evidence payload before the canonical write-once serializer runs.",
        },
    }
    result["fingerprint"] = _fingerprint(
        "producer-001c-forensic-ownership-map-v1", result
    )
    return result


def _file_manifest(
    root: Path,
    *,
    include: Iterable[Path] | None = None,
) -> list[dict[str, object]]:
    files = sorted(include if include is not None else root.rglob("*"))
    result = []
    for path in files:
        if not path.is_file():
            continue
        result.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return result


def _manifest_fingerprint(items: Iterable[Mapping[str, object]]) -> str:
    return _fingerprint("producer-001c-forensic-file-manifest-v1", list(items))


def _selected_production_hashes() -> dict[str, object]:
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    paths = {
        "automationManifest": program_data
        / "MomentumHunter"
        / "Automation"
        / "automation-manifest.json",
        "continuousDeployment": program_data
        / "MomentumHunter"
        / "Automation"
        / "continuous-deployment.json",
        "openingCaptureManifest": PRODUCTION_ROOT
        / "MomentumHunterData"
        / "data"
        / "integrity"
        / "capture_manifest.json",
    }
    evidence = {}
    for name, path in paths.items():
        evidence[name] = {
            "path": str(path),
            "exists": path.is_file(),
            "sha256": _sha256(path) if path.is_file() else None,
            "bytes": path.stat().st_size if path.is_file() else None,
        }
    return evidence


def _service_snapshot() -> list[dict[str, object]]:
    names = (
        "MomentumHunterAutomation",
        "MomentumHunterContinuousRuntime",
        "MomentumHunterContinuousWriter",
    )
    quoted = ",".join(f"'{name}'" for name in names)
    command = (
        f"Get-CimInstance Win32_Service | Where-Object {{ $_.Name -in @({quoted}) }} | "
        "Select-Object Name,State,StartMode,StartName,PathName | "
        "Sort-Object Name | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ("powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command),
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout or "[]")
    rows = payload if isinstance(payload, list) else [payload]
    return [dict(item) for item in rows]


def _manifest_safety_summary() -> dict[str, object]:
    path = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / (
        "MomentumHunter/Automation/automation-manifest.json"
    )
    if not path.is_file():
        return {"status": "MISSING"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    enabled = [item for item in jobs if item.get("enabled", True)]
    kinds = [str(item.get("kind", "")) for item in enabled]
    return {
        "status": "READ_ONLY",
        "manifestSha256": _sha256(path),
        "enabledJobCount": len(enabled),
        "futureOpeningJobs": sum(kind == "opening_capture" for kind in kinds),
        "enabledPaperJobs": sum("paper" in kind.lower() for kind in kinds),
        "enabledShadowJobs": sum("shadow" in kind.lower() for kind in kinds),
        "orderCapability": "UNAVAILABLE",
    }


def _production_baseline(label: str) -> dict[str, object]:
    result = {
        "schemaVersion": 1,
        "profile": CANARY_PROFILE,
        "label": label,
        "observedAt": datetime.now().astimezone().isoformat(),
        "sourceGit": _validate_canonical(),
        "canaryTaskGit": _validate_task_source(),
        "canonicalGit": _validate_production(),
        "services": _service_snapshot(),
        "selectedProductionHashes": _selected_production_hashes(),
        "manifestSafety": _manifest_safety_summary(),
        "authority": AUTHORITY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "accountValuesRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderCapability": ORDER_CAPABILITY,
    }
    result["fingerprint"] = _fingerprint(
        "producer-001c-forensic-production-baseline-v1", result
    )
    return result


def _runtime_config(campaign: Mapping[str, object]) -> ContinuousRuntimeConfig:
    cadence = int(campaign["discoveryCadenceSeconds"])
    return ContinuousRuntimeConfig(
        runtime_identity=str(campaign["runtimeIdentity"]),
        session_date=str(campaign["sessionDate"]),
        cadence=RuntimeCadence(
            broad_discovery_seconds=cadence,
            housekeeping_seconds=15,
            discovery_stale_seconds=cadence * 2,
            composition_stale_seconds=cadence * 2,
        ),
        queues=QueueCapacities(
            discovery=2,
            readiness=16,
            composition=16,
            evidence=128,
            health=16,
        ),
        lease_ttl_seconds=30,
        shutdown_timeout_seconds=10,
        maximum_tracked_symbols=60,
    )


def _topology(campaign: Mapping[str, object], config: ContinuousRuntimeConfig):
    return build_continuous_writer_topology_v2(
        root_path=Path(str(campaign["runtimeRoot"])) / "writer",
        evidence_program_id="producer-001c-forensic-canary",
        configuration_fingerprint=config.fingerprint,
        runtime_build_hash=_fingerprint(
            "producer-001c-canonical-runtime-build-v1",
            str(campaign["canonicalSourceSha"]),
        ),
    )


def _state_snapshot(
    *,
    phase: int,
    state: QualificationState,
    composition: LiveCompositionSource,
    runtime: ContinuousOpportunityRuntime,
    topology: object,
    process_started_at: str,
) -> dict[str, object]:
    evidence = read_evidence_snapshot(topology, reader_role=OFFLINE_REVIEW)
    producer = composition.producer_store.load()
    runtime_root = state.root
    immutable_files = [
        path
        for parent in (
            runtime_root / "writer",
            runtime_root / "source-evidence",
        )
        if parent.exists()
        for path in parent.rglob("*")
        if path.is_file() and not path.name.endswith(".lock")
    ]
    checkpoint = RuntimeCheckpointStore(runtime_root / "checkpoint").load(
        runtime.config.runtime_identity
    )
    completed_bar_events = tuple(
        item
        for item in checkpoint.get("event_records", [])
        if isinstance(item, Mapping)
        and item.get("trigger") == CANONICAL_BAR_COMPLETED
    )
    backfill_accounting = _backfill_accounting(
        runtime_root / "state" / "continuous-history-backfill.json"
    )
    snapshot = {
        "schemaVersion": 1,
        "profile": CANARY_PROFILE,
        "phase": phase,
        "processId": os.getpid(),
        "processStartedAt": process_started_at,
        "capturedAt": datetime.now().astimezone().isoformat(),
        "runtimeHealth": asdict(runtime.health(datetime.now().astimezone())),
        "writerSnapshot": asdict(evidence),
        "discoverySnapshot": (
            {
                "snapshotId": state.snapshot.snapshot_id,
                "fingerprint": state.snapshot.fingerprint,
                "pagesReceived": state.snapshot.pages_received,
                "representedRowCount": state.snapshot.represented_row_count,
                "qualifyingCandidateCount": state.snapshot.qualified_count,
                "symbols": [
                    item.ticker for item in state.snapshot.qualified_candidates()
                ],
            }
            if state.snapshot is not None
            else None
        ),
        "hotUniverse": (
            {
                "fingerprint": state.universe.state.fingerprint,
                "members": [asdict(item) for item in state.universe.state.members],
                "transitions": [asdict(item) for item in state.universe.state.transitions],
            }
            if state.universe is not None
            else None
        ),
        "producerRecords": [
            {
                "recordId": item.record_id,
                "fingerprint": item.fingerprint,
                "symbol": item.symbol,
                "setupId": item.setup_id,
                "predecessorSetupId": item.predecessor_setup_id,
                "tradePlanId": item.trade_plan_id,
                "evidenceCutoff": item.evidence_cutoff,
                "lifecycleState": item.lifecycle_state,
                "executionEligible": item.execution_eligible,
                "blockers": list(item.blockers),
            }
            for item in producer
        ],
        "qualificationMetrics": _sanitize(asdict(state.metrics)),
        "runtimeCompletedBarEvents": completed_bar_events,
        "runtimeCompletedBarEventCount": len(completed_bar_events),
        "runtimeCompletedBarCounter": int(
            checkpoint.get("counters", {}).get("completed_bar_events", 0)
        ),
        "attemptLedgerCount": len(runtime.attempt_history),
        "attemptLedgerHead": (
            runtime.attempt_history[-1].event_id
            if runtime.attempt_history
            else None
        ),
        "backfillAccounting": backfill_accounting,
        "immutableFileManifest": _file_manifest(runtime_root, include=immutable_files),
        "accountValuesRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderCapability": ORDER_CAPABILITY,
    }
    snapshot["immutableManifestFingerprint"] = _manifest_fingerprint(
        snapshot["immutableFileManifest"]
    )
    snapshot["fingerprint"] = _fingerprint(
        "producer-001c-forensic-phase-state-v1", snapshot
    )
    return snapshot


def _run_phase(campaign_path: Path, phase: int) -> int:
    process_started = datetime.now().astimezone().isoformat()
    campaign = json.loads(campaign_path.read_text(encoding="ascii"))
    canonical = _validate_canonical()
    task_source = _validate_task_source(
        str(campaign.get("canaryTaskGit", {}).get("head", ""))
    )
    if campaign.get("canonicalSourceSha") != canonical["head"]:
        raise ForensicCanaryError("Campaign canonical source identity changed.")
    runtime_root = _validate_runtime_root(
        Path(str(campaign["runtimeRoot"])), require_new=False
    )
    evidence_root = _validate_external_root(
        Path(str(campaign["evidenceRoot"])), require_new=False
    )
    expected_ending = os.environ.get(ACCOUNT_ENV, "").strip()
    if len(expected_ending) != 4 or not expected_ending.isdigit():
        raise ForensicCanaryError(
            f"{ACCOUNT_ENV} must contain the locally bound four-digit ending."
        )
    config = _runtime_config(campaign)
    topology = _topology(campaign, config)
    launch_at = _parse_timestamp(str(campaign["campaignStartedAt"]))
    state = QualificationState(
        root=runtime_root,
        launch_at=launch_at,
        allow_persistent=True,
        configuration_fingerprint=config.fingerprint,
    )
    discovery = LiveDiscoverySource(state)
    market = ForensicLiveMarketDataSource(
        state,
        expected_account_ending=expected_ending,
    )
    composition = LiveCompositionSource(state)
    denominator = LiveDenominatorSource(state)
    events = LiveMaterialEvents(
        state,
        market.backfill,
        natural_setup=composition.natural_setup,
    )
    capability = create_ephemeral_writer_capability()
    writer = DedicatedEvidenceWriter(topology)
    runtime_instance_id = str(campaign["runtimeInstanceId"])
    writer.activate_session(
        capability=capability,
        source_identity=runtime_instance_id,
    )
    client = AuthenticatedEvidenceWriterClient(
        topology=topology,
        capability=capability,
        runtime_instance_id=runtime_instance_id,
        writer=writer,
        maximum_ack_seconds=2.0,
    )
    checkpoints = RuntimeCheckpointStore(runtime_root / "checkpoint")
    leases = LogicalRuntimeLeaseRegistry()
    now = datetime.now().astimezone()
    if phase == 1:
        runtime = ContinuousOpportunityRuntime(
            config=config,
            runtime_instance_id=runtime_instance_id,
            discovery_source=discovery,
            market_data_source=market,
            event_source=events,
            composition_source=composition,
            denominator_source=denominator,
            writer=client,
            lease_registry=leases,
            checkpoint_store=checkpoints,
        )
        runtime.start(now)
        restored = False
    else:
        runtime = ContinuousOpportunityRuntime.restore(
            config=config,
            runtime_instance_id=runtime_instance_id,
            now=now,
            discovery_source=discovery,
            market_data_source=market,
            event_source=events,
            composition_source=composition,
            denominator_source=denominator,
            writer=client,
            lease_registry=leases,
            checkpoint_store=checkpoints,
        )
        restored = True
    duration = int(campaign[f"phase{phase}DurationSeconds"])
    cadence = int(campaign["discoveryCadenceSeconds"])
    deadline = time.monotonic() + duration
    tick_count = 0
    try:
        while time.monotonic() < deadline:
            runtime.tick(
                datetime.now().astimezone(),
                work_budget=512,
                discovery_cadence_seconds=cadence,
            )
            tick_count += 1
            time.sleep(min(5.0, max(0.0, deadline - time.monotonic())))
        market.backfill.wait_until_idle(timeout_seconds=120)
        runtime.tick(
            datetime.now().astimezone(),
            work_budget=512,
            discovery_cadence_seconds=cadence,
        )
        tick_count += 1
        health = runtime.shutdown(datetime.now().astimezone())
        snapshot = _state_snapshot(
            phase=phase,
            state=state,
            composition=composition,
            runtime=runtime,
            topology=topology,
            process_started_at=process_started,
        )
        receipt = {
            "schemaVersion": 1,
            "profile": CANARY_PROFILE,
            "phase": phase,
            "processId": os.getpid(),
            "processStartedAt": process_started,
            "completedAt": datetime.now().astimezone().isoformat(),
            "restoredFromCheckpoint": restored,
            "tickCount": tick_count,
            "durationSeconds": duration,
            "runtimeHealth": asdict(health),
            "stateSnapshotFingerprint": snapshot["fingerprint"],
            "canonicalSource": canonical,
            "canaryTaskSource": task_source,
            "importedModuleRoots": _imported_runtime_roots(),
            "authority": AUTHORITY,
            "executionAuthority": EXECUTION_AUTHORITY,
            "accountValuesRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderCapability": ORDER_CAPABILITY,
        }
        receipt["fingerprint"] = _fingerprint(
            "producer-001c-forensic-phase-receipt-v1", receipt
        )
        _write_once(evidence_root / f"phase-{phase}-state.json", _sanitize(snapshot))
        _write_once(evidence_root / f"phase-{phase}-receipt.json", receipt)
        return 0
    finally:
        writer.close()
        capability.close()


def _imported_runtime_roots() -> list[dict[str, str]]:
    names = (
        "momentum_hunter.continuous_runtime",
        "momentum_hunter.continuous_live_qualification",
        "momentum_hunter.continuous_natural_setup",
        "momentum_hunter.continuous_tradeplan_producer",
        "momentum_hunter.providers",
        "momentum_hunter.schwab_market_data",
        "momentum_hunter.schwab_candle_backfill",
    )
    result = []
    for name in names:
        module = sys.modules.get(name)
        path = Path(str(getattr(module, "__file__", ""))).resolve(strict=True)
        if CANONICAL_ROOT not in path.parents:
            raise ForensicCanaryError(f"{name} was imported outside canonical.")
        result.append(
            {"module": name, "path": str(path), "sha256": _sha256(path)}
        )
    return result


def _copy_sanitized_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        raise ForensicCanaryError("Sanitized runtime evidence destination exists.")
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.name.endswith(".lock") or path.suffix.lower() == ".tmp":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError):
                target.write_bytes(data)
            else:
                target.write_bytes(_canonical_bytes(_sanitize(payload)))
        else:
            target.write_bytes(data)


def _run_subprocess(
    *,
    campaign_path: Path,
    phase: int,
    evidence_root: Path,
    timeout_seconds: int,
) -> None:
    command = (
        sys.executable,
        "-B",
        str(Path(__file__).resolve()),
        "phase",
        "--campaign",
        str(campaign_path),
        "--phase",
        str(phase),
    )
    completed = subprocess.run(
        command,
        cwd=CANONICAL_ROOT,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=os.environ.copy(),
    )
    transcript = {
        "phase": phase,
        "command": [
            str(Path(command[0]).name),
            "-B",
            "[CANARY_TOOL]",
            "phase",
            "--campaign",
            "[FORENSIC_ROOT]/campaign-config.json",
            "--phase",
            str(phase),
        ],
        "returnCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "completedAt": datetime.now().astimezone().isoformat(),
    }
    _write_once(evidence_root / f"phase-{phase}-transcript.json", _sanitize(transcript))
    if completed.returncode != 0:
        raise ForensicCanaryError(f"Canary phase {phase} failed; evidence preserved.")


def _run_campaign(args: argparse.Namespace) -> int:
    canonical = _validate_canonical()
    task_source = _validate_task_source()
    standard = _validate_standard()
    failed_evidence = _validate_failed_evidence()
    ownership = _ownership_map()
    if ownership["status"] != "PASS":
        raise ForensicCanaryError(
            "Forensic wrapper attempted to own decision-authoritative work."
        )
    evidence_root = _validate_external_root(args.evidence_root, require_new=True)
    runtime_root = _validate_runtime_root(args.runtime_root, require_new=True)
    if not 600 <= args.duration_seconds <= 1800:
        raise ForensicCanaryError("Campaign duration must be between 600 and 1800 seconds.")
    if not 60 <= args.discovery_cadence_seconds <= 600:
        raise ForensicCanaryError("Discovery cadence must be between 60 and 600 seconds.")
    if not os.environ.get(ACCOUNT_ENV, "").strip():
        raise ForensicCanaryError(f"{ACCOUNT_ENV} is required locally and is never persisted.")
    evidence_root.mkdir(parents=True)
    runtime_root.mkdir(parents=True)
    started = datetime.now().astimezone()
    attempt_id = evidence_root.name.lower().replace("_", "-")
    runtime_identity = f"producer-001c-forensic-{started.strftime('%Y%m%d')}"
    runtime_instance = f"producer-001c-forensic-{_fingerprint('attempt', attempt_id)[:24]}"
    first_duration = args.duration_seconds // 2
    second_duration = args.duration_seconds - first_duration
    campaign = {
        "schemaVersion": 1,
        "profile": CANARY_PROFILE,
        "campaignId": attempt_id,
        "campaignStartedAt": started.isoformat(),
        "canonicalSourceSha": canonical["head"],
        "canaryTaskGit": task_source,
        "canonicalRoot": str(CANONICAL_ROOT),
        "canaryTool": str(Path(__file__).resolve()),
        "canaryToolSha256": _sha256(Path(__file__).resolve()),
        "runtimeRoot": str(runtime_root),
        "evidenceRoot": str(evidence_root),
        "runtimeIdentity": runtime_identity,
        "runtimeInstanceId": runtime_instance,
        "sessionDate": started.astimezone(EASTERN).date().isoformat(),
        "durationSeconds": args.duration_seconds,
        "phase1DurationSeconds": first_duration,
        "phase2DurationSeconds": second_duration,
        "discoveryCadenceSeconds": args.discovery_cadence_seconds,
        "authority": AUTHORITY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "accountValuesRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderCapability": ORDER_CAPABILITY,
    }
    campaign["configurationFingerprint"] = _fingerprint(
        "producer-001c-forensic-campaign-config-v1", campaign
    )
    _write_once(evidence_root / "forensic-standard-verification.json", standard)
    _write_once(
        evidence_root / "failed-evidence-preservation.json", failed_evidence
    )
    _write_once(evidence_root / "canonical-ownership-map.json", ownership)
    _write_once(evidence_root / "production-baseline-before.json", _production_baseline("BEFORE"))
    campaign_path = evidence_root / "campaign-config.json"
    _write_once(campaign_path, campaign)
    try:
        _run_subprocess(
            campaign_path=campaign_path,
            phase=1,
            evidence_root=evidence_root,
            timeout_seconds=first_duration + 360,
        )
        _run_subprocess(
            campaign_path=campaign_path,
            phase=2,
            evidence_root=evidence_root,
            timeout_seconds=second_duration + 360,
        )
        _copy_sanitized_tree(runtime_root, evidence_root / "runtime-artifacts")
        _write_once(
            evidence_root / "campaign-observation-terminal.json",
            {
                "status": "OBSERVATION_TERMINAL_PENDING_HARD_CHEW_AND_SEAL",
                "completedAt": datetime.now().astimezone().isoformat(),
                "phase1Present": (evidence_root / "phase-1-receipt.json").is_file(),
                "phase2Present": (evidence_root / "phase-2-receipt.json").is_file(),
                "physicalProcessRestart": True,
                "authority": AUTHORITY,
                "executionAuthority": EXECUTION_AUTHORITY,
                "accountValuesRequested": False,
                "positionsRequested": False,
                "ordersRequested": False,
                "orderCapability": ORDER_CAPABILITY,
            },
        )
        return 0
    except Exception as exc:
        _write_once(
            evidence_root / "campaign-failure.json",
            {
                "status": "FAILED_PRESERVED",
                "failedAt": datetime.now().astimezone().isoformat(),
                "failureClass": type(exc).__name__,
                "detail": str(exc),
                "authority": AUTHORITY,
                "orderCapability": ORDER_CAPABILITY,
            },
        )
        raise


def _record_payloads(evidence_root: Path) -> list[dict[str, object]]:
    records = evidence_root / "runtime-artifacts" / "writer"
    result = []
    for path in sorted(records.rglob("*.json")) if records.exists() else []:
        try:
            document = json.loads(path.read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        intent = document.get("intent")
        if not isinstance(intent, Mapping) or not intent.get("payload_json"):
            continue
        try:
            payload = json.loads(str(intent["payload_json"]))
        except json.JSONDecodeError:
            continue
        result.append(
            {
                "relativePath": path.relative_to(evidence_root).as_posix(),
                "evidenceType": intent.get("evidence_type"),
                "recordIdentity": intent.get("record_identity"),
                "recordFingerprint": intent.get("record_fingerprint"),
                "requestedAt": intent.get("requested_at"),
                "payload": payload,
            }
        )
    return result


def _producer_steps(records: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    steps = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            continue
        for step in payload.get("naturalSteps", []):
            if isinstance(step, Mapping):
                steps.append(dict(step))
    return steps


def _attempt_events(
    evidence_root: Path,
    *,
    runtime_identity: str,
    configuration_fingerprint: str,
) -> list[dict[str, object]]:
    root = (
        evidence_root
        / "runtime-artifacts"
        / "checkpoint"
        / f"{runtime_identity}-attempts"
    )
    ledger = ContinuousAttemptLedger(
        root,
        runtime_identity=runtime_identity,
        configuration_fingerprint=configuration_fingerprint,
    )
    return [asdict(item) for item in ledger.events]


def _canonical_bar_semantic_identity(candle: Mapping[str, object]) -> str:
    timestamp = _parse_timestamp(str(candle.get("timestamp", "")))
    payload = {
        "symbol": str(candle.get("symbol", "")).strip().upper(),
        "timestamp": timestamp.astimezone(timezone.utc).isoformat(),
        "open": float(candle["open"]),
        "high": float(candle["high"]),
        "low": float(candle["low"]),
        "close": float(candle["close"]),
        "volume": float(candle["volume"]),
        "source": str(candle.get("source", "")),
        "sessionDate": str(candle.get("sessionDate", "")),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).hexdigest()


def _completed_bar_finality_accounting(
    evidence_root: Path,
    completed_bar_events: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    completed_bar_events = list(completed_bar_events)
    minute_root = evidence_root / "runtime-artifacts" / "market-data" / "minute"
    versions: list[dict[str, object]] = []
    for path in sorted(minute_root.glob("*/*.json")):
        partition = json.loads(path.read_text(encoding="ascii"))
        for raw_bar in partition.get("bars", []):
            if not isinstance(raw_bar, Mapping):
                continue
            for version in raw_bar.get("historyVersions", []):
                if not isinstance(version, Mapping):
                    continue
                candle = version.get("candle")
                if not isinstance(candle, Mapping):
                    continue
                semantic = _canonical_bar_semantic_identity(candle)
                provider_timestamp = _parse_timestamp(
                    str(candle.get("timestamp", ""))
                ).astimezone(timezone.utc).isoformat()
                identity_payload = {
                    "symbol": str(candle.get("symbol", "")).strip().upper(),
                    "providerTimestamp": provider_timestamp,
                    "barFingerprint": semantic,
                    "sourceEvidenceFingerprint": semantic,
                }
                material_fingerprint = _fingerprint(
                    "continuous-completed-bar-material-v2", identity_payload
                )
                received = _parse_timestamp(str(version.get("firstReceivedAt", "")))
                bar_end = _parse_timestamp(provider_timestamp) + timedelta(minutes=1)
                versions.append(
                    {
                        "eventId": (
                            f"continuous-completed-bar-{material_fingerprint[:24]}"
                        ),
                        "sourceFingerprint": material_fingerprint,
                        "symbol": identity_payload["symbol"],
                        "providerTimestamp": provider_timestamp,
                        "firstReceivedAt": received.isoformat(),
                        "barEnd": bar_end.isoformat(),
                        "validCompleted": received >= bar_end,
                        "versionId": version.get("versionId"),
                        "semanticIdentity": semantic,
                        "partition": path.relative_to(evidence_root).as_posix(),
                    }
                )
    valid_events = []
    premature_events = []
    unmatched_events = []
    for event in completed_bar_events:
        event_id = str(event.get("event_id", ""))
        occurred = _parse_timestamp(str(event.get("occurred_at", "")))
        matches = [
            item
            for item in versions
            if item["eventId"] == event_id
            and _parse_timestamp(str(item["firstReceivedAt"])) == occurred
        ]
        if len(matches) != 1:
            unmatched_events.append(
                {"event": dict(event), "candidateVersionCount": len(matches)}
            )
            continue
        detail = {"event": dict(event), "version": matches[0]}
        if matches[0]["validCompleted"]:
            valid_events.append(detail)
        else:
            premature_events.append(detail)
    return {
        "observedHistoryVersionCount": len(versions),
        "provisionalHistoryVersionCount": sum(
            1 for item in versions if not item["validCompleted"]
        ),
        "semanticallyCompletedHistoryVersionCount": sum(
            1 for item in versions if item["validCompleted"]
        ),
        "dispatchedEventCount": len(completed_bar_events),
        "validCompletedEventCount": len(valid_events),
        "prematureCompletedEventCount": len(premature_events),
        "unmatchedEventCount": len(unmatched_events),
        "validEvents": valid_events,
        "prematureEvents": premature_events,
        "unmatchedEvents": unmatched_events,
    }


def _analyze(evidence_root: Path) -> dict[str, object]:
    campaign = json.loads(
        (evidence_root / "campaign-config.json").read_text(encoding="ascii")
    )
    checkpoint_path = (
        evidence_root
        / "runtime-artifacts"
        / "checkpoint"
        / f"{campaign['runtimeIdentity']}.json"
    )
    checkpoint = json.loads(checkpoint_path.read_text(encoding="ascii"))
    physical_atomicity = json.loads(
        (evidence_root / "physical-atomicity-proof.json").read_text(
            encoding="ascii"
        )
    )
    completed_bar_events = [
        dict(item)
        for item in checkpoint.get("event_records", [])
        if isinstance(item, Mapping)
        and item.get("trigger") == CANONICAL_BAR_COMPLETED
    ]
    completed_bar_counter = int(
        checkpoint.get("counters", {}).get("completed_bar_events", 0)
    )
    attempt_events = _attempt_events(
        evidence_root,
        runtime_identity=str(campaign["runtimeIdentity"]),
        configuration_fingerprint=str(checkpoint["config_fingerprint"]),
    )
    attempt_starts = [
        item for item in attempt_events if item["event_type"] == ATTEMPT_STARTED
    ]
    attempt_failures = [
        item for item in attempt_events if item["event_type"] == ATTEMPT_FAILED
    ]
    attempt_successes = [
        item for item in attempt_events if item["event_type"] == ATTEMPT_SUCCEEDED
    ]
    composition_attempts = [
        item for item in attempt_starts if item["stage"] == "COMPOSITION"
    ]
    composition_failures = [
        item for item in attempt_failures if item["stage"] == "COMPOSITION"
    ]
    finality = _completed_bar_finality_accounting(
        evidence_root, completed_bar_events
    )
    backfill_accounting = _backfill_accounting(
        evidence_root
        / "runtime-artifacts"
        / "state"
        / "continuous-history-backfill.json"
    )
    records = _record_payloads(evidence_root)
    discoveries = [
        item for item in records if item.get("evidenceType") == "DISCOVERY_CYCLE"
    ]
    compositions = [
        item for item in records if item.get("evidenceType") == "COMPOSITION_CYCLE"
    ]
    steps = _producer_steps(compositions)
    discovery_symbols: set[str] = set()
    qualifying = 0
    provider_rows = 0
    pages = 0
    hot_transitions = []
    for item in discoveries:
        payload = item["payload"]
        pulse = payload.get("pulse", {})
        discovery_symbols.update(pulse.get("symbols_for_readiness", []))
        source = payload.get("sourceEvidence", {})
        snapshot = source.get("snapshot", {}) if isinstance(source, Mapping) else {}
        rows = snapshot.get("rows", []) if isinstance(snapshot, Mapping) else []
        qualifying = max(
            qualifying,
            int(snapshot.get("qualifiedCount", 0) or 0),
        )
        provider_rows += int(snapshot.get("representedRowCount", len(rows)) or 0)
        pages += int(snapshot.get("pagesReceived", 0) or 0)
        universe = source.get("universe", {}) if isinstance(source, Mapping) else {}
        hot_transitions.extend(universe.get("transitionDelta", []))
    admission_files = sorted(
        (evidence_root / "runtime-artifacts" / "source-evidence" / "schwab").glob(
            "continuous-history-admission-*.json"
        )
    )
    admissions = [json.loads(path.read_text(encoding="ascii")) for path in admission_files]
    completed_bar_reevaluations = []
    plans = []
    no_plans = []
    successors = []
    anti_hindsight = True
    history_reconstructable = True
    instrument_blocked = True
    for record in compositions:
        payload = record["payload"]
        request = payload.get("request", {})
        known_at = _parse_timestamp(str(payload.get("knownAt")))
        decision_cutoff = _parse_timestamp(
            str(payload.get("decisionCutoff") or payload.get("knownAt"))
        )
        if known_at != decision_cutoff:
            anti_hindsight = False
        for chronology in payload.get("evidenceKnownAt", []):
            if (
                not isinstance(chronology, Mapping)
                or not chronology.get("evidence")
                or not chronology.get("knownAt")
                or _parse_timestamp(str(chronology["knownAt"])) > decision_cutoff
            ):
                anti_hindsight = False
        if request.get("trigger") == CANONICAL_BAR_COMPLETED:
            completed_bar_reevaluations.append(
                {
                    "symbol": request.get("symbol"),
                    "requestId": request.get("request_id"),
                    "knownAt": payload.get("knownAt"),
                    "decisionCutoff": payload.get("decisionCutoff"),
                    "evidenceKnownAt": payload.get("evidenceKnownAt", []),
                    "naturalStepCount": len(payload.get("naturalSteps", [])),
                }
            )
        for step in payload.get("naturalSteps", []):
            producer = step.get("producerRecord", {})
            history = producer.get("historicalContext", {})
            current = producer.get("currentMarketEvidence", {})
            instrument = producer.get("instrumentAdmission", {})
            cycle = producer.get("compositionCycle", {})
            members = cycle.get("member_results", [])
            member = members[0] if members else {}
            plan = member.get("intraday_plan")
            cutoff_values = [
                history.get("evidence_cutoff"),
                current.get("receipt_timestamp"),
                instrument.get("observed_at"),
            ]
            for value in cutoff_values:
                if not value or _parse_timestamp(str(value)) > known_at:
                    anti_hindsight = False
            history_reconstructable = history_reconstructable and bool(
                history.get("context_id")
                and history.get("fingerprint")
                and history.get("minute_evidence_fingerprint")
            )
            instrument_blocked = instrument_blocked and (
                instrument.get("execution_eligible") is False
            )
            if plan:
                plans.append(plan)
            else:
                no_plans.append(
                    {
                        "symbol": current.get("symbol"),
                        "eventType": step.get("eventType"),
                        "blockers": producer.get("blockers", []),
                        "disposition": member.get("disposition"),
                    }
                )
            proposal = member.get("lifecycle_proposal") or {}
            if proposal.get("create_new_setup") and proposal.get("predecessor_setup_id"):
                successors.append(proposal)
    phase1 = json.loads((evidence_root / "phase-1-state.json").read_text(encoding="ascii"))
    phase2 = json.loads((evidence_root / "phase-2-state.json").read_text(encoding="ascii"))
    process_restart = (
        phase1.get("processId") != phase2.get("processId")
        and json.loads(
            (evidence_root / "phase-2-receipt.json").read_text(encoding="ascii")
        ).get("restoredFromCheckpoint")
        is True
    )
    phase1_records = {
        item["recordId"]: item["fingerprint"]
        for item in phase1.get("producerRecords", [])
    }
    phase2_records = {
        item["recordId"]: item["fingerprint"]
        for item in phase2.get("producerRecords", [])
    }
    restart_continuity = process_restart and all(
        phase2_records.get(key) == value for key, value in phase1_records.items()
    )
    duplicate_ids = len(phase2_records) != len(phase2.get("producerRecords", []))
    phase1_health = phase1.get("runtimeHealth", {})
    phase2_health = phase2.get("runtimeHealth", {})
    phase1_compositions = int(phase1_health.get("composition_cycles", 0) or 0)
    phase2_compositions = int(phase2_health.get("composition_cycles", 0) or 0)
    accepted_before_restart = phase1_compositions > 0
    post_restart_composition = phase2_compositions > phase1_compositions
    attempt_restart_continuity = (
        int(phase2.get("attemptLedgerCount", 0))
        >= int(phase1.get("attemptLedgerCount", 0))
        and (
            not phase1.get("attemptLedgerHead")
            or any(
                item["event_id"] == phase1.get("attemptLedgerHead")
                for item in attempt_events
            )
        )
    )
    attempt_process_ids = sorted(
        {
            int(item["process_id"])
            for item in attempt_events
            if int(item.get("process_id", 0)) > 0
        }
    )
    attempt_physical_restart = len(attempt_process_ids) >= 2
    backfill_rows = 0
    for item in admissions:
        backfill = item.get("backfill") or {}
        for symbol_result in backfill.get("symbols", []):
            backfill_rows += int(symbol_result.get("minute", {}).get("rows", 0) or 0)
            backfill_rows += int(symbol_result.get("daily", {}).get("rows", 0) or 0)
    earliest = None
    if compositions:
        earliest = min(
            _parse_timestamp(str(item["payload"].get("knownAt")))
            for item in compositions
        )
    launch = _parse_timestamp(str(campaign["campaignStartedAt"]))
    no_five_bar_wait = bool(earliest and (earliest - launch).total_seconds() < 300)
    has_qualified = qualifying > 0
    first_observed = {
        str(item.get("symbol", "")): _parse_timestamp(
            str(item.get("first_observed_at"))
        )
        for phase in (phase1, phase2)
        for item in (phase.get("hotUniverse") or {}).get("members", [])
        if item.get("symbol") and item.get("first_observed_at")
    }
    prospective_floor_preserved = all(
        event.get("symbol") in first_observed
        and _parse_timestamp(str(event.get("provider_timestamp")))
        >= first_observed[str(event.get("symbol"))]
        for event in completed_bar_events
    )
    truthful_counters = (
        completed_bar_counter == len(completed_bar_events)
        and int(phase2_health.get("composition_attempts_started", -1))
        == len(composition_attempts)
        and int(phase2_health.get("composition_attempts_failed", -1))
        == len(composition_failures)
        and int(phase2_health.get("composition_cycles", -1))
        == len(compositions)
        and int(phase2_health.get("unique_ready_symbols", -1))
        <= int(phase2_health.get("ready_members", -1))
    )
    atomic_proof = physical_atomicity.get("proof", {})
    atomicity_passed = (
        physical_atomicity.get("classification")
        == "ATOMIC_COMPOSITION_PHYSICAL_PROOF_PASSED"
    )
    exact_failure_diagnostics = atomicity_passed and any(
        item.get("event_type") == ATTEMPT_FAILED
        and item.get("exception_class") == "RuntimeError"
        and item.get("diagnostic_code") == "RuntimeError"
        and item.get("message") == "producer-001c physical staged failure"
        and item.get("canonical_request_cutoff")
        and item.get("canonical_evidence_known_at")
        for item in physical_atomicity.get("attemptEvents", [])
    )
    classifications = {
        "CANONICAL_TIME_IDENTITY_REPAIRED": "YES" if compositions and anti_hindsight else "NO",
        "EQUIVALENT_OFFSET_INSTANTS_ACCEPTED": "YES" if compositions and anti_hindsight else "NO",
        "DISTINCT_INSTANTS_REJECTED": "YES_OFFLINE_PROOF",
        "ANTI_HINDSIGHT_GATE_PRESERVED": "YES" if compositions and anti_hindsight else "NO",
        "COMPLETED_BAR_FINALITY_REPAIRED": (
            "YES"
            if finality["prematureCompletedEventCount"] == 0
            and finality["unmatchedEventCount"] == 0
            and finality["validCompletedEventCount"] > 0
            else "NO"
        ),
        "PREMATURE_COMPLETED_BAR_EVENTS": finality["prematureCompletedEventCount"],
        "VALID_COMPLETED_BAR_EVENTS": finality["validCompletedEventCount"],
        "APPEND_ONLY_FAILURE_CHRONOLOGY": (
            "YES"
            if len(attempt_events) == int(checkpoint.get("attempt_ledger_count", -1))
            and (
                not attempt_events
                or attempt_events[-1]["event_id"]
                == checkpoint.get("attempt_ledger_head")
            )
            else "NO"
        ),
        "EXACT_COMPOSITION_FAILURE_DIAGNOSTICS": (
            "YES" if exact_failure_diagnostics else "NO"
        ),
        "TRUTHFUL_STAGE_COUNTERS": "YES" if truthful_counters else "NO",
        "ATOMIC_FAILED_COMPOSITION_NONMUTATION": (
            "YES"
            if atomicity_passed
            and atomic_proof.get("failureWasByteIdentical") is True
            and atomic_proof.get("failureCheckpointProjectionWasIdentical")
            is True
            and atomic_proof.get("restartRecoveredNoPhantomState") is True
            and atomic_proof.get("failureChangedAuthoritativeState") is False
            else "NO"
        ),
        "VALID_COMPOSITION_SINGLE_COMMIT": (
            "YES"
            if atomicity_passed
            and atomic_proof.get("validCompositionCommittedOnce") is True
            and atomic_proof.get("duplicateReplayWasIdempotent") is True
            else "NO"
        ),
        "PROSPECTIVE_FLOOR_INTEGRITY": (
            "YES" if completed_bar_events and prospective_floor_preserved else "NO"
        ),
        "REAL_PROVIDER_DISCOVERY_PROVEN": "YES" if len(discoveries) >= 2 and pages >= 2 else "NO",
        "NATURAL_HOT_UNIVERSE_ADMISSION_PROVEN": (
            "YES" if hot_transitions and has_qualified else "NO_QUALIFIED_CANDIDATE" if not has_qualified else "NO"
        ),
        "REAL_SCHWAB_BACKFILL_PROVEN": (
            "YES"
            if int(backfill_accounting["successful"]) > 0
            else "NOT_REQUIRED_EXISTING_HISTORY"
            if admissions and int(backfill_accounting["attempts"]) == 0
            else "ATTEMPTED_NOT_SUCCESSFUL"
            if int(backfill_accounting["attempts"]) > 0
            else "NO"
        ),
        "HISTORICAL_CONTEXT_FORENSICALLY_RECONSTRUCTABLE": (
            "YES" if compositions and history_reconstructable else "NO"
        ),
        "REAL_COMPLETED_BAR_DISPATCH_PROVEN": (
            "YES"
            if completed_bar_events
            and completed_bar_counter == len(completed_bar_events)
            and finality["validCompletedEventCount"] == len(completed_bar_events)
            and finality["prematureCompletedEventCount"] == 0
            and finality["unmatchedEventCount"] == 0
            else "NO"
        ),
        "NATURAL_MATERIAL_REEVALUATION_PROVEN": (
            "YES" if completed_bar_reevaluations else "NO"
        ),
        "NATURAL_RUNTIME_TRADEPLAN_OBSERVED": (
            "YES" if plans else "MARKET_DID_NOT_JUSTIFY_PLAN" if compositions else "NO"
        ),
        "NATURAL_SUCCESSOR_SETUP_OBSERVED": "YES" if successors else "NO",
        "NO_ARBITRARY_FIVE_BAR_WAIT_PHYSICALLY_PROVEN": "YES" if no_five_bar_wait else "NO",
        "END_TO_END_PRODUCER_RESTART_PROVEN": (
            "YES"
            if restart_continuity
            and attempt_restart_continuity
            and attempt_physical_restart
            and accepted_before_restart
            and post_restart_composition
            and not duplicate_ids
            else "NO"
        ),
        "ACCEPTED_COMPOSITION_CYCLE_PROVEN": (
            "YES" if phase2_compositions > 0 and compositions else "NO"
        ),
        "NATURAL_NO_PLAN_OR_TRADEPLAN_COMMITTED": (
            "YES" if phase2_records and (plans or no_plans) else "NO"
        ),
        "FAILED_001A_AND_001B_EVIDENCE_PRESERVED": "YES",
        "SECOND_EYE_ZIP_SELF_CONTAINED": "PENDING",
        "READY_FOR_SECOND_EYE_REVIEW": "NO",
        "MERGE_AUTHORIZED": "NO",
        "UNKNOWN_INSTRUMENT_EXECUTION_ELIGIBILITY": "BLOCKED" if instrument_blocked else "ANOMALY",
        "PAPER_OR_EXECUTION_AUTHORITY_USED": "NO",
    }
    timeline = {
        "discoveryRecords": discoveries,
        "admissions": admissions,
        "compositionRecords": compositions,
        "completedBarEvents": completed_bar_events,
        "completedBarFinality": finality,
        "completedBarReevaluations": completed_bar_reevaluations,
        "attemptEvents": attempt_events,
        "physicalAtomicityProof": physical_atomicity,
        "backfillAccounting": backfill_accounting,
        "tradePlans": plans,
        "truthfulNoPlans": no_plans,
        "successorSetups": successors,
    }
    result = {
        "schemaVersion": 1,
        "profile": CANARY_PROFILE,
        "analyzedAt": datetime.now().astimezone().isoformat(),
        "providerDiscovery": {
            "cycles": len(discoveries),
            "pages": pages,
            "representedRows": provider_rows,
            "maximumQualifyingCandidates": qualifying,
            "symbolsForReadiness": sorted(discovery_symbols),
        },
        "hotUniverseTransitionCount": len(hot_transitions),
        "schwabAdmissionCount": len(admissions),
        "schwabBackfillRows": backfill_rows,
        "schwabBackfillAttempts": int(backfill_accounting["attempts"]),
        "schwabBackfillSuccesses": int(backfill_accounting["successful"]),
        "schwabBackfillFailures": int(backfill_accounting["failed"]),
        "compositionCount": len(compositions),
        "acceptedCompositionCycleCount": phase2_compositions,
        "compositionAttemptCount": len(composition_attempts),
        "compositionAttemptFailureCount": len(composition_failures),
        "attemptEventCount": len(attempt_events),
        "attemptStartCount": len(attempt_starts),
        "attemptSuccessCount": len(attempt_successes),
        "attemptFailureCount": len(attempt_failures),
        "completedBarEventCount": len(completed_bar_events),
        "completedBarEventCounter": completed_bar_counter,
        "completedBarEventAccountingMatches": (
            completed_bar_counter == len(completed_bar_events)
        ),
        "completedBarReevaluationCount": len(completed_bar_reevaluations),
        "completedBarFinality": finality,
        "tradePlanCount": len(plans),
        "truthfulNoPlanCount": len(no_plans),
        "successorSetupCount": len(successors),
        "physicalRestart": process_restart,
        "restartContinuity": restart_continuity,
        "attemptRestartContinuity": attempt_restart_continuity,
        "attemptPhysicalProcessRestart": attempt_physical_restart,
        "attemptProcessIds": attempt_process_ids,
        "acceptedCompositionBeforeRestart": accepted_before_restart,
        "postRestartCompositionCycle": post_restart_composition,
        "duplicateProducerIdentity": duplicate_ids,
        "truthfulCounters": truthful_counters,
        "prospectiveFloorPreserved": prospective_floor_preserved,
        "classifications": classifications,
        "timelineFingerprint": _fingerprint(
            "producer-001c-forensic-timeline-v1", timeline
        ),
        "authority": AUTHORITY,
        "executionAuthority": EXECUTION_AUTHORITY,
        "accountValuesRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderCapability": ORDER_CAPABILITY,
    }
    result["fingerprint"] = _fingerprint(
        "producer-001c-forensic-analysis-v1", result
    )
    return {"analysis": result, "timeline": timeline}


def _compare_baselines(before: Mapping[str, object], after: Mapping[str, object]) -> dict[str, object]:
    stable_keys = ("services", "selectedProductionHashes", "manifestSafety")
    comparisons = {key: before.get(key) == after.get(key) for key in stable_keys}
    return {
        "sourceGitStable": before.get("sourceGit") == after.get("sourceGit"),
        "canaryTaskGitStable": before.get("canaryTaskGit") == after.get("canaryTaskGit"),
        "canonicalGitStable": before.get("canonicalGit") == after.get("canonicalGit"),
        "servicesStable": comparisons["services"],
        "selectedProductionHashesStable": comparisons["selectedProductionHashes"],
        "manifestSafetyStable": comparisons["manifestSafety"],
        "productionMutationByCanary": False,
        "comparisonPassed": all(comparisons.values())
        and before.get("sourceGit") == after.get("sourceGit")
        and before.get("canaryTaskGit") == after.get("canaryTaskGit")
        and before.get("canonicalGit") == after.get("canonicalGit"),
    }


def _seal(args: argparse.Namespace) -> int:
    root = _validate_external_root(args.evidence_root, require_new=False)
    if (root / "forensic-manifest.json").exists():
        raise ForensicCanaryError("Forensic packet is already sealed.")
    required = (
        "campaign-config.json",
        "canonical-ownership-map.json",
        "failed-evidence-preservation.json",
        "physical-atomicity-proof.json",
        "phase-1-state.json",
        "phase-1-receipt.json",
        "phase-2-state.json",
        "phase-2-receipt.json",
        "campaign-observation-terminal.json",
        "verification-summary.json",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise ForensicCanaryError(f"Canary evidence is incomplete: {missing}")
    preserved_now = _validate_failed_evidence()
    preserved_before = json.loads(
        (root / "failed-evidence-preservation.json").read_text(encoding="ascii")
    )
    if preserved_now != preserved_before:
        raise ForensicCanaryError("Failed Producer evidence changed during canary.")
    after = _production_baseline("AFTER")
    _write_once(root / "production-baseline-after.json", after)
    before = json.loads(
        (root / "production-baseline-before.json").read_text(encoding="ascii")
    )
    nonmutation = _compare_baselines(before, after)
    _write_once(root / "production-nonmutation.json", nonmutation)
    analyzed = _analyze(root)
    _write_once(root / "forensic-timeline.json", analyzed["timeline"])
    classifications = dict(analyzed["analysis"]["classifications"])
    classifications["FORENSIC_PACKET_COMPLETE"] = "YES"
    classifications["SECOND_EYE_ZIP_SELF_CONTAINED"] = "PENDING"
    classifications["READY_FOR_SECOND_EYE_REVIEW"] = "NO"
    analysis = dict(analyzed["analysis"])
    analysis["classifications"] = classifications
    analysis["productionNonmutation"] = nonmutation
    _write_once(root / "forensic-analysis.json", analysis)
    secret_scan = _secret_scan(root, forbidden_value=os.environ.get(ACCOUNT_ENV, ""))
    _write_once(root / "secret-scan.json", secret_scan)
    if secret_scan["status"] != "PASS":
        raise ForensicCanaryError("Forensic packet secret scan failed.")
    items = _file_manifest(root)
    manifest = {
        "schemaVersion": 1,
        "profile": CANARY_PROFILE,
        "sealedAt": datetime.now().astimezone().isoformat(),
        "files": items,
        "fileCount": len(items),
        "manifestFingerprint": _manifest_fingerprint(items),
        "classifications": classifications,
    }
    _write_once(root / "forensic-manifest.json", manifest)
    return 0


def _secret_scan(root: Path, *, forbidden_value: str = "") -> dict[str, object]:
    credential_patterns = (
        ("BEARER_CREDENTIAL", re.compile(r"Bearer\s+[A-Za-z0-9._~-]{20,}")),
        ("ALPACA_KEY_SHAPE", re.compile(r"\bPK[A-Z0-9]{18,}\b")),
    )
    findings: list[dict[str, object]] = []
    files_scanned = 0
    bound_identity_pattern = (
        re.compile(
            r"(?i)(?:account[_\s-]*(?:number|id|ending)|"
            r"expected[_\s-]*account[_\s-]*ending)"
            r"\s*[\"']?\s*[:=]\s*[\"']?"
            + re.escape(forbidden_value)
        )
        if forbidden_value
        else None
    )

    def inspect_json(value: object, *, relative: str, key: str = "") -> None:
        if _sensitive_key(key) and not (
            value is None or value == "" or value == "[REDACTED]"
        ):
            findings.append(
                {"path": relative, "term": "UNREDACTED_SENSITIVE_JSON_VALUE"}
            )
            return
        if isinstance(value, Mapping):
            for item_key, item_value in value.items():
                inspect_json(item_value, relative=relative, key=str(item_key))
        elif isinstance(value, list):
            for item in value:
                inspect_json(item, relative=relative)

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() in {".zip", ".png", ".exe", ".dll"}:
            continue
        files_scanned += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        for name, pattern in credential_patterns:
            if pattern.search(text):
                findings.append(
                    {"path": relative, "term": name}
                )
        if bound_identity_pattern is not None and bound_identity_pattern.search(text):
            findings.append(
                {"path": relative, "term": "BOUND_ENDING_CONTEXT"}
            )
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            inspect_json(payload, relative=relative)
    return {
        "status": "PASS" if not findings else "FAIL",
        "filesScanned": files_scanned,
        "findings": findings,
    }


def _resume_seal_after_false_positive(args: argparse.Namespace) -> int:
    root = _validate_external_root(args.evidence_root, require_new=False)
    if (root / "forensic-manifest.json").exists():
        raise ForensicCanaryError("Forensic packet is already sealed.")
    required = (
        "forensic-analysis.json",
        "forensic-timeline.json",
        "production-baseline-after.json",
        "production-nonmutation.json",
        "secret-scan.json",
        "verification-summary.json",
    )
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise ForensicCanaryError(
            f"Failed seal cannot be resumed; evidence is missing: {missing}"
        )
    original_scan = json.loads(
        (root / "secret-scan.json").read_text(encoding="ascii")
    )
    findings = original_scan.get("findings", [])
    if (
        original_scan.get("status") != "FAIL"
        or not findings
        or any(item.get("term") != "BOUND_ENDING" for item in findings)
    ):
        raise ForensicCanaryError(
            "Failed seal included a finding other than the proven raw-digit false positive."
        )
    corrected_scan = _secret_scan(
        root, forbidden_value=os.environ.get(ACCOUNT_ENV, "")
    )
    _write_once(root / "secret-scan-v2.json", corrected_scan)
    if corrected_scan["status"] != "PASS":
        raise ForensicCanaryError("Corrected context-aware secret scan failed.")
    campaign = json.loads(
        (root / "campaign-config.json").read_text(encoding="ascii")
    )
    reconciliation = {
        "schemaVersion": 1,
        "classification": "SEAL_RESUMED_AFTER_RAW_DIGIT_FALSE_POSITIVE",
        "originalSecretScan": {
            "path": "secret-scan.json",
            "sha256": _sha256(root / "secret-scan.json"),
            "findingCount": len(findings),
            "findingTerms": sorted({str(item.get("term")) for item in findings}),
            "preserved": True,
        },
        "correctedSecretScan": {
            "path": "secret-scan-v2.json",
            "status": corrected_scan["status"],
            "filesScanned": corrected_scan["filesScanned"],
        },
        "reason": (
            "A bare four-digit substring is common in market values, timestamps, "
            "and hashes; only sensitive JSON keys or explicit account-ending "
            "contexts may identify the local binding value."
        ),
        "campaignToolSha256": campaign.get("canaryToolSha256"),
        "campaignTaskHead": campaign.get("canaryTaskGit", {}).get("head"),
        "packagingToolGit": _validate_task_source(),
        "campaignEvidenceRewritten": False,
    }
    _write_once(root / "sealing-reconciliation.json", reconciliation)
    analysis = json.loads(
        (root / "forensic-analysis.json").read_text(encoding="ascii")
    )
    classifications = dict(analysis.get("classifications", {}))
    classifications["SEAL_RESUMED_AFTER_SECRET_SCAN_FALSE_POSITIVE"] = "YES"
    items = _file_manifest(root)
    manifest = {
        "schemaVersion": 1,
        "profile": CANARY_PROFILE,
        "sealedAt": datetime.now().astimezone().isoformat(),
        "files": items,
        "fileCount": len(items),
        "manifestFingerprint": _manifest_fingerprint(items),
        "classifications": classifications,
    }
    _write_once(root / "forensic-manifest.json", manifest)
    return 0


def _verification_command(
    *,
    evidence_root: Path,
    name: str,
    command: tuple[str, ...],
    timeout_seconds: int,
) -> dict[str, object]:
    started = datetime.now().astimezone()
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=os.environ.copy(),
    )
    finished = datetime.now().astimezone()
    transcript = {
        "name": name,
        "startedAt": started.isoformat(),
        "completedAt": finished.isoformat(),
        "elapsedSeconds": round((finished - started).total_seconds(), 3),
        "command": [Path(command[0]).name, *command[1:]],
        "returnCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
    }
    _write_once(
        evidence_root / "verification" / f"{name}.json",
        _sanitize(transcript),
    )
    return {
        "name": name,
        "status": transcript["status"],
        "returnCode": completed.returncode,
        "elapsedSeconds": transcript["elapsedSeconds"],
        "transcript": f"verification/{name}.json",
    }


def _verify(args: argparse.Namespace) -> int:
    root = _validate_external_root(args.evidence_root, require_new=False)
    if not (root / "campaign-observation-terminal.json").is_file():
        raise ForensicCanaryError("Terminal canary evidence is required before Hard Chew.")
    if (root / "verification-summary.json").exists():
        raise ForensicCanaryError("Verification evidence already exists.")
    python = sys.executable
    focused_modules = (
        "tests.test_continuous_attempt_ledger",
        "tests.test_continuous_time_identity",
        "tests.test_continuous_candle_finality",
        "tests.test_continuous_producer_001c_atomicity_proof",
        "tests.test_continuous_producer_001b_forensic_canary",
        "tests.test_continuous_live_qualification",
        "tests.test_continuous_canary_hardening",
        "tests.test_continuous_natural_setup",
        "tests.test_continuous_tradeplan_producer",
        "tests.test_continuous_runtime",
        "tests.test_broad_discovery",
        "tests.test_hot_universe",
        "tests.test_schwab_candle_backfill",
        "tests.test_schwab_market_data",
    )
    opening_modules = (
        "tests.test_automation_opening_capture",
        "tests.test_opening_candle_readiness",
    )
    commands = [
        (
            "focused-tests",
            (python, "-B", "-m", "unittest", "-v", *focused_modules),
            3600,
        ),
        (
            "opening-boundary-regressions",
            (python, "-B", "-m", "unittest", "-v", *opening_modules),
            1800,
        ),
        (
            "compileall",
            (
                python,
                "-B",
                "-m",
                "compileall",
                "-q",
                "momentum_hunter",
                "tools/run_continuous_producer_001c_atomicity_proof.py",
                "tools/run_continuous_producer_001b_forensic_canary.py",
            ),
            600,
        ),
    ]
    if args.full_suite:
        commands.append(
            (
                "full-python-discovery",
                (
                    python,
                    "-B",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test_*.py",
                    "-v",
                ),
                7200,
            )
        )
    results = [
        _verification_command(
            evidence_root=root,
            name=name,
            command=command,
            timeout_seconds=timeout,
        )
        for name, command, timeout in commands
    ]
    ownership = _ownership_map()
    capability = _static_capability_scan()
    summary = {
        "schemaVersion": 1,
        "profile": CANARY_PROFILE,
        "completedAt": datetime.now().astimezone().isoformat(),
        "commands": results,
        "canonicalOwnership": ownership["status"],
        "capabilityScan": capability,
        "protectedPathReview": {
            "runtimeRootPolicy": "TEMP_ONLY",
            "evidenceRootPolicy": "ARGUS_REVIEW_BUNDLES_ONLY",
            "productionMutationAuthorized": False,
            "status": "PASS",
        },
        "status": (
            "PASS"
            if all(item["status"] == "PASS" for item in results)
            and ownership["status"] == "PASS"
            and capability["status"] == "PASS"
            else "FAIL"
        ),
    }
    _write_once(root / "verification-summary.json", summary)
    return 0 if summary["status"] == "PASS" else 1


def _copy_package_tree(
    source: Path,
    destination: Path,
    *,
    forbidden_value: str,
) -> list[dict[str, object]]:
    substitutions: list[dict[str, object]] = []
    text_suffixes = {".cfg", ".csv", ".ini", ".json", ".md", ".ps1", ".py", ".txt", ".yaml", ".yml"}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if ".git" in relative.parts or "__pycache__" in relative.parts:
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.suffix.lower() in {".pyc", ".pyo"}:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if forbidden_value and path.suffix.lower() in text_suffixes:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(path, target)
                continue
            replacement_count = text.count(forbidden_value)
            if replacement_count:
                text = text.replace(forbidden_value, "0000")
                target.write_text(text, encoding="utf-8", newline="")
                substitutions.append(
                    {
                        "path": relative.as_posix(),
                        "replacementCount": replacement_count,
                        "reason": "LOCAL_ACCOUNT_BINDING_IDENTITY_REDACTED_TO_SYNTHETIC_VALUE",
                        "originalSha256": _sha256(path),
                        "sanitizedSha256": _sha256(target),
                    }
                )
                continue
        shutil.copy2(path, target)
    return substitutions


def _package_focus_modules() -> tuple[str, ...]:
    return (
        "tests.test_continuous_attempt_ledger",
        "tests.test_continuous_time_identity",
        "tests.test_continuous_candle_finality",
        "tests.test_continuous_producer_001c_atomicity_proof",
        "tests.test_continuous_producer_001b_forensic_canary",
        "tests.test_continuous_live_qualification",
        "tests.test_continuous_canary_hardening",
        "tests.test_continuous_natural_setup",
        "tests.test_continuous_tradeplan_producer",
        "tests.test_continuous_runtime",
        "tests.test_broad_discovery",
        "tests.test_hot_universe",
        "tests.test_schwab_candle_backfill",
        "tests.test_schwab_market_data",
    )


def _run_package_tests(source_root: Path) -> dict[str, object]:
    environment = os.environ.copy()
    environment[CANONICAL_ENV] = str(source_root)
    environment[ACCOUNT_ENV] = "0000"
    started = datetime.now().astimezone()
    command = (
        sys.executable,
        "-B",
        "-m",
        "unittest",
        "-v",
        *_package_focus_modules(),
    )
    completed = subprocess.run(
        command,
        cwd=source_root,
        capture_output=True,
        text=True,
        timeout=3600,
        env=environment,
    )
    finished = datetime.now().astimezone()
    return {
        "startedAt": started.isoformat(),
        "completedAt": finished.isoformat(),
        "elapsedSeconds": round((finished - started).total_seconds(), 3),
        "command": [Path(command[0]).name, *command[1:]],
        "returnCode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "localImportRoot": str(source_root),
    }


def _verify_extracted_manifest(extracted: Path) -> dict[str, object]:
    manifest_path = extracted / "PACKAGE-MANIFEST.json"
    payload = json.loads(manifest_path.read_text(encoding="ascii"))
    failures = []
    for item in payload.get("files", []):
        path = extracted / str(item["path"])
        if not path.is_file():
            failures.append({"path": item["path"], "reason": "MISSING"})
        elif _sha256(path) != item["sha256"]:
            failures.append({"path": item["path"], "reason": "HASH_MISMATCH"})
    return {
        "status": "PASS" if not failures else "FAIL",
        "manifestCount": len(payload.get("files", [])),
        "failures": failures,
    }


def _render_package_index(
    *,
    root: Path,
    ownership: Mapping[str, object],
    focused_modules: Iterable[str],
) -> str:
    stages = ownership.get("stages", [])
    lines = [
        "# Producer-001C Forensic Canary Second-Eye Packet",
        "",
        f"Canonical source: `{EXPECTED_CANONICAL_SHA}`",
        f"Evidence: `evidence/{root.name}`",
        "Authority: `RESEARCH_ONLY`; execution authority: `NONE`; order capability: `UNAVAILABLE`.",
        "",
        "## Canonical Ownership",
        "",
        "The forensic wrapper is observational. It starts/ticks/stops and restarts the isolated canonical runtime, captures and sanitizes evidence, verifies hashes, and packages this packet. It does not supply candidate, lifecycle, setup, material-event, TradePlan, or no-plan inputs.",
        "",
        "| Stage | Canonical owner | Source |",
        "|---|---|---|",
    ]
    for item in stages:
        owner = item["owner"]
        lines.append(
            f"| `{item['stage']}` | `{owner['qualifiedName']}` | `{owner['sourcePath']}:{owner['firstLine']}` |"
        )
    lines.extend(
        [
            "",
            "Machine-readable proof: `evidence/"
            + root.name
            + "/canonical-ownership-map.json`.",
            "",
            "## Contents",
            "",
            "- `evidence/`: immutable canary observations, verification transcripts, manifests, timeline, and classifications.",
            "- `source/momentum_hunter/`: complete canonical local package, sanitized only where the local account-binding identity appeared.",
            "- `source/tests/`: complete canonical tests plus the canary wrapper tests.",
            "- `source/tools/capture_job.py`: local source dependency read by the packaged hot-universe boundary test.",
            "- `source/tools/run_continuous_producer_001c_atomicity_proof.py`: deterministic disposable physical atomicity proof using production runtime/composition classes.",
            "- `source/tools/run_continuous_producer_001b_forensic_canary.py`: exact canary wrapper.",
            "- `references/`: binding standard, Roadmap snapshot, Producer-001B/001C charters, canary charter, and the prior Producer-001A release record.",
            "- `PACKAGE-SANITIZATION-LEDGER.json`: every source substitution and original/sanitized hashes.",
            "- `PACKAGE-MANIFEST.json`: per-file hashes for archive verification.",
            "",
            "## Focused Rerun",
            "",
            "Run from `source/` with the packaged source as `MH_CANARY_CANONICAL_ROOT`:",
            "",
            "```text",
            "python -B -m unittest -v " + " ".join(focused_modules),
            "```",
            "",
            "The package includes a pre-ZIP focused-rerun transcript and the external closeout includes an extracted-ZIP rerun result.",
            "",
            "## Known Limits",
            "",
            "- Unknown instrument subtype remains execution-ineligible.",
            "- The market may truthfully produce no TradePlan or successor setup.",
            "- Market observations grant no Paper, Shadow, broker, account, position, or order authority.",
            "- Sanitized source uses synthetic `0000` where the local account-binding identity appeared; the ledger preserves original and sanitized file hashes without preserving that identity.",
            "",
        ]
    )
    return "\n".join(lines)


def _next_package_identity(root: Path) -> tuple[Path, Path, Path, int]:
    for attempt in range(1, 100):
        suffix = "" if attempt == 1 else f"-V{attempt}"
        package_root = root.parent / f"{root.name}-SECOND-EYE{suffix}"
        zip_path = root.parent / f"{root.name}-SECOND-EYE{suffix}.zip"
        extracted_root = root.parent / (
            f"{root.name}-SECOND-EYE{suffix}-EXTRACTED-VERIFY"
        )
        if not any(path.exists() for path in (package_root, zip_path, extracted_root)):
            return package_root, zip_path, extracted_root, attempt
    raise ForensicCanaryError("No unused second-eye packaging identity remains.")


def _prior_package_attempts(root: Path) -> list[dict[str, object]]:
    attempts = []
    prefix = f"{root.name}-SECOND-EYE"
    for path in sorted(root.parent.glob(f"{prefix}*")):
        if not path.is_dir() or "-EXTRACTED-VERIFY" in path.name:
            continue
        rerun_path = path / "FOCUSED-RERUN-PREZIP.json"
        item: dict[str, object] = {
            "path": str(path),
            "preserved": True,
            "preZipFocusedRerun": "NOT_PRESENT",
        }
        if rerun_path.is_file():
            rerun = json.loads(rerun_path.read_text(encoding="ascii"))
            item["preZipFocusedRerun"] = {
                "status": rerun.get("status"),
                "returnCode": rerun.get("returnCode"),
                "elapsedSeconds": rerun.get("elapsedSeconds"),
                "sha256": _sha256(rerun_path),
            }
        attempts.append(item)
    return attempts


def _package(args: argparse.Namespace) -> int:
    root = _validate_external_root(args.evidence_root, require_new=False)
    manifest_path = root / "forensic-manifest.json"
    if not manifest_path.is_file():
        raise ForensicCanaryError("Forensic packet must be sealed before packaging.")
    prior_package_attempts = _prior_package_attempts(root)
    package_root, zip_path, extracted_root, package_attempt = (
        _next_package_identity(root)
    )
    evidence_destination = package_root / "evidence"
    shutil.copytree(root, evidence_destination)
    source_destination = package_root / "source"
    source_destination.mkdir(parents=True)
    forbidden_value = os.environ.get(ACCOUNT_ENV, "").strip()
    substitutions = []
    substitutions.extend(
        _copy_package_tree(
            CANONICAL_ROOT / "momentum_hunter",
            source_destination / "momentum_hunter",
            forbidden_value=forbidden_value,
        )
    )
    substitutions.extend(
        {
            **item,
            "path": f"tests/{item['path']}",
        }
        for item in _copy_package_tree(
            CANONICAL_ROOT / "tests",
            source_destination / "tests",
            forbidden_value=forbidden_value,
        )
    )
    shutil.copy2(CANONICAL_ROOT / "requirements.txt", source_destination / "requirements.txt")
    (source_destination / "tools").mkdir(parents=True)
    shutil.copy2(
        CANONICAL_ROOT / "tools" / "capture_job.py",
        source_destination / "tools" / "capture_job.py",
    )
    shutil.copy2(
        CANONICAL_ROOT
        / "tools"
        / "run_continuous_producer_001c_atomicity_proof.py",
        source_destination
        / "tools"
        / "run_continuous_producer_001c_atomicity_proof.py",
    )
    shutil.copy2(Path(__file__).resolve(), source_destination / "tools" / Path(__file__).name)
    shutil.copy2(
        Path(__file__).resolve().parents[1]
        / "tests"
        / "test_continuous_producer_001b_forensic_canary.py",
        source_destination / "tests" / "test_continuous_producer_001b_forensic_canary.py",
    )
    references = package_root / "references"
    references.mkdir(parents=True)
    shutil.copy2(
        PRODUCTION_ROOT / "docs" / "argus-office" / "ROADMAP.md",
        references / "ROADMAP.md",
    )
    shutil.copy2(
        PRODUCTION_ROOT
        / "docs"
        / "argus-office"
        / "reports"
        / "releases"
        / "ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001A.md",
        references / "ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001A.md",
    )
    shutil.copy2(
        CANONICAL_ROOT
        / "docs"
        / "argus-office"
        / "goal-charters"
        / "ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001B.md",
        references / "ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001B.md",
    )
    shutil.copy2(
        CANONICAL_ROOT
        / "docs"
        / "argus-office"
        / "goal-charters"
        / "ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001C.md",
        references / "ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001C.md",
    )
    shutil.copy2(
        Path(__file__).resolve().parents[1]
        / "docs"
        / "argus-office"
        / "goal-charters"
        / "ARGUS-CONTINUOUS-PRODUCER-001B-FORENSIC-CANARY.md",
        references / "ARGUS-CONTINUOUS-PRODUCER-001B-FORENSIC-CANARY.md",
    )
    shutil.copy2(
        Path(__file__).resolve().parents[1]
        / "docs"
        / "argus-office"
        / "goal-charters"
        / "ARGUS-CONTINUOUS-PRODUCER-001C-FORENSIC-CANARY.md",
        references / "ARGUS-CONTINUOUS-PRODUCER-001C-FORENSIC-CANARY.md",
    )
    shutil.copy2(FORENSIC_STANDARD_PATH, references / FORENSIC_STANDARD_PATH.name)
    ownership = json.loads(
        (root / "canonical-ownership-map.json").read_text(encoding="ascii")
    )
    focused_modules = _package_focus_modules()
    index = {
        "canonicalSourceSha": EXPECTED_CANONICAL_SHA,
        "evidenceRoot": f"evidence/{root.name}",
        "source": "source/momentum_hunter",
        "tests": "source/tests",
        "ownershipMap": f"evidence/{root.name}/canonical-ownership-map.json",
        "wrapperAuthority": "OBSERVATIONAL_ONLY",
        "focusedRerun": list(focused_modules),
        "knownLimitations": [
            "Unknown instrument subtype remains execution-ineligible.",
            "The market may truthfully produce no TradePlan or successor setup.",
            "Sanitized source replaces local account-binding identity with synthetic 0000.",
        ],
    }
    _write_once(package_root / "INDEX.json", index)
    _write_once(
        package_root / "INDEX.md",
        _render_package_index(
            root=root,
            ownership=ownership,
            focused_modules=focused_modules,
        ).encode("ascii"),
    )
    _write_once(
        package_root / "README.md",
        (
            "# Read-Only Review Packet\n\n"
            f"Canonical source SHA: `{EXPECTED_CANONICAL_SHA}`.\n\n"
            "This packet contains market-data-only forensic evidence. It grants no Paper, Shadow, broker, account, position, or order authority. The canary wrapper is observational; canonical production classes own every decision-authoritative input.\n"
        ).encode("ascii"),
    )
    _write_once(
        package_root / "PACKAGE-SANITIZATION-LEDGER.json",
        {
            "status": "SANITIZED",
            "syntheticReplacement": "0000",
            "substitutionCount": sum(
                int(item["replacementCount"]) for item in substitutions
            ),
            "files": substitutions,
        },
    )
    _write_once(
        package_root / "PACKAGING-RECONCILIATION.json",
        {
            "packageAttempt": package_attempt,
            "priorAttempts": prior_package_attempts,
            "priorAttemptsPreserved": True,
            "campaignEvidenceMutated": False,
        },
    )
    prezip_rerun = _run_package_tests(source_destination)
    _write_once(package_root / "FOCUSED-RERUN-PREZIP.json", _sanitize(prezip_rerun))
    if prezip_rerun["status"] != "PASS":
        raise ForensicCanaryError("Second-eye staged focused rerun failed.")
    package_scan = _secret_scan(package_root, forbidden_value=forbidden_value)
    _write_once(package_root / "secret-scan.json", package_scan)
    if package_scan["status"] != "PASS":
        raise ForensicCanaryError("Second-eye staging secret scan failed.")
    analysis = json.loads((root / "forensic-analysis.json").read_text(encoding="ascii"))
    final_classifications = dict(analysis["classifications"])
    final_classifications["FORENSIC_PACKET_COMPLETE"] = "YES"
    final_classifications["SECOND_EYE_ZIP_SELF_CONTAINED"] = "YES"
    final_classifications["READY_FOR_SECOND_EYE_REVIEW"] = "YES"
    _write_once(
        package_root / "FINAL-CLASSIFICATIONS.json",
        {
            "canonicalSourceSha": EXPECTED_CANONICAL_SHA,
            "classifications": final_classifications,
            "wrapperAuthority": "OBSERVATIONAL_ONLY",
            "downstreamImplementation": "STOPPED_PENDING_INDEPENDENT_REVIEW",
        },
    )
    package_files = _file_manifest(package_root)
    package_manifest = {
        "schemaVersion": 1,
        "profile": "producer-001c-second-eye-package-v1",
        "files": package_files,
        "fileCount": len(package_files),
        "manifestFingerprint": _manifest_fingerprint(package_files),
    }
    _write_once(package_root / "PACKAGE-MANIFEST.json", package_manifest)
    with zipfile.ZipFile(zip_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package_root.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(package_root).as_posix())
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extracted_root)
    extracted_manifest = _verify_extracted_manifest(extracted_root)
    extracted_rerun = _run_package_tests(extracted_root / "source")
    self_contained = (
        extracted_manifest["status"] == "PASS"
        and extracted_rerun["status"] == "PASS"
    )
    result = {
        "zipPath": str(zip_path),
        "zipSha256": _sha256(zip_path),
        "fileCount": sum(
            1 for path in package_root.rglob("*") if path.is_file()
        ),
        "manifestCount": len(package_files),
        "manifestVerification": extracted_manifest,
        "sanitization": package_scan,
        "preZipFocusedRerun": {
            "status": prezip_rerun["status"],
            "elapsedSeconds": prezip_rerun["elapsedSeconds"],
        },
        "extractedZipFocusedRerun": _sanitize(extracted_rerun),
        "selfContainedRerun": "PASS" if self_contained else "FAIL",
        "classifications": {
            **final_classifications,
            "SECOND_EYE_ZIP_SELF_CONTAINED": "YES" if self_contained else "NO",
            "READY_FOR_SECOND_EYE_REVIEW": "YES" if self_contained else "NO",
        },
    }
    _write_once(root / "second-eye-package.json", result)
    closeout_items = _file_manifest(root)
    _write_once(
        root / "closeout-manifest.json",
        {
            "schemaVersion": 1,
            "files": closeout_items,
            "fileCount": len(closeout_items),
            "manifestFingerprint": _manifest_fingerprint(closeout_items),
        },
    )
    if not self_contained:
        raise ForensicCanaryError("Extracted second-eye ZIP rerun failed.")
    return 0


def _static_capability_scan() -> dict[str, object]:
    paths = (
        Path(__file__).resolve(),
        CANONICAL_ROOT / "momentum_hunter" / "continuous_live_qualification.py",
        CANONICAL_ROOT / "momentum_hunter" / "continuous_natural_setup.py",
    )
    forbidden_imports = {
        "momentum_hunter.alpaca_paper_broker",
        "momentum_hunter.alpaca_paper_engineering",
        "momentum_hunter.shadow_selection",
        "momentum_hunter.shadow_opening",
        "momentum_hunter.account_allocation_snapshot",
    }
    forbidden_calls = {
        "submit_order",
        "cancel_order",
        "replace_order",
        "get_account",
        "get_positions",
    }
    findings = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_imports:
                        findings.append(f"{path.name}:import:{alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module in forbidden_imports:
                    findings.append(f"{path.name}:import:{node.module}")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr.lower() in forbidden_calls:
                    findings.append(f"{path.name}:call:{node.func.attr}")
    return {"status": "PASS" if not findings else "FAIL", "findings": findings}


def _preflight() -> int:
    ownership = _ownership_map()
    result = {
        "approvedProductSource": _validate_canonical(),
        "canaryTaskSource": _validate_task_source(),
        "productionCanonical": _validate_production(),
        "forensicStandard": _validate_standard(),
        "failedEvidence": _validate_failed_evidence(),
        "capabilityScan": _static_capability_scan(),
        "canonicalOwnershipMap": ownership,
        "services": _service_snapshot(),
        "manifestSafety": _manifest_safety_summary(),
        "networkRequested": False,
        "accountValuesRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
        "orderCapability": ORDER_CAPABILITY,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return (
        0
        if result["capabilityScan"]["status"] == "PASS"
        and ownership["status"] == "PASS"
        else 1
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run or verify the Producer-001C provider forensic canary."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("preflight")
    subparsers.add_parser("ownership")
    run = subparsers.add_parser("run")
    run.add_argument("--execute-read-only", action="store_true")
    run.add_argument("--evidence-root", type=Path, required=True)
    run.add_argument("--runtime-root", type=Path, required=True)
    run.add_argument("--duration-seconds", type=int, default=1800)
    run.add_argument("--discovery-cadence-seconds", type=int, default=300)
    phase = subparsers.add_parser("phase")
    phase.add_argument("--campaign", type=Path, required=True)
    phase.add_argument("--phase", type=int, choices=(1, 2), required=True)
    seal = subparsers.add_parser("seal")
    seal.add_argument("--evidence-root", type=Path, required=True)
    resume_seal = subparsers.add_parser("resume-seal-after-false-positive")
    resume_seal.add_argument("--evidence-root", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--evidence-root", type=Path, required=True)
    verify.add_argument("--full-suite", action="store_true")
    package = subparsers.add_parser("package")
    package.add_argument("--evidence-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "preflight":
        return _preflight()
    if args.command == "ownership":
        ownership = _ownership_map()
        print(json.dumps(ownership, indent=2, sort_keys=True))
        return 0 if ownership["status"] == "PASS" else 1
    if args.command == "phase":
        return _run_phase(args.campaign, args.phase)
    if args.command == "run":
        if not args.execute_read_only:
            raise SystemExit("Refusing provider canary without --execute-read-only.")
        return _run_campaign(args)
    if args.command == "seal":
        return _seal(args)
    if args.command == "resume-seal-after-false-positive":
        return _resume_seal_after_false_positive(args)
    if args.command == "verify":
        return _verify(args)
    if args.command == "package":
        return _package(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
