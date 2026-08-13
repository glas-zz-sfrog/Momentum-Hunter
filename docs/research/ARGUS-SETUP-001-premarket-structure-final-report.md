# ARGUS-SETUP-001 Premarket Structure And Fresh-Setup Research

## Classification

`RESEARCH_COMPLETE_IMPLEMENTATION_NOT_AUTHORIZED`

The Aug. 13 case study supports a narrow hypothesis: Momentum Hunter can lose the
ability to describe a later, distinct setup after an original Daily breakout is
missed. It does not show that the existing 0.25% extension rule is too strict.
The one fresh continuation candidate identified without post-decision data was
IREN, and that hypothetical setup later stopped out.

No scoring, ranking, Finviz filter, catalyst authority, Risk Governor, Paper,
scheduler, broker, TradePlan, stop/target, entry-extension, or production candle
behavior changed.

## Identity And Evidence Freeze

- Branch: `codex/ARGUS-SETUP-001-premarket-structure`
- Worktree: `C:\Users\steve\AppData\Local\MomentumHunter\worktrees\ARGUS-SETUP-001-premarket-structure`
- Shared base: `a9821ed08d5be91a10cbeb0151bb3d6bd3f028b5`
- Feature commit: recorded after the Hard Chew closeout; this report is part of
  that feature commit
- Canonical checkout: unchanged at the shared base throughout research
- Pass 1 decision time: `2026-08-13T09:35:38.562310-04:00`
- Completed-bar cutoff: `2026-08-13T09:35:00-04:00`
- Pass 1 fingerprint: `9C2F2AB10FA2BF97BB4854286DFA692142BD993DD80EF7E2526329A5C778FF5E`
- Pass 1 file SHA-256: `33A72E695B79AC1AED9C97080BD524B81556D86150A24BB8B1A03DB5FD7E6183`
- Conservative Pass 1 adjudication fingerprint: `618345BBF1B731EEF7FAF49435F123AA0BDBFD21CAF2EC65F9AABF4894A7CDAA`
- Conservative adjudication file SHA-256: `E53D1A4A22FA7C7F48DB4A254EB01E9B418BE245627A5E1BC35312C4E8DBC341`
- Pass 2 final fingerprint: `E1376174F0F6F62136177989E3CB35FC147E05D2309FF6BE3AB4587A4846AEAF`
- Pass 2 file SHA-256: `96D7E4758F23750638C1FEF6E7C45A5BA57BB118F42086C4F1786E9348A059A2`

Pass 1 was written and hashed before later-session prices were inspected. Pass 2
validates that fingerprint and the eight source-partition hashes before reading
later bars. Conflicting write-once outputs fail closed.

Hard-chew self-review after Pass 2 found that the first decision packet treated
CRWV's quote below its trigger as pending even though the completed 09:34 bar
had already crossed the trigger. The original packet remains immutable. A
separate adjudication corrects CRWV to `MISSED_ENTRY_BEFORE_DECISION` and
`NO_NEW_STRUCTURE`; it adds no allowed setup and does not alter IREN's frozen
decision or outcome. Because that adjudication occurred after outcome review, it
is disclosed as a conservative correction rather than represented as a second
outcome-blind pass. Its inherited `outcomeEvidenceInspected: false` field means
the reconstruction function did not read post-cutoff bars; it does **not** mean
the adjudication artifact predates Pass 2. Only fingerprint
`9C2F2AB10FA2BF97BB4854286DFA692142BD993DD80EF7E2526329A5C778FF5E`
is the original outcome-blind Pass 1.

## Source Truth

### Preserved At The Real Decision

- Opening capture:
  `MomentumHunterData/data/captures/2026-08-13/opening.json`
- TradePlan briefing:
  `MomentumHunterData/data/reports/trade-plan-briefing-2026-08-13-opening.json`
