# Shadow Sample Constitution

Status: `IMPLEMENTED_PENDING_INTEGRATION_NOT_AUTHORIZING`

This document describes the implemented methodology for the first official prospective
Momentum Hunter Shadow sample. It does not authorize Trade 1. The selector may become
`SELECTOR_ARMED` only after every prerequisite is tested, integrated
into canonical `master`, remotely backed up, and represented by one immutable
constitution hash attached to every counted trade and decision-cycle record.

## Purpose

The official sample measures the complete Momentum Hunter decision pipeline under
prospective, execution-adjusted FakeBroker conditions. It does not prove profitability,
authorize live trading, or treat Risk Governor approval as evidence of expected value.

Operator-selected simulations are exploratory and never count toward the official sample.

## State Machine

| State | Meaning |
| --- | --- |
| `DEFINITION_LOCKED` | Sample version, execution policy, fill model, evidence schema, and constitution hash are frozen. |
| `ACTIVATED` | The immutable activation record exists, but automatic selection is not yet allowed. |
| `SELECTOR_ARMED` | Canonical code, fresh-data monitoring, policy, and decision-cycle persistence have passed every pre-Trade-1 gate. |
| `COLLECTING` | The armed selector is processing prospective decision cycles. Zero completed trades is valid. |
| `GATE_REACHED` | The engineering sample minimum and required evidence-quality/diversity checks pass. This is not live authorization. |
| `CLOSED` | Collection ended without rewriting prior evidence. |
| `INVALIDATED` | A material defect prevents strategy conclusions. Evidence is preserved and a corrected methodology requires a new sample version. |

Current state: `ACTIVATED`; `SELECTOR_NOT_ARMED`; `0` completed trades.

## Frozen Selection Rule

1. Selection is automatic. Operator choice cannot enter the official sample.
2. The selector evaluates only immutable canonical scheduled TradePlan reports.
3. "First" means the highest-ranked eligible candidate ordered by canonical rank
   ascending, composite score descending, and stable candidate ID or symbol ascending.
4. Candidate order is not inferred from filesystem order, mutable monitor reports, or
   dictionary insertion order.
5. The complete ordered candidate list is preserved with one rejection or selection
   reason for every row.
6. Fatal data-quality warnings and informational warnings are separate. Blocking
   reasons, known structural warnings, and unknown warning codes are fatal. Known
   quote/chart provider notices may be informational, but the current executable quote
   must still pass every market-validity check.
7. Risk Governor approval is an eligibility gate and never changes ranking.
8. Rank and Risk Governor approval do not constitute a trade recommendation or proof
   of expected value.
9. A report with no eligible candidate creates no trade and still creates a decision-cycle record.

## Freshness And Clock Policy

Every timestamp must be timezone-aware, non-future, and mutually consistent.

| Clock | Initial maximum age | Rule |
| --- | --- | --- |
| Current entry-eligibility quote | 30 seconds | Recheck at selection; record source, as-of time, bid, ask, last, spread, session, and trading state. |
| Source capture completion | 10 minutes | Older captures are skipped. |
| Generated TradePlan report | 5 minutes | Older reports are skipped. |
| Report generation to selection attempt | 60 seconds | Longer handoff latency is skipped even when the report is otherwise under five minutes old. |
| Daily OHLC | Prior completed session | Never substitute an incomplete current daily bar. |
| Catalyst/news | Separately classified | Catalyst age is recorded and evaluated under a versioned catalyst policy, not the quote limit. |

The fresh quote recheck never rewrites the frozen TradePlan. The candidate is
non-executable when the quote is missing, stale, future-dated, halted, outside the
eligible session, crossed/invalid, beyond the permitted spread, through the stop,
already at or beyond the primary target, or otherwise contradictory.

Report generation, monitor-cycle, retrieval, or persistence time never substitutes
for provider quote time. The executable quote must carry a separately persisted,
timezone-aware provider quote timestamp and provider source. Missing either field
makes the quote unavailable; a newly written wrapper around old bid/ask values does
not refresh their age.

The initial production quote transport reads Schwab Market Data v1 quotes through one
exact-host GET and has no account or order endpoint. Candidate symbols and the SPY/IWM
benchmarks are requested once per decision cycle. Executable quote time is the oldest
of the provider's `bidTime`, `askTime`, and `quoteTime`, so both sides of the market
must satisfy the 30-second rule. Expired OAuth may refresh only through the existing
read-only sole-account revalidation that requires exactly one `2573`
`INDIVIDUAL_CASH` binding; that guarded refresh is the only indirect account read.

