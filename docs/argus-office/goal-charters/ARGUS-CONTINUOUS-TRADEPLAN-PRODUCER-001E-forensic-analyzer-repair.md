# Goal Charter: PRODUCER-001E Forensic Analyzer Repair

## Goal

Repair the three forensic-tooling defects established by the independent 001D
adjudication: completed-bar identity reconstruction, symbol-specific TradePlan
accounting, and approved-environment Hard Chew invocation.

## Scope

- Reuse the production completed-bar identity path when reconciling frozen
  canonical candle versions to persisted material events.
- Resolve each Producer result to its exact composition member by symbol and
  count unique TradePlan identities separately from persisted occurrences.
- Provide an explicit, fingerprint-bound way to run an isolated worktree with
  the approved external Python environment.
- Replay the immutable 001D provider evidence and reproduce the independently
  adjudicated result.
- Run Hard Chew, package a sanitized self-contained second-eye ZIP, commit, and
  push the task branch without merging it.

## Non-Goals

- No Product runtime, provider, discovery, backfill, readiness, lifecycle,
  setup, composition, TradePlan-production, restart, strategy, scoring, risk,
  admission, account, Paper, Shadow, broker, order, service, scheduler, or UI
  behavior change.
- No repair of unknown instrument classification.
- No provider contact or new live canary.
- No merge, deployment, activation, or production evidence mutation.

## Acceptance Evidence

- Frozen 001D replay reports 259 exact completed-bar matches, zero unmatched,
  zero premature, and zero prospective-floor violations.
- Frozen 001D replay reports four unique natural TradePlans for CRM, NVDA, and
  BMNR without fabricating a plan for MSTR.
- Runtime/analyzer identity parity, timezone equivalence, strict mismatch,
  symbol matching, duplicate-plan, no-plan, and malformed-input tests pass.
- The approved external interpreter is fingerprinted and runs full discovery
  against the isolated worktree without requiring a local `.venv`; an
  unapproved fingerprint fails closed.
- Product runtime source hashes match the 001D parent before and after.
- The second-eye ZIP passes manifest, sanitation, pre-ZIP, and extracted-ZIP
  verification.

## Goal Steward Review

- [x] The repair boundary is forensic/tooling-only and measurable.
- [x] Immutable provider evidence is replayed without contact or mutation.
- [x] Product/runtime and execution-authority boundaries are explicit.
- [x] Completion requires broad proof and an independent review package.
