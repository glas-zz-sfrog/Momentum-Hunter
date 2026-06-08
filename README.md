# Momentum Hunter

Momentum Hunter is a Windows-first Python desktop research assistant for finding momentum stocks for swing trading and short-term watchlists.

It is not an automated trading bot. It does not place orders. The human trader makes the final decision.

## Current Version

Version 0.1 implements the V1/V3 foundation:

- PySide6 desktop GUI
- PAPER/LIVE mode switch with no trading execution
- Base Momentum and Institutional Momentum scanner presets
- Swappable data-provider architecture
- Sample provider for offline use
- Finviz provider scaffold for screener/news parsing
- Candidate table with ticker, price, change, volume, relative volume, market cap, sector, and industry
- News and catalyst panel
- Deterministic scoring engine
- Candidate notes
- Save selected candidates to a next-session watchlist JSON file
- All displayed times use Central Time
- Market-calendar-aware morning/evening/preopen capture files for point-in-time review
- Structured capture JSON plus a flat analysis CSV for future scoring review
- Market regime label for each capture
- Automatic Windows startup launcher

## Install

Use Python 3.12 on Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```powershell
.\tools\launch_momentum_hunter.ps1
```

The launcher uses `pythonw.exe` when available, so the desktop app opens without a lingering console window. The app starts with the `sample` provider so you can verify the workflow without internet access.

## Data Files

Configuration and watchlists are stored under the project folder:

```text
MomentumHunterData
```

Watchlists are saved as:

```text
MomentumHunterData\data\watchlist-YYYY-MM-DD.json
```

Daily captures are stored as:

```text
MomentumHunterData\data\captures\YYYY-MM-DD\morning.json
MomentumHunterData\data\captures\YYYY-MM-DD\morning.md
MomentumHunterData\data\captures\YYYY-MM-DD\evening.json
MomentumHunterData\data\captures\YYYY-MM-DD\evening.md
MomentumHunterData\data\captures\YYYY-MM-DD\preopen.json
MomentumHunterData\data\captures\YYYY-MM-DD\preopen.md
```

The analysis table is stored as:

```text
MomentumHunterData\data\analysis-captures.csv
```

Forward outcome tracking is stored as:

```text
MomentumHunterData\data\analysis-outcomes.csv
```

Outcome fields include:

- `next_day_return_pct`
- `five_day_return_pct`
- `max_gain_pct`
- `max_drawdown_pct`
- `outcome_status`

Rows remain `pending_next_day` or `pending_five_day` until enough future daily price bars exist. Scheduled capture jobs run the outcome updater after each successful capture.

The Study Engine includes score-weight recommendations once enough completed 5-day outcomes exist. Recommendations are advisory only; Momentum Hunter does not automatically rewrite `config\scoring_profiles.json`.

## Daily Capture Workflow

1. Run the scanner during the morning or evening review window.
2. Review candidates and check the rows you want to track.
3. Click `Add Selected` to stage the picks.
4. Set or refresh the market regime.
5. Momentum Hunter auto-captures market-calendar-approved morning, evening, and preopen snapshots while the app is running.
6. Use the date and session selectors to reopen a past morning, evening, preopen, or manual capture.

Momentum Hunter installs a Windows startup launcher automatically so the app is available for scheduled captures after login.
The startup launcher is written as `Momentum Hunter.vbs` and launches the GUI hidden through `pythonw.exe`, avoiding a visible command window.

## Scheduled Capture Jobs

Momentum Hunter also includes a headless capture job for Windows Task Scheduler:

```powershell
.\.venv\Scripts\python.exe tools\capture_job.py --session morning
.\.venv\Scripts\python.exe tools\capture_job.py --session evening
```

The Windows tasks may fire daily, but the shared scheduling policy decides whether to capture or skip. The target exchange calendar is `XNYS` using `market-calendar-v1`, a built-in NYSE/Nasdaq full-day calendar covering weekends and standard full-day exchange holidays. Early closes are not modeled yet.

Policy behavior:

- Morning captures run at 7:00 AM CT only on market-open days.
- Evening captures run at 7:00 PM CT after each market-open day, including Friday evening.
- Sunday 7:00 PM CT normally becomes a separate `preopen` capture before Monday trading.
- If Monday is a market holiday, Sunday evening skips and Monday 7:00 PM CT becomes `preopen` before Tuesday trading.
- Saturday, Sunday morning, ordinary holiday morning, and ordinary holiday evening runs skip with logged reasons such as `SKIP_NOT_MARKET_DAY`, `SKIP_NOT_PREOPEN_GAP_REVIEW_DAY`, or `SKIP_DUPLICATE_CAPTURE`.
- Manual captures remain allowed on any day and keep the `manual` session identity.

