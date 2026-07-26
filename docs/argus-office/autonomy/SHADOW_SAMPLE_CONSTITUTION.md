# Shadow Sample Constitution

Status: `DRAFT_NOT_AUTHORIZING`

This document is the proposed frozen methodology for the first official prospective
Momentum Hunter Shadow sample. It does not authorize Trade 1. The selector may become
`SELECTOR_ARMED` only after every unresolved item is implemented, tested, integrated
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
3. "First" means the highest-ranked eligible candidate under a frozen canonical
   report-ranking version, explicit sort fields and directions, and stable tie-breakers.
4. Candidate order is not inferred from filesystem order, mutable monitor reports, or
   dictionary insertion order.
5. The complete ordered candidate list is preserved with one rejection or selection
   reason for every row.
6. Warning-free data quality and Risk Governor approval are independent eligibility
   gates. Both must pass.
7. Rank and Risk Governor approval do not constitute a trade recommendation or proof
   of expected value.
8. A report with no eligible candidate creates no trade and still creates a decision-cycle record.

Unresolved before freeze:

- The current report builder sorts by descending composite score and relies on stable
  source order for equal scores. A versioned stable tie-break must be added without
  changing score values.
- The current selector consumes persisted list order rather than validating a canonical
  rank sequence.

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

Current gap: the scheduled report does not carry a trustworthy per-candidate
market-data as-of timestamp, and the automatic selector has no fresh quote input.
Therefore the selector must remain unarmed.

## Duplicate, Cooldown, And Portfolio Rules

- Maximum one new official Shadow trade per immutable source report.
- Maximum one active Shadow order or position per symbol.
- Maximum one official trade per deterministic opportunity/setup identity.
- Regenerated or recovered reports for the same underlying opportunity do not create
  another trade.
- A deterministic symbol cooldown after terminal exit must be frozen before Trade 1.
- Portfolio concurrency applies to pending entries, partial fills, and open positions,
  not only fully open positions.
- The existing per-trade Risk Governor remains necessary but does not replace a global
  portfolio-risk budget.

Unresolved before freeze:

- Exact opportunity-identity fields.
- Exact symbol cooldown duration and market-session treatment.
- Portfolio risk budget beyond the current FakeBroker position-count and daily-loss limits.

## Entry, Exit, Session, And Fill Rules

- FakeBroker is the only automated execution boundary.
- Entry uses a nontransmitting DAY limit order during the regular session.
- An executable ask must be at or below the limit after configured slippage and after
  the prospective minimum fill delay.
- Touched-but-not-executable limits remain unfilled.
- Available size may produce a partial fill.
- Exit uses executable bid-side evidence with configured adverse slippage.
- A gap through the stop exits from the later executable observation, not the stop price.
- Halted, unavailable, stale, invalid, or ambiguous observations fail closed and remain
  visible in evidence.
- Overnight permission and the exact end-of-session cancellation/exit rule must be
  frozen before Trade 1.
- Every fill-model change creates a new version; prior samples are not recomputed.

## Decision-Cycle Denominator

The official report must disclose:

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

The sample records distinct trading sessions, regimes, sectors, catalysts, symbols,
and time-of-day buckets. Thirty completed trades is an engineering/evidence gate only.
A strategy-confidence review requires a larger prospective sample with meaningful
calendar and regime diversity.

For every eligible cycle, preserve nontransmitting observations for:

- The official selected candidate.
- Other eligible candidates.
- One deterministic random eligible candidate.
- A broad-market benchmark.
- A growth benchmark where relevant.
- A sector benchmark when reliable mapping exists.

Counterfactuals do not create FakeBroker portfolio trades or count toward the official
portfolio sample.

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
3. This constitution has no unresolved items, is versioned, hashed, and its hash is
   enforced by runtime and audit code.
4. Canonical ranking and stable tie-break tests pass.
5. Fresh quote recheck and every freshness boundary test pass.
6. Cross-report opportunity deduplication, one-active-symbol, cooldown, and
   portfolio-concurrency tests pass.
7. Every expected decision cycle and skip/block reason is durably recorded.
8. Provider identity, schema validation, system availability, and latency-chain
   evidence are present.
9. The production-local sample remains at zero trades until all gates pass.
10. Order transmission remains `UNAVAILABLE`.

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
