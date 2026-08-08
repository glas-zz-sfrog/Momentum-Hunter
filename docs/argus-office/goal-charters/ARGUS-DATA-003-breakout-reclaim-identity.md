# ARGUS-DATA-003 Goal Charter - Breakout Versus Reclaim Identity

## Goal

Give every prospective TradePlan a deterministic, versioned identity that
distinguishes an untouched Daily breakout level from a price that has already
moved above that level and therefore requires a later pullback-and-reclaim.

## Operator Outcome

Momentum Hunter no longer moves a hypothetical entry above the current price
after a breakout has already occurred. Steven sees the original level preserved
in report evidence, while Active Monitor and Shadow remain blocked until a real
reclaim chronology exists.

## Scope

- Derive setup identity only from completed Daily support/resistance evidence.
- Preserve the original breakout level as the prospective entry.
- Classify price at or below the level as `BREAKOUT` / `PENDING_BREAKOUT`.
- Classify price above the level as `RECLAIM_REQUIRED` /
  `RECLAIM_NOT_CONFIRMED` and require a future pullback-and-recross.
- Version and fingerprint the setup identity and duplicate it consistently in
  report-integrity and TradePlan evidence.
- Preserve the blocker through Active Monitor refresh.
- Make Shadow independently reject missing, legacy, cross-symbol,
  contradictory, unsupported, or tampered setup identity.

## Non-Goals

- Do not infer that a reclaim occurred from one price snapshot.
- Do not change discovery score, composite weights, ranking, alert thresholds,
  candle collection, Risk Governor formulas, position sizing, account
  allocation, FakeBroker lifecycle, or broker/order behavior.
- Do not rewrite historical captures or reports.
- Do not change WPF or legacy PySide layout/interaction behavior.
- Do not arm Shadow or create a trade.

## Acceptance Criteria

- [x] An untouched Daily level produces a fingerprinted `BREAKOUT` identity.
- [x] Price above the Daily level preserves that level and produces
  `RECLAIM_REQUIRED` rather than a higher chase entry.
- [x] Missing or estimated Daily levels fail closed as setup-ineligible.
- [x] Active Monitor cannot erase an existing reclaim blocker.
- [x] Shadow rejects missing, contradictory, or tampered setup identity.
- [x] An unconfirmed reclaim cannot start a Shadow trade.
- [x] JSON, Markdown, and CSV reports expose the setup identity.
- [x] Legacy TradePlans without setup identity retain their prior stable ID
  shape, while new identities bind their fingerprint into the plan ID.
- [x] Raw captures, generated production reports, and protected unrelated
  behavior remain unchanged.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused and adjacent DATA-003 suite: 143/143 pass.
- Full Python discovery: 1,250/1,250 pass in 1,010 seconds.
- Full .NET solution with warnings as errors: 251/251 pass.
- `git diff --check`: pass.
- Secret/capability scan: only established FakeBroker test vocabulary; no
  credential value or new provider/account/order/transmission method.
- Protected-path review: the authorized TradePlan/readiness/Shadow boundary
  changed; score weights, alerts, scheduling, service, database/schema,
  packages, credentials, UI, raw captures, and generated data did not.

## Status

`COMPLETE` after clean fast-forward integration, ordinary non-force backup, and
repinning of the remaining opening jobs to the synchronized release head.

## Goal Steward Review

- [x] The no-chase operator value is explicit.
- [x] Reclaim confirmation is not invented from snapshot data.
- [x] Protected readiness and Shadow changes are bounded to the approved
  DATA-003 roadmap gate.
- [x] Tests prove model, export, refresh, tamper, selection, and lifecycle
  behavior rather than label existence.
- [x] No visual acceptance item is required because no UI changed.
