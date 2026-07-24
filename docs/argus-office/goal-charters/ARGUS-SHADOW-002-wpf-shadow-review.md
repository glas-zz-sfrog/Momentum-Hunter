# ARGUS-SHADOW-002 Goal Charter - WPF Shadow Review

## Goal

Give Steven a restrained, dockable WPF surface for reviewing prospective Shadow Trades and their immutable Python/FakeBroker evidence before the first official 30-trade sample begins.

## Operator Outcome

Steven can select a Shadow Trade, understand the frozen decision, plan, risk result, simulated execution quality, outcome, and sample eligibility, then inspect the same symbol in linked Chart, Trade Plan, Why, and Activity contexts without granting the workstation any new execution authority.

## Scope

- Add a read-only Python-host snapshot client and strict .NET mapper for canonical Shadow Trading results.
- Add a dockable Shadow Review pane to the Review workspace.
- Show trade, plan, risk, execution, outcome, evidence-lock, audit, lifecycle, and sample-status fields.
- Explain spread, slippage, no fill, partial/delayed fill, stale/missing quote, halt, and stop-gap evidence in operator language, with raw codes under Technical Details.
- Gate aggregate performance metrics until at least 30 eligible completed prospective trades exist.
- Add restrained date/session, setup, catalyst, regime, outcome, and evidence-eligibility filters.
- Update linked unpinned Chart, Trade Plan, Why, and Activity contexts when a reviewed trade is selected.
- Add focused Python and .NET tests plus offscreen WPF screenshot proof.

## Non-Goals

- No Schwab, Paper, or Live order submission.
- No broker network, credential, account, OAuth, provider-fetch, or transmitting method.
- No new Shadow Trade creation, advancement, editing, deletion, or manual override control in WPF.
- No scoring, readiness, replay identity, alert, TradePlan, Risk Governor, FakeBroker fill, P&L, MFE, MAE, schema, or execution-policy semantic change.
- No R026 workstation consolidation; R026 remains a separate review and merge decision.
- No official 30-trade sample start in this task.

## Protected Areas

Core scoring, trade readiness, replay identity, historical capture selection, database schema/migrations, broker/order execution behavior, alert threshold semantics, secrets/API keys/env config, production configs, and runtime execution authority remain unchanged.

## Acceptance Criteria

- [ ] The WPF Review workspace exposes a dockable Shadow Review pane.
- [ ] The pane maps canonical Python Shadow snapshot data without fallback fabrication.
- [ ] Every required identity, plan, risk, execution, outcome, lifecycle, evidence-lock, and sample-count field is visible or honestly unavailable.
- [ ] A failed evidence or plan audit excludes the trade from the 30-trade sample.
- [ ] Metrics are withheld below 30 eligible completed records and become visible only at the gate.
- [ ] Filters are compact and deterministic.
- [ ] Selection updates only linked, unpinned review contexts.
- [ ] The pane exposes no create, advance, submit, cancel, modify, Paper, Live, credential, or broker-network command.
- [ ] Focused Python projection tests, .NET mapper/presentation tests, full .NET tests, Release build, Python compileall, and bounded adjacent Python tests pass.
- [ ] Offscreen proof shows the pane, sample gate, evidence locks, execution explanation, metrics gate, filters, and FakeBroker/nontransmitting language.
- [ ] Protected-path diff review finds no protected semantic changes.

## Evidence Depth / Hard Chew

- Compile Python and build the WPF solution in Release mode.
- Test eligibility failure, immutable evidence, deterministic counts, metric gating, strict mode/transmitting rejection, malformed payload rejection, filter behavior, linked-pane selection, and pinning.
- Run the full .NET suite and bounded adjacent Shadow/host Python suites.
- Generate and inspect a nonblank offscreen WPF screenshot.
- Review the complete diff for Schwab networking, credentials, transmitting verbs, broker execution changes, scoring/readiness/replay/alert changes, generated output, and accidental sample-start behavior.
- Perform a second-pass review, narrow fix pass, and final verification before commit.

## Smallest Safe Implementation Slice

One read-only Shadow snapshot projection, one WPF review pane, focused tests, and proof. No mutation command crosses the WPF boundary.

## Open CEO Decisions

- None required to build the review-only surface.
- Steven must separately accept Shadow-002 and the manual verification queue before the official sample may begin.

## Goal Steward Review

- [x] Goal and operator outcome are concrete.
- [x] Scope and non-goals are explicit.
- [x] Protected areas and execution-authority limits are named.
- [x] Acceptance criteria prove real review behavior.
- [x] Evidence depth satisfies the Hard Chew Protocol.
