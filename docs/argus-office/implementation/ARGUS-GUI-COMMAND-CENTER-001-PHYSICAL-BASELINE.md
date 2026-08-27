# ARGUS-GUI-COMMAND-CENTER-001 Physical Baseline

## Verdict

`PRE_IMPLEMENTATION_PHYSICAL_BASELINE = PASS`

Captured read-only at `2026-08-26T20:25:05-05:00`. No provider, account,
broker, Paper, Shadow, order, canary, service-control, scheduler-control,
runtime-promotion, install, or evidence-write action was performed.

## Frozen Git Identities

| Surface | Identity | State |
| --- | --- | --- |
| Canonical production | `master` at `82460b3313b86c34dff4ffb737d2c04bf02e3ace` | clean; `origin/master` divergence `0/0` |
| Producer-001C task | `codex/ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001C` at `b7f6df51e9f6e08056c58b419c870f116096179c` | clean; remote divergence `0/0` |
| Producer-001C product | detached at `4690dbf193355bc7a39c6c74e531344ea8a37875` | clean; no upstream by design; commit tree `01248f6a8b21cabf860fef0d52a1f154b15dad3f` |
| GUI task | `codex/ARGUS-GUI-COMMAND-CENTER-001` based at `82460b3313b86c34dff4ffb737d2c04bf02e3ace` | only task documentation existed at baseline |

## Frozen Canary Schedule And Evidence Binding

Codex heartbeat file:

`C:\Users\steve\.codex\automations\producer-001c-forensic-canary\automation.toml`

- SHA-256:
  `BE284EE4270111BF25E6DA92272B0D6C94BCBDD7BF526DC39C0609E3376BBE69`
- status: `ACTIVE`
- schedule: daily at `08:28` local (`FREQ=DAILY;BYHOUR=8;BYMINUTE=28`)
- target task: `019f0b0c-ab51-76d3-9cb1-5dfea6819100`
- required task head: `b7f6df51e9f6e08056c58b419c870f116096179c`
- required detached product: `4690dbf193355bc7a39c6c74e531344ea8a37875`
- provider observation: at or just after `08:32` Central
- evidence root:
  `C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-CONTINUOUS-PRODUCER-001C-FORENSIC-CANARY-20260827-REGULAR-B7F6DF5`
- disposable runtime root:
  `%TEMP%\MomentumHunter-Producer001C-Forensic-20260827-B7F6DF5`
- discovery cadence: 300 seconds
- order capability: unavailable; the heartbeat forbids account values,
  balances, positions, Paper, Shadow, broker, and order queries.

The heartbeat was read as a file only. It was not viewed, updated, paused,
woken, triggered, or deleted through the automation API.

## Binding Forensic Evidence

| Artifact | SHA-256 | Result |
| --- | --- | --- |
| Producer-001A forensic standard | `8B3A7F161BA393DACCED20C92B6B544C3893D201A97F76B370980DA884940303` | exact |
| Failed 001A second-eye ZIP | `E74B675DD24CA3E0EDFE0203F76197CAB35D1FA074E4FF322621DFDBC7F00345` | exact |
| Failed 001B second-eye V2 ZIP | `A4609AA3562D5705D88DF13498F7EBAEAB7E6A615910B4445887625B60EE371B` | exact |

Only file hashes were read. Contents of the ZIPs and any credentials were not
opened or printed.

## Opening Runtime

Read-only command from clean canonical production:

```text
.\.venv\Scripts\python.exe -B -m momentum_hunter.opening_runtime_release status
```

Result:

- status: `APPROVED_RUNTIME_MATCH`
- channel: `opening-capture`
- release: `OPENING-RUNTIME-D220AEA03F465DEA3B6A`
- release fingerprint:
  `3947881e4c0c70108b536aad0cb27738b4d89d14a3993ded16c95ddf05ce944e`
- approved runtime fingerprint:
  `d220aea03f465dea3b6ab970a417e08ec40b4649982d9a356336aafb93c67429`
- current Git: `82460b3313b86c34dff4ffb737d2c04bf02e3ace`
- runtime match: `true`
- worktree clean: `true`
- order transmission: `UNAVAILABLE`
- mutation performed: `false`

