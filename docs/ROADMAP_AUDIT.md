# Momentum Hunter Roadmap Audit

Date: 2026-06-11

Scope: documentation, workflow, UI purpose, roadmap status, duplicate functionality, and deferred idea tracking. This audit adds no trading logic, scoring changes, optimizer work, broker integration, or SQLite migration.

## Executive Summary

Momentum Hunter has reached a useful research-foundation stage. The system now has two clear product modes:

- Daily operator workflow: scanner dashboard, Morning Review, Daily Checklist, Generate Watchlist Report, entry plans, capture health.
- Research workflow: Replay, Research Lab, Historical Clusters, Catalyst Explorer, Catalyst Age, Headline Dedup, Outcome Explorer, Opportunity Research, Readiness Gate.

The core architecture is consistent: raw captures are immutable, user decisions and plans are derived records, outcomes are post-capture labels, and research reports are rebuildable. The largest usability risk is now navigation overlap, not missing data architecture.

Operator Navigation Cleanup v1 addressed the highest-signal label and grouping issues from this audit. Operator Workflow Redesign v1 Phase 1 now separates market-data freshness from operator-review validity: aged evening/preopen snapshots can remain reviewable for next-session planning while historical, research, expired, and quarantined contexts stay blocked.

## Major UI View Review

| View | Purpose | Intended Workflow | Overlaps | Consolidation Opportunity |
| --- | --- | --- | --- | --- |
| Scanner Dashboard | Run current scanner, inspect candidates, review one selected ticker, see capture health, save decisions. | Run scanner, select candidate, review news/score, mark status, add plans/watchlist. | Morning Review, Daily Checklist, Capture Health panel. | Keep as the primary live dashboard, but move deeper daily actions toward Morning Review/Daily Checklist. |
| Candidate Detail Panel | Inspect selected candidate, news, score, notes, entry plan. | Click a row, read details, save notes/plan for current data. | Morning Review Decision Card and Entry Plan panel. | Treat as quick detail view; Morning Review should become the fuller daily workflow surface. |
| Capture Health Panel | Confirm scheduled captures, provider status, CSV/outcome update status. | Check whether data collection is healthy. | Daily Checklist and Open Capture Health. | Keep compact panel on dashboard; Daily Checklist should summarize health, not duplicate every field. |
| Morning Review Workspace | Focused current or next-session review and plan creation. | Select candidates, mark interested/rejected/watchlist, open Why Score/Timeline, write entry plan. | Scanner Dashboard candidate table, Entry Plan panel, Generate Watchlist Report. | Strong candidate to become the primary daily review screen. |
| Daily Workflow Checklist | Operational completion report for daily discipline. | Check captures, review counts, plan completeness, outcomes/readiness, then jump to missing work. | Capture Health, Morning Review, Generate Watchlist Report, Readiness Gate. | Keep as the daily control panel. Add future persistence only when workflow analytics are needed. |
| Generate Watchlist Report | Generate next-session watchlist report with entry-plan annotations. | After review, output the actionable watchlist. | Open Latest Watchlist, Daily Checklist quick action. | Future v2 could create a single Watchlist Center. |
| Open Latest Watchlist | Opens latest saved watchlist/report artifacts. | Review saved output after it is generated. | Generate Watchlist Report. | Future v2 could consolidate saved watchlists and generated reports. |
| Historical Snapshot View | Load past capture into main table with read-only banner. | Select date/session, inspect what was captured. | Replay Mode, Candidate Timeline. | Keep as broad snapshot replay; Timeline/Replay handles ticker-specific detail. |
| Candidate Timeline | Show all trusted active captures for a ticker. | Pick a ticker, inspect appearances across time, launch Replay. | Historical Snapshot, Historical Clusters recurrence view. | Keep as ticker drilldown; consider adding entry from Morning Review and Study rows consistently. |
| Replay Mode | Point-in-time read-only view of one candidate in one capture. | Open from Timeline or cluster appearance, inspect capture-time facts plus later annotations. | Historical Snapshot. | Keep as the trust boundary view. It should remain read-only and clearly labeled. |
| Research Lab Overview | High-level study coverage and basic outcome charts. | Understand data coverage and pending/completed outcomes. | Outcome Explorer, Readiness Gate. | Keep as overview; avoid expanding it further. |
| Historical Clusters | Theme/set-up grouping over historical candidates. | Find recurring setups and repeated tickers/sectors/scanners. | Catalyst Explorer, Opportunity Research. | Keep for setup recurrence, not catalyst precision. |
| Catalyst Explorer | Classify stored headlines into catalyst buckets with confidence/purity. | Research catalyst quality and classification reliability. | Catalyst Age, Headline Dedup, Historical Clusters. | Consider a future unified "Catalyst Intelligence" section with subtabs. |
| Catalyst Age | Measure headline timestamp age at capture time. | Audit freshness/timestamp quality without affecting scores. | Catalyst Explorer, Headline Dedup, news stack column. | Keep as timestamp audit; avoid presenting it as catalyst event age until Catalyst Dating exists. |
| Headline Dedup / Source Quality | Group repeated headlines and estimate source reliability. | Detect duplicated/syndicated news and poor timestamp sources. | Catalyst Explorer provider quality metrics. | Could merge provider timestamp quality with Catalyst Explorer v3 or Source Quality dashboard. |
| Outcome Explorer | Compare actual post-capture outcomes by filters. | Filter candidates and inspect completed vs pending outcomes. | Opportunity Research. | Keep as "what happened" view; Opportunity Research is "which conditions matter." |
| Opportunity Research | Rank conditions and combinations once outcomes mature. | Study condition performance without generating scores. | Outcome Explorer, Recommendations tab. | Keep locked/diagnostic until enough outcomes mature. |
| Readiness Gate | Decide whether there is enough completed outcome data for research conclusions. | Check whether Outcome Explorer, Opportunity Research, Opportunity Score, or Optimization are ready. | Daily Checklist, Outcome Explorer warnings. | Keep as the authority for blocking conclusions. |
| Locked Research Notes | Existing advisory score-weight note report after minimum outcomes. | Intended to show diagnostic notes only after enough outcomes. | Opportunity Research, Readiness Gate, Future optimizer. | Future v2 could hide/disable until readiness thresholds are met. |

