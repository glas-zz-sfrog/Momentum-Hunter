# ARGUS-SCIENCE-ELIGIBILITY-AUTHORITY-CONTRACT-001 Authority Model

## Before: circular V1 authority

```text
Producer Decision sealed at T0
  └─ required Science eligibility hash ───────────────┐
                                                      │ impossible reverse dependency
Science receives producer evidence at T1 > T0         │
  └─ Science capture time                             │
      └─ Science eligibility hash ────────────────────┘
```

## After: one-way V2 authority

```text
PRODUCER CLOCK (T0)
  exact source facts
  producer known-at / cutoff / emitted-at
  producer identities and exact envelope bytes
  producer content hash
                  │
                  ▼ one-way immutable input
SCIENCE CLOCK (T1 >= T0)
  exact source-byte custody
  candidate-observation custody payload
  Science custody receipt + receipt hash
                  │
                  ▼
SCIENCE ELIGIBILITY
  exact producer content hash
  exact observation payload hash
  exact observation custody receipt hash
  frozen policy + first observation + instrument
  Science evaluation time
  separate Science eligibility hash
                  │
                  ▼
LATER OUTCOME
  exact decision + observation + eligibility
  exact series + horizon + canonical bars
```

There is no arrow from a future Science fact back into the producer source
Decision.

## Ownership

Producer-owned, immutable before Science receipt:

- source/provider timestamps and producer known-at;
- decision time and cutoff;
- producer session, stream, sequence, source-event, observation, setup,
  TradePlan, and instrument identities where authoritative;
- exact source payload/envelope bytes and hashes;
- producer decision facts and references.

Science-owned, created only after receipt:

- recorder capture/evaluation time;
- normalized custody payload sequence;
- receipt chain and exact receipt hash;
- Science eligibility identity, material, and hash;
- Science custody Decision linkage to eligibility;
- custody lineage, recovery, verification, and coverage.

## Anti-hindsight

Initial V2 eligibility is a closed canonical object. Its inputs are limited to:

- the frozen producer discovery/observation content known at receipt;
- exact source-envelope and custody payload/receipt identities;
- the START-frozen outcome policy;
- Science's actual receipt/evaluation time.

The object has no field for outcome, return, future bar, later decision, future
revision, account, broker, position, order, Paper, Shadow, or execution data.
Unknown fields fail closed. Outcomes are accepted only through the structurally
separate later attachment path and cannot mutate parents.

## Compatibility

V1 and V2 are explicit parallel read profiles:

- V1 behavior and sealed records remain unchanged and recoverable.
- V2 is required for new one-way producer compatibility.
- No V1 bytes are migrated or synthesized.
- A V1 eligibility cannot be represented as receipt-bound V2 eligibility
  without fabrication, so repaired linkage remains `UNKNOWN` for legacy data.

## Scope boundary

This contract adds no exporter, reader, provider client, live worker, service,
scheduler, deployment, GUI, Opening Engine, trading-policy, Paper, Shadow,
broker, account, position, or execution authority.

