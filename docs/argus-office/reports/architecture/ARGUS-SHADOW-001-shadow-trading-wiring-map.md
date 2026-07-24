# ARGUS-SHADOW-001 Shadow Trading Wiring Map

## Scope And Evidence

This audit maps the prospective, FakeBroker-only trading path on canonical `master`
at `69feedf`. It does not change scoring, readiness, alert thresholds, TradePlan
semantics, Risk Governor semantics, broker behavior, schemas, raw captures, or user
state.

Inspected implementation:

- `momentum_hunter/active_monitor.py`
- `momentum_hunter/trade_planning.py`
- `momentum_hunter/autonomy/view_models.py`
- `momentum_hunter/autonomy/risk_governor.py`
- `momentum_hunter/autonomy/broker.py`
- `momentum_hunter/autonomy/simulation.py`
- `momentum_hunter/autonomy/ledger.py`
- `momentum_hunter/autonomy/auditor.py`
- `momentum_hunter/workstation_simulation.py`
- `momentum_hunter/engine_host.py`
- `momentum_hunter/opportunity_alerts.py`
- `momentum_hunter/alert_outcome_updater.py`
- focused tests for these paths

## Executive Finding

The existing implementation proves a bounded plan-to-FakeBroker simulation chain:

`persisted TradePlan report -> Top5CandidatePlan -> Risk Governor -> FakeBroker
preview -> FakeBroker submit -> in-memory ledger -> simulation audit`

It is not yet a complete prospective Shadow Trading chain. The current FakeBroker
normally fills immediately at the requested limit price, creates an in-memory long
position, and stops. It does not freeze the source evidence as a new immutable
decision artifact, consume future quotes, model realistic entry eligibility, process
stops or targets, close positions, calculate trade P&L/MFE/MAE, persist its state, or
recover safely after restart.

## Link Classification

| Link | Classification | Current owner | Current code path | Input contract | Output contract |
| --- | --- | --- | --- | --- | --- |
| Live/current candidate | Partially implemented | Active Monitor | `active_monitor.run_monitor_cycle` | Latest trade report, targets, optional supplied/fetched `MarketTape` | Derived monitor, target, alert, and optionally refreshed trade reports |
| Candidate selection | Implemented but operator-driven | WPF/Python simulation workspace | `SimulationWorkspaceService.run_simulation(symbol)` | Symbol selected by the operator | One `Top5CandidatePlan` loaded from the latest persisted report |
| Stable candidate ID | Missing | None | No canonical field on `Top5CandidatePlan` | N/A | N/A |
| Frozen evidence snapshot | Missing | None | Source report is reread when commands execute | Mutable path to a persisted trade report | No decision-time evidence artifact or fingerprint |
| TradePlan generation | Implemented and connected | Trade Planning | `TradePlan`, report serialization, `candidate_plan_from_report_row` | Capture/candidate data plus optional bars/tape | Canonical `TradePlan` reconstructed from the report |
| Stable TradePlan ID | Partially implemented | Autonomy view model | `stable_trade_plan_id` | Symbol plus entry, stop, target 1, readiness | Deterministic readable ID; does not include evidence identity or full plan |
| Risk Governor decision | Implemented and connected | Risk Governor | `evaluate_trade_plan` | `TradePlan`, ticker, TradePlan ID, simulation mode | `RiskGovernorResult` with UUID result ID and timestamp |
| Frozen risk decision | Partially implemented | Risk Governor | Result is immutable in memory | Current plan | Not persisted independently; recreated whenever the report is loaded |
| Stable simulation command ID | Implemented at host boundary | Engine Host | `EngineHostRuntime.execute` | Caller-supplied command ID plus normalized arguments | Cached idempotent command result for the lifetime of one host |
| Restart-safe command ID | Missing | None | Receipt cache is in memory | N/A | Duplicate protection is lost on restart |
| FakeBroker order intent | Implemented and connected | Simulation Engine | `build_simulation_order_request` | Entry and estimated shares from selected plan | Buy limit `BrokerOrderRequest` |
| Realistic entry eligibility | Mocked | FakeBroker | `FakeBrokerAdapter.submit_order` | Order request and constructor flags | Immediate fill, partial fill, rejection, or accepted state |
| Bid/ask and spread | Missing | None | No quote contract reaches FakeBroker | N/A | N/A |
| Configurable slippage | Missing | None | No execution-friction policy | N/A | N/A |
| Limit order may not fill | Partially implemented | FakeBroker | `auto_fill=False` returns `accepted` | Constructor flag | Accepted order that never advances |
| Delayed/partial fill progression | Partially implemented | FakeBroker | Constructor symbol sets | Static one-time partial state | No subsequent quote-driven transition |
| Stale/missing quote block | Missing | None | Risk warnings can request review, but broker has no quote | N/A | N/A |
| Halt/session eligibility | Missing | None | No market-state contract | N/A | N/A |
| Buying-power gate | Missing | Fake account exposes buying power only | `get_account` | Configured buying power | Informational value; submit does not enforce it |
| Position concurrency/daily loss gate | Missing | None | No portfolio policy | N/A | N/A |
| Duplicate-order prevention | Partially implemented | Engine Host | Command ID cache | Host command ID | Same command is idempotent only until restart |
| Simulated order state | Implemented in memory | FakeBroker | `_orders` dictionary | Submitted request | `BrokerOrder` status |
| Simulated fill | Mocked | FakeBroker | `submit_order` | Plan limit price | Usually fills immediately at exactly the limit |
| Simulated position | Partially implemented | FakeBroker | `_upsert_position` | Filled order | In-memory long position; average-price math is incomplete for multiple fills |
| Stop/target/exit handling | Missing | None | No lifecycle consumer | N/A | N/A |
| Gaps through stops | Missing | None | No exit/fill model | N/A | N/A |
| Execution Ledger | Implemented but volatile | Execution Ledger | `ExecutionLedger.record` | Risk, preview, submit/block facts | Structured immutable in-memory events |
| Ledger persistence | Missing | None | `to_dicts` exists but no store owns it | N/A | N/A |
| Execution Auditor | Implemented for initial chain | Execution Auditor | `audit_simulation_chain` | In-memory ledger, ticker, TradePlan ID | PASS/FAIL for risk-before-preview-before-submit/block |
| Full lifecycle audit | Missing | None | No fill/position/exit/outcome chronology rules | N/A | N/A |
| Outcome classification | Implemented elsewhere but disconnected | Alert Outcome Updater | `calculate_alert_outcome_from_minute_bars` | Opportunity alert plus minute bars | Alert classification and returns, not a Shadow Trade outcome |
| Trade P&L, MFE, MAE | Missing | None | Alert MFE/MAE cannot represent actual simulated fills/exits | N/A | N/A |
| Aggregate Shadow metrics | Missing | None | Existing alert analytics summarize alert outcomes only | N/A | N/A |
| Manual paperMoney ticket | Missing | None | No nontransmitting order-ticket artifact | N/A | N/A |

