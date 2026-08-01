# ARGUS-SERVICE-007 State Write Retry

## Classification

`IMPLEMENTED_PENDING_INTEGRATION`

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

## Remaining Gate

Commit and fast-forward integration must pass, then the installed service must
be restarted once so its Python supervisor loads the repaired source. Final
proof requires a fresh stable heartbeat, Monday still `PENDING`, all 30 opening
jobs retained, zero Shadow jobs, and transmission `UNAVAILABLE`.
