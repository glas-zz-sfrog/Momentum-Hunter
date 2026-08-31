# ARGUS-PARALLEL-WORKSTREAM-GOVERNANCE-001 Goal Charter

## Objective

Establish three isolated persistent development lanes while preserving canonical
`master` as a clean, accepted-integration-only production checkout.

## Accepted Base

`14f7b24783146fc2dcf7ad64f205aac11b19d392`

Local `master` and `origin/master` must equal this commit and the production
checkout must be clean before setup begins.

## Authorized Scope

- Create one detached persistent AppData worktree root for each of `SCIENCE`,
  `OPENING_ENGINE`, and `GUI`.
- Record lane ownership, protected paths, capability boundaries, external-state
  isolation, package gates, second-eye gates, and merge gates.
- Establish immutable task-base, no-mid-task-sync, reviewed-head, and serialized
  integration rules.
- Make the repository's agent rules and authoritative Roadmap reflect the new
  operating model.
- Record `OBSERVER-AUTHORIZED-RELEASE-BINDING-001` as deferred work only.

## Prohibited Scope

Do not start lane tasks, modify Product/runtime/test/tool bytes, deploy, alter a
service or scheduler, mutate the approved Python environment, contact a provider,
or use Paper, Shadow, account, broker, position, or order authority.

## Acceptance

1. The production checkout remains clean on synchronized `master`.
2. All three persistent lane worktrees exist, are clean, detached, isolated, and
   contain no active task.
3. The registry contains every mandatory active-task field and unique evidence,
   temporary-runtime, and package-root templates.
4. Cross-lane contracts and integration are serialized and fail closed.
5. Shared governance documents are Integration-Steward-owned by default.
6. No executable, test, tool, runtime, service, scheduler, manifest, or approved
   environment state changes.
7. The deferred observer release-binding task is recorded without implementation.

## Stop Gate

Stop after governance setup and verification. Science, Opening Engine, and GUI
tasks require separate authorization and initialization.
