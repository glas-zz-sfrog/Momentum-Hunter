# ARGUS-DATA-005A Fresh Account And Portfolio Snapshot

Status: `COMPLETE` on canonical `master` through `dff993c`

## Result

DATA-005 now has a bounded source for fresh allocation evidence. It revalidates
the immutable Schwab binding, reads balances and positions from the exact bound
account, derives current portfolio commitments from Official Shadow evidence,
and returns a redacted `AccountAllocationContext`.

The source is intentionally not connected to selection or execution. No
numeric policy has been chosen, so allocation remains blocked.

## Read Contract

- Exact host: `api.schwabapi.com`.
- Method: `GET` only.
- Resource: one URL-encoded bound account identity.
- Query: `fields=positions`.
- Redirects: rejected.
- Response size: bounded to 512 KiB.
- Identity: exactly one account ending `2573`, type `INDIVIDUAL_CASH`.
- Clocks: provider HTTP date and local receipt time are preserved separately.
- Transport and parsing errors are redacted and fail closed.

## Portfolio Contract

- Reads Official Shadow state without mutation.
- Counts filled positions plus remaining working-order commitments.
- Uses the frozen DATA-005 allocation decision to derive open risk.
- Rejects missing, unauthorized, malformed, or fingerprint-mismatched
  allocation evidence.
- Uses the Central trading date for realized daily P&L.
- Does not combine an unexpected real brokerage position with Shadow state;
  that condition is a brokerage anomaly requiring Steven's attention.

## Live Proof

A nonpersisting, read-only proof observed:

- one expected `INDIVIDUAL_CASH` account ending `2573`;
- zero brokerage positions;
- zero active Shadow positions or commitments;
- valid provider/receipt chronology with 0.917 seconds between clocks; and
- order transmission `UNAVAILABLE`.

The proof did not retain the full account number, encrypted account hash,
balance values, OAuth token, client secret, or credentials.

## Verification

- Python compileall: pass.
- Focused and runtime-identity tests: 73/73 pass.
- Adjacent account, Schwab, simulation, Shadow, and selection tests: 210/210
  pass in 75.408 seconds.
- Full Python discovery: 1,314/1,314 pass in 265.161 seconds.
- Exact environment-only rerun: the two tests that require a worktree `.venv`
  pass after an ignored junction to the canonical dependency environment.
- Source-file nonmutation and deterministic repeated-allocation tests: pass.

## Safety Boundaries

- No UI, service manifest, scheduler, Engine Host command, selector, simulation,
  Shadow default, score, rank, alert, RVOL, TradePlan timing, database, package,
  credential, raw capture, generated report, or historical evidence changed.
- No submit, cancel, replace, order-status, or order-list method was added.
- The runtime hash includes this source so a stale Engine Host cannot claim the
  current allocation boundary.
- The installed service was refreshed under UAC after release. One
  authenticated current-build Engine Host owns the matching endpoint, lock,
  process, and listener; it is Healthy and idle. Opening capture remains
  independent of Engine Host availability.

## Remaining Gate

Steven must explicitly choose fixed unit risk, maximum position notional,
minimum cash reserve, maximum total open risk, daily-loss limit, maximum open
positions, and maximum account-evidence age before activation. No default is
implied by this release.
