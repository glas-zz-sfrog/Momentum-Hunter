# ARGUS-BREAKOUT-001 Sequential Breakout Research

## Classification

`IMPLEMENTED_PENDING_INTEGRATION`

Implementation commit: `2d9b616`

Stacked dependency: MONITOR implementation `b71feb0`

## Result

This isolated branch adds a dormant, research-only sequential event detector
over immutable canonical completed minute bars. It records impulse, opening or
continuation breakout, missed entry, failure, pullback, reclaim, exhaustion,
and explicit unavailable-data evidence without producing score, readiness,
TradePlan, selection, Risk Governor, broker, account, or order authority.

## Contract

- Reuses MONITOR opportunity and setup IDs exactly.
- Uses only prior completed windows for trigger, range, and volume baselines.
- Gives pullback and reclaim new setup identities with predecessor links.
- Keeps missed and failed breakout evidence immutable.
- Resets sequence derivation on gaps; a post-gap move cannot reuse the opening
  range and may qualify only from a newly completed continuation window.
- Persists versioned policy identity, provider/receipt time, canonical source
  state/fingerprint, relative volume, trigger distance, event chain, and
  explicit `RESEARCH_ONLY` / `execution_authority=false` flags.
- Provides deterministic event IDs, exact-rerun idempotency, conflict rejection,
  atomic replacement, tamper detection, and canonical JSON.

## Hard-Chew Findings

The second pass found and repaired three defects before commit:

1. A reclaim bar could fall through and be labeled as a new opening breakout on
   the same completed candle. Reclaim now consumes that bar's transition.
2. Persisted lineage did not independently prove that pullback/reclaim
   predecessors had already occurred. Setup sequence, predecessor, event-family,
   mode, chronology, and numeric invariants now fail closed.
3. A visible minute gap reset active state but could leave the pre-gap opening
   trigger reusable. Opening identity is now invalid after any gap.

## Verification

- Compileall: pass for `momentum_hunter` and `tests`.
- Focused sequential suite: 20/20 pass.
- Adjacent candle, MONITOR, legacy breakout, active-monitor, and intraday-plan
  suite: 188/188 pass.
- Full Python discovery: 1,372/1,372 pass in 225.639 seconds.
- The first full run had two environment-only failures because repository
  PowerShell tests require `.venv` inside the worktree. An ignored junction to
  the existing dependency environment made both exact tests pass; the final
  complete discovery then passed.
- Diff/whitespace, protected-path, secret-shaped value, runtime import, and
  network/broker capability scans: pass.

## Protected Boundaries

No existing runtime module imports this detector. No existing source, score,
rank, readiness, alert, TradePlan, selector, Risk Governor, allocation,
FakeBroker, Alpaca, Schwab request, account, position, order, service, scheduler,
Engine Host, WPF, Shadow, package, schema, credential, raw capture, production
data, or generated report changed. Canonical `master` remains clean and equal
to `origin/master` at `1d0ca95`; the installed service remains
Running/Automatic and its manifest hash remains unchanged.

## Remaining Work

- Reconcile stacked MONITOR lineage before integration.
- Do not install or activate while the canonical runtime pin is active.
- A later prospective producer may feed canonical completed bars into this
  layer; BREAKOUT-002 remains blocked until a frozen sufficient cohort exists.
- Thresholds remain versioned research policy and carry no trading authority.
