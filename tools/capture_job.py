from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.config import DATA_DIR, load_config
from momentum_hunter.market import detect_market_regime
from momentum_hunter.models import CaptureSession, SCANNER_PRESETS
from momentum_hunter.providers import ProviderUnavailableError, provider_from_name
from momentum_hunter.scheduling import SkipReason, evaluate_automatic_capture
from momentum_hunter.scoring import score_candidates
from momentum_hunter.score_breakdowns import upsert_score_breakdowns_for_capture_payload
from momentum_hunter.storage import CAPTURES_DIR, file_sha256, save_capture_failure, save_daily_capture
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import (
    build_trade_planning_report,
    capture_date_label,
    export_trade_planning_report,
    parse_datetime,
)


REPORTS_DIR = DATA_DIR / "reports"


def main() -> int:
    args = parse_args()
    session = CaptureSession(args.session)
    provider_name = args.provider or "config"
    scanner_name = args.scanner or "Institutional Momentum"
    failure_time = now_central()
    try:
        return run_capture(args, session=session)
    except Exception as exc:
        traceback_text = traceback.format_exc()
        try:
            config = load_config()
            provider_name = args.provider or config.provider
        except Exception:
            pass
        failure_path = save_capture_failure(
            session=session,
            provider=provider_name,
            scanner=scanner_name,
            error_message=friendly_error_message(exc),
            exception_type=type(exc).__name__,
            traceback_text=traceback_text,
            failure_time=failure_time,
        )
        print(f"Capture failed: {friendly_error_message(exc)}", file=sys.stderr)
        print(f"Failure record: {failure_path}", file=sys.stderr)
        print(traceback_text, file=sys.stderr)
        return 1


def run_capture(args: argparse.Namespace, *, session: CaptureSession) -> int:
    config = load_config()
    criteria = SCANNER_PRESETS[args.scanner] if args.scanner else SCANNER_PRESETS["Institutional Momentum"]
    capture_time = now_central()
    decision = evaluate_automatic_capture(session, current_time=capture_time, captures_dir=CAPTURES_DIR)
    if decision.is_skip:
        print(f"Capture skipped: {decision.skip_reason}")
        print(f"Requested session: {decision.requested_session.value}")
        print(f"Policy session: {decision.capture_session.value}")
        print(f"Calendar status: {decision.classification.capture_calendar_status}")
        print(f"Next market session: {decision.classification.next_market_session_date}")
        print(f"Scheduling policy: {decision.classification.scheduling_policy_version}")
        if decision.skip_reason == SkipReason.SKIP_DUPLICATE_CAPTURE.value:
            capture_path = (
                CAPTURES_DIR
                / decision.run_at.date().isoformat()
                / f"{decision.capture_session.value}.json"
            )
            report_paths = ensure_trade_planning_report(capture_path)
            print_report_paths(report_paths, prefix="Existing capture report")
        return 0

    provider = provider_from_name(args.provider or config.provider)
    market_regime = detect_market_regime()
    candidates = provider.scan(criteria)
    for candidate in candidates:
        if not candidate.news:
            candidate.news = provider.fetch_news(candidate.ticker, as_of=capture_time)
    candidates = score_candidates(candidates, regime=market_regime.regime, now=capture_time)
    json_path, report_path = save_daily_capture(
        candidates=candidates,
        selected_tickers=set(),
        reviewed_tickers=set(),
        criteria=criteria,
        provider=provider.name,
        mode=config.mode,
        session=decision.capture_session,
        market_regime=market_regime,
        capture_time=capture_time,
    )
    print(f"Saved {decision.capture_session.value} capture")
    print(f"Requested session: {decision.requested_session.value}")
    print(f"Calendar status: {decision.classification.capture_calendar_status}")
    print(f"JSON: {json_path}")
    print(f"Report: {report_path}")
    print(f"Candidates: {len(candidates)}")
    print(f"Market regime: {market_regime.regime.value}")
    try:
        upsert_score_breakdowns_for_capture_payload(json.loads(json_path.read_text(encoding="utf-8")))
        print("Score breakdowns updated")
    except Exception as exc:
        print(f"Score breakdown update failed: {exc}", file=sys.stderr)
    report_paths = ensure_trade_planning_report(json_path)
    print_report_paths(report_paths, prefix="Trade planning")
    return 0


