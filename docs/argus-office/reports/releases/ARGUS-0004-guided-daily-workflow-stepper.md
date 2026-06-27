# ARGUS-0004 Guided Daily Workflow Stepper

Date: 2026-06-27
Branch: `codex/ARGUS-0004-guided-daily-workflow-stepper`
Owner: Argus Orchestrator / Builder
Status: Complete, pending Steven review

## Scope

Implement the first safe Concept A bridge from ARGUS-0003: keep Daily Workflow as a modal and redesign the existing checklist dialog into a guided stepper using only existing report/context data and existing quick-action handlers.

This is not the full Concept B Dashboard cockpit.

## Phase 1 Promotion

ARGUS-0003 was fast-forward merged into local `master` before this branch was created.

- Source branch: `codex/ARGUS-0003-guided-daily-workflow-design`
- Promoted commit: `eee0ab3 Add ARGUS-0003 guided daily workflow design`
- Merge mode: fast-forward only
- Push: none

## Files Changed

- `momentum_hunter/app.py`
- `tests/test_daily_workflow.py`
- `docs/argus-office/reports/releases/ARGUS-0004-guided-daily-workflow-stepper.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CURRENT_STATE.md`
- `docs/argus-office/CHANGELOG_ARGUS.md`

## What Changed On Screen

The existing Daily Workflow modal is now titled `Guided Daily Workflow` and leads with:

1. The existing trust/capture banner.
2. Today's workflow score with conservative completion wording.
3. A dominant trust/blocker state.
4. A `Next Required Action` band.
5. A visible five-step sequence:
   - Capture Health
   - Morning Review
   - Watchlist Plans
   - Watchlist Report
   - Readiness Gate
6. Step cards with status lights, dependencies, blockers, and existing quick actions.
7. The previous checklist/warnings tables demoted into `Audit Details` and `Warning Detail` tabs.

## Sequence, Dependencies, Lights, And Next Action

The new stepper uses existing facts only:

- `DailyWorkflowReport` for review counts, entry-plan counts, capture status, workflow warnings, and readiness statuses.
- `OperatorReviewContext` for review/watchlist action eligibility and block reasons.
- `DataViewStyle` for current, aging, stale, historical, or study trust posture.
- Existing quick-action handlers for Morning Review, Watchlist Report, Capture Health, and Readiness Gate.

Status lights use conservative display states: green complete, blue active next action, yellow attention, red blocked, gray waiting/locked.

The Readiness Gate is shown as a check/gate only. It does not approve trades and does not change readiness logic.

## Protected Areas

No changes were made to scoring logic, trade readiness logic, replay identity rules, historical capture selection, SQLite/database schema or migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, package/dependency files, generated data, market data/report outputs, or production config.

## Tests Or Checks Run

- `.\.venv\Scripts\python.exe -B -m unittest tests.test_daily_workflow`

Result: passed.

## Manual QA

1. Launch Momentum Hunter on `codex/ARGUS-0004-guided-daily-workflow-stepper`.
2. Open the Dashboard and click `Daily Checklist`.
3. Confirm the modal title is `Guided Daily Workflow`.
4. Confirm the top of the modal shows the trust/banner state, workflow score, trust/blocker band, and `Next Required Action` band.
5. Confirm the sequence appears in order: Capture Health, Morning Review, Watchlist Plans, Watchlist Report, Readiness Gate.
6. Confirm each step shows a status light, dependency, blocker, and explanatory text.
7. Confirm `Open Morning Review`, `Generate Watchlist Report`, `Open Capture Health`, and `Open Readiness Gate` remain visible and route to the same existing workflows.
8. In a historical or study/read-only view, confirm Morning Review and Generate Watchlist Report remain disabled and the trust blocker explains why.
9. Confirm `Audit Details` and `Warning Detail` tabs still show the previous checklist facts and warning meanings.
10. Confirm no new Dashboard page, left-rail item, or full cockpit redesign was added.

## Risks

- The guided display logic is intentionally conservative and may label some downstream steps as waiting even though existing buttons remain visible for continuity.
- The Watchlist Report step cannot know whether a report was already generated because no new state was introduced.
- The Readiness Gate remains visually part of the flow, but only as a read-only check/gate. Copy must continue to avoid implying trade approval.

## Open Questions

- Should the next task promote the modal bridge into a first-class Dashboard cockpit, or should Steven review the modal bridge for a few sessions first?
- Should future work add a display-only "latest watchlist report generated" fact if an existing safe report artifact can be read without new state?

## Recommendation

Merge after Steven manually confirms the modal now makes the next required action, blockers, and step sequence clear. Do not promote to a full Dashboard cockpit until Steven approves that product move.
