# ARGUS-REGIME-002 Exhaustion And Market-Stress Specialist

## Boundary

REGIME-002 is a dormant, offline analytical extension of CONTINUOUS-003. It
accepts explicit canonical minute bars and a decision timestamp, reuses the
existing rolling-regime derivation, and returns an immutable research packet.
It has no provider, file writer, scheduler, service, Engine Host, UI, scoring,
risk, broker, or order capability.

## Existing CONTINUOUS-003 Truth

`rolling_market_regime.py` already owns:

- canonical `RegimeBar` validation and source-state requirements;
- SPY/QQQ/IWM benchmark policy and optional sector symbols;
- short/long SMA and return measurements;
- latest-range volatility multiple;
- `RISK_ON`, `RISK_OFF`, `MIXED`, `SECTOR_ROTATION`,
  `VOLATILITY_SHOCK`, `EVENT_RISK`, and `DATA_STALE`;
- explicit sufficiency, confidence, event-risk, transition, predecessor,
  policy, source, input, timestamp, and fingerprint fields;
- strictly increasing append-only snapshot transitions; and
- bounded candidate context fan-out without score authority.

`macro_event_context.py` already owns versioned calendar and revision identity,
source chronology, event scope, deterministic consequence rules, and
`NORMAL`, `CAUTION`, `BLOCK_NEW_ENTRY`, and `DATA_STALE` event context. It
cannot score or initiate a trade.

These contracts are integrated but dormant. They have deterministic unit and
integration proof, but no continuous production source/writer or execution
authority. REGIME-002 does not rename, replace, or fork them.

## REGIME-002 Addition

REGIME-002 adds a richer research body while preserving the common Specialist
Opinion envelope:

- `RegimeResearchPolicy`: immutable v1 feature and classification definitions.
- `BenchmarkFeatures`: raw measurements for each core benchmark.
- `RegimeResearchAssessment`: independent direction, extension, stress,
  session, and data-quality states.
- `RegimeSpecialistPacket`: policy + assessment + common Specialist Opinion,
  with a packet fingerprint binding all three.

The common envelope remains unchanged. The assessment is specialist-owned
because the common contract intentionally does not become a global enum or a
container for every specialist's domain model.

## Required Inputs

All three core benchmarks are required:

```text
SPY + QQQ + IWM
```

Inputs must be completed terminal canonical bars in `RECONCILED`, `CORRECTED`,
or `HISTORY_ONLY_GAP_FILL` state. They must share one session date, have one
source identity per symbol, remain within bounded timestamp skew and internal
gap limits, and contain no future/in-progress bar. Sixty-one completed bars
are required for the 60-minute horizon. Regular-session evaluation also
requires the complete 09:30-09:34 ET opening range.

Optional caller-supplied context is kept distinct:

- prior-close values are raw context and visibly carry the limitation
  `PRIOR_CLOSE_PROVENANCE_CALLER_SUPPLIED`;
- candidate participation is
  `BOUNDED_CANDIDATE_UNIVERSE_PROXY`, never market breadth; and
- validated CONTINUOUS-003 macro context may inform stress but cannot alter
  production behavior.

No internal provider or network call exists.

## Raw Feature Body

Each benchmark preserves:

- 1/5/15/30/60-minute returns;
- return since regular-session open, versus prior close, and across the
  observed premarket window when available;
- current price, session high/low, distances from both, higher-high and
  lower-low persistence, and opening-range location;
- volume-weighted typical-price `BAR_DERIVED_VWAP`, percentage distance, and
  ATR-normalized distance;
- ATR, ATR percentage, realized 1-minute volatility, current range, range
  expansion, 5-minute speed, and acceleration;
- consecutive directional bars, time since opposite bar, 15-minute price
  progress per million volume, and 5-to-15-minute incremental progress ratio;
  and
- cross-index agreement and 15-minute dispersion.

The values remain available regardless of the eventual state label.

## Independent States

Direction:

```text
TREND_UP | TREND_DOWN | ROTATION | CHOP | MIXED | UNKNOWN_DIRECTION
```

Extension:

```text
NORMAL_EXTENSION | LATE_TREND | EXHAUSTION_RISK |
EXTREME_EXTENSION | UNKNOWN_EXTENSION
```

Stress:

```text
NORMAL | ELEVATED_VOLATILITY | VOLATILITY_SHOCK |
MARKET_STRESS | DATA_UNSAFE
```

Session:

```text
PREMARKET | OPENING | MIDDAY | LATE_SESSION |
AFTER_HOURS | UNSUPPORTED_SESSION
```

Data quality:

```text
COMPLETE | PARTIAL | DATA_UNSAFE
```

This permits truthful combinations such as `TREND_UP + EXHAUSTION_RISK +
NORMAL`. `DATA_UNSAFE` is not `MIXED`, and a failed evaluation cannot become a
neutral opinion.

## Session And Missing-Data Policy

- Premarket evaluation covers only trusted observed evidence and preserves
  `TRUE_04_TO_07_PATH_UNOBSERVED`.
- V1 uses an explicit frozen session multiplier table rather than assuming
  one tape-speed threshold across the day: premarket `1.25x`, opening
  `1.00x`, midday `0.75x`, and late session `1.00x`. The multipliers apply to
  direction, rotation/chop, extension, downside-stress, and volatility
  thresholds and are included in the policy fingerprint.
- After-hours is recognized, but v1 abstains `UNSUPPORTED_SESSION`; regular
  thresholds are not silently borrowed.
- Any missing core benchmark or incomplete horizon abstains
  `INSUFFICIENT_EVIDENCE`.
- Stale evidence abstains `STALE_EVIDENCE`.
- Future, contradictory, cross-session, duplicate, wrong-symbol, mixed-source,
  gap, or fingerprint-mismatched evidence fails.

## Threshold Semantics

All v1 classifier thresholds are marked `RESEARCH_HEURISTIC`. They exist only
to make deterministic fixture and future prospective comparison possible.
They were not optimized against historical returns and do not represent a
crash probability. The session multipliers are provisional hypotheses, not
empirical calibrations. Common-envelope numeric confidence is
benchmark-alignment completeness with `HEURISTIC / UNCALIBRATED` semantics.

## Specialist Opinion Mapping

```text
specialistId       REGIME
specialistVersion  regime-exhaustion-research-v1
authority          RESEARCH_ONLY
executionAuthority EXECUTION_AUTHORITY_NONE
```

The opinion code carries the most salient current state in priority order:
stress, then extension, then direction. The full assessment remains
authoritative for multidimensional meaning. Directional bias reflects market
direction only; it is not an entry or exit recommendation. Feature-family
disclosure includes market regime, price momentum, candle structure, and
volume so a future arbiter cannot claim false independence from Momentum's
price evidence.

## Dormant Prospective Plan

Recommended future research identity: `regime-research-v1`.

Recommended cadence after a separate activation task: every five minutes
during the regular session, including periodic observations when Momentum has
no candidate. Candidate-linked observations should preserve the exact
opportunity/setup/TradePlan identity, while periodic observations use a
deterministic market-observation target ID.

Later prospective analysis should compare the unchanged Momentum baseline
against hypothetical regime veto and risk-reduction policies using win/loss,
MFE, MAE, R, setup family, and rank. REGIME-002 does not perform or authorize
those counterfactual policy changes.

## Retrospective Examples

No Aug. 13/14 retrospective classification was used in v1. The preserved
evidence was not needed to prove packet shape, and omitting known-outcome
examples avoids even the appearance of threshold tuning. Seven synthetic
fixtures are proof fixtures only, not performance observations.
