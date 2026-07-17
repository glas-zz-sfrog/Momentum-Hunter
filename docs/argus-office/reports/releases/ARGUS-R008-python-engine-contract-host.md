# ARGUS-R008: Python Engine Contract Host

## Classification

`READY_WITH_DOCUMENTED_CAUTIONS` on `codex/ARGUS-R008-python-engine-contract-host`; it is pushed for backup and awaits Steven's explicit fast-forward merge decision.

## Goal Charter Result

The Phase 8 Goal Charter is complete: the visible WPF workstation no longer owns collection lifecycle. A separate local Python Engine Host exposes only versioned host identity, health, collection state, pause, resume, one-cycle, and deliberate shutdown behavior.

## What Was Built

- `momentum_hunter/engine_host.py`: an independently hosted Python process using authenticated loopback TCP (`127.0.0.1` only), a random per-host transport token, atomic host lease, host identity, health, collection snapshots, capabilities, structured errors, and command IDs.
- A host-owned scheduled collection loop around the existing canonical active-monitor cycle with provider-fetch flags left at their defaults of false.
- Guards for one host lease, one in-flight collection cycle, idempotent duplicate command IDs, and an existing active-monitor runner that would otherwise create a second collection loop.
- Provider-neutral .NET contracts and `PythonEngineHostConnection` for WPF-side discover, attach, launch-if-missing, and reconnect behavior.
- `RemoteBackgroundCollectionService`, wired into the existing WPF application lifecycle. Normal close-to-tray leaves the host running; explicit Exit sends graceful host shutdown.

## Deliberately Not Built

- No candidates, research, evidence summaries, Replay, TradePlan, readiness, Risk Governor, simulation, broker, Paper, or Live command crosses this boundary.
- `MockEngineClient` remains the WPF data seam until Phase 9.
- No credentials, API keys, provider fetching, schema changes, generated reports, or raw-capture mutation was added.

## Evidence

- Fresh `dotnet restore MomentumHunter.Workstation.sln --force` completed.
- Release build completed with `0` warnings and `0` errors.
- Full .NET suite passed: `60/60` (37 integration, 18 presentation, 5 layout).
- Python compileall passed for `momentum_hunter` and `tests`.
- Focused Python regression set passed: `36/36` across host, active monitor, active-monitor runner, and daily workflow tests.
- The all-Python discovery command was bounded by the available 30-second command window and was inconclusive before it emitted its summary; it is not counted as passing evidence.

## Failure And Runtime Proof

- Python tests cover bad token, protocol mismatch, unsupported capabilities, duplicate command IDs, overlapping cycles, paused collection, collection failure, legacy-runner conflict, lease cleanup, and no mutation of canonical monitor source.
- A real Python subprocess test proves a separate client can exit while the host remains alive and accepts a reconnect using the same host ID; deliberate shutdown removes both endpoint and lease files.
- A real .NET-to-Python integration test concurrently launches/attaches two WPF-side connections, proves one host identity, repeats an idempotent pause command, resumes, and deliberately shuts the host down with cleanup.
- A clean-room clone from the pushed feature branch, with no copied `.venv` or runtime-state artifacts, completed fresh restore/build, `59/59` .NET tests, Python compileall, and `12/12` host tests before the final unavailable-host negative test was added.
- No operator layout or visible control text changed in Phase 8. Existing tray and application-menu controls now call the host bridge. The available automation surface could not capture a WPF desktop screenshot, so the lifecycle UI behavior is proven by the WPF adapter integration test rather than a new image artifact.

## Protected-Path Review

Reviewed the final diff for scoring, readiness, Replay identity, historical capture selection, database/schema, alert threshold, broker/order, credentials/environment, and generated-data paths.

Only host/lifecycle contracts, the WPF lifecycle registration, focused tests, and governance/release artifacts changed. No protected domain implementation changed.

## Cautions

- The current WPF host launcher is source-checkout oriented: it prefers the repository `.venv` interpreter and otherwise uses the Windows Python launcher. Packaging/distribution of the Python engine is a later deployment task, not a Phase 8 broker or domain concern.
- The legacy duplicate-loop guard recognizes the existing `active_monitor_runner` state file. An independently started, unmanaged CLI monitor process cannot be conclusively identified without broadening legacy monitor ownership, so Phase 9 work must preserve this caution.

## Next Action

Steven should review and decide whether to fast-forward the pushed Phase 8 branch into `master`. After integration, the next authorized work is Phase 9 read-only discovery, research, health, and Replay snapshots over this boundary.
