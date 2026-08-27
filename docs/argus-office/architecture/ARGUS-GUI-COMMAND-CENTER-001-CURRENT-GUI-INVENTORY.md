# ARGUS-GUI-COMMAND-CENTER-001 Current GUI Inventory And Reuse Map

## Verdict

`INVENTORY_COMPLETE = YES`

The existing WPF workstation already contains most of the required operator
capabilities. The safe implementation is a composition and presentation task,
not a second dashboard and not a backend expansion. The Command Center should
reuse the established AvalonDock panes and selected-symbol/link-group flow.

## Four-Zone Composition

| Command Center zone | Existing surface | Decision | Builder direction |
| --- | --- | --- | --- |
| Live Universe / Attention | `HunterAnchor`, `CandidateGrid`, `ShellViewModel.Candidates`, `CandidateSnapshot` | `MOVE / COMBINE` | Rename and restyle the existing Hunter pane. Add a presentation-only attention-row wrapper for rank, UI age, opportunity label, and evidence label. Keep selection routed through `SelectCandidateAsync`. |
| Focus Candidate / Market Story | `PrimaryChartDocument`, `ChartPaneViewModel`, `CandleChart`, chart link/pin/interval controls | `KEEP / MOVE` | Keep the current chart as the center of gravity. Add concise selected-symbol/story framing from already loaded candidate/chart/story data. Preserve provider/history honesty and inspection behavior. |
| Decision / Why / Evidence | `TradePlanAnchor`, current Plan/Why/Research/History tabs, `TradePlanSnapshot`, readiness checks, Risk Decision, candidate evidence bindings | `COMBINE / MOVE` | Reframe the existing right pane as Decision / Why. Put current answer, reason, and separate Opportunity/Evidence labels first; retain existing detailed tabs as secondary evidence. Do not infer missing plan values. |
| What Changed / Decision Timeline | `ActivityAnchor`, `ActivityRows`, `CandidateStoryRows`, `TechnicalResearchEventRows`, candidate selection | `NEW` composite hosted in existing pane | Make the existing bottom Activity pane visible by default and host a presentation-only chronological composite. Selection may expose the immutable identity/detail already present in Candidate Story; it must not rewrite the current decision. |

## Capability Inventory

| Capability requested | Current implementation | Classification | Reuse decision |
| --- | --- | --- | --- |
| Candidate/Hunter list | `HunterAnchor`, `CandidateGrid`, `Candidates`, `SelectedCandidate` | `MOVE / COMBINE` | Becomes Live Universe. Preserve the current candidate source and selection path. |
| Live Universe equivalent | Hunter plus Saved Watchlist | `COMBINE` | Hunter is the default live attention list. Saved Watchlist remains a secondary pane, not a duplicate default list. |
| Main chart/history | `PrimaryChartDocument`, `ChartPaneViewModel`, `CandleChart`, interval controls | `KEEP` | Reuse without candle aggregation or capture-policy changes. |
| TradePlan | `TradePlanAnchor`, `TradePlanSnapshot`, level/check/risk bindings | `MOVE / COMBINE` | Becomes the answer-first Decision surface; detailed plan remains read-only. |
| Risk Governor display | `TradePlan.RiskDecision`, checks, risk summary | `KEEP / MOVE` | Keep as secondary evidence under the current answer. No risk recomputation. |
| Positions | `PositionsAnchor`, `OpenPositions`, top Positions button, read-only Shadow review mapping | `KEEP` | Preserve obvious access and current read-only fields. Do not add order actions. |
| History/Activity | `ActivityAnchor`, `ActivityRows`, TradePlan History tab | `COMBINE` | Host What Changed in Activity; preserve raw Activity as lower-detail evidence. |
| Why/evidence | TradePlan Why tab, Candidate Story, Alert Evidence, Candidate Quality/Lineage | `COMBINE` | Surface Why now / Why trade or not above detailed evidence. |
| Candidate Story | `CandidateStoryAnchor`, `CandidateStoryOverview`, `CandidateStoryRows` | `RETIRE_FROM_DEFAULT_LAYOUT / COMBINE` | Keep accessible through panes/command palette; reuse its immutable capture identities in the timeline/detail shell. |
| Research Maturity | `ResearchMaturityAnchor` | `RETIRE_FROM_DEFAULT_LAYOUT` | Preserve as a specialist pane; it does not belong in the selected-ticker default hierarchy. |
| Technical Research | `ResearchAnchor`, technical event/study rows | `RETIRE_FROM_DEFAULT_LAYOUT / COMBINE` | Preserve pane and reuse exposed events only when they add honest selected-symbol context. |
| Command palette | `CommandPalette`, Ctrl+K overlay, pane actions | `KEEP` | Preserve behavior and regressions; do not add execution commands. |
| Health/status | `HealthButton`, `DiagnosticsAnchor`, `HealthDiagnosticsView`, status bar | `MOVE / COMBINE` | Add a compact high-level badge on the default surface and retain Diagnostics as drill-down. |
| Workspace/docking | AvalonDock layout, `PaneRegistry`, persistence, link/pin commands | `KEEP` | Reuse existing content IDs and pane kinds so stored layouts and pane recovery remain compatible. |
| Orders pane | Informational locked/unavailable text only | `RETIRE_FROM_DEFAULT_LAYOUT` | Keep hidden. It supplies no Command Center function and must not become actionable. |
| Automation/monitoring | Read-only monitoring pane | `RETIRE_FROM_DEFAULT_LAYOUT` | Keep accessible as diagnostics; do not put service controls in the Command Center. |

