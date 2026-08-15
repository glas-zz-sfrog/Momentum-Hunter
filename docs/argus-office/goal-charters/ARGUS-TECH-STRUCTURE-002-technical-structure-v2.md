# ARGUS-TECH-STRUCTURE-002 Goal Charter

## Goal Statement

Evolve the existing Technical Breakout Research Engine into one deterministic,
offline Technical Structure specialist that evaluates an already identified
Momentum opportunity without changing that opportunity or gaining strategy,
execution, provider, persistence, scheduler, service, or UI authority.

## Operator Outcome

Momentum Hunter can state which objective chart structures were knowable at a
specific time, why they support, contradict, exhaust, or do not inform the
existing thesis, and which exact completed-bar evidence produced that opinion.

## In Scope

- Reuse the existing technical bar, ATR, VWAP, and breakout primitives.
- Immutable pivots, levels, geometry measurements, structure instances, and
  common-contract Specialist Opinions.
- Compression/expansion, breakout/retest, failed breakout, VWAP reclaim/loss,
  higher-low/lower-high continuation, double top/bottom, sparse support and
  resistance, and head-and-shoulders/inverse structures.
- Explicit event time, `knownAt`, confirmation, invalidation, same-bar
  ambiguity, volatility normalization, price basis, session, and lineage.
- Synthetic, basis-safe, deterministic positive, negative, malformed, and
  look-ahead fixtures.
- Narrow compatibility contracts for RESEARCH-GOV-001, RESEARCH-DATA-002, and
  STAT-DATA-001 without making those sibling implementations runtime parents.

## Out Of Scope

- Candidate nomination, scoring, ranking, selection, TradePlan changes, Risk
  Governor changes, allocation, Paper, Shadow, broker/order behavior, provider
  calls, production persistence, service/scheduler/Engine Host wiring, WPF,
  activation, threshold optimization, profitability claims, or historical
  backfill.
- Pattern drawing, chart overlays, independent technical candidates, an
  Arbiter, short-selling authority, or combined specialist decisions.

## Price-Basis Boundary

- Same-session raw-provider geometry may be evaluated only from internally
  consistent authoritative evidence with session-bound identity.
- Cross-session geometry requires an explicitly admitted adjusted analysis
  basis and durable security identity.
- Unknown basis, unsafe corporate-action continuity, incomplete identity, or
  unobserved required session history produces explicit abstention.
- DATA-CORPACTION-001 remains required before serious historical technical or
  predictive claims. This task validates detector software, not edge.

## Protected Areas

Canonical `master`, the installed runtime and manifest, all Aug. 17 jobs,
production evidence, SETUP-002 policy/sample/jobs, scoring, readiness,
TradePlans, risk, allocation, Paper, Shadow, brokers, orders, credentials,
database schema, and UI remain unchanged.

## Acceptance Criteria

- [x] The implementation extends existing v1 primitives rather than creating
  a competing technical framework.
- [x] Every confirmed structure uses completed bars available at `asOf` and
  preserves economic event time separately from `knownAt`.
- [x] Structure and policy identities change when material evidence, pivots,
  geometry, basis, target, policy, or chronology changes.
- [x] Same-bar ordering is never invented.
- [x] Missing, malformed, stale, unsupported-session, and unsafe-basis evidence
  fails closed or abstains explicitly; unknown never becomes neutral.
- [x] Multiple and conflicting structures remain visible without majority
  voting or a universal technical score.
- [x] The common Specialist Contract is used with
  `RESEARCH_ONLY / EXECUTION_AUTHORITY_NONE`.
- [x] The observed opportunity and TradePlan remain byte-identical.
- [x] No provider, account, broker, order, persistence, service, scheduler,
  Engine Host, or UI capability is introduced.
- [x] Focused, adjacent, full-suite, scan, and canonical-nonmutation proof pass.

## Hard Chew Evidence

- Compileall and focused TECH-STRUCTURE tests.
- Technical Breakout v1, Specialist Contract, DATA-004, SETUP-001/002,
  RESEARCH-DATA, RESEARCH-GOV, STAT-DATA, and sibling-independence regressions.
- Deliberate future-bar leakage, duplicate/conflicting bar, missing interval,
  same-bar ambiguity, basis discontinuity, target mismatch, policy drift,
  tamper, mutation, authority, import, and capability attacks.
- Full Python discovery, `git diff --check`, secret/capability/import scans,
  protected-path review, canonical status/HEAD proof, manifest hash proof, and
  exact Aug. 17 pin proof.

## Git And Integration Boundary

- Branch: `codex/ARGUS-TECH-STRUCTURE-002-technical-structure-v2`.
- Parent: SPECIALIST-CONTRACT-001 at `e65cb702dfd0c2515c8c37bae6fd377315c71f83`.
- One focused implementation commit and ordinary feature-branch push are
  authorized after proof.
- Merge, installation, activation, scheduling, sibling merges, and Aug. 17
  repinning are prohibited.
- Expected closeout classification:
  `IMPLEMENTED_PENDING_PARENT_INTEGRATION`.

## Goal Steward Review

- [x] Goal and operator outcome are concrete.
- [x] Runtime authority and non-goals are explicit.
- [x] Price-basis and look-ahead risks are explicit.
- [x] Acceptance criteria require behavioral proof.
- [x] Integration and Aug. 17 operational boundaries are explicit.
