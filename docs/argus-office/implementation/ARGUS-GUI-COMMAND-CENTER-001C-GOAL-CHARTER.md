# ARGUS-GUI-COMMAND-CENTER-001C Goal Charter

## Charter Decision

`GOAL_CHARTER = REVIEWED / SEMANTIC_STOP_GATE_RESOLVED / IMPLEMENTATION_READY`

Implement the real, read-only Momentum Hunter Command Center on the isolated
001C branch so the running WPF application faithfully realizes Steven's
accepted 001B visual and semantic baseline using authoritative data only.

This charter is subordinate to the 001C directive and does not relax any Git,
truth, protected-area, visual-review, merge, or installation gate.

## Authoritative Identity

```text
IMPLEMENTATION_BRANCH = codex/ARGUS-GUI-COMMAND-CENTER-001C-PRODUCTION-INTEGRATION
IMPLEMENTATION_BASE = 9967935b93659ac496d263fecfc364a73da6d2b3
PRODUCER_001C_BEFORE = b7f6df51e9f6e08056c58b419c870f116096179c
001B_ACCEPTANCE_COMMIT = d483776327e89c7d8d7df7317c4eb5d4b71cb7cd
ACCEPTED_VISUAL_SHA256 = 22BB20149EE3D5A3A2A73336AFA34E806DEE6B14E8D5C6F3DE94F73EB6235FDA
GIT_GATE = PASS
LIFECYCLE_PRESENTATION_SEMANTIC_GATE = RESOLVED_BY_001C-B_AND_001C-C
```

The Roadmap `Now` section still centers the terminal Producer sequence. Git
preflight reconciles the local canonical head as the clean, linear, remotely
backed Producer-001A-through-001E chain and creates this separate 001C branch
from its exact head. This GUI task may consume authoritative read-only state;
it must not modify Producer behavior or claim canonical integration.

The population-semantics investigation is closed. Directive 001C-C resumes
Builder work using the 001C-B definitions below. These definitions are
presentation projections of existing authoritative machine truth; they do not
authorize a new lifecycle, Hot Universe, ranking, readiness, or execution
policy.

## Operator Outcome

At 1920 x 1080, Steven can understand within seconds:

1. what is on Radar and what is newly surfaced or changed;
2. the cross-lifecycle ranked candidates and their recent price behavior;
3. what was Accepted or Rejected, with authoritative reasons/times where
   exposed;
4. current read-only positions;
5. recent events and truthful system/data context.

Unsupported facts remain visibly unavailable. The screen must never create or
reinterpret trading truth to fill the accepted layout.

## Frozen Semantics And Visual Contract

- The accepted 001B `1920 x 1080` image is the production visual target, not
  inspiration. Deviations require an explicit category and Steven review.
- Preserve the compact header, situational summary, Radar/attention view,
  cross-lifecycle `RANKED CANDIDATES`, dedicated `ACCEPTED`, dedicated
  `REJECTED`, read-only `POSITIONS`, `WHAT CHANGED`, and `SYSTEM CONTEXT`.
- `CENTER_SURFACE_SEMANTICS = CROSS_LIFECYCLE_RANKED_CANDIDATES`.
- `RADAR`, `ACCEPTED`, and `REJECTED` use the exact frozen population semantics
  in the next section. Ranked-list presence does not change membership or
  disposition history.
- Ten primary rows target bounded two-trading-day, 15-minute microcharts.
  Accepted and Rejected retain equivalent historical context. Plot only
  source-proven observations; partial/unavailable history is explicit.
- Transition markers appear only when an authoritative transition timestamp
  exists. No fake history, candles, reasons, ranks, deltas, transitions, or
  timestamps are permitted.
- Chart color may describe displayed price-history behavior only and may not
  encode lifecycle or trading authority.
- `NEW` / `RECENT` / `SEEN` and microchart presentation are human-attention
  aids only:

```text
USER_ATTENTION_FRESHNESS != TRADING_STRATEGY_AGE
DISPLAY_MINICHART != TRADING_SIGNAL
```

Presentation concepts must be separately named and structurally incapable of
feeding ranking, score, admission, rejection, readiness, risk, sizing, entry,
exit, execution, or broker behavior.

## Resolved Population Semantics

