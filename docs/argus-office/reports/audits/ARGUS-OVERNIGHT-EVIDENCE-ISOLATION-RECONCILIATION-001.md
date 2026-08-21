# ARGUS-OVERNIGHT-EVIDENCE-ISOLATION-RECONCILIATION-001

## Classification

`OVERNIGHT_EVIDENCE_RECONCILED`

The original `ARGUS-OVERNIGHT-DATA-FIDELITY-001` result remains permanently:

```text
GLOBAL_PRODUCTION_NONMUTATION = FAILED
```

No historical checkpoint, report, manifest, provider result, or classification
was rewritten. This is a new claim-level overlay.

## Current Authority

| Identity | Value |
| --- | --- |
| Starting `master` / `origin/master` | `a413ced546c205e1e83e9c35fc7a82ac80488bfa` |
| Installed product | `e69426b3b7bd179cd62eba2e28a5d0553da47154` |
| Integrated provenance model | `d683d0180b3a1ed06265be635ebdee9a1d88692a` |
| Audit branch | `codex/ARGUS-OVERNIGHT-EVIDENCE-ISOLATION-RECONCILIATION-001` |
| Frozen campaign source | `a75422605e67575d267d7d2980519878ec3a5a26` |
| Overnight branch HEAD | `147ad753fbfdbeef1146205a0bfcca133cba2457` |
| Campaign/production baseline | `e1ea386f4640686569e2fb5a9a88e261ac974da3` |

## Historical Evidence

- Checkpoints: `15/15 COMPLETED`, all under persisted PID `65020`.
- Files: `51`.
- Prior and recomputed tree SHA-256:
  `5F52C966F5724A940C0B855ED1DC73AD6F60DFA1629FCA7F3CC6F93141573ED6`.
- ZIP SHA-256:
  `C03C60F055ACA1A148C5232D8C42FF6126B3DEC25ED20EF839864C570EF4B374`.
- Persisted runner SHA-256:
  `5809D0F2FB4BEE1CAF194E2E778AB9EA0C7ED27B3BE78CC7FB8E7DC94DCBC2C5`.
- Per-checkpoint module SHA-256:
  `B25E99BB7AB9581A5140F237E872D5133B71C99EC8CBC278FD1F1A4E450EEB13`.
- Reconstructed source-manifest SHA-256:
  `6F698AA4CE55F6E5C8AE6FC18B70CCF5383D439F0B5402F7736FFA0177A68116`.
- Source classification:
  `SOURCE_IDENTITY_STRONGLY_CORROBORATED_POST_HOC`, not start-time proof.

The original 49-entry manifest has one retained, self-referential closeout
exception. It recorded `closeout-147ad75.stdout.log` as empty before the
finisher emitted its terminal JSON into that same log. The retained log is 999
bytes, SHA-256
`423DFF6CD0E30D4549A55416023516AF76E0DBC06A0DB74E2FDB7E49380584EA`,
and is semantically identical to `closeout/CLOSEOUT-RESULT.json`. The other 48
entries match byte-for-byte. The known 51-file tree already includes this
terminal log and remains exact.

## Authorized Change Timeline

| UTC | Task/event | Canonical | Installed | Material intersection |
| --- | --- | --- | --- | --- |
| `2026-08-20 18:28:17` | Schwab auth-lifecycle fast-forward | `e1ea386` -> `e69426b` | unchanged | No campaign file/state change |
| `2026-08-20 18:32:51.9898474` | Continuous product deployment | `e69426b` | `e1ea386` -> `e69426b` | Separate ProgramData runtime; shared Schwab OAuth became an authorized writable resource |
| `2026-08-20 19:03:50.9334651` | Read-only auth canary reported | unchanged | unchanged | Corroborates production refresh lifecycle |
| `2026-08-20 19:11:06` | Governance-only closeout | `e69426b` -> `dca0671` | unchanged | No product/provider intersection |
| `2026-08-21 00:01:26.1203063` | Shared encrypted OAuth file atomic replacement | unchanged | unchanged | Directly intersects Schwab state between 19:55 and 20:05 ET |

The first 12 scheduled checkpoints completed before these changes. The 16:05,
19:55, and 20:05 ET checkpoints completed afterward. No checkpoint ran during
the merge/deployment window.

## Dependency Matrix

