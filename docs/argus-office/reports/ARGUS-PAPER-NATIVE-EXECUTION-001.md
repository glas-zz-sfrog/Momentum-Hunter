# Native Paper Execution 001 / Exit Contract 002

Status: implementation candidate, disabled, pending qualification and independent review.
Base: `4291662305a2486304fb5dd13f7fb9263218804b`.
Base tree: `ba17a2f83c19bc65c7fe779402648b7d7a787140`.
Branch: `codex/ARGUS-PAPER-NATIVE-EXECUTION-001`.
No canonical integration, installation, broker transport, credential access, or activation.
This unique report is an Integration Steward handoff, not a shared Roadmap edit.

## Recovered Contracts

Accepted R4 oracle: `8afc3a3bf35136840728e136352db4f017f57c1a`,
tree `e6fee09ea563df413235f29dc5083f7c6e91abea`. The oracle remains a separate,
unchanged offline reference, not an imported Product dependency or authority issuer.
Canonical `intraday_trade_plan.py` owns plan validation and content identity;
`provider_neutral_allocation.py` owns allocation. No existing generic native
execution owner was found. Alpaca, Shadow and research simulators are unchanged.

`target_prices[0]` is the first canonical target, without sorting or optimization.
The canonical IntradayPlan requires a stop and at least one target. All original
targets remain in the retained plan, but V1 closes the full remaining position at
the first target. The canonical `forced_flat_at` deadline is preserved as
`OTHER_CANONICAL_IF_ALREADY_DEFINED` / `FORCED_FLAT`, not a new research time stop.
Missing/invalid geometry or tick mismatch fails closed. Original entry, stop,
targets, plan ID and original R never change after admission.

No partial-profit policy, runner, trailing, break-even, 60-minute time stop,
momentum/regime exit or post-exit re-entry is introduced. EXIT-RESEARCH-001 remains
research-only, and deferred EXIT-POLICY-002 is not promoted.

## Oracle to Native Map

| Concept | Canonical input / native representation | Owner / adapter boundary |
| --- | --- | --- |
| Opportunity | Explicit opportunity_id, never symbol matching | Frozen decision and trade scope |
| Setup | Explicit setup_id | Frozen decision and trade scope |
| TradePlan | Exact typed IntradayPlanEvidence / plan_id | Canonical validator and retained full plan |
| ExecutionIntent | Runtime request/result identity; DISABLED only | DisabledPaperIntake, independent append ledger |
| EntryScope | Environment + namespace + opportunity + setup + plan + LONG_ENTRY | NativePaperExecutionEngine; consumed permanently |
| OrderIntent | Scope + full plan + final risk decision | Durable intent before adapter call |
| OrderIdentity | Deterministic native-entry-order | Exactly one native execution projection owner |
| BrokerOrderIdentity | Deterministic sim-order, separately verified | Exact SimulatedPaperBroker type only |
| FillIdentity | Global economic ID and complete sequence prefix | Simulator source, reconciled native ledger |
| PositionIdentity | Environment + namespace + scope + order | Actual entry fills minus actual exit fills |
| opened_at | Exact first accepted fill event time | Never arrival time or later reconstruction |
| ExitIntent | Plan/position-bound STOP, TARGET and canonical deadline siblings | Atomic contingent protection in offline adapter |
| RiskDecision | Policy, full plan, account, local exposure, time, quantity | Canonical allocation followed by bound final quantity |
| ExecutionState | Native trade projection and canonical ExecutionLedgerEvent | NativePaperStore transaction under path lease |

## Execution Boundary

All configuration flags must be false; enabling any flag is unsupported and
rejected. No real broker implementation, credential loader, network client,
arm command, installer, service, scheduler or production configuration is added.
The adapter protocol is descriptive; the engine currently accepts only the exact
local simulator, not a subclass or arbitrary adapter.

Continuous optionally emits canonical composition request/result observations to
`DisabledPaperIntake`. They cannot flow to `qualification_entry`. The durable
pending record survives restart and sink failure; retries are bounded to three.
Default Continuous construction does not provision a Paper root or alter its
checkpoint schema. V2/denominator publication continues independently.

Explicit `OfflinePaperDecision` fixtures are separate qualification inputs, not
production admission authority. Science outputs and backtest records have no
execution consumer. This is a software/API boundary, not a claim of hostile-code
or Windows principal isolation. Production Paper admission/transport remains a
separately authorized task.

## Entry and Closure

BUY / LIMIT / DAY / SIMPLE, no extended-hours route, exact planned entry, whole
positive quantity within instrument maximum. No repricing/chasing. Canonical
eligibility, finality, known-at/cutoff, exclusive expiry and price freshness are
rechecked at final initiation. A changed source snapshot prevents initiation.
The account/risk gate is rechecked at that same initiation time without changing
the already-published quantity or original risk/order identity.
Actual initiation time is durably bound separately from intent creation. Fills,
working/ACK/closure receipts and exit triggers cannot predate actual initiation;
missing initiation authority quarantines observed source effects.
Risk is finalized before intent/order identity; requested quantity can only be
bounded during risk evaluation, never resized after publication.

Persist possible submission before calling even the fake adapter. Timeout or
lookup absence never grants a resend. Positive sender exclusion is distinct from
unknown acceptance. Consumed scope replay returns historical state, not a new
current grant. Cancellation/rejection/expiry does not reset scope consumption.
Different opportunities sharing a symbol retain different identities.