## Documentation Audit

### README

Status: mostly accurate but needs cleanup.

Findings:

- The workflow section previously said `Click Add Selected`, but the current UI uses status flow such as `Mark Interested`, `Add Interested to Watchlist`, and `Watchlist Report`. This audit updates the README workflow wording.
- `Current Version` says "V1/V3 foundation", which is now too vague. The README should describe product areas instead of old version shorthand.
- `Latest Watchlist` and `Generate Watchlist` are now clearer, though a future Watchlist/report center may still be useful.
- The README now describes this area as `Locked Research Notes`; future work may hide or disable it until readiness thresholds are met.
- Several rendered docs contain mojibake for long dash characters in some `READ ONLY` labels. This is a documentation encoding issue, not a runtime logic issue.

Recommended fixes:

- Keep README workflow wording aligned with the current review-status workflow.
- Add a short "How to use Momentum Hunter each day" section: Daily Checklist, Morning Review, Generate Watchlist, then later Outcome Explorer.
- Keep `Locked Research Notes` diagnostic and readiness-gated so it cannot be mistaken for trading advice.

### CHANGELOG

Status: complete but hard to scan.

Findings:

- Recent milestones are captured, but several dates have repeated `### Added`, `### Safety`, and `### Tests` subsections under the same date.
- The changelog is becoming a development transcript rather than a release summary.

Recommended fixes:

- Keep it chronological, but group future entries by milestone name under each date.
- Avoid using changelog as roadmap; roadmap status should live in this audit/report or a dedicated roadmap file.

### FUTURE_IDEAS

Status: useful and current, with a few missing consolidation ideas.

Findings:

- Deferred research ideas are captured well.
- UI/navigation consolidation items were underrepresented before this audit.
- The existing `Catalyst date/age engine` idea is now partly complete as Catalyst Age measurement; true catalyst dating remains future work.

Updates made:

- Added Research Study tab grouping.
- Added Daily operator workflow consolidation.
- Added Generate Watchlist / Latest Watchlist naming cleanup.
- Added Locked Research Notes naming cleanup.
- Added documentation encoding cleanup.

### storage-map

Status: strong and mostly accurate.

Findings:

- Storage boundaries are well documented.
- Raw/derived separation is clear.
- It does not need a new section for Daily Workflow Checklist because the checklist is currently an in-memory derived view and creates no new store.
- The same mojibake issue appears in some labels.

Recommended fixes:

- Add a lightweight "Workflow reports" storage note only if workflow reports become persisted.
- Run a future docs encoding cleanup.

### Roadmap References

Status: fragmented.

Findings:

- README has a small Roadmap section focused on V2 fields and future integrations.
- FUTURE_IDEAS is a good backlog but not a status report.
- Readiness Gate is the actual authority for when Opportunity Score and optimization may begin.

Recommended fixes:

- Keep README roadmap short.
- Use this audit report or a future `docs/ROADMAP.md` as the status source.
- Tie future Opportunity Score work explicitly to Readiness Gate thresholds.

## Roadmap Status Report