| Resource | Classification | Changed? | Claim impact |
| --- | --- | --- | --- |
| Frozen campaign Git objects | `SHARED_IMMUTABLE` | No | Exact frozen source survives |
| Overnight feature worktree | `SHARED_MUTABLE_UNCHANGED` | Loaded files no | Later branch commits were docs/tests/closeout only |
| Python executable/site-packages | `HISTORICAL_STATE_UNPROVEN` | Not proven | Nonfatal dependency-identity limitation |
| Requirements/locked Git source | `SHARED_IMMUTABLE` | No | No authorized dependency declaration changed |
| Campaign configuration/schedule | `NOT_SHARED` | No | `CONFIG_IDENTITY_VALIDATED` |
| Campaign state/lock/evidence root | `NOT_SHARED` | Campaign only | One PID, 15 completed records, exact retained tree |
| Research Daily universe | `SHARED_MUTABLE_UNCHANGED` | No | Capacity source hash remained exact |
| Alpaca encrypted credential slot | `HISTORICAL_STATE_UNPROVEN` | Not proven | Exact credential/tier attribution limited; response evidence survives |
| Schwab encrypted OAuth state | `SHARED_MUTABLE_CHANGED` | Yes | Material to Schwab skip/call/auth attribution only |
| Finviz session/auth | `NOT_SHARED` | No | Fresh unauthenticated session per call |
| Provider host/route allowlists | `SHARED_IMMUTABLE` | No | Frozen code plus request metadata prove exact routes |
| DNS/network path | `HISTORICAL_STATE_UNPROVEN` | Not proven | Direct responses survive; path identity unclaimed |
| Production service/config/manifests | `NOT_SHARED` | Yes | No sidecar process/evidence-root intersection |

## Checkpoint Matrix

Every checkpoint uses source `a75422605e67575d267d7d2980519878ec3a5a26`.
All composite rows are `VALID_WITH_PROVENANCE_LIMITATION`; individual provider
claims below may still be fully `VALIDATED`.

| Checkpoint | Actual ET | SHA-256 | Providers/result | Production phase | Limitation |
| --- | --- | --- | --- | --- | --- |
| `BOUNDARY_0355_ET` | `03:55:00.000135` | `D472828A...8840` | Alpaca overnight 19x200; direct BOATS latest 4x403 | Before | Alpaca tier/dependency identity |
| `BOUNDARY_0400_ET` | `04:00:00.000224` | `DA679565...DC91` | Alpaca IEX 19x200, prior-day stale | Before | Fresh premarket not proven |
| `BOUNDARY_0405_ET` | `04:05:00.000415` | `C6923C9A...A740` | Alpaca IEX; 263/263; Finviz 20/20/0 | Before | Exact 04:00 Finviz boundary unproven |
| `BOUNDARY_0415_ET` | `04:15:00.000106` | `3A2E56E6...62C2` | Alpaca IEX 19x200, prior-day stale | Before | Alpaca tier/dependency identity |
| `EARLY_0500_ET` | `05:00:00.000345` | `40686F42...4F89` | Alpaca IEX 19x200, prior-day stale | Before | Alpaca tier/dependency identity |
| `EARLY_0600_ET` | `06:00:00.000155` | `53DCD307...EAAD` | Alpaca IEX 19x200, prior-day stale | Before | Alpaca tier/dependency identity |
| `PRE_0655_ET` | `06:55:00.000274` | `D0D3CA96...9C5D` | Alpaca IEX 19x200, prior-day stale | Before | No fresh 06:55 transition |
| `PRE_0700_ET` | `07:00:00.000200` | `CA321503...E50B` | Alpaca IEX 19x200, prior-day stale | Before | No fresh 07:00 transition |
| `PRE_0705_ET` | `07:05:00.000231` | `B61B9EB1...7241` | Alpaca IEX; 263/263; Finviz 20/20/1 | Before | Not a Schwab/universal boundary |
| `PRE_0800_ET` | `08:00:00.000461` | `51211A27...E825` | Alpaca IEX 19x200, prior-day stale | Before | Fresh Alpaca premarket disproven |
| `REGULAR_0945_ET` | `09:45:00.000239` | `E9210EB1...2969` | Alpaca current quotes/trades; 263/263; Finviz 20/20/10 | Before | Alpaca tier/dependency identity |
| `REGULAR_1000_ET` | `10:00:00.000247` | `0E34F0B0...D1F9` | Alpaca current quotes/trades | Before | Alpaca tier/dependency identity |
| `AFTER_1605_ET` | `16:05:00.000481` | `6C3F110C...DB9` | Alpaca mixed ages; Finviz 20/20/9; Schwab skipped | After | Schwab skip uses shared mutable auth |
| `AFTER_1955_ET` | `19:55:00.000181` | `A255438A...8852` | Alpaca stale; Schwab skipped | After | Schwab skip uses shared mutable auth |
| `OVERNIGHT_2005_ET` | `20:05:00.000657` | `D7E301D1...DC58` | Alpaca overnight + websocket; Schwab response with latest quote 20:00/bar 19:58 | After | OAuth replaced at 20:01:26; no true overnight Schwab update |

