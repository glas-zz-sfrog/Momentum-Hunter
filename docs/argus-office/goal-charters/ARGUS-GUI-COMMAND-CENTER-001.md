# Goal Charter: ARGUS-GUI-COMMAND-CENTER-001

## Charter Status

`REVIEWED / IMPLEMENTATION_READY_AFTER_INVENTORY_AND_PHYSICAL_BASELINE_PROOF`

- Task branch: `codex/ARGUS-GUI-COMMAND-CENTER-001`
- Isolated task worktree:
  `C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-GUI-COMMAND-CENTER-001`
- Canonical creation point:
  `82460b3313b86c34dff4ffb737d2c04bf02e3ace`
- Frozen canary branch:
  `codex/ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001C`
- Frozen canary head:
  `b7f6df51e9f6e08056c58b419c870f116096179c`
- Git preflight:
  `docs/argus-office/implementation/ARGUS-GUI-COMMAND-CENTER-001-GIT-PREFLIGHT.md`
  with `GIT_PREFLIGHT = PASS`
- Required terminal state:
  `GUI_IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE_AND_POST_CANARY_MERGE`

This charter authorizes the Builder to implement the bounded GUI slice only
after the current-GUI inventory/reuse map and the read-only pre-implementation
physical boundary snapshot described below exist. It does not authorize a
merge, installation, Start Menu or startup-pointer change, runtime deployment,
service or scheduler action, canary interference, or any expansion into a
protected backend surface.

## Authority Reconciliation

The canonical Roadmap `Now` section at the creation point still names
`ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001A` and describes a provider-backed
canary as the next gate. Steven's newer explicit directive freezes
Producer-001C at `b7f6df51e9f6e08056c58b419c870f116096179c`. The Git preflight
independently proves that the local and remote Producer-001C branch and its
dedicated worktree match that identity, while the GUI task branch was created
from clean synchronized canonical `82460b3313b86c34dff4ffb737d2c04bf02e3ace`
and is not stacked on a Producer branch.

For this task, the newer explicit directive plus exact Git evidence defines the
active frozen boundary. The lagging Roadmap text is a governance reconciliation
item, not authority to touch Producer-001C and not a reason to rewrite canary
history. Release Scribe must update branch-local closeout records from actual
evidence without claiming the GUI is merged, installed, or visually accepted.

## Goal Statement

Implement one coherent, read-only Momentum Hunter Command Center in the
isolated WPF workstation so Steven can understand what matters now, why a
symbol is interesting, whether Momentum Hunter would trade it, why or why not,
what changed, what historical context exists, what Momentum Hunter believed
earlier, what happened afterward where evidence exists, whether a blocker is
strategic or evidentiary, and which current positions require attention.

The implementation must organize existing authoritative read models. It must
not create, infer, repair, or change engine truth.

## User Pain / Operator Outcome

The current workstation exposes useful capabilities, but the operator must
mentally join independent panes and reread full evidence to answer basic
decision questions. The resulting Command Center should feel like one operating
surface centered on the selected ticker, with the default information priority:

1. answer;
2. reason;
3. change;
4. market context;
5. evidence detail;
6. raw diagnostics.

Steven should be able to distinguish instantly between a symbol that is not a
trade and a symbol that Momentum Hunter cannot currently evaluate. Technical
identifiers, hashes, fingerprints, internal task names, and low-level provider
diagnostics remain secondary drill-down evidence.

## In Scope

- Inspect the current GUI before implementation and classify the existing
  candidate/Hunter/Live Universe, chart, TradePlan, Risk Governor, Positions,
  History/Activity, Why/evidence, Research Maturity, command-palette,
  health/status, workspace, and docking capabilities as `KEEP`, `MOVE`,
  `COMBINE`, `RETIRE_FROM_DEFAULT_LAYOUT`, or `NEW`.
- Reuse suitable existing panes, view models, chart rendering, workspace and
  docking behavior, read-only Positions capability, command-palette behavior,
  and health/evidence presentation instead of duplicating them.
- Implement the Command Center's four primary visual zones:
  1. Live Universe / Attention List;
  2. Focus Candidate / Market Story;
  3. Decision / Why / Evidence;
  4. What Changed / Decision Timeline.
