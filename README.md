# Momentum Hunter

Momentum Hunter is a Windows-first Python desktop research assistant for finding momentum stocks for swing trading and short-term watchlists.

It is not an automated trading bot. It does not place orders. The human trader makes the final decision.

## Current Version

Version 0.1 implements the V1/V3 foundation:

- PySide6 desktop GUI
- PAPER/LIVE mode switch with no trading execution
- Basic Momentum and Heavy Volume Momentum scanner presets
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

Entry plans for watchlist candidates are stored separately as:

```text
MomentumHunterData\data\entry-plans.json
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
- `expected_next_day_session_date`
- `expected_five_day_session_date`
- `next_day_outcome_state`
- `five_day_outcome_state`
- `outcome_reason`
- `outcome_calculation_version`
- `outcome_status`

Outcome states distinguish `pending_not_mature`, `complete`, `provider_data_missing`, `calculation_failed`, `ineligible_capture`, and `calendar_mapping_error`. Market holidays and weekends are handled by expected market-session dates; for example, a June 18, 2026 capture uses June 22, 2026 as the next outcome session because June 19 was Juneteenth.

## Reliability Reports

Momentum Hunter includes read-only reliability reports for checking whether the system can be trusted before review or evidence analysis.

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.data_quality
.\.venv\Scripts\python.exe -m momentum_hunter.evidence_autopilot_reliability
.\.venv\Scripts\python.exe -m momentum_hunter.system_readiness
```

These write:

```text
MomentumHunterData\data\reports\data-quality-latest.json
MomentumHunterData\data\reports\data-quality-latest.md
MomentumHunterData\data\reports\evidence-autopilot-latest.json
MomentumHunterData\data\reports\evidence-autopilot-latest.md
MomentumHunterData\data\reports\system-readiness-latest.json
MomentumHunterData\data\reports\system-readiness-latest.md
```

These reports are diagnostic only. They do not change scanner logic, scoring, readiness states, alert thresholds, trade-planning rules, raw captures, broker behavior, or automated trading behavior.

## SQLite Foundation

