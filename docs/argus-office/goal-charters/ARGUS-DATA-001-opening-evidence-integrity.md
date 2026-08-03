# ARGUS-DATA-001 Goal Charter - Opening Evidence Integrity

## Goal

Make opening TradePlan reports tell the truth about where each displayed price came
from and whether each stored catalyst is actually attributable to the candidate,
without changing any score, rank, plan, readiness, risk, selector, or broker behavior.

## Operator Outcome

Steven can distinguish captured prices, screener bid/ask, provider quote values,
hypothetical plan levels, provider-attempt failures, and execution-ineligible evidence.
An article attached to a candidate no longer looks like direct issuer news unless the
stored headline explicitly names that ticker or company.

## Scope

- Preserve source, provider time, local receipt time, age, authentication status,
  result status, and research/execution authority for every displayed price field.
- Preserve provider attempts separately so a Yahoo `HTTP_401` cannot be confused with
  a successful Nasdaq field source.
- Record source article, publisher, URL, mentioned ticker where explicit, candidate
  ticker/company, relationship type, evidence, and catalyst score authority.
- Mark unproven relationships `UNRESOLVED` and their evidence-review score authority
  `BLOCKED`.
- Export the integrity record in JSON, CSV, and Markdown while retaining report schema
  compatibility for existing downstream readers.

## Non-Goals

- Do not change candidate scoring, rank order, Risk Governor, selector arming,
  entry/stop/target formulas, position sizing, RVOL, FakeBroker, accounts, or broker
  behavior.
- Do not repair Monday's immutable artifacts or mutate raw captures.
- Do not install or reload the service, repin opening jobs, merge into canonical
  `master`, or alter the next opening runtime in this task branch.
- Do not infer sector, peer, or customer/supplier relationships from an unstructured
  headline without structured evidence.

## Acceptance Criteria

- [x] Nasdaq-owned bid/ask fields remain `SUCCESS` while a separate Yahoo quote attempt
  is preserved as `HTTP_401`.
- [x] All price fields carry complete metadata keys and remain `RESEARCH_ONLY` /
  `EXECUTION_INELIGIBLE` in the current report path.
- [x] Direct issuer headlines are supported; GOOGL/Baker Hughes is unresolved; a
  CMCSA row preserves explicit `DIS` mention without claiming a peer relationship.
- [x] Markdown says `CAPTURED PRICE`, `SCREENER BID/ASK` where applicable,
  `FRESH PROVIDER QUOTE`, `HYPOTHETICAL PLAN`, and `EXECUTION-INELIGIBLE`.
- [x] Raw capture nonmutation remains proven.
- [x] Monday-capture rank, composite score, scenario ranks, plan values, and readiness
  are byte-identical to canonical base `2aa4ef3`.
- [x] Compileall, focused, adjacent, full discovery, diff, protected-path, and secret
  checks pass before commit.

## Evidence Depth / Hard Chew

- Python compileall: pass.
- Focused evidence-integrity plus trade-planning tests: 23/23 pass.
- Adjacent selection/proof/alerts/monitor tests: 81/81 pass.
- Capture/raw-integrity/automation/report-loader tests: 57/57 pass.
- Full Python discovery: 1,059/1,059 pass after adding an ignored worktree-local
  `.venv` junction required by an existing installer-path test.
- Canonical comparison: Monday rank, scores, risk-on/off ranks, plan values, and
  readiness are byte-identical to base `2aa4ef3`.
- Monday's actual four catalyst rows classify as `UNRESOLVED` / `BLOCKED`; CMCSA also
  preserves the explicitly mentioned ticker `DIS`.

## Status

`IMPLEMENTED_PENDING_MERGE` on
`codex/ARGUS-DATA-001-opening-evidence-integrity`. Canonical runtime, service,
manifest, and pinned opening jobs remain untouched.
