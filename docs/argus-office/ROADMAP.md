# Momentum Hunter Roadmap

## Authority

This is the single authoritative view of current product position, active work, and next work. Update its `Now` section from Git evidence before a task is reported complete, merged, or blocked.

Supporting records have narrower roles:

- `BRANCH_LEDGER.md` is the detailed Git and branch-evidence record.
- `VERIFICATION_QUEUE.md` is the exact deferred Steven-check list; it does not replace Roadmap state or authorize merges.
- `TASK_LOG.md` and `CHANGELOG_ARGUS.md` are append-only history.
- Routine opening captures are indexed by their ignored, date-partitioned operational evidence: the terminal service receipt in `C:\ProgramData\MomentumHunter\Automation\state\automation-service-state.json`, `MomentumHunterData/data/captures/<DATE>/opening.*`, `MomentumHunterData/logs/capture-opening-<DATE>-*.log`, and `MomentumHunterData/data/reports/*-<DATE>-opening.*`. These generated records preserve routine capture truth without changing canonical Git identity.
- Historical architecture notes and release reports remain evidence of their original decisions; they do not override this Roadmap.

## Delegated Authority And Interruption Policy

Steven delegates routine nonvisual execution to Codex. Do the work, prove it, integrate it, and back it up without asking Steven to approve an expected result.

Standing authorization includes bounded nonvisual implementation, tests, documentation, read-only external calls, OAuth refresh, expected single-account validation and encrypted immutable binding, deterministic evidence collection, exact confirmation phrases after preconditions pass, task branches, commits, clean fast-forward merges, and non-force pushes.

Steven remains the decision-maker for:

- GUI, layout, interaction, icon, and other visual acceptance.
- Unexpected brokerage state: account count other than one, ending other than `2573`, type other than `CASH`, changed hash, unexpected positions or trading permissions, broader authorization scope, or any condition that could expose another account to reads or future trades.
- Real order transmission, replacement, or cancellation; unattended-live enablement; money movement; destructive data deletion; database migration; credential revocation/rotation/deletion; provider-app deactivation/deletion; paid services; or ambiguous protected-domain semantics.
- Unsafe Git operations: reset, rebase, branch deletion, force-push, non-fast-forward merge, or remote-divergence resolution.

When an anomaly occurs, stop before the consequential action and ask Steven one concrete question that explains the observed state and practical exposure. A software confirmation phrase is an internal interlock, not a recurring CEO approval request.

## Now

The August 14 operational gate is terminal and preserved. The 05:55 Central
Schwab boundary checkpoint was `USEFUL_WITH_LIMITATIONS`; the 06:05 checkpoint
was `HIGH_FIDELITY` for SPY, QQQ, and NVDA. The 07:00 capture received and
parsed all 20 Finviz rows and truthfully qualified zero. The 08:35 opening
capture received and parsed all 20 rows, qualified SNDK and NU, and completed
canonical candle readiness with five opening bars and seven baseline sessions
for both symbols. The dependent Canary Alpaca Paper cycle reached actual
candidate-level strategy logic and terminated `NO_TRADE` without creating an
order. SNDK was below its entry trigger; NU was a missed/reclaim setup with
insufficient execution reward/risk.

The post-August-14 reconciliation is complete on synchronized local and remote
`master`. It integrates SETUP-001/002, PAPER-005, DATA-008,
SESSION-FIDELITY-008, AFTER-CLOSE-001/002, Phase 13R, and the SNDK stop-
authority repair. The SNDK issue was a stale cross-contract equality check:
the completed-Daily invalidation was `$1,331.58` and the valid tighter
same-session TradePlan stop was `$1,565.00`. Current code accepts a tighter
long stop and still fails closed if a plan allows loss below Daily
invalidation. All 2,004 reconciliation tests passed before integration.

ARGUS-SETUP-002A adds the separate unattended activation boundary for the
already-integrated offline successor-setup observer. Its immutable activation
record starts an empty prospective denominator on the first eligible session,
Monday August 17, 2026. Pass 1 depends on the same-date opening capture and is
evaluated before Paper at the fixed 09:35 ET cutoff. Pass 2 depends on the
exact Pass 1 packet and runs after the regular-session outcome horizon. Both
jobs are write-once, exact-head pinned, finite, zero-retry, and isolated: a
research failure cannot change the opening or Paper receipt and cannot invoke
a provider, account, position, broker, order, Shadow, Engine Host, or UI path.

The remaining 20 opening captures and the August 17 Canary Paper engineering
job remain pending under the exact canonical identity. The automation service
is Automatic and healthy, zero Shadow jobs are enabled, and real/live order
transmission remains unavailable. SETUP-002 is silent research only and does
not alter candidate admission, scoring, TradePlan, Risk Governor, allocation,
Paper selection, or the official Paper sample.

Next operational evidence is the August 17 opening/Paper result plus the two
SETUP-002 research receipts. A valid Pass 1 may still abstain for insufficient
history, and a valid Pass 2 may classify no successor setup; neither is a
production failure. After the first terminal pair, verify denominator count,
provider-bound exclusions, cutoff hashes, outcome separation, and production
nonmutation before extending unattended collection. R034 legacy-candle
deletion remains separately approval-gated. Routine successful captures stay
in append-only operational evidence and do not trigger daily Roadmap commits.

The approved long-term direction remains Phase 13R specialist intelligence,
with the current Momentum/Paper path preserved as the prospective baseline.
Specialist runtime authority and strategy activation remain future gates.

ARGUS-RESEARCH-INTEGRATION-001 is the active isolated preflight branch. It
combines SPECIALIST-CONTRACT-001, RESEARCH-DATA-001/002, RESEARCH-GOV-001,
STAT-DATA-001, REGIME-002, EXEC-QUALITY-001, EVENT-SHOCK-001,
TECH-STRUCTURE-002, and EXIT-RESEARCH-001 from frozen canonical base
`ea056155`. Every implementation module remains byte-identical to its source
branch. No production module imports the stack, and no producer, persistence,
activation, arbiter, provider, account, broker/order, service, scheduler,
Engine Host, WPF, Paper, or Shadow authority has been added.

The code and tests compose without source conflicts. The rehearsal identified
one bounded integration-debt class: all sibling branches edited the same five
governance ledgers and several independently reused risk IDs `R-083`, `R-086`,
or `R-087`. This branch preserves the unique artifacts, consolidates the
shared records once, and assigns unique combined risk IDs. The intended later
integration order is common contract; DATA-001 then DATA-002; research
governance; denominator; then the four market-intelligence specialists and
exit specialist. No canonical integration occurs before the August 17 opening,
Paper, and SETUP-002 receipts are terminal and preserved.

After August 17, reconcile current canonical head against this preflight,
re-run Hard Chew, and perform one deliberate integration and one operational
repin if all gates pass. STAT-DATA-002 producer wiring remains the next
activation-enabling data task; specialist producer wiring, prospective samples,
combination, calibration, and strategy authority remain separately gated.

On branch `codex/ARGUS-SPECIALIST-CONTRACT-001-common-opinion-contract`, the
first Phase 13R implementation slice is `IMPLEMENTED_PENDING_INTEGRATION` from
canonical base `ea05615`. It adds only the immutable provider-neutral common
opinion contract and tests. It is not imported by the runtime, has no arbiter,
provider, broker, storage, scheduler, service, Engine Host, WPF, Paper, Shadow,
or order capability, and does not alter the August 17 lane. Canonical `master`
and the installed runtime remain unchanged until a later clean integration.

ARGUS-RESEARCH-DATA-001 is implemented on
`codex/ARGUS-RESEARCH-DATA-001-data-inventory` and remains
`IMPLEMENTED_PENDING_MERGE`. Its read-only inventory found 38,286 canonical
Schwab minute bars across 7 symbols and 17 session dates, 1,764 canonical
Schwab Daily bars across the same 7 symbols, and 79,298 research-only adjusted
Daily rows across 263 symbols. The broader Daily cache is useful for bounded
research but is not canonical or survivor-safe: all inspected histories are
ticker-keyed and lack stable security identity, symbol-change/delisting
history, point-in-time membership, and corporate-action transformation
lineage. Daily technical-pattern and rank/setup-outcome uses are `PARTIAL`;
the other evaluated historical-statistical uses are `INSUFFICIENT`.

No new data provider is selected or recommended. The next research-data work
closes durable security identity and corporate-action price-basis lineage on
`codex/ARGUS-RESEARCH-DATA-002-security-action-basis`. The implementation is
`IMPLEMENTED_PENDING_MERGE`: point-in-time aliases, inactive/delisted states,
forward/reverse split and symbol-change actions, explicit price bases,
immutable transformation lineage, survivorship assessment, and fail-closed
research admission are implemented and focused tests pass. The actual DATA-001
compatibility matrix remains conservative: all five sources are ticker-keyed,
price basis is `UNKNOWN`, point-in-time universe capability is `INSUFFICIENT`,
and survivorship status is `UNCONTROLLED`.

No provider is procured or selected. Durable identity/action and historical
membership are demonstrated gaps that may eventually require another source,
but existing Schwab evidence and prospective collection remain preferred until
the recorded exit conditions fail. After merge reconciliation, the next
research-data task is `ARGUS-STAT-DATA-001`, the prospective opportunity
denominator. The August 17 installed runtime and operational jobs remain pinned
to canonical `master` and are unchanged by this stacked research branch.

Branch-local continuous development is active without changing that operational
baseline. `CONT-RUNTIME-001` is preserved at `fd04452` with its narrow ordered
`EvidenceWriteIntent` boundary. `WRITER-TOPOLOGY-002` is implemented on
`codex/ARGUS-WRITER-TOPOLOGY-002-dedicated-evidence-writer` from that exact
parent and reconciles the earlier topology conflict in favor of a dedicated,
credential-free evidence writer. Topology v1 remains readable and unchanged;
topology v2 makes Engine Host and WPF read-only, uses authenticated bounded IPC,
and stores immutable sharded intent records rather than rewriting a full-day
ledger. The branch is dormant and unmerged, no writer is installed, and no
continuous runtime is activated.

`CONTINUOUS-WINDOWS-ISOLATION-001` is implemented on the separate branch
`codex/ARGUS-CONTINUOUS-WINDOWS-ISOLATION-001-physical-proof` from writer
topology head `39bd45b`. The corrected physical run against disposable roots
proved that a dedicated `LOCAL SERVICE` writer can read, create, overwrite,
append, rename, and delete evidence under its protected root while the
medium-integrity current-user WPF/Engine-Host equivalent can read but cannot
perform any tested mutation, ACL/ownership change, junction creation, or
LocalService handle duplication. A high-integrity local administrator can
change ACLs, create a junction, duplicate the writer handle, and regain write
access; no administrator-resistance claim is made.

The same campaign also proved that same-SID processes can mutate committed
evidence, duplicate and read a capability handle, and interfere with the
partial-file path. Two physical writer processes both accepted sequence 1.
Explicit handle allowlisting, IPC authentication/replay rejection, capability
regeneration, and crash/restart idempotency passed. The dedicated-principal ACL
boundary is therefore accepted, but physical single-writer exclusion and
reparse-resistant persistence remain failed activation gates.

The final corrected report is preserved outside Git at
`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\CONTINUOUS-WINDOWS-ISOLATION-001\CONTINUOUS-WINDOWS-ISOLATION-001-20260816T153118Z-aea37c6df81942ff.json`
with SHA-256
`B07DD7D76159EFADDF22B9EF80EF0ABD9CBCE6ED8231761E498ACDFADD12503E`.
Current branch classification is
`PHYSICAL_PROOF_COMPLETE_ARCHITECTURE_HARDENING_REQUIRED`; no merge,
installation, service change, scheduler change, or activation is eligible.
The next architecture slice must retain the dedicated non-admin writer
principal and add OS-level single-writer exclusion plus reparse-resistant
temp/final operations, followed by a complete physical attack-matrix rerun.

## Integrated Work History

ARGUS-SETUP-002 prospective successor-setup research is integrated on canonical
`master` through the post-August-14 reconciliation. Its original implementation
commit `a676cd6` remains preserved on
`codex/ARGUS-SETUP-002-prospective-successor-observer`; SETUP-002A supplies the
separate prospective activation record and unattended research-only schedule.
The prospective sample identity is `successor-setup-research-20260813-v1` with
policy fingerprint `C2A214A12E6BE8A42BC868AD3A4F90998721F5DE652FB748012546170C95B943`.
It starts at zero sessions and zero candidates; all five SETUP-001 candidates
remain case-study evidence and are excluded from the denominator.

The offline observer preserves the complete opening-candidate denominator and
the production Momentum/Paper result as the control, evaluates at most five
candidates by canonical rank, and records every unevaluated row as
`NOT_EVALUATED_PROVIDER_BOUND`. Its immutable Pass 1 contains only completed
canonical Schwab bars before 09:35 ET, the completed 09:15-09:29 structure, the
09:30-09:34 opening range, Model A/B/C comparisons, raw verticality covariates,
broad-market context, original lifecycle, and a separately identified
continuation, pullback, reclaim, or no-structure opinion. The existing 0.25%
extension and 1.5 execution-R/R rules are frozen; no research opinion has
execution authority.

A separate Pass 2 validates the frozen decision and cutoff evidence before
classifying `UNTRIGGERED`, `TARGET_FIRST`, `STOP_FIRST`, `TIMEOUT`,
`INVALIDATED`, `AMBIGUOUS_SAME_BAR`, or `DATA_FAILURE`. MFE/MAE terminate with
the hypothetical lifecycle. Rejected candidates receive visibly separate
post-decision counterfactual observations that cannot rewrite Pass 1. Exact
duplicate writes are idempotent; conflicting writes, tampered packets, changed
cutoff candles, wrong symbols, and wrong session dates fail closed.

SETUP-002A activates SETUP-002 prospectively from an empty denominator on
August 17. Its two research jobs have zero retries and finite timeouts, and a
research failure cannot change opening or Paper status. The immutable Aug. 14
checkpoint/opening/Paper evidence remains preserved under its original Git
identity; activation creates no retrospective candidate or outcome.

Hard Chew proof passes compileall, 25 focused SETUP-002 tests, 37 combined
SETUP-001/002 tests, 134 affected setup/TradePlan/candle/continuous-plan
regressions, and all 1,961 Python tests. The remaining evidence limitation is
unchanged: the current trusted Schwab history normally begins near 07:00 ET,
so the true 04:00-07:00 path is recorded as `UNOBSERVED` rather than inferred.

ARGUS-SETUP-001 premarket structure and fresh-setup research is integrated on
canonical `master` through the post-August-14 reconciliation. Original feature
commit `6919b03` remains preserved on
`codex/ARGUS-SETUP-001-premarket-structure`. A deterministic two-pass tool
reconstructed the actual
August 13 CRWV/NBIS/IREN/HPE/SMCI decision using only evidence at or before the
09:35:38 ET quote cutoff, froze decision fingerprint
`9C2F2AB10FA2BF97BB4854286DFA692142BD993DD80EF7E2526329A5C778FF5E`,
then separately measured later outcomes. Schwab history used for structure was
received after the session and is explicitly
`RETROSPECTIVE_CANONICAL_HISTORY_RESEARCH_ONLY`; the actual morning runtime had
no August 13 canonical candles and the returned premarket path begins at 07:00
ET.

Hard-chew self-review preserved that original outcome-blind packet and added a
separate conservative adjudication at fingerprint
`618345BBF1B731EEF7FAF49435F123AA0BDBFD21CAF2EC65F9AABF4894A7CDAA`.
CRWV's completed 09:34 bar crossed the original trigger before the decision, so
its original setup is immutable missed despite the later ask sitting one cent
below the trigger. The correction added no allowed setup and did not alter
IREN's frozen decision or Pass 2 outcome. This adjudication is explicitly
post-outcome self-review; only fingerprint `9C2F2AB...` is the original
outcome-blind Pass 1.

The case study does not justify loosening the existing 0.25% extension rule.
NBIS, HPE, and SMCI had missed original setups without a defensible successor;
CRWV remained indeterminate because the real runtime lacked the required
candles. Only IREN produced a potential distinct `CONTINUATION_BREAKOUT` under
the frozen exploratory full-structure model: trigger `$47.01`, stop `$45.38`,
target `$50.27`, ask extension `0.0638%`, and execution-adjusted reward/risk
`1.9458`. In outcome-blind Pass 1 that was a research allow; Pass 2 showed a
`+4.5599%` MFE followed by a stop at 12:07 ET, so it is not evidence of a
profitable missed trade. SMCI's later rally is preserved only as a post-decision
market observation because no valid setup was frozen at the cutoff.

No production setup, TradePlan, scoring, ranking, Risk Governor, Paper, broker,
scheduler, service, candle-store, or UI behavior changed. Tomorrow's canonical
opening and dependent Paper jobs remain outside this worktree and must continue
on their existing exact identity. The recommended successor collector is now
implemented by SETUP-002 on a separate stacked branch, but remains unmerged,
uninstalled, unscheduled, and empty until the August 14 operational evidence
and separate activation gate are preserved. Production thresholds remain
blocked on a larger outcome-blind sample.

Hard Chew proof passes compileall, 12 focused research tests, 143 adjacent
setup/TradePlan/candle regressions, and all 1,936 Python tests. The research
loader fails closed on legacy mixing and source, session, timestamp,
minute-identity, or final-history contradictions.

ARGUS-DATA-009 opening candle readiness is `COMPLETE` in canonical `master`.
Implementation commit `ded2929` was fast-forwarded from
`codex/ARGUS-DATA-009-opening-candle-readiness` on synchronized base `9d735dd`;
the final canonical closeout identity is the commit containing this statement.
The installed service manifest is bound to that exact identity for 21 opening
jobs from August 14 through September 14 and the dependent August 14 Paper job.
Readback requires both next jobs `PENDING`, zero running jobs, zero enabled
Shadow jobs, and order transmission `UNAVAILABLE`. The August 13 opening capture
itself completed successfully with 20
raw Finviz rows, 20 parsed rows, five qualified candidates, and five persisted
candidate rows. Its immutable capture SHA-256 is
`86A13ABE8627DC9B00FA21365A1297C4DF334B14C799784BB2EF1890BD1AF5C9`; the
derived TradePlan report SHA-256 is
`A9903C5725E16755B6FEDB772CB449A38AB1F72199C8715AB183E37C91CB0870`.
The dependent Paper result is classified `NO_TRADE - EXECUTION EVIDENCE
UNAVAILABLE`, not a complete strategy rejection: the opening planner had no
authoritative current-window or baseline candle evidence. Independent review
found no basis to claim a missed valid trade. The preserved quote-only report
treated CRWV as below its trigger; retrospective research later showed the
09:34 candle had crossed before decision, but the actual runtime did not possess
that bar. NBIS, IREN, HPE, and SMCI were extended and/or below execution
reward/risk policy, with unresolved catalyst authority present on some rows.

DATA-009 composes the existing R032B/R032C Schwab history path, DATA-002
time-normalized RVOL, DATA-004 same-session TradePlan, and A004 Paper lane. For
the deduplicated top-five opening universe it inspects the canonical store,
performs at most three candidate-only guarded history passes, waits 10 then 25
seconds across the observed R031B two-to-28-second post-close arrival window,
and requires all 09:30 through 09:34 ET price-history-backed bars plus at least
five comparable baseline sessions. Only terminal canonical states are accepted.
Timeout, provider/backfill failure, insufficient baseline, partial current
window, wrong symbol/session, stale evidence, or tampered storage remain
explicitly execution-ineligible. The report persists the readiness record, and
Paper stops before quote/account/order work with
`CANONICAL_CANDLE_READINESS_TIMEOUT` or the exact failure status. No provisional
bar, legacy RVOL, source mutation, Shadow action, or order fabrication is
allowed.

The Paper chronology repair now separates `decisionStartedAt`, quote request and
receipt evidence, account/portfolio acquisition, `evidenceAcquiredAt`, and the
final frozen `decisionAt`. Report freshness is checked both at cycle start and
again after all evidence is acquired, so a quote created after cycle start is
not falsely future-dated and a report that ages out during collection cannot
submit an order. Compileall and 76 focused tests pass; 131 adjacent candle,
TradePlan, allocation, Shadow, and automation tests pass; and all 50 safe
bounded backend/evidence/storage modules pass without failure or timeout. Full
unittest discovery exceeded its explicit ten-minute bound without a result and
is not claimed as a pass. No live provider, account, position, or order call was
made by this repair verification.

ARGUS-PAPER-005 is integrated on canonical `master` through the
post-August-14 reconciliation; its original branch is
`codex/ARGUS-PAPER-005-protection-post-fill-hardening`. It recalculates
actual dollar risk, reward/risk, and entry extension from Alpaca Paper's
confirmed fill and broker position before protection; a failed post-fill check
forces the current Paper position flat. New and recovered protective stops must
match the exact current broker position quantity and frozen stop price, and the
active supervisor rechecks that invariant before reporting `POSITION_WORKING`.
Any mismatch cancels the owned stop where possible and flattens only the current
confirmed Paper position.
ARGUS-AFTER-CLOSE-002 is integrated on canonical `master` through the
post-August-14 reconciliation; its original isolated branch is
`codex/ARGUS-AFTER-CLOSE-002-real-regular-replay-trace`, based on
AFTER-CLOSE-001 commit `e593131`. A new offline replay consumed a preserved
July 29 SPY Schwab quote, five canonical 09:30-09:34 ET price-history bars, the
matching July 28 baseline bars, and the July 28 completed Daily candle. It
preserved `ORIGINAL_MARKET_TIME` separately from `REPLAY_EVALUATION_TIME`,
verified all four inputs stayed byte-identical, and made zero provider calls.