New captures and derived analysis rows include:

- `capture_session`
- `capture_calendar_status`
- `is_market_open_day`
- `is_study_eligible`
- `next_market_session_date`
- `scheduling_policy_version`

Study Engine excludes non-study-eligible captures by default. Use the `Include non-trading-day/preopen` option when researching weekend or holiday-gap behavior.

Install the daily scheduled tasks:

```powershell
.\tools\install_capture_tasks.ps1
```

By default, Windows runs these tasks under the current user. To configure Windows to run them whether the user is logged in or not, run the installer with:

```powershell
.\tools\install_capture_tasks.ps1 -RunWhetherLoggedOn
```

Run that command from an elevated PowerShell window. Windows may ask for your account credentials for that mode. That is a Task Scheduler requirement, not a Momentum Hunter requirement.

Scheduled capture logs are written to:

```text
MomentumHunterData\logs
```

## Data Freshness Safety

Freshness settings live here:

```text
config\ui_freshness_settings.json
```

Current thresholds:

- Fresh current data: `0-10` minutes old
- Aging current data: more than `10` minutes old
- Stale data: more than `20` minutes old

Momentum Hunter uses visible banners, timestamps, age text, read-only state, and table-header styling so current, stale, historical, and study data cannot be quietly confused.

## Scoring Profiles

Regime-aware scoring settings live here:

```text
config\scoring_profiles.json
```

The active profile is currently:

```text
regime-aware-v1
```

This profile preserves the original scoring structure, then applies small market-regime overlays:

- `bull`: slightly increases price-momentum and positive-catalyst points
- `neutral`: uses baseline weights
- `bear`: reduces price-momentum/catalyst points and increases risk-term penalties
- `unknown`: uses baseline weights

Each captured candidate records `score_profile` and `score_regime` for later study.

Score explanations are stored outside raw captures in:

```text
MomentumHunterData\data\score-breakdowns.json
```

