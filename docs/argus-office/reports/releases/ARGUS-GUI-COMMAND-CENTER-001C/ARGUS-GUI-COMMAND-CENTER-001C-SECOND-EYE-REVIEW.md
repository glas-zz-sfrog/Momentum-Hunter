# ARGUS-GUI-COMMAND-CENTER-001C Independent Second-Eye Review

## Decision

```text
SECOND_EYE_REVIEW = PASS
VISUAL_MACRO_FIDELITY = PASS
LIFECYCLE_POPULATION_RULES = PASS
LIFECYCLE_IDENTITY_CONTRACT = PASS
CHART_PROVENANCE = PASS
FRESHNESS_SEPARATION = PASS
PRESENTATION_TRADING_SEPARATION = PASS
CHRONOLOGY_PRESENTATION = PASS
NO_FABRICATED_VISIBLE_FACTS = PASS
PROTECTED_PATH_CONTAINMENT = PASS
READY_FOR_STEVEN_RUNTIME_VISUAL_REVIEW = YES
```

The corrected isolated-v3 proof preserves the accepted 001B macro hierarchy
and truthfully shows the observed partial runtime state. Independent re-review
confirms that all three bounded defects from the initial review were repaired
without changing Candidate Lifecycle, Hot Universe, ranking, readiness, risk,
broker, order, or execution policy. The branch is ready for Steven's exact
runtime visual review; it is not yet visually accepted, merge-authorized, or
install-authorized.

## Final Re-review Evidence

- Hot Universe transition events now carry an empty lifecycle `OpportunityId`,
  exact `RadarMemberIdentity`, and separately named
  `DerivedLifecycleOpportunityId`. Python and C# mapping tests assert that the
  membership and derived opportunity identities differ.
- `WHAT CHANGED` now reserves chronology capacity for authoritative lifecycle
  events, excludes periodic Engine Host housekeeping, deduplicates remaining
  workspace summaries, and records generic background status with an empty
  symbol. The replacement proof shows three stable `SYSTEM` availability rows
  after multiple refresh cycles and no polling flood.
- Ranked score is nullable from Python through the C# contract and presentation.
  Missing or invalid source score sets ranked coverage `PARTIAL`, adds an exact
  limitation, and renders `—`; it is never converted to numeric zero.
- Replacement artifacts were inspected at native resolution. The required
  overall proof is `1920x1080`; the side-by-side comparison is `3840x1140`.
  Their SHA-256 values exactly match the updated Hard Chew evidence.

## Original Findings — Resolved

### 1. Hot Universe membership identity is serialized as a lifecycle opportunity ID

`momentum_hunter/workstation_read_models.py:515-529` serializes Hot Universe
transition rows into the shared lifecycle-event DTO and assigns
`transition.member_id` to the wire field `opportunityId`. The C# contract keeps
that field explicitly named `OpportunityId`
(`src/MomentumHunter.Contracts/WorkstationContracts.cs:553-562`).

This contradicts the corrected 001C-C boundary: `HotUniverseMember.member_id`
is a membership-generation identity and must never equal, substitute for, or
be presented as `CandidateLifecycleEvent.opportunity_id`. The current WPF row
does not print the value, but the v3 read-model contract is still semantically
false and permits a future consumer to treat a membership ID as lifecycle
identity.

Required fix: represent exact source identity without overloading the field.
The smallest correction is to add a source-appropriate membership identity
field (or a discriminated source identity) and leave lifecycle opportunity ID
empty for `HOT_UNIVERSE` rows. If a derived lifecycle opportunity is needed,
name it explicitly as derived and keep the exact `member_id` separately. Add a
mapper test proving the two identities cannot be substituted.

**Resolution: PASS.** The wire and C# contracts now preserve the three concepts
separately, and focused Python/mapper tests prove the non-substitution rule.

### 2. `WHAT CHANGED` is flooded by polling activity and misattributes it to a symbol