Momentum Hunter has an additive SQLite foundation for future storage migration work. It does not replace the current JSON/CSV files yet.

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.sqlite_migration
```

This initializes:

```text
MomentumHunterData\data\momentum-hunter.sqlite3
```

The first low-risk vertical slice imports provider/data-quality report rows into `provider_quality_checks`. Existing report files remain the current operator-facing artifacts.

## Watchlist Discipline

When a current/live candidate is moved to Watchlist, Momentum Hunter can store an entry plan with trigger, stop, thesis, invalidation, max loss, position size idea, planned hold time, and notes. Incomplete plans show warnings for missing trigger, stop, invalidation, and max loss.

Entry plans are planning/journaling records only. Momentum Hunter does not place orders, route trades, or connect to a broker. Historical, Replay, Research Lab, expired, and quarantined views are read-only for entry plans.

## Operator Review Validity

Momentum Hunter separates market-data freshness from operator-review validity. A 7:00 PM CT evening or preopen capture may be older than the freshness threshold when you review it later that night, but it remains reviewable until 8:30 AM CT on the next market session date.

Review decisions, watchlist creation, entry plans, and watchlist report generation are allowed for `Ready for Next Session Review`, `Aging but Reviewable`, and `Current Manual Scan` contexts. Aged reviewable snapshots keep strong warnings visible; generating a watchlist report from aged but valid data requires an acknowledgement.

Expired review snapshots, historical snapshots, Replay, Research Lab, quarantined captures, missing captures, and failed captures block the trading workflow. Delayed review metadata is stored with review decisions, not in immutable raw captures.

## Morning Review Workspace

Use `Morning Review` from the main toolbar for a focused review surface that combines the candidate table, review/watchlist status, score context, catalyst summary, headline freshness context, warning flags, and entry-plan editing in one workspace.

The selected candidate shows a compact Decision Card with ticker, score, catalyst summary, confidence/purity context, review status, plan status, and key warnings. Current/manual data and next-session evening/preopen review snapshots can be reviewed and edited; expired, historical, replay, research, and quarantined contexts are clearly warned and read-only.

Quick actions support marking a candidate Interested or Rejected, adding it to Watchlist, opening the stored score explanation, and opening Timeline/Replay. Entry plans remain stored in `entry-plans.json`; the Morning Review workspace does not mutate raw captures and does not place trades.

## Daily Workflow Checklist

Use `Daily Checklist` from the main toolbar to check whether the daily Momentum Hunter routine is actually complete. The checklist shows capture health, review counts, watchlist and entry-plan completeness, outcome maturity counts, readiness-gate statuses, warnings, and a workflow-discipline score.

The workflow score measures operational consistency only: candidate review completion, watchlist plan completion, capture success, and critical warning status. It does not evaluate trade quality, recommend trades, change scoring, or optimize weights.

Quick actions can open Morning Review, Generate Watchlist Report, Capture Health, and Readiness Gate. In expired, historical, replay, research, quarantined, missing, or failed contexts, edit/write actions remain disabled while read-only diagnostics stay available.

Rows remain `pending_next_day` or `pending_five_day` only while the expected market session has not matured. Once a horizon matures, the row is either populated, marked complete, or marked with a data-quality reason such as `provider_data_missing` or `calculation_failed`. Scheduled capture jobs run the outcome updater after each successful capture.

The Research Lab area includes `Locked Research Notes` once enough completed 5-day outcomes exist. These notes are diagnostic only; Momentum Hunter does not automatically rewrite `config\scoring_profiles.json`.

## Daily Review Workflow

1. Let the scheduled morning/evening/preopen capture run, or run the scanner manually.
2. Open `Daily Checklist` to see what is incomplete.
3. Open `Morning Review` to review candidates and mark them Interested, Rejected, or Watchlist.
4. Complete entry plans for watchlist candidates.
5. Click `Generate Watchlist Report`.
6. Use the date and session selectors to reopen a past morning, evening, preopen, or manual capture.

The broader roadmap and UI workflow audit is tracked in:

```text
docs\ROADMAP_AUDIT.md
```

Older raw captures remain available through snapshot/replay tools. Trading workflow is allowed only from current/manual scans and valid next-session review snapshots; historical/research views remain read-only.

## Automated Capture Workflow

1. Set or refresh the market regime when needed.
2. Keep Momentum Hunter and/or the scheduled capture tasks running.
3. Momentum Hunter auto-captures market-calendar-approved morning, evening, and preopen snapshots.
4. Check `Capture Health` or `Daily Checklist` for failures.

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

Research Study excludes non-study-eligible captures by default. Use the `Include non-trading-day/preopen` option when researching weekend or holiday-gap behavior.

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

Momentum Hunter uses visible banners, timestamps, age text, operator-review state, and table-header styling so current, aged-but-reviewable, expired, historical, and research data cannot be quietly confused.

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

## Candidate Story, Timeline, and Replay Mode

Select a candidate and click `Timeline / Replay` to open the graph-first Candidate Story for that ticker. The default `Trail` mode shows every trusted active capture containing that ticker as a stored-capture story: first seen, latest capture, first/latest price, move since first seen, score movement, peak score, trusted capture count, and a plain-language status such as Building, Holding, Fading, Peaked, Stale, or Insufficient data.

Candidate Story uses stored capture facts only. Its chart shows capture-sequence price and score points from raw captures; it does not fetch current market data, invent missing price points, or recalculate historical scores. Simplified story rows below the chart show month/day, session marker, price, move since previous/first capture, score change, relative volume, volume, capture notes, and clearly labeled later annotations.

`Intraday` and `5D` modes currently show explicit missing-data placeholders unless reliable stored data exists. `Audit` mode preserves the dense capture table as `Advanced Capture Audit`.

Advanced Capture Audit rows show capture time, session, provider, scanner preset, score, score profile/version, market regime, review status, outcome status, score-breakdown status, and trust classification. The timeline can sort oldest-first or newest-first and can optionally show quarantined captures with a warning.

Replay Mode shows `preopen` rows as `Pre-Open Gap Review`. Ordinary historical weekend, holiday, and manual captures are hidden from timelines by default; enable `Show non-trading-day captures` to inspect them with a warning. Older raw files are not edited to add calendar fields.

Replay Mode opens a read-only point-in-time view for a timeline row labeled `POINT-IN-TIME REPLAY — READ ONLY`. It separates:

- capture-time facts from raw captures
- stored score explanations from `score-breakdowns.json`
- later user review decisions from `review-decisions.json`
- later outcome labels from `analysis-outcomes.csv`

Replay Mode never fetches current market data and does not recalculate historical scores with newer logic. Missing score explanations, legacy/incomplete breakdowns, missing outcome labels, and quarantined captures are shown as warnings.

Replay details also show expected next-day and five-day outcome session dates, per-horizon outcome state, outcome reason, max gain/drawdown, and the outcome calculation version. These are later-derived labels and are never presented as information known at capture time.

Timeline and Replay views include a `Replay Audit Identity` strip so similar-looking captures can be verified before analysis. The strip shows the selected capture timestamp, capture ID, selected symbol, candidate row ID/fingerprint, outcome record ID, source file path, and last refresh time. If no Replay rows match the selected candidate or filters, the UI shows an explicit reason instead of silently falling back to another capture.

The left navigation rail includes `Back` so operators can return to the previous Momentum Hunter screen after jumping into Replay, Watchlist, Evidence, Research, or Health.

On the Replay page, `Open Historical Snapshot` loads the selected date/session into a read-only candidate table and detail pane. Selecting a candidate there drives `Open Timeline / Replay For Selected Candidate`, so the workflow no longer requires jumping back through the Dashboard just to inspect a historical capture.

## Historical Clusters

The Research Lab area includes a `Catalyst - Historical Setups` tab labeled `HISTORICAL CLUSTERS — RESEARCH ONLY`.

Historical clusters group stored candidates into deterministic themes such as earnings/guidance, analyst actions, AI infrastructure, healthcare/FDA/biotech, high-volume institutional momentum, sector sympathy, weak catalyst, and no clear catalyst.

Cluster generation reads active raw captures plus separate derived stores: `score-breakdowns.json`, `review-decisions.json`, and `analysis-outcomes.csv`. It does not fetch current market data, mutate raw captures, or recalculate historical scores with newer logic.

Historical Cluster Display v1 also includes a `Recurring Clusters` view for repeated ticker, sector, and scanner-preset appearances across trusted captures. Selecting a recurrence cluster shows the underlying historical appearances with ticker, Central Time capture timestamp, session, scanner, provider, score, review status, stored score-breakdown status, and later-derived outcome labels.

Individual historical appearances can be opened in the existing point-in-time Replay Mode. Replay remains read-only, uses stored capture facts and stored score explanations, and does not fetch current market data or recompute historical scores.

Cluster filters include date range, market regime, scanner preset, sector, minimum score, review status, and the study-eligible-only default. Small samples and missing outcome data are shown as warnings.

## Catalyst Cluster Explorer

The Research Lab area includes a `Catalyst - Clusters` tab labeled `CATALYST CLUSTERS — RESEARCH ONLY`.

Catalyst Cluster Explorer groups the actual historical headlines stored inside raw captures into deterministic catalyst buckets such as earnings beat, guidance raise, analyst actions, AI infrastructure, AI partnership, contract wins, FDA/biotech events, merger/acquisition, macro-only, weak/vague catalyst, no clear catalyst, and unknown/uncategorized.

The v2 explorer also splits more ambiguous stored headlines into additional deterministic buckets such as product/platform launch, capital markets/financing, legal/regulatory, leadership/strategic update, index/fund flow, and price-action/no-catalyst-detail. This reduces catch-all Sector Sympathy behavior without using AI.

The explorer reads active raw captures plus `score-breakdowns.json`, `review-decisions.json`, `analysis-outcomes.csv`, and catalyst age metrics computed from stored headlines. It does not fetch current market data, mutate raw captures, recalculate historical scores, start optimizer work, or treat post-capture outcomes as capture-time facts.

Timestamp handling is explicit: known article timestamps get capture-time article age, missing timestamps remain `UNKNOWN_TIMESTAMP`, and future timestamps are excluded from catalyst clustering with a warning.

Each catalyst cluster shows deterministic confidence, purity, explicit-rule count, fallback count, exact timestamp rate, unknown timestamp rate, future timestamp rate, representative headlines, and warnings such as `LOW CONFIDENCE CLUSTER`, `LOW PURITY CLUSTER`, `HIGH UNKNOWN TIMESTAMP RATE`, and `HIGH FUTURE TIMESTAMP RATE`.

The cluster detail view lists matching stored headlines, ticker, capture time, source, timestamp status, classification confidence, explicit rule used, fallback reason if applicable, headline age, freshness label, score, review status, outcome status, max gain/drawdown, and stored URL when available. A provider-quality research view summarizes exact, unknown, future, and invalid timestamp rates by provider, cluster, and ticker.

## Catalyst Date / Age Engine

The Research Lab area includes a `Catalyst - Age` tab labeled `CATALYST AGE / FRESHNESS — RESEARCH ONLY`.

Catalyst Age measures stored headline timestamps at capture time. It reports `EXACT_TIMESTAMP`, `DATE_ONLY`, `ESTIMATED`, `UNKNOWN_TIMESTAMP`, `FUTURE_TIMESTAMP`, and `INVALID_TIMESTAMP` without changing any candidate score.

Age buckets are context only: `<1h`, `1-4h`, `4-12h`, `12-24h`, `1-3d`, `3d+`, `unknown`, and `invalid_future`.

Future timestamps are not treated as fresh and are reported as warnings. Unknown timestamps remain unknown and do not receive HOT/FRESH treatment.

The tab includes an audit summary, cluster-by-age summary, ticker-level summary, and headline detail rows. Filters include date range, ticker, catalyst cluster, market regime, scanner preset, timestamp status, age bucket, and the study-eligible-only default.

## Headline Deduplication / Source Quality

The Research Lab area includes a `Catalyst - Headline Dedup` tab labeled `HEADLINE DEDUP / SOURCE QUALITY — RESEARCH ONLY`.

Headline Dedup v1 groups stored historical headlines into deterministic catalyst events using normalized headline fingerprints. Normalization lowercases headlines, strips punctuation, removes source boilerplate, removes ticker prefixes where practical, collapses whitespace, and removes common filler words.

The report shows duplicate event summaries, source reliability, cluster dedup impact, and ticker dedup impact. Event rows include event ID, representative headline, tickers, sources, first/latest seen capture times, earliest known publication time, timestamp status summary, duplicate count, unique source count, catalyst cluster, confidence, notes, and warnings.

Source reliability reports exact timestamp percentage, unknown timestamp percentage, future timestamp percentage, invalid timestamp percentage, duplicate/syndicated rate, unique event count, and average headlines per event by provider/source. This is context only and does not affect Momentum Score, Opportunity Score, score profiles, or recommendations.

No `headline-events.json` file is written in v1. The report is rebuilt from active immutable raw captures and derived stores each time, and quarantined/non-study captures remain excluded by default.

## Outcome Explorer

The Research Lab area includes a `Readiness - Outcome Explorer` tab labeled `OUTCOME EXPLORER — POST-CAPTURE DATA`.

Outcome Explorer v1 compares stored candidate outcomes using only active raw captures and derived records such as `analysis-outcomes.csv`, `score-breakdowns.json`, `review-decisions.json`, catalyst clusters, catalyst age context, and headline dedup/source quality context. It does not fetch current market data, mutate raw captures, recalculate historical scores, alter scoring profiles, or build Opportunity Score.

Summary metrics include candidate count, completed outcome count, pending outcome count, average and median next-day return, average and median five-day return, average max gain, average max drawdown, win rate, best winner, and worst loser. Pending outcomes are counted but are not treated as wins, losses, or completed-return observations.

Comparison tables show performance by score bucket, market regime, scanner, sector, review status, catalyst cluster, catalyst age bucket, and cluster purity bucket. Candidate rows clearly mark outcome values as post-capture labels from `analysis-outcomes.csv`, not information known at capture time.

Outcome Explorer excludes quarantined captures and non-study-eligible captures by default. Enable non-trading-day/preopen inclusion only when deliberately researching those observations.

## Opportunity Research

The Research Lab area includes a `Readiness - Opportunity Research` tab labeled `OPPORTUNITY RESEARCH — RESEARCH ONLY`.

Opportunity Research v1 is a measurement framework for discovering which stored conditions appear predictive after enough outcomes mature. It uses active raw captures and derived context from `analysis-captures.csv`, `analysis-outcomes.csv`, `score-breakdowns.json`, `review-decisions.json`, catalyst clusters, catalyst age metrics, and headline dedup/source reliability metrics.

It does not create Opportunity Score, optimize weights, change `momentum_score_v1`, alter `scoring_profiles.json`, fetch current market data, mutate raw captures, start broker integration, or start SQLite migration.

The tab groups post-capture outcomes by score bucket, market regime, scanner, sector, industry, catalyst cluster, catalyst confidence, cluster purity, catalyst age bucket, review status, source reliability bucket, duplicate-rate bucket, and selected combinations. Ranking tables show best performing, worst performing, most pending, highest max gain, and highest drawdown conditions.

If completed outcomes are too low, the UI says `Insufficient completed outcomes for conclusions.` Pending outcomes are counted but are never treated as wins, losses, or completed-return observations.

## Outcome Maturity / Data Readiness

The Research Lab area includes a `Readiness - Gates` tab labeled `OUTCOME MATURITY / DATA READINESS - MONITOR ONLY`.

The readiness panel uses stored `analysis-captures.csv`, `analysis-outcomes.csv`, active raw capture identity, and review-decision context. It does not fetch current market data, mutate raw captures, alter `momentum_score_v1`, alter `scoring_profiles.json`, create Opportunity Score, optimize weights, start broker integration, or write SQLite records.

Readiness metrics show total candidates, study-eligible candidates, completed next-day outcomes, completed five-day outcomes, pending next-day outcomes, pending five-day outcomes, completed/pending percentages, capture date range, earliest date with usable five-day outcomes, and latest date still pending five-day outcomes.

Readiness gates are shown for Outcome Explorer, Opportunity Research, Opportunity Score design, and Weight optimization. Default thresholds are 20 completed next-day outcomes, 50 completed five-day outcomes, 100 completed five-day outcomes, and 300 completed five-day outcomes respectively. Each gate displays `LOCKED`, `DIAGNOSTIC`, or `READY`, with the current count, required count, reason, and estimated earliest readiness date when the estimate is calculable.

Pending outcomes are never treated as completed. Quarantined captures and non-study-eligible captures remain excluded by default unless the Research Lab filter explicitly includes non-trading-day/preopen observations.

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

Basic Momentum:

- Volume: 1,000,000
- Percent Change: 5%
- Market Cap: $1B
- Price: $5
- Relative Volume: 150%

Heavy Volume Momentum:

- Volume: 3,000,000
- Percent Change: 3%
- Market Cap: $5B
- Price: $10
- Relative Volume: 120%

`Heavy Volume Momentum` intentionally emphasizes higher absolute liquidity, larger market cap, and institutional participation. Its relative-volume threshold is lower than `Basic Momentum`; that is not a typo.

## Trading Safety

Momentum Hunter is a research tool only.

- No automatic trading
- No order placement
- No broker credentials
- No destructive actions
- One active mode at a time
- LIVE mode is reserved for future broker-connected research workflows

## Opportunity Detection Engine

Momentum Hunter now includes an early active-alert foundation that turns trade-planning report changes into timestamped opportunity alerts.

Before polling or alerting, Momentum Hunter can resolve the active monitor universe from watchlist decisions, interested decisions, entry plans, execution-ready trade-planning rows, and user-defined symbols:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.monitor_targets --trade-report "MomentumHunterData\data\reports\event-trade-plan-briefing-YYYY-MM-DD-session.json"
```