The requested real-evidence path is honestly `PARTIAL`: DATA-004 produced a
plan from the canonical Daily high/low and opening bars, but the preserved ask
was `$740.05` versus the normalized `$742.79` breakout entry. Paper Risk
Governor therefore returned only `PAPER_ENTRY_TRIGGER_NOT_REACHED`; DATA-005B
allocation and order serialization were not reached. Synthetic crossing tests
separately prove those downstream contracts, including fill-dependent
protective quantity and the zero-call broker boundary. They are not historical
evidence. The older identity `test-only:canonical-regular-session-replay`
remains unchanged but is adjudicated as meaning
`TEST_ONLY_CONSTRUCTED_REGULAR_SESSION_FIXTURE`; the real replay identity is
`TEST_ONLY_REAL_PRESERVED_SCHWAB_REGULAR_SESSION_REPLAY`.

Final replay fingerprint is
`3557A3FCF32BC613345C28941F814CB0007022F35A97C76929114B4FEFC35E79`.
Compileall, 69 focused/adjacent tests, and all 1,921 Python tests pass. No
canonical runtime, scheduler, service, Paper/Shadow state, opening evidence, or
production store changed. Do not merge before the August 13 pinned opening and
dependent Paper evidence are terminal and preserved.

ARGUS-AFTER-CLOSE-001 is integrated on canonical `master` through the
post-August-14 reconciliation; its original isolated branch is
`codex/ARGUS-AFTER-CLOSE-001-contract-transaction-trace` from historical
canonical head `9d735dd`. The final write-once diagnostic packet fingerprint is
`D5DF05A91BFB3630C16F377C7CE1E56CCFCAE3B9CD285DD8031EB69FB2BDAE2E`.
One bounded live trace observed the exact Finviz headers `No., Ticker, Company,
Sector, Industry, Market Cap, Float, ATR, Rel Volume, Volume, Price, Change %`,
parsed all 20 rows, and produced nine local qualifiers. GET-only Schwab quote
and price-history evidence mapped the current quote/OHLCV contracts for
diagnostic candidate `SPCX` plus SPY/QQQ/IWM; all candle invariants passed.
SPY/QQQ after-hours quotes older than the 30-second diagnostic threshold were
reported as stale and were never promoted to regular-session authority.

The stored Schwab refresh grant first returned HTTP 400. Interactive OAuth was
renewed, then read-only validation proved exactly one authorized `2573` `CASH`
account with no positions requested and transmission unavailable. One exact
Alpaca Paper `/v2/account` GET returned an active, usable, unblocked Paper
account. A deterministic TEST_ONLY regular-session replay then traversed
candidate, DATA-004 TradePlan, Paper Risk Governor, fresh account/allocation,
fractional entry, protective stop, restart identity, and emergency-flatten
serialization to `DRY_RUN_READY_FOR_PROVIDER_SUBMISSION`. Instrumentation
recorded 11 GETs and zero submit/cancel/replace calls. The canonical checkout,
installed service, active Paper/Shadow evidence, and automation manifest hash
`98851F1ADB8FCDFCF4EF6F11D447913AC729F25F8D0C32F81DBC3D5FC9035F61`
remained unchanged. Compileall, 159 focused/adjacent tests, and all 1,916 Python
tests pass. Do not merge before the August 13 pinned opening and dependent
Paper evidence are terminal and preserved.

ARGUS-DATA-007A corrects the causal certainty of the DATA-007 zero-candidate
adjudication without changing its operational conclusion. The August 7, 10,
11, and 12 decisions remain `INVALID / SYSTEM_DATA_CONTRACT_FAILURE /
DECISION_NOT_REACHED`; none is a legitimate strategy `NO_TRADE`. Provider
schema drift is now a separate root-cause candidate rather than a confirmed
failure label. August 7, 10, and 11 are `ROOT_CAUSE_INFERRED`; August 12 is
`ROOT_CAUSE_STRONGLY_CORROBORATED` because the same-day nonpersisting A/B proof
reproduced the `Change` to `Change %` mechanism. Every case explicitly records
`rootCauseConfirmed: false` because the exact 08:35 raw provider payloads and
row counts were not preserved.

The write-once correction fingerprint is
`FCA70F321855FD3AC538779EB8E4AB85B49A64B179232B96753B99A1C35D9450`.
It binds the same capture, opening-log, TradePlan-report, parser-head, and Paper
decision hashes and supersedes only the causal certainty in original DATA-007
fingerprint `EDE1872069F4509383DD747A2006D9CB209876A53669371D465ED518BE72FBCE`.
Source-hash verification proved every original artifact remained byte-identical;
no count, candidate, decision, trade, or Paper lifecycle was reconstructed.
Failure classification and root-cause attribution are separate evidence-model
concepts prospectively.

Paper engineering sample `alpaca-paper-engineering-20260810-v1` is preserved in
the write-once archive under its original historical closure label. Its two
zero-candidate decisions are bound by cycle ID and fingerprint to DATA-007 and
do not count toward any sample. Prospective sample
`alpaca-paper-engineering-20260813-v2` is active with unchanged policy values,
zero intents, zero active lifecycle records, zero provider calls, and zero
orders during rollover. The rollover fails closed on mismatched decisions,
existing archives, active intents/lifecycles, or invalid adjudication, and it
restores the original sample if replacement activation fails. Compileall, 31
focused tests, and all 1,907 Python tests pass.

ARGUS-QUALITY-003 contract-drift hardening is integrated on canonical `master`
through implementation commit `dac486c`. The audit expanded DATA-006 from a
single Finviz alias repair into three enforced boundaries. Finviz screener
parsing now requires the complete ordered schema, normalizes only explicitly
known aliases, fingerprints the canonical schema, records raw/parsed/qualifying
row counts, and rejects missing, reordered, duplicated, malformed, or
width-mismatched data instead of manufacturing plausible zero values. Opening
capture logs include the successful contract fingerprint and counts; a
deterministic contract-drift failure is terminal and cannot be disguised by
infrastructure retries or candidate/report creation.

The WPF production XAML now has a reflection-backed binding-contract test that
walks root, nested, collection-item, and template binding paths against their
actual view models. Programmatic bindings must use `nameof(...)`, so ordinary
property renames fail compilation or tests rather than producing an empty
control at runtime. No XAML, layout, label, styling, or other visible UI behavior
changed. The Python Engine Host boundary now rejects missing, renamed, or
unexpected endpoint/response fields, models the runtime build hash, selector-arm
schema, and active-position-marking evidence that .NET previously ignored, and
has mutation tests for representative root and nested renames. A shutdown test
race was also corrected by waiting for both endpoint and lock-file cleanup.

Hard Chew proof passed compileall; 49 final focused provider/capture tests; 3
production-XAML contract tests; 9 final Engine Host wire/integration tests; all
1,898 Python tests; and all 259 .NET tests. A nonpersisting live Finviz proof
parsed all 20 current rows and produced 13 qualifying candidates under schema
fingerprint `0ca3f6ee7bc3e9cab5942549f1b9bc4694d8db6d1968d759640aca47e7b7fea3`.
Whitespace, credential, and protected-path reviews passed. No scoring,
readiness, TradePlan, Risk Governor, broker/order, database/schema, production
data, scheduler, or visible UI semantics changed. Structural drift now fails
closed; a provider returning structurally valid but economically implausible
values remains a separate data-quality risk for future plausibility and
cross-source monitoring.

ARGUS-DATA-006 closes the Finviz screener schema-drift mechanism discovered on
August 12. The 08:35 scheduler, clock proof, artifact writes, and dependent
Paper handoff completed, but the capture was not a trustworthy market
observation and its exact raw Finviz response was not preserved. A later
same-day nonpersisting proof observed the current `Change %` header and showed
that the old `Change`-only parser returned zero while the corrected parser
returned qualifying rows. This strongly corroborates the mechanism for August
12 without proving the exact 08:35 payload or retrospectively confirming cause.
The August 7, 10, 11, and 12 zero-candidate captures and their dependent
zero-candidate Paper `NO_TRADE` results are preserved and formally adjudicated
as data-contract failures before the strategy decision boundary. They are not
strategy no-trades and do not count toward any performance sample.

The prospective parser accepts both percentage-header identities and both
`Shs Float`/`Float`, validates required screener columns before parsing, and
fails loudly on unknown required-column drift while still allowing a legitimate
header-only empty result. A nonpersisting live Finviz proof against the current
schema returned 16 qualifying Institutional Momentum candidates where the old
parser returned zero. Compileall, 65 focused provider/capture/Alpaca Paper
tests, and all 1,892 Python tests pass.
No historical capture was rewritten, no retrospective trade was created, and no
account, position, order, Shadow, scoring, readiness, UI, schema, or secret path
changed. The repair is integrated and backed up; all 22 future openings and the
next dependent Paper job are repinned to this final repair head.

ARGUS-SESSION-FIDELITY-004 reconciles the exact dormant read-only
SESSION-FIDELITY-001 through 003 observer stack from source head `799f07b` onto
current base `a46d31b`. All 11 source/test/tool artifacts are byte-identical to
their source, with one current-head timezone regression added separately.
Compileall, 16 focused tests, 209 adjacent market-data/broker-boundary tests,
and all 1,889 Python tests pass. No production runtime imports
the observer, and it adds no account, position, preview, order, live-endpoint,
Shadow, service, Engine Host, WPF, or production-store route.

The August 11 A/B/C session-fidelity jobs did run. Their Schwab children wrote
valid immutable evidence: A at 03:05 Central was `USEFUL_WITH_LIMITATIONS` with
fresh SPY/QQQ/NVDA quotes and volume; B at 05:55 was
`USEFUL_WITH_LIMITATIONS` with fresh quotes; C at 06:05 was `HIGH_FIDELITY`
with fresh quotes, candles, and volume. Each Alpaca child failed safely with
`TypeError`, so the three combined checkpoints are incomplete and no combined
manifest was fabricated. The defect was frozen-provider dependency mixing, not
a missed Task Scheduler launch or a Schwab capture failure.

The original A/B/C evidence also preserves an incorrect non-authoritative
`targetEastern` field that repeats the Central target. Actual task, provider,
and receipt clocks remain intact, and history is not rewritten. The frozen
August 12 retry currently resolves the correct Eastern targets at 04:05, 06:55,
and 07:05; a current-head regression test pins those conversions.

The prospective replacement is `SESSION-FIDELITY-003`, an Alpaca-only,
SPY/QQQ/NVDA, GET-only retry on Wednesday August 12 at 03:05, 05:55, and 06:05
Central. All three one-time tasks remain Ready, never run, and pinned to clean
immutable branch `codex/ARGUS-SESSION-FIDELITY-003-premarket-retry` at
`799f07b` with exact module, runner, adapter, and provider hashes. They require
Steven's Windows session to remain logged in for CurrentUser DPAPI; the desktop
may be locked and Codex is not required. No account values, positions,
previews, orders, strategy authority, execution authority, production
persistence, or transmission is available. Do not launch, replace, reschedule,
or amend the frozen retry. Audit its persisted result after each terminal run.
The retry evidence gate does not block unrelated project development or the
independent ordinary opening/Paper schedule.

ARGUS-ROADMAP-004 establishes `CAPTURE_SAFE_DEVELOPMENT_ACTIVE` for the
August 12 evidence window. Canonical `master`, the installed Automation
Service, and all ordinary opening/Paper jobs remain frozen at exact head
`5e06e33668f46e824e0eff092a426447e5a469cb`. The separate premarket retries
remain frozen at `799f07bf08dec8a9f0d7d1d970934237be2dd544`. Unrelated work
may continue only in a distinct AppData Git worktree using synthetic fixtures
and temporary output. It may be committed and backed up on its feature branch,
but it must not modify canonical files, the shared `.venv`, installed packages,
production data, DPAPI credentials, provider/account state, service or Engine
Host configuration, the automation manifest, Windows tasks, or any scheduled
evidence path.

The protected windows are 03:05, 05:55, and 06:05 Central for the read-only
Alpaca session-fidelity retries, followed by the 08:35 ordinary opening capture
and Paper engineering cycle. Canonical integration, Roadmap commits on
`master`, runtime installation, repinning, and service restart remain deferred
until all five jobs are terminal and any Momentum Hunter-owned Paper order or
position is terminal and reconciled. The Paper job has a seven-hour timeout,
so elapsed clock time alone is not proof that this gate has closed. Steven's
Windows session must remain logged in for the CurrentUser-DPAPI retry tasks;
the desktop may be locked, and Codex is not required. This Roadmap update is
branch-local and remains `IMPLEMENTED_PENDING_MERGE_AFTER_AUGUST_12_EVIDENCE`.

ARGUS-SHADOW-025L implementation `51579de` is fully verified and backed up on
`codex/ARGUS-SHADOW-025L-current-head-runtime-boundary`. This release closeout
is the intended final canonical identity; after its clean fast-forward,
non-force synchronization, and exact-head opening/Paper job repin, status
resolves to `COMPLETE` without another Git mutation. It reconciles the exact
dormant SHADOW-025B through 025K serialized runtime-boundary chain from source
head `203003b` onto canonical base `b4762c6`. The 39 restored artifacts cover cross-process event-
ledger ownership, prospective source admission, one explicit runtime topology,
write-once admission evidence, a composed writer session and evidence chain,
read-only recovery planning, dormant orchestration, raw-root security, and
installed-writer feasibility. No existing runtime path imports the stack and
the restored modules contain no provider, account, broker/order, service,
scheduler, Engine Host process, WPF, or production-store capability. Compileall,
196 focused runtime-chain tests, 412 continuous-stack tests, 387 adjacent
current-runtime regressions, and all 1,873 Python tests pass. Module presence
does not authorize activation.

The current Automation Service, Engine Host, and WPF share Steven's Windows
SID, so ACLs cannot distinguish the future raw-evidence writer from the UI.
The contracts preserve two feasible shapes but select neither: a distinct-
principal Engine Host that requires separately approved credential
reprovisioning/brokering, or a dedicated evidence-writer process behind a
strongly authenticated nonpersistent channel. Same-user SID-only pipe identity
is insufficient. Every result keeps `activation_authorized=false`. The next
consequential gate is the writer-principal and credential-access architecture
decision; no credential, principal, ACL, installed runtime, or production path
changes in 025L.

ARGUS-CONTINUOUS-003 implementation `1452507` is integrated locally, fully
verified, and backed by `codex/ARGUS-CONTINUOUS-003-current-head-integration`.
This release closeout is the intended final canonical identity; after its clean
fast-forward, non-force synchronization, and exact-head opening/Paper job
repin, status resolves to `COMPLETE` without another Git mutation. The task
reconciles the proven continuous-intraday contract stack
against the Paper-engineering and scheduler-hardened head: candidate lifecycle,
rolling regime, macro-event context, provider-neutral catalyst evidence,
prospective plan versions, sequential breakout research/outcomes, and
event-driven decision cycles. The eight Python modules remain dormant and no
existing runtime module imports them. This creates no provider, account,
broker/order, service, scheduler, Engine Host, WPF, production-store, scoring,
readiness, Shadow, or Paper capability. Current-head compileall, 254 focused
tests, 228 adjacent regressions, and all 1,715 Python tests pass. All 29 restored
artifacts match source branch `657cb37`; existing-runtime import, dormant-
capability, credential-shape, protected-path, and staged-whitespace reviews
pass. The explicit serialized runtime source/writer contract is supplied by
ARGUS-SHADOW-025L; installed activation remains a separate consequential gate.

The approved long-term direction is specialist intelligence and prospective
strategy diversification, not a monolithic replacement for Momentum Hunter's
Momentum engine. The current Momentum/Paper path remains the immutable
baseline/control. Future research flows from opportunity detection to
independently testable specialist opinions, then prospective comparison against
the baseline, and only later to combination or arbiter logic that has earned
authority through evidence. Phase 13R records that program without implementing
or activating it. It must reuse CONTINUOUS-003, Technical Breakout Research
Engine v1, SHADOW-025, DATA-004, DATA-005B, and existing prospective-sample,
counterfactual, rank-conditioned, and no-backfill governance. Near-term priority
remains the frozen A004 Paper engineering sample and the separate continuous
writer-principal/credential-access decision; specialist planning must not delay
either lane.

ARGUS-BROKER-ALPACA-004 Paper engineering wiring is integrated and backed up
through implementation commit `93f944c`. The former canary engineering sample
`alpaca-paper-engineering-20260810-v1` is closed and archived as invalidated by
provider contract drift. On August 11 and 12, the
independent Automation Service completed the ordinary opening capture and
admitted the dependent Paper cycle immediately. Both Paper cycles closed as
`NO_TRADE` with reason `PAPER_NO_CANDIDATES_IN_PROSPECTIVE_REPORT`; they made
zero Alpaca provider calls and created no intent/order/position/outcome. The
later DATA-006 diagnosis proves those empty reports were caused by Finviz
percentage-header schema drift, so these results prove schedule, dependency,
fresh-report identity, and fail-closed empty-report behavior only. They do not
prove a legitimate market no-trade or the prospective account, allocation,
entry, protection, or exit path.

Replacement sample `alpaca-paper-engineering-20260813-v2` starts prospectively
with the same policy values. No prior decision or result carries into v2.

The intended candidate-bearing path remains Schwab trusted evidence ->
DATA-004 TradePlan -> Paper Risk Governor -> DATA-005B provider-neutral
allocation -> Canary Alpaca Paper -> broker-resident fractional stop -> bounded
reconciliation -> immutable decision/outcome. Every cycle terminates as
`PAPER_TRADE_CREATED` or truthful `NO_TRADE`; it is prospective, Paper-only,
and excluded from the final continuous-intraday 30-trade strategy sample.

The initial canary engineering profile is a separately versioned lab policy,
not permanent strategy law: `$2` maximum risk per trade, `$95` maximum
notional, `$5` cash reserve, `$2` aggregate open risk, `$4` daily-loss limit,
one concurrent position, and 30-second account freshness. Entry additionally
requires current authoritative Schwab regular-session evidence, a valid
same-session plan, spread no wider than 3%, entry extension no greater than
0.25%, and reward/risk of at least 1.5. Alpaca remains authoritative only for
Paper account, order, fill, and position truth.

Restart safety is explicit. A write-once intent precedes submission; a restart
may recover an already accepted client-order identity but may never submit a
late new entry. Filled entries recover or install their stop, protection
failure triggers exact-quantity emergency flattening, partial emergency exits
cannot claim flat, and a Windows-wide mutex prevents concurrent lifecycle
managers. The Automation Service supports one `paper_engineering` job dependent
on the same-date opening capture, refreshes time after capture before admitting
Paper work, allows only a 15-minute start window, resumes persisted Paper work
after service restart, and supervises the session for at most seven hours.
Future opening-job repins also repin the dependent Paper job.

Compileall, 188 broker/allocation/automation regressions, 75 final focused
automation tests, and all 1,459 Python tests passed at release; the August 11
pre-open recheck passed compileall plus 138 focused broker/lifecycle/Paper/
automation tests. Activation preflight reached only the exact Alpaca Paper host
and found the Canary account `ACTIVE` with `$100` cash/buying power, zero
positions, and zero open orders; it made zero mutations. No Paper order has been
made by this prospective sample. No live Alpaca host, Schwab order, Shadow
activation, score/rank/alert change, database/schema change, UI change, or
final-sample claim exists. The next operational action is continue the same
engineering sample after DATA-006 is integrated and future jobs are repinned,
until candidate-bearing evidence exercises the downstream gates. Legitimate
future `NO_TRADE` results remain terminal evidence, but the August 7/10/11/12
empty results are invalid data-contract evidence with schema drift retained as
an inferred or strongly corroborated root-cause candidate. Continuous intraday
discovery remains the architectural answer to opening-only supply; it does not
replace correct parsing of the opening scanner.

ARGUS-AUTOMATION-008 closes the next-day repin defect exposed by that first
terminal Paper cycle. Future opening replans now remove a historical Paper job
from the active manifest only when the persisted Automation Service state proves
that exact job is terminal; a missing or nonterminal receipt fails closed.
Same-date and future Paper jobs remain bound to their opening dependency and are
repinned to the new full Git identity. Removing a terminal job from the active
manifest does not remove or rewrite its service receipt. The repaired planner
was proven against a byte-preserved copy of the August 11 production manifest:
it produced exactly 23 openings from August 12 through September 14, removed
the completed August 11 Paper entry, preserved nonmarket jobs, and left the
source manifest unchanged.

ARGUS-BROKER-ALPACA-001 through A003 are stacked on
canonical `master` through `c62eb93` and are `COMPLETE`. The proven feature
stack is backed up at `codex/ARGUS-BROKER-ALPACA-003-paper-lifecycle-proof`.
Secure onboarding stores only the
rotated `CANARY_REALISTIC` credential under lane-specific CurrentUser DPAPI;
the `STRATEGY_RESEARCH` slot remains empty and disabled. The isolated adapter
accepts only `https://paper-api.alpaca.markets`, rejects the live host and
research lane structurally, and is not imported by any production runtime.
The earlier A002 proof established fractional limit submission, exact
client-order lookup, cancellation, and a clean final account.