```text
RADAR = current-session Hot Universe members whose authoritative current state is TRACKED

ACCEPTED = current-session setup dispositions whose first authoritative
           lifecycle transition reached EXECUTION_ELIGIBLE

REJECTED = current-session setup dispositions whose first authoritative
           lifecycle transition reached ENTRY_MISSED, FAILED_BREAKOUT,
           or INVALIDATED
```

Radar is current tracking state. Accepted and Rejected are current-session
setup-disposition histories. They are intentionally not three mutually
exclusive historical buckets. The center remains
`CROSS_LIFECYCLE_RANKED_CANDIDATES` and cannot redefine any population.

The Command Center must not normalize any of the following into `REJECTED`:

- `OBSERVED_REJECTED`;
- `REJECTED_FILTER`;
- `DATA_STALE`;
- `EXHAUSTION_RISK`;
- `COOLDOWN`;
- a readiness blocker alone;
- a risk result alone;
- a non-execution-eligible Producer result alone.

Disposition identity follows the machine identity:

- a successor setup is a new setup identity;
- Accepted or Rejected status from a predecessor does not automatically
  transfer to its successor;
- a Hot Universe membership that expires and is later readmitted as a new
  membership generation receives a new Radar presentation identity;
- prior setup and membership history remains historical evidence under its
  original identity;
- Candidate Lifecycle and Hot Universe policy must not change for the GUI.

## Presentation Freshness Wall

The trading-domain `Candidate.freshness_score` is not the Command Center's
human-attention freshness. It must never be reused, aliased, bridged, or used
to derive `NEW`, `RECENT`, or `SEEN`.

Presentation freshness must remain explicitly presentation-owned, using names
such as `DisplayAttentionAge`, `DisplayFreshnessLabel`,
`DisplayFreshnessState`, `DisplayFirstSurfacedAt`, and
`DisplayStateChangedAt`.

```text
DISPLAY_FRESHNESS != CANDIDATE_FRESHNESS_SCORE
```

It may not feed ranking, scoring, admission, readiness, risk, entry, exit, or
execution.

## Radar Map Boundary

`RADAR_MAP_GEOMETRY = NOT_YET_AUTHORIZED`.

The accepted Radar visual region remains in the layout, but catalyst-angle,
radial-distance, or other spatial semantics must not be invented. Until an
authoritative geometry contract exists, the region renders a truthful pending
or unavailable state. That limitation does not block Radar population/count,
Ranked Candidates, Accepted, Rejected, microcharts, Positions, What Changed,
or System Context.

## In Scope

- Inventory every required visible field before implementation and classify it
  `AVAILABLE_NOW`, `PRESENTATION_DERIVABLE`, `NEW_READ_MODEL_REQUIRED`, or
  `UNAVAILABLE`, naming its authoritative owner and provenance.
- Reuse existing WPF/AvalonDock presentation components where they serve the
  frozen macro layout; move or retire old default-pane dominance where needed.
- Add the smallest bounded read-only contracts, bridge mappings, presentation
  models, and WPF surface required to expose authoritative lifecycle,
  candidate, persisted history, chronology, position, and health facts.
- Reuse the existing canonical persisted-history authority for multi-symbol
  chart payloads when it satisfies the contract. Backend aggregation may be
  used only through a reviewed read-only boundary; WPF may never fetch,
  backfill, synthesize, or reconstruct market truth.
- Add focused tests, bounded regressions, visual-proof artifacts, task
  documentation, and exact manual-review steps required by Hard Chew.
- Maintain continuous read-model updates without stealing focus, destabilizing
  selection, or producing frantic unreadable reordering.
- Project the resolved populations from existing authoritative Hot Universe,
  setup identity, and lifecycle-transition truth without modifying their
  policies.

## Out Of Scope

- Any change to strategy, scoring, ranking authority, candidate admission,
  rejection, readiness, setup/lifecycle transition rules, risk, position
  sizing, entry, exit, execution, broker behavior, alert thresholds, replay
  identity, or historical capture-selection policy.
- Provider-authority changes, a second market-data authority, or UI calls to
  Schwab, Alpaca, RTD, Finviz, or any hidden provider/backfill path.
- Producer-001C behavioral changes, database redesign/migration, unrelated
  runtime architecture, secrets/configuration changes, service/scheduler
  mutation, or generated runtime-data mutation.