The native 1920x1080 proof visibly contains repeated five-second rows such as
`CRWD / Monitoring / Refreshed Python Engine Host status.`. The host polling
service emits that message on every refresh
(`RemoteBackgroundCollectionService.cs:164-174`), while
`ShellViewModel.cs:2700-2706` merges all workspace activity with authoritative
lifecycle events, orders the combined stream, and takes only 18. The existing
background-activity adapter associates monitoring activity with the selected
symbol, so host housekeeping appears to be CRWD-specific evidence.

This is not meaningful chronology and can displace the actual lifecycle/Hot
Universe changes the panel exists to show. It also makes a generic host poll
look like symbol evidence.

Required fix: keep periodic host-refresh housekeeping in System Context, or
filter/deduplicate it before the `WHAT CHANGED` projection. Never attach a
generic host refresh to the selected symbol. Preserve exact lifecycle and Hot
Universe event order and add a regression test showing repeated polls cannot
displace or masquerade as symbol lifecycle events.

**Resolution: PASS.** The new projection gives lifecycle events first capacity,
filters host housekeeping, deduplicates summaries, and removes selected-symbol
attribution from background activity. A 25-poll regression and the replacement
multi-cycle proof both pass.

### 3. Missing/invalid source score becomes a visible numeric zero

`momentum_hunter/workstation_read_models.py:697-720` maps a missing or invalid
`composite_score` to `0`. The C# mapper repeats the fallback and the contract
uses non-null `int Score`, so the UI cannot distinguish a factual source score
of zero from unavailable source evidence.

That violates the no-fabrication gate. The Command Center may display a source
score or an explicit unavailable value; it may not manufacture a numeric score.

Required fix: preserve score absence through a nullable/read-model state and
render an em dash or explicit unavailable label, or fail that ranked row/source
coverage closed. Do not recalculate score. Add malformed/missing-score mapping
tests at both Python and C# boundaries.

**Resolution: PASS.** Missing/invalid score remains null, ranked source coverage
becomes `PARTIAL`, the limitation is explicit, and presentation renders `—`.
Python, C# mapper, and presentation tests cover the boundary.

## Passing Review Areas

- **Visual fidelity:** The isolated-v3 native proof retains the compact global
  header, five summary cards, Radar region, cross-lifecycle ranked center,
  separate Accepted/Rejected panels, What Changed, read-only positions, and
  System Context. Empty panels and changed counts are truthful runtime-data
  differences, not unauthorized design drift.
- **Radar geometry:** The accepted region remains visible and states
  `GEOMETRY PENDING` / `NOT YET AUTHORIZED`; no symbol angle or radius is
  invented.
- **Lifecycle populations:** The Python projection uses current-session
  `TRACKED` Hot Universe membership, filters to
  `CONTINUOUS_HOT_UNIVERSE`, derives and validates opportunity identity, and
  retains the first setup transition to `EXECUTION_ELIGIBLE` or the authorized
  terminal states. The focused tests prove exclusions, successors, readmission,
  missing lifecycle evidence, wrong-family evidence, unmatched opportunities,
  and producer contradiction behavior.
- **Chart provenance:** Command Center charts are bounded to two source
  sessions, 15-minute persisted candle snapshots, and explicit
  partial/unavailable states. The production workspace projection constructs a
  chart reader with `backfill_coordinator=None`; WPF renders supplied points and
  does not fetch, aggregate, interpolate, rank, or score. Line color depends
  only on displayed first/last close. Transition markers use the exact supplied
  disposition timestamp.
- **Freshness wall:** Display freshness is derived only from factual surfaced
  or state-change timestamps in `CommandCenterModels.cs`. The reviewed v3
  projection does not consume `Candidate.freshness_score`, and source rank is
  preserved independently of chart shape or the display clock.
- **Trading-authority wall:** The new flow is persisted evidence to Python
  read-only projection to v3 mapper to presentation. No Command Center control
  exposes provider, lifecycle mutation, broker, order, entry, exit, approval,
  or execution capability. Shadow positions remain labelled FakeBroker/read
  only.