The A003 harness
writes a tamper-evident plan before mutation, uses one-dollar SPY Paper entry,
frozen client-order IDs, idempotent submission/replacement recovery, bounded
polling, partial-fill recognition, distant stop/stop-limit/target hosting,
price-only replacement, three finite exact-quantity flatten attempts, sanitized
provider receipts, and write-once final/failure evidence outside Git. Synthetic
restart, interruption, orphan-state, partial-fill, tamper, duplicate-run, and
forced-flat tests pass. A pure offline adjudicator now requires the exact
fingerprinted lifecycle/event/provider-receipt chain, clean final-flat state,
and frozen command identities before promoting only directly observed
capabilities; bracket/OCO/OTO, streaming, linked protection, and every other
unobserved capability remain unproven. The lifecycle CLI emits that adjudicated
registry automatically after a successful proof without altering the persisted
source report. On 2026-08-10 at 12:32 Central, direct proof
`alpaca-paper-lifecycle-78aaade645ee4fd697a338d3` entered `$1.00` of SPY,
filled `0.00128035` share, hosted and canceled fractional stop and stop-limit
orders, replaced and canceled a fractional limit target, then liquidated the
exact quantity. The persisted and independent final checks both found zero
positions and zero open orders. Classification is
`ALPACA_PAPER_LIFECYCLE_PROVEN`; final-evidence SHA-256 is
`A1A4CDDFC60BF03DDC7D23B0F9AF548F64B107DF34E88287477E548B75A54414`.
No credential value or account identity appears in the evidence. Compileall,
53 immediate preflight tests, and all 1,391 Python tests pass.

Direct evidence now proves the Paper environment, fractional quantity, market,
limit, stop, stop-limit, price replacement, cancellation, client-order
identity, and exact fractional liquidation. Partial fills and provider restart
recovery were tested synthetically but did not occur in this direct run;
bracket/OCO/OTO, status streaming, extended-hours execution, and linked
broker-resident protection remain `UNKNOWN` or `DOCUMENTED_UNPROVEN`. No Alpaca
code is installed or reachable from Engine Host, Shadow, scheduler, service,
WPF, or production execution. This does not authorize live Alpaca trading,
funding, money movement, or a live endpoint. Schwab's proven authentication,
read-only account binding, quote, Streamer candle, `/pricehistory`, canonical
candle, chart, and continuous-monitoring work remains the market-data
foundation. Strategy logic remains broker-neutral:

```text
Schwab market data -> Momentum Hunter engine -> provider-capability boundary -> Alpaca Paper
```

Project status is `PROJECT_DEVELOPMENT_ACTIVE`. The direct A003 market-hours
acceptance and integration gates are closed; DATA-005B reconciliation is now
the active offline engineering lane.

ARGUS-DATA-005B provider-neutral allocation preparation is
`COMPLETE` on canonical `master`, released from
`codex/ARGUS-DATA-005B-current-master-integration`, reconciled from the proven
offline branch at `046b127`. It adds dormant `AccountSnapshot`,
`BrokerCapabilities`, and
allocation contracts that preserve `idealRiskQuantity`,
`providerExecutableQuantity`, and `finalAuthorizedQuantity`; capability-driven
fractional/whole-share quantization; cash, buying-power, freshness, aggregate
risk, daily-loss, notional, and configurable-concurrency gates; rank-preserving
multi-position Paper research evidence that consumes one shared account budget
across admitted candidates and preserves explicit aggregate notional/open-risk
blocks; and separate
`ALPACA_PAPER_EXECUTION_RESULT` versus
`MH_CONSERVATIVE_EXECUTABLE_RESULT` domains. Hard Chew self-review added
explicit candidate/allocation lineage, account-lane, provider, and environment
identity; mismatches now fail closed before research admission or result
pairing. Compileall, 36 focused tests, 202 bounded regressions, and all 1,427
Python tests pass on the current A003-integrated base. No numeric production
policy, Alpaca-specific capability, selector arm, Shadow trade, provider call,
credential, service, scheduler, UI, or transmission path is activated. The
older dirty `codex/ARGUS-DATA-005B-shadow-allocation-activation` worktree at
`91e461f` remains preserved for source comparison and must not be integrated as
is. Its useful cycle-snapshot semantics remain a separate review input; its
provisional whole-share, single-position, and numeric values are not strategy
law.

The next execution program has two separately versioned lanes. The
canary-realistic lane asks what the eventual small supervised account could
actually execute under fresh buying power and conservative limits. The
strategy-research Paper lane asks which independently eligible opportunities
have expectancy without allowing the tiny canary balance to censor higher-
priced symbols. The lanes require separate policy/configuration fingerprints,
capital and concurrency limits, and performance summaries. A result from one
lane may never count in the other. The first post-integration Paper work is an
engineering/activation sample; the final continuous-intraday 30-trade sample
does not begin under a temporary whole-share, single-position, opening-heavy,
or unproven provider model.

The first generated Canary key pair was exposed outside the local-entry
boundary and was provider-rotated without use. The initial hidden-console paste
implementation then stored Windows `Ctrl+V` as a one-character control code;
two account reads failed safely with HTTP 401 and no account body. The local
entry path now uses a masked Windows dialog with explicit Paste buttons,
rejects whitespace/control characters, clears a credential clipboard value on
successful storage, and encrypts the result with lane-specific CurrentUser
DPAPI entropy. The corrected one-request canary passed. Compileall, 24 focused
tests, 72 adjacent broker/allocation tests, and all 1,335 Python tests pass.
Secure onboarding and the bounded A002/A003 direct Paper proofs are complete and
integrated. Unknown capabilities remain blocked. DATA-005B's offline
architecture is now being reconciled onto the accepted current base; provider-
specific runtime wiring remains a later audited slice.

ARGUS-DATA-005A fresh account/portfolio evidence is `COMPLETE` on canonical
`master` through `dff993c`. The new exact-host,
GET-only source revalidates the immutable ending `2573` `INDIVIDUAL_CASH`
binding, requests current balances plus positions, preserves provider and local
receipt clocks, and derives current commitments and realized daily P&L from the
read-only Official Shadow state. It fails closed on a changed account, multiple
accounts, unexpected brokerage positions, malformed balances, invalid Shadow
allocation evidence, stale/future evidence, or any transmitting capability.
The source exposes no order method and is not wired into selector, simulation,
service, scheduler, Engine Host, or Shadow defaults. A nonpersisting live proof
observed exactly one expected account, zero brokerage positions, zero Shadow
commitments, and transmission `UNAVAILABLE`; no full account identity, balance,
token, or credential was retained in the proof. Compileall, 73 focused/runtime
identity tests, 210 adjacent tests, and all 1,314 Python tests pass. Activation
remains blocked pending DATA-005B reconciliation and separately frozen
canary-realistic and strategy-research policies after Alpaca capability proof. The
feature and canonical branches are backed up, all 25 future opening jobs are
pinned to the final synchronized closeout head, and the installed service was
restarted under UAC. Its
fresh heartbeat reports one authenticated `Healthy` current-build Engine Host,
matching endpoint/lock/process/listener identity, no active cycle, and
transmission `UNAVAILABLE`.

ARGUS-DATA-005 account-aware allocation is `COMPLETE` on canonical `master`
through implementation commit `a2e5020`. The versioned
`account-aware-fixed-unit-risk-v1` contract replaces executable `$500`
reference sizing with a separately fingerprinted allocation decision. Its
current whole-share quantization is a provider-policy implementation, not a
permanent strategy constraint. Quantity is bounded by fixed/remaining risk,
cash or buying power after reserve and commitments, and per-position notional
limit. Policy, account context,
allocation, and quantity are frozen through simulation and Shadow; Risk
Governor must precede allocation, and allocation must precede FakeBroker
preview/submission. Missing, stale, future, malformed, mismatched, over-limit,
or transmit-capable evidence blocks before order creation. The pure Schwab
bridge consumes already validated read models and performs no account or
network call. Full verification passes 1,296 Python and 251 .NET tests.
Scoring, rank, alerts, RVOL, DATA-004 setup/timing/replacement semantics,
providers, capture/service/scheduler, real broker behavior, database/schema,
packages, credentials, raw captures, generated reports, and historical
evidence are unchanged. DATA-005A now supplies the bounded fresh read-only
account/portfolio source, but it is not activated and no production numeric
defaults were invented. The allocator must next preserve distinct
`idealRiskQuantity`, `providerExecutableQuantity`, and
`finalAuthorizedQuantity`, with fractional precision and order-type support
coming only from explicit provider capabilities. Unknown capability fails
closed.

ARGUS-DATA-004 same-session intraday TradePlan semantics is `COMPLETE` through
the release titled `Add intraday TradePlan horizon semantics`. The versioned
`INTRADAY` contract supports `OPENING_BREAKOUT`, `CONTINUATION_BREAKOUT`,
`PULLBACK`, and `RECLAIM`, plus properly attributed catalyst-driven plans.
Opening is the first producer, not the horizon model. Setup-aware validity,
expiry, stop/target rules, forced-flat boundaries, lifecycle transitions,
source evidence, predecessor identity, plan ID, and record fingerprint are
prospective and fail closed. An already-crossed opening level becomes immutable
`MISSED_ENTRY`; a later reclaim must be a new plan with a terminal breakout
predecessor and explicit replacement reason. Risk Governor, Active Monitor,
workstation simulation, and Shadow enforce the same timing and identity
contract. Full verification passes 1,271 Python and 251 .NET tests. Scoring,
rank, alerts, RVOL, UI, capture/scheduler/service behavior, providers, accounts,
orders, transmission, database/schema, packages, credentials, raw captures,
generated reports, and historical evidence are unchanged. DATA-005 now consumes
this contract without narrowing it to opening momentum.

ARGUS-DATA-003 breakout-versus-reclaim plan identity is `COMPLETE` on
canonical `master` through the release titled `Add breakout and reclaim setup
identity`. A prospective TradePlan now preserves its completed-Daily breakout
level instead of moving entry above the current price after the level has
already broken. Versioned, fingerprinted evidence classifies an untouched level
as `BREAKOUT` / `PENDING_BREAKOUT` and an already-exceeded level as
`RECLAIM_REQUIRED` / `RECLAIM_NOT_CONFIRMED`. The latter remains
`DO_NOT_TRADE_SETUP_UNCONFIRMED` until a future task can prove an actual
pullback-and-recross chronology. Active Monitor preserves that blocker and
Shadow independently rejects missing, contradictory, legacy, cross-symbol, or
tampered setup evidence. Full verification passes 1,250 Python and 251 .NET
tests. Score weights, rank, alerts, UI, capture/scheduler/service behavior,
accounts, orders, transmission, schemas, packages, credentials, raw captures,
generated reports, and historical reports are unchanged. DATA-004 now supplies
the prospective same-session lifecycle; DATA-005 remains the account-aware
allocator gate.

ARGUS-DATA-002 time-normalized opening RVOL is `COMPLETE` on canonical
`master` through the release titled `Add time-normalized opening RVOL
authority`. Prospective TradePlan reports now compare cumulative canonical
Schwab minute volume only with identical elapsed-session windows from prior
sessions. Evidence records source, symbol, session minute, observed and
expected volume, formula, baseline dates, and sufficiency; five complete prior
sessions are the minimum and twenty are the target. Missing current minutes,
too few complete baselines, source/type/symbol mismatch, invalid chronology,
or tampering fails closed. The former partial-session/full-day ratio remains
visible only as `LEGACY_RVOL_RESEARCH_ONLY` and cannot grant readiness or
selection authority. Active Monitor preserves the same blocker, and Shadow
independently revalidates the evidence chain before eligibility. Historical
captures and reports are unchanged. Full Python discovery passed 1,236 tests
before the final cross-symbol hardening; final compileall and 58 focused RVOL/
selector tests pass afterward, along with all 251 .NET tests. No score weights,
alert thresholds, UI, account/order, transmission, database/schema, package,
credential, generated report, raw capture, or legacy-candle data changed.

Friday's ordinary unattended capture is `COMPLETE`, extending the opening
program to five consecutive first-attempt successes from August 3 through
August 7. `opening-capture-20260807` ran from 08:35:00 to 08:35:03 Central,
returned exit code `0`, and produced the required capture, score, and TradePlan
artifacts. The scanner returned zero candidates, so no hypothetical plan,
selector action, Shadow state, position/order request, broker action, or
transmission occurred. Twenty-five scheduled captures remain; Monday August 10
is next at 08:35 Central.

ARGUS-R032C automatic bounded candle backfill is `COMPLETE` on canonical
`master` through implementation commits `661b136` and `9f9967a`.
The Engine Host now renders existing cached bars first, coalesces repeated chart
requests behind one background symbol load, enforces a ten-symbol ceiling and
five-minute refresh cooldown, persists restart recovery atomically, and refuses
to auto-repair untrusted stores. Missing, shallow, or market-hours-stale history
is loaded through the existing sole-`2573` `INDIVIDUAL_CASH` Schwab guard into
the source-specific minute and Daily stores. WPF remains a five-second cached
consumer and shows `LOADING HISTORY` or a bounded failure without making a
provider call. Synthetic end-to-end proof transitions an immediate empty cache
snapshot to 30 populated canonical bars after one worker run. Compileall, 59
focused Python tests, all 1,216 Python tests, 35 focused presentation tests, all
251 .NET tests, and a zero-warning Release build pass. No scoring, readiness,
capture, scheduler, Shadow, Risk Governor, position/order, transmission,
database/schema, credential, legacy-candle, or R034 deletion behavior changed.
Steven accepted the isolated 1180x820 loading/failure proof on 2026-08-06: the
left side intentionally shows `LOADING HISTORY`, while the right side proves
the fail-closed `HISTORY LOAD FAILED` state without fabricated candles,
account identity, or order controls. Installed Engine Host proof then requested
previously uncached `QQQ`: the first snapshot queued history with zero candles,
and the terminal snapshots returned 180 Schwab candles for 1m, 5m, 15m, and
Daily. Intraday evidence correctly reported `STALE` after hours while Daily
reported `AVAILABLE`; the account invariant remained one ending `2573`
`INDIVIDUAL_CASH` account, positions/orders were not requested, and order
transmission remained `UNAVAILABLE`.

ARGUS-R034A legacy candle consumer migration is `COMPLETE` on canonical
`master` through `1aafca5`. Active outcome,
evidence-health, data-quality, read-model, research, Daily-symbol discovery,
source-registry, and SQLite reporting defaults now use reconciled Schwab
partitions or explicitly classify the old mirror as retired. The outcome
updater cannot recreate the production legacy JSON, and its former Yahoo
minute fetch path is removed. Stream-only/provisional bars remain ineligible
for canonical outcome or research use. The plan-only verifier identifies the
unchanged 710 CRWV JSON rows and 710 matching SQLite rows, finds 12,478 healthy
reconciled Schwab bars across CHYM/IWM/SPY/U, reports zero blocking references,
and proves all inputs unchanged. Focused tests pass 44/44, full Python discovery
passes 1,225/1,225, full .NET passes 251/251, compileall and `git diff --check`
pass, and secret/capability scans are clean. The verifier contains no delete,
archive-write, provider, account, broker, or database-write capability.

The stacked release is integrated. The installed Engine Host was replaced
through its guarded stale-host path and proved the new runtime with the QQQ
backfill above. Its governance closeout was backed up normally and the then-26
opening jobs were repinned to that synchronized head. Friday subsequently
completed; the current 25 jobs will be repinned to the final DATA-002 head.

The earlier read-only R034 preflight correctly found that destructive cutover
could not safely be a two-file deletion. R034A now closes those consumer and
recreation dependencies without deleting either legacy artifact.
`daily-ohlc-bars.json` is a separate 263-symbol/79,298-row research dataset,
not an active WPF chart source and not an R034 deletion target without a
separate approved migration.

Thursday's ordinary unattended capture is `COMPLETE`. The automation service
started `opening-capture-20260806` at 08:35:00 Central; the capture process
began at 08:35:01, passed the same-response HTTPS clock gate with 282.958
milliseconds skew and 1,163.903 milliseconds uncertainty, and completed on
attempt 1 of 2 at 08:35:22 with exit code `0`. It preserved two candidates,
`U` and `CHYM`, the opening JSON/Markdown capture, score breakdowns, and
TradePlan JSON/Markdown/CSV. Market regime was `bull`; outcome maintenance is
truthfully `DEFERRED_AFTER_OPENING`. Fresh Schwab quote evidence passed, while
both catalyst relationships remained `UNRESOLVED`, contributed zero authority,
and left both hypothetical plans `DO_NOT_TRADE_UNTRUSTED_EVIDENCE`. No selector,
Risk Governor execution decision, Shadow state, position/order request, broker
action, or transmission occurred.

Wednesday's ordinary unattended capture is `COMPLETE`. The automation service
started `opening-capture-20260805` at `2026-08-05T08:35:00.482217-05:00`; the
capture process began at 08:35:01, passed the same-response HTTPS clock gate
with 91.269 milliseconds skew and 1,154.837 milliseconds uncertainty, and
completed on attempt 1 of 2 at 08:35:23 with exit code `0`. It preserved three
candidates (`NVDA`, `SHOP`, and `ZETA`), score breakdowns, and the opening
capture plus TradePlan JSON/Markdown/CSV artifacts. Their audited SHA-256 values
are `09D9D68C...2BD81`, `B22EAC7A...10B6B`, `62EE7A08...D1BF`,
`5945EBBE...DBE0`, and `13471A23...BE5F`. Capture-to-report provider, scanner,
session, timestamp, and source-path identity are consistent. Outcome maintenance
is truthfully `DEFERRED_AFTER_OPENING`. DATA-001B's prospective authority gate
worked: all three rows are `DO_NOT_TRADE_UNTRUSTED_EVIDENCE`, unresolved
catalysts contribute zero authority, and no candidate became execution-eligible.
No selector, Risk Governor execution decision, Shadow state, account/position/
order request, broker action, or transmission occurred.

Tuesday's ordinary unattended capture gate is `COMPLETE`. The service started
`opening-capture-20260804` at `2026-08-04T08:35:01.4970294-05:00`, passed its
same-response HTTPS clock gate with 380.692 milliseconds skew and 1,163.416
milliseconds uncertainty, and completed on attempt 1 of 2 at 08:35:43 with
exit code `0`. It preserved 11 candidates, score breakdowns, and the opening
capture and TradePlan JSON/Markdown/CSV artifacts. Their audited SHA-256 values
are `CFEF9534...375BE`, `FCDE2590...9EE1`, `43953E43...61A9`,
`6679570D...E4CF`, and `E321D806...5E74`. The capture-to-report provider,
scanner, session, timestamp, and source-path validator passes. Outcome
maintenance is truthfully `DEFERRED_AFTER_OPENING`. No selector, Risk Governor
execution decision, Shadow state, account/position/order request, broker action,
or transmission occurred.

ARGUS-DATA-001 and ARGUS-DATA-001B are now `COMPLETE` on local `master` through
their unchanged implementation commits `488cbca` and `fe8c929`. DATA-001
preserves field-level price provenance and separate provider attempts, and it
classifies unproven catalyst relationships as `UNRESOLVED` / `BLOCKED` rather
than presenting them as direct issuer facts. DATA-001B prospectively gives
blocked catalyst evidence zero catalyst points and zero cluster-derived bonus,
forces current research-only price evidence to
`DO_NOT_TRADE_UNTRUSTED_EVIDENCE`, and makes Shadow selection reject missing,
legacy, tampered, or contradictory authority records. Monday's and Tuesday's
pre-integration reports remain immutable historical evidence; they are not
silently recomputed.

ARGUS-DATA-001C is `COMPLETE` through implementation commit `17e5b50`. A
TradePlan report now makes one bounded batch request through the canonical,
exact-host Schwab `/marketdata/v1/quotes` source and grants execution-price
authority only to matching, fresh, real-time, regular-session, tradable quotes
with valid last/bid/ask, provider clocks, spread, and HTTPS clock proof. Nasdaq
and Yahoo chart evidence remain visible as research-only fallbacks and can
never inherit Schwab authority. The unsupported Yahoo Finance v7 quote request
has been retired; immutable historical `QUOTE_HTTP_401` evidence is preserved.
A Schwab failure remains explicit and fail-closed. Active Monitor refreshes now
reapply the same authority rules instead of promoting research tape to
`EXECUTION_READY_TRADE`. No score weights, alert thresholds, account/order
method, transmission capability, database, package, or UI behavior changed.

ARGUS-R031B's full 15-minute market-hours proof is `COMPLETE` on local `master`
through implementation commit `404c589`. Schwab accepted
one read-only `CHART_EQUITY` subscription for SPY, IWM, and the canonical
rank-one candidate NVDA. Sixteen one-minute candles per symbol arrived once,
62.147 to 87.645 seconds after their bar-start timestamp, with complete OHLCV
shape and no replay, revision, out-of-order arrival, or missing streamed symbol.
All 48 comparable OHLC values matched `/pricehistory`; five NVDA volume values
contained fractional stream tails while price history returned the same
whole-number volumes. No explicit finality marker, current-minute revisions,
reconnect behavior, or subscription ceiling was proven. Adjudication is
`ACCEPTED_WITH_LIMITATIONS`: stream bars are near-live display/research evidence,
not canonical stored truth until reconciled against price history. The proof
wrote only sanitized, write-once artifacts outside the repository and invoked
no service, Engine Host, WPF, position, order, or production-data path.

ARGUS-R032 is `COMPLETE` through the commit titled
`Add Schwab incremental candle collector`. The bounded collector resolves an
exact-date opening universe from selected/active symbols, the top five Hunter
candidates, SPY, and IWM with a hard ten-symbol ceiling. It writes only to the
separate `schwab-candles-v1` store, preserves every distinct stream and price-
history version, makes `/pricehistory` canonical, identifies corrections and
history-only gap fills, and fails visibly on missing, stale, gapped, malformed,
or unreconciled evidence. A cross-process writer lease, atomic partition writes,
strict identity/hash validation, source-date checks, and write-once run results
cover restart, duplicate, out-of-order, tamper, and conflicting-output cases.

The exact patched-code live proof subscribed to SPY, IWM, NVDA, SHOP, and ZETA
for 60 seconds during extended hours. Stream transport and all five bounded
history reconciliations passed; eight stream versions and 13 history versions
were preserved. The overall result correctly remained `PARTIAL` because sparse
extended-hours evidence contained visible one-minute gaps for SPY, SHOP, and
ZETA. No account anomaly occurred. Guarded sole-account identity revalidation
was the only brokerage read; positions and orders were not requested and order
transmission remained `UNAVAILABLE`. The proof did not invoke Engine Host, WPF,
Shadow, scoring/readiness, or the legacy candle store.

