from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from momentum_hunter.config import DATA_DIR, ensure_app_dirs
from momentum_hunter.models import CaptureSession
from momentum_hunter.scheduling import next_automatic_run
from momentum_hunter.storage import ANALYSIS_CSV, CAPTURE_FAILURES_DIR, CAPTURES_DIR
from momentum_hunter.time_utils import CENTRAL_TZ, now_central


OUTCOMES_CSV = DATA_DIR / "analysis-outcomes.csv"


@dataclass(frozen=True)
class CaptureSuccessInfo:
    session: CaptureSession
    capture_time: datetime | None = None
    path: Path | None = None
    candidate_count: int = 0
    provider: str = ""
    scanner: str = ""


@dataclass(frozen=True)
class CaptureFailureInfo:
    failure_time: datetime | None = None
    session: str = ""
    provider: str = ""
    scanner: str = ""
    error_message: str = ""
    path: Path | None = None


@dataclass(frozen=True)
class CsvStatus:
    path: Path
    exists: bool
    row_count: int = 0
    last_updated: datetime | None = None


@dataclass(frozen=True)
class CaptureHealthSnapshot:
    last_morning_capture: CaptureSuccessInfo
    last_evening_capture: CaptureSuccessInfo
    last_preopen_capture: CaptureSuccessInfo
    last_failed_capture: CaptureFailureInfo
    next_morning_run: datetime
    next_evening_run: datetime
    next_preopen_run: datetime
    csv_append_status: CsvStatus
    outcome_update_status: CsvStatus


def build_capture_health_snapshot(
    *,
    now: datetime | None = None,
    captures_dir: Path = CAPTURES_DIR,
    failures_dir: Path = CAPTURE_FAILURES_DIR,
    analysis_csv: Path = ANALYSIS_CSV,
    outcomes_csv: Path = OUTCOMES_CSV,
) -> CaptureHealthSnapshot:
    current = normalize_central(now or now_central())
    return CaptureHealthSnapshot(
        last_morning_capture=latest_successful_capture(CaptureSession.MORNING, captures_dir),
        last_evening_capture=latest_successful_capture(CaptureSession.EVENING, captures_dir),
        last_preopen_capture=latest_successful_capture(CaptureSession.PREOPEN, captures_dir),
        last_failed_capture=latest_capture_failure(failures_dir),
        next_morning_run=next_automatic_run(CaptureSession.MORNING, after=current, captures_dir=captures_dir),
        next_evening_run=next_automatic_run(CaptureSession.EVENING, after=current, captures_dir=captures_dir),
        next_preopen_run=next_automatic_run(CaptureSession.PREOPEN, after=current, captures_dir=captures_dir),
        csv_append_status=csv_status(analysis_csv),
        outcome_update_status=csv_status(outcomes_csv),
    )


def latest_successful_capture(session: CaptureSession, captures_dir: Path = CAPTURES_DIR) -> CaptureSuccessInfo:
    if not captures_dir.exists():
        return CaptureSuccessInfo(session=session)
    best: CaptureSuccessInfo | None = None
    for path in sorted(captures_dir.glob(f"*/{session.value}.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        capture_time = parse_datetime(payload.get("capture_time"))
        if capture_time is None:
            continue
        info = CaptureSuccessInfo(
            session=session,
            capture_time=capture_time,
            path=path,
            candidate_count=len(payload.get("candidates") or []),
            provider=payload.get("provider", ""),
            scanner=(payload.get("scanner") or {}).get("name", ""),
        )
        if best is None or (info.capture_time and best.capture_time and info.capture_time > best.capture_time):
            best = info
    return best or CaptureSuccessInfo(session=session)


def latest_capture_failure(failures_dir: Path = CAPTURE_FAILURES_DIR) -> CaptureFailureInfo:
    if not failures_dir.exists():
        return CaptureFailureInfo()
    best: CaptureFailureInfo | None = None
    for path in sorted(failures_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        failure_time = parse_datetime(payload.get("failure_time"))
        info = CaptureFailureInfo(
            failure_time=failure_time,
            session=payload.get("session", ""),
            provider=payload.get("provider", ""),
            scanner=payload.get("scanner", ""),
            error_message=payload.get("error_message", ""),
            path=path,
        )
        if best is None:
            best = info
        elif info.failure_time and (best.failure_time is None or info.failure_time > best.failure_time):
            best = info
    return best or CaptureFailureInfo()


def next_scheduled_run(run_time: time, current: datetime) -> datetime:
    candidate = current.replace(
        hour=run_time.hour,
        minute=run_time.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def csv_status(path: Path) -> CsvStatus:
    ensure_app_dirs()
    if not path.exists():
        return CsvStatus(path=path, exists=False)
    row_count = 0
    try:
        with path.open(newline="", encoding="utf-8") as file:
            row_count = sum(1 for _ in csv.DictReader(file))
    except OSError:
        row_count = 0
    last_updated = datetime.fromtimestamp(path.stat().st_mtime, tz=CENTRAL_TZ)
    return CsvStatus(path=path, exists=True, row_count=row_count, last_updated=last_updated)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return normalize_central(parsed)


def normalize_central(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=CENTRAL_TZ)
    return value.astimezone(CENTRAL_TZ)
