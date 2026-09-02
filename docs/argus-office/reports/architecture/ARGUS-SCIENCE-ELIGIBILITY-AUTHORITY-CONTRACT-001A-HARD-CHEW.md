# ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001A Hard Chew

## Candidate boundary

- Canonical lineage root: `04f6f8382e03906cbd174711a1d4df2d43a5cab4`
- Rejected parent head: `663fad740df56e0ff4bc2f8308a508d4b107b589`
- Branch: `codex/ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001A`
- Contract disposition: correct V2 before acceptance; no V3
- Merge, deployment, exporter restart, reader restart, and live capture: prohibited

## Required behavioral gates

| Gate | Required result |
|---|---|
| Rejected-head chronology reproduction | PASS, Git-bound to `663fad7...` |
| Exact observation-receipt → eligibility injection | PASS |
| T1 receipt-effective chronology | PASS |
| T2 first evaluation/materialization chronology | PASS |
| Full named crash matrix plus clean path | PASS |
| Producer raw-byte stability | PASS |
| One eligibility/no conflicting sealed identity | PASS |
| Staged eligibility clock reuse | PASS |
| Semantic hash independent of physical recovery latency | PASS |
| Semantic hash dependent on frozen receipt-effective time | PASS |
| Hash-domain separation | PASS |
| Anti-hindsight and future-field rejection | PASS |
| Later exact outcome linkage | PASS |
| V1 preservation and V1/V2 parser separation | PASS |
| `science-eligibility` record-family declaration | PASS |

## Verification protocol

Before freeze, run the focused Science suite, Continuous compatibility suite,
full approved Python discovery, compileall, diff check, secret scan, capability
scan, and protected-path review. Commit source, tests, and these reports once.

After that commit, treat the exact commit as `FINAL_REVIEW_HEAD` and create a
fresh detached disposable worktree at that head. Generate every authoritative
result JSON there so each records the exact final Git head:

- focused Science suite
- Continuous compatibility suite
- full approved Python discovery
- deterministic two-clock/recovery proof
- compileall and repository/safety scans
- implementation-to-review executable/test byte equivalence

External result JSON and the sealed second-eye packet are the authoritative
final-head result records. No source, test, documentation, or tool commit may be
created after the freeze.

## Protected-area review

The allowed Git diff is limited to the Science custody contract declaration,
Science custody persistence implementation, task-matched eligibility tests, and
unique `001A` reports. No Continuous implementation, Science source reader,
GUI, Opening Engine, provider/authentication, service/scheduler, product
decision, trading, execution, or installed-runtime path is owned.
