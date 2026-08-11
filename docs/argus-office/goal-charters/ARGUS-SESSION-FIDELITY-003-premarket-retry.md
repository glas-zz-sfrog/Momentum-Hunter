# ARGUS-SESSION-FIDELITY-003 Goal Charter - Premarket Retry

## Goal

Collect fresh prospective Alpaca-only evidence for the three premarket session
checkpoints whose original Alpaca children failed due to a frozen-module loader
defect, without changing or reusing the failed observations.

## Operator Outcome

Momentum Hunter receives valid provider-by-session evidence for early
premarket, the pre-Schwab boundary, and Schwab premarket. A task failure remains
visible and cannot be mistaken for provider behavior.

## Scope

- Fix A/B/C at 03:05, 05:55, and 06:05 Central on August 12, 2026.
- Observe only Alpaca market data for SPY, QQQ, and NVDA for five minutes.
- Pin the retry source, repaired adapter, PowerShell runner, and frozen Alpaca
  probe by clean commit and SHA-256.
- Persist write-once, fingerprinted, sanitized evidence outside the repository.
- Make an exact scheduler retry reuse complete evidence without another
  provider request.
- Preserve the failed SESSION-FIDELITY-001 evidence unchanged.

## Non-Goals

- No account values, positions, previews, or orders.
- No Alpaca Paper order, Shadow decision, candidate selection, or execution
  authority.
- No production candle persistence, service change, canonical scheduler change,
  or merge into master.
- No use of historical Schwab evidence as a contemporaneous Alpaca comparison.

## Protected Areas

The task reads the existing encrypted Canary credential slot under Steven's
logged-in Windows identity and makes GET-only market-data requests. It cannot
display or persist credentials. Any account/order call, live endpoint, broader
symbol scope, source identity mismatch, or unsafe existing output fails closed.

## Acceptance Criteria

- [x] The original failed A-C records remain immutable.
- [x] The retry matrix and Central-time windows are fixed prospectively.
- [x] Every source identity is checked before installation and at runtime.
- [x] Existing exact evidence is verified without provider replay.
- [x] Wrong, tampered, or unsafe existing evidence fails closed.
- [x] Account, position, preview, order, live endpoint, and transmission routes
  are absent.
- [x] The service, opening/Paper jobs, Shadow, and production stores are not
  changed.
- [x] Focused, adjacent, and full regression suites pass.

## Evidence Depth

- Python compileall: pass.
- Focused SESSION-FIDELITY tests: 15/15 pass.
- Adjacent market-data boundary tests: 67/67 pass.
- Full Python discovery: 1,329/1,329 pass in 217.967 seconds.
- PowerShell parser checks, `git diff --check`, protected-path review, and secret/
  capability scans: required before commit.
- External launcher receipt and exported task XML: required after the exact
  branch commit and before the branch is frozen.

## Status

`IMPLEMENTED_PENDING_FROZEN_INSTALL`. After installation, the write-once
external receipt is operational truth; do not amend the pinned branch before
the observations run.