Steven's first 2026-08-06 R033 review correctly rejected the sparse 60-second
transport proof. The repaired review used a guarded isolated R032B historical
backfill and a dense six-pixel bounded viewport, producing readable recent 1m
structure at 1180x820 and 1920x1080. Steven accepted that visual repair and
directed integration. R033 is `COMPLETE` on canonical `master` through the
combined release at `af783da`; the source feature commit `c88faa4` remains
historical branch evidence and must not be merged separately.

ARGUS-R032B historical candle backfill is `COMPLETE` on canonical `master`
through the combined release at `af783da`; source feature commit `9f9ac96`
remains preserved. It adds bounded Schwab `/pricehistory`
backfill for a ten-day one-minute window and a one-year daily window, with a
separate source-specific daily store, atomic writes, exact rerun idempotency,
correction/reassertion history, tamper checks, and explicit minimum depth. The
guarded isolated market-hours proof for NVDA, SHOP, ZETA, SPY, and IWM inserted
39,165 minute versions and 1,260 daily bars with no findings and no position,
order, or transmission action. Daily is bound only to
`schwab-daily-candles-v1`; full combined Python/.NET and visual proof passed
before integration. R034 legacy deletion remains a separately approved
destructive gate, and Official Shadow remains unarmed at `0 / 30`.

Canonical `af783da` was the historical capture/runtime baseline before R032C.
The 26 jobs that originally began on 2026-08-07 were subsequently repinned to
the integrated R032C/R034A release. Friday completed successfully; the current
acceptance boundary is 25 future jobs beginning Monday 2026-08-10, a Running/
Automatic service with fresh heartbeat, Healthy Engine Host, zero Shadow jobs,
and order transmission `UNAVAILABLE` at the final DATA-002 head.

R032 Hard Chew proof passes Python compileall; 30 focused collector tests; all
89 Schwab candle contract, observer, adjudication, and collector tests; full
Python discovery at 1,173/1,173; `git diff --check`; protected-path review; source nonmutation;
and a zero-hit live-proof secret scan. No UI, score, readiness, selection,
TradePlan, Shadow, broker/order, service/scheduler, Engine Host, database/schema,
package, environment, raw-capture, legacy-candle, or generated-report file
changed in Git.

R032B Hard Chew proof passes Python compileall; 16 focused backfill tests; all
96 Schwab candle contract, observer, collector, and backfill tests; full Python
discovery at 1,196/1,196; a zero-network/zero-write plan-only CLI; and source
nonmutation tests. The implementation is isolated from the Thursday service
checkout and does not alter its exact Git pin.

ARGUS-MONDAY-002 Sunday-readiness hardening is `IMPLEMENTED_AND_VERIFIED` at
runtime commit `d86f750`. The opening manifest now freezes every ordinary
opening job to a full lowercase Git SHA, and the supervisor validates that
identity immediately before launching a capture. This prevents later edits or
an unexpected checkout change from silently altering Monday's runtime. The
manifest migration accepts the currently installed legacy unpinned opening
jobs as input, validates the fully pinned replacement before installation, and
does not mutate its source manifest while planning.

A successful opening capture can no longer be invalidated solely because the
secondary `DEFERRED_AFTER_OPENING` outcome-status file cannot be written. That
failure is logged as a warning while the immutable successful opening result
and exit code zero are preserved. An explicit regression also proves that a
failed Monday opening receipt does not block Tuesday's independent job. The
changed path passes Python compileall, PowerShell parsing, 104 focused and
adjacent automation/capture/trade-planning tests, and all 1,034 Python tests.
`git diff --check`, protected-path review, capability review, and secret
scanning pass. No scoring, ranking, readiness, replay, alert, database/schema,
account, broker/order, Shadow, UI, credential, or transmission semantics
changed.

This Roadmap closeout must be committed before final runtime activation so the
installed manifest can pin the exact synchronized canonical SHA that contains
both the runtime patch and this record. Git Steward must then fast-forward and
push normally, stop the service, migrate all 30 opening jobs to that final
head, and start a fresh service process. Post-commit acceptance is live
evidence: Running/Automatic service, fresh process and heartbeat, 30 pinned
pending jobs through 2026-09-14, Monday at 08:35 Central with hard latest start
08:40, zero Shadow jobs, transmission `UNAVAILABLE`, and no August 3 capture or
report before the scheduled run. No further canonical Git change is permitted
after that final pin before Monday's capture.

ARGUS-MONDAY-001 opening-timing hardening is `COMPLETE_AND_BACKED_UP` on
synchronized canonical `master`/`origin/master` through `50f2bae`. Its stale
pre-hardening service process was found during the Sunday audit and replaced
at 01:17 Central on 2026-08-02. The new service instance remained
Running/Automatic with a fresh heartbeat, Healthy Engine Host, the unchanged
30-job manifest, Monday `PENDING`, zero Shadow jobs, and transmission
`UNAVAILABLE`. The path fails closed on a preexisting `RUNNING` receipt,
persists terminal job results immediately, retries only explicit transient
opening exit `75` with one outer retry, limits opening enrichment to five
seconds for the top five candidates while preserving all captured/scored rows,
defers outcome maintenance until after the opening job, and uses atomic
TradePlan writes with JSON as the completion marker.

ARGUS-SERVICE-007 is `COMPLETE_AND_BACKED_UP` on canonical `master` at
`252cdc7`. A read-only status inspection at
2026-08-01 02:10 Central briefly denied the automation supervisor's atomic
replace of `automation-service-state.json`; the Python supervisor exited and
the Windows service wrapper recovered it after five seconds. The repair retries
only transient Windows access-denied and sharing-violation replace failures for
at most 20 attempts separated by 50 milliseconds. Persistent locks and every
other filesystem error still fail closed, the previous valid state remains
unchanged, and temporary files are removed. A real Windows no-delete-share lock
recovered in 0.265 seconds. Python compileall, 26 focused supervisor tests, 74
affected automation/capture tests, and all 1,019 Python tests pass. The patch
does not change job timing, capture behavior, provider calls, scoring,
readiness, Shadow state, accounts, broker/order behavior, or transmission.
The branch fast-forwarded into `master` and was pushed normally. A controlled
service restart at 02:30 Central loaded the repair without changing the
installed manifest, whose SHA-256 remains
`636274F988D89BD19AF7BB84201D64DBC175E647AF670041CFD8A2B81D388638`.
Twelve deliberate no-delete-share locks against the live receipt caused no
wrapper or supervisor restart and no new Application error. The service remains
Running/Automatic with a fresh heartbeat, Healthy Engine Host, all 30 opening
jobs pending through 2026-09-14, Monday 08:35 still `PENDING`, zero Shadow jobs,
and order transmission `UNAVAILABLE`.

Post-boot clock reliability hardening is `COMPLETE_AND_BACKED_UP` on canonical
`master` through runtime commit `30c25e5` and governance commit `3821490`. The
wake task waits two minutes after startup so the network can settle, keeps the
08:15 Central resync, and adds a final 08:25 resync before the 08:35 opening
capture. Both the installer and standalone hardener construct the same
SYSTEM-owned task and read it back to require the exact principal, action,
three triggers, wake policy, no late-start behavior, and five bounded
two-minute retries. PowerShell parsing, native task construction, compileall,
92 affected tests, all 1,017 Python tests, diff check, secret scan, and
protected-path review pass.

The physical clock gate passed at 2026-07-31 19:35 Central. Timestamped
elevated evidence proves SYSTEM ownership, action
`w32tm.exe /resync /rediscover`, startup delay `PT2M`, daily 08:15 and 08:25
triggers, `WakeToRun=true`, `StartWhenAvailable=false`, five two-minute
retries, task result `0`, and `clockSynchronized=true` against
`time.nist.gov,0x9`. Independent `w32tm /query /status` reports leap indicator
`0`, stratum `2`, the same NIST source, and successful synchronization at
19:35:42 Central. The automation service remains Running/Automatic with a
fresh heartbeat, Healthy Engine Host, all 30 opening jobs pending, zero Shadow
jobs, and order transmission `UNAVAILABLE`.

Monday opening readiness hardening is implemented on
`codex/monday-opening-readiness-hardening` at runtime commit `4b6668c` and is
integrated through this Roadmap closeout. The installed unattended service has
one ordinary capture-only job for Monday, 2026-08-03, at 08:35 Central with a
hard 08:40 latest-start boundary and a 15-minute process timeout. It is the
first of 30 pending XNYS market-session opening jobs through 2026-09-14.
Opening capture remains separate from Official Shadow: zero Shadow jobs are
enabled, the selector is not armed, no account, position, or order request is
part of this job, and order transmission remains `UNAVAILABLE`.

The runner now requires an opening job to finish as `CAPTURED`,
`REPORT_RECOVERED`, or `DUPLICATE`. A late retry or other ordinary `SKIPPED`
result can no longer be recorded as a successful service run with no opening
evidence. The clock-task hardener can also recreate the exact expected
SYSTEM-owned wake/resync task if it is genuinely absent, while refusing to
replace an existing task with an unexpected principal or action. The opening
capture hardening passes PowerShell parsing, Python compileall, 91 affected
automation tests, all 1,016 Python tests, `git diff --check`, and
protected-path review.
No scoring, readiness, replay, alert, database/schema, broker/order, UI, raw
capture, or generated-report behavior changed.

