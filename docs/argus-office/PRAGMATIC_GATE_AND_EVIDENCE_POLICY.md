# Pragmatic Gate And Evidence Policy

## Authority And Scope

Authority: Steven's directive `ARGUS-PRAGMATIC-GATE-AND-EVIDENCE-POLICY-001`.
This is the project-wide gate-classification rule for future Argus work,
including Astra and other specialists. It qualifies older blanket stop,
anomaly, evidence, review, and readmission wording in operating and role docs.
Classify the affected claim and consequence before deciding what must stop.

FAIL CLOSED ON MONEY / EXECUTION / CODE AUTHORITY.
FAIL HONESTLY ON RESEARCH UNCERTAINTY.
DO NOT LET EVIDENCE PERFECTION PARALYZE PAPER-BOUND DEVELOPMENT.

This policy authorizes governance changes only. It does not alter executable
gates, source behavior, deployed configuration, scheduler/service state,
provider/account authority, or Paper/live/execution activation. Existing code
checks remain enforced until a separately scoped implementation changes them.
An inability to pass an existing executable gate is not permission to bypass it.

## Three Tiers

| Tier | Classification | Default disposition |
| --- | --- | --- |
| 1 | `TIER_1_MATERIAL`: execution, safety, account, or code authority | HARD STOP / FAIL CLOSED for the affected consequential progression. |
| 2 | `TIER_2_OPERATIONAL`: understandable operational quality defect | Record exact impact; continue DEGRADED / QUALIFIED within explicit safe bounds. |
| 3 | `TIER_3_EVIDENTIARY`: research or historical evidence quality limit | Preserve the limitation, label honestly, and continue permitted work. |

The same observation can have different consequences for different claims.
A late capture can be useful research while failing exact scheduler qualification.
Never convert a failed or UNKNOWN qualification into PASS to allow continuation.

### Tier 1: Execution / Authority Critical

Hard-stop examples include canonical/source identity contradiction, unreviewed
code entering production, wrong account/environment, Paper/live confusion,
unknown submission, possible duplicate order, corrupt risk/safety/execution
authority, stale consequential authority, ambiguous position/fill custody,
pre-epoch job replay, and restart creating new consequential authority.

Keep deterministic tests, applicable Hard Chew/full-suite validation, required
byte/hash proof, ancestry proof, authoritative independent evidence custody,
fail-closed acceptance gates, and required explicit integration/activation
authorization. Schedule pressure and convenience cannot waive these controls.
Missing evidence needed to establish Tier-1 authority remains Tier 1, even if
the file is historical or its absence first looks like a copying/timing problem.

Block the affected consequential path and preserve the evidence. Unrelated,
already-authorized work can continue when it cannot affect the blocked authority.
Do not duplicate, retry, activate, or reconcile an order through uncertainty.

### Tier 2: Operational Quality

Examples include scheduler lateness, heartbeat timing, delayed capture, service
warm-up, degraded but understandable runtime health, and noncritical monitoring
discrepancies. These do not automatically stop the whole project.

DEGRADED / QUALIFIED continuation requires all four:

- No execution authority is expanded.
- No code identity is ambiguous.
- No consequential effect can be duplicated.
- The exact limitation is explicitly recorded.

Record affected functions and claims, bounded permitted work, monitoring and
the condition that ends continuation. Escalate the affected progression only
when impact crosses into Tier 1. If consequential safety cannot be established,
do not assume the defect is harmless merely because it is called operational.

### Tier 3: Research / Evidence Quality

Examples include a capture several minutes late, missing exact historical
bytes, reconstructed rather than original payloads, incomplete redundant
custody copies, imperfect chronology, unavailable observations, historical
UNKNOWN results, or an unrecoverable prior artifact.

Preserve the original failed/missing evidence and its limitations. Label
reconstructed content as RECONSTRUCTED and absent/unprovable facts as UNKNOWN.
Continue implementation, exploratory research, and unrelated work within
their existing authority. A limitation may exclude a record from a particular
analysis or prevent a stronger scientific claim without blocking development.

Do not manufacture an original payload, backdate a result, convert a historical
sample into prospective evidence, introduce hindsight into a decision, or use
research admission as execution eligibility.

## Classification And Continuation Record

For every material finding or gate decision, record:

```text
FINDING_ID
AFFECTED_CLAIM_OR_ACTION
TIER = TIER_1_MATERIAL | TIER_2_OPERATIONAL | TIER_3_EVIDENTIARY
EVIDENCE_AND_PROVENANCE
IMPACT
LIMITATIONS
RECOMMENDED_CORRECTION
PERMITTED_CONTINUATION_AND_BOUNDS
BLOCKED_CLAIMS_OR_ACTIONS
MONITORING_OR_RECHECK_TRIGGER
OWNER
```

Apply the highest applicable tier to the affected consequence, not to every
activity in the project. An unknown historical observation alone is Tier 3;
an unknown submission or unknown source of consequential authority is Tier 1.
A benign label cannot downgrade a demonstrated authority dependency.

