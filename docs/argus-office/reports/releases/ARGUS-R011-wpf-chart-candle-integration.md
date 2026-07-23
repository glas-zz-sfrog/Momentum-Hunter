# ARGUS-R011 - WPF Chart Candle Integration

## Verdict

`IMPLEMENTED_PENDING_MERGE` on `codex/ARGUS-R011-wpf-chart-candle-integration`.

R011 connects the WPF Chart pane to stored Python OHLC evidence through a versioned, read-only host command. It does not fetch providers, create fallback candles, mutate source files, or change scoring, readiness, replay, planning, risk, simulation, broker, Paper, or Live behavior.

## Implemented Path

- `momentum_hunter/workstation_charts.py` maps valid stored daily bars and stored minute bars into versioned snapshots.
- `momentum_hunter/engine_host.py` exposes validated `get_chart_snapshot` requests without starting a collection cycle.
- The C# contract, connection, and mapper validate schema version, OHLCV geometry, symbol identity, and interval identity.
- WPF refreshes primary, linked, and pinned chart contexts and uses the existing `CandleChart` control for bodies, wicks, and volume.
- Missing and malformed sources are explicit; stale bars remain visible with source and as-of evidence.

## Real Local Evidence

| Request | State | Candle count | As of |
| --- | --- | ---: | --- |
| CRWV `5m` | `STALE` | 143 | `2026-06-18T23:55:00Z` |
| CRWV `Daily` | `STALE` | 180 | `2026-07-02T00:00:00Z` |
| EQX `5m` | `UNAVAILABLE` | 0 | No stored intraday bars |
| EQX `Daily` | `STALE` | 180 | `2026-07-02T00:00:00Z` |

No cross-timeframe or simulated fallback was created.

## Automated Evidence

- Python compile: `python -B -m compileall -q momentum_hunter tests` - PASS.
- Release solution build: PASS with 0 warnings and 0 errors.
- Focused Python chart/host tests: 25 passed.
- Nearby Python read-model/simulation/OHLC/outcome tests: 29 passed.
- Protected scoring/readiness/replay/trade-planning regression set: 84 passed.
- Full .NET solution: 80 passed across layout, presentation, and live Python-host integration.
- Repository-wide Python discovery was bounded at 120 seconds and timed out. Its two launcher/runtime processes were identified and terminated; no discovery process remained.
- `git diff --check` passed.

## Source Integrity

The real source hashes were identical before and after service reads and both WPF proof runs:

- `daily-ohlc-bars.json`: `2B1FDC1482D9D98A810D6F06AACDB7E9DE1E6123BE39E5F35634DF34C66BB521`
- `opportunity-minute-bars.json`: `DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69`

## UI Proof

### Full Workstation

`ARGUS-R011-wpf-chart-candle-interface-cli-proof.png`

- Dimensions: 1904 x 1041.
- Size: 194,323 bytes.
- Nonblank sampled-pixel check: PASS; 1,998 sampled teal/red pixels.
- Generated from an off-screen real WPF window using the real Python host, so no desktop focus or input control was taken.
- Visible: CRWV, `STALE | 143 stored 5m candle(s)`, source/as-of evidence, candle bodies, wicks, volume, `SIMULATION - Python FakeBroker Only`, TradePlan/Risk Governor evidence, and paper/live locked language.

### Renderer Isolation

`ARGUS-R011-wpf-chart-candle-renderer-proof.png`

- Dimensions: 1200 x 650.
- Size: 25,673 bytes.
- Nonblank pixel check: PASS; 23,971 teal/red pixels.
- Visible: all 143 real CRWV five-minute candle bodies, wicks, grid lines, and volume bars.

## Hard Chew Fix Pass

Second-pass review found and fixed:

- Snapshot identity mismatch could have rendered candles under the wrong symbol or interval.
- A single old candle could have been labeled stale instead of insufficient.
- A long source-lineage label could crowd Link/Pin controls.
- A pinned chart needed explicit proof that both symbol and interval remain unchanged.
- Zero-volume-only input needed a safe renderer denominator.

Affected tests and the full .NET suite passed after the fixes.

## Protected Areas

No scoring, readiness, replay, historical-selection, schema/migration, alert-threshold, credential, provider-fetch, broker/order, Paper, Live, or production-configuration path changed. The host proof process was shut down gracefully and its endpoint/lock artifacts were removed.

## Remaining Risks

- Local evidence is stale and intraday coverage is sparse; the UI now says so but R011 does not solve data acquisition.
- The custom chart remains intentionally basic: no price/time axes, crosshair, zoom, or pan.
- Full Python discovery still exceeds the 120-second bound; focused and protected regression partitions passed.
- R011 is not on local `master` or any remote until Steven separately approves merge or push.

## Recommendation

Review the full-workstation proof, then fast-forward R011 into local `master` if accepted. Keep A017 blocked pending Schwab's official response. The next bounded WPF slice should add deterministic price/time axes and latest-bar details without expanding into provider, broker, or execution behavior.
