# Merge Checklist

## Task

## Branch

## Confirmations
- [ ] Goal Steward confirmed the Goal Charter or equivalent task framing.
- [ ] Acceptance evidence maps back to the Goal Charter.
- [ ] Git Steward confirmed current branch and expected task branch.
- [ ] Git Steward confirmed branch base.
- [ ] Git Steward confirmed worktree status.
- [ ] Git Steward confirmed ahead/behind versus `origin/master`.
- [ ] Scope matches approved task.
- [ ] Only expected files changed.
- [ ] Tests or checks completed.
- [ ] Risks documented.
- [ ] Manual QA documented, if applicable.
- [ ] No push without explicit approval.
- [ ] Steven explicitly approved merge.
- [ ] Merge is fast-forward only, or Steven explicitly approved another strategy in writing.
- [ ] Steven reviewed final report.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Final Merge Decision
Steven is final merge approver. Git Steward performs local fast-forward merge only after Steven approval and reports final Git state.
