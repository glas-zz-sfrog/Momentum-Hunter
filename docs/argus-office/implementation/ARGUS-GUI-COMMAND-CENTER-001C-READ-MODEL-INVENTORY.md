# ARGUS-GUI-COMMAND-CENTER-001C Read-Model Inventory

## Decision

```text
READ_MODEL_INSPECTION_COMPLETE = YES
READ_MODEL_GATE = RESOLVED
POPULATION_SEMANTICS = AUTHORIZED_BY_001C_C
AUTHORITATIVE_RADAR_POPULATION = CURRENT_SESSION_TRACKED_HOT_UNIVERSE_MEMBERS
AUTHORITATIVE_ACCEPTED_POPULATION = FIRST_EXECUTION_ELIGIBLE_TRANSITION_PER_CURRENT_SESSION_SETUP
AUTHORITATIVE_REJECTED_POPULATION = FIRST_ENTRY_MISSED_OR_FAILED_BREAKOUT_OR_INVALIDATED_TRANSITION_PER_CURRENT_SESSION_SETUP
SAFE_TO_POPULATE_LIFECYCLE_COUNTS_OR_PANELS = YES_AFTER_READ_ONLY_PROJECTION
SAFE_STORED_MICROCHART_SOURCE_EXISTS = YES
WPF_PROVIDER_ACCESS_REQUIRED = NO
PRESENTATION_TRADING_SEPARATION_FEASIBLE = YES
RADAR_MAP_GEOMETRY = NOT_YET_AUTHORIZED
PRODUCTION_UI_IMPLEMENTATION_MAY_CONTINUE = YES
```

001C-C resolves the product mapping without changing either underlying machine.
The authorized Command Center projections are:

1. `RADAR` is every current-session Hot Universe membership whose authoritative
   current state is `TRACKED`;
2. `ACCEPTED` is one historical current-session disposition per setup identity,
   anchored to that setup's first authoritative transition into
   `EXECUTION_ELIGIBLE`; and
3. `REJECTED` is one historical current-session disposition per setup identity,
   anchored to that setup's first authoritative transition into
   `ENTRY_MISSED`, `FAILED_BREAKOUT`, or `INVALIDATED`.

This is a read-only projection of existing facts. It does not add or alter a
Hot Universe state, Candidate Lifecycle state, transition, policy, readiness,
risk decision, or execution authority. Radar is current tracking state;
Accepted and Rejected are session disposition histories. They are intentionally
not three mutually exclusive historical buckets. A currently tracked membership
can have Accepted or Rejected setup history, and a setup that first reached
`EXECUTION_ELIGIBLE` can later have its first qualifying Rejected transition.

The first qualifying event is selected by immutable Candidate Lifecycle ledger
order and retained by exact `event_id`. Rows and counts are distinct setup
identities, not transition-event counts. The setup presentation identity is the
current-session tuple `(opportunity_id, setup_id)`; `setup_id` must be nonempty.
A successor setup has a different `setup_id` and receives no inherited
disposition. Radar presentation identity is exact `HotUniverseMember.member_id`,
which already binds symbol, session, and membership generation. Expiry followed
by readmission creates a new Radar presentation identity. Prior disposition
history remains attached to its original opportunity/setup identity.

The stored-candle architecture supports the required two-session/15-minute
charts through a bounded Engine Host snapshot without any WPF/provider call.
Radar-map geometry remains unavailable and must render a truthful pending state;
001C-C explicitly says that this does not block the rest of the implementation.

## Inspection Basis

- Implementation branch:
  `codex/ARGUS-GUI-COMMAND-CENTER-001C-PRODUCTION-INTEGRATION`
- Inspected base:
  `9967935b93659ac496d263fecfc364a73da6d2b3`
- Accepted proof commit:
  `d483776327e89c7d8d7df7317c4eb5d4b71cb7cd`
- Accepted visual:
  `ARGUS-GUI-COMMAND-CENTER-001B-proposed-1920x1080.png`
- Accepted visual SHA-256:
  `22BB20149EE3D5A3A2A73336AFA34E806DEE6B14E8D5C6F3DE94F73EB6235FDA`
- Frozen center semantic:
  `CROSS_LIFECYCLE_RANKED_CANDIDATES`
- Semantic-resume authority:
  `ARGUS-DIRECTIVE-GUI-COMMAND-CENTER-001C-C`

The accepted proof is a visual target, not evidence that its example values or
population labels exist in the current production read model. The 001A truth
map and 001B semantic decision were read together with the current Producer
base, Roadmap `Now`, C# contracts, Python Engine Host bridge, persisted report
reader, stored chart reader, Hot Universe, Candidate Lifecycle, Continuous
runtime topology, and Shadow/FakeBroker position projection.

## Classification Rules

| Classification | Meaning in this inventory |
| --- | --- |
| `AVAILABLE_NOW` | The current Engine Host/C# read-only boundary exposes the exact fact with usable source meaning. |
| `PRESENTATION_DERIVABLE` | Presentation can format, count, crop, or compose already exposed exact facts without inventing domain meaning or feeding the result back into a machine decision. |
| `NEW_READ_MODEL_REQUIRED` | An authoritative persisted source contains the fact, but the current versioned Engine Host/C# boundary does not expose the bounded fact required by the screen. |
| `UNAVAILABLE` | No current authoritative source defines the requested meaning, a safe identity/join is absent, or a nearby field has different semantics. It must be shown as unavailable or omitted. |

