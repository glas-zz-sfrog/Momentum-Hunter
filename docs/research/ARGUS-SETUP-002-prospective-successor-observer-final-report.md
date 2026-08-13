# ARGUS-SETUP-002 Prospective Successor-Setup Observer Final Report

## Classification

`IMPLEMENTED_PENDING_MERGE_AND_ACTIVATION_GATE`

Implementation is complete on a separate stacked feature branch. The observer
is not installed or scheduled, and the prospective sample remains empty.

## Starting Truth

- Canonical checkout: clean `master` at
  `a9821ed08d5be91a10cbeb0151bb3d6bd3f028b5`.
- `origin/master`: the same commit; ahead/behind `0/0`.
- SETUP-001: unmerged, remote-backed feature branch with implementation
  `6919b03` and governance closeout `1bfb4d2`.
- SETUP-002: implementation commit `a676cd6`, remote-backed and stacked on
  `1bfb4d2` in a distinct LocalAppData worktree.
- Installed Automation Service: running from the canonical checkout.
- August 14: 05:55 and 06:05 Schwab tasks remain Ready; the 08:35 opening and
  dependent Paper jobs remain Pending on canonical `a9821ed`.

## Frozen Sample

- Sample ID: `successor-setup-research-20260813-v1`.
- Policy fingerprint:
  `C2A214A12E6BE8A42BC868AD3A4F90998721F5DE652FB748012546170C95B943`.
- Initial denominator: 0 sessions, 0 candidates.
- SETUP-001 treatment: case study/hypothesis generation, excluded from the
  prospective denominator.
- Review checkpoints: 25, 50, and 100 fully evaluated candidates, with distinct
  session count and no tuning or claim of edge.

Frozen rules retain the existing 0.25% maximum extension, 1.5 minimum
execution-adjusted reward/risk, DATA-003/004 missed-entry and successor identity,
09:35 ET decision cutoff, 15:55 ET outcome horizon, canonical rank priority,
five-candidate provider bound, and unchanged production strategy semantics.

## Prospective Fields

Every denominator row preserves symbol, rank, baseline admission, original
setup/fingerprint/trigger/lifecycle, production TradePlan status/blockers, and
sanitized Paper evaluation/classification where supplied. Excluded rows remain
visible as `NOT_EVALUATED_PROVIDER_BOUND`.

Fully evaluated rows preserve canonical candle identities and cutoff hash,
earliest trusted bar, explicit `UNOBSERVED` 04:00-07:00 path, source/data basis,
prior close/high/low, ATR, trusted premarket OHLCV and bar-derived VWAP, first
known original cross, completed 09:15-09:29 structure, completed 09:30-09:34
opening range, decision quote provenance, broad-market agreement, and raw
verticality/pullback/compression covariates.

## Model Semantics

- Model A: current/original level only; preserved as the production comparison,
  never promoted into a successor merely because price moved.
- Model B: the completed prior 15-minute structure as a dominant local feature;
  visibly marked as a comparison that does not independently prove chronology.
- Model C: full trusted premarket chronology, prior 15-minute structure, and
  completed opening range.

Successors may be `CONTINUATION_BREAKOUT`, `RECLAIM`, or `PULLBACK`. Each has a
new setup ID, predecessor ID/relationship, trigger, structural stop, two-R
target, execution R/R, extension from its own trigger, evidence chronology,
engine version, and policy fingerprint. A missed original is immutable.

## Pass 1 Contract

Pass 1 is write-once and outcome-blind. It contains only completed bars before
09:35 ET, preserves all candidates, records unavailable windows as abstentions,
and labels every opinion `RESEARCH_ONLY / EXECUTION_AUTHORITY = NONE`. Exact
duplicate generation is idempotent; a conflicting output fails closed.

The packet and every fully evaluated candidate have deterministic fingerprints.
Post-cutoff bar values and identities are absent. A late reconstruction may
read an existing source container but hashes and evaluates only the explicit
cutoff subset.

## Pass 2 Contract

Pass 2 accepts a valid immutable Pass 1 and revalidates that every cutoff candle
is unchanged. It may classify `UNTRIGGERED`, `TARGET_FIRST`, `STOP_FIRST`,
`TIMEOUT`, `INVALIDATED`, `AMBIGUOUS_SAME_BAR`, or `DATA_FAILURE`. It does not
guess intrabar order from one-minute OHLC. MFE, MAE, and their timing end at the
first terminal event. A pending trigger or blocked-candidate counterfactual
cannot be finalized from a partial day: absence of the 15:55 ET horizon becomes
`DATA_FAILURE`. Ambiguous same-bar excursions remain unavailable rather than
implying an unknowable price chronology.

Candidates blocked or abstained in Pass 1 remain non-trades. Later behavior is
stored only as `POST_DECISION_COUNTERFACTUAL_OBSERVATION_NOT_A_TRADE` and cannot
change the frozen decision.

## Anti-Hindsight Guarantees

- Candidate selection comes only from the immutable opening report and rank.
- Every candidate remains in the denominator regardless of later outcome.
- Only `< 09:35 ET` bars enter Pass 1.
- Pass 1 and per-candidate fingerprints detect alteration.
- Pass 2 rejects changed cutoff evidence.
- Later rallies cannot create a frozen setup or alter a block.
- SETUP-001 observations never enter the prospective counts.
- No strategy parameter is tuned during the sample.

## Dormant Unattended Architecture

The code can emit a plan with the future sequence `opening terminal -> Pass 1 ->
after close -> Pass 2`, finite 10/15-minute timeouts, and zero retries. That plan
is explicitly `NOT_INSTALLED`, `activationAuthorized: false`, and states that a
research failure cannot change opening or Paper status.

No scheduler/service installation occurred. Activation requires terminal and
preserved August 14 evidence, current-head reconciliation, a distinct research
output root, exact runtime pin, and separate proof that the research job cannot
block production.

## Verification

- Compileall: PASS.
- Focused SETUP-002: 25/25 PASS.
- Combined SETUP-001/002: 37/37 PASS.
- DATA-003/004, candle readiness/backfill/collector, continuous-plan regression:
  134/134 PASS.
- Full Python discovery: 1,961/1,961 PASS in 275.035 seconds.
- Source nonmutation: PASS in focused fixtures.
- Same-bar ambiguity, cutoff leak, omitted loser, later-rally rewrite, missing
  premarket/opening, tampered identity/cutoff, wrong symbol/date, altered Pass 1,
  duplicate/conflicting writes, and research-failure isolation: PASS.

## Protected Boundary

Changed runtime code is one new offline research module. No existing scoring,
ranking, readiness, catalyst authority, TradePlan semantics, Risk Governor,
allocation, Paper, Shadow, broker/order, service, scheduler, provider client,
database/schema, WPF/UI, credential, production configuration, or production
data-store file changed.

The module has no network, provider-fetch, account, position, preview, order,
broker, service, scheduler, Shadow, or Paper mutation capability. It reads only
caller-supplied evidence paths and writes only caller-supplied output paths.

## Remaining Limitation And Gate

The current authoritative Schwab research history normally starts near 07:00
ET. SETUP-002 therefore records the true 04:00-07:00 path as `UNOBSERVED`; it
does not fill that gap from another provider or infer earlier chronology.

The next gate is terminal preservation of the August 14 05:55/06:05 Schwab,
08:35 opening, and dependent Paper evidence. After that, reconcile both stacked
research branches against current canonical truth. Integration may proceed only
after a clean compatibility review; unattended activation remains a separate
consequential task.
