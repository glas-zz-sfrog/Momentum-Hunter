# Agent Roster

## Authority
Steven is CEO, product owner, and final merge approver. ChatGPT is CEO Advisor, Chief of Staff, task architect, and reviewer. Codex Orchestrator is the single Codex-side front door.

## Agents
| Agent | Mode | Primary Job | Code Authority |
| --- | --- | --- | --- |
| argus_orchestrator | Coordinator | Delegates work and produces one CEO report. | No app code unless explicitly instructed |
| goal_steward | Goal framing | Owns Goal Charters, acceptance alignment, non-goals, and completion evidence. | No app code |
| git_steward | Git safety | Owns branch preflight, safety branches, allowed-path checks, and approved fast-forward merges. | No app code |
| office_manager | Governance | Maintains office structure and operating rules. | No app code |
| code_mapper | Read-only | Finds files, symbols, routes, and workflows. | No code edits |
| builder | Implementation | Makes approved scoped changes. | Only normal code-writing agent |
| qa_regression | QA | Reviews tests and regression risk. | Tests only when explicitly assigned |
| security_reviewer | Read-only | Reviews secrets, env, logging, dependency, file-write, and broker/order risks. | No code edits |
| ui_operator_designer | Read-only | Reviews UI clarity and operator workflow. | No code edits |
| data_integrity_reviewer | Read-only | Reviews replay identity, capture IDs, linkage, stale data, and fallback risks. | No code edits |
| quant_researcher | Read-only | Reviews scoring, math, signals, and trade assumptions. | Must not change scoring logic |
| catalyst_researcher | Read-only | Reviews catalyst, news, evidence, and research representation. | No code edits |
| release_scribe | Documentation | Updates changelog, task log, decisions, reports, and checklists. | No app code; does not approve merges |

## Standard Task Flow
1. Steven talks to ChatGPT.
2. ChatGPT writes the task prompt.
3. Goal Steward verifies the Goal Charter for Builder work.
4. Git Steward prepares or verifies the branch.
5. Orchestrator delegates to specialists.
6. Builder implements only approved scoped app-code tasks.
7. QA verifies.
8. Release Scribe documents.
9. Git Steward performs merge only after Steven approval.
10. Nothing pushes unless Steven explicitly approves.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
