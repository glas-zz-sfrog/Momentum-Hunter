# Simulation Foundation Hardening Plan

Date: 2026-07-01

## Decision

A016 broker research may proceed as docs-only work. A017/A018 must wait for simulation foundation hardening.

## Follow-Up Tasks

### ARGUS-QUALITY-002 - Harden Simulation Safety Tests

Scope: tests only, no behavior changes unless a defect is exposed and separately approved.

Acceptance:

- Test that `SimulationLabEngine` refuses a non-FakeBroker adapter before any adapter method is called.
- Test that a transmit-capable adapter cannot be used in Simulation Lab.
- Test auditor failure when submit evidence exists without preview evidence.
- Test auditor failure when event chronology is invalid.
- Test stale/corrupt report source behavior for Top 5 candidate loading.
- Test UI locked/no-op paths beyond label existence.

### ARGUS-A013B - FakeBroker-Only Simulation Engine Guard

Scope: autonomy behavior hardening, no paper/live broker code.

Acceptance:

- Simulation mode checks adapter metadata before preview or submit.
- Allowed adapter must be `FakeBrokerAdapter`, `Simulation Lab`, `order_transmit_allowed=False`, and `credential_status="not required"`.
- Failure records a blocked ledger event without calling adapter methods.
- Tests prove the guard catches fake noncompliant adapters.

### ARGUS-A010B - Machine Log / Ledger Hardening

Scope: ledger and log evidence quality.

Acceptance:

- Order-like ledger events require non-empty mode, ticker, TradePlan ID, RiskResult ID, adapter, approval state, result, actor/source, and action.
- Ledger rendering distinguishes blocked, previewed, submitted, rejected, filled, and audited events.
- Duplicate or missing event IDs are rejected or visibly blocked before advancement.

### ARGUS-A014B - Simulation Cockpit Hardening

Scope: UI state/rendering extraction and proof.

Acceptance:

- Extract cockpit table population and auditor display helpers away from broad direct `window` mutation.
- Preserve locked paper/live labels.
- Add screenshot sanity proof for dense cockpit layout.
- Add tests for empty/fewer-than-five/corrupt report states and disabled controls.

### ARGUS-A015B - Auditor-As-Gate Hardening

Scope: auditor gate semantics.

Acceptance:

- Auditor requires risk event before preview, preview before final submit/block, and consistent timestamps.
- Auditor requires event_type/requested_action consistency.
- Auditor validates adapter metadata, not only adapter name text.
- Paper advancement stays `BLOCK` unless every required simulation evidence item passes.

### ARGUS-A016 - Broker Research Matrix

Scope: docs-only research.

Acceptance:

- Compare broker APIs, paper mode, auth, order preview/submit/cancel/status, account/position reads, rate limits, audit evidence, and failure modes.
- Do not add broker code, dependencies, credentials, API keys, or runtime config.
- Convert research into A017/A018 safety gates.

## Sequence

Recommended order:

1. `ARGUS-QUALITY-002`
2. `ARGUS-A013B`
3. `ARGUS-A015B`
4. `ARGUS-A014B`
5. `ARGUS-A016`

A016 can run before some hardening only if it remains strictly docs-only and does not prepare credentials or code.
