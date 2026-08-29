# ARGUS-GUI-COMMAND-CENTER-001F Integration and Installation Evidence

## Branch

Canonical `master` at merge commit
`250ecde3b4d4b99d57f3e35d7582c5badca0c9b9`. The accepted implementation is
`fc2761ad59c09c7329aa2fbb3a66d3c2bc9e4809` on
`codex/ARGUS-GUI-COMMAND-CENTER-001C-PRODUCTION-INTEGRATION`.

## Scope

Directive 001F created one freeze exception: non-destructively merge and
install the exact already-accepted Command Center. No implementation byte was
modified during integration. No strategy, scoring, ranking, admission,
lifecycle/Hot Universe policy, readiness, risk, entry, exit, sizing, execution,
broker, provider, market-data, candle-writer, Producer, automation, scheduler,
service, configuration, database, migration, unrelated GUI, cleanup, or
refactoring work was authorized or performed.

## Delivery evidence

1. **Canonical pre-merge commit:**
   `23ee162373654e1db91af4c19f75bbc7887e3174`, tree
   `a0709d65db42981d39b69ef31ea748daf923fad4`. Canonical was clean and exactly
   synchronized with `origin/master`.
2. **Accepted implementation verification:**
   `fc2761ad59c09c7329aa2fbb3a66d3c2bc9e4809`, tree
   `990753d60bf9781a46b88a4dcbb200871e35e5dd`, exists and is reachable. The
   accepted visual SHA-256
   `22BB20149EE3D5A3A2A73336AFA34E806DEE6B14E8D5C6F3DE94F73EB6235FDA` and
   accepted verification ZIP SHA-256
   `FADF4DAB890D3CC240051DE666AF1DCE9D6BFAA90A81CC97EE8B052754959E41`
   match. The accepted branch's later head `40ceaa4` was verified as a
   documentation-only successor and was not substituted for the exact accepted
   implementation commit.
3. **Canonical post-merge commit:**
   `250ecde3b4d4b99d57f3e35d7582c5badca0c9b9`, tree
   `edd19dd1ff7b800e49438639dc165d53fc5b4a7d`.
4. **Exact merge method:** `git merge --no-ff --no-commit
   fc2761ad59c09c7329aa2fbb3a66d3c2bc9e4809`, followed by the explicit merge
   commit `Merge accepted Command Center implementation`. Its exact parents are
   pre-merge canonical `23ee162...` and accepted implementation `fc2761...`.
   The merge completed cleanly without source conflict, squash, rebase,
   cherry-pick, reset, force operation, or history rewrite.
5. **Changed-scope audit:** the pre-merge-to-merge delta contains the exact 36
   accepted 001C paths: 15 implementation/read-model files, 6 test files, and
   15 charter/inventory/governance/proof files. All accepted paths except the
   deliberately reconciled Roadmap have blobs exactly equal to `fc2761`.
   Protected-path and added-capability scans found no strategy, lifecycle/Hot
   Universe writer, Producer, risk, execution, provider, broker/order,
   configuration, service, scheduler, database, or migration change.
6. **Build results:** Python compileall passed. The independently staged clean
   Release WPF rebuild and established canonical Release rebuild both completed
   with zero warnings and zero errors.
7. **Focused and bounded regression:** Command Center Python `11/11`; broader
   affected Python `154/154`; focused Command Center presentation `12/12`;
   layout `6/6`; focused mapper/Command Center integration `6/6`; full .NET
   solution `273/273` (`214` Presentation, `53` Integration, `6` Layout).
   `git diff --check`, protected-path audit, bounded capability scan, and added-
   line secret scan passed.
8. **Pre-install installed identity:** established canonical Release
   `MomentumHunter.Desktop.Wpf.exe` SHA-256
   `98C756FA5BCE2D9B7017425B23D77B035F58D8A5A1B2BB00F5E8D4274CA5CFC4`.
   No alternate `%LOCALAPPDATA%` installed copy existed. The Start Menu shortcut
   and VBS launcher SHA-256 values were respectively
   `5A49E7096A14353384F6F4C58651B2273DFD0FDD7559A3393B1CEDECC1640A81`
   and
   `5D6DC33C4A20217091E226F5216BF2CBBA0802E492B887ABE93D04F4EDD6B10F`.
