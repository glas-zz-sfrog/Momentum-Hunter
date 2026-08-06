# ARGUS-DATA-001C Schwab TradePlan Quote Authority

Status: `COMPLETE`

## Scope

DATA-001C replaces unsupported Yahoo Finance v7 quote enrichment with the
existing exact-host Schwab quote source for prospective TradePlan price
authority. It keeps Nasdaq and Yahoo chart evidence research-only and changes
no scoring formula, alert threshold, account/order capability, broker
transmission, database/schema, package, scheduler, service, Engine Host, candle
collector, or UI behavior.

## Implementation

- `momentum_hunter/trade_planning.py` batches candidate symbols once through
  the canonical Schwab quote source and existing regular-market proof.
- A quote must match source and symbol; be real-time, regular-session, tradable,
  and no older than 30 seconds; contain finite positive last/bid/ask and valid
  spread; and pass provider-clock and HTTPS-clock validation.
- Only Schwab last/bid/ask receive `EXECUTION_ELIGIBLE` provenance and
  `OAUTH_AUTHENTICATED` status.
- Nasdaq and Yahoo chart values remain reportable research evidence but cannot
  inherit authority when Schwab fails.
- The unsupported `/v7/finance/quote` runtime request is removed. Historical
  `QUOTE_HTTP_401` evidence is not rewritten.
- `momentum_hunter/active_monitor.py` revalidates refreshed evidence and
  preserves price, plan, and catalyst authority gates.
- `momentum_hunter/market_tape_health.py` no longer probes the duplicate
  unsupported Yahoo quote path.

## Verification

- Python compileall: pass.
- Focused suite: 44/44 pass.
- Adjacent suite: 159/159 pass.
- Full Python discovery: 1,179/1,179 pass in approximately 186 seconds.
- `git diff --check`: pass.
- Runtime URL scan: zero Yahoo Finance v7 quote requests.
- Secret scan: no credentials, tokens, keys, or known sensitive values added.
- Source nonmutation and one-batch behavior: pass through synthetic fixtures.
- No live provider, account, position, order, or transmission call was made.

## Changed Files

Runtime:

- `momentum_hunter/trade_planning.py`
- `momentum_hunter/active_monitor.py`
- `momentum_hunter/market_tape_health.py`

Tests:

- `tests/test_trade_planning_schwab_quotes.py`
- `tests/test_trade_planning.py`
- `tests/test_evidence_integrity.py`
- `tests/test_market_tape_health.py`
- `tests/test_active_monitor.py`

Governance and release evidence are recorded in the Roadmap, Task Log,
Changelog, Branch Ledger, Risk Register, Decisions, and this Goal Charter/report.

## Protected Review

The authorized protected change is narrow: research-only price evidence may no
longer satisfy TradePlan/readiness price authority, and Active Monitor cannot
bypass that rule. Score weights, rank formulas, catalyst semantics, alert
thresholds, plan formulas, Shadow constitution, FakeBroker lifecycle, account
binding, broker methods, and order transmission are unchanged.

## Remaining Limits

- DATA-001C closes price-source authority only. TradePlans remain hypothetical
  and execution-ineligible while DATA-002 through DATA-005 are open.
- The first prospective market-hours opening report remains the operational
  observation of actual Schwab quote availability and fail-closed behavior.
- R033 live-chart integration remains on its separate feature branch pending
  Steven's visual acceptance and safe reconciliation.
- R032 remains manually invoked; no unattended candle collector was activated.
