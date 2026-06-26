# Argus Directive Order Ledger

Generated: 2026-06-26

Purpose: reconcile the major Argus/Momentum Hunter directives, their intended order, actual completion state, known commits, remaining gaps, and recommended next action before continuing additional feature work.

This ledger is a project-control document. It does not change scanner logic, scoring, readiness rules, alert thresholds, outcome classification, trade-planning rules, SQLite authority, or raw captures.

## Current Sprint Context

Active sprint: Roadmap Reconciliation and Autonomous Closure Sprint v1.

Latest completed checkpoint before this ledger:

- `68d77dc` - Document roadmap reconciliation sprint
- SQLite validation before this ledger: PASS, schema version 7
- SQLite shadow/read-model reports before this ledger: PASS
- Focused non-Qt baseline tests before this ledger: 44 tests passing

File-authoritative rule remains active: raw captures and user-authored review/watchlist/entry-plan files remain source of truth. SQLite remains additive and diagnostic unless a later explicit cutover is approved.

## Directive Ledger

| # | Directive | Intended order | Actual status | Known commit(s) | Order followed? | Risk | Recommended next action |
| ---: | --- | --- | --- | --- | --- | --- | --- |
| 1 | Operator Dashboard Redesign v1 | First UI migration after Gate 0 | Partial | `3187a1f`, `e113716`, plus later UI fixes | Partially | High | Do not continue broad visual redesign until Phase 1B gaps are verified. |
| 2 | Phase 1B Critical Workflow Stabilization | Before Phase 2 layout redesign | Partial / needs verification | `3187a1f`; documented in `docs/CHANGELOG.md` and `docs/PRE_1B_CONTROL_STATUS.md` | Mostly | High | Run a focused verification/fix pass on checkbox safety, canonical watchlist actions, research responsiveness, and Why Score formatting. |
| 3 | Candidate Story / Graph-First Timeline Redesign | After replay stability | Complete enough for current use | `86516b8` | Yes | Medium | Preserve current Candidate Story behavior; only do focused polish and tests. |
| 4 | Candidate Story UI Polish | After Candidate Story redesign | Partial | `a281a25` | Yes | Medium | Fix remaining chart readability only if contained; do not add intraday/5D charting. |
| 5 | Autonomous Reliability Sprint v1 | After evidence/autopilot foundation | Mostly complete, ongoing hardening remains | `8f19951`, `ecadc93` | Yes | Medium | Verify reports are truthful and current; fold into System Readiness and Evidence Autopilot checks. |
| 6 | SQLite Migration Foundation v1 | Before SQLite slices | Complete | `938f820` | Yes | Medium | Keep SQLite additive; no runtime cutover. |
| 7 | SQLite Evidence Slice v1 | After SQLite foundation | Complete | `b93f815` | Yes | Medium | Preserve JSON source of truth; next evidence storage slice was minute bars. |
| 8 | SQLite Evidence Backbone Program v1 | After evidence slice | Complete | `e2e11a1`, `0a69c8f`, `4264a28`, `0935f29`, `fb6256c`, `2f4855c`, `02a8007`, `114543e`, `dddbf18` | Yes | Medium | Use validation/shadow reports before trusting any SQLite read model. |
| 9 | SQLite User State Safety Cage v1 | Before any user-state cutover | Complete as safety mirror | `09ba39c`, `e2dee40` | Yes | High | Keep file-authoritative user state; report conflicts, never auto-resolve. |
| 10 | SQLite Read Model and Cutover Design v1 | After user-state safety cage | Complete as design/report layer | `f55e246` | Yes | Medium | Use as a design reference only; no UI/runtime cutover yet. |
| 11 | SQLite Read-Only Adoption / Shadow Mode | After read model design | Complete | `09104c2` | Yes | Medium | Keep default read model source as `file`; use `shadow` diagnostics. |
| 12 | Autonomous Backend Platform Sprint v2 | After reliability and SQLite backbone | In progress / this sprint | `68d77dc` plus future sprint commits | Active | High | Close testable backend/UI workflow gaps in order; avoid broad redesign and scoring changes. |