- Present opportunity state separately from evidence state in both the
  attention list and selected-symbol decision context.
- Present current decision values only when supplied by existing authoritative
  snapshots, including entry, stop, targets, readiness, blocker, setup type,
  evidence freshness, RVOL, and market context where available.
- Use existing read-only candle/history data to show honest pre-discovery
  context. Finer recent, coarser older, and Daily context may be selected only
  when the current read model already provides it; this task does not define a
  new aggregation or capture policy.
- Build a concise chronological What Changed surface from existing immutable
  evidence and deterministic, presentation-only comparison of exposed
  snapshots. Unsupported chronology or fields must be labeled unavailable.
- Allow navigation to an earlier frozen decision/evidence context where the
  current read models expose stable historical identity. Keep the selected
  historical decision visibly distinct from the current decision.
- Make `Why now?`, `Why trade / why not?`, `What changed?`, and `What happened?`
  available directly or through one compact expansion.
- Show compact high-level system health with secondary drill-down into only the
  already exposed quote/history, discovery, candle, clock, historical-context,
  freshness, and relevant service status.
- Preserve read-only Positions access for position, mark, unrealized P/L, R,
  stop, next target, lifecycle state, freshness, and source where the current
  read model provides them.
- Preserve visually distinct accepted, rejected, missed, watched, developing,
  blocked, and unavailable states without relying on color alone.
- Add deterministic UI-only age/freshness formatting and compact historical
  visualization only when based on existing read-model fields. These are visual
  awareness aids and have no analytical or execution authority.
- Add or update WPF/operator-surface code, GUI-specific presentation code,
  GUI-specific .NET tests, visual assets, screenshots, and task documentation
  needed for this slice.

## Allowed Change Boundary

The default allowed production paths are:

- `src/MomentumHunter.Desktop.Wpf/**`;
- `src/MomentumHunter.Presentation/**`.

The default allowed supporting paths are:

- GUI-focused files under `tests-dotnet/**` that verify WPF, presentation,
  layout, workspace, binding, resizing, or read-only shell behavior;
- GUI visual assets under the WPF project or task-specific visual-proof docs;
- task-specific files under `docs/argus-office/**`.

This is a semantic boundary, not permission to edit every file under an allowed
directory. Package/dependency/project-file changes are not authorized. A need
to change a path outside this boundary, including a contract or bridge merely
to expose more data, is a dependency to report and a stop condition. The GUI
must instead render an honest unavailable/limited state during this frozen
task.

## Out Of Scope

- Any file or behavior under `momentum_hunter/**` or any other Python engine,
  runtime, collection, persistence, or provider path.
- Continuous runtime, Continuous product source, candidate admission,
  lifecycle/setup logic, TradePlan production, scoring, ranking, readiness,
  risk, candle collection, historical capture or aggregation policy, and
  strategy semantics.
- Any shared runtime DTO, wire, host, application, engine-bridge, or persisted
  contract semantic change, including changes under
  `src/MomentumHunter.Contracts/**`, `src/MomentumHunter.Application/**`, or
  `src/MomentumHunter.EngineBridge/**`.
- Automation Service, Continuous Service, installed Engine Host, service
  manifests, scheduler/jobs, shared configuration, provider configuration,
  Schwab, Finviz, account binding, broker, order, position mutation, Paper,
  Shadow, FakeBroker, or exit-policy changes.
- A new data provider, network call, runtime command, evidence writer,
  retrospective market-data reconstruction, official delta computation,
  TradePlan inference, setup identity creation, or score/readiness calculation
  in WPF.
- Trading controls of any kind, including buy, sell, submit, replace, cancel,
  arm, advance, approve-for-execution, or order buttons/commands.
- Database/schema/migration, package/dependency, project/package file, secret,
  API key, OAuth, environment, production configuration, generated runtime
  data, installed binary, or shared-manifest changes.
- Editing, rebasing, merging into, repinning, restarting, observing through a
  mutating mechanism, or otherwise interfering with Producer-001C, its product
  source, observer, scheduler, evidence root, configuration, or acceptance
  criteria.
