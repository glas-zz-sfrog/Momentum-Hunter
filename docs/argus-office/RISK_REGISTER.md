# Risk Register

| ID | Risk | Area | Severity | Mitigation | Status |
| --- | --- | --- | --- | --- | --- |
| R-001 | Multiagent work creates fragmented recommendations. | Operations | Medium | Codex Orchestrator produces one consolidated CEO report. | Open |
| R-002 | Analysis agents accidentally modify code. | Governance | High | Recommendation-only agents are read-only by default; Builder is the only normal code-writing agent. | Open |
| R-003 | Protected trading or replay semantics change without approval. | Product trust | High | Protected areas require explicit approval and stop conditions. | Open |
| R-004 | Steven becomes the manual task router. | Operations | Medium | ChatGPT shapes tasks; Codex Orchestrator delegates and consolidates. | Open |
| R-005 | Push or merge happens before review. | Release | High | No push or merge without explicit approval; Steven is final merge approver. | Open |

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
