from __future__ import annotations

"""Operator CLI for approved opening-runtime releases and future-job migration."""

import argparse
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Mapping

from momentum_hunter.automation_supervisor import (
    DEFAULT_MANIFEST_PATH,
    AutomationManifest,
    parse_manifest,
)
from momentum_hunter.opening_runtime_identity import (
    DEFAULT_CHANNEL,
    DEFAULT_RELEASE_ROOT,
    LOADED_RUNTIME_IDENTITY_MODULE_SHA256,
    OpeningRuntimeIdentityError,
    OpeningRuntimeReleaseStore,
    RuntimeIdentityContext,
    build_release_record,
    build_runtime_identity,
    current_git_identity,
    verify_execution_gate,
)


PROMOTION_CONFIRMATION = "PROMOTE APPROVED OPENING RUNTIME"
MIGRATION_CONFIRMATION = "MIGRATE FUTURE OPENINGS TO APPROVED RUNTIME"
DEFAULT_SERVICE_HOST = (
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "MomentumHunter"
    / "Automation"
    / "service"
    / "MomentumHunter.AutomationService.exe"
)
MINIMUM_SUPERVISOR_FRESHNESS_SECONDS = 30.0


def _context(manifest: AutomationManifest) -> RuntimeIdentityContext:
    if manifest.service_host_executable is None:
        raise OpeningRuntimeIdentityError(
            "SERVICE_HOST_IDENTITY_MISSING",
            "Manifest must identify the installed Automation Service executable.",
        )
    return RuntimeIdentityContext(
        repository_root=manifest.repository_root,
        python_executable=manifest.python_executable,
        powershell_executable=manifest.powershell_executable,
        state_directory=manifest.state_directory,
        engine_host_state_directory=manifest.engine_host_state_directory,
        poll_interval_seconds=manifest.poll_interval_seconds,
        service_host_executable=manifest.service_host_executable,
        release_root=manifest.opening_runtime_release_root,
    )


def _state_payload(manifest: AutomationManifest) -> dict[str, object]:
    path = manifest.state_directory / "automation-service-state.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpeningRuntimeIdentityError(
            "SUPERVISOR_STATE_UNAVAILABLE",
            "Automation Supervisor state is unavailable for release validation.",
        ) from exc
    if not isinstance(payload, dict):
        raise OpeningRuntimeIdentityError(
            "SUPERVISOR_STATE_INVALID",
            "Automation Supervisor state must be an object.",
        )
    return payload


def _require_fresh_supervisor_state(
    manifest: AutomationManifest,
    payload: Mapping[str, object],
    *,
    now: datetime | None = None,
) -> datetime:
    raw = str(payload.get("last_heartbeat_at", ""))
    try:
        heartbeat = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise OpeningRuntimeIdentityError(
            "SUPERVISOR_HEARTBEAT_INVALID",
            "Automation Supervisor heartbeat is missing or malformed.",
        ) from exc
    if heartbeat.tzinfo is None or heartbeat.utcoffset() is None:
        raise OpeningRuntimeIdentityError(
            "SUPERVISOR_HEARTBEAT_INVALID",
            "Automation Supervisor heartbeat must include timezone identity.",
        )
    observed_at = now or datetime.now().astimezone()
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise OpeningRuntimeIdentityError(
            "SUPERVISOR_HEARTBEAT_INVALID",
            "Supervisor freshness evaluation requires timezone-aware time.",
        )
    age = observed_at - heartbeat
    maximum_age = timedelta(
        seconds=max(
            MINIMUM_SUPERVISOR_FRESHNESS_SECONDS,
            manifest.poll_interval_seconds * 5,
        )
    )
    if age < timedelta(seconds=-5) or age > maximum_age:
        raise OpeningRuntimeIdentityError(
            "SUPERVISOR_HEARTBEAT_STALE",
            "Automation Supervisor heartbeat is not fresh enough for runtime approval.",
            details={
                "heartbeat": heartbeat.isoformat(),
                "observedAt": observed_at.isoformat(),
                "maximumAgeSeconds": maximum_age.total_seconds(),
            },
        )
    return heartbeat


