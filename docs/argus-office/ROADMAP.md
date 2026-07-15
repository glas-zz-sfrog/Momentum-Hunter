# Momentum Hunter Roadmap

## Authority

This is the single authoritative view of current product position, active work, and next work. Update its `Now` section from Git evidence before a task is reported complete, merged, or blocked.

Supporting records have narrower roles:

- `BRANCH_LEDGER.md` is the detailed Git and branch-evidence record.
- `TASK_LOG.md` and `CHANGELOG_ARGUS.md` are append-only history.
- Historical architecture notes and release reports remain evidence of their original decisions; they do not override this Roadmap.

## Now

Last reconciled: 2026-07-15 from local Git evidence.

| Item | Current truth |
| --- | --- |
| Canonical product baseline | Local `master` at `1180315 Add daily OHLC source for breakout research`; synchronized with `origin/master` (`0` behind, `0` ahead). |
| Active product decision | Review the WPF workstation-shell spike before any new product implementation. |
| Active implementation | `ARGUS-R004` on `codex/ARGUS-R004-momentum-hunter-wpf-shell-spike` at `5bbd0c7 Add contextual workstation panes`. |
| R004 status | `IMPLEMENTED_PENDING_MERGE`: four commits ahead of `master`, fast-forwardable, and synchronized with its remote branch. |
| Immediate next action | Steven reviews the R004 WPF shell evidence and decides whether to fast-forward merge it into local `master`. |
| Next build after R004 decision | Phase 8: define versioned, read-only Python engine contracts for the WPF shell. |
| Broker and execution state | No paper or live broker path, credentials, API keys, or real order path exists. Paper and live remain locked. |

### Status Legend

- `NOT_STARTED`: no implementation has begun.
- `ACTIVE`: work is underway on the named branch.
- `IMPLEMENTED_PENDING_MERGE`: work is committed and verified on a branch, but Steven has not approved its local merge.
- `COMPLETE`: work is merged into local `master` and verified.
- `BLOCKED`: a stated gate or CEO decision prevents work from starting.
- `DEFERRED`: valid future work, intentionally not the current priority.

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

Status: `COMPLETE` on local `master`

- Use neutral product terminology: Automation, Simulation, Machine Room, Risk Governor, Execution Ledger, Trade Plan, and operator review.
- Keep `Argus` as the Codex builder and office persona, not a product-screen or product-flow name.
- Retain the existing Python simulation foundation: TradePlan, Risk Governor, FakeBroker-only simulation, Execution Ledger, and Execution Auditor.
- Keep every paper and live execution boundary locked.

### Phase 5 - C# WPF Workstation-Shell Feasibility

Status: `ACTIVE` through R004 review

- Preserve Python as the canonical engine for research, scoring, readiness, replay, storage, trade planning, risk, and simulation.
- Use the Windows-first .NET WPF workstation shell as the architecture feasibility path before committing more effort to Qt modernization.
- Do not treat the WPF shell as a Python rewrite or as broker integration.
- Do not start a new PySide-first modernization track while the WPF direction is being evaluated.

### Phase 6 - Python Simulation Foundation And Evidence Research

Status: `COMPLETE` on local `master`

- `momentum_hunter/autonomy/*`, `trade_planning.py`, and the current Python UI modules remain the canonical implementation on `master`.
- The clean-room simulation foundation and hardening tests are merged on `master`.
- Technical Breakout Research Engine v1 and its daily OHLC source are merged on `master`; they remain research-only and do not alter production scoring or execution behavior.
- The older standalone execution-model branch and earlier simulation branch are superseded; see `BRANCH_LEDGER.md`.

### Phase 7 - Build And Hard-Chew The Workstation Shell

Status: `IMPLEMENTED_PENDING_MERGE`

- R004 provides the WPF shell spike: docked, tabbed, floating, resizable panes; linked chart contexts; saved layouts; SQLite autosave and recovery; Live, Replay, and Review workspaces; and simulation-only safety language.
- R004 adds contextual Machine Room panes for Research, Watchlist, Automation, Diagnostics, Orders, and Positions without adding broker capability.
- R004 is ready for Steven's merge decision, not a production-frontend declaration.
- Physical multi-monitor/DPI validation and a real Python engine bridge remain future proof obligations.

### Phase 8 - Headless Python Engine Through Versioned Contracts

Status: `NOT_STARTED`

- Define versioned, read-only contracts that let the WPF shell request discovery, research, health, replay, and simulation data from the canonical Python engine.
- Keep the boundary explicit, local, observable, and free of credentials or broker transmit behavior.
- Prove contract compatibility before moving any existing product workflow into the WPF shell.

### Phase 9 - Read-Only Discovery, Research, Health, And Replay Integration

Status: `NOT_STARTED`

- Connect WPF panes to the Phase 8 read-only boundary for candidates, evidence, research context, health, and replay.
- Preserve source lineage, stale-data language, and read-only replay identity.

### Phase 10 - Trade Planning, Risk, And Simulation Integration

Status: `NOT_STARTED`

- Connect TradePlan, Risk Governor, Simulation, Execution Ledger, and Execution Auditor through the versioned Python boundary.
- Preserve FakeBroker-only simulation and require risk evidence before any simulated lifecycle action.

### Phase 11 - Broker Research And Hardening Before Paper Execution

Status: `DEFERRED`

- A016 broker research remains valid but is not the immediate Builder priority.
- Begin broker research only after the WPF direction and Python engine boundary are proven enough to define a stable integration surface.
- No credentials, API keys, paper adapter, order routing, or paper execution code belongs in this phase without a separate Goal Charter.

### Phase 12 - Incremental Capability Migration And Qt Retirement

Status: `NOT_STARTED`

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
5. Cite the resulting Roadmap transition in the final CEO report.

## Protected Areas

Do not change core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior without explicit approval.