- `BUY`, `SELL`, `SUBMIT`, `CANCEL`, `REPLACE`, `ARM`, `APPROVE`, `EXECUTE`,
  or any equivalent trading/order/lifecycle-mutation control.
- Merge, install, deployment, canonical workstation replacement, Start Menu or
  startup-pointer changes.

## Read-Model Gate

The population-semantic stop gate is resolved. Before production source
changes, finish recording the authoritative source and classification for at
least:

- the exact Radar membership generation and current `TRACKED` state;
- the first qualifying lifecycle transition per setup identity for Accepted
  and Rejected current-session histories;
- ranked ordering, score, rank delta, RVOL, catalyst/context, and lifecycle;
- acceptance/rejection reasons and transition timestamps;
- bounded candidate price-history payloads and any transition markers;
- recent-event chronology;
- positions, entry, mark, P/L, stop, and target;
- system/data health and last evidence/update time;
- first-surfaced and last meaningful state-change timestamps.

No UI terminology may infer a lifecycle mapping that the machine does not own.
No unavailable field may be filled with sample, synthetic, alternate-symbol,
or presentation-inferred truth. A required backend addition is allowed only if
it is the smallest clean read-only contract needed by this Command Center and
does not change a protected semantic owner.

## Measurable Acceptance Gates

1. **Identity:** Git preflight remains `PASS`; branch/base, Producer-001C,
   acceptance commit, image hash, and protected worktrees remain exact.
2. **Contract inventory:** every visible field is classified with provenance;
   every `UNAVAILABLE` item has an honest runtime treatment and closeout note.
3. **Frozen layout:** the real default WPF surface preserves all nine frozen
   macro regions and does not restore a dominant single-symbol CandleChart.
4. **Lifecycle truth:** Radar contains current-session Hot Universe membership
   in authoritative current state `TRACKED`; Accepted uses the first
   `EXECUTION_ELIGIBLE` transition per current-session setup; Rejected uses the
   first `ENTRY_MISSED`, `FAILED_BREAKOUT`, or `INVALIDATED` transition per
   current-session setup. The center remains explicitly cross-lifecycle and
   does not redefine membership.
5. **Lifecycle exclusions and identity:** tests prove discovery-filter and
   observed rejection, stale/exhaustion/cooldown states, blockers, risk-only
   results, and non-execution-eligible Producer results do not become Command
   Center Rejected; successors remain independent; new membership generations
   receive new Radar presentation identity; prior current-session disposition
   history remains available under the original setup identity.
6. **Microcharts:** up to ten ranked rows and equivalent Accepted/Rejected
   contexts consume bounded source-proven two-session/15-minute payloads;
   missing/partial series and absent transition timestamps remain explicit;
   provenance traces to canonical persisted candles through a bounded
   read-only Engine Host multi-symbol projection.
7. **Semantic wall:** tests and code review prove that
   `DisplayFreshnessLabel`, `DisplayFreshnessState`, and
   `DisplayMiniChartSeries` have no dependency path into decision-domain
   ranking, score, admission, readiness, risk, entry, exit, or execution. No
   display freshness field references, aliases, bridges, or derives from
   `Candidate.freshness_score`.
8. **Radar-map honesty:** the frozen Radar region remains visible but renders
   pending/unavailable geometry without invented angle or distance semantics.
9. **Continuous behavior:** authoritative updates appear without manual
   refresh; selection/focus stays stable and row movement remains readable.
10. **Read-only authority:** capability and UI review finds no provider call,
   write path, order/trading control, lifecycle mutation, or execution command.
11. **Build and focused proof:** affected projects build cleanly with no new
   unexplained warnings; focused tests pass for lifecycle populations,
   cross-lifecycle ranking, chart mapping/provenance, reason/time mapping,
   freshness mapping, membership generations, successor isolation, exclusions,
   session-history retention, and unavailable states.
12. **Broader bounded proof:** relevant presentation, workspace, chart,
    candidate/TradePlan read-model, lifecycle, position, chronology, and health
    regressions pass; any shared Python/read-model change receives proportionate
    focused and bounded suite coverage.
