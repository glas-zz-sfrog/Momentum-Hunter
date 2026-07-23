# Momentum Hunter Verification Queue

## Purpose

This is the durable list of user-visible changes Steven still needs to inspect. The Roadmap remains the authority for current product position and next work; this file records exact deferred manual checks and their results.

Pending manual verification does not stop unrelated Builder work on clean task branches. It also does not count as Steven acceptance, merge approval, or a manual pass.

## Status Legend

- `AUTOMATED_PASS`: compile, tests, source review, and available Codex-side proof passed.
- `AUTOMATED_FAIL`: Codex-side verification found a defect.
- `MANUAL_PENDING`: Steven has not yet completed the physical operator check.
- `MANUAL_PASS`: Steven completed the listed checks and accepted the behavior.
- `MANUAL_FAIL`: Steven found a defect; record the failed step and create a narrow follow-up.
- `SUPERSEDED`: a later verified change replaced this check.

## Queue Summary

| Task | Automated status | Steven status | Merge state | What Steven is checking |
| --- | --- | --- | --- | --- |
| R026 WPF Phase 12 Clean-Room Integration | `AUTOMATED_PASS` | `MANUAL_PENDING` | Branch-only through implementation `a263311` plus closeout; not pushed or merged | One coherent workstation build covering R013-R025 behavior, responsive pane integration, safety locks, and no rejected icon artwork |
| R012 WPF Chart Readability | `AUTOMATED_PASS` | `MANUAL_PENDING` | Merged and pushed with Steven approval at `69feedf` | Price/time axes, latest OHLCV, candles/wicks/volume, labels, and safety language |
| R012A Momentum Hunter Application Icon | `AUTOMATED_PASS` | `MANUAL_FAIL / SUPERSEDED` | Branch-only at `6f4c26e`; do not merge | Original artwork was recognizable but visually too busy |
| R012B Momentum Hunter Icon Redesign | `AUTOMATED_PASS` | `MANUAL_FAIL` | Branch-only at `37e92c4`; do not merge artwork | White-`M`/teal-arrow replacement was technically sound but failed Steven's visual review |
| R013 WPF Chart Inspection | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Crosshair snapping, inspected UTC/OHLCV, clear/restore behavior, and secondary/floating pane parity |
| R014 WPF Command Palette | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Symbol quick-open, filtering, keyboard/mouse actions, no-match behavior, and toolbar fit |
| Combined R012B/R013/R014 Review | `AUTOMATED_PASS` | `MANUAL_FAIL` | Review-only branch through `271d0ca`; do not merge as a unit | Included R012B icon failed; R013/R014 remain available for separate review |
| R015 WPF Candidate Evidence | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Persisted Why/Research facts, candidate switching, pinned-plan consistency, unavailable states, and safety language |
| R016 WPF Health Diagnostics | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Aggregate/component health, exact summaries/times, unavailable states, usable pane sizing, and read-only safety |
| R017 WPF Replay Context | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Exact replay identity/state/symbol/interval/time, unavailable states, layout fit, and no-mutation safety |
| R018 WPF Research Monitoring | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Lifecycle state, source detail, coverage/cycles/time, warning colors, live updates, and no-control safety |
| R019 WPF Activity Event Disclosure | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Full event evidence, newest-first insertion, state colors, wrapping/scrolling, and no-mutation safety |
| R020 WPF Alert And Outcome Evidence | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Source state/counts, alert/outcome fields, honest unavailable states, tab sizing, and no-recalculation safety |
| R021 WPF Technical Research Evidence | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Source state/counts, breakout signals, studied outcomes, symbol switching, partial evidence, pane sizing, and research-only safety |
| R022 WPF Saved Watchlist Evidence | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Latest saved source/state/counts, persisted row order and fields, missing-time/stale warnings, pane sizing, and read-only safety |
| R023 WPF Daily Workflow Evidence | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Exact workflow source/state/score/counts, next required action, five lights and blockers, responsive pane sizing, and no-action safety |
| R024 WPF Candidate Story Evidence | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Linked symbol, canonical story status/metrics, chronology, capture facts versus later annotations, responsive pane sizing, and no-action safety |
| R025 WPF Research Maturity Evidence | `AUTOMATED_PASS` | `SUPERSEDED` | Source branch preserved; integrated into R026 | Stale/source state, strategy lock, distinct completion denominators, evidence gates, census counts, research questions, responsive pane sizing, and no-action safety |

## R026 - WPF Phase 12 Clean-Room Integration

Branch: `codex/ARGUS-R026-wpf-phase12-clean-room-integration`.

Automated result: `AUTOMATED_PASS`

