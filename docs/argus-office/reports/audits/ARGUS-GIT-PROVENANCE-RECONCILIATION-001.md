# ARGUS-GIT-PROVENANCE-RECONCILIATION-001

## Classification

`GIT_PROVENANCE_RECONCILIATION_COMPLETE`

`LONG_RUNNING_CAMPAIGN_PROVENANCE_MODEL_CORRECTED`

Branch: `codex/ARGUS-GIT-PROVENANCE-RECONCILIATION-001`

Implementation commit: `0050dd4a31e27351d6aadface62a6b7ba9e03acc`

Integrated commit: `d683d0180b3a1ed06265be635ebdee9a1d88692a`

Integration status: `COMPLETE`

The original `ARGUS-OVERNIGHT-DATA-FIDELITY-001` result remains permanently:

```text
GLOBAL_PRODUCTION_NONMUTATION = FAILED
```

This task did not edit, regenerate, reclassify, or adjudicate its provider evidence.

## Current Authority

| Identity | Full SHA / SHA-256 |
| --- | --- |
| Local `master` | `dca0671b7856c11b432304a544477246d2764faf` |
| `origin/master` | `dca0671b7856c11b432304a544477246d2764faf` |
| Installed continuous product | `e69426b3b7bd179cd62eba2e28a5d0553da47154` |
| Governance HEAD | `dca0671b7856c11b432304a544477246d2764faf` |
| Automation manifest | `6B0FCA73BF56A04501AE016BFEFC39E85DA386C44BB9FA63DEF37ED837B18BE4` |
| Continuous config | `EF1986A35000CA8EB425BCD7470BE0A9C4496007853F4AF20F779B565AF9D982` |
| Continuous deployment manifest | `FC2810BAA3730EDFB7679026A70F305992EC772A381E733819B54FFFD29B73EB` |
| Automation Service executable | `9DDACD6AD2A24545BA7A1A69BE5085AFC4B09DF77D300A00F1B8FAC37AB22A1A` |
| Runtime/writer host executable | `2A3A7BBA1E0FC6B215D739FEB8315AF193DBB28796876EE7AA26E87467F728BE` |

Canonical was clean and local/remote were equal before branch creation.

## Ancestry

```text
e1ea386f4640686569e2fb5a9a88e261ac974da3
├─ e69426b3b7bd179cd62eba2e28a5d0553da47154
│  └─ dca0671b7856c11b432304a544477246d2764faf
└─ 6a706e9c7975d57d96ff984e116331efce8a27f0
   └─ a75422605e67575d267d7d2980519878ec3a5a26
      └─ d51baaae781c9c7f34853ad4497f77e58429f1fc
         └─ 2cf159789e97acc257aa23e9399d08238008e149
            └─ 147ad753fbfdbeef1146205a0bfcca133cba2457
```

- `e1ea386...` was campaign-era canonical and installed product at start.
- `a754226...` was the frozen campaign source.
- `147ad753...` is the pushed overnight feature/closeout head.
- `e69426b...` is the installed Schwab-auth-lifecycle product.
- `dca0671...` is current canonical/governance HEAD.

Every commit exists locally and is reachable from its expected remote branch.
`a754226...` and `e69426b...` diverge after `e1ea386...`; neither contains the
other. The overnight branch is not production ancestry.

## Installed Product Versus Governance

The only commit from installed product `e69426b...` to governance HEAD
`dca0671...` is `Record Schwab auth lifecycle closeout`. It changes only five
files under `docs/argus-office/`.

The `momentum_hunter`, `tools`, `src`, and `tests` tree IDs are byte-identical
between the two commits. Classification:

`AUTHORIZED_GOVERNANCE_ONLY_DIVERGENCE`

There is no unexpected product/deployment divergence.

## Overnight Campaign Identity

| Field | Value |
| --- | --- |
| Started | `2026-08-20T06:44:37.084955Z` |
| Completed | `2026-08-21T00:05:18.735620Z` |
| PID | `65020` |
| Frozen source | `a75422605e67575d267d7d2980519878ec3a5a26` |
| Start canonical/installed product | `e1ea386f4640686569e2fb5a9a88e261ac974da3` |
| Persisted runner hash | `5809D0F2FB4BEE1CAF194E2E778AB9EA0C7ED27B3BE78CC7FB8E7DC94DCBC2C5` |
| Persisted checkpoint module hash | `B25E99BB7AB9581A5140F237E872D5133B71C99EC8CBC278FD1F1A4E450EEB13` |
| Start-time dependency manifest | `NOT_CREATED` |
| Post-hoc frozen-Git manifest | `6F698AA4CE55F6E5C8AE6FC18B70CCF5383D439F0B5402F7736FFA0177A68116` |

The dependency manifest is useful reconstruction but is explicitly **not**
presented as contemporaneous start evidence. The branch advanced after launch
only through source-contract documentation, tests, and a separate closeout
module; the loaded runner/provider files remained unchanged.

The 263-symbol research input was `daily-ohlc-bars.json` with SHA-256
`2B1FDC1482D9D98A810D6F06AACDB7E9DE1E6123BE39E5F35634DF34C66BB521`.
Its hash was persisted in capacity checkpoints; its path was omitted there and
recovered by exact hash match.

## Authorized Change Timeline