Only Tier 1 automatically blocks consequential progression. Tier 2 and Tier 3
findings state impact, limitations and recommended correction and allow bounded
continuation when safe. Missing proof can still prevent the specific claim it
would have supported. Do not claim a task's acceptance criteria passed when
they did not. A failed test of changed behavior requires its own bounded repair
or explicit disposition; this policy does not turn a regression into a pass.

## Capture Window Policy

Separate CAPTURE DATA VALUE from SCHEDULER OPERATIONAL QUALIFICATION.
An out-of-window capture may be admitted for market research, candidate
analysis, Science, or momentum characterization with its actual limitations.

Record `TARGET_TIME`, `ACTUAL_TIME`, signed `DELTA = ACTUAL_TIME - TARGET_TIME`,
and `CAPTURE_CLASSIFICATION`. Preserve timezone/offset, trading-session
identity, time provenance, and the policy/tolerance version used. Distinguish
capture/observation time from later receipt or report-generation time.

Configurable classifications may include `EXACT`, `NEAR_WINDOW`, `LATE`, and
`POST_OPEN`. Exact tolerance values, session/calendar inputs, boundary
inclusivity and class precedence are configuration/policy inputs. This directive
sets no numerical tolerances and adds no date-specific source conditions.
If timing or its classification inputs cannot be proven, retain known fields
and mark the unresolved timing/classification UNKNOWN.

A several-minutes-late Opening capture can retain research value. It does not
prove that Automation fired exactly on schedule, exact-opening microstructure
was observed, or scheduler qualification passed. Preserve both truths in
separate findings/fields; research admission never overwrites the scheduler
result or changes an execution-freshness rule.

## UNKNOWN Evidence Policy

UNKNOWN is a valid terminal classification when historical fact cannot be
proven. State what was sought, the available evidence, the gap and the affected
claims. End unproductive reconstruction with that honest result; new evidence
may support a separately recorded reassessment.

UNKNOWN alone does not block unrelated implementation. If the unknown fact is
required for Tier-1 authority, the affected consequential progression remains
fail closed. No historical recovery is required solely to turn an unrelated
UNKNOWN into a cosmetically complete report.

## Redundant Custody

An additional-copy failure does not invalidate independently proven authoritative
primary custody. Record both `PRIMARY CUSTODY VALID` and
`REDUNDANT COPY INCOMPLETE`, identify the missing copy and its purpose, and
continue permitted work. Do not assert either label without evidence.

If the missing copy is itself a required Tier-1 authority source, or primary
custody/identity/integrity is unproven, retain the affected authority stop.
An independently required second-eye/custody artifact is not redundant merely
because another file with similar contents exists.

## Canonical Readmission

For a dependent read-only lane after a proven accepted canonical fast-forward:

1. Verify the old and new canonical SHAs, accepted integration evidence and
   ancestry. A branch label or a moving HEAD alone is not proof.
2. Verify the declared relevant input hashes and dependency/contract closure,
   including relevant policy/configuration inputs. Record any overlap and its
   effect on the retained claims.
3. If relevant inputs and authority remain valid, append a readmission record,
   READMIT, and CONTINUE. Preserve the original base, frozen candidate, artifact
   identities and original findings; do not relabel old evidence as a new run.
4. Stop/revalidate the affected portion for material overlapping source/input
   changes or a Tier-1 identity/authority contradiction. Preserve unaffected
   completed work and continue independent authorized portions.

Readmission records bind original task/base/candidate, old/new canonical,
ancestry/integration proof, relevant input paths and hashes, impact assessment,
retained/excluded claims and disposition. Unproven ancestry or ambiguous
relevant identity cannot be treated as a proven accepted fast-forward.

This rule permits reuse of valid read-only work, not a rebase, an in-place
candidate edit, a merge of newer master into a frozen task, or an automatic
canonical integration/activation. Changed implementation candidates still need
a new freeze and applicable review through the serialized Integration Steward.

## Date / Time Policy

Specific dates in directives are operational targets or test fixtures unless
explicitly stated otherwise. They are not product constants. Advancing the
trading session/date must not require source edits.

Use declared configuration/policy inputs for schedules, trading calendars,
timezones, tolerances and prospective epochs. Explicit safety cutoffs, fixed
contractual requirements and activation conditions remain binding until changed
by applicable authority; calendar rollover or restart cannot create authority
or replay pre-epoch jobs. Historical records retain their actual original dates.

## Astra Review And Paper Entry

Astra and other reviewers classify each finding with the three exact tier
labels above. Report facts separately from inferences and missing proof.
Review a frozen candidate without modifying it, keep author/reviewer identities
distinct, and ground acceptance claims in reproducible evidence. Tier 2/3
limitations qualify claims and permitted continuation; they do not become
blanket project stops. Tier-1 contradictions or missing authority proof remain
fail closed. An Astra ACCEPT is advisory, not merge/deployment/activation approval.

Paper exists partly to expose operational fuzziness safely. Paper entry still
requires all Tier-1 execution, identity, account, mode, safety and applicable
authorization gates. Tier-2 imperfections may be accepted with explicit bounds
and monitoring. Tier-3 imperfections may be documented without blocking Paper.
This policy alone does not arm Paper, submit an order, establish an account,
change risk limits, or expand live/execution authority.

