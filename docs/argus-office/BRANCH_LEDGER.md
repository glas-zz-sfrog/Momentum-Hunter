# Branch Ledger

Date reconciled: 2026-07-28

## Current Truth

Local and remote `master` are synchronized at SHADOW-016 scheduling closeout
`1af5b31`. The canonical product baseline contains the complete SHADOW-004 through
SHADOW-016 stack, including visual-acceptance commit `307a2e1`, alongside the Python
automation/simulation foundation, R004-R029 workstation work,
ARGUS-SHADOW-001/002/003, and SCHWAB-001/002/002A/003.

`codex/ARGUS-R035-candle-input-reconcile-1af5b31` is the only canonical R035
implementation lane. It replays six focused read-only candle commits onto current
`master`, adds a narrow file-boundary hardening closeout, and is verified pending
merge after the frozen 2026-07-29 SHADOW-016 operational audit.

`codex/ARGUS-R036-staged-candle-preview-host-7cbc2cb` is the canonical backend-only
successor stacked directly on R035. It reconciles the focused historical Engine Host
preview command, hardens the wire boundary, and is verified pending the same frozen
operational audit. It adds no WPF consumer or active chart cutover.

`codex/ARGUS-R037-wpf-staged-candle-preview-02f6423` is the isolated visual
successor stacked directly on R036. It reconciles and hardens only the WPF consumer,
current screenshots, and focused tests. It is implemented pending Steven's exact
visual acceptance and may not merge before that acceptance.

`codex/ARGUS-SHADOW-016-017-reconcile-1af5b31` is a parallel sibling of R035,
not part of the R035/R036/R037 ancestry. Read-only merge-tree proof finds no runtime
or test conflict with R036, but the branches both update four governance files.
After the frozen audit, preserve the six SHADOW-017 commits by replaying them onto
the released R036 baseline on a fresh reconciliation branch; do not directly merge,
rebase, or reset either source branch.

`codex/ARGUS-R035-candle-input-hardening` is superseded because it starts from the
older `4c35181` baseline and carries stale governance. The 62-commit
`codex/ARGUS-R035-staged-schwab-chart-preview-host` integration stack is
`DO_NOT_USE`; its focused candle and Engine Host content is preserved on the
canonical R035/R036 chain without its unrelated history. Its historical WPF preview
idea is reconciled on R037 without reusing the contaminated branch or stale proof.

`codex/ARGUS-SHADOW-004-official-sample-activation`,
`codex/ARGUS-SHADOW-005-prospective-evidence-handoff`, and
`codex/ARGUS-SHADOW-006-deterministic-market-validity`,
`codex/ARGUS-SHADOW-007-status-truthfulness`, and
`codex/ARGUS-SHADOW-008-proof-bundle-assembly`, and
`codex/ARGUS-SHADOW-009-live-proof-report-binding`, and
`codex/ARGUS-SHADOW-010-automatic-proof-ceremony`, and
`codex/ARGUS-SHADOW-011-proof-timestamp-ordering`, and
`codex/ARGUS-SHADOW-012-scheduler-retry` are preserved source-history
branches. Their complete stack is merged into local `master`; the relevant feature
tips are backed up remotely. The production-local sample is `ACTIVATED`,
`SELECTOR_NOT_ARMED`, and `0 / 30`.

Git evidence at reconciliation time:

- R027 and SCHWAB-001 are integrated into local `master` through `5f156eb`.
- ARGUS-SHADOW-004 began from synchronized `master` at `badee5c`, and Steven accepted its complete live WPF truth-label/layout proof on 2026-07-26.
- ARGUS-SHADOW-005 and SHADOW-006 are descendants of that accepted visual parent. The integrated stack adds no broker order or transmitting capability; compileall, 110 focused tests, all 844 Python tests, all 216 .NET tests, zero-warning Release build, live read-only weekend rejection proof, and production nonmutation proof pass.
- Local `master` fast-forwarded through acceptance commit `307a2e1` without a merge commit. The SHADOW-006 feature tip is synchronized with its remote feature ref.
- SHADOW-008 `fdcf898` adds the nontransmitting production proof assembler and schema-v2 quote provenance. It passed compileall, 26 focused tests, all 28 named proof-gate tests, 123 adjacent tests, all 854 Python tests, and all 216 .NET tests before clean fast-forward integration and non-force backup.
- SHADOW-009 `0038f17` removes caller-picked quote-proof identity and binds Gate 8 to the newest fresh canonical report plus immutable source capture. `3cb7854` adds the distinct 9:35 AM ET market-day capture, immediate authenticated Engine Host handoff, deterministic report-hash command identity, write-once receipt, and missing-receipt retry. It passed compileall, 193 affected tests, all 37 named proof gates, all 871 Python tests, all 216 .NET tests, PowerShell parsing, real loopback snapshot/auto-launch proof, and production nonmutation proof before clean fast-forward integration and non-force backup.
- SHADOW-010 `1e1bd21` automates the proof-complete opening arm ceremony before the existing handoff. It preflights synchronized Git and 11 static artifacts before a read-only Schwab quote request, binds candidate/SPY/IWM to the newest canonical report/capture, finalizes and re-verifies the 12-artifact bundle, and invokes the existing guarded arm method only after every proof passes. Compileall, 235 affected tests, all 45 named proof gates, all 880 Python tests, all 216 .NET tests, PowerShell parsing, secret/order-path scanning, and production nonmutation proof passed before clean fast-forward integration and non-force backup.
- SHADOW-011 `3f8acb8` fixes pre-request versus post-response clock ordering before the first live ceremony. A quote observed during OAuth/provider latency is now evaluated against the response-completion clock, request duration is retained, and backward/timezone-naive clocks fail closed. Compileall, 237 affected tests, all 46 named proof gates, all 882 Python tests, and all 216 .NET tests pass with production still unarmed and byte-identical.
- SHADOW-012 `c9c31f6` gives only the Shadow opening task three one-minute Windows restarts. The existing five-minute policy window, `IgnoreNew`, deterministic report-hash command, duplicate no-rescan path, and write-once handoff receipt bound retries without changing morning/evening capture behavior. Compileall, 18 focused tests, all 46 named proof gates, 237 affected tests, PowerShell parsing, and direct settings-object proof pass.
- `codex/ARGUS-SCHWAB-002A-credential-rotation` restores the existing approved Schwab app and OAuth state and is the source parent for the active SCHWAB-003 branch.
- `codex/ARGUS-SCHWAB-003-readonly-account-discovery` is merged into local `master` through `6f308d7`. Live discovery, account-detail validation, and immutable binding proved and pinned one `CASH` account ending `2573`; bound-refresh safety is implemented and tested, while every transmitting capability remains unavailable.
- R028 integrated workstation chrome and R029 canonical WPF launcher/icon passed automated and Steven manual verification.
- Steven approved the integration, and Git Steward fast-forwarded local `master` from `5f156eb` through R029 closeout `1d3d8e5` without a merge commit.
- Steven later approved the remote backup; Git Steward pushed the complete reconciled baseline to `origin/master` and verified the exact advertised HEAD.
- ARGUS-SHADOW-001's matching feature branch is remotely backed up at `bb962be`; ARGUS-SHADOW-002 is not pushed.
- `codex/ARGUS-A016T-schwab-paper-api-response` records Schwab's live-only, no-paperMoney, no-sandbox answer on a separate unmerged branch. A017 is blocked by vendor capability.
- `codex/ARGUS-R026-wpf-phase12-clean-room-integration` and R013-R025 are preserved source/audit branches superseded by the merged R027 path.
- `safety/ARGUS-R027-before-r026-integration` preserves pre-integration master `164e32e`.
- `codex/ARGUS-TEST-001-unattended-qt-discovery` remains preserved at `03ab813`; its two test files are identical to R026 `838ed22` and are included in R027 through the R026 parent.
- `codex/ARGUS-R011-wpf-chart-candle-integration` starts from `a17eff8`; its implementation and proof are merged into `master`, and commit `268f3f8` is remotely backed up through `origin/master`.
- `codex/ARGUS-R012-wpf-chart-readability` is merged and remotely backed up through `69feedf`.
- R004 and R005 are integrated through the `d3a98d9` and `e141054` history; their historical feature branches remain preserved but are not active work bases.

The Roadmap is the current-status authority. This ledger records branch evidence and classification only.

## Known Commit Containment