9. **Post-install installed identity:** established canonical Release
   `MomentumHunter.Desktop.Wpf.exe` SHA-256
   `9ED81F0DC8E0CFE214036F68164110C50271ACF62CA5FC88855500DCD4D3F28B`;
   `MomentumHunter.Presentation.dll` SHA-256
   `7A893F4CD1B2C02ACDEEC4A60B3282F53C61CD517A341A76A74F23EBA73F2225`.
   Both exactly match the independently staged build. Shortcut and launcher
   hashes remained byte-identical.
10. **Rollback artifact and procedure:** prior 61-file workstation preserved at
    `C:\Users\steve\AppData\Local\MomentumHunter\Proofs\ARGUS-GUI-COMMAND-CENTER-001F-20260828\rollback\pre-install-workstation-23ee162.zip`,
    SHA-256
    `0858D27E95B1C35367BA792BE31DF93EFBF536E7672AC89EE8241DCC60D904AA`.
    Manifest SHA-256 is
    `27BB0B0C6B23327F55A2FFC541E80116D2490FCCC6313133D236F7C246B75674`.
    A separate extraction compared with zero missing, mismatched, or extra
    files. To roll back: close the workstation; verify the destination is the
    exact canonical Release directory; restore the 61 preserved files from the
    verified ZIP (or preserved directory); restore the preserved shortcut/VBS
    only if their hashes differ; then re-hash and launch. No service or runtime
    change is part of rollback.
11. **Installed screenshot:**
    `ARGUS-GUI-COMMAND-CENTER-001F-installed-1920x1080.png`, dimensions
    `1920x1080`, SHA-256
    `ACD8522BA3FBA988F6E0FEA7840A8FDB72D599AE68E2E7EAED638CECFB56BA68`.
12. **Installed Command Center sanity:** PASS. The exact installed executable
    launched from the established canonical launcher. It displayed the accepted
    macro hierarchy, Cross-Lifecycle Ranked Candidates with ten genuine current
    rows, Radar, Accepted, Rejected, Shadow Positions, What Changed, and System
    Context. Geometry remained pending; unavailable/partial evidence remained
    truthful; no synthetic row, clipping, horizontal scrollbar, or
    Buy/Sell/Submit/Cancel/Replace/Arm/Approve/Execute control appeared.
    Presentation freshness and charts remain explicitly non-authoritative.
13. **Producer identity:** accepted Producer-001C worktree remains clean and
    synchronized at
    `b7f6df51e9f6e08056c58b419c870f116096179c`, tree
    `89ac815623db0ccdf903e9b8432baf624f052c1e`. No Producer behavior or installed
    Continuous runtime was changed.
14. **Automation/runtime identity:** all three services remained Running and
    Automatic with unchanged pre/post PIDs (`MomentumHunterAutomation` 52196,
    Continuous Writer 45880, Continuous Runtime 50224). Automation service
    executable SHA-256 remained
    `D71660B49BC4EFD51F36AC0A7C53333BE844057FCC6EF4C3982CF1005F0F7558`;
    Continuous service host remained
    `2A3A7BBA1E0FC6B215D739FEB8315AF193DBB28796876EE7AA26E87467F728BE`.
    The supervisor heartbeat and Engine Host remained healthy. Active opening
    channel remained `OPENING-RUNTIME-D220AEA03F465DEA3B6A` and its pointer
    SHA-256 remained
    `B4D5D2876087CEAEBBFD0185FB9C303C9EB2845AF81747E4391512AF23451F36`.
15. **Provider/broker/execution boundary:** unchanged. Continuous remains
    `RESEARCH_ONLY`, `executionAuthority = NONE`, `orderCapability =
    UNAVAILABLE`, `ordersRequested = false`, `positionsRequested = false`, and
    `orderTransmission = UNAVAILABLE`; Shadow is unavailable and zero Shadow
    jobs are enabled. Installation made no provider or broker call and added no
    order authority.
16. **Service/configuration audit:** unchanged hashes: automation manifest
    `AFC55EC289E46E02DF96C2FC0B4DD501DEEC763FC94B82DBB2065B25F942700B`;
    Continuous deployment manifest
    `FC2810BAA3730EDFB7679026A70F305992EC772A381E733819B54FFFD29B73EB`;
    Continuous configuration
    `EF1986A35000CA8EB425BCD7470BE0A9C4496007853F4AF20F779B565AF9D982`.
    No service was restarted or reconfigured, no scheduler/startup policy or
    canonical data root changed, and the shortcut/launcher remained unchanged.
