# ARGUS-R001 App.py Responsibility Map and Extraction Targets

## Executive Summary
`momentum_hunter/app.py` is not just a PySide window. It is the application shell, page router, gateway, Argus Machine console, Dashboard, Watchlist Center, Evidence Console, Research Lab, Replay UI, Daily Workflow dialog, scanner launcher, review-state writer, entry-plan editor, capture loader, report loader, chart builder, HTML formatter, design-system substitute, and message/guard surface. The safest first extraction is Gateway / Argus Machine UI because it is a compact, contiguous region, is display-only, has existing focused GUI tests, does not touch scoring/readiness/replay/storage/broker behavior, and already has clear object names and safety labels. R002 should extract that island before Daily Workflow or design-system work.

## App.py Size And Complexity Summary
- File: `momentum_hunter/app.py`
- Size: 7,188 lines.
- Main class: `MomentumHunterWindow`, starting at line 408.
- Global stylesheet starts at line 7558.
- The file contains more than 250 class/function/nested helper definitions by `rg -n "^class |^def |^    def " momentum_hunter/app.py`.
- The file owns both UI construction and operational behavior: scanner runs, score-breakdown persistence, review decisions, entry-plan writes, watchlist report generation, capture loading, active monitor launch, report loading, and display-state decisions.

## Responsibility Map By Region And Function

