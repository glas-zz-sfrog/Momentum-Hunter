from __future__ import annotations

import sys
from contextlib import ExitStack
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.models import Candidate, NewsItem
from momentum_hunter.news_age import apply_candidate_news_freshness
from momentum_hunter.recommendations import (
    RecommendationReport,
    ScoreWeightRecommendation,
)
from momentum_hunter.study import RegimeSummary, ScoreBucketSummary, StudySummary
from momentum_hunter.time_utils import now_central
from momentum_hunter.ui.data_view_state import DataViewState


OUTPUT_DIR = PROJECT_ROOT / "docs" / "screenshots"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])

    with ExitStack() as stack:
        stack.enter_context(patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None))
        stack.enter_context(patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None))
        stack.enter_context(patch.object(MomentumHunterWindow, "refresh_market_regime", lambda window, show_status=True: None))

        window = MomentumHunterWindow()
        window.resize(1280, 780)
        window.candidates = demo_candidates()
        window.saved_candidates = {"PATH": window.candidates[0], "HPE": window.candidates[1]}
        window.reviewed_tickers = {"PATH", "HPE", "INFY"}
        window.live_candidates = list(window.candidates)
        window.live_saved_candidates = dict(window.saved_candidates)
        window.live_reviewed_tickers = set(window.reviewed_tickers)
        window.current_capture_time = now_central() - timedelta(seconds=45)
        window.display_capture_time = window.current_capture_time
        window.display_session_label = "live"
        window.data_view_state = DataViewState.CURRENT
        window._apply_data_view_state()
        window._populate_table()
        saved = [save_widget(app, window, "momentum_hunter_current_dashboard.png")]

        window._load_historical_capture(historical_payload())
        saved.append(save_widget(app, window, "momentum_hunter_historical_snapshot.png"))

        def capture_dialog(dialog: QDialog) -> int:
            saved.append(save_widget(app, dialog, "momentum_hunter_study_engine.png"))
            dialog.close()
            return 0

        stack.enter_context(patch.object(QDialog, "exec", capture_dialog))
        stack.enter_context(patch("momentum_hunter.app.build_capture_study", return_value=study_summary()))
        stack.enter_context(patch("momentum_hunter.app.build_weight_recommendations", return_value=recommendation_report()))
        window._show_study_dialog(study_summary())

        window.close()

    print("Saved UI screenshots:")
    for path in saved:
        print(f" - {path}")
    return 0


def save_widget(app: QApplication, widget, filename: str) -> Path:
    widget.show()
    widget.raise_()
    widget.activateWindow()
    settle(app)
    path = OUTPUT_DIR / filename
    pixmap = widget.grab()
    if pixmap.isNull():
        raise RuntimeError(f"Could not capture screenshot for {filename}")
    if not pixmap.save(str(path), "PNG"):
        raise RuntimeError(f"Could not save screenshot to {path}")
    return path


def settle(app: QApplication) -> None:
    for _ in range(8):
        app.processEvents()


def demo_candidates() -> list[Candidate]:
    current = now_central()
    rows = [
        ("PATH", "UiPath Inc", 13.10, 11.8, 67_981_128, 1.85, 6_800_000_000, 96, 11, "earnings catalyst, beat catalyst, AI catalyst"),
        ("HPE", "Hewlett Packard Enterprise", 47.00, 9.2, 115_597_824, 1.44, 62_400_000_000, 95, 22, "AI infrastructure catalyst, institutional volume"),
        ("INFY", "Infosys Ltd ADR", 13.41, 6.0, 34_182_096, 1.31, 54_400_000_000, 90, 56, "partnership catalyst, large-cap participation"),
        ("ORCL", "Oracle Corp", 248.15, 9.9, 48_389_992, 1.53, 713_700_000_000, 89, 120, "AI catalyst, cloud infrastructure momentum"),
        ("IBM", "International Business Machines", 320.42, 7.6, 32_880_180, 1.27, 301_200_000_000, 89, 240, "enterprise AI catalyst, institutional participation"),
        ("NVDA", "NVIDIA Corp", 224.36, 6.3, 212_793_744, 1.22, 5_400_000_000_000, 74, 672, "AI infrastructure theme"),
    ]
    candidates: list[Candidate] = []
    for ticker, company, price, change, volume, rel_vol, market_cap, score, hours_old, reasons in rows:
        candidate = Candidate(
            ticker=ticker,
            company=company,
            price=price,
            percent_change=change,
            volume=volume,
            relative_volume=rel_vol,
            market_cap=market_cap,
            sector="Technology",
            industry="Software - Infrastructure",
            news=[
                NewsItem(
                    headline=f"{company} momentum headline with AI catalyst",
                    source="Finviz",
                    published_at=current - timedelta(hours=hours_old),
                    url=f"https://example.com/{ticker.lower()}",
                    summary="Review catalyst quality before making a trading decision.",
                )
            ],
            score=score,
            score_reasons=[reasons],
            score_profile="regime-aware-v1",
            score_regime="bull",
        )
        candidates.append(apply_candidate_news_freshness(candidate, now=current))
    return candidates


