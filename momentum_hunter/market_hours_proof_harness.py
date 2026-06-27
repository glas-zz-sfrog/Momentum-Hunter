from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.time_utils import now_central


MARKET_HOURS_PROOF_SCHEMA_VERSION = 1
MARKET_HOURS_PROOF_ENGINE_VERSION = "market_hours_proof_harness_v1"
REPORTS_DIR = DATA_DIR / "reports"
MARKET_HOURS_PROOF_LATEST_JSON = REPORTS_DIR / "market-hours-proof-harness-latest.json"
MARKET_HOURS_PROOF_LATEST_MD = REPORTS_DIR / "market-hours-proof-harness-latest.md"


@dataclass(frozen=True)
class HarnessStep:
    name: str
    module: str
    args: tuple[str, ...] = ()
    purpose: str = ""
    market_data_required: bool = False
    writes_derived_outputs: bool = True
    timeout_seconds: int = 120

    def command(self) -> list[str]:
        return [sys.executable, "-B", "-m", self.module, *self.args]


@dataclass(frozen=True)
class StepResult:
    name: str
    status: str
    command: list[str]
    purpose: str
    market_data_required: bool
    writes_derived_outputs: bool
    return_code: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    warning: str = ""


Runner = Callable[[list[str], int], subprocess.CompletedProcess[str]]


def proof_steps() -> list[HarnessStep]:
    return [
        HarnessStep("provider_field_quality", "momentum_hunter.provider_field_quality", purpose="Audit stored provider/scanner field quality."),
        HarnessStep(
            "active_monitor_cycle",
            "momentum_hunter.active_monitor",
            args=("--refresh-target-market-data", "--fetch-missing-market-data"),
            purpose="Run a live/delayed market-tape monitor cycle.",
            market_data_required=True,
            timeout_seconds=240,
        ),
        HarnessStep(
            "evidence_autopilot",
            "momentum_hunter.evidence_autopilot",
            args=("--no-fetch-missing-market-data", "--no-refresh-target-market-data", "--no-fetch-missing-bars"),
            purpose="Run Evidence Autopilot in no-fetch mode unless a later live run is explicitly approved.",
            timeout_seconds=240,
        ),
        HarnessStep("alert_outcome_updater", "momentum_hunter.alert_outcome_updater", purpose="Update outcomes from already stored minute bars."),
        HarnessStep(
            "sqlite_all_safe_import",
            "momentum_hunter.sqlite_migration",
            args=("--slice", "all-safe"),
            purpose="Refresh additive SQLite mirrors from file-authoritative sources.",
        ),
        HarnessStep("sqlite_validation", "momentum_hunter.sqlite_validation", purpose="Validate SQLite mirror parity."),
        HarnessStep(
            "sqlite_shadow_compare",
            "momentum_hunter.sqlite_reports",
            args=("--shadow-compare",),
            purpose="Compare file summaries against SQLite read-model summaries.",
        ),
        HarnessStep("system_readiness", "momentum_hunter.system_readiness", purpose="Regenerate top-level readiness report."),
        HarnessStep("active_alert_reliability", "momentum_hunter.active_alert_reliability", purpose="Audit active alert evidence chain."),
        HarnessStep("evidence_autopilot_reliability", "momentum_hunter.evidence_autopilot_reliability", purpose="Audit autopilot freshness and handoff."),
        HarnessStep("report_index", "momentum_hunter.report_index", purpose="Index latest generated reports."),
        HarnessStep("evidence_census", "momentum_hunter.evidence_census", purpose="Summarize current evidence sample and candidate completeness."),
        HarnessStep("sqlite_analytics", "momentum_hunter.sqlite_analytics", purpose="Run read-only SQLite analytics query pack."),
        HarnessStep("operational_reliability", "momentum_hunter.operational_reliability", purpose="Classify warnings into operational action categories."),
    ]


def run_market_hours_proof_harness(
    *,
    execute: bool = False,
    allow_live_market: bool = False,
    generated_at: str | None = None,
    runner: Runner | None = None,
) -> dict:
    generated_at = generated_at or now_central().isoformat()
    runner = runner or run_subprocess
    results: list[StepResult] = []
    for step in proof_steps():
        if not execute:
            results.append(step_result(step, "PLANNED_DRY_RUN", warning="Dry-run only; command not executed."))
            continue
        if step.market_data_required and not allow_live_market:
            results.append(
                step_result(
                    step,
                    "SKIPPED_MARKET_HOURS_REQUIRED",
                    warning="Skipped because live/delayed market-data proof requires explicit --allow-live-market.",
                )
            )
            continue
        results.append(execute_step(step, runner))
    statuses = [result.status for result in results]
    overall = "DRY_RUN" if not execute else "PASS"
    if any(status == "FAILED" for status in statuses):
        overall = "FAIL"
    elif execute and any(status.startswith("SKIPPED") for status in statuses):
        overall = "WARN"
    return {
        "schema_version": MARKET_HOURS_PROOF_SCHEMA_VERSION,
        "engine_version": MARKET_HOURS_PROOF_ENGINE_VERSION,
        "generated_at": generated_at,
        "overall_status": overall,
        "execution_mode": "EXECUTE" if execute else "DRY_RUN",
        "allow_live_market": allow_live_market,
        "step_count": len(results),
        "executed_steps": sum(1 for result in results if result.status == "PASS"),
        "skipped_steps": sum(1 for result in results if result.status.startswith("SKIPPED")),
        "failed_steps": sum(1 for result in results if result.status == "FAILED"),
        "steps": [asdict(result) for result in results],
        "market_hours_runbook": market_hours_runbook(),
        "safety_note": (
            "Harness/reporting only. Dry-run mode does not execute proof steps. Execution mode writes only existing "
            "derived reports/stores and does not change scoring, readiness, alert thresholds, outcome classification, "
            "trade planning, raw captures, or user-authored files."
        ),
    }