## Authoritative Boundaries Found

### Current workstation snapshot

`momentum_hunter/workstation_read_models.py:39-153` builds schema v2 from the
latest persisted trade-planning report, active-monitor status, and opportunity
alert store. Its own contract states that it reads precomputed evidence, does
not rescore or recalculate readiness, does not call providers, and does not
write source artifacts (`:44-49`). It emits candidates, a small activity set,
health, alert evidence, replay context, and `planningAvailable = false`.

`src/MomentumHunter.Contracts/WorkstationContracts.cs:485-494` and
`src/MomentumHunter.EngineBridge/PythonReadOnlyWorkspaceClient.cs:28-60` map
only that schema. The mapper accepts only v1/v2. The application interface is
read-only and explicitly lacks provider, broker, Paper, Live, planning, and
simulation commands
(`src/MomentumHunter.Application/ReadOnlyWorkspaceContracts.cs:5-12`).

### Ranked candidate source

The persisted trade-planning report is sorted by composite score and assigned
canonical ranks before export
(`momentum_hunter/trade_planning.py:459-482`). Every exported row contains
`rank`, symbol, score, RVOL, catalyst, detailed market data, and TradePlan facts
(`:3124-3207`). The current workstation mapper preserves file order and maps
score/RVOL/catalyst but drops the explicit source rank and TradePlan levels
(`momentum_hunter/workstation_read_models.py:70-78` and `:156-197`).

Therefore source ordering, score, RVOL, and catalyst are factual. The explicit
rank needs a small read-model addition. WPF must never sort by freshness,
microchart behavior, lifecycle color, or a locally recomputed score.

### Hot Universe owns the authorized Radar projection

`momentum_hunter/hot_universe.py:40-79` defines member states `TRACKED` and
`EXPIRED`, tiers, and transition types. A member carries stable identity,
generation, first/last observed times, last qualified/rejected observation
times, current tier/state, and source identities (`:173-206`). Transitions carry
reason, source row/snapshot identities, observation/evaluation/recording times,
and exact previous/next state and tier (`:209-236`).

Hot Universe retains a tracked member through bounded rejected observations;
only a threshold can expire it (`hot_universe.py:448-543`). 001C-C now
authorizes exact current-session `TRACKED` membership as Command Center Radar.
`OBSERVED_REJECTED` remains only a discovery-pulse observation and never becomes
Command Center Rejected. Radar identity is the exact `member_id`; membership
generation changes therefore produce new presentation identity without any new
machine state or policy.

The production Continuous location is separate from the workstation data root:
Hot Universe is under
`runtimeStateRoot/session/state/hot-universe.json`
(`momentum_hunter/continuous_production.py:874-885` and
`continuous_live_qualification.py:348-358`). The current workstation reader has
no runtime-root field and does not read this state.

### Candidate Lifecycle owns the authorized disposition-event projection

Candidate Lifecycle events preserve opportunity ID, symbol, previous/next
state, provider/receipt/event timestamps, source/evidence identity, material
delta, reason, and setup identity
(`momentum_hunter/candidate_lifecycle.py:223-254`). Its snapshot preserves exact
current state and update time (`:278-293`). The production natural setup store
is under
`runtimeStateRoot/session/state/continuous-natural-setup/candidate-lifecycle.json`
(`continuous_live_qualification.py:877-890`).

The state graph contains no literal `ACCEPTED` or `REJECTED` machine state, and
none should be added. 001C-C authorizes a read-only presentation projection:
the first actual transition per current-session setup into
`EXECUTION_ELIGIBLE` creates one Accepted disposition, while the first actual
transition per current-session setup into `ENTRY_MISSED`, `FAILED_BREAKOUT`, or
`INVALIDATED` creates one Rejected disposition. The event's exact `event_id`,
`occurred_at`, `reason`, and source identity own the row. Evidence refreshes
that do not enter a new state do not create a disposition.

The following remain expressly excluded from Command Center Rejected:
`OBSERVED_REJECTED`, `REJECTED_FILTER`, `DATA_STALE`, `EXHAUSTION_RISK`,
`COOLDOWN`, a readiness blocker alone, a risk result alone, and a
non-execution-eligible Producer result alone.

### Stored chart authority is sufficient at the backend

`momentum_hunter/workstation_charts.py:46-78` is a persisted-evidence chart
reader. It supports `15m`, loads canonical Schwab minute-store partitions, and
aggregates to 15-minute buckets in Python (`:166-204` and `:382-436`). It
preserves session dates, source, timestamps, gaps, corrections, and unavailable
states. Its lineage explicitly states that no provider call, legacy candle,
interpolation, or cross-timeframe fallback was used (`:453-550`).

The important caveat is invocation. The default workstation Engine Host starts
the selected-symbol chart service with automatic backfill enabled
(`momentum_hunter/engine_host.py:308-325` and `:1105-1109`). Reusing that
selected-symbol endpoint once per row would be provider-capable fan-out and is
forbidden by 001C. The safe solution is one new bounded batch projection inside
`build_read_only_workspace_snapshot` (or an equivalent read-only Engine Host
loader) using `WorkstationChartService(backfill_coordinator=None)`, then cropping
in Python to the last two source session dates. Missing/partial history stays
explicit.

