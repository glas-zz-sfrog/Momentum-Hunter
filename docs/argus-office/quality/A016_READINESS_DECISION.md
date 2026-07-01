# A016 Readiness Decision

Date: 2026-07-01

## Classification

`READY_FOR_A016_WITH_CAUTIONS`

## Decision

A016 broker research may proceed because it is docs-only broker/API feasibility work. It may compare APIs, paper modes, authentication models, order lifecycle endpoints, audit evidence, limits, and safety risks. It may not implement broker code, create adapters, add credentials, create API keys, install dependencies, or wire paper/live order behavior.

## Why A016 Is Allowed

- Current Argus Machine work defines useful vocabulary: `BrokerAdapter`, `FakeBrokerAdapter`, adapter metadata, transmit lock, credential status, Risk Governor, Execution Ledger, Simulation Lab Engine, and Execution Auditor.
- Paper/live UI controls are locked.
- There is no paper broker implementation and no live broker implementation in the autonomy path.
- A016 research can improve future task design without touching runtime behavior.

## Broker Research Constraints

A016 must:

- Remain docs-only.
- Avoid credentials, API keys, secrets, `.env`, or account setup.
- Avoid installing broker SDKs or dependencies.
- Avoid paper/live order submission code.
- Avoid production config changes.
- Compare brokers against Argus evidence needs: account reads, paper mode, order preview, submit, cancel, order status, positions, fills, rate limits, auth, audit trail, sandbox quality, and failure behavior.

## A017 Blockers

A017 PaperBrokerAdapter skeleton is blocked until:

- The simulation engine has a FakeBroker-only metadata guard.
- Tests prove non-Fake or transmit-capable adapters are rejected before method calls.
- Paper adapter skeleton requirements are docs-approved.
- Paper mode remains not configured and non-transmitting by default.

## A018 Blockers

A018 first paper order pilot is blocked until:

- Execution Auditor is a hard gate with chronology and preview-before-submit checks.
- Ledger validation/persistence is specified.
- Risk Governor is re-run or freshness-checked at action time.
- Manual overrides require end-to-end risk re-check.
- Paper credentials policy is approved and no secrets are stored in repo.
- Steven approves broker, account, order type, order size, failure behavior, and rollback process.

## Explicit No-Code Statement

A016 may research brokers. A016 may not implement broker code.
