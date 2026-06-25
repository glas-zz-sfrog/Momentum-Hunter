# Momentum Hunter Changelog

## 2026-06-25

### Added

- Added SQLite Migration Foundation v1 documentation with current storage audit, risk classification, and initial schema proposal.
- Added additive SQLite adapter and migration CLI for `MomentumHunterData/data/momentum-hunter.sqlite3`.
- Added idempotent schema initialization and first low-risk vertical slice importing provider/data-quality report rows into `provider_quality_checks`.
- Added focused SQLite tests for schema initialization, idempotent migrations, import round trip, duplicate handling, DB creation, report generation, and source-file immutability.
- Added Autonomous Reliability Sprint v1 report layer with `momentum_hunter.data_quality`, `momentum_hunter.evidence_autopilot_reliability`, and `momentum_hunter.system_readiness`.
- Added latest derived reports for provider/data-quality audit, Evidence Autopilot reliability, and system readiness under `MomentumHunterData/data/reports/`.
- Added explicit timestamp-quality accounting to the data-quality report so unavailable quote timestamps are marked unknown rather than treated as fresh.
- Added Evidence Autopilot background/app-closed behavior fields so a completed run is not mistaken for a verified daemon.
- Added documentation for provider audit, Evidence Autopilot reliability, system-readiness data layer, and the Autonomous Reliability Sprint safety contract.
- Added focused non-Qt tests for data-quality reporting, Evidence Autopilot reliability reporting, and readiness-section status behavior.

### Safety

- Reliability reports are read-only diagnostics. They do not change scanner logic, scoring math, readiness thresholds, alert generation, ranking, trade-planning rules, raw captures, broker behavior, or automated trading behavior.
- SQLite is additive only. Existing JSON/CSV/Markdown outputs remain active, and raw captures plus user-authored review/watchlist/entry-plan state remain file-based.

## 2026-06-24

### Fixed

- Added Phase 2A Candidate Story design documentation and changed the default Timeline / Replay dialog from a dense table-first timeline to a graph-first Candidate Story.
- Candidate Story now shows a compact story header with first/latest capture, price move, score movement, peak score, trusted capture count, and plain-language status before the audit table.
- Added a prominent stored-capture trail chart for price and score, simplified capture story rows, and missing-data placeholders for Intraday and 5D modes.
- Preserved the existing dense Timeline table as `Advanced Capture Audit` under Audit mode so capture identity, provider, scanner, source path, and replay audit details remain available.
- Added deterministic Candidate Story helper tests for first/latest/peak summary, insufficient single-capture stories, and missing stored-price warnings.
- Fixed Replay page navigation no-ops so `Current Dashboard` returns the operator to the live/current dashboard, while `Open Historical Snapshot` now opens the selected historical snapshot inside the Replay page.
- Added Replay Selection Integrity guardrails: Timeline detail and full Replay views now show a visible audit identity strip with selected capture timestamp, capture ID, symbol, candidate row ID/fingerprint, outcome record ID, source file path, and last refresh time.
- Replay row switching now avoids silent first-row fallback when no row is selected; empty timelines and invalid selections show explicit reasons.
- Added regression coverage proving June 17 and June 18 Replay rows produce distinct detail/replay identities and that different selected candidate symbols produce different Timeline rows.
- Added a left-rail Back button with page-history tracking so operators can return to the previous screen after jumping between Dashboard, Watchlist, Evidence, Research, Replay, and Health.
- Fixed the empty Replay page workflow: `Open Historical Snapshot` now populates a read-only snapshot candidate table and detail/audit pane directly on the Replay page instead of leaving the page blank or forcing a one-way loop through Dashboard.
- The Replay page `Open Timeline / Replay For Selected Candidate` action now uses the selected Replay snapshot row when the operator is on the Replay page.
- Added explicit derived outcome maturity fields for next-day and five-day outcome sessions, including expected session dates, per-horizon states, reason text, and calculation version.
- Timeline / Replay now shows expected next-day and five-day maturity dates, outcome states, outcome reason, max drawdown, and outcome calculation version in the detail panel.
- Legacy outcome rows without the new maturity fields are interpreted safely in Replay: if next-day return is present but five-day has not matured, Replay shows the next-day result as complete and the five-day result as `pending_not_mature` instead of silently looking blank.
- Verified the Juneteenth 2026 case: June 18 captures use June 22 as the expected next outcome session and June 26 as the expected five-day outcome session.

