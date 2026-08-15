# ARGUS-TECH-STRUCTURE-002 - Technical Structure Research v2

## Status

- Branch: `codex/ARGUS-TECH-STRUCTURE-002-technical-structure-v2`
- Canonical merge base: `ea056155182351be70bb03d23841aca55c6118ae`
- Exact parent: SPECIALIST-CONTRACT-001
  `e65cb702dfd0c2515c8c37bae6fd377315c71f83`
- Implementation commit: the focused commit containing this report
- Classification: `IMPLEMENTED_PENDING_PARENT_INTEGRATION`
- Merge/install/activation/scheduling: none

## Technical Breakout v1 Reuse

The implementation imports and reuses v1 `TechnicalPriceBar`, `true_range`,
and `cumulative_vwap_values`. V1 remains authoritative for its existing
Donchian, SMA, Bollinger, Keltner, opening-range, prior-high, volume/RVOL,
relative-strength, and event-study behavior. V2 adds prospective structure
geometry, chronology, target identity, basis admission, and common Specialist
Opinions; it does not create a second bar/ATR/VWAP framework or change v1.

## Frozen Research Contract

- Specialist/version: `TECHNICAL_STRUCTURE /
  technical-structure-research-v2`
- Structure version: `technical-structure-geometry-v2`
- Schema: `2`
- Policy fingerprint:
  `6b40ecc89cbfe5d1b3fb0c4d5b1376a4b5e9fb8e3bc96282afccf4838cbb1aa0`
- Authority: `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`
- Confidence: unavailable; no pattern probability or calibration claim
- Research timing: prospective
- Search method: one preregistered variant
- Outcome optimization: prohibited

## Implemented Structures

- Compression followed by completed range expansion.
- Breakout through a pre-known level, later retest, and separate completed hold.
- Failed bullish or bearish breakout within a frozen horizon.
- Bar-derived cumulative VWAP reclaim or loss plus completed confirmation.
- Higher-low continuation and lower-high breakdown from confirmed pivots.
- Potential and confirmed double top/bottom with explicit neckline state.
- Sparse support/resistance from caller-frozen levels or pivot clusters.
- Potential and confirmed head-and-shoulders and inverse structures.
- Instrument-level technical exhaustion from repeated failure, weaker highs,
  extreme extension/failure, or volume without price progress.

All valid structures remain visible. Conflicting structures are preserved; no
majority vote, weighted-pattern total, universal technical score, or arbiter
exists.

## Immutable Evidence And Chronology

Each bar binds symbol, economic timestamp, completion timestamp, OHLCV,
session, basis, source, evidence fingerprint, and bar identity. Confirmed
geometry uses only completed bars whose completion time is at or before
`asOf`. Pivots preserve their economic event time separately from the later
`knownAt` time created by right-side confirmation.

Structure records bind exact opportunity/setup/TradePlan targets, event time,
`knownAt`, evidence range, confirmation/invalidation state, pivots, levels,
normalized geometry, volatility/volume context, basis, session, source hashes,
policy fingerprint, identity, and tamper-evident fingerprint. Material changes
to chronology, evidence, target, basis, policy, level, pivot, or geometry
change identity.

Same-bar breakout/invalidation, retest/invalidation, VWAP confirmation,
continuation, double-extreme, and neckline sequences are reported as
`AMBIGUOUS_SAME_BAR`; intrabar order is never invented.

VWAP is identified explicitly as cumulative `BAR_DERIVED_VWAP` calculated
from completed caller-supplied bars. It is not represented as provider VWAP.
ATR uses v1 true range over the frozen completed-bar window. Break buffers,
retest tolerances, pivot prominence, level clustering, retracement, shoulder
symmetry, head prominence, extension, compression, and expansion are stored as
ATR- or range-normalized deterministic measurements rather than absolute-price
magic numbers. Equivalent scaled fixtures produce equivalent normalized
structure decisions.

## Basis And Session Admission

- One same-session raw-provider series is admitted only with verified basis,
  safe corporate-action continuity, and session-bound security identity.
- Cross-session raw geometry abstains.
- Cross-session split-adjusted or total-return-adjusted analysis requires a
  durable security identity and explicit verified basis.
