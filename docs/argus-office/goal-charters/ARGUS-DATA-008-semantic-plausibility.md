# ARGUS-DATA-008 Goal Charter - Semantic Plausibility

## Goal

Add a deterministic fail-closed boundary between structurally valid Finviz rows
and strategy evidence so economically implausible values cannot quietly reach
candidate filtering or scoring.

## Operator Outcome

Momentum Hunter distinguishes a legitimate zero-candidate scan from a provider
data-contract failure, records deterministic diagnostics, and can compare a
provider row with explicitly supplied time-aligned Schwab/candle evidence
without substituting, averaging, or mutating either source.

## Scope

- Validate intrinsic price, change, volume, relative-volume, market-cap, float,
  and ATR plausibility after structural parsing and before filtering.
- Account for every scanner rejection reason so a fully rejected scan remains
  valid when the criteria explain it.
- Detect row-count collapse, duplicate symbols, repeated economic signatures,
  extreme distribution shifts, timestamp/session contradictions, severe
  authoritative price disagreement, and comparable cumulative-volume conflicts.
- Preserve schema, policy, issue, count, rejection, and fingerprint evidence.
- Treat semantic failures as deterministic and nonretryable.

## Non-Goals

- No scoring, scanner threshold, TradePlan, readiness, Shadow, Paper, broker,
  order, UI, schema, credential, scheduler, or installed-runtime change.
- No provider call, provider voting, fallback substitution, or automatic repair.
- No assumption that two volume fields are comparable; the caller must assert
  comparability explicitly.
- No merge or activation before the August 14 operational evidence is preserved.

## Acceptance Criteria

- [x] Finviz semantic evaluation runs before candidate filtering and scoring.
- [x] Intrinsic impossibilities fail closed with deterministic diagnostics.
- [x] Legitimate criteria-driven zero-candidate scans remain valid.
- [x] Schwab reference comparison requires explicit authority, freshness, and
  matching session context.
- [x] Cumulative-volume comparison requires explicit comparability.
- [x] No candidate/source mutation or network/broker dependency exists.
- [x] Compileall, focused, bounded regression, and full discovery pass.
- [x] Canonical checkout, service, manifest, and August 14 jobs remain unchanged.

## Status

`IMPLEMENTED_PENDING_INTEGRATION_AFTER_AUGUST_14_EVIDENCE`. Intrinsic Finviz
checks are wired on the feature branch. Contextual Schwab/candle and historical
distribution checks are implemented but require an explicitly supplied,
time-aligned evidence context; canonical production does not yet supply one.