- Capture time: `2026-08-13T08:35:01.779338-05:00`
- Fresh Schwab quote receipt used for the cutoff: approximately 09:35:38 ET
- Original Daily levels, ATR, setup fingerprint, candidate rank, and report
  readiness from the preserved TradePlan briefing

The actual morning runtime had zero Aug. 13 canonical candle bars. It therefore
could not use the reconstructed premarket, 15-minute, or opening-range structure.

### Backfilled After The Decision

A bounded read-only Schwab `/pricehistory` pull collected the five candidates and
SPY, QQQ, and IWM after the session. Every minute partition was first received
after 20:30 UTC. These bars are labeled:

`RETROSPECTIVE_CANONICAL_HISTORY_RESEARCH_ONLY`

The returned intraday path starts at 07:00 ET. The 04:00-07:00 path and true
20:00-04:00 overnight path are unavailable:

`TRUE_OVERNIGHT_PATH_UNOBSERVED`

The reported VWAP values are deterministic typical-price-by-volume aggregates
from canonical one-minute OHLCV. They are approximations, not provider VWAP
fields.

## Broad Market At 09:35

| Benchmark | Premarket | 09:30-09:34 | Research context |
| --- | ---: | ---: | --- |
| SPY | +0.1072% | +0.0659% | Supportive |
| QQQ | +0.1035% | +0.1131% | Supportive |
| IWM | +0.1911% | +0.1381% | Supportive |

All three benchmarks advanced both premarket and during the completed opening
range. The case-study regime is therefore
`SUPPORTIVE_RISK_ON_RESEARCH_CONTEXT`. This is context, not a new regime rule.

## Decision Summary

| Symbol | Original entry | Ask | Original extension | Original premarket cross | Full-structure result | Frozen decision |
| --- | ---: | ---: | ---: | --- | --- | --- |
| CRWV | $111.83 | $111.82 | -0.0089% | No; crossed during opening | Original crossed before decision; no successor structure | Block / indeterminate |
| NBIS | $259.44 | $270.25 | +4.1667% | No; crossed during opening | Original missed; no successor structure | Block |
| IREN | $44.67 | $47.04 | +5.3056% | 07:33 ET | Potential new continuation at $47.01 | Research allow |
| HPE | $58.90 | $62.46 | +6.0441% | Before first 07:00 bar | Original missed; vertical/unconfirmed | Block |
| SMCI | $38.15 | $39.29 | +2.9882% | Before first 07:00 bar | Reclaim occurred, but no current fresh trigger | Block |

No row is a retrospective Paper trade. `Research allow` means only that the
frozen exploratory model found a structurally complete case for outcome study.

## Model Comparison

### Model A: Original Daily Level Only

- CRWV's quote alone looked one cent below the trigger with about 2.00R, but the
  completed 09:34 bar proves the original trigger had already crossed before the
  decision. Quote-only Model A therefore missed lifecycle chronology.
- NBIS, IREN, HPE, and SMCI were 2.99%-6.04% beyond their original levels.
- The model correctly refused to chase those four original setups.
- It could not ask whether a successor setup had formed.

### Model B: Prior 09:15-09:29 Candle As Dominant Reference

| Symbol | 15m trigger | Stop | Ask extension | Execution R/R | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| CRWV | $107.15 | $105.56 | +4.3584% | -0.2380 | Block |
| NBIS | $255.98 | $250.85 | +5.5747% | -0.2067 | Block |
| IREN | $46.04 | $45.12 | +2.1720% | 0.4375 | Block |
| HPE | $61.68 | $60.25 | +1.2646% | 0.9412 | Block |
| SMCI | $38.35 | $37.80 | +2.4511% | 0.1074 | Block |

The 15-minute candle was useful as a feature for all five symbols. Used alone,
it authorized no trade and therefore did not itself create a misleading trade.
It would still misstate setup identity, especially for CRWV, because its high is
not automatically a separately formed continuation trigger.

### Model C: Premarket + Prior 15m + Completed Opening Range

