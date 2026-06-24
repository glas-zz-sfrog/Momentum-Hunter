# Momentum Hunter Project Statistics Report

Static source analysis only. No test suite was run for this report.

Scope counted:

- Application Python: `momentum_hunter/**/*.py`
- Test Python: `tests/**/*.py`
- Documentation: `README.md` and `docs/*.md`
- Excluded: generated captures/reports/data, `.venv`, caches, Git metadata, images, CSV/JSON runtime artifacts

## Summary Table

| Metric | Count |
| --- | ---: |
| Application Python files | 48 |
| Test files | 41 |
| Documentation files | 5 |
| Application Python lines | 21,506 |
| Test code lines | 8,354 |
| Documentation lines | 1,862 |
| Total counted project lines | 31,722 |
| Discovered test case classes | 43 |
| Discovered test cases | 237 |
| Passing tests | Not run in this line-count report |

## Code Statistics

| Area | Files | Lines |
| --- | ---: | ---: |
| Application Python | 48 | 21,506 |
| Tests | 41 | 8,354 |
| Documentation | 5 | 1,862 |
| Total | 94 | 31,722 |

## Feature Statistics

| Feature Area | Associated Lines |
| --- | ---: |
| Dashboard/UI | 5,896 |
| Trade Planning | 1,848 |
| Outcome Tracking | 1,784 |
| Active Monitor | 1,584 |
| Alert Engine | 1,163 |
| Tests | 8,354 |
| Provider Health | 706 |

Notes:

- Feature counts are file-based approximations, not AST-level slicing.
- Dashboard/UI includes `momentum_hunter/app.py` and `momentum_hunter/ui/data_view_state.py`.
- Outcome Tracking includes outcomes, outcome explorer, outcome maturity, opportunity research, and alert outcome updater modules.
- Provider Health includes provider support plus market tape health diagnostics.

## Module Breakdown

| Module | Lines | Purpose |
| --- | ---: | --- |
| `momentum_hunter/__init__.py` | 3 | Package marker. |
| `momentum_hunter/active_monitor.py` | 907 | Runs active monitor cycles, refreshes target tape, creates coverage rows, and exports monitor artifacts. |
| `momentum_hunter/active_monitor_runner.py` | 253 | Starts/stops background active-monitor loop processes and tracks runner state. |
| `momentum_hunter/alert_outcome_updater.py` | 494 | Fetches minute bars and updates opportunity-alert outcomes. |
| `momentum_hunter/app.py` | 5,556 | Main PySide6 desktop UI and dashboard workflows. |
| `momentum_hunter/capture_health.py` | 168 | Summarizes capture health, failures, and latest capture status. |
| `momentum_hunter/catalyst_age.py` | 363 | Measures headline timestamp age and catalyst-age audit views. |
| `momentum_hunter/catalyst_clusters.py` | 717 | Deterministic catalyst clustering, confidence, purity, and provider-quality metrics. |
| `momentum_hunter/cleanup_legacy_captures.py` | 227 | Handles cleanup/quarantine of legacy non-study captures. |
| `momentum_hunter/config.py` | 50 | Application paths and directory setup. |
| `momentum_hunter/daily_workflow.py` | 211 | Daily checklist counts, workflow score, and operational warnings. |
| `momentum_hunter/entry_plans.py` | 155 | Stores and validates watchlist entry plans. |
| `momentum_hunter/headline_events.py` | 431 | Headline deduplication, event grouping, and source reliability metrics. |
| `momentum_hunter/historical_clusters.py` | 665 | Historical candidate clustering and setup/theme summaries. |
| `momentum_hunter/integrity.py` | 643 | Raw capture manifest, hashing, integrity audit, and derived record checks. |
| `momentum_hunter/integrity_audit.py` | 33 | CLI wrapper for integrity audit. |
| `momentum_hunter/market.py` | 87 | Market regime and market data helper logic. |
| `momentum_hunter/market_tape_health.py` | 351 | Market-tape provider health CLI and reports. |
| `momentum_hunter/models.py` | 116 | Core dataclasses shared across scanner/storage workflows. |
| `momentum_hunter/monitor_targets.py` | 424 | Builds active monitor target universe from watchlist, interested, entry plans, and user symbols. |
| `momentum_hunter/news_age.py` | 222 | News freshness, timestamp status, and freshness audit utilities. |
| `momentum_hunter/operator_review.py` | 173 | Operator review context and permission-state logic. |
| `momentum_hunter/opportunity_alerts.py` | 1,163 | Opportunity alert detection, state transitions, observations, outcomes, and alert reports. |
| `momentum_hunter/opportunity_research.py` | 276 | Research-only opportunity condition analysis. |
| `momentum_hunter/outcome_explorer.py` | 518 | Outcome Explorer filters, summaries, and comparison tables. |
| `momentum_hunter/outcome_maturity.py` | 254 | Readiness gates for research maturity and future optimization locks. |
| `momentum_hunter/outcomes.py` | 242 | Derived outcome calculations, daily bars, and shared market-data HTTP session. |
| `momentum_hunter/providers.py` | 355 | Finviz provider, retry/error handling, and scanner data access. |
| `momentum_hunter/quarantine.py` | 418 | Raw capture quarantine and recovery policy. |
| `momentum_hunter/quarantine_capture.py` | 25 | CLI wrapper for capture quarantine. |
| `momentum_hunter/rebuild_derived.py` | 283 | Rebuilds derived analysis CSV rows from immutable captures. |
| `momentum_hunter/rebuild_derived_data.py` | 33 | CLI wrapper for derived rebuilds. |
| `momentum_hunter/rebuild_score_breakdowns.py` | 28 | CLI wrapper for score-breakdown rebuilds. |
| `momentum_hunter/recommendations.py` | 142 | Locked research-note/readiness recommendation support. |
| `momentum_hunter/recover_modified_captures.py` | 225 | Recovery command for modified raw captures. |
| `momentum_hunter/replay.py` | 358 | Point-in-time candidate timeline and replay support. |
| `momentum_hunter/review.py` | 194 | Review decisions and candidate status persistence. |
| `momentum_hunter/scheduling.py` | 419 | Market-calendar-aware capture scheduling policy. |
| `momentum_hunter/score_breakdown_audit.py` | 31 | CLI wrapper for score-breakdown audit. |
| `momentum_hunter/score_breakdowns.py` | 364 | Score explanation generation and derived score-breakdown store. |
| `momentum_hunter/scoring.py` | 532 | Momentum score rules, profiles, and score components. |
| `momentum_hunter/startup.py` | 52 | Startup helper behavior. |
| `momentum_hunter/storage.py` | 781 | Capture/watchlist/report storage and serialization helpers. |
| `momentum_hunter/study.py` | 343 | Study summary calculations and filters. |
| `momentum_hunter/time_utils.py` | 30 | Central Time utility helpers. |
| `momentum_hunter/trade_planning.py` | 1,848 | Trade plan generation, RVOL audit fields, readiness state, and event reports. |
| `momentum_hunter/ui/__init__.py` | 3 | UI package marker. |
| `momentum_hunter/ui/data_view_state.py` | 340 | Current/stale/historical/replay data-view state handling. |

