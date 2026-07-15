# ARGUS-R005 - Background Collection Lifecycle And Windows System Tray

## 1. Executive Summary

R005 adds an in-process background collection lifecycle to the WPF workstation. Normal window close saves workstation presentation state, hides the taskbar surface, and leaves deterministic monitoring active in the system tray. Pause, resume, scan, status, restore, explicit exit, session ending, and single-instance activation are separated from the visible window. This does not create an independent Python engine host.

## 2. Selected Git Base

The R005 branch was created from `d3a98d9 Integrate authoritative roadmap with R004 workstation shell`. The preserved ancestors are `48d3ab4` for the authoritative Roadmap and `5bbd0c7` for R004.

## 3. Branch And Commit Information

- Branch: `codex/ARGUS-R005-background-tray-lifecycle`
- Head at report time: `89acdee Harden tray command surface`
- R005 commits: `9276c90`, `baa67e8`, `eb46a7a`, `3d98654`, and `89acdee`
- Remote backup: pushed to `origin/codex/ARGUS-R005-background-tray-lifecycle`
- Local master: unchanged. No master push, merge, rebase, or PR occurred.

## 4. Roadmap Changes

`9276c90` updated `docs/argus-office/ROADMAP.md` before implementation. It establishes that the visible workstation is an operator surface, while background collection has an explicit lifecycle. The Roadmap keeps R005 `ACTIVE` pending Steven's review and keeps Phase 8 responsible for an independent Python host and reconnect behavior.

## 5. Architecture Changes

- `IApplicationLifetimeCoordinator` owns close-to-tray and explicit-exit coordination.
- `IBackgroundCollectionService` provides deterministic in-process monitoring with normalized status.
- `ITrayService` isolates the Windows `NotifyIcon` adapter from application logic.
- `ISingleInstanceCoordinator` uses a named local mutex and activation event.
- `ITraySettingsStore` persists only close-to-tray and notification preferences separately from layout state.
- `INotificationService` provides the quiet first-close notification seam.

## 6. Close-To-Tray Behavior

`MainWindow.Closing` cancels ordinary destruction, requests `SavePresentationStateAsync`, then hides the window through `IWorkstationPresentation.HideWorkstation`. The presentation implementation sets `ShowInTaskbar` to false before `Hide()`. Alt+F4 follows the same WPF closing path. The application uses `ShutdownMode.OnExplicitShutdown`.

## 7. Background Collection Behavior

`DeterministicBackgroundCollectionService` starts in-process monitoring from the application host, not from `MainWindow`. It reports Starting, Healthy, Degraded, Paused, Blocked, and Stopping states; tracks completed-cycle count and timestamp; prevents overlapping scans; and rejects new scans while paused or stopping. A blocked monitor remains blocked until a retry succeeds; it is not silently relabeled as paused.

## 8. Pause/Resume Behavior

The tray and application menu use the same lifetime coordinator. Pausing prevents new collection cycles. Resuming restores Healthy monitoring without starting a second loop. Run Scan Now is disabled while paused or stopping and can explicitly retry a blocked deterministic monitor. The view model displays the current normalized status and the appropriate Pause or Resume label.

## 9. Single-Instance Behavior

The first process owns `Local\\MomentumHunter.Workstation.Instance` and listens for `Local\\MomentumHunter.Workstation.Activate`. A second process signals the existing process, exits before service construction, and therefore cannot create a second tray icon, timer, layout store, or collection loop. The primary marshals activation onto the WPF dispatcher and restores the existing workstation.

## 10. Explicit Exit Behavior

Both the tray and the main menu use the same WPF confirmation surface: `Exit Momentum Hunter and stop background collection?`, with `Cancel` and `Exit and Stop Collection`. Confirmed exit saves presentation state and tray settings, stops monitoring, disposes the tray icon, permits WPF shutdown, and terminates the application process. Session ending bypasses this normal confirmation and uses the explicit shutdown path immediately.

## 11. Session-Ending Behavior

