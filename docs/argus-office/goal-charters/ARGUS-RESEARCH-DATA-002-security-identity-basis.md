# ARGUS-RESEARCH-DATA-002 Goal Charter

## Goal

Define the minimum provider-neutral security-identity, symbol-history,
corporate-action, price-basis, transformation-lineage, and survivorship
contracts required before Momentum Hunter makes historical technical or
statistical claims.

## Operator Value

Historical research must not interpret a ticker rename as a new company, a
reused ticker as the same company, or a split as a market crash or rally. This
task gives future research engines a deterministic way to admit safe evidence
or abstain without changing production strategy behavior.

## Scope

- Resolve observations by durable security identity and point-in-time symbol
  aliases without rewriting the historical symbol.
- Preserve active, renamed, acquired, inactive, delisted, and unknown states.
- Model verified forward split, reverse split, and symbol-change events;
  preserve extension-only types without inventing transformation semantics.
- Distinguish raw-provider, split-adjusted, total-return-adjusted, and unknown
  price bases.
- Derive split-adjusted OHLCV with immutable raw/transformed lineage and
  mathematically consistent price and volume factors.
- Admit or reject research evidence based on identity, action, basis, lineage,
  and survivorship status.
- Apply the contract to the preserved RESEARCH-DATA-001 inventory without
  repairing any source file or selecting another provider.

## Non-Goals

- No split signal, score, candidate, TradePlan, or execution behavior.
- No production collection, candle-store migration, historical rewrite, or
  provider acquisition.
- No SETUP-002, scheduler, service, credentials, UI, broker, Paper, Shadow,
  scoring, ranking, Risk Governor, or allocation change.
- No complete reconstruction of delisted securities or point-in-time
  membership unsupported by current evidence.

## Frozen Semantics

- A split ratio is represented as post-action shares per pre-action share.
- Historical pre-action price factor is `denominator / numerator`.
- Historical pre-action volume factor is `numerator / denominator`.
- Raw provider evidence is immutable and remains authoritative for what the
  provider returned.
- An adjusted value is a deterministic derivation with explicit action IDs,
  factors, algorithm version, original OHLCV, transformed OHLCV, and hashes.
- `SAME_SYMBOL` does not imply `SAME_SECURITY`; `DIFFERENT_SYMBOL` does not
  imply `DIFFERENT_SECURITY`.
- Unsupported action types never acquire numeric transformation semantics.
- Current Schwab and research-cache adjustment semantics remain `UNKNOWN`
  unless exact evidence proves otherwise.

## Acceptance Evidence

- Synthetic point-in-time identity tests cover ticker changes, ticker reuse,
  overlapping aliases, missing dates, delisted history, duplicate JSON keys,
  and tampering.
- Split tests cover 2:1, 3:2, 10:1, and 1:10 with price and volume consistency.
- Negative tests cover malformed ratios, wrong identities, duplicate or
  out-of-range actions, forged lineage, and unsupported actions.
- Technical diagnostics prove unnormalized actions contaminate returns, ATR,
  moving averages, gaps, levels, patterns, MFE/MAE, and analog similarity.
- The actual DATA-001 compatibility report remains fail-closed and
  hash-addressed.
- Full Hard Chew passes without changing the canonical checkout, installed
  runtime, automation manifest, or August 17 jobs.

## Classification

`IMPLEMENTED_PENDING_MERGE`
