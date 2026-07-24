# Momentum Hunter Roadmap

## Authority

This is the single authoritative view of current product position, active work, and next work. Update its `Now` section from Git evidence before a task is reported complete, merged, or blocked.

Supporting records have narrower roles:

- `BRANCH_LEDGER.md` is the detailed Git and branch-evidence record.
- `VERIFICATION_QUEUE.md` is the exact deferred Steven-check list; it does not replace Roadmap state or authorize merges.
- `TASK_LOG.md` and `CHANGELOG_ARGUS.md` are append-only history.
- Historical architecture notes and release reports remain evidence of their original decisions; they do not override this Roadmap.

## Now

Last reconciled: 2026-07-23 on `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit` after the prospective Shadow Trading lifecycle, nontransmitting paperMoney ticket, credential-free Schwab read-only contracts, account-isolation policy, DPAPI-backed local secret-store abstraction, and synthetic Schwab emulator passed their Hard Chew verification. The required wiring audit `54c58a8` and implementation `5d11f02` are remotely backed up on the feature branch. The work remains branch-only and must be `IMPLEMENTED_PENDING_MERGE`, never `COMPLETE`, until Steven approves a local fast-forward. Sixty focused lifecycle, host, simulation, and Schwab safety tests plus 68 adjacent TradePlan/Risk/observation tests pass; Python compileall, .NET restore, all 88 .NET tests, and a zero-warning Release build pass. Full Python discovery exceeded its bounded 10-minute window and is recorded as a timeout, not a pass. Local and remote `master` remain synchronized at `69feedf`.

| Item | Current truth |
| --- | --- |
| Canonical product baseline | Local and remote `master` contain the Phase 10 TradePlan, Risk Governor, FakeBroker-only simulation, ledger, and auditor integration plus R011 chart candles and R012 deterministic chart axes/latest-bar details through `69feedf`. |
| Active product decision | The Windows-first WPF workstation is the accepted operator surface and Python remains the canonical trading and evidence engine. Schwab/thinkorswim may remain the eventual read-only/live direction, but Schwab Support confirmed Trader API cannot access paperMoney and has no current sandbox. Automated paper-broker direction is unresolved; no interim alternate adapter is approved. |
| Integrated implementation | Phases 8, 9, and 10 plus R011/R012 are `COMPLETE` on local and remote `master`. The R013-R025 WPF stack remains consolidated on unmerged R026. Phase 11's A017 paper API path is `BLOCKED_VENDOR_CAPABILITY`; ARGUS-SHADOW-001 is `IMPLEMENTED_PENDING_MERGE` as the credential-free prospective validation bridge. |
| R004 status | `COMPLETE`: workstation-shell feasibility is integrated into `origin/master`. |
| R005 status | `COMPLETE`: close-to-tray, lifecycle controls, single-instance activation, and physical Windows tray QA are integrated into `origin/master`. |
| Immediate next action | Review ARGUS-SHADOW-001 for local fast-forward eligibility. After merge approval, accumulate at least 30 completed prospective Shadow Trades before drawing strategy conclusions and reconcile selected nontransmitting tickets manually in thinkorswim paperMoney. R026 remains a separate manual-review decision. |
| Remote backup action | Local `master` is backed up to `origin/master` at `69feedf`. ARGUS-SHADOW-001 is backed up only on its feature branch; R026, A016T, and other branch-only work remain unmerged. Never push `master` from this task. |
| Broker and execution state | FakeBroker remains the only automated execution boundary. No Schwab credential, token, account hash, endpoint URL, HTTP client, paper/live broker path, or transmitting method exists. Paper and Live remain locked. |

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
- R005 supplied close-to-tray behavior, explicit exit, session-ending behavior, single-instance signaling, restricted tray commands, and the in-process background-collection lifecycle. Physical Windows QA passed.
- Collection continues while the WPF application process is alive and the visible workstation is hidden.
- The Python engine is not independently hosted yet. A WPF process crash or explicit process exit still stops the current R005-hosted lifecycle.

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

### Phase 11 - Broker Research And Hardening Before Paper Execution

Status: `ACTIVE`; ARGUS-SHADOW-001 is `IMPLEMENTED_PENDING_MERGE`; Schwab A017 is `BLOCKED_VENDOR_CAPABILITY`

- A016 produced a current broker matrix and Steven selected Schwab/thinkorswim continuity for both paper and eventual live trading; an interim Alpaca implementation is not approved.
- Schwab Trader API Support subsequently confirmed the API is compatible only with live brokerage accounts, cannot access paperMoney balances/positions/orders, and has no current sandbox. The A016S waiting state is superseded by the branch-only A016T response record.
- A017 is `BLOCKED_VENDOR_CAPABILITY`: do not treat the $100 live canary account as paper, do not automate thinkorswim, and do not add a Schwab paper adapter.
- ARGUS-SHADOW-001 connects frozen current evidence to canonical TradePlan and Risk Governor decisions, conservative quote-driven FakeBroker orders/positions/exits, durable ledger/audit/outcomes, executable P&L/R/MFE/MAE, sample-gated metrics, and a nontransmitting manual paperMoney ticket.
- The Shadow path is prospective and credential-free. It uses supplied persisted observations only, survives restart through atomic versioned JSON state, and fails closed on stale/missing/out-of-order quotes, invalid IDs, risk blocks, buying-power/concurrency/daily-loss limits, and ambiguous exits.
- The Schwab preparation modules are physically read-only and network-free: no production URL, HTTP client, credential, account value, OAuth token, or write method exists. Synthetic contracts prove account isolation, OAuth state/timeout behavior, DPAPI fake-token protection, redaction, and failure handling without contacting Schwab.
- Future Schwab progression is gated in this order:
  1. Credential-free specification and secure setup skeleton.
  2. Prospective Shadow Trading proof.
  3. Manual thinkorswim paperMoney reconciliation.
  4. Synthetic Schwab contract-emulator proof.
  5. Authenticated official-document review after developer approval.
  6. Separate approval for read-only OAuth setup.
  7. Exact one-account canary isolation proof.
  8. Read-only balances, positions, and orders.
  9. Stop before every transmitting endpoint or method.
- The minimum meaningful Shadow sample is 30 completed trades. Below that gate, metrics are descriptive evidence only and no best/worst strategy conclusion is allowed.

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

### Phase 13 - Paper Execution Gate

Status: `BLOCKED_VENDOR_CAPABILITY`

- Schwab Trader API cannot access paperMoney and has no current sandbox. Manual thinkorswim paperMoney reconciliation is evidence collection, not an API execution path.
- An automated paper gate now requires either a future Schwab sandbox or a separately approved alternate-paper-broker decision and Goal Charter. Neither is currently approved.
- Shadow Trading must first accumulate a meaningful prospective sample with reconciliation evidence; it does not authorize Paper or Live controls.

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
