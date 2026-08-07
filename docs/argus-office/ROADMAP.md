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

ARGUS-R032C automatic bounded candle backfill is
`IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE_AND_MERGE` on branch
`codex/ARGUS-R032C-automatic-candle-backfill` from canonical `af783da`.
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
Canonical `master`, the installed Engine Host, and Friday's capture remain on
`af783da` until visual acceptance and deliberate integration/reload.

The read-only R034 preflight found that destructive cutover cannot safely be a
two-file deletion. The active legacy minute artifact remains exactly 710 CRWV
bars at the recorded SHA-256, and SQLite contains exactly 710 rows bound to
that path/hash. However, the alert outcome updater can still rewrite that JSON,
and evidence-health, read-model, source-registry, SQLite validation/reporting,
and technical-breakout paths still read or validate it. `ARGUS-R034A` therefore
precedes R034: migrate active consumers or make absence explicit, add a
nonmutating cutover verifier, and prove the legacy file cannot be recreated.
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
directed integration. R033 is `VISUAL_ACCEPTED_PENDING_INTEGRATION` at pushed
feature commit `c88faa4`.

ARGUS-R032B historical candle backfill is `IMPLEMENTED_PENDING_INTEGRATION` at
pushed feature commit `9f9ac96`. It adds bounded Schwab `/pricehistory`
backfill for a ten-day one-minute window and a one-year daily window, with a
separate source-specific daily store, atomic writes, exact rerun idempotency,
correction/reassertion history, tamper checks, and explicit minimum depth. The
guarded isolated market-hours proof for NVDA, SHOP, ZETA, SPY, and IWM inserted
39,165 minute versions and 1,260 daily bars with no findings and no position,
order, or transmission action. The active integration branch combines R032B
with R033 and must bind Daily only to `schwab-daily-candles-v1`, rerun full
Python/.NET proof, and repin the remaining opening jobs before release. R034
legacy deletion remains a separately approved destructive gate, and Official
Shadow remains unarmed at `0 / 30`.

The synchronized DATA-001C closeout remained the exact head through Thursday's
successful capture. After this candle integration is committed and backed up,
Git Steward must repin the 26 remaining ordinary opening jobs from 2026-08-07
through 2026-09-14 exactly once. Acceptance requires a Running/Automatic
service with fresh heartbeat, Healthy Engine Host, Friday `PENDING` at 08:35
Central with latest start 08:40, all 26 jobs pending, zero Shadow jobs, and
order transmission `UNAVAILABLE`.

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
| Canonical baseline | Local `master` is synchronized at the pre-integration candle baseline and contains SHADOW-024, DATA-001/001B/001C, the routine-capture ledger policy, R031B, and R032. The verified integration branch adds R032B historical backfill plus R033 Engine Host/WPF chart consumption and will become the next canonical release through a clean fast-forward. The remaining opening jobs must then be repinned once to that final synchronized head. |
| Active implementation | Thursday's unattended capture passed. R032B and R033 are reconciled on `codex/ARGUS-R032B-R033-candle-integration`: guarded isolated proof preserved 39,165 minute versions and 1,260 Daily bars; Daily now reads only `schwab-daily-candles-v1`; all 1,203 Python and 250 .NET tests pass; the Release build has zero warnings; and Steven accepted the repaired dense chart. R032C automatic bounded symbol backfill is next after integration. DATA-002 follows the continuous-candle foundation. |
| Shadow sample | `official-shadow-v1` is preserved as a failed prospective ceremony at `0 / 30`; `official-shadow-v2` is preserved activated-empty and unarmed at `0 / 30`; prospective `official-shadow-v3` is activated-empty, unarmed, and `0 / 30`. Order transmission is `UNAVAILABLE`. |
| Active decision | Keep `official-shadow-v3` unarmed until quote provenance, catalyst attribution, setup identity, opening RVOL, sizing, and plan horizon are trustworthy. Thirty trades remains an engineering gate rather than proof of edge or live authorization. |
| Blocked by | Official Shadow selection remains blocked by DATA-002 through DATA-005. DATA-001C proves quote-source authority only; it does not make hypothetical plans execution-authoritative. R034 remains a separately approved destructive cutover. Phase 13 remains separately blocked by Schwab's lack of paperMoney/sandbox API support and the recorded credential-remediation gate. Fully powered-off recovery still depends on BIOS RTC/restore-on-AC-loss. |
| Scheduled operational proof | `COMPLETE`: the 2026-08-03 through 2026-08-06 08:35 ordinary captures all finished successfully on their first attempt with required artifacts and no Shadow or brokerage action. After this integration release, the remaining 26 opening jobs are repinned once to the final synchronized head. |
| Immediate operational work | Accept and integrate R032C, reload the installed Engine Host once, repin the remaining opening jobs, and prove one unseen-symbol live backfill. Then implement R034A legacy-consumer migration and its nonmutating cutover verifier. Do not activate unattended broad-universe collection or perform the separately approved R034 deletion yet. |
| Broker state | Schwab OAuth and the immutable `2573` `INDIVIDUAL_CASH` binding remain read-only. No account, position, preview, or order request occurred in Monday's through Thursday's captures. The guarded candle proof used only the expected identity check and market-data history; it made no position/order request. No transmitting method exists. The previously surfaced, unrotated Client Secret remains an explicit blocker for future transmitting code. |
| Steven action | No routine nonvisual approval is pending. Any brokerage anomaly, real-order proposal, destructive R034 candle cutover, or visual change remains a separate interruption gate. |
| Data caveat | DATA-001 proves displayed bid/ask provenance, DATA-001B prevents unresolved catalysts from granting authority, and DATA-001C permits only validated Schwab last/bid/ask to carry execution-price authority. Research tape remains nonauthoritative and the TradePlan itself remains hypothetical/execution-ineligible pending DATA-002 through DATA-005. Historical reports remain immutable. Opening RVOL still uses partial-session volume divided by a full-day average, and the $500-per-row reference sizing is not account-aware. Backfill is currently explicit; R032C owns automatic bounded queueing and visible loading state. DATA-002 owns RVOL correction; R034 retains the destructive-operation interruption gate. |