Full checkpoint hashes and fingerprints are in the adjacent JSON overlay and
enforced by `tools/verify_overnight_evidence_reconciliation.py`.

## Claim Ledger

| Claim ID | Provider | Phase | Checkpoint(s) | Original claim | Evidence | Source identity | Shared dependencies | Production intersection | Materiality | Final classification | Limitation | Rerun |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `SYS-001` | System | Full | All 15 | Global nonmutation passed | Original closeout | Original | Production | Direct contradiction | Governing gate | `VALIDATED` | Truth is FAIL | No |
| `SYS-002` | System | Full | All 15 | Exact start source/deps | State/checkpoints | Post-hoc corroborated | Python/Git | Git frozen; Python not frozen | Attribution | `VALID_WITH_PROVENANCE_LIMITATION` | Manifest reconstructed later | No |
| `SYS-003` | System | Full | All 15 | One continuous process | State/log/checkpoints | PID 65020 | State/Python | No restart observed | Continuity | `VALID_WITH_PROVENANCE_LIMITATION` | Command line not persisted | No |
| `ALP-001` | Alpaca | 03:55 | 03:55 | Fresh overnight quotes | 03:55 JSON | Exact route | Alpaca slot | None | Quote ages 0.142-29.729s | `VALIDATED` | Indicative only | No |
| `ALP-002` | Alpaca | 20:05 | 20:05 | Fresh overnight quotes | 20:05 JSON | Exact route | Alpaca slot | No Alpaca intersection | Quote ages 0.077-7.794s | `VALIDATED` | Bars/trades old | No |
| `ALP-003` | Alpaca | 03:55 | 03:55 | Bars/trades delayed 15-21m | 03:55 JSON | Exact route | Route | None | Direct timestamps | `VALIDATED` | One observed window | No |
| `ALP-004` | Alpaca | Overnight | 03:55,20:05 | Current BOATS denied | Two JSONs | Exact route | Alpaca slot | None material | 403/request IDs | `VALIDATED` | Named tier separate | No |
| `ALP-005` | Alpaca | Delayed | 03:55,corrected | BOATS history available | Two JSONs | Exact history routes | Route | None | Nonzero rows | `VALIDATED` | Research only | No |
| `ALP-006` | Alpaca | Delayed | 03:55,corrected | BOATS volume available | Two JSONs | Bar route | Route | None | Stored volume | `VALIDATED` | Delayed | No |
| `ALP-007` | Alpaca | Multiple | Five probes | 263/263 in one request | Capacity JSONs | Probe/universe hash | Universe/slot | None material | 47-93ms observed | `VALIDATED` | Not an SLA/max | No |
| `ALP-008` | Alpaca | 20:05 | WS matrix | 30 subscriptions accepted | WS JSON | Exact WS host | Alpaca slot | None | Three accepted shapes | `VALIDATED` | Bars-only no messages in 5.4s | No |
| `ALP-009` | Alpaca | 20:05 | WS matrix | 30 is hard ceiling | WS JSON | Matrix | Alpaca slot | None | 31 never attempted | `UNPROVEN` | Accepted-at-30 only | Yes |
| `ALP-010` | Alpaca | Full | Alpaca rows | Exact Basic identity | 03:55/20:05/contracts | Canary slot code | Alpaca slot | No blob fingerprint | Tier attribution | `VALID_WITH_PROVENANCE_LIMITATION` | Strongly corroborated only | Yes |
| `ALP-011` | Alpaca | Premarket | 04:00-08:00 | Fresh IEX premarket | Boundary JSONs | IEX routes | Route | None | Records prior-day stale | `INVALIDATED` | Staleness is surviving fact | No |
| `ALP-012` | Alpaca | Regular | 09:45,10:00 | Current regular IEX | Two JSONs | IEX routes | Route | Before changes | Direct timestamps | `VALIDATED` | Not an SLA | No |
| `ALP-013` | Alpaca | Full | Alpaca rows | Exact host/GET routes | Request metadata/source | Hardcoded allowlist | Route | No external override | Route provenance | `VALIDATED` | No account/order host | No |
| `FIN-001` | Finviz | 04:05 | 04:05 | 20/20/0 | 04:05 JSON | Frozen parser/schema | Fresh session | None | Counts/times/schema | `VALIDATED` | Raw HTML absent | No |
| `FIN-002` | Finviz | 07:05 | 07:05 | 20/20/1 | 07:05 JSON | Frozen parser/schema | Fresh session | None | Includes MSTR | `VALIDATED` | Not universal boundary | No |
| `FIN-003` | Finviz | 09:45 | 09:45 | 20/20/10 | 09:45 JSON | Frozen parser/schema | Fresh session | None | Counts/symbols | `VALIDATED` | First page only | No |
| `FIN-004` | Finviz | 16:05 | 16:05 | 20/20/9 | 16:05 JSON | Frozen parser/schema | Fresh session | Schwab-only change | Counts/symbols | `VALIDATED` | First page only | No |
| `FIN-005` | Finviz | 04:00 | 04:00,04:05 | Usable exactly 04:00 | Boundary JSONs | Not called until 04:05 | Fresh session | None | Five-minute gap | `UNPROVEN` | 04:05 cannot prove 04:00 | Yes |
| `FIN-006` | Finviz | Full | Four calls | Full universe/paging | Four JSONs | Single-page discover | Route | None | Only 20 rows/call | `UNPROVEN` | Not a denominator | No |
| `FIN-007` | Finviz | Full | Four calls | Named real-time tier | Four JSONs | Unauthenticated | Fresh session | None | No provider time/tier | `UNPROVEN` | Access survives | No |
| `SCH-001` | Schwab | 03:55-10:00 | First 12 | Inactive skip/no refresh | Boundary JSONs | Frozen nonrefresh | OAuth | Before change | Repeated skip state | `VALIDATED` | Not market data | No |
| `SCH-002` | Schwab | 16:05,19:55 | Two | Post-change inactive skip | Two JSONs | Frozen nonrefresh | OAuth | Authorized writer exists | Skip real, lineage limited | `VALID_WITH_PROVENANCE_LIMITATION` | Baseline attribution incomplete | No |
| `SCH-003` | Schwab | 20:05 | Final | Quotes/history returned | Final JSON | Frozen probe | OAuth | Replaced at 20:01:26 | Direct response | `VALID_WITH_PROVENANCE_LIMITATION` | Latest quote 20:00/bar 19:58 | No |
| `SCH-004` | Schwab | Post-20:00 | Final | True overnight updates | Final JSON | Frozen probe | OAuth | Auth changed | No post-20:00 timestamp | `UNPROVEN` | API response is not capability | Yes |
| `SCH-005` | Schwab | Full | Schwab rows | Campaign-isolated auth | 19:55/20:05 | Shared OAuth | OAuth | Direct shared mutation | Contradicts isolation | `INVALIDATED` | Response itself preserved | No |
| `SCH-006` | Schwab | Full | All | Streamer overnight | Final JSON | Not run | OAuth | N/A | No evidence | `UNPROVEN` | Explicitly not run | No |
| `ARC-001` | Cross | 06:55-07:05 | Five | 07:05 not universal start | Alpaca/Finviz JSONs | Surviving evidence | Alpaca/Finviz | Before changes | Earlier 03:55/04:05 evidence | `VALIDATED` | No Schwab claim | No |
| `ARC-002` | Alpaca | Full | Alpaca rows | Free tier sufficient for bounded research | Matrix/JSONs | Behavior/config | Alpaca slot | None material | Quotes/history/capacity | `VALID_WITH_PROVENANCE_LIMITATION` | Exact tier/ceiling limited | No |
| `ARC-003` | Cross | Architecture | Provider rows | Alpaca can be overnight context | Matrix/JSONs | Claim overlay | Alpaca/Schwab | Schwab limitation isolated | Useful bounded architecture | `VALID_WITH_PROVENANCE_LIMITATION` | No trading authority | No |

