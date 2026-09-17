# 018A Contract Reconstruction

Status: CONTRACT_RECONSTRUCTED; implementation and qualification pending.
Base: `8fe5e9b6a686678c7eed7d462a7ef24966449dda`.
Reference only: frozen 017A overlay on `2dd1eb40c5e5ad2ef1b5cffe37cc58f6bf2bfd9a`,
source manifest SHA-256 `A9D7EA56EE8855B7EDC42EE07C846017ADEA9F0F65B06EBAC0059252266E9CB5`.
No old physical configuration, native object identity, key or service is reusable.

## Contract Matrix (Recorded Before Product Implementation)

| Requirement | Canonical current state | Old 013B behavior | Successor required behavior | Test or evidence |
| --- | --- | --- | --- | --- |
| Explicit input authority | Legacy research-only writer/runtime; no installed offline mode | Schema-2 OFFLINE_QUALIFICATION, exact authority and collision rejection | Preserve legacy production decode without granting Science; admit only explicit isolated offline host | Original 013B directive; test_continuous_host_boundaries |
| Source/install separation | No installed qualification topology | Exact installed source role may be inside instance; checkout and writable overlaps rejected | Retain repaired role/path and reparse/Git-metadata rules; new source/fixture identities | test_continuous_installed_source |
| Offline import and network boundary | Provider modules import HTTP implementation eagerly | Lazy HTTP imports; retained input adapters; Python audit denial | No provider construction/contact during offline qualification; imports must not create sockets; no provider semantic change | test_offline_http_imports; host-boundary negative tests |
| Science process owner | No Science service role | Dedicated SCM service embeds Python in-process | Reuse existing service host; SCM_DIRECT only; no restricted-child launcher, token borrowing, new credentials or privilege ladder | Architecture 014; DirectScience.Probe; test_science_direct_service_contract |
| Science authority | Science007 custody policy exists, not host-bound | Exact service SID, token, image and per-resource authority validation | Preserve actual actor validation, denied service/file rights, trusted input image and zero-socket bootstrap | DirectScienceAuthority/TokenContract/Image; qualification-target negative probes |
| Writer trust model | Trusted Science007 finalizer, no bounded host profile | LocalService actual SCM/generation binding plus finite token and resource envelope | Preserve trusted finalizer, not OS-WORM against Writer; HIGH alone is insufficient; exact stable groups/attributes, fresh logon, mandatory policy, privilege inventory, native resources and service denials | 017A accepted report: 133 focused tests/1422 subtests and independent 25/554; test_writer_admission_contract_017a |
| Admission lifetime | No installed generation model | Native admission rechecks and held image/resource bindings | Revalidate actual process/token/resource generation; fail closed on drift | test_windows_writer_profile_016d; test_writer_token_diagnostics_016h; test_writer_self_authority_016j |
| Untrusted handoff | Canonical Science007 already owns request/finalization protocol | Host guards plus adversarial request/source/final-object checks | Preserve payload/envelope meanings, exact bytes, bounded work, conflicts, no stale-path cleanup and no arbitrary deputy authority | test_writer_handoff_016e; Science007 writer/Windows tests |
| Durable acknowledgment | Canonical receipt visibility alone can precede required post-rename durability | Completion marker published after dependency barriers; read/recovery gate checks confirmation | Port proven 016E repair: pending is not success/corruption; only Writer can reconfirm; lost replies/restarts cannot cause premature cleanup | 016E durability reopen authorization; test_science_custody_durability_016e; recorder/recovery regressions |
| Readiness | Per-role status, no aggregate installed Science gate | Fresh birth-bound generation vector, current dependencies, V2/custody readiness | Require all mandatory roles/current-generation evidence; stale, degraded, pending and failed never READY | test_continuous_host_generation; test_continuous_host_science007 |
| Drain/restart | Host kills subprocess on stop | Cooperative runtime -> Science -> Writer drain, completion bound to actual exit | Preserve stop admission, durable obligations, bounded incomplete result and no orphan claim; reuse canonical checkpoint/Science semantics | generation tests; host lifecycle tests; DirectScience generation probe |
| Qualification targets | Not present | Exact qualification target manifest and native resource identities, denied unsafe grants | New target identities only; preserve complete/nonempty checks, frozen bindings and native access-result interpretation | test_science_qualification_targets; QualificationTargets.Probe |
| Validator diagnostics | Redirected output only, cancellation may lose evidence | Linked caller/timer cancellation and in-memory validator output; historical cause UNKNOWN | Successor must retain bounded durable stdout/stderr, child/birth, cancellation source/time and exit before teardown; synthetic evidence before physical use | New successor diagnostic tests; phase-7 evidence still required |
| Plan versus activation | Existing installed production untouched | Plan-only command describes intended service configuration | Validator may produce plan, never install/start services; physical validation is separate authority | print-install-plan focused tests; phase-8 exact fixture admission |

## Selected Delta And Exclusions

Select only six host/Writer Python modules, their continuous_production integration,
required lazy HTTP import changes, the Science007 durability/read-recovery delta,
native custody/profile admission delta, SCM-direct C# host integration and its
directly corresponding tests. Review each meaningful diff against current canonical;
ignore line-ending-only changes. Canonical already includes Science007 and is not
to be replaced by an older base.

Exclude WindowsScienceProcess, WindowsScienceToken and WindowsScienceTokenContract
child-launch implementations and their obsolete launcher-only probe/tests. Retain
WindowsScienceTokenInspection used by the actual SCM-direct authority path.
Exclude all external old harnesses, configuration files, key material, native IDs,
service creations, retired 017F paths and historical compatibility workarounds.
Diagnostic test fixtures are data, never actual admission authority.

The qualification-target owner contract is frozen to the new 018A lineage.
Old 015 owner declarations/responses must be rejected, not relabeled at runtime.
Target protocol structure, native ownership and security checks are unchanged.

The 017A evidence supports that bounded profile repair only; it explicitly did not
run a full suite. No old focused/full/physical result is asserted to qualify 018A.
New focused gates precede one full-suite pass and one independent frozen review.

## Governance And Stop Boundary

Historical dispositions remain: 017F cause UNKNOWN; physical replay NONREPLAYABLE;
017H PASS; 017I PASS; 017J PREFLIGHT_BLOCKED. Old branches/evidence are read-only.
Source implementation is branch-only. No canonical, installed service, scheduler,
provider/auth, Paper/live, broker/account/order or production mutation. No UAC.
Physical Runtime/SCM qualification is forbidden under 018A even after validator PASS.
Fresh fixture/instrumentation and exact validator admission follow review, not precede it.