`App.SessionEnding` calls `RequestExplicitExitAsync` with `isSessionEnding: true`, permits application shutdown, flushes layout/settings through the coordinator, stops background collection, and disposes the tray. It does not attempt to hide the workstation back to the tray or block Windows shutdown with the normal confirmation.

## 12. Build And Test Results

CLI verification completed on the R005 worktree:

```powershell
dotnet build MomentumHunter.Workstation.sln -c Release
dotnet test MomentumHunter.Workstation.sln -c Release --no-restore
C:\Users\steve\OneDrive\Documents\Investing\.venv\Scripts\python.exe -B -m compileall -q momentum_hunter tests
```

- Release build: passed, 0 warnings, 0 errors.
- .NET tests: passed, 55 total: 33 integration, 17 presentation, and 5 layout.
- Python compile: passed.

Focused lifecycle tests cover save-before-hide, background continuity, first-close dismissal, pause/resume, non-overlap, blocked/recovery state, explicit exit, session ending, tray status, restore, single-instance signaling, settings round trip, compact tooltip text, and the restricted tray command surface.

## 13. Hard Chew Evidence

- Compile/build pass: complete.
- Focused and broader bounded tests: complete.
- Protected-path diff review: complete; no scoring, readiness, replay, broker/order, schema, alert, secrets, or provider paths changed.
- Second-pass review found and fixed mutex ownership across asynchronous shutdown, dispatcher marshaling for tray callbacks, blocked-state handling, precise exit wording, and an explicit restricted tray command definition.
- Final CLI verification: complete after the narrow fixes.

## 14. UI Proof

This run used CLI verification by Steven's instruction. No screenshot or interactive computer-control artifact was created, and this report does not claim pixel-level inspection of the Windows notification area.

Equivalent CLI evidence proves the lifecycle contracts and menu surface: `NotifyIconTrayService` is the sole tray adapter; `TrayMenuDefinition` has only Open Workstation, Pause/Resume Monitoring, Run Scan Now, View System Status, and Exit Momentum Hunter; the test suite asserts Paper, Live, broker, and risk commands are absent. The adapter truncates tooltip text to the Windows-safe 63-character limit and uses the WPF dispatcher for all tray operations.

Visual-only checks still appropriate for Steven before integration are one physical tray-icon inspection, menu rendering, first-close notice appearance, restored floating Chart B, and font/icon appearance. They are intentionally not represented as completed here.

## 15. Known Limitations

- Background collection exists only while the WPF application process remains alive.
- This is deterministic in-process monitoring, not a Python engine host.
- Closing to the tray is proven through lifecycle tests; a physical Windows notification-area screenshot is not included in this CLI-only run.
- No paper broker, live broker, credentials, provider calls, order routing, or execution authorization was added.

## 16. Phase 8 Handoff Requirements

Phase 8 must introduce a separately hosted Python engine with versioned local contracts. It must prove that WPF can disconnect, restart, and reconnect without ending monitoring; that an engine survives workstation exit or failure; that engine health and pause/resume are queryable and auditable; and that duplicate engine hosts and collection loops are prevented.

## Direct Answers

- R005 base commit: `d3a98d9`.
- Does closing the window keep collection active: yes, while the WPF application process remains alive.
- Does explicit Exit stop collection: yes.
- Does reopening restore the previous workspace: yes, through the existing R004 layout/presentation restoration path.
- Does Chart B restore: yes, through the preserved R004 layout path; physical rendering remains a visual-only check.
- Can a second launch create duplicate monitoring: no; it signals the primary before services are built.
- Can tray or layout state authorize Paper or Live: no; tray settings contain only lifecycle/notification preferences and the command surface has no Paper or Live action.
- Is the Python engine independently hosted yet: no; that is Phase 8.

## Classification

`READY_WITH_DOCUMENTED_CAUTIONS`

The implementation, tests, branch safety, and CLI verification are complete. The sole caution is intentionally deferred visual-only notification-area and pixel rendering inspection after Steven requested CLI-only verification.
