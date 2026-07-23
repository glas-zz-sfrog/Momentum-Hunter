# ARGUS-R012 - WPF Chart Readability

## Result

R012 adds deterministic price and UTC time axes plus a latest-stored-bar OHLCV strip to the existing read-only WPF candle chart. It does not change the Python host payload, fetch market data, write source evidence, or alter planning, risk, simulation, broker, Paper, or Live behavior.

Status: `IMPLEMENTED_PENDING_MERGE` on `codex/ARGUS-R012-wpf-chart-readability`.

## Runtime Changes

- `src/MomentumHunter.Presentation/ChartAxisScale.cs`
  - Builds deterministic nice price bounds and labels from candle lows/highs.
  - Selects chronological time ticks and formats intraday/daily UTC labels.
  - Expands flat-price ranges safely and rejects invalid tick targets.
- `src/MomentumHunter.Presentation/ChartPaneViewModel.cs`
  - Selects the chronologically latest candle.
  - Formats timestamp, open, high, low, close, and volume without inventing unavailable values.
- `src/MomentumHunter.Desktop.Wpf/Controls/CandleChart.cs`
  - Sorts candles chronologically before rendering.
  - Reserves stable right/bottom axis geometry.
  - Renders price/time grid lines, labels, explicit UTC, candles, wicks, and volume.
- `src/MomentumHunter.Desktop.Wpf/MainWindow.xaml`
  - Binds the selected interval into the renderer.
  - Adds a compact latest-bar evidence strip below the plot.

## Tests

- Added `tests-dotnet/MomentumHunter.Presentation.Tests/ChartReadabilityTests.cs`.
- Extended `SimulationWorkspaceShellTests.cs` for latest-bar population and unavailable clearing.
- Focused chart-readability/simulation-shell run: 14 passed.
- Full `MomentumHunter.Workstation.sln` test run:
  - Presentation: 43 passed.
  - Layout: 5 passed.
  - Integration: 40 passed.
  - Total: 88 passed, 0 failed.
- Release solution build: passed with 0 warnings and 0 errors.
- `git diff --check`: passed.

## UI Proof

`docs/argus-office/reports/releases/ARGUS-R012-wpf-chart-readability-cli-proof.png`

- Dimensions: 1904 x 1041.
- Size: 204,552 bytes.
- SHA-256: `BCCC4141782D2F8C010723E7E5A1E912B09FDBA4F89E9706A613628293D6DAB1`.
- Nonblank check: 29,736 of 31,178 sampled pixels exceeded the background threshold.
- Candle-color check: 909 sampled teal/red pixels.
- Visible evidence:
  - CRWV stale stored 5-minute chart.
  - Price labels from 114.00 through 120.00.
  - UTC time labels from 12:05 through 23:55.
  - Candle bodies, wicks, and volume.
  - Latest stored bar timestamp and OHLCV.
  - Stored source/as-of lineage and no-provider-fetch language.
  - `SIMULATION - Python FakeBroker Only`.
  - TradePlan simulation-only status and explicit paper/live lock.

The proof used a temporary offscreen WPF harness outside the repository. It did not move the pointer, type, focus another application, or capture unrelated desktop content. The Python host shut down normally; zero host processes remained.

## Source Integrity

The proof consumed the same read-only source files as R011. Their post-proof hashes still match the recorded R011 baseline:

- `daily-ohlc-bars.json`: `2B1FDC1482D9D98A810D6F06AACDB7E9DE1E6123BE39E5F35634DF34C66BB521`
- `opportunity-minute-bars.json`: `DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69`

## Self-Review

The first pass calculated ticks chronologically but relied on the incoming list order for candle rendering. The narrow fix explicitly sorts renderer candles by timestamp so bars and labels cannot diverge if a collection arrives out of order. Focused and full tests passed after that fix.

## Protected Areas

No scoring, readiness, replay, historical-selection, alert-threshold, schema/migration, package, credential, provider-fetch, broker/order, Paper, Live, or production-configuration path changed. No Python file changed.

## Remaining Risks

- The custom chart still has no crosshair, hover inspection, zoom, or pan.
- Sparse/stale local evidence remains sparse/stale; R012 displays it more clearly but does not acquire new data.
- Very narrow chart panes intentionally show a clear small-pane state instead of overlapping axes and candles.

## Recommendation

Steven reviews the full-workstation proof. If accepted, Git Steward may fast-forward R012 into local `master`; pushing requires separate explicit approval. Keep A017 blocked pending Schwab's official paper-API response.
