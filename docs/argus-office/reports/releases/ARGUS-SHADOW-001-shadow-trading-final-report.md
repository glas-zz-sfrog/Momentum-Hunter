# ARGUS-SHADOW-001 Shadow Trading Final Report

## 1. Executive Summary

Momentum Hunter now has a continuous, prospective, nontransmitting validation path
for one selected persisted candidate:

`frozen report/candidate -> canonical TradePlan -> canonical Risk Governor ->
quote-driven FakeBroker -> persisted order/position -> stop/target outcome ->
Execution Ledger -> Execution Auditor -> executable P&L/R/MFE/MAE`

The path uses no Schwab credential, endpoint, account, token, or network request. It
does not add Paper or Live capability. The first real prospective sample has not
started, so this implementation proves lifecycle mechanics, not profitability.

## 2. Git Base And Branch

- Canonical base: local and remote `master` at `69feedf`
- Task branch: `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit`
- Required pre-implementation audit commit: `54c58a8 Map Shadow Trading lifecycle wiring`
- Implementation commit: `5d11f02 Build prospective Shadow Trading validation`
- Audit and implementation milestones: pushed to the feature branch
- Local `master`: unchanged and not pushed by this task
- Merge: none

## 3. Current Roadmap Phase

The work belongs to Phase 11, Broker Research and Hardening Before Paper Execution.
ARGUS-SHADOW-001 is `IMPLEMENTED_PENDING_MERGE`. Schwab A017 is
`BLOCKED_VENDOR_CAPABILITY` because official support confirmed that Trader API is
live-account-only, cannot access paperMoney, and has no current sandbox.

The validation order is now credential-free design, secure setup skeleton, prospective
Shadow Trading, manual paperMoney reconciliation, synthetic Schwab emulation,
authenticated documentation review, separately approved read-only OAuth, exact
canary-account isolation, read-only account evidence, and then a hard stop before
transmission.

## 4. Shadow Trading Wiring Map

The pre-change map is:

`docs/argus-office/reports/architecture/ARGUS-SHADOW-001-shadow-trading-wiring-map.md`

It identified that the original Phase 10 simulation ended at an immediate in-memory
FakeBroker fill. It lacked frozen evidence, durable command receipts, quote-driven
progression, realistic execution friction, exits, outcomes, lifecycle persistence, and
trade metrics.

## 5. Connected And Missing Links

Connected:

- Latest persisted trade-planning report to one exact selected candidate.
- Exact source text/hash and candidate row frozen at the decision timestamp.
- Stable candidate, evidence, TradePlan, risk, command, trade, order, position, ledger,
  and outcome identities.
- Canonical `TradePlan`, `stable_trade_plan_id`, and `evaluate_trade_plan`.
- Risk pass before FakeBroker order creation.
- Future supplied observation to entry, partial fill, position, stop/target exit, outcome,
  ledger chronology, and audit.
- Atomic JSON persistence and command idempotency across restart.
- Engine Host commands for start, advance, and snapshot.
- Successful canonical collection cycle to persisted-observation advancement.

Still missing or intentionally deferred:

- WPF operator controls and Shadow review panes.
- An automatic policy that chooses which candidate to start; rank is not authorization.
- A production market quote provider or Schwab market-data request.
- Broker-native order semantics, queue position, exchange routing, and actual liquidity.
- End-of-day/session-close exit policy and multi-target/scale-out rules.
- Automated thinkorswim paperMoney entry or reconciliation.
- A completed prospective sample.
- Any authenticated Schwab transport.

## 6. FakeBroker Hardening

`ProspectiveFakeBroker` models:

- bid/ask execution;
- configurable basis-point slippage;
- limit orders that remain unfilled;
- minimum fill delay;
- available-size partial fills;
- cancellation of an unfilled remainder before a partial position exits;
- stale, missing, future-clock, crossed, halted, extended-session, and wide-spread blocks;
- executable gap-through-stop prices rather than ideal stop prices;
- explicit unknown state when one observation makes stop and target ordering ambiguous;
- buying-power, open-position-count, and daily-loss limits;
- out-of-order observation rejection;
- duplicate-observation and duplicate-command idempotency;
- atomic restart recovery and strict malformed/duplicate-ID failure.

Ideal plan P&L and estimated executable P&L are both retained. Estimated executable P&L
is the primary validation value.

## 7. Forward Shadow Trading Readiness

The lifecycle is ready for a bounded prospective trial after branch review and merge.
It is not ready to claim an edge:

- Production sample count: `0`
- Minimum meaningful completed sample: `30`
- WPF/operator start surface: not implemented
- Credentials required: none
- Broker connection required: none
- Automated candidate selection: intentionally absent