This writes `opportunity-monitor-targets-*.csv`, `.json`, and `.md` reports. User-defined monitor symbols live in `opportunity-monitor-symbols.json`; they are derived operator preferences and never modify raw captures.

Run an active monitor cycle after a trade-planning report exists:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.active_monitor
```

The active monitor cycle resolves the current watch universe, filters alert detection to that universe, runs the opportunity alert engine, and writes `active-monitor-cycle-*.csv`, `.json`, and `.md` summaries. If a watchlist or user-defined symbol is missing from the source trade-planning report, the cycle adds a `MONITORING_ONLY` coverage row so the symbol remains visible instead of silently disappearing.

Coverage rows are clearly marked as monitor artifacts. Without live quote fetching they show `COVERAGE_ROWS_WITHOUT_MARKET_DATA`; with quote fetching they can contribute price/RVOL observations for alert detection.

It can also refresh a trade-planning report from the latest raw capture before monitoring:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.active_monitor --latest-capture --fetch-market-data --event-mode
```

To fetch quote tape only for missing watch targets:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.active_monitor --fetch-missing-market-data
```

To refresh quote tape for every active monitor target into a derived monitor report:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.active_monitor --refresh-target-market-data
```

To run a short polling loop:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.active_monitor --cycles 4 --interval-seconds 300
```

Loop status is written to `MomentumHunterData\data\active-monitor-status.json`, including current state, completed cycles, next run time, last report path, warnings, and any failure message.

The refresh mode may use external quote providers and can fail cleanly if provider data is unavailable. Monitor-cycle artifacts are derived records; they do not rewrite raw captures or create broker orders.

The main dashboard shows an `Active Monitor` summary above execution-ready trades. It displays target count, matched/covered symbols, coverage rows, warning state, active/new alert counts, and the latest generated monitor artifact.

Use `Run Monitor Cycle` in that panel to generate one fresh derived monitor cycle from the latest trade-planning report. Leave `Fetch missing quotes` unchecked for a fast local-only cycle; check it when you want Momentum Hunter to try quote-tape fetches for watchlist/user-defined symbols missing from the latest trade-planning report. Use `Refresh target quotes` when you want fresh quote tape for every active monitor target; this writes a separate `active-monitor-refresh-*.json` artifact, recalculates readiness in that derived artifact, and preserves the original trade-planning report.

Use the `Symbol` / `Monitor note` controls in the same panel to add extra user-defined symbols to the active monitor universe. `Remove Selected` deletes selected user-defined symbols from `opportunity-monitor-symbols.json`; these are operator preferences and do not modify raw captures.

Use `Start Monitor Loop` to launch active monitoring in a background Python process, and `Stop Monitor` to terminate it. The background runner writes `MomentumHunterData\data\active-monitor-runner.json` with the process id, command, interval, fetch mode, and current runner state.

Run it after generating a trade-planning report:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.opportunity_alerts --trade-report "MomentumHunterData\data\reports\event-trade-plan-briefing-YYYY-MM-DD-session.json"
```

