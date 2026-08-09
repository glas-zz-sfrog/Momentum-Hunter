# ARGUS-WORKTREE-HYGIENE-001 - No-Delete Worktree Inventory

## Verdict

Status: `IMPLEMENTED_PENDING_CEO_RETIREMENT_DECISION`.

Git worktree history is crowded but not currently unsafe. Canonical `master` is
clean and synchronized, every one of the 74 registered paths exists, and Git
reports no locked, prunable, inaccessible, or remotely diverged worktree. No
worktree, branch, file, or registration was removed, reset, stashed, moved,
repaired, or pruned during this audit.

The safest useful next reduction is a later **Batch A** retirement of only the
19 clean worktrees whose HEAD is already contained by canonical `master`.
Batch A would remove worktree directories/registrations only and retain every
local and remote branch. It is not executed by this task.

## Evidence Artifact

The complete 74-row machine-readable inventory is:

`docs/argus-office/reports/audits/ARGUS-WORKTREE-HYGIENE-001-inventory.json`

- Size: `668,949` bytes.
- SHA-256:
  `055B2209E1B30A904FB6B1D991C2120068C9013465F323E0C40CE911A6EBB008`.
- Every row contains absolute path, branch/detached identity, full HEAD, path
  existence, dirty count and dirty paths, `master` containment, ahead/behind,
  origin-branch presence/exactness, lock/prunable/status errors, and final
  classification.
- Pattern hits are branch names and filenames such as `Alpaca`, `Schwab`, or
  credential-governance reports. No file contents were copied.
- The known revoked Alpaca credential values and obvious `AKIA`/`sk-`-shaped
  values are absent.

Path aliases used below:

- `$REPO` = `C:\Users\steve\OneDrive\Documents\Investing`
- `$WORKTREES` = `C:\Users\steve\AppData\Local\MomentumHunter\worktrees`
- `$TEMP` = `C:\Users\steve\AppData\Local\Temp`
- `$ONEDRIVE_WORKTREES` =
  `C:\Users\steve\OneDrive\Documents\Investing-worktrees`

## Reconciled Totals

| Classification | Count | Disposition |
| --- | ---: | --- |
| Canonical operational preserve | 1 | Never retire through this plan. |
| Active clean preserve | 13 | Current integration, evidence, Roadmap, or visual-gate work. |
| Active dirty preserve | 1 | This audit worktree; dirty only from current audit artifacts. |
| Clean merged worktree retirement candidate | 19 | Recommended later Batch A, worktree only. |
| Clean unmerged exact-remote worktree candidate | 17 | Park; possible later Batch B after lineage review. |
| Clean unmerged local-only preserve | 1 | Preserve until explicitly backed up or superseded. |
| Dirty individual review | 22 | No batch action. One contains real edits; 21 are deletion-only historical shells. |
| **Total** | **74** | Counts reconcile exactly. |

Independent cross-checks:

- Clean worktrees at snapshot: `51`.
- Dirty worktrees at snapshot: `23`.
- HEADs contained by `master`: `24`.
- Exact matching origin branch: `52`.
- Remote-diverged worktrees: `0`.
- Missing origin branch: `22`.
- Detached worktrees: `1`.
- Missing, inaccessible, locked, or prunable worktrees: `0`.

Canonical nonmutation evidence:

- Canonical status before/after inspection: clean `master...origin/master`.
- Canonical local/origin HEAD before/after: `1d0ca95` / `1d0ca95`.
- Installed service before/after: `MomentumHunterAutomation` Running/Automatic.
- Installed manifest SHA-256 before/after:
  `E99E65A302B97A5D866071C3C1B37C8519972F8D55966EAC08772A1F6F093B47`.

## Preserve - Canonical And Active

