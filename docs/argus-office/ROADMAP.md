# Roadmap

## Phase 0 - Office Scaffold
- Create agent roster, operating rules, commandbus folders, templates, and role docs.
- Keep all changes governance/configuration/documentation-only.

## Phase 1 - Read-Only Mapping
- Use Code Mapper to document key routes, data flows, scoring surfaces, replay surfaces, alert flows, and operator workflows.
- Use specialists to identify risks and task candidates.

## Phase 2 - Scoped Improvements
- Convert approved findings into small tasks.
- Builder implements only approved work.
- QA validates regression risk and may add tests only when explicitly assigned.

## Phase 3 - Release Discipline
- Release Scribe maintains changelog, task log, decision log, reports, and merge checklists.
- Steven remains final merge approver.

## Phase 4 - Autonomous Platform Foundation
- Split the product direction into Steven Desk and Argus Machine.
- Define autonomy modes, Machine Console panels, Trade Plan Ladder, Top 5 Trade Plan Candidates, Risk Governor, Broker Adapter roadmap, and Execution Ledger.
- Keep autonomous agents read-only/spec-only by default until future Goal Charters explicitly approve implementation.

## Phase 5 - Staged Architecture Modernization
- Do not rewrite Momentum Hunter now.
- Keep Python as the core engine for scanning, scoring, evidence, replay, storage, readiness, trade planning, and risk governance.
- Modernize PySide6 first with a real design system and extracted UI modules.
- Shrink `momentum_hunter/app.py` through small, test-protected extractions.
- Define a backend/frontend boundary before considering C# WinUI, Avalonia, or Tauri as replacement frontends.
- Use ARGUS-R001 as the responsibility map for extraction order.
- Start implementation with Gateway / Argus Machine UI extraction before touching scanner, review, watchlist, capture, replay, readiness, or broker-adjacent behavior.

## Phase 6 - Simulation Foundation And Branch Reconciliation
- Local `master` now contains the Argus Machine simulation foundation through the clean-room verification merge.
- Treat `momentum_hunter/autonomy/*`, `momentum_hunter/ui/autonomy_gateway.py`, and `momentum_hunter/ui/trade_plan_ladder.py` as canonical for the current Argus Machine simulation path.
- Treat `codex/ARGUS-A006-A015-argus-machine-simulation` and `codex/ARGUS-A004-A005-tradeplan-risk-governor` as superseded branches.
- Keep `master` local until Steven explicitly approves a push.
- Maintain `docs/argus-office/BRANCH_LEDGER.md` and `docs/argus-office/CANONICAL_CODE_PATHS.md` whenever merge state changes.

## Phase 7 - Broker Research Before Paper Code
- Next planned Builder-adjacent work is A016 broker research matrix, docs-only.
- Do not implement paper broker code, live broker code, credentials, API keys, or order routing in A016.
- Future paper broker work must start from a new Goal Charter and must preserve FakeBroker / paper / read-only live / preview / confirmed live separation.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
