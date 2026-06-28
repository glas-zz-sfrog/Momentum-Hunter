# Trade Plan Ladder Spec

## Goal
The Trade Plan Ladder turns a candidate setup into a structured plan that can be reviewed, simulated, paper traded, and eventually audited for broker execution readiness.

## Required Fields
- Ticker.
- Setup type.
- Entry trigger.
- Entry or limit price.
- Invalidation or hard stop.
- Target 1.
- Target 2.
- Target 3.
- Trailing stop rule.
- Position size.
- Max dollar risk.
- Risk/reward.
- Manual override state.
- Risk Governor status.

## Top 5 Interaction
Each Top 5 Trade Plan Candidate ticker must be clickable. Clicking the ticker selects that candidate and populates the ladder. If the candidate lacks a full plan, the ladder should show missing fields and the next required plan-building action.

## Manual Overrides
If Steven edits any machine-filled field, the field and plan must be marked as manual override. Manual overrides require Risk Governor re-check before any simulation, paper, preview, or live state can advance.

## Status Language
Use labels such as draft, missing fields, needs risk check, simulation-ready, paper-eligible, preview-only, blocked, and live-locked. Do not use approved live language until a future live execution task explicitly implements it.

## Non-Goals
This spec does not authorize broker order placement, scoring changes, or database/schema changes.