| Commit | Meaning | Local `master` contains? |
| --- | --- | --- |
| `ed94997` | Guard Daily Checklist quick actions | Yes |
| `c749e05` | Add guided Daily Workflow stepper | Yes |
| `18f3bf6` | Add Git Steward agent | Yes |
| `b8ecc92` | Add Goal Steward charter system | Yes |
| `4c004a1` | Add subagent artifact-first work contracts | Yes |
| `e04dffa` | Add autonomous platform foundation | Yes |
| `3365dea` | Add Hard Chew Protocol governance | Yes |
| `9ece892` | Add gateway and Argus Machine console skeleton | Yes |
| `e82b63e` | Add app.py responsibility map and extraction targets | Yes |
| `0ac66e0` | Extract Gateway and Argus Machine UI module | Yes |
| `664381d` | Add clean-room simulation proof | Yes |
| `4d63655` | Add technical breakout research engine | Yes |
| `1180315` | Add daily OHLC source for breakout research | Yes |
| `d3a98d9` | Integrate authoritative roadmap with R004 workstation shell | Yes |
| `e141054` | Preserve floating layout on explicit exit | Yes |
| `30c0e0b` | Reconcile roadmap after R004 and R005 integration | Yes |
| `6f853ba` | Harden Python host unavailable state | Yes |
| `a886c90` | Add read-only workstation integration | Yes |
| `180d69f` | Integrate WPF simulation workspace | Yes |
| `14fe317` | Fix simulation workspace plan mapping | Yes |
| `893a6da` | Clarify unavailable TradePlan state | Yes |
| `7efd48d` | Reconcile Phase 10 follow-up state | Yes |
| `a17eff8` | Record Phase 10 local integration | Yes |
| `268f3f8` | Add read-only WPF chart candles | Yes |
| `69feedf` | Add WPF chart readability | Yes |
| `fdcf898` | Build Shadow selector proof bundle | Yes |
| `0038f17` | Bind live quote proof to canonical report | Yes |
| `3cb7854` | Schedule official Shadow opening capture | Yes |
| `1e1bd21` | Automate guarded Shadow arm ceremony | Yes |
| `3f8acb8` | Fix Shadow quote proof timestamp ordering | Yes |
| `c9c31f6` | Retry failed Shadow opening task | Yes |
| `54c58a8` | Map Shadow Trading lifecycle wiring | Yes |
| `5d11f02` | Build prospective Shadow Trading validation | Yes |
| `7fee390` | Add WPF Shadow Trading review surface | Yes |
| `9002df0` | Add Shadow sample readiness gate | Yes |
| `a263311` | R026 integrated Phase 12 implementation through Research Maturity | No; R026/R027 branch history only |
| `838ed22` | Harden unattended Qt test discovery on R026 | No; R026/R027 branch history only |

## Branch Classifications