Model C changed the structural conclusion only for IREN. It preserved the Daily
setup as IREN's immutable missed predecessor and created a distinct research
Setup ID for the later continuation. It did not move the old entry upward.

The other four cases lacked a new trigger chronology, acceptable current trigger,
or defensible nonvertical entry by the cutoff. Model C therefore did not use
later gains to force them into trades.

## Candidate Reconstructions

### CRWV

1. Original breakout before 09:30: **No.** Premarket high was $107.15 versus
   the $111.83 trigger.
2. Approximate first breakout: The 09:34 completed minute reached $112.00. No
   exact tick crossing time is available.
3. Original setup genuinely missed: **Yes.** The trigger crossed before the
   09:35 decision and remains immutable even though the quote later slipped one
   cent below the level.
4. New defensible structure by 09:35: **No.** No completed base, pullback, or
   reclaim existed after the 09:34 crossing.
5. Best family: `NO_NEW_STRUCTURE` for a successor; the original
   `OPENING_BREAKOUT` is missed.
6-8. Fresh trigger/stop/R/R: Unavailable without inventing post-cross structure.
9. Vertical/overextended: The opening range rose 4.17% and 0.58 ATR in five
   minutes, with the crossing occurring in the final completed minute.
10. Last 15 minutes: Useful evidence of acceleration into the open.
11. Last-15 alone: It blocked at a stale $107.15 reference and would misstate
   identity; it did not create a trade.
12. Full structure versus A/B: It corrected Model A's quote-only pending state
   and avoided replacing the missed setup with the 15-minute high.
13. Classification: `INDETERMINATE_EVIDENCE`, because the actual runtime lacked
   the candles needed to make this structural determination.

Premarket: O $105.145, H $107.15, L $104.80, C $107.07, volume 481,640,
VWAP approximation $105.792894. Last 15m: O $105.91, H $107.15, L $105.56,
C $107.07, volume 69,502. Opening: O/L $107.14, H $112.00, C $111.605,
volume 2,648,676.

Post-decision observation, not a trade: high $117.49 (+5.0706% from the ask),
low $105.84 (-5.3479%), 15:55 close $106.095.

### NBIS

1. Original breakout before 09:30: **No.** Premarket high was $255.98 versus
   $259.44.
2. Approximate breakout: During the 09:30-09:34 opening range.
3. Original setup genuinely missed: **Yes**, at +4.1667% extension.
4. New defensible structure by 09:35: **No.** The opening move was still the
   impulse and had not built a successor base.
5. Best family: `NO_NEW_STRUCTURE` for a successor; the old family remains an
   immutable missed `OPENING_BREAKOUT`.
6-8. Fresh trigger/stop/R/R: Unavailable without inventing structure.
9. Vertical/overextended: Yes. The five-minute opening range ran from $255.47
   to $271.4799; the ask was $270.25.
10. Last 15 minutes: Useful proof that the premarket high formed at 09:29.
11. Last-15 alone: It also blocked; it did not create a misleading trade.
12. Full structure: Confirmed that the 15-minute high was part of the ongoing
   impulse rather than an independently established successor setup.
13. Classification:
   `CORRECT_ORIGINAL_SETUP_MISSED_BUT_NEW_SETUP_UNAVAILABLE`.

Premarket: O $249.00, H $255.98, L $248.02, C $255.50, volume 578,156,
VWAP approximation $250.816250. Last 15m: O $252.11, H $255.98, L $250.85,
C $255.50, volume 95,085. Opening: O/L $255.47, H $271.4799, C $270.758,
volume 2,037,332.

Post-decision observation, not a trade: high $275.96 (+2.1129%), low $247.38
(-8.4625%), 15:55 close $253.62.

### IREN

1. Original breakout before 09:30: **Yes.**
2. First recoverable cross: approximately 07:33 ET.
3. Original setup genuinely missed: **Yes**, at +5.3056% extension.
4. New defensible structure by 09:35: **Potentially yes under the exploratory
   model.** A premarket impulse peaked at $46.79 at 07:54, pulled back, recovered
   through the last 15 minutes, and formed a completed opening high at $47.01 at
   09:33 with one later completed minute below that high.
