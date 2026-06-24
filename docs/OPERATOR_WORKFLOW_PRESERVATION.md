# Operator Workflow Preservation Matrix

Date: 2026-06-22

Purpose: preserve every current Momentum Hunter operator workflow before Operator Dashboard Redesign v1 moves UI surfaces into a cleaner command-center structure.

Migration rule: no workflow may be removed. Workflows may only stay in place or move to a named destination with the same underlying behavior preserved.

## Screenshot Baseline

Fresh screenshots were captured under `docs/screenshots/`:

| Surface | Screenshot |
| --- | --- |
| Main Dashboard / scanner view | `momentum_hunter_current_dashboard.png` |
| Evidence / Active Monitor panel | `momentum_hunter_evidence_active_monitor_panel.png` |
| Evidence Autopilot section | `momentum_hunter_evidence_autopilot_section.png` |
| Evidence Health section | `momentum_hunter_evidence_health_section.png` |
| Execution Ready section | `momentum_hunter_execution_ready_section.png` |
| State Transitions section | `momentum_hunter_state_transitions_section.png` |
| Active Alerts section | `momentum_hunter_active_alerts_section.png` |
| Alert Outcome Tracker section | `momentum_hunter_alert_outcome_tracker_section.png` |
| Alert Performance section | `momentum_hunter_alert_performance_section.png` |
| Morning Review Workspace | `momentum_hunter_morning_review.png` |
| Daily Workflow Checklist | `momentum_hunter_daily_workflow_checklist.png` |
| Open Latest Watchlist | `momentum_hunter_latest_watchlist.png` |
| Capture Health | `momentum_hunter_capture_health.png` |
| Timeline / Replay | `momentum_hunter_timeline_replay.png` |
| Historical Snapshot | `momentum_hunter_historical_snapshot.png` |
| Research Lab | `momentum_hunter_study_engine.png` |

Note: `momentum_hunter_current_dashboard.png` is the full visual baseline for the crowded dashboard/evidence layout. The evidence-specific PNG files are section-level table thumbnails that prove each current evidence surface is present, not polished full-page screenshots. `tools/capture_ui_screenshots.py` currently writes the screenshot files but can hang during Qt cleanup after printing the saved paths. Treat that as tooling debt for the redesign milestone; do not use the hang as evidence that any operator workflow failed.

## Testing Safety Rule

When debugging Momentum Hunter UI or Qt behavior, do not run broad Qt unittest modules blindly. Use isolated commands with hard timeouts, bytecode disabled, one probe at a time, and a Python process check after each risky command. If any command hangs, stop immediately, kill only the stuck test process, record the exact command, and do not continue the sequence until the hang is understood.

## Safety Rules To Preserve

- Current/live and valid next-session review snapshots allow review decisions, watchlist status changes, entry-plan edits, and watchlist report generation.
- Aged-but-reviewable evening/preopen snapshots warn the operator but still allow review workflow until the next market open cutoff.
- Expired, historical, replay, study/research, quarantined, missing, and failed-capture contexts block trading workflow writes.
- Replay and Research Lab may show later-derived decisions and outcomes, but must label them as post-capture data and remain read-only.
- Raw capture JSON/MD files must not be modified by review, watchlist, entry-plan, evidence, or research workflows.

## Preservation Matrix

