# ARGUS-RESEARCH-DATA-001 Goal Charter

## Goal

Produce a deterministic, read-only inventory of the historical and prospective
research evidence Momentum Hunter actually possesses, then classify which
research questions that evidence can support without making statistical claims
or selecting another provider.

## Acceptance

- Inventory canonical Schwab minute and Daily stores, the broad research-only
  Daily cache, candidate/outcome history, opening-capture denominators, and the
  empty prospective SETUP-002 lane.
- Preserve source path, hash/fingerprint, schema, authority, breadth, depth,
  timestamp coverage, and known data-quality limitations.
- Distinguish `CANONICAL`, `RESEARCH_ONLY`, and `PROSPECTIVE_RESEARCH` evidence.
- Evaluate data sufficiency for Daily patterns, intraday analogs, premarket
  structure, failed breakouts, successor setups, regimes, events, time-of-day,
  rank/setup outcomes, and historical analog modeling.
- Identify stable-security, symbol-change, delisting, point-in-time-universe,
  and corporate-action lineage weaknesses.
- State exact capability gaps and exit conditions before any provider proposal.
- Use no network, provider, account, broker, service, scheduler, Engine Host,
  UI, production mutation, scoring, readiness, or execution path.

## Protected Boundaries

Canonical `master`, the installed automation service, August 17 opening/Paper
and SETUP-002 jobs, raw captures, production candle stores, broker/account
state, credentials, scoring, readiness, selection, TradePlan, Risk Governor,
and UI behavior remain unchanged.

## Result

`IMPLEMENTED_PENDING_MERGE`. The inventory proves that current evidence is
useful but insufficient for broad historical claims. Daily technical research
and rank/setup outcome research are `PARTIAL`; all other evaluated research
uses are `INSUFFICIENT`. No new provider is selected or recommended.
