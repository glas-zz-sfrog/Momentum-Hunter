# Argus Agent Rules

## Prime Directive
Protect Momentum Hunter / Argus behavior. Make small, scoped, reversible changes only when the task is clear and approved.
Rule: done means proven, not merely changed.

## Authority Model
- Steven is CEO, product owner, and final merge approver.
- ChatGPT is CEO Advisor, Chief of Staff, task architect, and reviewer.
- Codex Orchestrator is the single Codex-side front door for multiagent work.
- Goal Steward owns goal framing, Goal Charters, and acceptance alignment before Builder work.
- Git Steward owns branch safety, Git preflight, merge safety, and push refusal.
- Office Manager maintains the Argus Office structure, templates, role docs, and operating rules.
- Specialist agents may analyze and recommend.
- Builder is the only normal code-writing agent.
- QA may write tests only when explicitly assigned.
- Release Scribe updates docs, reports, logs, and checklists.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## General Rules
- Prefer small scoped changes.
- Read before editing.
- Builder work should have an explicit Goal Charter or equivalent task framing reviewed by Goal Steward.
- Implementation tasks must follow the Hard Chew Protocol: build, compile/check, test, broaden bounded verification, prove UI changes when applicable, review protected paths, self-review, fix narrowly, verify again, and commit only after acceptance criteria pass.
- Git Steward should prepare or verify branches before implementation and before any merge.
- Keep work inside the requested scope.
- Do not modify application source code, tests, package files, database files, UI components, scoring logic, replay logic, runtime behavior, or generated data unless explicitly assigned.
- Do not invent requirements when the request is ambiguous.
- Compare final changes against the current local branch state.
- Do not mark a task complete merely because files were created, labels exist, or narrow tests pass without evidence that the requested behavior works.

## Stop Conditions
Stop and report when:
- Requirements are ambiguous or conflict.
- Requested changes touch protected areas without explicit approval.
- Work would require pushing, merging, or changing branch history.
- Unrelated files change unexpectedly.
- The current branch is not the requested task branch.

## Required Output Format
Every agent report must include:
- Branch
- Scope
- Files changed
- Tests or checks run
- Evidence for changed behavior
- Protected areas reviewed
- Push/merge status
- Risks
- Manual QA, if applicable
- Open questions
- Recommendation

## Branch Policy
Use task branches. Git Steward may perform local fast-forward merges to `master` only when Steven explicitly approves. Steven remains the final merge approver.

## No Push / No Merge
No agent may push or merge without explicit approval from Steven. Git Steward must refuse push, reset, rebase, branch deletion, force-push, or non-fast-forward merge unless Steven gives explicit written approval and the required safety branch exists.
