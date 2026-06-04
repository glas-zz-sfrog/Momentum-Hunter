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
- Daily morning/evening capture files for point-in-time review
- Structured capture JSON plus a flat analysis CSV for future scoring review
- Market regime label for each capture
- Automatic Windows startup launcher

## Install

Use Python 3.12 on Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```powershell
.\tools\launch_momentum_hunter.ps1
```

The launcher uses `pythonw.exe` when available, so the desktop app opens without a lingering console window. The app starts with the `sample` provider so you can verify the workflow without internet access.

## Data Files

Configuration and watchlists are stored under the project folder:

```text
MomentumHunterData
```

Watchlists are saved as:

```text
MomentumHunterData\data\watchlist-YYYY-MM-DD.json
```

Daily captures are stored as:

```text
MomentumHunterData\data\captures\YYYY-MM-DD\morning.json
MomentumHunterData\data\captures\YYYY-MM-DD\morning.md
MomentumHunterData\data\captures\YYYY-MM-DD\evening.json
MomentumHunterData\data\captures\YYYY-MM-DD\evening.md
```

The analysis table is stored as:

```text
MomentumHunterData\data\analysis-captures.csv
```

Forward outcome tracking is stored as:

```text
MomentumHunterData\data\analysis-outcomes.csv
```

Outcome fields include:

- `next_day_return_pct`
- `five_day_return_pct`
- `max_gain_pct`
- `max_drawdown_pct`
- `outcome_status`

Rows remain `pending_next_day` or `pending_five_day` until enough future daily price bars exist. Scheduled capture jobs run the outcome updater after each successful capture.

The Study Engine includes score-weight recommendations once enough completed 5-day outcomes exist. Recommendations are advisory only; Momentum Hunter does not automatically rewrite `config\scoring_profiles.json`.

## Daily Capture Workflow

1. Run the scanner during the morning or evening review window.
2. Review candidates and check the rows you want to track.
3. Click `Add Selected` to stage the picks.
4. Set or refresh the market regime.
5. Momentum Hunter auto-captures morning and evening snapshots while the app is running.
6. Use the date and session selectors to reopen a past morning or evening capture.

Momentum Hunter installs a Windows startup launcher automatically so the app is available for scheduled captures after login.
The startup launcher is written as `Momentum Hunter.vbs` and launches the GUI hidden through `pythonw.exe`, avoiding a visible command window.

## Scheduled Capture Jobs

Momentum Hunter also includes a headless capture job for Windows Task Scheduler:

```powershell
.\.venv\Scripts\python.exe tools\capture_job.py --session morning
.\.venv\Scripts\python.exe tools\capture_job.py --session evening
```

Install the daily scheduled tasks:

```powershell
.\tools\install_capture_tasks.ps1
```

By default, Windows runs these tasks under the current user. To configure Windows to run them whether the user is logged in or not, run the installer with:

```powershell
.\tools\install_capture_tasks.ps1 -RunWhetherLoggedOn
```

Run that command from an elevated PowerShell window. Windows may ask for your account credentials for that mode. That is a Task Scheduler requirement, not a Momentum Hunter requirement.

Scheduled capture logs are written to:

```text
MomentumHunterData\logs
```

## Data Freshness Safety

Freshness settings live here:

```text
config\ui_freshness_settings.json
```

Current thresholds:

- Fresh current data: `0-10` minutes old
- Aging current data: more than `10` minutes old
- Stale data: more than `20` minutes old

Momentum Hunter uses visible banners, timestamps, age text, read-only state, and table-header styling so current, stale, historical, and study data cannot be quietly confused.

## Scoring Profiles

Regime-aware scoring settings live here:

```text
config\scoring_profiles.json
```

The active profile is currently:

```text
regime-aware-v1
```

This profile preserves the original scoring structure, then applies small market-regime overlays:

- `bull`: slightly increases price-momentum and positive-catalyst points
- `neutral`: uses baseline weights
- `bear`: reduces price-momentum/catalyst points and increases risk-term penalties
- `unknown`: uses baseline weights

Each captured candidate records `score_profile` and `score_regime` for later study.

## Administrator Actions

Normal dashboard use does not require Administrator rights.

Administrator rights are useful for one-time system setup:

- Installing or repairing scheduled capture tasks
- Configuring scheduled tasks to run whether the user is logged in or not
- Running scheduled capture tasks with highest privileges

Rollback scheduled capture tasks:

```powershell
Unregister-ScheduledTask -TaskName "Momentum Hunter Morning Capture" -Confirm:$false
Unregister-ScheduledTask -TaskName "Momentum Hunter Evening Capture" -Confirm:$false
```

Rollback Windows startup launcher:

```powershell
Remove-Item "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Momentum Hunter.vbs"
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
