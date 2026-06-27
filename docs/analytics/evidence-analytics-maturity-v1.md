# Evidence Analytics Maturity v1

Momentum Hunter uses this report to keep alert research honest while the sample size is still small.

The report is evidence-only. It does not change:

- scoring
- readiness rules
- alert thresholds
- outcome classification
- trade-planning rules
- broker/order behavior

## Sample Gates

| Completed alerts | Allowed action | Strategy changes |
| ---: | --- | --- |
| 0-24 | Collect evidence only | Locked |
| 25-49 | Identify early patterns | Locked |
| 50-99 | Recommend investigations | Locked |
| 100+ | Review possible strategy modifications | Still requires human review |

Group-level summaries use a smaller diagnostic threshold of 10 completed outcomes per alert type, symbol, or readiness state. Groups below that threshold are shown as insufficient sample rather than hidden.

## Data Categories

The report separates:

- completed scored outcomes
- true pending alerts
- terminal unscorable data-quality outcomes
- missing minute bars
- incomplete outcome records
- missing readiness/news context

Pending and unscorable alerts are not counted as completed outcomes and do not unlock evidence gates.

## Output

Latest reports are written to:

```text
MomentumHunterData/data/reports/evidence-analytics-maturity-latest.json
MomentumHunterData/data/reports/evidence-analytics-maturity-latest.md
```

## Use

Use this before asking whether Momentum Hunter has an edge. If the report says the gates are locked, the correct action is to keep collecting evidence, not tune thresholds or optimize weights.