- R026 begins at synchronized `master` commit `69feedf` and integrates one implementation commit from each R013 through R025 source branch. Its implementation stack is 13 commits ahead of `master` through `a263311`.
- Shared host and shell changes are reconciled rather than overwritten: schema-v2 alert evidence remains intact, Technical Research and Candidate Story refresh concurrently, legacy layouts migrate through schema 7, and every optional pane has one registry identity.
- Python compileall passed. The bounded integrated Python suite passed 115/115. Release compilation passed with 0 warnings and 0 errors. The complete .NET solution passed 194/194.
- The packaged host advertises and accepts persisted workspace, chart, technical research, saved watchlist, Daily Workflow, Candidate Story, Research Maturity, and FakeBroker-only simulation capabilities. No Paper, Live, credential, API-key, provider-fetch, or real-order command exists.
- Real packaged results include 14 candidates; CRWV chart `STALE`; 124 technical events and 124 studies; 3 saved-watchlist rows; 5 Daily Workflow steps; 13 Candidate Story points; and Research Maturity `STALE` with strategy optimization `LOCKED`.
- All 8,982 canonical source-evidence files retained aggregate SHA-256 `F4E1127174FFBE0919563DBDC3A291CA9A17C1F7066639EBED4403727CA7E201` before and after packaged-host verification.
- Protected-path review found no scoring, readiness-semantic, replay-identity, historical-capture-selection, alert-threshold, provider, broker/order, credential, package/dependency, database-schema/migration, or production-configuration change.
- The proof board is `docs/argus-office/reports/releases/ARGUS-R026-wpf-phase12-integration-cli-proof.png`: 1440x5490, 1,037,729 bytes, SHA-256 `9DC43FD30F7F61DA655CE688429928C58E5070EE7370EBF701DDC70A4548FBAB`, nonblank, and visually inspected.
- The isolated package is `%LOCALAPPDATA%\MomentumHunter\Builds\R026-phase12-integrated-review`. Its launcher is `Launch R026 Phase 12 Integrated Review.lnk`; it uses isolated layout/settings plus the R026 Python host and a read-only junction to canonical evidence.
- R026 deliberately excludes both rejected icon implementations. The current generic executable/shortcut icon is known and is not the R026 acceptance target; R012C remains a separate visual-identity decision.
- The package does not replace the pinned taskbar shortcut. Nothing was pushed or merged.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. In any currently running Momentum Hunter window, choose `Menu`, then the explicit `Exit Momentum Hunter` command. Closing only the window may leave an older single-instance process running.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R026-phase12-integrated-review\Launch R026 Phase 12 Integrated Review.lnk`. Do not use the pinned taskbar shortcut for this isolated review.
3. Confirm the title is `Momentum Hunter Workstation` and the top environment label says `SIMULATION` / `Python FakeBroker Only`. There must be no Paper, Live-broker, credential, or real-order mode control.
4. Press `Ctrl+K`. Confirm the centered Command Palette opens, lists `Add chart`, `Toggle activity`, `View diagnostics`, and candidate symbols, filters as you type, opens an exact candidate, and closes with `Esc`. Search for a nonsense symbol and confirm the visible no-match state does not change the selected candidate.
5. Select `CRWV` and `5m`. Confirm the chart contains real stored candles, wicks, volume bars, price/time axes, source lineage, a `STALE` label, and the latest UTC/OHLCV strip. No blank or simulated fallback chart is acceptable.
6. Hover different candles. Confirm the crosshair snaps to the nearest chronological candle, the strip changes to that candle's exact UTC/OHLCV facts, leaving the chart restores the latest-bar strip, and opening a second chart preserves the same behavior.
7. In Trade Plan, confirm the badge says `Simulation-only`; Entry, Stop, Target, Reward/Risk, and Risk Governor rows are populated for CRWV. Open `Why` and `Research`; confirm persisted catalyst/readiness/liquidity/quality/lineage/notes appear and candidate switching updates them unless the pane is pinned.
8. Open `Panes` -> `Diagnostics`. Confirm aggregate and component health states, exact summaries, and UTC check times appear; degraded/unavailable states must not be styled as healthy.
9. Switch to `Replay`, open `Replay Events`, and confirm stored replay identity, source state, symbol, interval, as-of time, and summary appear without any capture picker, replay-ID editor, or source-mutation control.
10. Return to `Live`, open `Automation` and `Activity`. Confirm monitoring state/detail/symbol and cycle counts are read-only, while Activity rows show full UTC time, category, symbol or `Workspace`, health state, and wrapped source message in source order.
11. Switch to `Review`, open `Outcomes`, and inspect both tabs. Confirm source state/counts, persisted active/pending alert fields, and recorded outcome fields appear; missing values say unavailable and nothing offers recalculation or outcome mutation.
12. Return to `Live`, select `CRWV`, and open `Research`. Confirm state `STALE`, 124 symbol events, 124 studied outcomes, source labels, warnings, signal rows, outcome rows, and research-only language. Rapid symbol changes must not allow an older response to overwrite the newest symbol.
13. Open `Watchlist`. Confirm `Saved Watchlist Evidence`, state `PARTIAL`, three stored rows in source order, source filename/time, missing-time/stale warnings, and the statement that this is not the active Hunter ranking or an order instruction.
14. Open `Daily Workflow`. Confirm state `STALE`, five ordered lights, exact persisted counts, the blocked `Next Required Action: restore a reviewable current workflow`, and no button that performs a review, plan, report, readiness, provider, or trade action.
15. Open `Candidate Story` with `CRWV` selected. Confirm state `PARTIAL`, status `Fading`, 13 trusted captures, first/latest/peak/score-path facts, chronological rows, separate capture-time facts and later annotations, and no score/readiness/plan/action control.
16. Open `Research Maturity`. Confirm state `STALE`, `STRATEGY OPTIMIZATION LOCKED`, `Allowed now: Collect evidence only`, maturity `100.0%` of scorable alerts, census `50.0%` of all alerts, evidence gate `1 / 25`, 24 needed, and all later research gates locked.
17. Resize the workstation to roughly 1440x900 and then about 1180x820. Confirm toolbar text, cards, tables, tabs, charts, and dock panes remain readable or scrollable with no incoherent overlap or clipped longest words.
18. Close and reopen each optional pane through `Panes`. Confirm one pane returns at a useful size, no duplicate pane is created, and saved/legacy layout restoration does not erase the newer panes.
19. Across all views, confirm there is no provider-refresh, collect-now inside evidence panes, score-change, readiness-change, replay-selection, alert-generation, watchlist-generation, broker, Paper, Live, order, or automated-trading action. The only order-like action is explicitly labeled FakeBroker simulation.
20. Do not judge the generic application icon as an R026 pass/fail item. Confirm only that the rejected target/candlestick and white-`M`/teal-arrow artworks are absent. Final Momentum Hunter icon artwork remains R012C.
21. Report `PASS R026` if checks 1-20 pass. On failure, report the failed step number, selected workspace/symbol/interval, visible state/count, window size, and attach a screenshot.

Passing this checklist proves the integrated R026 user-visible behavior but does not authorize a merge or push.

## R025 - WPF Research Maturity Evidence

Branch: `codex/ARGUS-R025-wpf-research-maturity-evidence`.

Automated result: `AUTOMATED_PASS`

- The Python host adds one separate argument-free Research Maturity snapshot command that reads only the persisted maturity and census JSON reports. It does not regenerate reports, open SQLite, run collection, fetch a provider, recalculate research, or write evidence.
- The projection keeps maturity completion among scorable alerts separate from census completion among all alerts. Missing, malformed, stale, partial, empty, duplicate, inconsistent, or attempted strategy-unlock evidence fails visibly and conservatively.
- Every source gate is safety-validated before the 20-row display limit, every census table count is validated before the 50-row display limit, invalid census payloads contribute neither data nor provenance, and cache callers receive defensive copies.
- Tests cover valid, stale, empty, partial, missing, malformed, wrong-version, inconsistent-count, duplicate-row, invalid-time, hidden-unlock, invalid-optimization, rejected-provenance, source-nonmutation, cache-refresh, host-idempotency, strict .NET mapping, shell-failure, layout-migration, and candidate-independence behavior.
- Python compileall passed; 17 focused and 53 bounded Python tests passed. Release compilation passed with 0 warnings and 0 errors; the full .NET solution passed 99/99.
- The actual host returns `STALE`, maturity `WARN`, census `WARN`, 1/2 total alerts, 1 completed, 0 pending, 1 unscorable, 100.0% completion among scorable alerts, and 50.0% completion among all alerts.
- The current evidence gate is 1/25 with 24 more completed outcomes needed. Sample confidence is `COLLECTING_ONLY`, measurable edge is `INSUFFICIENT_SAMPLE`, strategy optimization is `LOCKED`, and the only allowed action is `Collect evidence only`.
- The actual census returns 41 captures, 675 candidate rows, 710 minute bars across 1 symbol, 14 evidence runs, 380 evidence metrics, 17 candidate reviews, 8 watchlist items, 27 entry plans, 0 complete plans, and 27 incomplete plans.
- The real maturity and census sources retained SHA-256 `D38560B17CE9EDCED8ACBD8FDF3D5DA8260A4E1D291E01DF0EE73ED69B089F3C` and `3F571392162E370586A38D34D9605B405A08D65DD4A1B8C57992B6254644D80E` before and after projection.
- The nonblank 1440x1740 combined 1440/1180 viewport proof is `docs/argus-office/reports/releases/ARGUS-R025-wpf-research-maturity-evidence-cli-proof.png`. The exact pane remains readable at both widths with no clipped evidence-gate columns.
- The isolated build and launcher are under `%LOCALAPPDATA%\MomentumHunter\Builds\R025-research-maturity-evidence`. It uses isolated layout/settings plus the branch Python host and a read-only junction to canonical local evidence; it does not replace the pinned taskbar shortcut.
- Protected-path review found no research-calculation, scoring, readiness-semantic, replay-identity, historical-capture-selection, provider, alert, trade-planning, simulation, broker/order, credential, package-dependency, database-schema, migration, or production-configuration change.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. In any currently running Momentum Hunter window, use `Menu`, then the explicit `Exit` command. Closing only the window may leave an older single-instance process or Python host alive.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R025-research-maturity-evidence\Launch R025 Research Maturity Review.lnk`. Do not use the pinned taskbar shortcut for this isolated branch check.
3. Confirm the top environment says `SIMULATION` / `Python FakeBroker Only` and that no Paper, Live, broker, real-order, credential, or automated-trading control appears.
4. Click `Panes`, then open `Research Maturity`. Confirm one large dedicated bottom pane opens; it should be hidden by default and must not replace the existing symbol-specific Research pane.
5. Confirm the upper-right state is `STALE`, not green/available, and the source date is June 27, 2026. A newer legitimate report may change this date/state, but the source label must still name the persisted maturity and census reports.
6. Confirm the amber lock banner says `STRATEGY OPTIMIZATION LOCKED` and the adjacent action says `Allowed now: Collect evidence only`. Nothing may imply that strategy changes, recommendations, Paper, or Live are allowed.
7. Confirm the four summary cards keep these concepts distinct: maturity completion, census completion, evidence gate, and strategy status. No card should overlap, clip, or silently merge the two completion denominators.
8. With the unchanged evidence, confirm maturity completion is `100.0%` for `1 / 1 scorable alerts`, while census completion is `50.0%` for `1 / 2 all alerts`. This distinction is the most important semantic check.
9. Confirm the evidence gate is `1 / 25`, says `24 needed`, sample confidence is `COLLECTING_ONLY`, and measurable edge is `INSUFFICIENT_SAMPLE`.
10. On `Evidence Gates`, confirm exactly four rows appear in this order: `Collect Evidence` `UNLOCKED` at 1/0 with 0 needed; `Identify Patterns` `LOCKED` at 1/25 with 24 needed; `Recommend Investigations` `LOCKED` at 1/50 with 49 needed; and `Strategy Modification Review` `LOCKED` at 1/100 with 99 needed.
11. Confirm every gate's strategy-change value is false/no and no gate row is presented as trade approval.
12. On `Census Counts`, confirm the major persisted counts are 41 captures, 675 candidate rows, 710 minute bars, 1 minute-bar symbol, 14 evidence runs, 380 metrics, 17 candidate reviews, 8 watchlist items, 27 plans, 0 complete plans, and 27 incomplete plans.
13. On `Research Questions`, confirm every answer begins `NOT_YET`, including alerts predictive, alert types, symbols, readiness states, and system edge. Nothing should claim an edge from the present sample.
14. Expand warnings and safety notes. Confirm they remain readable, explicitly describe insufficient evidence/stale data, and do not contain `Buy`, `Sell`, `Guaranteed edge`, or `Strategy should change`.
15. Select several Hunter symbols rapidly. Confirm Research Maturity does not change symbol, clear, reload into a candidate-specific state, or imply that its aggregate evidence belongs to the selected symbol.
16. Resize the workstation to roughly 1440x900 and then about 1180x820. Confirm cards wrap cleanly, all table columns remain readable or horizontally scrollable, tab content remains vertically reachable, and no text overlaps.
17. Close Research Maturity and reopen it through `Panes`. Confirm exactly one pane returns at a usable review height and no duplicate pane is created.
18. Confirm the Research Maturity pane contains no collect, refresh, optimize, recommend, edit, save, score, readiness-change, provider, planning, simulation, broker, Paper, Live, order, or automatic-trading button.
19. Report `PASS R025` if all eighteen behavioral checks pass. On failure, report the failed step number, visible state/count, selected tab, window size, and attach a screenshot.