- **Protected paths:** The branch diff does not modify Candidate Lifecycle, Hot
  Universe, scoring, readiness, risk, broker/order execution, replay identity,
  database/migration, or secrets. The explicit Continuous runtime path is a
  bounded read-only dependency addition.

## Visual Difference Accounting

| Observed difference | Classification | Review |
| --- | --- | --- |
| Radar `15`; Accepted/Rejected unavailable; no ranked rows | `RUNTIME_TRUTH_DIFFERENCE` | Correct fail-closed presentation for the captured evidence set. |
| Radar nodes absent | `MISSING_READ_MODEL` | Correctly represented as geometry pending. |
| Empty Accepted/Rejected/chart regions | `RUNTIME_TRUTH_DIFFERENCE` | Honest, not populated with design-proof examples. |
| Periodic monitoring-refresh rows absent from What Changed after multiple cycles | `TECHNICAL_CORRECTION` | Verified; three deduplicated `SYSTEM` source-availability summaries remain. |
| Other macro layout differences | None material | No blocking unauthorized layout drift found. |

## Checks Run

- Inspected the complete current working-tree name/status and changed-file set.
- Inspected the isolated-v3 1920x1080 proof and both accepted-versus-runtime
  comparison artifacts at native source resolution.
- Reviewed Python v3 population/chart projection, Engine Host path, C# mapper
  and contracts, presentation projections, XAML, microchart renderer, refresh
  path, and focused tests.
- `python -m unittest tests.test_command_center_read_model -v` using local
  Python 3.12: **10 passed**.
- Focused Presentation tests: **22 passed**.
- Focused Integration tests: **11 passed**.
- `git diff --check`: **passed**.
- Protected-path filename scan: no changed protected decision-owner file.

The new focused tests directly assert source-typed event identity,
polling-noise exclusion/non-displacement, generic background scope, nullable
score mapping, partial coverage, and unavailable score rendering.

## Re-review Completion

1. Focused Python, mapper, presentation, layout, and integration tests passed.
2. The required negative tests were added and passed.
3. The isolated native proof was recaptured after multiple refresh cycles.
4. The accepted-versus-implementation comparison was regenerated and inspected.
5. Hard Chew records `UNAUTHORIZED_DESIGN_DRIFT: NONE` and correct
   `RUNTIME_TRUTH_DIFFERENCE`, `MISSING_READ_MODEL`, and
   `TECHNICAL_CONSTRAINT` classifications.

## Agent Report

- **Branch:** `codex/ARGUS-GUI-COMMAND-CENTER-001C-PRODUCTION-INTEGRATION`
- **Scope:** Independent read-only source/diff and visual-proof review.
- **Files changed by reviewer:** This review artifact only.
- **Evidence:** Source citations, native proof comparison, and test results above.
- **Protected areas reviewed:** lifecycle/hot-universe identity boundary,
  ranking/freshness/chart authority, provider/backfill path, broker/order/trading
  surface, runtime path, and changed-file containment.
- **Push/merge status:** No commit, push, merge, install, or deployment.
- **Risks:** The captured runtime legitimately lacks Candidate Lifecycle and
  ranked-report evidence, so Accepted/Rejected/ranked/chart visual population
  remains unexercised in the real proof. Automated populated-state coverage
  passes; Steven still owns final visual acceptance.
- **Manual QA:** Ready for Steven's exact native 1920x1080 visual review. This
  PASS is independent technical review, not Steven acceptance.
- **Open questions:** None for the second-eye gate. Roadmap and Verification
  Queue still carry the pre-re-review pending-repair wording and should be
  reconciled by the owning release/report role after this PASS.
- **Recommendation:** Advance to Steven runtime visual review with the updated
  proof. Keep merge and installation unauthorized until the remaining gates
  and Steven's visual decision are recorded.
