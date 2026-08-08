# ARGUS-DATA-003 Breakout Versus Reclaim Identity

Status: `COMPLETE`

## Result

Prospective TradePlans no longer convert an already-crossed Daily resistance
level into a new entry just above the current price. The original level remains
the plan entry, and the setup becomes `RECLAIM_REQUIRED` with a fail-closed
`RECLAIM_CONFIRMATION_REQUIRED` blocker until later work can prove a real
pullback-and-recross chronology.

## Evidence Contract

- Schema 1 and profile `breakout-reclaim-identity-v1` bind symbol, source,
  observed price, breakout level, planned entry, confirmation state/rule,
  invalidation level/rule, pullback requirement, findings, and SHA-256
  fingerprint.
- Only completed Daily-bar levels can receive setup-identity authority.
- Price at or below the level is `BREAKOUT` / `PENDING_BREAKOUT`.
- Price above the level is `RECLAIM_REQUIRED` /
  `RECLAIM_NOT_CONFIRMED`; the level is not moved and no reclaim is fabricated.
- JSON stores the same setup record under evidence integrity and TradePlan;
  Markdown and CSV expose the setup type, authority, original level,
  confirmation, and fingerprint.

## Runtime Boundaries

- Active Monitor recalculates against the original breakout level and preserves
  the reclaim blocker during market-tape refresh.
- Shadow independently checks schema, profile, source, symbol, level ordering,
  Daily technical agreement, TradePlan agreement, setup-specific rules,
  blockers, readiness, and fingerprint.
- A missing/tampered setup or an unconfirmed reclaim cannot start a Shadow
  trade.
- The selector runtime-build identity now includes both `trade_planning.py` and
  `trade_setup_identity.py`.

## Verification

- Python compileall: pass.
- Focused/adjacent TradePlan, setup, monitor, autonomy, Shadow lifecycle, and
  selector tests: 143 passed.
- Full Python discovery: 1,250 passed in 1,010.393 seconds.
- Full .NET solution: 251 passed with warnings treated as errors.
- `git diff --check`: pass.
- Source nonmutation, stable legacy plan IDs, deterministic fingerprints,
  sub-cent normalization, export identity, no-chase behavior, monitor
  preservation, selector tamper rejection, and no-trade reclaim behavior are
  covered directly.

## Protected Review

- Composite score weights and alert thresholds are unchanged.
- No account, position, preview, order, cancellation, replacement, broker, or
  transmission method was added or invoked.
- No service, scheduler, capture timing, provider, candle store, database,
  schema, package, credential, WPF, PySide layout, raw capture, generated
  report, or R034 legacy artifact changed.
- Historical reports remain immutable under their prior composite/evidence
  profiles.

## Remaining Limits

- DATA-003 defines and blocks a required reclaim; it does not yet observe or
  authorize one. Intraday plan horizon and lifecycle semantics remain DATA-004.
- The `$500` reference quantity is not account-aware; DATA-005 remains the
  allocator/sizing gate.
- Official Shadow remains unarmed and `0 / 30`.
- R034 archive/deletion remains a separate Steven approval gate.

## Integration Closeout

- The verified feature branch is fast-forward compatible with synchronized
  canonical `master`.
- After final integration and backup, the 25 future opening jobs are repinned to
  the synchronized release head without adding a Shadow job or transmission
  capability.
- Monday August 10 remains the next ordinary 08:35 Central capture.