Every decision must be started before later observations are consumed. Retrospective
backfill, plan rewriting, score rewriting, and deletion of failed/unfilled evidence are
not valid uses.

## 8. Metrics And Persistence

Per-trade state records candidate score/rank, setup, catalyst, regime, decision time,
frozen plan/risk/evidence, entry proposal, quantity, spread, slippage, fills, stop,
target, rejection reasons, data quality, exit, duration, ideal P&L, executable P&L, R,
MFE, and MAE.

Aggregate output records candidates, valid plans, risk rejects, simulated entries,
unfilled orders, completed trades, win rate, average win/loss, expectancy, average R,
maximum drawdown, profit factor at a meaningful sample, results by setup/catalyst/
regime/time, and the ideal-versus-executable gap.

State is an atomic schema-versioned JSON document under the local generated-data tree.
Generated state and reports are not committed. A malformed version, duplicate/missing
identity, dangling receipt, or command reuse with changed evidence fails closed.

## 9. Manual paperMoney Ticket

The JSON and Markdown ticket is explicitly:

`PAPER SHADOW / NONTRANSMITTING`

It includes order identity/time, symbol, side, quantity, limit, duration, session,
maximum notional, plan/risk/evidence identity, and plan fingerprint. It also reserves
fields for the exact manually entered ticket, operator changes, paperMoney result/fill,
exit, outcome, and reconciliation notes.

Momentum Hunter does not automate the thinkorswim GUI.

## 10. Schwab Setup Skeleton

`momentum_hunter.schwab_setup` currently:

- prints the required application-credential-only warning;
- accepts no secret through command-line arguments;
- uses a no-echo reader for a future application secret;
- generates random OAuth state and validates it exactly;
- rejects non-loopback, non-HTTP(S), duplicate, missing, mismatched, and timed-out callbacks;
- provides Windows-current-user DPAPI encryption and atomic local storage;
- supports token-store deletion;
- redacts status values;
- keeps callback path, HTTPS, certificate, and fixed-port requirements unresolved.

The CLI is locked and network-free. It does not open a browser, start a listener, ask
for a credential, or contact Schwab.

Official public-document source map:

- [Schwab Developer Portal](https://developer.schwab.com/)
- [Trader API - Individual product](https://developer.schwab.com/products/trader-api--individual)
- [Authenticated OAuth guide location](https://developer.schwab.com/user-guides/get-started/authenticate-with-oauth)
- [Schwab public data-sharing security note](https://www.schwab.com/legal/public-security-tips-popup)

The portal exposes little detail without authenticated approval. Callback and endpoint
facts must come from the approved portal, not unofficial wrappers. Schwab Support's
direct response is the controlling evidence for the absence of paperMoney/sandbox
access.

## 11. Read-Only Adapter Contract

`SchwabReadOnlyAdapter` contains only:

- `list_authorized_accounts`
- `get_account`
- `get_balances`
- `get_positions`
- `list_orders`
- `get_order_status`

The logical endpoint policy allows only `GET` plus those named operations. There is no
`submit_order`, `replace_order`, `cancel_order`, `transfer_money`, or `withdraw`
method, endpoint, URL, HTTP client, or hidden transmit flag.

## 12. Account-Isolation Policy

The future adapter fails closed unless:

- exactly one authorized account is returned;
- its type is `INDIVIDUAL_CASH`;
- it is cash-only;
- Steven manually confirms its redacted last four digits;
- its opaque account hash is pinned;
- every response uses the same hash;
- returned account type/ending/cash state still match;
- every read revalidates the complete authorized account list.

Zero, multiple, changed-hash, changed-ending, wrong-type, margin, and cross-account
responses lock the connection. Account selection never uses array position, display
order, nickname, first-account logic, or current UI selection.

## 13. Contract Emulator

The offline emulator uses synthetic values only. It covers:

- one-use authorization code and exact state;
- token expiration and rotating one-use refresh;
- unauthorized, rate-limit, timeout, and malformed failures;
- zero, one, and multiple account lists;
- changed hash, wrong account type, and non-cash account;
- balances, positions, working/filled/canceled/unknown orders.

It imports no network client and never connects to Schwab. Synthetic assumptions are
labeled `SYNTHETIC`.

## 14. Tests And Hard Chew Evidence

Passed:

- `python -B -m compileall -q momentum_hunter tests`
- 60 focused Shadow/Schwab/Engine Host/existing simulation tests
- 68 adjacent TradePlan, autonomy, ladder, gateway, alert-observation, and target tests
- `dotnet restore MomentumHunter.Workstation.sln`
- 88/88 .NET tests in Release configuration
- full .NET Release build with 0 warnings and 0 errors
- `git diff --check`
- deterministic restart, duplicate-command, partial-fill, gap-stop, P&L/MFE/MAE,
  source-nonmutation, account-isolation, fake-token DPAPI, OAuth-negative, and
  no-transmit proofs

Bounded but not passed:

- Full Python `unittest discover` exceeded 10 minutes and was terminated.
- The two spawned discovery processes were identified by exact command line and stopped.
- This repository-wide harness risk remains; focused and adjacent suites are green.

## 15. Protected-Path Review

No production scoring, readiness, Risk Governor semantics, alert thresholds, replay
identity, historical capture selection, database schema/migration, package/dependency,
raw capture, generated market data, production configuration, Paper broker, Live
broker, or Schwab order behavior changed.

The existing `engine_host.py` changed only to expose the Shadow start/advance/snapshot
commands and advance already-active Shadow Trades after a successful canonical capture.
It advertises no broker, Paper, Live, credential, or transmit capability.

## 16. Known Limitations

- Zero real prospective outcomes exist.
- Current persisted observations may lack bid/ask and then correctly block fills.
- The model estimates spread/slippage but cannot reproduce exchange queue position,
  hidden liquidity, routing, halts, or broker-native partial-fill rules.
- Session-close, multi-target, scale-out, short-sale, options, and overnight policies
  are out of scope.
- There is no WPF Shadow operator/review surface.
- Manual paperMoney reconciliation fields are emitted but not imported automatically.
- Callback URL, HTTPS/certificate rule, production endpoint shapes, rate limits, token
  lifetime, and account response schemas remain subject to authenticated official docs.
- Schwab provides no Trader API paperMoney or current sandbox path.

## 17. Exact Input Needed From Steven After Schwab Approval

Do not send a Client ID, Client Secret, username, password, MFA, account number, account
hash, token, cookie, or screenshot containing those values.

After developer approval and only when a separate read-only task is authorized, provide:

- `Individual Developer status:`
- `Trader API Individual status:`
- `Existing app: Yes / No`
- `App status:`
- `App name:`

Codex must then inspect authenticated official callback and read-endpoint documentation
before requesting any app field. A real account connection remains separately gated.

## 18. Recommended Next Work

1. Review and fast-forward ARGUS-SHADOW-001 only if Steven accepts the code/test evidence.
2. Add a bounded WPF Shadow review surface: explicit start, current state, chronology,
   outcome metrics, and ticket export; keep candidate selection operator-driven.
3. Run the first prospective trial and retain every blocked/unfilled/ambiguous result.
4. Manually reconcile selected tickets in thinkorswim paperMoney.
5. Stop strategy comparisons below 30 completed Shadow Trades.
6. Keep Schwab disconnected until developer approval, authenticated-doc review, and a
   separate read-only Goal Charter.
7. Do not add transmission while the paper API path is unavailable.

## Explicit Answers

| Question | Answer |
| --- | --- |
| Is the complete Shadow Trading chain connected? | Yes for one selected persisted candidate through a supplied quote-driven simulated outcome, ledger, audit, and metrics. Automatic candidate selection and WPF controls are intentionally not connected. |
| Can Momentum Hunter prospectively track simulated P&L? | Yes. It persists executable and ideal P&L, R, MFE, MAE, duration, and grouped aggregate evidence. The current real sample is zero. |
| Are evidence and plans frozen at decision time? | Yes. Exact source text/hash, candidate JSON, timestamp, canonical plan JSON/fingerprint, and Risk result are persisted. |
| Does FakeBroker model realistic execution friction? | Yes at a conservative deterministic approximation: spread, slippage, delay, unfilled/partial fills, limits, stale/missing/halt/session blocks, stop gaps, and ambiguity. It is not an exchange simulator. |
| Can duplicate simulated orders occur? | Repeating the same command is idempotent across restart; reuse with different evidence fails. Strict persisted duplicate/missing-ID checks fail closed. |
| Is any Schwab credential currently stored? | No. DPAPI tests use synthetic fake token strings in temporary paths only. |
| Is any Schwab network request currently possible? | No. The new Schwab modules contain no endpoint URL or HTTP client. |
| Does any transmitting Schwab method exist? | No. No submit, replace, cancel, transfer, or withdrawal method exists. |
| What exact action is waiting on Schwab approval? | Authenticated official-document inspection and, only after separate approval, app/OAuth callback registration followed by read-only account-isolation proof. No Paper or Live order action is waiting or authorized. |