### Status Legend

- `NOT_STARTED`: no implementation has begun.
- `ACTIVE`: work is underway on the named branch.
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
- A016 selected Schwab/thinkorswim continuity. Schwab Support confirmed that Trader API cannot access paperMoney and has no retail sandbox, so A017 is `BLOCKED_VENDOR_CAPABILITY`.
- FakeBroker is the only automated boundary. thinkorswim paperMoney is manual ticket and fill-model reconciliation only; no interim Alpaca path is approved.
- SCHWAB-001/002/002A/003, live `CASH` validation, immutable binding, and bound-refresh safety are integrated. The production app, loopback callback, certificate trust, OAuth, DPAPI vault, and sole `2573` `INDIVIDUAL_CASH` binding are active and read-only.
- Account discovery and validation fail closed on any unexpected account count, suffix, type, hash, position, or permission. Sensitive account and balance values remain suppressed.
- The Client Secret was surfaced to the browser-automation channel during portal research. No credential or token was found in Git, but no rotation occurred. Read-only use continues under the recorded risk; transmitting code is blocked until Schwab supplies rotation, replacement, or explicit vendor remediation.
- The first future real-money gate is a broker-plumbing canary using a boring, liquid, preapproved instrument. A strategy-driven canary is separate and later. Pre-canary, canary-active, and post-canary position invariants must be implemented first.
- Detailed chronology, certificate identifiers, test counts, containment evidence, and remaining gates are preserved in `reports/security/SCHWAB-READONLY-ONBOARDING-AND-CREDENTIAL-INCIDENT.md`.
- No task may ask for a Schwab username, password, or MFA; place credentials/tokens/account hashes in Git or chat; automate thinkorswim; or transmit, replace, or cancel a real broker order without the applicable Steven decision.

#### Standing Authorization And Branch Discipline

- Standing-authorized nonvisual work includes bounded Shadow implementation/repair, evidence collection, 5/10/20/30 reports, manual paperMoney reconciliation artifacts, authenticated read-only Schwab calls, OAuth refresh, exact canary binding when one `2573` CASH account revalidates, broker-preview research that official documentation proves nontransmitting, tests, reports, Roadmap updates, commits, clean fast-forward merges, and non-force pushes.
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

Status: `IMPLEMENTED_PENDING_VISUAL_ACCEPTANCE_AND_MERGE`

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
- Implementation proof is complete on the feature branch: one chart request
  queues work without blocking, repeated five-second requests coalesce, one
  interrupted job recovers after Engine Host restart, malformed state and
  tampered candle stores fail closed, and a successful synthetic load repaints
  from `UNAVAILABLE / LOADING HISTORY` to 30 canonical candles. Integration,
  installed Engine Host reload, one live unseen-symbol proof, and Steven's
  visible wording check remain pending.

#### ARGUS-R034A - Legacy Candle Consumer Migration And Cutover Verifier

Status: `NOT_STARTED`; required non-destructive predecessor to R034

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

Status: `BLOCKED_VENDOR_CAPABILITY`

- The future evidence ladder is: (1) FakeBroker prospective Shadow Trading; (2) manual thinkorswim paperMoney ticket/reconciliation; (3) Schwab contract emulator, complete on local `master`; (4) synthetic one-use HTTPS loopback callback, certificate lifecycle, and browser-proof tooling, complete on local `master`; (5) production-local certificate staging, exact CurrentUser trust installation, and browser-warning-free proof, `PASS`; (6) credential onboarding and OAuth, complete on local `master` in SCHWAB-002; (7) standing-authorized Schwab authenticated read-only account discovery; (8) exact single-canary-account isolation proof; (9) broker preview only if official documentation proves a nontransmitting endpoint; (10) a Steven-approved supervised live canary order; (11) reconciliation, audit review, and token-revocation drill; and (12) repeated supervised canary cycles.
- Schwab Trader API cannot access paperMoney and has no retail sandbox. Manual thinkorswim paperMoney reconciliation is evidence collection, not an automated API execution path.
- Authenticated reads and proven nontransmitting preview work may advance automatically when expected invariants hold. Real order transmission never auto-advances and requires a concrete Steven decision after the complete evidence chain is shown.

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