## Existing Read Models Available To The Builder

- `CandidateSnapshot`: symbol, company, price/change, volume/RVOL, catalyst,
  readiness, score, liquidity, observed time, source readiness label, lineage,
  and opportunity notes.
- `ChartPaneViewModel` / `ChartSnapshot`: selected-symbol candles, actual
  interval, source/quality/history-load status, timestamps, gaps, corrections,
  and stale/unavailable state.
- `TradePlanSnapshot`: entry, stop, one target, risk/share, simulated quantity,
  reward/risk, readiness, checks, levels, lineage, and risk decision.
- `ActivityEvent`: timestamp, category, message, symbol, and health state.
- `CandidateStorySnapshot`: stable capture/identity keys, captured time, price,
  score, RVOL, capture note, later annotation, source context, and trust.
- `TechnicalResearchSnapshot`: selected-symbol event timestamps/types/statuses
  and later study results where persisted.
- `SystemHealthSnapshot`: high-level component states and checked times.
- `OpenPositionView`: read-only position, mark, unrealized P/L, R, stop, next
  target, state, freshness, and source fields when evidence exists.

## Required Presentation-Only Additions

1. A GUI-local attention-row view that wraps `CandidateSnapshot` without
   changing contracts. It may format rank and age and place source opportunity
   wording beside evidence/readiness wording. It may not sort or rank on age.
2. A GUI-local current-decision view that formats exact exposed values and
   labels unavailable values honestly.
3. A GUI-local timeline item view composed only from Activity, Candidate Story,
   and already exposed research events. Every timestamp and identity must cite
   its source kind.
4. A selected timeline-detail state that is visibly historical and independent
   of the current decision. Navigation is limited to exposed immutable capture
   identity; no retrospective TradePlan reconstruction is allowed.
5. A compact health view derived from the existing diagnostics mapper.

## Current Read-Model Limitations

These are implementation constraints, not permission to alter backend code:

- There is no canonical, independent per-candidate opportunity-state and
  evidence-state DTO. The UI can keep `SourceReadinessLabel`/operator wording
  separate from existing readiness/quality/chart evidence, but must label the
  result as presentation of exposed fields rather than new engine truth.
- There is no canonical decision-delta stream. What Changed is therefore
  `PARTIAL`: it can show persisted Activity, Candidate Story captures, and
  technical events, but cannot claim every reevaluation or TradePlan transition.
- The C# plan contract exposes one target, not Target 2, and does not expose a
  canonical setup type. Display `Unavailable in current read model`; do not infer.
- Current-decision TradePlan identity/history is not exposed in the live C#
  workspace contract. Historical navigation is `PARTIAL` and limited to stable
  Candidate Story capture identities and their frozen evidence details.
- Candidate rows do not carry candle series. Do not fan out chart/provider
  requests or draw invented sparklines. Per-row micro charts are deferred.
- The main chart may show pre-discovery history only to the extent its current
  stored-candle client already returns it. No new horizon or aggregation policy
  is authorized.
- Health component names depend on the existing snapshot; absent provider,
  clock, or history components must be labeled unavailable, not synthesized.

## Future Read-Model Requirements Discovered

