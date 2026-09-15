# Repeated Bounded Qualification-Harness Repair Authority

## Authority And Scope

Authority: Steven's directive
`ARGUS-GOVERNANCE-AMENDMENT-HARNESS-REPAIR-AUTONOMY-001`, adopted
2026-09-14. Effect: `STANDING MH DEVELOPMENT RULE`.

During an already-authorized Momentum Hunter / Argus task, Argus may
autonomously diagnose, repair and retest deterministic qualification,
test-harness, instrumentation and helper defects multiple times without
requesting new user authorization for each repair. There is no one-repair
quota. Prefer productive bounded continuation while Steven is unavailable;
routine clerical qualification defects do not need repeated owner decisions.

This rule clarifies decisive-failure and interruption wording in agent,
operating and role documents. Apply
[the three-tier policy](PRAGMATIC_GATE_AND_EVIDENCE_POLICY.md) to the affected
claim and consequence. A harness label does not downgrade a product, security
or authority failure and never converts a failed gate into PASS.

## All Continuation Predicates Must Hold

- Product/runtime/trading/Science semantics are not implicated.
- Production state remains untouched.
- No new privilege or authority is granted.
- No safety or correctness invariant is weakened.
- The root cause is concrete and reproducible.
- The repair is confined to qualification/test/instrumentation/helper machinery.
- Original failed evidence is preserved.
- The repair remains inside the current task's authorized scope.

Examples, subject to every predicate: hash-case comparisons, harness paths,
test-environment layout, qualification-manifest bookkeeping, helper buffer or
serialization defects, stale test expectations, instrumentation-only defects,
test-only privilege cleanup and qualification-only import side effects.

Classify by actual effect, not a filename or the convenience of passing a test.
A stale expectation is repairable only with evidence of the unchanged
authoritative requirement; changing an expectation to excuse incorrect product
behavior or dropping a required assertion weakens acceptance and is prohibited.
Test-only cleanup cannot grant privileges or relax host security. Layout repair
does not authorize changes to the shared approved Python environment.

## Required Repair Loop

For each defect, including a second, third or later defect in the same task:

1. Preserve the original failed receipt, command, inputs and relevant identities.
2. Establish the exact reproducible root cause and all continuation predicates.
3. Make the smallest bounded machinery-only repair within the authorized scope.
4. Rerun **only the directly affected gate first**.
5. If that gate passes, automatically resume the parent qualification.
6. Retain both failed and repaired evidence for independent review.

If the affected gate fails again, retain that failure and classify its cause.
Repeat the loop for a proven, in-scope harness-only defect; do not loop blindly
until green, conceal an intermittent failure or claim the parent passed early.
Do not stop just because an autonomous repair was already made.

Do not rerun broad or full suites merely because the harness was corrected.
Run them when the parent task's later acceptance logic requires them. Required
Hard Chew, full-suite, byte/hash, ancestry, independent custody and review gates
remain mandatory. Reused valid evidence stays labeled as reused, not a new run.

## Decisive Failure And Fresh Authorization

For a real product, security or architecture blocker, stop downstream work
that cannot change the disposition. For a harness/qualification defect, stop
irrelevant downstream work, repair the harness, retest the affected gate and
resume the parent automatically after PASS. A deterministic failure is not,
by itself, an instruction to wait for Steven.

Stop the affected repair/progression and request fresh authorization if it
requires any of:

- Product behavior change.
- Trading, decision or Science semantic change.
- Architecture change.
- Production mutation.
- Security-policy relaxation.
- New privilege.
- New authority.
- Provider, broker or account contact.
- Live or Paper execution authority.
- Weakening an acceptance gate.
- Material expansion beyond the current directive.
- Changing a canonical contract.

Preserve the blocker and its evidence. Independently authorized work that
cannot affect it may continue under the three-tier policy. Missing Tier-1
identity, safety or authority proof still fails closed.

