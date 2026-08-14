# ARGUS-RESEARCH-DATA-001 Research Data Inventory

- As of: `2026-08-14T15:12:22.0030338-05:00`
- Classification: `LOCAL_EVIDENCE_INVENTORIED_RESEARCH_SCALE_GAPS_PROVEN`
- Inventory fingerprint: `5D414FDC41BA78DBC07328653EA491847377D0C5690904F96E4067C6CB2BA735`
- Execution authority: `NONE`
- Provider selection: `NOT_PERFORMED`

## Dataset Inventory

| Dataset | Authority | Records | Symbols | Coverage | Identity / action lineage |
|---|---:|---:|---:|---|---|
| canonicalSchwabMinute | CANONICAL | 38286 | 7 | 2026-07-28T00:53:00+00:00 to 2026-08-14T13:35:00+00:00 | security=false, actions=false |
| canonicalSchwabDaily | CANONICAL | 1764 | 7 | 2025-08-06 to 2026-08-14 | security=false, actions=false |
| researchDaily263 | RESEARCH_ONLY | 79298 | 263 | 2025-04-01 to 2026-07-02 | security=false, actions=false |
| candidateOutcomeHistory | RESEARCH_ONLY | 1256 | 290 | 2026-06-02T14:27:27.491123-05:00 to 2026-08-14T08:35:02.665991-05:00 | security=false, actions=false |
| successorSetupProspective | PROSPECTIVE_RESEARCH | 0 | 0 | eligible from 2026-08-17 | security=false, actions=false |

## Research Capability Matrix

| Research use | Status | Evidence | Minimum requirement |
|---|---:|---|---|
| dailyTechnicalPatterns | PARTIAL | Research Daily covers 263 symbols, including 248 with at least 200 bars, while canonical Daily covers 7; adjustment-event and security lineage are absent. | At least 200 adjusted Daily bars per symbol plus event-level adjustment and security lineage. |
| intradayTechnicalPatternsAndAnalogs | INSUFFICIENT | Canonical minute history covers 7 symbols and 17 session dates. | At least 60 complete canonical sessions across a broad candidate universe. |
| premarketStructure | INSUFFICIENT | Only 17 session dates exist and current evidence does not prove complete true 04:00-07:00 ET coverage. | Repeated complete 04:00-09:29 ET histories for candidate and benchmark symbols. |
| failedBreakouts | INSUFFICIENT | Current candidate history is not a complete setup-identified prospective denominator. | Prospective immutable breakout triggers linked to complete post-trigger minute outcomes. |
| continuationPullbackReclaimStatistics | INSUFFICIENT | SETUP-002 is activated but currently has 0 Pass 1 observations. | Prospective SETUP-002 Pass 1/Pass 2 pairs with a frozen denominator. |
| regimeConditioning | INSUFFICIENT | Benchmark minute history is narrow and no broad point-in-time universe or regime outcome panel exists. | Candidate outcomes aligned to broad benchmark/regime evidence over multiple regimes. |
| eventReactionStudies | INSUFFICIENT | Current catalyst and ticker records do not provide a survivor-safe event/security panel. | Durable issuer/security identity plus attributed event time, type, and surprise context. |
| timeOfDayEffects | INSUFFICIENT | Only 7 symbols and 17 canonical minute dates are present. | Complete intraday sessions across enough symbols/days to separate clock effects from selection effects. |
| rankAndSetupConditionedOutcomes | PARTIAL | 1256 candidate rows exist, but complete rejected history is absent. | Full admitted/rejected denominator with immutable setup identity and terminal outcomes. |
| historicalAnalogModeling | INSUFFICIENT | Stable security identity, delisting coverage, point-in-time membership, and action lineage are absent. | Broad survivor-safe, corporate-action-safe feature/outcome panel with walk-forward splits. |

## Universe Integrity

- Classification: `INSUFFICIENT`
- Stable security identity: `False`
- Symbol-change history: `False`
- Delisted-security coverage: `False`
- Point-in-time membership: `False`
- Corporate-action event lineage: `False`
- Finding: All inspected histories are ticker-keyed and no point-in-time universe, symbol lineage, delisting history, or corporate-action event chain is present.

