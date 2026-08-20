# Goal Charter: OVERNIGHT-DATA-FIDELITY-001

## Goal Statement

Measure the earliest useful market visibility available to Momentum Hunter from
20:00 ET through the regular session, using existing or free provider capacity
first, without changing production authority, cadence, strategy, or execution.

## User Pain / Operator Outcome

Momentum Hunter must be able to distinguish a move that began overnight from a
fresh premarket move. Steven needs measured provider coverage, latency, universe
capacity, and cost tradeoffs rather than treating 07:05 ET as a sacred start.

## In Scope

- Run an isolated, read-only sidecar with its own identity, logs, and durable
  evidence root.
- Measure Alpaca Basic overnight latest bars, quotes, trades, snapshots, delayed
  history, bounded REST/batch capacity, and a bounded websocket hot set.
- Measure Schwab quote and price-history behavior with a tiny basket and reuse
  preserved Streamer evidence where a fresh Streamer bootstrap would cross the
  no-account-call boundary.
- Observe the 04:00 ET and 07:00 ET transitions, premarket, and a regular-session
  control without changing production jobs.
- Preserve provider timestamps, local receipt timestamps, feed identity,
  latency, coverage, gaps, and explicit authority classifications.
- Produce a sanitized, hash-addressed evidence bundle and a free-versus-paid
  capability recommendation.

## Out Of Scope

- No trading, Paper, Shadow, account, position, preview, or order call.
- No broker capability, execution authority, strategy authority, candidate
  admission, scoring, ranking, TradePlan, Risk Governor, or allocation change.
- No production service, writer, evidence root, scheduler, manifest, cadence,
  credential, or runtime mutation.
- No provider purchase or authority promotion.
- No claim that thinkorswim display capability is identical to Trader API
  capability.

## Protected Areas

- Production continuous services and the existing automation service are
  read-only invariants for this task.
- Provider credentials may be loaded only through existing local encrypted
  repositories and may never enter evidence, logs, diagnostics, Git, or chat.
- Alpaca is restricted to `data.alpaca.markets` market-data GET routes and its
  documented market-data websocket host. Schwab is restricted to market-data
  quotes and price history unless a separate safe Streamer path is proven.
- A provider path stops immediately if it requires account, position, order,
  trading-state, or broader authorization access.

## Acceptance Criteria

- Every checkpoint is write-once, fingerprinted, source-identified, timestamped,
  and secret-scanned.
- The fixed basket includes SPY, QQQ, AAPL, NVDA, and MU; any mover additions are
  explicitly research-only and source-attributed.
- Alpaca `overnight` and `boats` results remain separate, including entitlement
  failures and delayed-history semantics.
- Schwab observations report exact earliest returned minutes and never infer
  absent overnight intervals.
- Capacity evidence reports measured basket size, request count, elapsed time,
  response coverage, and provider limits without using account or order routes.
- Provider roles are classified independently as discovery radar, canonical
  candidate, delayed reconstruction, indicative only, or unusable. No values are
  averaged or voted into authority.
- Production Git, services, manifests, scheduler, and evidence roots remain
  unchanged through closeout.
- Final evidence answers directive sections A through J and selects exactly one
  allowed final decision.

## Evidence Required

- Frozen Git/service/config identities and before/after hashes.
- Official provider documentation URLs and retrieval timestamps.
- Sanitized live checkpoint JSON/Markdown, response-shape summaries, latency and
  capacity measurements, and checkpoint hashes.
- Synthetic tests for route denial, sanitation, deterministic fingerprints,
  write-once behavior, phase classification, capacity math, and provider-role
  separation.
- Compileall, focused and adjacent tests, diff/whitespace checks, secret scan,
  capability scan, and canonical nonmutation proof.

## Evidence Depth / Hard Chew Requirements

- Exercise current live read-only market-data paths during each available market
  phase, while allowing unavailable later checkpoints to remain explicitly
  pending rather than fabricated.
- Compare provider timestamps to local receipt time and preserve sparse minutes,
  missing records, and entitlement failures.
- Re-run focused tests after self-review and any narrow repair.
- Do not merge or deploy this research sidecar into production.

## Smallest Safe Implementation Slice

One isolated feature branch from canonical `e1ea386`, one standalone sidecar,
one nonproduction durable evidence root, and no installed-service or scheduler
change.

## Open CEO Decisions

- None for research execution. Any paid tier, provider-authority promotion, or
  production integration remains a later explicit decision.

## Goal Steward Review

- [x] Goal statement is concrete.
- [x] Operator outcome is clear.
- [x] Scope and non-goals are explicit.
- [x] Protected areas are named.
- [x] Acceptance criteria prove the requested outcome.
- [x] Evidence requirements preserve provider and security truth.