def _origin_master(repository_root: Path) -> str:
    import subprocess

    result = subprocess.run(
        ["git", "-C", str(repository_root), "rev-parse", "origin/master"],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    value = result.stdout.strip()
    if result.returncode != 0 or len(value) != 40:
        raise OpeningRuntimeIdentityError(
            "ORIGIN_IDENTITY_UNAVAILABLE",
            "origin/master identity cannot be verified.",
        )
    return value


def plan(manifest_path: Path) -> dict[str, object]:
    manifest = parse_manifest(manifest_path)
    context = _context(manifest)
    head, status = current_git_identity(context.repository_root)
    identity = build_runtime_identity(context)
    store = OpeningRuntimeReleaseStore(context.release_root)
    try:
        active, _, _ = store.verify_channel(DEFAULT_CHANNEL)
    except OpeningRuntimeIdentityError as exc:
        if exc.code not in {"RELEASE_POINTER_MISSING", "PROMOTION_RECEIPT_MISSING"}:
            raise
        active = {}
    active_components = {
        str(item.get("path")): str(item.get("sha256"))
        for item in active.get("runtimeComponents", [])
        if isinstance(item, dict)
    }
    candidate_components = {
        str(item.get("path")): str(item.get("sha256"))
        for item in identity["runtimeSurface"]["components"]
        if isinstance(item, dict)
    }
    changed = sorted(
        key
        for key in set(active_components) | set(candidate_components)
        if active_components.get(key) != candidate_components.get(key)
    )
    return {
        "status": "PLAN_ONLY",
        "currentGitSha": head,
        "originMasterSha": _origin_master(context.repository_root),
        "worktreeClean": not bool(status),
        "activeReleaseId": active.get("releaseId", ""),
        "activeRuntimeFingerprint": active.get("approvedRuntimeFingerprint", ""),
        "candidateRuntimeFingerprint": identity["approvedRuntimeFingerprint"],
        "runtimeMatch": active.get("approvedRuntimeFingerprint")
        == identity["approvedRuntimeFingerprint"],
        "changedRuntimeComponents": changed,
        "configurationFingerprint": identity["configuration"][
            "configurationFingerprint"
        ],
        "environmentFingerprint": identity["environment"][
            "environmentFingerprint"
        ],
        "mutationPerformed": False,
    }


def status(manifest_path: Path) -> dict[str, object]:
    manifest = parse_manifest(manifest_path)
    context = _context(manifest)
    state = _state_payload(manifest)
    heartbeat = _require_fresh_supervisor_state(manifest, state)
    result = verify_execution_gate(
        context,
        channel=DEFAULT_CHANNEL,
        loaded_supervisor_sha256=str(state.get("loaded_supervisor_sha256", "")),
        loaded_identity_module_sha256=str(
            state.get("loaded_runtime_identity_module_sha256", "")
        ),
        loaded_service_host_sha256=str(
            state.get("loaded_service_host_sha256", "")
        ),
    )
    return {
        "status": "APPROVED_RUNTIME_MATCH",
        "channel": result.channel,
        "releaseId": result.release_id,
        "releaseFingerprint": result.release_fingerprint,
        "runtimeFingerprint": result.approved_runtime_fingerprint,
        "releaseSourceGitSha": result.release_source_git_sha,
        "currentGitSha": result.current_git_sha,
        "worktreeClean": result.current_worktree_clean,
        "runtimeMatch": result.runtime_match,
        "supervisorHeartbeatAt": heartbeat.isoformat(),
        "orderTransmission": "UNAVAILABLE",
        "mutationPerformed": False,
    }


def promote(
    manifest_path: Path,
    *,
    qualification_evidence: list[str],
    confirmation: str,
) -> dict[str, object]:
    if confirmation != PROMOTION_CONFIRMATION:
        raise OpeningRuntimeIdentityError(
            "PROMOTION_CONFIRMATION_MISSING",
            "Exact runtime promotion confirmation was not supplied.",
        )
    manifest = parse_manifest(manifest_path)
    context = _context(manifest)
    head, worktree_status = current_git_identity(context.repository_root)
    if worktree_status:
        raise OpeningRuntimeIdentityError(
            "PROMOTION_WORKTREE_DIRTY",
            "Runtime promotion requires a clean canonical worktree.",
        )
    origin = _origin_master(context.repository_root)
    if origin != head:
        raise OpeningRuntimeIdentityError(
            "PROMOTION_GIT_DIVERGED",
            "Runtime promotion requires local master synchronized with origin/master.",
        )
    store = OpeningRuntimeReleaseStore(context.release_root)
    try:
        active, _, _ = store.verify_channel(DEFAULT_CHANNEL)
        predecessor = str(active["releaseId"])
    except OpeningRuntimeIdentityError as exc:
        if exc.code not in {"RELEASE_POINTER_MISSING", "PROMOTION_RECEIPT_MISSING"}:
            raise
        predecessor = ""
    record = build_release_record(
        context,
        source_git_sha=head,
        qualification_evidence=qualification_evidence,
        predecessor_release_id=predecessor,
    )
    state = _state_payload(manifest)
    heartbeat = _require_fresh_supervisor_state(manifest, state)
    components = {
        str(item.get("path")): str(item.get("sha256"))
        for item in record["runtimeComponents"]
        if isinstance(item, dict)
    }
    if state.get("loaded_supervisor_sha256") != components.get(
        "momentum_hunter/automation_supervisor.py"
    ):
        raise OpeningRuntimeIdentityError(
            "PROMOTION_REQUIRES_SUPERVISOR_RESTART",
            "Running supervisor bytes do not match the candidate release.",
        )
    if state.get(
        "loaded_runtime_identity_module_sha256"
    ) != components.get("momentum_hunter/opening_runtime_identity.py"):
        raise OpeningRuntimeIdentityError(
            "PROMOTION_REQUIRES_IDENTITY_GATE_RESTART",
            "Running identity-gate bytes do not match the candidate release.",
        )
    if state.get("loaded_service_host_sha256") != record[
        "environmentIdentity"
    ]["serviceHost"]["sha256"]:
        raise OpeningRuntimeIdentityError(
            "PROMOTION_REQUIRES_SERVICE_HOST_RESTART",
            "Running Automation Service host does not match the candidate release.",
        )
    release, pointer, changed = store.promote(
        record,
        channel=DEFAULT_CHANNEL,
        current_git_sha=head,
    )
    return {
        "status": "PROMOTED" if changed else "ALREADY_ACTIVE",
        "releaseId": release["releaseId"],
        "releaseFingerprint": release["releaseFingerprint"],
        "runtimeFingerprint": release["approvedRuntimeFingerprint"],
        "sourceGitSha": release["sourceGitSha"],
        "pointerFingerprint": pointer.get("pointerFingerprint", ""),
        "supervisorHeartbeatAt": heartbeat.isoformat(),
        "promotionChanged": changed,
        "orderTransmission": "UNAVAILABLE",
    }


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpeningRuntimeIdentityError(
            "MIGRATION_INPUT_INVALID",
            f"Migration input is unreadable: {path}",
        ) from exc
    if not isinstance(payload, dict):
        raise OpeningRuntimeIdentityError(
            "MIGRATION_INPUT_INVALID",
            "Migration input must be an object.",
        )
    return payload


def plan_future_opening_migration(
    manifest_payload: Mapping[str, object],
    state_payload: Mapping[str, object],
    *,
    now: datetime,
    service_host_executable: Path,
    release_root: Path,
) -> tuple[dict[str, object], list[str], list[str]]:
    migrated = json.loads(json.dumps(manifest_payload))
    jobs = migrated.get("jobs")
    if not isinstance(jobs, list):
        raise OpeningRuntimeIdentityError(
            "MIGRATION_MANIFEST_INVALID",
            "Automation manifest jobs are invalid.",
        )
    receipts = state_payload.get("jobs", {})
    if not isinstance(receipts, dict):
        raise OpeningRuntimeIdentityError(
            "MIGRATION_STATE_INVALID",
            "Automation state receipts are invalid.",
        )
    eligible_ids: list[str] = []
    changed_ids: list[str] = []
    for job in jobs:
        if not isinstance(job, dict) or job.get("kind") != "opening_capture":
            continue
        try:
            scheduled_at = datetime.fromisoformat(str(job.get("scheduledAt", "")))
        except ValueError as exc:
            raise OpeningRuntimeIdentityError(
                "MIGRATION_JOB_TIME_INVALID",
                "Opening job has an invalid scheduled time.",
            ) from exc
        if scheduled_at <= now:
            continue
        job_id = str(job.get("jobId", ""))
        receipt = receipts.get(job_id, {})
        receipt_status = (
            str(receipt.get("status", "NOT_OBSERVED"))
            if isinstance(receipt, dict)
            else "INVALID"
        )
        if receipt_status not in {"PENDING", "NOT_OBSERVED"}:
            raise OpeningRuntimeIdentityError(
                "MIGRATION_FUTURE_JOB_NOT_PENDING",
                f"Future opening job is not pending: {job_id}",
            )
        eligible_ids.append(job_id)
        if (
            job.get("approvedRuntimeChannel") == DEFAULT_CHANNEL
            and "expectedGitHead" not in job
        ):
            continue
        job.pop("expectedGitHead", None)
        job["approvedRuntimeChannel"] = DEFAULT_CHANNEL
        changed_ids.append(job_id)
    if not eligible_ids:
        raise OpeningRuntimeIdentityError(
            "MIGRATION_NO_FUTURE_OPENINGS",
            "No future pending opening jobs are eligible for migration.",
        )
    migrated["serviceHostExecutable"] = str(service_host_executable.absolute())
    migrated["openingRuntimeReleaseRoot"] = str(release_root.absolute())
    return migrated, sorted(eligible_ids), sorted(changed_ids)


def migrate_future_openings(
    manifest_path: Path,
    state_path: Path,
    *,
    apply: bool,
    confirmation: str,
    now: datetime | None = None,
    service_host_executable: Path = DEFAULT_SERVICE_HOST,
    release_root: Path = DEFAULT_RELEASE_ROOT,
) -> dict[str, object]:
    manifest_payload = _load_json(manifest_path)
    state_payload = _load_json(state_path)
    migrated, job_ids, changed_ids = plan_future_opening_migration(
        manifest_payload,
        state_payload,
        now=now or datetime.now().astimezone(),
        service_host_executable=service_host_executable,
        release_root=release_root,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{manifest_path.name}.",
        suffix=".validation.tmp",
        dir=manifest_path.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(
            json.dumps(migrated, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        parse_manifest(temporary)
        if apply and changed_ids:
            if confirmation != MIGRATION_CONFIRMATION:
                raise OpeningRuntimeIdentityError(
                    "MIGRATION_CONFIRMATION_MISSING",
                    "Exact future-opening migration confirmation was not supplied.",
                )
            backup = manifest_path.with_name(
                f"{manifest_path.name}.{datetime.now().strftime('%Y%m%dT%H%M%S')}.runtime-identity.bak"
            )
            shutil.copy2(manifest_path, backup)
            os.replace(temporary, manifest_path)
        else:
            backup = None
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "status": (
            "MIGRATED"
            if apply and changed_ids
            else "ALREADY_MIGRATED"
            if apply
            else "PLAN_ONLY"
        ),
        "futureOpeningJobCount": len(job_ids),
        "futureOpeningJobIds": job_ids,
        "changedFutureOpeningJobIds": changed_ids,
        "approvedRuntimeChannel": DEFAULT_CHANNEL,
        "legacyGitPinsRemoved": len(changed_ids),
        "backupPath": str(backup) if backup else "",
        "mutationPerformed": apply and bool(changed_ids),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Manage approved Momentum Hunter opening runtime releases."
    )
    parser.add_argument(
        "command",
        choices=("plan", "status", "verify", "promote", "migrate-plan", "migrate-apply"),
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--qualification-evidence", action="append", default=[])
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--service-host", type=Path, default=DEFAULT_SERVICE_HOST)
    parser.add_argument("--release-root", type=Path, default=DEFAULT_RELEASE_ROOT)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = plan(args.manifest)
        elif args.command in {"status", "verify"}:
            result = status(args.manifest)
        elif args.command == "promote":
            result = promote(
                args.manifest,
                qualification_evidence=args.qualification_evidence,
                confirmation=args.confirmation,
            )
        else:
            state_path = args.state
            if state_path is None:
                manifest = parse_manifest(args.manifest)
                state_path = (
                    manifest.state_directory / "automation-service-state.json"
                )
            result = migrate_future_openings(
                args.manifest,
                state_path,
                apply=args.command == "migrate-apply",
                confirmation=args.confirmation,
                service_host_executable=args.service_host,
                release_root=args.release_root,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OpeningRuntimeIdentityError, OSError, ValueError) as exc:
        code = getattr(exc, "code", type(exc).__name__)
        print(json.dumps({"status": "FAILED", "code": code, "detail": str(exc)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
