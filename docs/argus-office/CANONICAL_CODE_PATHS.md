# Canonical Code Paths

Date reconciled: 2026-07-23

This document names the current merged implementation paths on local and remote `master` at `69feedf`, plus the explicitly labeled R026 Phase 12 integration candidate under review. The Roadmap, not this file, decides priority and next work.

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
| Daily Workflow Qt UI | `momentum_hunter/app.py` | Canonical merged Qt dialog remains in `app.py`. R026 imports the behavior-equivalent pure guidance functions from `momentum_hunter/daily_workflow_guidance.py`; widget construction and quick-action wiring remain in `app.py`. |
| Daily Workflow WPF evidence boundary | R026 integration candidate, originating R023: `momentum_hunter/workstation_daily_workflow.py`, `momentum_hunter/engine_host.py`, `src/MomentumHunter.EngineBridge/PythonDailyWorkflowWorkspaceClient.cs`, `src/MomentumHunter.Presentation/ShellViewModel.cs`, `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml` | Argument-free, read-only projection of persisted workflow evidence. It becomes canonical only if Steven approves and merges R026. |
| Candidate Story model and Qt evidence | `momentum_hunter/replay.py`, `momentum_hunter/candidate_story_view_model.py`, and existing Qt routing in `momentum_hunter/app.py` | Canonical merged trusted timeline and Candidate Story classification. R024 makes missing/aware capture-time sorting defensive but does not change status semantics, replay identity, or capture selection. |
| Candidate Story WPF evidence boundary | R026 integration candidate, originating R024: `momentum_hunter/workstation_candidate_story.py`, `momentum_hunter/engine_host.py`, `src/MomentumHunter.EngineBridge/PythonCandidateStoryWorkspaceClient.cs`, `src/MomentumHunter.Presentation/CandidateStoryView.cs`, `src/MomentumHunter.Presentation/ShellViewModel.cs`, `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml` | Argument-scoped, read-only projection of canonical trusted Candidate Story evidence with separate capture-time facts and later annotations. It becomes canonical only if Steven approves and merges R026. |
| Research maturity source reports | `MomentumHunterData/data/reports/evidence-analytics-maturity-latest.json`, `MomentumHunterData/data/reports/evidence-census-latest.json` | Persisted research evidence only. R025 reads these reports without regenerating them or making SQLite authoritative. |
| Research Maturity WPF evidence boundary | R026 integration candidate, originating R025: `momentum_hunter/workstation_research_maturity.py`, `momentum_hunter/engine_host.py`, `src/MomentumHunter.EngineBridge/PythonResearchMaturityWorkspaceClient.cs`, `src/MomentumHunter.Presentation/ShellViewModel.cs`, `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml` | Argument-free, read-only projection of persisted maturity/census evidence with separate denominators, strict strategy-lock validation, and no collection or action path. It becomes canonical only if Steven approves and merges R026. |
| Phase 12 integrated WPF candidate | Branch-only R026: `src/MomentumHunter.Desktop.Wpf/`, `src/MomentumHunter.Presentation/`, `src/MomentumHunter.EngineBridge/`, `src/MomentumHunter.Application/`, `src/MomentumHunter.Contracts/`, and the `momentum_hunter/workstation_*.py` projections | One clean integration of R013-R025 through `a263311`, using layout schema 7 and no rejected icon artwork. This is the sole current Phase 12 merge candidate; individual R013-R025 branches are preserved for audit only. |
| WPF operator shell and lifecycle | `src/MomentumHunter.Desktop.Wpf/` | Canonical WPF operator surface on `master`: workstation UI, docking, chart surface, layout persistence, notifications, tray integration, and explicit application lifecycle. It does not replace the Python engine. |
| WPF presentation state | `src/MomentumHunter.Presentation/` | Canonical WPF shell view models, pane registry/state, linked contexts, workspace selection, and layout autosave coordination. |
| Python Engine Host | `momentum_hunter/engine_host.py` | Local loopback-only independent process. On `master` it exposes versioned lifecycle, persisted workspace, chart, and FakeBroker-only simulation capabilities. R026 adds branch-only technical-research, saved-watchlist, Daily Workflow, Candidate Story, and Research Maturity snapshots. Every new command is read-only. It has no paper/live broker or real-order command. |
| Python read-only workstation model | `momentum_hunter/workstation_read_models.py` | Maps persisted reports and statuses without writing source artifacts, recalculating scores/readiness, creating Replay identities, fetching providers, or exposing planning/simulation. |
| WPF lifecycle application services | `src/MomentumHunter.Application/` | Canonical WPF lifecycle interfaces and background-collection coordination. `PythonEngineHostContracts.cs` and `ReadOnlyWorkspaceContracts.cs` define the narrow host and persisted-evidence interfaces. |
| WPF contracts | `src/MomentumHunter.Contracts/` | Canonical .NET workstation contracts and shared value types. `PythonEngineHostContracts.cs` adds provider-neutral host and command-result models; `ReadOnlyWorkspaceSnapshot` carries typed persisted-evidence displays. |
| WPF infrastructure | `src/MomentumHunter.Infrastructure/` | Canonical WPF persistence, layout integrity, monitor recovery, and tray-setting storage. |
| WPF engine bridge | `src/MomentumHunter.EngineBridge/` | `PythonEngineHostConnection`, `RemoteBackgroundCollectionService`, and typed workspace clients bridge local persisted evidence, charts, and FakeBroker-only simulation. R026 integrates strict read-only clients for technical research, saved watchlist, Daily Workflow, Candidate Story, and Research Maturity. No provider, paper/live broker, credential, or real-order integration exists here. |
| WPF verification | `tests-dotnet/` | Canonical .NET presentation, lifecycle, shell-workflow, and layout test coverage for R004/R005. |
| Python engine lifecycle contracts | `momentum_hunter/engine_host.py`, `src/MomentumHunter.Contracts/PythonEngineHostContracts.cs`, `src/MomentumHunter.Application/PythonEngineHostContracts.cs` | Merged implementation covers host identity, health, collection state, pause, resume, one cycle, shutdown, persisted workspace, chart snapshots, and FakeBroker-only simulation. R026's five additional evidence commands remain branch-only and read-only. |
| Future paper broker work | No code path yet | Blocked until official Schwab paper-API evidence and a separate Steven-approved Goal Charter. No paper broker adapter exists on `master` or R026. |

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
- Phases 8-10 plus R011/R012 are merged and backed up on `master`; R026 is the sole integrated Phase 12 candidate, while Paper and Live remain absent and locked.
- Do not merge R013-R025 individually while R026 is under review; retain them only as source/audit branches.
- Do not inherit R012A/R012B icon artwork into R026. R012C must remain a separately approved visual-identity branch.
- Do not build on the original `codex/ARGUS-A006-A015-argus-machine-simulation` branch.
- Do not build on `codex/ARGUS-A004-A005-tradeplan-risk-governor`.
- Do not add paper/live broker code until a new Goal Charter explicitly approves that scope.
- Keep `TradePlan` source authority in `momentum_hunter/trade_planning.py` unless Steven approves a model migration.