### Safety

- Outcome maturity fields are derived labels in `analysis-outcomes.csv`; they are not written into immutable raw captures.
- The outcome engine uses market-open session dates for labels and does not change scanner, scoring, alert, readiness, ranking, trade-planning, or broker behavior.
- Existing top-score / five-day-hold analysis should remain blocked until mature outcomes are proven with expected session dates, calculation version, and duplicate-inflation checks.

### Tests

- Added Juneteenth outcome tests proving June 19 is skipped and June 22 is the expected next outcome session.
- Added scheduling tests for Juneteenth holiday skips, market-day premarket/intraday/post-close classification, and early-close-as-market-open behavior.
- Added Replay tests for explicit and legacy outcome maturity context.
- Added targeted Replay navigation tests for historical snapshot selection, empty-capture no-fallback handling, and current-dashboard restoration.

## 2026-06-23

### Fixed

- Added defensive Finviz quote-page enrichment for scanner Relative Volume so the table can show Finviz `Rel Volume` values when the screener overview omits them.
- Kept scanner results stable if quote-page enrichment fails; candidates remain visible with `n/a` Relative Volume instead of failing the scan.
- Fixed candidate-selection safety so simply selecting or auto-selecting a row no longer marks the ticker as reviewed.
- Added visible failure feedback for Research Lab and Readiness Gate report loading instead of leaving the operator with only a stalled-looking workflow.
- Improved Score Breakdown dialog formatting for easier scanning without changing score math.
- Clarified duplicate dashboard review actions with explicit checked-row/selected-row wording and tooltips.
- Added visible Morning Review feedback for no-selection entry-plan saves and candidate status changes.
- Phase 1B: preserved checked candidate rows during row selection/detail refresh and limited checkmark clearing to explicit bulk actions.
- Phase 1B: removed the duplicate top-bar Mark Interested shortcut and relocated Clear Checkmarks to the candidate action bar.
- Phase 1B: added a Watchlist Center summary/table backed by the same current candidates and review decisions as the dashboard.
- Phase 1B: moved Research Lab and Readiness Gate report building to background workers with a loading dialog and load-time status.
- Phase 1B: improved Why Score content formatting for market cap, volume, rule thresholds, Base Points vs Applied Impact, freshness context, and latest valid article context.
- Pre-1B follow-up: hardened Research Lab panel loading so a failing research panel shows a recoverable error instead of taking down the app.
- Pre-1B follow-up: clarified `Heavy Volume Momentum` scanner semantics with visible tooltip/criteria text explaining higher absolute liquidity and lower relative-volume threshold.
- Pre-1B follow-up: changed Watchlist Center plan display to `Trade Plan`, progress such as `Incomplete 0/4`, missing-field tooltips, and a row-level `Edit Plan` action.
- Pre-1B follow-up: Timeline / Replay now marks missing or legacy-zero relative volume as `N/A` instead of showing a misleading `0.0`.
- Pre-1B follow-up: Timeline / Replay warns when repeated signal fingerprints appear across captures while preserving timestamped rows.
- Pre-1B follow-up: grouped Evidence Console into Monitor + Health, Execution Ready, Alerts + Outcomes, and Performance tabs with a top next-action guidance strip.
- Pre-1B follow-up: added Timeline / Replay view presets for `Signal`, `Outcome`, and `Audit`, plus a selected-row detail panel separating capture-time facts from later annotations.
- Pre-1B follow-up: made Research Lab open with lightweight overview panels first, while heavier research panels load only when their tab action is requested.
- Pre-1B follow-up: optimized Readiness Gate report generation so it reads the derived outcome CSV directly and filters to active captures without triggering the heavier Outcome Explorer path.
- Pre-1B follow-up: added `docs/PRE_1B_CONTROL_STATUS.md` mapping each workbook finding to fixed, verified, preserved, or intentionally deferred status.
- Added `docs/ONE_B_STABILIZATION_PLAN.md` as the active 1B stabilization contract for the Operator Command Center phase.

### Tests