- Merge into canonical `master`; merge into any Producer branch; installation
  as the canonical workstation; Start Menu/startup pointer changes; runtime or
  service deployment during this task.

## Protected Areas And Interruption Conditions

The following protected areas are explicitly reviewed but not authorized for
change: scoring, trade readiness, candidate admission, lifecycle and setup
identity, immutable decision/replay identity, historical capture selection,
TradePlan semantics, risk, exit policy, database/schema, runtime behavior,
service/scheduler/manifest/configuration, secrets, provider/account state,
Paper/Shadow, broker/order capability, and the frozen Producer-001C evidence
campaign.

Stop before making a change and report the exact dependency if:

- any requested field requires a Python, Continuous, DTO, bridge, contract,
  provider, service, scheduler, configuration, Paper, Shadow, broker, account,
  order, or shared persistence change;
- existing read models cannot support an intended horizon, chronology, prior
  decision, health field, position field, or delta without inventing truth;
- the task branch/worktree identity differs from the Git preflight;
- Producer-001C is not at the frozen identity or another expected boundary
  invariant differs from the captured baseline;
- the opening runtime is not `APPROVED_RUNTIME_MATCH`;
- an unrelated file changes unexpectedly;
- a build, test, binding check, screenshot sanity check, protected-path review,
  secret scan, no-live-capability check, or nonmutation check fails and cannot
  be repaired narrowly inside the authorized GUI result;
- completion would require merge, install, Start Menu/startup change, service or
  scheduler mutation, canary restart/interference, destructive Git action,
  real order behavior, secret action, database migration, or any broader
  authorization.

An unsupported UI feature is not permission to expand the backend. Preserve the
shell, label the limitation honestly, and record the future read-model need.

## Acceptance Criteria

### A. Inventory And Reuse

1. Before WPF modification, a written inventory maps every requested current
   capability to `KEEP`, `MOVE`, `COMBINE`, `RETIRE_FROM_DEFAULT_LAYOUT`, or
   `NEW`, naming the concrete existing pane/view/view-model where applicable.
2. The final implementation reuses the current GUI's useful chart, read-only
   Positions, workspace/docking, activity/evidence, health, command-palette,
   and related presentation capabilities where the inventory finds them fit.
   Any new pane has an explicit non-duplication rationale.

### B. Four-Zone Command Center

3. The default Command Center is one coherent selected-ticker surface with a
   recognizable left/equivalent attention zone, center/equivalent market-story
   zone, right/equivalent decision zone, and bottom/equivalent change-history
   zone. The direction may adapt to the existing docking architecture, but all
   four operator purposes remain visible and coordinated.
4. Selecting a Live Universe item updates the linked Focus Candidate,
   Decision/Why/Evidence, and What Changed contexts without creating a trade,
   mutating evidence, or overwriting pinned/immutable historical context.
5. The default hierarchy presents answer, reason, change, and market context
   before low-level evidence and diagnostics. Internal project identifiers,
   hashes, and fingerprints do not dominate the primary surface.

### C. Live Universe / Attention

6. Each attention row shows symbol and the highest-value available context:
   rank/priority, separate opportunity and evidence states, price/change,
   catalyst age/type, UI freshness, compact movement, and accepted/rejected/
   watch/missed/setup treatment. Fields absent from the current read model are
   omitted or labeled unavailable rather than synthesized.
7. UI age/freshness such as `7m` is presentation-only. Automated tests prove it
   is not an input to admission, rank, readiness, risk, timing, or execution.
8. State treatment is understandable without color alone and remains readable
   for accepted, rejected, missed, watched, developing, blocked, and unavailable
   cases.

### D. Focus Candidate / Historical Context

9. The selected symbol and chart are the center of gravity and do not imply
   that market history began at discovery. Existing pre-discovery history is
   visible when supplied by the read model.
10. Horizon/resolution labels accurately describe the data actually rendered.
    Missing finer recent, coarser older, or Daily context is presented as a
    current read-model limitation; WPF does not invent aggregation, backfill,
    candles, or retrospective truth.