The alert engine compares the latest trade-planning report against `opportunity-monitor-state.json` and records alerts in `opportunity-alerts.json` when it detects:

- trade state changes, such as `PLANNING_SCAFFOLD` to `EXECUTION_READY_TRADE`
- RVOL threshold crosses at `0.5`, `1.0`, `1.2`, and `2.0`
- breakouts above previous-day high or planned entry
- support reclaims
- catalyst/news summary changes, stored as `BREAKING_NEWS_CATALYST`
- short-window price expansion when consecutive reports are close enough in time

Every alert stores the timestamp, symbol, alert type, current readiness state, entry/stop/targets, bid/ask/spread, volume, RVOL context, catalyst text, market regime, event-mode flag, and source report path. Alerts are derived validation records; they do not mutate raw captures and do not place trades.

The dashboard shows compact `Active Alerts` and `State Transitions` panels from the latest derived alert/trade-planning stores. Each alert-engine run also stores price observations in `opportunity-price-observations.json` and updates pending alerts once enough post-alert observations exist. Current outcome metrics include 5/15/30/60-minute returns, 15/30/60-minute MFE and MAE, target/stop hits, stop-before-target ordering, and deterministic alert classification.

Alert outcomes are separated into three evidence buckets:

- completed scored outcomes: `SUCCESSFUL`, `FAILED`, `NOISE`, or `LATE`
- pending outcomes: alerts still waiting for recoverable post-alert market data
- unscorable data-quality outcomes: terminal records such as `UNSCORABLE_MISSING_ENTRY_PRICE` or `UNSCORABLE_INVALID_TIMESTAMP`

