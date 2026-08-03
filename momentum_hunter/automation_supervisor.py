from __future__ import annotations

"""Unattended, restart-safe scheduling for Momentum Hunter automation.

The supervisor is intentionally deterministic. It can launch the existing
FakeBroker-only opening runner, but it cannot create proof, arm a selector, or
transmit an order by itself. Missed market jobs are recorded and never run late.
"""

import argparse
import ctypes
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence

from momentum_hunter.engine_host import COMMAND_SNAPSHOT
from momentum_hunter.engine_host_client import (
    default_state_directory as default_engine_host_state_directory,
)
from momentum_hunter.engine_host_client import (
    ensure_engine_host,
    send_engine_host_command,
)
from momentum_hunter.schwab_onboarding import (
    EncryptedSchwabAccountBindingStore,
    SchwabOAuthSecretRepository,
)
from momentum_hunter.schwab_readonly import redact_value


MANIFEST_SCHEMA_VERSION = 1
STATE_SCHEMA_VERSION = 1
STATE_REPLACE_RETRY_ATTEMPTS = 20
STATE_REPLACE_RETRY_DELAY_SECONDS = 0.05
JOB_KINDS = frozenset(
    {
        "nonmarket_canary",
        "opening_capture",
        "shadow_opening",
        "codex_review",
    }
)
ENGINE_HOST_REQUIRED_JOB_KINDS = frozenset(
    {"nonmarket_canary", "shadow_opening"}
)
FINAL_JOB_STATES = frozenset(
    {
        "COMPLETED",
        "FAILED",
        "MISSED",
        "BLOCKED_DEPENDENCY",
        "DISABLED",
    }
)
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_SERVICE_ROOT = (
    Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    / "MomentumHunter"
    / "Automation"
)
DEFAULT_MANIFEST_PATH = DEFAULT_SERVICE_ROOT / "automation-manifest.json"


class AutomationSupervisorError(RuntimeError):
    pass


class ManifestValidationError(AutomationSupervisorError):
    pass


@dataclass(frozen=True)
class AutomationJob:
    job_id: str
    kind: str
    scheduled_at: datetime
    latest_start_at: datetime
    enabled: bool = True
    depends_on_job_id: str = ""
    expected_git_head: str = ""
    proof_bundle_path: Path | None = None
    task_definition_path: Path | None = None
    prompt_path: Path | None = None
    expected_output: str = ""
    timeout_seconds: int = 1800


@dataclass(frozen=True)
class AutomationManifest:
    repository_root: Path
    python_executable: Path
    powershell_executable: Path
    codex_executable: Path | None
    state_directory: Path
    engine_host_state_directory: Path
    poll_interval_seconds: float
    jobs: tuple[AutomationJob, ...]
    expected_account_ending: str = ""
    expected_account_type: str = "INDIVIDUAL_CASH"


@dataclass
class JobReceipt:
    job_id: str
    kind: str
    status: str
    scheduled_at: str
    latest_start_at: str
    observed_at: str
    started_at: str = ""
    completed_at: str = ""
    exit_code: int | None = None
    reason: str = ""
    log_path: str = ""
    depends_on_job_id: str = ""


@dataclass
class SupervisorState:
    schema_version: int = STATE_SCHEMA_VERSION
    service_instance_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    service_started_at: str = ""
    last_heartbeat_at: str = ""
    engine_host_state: str = "UNKNOWN"
    engine_host_detail: str = ""
    engine_host_observed_at: str = ""
    jobs: dict[str, JobReceipt] = field(default_factory=dict)


Clock = Callable[[], datetime]
EngineHostProbe = Callable[[], Mapping[str, object]]
JobExecutor = Callable[[AutomationJob, Path], tuple[int, str]]


