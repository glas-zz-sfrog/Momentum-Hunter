# Broker Integration Roadmap

## Goal
Stage broker integration so Argus earns trust before any real capital path exists.

## Phase 1 - No Broker
Build gateway, console skeleton, TradePlan, Risk Governor, and machine logging without broker connectivity.

## Phase 2 - Fake Broker
Use FakeBrokerAdapter for simulated order lifecycle and Execution Ledger proof.

## Phase 3 - Paper Broker
Connect to a paper environment only. Paper actions must be clearly labeled and ledgered.

## Phase 4 - Read-Only Live Broker
Read live account, position, and buying-power context without any order ability.

## Phase 5 - Live Order Preview
Generate reviewable order payloads but do not transmit. Steven sees exactly what would be sent.

## Phase 6 - Confirmed Live Execution
Only after explicit Steven approval, implement the narrowest confirmed send path with Risk Governor pass, TradePlan linkage, approval state, and Execution Ledger writes.

## Phase 7 - Supervised Automation
Permit limited autonomous monitoring or action only after live execution has a proven audit trail and Steven approves the exact scope.

## Safety Gates
- Separate Goal Charter for each phase.
- Git Steward branch preflight.
- Security review for credentials and logging.
- Risk Governor review for gate semantics.
- Execution Auditor review for ledger completeness.
- Focused tests for locked and blocked states.
