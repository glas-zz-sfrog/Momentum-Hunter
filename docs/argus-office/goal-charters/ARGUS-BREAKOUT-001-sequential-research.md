# ARGUS-BREAKOUT-001 Goal Charter - Sequential Breakout Research

## Goal

Create a deterministic, append-only research evidence layer for intraday
impulse, breakout, missed-entry, failure, pullback, reclaim, exhaustion, and
unavailable-data sequences over canonical completed Schwab minute bars.

## Operator Outcome

Momentum Hunter can preserve the exact structural sequence that occurred for a
candidate instead of reducing the day to one hindsight label. Steven can later
compare continuation, failure, pullback, and reclaim outcomes without the
research layer changing score, readiness, plans, selection, risk, or execution.

## Source Identity

- Canonical base: `1d0ca95`
- Stacked dependency: MONITOR implementation `b71feb0`
- Validated MONITOR branch closeout: `d2b77c2`
- Existing historical indicator engine: `momentum_hunter/technical_breakouts.py`
- Canonical bars: `momentum_hunter/canonical_candle_evidence.py`

## Scope

- Define immutable research observations, events, policy identity, sequence
  identity, and append-only ledger.
- Reuse MONITOR opportunity/setup identities rather than inventing a parallel
  candidate identity system.
- Detect structural impulse, opening/continuation breakout, missed entry,
  failure, pullback, reclaim, exhaustion, and explicit gap/unavailable events
  using only prior and current completed bars.
- Preserve provider timestamp, receipt timestamp, source/state, source evidence
  fingerprint, trigger/reference values, relative volume, and predecessor setup.
- Support exact rerun idempotency, conflict rejection, tamper detection, atomic
  persistence, and source nonmutation.
- Remain dormant until a later integration task wires a prospective producer.

## Non-Goals

- No score, rank, readiness, alert, TradePlan, selector, Risk Governor,
  allocation, FakeBroker, Alpaca, Schwab request, account, position, order,
  service, scheduler, Engine Host, WPF, Shadow, or live behavior change.
- No provider fetch and no production data write in this task.
- No retrospective trade, entry, fill, P&L, recommendation, or edge claim.
- No BREAKOUT-002 outcome conclusion and no PLAN-002 authority.
- No generated report committed to Git.

## Research Rules

- Every trigger uses a prior completed window; current/future bars cannot define
  their own trigger.
- A missed or failed breakout remains immutable. Pullback and reclaim receive
  new setup identities with predecessor links.
- Numerical thresholds are versioned research policy, not trading law.
- Gaps and insufficient observations reset sequence derivation and remain
  visible; they are never interpolated.
- Exact repeated input returns the same event identity and bytes where
  practical. Conflicting reuse fails closed.
- Every persisted event states `RESEARCH_ONLY` and `execution_authority=False`.

## Acceptance Criteria

- [x] Opportunity/setup IDs exactly match MONITOR helpers.
- [x] Synthetic tests cover impulse, opening breakout, continuation breakout,
  missed entry, failed breakout, pullback, reclaim, exhaustion, and gaps.
- [x] No-lookahead tests prove trigger windows exclude the current bar.
- [x] Duplicate rerun is idempotent; conflicting IDs and rehashed tampering fail.
- [x] Store replacement failure preserves the prior ledger.
- [x] Input observations and canonical source files are never mutated.
- [x] No network, broker, scoring, readiness, plan, selection, or runtime import
  gives the module authority.
- [x] Compile, focused, bounded, and full Python verification pass.
- [x] Protected-path and secret scans pass.
- [x] Canonical master, installed manifest, service, scheduled jobs, provider,
  account, and Paper/Shadow state remain unchanged.

## Classification

`IMPLEMENTED_PENDING_INTEGRATION` on
`codex/ARGUS-BREAKOUT-001-sequential-research`. Integration must preserve the
MONITOR dependency and wait for the runtime pin; no runtime activation is part
of BREAKOUT-001.