## Persistence, Failure, Restart, And Duplicate Risks

| Area | Current behavior | Operator consequence | Required narrow repair |
| --- | --- | --- | --- |
| Source evidence | A report path is reread; no byte fingerprint or frozen copy is attached to the decision | A later report edit can silently change what is simulated | Store an immutable normalized evidence snapshot with source hash and decision timestamp |
| Risk evidence | Risk result is recreated on report load and receives a new UUID | The same plan can have different untracked risk IDs | Persist the risk result inside the frozen Shadow Trade |
| Broker state | Orders and positions live only in dictionaries | Restart loses open orders and positions | Atomic JSON state store with schema version and strict load validation |
| Ledger | Events live only in memory | Restart loses chronology and audit evidence | Append/persist events atomically with duplicate ID validation |
| Command receipts | Host caches receipts only in memory | Restart can repeat an entry | Persist simulation command IDs and their terminal result |
| Entry fill | Immediate plan-price fill is the default | Strategy evidence is optimistically biased | Require a fresh quote/bar and apply explicit spread/slippage/limit eligibility |
| Accepted order | An unfilled order never advances | No prospective lifecycle exists | Feed future quote/bar observations into an order advancement method |
| Position | Long position is opened but never closed | No realized result can be measured | Add deterministic stop/target/session-close handling |
| Exit gap | Not modeled | Stop losses are understated | Fill at the first executable price after a gap, not retroactively at the stop |
| Outcome | Alert outcomes are separate from execution | Results measure signal movement, not executable trading | Create a Shadow Trade outcome from actual simulated fills and exits |

## Existing Reusable Contracts

- `TradePlan` remains the canonical plan primitive and must not be rescored or
  rewritten.
- `RiskGovernorResult` remains the pre-simulation risk evidence.
- `ExecutionLedgerEvent` remains the event vocabulary; Shadow Trading can add
  lifecycle payloads without changing current gate semantics.
- `MinutePriceBar` and the existing alert-outcome excursion helpers demonstrate
  deterministic time-window handling, but Shadow Trading needs fill-relative metrics.
- `EngineHostRuntime` already supplies one loop, non-overlapping collection, and
  command idempotency. Durable Shadow state should be owned below the host so it can
  survive a host restart.

## Failure Policy For The Next Slice

The next implementation must fail closed when:

- no persisted candidate/TradePlan exists;
- decision-time source evidence cannot be parsed or fingerprinted;
- the Risk Governor blocks simulation;
- the quote is absent, stale, halted, or outside the configured session;
- bid/ask are invalid or crossed;
- buying power, position count, or daily loss limits would be exceeded;
- a command, evidence, plan, risk, order, ledger, or outcome ID is missing;
- a persisted state document is malformed or has an unsupported schema;
- an existing command ID is reused with different input;
- an account or credential is supplied to the Shadow Trading path.

Ambiguous entry, stop, target, or ordering conditions must remain unfilled or enter an
explicit unknown state. They must never be interpreted optimistically.

## Recommended Next Task

Implement a bounded `momentum_hunter.shadow_trading` domain service and atomic JSON
store that:

1. freezes one decision from a persisted candidate row;
2. assigns stable cross-stage IDs and a plan fingerprint;
3. reuses the canonical TradePlan and Risk Governor;
4. accepts explicit quote/bar observations without fetching;
5. models conservative FakeBroker entry and exit behavior;
6. persists commands, orders, positions, ledger events, and outcomes;
7. calculates executable P&L, R, MFE, and MAE;
8. emits a nontransmitting paperMoney ticket; and
9. reports sample-gated aggregate metrics.

The service may later be called after a successful Active Monitor cycle, but the first
slice should use explicit supplied market observations. Automatic candidate entry is a
separate policy decision and must not be inferred from candidate rank or score.

No Schwab credential, network request, account hash, or transmitting method belongs in
this task.
