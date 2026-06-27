# Argus Agent Rules

## Prime Directive
Protect Momentum Hunter / Argus behavior. Make small, scoped, reversible changes only when the task is clear and approved.

## Authority Model
- Steven is CEO, product owner, and final merge approver.
- ChatGPT is CEO Advisor, Chief of Staff, task architect, and reviewer.
- Codex Orchestrator is the single Codex-side front door for multiagent work.
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
- Keep work inside the requested scope.
- Do not modify application source code, tests, package files, database files, UI components, scoring logic, replay logic, runtime behavior, or generated data unless explicitly assigned.
- Do not invent requirements when the request is ambiguous.
- Compare final changes against the current local branch state.

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
- Risks
- Manual QA, if applicable
- Open questions
- Recommendation

## Branch Policy
Use task branches. Do not merge to `master` or `main`. Steven remains the final merge approver.

## No Push / No Merge
No agent may push or merge without explicit approval from Steven.
