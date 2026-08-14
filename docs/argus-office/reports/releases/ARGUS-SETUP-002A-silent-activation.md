# ARGUS-SETUP-002A Silent Activation

## Classification

`IMPLEMENTED_AND_ACTIVATED_FOR_FIRST_PROSPECTIVE_SESSION`

## Scope

SETUP-002A activates the already-proven successor-setup observer as an
isolated, silent research lane. It does not change candidate admission,
ranking, scoring, TradePlan, Risk Governor, allocation, Paper selection,
broker behavior, Shadow state, or UI behavior.

## Activation Contract

- The sample charter and a separate immutable activation record share the
  frozen SETUP-002 policy and charter fingerprints.
- The activation record stores the real activation timestamp, first eligible
  session, exact Git identity, empty initial counts, and no execution authority.
- Pass 1 depends on the same-date opening capture, runs before Paper, and uses
  the deterministic 09:35 ET cutoff.
- Pass 2 depends on the exact same-session Pass 1 packet and runs after the
  regular-session outcome horizon.
- Outputs are write-once under
  `MomentumHunterData/data/research/successor-setup-research-20260813-v1/`.
- Both jobs have finite windows, finite timeouts, zero retries, and exact-head
  validation.
- Research failure is isolated from opening and Paper receipts.

## Safety Evidence

- The observer command has no provider, account, position, broker, order,
  service-control, Engine Host, Shadow, or UI capability.
- The installer preserves existing jobs, requires a clean exact-head canonical
  checkout, refuses any running automation job or enabled Shadow job, and
  validates the complete candidate manifest before installation.
- The installer backs up the prior manifest and restores it automatically if
  both research jobs do not hot-reload as `PENDING`.
- Future opening repins update both successor research jobs to the same exact
  canonical identity, preventing stale-head execution after later governance
  commits.

## Verification

- Python compileall: pass.
- Focused activation/observer/supervisor/opening-repin tests: 85 pass.
- Full Python discovery before the final repin guard: 2,012 pass.
- Final full Python discovery: 2,013 pass in 265.954 seconds.
- PowerShell parser: pass.
- Plan-only Aug. 17 installation: pass with explicit Central offsets.
- `git diff --check`: pass.
- Secret and capability scans: pass.
- WPF/.NET tests: not required; no WPF or .NET file changed.

## Operational Result

The first prospective session is August 17, 2026. The service manifest keeps
the opening and Canary Paper lanes intact and adds only:

- `successor-setup-pass1-20260817`
- `successor-setup-pass2-20260817`

The sample begins at zero sessions and zero candidates. No retrospective
candidate or outcome is added, and no research result counts as an official
Paper trade.
