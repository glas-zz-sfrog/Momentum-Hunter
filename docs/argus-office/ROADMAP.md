# Momentum Hunter Roadmap

## Authority

This is the single authoritative view of current product position, active work, and next work. Update its `Now` section from Git evidence before a task is reported complete, merged, or blocked.

Supporting records have narrower roles:

- `BRANCH_LEDGER.md` is the detailed Git and branch-evidence record.
- `VERIFICATION_QUEUE.md` is the exact deferred Steven-check list; it does not replace Roadmap state or authorize merges.
- `TASK_LOG.md` and `CHANGELOG_ARGUS.md` are append-only history.
- Historical architecture notes and release reports remain evidence of their original decisions; they do not override this Roadmap.

## Now

Last reconciled: 2026-07-23 on `codex/ARGUS-SHADOW-002-wpf-shadow-review` after fetching `origin` and verifying all named Shadow/R012/R026 refs and merge bases. ARGUS-SHADOW-001 passed clean-room verification and fast-forwarded into local `master` at `bb962be`; its local and remote feature tips match. Local `master` is three commits ahead of `origin/master` at `69feedf`; no master push occurred. ARGUS-SHADOW-002 implementation is committed at `7fee390`, with this Roadmap reconciliation carried on the same branch; it remains `IMPLEMENTED_PENDING_MERGE`. R012 equals `origin/master`; R026 is a clean, unpushed parallel line whose merge base with both local `master` and Shadow-002 is `69feedf`. The official Shadow sample has not started and may not start until Shadow-002 is accepted and integrated and every sample-start lock below is proven.

| Item | Current truth |
| --- | --- |
| Canonical product baseline | Local `master` at `bb962be` contains the Phase 10 foundation, R011/R012 chart work, and the integrated ARGUS-SHADOW-001 prospective Shadow Trading foundation. Remote `master` remains at `69feedf`. |
| Active product decision | The Windows-first WPF workstation is the accepted operator surface and Python remains the canonical trading and evidence engine. Schwab Trader API is the eventual read-only and separately supervised-live target. Schwab Support confirmed there is no automated Trader API paperMoney path or retail sandbox; thinkorswim paperMoney is manual Shadow reconciliation only. |
| Integrated implementation | Phases 8, 9, and 10 plus R011/R012 are `COMPLETE` on local and remote `master`. ARGUS-SHADOW-001 and its wiring foundation are `COMPLETE` on local `master`. ARGUS-SHADOW-002 is `IMPLEMENTED_PENDING_MERGE` on its bounded feature branch. The R013-R025 WPF stack remains consolidated on unmerged R026. Phase 11's A017 paper API path remains `BLOCKED_VENDOR_CAPABILITY`. |
| Git sequencing | R012 local tip and `origin/master` are `69feedf`; there is no separate remote R012 branch. Shadow-001 local/remote tips and local `master` are `bb962be`, proving Shadow-001 contains the current canonical R012 baseline. Shadow-002 implementation is `7fee390`, followed only by its Roadmap reconciliation. R026 is clean at `838ed22`, has no remote branch, and diverges from local `master` by 15 R026 commits versus 3 Shadow product commits. Shadow-002 needs no integration branch to fast-forward into local `master`; any future R026 integration requires a dedicated branch and explicit Steven sequencing approval. Do not rebase or rewrite either validated line for cosmetic linearity. |
| Merge-base evidence | `master`/`origin/master`, Shadow-001/`origin/master`, R012/`master`, R026/`master`, and R026/Shadow-002 all resolve to `69feedf`. Shadow-002/`master` resolves to `bb962be`. |
| R004 status | `COMPLETE`: workstation-shell feasibility is integrated into `origin/master`. |
| R005 status | `COMPLETE`: close-to-tray, lifecycle controls, single-instance activation, and physical Windows tray QA are integrated into `origin/master`. |
| Immediate next action | Steven reviews the Shadow-002 UI proof and branch evidence, then explicitly approves or rejects its local fast-forward. After integration, run the sample-start gate as a separate proof checkpoint; do not start the official sample merely because Shadow-002 merged. R026 remains a separate numbered workstation review and dedicated integration decision. Because Shadow-002 and R026 are both awaiting integration decisions, do not open another implementation branch yet. |
| Remote backup action | Remote `master` remains at `69feedf`; local `master` is three commits ahead at `bb962be`. The Shadow-001 feature branch is remotely backed up. Do not push `master` without Steven's separate explicit approval. |
| Broker and execution state | FakeBroker remains the only automated execution boundary. Schwab developer access is requested/pending. No Client ID, Client Secret, OAuth token, account hash, authenticated request, production endpoint client, paper/live broker path, or transmitting method exists. Paper and Live remain locked. |