| Region | Lines | Functions / Classes | Responsibility | Extraction Note |
| --- | ---: | --- | --- | --- |
| Imports and constants | 1-340 | imports, `SCANNER_DISPLAY_NAMES`, `ARGUS_MACHINE_PLACEHOLDER_CANDIDATES` | Pulls most engine, storage, report, review, replay, and PySide dependencies into one file. Holds Argus placeholder data. | Placeholder candidates can move with Argus Machine UI. Imports shrink as modules are extracted. |
| Utility widgets/workers | 341-407 | `WatermarkWidget`, `WatermarkTableWidget`, `ReportLoaderWorker` | Generic PySide widgets and threaded report loader. | Watermark widgets can move to `ui/components.py`; loader can move later. |
| Main window init and shell | 408-481 | `MomentumHunterWindow.__init__`, `_build_ui` | Initializes config, candidate state, review/entry state, report-loader state, market regime, app stack, startup timer, capture health, evidence panel, view state. | Dangerous early; leave until page modules exist. |
| Steven Desk / Gateway / Argus Machine | 482-881 | `_build_steven_desk_page`, `_build_gateway_page`, `_build_gateway_choice`, `show_gateway`, `open_steven_desk`, `open_argus_machine_console`, `_build_argus_machine_console_page`, Argus panel builders, `_select_argus_machine_candidate` | Startup two-door gateway, display-only Argus Machine shell, placeholder Top 5, Trade Plan Ladder table, preview Risk Governor table, locked Order Console, Machine Log. | Safest first extraction. Mostly UI and placeholder view data. Existing tests cover it. |
| Navigation and page shell | 882-969 | `_build_navigation_rail`, `_navigate_to_page`, `_go_back_page`, `_update_back_button`, `_page_name` | Steven Desk navigation, page history, route side effects for Watchlist and Replay page loading. | Moderate risk; extract after page modules stabilize. |
| Dashboard and page builders | 970-1242 | `_build_dashboard_page`, `_build_command_status_strip`, `_build_watchlist_center_page`, `_build_evidence_console_page`, `_build_research_lab_page`, `_build_timeline_replay_page`, `_build_capture_health_page` | Builds the main pages and wires high-level actions. | Page-by-page extraction possible after Gateway. Watchlist and Replay have data/state coupling. |
| Evidence Console and Active Monitor UI | 1243-1900 | `_build_execution_ready_panel`, `_refresh_execution_ready_panel`, active monitor/evidence/autopilot/outcome methods, user monitor symbol methods | Builds evidence tabs, loads dashboard rows from evidence modules, starts/stops active monitor loop, runs evidence autopilot/outcome updates, shapes tables. | Valuable but riskier because UI directly invokes services and file-backed dashboard data. |
| Dashboard controls and candidate detail builders | 1901-2185 | `_build_top_bar`, `_build_candidate_panel`, `_build_research_panel` | Builds scanner controls, review buttons, candidate table, chart, news, notes, entry-plan editor. | High value, medium/high risk due to review and entry-plan coupling. |
| Config and scanner execution | 2186-2300 | `_apply_config_to_controls`, `_mode_changed`, `_provider_changed`, `_scanner_changed`, `run_scan`, `_scan_current_candidates` | Writes config, refreshes provider health, runs provider scans, fetches news, scores candidates, persists score breakdowns. | Engine/service logic trapped in UI. Do not extract until service boundary is defined. |
| Candidate table, review, entry plan, watchlist | 2301-2660 | `_populate_table`, `_selection_changed`, `_show_candidate_details`, entry-plan load/save/upsert, review status methods, `save_tomorrow_watchlist`, `view_research_list`, `view_candidate_timeline` | Shapes candidate table, saves entry plans, writes review decisions, moves candidates, generates watchlist report and manual capture. | Dangerous because it writes user state and capture/report files. Needs dedicated view model and service contracts. |
| Morning Review workspace | 2660-2984 | `open_morning_review_workspace` and nested closures | Dialog construction plus nested view-model, table refresh, entry-plan save, review status changes, timeline/why actions. | Good R003/R006-adjacent target after Daily Workflow. Nested closures should become testable helpers. |
| Daily Workflow dialog wrapper | 2985-3077 | `_build_daily_workflow_report`, `open_daily_workflow_checklist`, `_run_daily_workflow_quick_action` | Builds report inputs from window state, opens guided modal, wires quick actions. | R003 target. Wrapper still needs app state; pure step logic can move first. |
| Capture health, Readiness, Timeline, Replay dialogs | 3078-3354 | `open_capture_health_report`, `open_readiness_gate`, `_show_readiness_gate_dialog`, `_show_timeline_dialog`, `_show_replay_dialog` | Opens diagnostic/readiness/replay dialogs, builds large story UI, calls replay/timeline builders, guard messages. | Replay UI extraction is useful but riskier than Gateway because of identity/audit guarantees. |
| Capture, snapshot, historical loading | 3354-3872 | `capture_daily_snapshot`, `_capture_snapshot`, timers, auto-capture, capture health refresh/history, payload loaders, `open_selected_capture`, report loader | Saves captures, auto-captures, reads capture JSON, converts candidates, sets historical/replay state. | Dangerous. This is engine/service territory and should stay until boundary DTOs exist. |
| View-state, operator context, charts, score breakdowns | 3873-4283 | `_apply_data_view_state`, `_operator_review_context`, `_update_operator_guidance`, `_update_score_chart`, regime and identity helpers, score breakdown dialogs, guard/status helpers | Maps data state to UI enabled states, chart labels, operator guidance, review identities, score-breakdown persistence. | Core view-model seam. Extract only with focused tests around stale/current/historical states. |
| Research Lab shell | 4284-4749 | `_show_study_dialog` and nested filter/lazy-tab closures | Builds research filters, constructs `StudyFilter`, lazy-loads heavy panels, updates charts/tables, catches report errors. | High value but not first. Many nested closures and heavy report builders. |
| Daily Workflow top-level builders | 4750-5301 | `build_daily_workflow_summary_table`, `build_daily_workflow_guided_panel`, `daily_workflow_*` step functions, style helpers | Builds Daily Workflow tables, trust state, next action, step cards, blocker/dependency text. | Safe-ish R003 target because much is pure view mapping, but operator wording is user-facing. |
| Formatting and replay/story helpers | 5325-6068 | `format_news`, `morning_review_context`, capture formatters, news HTML, story chart/table, timeline/replay HTML, trade-plan report path readers | Mixes view-model shaping, HTML generation, chart building, and data file discovery. | Split into `ui/replay_views.py`, `ui/story_views.py`, and service helpers later. |
| Color/chart/style helpers | 6069-6272, 7542-7557 | `score_color`, `freshness_color`, `review_status_color`, chart colors, logo scaling, chart builders, `add_chart_watermark` | Acts as an implicit theme/design-system layer. | R004 target after first page extraction proves the module pattern. |
| Research report panels | 6273-7541 | historical, catalyst, outcome, opportunity, readiness, recommendation table/panel builders | Large read-only report widgets built from report DTOs. | Extractable by report family, but not first because the surface is wide. |
| Global stylesheet and entry point | 7558-7780 | `STYLESHEET`, `main` | Global QSS plus gateway/Argus style rules, app launch. | QSS moves in R004. `main` stays minimal. |