Unscorable alerts stay in `opportunity-alerts.json` for auditability, but they are excluded from pending counts, win-rate math, completed-outcome thresholds, and optimization gates.

For stronger validation, update alert outcomes from one-minute bars:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.alert_outcome_updater --fetch-missing-bars
```

This writes one-minute bars to `opportunity-minute-bars.json` and updates `opportunity-alerts.json`. It is derived validation data only; it does not mutate raw captures, place orders, or change scanner scores.

The dashboard also includes `Update Alert Outcomes` and `Fetch minute bars` controls in the `Execution Ready` panel. The last update status is stored in `alert-outcome-update-status.json` and displayed above the Alert Outcome Tracker.

Generate the standalone alert-performance analytics report with:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.alert_performance
```

This writes `alert-performance-report-*.json` and `alert-performance-report-*.md` under `MomentumHunterData\data\reports`. The report uses existing alert outcomes only and summarizes performance by alert type, symbol, and readiness state. Each group shows alert count, completed/pending/unscorable counts, win rate, 5/15/30/60-minute average returns, average MFE/MAE, and `SUCCESSFUL` / `FAILED` / `NOISE` / `LATE` rates.

The dashboard surfaces Active Alerts, State Transitions, the Alert Outcome Tracker, and an `Alert Performance` section with best/worst alert types, best/worst symbols, and current sample size. Small samples are explicitly diagnostic only.

