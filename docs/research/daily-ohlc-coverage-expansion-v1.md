# Daily OHLC Coverage Expansion v1

This slice expands the research-only daily OHLC cache used by Technical Breakout Research Engine v1. It preserves file-based fallback behavior, keeps generated cache/report files ignored, and does not change scoring, readiness, alerts, scanner behavior, trade planning, outcomes, broker behavior, or UI workflows.

## Symbol Source Categories

The requested daily OHLC universe is built from local evidence only:

| Category | Meaning | Priority |
| --- | --- | ---: |
| `alert_symbols` | Symbols present in `opportunity-alerts.json`. | 1 |
| `outcome_symbols` | Symbols present in `analysis-outcomes.csv`. | 1 |
| `current_watchlist` | Latest watchlist file plus review decisions marked watchlist. | 1 |
| `entry_plan_symbols` | Symbols with entry-plan records. | 1 |
| `active_monitor_targets` | Symbols in the latest active monitor target report. | 1 |
| `recent_high_score_capture_symbols` | Capture rows with score at or above 85. | 2 |
| `candidate_story_symbols` | Symbols with repeated captures supporting Candidate Story context. | 2 |
| `repeated_capture_candidates` | Symbols seen in at least two capture rows. | 2 |
| `reviewed_candidates` | Reviewed non-watchlist candidate symbols. | 2 |
| `research_candidates` | Broader capture and score-breakdown symbols. | 3 |
| `recent_captures` | Capture symbols seen near the latest capture date. | 3 |
| `broad_market_baseline` | `QQQ` and `SPY`. | baseline |
| `sector_etf_baseline` | `SMH` and `SOXX`. | baseline |

## Priority Order

1. Alerts, outcomes, watchlist, entry plans, and active monitor targets.
2. Recent high-score captures, Candidate Story symbols, repeated captures, and reviewed candidates.
3. Broader research candidates and recent captures.
4. Baselines are always included: `QQQ`, `SPY`, `SMH`, and `SOXX`.

Because `analysis-outcomes.csv` currently contains records for almost every capture symbol, most research symbols are classified as Priority 1.

## Coverage Target

The expansion plan requested 263 symbols:

- Baseline symbols: 4
- Priority 1 symbols: 227
- Priority 2 symbols: 0
- Priority 3 symbols: 32

The generated breakout report requested 226 symbols from its narrower evidence path and all 226 are now covered.

## Provider And Fetch Constraints

The fetch/cache expansion uses Yahoo chart-derived daily bars through the existing provider pattern. Fetching is explicit; default loading remains local and read-only.

Safeguards:

- per-symbol fetch isolation
- retry limit
- delay between symbols
- invalid OHLC rejection
- no fabricated bars
- source and timestamp preserved
- one failed symbol does not fail the run
- cache remains generated data and is not tracked by Git

## Cache And Update Strategy

The local cache is:

`MomentumHunterData/data/daily-ohlc-bars.json`

Cache behavior:

- additive merge by symbol/date
- existing valid records are preserved
- new valid records replace matching symbol/date rows
- invalid records are rejected from the cache
- coverage reports list missing, failed, invalid, and insufficient-history symbols

The cache is a research input, not a source of truth for scanner, scoring, readiness, or trade planning.

## Data Quality Risks

- Provider availability can change or rate-limit.
- Some symbols have short trading histories, producing insufficient-history warnings.
- Yahoo adjusted OHLC normalization is consistent for research math but may differ from raw chart levels.
- Delisted, renamed, or very new tickers may fail or produce sparse results.
- Sector ETF coverage is baseline-only; no full sector mapping is promoted in this slice.

## No-Trade-Recommendation Guardrails

Reports may describe coverage, breakout presence, insufficient data, failed events, and study outcomes.

Reports must not say:

- buy
- sell
- guaranteed edge
- strategy should change
- approved trade

This is evidence infrastructure only.