### Positions are Shadow/FakeBroker evidence only

`OpenPositionView` is derived from canonical Shadow active-mark evidence and
already contains symbol, side, quantity, simulated fill, executable mark,
market value, unrealized P/L and R, stop, next target, quote source/age, and
state (`src/MomentumHunter.Presentation/OpenPositionView.cs:5-98`). The shell
explicitly says Schwab account positions are not connected and no order
controls exist (`ShellViewModel.cs:714-724`). These rows are safe only while
labeled `SHADOW/FAKEBROKER`, `READ-ONLY`, and `NO ORDER AUTHORITY`; they are not
real brokerage positions.

### Current chronology is partial

`ActivityEvent` exposes timestamp, category, message, symbol, and health state
(`WorkstationContracts.cs:430-435`). The current Python snapshot emits only
summary activity for the loaded report, monitor status, alerts, and replay
context (`workstation_read_models.py:58-60`, `:61-134`). It is not the Hot
Universe or Candidate Lifecycle event ledger. Existing Candidate Story and
Technical Research can be composed for a selected symbol, but still do not make
a complete lifecycle chronology. `PARTIAL HISTORY` remains mandatory.

## Required Field And Surface Inventory

### Header, shell, navigation, and footer

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Product identity / Momentum Hunter | `AVAILABLE_NOW` | Existing static application identity. Do not present proof/example badges in production. |
| `READ-ONLY RESEARCH` / no order authority | `AVAILABLE_NOW` | `ShellViewModel.EnvironmentLabel/EnvironmentDetail`, `ShellViewModel.cs:635-653`; retain explicit order-unavailable wording. |
| Source context such as `EQUITIES · RESEARCH` | `PRESENTATION_DERIVABLE` | Product/workspace context only. Do not imply exchange status, account authority, or a connected scanner. |
| Local time and timezone | `PRESENTATION_DERIVABLE` | UI clock labeled with the actual zone. It is not market/source time. |
| Evidence mode | `PRESENTATION_DERIVABLE` | Label exact sources, e.g. `PERSISTED SNAPSHOT + STORED HISTORY`; do not say `LIVE` solely because a timer refreshes. |
| Last evidence/update time | `AVAILABLE_NOW` | `ReadOnlyWorkspaceSnapshot.ObservedAt` and `SystemHealthSnapshot.CheckedAt`, `WorkstationContracts.cs:481-494`. Preserve their distinct meanings. |
| Data-health state | `PRESENTATION_DERIVABLE` | `HealthDiagnosticsView.From`, `HealthDiagnostics.cs:13-54`, rolls exact component states into `HEALTHY/PARTIAL/DEGRADED/UNAVAILABLE`. Call it data health, not connectivity or all-systems-go. |
| Console/Radar/Accepted/Rejected/Positions/Activity/Settings navigation labels | `PRESENTATION_DERIVABLE` | Static read-only navigation. The label does not prove the destination has authoritative rows. |
| Footer semantic wall | `PRESENTATION_DERIVABLE` | Static invariant: `USER ATTENTION FRESHNESS != TRADING / STRATEGY AGE`; no machine input. |
| Market open/session state | `UNAVAILABLE` | No current market-session contract exists in the workstation snapshot. |
| Scanner `LIVE`, connected status, uptime/SLA | `UNAVAILABLE` | Health/status lacks the required duration, denominator, connection, and market-session semantics. |

### Summary strip

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Radar count | `NEW_READ_MODEL_REQUIRED` | Count exact current-session Hot Universe members whose current state is `TRACKED`, keyed by `member_id`. No report/readiness inference. |
| Accepted count | `NEW_READ_MODEL_REQUIRED` | Count distinct current-session `(opportunity_id, setup_id)` identities with a first actual transition into `EXECUTION_ELIGIBLE`. |
| Rejected count | `NEW_READ_MODEL_REQUIRED` | Count distinct current-session `(opportunity_id, setup_id)` identities with a first actual transition into `ENTRY_MISSED`, `FAILED_BREAKOUT`, or `INVALIDATED`. |
| Radar/Accepted/Rejected deltas | `UNAVAILABLE` | The authorized snapshot defines current counts but no prior-comparable population snapshot/delta window. Use `—`, not a local comparison. |
| Positions count | `PRESENTATION_DERIVABLE` | Count current source-labeled `OpenPositions`; it is Shadow/FakeBroker only (`ShellViewModel.cs:681-721`). |
| Position-count delta | `UNAVAILABLE` | No comparable previous position snapshot contract exists. |
| Attention count | `UNAVAILABLE` | `OpenPositionAttentionCount` may be labeled `Shadow positions needing attention`, but it is not generic `At Risk` or candidate attention. The accepted proof correctly showed `not exposed`. |