Passing this checklist proves the R025 user-visible behavior but does not authorize a merge or push.

## R024 - WPF Candidate Story Evidence

Branch: `codex/ARGUS-R024-wpf-candidate-story-evidence`.

Automated result: `AUTOMATED_PASS`

- The Python host adds one separate symbol-scoped Candidate Story snapshot command that reuses the canonical trusted replay timeline and `build_candidate_story_summary`; it does not run collection, fetch providers, select a different historical capture, recalculate a score/readiness gate, or write evidence.
- The projection excludes quarantined and ordinary non-trading-day rows, keeps capture-time facts separate from later review/outcome annotations, preserves full counts, bounds display detail to the latest 100 chronological points, caches only while source fingerprints remain unchanged, and returns deep copies.
- Tests cover canonical Candidate Story status preservation, empty and single-capture states, missing mixed-time rows, ordinary non-trading-day exclusion, bounded chronology, cache invalidation, caller mutation, source nonmutation, invalid/path-like symbols, host idempotency, strict schema/count/provenance/identity validation, duplicate IDs, stale asynchronous responses, shell failure isolation, legacy-layout migration, link propagation, and absence of product action buttons.
- Python compileall passed; 32 focused and 75 bounded Python tests passed. Release compilation passed with 0 warnings and 0 errors; the full .NET solution passed 101/101.
- All 76 actual capture/manifest/score/review/outcome source files retained aggregate SHA-256 `FAB0731CB65A2ED5955BDA162B2CCB1F4377E1A44466C77F3B26D78E411CABF5` before and after projection and UI proof.
- The current canonical CRWV source returns `PARTIAL`, `Fading`, 13 trusted/displayed points, first `$100.55`, latest `$90.00`, move `-10.5%`, score `76 -> 69`, and peak score `83`. The packaged branch host reproduces the same state/count.
- The nonblank 1440x2000 combined two-viewport proof is `docs/argus-office/reports/releases/ARGUS-R024-wpf-candidate-story-evidence-cli-proof.png`. The legacy-layout harness recreated the dedicated pane at 520 pixels; at 1440 and 1100 pixels the story, table, source, read-only language, and warnings remain visible/reachable.
- Visual-tree inspection found no Candidate Story product command. The only `Button` generated inside the pane is the read-only DataGrid's built-in `Select All` control.
- The isolated build and launcher are under `%LOCALAPPDATA%\MomentumHunter\Builds\R024-candidate-story-evidence`. It uses isolated layout/settings plus the branch Python host and a read-only junction to canonical local evidence; it does not replace the pinned taskbar shortcut.
- Protected-path review found no scoring, readiness-semantic, replay-identity, historical-capture-selection, provider, alert, trade-planning, simulation, broker/order, credential, package-dependency, database-schema, migration, or production-configuration change.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. In any currently running Momentum Hunter window, use `Menu`, then the explicit `Exit` command. Closing only the window may leave an older single-instance process or Python host alive.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R024-candidate-story-evidence\Launch R024 Candidate Story Review.lnk`. Do not use the pinned taskbar shortcut for this isolated branch check.
3. Confirm the top environment says `SIMULATION` / `FakeBroker` only and that no Paper, Live, broker, real-order, credential, or automated-trading control appears.
4. Click `Panes`, then open `Candidate Story`. Confirm it opens as a large dedicated bottom pane rather than the compact Activity strip.
5. Select `CRWV` in Hunter. Confirm both the pane header and selected Hunter row say `CRWV`; the pane must not retain another symbol.
6. With unchanged canonical evidence, confirm the pane says `PARTIAL`, status `Fading`, company context `CoreWeave Inc | Technology | Software - Infrastructure`, and `13 trusted captures`. If legitimate persisted evidence changed, record the new values and verify that the pane still labels the source/state honestly.
7. With unchanged evidence, confirm First Seen is `Jun 12, 2026 7:00 PM CT | $100.55`, Latest is `Jul 9, 2026 7:00 AM CT | $90.00`, Move is `-10.5%`, Score Path is `76 -> 69`, and Peak Score is `83 | Jun 30, 2026 7:00 PM CT`.
8. Confirm the timeline runs oldest to newest, sequence numbers are contiguous, and the visible table has Captured At, Session, Price, Score, Move From First, RVOL, Capture-Time Fact, Later Annotation, Source Context, and Trust columns.
9. Compare at least two rows. Confirm `Capture-Time Fact` describes only what was known at capture time, while `Later Annotation` is explicitly labeled as a later review/outcome such as `Post-capture outcome: complete`; the two must not be blended into one claim.
10. Confirm source and trust language is visible below the table, the footer says `READ ONLY`, legacy zero/missing RVOL is displayed as `n/a` rather than `0.0`, and warnings remain amber and scrollable.
11. Select a second symbol, then return to `CRWV`. Confirm the header, metrics, rows, and warnings all change together; an empty/partial second symbol must show that state instead of retaining CRWV facts.
12. Switch rapidly between two or three Hunter symbols and stop on one. Wait several seconds and confirm a slower response for an older selection never overwrites the final selected symbol.
13. Resize the workstation to roughly 1440x900 and then about 1100x900. Confirm the Candidate Story cards wrap, the timeline remains horizontally/vertically scrollable, source/warning text remains reachable, and text does not overlap.
14. Close Candidate Story and reopen it through `Panes`. Confirm exactly one pane returns at a usable review height and no duplicate pane is created.
15. Confirm the Candidate Story pane itself contains no edit, review, save, score, readiness-change, provider-refresh, planning, simulation, broker, Paper, Live, order, or automatic-trading command. The small DataGrid Select All corner is a table-selection affordance only.
16. Report `PASS R024` if all fifteen behavioral checks pass. On failure, report the failed step number, selected symbol, state/status/count, window size, and attach a screenshot.

Passing this checklist proves the R024 user-visible behavior but does not authorize a merge or push.

## R023 - WPF Daily Workflow Evidence

Branch: `codex/ARGUS-R023-wpf-daily-workflow-evidence`.

Automated result: `AUTOMATED_PASS`

- The Python host adds one separate argument-free Daily Workflow snapshot command that reads persisted report, capture-health, review-decision, entry-plan, and outcome-maturity evidence without running collection or any provider.
- The ten existing Daily Workflow trust/next-action/step function bodies are AST-equivalent before and after extraction from `app.py`; the Qt modal and WPF projection use the same guidance.
- Tests cover exact current identity matching, stale/historical blocking, unavailable and partial sources, malformed/duplicate rows, source nonmutation, host idempotency and argument rejection, strict .NET schema/count/state/step validation, shell failure isolation, hidden-pane registration, and candidate-selection independence.
- Python compileall passed; 78 bounded Python tests passed. The legacy `EntryPlanGuiTests` Qt class exceeded its bounded timeout and was terminated with no process left running; its four persistence tests pass, and the nine focused Daily Workflow Qt tests pass.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 95/95.
- All 8,666 actual files in the projection's report/capture/failure/review/plan/outcome source set retained identical SHA-256 hashes before and after projection.
- The current canonical source returns `STALE`, `HISTORICAL_READ_ONLY`, workflow discipline 54%, reviews 0/14, no watchlist plans, outcomes 949 next-day / 912 five-day / 38 pending, a blocked restore-current-evidence action, and five ordered steps.
- Protected-path review found no scoring, readiness-semantic, replay-identity, historical-capture-selection, watchlist-generation, provider, alert, trade-planning, broker/order, credential, package, database-schema, migration, or production-configuration change.
- The nonblank 1440x1800 two-viewport proof is `docs/argus-office/reports/releases/ARGUS-R023-wpf-daily-workflow-evidence-cli-proof.png`. At 1440 pixels all five cards are visible; at 1100 pixels they wrap and remain reachable by vertical scrolling.
- The isolated build and launcher are under `%LOCALAPPDATA%\MomentumHunter\Builds\R023-daily-workflow-evidence`. It uses isolated layout/settings plus the branch Python host and a read-only junction to canonical local evidence; it does not replace the pinned taskbar shortcut.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. In any currently running Momentum Hunter window, use `Menu`, then the explicit `Exit` command. Closing only the window may leave an older single-instance process or Python host alive.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R023-daily-workflow-evidence\Launch R023 Daily Workflow Review.lnk`. Do not use the pinned taskbar shortcut for this isolated branch check.
3. Confirm the top environment says `SIMULATION` / `FakeBroker` only and that no Paper, Live, broker, real-order, or credential control appears.
4. Click `Panes`, then open `Daily Workflow`. Confirm it opens as a large dedicated bottom pane rather than the compact Activity strip.
5. Confirm the pane identifies the persisted source and exact capture context. With the current source, expect `event-trade-plan-briefing-2026-06-17-morning.json` and `2026-06-17 / morning / finviz / Institutional Momentum`. If legitimate newer evidence exists, report its filename/context instead of treating that alone as failure.
6. Confirm the current evidence is visibly `STALE`, says workflow discipline `54%`, and shows a source-as-of time. It must not look current, healthy, or approved.
7. Confirm the summary shows reviews `0/14` with 14 unreviewed, plans `0/0`, outcomes `949` next-day / `912` five-day / `38` pending, and readiness statuses. If canonical evidence changed, record the new exact values and confirm the labels remain truthful.
8. Confirm the amber next-action band says `Next Required Action: restore a reviewable current workflow` and explains that historical evidence cannot satisfy today's flow.
9. Read all five cards in order: `Capture Health`, `Morning Review`, `Watchlist Plans`, `Watchlist Report`, `Readiness Gate`. Confirm each has one light, status, dependency, blocker, and detail; the current lights should be red, gray, gray, gray, green.
10. Confirm the green Readiness Gate says availability is not approval or a trade instruction, while the blocked upstream workflow remains visibly blocked.
11. Expand `Warnings`. Confirm stale source, incomplete reviews, capture failure, and do-not-use-for-trading language are visible and do not overlap.
12. Resize to roughly 1440x900 and then about 1100x900. At 1440, confirm five cards fit on one row; at 1100, confirm they wrap into two rows, remain reachable by vertical scrolling, and text does not clip or overlap.
13. Select another Hunter candidate and change chart intervals. Confirm the Daily Workflow source, counts, and steps do not change because this pane represents one persisted workflow, not the selected chart candidate.
14. Close and reopen Daily Workflow through `Panes`. Confirm one pane returns at a usable review height and no duplicate pane is created.
15. Confirm the Daily Workflow pane itself contains no review, save-plan, generate-report, refresh-provider, score, readiness-change, watchlist, alert, simulation, broker, Paper, Live, order, or automatic-trading button.
16. Report `PASS R023` if all fifteen behavioral checks pass. On failure, report the failed step number, source filename, state/score/counts, window size, and attach a screenshot.