The selector validates requested symbol, embedded symbol, source, as-of identity,
finite bid/ask values, session, trading state, and all relevant clocks. It records
capture-to-report, report-to-selection, capture-to-selection, and quote-age seconds
without mutating capture or provider evidence. Missing, delayed, stale, closed,
extended-hours, mismatched, non-finite, or unrequested evidence is unavailable.
The source module is part of the immutable Shadow runtime build hash. Live weekend
proof confirms the provider response is parsed and old closed-session evidence is
rejected; production arming still requires a regular-market operational proof inside
the 30-second boundary.

## Duplicate, Cooldown, And Portfolio Rules

- Maximum one new official Shadow trade per immutable source report or source capture.
- Maximum one pending order, partial fill, or open position globally.
- Maximum one official trade per symbol per NYSE trading day; same-day re-entry is prohibited.
- Maximum one official trade per deterministic opportunity identity derived from
  symbol, long direction, setup family, catalyst identity, session date, and frozen
  plan fingerprint.
- Regenerated or recovered reports for the same underlying opportunity do not create
  another trade.
- Portfolio concurrency applies to pending entries, partial fills, and open positions,
  not only fully open positions.
- Existing frozen FakeBroker buying power, fixed reference unit, and daily-loss ceiling
  remain in force. R multiple is the primary performance measure; dollars are secondary.
- One global position makes simultaneous sector and symbol concentration impossible in
  v1. Sector identity remains unavailable for retrospective concentration reporting and
  is labeled honestly.

## Entry, Exit, Session, And Fill Rules

- FakeBroker is the only automated execution boundary.
- New entries are regular-session only from 9:35 AM through 3:30 PM ET.
- Early-close entry ends at 12:30 PM ET. The reviewed NYSE early-close calendar covers
  2026-2028 and fails closed outside that range.
- Overnight holding and extended-hours execution are prohibited.
- Open positions are forced flat by 3:55 PM ET, or 12:55 PM ET on a reviewed early close.
- Unfilled entry orders are cancelled when the entry window closes.
- Entry uses a nontransmitting DAY limit order.
- An executable ask must be at or below the limit after configured slippage and after
  the prospective minimum fill delay.
- Touched-but-not-executable limits remain unfilled.
- Available size may produce a partial fill.
- Exit uses executable bid-side evidence with configured adverse slippage.
- A gap through the stop exits from the later executable observation, not the stop price.
- Halted, unavailable, stale, invalid, or ambiguous observations fail closed and remain
  visible in evidence.
- Every fill-model change creates a new version; prior samples are not recomputed.

## Decision-Cycle Denominator

Every expected armed in-window five-minute Engine Host cycle is persisted. Restart-gap
inference creates explicit `SYSTEM_DOWNTIME` records. Each attempt links to its
decision-cycle result and discloses:

- Expected scheduled reports.
- Completed reports.
- Failed or missing reports.
- Eligible cycles.
- Selection attempts.
- Stale-data skips.
- Data-quality blocks.
- Risk blocks.
- Duplicate/cooldown/concurrency blocks.
- Orders created.
- Orders unfilled, partially filled, rejected, cancelled, or invalidated.
- Completed trades.
- Machine and provider availability during expected decision windows.

Only reporting completed trades is prohibited.

## Diversity And Counterfactual Evidence

The sample records distinct trading sessions, regimes, catalysts, symbols, and
time-of-day buckets; sector concentration is explicitly unavailable until a frozen
sector identity exists. Thirty completed trades releases descriptive aggregate metrics
only. At least 10 distinct trading sessions are required before a strategy review may
draw broader conclusions.

For every eligible cycle, preserve nontransmitting observations for:

- The official selected candidate.
- Other eligible candidates.
- One deterministic random eligible candidate.
- SPY as the broad-market benchmark.
- IWM as the second market benchmark.
- A sector benchmark when reliable mapping exists.

Counterfactuals do not create FakeBroker portfolio trades or count toward the official
portfolio sample. Open/no-trade cycles are labeled mark-to-latest observations. When
the selected trade closes, all eligible-candidate and benchmark returns are finalized
to the selected trade's immutable exit timestamp.