### Radar / attention visualization

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Radar node membership | `NEW_READ_MODEL_REQUIRED` | Exact current-session `TRACKED` Hot Universe members, keyed by `member_id`; the current workstation boundary does not expose them. |
| Stable node identity | `NEW_READ_MODEL_REQUIRED` | Hot Universe has `member_id`, symbol, generation, and current-session identity, but the workstation boundary does not expose them. |
| Radius = source rank | `UNAVAILABLE` | Radar geometry is `NOT_YET_AUTHORIZED`; source rank availability does not authorize radial placement. |
| Angle = stable catalyst group | `UNAVAILABLE` | The report has `catalyst_cluster`, but no approved finite grouping/order/normalization contract for polar placement exists. The 001A proof expressly left this unapproved. |
| Node state text/color inside map geometry | `UNAVAILABLE` | No nodes may be placed while geometry is unauthorized. A non-geometric legend/status may format authoritative projected population text and restrained color. |
| Node first-surfaced time | `NEW_READ_MODEL_REQUIRED` | Hot Universe `first_observed_at` is authoritative for one membership generation; expose it only with stable member identity/current-session join. |
| Node latest exact lifecycle transition | `NEW_READ_MODEL_REQUIRED` | Candidate Lifecycle event/snapshot has exact state/update evidence, but is not bridged. Keep raw machine state distinct from population. |
| `NEW/RECENT/SEEN` attention label | `PRESENTATION_DERIVABLE` | After the v3 projection supplies factual first-surfaced or transition time, derive via UI clock. Current report `ObservedAt` is shared report age. User-seen state requires a separate presentation-owned store. |
| Empty/unavailable map state | `PRESENTATION_DERIVABLE` | Retain the visual region and state `RADAR MAP GEOMETRY NOT YET AUTHORIZED`; show the separate authoritative Radar count, but no decorative nodes. |

### Cross-lifecycle Ranked Candidates

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Canonical rank / ordering | `NEW_READ_MODEL_REQUIRED` | Exported report `rank` exists; expose it explicitly and preserve ascending source rank. Current file-order preservation is useful but not a typed rank contract. |
| Top ten / total row count | `PRESENTATION_DERIVABLE` | Take first ten by exact source rank and count source rows. Never rerank in WPF. |
| Symbol / company | `AVAILABLE_NOW` | `CandidateSnapshot`, `WorkstationContracts.cs:166-182`. |
| Candidate score | `AVAILABLE_NOW` | Exact report `composite_score`; current mapper does not recalculate (`workstation_read_models.py:177-196`). |
| Rank delta | `UNAVAILABLE` | No prior comparable canonical-rank snapshot/identity is exposed. Do not compare UI collection positions or create a local rank boost. |
| RVOL | `AVAILABLE_NOW` | Exact report `relative_volume` with report lineage; missing remains unavailable. |
| Catalyst/context | `AVAILABLE_NOW` | Exact report catalyst summary and source lineage. Catalyst cluster is not currently bridged. |
| Current raw lifecycle state | `NEW_READ_MODEL_REQUIRED` | Candidate Lifecycle snapshot owns the exact machine state. Requires explicit runtime path and unambiguous opportunity/member join. |
| Display populations (`RADAR/ACCEPTED/REJECTED`) | `NEW_READ_MODEL_REQUIRED` | Backend projects Radar from current `TRACKED` membership and disposition-history flags/counts from first qualifying setup events. Because histories can overlap current Radar and each other, expose a collection/flags, not one exclusive enum. |
| Report observation time | `AVAILABLE_NOW` | `CandidateSnapshot.ObservedAt`; label it `REPORT AGE/OBSERVED`, not first surfaced or state changed. |
| First surfaced / membership age | `NEW_READ_MODEL_REQUIRED` | Hot Universe `first_observed_at` plus member generation/identity. |
| Latest actual state change | `NEW_READ_MODEL_REQUIRED` | Expose the latest authoritative event where `previous_state != next_state`; presentation may format `DisplayStateChangedAt`. Do not include same-state evidence refresh. |
| `NEW/RECENT/SEEN` freshness | `PRESENTATION_DERIVABLE` | Derive only after the v3 projection exposes the authorized factual clock; presentation-owned label/brush remains structurally excluded from ranking and engine contracts. |
| Two-session / 15-minute microchart | `NEW_READ_MODEL_REQUIRED` | Safe canonical stored source exists, but a bounded multi-symbol payload does not. Add one batch snapshot, never per-row chart calls. |
| Microchart line color | `PRESENTATION_DERIVABLE` | Use displayed first/last close behavior only (positive/negative/flat), with text context; never lifecycle, score, readiness, risk, or priority. |
| Row selection stability | `PRESENTATION_DERIVABLE` | Preserve selection by stable candidate/member identity through refresh; new rows must not steal focus. |

