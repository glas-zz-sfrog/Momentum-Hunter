# AUTOMATION-RUNTIME-IDENTITY-001 Branch Qualification

## Identity

- Canonical protected baseline:
  `f2c2b65d3741d7658947aec7493b08ad5096336d`.
- Feature branch: `codex/ARGUS-AUTOMATION-RUNTIME-IDENTITY-001`.
- Architecture: Model B, current clean canonical checkout plus approved runtime
  surface, nonsecret configuration, complete installed-distribution set, and
  loaded-process identity.
- ADR:
  `docs/argus-office/architecture/OPENING_RUNTIME_IDENTITY_ADR_V1.md`.
- Classification: `IMPLEMENTED_PENDING_PRODUCTION_PROOF`.

## Runtime Contract

`OpeningRuntimeSurfaceV1` automatically includes every Python file below
`momentum_hunter/`, the opening orchestrator, PowerShell launcher, and
`requirements.txt`. It binds every add, remove, rename, or byte change. The
environment identity binds interpreter and launcher bytes/versions, the
installed Automation Service executable, every installed Python distribution,
platform, and timezone. Nonsecret runtime configuration is classified and
fingerprinted; unknown configuration fields fail closed. Credentials, OAuth
state, account values, and other secrets are excluded.

`OpeningRuntimeReleaseV1` is immutable and hash-addressed.
`OpeningRuntimePromotionV1` receipts form a filename-, predecessor-, release-,
and fingerprint-bound chain. `OpeningRuntimeChannelV1` is updated atomically.
Promotion requires explicit confirmation, a clean synchronized canonical
checkout, qualification evidence, fresh supervisor heartbeat, and matching
loaded supervisor, identity-gate, and service-host bytes.

Future channel-based openings evaluate the complete contract before the
runner/provider boundary. Legacy exact-Git jobs and receipts remain supported
and unchanged. Execution receipts preserve both release-source Git and current
execution Git.

## Verification

- Focused identity/release/opening/supervisor tests: 85/85 pass, one expected
  symlink-capability skip.
- Full Python discovery after security hardening: 2,714/2,714 pass, one
  expected skip, 644.768 seconds.
- Full .NET solution: 259/259 pass.
- Compileall: pass.
- PowerShell parse: pass.
- `git diff --check`: pass.
- Actual environment probe: six declared requirements, fifteen installed
  distributions, deterministic fingerprint produced.
- Codex Security diff scan
  `de1408fc-2e0c-4c0f-8884-a4003e9f73a3`: complete, three findings repaired
  before branch qualification.

The deterministic mutation matrix proves docs/governance/review/test-only
changes leave runtime identity unchanged, while runtime code, launcher,
orchestration, provider/parser, models, scoring, TradePlan, calendar,
configuration, dependency/environment, add/remove/rename, and uncommitted
runtime changes invalidate identity. Release, receipt, pointer, missing
historical release, predecessor, fingerprint, schema, conflict, and reparse
tampering fail closed.

## Protected Boundaries

No candidate, Finviz rule, score, rank, TradePlan, Risk Governor, allocation,
Paper, Shadow, FakeBroker, Alpaca, Schwab, thinkorswim, market-data authority,
specialist, WPF, database, account, broker, order, or historical-evidence
semantics changed. Runtime strategy impact, broker/order impact, and market-data
semantic impact are all `NONE`. Release authority explicitly leaves Paper,
Shadow, broker orders, and transmission unavailable.

## Production Gate

The installed manifest remains SHA-256
`7757FEED119C13A209E7573BCBD315E78092C50CCFCC2DA0802D8641168496CD`.
The installed service executable remains SHA-256
`9DDACD6AD2A24545BA7A1A69BE5085AFC4B09DF77D300A00F1B8FAC37AB22A1A`.
Production remains on the exact-Git schedule with 15 pending openings, Monday
August 24 at 08:35 CT / latest 08:40 CT, service Running/Automatic, zero Shadow
jobs, and order transmission unavailable.

Before activation: commit and push the feature, create the rollback package,
fast-forward canonical, update the service with rollback, explicitly promote
Release A, advance canonical by docs only to B, pass the real zero-provider
service canary with A/B provenance, migrate only future pending openings
atomically, then perform final Monday readiness. Any failed gate restores the
exact-Git model.