## Data And Versioning

The constitution freezes:

- Sample version.
- Strategy/configuration fingerprint.
- Constitution version and hash.
- Report-ranking policy version.
- Selection and eligibility policy.
- Freshness matrix.
- Data-provider and schema identities.
- TradePlan and Risk Governor contract versions.
- Fill-model version.
- Evidence-schema version.
- Benchmark definitions.
- Session, concurrency, cooldown, and invalidation rules.

A material change to source provider, provider schema, ranking, eligibility,
freshness, fill assumptions, TradePlan semantics, Risk Governor semantics, benchmark
definitions, or session rules requires a new sample version.

## Trade 1 Gates

Trade 1 remains blocked until all of the following pass:

1. SHADOW-004 visual truth-label acceptance is recorded.
2. SHADOW-004/005 and the hardened selector are committed, fast-forwarded into
   canonical local `master`, and non-force backed up to `origin/master`.
3. The implemented constitution version/hash and runtime build hash are recorded in a
   write-once selector-arm record and enforced by runtime and audit code.
4. Canonical ranking and stable tie-break tests pass.
5. Fresh quote recheck and every freshness boundary test pass.
6. Cross-report opportunity deduplication, one-active-symbol, cooldown, and
   portfolio-concurrency tests pass.
7. Every expected in-window decision cycle, inferred downtime slot, and skip/block
   reason is durably recorded.
8. A canonical production-local regular-market cycle proves Schwab supplies a current
   executable bid/ask boundary with provider/schema/latency identity. Closed-session
   fail-closed proof does not satisfy this gate.
9. The production-local sample remains at zero trades until all gates pass.
10. Order transmission remains `UNAVAILABLE`.

Arming requires the exact internal phrase plus a complete set of distinct structured
`PASS` proof artifacts. Each artifact must bind its named gate to the exact sample
version, activation-file SHA-256, constitution hash, runtime build hash, and an
offset-aware verification time between activation and arming. It must reference at
least one relative, hash-verified evidence file inside its proof bundle. The arm
record persists the canonical proof paths and SHA-256 values. Runtime re-reads every
proof and referenced evidence file before treating the selector as armed; missing,
empty, oversized, malformed, duplicated, relocated, altered, or context-mismatched
material fails closed. A failed or partial arm creates neither policy nor arm state.
Changing selector source after arming changes the runtime build hash and fails closed.

The pre-arm market-data gate is exercised with
`python -B -m momentum_hunter.schwab_market_data proof --symbols <candidate> SPY IWM`.
The derived output may be persisted under ignored local reports. It qualifies only
when every requested symbol is realtime, regular-session, tradable, has valid
noncrossed bid/ask evidence, carries the exact provider identity, and all independent
provider clocks are offset-aware, nonfuture, and no older than 30 seconds. Synthetic,
closed-session, delayed, stale, partial, or failed output never satisfies Gate 8.

The supported operational dry run is `selector-arm-check --proof-bundle <directory>`.
It performs the complete service-layer verification and must not persist policy, arm,
decision-cycle, state, or trade data. The separate `selector-arm` command reads the
same fixed `<proof-name>.json` bundle and requires the exact internal confirmation
phrase before the write-once arm is attempted. Neither command has broker or order
authority.

## Fill-Model Calibration

The deterministic model remains an estimate. Early official tickets must be compared
manually with thinkorswim paperMoney. Record expected versus observed fill price,
timing, partial-fill state, rejection, and slippage error. Later supervised canary
fills may extend calibration. Any resulting assumption change creates a new fill-model
version and never rewrites the active or completed sample.

## Later Broker Gates

The first real-money canary tests broker plumbing with a boring, liquid,
preapproved instrument. It does not test Momentum Hunter strategy performance.
A later strategy-driven canary is a separate gate.

Before any transmitting code exists:

- Schwab must rotate the previously surfaced Client Secret, permit a replacement app,
  or explicitly provide acceptable vendor remediation.
- The account state machine must support pre-canary zero positions, canary-active only
  the exact ledger-matched position, and post-canary return to zero positions.
- Settled cash, submission ambiguity, retry identity, partial fills, cancel races,
  broker-truth reconciliation, restart recovery, shutdown, and independent revocation
  must be proven.

No state in this document authorizes unattended live execution.