Raw source receipt precedes financial projection. Q = F + U + X.
An unprojected durable receipt cannot be replaced by a regressed snapshot;
retain both the original raw receipt and contradiction and quarantine instead.
This also preserves unprojected trigger identity across a higher source revision;
neither disappearance nor replacement can erase a retained raw contradiction.
Terminal text, cancel ACK or full fill alone does not establish complete-source closure. Require
the full prefix, matching original-order identity, complete child/finality proof
and coherent chronology. Retain historical closure on later contradiction;
quarantine current authority and preserve pending raw evidence. Working evidence
strictly before the earliest qualified close is harmless; equal/later post-close
working evidence blocks. First-close equal-time arrival ordering is preserved.

## Exit and Recovery

Contingent siblings exist before entry fills and share one actual remaining
position budget under the simulator lock. Broker partial fills do not define a
strategic partial exit. Every fill resizes remaining protection, full closure
invalidates siblings and entry remainder, and late callbacks cannot oversell or
reopen a flat position. Trigger evidence is separate from fill price; STOP price
improvement does not erase a valid earlier stop trigger. No OHLC ordering is used.
Any present trigger is validated even before a fill, including its acquired
position frontier, role, price, deadline and current-time boundary.

Unknown protection, missing stop, changed identity, conflicting fills, impossible
positions or missing prefix quarantines. Unknown exit reconciliation never sends
a second SELL. Exit events retain plan, position, intent, type, exact quantities,
request/event times, response, reason and state transition. Full financial closure
and complete-source closure are separate states.

The path lease owns read/decision/effect fence/commit. Hash-linked full snapshots,
atomic rename and a head anchor detect incomplete/corrupt chains and lost tails.
Recovery may require existing custody rather than silently creating a fresh root.
An unacknowledged record after a crash is conservatively retained. Physical tests
use local subprocess `os._exit`, never production process termination.

The store has a deliberate 4096-transaction offline bound and rereads its chain;
it is not an installed, production-scale or administrator-resistant custody
implementation. Whole-root rollback plus matching simulator rollback needs
independent external custody and is not claimed solved here. Capacity exhaustion
raises without authorizing a new effect. No Science007 bytes are consumed.

## Risk Policy

Capital, fractions, portfolio/position/risk caps, reserve, daily loss, position
count and freshness are configurable, not account-size constants. The immutable
policy's capital_base is also the configured daily-loss base; it is not inferred
equity. No account/equity provider read is made.

OFFLINE_FIXTURE explicitly means a fixed economic baseline excluding all native
ledger trades. Refreshing time/cycle evidence does not rebase economic fields.
Local exposure is added to external baseline exposure, never max() merged.
Pending entry quantities reserve cash; actual entry fill costs consume cash,
including after closure. Exit proceeds receive zero settlement credit. Open
notional/risk are conservatively valued at frozen entry/stop. Loss lockout includes
negative local exit-price versus original-entry differences and never nets away
losses with later profit. This is conservative, not tax/P&L/account reporting.
Active scopes add position slots. Duplicate opportunity_id exposure is denied;
separate opportunities for one symbol remain distinguishable as required.

No independent source proves arbitrary account-baseline updates; they are rejected
inside the same execution namespace. Real settlement, equity, marked gross,
fees, corporate actions, multi-currency and broker account normalization remain
outside this disabled fixture contract. Full upstream K risk mathematical parity
is NOT CLAIMED. R4 Paper execution entry/closure parity and Exit Contract 002 are
the applicable execution gates, not an authorization to implement a new K engine.

## Qualification and Acceptance Gates

`test_native_paper_r4_parity.py`: 135 generated closure/order scenarios across
A/B/FAR dates and three terminal categories, plus exact boundary/finality/fence
controls. `test_native_paper_execution.py` covers entry, identity, disabled gates,
unknown submission, reconciliation and multiple opportunities.
`test_native_paper_exit.py` covers full/partial fills, both race orders, queued
callbacks, unknown exits, restart, protection, actual chronology and audit.
`test_native_paper_mechanics.py` covers allocator, scale, risk and persistence.
`test_native_paper_process_restart.py` uses actual child termination; its helper is
`tools/native_paper_crash_probe.py`. `test_native_paper_continuous.py` proves the
canonical disabled-intake path. All are offline fixtures, not market proof.

Final acceptance additionally requires unchanged R4 oracle replay, full Python
discovery on exact bytes, compile/import, broader runtime/producer/Science/writer/
V2/execution coverage, protected-state/secret scans and a fresh independent Astra
report. Detailed actual counts/results belong in the sealed external receipts,
not predeclared PASS labels here. Any post-freeze byte change requires re-review.

Safety hooks are present, explicitly unarmed and not performed. Emergency
flatten remains distinct from ordinary plan exits. The next safety task must
qualify these controls before any activation. Advisory review does not grant
merge/deployment/transport authority.

## Evidence Custody

Original six-file checkpoint is retained unchanged at
`F:/ArgusQualification/Engine/ARGUS-PAPER-NATIVE-EXECUTION-001-4291662`.
Continuation evidence and failed/repaired receipts reside at
`F:/ArgusQualification/Engine/ARGUS-PAPER-NATIVE-EXIT-POLICY-CONTRACT-002-4291662`.
The final external report will bind candidate hashes, reviewed tree, test results,
independent review, eventual isolated commit/direct remote, and package identity.
No shared Roadmap, branch ledger, task log or canonical file is edited by this task.