Passing this checklist proves the R023 user-visible behavior but does not authorize a merge or push.

## R022 - WPF Saved Watchlist Evidence

Branch: `codex/ARGUS-R022-wpf-saved-watchlist-evidence`.

Automated result: `AUTOMATED_PASS`

- The Python host adds one separate read-only saved-watchlist command backed only by the newest exact `watchlist-YYYY-MM-DD.json` persisted artifact.
- Tests prove exact-filename selection, source-order preservation, stored-value/null handling, 100-row display cap with full counts, `AVAILABLE`/`STALE`/`PARTIAL`/`EMPTY`/`UNAVAILABLE` states, invalid source rejection, duplicate/missing identity warnings, source cache refresh, source nonmutation, host idempotency/no-collection behavior, strict mapper validation, explicit presentation fallbacks, and shell failure isolation.
- Python compileall passed; 63 bounded watchlist/host/storage/read-model/chart/trade-planning regressions passed.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 98/98.
- The actual 14,507-byte `watchlist-2026-06-18.json` retained SHA-256 `6F19E86AF2B189D3560DB9CCCB6A0725754B74CE598AD7A6105017D5BBD2E8C8` before and after projection. It returns `PARTIAL`, 3 stored/usable/displayed rows, source order `NAVN`, `FRMI`, `HOOD`, one missing save timestamp, and a separate stale warning.
- Protected-path review found no watchlist generation, scoring, readiness, replay, historical-capture selection, provider, alert, trade-planning, broker/order, credential, package, database-schema, migration, or production-configuration change.
- The 1440x1800 two-viewport proof is `docs/argus-office/reports/releases/ARGUS-R022-wpf-saved-watchlist-evidence-cli-proof.png`.
- The isolated build and review launcher are under `%LOCALAPPDATA%\MomentumHunter\Builds\R022-saved-watchlist-evidence`. The launcher pairs the branch WPF code with its packaged branch Python host and a read-only junction to canonical local data; it does not change the canonical taskbar shortcut.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. In any currently running Momentum Hunter window, use `Menu`, then the explicit `Exit` command so the fixed single-instance guard cannot redirect the review launch to an older build.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R022-saved-watchlist-evidence\Launch R022 Saved Watchlist Review.lnk`. Do not use the pinned taskbar shortcut for this isolated branch check.
3. Confirm the top environment remains `SIMULATION` / `FakeBroker` only and that no Paper, Live, broker, or real-order control appears.
4. Click `Panes`, then open `Watchlist`. Confirm the pane heading says `Saved Watchlist Evidence`, with a compact `PARTIAL` badge and source `watchlist-2026-06-18.json`.
5. Confirm the pane reports `3 displayed | 3 usable | 3 stored` and rows appear in exact order `#1 NAVN`, `#2 FRMI`, `#3 HOOD`. If the canonical saved source has legitimately changed, report the newer filename, counts, and order rather than treating that alone as a failure.
6. Inspect the rows. Confirm they disclose stored score, price/change, volume/RVOL, sector/industry, freshness, save time, headline, and operator-note fallback without claiming any field is current.
7. Confirm FRMI says `Saved time unavailable` while remaining visible, and the warning band reports both one missing `saved_at` timestamp and that the saved artifact is older than 36 hours.
8. Confirm the pane says it is a read-only historical artifact and not the active Hunter ranking, approval state, TradePlan, alert, or order instruction.
9. Confirm there is no edit, remove, promote, regenerate, provider-fetch, score, alert, TradePlan, broker, Paper, Live, order, or automatic-trading action in the Watchlist pane.
10. Resize the workstation to roughly 1440x900 and then about 1100x900. Confirm the header wraps, rows remain readable, the list scrolls, and the pane does not overlap Hunter, Chart, or Trade Plan.
11. Select different Hunter candidates and change chart intervals. Confirm the saved rows and their source order do not change, because this artifact is independent of the active candidate and chart context.
12. Report `PASS R022` if all eleven behavioral checks pass. On failure, report the failed step number, source filename, state/counts, window size, and attach a screenshot.