### Status Legend

- `NOT_STARTED`: no implementation has begun.
- `ACTIVE`: work is underway on the named branch.
- `IMPLEMENTED_PENDING_MERGE`: work is committed and verified on a branch, but Steven has not approved its local merge.
- `COMPLETE`: work is merged into local `master` and verified.
- `BLOCKED`: a stated gate or CEO decision prevents work from starting.
- `BLOCKED_VENDOR_CAPABILITY`: the required broker capability does not exist; implementation cannot proceed by configuration alone.
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
- R005 originally supplied close-to-tray behavior, explicit exit, session-ending behavior, single-instance signaling, restricted tray commands, and an in-process background-collection lifecycle. Physical Windows QA passed.
- Under the original R005 boundary, collection continued only while the hidden WPF process remained alive.
- Phase 8 superseded that hosting limitation. The independent Python Engine Host is now canonical, and a WPF close or crash does not inherently stop it.
- Explicit Exit remains the deliberate joint-shutdown path for the workstation and its managed Python host.

### Phase 8 - Headless Python Engine Through Versioned Contracts

Status: `COMPLETE` on local and remote `master` through `a886c90`

- The approved Goal Charter creates versioned, provider-neutral host identity, health, collection, capability, command, and structured-error contracts.
- `momentum_hunter/engine_host.py` owns the independent loopback-only Python Engine Host. WPF discovers an existing host or launches one, reconnects by host identity, and deliberately shuts it down only on explicit Exit.
- The host has an atomic single-host lease, per-command idempotency, non-overlapping cycle guard, and a guard against the existing active-monitor runner starting a second collection loop.
- The host core owns snapshot, pause, resume, one collection cycle, and graceful shutdown. Phase 9 adds one versioned persisted-evidence snapshot capability; TradePlan, Risk Governor, chart data, simulation, broker, Paper, and Live remain outside the boundary.
- Focused Python process proof and .NET integration proof passed. The implementation fast-forwarded into local `master` and was later backed up through the approved R011 master push. See `reports/releases/ARGUS-R008-python-engine-contract-host.md`.

### Phase 9 - Read-Only Discovery, Research, Health, And Replay Integration

Status: `COMPLETE` on local and remote `master` through `a886c90`

- Connect WPF panes to the Phase 8 read-only boundary for candidates, evidence, research context, health, and replay.
- Preserve source lineage, stale-data language, and read-only replay identity.
- Use the independent engine lifecycle rather than a workstation-owned collection loop.
- The first slice exposes persisted report/status snapshots only and explicitly disables mock TradePlan, chart, risk, and simulation fallback until Phase 10.
- Focused Python tests, focused C# presentation/integration tests, a C#-to-Python host proof, broader nearby Python regression, the full .NET suite, and full Python discovery passed before the Steven-approved local fast-forward.

### Phase 10 - Trade Planning, Risk, And Simulation Integration

Status: `COMPLETE` on local and remote `master` through `a17eff8`

- The versioned Python host exposes a persisted-plan simulation workspace snapshot and a symbol-scoped FakeBroker-only simulation command.
- WPF consumes the canonical persisted TradePlan, Risk Governor, Execution Ledger, and Execution Auditor evidence rather than a mock fallback. R011 adds chart evidence separately and does not alter these planning or simulation contracts.
- A Risk Governor block prevents the simulation call and states that no evidence changed. A permitted simulation records risk, preview, FakeBroker outcome, and audit evidence in the in-memory host ledger.
- Follow-up commits `14fe317` and `893a6da` remove the Top-5-only plan mapping mismatch and the empty Risk Governor badge: all valid persisted candidate plans are exposed, and a missing plan explicitly shows `Plan unavailable` with simulation unavailable rather than a blank colored state.
- Steven accepted the manual visual proof and approved the local merge with real chart candles still explicitly deferred. Release compilation passed; focused Python simulation/autonomy tests passed 29 tests, and the full .NET workstation solution passed 71 tests immediately before merge. Full Python discovery was previously bounded at 120 seconds and did not complete; retain that test-harness timeout as a follow-up risk.

### Phase 11 - Shadow Evidence, Schwab Capability, And Pre-Execution Hardening

Status: `ACTIVE`; ARGUS-SHADOW-001 is `COMPLETE` on local `master`; ARGUS-SHADOW-002 is `IMPLEMENTED_PENDING_MERGE`; Schwab A017 is `BLOCKED_VENDOR_CAPABILITY`

#### 11A - Shadow Trading Evidence Program