| Path | Branch | HEAD | Reason |
| --- | --- | --- | --- |
| `$REPO` | `master` | `1d0ca95` | Canonical installed operational checkout. |
| `$WORKTREES\ARGUS-BROKER-ALPACA-001-paper-onboarding` | `codex/ARGUS-BROKER-ALPACA-001-paper-onboarding` | `39576d9` | Alpaca cumulative evidence chain. |
| `$WORKTREES\ARGUS-BROKER-ALPACA-002-fractional-capability` | `codex/ARGUS-BROKER-ALPACA-002-fractional-capability` | `256d442` | Alpaca cumulative evidence chain. |
| `$WORKTREES\ARGUS-BROKER-ALPACA-003-paper-lifecycle-proof` | `codex/ARGUS-BROKER-ALPACA-003-paper-lifecycle-proof` | `1abb4dd` | Market-hours acceptance pending. |
| `$WORKTREES\ARGUS-DATA-005B-provider-neutral-allocation` | `codex/ARGUS-DATA-005B-provider-neutral-allocation` | `046b127` | Validated integration candidate. |
| `$WORKTREES\ARGUS-MONITOR-001-candidate-lifecycle` | `codex/ARGUS-MONITOR-001-candidate-lifecycle` | `d2b77c2` | Validated integration candidate. |
| `$WORKTREES\ARGUS-CATALYST-002A-provider-neutral-evidence` | `codex/ARGUS-CATALYST-002A-provider-neutral-evidence` | `97ab34d` | Validated stacked integration candidate. |
| `$WORKTREES\ARGUS-REGIME-001-rolling-market-sector-regime` | `codex/ARGUS-REGIME-001-rolling-market-sector-regime` | `f4deb18` | Validated stacked integration candidate. |
| `$WORKTREES\ARGUS-EVENT-001-versioned-macro-event-context` | `codex/ARGUS-EVENT-001-versioned-macro-event-context` | `b6e861a` | Validated stacked integration candidate. |
| `$WORKTREES\ARGUS-BREAKOUT-001-sequential-research` | `codex/ARGUS-BREAKOUT-001-sequential-research` | `7492683` | Validated stacked integration candidate. |
| `$WORKTREES\ARGUS-ROADMAP-002-continuous-intraday-awareness` | `codex/ARGUS-ROADMAP-002-continuous-intraday-awareness` | `bae053b` | Preserved Roadmap source lineage. |
| `$WORKTREES\ARGUS-ROADMAP-002-current-master-reconciliation` | `codex/ARGUS-ROADMAP-002-current-master-reconciliation` | `e706b68` | Current-master reconciliation candidate. |
| `$WORKTREES\ARGUS-ROADMAP-003-parallel-pipeline` | `codex/ARGUS-ROADMAP-003-parallel-pipeline-refactor` | `2174817` | Authoritative branch-local scheduler. |
| `$WORKTREES\ARGUS-UI-STREAMLINE-001` | `codex/ARGUS-UI-STREAMLINE-001-workstation-hierarchy` | `989cb7c` | Visual acceptance pending. |
| `$WORKTREES\ARGUS-WORKTREE-HYGIENE-001` | `codex/ARGUS-WORKTREE-HYGIENE-001-inventory` | `1d0ca95` at snapshot | Current audit worktree. |

## Recommended Batch A - Clean And Merged

These 19 worktree HEADs are ancestors of canonical `master`, and all worktrees
were clean at inspection. The recommendation is to remove only their worktree
directories/registrations after a later exact approval. Do not delete branches.

| Worktree leaf | Branch | HEAD |
| --- | --- | --- |
| `ARGUS-BROKER-ALPACA-001-roadmap-reconciliation` | `codex/ARGUS-BROKER-ALPACA-001-roadmap-reconciliation` | `1d0ca95` |
| `ARGUS-DATA-001-opening-evidence-integrity` | `codex/ARGUS-DATA-001-opening-evidence-integrity` | `488cbca` |
| `ARGUS-DATA-001B-evidence-authority-enforcement` | `codex/ARGUS-DATA-001B-evidence-authority-enforcement` | `fe8c929` |
| `ARGUS-DATA-001C-schwab-quote-authority` | `codex/ARGUS-DATA-001C-schwab-quote-authority` | `40028f8` |
| `ARGUS-DATA-005A-account-portfolio-snapshot` | `codex/ARGUS-DATA-005A-account-portfolio-snapshot` | `91e461f` |
| `Investing-integration` | `codex/ARGUS-INTEGRATE-roadmap-r004` | `d3a98d9` |
| `ARGUS-MONDAY-001-opening-timing-hardening` | `codex/ARGUS-MONDAY-001-opening-timing-hardening` | `c344ed9` |
| `ARGUS-MONDAY-001-roadmap-closeout` | `codex/ARGUS-MONDAY-001-roadmap-closeout` | `50f2bae` |
| `ARGUS-MONDAY-002-sunday-readiness` | `codex/ARGUS-MONDAY-002-sunday-readiness` | `2006f25` |
| `Investing-r005` | `codex/ARGUS-R005-background-tray-lifecycle` | `e141054` |
| `ARGUS-R031B-current-master-integration` | `codex/ARGUS-R032-schwab-incremental-candle-collector` | `5442fbb` |
| `ARGUS-R032B-R033-candle-integration` | `codex/ARGUS-R032B-R033-candle-integration` | `af783da` |
| `ARGUS-R032C-automatic-candle-backfill` | `codex/ARGUS-R032C-automatic-candle-backfill` | `9f9967a` |
| `ARGUS-R034A-legacy-candle-consumer-migration` | `codex/ARGUS-R034A-legacy-candle-consumer-migration` | `1aafca5` |
| `ARGUS-SERVICE-006-state-write-retry` | `codex/ARGUS-SERVICE-007-state-write-retry` | `252cdc7` |
| `ARGUS-SHADOW-023-service-integration` | `codex/ARGUS-SHADOW-023-service-integration` | `cc2b1e2` |
| `ARGUS-SHADOW-024-post-monday-integration` | `codex/ARGUS-SHADOW-024-post-monday-integration` | `2aa4ef3` |
| `Investing-roadmap` | `codex/ARGUS-STATE-003-authoritative-roadmap` | `48d3ab4` |
| `monday-clock-task-reliability` | `codex/roadmap-self-reference-fix` | `ddc09f8` |

