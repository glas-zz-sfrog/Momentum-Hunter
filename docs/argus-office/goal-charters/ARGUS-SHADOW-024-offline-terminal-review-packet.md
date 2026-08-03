# ARGUS-SHADOW-024 Goal Charter - Offline Terminal Review Packet

## Goal

Build a deterministic, sanitized, offline packet from one terminal Shadow event so a
later optional reviewer can inspect exactly what the persisted evidence says without
placing Codex, a provider, a broker, or any new automation in the trading path.

## Operator Outcome

Steven can identify one completed FakeBroker trade, terminal unfilled/cancelled/
invalidated order, or legitimate terminal no-trade cycle and receive a hash-addressed
JSON and Markdown record of its evidence chain, missing facts, deterministic
derivations, and review questions.

## Scope

- Read six explicit JSON inputs: Shadow state, decision cycles, handoff, source report,
  sample activation, and selection policy.
- Bind sample, strategy, fill model, evidence schema, policy, arm, capture, cycle,
  command, opportunity, trade, plan, risk, order, position, ledger, and outcome
  identities where persisted.
- Validate terminal lifecycle, source-report hashes, handoff semantics, current sample
  activation, current selection policy, and cross-record identity consistency.
- Produce write-once canonical JSON plus readable Markdown with ten review sections.
- Classify section fields as `STORED_FACT`, `DETERMINISTIC_DERIVATION`, `MISSING`, or
  `REVIEW_QUESTION`.
- Fail closed on tampering, contradictions, nonterminal state, output conflict,
  source mutation, or secret-risk content.

## Non-Goals

- Do not invoke Codex, OpenAI, Schwab, another provider, a broker, the service, the
  Engine Host, WPF, a scheduler, or a background task.
- Do not capture, select, rank, plan, risk-check, fill, mark, close, recalculate, repair,
  normalize, or mutate any official event.
- Do not change scoring, readiness, alerts, TradePlan, Risk Governor, FakeBroker,
  lifecycle, P&L, database, provider, scheduler, UI, or execution semantics.
- Do not integrate into canonical `master` before Monday's evidence is preserved.

## Acceptance Criteria

- [x] Completed winner, loser, and flat events produce distinct terminal identities.
- [x] Unfilled, cancelled, and invalidated events expose no fabricated performance.
- [x] No-eligible, risk-blocked, and stale-quote cycles prove no order or position.
- [x] Counterfactuals are explicitly separated from official trades.
- [x] Missing optional evidence remains `MISSING`; missing required identity fails.
- [x] Sample, fill-model, policy, arm, opportunity, and report-hash mismatches fail.
- [x] Exact duplicate generation is byte-identical and logically idempotent.
- [x] Conflicting outputs are never overwritten; partial writes roll back.
- [x] Source files remain byte-identical before and after generation.
- [x] Secret keys, credential-like values, and caller-supplied known live values fail.
- [x] The module contains no network, provider, broker, service, Engine Host, scheduler,
  WPF, or Codex capability.
- [x] Compileall, focused tests, Shadow regressions, full discovery, and diff checks pass.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused packet tests: 17/17 pass.
- Packet plus adjacent Shadow regression: 168/168 pass.
- Full Python discovery on the original branch: 1,034/1,034 pass after providing the isolated worktree's
  ignored `.venv` junction required by an existing installer-path test.
- `git diff --check`: pass.
- Static network/broker/service/Codex capability scan: pass.
- Source nonmutation, write conflict, partial-write rollback, and post-write source-race
  cleanup tests: pass.
- Canonical checkout and installed runtime artifacts are rechecked before feature-branch
  commit/push and remain outside this worktree.

## Status

`COMPLETE_AND_BACKED_UP` after Monday's terminal evidence passed, the
current-baseline reconciliation passed 17 focused, 225 adjacent, and 1,051 full
Python tests, and `master` fast-forwarded through `cd43852`.

## Goal Steward Review

- [x] The packet has a concrete operator use and an explicit downstream-only boundary.
- [x] Facts, derivations, missing values, and questions cannot be confused.
- [x] Acceptance proves real terminal behaviors and negative paths, not labels alone.
- [x] Protected runtime and Monday's operational baseline remain outside scope.