## Detailed Status By Directive

### 1. Operator Dashboard Redesign v1

Goal: move Momentum Hunter away from the Everything Dashboard toward a command-center model.

Evidence found:

- Gate 0 workflow preservation and screenshots were documented in `docs/OPERATOR_WORKFLOW_PRESERVATION.md`.
- Operator navigation cleanup is documented in `docs/ROADMAP_AUDIT.md` and `docs/CHANGELOG.md`.
- The app now has a left rail with Dashboard, Watchlist, Evidence, Research, Replay, and Health pages.
- A Back button and page-history behavior were added after the first navigation migration.

Completion status:

- Partially complete.
- The major workflow destinations exist.
- The full visible dashboard redesign is not complete enough to call finished.

Open items:

- Dashboard still needs final operator-first layout validation.
- Active nav styling, midnight-blue active canvas, and table prominence need visual verification.
- Evidence, research, and watchlist surfaces exist but may still feel like relocated tools rather than a polished command center.

Recommended next action:

- Treat broad layout redesign as deferred until the Phase 1B functional gaps are verified.

### 2. Phase 1B Critical Workflow Stabilization

Goal: fix operator workflow blockers without starting Phase 2 layout redesign.

Evidence found:

- `docs/CHANGELOG.md` says Phase 1B fixed checked-row preservation, duplicate top-bar Mark Interested, Clear Checkmarks relocation, Watchlist Center backing store, background Research/Readiness loading, and Why Score formatting.
- `docs/PRE_1B_CONTROL_STATUS.md` records targeted bounded probes and explicitly warns not to run broad Qt unittest modules.
- Tests referenced include provider errors, replay, outcome maturity, targeted UI probes, checkbox preservation, Watchlist Center persistence, non-blocking Research loading, and Why Score formatting.

Completion status:

- Partial.
- Documented fixes exist.
- Because the user later reported continuing UI confusion, this needs a current verification pass before Phase 2.

Open items needing direct verification:

- Checked boxes survive normal row selection, candidate-detail refresh, and misclicks near checkboxes.
- One workflow action has one canonical implementation for marking interested, rejected, and watchlist movement.
- Dashboard-to-Watchlist synchronization is immediate and backed by the same store.
- Research Lab and Readiness Gate do not freeze or leave the app Not Responding.
- Why Score dialog formatting is actually readable in the running app.

Recommended next action:

- Phase 2 of the current sprint should run focused non-hanging probes or small tests for these exact items, then fix only objective failures.

### 3. Candidate Story / Graph-First Timeline Redesign

Goal: make Timeline / Replay useful as a candidate story instead of a dense audit table.

Evidence found:

- `86516b8` - Add graph-first candidate story replay.
- `docs/CHANGELOG.md` records Candidate Story header, stored-capture trail chart, simplified rows, and preserving Advanced Capture Audit under Audit mode.
- Replay navigation fixes later made historical snapshots populate directly on the Replay page.

Completion status:

- Complete enough for current operator use.

Open items:

- Intraday and 5D charting remain intentionally deferred.
- Chart readability still needs visual polish if the current legend remains unreadable.

Recommended next action:

- Keep the story model; only polish readability if safe and bounded.

### 4. Candidate Story UI Polish

Goal: improve Candidate Story chart readability without changing timeline logic.

Evidence found:

- `a281a25` - Polish candidate story chart readability.
- User later still flagged the legend as unreadable in a screenshot.

Completion status:

- Partial.

Open items:

- Confirm whether chart legend chips/direct labels are readable in the actual running app.
- Improve legend contrast and axis readability if still poor.
- Keep Advanced Capture Audit available but secondary.

Recommended next action:

- Phase 10 of the current sprint may do this if earlier reliability phases are complete and the change is visual-only.

### 5. Autonomous Reliability Sprint v1

Goal: make evidence collection and system health measurable without tuning signals.

Evidence found:

- `8f19951` - Add autonomous reliability reports.
- `ecadc93` - Tighten reliability audit truthfulness.
- `docs/evidence-autopilot-reliability.md` documents that a completed status file does not prove a daemon is continuously running.
- Reports exist for provider/data quality, Evidence Autopilot reliability, and system readiness.

Completion status:

- Mostly complete.
- Reliability remains a living area because monitoring and evidence collection can fail over time.

Open items:

- Confirm current reports are current and not stale.
- Confirm Evidence Autopilot updates status and daily evidence brief consistently.
- Confirm System Readiness includes SQLite mirror and user-state safety visibility.

Recommended next action:

- Use Phases 5 and 6 of the current sprint to verify and close objective reporting gaps.

### 6. SQLite Migration Foundation v1

Goal: establish additive SQLite storage without changing source-of-truth behavior.

Evidence found:

- `938f820` - Add SQLite migration foundation.
- Schema, migration CLI, provider-quality import, and source-file immutability tests were added.

Completion status:

- Complete.

Open items:

- None for the foundation slice.

Recommended next action:

- Continue additive slices only; never make SQLite authoritative without an explicit cutover plan.

### 7. SQLite Evidence Slice v1

Goal: mirror opportunity alerts and alert outcomes into SQLite safely.

Evidence found:

- `b93f815` - Add SQLite evidence slice.
- Changelog records support for pending, completed, and terminal unscorable classifications.

Completion status:

- Complete.

Open items:

- Continue validating that JSON remains authoritative.

Recommended next action:

- Use SQLite only for read/report/shadow comparison until cutover is explicitly approved.

### 8. SQLite Evidence Backbone Program v1

Goal: expand SQLite mirrors across minute bars, evidence runs, status events, captures, and validation reports.

Evidence found:

- `e2e11a1` - Add SQLite minute bars slice.
- `0a69c8f` - Add SQLite evidence runs slice.
- `4264a28` - Add SQLite system status slice.
- `0935f29` - Add SQLite capture index slice.
- `fb6256c` - Add SQLite read-only query helpers.
- `2f4855c` - Document SQLite all-safe import workflow.
- `02a8007` - Add SQLite validation report.
- `114543e` - Add SQLite evidence backbone final report.
- `dddbf18` - Complete SQLite evidence backbone audit fixes.

Completion status:

- Complete for current additive backbone.

Open items:

- Keep validation reports part of every future SQLite-related sprint.

Recommended next action:

- Treat SQLite reports as diagnostic confidence tools, not runtime authority.

### 9. SQLite User State Safety Cage v1

Goal: mirror user-authored review/watchlist/entry-plan data safely without overwriting it.

Evidence found:

- `09ba39c` - Add user state backup safety tools.
- `e2dee40` - Add SQLite user state mirror.
- `docs/storage/sqlite-user-state-safety-cage-v1.md` says file-based state remains authoritative and conflicts must be reported, never auto-resolved.

Completion status:

- Complete as a safety cage.

Open items:

- No reverse sync from SQLite to files.
- No runtime adoption until conflict policy and recovery are explicit.

Recommended next action:

- Continue using dry-run diff and backup/restore reports before any future user-state migration.

### 10. SQLite Read Model and Cutover Design v1

Goal: design how SQLite read models could be used safely before cutover.

Evidence found:

- `f55e246` - Add SQLite read model reports.
- Read-model reports exist for Candidate Story, Evidence, Watchlist/Plans, System Readiness, and file-vs-SQLite comparison.

Completion status:

- Complete as report/design work.

Open items:

- Runtime UI remains file-based by design.

Recommended next action:

