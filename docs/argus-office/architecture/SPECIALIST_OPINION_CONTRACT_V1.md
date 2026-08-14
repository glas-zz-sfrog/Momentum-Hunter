# Specialist Opinion Contract v1

## Boundary

`momentum_hunter.specialist_opinion` defines an immutable, provider-neutral,
broker-neutral, and strategy-neutral research packet. It performs no I/O and
has no provider, account, broker, order, scheduler, service, Engine Host, WPF,
or persistence capability.

Version 1 permits only:

```text
authority = RESEARCH_ONLY
executionAuthority = EXECUTION_AUTHORITY_NONE
```

An opinion cannot approve, veto, size, plan, submit, replace, cancel, or exit a
trade. No combination or Meta-Arbiter behavior exists in this slice.

## Identity

Each packet binds:

- contract, specialist, and specialist-version identity;
- opportunity, candidate, setup, and TradePlan identity where applicable;
- as-of and expiration time;
- research identity and policy fingerprint;
- ordered evidence references and their input fingerprint;
- evaluation status, opinion code, directional bias, disclosed feature
  families, confidence semantics, machine reason codes, and authority;
- a derived opinion ID and whole-record fingerprint.

Canonical JSON uses sorted keys, canonical UTC timestamps, sorted bounded
collections, and ASCII serialization. A change to evidence, specialist
version, opinion, confidence, target identity, or authority changes packet
identity. `validate_opinion_target_identity` lets a consumer reject an opinion
that addresses a different opportunity/setup/TradePlan chain.

## Semantics

`EVALUATED`, `ABSTAINED`, and `FAILED` are separate states. Abstention is an
explicit `NO_OPINION`, not a neutral or negative opinion. Confidence is either
unavailable or carries named semantics. A heuristic cannot claim calibrated
probability, and calibrated probability requires a bounded value and sample
size. Feature-family disclosure makes overlap visible without pretending that
several correlated specialists are independent votes.

## Promotion

Every specialist starts research-only. Any future promotion requires a
separate Goal Charter, a new prospective sample/configuration identity,
governance approval for the exact authority, independent regression and safety
proof, and explicit runtime integration. Accumulated research packets do not
themselves earn order, veto, Risk Governor, TradePlan, or strategy authority.