Passing this checklist proves the R022 user-visible behavior but does not authorize a merge or push.

## R021 - WPF Technical Research Evidence

Branch: `codex/ARGUS-R021-wpf-technical-research-evidence`.

Automated result: `AUTOMATED_PASS`

- The Python host adds one separate read-only technical-research command backed only by existing persisted breakout-event and outcome-study JSON reports.
- Tests prove schema and research-only marker validation, `AVAILABLE`/`STALE`/`PARTIAL`/`EMPTY`/`UNAVAILABLE` states, missing and one-sided evidence, full counts with 50-row display caps, source cache refresh, source nonmutation, symbol normalization, host idempotency, mapper failures, shell failure states, and out-of-order selection protection.
- Broader breakout/service/host Python tests passed 45/45.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 103/103; Python compileall passed.
- The actual 24,457,699-byte event report and 17,039,613-byte study report retained identical SHA-256 hashes before and after projection. CRWV returned 124 events and 124 studies with 50 newest rows per tab; an unknown symbol returned honest `EMPTY` text that explicitly does not mean “breakout absent.”
- Protected-path review found no breakout-calculation, generated-report, scoring, readiness, alert, replay, capture-selection, provider, trade-planning, broker/order, credential, package, database-schema, migration, or production-configuration change.
- The 1440x1800 two-viewport proof is `docs/argus-office/reports/releases/ARGUS-R021-wpf-technical-research-evidence-cli-proof.png`.
- The isolated build and review launcher are under `%LOCALAPPDATA%\MomentumHunter\Builds\R021-technical-research-evidence`. The launcher intentionally pairs the branch WPF code with the branch Python host; it does not change the canonical taskbar shortcut.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. In any currently running Momentum Hunter window, use `Menu`, then the explicit `Exit` command. Closing only the window may leave the old Python host alive, which would not contain R021.
2. Open `%LOCALAPPDATA%\MomentumHunter\Builds\R021-technical-research-evidence\Launch R021 Technical Research Review.lnk`. Do not use the pinned taskbar shortcut for this isolated branch check.
3. Click `Panes`, then open `Research`. Confirm the pane heading says `Technical Research` followed by the currently selected symbol and that a compact state badge appears.
4. Select `CRWV`. Confirm the current stored reports show `STALE`, source time `2026-07-05`, 124 symbol events, 124 studied outcomes, and the explicit research-only/no-change statement. These exact counts apply to the current July 5 reports; report any newer legitimate source time/counts instead of treating them as a failure.
5. On `Signals`, inspect several rows. Confirm each visible row identifies UTC date/time, signal type, timeframe, stored status, quality, event ID, trigger/distance/RVOL, volume and relative-strength confirmation, and stored notes. Missing values must say unavailable.
6. Open `Outcome Studies`. Confirm rows show stored status, event ID, available forward returns, MFE/MAE, held/failed/extended/volume flags, and notes. A row without forward bars must say `Forward returns unavailable`; it must not invent zero returns.
7. Select `SPCX`. With the current reports it should show `PARTIAL`, 1 event, and 0 studied outcomes. Confirm the Signals row remains visible and Outcome Studies explains that the evidence is partial or unavailable rather than saying the breakout failed.
8. Switch quickly among `CRWV`, `EQX`, and `JPM`. Confirm the heading and rows always finish on the newest selected symbol; an older response must not overwrite it.
9. Resize the workstation to roughly 1440x900 and then about 1100x900. Confirm the header metadata wraps, both tabs remain reachable, rows scroll, and the Research pane does not overlap Hunter, Chart, or Trade Plan.
10. Close and reopen Research through `Panes`. Confirm one pane returns and merely viewing or switching tabs does not change source counts, candidate score/readiness, or Trade Plan evidence.
11. Confirm Research contains no regenerate-report, provider-fetch, score, alert, watchlist, trade-plan, broker, Paper, Live, order, or automatic-trading action.
12. Report `PASS R021` if all eleven behavioral checks pass. On failure, report the failed step number, selected symbol, state/counts, selected tab, window size, and attach a screenshot.

Passing this checklist proves the R021 user-visible behavior but does not authorize a merge or push.

## Combined R012B/R013/R014 Review

Branch: `codex/ARGUS-REVIEW-R012B-R014-combined-ui`.

Automated result: `AUTOMATED_PASS`

- The three preserved implementation commits integrated without manual conflict resolution.
- Focused chart/palette tests passed 25/25 and the icon contract passed 1/1.
- Release compilation passed with 0 warnings and 0 errors.
- The combined .NET suite passed 106/106.
- Protected-path review found no scoring, readiness, replay, capture, provider, alert, broker/order, credential, package, schema, migration, or production-configuration change.
- The combined proof board is `docs/argus-office/reports/releases/ARGUS-REVIEW-R012B-R014-combined-ui-proof.png`.
- The pinned taskbar and Start Menu shortcuts target `%LOCALAPPDATA%\MomentumHunter\Builds\Combined-R012B-R014-28c4154\MomentumHunter.Desktop.Wpf.exe`.
- The previously published R012A, R012B, and R014 directories remain intact as rollback evidence.

Steven status: `MANUAL_FAIL`

Steven rejected the displayed white-`M`/teal-arrow icon. The combined branch therefore cannot pass or merge as a unit. Its automated R013 chart-inspection and R014 command-palette evidence remains valid, but those features must be reviewed and integrated independently from a future R012C icon replacement.

## R018 - WPF Research Monitoring Status

Branch: `codex/ARGUS-R018-wpf-monitoring-status`.

Automated result: `AUTOMATED_PASS`

- The presentation projection uses only the existing `BackgroundCollectionStatus`; no background-service or provider contract changed.
- Tests prove starting, healthy, degraded, paused, blocked, and stopping states; singular/plural counts; UTC conversion; source-detail preservation; and shell property notifications.
- Focused presentation and lifecycle integration tests passed 33/33.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 95/95; Python compileall passed.
- Protected-path review found no monitoring command, provider, scoring, readiness, replay, capture-selection, alert, broker/order, credential, package, schema, migration, or production-configuration change.
- The 1440x1740 degraded-state proof is `docs/argus-office/reports/releases/ARGUS-R018-wpf-monitoring-status-cli-proof.png`.
- The isolated build is `%LOCALAPPDATA%\MomentumHunter\Builds\R018-monitoring-status\MomentumHunter.Desktop.Wpf.exe`. It is based on canonical `master` and intentionally does not contain pending R012B/R013/R014/R015/R016/R017 changes.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Close any currently running Momentum Hunter window normally so the single-instance guard does not redirect this launch to another review build.
2. Launch `%LOCALAPPDATA%\MomentumHunter\Builds\R018-monitoring-status\MomentumHunter.Desktop.Wpf.exe` directly. Do not use the pinned combined-review shortcut for this separate check.
3. Click `Panes`, then open `Automation`. Confirm the pane heading says `Research Monitoring` and its state matches the top monitoring label.
4. Confirm the pane shows an operator summary, monitored-symbol count, completed-cycle count, and last completed scan in UTC. If source detail exists, confirm it appears beneath the summary.
5. Pause or resume monitoring using the existing top/tray control. Confirm the pane changes to `PAUSED` or the returned runtime state without creating a second pane or changing any candidate.
6. If monitoring reports `DEGRADED` or `BLOCKED`, confirm the badge is amber/red rather than healthy teal and that source detail remains visible. Do not expect Codex's proof fixture text on your live data.
7. Resize the workstation to roughly 1440x900 and then about 1100x820. Confirm all facts and the read-only safety line remain visible, text wraps when needed, and neighboring panes do not overlap.
8. Close and reopen Automation through `Panes`. Confirm the existing pane toggle works and no duplicate pane is created.
9. Confirm the pane itself contains no pause/resume, scan-now, scheduler, provider, credential, broker, Paper, Live, order, or automatic-trading control.
10. Report `PASS R018` if all nine behavioral checks pass. On failure, report the step number, top monitoring label, pane state/counts/time, window size, and attach a screenshot.

