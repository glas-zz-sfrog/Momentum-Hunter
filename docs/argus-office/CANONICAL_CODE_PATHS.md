# Canonical Code Paths

Date reconciled: 2026-07-16

This document names the current canonical implementation paths on synchronized `master` and `origin/master` at `e141054`. The Roadmap, not this file, decides priority and next work.

## Canonical Paths

| Area | Canonical path | Notes |
| --- | --- | --- |
| Existing Python Automation and Simulation UI | `momentum_hunter/ui/autonomy_gateway.py` plus routing calls in `momentum_hunter/app.py` | Canonical merged Python UI path for the existing Python application. Existing source names are historical implementation names, not future product terminology. |
| Trade Plan Ladder UI | `momentum_hunter/ui/trade_plan_ladder.py` | Renders ladder rows from `momentum_hunter/autonomy/view_models.py`. |
| Top 5 candidate view model | `momentum_hunter/autonomy/view_models.py` | Builds `Top5CandidatePlan` rows from `TradePlanningReport.rows` or current candidate state. These are candidates, not approved trades. |
| TradePlan model | `momentum_hunter/trade_planning.py` | `TradePlan`, `TradePlanRow`, and `TradePlanningReport` are the source primitives. Do not introduce a parallel TradePlan model path. |
| Risk Governor | `momentum_hunter/autonomy/risk_governor.py` | Simulation-only gates. Paper and live remain locked. |
| Execution Ledger | `momentum_hunter/autonomy/ledger.py` | Append-only in-memory/file-serializable event model for simulation audit evidence. |
| BrokerAdapter / FakeBroker | `momentum_hunter/autonomy/broker.py` | `FakeBrokerAdapter` is the only implemented broker adapter. It is simulation-only and has `order_transmit_allowed=False`. |
| Simulation Lab Engine | `momentum_hunter/autonomy/simulation.py` | Orchestrates candidate TradePlan -> Risk Governor result -> FakeBroker -> Execution Ledger. |
| Execution Auditor | `momentum_hunter/autonomy/auditor.py` | Audits simulation chains and provides the display-only future paper advancement gate. |
| Daily Workflow report model | `momentum_hunter/daily_workflow.py` | Builds `DailyWorkflowReport`. |
| Daily Workflow operator context | `momentum_hunter/operator_review.py`, `momentum_hunter/outcome_maturity.py`, `momentum_hunter/ui/data_view_state.py` | Supplies review context, outcome maturity, and view-state language used by the operator UI. |
| Daily Workflow UI | `momentum_hunter/app.py` | The guided Daily Workflow stepper is still implemented inside `app.py`; future extraction should be a separate scoped task. |
| WPF operator shell and lifecycle | `src/MomentumHunter.Desktop.Wpf/` | Canonical WPF operator surface on `master`: workstation UI, docking, chart surface, layout persistence, notifications, tray integration, and explicit application lifecycle. It does not replace the Python engine. |
| WPF presentation state | `src/MomentumHunter.Presentation/` | Canonical WPF shell view models, pane registry/state, linked contexts, workspace selection, and layout autosave coordination. |
| WPF lifecycle application services | `src/MomentumHunter.Application/` | Canonical WPF application-level lifecycle, background-collection coordination, and shell-facing engine contracts. This is not an independent Python engine host. |
| WPF contracts | `src/MomentumHunter.Contracts/` | Canonical .NET workstation contracts and shared value types. They do not yet define the Phase 8 Python boundary. |
| WPF infrastructure | `src/MomentumHunter.Infrastructure/` | Canonical WPF persistence, layout integrity, monitor recovery, and tray-setting storage. |
| WPF engine bridge | `src/MomentumHunter.EngineBridge/` | Canonical current shell bridge seam and deterministic/mock engine client. It is not a Python-process bridge or provider integration. |
| WPF verification | `tests-dotnet/` | Canonical .NET presentation, lifecycle, shell-workflow, and layout test coverage for R004/R005. |
| Future Python engine contracts | No canonical implementation yet | Phase 8 will define versioned, read-only, provider-neutral contracts and independently host the canonical Python engine. |
| Future paper broker work | No code path yet | Deferred until the WPF direction and Python engine boundary are proven. No paper broker adapter exists on `master`. |

## Direct Answers

1. Is `momentum_hunter/autonomy/*` the canonical autonomy implementation path?

Yes. `momentum_hunter/autonomy/*` is canonical for merged Python automation and simulation primitives: view models, risk gates, ledger, fake broker, simulation engine, and auditor.

2. Is any older `momentum_hunter/execution/*` path still active?

No. Local `master` does not contain an active `momentum_hunter/execution/*` implementation path. That path exists only on the older unmerged A004/A005 branch.

3. Is `codex/ARGUS-A004-A005-tradeplan-risk-governor` superseded?

Yes. It is superseded by the current `trade_planning.py` and `autonomy/*` implementation on local `master`.

4. Is anything from that branch worth salvaging?

Possibly as reference only. Its isolated TradePlan/RiskGovernor tests and naming may be useful for a future review, but the branch should not be merged directly because it would introduce a duplicate `momentum_hunter/execution/*` model path.

## Rules For Future Work

- New simulation/autonomy work should branch from local `master`.
- New WPF shell work should branch from local `master`; do not continue R004/R005 historical feature branches.
- Phase 8 must not claim that `MomentumHunter.EngineBridge` is an independent Python host before that host and its versioned contracts exist.
- Do not build on the original `codex/ARGUS-A006-A015-argus-machine-simulation` branch.
- Do not build on `codex/ARGUS-A004-A005-tradeplan-risk-governor`.
- Do not add paper/live broker code until a new Goal Charter explicitly approves that scope.
- Keep `TradePlan` source authority in `momentum_hunter/trade_planning.py` unless Steven approves a model migration.