def parse_manifest(path: Path) -> AutomationManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestValidationError(
            f"Automation manifest cannot be read: {path}"
        ) from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != MANIFEST_SCHEMA_VERSION:
        raise ManifestValidationError("Automation manifest schema is unsupported.")

    repository_root = _required_path(payload, "repositoryRoot", directory=True)
    python_executable = _required_path(payload, "pythonExecutable", file=True)
    powershell_executable = _required_path(
        payload,
        "powershellExecutable",
        file=True,
    )
    state_directory = _required_path(payload, "stateDirectory")
    engine_host_state_directory = _required_path(
        payload,
        "engineHostStateDirectory",
    )
    codex_value = str(payload.get("codexExecutable", "")).strip()
    codex_executable = Path(codex_value).resolve() if codex_value else None
    if codex_executable is not None and not codex_executable.is_file():
        raise ManifestValidationError(
            "Configured Codex executable does not exist."
        )
    poll_interval_seconds = float(payload.get("pollIntervalSeconds", 1.0))
    if not 0.25 <= poll_interval_seconds <= 60:
        raise ManifestValidationError(
            "pollIntervalSeconds must be between 0.25 and 60."
        )
    expected_account_ending = str(
        payload.get("expectedAccountEnding", "")
    ).strip()
    if not re.fullmatch(r"\d{4}", expected_account_ending):
        raise ManifestValidationError(
            "Automation manifest requires a four-digit expectedAccountEnding."
        )
    expected_account_type = str(
        payload.get("expectedAccountType", "")
    ).strip()
    if expected_account_type != "INDIVIDUAL_CASH":
        raise ManifestValidationError(
            "Automation manifest expectedAccountType must be INDIVIDUAL_CASH."
        )

    raw_jobs = payload.get("jobs", [])
    if not isinstance(raw_jobs, list):
        raise ManifestValidationError("Automation manifest jobs must be a list.")
    jobs = tuple(
        _parse_job(item, repository_root=repository_root)
        for item in raw_jobs
    )
    job_ids = [job.job_id for job in jobs]
    if len(job_ids) != len(set(job_ids)):
        raise ManifestValidationError("Automation job identifiers must be unique.")
    known_ids = set(job_ids)
    jobs_by_id = {job.job_id: job for job in jobs}
    for job in jobs:
        if job.depends_on_job_id and job.depends_on_job_id not in known_ids:
            raise ManifestValidationError(
                f"Job {job.job_id!r} references an unknown dependency."
            )
        if job.depends_on_job_id == job.job_id:
            raise ManifestValidationError(
                f"Job {job.job_id!r} cannot depend on itself."
            )
        if job.kind == "codex_review" and not job.depends_on_job_id:
            raise ManifestValidationError(
                "Codex review jobs require a terminal runtime dependency."
            )
        if job.kind != "codex_review" and job.depends_on_job_id:
            raise ManifestValidationError(
                "Runtime jobs cannot depend on a Codex review or another job."
            )
        if (
            job.kind == "codex_review"
            and job.depends_on_job_id
            and jobs_by_id[job.depends_on_job_id].kind == "codex_review"
        ):
            raise ManifestValidationError(
                "Codex reviews must depend directly on a runtime job."
            )
        if job.kind == "codex_review" and codex_executable is None:
            raise ManifestValidationError(
                "Codex review job exists but codexExecutable is not configured."
            )
    opening_dates = {
        job.scheduled_at.date()
        for job in jobs
        if job.kind == "opening_capture" and job.enabled
    }
    shadow_dates = {
        job.scheduled_at.date()
        for job in jobs
        if job.kind == "shadow_opening" and job.enabled
    }
    if opening_dates & shadow_dates:
        raise ManifestValidationError(
            "A market date cannot schedule both an opening capture and a "
            "Shadow opening; the Shadow opening already performs the capture."
        )

    return AutomationManifest(
        repository_root=repository_root,
        python_executable=python_executable,
        powershell_executable=powershell_executable,
        codex_executable=codex_executable,
        state_directory=state_directory,
        engine_host_state_directory=engine_host_state_directory,
        poll_interval_seconds=poll_interval_seconds,
        jobs=jobs,
        expected_account_ending=expected_account_ending,
        expected_account_type=expected_account_type,
    )


