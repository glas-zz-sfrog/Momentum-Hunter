# ARGUS-CATALYST-002A Provider-Neutral Catalyst Evidence

## Classification

`IMPLEMENTED_PENDING_INTEGRATION`

Implementation commit: `c53a24b`

Validated base: MONITOR closeout `d2b77c2`, including candidate-lifecycle
implementation `b71feb0` from canonical `1d0ca95`.

## Result

This isolated branch adds a dormant, provider-neutral contract for continuous
catalyst observations. It preserves source/article identity, immutable
revisions, supplied attribution and authority, source availability, evaluated
freshness, deterministic material deltas, and tamper-evident replay without
fetching a provider or changing production scoring.

## Contract

- Stable event identity binds canonical source, source article, and candidate.
- Every observation is normalized, fingerprinted, and appended atomically.
- Exact replay is byte-stable and idempotent.
- Redelivery and cosmetic revisions remain visible without refreshing the
  original publication clock or triggering reevaluation.
- Content, attribution, authority, source metadata, and duplicate-status
  changes create explicit deterministic material deltas.
- Same-source duplicate content keeps each source record but emits one material
  discovery. Duplicate snapshots are `DUPLICATE_CONTENT`, research-only, and
  effective-score-authority blocked.
- Different canonical sources remain independent even when their text matches.
- Unknown publication time, stale evidence, source outage, unresolved
  attribution, and duplicate content all fail closed.
- Recovery never makes old catalyst evidence fresh.
- Historical evaluation excludes later revisions and outages, preventing
  lookahead.

## Self-Review Repairs

The second pass found and fixed three issues before commit:

1. Duplicate article IDs initially suppressed a second material event but their
   snapshots could still look authority-supported. Duplicate snapshots now
   carry explicit lineage and blocked effective authority.
2. Duplicate validation initially compared only with the source event's first
   revision. It now accepts any earlier matching revision while rejecting
   missing or contradictory lineage.
3. A catalyst becoming duplicate or becoming independent again initially had
   no explicit authority transition. `CATALYST_DUPLICATE_STATUS_CHANGED` now
   forces deterministic reevaluation without creating another discovery.

Validation also rejects boolean schema values and non-string required IDs,
symbols, and text instead of allowing Python coercion to make malformed input
look valid.

## Verification

- Compileall: pass.
- Focused catalyst suite: 43/43 pass.
- Bounded catalyst, evidence-integrity, lifecycle, age/cluster/headline,
  monitor, TradePlan, and Daily Workflow suite: 158/158 pass.
- Full Python discovery: 1,395/1,395 pass in 217.383 seconds.
- The temporary ignored `.venv` junction needed by two repository PowerShell
  tests was verified, used only for discovery, and removed afterward; the
  canonical dependency environment remains present.
- `git diff --check`: pass.
- Secret scan: no credential-shaped value; the only lexical hit was the word
  `secret` in the proof checklist.
- Capability scan: standard library plus `evidence_integrity` only; no network,
  provider, broker, account, endpoint, or order import/call.
- Runtime import scan: no existing production module imports this contract.

## Protected Boundaries

No existing runtime, scoring, ranking, readiness, TradePlan, Risk Governor,
selector, Shadow, FakeBroker, Alpaca, Schwab, account, order, service,
scheduler, Engine Host, WPF, package, schema, credential, production evidence,
generated data, or provider configuration file changed. Canonical `master`,
the installed service, 25 pinned opening jobs, Shadow state, and Alpaca Paper
state were not touched.

## Remaining Work

- Integration must preserve commit order after MONITOR and wait for the
  serialized runtime-pinning window.
- CATALYST-002B must choose and prove a provider/source contract before any live
  intake exists.
- A later separately scoped task must connect accepted observations to runtime
  monitoring and production authority. This branch does not do so.
