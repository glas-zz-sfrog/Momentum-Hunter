from __future__ import annotations

"""Plan bounded, capture-only 08:35 service jobs for future market days."""

import argparse
import json
import re
import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Mapping

from momentum_hunter.automation_supervisor import parse_manifest
from momentum_hunter.scheduling import is_market_open_day
from momentum_hunter.time_utils import CENTRAL_TZ


OPENING_CAPTURE_KIND = "opening_capture"
OPENING_CAPTURE_TIME = time(8, 35)
OPENING_CAPTURE_LATE_WINDOW = timedelta(minutes=5)
DEFAULT_MARKET_SESSIONS = 30
MAX_MARKET_SESSIONS = 90
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def build_opening_capture_jobs(
    *,
    start_date: date,
    market_sessions: int,
    expected_git_head: str,
    shadow_dates: Iterable[date] = (),
) -> list[dict[str, object]]:
    if not 1 <= market_sessions <= MAX_MARKET_SESSIONS:
        raise ValueError(
            f"market_sessions must be between 1 and {MAX_MARKET_SESSIONS}."
        )
    normalized_head = expected_git_head.strip()
    if not GIT_SHA_PATTERN.fullmatch(normalized_head):
        raise ValueError("expected_git_head must be a full lowercase Git SHA.")
    shadow_days = set(shadow_dates)
    jobs: list[dict[str, object]] = []
    candidate = start_date
    covered_sessions = 0
    while covered_sessions < market_sessions:
        if is_market_open_day(candidate):
            covered_sessions += 1
            if candidate not in shadow_days:
                scheduled_at = datetime.combine(
                    candidate,
                    OPENING_CAPTURE_TIME,
                    tzinfo=CENTRAL_TZ,
                )
                jobs.append(
                    {
                        "jobId": f"opening-capture-{candidate:%Y%m%d}",
                        "kind": OPENING_CAPTURE_KIND,
                        "scheduledAt": scheduled_at.isoformat(),
                        "latestStartAt": (
                            scheduled_at + OPENING_CAPTURE_LATE_WINDOW
                        ).isoformat(),
                        "enabled": True,
                        "timeoutSeconds": 900,
                        "expectedGitHead": normalized_head,
                    }
                )
        candidate += timedelta(days=1)
    return jobs


def plan_opening_capture_manifest(
    payload: Mapping[str, object],
    *,
    start_date: date,
    market_sessions: int,
    expected_git_head: str,
    terminal_job_ids: Iterable[str] = (),
) -> dict[str, object]:
    raw_jobs = payload.get("jobs", [])
    if not isinstance(raw_jobs, list):
        raise ValueError("Automation manifest jobs must be a list.")
    terminal_ids = set(terminal_job_ids)
    retained_jobs: list[dict[str, object]] = []
    historical_dependency_kinds = {
        "paper_engineering",
        "successor_setup_pass1",
        "successor_setup_pass2",
    }
    for raw_job in raw_jobs:
        if not isinstance(raw_job, dict):
            continue
        job = dict(raw_job)
        if job.get("kind") == OPENING_CAPTURE_KIND:
            continue
        if job.get("kind") in historical_dependency_kinds:
            scheduled_at = datetime.fromisoformat(str(job.get("scheduledAt", "")))
            if scheduled_at.date() < start_date:
                job_id = str(job.get("jobId", ""))
                if job_id not in terminal_ids:
                    raise ValueError(
                        "A historical dependent job has no terminal service receipt."
                    )
                continue
        retained_jobs.append(job)
    shadow_dates = {
        datetime.fromisoformat(str(job["scheduledAt"])).date()
        for job in retained_jobs
        if job.get("kind") == "shadow_opening"
        and bool(job.get("enabled", True))
    }
    opening_jobs = build_opening_capture_jobs(
        start_date=start_date,
        market_sessions=market_sessions,
        expected_git_head=expected_git_head,
        shadow_dates=shadow_dates,
    )
    opening_by_id = {str(job["jobId"]): job for job in opening_jobs}
    for job in retained_jobs:
        if job.get("kind") not in {"paper_engineering", "successor_setup_pass1"}:
            continue
        dependency_id = str(job.get("dependsOnJobId", ""))
        dependency = opening_by_id.get(dependency_id)
        if dependency is None:
            raise ValueError(
                "A retained dependent opening job has no repinned opening capture."
            )
        job["expectedGitHead"] = dependency["expectedGitHead"]
    retained_by_id = {str(job.get("jobId", "")): job for job in retained_jobs}
    for job in retained_jobs:
        if job.get("kind") != "successor_setup_pass2":
            continue
        dependency_id = str(job.get("dependsOnJobId", ""))
        dependency = retained_by_id.get(dependency_id)
        if dependency is None or dependency.get("kind") != "successor_setup_pass1":
            raise ValueError(
                "A retained Successor Pass 2 job has no repinned Pass 1 dependency."
            )
        job["expectedGitHead"] = dependency["expectedGitHead"]
    planned = dict(payload)
    planned["jobs"] = sorted(
        [*retained_jobs, *opening_jobs],
        key=lambda job: (
            str(job.get("scheduledAt", "")),
            str(job.get("kind", "")),
            str(job.get("jobId", "")),
        ),
    )
    return planned


def write_validated_plan(
    *,
    manifest_path: Path,
    output_path: Path,
    start_date: date,
    market_sessions: int,
    expected_git_head: str,
    terminal_job_ids: Iterable[str] = (),
) -> dict[str, object]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned = plan_opening_capture_manifest(
        payload,
        start_date=start_date,
        market_sessions=market_sessions,
        expected_git_head=expected_git_head,
        terminal_job_ids=terminal_job_ids,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(
        f"{output_path.name}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(planned, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output_path)
        validated = parse_manifest(output_path)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)
    opening_jobs = [
        job for job in validated.jobs if job.kind == OPENING_CAPTURE_KIND
    ]
    return {
        "outputPath": str(output_path),
        "openingCaptureJobs": len(opening_jobs),
        "firstOpeningCapture": (
            opening_jobs[0].scheduled_at.isoformat() if opening_jobs else ""
        ),
        "lastOpeningCapture": (
            opening_jobs[-1].scheduled_at.isoformat() if opening_jobs else ""
        ),
        "marketSessionsCovered": market_sessions,
        "shadowDatesUseShadowCapture": market_sessions - len(opening_jobs),
        "selectorArming": "UNAVAILABLE",
        "orderTransmission": "UNAVAILABLE",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-date", type=date.fromisoformat, required=True)
    parser.add_argument("--expected-git-head", required=True)
    parser.add_argument(
        "--market-sessions",
        type=int,
        default=DEFAULT_MARKET_SESSIONS,
    )
    parser.add_argument("--terminal-job-id", action="append", default=[])
    return parser


def main() -> int:
    args = _parser().parse_args()
    summary = write_validated_plan(
        manifest_path=args.manifest,
        output_path=args.output,
        start_date=args.start_date,
        market_sessions=args.market_sessions,
        expected_git_head=args.expected_git_head,
        terminal_job_ids=args.terminal_job_id,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