def execute_step(step: HarnessStep, runner: Runner) -> StepResult:
    try:
        completed = runner(step.command(), step.timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        return step_result(
            step,
            "FAILED",
            return_code=None,
            stdout_tail=tail(exc.stdout or ""),
            stderr_tail=tail(exc.stderr or ""),
            warning=f"STEP_TIMEOUT:{step.timeout_seconds}s",
        )
    except OSError as exc:
        return step_result(step, "FAILED", warning=f"STEP_EXECUTION_ERROR:{type(exc).__name__}:{exc}")
    return step_result(
        step,
        "PASS" if completed.returncode == 0 else "FAILED",
        return_code=completed.returncode,
        stdout_tail=tail(completed.stdout),
        stderr_tail=tail(completed.stderr),
        warning="" if completed.returncode == 0 else f"NONZERO_EXIT:{completed.returncode}",
    )


def run_subprocess(command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        env=env,
        check=False,
    )


def step_result(
    step: HarnessStep,
    status: str,
    *,
    return_code: int | None = None,
    stdout_tail: str = "",
    stderr_tail: str = "",
    warning: str = "",
) -> StepResult:
    return StepResult(
        name=step.name,
        status=status,
        command=step.command(),
        purpose=step.purpose,
        market_data_required=step.market_data_required,
        writes_derived_outputs=step.writes_derived_outputs,
        return_code=return_code,
        stdout_tail=stdout_tail,
        stderr_tail=stderr_tail,
        warning=warning,
    )


def market_hours_runbook() -> list[str]:
    return [
        "1. Before market hours, run this harness without flags to review the planned proof sequence.",
        "2. During a safe market-data window, run with --execute --allow-live-market only when live/delayed data access is expected to work.",
        "3. If live access is not approved, run --execute without --allow-live-market to refresh safe backend reports while skipping market-tape proof.",
        "4. Inspect market-hours-proof-harness-latest.md, system-readiness-latest.md, active-alert-reliability-latest.md, and operational-reliability-sprint-v1-final-report.md.",
        "5. Do not tune strategy from this run; use it only to prove the evidence pipeline and market-data access behavior.",
    ]


def write_market_hours_proof_report(
    payload: dict,
    *,
    json_path: Path = MARKET_HOURS_PROOF_LATEST_JSON,
    markdown_path: Path = MARKET_HOURS_PROOF_LATEST_MD,
) -> dict[str, Path]:
    ensure_app_dirs()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(format_market_hours_proof_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def format_market_hours_proof_markdown(payload: dict) -> str:
    lines = [
        "# Market-Hours Proof Run Harness v1",
        "",
        payload.get("safety_note", ""),
        "",
        f"- Generated: {payload.get('generated_at', '')}",
        f"- Status: {payload.get('overall_status', 'UNKNOWN')}",
        f"- Execution mode: {payload.get('execution_mode', '')}",
        f"- Allow live market: {payload.get('allow_live_market', False)}",
        f"- Steps: {payload.get('step_count', 0)}",
        f"- Executed: {payload.get('executed_steps', 0)}",
        f"- Skipped: {payload.get('skipped_steps', 0)}",
        f"- Failed: {payload.get('failed_steps', 0)}",
        "",
        "## Runbook",
        "",
    ]
    lines.extend([f"- {item}" for item in payload.get("market_hours_runbook", [])])
    lines.extend(
        [
            "",
            "## Steps",
            "",
            "| Step | Status | Market Data Required | Command | Purpose | Warning |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in payload.get("steps", []):
        command = " ".join(item.get("command", []))
        lines.append(
            f"| {item.get('name', '')} | {item.get('status', '')} | {item.get('market_data_required', False)} | "
            f"`{command}` | {item.get('purpose', '')} | `{item.get('warning', '')}` |"
        )
    return "\n".join(lines).rstrip() + "\n"


def tail(value: str, *, limit: int = 2000) -> str:
    if value is None:
        return ""
    text = str(value)
    return text[-limit:]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate or execute Momentum Hunter market-hours proof harness.")
    parser.add_argument("--execute", action="store_true", help="Execute proof steps instead of dry-run planning.")
    parser.add_argument(
        "--allow-live-market",
        action="store_true",
        help="Allow live/delayed market-data-dependent steps when --execute is used.",
    )
    parser.add_argument("--json", type=Path, default=MARKET_HOURS_PROOF_LATEST_JSON)
    parser.add_argument("--md", type=Path, default=MARKET_HOURS_PROOF_LATEST_MD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = run_market_hours_proof_harness(execute=args.execute, allow_live_market=args.allow_live_market)
    paths = write_market_hours_proof_report(payload, json_path=args.json, markdown_path=args.md)
    print(
        json.dumps(
            {
                "overall_status": payload.get("overall_status"),
                "execution_mode": payload.get("execution_mode"),
                "step_count": payload.get("step_count"),
                "executed_steps": payload.get("executed_steps"),
                "skipped_steps": payload.get("skipped_steps"),
                "failed_steps": payload.get("failed_steps"),
                "paths": {key: str(value) for key, value in paths.items()},
            },
            indent=2,
        )
    )
    return 1 if payload.get("overall_status") == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
