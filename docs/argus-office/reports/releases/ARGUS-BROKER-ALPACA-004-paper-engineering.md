# ARGUS-BROKER-ALPACA-004 - Paper Engineering Wiring

## Result

The canary-realistic Paper lane now has a complete prospective engineering
chain from trusted Momentum Hunter evidence through Paper execution and
terminal evidence. It uses the accepted A003 capability proof and DATA-005B
fractional allocation without making Alpaca a strategy market-data source.

## Runtime Behavior

- Canonical rank order is preserved and each candidate independently passes
  evidence, DATA-004 TradePlan, Paper Risk, and allocation gates.
- One fresh Alpaca account/position/order snapshot is frozen per cycle.
- A write-once intent precedes the idempotent fractional Paper market entry.
- A filled position receives a standalone fractional day stop using only the
  directly proven capability set.
- Target or forced-flat reconciliation cancels the stop before an idempotent
  exact-quantity market exit.
- Missing protection triggers emergency flattening; partial flattening cannot
  be reported as flat.
- Restart recovery can recover an accepted entry and install/recover its stop,
  but cannot submit a late new entry.
- One global Windows mutex prevents concurrent lifecycle managers.

## Automation

The service supports one `paper_engineering` job bound to the same-date opening
capture and exact Git head. It refreshes time after capture, admits work only
through 08:50 Central, supervises for at most 25,200 seconds, and may relaunch
only the idempotent Paper recovery path after interruption. A deterministic
installer refuses manifest mutation while another automation job is running.

## Verification

- `python -B -m compileall -q momentum_hunter tests`: PASS.
- Broker/allocation/automation adjacent suite: 188/188 PASS.
- Final focused automation/Paper suite: 75/75 PASS.
- Full Python discovery: 1,459/1,459 PASS.
- `git diff --check`: PASS.
- Provider calls and Paper orders during implementation: zero.

## Remaining Activation Work

Integrate and back up the branch, refresh the installed service, freeze the
versioned engineering sample, install the next same-head Paper job, and preserve
the first prospective provider result. This release does not authorize or make
reachable an Alpaca live order.