- Added targeted tests for Finviz Relative Volume enrichment/fallback, command-center navigation, passive-selection review safety, and Research/Readiness failure feedback.
- Added targeted tests for checkbox preservation, Watchlist Center persistence, non-blocking Research loading, and Why Score readable formatting.
- Added targeted replay tests for legacy-zero relative volume and repeated signal fingerprints.
- Verified Research Lab initial panel loading with an isolated offscreen Qt smoke probe instead of broad Qt unittest modules.
- Verified Readiness Gate report generation with focused unit tests and a direct timing probe.
- Adopted the UI/Qt testing safety rule: run isolated probes with hard timeouts, bytecode disabled, and Python process checks after risky commands instead of broad Qt unittest modules.

## 2026-06-22

### Added

- Added the Operator Workflow Preservation Matrix as the baseline contract before Operator Dashboard Redesign v1.
- Refreshed UI screenshots for the dashboard, evidence sections, watchlist, Morning Review, Daily Checklist, Capture Health, Timeline/Replay, historical snapshot, and Research Lab.

### Safety

- Documented that no current operator workflow may be removed during the dashboard migration; workflows may only stay in place or move to Dashboard, Watchlist Center, Evidence Console, Research Lab, Timeline/Replay, Capture Health, or background/scheduled execution.
- Documented stale/current/historical/replay/research workflow safety rules to preserve during layout migration.

## 2026-06-20

### Added

- Added Data Quality Terminal States v1 for alert outcomes that can never be scored, including `UNSCORABLE_MISSING_ENTRY_PRICE` and `UNSCORABLE_INVALID_TIMESTAMP`.
- Updated one-shot Active Monitor and Evidence Autopilot cycles to refresh `active-monitor-status.json` so the dashboard shows the latest monitor run instead of stale background-runner state.
- Added Evidence Health and Reliability reporting with `evidence-health-report-*.json`, `.md`, `reliability-report-*.json`, and `.md` outputs.
- Added Evidence Autopilot v1 CLI and dashboard control to run the existing monitor cycle, outcome updater, Evidence Health report, and daily evidence brief in one orchestration pass.
- Added derived `evidence-autopilot-status.json` status store and `daily-evidence-brief-YYYY-MM-DD.md` output.
- Added dashboard `Evidence Health` section showing completed-alert threshold progress, completion rate, alert funnel, data issues, and optimization gate status.
- Added evidence gates that keep strategy optimization locked below defined completed-alert thresholds.
- Added optional Windows scheduled-task tooling for daily Evidence Health and weekly Reliability report generation.

### Safety

- Unscorable alert outcomes remain in the derived alert store for auditability but are excluded from pending counts, success/failure/noise/late counts, completed-outcome thresholds, and optimization gates.
- Evidence Health reads existing derived evidence stores only and does not change scoring, alert thresholds, readiness logic, ranking, monitoring rules, or trade-planning rules.
- Evidence Autopilot is orchestration only and does not duplicate or change alert generation, scoring, readiness logic, ranking, monitoring rules, or trade-planning rules.
- Evidence thresholds are reporting gates only; they do not alter signal generation.

### Tests

- Added tests for missing-price and invalid-timestamp terminal alert outcomes, recoverable missing-bar pending behavior, unscorable evidence-health reporting, and alert-performance unscorable counts.
- Added tests for alert-funnel counts, stale pending alerts, missing minute-bar warnings, missing outcome warnings, reliability math, report export, read-only alert-store behavior, and dashboard Evidence Health rows.
- Added tests for Evidence Autopilot orchestration, status persistence, failure status, daily brief generation, and dashboard autopilot status rows.

## 2026-06-19

### Added

- Added Alert Performance Analytics v1 with standalone `alert-performance-report-*.json` and `.md` exports from existing opportunity-alert outcomes.
- Added main-dashboard `Alert Performance` section showing best/worst alert types, best/worst symbols, and current completed-alert sample size.

### Safety

- Alert Performance Analytics reads existing derived alert outcomes only and does not change trade-planning logic, alert-generation logic, readiness logic, monitoring logic, raw captures, or score outputs.

### Tests

- Added tests for deterministic Alert Performance Analytics grouping/export and dashboard performance helper rows.

## 2026-06-17

### Added