Expected effect if Batch A is later approved and revalidated immediately before
execution: registered worktrees fall from 74 to 55; branch count is unchanged;
canonical and installed runtime remain untouched.

## Park - Clean, Unmerged, Exact Remote Backup

These 17 worktrees are clean and their HEAD exactly matches an origin branch,
but they are not ancestors of current `master`. They are possible later
worktree-only retirement candidates, not Batch A, because several preserve
stacked lineage or historical evidence that may still aid integration.

| Worktree leaf | Branch | HEAD |
| --- | --- | --- |
| `ARGUS-FI-overnight-market-intelligence` | `codex/ARGUS-FI-overnight-market-intelligence` | `66b97ab` |
| `ARGUS-INTEGRATION-003-preopening-rehearsal` | `codex/ARGUS-INTEGRATION-003-preopening-rehearsal` | `f1aa09c` |
| `ARGUS-R031B-live-candle-proof-adjudication` | `codex/ARGUS-R031B-live-candle-proof-adjudication` | `36c792b` |
| `ARGUS-R031-schwab-candle-contract` | `codex/ARGUS-R032A-synthetic-candle-persistence-contract` | `d6d7217` |
| `ARGUS-R032B-schwab-historical-candle-backfill` | `codex/ARGUS-R032B-schwab-historical-candle-backfill` | `9f9ac96` |
| `ARGUS-R033-live-chart-engine-host-integration` | `codex/ARGUS-R033-live-chart-engine-host-integration` | `c88faa4` |
| `ARGUS-R035-candle-input-reconcile` | `codex/ARGUS-R035-candle-input-reconcile-1af5b31` | `7cbc2cb` |
| `ARGUS-R036-staged-candle-preview-host` | `codex/ARGUS-R036-staged-candle-preview-host-7cbc2cb` | `02f6423` |
| `ARGUS-R037-wpf-staged-candle-preview` | `codex/ARGUS-R037-wpf-staged-candle-preview-02f6423` | `089e1ff` |
| `ARGUS-SHADOW-016-017-reconcile` | `codex/ARGUS-SHADOW-016-017-reconcile-1af5b31` | `97884ea` |
| `ARGUS-SHADOW-018-trade-experiment-reports` | `codex/ARGUS-SHADOW-018-trade-experiment-reports` | `58e8b3c` |
| `ARGUS-SHADOW-019-experiment-study` | `codex/ARGUS-SHADOW-019-experiment-study` | `2934854` |
| `ARGUS-SHADOW-020-experiment-pipeline` | `codex/ARGUS-SHADOW-020-experiment-pipeline` | `2590bc2` |
| `ARGUS-SHADOW-021-automated-experiment-evidence` | `codex/ARGUS-SHADOW-021-automated-experiment-evidence` | `c766214` |
| `ARGUS-SHADOW-022-restart-lifecycle-integrity` | `codex/ARGUS-SHADOW-022-restart-lifecycle-integrity` | `b54a137` |
| `ARGUS-SHADOW-024-offline-terminal-review-packet` | `codex/ARGUS-SHADOW-024-offline-terminal-review-packet` | `48dbcb2` |
| `ARGUS-CANARY-021-current-baseline-reconciliation` | `codex/ARGUS-TECHNICAL-001-confluence-current-baseline` | `1b3cbcd` |

## Preserve - Clean Local-Only Branch

`$ONEDRIVE_WORKTREES\ARGUS-SHADOW-023-clock-normalized-quote-validation`
is clean at `919b64d`, unmerged to current `master`, and has no matching origin
branch. Preserve both its worktree and local branch until a separate lineage
review proves it superseded or backs it up intentionally.

## Dirty Worktrees - No Batch Action

### Substantive Dirty Work

`$WORKTREES\ARGUS-DATA-005B-shadow-allocation-activation` has seven real paths:

- Modified: `momentum_hunter/account_allocation_snapshot.py`
- Modified: `momentum_hunter/shadow_market_validity.py`
- Modified: `momentum_hunter/shadow_selection.py`
- Modified: `tests/test_account_allocation_snapshot.py`
- Modified: `tests/test_shadow_selection.py`
- Untracked: `momentum_hunter/account_allocation_policy.py`
- Untracked: `tests/test_account_allocation_policy.py`

