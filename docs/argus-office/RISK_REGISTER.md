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

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
