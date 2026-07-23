# Argus Changelog

## Unreleased
- Fast-forwarded Steven-approved R011 into local `master` at `268f3f8`, reconciled the authoritative roadmap and branch ledger, and backed the integrated baseline up to `origin/master` under explicit push approval.
- Added R011's versioned read-only local chart snapshot boundary and WPF candle/wick/volume rendering for stored `1m`, aggregated `5m`/`15m`, and `Daily` evidence.
- Added explicit chart `AVAILABLE`, `STALE`, `INSUFFICIENT_DATA`, and `UNAVAILABLE` states, source/as-of lineage, request identity validation, and no mock or cross-timeframe fallback.
- Added chart selection, interval, linked-pane, pinned-pane, malformed-data, source-integrity, and live Python-host integration coverage.
- Preserved CLI-rendered full-workstation and renderer-only proof showing nonblank CRWV 5-minute candles, simulation-only language, and paper/live locks without taking over the desktop.
- Recorded the branch-only A016/A016S Schwab decision and official support request; A017 remains blocked pending an official machine-verifiable paper boundary.
- Locally fast-forwarded Steven-approved Phase 10 into `master` through `7efd48d`; no merge commit and no master push occurred.
- Added persisted TradePlan and Risk Governor evidence to the WPF workstation, with symbol-scoped FakeBroker-only simulation, Execution Ledger events, and Execution Auditor results supplied through the versioned Python host.
- Exposed valid persisted plans for all candidate rows and made missing plans explicit as `Plan unavailable`, with simulation disabled and no empty status badge.
- Kept real chart candles deferred with no synthetic fallback; paper/live controls, credentials, provider access, and real broker/order paths remain absent and locked.
- Locally fast-forwarded the Steven-approved Phase 8 + Phase 9 stack into `master` through `a886c90`; no merge commit and no master push occurred. The independent host and persisted-evidence WPF boundary are now the local canonical baseline.
- Added Phase 9 persisted-evidence workstation snapshots over the existing loopback-only Python host: candidates, evidence activity, health, source lineage, and read-only Replay context now cross a versioned boundary without score/readiness recalculation.
- Disabled WPF mock TradePlan, chart, risk, and simulation fallback whenever Phase 9 read-only snapshots are active; missing Python data remains unavailable rather than being replaced by deterministic candidates.
- Added Python mapper/host, C# wire-mapper, presentation, and live C#-to-Python host coverage for the read-only boundary; no broker, Paper, Live, provider, or order capability was added.
- Added Phase 8's versioned local Python Engine Host and WPF lifecycle bridge: discover/launch, reconnect, health/collection snapshots, pause, resume, one-cycle, and explicit graceful shutdown.
- Added atomic duplicate-host and duplicate-cycle guards, legacy active-monitor-runner conflict blocking, loopback-only authenticated IPC, structured protocol failures, and Python/.NET process-level integration tests.
- Kept candidate, research, Replay, TradePlan, Risk Governor, simulation, broker, Paper, and Live workflows outside the Phase 8 process boundary.
- Established `ROADMAP.md` as the sole current-status and next-work authority, retired the independent Current State document, and added a required roadmap reconciliation gate to governance templates and operating rules.
- Replaced the obsolete PySide-first planning direction in active governance sources with the Python-canonical, Windows-first C#/.NET WPF workstation-shell feasibility path.
- Recorded R004 as implemented and pending Steven merge; broker research and paper-execution preparation remain deferred until the WPF direction and Python engine boundary are proven.
- Added ARGUS-QUALITY-002 simulation hardening tests and narrow safety fixes for adapter rejection, auditor chronology, preview-before-submit evidence, and locked UI no-op behavior.
- Blocked Simulation Lab from using non-Fake, transmit-capable, credential-backed, wrong-mode, or paper/live/transmit-capability adapters before preview/submit calls.
- Hardened Execution Auditor simulation-chain checks so submit evidence requires prior preview evidence and Risk Governor evidence must come before preview/submit/block evidence.
- Added ARGUS-QUALITY-001 simulation foundation quality review, A016 readiness decision, hardening plan, and test quality review.
- Classified the simulation foundation as ready for A016 broker research with cautions, while requiring hardening before A017/A018 paper broker work.
- Added branch truth ledger and canonical code path docs so future work starts from real local `master` state instead of stale feature branch reports.
- Reconciled local `master` after the clean-room Argus Machine simulation foundation merge; `master` remains unpushed and ahead of `origin/master`.
- Hardened Argus Machine simulation cockpit with FakeBroker-only simulated orders, simulated positions, and ledger-backed fills/events panels.
- Added a visible Execution Auditor paper advancement gate that reports `PASS`, `WARN`, or `BLOCK` from TradePlan, RiskResult, Ledger, and FakeBroker evidence while keeping paper/live controls locked.
- Added artifact-first subagent work contracts so helper agents must create role-specific artifacts, proof, specs, checklists, mockups, briefs, or handoffs instead of advice-only responses.
- Added Graphics Designer, Product Roadmap Agent, and App Architect helper roles with firm non-code boundaries.
- Extracted Gateway and Argus Machine console UI construction into `momentum_hunter/ui/autonomy_gateway.py`, reducing `app.py` while preserving gateway routing, display-only placeholder state, Trade Plan Ladder population, and locked order controls.
- Added ARGUS-R001 app.py responsibility map, extraction target ranking, extraction risk matrix, and R002-R006 task contracts.
- Added ARGUS-R000 architecture decision docs recommending staged PySide6 modernization, app.py extraction, and a backend/frontend boundary instead of a full rewrite now.
- Added startup gateway with Steven Desk and Argus Machine choices.
- Added safe Argus Machine Console shell with Machine Status Bar, Top 5 Trade Plan Candidates, Selected Candidate Workbench, Trade Plan Ladder, Risk Governor, locked Order Console, and Machine Log.
- Added focused UI tests for gateway routing, Top 5 candidate selection, Trade Plan Ladder population, and disabled order controls.
- Added ARGUS-A000 autonomous platform foundation docs for Steven Desk, Argus Machine, autonomy modes, Machine Console, Trade Plan Ladder, Top 5 Trade Plan Candidates, Risk Governor, Broker Adapter, and Execution Ledger.
- Added autonomous-side agent roles for execution architecture, risk governance, broker integration, paper trading, chart analysis, equity research, and execution auditability.
- Added the first 20 autonomous roadmap tasks and fully specified ARGUS-A001 through ARGUS-A005.
- Added permanent Goal Steward governance for Goal Charters, acceptance alignment, non-goals, and completion evidence before Builder work.
- Added `GOALS.md` with the active Daily Workflow "make the next light click" goal and a governance goal requiring Goal Charters before Builder tasks.
- Added a Goal Charter template and updated task/merge templates to require explicit goal framing.
- Added permanent Git Steward governance for branch safety, Git preflight, safety branches, allowed-path checks, fast-forward merge safety, and push refusal.
- Updated Argus Office task flow so Git Steward prepares/verifies branches before implementation and performs merges only after Steven approval.
- Added the ARGUS-0004 Guided Daily Workflow stepper bridge: the existing Daily Workflow modal now leads with trust state, next required action, five-step sequence, status lights, dependencies, blockers, and the same quick actions.
- Demoted Daily Workflow checklist/warning tables into audit tabs while preserving existing report facts and warning meanings.
- Added focused Daily Workflow regression coverage for the guided stepper labels, status lights, and read-only blocker language.
- Restored a visible Dashboard path to the existing Daily Checklist workflow for ARGUS-0002.
- Guarded Daily Checklist quick actions so target dialogs and unavailable-action messages are visible instead of appearing to do nothing.
- Added focused Daily Workflow GUI regression coverage that opens the checklist through the restored button.
- Added Argus Office v0.1 scaffold for governance, agent roles, commandbus workflow, templates, branch policy, and release documentation.
- Established Steven as final merge approver, ChatGPT as CEO Advisor, and Codex Orchestrator as the single Codex-side front door.
- Distinguished read-only specialist agents from Builder, the only normal code-writing agent.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