def _parse_job(
    payload: object,
    *,
    repository_root: Path,
) -> AutomationJob:
    if not isinstance(payload, dict):
        raise ManifestValidationError("Each automation job must be an object.")
    job_id = str(payload.get("jobId", "")).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", job_id):
        raise ManifestValidationError("Automation jobId is invalid.")
    kind = str(payload.get("kind", "")).strip()
    if kind not in JOB_KINDS:
        raise ManifestValidationError(
            f"Automation job {job_id!r} has an unsupported kind."
        )
    scheduled_at = _parse_timestamp(payload.get("scheduledAt"), "scheduledAt")
    latest_start_at = _parse_timestamp(
        payload.get("latestStartAt"),
        "latestStartAt",
    )
    if latest_start_at < scheduled_at:
        raise ManifestValidationError(
            f"Job {job_id!r} latestStartAt precedes scheduledAt."
        )
    if kind in {"opening_capture", "shadow_opening"}:
        maximum_window = 5 if kind == "shadow_opening" else 300
        if (latest_start_at - scheduled_at).total_seconds() > maximum_window:
            if kind == "shadow_opening":
                message = (
                    "Shadow openings allow at most a five-second start window."
                )
            else:
                message = (
                    "Opening captures allow at most a five-minute start window."
                )
            raise ManifestValidationError(message)
        if scheduled_at.strftime("%H:%M:%S") != "08:35:00":
            raise ManifestValidationError(
                "Opening jobs must be scheduled at exactly 08:35:00 local time."
            )

    timeout_seconds = int(payload.get("timeoutSeconds", 1800))
    if not 1 <= timeout_seconds <= 3600:
        raise ManifestValidationError(
            f"Job {job_id!r} timeoutSeconds must be between 1 and 3600."
        )
    expected_git_head = str(payload.get("expectedGitHead", "")).strip().lower()
    proof_bundle_path = _optional_path(payload.get("proofBundlePath"))
    task_definition_path = _optional_path(payload.get("taskDefinitionPath"))
    prompt_path = _optional_path(payload.get("promptPath"))
    expected_output = str(payload.get("expectedOutput", "")).strip()

    if kind in {"opening_capture", "shadow_opening"}:
        if not GIT_SHA_PATTERN.fullmatch(expected_git_head):
            raise ManifestValidationError(
                "Opening jobs require a full expectedGitHead."
            )
    if kind == "shadow_opening":
        if proof_bundle_path is None or not proof_bundle_path.is_dir():
            raise ManifestValidationError(
                "Shadow openings require an existing proof bundle directory."
            )
        if task_definition_path is None or not task_definition_path.is_file():
            raise ManifestValidationError(
                "Shadow openings require an existing frozen launch definition."
            )
        _require_within_repository(proof_bundle_path, repository_root)
        _require_within_repository(task_definition_path, repository_root)
    elif kind == "opening_capture":
        if proof_bundle_path or task_definition_path:
            raise ManifestValidationError(
                f"Job {job_id!r} cannot carry Shadow opening authority."
            )
    elif expected_git_head or proof_bundle_path or task_definition_path:
        raise ManifestValidationError(
            f"Job {job_id!r} cannot carry Shadow opening authority."
        )

    if kind == "codex_review":
        if prompt_path is None or not prompt_path.is_file():
            raise ManifestValidationError(
                "Codex review jobs require an existing promptPath."
            )
        _require_within_repository(prompt_path, repository_root)
        if expected_output and not re.fullmatch(
            r"[A-Z][A-Z0-9_]{0,63}",
            expected_output,
        ):
            raise ManifestValidationError(
                "Codex expectedOutput must be an uppercase machine token."
            )
    elif prompt_path is not None or expected_output:
        raise ManifestValidationError(
            f"Job {job_id!r} cannot carry Codex review configuration."
        )

    return AutomationJob(
        job_id=job_id,
        kind=kind,
        scheduled_at=scheduled_at,
        latest_start_at=latest_start_at,
        enabled=bool(payload.get("enabled", True)),
        depends_on_job_id=str(payload.get("dependsOnJobId", "")).strip(),
        expected_git_head=expected_git_head,
        proof_bundle_path=proof_bundle_path,
        task_definition_path=task_definition_path,
        prompt_path=prompt_path,
        expected_output=expected_output,
        timeout_seconds=timeout_seconds,
    )


def _required_path(
    payload: Mapping[str, object],
    key: str,
    *,
    file: bool = False,
    directory: bool = False,
) -> Path:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ManifestValidationError(f"Automation manifest requires {key}.")
    path = Path(value).resolve()
    if file and not path.is_file():
        raise ManifestValidationError(f"Configured {key} file does not exist.")
    if directory and not path.is_dir():
        raise ManifestValidationError(
            f"Configured {key} directory does not exist."
        )
    return path


