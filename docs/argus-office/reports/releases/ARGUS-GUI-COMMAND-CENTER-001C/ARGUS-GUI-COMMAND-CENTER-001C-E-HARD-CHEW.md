# ARGUS-GUI-COMMAND-CENTER-001C-E Hard Chew Evidence

## Scope and Git gate

This repair remains isolated on
`codex/ARGUS-GUI-COMMAND-CENTER-001C-PRODUCTION-INTEGRATION`. The fresh gate
proved the expected pre-repair commit
`93088769544547b6b9a88e5b972d99e0be3e10c7`, canonical identity
`23ee162373654e1db91af4c19f75bbc7887e3174`, Producer-001C identity
`b7f6df51e9f6e08056c58b419c870f116096179c`, a clean task worktree, and the
accepted 001B visual SHA-256
`22BB20149EE3D5A3A2A73336AFA34E806DEE6B14E8D5C6F3DE94F73EB6235FDA`.

Only the two defects authorized by 001C-E changed: native-width Ranked
Candidates overflow and same-timestamp lifecycle chronology. No merge,
installation, startup/Start Menu change, or canonical-workstation replacement
occurred.

## Defect 1: Ranked Candidates native width

The ranked ListBox now explicitly disables horizontal scrolling. The accepted
center-board geometry, text sizes, fields, and matching header/row columns
remain unchanged at `34 / 70 / 64 / 58 / 1* / 142 / 76`. Long catalyst text
continues to use ellipsis inside the proportional catalyst column.

The native 1920x1080 populated proof shows all eight source-ranked rows at
once. Rank, symbol, score, RVOL, catalyst/population, stored 2-day/15-minute
microchart, and row freshness remain visible and readable. No horizontal
scrollbar is present. Accepted and Rejected retain the accepted right-column
geometry.

## Defect 2: lifecycle chronology

The read-only projection and contract now carry the exact nullable persisted
`sourceSequence` from Candidate Lifecycle and Hot Universe evidence. Neither
writer nor state machine changed.

The final presentation key is:

1. `occurred_at` descending;
2. deterministic source/ledger grouping;
3. within that same source/ledger only, non-null authoritative
   `sourceSequence` before missing sequence and `sourceSequence` descending;
4. `eventIdentity` ordinal as the deterministic final tie.

The stable timestamp pass remains outermost. Source sequence is never compared
globally across unrelated sources. Input enumeration order, state names, event
text, and dictionary order do not determine chronology.

The authoritative BMNR events at
`2026-08-27T11:55:45.414196-05:00` now appear newest first as persisted
sequences `18, 17, 16, 15`:

- `FAILED_BREAKOUT -> RECLAIM_FORMING`
- `BREAKOUT_CONFIRMED -> FAILED_BREAKOUT`
- `BREAKOUT_FORMING -> BREAKOUT_CONFIRMED`
- `IMPULSE_DETECTED -> BREAKOUT_FORMING`

## Automated verification

- Python compilation: passed.
- Focused Command Center Python: `11/11` passed.
- Adjacent Command Center/read-model Python: `20/20` passed.
- Broader affected Python boundary regression: `154/154` passed across Engine
  Host, workstation read models, Command Center, Hot Universe, Candidate
  Lifecycle, charts, and Continuous TradePlan producer tests.
- Focused presentation/layout: `11/11` passed.
- Presentation suite: `214/214` passed.
- Exact mapper check: `1/1` passed.
- Integration suite: `53/53` passed.
- Full .NET solution: `273/273` passed (`214` presentation, `53` integration,
  `6` layout).
- Release solution build: succeeded with `0` warnings and `0` errors.
- Diff check, bounded protected-path review, and added-line secret scan: clean.

## Authoritative populated proof

The Release WPF executable was launched only from this task worktree with an
isolated Engine Host state directory and the same read-only authoritative
001C-D evidence set. The selected session is `2026-08-27`:

- Radar: `19` current-session authoritative `TRACKED` memberships.
- Ranked: `8` rows from the preserved evening TradePlan report.
- Accepted: `0`, because the evidence has no first `EXECUTION_ELIGIBLE`
  disposition for the session.
- Rejected: `1`, BMNR `FAILED_BREAKOUT`.
- Stored history: truthful partial 91-point microcharts for NVDA and CRM and a
  partial BMNR disposition chart; unavailable histories remain unavailable.
- Radar geometry: still explicitly `NOT_YET_AUTHORIZED`; no nodes are inferred.
- Shadow positions: read-only and unavailable; no order control is present.

No example, generated, fallback, or synthetic row was introduced. The evidence
source hashes remained unchanged from 001C-D:

- Hot Universe: `2B8C3B402BD3DE2DEC397B5F6DC4B11E0492F67AA1848720D859CD66410A893A`
- Candidate Lifecycle: `D62267706013142296541409A6A97B5B3E1244B926C8D21F44E4C42BFFF59BB7`
- Continuous producer: `E4EE3B24382520E2C2F50A5C29835B08CB120F41DE96EEC8384C672B7C55817D`
- Evening ranked report: `9C0A8750223DB6304F1D37F478D42E271E29F31C4E6320130DD9966E2A26C801`
- Candle-set aggregate: `0F771063A582783923CE3931E373BF5F5FC750F7FF9390269278DC60C776A4C9`
- Source mismatch count: `0`.

Only the exact isolated WPF and its proof Engine Host process chain ran. Both
were stopped after capture; no proof process remained.

## Required artifacts

- `ARGUS-GUI-COMMAND-CENTER-001C-E-populated-1920x1080.png`
  - dimensions: `1920x1080`
  - SHA-256: `FC0F8A5944F1262078CDE2ADA5D0716E4617C9A1422D30923411F3EE54E8D4D2`
- `ARGUS-GUI-COMMAND-CENTER-001C-E-ranked-microcharts.png`
  - dimensions: `748x575`
  - SHA-256: `6D330F37FE38F56CF459A09BEEFB089818691805B33CD21876305609AD84511C`
- `ARGUS-GUI-COMMAND-CENTER-001C-E-chronology.png`
  - dimensions: `784x312`
  - SHA-256: `651ED9394503E6289FDAC56565D22DFB82D0A6D4EB811E9A6656B04E952646A9`
- `ARGUS-GUI-COMMAND-CENTER-001C-E-accepted-vs-runtime.png`
  - dimensions: `3840x1080`
  - SHA-256: `8884279FB796EED646413BFBA0823BB32B0411709361374250644610C3FC7420`

## Authority and protected-area review

Radar, Accepted, Rejected, and cross-lifecycle ranked-candidate semantics are
unchanged. Chart and display-freshness data remain human context only and have
no ranking, scoring, admission, readiness, risk, entry, exit, or execution
authority. No lifecycle writer/state machine, Hot Universe writer/policy,
TradePlan/scoring logic, provider, broker, order, database, migration, secret,
or production configuration changed.

## Terminal result

- `RANKED_NATIVE_WIDTH_DEFECT_RESOLVED = YES`
- `FRESHNESS_VISIBLE_WITHOUT_HORIZONTAL_SCROLL = YES`
- `SAME_TIMESTAMP_LIFECYCLE_ORDER_PROVEN = YES`
- `POPULATED_MICROCHART_VISUAL_PROVEN = YES`
- `UNAUTHORIZED_DESIGN_DRIFT = NO`
- `HARD_CHEW_COMPLETE = YES`
- `READY_FOR_STEVEN_FINAL_VISUAL_ACCEPTANCE = YES`
- `MERGE_AUTHORIZED = NO`
- `INSTALL_AUTHORIZED = NO`
