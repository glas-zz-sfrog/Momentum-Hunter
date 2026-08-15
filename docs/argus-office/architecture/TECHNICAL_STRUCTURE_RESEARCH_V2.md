# Technical Structure Research v2

## Boundary

TECH-STRUCTURE-002 is a pure, offline evaluator for an existing Momentum
opportunity. It accepts caller-supplied bar and level evidence and returns
immutable structure instances plus one common-contract Specialist Opinion. It
does not fetch, persist, nominate, rank, select, plan, size, trade, schedule,
render, or modify the opportunity it observes.

## Technical Breakout Engine v1 Inventory

The existing `momentum_hunter/technical_breakouts.py` remains the foundation.

- Daily features: prior-window Donchian 20/30/50 breakouts, 20/50 SMA state and
  crossings, Bollinger upper-band breakout, ATR/Keltner breakout, volume/RVOL,
  and optional QQQ relative-strength confirmation.
- Intraday features: bar-derived cumulative VWAP reclaim, opening-range high,
  15-minute high, 60-minute high, volume context, and research extension.
- Outcome study: forward returns, MFE, MAE, held/failed level state, extension,
  and explicit insufficient-data results.
- Inputs: local canonical Schwab minute bars, optional Daily OHLC, and local
  evidence/report files. The report builder can read those sources and write
  latest JSON/Markdown reports.
- Existing levels: rolling highs, moving averages, volatility bands, opening
  range, and prior intraday highs. V1 has no reusable swing-pivot or sparse
  support/resistance engine.
- Existing volatility normalization: standard deviation, true range/ATR,
  Keltner distance, relative volume, and extension calculations.
- Existing identity: event identity binds symbol, timestamp, event type, and
  timeframe. It does not bind a prospective pivot-confirmation horizon,
  opportunity/setup target, analysis price basis, or common specialist policy.
- Existing semantics: breakout event detection and retrospective event-study
  measurement. It does not provide immutable structure geometry, separate
  economic/known-at time, basis admission, or a Specialist Opinion.

V2 imports and reuses v1's `TechnicalPriceBar`, `true_range`, and cumulative
bar-derived VWAP rather than replacing those calculations. Its richer bar
wrapper adds only evidence properties v1 lacks: completion time, completion
state, session, price basis, immutable bar identity, and source fingerprint.

## Immutable Contracts

### TechnicalStructureBar

Each bar binds symbol, economic timestamp, completion timestamp, OHLCV, source,
session, price basis, completion state, evidence fingerprint, and deterministic
bar identity. Completed geometry may use only bars whose completion timestamp
is at or before the evaluation `asOf`. A forming bar remains provisional and
cannot confirm a structure.

### TechnicalPivot

A pivot preserves:

- `timestamp`: the economic time of the swing high/low;
- `known_at`: completion time of the final required right-side confirmation
  bar;
- pivot type, price, source bar, confirmation horizon, evidence fingerprint,
  identity, and full fingerprint.

The engine never treats the economic pivot time as the time the pivot became
knowable.

### TechnicalReferenceLevel

Levels are either caller-frozen preexisting levels or sparse pivot clusters.
They preserve price, type, origin, first-known time, actual known time, touch
count, ATR tolerance, invalidation state, evidence identity, and fingerprint.
The detector does not emit a dense collection of arbitrary chart lines.

### TechnicalStructureInstance

Every instance binds:

- structure/version, opportunity/setup, symbol, direction;
- event time, `knownAt`, evidence start/end;
- confirmation and invalidation state;
- exact pivots, levels, normalized geometry, volatility and volume context;
- session, price basis, policy fingerprint, source fingerprints, reasons;
- deterministic structure identity and tamper-evident fingerprint.

Changing a material pivot, level, horizon, bar, target, policy, basis, or
geometry changes identity.

## Frozen v2 Policy

`technical-structure-research-v2` fingerprints every material heuristic:
pivot left/right confirmation, ATR and minimum-bar windows, interval and stale
limits, level touch/tolerance, breakout buffer, retest tolerance, failure
horizon, compression/expansion thresholds, retracement bounds, double-extreme
geometry, shoulder/head/neckline tolerances, VWAP tolerance, exhaustion
thresholds, supported sessions, and premarket path admission.

The policy is one preregistered software-validation variant. No historical
profit optimization or parameter search is performed.

Frozen policy fingerprint:
`6b40ecc89cbfe5d1b3fb0c4d5b1376a4b5e9fb8e3bc96282afccf4838cbb1aa0`.

## Structure Semantics

- **Compression/expansion:** prior-window range contraction followed by a
  completed range expansion closing outside the frozen compression boundary.
