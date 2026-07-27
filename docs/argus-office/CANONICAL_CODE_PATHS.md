# Canonical Code Paths

Date reconciled: 2026-07-27

This document names the merged implementation paths on `master` through
SHADOW-010. The Roadmap, not this file, decides priority and next work.

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
| Daily Workflow WPF evidence boundary | `momentum_hunter/workstation_daily_workflow.py`, `momentum_hunter/engine_host.py`, `src/MomentumHunter.EngineBridge/PythonDailyWorkflowWorkspaceClient.cs`, `src/MomentumHunter.Presentation/ShellViewModel.cs`, `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml` | Canonical argument-free, read-only projection of persisted workflow evidence, integrated through R027. |
| Candidate Story model and Qt evidence | `momentum_hunter/replay.py`, `momentum_hunter/candidate_story_view_model.py`, and existing Qt routing in `momentum_hunter/app.py` | Canonical merged trusted timeline and Candidate Story classification. R024 makes missing/aware capture-time sorting defensive but does not change status semantics, replay identity, or capture selection. |
| Candidate Story WPF evidence boundary | `momentum_hunter/workstation_candidate_story.py`, `momentum_hunter/engine_host.py`, `src/MomentumHunter.EngineBridge/PythonCandidateStoryWorkspaceClient.cs`, `src/MomentumHunter.Presentation/CandidateStoryView.cs`, `src/MomentumHunter.Presentation/ShellViewModel.cs`, `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml` | Canonical argument-scoped, read-only projection of trusted Candidate Story evidence, integrated through R027. |
| Research maturity source reports | `MomentumHunterData/data/reports/evidence-analytics-maturity-latest.json`, `MomentumHunterData/data/reports/evidence-census-latest.json` | Persisted research evidence only. R025 reads these reports without regenerating them or making SQLite authoritative. |
| Research Maturity WPF evidence boundary | `momentum_hunter/workstation_research_maturity.py`, `momentum_hunter/engine_host.py`, `src/MomentumHunter.EngineBridge/PythonResearchMaturityWorkspaceClient.cs`, `src/MomentumHunter.Presentation/ShellViewModel.cs`, `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml` | Canonical argument-free, read-only maturity/census projection with separate denominators and strict strategy-lock validation, integrated through R027. |
| Integrated WPF capability stack | `src/MomentumHunter.Desktop.Wpf/`, `src/MomentumHunter.Presentation/`, `src/MomentumHunter.EngineBridge/`, `src/MomentumHunter.Application/`, `src/MomentumHunter.Contracts/`, and `momentum_hunter/workstation_*.py` | R013-R029 are integrated and canonical on `master`. R026 and individual R013-R025 branches are audit history only. |
| WPF operator shell and lifecycle | `src/MomentumHunter.Desktop.Wpf/` | Canonical WPF operator surface on `master`: workstation UI, docking, chart surface, layout persistence, notifications, tray integration, and explicit application lifecycle. It does not replace the Python engine. |
| WPF presentation state | `src/MomentumHunter.Presentation/` | Canonical WPF shell view models, pane registry/state, linked contexts, workspace selection, and layout autosave coordination. |
| Python Engine Host | `momentum_hunter/engine_host.py` | Canonical loopback-only independent process exposing versioned lifecycle, persisted workspace, chart, FakeBroker-only simulation, prospective Shadow, technical-research, saved-watchlist, Daily Workflow, Candidate Story, and Research Maturity capabilities. It has no paper/live broker or real-order command. |
| Python read-only workstation model | `momentum_hunter/workstation_read_models.py` | Maps persisted reports and statuses without writing source artifacts, recalculating scores/readiness, creating Replay identities, fetching providers, or exposing planning/simulation. |
| WPF lifecycle application services | `src/MomentumHunter.Application/` | Canonical WPF lifecycle interfaces and background-collection coordination. `PythonEngineHostContracts.cs` and `ReadOnlyWorkspaceContracts.cs` define the narrow host and persisted-evidence interfaces. |
| WPF contracts | `src/MomentumHunter.Contracts/` | Canonical .NET workstation contracts and shared value types. `PythonEngineHostContracts.cs` adds provider-neutral host and command-result models; `ReadOnlyWorkspaceSnapshot` carries typed persisted-evidence displays. |
| WPF infrastructure | `src/MomentumHunter.Infrastructure/` | Canonical WPF persistence, layout integrity, monitor recovery, and tray-setting storage. |
| WPF engine bridge | `src/MomentumHunter.EngineBridge/` | `PythonEngineHostConnection`, `RemoteBackgroundCollectionService`, and typed clients bridge persisted evidence, charts, FakeBroker-only simulation, read-only Shadow review, technical research, saved watchlist, Daily Workflow, Candidate Story, and Research Maturity. No paper/live broker, credential, or real-order integration exists here. |
| WPF verification | `tests-dotnet/` | Canonical .NET presentation, lifecycle, shell-workflow, and layout test coverage for R004/R005. |
| Python engine lifecycle contracts | `momentum_hunter/engine_host.py`, `src/MomentumHunter.Contracts/PythonEngineHostContracts.cs`, `src/MomentumHunter.Application/PythonEngineHostContracts.cs` | Merged implementation covers host identity, health, collection state, pause, resume, one cycle, shutdown, persisted workspace, chart snapshots, FakeBroker-only simulation, prospective Shadow state, and the five read-only R027 evidence commands. |
| Shadow Trading lifecycle | `momentum_hunter/shadow_trading.py`, `momentum_hunter/workstation_shadow.py`, `momentum_hunter/engine_host.py` | Canonical merged Shadow lifecycle, persistent evidence, FakeBroker quote processing, audit, metrics, WPF read model, and host boundary. |
| Official Shadow activation | `momentum_hunter/shadow_trading.py`, `momentum_hunter/workstation_shadow.py`, and WPF Shadow presentation paths | Canonical write-once activation and accepted active-empty visual truth. Production-local activation is ignored generated state, not Git content. |
| Prospective capture-to-report handoff | `tools/capture_job.py`, `momentum_hunter/providers.py`, and TradePlan export paths | Canonical write-once scheduled capture-to-report handoff with raw-capture nonmutation, bounded Finviz scan behavior, and a distinct immutable `shadow` session. |
| Official Shadow opening cadence | `momentum_hunter/models.py`, `momentum_hunter/scheduling.py`, `tools/capture_job.py`, `tools/run_capture_job.ps1`, `tools/install_capture_tasks.ps1`, `momentum_hunter/engine_host_client.py`, and `momentum_hunter/engine_host.py` | One XNYS-market-day capture at 9:35 AM ET feeds the existing guarded Engine Host selector cycle. Deterministic report-hash command IDs and write-once receipts provide at-least-once retry without rescanning or duplicate official trades. |
| Automatic Shadow proof/arm ceremony | `momentum_hunter/shadow_arm_ceremony.py`, `momentum_hunter/shadow_proof_bundle.py`, `momentum_hunter/shadow_trading.py`, `momentum_hunter/schwab_market_data.py`, and the opening-cadence paths | Canonical nonvisual SHADOW-010 path. It preflights synchronized Git and static evidence, validates the newest canonical report/capture, obtains candidate/SPY/IWM quotes through the read-only Schwab source, finalizes and re-verifies all 12 proof artifacts, arms only through the existing exact guarded method, and then permits the existing FakeBroker-only selector cycle. |
| Automatic official-sample selector | `momentum_hunter/shadow_selection.py`, `momentum_hunter/shadow_market_validity.py`, `momentum_hunter/shadow_trading.py`, `momentum_hunter/workstation_shadow.py`, `momentum_hunter/engine_host.py`, `momentum_hunter/schwab_market_data.py` | Canonical deterministic selector, market-validity, proof-backed arm, cycle, counterfactual, and read-only quote-proof boundaries. The selector remains `NOT_ARMED` until the regular-market proof and complete immutable proof bundle pass. |
| Selector proof-bundle assembly | `momentum_hunter/shadow_proof_bundle.py`, `momentum_hunter/shadow_market_validity.py`, `momentum_hunter/schwab_market_data.py` | Canonical nontransmitting preparation path. `prepare-static` atomically assembles 11 verified static artifacts only from clean synchronized `master`; `finalize` derives the candidate from the newest fresh canonical report, validates and copies its immutable source capture, accepts only the matching schema-v2 live Schwab candidate/SPY/IWM quote proof, adds the twelfth artifact, and invokes the existing nonmutating verifier. It does not arm, write policy/state/trades, or expose an order method. |
| Official sample operational status | `momentum_hunter/shadow_trading.py` `sample-status` command | Canonical read-only activation, selector-arm, collection-enabled, next-gate, sample-count, and transmission-lock status. Activation readiness is explicitly scoped and cannot be mistaken for selector arming. |
| Schwab OAuth and read-only account boundary | `momentum_hunter/schwab_setup.py`, `schwab_onboarding.py`, `schwab_oauth_listener.py`, `schwab_loopback_certificate.py`, `schwab_readonly.py`, `schwab_account_discovery.py`, `schwab_account_validation.py`, `schwab_cash_account_binding.py`, `schwab_bound_account_refresh.py` | Canonical credential-protected, read-only Schwab path bound immutably to the sole `2573` `CASH` account. No transmitting method exists. |
| Future paper broker work | No code path yet | Schwab Trader API paperMoney is unavailable. Manual thinkorswim paperMoney reconciliation is the only current paper path. No paper broker adapter exists on `master` or R027. |

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

- New work normally branches from synchronized local `master`. SHADOW-004/005/006 are merged source history and must not be continued as active implementation branches.
- R013-R029 and Shadow-001/002/003 are merged and backed up. Preserve R026 and individual R013-R025 branches as source/audit history; do not merge them again.
- Do not inherit R012A/R012B icon artwork into R027. R012C must remain a separately approved visual-identity branch.
- Do not build on the original `codex/ARGUS-A006-A015-argus-machine-simulation` branch.
- Do not build on `codex/ARGUS-A004-A005-tradeplan-risk-governor`.
- Do not add transmitting broker code until a new Goal Charter explicitly approves the applicable plumbing or strategy canary and every Roadmap gate passes.
- The previously surfaced Schwab Client Secret blocks transmitting code until vendor remediation is documented.
- Keep `TradePlan` source authority in `momentum_hunter/trade_planning.py` unless Steven approves a model migration.
