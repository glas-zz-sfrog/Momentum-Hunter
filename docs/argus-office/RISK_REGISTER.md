# Risk Register

| ID | Risk | Area | Severity | Mitigation | Status |
| --- | --- | --- | --- | --- | --- |
| R-001 | Multiagent work creates fragmented recommendations. | Operations | Medium | Codex Orchestrator produces one consolidated CEO report. | Open |
| R-002 | Analysis agents accidentally modify code. | Governance | High | Recommendation-only agents are read-only by default; Builder is the only normal code-writing agent. | Open |
| R-003 | Protected trading or replay semantics change without approval. | Product trust | High | Protected areas require explicit approval and stop conditions. | Open |
| R-004 | Steven becomes the manual task router. | Operations | Medium | ChatGPT shapes tasks; Codex Orchestrator delegates and consolidates. | Open |
| R-005 | Push or merge happens before review. | Release | High | No push or merge without explicit approval; Steven is final merge approver. | Open |
| R-006 | Autonomous UI language implies a candidate is an approved live trade. | Product trust | High | Use candidate, setup, simulation, paper, preview, and live-locked labels until Risk Governor and approvals prove stronger states. | Open |
| R-007 | Broker integration begins before adapter, risk, and audit boundaries exist. | Broker safety | High | Require Broker Adapter, Risk Governor, TradePlan, and Execution Ledger specs before broker implementation. | Open |
| R-008 | Paper and live broker states are blurred. | Broker safety | High | Separate fake, paper, read-only live, preview, and confirmed live adapter modes with visible console labels. | Open |
| R-009 | Manual TradePlan edits bypass risk re-check. | Risk controls | High | Mark edits as manual overrides and require Risk Governor re-check before advancing state. | Open |
| R-010 | Autonomous roadmap expands into protected runtime behavior too early. | Scope control | Medium | Keep ARGUS-A000 docs/config only and require future Goal Charters for implementation. | Open |
| R-011 | A broad frontend rewrite regresses proven trading behavior before the Python boundary is ready. | Architecture | High | Keep Python canonical; use the WPF shell only as a bounded feasibility spike, then define versioned contracts before incremental migration. | Open |
| R-012 | Qt and `app.py` complexity continue growing while the replacement boundary is unclear. | Maintainability | High | Prove the WPF shell and Python contracts first; migrate or retire Qt screens one workflow at a time with test and rollback evidence. | Open |
| R-013 | Frontend modernization improves appearance but weakens safety language. | Product trust | High | Preserve locked/live/paper/simulation labels and screenshot-proof warning states in every UI modernization task. | Open |
| R-014 | Stale branch reports cause Steven or ChatGPT to continue from a superseded branch. | Git / operations | High | Maintain `BRANCH_LEDGER.md`, classify superseded branches, and start new work only from local `master` unless Git Steward says otherwise. | Open |
| R-015 | Duplicate TradePlan/RiskGovernor model paths create conflicting source authority. | Architecture | High | Treat `momentum_hunter/trade_planning.py` and `momentum_hunter/autonomy/*` as canonical; do not merge the older `momentum_hunter/execution/*` branch as-is. | Open |
| R-016 | Review bundles omit imported dependencies or include stale manifest values. | Review quality | Medium | Future bundles must include key imported dependencies such as `trade_planning.py`, `models.py`, `time_utils.py`, and `monitor_targets.py`, while staying curated and excluding secrets/data. | Open |
| R-017 | Simulation engine adapter injection becomes a paper/live transmit path if reused without guards. | Broker safety | High | Before A017/A018, require FakeBroker-only metadata checks and tests proving non-Fake or transmit-capable adapters are rejected before adapter calls. | Open |
| R-018 | Execution Auditor is treated as a hard paper gate before it validates chronology, preview-before-submit, and event consistency. | Broker safety | High | Harden auditor rules and tests before any paper broker skeleton or paper pilot. | Open |
| R-019 | Competing status documents or stale roadmap entries send work down an obsolete architectural path. | Operations | High | Treat `ROADMAP.md` as the sole current-status authority; reconcile it from Git at every substantive task closeout. | Open |
| R-020 | Sparse or stale stored chart bars look like current market data in the workstation. | Product trust | High | Label chart state, source, timeframe, and as-of timestamp; preserve stale candles only with explicit `STALE`; use `UNAVAILABLE` rather than mock, daily, interpolated, or provider fallback. | Mitigated in R011; monitor source coverage |

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
