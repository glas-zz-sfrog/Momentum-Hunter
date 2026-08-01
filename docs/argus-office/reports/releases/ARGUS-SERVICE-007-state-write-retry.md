# ARGUS-SERVICE-007 State Write Retry

## Classification

`COMPLETE_AND_BACKED_UP`

## Defect

At 2026-08-01 02:10 Central, a concurrent read of the unattended automation
state receipt caused Windows to reject the supervisor's atomic replace with
access denied. The Python supervisor exited and the Windows service wrapper
restarted it five seconds later. Monday's receipt remained pending, but the
same race during a consequential window could interrupt scheduling or evidence
finalization.

## Repair

`SupervisorStateStore.save` retains temporary-file plus atomic-replace
semantics. It now retries only `PermissionError`, Windows access denied (`5`),
and sharing violation (`32`) for 20 attempts with 50 milliseconds between
attempts. A persistent lock or unrelated filesystem failure still raises. The
previous destination remains intact and the temporary file is removed.

## Proof

- Python compileall: pass.
- Focused supervisor tests: 26 / 26.
- Affected automation and capture tests: 74 / 74.
- Full Python discovery: 1,019 / 1,019 in 224.887 seconds.
- Real Windows no-delete-share lock: recovered in 0.265 seconds with the new
  state readable and zero temporary files left behind.
- `git diff --check`: pass.

## Protected Behavior

No job schedule, retry policy, capture result, provider request, scoring,
readiness, replay, alert, database/schema, UI, Shadow state, brokerage account,
order, credential, or transmission behavior changes. The Monday manifest is
not changed by this patch.

## Installed Proof

Commit `252cdc7` fast-forwarded into canonical `master` and was pushed normally.
A controlled service restart at 02:30 Central loaded the repaired source while
the installed manifest SHA-256 remained
`636274F988D89BD19AF7BB84201D64DBC175E647AF670041CFD8A2B81D388638`.
Twelve deliberate no-delete-share locks against the live state receipt caused
no wrapper restart, no supervisor restart, and no new Application error. The
service remained Running/Automatic with a fresh heartbeat and Healthy Engine
Host. All 30 opening jobs remain pending through 2026-09-14, Monday 08:35 is
still `PENDING`, zero Shadow jobs are enabled, and transmission is
`UNAVAILABLE`.

The final Friday readiness sweep also passed canonical Git synchronization,
Finviz scanning, Yahoo SPY history, same-response HTTPS clock proof, NIST
Windows Time, Central timezone, AC power settings, disk health, reboot-pending
inspection, service-account lifetime, and three-level Windows service recovery.
Monday is a normal XNYS session. Residual external risks remain power loss,
full shutdown, internet/provider outage, or a new OS/hardware failure after the
Sunday preflight.
