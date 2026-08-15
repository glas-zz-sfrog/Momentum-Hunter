# ARGUS-EXEC-QUALITY-001 Release Report

## Classification

`IMPLEMENTED_PENDING_PARENT_INTEGRATION`

This release adds one provider-neutral, read-only Execution Quality research
specialist. It answers what evidence indicates that entry and exit conditions
were mechanically clean or mechanically ugly. It cannot answer whether to buy,
alter a strategy decision, or acquire execution authority.

## Source Identity

- Canonical master: `ea056155182351be70bb03d23841aca55c6118ae`
- Specialist Contract parent: `e65cb702dfd0c2515c8c37bae6fd377315c71f83`
- Feature branch: `codex/ARGUS-EXEC-QUALITY-001-liquidity-execution-research`
- Specialist ID: `EXECUTION_QUALITY`
- Specialist version: `execution-quality-research-v1`
- Policy version: `execution-quality-research-policy-v1`
- Policy fingerprint:
  `5b831e70e92827104df23e116a4d679835f7e693292750f9b85f0d34e080f1df`
- Authority: `RESEARCH_ONLY`
- Execution authority: `EXECUTION_AUTHORITY_NONE`
- REGIME-002 remains an independently testable sibling and is not imported.

## Evidence Inputs

Predecision inputs are immutable caller-supplied records only:

- bid, ask, component timestamps, provider quote time, local receipt time,
  source identity, session, real-time state, and optional proven displayed size;
- bounded canonical one-minute OHLCV evidence with source, session, state,
  timestamp, and fingerprint identity;
- an optional immutable DATA-004 TradePlan;
- an optional DATA-005B allocation decision used only to express hypothetical
  dollar-risk sensitivity at an already-authorized quantity;
- an optional provider-neutral capability registry, without provider-name
  inference.

The specialist makes no Schwab, Alpaca, account, provider, network, filesystem,
service, scheduler, Engine Host, WPF, or order call.

Later broker outcome attachment accepts separately persisted actual provider
facts: decision ask, submitted reference, requested quantity/notional, provider
acceptance/fill/cancel chronology, actual filled quantity, confirmed position
quantity, and actual average fill. Later evidence cannot mutate the original
packet or opinion.

## Frozen V1 Vocabulary

- Liquidity: `LIQUID`, `ADEQUATE`, `THIN`, `VERY_THIN`, `UNKNOWN`.
- Spread: `TIGHT`, `NORMAL`, `WIDE`, `EXTREME`, `UNKNOWN`.
- Quote stability: `STABLE`, `MODERATELY_UNSTABLE`, `UNSTABLE`, `DISLOCATED`,
  `UNKNOWN`.
- Price-impact risk: `LOW`, `MODERATE`, `HIGH`, `UNKNOWN`.
- Fill risk: `LOW`, `MODERATE`, `HIGH`, `UNKNOWN`.
- Data quality: `COMPLETE`, `PARTIAL`, `DATA_UNSAFE`.
- Market state includes `NORMAL_MARKET`, `HALTED`, `QUOTE_UNAVAILABLE`,
  `ONE_SIDED_MARKET`, `CROSSED_MARKET`, `LOCKED_MARKET`, `STALE_MARKET`, and
  `DATA_UNSAFE`.
- Observed fills: `FULL_FILL`, `PARTIAL_FILL`, `NO_FILL`,
  `CANCELLED_REMAINDER`, `UNKNOWN`.

## Derived Research Features

Raw features preserve bid, ask, midpoint, absolute/percentage/basis-point
spread, spread relative to ATR, recent one-minute range, stop distance, and
planned risk per share. Quote-sequence features preserve observation window,
bid/ask/midpoint movement, midpoint range, spread expansion, update frequency,
direction changes, and realized midpoint volatility. Candle features preserve
recent/prior volume, dollar turnover, price progress/range, progress per unit
volume, volume expansion, volume without progress, and rapid movement on thin
volume.

TradePlan sensitivity is explicitly `MATHEMATICAL_COUNTERFACTUAL` at frozen
entry bands of 0, 5, 10, and 25 basis points. Each point reports hypothetical
entry, per-share risk/reward, reward/risk, entry extension, distances to stop
and first target, and optional dollar risk at the already-authorized quantity.
It never changes entry, stop, target, allocation, or quantity.