| Milestone | Status | Notes |
| --- | --- | --- |
| Windows PySide6 desktop shell | Complete | Core UI exists. |
| Scanner dashboard | Complete | Base/Institutional presets and provider selection exist. |
| Finviz provider with error handling | Complete | DNS/provider failures are handled with retry/status behavior. |
| Scheduled captures | Complete | Market-calendar-aware morning/evening/preopen policy exists. |
| Capture Health panel | Complete | Dashboard panel and Daily Checklist summary exist. |
| Immutable raw captures | Complete | Manifest, SHA-256 audit, quarantine policy, rebuild tools exist. |
| Derived CSV rebuild | Complete | Rebuild commands and tests exist. |
| Review workflow statuses | Complete | Unreviewed/interested/rejected/watchlist stored separately. |
| Entry plans | Complete | Stored in `entry-plans.json`, included in watchlist reports. |
| Morning Review Workspace | Complete | Focused daily review workspace exists. |
| Daily Workflow Checklist | Complete | Workflow score and operational warnings exist. |
| Score breakdown / Why Score | Complete | Stored outside raw captures with version metadata. |
| Replay Mode / Candidate Timeline | Complete | Point-in-time read-only replay exists. |
| Historical Cluster Display | Complete | Historical and recurrence clustering exist. |
| Catalyst Cluster Explorer v1/v2 | Complete | Deterministic clusters, confidence, purity, provider quality exist. |
| Catalyst Age / Freshness measurement | Complete | Article timestamp age is measured; catalyst event dating is not. |
| Headline Dedup / Source Quality | Complete | In-memory event grouping and source reliability exist. |
| Outcome Explorer | Complete | Outcome filtering/comparison exists, pending handled safely. |
| Opportunity Research Framework | Complete | Research-only condition ranking exists. |
| Outcome Maturity / Readiness Gate | Complete | Gates lock Opportunity Score and optimization until maturity. |
| Generate Watchlist | Complete | Includes entry-plan fields in the generated report. |
| Operator Workflow Redesign v1 Phase 1 | Complete | Aged next-session captures warn but remain reviewable; expired/historical/research/quarantined contexts block workflow. |
| Documentation and storage map | In Progress | Broad coverage exists; cleanup and roadmap consolidation recommended. |
| Catalyst Dating Engine | Deferred | Catalyst Age measures article age, not underlying event date. |
| Opportunity Score | Deferred | Locked until sufficient completed five-day outcomes exist. |
| Weight optimization | Deferred | Locked until sufficient completed outcomes and walk-forward validation. |
| SQLite migration | Deferred | Should wait until data model stabilizes further. |
| Provider raw snapshots | Deferred | Future data-quality layer. |
| Broker integration | Future Idea | Should remain blocked until research evidence exists. |
| Automated trading | Future Idea | Not planned until evidence and controls justify it. |

## Feature Inventory

| Feature | Purpose | Status | Dependencies |
| --- | --- | --- | --- |
| Scanner presets | Reduce market to candidate list. | Complete | Provider layer, scoring profile. |
| Provider abstraction | Allow data providers to be swapped. | Complete | Provider implementations. |
| Finviz scan/news parsing | Initial market data source. | Complete | Network/provider availability. |
| Provider error handling | Fail cleanly and protect stale table state. | Complete | Provider layer, capture logs. |
| Market regime label | Context for scoring/research. | Complete | Manual/refresh regime workflow. |
| Market-calendar scheduling | Avoid weekend/holiday capture noise. | Complete | Scheduling policy module. |
| Headless capture job | Run scheduled captures without manual UI. | Complete | Task Scheduler, provider layer. |
| Capture Health | Show capture/provider/CSV/outcome status. | Complete | Capture files, failure records. |
| Immutable capture manifest | Prove raw captures did not drift. | Complete | SHA-256 manifest. |
| Quarantine/recovery | Remove untrusted captures from active study use. | Complete | Integrity audit and rebuild tools. |
| Review statuses | Track human decision state. | Complete | `review-decisions.json`. |
| Entry plans | Record trade plan discipline. | Complete | `entry-plans.json`, review identity. |
| Generate Watchlist | Produce next-session watchlist artifact. | Complete | Watchlist status, entry plans. |
| Morning Review | Focus daily candidate decisions. | Complete | Current candidates, review decisions, entry plans. |
| Daily Checklist | Track daily workflow completion. | Complete | Capture health, review statuses, entry plans, readiness report. |
| Score breakdowns | Explain every displayed score. | Complete | Scoring engine, score-breakdowns store. |
| Replay Mode | Inspect point-in-time candidate state. | Complete | Raw captures, score breakdowns, decisions, outcomes. |
| Historical Clusters | Find recurring setups/themes. | Complete | Active captures and derived stores. |
| Catalyst Explorer | Classify headline themes deterministically. | Complete | Stored headlines, catalyst rules. |
| Catalyst Age | Measure article age at capture time. | Complete | Stored headline timestamps. |
| Headline Dedup | Estimate duplicate/syndicated headline impact. | Complete | Stored headlines, catalyst classification. |
| Source Reliability | Measure timestamp/source quality. | Complete | Headline timestamps and sources. |
| Outcome Explorer | Analyze post-capture results. | Complete | `analysis-outcomes.csv`, active capture identity. |
| Opportunity Research | Research condition performance. | Complete | Mature outcomes, catalyst/source context. |
| Readiness Gate | Prevent premature conclusions. | Complete | Outcome maturity metrics. |
| Locked Research Notes | Advisory score-weight note output after minimum outcomes. | In Progress | Outcomes; future v2 should hide/disable until readiness thresholds. |
| Catalyst Dating | Determine underlying event date, not article age. | Deferred | Better event clustering and timestamp confidence. |
| Opportunity Score | Combine momentum/catalyst/freshness after evidence. | Deferred | Completed outcomes, validation, readiness gates. |
| SQLite | Centralize data once model stabilizes. | Deferred | Stable schema and migration plan. |