Separate post-freeze work may consider a versioned read-only Command Center
contract containing independent opportunity/evidence states, immutable decision
and successor identifiers, explicit decision deltas/reasons, setup type,
multiple targets, per-candidate comparable candle summaries, and a frozen
historical decision snapshot. None is implemented by this task.

## Operator-Visible Screenshot Baseline Addendum — 2026-08-26

### Authority and reconciliation

The supplied 1672×941 screenshot was inspected at original detail. It is an
operator-visible visual baseline, not evidence that the displayed symbols,
counts, rates, P&L, uptime, session state, scan totals, timestamps, or live-feed
authority exist in the application. The approved Command Center directive is
newer and controls information architecture: the selected ticker remains the
center of gravity in the four-zone workspace. The screenshot contributes shell
rhythm, density, color language, and discoverability; it does not replace the
chart/decision/evidence requirements or authorize new engine data.

### Visible-element disposition

| Screenshot surface | Decision | Implementation/reuse rule |
| --- | --- | --- |
| Fixed left navigation rail (`Console`, `Radar`, `Accepted`, `Rejected`, `Positions`, `Analytics`, `Settings`) | `NEW` shell chrome | A narrow fixed rail may focus an existing pane, apply a presentation-only candidate filter, or open the existing command palette. It must not create duplicate pages, a second navigation model, or runtime commands. Labels with no honest current destination must be omitted/disabled, not simulated. |
| Top brand, clock, market/scanner/health strip | `COMBINE` | Keep the compact header rhythm. Bind only current clock plus existing `ShellViewModel`/`HealthDiagnosticsView` status, `ScanStateLabel`, `StatusText`, `LastRefreshText`, and selected `ChartQuality`. Do not assert `MARKET OPEN`, `SCANNER LIVE`, `All Systems Go`, or a live-feed connection without an authoritative contract. |
| Top averages, accept/rejection rates, uptime | `RETIRE_FROM_DEFAULT_LAYOUT` | The screenshot's `Avg Score`, `Avg RVOL`, `Accept Rate (Today)`, `Rejection Rate`, and `Uptime` are not canonical current contracts. A visible-snapshot average could be a clearly labeled presentation calculation later, but it is not part of this Builder slice. Never hard-code the screenshot values. |
| `RADAR` summary card | `COMBINE` | Show the current candidate/radar row count from the loaded candidate collection. The `+3` delta is unavailable unless derived from an explicitly UI-session-local prior snapshot and labeled nonauthoritative. |
| `ACCEPTED` summary card | `COMBINE` | Filter/count the same candidate collection by its exposed current opportunity state; do not create a second accepted data source. The `+1` delta and `Qualified` implication are unavailable unless already stated by the row. |
| `REJECTED` summary card | `COMBINE` | Filter/count the same candidate collection by exposed current opportunity state. The `-2`, `Filtered Out`, and rejection-time history shown in the mockup are not available as canonical daily aggregates. |
| `POSITIONS` summary card | `COMBINE` | Count the existing `OpenPositionView` rows and label their existing Paper/Shadow/FakeBroker authority honestly. It must not imply Schwab/live-account authority. |
| `AT RISK` summary card | `RETIRE_FROM_DEFAULT_LAYOUT` | No current contract defines the screenshot's per-position `At Risk` classification/count. Existing Risk Governor state and `RiskOnStop` are different facts and must not be relabeled. |
| `RADAR MAP` polar plot | `RETIRE_FROM_DEFAULT_LAYOUT` | No current view or contract defines polar axes, placement, or comparable multi-symbol history. Arbitrary score/RVOL geometry would imply unsupported analysis and would displace the required selected-ticker chart. Reconsider only with a defined read model and operator purpose. |
| `RADAR TOP 10` table | `COMBINE` | This becomes Zone 1's existing Hunter/Candidates grid, sorted/filterable through presentation state. Reuse symbol, score/rank, RVOL, catalyst, price/action text, state, quality/evidence label, and UI freshness only where exposed. Do not add per-row chart/provider fan-out. |
| Separate `ACCEPTED` table | `COMBINE` | Make `Accepted` a filter/view of Zone 1, preserving selected-symbol synchronization; do not pin a second table beside the chart. Screenshot thesis, target ladder, confidence, and since-time columns are not all present in one candidate read model. |
| Separate `REJECTED` table | `COMBINE` | Make `Rejected` a filter/view of Zone 1 or an existing pane activation. Exact rejection chronology/reason is shown only when supplied by existing activity/evidence; do not derive it from color or absence. |
| `MACHINE LOG / RECENT EVENTS` | `COMBINE` | Use Zone 4's existing Activity anchor to host the read-only chronological composite of `ActivityRows`, `CandidateStoryRows`, alerts, and technical-research events. Keep source labels and immutable identities visible in drill-down. Do not invent event text or merge distinct evidence into one authoritative lifecycle. |
| `POSITIONS` table | `KEEP` | Reuse the existing Positions pane and `OpenPositionView` columns (mark, P&L, R, stop, target, quote age/source, display state). It may be focused from the rail or docked in the lower workspace; it is not a replacement for Zone 4. |
| `STATS (TODAY)` | `RETIRE_FROM_DEFAULT_LAYOUT` | `Items Scanned`, today's rates, uptime, and last-scan aggregation in the screenshot have no complete canonical read model. Supported current-snapshot facts belong in the truthful header or diagnostics, not an imitation panel. |
| Footer, freshness legend, version/time/live badge | `COMBINE` | Reuse the existing status/footer area for actual last refresh, chart quality/source, quote age, connection/report status, and a UI-only freshness legend. Do not show a hard-coded version, `Data is real-time`, or `Live` without authoritative values. |
| Dark navy visual language, fine separators, compact tables, blue selection, green/red/amber state accents | `KEEP` | Carry these visual tokens into WPF resources while preserving readable type, keyboard focus, tooltips, scroll behavior, minimum pane sizes, and existing semantic state colors. Use information-dense rows, but leave the selected ticker/chart/decision path visually dominant. |

