# ARGUS-0003 Guided Daily Workflow Design Sprint

Date: 2026-06-27
Branch: `codex/ARGUS-0003-guided-daily-workflow-design`
Owner: Argus Orchestrator
Status: Complete, pending Steven review

## Executive Summary

Momentum Hunter has a visible Daily Checklist path, but it still behaves like a report with action buttons attached. The current UI answers "what facts exist?" better than it answers "what must happen next?" Steven's pain is valid: the operator must infer sequence, dependencies, and readiness from a table, a warning string, and several equal-weight buttons.

Recommendation: approve **Concept B: Modern Command Cockpit** as the product direction, but implement it in small reversible slices starting with **Concept A: Conservative Guided-Step Improvement** inside the existing Daily Workflow dialog. This protects current behavior while changing the operator experience from "collection of buttons" to "guided decision flow."

The core model should be: **make the next light click**. Every step should show its current state, its dependency, its blocker, the next action, and the proof that will turn the light green.

## Diagnosis Of Current Daily Workflow Pain

Current Daily Workflow pieces exist, but they do not yet form a guided product experience:

- The Dashboard shows `Daily Checklist`, `Morning Review`, `Generate Watchlist Report`, `Open Latest Watchlist`, `Capture Health`, and `Research Lab` as a horizontal strip of similar buttons.
- The Daily Workflow dialog shows a score, a warning line, a checklist table, a warnings tab, and four quick actions.
- The operator guidance label can say what to do next, but it is separate from the workflow buttons and does not visually explain dependencies.
- The checklist table is useful for audit facts, but it does not communicate time order, gate order, blocked paths, or "what makes the next light click."
- Warnings such as `REVIEWS INCOMPLETE`, `WATCHLIST HAS NO ENTRY PLAN`, `INCOMPLETE ENTRY PLAN`, and `READINESS GATE LOCKED` are present, but they are not mapped to the controls they block.

This creates the "buttons without meaning" problem. The operator can see possible actions but cannot quickly see which action matters now, which action is unavailable, and what evidence must change before the next step works.

## Current Operator Journey Map

1. Operator opens Momentum Hunter on the Dashboard.
2. Operator runs or loads a current scan/capture.
3. Dashboard shows the current trust banner and a Daily Workflow button row.
4. Operator clicks `Daily Checklist`.
5. Dialog opens with workflow score, warnings, checklist metrics, warnings tab, and quick actions.
6. Operator manually interprets the table and warning labels.
7. Operator chooses one of four quick actions: `Open Morning Review`, `Generate Watchlist Report`, `Open Capture Health`, or `Open Readiness Gate`.
8. If an action is blocked, the existing guard may explain why, but the blocked dependency was not visually obvious before clicking.

## Proposed Operator Journey Map

1. Operator opens Momentum Hunter and sees a clear **Start Here** workflow strip on the Dashboard.
2. The strip shows the current daily sequence: `Capture Health -> Morning Review -> Watchlist Plans -> Watchlist Report -> Readiness Gate`.
3. One step is visually active in blue. Completed steps are green. Attention-needed steps are yellow. Blocking trust failures are red. Unavailable/read-only steps are gray or locked.
4. The Dashboard shows one high-priority **Next Best Action** with the exact reason it matters.
5. Opening Daily Workflow shows a guided cockpit, not a table-first report.
6. Each step card/gate explains:
   - current status,
   - dependency,
   - blocker if any,
   - proof needed to turn green,
   - the safest action button.
7. Missing or stale data takes over the top of the flow before review/watchlist/readiness choices are presented.
8. Operator completes the active step and sees the next step become active without guessing.

## Make The Next Light Click Model

The future Daily Workflow should use a simple mental model:

| Light | Meaning | What The UI Must Show |
| --- | --- | --- |
| Off / gray | Not available yet or not applicable in this view | The dependency that must be satisfied first |
| Red | Trust blocker or failed required input | The failure, source, and safest recovery action |
| Yellow | Action needed but workflow can proceed to this step | The exact unfinished work |
| Blue | Current next required action | One primary action and why it is next |
| Green | Complete or ready | The fact/proof that made it ready |
| Locked | Research/readiness gate unavailable | The evidence requirement, without implying changed readiness logic |