11. Any mini-chart/sparkline uses one documented, consistent UI horizon and
    fidelity for comparable rows, draws only existing data, and remains a
    nonauthoritative visualization.

### E. Decision / Why / Evidence

12. The current Decision panel displays the exact existing canonical state or
    a truthful operator label mapped without semantic invention. When exposed,
    entry, stop, Target 1, Target 2, readiness, blocker, setup type, evidence
    freshness, RVOL, and market context are shown without WPF fallback values.
13. Opportunity state and evidence state are separate, independently labeled,
    and covered by tests for at least these materially different cases:
    `MISSED ENTRY / READY`, `UNKNOWN / HISTORY LOADING`, and
    `RECLAIM READY / QUOTE STALE`, using existing/synthetic read-only fixtures
    solely for presentation proof.
14. The UI never collapses strategy rejection and missing/bad system evidence
    into a generic `NO TRADE`.
15. `Why now?`, `Why trade / why not?`, and the decisive blocker/reason are one
    click or one compact expansion away. Detailed evidence and raw diagnostics
    remain secondary.

### F. What Changed And Immutable Decision History

16. The What Changed zone is a first-class concise chronological stream that
    displays exposed changes such as price, RVOL, setup state, evidence
    readiness, missed breakout, developing/confirmed reclaim, blocker,
    catalyst, TradePlan identity, or an explicitly unchanged prior decision.
17. Every displayed timestamp, transition, and identity is traceable to an
    existing read-model field or a deterministic presentation-only comparison
    of successive exposed immutable snapshots. No fabricated chronology is
    permitted.
18. If the read model lacks complete chronology, the timeline shell remains
    useful, explicitly marks unavailable fields/intervals, and the final report
    classifies the result `PARTIAL` with the exact missing backend read-model
    requirement. Lack of data does not authorize backend work.
19. Where stable historical decision identity and its frozen context are
    exposed, selecting a prior event navigates independently of the current
    decision and visibly labels historical versus current state. A successor
    TradePlan never rewrites or masquerades as its missed/rejected predecessor.
20. Where frozen historical context is not exposed, navigation is disabled or
    limited honestly, never reconstructed in WPF, and reported as `PARTIAL`
    with the exact limitation.

### G. Health And Positions

21. The default surface shows compact `DATA HEALTHY`, `PARTIAL`, `DEGRADED`, or
    `UNAVAILABLE`-style health derived only from existing statuses, with a
    restrained drill-down for already exposed quote/history, discovery,
    candle, clock, historical-context, provider-freshness, and service state.
22. Health does not become a wall of infrastructure badges and does not trigger
    provider, service, scheduler, runtime, or recovery actions.
23. Positions remain obviously accessible and read-only. Where available, the
    view shows symbol/position, mark, unrealized P/L, R, stop, next target,
    lifecycle state, freshness, and source.
24. No trading, order, mutation, arm, or lifecycle-advance control or command is
    present anywhere in the Command Center or Positions path. The surface makes
    no claim of execution authority.

### H. Layout, Resizing, And Visual Proof

25. The Command Center remains usable at a normal workstation size and a
    materially narrower/smaller window. Proof includes at minimum a
    1920x1080-class view and an approximately 1180x820 compact view, or clearly
    documented equivalent sizes, with no overlap, clipped decisive state,
    inaccessible primary action, unreadable chart, or hidden no-trade reason.
26. Existing docking, pane persistence, command palette, pinning/linking, and
    workspace behavior continue to work where affected. Resize/docking tests
    and visual proof show that the four operator purposes remain reachable.
27. Safe isolated screenshots show the overall layout, candidate list,
    selected ticker/chart, decision state, opportunity-versus-evidence
    distinction, What Changed timeline, system health, read-only Positions
    access, and the absence of trading controls or misleading execution
    authority.
28. Screenshot generation is inspected for nonblank, correctly rendered,
    unclipped content. Steven's manual visual acceptance remains mandatory;
    automated screenshots alone cannot authorize merge or completion.
