from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.config import DATA_DIR, load_config
from momentum_hunter.market import detect_market_regime
from momentum_hunter.models import CaptureSession, SCANNER_PRESETS
from momentum_hunter.opening_candle_readiness import (
    MAX_OPENING_SYMBOLS,
    failed_opening_candle_readiness,
    prepare_opening_candle_readiness,
)
from momentum_hunter.providers import ProviderUnavailableError, provider_from_name
from momentum_hunter.scheduling import SkipReason, evaluate_automatic_capture
from momentum_hunter.scoring import score_candidates
from momentum_hunter.score_breakdowns import upsert_score_breakdowns_for_capture_payload
from momentum_hunter.storage import (
    CAPTURES_DIR,
    ensure_raw_capture_artifacts,
    file_sha256,
    save_capture_failure,
    save_daily_capture,
)
from momentum_hunter.shadow_opening import (
    ShadowOpeningSafetyError,
    build_https_clock_skew_proof,
    build_shadow_handoff_receipt,
    canonical_json,
    clock_skew_findings,
    shadow_handoff_findings,
)
from momentum_hunter.time_utils import now_central
from momentum_hunter.trade_planning import (
    build_trade_planning_report,
    capture_date_label,
    export_trade_planning_report,
    parse_datetime,
)


REPORTS_DIR = DATA_DIR / "reports"
SHADOW_HANDOFFS_DIR = DATA_DIR / "shadow-trading" / "capture-handoffs"
SHADOW_RETRYABLE_INFRASTRUCTURE_EXIT = 75
OPENING_CLOCK_URL = "https://finviz.com/"
OPENING_CLOCK_SOURCE = "finviz.com:https_date"
OPENING_REPORT_REQUEST_TIMEOUT_SECONDS = 5.0
OPENING_REPORT_NETWORK_CANDIDATE_LIMIT = 5


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
        if (
            getattr(args, "require_opening_result", False)
            and session != CaptureSession.OPENING
        ):
            raise ValueError(
                "--require-opening-result is valid only for the opening session."
            )
        if args.trigger_shadow_selector:
            require_frozen_shadow_arguments(args)
        result = run_capture_with_result(args, session=session)
        if getattr(args, "require_opening_result", False):
            if result.disposition not in {
                "CAPTURED",
                "REPORT_RECOVERED",
                "DUPLICATE",
            }:
                raise RuntimeError(
                    "Required opening capture result was not produced: "
                    f"{result.disposition}."
                )
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
                if not getattr(args, "shadow_opening_proof_only", False):
                    ensure_shadow_engine_host_ready()
                if report_path is None or not report_path.is_file():
                    raise RuntimeError(
                        "Shadow selector handoff requires the canonical JSON report."
                    )
                selector_proof_bundle = getattr(
                    args,
                    "selector_proof_bundle",
                    None,
                )
                if selector_proof_bundle is not None:
                    from momentum_hunter.shadow_arm_ceremony import (
                        complete_shadow_selector_arm,
                        verify_shadow_opening_proof,
                    )

                    ceremony_runner = (
                        verify_shadow_opening_proof
                        if getattr(
                            args,
                            "shadow_opening_proof_only",
                            False,
                        )
                        else complete_shadow_selector_arm
                    )
                    ceremony = ceremony_runner(
                        selector_proof_bundle,
                        report_path,
                        task_definition_path=args.task_definition,
                        expected_provider=args.provider,
                        expected_scanner=args.scanner,
                    )
                    print(f"Shadow selector arm ceremony: {ceremony.state}")
                    if ceremony.candidate:
                        print(f"Proof candidate: {ceremony.candidate}")
                if getattr(args, "shadow_opening_proof_only", False):
                    print(
                        "Engine Host selector cycle skipped: "
                        "UNARMED_OPENING_PROOF_ONLY"
                    )
                    return result.exit_code
                from momentum_hunter.engine_host_client import (
                    run_immediate_collection_cycle,
                )

                report_hash = file_sha256(report_path)
                command_id = f"shadow-opening-capture-{report_hash}"
                cycle = run_immediate_collection_cycle(
                    command_id=command_id,
                )
                write_shadow_handoff_receipt(
                    report_path,
                    report_hash=report_hash,
                    capture_id=capture_identity(report_path),
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
        retryable = shadow_error_is_retryable(
            exc,
            session=session,
            trigger_shadow_selector=bool(
                getattr(args, "trigger_shadow_selector", False)
            ),
        ) or opening_error_is_retryable(exc, session=session)
        return SHADOW_RETRYABLE_INFRASTRUCTURE_EXIT if retryable else 1


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
            ensure_raw_capture_artifacts(capture_path)
            expected = trade_planning_report_paths(
                capture_path,
                reports_dir=REPORTS_DIR,
            )
            reports_preexisting = all(path.exists() for path in expected.values())
            report_options = {
                "expected_provider": args.provider or config.provider,
                "expected_scanner": args.scanner or "Institutional Momentum",
                "request_timeout_seconds": (
                    OPENING_REPORT_REQUEST_TIMEOUT_SECONDS
                    if session == CaptureSession.OPENING
                    else 20.0
                ),
                "network_candidate_limit": (
                    OPENING_REPORT_NETWORK_CANDIDATE_LIMIT
                    if session == CaptureSession.OPENING
                    else None
                ),
            }
            if session == CaptureSession.OPENING:
                report_options["prepare_opening_candles"] = True
            report_paths = ensure_trade_planning_report(
                capture_path,
                **report_options,
            )
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

    if session == CaptureSession.OPENING:
        proof = verify_opening_https_clock()
        print(
            "Opening HTTPS clock proof: "
            f"{proof['status']} | source={proof['source']} | "
            f"skewMs={proof['signedSkewMilliseconds']} | "
            f"uncertaintyMs={proof['measurementUncertaintyMilliseconds']}"
        )

    provider = provider_from_name(args.provider or config.provider)
    market_regime = detect_market_regime()
    candidates = provider.scan(criteria)
    scan_diagnostics = getattr(provider, "last_scan_diagnostics", None)
    if scan_diagnostics is not None:
        print(
            "Provider contract: "
            f"schema={scan_diagnostics.schema_fingerprint} | "
            f"rows={scan_diagnostics.data_row_count} | "
            f"parsed={scan_diagnostics.parsed_row_count} | "
            f"qualifying={scan_diagnostics.qualifying_candidate_count}"
        )
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
    report_options = {
        "expected_provider": provider.name,
        "expected_scanner": criteria.name,
        "request_timeout_seconds": (
            OPENING_REPORT_REQUEST_TIMEOUT_SECONDS
            if session == CaptureSession.OPENING
            else 20.0
        ),
        "network_candidate_limit": (
            OPENING_REPORT_NETWORK_CANDIDATE_LIMIT
            if session == CaptureSession.OPENING
            else None
        ),
    }
    if session == CaptureSession.OPENING:
        report_options["prepare_opening_candles"] = True
    report_paths = ensure_trade_planning_report(
        json_path,
        **report_options,
    )
    print_report_paths(report_paths, prefix="Trade planning")
    return CaptureRunResult(
        exit_code=0,
        disposition="CAPTURED",
        report_paths=report_paths,
    )


def verify_opening_https_clock(
    *,
    url: str = OPENING_CLOCK_URL,
    timeout_seconds: float = 10.0,
    opener: Callable[..., object] = urlopen,
    utc_clock: Callable[[], datetime] | None = None,
) -> dict[str, object]:
    clock = utc_clock or (lambda: datetime.now(timezone.utc))
    request_started_at = clock()
    request = Request(
        url,
        method="HEAD",
        headers={"User-Agent": "MomentumHunter/1.0 clock-preflight"},
    )
    with opener(request, timeout=timeout_seconds) as response:
        remote_date = str(response.headers.get("Date", ""))
    response_received_at = clock()
    proof = build_https_clock_skew_proof(
        request_started_at=request_started_at,
        response_received_at=response_received_at,
        remote_date_header=remote_date,
        source_identity=OPENING_CLOCK_SOURCE,
    )
    findings = clock_skew_findings(
        proof,
        evaluated_at=response_received_at,
    )
    if findings:
        raise RuntimeError(
            "Opening capture clock preflight failed closed: "
            + " | ".join(findings)
        )
    return proof


def ensure_trade_planning_report(
    capture_path: Path,
    *,
    reports_dir: Path = REPORTS_DIR,
    expected_provider: str | None = None,
    expected_scanner: str | None = None,
    request_timeout_seconds: float = 20.0,
    network_candidate_limit: int | None = None,
    prepare_opening_candles: bool = False,
) -> dict[str, Path]:
    if not capture_path.exists():
        raise FileNotFoundError(f"Raw capture JSON is missing: {capture_path}")
    expected = trade_planning_report_paths(capture_path, reports_dir=reports_dir)
    existing = {name: path.exists() for name, path in expected.items()}
    if existing["json"]:
        if not all(existing.values()):
            missing = ", ".join(
                name for name, exists in existing.items() if not exists
            )
            raise RuntimeError(
                "The completed TradePlan JSON exists but companion outputs are "
                f"missing: {missing}."
            )
        validate_trade_planning_report(
            expected["json"],
            capture_path,
            expected_provider=expected_provider,
            expected_scanner=expected_scanner,
        )
        return expected

    capture_payload = json.loads(capture_path.read_text(encoding="utf-8"))
    capture_timestamp = parse_datetime(str(capture_payload.get("capture_time", "")))
    readiness = None
    readiness_evidence: dict[str, object] | None = None
    readiness_warning: str | None = None
    if prepare_opening_candles:
        raw_symbols = tuple(
            str(item.get("ticker", "")).strip().upper()
            for item in capture_payload.get("candidates", [])
            if isinstance(item, dict) and str(item.get("ticker", "")).strip()
        )
        symbols = tuple(dict.fromkeys(raw_symbols))[:MAX_OPENING_SYMBOLS]
        if symbols and capture_timestamp is not None:
            try:
                readiness = prepare_opening_candle_readiness(
                    symbols,
                    evidence_as_of=capture_timestamp,
                )
                readiness_evidence = readiness.to_evidence()
                print(
                    "Opening candle readiness: "
                    f"{readiness.status} | attempts={len(readiness.attempts)} | "
                    + " | ".join(
                        f"{symbol}="
                        f"{item.get('openingBarCount', 0)}/"
                        f"{item.get('requiredOpeningBarCount', 5)} bars,"
                        f"{item.get('baselineSessionCount', 0)}/"
                        f"{item.get('minimumBaselineSessions', 5)} baseline"
                        for symbol, item in sorted(readiness.symbol_evidence.items())
                    )
                )
                if not readiness.ready:
                    readiness_warning = (
                        "Opening candle readiness failed closed: "
                        f"{readiness.status}."
                    )
            except Exception as exc:
                failure_finding = (
                    f"OPENING_CANDLE_READINESS_FAILED:{type(exc).__name__}"
                )
                readiness = failed_opening_candle_readiness(
                    symbols,
                    evidence_as_of=capture_timestamp,
                    finding=failure_finding,
                )
                readiness_evidence = readiness.to_evidence()
                readiness_warning = (
                    "Opening candle readiness failed closed: "
                    f"{type(exc).__name__}."
                )
                print(readiness_warning, file=sys.stderr)

    generated_at = now_central()
    if capture_timestamp is None or generated_at < capture_timestamp:
        raise ValueError("TradePlan report time cannot precede the source capture.")
    capture_hash = file_sha256(capture_path)
    build_options = {
        "fetch_bars": True,
        "fetch_market_data": True,
        "as_of": generated_at,
        "request_timeout_seconds": request_timeout_seconds,
        "network_candidate_limit": network_candidate_limit,
    }
    if readiness is not None:
        build_options["rvol_evidence_by_ticker"] = readiness.rvol_by_symbol
        build_options["intraday_bars_by_ticker"] = readiness.bars_by_symbol
    report = build_trade_planning_report(capture_path, **build_options)
    if readiness_evidence is not None or readiness_warning is not None:
        report = replace(
            report,
            opening_candle_readiness=readiness_evidence,
            warnings=(
                [*getattr(report, "warnings", []), readiness_warning]
                if readiness_warning is not None
                else getattr(report, "warnings", [])
            ),
        )
    actual = export_trade_planning_report(report, reports_dir)
    if actual != expected:
        raise RuntimeError("TradePlan report export returned unexpected output paths.")
    if file_sha256(capture_path) != capture_hash:
        raise RuntimeError("TradePlan report generation mutated the immutable raw capture.")
    validate_trade_planning_report(
        actual["json"],
        capture_path,
        expected_provider=expected_provider,
        expected_scanner=expected_scanner,
    )
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


def validate_trade_planning_report(
    report_path: Path,
    capture_path: Path,
    *,
    expected_provider: str | None = None,
    expected_scanner: str | None = None,
) -> None:
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
    report_provider = str(metadata.get("source_provider", "")).strip()
    report_scanner = str(metadata.get("source_scanner", "")).strip()
    capture_provider = str(capture_payload.get("provider", "")).strip()
    capture_scanner = capture_payload.get("scanner")
    capture_scanner_name = (
        str(capture_scanner.get("name", "")).strip()
        if isinstance(capture_scanner, dict)
        else ""
    )
    if report_provider != capture_provider:
        raise ValueError(
            "Derived TradePlan report provider does not match the source capture."
        )
    if report_scanner != capture_scanner_name:
        raise ValueError(
            "Derived TradePlan report scanner does not match the source capture."
        )
    if (
        expected_provider is not None
        and report_provider.lower() != expected_provider.strip().lower()
    ):
        raise ValueError(
            "Derived TradePlan report provider does not match frozen configuration."
        )
    if (
        expected_scanner is not None
        and report_scanner != expected_scanner.strip()
    ):
        raise ValueError(
            "Derived TradePlan report scanner does not match frozen configuration."
        )
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
    return not shadow_handoff_findings(
        payload,
        expected_report_sha256=report_hash,
    )


def write_shadow_handoff_receipt(
    report_path: Path,
    *,
    report_hash: str,
    capture_id: str,
    cycle: object,
    handoffs_dir: Path = SHADOW_HANDOFFS_DIR,
) -> Path:
    receipt_path = shadow_handoff_receipt_path(
        report_path,
        handoffs_dir=handoffs_dir,
    )
    payload = build_shadow_handoff_receipt(
        report_path=report_path,
        report_sha256=report_hash,
        capture_id=capture_id,
        cycle=cycle,
        recorded_at=now_central(),
    )
    if receipt_path.exists():
        if shadow_handoff_is_complete(
            report_path,
            handoffs_dir=handoffs_dir,
        ):
            return receipt_path
        preserve_incomplete_handoff_receipt(receipt_path)
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


def preserve_incomplete_handoff_receipt(receipt_path: Path) -> Path:
    payload = receipt_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()[:16]
    preserved = receipt_path.with_name(
        f"{receipt_path.stem}.incomplete-{digest}{receipt_path.suffix}"
    )
    if preserved.exists():
        preserved = receipt_path.with_name(
            f"{receipt_path.stem}.incomplete-{digest}-{uuid.uuid4().hex}"
            f"{receipt_path.suffix}"
        )
    receipt_path.replace(preserved)
    return preserved


def capture_identity(report_path: Path) -> str:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowOpeningSafetyError(
            "Shadow handoff report identity cannot be loaded."
        ) from exc
    metadata = report.get("metadata") if isinstance(report, dict) else None
    if not isinstance(metadata, dict):
        raise ShadowOpeningSafetyError(
            "Shadow handoff report metadata is missing."
        )
    source_path = str(metadata.get("source_capture_path", "")).strip()
    source_time = str(metadata.get("source_capture_time", "")).strip()
    if not source_path or not source_time:
        raise ShadowOpeningSafetyError(
            "Shadow handoff source capture identity is incomplete."
        )
    return hashlib.sha256(
        canonical_json(
            {
                "sourceCapturePath": str(Path(source_path).resolve()),
                "sourceCaptureTime": source_time,
            }
        ).encode("ascii")
    ).hexdigest()


def require_frozen_shadow_arguments(args: argparse.Namespace) -> None:
    required = {
        "provider": getattr(args, "provider", None),
        "scanner": getattr(args, "scanner", None),
        "selector proof bundle": getattr(
            args,
            "selector_proof_bundle",
            None,
        ),
        "scheduled-task definition": getattr(
            args,
            "task_definition",
            None,
        ),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ShadowOpeningSafetyError(
            "Official Shadow opening requires explicit frozen "
            + ", ".join(missing)
            + "."
        )


def ensure_shadow_engine_host_ready() -> None:
    from momentum_hunter.engine_host_client import ensure_engine_host
    from momentum_hunter.shadow_market_validity import (
        SHADOW_SELECTOR_ARM_SCHEMA_VERSION,
    )

    ensure_engine_host()
    print(
        "Engine Host runtime preflight: "
        f"CURRENT / selector-arm schema {SHADOW_SELECTOR_ARM_SCHEMA_VERSION}"
    )


def shadow_error_is_retryable(
    exc: Exception,
    *,
    session: CaptureSession,
    trigger_shadow_selector: bool,
) -> bool:
    if session != CaptureSession.SHADOW or not trigger_shadow_selector:
        return False
    from momentum_hunter.engine_host_client import EngineHostRetryableError
    from momentum_hunter.schwab_market_data import (
        SchwabMarketDataNetworkError,
    )

    return isinstance(
        exc,
        (
            EngineHostRetryableError,
            ProviderUnavailableError,
            SchwabMarketDataNetworkError,
        ),
    ) and getattr(exc, "reason", "") != "contract_drift"


def opening_error_is_retryable(
    exc: Exception,
    *,
    session: CaptureSession,
) -> bool:
    if session != CaptureSession.OPENING:
        return False
    return isinstance(
        exc,
        (
            ConnectionError,
            ProviderUnavailableError,
            TimeoutError,
            URLError,
        ),
    ) and getattr(exc, "reason", "") != "contract_drift"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a headless Momentum Hunter capture.")
    parser.add_argument("--session", choices=[item.value for item in CaptureSession], required=True)
    parser.add_argument("--provider", choices=["sample", "finviz"], default=None)
    parser.add_argument("--scanner", choices=list(SCANNER_PRESETS), default=None)
    parser.add_argument(
        "--require-opening-result",
        action="store_true",
        help=(
            "Fail the service-run opening job unless a capture, recovered "
            "report, or verified duplicate exists."
        ),
    )
    parser.add_argument(
        "--trigger-shadow-selector",
        action="store_true",
        help=(
            "After a new or recovered shadow report, run one immediate guarded "
            "Engine Host collection/selector cycle."
        ),
    )
    parser.add_argument(
        "--task-definition",
        type=Path,
        help=(
            "Exported immutable Windows scheduled-task definition used by "
            "the Official Shadow opening proof."
        ),
    )
    parser.add_argument(
        "--shadow-opening-proof-only",
        action="store_true",
        help=(
            "Finalize and verify opening evidence without arming or invoking "
            "the selector."
        ),
    )
    parser.add_argument(
        "--selector-proof-bundle",
        type=Path,
        help=(
            "Exact canonical static proof bundle to finalize and arm before "
            "the immediate Shadow selector cycle."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