### Accepted panel

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Accepted membership, count, and historical status | `NEW_READ_MODEL_REQUIRED` | One current-session row per distinct setup identity whose first actual Candidate Lifecycle transition entered `EXECUTION_ELIGIBLE`. Preserve the first event ID. |
| Symbol and candidate context | `NEW_READ_MODEL_REQUIRED` | Symbol comes from the disposition event. Report context is optional and may join only through an unambiguous same-session symbol/source row; disposition survives if context is missing. |
| Acceptance reason / thesis | `NEW_READ_MODEL_REQUIRED` | The exact first qualifying event `reason` is the disposition reason. Thesis/context may be separately source-labeled from the matched report; never substitute readiness/risk text. |
| Accepted-at timestamp / age | `NEW_READ_MODEL_REQUIRED` | Exact first qualifying event `occurred_at`; presentation derives age without changing membership. |
| Entry / stop / target / score | `NEW_READ_MODEL_REQUIRED` for a lifecycle row | The persisted report has TradePlan levels and score. Include only an unambiguous same-session match and keep levels labeled hypothetical/research; missing context remains unavailable. |
| Equivalent 2D/15m mini-chart | `NEW_READ_MODEL_REQUIRED` | Use the same stored batch contract as ranked rows. Missing history remains explicit. |
| Acceptance transition marker | `NEW_READ_MODEL_REQUIRED` | Place only from the exact first `EXECUTION_ELIGIBLE` event timestamp when it lies within the displayed series. No timestamp or out-of-window event means no marker. |

### Rejected panel

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Rejected membership, count, and historical status | `NEW_READ_MODEL_REQUIRED` | One current-session row per distinct setup identity whose first actual transition entered `ENTRY_MISSED`, `FAILED_BREAKOUT`, or `INVALIDATED`. Preserve the first qualifying event ID. |
| Rejection reason / blocker | `NEW_READ_MODEL_REQUIRED` | Use only the exact first qualifying event `reason`. Discovery rejection, readiness blockers, risk results, `DATA_STALE`, `EXHAUSTION_RISK`, and `COOLDOWN` remain excluded. |
| Rejected-at timestamp / age | `NEW_READ_MODEL_REQUIRED` | Exact first qualifying event `occurred_at`; never use `HotUniverseMember.last_rejected_at`, which is discovery-observation time. |
| Score / RVOL context | `NEW_READ_MODEL_REQUIRED` | Optional same-session unambiguous report context. Missing context does not remove or rewrite the disposition row. |
| Equivalent 2D/15m mini-chart | `NEW_READ_MODEL_REQUIRED` | Same bounded stored batch as ranked rows. |
| Rejection transition marker | `NEW_READ_MODEL_REQUIRED` | Place only from the exact first qualifying Rejected event timestamp when in the displayed series; otherwise omit. |

### What Changed / recent events

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Current Activity time/category/message/symbol/state | `AVAILABLE_NOW` | Exact persisted report/monitor/alert/replay summary activity only. |
| Selected Candidate Story / technical events | `AVAILABLE_NOW` | Existing selected-symbol read-only contracts; compose with source labels. |
| Hot Universe transitions | `NEW_READ_MODEL_REQUIRED` | Exact persisted transition fields exist but are not exposed through the Engine Host snapshot. |
| Candidate Lifecycle transitions | `NEW_READ_MODEL_REQUIRED` | Exact event/reason/time/source fields exist but are not exposed. |
| Rank-change chronology | `UNAVAILABLE` | No prior comparable canonical rank snapshot is preserved in the current read model. |
| Complete chronology claim | `UNAVAILABLE` | Keep `PARTIAL HISTORY`; never claim a complete machine log. |
| Reverse chronological ordering | `PRESENTATION_DERIVABLE` | Sort only exact event timestamps within the explicitly source-bounded set; stable event identity is required for dedupe. |

### Positions — read-only

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Symbol, side, quantity | `AVAILABLE_NOW` | `OpenPositionView` from canonical Shadow active marks. |
| Entry | `AVAILABLE_NOW` | Simulated average fill; label `SIM FILL`, not brokerage entry. |
| Mark/current price | `AVAILABLE_NOW` | Current executable Shadow mark with provider/age; unavailable stays unavailable. |
| Unrealized P/L, percent, R, market value | `PRESENTATION_DERIVABLE` | Existing `OpenPositionView.From` derives these from exact mark/fill/quantity (`OpenPositionView.cs:44-89`). |
| Stop / next target | `AVAILABLE_NOW` | Shadow active-mark evidence; not an executable order. |
| Thesis/source | `PRESENTATION_DERIVABLE` | Compose exact Shadow trade Setup/Catalyst and source mode from the same `ShadowTradeReviewSnapshot`; do not join by symbol alone. |
| Position count / visible rows | `PRESENTATION_DERIVABLE` | Count exact open views; preserve current filter/identity. |
| Real brokerage positions/account/orders | `UNAVAILABLE` | Must remain absent. No account/order authority is authorized or connected. |

### System Context

| Visible field/surface | Classification | Exact treatment and source |
| --- | --- | --- |
| Data health | `PRESENTATION_DERIVABLE` | Existing health diagnostics rollup with exact component detail. |
| Last evidence update | `AVAILABLE_NOW` | Workspace observed time and component checked times. |
| Workspace authority | `AVAILABLE_NOW` | Existing `READ-ONLY` environment state and explanation. |
| Event history completeness | `PRESENTATION_DERIVABLE` | Must remain `PARTIAL` until both source coverage and event contract completeness are proven. |
| Attention / at-risk | `UNAVAILABLE` | No generic candidate/position risk-attention contract. Shadow attention may be shown only with that exact scope. |
| Uptime, scan rate, acceptance/rejection rate | `UNAVAILABLE` | Required denominators/windows do not exist. |

