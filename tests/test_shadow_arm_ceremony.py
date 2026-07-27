from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, patch

from momentum_hunter.shadow_arm_ceremony import (
    ShadowArmCeremonyError,
    complete_shadow_selector_arm,
    run_command,
)
from momentum_hunter.shadow_proof_bundle import PROJECT_ROOT
from momentum_hunter.shadow_trading import (
    SHADOW_SELECTOR_ARM_CONFIRMATION,
    ShadowStateError,
)


CHECKED_AT = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)


class ShadowArmCeremonyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "proof-bundle"
        self.bundle.mkdir()
        self.report = self.root / "trade-plan-briefing-shadow.json"
        self.report.write_text("{}", encoding="utf-8")
        self.quote_proof = self.root / "live-quote-proof.json"
        self.service = Mock()
        self.service.selector_is_armed.return_value = False
        self.arm = SimpleNamespace(
            arm_id="arm-1",
            armed_at=CHECKED_AT.isoformat(),
        )
        self.service.arm_automatic_selector.return_value = self.arm

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_already_armed_is_nonmutating_and_skips_market_data(self) -> None:
        self.service.selector_is_armed.return_value = True
        self.service.selector_arm_record.return_value = self.arm

        with patch(
            "momentum_hunter.shadow_arm_ceremony.SchwabMarketDataQuoteSource"
        ) as quote_source:
            result = complete_shadow_selector_arm(
                self.bundle,
                self.report,
                service=self.service,
            )

        self.assertEqual("ALREADY_ARMED", result.state)
        self.assertFalse(result.transmitting)
        quote_source.assert_not_called()
        self.service.arm_automatic_selector.assert_not_called()

    def test_complete_bundle_arms_only_through_existing_verifier(self) -> None:
        proofs = SimpleNamespace(hashes={"fresh_quote_boundary": "a" * 64})
        self.service.verify_automatic_selector_prerequisites.return_value = (
            proofs,
            CHECKED_AT,
        )

        result = complete_shadow_selector_arm(
            self.bundle,
            self.report,
            service=self.service,
        )

        self.assertEqual("ARMED_FROM_COMPLETE_BUNDLE", result.state)
        self.service.arm_automatic_selector.assert_called_once_with(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=ANY,
        )

    def test_missing_live_proof_builds_report_derived_proof_then_arms(self) -> None:
        proofs = SimpleNamespace(hashes={"fresh_quote_boundary": "a" * 64})
        self.service.verify_automatic_selector_prerequisites.side_effect = (
            ShadowStateError(
                "Selector arm proof artifact is unavailable: "
                "fresh_quote_boundary."
            ),
            (proofs, CHECKED_AT),
        )
        report_evidence = SimpleNamespace(candidate="CRWV")
        quote_result = {
            "proofStatus": "PASS",
            "checkedAt": CHECKED_AT.isoformat(),
            "requestedSymbols": ["CRWV", "SPY", "IWM"],
            "transmitting": False,
            "orderTransmission": "UNAVAILABLE",
        }
        source = object()

        with (
            patch(
                "momentum_hunter.shadow_arm_ceremony.load_proof_context",
                return_value=SimpleNamespace(),
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "verify_canonical_git_still_matches",
            ) as verify_git,
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "validate_static_artifact",
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "read_and_validate_candidate_report",
                return_value=report_evidence,
            ) as validate_report,
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "SchwabMarketDataQuoteSource",
                return_value=source,
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "build_regular_market_quote_proof",
                return_value=quote_result,
            ) as build_quote,
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "finalize_selector_proof_bundle",
            ) as finalize,
        ):
            result = complete_shadow_selector_arm(
                self.bundle,
                self.report,
                quote_proof_path=self.quote_proof,
                clock=lambda: CHECKED_AT,
                service=self.service,
            )

        self.assertEqual("ARMED", result.state)
        self.assertEqual("CRWV", result.candidate)
        self.assertTrue(self.quote_proof.exists())
        verify_git.assert_called_once_with(
            self.bundle,
            PROJECT_ROOT.resolve(),
            command_runner=run_command,
        )
        validate_report.assert_called_once()
        build_quote.assert_called_once_with(
            source,
            ("CRWV", "SPY", "IWM"),
            checked_at=CHECKED_AT,
        )
        finalize.assert_called_once()
        self.service.arm_automatic_selector.assert_called_once_with(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=ANY,
        )

    def test_failed_quote_retries_and_never_finalizes_or_arms(self) -> None:
        self.service.verify_automatic_selector_prerequisites.side_effect = (
            ShadowStateError(
                "Selector arm proof artifact is unavailable: "
                "fresh_quote_boundary."
            )
        )
        failures = [
            {
                "proofStatus": "FAIL",
                "checkedAt": CHECKED_AT.isoformat(),
                "requestedSymbols": ["CRWV", "SPY", "IWM"],
            }
            for _ in range(3)
        ]
        sleeps: list[float] = []

        with (
            patch(
                "momentum_hunter.shadow_arm_ceremony.load_proof_context",
                return_value=SimpleNamespace(),
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "verify_canonical_git_still_matches",
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "validate_static_artifact",
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "read_and_validate_candidate_report",
                return_value=SimpleNamespace(candidate="CRWV"),
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "build_regular_market_quote_proof",
                side_effect=failures,
            ) as build_quote,
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "finalize_selector_proof_bundle",
            ) as finalize,
        ):
            with self.assertRaisesRegex(
                ShadowArmCeremonyError,
                "did not pass",
            ):
                complete_shadow_selector_arm(
                    self.bundle,
                    self.report,
                    quote_proof_path=self.quote_proof,
                    quote_source=object(),
                    quote_attempts=3,
                    quote_retry_seconds=0.25,
                    clock=lambda: CHECKED_AT,
                    sleeper=sleeps.append,
                    service=self.service,
                )

        self.assertEqual(3, build_quote.call_count)
        self.assertEqual([0.25, 0.25], sleeps)
        self.assertTrue(self.quote_proof.exists())
        finalize.assert_not_called()
        self.service.arm_automatic_selector.assert_not_called()

    def test_existing_quote_output_stops_before_quote_request(self) -> None:
        self.service.verify_automatic_selector_prerequisites.side_effect = (
            ShadowStateError(
                "Selector arm proof artifact is unavailable: "
                "fresh_quote_boundary."
            )
        )
        self.quote_proof.write_text("{}", encoding="utf-8")

        with (
            patch(
                "momentum_hunter.shadow_arm_ceremony.load_proof_context",
                return_value=SimpleNamespace(),
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "verify_canonical_git_still_matches",
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "validate_static_artifact",
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "read_and_validate_candidate_report",
                return_value=SimpleNamespace(candidate="CRWV"),
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "build_regular_market_quote_proof",
            ) as build_quote,
        ):
            with self.assertRaisesRegex(
                ShadowArmCeremonyError,
                "already exists",
            ):
                complete_shadow_selector_arm(
                    self.bundle,
                    self.report,
                    quote_proof_path=self.quote_proof,
                    clock=lambda: CHECKED_AT,
                    service=self.service,
                )

        build_quote.assert_not_called()
        self.service.arm_automatic_selector.assert_not_called()

    def test_static_or_git_preflight_failure_stops_before_quote(self) -> None:
        self.service.verify_automatic_selector_prerequisites.side_effect = (
            ShadowStateError(
                "Selector arm proof artifact is unavailable: "
                "fresh_quote_boundary."
            )
        )

        with (
            patch(
                "momentum_hunter.shadow_arm_ceremony.load_proof_context",
                return_value=SimpleNamespace(),
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "verify_canonical_git_still_matches",
                side_effect=ValueError("canonical Git mismatch"),
            ),
            patch(
                "momentum_hunter.shadow_arm_ceremony."
                "build_regular_market_quote_proof",
            ) as build_quote,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "canonical Git mismatch",
            ):
                complete_shadow_selector_arm(
                    self.bundle,
                    self.report,
                    clock=lambda: CHECKED_AT,
                    service=self.service,
                )

        build_quote.assert_not_called()
        self.service.arm_automatic_selector.assert_not_called()

    def test_existing_invalid_live_artifact_stops_before_quote_request(self) -> None:
        (self.bundle / "fresh_quote_boundary.json").write_text(
            "{}",
            encoding="utf-8",
        )
        self.service.verify_automatic_selector_prerequisites.side_effect = (
            ShadowStateError("proof failed revalidation")
        )

        with patch(
            "momentum_hunter.shadow_arm_ceremony.build_regular_market_quote_proof"
        ) as build_quote:
            with self.assertRaisesRegex(
                ShadowStateError,
                "failed revalidation",
            ):
                complete_shadow_selector_arm(
                    self.bundle,
                    self.report,
                    clock=lambda: CHECKED_AT,
                    service=self.service,
                )

        build_quote.assert_not_called()
        self.service.arm_automatic_selector.assert_not_called()

    def test_offsetless_clock_fails_before_quote_or_arm(self) -> None:
        self.service.verify_automatic_selector_prerequisites.side_effect = (
            ShadowStateError(
                "Selector arm proof artifact is unavailable: "
                "fresh_quote_boundary."
            )
        )

        with self.assertRaisesRegex(
            ShadowArmCeremonyError,
            "UTC offset",
        ):
            complete_shadow_selector_arm(
                self.bundle,
                self.report,
                clock=lambda: datetime(2026, 7, 27, 9, 35),
                service=self.service,
            )

        self.service.arm_automatic_selector.assert_not_called()


if __name__ == "__main__":
    unittest.main()
