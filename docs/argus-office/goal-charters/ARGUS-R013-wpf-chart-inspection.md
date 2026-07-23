# ARGUS-R013 Goal Charter - WPF Chart Inspection

## Goal

Let Steven inspect any existing stored chart candle precisely by hovering the WPF chart, without changing data acquisition, analysis, planning, or execution behavior.

## Scope

- Select the nearest chronologically ordered candle from pointer position.
- Render a restrained vertical/horizontal crosshair at the selected candle and its close.
- Replace the latest-bar strip temporarily with the inspected candle's UTC timestamp and OHLCV facts.
- Restore latest-bar details when inspection ends.
- Clear inspection when the pointer leaves, candles change, or a new snapshot/context is applied.
- Give primary and dynamically created secondary/floating chart panes the same behavior.
- Add focused pure-behavior tests and offscreen WPF render proof.

## Non-Goals

- No provider fetch, background collection, source-data write, Python contract, or engine-host change.
- No chart zoom, pan, indicator, drawing tool, alert, trade-plan, risk, simulation, broker, order, Paper, or Live overlay.
- No scoring, readiness, replay identity, historical capture selection, or outcome-classification change.
- No credential, API key, package, schema, migration, or production-configuration change.

## Acceptance Evidence

- [x] Nearest-candle selection is deterministic for unordered input and first, middle, last, and exact-edge positions.
- [x] Empty, out-of-plot, NaN, and infinite positions do not produce an inspection.
- [x] Inspected-bar UTC/OHLCV details replace latest-bar details only while inspection is active.
- [x] Clearing inspection restores the latest-bar facts.
- [x] Snapshot replacement and collection mutation clear stale inspection state.
- [x] Primary and secondary/floating chart panes bind candle inspection, interval, and detail state.
- [x] Focused chart inspection tests pass 17/17.
- [x] The full .NET solution passes 97/97.
- [x] Release compilation passes with zero warnings and zero errors.
- [x] Offscreen WPF proof is nonblank and shows candles, wicks, volume, crosshair, selected UTC/OHLCV, research-only language, and Paper/Live locks.
- [x] Protected-path review finds no protected behavior changes.
- [x] Work remains branch-only until Steven separately approves a local merge.
