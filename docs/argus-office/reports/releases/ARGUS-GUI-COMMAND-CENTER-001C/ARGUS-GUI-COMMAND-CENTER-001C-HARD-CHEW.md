# ARGUS-GUI-COMMAND-CENTER-001C-C Hard Chew Evidence

## Scope and isolation

The production Command Center was launched from the task worktree executable,
not from the installed or canonical workstation:

`C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-GUI-COMMAND-CENTER-001C-PRODUCTION-INTEGRATION\src\MomentumHunter.Desktop.Wpf\bin\Debug\net8.0-windows\MomentumHunter.Desktop.Wpf.exe`

The proof used these process-local environment overrides:

- `MOMENTUM_HUNTER_ENGINE_HOST_STATE_DIRECTORY=C:\Users\steve\AppData\Local\MomentumHunter\command-center-001c-proof-host`
- `MOMENTUM_HUNTER_REPOSITORY_ROOT=C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-GUI-COMMAND-CENTER-001C-PRODUCTION-INTEGRATION`
- `MOMENTUM_HUNTER_CONTINUOUS_RUNTIME_STATE_ROOT=C:\ProgramData\MomentumHunter\ContinuousRuntime`

`MOMENTUM_HUNTER_ENGINE_HOST_STATE_DIRECTORY` is an optional proof-isolation
hook. When it is unset, the existing default remains
`%LOCALAPPDATA%\MomentumHunter\python-engine-host`. It is not a production
configuration change and does not alter host protocol, provider, broker,
writer, lifecycle, scoring, readiness, risk, or order behavior.

The observed isolated Python process command line used the proof state
directory and the explicit Continuous runtime evidence root. Its runtime build
identity was
`9ca7a31d0cbe3c8d52c561cb2c4847b276aed4d53369328e6dd701768c70e0c5`.
The canonical endpoint and canonical workstation processes were not stopped,
reconfigured, or overwritten. After capture, only the verified worktree UI and
isolated host processes were stopped. The ephemeral endpoint and lock files
were removed.

## Observed runtime truth

The real WPF application received the v3 Command Center projection. The
accessibility tree and native image showed:

- session `2026-08-27`;
- projection `PARTIAL`;
- Radar `15`, sourced from current-session `TRACKED` Hot Universe evidence;
- Accepted and Rejected `UNAVAILABLE` because Candidate Lifecycle evidence was
  absent at the configured runtime evidence root;
- zero source-ranked rows because no persisted trade-planning report was
  available in the isolated worktree data root;
- Radar geometry `PENDING` / `NOT YET AUTHORIZED` with no inferred symbol
  placement;
- Shadow positions explicitly labeled `FAKEBROKER · READ ONLY`;
- host health `HOST PARTIAL` and projection data `PARTIAL` shown as separate
  signals;
- explicit source limitations, with no synthetic candidates, dispositions,
  charts, or fallback data;
- no repeated five-second Engine Host polling rows in `WHAT CHANGED` after
  observing multiple refresh cycles; the three remaining workspace rows are
  deduplicated source-availability summaries scoped to `SYSTEM`;
- no broker, order, buy, sell, submit, cancel, or execution control.

This partial state is the expected truth for the selected evidence roots. It
proves the changed host/read-model path in the real application without
manufacturing missing lifecycle or report evidence.

## Visual comparison

The accepted 001B visual remains the macro hierarchy reference. The production
implementation preserves the left navigation, five-card summary row, Radar /
ranked-candidate / disposition triad, and bottom event / Shadow / System row.

The directive-required difference classification is:

| Difference | Classification | Disposition |
| --- | --- | --- |
| Radar `15`, Accepted/Rejected unavailable, no ranked rows | `RUNTIME_TRUTH_DIFFERENCE` | The captured evidence root has current-session Hot Universe evidence but no Candidate Lifecycle file, while the isolated worktree data root has no report. No example rows were retained. |
| Empty Accepted/Rejected and chart regions | `RUNTIME_TRUTH_DIFFERENCE` | Empty/unavailable panels preserve accepted geometry without manufacturing evidence. |
| Radar nodes absent | `MISSING_READ_MODEL` | Geometry semantics are not authorized; the region explicitly says `GEOMETRY PENDING` / `NOT YET AUTHORIZED`. |
| Earlier non-maximized 1440-wide rightmost header compression | `TECHNICAL_CONSTRAINT` | Recorded below; it is absent from the required native 1920x1080 surface. |
| Other macro, hierarchy, lifecycle, or control-surface difference | `UNAUTHORIZED_DESIGN_DRIFT` | `NONE`. |

`UNAUTHORIZED_DESIGN_DRIFT: NONE`

The intentional runtime differences are:

- real evidence replaces all example symbols and values;
- the Radar map remains a labeled pending geometry rather than inventing a
  placement algorithm;
- unavailable populations remain empty and visibly unavailable;
- the ranked board remains empty when its source report is absent;
- `HOST HEALTH` and `PROJECTION DATA` are separated so transport health cannot
  imply projection completeness;
- the footer uses bounded columns to avoid concatenating status text.

The corrected proof also shows that periodic host refresh activity remains in
host/System status and does not flood or masquerade as symbol evidence in
`WHAT CHANGED`. Hot Universe events carry their exact Radar membership identity
separately from the explicitly derived lifecycle opportunity identity, and an
invalid or absent ranked score remains unavailable instead of becoming zero.

Native 1920x1080 review found no clipping in the top status strip, summary
cards, ranked-board header, disposition panels, System Context, or footer. The
center/right width ratio was tightened to match the accepted macro hierarchy.
The earlier non-maximized 1440-wide observation compressed the rightmost top
status field; the accepted and required native 1920x1080 surface does not.

## Required artifacts

- `ARGUS-GUI-COMMAND-CENTER-001C-overall-1920x1080.png`
  - dimensions: `1920x1080`
  - SHA-256: `89C5B7BF1A2F2B9E21FCE77CB2F63E998DCD38C539BAE00A87481A9546041689`
- `ARGUS-GUI-COMMAND-CENTER-001C-accepted-vs-implementation.png`
  - dimensions: `3840x1140`
  - SHA-256: `E5C4731C9F9574CC40A580679097505168B8B7F73848E603C3D213CA217374A6`

The comparison is intentionally side-by-side rather than a pixel-difference
heat map because the accepted 001B file contains example populations while the
001C image contains observed persisted-evidence truth.

## Verification evidence

- Focused Command Center Python tests: `10/10` passed.
- Focused host/mapper integration tests: `6/6` passed.
- Focused Command Center presentation/activity tests: `13/13` passed.
- Broader affected Python boundary regression: `153/153` passed across the
  engine host, workstation read models, Command Center read model, Hot
  Universe, Candidate Lifecycle, workstation charts, and continuous TradePlan
  producer suites.
- Full .NET solution regression: `271/271` passed (`212` presentation, `53`
  integration, `6` layout).
- Desktop build: succeeded with `0` warnings and `0` errors.
- An additional optional whole-repository Python discovery run exceeded the
  bounded 20-minute policy without emitting a unittest completion summary. Its
  result is `INCONCLUSIVE_HUNG_NO_FAILURE_SUMMARY` (neither pass nor failure).
  Only its exact verified process chain was terminated; the required bounded
  relevant regression above remains green.
