from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.config import load_config
from momentum_hunter.market import detect_market_regime
from momentum_hunter.models import CaptureSession, SCANNER_PRESETS
from momentum_hunter.providers import provider_from_name
from momentum_hunter.scoring import score_candidates
from momentum_hunter.storage import save_daily_capture
from momentum_hunter.time_utils import now_central


def main() -> int:
    args = parse_args()
    config = load_config()
    session = CaptureSession(args.session)
    criteria = SCANNER_PRESETS[args.scanner] if args.scanner else SCANNER_PRESETS["Institutional Momentum"]
    provider = provider_from_name(args.provider or config.provider)
    market_regime = detect_market_regime()

    candidates = provider.scan(criteria)
    for candidate in candidates:
        if not candidate.news:
            candidate.news = provider.fetch_news(candidate.ticker)
    candidates = score_candidates(candidates, regime=market_regime.regime)
    json_path, report_path = save_daily_capture(
        candidates=candidates,
        selected_tickers=set(),
        reviewed_tickers=set(),
        criteria=criteria,
        provider=provider.name,
        mode=config.mode,
        session=session,
        market_regime=market_regime,
        capture_time=now_central(),
    )
    print(f"Saved {session.value} capture")
    print(f"JSON: {json_path}")
    print(f"Report: {report_path}")
    print(f"Candidates: {len(candidates)}")
    print(f"Market regime: {market_regime.regime.value}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a headless Momentum Hunter capture.")
    parser.add_argument("--session", choices=[item.value for item in CaptureSession], required=True)
    parser.add_argument("--provider", choices=["sample", "finviz"], default=None)
    parser.add_argument("--scanner", choices=list(SCANNER_PRESETS), default=None)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