17. **Independent second eye:** performed read-only against merge parentage,
    accepted blobs, test/build evidence, installed screenshot and binaries,
    rollback package, and protected runtime identities. The separate review
    artifact records the final verdict.
18. **No unrelated production work:** confirmed. Only the exact accepted GUI
    merge, normal canonical Release replacement, proof collection, governance
    closeout, and required checkpoint scheduling occurred.
19. **Freeze:** `MOMENTUM_HUNTER_FREEZE = ACTIVE`. A one-time read-only Codex
    heartbeat named `Argus Monday Freeze Checkpoint` is scheduled for Monday
    2026-08-31 08:32 CT. It explicitly cannot release the freeze or authorize
    production changes.

## Pre-existing fail-closed runtime mismatch

`opening_runtime_release status` remains `FAILED /
APPROVED_RUNTIME_MISMATCH`, exactly as before 001F. The active D220 release
source predates the accepted Producer change to `canonical_candle_evidence.py`;
the GUI integration has zero diff to that file. Post-merge plan-only evidence
reports candidate fingerprint
`0ed9dad2a0bec4120a48f7d499c1c3fb5bb2d53523845a7860bfbdaacce01af8`
and `mutationPerformed = false`. The mismatch remains a separate
`DEPLOYMENT_HELD` condition. It was not promoted, repaired, waived, or caused by
the GUI installation and remains fail-closed before the next opening job.

## Files changed

The accepted merge contributed its previously reviewed 36 paths. The 001F
closeout adds only this report, the installed screenshot, the independent
second-eye report, and truthful Roadmap/Verification Queue updates. Application
source, tests, package files, services, configuration, data, and runtime
artifacts were not edited under 001F.

## Evidence for changed behavior

The installed executable identity equals the independently staged canonical
build, and the native installed capture proves the accepted read-only Command
Center is the application launched by the established canonical path. Protected
machine hashes, service PIDs, service health, launcher hashes, runtime authority,
and provider/order boundaries remained unchanged across installation.

## Protected areas reviewed

Strategy, scoring, ranking, admission, lifecycle/Hot Universe writers and
policies, TradePlan Producer, readiness, risk, entry/exit/sizing, execution,
brokers, providers, canonical candles, automation/scheduler/services,
configuration, data roots, database/migrations, credentials, and secrets.
None changed. The existing runtime mismatch is disclosed above.

## Push/merge status

The exact implementation is merged locally through `250ecde`. Final evidence
and governance changes are committed and normally pushed only after the
independent second eye and final clean-status/secret/protected-scope checks pass;
the delivery response records the final remote identity.

## Risks

The known `APPROVED_RUNTIME_MISMATCH` means the Monday opening capture remains
expected to fail closed unless a later separately authorized runtime directive
resolves it. Directive 001F does not authorize that work. The Monday checkpoint
does not automatically release the production freeze.

## Manual QA

Steven's final 001C visual and semantic decision is `PASS`. Installation sanity
was then performed against the exact installed canonical executable at native
1920x1080. No new Steven visual action remains queued.

## Open questions

None for the bounded GUI merge/install. The future runtime-mismatch disposition
and any freeze release require separate Steven authority.

## Recommendation

Preserve the installed and rollback artifacts, leave all protected services and
runtime identities untouched, keep canonical frozen, and use the scheduled
Monday 08:32 CT checkpoint only for read-only decision evidence.

## Terminal classification

- `ACCEPTED_GUI_COMMIT_VERIFIED = YES`
- `CANONICAL_MERGE_COMPLETE = YES`
- `POST_MERGE_TESTS_PASS = YES`
- `ROLLBACK_PROVEN = YES`
- `CANONICAL_INSTALL_COMPLETE = YES`
- `INSTALLED_RUNTIME_SANITY_PASS = YES`
- `TRADING_BEHAVIOR_UNCHANGED = YES`
- `PROVIDER_AUTHORITY_UNCHANGED = YES`
- `AUTOMATION_RUNTIME_BEHAVIOR_UNCHANGED = YES`
- `UNRELATED_FREEZE_BOUNDARY_CHANGE = NO`
- `HARD_CHEW_COMPLETE = YES`
- `GENERAL_PRODUCTION_FREEZE = ACTIVE`
- `FREEZE_RELEASE_NOT_BEFORE = 2026-08-31 08:32 AM CT`
