# ARGUS-EXEC-QUALITY-001 Architecture

## Boundary

`momentum_hunter.execution_quality_specialist` is a pure, provider-neutral
research module. A caller supplies already-persisted or already-validated
evidence. The module has no provider client, account method, broker adapter,
order method, writer, service hook, scheduler hook, Engine Host hook, or UI
consumer.

```text
caller-supplied canonical quote/candle evidence
                +
optional immutable DATA-004 / DATA-005B / capability evidence
                |
                v
PRE_DECISION_EXECUTION_QUALITY
                |
                v
common SpecialistOpinion
RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE

later confirmed Paper fill/position evidence
                |
                v
OBSERVED_PROVIDER_EXECUTION_RESULT
separate immutable attachment; original opinion unchanged
```

REGIME-002 is an independent sibling. EXEC-QUALITY-001 stacks directly on the
common Specialist Contract and imports no REGIME implementation.

## V1 Policy

The frozen specialist and policy identities are:

- Specialist: `EXECUTION_QUALITY`
- Specialist version: `execution-quality-research-v1`
- Policy: `execution-quality-research-policy-v1`
- Research identity: `execution-quality-research-v1`
- Full classification: regular session only
- Quote age ceiling: 30 seconds, unchanged from production
- Quote observations: minimum 3, maximum 20
- Completed canonical minute bars: minimum 31, maximum 90
- Sensitivity bands: 0, 5, 10, and 25 basis points
- Threshold semantics: `RESEARCH_HEURISTIC`

Thresholds produce research labels, not candidate points, risk decisions,
quantity changes, order decisions, or probabilities.

## Inputs

Each quote wrapper preserves symbol, bid, ask, provider component timestamps,
local receipt time, source/session identity, real-time and market state, and
optional displayed-size authority. The effective quote time is the oldest
provider component time. Missing/zero/nonfinite/crossed prices, future or
contradictory chronology, wrong identity, duplicates, and tampering fail
closed. Stale but structurally valid evidence abstains.

Each candle projection preserves exact symbol/time/OHLCV/source/state/session
identity. Only `RECONCILED`, `CORRECTED`, or `HISTORY_ONLY_GAP_FILL` terminal
states are accepted. Gaps, duplicates, future bars, malformed OHLCV, source
mixing, and tampering fail closed. Missing volume or insufficient depth
abstains.

The specialist validates an optional DATA-004 TradePlan and may reference a
matching DATA-005B allocation decision for mathematical dollar-risk
sensitivity. It never changes plan levels or quantity. `finalAuthorizedQuantity`
is never treated as a fill.

An optional provider-neutral capability registry may be referenced by
fingerprint. No capability is inferred from a provider name. Because the
registry has no native as-of timestamp, that limitation is explicit. Displayed
size defaults to `UNSUPPORTED`; no Level 2 depth is fabricated.

## Multidimensional Output

- Liquidity: `LIQUID`, `ADEQUATE`, `THIN`, `VERY_THIN`, `UNKNOWN`
- Spread: `TIGHT`, `NORMAL`, `WIDE`, `EXTREME`, `UNKNOWN`
- Quote stability: `STABLE`, `MODERATELY_UNSTABLE`, `UNSTABLE`,
  `DISLOCATED`, `UNKNOWN`
- Price-impact risk: `LOW`, `MODERATE`, `HIGH`, `UNKNOWN`
- Fill risk: `LOW`, `MODERATE`, `HIGH`, `UNKNOWN`
- Data quality: `COMPLETE`, `PARTIAL`, `DATA_UNSAFE`

There is no universal execution score. Raw evidence includes spread in several
units, quote movement/update behavior, midpoint micro-volatility, volume and
dollar turnover, price progress, and deterministic TradePlan sensitivity.

## Opinion And Abstention

The common opinion is always non-directional and uses
`EXECUTION_CONDITIONS_SUPPORT`, `ACCEPTABLE`, `FRAGILE`, `POOR`,
`DISLOCATED`, or explicit `NO_OPINION`. `SUPPORT` is not permission to trade.
Confidence is an uncalibrated evidence-completeness heuristic, never fill
probability.

Premarket and after-hours v1 evidence may preserve safe raw spread facts, then
abstains `UNSUPPORTED_SESSION`. A lone quote preserves spread but stability
remains `UNKNOWN` and the packet abstains with machine reason
`QUOTE_SEQUENCE_UNAVAILABLE`.

## Later Execution Evidence

The separate observed-result model supports `FULL_FILL`, `PARTIAL_FILL`,
`NO_FILL`, `CANCELLED_REMAINDER`, and `UNKNOWN`. It requires actual filled and
confirmed position quantities. A fill cannot exceed either a quantity request
or confirmed position, and a partial fill cannot be labeled full.

Later metrics may include actual slippage, delay, quantity fill ratio, initial
risk, and execution-adjusted reward/risk. No-fill results carry no fill or
slippage metrics. The attachment binds the original opinion ID and fingerprint
and fails if later evidence changes either.

## Deferred Capabilities

- Level 2/order-book depth and queue position
- Calibrated fill probability
- Native capability-registry chronology
- Extended-hours threshold calibration
- Shortability, borrow, locate, margin, SSR, and short buying power
- Prospective collection, storage, comparison, arbitration, or authority

These gaps do not authorize a new provider or paid data source.
