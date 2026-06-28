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

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.
