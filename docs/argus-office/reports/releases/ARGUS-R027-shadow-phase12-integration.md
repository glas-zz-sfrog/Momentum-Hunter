# ARGUS-R027 - Shadow And Phase 12 Integration

## Branch And Status

- Branch: `codex/ARGUS-R027-integrate-r026-with-shadow-baseline`
- First parent: local `master` at `164e32e`
- Second parent: R026 at `838ed22`
- Safety branch: `safety/ARGUS-R027-before-r026-integration` at `164e32e`
- Classification: `IMPLEMENTED_PENDING_MERGE`
- Push: none
- Merge to `master`: none
- Official Shadow sample: not started

## Scope

R027 combines the canonical Shadow-003 baseline with the validated R013-R025
workstation stack while preserving a real two-parent history. The integration keeps
the read-only Shadow Review, frozen decision context, sample-readiness lock, and
post-collection Shadow observation path alongside chart inspection, command palette,
candidate evidence, health, replay, monitoring, activity, alert/outcome evidence,
technical research, saved watchlist, Daily Workflow, Candidate Story, and Research
Maturity.

Eleven merge conflicts were resolved additively in governance, host wiring, dependency
injection, layout/presentation state, and integration tests. No conflict markers
remain.

## Automated Verification

- Python compileall: pass.
- Focused combined Python suite: 146/146 pass.
- Full Python discovery: 641/641 pass in 211 seconds.
- .NET solution: 206/206 pass.
  - Presentation: 159
  - Layout: 5
  - Integration: 42
- Release build: pass with 0 warnings and 0 errors.
- `git diff --check`: pass.
- Daily Workflow extraction: all ten moved function bodies are AST-identical to
  local `master`; only their module boundary/type protocol changed.
- Source nonmutation: focused tests cover the read-only workspace, Daily Workflow,
  and Candidate Story projections; the official Shadow state file remained absent
  after compile, tests, packaging, and proof capture.

Two integration assertions were narrowed after the combined environment exposed
fixture assumptions:

- An impossible technical-research symbol now accepts either honest `UNAVAILABLE` or
  `EMPTY` while still requiring zero rows.
- Saved-watchlist integration validates documented state values and displayed/total
  count consistency instead of assuming the developer data directory is empty.

These are test-robustness changes only. Runtime semantics were not relaxed.

## UI Proof

### Phase 12 board

- Path:
  `docs/argus-office/reports/releases/ARGUS-R027-shadow-phase12-integration-proof.png`
- Dimensions: 1440 x 5490
- Size: 1,037,729 bytes
- SHA-256:
  `9DC43FD30F7F61DA655CE688429928C58E5070EE7370EBF701DDC70A4548FBAB`
- Pixel sanity: 113 unique colors in a 40-pixel sampling grid; nonblank.

The six-frame board visibly includes stored CRWV candle bodies/wicks/volume,
command palette, simulation-only Trade Plan and Risk Governor evidence, Technical
Research, saved Watchlist, Daily Workflow, Candidate Story, and locked Research
Maturity.

### Integrated Shadow linkage

- Path:
  `docs/argus-office/reports/releases/ARGUS-R027-shadow-review-linked-context-proof.png`
- Dimensions: 1880 x 1040
- Size: 132,253 bytes
- SHA-256:
  `36426961FB74F7F8470B955D3750A60A4AA5623123224B78483328300D76E02D`
- Pixel sanity: 28 unique colors in a 40-pixel sampling grid; nonblank.

The fresh integrated capture visibly includes `REVIEW - Read Only`, frozen Shadow
decision context, `SAMPLE START LOCKED`, `FAKEBROKER - NONTRANSMITTING`, and the
absence of a sample-start or order action.

The expanded Phase 12 dock layout leaves the lower Shadow grid compressed in a
whole-window offscreen capture. Detailed row, overview, evidence-lock, execution-
quality, and filter visuals therefore remain proven by the already-versioned
Shadow-003 screenshots rather than by duplicated R027 images:

- `ARGUS-SHADOW-003-sample-readiness-gate-overview-proof.png`
- `ARGUS-SHADOW-003-sample-readiness-gate-evidence-lock-proof.png`
- `ARGUS-SHADOW-003-sample-readiness-gate-execution-quality-proof.png`

Capture used temporary offscreen WPF harnesses outside the repository. It used no
mouse, keyboard, desktop takeover, provider fetch, official sample state, or source
data write.

## Review Build

- Directory:
  `%LOCALAPPDATA%\MomentumHunter\Builds\R027-shadow-phase12-integrated-review`
- Launcher:
  `Launch R027 Shadow Phase 12 Integrated Review.lnk`
- Python host: 96 packaged modules plus a read-only junction to the existing local
  evidence root.
- Local application state is isolated under the versioned build directory.

Use this launcher for manual R027 review. Do not use the pinned shortcut.

## Protected Areas

No production scoring module, trade-readiness module, replay-selection rule,
historical-capture selector, database/schema/migration, alert threshold, TradePlan
calculation, Risk Governor rule, FakeBroker fill/exit rule, broker adapter,
credential/API-key/env configuration, package/dependency file, production
configuration, provider fetch, Paper control, Live control, or transmitting method
changed.

The host still exposes the pre-existing prospective Shadow lifecycle internally, but
WPF has no sample-start action and C# exposes no sample-start command. The default
sample definition remains unauthorized, its readiness audit remains blocked, and
`MomentumHunterData/data/shadow-trading/shadow-trading-state.json` remains absent.

## Risks And Limits

- R027 is local only and is not remotely backed up.
- Local `master` remains ten commits ahead of `origin/master`; R027 is additional
  unpushed work.
- The manual multi-size, hover, filter, pane-close/reopen, and linked-selection checks
  remain Steven-verification items.
- Test discovery creates ignored `_test-*` directories under the local data root.
  They do not affect Git status or official Shadow state, but remain local hygiene.
- Proof fixtures demonstrate rendering and safety boundaries; they do not constitute
  official Shadow evidence or strategy results.

## Steven Check

Follow the numbered R027 checklist in
`docs/argus-office/VERIFICATION_QUEUE.md`. Report `PASS R027` only if all checks pass,
or report the failed number with workspace, symbol, interval, window size, and a
screenshot.

Passing the manual check does not itself merge or push R027 and does not authorize the
official Shadow sample.