This fingerprint is the authoritative installed opening-reachable byte/config
identity for the before/after equality gate.

## Installed Service, Manifest, And Continuous Identities

All three relevant services reported `Running` and `Auto`:

- `MomentumHunterAutomation`
- `MomentumHunterContinuousRuntime`
- `MomentumHunterContinuousWriter`

| Installed surface | SHA-256 |
| --- | --- |
| Automation manifest | `AFC55EC289E46E02DF96C2FC0B4DD501DEEC763FC94B82DBB2065B25F942700B` |
| Automation service executable | `D71660B49BC4EFD51F36AC0A7C53333BE844057FCC6EF4C3982CF1005F0F7558` |
| Continuous deployment configuration | `EF1986A35000CA8EB425BCD7470BE0A9C4496007853F4AF20F779B565AF9D982` |
| Continuous deployment manifest | `FC2810BAA3730EDFB7679026A70F305992EC772A381E733819B54FFFD29B73EB` |
| Continuous service host executable | `2A3A7BBA1E0FC6B215D739FEB8315AF193DBB28796876EE7AA26E87467F728BE` |
| Deployed Continuous source tree (416-file deterministic manifest digest) | `C73EFFA113D26CC91970BF8C10A7373882F595D15E15EC32FD7320C9F2D4482E` |

The deployed source path remains bound to product identity
`e69426b3b7bd179cd62eba2e28a5d0553da47154` by its installed directory name.
The Automation manifest contains 19 jobs, zero enabled Shadow jobs, and zero
enabled Paper jobs. The opening release root remains
`C:\ProgramData\MomentumHunter\Automation\opening-runtime`.

### Official Installed Continuous Runtime-Build Proof

The deployed source is bound by the installation manifest to canonical product
commit `e69426b3b7bd179cd62eba2e28a5d0553da47154`. Its Git
`momentum_hunter` tree is
`96be6ad16f4670506cb2a93b734f0d75e72b45c9`. The installed commit's own
six-file `Get-RuntimeBuildHash` algorithm was reproduced from the deployed
source root and returned
`a44e9f35cfdf804efc85bad9459b5102902d695b9d8db179885e65b31450ef45`,
exactly equal to `runtimeBuildHash` in both installed Continuous manifests.

Each covered installed source also normalized to the exact Git blob at
`e69426b3b7bd179cd62eba2e28a5d0553da47154`:

| Installed source | File SHA-256 | Expected and observed Git blob |
| --- | --- | --- |
| `momentum_hunter\continuous_production.py` | `2a851e14f90f077088c6b8a162c0324142b25169e405cfc489b3dbfc329ca21b` | `1c37e552801cdb2dd9b45550bfd732b8a6204cfd` |
| `momentum_hunter\continuous_runtime.py` | `d2b14b3e4e764c35d6f179485f3a08776f1f763b0647c9c43eb602bdc20d097e` | `ee5ef26d443a17a2b38b92c5c1fabf504a312f36` |
| `momentum_hunter\continuous_live_qualification.py` | `ece88db07ffb040feab0741289b9d68ccb7d4335e71cf21342dafeb3ad7f057d` | `0481567b448267b798c36c3c8a30eca4d7200535` |
| `momentum_hunter\continuous_evidence_writer.py` | `8dcf7f0e5eb23decd627dd3f43efb60c93b588e9e8169e0ae1e528c382563bb8` | `b3e8c0f9d6eb5ea3ae1ecc29623834992bb530cb` |
| `momentum_hunter\event_runtime_writer_ipc.py` | `96dd2881ed2596d05db2ca1d9b09caafa91f67f23f397f99a616ac7e53b8c2a3` | `5cf9356cb48f9a6bded4ca922a5b0de9bded9aa9` |
| `momentum_hunter\windows_writer_storage.py` | `a815ed1a3c960652174a03e84f836e77d55f3390af89292b485f2931215c0587` | `153d6047f15cfff481fa7290cccbe0a5ff9b6090` |

The current canonical installer contains a seventh source for future releases;
that later list is not the identity algorithm for installed commit `e69426b...`.
The commit-local six-file proof above is the applicable baseline and passed.

