# ARGUS-EVENT-SHOCK-001 - Event And Reaction Research Specialist

## Status

- Branch: `codex/ARGUS-EVENT-SHOCK-001-event-reaction-research`
- Base: specialist-contract head `e65cb70`, whose canonical ancestor is
  `ea05615`
- Classification: `IMPLEMENTED_PENDING_MERGE`
- Runtime/install/activation: none

## Implementation

- Added a deterministic event-shock packet that reuses existing catalyst,
  macro-event, rolling-regime, evidence-integrity, and common specialist
  contracts.
- Versioned every Roadmap event category and preserved direct-issuer,
  competitor, supplier/customer, sector, commodity, macro, and unresolved
  relationship semantics.
- Separated event relevance, prospective expected reaction, completed-bar
  market confirmation, and later immutable actual-reaction outcome.
- Added explicit research states for directional and non-directional market
  confirmation, unconfirmed evidence, no material reaction, and data failure.
- Preserved news/price disagreement, volume without progress, relative lag,
  and immediate breakout failure without turning any headline into a trade.
- Restricted every opinion to `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE` and
  added no producer, provider, persistence, service, scheduler, runtime, UI,
  Paper, Shadow, broker, or order capability.

## Verification

- Goal Steward: `READY_FOR_BUILDER` after event-category, protected-path, and
  closeout-status corrections.
- Focused EVENT-SHOCK tests: 25/25 pass.
- Common-opinion, catalyst, macro-event, and event-cycle regressions: 189/189
  pass.
- Full Python discovery: 2,088/2,088 pass in 243.633 seconds.
- Python compileall and `git diff --check`: pass.
- Future-bar, tamper, duplicate/write-once, incomplete-horizon, abstention,
  input-nonmutation, deterministic serialization, and forbidden-capability
  proofs pass.
- Final read-only nonmutation proof confirmed canonical and remote master at
  `ea05615`, the unchanged installed-manifest hash, and all four Aug. 17 jobs
  still exact-head pinned with their intended dependencies.

## Remaining Work

The module is deliberately dormant. It does not collect prospective records,
persist packets, combine specialists, or claim strategy edge. Preserve the
Aug. 17 operational evidence first, then reconcile the specialist foundation.
STAT-DATA-002 remains the separate producer-wiring and activation task needed
to supply a complete bounded opportunity population.