The final Friday preflight at 02:35 Central found canonical `master` clean and
synchronized with `origin/master`, the service Running/Automatic with a fresh
heartbeat, a Healthy Engine Host, the expected 30 pending opening jobs, no
duplicate August 3 capture/report, working Finviz and Yahoo access, ten current
screener candidates, and a current bull regime result. The same-response
Finviz HTTPS clock proof passed with 511 milliseconds absolute skew and 1,192
milliseconds uncertainty; Windows Time reports leap indicator zero, stratum
two, and `time.nist.gov,0x9`. The local session policy and the
[official NYSE 2026 calendar](https://www.nyse.com/publicdocs/nyse/ICE_NYSE_2026_Yearly_Trading_Calendar.pdf)
both classify Monday, August 3 as a normal trading day. Drive
`C:` is healthy with about 16.4 GiB free, AC sleep and hibernate are disabled,
wake timers are enabled, and no Windows Update reboot-pending flag exists. The
service account is enabled and does not expire, while Windows Service Control
Manager retains three restart actions after 5, 15, and 60 seconds. A recent
ordinary morning capture also completed end to end with raw JSON/Markdown,
score breakdown, TradePlan reports, and outcome-update exit `0`.

No known code defect remains before Monday after ARGUS-MONDAY-002, but its
final canonical head must be installed and loaded after this Roadmap commit as
described above. After that controlled reload and read-only identity check,
leave the computer powered on and plugged in through at least 08:40 Central.
Windows can wake a sleeping machine, but it cannot start a fully powered-off
machine without separate BIOS support.
Residual failure modes are external power loss, full shutdown,
internet/provider outage, provider-shape change, or a new
operating-system/hardware failure after the Sunday check. The Sunday 19:00
read-only preflight and Monday terminal audit remain evidence observers; they
must not launch, retry, repair, or fabricate an opening capture.

Monday's terminal receipt and opening capture/report are preserved. Canonical
integration may resume through verified fast-forward changes. Because each
remaining opening job fails closed on an exact Git identity, any canonical
advance must be followed by a controlled manifest repin and fresh service-state
proof before the next opening window.

The live-candle roadmap gap is explicit and sequenced. R011/R012 prove only
stored-candle contracts and rendering; the five-second Schwab bid/ask loop is
quote evidence and cannot be treated as authoritative OHLCV candles. R031/R031B
are complete: they identify Schwab `CHART_EQUITY` as near-live evidence and
`/pricehistory` as canonical reconciliation, prove entitlement and observed
latency, and retain unknown finality/reconnect/halt/scaling behavior as limits.
R032 is complete with bounded persistence and reconciliation. R033 proved the
consumer wiring but failed visual acceptance because R032 supplied only proof-
window history. R032B historical backfill is now the required bridge before
R033 can be reconciled and reviewed again. R034 remains the separately approved
destructive cutover.

`ARGUS-SHADOW-024` is `COMPLETE_AND_BACKED_UP` through implementation
reconciliation `4dea501` and verification/integration `cd43852`. The
deterministic offline packet builder passes 17
focused tests, 225 adjacent Shadow/Engine Host tests, and all 1,051 Python tests
on the current baseline. It reads six explicit files, emits write-once hash-addressed JSON/Markdown,
and has no provider, broker, service, Engine Host, WPF, scheduler, or Codex
capability. Monday's evidence is preserved, current-baseline regression,
protected-path, and secret checks pass, and canonical integration is complete.

The prior post-Monday activation completed successfully and produced Tuesday's
terminal capture. This closeout repeats the same controlled activation: after
the governance commit is synchronized, all 28 remaining opening jobs are
repinned to its exact Git head from 2026-08-05 through 2026-09-14. The
Running/Automatic service must hot-load that manifest, retain Monday's and
Tuesday's completed receipts, report Wednesday `PENDING`, show zero running and
zero Shadow jobs, and keep selector arming and order transmission
`UNAVAILABLE`. Any later canonical runtime change requires another deliberate
repin before its next opening.

ARGUS-R030 is `COMPLETE_AND_BACKED_UP` on canonical `master` through
implementation commit `94e1708`. The WPF workstation now has a
first-class `Positions` command and compact top-bar entry that opens a
read-only, dockable open-position monitor in the current workspace. The
monitor maps only canonical Shadow/FakeBroker open-position evidence and
shows side, quantity, average fill, executable mark, market value, unrealized
P&L, percentage, R multiple, stop, next target, state, quote age, and quote
source. Stale or halted positions remain visible with unavailable values
instead of disappearing. The current canonical empty state reports zero open
positions honestly. Schwab account positions are not connected, no account
scope changed, and no order or broker controls were added. Automated proof
passes a zero-warning solution build, all 185 presentation tests, and all 237
.NET tests. Steven accepted the visible surface on 2026-07-31. The work was
fast-forward integrated without a merge commit and backed up by normal
non-force push. The populated-row visual check remains deferred until
canonical Shadow evidence contains an open position.

ARGUS-SHADOW-023 is `COMPLETE_AND_BACKED_UP` on canonical `master` through
integration commit `cc2b1e2`, with ARGUS-SERVICE-001 predecessor `0ce70c2`.
It repairs the clock chronology defects
found during a protected late-session rehearsal and separates the local
Engine Host request and response limits. Schwab quote proof now evaluates
provider timestamps against independently validated bounds derived from the
same exact-host HTTPS `Date` response. The selector evaluates its post-request
clock proof after the request and uses the conservative trusted upper bound
only for quote freshness; the frozen decision timestamp and strategy semantics
remain unchanged. Invalid, stale, over-five-second, over-uncertainty, and
over-30-second request chronologies still fail closed. Requests remain capped
at 64 KiB; authenticated loopback responses have a separate bounded 1 MiB
limit.

The 2026-07-30 late-session clean-room rehearsal is
`COMPLETED_REHEARSAL_ONLY`. Its disposable policy alone extended the entry
window to 15:59 ET and report-to-selection limit to 300 seconds so the
production path could be exercised after the normal 15:30 ET cutoff. The
production policy remains 15:30 ET and 60 seconds. The rehearsal captured nine
current candidates, completed a current Schwab candidate+SPY+IWM quote proof,
finalized all 12 proof categories, armed one isolated selector, recorded one
decision, selected IREN, created one Risk-Governor-approved
`Simulation-only` FakeBroker order intent, and persisted terminal handoff
`CYCLE_COMPLETED_TRADE_CREATED / TRADE_STARTED`. The order remained
`PAPER SHADOW / NONTRANSMITTING`, with transmission `false` and
`orderTransmission: UNAVAILABLE`. Idempotent replay produced no second
decision or trade. Production Shadow evidence and the production worktree were
unchanged, and the rehearsal does not count toward the official `0 / 30`
sample.

The rehearsal first exposed the local-clock quote comparison, then the
selector's pre-request decision clock, and finally the client reusing the
64 KiB request limit for a valid larger host response. Each failure stopped
before the next boundary; no evidence was invented. The final sanitized
25-file bundle is
`C:\Users\steve\OneDrive\Documents\ArgusReviewBundles\ARGUS-SHADOW-023-isolated-rehearsal-20260730-150526.zip`,
SHA-256
`456B77A217AB212261200C32DC3B07ADC18B41980152403F6DAF299A1D5FE583`.
It excludes raw captures, full state, accounts, secrets, tokens, credentials,
and environment files.

The same-response Schwab HTTPS clock remains the quote-chronology authority.
Public NIST NTP is unauthenticated and remains corroboration rather than sole
runtime authority. Windows Time now reports leap indicator `0 / NO_WARNING`,
stratum `2`, source `time.nist.gov`, and a successful synchronization at
2026-07-30 21:44:21 Central. A three-sample NIST stripchart measured the local
offset at approximately 105-107 milliseconds, well inside the five-second
clock gate.

ARGUS-SERVICE-001 is installed and operational. The code is
`COMPLETE_AND_BACKED_UP` through `0ce70c2`, `cc2b1e2`, retry repair `8ce0d53`,
and installer hardening `c3928b6`. `MomentumHunterAutomation` runs under
`BEASTCOMPUTER\steve`, is configured for automatic startup, and retains finite
restart recovery. The password was recovered locally rather than reset, was
never placed in Git or chat, and the current-user DPAPI boundary was not
changed.

The Windows service wrapper, strict manifest, nonmarket account/DPAPI canary,
read-only status command, secure installer, and one-time manifest updater are
implemented. The installer plans immediate `Automatic` startup, finite process
recovery, a SYSTEM-owned 08:15 no-op wake task with `WakeToRun`, Steven's
Windows service identity, ending `2573`, type
`INDIVIDUAL_CASH`, one nonmarket canary, one downstream exact-response Codex
service probe when the CLI is available, zero Shadow jobs, no interactive
autologon, and order
transmission `UNAVAILABLE`. OpenAI's user-local Codex CLI `0.146.0` is
installed, its saved authentication is present without being read or copied,
and both wrapper and native executable completed real ephemeral read-only
headless probes. The installation probe must return exactly
`CODEX_SERVICE_READY`; its failure cannot alter or block the terminal runtime
canary receipt.

The current High Performance power plan permits AC wake timers, and this
machine supports S3 sleep. The wake task can resume sleep without signing in.
It cannot power on a fully shut-down or unpowered machine; BIOS RTC wake and
restore-on-AC-loss remain a separate physical configuration check.

Combined integration proof passes Python compileall, all 976 Python tests, a
zero-warning solution build, and all 228 .NET tests. The service predecessor
also passed its 87 focused/adjacent tests, installer dry-run nonmutation,
PowerShell parsing, native headless Codex proof, and exact-response downstream
probe tests. Protected-path review shows no scoring, readiness, replay, alert,
database/schema, broker/order, production UI, raw capture, or generated-report
change.

The installed nonmarket account/DPAPI canary completed without runtime
mutation, the downstream headless Codex probe returned exactly
`CODEX_SERVICE_READY`, and the Engine Host reports `Healthy`. The SYSTEM-owned
wake task is `Ready`, uses `ServiceAccount` logon, has `WakeToRun: true`,
`StartWhenAvailable: false`, and next runs at 2026-07-31 08:15 Central.
Interactive autologon remains prohibited. Zero Shadow jobs are enabled and
order transmission is `UNAVAILABLE`.

ARGUS-SERVICE-004 implementation `357c974` is on canonical `master`, with
elevated-launch repairs `643b2ee` and `f8edc6b` and manifest-validation repair
`becbd6d`. It adds
one-use planning and verification for the remaining reboot-without-login
canary. Preparation is fail-closed, requires a future nonmarket schedule,
preserves terminal installation receipts, enables zero Shadow jobs, performs
no service restart, and never reboots the machine. Verification requires a
new Windows boot, a new service instance, Running/Automatic service state,
Healthy Engine Host, an exit-zero canary receipt inside the exact schedule,
Session 0 execution, zero logged-on interactive user sessions, the unchanged
sole `2573` `INDIVIDUAL_CASH` binding, no position or order request, and
transmission `UNAVAILABLE`. An optional downstream Codex probe must return
exactly `CODEX_SERVICE_READY`; runtime success does not depend on Codex.

The original tooling passes Python compileall, PowerShell parsing, a live
nonmutating `PlanOnly` run against the installed service, 75 final focused and
adjacent tests, and all 987 Python tests. The installed manifest and terminal
job receipts remained semantically unchanged during dry-run proof; no reboot
baseline was created during that dry run.

The first physical reboot attempt on 2026-07-31 is
`FAILED_BEFORE_CANARY_EXECUTION`. Windows rebooted at 03:11 Central and the
service started automatically in Session 0, but the planner had generated an
uppercase `T` inside both reboot job identifiers. The production supervisor
accepts lowercase identifiers only and rejected the manifest before creating a
canary receipt, Codex receipt, account request, position request, order request,
or transmission path. The failed manifest, baseline, Application events, and
hashes are preserved under the ProgramData reboot-attempt archive. The prior
terminal manifest was restored without deleting evidence; the service now has
a fresh instance, current heartbeat, Healthy Engine Host, two terminal
installation jobs, zero Shadow jobs, and transmission `UNAVAILABLE`.

ARGUS-SERVICE-005 repair `becbd6d` generates lowercase timestamp identifiers
and adds the missing end-to-end proof that every planned reboot manifest parses
through the production supervisor. Python compileall, 35 focused service and
reboot tests, and all 988 Python tests pass. The repair is integrated and
backed up. The clean prospective repeat at 2026-07-31 10:45 Central is `PASS`.
Windows had a new boot and service instance, the service ran in noninteractive
Session 0 with zero interactive sessions at canary time, the nonmarket canary
and exact-output Codex probe completed, Engine Host was Healthy, and the sole
`2573` `INDIVIDUAL_CASH` binding remained unchanged. No position or order
request occurred, zero Shadow jobs were enabled, and transmission remained
`UNAVAILABLE`. The failed first attempt remains preserved and is not
reclassified.

The unattended opening path is additionally hardened and backed up through
atomic-capture/recovery commit `c95da62`, streamlined launcher `40729c9`, and
forced-restart repair `e24feed`. The final exact-time reboot canary scheduled
for 2026-07-31 16:39:10 Central is `PASS`: Windows established a new kernel
boot at 16:35:31, the service started automatically with a new instance at
16:35:55, the nonmarket canary completed in Session 0 with zero interactive
sessions, and the downstream Codex probe returned exactly
`CODEX_SERVICE_READY`. The sole `2573` `INDIVIDUAL_CASH` binding matched,
Engine Host was Healthy, no position or order request occurred, all 30 future
opening captures remained pending, zero Shadow jobs were enabled, and order
transmission remained `UNAVAILABLE`. The preceding early-login and
requested-but-not-completed-reboot attempts are preserved as invalid evidence;
neither is reclassified. The successful evidence is archived without deletion,
and the active manifest is restored to the ordinary 30-capture schedule.

ARGUS-SERVICE-006 implementation `13c453d` and governance update `2a7628d` are
integrated into and backed up from canonical `master`; the task is
`COMPLETE_AND_BACKED_UP`. It separates ordinary 08:35
market evidence collection from the official Shadow selector ceremony. The new
`opening` capture session is non-official, not automatically study-eligible,
and cannot carry a proof bundle, task definition, frozen Git identity, selector
arm, decision-cycle dependency, Codex prompt, account/position/order request,
or transmission authority. It runs from the existing unattended Windows
service without an Engine Host dependency, uses a bounded 08:35-08:40 Central
start window and at most four capture attempts, records terminal service
receipts, and never backfills after the window. A manifest cannot schedule both
an opening capture and an official Shadow opening on the same market date;
Shadow already performs that date's capture.

The service can hot-reload job-only manifest changes while rejecting account,
path, executable, polling, and service-identity changes. The planner generates
bounded date-specific jobs from the existing NYSE calendar and preserves every
non-opening job. A live `PlanOnly` pass against the installed manifest produced
30 future market sessions from 2026-08-03 through 2026-09-14, skipped weekends
and Labor Day, and reported selector arming and order transmission
`UNAVAILABLE`. Python compileall, PowerShell parsing, 74 focused tests, all
1,001 Python tests, and a 106-test post-review regression pass succeed. The
successful reboot loaded the current supervisor. The service then hot-reloaded
the installed 30-job manifest without a restart or UAC prompt. All 30 jobs are
`PENDING`, beginning 2026-08-03 and ending 2026-09-14; service state is
Running/Automatic with Healthy Engine Host, zero Shadow jobs, and transmission
`UNAVAILABLE`. The first operational acceptance check is the terminal August 3
receipt plus its preserved `opening` capture and report.

Installation exposed and repaired three bounded defects: retrying over an
existing manifest, resolving the project root under Windows PowerShell
`-File`, and Windows PowerShell's UTF-8 BOM making the Python manifest
unreadable. The generated manifest was normalized without changing its JSON,
the running service recovered on its finite retry, and both canaries then
completed. The reboot-without-login gate is now `PASS`. A future official
Shadow selector opening still requires a new prospective date and fresh proof
identity, but it is no longer blocked by service startup reliability.
Independent capture-only opening evidence is installed separately. A machine
powered off through 08:40 still records a missed capture window after boot;
neither the service nor Codex may backfill the market event.

The 2026-07-30 ARGUS-SHADOW-017 opening is `FAILED_TASK_DID_NOT_RUN`. The
one-time 8:35 AM Central task remained enabled with the correct final release
action, but Task Scheduler still reports its last run as 2026-07-29 at
08:35:01, result `1`, and reports no next run. No 2026-07-30 opening log,
runner attempt, exit code, capture, report, quote proof, handoff, decision
cycle, or trade exists. The canonical `60d7c9a` bundle remains static-ready at
11 / 12 and was not finalized. This is a missed task launch, not a failed
selector cycle and not an official sample observation.

The frozen task definition remains byte-valid at SHA-256
`E07D069123C8EBEAEC90D0C34619B63FB8040725F2A8BB6F4C6838EEF9230AC1`.
Its action contains exactly one `-ArmShadowSelector`, references only
`official-shadow-v3-selector-proof-bundle-60d7c9a`, has no proof-only switch,
and retains the intended one-time, no-late-start, zero-scheduler-retry,
limited-interactive shape. Task Scheduler Operational history was disabled, so
Windows retained no event-level explanation for the missed trigger. Windows
recorded an input-driven system-session transition at 08:45:22 and successful
Winlogon authentication at 08:46:23, after the trigger; these facts are
consistent with the interactive session being unavailable around 08:35 but do
not prove a single root cause. Repeated ExpressVPN service failures also
occurred around the opening window, but no causal relationship is established.

Current classification is `FAILED_TASK_DID_NOT_RUN / PRESERVE_EVIDENCE /
DO_NOT_RETRY_AFTER_FACT`. ARGUS-SERVICE-001 is the bounded reliability repair.
Its service-account and reboot-without-login canaries now pass. Capture-only
market evidence follows the separate ARGUS-SERVICE-006 path and requires no
proof identity or selector authority. A new official run must use a new
prospective date and fresh proof identity; the July 30 opening must not be
reconstructed.

The accepted SHADOW-017 implementation remains complete on canonical
`master`/`origin/master` through implementation `94f5074`, proof-acceptance
repair `40a26a0`, and operational release `60d7c9a`. It adds a separate
five-second active-order/position quote loop, a ten-second maximum active quote
age, durable executable marks, restart validation, a versioned read-only Engine
Host/WPF snapshot, and the Active Test Trade review. Python remains
authoritative. WPF refreshes cached state once per second and never fetches a
quote or calculates official P&L, R, MFE, MAE, stops, targets, or outcomes.

This is a material fill-model change. The failed `official-shadow-v1` ceremony
and activated-empty `official-shadow-v2` sample remain preserved at `0 / 30`
without mutation or backfill. The new prospective identity is
`official-shadow-v3` with fill model
`prospective-fakebroker-live-mark-v2`; v3 is activated-empty, not armed, and not
collecting at `0 / 30`.
Long positions mark from bid and short positions mark from ask. A stale or halted
quote preserves the last reliable mark, suppresses live P&L and lifecycle exits,
and cannot appear as a live winner.

Steven accepted all seven WPF proof checks on 2026-07-29, and Git Steward
committed, fast-forwarded, and backed up the implementation and proof repair
without a merge commit. The missed July 30 task did not alter that visual
acceptance or implementation result. V3 still has only its activation; no
policy, arm, cycle, state, handoff, trade, or real-order capability exists.
The selector is `NOT_ARMED`, the official sample remains `0 / 30`, and no
retrospective evidence may be fabricated.

Automated proof currently includes Python compileall, 183 focused
Shadow/Engine Host/Schwab read-only tests, the 941-test Python discovery, all
224 .NET tests with warnings treated as errors, and a real 1180x820 WPF render
at `docs/argus-office/reports/releases/ARGUS-SHADOW-017-synthetic-live-marking-ui-proof.png`.
The screenshot is synthetic, explicitly non-production, and changes no official
state. The read-only 08:50 audit found a healthy loopback Engine Host with the
expected runtime build and schema, no active FakeBroker order or position, and
order transmission `UNAVAILABLE`. The immutable Schwab binding remained ending
`2573`, type `INDIVIDUAL_CASH`, with the hash withheld, no positions requested,
and no order-transmission capability. Its access token was expired at inspection;
that is not attributed as the launch failure because the runner never started.

Final-head self-review rejected the first `d87b53b` static bundle before use:
its visual-acceptance collector still referenced the historical SHADOW-004 JPEG
and wording instead of the accepted SHADOW-017 PNG and seven-check pass. The
opening task was immediately disabled. Integrated repair `40a26a0` binds the proof
collector to SHADOW-017, rejects stale SHADOW-004 acceptance and invalid PNG
evidence, and passes 87 focused/adjacent tests plus all 941 Python tests. The
`d87b53b` bundle remains preserved as stale evidence and must not be armed.

Last reconciled: 2026-07-29 for the SHADOW-017 opening-runtime repair. The one-time armed opening did run at `08:35:01` CT and captured real prospective market evidence, but it exited `1` before completing a selector decision cycle. The task produced the immutable `shadow` capture, bound TradePlan report, current candidate+SPY/IWM quote/clock proof, finalized 12/12 bundle, and write-once `official-shadow-v1` selection-policy and arm records. Those facts make the opening useful as failed-run and counterfactual research evidence.

The same run cannot count as Trade 1 or as a completed official decision-cycle denominator. The Python Engine Host had remained alive since 2026-07-27 on selector-arm schema 2 while the installed code and valid arm used schema 3. It rejected the new arm before selection, so no decision cycle, Shadow state, handoff, FakeBroker order, or trade was created. Constructing one after the fact would introduce hindsight/lookahead and is forbidden. `official-shadow-v1` therefore closes at `0 / 30`; its activation, policy, arm, capture, report, proof, task, and logs remain preserved without backfill.

SHADOW-017 repairs both proven causes. Every Engine Host process now freezes and reports its loaded runtime-build hash and selector-arm schema. An authenticated idle host with stale identity receives the existing graceful loopback shutdown command and is replaced before an armed ceremony; a host in an active collection cycle is not stopped and instead returns a retryable result. The armed capture job runs this preflight before arming, while proof-only runs remain nonmutating. The PowerShell runner now preserves native stderr as plain log text, captures `$LASTEXITCODE`, and completes its finite one-plus-three retry/finalization logic instead of terminating on `NativeCommandError`.

Historical opening-repair state, superseded operationally by the live-marking
status above: `official-shadow-v2` isolated its state, activation, policy, arm,
and decision-cycle paths from v1. SHADOW-017 opening-repair implementation
`2213299` is integrated and backed up. V2 activated at
`2026-07-29T14:31:33.495182-05:00` with activation SHA-256
`930543A24D147C776A2A6C959E719460EB8BC61D7420D098317527884B007B9F`
and remains `NOT_ARMED` at `0 / 30`; no other v2 state exists. Its armed
2026-07-30 task was installed, then intentionally disabled before the
SHADOW-017 live-marking implementation began. It will not run under the old
fill model.

Scheduler independence is separately proven. A disposable non-market canary fired successfully with result `0` only `2.345` seconds after its requested time while all 922 Python tests ran continuously. The canary accessed no market data and changed no runtime state. This proves Codex activity does not block Windows Task Scheduler. Protected opening files must still remain frozen in the canonical task worktree; unrelated development may continue in another worktree rather than relying on a chat interruption.

Verification passes: compileall and PowerShell parsing; 185 focused Shadow/Engine Host/opening tests; all 923 Python tests; all 216 .NET tests; and a zero-warning, zero-error isolated Release build. The normal Release output directory was locked by the open Momentum Hunter UI, so compilation was repeated successfully into a separate temporary output path without closing the app. No scoring, readiness, alert, trade-planning, broker/order, credential, account-binding, database/schema, or UI behavior changed. Real-order transmission remains unavailable.

The immutable Schwab binding remains the sole approved ending `2573`, type `INDIVIDUAL_CASH`, with the account hash withheld. No account count, account identity, positions, permissions, or transmission capability changed, and no brokerage anomaly was observed.

SHADOW-015 closes the three remaining synthetic negative controls with one executable, nonmutating drill. Structured Engine Host failure is blocked before handoff creation, clock skew plus uncertainty above five seconds is blocked, and a still-running opening remains `IN_PROGRESS` without retiring its observer. The production-local run passed `3 / 3`; its ignored JSON and Markdown evidence have SHA-256 `42291D42534F1228CBBCD9F6C22252B2913EE0CBC54F54B01AE93A9FA38A2FC3` and `17A20D69F0EC117A829E1EE8B207F681AB9BA72AF4D22AC27AFDFF063A726D88`. The full protected Shadow directory stayed unchanged with only activation SHA-256 `6980D5734F3F2010D892CD1F3E29354D5DF37B193B082B18A01D8B5D485AD20C`; arm, policy, cycle, state, handoff, and trade remain absent. Compileall, 6 focused tests, 127 adjacent Shadow/Engine Host tests, all 50 bounded backend/evidence/storage modules, and all 914 Python tests pass.

SHADOW-016 closes the scheduler-shape gap before the first armed FakeBroker-only opening. An armed task is now rejected unless it is explicitly Shadow-only, enabled, future-dated, one-time, and scheduled at exactly 8:35 AM local Central time. The one-time task cannot start late when missed, receives zero Task Scheduler retries, and retains only the existing runner-owned initial attempt plus three finite infrastructure retries. A nonmutating plan mode proves the exact task action before registration; the default installer still plans three daily unarmed tasks and leaves Shadow disabled. PowerShell parsing, 3 focused scheduling tests, 130 affected Shadow/Engine Host tests, all 917 Python tests, and all 216 .NET tests pass. The final scheduling closeout binds the 2026-07-29 task to the synchronized commit containing this statement; after integration and backup, a fresh 11-artifact static bundle is prepared from that final head before the task is installed.

SHADOW-007 status truthfulness is integrated and backed up from `79e75b2` through this closeout. The read-only `sample-status` command now scopes its legacy `PASS` to sample activation only and separately reports `NOT_ARMED`, `automaticCollectionEnabled: false`, `canCollectOfficialTrade: false`, `ACTIVATED_SELECTOR_NOT_ARMED`, and the regular-market quote-proof/bundle gate. The change creates no state and leaves the activation hash and `0 / 30` sample unchanged. Twenty-seven focused tests, 123 adjacent Shadow/Engine Host tests, all 844 Python tests, and all 216 .NET tests pass.

SHADOW-008 proof-bundle assembly is integrated and backed up at `fdcf898`. Quote-proof schema v2 distinguishes `LIVE_SCHWAB_TRADER_API`, `INJECTED_SOURCE`, and unspecified sources; only the normal CLI-created Schwab transport path is marked production. The nontransmitting assembler creates 11 atomic static proof artifacts on synchronized canonical `master` and never calls `selector-arm`, writes policy, creates a cycle or trade, or exposes an order endpoint. SHADOW-009 supersedes the earlier caller-supplied candidate input with report-derived identity and expands the runtime/test evidence, so the retained SHADOW-008 production bundle is stale by design and cannot pass current canonical verification.

| Item | Current truth |
| --- | --- |
| Canonical baseline | Canonical `master` contains the post-August-14 reconciliation: SETUP-001/002, PAPER-005, DATA-008, SESSION-FIDELITY-008, AFTER-CLOSE-001/002, Phase 13R, and the SNDK stop-authority repair. SETUP-002A adds only the separate silent research activation boundary. |
| Active implementation | SETUP-002A begins the empty prospective successor-setup denominator on August 17 with two exact-head, write-once, research-only receipts. DATA-008 intrinsic Finviz plausibility runs after structural parsing and before filtering/scoring; contextual Schwab/candle and distribution checks still require explicit authoritative input. R034 remains a separate destructive approval gate. |
| Shadow sample | `official-shadow-v1` is preserved as a failed prospective ceremony at `0 / 30`; `official-shadow-v2` is preserved activated-empty and unarmed at `0 / 30`; prospective `official-shadow-v3` is activated-empty, unarmed, and `0 / 30`. Order transmission is `UNAVAILABLE`. |
| Active decision | Keep `official-shadow-v3` unarmed and preserve it at `0 / 30`. Use a separately versioned canary-realistic Alpaca Paper engineering sample to prove prospective selection, fractional allocation, provider execution, protection, recovery, and terminal evidence. Do not count it as the final continuous-intraday strategy sample. Thirty trades remains an engineering gate rather than proof of edge or live authorization. |
| Blocked by | Candidate-bearing Paper execution remains unobserved because the August 7/10/11/12 candidate-admission evidence is invalid and did not reach a strategy decision. Provider schema drift is the leading inferred cause and is strongly corroborated only for August 12; exact-run payloads are unavailable. V2 starts cleanly, but partial-fill and provider-restart behavior remain synthetic-only; broker-resident linked protection and status streaming remain separate unknowns. DATA-002 authority remains fail-closed on incomplete current-window/baseline bars; DATA-004 requires real chronology and successor identity for reclaim. R034 remains separately destructive approval-gated. Fully powered-off recovery still depends on BIOS RTC/restore-on-AC-loss. |
| Scheduled operational proof | The Aug. 14 fidelity, opening, and Paper evidence is terminal and preserved. Twenty future openings remain, the Aug. 17 Paper job is pending, and SETUP-002A adds Aug. 17 Pass 1/Pass 2 research receipts without enabling Shadow. All are bound to the final canonical activation identity. |
| Immediate operational work | Preserve and adjudicate the Aug. 17 opening, Paper, and successor-setup research receipts. Verify the first research denominator, provider-bound exclusions, cutoff hashes, outcome separation, and production nonmutation. Present R034's exact deletion plan only when Steven is ready. |
| Broker state | Schwab OAuth and immutable `2573` `INDIVIDUAL_CASH` binding remain read-only market-data/account evidence. No transmitting Schwab method exists. The Canary Alpaca Paper credential is encrypted outside Git. The exact Paper host accepted and completed one bounded fractional lifecycle; the activation preflight found the account active with `$100` cash/buying power, zero positions, and zero open orders. The research credential slot is empty. Invalidated Paper v1 is archived; v2 is active with unchanged policy and no carried decisions, intents, positions, or orders. The live Alpaca host cannot be enabled by a mode flip. |
| Steven action | No routine nonvisual approval is pending. Interrupt Steven before funding, money movement, any live endpoint/order, unexpected brokerage scope, destructive R034 cutover, or visual acceptance. Do not ask Steven to re-enter the stored Canary credential. |
| Data caveat | Schwab remains authoritative for proven quote/candle evidence while execution-provider capability remains separate. Finviz structural schema/row/value drift is validated prospectively; structurally valid but economically implausible provider values remain the explicit ARGUS-DATA-008 risk. Historical raw payloads and raw/parsed row counts for August 7/10/11/12 were never persisted and remain unknown; their empty candidate sets are adjudicated contract failures and may not be interpreted as market no-trades. Schema drift is `ROOT_CAUSE_INFERRED` for August 7/10/11 and `ROOT_CAUSE_STRONGLY_CORROBORATED` for August 12, never confirmed for the exact opening runs. DATA-001 through DATA-004 retain their provenance, RVOL, setup, and same-session chronology gates. DATA-005 makes `$500` reference sizing nonexecutable; DATA-005A supplies fresh bound-account/portfolio evidence. Fractional support may alter provider-executable quantity prospectively but may never rewrite old allocation or Shadow evidence. Legacy RVOL remains research-only; insufficient candle history and unknown broker capability fail closed. |

### Status Legend

- `NOT_STARTED`: no implementation has begun.
- `ACTIVE`: work is underway on the named branch.
- `ACTIVE_ENGINEERING_PRECURSOR`: useful provider-neutral implementation is in progress, but consequential policy and activation remain intentionally unfrozen.
- `ACTIVE_PROVIDER_RESEARCH`: official contract research or isolated provider proof is the current implementation lane; production authority has not been granted.
- `IMPLEMENTED_PENDING_MERGE`: work is committed and verified on a branch but has not yet been integrated. Proven nonvisual work may integrate automatically; visual work waits for Steven's manual acceptance.
- `COMPLETE`: work is merged into local `master` and verified.
- `BLOCKED`: a stated gate or CEO decision prevents work from starting.
- `BLOCKED_VENDOR_CAPABILITY`: the required broker capability does not exist; implementation cannot proceed by configuration alone.
- `DEFERRED`: valid future work, intentionally not the current priority.

### Roadmap Governance

Status: `COMPLETE`

- The authoritative Roadmap is integrated into `master`; `CURRENT_STATE.md` remains deleted.
- This file is the single live state view; branch history and canonical paths are recorded in their supporting governance files.

## Roadmap

### Phase 0 - Office Scaffold

Status: `COMPLETE`

- Establish agent roles, operating rules, templates, branch policy, and protected-area rules.
- Keep governance separate from product runtime behavior.

### Phase 1 - Read-Only Mapping

Status: `COMPLETE`

- Map critical routes, data flows, scoring surfaces, replay surfaces, alerts, storage, and operator workflows.
- Use maps and audits to identify small, protected implementation slices.

### Phase 2 - Scoped Improvements

Status: `COMPLETE`

- Turn scoped findings into bounded Builder tasks with focused tests and protected-path review.
- Preserve scoring, readiness, replay, storage, and execution behavior unless the current task explicitly authorizes a bounded change; interrupt Steven only if scope or semantics must expand.

### Phase 3 - Release Discipline

Status: `COMPLETE`

- Maintain task, branch, decision, quality, and release evidence.
- Require Steven visual acceptance for GUI work. Integrate and non-force-push proven nonvisual work automatically when Git and secret checks are clean.

### Phase 4 - Automation And Simulation Foundation

Status: `COMPLETE` on `origin/master`

- Use neutral product terminology: Automation, Simulation, Machine Room, Risk Governor, Execution Ledger, Trade Plan, and operator review.
- Keep `Argus` as the Codex builder and office persona, not a product-screen or product-flow name.
- Retain the existing Python simulation foundation: TradePlan, Risk Governor, FakeBroker-only simulation, Execution Ledger, and Execution Auditor.
- Keep every paper and live execution boundary locked.

### Phase 5 - C# WPF Operator-Surface Feasibility

Status: `COMPLETE / DIRECTION ACCEPTED`

- Preserve Python as the canonical engine for research, scoring, readiness, replay, storage, trade planning, risk, and simulation.
- R004 proved the Windows-first WPF workstation shell: docked and floating panes, linked contexts, persistent layouts, recovery behavior, and simulation-only safety language.
- R005 proved close-to-tray behavior, single-instance activation, lifecycle controls, restricted tray commands, and physical Windows tray behavior.
- WPF is the accepted planned operator surface, subject to continued phase-gated validation; it is not a Python-engine rewrite or broker integration.
- Keep Hide, Pause Monitoring, and Exit as separate lifecycle operations. Tray or layout state must never store execution authorization, credentials, API keys, broker permissions, or order-routing permissions.

### Phase 6 - Python Simulation Foundation And Evidence Research

Status: `COMPLETE` on `origin/master`

- `momentum_hunter/autonomy/*`, `trade_planning.py`, and the current Python UI modules remain the canonical implementation on `master`.
- The clean-room simulation foundation and hardening tests are merged on `master`.
- Technical Breakout Research Engine v1 and its daily OHLC source are merged on `master`; they remain research-only and do not alter production scoring or execution behavior.
- The older standalone execution-model branch and earlier simulation branch are superseded; see `BRANCH_LEDGER.md`.

### Phase 7 - WPF Workstation And Background Lifecycle

Status: `COMPLETE`

- R004 and R005 are integrated into `origin/master` at `e14105493061ec133ecd273aaac21d8e33ead5cf`.
- R004 supplied the workstation shell: docked, tabbed, floating, resizable panes; linked chart contexts; saved layouts; SQLite recovery; and simulation-only safety language.
- R005 originally supplied close-to-tray behavior, explicit exit, session-ending behavior, single-instance signaling, restricted tray commands, and an in-process background-collection lifecycle. Physical Windows QA passed.
- Under the original R005 boundary, collection continued only while the hidden WPF process remained alive.
- Phase 8 superseded that hosting limitation. The independent Python Engine Host is now canonical, and a WPF close or crash does not inherently stop it.
- Explicit Exit remains the deliberate joint-shutdown path for the workstation and its managed Python host.

### Phase 8 - Headless Python Engine Through Versioned Contracts

Status: `COMPLETE` on local and remote `master` through `a886c90`

- The approved Goal Charter creates versioned, provider-neutral host identity, health, collection, capability, command, and structured-error contracts.
- `momentum_hunter/engine_host.py` owns the independent loopback-only Python Engine Host. WPF discovers an existing host or launches one, reconnects by host identity, and deliberately shuts it down only on explicit Exit.
- The host has an atomic single-host lease, per-command idempotency, non-overlapping cycle guard, and a guard against the existing active-monitor runner starting a second collection loop.
- The host core owns snapshot, pause, resume, one collection cycle, and graceful shutdown. Phase 9 adds one versioned persisted-evidence snapshot capability; TradePlan, Risk Governor, chart data, simulation, broker, Paper, and Live remain outside the boundary.
- Focused Python process proof and .NET integration proof passed. The implementation fast-forwarded into local `master` and was later backed up through the approved R011 master push. See `reports/releases/ARGUS-R008-python-engine-contract-host.md`.
- ARGUS-SERVICE-001 extends this boundary with a Windows Service wrapper and
  restart-safe scheduler. It is installed, Running/Automatic, and has passed
  its installation canary and exact-response Codex probe. ARGUS-SERVICE-004
  adds the separate reboot-without-login proof tooling. The first reboot
  started Windows and the service but failed before canary execution on an
  invalid generated job ID; ARGUS-SERVICE-005 repairs and production-validates
  that manifest. The final exact-time forced-restart repeat now passes with a
  new boot, new service instance, Session 0, and zero interactive sessions.
  Codex is an optional read-only downstream reviewer, not a runtime authority
  and not an order path.

### Phase 9 - Read-Only Discovery, Research, Health, And Replay Integration

Status: `COMPLETE` on local and remote `master` through `a886c90`

- Connect WPF panes to the Phase 8 read-only boundary for candidates, evidence, research context, health, and replay.
- Preserve source lineage, stale-data language, and read-only replay identity.
- Use the independent engine lifecycle rather than a workstation-owned collection loop.
- The first slice exposes persisted report/status snapshots only and explicitly disables mock TradePlan, chart, risk, and simulation fallback until Phase 10.
- Focused Python tests, focused C# presentation/integration tests, a C#-to-Python host proof, broader nearby Python regression, the full .NET suite, and full Python discovery passed before the Steven-approved local fast-forward.

### Phase 10 - Trade Planning, Risk, And Simulation Integration

Status: `COMPLETE` on local and remote `master` through `a17eff8`

- The versioned Python host exposes a persisted-plan simulation workspace snapshot and a symbol-scoped FakeBroker-only simulation command.
- WPF consumes the canonical persisted TradePlan, Risk Governor, Execution Ledger, and Execution Auditor evidence rather than a mock fallback. R011 adds chart evidence separately and does not alter these planning or simulation contracts.
- A Risk Governor block prevents the simulation call and states that no evidence changed. A permitted simulation records risk, preview, FakeBroker outcome, and audit evidence in the in-memory host ledger.
- Follow-up commits `14fe317` and `893a6da` remove the Top-5-only plan mapping mismatch and the empty Risk Governor badge: all valid persisted candidate plans are exposed, and a missing plan explicitly shows `Plan unavailable` with simulation unavailable rather than a blank colored state.
- Steven accepted the manual visual proof and approved the local merge with real chart candles still explicitly deferred. Release compilation passed; focused Python simulation/autonomy tests passed 29 tests, and the full .NET workstation solution passed 71 tests immediately before merge. Full Python discovery was previously bounded at 120 seconds and did not complete; retain that test-harness timeout as a follow-up risk.

### Phase 11 - Shadow Evidence, Schwab Capability, And Pre-Execution Hardening

Status: `ACTIVE`; the prior SHADOW-017 opening-runtime repair and Schwab
read-only foundations are `COMPLETE` on synchronized `master`; the
SHADOW-017 live-position-marking amendment is
implemented and visually accepted, while its 2026-07-30 prospective opening is
`FAILED_TASK_DID_NOT_RUN`;
v1 and activated-empty v2 are preserved at `0 / 30`, prospective v3 is
activated-empty and unarmed at `0 / 30`, A017 is
`BLOCKED_VENDOR_CAPABILITY`, and every real-order gate remains closed.

#### 11A - Shadow Trading Evidence Program

- ARGUS-SHADOW-017 live position marking adds a five-second quote loop only
  while a current official FakeBroker order/position is active. The existing
  five-minute candidate/decision cycle remains unchanged. Active quotes are
  read-only, exact-symbol Schwab market-data requests with a frozen ten-second
  age limit. Python persists bid/ask executable marks and lifecycle evidence;
  WPF consumes the versioned cached snapshot only. The material cadence change
  requires `official-shadow-v3` and
  `prospective-fakebroker-live-mark-v2`; Steven accepted all seven WPF checks
  and implementation `94f5074` is integrated and backed up, while final-head
  task/proof rebinding remains pending.
- ARGUS-SHADOW-001 is integrated into local `master` at `bb962be`. It connects frozen current evidence to canonical TradePlan and Risk Governor decisions, conservative quote-driven FakeBroker orders/positions/exits, durable ledger/audit/outcomes, executable P&L/R/MFE/MAE, sample-gated metrics, and a nontransmitting manual paperMoney ticket.
- ARGUS-SHADOW-002 is integrated into local `master` after Steven's explicit fast-forward approval. It adds a read-only WPF review surface over canonical Shadow/FakeBroker evidence; it creates no execution authority and cannot edit completed trades, plans, or risk decisions.
- ARGUS-SHADOW-003 is integrated into local `master` after Steven's explicit fast-forward approval. Implementation `9002df0` freezes sample version, strategy/configuration fingerprint, fill-model version, evidence-schema version, and explicit sample authorization on new records; preserves legacy records without backfill; excludes unauthorized, obsolete, malformed, or mismatched records; gates every aggregate metric path; and exposes a read-only `SAMPLE START LOCKED` audit in WPF.
- Python owns the prospective sample lifecycle and durable evidence. WPF is a bounded review surface only. FakeBroker remains the only automated execution boundary, and every Shadow decision must be prospective.
- Shadow-002 proof visibly shows: `X / 30` eligible completed trades; active, unfilled, rejected, excluded, and invalid states; evidence and plan locks; decision and evidence timestamps; ideal versus estimated executable results; spread/slippage/fill explanation; P&L, R, MFE, MAE, duration, and exit reason; linked Chart, frozen Trade Plan, Why, and History/Activity drill-down; and minimum-sample gating.
- The official sample may start only after Shadow-001 is in the active baseline, Shadow-002 is accepted and integrated, evidence snapshots/TradePlans/Risk decisions are immutable, stable IDs connect candidate/evidence/plan/risk/command/ledger/outcome, duplicate commands and restart duplicates fail closed, P&L/MFE/MAE are reproducible, fill/spread/slippage assumptions are documented and locked, market-session/time-zone behavior is verified, and data-quality eligibility is deterministic.
- Every counted Shadow Trade must record a `SampleVersion`, strategy/configuration fingerprint, fill-model version, and evidence-schema version. Shadow-003 makes these requirements canonical on local `master`; their engineering `PASS` state has no command or side effect that begins sample collection.
- ARGUS-SHADOW-004 adds a CLI-only, write-once activation record for `official-shadow-v1`. It creates no trade, report, ticket, provider request, broker call, or order. Production services load the record automatically; a direct in-memory authorization flag without persisted evidence fails closed.
- The official sample activated at `2026-07-25T18:18:58.477916-05:00` and remains empty at `0 / 30`. Report generation and source capture must both be offset-aware, at or after activation, ordered correctly, and no later than the decision. The June 17 CRWV report was deliberately rejected and left no Shadow state file.
- The activation file is local generated state under ignored `MomentumHunterData`; it is not tracked or pushed. Its immutable SHA-256 is `6980D5734F3F2010D892CD1F3E29354D5DF37B193B082B18A01D8B5D485AD20C`.
- ARGUS-SHADOW-005 makes each successful scheduled capture produce the canonical CSV/JSON/Markdown TradePlan report exactly once. It validates source path, timestamp, session, prospective ordering, and candidate count; refuses partial output sets; verifies the raw capture hash did not change; and can recover the missing derived report on a duplicate scheduled run without rescanning.
- The Finviz scan now reads its required candidate fields from one custom screener response. Quote/news requests remain read-only and bounded separately, preventing the old per-symbol full retry schedule from overrunning the 30-minute Windows task limit.
- Steven approved deterministic automatic selection and rejected operator selection for the official sample. SHADOW-006 implements canonical rank/score/identity ordering and preserves the complete ordered assessment with every rejection reason; Risk Governor remains an eligibility gate rather than a ranker.
- The blanket 30-minute freshness proposal is rejected. The accepted initial matrix is: current selection quote no older than 30 seconds, source capture no older than 10 minutes, report no older than 5 minutes, and report-to-selection delay no longer than 60 seconds. Daily OHLC and catalyst age use separate rules. Missing, future-dated, timezone-ambiguous, or contradictory clocks skip the cycle.
- A production audit found that Active Monitor refreshes report-level `generated_at` even when copied candidate bid/ask values were not fetched again. The observation schema now keeps monitor-cycle time separate from provider quote time/source. Shadow selection, fills, and counterfactuals consume only independently identified provider quote time/source; legacy or current rows without them fail closed as quote unavailable. Alert-cycle timing and alert thresholds are unchanged.
- The canonical baseline includes a read-only Schwab Market Data quote source at the exact `/marketdata/v1/quotes` endpoint. It requests candidates and SPY/IWM once per cycle, uses the oldest provider `bidTime`, `askTime`, and `quoteTime` as executable time, refreshes expired OAuth only through the immutable sole-`2573`-CASH read-only account revalidation path, and records only requested symbol-matched finite evidence. The quote transport has no account endpoint; no order endpoint or transmitting method exists. Live weekend proof parsed the provider response and rejected it as stale, closed, and extended-hours; one canonical in-market 30-second proof remains before arming.
- `docs/argus-office/autonomy/SHADOW_SAMPLE_CONSTITUTION.md` is now `IMPLEMENTED_CANONICAL_NOT_AUTHORIZING`. Runtime and tests implement its ranking, warning severity, freshness, quote boundary, duplicate/portfolio, session, denominator, benchmark, diversity, and hash rules. It still grants no authority to arm or begin Trade 1.
- The compile-time construction switch is replaced by a write-once selector-arm record. Arming requires the exact internal phrase and the complete named set of structured proof artifacts, each bound to the current activation, sample, constitution, runtime build, verification time, and hash-verified evidence. `selector-arm-check` runs that verifier without mutation; `selector-arm` uses the same verifier before creating policy or arm state. Partial proof creates neither policy nor arm state; later source or proof changes invalidate the arm.
- Every armed in-window five-minute Engine Host attempt is a denominator record; restart gaps become `SYSTEM_DOWNTIME`. Reports, stale/data-quality blocks, selections, unfilled/cancelled orders, completions, and failures are counted separately.
- Eligible-candidate, deterministic-random, SPY, and IWM observations are preserved without creating trades. Completed-trade cycles finalize comparable returns at the selected trade exit; open/no-trade cycles remain explicitly mark-to-latest.
- The 30-trade gate releases descriptive metrics only. At least 10 distinct trading sessions are required for broader strategy review, and concentration is reported without altering selection.
- Trade 1 cannot occur from a feature branch or an unbacked local build. SHADOW-004/005 and the hardened selector must be committed, fast-forwarded into canonical `master`, and non-force backed up before the selector can become armed.
- SHADOW-008 provides the production proof-bundle ceremony. Static preparation is atomic and write-once, requires clean synchronized `master`, verifies the accepted SHADOW-004 UI evidence and every named static gate, and creates 11 artifacts without arming. Finalization accepts only schema-v2 live Schwab CLI evidence for the exact candidate plus SPY/IWM, revalidates every hash and context, adds the twelfth artifact, and remains nonmutating. The final arm is still a separate command.
- SHADOW-009 removes caller-selected quote-proof identity: finalization derives the highest canonical-ranked symbol from the newest fresh report, validates its provider/schema/clocks, validates source-capture path/time/session/count/symbol identity, and preserves report/capture/quote bytes plus a hash-bound binding artifact.
- SHADOW-009 adds one distinct immutable `shadow` capture at 9:35 AM ET per XNYS market-open day, followed immediately by the existing Engine Host cycle. The handoff is report-hash-idempotent, retries a complete duplicate report only when its write-once host receipt is missing, and does not rescan, transmit, arm, or create an official trade by itself.
- SHADOW-010 automates the already-authorized nontransmitting arm ceremony before that handoff. It proves canonical Git/static evidence before contacting Schwab, derives the three-symbol quote request from the canonical report, accepts only normal live Schwab quote provenance, finalizes and re-verifies all 12 artifacts, and supplies the existing exact arm confirmation only after the verifier passes. Any failure stops before the selector cycle; an already valid arm is nonmutating and skips market-data work.
- SHADOW-011 fixes proof-clock ordering discovered during the pre-open audit. The quote proof records request start before guarded OAuth/provider work, evaluates freshness after the response, rejects backward or timezone-naive evaluation clocks, and records actual request duration. This changes no freshness threshold and weakens no future-data rejection.
- SHADOW-012's scheduler-native restart design is superseded by SHADOW-013's runner-owned bounded retry classifier. One initial attempt plus three retries occur only for recognized provider/network/host infrastructure failures; terminal policy or evidence failures stop after one attempt.
- SHADOW-013 makes receipt completeness semantic, requires verified host/capture/report/cycle identities, preserves incomplete receipts, adds pre-arm and per-decision clock-skew proof, freezes configuration/task identity, and separates outcome-update status from opening success.
- The default SHADOW-013 scheduled action is proof-only and unarmed. The installer leaves the Shadow task disabled unless explicitly enabled, and the runner omits selector/Engine Host invocation unless the separately explicit arm switch is present. The 8:50 heartbeat is finite, tri-state, and inspection-only.
- SHADOW-017 preserves the real 2026-07-29 v1 market/proof evidence but excludes it from the official sample because the stale schema-2 Engine Host rejected the schema-3 arm before any decision cycle or handoff existed. V1 closes at `0 / 30`; no retrospective selection or Trade 1 may be fabricated.
- SHADOW-017 makes loaded Engine Host build/schema identity explicit, gracefully replaces only an authenticated idle stale host before an armed ceremony, defers replacement during an active cycle, and keeps proof-only operation nonmutating.
- SHADOW-017 restores finite runner retries when native Python writes retryable diagnostics to stderr. `official-shadow-v2` uses separate state/activation/policy/arm/cycle files so v1 evidence remains byte-preserved.
- A live Task Scheduler contention drill proves an independent non-market canary still starts within `2.345` seconds while 922 Python tests run. Opening execution never depends on a Codex heartbeat or chat interruption; protected task code instead remains frozen in its canonical worktree.
- Once a sample version starts, it permits no historical backfill, deletion of losers, selective exclusions, scoring/readiness/risk changes, entry/stop/target changes, spread/slippage/fill-model changes, or silent recomputation.
- If a material defect invalidates evidence, preserve the affected sample, close its version, document and fix the defect, and begin a new version. Never rewrite the affected sample into a cleaner result.
- FakeBroker evidence must model and record bid/ask spread, slippage, unfilled and delayed limit fills, supported partial fills, gaps through stops, halted/unavailable states, stale/missing quote rejection, session eligibility, buying power, position concurrency, daily-loss limits, restart recovery, and ambiguous states. Track both ideal setup and estimated executable results; estimated executable result is the primary evidence metric.
- Report evidence checkpoints at 5, 10, 20, and 30 completed eligible trades. Interim reports evaluate mechanics and evidence quality and must not tune the strategy to the developing sample.
- Thirty completed eligible trades is an initial engineering gate, not proof of a durable edge, a profitability claim, or permission to transmit any broker order.
- ARGUS-SHADOW-024 is implemented, Hard-Chew verified, integrated, and backed up
  through `cd43852`.
  It builds deterministic, sanitized, write-once JSON/Markdown packets from one
  terminal trade or no-trade evidence chain. It validates current sample/policy,
  report, handoff, cycle, selection, lifecycle, and input hashes; separates
  facts, derivations, missing values, and questions; and never invokes Codex,
  Schwab, a broker, the service, Engine Host, WPF, or a scheduler. Focused tests
  pass 17/17, adjacent Shadow/Engine Host tests pass 225/225, and full discovery
  passes 1,051/1,051. Status is `COMPLETE_AND_BACKED_UP`; Monday's evidence
  prerequisite passed.

#### 11B - Schwab Read-Only And Canary Preparation

- ARGUS-SERVICE-004 provides the one-use reboot-without-login canary gate. It
  records a pre-reboot boot and service-instance baseline, schedules only a
  nonmarket account/DPAPI canary plus an optional downstream exact-response
  Codex probe, and verifies post-boot service, Engine Host, receipt, account,
  Session 0, zero-interactive-user, and no-order evidence. It never schedules
  Shadow, restarts the service during preparation, reboots Windows, reads
  positions, requests orders, or enables transmission. Tooling is complete on
  canonical `master`. The first physical attempt failed before canary
  execution on the repaired job-ID defect. The final exact-time forced-restart
  attempt at 2026-07-31 16:39 Central passes every verifier gate and is
  archived without deleting the failed or invalid attempts.
- A016's Schwab/thinkorswim continuity decision is superseded for execution
  research by ARGUS-BROKER-ALPACA-001. Schwab Support's confirmation that Trader
  API cannot access paperMoney and has no retail sandbox remains true; Schwab
  remains the proven market-data source rather than the Paper execution lab.
- FakeBroker remains the only currently integrated automated execution boundary.
  Alpaca Paper is now the preferred next execution laboratory pending official
  documentation and direct Paper proof. thinkorswim remains optional manual
  visual/paperMoney reconciliation and is not a runtime dependency.
- SCHWAB-001/002/002A/003, live `CASH` validation, immutable binding, and bound-refresh safety are integrated. The production app, loopback callback, certificate trust, OAuth, DPAPI vault, and sole `2573` `INDIVIDUAL_CASH` binding are active and read-only.
- Account discovery and validation fail closed on any unexpected account count, suffix, type, hash, position, or permission. Sensitive account and balance values remain suppressed.
- The Client Secret was surfaced to the browser-automation channel during portal research. No credential or token was found in Git, but no rotation occurred. Read-only use continues under the recorded risk; transmitting code is blocked until Schwab supplies rotation, replacement, or explicit vendor remediation.
- The first future real-money gate is a broker-plumbing canary using a boring, liquid, preapproved instrument. A strategy-driven canary is separate and later. Pre-canary, canary-active, and post-canary position invariants must be implemented first.
- Detailed chronology, certificate identifiers, test counts, containment evidence, and remaining gates are preserved in `reports/security/SCHWAB-READONLY-ONBOARDING-AND-CREDENTIAL-INCIDENT.md`.
- No task may ask for a Schwab username, password, or MFA; place credentials/tokens/account hashes in Git or chat; automate thinkorswim; or transmit, replace, or cancel a real broker order without the applicable Steven decision.

#### Standing Authorization And Branch Discipline

- Standing-authorized nonvisual work includes bounded Shadow implementation/repair, evidence collection, Paper-only Alpaca documentation/adapter/lifecycle work after expected credential handoff, manual paperMoney reconciliation artifacts, authenticated read-only Schwab calls, OAuth refresh, exact canary binding when one `2573` CASH account revalidates, tests, reports, Roadmap updates, commits, clean fast-forward merges, and non-force pushes. Funding, live endpoints, live orders, and money movement remain explicit interruption gates.
- Steven checkpoints apply to GUI/visual acceptance and the anomaly/consequence list in this Roadmap. Real broker transmission, destructive data/schema operations, credential or provider-app revocation, paid services, and protected semantic expansion remain interruption gates.
- Keep one active implementation branch and at most one stacked successor. Begin new work from the integrated local baseline. The official Shadow sample may begin automatically after every frozen prerequisite passes; any failed or ambiguous prerequisite interrupts Steven.
- R027 must preserve both validated parents: current Shadow `master` and R026. R026 and TEST-001 become source/audit branches after combined verification; do not rebase or rewrite either history merely for linearity.

### Phase 12 - Incremental Capability Migration And Qt Retirement

Status: `ACTIVE`; R011-R029 plus Shadow-001/002/003 are `COMPLETE` on local `master`; remaining Qt retirement stays incremental

- R011 adds one versioned `get_chart_snapshot` host command backed only by stored `opportunity-minute-bars.json` and `daily-ohlc-bars.json` evidence.
- WPF renders `1m`, deterministically aggregated `5m`/`15m`, and `Daily` candles with bodies, wicks, and volume. Source lineage and `AVAILABLE`, `STALE`, `INSUFFICIENT_DATA`, or `UNAVAILABLE` state remain visible.
- Missing intraday evidence never falls back to daily or mock candles. No provider call, background fetch, or source-data write was added.
- Candidate, interval, linked-pane, and pinned-pane context are covered by tests. The full CLI-only WPF proof shows CRWV with 143 stored stale 5-minute candles, source/as-of text, simulation-only language, and paper/live locks.
- Steven approved R011; Git Steward fast-forwarded it into local `master` without a merge commit and backed it up to `origin/master` under separate explicit push approval.
- R012 adds deterministic nice price ticks, chronological UTC time ticks, and a latest stored-bar OHLCV strip without changing the chart contract or Python engine.
- R012 focused tests passed 14 tests, the complete .NET suite passed 88 tests, Release compilation passed with zero warnings, and the offscreen WPF proof shows readable axes/details while preserving source lineage, simulation-only language, and paper/live locks.
- R012 was accepted, fast-forwarded, and pushed with local and remote `master` synchronized at `69feedf`.
- R013 through R025 remain preserved on R026 and are fully integrated with the current Shadow baseline on local `master` through Steven-authorized R027.
- R027 preserves Shadow snapshot/start/advance commands, automatic post-collection observation, read-only Shadow Review, sample lock, and FakeBroker-only boundaries alongside technical research, saved watchlist, Daily Workflow, Candidate Story, Research Maturity, command palette, chart inspection, health, replay, monitoring, activity, and alert/outcome evidence.
- R027 passed Python compileall, full discovery at 672/672, 163 presentation tests, all 210 .NET tests, zero-warning Release compilation, no-live-capability and protected-path review, source-nonmutation checks, and fresh UI proof. Manual review passed the required `CRWV` / `5m` candle and hover cases and provisionally accepted the current Trade Plan evidence tabs pending broader market data. Repair commit `f84106a` and palette repair `cd09f1b` resolved clipped interval text, meaningless sync labels, no-op pane actions, unrecoverable pane removal, and focus-loss dismissal. Live Windows verification confirms the truthful palette miss, complete Current pane menu, Research Maturity opening, single global mode treatment, first-class `Test Trade Review`, final compact toolbar, and persistence of the palette/query across a Codex-to-workstation focus round-trip. The palette is inside the main window and creates no second taskbar or Alt+Tab window. Steven manually accepted the final visual check and explicitly authorized the local fast-forward merge.
- Real candle-data cutover has a mandatory destructive-operation interruption gate. The active legacy artifact is `MomentumHunterData/data/opportunity-minute-bars.json`, SHA-256 `DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69`; its current SQLite mirror contains 710 `CRWV` rows tied to that exact path and hash. Immediately before activating an actual candle source, stop and tell Steven the exact deletion targets and effect before removing the legacy JSON or rebuilding mirrored rows. Cutover cannot pass until the old hash is absent from every active candle store, none of the old 710 rows can be queried or rendered, source lineage names the actual provider and fresh timestamp, and regression/UI proof shows no mixed legacy/live candles. Do not delete the legacy data early or treat an archive/backup as an active chart source.
- R028 integrated-workstation chrome is `COMPLETE` on local `master`. The implementation removes the separate light Windows strip and makes app identity, workspace navigation, the single global mode state, and system controls one continuous dark surface through WPF `WindowChrome`. It uses the native caption and resize contract rather than a borderless imitation, routes caption buttons through `SystemCommands`, provides an explicit `Alt+Space` menu path, declares `PerMonitorV2` through the supported project property, and keeps a single dormant red badge treatment for any future separately approved real-money label. Focused tests pass 4/4, all current .NET tests pass 215/215, and the zero-warning Release build passes. Steven manually passed the dark title surface, drag, double-click maximize/restore, left/right Snap, four-edge/two-corner resize, minimize/maximize controls, `Alt+Space`, cross-monitor movement, and restored/maximized no-clipping checks. This visual shell task grants no broker, live-mode, credential, or execution authority.
- R029 canonical WPF launcher and icon are `COMPLETE` and backed up through `origin/master`. `run.py`, the tracked batch/VBS path, the startup script generated by `momentum_hunter.startup`, and the PowerShell helper converge on a resolver that launches only the checkout Release WPF executable or a deliberately installed local workstation. Unmerged review builds are not auto-selected; missing WPF fails visibly; direct legacy Qt startup requires `python -m momentum_hunter.app`. Focused launcher tests pass 9/9, full Python discovery passes 679/679, all .NET tests pass 215/215, and Release compilation passes with zero warnings/errors. Physical verification opened the checkout Release WPF executable, retained one responsive process on a second launch, redirected the stale R027 Start Menu entry, removed all 20 obsolete local review packages, and passed the current icon/tooltip/single-window checks. Git Steward fast-forwarded the verified stack into local `master` through `1d3d8e5`; Steven separately approved the later remote backup.

#### ARGUS-R031 - Schwab Intraday Candle Capability And Contract

Status: `COMPLETE`; implementation integrated on local `master` through
`404c589`, with live proof accepted with limitations

- Contract implementation identifies Schwab `CHART_EQUITY` WebSocket messages
  as the expected near-live one-minute source and `/pricehistory` as historical
  retrieval and gap-repair evidence. It does not treat `/quotes` as candles.
- The isolated implementation preserves every Streamer arrival in arrival order,
  classifies first observations, identical replays, revisions, out-of-order
  updates, and gaps, binds session/source identity, and compares the final
  observed stream version with price history without granting canonicality.
- Do not infer candle capability from the existing `/marketdata/v1/quotes`
  path. Bid/ask snapshots are not authoritative trade-volume bars.
- The provider-neutral candidate contract includes symbol,
  interval, open/high/low/close/volume, bar-start/end identity, session,
  completion state, provider/source lineage, provider timestamp, receipt time,
  correction/version identity, and explicit quality state.
- Fail-closed validators cover unsupported capability, stale or partial
  responses, ambiguous timestamps, duplicate/out-of-order/corrected bars,
  missing intervals, session boundaries, and rate exhaustion.
- Focused tests pass 23/23, adjacent contract tests pass 77/77, and full Python
  discovery passes 1,040/1,040 on the R031 branch. No generated output or secret
  is tracked.
- The full market-hours proof subscribed to SPY, IWM, and current rank-one
  candidate NVDA for 15 minutes. It observed 48 complete streamed minutes with
  one update per symbol-minute and first-arrival latency of 62.147 to 87.645
  seconds from the bar-start timestamp. Entitlement, transport, shape, and
  `/pricehistory` access pass.
- Stream and history OHLC matched for all 48 comparable minutes. Five NVDA
  volume fields differed only by fractional stream tails versus whole-number
  history values. The proof therefore grants no stream-only canonicality.
- Schwab exposed no explicit completion marker in the observed frames, and the
  run did not prove a current forming-minute update, late correction, reconnect,
  halt behavior, or production subscription ceiling. These remain explicit
  R032 acceptance limits rather than guessed provider semantics.
- Live-shape repair accepts Schwab's object acknowledgement, keyed symbol,
  nonnegative sequence, and observed field map; it rejects conflicting identity
  or malformed frames immediately before any history request.
- Read-only verification and contract work only. Do not write production data,
  change the service manifest, query accounts/orders, add WPF provider calls,
  or modify the installed runtime. If official documentation does not prove a
  safe candle source, stop at `BLOCKED_VENDOR_CAPABILITY` rather than deriving
  candles from sparse quote snapshots.

#### ARGUS-R032 - Schwab Incremental Candle Collector

Status: `COMPLETE`; bounded collector and exact-code live proof verified

- The bounded resolver uses the exact-date opening report, selected and active
  symbols, the top five Hunter candidates, SPY, and IWM, with deterministic
  priority, source fingerprints, visible exclusions, and a ten-symbol ceiling.
- Python owns provider access, normalization, quality classification, and
  persistence. WPF never calls Schwab. Guarded account-identity revalidation is
  limited to the expected sole account; positions, previews, and orders are not
  requested. Candidate ranking, Risk Governor, selection, fill, and execution
  semantics are unchanged.
- Daily/symbol partitions persist stream and history versions idempotently with
  source lineage. The store detects and reports gaps, duplicates, out-of-order
  delivery, provider corrections, stale responses, incomplete/unreconciled
  bars, session transitions, tampering, and bounded retry state. Conflicting
  evidence is never silently overwritten.
- Never mix Schwab bars and legacy candles beneath the same source identity.
  Keep the existing CRWV artifact and its SQLite mirror untouched until R034.
- Thirty focused tests, 89 complete Schwab candle-stack tests, 1,173-test full discovery,
  and an external exact-code live proof pass. The live result is truthfully
  `PARTIAL` for sparse extended-hours gaps while stream and history transport
  both pass. R032 remains manually invoked and has no Engine Host/WPF consumer.

#### ARGUS-R032B - Schwab Historical Candle Backfill

Status: `VERIFIED_ON_INTEGRATION_BRANCH`; source commit `9f9ac96`

- Fill the product gap exposed by R033's visual review: the 60-second R032 proof
  is transport evidence, not a usable chart history.
- Request at most Schwab's documented ten-day one-minute window and one year of
  daily `/pricehistory` for the bounded R032 universe. Require at least 30
  minute and 20 daily rows per symbol or report `INSUFFICIENT_DEPTH`.
- Persist minute rows through `schwab-candles-v1`; persist daily rows in the
  separate `schwab-daily-candles-v1` store. Preserve source, provider timestamp,
  exact duplicate idempotency, corrections, A-B-A reassertions, and tamper-
  checked canonical history.
- Remain plan-only by default and unscheduled. Do not connect Streamer, invoke
  Engine Host/WPF, change Shadow/scoring/readiness/selection, query positions or
  orders, transmit, or mutate Yahoo/CRWV/SQLite/raw-capture evidence.
- Compileall, 16 focused tests, all 96 Schwab candle tests, all 1,196 source-
  branch Python tests, and the zero-network/zero-write plan CLI pass. The
  post-capture guarded proof inserted 39,165 minute versions and 1,260 daily
  bars for NVDA, SHOP, ZETA, SPY, and IWM with no findings, position/order
  request, or transmission.

#### ARGUS-R033 - Live Chart And Engine Host Integration

Status: `VISUAL_ACCEPTED / COMBINED_VERIFIED_PENDING_MASTER_INTEGRATION`;
source commit `c88faa4`

- Python remains authoritative and exposes versioned candle snapshots through
  the Engine Host. WPF consumes only that cached contract and performs no
  provider or account calls.
- Preserve one-minute source bars; derive 5m and 15m deterministically from 1m.
  Daily remains a separately identified source/aggregation contract rather
  than an implicit fallback.
- Surface provider/source, last completed bar, separately identified in-
  progress bar, provider and receipt times, quote/bar age, gaps, corrections,
  stale state, and insufficient-data state. Missing bars must never be replaced
  with mock, daily, legacy, or quote-derived candles.
- Cover candidate changes, linked and pinned panes, selected/active symbols,
  reconnects, stale transitions, corrections, and no-data states with Python,
  contract, .NET, and visual proof. Steven remains the visual acceptance gate.
- The branch implements Python chart schema 2, a cached Engine Host contract,
  five-second WPF refresh, canonical/provisional/corrected/gapped states,
  provider/timing/gap/correction evidence, deterministic 1m-to-5m/15m
  aggregation, and a separately identified Daily source with no fallback.
- The first sparse proof was correctly rejected. The repaired chart uses a
  six-pixel dense bounded viewport and meaningful R032B history; Steven accepted
  its 1180x820 and 1920x1080 proof on 2026-08-06. The combined branch reads
  Daily only from validated `schwab-daily-candles-v1`, returns 180 Daily bars
  for every five-symbol proof input, rejects legacy/tampered Daily evidence,
  passes all 1,203 Python and 250 .NET tests, and builds Release with zero
  warnings or errors.

#### ARGUS-R032C - Automatic Bounded Symbol Backfill Queue

Status: `COMPLETE`

- When a symbol enters the current Hunter candidates, saved watchlist, selected
  chart, or active FakeBroker-position universe, inspect the canonical minute
  and Daily stores before requesting data. Render cached bars immediately.
- If required history is absent or below the explicit depth/freshness contract,
  enqueue one coalesced background backfill for that symbol. Repeated clicks or
  duplicate universe membership must not create duplicate provider work.
- Keep the universe bounded and prioritized: active position, selected symbol,
  Hunter candidates, watchlist, then SPY/IWM. Enforce the existing ten-symbol
  provider ceiling per batch and finite retry/backoff limits.
- Expose `LOADING HISTORY`, last successful refresh, failure, insufficient-
  depth, and stale states through the Engine Host contract. WPF remains a
  consumer and never calls Schwab directly.
- Preserve plan-first validation, sole-account read-only guard, source-specific
  stores, atomic/idempotent writes, provider timestamps, corrections, gaps, and
  no legacy/Yahoo/quote-derived mixing. No score, readiness, Shadow, Risk
  Governor, account-position/order, transmission, service-opening, or R034
  deletion behavior changes.
- Prove cache-first rendering, queue coalescing, new-symbol backfill, restart
  recovery, bounded retries, malformed/tampered input, source nonmutation, and
  the transition from loading to populated 1m/5m/15m/Daily snapshots.
- Implementation proof is complete: one chart request
  queues work without blocking, repeated five-second requests coalesce, one
  interrupted job recovers after Engine Host restart, malformed state and
  tampered candle stores fail closed, and a successful synthetic load repaints
  from `UNAVAILABLE / LOADING HISTORY` to 30 canonical candles. Steven accepted
  the loading/failure visual proof on 2026-08-06. Installed-runtime proof then
  loaded previously uncached QQQ to 180 stored candles on 1m, 5m, 15m, and
  Daily; after-hours staleness was represented honestly and no position/order
  method or transmission capability was used.

#### ARGUS-R034A - Legacy Candle Consumer Migration And Cutover Verifier

Status: `COMPLETE`; required non-destructive predecessor to R034

- Inventory and migrate every active reader/writer of
  `opportunity-minute-bars.json`. The alert outcome updater must not recreate
  the file after cutover; evidence-health, read models, source registry,
  technical-breakout research, and SQLite validation/reporting must consume a
  source-specific replacement or report the source as intentionally retired.
- Add a plan-only verifier that reports the exact legacy JSON identity, the
  exact matching SQLite rows, remaining code/config references, active Schwab
  store health, archive destination, and rollback conditions. It must make no
  source, database, provider, account, order, or runtime change.
- Preserve historical report identity and do not rewrite prior alert outcomes
  or breakout studies. Missing evidence remains missing; Schwab candles may be
  used prospectively only through an explicit source/version contract.
- Prove synthetic absent-file startup, outcome maintenance, evidence health,
  research reporting, SQLite validation, no recreation, no mixed-source chart,
  and source nonmutation before asking Steven for R034 deletion approval.
- Keep `daily-ohlc-bars.json` outside this task. It currently contains 79,298
  research-only Daily records across 263 symbols (SHA-256
  `2B1FDC1482D9D98A810D6F06AACDB7E9DE1E6123BE39E5F35634DF34C66BB521`)
  and is not read by the canonical WPF chart path.
- The active consumers now default to terminal, price-history-backed Schwab
  partitions; Streamer-only evidence is excluded. Explicit fixture paths remain
  available for historical tests, but the exact production legacy path is
  write-blocked and the old Yahoo minute-fetch compatibility flag makes no
  provider call.
- The plan-only verifier passes against production evidence: legacy SHA-256
  `DAAC049E...A6AD69`, 710 CRWV JSON bars, 710 matching/710 total SQLite rows,
  12,478 healthy canonical Schwab bars across CHYM/IWM/SPY/U, zero blocking
  references, unchanged input hashes, and an archive destination outside active
  candle stores. It implements no delete or write action.
- Hard Chew proof passes compileall, 44 focused consumer/cutover tests, all
  1,225 Python tests, all 251 .NET tests, `git diff --check`, protected-path
  review, source nonmutation, and zero-hit secret/network/account/order scans.
  R034 remains the only destructive step and still requires Steven's explicit
  approval. R034A is integrated and installed-runtime verification passes.

#### ARGUS-R034 - Legacy Candle Cutover

Status: `BLOCKED`; destructive-operation gate after R032C and R034A pass

- Stop and tell Steven the exact active deletion/rebuild targets and practical
  effect immediately before cutover. Approval for R031-R033 does not authorize
  R034 deletion.
- Archive the legacy CRWV evidence outside active chart stores, then remove the
  active legacy JSON and rebuild its 710 mirrored SQLite rows only after the
  actual source and rollback evidence are proven.
- Cutover fails unless the old SHA-256
  `DAAC049E4DA87729DE23B312D86B9034FF724F9BF4B2B8ED7FC1AFD293A6AD69`
  is absent from every active candle store, none of the old rows can be queried
  or rendered, and every active chart names the verified actual source and
  current timestamp.
- Regression and UI proof must demonstrate that legacy and Schwab candles can
  never appear in one active series. Do not delete legacy evidence early, and
  do not treat the archive as an active fallback.

- Migrate individual proven workflows to the WPF shell only after their Python contracts and operator proof are complete.
- Retire corresponding Qt screens incrementally, with acceptance evidence and rollback paths. Do not perform a broad rewrite.

### Phase 13 - Broker Execution Validation Gate

Status: `PAPER_ENGINEERING_V2_ACTIVE / AUGUST_14_DECISION_PROVEN / CONTINUOUS_INTRADAY_FOUNDATION_NEXT`

- A001-A003, DATA-005B, and the bounded A004 Paper-engineering runtime are
  integrated. The direct lifecycle proved fractional market/limit/stop/
  stop-limit behavior, replacement, cancellation, and exact liquidation. DATA-007
  proves the first two opening-dependent Paper results did not reach a strategy
  decision because provider contract drift emptied their reports; v1 is archived
  invalid and v2 starts prospectively with unchanged policy. Continue v2 until
  candidate-bearing evidence exercises account, allocation, entry, protection,
  and exit gates.
- ARGUS-DATA-008 adds a semantic plausibility gate between the structural
  provider contract and strategy evidence. It detects structurally valid
  but economically implausible values, including unexplained raw-to-qualified
  count collapse, impossible price/change relationships, severe disagreement
  with authoritative Schwab evidence where comparison is justified, candle or
  volume inconsistency, session/timestamp contradictions, suspiciously repeated
  cross-symbol values, and extreme distribution shifts. A plausibility failure
  must fail closed with preserved diagnostics; it may not silently substitute a
  fallback provider, average providers, alter scoring, or manufacture candidates.
  Intrinsic Finviz checks are wired before filtering/scoring; deterministic
  contextual Schwab/candle and baseline checks require explicit authoritative,
  time-aligned inputs and remain unwired. The August 14 gate is preserved and
  the implementation is included in the post-August-14 reconciliation.
- Continuous intraday discovery is the parallel foundation needed to escape the
  observed opening-scanner supply limit. The dormant provider-neutral contracts
  and SHADOW-025B through 025K runtime-boundary chain may integrate after
  current-head proof, but installed source/writer activation requires a separate
  writer-principal and credential-access decision and cannot be inferred from
  module presence.
- Broker capabilities are explicit data, never inferred. The capability model
  must distinguish fractional quantity precision and support for market, limit,
  stop, stop-limit, take-profit, bracket, OCO, OTO/OTOCO, replacement,
  extended-hours, status streaming, and broker-resident protection. Unknown is
  blocked. Strategy code must not branch on a provider name.
- Allocation preserves `idealRiskQuantity`, `providerExecutableQuantity`, and
  `finalAuthorizedQuantity`. Risk and setup quality define the ideal quantity;
  broker precision/order support defines executability; account/portfolio policy
  defines final authorization. Stock price alone is not a global universe gate.
- Paper research must preserve every independently eligible candidate and support
  prospective top-three/rank-conditioned analysis under a versioned configurable
  concurrency policy. It must not assume Rank 1, one position, three positions,
  or any fixed maximum is optimal. Counterfactuals remain separate and no
  retrospective trade may be manufactured.
- The canary-realistic and strategy-research lanes have separate capital, risk,
  concurrency, rank-participation, provider/fill, sample, and report identities.
  Material changes start a new prospective identity. Alpaca Paper results remain
  distinct from Momentum Hunter's conservative executable result and are not
  proof of live profitability.
- Paper mode uses an exact paper-host allowlist, separate local secrets, and
  structural rejection of live hosts. No secret may enter Git, logs, screenshots,
  evidence, chat, or documentation. No live adapter is enabled by a boolean flip.
- Schwab market-data and DATA-004 continuous same-session semantics remain in
  force. The 8:35 capture is a bootstrap, not the only trading window; missed
  breakouts remain immutable and new continuation/pullback/reclaim setups require
  new prospective evidence, setup ID, TradePlan, and Risk decision.
- Final classification after direct Paper proof is one of
  `ALPACA_PAPER_FRACTIONAL_EXECUTION_PROVEN`,
  `ALPACA_PAPER_FRACTIONAL_EXECUTION_PROVEN_WITH_LIMITATIONS`,
  `ALPACA_PAPER_FRACTIONAL_EXECUTION_UNSUITABLE`, or
  `ADDITIONAL_VENDOR_PROOF_REQUIRED`.
- The 2026-08-10 bounded direct lifecycle is
  `ALPACA_PAPER_FRACTIONAL_EXECUTION_PROVEN_WITH_LIMITATIONS`: fractional
  market/limit/stop/stop-limit, replacement, cancellation, client-order
  identity, and exact liquidation are directly proven. Partial-fill and restart
  recovery remain synthetic-only; bracket/OCO/OTO, status streaming,
  extended-hours execution, and broker-resident linked protection remain
  unproven and fail closed.

### Phase 13R - Specialist Intelligence Research And Strategy Diversification

Status: `STARTED - SPECIALIST-CONTRACT-001 AND STAT-DATA-001 IMPLEMENTED_PENDING_INTEGRATION`

Roadmap inclusion authorizes planning and bounded research preparation only.
It does not activate runtime imports, begin or modify a Paper sample, grant
order authority, or grant live authority. Every specialist begins as a
read-only or silent observer unless a later bounded task separately proves and
authorizes promotion. Momentum remains one opportunity specialist and the
current Momentum/Paper path remains the control against which incremental value
is measured.

The frozen Alpaca Paper engineering sample is unchanged. Specialist planning
must not alter its candidate rules, scoring, rank, candidate source, setup and
entry semantics, stop/target behavior, allocation or risk policy, execution
assumptions, lifecycle, or sample identity. These properties remain available
as the prospective control rather than being rewritten after specialist
outcomes are known.

Intended specialist architecture:

- Momentum: opportunity specialist and current prospective baseline.
- Regime: environment, exhaustion, volatility, and stress specialist.
- Technical Structure: deterministic chart-structure specialist.
- Event Shock: catalyst, relationship, and expected-versus-actual reaction
  specialist.
- Statistical Outcome: historical expectancy and uncertainty specialist.
- Execution Quality: liquidity, fill, and tradability specialist.
- Exit Intelligence: trade-management research specialist.
- Bearish Equity: later stock-shorting strategy family; no options work.
- Meta-Arbiter: later combination layer earned only through prospective
  evidence.

#### ARGUS-DATA-CORPACTION-001 - Analysis Price-Basis And Security-Identity Integrity

- Preserve raw provider candles unchanged and maintain a separately identified,
  analysis-consistent price/volume basis with complete lineage.
- Initial scope is forward splits, reverse splits, effective timestamps,
  adjustment factors, and symbol/security identity continuity where research
  requires it. Additional corporate actions require a named analysis gap.
- Every technical or statistical feature must identify its price basis and
  lineage so corporate actions cannot corrupt returns, ATR, moving averages,
  levels, patterns, gaps, MFE/MAE, or historical analogs.
- This is data-integrity work, not a split strategy. It grants no split score,
  candidate bonus, entry trigger, or strategy authority.

#### ARGUS-SPECIALIST-CONTRACT-001 - Common Specialist Opinion Contract

- Branch-local status: `IMPLEMENTED_PENDING_INTEGRATION` from `ea05615`; no
  runtime consumer, persistence path, arbiter, activation, or authority exists.
- Define one provider-neutral, read-only opinion packet containing specialist
  and version, opportunity/setup identity, as-of time, expiration, evidence
  hashes, opinion, confidence/calibration metadata, authority level, evidence
  families, and abstention reason.
- Support explicit `NO_OPINION`, `INSUFFICIENT_EVIDENCE`, and `OUT_OF_DOMAIN`
  abstentions.
- A specialist cannot place an order or silently mutate another specialist's
  evidence.

#### ARGUS-REGIME-002 - Exhaustion And Market-Stress Research

- Branch-local status: `IMPLEMENTED_PENDING_PARENT_INTEGRATION` on Specialist
  Contract parent `e65cb70`; policy fingerprint
  `55d5e05f91553381ba162c70b09c5f9987262edfbe2a9ec687214cc29f9d1057`.
- Extend CONTINUOUS-003 rolling regime rather than creating a competing regime
  engine.
- Research trend-up, trend-down, rotation, chop, late-trend, exhaustion,
  volatility-shock, market-stress, and data-unsafe states from evidence such as
  SPY, QQQ, IWM, breadth, sector participation, realized volatility,
  correlation, VWAP/range extension, and prospective breakout-failure rate.
- Initial role is `SILENT_OBSERVER`. Measure whether a proposed veto or risk
  reduction would have improved the actual Momentum baseline; classifier
  existence grants no trade authority.
- V1 requires SPY/QQQ/IWM for evaluation; missing/stale evidence abstains,
  contradictory/tampered evidence fails, and after-hours is identified but
  unsupported. Frozen provisional session profiles are premarket `1.25x`,
  opening `1.00x`, midday `0.75x`, and late session `1.00x`; they are policy-
  fingerprinted `RESEARCH_HEURISTIC` hypotheses rather than calibrated
  probabilities. Proposed five-minute regular-session cadence remains
  dormant pending a separate integration and activation task.

#### ARGUS-TECH-STRUCTURE-002 - Technical Structure Research v2

- Branch-local status: `IMPLEMENTED_PENDING_PARENT_INTEGRATION` from exact
  parent SPECIALIST-CONTRACT-001 `e65cb70`; frozen policy fingerprint
  `6b40ecc89cbfe5d1b3fb0c4d5b1376a4b5e9fb8e3bc96282afccf4838cbb1aa0`.
- Evolve Technical Breakout Research Engine v1 rather than creating a second
  technical framework.
- Define volatility-aware, deterministic geometry for compression-expansion,
  breakout-retest, failed breakout, VWAP reclaim/loss, higher-low continuation,
  lower-high breakdown, double top/bottom, support/resistance, and head-and-
  shoulders/inverse head-and-shoulders structures.
- Consume corporate-action-safe analysis history and initially emit
  `SUPPORTS`, `NEUTRAL`, `CONTRADICTS`, `EXHAUSTED`, or an abstention for
  existing Momentum Hunter opportunities.
- Implemented v2 preserves completed-bar chronology, economic event time versus
  `knownAt`, explicit same-bar ambiguity, ATR/range-normalized geometry,
  sparse levels, conflicting structures, bar-derived VWAP identity, data-basis
  admission, and immutable source/policy/target fingerprints. Unknown evidence
  abstains rather than becoming neutral.
- Hard Chew passes 50 focused tests, 245 adjacent tests, 202 untouched sibling
  contract tests, compileall, `git diff --check`, and all 2,113 Python tests.
  Existing runtime imports and provider/account/broker/order/persistence/
  service/scheduler/UI capabilities remain absent.
- Independent technical candidate nomination is later work requiring its own
  prospective evidence and sample gate.
- Do not infer pattern edge from synthetic detector proof. Later integration
  requires the parent contract, and later prospective attachment requires
  RESEARCH-GOV/RESEARCH-DATA/STAT producer wiring plus a new activation gate.

#### ARGUS-RESEARCH-DATA-001 - Research-Scale Historical Data And Universe Integrity

- Status: `IMPLEMENTED_PENDING_MERGE` on
  `codex/ARGUS-RESEARCH-DATA-001-data-inventory`.
- Frozen inventory fingerprint:
  `5D414FDC41BA78DBC07328653EA491847377D0C5690904F96E4067C6CB2BA735`.
- Measured evidence: 38,286 canonical Schwab minute bars / 7 symbols / 17
  session dates; 1,764 canonical Schwab Daily bars / 7 symbols; 79,298
  research-only adjusted Daily rows / 263 symbols; 1,256 candidate rows / 290
  symbols; and an empty prospective SETUP-002 sample.
- Research capability: Daily technical patterns and rank/setup-conditioned
  outcomes are `PARTIAL`; intraday analogs, complete premarket structure,
  failed breakouts, successor-setup statistics, regimes, events, time-of-day,
  and historical analog modeling are `INSUFFICIENT`.
- Universe integrity is `INSUFFICIENT`: durable security identity, symbol
  continuity, delisted coverage, point-in-time membership, and complete
  corporate-action lineage are absent.
- No provider is selected or recommended. The inventory records exact gaps,
  allowed/denied authority, and exit conditions before procurement.
- Inventory actual Schwab minute and Daily history, prospectively accumulated
  evidence, research-only Daily history, security identity coverage, and enough
  renamed/delisted handling to avoid obvious survivorship bias.
- Determine required depth for technical patterns, intraday analogs,
  regime-conditioned setups, event reactions, time-of-day effects, and
  rank/setup-conditioned outcomes.
- Provider minimalism remains mandatory: prefer existing authoritative data and
  prospectively accumulated canonical data. Before proposing another provider,
  document the exact capability gap, required fields/depth, proposed and denied
  authority, cost, and exit condition.

#### ARGUS-RESEARCH-DATA-002 - Security Identity And Corporate-Action Basis

- Status: `IMPLEMENTED_PENDING_MERGE` on
  `codex/ARGUS-RESEARCH-DATA-002-security-action-basis`, stacked on DATA-001
  `d03301c` from canonical baseline `ea056155`.
- Define durable research security IDs, point-in-time aliases, inactive and
  delisted states, and fail-closed ambiguous/reused-symbol resolution.
- Define verified forward split, reverse split, and symbol-change actions;
  preserve merger/spinoff/distribution extension types without inventing
  unsupported transformation semantics.
- Require every research bar to declare `RAW_PROVIDER`, `SPLIT_ADJUSTED`,
  `TOTAL_RETURN_ADJUSTED`, or `UNKNOWN`; provider name never proves basis.
- Preserve raw OHLCV and bind every derived bar to identity, action IDs,
  cumulative price/volume factors, transformation version, and fingerprints.
- Current dataset result: all five DATA-001 sources have unresolved identity,
  unknown price basis, uncontrolled survivorship, and insufficient point-in-
  time universe evidence. They remain useful only for explicitly bounded
  source/prospective evidence inspection, not survivor-safe or corporate-
  action-sensitive statistical claims.
- No provider selected. The compatibility report records durable identity,
  event-chain, basis-verification, and point-in-time-universe gaps plus whether
  prospective collection can close each one.

#### ARGUS-STAT-DATA-001 - Prospective Opportunity Denominator

- Branch-local status: `IMPLEMENTED_PENDING_PARENT_INTEGRATION` from common
  Specialist Contract parent `e65cb70`; no runtime consumer or activation
  exists.
- Preserve a cycle-level proof of the complete bounded source universe and one
  immutable row for every represented Momentum candidate, rank alternative,
  reject, data/risk/provider block, provider-bound non-evaluation, future
  specialist nomination, system failure, and explicit counterfactual.
- Maintain stable opportunity identity across separately attached specialist,
  market-path, broker-execution, and data-quality records. Same-symbol,
  same-session opportunities remain distinct when setup, origin, cutoff, or
  evidence identity differs; ticker is never treated as durable issuer identity
  without proof.
- Market-path outcomes support `TARGET_FIRST`, `STOP_FIRST`, `TIMEOUT`,
  `UNTRIGGERED`, `INVALIDATED`, `AMBIGUOUS_SAME_BAR`, and `DATA_FAILURE`, with
  terminal-bounded MFE/MAE and timing. Broker outcomes independently require
  actual provider submission/fill evidence and never infer fill quantity from
  candles or allocation authority.
- Exact duplicate persistence is idempotent; conflicts, malformed/tampered
  records, incomplete writes, sample/policy drift, future evidence, and any
  attempted execution authority fail closed.
- Sample `opportunity-denominator-research-v1` is inactive at 0 sessions and 0
  opportunities. Historical fixtures and the August 14 opening-report proof
  remain `RETROSPECTIVE_RESEARCH_EXAMPLE` and cannot enter the prospective
  denominator.

#### ARGUS-STAT-DATA-002 - Prospective Producer Wiring And Activation

- Begin only after the frozen Aug. 17 evidence is terminal and preserved.
- Feed the denominator from the complete bounded source population, including
  rows that do not survive scanner/report admission, rather than treating a
  surviving briefing subset as the original population.
- Wire and activate prospectively under a new immutable activation identity;
  do not backfill history, rewrite STAT-DATA-001 records, or change the current
  Momentum/Paper strategy path.

#### ARGUS-EXEC-QUALITY-001 - Liquidity And Execution-Quality Research

- Branch-local status: `IMPLEMENTED_PENDING_PARENT_INTEGRATION` from Specialist
  Contract `e65cb70`; no runtime consumer, persistence, activation, or
  authority exists.
- Preserve spread, spread expansion, quote age/stability, executable size only
  where proven, volume versus price progress, heuristic fill-risk state,
  halt/unavailable state, and provider capability as separate research
  dimensions rather than one score.
- Preserve later provider-confirmed fill state, delay, actual filled quantity,
  slippage, and execution-adjusted risk/R:R in a separate immutable attachment;
  never leak later execution into the original opinion and never report an
  uncalibrated fill probability.
- Future bearish work must separately evaluate shortability, borrow/locate,
  margin/buying-power eligibility, and broker restrictions.
- Strategy logic remains provider-neutral; a provider name cannot become
  strategy law.

#### ARGUS-STAT-OUTCOME-001 - Historical Analog / Outcome Probability Engine

- Begin only after sufficient STAT-DATA, research-history depth, and clean
  corporate-action/price-basis semantics.
- Candidate outputs may include target-before-stop probability, expected R,
  MFE/MAE distributions, time to target/stop, fill probability, uncertainty,
  sample size, and calibration quality.
- Progress from matched historical analogs to interpretable logistic models,
  then survival/competing-risk models; consider tree/boosting methods only when
  they prove incremental value. Require walk-forward/out-of-sample evidence;
  in-sample performance grants no authority.

#### ARGUS-EXIT-RESEARCH-001 - Trade-Management And Exit Intelligence

- Branch-local status: `IMPLEMENTED_PENDING_PARENT_INTEGRATION` on
  `codex/ARGUS-EXIT-RESEARCH-001-trade-management-research`, stacked exactly on
  Specialist Contract commit `e65cb70`; no runtime consumer, persistence path,
  activation, or authority exists.
- Freeze `exit-management-research-v1` as a software-validation policy. Require
  the actual broker-confirmed fill, quantity, time, original protective stop,
  TradePlan, policy, and evidence identities before evaluating any alternative.
- Implement eight separate methods: actual frozen control, structural stop,
  next-bar-effective ATR trailing stop, 60-minute time stop, +1R break-even,
  50% Target-1 partial exit with original-stop/Target-2 runner, momentum
  failure, and regime deterioration. No optimized combined method exists.
- Preserve each actual Paper trade under its frozen TradePlan/lifecycle while
  silently comparing structural stop, trailing stop, time stop, break-even,
  partial exit, momentum-failure exit, and regime-deterioration exit methods.
- Keep actual and counterfactual results separate. A counterfactual exit may
  never rewrite an actual trade.
- Use completed bars only and preserve ambiguous same-bar stop/target ordering,
  gap execution uncertainty, stable original 1R, quantity conservation,
  counterfactual MFE/MAE only through exit, and separately labeled post-exit
  opportunity. Stale or mismatched specialist evidence abstains.
- The prospective sample is defined but inactive with zero trades. Integration,
  producer wiring, persistence, activation, parameter research, strategy
  influence, and any execution authority require separately authorized gates.
- Research whether management produces more incremental edge than another
  entry filter; do not change current TradePlans under this task.

#### ARGUS-EVENT-SHOCK-001 - Unscheduled Event And Reaction Intelligence

- Branch-local status: `IMPLEMENTED_PENDING_MERGE` from specialist-contract
  head `e65cb70`; no producer, persistence, runtime consumer, activation, or
  execution authority exists.
- Extend CONTINUOUS-003 macro-event and catalyst architecture rather than
  creating competing infrastructure.
- Research supply disruptions, industrial incidents, geopolitical escalation,
  cyber incidents, unexpected regulation, material corporate events, and other
  credible breaking shocks.
- Preserve direct-issuer, competitor, proven supplier/customer, sector,
  commodity, macro, and unresolved relationship semantics; require market
  confirmation.
- Make expected reaction versus actual reaction first-class research, including
  news/price disagreement, volume without progress, relative lag, and immediate
  breakout failure. Headline sentiment never directly creates an order.

#### ARGUS-BEAR-001 - Bearish Equity / Short-Selling Research

- This is stock-shorting research only; no options work is authorized.
- Begin only after regime, technical structure, execution quality,
  account/broker capability, and short-side risk semantics are sufficiently
  proven.
- Research downside breakout, failed support/reclaim, lower-high breakdown,
  relative weakness, and event-driven downside repricing in Paper/research
  first.
- Do not assume long-side sizing, borrow, margin, fractional, stop, fill, or
  protection semantics apply to shorts. No live short authority is granted.

#### ARGUS-RESEARCH-GOV-001 - Experiment Registry And Model-Health Discipline

- Status: `IMPLEMENTED_PENDING_MERGE` on the isolated task branch; no runtime
  integration or activation exists.
- Before broad parameter/model searches, preserve hypothesis, feature
  definitions, every attempted variant, training/validation/test periods,
  benchmark, success criteria, and untouched holdout. Failed variants remain
  visible.
- Later preserve `HEALTHY`, `DEGRADING`, `UNRELIABLE`, and
  `INSUFFICIENT_RECENT_EVIDENCE` health states. A model or pattern can lose
  authority; one favorable historical test never makes a strategy rule
  permanent.
- Contract v1 now also distinguishes authorized final holdout access from
  permanent early-access contamination; separates results and invalidations
  from preregistration; exposes planned and actual search counts; and rejects
  deleted negative evidence, broken receipt chains, tampering, and execution
  authority. Static examples remain unactivated and make no predictive claim.

#### ARGUS-ARBITER-001 - Meta-Decision / Strategy Arbiter

- Status is `DEFERRED`. Begin only after multiple specialists have prospective
  evidence of incremental value versus the Momentum baseline.
- Do not naively average scores or count correlated indicators as independent
  confirmation. Future combination must use explicit authority, veto,
  abstention, evidence family, regime, portfolio risk, and broker capability.
- Any material arbiter rule starts under a new prospective strategy and
  configuration fingerprint and sample identity. No live authority is implied.

#### Phase 13R Dependencies And Promotion Gates

- DATA-CORPACTION-001 precedes serious TECH-STRUCTURE-002 and
  STAT-OUTCOME-001 historical claims.
- SPECIALIST-CONTRACT-001 precedes any combination of specialist opinions.
- STAT-DATA-001 precedes STAT-OUTCOME-001, and RESEARCH-DATA-001 must prove
  sufficient depth before broad historical/statistical claims.
- REGIME-002 and TECH-STRUCTURE-002 may initially operate silently and
  independently after their prerequisites exist. EVENT-SHOCK-001 and
  EXIT-RESEARCH-001 remain independent research lanes and need not wait for the
  final arbiter.
- BEAR-001 depends on sufficient bearish setup, execution-quality, broker-
  capability, and risk evidence. ARBITER-001 is last and must be earned through
  prospective A/B evidence.

Roadmap presence does not activate a strategy. Silent research does not count
as an executed trade, and a counterfactual does not become a historical trade.
Existing Paper evidence remains immutable. Any specialist influence on
candidate admission, direction, entry, sizing, risk, stop, target, exit, or
strategy combination is a material strategy change and must begin under a new
prospective policy/configuration fingerprint and sample identity. No
retrospective backfill, winner-only selection, or rewriting of the Momentum
baseline after specialist outcomes is permitted.

### Phase 14 - Unattended Live Execution

Status: `BLOCKED`

- Requires a separate explicit Steven decision after repeated supervised-canary evidence, credential and account-isolation controls, reconciliation and independent audit review, token-revocation proof, and a dedicated unattended-live Goal Charter.
- No standing directive may auto-advance into Phase 14.

## Roadmap Update Protocol

At every substantive task closeout, the responsible agent must:

1. Reconcile the `Now` section against `git status --short --branch`, the active branch HEAD, and local `master` versus `origin/master`.
2. Move the affected roadmap phase to the correct status without calling branch-only work `COMPLETE`.
3. Record the concrete next action and any new block or decision gate.
4. Update `BRANCH_LEDGER.md` only when branch/merge/push state changes, and `TASK_LOG.md` or `CHANGELOG_ARGUS.md` as historical evidence requires.
5. After every terminal ordinary opening capture, verify and preserve its terminal receipt, dated capture/report/log identity, candidate/result summary, and safety outcome in the ignored operational evidence index. A routine successful capture must not trigger a Roadmap commit, canonical Git identity change, or remaining-job repin.
6. Update `Now` for a capture only when it materially changes a gate, exposes a defect or anomaly, changes runtime capability or schedule, requires repair, or completes a defined evidence milestone. Preserve the already-committed August 5 evidence prospectively; do not rewrite it merely to apply this policy.
7. Cite any resulting material Roadmap transition in the final CEO report.

## Protected Areas

Protected areas require exact task scope and Hard Chew proof. Do not ask again when the current task or Roadmap already authorizes the bounded change. Interrupt Steven before changing protected semantics, transmitting a real order, performing destructive data/schema work, exposing or revoking credentials, or expanding beyond the documented outcome.