## Authorized Smallest Bounded V3 Contract

Do not add a second provider or decision authority. Extend the existing schema
to v3 with one optional, fully read-only `commandCenter` payload produced by the
Python Engine Host. Retain v1/v2 compatibility and fail closed to explicit
unavailable states.

```text
ReadOnlyWorkspaceSnapshot v3
└── CommandCenter: CommandCenterSnapshot?
    ├── ObservedAt
    ├── SessionDate
    ├── ProjectionState / SourceCoverage / Limitations
    ├── PopulationContractVersion = command-center-populations-v1
    ├── SourceIdentities
    ├── RadarMembers[]
    ├── AcceptedDispositions[]
    ├── RejectedDispositions[]
    ├── RankedCandidates[]
    ├── LifecycleEvents[]
    └── MiniChartsBySymbol{}
```

Minimum Radar member facts:

```text
RadarPresentationIdentity = HotUniverseMember.member_id
MembershipGeneration
DerivedLifecycleOpportunityId = expected_opportunity_id(Symbol, SessionDate, "CONTINUOUS_HOT_UNIVERSE")
Symbol
SessionDate
FirstSurfacedAt = first_observed_at
LastObservedAt
CurrentState = TRACKED
CurrentTier
SourceSnapshotIdentity
DataLineage
```

Minimum Accepted/Rejected disposition facts:

```text
DispositionPresentationIdentity = (SessionDate, OpportunityId, SetupId, Kind)
DispositionEventId = exact first qualifying CandidateLifecycleEvent.event_id
Kind = ACCEPTED | REJECTED
OpportunityId
SetupId
SetupFamily
SetupSequence
Symbol
SessionDate
PreviousState
ReachedState
OccurredAt
Reason
SourceIdentity / EvidenceFingerprint
DataLineage
```

Minimum ranked-row facts:

```text
StableCandidateIdentity
Symbol
SourceRank
Score
RelativeVolume
CatalystSummary
RadarMemberIdentity?        # exact projector result, never inferred by WPF
AcceptedDispositionIds[]    # may coexist with Radar and Rejected history
RejectedDispositionIds[]
RawMachineState?            # exact joined snapshot only
DisplayFirstSurfacedAt?     # factual member-generation timestamp
DisplayStateChangedAt?      # latest actual previous_state != next_state event
DataLineage / SourceIdentity
MiniChartSymbolKey
```

The populations are not represented by one exclusive enum. Radar is a current
membership projection; Accepted and Rejected are event-backed setup histories.
A setup may have both Accepted and Rejected disposition identities, and its Hot
Universe membership may still be Radar. The backend owns those references; WPF
only formats them.

Minimum `DisplayMiniChartSeries` facts:

```text
State = AVAILABLE | PARTIAL | UNAVAILABLE
Symbol
Interval = 15m
RequestedSessionCount = 2
SourceSessionDates[]
Points[] = (Timestamp, Close)
SourceLabel
AsOf
GapCount / CorrectionCount / Findings
Limitation
```

The backend must:

1. validate and project population/event identity exactly as specified below;
2. preserve the full population counts while ordering disposition display rows
   newest-first by exact event chronology, never by chart/freshness behavior;
3. take ten ranked symbols plus the visible Accepted/Rejected row symbols in
   one bounded distinct chart-symbol set;
4. read persisted canonical candles only with no backfill coordinator;
5. aggregate 15m in Python using the existing canonical implementation;
6. select the last two source session dates, not 48 clock hours;
7. cap points and chart symbols deterministically;
8. preserve partial/unavailable status and exact lineage; and
9. emit no color, trend score, chart strength, freshness score, or trading
   interpretation.

The C# presentation may derive only:

- formatted ages from exact timestamps;
- `DisplayFreshnessLabel` and `DisplayFreshnessState` in Presentation;
- chart geometry and a line brush from displayed first/last close behavior;
- top-ten truncation from explicit source rank;
- counts from already authoritative population arrays; and
- Shadow position totals from exact current rows.

`Candidate.freshness_score` is prohibited from the v3 projector, DTOs, view
models, bindings, and tests. `DisplayFirstSurfacedAt`,
`DisplayStateChangedAt`, `DisplayAttentionAge`, `DisplayFreshnessLabel`, and
`DisplayFreshnessState` are presentation-owned. No display freshness value is
serialized back to Python or passed to any engine interface.

The contract must not appear in any scoring, readiness, risk, plan, entry,
exit, broker, Paper, Shadow-writing, or execution interface. A repository
reference scan and tests should prove that the new display DTOs flow only:

```text
persisted evidence
-> Python read-only projector
-> Python Engine Host snapshot command
-> C# read-only mapper/contracts
-> Presentation/WPF
```

There must be no reverse edge.

## Runtime Path And Identity Requirement

The workstation Engine Host currently knows the repository
`MomentumHunterData/data` paths, while production Continuous evidence is under
an independently configured `runtimeStateRoot`. WPF must not read Continuous
files directly. The read-only projector needs an explicit, non-secret,
validated runtime evidence path supplied to the Engine Host or a separately
published read-only snapshot. It must validate:

- expected Hot Universe and Candidate Lifecycle schema/profile;
- current session identity;
- unique active member per symbol;
- independent preservation of `HotUniverseMember.member_id` as the membership-
  generation identity (it is never equal to a Candidate Lifecycle opportunity);
- `CandidateLifecycleEvent.originating_evidence_family ==
  "CONTINUOUS_HOT_UNIVERSE"` and
  `event.opportunity_id == expected_opportunity_id(member.symbol,
  member.session_date, "CONTINUOUS_HOT_UNIVERSE")`, with exact symbol/session
  agreement;
- source predecessor/fingerprint integrity through existing loaders;
- exact report candidate rank/identity; and
- unavailable status for missing, stale, ambiguous, or cross-session joins.

### Exact population and event algorithm

The projector must load both stores through their existing validating loaders.
Let `session_date` be the nonempty `HotUniverseState.current_session_date`.
Then:

1. `RadarMembers` is every member with `member.session_date == session_date`
   and `member.current_state == TRACKED`, keyed by exact `member.member_id`.
2. Traverse Candidate Lifecycle events in validated ascending ledger sequence.
   Consider only events with `event.session_date == session_date`,
   `event.originating_evidence_family == "CONTINUOUS_HOT_UNIVERSE"`, nonempty
   `opportunity_id`, nonempty `setup_id`, and
   `event.previous_state != event.next_state`.
3. For each `(opportunity_id, setup_id)`, the first considered event whose
   `next_state == EXECUTION_ELIGIBLE` creates exactly one Accepted disposition.
4. For each `(opportunity_id, setup_id)`, the first considered event whose
   `next_state` is `ENTRY_MISSED`, `FAILED_BREAKOUT`, or `INVALIDATED` creates
   exactly one Rejected disposition.
5. Preserve the exact qualifying `event_id`, sequence, reason, occurred time,
   evidence fingerprint, and source identity. Do not replace the first event
   with a later event in the same disposition family.
6. Do not suppress a Rejected disposition because the same setup already has
   Accepted history, and do not suppress Radar because a setup disposition
   exists.
7. A successor `setup_id` is evaluated independently. No prior disposition is
   copied to it.
8. A readmitted Hot Universe generation uses its new `member_id`; no Radar
   presentation identity is reused. Historical dispositions retain their
   original opportunity/setup identity.

The projector must explicitly exclude `OBSERVED_REJECTED`, `REJECTED_FILTER`,
`DATA_STALE`, `EXHAUSTION_RISK`, `COOLDOWN`, same-state evidence refresh,
readiness blockers, risk results, and non-execution-eligible Producer results
from Rejected creation. It must never derive Accepted from readiness, a risk
allow result, or Producer output.

### Join and fail-closed behavior

- `HotUniverseMember.member_id` and `CandidateLifecycleEvent.opportunity_id`
  are different protected identities. They must never be compared for equality
  or substituted for one another.
- A Candidate Lifecycle event may join a Hot Universe membership only when all
  of these are true: both validating loaders succeeded; symbol and session date
  agree exactly after the existing canonical normalization; the event's
  originating family is exactly `CONTINUOUS_HOT_UNIVERSE`; and its
  `opportunity_id` equals `expected_opportunity_id(member.symbol,
  member.session_date, "CONTINUOUS_HOT_UNIVERSE")`.
- This is an authoritative identity derivation, not a symbol-only inference.
  `CandidateLifecycleCoordinator.discover` constructs the opportunity with that
  function (`candidate_lifecycle.py:407-427`), the natural coordinator supplies
  the fixed family (`continuous_natural_setup.py:200-227`), and every persisted
  event is rejected unless the same identity recomputes exactly
  (`candidate_lifecycle.py:926-936` and `:1224-1237`).
- A validated `ContinuousProducerRecord` is corroboration where it contains a
  setup-bearing lifecycle proposal, not the primary bridge. The record binds
  `member_id` and top-level `setup_id`; its hashed `payload_json` embeds the
  composition cycle, whose matching member result contains
  `universe_member_id` and `lifecycle_proposal.{opportunity_id,setup_id}`
  (`continuous_tradeplan_producer.py:666-776`). For such a record, require
  exactly one matching member result and exact agreement among record member,
  record setup, proposal opportunity/setup, derived opportunity, symbol, and
  session. Any disagreement makes that setup join `UNAVAILABLE`.
- Producer corroboration must not be required when no setup-bearing proposal
  was persisted. Natural setup can commit direct lifecycle transitions before
  composition, and unchanged/no-proposal producer records intentionally carry
  an empty top-level `setup_id` (`continuous_natural_setup.py:404-468` and
  `continuous_tradeplan_producer.py:692-700`). Absence of a producer proposal
  therefore cannot invalidate an otherwise loader-validated lifecycle event;
  it only means producer corroboration is not applicable.
- Radar does not require a setup event. A setup disposition does not require
  the membership to remain Radar.
- Ranked report context may join population rows only through a unique
  normalized-symbol match in the same source session. If same-session identity
  cannot be proven, keep the ranked row and disposition rows independently and
  expose the context join as unavailable.
- Multiple setup dispositions for one symbol remain multiple identities. A
  ranked symbol receives disposition ID collections, never a silently selected
  single lifecycle state.
- Missing chart history affects only `MiniChartsBySymbol`; it cannot remove,
  reorder, accept, reject, or reclassify a candidate.