- **Breakout/retest:** a level known beforehand, completed close beyond an
  ATR-normalized buffer, later return within tolerance, then a separate
  completed hold/rejection bar.
- **Failed breakout:** a known level breaks, then closes back through the
  opposite tolerance within the frozen prospective horizon. A bar crossing
  breakout and invalidation together is `AMBIGUOUS_SAME_BAR`.
- **VWAP reclaim/loss:** completed below-to-above or above-to-below close
  transition around cumulative `BAR_DERIVED_VWAP`, followed by a completed
  hold/rejection. It is never described as provider VWAP.
- **Higher-low/lower-high:** ordered confirmed pivots, ATR/ratio-bounded
  retracement, then completed continuation/breakdown through the prior impulse
  extreme.
- **Double top/bottom:** two confirmed extremes within ATR tolerance, a
  sufficiently deep intervening valley/peak, and optional later neckline
  confirmation. Potential and confirmed states remain distinct.
- **Support/resistance:** caller-frozen levels or repeated pivot clusters,
  admitted only when near current structure and represented sparsely.
- **Head-and-shoulders/inverse:** five ordered pivots, ATR-bounded shoulder
  symmetry and head prominence, explicit neckline geometry, and optional later
  neckline confirmation.
- **Technical exhaustion:** instrument-level repeated failure, weaker highs,
  extreme extension/failure, or high volume without price progress. This is
  separate from REGIME's market-level exhaustion role.

Multiple valid structures coexist. Conflicting confirmed structures remain
visible. V2 performs no majority vote, weighted pattern score, universal
technical score, or Arbiter function.

## Opinion Mapping

The high-level common-contract vocabulary is:

- `STRUCTURE_SUPPORTS`
- `STRUCTURE_NEUTRAL`
- `STRUCTURE_CONTRADICTS`
- `STRUCTURE_EXHAUSTED`
- explicit `NO_OPINION` abstention

Unknown, stale, unsupported, or unsafe evidence abstains; it does not become
neutral. Confidence remains unavailable in v2 rather than implying a pattern
probability. Evidence-family disclosure includes only consumed candle
structure, price momentum, and, for bar-derived VWAP or volume exhaustion,
volume evidence.

## Price-Basis Admission

- `SAME_SESSION_RAW_PROVIDER` is admitted only for one internally consistent
  session with verified basis, safe corporate-action continuity, and at least
  session-bound security identity.
- Cross-session raw geometry abstains.
- Cross-session `SPLIT_ADJUSTED_ANALYSIS` or `TOTAL_RETURN_ADJUSTED` geometry
  requires durable security identity and explicit verified basis.
- Unknown basis, unresolved identity, or a corporate-action discontinuity
  produces `DATA_BASIS_UNCERTAIN` abstention.
- Regular session is the only full-evaluation session in frozen v2. Premarket
  and after-hours abstain; current premarket evidence cannot represent the
  unobserved 04:00-07:00 ET path.

These are narrow compatibility semantics for RESEARCH-DATA-002. This module
does not transform bars or repair corporate-action history.

## Same-Bar And Look-Ahead Safety

No bar after `asOf`, no completed bar whose completion is after `asOf`, and no
future right-side pivot confirmation is admitted. Breakout/retest, VWAP,
continuation, double-extreme, and head-and-shoulders confirmation checks detect
bars that also cross their invalidation boundary and preserve
`AMBIGUOUS_SAME_BAR` rather than inventing intrabar order.

## Research Compatibility

- **SPECIALIST-CONTRACT-001:** exact parent dependency; output is
  `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE` and binds the existing target
  chain without creating another envelope.
- **RESEARCH-GOV-001:** exposes a single-variant preregistration descriptor;
  no outcome optimization or holdout access occurs.
- **RESEARCH-DATA-002:** uses explicit basis/security admission concepts and
  abstains instead of duplicating its transformation or registry machinery.
- **STAT-DATA-001:** the common opinion carries opportunity/opinion/as-of/
  fingerprint fields needed for a later separate write-once attachment. This
  task writes no denominator record.
- **SETUP-002:** no import, sample change, policy change, observer change, or
  scheduler change. A SETUP-002 successor outcome is not a TECH opinion.
- **REGIME / EXEC-QUALITY / EVENT-SHOCK:** no imports or combined decision.
  Market regime, liquidity/fill quality, and event relevance remain separate
  sibling evidence.

## What Is Not Proven

TECH-STRUCTURE-002 proves deterministic detector software, evidence chronology,
price-basis admission, immutable geometry, and bounded research opinions. It
does not prove pattern profitability, predictive edge, optimal thresholds,
independent information value, production usefulness, candidate-nomination
value, or trade authority. Predictive claims require future prospectively
governed evidence and the outstanding corporate-action/data foundations.