def ensure_trade_planning_report(
    capture_path: Path,
    *,
    reports_dir: Path = REPORTS_DIR,
) -> dict[str, Path]:
    if not capture_path.exists():
        raise FileNotFoundError(f"Raw capture JSON is missing: {capture_path}")
    expected = trade_planning_report_paths(capture_path, reports_dir=reports_dir)
    existing = {name: path.exists() for name, path in expected.items()}
    if all(existing.values()):
        validate_trade_planning_report(expected["json"], capture_path)
        return expected
    if any(existing.values()):
        incomplete = ", ".join(name for name, exists in existing.items() if exists)
        raise RuntimeError(
            "A partial derived TradePlan report already exists; refusing to overwrite it. "
            f"Existing outputs: {incomplete}"
        )

    capture_payload = json.loads(capture_path.read_text(encoding="utf-8"))
    capture_timestamp = parse_datetime(str(capture_payload.get("capture_time", "")))
    generated_at = now_central()
    if capture_timestamp is None or generated_at < capture_timestamp:
        raise ValueError("TradePlan report time cannot precede the source capture.")
    capture_hash = file_sha256(capture_path)
    report = build_trade_planning_report(
        capture_path,
        fetch_bars=True,
        fetch_market_data=True,
        as_of=generated_at,
    )
    actual = export_trade_planning_report(report, reports_dir)
    if actual != expected:
        raise RuntimeError("TradePlan report export returned unexpected output paths.")
    if file_sha256(capture_path) != capture_hash:
        raise RuntimeError("TradePlan report generation mutated the immutable raw capture.")
    validate_trade_planning_report(actual["json"], capture_path)
    return actual


def trade_planning_report_paths(
    capture_path: Path,
    *,
    reports_dir: Path = REPORTS_DIR,
) -> dict[str, Path]:
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    capture_time = str(payload.get("capture_time", ""))
    session = str(payload.get("session", "")).strip()
    parsed_capture_time = parse_datetime(capture_time)
    if (
        parsed_capture_time is None
        or parsed_capture_time.tzinfo is None
        or parsed_capture_time.utcoffset() is None
    ):
        raise ValueError("Raw capture is missing a valid offset-aware capture_time.")
    valid_sessions = {item.value for item in CaptureSession}
    if session not in valid_sessions:
        raise ValueError("Raw capture is missing a valid session.")
    base = f"trade-plan-briefing-{capture_date_label(capture_time)}-{session}"
    return {
        "csv": reports_dir / f"{base}.csv",
        "json": reports_dir / f"{base}.json",
        "report": reports_dir / f"{base}.md",
    }


def validate_trade_planning_report(report_path: Path, capture_path: Path) -> None:
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata")
    capture_payload = json.loads(capture_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("Derived TradePlan report is missing metadata.")
    expected_capture_time = str(capture_payload.get("capture_time", ""))
    expected_session = str(capture_payload.get("session", "")).strip()
    if str(metadata.get("source_capture_time", "")) != expected_capture_time:
        raise ValueError("Derived TradePlan report does not match the source capture time.")
    if str(metadata.get("source_session", "")) != expected_session:
        raise ValueError("Derived TradePlan report does not match the source capture session.")
    source_path = Path(str(metadata.get("source_capture_path", "")))
    if source_path.resolve() != capture_path.resolve():
        raise ValueError("Derived TradePlan report does not match the source capture path.")
    generated_at = parse_datetime(str(metadata.get("generated_at", "")))
    capture_time = parse_datetime(expected_capture_time)
    if (
        generated_at is None
        or generated_at.tzinfo is None
        or generated_at.utcoffset() is None
        or capture_time is None
        or generated_at < capture_time
    ):
        raise ValueError("Derived TradePlan report has invalid prospective timing.")
    candidates = payload.get("candidates")
    source_candidates = capture_payload.get("candidates")
    if not isinstance(candidates, list) or not isinstance(source_candidates, list):
        raise ValueError("Derived TradePlan report or source capture has invalid candidates.")
    if len(candidates) != len(source_candidates):
        raise ValueError("Derived TradePlan report candidate count does not match the source capture.")


def print_report_paths(paths: dict[str, Path], *, prefix: str) -> None:
    print(f"{prefix} CSV: {paths['csv']}")
    print(f"{prefix} JSON: {paths['json']}")
    print(f"{prefix} report: {paths['report']}")


def friendly_error_message(exc: Exception) -> str:
    if isinstance(exc, ProviderUnavailableError):
        return exc.user_message
    return str(exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a headless Momentum Hunter capture.")
    parser.add_argument("--session", choices=[item.value for item in CaptureSession], required=True)
    parser.add_argument("--provider", choices=["sample", "finviz"], default=None)
    parser.add_argument("--scanner", choices=list(SCANNER_PRESETS), default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