1. `2026-08-20T18:28:17Z`: local `master` fast-forwarded from `e1ea386...` to
   product `e69426b...` for `ARGUS-SCHWAB-CONTINUOUS-AUTH-LIFECYCLE-001`.
   `origin/master` recorded the push at `18:28:33Z`. Installed product remained
   `e1ea386...` during this Git-only transition.
2. `2026-08-20T18:32:51.9898474Z`: installed Continuous Runtime/writer advanced
   from `e1ea386...` to `e69426b...`. Continuous config changed
   `D8D96E...` to `EF1986...`; deployment manifest changed `F41857...` to
   `FC2810...`; Automation manifest stayed `6B0FCA...`. Runtime and writer
   service roots changed to the `e69426b...` source/runtime trees.
3. `2026-08-20T19:11:06Z`: governance closeout advanced canonical from
   `e69426b...` to `dca0671...`; `origin/master` recorded the push at
   `19:11:19Z`. Installed product, services, and manifests did not change.

The authority source was Steven's bounded Schwab auth-lifecycle directive and
Goal Charter, followed by standing-delegated nonvisual release closeout.

## Why The Historical Gate Failed

The finisher expected:

```text
canonical              e1ea386...
continuous config      D8D96E...
deployment manifest    F41857...
```

It observed:

```text
canonical              dca0671...
continuous config      EF1986...
deployment manifest    FC2810...
```

The Automation manifest stayed unchanged. The exact root cause was separately
authorized concurrent Schwab auth-lifecycle integration/deployment plus its
governance closeout. Therefore the original broad production-nonmutation test
truthfully failed.

## Shared Resources And Gaps

The campaign evidence root was campaign/closeout-owned and no production path
touched it. The research Daily universe was read-only and its hash stayed
identifiable.

The following historical gaps prevent retroactively asserting the new narrower
campaign claim:

- The sidecar read the same mutable user-DPAPI Schwab OAuth state that
  production was authorized to refresh. Earlier checkpoints preserved
  `EXPIRED / NOT_RUN_SHARED_TOKEN_NOT_ACTIVE`; the final 20:05 ET checkpoint
  preserved `SUCCESS`. The external change was not followed by campaign
  isolation revalidation.
- The Alpaca Canary Paper DPAPI credential was shared read-only, but no
  start-time encrypted-blob fingerprint or mutation receipt was preserved.
- Python interpreter/dependency identity and a standalone provider-route
  allowlist fingerprint were not frozen at campaign start.
- The full source dependency manifest was reconstructed after the fact rather
  than persisted before launch.

These are `CAMPAIGN_PROVENANCE_GAP` findings, not provider-data adjudications.
They do not change the old result and do not prove the provider observations
valid or invalid.

## Corrected Model

The old model had one giant `PRODUCTION_DID_NOT_CHANGE` boolean. The new model
requires:

1. Campaign-frozen full Git/file/config/process/provider/evidence identity.
2. Production baseline with canonical and installed product separated.
3. Declared shared mutable resources and allowed writers.
4. Append-only authorized external changes with old/new Git, installed product,
   manifest, service, shared-resource, and authorization identity.
5. Bounded revalidation after every external change.

The two claims are now independent:

```text
CAMPAIGN_NONMUTATION
GLOBAL_PRODUCTION_NONMUTATION
```

A future campaign may pass the first while the second is false only when every
external change is declared and classified
`AUTHORIZED_EXTERNAL_CHANGE_ISOLATION_REVALIDATED`. Otherwise it is
`CAMPAIGN_ISOLATION_BROKEN`.

The contract is in
`docs/argus-office/templates/LONG_RUNNING_CAMPAIGN_PROVENANCE_TEMPLATE.md` and
is enforced by `tools/verify_campaign_provenance.py`.

## Five Required Answers

1. Did the original campaign truthfully fail its broad production nonmutation
   gate? **YES.**
2. Are we rewriting that historical result? **NO.**
3. Does the prospective model allow authorized production work without
   automatically invalidating campaign isolation? **YES, only after declared
   shared-resource and isolation revalidation pass.**
4. Can current master, installed product, governance HEAD, and frozen campaign
   source be related exactly? **YES.**
5. Is repository/provenance state clean enough for a separate overnight-
   evidence isolation reconciliation? **YES.** That later task must confront
   the historical provenance gaps and may not assume campaign nonmutation.

## Production Protection

No service, manifest, scheduler, credential, provider, account, broker, order,
runtime evidence, or overnight evidence was changed by this task. The terminal
read-only comparison at `2026-08-21T03:07:21.4898587Z` matched the baseline:

- service snapshot SHA-256:
  `C711BEA0FA78338719269048CF8DA287BE3D58B9CE45B583B66D7146688D0B5D`;
- scheduled task count: `23`, with no Momentum Hunter scheduler mutation event
  observed during the reconciliation;
- historical evidence: `51` files, tree SHA-256
  `5F52C966F5724A940C0B855ED1DC73AD6F60DFA1629FCA7F3CC6F93141573ED6`;
- automation manifest SHA-256:
  `6B0FCA73BF56A04501AE016BFEFC39E85DA386C44BB9FA63DEF37ED837B18BE4`;
- continuous configuration SHA-256:
  `EF1986A35000CA8EB425BCD7470BE0A9C4496007853F4AF20F779B565AF9D982`;
- continuous deployment manifest SHA-256:
  `FC2810BAA3730EDFB7679026A70F305992EC772A381E733819B54FFFD29B73EB`.

Canonical remained clean at synchronized
`dca0671b7856c11b432304a544477246d2764faf`.
