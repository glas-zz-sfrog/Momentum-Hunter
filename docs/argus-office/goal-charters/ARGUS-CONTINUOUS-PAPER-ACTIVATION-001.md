# ARGUS-CONTINUOUS-PAPER-ACTIVATION-001

## Goal Statement

Connect genuine prospective Continuous Runtime TradePlans to one bounded Alpaca Paper canary through an independent execution supervisor, without giving the research runtime broker capability or creating any path to live money.

## Operator Outcome

The first strategy-valid continuous TradePlan may create at most one Alpaca Paper entry lifecycle under the $100 Canary policy. Research must keep hunting while Paper execution is pending or active, and every broker action must remain Paper-only, idempotent, protected, restart-safe, and auditable.

## In Scope

- An immutable Continuous Runtime TradePlan admission record written through the dedicated writer.
- A separate Paper-only process that consumes verified admissions and reuses A004/PAPER-005 execution.
- Exact Paper-host and DPAPI Canary credential boundaries.
- The resolved $100/$2/$95/$5/$2/$4/one-position/30-second policy.
- Exactly-once admission and deterministic Alpaca `client_order_id` behavior.
- Read-only Paper account/order/position preflight before arming.
- One-entry canary locking, lifecycle supervision, protection, recovery, and evidence.
- Offline failure, restart, FakeBroker whole-day, and full-suite proof.
- Staged canonical deployment only after the independent overnight experiment is terminal.

## Out Of Scope

- Alpaca Live, Schwab orders, live money, Shadow, transfers, or account changes.
- Strategy, scoring, setup, spread, extension, R/R, Risk Governor, or session-rule changes.
- Synthetic production TradePlans or retrospective Paper trades.
- Ongoing multi-entry Continuous Paper after the first lifecycle.
- Repairing or inventing an upstream continuous lifecycle/successor producer.

## Protected Areas

Broker/order behavior, credentials, production services, production configuration, and runtime evidence are protected. The directive authorizes only one Alpaca Paper entry lifecycle after every gate passes. Stop for a non-Paper host, unavailable credential store, unknown Paper order/position, contradictory account scope, live capability, unsafe Git state, failed Hard Chew gate, or missing canonical plan-freshness semantics.

## Acceptance Criteria

- Research Runtime retains no credential, account, position, or order capability.
- Only verified write-once prospective plan admissions can reach the Paper supervisor.
- The Paper supervisor is independently restartable and cannot stall research.
- Paper host is exactly `https://paper-api.alpaca.markets`; live host fails before credentialed transmission.
- Pre-arm account/order/position reads prove a clean Paper environment.
- At most one new Paper entry intent can be transmitted, with deterministic broker identity.
- Actual fill/position quantity controls risk reconciliation and protection.
- Offline matrix and whole-day proof pass, followed by compileall, full suite, scans, canonicalization, staged deployment, and installed read-only proof.
- If no genuine plan appears, the honest terminal task status is armed pending a qualifying plan.

## Evidence Required

- Starting Git, installed service, capability, and overnight-campaign identities.
- Reuse inventory and exact source lineage.
- Focused, adjacent, full-suite, secret, credential, host, capability, and protected-path results.
- Staged installation and installed capability report.
- Sanitized Paper preflight and activation evidence.
- Final review bundle or explicit armed-pending evidence.

## Smallest Safe Slice

Emit one broker-neutral, immutable plan admission from a real composed plan; consume it from a separate Paper-only supervisor that reuses the canonical Alpaca Paper engineering engine. Do not add another execution engine and do not alter plan production.

## Known Entry Gap

At task start, the installed Continuous Runtime has produced zero TradePlans because its production composition source has not supplied lifecycle/successor evidence. The bridge may be implemented and proven offline, but production arming must not be represented as likely to trade until a genuine producer exists. This task does not authorize inventing that producer.

## Goal Steward Review

- [x] Goal and one-entry consequence are explicit.
- [x] Research/execution separation is explicit.
- [x] Protected areas and stop conditions are explicit.
- [x] No-trade and missing-producer truth remain distinguishable.
- [x] Completion requires proof, not configuration labels.

