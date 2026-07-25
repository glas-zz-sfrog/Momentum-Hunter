# Argus Office

Argus Office v0.1 is the operating scaffold for Momentum Hunter / Argus. It defines how Steven, ChatGPT, Codex Orchestrator, and specialist agents coordinate work while keeping code changes controlled, reviewed, and reversible.

## Authority Model
- Steven is CEO, product owner, final visual acceptance authority, and decision-maker for anomalies and consequential actions.
- Routine proven nonvisual work, clean fast-forward integration, and non-force backup are delegated through the Roadmap.
- ChatGPT is CEO Advisor, Chief of Staff, task architect, and reviewer.
- Codex Orchestrator is the single Codex-side front door for multiagent work.
- Office Manager maintains the office structure.
- Specialist agents make role-specific artifacts. Advice alone is only acceptable when blocked.
- Builder is the only normal code-writing agent.
- QA may write tests only when explicitly assigned.
- Release Scribe updates docs, reports, logs, and checklists.

## Operating Model
Work begins as a CEO request or Roadmap slice, moves through the commandbus, is mapped or reviewed by specialists, is implemented only by Builder when scoped and authorized, and returns as a consolidated CEO report.

## Current Work
Open `ROADMAP.md` first. Its `Now` section is the single authoritative current-status and next-work record; the branch ledger and task log provide supporting evidence rather than competing summaries.

## Artifact-First Work
Every helper subagent must make the useful thing its role owns: a brief, file map, wireframe, visual asset, test report, checklist, spec, ticket set, ADR, changelog entry, or implementation-ready handoff. Do not stop at "you could" advice unless the task is blocked.

## Protected Areas
Protected areas require exact task scope and Hard Chew proof. Interrupt Steven before semantic expansion, destructive migration, secret exposure/revocation, real execution, or unexpected external state.

## Integration And Interruption
Git Steward may cleanly fast-forward and non-force-push proven nonvisual work under standing delegation. Visual work waits for Steven's manual acceptance. Unsafe Git, anomalies, real orders, destructive changes, credential/provider actions, and paid services require a concrete Steven decision.