## Duplicate Functionality Findings

1. Dashboard Candidate Detail and Morning Review overlap on selected candidate details, score context, review status, and entry plan fields.
   - Recommendation: keep dashboard detail as quick inspection; make Morning Review the primary daily decision workspace.

2. Capture Health panel, Daily Checklist, and Open Capture Health overlap.
   - Recommendation: dashboard panel stays compact, checklist summarizes, Open Capture Health provides text detail.

3. Generate Watchlist and Latest Watchlist overlap.
   - Recommendation: future v2 could consolidate them into one Watchlist/report center.

4. Outcome Explorer and Opportunity Research overlap in grouping outcome data.
   - Recommendation: Outcome Explorer answers "what happened"; Opportunity Research answers "which conditions might matter."

5. Catalyst Explorer, Catalyst Age, and Headline Dedup all describe news quality.
   - Recommendation: eventually consolidate under a Catalyst Intelligence section with subtabs.

6. Locked Research Notes overlaps with deferred optimizer/Opportunity Score posture.
   - Recommendation: future v2 could hide or disable it behind Readiness Gate until sufficient outcomes exist.

## Orphaned, Unfinished, or Confusing Areas

- `Research List` has been renamed `Latest Watchlist`; future work may still consolidate watchlist artifacts.
- Older workflow terminology such as `Add Selected` should stay out of user-facing docs.
- `Locked Research Notes` is clearer than `Recommendations`, but future work should still enforce readiness gating visually.
- `Catalyst Age` could be confused with catalyst event age. It currently measures article timestamp age at capture time.
- `LIVE` mode remains a research mode only. That is documented, but the label may still invite broker assumptions.
- Some documentation has encoding artifacts in long-dash labels.

## Documentation Findings

- README is broad and useful, but it is now doing install guide, operator guide, storage overview, and roadmap all at once.
- CHANGELOG is complete but verbose.
- FUTURE_IDEAS is healthy but needed UI/navigation consolidation ideas.
- storage-map is strong and should remain the source for raw/derived safety.
- A dedicated roadmap/status document is now justified.

## Future-Idea Findings

Verified already present:

- Opportunity Score only after sufficient completed outcomes.
- Walk-forward validation.
- Regime-specific Opportunity Score research.
- Minimum sample-size thresholds.
- Source-level timestamp reliability.
- Semantic event clustering.
- Near-duplicate headline detection.
- Multi-source catalyst consolidation.
- Workflow Discipline Analytics.
- Trade Plan Outcome Analysis.
- Entry Plan UI v2.
- SQLite migration after clusters stabilize.
- Broker integration only after research validation.

Added by this audit:

- Research Study tab grouping.
- Daily operator workflow consolidation.
- Generate Watchlist / Latest Watchlist naming cleanup.
- Locked Research Notes naming cleanup.
- Documentation encoding cleanup.

## Recommended Next Roadmap Milestone

**Recommended Next Roadmap Milestone: Research Study Navigation v2 or Watchlist/Report Center v1**

Goal: continue reducing navigation crowding after the high-signal label cleanup.

Suggested scope:

- Consider a sidebar or nested navigation for Research Study sections.
- Consider a single Watchlist/report center for generated watchlists and latest artifacts.
- Hide or disable Locked Research Notes until Readiness Gate thresholds are met.
- Reduce toolbar crowding further if more top-level actions are added.
- Fix documentation mojibake in README/storage-map labels.

Do not include Opportunity Score, optimizer work, broker integration, scoring changes, or SQLite migration in that milestone.