- Use read-model reports to validate parity; do not wire into live UI without shadow PASS and a narrow adoption milestone.

### 11. SQLite Read-Only Adoption / Shadow Mode

Goal: add safe read-only source resolution and shadow comparisons without changing runtime defaults.

Evidence found:

- `09104c2` - Add SQLite read-only adoption audit.
- `docs/storage/sqlite-read-only-adoption-final-report.md` reports validation PASS, shadow compare PASS, and default source mode `file`.
- Feature flags exist for `file`, `sqlite`, and `shadow` report-summary modes.

Completion status:

- Complete.

Open items:

- Feature flag is not wired into live UI workflows.

Recommended next action:

- Keep `file` default. Use `shadow` mode as a diagnostic guardrail.

### 12. Autonomous Backend Platform Sprint v2

Goal: close the objective gaps left after the UI and backend sprints without changing trading logic.

Evidence found:

- `68d77dc` created the current sprint report.
- Current sprint phases are still open after Phase 0.

Completion status:

- In progress.

Open items mapped to sprint phases:

- Phase 1: directive order ledger - this document.
- Phase 2: close Phase 1B workflow gaps.
- Phase 3: Research/Readiness responsiveness audit.
- Phase 4: reconcile SQLite read-only/shadow mode - already mostly completed by `09104c2`, but should be verified in sprint report.
- Phase 5: System Readiness engine gaps.
- Phase 6: Evidence Autopilot reliability gaps.
- Phase 7: Active Alert evidence hardening.
- Phase 8: test harness reliability.
- Phase 9: `app.py` modularization audit and only low-risk extraction.
- Phase 10: Candidate Story chart polish if safe.
- Phase 11: final validation and scoreboard.

Recommended next action:

- Continue to Phase 2 and fix only objective, testable workflow gaps.

## Cross-Cutting Open Items

### Must Verify Before More UI Redesign

- Checkbox and row-selection safety.
- Misclick behavior near checkboxes.
- Dashboard and Watchlist Center status synchronization.
- Canonical review/watchlist movement function.
- Research/Readiness non-blocking load behavior.
- Visible blocked-action feedback.
- Why Score dialog readability.
- Replay page candidate table population from historical snapshot.

### Must Preserve

- Raw captures are immutable.
- Review decisions and entry plans are derived/user-authored stores, not raw capture edits.
- Historical, Replay, and Study contexts remain read-only.
- SQLite remains additive and non-authoritative.
- JSON/CSV/Markdown outputs remain available.
- Alert/scoring/readiness/trade-planning logic remains unchanged unless a future directive explicitly approves it.

### Known Deferred Work

- Opportunity Score.
- Optimizer.
- Broker integration.
- Automated trading.
- Full SQLite source-of-truth cutover.
- Position management engine.
- Relative strength engine.
- Liquidity sweep/market structure validation.
- Intraday and 5D Candidate Story charting.
- Full Daily Review Dashboard merge.
- Watchlist Center v2.

## Current Recommended Order From Here

1. Phase 2: Focused Phase 1B verification and safe fixes.
2. Phase 3: Research/Readiness responsiveness audit.
3. Phase 4: Record SQLite read-only/shadow mode as complete in the sprint scoreboard.
4. Phase 5: System Readiness gaps.
5. Phase 6: Evidence Autopilot reliability gaps.
6. Phase 7: Active Alert evidence hardening.
7. Phase 8: Test harness reliability helper or documentation.
8. Phase 9: `app.py` modularization audit with only low-risk extraction.
9. Phase 10: Candidate Story chart polish if still needed.
10. Phase 11: Final validation, report, and commit summary.

## Phase 1 Acceptance Status

Phase 1 acceptance criteria:

- Major directives listed: PASS
- Intended order documented: PASS
- Actual completion status documented: PASS
- Known commit hashes captured where available: PASS
- Open risks and next actions documented: PASS
- No code behavior changed: PASS

