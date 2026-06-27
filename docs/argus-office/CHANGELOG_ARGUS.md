# Argus Changelog

## Unreleased
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