- Missing/corrupt Hot Universe state makes all three lifecycle projections
  `UNAVAILABLE` because the authoritative current session cannot be established.
  A valid Hot Universe with missing/corrupt Candidate Lifecycle evidence still
  permits Radar, but Accepted/Rejected are `UNAVAILABLE`; it never creates
  empty-but-healthy populations.
- Invalid schema/profile, duplicate identities, nonmonotonic sequence,
  mismatched derived opportunity/symbol/session/family identity, contradictory
  producer corroboration, empty setup ID, cross-session data,
  or ambiguous report context must produce an explicit component limitation.
  Do not guess, coerce, or fall back to readiness/risk/discovery text.

Changing the Continuous producer, its state machine, its files, or its write
behavior is outside 001C. The read model may observe only. The remaining hard
integration constraint is supplying an explicit validated read-only Continuous
runtime path to the Engine Host without install/startup/config mutation. If it
is absent at runtime, the applicable populations render `UNAVAILABLE`; Builder
implementation itself may continue and must prove this fail-closed state.

## Continuous Refresh Boundary

The current window refreshes selected chart data every five seconds and Shadow
positions every second; it does not continuously refresh the read-only
workspace (`MainWindow.xaml.cs:39-80` and `:90-104`). Use one guarded Command
Center snapshot refresh, preferably on the existing five-second background
cadence. Do not issue row-level requests.

Refresh must:

- use a non-overlapping lock/cancellation guard;
- preserve selected row by stable identity;
- update existing keyed rows rather than clear/reselect everything;
- let exact source rank change only when a new authoritative snapshot changes
  it;
- never let new rows steal focus;
- leave source-unavailable rows visible with limitations; and
- keep WPF selection/freshness state presentation-owned and out of the wire
  input to machine decisions.

## Required Semantic Tests

1. Radar contains exactly authoritative current-session `TRACKED` Hot Universe
   memberships and uses `member_id` as presentation identity.
2. Accepted selects only the first `EXECUTION_ELIGIBLE` transition per
   current-session `(opportunity_id, setup_id)`.
3. Rejected selects only the first `ENTRY_MISSED`, `FAILED_BREAKOUT`, or
   `INVALIDATED` transition per current-session setup identity.
4. `OBSERVED_REJECTED`, `REJECTED_FILTER`, `DATA_STALE`, `EXHAUSTION_RISK`,
   `COOLDOWN`, readiness blockers, risk results, and non-execution-eligible
   Producer results do not create Rejected rows.
5. Successor setup IDs remain independent and receive no inherited
   Accepted/Rejected disposition.
6. Expired/readmitted membership generations receive new Radar presentation
   identity while prior disposition history retains its original identity.
7. Accepted/Rejected histories remain available for the current session even
   when the membership is no longer Radar; one setup may have both histories.
8. Ranked Candidates may reference Radar and disposition histories without
   changing any population count, rank, or lifecycle state.
9. Source rank is preserved exactly; modifying display freshness or chart series
   cannot change rank or score.
10. `Candidate.freshness_score` has no reference/path to
    `DisplayAttentionAge`, `DisplayFreshnessLabel`,
    `DisplayFreshnessState`, `DisplayFirstSurfacedAt`, or
    `DisplayStateChangedAt`.
11. Display freshness and `DisplayMiniChartSeries` are referenced only by
    read-only Presentation/WPF paths, never scoring/admission/readiness/risk/
    entry/exit/execution interfaces.
12. Batch charts contain only source-proven last-two-session 15m points; no
    provider call, interpolation, cross-symbol reuse, or WPF aggregation occurs.
13. Missing/partial chart evidence remains explicit and cannot remove, reorder,
    accept, reject, or reclassify a candidate.
14. Missing lifecycle path, mismatched session/family, duplicate identity,
    empty setup ID, a lifecycle opportunity that does not recompute from the
    authoritative natural-family tuple, or contradictory producer corroboration
    produces `UNAVAILABLE`, never an inferred population.
15. Accepted/Rejected reasons and markers appear only from their exact retained
    first qualifying event ID and timestamp.
16. Workspace refresh preserves selection and does not issue per-row Engine
    Host calls.
17. Position rows retain Shadow/FakeBroker/read-only disclosure and expose no
    trade command.

## Resolved Authority And Remaining Hard Constraint

001C-C is the authority for every population/event rule in this inventory. The
semantic gate is resolved and Builder work may resume; it must not reopen or
broaden the decision.

Radar-map geometry is still `NOT_YET_AUTHORIZED`. The region must remain in the
accepted layout but render a truthful pending/unavailable state—no catalyst
angle, radial distance, motion, or decorative node placement. This does not
block Radar count/population, Ranked Candidates, Accepted, Rejected,
microcharts, Positions, What Changed, or System Context.

The only remaining hard integration constraint is a validated read-only route
from the Engine Host to the existing Continuous runtime evidence path. It may
be solved by explicit dependency/path injection in the bounded projector; it
may not modify installation, startup pointers, Continuous writer behavior, or
provider authority. Runtime absence must fail closed as documented above.

No production code, test, runtime, provider, strategy, broker, or order file was
changed by this inventory.