29. Release Scribe adds exact numbered operator checks to
    `docs/argus-office/VERIFICATION_QUEUE.md`, specifying what Steven opens,
    selects, resizes/docks, should see, must not see, and how to report a
    failure. The result remains pending until Steven records acceptance.

### I. Automated And Boundary Verification

30. `dotnet build MomentumHunter.Workstation.sln -c Release` completes with
    zero warnings and zero errors.
31. Focused presentation/view-model, XAML binding-contract, layout/resizing,
    current-selection, state-separation, timeline, historical-navigation,
    health, Positions-read-only, and no-live-capability tests pass.
32. Existing presentation, layout, workstation/shell integration, command
    palette, workspace/docking, chart, Positions, activity/evidence, and health
    regressions pass where affected, followed by bounded full .NET solution
    test discovery.
33. Python tests are not run ceremonially when no Python/shared contract is
    touched. Any Python or shared-contract diff is itself an unauthorized-scope
    failure, not a reason to broaden this task's test plan.
34. The complete diff from canonical creation point `82460b3...` contains only
    authorized GUI/presentation/test/asset/task-document changes. Protected
    path review, secret scan, generated-data review, and a semantic check for
    trading/live/order commands all pass.
35. Pre- and post-implementation evidence proves all of the following:
    Producer-001C source and branch identity unchanged; scheduled canary
    identity unchanged; canary evidence-root binding unchanged; opening runtime
    remains `APPROVED_RUNTIME_MATCH`; no opening-reachable Python bytes changed;
    no Continuous runtime bytes changed; no service manifest/configuration
    changed; no provider/account/broker/order capability changed. The canary's
    evidence contents may naturally advance under its own observer; this task
    must not mutate or redirect them.
36. A second-pass self-review checks the entire diff, tests, bindings,
    screenshots, operator wording, unavailable states, immutable history,
    protected paths, and nonmutation evidence. Findings receive a narrow fix
    pass followed by a final build/test/proof pass before implementation commit.

### J. Terminal Classification

37. After all automated proof passes and visual artifacts are ready, the branch
    stops at
    `GUI_IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE_AND_POST_CANARY_MERGE`.
38. No merge or install occurs. A normal non-force backup push of the proven
    task branch may occur under standing policy, but it grants no merge,
    installation, runtime, canary, or execution authority.
39. The GUI cannot be reported `COMPLETE` until the Producer-001C canary is
    terminal, its mandatory second-eye ZIP exists, the frozen boundary is
    released, Steven visually accepts the Command Center, and a separate
    post-freeze merge/install action is authorized and proven.

## Evidence Required

### Pre-Implementation Evidence

- The current Git preflight report remains `PASS`, and the Builder independently
  confirms branch, worktree, base commit, and current worktree status before
  editing.
- A current-GUI inventory/reuse artifact exists with concrete component names,
  current locations, classification, reuse decision, and duplication risks.
- Read-only physical baseline evidence records the exact current values needed
  for later equality checks: Producer-001C branch/source identities, scheduled
  canary identity, evidence-root binding, opening runtime result, opening
  reachable-byte identity, Continuous runtime identity, relevant service/
  manifest/config identity, and provider/account/broker/order capability state.
  Capture must use existing read-only verification paths and must not restart,
  repin, wake, or otherwise interfere with the canary.

### Implementation Evidence

- A file-by-file mapping from every changed production file to one or more
  acceptance criteria.
- Focused test names and results proving state separation, honest unavailable
  behavior, timeline identity, historical selection, read-only positions,
  compact health, no mutation commands, and selection/layout behavior.
- Exact Release build and bounded broader test commands, duration, pass/fail/
  skip counts, warning/error counts, and timeout handling.
- Screenshot/proof paths and recorded viewport sizes, plus sanity inspection of
  each artifact.
- Explicit inventory/reuse map and resulting layout description.
- Exact limitations caused by unavailable current read-model data and separate,
  unimplemented future backend/read-model requirements.

### Final Boundary Evidence

- `git diff --name-status 82460b3313b86c34dff4ffb737d2c04bf02e3ace...HEAD`
  plus worktree status, with every path classified as allowed and intentional.
