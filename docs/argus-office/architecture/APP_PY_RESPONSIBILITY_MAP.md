# App.py Responsibility Map

## Purpose
This map records what `momentum_hunter/app.py` owns today so future refactors can move one seam at a time without changing production behavior.

## Summary
`app.py` should eventually become a thin shell: initialize `QApplication`, build the main window, wire page modules, and delegate business/state work to services or view models. Today it owns shell, pages, workflows, data reads/writes, view models, styles, and safety messaging.

## Line-Range Map

| Lines | Area | Main Responsibility | Should Live In |
| ---: | --- | --- | --- |
| 1-230 | Imports/global constants | Pulls PySide, report, storage, scoring, review, replay, evidence, and UI modules into one file. | Split imports across page modules and services as extracted. |
| 237-339 | `ARGUS_MACHINE_PLACEHOLDER_CANDIDATES` | Placeholder autonomous candidates and ladder fields. | `momentum_hunter/ui/argus_machine.py` now; later an Argus Machine view model/service. |
| 341-388 | Watermark widgets | Reusable UI widgets. | `momentum_hunter/ui/components.py`. |
| 390-407 | `ReportLoaderWorker` | Generic thread worker for slow report builders. | `momentum_hunter/ui/report_loader.py` or app service helper. |
| 408-481 | Main window init/shell | State initialization, app stacks, startup hooks, timers, first refreshes. | Keep in `app.py` until page modules exist. |
| 482-498 | Steven Desk stack | Builds inner desktop page stack. | Could stay in shell or move to `ui/steven_desk.py`. |
| 499-610 | Gateway page and routing | Gateway page, choice cards, route methods. | `ui/argus_machine.py` or `ui/gateway.py`. |
| 611-881 | Argus Machine console | Machine page, Top 5, workbench, ladder, risk table, locked order console, log, selection handler. | `ui/argus_machine.py`. |
| 882-969 | Navigation rail/history | Page buttons, back history, page names, page-change side effects. | Shell or `ui/navigation.py` after page extraction. |
| 970-1000 | Dashboard page | Builds dashboard layout and status label. | `ui/dashboard_page.py`. |
| 1001-1027 | Command status strip | Status cards for market/evidence/alerts/outcomes/execution/autopilot. | Dashboard component/view model. |
| 1028-1082 | Watchlist Center page | Actions/table/guidance for interested/watchlist candidates. | `ui/watchlist_center.py` plus service/view model. |
| 1083-1101 | Evidence page shell | Evidence Console page wrapper. | `ui/evidence_console.py`. |
| 1102-1132 | Research Lab page shell | Research page wrapper/actions. | `ui/research_lab.py`. |
| 1133-1191 | Timeline/Replay page | Historical snapshot controls, candidate replay table/detail. | `ui/replay_page.py`; preserve replay identity. |
| 1192-1242 | Capture Health page | Provider/capture/CSV/outcome status labels and retry. | `ui/capture_health_page.py`. |
| 1243-1453 | Evidence Console builder | Active monitor, autopilot, evidence health, execution-ready, alerts, outcomes, performance tabs. | `ui/evidence_console.py`; service adapter later. |
| 1454-1645 | Evidence refresh/view shaping | Loads dashboard rows, filters execution-ready rows, populates tables, next-action summary. | Evidence view model/service adapter. |
| 1646-1668 | Command status refresh | Copies evidence/capture status into dashboard cards. | Dashboard view model. |
| 1669-1744 | Watchlist Center refresh/open plan | Shapes watchlist rows and routes to entry plan editor. | Watchlist view model plus UI module. |
| 1745-1881 | Active monitor/evidence actions | Runs monitor cycle/autopilot/outcome updates; starts/stops monitor loop. | Application services, not UI. |
| 1882-1900 | User monitor symbols | Adds/removes symbols through monitor target services. | Evidence service/UI split. |
| 1901-2004 | Top bar | Mode/provider/scanner controls, action buttons, guidance, logo. | Dashboard controls component. |
| 2005-2065 | Candidate panel | Candidate table and review buttons. | Dashboard candidate table component. |
| 2066-2185 | Research/candidate detail panel | Candidate identity, chart, news, notes, entry-plan editor. | Dashboard detail component plus entry-plan view model. |
| 2186-2228 | Config/mode/provider/scanner changes | Writes config and UI guidance for scanner criteria. | App settings service plus UI adapter. |
| 2229-2300 | Scanner run | Calls provider, fetches news, scores candidates, updates state, handles provider errors. | Scanner application service. |
| 2301-2397 | Candidate table/detail refresh | Builds candidate rows, colors, selected detail, news HTML, row state. | Dashboard view model and components. |
| 2398-2493 | Entry-plan field persistence | Loads/clears/saves/upserts entry plans. | Entry-plan service/view model. |
| 2494-2659 | Review/watchlist/report actions | Warnings, review status writes, watchlist generation, latest report view, timeline open. | Review/watchlist services plus UI adapter. |
| 2660-2984 | Morning Review workspace | Large dialog plus nested table, decision card, entry-plan, status, why, replay closures. | `ui/morning_review.py`; pure view-model helpers first. |
| 2985-3077 | Daily Workflow dialog wrapper | Builds report inputs, opens guided dialog, wires quick actions. | `ui/daily_workflow_page.py` plus service wrapper. |
| 3078-3126 | Capture Health and Readiness dialogs | Text diagnostics and async readiness report loading. | Page modules/report loader. |
| 3127-3354 | Timeline/Replays dialogs | Candidate Story, chart/table/audit/replay dialogs, nested filter/update logic. | `ui/replay_views.py`; preserve identity/audit text. |
| 3354-3458 | Capture/save/timer/autocapture | Saves daily capture, snapshots, scheduled capture behavior, auto-scan before capture. | Capture service; dangerous seam. |
| 3459-3524 | Freshness/capture health/history refresh | Applies data view state, populates capture date/session combos. | Capture health service plus UI adapter. |
| 3525-3630 | Historical capture load/open | Loads selected/latest capture JSON and routes historical snapshot UI. | Replay/capture service; preserve selection semantics. |
| 3631-3717 | Study/research loader | Async report loader and loading dialog. | Report loader helper. |
| 3718-3872 | Historical/replay payload application | Converts capture payloads into candidate/view state; returns current dashboard. | Capture/replay service plus UI adapter. |
| 3873-3993 | Data view state/operator context/guidance | Enables/disables controls, builds operator context and guidance. | Dashboard/Daily Workflow view model. |
| 3994-4054 | Score chart/watermark | Builds chart series and watermarks. | Chart component/theme module. |
| 4055-4116 | Market regime/startup/score persistence | Detects regime, startup install, score-breakdown persistence. | Services. |
| 4117-4283 | Score breakdown, identity, selection, guards | Score-breakdown dialogs, identities, review status helpers, guard messages. | Mixed: services plus UI guards. |
| 4284-4749 | Research Lab dialog | Filters, study filter construction, lazy report tabs, report panel builders. | `ui/research_lab.py` plus report service adapter. |
| 4750-5301 | Daily Workflow builders | Summary table, guided panel, trust/next-action/step state, styles. | R003: `ui/daily_workflow.py` and view model. |
| 5325-5668 | News/morning story helpers | News text/HTML, catalyst classification context, candidate story chart/table. | View-model and UI helpers. |
| 5669-5966 | Timeline/replay helpers | Timeline table, presets, detail HTML, replay HTML. | `ui/replay_views.py`. |
| 5967-6068 | File/path/readiness helpers | Labels, market cap, latest report paths, CSV/JSON readers. | Service/data access helpers. |
| 6084-6272 | Color and chart helpers | Status colors, chart colors, logo scaling, study/outcome charts. | `ui/theme.py` and chart helpers. |
| 6273-7541 | Research report panels | Historical/catalyst/headline/outcome/opportunity/recommendation panels. | `ui/report_panels.py` by report family. |
| 7542-7557 | Chart watermark helper | Generic chart watermark. | Chart helper module. |
| 7558-7772 | `STYLESHEET` | Global QSS and object-name styling. | R004: `ui/theme.py`. |
| 7773-7780 | `main` | Creates app/window and starts event loop. | Stay in `app.py`. |

## Business Logic That Should Not Live In UI
- Provider scan orchestration and news fetching.
- Score candidate calls and score-breakdown persistence.
- Review decision identity/write logic.
- Entry-plan upsert/defaulting logic.
- Watchlist report generation and capture side effects.
- Capture scheduling and auto-capture.
- Historical capture selection and replay identity construction.
- Active monitor start/stop/run behavior.
- Research `StudyFilter` parsing from raw widgets.
- File discovery/parsing for trade-plan reports.

## Safe Refactor Principle
Extract UI-only islands first, then view models, then service boundaries. Do not start with data-writing or replay-identity code.
