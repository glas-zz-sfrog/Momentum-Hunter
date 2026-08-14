# ARGUS-REGIME-002 Exhaustion And Market-Stress Research Specialist

## Classification

`IMPLEMENTED_PENDING_PARENT_INTEGRATION`

## Lineage

- Canonical base: `ea056155182351be70bb03d23841aca55c6118ae`.
- Specialist Contract parent: `e65cb702dfd0c2515c8c37bae6fd377315c71f83`.
- Branch: `codex/ARGUS-REGIME-002-exhaustion-market-stress`.
- Specialist version: `regime-exhaustion-research-v1`.
- Policy version: `regime-exhaustion-research-policy-v1`.
- Policy fingerprint:
  `55d5e05f91553381ba162c70b09c5f9987262edfbe2a9ec687214cc29f9d1057`.

## Delivered Behavior

REGIME-002 consumes explicit canonical SPY/QQQ/IWM minute bars and returns a
deterministic packet containing:

- raw 1/5/15/30/60-minute, session, prior-close, and premarket returns;
- session structure, opening range, `BAR_DERIVED_VWAP`, ATR, realized
  volatility, range expansion, speed, acceleration, persistence, pullback,
  progress/volume, agreement, and divergence features;
- separate direction, extension, stress, session, and data-quality states;
- an immutable specialist-owned assessment and the unchanged common
  Specialist Opinion Contract; and
- source, input, rolling-snapshot, macro-context, policy, assessment, opinion,
  and packet identity/fingerprints.

All thresholds are provisional `RESEARCH_HEURISTIC` constants. The immutable
policy applies explicit premarket `1.25x`, opening `1.00x`, midday `0.75x`,
and late-session `1.00x` threshold profiles rather than treating every time
of day as equivalent. Numeric confidence is `HEURISTIC / UNCALIBRATED`, not
a probability.

## Frozen Safety Behavior

- Missing SPY, QQQ, or IWM: `ABSTAINED / INSUFFICIENT_EVIDENCE`.
- Stale benchmark: `ABSTAINED / STALE_EVIDENCE`.
- Unsupported after-hours session: `ABSTAINED / UNSUPPORTED_SESSION`.
- Future, in-progress, contradictory, mixed-date, wrong-symbol, duplicate,
  mixed-source, gap, or fingerprint-mismatched evidence: `FAILED`.
- Unsafe evidence: `UNKNOWN_DIRECTION / UNKNOWN_EXTENSION / DATA_UNSAFE`,
  never a neutral market claim.
- Research authority: exactly `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`.

## Fixture Evidence

Focused synthetic proof covers normal trend-up, normal trend-down, rotation,
chop, late trend, exhaustion/extreme extension, volatility shock, coordinated
market stress, and data unsafe. The negative matrix covers missing benchmarks,
staleness, future/in-progress bars, mixed dates, wrong identity, mixed sources,
duplicates, gaps, missing opening range, incomplete horizon, timezone-naive
time, after-hours, fingerprint mismatch, one-index nonconfirmation, policy and
packet tampering, authority escalation, false full-market breadth, and missing
or malformed session-threshold policy. A matched marginal-move fixture proves
that opening and midday apply their distinct frozen profiles.

No Aug. 13/14 result was used or tuned.

## Verification

- Module compile: PASS.
- Focused REGIME-002 tests: 43 / 43 PASS.
- REGIME-002 + Specialist + rolling-regime + macro regressions: 152 / 152
  PASS.
- Candle/readiness/evidence regressions: 102 / 102 PASS.
- SETUP-002 nonmutation regressions: 29 / 29 PASS.
- Full Python discovery: 2,106 / 2,106 PASS after the v1 after-hours policy
  fail-closed guard.
- `git diff --check`: PASS (line-ending warnings only).
- Runtime importer/capability scan: PASS; no runtime imports REGIME-002 and the
  specialist imports no provider, persistence, service, UI, risk, Paper,
  Shadow, broker, or order capability.
- Secret scan: PASS; no credential-shaped value exists in the changed set.
- Canonical nonmutation: clean `master` and `origin/master` remain identical at
  `ea056155182351be70bb03d23841aca55c6118ae`.
- Installed manifest identity: unchanged SHA-256
  `8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`.
- August 17 opening, Paper, SETUP-002 Pass 1, and SETUP-002 Pass 2 jobs remain
  enabled, dependency-correct, and pinned to canonical `ea056155`.

## Protected Boundary

No existing runtime file is modified. No provider, persistence, service,
scheduler, Engine Host, UI, score, candidate, TradePlan, Risk Governor,
allocation, Paper, Shadow, account, broker, order, stop, liquidation,
credential, database/schema, generated data, or Aug. 17 job path changes.

## Remaining Gate

The parent Specialist Contract must be deliberately integrated before, or in
the same reconciled integration as, REGIME-002. A later task must separately
authorize any persistence, schedule, continuous observer, UI, or strategy use.
