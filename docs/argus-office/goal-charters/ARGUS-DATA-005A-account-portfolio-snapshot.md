# ARGUS-DATA-005A Goal Charter - Fresh Account And Portfolio Evidence

## Goal

Supply DATA-005 with a fresh, read-only, exact-account-bound allocation context
without activating allocation, changing policy, or adding order capability.

## Operator Outcome

Momentum Hunter can obtain current cash/buying-power evidence and combine it
with current Official Shadow commitments before sizing a future simulated
position. A changed account, unexpected brokerage position, malformed balance,
or invalid Shadow commitment stops the decision and is visible as an anomaly.

## Scope

- Revalidate exactly one bound account ending `2573` with type
  `INDIVIDUAL_CASH` before each snapshot.
- Use one exact-host Schwab `GET` for current balances and positions.
- Preserve provider and local receipt timestamps without retaining the full
  account number, encrypted hash, token, or balance in proof output.
- Derive committed notional, committed open risk, open position count, and
  realized current-session P&L from read-only Official Shadow state.
- Capture a new context for every allocation request.
- Include this source in the Engine Host runtime identity.

## Non-Goals

- Do not choose or activate Steven's numeric allocation policy.
- Do not wire the source into selection, simulation, Shadow, the service,
  scheduler, Engine Host commands, or WPF.
- Do not add an order endpoint, transmitting method, account mutation, or
  provider write.
- Do not change DATA-004 setup-aware same-session TradePlan semantics.
- Do not change scoring, rank, alerts, RVOL, capture, schemas, packages,
  credentials, raw evidence, or historical reports.

## Acceptance Criteria

- [x] The source requests only the bound account and includes positions.
- [x] Account count, ending, type, and encrypted binding are revalidated.
- [x] Provider and receipt clocks remain distinct and fail closed.
- [x] Unexpected brokerage positions surface as a brokerage anomaly.
- [x] Shadow commitments require valid frozen DATA-005 allocation evidence.
- [x] Partial fills include the filled position and remaining working order.
- [x] Current-session realized P&L uses Central trading-date semantics.
- [x] Repeated allocation requests capture fresh context each time.
- [x] Source evidence is not mutated.
- [x] No order or transmission method exists.
- [x] The source remains inactive until the numeric policy is explicit.

## Evidence Depth

- Python compileall: pass.
- Focused and runtime-identity tests: 73/73 pass.
- Adjacent account, Schwab, simulation, Shadow, and selection tests: 210/210
  pass.
- Full Python discovery: 1,314/1,314 pass in 265.161 seconds.
- Nonpersisting live proof: one expected cash account, zero brokerage
  positions, zero Shadow commitments, transmission `UNAVAILABLE`.
- `git diff --check`, secret scan, capability scan, and protected-path review:
  required before release.

## Status

`COMPLETE` on canonical `master` through `dff993c`, with backup, exact-head
opening-job repin, and installed-runtime refresh verified. Activation remains
blocked on Steven's explicit numeric policy and is not part of this task.