def _optional_path(value: object) -> Path | None:
    text = str(value or "").strip()
    return Path(text).resolve() if text else None


def _parse_timestamp(value: object, field_name: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ManifestValidationError(
            f"Automation job {field_name} is invalid."
        ) from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ManifestValidationError(
            f"Automation job {field_name} must include a UTC offset."
        )
    return timestamp


def _require_within_repository(path: Path, repository_root: Path) -> None:
    try:
        path.resolve().relative_to(repository_root.resolve())
    except ValueError as exc:
        raise ManifestValidationError(
            "Automation job artifact escapes the configured repository."
        ) from exc


class SupervisorStateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, *, started_at: datetime) -> SupervisorState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return SupervisorState(service_started_at=started_at.isoformat())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AutomationSupervisorError(
                "Automation supervisor state is unreadable."
            ) from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != STATE_SCHEMA_VERSION:
            raise AutomationSupervisorError(
                "Automation supervisor state schema is unsupported."
            )
        raw_jobs = payload.get("jobs", {})
        if not isinstance(raw_jobs, dict):
            raise AutomationSupervisorError(
                "Automation supervisor job state is invalid."
            )
        jobs: dict[str, JobReceipt] = {}
        for key, value in raw_jobs.items():
            if not isinstance(value, dict):
                raise AutomationSupervisorError(
                    "Automation supervisor receipt is invalid."
                )
            jobs[str(key)] = JobReceipt(**value)
        return SupervisorState(
            schema_version=STATE_SCHEMA_VERSION,
            service_instance_id=str(payload.get("service_instance_id", "")),
            service_started_at=str(payload.get("service_started_at", "")),
            last_heartbeat_at=str(payload.get("last_heartbeat_at", "")),
            engine_host_state=str(payload.get("engine_host_state", "UNKNOWN")),
            engine_host_detail=str(payload.get("engine_host_detail", "")),
            engine_host_observed_at=str(
                payload.get("engine_host_observed_at", "")
            ),
            jobs=jobs,
        )

    def save(self, state: SupervisorState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(state)
        temporary = self.path.with_name(
            f"{self.path.name}.{uuid.uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            _replace_state_file(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)


def _replace_state_file(temporary: Path, destination: Path) -> None:
    for attempt in range(STATE_REPLACE_RETRY_ATTEMPTS):
        try:
            temporary.replace(destination)
            return
        except OSError as exc:
            retryable = (
                isinstance(exc, PermissionError)
                or getattr(exc, "winerror", None) in {5, 32}
            )
            if not retryable or attempt == STATE_REPLACE_RETRY_ATTEMPTS - 1:
                raise
            time.sleep(STATE_REPLACE_RETRY_DELAY_SECONDS)


class AutomationSupervisor:
    def __init__(
        self,
        manifest: AutomationManifest,
        *,
        clock: Clock | None = None,
        engine_host_probe: EngineHostProbe | None = None,
        job_executor: JobExecutor | None = None,
    ) -> None:
        self.manifest = manifest
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.engine_host_probe = engine_host_probe or self._probe_engine_host
        self.job_executor = job_executor or self._execute_job
        started_at = self.clock()
        self.state_store = SupervisorStateStore(
            manifest.state_directory / "automation-service-state.json"
        )
        self.state = self.state_store.load(started_at=started_at)
        self.state.service_instance_id = uuid.uuid4().hex
        self.state.service_started_at = started_at.isoformat()
        self._last_engine_probe_monotonic = 0.0

    def tick(self) -> SupervisorState:
        now = self.clock()
        opening_jobs = tuple(
            job
            for job in self.manifest.jobs
            if job.kind == "opening_capture"
        )
        for job in opening_jobs:
            self._evaluate_job(job, now)
        probe_started_at = self.clock()
        self._refresh_engine_host(probe_started_at)
        now = self.clock()
        self.state.last_heartbeat_at = now.isoformat()
        for job in self.manifest.jobs:
            if job.kind in ENGINE_HOST_REQUIRED_JOB_KINDS:
                self._evaluate_job(job, now)
        for job in self.manifest.jobs:
            if job.kind == "codex_review":
                self._evaluate_job(job, now)
        self.state_store.save(self.state)
        return self.state

    def replace_manifest(self, manifest: AutomationManifest) -> None:
        if _manifest_runtime_identity(manifest) != _manifest_runtime_identity(
            self.manifest
        ):
            raise ManifestValidationError(
                "A running service may hot-reload jobs only; runtime identity "
                "changes require explicit service reinstallation."
            )
        self.manifest = manifest

    def _refresh_engine_host(self, now: datetime) -> None:
        current = time.monotonic()
        if current - self._last_engine_probe_monotonic < 15:
            return
        self._last_engine_probe_monotonic = current
        try:
            snapshot = self.engine_host_probe()
            identity = snapshot.get("identity", {})
            health = snapshot.get("health", {})
            if not isinstance(identity, Mapping) or not isinstance(health, Mapping):
                raise AutomationSupervisorError(
                    "Engine Host snapshot is incomplete."
                )
            self.state.engine_host_state = str(health.get("state", "UNKNOWN"))
            self.state.engine_host_detail = str(
                health.get("detail", "Engine Host responded.")
            )
        except Exception as exc:
            self.state.engine_host_state = "UNAVAILABLE"
            self.state.engine_host_detail = (
                f"Engine Host preflight failed: {type(exc).__name__}"
            )
        self.state.engine_host_observed_at = now.isoformat()

    def _evaluate_job(self, job: AutomationJob, now: datetime) -> None:
        receipt = self.state.jobs.get(job.job_id)
        if receipt is not None and receipt.status in FINAL_JOB_STATES:
            return
        if not job.enabled:
            self.state.jobs[job.job_id] = self._receipt(
                job,
                now,
                "DISABLED",
                "Job is disabled in the immutable service manifest.",
            )
            return
        if receipt is not None and receipt.status == "RUNNING":
            receipt.status = "FAILED"
            receipt.observed_at = now.isoformat()
            receipt.completed_at = now.isoformat()
            receipt.reason = (
                "The service restarted while this job was in progress; the job "
                "was not relaunched because doing so could duplicate an existing "
                "capture process."
            )
            return
        if now < job.scheduled_at:
            if receipt is None:
                self.state.jobs[job.job_id] = self._receipt(
                    job,
                    now,
                    "PENDING",
                    "Waiting for the prospective schedule.",
                )
            return
        if now > job.latest_start_at:
            self.state.jobs[job.job_id] = self._receipt(
                job,
                now,
                "MISSED",
                "The service was not ready inside the allowed start window; "
                "the job will not run late.",
            )
            return
        if (
            job.kind in ENGINE_HOST_REQUIRED_JOB_KINDS
            and self.state.engine_host_state != "Healthy"
        ):
            self.state.jobs[job.job_id] = self._receipt(
                job,
                now,
                "FAILED",
                "Engine Host was not healthy inside the allowed start window.",
            )
            return
        if job.depends_on_job_id:
            dependency = self.state.jobs.get(job.depends_on_job_id)
            if dependency is None or dependency.status not in FINAL_JOB_STATES:
                return
            if dependency.status != "COMPLETED":
                self.state.jobs[job.job_id] = self._receipt(
                    job,
                    now,
                    "BLOCKED_DEPENDENCY",
                    f"Dependency {job.depends_on_job_id!r} did not complete.",
                )
                return

        running = self._receipt(job, now, "RUNNING", "Job process started.")
        running.started_at = now.isoformat()
        self.state.jobs[job.job_id] = running
        self.state_store.save(self.state)
        log_path = (
            self.manifest.state_directory
            / "logs"
            / f"{job.job_id}-{now.strftime('%Y%m%dT%H%M%S')}.log"
        )
        try:
            exit_code, detail = self.job_executor(job, log_path)
        except Exception as exc:
            exit_code = 1
            detail = f"Job process failed: {type(exc).__name__}"
        completed_at = self.clock()
        running.status = "COMPLETED" if exit_code == 0 else "FAILED"
        running.completed_at = completed_at.isoformat()
        running.observed_at = completed_at.isoformat()
        running.exit_code = exit_code
        running.reason = detail
        running.log_path = str(log_path)
        # Persist the terminal result before any later health probe or job can
        # interrupt this tick and leave a completed opening job marked RUNNING.
        self.state_store.save(self.state)

    @staticmethod
    def _receipt(
        job: AutomationJob,
        now: datetime,
        status: str,
        reason: str,
    ) -> JobReceipt:
        return JobReceipt(
            job_id=job.job_id,
            kind=job.kind,
            status=status,
            scheduled_at=job.scheduled_at.isoformat(),
            latest_start_at=job.latest_start_at.isoformat(),
            observed_at=now.isoformat(),
            reason=reason,
            depends_on_job_id=job.depends_on_job_id,
        )

    def _probe_engine_host(self) -> Mapping[str, object]:
        endpoint = ensure_engine_host(
            state_directory=self.manifest.engine_host_state_directory
        )
        result = send_engine_host_command(endpoint, COMMAND_SNAPSHOT)
        if not result.accepted:
            raise AutomationSupervisorError(
                f"Engine Host rejected snapshot: {result.code}"
            )
        return result.snapshot

    def _execute_job(
        self,
        job: AutomationJob,
        log_path: Path,
    ) -> tuple[int, str]:
        if job.kind == "nonmarket_canary":
            return self._run_nonmarket_canary(log_path)
        if job.kind == "opening_capture":
            self._validate_repository_identity(job.expected_git_head)
            command = self._opening_capture_command()
            return self._run_process(
                command,
                log_path=log_path,
                timeout_seconds=job.timeout_seconds,
                working_directory=self.manifest.repository_root,
            )
        if job.kind == "shadow_opening":
            self._validate_repository_identity(job.expected_git_head)
            command = self._shadow_opening_command(job)
            return self._run_process(
                command,
                log_path=log_path,
                timeout_seconds=job.timeout_seconds,
                working_directory=self.manifest.repository_root,
            )
        if job.kind == "codex_review":
            command = self._codex_review_command(job, log_path)
            exit_code, detail = self._run_process(
                command,
                log_path=log_path,
                timeout_seconds=job.timeout_seconds,
                working_directory=self.manifest.repository_root,
            )
            if exit_code != 0 or not job.expected_output:
                return exit_code, detail
            output_path = log_path.with_suffix(".final.txt")
            try:
                actual_output = output_path.read_text(
                    encoding="utf-8",
                ).strip()
            except (OSError, UnicodeDecodeError):
                return 1, "Codex service probe did not create readable output."
            if actual_output != job.expected_output:
                return 1, "Codex service probe returned unexpected output."
            return 0, "Codex service probe returned the expected output."
        raise AutomationSupervisorError(f"Unsupported job kind: {job.kind}")

    def _run_nonmarket_canary(self, log_path: Path) -> tuple[int, str]:
        binding = EncryptedSchwabAccountBindingStore().load()
        auth = SchwabOAuthSecretRepository().status()
        service_session_id = _current_process_session_id()
        interactive_user_session_count = _interactive_user_session_count()
        binding_matches = (
            binding.account_number_last_four
            == self.manifest.expected_account_ending
            and binding.account_type == self.manifest.expected_account_type
        )
        codex_executable_present = bool(
            self.manifest.codex_executable
            and self.manifest.codex_executable.is_file()
        )
        codex_auth_material_present = (
            Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            / "auth.json"
        ).is_file()
        receipt = {
            "schemaVersion": 1,
            "mode": "NONMARKET_SERVICE_CANARY",
            "windowsIdentity": os.environ.get("USERNAME", ""),
            "serviceProcessId": os.getpid(),
            "serviceSessionId": service_session_id,
            "serviceSessionIsNonInteractive": service_session_id == 0,
            "interactiveUserSessionCount": interactive_user_session_count,
            "userProfileAvailable": Path.home().is_dir(),
            "dpapiBindingReadable": True,
            "accountEnding": binding.account_number_last_four,
            "accountType": binding.account_type,
            "accountHashRedacted": redact_value(binding.account_hash),
            "accountBindingMatches": binding_matches,
            "tokenState": auth.get("tokenState"),
            "engineHostState": self.state.engine_host_state,
            "codexExecutablePresent": codex_executable_present,
            "codexAuthMaterialPresent": codex_auth_material_present,
            "positionsRequested": False,
            "ordersRequested": False,
            "orderTransmission": "UNAVAILABLE",
        }
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not binding_matches:
            return 1, (
                "Brokerage account binding anomaly; service canary failed closed."
            )
        if service_session_id != 0:
            return 1, (
                "Service canary is not running in noninteractive session 0."
            )
        return 0, "Nonmarket service canary completed without runtime mutation."

    def _validate_repository_identity(self, expected_head: str) -> None:
        head = _run_git(
            self.manifest.repository_root,
            ("rev-parse", "HEAD"),
        )
        if head != expected_head:
            raise AutomationSupervisorError(
                "Repository HEAD does not match the frozen opening identity."
            )
        status = _run_git(
            self.manifest.repository_root,
            ("status", "--porcelain"),
        )
        if status:
            raise AutomationSupervisorError(
                "Repository worktree is dirty; opening job failed closed."
            )

    def _shadow_opening_command(self, job: AutomationJob) -> list[str]:
        assert job.proof_bundle_path is not None
        assert job.task_definition_path is not None
        runner = self.manifest.repository_root / "tools" / "run_capture_job.ps1"
        if not runner.is_file():
            raise AutomationSupervisorError(
                "Shadow opening runner is missing."
            )
        return [
            str(self.manifest.powershell_executable),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runner),
            "-Session",
            "shadow",
            "-ProjectRoot",
            str(self.manifest.repository_root),
            "-PythonExe",
            str(self.manifest.python_executable),
            "-Provider",
            "finviz",
            "-Scanner",
            "Institutional Momentum",
            "-SelectorProofBundle",
            str(job.proof_bundle_path),
            "-TaskDefinitionPath",
            str(job.task_definition_path),
            "-ArmShadowSelector",
        ]

    def _opening_capture_command(self) -> list[str]:
        runner = self.manifest.repository_root / "tools" / "run_capture_job.ps1"
        if not runner.is_file():
            raise AutomationSupervisorError(
                "Opening capture runner is missing."
            )
        return [
            str(self.manifest.powershell_executable),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(runner),
            "-Session",
            "opening",
            "-ProjectRoot",
            str(self.manifest.repository_root),
            "-PythonExe",
            str(self.manifest.python_executable),
            "-Provider",
            "finviz",
            "-Scanner",
            "Institutional Momentum",
        ]

    def _codex_review_command(
        self,
        job: AutomationJob,
        log_path: Path,
    ) -> list[str]:
        if self.manifest.codex_executable is None or job.prompt_path is None:
            raise AutomationSupervisorError(
                "Codex review configuration is incomplete."
            )
        prompt = job.prompt_path.read_text(encoding="utf-8").strip()
        if not prompt:
            raise AutomationSupervisorError("Codex review prompt is empty.")
        output_path = log_path.with_suffix(".final.txt")
        return [
            str(self.manifest.codex_executable),
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--output-last-message",
            str(output_path),
            prompt,
        ]

    @staticmethod
    def _run_process(
        command: Sequence[str],
        *,
        log_path: Path,
        timeout_seconds: int,
        working_directory: Path,
    ) -> tuple[int, str]:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment.pop("OPENAI_API_KEY", None)
        environment.pop("CODEX_API_KEY", None)
        with log_path.open("a", encoding="utf-8") as stream:
            process = subprocess.Popen(
                list(command),
                cwd=working_directory,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                exit_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process.pid)
                process.wait(timeout=10)
                return 124, "Job exceeded its finite runtime and was stopped."
        return exit_code, f"Job process exited with code {exit_code}."


def _run_git(repository_root: Path, arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
        shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise AutomationSupervisorError(
            "Git identity preflight could not be completed."
        )
    return completed.stdout.strip()


def _manifest_runtime_identity(
    manifest: AutomationManifest,
) -> tuple[object, ...]:
    return (
        manifest.repository_root,
        manifest.python_executable,
        manifest.powershell_executable,
        manifest.codex_executable,
        manifest.state_directory,
        manifest.engine_host_state_directory,
        manifest.poll_interval_seconds,
        manifest.expected_account_ending,
        manifest.expected_account_type,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_process_session_id() -> int:
    if os.name != "nt":
        raise AutomationSupervisorError(
            "Automation service session proof requires Windows."
        )
    session_id = ctypes.c_uint()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(
        os.getpid(),
        ctypes.byref(session_id),
    ):
        raise AutomationSupervisorError(
            "Automation service session identity could not be determined."
        )
    return int(session_id.value)


class _WtsSessionInfo(ctypes.Structure):
    _fields_ = (
        ("session_id", wintypes.DWORD),
        ("station_name", wintypes.LPWSTR),
        ("state", ctypes.c_int),
    )


def _interactive_user_session_count() -> int:
    if os.name != "nt":
        raise AutomationSupervisorError(
            "Interactive session proof requires Windows."
        )
    wts = ctypes.WinDLL("Wtsapi32.dll", use_last_error=True)
    sessions = ctypes.POINTER(_WtsSessionInfo)()
    session_count = wintypes.DWORD()
    wts.WTSEnumerateSessionsW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_WtsSessionInfo)),
        ctypes.POINTER(wintypes.DWORD),
    )
    wts.WTSEnumerateSessionsW.restype = wintypes.BOOL
    wts.WTSQuerySessionInformationW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(wintypes.DWORD),
    )
    wts.WTSQuerySessionInformationW.restype = wintypes.BOOL
    wts.WTSFreeMemory.argtypes = (wintypes.LPVOID,)
    wts.WTSFreeMemory.restype = None
    if not wts.WTSEnumerateSessionsW(
        None,
        0,
        1,
        ctypes.byref(sessions),
        ctypes.byref(session_count),
    ):
        raise AutomationSupervisorError(
            "Interactive Windows sessions could not be enumerated."
        )
    logged_on = 0
    try:
        for session in sessions[: session_count.value]:
            if session.session_id == 0:
                continue
            user_name = wintypes.LPWSTR()
            returned_bytes = wintypes.DWORD()
            if not wts.WTSQuerySessionInformationW(
                None,
                session.session_id,
                5,
                ctypes.byref(user_name),
                ctypes.byref(returned_bytes),
            ):
                raise AutomationSupervisorError(
                    "A Windows session user could not be inspected."
                )
            try:
                if user_name.value and user_name.value.strip():
                    logged_on += 1
            finally:
                if user_name:
                    wts.WTSFreeMemory(user_name)
    finally:
        if sessions:
            wts.WTSFreeMemory(sessions)
    return logged_on


