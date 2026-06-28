# Top 5 Trade Plan Candidates Spec

## Goal
The Top 5 area gives Steven a fast machine-ranked view of the most important candidate trade plans without implying that they are approved live trades.

## Required Row Content
- Ticker.
- Setup label.
- Plan status.
- Risk or gate state when available.

## Click Behavior
The ticker or row should be clickable. Selecting a candidate populates the Trade Plan Ladder and Selected Candidate Workbench.

## Ranking
Ranking should eventually use machine priority, data quality, setup maturity, risk gate state, and paper/simulation outcomes. Early placeholder implementations can use static or safely available candidate data if clearly labeled.

## Safe Labels
Preferred labels:
- Top 5 Setups.
- Top 5 Trade Plan Candidates.
- Top 5 Machine Plans.

Avoid "Strongest Trades" until Risk Governor and paper outcomes prove that wording.

## Empty And Blocked States
If there are fewer than five candidates, show fewer rows and explain why. If stale data, missing plan fields, or risk gates block a candidate, show that state directly.
