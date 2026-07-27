from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.schwab_market_data import (
    INJECTED_QUOTE_PROOF_ORIGIN,
    LIVE_SCHWAB_QUOTE_PROOF_ORIGIN,
    SCHWAB_QUOTE_SOURCE,
    build_regular_market_quote_proof,
)
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


HEAD = "a" * 40
ACTIVATED_AT = datetime(2026, 7, 26, 20, 0, tzinfo=timezone.utc)
PREPARED_AT = datetime(2026, 7, 27, 13, 58, tzinfo=timezone.utc)
QUOTED_AT = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)


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
    def __init__(self, observed_at: datetime) -> None:
        self.observed_at = observed_at

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


class ShadowProofBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo_root = self.root / "repo"
        self.repo_root.mkdir()
        self.state_path = self.root / "shadow-state.json"
        self.bundle = self.root / "selector-proof-bundle"
        self.quote_proof_path = self.root / "quote-proof.json"
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
        queue.parent.mkdir(parents=True)
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
        screenshot = (
            self.repo_root
            / "docs"
            / "argus-office"
            / "reports"
            / "releases"
            / "ARGUS-SHADOW-004-official-sample-active-proof.jpg"
        )
        screenshot.parent.mkdir(parents=True)
        screenshot.write_bytes(b"\xff\xd8" + (b"proof" * 2_100) + b"\xff\xd9")

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
        evidence_origin: str = LIVE_SCHWAB_QUOTE_PROOF_ORIGIN,
    ) -> dict[str, object]:
        proof = build_regular_market_quote_proof(
            ProofQuoteSource(observed_at or checked_at - timedelta(seconds=5)),
            symbols,
            checked_at=checked_at,
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

    def finalize(
        self,
        *,
        candidate: str = "CRWV",
        finalized_at: datetime | None = None,
        runner: FakeCommandRunner | None = None,
    ) -> dict[str, object]:
        return finalize_selector_proof_bundle(
            self.bundle,
            quote_proof_path=self.quote_proof_path,
            candidate=candidate,
            repo_root=self.repo_root,
            state_path=self.state_path,
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
        self.assertTrue(
            (self.bundle / "fresh_quote_boundary.json").exists()
        )
        self.assertFalse(result["stateMutated"])
        self.assertFalse(result["transmitting"])
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
            self.finalize(candidate="CRWV")

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
