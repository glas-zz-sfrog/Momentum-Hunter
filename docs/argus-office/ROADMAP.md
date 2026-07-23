# Momentum Hunter Roadmap

## Authority

This is the single authoritative view of current product position, active work, and next work. Update its `Now` section from Git evidence before a task is reported complete, merged, or blocked.

Supporting records have narrower roles:

- `BRANCH_LEDGER.md` is the detailed Git and branch-evidence record.
- `VERIFICATION_QUEUE.md` is the exact deferred Steven-check list; it does not replace Roadmap state or authorize merges.
- `TASK_LOG.md` and `CHANGELOG_ARGUS.md` are append-only history.
- Historical architecture notes and release reports remain evidence of their original decisions; they do not override this Roadmap.

## Now

Last reconciled: 2026-07-23 after R026 cleanly integrated the independently verified R013 through R025 WPF slices onto `codex/ARGUS-R026-wpf-phase12-clean-room-integration` from synchronized `master` at `69feedf`. The 13 implementation commits now form one coherent Phase 12 candidate: nearest-candle inspection, command palette, candidate evidence, diagnostics, Replay context, monitoring, Activity, alert/outcome evidence, technical research, saved watchlist, Daily Workflow, Candidate Story, and Research Maturity. Python compileall, all 588 discovered Python tests, the 194-test full .NET suite, zero-warning Release compilation, all packaged host commands, an 8,982-file source-integrity comparison, and a nonblank 1440x5490 six-frame WPF proof pass. The prior bounded Qt discovery stalls are resolved with deterministic modal interception and asynchronous mock-lifetime coverage; the affected 21 focused entry-plan/GUI-state tests also pass. Paper and Live remain locked; no broker credentials, API keys, provider fetch, real-order path, scoring change, readiness change, alert-threshold change, replay-identity change, capture-selection change, or database migration was introduced. The rejected R012A/R012B artwork is excluded, so the isolated R026 review build intentionally retains the generic executable icon while R012C awaits Steven's visual choice. Local and remote `master` remain synchronized at `69feedf`; R026 is unpushed, unmerged, and `MANUAL_PENDING`.

| Item | Current truth |
| --- | --- |
| Canonical product baseline | Local and remote `master` contain the Phase 10 TradePlan, Risk Governor, FakeBroker-only simulation, ledger, and auditor integration plus R011 chart candles and R012 deterministic chart axes/latest-bar details through `69feedf`. |
| Active product decision | The Windows-first WPF workstation is the accepted operator surface, Python remains the canonical trading and evidence engine, and Schwab/thinkorswim is the selected broker direction for both paper and eventual live trading. An interim Alpaca adapter is not approved. |
| Integrated implementation | Phases 8, 9, and 10 are `COMPLETE` on local and remote `master`. Phase 11/A016 and A016S remain branch-only through `c979866`: the Schwab support request is sent and A017 remains blocked pending an official paper-API answer. Phase 12/R011 and R012 are `COMPLETE`; R012A and R012B icon artwork are rejected; R013 through R025 are consolidated and superseded as individual merge candidates by R026, which is `IMPLEMENTED_PENDING_MERGE`. |
| R004 status | `COMPLETE`: workstation-shell feasibility is integrated into `origin/master`. |
| R005 status | `COMPLETE`: close-to-tray, lifecycle controls, single-instance activation, and physical Windows tray QA are integrated into `origin/master`. |
| Immediate next action | Steven reviews the isolated R026 build using the consolidated numbered checklist in `VERIFICATION_QUEUE.md`, then explicitly approves or rejects its local fast-forward merge and GitHub push. The individual R013 through R025 branches must not be merged separately while R026 is under review. Separately, Steven chooses `APPROVE A`, `APPROVE B`, `APPROVE C`, or `REJECT ALL` for R012C before any new icon artwork is embedded. Preserve and reconcile Schwab's written support response before proposing A017. |
| Remote backup action | Local `master`, including R012, is backed up to `origin/master` at `69feedf`. R026, its R013-R025 source branches, R012B, the rejected combined review branch, and A016/A016S remain branch-only and must not be pushed or merged without separate approval. |
| Broker and execution state | No paper or live broker path, credentials, API keys, or real order path exists. Paper and live remain locked. |

### Status Legend

- `NOT_STARTED`: no implementation has begun.
- `ACTIVE`: work is underway on the named branch.
- `IMPLEMENTED_PENDING_MERGE`: work is committed and verified on a branch, but Steven has not approved its local merge.
- `COMPLETE`: work is merged into local `master` and verified.
- `BLOCKED`: a stated gate or CEO decision prevents work from starting.
- `DEFERRED`: valid future work, intentionally not the current priority.

### Roadmap Governance

Status: `COMPLETE`

