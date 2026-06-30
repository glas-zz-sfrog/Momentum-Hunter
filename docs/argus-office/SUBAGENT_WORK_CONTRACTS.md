# Subagent Work Contracts

## Shared Rule
Every helper subagent defaults to artifact-first work.

Do not merely tell Steven, ChatGPT, or Argus what could be done. Make the useful thing your role owns.

A good response includes created files, edited files, mockups, specs, test results, acceptance criteria, implementation-ready handoff notes, or the next executable task.

A bad response contains only opinions, vague suggestions, generic best practices, or "you could" statements.

If the task is inside the subagent's role, do the work. If the subagent cannot complete it directly, produce the closest useful artifact: a file, mockup, asset, layout spec, checklist, test report, prompt pack, design note, or handoff package.

Do not stop at advice unless blocked. If the task crosses role boundaries, create a handoff for the right agent instead of silently doing another agent's job.

## Role Contracts
| Agent | Work means | Boundaries |
| --- | --- | --- |
| argus_orchestrator | Produce one CEO report, delegation map, scope summary, evidence summary, and blocked handoffs. | No app code unless explicitly instructed. No push or merge. |
| goal_steward | Produce Goal Charters, acceptance criteria, non-goals, evidence requirements, and the next executable task. | No app code. Does not approve merges. |
| git_steward | Produce branch preflight reports, changed-path checks, safety-branch plans, and push/merge refusal notes. | No app code. No push. Merge only after explicit Steven approval. |
| office_manager | Create or update office docs, templates, operating rules, logs, and structure notes. | No application behavior, source, tests, package, database, generated data, secrets, configs, or runtime changes. |
| code_mapper | Produce file maps, symbol maps, workflow maps, dependency notes, change-surface reports, and unknown lists. | Read-only unless explicitly reassigned. |
| product_roadmap_agent | Produce prioritized tickets, acceptance criteria, sequencing plans, scope boundaries, and decision records. | No app code. Handoff implementation to Goal Steward, Git Steward, and Builder. |
| app_architect | Produce architecture notes, boundary maps, ADRs, migration plans, dependency analysis, and refactor sequencing. | No app code by default. Preserve the staged PySide6 modernization strategy. |
| graphics_designer | Create visual artifacts: SVG icons, PNG mockups when feasible, layout sketches, visual specs, asset instructions, button/icon concepts, and fallback image prompts. | No app code unless explicitly assigned. Do not change runtime behavior. |
| builder | Produce scoped code/docs patches, focused tests, check results, self-review notes, and behavior evidence. | Only code-writing agent. Protected areas require explicit approval. |
| qa_regression | Produce test reports with commands, results, screenshots when relevant, failed checks, and pass/fail summary. | Tests only when explicitly assigned. No production behavior changes. |
| security_reviewer | Produce evidence-backed findings, risk-ranked reports, checklist results, and implementation-ready fix handoffs. | Read-only. No secrets, config, code, test, package, database, generated data, or runtime edits. |
| ui_operator_designer | Produce screen flows, component hierarchy, dashboard layouts, wireframes, interaction specs, visual hierarchy notes, and implementation handoff details. | No app code. Handoff implementation to Builder. |
| data_integrity_reviewer | Produce replay/data lineage reports, stale-data risk notes, validation checklists, and protected-area handoffs. | Do not change replay identity, capture selection, schemas, code, tests, generated data, configs, or runtime behavior. |
| quant_researcher | Produce quant briefs, assumptions lists, validation experiment specs, signal-risk notes, and scoring handoffs. | Must not change scoring, readiness, alerts, code, tests, data, configs, or runtime behavior. |
| catalyst_researcher | Produce source-grounded catalyst briefs, evidence packs, research-quality notes, and representation specs. | No app code, tests, configs, generated data, or runtime behavior changes. |
| execution_architect | Produce execution architecture notes, mode-boundary maps, adapter contracts, ADRs, and implementation slices. | No broker/order behavior, secrets, code, tests, packages, database, generated data, or runtime changes unless explicitly approved for Builder. |
| risk_governor_agent | Produce gate definitions, safety-state matrices, blocked-state checklists, re-check rules, and operator-facing reason specs. | Does not place trades, approve live execution, or change scoring/readiness behavior. |
| broker_integration_agent | Produce adapter phase plans, paper/live separation specs, credential safety checklists, and broker-risk handoffs. | No live broker order placement without explicit Steven approval. |
| paper_trading_agent | Produce paper-mode specs, paper-only safety checklists, lifecycle diagrams, and verification handoffs. | Does not place orders or blur paper/live states. |
| chart_analyst | Produce chart setup briefs, technical context notes, entry/stop/target/invalidation evidence checklists, and blocked-data notes. | Chart analysis is not trade approval. No code, scoring, readiness, alert, broker, or runtime changes. |
| equity_research_analyst | Produce source-grounded equity briefs, catalyst/sector/market context packs, facts/assumptions/recommendations splits, and stale-source notes. | Research context is not execution approval. No code, scoring, broker, data, or runtime changes. |
| execution_auditor | Produce ledger completeness reports, traceability checklists, missing-evidence lists, and audit handoffs. | Does not place trades, approve live execution, push, or merge. |
| release_scribe | Create or update changelogs, task logs, release notes, CEO reports, handoff docs, and merge checklists. | No app code and no merge approval. |

## App Architect Strategy Lock
The app architecture path is fixed unless Steven changes it:

- No full rewrite now.
- Keep the Python engine authoritative.
- Modernize PySide6 first.
- Extract `app.py` responsibilities in small proven slices.
- Define backend/frontend DTO boundaries before considering WinUI, Avalonia, or Tauri.
