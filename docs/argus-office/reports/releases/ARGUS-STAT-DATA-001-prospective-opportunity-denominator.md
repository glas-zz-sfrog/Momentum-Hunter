# ARGUS-STAT-DATA-001 Release Report

## Classification

`IMPLEMENTED_PENDING_PARENT_INTEGRATION`

The feature branch is stacked directly on common Specialist Contract commit
`e65cb702dfd0c2515c8c37bae6fd377315c71f83`. Canonical `master` remains
`ea056155182351be70bb03d23841aca55c6118ae`, synchronized with
`origin/master` and outside this worktree.

## Contract

- Contract version: `1`
- Sample: `opportunity-denominator-research-v1`
- Policy: `opportunity-denominator-policy-v1`
- Policy fingerprint:
  `fa0f034b224bea1f053ce85cbfbc37b7961b257c46514070b422476b190fc5e8`
- Sample status: `INACTIVE_NOT_ACTIVATED`
- Current prospective sessions/opportunities: `0 / 0`
- Authority: `RESEARCH_ONLY`
- Execution authority: `EXECUTION_AUTHORITY_NONE`

`OpportunityCycleRecord` freezes source, session, observed/cutoff timestamps,
raw/parsed/classified counts, record references, and complete-denominator
status. `OpportunityRecord` separately freezes origin lineage, symbol and
security-identity status, candidate/setup/TradePlan identity where present,
rank, cutoff evidence, disposition, and actual/counterfactual classification.

Same-symbol same-session rows remain distinct when their source origin, setup,
cutoff, rank, or evidence fingerprint differs. A ticker remains
`UNRESOLVED` unless a separate durable security identity is actually supplied;
ticker alone is rejected as durable identity.

## Later Evidence

Base records never change. The ledger adds separate write-once records for:

- common-contract specialist opinions with exact opportunity/candidate/setup/
  TradePlan/symbol validation and derived `PRE_DECISION`, `AT_DECISION`, or
  `POST_DECISION_RESEARCH` timing;
- market paths with `TARGET_FIRST`, `STOP_FIRST`, `TIMEOUT`, `UNTRIGGERED`,
  `INVALIDATED`, `AMBIGUOUS_SAME_BAR`, or `DATA_FAILURE` and terminal-bounded
  MFE/MAE/timing;
- actual broker execution with `FULL_FILL`, `PARTIAL_FILL`, `UNFILLED`,
  `CANCELLED`, `REJECTED`, or `EXECUTION_DATA_FAILURE`, requiring provider
  submission and fill evidence; and
- data-quality outcomes including system/data failure and incomplete
  denominator evidence.

Counterfactual market paths never become actual decisions or broker fills.
`finalAuthorizedQuantity` is not accepted as broker fill evidence.

## Persistence

The store has no default path. A caller must provide a root, under which it can
later create:

```text
<root>/opportunity-denominator-research-v1/
  cycles/
  opportunities/
  specialist-attachments/
  outcomes/
```

Writes are canonical, atomic, and write-once. Opportunities complete first and
the terminal cycle completes last. Exact replay is idempotent; conflicting
identity, malformed/tampered records, duplicate JSON keys, policy/sample drift,
and authority escalation fail closed. Restart summaries count only validated
opportunities referenced by terminal cycles; temporary files cannot inflate
the denominator.

## Opening Adapter Proof

The preserved August 14 opening report was read from canonical evidence and
adapted in memory only:

- source SHA-256:
  `69aeb1b0a5917a9a5be590eea6c1372d0e55fa5cf2478ed70f9b6e254a488f04`
- cycle ID:
  `b0e135672458fe27f81602abff5e657a5e80c5ebc017fa563446c54ed6ee6df1`
- raw / parsed / represented: `20 / 20 / 2`
- represented symbols: `SNDK`, `NU`
- result: `RETROSPECTIVE_RESEARCH_EXAMPLE / DENOMINATOR_INCOMPLETE`
- persistence writes: `0`

This is intentional. The current TradePlan report is a bounded candidate
briefing, not proof of all 20 source rows, so it cannot seed a complete general
denominator.

## Independence

SETUP-002 remains the specialized successor-setup sample and is unchanged.
STAT-DATA reuses its outcome-blind/write-once principles but neither imports nor
duplicates its sample. REGIME-002 and EXEC-QUALITY-001 remain sibling
specialists; this branch imports only the common Specialist Contract and can
later attach either opinion independently without combining or voting.

No current runtime imports STAT-DATA. No scanner, score, rank, TradePlan, Risk
Governor, allocator, Paper, Shadow, provider, account, broker/order, service,
scheduler, Engine Host, WPF, production store, or August 17 job changed.

## Verification

- Goal Steward: `READY_FOR_BUILDER`
- Python compileall: pass
- Focused negative matrix: `32 / 32` pass
- Adjacent Specialist/SETUP-002/opening/TradePlan/Paper regressions:
  `215 / 215` pass
- Full Python discovery: `2,095 / 2,095` pass
- Real opening adapter: pass, read-only/in-memory
- Existing runtime import scan: no consumers
- Provider/network/broker/order capability scan: no capability imports/calls
- `git diff --check`: pass
- Canonical checkout: clean at synchronized `ea05615`
- Installed automation manifest and August 17 pins: unchanged from preflight

Ruff is not installed and was not claimed. Full compile and test gates passed.
The full-suite runner left ignored `_test-*` scratch directories in the
isolated worktree; automated cleanup was blocked by command policy. They are
not tracked, are not production data, and do not affect Git state.

## Remaining Gate

Integrate the common Specialist Contract parent first, then reconcile and
integrate this stacked branch. Prospective activation, a complete opening or
continuous producer, scheduling, UI, statistical interpretation, specialist
nomination authority, regime veto authority, and every production influence
remain future separately authorized tasks.