13. **Real visual proof:** capture the running application at exact
    `1920 x 1080` as
    `ARGUS-GUI-COMMAND-CENTER-001C-overall-1920x1080.png` and produce
    `ARGUS-GUI-COMMAND-CENTER-001C-accepted-vs-implementation.png` against the
    SHA-verified baseline. Inspect native resolution for clipping, overlap,
    readability, alignment, chart errors, stale/misleading facts, missing rows,
    and contradictory lifecycle state.
14. **Difference accounting:** every material visual difference is labeled
    `RUNTIME_TRUTH_DIFFERENCE`, `TECHNICAL_CONSTRAINT`,
    `MISSING_READ_MODEL`, or `UNAUTHORIZED_DESIGN_DRIFT`; the last category
    must be empty.
15. **Independent review:** a second eye passes visual fidelity, lifecycle
    semantics, presentation/trading separation, chart-data provenance, and
    chronology semantics after narrow findings are resolved.
16. **Final audit:** exact diff, parentage, protected paths, secrets,
    generated-data status, and canonical/Producer/install/startup nonmutation
    are recorded. Required Roadmap, Verification Queue, and release evidence
    reflect branch-only truth.
17. **Delivery:** only a proven isolated-branch commit and normal non-force
    branch push may occur. `MERGE_AUTHORIZED = NO` and
    `INSTALL_AUTHORIZED = NO` remain unchanged.

Steven's physical visual review remains required after automated and
independent proof. Before that decision the branch may be described only as
implemented and ready for runtime visual review, never visually accepted or
complete in canonical production.

## Stop Conditions

Stop and report the exact dependency or mismatch if:

- the accepted image hash, branch/commit identity, canonical reconciliation,
  Producer-001C identity, or worktree cleanliness becomes unexplained;
- the implementation cannot project the exact resolved population and identity
  semantics without changing Candidate Lifecycle or Hot Universe policy;
- chart history would require UI-side provider access, synthetic candles, or a
  second market-data authority;
- implementation requires changing trading/Producer logic or a protected
  semantic owner;
- freshness or chart presentation cannot be isolated structurally from
  decision logic;
- visual fidelity requires fabricated runtime truth;
- a major unrelated architectural, schema, provider, runtime, service,
  scheduler, configuration, secret, broker, account, or order change is needed;
- unrelated files change unexpectedly, or a required build, test, security,
  secret, protected-path, provenance, visual, or nonmutation check fails and
  cannot be repaired narrowly inside scope;
- completion would require merge, install, deployment, Start Menu/startup
  mutation, destructive Git, or any real order action.

## Required Terminal Classification

```text
PRODUCTION_IMPLEMENTATION_COMPLETE = YES / NO
READ_MODEL_CONTRACT_COMPLETE = YES / NO
MICROCHART_INTEGRATION_COMPLETE = YES / NO
LIFECYCLE_PRESENTATION_SEMANTICS_PROVEN = YES / NO
PRESENTATION_TRADING_SEPARATION_PROVEN = YES / NO
HARD_CHEW_COMPLETE = YES / NO
READY_FOR_STEVEN_RUNTIME_VISUAL_REVIEW = YES / NO

MERGE_AUTHORIZED = NO
INSTALL_AUTHORIZED = NO
```

## Goal Steward Review

- [x] The accepted 001B image and semantic decision are the frozen target.
- [x] Lifecycle populations and cross-lifecycle display semantics are distinct.
- [x] The 001C-B/001C-C population-semantic stop gate is resolved with exact
      lifecycle transitions, exclusions, successor, and readmission rules.
- [x] Read-model inventory and no-fabrication gates precede source changes.
- [x] Bounded read-only integration is authorized without trading authority.
- [x] Microchart provenance and presentation/trading isolation are testable.
- [x] `Candidate.freshness_score` is excluded from display freshness by an
      explicit ownership wall.
- [x] Radar-map geometry remains unavailable without blocking the truthful
      Command Center regions.
- [x] Hard Chew includes build, focused/broader tests, real-app visual proof,
      native sanity, scope/security review, and independent second-eye review.
- [x] Steven retains final visual acceptance authority.
- [x] Merge and installation remain explicitly unauthorized.

The semantic investigation is complete and Builder work may resume. The
remaining inventory records source ownership and field availability; it does
not reopen the frozen product-semantic decision. If the exact projections
cannot be implemented within these boundaries, the correct result is a
documented stop, not invented truth or expanded authority.
