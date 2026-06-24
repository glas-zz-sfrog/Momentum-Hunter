# 1B Stabilization Plan

Date: 2026-06-24

Purpose: move Momentum Hunter from Pre-1B cleanup into the next stabilization phase without changing trading logic. Pre-1B closed the known crash/data-display rough edges. 1B should now make the operator workflow calmer, more obvious, and safer to use day to day.

## Current Entry State

Pre-1B is complete:

- Research Lab no longer crashes on open; heavy research panels load on demand.
- Scanner profile wording explains `Basic Momentum` vs `Heavy Volume Momentum`.
- Watchlist Center shows trade-plan progress and row-level `Edit Plan` / `View Plan`.
- Timeline / Replay has `Signal`, `Outcome`, and `Audit` presets.
- Timeline relative volume distinguishes unavailable legacy values from real zero.
- Timeline warns on repeated signal fingerprints.
- Evidence Console has first-pass progressive disclosure.
- Qt testing safety rule is documented.

Authoritative closure artifact: `docs/PRE_1B_CONTROL_STATUS.md`.

## 1B Objective

Stabilize the daily operator workflow so Steven can answer quickly:

1. What happened?
2. What matters?
3. What should I do next?

The main app should feel like a command center, not a pile of every available diagnostic table.

## Non-Goals

Do not change:

- scanner thresholds
- scoring logic
- readiness rules
- alert thresholds
- trade-planning rules
- broker/order behavior
- Opportunity Score
- optimizer or weight recommendations
- SQLite storage model

## Stabilization Workstreams

### 1. Dashboard Command Center

Goal: make the Dashboard the primary daily review surface.

Planned behavior:

- Keep candidate table prominent.
- Keep candidate detail panel reachable without scrolling.
- Keep compact status cards.
- Keep `What should I do next?` guidance visible.
- Remove or relocate diagnostic density that belongs in Evidence Console, Research Lab, Timeline / Replay, or Capture Health.

Acceptance checks:

- Candidate table is not squeezed into the bottom of the screen.
- A user can see snapshot state, next action, candidates, and selected-candidate details without hunting.
- Current/stale/historical warnings remain visible.

### 2. Watchlist Center Stabilization

Goal: make watchlist creation and entry-plan completion feel like one coherent workflow.

Planned behavior:

- Show Interested and Watchlist candidates clearly.
- Keep trade-plan progress and missing fields visible.
- Preserve row-level `Edit Plan` / `View Plan`.
- Keep `Generate Watchlist Report` and `Open Latest Watchlist` near the watchlist workflow.

Acceptance checks:

- Dashboard review decisions appear in Watchlist Center immediately.
- Watchlist report uses watchlist candidates by default.
- Entry-plan edits update the row state without requiring app restart.

### 3. Evidence Console Stabilization

Goal: keep evidence collection powerful but stop it from overwhelming the daily dashboard.

Planned behavior:

- Keep top next-action guidance.
- Keep `Monitor + Health`, `Execution Ready`, `Alerts + Outcomes`, and `Performance` grouping.
- Prefer compact summaries first, detail tables second.
- Preserve Active Monitor, Evidence Autopilot, Alert Outcomes, Alert Performance, State Transitions, and Active Alerts.

Acceptance checks:

- Evidence Console is reachable from navigation.
- Active Monitor and Evidence Autopilot controls still work.
- Evidence views remain derived/read-only where appropriate.
- No signal/scoring/readiness logic changes occur.

### 4. Research Lab Stabilization

Goal: keep research useful while avoiding freezes and premature conclusions.

Planned behavior:

- Keep initial Research Lab load lightweight.
- Keep heavy panels on demand.
- Keep Readiness Gate fast.
- Consider clearer grouping for Overview, Catalyst Research, Historical Review, and Data Readiness.
- Keep research-only labels and post-capture warnings visible.

Acceptance checks:

- Open Research Lab does not freeze the app.
- Open Readiness Gate does not freeze the app.
- Heavy research panels can fail safely without closing Momentum Hunter.

### 5. Timeline / Replay Stabilization

Goal: preserve audit depth while making point-in-time review easier.

Planned behavior:

- Keep `Signal`, `Outcome`, and `Audit` presets.
- Keep row detail panel.
- Keep unavailable relative volume and repeated-signal warnings.
- Do not mix future outcome labels into capture-time facts.

Acceptance checks:

- Signal preset prioritizes capture-time facts.
- Outcome preset labels later-derived fields.
- Audit preset preserves full detail.

### 6. Test Harness Stabilization

Goal: stop losing time to stuck Qt tests.

Required rule:

When debugging Momentum Hunter UI or Qt behavior, do not run broad Qt unittest modules blindly. Use isolated commands with hard timeouts, bytecode disabled, one probe at a time, and a Python process check after each risky command. If any command hangs, stop immediately, kill only the stuck test process, record the exact command, and do not continue the sequence until the hang is understood.

1B should prefer:

- syntax-only checks
- non-Qt unit tests
- targeted offscreen Qt probes
- process checks after risky commands

Avoid:

- full Qt unittest modules as routine validation
- repeated retries of a timed-out command
- starting a second risky command before checking for leftover Python processes

## Recommended Implementation Order

1. Dashboard layout stabilization.
2. Watchlist Center/report workflow tightening.
3. Evidence Console compact summary pass.
4. Research Lab grouping polish, keeping lazy loads.
5. Timeline / Replay polish only if dashboard/watchlist/evidence work does not destabilize it.
6. Add a small timeout-safe UI probe script only if manual probes remain tedious.

## Minimum 1B Validation Set

Run only targeted commands:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -B -m unittest tests.test_provider_errors tests.test_replay tests.test_outcome_maturity
```

For UI behavior, use isolated offscreen probes instead of broad Qt unittest modules:

- Dashboard constructs and closes.
- Watchlist Center sees dashboard review decisions.
- Evidence page tabs exist.
- Research Lab initial load returns quickly.
- Readiness Gate opens quickly.

Always run a process check after risky probes:

```powershell
Get-Process python,pythonw -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,StartTime,Path |
  Sort-Object StartTime |
  Format-Table -AutoSize
```

## Completion Criteria

1B stabilization is complete when:

- Dashboard is visibly usable as the daily command center.
- Watchlist Center is the natural home for watchlist/report/entry-plan workflows.
- Evidence Console is useful without crowding the Dashboard.
- Research Lab and Readiness Gate remain non-freezing.
- Timeline / Replay keeps compact and audit views.
- Existing workflows from `docs/OPERATOR_WORKFLOW_PRESERVATION.md` are preserved or intentionally relocated.
- No trading logic, scoring logic, alert logic, readiness logic, ranking logic, or trade-planning rules changed.