5. Best family: `CONTINUATION_BREAKOUT`.
6. Fresh trigger: $47.01.
7. Structural stop: $45.38 opening-range low.
8. Execution-adjusted R/R: 1.9458 at the $47.04 ask to a $50.27 target.
9. Vertical/overextended: Original setup yes; successor trigger only +0.0638%
   away. This distinction is the research hypothesis.
10. Last 15 minutes: Useful evidence of recovery, but not sufficient alone.
11. Last-15 alone: It blocked at a $46.04 trigger and 0.4375R; it did not create
   a misleading trade.
12. Full structure: Added predecessor chronology, pullback, and opening-range
   evidence that Models A and B lacked.
13. Classification: `POTENTIAL_FRESH_SETUP_NOT_RECOGNIZED`.

Premarket: O $43.40, H $46.79, L $42.78, C $46.02, volume 4,045,859,
VWAP approximation $45.616980. Last 15m: O $45.33, H $46.04, L $45.12,
C $46.02, volume 292,039. Opening: O $45.98, H $47.01, L $45.38,
C $46.85, volume 3,435,016.

Pass 2: hypothetical entry $47.04, target $50.27, stop $45.38. Maximum
favorable excursion before termination was +4.5599%; maximum adverse excursion
was -3.5289%. Target was never reached. Stop was reached at 12:07 ET, about
151.4 minutes after the decision. The real MH rejection therefore avoided this
frozen hypothetical loss. This outcome does not invalidate the setup identity
hypothesis, but it strongly rejects any claim that Aug. 13 demonstrates a
profitable missed IREN trade.

### HPE

1. Original breakout before 09:30: **Yes, before the earliest 07:00 ET bar.**
2. Exact time: Unavailable.
3. Original setup genuinely missed: **Yes**, at +6.0441% extension.
4. New defensible structure by 09:35: **No.** Premarket high occurred at 09:29
   and the opening continued the impulse.
5. Best family: `NO_NEW_STRUCTURE`.
6-8. Fresh trigger/stop/R/R: Unavailable without inventing a base.
9. Vertical/overextended: Yes; opening range was 0.758 ATR and current Daily
   execution R/R had fallen to 0.5568.
10. Last 15 minutes: Useful confirmation that the high was still forming.
11. Last-15 alone: It blocked at 0.9412R; it did not create a trade.
12. Full structure: Prevented treating the 09:29 high as a mature setup.
13. Classification:
   `CORRECT_ORIGINAL_SETUP_MISSED_BUT_NEW_SETUP_UNAVAILABLE`.

Premarket: O $60.25, H $61.68, L $60.12, C $61.68, volume 485,016,
VWAP approximation $60.886709. Last 15m: O $60.73, H $61.68, L $60.25,
C $61.68, volume 95,339. Opening: O $61.20, H $63.44, L $61.00,
C $62.72, volume 2,747,591.

Post-decision observation, not a trade: high $62.90 (+0.7045%), low $59.68
(-4.4508%), 15:55 close $59.94.

### SMCI

1. Original breakout before 09:30: **Yes, before the earliest 07:00 ET bar.**
2. Exact first cross: Unavailable.
3. Original setup genuinely missed: **Yes**, at +2.9882% extension.
4. New defensible structure by 09:35: **No current entry.** Price traded back
   below the original level, reclaimed it, then reached $39.68 at 09:33. The
   09:35 ask had already fallen to $39.29, below that possible new trigger.
5. Best family: `NO_NEW_STRUCTURE`; chronology contains a reclaim, but a valid
   fresh reclaim/continuation trigger was not current at the cutoff.
6-8. Fresh trigger/stop/R/R: Not frozen.
9. Vertical/overextended: The original and last-15 references were 2.99% and
   2.45% behind the ask, respectively.
