# ARGUS-SHADOW-003 Goal Charter - Sample Readiness Gate

## Goal

Make the prospective Shadow evidence format ready for a future official sample by
freezing explicit sample, strategy/configuration, fill-model, and evidence-schema
versions on every newly created Shadow Trade and by exposing a deterministic audit
that refuses sample start when any required proof is missing.

## Operator Outcome

Steven can see whether the Shadow system is technically ready to collect official
trade 1, exactly why it is blocked, and which immutable configuration will govern the
sample. Passing this engineering gate will not start a sample or authorize broker
access.

## Scope

- Add an immutable Shadow sample-definition model.
- Record `SampleVersion`, strategy/configuration fingerprint, fill-model version, and
  evidence-schema version on every newly created Shadow Trade.
- Derive fingerprints deterministically from canonical configuration rather than
  accepting an unverified display label.
- Preserve existing/unversioned state without backfilling or rewriting it.
- Exclude unversioned, malformed, or fingerprint-mismatched records from sample
  eligibility.
- Add a deterministic sample-readiness audit with explicit pass/fail findings.
- Include sample metadata and gate state in the existing read-only Shadow review
  projection.
- Add focused serialization, restart, mutation, eligibility, and isolation tests.

## Non-Goals

- Do not start the official sample or create official trade 1.
- Do not backfill, delete, or rewrite existing Shadow evidence.
- Do not change scoring, readiness, Risk Governor semantics, TradePlan calculations,
  FakeBroker fills/exits, P&L/R/MFE/MAE, alert thresholds, replay identity, or provider
  behavior.
- Do not add a database migration, broker adapter, Schwab request, credential, OAuth,
  account access, Paper/Live control, or transmitting method.
- Do not merge R026 or change its branch history.

## Protected Areas

Core scoring, trade readiness, replay identity, historical capture selection, database
schema/migrations, broker/order execution semantics, alert thresholds, secrets/API
keys/env config, production configuration, and real execution authority remain
unchanged.

## Acceptance Criteria

- [x] Every newly created Shadow Trade stores all four required sample metadata fields.
- [x] Metadata survives atomic JSON serialization and restart unchanged.
- [x] The strategy/configuration fingerprint is reproducible from canonical frozen
      inputs.
- [x] The fill-model version identifies the existing FakeBroker execution model
      without changing that model.
- [x] Existing/unversioned records are preserved and excluded rather than backfilled.
- [x] Missing, malformed, or mismatched metadata fails sample eligibility and the
      readiness audit with an explicit reason.
- [x] A deterministic readiness result reports `PASS` only when all configured
      engineering gates are proven.
- [x] Passing the readiness audit has no method or side effect that starts a sample,
      creates a trade, accesses a broker, or transmits an order.
- [x] The read-only review projection exposes metadata and gate status honestly.
- [x] Focused and bounded adjacent tests, Python compileall, all .NET tests, and the
      Release build pass.
- [x] Protected-path and source-mutation review pass.

## Evidence Depth / Hard Chew

- Run Python compileall.
- Add focused tests for deterministic fingerprints, new-record metadata, legacy state,
  malformed metadata, serialization/restart, audit failure/pass, no source mutation,
  and no automatic sample start.
- Run bounded Shadow, host, simulation, planning, autonomy, Schwab-safety, and WPF
  contract/presentation tests.
- Run the complete .NET suite and zero-warning Release build.
- Review the full diff for scoring/readiness/replay/alert changes, FakeBroker semantic
  drift, schemas/migrations, Schwab/network/credentials, transmitting verbs, generated
  state, and accidental sample collection.
- Perform a second-pass diff/test/operator-language review and narrow fix pass.
- Update the Roadmap with branch, commit, tests, merge/push state, remaining gates, and
  exact next action.

## Smallest Safe Implementation Slice

One immutable metadata model, one deterministic readiness audit, extensions to the
existing Shadow record/projection, and focused tests. No new execution command or UI
mutation control.

## Open CEO Decisions

- None required for this engineering gate.
- Starting the official sample remains a separate checkpoint after this branch is
  accepted, integrated, and all remaining gate findings pass.

## Goal Steward Review

- [x] Goal and operator outcome are concrete.
- [x] Scope and non-goals are explicit.
- [x] Protected areas and execution-authority limits are named.
- [x] Acceptance criteria prove immutable evidence and fail-closed behavior.
- [x] Evidence depth satisfies the Hard Chew Protocol.
