# Engine008: finite physical backlog gate correction

Status: IMPLEMENTED_PENDING_MERGE. Engine-only test/helper correction; no
canonical integration or activation authority. Qualification receipts and the
independent frozen review are external, not a claim supplied by this document.

## Identity and ownership

- Base/head at task opening: 49a01500e225d63ebe0dcec0212072941ed4664d.
- Base tree: 5daf5cfdedc88774911514f7304ce7924922c2d4.
- Branch: codex/ARGUS-CONTINUOUS-WRITER-BACKLOG-GATE-CORRECTION-008.
- Physical007 source: 927a032e548217fd6c921329aae2db6c98fb4b65.
- Only two existing test files, a test helper, its tests, and this report change.
- Integration owns the later composite and must rerun its final runway. No
  Product/runtime, Science, GUI, provider, auth, scheduler, or service edit.

## Primary qualification

`tests.writer_backlog_gate` requires the exact accepted007 review and custody
manifest, verifies all 4596 retained file hashes, and binds current queue,
writer, durability, and liveness source bytes to the physical capture. A changed
bound source requires explicit requalification; there is no skip or fallback.
The Engine base lacks the V2 facade. Where present, its accepted source is also
bound; absence grants no V2 operational readiness claim.

The helper executes the actual `BoundedWorkQueue` at capacity256, comparing
every recorded admission, service/departure, observed depth, FIFO identity, and
restart snapshot against the immutable physical trace. It validates every
EvidenceWriteIntent, durable record, acknowledgement, checkpoint chain, pending
identity, and preserved overload failure. It is not a fresh latency measurement
and does not replace physical evidence with constant-rate synthetic arrivals.

Accepted finite bounds: EXPECTED2, PEAK122, SAFETY244 (below256), TRANSIENT122,
PERSISTENT256, ROLLOVER2. All1550 admissions reconcile into1294 durable and256
pending records. The transient physical tail drains in5.0962796 seconds; the
whole recovery must remain below the existing120-second recovery budget.
Persistent overload fails closed after the retained615.390991-second pressure
episode and preserves failure and pending identity across restart. These are
finite observed results, not new timing allowances.

007 review freeze SHA256:
586f9cf3865f87d1ba11a7577958155288c6d36fe916b05ac477e73d99d6a5c2

007 accepted Astra receipt SHA256:
f328f332c662f60f0e23b199822726b51e351f2f58006e56a416003e0574c6c9

## Historical stress retained

The4300-record accelerated test still runs and reports correctness, durability,
write/reopen timing, tail health, and its35.8333/s modeled queue. Only its two
modeled backlog admission assertions are removed. Modeled FAIL remains visible
as nonblocking stress telemetry, including the prior1442 modeled peak; it was
not a physically observed production queue. Write/reopen budgets, durability,
sequence, sharding, bounded-record checks,500ms health, and Writer005 remain.

No prior failure or007 evidence is rewritten. The unit test for synthetic
arithmetic retains its historical bound as an arithmetic regression, not as
the production admission criterion. A new overflow control proves the model
remains visible even when it exceeds128 and120 seconds.

## Reproduction and limitations

Set `MH_WRITER_BACKLOG_007_EVIDENCE_ROOT` to a byte-exact copy of the accepted007
root when not using its original F: location. This variable relocates custody;
it cannot change accepted hashes, bounds, or authority. Run with the approved
Python environment:

```text
python -B -m tests.writer_backlog_gate
python -B -m unittest tests.test_writer_backlog_gate tests.test_writer_liveness -v
python -B -m unittest discover -s tests -p test_*.py -v
```

Negative tests cover wrong capacity, actual-queue disagreement, exceeded finite
bounds, missing admissions, lost records, checkpoint mismatch, undrained or
late transient backlog, uncleared pending identities, improper overload reset,
V2 authority, missing/tampered custody, and changed runtime bytes.

External evidence root:
F:/ArgusQualification/Engine/ARGUS-CONTINUOUS-WRITER-BACKLOG-GATE-CORRECTION-008-20260911

Tier2/3 limits from007 remain: synchronous V2 overhead and finite history,
fixture workloads rather than live providers, object reconstruction rather
than installed service restart, same-user trial writer rather than installed
LocalService, and preserved unexplained smoke status-replace failure. No
infinite/full-session demand, installed-production, provider, or execution
readiness follows. Tier1 runtime/authority drift remains blocking.