| Branch | HEAD | Pushed? | Merged to local `master`? | Classification | Purpose | Next action |
| --- | --- | --- | --- | --- | --- | --- |
| `codex/ARGUS-R037-wpf-staged-candle-preview-02f6423` | `c5f287a` plus governance closeouts | Yes; ordinary non-force feature-branch backup | No | `ACTIVE / IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE / PUSHED_FEATURE_BRANCH` | Explicit session-only WPF `Stored` / `Staged preview` selector, independently strict .NET envelope mapping, truthful no-fallback states, current screenshots, and no active chart/provider/account/write/order behavior. | Wait for Steven's exact seven-step visual acceptance. If SHADOW-017 reconciliation lands first, replay implementation commit `c5f287a` onto the then-current baseline and reverify instead of directly merging this sibling branch. |
| `codex/ARGUS-R036-staged-candle-preview-host-7cbc2cb` | `05008f3` plus feature-backup closeout | Yes; ordinary non-force feature-branch backup | No | `ACTIVE / IMPLEMENTED_PENDING_MERGE / PUSHED_FEATURE_BRANCH` | Canonical backend-only successor exposing the hash-verified inactive R035 stage through one bounded idempotent Engine Host command, with strict payload sanitization and no WPF/provider/account/write/order path. | Merge after R035 only when the frozen SHADOW-016 operational audit releases `master`. |
| `codex/ARGUS-R035-candle-input-reconcile-1af5b31` | Branch tip containing the R035 verification closeout | Yes; ordinary non-force feature-branch backup | No | `ACTIVE / IMPLEMENTED_PENDING_MERGE / PUSHED_FEATURE_BRANCH` | Canonical current-baseline lane for bounded GET-only Schwab candle staging, verified inactive chart previews, read-only cutover inventory/preflight, and file-boundary hardening. | Merge only after the frozen SHADOW-016 operational audit releases `master`. |
| `codex/ARGUS-R035-candle-input-hardening` | `00fcda6` | No | No | `SUPERSEDED` | Older-base source lane containing the six focused candle commits plus stale governance and obsolete rehearsal history. | Preserve as audit history; do not merge or continue. |
| `codex/ARGUS-R035-staged-schwab-chart-preview-host` | `16107c7` | No | No | `DO_NOT_USE` | Contaminated 62-commit integration stack that mixes focused candle/host/WPF preview work with unrelated branch history. | Preserve for forensic reference only. Candle, host, and WPF ideas are reconciled on the clean R035/R036/R037 chain; never merge or continue this branch. |
| `codex/ARGUS-SHADOW-016-017-reconcile-1af5b31` | `97884ea` | Yes | No | `IMPLEMENTED_PENDING_RECONCILIATION / PUSHED_FEATURE_BRANCH` | Preserves manual paperMoney reconciliation, model-error audit, immutable 5/10/20/30 evidence checkpoints, and checkpoint recovery on the frozen SHADOW-016 baseline. It is a parallel sibling of R035, with only four governance conflicts predicted against R036. | After the scheduled audit and R035/R036 fast-forward, replay its six focused commits onto the released baseline, regenerate governance from actual state, run combined proof, and fast-forward the new reconciliation branch. Do not merge this source branch directly. |
| `codex/ARGUS-SHADOW-013-opening-ceremony-hardening` | `58552da` | Via `master` | Yes | `MERGED_TO_LOCAL_MASTER` | Hardens semantic handoff completion, clock validity, frozen configuration, retry classification, proof-only opening rehearsal, outcome separation, and read-only heartbeat behavior. | Preserve branch; prepare the final-HEAD disabled proof-only task and real-session audit. |
| `codex/ARGUS-SHADOW-012-scheduler-retry` | `c9c31f6` plus governance closeout | Yes | Yes | `MERGED_TO_LOCAL_MASTER / PUSHED_FEATURE_BRANCH` | Adds bounded one-minute Windows restarts to the idempotent Shadow opening task without changing other capture schedules. | Preserve as source history; use the regenerated SHADOW-012 final-HEAD bundle and inspect the first live run. |
| `codex/ARGUS-SHADOW-011-proof-timestamp-ordering` | `3f8acb8` plus governance closeout | Yes | Yes | `MERGED_TO_LOCAL_MASTER / PUSHED_FEATURE_BRANCH` | Evaluates proof freshness after guarded OAuth/provider completion instead of against the pre-request clock, while preserving future-data rejection. | Preserve as source history; use only the regenerated SHADOW-011 final-HEAD bundle for the opening task. |
| `codex/ARGUS-SHADOW-010-automatic-proof-ceremony` | `1e1bd21` plus governance closeout | Yes | Yes | `MERGED_TO_LOCAL_MASTER / PUSHED_FEATURE_BRANCH` | Automates the proof-complete nontransmitting opening ceremony and invokes the existing FakeBroker-only selector cycle only after every immutable prerequisite revalidates. | Preserve as source history; inspect the first live market-day ceremony from canonical `master`. |
| `codex/ARGUS-SHADOW-009-live-proof-report-binding` | `3cb7854` plus governance closeout | Yes | Yes | `MERGED_TO_LOCAL_MASTER / PUSHED_FEATURE_BRANCH` | Binds live proof to the latest canonical report/capture and supplies the official 9:35 AM ET capture-to-selector handoff with retry/idempotency evidence. | Preserve as source history; use canonical `master` and the uniquely named SHADOW-009 static bundle. |
| `codex/ARGUS-SHADOW-008-proof-bundle-assembly` | `fdcf898` | Yes | Yes | `MERGED_TO_LOCAL_MASTER / PUSHED_FEATURE_BRANCH` | Adds schema-v2 quote provenance plus atomic 11-static/one-live proof-bundle preparation and finalization without arming or transmitting. | Preserve as source history; use canonical `master` for the ignored production proof bundle. |
| `codex/ARGUS-SHADOW-007-status-truthfulness` | `79e75b2` | Yes | Yes | `MERGED_TO_LOCAL_MASTER / PUSHED_FEATURE_BRANCH` | Separates sample-activation readiness from selector-arm and collection readiness in the read-only status command. | Preserve as source history; continue from canonical `master`. |
| `codex/ARGUS-SHADOW-006-deterministic-market-validity` | `307a2e1` | Yes | Yes | `MERGED_TO_LOCAL_MASTER / PUSHED_FEATURE_BRANCH` | Implements deterministic Official Shadow V1 selection, market validity, deduplication, portfolio/session/cycle/counterfactual evidence, proof-backed arming, and the pre-arm quote-proof CLI. Production remains unarmed and `0 / 30`. | Preserve as source history; continue only from canonical `master`. |
| `codex/ARGUS-SHADOW-005-prospective-evidence-handoff` | `ce5ef29` | Yes | Yes through SHADOW-006 | `MERGED_TO_LOCAL_MASTER / SUPERSEDED_BY_SHADOW_006` | Contains the verified capture-to-report handoff and the earlier fail-closed selector foundation. | Preserve as parent history; do not continue here. |
| `codex/ARGUS-SHADOW-004-official-sample-activation` | `375da59` | No feature ref; commits are included through integrated `master` | Yes through SHADOW-006 | `MERGED_TO_LOCAL_MASTER` | Adds the write-once official-sample activation boundary and Steven-accepted activated-empty WPF status. The ignored local sample is `ACTIVATED`, `SELECTOR_NOT_ARMED`, and `0 / 30`; no transmitting method exists. | Preserve as visual-parent history; do not merge again. |
| `codex/ARGUS-SCHWAB-003-readonly-account-discovery` | `6f308d7` | No feature ref; commits are backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Adds exact GET-only discovery, live CASH validation, immutable DPAPI binding to the sole `2573` `INDIVIDUAL_CASH` account, bound-refresh revalidation, and the standing-delegation governance; every transmitting capability remains unavailable. | Preserve as audit history; current work continues from `master`. |
| `codex/ARGUS-SCHWAB-002A-credential-rotation` | `cd73411` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Preserves the credential containment history and restoration of the existing approved Schwab app, local DPAPI credentials, and fresh OAuth. | Preserve as audit history; its work is included through SCHWAB-003. |
| `master` | Contains integration anchor `307a2e1`, SHADOW-007 `79e75b2`, SHADOW-008 `fdcf898`, SHADOW-009 `3cb7854`, SHADOW-010 `1e1bd21`, SHADOW-011 `3f8acb8`, SHADOW-012 `c9c31f6`, and this closeout | Yes; ordinary non-force backup push | Yes | `MERGED_TO_LOCAL_MASTER` | Canonical Python engine, WPF operator surface through R029, Shadow lifecycle/review/sample activation/evidence handoff/deterministic selector/truthful pre-arm status/report-bound proof assembly/opening cadence/automatic proof ceremony/post-response quote evaluation/bounded task retry, and SCHWAB-001/002/002A/003 with immutable `2573` CASH binding. | Run and inspect the first automatic live market-day proof/arm/handoff from the final-HEAD static bundle; preserve every failed or successful artifact. |
| `codex/ARGUS-R029-canonical-wpf-launcher` | `1d3d8e5` | No feature ref; commit is backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Makes the tracked normal launcher path WPF-only, restores the canonical icon, retains explicit Qt rollback, and refuses arbitrary review builds. | Preserve as audit history; do not merge again. |
| `codex/ARGUS-R028-integrated-workstation-chrome` | `0e7a6ce` | No feature ref; commit is backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Replaces the separate native title strip with integrated dark WPF chrome while preserving native window interactions and one global mode treatment. | Preserve as audit history; do not merge again. |
| `codex/ARGUS-R027-integrate-r026-with-shadow-baseline` | `6fe3f97` plus accepted repair/closeout history through local `master` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Preserves Shadow lifecycle/review/sample lock while adding the R013-R025 read-only WPF stack and R026 test hardening. | Preserve as audit history; do not merge again. |
| `safety/ARGUS-R027-before-r026-integration` | `164e32e` | No | Points to current master | `DO_NOT_USE` | Safety pointer for the pre-R027 canonical baseline. | Preserve until R027 is resolved and reviewed. |
| `codex/ARGUS-TEST-001-unattended-qt-discovery` | `03ab813` | No | No | `SUPERSEDED` | Independent copy of the same two Qt test fixes carried by R026 `838ed22`; R027 full discovery passes 641/641. | Preserve as audit evidence; do not merge separately. |
| `codex/ARGUS-SHADOW-003-sample-readiness-gate` | `9002df0`, `bb7aec6`, plus this merge-state closeout | No | Yes | `MERGED_TO_LOCAL_MASTER` | Immutable sample/config/fill/evidence metadata, fail-closed eligibility and readiness audit, gated metrics, and read-only locked WPF proof. | Preserve locally as audit history. Its historical merge did not start trade 1; current sample start follows the Roadmap's automated frozen-prerequisite gate. |
| `codex/ARGUS-SHADOW-001-shadow-trading-wiring-audit` | `bb962be` | Yes; feature branch only | Yes | `MERGED_TO_LOCAL_MASTER` | Prospective frozen-evidence Shadow Trading, quote-driven FakeBroker lifecycle/outcomes, durable audit/metrics, manual paperMoney ticket, and network-free Schwab read-only preparation. | Preserve as remotely backed-up audit history. |
| `codex/ARGUS-SHADOW-002-wpf-shadow-review` | `fe3326d` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Read-only WPF Shadow review, strict identity-chain audit, filters, linked review panes, and minimum-sample metric gating. | Preserve locally; next work starts from local `master`, not this branch. |
| `codex/ARGUS-R026-wpf-phase12-clean-room-integration` | `838ed22` | No | No | `SUPERSEDED` | Consolidated R013-R025 WPF implementation and unattended Qt test hardening; source parent for the verified R027 integration. | Preserve as immutable audit history; review R027 instead of merging R026 directly. |
| `codex/ARGUS-R025-wpf-research-maturity-evidence` | `5f0d36c` | No | No | `SUPERSEDED` | Read-only research-maturity/evidence-census projection with fail-closed strategy locks. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R024-wpf-candidate-story-evidence` | `37a0778` | No | No | `SUPERSEDED` | Linked read-only Candidate Story projection over canonical persisted evidence. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R023-wpf-daily-workflow-evidence` | `22eac54` | No | No | `SUPERSEDED` | Read-only Daily Workflow guidance and evidence pane. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R022-wpf-saved-watchlist-evidence` | `8fd9b72` | No | No | `SUPERSEDED` | Read-only persisted saved-watchlist projection. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R021-wpf-technical-research-evidence` | `756fbd2` | No | No | `SUPERSEDED` | Read-only technical-breakout event and study projection. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R020-wpf-alert-outcome-evidence` | `1475c41` | No | No | `SUPERSEDED` | Read-only persisted alert/outcome evidence. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R019-wpf-activity-events` | `9cb3f8b` | No | No | `SUPERSEDED` | Full read-only activity event disclosure. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R018-wpf-monitoring-status` | `1137a02` | No | No | `SUPERSEDED` | Read-only monitoring lifecycle disclosure. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R017-wpf-replay-context` | `b642aa9` | No | No | `SUPERSEDED` | Exact read-only replay identity disclosure. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R016-wpf-health-diagnostics` | `89952aa` | No | No | `SUPERSEDED` | Read-only component health diagnostics. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R015-wpf-candidate-evidence` | `a9f27c7` | No | No | `SUPERSEDED` | Persisted candidate Why/Research evidence disclosure. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R014-wpf-command-palette` | `86c54c4` | No | No | `SUPERSEDED` | Symbol quick-open and real pane actions with visible failure states. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-R013-wpf-chart-inspection` | `29dd27d` | No | No | `SUPERSEDED` | Nearest-candle hover inspection with UTC/OHLCV detail. | Preserve as an R026/R027 source branch. |
| `codex/ARGUS-A016T-schwab-paper-api-response` | `1bc90a8` | No | No | `NEEDS_REVIEW` | Preserves Schwab Support's live-only, no-paperMoney, no-sandbox response and broker decision consequences. | Keep A017 blocked; preserve as branch evidence. |
| `codex/ARGUS-R012-wpf-chart-readability` | `69feedf` | Commit backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Deterministic WPF chart price/time axes and latest stored-bar OHLCV details with no engine or provider change. | Historical integration branch. |
| `codex/ARGUS-R011-wpf-chart-candle-integration` | `268f3f8` | No branch ref; commit is backed up through `origin/master` | Yes | `MERGED_TO_LOCAL_MASTER` | Versioned read-only local chart snapshots and WPF candle/wick/volume rendering with explicit stale/unavailable behavior. | Historical integration branch; begin R012 from `master`. |
| `codex/ARGUS-A016S-schwab-paper-api-verification` | `c979866` | No | No | `SUPERSEDED` | Schwab paper API evidence gate and verified support request. | Preserve as sent-request history; A016T records the answer. |
| `codex/ARGUS-A016-broker-research-matrix` | `90259e4` | No | No | `SUPERSEDED` | Broker matrix plus Steven's original Schwab/thinkorswim continuity decision. | Preserve as research history; A016T records the vendor constraint. |
| `codex/ARGUS-R010-tradeplan-risk-simulation-integration` | `7efd48d` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Persisted TradePlan and Risk Governor evidence, FakeBroker-only simulation, ledger/auditor results, and explicit unavailable-plan handling in WPF. | Historical integration branch; start Phase 11 from local `master`. |
| `codex/ARGUS-R009-readonly-workstation-integration` | `a886c90` (stacked from `6f853ba`) | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Read-only persisted Python candidates, evidence, health, source lineage, and Replay context in WPF; mock planning/chart/simulation fallback disabled. | Historical integration branch; Phase 10 must branch from local master. |
| `codex/ARGUS-R008-python-engine-contract-host` | `6f853ba` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Independent local Python Engine Host, versioned WPF lifecycle bridge, duplicate guards, and process-level proof. | Historical integration branch; Phase 10 must branch from local master. |
| `codex/ARGUS-R004-momentum-hunter-wpf-shell-spike` | `5bbd0c7` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Windows-first WPF workstation-shell feasibility spike. | Historical branch; do not continue feature work here. |
| `codex/technical-confluence-wave-1-primitives` | `9678c5` | Yes | No | `NEEDS_REVIEW` | Research-only technical confluence primitives. | Review separately; it is not the current workstation-shell priority. |
| `codex/technical-indicator-registry-confluence-roadmap-v1` | `2af99da` | Yes | No | `NEEDS_REVIEW` | Indicator registry and confluence planning artifacts. | Keep as research planning; do not treat it as production behavior. |
| `codex/ARGUS-STATE-002-roadmap-reconciliation` | `ccfb7a0` | Yes | No | `SUPERSEDED` | Earlier roadmap reconciliation attempt. | Do not merge; replaced by the authoritative Roadmap reconciliation. |
| `codex/ARGUS-STATE-003-authoritative-roadmap` | `48d3ab4` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Established the authoritative Roadmap that was integrated through R004/R005 history. | Historical governance branch. |
| `codex/ARGUS-INTEGRATE-roadmap-r004` | `d3a98d9` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Integrated the authoritative Roadmap with R004 workstation history. | Superseded as an active work base by `master`. |
| `codex/ARGUS-R005-background-tray-lifecycle` | `e141054` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Close-to-tray, lifecycle controls, single-instance signaling, and R005 physical QA fixes. | Historical branch; Phase 8 must start from a new branch. |
| `codex/ARGUS-A006-A015-clean-room-verification` | `664381d` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Clean-room cherry-pick verification branch for simulation foundation; source of local fast-forward merge. | Keep as audit branch; do not continue feature work here. |
| `codex/ARGUS-A006-A015-argus-machine-simulation` | `91da577` | No | No by commit identity; content superseded by clean-room cherry-picks on `master` | `SUPERSEDED` | Original simulation foundation workstream. | Do not use for future work; use `master` or a new task branch. |
| `codex/ARGUS-A004-A005-tradeplan-risk-governor` | `8a90e18` | Yes | No | `SUPERSEDED` | Older standalone `momentum_hunter/execution/*` TradePlan/RiskGovernor experiment. | Do not merge as-is; see salvage note below. |
| `codex/ARGUS-A002-A003-gateway-machine-console-skeleton` | `52474fe` | Yes | No | `SUPERSEDED` | Earlier Gateway / Argus Machine skeleton branch. | Do not use; replaced by `codex/ARGUS-A002A...`, R002 extraction, and current `master`. |
| `codex/ARGUS-A002A-gateway-machine-console-hardening` | `9ece892` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Hardened Gateway / Argus Machine skeleton. | Historical branch only. |
| `codex/ARGUS-R002-extract-gateway-machine-ui` | `0ac66e0` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Extracted Gateway / Argus Machine UI into `momentum_hunter/ui/autonomy_gateway.py`. | Historical branch only. |
| `codex/ARGUS-R001-app-py-responsibility-map` | `e82b63e` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | `app.py` responsibility map and extraction targets. | Historical branch only. |
| `codex/ARGUS-R000-rewrite-refactor-decision-spike` | `b27013b` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Rewrite/refactor decision spike. | Historical branch only. |
| `codex/ARGUS-FI-001-future-ideas-autonomy-ui` | `008ac9a` | Yes | No | `PUSHED_FEATURE_BRANCH` | Future ideas parking lot for autonomy/UI. | Needs Steven/ChatGPT review before cherry-pick or merge; not canonical. |
| `codex/subagent-work-contracts` | `4c004a1` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Artifact-first subagent work contracts. | Historical branch only. |
| `codex/ARGUS-A000A-hard-chew-protocol` | `3365dea` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Hard Chew Protocol governance. | Historical branch only. |
| `codex/ARGUS-A000-autonomous-platform-foundation` | `e04dffa` | Yes | Yes | `MERGED_TO_LOCAL_MASTER` | Autonomous platform foundation docs. | Historical branch only. |
| `codex/ARGUS-0005A-goal-steward-verify` | `b8ecc92` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Goal Steward and Goal Charter system. | Historical branch only. |
| `codex/ARGUS-0005-git-steward-agent` | `18f3bf6` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Git Steward agent and branch safety rules. | Historical branch only. |
| `codex/ARGUS-0004-guided-daily-workflow-stepper` | `c749e05` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Guided Daily Workflow stepper bridge. | Historical branch only. |
| `codex/ARGUS-0003-guided-daily-workflow-design` | `eee0ab3` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Guided Daily Workflow design report. | Historical branch only. |
| `codex/ARGUS-0002-daily-checklist-visibility` | `ed94997` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Daily Checklist visibility and quick-action guards. | Historical branch only. |
| `codex/ARGUS-0000-office-scaffold` | `319244b` | No | Yes | `MERGED_TO_LOCAL_MASTER` | Argus Office scaffold and discovery report. | Historical branch only. |

