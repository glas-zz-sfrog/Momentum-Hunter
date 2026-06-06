from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.config import load_config
from momentum_hunter.market import detect_market_regime
from momentum_hunter.models import CaptureSession, SCANNER_PRESETS
from momentum_hunter.providers import ProviderUnavailableError, provider_from_name
from momentum_hunter.scoring import score_candidates
from momentum_hunter.score_breakdowns import upsert_score_breakdowns_for_capture_payload
from momentum_hunter.storage import save_capture_failure, save_daily_capture
from momentum_hunter.time_utils import now_central


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
    provider = provider_from_name(args.provider or config.provider)
    market_regime = detect_market_regime()
    capture_time = now_central()

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
        session=session,
        market_regime=market_regime,
        capture_time=capture_time,
    )
    print(f"Saved {session.value} capture")
    print(f"JSON: {json_path}")
    print(f"Report: {report_path}")
    print(f"Candidates: {len(candidates)}")
    print(f"Market regime: {market_regime.regime.value}")
    try:
        upsert_score_breakdowns_for_capture_payload(json.loads(json_path.read_text(encoding="utf-8")))
        print("Score breakdowns updated")
    except Exception as exc:
        print(f"Score breakdown update failed: {exc}", file=sys.stderr)
    return 0


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
