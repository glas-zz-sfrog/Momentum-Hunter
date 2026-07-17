# Goal Charter: R008 Python Engine Contract Host

## Goal Statement

Separate the canonical Python collection lifecycle from the visible WPF workstation through a small, versioned, local-only boundary.

## User Pain / Operator Outcome

Closing, restarting, or losing the WPF workstation must not silently stop collection. Steven needs one discoverable Python Engine Host with honest health and collection state, plus explicit pause, resume, run-cycle, and shutdown controls.

## In Scope

- Versioned provider-neutral host identity, health, collection, capability, command, and error contracts.
- A single independently hosted Python process using loopback-only IPC.
- WPF discovery, attach, launch-if-missing, reconnect, and deliberate shutdown.
- Host-owned collection state, pause, resume, and single-cycle commands.
- Duplicate-host and duplicate-cycle prevention.
- Focused Python and .NET tests plus a process-level independence proof.

## Out Of Scope

- Candidate, research, evidence, replay, TradePlan, readiness, Risk Governor, simulation, broker, Paper, Live, credentials, provider changes, or database/schema changes.
- Rewriting the canonical Python engine or removing the existing Qt/PySide surface.

## Protected Areas

Core scoring, trade readiness, replay identity, historical capture selection, database schema/migrations, broker/order execution, alert semantics, credentials/API keys/environment configuration, production configs, and all Paper/Live behavior remain unchanged.

## Acceptance Criteria

- One Python Engine Host can be discovered or launched locally by WPF and exposes versioned snapshots.
- The host permits only host identity, health, collection state, pause, resume, run-cycle, and graceful-shutdown commands.
- Host lease and command IDs prevent duplicate hosts, loops, and repeated lifecycle effects.
- WPF restart reconnects to the same host; ordinary WPF shutdown does not occur on crash, while explicit Exit shuts down both processes deliberately.
- No candidate or trading-domain workflow crosses the new boundary.

## Evidence Required

- Python compile, focused host tests, .NET build/tests, and bounded regression suites.
- Process proof that a separate client exit does not end the Python host and that reconnect uses the same host ID.
- Negative tests for malformed requests, protocol mismatch, unauthenticated requests, duplicate host launch, paused collection, concurrent cycle request, duplicate command ID, and shutdown cleanup.
- Protected-path diff review, self-review, clean Git state, and a release report with limits stated plainly.

## Smallest Safe Implementation Slice

Build a local host around the existing canonical active-monitor cycle with no provider-fetch flags, then replace only WPF's in-process collection lifecycle adapter. Keep all workstation data panes on their existing deterministic client until Phase 9.

## Open CEO Decisions

- None for Phase 8. Paper and Live remain separate approval gates.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove the requested outcome.
- [x] Evidence required is strong enough to verify completion.
