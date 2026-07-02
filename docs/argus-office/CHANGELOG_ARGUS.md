# Argus Changelog

## Unreleased
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