The isolated Continuous Python runtime contained `2736` files totaling
`38347099` bytes. Its `Scripts\python.exe` SHA-256 was
`21BB438C0D4A6F1F164B9A646F6EE000340185E5871180AEC06DB8D3F07C0082`,
and its `pyvenv.cfg` SHA-256 was
`BD2524835367CB09F5E4F81CDA2511FA75165225D3F4994F99E637A2EECC16DE`.

## Startup Pointer Identities

| Pointer | SHA-256 |
| --- | --- |
| User Start Menu `Momentum Hunter.lnk` | `5A49E7096A14353384F6F4C58651B2273DFD0FDD7559A3393B1CEDECC1640A81` |
| User Startup `Momentum Hunter.vbs` | `A19BAD72D48E85F3E61BD200AFDE10C35851BDCFD88202194D0B1A6B5CC5EE6D` |

Targets were not launched or changed.

## Capability And Contact Boundary

- Provider contact performed: `NO`
- Account/position/balance query performed: `NO`
- Broker/order capability invoked: `NO`
- Paper or Shadow invoked: `NO`
- Service/scheduler mutation: `NO`
- Canary/evidence root touched: `NO`
- Opening promotion/repin/install: `NO`
- Order transmission reported by the opening gate: `UNAVAILABLE`

Installed local config/manifest/status artifacts reported these exact
capability values without any provider or account query:

| Capability field | Baseline value |
| --- | --- |
| Deployment mode / authority | `RESEARCH_ONLY` / `RESEARCH_ONLY` |
| Execution authority | config `NONE`; runtime status `EXECUTION_AUTHORITY_NONE` |
| Account binding | present; value intentionally not printed |
| Account type | `INDIVIDUAL_CASH` |
| Account reads | configured `AUTHORIZATION_BOUNDARY_ONLY`; current runtime status `UNAVAILABLE` |
| Positions requested / position reads | `False` / `UNAVAILABLE` |
| Orders requested | `False` |
| Order capability / transmission | `UNAVAILABLE` / `UNAVAILABLE` |
| Broker orders | `UNAVAILABLE` |
| Shadow execution / enabled jobs | `UNAVAILABLE` / `0` |
| Alpaca Paper / Alpaca Live | `UNAVAILABLE` / `UNAVAILABLE` |
| Runtime state / session phase | `IDLE_OUT_OF_SESSION` / `SESSION_CLOSED` |

`runtime-status.json` naturally advances, so its whole-file hash is contextual
rather than a strict byte-equality gate. The stable installed config,
deployment manifest, source/runtime hashes, and capability values above are the
post-implementation comparison surfaces.

## Exact Read-Only Checks

- `git rev-parse`, `git symbolic-ref`, `git status --porcelain`, upstream and
  divergence checks in canonical, canary task, and detached product worktrees.
- `Get-FileHash -Algorithm SHA256` on the heartbeat, binding forensic evidence,
  installed manifests/configuration/binaries, Continuous tree manifest, and
  workstation pointers.
- `Get-CimInstance Win32_Service` for state/start/path observation only.
- selected-field JSON parsing of the Automation manifest; no file write.
- the opening-runtime `status` command above, which returned
  `mutationPerformed=false`.

## QA Baseline Report

- Branch: `codex/ARGUS-GUI-COMMAND-CENTER-001`.
- Scope: read-only pre-implementation physical identity baseline.
- Files changed: this report only.
- Tests/checks: exact checks listed above.
- Evidence for changed behavior: none; this is an equality baseline.
- Protected areas reviewed: canary, runtime, scheduler, evidence, services,
  manifests/configuration, providers, Paper/Shadow, broker/account/order, and
  startup pointers; none changed.
- Push/merge status: none.
- Risks: the Roadmap prose lags Producer-001C, but exact live Git/heartbeat
  identities match Steven's newer directive.
- Manual QA: not applicable at this stage.
- Open questions: none blocking GUI-only implementation.
- Recommendation: Builder may edit only the chartered GUI worktree. Repeat all
  equality checks after implementation and before commit/push.