Passing this checklist proves the R018 user-visible behavior but does not authorize a merge or push.

## R019 - WPF Activity Event Disclosure

Branch: `codex/ARGUS-R019-wpf-activity-events`.

Automated result: `AUTOMATED_PASS`

- The presentation projection uses only existing `ActivityEvent` fields and preserves the collection's existing order.
- Tests prove full UTC conversion, exact category/message/scope/state display, explicit blank-field fallbacks, source-order preservation, monitoring-event insertion, simulation-event insertion, retained prior rows, and property notifications.
- Focused activity/read-only/lifecycle tests passed 31/31.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 93/93; Python compileall passed.
- Protected-path review found no event-producer, monitoring-command, simulation-engine, provider, scoring, readiness, replay, capture-selection, alert, broker/order, credential, package, schema, migration, or production-configuration change.
- The 1440x1740 two-viewport proof is `docs/argus-office/reports/releases/ARGUS-R019-wpf-activity-events-cli-proof.png`.
- The isolated build is `%LOCALAPPDATA%\MomentumHunter\Builds\R019-activity-events\MomentumHunter.Desktop.Wpf.exe`. It is based on canonical `master` and intentionally does not contain pending R012B/R013/R014/R015/R016/R017/R018 changes.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Close any currently running Momentum Hunter window normally so the single-instance guard does not redirect this launch to another review build.
2. Launch `%LOCALAPPDATA%\MomentumHunter\Builds\R019-activity-events\MomentumHunter.Desktop.Wpf.exe` directly. Do not use the pinned combined-review shortcut for this separate check.
3. Click the top `Activity` button. If that button is outside the visible toolbar at a narrow width, click `Panes`, then open `Activity`.
4. Confirm the right side says how many source events exist and identifies Activity as local to this shell.
5. For each visible row, confirm there is a full date/time ending in `UTC`, a category, a symbol or `Workspace` scope, a state, and a readable message.
6. Confirm `HEALTHY` is teal, `DEGRADED` is amber, and `UNAVAILABLE` is red/pink. A missing symbol must say `Workspace`; it must not invent a ticker.
7. Use an existing monitoring action or the existing FakeBroker-only simulation action. Reopen Activity if needed and confirm the resulting source event appears first while all prior rows remain in their previous order.
8. Resize the workstation to roughly 1440x900 and then about 1100x820. Confirm messages wrap, the event list scrolls, every row remains reachable, and the Activity pane does not overlap its source-count panel.
9. Close and reopen Activity through `Panes`. Confirm the existing pane toggle works and no duplicate pane or duplicate event is created merely by viewing it.
10. Confirm Activity contains no edit, delete, reorder, filter, persistence, provider, credential, broker, Paper, Live, order, or automatic-trading control.
11. Report `PASS R019` if all ten behavioral checks pass. On failure, report the failed step number, event count, visible row fields, window size, and attach a screenshot.

Passing this checklist proves the R019 user-visible behavior but does not authorize a merge or push.

## R020 - WPF Alert And Outcome Evidence

Branch: `codex/ARGUS-R020-wpf-alert-outcome-evidence`.

Automated result: `AUTOMATED_PASS`

- Schema-v2 `alertEvidence` reads only the existing persisted opportunity-alert store and exposes separate `AVAILABLE`, `EMPTY`, and `UNAVAILABLE` source states.
- Full-store counts remain separate from bounded detail: newest 50 active/pending rows and newest 100 recorded outcomes.
- Tests prove exact stored alert/outcome mapping, newest-valid-time ordering, malformed/missing timestamps, missing and duplicate IDs, empty/malformed stores, full-count row caps, schema-v1 compatibility, unsupported-schema rejection, negative-count clamping, source-byte integrity, shell unavailable behavior, and no candidate score/readiness recalculation.
- Nearby Python alert/read-model/host/simulation tests passed 53/53.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 96/96; Python compileall passed.
- Bounded repository-wide Python unittest discovery ran for five minutes without completing. It was terminated cleanly, left no test process running, and is not reported as a pass.
- Protected-path review found no alert-generation, threshold, outcome-classification, scoring, readiness, replay, capture-selection, provider, broker/order, credential, package, database-schema, migration, or production-configuration change.
- The 1440x1740 two-viewport proof is `docs/argus-office/reports/releases/ARGUS-R020-wpf-alert-outcome-evidence-cli-proof.png`.
- The isolated build is `%LOCALAPPDATA%\MomentumHunter\Builds\R020-alert-outcome-evidence\MomentumHunter.Desktop.Wpf.exe`. It is based on canonical `master` and intentionally does not contain pending R012B/R013/R014/R015/R016/R017/R018/R019 changes.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Close any currently running Momentum Hunter window normally so the single-instance guard does not redirect this launch to another review build.
2. Launch `%LOCALAPPDATA%\MomentumHunter\Builds\R020-alert-outcome-evidence\MomentumHunter.Desktop.Wpf.exe` directly. Do not use the pinned combined-review shortcut for this separate check.
3. Click `Review` in the top workspace selector. Click `Panes`, then reopen `Outcomes`.
4. Confirm the pane expands to a usable height and says `Alert Evidence & Outcomes`.
5. Confirm the header shows `AVAILABLE`, `EMPTY`, or `UNAVAILABLE`, a clearly labeled source/check UTC time, full-store counts, and a source summary. Your live data may legitimately be empty or unavailable; do not expect Codex's proof-fixture counts.
6. Open `Active / Pending`. For every visible row, confirm alert time or `Time unavailable`, symbol, alert type, stored state, alert ID or `ID unavailable`, and a readable stored reason.
7. Open `Recorded Outcomes`. For every visible row, confirm source alert time or `Alert time unavailable`, symbol, stored status, stored classification, alert ID or `ID unavailable`, and any persisted return/target/stop details.
8. If the header says `EMPTY`, confirm both tabs show honest no-data messages. If it says `UNAVAILABLE`, confirm both tabs say evidence is unavailable and no rows are invented.
9. Resize the workstation to roughly 1440x900 and then about 1100x820. Confirm the pane remains usable, metadata wraps, rows scroll, classifications remain readable, and neighboring panes do not overlap.
10. Close and reopen Outcomes through `Panes`. Confirm one pane returns, no duplicate row appears merely from viewing it, and the displayed counts do not change because of tab switching.
11. Confirm there is no create-alert, update-outcome, classify, threshold, refresh-provider, edit, delete, broker, Paper, Live, order, or automatic-trading control.
12. Report `PASS R020` if all eleven behavioral checks pass. On failure, report the failed step number, workspace, source state/counts, selected tab, window size, and attach a screenshot.

Passing this checklist proves the R020 user-visible behavior but does not authorize a merge or push.

## R017 - WPF Replay Context Disclosure

Branch: `codex/ARGUS-R017-wpf-replay-context`.

Automated result: `AUTOMATED_PASS`

- The presentation projection uses only the existing read-only `ReplaySnapshot`; it does not calculate or alter replay identity.
- Tests prove null, `NOT_SELECTED`, `UNAVAILABLE`, available, blank-field, exact identity, UTC-conversion, and shell-notification behavior.
- Focused replay/read-only/simulation-boundary tests passed 14/14.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 93/93; Python compileall passed.
- Protected-path review found no replay-identity, historical-capture-selection, scoring, readiness, provider, alert, broker/order, credential, package, schema, migration, or production-configuration change.
- The 1440x1740 two-viewport proof is `docs/argus-office/reports/releases/ARGUS-R017-wpf-replay-context-cli-proof.png`.
- The isolated build is `%LOCALAPPDATA%\MomentumHunter\Builds\R017-replay-context\MomentumHunter.Desktop.Wpf.exe`. It is based on canonical `master` and intentionally does not contain pending R012B/R013/R014/R015/R016 changes.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Close any currently running Momentum Hunter window normally so the single-instance guard does not redirect this launch to another review build.
2. Launch `%LOCALAPPDATA%\MomentumHunter\Builds\R017-replay-context\MomentumHunter.Desktop.Wpf.exe` directly. Do not use the pinned combined-review shortcut for this separate check.
3. Click `Panes`, then open `Replay Events`. Confirm the pane heading says `Replay Context` and a compact source-state badge appears.
4. Confirm the pane shows one replay ID, one UTC as-of time, one symbol, one interval, and one source summary. Check that no field is duplicated or clipped.
5. Compare the displayed symbol and interval with the current replay context. Confirm the pane does not pretend that changing the current Hunter selection created a new replay identity.
6. If the source has no selected replay, confirm the badge says `NOT SELECTED`; if the source is unavailable, confirm it says `UNAVAILABLE`. Neither state may appear green or invent an ID.
7. Resize the workstation to roughly 1440x900 and then about 1100x820. Confirm all facts and the read-only safety line remain visible, text wraps when needed, and neighboring panes do not overlap.
8. Close and reopen Replay Events through `Panes`. Confirm the existing pane toggle works and no duplicate pane is created.
9. Confirm there is no capture picker, replay-ID editor, refresh-provider, broker, Paper, Live, order, or execution control. Current research and candidate state must not change from opening the pane.
10. Report `PASS R017` if all nine behavioral checks pass. On failure, report the step number, displayed replay state/ID/symbol/interval, window size, and attach a screenshot.

