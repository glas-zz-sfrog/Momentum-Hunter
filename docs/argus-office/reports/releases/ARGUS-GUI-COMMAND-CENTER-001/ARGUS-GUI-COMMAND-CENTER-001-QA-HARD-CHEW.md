# ARGUS-GUI-COMMAND-CENTER-001 QA / Hard Chew

## Verdict

`AUTOMATED_QA_PASS — STEVEN_VISUAL_ACCEPTANCE_PENDING`

Independent final verification completed read-only at
`2026-08-26T21:48:29.4690999-05:00` on
`codex/ARGUS-GUI-COMMAND-CENTER-001`, based at
`82460b3313b86c34dff4ffb737d2c04bf02e3ace`.

No open P0, P1, or P2 code/visual finding remains in the final inspected
worktree. Steven remains the final visual acceptance authority, so this branch
must not be merged as complete from automated evidence alone.

## Findings By Priority

### Open findings

- P0: none.
- P1: none.
- P2: none.

### Closed during this chew

1. Production evidence projection initially did not prove the required exact
   `UNKNOWN / HISTORY LOADING` and `RECLAIM READY / QUOTE STALE` pairs. Builder
   added exact production-path projection tests while retaining the truthful
   generic `NEEDS EVIDENCE` and `STALE` fallbacks when those exact labels are
   not exposed.
2. Stable historical selection initially lacked a sufficiently explicit
   Decision treatment. Final proof shows the CURRENT answer preserved above a
   separate amber `HISTORICAL EVIDENCE` block, stable identity/source/time,
   `Return to Current`, and an amber selected timeline row.
3. The Command Center menu initially retained monitoring/run-scan controls.
   Final XAML exposes navigation/status/exit only and contains no service or
   simulation action.
4. The first verified 1180x820 render clipped caption controls and selected
   price/change. Builder repaired the compact title bar, selected header,
   candidate rows, and stable-history focus. All corrected frames were
   regenerated and independently inspected at original detail.

## Code And Behavior Review

- `CommandCenterModels.cs`: source order is preserved; UI age/freshness uses
  `ObservedAt` for display only; opportunity and evidence remain separate;
  exact exposed evidence labels are preserved without inventing
  `HISTORY LOADING`; missing target 2/setup values remain explicitly
  unavailable.
- `ShellViewModel.cs`: Live Universe, Focus, Decision, and What Changed share
  the selected symbol; selecting timeline evidence does not replace the
  current candidate/TradePlan; returning to current clears only the timeline
  selection; What Changed recomposes reverse chronologically.
- `WorkspaceFactory.cs`: Live defaults reuse Hunter/Chart/TradePlan/Activity
  `PaneKind` values and make What Changed visible without duplicating kinds.
  Legacy titles upgrade narrowly. Current/Replay/Review switching remains
  reachable from the application Menu.
- `MainWindow.xaml` / code-behind: candidate selection unwraps the presentation
  row to the existing candidate snapshot; Decision and timeline render current
  versus stable history distinctly; compact health and read-only Positions
  remain available; no Buy, Sell, Submit, Replace, Cancel, Arm, Approve,
  service-control, or simulation action appears in the Command Center.
- Positions stays read-only and fails visibly to unavailable when no position
  snapshot is supplied. No fallback position was fabricated.

## Final Tests And Build

Commands were run from the GUI task worktree:

```text
dotnet test tests-dotnet/MomentumHunter.Presentation.Tests/MomentumHunter.Presentation.Tests.csproj -c Release --no-restore --filter "FullyQualifiedName~CommandCenterModelsTests|FullyQualifiedName~ChartReadabilityTests|FullyQualifiedName~PaneRegistryTests" --property:TreatWarningsAsErrors=true
dotnet test tests-dotnet/MomentumHunter.Layout.Tests/MomentumHunter.Layout.Tests.csproj -c Release --no-restore --property:TreatWarningsAsErrors=true
dotnet build MomentumHunter.Workstation.sln -c Release --no-restore -warnaserror
dotnet test MomentumHunter.Workstation.sln -c Release --no-build --no-restore --property:TreatWarningsAsErrors=true
```

Results:

- focused Command Center/chart/pane tests: `77/77` passed;
- Layout tests: `6/6` passed;
- full solution: `287/287` passed (`230` Presentation, `6` Layout,
  `51` Integration);
- Release build: passed with `0` warnings and `0` errors.

## Diff, Boundary, And Capability Audit

- `git diff --check`: pass; only Git's informational LF-to-CRLF warnings were
  emitted.
- Final changed paths including this report: `21`; allowed: `21`; forbidden:
  `0`.
- Protected source/config/runtime paths changed: `0`.
- Project/package files changed: `0`; repository remains `11` `.csproj` files
  and `1` solution.
- Added secret-pattern matches: tracked `0`; untracked text `0`; values were
  never printed.
- Command Center prohibited-control matches: `0`.
- XAML content IDs: `16`; unique: `16`; duplicates: `0`.
- The Integration `ShellWorkflowTests.cs` change is allowed under the reviewed
  Goal Charter's higher-authority `tests-dotnet/**` GUI/workspace/read-only
  shell test boundary. It updates the stale hidden-Activity expectation to the
  required default-visible What Changed behavior. The narrower architecture
  handoff wording does not make this necessary GUI test forbidden.