- Before/after equality evidence for every invariant in Acceptance Criterion 35.
- Protected-path review, secret scan, generated-data review, and search/review
  for broker/order/live/transmitting or mutation capability.
- Confirmation that canonical, Producer-001C, installed runtime, services,
  scheduler, evidence-root binding, provider configuration, account/broker/order
  capability, Start Menu, and startup pointers were not changed.
- Confirmation that no merge or install occurred.

## Evidence Depth / Hard Chew Requirements

1. Capture and review pre-implementation Git, physical runtime, schedule,
   evidence-root, and capability invariants without mutating external state.
2. Complete the GUI inventory/reuse map before source edits.
3. Implement the smallest coherent four-zone read-only surface inside the
   allowed boundary.
4. Run the zero-warning Release build and the focused tests named above.
5. Broaden verification to bounded adjacent and full .NET discovery, preserving
   exact results and handling timeouts explicitly.
6. Generate safe isolated visual proof at normal and compact sizes and inspect
   it for rendering, clipping, hierarchy, state separation, and absence of
   execution controls.
7. Review the full diff against the canonical creation point, not merely the
   last commit. Prove allowed paths and protected-area nonmutation.
8. Perform secret, generated-data, live-capability, and opening/Continuous/
   canary boundary checks.
9. Perform a second independent self-review of code, tests, docs, screenshots,
   semantics, accessibility beyond color, and operator truthfulness.
10. Repair only narrow findings within the charter; otherwise stop and report.
11. Repeat affected tests, Release build, screenshot sanity checks, diff review,
    and final nonmutation proof before implementation commit.
12. Update branch-local Roadmap/Verification Queue/release evidence from actual
    branch, commit, test, visual-proof, push, merge, and next-action truth. Do
    not represent branch-only or visually unaccepted work as complete.

Done means proven behavior and preserved boundaries, not the presence of panes,
labels, test names, or screenshots alone.

## Smallest Safe Implementation Slice

Reuse the existing selected-symbol, chart, evidence/activity, health, Positions,
workspace, docking, and command-palette capabilities to compose one default
four-zone Command Center. Add only GUI-local presentation models needed to keep
opportunity state separate from evidence state, render deterministic
presentation deltas, navigate already exposed immutable history, and show
honest unavailable states. Prove normal and compact layouts with synthetic or
existing read-only fixtures. Do not cross the GUI boundary to fill missing
data.

## Implementation-Ready Handoff Notes

### App Architect / UI Operator Designer

- Produce the current-GUI inventory and reuse map first.
- Identify the concrete selected-symbol coordination path and existing
  workspace/docking/linking rules.
- Define which timeline and historical-navigation requirements are fully
  supported by current read models and which must render as unavailable.
- Keep the information hierarchy operator-facing and component-reuse-first.
- Do not edit code unless separately assigned as Builder.

### Builder

- Work only in the isolated task worktree and only after inventory plus physical
  baseline evidence exist.
- Treat the allowed path list as a hard boundary.
- Reuse existing components and snapshot truth; never add a fallback that
  invents TradePlan, readiness, score, chronology, history, health, or position
  data.
- Implement one coherent vertical slice before optional cosmetic refinement.
- Stop at the first shared-contract/backend dependency and record the exact
  unavailable-state treatment and future read-model requirement.

### QA / Reviewer

- Test operator outcomes, not only text presence: coordinated selection,
  opportunity/evidence independence, immutable historical context, honest
  missing data, no mutation authority, and usable resizing/docking.
- Inspect XAML bindings and screenshots for blank/failed bindings, clipping,
  misleading state, color-only encoding, and hidden decisive reasons.
- Compare final physical invariants to the captured baseline and reject any
  unexplained difference.

### Graphics Designer

- If separately assigned, create only task-local presentation assets/mockups
  that do not change application behavior. Preserve existing visual language
  unless the approved design artifact explicitly changes it.

### Release Scribe / Git Steward

- Record actual test, proof, commit, and optional non-force backup-push state.
- Add exact visual checks to the Verification Queue.
- Keep merge/install authorization `NO`; do not integrate while the frozen
  Producer-001C boundary or Steven's visual gate remains open.
