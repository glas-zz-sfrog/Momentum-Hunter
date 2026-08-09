from __future__ import annotations

import unittest
from dataclasses import fields, replace
from decimal import Decimal

from momentum_hunter.paper_research_evidence import (
    CandidateDisposition,
    ExecutionResultEvidence,
    ExecutionResultType,
    PaperResearchPolicy,
    ProspectiveResearchCandidate,
    build_paper_research_portfolio_evidence,
    pair_execution_results,
)
from momentum_hunter.provider_neutral_allocation import (
    AllocationStatus,
    ProviderNeutralAllocationDecision,
    QuantityMode,
)


def allocation(
    *, authorized: bool = True, candidate_number: int = 1
) -> ProviderNeutralAllocationDecision:
    quantity = Decimal("0.250") if authorized else Decimal("0")
    return ProviderNeutralAllocationDecision(
        request_fingerprint=f"{candidate_number:X}" * 64,
        policy_fingerprint="A" * 64,
        account_snapshot_fingerprint="B" * 64,
        capability_registry_fingerprint="C" * 64,
        status=AllocationStatus.AUTHORIZED if authorized else AllocationStatus.BLOCKED,
        quantity_mode=QuantityMode.FRACTIONAL,
        quantity_increment=Decimal("0.001"),
        ideal_risk_quantity=Decimal("0.300"),
        provider_executable_quantity=Decimal("0.300"),
        final_authorized_quantity=quantity,
        risk_per_share=Decimal("2"),
        effective_cash_available=Decimal("90"),
        effective_open_risk_available=Decimal("5"),
        position_notional=Decimal("25") if authorized else None,
        total_risk=Decimal("0.5") if authorized else None,
        target_reward=Decimal("1") if authorized else None,
        blockers=() if authorized else ("SYNTHETIC_BLOCK",),
    )


def candidate(
    rank: int,
    *,
    independently_eligible: bool = True,
    allocation_authorized: bool = True,
) -> ProspectiveResearchCandidate:
    return ProspectiveResearchCandidate(
        candidate_id=f"candidate-{rank}",
        decision_cycle_id="cycle-1",
        canonical_rank=rank,
        symbol=f"SYM{rank}",
        setup_id=f"setup-{rank}",
        trade_plan_id=f"plan-{rank}",
        risk_decision_id=f"risk-{rank}",
        source_evidence_fingerprint=str(rank) * 64,
        allocation=allocation(
            authorized=allocation_authorized,
            candidate_number=rank,
        ),
        independently_eligible=independently_eligible,
        eligibility_blockers=(
            () if independently_eligible else ("EVIDENCE_NOT_ELIGIBLE",)
        ),
    )


def research_policy(max_positions: int = 2) -> PaperResearchPolicy:
    return PaperResearchPolicy(
        policy_id="paper-research-v1",
        lane="PAPER_RESEARCH",
        participating_ranks=(1, 2, 3),
        max_concurrent_positions=max_positions,
    )


def result(
    result_type: ExecutionResultType,
    *,
    candidate_id: str = "candidate-1",
    requested_quantity: Decimal = Decimal("0.250"),
) -> ExecutionResultEvidence:
    return ExecutionResultEvidence(
        result_type=result_type,
        result_id=f"result-{result_type.value}",
        decision_cycle_id="cycle-1",
        candidate_id=candidate_id,
        trade_plan_id="plan-1",
        symbol="TEST",
        requested_quantity=requested_quantity,
        filled_quantity=Decimal("0.250"),
        entry_price=Decimal("20"),
        exit_price=Decimal("21"),
        realized_pnl=Decimal("0.25"),
        terminal_status="FILLED_AND_CLOSED",
        evidence_fingerprint="E" * 64,
        observed_at="2026-08-10T20:00:00+00:00",
    )