## Proven Gaps

### CANONICAL_INTRADAY_DEPTH_AND_BREADTH

- Required: Canonical one-minute OHLCV, session labels, gap/correction lineage, at least 60 complete sessions per studied symbol.
- Current evidence: Current store: 7 symbols / 17 session dates.
- Proposed authority: `CANONICAL_RESEARCH_EVIDENCE_ONLY`
- Denied authority: No execution, scoring, or selection authority.
- Cost: `NOT_EVALUATED_NO_PROVIDER_SELECTED`
- Exit condition: Existing Schwab backfill plus prospective collection reaches the required panel with verified completeness.

### EXTENDED_SESSION_TIMESTAMP_SEMANTICS

- Required: Provider-session identity and timestamp semantics that distinguish true premarket, regular, after-hours, and unavailable overnight intervals.
- Current evidence: The canonical minute store includes 6932 bars outside standard 04:00-20:00 ET equity sessions.
- Proposed authority: `RESEARCH_SESSION_CLASSIFICATION_ONLY`
- Denied authority: No overnight execution authority and no reinterpretation of preserved timestamps.
- Cost: `NOT_EVALUATED_NO_PROVIDER_SELECTED`
- Exit condition: Preserved provider evidence and contract tests deterministically classify every timestamp without inventing unavailable sessions.

### SECURITY_MASTER_AND_SYMBOL_CONTINUITY

- Required: Durable security identifier, ticker effective dates, rename/delist history, and point-in-time universe membership.
- Current evidence: All inspected histories are ticker-keyed and no point-in-time universe, symbol lineage, delisting history, or corporate-action event chain is present.
- Proposed authority: `RESEARCH_IDENTITY_ONLY`
- Denied authority: No broker/account identity and no automatic symbol substitution.
- Cost: `NOT_EVALUATED_NO_PROVIDER_SELECTED`
- Exit condition: Every studied row resolves to a durable identity with tested rename/delist continuity.

### CORPORATE_ACTION_PRICE_BASIS_LINEAGE

- Required: Raw bars, adjusted analysis bars, effective action timestamps, factors, and transformation lineage.
- Current evidence: Adjusted Daily values exist, but no per-event factors or raw-to-adjusted lineage exist.
- Proposed authority: `ANALYSIS_TRANSFORMATION_ONLY`
- Denied authority: Raw provider evidence must remain immutable; no strategy bonus or authority.
- Cost: `NOT_EVALUATED_NO_PROVIDER_SELECTED`
- Exit condition: Split fixtures and real preserved cases prove returns, levels, ATR, patterns, and volume remain basis-consistent.

### PROSPECTIVE_OPPORTUNITY_DENOMINATOR

- Required: Every admitted, rejected, provider-bound, regime-vetoed, and unavailable candidate with immutable setup/outcome identity.
- Current evidence: Legacy history contains qualified candidates but not a complete rejected point-in-time denominator.
- Proposed authority: `PROSPECTIVE_RESEARCH_ONLY`
- Denied authority: No retrospective trade creation and no rewriting prior samples.
- Cost: `NOT_EVALUATED_NO_PROVIDER_SELECTED`
- Exit condition: A prospective sample preserves every expected decision opportunity and terminal data failure.

### EVENT_ATTRIBUTION_HISTORY

- Required: Issuer/security identity, event type/time, relationship, expected-versus-actual result, and source lineage.
- Current evidence: Current catalyst records are insufficient for survivor-safe event reaction statistics.
- Proposed authority: `RESEARCH_ONLY`
- Denied authority: No catalyst score, readiness, or execution authority.
- Cost: `NOT_EVALUATED_NO_PROVIDER_SELECTED`
- Exit condition: Attributed event fixtures and prospective records support deterministic event-window studies.

## Provider-Minimal Decision

No new provider is selected or recommended by this task. Existing Schwab history, the current research Daily cache, and prospective evidence must be measured against the explicit exit conditions before procurement is considered.

This inventory makes no edge, profitability, scoring, readiness, selection, broker, Paper, Shadow, or live-execution claim.