Rules:

- One step owns priority at a time.
- Trust blockers outrank normal workflow progress.
- "No candidates" is not the same as "capture failed."
- Readiness locks are research/evidence maturity states, not trade execution permission changes.
- The workflow score remains discipline-only and must never look like trade quality.

## Concept A: Conservative Guided-Step Improvement

### Visual Metaphor

A guided checklist rail: a calm stepper that keeps the current modal but turns the table into a sequence.

### Layout Description

Keep the `Daily Workflow Checklist` dialog. Replace the table-first body with a top "Next Required Action" band, a horizontal or vertical stepper, and expandable step details. Keep the existing table as an "Audit Details" tab for evidence.

### Primary Screen Regions

- Top trust banner: current capture/view trust state.
- Next action band: one sentence, one primary button, one blocker if present.
- Stepper region: Capture Health, Morning Review, Watchlist Plans, Watchlist Report, Readiness Gate.
- Detail panel: selected step facts, dependencies, and explanation.
- Audit details: current metrics table for traceability.

### How Sequence Is Communicated

Steps are ordered left-to-right or top-to-bottom with connecting lines. The active step is blue and visually larger. Completed prior steps are green. Later steps are muted until their dependencies are met.

### How Dependencies Are Communicated

Each step has a "Depends on" line and an optional "Blocked by" line. A blocked downstream action points back to the unmet upstream step instead of leaving the operator to infer it.

### How Readiness Lights Work

Each step gets a status light using current report data and existing operator context. Green means the step's existing facts are complete. Yellow means operator work remains. Red means a trust blocker. Locked means a research/readiness gate is unavailable.

### How The Next Required Action Is Shown

The dialog top band says, for example: "Next: Review 4 unreviewed candidates to unlock watchlist generation." The primary button is `Open Morning Review`.

### How Blocked/Unavailable Actions Explain Themselves

Disabled buttons keep visible reason text nearby: "Generate Watchlist Report is blocked because no candidates are marked Watchlist." Do not hide unavailable actions; explain them.

### How Color, Background, Spacing, Lines, Or Cards Guide The Operator

Use a restrained operations palette: red for blockers, yellow for attention, blue for active, green for complete, gray for unavailable. Use thin connector lines between steps and generous spacing so the flow is readable at a glance.

### How Missing/Stale Data Dominates Attention

If capture is missing, failed, stale, quarantined, expired, or read-only, the top banner becomes the dominant red/yellow state and downstream workflow cards are muted until the trust issue is resolved or acknowledged.

### Risks / Tradeoffs

- Lowest implementation risk.
- Best bridge from current code.
- May still feel modal/report-like if the table remains too prominent.
- Does not fully solve Dashboard-level button sprawl unless paired with a small Dashboard strip.

## Concept B: Modern Command Cockpit

### Visual Metaphor

An operator cockpit: one first-class workflow surface that shows mission state, next action, and supporting evidence without feeling theatrical.

### Layout Description

Promote Daily Workflow into a dedicated cockpit surface reached from the Dashboard. The cockpit is not just a modal. It is a structured operator command view that sits above the existing workflows and routes to them.

### Primary Screen Regions

- Left workflow rail: Capture, Review, Plans, Report, Readiness.
- Center action panel: current step, primary action, blocker, proof needed.
- Right evidence panel: capture time, candidate counts, review counts, watchlist/plan status, readiness sections.
- Bottom activity/action bar: latest state change, safe quick actions, read-only disclaimer.

### How Sequence Is Communicated

The rail gives each step a fixed place and state. The center panel always corresponds to the active rail step. Connecting background lines can show flow direction without clutter.

### How Dependencies Are Communicated

Each downstream step visibly references its upstream requirement. Example: "Watchlist Report waits for: at least one Watchlist candidate and complete required entry-plan fields."

### How Readiness Lights Work

Readiness lights become a compact status stack: `Trust`, `Candidates`, `Review`, `Plans`, `Report`, `Research Readiness`. The operator can see the whole chain without reading a table.

