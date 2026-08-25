# Goal Charter: ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001

## User-Visible Goal

Momentum Hunter can encounter a symbol at any supported same-session time, load
bounded authoritative history, combine it with completed current evidence, and
produce or reevaluate one immutable DATA-004 TradePlan when an existing
prospective setup contract supplies defensible levels.

## Operator Pain

The current Continuous runtime can discover symbols and assess candle readiness,
but it retains the complete composition packet only in memory and supplies no
lifecycle/setup input to the composer. A newly encountered symbol therefore
cannot produce a durable prospective TradePlan, and the universal five-bar
composition default can be mistaken for a requirement to observe five new bars.

## Scope

- Add one provider-neutral Continuous TradePlan producer over the existing hot
  universe, canonical candle, RVOL, lifecycle, composition, and DATA-004
  contracts.
- Bind historical context, current evidence, universe origin, instrument
  admission, material trigger, setup/predecessor, configuration, and producer
  identity into each immutable producer record.
- Reuse bounded R032C backfill admission and the existing minute/Daily stores.
- Persist complete producer evidence through the existing dedicated writer while
  retaining only bounded restart/idempotency state under the runtime-state root.
- Use one completed canonical current bar for Continuous readiness while leaving
  the opening-specific 09:30-09:34 contract unchanged.
- Accept setup/lifecycle evidence only through existing contracts; do not infer
  setup levels inside the producer.
- Audit instrument admission and fail closed when authoritative classification is
  missing, unknown, leveraged, inverse, or ETN.

## Non-Goals

- No new setup detector, strategy threshold, entry, stop, target, rank, risk, or
  allocation semantics.
- No second candle store, provider path, TradePlan engine, lifecycle model, or
  evidence writer.
- No Paper, Shadow, broker, account, position, order, or WPF activation.
- No multi-resolution retention horizon or destructive compaction policy.
- No opening-runtime promotion unless dependency-closure evidence requires it.

## Protected Areas

- Continuous readiness and runtime orchestration.
- Immutable TradePlan and candidate-lifecycle identity.
- Canonical candle/history persistence.
- Dedicated writer payloads and restart behavior.

## Acceptance Criteria

1. A cold symbol requests bounded backfill immediately, current evidence can be
   acquired independently, and evaluation proceeds after canonical context is
   ready.
2. A symbol discovered after the open can be evaluated from backfilled history
   plus one latest completed canonical bar without waiting for five newly
   observed bars.
3. Missing, stale, gapped, conflicting, or tampered context fails closed.
4. Material evidence changes create deterministic new evidence; an unchanged
   material packet is idempotent before and after restart.
5. A missed plan remains immutable and a later continuation, pullback, or reclaim
   carries a distinct setup, predecessor, cutoff, and TradePlan identity.
6. Backfilled, persisted, and newly completed canonical bars compose into one
   duplicate-free chronology; provisional bars do not enter canonical context.
7. Instrument classification is authoritative or explicitly blocked; no ticker
   or product-name inference is used.
8. The branch-only Continuous Paper admission contract consumes a valid producer
   cycle unchanged, but no Paper capability is activated.
9. Focused, adjacent, full discovery, compile, protected-path, secret/capability,
   historical-nonmutation, opening-runtime, and installed-state checks pass.

## Required Evidence

- Focused synthetic/replay tests for cold start, arbitrary startup, backfill,
  chronology, stale/tampered failures, reevaluation, successor identity, restart,
  duplicate conflict, and safety.
- Compatibility proof against the branch-only Continuous Paper contract.
- Identity-003 opening dependency-closure comparison.
- Read-only hashes/status for installed services, scheduler/manifest, and existing
  historical evidence before and after verification.

## Completion Rule

Done means the bounded producer is implemented and proven on a task branch,
Hard Chew is green, governance reflects actual Git/integration state, and no
execution authority or installed runtime change occurred.
