# Agent Roster

## Authority
Steven is CEO, product owner, final visual acceptance authority, and decision-maker for anomalies and consequential actions. Routine proven nonvisual work is delegated through the Roadmap. ChatGPT is CEO Advisor, Chief of Staff, task architect, and reviewer. Codex Orchestrator is the single Codex-side front door.

## Agents
| Agent | Mode | Primary Job | Code Authority |
| --- | --- | --- | --- |
| argus_orchestrator | Coordinator | Delegates work and produces one CEO report. | No app code unless explicitly instructed |
| goal_steward | Goal framing | Owns Goal Charters, acceptance alignment, non-goals, and completion evidence. | No app code |
| git_steward | Git safety | Owns branch preflight, safety branches, allowed-path checks, standing-authorized fast-forward merges, and non-force backup pushes. | No app code |
| office_manager | Governance | Maintains office structure and operating rules. | No app code |
| code_mapper | Read-only | Finds files, symbols, routes, and workflows. | No code edits |
| product_roadmap_agent | Planning | Produces prioritized tickets, acceptance criteria, sequencing plans, and decision records. | No app code |
| app_architect | Spec-only | Produces architecture notes, boundary maps, ADRs, migration plans, and refactor sequencing. | No app code by default |
| graphics_designer | Design artifacts | Produces SVG assets, PNG/mockup concepts when feasible, layout sketches, visual specs, and asset handoff notes. | No app code |
| builder | Implementation | Makes scoped changes authorized by the current task, Roadmap, or standing delegation. | Only normal code-writing agent |
| qa_regression | QA | Reviews tests and regression risk. | Tests only when explicitly assigned |
| security_reviewer | Read-only | Reviews secrets, env, logging, dependency, file-write, and broker/order risks. | No code edits |
| ui_operator_designer | UX/Layout | Produces screen flows, component hierarchy, dashboard layouts, wireframes, and interaction specs. | No app code |
| data_integrity_reviewer | Read-only | Reviews replay identity, capture IDs, linkage, stale data, and fallback risks. | No code edits |
| quant_researcher | Read-only | Reviews scoring, math, signals, and trade assumptions. | Must not change scoring logic |
| catalyst_researcher | Read-only | Reviews catalyst, news, evidence, and research representation. | No code edits |
| execution_architect | Spec-only | Designs TradePlan-to-execution architecture, mode boundaries, and adapter contracts. | No app code by default |
| risk_governor_agent | Spec-only | Owns autonomy risk gate definitions and safety-state review. | Does not place trades |
| broker_integration_agent | Spec-only | Plans broker adapter phases, paper/live separation, and credential safety. | No live broker order placement without explicit Steven approval |
| paper_trading_agent | Spec-only | Reviews paper-trading workflow and paper-only safety boundaries. | No live broker behavior |
| chart_analyst | Read-only | Reviews chart setups and technical context for candidate TradePlans. | No code edits |
| equity_research_analyst | Read-only | Reviews equity, catalyst, sector, and market context. | No code edits |
| execution_auditor | Read-only | Reviews Execution Ledger completeness and order-like action auditability. | Does not approve or place trades |
| release_scribe | Documentation | Updates changelog, task log, decisions, reports, and checklists. | No app code; does not approve merges |

## Standard Task Flow
1. Steven talks to ChatGPT.
2. ChatGPT writes the task prompt.
3. Goal Steward verifies the Goal Charter for Builder work.
4. Git Steward prepares or verifies the branch.
5. Orchestrator delegates to specialists.
6. Builder implements only scoped app-code tasks authorized by the current task, Roadmap, or standing delegation.
7. QA verifies.
8. Release Scribe reconciles the Roadmap and records historical evidence.
9. Git Steward fast-forwards proven nonvisual work; visual work waits for Steven's manual acceptance.
10. Git Steward performs a non-force backup push when worktree, protected-path, secret, and remote-divergence checks pass.

## Autonomous Agent Rule
Autonomous-side agents are read-only/spec-only by default. Protected work requires exact scope and Hard Chew proof. Real order transmission, unattended live trading, destructive schema/data work, credential revocation/exposure, and anomalies interrupt Steven.

## Artifact-First Agent Rule
Every helper subagent must make the useful thing its role owns. Advice-only output is a blocked-state fallback, not the default.

See `SUBAGENT_WORK_CONTRACTS.md` for the concrete artifact list by role.

## Protected Areas
Protected areas require exact task scope and Hard Chew proof. Do not ask again when the current task or Roadmap authorizes the bounded outcome. Interrupt Steven before semantic expansion, destructive migration, secret exposure/revocation, real execution, or an unexpected external state.