- The authoritative Roadmap is integrated into `master`; `CURRENT_STATE.md` remains deleted.
- This file is the single live state view; branch history and canonical paths are recorded in their supporting governance files.

## Roadmap

### Phase 0 - Office Scaffold

Status: `COMPLETE`

- Establish agent roles, operating rules, templates, branch policy, and protected-area rules.
- Keep governance separate from product runtime behavior.

### Phase 1 - Read-Only Mapping

Status: `COMPLETE`

- Map critical routes, data flows, scoring surfaces, replay surfaces, alerts, storage, and operator workflows.
- Use maps and audits to identify small, protected implementation slices.

### Phase 2 - Scoped Improvements

Status: `COMPLETE`

- Turn approved findings into bounded Builder tasks with focused tests and protected-path review.
- Preserve scoring, readiness, replay, storage, and execution behavior unless a separate task explicitly approves a change.

### Phase 3 - Release Discipline

Status: `COMPLETE`

- Maintain task, branch, decision, quality, and release evidence.
- Require Steven approval for local merge and explicit approval for push.

### Phase 4 - Automation And Simulation Foundation

Status: `COMPLETE` on `origin/master`

- Use neutral product terminology: Automation, Simulation, Machine Room, Risk Governor, Execution Ledger, Trade Plan, and operator review.
- Keep `Argus` as the Codex builder and office persona, not a product-screen or product-flow name.
- Retain the existing Python simulation foundation: TradePlan, Risk Governor, FakeBroker-only simulation, Execution Ledger, and Execution Auditor.
- Keep every paper and live execution boundary locked.

### Phase 5 - C# WPF Operator-Surface Feasibility

Status: `COMPLETE / DIRECTION ACCEPTED`

- Preserve Python as the canonical engine for research, scoring, readiness, replay, storage, trade planning, risk, and simulation.
- R004 proved the Windows-first WPF workstation shell: docked and floating panes, linked contexts, persistent layouts, recovery behavior, and simulation-only safety language.
- R005 proved close-to-tray behavior, single-instance activation, lifecycle controls, restricted tray commands, and physical Windows tray behavior.
- WPF is the accepted planned operator surface, subject to continued phase-gated validation; it is not a Python-engine rewrite or broker integration.
- Keep Hide, Pause Monitoring, and Exit as separate lifecycle operations. Tray or layout state must never store execution authorization, credentials, API keys, broker permissions, or order-routing permissions.

### Phase 6 - Python Simulation Foundation And Evidence Research

Status: `COMPLETE` on `origin/master`

- `momentum_hunter/autonomy/*`, `trade_planning.py`, and the current Python UI modules remain the canonical implementation on `master`.
- The clean-room simulation foundation and hardening tests are merged on `master`.
- Technical Breakout Research Engine v1 and its daily OHLC source are merged on `master`; they remain research-only and do not alter production scoring or execution behavior.
- The older standalone execution-model branch and earlier simulation branch are superseded; see `BRANCH_LEDGER.md`.

### Phase 7 - WPF Workstation And Background Lifecycle

Status: `COMPLETE`

- R004 and R005 are integrated into `origin/master` at `e14105493061ec133ecd273aaac21d8e33ead5cf`.
- R004 supplied the workstation shell: docked, tabbed, floating, resizable panes; linked chart contexts; saved layouts; SQLite recovery; and simulation-only safety language.
- R005 supplied close-to-tray behavior, explicit exit, session-ending behavior, single-instance signaling, restricted tray commands, and the in-process background-collection lifecycle. Physical Windows QA passed.
- Collection continues while the WPF application process is alive and the visible workstation is hidden.
- The Python engine is not independently hosted yet. A WPF process crash or explicit process exit still stops the current R005-hosted lifecycle.

### Phase 8 - Headless Python Engine Through Versioned Contracts

Status: `COMPLETE` on local and remote `master` through `a886c90`

- The approved Goal Charter creates versioned, provider-neutral host identity, health, collection, capability, command, and structured-error contracts.
- `momentum_hunter/engine_host.py` owns the independent loopback-only Python Engine Host. WPF discovers an existing host or launches one, reconnects by host identity, and deliberately shuts it down only on explicit Exit.
- The host has an atomic single-host lease, per-command idempotency, non-overlapping cycle guard, and a guard against the existing active-monitor runner starting a second collection loop.
- The host core owns snapshot, pause, resume, one collection cycle, and graceful shutdown. Phase 9 adds one versioned persisted-evidence snapshot capability; TradePlan, Risk Governor, chart data, simulation, broker, Paper, and Live remain outside the boundary.
- Focused Python process proof and .NET integration proof passed. The implementation fast-forwarded into local `master` and was later backed up through the approved R011 master push. See `reports/releases/ARGUS-R008-python-engine-contract-host.md`.

### Phase 9 - Read-Only Discovery, Research, Health, And Replay Integration

