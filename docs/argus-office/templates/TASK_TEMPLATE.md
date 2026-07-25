# Task Template

## Task ID

## Branch

## Owner

## Scope

## Out of Scope

## Acceptance Criteria
-

## Assigned Agents

## Goal Charter
- [ ] Goal Steward reviewed or created a Goal Charter before Builder work.
- [ ] Goal statement is explicit.
- [ ] User pain or operator outcome is explicit.
- [ ] In scope and out of scope are explicit.
- [ ] Acceptance criteria and evidence required are explicit.

## Git Steward Preflight
- [ ] Current branch confirmed.
- [ ] Branch base confirmed.
- [ ] Worktree clean/dirty state confirmed.
- [ ] Ahead/behind versus `origin/master` reported.
- [ ] Allowed changed paths identified.

## Roadmap Ledger
- [ ] Read `docs/argus-office/ROADMAP.md` before work and confirmed the active task and next action.
- [ ] Final Roadmap status will distinguish branch-only implementation from merged completion.
- [ ] Required `Now` section fields, affected phase, next action, and block/decision gates are identified.

## Hard Chew Protocol
Required for app-code, UI-code, runtime, workflow, or behavior-changing tasks. Done means proven, not merely changed.
- [ ] Build/implementation pass completed.
- [ ] Full compile check run where applicable.
- [ ] Focused tests prove the changed behavior.
- [ ] Broader bounded test discovery run with timeout handling.
- [ ] UI proof captured for UI changes, including screenshot sanity checks when possible.
- [ ] Protected-path diff review completed.
- [ ] Second-pass self-review covered diff, tests, docs, and user-facing behavior.
- [ ] Narrow fix pass completed for issues found during self-review.
- [ ] Final verification pass completed.
- [ ] Commit created only after acceptance criteria passed.

## Checks Required

## Protected Areas
Name every protected area touched and the exact authorized outcome. Do not ask again when the current task or Roadmap already authorizes that bounded result. Define anomaly conditions that must interrupt Steven before scope, semantics, destruction, credential state, or real execution changes.

## Steven Interruption Conditions
- Visual/manual acceptance required:
- Unexpected external state that changes exposure:
- Destructive or irreversible action:
- Real order or unattended-live action:
- Secret, provider, paid-service, or Git-divergence risk:

## Output Required
- Branch
- Files changed
- Tests or checks run
- Git Steward branch/status report
- Commands run
- Behavior evidence
- UI proof artifacts, if UI changed
- Protected areas reviewed
- Push/merge status
- Risks
- Manual QA
- Open questions
- Recommendation
- Roadmap transition and exact next action