## Isolated Visual Proof

The harness lives outside repository source at
`C:\Users\steve\AppData\Local\Temp\MomentumHunter-ARGUS-GUI-CC-001-QA`.
It uses a fresh WPF Window/view model per scenario, deterministic fixtures
explicitly labeled as non-production data, blocks simulation/service methods,
detaches the production `App.OnStartup` path, positions the native window
offscreen without activation, and asserts exact native client dimensions with
`GetClientRect` before `RenderTargetBitmap` capture. It did not move the mouse,
focus another application, capture desktop pixels, contact providers, or open
the installed app.

The earlier screen-clamped/stale captures failed QA, were overwritten by these
corrected files, and are explicitly superseded; none is retained or cited as
accepted evidence.

| Proof | Dimensions | Bytes | SHA-256 | Sample sanity |
| --- | ---: | ---: | --- | --- |
| `ARGUS-GUI-COMMAND-CENTER-001-overall-1920x1080.png` | 1920x1080 | 198576 | `A2DC5E30BCE7695823213E5B6049B9FDCDABFEC610A5EC5B3F487B1A1AA753E2` | 32400/32400 nonblack samples; 377 sampled colors |
| `ARGUS-GUI-COMMAND-CENTER-001-compact-1180x820.png` | 1180x820 | 170299 | `0E3AE9CDD3E2F29774F8320765F05F2CDBBC942118176CD273C3374C77E5D051` | 15244/15244 nonblack samples; 373 sampled colors |
| `ARGUS-GUI-COMMAND-CENTER-001-state-loading-1180x820.png` | 1180x820 | 174082 | `8258D1B8656F8F336523F64BC9D5BBB05A208718C841BC56B6D9FD4E999C76C9` | 15244/15244 nonblack samples; 390 sampled colors |
| `ARGUS-GUI-COMMAND-CENTER-001-state-stale-1180x820.png` | 1180x820 | 172217 | `2CB2AB99BC4C1817E151B56A73DC526F3FAC0FC069E17A0D25F9C56181ECED18` | 15244/15244 nonblack samples; 374 sampled colors |
| `ARGUS-GUI-COMMAND-CENTER-001-historical-1180x820.png` | 1180x820 | 179534 | `3D905ED3F5927E7045155967751B7861793CD91411FE4FA30CA603F40F3F7477` | 15244/15244 nonblack samples; 445 sampled colors |
| `ARGUS-GUI-COMMAND-CENTER-001-positions-health-1920x1080.png` | 1920x1080 | 191472 | `2B48B37BA94D588E9E8FFBF1916C8323F5E49821E061BC51A9CED532735B3478` | 32400/32400 nonblack samples; 388 sampled colors |

Original-detail inspection confirms:

- normal and compact frames are nonblank and fill their exact requested client
  dimensions;
- compact `MH | CC`, interval/search, `READ-ONLY RESEARCH`, layout controls,
  `SIMULATION` environment badge, Positions, What Changed, health, Menu, and
  minimize/maximize/close are fully visible;
- selected symbol, company, exact price, and exact change are visible at
  1180x820;
- candidate exact price/change and compact `SEEN` freshness remain visible;
- Decision state pairs are readable and do not overlap or clip;
- chart, latest-bar lineage, decisive answer/reason, What Changed limitation,
  rows, and selected detail remain in-bounds;
- stable history is materially distinct from current state and the current
  answer/TradePlan is explicitly retained;
- Diagnostics and read-only Positions are nonblank and truthfully show
  unavailable position data with no fabricated fallback or order control.

## Physical-Baseline Reconciliation

Final read-only reconciliation at `2026-08-26T21:48:29.4690999-05:00` passed:

- canonical `master` remains clean at
  `82460b3313b86c34dff4ffb737d2c04bf02e3ace`, exactly equal to
  `origin/master`, divergence `0/0`;
- Producer-001C task remains clean at
  `b7f6df51e9f6e08056c58b419c870f116096179c`, exactly equal to its upstream,
  divergence `0/0`;
- Producer-001C product remains clean and detached at
  `4690dbf193355bc7a39c6c74e531344ea8a37875`, tree
  `01248f6a8b21cabf860fef0d52a1f154b15dad3f`;
- heartbeat hash remains
  `BE284EE4270111BF25E6DA92272B0D6C94BCBDD7BF526DC39C0609E3376BBE69`;
  ACTIVE status, 08:28 schedule, target task, required task/product identities,
  and required evidence-root binding all match;
- opening runtime returns `APPROVED_RUNTIME_MATCH`, release fingerprint
  `3947881e4c0c70108b536aad0cb27738b4d89d14a3993ded16c95ddf05ce944e`,
  runtime fingerprint
  `d220aea03f465dea3b6ab970a417e08ec40b4649982d9a356336aafb93c67429`,
  `runtimeMatch=true`, `worktreeClean=true`, transmission `UNAVAILABLE`, and
  `mutationPerformed=false`;