Status: `COMPLETE` on local and remote `master` through `a886c90`

- Connect WPF panes to the Phase 8 read-only boundary for candidates, evidence, research context, health, and replay.
- Preserve source lineage, stale-data language, and read-only replay identity.
- Use the independent engine lifecycle rather than a workstation-owned collection loop.
- The first slice exposes persisted report/status snapshots only and explicitly disables mock TradePlan, chart, risk, and simulation fallback until Phase 10.
- Focused Python tests, focused C# presentation/integration tests, a C#-to-Python host proof, broader nearby Python regression, the full .NET suite, and full Python discovery passed before the Steven-approved local fast-forward.

### Phase 10 - Trade Planning, Risk, And Simulation Integration

Status: `COMPLETE` on local and remote `master` through `a17eff8`

- The versioned Python host exposes a persisted-plan simulation workspace snapshot and a symbol-scoped FakeBroker-only simulation command.
- WPF consumes the canonical persisted TradePlan, Risk Governor, Execution Ledger, and Execution Auditor evidence rather than a mock fallback. R011 adds chart evidence separately and does not alter these planning or simulation contracts.
- A Risk Governor block prevents the simulation call and states that no evidence changed. A permitted simulation records risk, preview, FakeBroker outcome, and audit evidence in the in-memory host ledger.
- Follow-up commits `14fe317` and `893a6da` remove the Top-5-only plan mapping mismatch and the empty Risk Governor badge: all valid persisted candidate plans are exposed, and a missing plan explicitly shows `Plan unavailable` with simulation unavailable rather than a blank colored state.
- Steven accepted the manual visual proof and approved the local merge with real chart candles still explicitly deferred. Release compilation passed; focused Python simulation/autonomy tests passed 29 tests, and the full .NET workstation solution passed 71 tests immediately before merge. Full Python discovery was previously bounded at 120 seconds and did not complete; retain that test-harness timeout as a follow-up risk.

### Phase 11 - Broker Research And Hardening Before Paper Execution

Status: `ACTIVE`; A016 and A016S are `IMPLEMENTED_PENDING_MERGE`, with A016S awaiting an official Schwab response through `c979866`

- A016 produced a current broker matrix and Steven selected Schwab/thinkorswim continuity for both paper and eventual live trading; an interim Alpaca implementation is not approved.
- A016S verified that public official evidence does not prove retail Trader API access to paperMoney. A credential-free question set was sent to `TraderAPI@Schwab.com` and verified in Outlook Sent Items.
- A017 is `BLOCKED_OFFICIAL_CONFIRMATION_REQUIRED`: no adapter work may begin until Schwab confirms a machine-verifiable paper boundary.
- The WPF direction and Python engine boundary are proven through Phase 10, but no paper capability is approved.
- No credentials, API keys, paper adapter, order routing, or paper execution code belongs in this phase without a separate Goal Charter.

### Phase 12 - Incremental Capability Migration And Qt Retirement

Status: `ACTIVE`; R011 and R012 are `COMPLETE` on local and remote `master`; R012A/R012B icon artwork is `REJECTED`; R026 has consolidated R013 through R025 and is `IMPLEMENTED_PENDING_MERGE`