## Largest Files

| Rank | File | Lines |
| ---: | --- | ---: |
| 1 | `momentum_hunter/app.py` | 5,556 |
| 2 | `momentum_hunter/trade_planning.py` | 1,848 |
| 3 | `momentum_hunter/opportunity_alerts.py` | 1,163 |
| 4 | `momentum_hunter/active_monitor.py` | 907 |
| 5 | `momentum_hunter/storage.py` | 781 |
| 6 | `momentum_hunter/catalyst_clusters.py` | 717 |
| 7 | `momentum_hunter/historical_clusters.py` | 665 |
| 8 | `momentum_hunter/integrity.py` | 643 |
| 9 | `README.md` | 551 |
| 10 | `momentum_hunter/scoring.py` | 532 |
| 11 | `docs/storage-map.md` | 531 |
| 12 | `momentum_hunter/outcome_explorer.py` | 518 |
| 13 | `tests/test_trade_planning.py` | 516 |
| 14 | `momentum_hunter/alert_outcome_updater.py` | 494 |
| 15 | `momentum_hunter/headline_events.py` | 431 |
| 16 | `momentum_hunter/monitor_targets.py` | 424 |
| 17 | `momentum_hunter/scheduling.py` | 419 |
| 18 | `momentum_hunter/quarantine.py` | 418 |
| 19 | `tests/test_catalyst_clusters.py` | 418 |
| 20 | `tests/test_historical_clusters.py` | 410 |

## Test File Breakdown

| Test File | Lines |
| --- | ---: |
| `tests/test_active_monitor.py` | 337 |
| `tests/test_active_monitor_dashboard.py` | 153 |
| `tests/test_active_monitor_runner.py` | 120 |
| `tests/test_alert_outcome_updater.py` | 157 |
| `tests/test_branding.py` | 39 |
| `tests/test_capture_health.py` | 86 |
| `tests/test_catalyst_age.py` | 238 |
| `tests/test_catalyst_clusters.py` | 418 |
| `tests/test_daily_workflow.py` | 281 |
| `tests/test_data_view_state.py` | 109 |
| `tests/test_entry_plans.py` | 247 |
| `tests/test_gui_states.py` | 279 |
| `tests/test_headline_events.py` | 170 |
| `tests/test_historical_clusters.py` | 410 |
| `tests/test_legacy_capture_cleanup.py` | 213 |
| `tests/test_market_tape_health.py` | 172 |
| `tests/test_monitor_targets.py` | 210 |
| `tests/test_morning_review_workspace.py` | 196 |
| `tests/test_news_age.py` | 161 |
| `tests/test_news_freshness_audit.py` | 57 |
| `tests/test_news_links.py` | 53 |
| `tests/test_operator_review.py` | 68 |
| `tests/test_opportunity_alerts.py` | 393 |
| `tests/test_opportunity_research.py` | 130 |
| `tests/test_outcome_explorer.py` | 221 |
| `tests/test_outcome_maturity.py` | 158 |
| `tests/test_outcomes.py` | 39 |
| `tests/test_provider_errors.py` | 34 |
| `tests/test_quarantine.py` | 330 |
| `tests/test_raw_capture_integrity.py` | 344 |
| `tests/test_rebuild_derived.py` | 211 |
| `tests/test_recommendations.py` | 53 |
| `tests/test_replay.py` | 400 |
| `tests/test_review_workflow.py` | 379 |
| `tests/test_scheduling_policy.py` | 172 |
| `tests/test_score_breakdowns.py` | 327 |
| `tests/test_scoring.py` | 76 |
| `tests/test_startup.py` | 47 |
| `tests/test_storage.py` | 154 |
| `tests/test_study.py` | 196 |
| `tests/test_trade_planning.py` | 516 |

## Testing Statistics

| Metric | Count |
| --- | ---: |
| Test files | 41 |
| Test code lines | 8,354 |
| Discovered test case classes | 43 |
| Discovered test cases | 237 |
| Passing tests | Not run in this static line-count report |

## Notes

- This report intentionally does not execute tests.
- The earlier full test run was stopped and is not used in this report.
- Line counts are physical lines, including blanks and comments.
- Feature statistics are approximate because some large modules, especially `app.py`, contain multiple workflows in one file.
