# Daily OHLC Coverage Expansion Final Report

## Summary

Breakout Research Integration & Daily OHLC Coverage Expansion v1 merged the existing local breakout research work into `master`, built a prioritized daily OHLC symbol universe, expanded the generated daily OHLC cache, and regenerated breakout research reports against broader daily coverage.

This remains research infrastructure only. No scoring, readiness, alert, scanner, trade-planning, outcome-classification, broker, automated trading, UI workflow, or raw capture behavior changed.

## Branches Merged

- `codex/technical-breakout-research-engine-v1`
- `codex/daily-ohlc-source-for-breakout-research-v1`

## Commits Integrated

- `4d63655 Add technical breakout research engine`
- `1180315 Add daily OHLC source for breakout research`

Local `master` was fast-forwarded to `1180315` before this coverage-expansion branch was created.

## Coverage Expansion

Before expansion:

- Requested symbols: 226
- Covered symbols: 2
- Missing symbols: 224
- Covered tickers: `CRWV`, `QQQ`

After expansion:

- Full coverage plan symbols: 263
- Full coverage plan covered symbols: 263
- Breakout-requested symbols: 226
- Breakout-requested covered symbols: 226
- Coverage percentage for breakout-requested symbols: 100.0%
- Valid daily OHLC records: 79,298
- Invalid daily OHLC records: 0
- Failed symbols: 0
- Insufficient-history symbols: 5
- Earliest date: 2025-04-01
- Latest date: 2026-07-02

Generated reports:

- `MomentumHunterData/data/reports/daily-ohlc-coverage-plan-latest.json`
- `MomentumHunterData/data/reports/daily-ohlc-coverage-plan-latest.md`
- `MomentumHunterData/data/reports/daily-ohlc-coverage-latest.json`
- `MomentumHunterData/data/reports/daily-ohlc-coverage-latest.md`
- `MomentumHunterData/data/reports/technical-breakout-events-latest.json`
- `MomentumHunterData/data/reports/technical-breakout-events-latest.md`
- `MomentumHunterData/data/reports/technical-breakout-study-latest.json`
- `MomentumHunterData/data/reports/technical-breakout-study-latest.md`

Generated cache/report files remain ignored and untracked.

## Breakout Report Effect

Regenerated breakout events:

- Total records: 23,860
- Breakout present: 23,857
- Insufficient data: 3
- Donchian 20-day breakouts: 3,892
- Donchian 30-day breakouts: 3,173
- Donchian 50-day breakouts: 2,432
- Bollinger upper-band breakouts: 3,588
- ATR/Keltner breakouts: 3,624
- Price cross above 20-day SMA: 4,215
- Price cross above 50-day SMA: 2,224
- 20-day SMA cross above 50-day SMA: 669

Regenerated event study:

- Study rows: 23,857
- Failed back below breakout level: 22,166
- Held above breakout level: 1,573
- Became extended: 13,851
- Insufficient data: 118

The report remains descriptive and research-only; it does not convert breakouts into recommendations.

## Tests Run

Phase 0 merge-readiness tests:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_daily_ohlc tests.test_technical_breakouts -v
.\.venv\Scripts\python.exe -B -m unittest tests.test_alert_outcome_updater tests.test_evidence_census -v
```

Coverage-expansion focused tests:

```powershell
.\.venv\Scripts\python.exe -B -m unittest tests.test_daily_ohlc -v
```

Pass results before final broad verification:

- `tests.test_daily_ohlc`: 10 passed
- `tests.test_technical_breakouts`: 15 passed
- `tests.test_alert_outcome_updater`: 6 passed in Phase 0
- `tests.test_evidence_census`: 3 passed in Phase 0

Final combined verification:

- `tests.test_daily_ohlc tests.test_technical_breakouts`: 25 passed
- `tests.test_alert_outcome_updater tests.test_evidence_census`: 9 passed

## Remaining Coverage Gaps

- 5 symbols have insufficient daily history for the full long-window study.
- Provider data remains a generated research cache, not an authoritative market data system.
- Sector ETF mapping remains baseline-only with `SMH` and `SOXX`; no full sector map was promoted.

## Recommended Next Research Slice

Add a read-only breakout-summary analytics report that aggregates daily breakout families by source category, sector, history sufficiency, and forward-return buckets. Keep it descriptive and do not feed it into scoring or alert thresholds.

## Final State Notes

- Current branch: `codex/daily-ohlc-coverage-expansion-v1`
- Generated files ignored: yes
- Protected areas unchanged: yes
- Push status: not pushed
- Merge status: existing branches merged locally into `master`; this coverage-expansion branch not merged yet
- Worktree status and final commit hash are recorded in the chat final response after verification and commit.