Counts: `17 VALIDATED`, `7 VALID_WITH_PROVENANCE_LIMITATION`, `6 UNPROVEN`,
and `2 INVALIDATED`.

## Provider Results

### Alpaca

`ALPACA_EVIDENCE = MIXED_VALIDATED_AND_VALID_WITH_PROVENANCE_LIMITATION`

The direct market-data observations are usable. Exact host and GET-only routes,
fresh 03:55 and 20:05 indicative quotes, delayed BOATS bars/quotes/trades and
volume, direct BOATS 403 responses, 263/263 bounded REST coverage, and three
30-channel websocket subscription shapes survive. Exact start credential/Basic
tier identity is only strongly corroborated. Thirty accepted channels is not a
proven hard ceiling. The campaign disproves, rather than proves, fresh Alpaca
IEX premarket data between 04:00 and 08:00 ET.

### Finviz

`FINVIZ_EVIDENCE = MIXED_VALIDATED_AND_UNPROVEN`

Four isolated unauthenticated first-page observations survive: 20/20/0 at
04:05, 20/20/1 at 07:05, 20/20/10 at 09:45, and 20/20/9 at 16:05, all under
the same parser/schema fingerprint. The campaign did not call Finviz at 04:00,
did not page beyond 20 rows, and did not preserve entitlement/provider-time
evidence sufficient to call it real-time.

