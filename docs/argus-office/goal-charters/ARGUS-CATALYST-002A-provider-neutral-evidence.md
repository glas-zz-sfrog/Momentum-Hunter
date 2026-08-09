# ARGUS-CATALYST-002A Goal Charter - Provider-Neutral Catalyst Evidence

## Goal

Build the immutable provider-neutral evidence boundary for continuous catalyst
updates without choosing a provider, changing scoring authority, or connecting
the contract to production monitoring.

## Operator Outcome

Momentum Hunter can later ingest continuous catalyst observations while
preserving source/article identity, every meaningful or nonmaterial revision,
attribution, clocks, authority, stale/outage state, and deterministic material
deltas. Old evidence can never look fresh merely because it was redelivered or
because a provider recovered.

## Scope

- Add a pure Python catalyst evidence module on validated MONITOR head
  `d2b77c2`.
- Model source observations, immutable revisions, material-delta events,
  provider availability events, evaluated snapshots, and state deltas.
- Preserve DATA-001/001B relationship and score-authority classifications.
- Provide an atomic append-only JSON store with deterministic identities,
  replay validation, conflict rejection, and tamper detection.
- Preserve duplicate source records while deduplicating the same catalyst
  content within one canonical source so it cannot trigger authority twice.
- Add synthetic and temporary-directory-only tests.

## Non-Goals

- No provider, network, account, broker, Paper, Shadow, scheduler, service,
  Engine Host, WPF, or production-data call.
- No scoring, ranking, readiness, TradePlan, Risk Governor, selection, order,
  position, or lifecycle activation.
- No inferred sector, peer, customer/supplier, issuer, or macro relationship.
- No source-specific cadence, freshness value, or production policy decision.
- No canonical merge or installed-runtime change while scheduled jobs remain
  pinned.

## Acceptance Criteria

- [x] Stable article/candidate event identity and immutable revision chain.
- [x] Exact duplicates are idempotent; nonmaterial source revisions are
  preserved without triggering reevaluation.
- [x] Duplicate article identities with the same source/content are preserved
  but produce only one material catalyst discovery.
- [x] Content, attribution, authority, and source-metadata changes produce
  explicit material deltas.
- [x] `UNRESOLVED` attribution remains visible but score-authority blocked.
- [x] Stale, unknown-time, and source-outage evidence fail closed.
- [x] Redelivery or source recovery cannot refresh the original publication
  clock.
- [x] Store replay, chronology, conflict, atomicity, and tamper tests pass.
- [x] Static boundary tests prove no network, provider, broker, scoring,
  readiness, plan, Risk Governor, selector, or order capability.
- [x] Compile, focused, adjacent, full, protected-path, diff, and secret checks
  pass before commit.
- [ ] Feature branch is backed up without merge or runtime installation.

## Protected Areas

Scoring, authority enforcement in current reports, TradePlan, Risk Governor,
Shadow, broker/order execution, provider configuration, credentials, service,
scheduler, Engine Host, WPF, production evidence, and generated data remain
unchanged.

## Target Classification

`IMPLEMENTED_PENDING_INTEGRATION`
