# ARGUS-BROKER-ALPACA-003 Goal Charter - Paper Lifecycle Proof

## Goal

Build a bounded, resumable Alpaca Paper lifecycle harness that can directly
adjudicate fractional market entry, protective orders, replacement, partial
fills, position recovery, and exact liquidation without connecting Alpaca to
Momentum Hunter runtime or exposing a live endpoint.

## Operator Outcome

During a safe regular-market window, Steven can run one isolated `$1.00`
Canary Paper proof. The proof either finishes flat with sanitized, write-once
provider evidence or fails closed while preserving enough identity to resume
without blindly submitting a duplicate command.

## Scope

- Lock the adapter to the exact Alpaca Paper host and Canary credential lane.
- Freeze one SPY lifecycle plan and every client-order ID before mutation.
- Submit at most `$1.00` for the initial fractional market entry.
- Exercise distant stop, stop-limit, and profit-target orders without treating
  them as production protection.
- Exercise price-only replacement and cancellation.
- Recognize partial fills and use at most three frozen exact-quantity exit IDs.
- Recover submissions and replacements by client-order ID after interruption.
- Preserve allowlisted provider receipts and normalized lifecycle evidence.
- Keep every output outside the repository and free of account identity and
  credential values.

## Non-Goals

- Do not connect Alpaca to Engine Host, Shadow, service, scheduler, WPF,
  Risk Governor, allocation, or production execution.
- Do not authorize or contact the Alpaca live host.
- Do not begin a Paper strategy sample or promote a capability from synthetic
  evidence.
- Do not prove bracket, OCO, OTO/OTOCO, streaming, extended-hours, or
  broker-resident linked protection.
- Do not change scoring, readiness, alerts, RVOL, TradePlan semantics,
  account policy, schemas, packages, credentials, raw evidence, or Monday's
  installed runtime.

## Acceptance Criteria

- [x] Plan identity and command IDs are write-once and tamper-evident.
- [x] Closed-market execution stops before provider access or local output.
- [x] Submission and replacement are idempotent across ambiguous responses.
- [x] Existing owned entry/position state can resume without a second entry.
- [x] Unexpected positions, foreign orders, and orphan protective orders stop.
- [x] Partial entry and exit fills are preserved and bounded.
- [x] Stops, stop-limits, target replacement, and cancellation are modeled.
- [x] Exact fractional liquidation uses finite frozen attempts.
- [x] Failure evidence is write-once and cleanup is best-effort/fail-closed.
- [x] Provider receipts omit account identity and credential-shaped values.
- [x] No production runtime imports the adapter or lifecycle harness.
- [x] One direct regular-market Alpaca Paper lifecycle finishes and is
  independently adjudicated.

## Evidence Depth

- Python compileall: pass.
- Adapter tests: 32/32 pass.
- Lifecycle tests: 21/21 pass.
- Adjacent onboarding/allocation/TradePlan/simulation tests: 151/151 pass.
- Full Python discovery: 1,391/1,391 pass in 231.451 seconds after direct proof.
- `git diff --check`: pass.
- Credential-shaped-value scan: zero hits.
- Runtime import and protected-path scans: zero hits.
- Canonical `master` remains clean and synchronized at `1d0ca95`; the installed
  service remains Running/Automatic with 25 opening jobs and zero Shadow jobs.

## Status

`DIRECT_PROOF_COMPLETE_PENDING_INTEGRATION` on
`codex/ARGUS-BROKER-ALPACA-003-paper-lifecycle-proof`. Direct proof
`alpaca-paper-lifecycle-78aaade645ee4fd697a338d3` is
`ALPACA_PAPER_LIFECYCLE_PROVEN`, ends flat with zero open orders, and contains
no credential or account identity. Runtime integration remains out of scope.