def historical_payload() -> dict:
    capture_time = now_central() - timedelta(days=2)
    return {
        "capture_time": capture_time.isoformat(),
        "session": "evening",
        "candidates": [
            {**candidate_to_payload(item), "selected": item.ticker in {"PATH", "HPE"}, "reviewed": item.ticker != "NVDA"}
            for item in demo_candidates()
        ],
    }


def candidate_to_payload(candidate: Candidate) -> dict:
    return {
        "ticker": candidate.ticker,
        "company": candidate.company,
        "price": candidate.price,
        "percent_change": candidate.percent_change,
        "volume": candidate.volume,
        "relative_volume": candidate.relative_volume,
        "market_cap": candidate.market_cap,
        "sector": candidate.sector,
        "industry": candidate.industry,
        "news": [
            {
                "headline": item.headline,
                "source": item.source,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "url": item.url,
                "summary": item.summary,
            }
            for item in candidate.news
        ],
        "score": candidate.score,
        "news_hours_old": candidate.news_hours_old,
        "freshness": candidate.freshness,
        "freshness_score": candidate.freshness_score,
        "score_reasons": candidate.score_reasons,
        "score_profile": candidate.score_profile,
        "score_regime": candidate.score_regime,
        "user_notes": candidate.user_notes,
        "saved_at": None,
    }


def study_summary() -> StudySummary:
    return StudySummary(
        run_id="2026-06-03_study_v1",
        source_range="2026-06-01 to 2026-06-03 | Filter: all candidates",
        capture_count=4,
        candidate_count=24,
        selected_count=7,
        reviewed_count=15,
        scoring_profiles=["regime-aware-v1"],
        outcome_count=18,
        complete_outcome_count=12,
        avg_next_day_return_pct=0.85,
        avg_five_day_return_pct=2.15,
        next_day_win_rate_pct=61.1,
        five_day_win_rate_pct=66.7,
        score_buckets=[
            ScoreBucketSummary("0-49", count=0),
            ScoreBucketSummary("50-69", count=3, reviewed_count=1, avg_next_day_return_pct=-0.4, avg_five_day_return_pct=-1.1),
            ScoreBucketSummary("70-84", count=9, selected_count=2, reviewed_count=5, avg_next_day_return_pct=0.5, avg_five_day_return_pct=1.2),
            ScoreBucketSummary("85-100", count=12, selected_count=5, reviewed_count=9, avg_next_day_return_pct=1.3, avg_five_day_return_pct=3.1),
        ],
        regimes=[
            RegimeSummary("bull", 14),
            RegimeSummary("neutral", 10),
        ],
        has_data=True,
    )


def recommendation_report() -> RecommendationReport:
    return RecommendationReport(
        status="Sample handoff recommendations generated from completed 5-day outcomes.",
        minimum_rows=20,
        completed_rows=24,
        recommendations=[
            ScoreWeightRecommendation(
                regime="bull",
                bucket="85-100",
                sample_size=12,
                avg_five_day_return_pct=3.1,
                win_rate_pct=66.7,
                recommendation="Keep or modestly increase high-score momentum/catalyst weight",
                rationale="The top score bucket is outperforming the 70-84 bucket in this sample.",
            ),
            ScoreWeightRecommendation(
                regime="neutral",
                bucket="50-69",
                sample_size=3,
                avg_five_day_return_pct=-1.1,
                win_rate_pct=33.3,
                recommendation="Reduce exposure to this bucket",
                rationale="Average return is negative and win rate is weak in this sample.",
            ),
        ],
    )


if __name__ == "__main__":
    raise SystemExit(main())