This is protected, known strategy/allocation work. Do not clean, commit, stash,
or retire it through worktree hygiene.

### Deletion-Only Historical Shells

The remaining 21 dirty historical worktrees report only tracked-file deletions,
with no modified or untracked paths. Their directories still exist, but 461 to
653 files are absent. This likely reflects old temporary checkout cleanup, not
a useful editable state; nevertheless, deletion status is dirty state and is
preserved until individually adjudicated.

| Branch / detached identity | HEAD | Deleted paths |
| --- | --- | ---: |
| `(detached)` | `bb962be` | 467 |
| `codex/ARGUS-A016T-schwab-paper-api-response` | `1bc90a8` | 525 |
| `codex/ARGUS-CANARY-002-position-evidence-chain` | `9a19d78` | 594 |
| `codex/ARGUS-CANARY-003-funding-restrictions` | `ef9c0fc` | 592 |
| `codex/ARGUS-R012B-momentum-hunter-icon-redesign` | `ae05473` | 463 |
| `codex/ARGUS-R015-wpf-candidate-evidence` | `a9f27c7` | 461 |
| `codex/ARGUS-R016-wpf-health-diagnostics` | `89952aa` | 462 |
| `codex/ARGUS-R017-wpf-replay-context` | `b642aa9` | 463 |
| `codex/ARGUS-R018-wpf-monitoring-status` | `1137a02` | 464 |
| `codex/ARGUS-R019-wpf-activity-events` | `9cb3f8b` | 465 |
| `codex/ARGUS-R020-wpf-alert-outcome-evidence` | `1475c41` | 466 |
| `codex/ARGUS-R021-wpf-technical-research-evidence` | `756fbd2` | 472 |
| `codex/ARGUS-R022-wpf-saved-watchlist-evidence` | `8fd9b72` | 477 |
| `codex/ARGUS-R023-wpf-daily-workflow-evidence` | `22eac54` | 465 |
| `codex/ARGUS-R024-wpf-candidate-story-evidence` | `37a0778` | 465 |
| `codex/ARGUS-R025-wpf-research-maturity-evidence` | `5f0d36c` | 464 |
| `codex/ARGUS-R026-wpf-phase12-clean-room-integration` | `838ed22` | 520 |
| `codex/ARGUS-R035-candle-input-hardening` | `00fcda6` | 600 |
| `codex/ARGUS-R035-staged-schwab-chart-preview-host` | `16107c7` | 653 |
| `codex/ARGUS-REVIEW-R012B-R014-combined-ui` | `1a9c604` | 470 |
| `codex/ARGUS-SHADOW-017-evidence-checkpoints` | `4858d73` | 596 |

Before any later action, each must be checked for branch backup/containment and
whether its absent directory content was intentionally removed. The detached
entry requires special preservation because it has no branch name.

## Retirement Plan

### Stage 0 - Current Task

- Complete inventory and preserve its hash.
- Perform no retirement.
- Keep canonical, service, scheduler, data, and branches unchanged.

### Stage 1 - Recommended Batch A

- Obtain Steven's exact approval for the 19 named clean/merged worktrees.
- Immediately rerun status, HEAD containment, path, process, and runtime-path
  checks before action.
- Remove only the named worktree registrations/directories through Git-aware,
  path-verified operations.
- Retain every branch.
- Recount worktrees and prove canonical/service nonmutation.
- Stop on any changed state; do not partially improvise around a mismatch.

### Stage 2 - Optional Clean Remote-Backed Batch

- Wait until pending integration lineage is reconciled.
- Revalidate all 17 exact remote heads.
- Require a separate exact approval.
- Remove worktrees only; retain local and remote branches.

### Stage 3 - Dirty Individual Review

- Review the one seven-file allocation checkout as protected active work.
- Audit each deletion-only shell independently.
- Create a branch for the detached `bb962be` identity before any later removal
  if that commit is not otherwise safely named.
- Never use forced removal as a substitute for classification.

### Stage 4 - Branch Retirement

Branch deletion is not part of this plan. Any future branch-retirement task must
have its own containment/remote evidence and explicit Steven approval.

## CEO Decision

Recommended later decision phrase:

`APPROVE WORKTREE-HYGIENE-001 BATCH A WORKTREE-ONLY RETIREMENT; RETAIN ALL BRANCHES`

That phrase would authorize only a fresh preflight and the 19 named Batch A
worktree removals. It would not authorize Batch B, dirty checkout cleanup,
branch deletion, reset, stash, prune, force removal, canonical changes, or
runtime changes.

## Integration Note

This branch and UI-STREAMLINE-001 both append supporting governance files from
the same `1d0ca95` base. Their runtime/code scopes do not collide, but their
documentation commits are sibling histories. Integrate them only through the
serialized current-master reconciliation lane; do not force, reset, or invent a
non-fast-forward merge merely to combine append-only records.