### Freshness correction

The screenshot's legend says `NEW < 15m` and `NEW = first 15m after discovery`.
That definition is superseded by Steven's later explicit UI-only semantics:

- `NEW`: 0–30 minutes;
- `RECENT`: 30 minutes–2 hours;
- `EARLIER`: 2+ hours, or show the absolute seen/changed time when clearer.

These labels are visual awareness only and must never affect admission, rank,
score, readiness, risk, trade timing, or execution. Current contracts do not
carry durable candidate first-seen or material-change timestamps. Builder may
track first-visible/materially-changed time in presentation memory for the
current GUI session, label it as UI freshness, and allow it to reset on restart.
`CandidateSnapshot.ObservedAt` is report observation time and must not silently
be relabeled as discovery time. Durable cross-session freshness remains a future
read-model requirement.

### Screenshot-versus-current-WPF gaps

- Current WPF is an AvalonDock pane workspace with a Hunter/Chart/TradePlan
  default, command palette, saved layouts, and optional lower panes; the
  screenshot is a fixed dashboard with duplicated summary/table regions.
- Current WPF already has the required selected-symbol chart with `1m`, `5m`,
  `15m`, and `Daily` intervals; the screenshot has no focus chart, no chart
  quality/source, and no earlier-decision selection. The existing chart wins.
- Current TradePlan, Why, Evidence, Risk, Candidate Story, Activity, Alerts,
  Positions, Replay, Research Maturity, and diagnostics content has no direct
  one-panel equivalent in the screenshot. It must be reused, not discarded.
- There is no Radar Map component, canonical polar coordinate model, row
  sparkline collection, durable candidate age, complete market-session state,
  scanner uptime, daily throughput/rates, `At Risk` classification, or unified
  accepted/rejected event ledger in current contracts.
- C# `TradePlanView` exposes entry, stop, and one target; it does not provide the
  screenshot's target ladder as a candidate-table field. It also lacks setup
  type and predecessor/successor decision navigation.
- Shadow/Replay evidence can expose immutable historical identities, but the
  current selected chart is not a frozen decision-time chart. Builder must not
  present ordinary current candles as historical decision context.
- Screenshot sample symbols and metrics are mock content. No value visible in
  the image may ship as a fallback, demo default, or implied live authority.

### Revised four-zone implementation lock

The fixed rail and header are shell chrome outside the workspace. Inside them,
the default built-in layout is locked to:

1. **Left — Candidates:** one Hunter/Candidates collection with Radar,
   Accepted, and Rejected filters, explicit selection, state/evidence labels,
   and the corrected UI-only freshness buckets.
