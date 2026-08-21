from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.alpaca_paper_engineering import (
    CONTINUOUS_PAPER_DECISION_CONFIRMATION,
    PAPER_ENGINEERING_SAMPLE_CONFIRMATION,
    PAPER_TRADE_CREATED,
    AlpacaPaperEngineeringEngine,
    freeze_paper_engineering_sample,
)
from momentum_hunter.continuous_paper_contract import (
    build_continuous_paper_admission_intent,
)
from tests.test_alpaca_paper_engineering import (
    DECISION_AT,
    SyntheticAdapter,
    SyntheticQuoteSource,
    policy,
    quote_result,
    registry,
)
from tests.test_continuous_paper_contract import at, fixtures


CONTINUOUS_DECISION_AT = at(11, 1)


class ContinuousPaperEngineeringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        lifecycle = self.root / "lifecycle-final.json"
        lifecycle.write_text(json.dumps({"fingerprint": "A" * 64}), encoding="ascii")
        continuous_policy = replace(
            policy(),
            sample_id="continuous-paper-engineering-20260820-v1",
            policy_id="continuous-paper-engineering-policy-20260820-v1",
        )
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ), patch(
            "tests.test_alpaca_paper_engineering.DECISION_AT",
            CONTINUOUS_DECISION_AT,
        ):
            freeze_paper_engineering_sample(
                policy=continuous_policy,
                lifecycle_proof_path=lifecycle,
                output_directory=self.root / "paper",
                confirmation=PAPER_ENGINEERING_SAMPLE_CONFIRMATION,
                activated_at=CONTINUOUS_DECISION_AT - timedelta(minutes=5),
            )
        cycle, member_result, universe_member = fixtures()
        self.admission = build_continuous_paper_admission_intent(
            cycle=cycle,
            member=member_result,
            universe_member=universe_member,
            runtime_configuration_fingerprint="f" * 64,
            product_sha="1" * 40,
        )
        self.source = self.root / "writer-record.json"
        self.source.write_text(json.dumps(self.admission.to_dict()), encoding="ascii")

    def engine(self, adapter: SyntheticAdapter):
        quote = quote_result(
            symbol="SPCX",
            bid=100.0,
            ask=100.1,
            last=100.05,
            timestamp=(CONTINUOUS_DECISION_AT - timedelta(seconds=1)).isoformat(),
            providerQuoteTimestamp=(CONTINUOUS_DECISION_AT - timedelta(seconds=1)).isoformat(),
            providerBidTimestamp=(CONTINUOUS_DECISION_AT - timedelta(seconds=1)).isoformat(),
            providerAskTimestamp=(CONTINUOUS_DECISION_AT - timedelta(seconds=1)).isoformat(),
        )
        return AlpacaPaperEngineeringEngine(
            adapter=adapter,
            quote_source=SyntheticQuoteSource({"SPCX": quote}),
            output_directory=self.root / "paper",
            clock=lambda: CONTINUOUS_DECISION_AT,
            sleep=lambda _seconds: None,
        )

    def test_continuous_admission_reuses_a004_fill_and_protection(self):
        adapter = SyntheticAdapter()
        adapter.entry_fill_price = Decimal("100.1")
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ), patch(
            "tests.test_alpaca_paper_engineering.DECISION_AT",
            CONTINUOUS_DECISION_AT,
        ):
            result = self.engine(adapter).run_continuous_admission(
                self.admission.to_dict(),
                source_path=self.source,
                confirmation=CONTINUOUS_PAPER_DECISION_CONFIRMATION,
            )

        self.assertEqual(PAPER_TRADE_CREATED, result["classification"])
        self.assertTrue(result["paperOrderCreated"])
        self.assertTrue(result["positionProtected"])
        self.assertEqual(
            result["entryOrder"]["filledQuantity"],
            result["protectiveStopOrder"]["quantity"],
        )
        self.assertEqual("PASS", result["postFillRisk"]["status"])
        self.assertEqual(
            2,
            sum(call == "POST /v2/orders" for call in adapter.calls),
        )

        calls = list(adapter.calls)
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ), patch(
            "tests.test_alpaca_paper_engineering.DECISION_AT",
            CONTINUOUS_DECISION_AT,
        ):
            duplicate = self.engine(adapter).run_continuous_admission(
                self.admission.to_dict(),
                source_path=self.source,
                confirmation=CONTINUOUS_PAPER_DECISION_CONFIRMATION,
            )
        self.assertEqual(result["fingerprint"], duplicate["fingerprint"])
        self.assertEqual(calls, adapter.calls)

    def test_stale_continuous_plan_is_risk_rejected_before_order(self):
        adapter = SyntheticAdapter()
        late = CONTINUOUS_DECISION_AT + timedelta(hours=8)
        quote = quote_result(
            symbol="SPCX",
            bid=100.0,
            ask=100.1,
            last=100.05,
            timestamp=(late - timedelta(seconds=1)).isoformat(),
            providerQuoteTimestamp=(late - timedelta(seconds=1)).isoformat(),
            providerBidTimestamp=(late - timedelta(seconds=1)).isoformat(),
            providerAskTimestamp=(late - timedelta(seconds=1)).isoformat(),
        )
        engine = AlpacaPaperEngineeringEngine(
            adapter=adapter,
            quote_source=SyntheticQuoteSource({"SPCX": quote}),
            output_directory=self.root / "paper",
            clock=lambda: late,
            sleep=lambda _seconds: None,
        )
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            result = engine.run_continuous_admission(
                self.admission.to_dict(),
                source_path=self.source,
                confirmation=CONTINUOUS_PAPER_DECISION_CONFIRMATION,
            )

        self.assertEqual("PAPER_RISK_REJECTED", result["classification"])
        self.assertFalse(result["paperOrderCreated"])
        self.assertFalse(any(call == "POST /v2/orders" for call in adapter.calls))

    def test_unfilled_continuous_entry_is_broker_rejected_not_strategy_no_trade(self):
        adapter = SyntheticAdapter()
        adapter.entry_fills = False
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ), patch(
            "tests.test_alpaca_paper_engineering.DECISION_AT",
            CONTINUOUS_DECISION_AT,
        ):
            result = self.engine(adapter).run_continuous_admission(
                self.admission.to_dict(),
                source_path=self.source,
                confirmation=CONTINUOUS_PAPER_DECISION_CONFIRMATION,
            )

        self.assertEqual("PAPER_BROKER_REJECTED", result["classification"])
        self.assertTrue(result["paperOrderCreated"])
        self.assertIn("PAPER_ENTRY_UNFILLED", result["reasons"])


if __name__ == "__main__":
    unittest.main()