- Added roadmap documentation for Position Management / Exit Logic as a high-priority future milestone after Alert Outcome Tracking and before Liquidity Sweep / Market Structure Detection.
- Added the post-entry management principle that Momentum Hunter should answer `HOLD`, `TRIM`, or `EXIT` based on evidence rather than selling only because a position is profitable.
- Added Active Opportunity Detection and Validation Engine v1 foundation.
- Added `momentum_hunter.opportunity_alerts` to generate timestamped opportunity alerts from trade-planning report changes.
- Added derived stores `MomentumHunterData/data/opportunity-alerts.json` and `MomentumHunterData/data/opportunity-monitor-state.json`.
- Added derived observation store `MomentumHunterData/data/opportunity-price-observations.json`.
- Added alert detection for trade state transitions, RVOL threshold crosses, previous-day-high breakouts, planned-entry breakouts, support reclaims, and short-window price expansion.
- Added deterministic `BREAKING_NEWS_CATALYST` alerts when a monitored symbol's stored catalyst/news summary changes.
- Added alert outcome tracking for 5/15/30/60-minute returns, 15/30/60-minute MFE/MAE, target/stop hits, stop-before-target ordering, and deterministic alert classification.
- Added alert learning summaries by alert type, symbol, readiness state, and market regime.
- Added opportunity alert CSV, JSON, and Markdown report export.
- Added dashboard `Active Alerts`, `Alert Outcome Tracker`, and alert leaderboard displays alongside Execution Ready and State Transitions.
- Added `momentum_hunter.monitor_targets` to resolve the active monitoring universe from watchlist decisions, interested decisions, entry plans, execution-ready trade-planning rows, and user-defined symbols.
- Added derived user-defined monitor symbol store `MomentumHunterData/data/opportunity-monitor-symbols.json`.
- Added opportunity monitor target CSV, JSON, and Markdown report export.
- Added `momentum_hunter.active_monitor` to run a focused active monitor cycle that resolves targets, filters alert detection to the monitor universe, exports alert reports, and writes active-monitor cycle summaries.
- Added `MONITORING_ONLY` coverage rows for watchlist/user-defined monitor targets missing from the source trade-planning report.
- Added optional missing-target quote tape support through `--fetch-missing-market-data`.
- Added main-dashboard `Active Monitor` summary panel showing latest monitor cycle target coverage, coverage warnings, active/new alert counts, and generated artifact context.
- Added main-dashboard `Run Monitor Cycle` control and explicit `Fetch missing quotes` option for one-shot active monitor refreshes.
- Added status-aware active monitor loop support with `active-monitor-status.json`, `--cycles`, `--interval-seconds`, and failure-state recording.
- Added `momentum_hunter.active_monitor_runner` and main-dashboard `Start Monitor Loop` / `Stop Monitor` controls for non-blocking background monitoring.
- Added main-dashboard user-defined monitor symbol controls with `Symbol`, `Monitor note`, `Add Symbol`, `Remove Selected`, and a compact monitor-symbol table.
- Added `--refresh-target-market-data` and dashboard `Refresh target quotes` support to refresh quote tape for every active monitor target into a separate derived `active-monitor-refresh-*.json` report.
- Added derived readiness recalculation for refreshed monitor rows so active-monitor cycles can detect readiness state changes without rewriting the source trade-planning report.
- Added `momentum_hunter.alert_outcome_updater` to update pending opportunity-alert outcomes from one-minute bars.
- Added derived one-minute bar store `MomentumHunterData/data/opportunity-minute-bars.json`.
- Added derived alert outcome update status store `MomentumHunterData/data/alert-outcome-update-status.json`.
- Added dashboard `Update Alert Outcomes` and `Fetch minute bars` controls with visible last-run outcome update status.

### Safety

- Opportunity alerts are derived validation records and do not mutate raw captures.
- Alert outcomes update only derived alert records; no Opportunity Score, optimizer, broker integration, order placement, SQLite migration, or automated trading was added.
- Monitor target resolution is derived operator workflow data and does not fetch current market data or mutate raw captures.
- Active monitor cycles write derived monitoring artifacts only and do not mutate raw captures, place orders, alter scoring, or add broker integration.
- Monitor coverage rows are labeled as derived coverage artifacts and are not presented as scanner picks or raw capture facts.
- Active monitor status is derived runtime state and records heartbeat/failure information without changing captures or score outputs.
- Active monitor runner state is process-control metadata only; it does not place orders, mutate captures, alter scoring, or connect to a broker.
- User-defined monitor symbols are derived operator preferences only and do not mutate raw captures, scoring, or trade plans.
- Refreshed target quote reports are derived monitoring artifacts; they update market tape and derived readiness for alert detection but do not mutate raw captures or silently rewrite the source trade-planning report.
- Minute-bar alert outcome updates write only derived alert/bar stores and do not mutate raw captures, scanner output, scores, or trade plans.
- Dashboard alert outcome update controls call the same derived updater and do not place orders or mutate capture/source report history.

