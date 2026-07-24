# ARGUS-R027 Goal Charter - Integrate R026 With Shadow Baseline

## Goal

Reconcile the validated R013-R025 workstation stack with the canonical Shadow-003
baseline while preserving both histories, all safety boundaries, and truthful
operator evidence.

## Operator Outcome

Steven can review one combined WPF workstation that includes chart inspection,
command palette, candidate evidence, health, replay, monitoring, activity,
alert/outcome evidence, technical research, saved watchlist, Daily Workflow,
Candidate Story, Research Maturity, and the complete read-only Shadow Review.

## Scope

- Start from local `master` at `164e32e`.
- Merge R026 at `838ed22` as a real second parent.
- Preserve every Shadow host command, review workflow, sample lock, and
  post-collection observation path.
- Preserve every R013-R025 read-only host command, pane, and test.
- Resolve shared contracts, dependency injection, layout schema, pane linking,
  Trade Plan context, and governance records.
- Produce fresh combined compile, test, safety, and multi-size UI proof.

## Non-Goals

- Do not start the official Shadow sample.
- Do not change scoring, readiness, replay identity, capture selection, alert
  thresholds, TradePlan/Risk Governor semantics, Shadow eligibility, FakeBroker
  fill/exit behavior, database schema, broker/order behavior, credentials, Paper,
  Live, provider access, or production configuration.
- Do not add icon artwork, broker integration, OAuth, credentials, or transmission.
- Do not merge to `master` or push without separate Steven approval.

## Acceptance Criteria

- [x] All merge conflicts are resolved additively and no markers remain.
- [x] Python compileall passes.
- [x] Full combined Python discovery passes unattended.
- [x] Full .NET solution passes.
- [x] Release build passes with zero warnings and errors.
- [x] Shadow commands and all R013-R025 commands pass combined contract tests.
- [x] Paper and Live remain visibly and logically locked.
- [x] Official Shadow state remains absent and sample start remains locked.
- [x] Fresh UI proof shows Shadow Review and the R013-R025 workstation surfaces.
- [x] Protected-path and source-mutation reviews pass.
- [x] R027 is committed cleanly and remains unpushed/unmerged pending Steven review.
