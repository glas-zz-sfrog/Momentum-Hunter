# CEO Console

## Steven's Role
Steven is CEO, product owner, priority setter, and final merge approver. Steven decides what matters, what ships, and when work is accepted into `master` or `main`.

## ChatGPT's Role
ChatGPT acts as CEO Advisor, Chief of Staff, task architect, and reviewer. ChatGPT helps shape requests, clarify acceptance criteria, review outputs, and reduce Steven's project-management load.

## Current Position
Read `ROADMAP.md`, especially its `Now` section, for the single authoritative current phase, active branch, merge state, safety gates, and next action. This file must not duplicate moving task state.

## Operating Model
Steven talks to ChatGPT, ChatGPT writes the task prompt, Goal Steward verifies the Goal Charter, Git Steward prepares or verifies the branch, Codex Orchestrator coordinates specialists, Builder implements only approved scoped tasks, QA verifies, Release Scribe documents, and Git Steward performs local fast-forward merges only after Steven approval. Nothing pushes unless Steven explicitly approves.

## Protected Areas
Do not change these areas without explicit approval: core scoring logic, trade readiness logic, replay identity rules, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, or runtime behavior.

## Next Recommended Action
Use the Roadmap's `Now` section. At this revision, the immediate CEO decision is whether to merge the verified R004 WPF workstation-shell spike into local `master`.