### How The Next Required Action Is Shown

The center panel owns one primary button. The label is action-oriented: `Review Candidates`, `Complete Entry Plans`, `Generate Watchlist Report`, `Open Capture Health`, or `Open Readiness Gate`.

### How Blocked/Unavailable Actions Explain Themselves

Unavailable actions stay visible but locked. The cockpit says what must happen first and links to the relevant upstream step. A blocked state should answer "why can't I click this yet?" before the operator asks.

### How Color, Background, Spacing, Lines, Or Cards Guide The Operator

Use full-width bands rather than nested cards. A subtle flow line should move from left rail to center action to right evidence. Status colors should sit around steps, not simply color random table cells.

### How Missing/Stale Data Dominates Attention

Trust failures replace the center action panel. The cockpit should not show normal review/watchlist momentum while the system is saying "do not trust this capture/view." Recovery actions take priority.

### Risks / Tradeoffs

- Best answer to Steven's "modern dashboard" and "flow chart" feedback.
- More product decision weight than Concept A.
- May require deciding whether Daily Workflow becomes a first-class page, which ARGUS-0002 intentionally did not do.
- Needs careful copy so the cockpit is not mistaken for new trading logic.

## Concept C: Bold Launch-Sequence / Mission-Flow Redesign

### Visual Metaphor

A launch sequence: daily operation moves through gates from "data captured" to "workflow cleared." This is the strongest visual version of "make the next light click."

### Layout Description

The screen presents a mission-flow path with gates: `Data Captured`, `Candidates Reviewed`, `Plans Armed`, `Watchlist Built`, `Readiness Cleared`. The current gate expands. Prior gates lock green. Failed gates stop the sequence.

### Primary Screen Regions

- Mission status header: Hold, Proceed, or Cleared.
- Gate path: large connected gates with visible dependencies.
- Current gate console: evidence, blocker, action.
- Trust override panel: capture/read-only/stale/quarantine warnings.
- Audit drawer: raw checklist facts.

### How Sequence Is Communicated

The sequence is the interface. Lines and gate positions show what must happen before the next light can click.

### How Dependencies Are Communicated

Each gate cannot visually open until upstream gates are satisfied. The UI text names the exact dependency: "Plans Armed waits for Watchlist candidates."

### How Readiness Lights Work

Lights are more prominent and emotionally legible: red hold, yellow attention, blue active, green cleared, gray standby, locked research gate.

### How The Next Required Action Is Shown

The current gate contains the single primary command and the exact completion condition. Example: "Complete 2 entry plans. Add trigger, stop, invalidation, and max loss."

### How Blocked/Unavailable Actions Explain Themselves

Blocked gates show a short stop reason, not a disabled mystery button. Example: "Hold: capture is stale. Refresh or load current capture before review."

### How Color, Background, Spacing, Lines, Or Cards Guide The Operator

Use strong directional lines and surrounding color fields. Avoid novelty styling; the launch metaphor should serve clarity, not decoration.

### How Missing/Stale Data Dominates Attention

The sequence enters `HOLD` and downstream gates fade. The recovery action becomes the only primary action until trust is restored.

### Risks / Tradeoffs

- Most memorable and intuitive if done well.
- Highest risk of feeling too dramatic for daily investing operations.
- Could imply operational enforcement if copy is not precise.
- Should not be the first implementation slice unless Steven explicitly wants the bolder product direction.

## Specific Recommendation For The Daily Workflow Dialog

Use the dialog as the first safe implementation target. In the first Builder slice, do not create new state, do not change logic, and do not alter readiness/scoring semantics. Reuse `DailyWorkflowReport`, `OperatorReviewContext`, `DataViewStyle`, and existing quick-action handlers.

