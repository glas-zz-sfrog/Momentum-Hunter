# ARGUS-SHADOW-002 - WPF Shadow Review

## 1. Shadow-001 Merge Readiness

Classification: `READY_WITH_BOUNDED_FULL_SUITE_CAUTION`.

ARGUS-SHADOW-001 passed complete diff review, fresh detached-worktree verification, focused and adjacent Python tests, all .NET tests, Release build, and post-merge verification. Local `master` fast-forwarded from `69feedf` to `bb962be`; no merge commit and no master push occurred.

## 2. Full Python Timeout Diagnosis

Discovery is healthy: 558 tests across 91 modules collect in about three seconds. Per-module bounded execution completed 89 modules. The two legacy Qt modules `tests.test_entry_plans` and `tests.test_gui_states` contain four hanging GUI cases and two failures, all outside the Shadow-001/002 diff. No orphan test process remained. This is a documented harness caution, not a Shadow evidence, P&L, restart, duplicate, ledger, FakeBroker, or Schwab-safety defect.

## 3. Clean-Room Verification

The detached Shadow-001 worktree passed Python compileall, 60 focused tests, 68 adjacent tests, 88 .NET tests, and a zero-warning Release build without local-only files or tracked generated reports.

## 4. Master Integration

Local `master` is `bb962be`, three commits ahead of `origin/master` at `69feedf`. Shadow-001 is integrated locally. Nothing was pushed and R026 remains separate.

## 5. Roadmap Reconciliation

The authoritative Roadmap records Shadow-001 as complete on local `master`, Shadow-002 as `IMPLEMENTED_PENDING_MERGE`, A017 as `BLOCKED_VENDOR_CAPABILITY`, FakeBroker as the only automated execution boundary, and 30 eligible completed trades as the minimum sample. The official sample has not started.

## 6. Branch And Goal Charter

- Branch: `codex/ARGUS-SHADOW-002-wpf-shadow-review`
- Goal Charter: `docs/argus-office/goal-charters/ARGUS-SHADOW-002-wpf-shadow-review.md`
- Scope: read-only Python snapshot projection, strict .NET mapping, WPF review pane, evidence/sample gating, linked review navigation, tests, and UI proof.

## 7. WPF Review Surface

The Review workspace now includes a dockable Shadow Review pane with:

- Shadow/candidate/plan/risk identities, setup, catalyst, regime, session, and decision/evidence timestamps.
- Proposed entry, FakeBroker fill, spread, slippage, stop, targets, exit, exit reason, ideal/executable P&L, R, MFE, MAE, duration, and lifecycle.
- Evidence and plan locks, correction state, audit state, data quality, sample eligibility, and technical event codes.
- Human-first execution explanations for spread, slippage, no fill, partial/delayed fill, quote rejection, stale/missing quote, halt, and stop gaps.
- Date/session, setup, catalyst, regime, outcome, and eligibility filters.
- Linked Chart, frozen Trade Plan, Why, and Activity updates that respect link groups and pinned panes.

The WPF client has one method, `GetSnapshotAsync`. It exposes no create, advance, submit, cancel, modify, Paper, Live, credential, network, or broker method.

## 8. UI Proof

- Path: `docs/argus-office/reports/releases/ARGUS-SHADOW-002-wpf-shadow-review-overview-proof.png`
- Dimensions: 1880 x 1040
- Size: 177,060 bytes
- SHA-256: `8374F5BDD74F74475B92E114C14CDA28B83E0946194A1D8FFE3D22541DAF3902`
- Pixel sanity: 31 unique colors in a 40-pixel sampling grid; nonblank.
- Visible proof: Review/read-only mode, FakeBroker/nontransmitting label, filters, `1 / 30`, all sample counts, withheld metrics, frozen evidence, frozen plan, no correction, selected lifecycle/outcome, Chart, Why context, and no order action.

The image uses synthetic proof fixtures and does not create a Shadow state file or count toward the official sample.

## 9. Evidence-Lock Proof

The Python audit now recomputes candidate, evidence, Shadow Trade, TradePlan, Risk Governor, and outcome identities from the frozen source/candidate/plan payloads. It also checks source metadata, hashes, candidate/report equality, decision timestamp equality, ledger chronology, and correction/override/amend/edit/mutation events. Any mismatch fails closed and excludes the record.

## 10. Metric Calculations

Eligible completed records alone feed review metrics. Before 30 records, win rate, average win/loss, expectancy, average R, maximum drawdown, profit factor, and ideal-versus-executable values are set to `null` by Python and shown as `Withheld` by WPF. At 30, tests prove the aggregate metric payload is released. Tiny subgroup best/worst conclusions are not shown.

## 11. Sample-Gating Proof

- [x] Shadow-001 integrated locally.
- [ ] Shadow-002 accepted and integrated; Steven decision still required.
- [x] Evidence snapshots and TradePlans are fingerprinted and identity-chain audited.
- [x] Duplicate command IDs are idempotent and conflicting reuse fails.
- [x] Restart recovery and malformed-state failure are tested.
- [x] P&L, R, MFE, and MAE are deterministic and tested.
- [x] Fill assumptions are frozen: executable ask/bid, configured slippage, delayed-fill requirement, spread/session/quote-age gates, partial-fill rules, and conservative gap/ambiguous-exit handling.
- [x] Data-quality exclusions are deterministic: non-`COMPLETE`, failed lock/audit, or correction evidence is excluded.
- [x] Manual override policy is explicit: WPF cannot edit; any correction/override evidence excludes the record. A material rule change closes the sample and requires a new version.
- [x] Aware timestamps, post-decision quote ordering, regular/extended session policy, stale quotes, and out-of-order observations are tested.

Official sample rules: prospective only; no retroactive additions; no deleting losers; no mid-sample change to fill, score, risk, stop, or target rules. A material rule change closes the current sample, records the reason, and starts a new version.

## 12. Protected-Path Review

No scoring, readiness, replay identity, historical capture selection, database/schema, alert threshold, provider-fetch, Schwab network, credential, account, OAuth, Paper, Live, or transmitting behavior changed. The narrow Shadow audit hardening changes review eligibility only when frozen evidence is inconsistent.

## 13. Known Limitations

- Full Python discovery retains the legacy Qt hang/failure caution described above.
- Shadow-002 is branch-only and not remotely backed up until a separate push is approved.
- The UI proof is synthetic; no official prospective sample records exist yet.
- Schwab paperMoney remains inaccessible through Trader API, and A017 remains vendor-blocked.
- R026 remains a separate workstation review and merge decision.

## 14. Readiness

Classification: `READY_WITH_DOCUMENTED_CAUTIONS`.

Shadow-001 is ready and integrated locally. Shadow-002 passes automated and visual proof but is not accepted or merged yet. Therefore the official 30-trade sample must not begin until Steven reviews the proof, approves local fast-forward, and confirms the frozen sample rules.

## Verification

- Python compileall: pass.
- Bounded Python suite: 84/84 pass.
- .NET suite: 98/98 pass.
- Release build: pass, 0 warnings, 0 errors.
- `git diff --check`: pass.
- Push: none.
- Shadow-002 merge: none.
