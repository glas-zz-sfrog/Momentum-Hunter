from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.schwab_market_data import (
    INJECTED_QUOTE_PROOF_ORIGIN,
    LIVE_SCHWAB_QUOTE_PROOF_ORIGIN,
    SCHWAB_QUOTE_SOURCE,
    SchwabQuoteEvidenceBatch,
    build_regular_market_quote_proof,
)
from momentum_hunter.shadow_opening import build_https_clock_skew_proof
from momentum_hunter.shadow_proof_bundle import (
    STATIC_PROOF_NAMES,
    CommandResult,
    SelectorProofBundleError,
    finalize_selector_proof_bundle,
    prepare_static_selector_proof_bundle,
)
from momentum_hunter.shadow_trading import (
    OFFICIAL_SHADOW_SAMPLE_VERSION,
    SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
    ShadowStateStore,
    ShadowTradingService,
)
from momentum_hunter.trade_planning import REPORT_SCHEMA_VERSION


HEAD = "a" * 40
ACTIVATED_AT = datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc)
PREPARED_AT = datetime(2026, 7, 27, 13, 58, tzinfo=timezone.utc)
QUOTED_AT = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)
CAPTURED_AT = QUOTED_AT - timedelta(seconds=20)
REPORTED_AT = QUOTED_AT - timedelta(seconds=10)


class FakeCommandRunner:
    def __init__(
        self,
        *,
        dirty: bool = False,
        failed_gate: str = "",
        branch: str = "master",
        head: str = HEAD,
    ) -> None:
        self.dirty = dirty
        self.failed_gate = failed_gate
        self.branch = branch
        self.head = head
        self.commands: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: tuple[str, ...] | list[str],
        cwd: Path,
        timeout_seconds: float,
    ) -> CommandResult:
        del cwd, timeout_seconds
        normalized = tuple(str(item) for item in command)
        self.commands.append(normalized)
        if normalized[:3] == ("git", "branch", "--show-current"):
            return self.result(normalized, stdout=f"{self.branch}\n")
        if normalized[:3] == ("git", "status", "--porcelain"):
            stdout = " M unexpected.py\n" if self.dirty else ""
            return self.result(normalized, stdout=stdout)
        if normalized[:3] == ("git", "rev-parse", "HEAD"):
            return self.result(normalized, stdout=f"{self.head}\n")
        if normalized[:3] == ("git", "rev-parse", "origin/master"):
            return self.result(normalized, stdout=f"{self.head}\n")
        if normalized[:3] == ("git", "merge-base", "--is-ancestor"):
            return self.result(normalized)
        if "unittest" in normalized:
            if self.failed_gate and any(
                self.failed_gate in item for item in normalized
            ):
                return self.result(
                    normalized,
                    returncode=1,
                    stderr="FAILED (failures=1)\n",
                )
            test_count = max(1, len(normalized) - normalized.index("-q") - 1)
            return self.result(
                normalized,
                stderr=f"Ran {test_count} tests in 0.010s\n\nOK\n",
            )
        raise AssertionError(f"Unexpected command: {normalized}")

    @staticmethod
    def result(
        command: tuple[str, ...],
        *,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
    ) -> CommandResult:
        return CommandResult(command, returncode, stdout, stderr)


class ProofQuoteSource:
    def __init__(
        self,
        observed_at: datetime,
        *,
        trusted_remote_at: datetime | None = None,
    ) -> None:
        self.observed_at = observed_at
        self.trusted_remote_at = trusted_remote_at

    def quotes(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime | None = None,
    ) -> dict[str, dict[str, object]]:
        del decision_at
        return {
            symbol: proof_quote(symbol, self.observed_at)
            for symbol in symbols
        }

    def quotes_with_clock(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime | None = None,
    ) -> SchwabQuoteEvidenceBatch:
        assert decision_at is not None
        return SchwabQuoteEvidenceBatch(
            quotes=self.quotes(symbols, decision_at=decision_at),
            clock_skew_proof=build_https_clock_skew_proof(
                request_started_at=decision_at,
                response_received_at=decision_at,
                remote_date_header=format_datetime(
                    self.trusted_remote_at or decision_at
                ),
                source_identity="synthetic-test-https-date",
            ),
        )


class ShadowProofBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo_root = self.root / "repo"
        self.repo_root.mkdir()
        self.state_path = self.root / "shadow-state.json"
        self.bundle = self.root / "selector-proof-bundle"
        self.quote_proof_path = self.root / "quote-proof.json"
        self.data_dir = self.root / "data"
        self.reports_dir = self.data_dir / "reports"
        self.captures_dir = self.data_dir / "captures"
        self.reports_dir.mkdir(parents=True)
        self.captures_dir.mkdir(parents=True)
        self.report_path, self.capture_path = self.write_candidate_report()
        self.task_definition_path = self.root / "shadow-task.xml"
        self.task_definition_path.write_text(
            "<Task><Action>synthetic</Action></Task>\n",
            encoding="utf-8",
        )
        self.write_visual_evidence()
        service = ShadowTradingService(store=ShadowStateStore(self.state_path))
        with patch(
            "momentum_hunter.shadow_trading.now_central",
            return_value=ACTIVATED_AT,
        ):
            service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
                sample_version=OFFICIAL_SHADOW_SAMPLE_VERSION,
            )
        self.activation_path = service.activation_store.path
        self.activation_hash = file_hash(self.activation_path)
        self.protected_paths = (
            service.store.path,
            service.selector_arm_store.path,
            service.selection_policy_store.path,
            service.decision_cycle_store.path,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_visual_evidence(self) -> None:
        queue = (
            self.repo_root
            / "docs"
            / "argus-office"
            / "VERIFICATION_QUEUE.md"
        )
        queue.parent.mkdir(parents=True, exist_ok=True)
        queue.write_text(
            "\n".join(
                (
                    "ARGUS-SHADOW-017 live position marking",
                    "`MANUAL_PASS`; Steven passed all seven checks on 2026-07-29",
                    "Steven result: `MANUAL_PASS` on 2026-07-29",
                    "This acceptance does not arm the selector",
                )
            ),
            encoding="utf-8",
        )
        screenshot = (
            self.repo_root
            / "docs"
            / "argus-office"
            / "reports"
            / "releases"
            / "ARGUS-SHADOW-017-synthetic-live-marking-ui-proof.png"
        )
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        screenshot.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + (b"proof" * 2_100)
            + b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        self.visual_proof_path = screenshot

    def prepare(self, runner: FakeCommandRunner | None = None) -> dict[str, object]:
        return prepare_static_selector_proof_bundle(
            self.bundle,
            repo_root=self.repo_root,
            state_path=self.state_path,
            verified_at=PREPARED_AT,
            command_runner=runner or FakeCommandRunner(),
        )

    def write_quote_proof(
        self,
        *,
        symbols: tuple[str, ...] = ("CRWV", "SPY", "IWM"),
        checked_at: datetime = QUOTED_AT,
        observed_at: datetime | None = None,
        trusted_remote_at: datetime | None = None,
        evidence_origin: str = LIVE_SCHWAB_QUOTE_PROOF_ORIGIN,
    ) -> dict[str, object]:
        proof = build_regular_market_quote_proof(
            ProofQuoteSource(
                observed_at or checked_at - timedelta(seconds=5),
                trusted_remote_at=trusted_remote_at,
            ),
            symbols,
            checked_at=checked_at,
            require_clock_proof=True,
        )
        proof["evidenceOrigin"] = evidence_origin
        proof["productionSource"] = (
            evidence_origin == LIVE_SCHWAB_QUOTE_PROOF_ORIGIN
        )
        self.quote_proof_path.write_text(
            json.dumps(proof, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return proof

    def write_candidate_report(
        self,
        *,
        symbol: str = "CRWV",
        session: str = "manual",
        captured_at: datetime = CAPTURED_AT,
        reported_at: datetime = REPORTED_AT,
    ) -> tuple[Path, Path]:
        capture_path = (
            self.captures_dir
            / captured_at.date().isoformat()
            / f"{session}.json"
        )
        capture_path.parent.mkdir(parents=True, exist_ok=True)
        capture = {
            "capture_time": captured_at.isoformat(),
            "session": session,
            "provider": "finviz",
            "scanner": {"name": "Institutional Momentum"},
            "candidates": [{"symbol": symbol}],
        }
        capture_path.write_text(
            json.dumps(capture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report_path = (
            self.reports_dir
            / (
                f"trade-plan-briefing-{captured_at.date().isoformat()}"
                f"-{session}.json"
            )
        )
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "metadata": {
                "generated_at": reported_at.isoformat(),
                "source_capture_path": str(capture_path.resolve()),
                "source_capture_time": captured_at.isoformat(),
                "source_session": session,
                "source_provider": "finviz",
                "source_scanner": "Institutional Momentum",
            },
            "candidates": [
                {
                    "rank": 1,
                    "symbol": symbol,
                    "candidate_id": f"{symbol}-candidate",
                    "scoring": {"composite_score": 90.0},
                }
            ],
        }
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report_path, capture_path

    def finalize(
        self,
        *,
        report_path: Path | None = None,
        finalized_at: datetime | None = None,
        runner: FakeCommandRunner | None = None,
    ) -> dict[str, object]:
        return finalize_selector_proof_bundle(
            self.bundle,
            quote_proof_path=self.quote_proof_path,
            report_path=report_path or self.report_path,
            repo_root=self.repo_root,
            state_path=self.state_path,
            reports_dir=self.reports_dir,
            captures_dir=self.captures_dir,
            task_definition_path=self.task_definition_path,
            finalized_at=finalized_at or QUOTED_AT + timedelta(seconds=5),
            command_runner=runner or FakeCommandRunner(),
        )

    def assert_production_state_untouched(self) -> None:
        self.assertEqual(self.activation_hash, file_hash(self.activation_path))
        self.assertTrue(all(not path.exists() for path in self.protected_paths))

    def test_static_preparation_creates_eleven_atomic_proofs_only(self) -> None:
        result = self.prepare()

        self.assertEqual("STATIC_READY", result["bundleState"])
        self.assertEqual(len(STATIC_PROOF_NAMES), result["proofArtifactCount"])
        self.assertEqual(
            {"fresh_quote_boundary"},
            set(result["missingProofArtifacts"]),
        )
        self.assertEqual(
            set(STATIC_PROOF_NAMES),
            {path.stem for path in self.bundle.glob("*.json")},
        )
        for proof_name in STATIC_PROOF_NAMES:
            proof = json.loads(
                (self.bundle / f"{proof_name}.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual("PASS", proof["status"])
            self.assertEqual(proof_name, proof["proof_name"])
        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assertFalse(result["stateMutated"])
        self.assert_production_state_untouched()

    def test_static_preparation_requires_current_visual_acceptance_png(
        self,
    ) -> None:
        queue = (
            self.repo_root
            / "docs"
            / "argus-office"
            / "VERIFICATION_QUEUE.md"
        )
        queue.write_text(
            "\n".join(
                (
                    "ARGUS-SHADOW-004 Official Sample Activation",
                    "Status: `COMPLETE`; `AUTOMATED_PASS`; `MANUAL_PASS`",
                    "Steven completed and accepted these checks on 2026-07-26",
                )
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            SelectorProofBundleError,
            "SHADOW-017 manual acceptance",
        ):
            self.prepare()
        self.assertFalse(self.bundle.exists())

        self.write_visual_evidence()
        self.visual_proof_path.write_bytes(
            b"\xff\xd8" + (b"old-proof" * 2_000) + b"\xff\xd9"
        )
        with self.assertRaisesRegex(
            SelectorProofBundleError,
            "valid retained PNG",
        ):
            self.prepare()

        self.assertFalse(self.bundle.exists())
        self.assert_production_state_untouched()

    def test_dirty_git_or_failed_gate_leaves_no_partial_bundle(self) -> None:
        cases = (
            FakeCommandRunner(dirty=True),
            FakeCommandRunner(failed_gate="test_one_active_position"),
        )
        for runner in cases:
            with self.subTest(commands=len(runner.commands)):
                with self.assertRaises(SelectorProofBundleError):
                    self.prepare(runner)
                self.assertFalse(self.bundle.exists())
                temporary_siblings = tuple(
                    self.bundle.parent.glob(f".{self.bundle.name}.*.tmp")
                )
                self.assertEqual((), temporary_siblings)
                self.assert_production_state_untouched()

    def test_existing_bundle_is_write_once(self) -> None:
        self.prepare()

        with self.assertRaises(SelectorProofBundleError):
            self.prepare()

        self.assert_production_state_untouched()

    def test_live_quote_finalizes_all_proofs_without_arming(self) -> None:
        self.prepare()
        proof = self.write_quote_proof()

        result = self.finalize()

        self.assertEqual("PASS", proof["proofStatus"])
        self.assertEqual("READY_TO_ARM", result["bundleState"])
        self.assertEqual(12, result["proofArtifactCount"])
        self.assertEqual("CRWV", result["candidate"])
        self.assertEqual(
            file_hash(self.report_path),
            result["sourceReportSha256"],
        )
        self.assertEqual(
            file_hash(self.capture_path),
            result["sourceCaptureSha256"],
        )
        self.assertTrue(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        fresh_proof = json.loads(
            (self.bundle / "fresh_quote_boundary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(6, len(fresh_proof["evidence"]))
        self.assertTrue(
            (
                self.bundle
                / "evidence"
                / "fresh_quote_report_binding.json"
            ).exists()
        )
        self.assertFalse(result["stateMutated"])
        self.assertFalse(result["transmitting"])
        self.assert_production_state_untouched()

    def test_clock_normalized_live_quote_finalizes_when_local_clock_lags(
        self,
    ) -> None:
        self.prepare()
        proof = self.write_quote_proof(
            observed_at=QUOTED_AT + timedelta(seconds=1.5),
            trusted_remote_at=QUOTED_AT + timedelta(seconds=2),
        )

        result = self.finalize(
            finalized_at=QUOTED_AT + timedelta(seconds=0.5)
        )

        self.assertEqual("PASS", proof["proofStatus"])
        self.assertEqual(
            "VALIDATED_HTTPS_DATE_BOUND",
            proof["quoteTimeBasis"]["basis"],
        )
        self.assertEqual("READY_TO_ARM", result["bundleState"])
        self.assert_production_state_untouched()

    def test_tampered_clock_basis_is_rejected(self) -> None:
        self.prepare()
        proof = self.write_quote_proof()
        proof["quoteTimeBasis"]["latestPlausibleTrustedAt"] = (
            QUOTED_AT + timedelta(seconds=10)
        ).isoformat()
        self.quote_proof_path.write_text(
            json.dumps(proof, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(SelectorProofBundleError):
            self.finalize()

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assert_production_state_untouched()

    def test_tampered_provider_timestamp_beyond_clock_bound_is_rejected(
        self,
    ) -> None:
        self.prepare()
        proof = self.write_quote_proof()
        proof["quotes"][0]["providerAskTimestamp"] = (
            QUOTED_AT + timedelta(seconds=10)
        ).isoformat()
        self.quote_proof_path.write_text(
            json.dumps(proof, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with self.assertRaises(SelectorProofBundleError):
            self.finalize()

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assert_production_state_untouched()

    def test_injected_quote_proof_is_rejected(self) -> None:
        self.prepare()
        self.write_quote_proof(
            evidence_origin=INJECTED_QUOTE_PROOF_ORIGIN
        )

        with self.assertRaises(SelectorProofBundleError):
            self.finalize()

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assert_production_state_untouched()

    def test_stale_quote_proof_is_rejected(self) -> None:
        self.prepare()
        self.write_quote_proof()

        with self.assertRaises(SelectorProofBundleError):
            self.finalize(finalized_at=QUOTED_AT + timedelta(seconds=31))

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assert_production_state_untouched()

    def test_mismatched_candidate_and_symbol_set_are_rejected(self) -> None:
        self.prepare()
        self.write_quote_proof(symbols=("NVDA", "SPY", "IWM"))

        with self.assertRaises(SelectorProofBundleError):
            self.finalize()

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assert_production_state_untouched()

    def test_highest_canonical_rank_is_derived_from_report(self) -> None:
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        capture = json.loads(self.capture_path.read_text(encoding="utf-8"))
        report["candidates"] = [
            {
                "rank": 2,
                "symbol": "CRWV",
                "candidate_id": "CRWV-candidate",
                "scoring": {"composite_score": 95.0},
            },
            {
                "rank": 1,
                "symbol": "NVDA",
                "candidate_id": "NVDA-candidate",
                "scoring": {"composite_score": 80.0},
            },
        ]
        capture["candidates"] = [
            {"symbol": "CRWV"},
            {"symbol": "NVDA"},
        ]
        self.report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.capture_path.write_text(
            json.dumps(capture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.prepare()
        self.write_quote_proof(symbols=("NVDA", "SPY", "IWM"))

        result = self.finalize()

        self.assertEqual("NVDA", result["candidate"])
        self.assert_production_state_untouched()

    def test_noncanonical_or_not_latest_report_is_rejected(self) -> None:
        self.prepare()
        self.write_quote_proof()
        copied_report = self.root / self.report_path.name
        copied_report.write_bytes(self.report_path.read_bytes())

        with self.assertRaises(SelectorProofBundleError):
            self.finalize(report_path=copied_report)

        later_report, _ = self.write_candidate_report(
            symbol="NVDA",
            session="morning",
            captured_at=CAPTURED_AT + timedelta(seconds=1),
            reported_at=REPORTED_AT + timedelta(seconds=1),
        )
        self.assertNotEqual(self.report_path, later_report)
        with self.assertRaises(SelectorProofBundleError):
            self.finalize(report_path=self.report_path)
        self.assert_production_state_untouched()

    def test_stale_report_is_rejected_even_with_fresh_quotes(self) -> None:
        stale_report, _ = self.write_candidate_report(
            session="morning",
            captured_at=QUOTED_AT - timedelta(minutes=2),
            reported_at=QUOTED_AT - timedelta(minutes=2),
        )
        self.prepare()
        self.write_quote_proof()

        with self.assertRaises(SelectorProofBundleError):
            self.finalize(report_path=stale_report)

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assert_production_state_untouched()

    def test_report_and_source_capture_mismatch_is_rejected(self) -> None:
        capture = json.loads(self.capture_path.read_text(encoding="utf-8"))
        capture["candidates"] = [{"symbol": "NVDA"}]
        self.capture_path.write_text(
            json.dumps(capture, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.prepare()
        self.write_quote_proof()

        with self.assertRaises(SelectorProofBundleError):
            self.finalize()

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assert_production_state_untouched()

    def test_tampered_static_evidence_is_rejected(self) -> None:
        self.prepare()
        self.write_quote_proof()
        evidence = self.bundle / "evidence" / "portfolio_policy.json"
        evidence.write_text("tampered\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            self.finalize()

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assert_production_state_untouched()

    def test_failed_full_verification_removes_fresh_artifacts(self) -> None:
        self.prepare()
        self.write_quote_proof()

        with (
            patch.object(
                ShadowTradingService,
                "verify_automatic_selector_prerequisites",
                side_effect=RuntimeError("synthetic verification failure"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.finalize()

        self.assertFalse(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assertFalse(
            (self.bundle / "evidence" / "fresh_quote_boundary.json").exists()
        )
        self.assertFalse(
            (
                self.bundle
                / "evidence"
                / "fresh_quote_report_binding.json"
            ).exists()
        )
        self.assertFalse(
            (
                self.bundle
                / "evidence"
                / "fresh_quote_source_report.json"
            ).exists()
        )
        self.assertFalse(
            (
                self.bundle
                / "evidence"
                / "fresh_quote_source_capture.json"
            ).exists()
        )
        self.assert_production_state_untouched()


def proof_quote(symbol: str, observed_at: datetime) -> dict[str, object]:
    timestamp = observed_at.isoformat()
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "provider_quote_timestamp": timestamp,
        "provider_bid_timestamp": timestamp,
        "provider_ask_timestamp": timestamp,
        "bid": 100.0,
        "ask": 100.05,
        "last": 100.02,
        "volume": 10_000,
        "session": "regular",
        "trading_state": "tradable",
        "realtime": True,
        "security_status": "Normal",
        "source": SCHWAB_QUOTE_SOURCE,
    }


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
