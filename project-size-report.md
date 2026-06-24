# Momentum Hunter Project Size Report

Generated from local filesystem scan of `C:\Users\steve\OneDrive\Documents\Investing`.

This report measures file count and disk footprint. It does not run tests and does not evaluate code behavior.

## Summary

| Area | Files | Size |
| --- | ---: | ---: |
| Full workspace, including `.venv` and `.git` | 12,102 | 740.5 MB |
| Core project, excluding `.venv`, `.git`, and caches | 613 | 17.9 MB |
| Application source: `momentum_hunter` | 48 | 857.4 KB |
| Tests: `tests` | 41 | 363.9 KB |
| Documentation: `README.md` and `docs` | 10 | 603.0 KB |
| Tools: `tools` | 9 | 34.2 KB |
| Runtime data: `MomentumHunterData` | 334 | 15.9 MB |
| Virtual environment: `.venv` | 4,690 | 489.3 MB |
| Git repository metadata: `.git` | 6,704 | 231.7 MB |

## Top-Level Size Breakdown

### Including Dependencies And Git

| Path | Size |
| --- | ---: |
| `.venv` | 489.3 MB |
| `.git` | 231.7 MB |
| `MomentumHunterData` | 15.9 MB |
| `momentum_hunter` | 1.9 MB |
| `tests` | 893.9 KB |
| `docs` | 570.8 KB |
| `assets` | 119.1 KB |
| `tools` | 72.8 KB |
| `README.md` | 32.1 KB |
| `.tmp` | 24.0 KB |

### Core Project Only

| Path | Size |
| --- | ---: |
| `MomentumHunterData` | 15.9 MB |
| `momentum_hunter` | 857.4 KB |
| `docs` | 570.8 KB |
| `tests` | 363.9 KB |
| `assets` | 119.1 KB |
| `tools` | 34.2 KB |
| `README.md` | 32.1 KB |
| `.tmp` | 24.0 KB |
| `project-stats-report.md` | 9.7 KB |
| `config` | 2.4 KB |

## Runtime Data Breakdown

| Runtime Data Item | Files | Size |
| --- | ---: | ---: |
| `MomentumHunterData\data\score-breakdowns.json` | 1 | 8.3 MB |
| `MomentumHunterData\data\backups` | 81 | 2.4 MB |
| `MomentumHunterData\data\captures` | 60 | 2.2 MB |
| `MomentumHunterData\data\integrity` | 29 | 1.1 MB |
| `MomentumHunterData\data\reports` | 86 | 908.9 KB |
| `MomentumHunterData\data\analysis-captures.csv` | 1 | 242.0 KB |
| `MomentumHunterData\data\analysis-outcomes.csv` | 1 | 202.0 KB |
| `MomentumHunterData\data\opportunity-minute-bars.json` | 1 | 195.8 KB |
| `MomentumHunterData\data\news-freshness-audit.csv` | 1 | 124.1 KB |
| `MomentumHunterData\data\quarantine` | 18 | 88.2 KB |
| `MomentumHunterData\data\watchlist-2026-06-04.json` | 1 | 15.9 KB |
| `MomentumHunterData\data\watchlist-2026-06-18.json` | 1 | 14.2 KB |
| `MomentumHunterData\data\opportunity-price-observations.json` | 1 | 11.1 KB |
| `MomentumHunterData\data\entry-plans.json` | 1 | 9.9 KB |
| `MomentumHunterData\data\opportunity-monitor-state.json` | 1 | 7.0 KB |

## Largest Project Files

Excludes `.venv`, `.git`, Python caches, and test caches.

| File | Size |
| --- | ---: |
| `MomentumHunterData\data\score-breakdowns.json` | 8.3 MB |
| `MomentumHunterData\data\backups\score-breakdowns\20260607-113002\score-breakdowns.json` | 1.2 MB |
| `momentum_hunter\app.py` | 247.4 KB |
| `MomentumHunterData\data\analysis-captures.csv` | 242.0 KB |
| `MomentumHunterData\data\analysis-outcomes.csv` | 202.0 KB |
| `MomentumHunterData\data\opportunity-minute-bars.json` | 195.8 KB |
| `MomentumHunterData\data\integrity\headline_dedup_v1.png` | 175.6 KB |
| `docs\screenshots\momentum_hunter_historical_snapshot.png` | 138.8 KB |
| `docs\screenshots\momentum_hunter_current_dashboard.png` | 137.7 KB |
| `MomentumHunterData\data\backups\derived-rebuild\20260606-163706\analysis-captures.csv` | 132.9 KB |
| `MomentumHunterData\data\integrity\catalyst_clusters_v1.png` | 124.9 KB |
| `MomentumHunterData\data\news-freshness-audit.csv` | 124.1 KB |
| `assets\momentum_hunter_logo.jpg` | 119.1 KB |
| `MomentumHunterData\data\integrity\catalyst_cluster_v2.png` | 117.8 KB |
| `MomentumHunterData\data\integrity\market_calendar_dashboard_screenshot.png` | 101.1 KB |
| `MomentumHunterData\data\captures\2026-06-15\evening.json` | 94.0 KB |
| `MomentumHunterData\data\captures\2026-06-16\morning.json` | 94.0 KB |
| `MomentumHunterData\data\captures\2026-06-16\evening.json` | 94.0 KB |
| `MomentumHunterData\data\captures\2026-06-15\morning.json` | 93.9 KB |
| `MomentumHunterData\data\captures\2026-06-11\evening.json` | 90.4 KB |

## Observations

- The actual application code is still small: under 1 MB for `momentum_hunter`.
- The full workspace is dominated by the virtual environment and Git metadata, together about 721 MB.
- Runtime data is currently 15.9 MB, with score breakdown history accounting for more than half of that.
- The largest source file is `momentum_hunter\app.py`, which is the main UI/workflow concentration point.
- Existing runtime data growth is reasonable, but `score-breakdowns.json` is the first file to watch if the app starts feeling sluggish.

## Test Status

No tests were run for this report. This was a filesystem-size scan only.