## Policy Acceptance Cases

These are governance decision cases, not claims that executable behavior changed.

| Case | Required disposition |
| --- | --- |
| Known several-minutes-late capture, sound identity, research only | Tier 3 for research quality; retain value and actual times. Scheduler timing separately Tier 2; no exact-window PASS. |
| Warm-up delay, sound identity, no orders/authority expansion/duplicate effects | Tier 2; record bounds and monitoring, continue qualified work. |
| Stale heartbeat that leaves consequential authority freshness unproven | Tier 1 for that authority; fail closed. |
| Historical exact payload unrecoverable | Tier 3 terminal UNKNOWN; continue unrelated implementation. |
| Reconstructed historical payload | Tier 3 RECONSTRUCTED; no original-byte or prospective claim. |
| Submission outcome unknown or possible duplicate order | Tier 1; no consequential retry through uncertainty. |
| Primary custody independently valid, optional copy missing | Tier 3; primary valid plus redundant copy incomplete. |
| Missing copy is required independent authority/custody proof | Tier 1 for acceptance depending on it. |
| Proven accepted fast-forward, relevant read-only input hashes unchanged | Verify, append readmission, continue; no candidate mutation. |
| Canonical movement materially changes a consumed execution contract | Stop/revalidate affected claims; preserve independent work. |
| Wrong account, Paper/live confusion, or corrupt risk authority | Tier 1 regardless of schedule or research value. |
| Date advances with no new activation authority | Use declared session inputs; do not invent a new epoch or replay old jobs. |
| Timing tolerance or time provenance unavailable | Timing/classification UNKNOWN; no fabricated EXACT/scheduler PASS. |
| Paper candidate has bounded noncritical lag and incomplete unrelated history | Tier 2/3 can be documented; every Tier-1 gate and separate activation authority still required. |

## Existing Gates And Follow-Up

Apply the classification to current operating/review decisions immediately.
An executable check that needs different behavior requires a separately scoped
implementation and its normal proof; keep its current result intact meanwhile.
Historical reports retain the verdict and evidence they originally recorded.

The following mapping was checked against canonical source at
`c596c80324d24e01b32b7efecda83e362b9ae1cf`; it is not a declaration that any
particular production incident or redundant-copy failure occurred.

| Existing gate / source | Classification and retained boundary | Future implementation, if authorized |
| --- | --- | --- |
| `momentum_hunter/automation_supervisor.py` out-of-window `MISSED` launch disposition | Tier 2 scheduler outcome; Tier 3 timing limit on an independently available capture. Keep MISSED and no exact-opening claim. | Separate capture research admission from scheduler qualification; do not permit late launches/retries by reinterpretation. |
| `momentum_hunter/automation_preopen_guardian.py` heartbeat/window checks aggregated into `RED_NOT_READY` | Known noncritical lag/warm-up is Tier 2; runtime identity, compatible receipts, safe epochs and consequential freshness remain Tier 1. | Expose per-claim tier and bounded degraded work; do not replace RED with GREEN or bypass an executable gate in this policy task. |
| Guardian `CANONICAL_EXPECTED`; parallel frozen-base policy | Verify accepted fast-forward and relevant hashes to readmit dependent read-only work. Exact code/runtime identity required for authority remains Tier 1. | A separate code task may implement read-only admission semantics; policy readmission alone does not satisfy Guardian's current exact-head predicate. |
| `docs/storage-map.md` historical UNKNOWN and `momentum_hunter/automation_state_recovery.py` `legacyHistory=UNKNOWN` | Tier 3 for research/history; keep statistical exclusions and truthful chronology. Recovery state/epoch/source hashes, retained execution claims and pre-epoch suppression remain Tier 1. | No need to recover every historical byte before unrelated work. Any recovery behavior change remains separately scoped. |
| Parallel review-package custody | Proven primary custody plus missing optional copy is Tier 3. Required independent review/authority custody is not an optional copy. | Record primary identity and redundant-copy limitation separately; never waive required source/package proof. |
| Roadmap `NATURAL_RUNTIME_AND_INSTRUMENT_AUTHORITY_REQUIRED` Paper gate | Split research-canary quality into Tier 2/3 where safe. Instrument/account/mode authority, reviewed code, risk/order custody, disabled-install proof and separate arming remain Tier 1. | Audit each prerequisite by its claim; do not declare Paper ready or armed from this reclassification. |
| `automation_opening_capture.py` fixed five-minute late window; `automation_state_recovery.py` fixed `08:35/-05:00` epoch construction | Tolerance/calendar/session inputs belong in policy/configuration. A consequential epoch boundary remains Tier 1. | Parameterize through a separately authorized source task with timezone/calendar and restart/replay proof; no values or source bytes change here. |

The leading Roadmap snapshot predates four Automation source commits already
on canonical. Record the actual Git lineage in the Integration Steward's
closeout. These reads establish source identity, not historical acceptance or
installed/deployed readiness. If later consequential work needs that authority,
its missing proof is Tier 1 for that work; it does not block this isolated
documentation policy change or certify the prior commits by implication.
