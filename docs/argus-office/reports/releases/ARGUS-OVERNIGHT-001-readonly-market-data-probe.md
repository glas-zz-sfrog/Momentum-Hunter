# ARGUS-OVERNIGHT-001 Read-Only Market-Data Probe

Final classification: `OVERNIGHT_CONTEXT_PROVEN_WITH_LIMITATIONS`

## Identity

- Observation window: 2026-08-09 22:31:42.232622 through 22:31:47.693483 Central.
- Symbols: SPY, QQQ, NVDA.
- Feature branch: `codex/ARGUS-OVERNIGHT-001-readonly-market-data-probe`.
- Feature base: `1abb4ddf95b927e42903f27d34b2891df3eb8bc5`.
- Frozen canonical master: `1d0ca95a24b52d5c19e0866914e69880c07a13f5`.

## Observed Capability

- Alpaca's derived `overnight` feed returned latest bars, indicative quotes, latest trades, and snapshots for all three symbols with HTTP 200.
- Direct latest BOATS bar/quote/trade/snapshot requests returned HTTP 403 because the current subscription does not permit those queries.
- Bounded `feed=boats` historical one-minute requests returned HTTP 200 for all three symbols.
- Derived overnight quotes were 0.10 to 3.42 seconds old at receipt.
- Latest bars were 1,002.33 to 1,302.33 seconds old at receipt and are classified `DELAYED_CONTEXT`.
- Latest trades were 934.95 to 1,256.21 seconds old at receipt and are classified `DELAYED_CONTEXT`.
- A five-second repeated latest-bar observation showed no revision for SPY, QQQ, or NVDA; this short proof does not establish finalization semantics.

## Historical Evidence

| Symbol | Bars | First minute (Central) | Latest minute (Central) | High | Low | Volume | Missing minutes | Duplicates |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| SPY | 111 | 19:00 | 22:10 | 773.60 | 771.82 | 55,263 | 80 | 0 |
| QQQ | 157 | 19:00 | 22:15 | 724.77 | 721.42 | 121,486 | 39 | 0 |
| NVDA | 123 | 19:00 | 22:14 | 225.13 | 223.90 | 219,226 | 72 | 0 |

Missing minutes are preserved as sparse market observations; they were not fabricated as zero-volume candles. OHLC and volume were populated on returned bars.

## Adjudication

- `OVERNIGHT_DATA_AVAILABLE`: PASS
- `OVERNIGHT_1M_CANDLES`: PASS
- `OVERNIGHT_VOLUME`: PASS
- `OVERNIGHT_QUOTES`: PASS
- `OVERNIGHT_TRADES`: PASS, delayed context
- `FEED_IDENTITY`: DERIVED_OVERNIGHT for latest context; delayed BOATS for bounded history
- `CONTEXT_USEFULNESS`: USEFUL_WITH_LIMITATIONS
- `EXECUTION_AUTHORITY`: UNVERIFIED
- `CANONICAL_STRATEGY_AUTHORITY`: NOT_GRANTED

The narrow future role is an `OVERNIGHT CONTEXT SNAPSHOT`: overnight high/low, price context, volume where present, feed identity, and measured freshness. It must not generate trades, rank candidates, replace Schwab, or become canonical strategy data without a separate task and proof.

## Proof Integrity

- Canonical JSON: `ARGUS-OVERNIGHT-001-sunday-night-proof.json`
- JSON SHA-256: `CA85D8351981D951ED7780949CF36E7A7DACA9377FCA6FEDB51E86A55A6B8984`
- Canonical Markdown: `ARGUS-OVERNIGHT-001-sunday-night-proof.md`
- Markdown SHA-256: `1107F2C17E1827FB14ED9540FBDD0CA0D72632D449095C6E822D43D4C56629AD`
- Initial classifier attempt preserved separately. It exposed and led to correction of an age-classification defect; it is not the canonical adjudication.
- No credential value, account identity, account request, position request, order request, mutation, or production persistence is present.

## Verification

- Python compileall: PASS.
- Focused overnight probe tests: 10 passed.
- Adjacent Alpaca onboarding, broker, lifecycle, and allocation tests: 121 passed.
- Full Python discovery: 1,401 passed in 218.859 seconds.
- The first full discovery attempt identified only two isolated-worktree environment failures because `.venv` was absent. Both exact tests passed after an ignored temporary junction was added, and the complete suite then passed.
- Generic secret-shape scan: PASS.
- Runtime mutating/trading capability scan: PASS; the new module exposes only allowlisted GET requests to `data.alpaca.markets`.
- Canonical master remained clean and synchronized at `1d0ca95a24b52d5c19e0866914e69880c07a13f5`.
- `MomentumHunterAutomation` remained Running/Automatic.
- Installed manifest SHA-256 remained `E99E65A302B97A5D866071C3C1B37C8519972F8D55966EAC08772A1F6F093B47`.