Use the GUI `Why [score]?` button to inspect the component-by-component explanation for a candidate. Rebuild the derived explanation store with:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.rebuild_score_breakdowns
.\.venv\Scripts\python.exe -m momentum_hunter.score_breakdown_audit
```

The `Why [score]?` dialog has a compact summary and detailed component view. Compact rows group the score into Base, Volume, Relative Volume, Market Cap, Price Move, Catalyst, Freshness, and Risk/Penalty lines. Detailed rows show raw values, rules, contribution math, and reconciliation to the displayed score. In `momentum_score_v1`, Freshness is recorded as zero-point context so it is visible for research without changing current score behavior.

## Candidate Timeline and Replay Mode

Select a candidate and click `View Timeline` to see every trusted active capture containing that ticker. The timeline can sort oldest-first or newest-first and can optionally show quarantined captures with a warning.

Timeline rows show capture time, session, provider, scanner preset, score, score profile/version, market regime, review status, outcome status, score-breakdown status, and trust classification.

Replay Mode shows `preopen` rows as `Pre-Open Gap Review`. Ordinary historical weekend, holiday, and manual captures are hidden from timelines by default; enable `Show non-trading-day captures` to inspect them with a warning. Older raw files are not edited to add calendar fields.

Replay Mode opens a read-only point-in-time view for a timeline row labeled `POINT-IN-TIME REPLAY — READ ONLY`. It separates:

- capture-time facts from raw captures
- stored score explanations from `score-breakdowns.json`
- later user review decisions from `review-decisions.json`
- later outcome labels from `analysis-outcomes.csv`

Replay Mode never fetches current market data and does not recalculate historical scores with newer logic. Missing score explanations, legacy/incomplete breakdowns, missing outcome labels, and quarantined captures are shown as warnings.

## Historical Clusters

The Study Engine includes a `Historical Clusters` tab labeled `HISTORICAL CLUSTERS — RESEARCH ONLY`.

Historical clusters group stored candidates into deterministic themes such as earnings/guidance, analyst actions, AI infrastructure, healthcare/FDA/biotech, high-volume institutional momentum, sector sympathy, weak catalyst, and no clear catalyst.

Cluster generation reads active raw captures plus separate derived stores: `score-breakdowns.json`, `review-decisions.json`, and `analysis-outcomes.csv`. It does not fetch current market data, mutate raw captures, or recalculate historical scores with newer logic.

Cluster filters include date range, market regime, scanner preset, sector, minimum score, review status, and the study-eligible-only default. Small samples and missing outcome data are shown as warnings.

## Catalyst Cluster Explorer

The Study Engine includes a `Catalyst Explorer` tab labeled `CATALYST CLUSTERS — RESEARCH ONLY`.

Catalyst Cluster Explorer groups the actual historical headlines stored inside raw captures into deterministic catalyst buckets such as earnings beat, guidance raise, analyst actions, AI infrastructure, AI partnership, contract wins, FDA/biotech events, merger/acquisition, macro-only, weak/vague catalyst, no clear catalyst, and unknown/uncategorized.

The v2 explorer also splits more ambiguous stored headlines into additional deterministic buckets such as product/platform launch, capital markets/financing, legal/regulatory, leadership/strategic update, index/fund flow, and price-action/no-catalyst-detail. This reduces catch-all Sector Sympathy behavior without using AI.

The explorer reads active raw captures plus `score-breakdowns.json`, `review-decisions.json`, `analysis-outcomes.csv`, and catalyst age metrics computed from stored headlines. It does not fetch current market data, mutate raw captures, recalculate historical scores, start optimizer work, or treat post-capture outcomes as capture-time facts.

Timestamp handling is explicit: known article timestamps get capture-time article age, missing timestamps remain `UNKNOWN_TIMESTAMP`, and future timestamps are excluded from catalyst clustering with a warning.

Each catalyst cluster shows deterministic confidence, purity, explicit-rule count, fallback count, exact timestamp rate, unknown timestamp rate, future timestamp rate, representative headlines, and warnings such as `LOW CONFIDENCE CLUSTER`, `LOW PURITY CLUSTER`, `HIGH UNKNOWN TIMESTAMP RATE`, and `HIGH FUTURE TIMESTAMP RATE`.

The cluster detail view lists matching stored headlines, ticker, capture time, source, timestamp status, classification confidence, explicit rule used, fallback reason if applicable, headline age, freshness label, score, review status, outcome status, max gain/drawdown, and stored URL when available. A provider-quality research view summarizes exact, unknown, future, and invalid timestamp rates by provider, cluster, and ticker.

## Catalyst Date / Age Engine

The Study Engine includes a `Catalyst Age` tab labeled `CATALYST AGE / FRESHNESS — RESEARCH ONLY`.

Catalyst Age measures stored headline timestamps at capture time. It reports `EXACT_TIMESTAMP`, `DATE_ONLY`, `ESTIMATED`, `UNKNOWN_TIMESTAMP`, `FUTURE_TIMESTAMP`, and `INVALID_TIMESTAMP` without changing any candidate score.

Age buckets are context only: `<1h`, `1-4h`, `4-12h`, `12-24h`, `1-3d`, `3d+`, `unknown`, and `invalid_future`.

Future timestamps are not treated as fresh and are reported as warnings. Unknown timestamps remain unknown and do not receive HOT/FRESH treatment.

The tab includes an audit summary, cluster-by-age summary, ticker-level summary, and headline detail rows. Filters include date range, ticker, catalyst cluster, market regime, scanner preset, timestamp status, age bucket, and the study-eligible-only default.

## Headline Deduplication / Source Quality

The Study Engine includes a `Headline Dedup` tab labeled `HEADLINE DEDUP / SOURCE QUALITY — RESEARCH ONLY`.

Headline Dedup v1 groups stored historical headlines into deterministic catalyst events using normalized headline fingerprints. Normalization lowercases headlines, strips punctuation, removes source boilerplate, removes ticker prefixes where practical, collapses whitespace, and removes common filler words.

The report shows duplicate event summaries, source reliability, cluster dedup impact, and ticker dedup impact. Event rows include event ID, representative headline, tickers, sources, first/latest seen capture times, earliest known publication time, timestamp status summary, duplicate count, unique source count, catalyst cluster, confidence, notes, and warnings.

Source reliability reports exact timestamp percentage, unknown timestamp percentage, future timestamp percentage, invalid timestamp percentage, duplicate/syndicated rate, unique event count, and average headlines per event by provider/source. This is context only and does not affect Momentum Score, Opportunity Score, score profiles, or recommendations.

No `headline-events.json` file is written in v1. The report is rebuilt from active immutable raw captures and derived stores each time, and quarantined/non-study captures remain excluded by default.

## Outcome Explorer

The Study Engine includes an `Outcome Explorer` tab labeled `OUTCOME EXPLORER — POST-CAPTURE DATA`.

Outcome Explorer v1 compares stored candidate outcomes using only active raw captures and derived records such as `analysis-outcomes.csv`, `score-breakdowns.json`, `review-decisions.json`, catalyst clusters, catalyst age context, and headline dedup/source quality context. It does not fetch current market data, mutate raw captures, recalculate historical scores, alter scoring profiles, or build Opportunity Score.

Summary metrics include candidate count, completed outcome count, pending outcome count, average and median next-day return, average and median five-day return, average max gain, average max drawdown, win rate, best winner, and worst loser. Pending outcomes are counted but are not treated as wins, losses, or completed-return observations.

Comparison tables show performance by score bucket, market regime, scanner, sector, review status, catalyst cluster, catalyst age bucket, and cluster purity bucket. Candidate rows clearly mark outcome values as post-capture labels from `analysis-outcomes.csv`, not information known at capture time.

Outcome Explorer excludes quarantined captures and non-study-eligible captures by default. Enable non-trading-day/preopen inclusion only when deliberately researching those observations.

## Opportunity Research

The Study Engine includes an `Opportunity Research` tab labeled `OPPORTUNITY RESEARCH — RESEARCH ONLY`.

Opportunity Research v1 is a measurement framework for discovering which stored conditions appear predictive after enough outcomes mature. It uses active raw captures and derived context from `analysis-captures.csv`, `analysis-outcomes.csv`, `score-breakdowns.json`, `review-decisions.json`, catalyst clusters, catalyst age metrics, and headline dedup/source reliability metrics.

It does not create Opportunity Score, optimize weights, change `momentum_score_v1`, alter `scoring_profiles.json`, fetch current market data, mutate raw captures, start broker integration, or start SQLite migration.

The tab groups post-capture outcomes by score bucket, market regime, scanner, sector, industry, catalyst cluster, catalyst confidence, cluster purity, catalyst age bucket, review status, source reliability bucket, duplicate-rate bucket, and selected combinations. Ranking tables show best performing, worst performing, most pending, highest max gain, and highest drawdown conditions.

If completed outcomes are too low, the UI says `Insufficient completed outcomes for conclusions.` Pending outcomes are counted but are never treated as wins, losses, or completed-return observations.

## Legacy Capture Cleanup

If a non-market-day `morning` or `evening` raw capture is accidentally created beside a valid `preopen` capture, use the cleanup command to quarantine the unwanted raw files and rebuild/prune derived CSV rows without editing raw captures:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.cleanup_legacy_captures 2026-06-07 --sessions morning evening
```