| Workflow | Current entry point | Current screen/location | Current user actions | Current output/artifact | Current safety rules | New destination after redesign | Must-preserve test/check |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Launch Momentum Hunter | `Momentum Hunter.vbs`, `Momentum Hunter.bat`, or `python run.py` | Main window | Start app | GUI session, startup launcher behavior | No trading actions; startup should not mutate captures | Stays on Dashboard | App opens without console window via VBS and shows current dashboard |
| Run scanner | `Run Scanner` | Top toolbar / dashboard | Choose provider/scanner, run scan | Candidate rows, current capture context | Provider errors must not replace good/stale table with bad data | Stays on Dashboard | Scan populates candidates or shows provider failure cleanly |
| Retry failed scan | `Retry Scan` | Provider failure banner/control | Retry after provider failure | Candidate rows or failure message | Old data remains marked stale if retry fails | Stays on Dashboard | Retry calls same scan path and preserves stale banner on failure |
| Select candidate | Candidate table row | Dashboard candidate table | Click row | Selected candidate panel updates | Read-only state does not block inspection | Stays on Dashboard | Selecting row updates ticker, score, news, notes, plan context |
| View candidate details/news | Candidate table row | Candidate detail panel | Select candidate, inspect news/catalyst/detail | Read-only detail display | Current and historical data must be visually distinguished | Stays on Dashboard | Details match selected row and stale/historical banner remains visible |
| Open Why Score | `Why?` | Candidate detail panel | Click score explanation | Score breakdown dialog | Uses stored breakdown; does not recalculate old scores | Stays on Dashboard | Dialog opens when breakdown exists; missing breakdown warns |
| Mark Interested | `Mark Interested` candidate-table action / Morning Review `Mark Interested` | Dashboard candidate action bar / Morning Review | Check rows or select candidate, click action | `review-decisions.json` update | Allowed only for reviewable contexts; blocked with reason in read-only contexts | Stays on Dashboard and Morning Review | Decision persists outside raw captures; checked rows survive selection/detail refresh |
| Mark Rejected | `Mark Rejected` | Dashboard row action / Morning Review | Check rows or select candidate, click action | `review-decisions.json` update | Allowed only for reviewable contexts | Stays on Dashboard and Morning Review | Decision persists and raw captures unchanged |
| Move Interested to Watchlist | `Move Interested to Watchlist` | Dashboard row action | Mark candidates Interested, click action | Watchlist review decisions and entry-plan shells | Allowed only for reviewable contexts | Moves to Watchlist Center; shortcut stays on Dashboard | Interested candidates become Watchlist, no raw mutation |
| Clear Checkmarks | `Clear Checkmarks` | Dashboard candidate action bar | Click action | UI selection marks cleared | Blocked in read-only contexts | Stays near candidate table | Checkmarks clear without changing review decisions |
| Create/edit Entry Plan | Entry Plan panel / Morning Review `Create/Edit Entry Plan` | Candidate detail or Morning Review | Fill trigger, stop, thesis, invalidation, max loss, size, hold, notes | `entry-plans.json` update | Allowed only for current/reviewable contexts | Moves to Watchlist Center; compact edit stays in Morning Review | Plan persists and incomplete warnings update |
| Generate Watchlist Report | `Generate Watchlist Report` | Top toolbar / Daily Checklist | Ensure Watchlist candidates exist, click action | `watchlist-YYYY-MM-DD.json`, `watchlist-report-YYYY-MM-DD.md`, manual snapshot | Reviewable only; aged snapshots require acknowledgement; historical/replay/study blocked | Moves to Watchlist Center; shortcut stays on Dashboard | Report includes watchlist candidates and entry-plan fields |
| Open Latest Watchlist | `Open Latest Watchlist` | Top toolbar | Click action | Read-only text dialog from latest watchlist/report artifact | Read-only display; no writes | Moves to Watchlist Center | Opens latest report or clear no-report message |
| Open Morning Review | `Morning Review` | Top toolbar | Click action | Morning Review Workspace dialog | Current/reviewable can edit; historical/study/replay read-only or blocked | Stays as Daily Workflow screen | Dialog shows candidate table, decision card, plan warnings |
| Use Daily Checklist | `Daily Checklist` | Top toolbar | Click action, inspect checklist/warnings, use quick actions | In-memory daily workflow report | Quick actions respect operator context | Stays as Daily Workflow screen | Counts, workflow score, and warnings are deterministic |
| Open Capture Health | `Capture Health` | Top toolbar / Daily Checklist | Click action | Read-only capture/provider/CSV/outcome health dialog | Diagnostic only | Moves to Capture Health | Dialog shows last/next capture and failure/CSV/outcome status |
| Open Historical Snapshot | `Open Historical Snapshot` | History date/session controls | Select date/session, click action | Main table loads historical capture | Historical data is read-only and warning-styled | Moves to Timeline / Replay; shortcut may remain | Historical load does not mutate raw captures |
| Return to Current Dashboard | `Current Dashboard` | Top toolbar | Click action | Live/current candidates restored | Restores current operator context | Stays on Dashboard | Current view returns with current banner and live candidates |
| Open Timeline / Replay | `Timeline / Replay` | Dashboard candidate action | Select candidate, click action, optionally replay selected capture | Timeline dialog and replay dialog | Timeline/replay read-only; quarantined/non-trading hidden by default | Moves to Timeline / Replay | Timeline rows are point-in-time and replay is read-only |
| Open Research Lab | `Research Lab` | Top toolbar | Click action, use filters/tabs | Research Lab dialog with stored-data studies | Research-only; no trade workflow writes | Moves to Research Lab | Study tabs open and post-capture labels remain clear |
| Run Active Monitor Cycle | `Run Monitor Cycle` | Execution Ready group | Click action; optional quote flags | Derived active-monitor cycle artifacts and dashboard rows | Does not change alert thresholds, scoring, readiness, or trade planning | Moves to Evidence Console | Cycle runs and updates derived monitor status only |
| Start/stop Monitor Loop | `Start Monitor Loop`, `Stop Monitor` | Execution Ready group | Start background loop, stop it | Background monitor process/status | No broker actions; loop controls only monitoring | Moves to Evidence Console | Start/stop buttons preserve process lifecycle behavior |
| Add/remove monitor symbol | `Add Symbol`, `Remove Selected` | Execution Ready group | Type symbol/note, add; select row, remove | User monitor symbol store/rows | Monitoring universe only; no trade order behavior | Moves to Watchlist Center and Evidence Console | Symbols affect monitor targets without raw capture mutation |
| Run Evidence Autopilot | `Run Evidence Autopilot` | Execution Ready group | Click action | Monitor cycle, outcome updater, evidence health, daily brief, status file | Orchestration only; no signal/scoring/readiness changes | Moves to Evidence Console | Status file and daily brief update; existing monitor path still works |
| Update Alert Outcomes | `Update Alert Outcomes` | Execution Ready group | Click action; optional fetch minute bars | Updated derived alert outcomes/status | Derived alert store only; no raw capture mutation | Moves to Evidence Console | Pending/completed/unscorable categories update correctly |
| Review Evidence Health | Evidence Health table | Execution Ready group | Inspect rows | Read-only evidence health metrics | Reporting gate only; no strategy changes | Moves to Evidence Console | Completed/pending/unscorable counts display separately |
| Review Alert Performance | Alert Performance table | Execution Ready group | Inspect rows | Read-only alert performance summaries | Excludes unscorable from return math | Moves to Evidence Console | Sample size and best/worst groups remain visible |
| Review State Transitions | State Transitions table | Execution Ready group | Inspect rows | Read-only state transition log | Derived monitoring state only | Moves to Evidence Console | Empty state shows no transitions instead of blank confusion |
| Review Active Alerts | Active Alerts table | Execution Ready group | Inspect rows | Read-only active alert list | Alert facts are historical evidence, not trade orders | Moves to Evidence Console | Active alert count and rows remain visible |
| Refresh Market Regime | `Refresh Regime` | Top toolbar | Click action | Current regime label | Context signal only; no trade execution | Stays on Dashboard or Settings/Health | Regime refresh updates label without changing raw captures |