Observed execution metrics are separate from predecision features and include
slippage from both decision ask and submitted reference, fill delay, actual
quantity fill ratio, realized initial risk, and realized execution reward/risk.
Full and partial fills use actual provider-filled quantity only. A no-fill has
no slippage or realized metrics. A cancelled remainder retains partial-fill
semantics and requires a cancellation timestamp. Filled quantity cannot exceed
requested quantity or confirmed position quantity.

## Opinion And Abstention

Evaluated packets map to one specialist-owned code:

- `EXECUTION_CONDITIONS_SUPPORT`
- `EXECUTION_CONDITIONS_ACCEPTABLE`
- `EXECUTION_CONDITIONS_FRAGILE`
- `EXECUTION_CONDITIONS_POOR`
- `EXECUTION_CONDITIONS_DISLOCATED`

Missing, stale, contradictory, unsupported-session, or insufficient evidence
uses first-class abstained/failed semantics with `NO_OPINION`; it is never
represented as neutral, stable, liquid, or acceptable. Full v1 classification
is regular-session only. Premarket and after-hours packets preserve safe raw
spread measurements and then abstain as `UNSUPPORTED_SESSION`.

Confidence is an uncalibrated `HEURISTIC` completeness indicator. It is not a
fill probability, strategy probability, universal execution score, or trade
authority. Feature-family disclosure includes only consumed evidence families.

## Fixture And Hard Chew Results

- All A-K directive fixtures passed: liquid/tight, wide spread, unstable quote,
  volume without progress, thin rapid move, stale quote, malformed market,
  partial fill, positive slippage, negative slippage, and no fill.
- The complete negative matrix passed, including chronology, identity,
  freshness, malformed/tampered evidence, policy drift, authority tampering,
  impossible quantities, no-fill contamination, and later-fill leakage.
- Focused EXEC-QUALITY suite: **45 tests passed**.
- Affected Specialist Contract, DATA-004, DATA-005B, Paper lifecycle, Schwab
  quote, SETUP-002 observer, and activation regressions: **216 tests passed**.
- Full Python discovery: **2,108 tests passed** in 240.603 seconds.
- Python compileall: passed.
- Git diff check: passed before release closeout.

The historical A003 $1 SPY Paper lifecycle was not consumed or used to tune
thresholds. It remains available only as a future
`HISTORICAL_EXECUTION_CAPABILITY_EXAMPLE`, never strategy or general fill-quality
evidence.

## Prospective Design And Missing Capabilities

A later, separately authorized prospective sample may freeze an immutable
predecision packet per opportunity and attach actual Paper execution afterward
without changing the original opinion. It should preserve opportunity/setup,
decision time, TradePlan fingerprint, opinion, whether a trade occurred, and
later actual or counterfactual outcomes. It is not activated by this task.

Missing capabilities remain explicit: no Level 2/order-book depth, no proven
universal displayed-size source, no calibrated fill probability, no extended-
hours classification thresholds, no shortability/borrow/locate/SSR model, no
provider expansion, no prospective sample, and no statistical claim about
incremental value after Momentum or REGIME.

## Safety And Nonmutation Proof

- Changed runtime surface is one unconsumed pure research module; no production
  module imports it.
- No candidate, score, ranking, TradePlan, Risk Governor, allocation, Paper,
  Shadow, provider, broker adapter, account, order, SETUP-002, REGIME-002,
  service, scheduler, Engine Host, WPF, package, schema, or generated-data file
  changed.
- Static import/capability tests found no provider, network, broker-order,
  persistence, runtime, service, scheduler, Engine Host, or UI capability.
- Canonical checkout remained clean and synchronized at `ea056155`.
- Installed automation manifest SHA-256 remained
  `8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`.
- Aug. 17 opening, Paper, SETUP-002 Pass 1, and SETUP-002 Pass 2 jobs remained
  enabled, dependency-gated, and pinned to `ea056155`.
- Nothing was installed, activated, scheduled, repinned, or merged.

## Exact Next Gate

After Aug. 17 operational evidence is terminal and preserved, reconcile the
common Specialist Contract and its independently developed specialist siblings
on one deliberate integration branch. Then rerun combined contract and full
regressions. Prospective EXEC-QUALITY collection, statistical calibration,
combination with other specialists, and any production authority each require
their own later task.
