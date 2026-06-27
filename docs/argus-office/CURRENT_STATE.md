# Current State

## Phase
Argus Office v0.1 Git Steward installation.

## Branch
`codex/ARGUS-0005-git-steward-agent`

## State Summary
ARGUS-0004 was manually QA approved by Steven and fast-forward merged into local `master`. ARGUS-0005 creates a permanent Git Steward role so branch preflight, safety branches, allowed-path checks, merge safety, and push refusal are owned explicitly.

## Active Rule
Steven remains final merge approver. No push or merge has been performed. Future work should remain task-branch scoped and avoid protected areas unless explicitly approved.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should review the Git Steward governance update. After approval, Git Steward should handle branch preflight for future tasks and perform local fast-forward merges only when Steven explicitly approves.