- Unknown basis, unresolved identity, unsafe corporate action, malformed or
  stale bars, missing intervals, and unsupported sessions fail closed or
  abstain explicitly.
- Frozen v2 performs full evaluation only in the regular session. Premarket and
  after-hours inputs abstain because currently available evidence cannot prove
  the complete required path.

## Specialist Opinion

The common contract can emit `STRUCTURE_SUPPORTS`, `STRUCTURE_NEUTRAL`,
`STRUCTURE_CONTRADICTS`, `STRUCTURE_EXHAUSTED`, or explicit `NO_OPINION`
abstention. Unknown never becomes neutral. Evidence-family disclosure includes
only evidence actually consumed, preventing unused volume from appearing as an
independent confirmation.

## Compatibility

- SPECIALIST-CONTRACT-001 is the exact parent and common envelope.
- RESEARCH-GOV-001 focused suite: 33/33 pass; v2 exposes one preregistered
  software-validation variant and performs no outcome tuning.
- RESEARCH-DATA-002 focused suite: 24/24 pass; v2 consumes explicit basis and
  identity semantics without transforming or repairing source history.
- STAT-DATA-001 focused suite: 32/32 pass; opinion identity fields are suitable
  for a later separate immutable attachment, but no denominator is written.
- REGIME-002 focused suite: 43/43 pass; market regime remains independent.
- EXEC-QUALITY-001 focused suite: 45/45 pass; liquidity/fill quality remains
  independent.
- EVENT-SHOCK-001 focused suite: 25/25 pass; event relevance remains
  independent.
- SETUP-002 is neither imported nor modified. A successor-setup observation is
  not recast as a Technical Structure opinion.

## Hard Chew Verification

- Focused TECH-STRUCTURE tests: 50/50 pass.
- Adjacent breakout, specialist, setup, planning, observer, and outcome tests:
  245/245 pass.
- Untouched sibling focused suites: 202/202 pass.
- Full Python discovery: 2,113/2,113 pass in 258.639 seconds.
- Python compileall: pass.
- `git diff --check`: pass.
- Credential-shaped value scan: pass; no values found.
- Forbidden capability/import scan: pass.
- Existing-runtime import scan: pass; no runtime imports the new module.

The 50 focused tests use only synthetic fixtures and temporary in-memory
objects. They cover positive, negative, malformed, stale, missing, gapped,
duplicate, conflicting, out-of-order, future-bar, same-bar, basis, session,
target, tamper, policy-drift, scale-equivalence, nonmutation, authority, and
capability cases. No retrospective market example was evaluated or included;
therefore there is no retrospective result to classify and no edge claim.

The first full discovery attempt reported two existing PowerShell-test failures
because the isolated worktree lacked its expected local `.venv` path. An
ignored junction to the canonical virtual environment restored the repository's
assumed development shape. Both exact tests then passed unchanged, followed by
the clean 2,113-test full rerun. No tracked code was changed to mask them.

## Protected-Lane Proof

- Canonical checkout remained clean at
  `ea056155182351be70bb03d23841aca55c6118ae`.
- Local `master` equals `origin/master`; divergence is `0 / 0`.
- Installed manifest SHA-256 remains
  `8C211729AE78DCDAEF6BC16497E9F4C797B7FDD87B34F2AB9583FCD45AD6A329`.
- August 17 opening, Paper, SETUP-002 Pass 1, and SETUP-002 Pass 2 jobs remain
  dependency-bound and pinned to `ea056155`.
- All dependency worktrees remain clean at their recorded commits.
- No production evidence, service, scheduler, account, broker, order,
  credential, Engine Host, WPF, Paper, Shadow, or sample state was contacted or
  changed.

## Remaining Gates

This work proves deterministic detector software, not predictive edge. It does
not prove profitable patterns, calibrated probabilities, optimal thresholds,
broad corporate-action-safe history, premarket/after-hours structure, provider
collection, persistence, prospective denominator attachment, strategy value,
or execution authority.

The exact next integration gate is parent-first reconciliation after the
August 17 operational evidence is terminal. A later separately authorized task
must wire immutable prospective attachments under RESEARCH-GOV/RESEARCH-DATA/
STAT producer controls. Any runtime observation, strategy use, or authority
promotion requires a new versioned sample and independent Hard Chew proof.