## Existing Ownership And Frozen-Candidate Boundaries

This amendment supplies bounded harness-repair autonomy inside an existing
task, not new product implementation, production, integration or activation
authority. Preserve role ownership, declared owned/protected paths, unique
evidence/runtime roots and environment isolation. A read-only review or
exact-byte integration task does not become a feature-repair task.

Follow [parallel workstream governance](architecture/PARALLEL_WORKSTREAM_GOVERNANCE.md).
Do not mutate a frozen reviewed head, sealed package or retained receipt in
place. A needed executable/test/tool repair after freeze uses a separately
identified successor candidate within the existing authorized scope, a new
freeze and applicable re-review. If the task does not allow that successor,
request the missing authority; never silently change the admitted candidate.
External harness-only repairs preserve the product candidate identity and
record the separate harness identity and evidence.

No builder self-merge, executable conflict resolution, rebase, deployment,
provider contact, service/scheduler action, approved-environment repair or
Paper/live authority follows from this amendment.

## Required Final Reporting

Every final task report lists the following fields, including zero or
not-applicable results when no harness repair occurred:

```text
HARNESS_DEFECTS_AUTONOMOUSLY_REPAIRED
FAILED_RECEIPTS_PRESERVED
AFFECTED_GATES_RERUN
PRODUCT_BYTES_CHANGED_BY_HARNESS_REPAIRS = NO
PRODUCTION_CHANGED_BY_HARNESS_REPAIRS = NO
SECURITY_AUTHORITY_EXPANDED = NO
```

For each repair identify the defect/root cause, affected claim and tier,
failed receipt, repaired machinery identity/diff, affected-gate command/result,
retained failed/repaired evidence and parent-resumption point. Report
limitations, permitted continuation, blocked claims and recheck triggers.
Do not print NO if contrary evidence exists: report the actual boundary breach
and stop the affected progression. Keep unrelated, separately authorized
product changes distinguishable from harness repairs.

## Governance Acceptance Cases

These are policy decisions, not claims that product tests were executed.

| Case | Required decision |
| --- | --- |
| SHA text differs only in case; unchanged bytes and authority are proven | Preserve failure, repair comparison, retest that gate, resume on PASS. |
| Second or later independent harness path defect | Repeat the same loop; no repair quota or routine owner reauthorization. |
| Isolated test layout is wrong; approved interpreter/packages unchanged | Correct only in-scope layout, retain receipts, affected gate first. |
| Stale expectation contradicts an independently proven unchanged requirement | Smallest test-only correction; retain the requirement and all acceptance invariants. |
| Removing an assertion would hide a product regression | Stop; no acceptance weakening. |
| Helper serialization or qualification-only import defect with all predicates proven | Repair only the helper machinery and resume after affected-gate PASS. |
| Cleanup requires granting privilege or relaxing security policy | Stop and request fresh authority. |
| First affected-gate rerun fails for another proven harness cause | Preserve both failures, diagnose and repeat the bounded loop. |
| Repair passes; an unrelated broad suite was already valid | Resume the parent; no full rerun solely because a repair occurred. |
| Parent acceptance requires a full suite on final candidate bytes | Run that required suite; the amendment does not waive it. |
| Repair would touch a frozen test/tool candidate | Preserve it; use an authorized successor, new freeze and applicable review, or stop for missing scope. |
| Actual accepted bytes/hash, canonical contract or code authority differs | Fail closed for the affected admission; not a hash-case clerical repair. |
| Fix requires product/Science/trading semantics, architecture or production changes | Stop the affected repair; this amendment supplies no such authority. |
| Qualification needs provider/broker/account contact or Paper/live authority | Stop and request fresh authorization; no implicit contact or execution. |
| Original failure cannot be retained or root cause is unproven | Continuation predicates are unmet; no speculative harness PASS. |
| No harness defect occurred | Report zero repairs and not-applicable receipts/reruns honestly. |
