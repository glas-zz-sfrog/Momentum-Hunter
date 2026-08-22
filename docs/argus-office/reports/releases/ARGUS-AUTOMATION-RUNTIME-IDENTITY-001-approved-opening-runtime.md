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
- Implementation commit:
  `ec199549e96062570864262f181fd339d7596121`, pushed and cleanly
  fast-forwarded to canonical.
- Approved release: `OPENING-RUNTIME-B7F9069A246ED2D99BC8` from source Git
  `6e3bf54ad156ecdd82a8d5f105285f83714958c0`.
- Runtime fingerprint:
  `b7f9069a246ed2d99bc86396fbc5914a0e541adf8bb766258e01cd0f1e5a85df`.
- Classification: `COMPLETE / APPROVED_RUNTIME_ACTIVE`.

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

The installed migrated manifest is SHA-256
`F293CE95F143BB8853E83F88D83F6ACED62A891CA88AFDE8780B95AB023EB862`.
The installed service executable is SHA-256
`891897683C1F0E6600473618434822B5DDC4D02D405A0D9ABE67B0F9FFDC3411`.
The loaded supervisor and runtime-identity module are respectively
`f9097fc9523e0873a756340397bda4e544b3573c7599693eda9927b1baf3cefd`
and `1764dad2851893f5f89f4fb38b3f923f40d7e79a85b138fca90136b261bb4380`.

Physical service canary `runtime-identity-canary-20260822t012058` completed
with exit `0`. It bound release source Git `6e3bf54`, execution Git `45ff047`,
release `OPENING-RUNTIME-B7F9069A246ED2D99BC8`, and exact approved runtime
match. Its durable evidence sets provider, account, position, Paper, Shadow,
and order requests to false and transmission to unavailable. The canary is no
longer in the active manifest; its receipt and one log remain preserved.

Migration changed exactly 15 future pending openings from legacy Git pins to
the `opening-capture` approved channel. The immediate plan and apply reruns
changed zero jobs. Monday August 24 remains enabled and `PENDING` at 08:35 CT /
latest 08:40 CT. The service is Running/Automatic with a fresh heartbeat,
zero jobs are running, zero Shadow/Paper jobs are enabled, order transmission
is unavailable, and Windows Time is synchronized to NIST.

Rollback package:
`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-AUTOMATION-RUNTIME-IDENTITY-001-ROLLBACK-f2c2b65d.zip`,
SHA-256
`C7FEE933E5F623A6FD4C72DC999B124357364F5897A85DEC433A63F3D8693F5B`.

The feature is integrated, promoted, physically proven, migrated, and ready.
Two initial service-update UAC prompts were canceled and the exact-Git fallback
was immediately restored; the later attended update passed. No provider,
capture, account, Paper, Shadow, broker, or order operation occurred during the
production proof. The approved release now decouples future opening eligibility
from unrelated Git-only changes while preserving fail-closed runtime identity
and the executable exact-Git rollback.