2. **Center — Market Story:** the existing selected-ticker `PrimaryChart`
   remains largest, synchronized to Zone 1, with existing interval/session and
   chart quality/source behavior. No Radar Map or multi-symbol mini-chart fan-out.
3. **Right — Decision / Why / Evidence:** combine existing TradePlan, Why,
   evidence, Risk Governor, and honest blocker context for the selected ticker.
   Missing target ladder, setup identity, or historical identity is displayed
   as unavailable, never inferred.
4. **Bottom — What Changed:** make the existing Activity host visible and
   compose existing Candidate Story, Activity, Alerts, and research-event rows
   chronologically. Selecting an immutable historical item may show only the
   frozen detail actually exposed; it must not mutate current selection truth or
   imply that the live chart is the historical chart.

Positions, Replay/Test Trade Review, Technical Research, diagnostics, and other
kept/moved panes remain reachable by docking, command palette, or the fixed
rail. They do not displace the four-zone default. Existing saved named layouts
remain user-owned; any one-time built-in layout reset must be GUI-only and must
not delete named layouts.

### Exact Builder handoff

Builder may implement only the composition above and must stop at missing data.
The production-file allowance is exactly:

- `src/MomentumHunter.Presentation/ShellViewModel.cs`;
- `src/MomentumHunter.Presentation/WorkspaceFactory.cs`;
- new presentation-only `src/MomentumHunter.Presentation/CommandCenter*.cs`;
- `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml`;
- `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml.cs` only for existing WPF
  selection/docking/keyboard behavior that cannot remain declarative;
- `src/MomentumHunter.Desktop.Wpf/App.xaml` only for Command Center visual
  resources; and
- focused tests under `tests-dotnet/MomentumHunter.Presentation.Tests/**` and
  `tests-dotnet/MomentumHunter.Layout.Tests/**`, plus task documentation/proof.

The first Builder pass should create the truthful shell/header, single filtered
candidate surface, selected-symbol synchronization, four-zone default,
Decision/Why/Evidence composition, What Changed composition, and UI-only
freshness formatter. It must not implement Radar Map, per-row sparklines,
today/rate/uptime statistics, At Risk classification, new provider calls,
historical candle synthesis, or any contract/runtime fallback. Those omissions
are honest scope outcomes, not reasons to cross the protected boundary.

## Builder File Boundary

Allowed production edits are limited to:

- `src/MomentumHunter.Presentation/**` for presentation-only view types and
  `ShellViewModel`/`WorkspaceFactory` composition;
- `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml` and narrowly necessary WPF
  code-behind for selection/visual behavior;
- GUI-focused files under `tests-dotnet/MomentumHunter.Presentation.Tests/**`
  and `tests-dotnet/MomentumHunter.Layout.Tests/**`;
- task-specific docs and screenshots.

Do not change `PaneKind`, shared Contracts, Application, EngineBridge,
Infrastructure, Python, project/package files, configuration, services,
scheduler, providers, Paper, Shadow, broker, account, order, or installed files.

## Protected-Path Review

Protected and excluded: `momentum_hunter/**`, Continuous runtime/producer paths,
`src/MomentumHunter.Contracts/**`, `src/MomentumHunter.Application/**`,
`src/MomentumHunter.EngineBridge/**`, `src/MomentumHunter.Infrastructure/**`,
service hosts, manifests/configuration, databases/generated data, providers,
Paper/Shadow, broker/account/order, canary worktrees/evidence, and canonical
installation/startup pointers.

## App Architect Report

- Branch: `codex/ARGUS-GUI-COMMAND-CENTER-001`.
- Scope: current WPF inventory, reuse decisions, boundary and limitation map.
- Files changed: this architecture artifact only.
- Tests/checks: source inventory of WPF, Presentation, Contracts, and focused
  GUI tests; original-detail inspection of the 1672×941 operator screenshot;
  no product tests or runtime actions.
- Evidence for changed behavior: no behavior changed; the artifact defines the
  smallest implementation slice.
- Protected areas reviewed: all excluded paths above; no edits.
- Push/merge status: none.
- Risks: timeline and decision navigation remain partial until richer immutable
  read models exist; row sparklines, daily/rate/uptime cards, At Risk count, and
  durable freshness are unavailable without additional read models.
- Manual QA: not applicable until Builder produces visual proof.
- Open questions: none for the bounded GUI slice.
- Recommendation: Builder should implement the four-zone composition by
  reusing existing pane/content identities and stop at any backend dependency.