## A004/A005 Supersession Finding

`codex/ARGUS-A004-A005-tradeplan-risk-governor` is superseded.

Evidence:

- It is listed by `git branch --no-merged master`.
- Its branch-only diff adds `momentum_hunter/execution/__init__.py`, `momentum_hunter/execution/trade_plan.py`, `momentum_hunter/execution/risk_governor.py`, `tests/test_trade_plan.py`, and `tests/test_risk_governor.py`.
- Current local `master` does not use `momentum_hunter/execution/*`.
- Current canonical implementation uses `momentum_hunter/trade_planning.py` for `TradePlan` / `TradePlanRow` and `momentum_hunter/autonomy/*` for Risk Governor, ledger, broker adapter, simulation engine, and auditor.

Salvage note:

- Do not merge A004/A005 as-is.
- The branch may be useful only as historical reference for isolated tests or naming ideas.
- Any salvage must be manually ported into the canonical `trade_planning.py` / `autonomy/*` architecture under a new task, with tests proving no duplicate model path is introduced.

## Do Not Use For New Work

Do not start new implementation from:

- `codex/ARGUS-A006-A015-argus-machine-simulation`
- `codex/ARGUS-A004-A005-tradeplan-risk-governor`
- `codex/ARGUS-A002-A003-gateway-machine-console-skeleton`

Use a fresh task branch from local `master` instead.