## Top 10 Responsibility Clusters
1. App shell and startup state.
2. Startup gateway and Argus Machine console.
3. Navigation/page switching.
4. Dashboard scanner and candidate table.
5. Review/watchlist/entry-plan workflow.
6. Daily Workflow guided modal and stepper.
7. Evidence Console and Active Monitor controls.
8. Replay/historical capture UI.
9. Research Lab and report panels.
10. Theme/style/color/chart helpers.

## UI-Only Responsibilities
- Widget construction, layout, and object names.
- Navigation rail and stacked pages.
- Gateway cards and mode labels.
- Argus Machine display panels and locked controls.
- Candidate tables, report tables, chart containers.
- Dialog windows and button rows.
- QSS and color helpers.
- Screenshot-visible safety labels and disabled button states.

## Engine/Service Responsibilities Currently Trapped In UI
- `run_scan` and `_scan_current_candidates` call providers, fetch news, score candidates, and mutate live state.
- Review status methods call `upsert_review_decision`.
- Entry-plan methods call `upsert_entry_plan`.
- `save_tomorrow_watchlist` calls `save_watchlist`, `save_watchlist_report`, and `capture_daily_snapshot`.
- Capture methods call `save_daily_capture`, `load_capture_json`, `candidate_from_dict`, score-breakdown persistence, and scheduling decisions.
- Evidence methods call active monitor, evidence autopilot, alert outcome updater, and user monitor symbol services.
- Research Lab creates `StudyFilter` and calls heavy report builders.

## View-Model Responsibilities Currently Trapped In UI
- Candidate table rows, colors, review labels, freshness labels.
- Watchlist Center plan completeness and missing-field text.
- Morning Review candidate context and warning aggregation.
- Daily Workflow trust state, next action, step lights, blockers, dependencies.
- Operator guidance for stale/current/no-candidates/incomplete-plan states.
- Evidence dashboard row mapping into table labels.
- Replay snapshot detail HTML and audit identity.
- Research report table row shaping.

## Data-Access Responsibilities Currently Trapped In UI
- Latest trade-plan CSV/JSON file discovery.
- Execution-ready CSV parsing and filtering.
- State-transition JSON parsing.
- Capture JSON loading and `_source_path` synthesis.
- Capture date/session combo population.
- Score-breakdown lookup and opportunistic persistence.
- Latest watchlist/report loading.

## Styling/Design-System Responsibilities Currently Trapped In UI
- Global `STYLESHEET`.
- Daily Workflow panel/card/light styles.
- Score/freshness/review status colors.
- View-state object names and banner colors.
- Gateway/Argus Machine QSS.
- Chart badge/watermark colors.
- Per-widget inline styles for warning/success labels.

## Safe Extraction Seams
1. Gateway and Argus Machine console page builders.
2. Argus placeholder candidate data and ladder row mapping.
3. Daily Workflow pure step/next-action view model.
4. Daily Workflow widget builders after preserving labels/object names.
5. Theme constants and color helpers.
6. Watermark widgets and common components.
7. Report panel builders by report family.
8. Replay HTML formatters after preserving identity/audit text.
9. Watchlist Center table row shaping after service boundaries.
10. Evidence dashboard row table population after service boundaries.

