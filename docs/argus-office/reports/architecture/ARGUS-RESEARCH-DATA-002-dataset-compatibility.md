# ARGUS-RESEARCH-DATA-002 Dataset Compatibility

- As of: `2026-08-14T21:21:07.800178+00:00`
- Classification: `IDENTITY_AND_PRICE_BASIS_FOUNDATION_DEFINED_GAPS_REMAIN`
- Fingerprint: `3C763CFF90D9CFEF1C5B75B55E2ABBB5D0E759883519317DE1ACBD199EFAD8BC`
- Point-in-time universe: `INSUFFICIENT`
- Survivorship status: `UNCONTROLLED`
- Provider selection: `NOT_PERFORMED`

## Dataset Matrix

| Dataset | Records | Symbols | Security ID | Price basis | Survivorship | Admission |
|---|---:|---:|---|---|---|---|
| canonicalSchwabMinute | 38286 | 7 | False | UNKNOWN | UNCONTROLLED | SECURITY_IDENTITY_UNRESOLVED |
| canonicalSchwabDaily | 1764 | 7 | False | UNKNOWN | UNCONTROLLED | SECURITY_IDENTITY_UNRESOLVED |
| researchDaily263 | 79298 | 263 | False | UNKNOWN | UNCONTROLLED | SECURITY_IDENTITY_UNRESOLVED |
| candidateOutcomeHistory | 1256 | 290 | False | UNKNOWN | UNCONTROLLED | SECURITY_IDENTITY_UNRESOLVED |
| successorSetupProspective | 0 | 0 | False | UNKNOWN | UNCONTROLLED | SECURITY_IDENTITY_UNRESOLVED |

## Unresolved Gaps

### DURABLE_SECURITY_IDENTITY

- Requirement: Stable issuer/security ID with point-in-time aliases and inactive states.
- Existing capability: No inspected dataset contains durable identity or alias history.
- Missing capability: Stable issuer/security ID with point-in-time aliases and inactive states.
- Research consequence: Historical records cannot prove economic-security continuity.
- Prospective collection can close: `False`
- Another provider might eventually be required: `True`

### CORPORATE_ACTION_EVENT_CHAIN

- Requirement: Verified split/symbol-change events with effective time, ratio, and source fingerprint.
- Existing capability: No inspected dataset contains event-level action lineage.
- Missing capability: Verified split/symbol-change events with effective time, ratio, and source fingerprint.
- Research consequence: Returns, ATR, gaps, levels, patterns, excursions, and analogs can be corrupted.
- Prospective collection can close: `True`
- Another provider might eventually be required: `True`

### PRICE_BASIS_VERIFICATION

- Requirement: Explicit raw/split-adjusted/total-return basis and transformation lineage.
- Existing capability: Schwab basis is unspecified and broad Daily adjustment method lacks event lineage.
- Missing capability: Explicit raw/split-adjusted/total-return basis and transformation lineage.
- Research consequence: Corporate-action-sensitive analysis must abstain.
- Prospective collection can close: `True`
- Another provider might eventually be required: `False`

### POINT_IN_TIME_UNIVERSE

- Requirement: Historical membership including renamed, inactive, acquired, and delisted securities.
- Existing capability: Current evidence is ticker-keyed and evidence-derived.
- Missing capability: Historical membership including renamed, inactive, acquired, and delisted securities.
- Research consequence: Historical statistics remain exposed to survivorship bias.
- Prospective collection can close: `False`
- Another provider might eventually be required: `True`

No provider is selected or procured by this task.

This compatibility report grants no scoring, selection, Paper, Shadow, broker, or execution authority.
