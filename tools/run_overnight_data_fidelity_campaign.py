from __future__ import annotations

"""Run the isolated OVERNIGHT-DATA-FIDELITY-001 phase campaign."""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from momentum_hunter.overnight_data_fidelity import (
    TASK_ID,
    OvernightDataFidelityError,
    fingerprint,
    require_sanitized,
    run_checkpoint,
    write_checkpoint,
)


EASTERN = ZoneInfo("America/New_York")
UTC = timezone.utc
MAX_START_LAG_SECONDS = 120.0


@dataclass(frozen=True)
class CampaignCheckpoint:
    code: str
    target_eastern: datetime
    include_capacity: bool = False
    include_websocket: bool = False
    include_finviz: bool = False

    def to_evidence(self) -> dict[str, object]:
        return {
            "code": self.code,
            "targetEastern": self.target_eastern.isoformat(),
            "targetUtc": self.target_eastern.astimezone(UTC).isoformat(),
            "includeCapacity": self.include_capacity,
            "includeWebsocket": self.include_websocket,
            "includeFinviz": self.include_finviz,
        }


def campaign_schedule(session_date: date) -> tuple[CampaignCheckpoint, ...]:
    def at(hour: int, minute: int) -> datetime:
        return datetime.combine(session_date, wall_time(hour, minute), EASTERN)

    return (
        CampaignCheckpoint("BOUNDARY_0355_ET", at(3, 55)),
        CampaignCheckpoint("BOUNDARY_0400_ET", at(4, 0)),
        CampaignCheckpoint("BOUNDARY_0405_ET", at(4, 5), include_capacity=True, include_finviz=True),
        CampaignCheckpoint("BOUNDARY_0415_ET", at(4, 15)),
        CampaignCheckpoint("EARLY_0500_ET", at(5, 0)),
        CampaignCheckpoint("EARLY_0600_ET", at(6, 0)),
        CampaignCheckpoint("PRE_0655_ET", at(6, 55)),
        CampaignCheckpoint("PRE_0700_ET", at(7, 0)),
        CampaignCheckpoint("PRE_0705_ET", at(7, 5), include_capacity=True, include_finviz=True),
        CampaignCheckpoint("PRE_0800_ET", at(8, 0)),
        CampaignCheckpoint("REGULAR_0945_ET", at(9, 45), include_capacity=True, include_finviz=True),
        CampaignCheckpoint("REGULAR_1000_ET", at(10, 0)),
        CampaignCheckpoint("AFTER_1605_ET", at(16, 5), include_finviz=True),
        CampaignCheckpoint("AFTER_1955_ET", at(19, 55)),
        CampaignCheckpoint("OVERNIGHT_2005_ET", at(20, 5), include_capacity=True, include_websocket=True),
    )


