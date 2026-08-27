# ARGUS-GUI-COMMAND-CENTER-001A Truth Dependency Map

## Decision

This is a read-only source inventory for the visual-fidelity directive at
`4bf397b2c410760f31af317a27c66e00b87fabe7`.

```text
STRATEGY_SEMANTICS_CHANGED = NO
EXECUTION_SEMANTICS_CHANGED = NO
SCORING_OR_RANKING_CHANGED = NO
READINESS_OR_RISK_CHANGED = NO
BROKER_OR_ORDER_AUTHORITY_ADDED = NO
```

The reference image is a visual target, not a data contract. Its numbers,
state names, rates, market/scanner claims, confidence values, and Radar
geometry must not be copied into the product. Existing truth may be moved,
formatted, counted, filtered, or source-labeled in the presentation layer only
where the table below says that is safe.

## Classification Rules

| Classification | Meaning in this map |
| --- | --- |
| `AVAILABLE` | A current C# contract/read model already exposes the required fact with usable identity and provenance. |
| `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | The UI can deterministically format, count, filter, crop, or compose already exposed facts without changing their meaning or feeding them back into ranking, readiness, risk, alerts, or execution. |
| `UNAVAILABLE` | No authoritative current source supports the claimed meaning, or the only nearby field has materially different semantics. The field must be omitted or labeled unavailable. |
| `FUTURE READ-MODEL DEPENDENCY` | Related source evidence exists, often in Python, but the WPF boundary lacks a typed, versioned field/collection that preserves the required meaning and provenance. |

## Executive Region Map

| Required region or field | Classification | Safe current treatment | Truth source / reason |
| --- | --- | --- | --- |
| Product identity and global `READ-ONLY RESEARCH` context | `AVAILABLE` | Keep the existing static safety statement. | `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml:246` and `:2676`. |
| Workspace/environment context | `AVAILABLE` | Show `READ-ONLY`, `SIMULATION`, `REPLAY ONLY`, or `REVIEW ONLY` with the existing explanation. | `ShellViewModel.EnvironmentLabel` and `EnvironmentDetail`, `src/MomentumHunter.Presentation/ShellViewModel.cs:650-668`. |
| Selected symbol, exact price/change, selected interval, chart source/quality/as-of | `AVAILABLE` | Show the selected-candidate/chart values with source and unavailable states intact. | `CandidateSnapshot`, `WorkstationContracts.cs:166-182`; `ChartSnapshot`, `:241-251`; `CommandCenterMarketStoryView`, `CommandCenterModels.cs:254-288`; `ChartPaneViewModel`, `ChartPaneViewModel.cs:41-124`. |
| UI clock/date | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | A local or UTC UI clock may be shown only when labeled as an application clock. It is not exchange time, source time, or proof the market is open. | Presentation can read the local clock; provider/source timestamps remain separately exposed by `ChartQualitySnapshot`, `WorkstationContracts.cs:221-239`. |
| `MARKET OPEN`, `U.S. Equities`, or authoritative exchange-session header | `UNAVAILABLE` | Omit. A historical capture's session marker must not become a global current-market state. | Candidate Story exposes per-capture `Session`/`SessionMarker` only, `WorkstationContracts.cs:338-364`; no current market-session contract exists in the WPF snapshot. |
| `SCANNER LIVE`, `All Systems Go`, or connected-for-trading claim | `UNAVAILABLE` | Omit. Health is not scanner authority or execution readiness. | `SystemHealthSnapshot` carries component state/summary/check time only, `WorkstationContracts.cs:475-483`. |
| Current candidate count / Radar-list count when explicitly labeled as current candidates | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | Count the current `Candidates`/`AttentionRows` collection; label the denominator `current source-ordered candidates`, not `Radar coverage`. | `ShellViewModel.UniverseCountLabel`, `ShellViewModel.cs:674-676`; source order is preserved by `CommandCenterAttentionRowView.ProjectSourceOrder`, `CommandCenterModels.cs:57-60`. |
| What Changed row count | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | Count the selected-symbol composite and retain `PARTIAL HISTORY`. | `ShellViewModel.WhatChangedCountLabel`/`WhatChangedLimitationLabel`, `ShellViewModel.cs:693-698`; composition at `CommandCenterModels.cs:291-358`. |
| Read-only position count | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | Count only current source-labeled FakeBroker/Shadow position views. | `PositionsButtonLabel`, `ShellViewModel.cs:724-731`; `OpenPositionView`, `OpenPositionView.cs:5-21`. |
| Health-component counts | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | Show component total/healthy/degraded/unavailable as data health, not system readiness. | `HealthDiagnosticsView.From`, `HealthDiagnostics.cs:18-59`. |
| Radar Top list | `AVAILABLE` | Reuse Live Universe rows: source rank, symbol, exact price/change, score, RVOL, catalyst, opportunity/evidence text, and report-observation age. | Candidate fields at `WorkstationContracts.cs:166-182`; presentation row at `CommandCenterModels.cs:11-60`. |
| Radar map geometry, radial distance, angle, node motion, or map legend semantics | `UNAVAILABLE` | Do not draw a semantic map. A decorative plot would invent relationships. | No coordinate/axis/polar model exists in Contracts, EngineBridge, or Presentation. The current list has rank but no geometry. |
| Canonical `Accepted` membership/list/count | `FUTURE READ-MODEL DEPENDENCY` | Do not infer membership from green color, score, readiness, `RiskDecision.Allowed`, or label substrings. An exact raw source label may be displayed as-is, but it does not define a normalized Accepted set. | `CandidateSnapshot.SourceReadinessLabel` is free text, `WorkstationContracts.cs:181-192`; `RiskDecision` is selected-plan evidence only, `:404-419`; the UI keeps opportunity and evidence text separate at `CommandCenterModels.cs:132-161`. |
| Canonical `Rejected` membership/list/count | `FUTURE READ-MODEL DEPENDENCY` | Do not infer from absence, stale data, blocked readiness, or a failed risk check. | Current candidate contract has no disposition enum or rejection identity. `DailyWorkflowReviewCounts.Rejected`, `WorkstationContracts.cs:496-502`, belongs to the separate daily-review artifact and is not the live universe. `ShadowSampleStatus.RiskRejected`, `:824-838`, belongs to the Shadow sample and is also not the live universe. |
| Rejection reason | `FUTURE READ-MODEL DEPENDENCY` | For the selected current plan, show exact `RiskDecision.Reasons`; do not call that a durable candidate-rejection record. A Rejected table needs an explicit source reason. | Current selected-plan reason mapping is `CommandCenterDecisionView`, `CommandCenterModels.cs:196-246`. Python has related Hot Universe transition `reason`, but it is not exposed to WPF: `momentum_hunter/hot_universe.py:210-230`. |
| Rejected-at time / `Since` duration | `FUTURE READ-MODEL DEPENDENCY` | Omit until the candidate disposition event carries an authoritative timestamp and identity. | Python `HotUniverseMember.last_rejected_at` exists at `momentum_hunter/hot_universe.py:173-203`, but no corresponding C# contract/mapper field exists. |
| Selected-symbol candles at the requested `15m` interval | `AVAILABLE` | Use the existing chart request and stored candles when the returned snapshot identifies interval `15m`; preserve loading, partial, stale, and unavailable states. | `ShellViewModel.IntervalOptions` includes `15m`, `ShellViewModel.cs:393`; `PythonChartWorkspaceClient.GetSnapshotAsync`, `PythonChartWorkspaceClient.cs:17-35`; OHLCV contract at `WorkstationContracts.cs:203-251`. |
| Selected-symbol two-session mini-chart from already loaded candles | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | The UI may crop an existing selected-symbol candle collection to its last two exposed session dates. If two sessions are not present, say so; do not aggregate or backfill. | `ChartQualitySnapshot.SessionDates` and `ChartSnapshot.Candles`, `WorkstationContracts.cs:221-251`; mapper preserves both at `PythonChartWorkspaceClient.cs:53-101` and `:150-168`. |
| Two-day/15m mini-chart for every Radar/Accepted row | `FUTURE READ-MODEL DEPENDENCY` | Do not fan out provider calls or reuse the selected symbol's candles. A batched, source-bounded multi-symbol candle read model is required. | `ChartPaneViewModel` owns one pane/symbol candle collection, `ChartPaneViewModel.cs:13-49`; chart fetch is one requested symbol/interval, `PythonChartWorkspaceClient.cs:17-35`. |
| Technical/capture marker on the selected chart | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | A marker may be placed only from an exact exposed event/capture timestamp and exact trigger/capture price, clearly labeled `TECHNICAL RESEARCH` or `CANDIDATE STORY`. Missing price/time means no marker. | `TechnicalResearchEventSnapshot.EventTimestamp`/`TriggerPrice`, `WorkstationContracts.cs:253-266`; Candidate Story capture time/price/identity, `:338-364`; their mappers preserve these fields at `TechnicalResearchView.cs:52-108` and `PythonCandidateStoryWorkspaceClient.cs:115-156`. |
| Candidate lifecycle/admission/accept/reject transition marker | `FUTURE READ-MODEL DEPENDENCY` | Do not translate Activity text into a typed transition. A versioned transition DTO is required. | Python retains previous/next state/tier, reason, identities, and timestamps in `HotUniverseTransition`, `momentum_hunter/hot_universe.py:209-233`; none is present in the C# read-only workspace mapper, which maps only candidates/activity/health/alert/replay at `PythonReadOnlyWorkspaceClient.cs:28-60`. |
| Report-observation freshness (`NEW`/`RECENT`/`EARLIER`/`SEEN`) | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | Continue formatting from `CandidateSnapshot.ObservedAt`, explicitly saying it is not discovery time and never using it for ordering or readiness. | `CommandCenterAgeView`, `CommandCenterModels.cs:88-125`; source order remains independent at `:57-60`. |
| First trusted Candidate Story capture and latest trusted capture | `AVAILABLE` | May be shown as `First capture` / `Latest capture`, preserving the supplied labels and source. Do not relabel either as first surfaced or last meaningful change. | `CandidateStorySnapshot.FirstSeenLabel`/`LatestSeenLabel`, `WorkstationContracts.cs:366-393`; presentation maps them at `CandidateStoryView.cs:44-67`. |
| First surfaced in the live candidate machine | `FUTURE READ-MODEL DEPENDENCY` | Requires an exposed membership identity/generation plus `firstObservedAt`. Candidate report `ObservedAt` and Candidate Story first capture are not substitutes. | Python `HotUniverseMember.first_observed_at`, generation, and discovery identities exist at `momentum_hunter/hot_universe.py:173-205`; the WPF candidate mapper exposes none of them, `PythonReadOnlyWorkspaceClient.cs:63-96`. |
| Last meaningful change | `FUTURE READ-MODEL DEPENDENCY` | Requires the machine/domain to define which transition types are meaningful and expose the chosen event timestamp/identity. Do not use `last_observed_at`, latest capture, latest quote, or UI selection time as a proxy. | Related Python facts are `HotUniverseMember.last_observed_at`/`last_qualified_at`/`last_rejected_at`, `hot_universe.py:179-194`, and transition `recorded_at`, `:210-230`; no canonical `lastMeaningfulChangeAt` exists. |
| Generic machine log / recent-event rows already emitted as Activity | `AVAILABLE` | Display exact timestamp, category, message, symbol, and health state. Keep source label `ACTIVITY`. | `ActivityEvent`, `WorkstationContracts.cs:430-435`; read-only mapper at `PythonReadOnlyWorkspaceClient.cs:99-104`. |
| Candidate Story and technical research rows in the recent-event region | `AVAILABLE` | Compose source-labeled evidence in reverse chronology and preserve stable Candidate Story identity. Keep the region explicitly partial. | `CommandCenterTimelineItemView.Compose`, `CommandCenterModels.cs:291-372`; Shell refresh at `ShellViewModel.cs:1675-1695`. |
| Complete machine transition log / every reevaluation | `FUTURE READ-MODEL DEPENDENCY` | Show `PARTIAL HISTORY`; do not claim completeness. | Current composite uses only Activity, Candidate Story, and Technical Research. The limitation is explicit at `ShellViewModel.cs:697-698`. Python Hot Universe transitions are not bridged. |
| Positions table: symbol, side, quantity, fill, mark, market value, unrealized P&L/%, R, stop, next target, state, provider, quote age | `AVAILABLE` | Keep the pane and every field explicitly `POSITIONS — READ-ONLY`, `FakeBroker`, or exact source mode. | `OpenPositionView`, `OpenPositionView.cs:5-42`; mapping from Shadow active marks at `:44-89`; source disclosure at `ShellViewModel.cs:757-767`. |
| Position total market value / current unrealized P&L / attention-state count | `PRESENTATION-DERIVABLE WITHOUT SEMANTIC CHANGE` | Sum only non-null current source values and retain unavailable handling. Call the state count `need attention`, never `At Risk`. | `ShellViewModel.OpenPositionPnlDisplay`, `OpenPositionMarketValueDisplay`, `OpenPositionAttentionCount`, and `OpenPositionQuoteHealthDisplay`, `ShellViewModel.cs:733-755`. |
| Real brokerage positions, account equity, buying power, orders, or executable controls | `UNAVAILABLE` | Omit. Do not convert Shadow/FakeBroker evidence into brokerage state. | Existing source disclosure explicitly says Schwab account positions are not connected and no order controls are available, `ShellViewModel.cs:766-767`. |
| System/data health summary and component drill-down | `AVAILABLE` | Show `DATA HEALTHY`, `DATA PARTIAL`, `DATA DEGRADED`, or `DATA UNAVAILABLE`, summary, checked-at, and source components. | `SystemHealthSnapshot`, `WorkstationContracts.cs:475-483`; `HealthDiagnosticsView`, `HealthDiagnostics.cs:5-59`; compact wrapper `CommandCenterModels.cs:450-458`. |
| Uptime percentage, scanner uptime, scan rate, provider SLA, or latency percentile | `UNAVAILABLE` | Omit. Component status and checked time cannot be converted into uptime or SLA. | No uptime duration, observation window, denominator, heartbeat series, scan count window, or latency distribution exists in the WPF health contract. |

## Header And Data-Context Boundaries

The header can truthfully contain:

- product identity and the global `READ-ONLY RESEARCH` safety state;
- current workspace mode from `EnvironmentLabel`;
- current selected symbol and selected interval;
- candidate/chart as-of, provider, receipt, completed-bar, and age details;
- compact data health and its checked-at time;
- read-only navigation to Positions, What Changed, panes, and diagnostics.

The reference header's `MARKET OPEN`, `SCANNER LIVE`, `All Systems Go`, accept
rate, rejection rate, and uptime are not current facts. A wall clock can be a
UI clock, but it must not make those claims. `ChartQualitySnapshot.AgeSeconds`
is the age of selected chart evidence, not scanner uptime or universe
freshness (`WorkstationContracts.cs:221-239`).

## Summary Counts

### Safe now

1. `current source-ordered candidates` = `AttentionRows.Count`.
2. `traceable rows` = current selected-symbol `WhatChangedRows.Count`, with
   `PARTIAL HISTORY` beside it.
3. `read-only FakeBroker positions` = `OpenPositions.Count`.
4. data-health component totals by the exact `HealthState` values.
5. alert counts only inside an explicitly labeled Alert Evidence surface:
   `AlertEvidenceSnapshot` supplies total, active, recorded-outcome, and
   unscorable counts at `WorkstationContracts.cs:453-462`.

### Not interchangeable

- `DailyWorkflowReviewCounts.Interested/Rejected/Watchlist` describes a daily
  review artifact, not the current live candidate universe.
- `ShadowSampleStatus.RiskRejected` describes the prospective Shadow sample,
  not current candidate rejection.
- `AlertEvidenceSnapshot.ActiveAlertCount` is not `At Risk` positions.
- `OpenPositionAttentionCount` is a presentation count of exact position
  states `STALE`, `HALTED`, or `EXIT_PENDING`; it must remain labeled `need
  attention` and source-scoped.

## Radar, Accepted, And Rejected

### Radar list

The existing Live Universe is sufficient for a table/list interpretation of
Radar. It already carries rank, symbol, price, percent change, RVOL, catalyst,
score through the wrapped `CandidateSnapshot`, source opportunity wording,
evidence quality/readiness, and UI-only age. Rank is the incoming collection
position; the presentation does not rerank (`CommandCenterModels.cs:6-9` and
`:57-60`).

### Radar map

There is no safe mapping from score/RVOL/age to angle, radius, color, or motion.
Those choices would create semantics the engine does not own. A future map
would first need an approved definition of axes, normalization, population,
time window, and stable identity, then a versioned read model. Until then the
map is `UNAVAILABLE`, not an empty-but-implied live surface.

### Accepted and Rejected

The following near-matches do not establish candidate disposition:

- `ReadinessState.ReadyForSimulation` is evidence/readiness, not acceptance.
- `RiskDecision.Allowed` is the selected TradePlan's current risk evidence,
  not durable membership in Accepted.
- a green `SourceReadinessLabel` is free text, not a normalized enum.
- `DailyWorkflowReviewCounts.Rejected` is a different workflow and has no row
  reason/time in the Command Center snapshot.
- `ShadowSampleStatus.RiskRejected` is a test-trade sample statistic.

A future accepted/rejected read model must minimally expose symbol, stable
candidate or membership identity, exact disposition, disposition reason,
decision/event timestamp, source identity, and whether the row is current or
historical. If rates are desired, it must also define the denominator and time
window. WPF must consume that truth; it must not define it.

## Mini-Charts And Markers

The current selected chart is authoritative only for the returned symbol and
interval. It carries exact OHLCV, candle lifecycle/source/timestamps, gaps,
corrections, session dates, and history-load state. Therefore:

- a selected-symbol `15m` chart is available when the 15m request succeeds;
- a two-session crop is UI-only and safe only from already returned candles;
- insufficient sessions remain visibly insufficient;
- WPF may not synthesize 15m candles from another interval;
- WPF may not backfill missing sessions;
- WPF may not issue per-row fan-out merely to imitate mini-charts.

Existing Technical Research and Candidate Story facts can become source-labeled
markers on the selected chart. They are not candidate-machine transition
markers. Exact admission, tier, accepted, rejected, expired, or reactivation
markers require the future typed transition boundary described above.

## Freshness Clocks

| Clock | Current status | Required label discipline |
| --- | --- | --- |
| Candidate report observation (`CandidateSnapshot.ObservedAt`) | Available; UI age derivable | `Observed` / `report age`; never discovery or meaningful change. |
| Catalyst observation (`CatalystSummary.ObservedAt`) | Available | `Catalyst observed`; not candidate admission. |
| Chart as-of/provider/receipt/latest bar | Available | Keep each source clock distinct. |
| Candidate Story first/latest trusted capture | Available | `First capture` / `Latest capture`; not first surfaced/change. |
| Candidate machine first surfaced | Future read-model dependency | Requires Hot Universe membership identity and `firstObservedAt`. |
| Candidate machine last meaningful change | Future read-model dependency | Requires domain-defined qualifying transitions and event identity/time. |

No freshness clock may change rank, score, admission, readiness, risk, alerting,
or action. The current age formatter already documents this separation at
`CommandCenterModels.cs:88-125`.

## Machine Events

The existing What Changed surface is a safe partial machine/evidence log:

1. Activity supplies exact generic source events.
2. Candidate Story supplies stable capture identity and capture time.
3. Technical Research supplies exact event identity, timestamp, timeframe,
   status, trigger price, and notes.

It cannot claim every candidate-machine transition or every reevaluation.
Python's `HotUniverseTransition` is substantially richer, but adding it to WPF
requires a separate versioned read-only contract and mapper. That dependency
does not authorize any Python, lifecycle, strategy, persistence, or execution
change in this directive.

## Positions

Positions are available only as read-only Shadow/FakeBroker evidence derived
from `ShadowTradeReviewSnapshot.ActiveMark`. The safe region may show the
current mapped fields and deterministic totals already implemented. It must
retain the exact source/mode and unavailable states.

It must not say `live positions`, `broker positions`, `account`, `buying power`,
or `At Risk`. It must not add buy/sell/submit/replace/cancel actions. Position
inspection has no effect on trade state.

## System Health

System health is an observation of named component states at checked times.
The compact health projection is safe. It does not prove:

- the market is open;
- the scanner is live;
- all providers are current;
- the strategy is ready;
- execution is enabled;
- uptime or an SLA percentage.

The label must remain data/system health, not trading readiness.

## Forbidden Unsupported Aggregates And Claims

| Reference concept | Current classification | Why it is forbidden now |
| --- | --- | --- |
| `Avg Score (Radar)` / `Avg RVOL (Radar)` | `UNAVAILABLE` | No canonical Radar population or denominator. A displayed-row average would have different semantics. |
| `Accept Rate (Today)` / `Rejection Rate` | `UNAVAILABLE` | No canonical accepted/rejected event set, time window, or denominator in the WPF read model. |
| `Radar 28 +3`, `Accepted 7 +1`, `Rejected 12 -2` | `UNAVAILABLE` | Current counts may be shown only under their real collection names; deltas need prior comparable snapshots and disposition truth. |
| `At Risk 1` | `UNAVAILABLE` | No canonical At Risk definition. Position `need attention` is narrower and source-specific. |
| `Scanner Uptime 99.8%`, items scanned, last scan | `UNAVAILABLE` | No uptime window/heartbeat series/scanner census contract. |
| `MARKET OPEN`, `SCANNER LIVE`, `Live Feed Connected`, footer `Live` | `UNAVAILABLE` | No current authoritative market/scanner/live-execution state. These can imply trading authority. |
| Candidate confidence percentage/bars | `UNAVAILABLE` | Score, readiness, and evidence quality are not probability/confidence. |
| Accepted thesis, target ladder, and `Since` | `FUTURE READ-MODEL DEPENDENCY` | TradePlan has one target; canonical Accepted membership/time/setup thesis is absent. `TradePlanSnapshot` fields are at `WorkstationContracts.cs:406-419`. |
| Daily realized P&L / performance / win rate on the Command Center | `UNAVAILABLE` | Current position P&L is unrealized Shadow/FakeBroker evidence. `ShadowAggregateMetrics`, `WorkstationContracts.cs:854-880`, is a separate sample study and cannot be repurposed as today's live performance. |
| Complete machine chronology | `FUTURE READ-MODEL DEPENDENCY` | Current timeline is intentionally partial; typed Hot Universe transitions are not bridged. |

## Future Read-Model Boundary, If Separately Authorized

Visual fidelity beyond the safe current list would require read-only contracts,
not presentation inference. Separate product/domain work would need to define:

1. a candidate-membership snapshot with stable identity/generation, current
   tier/state/disposition, first surfaced time, last source observation, last
   meaningful transition, and source lineage;
2. a candidate-transition stream with prior/next state and tier, reason,
   source/evaluation/recorded timestamps, and immutable transition identity;
3. explicit Accepted/Rejected membership semantics and a rate denominator/time
   window if aggregate rates are desired;
4. a bounded multi-symbol mini-chart payload with exact symbol, interval,
   sessions, candle quality, and no implicit provider fan-out;
5. separately defined scanner/market availability and uptime contracts if such
   claims are ever approved.

That future boundary must remain read-only for the GUI. It must not change
candidate lifecycle policy, scoring, source order, strategy admission,
readiness, risk, TradePlan generation, replay identity, broker behavior, order
behavior, or execution authority.

## Inventory Conclusion

The visual-fidelity task can safely reuse the current header safety context,
Live Universe/Radar list, selected chart, partial machine events, read-only
Positions, and data health. It can derive exact counts, formatting, a bounded
two-session crop of already loaded selected-symbol candles, and source-labeled
existing-event markers.

It cannot truthfully implement Radar geometry, canonical Accepted/Rejected
regions or rates, rejected-at chronology, first-surfaced/last-meaningful-change
freshness, multi-symbol mini-charts, complete machine transitions, scanner or
market-live claims, uptime, confidence, At Risk, or live performance
aggregates. Those items must be omitted, labeled unavailable, or deferred to a
separately authorized read-model task.