## Dangerous Extraction Seams
- Scanner/provider/scoring execution.
- Review identity and review-decision writes.
- Entry-plan persistence.
- Watchlist report generation and capture side effects.
- Auto-capture scheduling.
- Replay identity and capture selection rules.
- Readiness/outcome-maturity semantics.
- Score-breakdown persistence and identity formation.
- Active monitor process start/stop behavior.
- Broker/order labels or locked controls if safety language is not preserved.

## First 10 Extraction Targets Ranked By Safety/Value
| Rank | Target | Safety | Value | Why |
| ---: | --- | --- | --- | --- |
| 1 | Gateway / Argus Machine UI module | High | High | Contiguous, display-only, existing tests, no engine writes. |
| 2 | Argus Machine placeholder view model and Trade Plan Ladder row mapper | High | High | Small data-shaping seam; supports later real TradePlan mapping. |
| 3 | Daily Workflow step/next-action view model | Medium/High | High | Mostly pure logic; existing tests can expand around labels/states. |
| 4 | Daily Workflow dialog/widget builder | Medium | High | User-facing workflow improvement; must preserve action wiring. |
| 5 | Theme/color helper module | Medium | High | Reduces duplicate visual state and enables modernization. |
| 6 | Watermark/common UI components | High | Medium | Low behavior risk, useful cleanup. |
| 7 | Replay/story HTML and chart helpers | Medium | Medium | Improves app.py size; replay audit identity needs care. |
| 8 | Research report panels module | Medium | Medium | Large read-only surface; extraction mostly imports and builders. |
| 9 | Watchlist Center view model | Medium/Low | High | Valuable but writes review/plan state nearby. Needs service seam. |
| 10 | Evidence Console view model/service adapter | Medium/Low | High | Important but touches active monitor/process/report paths. |

## Recommended First Extraction
Recommended first extraction: `ARGUS-R002 - Extract Gateway / Argus Machine UI into dedicated PySide module`.

## Why R002 Is Safest
- The code lives in a contiguous early region: `ARGUS_MACHINE_PLACEHOLDER_CANDIDATES` at lines 237-339 and Gateway/Argus Machine builders at lines 499-881.
- It is display-only. It does not call providers, scoring, storage, readiness, replay, SQLite, or broker/order services.
- Its buttons are navigation or disabled locked controls.
- Existing `tests/test_autonomy_gateway.py` already verifies the two gateway choices, Steven Desk route, Argus Machine shell, five Top 5 rows, ladder population, and disabled order buttons.
- The extraction can preserve object names, labels, and button properties, reducing UI regression risk.

## Exact Files/Modules Proposed For R002
Proposed R002 files:
- `momentum_hunter/app.py` - remove extracted builders and call the new module.
- `momentum_hunter/ui/argus_machine.py` - Gateway and Argus Machine page builders, placeholder candidate data, ladder row mapping, locked console helpers.
- `tests/test_autonomy_gateway.py` - keep existing assertions; add narrow tests only if object lookup changes.
- `docs/argus-office/reports/releases/ARGUS-R002-extract-gateway-machine-ui.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`

Possible module API:
- `build_gateway_page(window: MomentumHunterWindow) -> QWidget`
- `build_argus_machine_console_page(window: MomentumHunterWindow) -> QWidget`
- `clear_argus_trade_plan_ladder(window: MomentumHunterWindow) -> None`
- `select_argus_machine_candidate(window: MomentumHunterWindow, candidate: dict[str, str]) -> None`

R002 should not introduce a backend service or real TradePlan mapping yet.

## Tests Required For R002
- `.\.venv\Scripts\python.exe -B -m compileall -q momentum_hunter tests`
- `.\.venv\Scripts\python.exe -B -m unittest tests.test_autonomy_gateway -v`
- Screenshot sanity check if the visible layout or styling changes.
- `git diff --check`
- Changed-path check confirming only approved app/ui/test/docs files changed.

## Stop Conditions For R002
- Any broker/order execution behavior appears.
- Locked order buttons become enabled.
- Safety text such as "No broker connected" or "Live trading locked" disappears.
- Object names used by tests are removed without replacement.
- Gateway no longer opens both Steven Desk and Argus Machine.
- The extraction touches scoring, readiness, replay identity, storage/schema, package files, or generated data.

