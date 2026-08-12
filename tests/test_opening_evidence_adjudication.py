from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.opening_evidence_adjudication import (
    DECISION_NOT_REACHED,
    RAW_COUNTS_NOT_PRESERVED,
    SYSTEM_DATA_CONTRACT_FAILURE,
    OpeningEvidenceAdjudicationError,
    OpeningEvidenceCase,
    adjudicate_opening_evidence,
    write_adjudication,
)
from momentum_hunter.provider_neutral_allocation import evidence_fingerprint


class OpeningEvidenceAdjudicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.capture = self.root / "opening.json"
        self.capture.write_text(
            json.dumps(
                {
                    "session": "opening",
                    "provider": "finviz",
                    "candidates": [],
                }
            ),
            encoding="utf-8",
        )
        self.report = self.root / "report.json"
        self.report.write_text(json.dumps({"candidates": []}), encoding="utf-8")
        self.log = self.root / "opening.log"
        self.log.write_text("Candidates: 0\nExitCode: 0\n", encoding="utf-8")
        self.paper = self.root / "paper.json"
        decision = {
            "classification": "NO_TRADE",
            "candidatesEvaluated": 0,
            "paperOrderCreated": False,
            "providerCalls": [],
            "reasons": ["PAPER_NO_CANDIDATES_IN_PROSPECTIVE_REPORT"],
            "decisionCycleId": "paper-cycle-test",
            "sampleId": "alpaca-paper-engineering-test-v1",
        }
        decision["fingerprint"] = evidence_fingerprint(decision)
        self.paper.write_text(json.dumps({"decision": decision}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def case(self) -> OpeningEvidenceCase:
        return OpeningEvidenceCase(
            market_date="2026-08-11",
            parser_git_head="a" * 40,
            capture_path=self.capture,
            log_path=self.log,
            report_path=self.report,
            paper_decision_paths=(self.paper,),
        )

    @patch(
        "momentum_hunter.opening_evidence_adjudication._git_file",
        return_value='percent_change=parse_percent(values.get("Change", ""))',
    )
    def test_invalidated_zero_is_decision_not_reached_without_invented_counts(
        self,
        _git_file,
    ) -> None:
        result = adjudicate_opening_evidence(
            [self.case()],
            repository_root=self.root,
            adjudicated_at=datetime.fromisoformat("2026-08-12T10:30:00-05:00"),
        )

        self.assertEqual(SYSTEM_DATA_CONTRACT_FAILURE, result["classification"])
        self.assertEqual(DECISION_NOT_REACHED, result["decisionState"])
        self.assertEqual(RAW_COUNTS_NOT_PRESERVED, result["rawCountStatus"])
        case = result["cases"][0]
        self.assertIsNone(case["rawProviderRows"])
        self.assertIsNone(case["parsedRows"])
        self.assertFalse(case["qualifiedRowsAuthoritative"])
        self.assertFalse(case["paperDecisions"][0]["countsTowardAnySample"])
        self.assertFalse(result["historicalArtifactsMutated"])

    @patch(
        "momentum_hunter.opening_evidence_adjudication._git_file",
        return_value='percent_change=parse_percent(values.get("Change", ""))',
    )
    def test_write_once_outputs_are_idempotent_and_conflicts_fail(self, _git_file) -> None:
        result = adjudicate_opening_evidence(
            [self.case()],
            repository_root=self.root,
            adjudicated_at=datetime.fromisoformat("2026-08-12T10:30:00-05:00"),
        )
        json_path = self.root / "adjudication.json"
        markdown_path = self.root / "adjudication.md"

        write_adjudication(result, json_path=json_path, markdown_path=markdown_path)
        before = json_path.read_bytes()
        write_adjudication(result, json_path=json_path, markdown_path=markdown_path)
        self.assertEqual(before, json_path.read_bytes())
        markdown_path.write_text("conflict", encoding="utf-8")
        with self.assertRaisesRegex(OpeningEvidenceAdjudicationError, "Conflicting"):
            write_adjudication(result, json_path=json_path, markdown_path=markdown_path)

    @patch(
        "momentum_hunter.opening_evidence_adjudication._git_file",
        return_value="percent_change=parse_percent(values.get(\"Change %\", \"\"))",
    )
    def test_nonvulnerable_parser_cannot_be_invalidated_by_this_adjudicator(
        self,
        _git_file,
    ) -> None:
        with self.assertRaisesRegex(OpeningEvidenceAdjudicationError, "does not contain"):
            adjudicate_opening_evidence([self.case()], repository_root=self.root)

    @patch(
        "momentum_hunter.opening_evidence_adjudication._git_file",
        return_value='percent_change=parse_percent(values.get("Change", ""))',
    )
    def test_candidate_bearing_capture_is_rejected(self, _git_file) -> None:
        self.capture.write_text(
            json.dumps({"session": "opening", "provider": "finviz", "candidates": [{}]}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(OpeningEvidenceAdjudicationError, "not zero-candidate"):
            adjudicate_opening_evidence([self.case()], repository_root=self.root)


if __name__ == "__main__":
    unittest.main()
