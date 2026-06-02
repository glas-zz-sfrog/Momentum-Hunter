# Momentum Hunter

Momentum Hunter is a Windows-first Python desktop research assistant for finding momentum stocks for swing trading and short-term watchlists.

It is not an automated trading bot. It does not place orders. The human trader makes the final decision.

## Current Version

Version 0.1 implements the V1/V3 foundation:

- PySide6 desktop GUI
- PAPER/LIVE mode switch with no trading execution
- Base Momentum and Institutional Momentum scanner presets
- Swappable data-provider architecture
- Sample provider for offline use
- Finviz provider scaffold for screener/news parsing
- Candidate table with ticker, price, change, volume, relative volume, market cap, sector, and industry
- News and catalyst panel
- Deterministic scoring engine
- Candidate notes
- Save selected candidates to a next-session watchlist JSON file
- All displayed times use Central Time

## Install

Use Python 3.12 on Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```powershell
python run.py
```

The app starts with the `sample` provider so you can verify the workflow without internet access.

## Data Files

Configuration and watchlists are stored under:

```text
%USERPROFILE%\MomentumHunter
```

Watchlists are saved as:

```text
%USERPROFILE%\MomentumHunter\data\watchlist-YYYY-MM-DD.json
```

## Scanner Presets

Base Momentum:

- Volume: 1,000,000
- Percent Change: 5%
- Market Cap: $1B
- Price: $5
- Relative Volume: 150%

Institutional Momentum:

- Volume: 3,000,000
- Percent Change: 3%
- Market Cap: $5B
- Price: $10
- Relative Volume: 120%

## Trading Safety

Momentum Hunter is a research tool only.

- No automatic trading
- No order placement
- No broker credentials
- No destructive actions
- One active mode at a time
- LIVE mode is reserved for future broker-connected research workflows

## Roadmap

Planned V2 fields:

- Float
- Short Float
- Short Interest
- Premarket Volume
- Gap %
- Earnings Date
- ATR
- Relative Strength

Planned future integrations:

- Yahoo Finance
- Schwab
- Thinkorswim
- Analyst action feeds
- Earnings providers