Generate evidence-health and reliability reports with:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.evidence_health
```

This writes `evidence-health-report-*.json`, `evidence-health-report-*.md`, `reliability-report-*.json`, and `reliability-report-*.md` under `MomentumHunterData\data\reports`.

To install scheduled evidence reports:

```powershell
powershell -ExecutionPolicy Bypass -File "C:\Users\steve\OneDrive\Documents\Investing\tools\install_evidence_report_tasks.ps1" -RunWhetherLoggedOn
```

That installs:

- `Momentum Hunter Evidence Health Daily`, defaulting to 8:30 PM CT
- `Momentum Hunter Reliability Weekly`, defaulting to Friday at 8:45 PM CT

Evidence Health tracks the alert funnel:

```text
Alerts Generated -> Alerts Captured -> Alerts Classified -> Completed Outcomes
```

It also reports pending alerts, terminal unscorable alerts, stale pending alerts, missing minute bars, missing outcome data, incomplete outcome calculations, missing readiness states, missing news snapshots, and whether the evidence threshold is still locked. Strategy optimization stays locked until at least 100 completed scored alerts exist, and no strategy changes should be recommended below the evidence thresholds.

Run Evidence Autopilot once from the command line:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.evidence_autopilot
```

Evidence Autopilot executes the existing monitor cycle, alert outcome updater, Evidence Health report, and daily evidence brief. It writes status to `MomentumHunterData\data\evidence-autopilot-status.json` and a brief like `MomentumHunterData\data\reports\daily-evidence-brief-YYYY-MM-DD.md`.

The dashboard `Run Evidence Autopilot` button performs the same orchestration. It is evidence infrastructure only; it does not change alert generation, scoring, readiness logic, ranking, or trade-planning rules.

## Roadmap

Strategic priority order:

1. Fix live market tape and minute-bar reliability so monitor evidence can become measurable.
2. Harden the Active Alert Engine so it detects emerging opportunities from watchlist, interested, execution-ready, and user-defined symbols.
3. Mature Alert Outcome Tracking so every alert can answer what happened after it fired.
4. Add Position Management / Exit Logic so open short-term trades can be managed with `HOLD`, `TRIM`, or `EXIT` decisions.
5. Add a Relative Strength Engine to separate true leaders from stocks merely moving with QQQ or their sector ETF.
6. Add Liquidity Sweep and Market Structure Detection to prevent abnormal prints, low-liquidity moves, and ETF-wide anomalies from producing execution-ready signals.

Position Management / Exit Logic should not say "sell just because I am up." It should answer whether the same position would still be opened today at the current price, whether leadership is intact, whether the symbol is still outperforming QQQ and its sector ETF, what evidence would justify selling, and whether the current action is `HOLD`, `TRIM`, or `EXIT`.

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