- ARGUS-SHADOW-001 is integrated into local `master` at `bb962be`. It connects frozen current evidence to canonical TradePlan and Risk Governor decisions, conservative quote-driven FakeBroker orders/positions/exits, durable ledger/audit/outcomes, executable P&L/R/MFE/MAE, sample-gated metrics, and a nontransmitting manual paperMoney ticket.
- ARGUS-SHADOW-002 is implemented and verified on `codex/ARGUS-SHADOW-002-wpf-shadow-review`. It adds a read-only WPF review surface over canonical Shadow/FakeBroker evidence; it creates no execution authority and cannot edit completed trades, plans, or risk decisions. It remains branch-only pending Steven's review and local-merge approval.
- Python owns the prospective sample lifecycle and durable evidence. WPF is a bounded review surface only. FakeBroker remains the only automated execution boundary, and every Shadow decision must be prospective.
- Shadow-002 acceptance must visibly prove: `X / 30` eligible completed trades; active, unfilled, rejected, excluded, and invalid states; evidence and plan locks; decision and evidence timestamps; ideal versus estimated executable results; spread/slippage/fill explanation; P&L, R, MFE, MAE, duration, and exit reason; linked Chart, frozen Trade Plan, Why, and History/Activity drill-down; and minimum-sample gating.
- The official sample may start only after Shadow-001 is in the active baseline, Shadow-002 is accepted and integrated, evidence snapshots/TradePlans/Risk decisions are immutable, stable IDs connect candidate/evidence/plan/risk/command/ledger/outcome, duplicate commands and restart duplicates fail closed, P&L/MFE/MAE are reproducible, fill/spread/slippage assumptions are documented and locked, market-session/time-zone behavior is verified, and data-quality eligibility is deterministic.
- Every counted Shadow Trade must record a `SampleVersion`, strategy/configuration fingerprint, fill-model version, and evidence-schema version. These are pre-sample requirements; existing schema or plan fingerprints do not by themselves satisfy the full gate.
- Once a sample version starts, it permits no historical backfill, deletion of losers, selective exclusions, scoring/readiness/risk changes, entry/stop/target changes, spread/slippage/fill-model changes, or silent recomputation.
- If a material defect invalidates evidence, preserve the affected sample, close its version, document and fix the defect, and begin a new version. Never rewrite the affected sample into a cleaner result.
- FakeBroker evidence must model and record bid/ask spread, slippage, unfilled and delayed limit fills, supported partial fills, gaps through stops, halted/unavailable states, stale/missing quote rejection, session eligibility, buying power, position concurrency, daily-loss limits, restart recovery, and ambiguous states. Track both ideal setup and estimated executable results; estimated executable result is the primary evidence metric.
- Report evidence checkpoints at 5, 10, 20, and 30 completed eligible trades. Interim reports evaluate mechanics and evidence quality and must not tune the strategy to the developing sample.
- Thirty completed eligible trades is an initial engineering gate, not proof of a durable edge, a profitability claim, or permission to transmit any broker order.

#### 11B - Schwab Read-Only And Canary Preparation

- A016 produced the broker matrix, and Steven selected Schwab/thinkorswim continuity for the eventual read-only and supervised-live direction. An interim Alpaca implementation is not approved.
- Schwab Trader API Support confirmed there is no automated Trader API paperMoney path and no retail sandbox. A017 is therefore `BLOCKED_VENDOR_CAPABILITY`, not awaiting an answer.
- FakeBroker remains the only automated boundary. thinkorswim paperMoney is limited to manual Shadow ticket entry and reconciliation; do not automate thinkorswim or represent the $100 live canary account as paper.
- Schwab Trader API is the eventual read-only and separately supervised-live target. Developer access is requested/pending.
- No Client ID, Client Secret, OAuth token, account hash, authenticated request, production network client, or transmitting method exists. The canary account is not connected.
- Credential-free preparation may use official documentation, secure-local-setup design, synthetic Schwab fixtures, a contract emulator, manual paperMoney Shadow tickets, a physically read-only adapter design, and exact account-isolation policy.
- Existing Schwab preparation code remains network-free and nontransmitting. No real account connection may occur until a separate Steven checkpoint, and no order transmission is authorized.
- No task may ask for a Schwab username, password, or MFA; store a Client ID/Secret in Git or chat; perform OAuth; access an account; add submit/replace/cancel; automate thinkorswim; or transmit Paper or Live orders.
- Schwab developer approval permits a separate review checkpoint only. It does not automatically authorize OAuth, account connection, read-only requests, preview, or trading.

#### Standing Authorization And Branch Discipline

