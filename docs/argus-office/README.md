# Argus Office

Argus Office v0.1 is the operating scaffold for Momentum Hunter / Argus. It defines how Steven, ChatGPT, Codex Orchestrator, and specialist agents coordinate work while keeping code changes controlled, reviewed, and reversible.

## Authority Model
- Steven is CEO, product owner, and final merge approver.
- ChatGPT is CEO Advisor, Chief of Staff, task architect, and reviewer.
- Codex Orchestrator is the single Codex-side front door for multiagent work.
- Office Manager maintains the office structure.
- Specialist agents analyze and recommend.
- Builder is the only normal code-writing agent.
- QA may write tests only when explicitly assigned.
- Release Scribe updates docs, reports, logs, and checklists.

## Operating Model
Work begins as a CEO request, moves through the commandbus, is mapped or reviewed by specialists, is implemented only by Builder when approved, and returns as a consolidated CEO report for review.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## No Push / No Merge
No agent may push or merge without explicit approval. No agent merges to `master` or `main`; Steven remains final merge approver.
