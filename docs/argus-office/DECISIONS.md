# Decisions

| Date | Decision | Owner | Rationale | Status |
| --- | --- | --- | --- | --- |
| 2026-06-27 | Create Argus Office v0.1 scaffold. | Steven | Reduce manual project-management burden while preserving code control. | Accepted |
| 2026-06-27 | Make Codex Orchestrator the single Codex-side front door. | Steven | Keep multiagent work coordinated and reportable. | Accepted |
| 2026-06-27 | Distinguish recommendation-only agents from Builder. | Steven | Prevent accidental code changes from analysis roles. | Accepted |
| 2026-06-27 | Require no push and no merge without explicit approval. | Steven | Keep Steven as final merge approver. | Accepted |

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
