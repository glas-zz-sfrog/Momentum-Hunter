from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import uuid
from dataclasses import dataclass
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
SHADOW_HANDOFFS_DIR = DATA_DIR / "shadow-trading" / "capture-handoffs"
SHADOW_HANDOFF_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CaptureRunResult:
    exit_code: int
    disposition: str
    report_paths: dict[str, Path]

    @property
    def should_trigger_shadow_selector(self) -> bool:
        return self.disposition in {"CAPTURED", "REPORT_RECOVERED"}


def main() -> int:
    args = parse_args()
    session = CaptureSession(args.session)
    provider_name = args.provider or "config"
    scanner_name = args.scanner or "Institutional Momentum"
    failure_time = now_central()
    try:
        result = run_capture_with_result(args, session=session)
        if args.trigger_shadow_selector:
            if session != CaptureSession.SHADOW:
                raise ValueError(
                    "--trigger-shadow-selector is valid only for the shadow session."
                )
            report_path = result.report_paths.get("json")
            needs_handoff = result.should_trigger_shadow_selector or (
                result.disposition == "DUPLICATE"
                and report_path is not None
                and not shadow_handoff_is_complete(report_path)
            )
            if needs_handoff:
                if report_path is None or not report_path.is_file():
                    raise RuntimeError(
                        "Shadow selector handoff requires the canonical JSON report."
                    )
                from momentum_hunter.engine_host_client import (
                    run_immediate_collection_cycle,
                )

                report_hash = file_sha256(report_path)
                cycle = run_immediate_collection_cycle(
                    command_id=f"shadow-opening-capture-{report_hash}",
                )
                write_shadow_handoff_receipt(
                    report_path,
                    report_hash=report_hash,
                    cycle=cycle,
                )
                print(f"Engine Host selector cycle: {cycle.code}")
                print(cycle.summary)
            else:
                print(
                    "Engine Host selector cycle skipped: "
                    f"{result.disposition}"
                )
        return result.exit_code
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
    return run_capture_with_result(args, session=session).exit_code


def run_capture_with_result(
    args: argparse.Namespace,
    *,
    session: CaptureSession,
) -> CaptureRunResult:
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
            expected = trade_planning_report_paths(
                capture_path,
                reports_dir=REPORTS_DIR,
            )
            reports_preexisting = all(path.exists() for path in expected.values())
            report_paths = ensure_trade_planning_report(capture_path)
            print_report_paths(report_paths, prefix="Existing capture report")
            return CaptureRunResult(
                exit_code=0,
                disposition=(
                    "DUPLICATE"
                    if reports_preexisting
                    else "REPORT_RECOVERED"
                ),
                report_paths=report_paths,
            )
        return CaptureRunResult(
            exit_code=0,
            disposition="SKIPPED",
            report_paths={},
        )

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
    return CaptureRunResult(
        exit_code=0,
        disposition="CAPTURED",
        report_paths=report_paths,
    )


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


def shadow_handoff_receipt_path(
    report_path: Path,
    *,
    handoffs_dir: Path = SHADOW_HANDOFFS_DIR,
) -> Path:
    return handoffs_dir / f"{report_path.stem}.json"


def shadow_handoff_is_complete(
    report_path: Path,
    *,
    handoffs_dir: Path = SHADOW_HANDOFFS_DIR,
) -> bool:
    receipt_path = shadow_handoff_receipt_path(
        report_path,
        handoffs_dir=handoffs_dir,
    )
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    try:
        report_hash = file_sha256(report_path)
    except OSError:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schemaVersion") == SHADOW_HANDOFF_SCHEMA_VERSION
        and payload.get("status") == "ENGINE_HOST_ACCEPTED"
        and payload.get("reportSha256") == report_hash
        and payload.get("transmitting") is False
        and payload.get("orderTransmission") == "UNAVAILABLE"
    )


def write_shadow_handoff_receipt(
    report_path: Path,
    *,
    report_hash: str,
    cycle: object,
    handoffs_dir: Path = SHADOW_HANDOFFS_DIR,
) -> Path:
    receipt_path = shadow_handoff_receipt_path(
        report_path,
        handoffs_dir=handoffs_dir,
    )
    if receipt_path.exists():
        if shadow_handoff_is_complete(
            report_path,
            handoffs_dir=handoffs_dir,
        ):
            return receipt_path
        raise RuntimeError(
            "Existing Shadow selector handoff receipt is invalid or mismatched."
        )
    snapshot = getattr(cycle, "snapshot", {})
    payload = {
        "schemaVersion": SHADOW_HANDOFF_SCHEMA_VERSION,
        "status": "ENGINE_HOST_ACCEPTED",
        "recordedAt": now_central().isoformat(),
        "reportPath": str(report_path.resolve()),
        "reportSha256": report_hash,
        "engineHostInstanceId": (
            str(snapshot.get("hostInstanceId", ""))
            if isinstance(snapshot, dict)
            else ""
        ),
        "cycleCode": str(getattr(cycle, "code", "")),
        "transmitting": False,
        "orderTransmission": "UNAVAILABLE",
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = receipt_path.with_name(
        f"{receipt_path.name}.{uuid.uuid4().hex}.tmp"
    )
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        os.link(temporary, receipt_path)
    except FileExistsError:
        if not shadow_handoff_is_complete(
            report_path,
            handoffs_dir=handoffs_dir,
        ):
            raise RuntimeError(
                "Concurrent Shadow selector handoff receipt is invalid."
            ) from None
    finally:
        temporary.unlink(missing_ok=True)
    return receipt_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a headless Momentum Hunter capture.")
    parser.add_argument("--session", choices=[item.value for item in CaptureSession], required=True)
    parser.add_argument("--provider", choices=["sample", "finviz"], default=None)
    parser.add_argument("--scanner", choices=list(SCANNER_PRESETS), default=None)
    parser.add_argument(
        "--trigger-shadow-selector",
        action="store_true",
        help=(
            "After a new or recovered shadow report, run one immediate guarded "
            "Engine Host collection/selector cycle."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
