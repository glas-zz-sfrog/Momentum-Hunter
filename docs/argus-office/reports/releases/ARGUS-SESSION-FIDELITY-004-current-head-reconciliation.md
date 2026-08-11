# ARGUS-SESSION-FIDELITY-004 Current-Head Reconciliation

## Result

Reconciled the exact SESSION-FIDELITY-001 through 003 read-only observer stack
from source head `799f07b` onto current canonical base `a46d31b`. The stack is
dormant and is not imported by production runtime code. It preserves the
original August 11 A/B/C evidence and does not alter the frozen August 12 retry
tasks.

## Observed August 11 Results

| Checkpoint | Central | Schwab result | Combined result |
| --- | --- | --- | --- |
| A | 03:05 | `USEFUL_WITH_LIMITATIONS`; fresh SPY/QQQ/NVDA quotes and volume, candle authority not proven | Incomplete: Alpaca child failed safely with `TypeError` |
| B | 05:55 | `USEFUL_WITH_LIMITATIONS`; fresh SPY/QQQ/NVDA quotes, candle and volume authority not proven | Incomplete: Alpaca child failed safely with `TypeError` |
| C | 06:05 | `HIGH_FIDELITY`; fresh SPY/QQQ/NVDA quotes, candles, and volume | Incomplete: Alpaca child failed safely with `TypeError` |

The three original Schwab files remain write-once at SHA-256 values
`B8D65060707B5A2B0D5F69543216B2B6CFD97E32DA48DCEB117010CDB94125C9`,
`685F294468CD71B6295059DB40B373FBE57DFB2AF3B57FAF767182FF592E00D1`,
and `A8DFCC9259A754BF1B10B3E3923E74116E2329E23394D9854C1C9B468E63BF64`.
No combined manifest was fabricated.

The original A/B/C files also preserve a non-authoritative metadata defect:
`targetEastern` repeats the Central value and offset. Their `targetCentral`,
actual Task Scheduler run times, provider timestamps, and local receipt times
remain available and are the time evidence used for this audit. The historical
files are not rewritten. The frozen August 12 retry computes distinct Central
and Eastern targets correctly, and current head adds a regression test for
04:05, 06:55, and 07:05 Eastern.

## Repair And Retry

The defect was dependency-identity mixing: the Alpaca wrapper loaded an
incompatible host DPAPI class into the frozen provider module. The restored
adapter loads and origin-checks one frozen dependency set, restores host import
state, and supports the separately identified `SESSION-FIDELITY-003` retry.

Three Alpaca-only retries remain Ready for August 12 at 03:05, 05:55, and 06:05
Central. They reference clean immutable head `799f07b`, exact module/runner/
adapter hashes, SPY/QQQ/NVDA only, one bounded scheduler retry, no late start,
and write-once output outside Git. The user must remain logged in for
CurrentUser DPAPI; the desktop may be locked. Codex is not required.

## Verification

- All 11 restored source/test/tool artifacts are byte-identical to `799f07b`.
- Python compileall: pass.
- Focused session-fidelity tests: 16/16 pass.
- Adjacent market-data and broker-boundary tests: 209/209 pass.
- Full Python discovery: 1,889/1,889 pass in 235.420 seconds.
- Production imports of the observer chain: zero.
- Account, position, preview, order, live-endpoint, and transmission route scan:
  zero findings.
- Frozen retry branch: clean at `799f07b`.
- Frozen retry tasks: three Ready, never run, correct times, `WakeToRun=true`,
  `StartWhenAvailable=false`, and `RestartCount=1`.
- No provider, account, position, order, Shadow, service, scheduler, Engine
  Host, WPF, production-store, credential, or generated-evidence mutation was
  performed by this reconciliation.

## Classification

`IMPLEMENTED_PENDING_INTEGRATION`

After clean fast-forward integration, backup, and exact-head opening/Paper job
repin, this code reconciliation becomes `COMPLETE`. The August 12 external
retry remains independently `PENDING_MARKET_SESSION_EVIDENCE`.