class PaperResearchEvidenceTests(unittest.TestCase):
    def test_rank_one_two_three_are_preserved_with_independent_eligibility(self) -> None:
        evidence = build_paper_research_portfolio_evidence(
            policy=research_policy(max_positions=2),
            candidates=(candidate(3), candidate(1), candidate(2)),
            existing_open_positions=0,
        )

        self.assertEqual([1, 2, 3], [item.canonical_rank for item in evidence.records])
        self.assertEqual(
            [
                CandidateDisposition.WOULD_ADMIT,
                CandidateDisposition.WOULD_ADMIT,
                CandidateDisposition.WITHHELD_CONCURRENCY,
            ],
            [item.disposition for item in evidence.records],
        )
        self.assertTrue(evidence.records[2].independently_eligible)
        self.assertFalse(evidence.activated)
        self.assertFalse(evidence.orders_created)
        self.assertFalse(evidence.counts_toward_official_sample)
        construction_fields = {
            item.name: item.init for item in fields(type(evidence))
        }
        self.assertFalse(construction_fields["activated"])
        self.assertFalse(construction_fields["orders_created"])
        self.assertFalse(construction_fields["counts_toward_official_sample"])

    def test_existing_portfolio_positions_reduce_available_slots(self) -> None:
        evidence = build_paper_research_portfolio_evidence(
            policy=research_policy(max_positions=3),
            candidates=(candidate(1), candidate(2), candidate(3)),
            existing_open_positions=2,
        )

        self.assertEqual(CandidateDisposition.WOULD_ADMIT, evidence.records[0].disposition)
        self.assertEqual(
            CandidateDisposition.WITHHELD_CONCURRENCY,
            evidence.records[1].disposition,
        )
        self.assertEqual(
            CandidateDisposition.WITHHELD_CONCURRENCY,
            evidence.records[2].disposition,
        )

    def test_independent_ineligibility_does_not_consume_portfolio_slot(self) -> None:
        evidence = build_paper_research_portfolio_evidence(
            policy=research_policy(max_positions=1),
            candidates=(
                candidate(1, independently_eligible=False),
                candidate(2),
                candidate(3),
            ),
            existing_open_positions=0,
        )

        self.assertEqual(CandidateDisposition.INELIGIBLE, evidence.records[0].disposition)
        self.assertIn(
            "EVIDENCE_NOT_ELIGIBLE", evidence.records[0].eligibility_blockers
        )
        self.assertEqual(CandidateDisposition.WOULD_ADMIT, evidence.records[1].disposition)
        self.assertEqual(
            CandidateDisposition.WITHHELD_CONCURRENCY,
            evidence.records[2].disposition,
        )

    def test_allocation_block_is_preserved_as_ineligible(self) -> None:
        evidence = build_paper_research_portfolio_evidence(
            policy=research_policy(),
            candidates=(candidate(1, allocation_authorized=False), candidate(2)),
            existing_open_positions=0,
        )

        self.assertEqual(CandidateDisposition.INELIGIBLE, evidence.records[0].disposition)
        self.assertIn(
            "SYNTHETIC_BLOCK", evidence.records[0].allocation_blockers
        )
        self.assertEqual(Decimal("0"), evidence.records[0].final_authorized_quantity)

    def test_nonparticipating_rank_remains_visible(self) -> None:
        restricted = replace(research_policy(), participating_ranks=(1, 2))
        evidence = build_paper_research_portfolio_evidence(
            policy=restricted,
            candidates=(candidate(1), candidate(2), candidate(3)),
            existing_open_positions=0,
        )

        self.assertEqual(
            CandidateDisposition.RANK_NOT_PARTICIPATING,
            evidence.records[2].disposition,
        )

    def test_duplicate_rank_or_candidate_identity_is_rejected(self) -> None:
        duplicate_rank = replace(candidate(2), canonical_rank=1)
        duplicate_id = replace(candidate(2), candidate_id="candidate-1")

        with self.assertRaisesRegex(ValueError, "ranks"):
            build_paper_research_portfolio_evidence(
                policy=research_policy(),
                candidates=(candidate(1), duplicate_rank),
                existing_open_positions=0,
            )
        with self.assertRaisesRegex(ValueError, "identities"):
            build_paper_research_portfolio_evidence(
                policy=research_policy(),
                candidates=(candidate(1), duplicate_id),
                existing_open_positions=0,
            )

    def test_candidate_lineage_is_preserved_in_serialized_evidence(self) -> None:
        source = candidate(1)
        evidence = build_paper_research_portfolio_evidence(
            policy=research_policy(),
            candidates=(source,),
            existing_open_positions=0,
        )

        record = evidence.to_dict()["records"][0]
        self.assertEqual(source.setup_id, record["setupId"])
        self.assertEqual(source.trade_plan_id, record["tradePlanId"])
        self.assertEqual(source.risk_decision_id, record["riskDecisionId"])
        self.assertEqual(
            source.source_evidence_fingerprint,
            record["sourceEvidenceFingerprint"],
        )

    def test_missing_candidate_lineage_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            build_paper_research_portfolio_evidence(
                policy=research_policy(),
                candidates=(replace(candidate(1), source_evidence_fingerprint=""),),
                existing_open_positions=0,
            )
    def test_result_domains_remain_separate_and_statistics_are_not_combined(self) -> None:
        paper = result(ExecutionResultType.ALPACA_PAPER_EXECUTION_RESULT)
        conservative = result(
            ExecutionResultType.MH_CONSERVATIVE_EXECUTABLE_RESULT
        )

        comparison = pair_execution_results(paper, conservative)

        self.assertIs(paper, comparison.alpaca_paper_execution_result)
        self.assertIs(
            conservative, comparison.mh_conservative_executable_result
        )
        self.assertFalse(comparison.statistics_combined)
        construction_fields = {
            item.name: item.init for item in fields(type(comparison))
        }
        self.assertFalse(construction_fields["statistics_combined"])

    def test_result_domain_or_identity_mismatch_is_rejected(self) -> None:
        conservative = result(
            ExecutionResultType.MH_CONSERVATIVE_EXECUTABLE_RESULT
        )
        with self.assertRaisesRegex(ValueError, "wrong evidence domain"):
            pair_execution_results(conservative, conservative)
        with self.assertRaisesRegex(ValueError, "prospective identity"):
            pair_execution_results(
                result(ExecutionResultType.ALPACA_PAPER_EXECUTION_RESULT),
                result(
                    ExecutionResultType.MH_CONSERVATIVE_EXECUTABLE_RESULT,
                    candidate_id="other-candidate",
                ),
            )

    def test_invalid_execution_result_evidence_is_rejected(self) -> None:
        paper = result(ExecutionResultType.ALPACA_PAPER_EXECUTION_RESULT)
        conservative = result(
            ExecutionResultType.MH_CONSERVATIVE_EXECUTABLE_RESULT
        )
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            pair_execution_results(
                replace(paper, evidence_fingerprint="not-a-hash"),
                conservative,
            )
        with self.assertRaisesRegex(ValueError, "exceed"):
            pair_execution_results(
                replace(paper, filled_quantity=Decimal("1")),
                conservative,
            )
        with self.assertRaisesRegex(ValueError, "quantities"):
            pair_execution_results(
                replace(paper, requested_quantity="invalid"),  # type: ignore[arg-type]
                replace(
                    conservative,
                    requested_quantity="invalid",  # type: ignore[arg-type]
                ),
            )


if __name__ == "__main__":
    unittest.main()