## Migration Destinations

| Destination | Workflows |
| --- | --- |
| Stays on Dashboard | Launch, run/retry scanner, select/view candidate, Why Score, mark interested/rejected, clear checkmarks, compact watchlist shortcut, current dashboard, refresh regime |
| Moves to Watchlist Center | Move Interested to Watchlist, entry plans, generate/open watchlist, monitor target management |
| Moves to Evidence Console | Active Monitor, Evidence Autopilot, Evidence Health, Alert Outcomes, Alert Performance, State Transitions, Active Alerts |
| Moves to Research Lab | Stored-data studies, catalyst research, outcome research, readiness gates |
| Moves to Timeline / Replay | Historical Snapshot, Candidate Timeline, Replay |
| Moves to Capture Health | Capture/provider/CSV/outcome diagnostics |
| Remains background/scheduled | Windows startup, scheduled captures, scheduled evidence/reliability reports |

## Acceptance Status

- Fresh screenshots exist for all major current screens listed above.
- Every current operator button/action has a post-redesign destination.
- Daily, watchlist, evidence, research, historical/replay, and health workflows are accounted for.
- Current stale/current/historical/replay/research safety rules are documented.
- Operator Dashboard Redesign v1 should not begin until this matrix is reviewed or explicitly accepted as the migration contract.
