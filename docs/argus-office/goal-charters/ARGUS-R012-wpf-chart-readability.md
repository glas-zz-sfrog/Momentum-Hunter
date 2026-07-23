# ARGUS-R012 Goal Charter - WPF Chart Readability

## Goal

Make the existing read-only WPF candle chart operationally readable by adding deterministic price and UTC time axes plus details for the latest stored OHLCV bar.

## Scope

- Add a presentation-layer axis model derived only from the validated candle collection.
- Render stable price ticks, UTC time ticks, grid lines, and reserved axis margins in the existing WPF chart control.
- Show the chronologically latest stored bar's timestamp, open, high, low, close, and volume.
- Preserve explicit stale, insufficient, and unavailable states.
- Add focused tests and an offscreen full-workstation screenshot proof.

## Non-Goals

- No provider fetch, background collection, source-data write, or new chart contract.
- No crosshair, zoom, pan, technical indicator, drawing tool, or order overlay.
- No scoring, readiness, replay, trade-planning, risk, simulation, broker, Paper, or Live behavior change.
- No credential, API key, package, schema, migration, or production-configuration change.

## Acceptance Evidence

- [x] Price ticks use deterministic nice bounds that contain all candle highs and lows.
- [x] Time ticks use chronological candle positions and explicit UTC labeling.
- [x] Flat-price and zero-volume series render safely.
- [x] Latest-bar details use the chronologically newest candle and clear when data is unavailable.
- [x] Focused chart-readability and simulation-shell tests pass.
- [x] The full .NET solution passes.
- [x] Release compilation passes with zero warnings.
- [x] Offscreen WPF proof shows readable axes, candles, volume, latest-bar details, source lineage, simulation-only language, and paper/live locks.
- [x] Stored source hashes remain identical to the R011 baseline.
- [x] Protected-path review finds no protected behavior changes.
- [x] Work remains branch-only until Steven approves a local merge.
