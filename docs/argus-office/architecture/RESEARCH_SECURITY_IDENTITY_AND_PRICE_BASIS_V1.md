# Research Security Identity And Price Basis v1

## Boundary

This contract is a pure research-data admission layer. It has no provider,
network, account, broker, order, strategy, runtime, service, scheduler, Engine
Host, or UI capability. It grants `RESEARCH_DATA_ADMISSION_ONLY` authority and
always grants `NONE` execution authority.

## Security Identity

`SecurityIdentity` uses a stable research security ID and explicit
point-in-time `SymbolAlias` records. Each alias contains its symbol, inclusive
effective dates, optional exchange, source, source fingerprint, and confidence
status. Alias windows for one identity may not overlap. Resolution requires an
observation timestamp and returns `RESOLVED`, `UNRESOLVED`, or `AMBIGUOUS`;
cross-security ticker overlap never resolves by guesswork.

Historical records retain their original symbol. The identity may separately
state a current symbol and one of `ACTIVE`, `DELISTED`, `ACQUIRED`, `RENAMED`,
`INACTIVE`, or `UNKNOWN`. Delisted and inactive identities remain resolvable
inside their documented historical alias windows.

## Corporate Actions

Supported transformation actions are `FORWARD_SPLIT`, `REVERSE_SPLIT`, and
`SYMBOL_CHANGE`. `MERGER`, `SPINOFF`, `SPECIAL_DISTRIBUTION`, and `OTHER` are
reserved extension points and are rejected by the numeric transformation
engine.

Every action binds an action ID, security ID, action type, known announcement
time, effective time, ratio or symbol transition, source, source fingerprint,
verification status, and action fingerprint. For a split ratio `N:D`, the
contract means `N` post-action shares for `D` pre-action shares. A pre-action
historical bar is transformed with:

```text
price factor  = D / N
volume factor = N / D
```

A 10:1 forward split therefore divides historical price by ten and multiplies
historical volume by ten. A 1:10 reverse split multiplies historical price by
ten and divides historical volume by ten. Symbol changes preserve numeric
OHLCV and add identity lineage only.

## Price Basis And Lineage

Every `ResearchPriceBar` declares `RAW_PROVIDER`, `SPLIT_ADJUSTED`,
`TOTAL_RETURN_ADJUSTED`, or `UNKNOWN`, plus a verification status. Provider
name alone does not prove the basis.

`PriceTransformationLineage` binds:

- the stable security identity and its fingerprint;
- raw source bar ID, source fingerprint, and original OHLCV;
- ordered corporate-action IDs and fingerprints;
- cumulative price and volume factors;
- transformation version and target basis;
- transformed OHLCV and transformed-bar fingerprint;
- one deterministic lineage fingerprint.

Validation independently rebuilds the transformed bar from the raw bar,
identity, and action chain. Missing, duplicated, out-of-window, wrong-security,
unverified, tampered, or unsupported actions fail closed. Raw source evidence
is never overwritten.

## Survivorship And Admission

`assess_survivorship_bias` returns `CONTROLLED`, `PARTIAL`, `UNCONTROLLED`, or
`UNKNOWN`. A current-only universe cannot claim `CONTROLLED`; controlled status
requires point-in-time membership and explicit inactive/delisted coverage.

`assess_research_price_basis` returns one of:

- `SAFE_FOR_RAW_ANALYSIS`
- `SAFE_FOR_SPLIT_ADJUSTED_ANALYSIS`
- `DATA_BASIS_UNCERTAIN`
- `CORPORATE_ACTION_UNRESOLVED`
- `SECURITY_IDENTITY_UNRESOLVED`
- `SURVIVORSHIP_STATUS_UNCONTROLLED`

The contract is compatible with specialist feature family
`CORPORATE_ACTION` and abstention code `DATA_BASIS_UNCERTAIN`, but imports no
SPECIALIST-CONTRACT-001 code and creates no branch or runtime dependency.

## Current Evidence Result

The DATA-001 inventory proves all five inspected sources are ticker-keyed and
lack durable security IDs, historical aliases, delisted coverage,
point-in-time membership, event-level corporate-action lineage, and verified
price-basis semantics. Current compatibility is therefore:

| Dataset | Current safe use | Blocked use |
|---|---|---|
| Canonical Schwab minute | Source-evidence inspection | Corporate-action-sensitive returns, levels, analogs, survivor-safe statistics |
| Canonical Schwab Daily | Source-evidence inspection | Corporate-action-sensitive returns, levels, analogs, survivor-safe statistics |
| Research Daily 263 | Bounded source-evidence inspection | Canonical or survivor-safe technical/statistical claims |
| Candidate/outcome history | Point-in-time candidate-evidence inspection | Complete-denominator or survivor-safe outcome claims |
| SETUP-002 prospective | Prospective setup evidence after activation | Historical or survivor-safe claims before the denominator exists |

Point-in-time universe capability is `INSUFFICIENT`; survivorship status is
`UNCONTROLLED`. Schwab basis remains `UNKNOWN`, and the broad Daily cache's
adjustment method lacks event lineage. No provider was selected. The report
demonstrates that a durable identity/action source might eventually be needed,
but existing evidence and prospective collection must first be measured
against the recorded gap exit conditions.