- After the current Shadow directive and Roadmap reconciliation, bounded Shadow pipeline implementation/repair, Shadow review improvements, gated evidence collection, 5/10/20/30 checkpoint reports, manual paperMoney reconciliation, credential-free Schwab contracts/fixtures, tests, reports, Roadmap updates, and sample-safe WPF migration are standing-authorized.
- Master merge/push, consequential Git integration, real OAuth/account access, Client credentials/tokens, authenticated Schwab requests, transmitting broker methods, protected-domain semantic changes, database migrations, and paid dependencies/data still require separate Steven approval.
- Keep one active implementation branch and at most one stacked successor. Stop when two completed branches await integration. Shadow-002 and R026 currently occupy that queue, so no additional implementation branch should begin until Steven resolves at least one.
- R012 remains the separately integrated chart-readability slice. R026 remains a separate numbered workstation review and must not be absorbed into Shadow-002. If Steven accepts R026, reconcile its 15-commit parallel line with the three-commit Shadow line on a dedicated integration branch; do not rebase or rewrite either history merely for linearity.

### Phase 12 - Incremental Capability Migration And Qt Retirement

Status: `ACTIVE`; R011 and R012 are `COMPLETE` on local and remote `master`; R013-R025 are consolidated as `IMPLEMENTED_PENDING_MERGE` on R026

- R011 adds one versioned `get_chart_snapshot` host command backed only by stored `opportunity-minute-bars.json` and `daily-ohlc-bars.json` evidence.
- WPF renders `1m`, deterministically aggregated `5m`/`15m`, and `Daily` candles with bodies, wicks, and volume. Source lineage and `AVAILABLE`, `STALE`, `INSUFFICIENT_DATA`, or `UNAVAILABLE` state remain visible.
- Missing intraday evidence never falls back to daily or mock candles. No provider call, background fetch, or source-data write was added.
- Candidate, interval, linked-pane, and pinned-pane context are covered by tests. The full CLI-only WPF proof shows CRWV with 143 stored stale 5-minute candles, source/as-of text, simulation-only language, and paper/live locks.
- Steven approved R011; Git Steward fast-forwarded it into local `master` without a merge commit and backed it up to `origin/master` under separate explicit push approval.
- R012 adds deterministic nice price ticks, chronological UTC time ticks, and a latest stored-bar OHLCV strip without changing the chart contract or Python engine.
- R012 focused tests passed 14 tests, the complete .NET suite passed 88 tests, Release compilation passed with zero warnings, and the offscreen WPF proof shows readable axes/details while preserving source lineage, simulation-only language, and paper/live locks.
- R012 was accepted, fast-forwarded, and pushed with local and remote `master` synchronized at `69feedf`.
- R013 through R025 are preserved on `codex/ARGUS-R026-wpf-phase12-clean-room-integration`; that combined branch remains a separate manual-review and merge decision.
- Migrate individual proven workflows to the WPF shell only after their Python contracts and operator proof are complete.
- Retire corresponding Qt screens incrementally, with acceptance evidence and rollback paths. Do not perform a broad rewrite.

### Phase 13 - Broker Execution Validation Gate

Status: `BLOCKED_VENDOR_CAPABILITY`

- The future evidence ladder is: (1) FakeBroker prospective Shadow Trading; (2) manual thinkorswim paperMoney ticket/reconciliation; (3) Schwab contract emulator; (4) Schwab authenticated read-only integration; (5) exact single-canary-account isolation proof; (6) broker preview only if official documentation proves a nontransmitting endpoint; (7) a separately approved supervised live canary; (8) reconciliation, audit review, and token-revocation drill; and (9) repeated supervised canary cycles.
- Schwab Trader API cannot access paperMoney and has no retail sandbox. Manual thinkorswim paperMoney reconciliation is evidence collection, not an automated API execution path.
- No automatic transition into authenticated access, broker preview, or supervised live testing is authorized. Each applicable ladder step requires its own evidence and Steven checkpoint.

### Phase 14 - Unattended Live Execution

Status: `BLOCKED`

- Requires separate explicit Steven approval after repeated supervised-canary evidence, credential and account-isolation controls, reconciliation and independent audit review, token-revocation proof, and a dedicated unattended-live Goal Charter.
- No standing directive may auto-advance into Phase 14.

## Roadmap Update Protocol

At every substantive task closeout, the responsible agent must:

1. Reconcile the `Now` section against `git status --short --branch`, the active branch HEAD, and local `master` versus `origin/master`.
2. Move the affected roadmap phase to the correct status without calling branch-only work `COMPLETE`.
3. Record the concrete next action and any new block or decision gate.
4. Update `BRANCH_LEDGER.md` only when branch/merge/push state changes, and `TASK_LOG.md` or `CHANGELOG_ARGUS.md` as historical evidence requires.
5. Cite the resulting Roadmap transition in the final CEO report.

## Protected Areas

Do not change core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior without explicit approval.
