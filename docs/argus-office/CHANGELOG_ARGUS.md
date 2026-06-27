# Argus Changelog

## Unreleased
- Restored a visible Dashboard path to the existing Daily Checklist workflow for ARGUS-0002.
- Guarded Daily Checklist quick actions so target dialogs and unavailable-action messages are visible instead of appearing to do nothing.
- Added focused Daily Workflow GUI regression coverage that opens the checklist through the restored button.
- Added Argus Office v0.1 scaffold for governance, agent roles, commandbus workflow, templates, branch policy, and release documentation.
- Established Steven as final merge approver, ChatGPT as CEO Advisor, and Codex Orchestrator as the single Codex-side front door.
- Distinguished read-only specialist agents from Builder, the only normal code-writing agent.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
