# Current State

## Phase
Argus Office v0.1 first controlled Builder task.

## Branch
`codex/ARGUS-0002-daily-checklist-visibility`

## State Summary
ARGUS-0002 restored a visible Dashboard path to the existing Daily Checklist workflow. The change reuses the existing Daily Checklist button/dialog and keeps the workflow as a Dashboard modal action rather than adding a new navigation page.

## Active Rule
Steven remains final merge approver. No push or merge has been performed. Future work should remain task-branch scoped and avoid protected areas unless explicitly approved.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next State Target
Steven should manually QA the restored Daily Checklist path, then decide whether to merge ARGUS-0002. Recommended next task: repair screenshot-capture validation so UI screenshot evidence must be nonblank and have sane dimensions before it is trusted.
