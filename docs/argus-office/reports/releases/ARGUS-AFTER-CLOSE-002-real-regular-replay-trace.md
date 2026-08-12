# ARGUS-AFTER-CLOSE-002 - Real Regular-Session Replay Trace

## Verdict

`REAL_PRESERVED_EVIDENCE_REPLAY_TERMINATED_AT_LEGITIMATE_GATE`

The replay consumed real preserved Schwab regular-session market evidence, but
the entire decision chain did not reach the broker submission boundary. This is
the correct result: SPY's preserved ask was `$740.05`, below the normalized
`$742.79` prior-Daily-high entry, so Paper Risk returned only
`PAPER_ENTRY_TRIGGER_NOT_REACHED`.

## Proven Chain

```text
preserved Schwab quote + canonical Daily/opening/baseline candles
    -> canonical price/candle authority PASS
    -> DATA-004 TradePlan PASS
    -> Paper Risk BLOCKED: trigger not reached
    -> DATA-005B NOT_REACHED
    -> order intent NOT_CREATED
    -> protective plan NOT_CREATED
    -> broker boundary NOT_REACHED_NO_SERIALIZED_ORDER
```

No retrospective trade, allocation, or order was created to force a pass.

## Source Files

- Quote proof SHA-256: `52831A3F9477B7C03EC4DC0CC0D9558C7964EA53B0A8B6C88F0306141AEAA72B`
- July 29 minute-store SHA-256: `D3E77E5F3E13BF8F72ADE52488619393674FA7D6A7853CA76866B180D6436469`
- July 28 baseline-store SHA-256: `0B0CAA64DCF74EBDA464E23A10558A15F58F9F087A7302F93DFE6540B7FEEF42`
- SPY Daily-store SHA-256: `9F0552C05937A45286EC0D3FB6F31938793DC1E24AB02145AA484D7234C78677`

The quote evidence fingerprint is
`FE9789D2267439BE47B87B0D84B4E833C04C4D9EC795DE28E906E33141AA22DD`.
Its provider timestamp is `2026-07-29T08:35:23.727-05:00` and its bid/ask is
`$740.03 / $740.05`.

## Market Evidence IDs

- Daily: `schwab-equity-1d:v1|SPY|2026-07-28|version:A56D1285114C388C111779610FD5974F0D783CEB9FEBD23BC8D02D45CFAAEBAD`
- Opening 09:30: `schwab-equity-1m:v1|SPY|2026-07-29T13:30:00+00:00|version:7FE26BEB0EB89B0FC262BD34D9C441F8523FE87C0F206E89E181632BC1DF2E76`
- Opening 09:31: `schwab-equity-1m:v1|SPY|2026-07-29T13:31:00+00:00|version:90342DF917DFA18562E3DAD4DEE9BA2A9A6DC33AEBC83DEDCE1B4BDDEF499C66`
- Opening 09:32: `schwab-equity-1m:v1|SPY|2026-07-29T13:32:00+00:00|version:0AC81A0F831130ED67489ED5006053F12963E8F1C0C4B2D32D64502640807886`
- Opening 09:33: `schwab-equity-1m:v1|SPY|2026-07-29T13:33:00+00:00|version:169B68CD463DD980CFA50C3735B5C48982275ECA8E27FEF623151CB8D99C89BF`
- Opening 09:34: `schwab-equity-1m:v1|SPY|2026-07-29T13:34:00+00:00|version:28AEB1FE1912E0903E2D779DC645F861A180FE3D7E82F8AE558CB38762DD9C94`
- Baseline 09:30: `schwab-equity-1m:v1|SPY|2026-07-28T13:30:00+00:00|version:5AC2762E9CBDA057CE9AEBFC20D64713AF656F75B234B5B049F7EDD6AF9603B9`
- Baseline 09:31: `schwab-equity-1m:v1|SPY|2026-07-28T13:31:00+00:00|version:22A5ACF9FCA38507750D46320E2A9201D71433FA274616B90C2080EC2819C4B9`
- Baseline 09:32: `schwab-equity-1m:v1|SPY|2026-07-28T13:32:00+00:00|version:ED407BE7EFC77CCE5F13153450E1012FD837B9B71E3FFEE8012E50724B41C6F0`
- Baseline 09:33: `schwab-equity-1m:v1|SPY|2026-07-28T13:33:00+00:00|version:7BC0F04135AF309687532FC87E2A82E015D120D2002D7D2460C2A6C2064E8451`
- Baseline 09:34: `schwab-equity-1m:v1|SPY|2026-07-28T13:34:00+00:00|version:2E25D43C9E387E25D24DB2C0F92FB4534763D867D5CD3BA056A564B180A0755D`

The candle stores were backfilled after July 29. The packet therefore proves
that current contracts can consume preserved real evidence; it does not claim
that all candle evidence existed contemporaneously on July 29.

## Time Identity

- `ORIGINAL_MARKET_TIME`: quote and decision chronology from July 29.
- `REPLAY_EVALUATION_TIME`: when the offline tool evaluated the packet.
- Replay time does not control the historical decision clock.

## Label Adjudication

The existing AFTER-CLOSE-001 label
`test-only:canonical-regular-session-replay` is stronger than its actual
provenance. That artifact was constructed from a live Finviz price and should
be understood prospectively as
`TEST_ONLY_CONSTRUCTED_REGULAR_SESSION_FIXTURE`. It was not changed.

This task uses
`TEST_ONLY_REAL_PRESERVED_SCHWAB_REGULAR_SESSION_REPLAY`.

## Synthetic Downstream Proof

Synthetic crossing tests separately prove:

- Paper Risk authorization when the trigger is reached.
- DATA-005B fractional allocation.
- Notional market-entry serialization.
- Protective quantity remains unset until actual fill reconciliation.
- Partial-fill protection resizes to the exact current position.
- Broker submission boundary makes zero provider calls.

These tests are not historical market evidence.

## Outputs

- Packet fingerprint: `3557A3FCF32BC613345C28941F814CB0007022F35A97C76929114B4FEFC35E79`
- JSON SHA-256: `EA62B28395C96A1A748636AA4E0E87C2B2B60FF0CA90B98DD1BD8A4F8E8961AE`
- Markdown SHA-256: `C812969D5A112633207437C89035480C562A404076582570D31ED456DCB9565A`

## Verification

- Compileall: pass.
- Focused and adjacent tests: 69 pass.
- Full bounded Python suite: 1,921 pass in 239.782 seconds.
- Source mutation: pass; all four input hashes unchanged.
- Network/provider/order calls: zero.
- Canonical runtime, service, scheduler, opening evidence, Paper/Shadow state,
  and production stores: unchanged.