### Tests

- Added tests for deterministic alert detection, alert-store deduplication, raw-capture immutability, pending alert report output, fixed-time return tracking, MFE/MAE outcome tracking, stop-before-target failure classification, and grouped alert learning summaries.
- Added tests for new catalyst appearance, catalyst-change alerts, and unchanged catalyst suppression.
- Added tests for monitor-target source merging, deduplication, include/exclude flags, user-symbol persistence, export generation, and raw-capture immutability.
- Added tests for active monitor target filtering, missing target warnings, monitor-cycle artifact export, and raw-capture immutability.
- Added tests proving missing monitor targets can be covered honestly and can generate price-expansion alerts when quote tape is available.
- Added tests for active monitor dashboard summary/coverage helpers, including bad-report handling.
- Added tests for user-defined monitor symbol row display, malformed symbol-store handling, and symbol removal persistence.
- Added tests proving target quote refresh updates existing monitored rows through a derived report, preserves raw captures, recalculates readiness, and can generate state-change and price-expansion alerts.
- Added tests for one-minute bar outcome updates, including fixed-window returns, MFE/MAE from high/low bars, target/stop ordering, completed-alert preservation, and raw-capture immutability.
- Added tests for alert outcome update status persistence and dashboard status text.
- Added tests for active monitor loop status persistence, multiple-cycle execution without real sleeps, and failure-state recording.
- Added tests for background runner command generation, fake-process start behavior, running-process reuse, stop handling, and missing-state stop behavior.

## 2026-06-14

### Added

- Added Operator Workflow Redesign v1 Phase 1.
- Added operator review states that separate market-data freshness from next-session review validity.
- Added `Ready for Next Session Review`, `Aging but Reviewable`, `Current Manual Scan`, and `Expired Review Snapshot` UI language.
- Added a `What should I do next?` guidance area for review, entry-plan, watchlist, capture-failure, and research-only contexts.
- Added delayed-review metadata to `review-decisions.json` for aged-but-valid review decisions.
- Renamed scanner display labels to `Basic Momentum` and `Heavy Volume Momentum` while keeping internal preset keys compatible.
- Renamed visible workflow actions to `Generate Watchlist Report`, `Open Latest Watchlist`, `Research Lab`, `Clear Checkmarks`, `Move Interested to Watchlist`, and `Timeline / Replay`.

### Safety

- Aged evening/preopen captures remain reviewable until 8:30 AM CT on their next market session date.
- Watchlist report generation from aged-but-reviewable snapshots requires acknowledgement.
- Expired, historical, replay, research, quarantined, missing, and failed contexts block trading workflow actions with visible explanations.
- Raw captures remain immutable; review decisions, delayed-review metadata, entry plans, and watchlist artifacts remain derived/user records.
- No Opportunity Score, optimizer, broker integration, SQLite migration, automated trading, or new research engine was added.

### Tests

- Added operator-review state tests for aged evening/preopen review, expiration, and quarantine blocking.
- Updated data-view, review workflow, Morning Review, Daily Workflow, and GUI state tests for warning-but-reviewable aged snapshots.
- Added tests for acknowledgement-controlled watchlist generation and delayed-review metadata storage.

## 2026-06-11

### Added

