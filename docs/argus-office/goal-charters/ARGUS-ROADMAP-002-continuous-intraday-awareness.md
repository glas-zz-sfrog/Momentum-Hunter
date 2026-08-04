# ARGUS-ROADMAP-002 Goal Charter - Continuous Intraday Market Awareness

## Goal

Reorient Momentum Hunter from a morning-capture-centered workflow into a
continuous, event-aware intraday system while preserving the existing Python
engine, evidence authority, FakeBroker-only boundary, and fail-closed safety
rules.

The 08:35 Central opening capture remains a valuable bootstrap and immutable
session artifact. It is not the sole discovery window, monitoring cycle, plan
creation point, or opportunity window.

## Operator Outcome

Steven can leave Momentum Hunter running and expect it to:

- discover candidates periodically throughout the session;
- monitor a bounded watch set continuously;
- recognize meaningful setup transitions without cycling on every quote;
- keep market, sector, catalyst, and macro-event context current;
- create immutable, versioned TradePlans for distinct setup identities;
- require Risk Governor evidence for every simulated decision; and
- preserve truthful stale, blocked, missed, failed, and no-trade outcomes.

## Current Problem

The current platform has reliable unattended opening capture, persisted
evidence, candidate reports, TradePlan and Risk Governor primitives, a
FakeBroker lifecycle, a WPF workstation, and preliminary Schwab candle
contracts. Its active roadmap still centers the next analytical work around an
opening snapshot. That leaves no authoritative continuous ownership model for
Schwab Streamer subscriptions, candidate state transitions, event-triggered
reevaluation, plan versioning, intraday catalyst refresh, or rolling market
regime.

## Scope

- Reconcile the authoritative Roadmap to continuous intraday awareness.
- Define one canonical Python-owned Schwab Streamer session and subscription
  manager.
- Separate broad discovery from bounded continuous monitoring.
- Define candidate lifecycle states, event triggers, cadences, and noise
  controls.
- Define immutable setup and TradePlan versioning.
- Define market-regime, macro-event, catalyst, and sequential-breakout research
  contracts.
- Define R031B as the next live, nonpersisting evidence gate.
- Produce implementation-ready task contracts and an explicit dependency chain.

## Non-Goals

- No runtime, service, scheduler, Engine Host, provider, WPF, database, account,
  broker, FakeBroker, selector, scoring, readiness, or Shadow-state change.
- No Schwab connection, subscription, account query, market-data request, or
  live proof in this task.
- No real order method, paper broker, transmitting adapter, or unattended-live
  authority.
- No numerical trading thresholds invented without evidence.
- No official Shadow sample mutation or backfill.
- No claim that continuous monitoring or sequential breakouts have edge.

## Protected Boundaries

- Python remains the canonical trading and evidence engine.
- WPF remains presentation and operator control through versioned Engine Host
  contracts; it never owns a provider connection or recalculates official
  decisions.
- Codex remains optional and downstream of persisted terminal evidence.
- FakeBroker remains the only automated execution boundary.
- Every provider bootstrap must fail closed unless exactly one approved account
  ending `2573`, type `INDIVIDUAL_CASH`, and the immutable account hash agree.
- Any future semantic change to scoring, readiness, selection, TradePlan, Risk
  Governor, fill model, or official sample requires its own prospective version
  and proof.

## Acceptance Criteria

- [x] Current versus target gaps are explicit.
- [x] The 08:35 capture is defined as bootstrap, not the whole trading day.
- [x] Exactly one canonical Schwab Streamer owner is defined.
- [x] Discovery and monitoring have separate responsibilities and cadences.
- [x] Candidate lifecycle states and legal transition principles are defined.
- [x] Event-trigger and data-cadence matrices identify required inputs, actions,
  and fail-closed behavior.
- [x] TradePlans are immutable and versioned by opportunity, setup, and plan
  identity.
- [x] Market-regime, macro-event, catalyst, and sequential-breakout contracts
  are specified without claiming production authority.
- [x] R031B has a strict observation and adjudication contract.
- [x] Prioritized tasks include dependencies, acceptance criteria, and protected
  exclusions.
- [x] Roadmap, goals, decisions, risks, branch ledger, task log, and changelog
  are reconciled from actual Git evidence.
- [x] Canonical runtime, installed service, scheduler, provider state, account
  state, official Shadow state, and generated market evidence remain unchanged.

## Evidence Depth / Hard Chew

- Canonical and feature worktrees are checked independently.
- Local `master` and `origin/master` share base `0bd8a18` at task start.
- DATA-001 `488cbca`, DATA-001B `fe8c929`, and SHADOW-024 `cd43852` are present
  on canonical `master`.
- R031 implementation `a39086c` is followed by closeout/hardening `b96f745`;
  provisional R032A and R031 observer work continues through `35c59ee`,
  `3272476`, and `d6d7217` on the separate candle branch.
- Official Shadow v3 remains activated-empty, unarmed, and `0 / 30`; automatic
  collection is disabled and transmission is unavailable.
- Markdown cross-references, contradiction scans, protected-path review,
  credential-shaped secret scan, and `git diff --check` must pass before commit.
- No application test is required because this task changes documentation only;
  later runtime tasks must execute their own compile, focused, bounded, full,
  and operational proof gates.

## Status

`IMPLEMENTED_PENDING_MERGE` on
`codex/ARGUS-ROADMAP-002-continuous-intraday-awareness`. Canonical `master`, the
installed service, and scheduled opening jobs remain on the pre-task runtime
baseline until a later deliberate integration and repin.

## Goal Steward Review

The charter converts the CEO direction into an implementable sequence without
granting unobserved Schwab behavior, new strategy authority, or runtime access.
The next action is the bounded R031B market-hours proof, not speculative
collector implementation and not another morning-only scoring repair.
