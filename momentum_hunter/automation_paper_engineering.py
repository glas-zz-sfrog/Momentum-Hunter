from __future__ import annotations

"""Install one bounded Alpaca Paper engineering job after an opening capture."""

import argparse
import json
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Mapping

from momentum_hunter.automation_supervisor import parse_manifest


INSTALL_CONFIRMATION = "INSTALL ALPACA PAPER ENGINEERING JOB"
PAPER_JOB_KIND = "paper_engineering"
_GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class PaperAutomationInstallError(RuntimeError):
    pass


def plan_paper_engineering_job(
    payload: Mapping[str, object],
    *,
    market_date: date,
    expected_git_head: str,
) -> dict[str, object]:
    if not _GIT_SHA_PATTERN.fullmatch(expected_git_head):
        raise PaperAutomationInstallError("A full lowercase Git identity is required.")
    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list):
        raise PaperAutomationInstallError("Automation manifest jobs are invalid.")
    opening_id = f"opening-capture-{market_date:%Y%m%d}"
    opening = next(
        (
            item
            for item in raw_jobs
            if isinstance(item, Mapping)
            and item.get("jobId") == opening_id
            and item.get("kind") == "opening_capture"
            and item.get("enabled", True) is True
        ),
        None,
    )
    if opening is None:
        raise PaperAutomationInstallError(
            "The same-date enabled opening capture is not installed."
        )
    if opening.get("expectedGitHead") != expected_git_head:
        raise PaperAutomationInstallError(
            "The opening capture and Paper job Git identities would differ."
        )
    scheduled_at = str(opening.get("scheduledAt", ""))
    if not scheduled_at:
        raise PaperAutomationInstallError("The opening capture schedule is invalid.")
    scheduled = datetime.fromisoformat(scheduled_at)
    if scheduled.date() != market_date:
        raise PaperAutomationInstallError("The opening capture date is invalid.")

    paper_id = f"paper-engineering-{market_date:%Y%m%d}"
    retained = [
        dict(item)
        for item in raw_jobs
        if isinstance(item, Mapping) and item.get("jobId") != paper_id
    ]
    paper = {
        "jobId": paper_id,
        "kind": PAPER_JOB_KIND,
        "scheduledAt": scheduled.isoformat(),
        "latestStartAt": scheduled.replace(minute=50).isoformat(),
        "enabled": True,
        "timeoutSeconds": 25_200,
        "expectedGitHead": expected_git_head,
        "dependsOnJobId": opening_id,
    }
    planned = dict(payload)
    planned["jobs"] = sorted(
        [*retained, paper],
        key=lambda item: (
            str(item.get("scheduledAt", "")),
            str(item.get("kind", "")),
            str(item.get("jobId", "")),
        ),
    )
    return planned


def install_paper_engineering_job(
    *,
    manifest_path: Path,
    market_date: date,
    expected_git_head: str,
    confirmation: str,
) -> dict[str, object]:
    if confirmation != INSTALL_CONFIRMATION:
        raise PaperAutomationInstallError(
            "The exact Paper automation installation confirmation was not provided."
        )
    parse_manifest(manifest_path)
    state_path = manifest_path.parent / "state" / "automation-service-state.json"
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        jobs = state.get("jobs", {}) if isinstance(state, Mapping) else {}
        if isinstance(jobs, Mapping) and any(
            isinstance(value, Mapping) and value.get("status") == "RUNNING"
            for value in jobs.values()
        ):
            raise PaperAutomationInstallError(
                "An automation job is running; the manifest was not changed."
            )
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    planned = plan_paper_engineering_job(
        payload,
        market_date=market_date,
        expected_git_head=expected_git_head,
    )
    temporary = manifest_path.with_name(
        f"{manifest_path.name}.{uuid.uuid4().hex}.tmp"
    )
    backup = manifest_path.with_name(
        f"{manifest_path.name}.{market_date:%Y%m%d}.pre-paper.bak"
    )
    if backup.exists():
        raise PaperAutomationInstallError("The write-once Paper manifest backup exists.")
    try:
        temporary.write_text(
            json.dumps(planned, indent=2) + "\n",
            encoding="utf-8",
        )
        parse_manifest(temporary)
        backup.write_bytes(manifest_path.read_bytes())
        os.replace(temporary, manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    installed = parse_manifest(manifest_path)
    paper_id = f"paper-engineering-{market_date:%Y%m%d}"
    job = next(item for item in installed.jobs if item.job_id == paper_id)
    return {
        "classification": "ALPACA_PAPER_ENGINEERING_JOB_INSTALLED",
        "jobId": job.job_id,
        "dependsOnJobId": job.depends_on_job_id,
        "scheduledAt": job.scheduled_at.isoformat(),
        "latestStartAt": job.latest_start_at.isoformat(),
        "timeoutSeconds": job.timeout_seconds,
        "expectedGitHead": job.expected_git_head,
        "mode": "PAPER_ONLY",
        "liveEndpointReachable": False,
        "manifestPath": str(manifest_path),
        "backupPath": str(backup),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--market-date", type=date.fromisoformat, required=True)
    parser.add_argument("--expected-git-head", required=True)
    parser.add_argument("--confirmation", required=True)
    args = parser.parse_args(argv)
    try:
        result = install_paper_engineering_job(
            manifest_path=args.manifest,
            market_date=args.market_date,
            expected_git_head=args.expected_git_head,
            confirmation=args.confirmation,
        )
    except (PaperAutomationInstallError, OSError, ValueError) as exc:
        print(f"Paper automation installation stopped safely: {type(exc).__name__}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
