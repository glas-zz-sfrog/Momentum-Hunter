# ARGUS-GUI-COMMAND-CENTER-001 Visual Baseline Addendum

## Status And Authority

`VISUAL_BASELINE_REVIEWED = YES`

This design-only addendum reconciles Steven's 1672x941 operator-visible
baseline screenshot at
`C:\Users\steve\AppData\Local\Temp\codex-clipboard-3aff49ae-b729-4e30-a313-428b1795fc1a.png`
with the Goal Charter and
`ARGUS-GUI-COMMAND-CENTER-001-CURRENT-GUI-INVENTORY.md`. The screenshot is
authoritative for visual language and visible information density. It is not a
source of engine, position, health, confidence, acceptance, or execution truth.

The resulting design remains a read-only research workstation. It reuses the
current WPF panes, selection flow, chart, docking, command palette, diagnostics,
activity evidence, and Positions surface. It creates no app code, backend
contract, strategy semantic, provider call, order action, or runtime behavior.

## Operator-Visible Baseline

Steven currently sees a dark navy command console with:

- a persistent brand and status frame;
- a narrow icon-and-label navigation rail;
- compact summary cards with large values and restrained semantic color;
- high-density tables with clear column rhythm and tabular numerals;
- blue/cyan for focus and system context, green for favorable/ready, amber for
  warning/newness, and red for rejected/problem states;
- a radar plot, ranked candidates, accepted and rejected lists, recent machine
  events, positions, and daily statistics visible at once;
- small timestamps, freshness labels, and source/status text supporting the
  primary answer rather than competing with it.

Preserve the calm, precise, low-glare visual language, compact telemetry, thin
borders, rounded panel grouping, and strong state scanning. Do not preserve
unsupported numbers or the implication that Momentum Hunter has live execution
authority.

### Visual Tokens To Preserve

Use existing WPF resources where they are equivalent; do not introduce a font
or package dependency merely to match the screenshot.

| Purpose | Target treatment |
| --- | --- |
| App background | Near-black navy, approximately `#06131F` |
| Panel surface | Navy blue, approximately `#0B1B2A`; one lighter nested level near `#0E2233` |
| Dividers | One-pixel blue-gray near `#1B3D55`; avoid bright box outlines |
| Primary text | Cool white near `#E7F2FB` |
| Secondary text | Blue-gray near `#91A8B9`; never below readable contrast |
| Focus/current | Cyan-blue near `#4CA3FF`, with a shape or label as well as color |
| Positive/ready | Green near `#65C466`, reserved for exposed ready/healthy truth |
| Warning/newness | Amber near `#E0A72E` |
| Rejected/error | Red near `#F45B5B`; never the only discriminator |
| Typography | Existing Windows/WPF sans-serif; 12-13 px body, 11 px metadata, 16-22 px answer/symbol; uppercase only for short labels |
| Density | 8 px base spacing; 10-12 px panel padding; 54-60 px attention rows; 28-34 px compact timeline rows |

## Screenshot-To-Source Reconciliation

