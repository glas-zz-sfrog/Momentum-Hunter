# Momentum Hunter Roadmap

## Authority

This is the single authoritative view of current product position, active work, and next work. Update its `Now` section from Git evidence before a task is reported complete, merged, or blocked.

Supporting records have narrower roles:

- `BRANCH_LEDGER.md` is the detailed Git and branch-evidence record.
- `TASK_LOG.md` and `CHANGELOG_ARGUS.md` are append-only history.
- Historical architecture notes and release reports remain evidence of their original decisions; they do not override this Roadmap.

## Now

Last reconciled: 2026-07-17 from the completed Phase 9 stacked-branch verification; `master` remains unchanged.

| Item | Current truth |
| --- | --- |
| Canonical product baseline | `master` and `origin/master` are synchronized at `30c0e0b Reconcile roadmap after R004 and R005 integration` (`0` behind, `0` ahead); verified tree `388b410727aefe9f65bd94bac8fa589e408ea787`. |
| Active product decision | The Windows-first WPF workstation is the accepted operator-surface direction, while Python remains the canonical trading and evidence engine. |
| Active implementation | Phase 8 is `IMPLEMENTED_PENDING_MERGE` on `codex/ARGUS-R008-python-engine-contract-host`, based on `30c0e0b`. It has independent Python-host and WPF-bridge milestones, focused process proof, and remote feature-branch backup. |
| Active successor implementation | Phase 9 is `IMPLEMENTED_PENDING_MERGE` on `codex/ARGUS-R009-readonly-workstation-integration`, intentionally stacked from verified Phase 8 tip `6f853ba`. It connects only persisted Python evidence snapshots to WPF and keeps Phase 10 planning/simulation unavailable. |
| R004 status | `COMPLETE`: workstation-shell feasibility is integrated into `origin/master`. |
| R005 status | `COMPLETE`: close-to-tray, lifecycle controls, single-instance activation, and physical Windows tray QA are integrated into `origin/master`. |
| Immediate next action | Steven reviews the Phase 8 + Phase 9 fast-forward stack for integration into `master`. Do not begin another successor phase until that stack is merged or Steven explicitly directs otherwise. |
| Next build after the stack | Phase 10: attach TradePlan, Risk Governor, FakeBroker-only simulation, Execution Ledger, and Execution Auditor only after the read-only boundary is merged and reviewed. |
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

Status: `IMPLEMENTED_PENDING_MERGE` on `codex/ARGUS-R008-python-engine-contract-host`

- The approved Goal Charter creates versioned, provider-neutral host identity, health, collection, capability, command, and structured-error contracts.
- `momentum_hunter/engine_host.py` owns the independent loopback-only Python Engine Host. WPF discovers an existing host or launches one, reconnects by host identity, and deliberately shuts it down only on explicit Exit.
- The host has an atomic single-host lease, per-command idempotency, non-overlapping cycle guard, and a guard against the existing active-monitor runner starting a second collection loop.
- The exposed command surface is only snapshot, pause, resume, run one collection cycle, and graceful shutdown. Candidate, research, Replay, TradePlan, Risk Governor, simulation, broker, Paper, and Live workflows do not cross this boundary.
- Focused Python process proof and .NET integration proof passed. The branch is pushed; no merge has occurred. See `reports/releases/ARGUS-R008-python-engine-contract-host.md`.

### Phase 9 - Read-Only Discovery, Research, Health, And Replay Integration

Status: `IMPLEMENTED_PENDING_MERGE` on `codex/ARGUS-R009-readonly-workstation-integration` (stacked from `codex/ARGUS-R008-python-engine-contract-host` at `6f853ba`)

- Connect WPF panes to the Phase 8 read-only boundary for candidates, evidence, research context, health, and replay.
- Preserve source lineage, stale-data language, and read-only replay identity.
- Use the independent engine lifecycle rather than a workstation-owned collection loop.
- The first slice exposes persisted report/status snapshots only and explicitly disables mock TradePlan, chart, risk, and simulation fallback until Phase 10.
- Focused Python tests, focused C# presentation/integration tests, a C#-to-Python host proof, broader nearby Python regression, the full .NET suite, and full Python discovery passed before branch review.

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