Passing this checklist proves the R017 user-visible behavior but does not authorize a merge or push.

## R016 - WPF Health Diagnostics

Branch: `codex/ARGUS-R016-wpf-health-diagnostics`.

Automated result: `AUTOMATED_PASS`

- The presentation projection uses only the existing read-only `SystemHealthSnapshot`; it does not recalculate or fetch health evidence.
- Tests prove null, empty, healthy, mixed degraded/unavailable, source-order, UTC conversion, fallback-label, and shell-notification behavior.
- Focused health/read-only/simulation-boundary tests passed 10/10.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 93/93; Python compileall passed.
- Protected-path review found no scoring, readiness, replay, capture-selection, provider, alert, broker/order, credential, package, schema, migration, or production-configuration change.
- The 1440x1740 two-viewport proof is `docs/argus-office/reports/releases/ARGUS-R016-wpf-health-diagnostics-cli-proof.png`.
- The isolated build is `%LOCALAPPDATA%\MomentumHunter\Builds\R016-health-diagnostics\MomentumHunter.Desktop.Wpf.exe`. It is based on canonical `master` and intentionally does not include pending R012B/R013/R014/R015 changes.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Close any currently running Momentum Hunter window normally so the single-instance guard does not redirect this launch to another review build.
2. Launch `%LOCALAPPDATA%\MomentumHunter\Builds\R016-health-diagnostics\MomentumHunter.Desktop.Wpf.exe` directly. Do not use the pinned combined-review shortcut for this separate check.
3. Click `Health` in the top toolbar. Confirm the existing health popup still shows its current aggregate status and summary; close it without any background action starting.
4. Click `Panes`, then open `Diagnostics` if it is not already visible. Confirm the bottom pane opens to a usable height and shows an aggregate state badge, component counts, and a snapshot UTC time.
5. Read every diagnostic row. Confirm each row shows a component name, one exact state (`HEALTHY`, `DEGRADED`, or `UNAVAILABLE`), a meaningful source summary, and its own checked UTC time.
6. Confirm a degraded component is amber, an unavailable component is muted, and neither is presented as healthy. If all current source components are healthy, report that actual source state instead of expecting a forced warning.
7. Resize the workstation to roughly 1440x900 and then about 1100x820. Confirm all rows remain reachable by scrolling, the badge stays compact, text does not overlap, and neighboring panes remain usable.
8. Close and reopen Diagnostics through both its pane close control and `Panes`. Confirm the existing toggle remains functional and does not create duplicate panes.
9. Confirm the footer says the evidence is read-only and that the pane exposes no repair, refresh-provider, credential, broker, Paper, Live, order, or execution control.
10. Report `PASS R016` if all nine behavioral checks pass. On failure, report the step number, visible aggregate/component state, window size, and attach a screenshot.

Passing this checklist proves the R016 user-visible behavior but does not authorize a merge or push.

## R015 - WPF Candidate Evidence Disclosure

Branch: `codex/ARGUS-R015-wpf-candidate-evidence`.

Automated result: `AUTOMATED_PASS`

- The Python read-model producer still passes source score/readiness through without recalculation and now has an explicit assertion for the existing `notes` wire field.
- The .NET mapper trims valid persisted notes, drops blank entries, and maps missing notes to an empty collection.
- View-model tests prove selected-candidate evidence changes with selection, partial evidence receives explicit unavailable labels, source score/readiness remain unchanged, and pinned Trade Plan evidence remains attached to the pinned symbol.
- Focused .NET tests passed 5/5; nearby Python read-model/simulation tests passed 10/10.
- Release compilation passed with 0 warnings and 0 errors; the full .NET suite passed 91/91; Python compileall passed.
- Protected-path review found no scoring, readiness, replay, capture selection, provider, alert, broker/order, credential, package, schema, migration, or production-configuration change.
- The 1440x1808 Why/Research proof is `docs/argus-office/reports/releases/ARGUS-R015-wpf-candidate-evidence-cli-proof.png`.
- The isolated build is `%LOCALAPPDATA%\MomentumHunter\Builds\R015-candidate-evidence\MomentumHunter.Desktop.Wpf.exe`. It is based on canonical `master` and intentionally does not include pending R012B/R013/R014 changes.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Close any currently running Momentum Hunter window normally so the single-instance guard does not redirect the launch to another review build.
2. Launch `%LOCALAPPDATA%\MomentumHunter\Builds\R015-candidate-evidence\MomentumHunter.Desktop.Wpf.exe` directly. Do not use the pinned combined-review shortcut for this separate check.
3. Select a candidate with a persisted TradePlan, then open the Trade Plan `Why` tab. Confirm the symbol, catalyst, catalyst source, UTC timestamp, source state, and liquidity are populated from stored evidence.
4. Select a different candidate. Confirm every `Why` value updates to that candidate and no prior symbol's catalyst or liquidity remains.
5. Click `Pin` in Trade Plan, select another Hunter candidate, and confirm the Trade Plan symbol and `Why` evidence remain on the pinned symbol. Click `Pin` again, reselect the new candidate, and confirm both move together.
6. Open `Research`. Confirm evidence quality, source lineage, UTC as-of time, lineage summary, and stored opportunity notes appear. If the selected candidate has no notes, confirm the pane says `No stored opportunity notes are available.` rather than inventing notes.
7. Select a candidate with missing or stale evidence if one is available. Confirm missing catalyst/source/lineage/quality/liquidity fields say unavailable and do not borrow another candidate's facts.
8. Resize the window narrower and wider. Confirm Why/Research text wraps inside the Trade Plan pane, the tabs remain reachable, and neighboring panes do not overlap.
9. Confirm the disclosures remain read-only, no score/readiness value changes after opening either tab, the header still says `SIMULATION` and `FakeBroker`, and no Paper/Live execution control appears.
10. Report `PASS R015` if all nine behavioral checks pass. On failure, report the step number, selected symbol(s), pinned/unpinned state, and attach a screenshot.

Passing this checklist proves the R015 user-visible behavior but does not authorize a merge or push.

## R012 - WPF Chart Readability

Branch/commit: merged from `codex/ARGUS-R012-wpf-chart-readability`; local and remote `master` contain `69feedf`.

Automated result: `AUTOMATED_PASS`

- Focused chart tests passed 14/14.
- Full .NET regression passed 88/88 at R012 closeout.
- Release compilation passed with 0 warnings and 0 errors.
- Offscreen full-workstation proof is `docs/argus-office/reports/releases/ARGUS-R012-wpf-chart-readability-cli-proof.png`.
- Stored chart source files remained byte-identical; no provider, broker, Paper, Live, scoring, readiness, replay, or alert behavior changed.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Open Momentum Hunter, select a candidate with stored chart data, and choose `5m`. Confirm candles have visible bodies and wicks and the volume bars remain visible.
2. Confirm the right-side price labels are readable, sensible for the displayed bars, and not clipped.
3. Confirm bottom time labels increase left to right and clearly indicate UTC.
4. Confirm the latest-bar strip shows timestamp, open, high, low, close, and volume without truncation.
5. Resize the workstation narrower and wider. Confirm axes, latest-bar details, candles, and neighboring panes do not overlap.
6. Select a stale or unavailable context. Confirm stale/read-only/source language remains visible and no simulated candle fallback appears.
7. Confirm the header still says `SIMULATION - Python FakeBroker Only` and paper/live controls remain locked or absent.
8. Report `PASS R012` if all eight checks pass. On failure, report the step number and attach a screenshot.