- Added Operator Navigation Cleanup v1.
- Renamed top-level workflow actions to `Daily Checklist`, `Morning Review`, `Capture Health`, `Generate Watchlist`, `Latest Watchlist`, `Open Historical Snapshot`, `Current Dashboard`, and `Research Study`.
- Grouped Study tabs with purpose prefixes: `Overview`, `Catalyst`, `Readiness`, and `Locked Research Notes`.
- Added Documentation, Workflow, and Roadmap Audit v1.
- Added `docs/ROADMAP_AUDIT.md` with UI view purpose/workflow notes, roadmap status, feature inventory, duplicate-functionality findings, documentation findings, future-idea findings, and recommended next milestone.
- Added deferred ideas for Study Engine consolidation, daily operator workflow consolidation, Watchlist/Research List naming cleanup, Recommendations readiness gating, and documentation encoding cleanup.
- Added Daily Workflow Checklist / Review Report v1.
- Added a `Daily Checklist` toolbar action with capture status, review status, entry-plan status, outcome status, readiness status, workflow warnings, and a workflow-discipline score.
- Added quick actions for Open Morning Review, Generate Watchlist, Open Capture Health, and Open Readiness Gate.
- Added Daily Workflow Checklist screenshot generation for documentation evidence.
- Added Morning Review Workspace v1.
- Added a `Morning Review` toolbar action with a focused candidate table, compact Decision Card, score/catalyst/freshness context, source and duplicate warning context, review actions, and entry-plan editing.
- Added quick actions for Mark Interested, Mark Rejected, Add to Watchlist, Open Why Score, and Open Timeline/Replay.
- Added Morning Review screenshot generation for documentation evidence.

### Safety

- Operator Navigation Cleanup v1 is UI/navigation-only and does not add trading logic, scoring changes, Opportunity Score, optimizer work, broker integration, SQLite migration, or new research engines.
- Documentation, Workflow, and Roadmap Audit v1 is documentation-only and does not add trading logic, scoring changes, optimizer work, broker integration, or SQLite migration.
- Daily Workflow Checklist is workflow tracking only and does not add scoring changes, Opportunity Score, optimization, broker integration, order placement, SQLite migration, or automated trading.
- The workflow score measures daily process completion only and does not evaluate trade quality.
- Morning Review is workflow/UI only and does not add broker integration, order placement, Opportunity Score, optimizer logic, scoring changes, SQLite migration, or automated trading.
- Current/live data can be reviewed and edited; stale, historical, replay, and study-style views remain clearly warned and read-only.
- Review decisions and entry plans continue to live in derived stores and do not mutate immutable raw captures.

### Tests

- No tests were added for the documentation-only audit because no runtime behavior changed.
- Added tests for deterministic Daily Workflow counts, workflow score math, warning triggers, raw-capture immutability, and read-only historical/study quick-action behavior.
- Added tests for current Morning Review editing, stale-data warnings, historical/study read-only behavior, raw-capture immutability, selected-candidate Decision Card updates, and incomplete-plan warnings.

## 2026-06-09

### Added

- Added Watchlist Discipline / Entry Plan v1.
- Added `entry-plans.json` as a separate user planning store keyed by candidate identity.
- Expanded the Entry Plan UI with trigger, stop, thesis, invalidation, max loss, position size idea, planned hold time, notes, and Plan Complete status.
- Added incomplete-plan warnings for missing trigger, stop, invalidation, and max loss.
- Added entry-plan fields to Watchlist Report output.

### Safety

- Entry plans are planning/journaling records only and do not place orders, integrate brokers, create Opportunity Score, optimize weights, mutate raw captures, or write SQLite records.
- Historical, Replay, and Study views remain read-only for entry-plan editing.

### Tests

- Added tests for entry-plan persistence, raw-capture immutability, read-only historical behavior, watchlist report output, and incomplete-plan warnings.

### Added

- Added Historical Cluster Display recurrence refinement.
- Added ticker, sector, and scanner recurring cluster summaries using stored active captures and Replay Mode identities.
- Added recurrence appearance detail support with capture-time fields separated from later-derived outcome labels.
- Added Replay Mode handoff for individual historical appearances from recurring clusters.
- Added documentation-only future idea for Automated Market-Cycle Classification.

### Safety

- Historical recurrence clustering does not fetch current market data, mutate raw captures, recalculate historical scores, start provider integrations, start optimizer work, or write SQLite records.
- Quarantined captures remain excluded by default, and non-study-eligible captures remain filtered through the existing Study Engine controls.

### Tests

- Added tests for repeated ticker, sector, scanner clustering, chronological appearance ordering, recency/count sorting, average score calculation, score-breakdown status counts, outcome summaries, quarantine exclusion, Replay Mode handoff, and no current-data fetch.

### Added