| Item | Recommended Form | Status States | Depends On | Missing Dependency UI |
| --- | --- | --- | --- | --- |
| Capture Health | Gate and trust banner | Healthy, Attention, Failed, Missing, Stale, Read-only | `CaptureHealthSnapshot`, current data view style/context | Red/yellow banner with `Open Capture Health` as primary action; downstream cards muted |
| Morning Review | Step card | Not started, In progress, Complete, Blocked, Read-only | Reviewable current capture and candidate availability | Explain "No reviewable current capture" or "No candidates available"; show source capture status |
| Watchlist Plans | Step card/gate | No watchlist, Plan needed, Incomplete, Complete, Blocked | At least one Watchlist candidate; entry-plan fields | Explain which candidates/plans are missing trigger, stop, invalidation, or max loss |
| Watchlist Report | Gate/action card | Unavailable, Ready to generate, Generated/latest available, Blocked | Watchlist candidates and acceptable operator context | Keep button visible but locked with reason: "Mark candidates as Watchlist first" |
| Readiness Gate | Research gate | Locked, Warning, Ready, Unknown | Outcome maturity/readiness report data | Label as research/evidence maturity; show evidence requirement without implying changed trade readiness |

The dialog should be renamed only if Steven approves. `Daily Workflow` or `Daily Command` may feel more modern than `Daily Workflow Checklist`, but this is a product naming decision.

## Specific Recommendation For The Main Dashboard

The Dashboard should show a small guided workflow strip before the operator opens the dialog.

- **Start here:** put a visually distinct `Start Daily Workflow` / `Daily Workflow` entry at the beginning of the daily row, with a state light and short next-action text.
- **Blocked:** show the highest-priority blocker beside the workflow entry, not buried in the modal. Example: "Blocked: stale capture" or "Blocked: no Watchlist candidates."
- **Ready:** show "Ready: generate watchlist report" only when the existing report/action contracts say it is available.
- **Next best action:** show one sentence and one primary command. Example: "Next: review 4 candidates" with `Morning Review` as the emphasized action.

Dashboard hierarchy should make the Daily Workflow group feel intentional:

1. Trust banner.
2. Daily Workflow strip with state light and next action.
3. Candidate/review work area.
4. Research/readiness panels.

## Trust-State Language

Use these phrases as the starting copy system:

| Trust State | Operator Language | Visual Priority |
| --- | --- | --- |
| Capture missing | "No current capture is loaded. Load or run a current capture before daily review." | Red blocker |
| Stale capture | "This capture is stale for daily workflow. Refresh current data before creating a new watchlist." | Red or yellow blocker, depending on existing context |
| Capture failed | "Last scheduled capture failed. Open Capture Health for details before trusting today's workflow." | Red blocker |
| No candidates | "Capture is available, but no review candidates were found." | Yellow attention, not data failure |
| Unreviewed candidates | "Review incomplete: mark remaining candidates Interested, Rejected, or Watchlist." | Yellow active workflow |
| Watchlist unavailable | "No Watchlist candidates selected. Mark at least one candidate Watchlist before generating the report." | Yellow/locked action |
| Entry plan incomplete | "Watchlist plans incomplete: add trigger, stop, invalidation, and max loss." | Yellow blocker for workflow completion |
| Readiness blocked | "Readiness research gate locked: outcome evidence requirement is not met yet." | Locked research gate |
| Execution-ready | "Execution-ready items present in the existing report. Review evidence before any trading decision." | Green evidence state with caution copy |
| Historical/read-only | "This view is read-only and cannot create a new daily watchlist." | Gray locked state |
| User-state safety warning | "User-state mirror needs attention. File-backed review/watchlist records remain authoritative." | Yellow trust warning |

## First 5 Small Builder Implementation Slices For Later

1. **Dialog stepper shell:** replace the checklist table-first layout with a read-only stepper that still uses `build_daily_workflow_report()` and current quick-action handlers. Keep the existing table as an audit tab.
2. **Next required action band:** derive a single display-only next action from existing report/context facts and show the matching existing quick action.
3. **Blocked-action explanations:** keep unavailable buttons visible with inline dependency reasons, preserving existing guards and handlers.
4. **Dashboard workflow strip:** convert the current Daily Workflow button row into a small sequence/status strip with one emphasized next action.
5. **Stable test identifiers and state labels:** add object names/status labels for steps so QA can verify state without screenshot-only assertions.

