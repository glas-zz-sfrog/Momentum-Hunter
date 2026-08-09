# ARGUS-MONITOR-001 Candidate Lifecycle And Event Coordinator

## Classification

`IMPLEMENTED_PENDING_INTEGRATION`

Implementation commit: `b71feb0`

## Result

This isolated branch adds a dormant provider-neutral coordinator for persisted
candidate lifecycle evidence. It records facts supplied by a future producer;
it does not detect patterns, score candidates, build plans, select trades, or
contact a provider or broker.

## Contract

- Stable opportunity ID: symbol + market session + originating evidence family.
- Stable setup ID: opportunity + setup family + sequence.
- Explicit predecessor setup link for replacement setups.
- Legal state-transition validation across discovery, watch, impulse, breakout,
  pullback, reclaim, eligibility, missed entry, exhaustion, failure,
  invalidation, cooldown, and stale states.
- Append-only canonical JSON with atomic replacement, deterministic event IDs,
  record fingerprints, policy fingerprints, predecessor-event chains, and
  replay validation.
- Separate discovery/monitoring availability events so outages cannot erase
  candidate state or masquerade as retrospective decisions.
- Versioned cooldown, hysteresis, and minimum-delta policy; quote-only events
  cannot create decision cycles.

## Hardening Found During Self-Review

The second pass fixed two issues before commit:

1. Exact discovery replay and historical already-consumed evidence were
   initially collapsed into one status. Exact replay now returns `DUPLICATE`,
   historical replay returns `NO_CHANGE`, and conflicting replay fails closed.
2. Cooldown expiry initially used the coordinator's current policy. It now uses
   the policy persisted on the cooldown predecessor, and replay validation
   rejects an early rewritten expiry.

Event and availability identities are also recomputed from their evidence
fields, so replacing an ID and recomputing only the outer record hash fails.

## Verification

- Compileall: pass.
- Focused lifecycle suite: 38/38 pass.
- Adjacent monitor, alert, targets, TradePlan, Shadow selector, and Engine Host
  suite: 195/195 pass.
- Full Python discovery: 1,352/1,352 pass in 272.318 seconds.
- Two initial full-suite failures were worktree environment failures because
  repository PowerShell tests expect `.venv` beneath the current checkout. An
  ignored local junction to the existing dependency environment made both exact
  tests pass; the complete suite then passed.
- `git diff --check`: pass.
- Secret scan: no credential-shaped staged values.
- Capability scan: no network or order method/import.
- Runtime import scan: no existing production module imports this coordinator.

## Protected Boundaries

No existing runtime, provider, broker, adapter, account, order, scoring,
readiness, selection, TradePlan, Shadow, service, scheduler, Engine Host, WPF,
package, schema, credential, raw capture, generated production report, or
production configuration file changed. Canonical `master`, Monday's jobs, the
installed service, Shadow state, and Alpaca Paper state were not touched.

## Remaining Work

- Do not merge or activate this branch while the integration lane is frozen.
- A later task must wire only canonical R032 events into this coordinator.
- Setup detectors, regime, catalysts, breakout research, immutable plan
  versions, Risk Governor, and execution remain separate downstream tasks.