- Added Outcome Maturity / Data Readiness Gate v1.
- Added `Readiness Gate` Study Engine tab with readiness metrics and gate statuses for Outcome Explorer, Opportunity Research, Opportunity Score design, and Weight optimization.
- Added completed next-day versus completed five-day outcome counting so pending five-day rows do not block next-day readiness measurement.
- Added readiness warnings for insufficient completed outcomes, high pending rate, diagnostic-only state, and trading-decision safety.

### Safety

- Outcome Maturity v1 is monitor-only and does not create Opportunity Score, optimize weights, alter `momentum_score_v1`, alter `scoring_profiles.json`, fetch current market data, mutate raw captures, start broker integration, or write SQLite records.
- Pending outcomes are counted as pending and are never treated as completed outcomes.
- Quarantined captures and non-study-eligible captures remain excluded by default through the existing active-capture and Study Engine filters.

### Tests

- Added tests for deterministic readiness counts, pending exclusion, gate thresholds, quarantined capture exclusion, non-study default exclusion, raw-capture immutability, and graceful readiness-date estimates.

## 2026-06-07

### Added

- Added Opportunity Research Framework v1.
- Added `Opportunity Research` Study Engine tab with summary, condition grouping, ranking, and combination-analysis views.
- Added condition analysis by score bucket, market regime, scanner preset, sector, industry, catalyst cluster, catalyst confidence, cluster purity, catalyst age bucket, review status, source reliability bucket, and duplicate-rate bucket.
- Added ranking tables for best performing, worst performing, most pending, highest max gain, and highest drawdown conditions.
- Added combination analysis for regime+catalyst, score+catalyst confidence, score+cluster purity, and review+catalyst conditions.

### Safety

- Opportunity Research v1 is research-only and does not create Opportunity Score, optimize weights, alter `momentum_score_v1`, alter `scoring_profiles.json`, fetch current market data, mutate raw captures, start broker integration, or write SQLite records.
- Pending outcomes are counted but excluded from completed-return math and are never treated as wins or losses.
- The UI displays `Insufficient completed outcomes for conclusions.` when completed outcomes are too low.

### Tests

- Added tests for deterministic groupings/rankings, pending exclusion, low-sample warnings, raw-capture immutability, quarantined capture exclusion, non-study default exclusion, and post-capture outcome separation.

### Added

- Added Outcome Explorer v1.
- Added `Outcome Explorer` Study Engine tab with summary, score bucket, regime, scanner, sector, review-status, catalyst-cluster, catalyst-age-bucket, cluster-purity, and candidate detail views.
- Added outcome filters for score bucket and industry alongside existing date, ticker, score, regime, scanner, sector, review, cluster, confidence, purity, timestamp status, age bucket, and study-eligibility filters.
- Added completed/pending outcome separation and post-capture labeling.

### Safety

- Outcome Explorer v1 is research-only and does not fetch current market data, mutate raw captures, recalculate historical scores, alter scoring profiles, start Opportunity Score, optimize weights, use broker APIs, or write SQLite records.
- Pending outcomes are counted but excluded from completed-return math and are not treated as wins or losses.
- Quarantined captures are excluded by requiring outcome rows to match active raw-capture identities.

### Tests

- Added tests for deterministic filters, deterministic summary metrics, pending outcome exclusion, quarantined/orphan outcome exclusion, non-study default exclusion, preopen inclusion, raw-capture immutability, and post-capture label separation.

### Added

- Added Headline Deduplication / Source Quality v1.
- Added deterministic headline fingerprinting and in-memory catalyst event grouping.
- Added `Headline Dedup` Study Engine tab with duplicate event summary, source reliability, cluster dedup impact, and ticker dedup impact views.
- Added source/provider reliability metrics for exact, unknown, future, and invalid timestamp rates, duplicate/syndicated rate, unique event count, and average headlines per event.
- Added source and minimum duplicate count filters.

### Safety

- Headline Dedup v1 is research-only and does not change Momentum Score, Opportunity Score, scoring profiles, optimizer behavior, broker behavior, SQLite storage, or raw captures.
- Future timestamp headlines are warned in source-quality reporting and are not treated as fresh.
- Dedup results are rebuilt in memory from stored data; no `headline-events.json` file is written in v1.

### Tests

- Added tests for deterministic fingerprinting, deterministic duplicate grouping, raw-capture immutability, quarantine exclusion, non-study default exclusion, preopen inclusion, future/unknown timestamp warnings, source reliability, and duplicate-count filtering.

