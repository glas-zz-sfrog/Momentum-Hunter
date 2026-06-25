# Provider Data Quality Audit

The data-quality audit is a read-only diagnostic layer for market tape and scanner field reliability.

Run:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.data_quality
```

Optional symbol list:

```powershell
.\.venv\Scripts\python.exe -m momentum_hunter.data_quality CRWV SOFI HOOD MDT SSRM
```

Outputs:

- `MomentumHunterData/data/reports/data-quality-latest.json`
- `MomentumHunterData/data/reports/data-quality-latest.md`

The report checks:

- provider availability and quote success/failure
- usable market tape by symbol
- last price, bid, ask, spread, volume/RVOL, and average-volume fields when available
- quote timestamp availability and stale timestamp status when timestamps are available
- missing or impossible market-data values
- scanner field reliability, including missing or zero relative volume
- duplicate tickers inside a capture
- repeated identical candidate rows across captures
- minute-bar coverage for monitored symbols

Current limitation: Momentum Hunter's shared `MarketTape` object does not yet normalize provider quote timestamps, so the audit reports quote timestamp quality as unknown instead of assuming quotes are fresh.

This report is evidence plumbing. It does not change scanner results, scoring, readiness, alerts, or trade planning.
