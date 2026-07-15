# Decisions

| Date | Decision | Owner | Rationale | Status |
| --- | --- | --- | --- | --- |
| 2026-06-27 | Create Argus Office v0.1 scaffold. | Steven | Reduce manual project-management burden while preserving code control. | Accepted |
| 2026-06-27 | Make Codex Orchestrator the single Codex-side front door. | Steven | Keep multiagent work coordinated and reportable. | Accepted |
| 2026-06-27 | Distinguish recommendation-only agents from Builder. | Steven | Prevent accidental code changes from analysis roles. | Accepted |
| 2026-06-27 | Require no push and no merge without explicit approval. | Steven | Keep Steven as final merge approver. | Accepted |
| 2026-07-15 | Make `ROADMAP.md` the single current-status authority and retire the independent Current State document. | Steven | Prevent conflicting status summaries and make the next action visible in one place. | Accepted |
| 2026-07-15 | Evaluate the Windows-first C#/.NET WPF workstation shell before further Qt modernization. | Steven | Preserve the Python engine while proving a workstation shell and explicit engine boundary before incremental migration. | Accepted |

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