10. Last 15 minutes: Useful evidence of the pre-open reclaim.
11. Last-15 alone: It blocked at 0.1074R; it did not create a trade.
12. Full structure: Kept the reclaim chronology without manufacturing an entry
   after the opening high had already printed.
13. Classification:
   `CORRECT_ORIGINAL_SETUP_MISSED_BUT_NEW_SETUP_UNAVAILABLE`.

Premarket: O $38.50, H $38.5862, L $37.80, C $38.25, volume 2,003,593,
VWAP approximation $38.163829. Last 15m: O $37.89, H $38.35, L $37.80,
C $38.25, volume 263,461. Opening: O $38.28, H $39.68, L $38.20,
C $39.175, volume 6,034,683.

Post-decision observation, not a trade: high $42.31 (+7.6864%), low $39.06
(-0.5854%), 15:55 close $39.335. This large later gain does not create a valid
09:35 setup retroactively.

## Verticality Features Worth Collecting Prospectively

The research implementation records, without granting production authority:

- Move from prior close in percent and ATR units
- Move from premarket VWAP approximation in ATR units
- 5/15/30/60-minute returns
- Opening and last-15 range in ATR units
- Maximum pullback depth in ATR units
- Exploratory count of pullbacks at least 0.25 ATR
- Maximum consecutive upward bars
- Distance from original, premarket-high, opening-high, and VWAP references
- Execution R/R to an actual structural stop

No threshold from this five-name session is proposed as production truth.

## Minimum Recommended Implementation

Do not alter the 0.25% rule. Apply it to the frozen trigger belonging to the
current Setup ID.

The minimum later implementation should reuse DATA-003, DATA-004, and
CONTINUOUS-003:

1. Load prospective canonical premarket history for each admitted candidate.
2. Compute premarket, prior completed 15-minute, and completed opening-range
   evidence with source identities.
3. Preserve the original setup as untouched, missed, or failed.
4. When missed, run a separate successor evaluator for existing
   `CONTINUATION_BREAKOUT`, `PULLBACK`, and `RECLAIM` families.
5. Require chronology, a new Setup ID, predecessor identity, trigger, structural
   stop, targets, execution-adjusted R/R, and nonvertical entry evidence.
6. Apply the unchanged 0.25% extension limit to that new trigger.
7. Send only prospectively valid output through the existing Risk Governor and
   Paper path.

Before production, replay this evaluator prospectively across a larger,
outcome-blind sample containing winners, losers, and no-trades. Aug. 13 alone is
not enough to select thresholds.

## Remaining Evidence Gaps

- No Aug. 13 candles were available to the actual 09:35 runtime.
- Schwab returned no 04:00-07:00 path for this bounded historical request.
- Exact tick crossing times are unavailable; minute bars provide approximations.
- Derived VWAP is not an authoritative provider VWAP field.
- Sector-relative context was not already available for all five candidates.
- One favorable market regime cannot establish regime-conditioned authority.
- One potential successor setup, which stopped out, cannot validate an edge.
- Structural thresholds need a larger prospective, outcome-blind sample.

## Verification

Focused synthetic tests cover:

- Distinct successor Setup ID and predecessor identity
- Vertical/no-new-structure blocking
- Completed-window aggregation and derived VWAP
- Legacy-source mixing rejection
- Session, timestamp, minute-identity, and final-history tamper rejection
- Post-cutoff exclusion from Pass 1
- Pass 1 tamper rejection
- Target/stop outcome ordering
- Lifecycle-bounded MFE/MAE
- Absence of runtime, broker, scheduler, scoring, and Risk Governor imports

Verification results:

- Python compileall: pass
- Focused research tests: 12 / 12 pass
- Adjacent setup, TradePlan, and candle regressions: 143 / 143 pass
- Complete Python discovery: 1,936 / 1,936 pass in 272.833 seconds

The implementation is an offline explicit-path CLI. It performs no provider,
account, broker, Engine Host, scheduler, service, WPF, Paper, or production-store
operation.