- Do not perform reset, rebase, branch deletion, force push, non-fast-forward
  integration, or any canary/canonical mutation under this charter.

## Required Final Classification

The implementation closeout must return exactly these classifications with
evidence or an explicit limitation for every non-`YES` result:

```text
GUI_COMMAND_CENTER_IMPLEMENTED = YES / NO
GUI_ONLY_SCOPE_PRESERVED = YES / NO
CURRENT_COMPONENTS_REUSED = YES / NO
OPPORTUNITY_AND_EVIDENCE_STATE_SEPARATED = YES / NO
WHAT_CHANGED_TIMELINE_IMPLEMENTED = YES / PARTIAL / NO
HISTORICAL_CONTEXT_VISIBLE = YES / PARTIAL / NO
DECISION_HISTORY_NAVIGABLE = YES / PARTIAL / NO
SYSTEM_HEALTH_VISIBLE = YES / NO
POSITIONS_READ_ONLY_INTEGRATION = YES / NO
TRADING_CONTROLS_ADDED = NO
ENGINE_OR_STRATEGY_SEMANTICS_CHANGED = NO
PRODUCER_001C_CANARY_UNTOUCHED = YES / NO
OPENING_RUNTIME_UNCHANGED = YES / NO
READY_FOR_STEVEN_VISUAL_REVIEW = YES / NO
MERGE_AUTHORIZED = NO
```

## Required Closeout And Agent Report Fields

Every agent report must include:

- Branch.
- Scope.
- Files changed.
- Tests or checks run.
- Evidence for changed behavior.
- Protected areas reviewed.
- Push/merge status.
- Risks.
- Manual QA, if applicable.
- Open questions.
- Recommendation.

The consolidated implementation closeout must also include:

1. branch and implementation commit;
2. complete files-changed list;
3. current-GUI inventory and reuse map;
4. resulting layout description;
5. screenshots/visual-proof paths and viewport sizes;
6. automated test/build results;
7. exact boundary/nonmutation proof;
8. exact limitations caused by currently unavailable backend read-model data;
9. future backend/read-model requirements discovered but not implemented;
10. confirmation that Producer-001C remained frozen;
11. confirmation that no merge/install, Start Menu/startup pointer, service,
    scheduler, runtime, provider, Paper/Shadow, broker, account, or order action
    occurred;
12. exact numbered visual-review checklist for Steven;
13. the Required Final Classification block;
14. the exact next action and unresolved gate.

## Open CEO Decisions

- Steven remains the final visual acceptance gate after the isolated screenshots
  and safe WPF proof are ready.
- Any desired field or history behavior not exposed by the current read models
  requires a separate post-freeze product/read-model decision; this task must
  show the limitation honestly rather than requesting an in-flight backend
  expansion.
- Merge/install remains a separate future decision only after Producer-001C is
  terminal, its mandatory second-eye ZIP exists, the frozen boundary is
  released, and Steven has accepted the GUI.

## Goal Steward Review

- [x] Goal statement is concrete and centered on Steven's operator questions.
- [x] Operator outcome and information hierarchy are explicit.
- [x] Four-zone GUI scope and current-component reuse are required.
- [x] Opportunity state and evidence state are independently testable.
- [x] Timeline, historical context, and immutable decision-history rules permit
      only existing read-model truth and honest `PARTIAL` results.
- [x] Compact health and read-only Positions behavior are bounded.
- [x] Trading controls and backend/runtime semantic changes are forbidden.
- [x] Producer-001C, opening runtime, scheduler, evidence root, provider,
      service, broker, order, Paper, and Shadow boundaries are named.
- [x] Visual proof, resizing/docking, Steven acceptance, build, focused tests,
      broader regressions, self-review, secret scan, protected-path review, and
      pre/post canary nonmutation evidence are required.
- [x] The Roadmap-versus-Git mismatch is reconciled without rewriting frozen
      evidence or weakening the current directive.
- [x] Expected terminal state is
      `GUI_IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE_AND_POST_CANARY_MERGE`.
- [x] Implementation-ready handoff notes and all required report fields are
      present.
