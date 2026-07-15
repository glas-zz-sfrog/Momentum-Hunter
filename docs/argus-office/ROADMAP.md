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
| Active product decision | The approved R004 workstation and authoritative Roadmap are preserved together on `codex/ARGUS-INTEGRATE-roadmap-r004` at `d3a98d9`; local `master` remains unchanged pending Steven's separate fast-forward approval. |
| Active implementation | `ARGUS-R005` on `codex/ARGUS-R005-background-tray-lifecycle`, based on the verified integration commit `d3a98d9`. |
| R004 status | `IMPLEMENTED_PENDING_MASTER_MERGE`: the WPF shell is accepted in the remote-backed integration history; it is not yet merged to local `master`. |
| R005 status | `ACTIVE`: build the close-to-tray lifecycle and deterministic in-process background-collection controls without claiming independent engine hosting. |
| Immediate next action | Implement and hard-chew R005: explicit hide, pause, resume, scan, status, restore, single-instance, and exit behavior for the WPF host. |
| Next build after R005 acceptance | Phase 8: define versioned contracts and an independent Python engine host that survives WPF restart, disconnect, and failure. |
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

Status: `ACTIVE` through R005 lifecycle validation

- Preserve Python as the canonical engine for research, scoring, readiness, replay, storage, trade planning, risk, and simulation.
- Use the Windows-first .NET WPF workstation shell as the architecture feasibility path before committing more effort to Qt modernization.
- Do not treat the WPF shell as a Python rewrite or as broker integration.
- Do not start a new PySide-first modernization track while the WPF direction is being evaluated.
- Require Windows system-tray integration, close-to-tray behavior, persistent in-process monitoring while the workstation is hidden, exact layout restoration, single-instance activation, reliable tray cleanup, visible background health, and safe session-ending behavior before accepting the shell as the operator surface.
- Keep Hide, Pause Monitoring, and Exit as separate lifecycle operations. Tray or layout state must never store execution authorization, credentials, API keys, broker permissions, or order-routing permissions.

### Phase 6 - Python Simulation Foundation And Evidence Research

Status: `COMPLETE` on local `master`

- `momentum_hunter/autonomy/*`, `trade_planning.py`, and the current Python UI modules remain the canonical implementation on `master`.
- The clean-room simulation foundation and hardening tests are merged on `master`.
- Technical Breakout Research Engine v1 and its daily OHLC source are merged on `master`; they remain research-only and do not alter production scoring or execution behavior.
- The older standalone execution-model branch and earlier simulation branch are superseded; see `BRANCH_LEDGER.md`.

### Phase 7 - Build And Hard-Chew The Workstation Shell

Status: `ACTIVE`

- R004 provides the WPF shell spike: docked, tabbed, floating, resizable panes; linked chart contexts; saved layouts; SQLite autosave and recovery; Live, Replay, and Review workspaces; and simulation-only safety language.
- R004 adds contextual Machine Room panes for Research, Watchlist, Automation, Diagnostics, Orders, and Positions without adding broker capability.
- R004 is implemented in the accepted integration history, pending Steven's separate local-master fast-forward decision; it is not a production-frontend declaration.
- R005 is active: add WPF close-to-tray behavior, deterministic in-process background collection while hidden, explicit Pause, Resume, Run Scan Now, Open, Status, and Exit controls, one-instance activation, lifecycle tests, and UI proof.
- R005 prepares the future engine boundary but does not claim that Python collection survives WPF application exit, crash, or restart.
- Physical multi-monitor/DPI validation and a real Python engine bridge remain future proof obligations.

### Phase 8 - Headless Python Engine Through Versioned Contracts

Status: `NOT_STARTED`

- Define versioned, read-only contracts that let the WPF shell request discovery, research, health, replay, and simulation data from the canonical Python engine.
- Keep the boundary explicit, local, observable, and free of credentials or broker transmit behavior.
- Prove contract compatibility before moving any existing product workflow into the WPF shell.
- Run Python as a genuinely independent engine process: WPF must connect to an already-running host, disconnect or restart without stopping it, reconnect without duplicate loops, and query health and monitoring state through versioned contracts.
- Make Pause, Resume, and engine shutdown explicit and auditable. Prevent duplicate engine-host processes. Prove that closing or crashing WPF does not stop scheduled Python collection.

### Phase 9 - Read-Only Discovery, Research, Health, And Replay Integration

Status: `NOT_STARTED`

- Connect WPF panes to the Phase 8 read-only boundary for candidates, evidence, research context, health, and replay.
- Preserve source lineage, stale-data language, and read-only replay identity.
- Use the independent engine lifecycle rather than a workstation-owned collection loop.

### Phase 10 - Trade Planning, Risk, And Simulation Integration

Status: `NOT_STARTED`

- Connect TradePlan, Risk Governor, Simulation, Execution Ledger, and Execution Auditor through the versioned Python boundary.
- Preserve FakeBroker-only simulation and require risk evidence before any simulated lifecycle action.
- Use the same independent engine lifecycle and preserve the simulation-only execution boundary.

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