## What Not To Touch Yet
- Scoring formulas or score weights.
- Scanner/provider behavior.
- Review identity and review-decision persistence.
- Entry-plan persistence semantics.
- Watchlist report generation behavior.
- Replay identity and historical capture selection.
- Readiness/outcome-maturity logic.
- Active monitor process behavior.
- SQLite schema/migrations.
- Broker/order execution behavior.
- Package/dependency files.
- Generated data or runtime artifacts.

## First 5 Extraction Tasks

| ID | Branch | Allowed Files | Protected Files | Tests | Stop Conditions | Acceptance Criteria |
| --- | --- | --- | --- | --- | --- | --- |
| ARGUS-R002 | `codex/ARGUS-R002-extract-gateway-machine-ui` | `momentum_hunter/app.py`, `momentum_hunter/ui/**`, `tests/test_autonomy_gateway.py`, release docs | scoring, readiness, replay, storage/schema, broker/order, package files, generated data | compileall, `tests.test_autonomy_gateway`, screenshot sanity if visual change, `git diff --check` | lost safety labels, enabled order buttons, changed routes, protected-path changes | Gateway/Argus builders leave `app.py`; existing behavior and tests pass. |
| ARGUS-R003 | `codex/ARGUS-R003-extract-daily-workflow-ui` | `momentum_hunter/app.py`, `momentum_hunter/ui/**`, `tests/test_daily_workflow.py`, release docs | scoring, readiness semantics, replay, storage/schema, broker/order | compileall, `tests.test_daily_workflow`, pure view-model tests if added | next-action order changes, blocker text regresses, action buttons no-op | Daily Workflow UI/view mapping leaves `app.py`; labels/states remain proven. |
| ARGUS-R004 | `codex/ARGUS-R004-design-system-theme-layer` | `momentum_hunter/app.py`, `momentum_hunter/ui/**`, focused GUI tests, screenshot artifacts, release docs | engine behavior, scoring, readiness, replay, storage/schema, broker/order, package files | compileall, focused GUI tests, screenshot proof, `git diff --check` | warning/locked/live/paper states become ambiguous, text overlaps | Reusable theme tokens/components exist; one isolated screen demonstrates them. |
| ARGUS-R005 | `codex/ARGUS-R005-backend-engine-boundary-dtos` | docs/architecture by default; optional pure DTO/view-model modules only if explicitly approved | scoring, readiness, replay identity, schema/migrations, broker/order, package files, generated data | docs-only checks by default; if implementation approved, compileall and DTO tests | second frontend starts, broker/order behavior appears, semantics mutate | Service/DTO boundary and command/no-command lists are defined. |
| ARGUS-R006 | `codex/ARGUS-R006-extract-trade-plan-ladder-ui` | `momentum_hunter/app.py`, `momentum_hunter/ui/**`, `tests/test_autonomy_gateway.py` or new focused UI test, release docs | broker/order behavior, real execution, scoring, readiness, replay, storage/schema | compileall, focused ladder tests, screenshot sanity if visual change | ladder implies live approval, manual override/risk labels disappear | Trade Plan Ladder UI component is reusable and still display-only/locked. |

## Recommended CEO Decision
Approve R002 as the first implementation extraction. It is the smallest high-value cut that reduces `app.py`, preserves all protected behavior, and gives the team a repeatable pattern for later Daily Workflow and design-system extractions.

## Evidence Reviewed
- `momentum_hunter/app.py` line count: 7,188.
- Function/class map from `rg -n "^class |^def |^    def " momentum_hunter/app.py`.
- Responsibility keyword map from `rg -n "Gateway|Argus Machine|Daily Workflow|Evidence Console|Replay|Historical|Active monitor|Watchlist|Capture Health|Readiness|STYLESHEET" momentum_hunter/app.py`.
- Existing R002 guard test: `tests/test_autonomy_gateway.py`.

## Verification Plan
- `git status`
- `git diff --check`
- Changed-path check confirming only docs changed.