def _terminate_process_tree(process_id: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process_id), "/T", "/F"],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )


def run_service_loop(manifest_path: Path) -> int:
    manifest = parse_manifest(manifest_path)
    supervisor = AutomationSupervisor(manifest)
    manifest_hash = _file_sha256(manifest_path)
    while True:
        current_hash = _file_sha256(manifest_path)
        if current_hash != manifest_hash:
            candidate = parse_manifest(manifest_path)
            supervisor.replace_manifest(candidate)
            manifest = candidate
            manifest_hash = current_hash
        supervisor.tick()
        time.sleep(manifest.poll_interval_seconds)


def status_report(manifest_path: Path) -> dict[str, object]:
    manifest = parse_manifest(manifest_path)
    store = SupervisorStateStore(
        manifest.state_directory / "automation-service-state.json"
    )
    state = store.load(started_at=datetime.now().astimezone())
    return {
        "schemaVersion": 1,
        "serviceInstanceId": state.service_instance_id,
        "serviceStartedAt": state.service_started_at,
        "lastHeartbeatAt": state.last_heartbeat_at,
        "engineHostState": state.engine_host_state,
        "engineHostDetail": state.engine_host_detail,
        "jobs": {
            key: {
                "kind": value.kind,
                "status": value.status,
                "scheduledAt": value.scheduled_at,
                "observedAt": value.observed_at,
                "exitCode": value.exit_code,
                "reason": value.reason,
            }
            for key, value in sorted(state.jobs.items())
        },
        "orderTransmission": "UNAVAILABLE",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the unattended Momentum Hunter automation supervisor."
    )
    parser.add_argument("command", choices=("run", "run-once", "status"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
    )
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            return run_service_loop(args.manifest)
        if args.command == "run-once":
            manifest = parse_manifest(args.manifest)
            AutomationSupervisor(manifest).tick()
            return 0
        print(json.dumps(status_report(args.manifest), indent=2, sort_keys=True))
        return 0
    except (AutomationSupervisorError, OSError) as exc:
        print(f"Momentum Hunter automation supervisor stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