| Visible baseline element | Current source/read-model truth | Decision | Command Center treatment |
| --- | --- | --- | --- |
| Momentum Hunter brand and dark console frame | Existing WPF shell and status bar | `KEEP` | Preserve brand, dark shell, slim separators, and compact operator density. |
| Top market/scanner/time strip | `SystemHealthSnapshot`, chart checked/received times, and status message exist; a canonical market-open or scanner-live contract is not established by the inventory | `COMBINE / RETIRE_FROM_DEFAULT_LAYOUT` | Show exact `checked/received/as of` times and compact data health. Do not show `MARKET OPEN`, `SCANNER LIVE`, a green live dot, or uptime unless an existing authoritative field supplies that exact meaning. |
| Avg Score, Avg RVOL, Accept Rate, Rejection Rate, Uptime | Per-candidate score/RVOL and component health exist; these aggregate metrics are not exposed as canonical Command Center truth | `RETIRE_FROM_DEFAULT_LAYOUT` | Keep selected-row score/RVOL where exposed. Do not average, calculate rates, relabel score as confidence, or synthesize uptime in WPF. |
| Left Console/Radar/Accepted/Rejected/Positions/Analytics/Settings rail | Existing panes, `PaneRegistry`, Panes menu, command palette, Positions, Activity, Diagnostics, Research | `KEEP / COMBINE` | Recast as a workspace rail that focuses existing content IDs. Primary items: Command Center, Positions, History/Activity, Evidence/Research, Health. Accepted/rejected/watch are filters within Live Universe only when the exposed row label supports them, not duplicate pages. Settings/automation remain secondary. |
| Radar/Accepted/Rejected/Positions/At Risk summary cards | `Candidates`, `OpenPositions`, selected candidate, and system health exist; canonical Accepted/Rejected/At Risk aggregates do not | `COMBINE / MOVE` | Replace the tall five-card row with a slim truth-only summary strip: Universe count, selected symbol, data health, and source-labeled research/simulated position count. Omit any unavailable card rather than displaying zero or a guessed state. |
| Radar Map | No canonical spatial/radial semantic and no per-candidate candle series | `RETIRE_FROM_DEFAULT_LAYOUT` | Remove from the default layout. The existing `CandleChart` becomes the center of gravity. Do not create a decorative scatterplot or fan out provider requests. |
| Radar Top 10 | `HunterAnchor`, `CandidateGrid`, `Candidates`, `SelectedCandidate`, `SelectCandidateAsync` | `MOVE / COMBINE` | Becomes the left Live Universe / Attention list. Preserve the current selection path and source ordering unless an existing user sort is selected. |
| Separate Accepted and Rejected tables | No independent canonical per-candidate opportunity/evidence DTO; exposed readiness/operator words may be displayed separately | `COMBINE / RETIRE_FROM_DEFAULT_LAYOUT` | Express state in each Live Universe row and optional truthful filters. Do not duplicate the same candidates in two always-visible lists or publish aggregate rates from presentation inference. |
| Confidence bars and target ladders | Candidate score is not confidence; C# TradePlan exposes one target, not a ladder/Target 2 | `RETIRE_FROM_DEFAULT_LAYOUT` | Label score as score only. Show Target 1 exactly when exposed and `Unavailable in current read model` for Target 2 when the field is part of the detail design. |
| Machine Log / Recent Events | `ActivityAnchor`, `ActivityRows`, `CandidateStoryRows`, technical research events | `MOVE / COMBINE` | Becomes the first-class bottom What Changed timeline. Raw Activity remains an expandable evidence view. |
| Positions table and navigation | `PositionsAnchor`, `OpenPositions`, command palette action, source/freshness fields | `KEEP` | Preserve obvious access and docking. Label the exact research/simulation/shadow source prominently. No buy, sell, submit, replace, cancel, arm, approve, or lifecycle-advance action appears. |
| Stats (Today) panel | Some individual values exist elsewhere; daily aggregates shown in the screenshot are not canonical current read-model fields | `RETIRE_FROM_DEFAULT_LAYOUT` | Replace with compact data health and selected-symbol context. Raw metrics belong in Diagnostics only when already exposed. |
| Footer `Live Feed Connected`, `Data is real-time`, and green `Live` indicator | Existing data/source status does not grant trading or execution authority | `RETIRE_FROM_DEFAULT_LAYOUT / COMBINE` | Use `READ-ONLY RESEARCH EVIDENCE`, exact source, and exact checked/received time. If data is connected, say `DATA CONNECTED`; never shorten this to `LIVE`. |
| Screenshot `NEW < 15m` legend | Superseded by Steven's current visual-awareness thresholds | `MOVE / REPLACE` | Use the UI-only freshness semantics below. They must not affect rank, admission, readiness, risk, timing, or execution. |
| Current WPF Simulation button and `Run FakeBroker simulation` action | Existing research workflow, but not a Command Center read-only purpose | `RETIRE_FROM_DEFAULT_LAYOUT` | Keep outside the default Command Center in its existing specialist/review workflow if still required. The Command Center itself contains no simulation or trading action. |
| Separate Opportunity and Evidence labels | Neither the screenshot nor the current pane hierarchy distinguishes them consistently; exact exposed source wording is available for a GUI-local presentation | `NEW` | Add the paired, independently labeled presentation described below without claiming a new canonical engine state. |
| Historical-versus-current context treatment | Candidate Story has stable capture identities, but the screenshot does not visibly protect current truth from selected historical evidence | `NEW / COMBINE` | Add explicit current and historical visual modes and compose traceable history into the reused Activity pane; do not reconstruct prior TradePlans. |

## Final Four-Zone Layout

The default workspace reuses AvalonDock identities rather than creating a
parallel dashboard:

1. `HunterAnchor` becomes **Live Universe / Attention**.
2. `PrimaryChartDocument` and `CandleChart` become **Focus Candidate / Market
   Story**.
3. `TradePlanAnchor` becomes **Decision / Why / Evidence** while retaining its
   detailed read-only tabs.
4. `ActivityAnchor` is visible by default as **What Changed / Decision
   Timeline**, composed from existing activity, Candidate Story, and research
   evidence.

`PositionsAnchor`, Diagnostics, Candidate Story, Technical Research, Research
Maturity, Saved Watchlist, Automation, and Orders retain their current content
IDs and reopen/focus behavior. Positions and Diagnostics remain obvious
secondary destinations; the other specialist panes do not occupy default
Command Center space. Orders remains hidden and nonactionable.

### Normal Workstation Frame: 1920x1080 Class

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ 48 px APP BAR: MH | COMMAND CENTER | exact as-of time | READ-ONLY RESEARCH │
├──────┬─────────────────────────────────────────────────────────────────────┤
│      │ 36 px TRUTH STRIP: Universe | Selected | Data health | Positions*  │
│ 72px ├──────────────┬──────────────────────────────────┬───────────────────┤
│ rail │ LIVE         │ FOCUS CANDIDATE / MARKET STORY   │ DECISION / WHY    │
│      │ UNIVERSE     │ current/historical context bar  │ paired OPP/DATA   │
│      │ 320 px       │ chart + exact source/horizon    │ answer + reason   │
│      │ sticky head  │ story: catalyst/RVOL/context    │ plan + evidence   │
│      │ 54-60px rows │ flexible, target >= 1100 px     │ 396 px            │
│      │              ├──────────────────────────────────┴───────────────────┤
│      │              │ WHAT CHANGED / DECISION TIMELINE, target 220-236 px │
├──────┴──────────────┴──────────────────────────────────────────────────────┤
│ 22-24 px status: exact source/check time | read-only/no order capability   │
└────────────────────────────────────────────────────────────────────────────┘
```

After the 72 px rail, use approximately 320 px for Live Universe, a flexible
center with a 720 px normal minimum, and 380-410 px for Decision. The bottom
timeline spans the Focus and Decision columns; Live Universe remains visible
at full workspace height. The chart owns the largest single rectangle.

### Compact Frame: Approximately 1180x820

```text
┌────────────────────────────────────────────────────────────────────────────┐
│ 44 px APP BAR: MH | CC | as-of | READ-ONLY | Health | Positions | Ctrl+K  │
├────┬───────────────────────────────────────────────────────────────────────┤
│    │ 30 px TRUTH STRIP: Universe | Data | Positions* | Selected symbol    │
│48px├───────────┬────────────────────────────┬──────────────────────────────┤
│icon│ LIVE      │ FOCUS / MARKET STORY       │ DECISION / WHY               │
│rail│ UNIVERSE  │ symbol + current context   │ OPP and DATA on separate rows│
│    │ 248 px    │ chart, target 540 px       │ answer/reason pinned         │
│    │ 54px rows │ source/horizon below title │ 328 px; detail scrolls       │
│    │           ├────────────────────────────┴──────────────────────────────┤
│    │           │ WHAT CHANGED, 168-180 px; concise rows; detail on select │
├────┴───────────┴───────────────────────────────────────────────────────────┤
│ 22 px status: READ-ONLY RESEARCH | exact source/check time                 │
└────────────────────────────────────────────────────────────────────────────┘
```

At 1180x820, supported targets are: 48 px icon rail, 248 px Live Universe,
328 px Decision, two 8 px splitters/gutters, and the remaining approximately
540 px for Focus. The main row receives approximately 520-540 px height and
the timeline 168-180 px. The chart remains readable; answer and decisive reason
stay visible without scrolling.

Below the supported compact width, do not squeeze all text indefinitely. Keep
the chart at a 480 px hard visual minimum, Live Universe at 236 px, and Decision
at 312 px. Collapse the timeline to a labeled bottom drawer showing its latest
row and expose hidden panes through the existing Panes menu/command palette.
Every zone must retain a visible dock handle or focus command; no whole-window
horizontal scrollbar is allowed.

## Zone Content And Hierarchy

### 1. Live Universe / Attention

- Sticky header: `LIVE UNIVERSE`, exact item count, search/filter affordance,
  and a short `UI age only` tooltip on freshness.
- Row line 1: rank/priority when exposed, untruncated symbol, exact price and
  change, then freshness at the trailing edge.
- Row line 2: two separately bordered compact labels, `OPPORTUNITY` and
  `EVIDENCE`; never one combined status pill.
- Row line 3: catalyst type/age and one concise reason when exposed. Omit the
  line if empty.
- Keep candidate source order by default. UI freshness never changes ordering.
- Do not draw row sparklines: `CandidateSnapshot` does not carry comparable
  candles. Reserve no empty sparkline slot.

### 2. Focus Candidate / Market Story

- Title row: selected symbol, company, exact price/change, current/historical
  context, link/pin behavior, and actual chart interval.
- `CandleChart` fills the pane. Show the exact source, actual stored interval,
  checked/received time, and availability/staleness state in a quiet strip.
- A compact story band below or above the chart answers `Why now?` with exposed
  catalyst, RVOL, score, and opportunity notes. Do not imply that discovery is
  the start of market history.
- Pre-discovery candles appear only when returned by the current stored-candle
  client. Missing finer/coarser/Daily history is labeled as unavailable rather
  than backfilled or aggregated in WPF.

### 3. Decision / Why / Evidence

Order content as:

1. `CURRENT` or `HISTORICAL EVIDENCE` context;
2. paired Opportunity and Evidence states;
3. one large answer and a two-line maximum decisive reason;
4. exact entry, stop, Target 1, readiness, blocker, RVOL, and market context;
5. `Why now?` and `Why trade / why not?` compact expansions;
6. Risk Decision, checks, lineage, and raw evidence tabs;
7. persistent `READ-ONLY RESEARCH — NO ORDER CAPABILITY` footer.

Target 2 and setup type may occupy labeled detail slots only as `Unavailable in
current read model`; never show blank numeric fallbacks, zero, copied Target 1,
or inferred setup identity.

### 4. What Changed / Decision Timeline

- Sticky header: `WHAT CHANGED`, selected symbol, and `PARTIAL HISTORY` when
  complete decision chronology is unavailable.
- Each row: exact timestamp, source-kind icon/text, concise event or delta,
  current/historical marker, and disclosure affordance when immutable detail
  exists.
- Compose only from `ActivityRows`, stable `CandidateStoryRows`, and already
  exposed technical research events. The row may compare exposed immutable
  snapshots deterministically but may not claim an official engine delta.
- Show `Complete reevaluation chronology unavailable in current read model`
  when gaps exist. Raw Activity is an expansion, not the default hierarchy.
- Selecting a stable Candidate Story identity opens historical evidence without
  overwriting or relabeling the current Decision.

## Opportunity And Evidence Treatments

Use two independently bordered labels with a short prefix, plain-language text,
and a simple line icon. Color is redundant support, never the sole encoding.
Use existing vector/icon resources or simple WPF geometry; do not use emoji.

| State family | Text/icon treatment | Accent |
| --- | --- | --- |
| Opportunity ready/accepted | `OPPORTUNITY  [check]  TRADEPLAN READY` or exact exposed wording | Green |
| Opportunity watch/developing | `OPPORTUNITY  [ring]  SETUP DEVELOPING` | Blue |
| Opportunity missed | `OPPORTUNITY  [turn arrow]  MISSED ENTRY` | Amber |
| Opportunity rejected/strategy blocked | `OPPORTUNITY  [barred circle]  REJECTED/BLOCKED` plus reason | Red |
| Opportunity unknown | `OPPORTUNITY  [?]  UNKNOWN` | Neutral gray |
| Evidence ready | `EVIDENCE  [check shield]  READY` | Green |
| Evidence loading | `EVIDENCE  [clock]  HISTORY LOADING` | Blue |
| Evidence partial | `EVIDENCE  [half ring]  PARTIAL` | Amber |
| Evidence stale | `EVIDENCE  [alert clock]  QUOTE STALE` | Amber-red |
| Evidence unavailable | `EVIDENCE  [broken shield]  UNAVAILABLE` | Gray/red |

Required visual fixtures remain materially distinct:

- amber `MISSED ENTRY` beside green `READY`;
- gray `UNKNOWN` beside blue `HISTORY LOADING`;
- green `RECLAIM READY` beside amber-red `QUOTE STALE`.

The current contracts do not supply a canonical independent state pair. The
presentation may place exact exposed opportunity/operator wording beside exact
readiness/quality/source wording, but it must not invent a canonical state. If
the mapping is not honest, render `UNKNOWN` or `UNAVAILABLE` and retain the raw
source label in detail.

## UI-Only Freshness

The screenshot's `NEW < 15m` language is superseded. Format age from an exposed
observed/captured timestamp only:

| UI category | Deterministic display rule | Treatment |
| --- | --- | --- |
| `NEW` | age `>= 0` and `< 30m` | amber dot + `NEW 7m` |
| `RECENT` | age `>= 30m` and `< 2h` | blue outline + `RECENT 47m` |
| `EARLIER` | age `>= 2h` | neutral clock + `EARLIER 2h 14m` |
| `AGE UNKNOWN` | missing, invalid, or future/skewed timestamp | neutral question icon + `AGE UNKNOWN` |

This is display formatting only. It must not affect sorting, rank, score,
candidate admission, strategy freshness, readiness, risk, timing, alerts, or
execution. It does not assert that a material engine change occurred unless an
exposed event explicitly says so.

## Current Versus Historical Evidence

- Current context uses a solid cyan top rule and the explicit label
  `CURRENT — AS OF <timestamp>`.
- Historical context uses a persistent amber left rule, a lightly tinted header,
  and `HISTORICAL EVIDENCE — CAPTURED <timestamp>`. Do not indicate history by
  gray-out alone.
- When historical evidence is selected, keep a compact current-answer strip at
  the top of Decision and provide `Return to Current`. Historical content may
  not inherit current TradePlan values.
- A selected historical timeline row receives the same amber focus treatment.
  Stable capture/identity detail is secondary and may truncate; the historical
  timestamp and label may not.
- When frozen decision context is not exposed, disable navigation and show
  `Frozen decision details unavailable in current read model`. Never reconstruct
  a prior TradePlan in WPF.

## Density, Truncation, Scrolling, And Docking

- The shell and summary strip remain fixed. Each zone owns its vertical scroll;
  the entire window does not acquire nested whole-page scrolling.
- Live Universe and timeline headers stay visible. Decision keeps context,
  paired states, answer, and decisive reason pinned while details scroll.
- The chart resizes with its pane and never scrolls inside a clipped viewport.
- Symbols, state labels, decisive blocker/reason, current/historical label, and
  safety label are never ellipsized. The reason may wrap to two lines.
- Catalyst headlines, company names, and source names use one-line ellipsis plus
  tooltip. Technical identities/hashes may truncate in drill-down only.
- Numeric columns are right aligned with stable decimal rhythm. Do not let
  changing values move status labels laterally.
- Reuse AvalonDock splitters, floating, hiding, persistence, link, and pin
  behavior. Reuse existing content IDs so saved layouts and pane recovery do not
  fork into duplicate surfaces.
- Closing a primary pane hides it; the existing Panes menu or command palette
  must reopen/focus it. A hidden pane does not silently create a replacement.
- At normal size, use 10-12 px gutters. At compact size, reduce to 8 px before
  reducing type size. Body text must not fall below 11 px.

## Read-Only And Research-Only Safety Language

- Global app bar: `READ-ONLY RESEARCH` with an information/shield icon.
- Status bar: `Research evidence only — no broker/order capability in this
  Command Center`.
- Positions title: `POSITIONS — READ-ONLY` plus the exact source such as
  `SIMULATED`, `SHADOW`, or the exposed source label. Never present a generic
  green `ACTIVE` badge that could be read as live brokerage state.
- Decision footer: `Informational evidence. No order controls.`
- Data health uses `DATA HEALTHY`, `DATA PARTIAL`, `DATA DEGRADED`, or
  `DATA UNAVAILABLE`; it does not say the trading system is ready.
- Do not use `LIVE`, `MARKET OPEN`, `SCANNER LIVE`, `Connected for trading`,
  `At Risk`, confidence bars, or order-shaped controls unless a future
  authoritative contract and separately authorized design explicitly support
  their exact meaning.

The Command Center contains no buy, sell, submit, replace, cancel, order, arm,
approve-for-execution, advance-lifecycle, recovery, service-control, or
simulation action. Positions, historical navigation, pane focus, filters,
chart inspection, and evidence expansion are read-only navigation.

## Steven Visual Proof Frames

Builder/QA should return these safe isolated, nonblank, inspected frames. Each
frame must show the exact viewport in its filename or report.

1. **1920x1080 overall Command Center:** all four zones visible; selected
   candidate, real chart, paired `MISSED ENTRY / READY`, compact data health,
   timeline, read-only banner, and no trading/simulation controls.
2. **1180x820 compact Command Center:** icon rail, compact truth strip, readable
   chart, uncut answer/reason, paired `UNKNOWN / HISTORY LOADING`, and reachable
   What Changed timeline without horizontal scrolling.
3. **State-separation detail:** `RECLAIM READY / QUOTE STALE` plus the other two
   required pairs, proving text, icon, border, and color distinctions.
4. **Historical selection:** an immutable Candidate Story event selected,
   amber `HISTORICAL EVIDENCE` context visible, current-answer strip preserved,
   and no current values masquerading as historical values.
5. **Timeline limitation:** `PARTIAL HISTORY` and the exact unavailable message
   visible alongside traceable Activity/Candidate Story/research rows.
6. **Positions and health:** Positions opened/focused with `READ-ONLY` and exact
   source, Diagnostics reached from compact health, and no broker/order/service
   action present.
7. **Dock/recovery proof:** hide then reopen/focus Activity or Positions through
   the existing Panes menu/command palette; demonstrate preserved content ID,
   selection coordination, and usable 1180x820 resizing.

Steven should reject a frame if a decisive state is clipped; opportunity and
evidence collapse into one label; history resembles current state; unsupported
aggregate metrics appear; a radar map remains dominant; a source is hidden;
`LIVE` can be mistaken for execution authority; or any trading/simulation
control appears in the Command Center.

## Implementation Handoff

- Compose the default layout from existing pane/content identities. Do not
  create duplicate Candidate, chart, Decision, Activity, Positions, or Health
  surfaces.
- Add only GUI-local presentation wrappers required for paired state labels,
  UI age formatting, compact health, and traceable timeline rows.
- Treat the screenshot's numeric values and semantics as illustrative visuals,
  not fixtures or fallback data.
- When a requested field is missing, omit it or show the exact unavailable
  wording above. Do not cross into Contracts, Application, EngineBridge,
  Infrastructure, Python, runtime, service, provider, Paper/Shadow, broker,
  account, order, database, configuration, scheduler, or canary paths.
- Preserve Command Palette, pane persistence, link/pin, chart inspection, and
  read-only Positions regressions. Stop at the first backend/read-model need.

## Graphics Designer / UI Operator Designer Report

- **Branch:** `codex/ARGUS-GUI-COMMAND-CENTER-001`.
- **Scope:** operator-visible screenshot reconciliation and implementation-ready
  Command Center visual/layout specification only.
- **Files changed:**
  `docs/argus-office/architecture/ARGUS-GUI-COMMAND-CENTER-001-VISUAL-BASELINE-ADDENDUM.md`.
- **Tests or checks run:** original-detail inspection of the 1672x941 supplied
  screenshot; reviewed the Goal Charter, current GUI inventory, existing WPF
  1920x1080 and 1180x820 proof frames, pane/content IDs, candidate selection,
  command-palette, Positions, health, Activity, and chart references; Markdown
  and Git diff/status checks pending after write.
- **Evidence for changed behavior:** no behavior changed. This artifact defines
  exact baseline reconciliation, responsive wireframes, state treatments,
  unavailable-state rules, safety language, and visual proof frames.
- **Protected areas reviewed:** scoring, admission, readiness, risk, TradePlan
  semantics, replay/decision identity, history capture/aggregation, Contracts,
  Application, EngineBridge, Infrastructure, Python/runtime, services,
  scheduler, providers, Paper/Shadow, broker/account/order, database,
  configuration, secrets, installed runtime, and Producer-001C canary. No edits.
- **Push/merge status:** no commit, push, merge, install, or runtime action.
- **Risks:** What Changed and historical decision navigation remain visually
  `PARTIAL`; independent opportunity/evidence states, Target 2, setup type,
  row candle summaries, and complete decision deltas are not canonical current
  read-model fields. Source-labeled research positions must not be mistaken for
  live brokerage positions.
- **Manual QA:** Steven remains the final visual authority and should review the
  seven proof frames above after Builder implementation.
- **Open questions:** none for the bounded GUI-only implementation. Richer
  immutable decision history or canonical independent state fields require a
  separate post-freeze read-model decision.
- **Recommendation:** implement this four-zone composition as the visual
  baseline, render current limitations honestly, and stop at
  `GUI_IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE_AND_POST_CANARY_MERGE`.
