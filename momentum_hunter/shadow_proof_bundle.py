from __future__ import annotations

"""Build and finalize the nontransmitting Official Shadow selector proof bundle."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.config import DATA_DIR
from momentum_hunter.schwab_market_data import (
    LIVE_SCHWAB_QUOTE_PROOF_ORIGIN,
    REGULAR_MARKET_QUOTE_PROOF_SCHEMA_VERSION,
    SCHWAB_QUOTE_SOURCE,
    normalize_symbols,
)
from momentum_hunter.shadow_market_validity import (
    MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
    MAX_SELECTOR_PROOF_ARTIFACT_BYTES,
    SELECTOR_PROOF_ARTIFACT_SCHEMA_VERSION,
    SHADOW_SELECTOR_ARM_REQUIRED_PROOFS,
    canonical_candidate_rows,
    entry_window_findings,
    parse_datetime,
    read_stable_selector_artifact,
    runtime_build_hash,
    shadow_constitution_hash,
    validate_report_clocks,
    validate_selector_proof_artifact,
)
from momentum_hunter.shadow_selection import load_report_object
from momentum_hunter.shadow_trading import (
    SHADOW_STATE_PATH,
    ShadowStateStore,
    ShadowTradingService,
    selector_proof_bundle_paths,
)
from momentum_hunter.trade_planning import REPORT_SCHEMA_VERSION


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = DATA_DIR / "reports"
CAPTURES_DIR = DATA_DIR / "captures"
VISUAL_PROOF_PATH = (
    Path("docs")
    / "argus-office"
    / "reports"
    / "releases"
    / "ARGUS-SHADOW-004-official-sample-active-proof.jpg"
)
VERIFICATION_QUEUE_PATH = (
    Path("docs") / "argus-office" / "VERIFICATION_QUEUE.md"
)
STATIC_PROOF_NAMES = tuple(
    name
    for name in SHADOW_SELECTOR_ARM_REQUIRED_PROOFS
    if name != "fresh_quote_boundary"
)
REQUIRED_INTEGRATION_COMMITS = ("307a2e1", "79e75b2")

STATIC_TEST_GATES: dict[str, tuple[str, ...]] = {
    "counterfactuals": (
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_cycle_preserves_all_rejections_random_candidate_and_benchmarks",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_workspace_records_counterfactual_observations_without_source_mutation",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_counterfactual_holding_window_finalization_is_immutable",
    ),
    "cycle_accounting": (
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_expected_cycle_accounting_infers_restart_downtime_and_links_outcome",
        "tests.test_engine_host.EngineHostRuntimeTests."
        "test_selection_failure_still_advances_existing_shadow_observations",
        "tests.test_engine_host.EngineHostRuntimeTests."
        "test_observation_failure_closes_attempt_as_post_collection_failure",
        "tests.test_engine_host_client.EngineHostClientTests."
        "test_immediate_cycle_uses_existing_authenticated_loopback_host",
        "tests.test_scheduling_policy.SchedulingPolicyTests."
        "test_shadow_opening_capture_has_one_narrow_market_day_window",
        "tests.test_scheduling_policy.SchedulingPolicyTests."
        "test_shadow_capture_is_distinct_and_schedules_for_835_central",
        "tests.test_capture_job.CaptureJobTradePlanHandoffTests."
        "test_main_triggers_one_host_cycle_only_for_new_shadow_report",
        "tests.test_capture_job.CaptureJobTradePlanHandoffTests."
        "test_main_does_not_trigger_host_cycle_for_duplicate_shadow_report",
        "tests.test_capture_job.CaptureJobTradePlanHandoffTests."
        "test_duplicate_shadow_report_retries_when_receipt_is_missing",
        "tests.test_capture_job.CaptureJobTradePlanHandoffTests."
        "test_shadow_handoff_receipt_is_write_once_and_report_bound",
        "tests.test_capture_job.CaptureJobTradePlanHandoffTests."
        "test_shadow_capture_has_distinct_immutable_report_identity",
        "tests.test_capture_job.CaptureJobTradePlanHandoffTests."
        "test_windows_task_wires_distinct_shadow_opening_capture",
    ),
    "freshness_matrix": (
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_multi_clock_freshness_rejects_each_stale_or_ambiguous_boundary",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_provider_schema_quote_identity_and_latency_evidence_are_frozen",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_quote_boundary_rejects_stale_target_stop_spread_halt_and_session",
    ),
    "opportunity_deduplication": (
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_completed_symbol_and_opportunity_cannot_reenter_same_day",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_same_capture_is_idempotent_even_when_report_bytes_change",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_exact_report_repeat_returns_cycle_without_new_trade",
    ),
    "portfolio_policy": (
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_one_active_position_blocks_every_later_report",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_frozen_daily_loss_ceiling_blocks_new_entry",
        "tests.test_shadow_trading.ShadowTradingLifecycleTests."
        "test_buying_power_and_position_limits_reject_before_fill",
    ),
    "ranking_and_tie_breaks": (
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_canonical_rank_is_primary_and_persisted_order_cannot_choose",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_score_and_symbol_are_stable_tie_breakers",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_decimal_scores_are_not_truncated_and_duplicate_identity_fails_closed",
    ),
    "secret_transmission_block": (
        "tests.test_shadow_sample_readiness.ShadowSampleReadinessTests."
        "test_service_exposes_no_provider_network_or_transmitting_method",
        "tests.test_shadow_trading.ShadowWorkspaceIntegrationTests."
        "test_engine_host_exposes_idempotent_shadow_commands_without_broker_capability",
        "tests.test_schwab_market_data.SchwabMarketDataQuoteSourceTests."
        "test_source_contains_one_marketdata_url_and_no_account_or_order_endpoint",
        "tests.test_engine_host.EngineHostProtocolTests."
        "test_protocol_returns_versioned_snapshot_and_no_execution_capability",
    ),
    "session_and_forced_exit": (
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_entry_window_market_calendar_and_forced_exit_deadline_are_frozen",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_official_position_is_forced_flat_and_never_held_overnight",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_unfilled_official_entry_is_cancelled_after_entry_window",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_next_session_observation_forces_flat_instead_of_overnight_hold",
    ),
    "warning_severity": (
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_informational_provider_warning_does_not_hide_fresh_quote",
        "tests.test_shadow_selection.ShadowMarketValiditySelectionTests."
        "test_unknown_and_structural_warnings_fail_closed",
    ),
}


class SelectorProofBundleError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ProofContext:
    sample_version: str
    activation_hash: str
    activated_at: datetime
    constitution_hash: str
    build_hash: str


@dataclass(frozen=True)
class CandidateReportEvidence:
    candidate: str
    report_path: Path
    report_bytes: bytes
    report_sha256: str
    source_capture_path: Path
    source_capture_bytes: bytes
    source_capture_sha256: str
    report_generated_at: str
    source_capture_time: str


CommandRunner = Callable[[Sequence[str], Path, float], CommandResult]


def run_command(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: float,
) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        check=False,
    )
    return CommandResult(
        command=tuple(str(item) for item in command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def prepare_static_selector_proof_bundle(
    bundle: Path,
    *,
    repo_root: Path = PROJECT_ROOT,
    state_path: Path = SHADOW_STATE_PATH,
    verified_at: datetime | None = None,
    command_runner: CommandRunner = run_command,
) -> dict[str, object]:
    root = repo_root.resolve()
    target, temporary = new_bundle_paths(bundle)
    context = load_proof_context(state_path)
    timestamp = require_current_timestamp(
        verified_at or datetime.now(timezone.utc),
        context,
    )
    try:
        temporary.mkdir(parents=False)
        evidence_root = temporary / "evidence"
        evidence_root.mkdir()

        canonical_evidence = collect_canonical_git_evidence(
            root,
            command_runner=command_runner,
            verified_at=timestamp,
        )
        canonical_path = evidence_root / "canonical_merge_backup.json"
        write_json(canonical_path, canonical_evidence)
        write_proof_artifact(
            temporary,
            "canonical_merge_backup",
            "Canonical master is clean, synchronized, and contains the required stack.",
            (canonical_path,),
            context=context,
            verified_at=timestamp,
        )

        visual_paths = collect_visual_acceptance_evidence(
            root,
            evidence_root,
            verified_at=timestamp,
        )
        write_proof_artifact(
            temporary,
            "visual_acceptance",
            "Steven's SHADOW-004 visual acceptance and retained UI proof are present.",
            visual_paths,
            context=context,
            verified_at=timestamp,
        )

        for proof_name, test_ids in STATIC_TEST_GATES.items():
            evidence = run_test_gate(
                proof_name,
                test_ids,
                root,
                command_runner=command_runner,
                verified_at=timestamp,
            )
            evidence_path = evidence_root / f"{proof_name}.json"
            write_json(evidence_path, evidence)
            write_proof_artifact(
                temporary,
                proof_name,
                f"Canonical focused checks passed for {proof_name}.",
                (evidence_path,),
                context=context,
                verified_at=timestamp,
            )

        for proof_name in STATIC_PROOF_NAMES:
            validate_static_artifact(
                temporary / f"{proof_name}.json",
                proof_name=proof_name,
                context=context,
                verified_at=timestamp,
            )

        temporary.replace(target)
    except Exception:
        cleanup_temporary_bundle(temporary, target.parent)
        raise

    return {
        "bundleState": "STATIC_READY",
        "bundle": str(target),
        "sampleVersion": context.sample_version,
        "activationHash": context.activation_hash,
        "constitutionHash": context.constitution_hash,
        "runtimeBuildHash": context.build_hash,
        "proofArtifactCount": len(STATIC_PROOF_NAMES),
        "missingProofArtifacts": ["fresh_quote_boundary"],
        "stateMutated": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }


def finalize_selector_proof_bundle(
    bundle: Path,
    *,
    quote_proof_path: Path,
    report_path: Path,
    repo_root: Path = PROJECT_ROOT,
    state_path: Path = SHADOW_STATE_PATH,
    reports_dir: Path = REPORTS_DIR,
    captures_dir: Path = CAPTURES_DIR,
    finalized_at: datetime | None = None,
    command_runner: CommandRunner = run_command,
) -> dict[str, object]:
    root = repo_root.resolve()
    target = require_existing_bundle(bundle)
    context = load_proof_context(state_path)
    timestamp = require_current_timestamp(
        finalized_at or datetime.now(timezone.utc),
        context,
    )
    verify_canonical_git_still_matches(
        target,
        root,
        command_runner=command_runner,
    )
    for proof_name in STATIC_PROOF_NAMES:
        validate_static_artifact(
            target / f"{proof_name}.json",
            proof_name=proof_name,
            context=context,
            verified_at=timestamp,
        )

    report_evidence = read_and_validate_candidate_report(
        report_path,
        reports_dir=reports_dir,
        captures_dir=captures_dir,
        context=context,
        finalized_at=timestamp,
    )
    quote_payload, quote_bytes = read_and_validate_live_quote_proof(
        quote_proof_path,
        candidate=report_evidence.candidate,
        finalized_at=timestamp,
    )

    evidence_root = target / "evidence"
    evidence_path = evidence_root / "fresh_quote_boundary.json"
    report_copy_path = evidence_root / "fresh_quote_source_report.json"
    capture_copy_path = evidence_root / "fresh_quote_source_capture.json"
    binding_path = evidence_root / "fresh_quote_report_binding.json"
    proof_path = target / "fresh_quote_boundary.json"
    fresh_paths = (
        evidence_path,
        report_copy_path,
        capture_copy_path,
        binding_path,
        proof_path,
    )
    if any(path.exists() for path in fresh_paths):
        raise SelectorProofBundleError(
            "Fresh quote boundary evidence already exists in this bundle."
        )
    try:
        evidence_path.write_bytes(quote_bytes)
        report_copy_path.write_bytes(report_evidence.report_bytes)
        capture_copy_path.write_bytes(report_evidence.source_capture_bytes)
        write_json(
            binding_path,
            {
                "schemaVersion": 1,
                "proof": "fresh_quote_boundary",
                "status": "PASS",
                "verifiedAt": timestamp.isoformat(),
                "candidate": report_evidence.candidate,
                "sourceReport": report_evidence.report_path.name,
                "sourceReportSha256": report_evidence.report_sha256,
                "sourceReportGeneratedAt": (
                    report_evidence.report_generated_at
                ),
                "sourceCapture": report_evidence.source_capture_path.name,
                "sourceCaptureSha256": (
                    report_evidence.source_capture_sha256
                ),
                "sourceCaptureTime": report_evidence.source_capture_time,
                "quoteCheckedAt": quote_payload["checkedAt"],
                "transmitting": False,
                "orderTransmission": "UNAVAILABLE",
            },
        )
        write_proof_artifact(
            target,
            "fresh_quote_boundary",
            (
                "The highest-ranked candidate from the latest fresh canonical "
                "report and SPY/IWM passed the live Schwab 30-second boundary."
            ),
            (
                binding_path,
                report_copy_path,
                capture_copy_path,
                evidence_path,
            ),
            context=context,
            verified_at=timestamp,
        )
        service = ShadowTradingService(store=ShadowStateStore(state_path))
        proofs, verified_at = service.verify_automatic_selector_prerequisites(
            selector_proof_bundle_paths(target),
            verified_at=timestamp,
        )
    except Exception:
        for path in reversed(fresh_paths):
            path.unlink(missing_ok=True)
        raise

    return {
        "bundleState": "READY_TO_ARM",
        "bundle": str(target),
        "verifiedAt": verified_at.isoformat(),
        "quoteCheckedAt": quote_payload["checkedAt"],
        "candidate": report_evidence.candidate,
        "sourceReport": str(report_evidence.report_path),
        "sourceReportSha256": report_evidence.report_sha256,
        "sourceCapture": str(report_evidence.source_capture_path),
        "sourceCaptureSha256": report_evidence.source_capture_sha256,
        "sampleVersion": context.sample_version,
        "activationHash": context.activation_hash,
        "constitutionHash": context.constitution_hash,
        "runtimeBuildHash": context.build_hash,
        "proofArtifactCount": len(proofs.hashes),
        "proofs": proofs.hashes,
        "stateMutated": False,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }


def load_proof_context(state_path: Path) -> ProofContext:
    service = ShadowTradingService(store=ShadowStateStore(state_path))
    activation = service.sample_activation
    if activation is None:
        raise SelectorProofBundleError(
            "Selector proof preparation requires the immutable sample activation."
        )
    activation_path, activation_bytes = read_stable_selector_artifact(
        service.activation_store.path,
        proof_name="sample_activation",
        artifact_role="activation",
        maximum_bytes=MAX_SELECTOR_PROOF_ARTIFACT_BYTES,
    )
    if activation_path != service.activation_store.path.resolve():
        raise SelectorProofBundleError("Sample activation path is not canonical.")
    activated_at = parse_datetime(activation.activated_at)
    if activated_at is None or activated_at.utcoffset() is None:
        raise SelectorProofBundleError(
            "Sample activation timestamp is invalid."
        )
    return ProofContext(
        sample_version=activation.sample_metadata.sample_version,
        activation_hash=hashlib.sha256(activation_bytes).hexdigest(),
        activated_at=activated_at,
        constitution_hash=shadow_constitution_hash(),
        build_hash=runtime_build_hash(),
    )


def require_current_timestamp(
    value: datetime,
    context: ProofContext,
) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SelectorProofBundleError(
            "Proof verification timestamp requires a UTC offset."
        )
    if value < context.activated_at:
        raise SelectorProofBundleError(
            "Proof verification cannot predate sample activation."
        )
    return value


def new_bundle_paths(bundle: Path) -> tuple[Path, Path]:
    target = bundle.expanduser().resolve()
    if target.exists():
        raise SelectorProofBundleError(
            f"Selector proof bundle already exists: {target}"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.tmp"
    if temporary.exists() or temporary.parent.resolve() != target.parent.resolve():
        raise SelectorProofBundleError("Selector proof temporary path is unsafe.")
    return target, temporary


def require_existing_bundle(bundle: Path) -> Path:
    if bundle.is_symlink():
        raise SelectorProofBundleError(
            "Selector proof bundle cannot be a symlink."
        )
    target = bundle.expanduser().resolve(strict=True)
    if not target.is_dir():
        raise SelectorProofBundleError(
            "Selector proof bundle is not a directory."
        )
    return target


def cleanup_temporary_bundle(temporary: Path, intended_parent: Path) -> None:
    if (
        temporary.exists()
        and temporary.parent.resolve() == intended_parent.resolve()
        and temporary.name.startswith(".")
        and temporary.name.endswith(".tmp")
    ):
        shutil.rmtree(temporary)


def collect_canonical_git_evidence(
    repo_root: Path,
    *,
    command_runner: CommandRunner,
    verified_at: datetime,
) -> dict[str, object]:
    branch = run_checked(
        ("git", "branch", "--show-current"),
        repo_root,
        command_runner,
    ).stdout.strip()
    status = run_checked(
        ("git", "status", "--porcelain"),
        repo_root,
        command_runner,
    ).stdout
    head = run_checked(
        ("git", "rev-parse", "HEAD"),
        repo_root,
        command_runner,
    ).stdout.strip()
    origin_head = run_checked(
        ("git", "rev-parse", "origin/master"),
        repo_root,
        command_runner,
    ).stdout.strip()
    if branch != "master" or status.strip() or head != origin_head:
        raise SelectorProofBundleError(
            "Canonical merge proof requires clean synchronized master."
        )
    for commit in REQUIRED_INTEGRATION_COMMITS:
        run_checked(
            ("git", "merge-base", "--is-ancestor", commit, "HEAD"),
            repo_root,
            command_runner,
        )
    return {
        "schemaVersion": 1,
        "proof": "canonical_merge_backup",
        "status": "PASS",
        "verifiedAt": verified_at.isoformat(),
        "branch": branch,
        "head": head,
        "originMaster": origin_head,
        "worktreeClean": True,
        "requiredCommits": list(REQUIRED_INTEGRATION_COMMITS),
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }


def verify_canonical_git_still_matches(
    bundle: Path,
    repo_root: Path,
    *,
    command_runner: CommandRunner,
) -> None:
    evidence_path = bundle / "evidence" / "canonical_merge_backup.json"
    _, evidence_bytes = read_stable_selector_artifact(
        evidence_path,
        proof_name="canonical_merge_backup",
        artifact_role="evidence",
        maximum_bytes=MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
    )
    try:
        evidence = json.loads(evidence_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SelectorProofBundleError(
            "Canonical merge evidence is malformed."
        ) from None
    head = run_checked(
        ("git", "rev-parse", "HEAD"),
        repo_root,
        command_runner,
    ).stdout.strip()
    origin_head = run_checked(
        ("git", "rev-parse", "origin/master"),
        repo_root,
        command_runner,
    ).stdout.strip()
    branch = run_checked(
        ("git", "branch", "--show-current"),
        repo_root,
        command_runner,
    ).stdout.strip()
    status = run_checked(
        ("git", "status", "--porcelain"),
        repo_root,
        command_runner,
    ).stdout.strip()
    if (
        branch != "master"
        or status
        or head != origin_head
        or evidence.get("head") != head
        or evidence.get("originMaster") != origin_head
    ):
        raise SelectorProofBundleError(
            "Canonical master changed after static proof preparation."
        )


def collect_visual_acceptance_evidence(
    repo_root: Path,
    evidence_root: Path,
    *,
    verified_at: datetime,
) -> tuple[Path, ...]:
    queue_path = repo_root / VERIFICATION_QUEUE_PATH
    screenshot_path = repo_root / VISUAL_PROOF_PATH
    queue_resolved, queue_bytes = read_stable_selector_artifact(
        queue_path,
        proof_name="visual_acceptance",
        artifact_role="verification-queue",
        maximum_bytes=MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
    )
    screenshot_resolved, screenshot_bytes = read_stable_selector_artifact(
        screenshot_path,
        proof_name="visual_acceptance",
        artifact_role="screenshot",
        maximum_bytes=MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
    )
    queue_text = queue_bytes.decode("utf-8")
    required_text = (
        "ARGUS-SHADOW-004 Official Sample Activation",
        "Status: `COMPLETE`; `AUTOMATED_PASS`; `MANUAL_PASS`",
        "Steven completed and accepted these checks on 2026-07-26",
    )
    if any(value not in queue_text for value in required_text):
        raise SelectorProofBundleError(
            "Verification Queue does not prove SHADOW-004 manual acceptance."
        )
    if (
        len(screenshot_bytes) < 10_000
        or not screenshot_bytes.startswith(b"\xff\xd8")
        or not screenshot_bytes.endswith(b"\xff\xd9")
    ):
        raise SelectorProofBundleError(
            "SHADOW-004 visual proof is not a valid retained JPEG."
        )
    copied_screenshot = evidence_root / screenshot_resolved.name
    copied_screenshot.write_bytes(screenshot_bytes)
    summary_path = evidence_root / "visual_acceptance.json"
    write_json(
        summary_path,
        {
            "schemaVersion": 1,
            "proof": "visual_acceptance",
            "status": "PASS",
            "verifiedAt": verified_at.isoformat(),
            "verificationQueue": str(
                queue_resolved.relative_to(repo_root)
            ),
            "verificationQueueSha256": hashlib.sha256(
                queue_bytes
            ).hexdigest(),
            "screenshot": str(screenshot_resolved.relative_to(repo_root)),
            "screenshotSha256": hashlib.sha256(
                screenshot_bytes
            ).hexdigest(),
            "screenshotBytes": len(screenshot_bytes),
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        },
    )
    return summary_path, copied_screenshot


def run_test_gate(
    proof_name: str,
    test_ids: Sequence[str],
    repo_root: Path,
    *,
    command_runner: CommandRunner,
    verified_at: datetime,
) -> dict[str, object]:
    command = (
        sys.executable,
        "-B",
        "-m",
        "unittest",
        "-q",
        *test_ids,
    )
    result = command_runner(command, repo_root, 180.0)
    if result.returncode != 0:
        raise SelectorProofBundleError(
            f"Focused proof checks failed for {proof_name}."
        )
    output = f"{result.stdout}\n{result.stderr}"
    if "OK" not in output or "Ran " not in output:
        raise SelectorProofBundleError(
            f"Focused proof checks returned ambiguous output for {proof_name}."
        )
    return {
        "schemaVersion": 1,
        "proof": proof_name,
        "status": "PASS",
        "verifiedAt": verified_at.isoformat(),
        "command": list(result.command),
        "testIds": list(test_ids),
        "returnCode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }


def run_checked(
    command: Sequence[str],
    repo_root: Path,
    command_runner: CommandRunner,
) -> CommandResult:
    result = command_runner(command, repo_root, 60.0)
    if result.returncode != 0:
        raise SelectorProofBundleError(
            f"Proof command failed: {' '.join(command)}"
        )
    return result


def write_proof_artifact(
    bundle: Path,
    proof_name: str,
    summary: str,
    evidence_paths: Sequence[Path],
    *,
    context: ProofContext,
    verified_at: datetime,
) -> Path:
    if proof_name not in SHADOW_SELECTOR_ARM_REQUIRED_PROOFS:
        raise SelectorProofBundleError(
            f"Unsupported selector proof name: {proof_name}"
        )
    evidence: list[dict[str, str]] = []
    bundle_root = bundle.resolve()
    for evidence_path in evidence_paths:
        resolved = evidence_path.resolve(strict=True)
        if not resolved.is_relative_to(bundle_root):
            raise SelectorProofBundleError(
                f"Proof evidence is outside the bundle: {proof_name}"
            )
        payload = resolved.read_bytes()
        evidence.append(
            {
                "path": resolved.relative_to(bundle_root).as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    path = bundle / f"{proof_name}.json"
    write_json(
        path,
        {
            "activation_hash": context.activation_hash,
            "build_hash": context.build_hash,
            "constitution_hash": context.constitution_hash,
            "evidence": evidence,
            "proof_name": proof_name,
            "schema_version": SELECTOR_PROOF_ARTIFACT_SCHEMA_VERSION,
            "sample_version": context.sample_version,
            "status": "PASS",
            "summary": summary,
            "verified_at": verified_at.isoformat(),
        },
    )
    return path


def validate_static_artifact(
    path: Path,
    *,
    proof_name: str,
    context: ProofContext,
    verified_at: datetime,
) -> None:
    resolved, payload = read_stable_selector_artifact(
        path,
        proof_name=proof_name,
        artifact_role="proof",
        maximum_bytes=MAX_SELECTOR_PROOF_ARTIFACT_BYTES,
    )
    validate_selector_proof_artifact(
        proof_name,
        resolved,
        payload,
        sample_version=context.sample_version,
        activation_hash=context.activation_hash,
        activated_at=context.activated_at,
        constitution_hash=context.constitution_hash,
        build_hash=context.build_hash,
        armed_at=verified_at,
    )


def read_and_validate_candidate_report(
    path: Path,
    *,
    reports_dir: Path,
    captures_dir: Path,
    context: ProofContext,
    finalized_at: datetime,
) -> CandidateReportEvidence:
    if path.is_symlink():
        raise SelectorProofBundleError(
            "Fresh quote source report cannot be a symlink."
        )
    try:
        canonical_reports_dir = reports_dir.expanduser().resolve(strict=True)
        canonical_captures_dir = captures_dir.expanduser().resolve(strict=True)
    except OSError as exc:
        raise SelectorProofBundleError(
            "Canonical report or capture directory is unavailable."
        ) from exc
    if (
        not canonical_reports_dir.is_dir()
        or not canonical_captures_dir.is_dir()
    ):
        raise SelectorProofBundleError(
            "Canonical report or capture path is not a directory."
        )
    report_path, report_bytes = read_stable_selector_artifact(
        path,
        proof_name="fresh_quote_boundary",
        artifact_role="source-report",
        maximum_bytes=MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
    )
    if (
        report_path.parent != canonical_reports_dir
        or not report_path.name.startswith("trade-plan-briefing-")
        or report_path.suffix.lower() != ".json"
    ):
        raise SelectorProofBundleError(
            "Fresh quote proof requires a canonical scheduled TradePlan report."
        )
    scheduled_reports = tuple(
        item
        for item in canonical_reports_dir.glob(
            "trade-plan-briefing-*.json"
        )
        if item.is_file() and not item.is_symlink()
    )
    if not scheduled_reports:
        raise SelectorProofBundleError(
            "No canonical scheduled TradePlan report is available."
        )
    latest_report = max(
        scheduled_reports,
        key=lambda item: item.stat().st_mtime_ns,
    ).resolve(strict=True)
    if report_path != latest_report:
        raise SelectorProofBundleError(
            "Fresh quote proof report is not the latest canonical report."
        )

    try:
        report = load_report_object(report_bytes)
    except ValueError as exc:
        raise SelectorProofBundleError(str(exc)) from exc
    rows = report.get("candidates") or report.get("top_5_for_capital") or []
    if not isinstance(rows, list):
        raise SelectorProofBundleError(
            "Fresh quote proof report lacks a candidate collection."
        )
    try:
        canonical_rows = canonical_candidate_rows(rows)
    except ValueError as exc:
        raise SelectorProofBundleError(str(exc)) from exc
    if not canonical_rows:
        raise SelectorProofBundleError(
            "Fresh quote proof report has no canonical candidate."
        )
    candidate = str(canonical_rows[0][1].get("symbol", "")).strip().upper()
    if (
        candidate in {"SPY", "IWM"}
        or normalize_symbols((candidate,)) != (candidate,)
    ):
        raise SelectorProofBundleError(
            "Highest-ranked report candidate is invalid for quote proof."
        )

    metadata = (
        report.get("metadata", {})
        if isinstance(report.get("metadata"), dict)
        else {}
    )
    if (
        report.get("schema_version") != REPORT_SCHEMA_VERSION
        or not str(metadata.get("source_provider", "")).strip()
        or not str(metadata.get("source_capture_path", "")).strip()
        or not str(metadata.get("source_session", "")).strip()
    ):
        raise SelectorProofBundleError(
            "Fresh quote proof report identity is incomplete."
        )
    clock_findings = validate_report_clocks(
        metadata,
        decision_at=finalized_at,
    )
    session_findings = entry_window_findings(finalized_at)
    if clock_findings or session_findings:
        raise SelectorProofBundleError(
            "Fresh quote proof report is not currently eligible: "
            + " | ".join((*clock_findings, *session_findings))
        )
    report_at = parse_datetime(str(metadata.get("generated_at", "")))
    capture_at = parse_datetime(
        str(metadata.get("source_capture_time", ""))
    )
    if (
        report_at is None
        or capture_at is None
        or report_at < context.activated_at
        or capture_at < context.activated_at
    ):
        raise SelectorProofBundleError(
            "Fresh quote proof report predates the official sample activation."
        )

    supplied_capture = Path(
        str(metadata.get("source_capture_path", ""))
    ).expanduser()
    if supplied_capture.is_symlink():
        raise SelectorProofBundleError(
            "Fresh quote source capture cannot be a symlink."
        )
    capture_path, capture_bytes = read_stable_selector_artifact(
        supplied_capture,
        proof_name="fresh_quote_boundary",
        artifact_role="source-capture",
        maximum_bytes=MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
    )
    if not capture_path.is_relative_to(canonical_captures_dir):
        raise SelectorProofBundleError(
            "Fresh quote source capture is outside canonical capture storage."
        )
    try:
        capture = json.loads(capture_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SelectorProofBundleError(
            "Fresh quote source capture is not valid UTF-8 JSON."
        ) from None
    if not isinstance(capture, dict):
        raise SelectorProofBundleError(
            "Fresh quote source capture has an invalid shape."
        )
    source_rows = capture.get("candidates")
    report_symbols = {
        str(row.get("symbol", "")).strip().upper()
        for row in rows
        if isinstance(row, dict)
    }
    source_symbols = (
        {
            str(row.get("ticker") or row.get("symbol") or "").strip().upper()
            for row in source_rows
            if isinstance(row, dict)
        }
        if isinstance(source_rows, list)
        else set()
    )
    if (
        str(capture.get("capture_time", ""))
        != str(metadata.get("source_capture_time", ""))
        or str(capture.get("session", "")).strip()
        != str(metadata.get("source_session", "")).strip()
        or not isinstance(source_rows, list)
        or len(source_rows) != len(rows)
        or "" in report_symbols
        or "" in source_symbols
        or report_symbols != source_symbols
    ):
        raise SelectorProofBundleError(
            "Fresh quote report does not match its immutable source capture."
        )
    return CandidateReportEvidence(
        candidate=candidate,
        report_path=report_path,
        report_bytes=report_bytes,
        report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        source_capture_path=capture_path,
        source_capture_bytes=capture_bytes,
        source_capture_sha256=hashlib.sha256(capture_bytes).hexdigest(),
        report_generated_at=str(metadata.get("generated_at", "")),
        source_capture_time=str(metadata.get("source_capture_time", "")),
    )


def read_and_validate_live_quote_proof(
    path: Path,
    *,
    candidate: str,
    finalized_at: datetime,
) -> tuple[Mapping[str, object], bytes]:
    _, payload = read_stable_selector_artifact(
        path,
        proof_name="fresh_quote_boundary",
        artifact_role="quote-proof",
        maximum_bytes=MAX_SELECTOR_EVIDENCE_ARTIFACT_BYTES,
    )
    try:
        proof = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SelectorProofBundleError(
            "Fresh quote proof is not valid UTF-8 JSON."
        ) from None
    expected_symbols = (candidate, "SPY", "IWM")
    requested_symbols = tuple(
        str(item).strip().upper()
        for item in proof.get("requestedSymbols", [])
    )
    checked_at = parse_datetime(str(proof.get("checkedAt", "")))
    quotes = proof.get("quotes")
    if (
        proof.get("schemaVersion")
        != REGULAR_MARKET_QUOTE_PROOF_SCHEMA_VERSION
        or proof.get("proofType")
        != "SCHWAB_REGULAR_MARKET_QUOTE_BOUNDARY"
        or proof.get("proofStatus") != "PASS"
        or proof.get("evidenceOrigin") != LIVE_SCHWAB_QUOTE_PROOF_ORIGIN
        or proof.get("productionSource") is not True
        or proof.get("source") != SCHWAB_QUOTE_SOURCE
        or proof.get("maximumQuoteAgeSeconds") != 30
        or requested_symbols != expected_symbols
        or checked_at is None
        or checked_at.utcoffset() is None
        or checked_at > finalized_at
        or (finalized_at - checked_at).total_seconds() > 30
        or proof.get("transmitting") is not False
        or proof.get("orderTransmission") != "UNAVAILABLE"
        or proof.get("accountDataIncluded") is not False
        or not isinstance(quotes, list)
        or len(quotes) != len(expected_symbols)
    ):
        raise SelectorProofBundleError(
            "Fresh quote proof context is invalid or not live production evidence."
        )
    rows = {str(row.get("symbol", "")).upper(): row for row in quotes}
    if set(rows) != set(expected_symbols):
        raise SelectorProofBundleError(
            "Fresh quote proof does not contain the exact candidate and benchmarks."
        )
    for symbol in expected_symbols:
        row = rows[symbol]
        timestamp = parse_datetime(str(row.get("timestamp", "")))
        bid = finite_number(row.get("bid"))
        ask = finite_number(row.get("ask"))
        if (
            row.get("status") != "PASS"
            or row.get("findings") != []
            or row.get("source") != SCHWAB_QUOTE_SOURCE
            or row.get("realtime") is not True
            or str(row.get("session", "")).lower() != "regular"
            or str(row.get("tradingState", "")).lower()
            not in {"open", "tradable"}
            or timestamp is None
            or timestamp.utcoffset() is None
            or timestamp > finalized_at
            or (finalized_at - timestamp).total_seconds() > 30
            or bid is None
            or ask is None
            or bid <= 0
            or ask < bid
        ):
            raise SelectorProofBundleError(
                f"Fresh quote proof row is invalid or stale: {symbol}."
            )
    serialized = payload.lower()
    for forbidden in (
        b"access_token",
        b"refresh_token",
        b"account_hash",
        b"client_secret",
    ):
        if forbidden in serialized:
            raise SelectorProofBundleError(
                "Fresh quote proof contains prohibited sensitive fields."
            )
    return proof, payload


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return parsed


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare and finalize the nontransmitting Official Shadow selector "
            "proof bundle."
        )
    )
    parser.add_argument("--state-path", type=Path, default=SHADOW_STATE_PATH)
    parser.add_argument("--repo-root", type=Path, default=PROJECT_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser(
        "prepare-static",
        help="Run static prerequisite checks and create 11 proof artifacts.",
    )
    prepare_parser.add_argument("--bundle", type=Path, required=True)
    finalize_parser = subparsers.add_parser(
        "finalize",
        help="Validate a live quote proof and complete the 12-artifact bundle.",
    )
    finalize_parser.add_argument("--bundle", type=Path, required=True)
    finalize_parser.add_argument("--quote-proof", type=Path, required=True)
    finalize_parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-static":
            result = prepare_static_selector_proof_bundle(
                args.bundle,
                repo_root=args.repo_root,
                state_path=args.state_path,
            )
        else:
            result = finalize_selector_proof_bundle(
                args.bundle,
                quote_proof_path=args.quote_proof,
                report_path=args.report,
                repo_root=args.repo_root,
                state_path=args.state_path,
            )
    except (
        OSError,
        SelectorProofBundleError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        result = {
            "bundleState": "FAIL",
            "failure": f"{type(exc).__name__}: {exc}",
            "stateMutated": False,
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