## R012A - Momentum Hunter Application Icon

Branch/commit: `codex/ARGUS-R012A-momentum-hunter-app-icon` at `6f4c26e`.

Automated result: `AUTOMATED_PASS`

- The WPF executable embeds `Assets/MomentumHunter.ico`; the window uses the same resource.
- The icon contains 16, 20, 24, 32, 40, 48, 64, 128, and 256-pixel frames.
- The tray loads the executable's associated icon and retains a safe system-icon fallback.
- The focused icon contract test passed 1/1.
- Release compilation passed with 0 warnings and 0 errors.
- The full .NET suite passed 89/89.
- Windows extracted the expected branded 32-pixel icon from the compiled Release executable.
- Start Menu and pinned-taskbar shortcuts target the Release executable and the dedicated icon.
- Light/dark size proof is `docs/argus-office/reports/releases/ARGUS-R012A-momentum-hunter-icon-size-proof.png`.

Steven status: `MANUAL_FAIL / SUPERSEDED`

Steven found the original target/candlestick/arrow artwork visually unacceptable. Do not merge R012A by itself; use the R012B replacement checks below.

## R012B - Momentum Hunter Icon Redesign

Branch/commit: `codex/ARGUS-R012B-momentum-hunter-icon-redesign` at `37e92c4`.

Automated result: `AUTOMATED_PASS`

- The replacement keeps the existing executable, window, tray, Start Menu, and pinned-taskbar integration.
- The simplified mark is a bold white `M` ending in a teal rising arrow on a navy rounded square.
- A deterministic source generator creates the 1024-pixel PNG and 16, 20, 24, 32, 40, 48, 64, 128, and 256-pixel ICO frames.
- The focused icon contract passed, the full .NET suite passed 89/89, and Release compilation passed with 0 warnings and 0 errors.
- Windows extracted the redesigned 32-pixel icon from the compiled executable.
- The Start Menu and pinned-taskbar shortcuts target `%LOCALAPPDATA%\MomentumHunter\Builds\R012B-37e92c4`.
- Light/dark size proof is `docs/argus-office/reports/releases/ARGUS-R012B-momentum-hunter-icon-redesign-proof.png`.

Steven status: `MANUAL_FAIL`

Steven found the white-`M`/teal-arrow artwork visually unacceptable. Do not merge R012B or use it as the final product identity. Its multi-resolution generator, extraction test, executable resource, title-bar, tray, Start Menu, and taskbar wiring may be reused on a clean R012C branch after new artwork is approved.

## R013 - WPF Chart Inspection

Branch/commit: `codex/ARGUS-R013-wpf-chart-inspection` through evidence commit `29dd27d` with implementation at `4c1c1ab`.

Automated result: `AUTOMATED_PASS`

- Deterministic nearest-candle behavior is covered for unordered input, first/middle/last positions, exact edges, empty input, out-of-plot positions, NaN, and infinity.
- Inspected details, latest-bar restoration, and stale-inspection clearing are covered by focused view-model tests.
- Primary XAML and dynamically created secondary/floating chart panes bind the same inspection, interval, and detail state.
- Focused chart tests passed 17/17.
- Release compilation passed with 0 warnings and 0 errors.
- The full .NET suite passed 97/97.
- Protected-path review found no Python engine, provider, source-data, scoring, readiness, replay, alert, broker/order, credential, package, schema, migration, or production-configuration change.
- The 1440x760 offscreen proof is nonblank and is stored at `docs/argus-office/reports/releases/ARGUS-R013-wpf-chart-inspection-cli-proof.png`.

Steven status: `MANUAL_PENDING`

Check these one by one:

1. Open the R013 Momentum Hunter build, select a candidate with stored candles, and choose `5m`.
2. Move the pointer slowly from the leftmost candle toward the rightmost candle. Confirm one amber vertical line snaps candle by candle and one amber horizontal line aligns with the selected candle's close.
3. Confirm the strip changes from `LATEST BAR` to `INSPECTED BAR` while the pointer is over the plot.
4. Confirm the inspected UTC timestamp, open, high, low, close, and volume change as you move between candles and appear consistent with each highlighted candle.
5. Move the pointer outside the plotted candle/volume area. Confirm the crosshair clears and the strip returns to `LATEST BAR`.
6. While inspecting, change candidate or interval. Confirm no crosshair or inspected details from the old context survive.
7. Create a secondary chart with `New Chart`, then dock or float it. Confirm hover inspection, UTC/OHLCV details, and clearing behavior work there too.
8. Confirm candles, wicks, volume bars, price/time axes, source/stale language, and neighboring panes remain readable and do not jump or overlap during inspection.
9. Confirm the header still says `SIMULATION - Python FakeBroker Only`; Paper and Live remain locked, and no provider-fetch or execution overlay appears.
10. Report `PASS R013` if all nine behavioral checks pass. On failure, report the step number, candidate, interval, and attach a screenshot.

## R014 - WPF Command Palette And Symbol Quick-Open

Branch/commit: `codex/ARGUS-R014-wpf-command-palette` at `8ca111b`.

Automated result: `AUTOMATED_PASS`

- Exact symbol lookup, case-insensitive and partial candidate filtering, command aliases, no-match state, stale-candidate rejection, Add Chart, Activity, and Diagnostics behavior are covered by 8 focused tests.
- Release compilation passed with 0 warnings and 0 errors.
- The full .NET suite passed 96/96.
- Protected-path review found no Python engine, provider, source-data, scoring, readiness, replay, alert, broker/order, credential, package, schema, migration, or production-configuration change.
- The 1440x900 offscreen proof is nonblank and stored at `docs/argus-office/reports/releases/ARGUS-R014-wpf-command-palette-cli-proof.png`.
- The isolated review build is `%LOCALAPPDATA%\MomentumHunter\Builds\R014-8ca111b\MomentumHunter.Desktop.Wpf.exe`.

Steven status: `MANUAL_PENDING`

This isolated build does not contain the separate R012B icon or R013 chart-inspection branches. Do not judge those changes while checking R014.

Check these one by one:

1. Close every running Momentum Hunter process so single-instance activation does not redirect you to another review build.
2. Launch `%LOCALAPPDATA%\MomentumHunter\Builds\R014-8ca111b\MomentumHunter.Desktop.Wpf.exe`.
3. Press `Ctrl+K`. Confirm a centered Command Palette opens, keyboard focus is in its search field, and Add Chart, Toggle Activity, View Diagnostics, and current candidates are listed.
4. Type `PLTR`, use Up/Down, then press Enter. Confirm PLTR becomes the selected candidate and its linked chart/trade-plan context updates through the normal selection workflow.
5. Use the top search field to enter exact symbol `AMD` and press Enter. Confirm AMD opens directly.
6. Enter partial company text `lant` in the top search and press Enter. Confirm the palette opens with PLTR filtered first rather than silently opening an unrelated candidate.
7. Enter `zzzz`. Confirm a visible no-match message appears; pressing Enter must not change the selected candidate or close the palette.
8. Execute Add Chart. Confirm a linked chart is created and activated for the current symbol.
9. Execute Toggle Activity twice. Confirm the Activity pane opens and then hides.
10. Execute View Diagnostics. Confirm the Diagnostics pane becomes visible.
11. Click a result and press Enter, then reopen the palette and press Escape from both the search field and result list. Confirm execution and closing work without a no-op.
12. At approximately 1440px window width, confirm `Search (Ctrl+K)` is readable and the compact Save/Restore buttons show `Save layout` and `Restore layout` tooltips.
13. Confirm the header still contains both `SIMULATION` and `FakeBroker`, Paper/Live remain unavailable, and no provider or execution control was added.
14. Report `PASS R014` if all thirteen behavioral checks pass. On failure, report the step number, query/command used, and attach a screenshot.