## First 5 QA Checks / Tests For Later

1. Verify the guided UI renders the same `DailyWorkflowReport` facts as the current checklist: score, review counts, entry-plan counts, warnings, capture status, and readiness statuses.
2. Verify each guided step exposes stable labels/object names and state values: current, complete, blocked, locked, attention, or read-only.
3. Verify quick actions still dispatch only to existing handlers: Morning Review, Generate Watchlist Report, Capture Health, and Readiness Gate.
4. Verify operator context gating is preserved for current, historical, study/research, expired, missing, failed, and read-only contexts.
5. Verify opening and navigating the guided workflow does not mutate raw capture JSON/Markdown, review decisions, entry plans, watchlists, database files, scoring, readiness gates, or alert thresholds unless the operator invokes an existing write workflow.

## Questions For Steven

1. Should Daily Workflow remain a modal for now, or should it become a first-class Dashboard page after the guided-step bridge?
2. Should the end state be called "Daily discipline complete," "Ready to generate watchlist," or something else?
3. Do you prefer calm command-cockpit language or the bolder launch-sequence metaphor?
4. Should Readiness Gate be visually part of the daily workflow, or clearly separated as research/evidence maturity?
5. Should a failed User-State Safety section visually block watchlist generation, or warn while file-authoritative workflows remain usable?

## Recommended CEO Decision

Approve **Concept B: Modern Command Cockpit** as the target product direction, with **Concept A** as the first Builder implementation slice. Do not start with Concept C unless Steven explicitly wants a more dramatic launch-sequence product feel.

The next approved Builder task should be narrow: redesign the existing Daily Workflow dialog into a guided stepper using current data and handlers only. No scoring, readiness, replay, schema, alert, broker/order, generated-data, or runtime behavior should change.

## Role Coordination Summary

- `ui_operator_designer`: Recommended Concept B as the strongest product direction, phased through Concept A.
- `code_mapper`: Mapped current flow to `momentum_hunter/app.py`, `momentum_hunter/daily_workflow.py`, and `tests/test_daily_workflow.py`; warned that a full page needs Steven approval.
- `data_integrity_reviewer`: Defined trust-state dominance: trust blockers, no candidates, unreviewed candidates, watchlist unavailable, entry-plan incomplete, readiness locked, storage trust warnings.
- `qa_regression`: Recommended state/action/context/no-mutation tests, with screenshots only as layout sanity evidence.
- `release_scribe`: Consolidated the design sprint into this CEO-ready report.

## Agent Report

### Branch

`codex/ARGUS-0003-guided-daily-workflow-design`

### Scope

Creative, read-only UI design sprint for Momentum Hunter Daily Workflow. Documentation only.

### Files Changed

- `docs/argus-office/reports/audits/ARGUS-0003-guided-daily-workflow-design.md`
- `docs/argus-office/TASK_LOG.md`
- `docs/argus-office/CURRENT_STATE.md`

### Tests Or Checks Run

- `git status --short --branch`
- `git merge-base HEAD master`
- `git rev-parse master`
- `Test-Path` checks for `AGENTS.md`, `.codex/agents/`, and `docs/argus-office/`
- Read-only `rg` mapping of Daily Workflow, Dashboard, tests, and office docs
- Visual inspection of existing Daily Workflow and Dashboard screenshots

No application tests were run because this was a design/specification-only docs task.

### Risks

- Promoting Daily Workflow to a full page may conflict with the ARGUS-0002 minimal Dashboard-modal approach unless Steven approves the product move.
- New visual state language could be mistaken for changed readiness/scoring logic if copy is not explicit.
- A future implementation could accidentally duplicate workflow logic instead of reusing existing report/context contracts.

### Manual QA

Not applicable for this design-only report. Future UI implementation should receive manual QA on the Dashboard workflow strip, guided dialog, blocked states, and read-only contexts.

### Open Questions

See "Questions For Steven" above.

### Recommendation

Approve Concept B as the direction and authorize a small Builder slice for Concept A first: a guided-step replacement for the current Daily Workflow dialog, reusing existing data and actions.
