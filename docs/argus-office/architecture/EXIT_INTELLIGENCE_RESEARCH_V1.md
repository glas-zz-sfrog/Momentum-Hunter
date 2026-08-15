# Exit Intelligence Research v1

## Existing Lifecycle Inventory

Momentum Hunter already has several deliberately separate lifecycle domains:

- DATA-004 owns prospective same-session TradePlan identity, planned entry,
  invalidation, targets, entry expiry, and persisted forced-flat time. Regular
  sessions flatten by 15:55 Eastern and early-close sessions by 12:55 Eastern.
- Active Monitor refreshes candidate evidence and readiness; it is not a
  position-management or exit engine.
- Risk Governor and DATA-005B allocation are pre-entry admission controls.
- Execution Ledger and Auditor preserve Simulation Lab chronology and the
  FakeBroker-only boundary; they are not authoritative Alpaca fill truth.
- FakeBroker has deterministic in-memory simulation fills and positions.
- Shadow persists its own synthetic orders, marks, target/stop/forced-exit
  outcomes, and executable-versus-ideal evidence.
- Alpaca Paper owns provider order, cumulative fill, average fill, position,
  protection, emergency-flatten, and restart/recovery truth. PAPER-005 validates
  post-fill risk, exact protective quantity, and current-position flattening.

EXIT-RESEARCH does not replace any of these. Actual fills, quantity, exits, and
realized outcomes enter as immutable caller-supplied evidence references.

## Boundary

`momentum_hunter.exit_research` is an offline counterfactual evaluator. It can
consume completed bars, immutable structure evidence, and common Specialist
Opinions supplied by a caller. It has no provider, network, credential, account,
broker, order, persistence, service, scheduler, Engine Host, database, or UI
capability.

```text
actual broker-confirmed fill and frozen TradePlan
                    |
                    v
         immutable actual control
                    |
                    v
 seven independent counterfactual paths
                    |
                    v
 research-only opinions and comparison records
```

The actual control is historical truth. Counterfactual paths cannot write back
to that control or to any runtime lifecycle.

## Frozen V1 Policy

- Research identity: `exit-management-research-v1`.
- Specialist: `EXIT_INTELLIGENCE` / `exit-intelligence-research-v1`.
- Long, regular-session, one-minute completed-bar evidence only.
- Trailing stop: completed-bar high minus `2.0 * ATR`, tightens only, and becomes
  effective for the next bar.
- Time stop: 60 elapsed minutes.
- Break-even: arms after `+1R`, with zero offset, effective after the trigger bar.
- Partial exit: 50% at frozen Target 1; remainder uses the original stop and
  frozen Target 2, then forced flat.
- Structural stop: caller-supplied immutable level, never internally detected.
- Momentum and regime exits: caller-supplied common Specialist Opinions only.
- Ambiguous same-bar order is preserved as `AMBIGUOUS_SAME_BAR`.
- A stop gap records the crossed level and gap, but execution remains unknown.
- Forced-flat comes from the frozen DATA-004 control; no overnight extension.

These values prove software behavior. They are not claimed to be optimal.

## Evidence And Chronology

Each bar separates market event time, completion time, evidence `knownAt`, and
evaluation time. Forming bars, future bars, duplicate conflicting bars, missing
cadence, stale evidence, and cross-symbol evidence fail closed. An intrabar
level crossing is a market-path trigger, not a broker fill.

An otherwise valid actual `SHORT` trade or non-regular-session trade is outside
the frozen v1 evaluation domain and produces an explicit `OUT_OF_DOMAIN`
abstention with `UNSUPPORTED_SIDE` or `UNSUPPORTED_SESSION`. It does not create
an actual control or any counterfactual path.

A trailing stop derived from bar N cannot govern bar N. A break-even trigger and
violation in the same bar is ambiguous. A partial target and stop in the same
bar is ambiguous. Structure and specialist evidence cannot act before it was
known, and specialist target identity must match the exact opportunity/setup/
TradePlan chain.

## Result Domains And Metrics

Actual provider fills use `ACTUAL_EXECUTABLE_RESULT`. Candle-derived alternatives
use `COUNTERFACTUAL_MARKET_PATH_RESULT`. V1 does not invent a fill model, so a
modeled-execution result is unavailable. Gap-through-stop execution is explicitly
unknown.

The stable 1R denominator is actual average fill minus the valid original
protective stop. It never changes after the path is observed. Partial results are
quantity-weighted against actual filled quantity. MFE and MAE stop at the
hypothetical exit; later movement is a separate `PostExitOpportunityObservation`.

## Specialist Contract

Each alternative emits the common Specialist Opinion envelope with unavailable
confidence, `RESEARCH_ONLY` authority, and `EXECUTION_AUTHORITY_NONE`. Opinion
codes are research-shaped (`COUNTERFACTUAL_HOLD_SIGNAL`,
`COUNTERFACTUAL_EXIT_SIGNAL`, `COUNTERFACTUAL_PARTIAL_EXIT_SIGNAL`, or
`NO_OPINION`) and never resemble an order command.

## Sibling Compatibility

- RESEARCH-GOV may later preregister this exact policy and comparisons.
- STAT-DATA may attach path fingerprints to the same opportunity denominator.
- TECH may supply immutable structure or momentum opinions; its implementation
  is not imported.
- REGIME may supply immutable deterioration opinions; its implementation is not
  imported.
- EXEC remains independent from market-path exit intent.
- EVENT is not consumed in v1.

## Activation

The prospective sample identity is `exit-management-research-v1`, with
`activated = false` and `trades = 0`. Synthetic fixtures never enter that sample.
Runtime collection and any exit authority require separate integration,
activation, and prospective evidence gates.

Its static preregistration question compares all eight named methods against
the frozen actual Momentum baseline. Parameter optimization and historical
backfill are both disabled in the sample contract.
