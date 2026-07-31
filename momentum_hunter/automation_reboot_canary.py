from __future__ import annotations

"""Plan and verify a one-use, nonmarket automation-service reboot canary."""

import argparse
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence


FINAL_JOB_STATES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "MISSED",
        "BLOCKED_DEPENDENCY",
        "DISABLED",
    }
)
EXPECTED_ACCOUNT_ENDING = "2573"
EXPECTED_ACCOUNT_TYPE = "INDIVIDUAL_CASH"
CANARY_MODE = "NONMARKET_SERVICE_CANARY"
PROOF_MODE = "REBOOT_WITHOUT_LOGIN_CANARY"


class RebootCanaryError(RuntimeError):
    pass


def parse_timestamp(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise RebootCanaryError(f"{field} must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RebootCanaryError(f"{field} must include a UTC offset.")
    return parsed


def build_reboot_canary_plan(
    manifest: Mapping[str, object],
    state: Mapping[str, object],
    *,
    scheduled_at: datetime,
    prepared_at: datetime,
    pre_reboot_boot_time: datetime,
    baseline_path: Path,
) -> dict[str, object]:
    _validate_manifest_identity(manifest)
    scheduled = _aware(scheduled_at, "scheduled_at")
    prepared = _aware(prepared_at, "prepared_at")
    boot_time = _aware(pre_reboot_boot_time, "pre_reboot_boot_time")
    if scheduled < prepared + timedelta(minutes=3):
        raise RebootCanaryError(
            "The reboot canary must be scheduled at least three minutes ahead."
        )
    if boot_time >= prepared:
        raise RebootCanaryError(
            "The observed pre-reboot boot time must precede preparation."
        )
    latest_start_at = scheduled + timedelta(minutes=15)

    service_instance_id = str(state.get("service_instance_id", "")).strip()
    if not service_instance_id:
        raise RebootCanaryError(
            "Current service state has no service_instance_id."
        )
    raw_state_jobs = state.get("jobs", {})
    if not isinstance(raw_state_jobs, Mapping):
        raise RebootCanaryError("Current service state jobs must be an object.")

    raw_jobs = manifest.get("jobs", [])
    if not isinstance(raw_jobs, Sequence) or isinstance(raw_jobs, (str, bytes)):
        raise RebootCanaryError("Automation manifest jobs must be a list.")
    existing_jobs: list[dict[str, object]] = []
    preserved_pending_opening_jobs: list[dict[str, object]] = []
    for raw_job in raw_jobs:
        if not isinstance(raw_job, Mapping):
            raise RebootCanaryError("Automation manifest jobs must be objects.")
        job = dict(raw_job)
        job_id = str(job.get("jobId", "")).strip()
        kind = str(job.get("kind", "")).strip()
        enabled = bool(job.get("enabled", True))
        if not job_id or not kind:
            raise RebootCanaryError(
                "Existing automation jobs require jobId and kind."
            )
        if kind == "shadow_opening" and enabled:
            raise RebootCanaryError(
                "An enabled Shadow opening is incompatible with reboot proof."
            )
        receipt = raw_state_jobs.get(job_id)
        receipt_status = (
            str(receipt.get("status", "")).strip()
            if isinstance(receipt, Mapping)
            else ""
        )
        preserves_pending_opening = False
        if enabled and kind == "opening_capture" and receipt_status == "PENDING":
            opening_scheduled_at = parse_timestamp(
                job.get("scheduledAt"),
                f"Existing opening job {job_id} scheduledAt",
            )
            preserves_pending_opening = opening_scheduled_at > latest_start_at
        if (
            enabled
            and receipt_status not in FINAL_JOB_STATES
            and not preserves_pending_opening
        ):
            raise RebootCanaryError(
                f"Existing enabled job {job_id} is not terminal."
            )
        if preserves_pending_opening:
            preserved_pending_opening_jobs.append(job)
        existing_jobs.append(job)

    suffix = scheduled.strftime("%Y%m%dt%H%M%S")
    canary_job_id = f"reboot-canary-{suffix}"
    codex_job_id = ""
    existing_ids = {str(job["jobId"]) for job in existing_jobs}
    if canary_job_id in existing_ids:
        raise RebootCanaryError("The planned reboot canary job already exists.")
    canary_job: dict[str, object] = {
        "jobId": canary_job_id,
        "kind": "nonmarket_canary",
        "scheduledAt": scheduled.isoformat(),
        "latestStartAt": latest_start_at.isoformat(),
        "enabled": True,
        "timeoutSeconds": 60,
    }
    planned_jobs = [*existing_jobs, canary_job]

    codex_executable = str(manifest.get("codexExecutable", "")).strip()
    repository_root = Path(str(manifest["repositoryRoot"])).resolve()
    prompt_path = repository_root / "config" / "codex-service-canary-prompt.txt"
    if codex_executable:
        if not Path(codex_executable).is_file():
            raise RebootCanaryError(
                "Configured Codex executable is unavailable."
            )
        if not prompt_path.is_file():
            raise RebootCanaryError("Codex service canary prompt is missing.")
        codex_job_id = f"reboot-codex-probe-{suffix}"
        if codex_job_id in existing_ids:
            raise RebootCanaryError(
                "The planned reboot Codex probe already exists."
            )
        planned_jobs.append(
            {
                "jobId": codex_job_id,
                "kind": "codex_review",
                "scheduledAt": (scheduled + timedelta(seconds=1)).isoformat(),
                "latestStartAt": latest_start_at.isoformat(),
                "enabled": True,
                "dependsOnJobId": canary_job_id,
                "promptPath": str(prompt_path),
                "expectedOutput": "CODEX_SERVICE_READY",
                "timeoutSeconds": 180,
            }
        )

    planned_manifest = deepcopy(dict(manifest))
    planned_manifest["jobs"] = planned_jobs
    baseline = {
        "schemaVersion": 1,
        "proofMode": PROOF_MODE,
        "preparedAt": prepared.isoformat(),
        "preRebootBootTime": boot_time.isoformat(),
        "preRebootServiceInstanceId": service_instance_id,
        "canaryJobId": canary_job_id,
        "codexProbeJobId": codex_job_id,
        "scheduledAt": scheduled.isoformat(),
        "latestStartAt": latest_start_at.isoformat(),
        "expectedAccountEnding": EXPECTED_ACCOUNT_ENDING,
        "expectedAccountType": EXPECTED_ACCOUNT_TYPE,
        "expectedServiceSessionId": 0,
        "requiresNoInteractiveLogin": True,
        "shadowJobsEnabled": 0,
        "orderTransmission": "UNAVAILABLE",
        "baselinePath": str(baseline_path.resolve()),
        "preservedPendingOpeningJobs": preserved_pending_opening_jobs,
    }
    summary = {
        "classification": "READY_TO_INSTALL",
        "canaryJobId": canary_job_id,
        "codexProbeJobId": codex_job_id or "NOT_CONFIGURED",
        "scheduledAt": scheduled.isoformat(),
        "latestStartAt": latest_start_at.isoformat(),
        "manifestJobCount": len(planned_jobs),
        "shadowJobsEnabled": 0,
        "serviceRestartRequiredDuringPreparation": False,
        "requiresReboot": True,
        "requiresNoInteractiveLogin": True,
        "orderTransmission": "UNAVAILABLE",
        "preservedPendingOpeningJobCount": len(
            baseline["preservedPendingOpeningJobs"]
        ),
    }
    return {
        "manifest": planned_manifest,
        "baseline": baseline,
        "summary": summary,
    }


def verify_reboot_canary(
    manifest: Mapping[str, object],
    state: Mapping[str, object],
    baseline: Mapping[str, object],
    *,
    current_boot_time: datetime,
    service_status: str,
    service_start_mode: str,
) -> dict[str, object]:
    _validate_manifest_identity(manifest)
    if baseline.get("proofMode") != PROOF_MODE:
        raise RebootCanaryError("Reboot canary baseline mode is invalid.")
    if baseline.get("orderTransmission") != "UNAVAILABLE":
        raise RebootCanaryError("Reboot canary baseline transmission lock is invalid.")
    if baseline.get("shadowJobsEnabled") != 0:
        raise RebootCanaryError("Reboot canary baseline permits a Shadow job.")
    if baseline.get("requiresNoInteractiveLogin") is not True:
        raise RebootCanaryError("Reboot canary baseline lacks the no-login gate.")
    if baseline.get("expectedAccountEnding") != EXPECTED_ACCOUNT_ENDING:
        raise RebootCanaryError("Reboot canary baseline account ending is invalid.")
    if baseline.get("expectedAccountType") != EXPECTED_ACCOUNT_TYPE:
        raise RebootCanaryError("Reboot canary baseline account type is invalid.")
    if service_status != "Running" or service_start_mode != "Auto":
        raise RebootCanaryError(
            "Automation service must be Running with Automatic startup."
        )

    current_boot = _aware(current_boot_time, "current_boot_time")
    previous_boot = parse_timestamp(
        baseline.get("preRebootBootTime"),
        "preRebootBootTime",
    )
    if current_boot <= previous_boot:
        raise RebootCanaryError("No reboot occurred after canary preparation.")
    previous_instance = str(
        baseline.get("preRebootServiceInstanceId", "")
    ).strip()
    current_instance = str(state.get("service_instance_id", "")).strip()
    if not current_instance or current_instance == previous_instance:
        raise RebootCanaryError(
            "The service instance did not change after preparation."
        )
    service_started = parse_timestamp(
        state.get("service_started_at"),
        "service_started_at",
    )
    if service_started < current_boot:
        raise RebootCanaryError(
            "Service start evidence predates the current boot."
        )
    if str(state.get("engine_host_state", "")) != "Healthy":
        raise RebootCanaryError("Engine Host was not healthy after reboot.")

    jobs = state.get("jobs", {})
    if not isinstance(jobs, Mapping):
        raise RebootCanaryError("Service state jobs must be an object.")
    canary_job_id = str(baseline.get("canaryJobId", "")).strip()
    scheduled_at = parse_timestamp(
        baseline.get("scheduledAt"),
        "scheduledAt",
    )
    latest_start_at = parse_timestamp(
        baseline.get("latestStartAt"),
        "latestStartAt",
    )
    manifest_jobs = manifest.get("jobs", [])
    _verify_preserved_pending_opening_jobs(
        manifest_jobs,
        jobs,
        baseline.get("preservedPendingOpeningJobs", []),
        latest_start_at=latest_start_at,
    )
    canary_job = _find_manifest_job(manifest_jobs, canary_job_id)
    _verify_manifest_job(
        canary_job,
        expected_kind="nonmarket_canary",
        scheduled_at=scheduled_at,
        latest_start_at=latest_start_at,
    )
    receipt = jobs.get(canary_job_id)
    if not isinstance(receipt, Mapping):
        raise RebootCanaryError("Reboot canary receipt is missing.")
    _verify_completed_receipt(
        receipt,
        expected_kind="nonmarket_canary",
        current_boot=current_boot,
        scheduled_at=scheduled_at,
        latest_start=latest_start_at,
    )

    state_directory = Path(str(manifest["stateDirectory"])).resolve()
    log_path = Path(str(receipt.get("log_path", ""))).resolve()
    if not log_path.is_relative_to(state_directory) or not log_path.is_file():
        raise RebootCanaryError(
            "Reboot canary log is missing or outside the service state directory."
        )
    try:
        canary_log = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RebootCanaryError("Reboot canary log is unreadable.") from exc
    expected_values = {
        "mode": CANARY_MODE,
        "dpapiBindingReadable": True,
        "accountEnding": EXPECTED_ACCOUNT_ENDING,
        "accountType": EXPECTED_ACCOUNT_TYPE,
        "accountBindingMatches": True,
        "userProfileAvailable": True,
        "engineHostState": "Healthy",
        "positionsRequested": False,
        "ordersRequested": False,
        "orderTransmission": "UNAVAILABLE",
        "serviceSessionId": 0,
        "serviceSessionIsNonInteractive": True,
        "interactiveUserSessionCount": 0,
    }
    if (
        not isinstance(canary_log.get("serviceProcessId"), int)
        or canary_log["serviceProcessId"] <= 0
    ):
        raise RebootCanaryError(
            "Reboot canary log has no valid serviceProcessId."
        )
    for key, expected in expected_values.items():
        if canary_log.get(key) != expected:
            raise RebootCanaryError(
                f"Reboot canary log field {key} did not match {expected!r}."
            )

    codex_job_id = str(baseline.get("codexProbeJobId", "")).strip()
    codex_status = "NOT_CONFIGURED"
    if codex_job_id:
        codex_job = _find_manifest_job(manifest_jobs, codex_job_id)
        _verify_manifest_job(
            codex_job,
            expected_kind="codex_review",
            scheduled_at=scheduled_at + timedelta(seconds=1),
            latest_start_at=latest_start_at,
            dependency_job_id=canary_job_id,
        )
        if codex_job.get("expectedOutput") != "CODEX_SERVICE_READY":
            raise RebootCanaryError(
                "Reboot Codex probe manifest output token is invalid."
            )
        codex_receipt = jobs.get(codex_job_id)
        if not isinstance(codex_receipt, Mapping):
            raise RebootCanaryError("Reboot Codex probe receipt is missing.")
        _verify_completed_receipt(
            codex_receipt,
            expected_kind="codex_review",
            current_boot=current_boot,
            scheduled_at=scheduled_at + timedelta(seconds=1),
            latest_start=latest_start_at,
        )
        if (
            str(codex_receipt.get("reason", ""))
            != "Codex service probe returned the expected output."
        ):
            raise RebootCanaryError(
                "Reboot Codex probe did not return the exact expected output."
            )
        codex_status = "COMPLETED"

    enabled_shadow_jobs = [
        job
        for job in manifest_jobs
        if isinstance(job, Mapping)
        and job.get("kind") == "shadow_opening"
        and bool(job.get("enabled", True))
    ]
    if enabled_shadow_jobs:
        raise RebootCanaryError(
            "An enabled Shadow job exists during reboot verification."
        )
    return {
        "classification": "PASS",
        "proofMode": PROOF_MODE,
        "canaryJobId": canary_job_id,
        "canaryStatus": "COMPLETED",
        "codexProbeStatus": codex_status,
        "serviceStatus": service_status,
        "serviceStartMode": service_start_mode,
        "serviceInstanceChanged": True,
        "bootChanged": True,
        "serviceSessionId": 0,
        "serviceSessionIsNonInteractive": True,
        "interactiveUserSessionCount": 0,
        "engineHostState": "Healthy",
        "accountEnding": EXPECTED_ACCOUNT_ENDING,
        "accountType": EXPECTED_ACCOUNT_TYPE,
        "positionsRequested": False,
        "ordersRequested": False,
        "shadowJobsEnabled": 0,
        "orderTransmission": "UNAVAILABLE",
        "preservedPendingOpeningJobCount": len(
            baseline.get("preservedPendingOpeningJobs", [])
        ),
    }


def _verify_preserved_pending_opening_jobs(
    manifest_jobs: object,
    state_jobs: Mapping[str, object],
    expected_jobs: object,
    *,
    latest_start_at: datetime,
) -> None:
    if not isinstance(expected_jobs, list):
        raise RebootCanaryError(
            "Reboot baseline pending opening jobs must be a list."
        )
    for expected in expected_jobs:
        if not isinstance(expected, Mapping):
            raise RebootCanaryError(
                "Reboot baseline pending opening job is invalid."
            )
        job_id = str(expected.get("jobId", "")).strip()
        actual = _find_manifest_job(manifest_jobs, job_id)
        if dict(actual) != dict(expected):
            raise RebootCanaryError(
                f"Pending opening job {job_id!r} changed during reboot proof."
            )
        receipt = state_jobs.get(job_id)
        if not isinstance(receipt, Mapping) or receipt.get("status") != "PENDING":
            raise RebootCanaryError(
                f"Pending opening job {job_id!r} was not preserved as PENDING."
            )
        if parse_timestamp(
            actual.get("scheduledAt"),
            f"Pending opening job {job_id} scheduledAt",
        ) <= latest_start_at:
            raise RebootCanaryError(
                f"Pending opening job {job_id!r} is not prospective."
            )


def _validate_manifest_identity(manifest: Mapping[str, object]) -> None:
    if manifest.get("schemaVersion") != 1:
        raise RebootCanaryError("Automation manifest schema is unsupported.")
    if manifest.get("expectedAccountEnding") != EXPECTED_ACCOUNT_ENDING:
        raise RebootCanaryError("Automation manifest account ending is unexpected.")
    if manifest.get("expectedAccountType") != EXPECTED_ACCOUNT_TYPE:
        raise RebootCanaryError("Automation manifest account type is unexpected.")
    for key in (
        "repositoryRoot",
        "pythonExecutable",
        "powershellExecutable",
        "stateDirectory",
        "engineHostStateDirectory",
    ):
        if not str(manifest.get(key, "")).strip():
            raise RebootCanaryError(
                f"Automation manifest field {key} is required."
            )


def _verify_completed_receipt(
    receipt: Mapping[str, object],
    *,
    expected_kind: str,
    current_boot: datetime,
    scheduled_at: datetime,
    latest_start: datetime,
) -> None:
    if receipt.get("kind") != expected_kind:
        raise RebootCanaryError(
            f"Receipt kind must be {expected_kind}."
        )
    if receipt.get("status") != "COMPLETED" or receipt.get("exit_code") != 0:
        raise RebootCanaryError(
            f"{expected_kind} receipt did not complete successfully."
        )
    started_at = parse_timestamp(receipt.get("started_at"), "started_at")
    completed_at = parse_timestamp(receipt.get("completed_at"), "completed_at")
    if (
        started_at < current_boot
        or started_at < scheduled_at
        or started_at > latest_start
    ):
        raise RebootCanaryError(
            f"{expected_kind} start is outside the reboot proof window."
        )
    if completed_at < started_at:
        raise RebootCanaryError(
            f"{expected_kind} completion predates its start."
        )


def _find_manifest_job(
    manifest_jobs: object,
    job_id: str,
) -> Mapping[str, object]:
    if not isinstance(manifest_jobs, Sequence) or isinstance(
        manifest_jobs,
        (str, bytes),
    ):
        raise RebootCanaryError("Automation manifest jobs must be a list.")
    matching = [
        job
        for job in manifest_jobs
        if isinstance(job, Mapping)
        and str(job.get("jobId", "")).strip() == job_id
    ]
    if len(matching) != 1:
        raise RebootCanaryError(
            f"Automation manifest must contain exactly one job {job_id!r}."
        )
    return matching[0]


def _verify_manifest_job(
    job: Mapping[str, object],
    *,
    expected_kind: str,
    scheduled_at: datetime,
    latest_start_at: datetime,
    dependency_job_id: str = "",
) -> None:
    if job.get("kind") != expected_kind or job.get("enabled") is not True:
        raise RebootCanaryError(
            f"Manifest job must be enabled {expected_kind}."
        )
    if parse_timestamp(job.get("scheduledAt"), "scheduledAt") != scheduled_at:
        raise RebootCanaryError("Manifest job scheduledAt differs from baseline.")
    if (
        parse_timestamp(job.get("latestStartAt"), "latestStartAt")
        != latest_start_at
    ):
        raise RebootCanaryError(
            "Manifest job latestStartAt differs from baseline."
        )
    if str(job.get("dependsOnJobId", "")).strip() != dependency_job_id:
        raise RebootCanaryError(
            "Manifest job dependency differs from reboot-canary plan."
        )


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RebootCanaryError(f"{field} must include a UTC offset.")
    return value.astimezone(timezone.utc)


def _load_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RebootCanaryError(f"Cannot read JSON evidence: {path}") from exc
    if not isinstance(payload, dict):
        raise RebootCanaryError(f"JSON evidence must be an object: {path}")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--state", type=Path, required=True)
    plan.add_argument("--scheduled-at", required=True)
    plan.add_argument("--prepared-at", required=True)
    plan.add_argument("--pre-reboot-boot-time", required=True)
    plan.add_argument("--baseline", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--state", type=Path, required=True)
    verify.add_argument("--baseline", type=Path, required=True)
    verify.add_argument("--current-boot-time", required=True)
    verify.add_argument("--service-status", required=True)
    verify.add_argument("--service-start-mode", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = _load_json(args.manifest)
        state = _load_json(args.state)
        if args.command == "plan":
            result = build_reboot_canary_plan(
                manifest,
                state,
                scheduled_at=parse_timestamp(args.scheduled_at, "scheduledAt"),
                prepared_at=parse_timestamp(args.prepared_at, "preparedAt"),
                pre_reboot_boot_time=parse_timestamp(
                    args.pre_reboot_boot_time,
                    "preRebootBootTime",
                ),
                baseline_path=args.baseline,
            )
        else:
            result = verify_reboot_canary(
                manifest,
                state,
                _load_json(args.baseline),
                current_boot_time=parse_timestamp(
                    args.current_boot_time,
                    "currentBootTime",
                ),
                service_status=args.service_status,
                service_start_mode=args.service_start_mode,
            )
    except RebootCanaryError as exc:
        print(
            json.dumps(
                {
                    "classification": "FAIL",
                    "reason": str(exc),
                    "orderTransmission": "UNAVAILABLE",
                },
                indent=2,
            )
        )
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