### Schwab

`SCHWAB_EVIDENCE = MIXED_VALID_WITH_PROVENANCE_LIMITATION_UNPROVEN_AND_INVALIDATED`

The first 12 inactive-token skips are validated. The 16:05/19:55 skips are
proven observations with changed-shared-state limitations. The 20:05 response
is real, but the encrypted OAuth file had been atomically replaced at 20:01:26
ET. Its newest quote stopped at 20:00 ET and newest bar at 19:58 ET. Therefore
this campaign did **not** prove Schwab true-overnight API capability. Streamer
was never run, and isolated-auth attribution is invalidated.

## Momentum-Birth Result

- Real-time overnight detection survives for Alpaca indicative quotes, earliest
  at `03:55 ET` in the scheduled campaign.
- Delayed reconstruction survives for Alpaca BOATS bars, quotes, trades, and
  volume, with roughly 15-21 minute bar/trade delay in the earliest window.
- One bounded request repeatedly returned 263/263 research symbols.
- Finviz discovery access survives from `04:05 ET`, but only for the first 20
  rows and without real-time/tier proof.
- Schwab supplied no post-20:00 quote or candle in this campaign and receives
  no true-overnight architecture role from it.

## 07:05 Result

`07:05 IS NOT A UNIVERSAL START BOUNDARY` survives. Alpaca already supplied
fresh overnight indicative quotes at 03:55, and Finviz succeeded at 04:05.
At 06:55, 07:00, and 07:05, Alpaca IEX remained prior-day stale; only the 07:05
Finviz call added one qualifying first-page symbol. No Schwab call supplied a
07:05 fidelity result.

## Rerun Plan

`NO_FULL_RERUN_REQUIRED`

The existing evidence supports a provider-neutral, research-only architecture
using Alpaca overnight indicative context and delayed reconstruction. Before
assigning Schwab a true-overnight role, run one bounded,
credential/dependency-fingerprinted, read-only Schwab quote-plus-candle probe
after 20:05 ET and require provider timestamps after 20:00 ET. Only if product
code will hardcode an Alpaca Basic websocket ceiling, run one separate
credential-slot/blob-fingerprinted 31-subscription rejection probe. Neither
probe is launched or authorized by this audit.

## Production Protection

Baseline read-only identities:

- services SHA-256:
  `C711BEA0FA78338719269048CF8DA287BE3D58B9CE45B583B66D7146688D0B5D`;
- scheduler definitions: `23` tasks, SHA-256
  `3EC81FB383180FC4646F144804A2261BFC158BCFB7B683149E11AB553E613FE8`;
- automation manifest:
  `6B0FCA73BF56A04501AE016BFEFC39E85DA386C44BB9FA63DEF37ED837B18BE4`;
- continuous configuration:
  `EF1986A35000CA8EB425BCD7470BE0A9C4496007853F4AF20F779B565AF9D982`;
- deployment manifest:
  `FC2810BAA3730EDFB7679026A70F305992EC772A381E733819B54FFFD29B73EB`.

The final read-only check at `2026-08-21T05:23:48.3644729Z` reproduced every
service, scheduler-definition, and manifest hash above. All three services
remained Automatic/Running under their original principals, scheduler count
remained 23, and the canonical main worktree remained clean.

Provider calls: `0`. Account calls: `0`. Broker calls: `0`. Orders: `0`.
Services restarted: `0`. Manifests changed: `0`. Scheduler changes: `0`.
Historical evidence files changed: `0`.

## Seven Answers

1. Does the original campaign permanently fail global production nonmutation?
   **YES.**
2. Were historical checkpoints rewritten? **NO.**
3. Are Alpaca observations usable? **YES.**
4. Are Finviz observations usable? **YES.**
5. Did this campaign prove Schwab overnight API capability? **NO.**
6. Can useful architecture conclusions survive without a full rerun? **YES.**
7. Smallest remaining experiment: one fingerprinted post-20:05 ET Schwab
   quote/candle probe before granting Schwab an overnight role; separately, one
   31-subscription Alpaca probe only if a hard ceiling must be encoded.