- R011 adds one versioned `get_chart_snapshot` host command backed only by stored `opportunity-minute-bars.json` and `daily-ohlc-bars.json` evidence.
- WPF renders `1m`, deterministically aggregated `5m`/`15m`, and `Daily` candles with bodies, wicks, and volume. Source lineage and `AVAILABLE`, `STALE`, `INSUFFICIENT_DATA`, or `UNAVAILABLE` state remain visible.
- Missing intraday evidence never falls back to daily or mock candles. No provider call, background fetch, or source-data write was added.
- Candidate, interval, linked-pane, and pinned-pane context are covered by tests. The full CLI-only WPF proof shows CRWV with 143 stored stale 5-minute candles, source/as-of text, simulation-only language, and paper/live locks.
- Steven approved R011; Git Steward fast-forwarded it into local `master` without a merge commit and backed it up to `origin/master` under separate explicit push approval.
- R012 adds deterministic nice price ticks, chronological UTC time ticks, and a latest stored-bar OHLCV strip without changing the chart contract or Python engine.
- R012 focused tests passed 14 tests, the complete .NET suite passed 88 tests, Release compilation passed with zero warnings, and the offscreen WPF proof shows readable axes/details while preserving source lineage, simulation-only language, and paper/live locks.
- Steven approved R012; Git Steward fast-forwarded it without a merge commit and pushed the approved `master` baseline to `origin/master` at `69feedf`.
- R012's physical visual checklist remains `MANUAL_PENDING` in `VERIFICATION_QUEUE.md`; that status is honest deferred QA, not a reversal of Steven's merge approval.
- R012A embeds a multi-resolution Momentum Hunter icon in the WPF executable and window, uses it for the tray with a safe fallback, and refreshes the Start Menu/taskbar shortcuts. Release build passed with zero warnings, the full .NET suite passed 89 tests, and Windows extracted the expected 32-pixel icon from the compiled executable.
- Steven rejected the original R012A artwork as visually too busy and later rejected R012B's white-`M`/teal-arrow replacement as visually unacceptable. Neither artwork may merge.
- R012B remains preserved at `37e92c4` because its reproducible generator, PNG/ICO assertions, and executable/window/tray/shortcut wiring are reusable. R012C should replace only the visual identity, regenerate a multi-resolution `.ico`, rebuild the existing WPF executable, and require visual approval before merge.
- R013 selects the nearest chronological candle from pointer position, renders a restrained crosshair at that candle and its close, and temporarily replaces the latest-bar strip with inspected UTC/OHLCV facts.
- Primary and dynamically created secondary/floating charts share the behavior; pointer leave, candle mutation, and snapshot/context replacement clear inspection and restore current latest-bar facts.
- R013 focused chart tests passed 17/17, the full .NET suite passed 97/97, Release compilation passed with zero warnings and zero errors, and the 1440x760 offscreen proof is nonblank with candles, wicks, volume, crosshair, inspected details, research-only language, and Paper/Live locks.
- R013 is committed through `29dd27d` on `codex/ARGUS-R013-wpf-chart-inspection`, remains unpushed and unmerged, and awaits Steven's physical hover/floating-pane check plus separate merge approval.
- R014 replaces the inert top search and placeholder command popup with real candidate filtering, exact symbol quick-open, partial symbol/company results, keyboard/mouse execution, and existing Add Chart, Activity, and Diagnostics workflows.
- R014 no-match and stale-candidate paths fail visibly without changing the selected candidate. The 1440px toolbar retains a readable `Search (Ctrl+K)` field using compact save/restore icon buttons with tooltips.
- R014 focused tests passed 8/8, the full .NET suite passed 96/96, Release compilation passed with zero warnings and zero errors, and the 1440x900 proof is nonblank with real commands, candidates, chart context, and FakeBroker-only safety language.
- R014 is committed at `8ca111b`, remains unpushed and unmerged, and has an isolated review build at `%LOCALAPPDATA%\MomentumHunter\Builds\R014-8ca111b`.
- `codex/ARGUS-REVIEW-R012B-R014-combined-ui` is a noncanonical review branch containing all three preserved implementations. It cherry-picked cleanly, passed the combined 106-test suite and Release build, and has a proof board at `docs/argus-office/reports/releases/ARGUS-REVIEW-R012B-R014-combined-ui-proof.png`.
- The combined review executable is `%LOCALAPPDATA%\MomentumHunter\Builds\Combined-R012B-R014-28c4154\MomentumHunter.Desktop.Wpf.exe`; the Start Menu and pinned-taskbar shortcuts target it. The prior versioned builds remain available for rollback.
- The combined branch is an operator-convenience artifact, not implicit approval to merge R013 or R014, and it must not merge as a unit because it contains rejected R012B artwork.
- R015 replaces the static Trade Plan `Why` and `Research` text with persisted catalyst/source/timestamp, source readiness, liquidity, source quality, lineage, and opportunity notes for the pane's current candidate.
- The .NET mapper preserves the existing Python `notes` array instead of dropping it. Missing catalyst, source, lineage, quality, liquidity, or notes remain explicitly unavailable; no evidence is synthesized.
- Candidate switching refreshes the disclosure, while a pinned Trade Plan keeps its evidence attached to the pinned symbol. Focused .NET tests passed 5/5, nearby Python read-model/simulation tests passed 10/10, the full .NET suite passed 91/91, Release compilation passed with zero warnings/errors, and Python compileall passed.
- R015 has a nonblank 1440x1808 Why/Research proof at `docs/argus-office/reports/releases/ARGUS-R015-wpf-candidate-evidence-cli-proof.png` and an isolated review build at `%LOCALAPPDATA%\MomentumHunter\Builds\R015-candidate-evidence`.
- R015 remains branch-only on `codex/ARGUS-R015-wpf-candidate-evidence`; it does not change scoring, readiness, replay, capture selection, providers, alerts, broker/orders, credentials, schema/migrations, or Paper/Live locks.
- R016 replaces the Diagnostics pane's component-name-only list with the existing Python health snapshot's aggregate state, component counts, snapshot UTC time, and each component's exact state, summary, and checked UTC time.
- The WPF projection preserves source component order and exact `Healthy`, `Degraded`, and `Unavailable` states. Missing or empty snapshots are explicitly unavailable; degraded and partial states are not painted as healthy.
- Opening Diagnostics expands its AvalonDock pane to a usable minimum height without changing saved-layout restoration. The content remains scrollable at narrower workstation widths.
- R016 focused health/read-only/simulation-boundary tests passed 10/10, the full .NET suite passed 93/93, Release compilation passed with zero warnings/errors, Python compileall passed, and protected-path diff review passed.
- R016 has a nonblank two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R016-wpf-health-diagnostics-cli-proof.png` and an isolated review build at `%LOCALAPPDATA%\MomentumHunter\Builds\R016-health-diagnostics`. It remains branch-only and adds no repair, provider, broker, execution, scoring, readiness, alert, schema, or credential behavior.
- R017 replaces the Replay pane's one-line placeholder with a projection of the existing `ReplaySnapshot`: exact replay ID, `AVAILABLE`/`NOT SELECTED`/`UNAVAILABLE` state, symbol, interval, UTC as-of time, and source summary.
- Missing snapshots and blank fields use explicit unavailable labels. The WPF layer does not synthesize replay IDs, choose captures, change replay identity, or mutate current research.
- R017 focused replay/read-only/simulation tests passed 14/14, the full .NET suite passed 93/93, Release compilation passed with zero warnings/errors, Python compileall passed, and protected-path review passed.
- R017 has a nonblank two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R017-wpf-replay-context-cli-proof.png` and an isolated review build at `%LOCALAPPDATA%\MomentumHunter\Builds\R017-replay-context`. It remains branch-only and does not change replay semantics, capture selection, scoring, readiness, providers, alerts, broker/orders, credentials, schema/migrations, or Paper/Live locks.
- R018 replaces the Automation pane's future-placeholder copy with the existing `BackgroundCollectionStatus`: exact lifecycle state, established operator summary, source detail, monitored-symbol count, completed-cycle count, and last completed UTC scan.
- `HEALTHY`, `DEGRADED`, `PAUSED`, `BLOCKED`, `STARTING`, and `STOPPING` remain distinct. The pane adds no scheduler, provider call, scan action, or automated-trading control.
- R018 focused presentation/lifecycle tests passed 33/33, the full .NET suite passed 95/95, Release compilation passed with zero warnings/errors, Python compileall passed, and protected-path review passed.
- R018 has a nonblank degraded-state two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R018-wpf-monitoring-status-cli-proof.png` and an isolated review build at `%LOCALAPPDATA%\MomentumHunter\Builds\R018-monitoring-status`. It remains branch-only and does not change monitoring lifecycle commands, providers, scoring, readiness, replay, capture selection, alerts, broker/orders, credentials, schema/migrations, or Paper/Live locks.
- R019 replaces the Activity pane's abbreviated time/category/message row with a presentation-only projection of each existing `ActivityEvent`: full UTC timestamp, category, symbol or explicit `Workspace` scope, exact health state, and wrapped source message.
- Existing collection order is preserved, newest insertions appear where their current producers place them, and blank source fields receive visible fallbacks. The projection does not create, filter, reorder, persist, fetch, or route events.
- R019 focused activity/read-only/lifecycle tests passed 31/31, the full .NET suite passed 93/93, Release compilation passed with zero warnings/errors, Python compileall passed, and protected-path review passed.
- R019 has a nonblank two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R019-wpf-activity-events-cli-proof.png` and an isolated review build at `%LOCALAPPDATA%\MomentumHunter\Builds\R019-activity-events`. It remains branch-only and does not change event producers, monitoring commands, simulation behavior, providers, scoring, readiness, replay, capture selection, alerts, broker/orders, credentials, schema/migrations, or Paper/Live locks.
- R020 advances the read-only workspace payload to schema v2 and adds one `alertEvidence` object sourced only from the existing persisted `opportunity-alerts.json`. `AVAILABLE`, `EMPTY`, and `UNAVAILABLE` remain distinct; full-store counts are separate from the newest 50 active/pending rows and newest 100 recorded-outcome rows.
- The existing Review-workspace Outcomes pane now exposes source state/time/summary/counts, active or pending alert ID/time/symbol/type/state/reason, and recorded outcome alert time/status/classification/stored metrics. Missing IDs and timestamps remain visibly unavailable.
- Stored alert status and outcome classification are never recalculated. The read model does not call a provider, update outcomes, alter thresholds, mutate the alert store, change scoring/readiness, or expose an action.
- R020's 53 nearby Python tests and 96/96 full .NET tests pass; Release compilation has zero warnings/errors, Python compileall passes, source hashes remain unchanged, structurally invalid alert collections remain explicitly unavailable instead of appearing empty, and the real host boundary returns schema v2. Repository-wide Python discovery timed out at five minutes and is recorded as incomplete rather than passed.
- R020 has a nonblank two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R020-wpf-alert-outcome-evidence-cli-proof.png` and an isolated review build at `%LOCALAPPDATA%\MomentumHunter\Builds\R020-alert-outcome-evidence`. It remains branch-only and does not change alert generation, outcome classification, scoring, readiness, replay, capture selection, providers, broker/orders, credentials, database schema/migrations, or Paper/Live locks.
- R021 adds one separate `get_technical_research_snapshot` host capability backed only by the existing persisted `technical-breakout-events-latest.json` and `technical-breakout-study-latest.json` reports. It does not regenerate reports, fetch a provider, mutate evidence, or join this payload to scoring/readiness/alert/trade-planning/execution contracts.
- The WPF Research pane now shows the selected symbol's exact source state/time, full event/outcome counts, warnings, newest 50 signal rows, and newest 50 studied-outcome rows. Trigger, distance, RVOL, volume/relative-strength confirmation, forward returns, MFE/MAE, held/failed/extended flags, and stored notes remain nullable and explicitly unavailable when absent.
- `EMPTY` means both complete reports contained no selected-symbol rows and explicitly does not mean “breakout absent.” Missing sources/timestamps or one-sided event/outcome evidence are `PARTIAL`; unreadable event evidence is `UNAVAILABLE`; reports older than 24 hours remain visible as `STALE`.
- R021 guards asynchronous candidate changes so a late response for an older symbol cannot overwrite the newest selection. Tests cover source validation, incomplete chains, row limits, cache refresh, nonmutation, host idempotency/no-collection behavior, mapper validation, shell failures, and out-of-order responses.
- R021's 45 broader Python tests and 103/103 full .NET tests pass; Release compilation has zero warnings/errors, Python compileall passes, actual source hashes remain unchanged, the real reports return 124 CRWV events and 124 studies with 50-row detail caps, and protected-path review passes.
- R021 has a nonblank two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R021-wpf-technical-research-evidence-cli-proof.png` and an isolated review build at `%LOCALAPPDATA%\MomentumHunter\Builds\R021-technical-research-evidence`. It remains branch-only and does not change breakout calculations, generated reports, scoring, readiness, alerts, replay, capture selection, providers, trade planning, broker/orders, credentials, database schema/migrations, or Paper/Live locks.
- R022 adds one separate `get_saved_watchlist_snapshot` host capability backed only by the newest exact `watchlist-YYYY-MM-DD.json` persisted artifact. Markdown reports and unrelated filenames are ignored; the source is read directly without creating directories, fetching providers, regenerating lists, or writing evidence.
- The WPF Watchlist pane now shows source file/date/time, exact `AVAILABLE`, `STALE`, `PARTIAL`, `EMPTY`, or `UNAVAILABLE` state, full/usable/displayed counts, warnings, and up to 100 source-ordered rows. Stored rank, symbol, company, score, price/change, volume/RVOL, sector/industry, freshness, save time, headline, and operator notes remain nullable and explicitly unavailable when absent.
- The artifact is labeled `Saved Watchlist Evidence`: it is not joined to current candidates, review decisions, entry plans, alerts, TradePlans, or execution. The pane exposes no edit, promote, regenerate, provider, score, alert, planning, broker, Paper, Live, order, or automatic-trading action.
- R022's Python compileall, 63 bounded Python regressions, 98/98 full .NET tests, and Release build pass; the actual 14,507-byte source retained SHA-256 `6F19E86AF2B189D3560DB9CCCB6A0725754B74CE598AD7A6105017D5BBD2E8C8` before and after projection. The real artifact returns `PARTIAL`, 3/3/3 counts, `NAVN`/`FRMI`/`HOOD` in source order, one missing `saved_at`, and a stale warning.
- R022 has a nonblank two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R022-wpf-saved-watchlist-evidence-cli-proof.png` and an isolated review launcher at `%LOCALAPPDATA%\MomentumHunter\Builds\R022-saved-watchlist-evidence\Launch R022 Saved Watchlist Review.lnk`. It remains branch-only and does not change watchlist generation, scoring, readiness, replay, capture selection, providers, alerts, trade planning, broker/orders, credentials, database schema/migrations, or Paper/Live locks.
- R023 adds one separate argument-free `get_daily_workflow_snapshot` host capability backed only by persisted trade-planning, capture-health, review-decision, entry-plan, and outcome-maturity evidence. It does not run collection, fetch a provider, refresh a report, save a decision/plan, or mutate source data.
- The existing Daily Workflow trust, next-action, and five-step guidance bodies move unchanged from `app.py` into `daily_workflow_guidance.py`; the Qt modal continues importing the same functions while the new workstation projection reuses them. WPF receives exact source identity, operator context, workflow score, capture state, review/plan/outcome counts, readiness evidence, warnings, next action, and the canonical five lights.
- The WPF pane is explicitly read-only, hidden by default, and presented in a dedicated review-height bottom pane. It has no action button and states that lights describe operator discipline rather than trade quality, readiness approval, or an order instruction. At 1100 pixels wide the five fixed-width cards wrap and remain reachable by scrolling.
- R023's Python compileall and 78 bounded Python tests pass; the full .NET suite passes 95/95; Release compilation has zero warnings/errors; all ten extracted guidance function bodies are AST-equivalent to `master`; and 8,666 actual source files retain identical SHA-256 hashes before and after projection. `EntryPlanGuiTests` exceeded its bounded Qt timeout and remains an explicit test-harness risk.
- The actual source returns `STALE`, `HISTORICAL_READ_ONLY`, discipline score 54, reviews 0/14, no watchlist plans, next-day/five-day/pending outcomes 949/912/38, a blocked restore-current-evidence action, and the canonical `capture`, `review`, `plans`, `report`, `readiness` sequence.
- R023 has a nonblank 1440x1800 two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R023-wpf-daily-workflow-evidence-cli-proof.png` and an isolated review launcher at `%LOCALAPPDATA%\MomentumHunter\Builds\R023-daily-workflow-evidence\Launch R023 Daily Workflow Review.lnk`. It remains branch-only and does not change scoring, readiness semantics, replay identity, historical capture selection, watchlist generation, providers, alerts, trade planning, broker/orders, credentials, database schema/migrations, or Paper/Live locks.
- R024 adds one separate argument-scoped `get_candidate_story_snapshot` host capability backed by the canonical trusted replay timeline and `build_candidate_story_summary`. It reads persisted raw captures plus existing review/outcome annotations, excludes quarantined and ordinary non-trading-day rows, bounds display detail to the latest 100 points while preserving full counts, and never writes or recalculates source evidence.
- The linked WPF Candidate Story pane shows exact evidence state, canonical status/detail, company/sector/industry, first/latest price, move, score path, peak, full trusted count, chronology, source/trust context, and warnings. Capture-time facts and later-derived annotations have separate columns. Empty, partial, unavailable, malformed, duplicate-identity, missing-time, invalid-symbol, failure, and out-of-order-response cases fail visibly and safely.
- The pane is hidden by default, follows Link A symbol/interval context, restores into legacy layouts at a dedicated 520-pixel review height, and exposes no review, score, readiness, planning, simulation, provider, broker, Paper, Live, order, or automated-trading action. Its only rendered button is the read-only DataGrid's built-in Select All affordance.
- R024's Python compileall and 75 bounded Python tests pass; the full .NET suite passes 101/101; Release compilation has zero warnings/errors; the real packaged projection returns CRWV `PARTIAL`, `Fading`, and 13 trusted points; and all 76 actual source files retain aggregate SHA-256 `FAB0731CB65A2ED5955BDA162B2CCB1F4377E1A44466C77F3B26D78E411CABF5` before and after projection.
- R024 has a nonblank 1440x2000 combined two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R024-wpf-candidate-story-evidence-cli-proof.png` and an isolated review launcher at `%LOCALAPPDATA%\MomentumHunter\Builds\R024-candidate-story-evidence\Launch R024 Candidate Story Review.lnk`. It remains branch-only and does not change scoring, readiness semantics, replay identity, historical capture selection, providers, alerts, trade planning, broker/orders, credentials, database schema/migrations, or Paper/Live locks.
- R025 adds one separate argument-free `get_research_maturity_snapshot` host capability backed only by `evidence-analytics-maturity-latest.json` and `evidence-census-latest.json`. It never regenerates either report, opens SQLite, fetches a provider, runs collection, changes a score/readiness/alert, or writes source evidence.
- The dedicated WPF Research Maturity pane shows exact source state/time, strategy lock, allowed action, scorable-alert maturity, all-alert census completion, evidence-gate progress, sample/edge status, persisted census counts, research questions, warnings, and safety language. Missing, malformed, stale, partial, empty, duplicate, inconsistent, and attempted strategy-unlock states fail visibly and conservatively.
- R025 validates every source gate and table count before display truncation, keeps full counts separate from bounded rows, rejects structurally invalid census provenance, uses defensive cache copies, and keeps the pane independent from candidate selection. Legacy layouts gain one hidden unlinked pane; schema-v5 layouts preserve a deliberate close.
- R025's Python compileall and 53 bounded Python tests pass, including 17 focused research-maturity tests; the full .NET suite passes 99/99; Release compilation has zero warnings/errors; and the real host returns `STALE`, 100.0% scorable maturity, 50.0% census completion, 1/25 evidence-gate progress, `COLLECTING_ONLY`, `INSUFFICIENT_SAMPLE`, and `LOCKED`.
- The two real persisted source reports retain SHA-256 `D38560B17CE9EDCED8ACBD8FDF3D5DA8260A4E1D291E01DF0EE73ED69B089F3C` and `3F571392162E370586A38D34D9605B405A08D65DD4A1B8C57992B6254644D80E` before and after projection. R025 has a nonblank 1440x1740 combined two-viewport proof at `docs/argus-office/reports/releases/ARGUS-R025-wpf-research-maturity-evidence-cli-proof.png` and an isolated review launcher at `%LOCALAPPDATA%\MomentumHunter\Builds\R025-research-maturity-evidence\Launch R025 Research Maturity Review.lnk`.
- R025 remains branch-only and does not change research calculations, scoring, readiness semantics, replay identity, historical capture selection, providers, alerts, trade planning, simulation, broker/orders, credentials, database schema/migrations, or Paper/Live locks.
- R026 starts cleanly from `69feedf` and integrates one implementation commit from each R013 through R025 source branch without the rejected R012A/R012B icon artwork. Shared host contracts, schema-v2 alert evidence, concurrent technical/Candidate Story refresh, and layout migrations are reconciled into layout schema 7.
- The integrated runtime is 13 implementation commits ahead of `master` through `a263311`, followed by closeout and test-hardening evidence. Python compileall passes; all 588 tests found by repository-wide Python discovery pass; the 21 focused entry-plan/GUI-state tests pass; the Release solution builds with 0 warnings and 0 errors; and all 194 .NET tests pass.
- Repository-wide Python discovery now completes in 63.3 seconds. The previous unattended Qt stalls were test-harness defects: read-only entry-plan tests left informational modals open, while asynchronous readiness/research callbacks outlived their mocked dependencies and the Research Lab assertion ran before its queued refresh. The tests now exercise the same behavior deterministically without changing application code.
- Every packaged read-only command and the FakeBroker-only simulation workspace succeeds against canonical local evidence. The integrated display returns 14 candidates; CRWV chart `STALE`; technical research `STALE` with 124 events and 124 studies; saved watchlist `PARTIAL` with 3 rows; Daily Workflow `STALE` with 5 steps; Candidate Story `PARTIAL` with 13 points; and Research Maturity `STALE` with strategy optimization `LOCKED`.
- All 8,982 source-evidence files retained aggregate SHA-256 `F4E1127174FFBE0919563DBDC3A291CA9A17C1F7066639EBED4403727CA7E201` before and after the packaged host proof.
- The nonblank 1440x5490 six-frame integration proof is `docs/argus-office/reports/releases/ARGUS-R026-wpf-phase12-integration-cli-proof.png`. It visibly covers the command palette, candles/wicks, simulation-only TradePlan, technical research, saved watchlist, Daily Workflow, Candidate Story, Research Maturity, and Paper/Live locks.
- The isolated review launcher is `%LOCALAPPDATA%\MomentumHunter\Builds\R026-phase12-integrated-review\Launch R026 Phase 12 Integrated Review.lnk`. It uses isolated layout/settings and a read-only junction to canonical local evidence; it does not replace the pinned taskbar shortcut.
- R026 remains unpushed and unmerged pending Steven's consolidated physical review and explicit Git decision. R013 through R025 remain preserved as audit branches but are superseded as individual merge candidates.
- The generic executable icon in the R026 package is not acceptance evidence. R012C remains a separate visual-identity slice because both prior icon artworks were rejected.
- Zoom, pan, provider access, indicators, drawing tools, alerts, and execution overlays remain outside R013/R014.
- Migrate individual proven workflows to the WPF shell only after their Python contracts and operator proof are complete.
- Retire corresponding Qt screens incrementally, with acceptance evidence and rollback paths. Do not perform a broad rewrite.

### Phase 13 - Paper Execution Gate

Status: `BLOCKED`

- Requires completed Phases 8-12, a Steven-approved paper-execution Goal Charter, broker research, adapter safeguards, audit evidence, and explicit paper-only UI and mode boundaries.

### Phase 14 - Live Execution Gate

Status: `BLOCKED`

- Requires successful paper-operation evidence, a separate CEO decision, explicit credential and approval controls, independent audit review, and a dedicated live-execution Goal Charter.

## Roadmap Update Protocol

At every substantive task closeout, the responsible agent must:

1. Reconcile the `Now` section against `git status --short --branch`, the active branch HEAD, and local `master` versus `origin/master`.
2. Move the affected roadmap phase to the correct status without calling branch-only work `COMPLETE`.
3. Record the concrete next action and any new block or decision gate.
4. Update `BRANCH_LEDGER.md` only when branch/merge/push state changes, and `TASK_LOG.md` or `CHANGELOG_ARGUS.md` as historical evidence requires.
5. Add or update exact manual checks in `VERIFICATION_QUEUE.md` for every user-visible change.
6. Cite the resulting Roadmap transition in the final CEO report.

## Protected Areas

Do not change core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior without explicit approval.
