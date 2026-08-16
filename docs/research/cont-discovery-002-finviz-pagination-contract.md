# CONT-DISCOVERY-002 Finviz Pagination Contract

## Observed Read-Only Capability Proof

On 2026-08-15, the existing canonical Finviz screener query was requested
read-only with its existing filters and `-volume` sort. The proof made three
requests only: the initial page, `r=21`, and `r=141`.

- Finviz uses `r` as a one-based row offset. Page one is the base request;
  page two is `r=21` for the observed 20-row page size.
- The response visibly exposed `160 Total` for that exact query at proof time.
- `r=21` contained rows 21 through 40. `r=141` contained rows 141 through 160.
- The provider visibly exposed a total-result count, but did not expose an
  authoritative total-page count or snapshot token in the observed contract.
- The implementation derives `pagesAvailable` only when both the provider total
  and page size are known. It never records that derived value as a provider
  total-page claim.

## Resulting Contract

`FinvizProvider.scan()` and `FinvizProvider.discover()` preserve their existing
single-response behavior. `FinvizProvider.discover_paginated()` is a separate,
explicit opt-in path requiring a versioned `DiscoveryPaginationPolicy`.

Every paginated snapshot records its query and policy identity, page offsets,
page-local/global row coordinates, per-page request timing, total-result
metadata when available, coverage state, truncation reason, and page receipts.

`CROSS_PAGE_ATOMICITY` is always `NOT_GUARANTEED`: Finviz exposes no observed
snapshot token, so different pages may represent different instants. A complete
result is complete with respect to the observed filtered query pages, not a
provider transaction.

## Coverage Truth

- `COMPLETE_FILTERED_RESULT_SET`: terminal provider evidence or all known pages
  were represented.
- `BOUNDED_PAGE_PREFIX`: an intentional `maxPages` or `maxRows` policy bound
  stopped further requests.
- `REQUEST_BUDGET_EXHAUSTED`: the bounded elapsed-time budget stopped the pulse.
- `PARTIAL_PROVIDER_FAILURE`: a required page failed validation or transport.
- `PROVIDER_PAGE_LIMIT`: provider policy prevented the requested next page.

No prefix is described as complete. Identical duplicate source observations are
preserved explicitly; conflicting duplicate symbols fail closed. This task does
not select a normal live page depth or activate recurring discovery.