def run_campaign(
    *,
    session_date: date,
    output_root: Path,
    universe_source: Path | None,
    source_commit: str,
    clock=lambda: datetime.now(UTC),
    sleeper=time.sleep,
) -> dict[str, object]:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "campaign.lock"
    lock_descriptor = _acquire_lock(lock_path)
    schedule = campaign_schedule(session_date)
    state: dict[str, object] = {
        "taskId": TASK_ID,
        "campaignDate": session_date.isoformat(),
        "status": "RUNNING",
        "processId": os.getpid(),
        "startedAt": _aware(clock()).isoformat(),
        "sourceIdentity": {
            "featureCommit": _source_commit(source_commit),
            "campaignModuleSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest().upper(),
        },
        "schedule": [checkpoint.to_evidence() for checkpoint in schedule],
        "results": [],
        "productionMutation": False,
        "accountRequested": False,
        "positionsRequested": False,
        "ordersRequested": False,
    }
    _write_state(root, state)
    try:
        for checkpoint in schedule:
            existing = root / "checkpoints" / f"{checkpoint.code}.json"
            if existing.exists():
                state["results"].append({
                    "code": checkpoint.code,
                    "classification": "REUSED_EXISTING_WRITE_ONCE_EVIDENCE",
                    "sha256": hashlib.sha256(existing.read_bytes()).hexdigest().upper(),
                })
                _write_state(root, state)
                continue
            target = checkpoint.target_eastern.astimezone(UTC)
            now = _aware(clock())
            while now < target:
                sleeper(min(30.0, (target - now).total_seconds()))
                now = _aware(clock())
            lag = (now - target).total_seconds()
            if lag > MAX_START_LAG_SECONDS:
                result = {
                    "code": checkpoint.code,
                    "classification": "MISSED_BOUNDED_START_WINDOW",
                    "targetEastern": checkpoint.target_eastern.isoformat(),
                    "observedAt": now.isoformat(),
                    "startLagSeconds": round(lag, 6),
                }
                _write_campaign_event_once(root, checkpoint.code, result)
                state["results"].append(result)
                _write_state(root, state)
                continue
            try:
                proof = run_checkpoint(
                    checkpoint_code=checkpoint.code,
                    observed_at=now,
                    include_capacity=checkpoint.include_capacity,
                    include_websocket=checkpoint.include_websocket,
                    include_finviz=checkpoint.include_finviz,
                    universe_source=universe_source,
                )
                json_path, _, json_hash, _ = write_checkpoint(proof, output_root=root)
                result = {
                    "code": checkpoint.code,
                    "classification": "COMPLETED",
                    "startLagSeconds": round(lag, 6),
                    "path": str(json_path),
                    "sha256": json_hash,
                }
            except Exception as exc:
                result = {
                    "code": checkpoint.code,
                    "classification": "FAILED_SAFE",
                    "startLagSeconds": round(lag, 6),
                    "errorType": type(exc).__name__,
                    "credentialMaterialIncluded": False,
                    "accountRequested": False,
                    "positionsRequested": False,
                    "ordersRequested": False,
                }
                _write_campaign_event_once(root, checkpoint.code, result)
            state["results"].append(result)
            _write_state(root, state)
        state["status"] = "TERMINAL"
        state["completedAt"] = _aware(clock()).isoformat()
        _write_state(root, state)
        return state
    finally:
        os.close(lock_descriptor)
        lock_path.unlink(missing_ok=True)


def _acquire_lock(path: Path) -> int:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise OvernightDataFidelityError("An overnight fidelity campaign already owns this root.") from exc
    os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
    os.fsync(descriptor)
    return descriptor


def _write_state(root: Path, state: Mapping[str, object]) -> None:
    payload = dict(state)
    payload["stateFingerprint"] = fingerprint(payload)
    require_sanitized(payload, forbidden_values=())
    target = root / "campaign-state.json"
    temporary = root / "campaign-state.json.tmp"
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, target)


def _write_campaign_event_once(root: Path, code: str, event: Mapping[str, object]) -> None:
    target = root / "campaign-events" / f"{code}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload["eventFingerprint"] = fingerprint(payload)
    require_sanitized(payload, forbidden_values=())
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise OvernightDataFidelityError("Campaign timestamps must be aware.")
    return value.astimezone(UTC)


def _source_commit(value: str) -> str:
    normalized = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", normalized):
        raise OvernightDataFidelityError("The campaign source commit must be a full Git SHA.")
    return normalized


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the isolated overnight-data fidelity campaign.")
    parser.add_argument("--session-date", type=date.fromisoformat, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--universe-source", type=Path)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args(argv)
    try:
        state = run_campaign(
            session_date=args.session_date,
            output_root=args.output_root,
            universe_source=args.universe_source,
            source_commit=args.source_commit,
        )
        print(json.dumps({
            "classification": "CAMPAIGN_TERMINAL",
            "status": state["status"],
            "resultCount": len(state["results"]),
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "classification": "CAMPAIGN_FAILED_SAFE",
            "errorType": type(exc).__name__,
            "credentialMaterialIncluded": False,
            "accountRequested": False,
            "positionsRequested": False,
            "ordersRequested": False,
        }, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