### Added

- Added Catalyst Cluster Explorer v2 refinement.
- Added deterministic catalyst classification confidence, rule names, explicit/fallback labels, fallback reasons, cluster purity, and explicit match statistics.
- Added provider timestamp-quality summaries by provider, catalyst cluster, and ticker.
- Added Catalyst Explorer quality filters for minimum confidence, minimum purity, and minimum exact timestamp percentage.
- Added additional deterministic catalyst buckets for product/platform launch, capital markets/financing, legal/regulatory, leadership/strategic update, index/fund flow, and price-action/no-catalyst-detail.

### Safety

- Catalyst Cluster Explorer v2 remains research-only and does not change scores, scoring profiles, raw captures, optimizer behavior, broker behavior, or SQLite storage.
- Future timestamp headlines remain excluded from clustering and freshness-style analysis while still appearing in timestamp-quality warnings.

### Tests

- Added tests for deterministic classification confidence, purity, provider timestamp quality, fallback labeling, threshold filters, future timestamp exclusion, and raw-capture immutability coverage.

### Added

- Added Catalyst Date / Age Engine v1 in the Study Engine.
- Added `Catalyst Age` tab with audit totals, headline age bucket distribution, cluster-by-age summary, ticker-level summary, and headline-level details.
- Added timestamp statuses: `EXACT_TIMESTAMP`, `DATE_ONLY`, `ESTIMATED`, `UNKNOWN_TIMESTAMP`, `FUTURE_TIMESTAMP`, and `INVALID_TIMESTAMP`.
- Added age buckets: `<1h`, `1-4h`, `4-12h`, `12-24h`, `1-3d`, `3d+`, `unknown`, and `invalid_future`.
- Added age filters for ticker, catalyst cluster, timestamp status, and age bucket.

### Safety

- Catalyst age is measurement-only and does not alter `momentum_score_v1`, score profiles, existing scores, or scoring output.
- Future timestamps are warned and excluded from freshness-style analysis.
- Unknown timestamps remain unknown and are not treated as fresh.

### Tests

- Added tests for exact/date-only/estimated/unknown/future/invalid timestamps, deterministic age buckets, raw-capture immutability, quarantine exclusion, preopen inclusion rules, and age filters.

### Added

- Added legacy non-study capture cleanup command for quarantining unwanted non-market-day `morning`/`evening` captures while preserving valid `preopen` captures.
- Added derived CSV backup and prune behavior for legacy cleanup.

### Fixed

- Quarantined unwanted 2026-06-07 Sunday `morning` and `evening` captures with missing calendar metadata.
- Rebuilt/pruned derived analysis and outcome rows so ordinary Study Engine views no longer include those unwanted Sunday captures.

### Safety

- Legacy cleanup does not mutate raw captures in place.
- Legacy cleanup preserves valid active `preopen` captures.
- Legacy cleanup prunes existing outcome rows to active analysis identities without fetching current market data.

### Tests

- Added tests for Sunday legacy cleanup, preopen preservation, derived-row pruning, Study default exclusion, and Replay default hiding behavior.

### Added

- Added Catalyst Cluster Explorer v1 in the Study Engine.
- Added deterministic stored-headline catalyst grouping for earnings beat, guidance raise, analyst actions, AI infrastructure, AI partnership, contract/customer wins, FDA/biotech events, merger/acquisition, sector sympathy, macro-only, weak/vague catalyst, no clear catalyst, and unknown/uncategorized.
- Added catalyst cluster detail view with matching headlines, ticker, capture time, source, timestamp status, article age, freshness label, score, review status, outcome status, max gain/drawdown, and stored URLs.
- Added explicit timestamp handling: missing timestamps remain unknown and future timestamps are excluded with report warnings.
- Added `docs/FUTURE_IDEAS.md`.

### Safety

- Catalyst clusters read active raw captures plus derived stores only.
- Catalyst clusters do not fetch current market data, mutate raw captures, recalculate historical scores, start optimizer work, start broker integration, or perform SQLite migration.

### Tests

- Added tests for stored-data-only catalyst clustering, raw-capture immutability, quarantine exclusion, non-study filtering, missing timestamp behavior, missing outcome warnings, deterministic counts and representative headlines, and future timestamp exclusion.
