# Goal Charter: ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001D

## Objective

Repair the admitted-finality boundary, decision identity, completed-bar event
clocks, and forensic stage accounting revealed by the failed Producer-001C
provider canary, then repeat the bounded provider proof.

## Starting Identity

- Canonical production remains `82460b3313b86c34dff4ffb737d2c04bf02e3ace`.
- Stacked parent is reviewed Producer-001C head
  `b7f6df51e9f6e08056c58b419c870f116096179c`.
- Branch is `codex/ARGUS-CONTINUOUS-TRADEPLAN-PRODUCER-001D`.
- Authority is `RESEARCH_ONLY`; order capability is `UNAVAILABLE`.

## Acceptance

- Observed/discarded provisional versions remain diagnostic and cannot block a
  decision whose admitted authoritative set contains zero provisional bars.
- Decision identity ignores diagnostic-only provisional inventory while still
  changing for newly admitted or materially changed completed evidence.
- New completed-bar runtime events preserve provider and receipt clocks;
  legacy checkpoints lacking provider time restore without fabrication.
- Every forensic stage is classified from its own evidence, even when a later
  analyzer or acceptance stage fails.
- Offline exact-path replay and Hard Chew pass before provider contact.
- Every terminal provider outcome produces a sanitized self-contained packet.

## Hard Stop

Do not merge, deploy, activate Paper or Shadow, query accounts or positions, or
expose broker/order capability. Stop after the new second-eye packet.