The command backs up `analysis-captures.csv` and `analysis-outcomes.csv`, quarantines matching legacy/non-study captures, preserves valid active captures such as `preopen`, rebuilds analysis rows from active raw captures, and prunes outcome rows to active analysis identities.

## Administrator Actions

Normal dashboard use does not require Administrator rights.

Administrator rights are useful for one-time system setup:

- Installing or repairing scheduled capture tasks
- Configuring scheduled tasks to run whether the user is logged in or not
- Running scheduled capture tasks with highest privileges

Rollback scheduled capture tasks:

```powershell
Unregister-ScheduledTask -TaskName "Momentum Hunter Morning Capture" -Confirm:$false
Unregister-ScheduledTask -TaskName "Momentum Hunter Evening Capture" -Confirm:$false
```

Rollback Windows startup launcher:

```powershell
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Momentum Hunter.vbs"
```

## Scanner Presets

Base Momentum:

- Volume: 1,000,000
- Percent Change: 5%
- Market Cap: $1B
- Price: $5
- Relative Volume: 150%

Institutional Momentum:

- Volume: 3,000,000
- Percent Change: 3%
- Market Cap: $5B
- Price: $10
- Relative Volume: 120%

## Trading Safety

Momentum Hunter is a research tool only.

- No automatic trading
- No order placement
- No broker credentials
- No destructive actions
- One active mode at a time
- LIVE mode is reserved for future broker-connected research workflows

## Roadmap

Planned V2 fields:

- Float
- Short Float
- Short Interest
- Premarket Volume
- Gap %
- Earnings Date
- ATR
- Relative Strength

Planned future integrations:

- Yahoo Finance
- Schwab
- Thinkorswim
- Analyst action feeds
- Earnings providers