- Automation, Continuous Runtime, and Continuous Writer remain `Running` /
  `Auto`;
- every baseline Automation manifest/service, Continuous config/manifest/host,
  isolated Python/pyvenv, Start Menu, and Startup pointer SHA-256 matches;
- deployed Continuous source remains exactly `416` files with deterministic
  digest
  `C73EFFA113D26CC91970BF8C10A7373882F595D15E15EC32FD7320C9F2D4482E`;
- installed Continuous build identity remains
  `a44e9f35cfdf804efc85bad9459b5102902d695b9d8db179885e65b31450ef45`
  in config and manifest, bound to
  `e69426b3b7bd179cd62eba2e28a5d0553da47154`;
- stable capabilities remain `RESEARCH_ONLY`, execution `NONE`, positions and
  orders not requested, and order/broker/Paper/Live/Shadow capabilities
  `UNAVAILABLE`; runtime remains `IDLE_OUT_OF_SESSION` / `SESSION_CLOSED`.

No provider/account/position/balance query, canary run, evidence-root access,
service/scheduler start/stop/restart, installed-app launch, broker/order action,
Paper/Shadow action, promotion, repin, or installation was performed.

## Limitations And Risks

- Proof uses deterministic presentation fixtures, not provider or account data.
- Missing frozen historical decision values remain explicitly unavailable; the
  UI shows only stable Candidate Story evidence and does not reconstruct a
  historical TradePlan.
- The normal frame deliberately retains compact `MH | CC` branding; whether
  Steven prefers the expanded brand at 1920 is a visual-preference decision,
  not a behavior or clipping failure.
- Automated screenshots cannot validate Steven's font/rendering perception or
  authorize GUI acceptance.

## Required Steven Checks

1. Open the 1920x1080 overall proof. Confirm the four zones are recognizable,
   the chart owns the largest region, Decision answer/reason is prominent, and
   What Changed remains visible at the bottom.
2. Open the 1180x820 compact proof at 100% / original pixels. Confirm
   `READ-ONLY RESEARCH`, Positions, What Changed, `DATA DEGRADED`, Menu, and
   all three caption buttons are fully visible with no horizontal clipping.
3. In the compact proof, confirm NVDA, NVIDIA Corporation, `$176.42`, `+3.2%`,
   each candidate's price/change, and `SEEN 2026-07-13` remain readable; confirm
   the chart and current answer/reason remain usable.
4. Open the loading and stale proofs. Confirm `UNKNOWN / HISTORY LOADING` and
   `RECLAIM READY / QUOTE STALE` read as separate opportunity/evidence states
   and do not overlap or clip.
5. Open the historical proof. Confirm the amber selected timeline row, amber
   historical Decision block, stable identity/source/time, current answer
   strip above it, and `Return to Current` clearly prevent historical evidence
   from masquerading as current truth.
6. Open the Positions/health proof. Confirm Diagnostics is compact and truthful,
   Positions says `POSITIONS — READ-ONLY` and `POSITION DATA UNAVAILABLE`, and
   no fallback position or broker/order control appears.
7. In a task-worktree run, open Menu and confirm Current, Replay, and Review
   remain reachable, while Pause/Resume monitoring, Run Scan, service control,
   simulation, and trading actions remain absent from the Command Center.
8. Report the exact check number and screenshot/app element if any text clips,
   overlaps, looks misleading, or fails to remain visibly read-only.

## Agent Report

- **Branch:** `codex/ARGUS-GUI-COMMAND-CENTER-001` at base
  `82460b3313b86c34dff4ffb737d2c04bf02e3ace`.
- **Scope:** independent QA/Hard Chew of the uncommitted GUI implementation,
  final offscreen visual proof, and physical-boundary equality.
- **Files changed:** six task-local PNG proofs and this QA report. No production
  or test file was edited by QA. The temporary harness is outside the repo.
- **Tests or checks run:** focused/full .NET tests, Release build with warnings
  as errors, XAML/content identity checks, diff/boundary/project/package/secret/
  capability audits, original-detail image inspection, pixel/hash sanity, and
  final physical-baseline equality checks.
- **Evidence for changed behavior:** test results, source/binding review, six
  distinct verified-dimension frames, exact hashes, and physical equality above.
- **Protected areas reviewed:** Contracts, Application, EngineBridge,
  Infrastructure, Python/runtime, service/config/scheduler, provider/account,
  Paper/Shadow, broker/order, canary/evidence, startup pointers; none changed or
  invoked.
- **Push/merge status:** none; no commit, push, merge, install, or branch action.
- **Risks:** Steven visual acceptance remains pending; deterministic proof does
  not claim provider/account/live truth.
- **Manual QA:** required; use the eight numbered checks above.
- **Open questions:** none blocking automated QA. Expanded 1920 branding is a
  Steven visual-preference choice.
- **Recommendation:** treat as `IMPLEMENTED_PENDING_STEVEN_VISUAL_ACCEPTANCE`.
  Do not merge until Steven records the numbered visual result.
