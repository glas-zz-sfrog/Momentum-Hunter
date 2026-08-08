from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import momentum_hunter.shadow_market_validity as shadow_market_validity_module
from momentum_hunter.shadow_market_validity import (
    SHADOW_SELECTOR_ARM_CONFIRMATION,
    DecisionCycleStore,
    PersistedObservationQuoteSource,
    canonical_json,
    classify_warnings,
    decision_cycle_summary,
    entry_window_findings,
    forced_exit_deadline,
    hash_prerequisite_proof_artifacts,
    is_nyse_early_close,
    portfolio_findings,
    runtime_build_hash,
    shadow_constitution_hash,
    validate_opening_configuration_identity,
    validate_arm_record,
)
from momentum_hunter.shadow_selection import (
    SELECTION_ALREADY_PROCESSED,
    SELECTION_CONFIGURATION_MISMATCH,
    SELECTION_CLOCK_SKEW_BLOCKED,
    SELECTION_CONSTITUTION_NOT_ARMED,
    SELECTION_DUPLICATE_CAPTURE,
    SELECTION_INVALID_REPORT,
    SELECTION_NO_ELIGIBLE_CANDIDATE,
    SELECTION_STARTED,
    AutomaticShadowSelector,
)
from momentum_hunter.shadow_opening import build_https_clock_skew_proof
from momentum_hunter.shadow_trading import (
    SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
    ShadowStateError,
    ShadowStateStore,
    ShadowQuote,
    ShadowTradingService,
    audit_shadow_trade,
)
from momentum_hunter.workstation_shadow import (
    ShadowWorkspacePaths,
    ShadowWorkspaceService,
)
from tests.test_shadow_trading import report_payload
from tests.shadow_proof_fixtures import write_synthetic_proof_artifacts


class DictQuoteSource:
    def __init__(self, quotes: dict[str, dict]) -> None:
        self.quotes = quotes
        self.calls: list[str] = []

    def quote(self, symbol: str, *, decision_at: datetime) -> dict | None:
        self.calls.append(symbol)
        value = self.quotes.get(symbol)
        return copy.deepcopy(value) if value is not None else None

    def quotes_with_clock(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            quotes={
                symbol: quote
                for symbol in symbols
                if (
                    quote := self.quote(
                        symbol,
                        decision_at=decision_at,
                    )
                )
                is not None
            },
            clock_skew_proof=synthetic_clock_proof(decision_at),
        )


class BatchQuoteSource:
    def __init__(self, quotes: dict[str, dict]) -> None:
        self.values = quotes
        self.calls: list[tuple[tuple[str, ...], datetime]] = []

    def quotes(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime,
    ) -> dict[str, dict]:
        self.calls.append((tuple(symbols), decision_at))
        return {
            symbol: copy.deepcopy(self.values[symbol])
            for symbol in symbols
            if symbol in self.values
        }

    def quotes_with_clock(
        self,
        symbols: tuple[str, ...],
        *,
        decision_at: datetime,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            quotes=self.quotes(symbols, decision_at=decision_at),
            clock_skew_proof=synthetic_clock_proof(decision_at),
        )


def synthetic_clock_proof(checked_at: datetime) -> dict[str, object]:
    return build_https_clock_skew_proof(
        request_started_at=checked_at,
        response_received_at=checked_at,
        remote_date_header=format_datetime(checked_at),
        source_identity="synthetic-test-https-date",
    )


class ShadowMarketValiditySelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.reports_dir = self.root / "reports"
        self.reports_dir.mkdir()
        self.report_path = (
            self.reports_dir / "trade-plan-briefing-2026-07-23-morning.json"
        )
        self.state_path = self.root / "shadow-state.json"
        self.service = ShadowTradingService(
            store=ShadowStateStore(self.state_path),
        )
        self.decision_at = at("2026-07-23T10:00:00-05:00")
        self.quote_source = DictQuoteSource(
            {
                "TEST": quote_payload("TEST"),
                "SPY": quote_payload("SPY", bid=625.00, ask=625.02),
                "IWM": quote_payload("IWM", bid=225.00, ask=225.02),
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def activate(self, *, arm: bool = True) -> None:
        with patch(
            "momentum_hunter.shadow_trading.now_central",
            return_value=at("2026-07-23T09:57:00-05:00"),
        ):
            self.service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
            )
        if arm:
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=self.proof_artifacts(self.id()),
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )

    def proof_artifacts(
        self,
        seed: str,
        *,
        verified_at: datetime | None = None,
    ) -> dict[str, Path]:
        return write_synthetic_proof_artifacts(
            self.root,
            seed,
            sample_version=self.service.sample_definition.sample_version,
            activation_path=self.service.activation_store.path,
            verified_at=verified_at
            or at("2026-07-23T09:57:20-05:00"),
        )

    def write_report(
        self,
        payload: dict | None = None,
        *,
        path: Path | None = None,
    ) -> Path:
        target = path or self.report_path
        target.write_text(
            json.dumps(payload or report_payload()),
            encoding="utf-8",
        )
        return target

    def selector(self) -> AutomaticShadowSelector:
        return AutomaticShadowSelector(
            self.service,
            quote_source=self.quote_source,
        )

    def test_write_once_arm_record_replaces_source_code_switch(self) -> None:
        self.activate(arm=False)
        proof_paths = self.proof_artifacts("arm")
        arm = self.service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=proof_paths,
            armed_at=at("2026-07-23T09:57:30-05:00"),
        )
        repeated = self.service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=proof_paths,
            armed_at=at("2026-07-23T09:57:30-05:00"),
        )

        self.assertEqual(arm, repeated)
        self.assertEqual(shadow_constitution_hash(), arm.constitution_hash)
        self.assertTrue(self.service.selector_is_armed())
        self.assertFalse(self.state_path.exists())
        with self.assertRaisesRegex((ValueError, ShadowStateError), "immutable"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=self.proof_artifacts("different"),
                armed_at=at("2026-07-23T09:57:31-05:00"),
            )

    def test_arm_hashes_actual_artifacts_and_tamper_changes_identity(self) -> None:
        self.activate(arm=False)
        proof_paths = self.proof_artifacts("artifact-hashes")
        armed_at = at("2026-07-23T09:57:30-05:00")
        expected = hash_prerequisite_proof_artifacts(
            proof_paths,
            sample_version=self.service.sample_definition.sample_version,
            activation_hash=hashlib.sha256(
                self.service.activation_store.path.read_bytes()
            ).hexdigest(),
            activated_at=at("2026-07-23T09:57:00-05:00"),
            constitution_hash=shadow_constitution_hash(),
            build_hash=runtime_build_hash(),
            armed_at=armed_at,
        )

        arm = self.service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=proof_paths,
            armed_at=armed_at,
        )

        self.assertEqual(expected.hashes, arm.prerequisite_proofs)
        self.assertEqual(expected.paths, arm.prerequisite_proof_paths)
        changed_path = proof_paths["ranking_and_tie_breaks"]
        changed_payload = json.loads(changed_path.read_text(encoding="utf-8"))
        changed_payload["summary"] = "Changed after the immutable arm."
        changed_path.write_text(
            json.dumps(changed_payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ShadowStateError, "immutable"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=proof_paths,
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )
        with self.assertRaisesRegex(
            ShadowStateError,
            "no longer match",
        ):
            self.service.selector_arm_record()
        self.assertEqual(arm, self.service.selector_arm_store.load())

    def test_invalid_artifacts_fail_before_policy_or_arm_state(self) -> None:
        self.activate(arm=False)
        valid_paths = self.proof_artifacts("invalid-artifacts")
        missing_paths = dict(valid_paths)
        missing_paths["visual_acceptance"] = self.root / "missing-proof.json"
        with self.assertRaisesRegex(ShadowStateError, "unavailable"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=missing_paths,
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )

        empty_path = self.root / "empty-proof.json"
        empty_path.write_bytes(b"")
        empty_paths = dict(valid_paths)
        empty_paths["visual_acceptance"] = empty_path
        with self.assertRaisesRegex(ShadowStateError, "empty"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=empty_paths,
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )

        duplicate_paths = dict(valid_paths)
        duplicate_paths["visual_acceptance"] = duplicate_paths[
            "ranking_and_tie_breaks"
        ]
        with self.assertRaisesRegex(ShadowStateError, "distinct"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=duplicate_paths,
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )

        oversized_path = self.root / "oversized-proof.bin"
        oversized_path.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
        oversized_paths = dict(valid_paths)
        oversized_paths["visual_acceptance"] = oversized_path
        with self.assertRaisesRegex(ShadowStateError, "too large"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=oversized_paths,
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )

        failed_status_paths = self.proof_artifacts("failed-status")
        failed_status_path = failed_status_paths["visual_acceptance"]
        failed_status = json.loads(
            failed_status_path.read_text(encoding="utf-8")
        )
        failed_status["status"] = "FAIL"
        failed_status_path.write_text(
            json.dumps(failed_status, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ShadowStateError, "context"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=failed_status_paths,
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )

        mismatched_evidence_paths = self.proof_artifacts(
            "mismatched-evidence"
        )
        evidence_proof = json.loads(
            mismatched_evidence_paths["visual_acceptance"].read_text(
                encoding="utf-8"
            )
        )
        evidence_path = (
            mismatched_evidence_paths["visual_acceptance"].parent
            / evidence_proof["evidence"][0]["path"]
        )
        evidence_path.write_text("tampered evidence\n", encoding="utf-8")
        with self.assertRaisesRegex(ShadowStateError, "hash does not match"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=mismatched_evidence_paths,
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )

        self.assertFalse(self.service.selector_arm_store.path.exists())
        self.assertFalse(self.service.selection_policy_store.path.exists())
        self.assertFalse(self.state_path.exists())

    def test_arm_record_rejects_nonhex_artifact_digest(self) -> None:
        self.activate(arm=False)
        arm = self.service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=self.proof_artifacts("nonhex-proof"),
            armed_at=at("2026-07-23T09:57:30-05:00"),
        )
        malformed = replace(
            arm,
            prerequisite_proofs={
                **arm.prerequisite_proofs,
                "visual_acceptance": "PASS:" + "z" * 64,
            },
        )

        with self.assertRaisesRegex(ValueError, "visual_acceptance"):
            validate_arm_record(malformed)

    def test_armed_selector_fails_closed_when_evidence_is_deleted(self) -> None:
        self.activate(arm=False)
        proof_paths = self.proof_artifacts("deleted-evidence")
        self.service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=proof_paths,
            armed_at=at("2026-07-23T09:57:30-05:00"),
        )
        visual_proof = json.loads(
            proof_paths["visual_acceptance"].read_text(encoding="utf-8")
        )
        evidence_path = (
            proof_paths["visual_acceptance"].parent
            / visual_proof["evidence"][0]["path"]
        )
        evidence_path.unlink()

        with self.assertRaisesRegex(
            ShadowStateError,
            "failed revalidation",
        ):
            self.service.selector_is_armed()

    def test_runtime_build_hash_includes_quote_and_capture_cadence_boundary(self) -> None:
        root = Path(shadow_market_validity_module.__file__).resolve().parent
        project_root = root.parent
        expected_paths = (
            root / "engine_host.py",
            root / "engine_host_client.py",
            root / "models.py",
            root / "scheduling.py",
            root / "schwab_market_data.py",
            root / "shadow_arm_ceremony.py",
            root / "shadow_market_validity.py",
            root / "shadow_opening.py",
            root / "shadow_selection.py",
            root / "shadow_trading.py",
            root / "storage.py",
            root / "workstation_shadow.py",
            project_root / "tools" / "capture_job.py",
            project_root / "tools" / "install_capture_tasks.ps1",
            project_root / "tools" / "run_capture_job.ps1",
        )

        self.assertEqual(
            runtime_build_hash(expected_paths),
            runtime_build_hash(),
        )

    def test_incomplete_proofs_cannot_arm(self) -> None:
        self.activate(arm=False)
        artifacts = self.proof_artifacts("incomplete")
        with self.assertRaisesRegex((ValueError, ShadowStateError), "proof"):
            self.service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths={
                    "ranking_and_tie_breaks": artifacts[
                        "ranking_and_tie_breaks"
                    ]
                },
                armed_at=at("2026-07-23T09:57:30-05:00"),
            )
        self.assertFalse(self.service.selector_arm_store.path.exists())
        self.assertFalse(self.service.selection_policy_store.path.exists())
        self.assertFalse(self.state_path.exists())

    def test_unarmed_activation_fails_closed_without_policy_cycle_or_trade(self) -> None:
        self.activate(arm=False)
        self.write_report()
        before = self.report_path.read_bytes()

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_CONSTITUTION_NOT_ARMED, result.status)
        self.assertEqual(before, self.report_path.read_bytes())
        self.assertFalse(self.service.selection_policy_store.path.exists())
        self.assertFalse(self.service.decision_cycle_store.path.exists())
        self.assertFalse(self.state_path.exists())

    def test_provider_and_scanner_mismatch_block_before_cycle_or_trade(
        self,
    ) -> None:
        for field, value in (
            ("source_provider", "wrong-provider"),
            ("source_scanner", "Wrong Scanner"),
        ):
            with self.subTest(field=field):
                self.tearDown()
                self.setUp()
                self.activate()
                payload = report_payload()
                payload["metadata"][field] = value
                self.write_report(payload)

                result = self.selector().select(
                    self.report_path,
                    decision_at=self.decision_at,
                )

                self.assertEqual(
                    SELECTION_CONFIGURATION_MISMATCH,
                    result.status,
                )
                self.assertFalse(
                    self.service.decision_cycle_store.path.exists()
                )
                self.assertFalse(self.state_path.exists())

    def test_missing_decision_clock_blocks_before_cycle_or_trade(self) -> None:
        self.activate()
        self.write_report()
        source = BatchQuoteSource(self.quote_source.quotes)
        source.quotes_with_clock = lambda *_args, **_kwargs: SimpleNamespace(
            quotes=source.values,
            clock_skew_proof={},
        )

        result = AutomaticShadowSelector(
            self.service,
            quote_source=source,
        ).select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_CLOCK_SKEW_BLOCKED, result.status)
        self.assertFalse(self.service.decision_cycle_store.path.exists())
        self.assertFalse(self.state_path.exists())

    def test_quote_request_uses_trusted_post_request_clock_bounds(self) -> None:
        self.activate()
        self.write_report()
        completed_at = self.decision_at + timedelta(seconds=2)
        trusted_remote = completed_at + timedelta(seconds=1)
        source = BatchQuoteSource(
            {
                "TEST": quote_payload(
                    "TEST",
                    timestamp=(
                        self.decision_at + timedelta(seconds=1)
                    ).isoformat(),
                ),
                "SPY": quote_payload(
                    "SPY",
                    timestamp=(
                        self.decision_at + timedelta(seconds=1)
                    ).isoformat(),
                    bid=625.00,
                    ask=625.02,
                ),
                "IWM": quote_payload(
                    "IWM",
                    timestamp=(
                        self.decision_at + timedelta(seconds=1)
                    ).isoformat(),
                    bid=225.00,
                    ask=225.02,
                ),
            }
        )
        source.quotes_with_clock = lambda *_args, **_kwargs: SimpleNamespace(
            quotes=copy.deepcopy(source.values),
            clock_skew_proof=build_https_clock_skew_proof(
                request_started_at=self.decision_at,
                response_received_at=completed_at,
                remote_date_header=format_datetime(trusted_remote),
                source_identity="synthetic-test-https-date",
            ),
        )

        result = AutomaticShadowSelector(
            self.service,
            quote_source=source,
        ).select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertNotEqual(SELECTION_CLOCK_SKEW_BLOCKED, result.status)

    def test_quote_clock_completion_outside_request_bound_fails_closed(
        self,
    ) -> None:
        self.activate()
        self.write_report()
        completed_at = self.decision_at + timedelta(seconds=31)
        source = BatchQuoteSource(self.quote_source.quotes)
        source.quotes_with_clock = lambda *_args, **_kwargs: SimpleNamespace(
            quotes=copy.deepcopy(source.values),
            clock_skew_proof=synthetic_clock_proof(completed_at),
        )

        result = AutomaticShadowSelector(
            self.service,
            quote_source=source,
        ).select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_CLOCK_SKEW_BLOCKED, result.status)
        self.assertIn("bounded quote-request interval", result.reason)
        self.assertFalse(self.service.decision_cycle_store.path.exists())
        self.assertFalse(self.state_path.exists())

    def test_frozen_policy_and_build_hash_mismatch_fail_closed(self) -> None:
        self.activate()
        arm = self.service.selector_arm_record()
        assert arm is not None
        cases = (
            (
                "runtimeBuildHash",
                "b" * 64,
                {"expected_build_hash": arm.build_hash},
                "runtime build hash does not match",
            ),
            (
                "selectionPolicyFingerprint",
                "c" * 64,
                {
                    "expected_selection_policy_fingerprint": (
                        arm.selection_policy_fingerprint
                    )
                },
                "selection policy hash does not match",
            ),
        )
        for field, value, expected, message in cases:
            with self.subTest(field=field):
                identity = dict(arm.opening_configuration)
                identity[field] = value
                unsigned = dict(identity)
                unsigned.pop("configurationIdentitySha256", None)
                identity["configurationIdentitySha256"] = hashlib.sha256(
                    canonical_json(unsigned).encode("utf-8")
                ).hexdigest()

                with self.assertRaisesRegex(ValueError, message):
                    validate_opening_configuration_identity(
                        identity,
                        **expected,
                    )

    def test_canonical_rank_is_primary_and_persisted_order_cannot_choose(self) -> None:
        self.activate()
        payload = report_payload()
        rank_two = copy.deepcopy(payload["candidates"][0])
        rank_two["rank"] = 2
        rank_two["symbol"] = "SECOND"
        rank_two["evidence_integrity"]["rvol_evidence"]["symbol"] = "SECOND"
        rank_two["scoring"]["composite_score"] = 99
        rank_one = copy.deepcopy(payload["candidates"][0])
        rank_one["rank"] = 1
        rank_one["symbol"] = "FIRST"
        rank_one["evidence_integrity"]["rvol_evidence"]["symbol"] = "FIRST"
        rank_one["scoring"]["composite_score"] = 80
        payload["candidates"] = [rank_two, rank_one]
        self.quote_source.quotes.update(
            {
                "FIRST": quote_payload("FIRST"),
                "SECOND": quote_payload("SECOND"),
            }
        )
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_STARTED, result.status)
        self.assertEqual("FIRST", result.selected_symbol)
        self.assertEqual(1, result.selected_rank)
        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        self.assertEqual(
            ["FIRST", "SECOND"],
            [item["symbol"] for item in cycle["candidate_assessments"]],
        )

    def test_unresolved_catalyst_is_explicitly_ineligible(self) -> None:
        self.activate()
        payload = report_payload()
        row = payload["candidates"][0]
        row["evidence_integrity"]["catalyst_attribution"]["relationship_type"] = (
            "UNRESOLVED"
        )
        row["evidence_integrity"]["catalyst_attribution"]["score_authority"] = (
            "BLOCKED"
        )
        row["scoring"]["authoritative_catalyst_confidence"] = 0
        row["scoring"]["catalyst_score_contribution"] = 0.0
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, result.status)
        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        self.assertIn(
            "catalyst attribution is unresolved or score-blocked",
            " ".join(cycle["candidate_assessments"][0]["rejection_reasons"]),
        )
        self.assertEqual((), self.service.store.load().trades)

    def test_research_only_price_and_plan_authority_are_ineligible(self) -> None:
        self.activate()
        payload = report_payload()
        integrity = payload["candidates"][0]["evidence_integrity"]
        integrity["price_evidence_status"] = "EXECUTION_INELIGIBLE"
        integrity["plan_authority"] = "EXECUTION_INELIGIBLE"
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, result.status)
        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        reasons = " ".join(
            cycle["candidate_assessments"][0]["rejection_reasons"]
        )
        self.assertIn("price evidence is not execution-eligible", reasons)
        self.assertIn("TradePlan authority is not execution-eligible", reasons)

    def test_missing_or_ineligible_time_normalized_rvol_is_rejected(self) -> None:
        self.activate()
        payload = report_payload()
        payload["candidates"][0]["evidence_integrity"].pop("rvol_evidence")
        self.write_report(payload)

        missing = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, missing.status)
        cycle = self.service.decision_cycle_store.get(missing.decision_cycle_id)
        self.assertIn(
            "time-normalized RVOL evidence is missing",
            " ".join(cycle["candidate_assessments"][0]["rejection_reasons"]),
        )

    def test_tampered_time_normalized_rvol_ratio_is_rejected(self) -> None:
        self.activate()
        payload = report_payload()
        payload["candidates"][0]["evidence_integrity"]["rvol_evidence"][
            "relative_volume"
        ] = 8.0
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, result.status)
        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        reasons = " ".join(cycle["candidate_assessments"][0]["rejection_reasons"])
        self.assertIn("ratio contradicts its volumes", reasons)
        self.assertIn("market-data RVOL contradicts", reasons)

    def test_tampered_rvol_baseline_identity_is_rejected(self) -> None:
        self.activate()
        payload = report_payload()
        payload["candidates"][0]["evidence_integrity"]["rvol_evidence"][
            "baseline_session_count"
        ] = 6
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, result.status)
        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        self.assertIn(
            "baseline session dates are invalid",
            " ".join(cycle["candidate_assessments"][0]["rejection_reasons"]),
        )

    def test_tampered_catalyst_contribution_is_ineligible(self) -> None:
        self.activate()
        payload = report_payload()
        payload["candidates"][0]["scoring"]["catalyst_score_contribution"] = 99.0
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, result.status)
        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        self.assertIn(
            "contradicts authorized confidence",
            " ".join(cycle["candidate_assessments"][0]["rejection_reasons"]),
        )

    def test_legacy_composite_profile_is_invalid_before_selection(self) -> None:
        self.activate()
        payload = report_payload()
        payload["metadata"]["composite_profile"] = "trade-planning-composite-v1"
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_INVALID_REPORT, result.status)
        self.assertIn("not authority-enforced", result.reason)
        self.assertEqual((), self.service.store.load().trades)

    def test_tampered_composite_configuration_is_invalid_before_selection(self) -> None:
        self.activate()
        payload = report_payload()
        payload["metadata"]["composite_configuration"]["blocked_catalyst_confidence"] = 75
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_INVALID_REPORT, result.status)
        self.assertIn("contradicts its fingerprint", result.reason)
        self.assertEqual((), self.service.store.load().trades)

    def test_batch_quote_source_is_called_once_for_candidates_and_benchmarks(self) -> None:
        self.activate()
        payload = report_payload()
        second = copy.deepcopy(payload["candidates"][0])
        second["rank"] = 2
        second["symbol"] = "SECOND"
        second["evidence_integrity"]["rvol_evidence"]["symbol"] = "SECOND"
        payload["candidates"].append(second)
        self.write_report(payload)
        source = BatchQuoteSource(
            {
                "TEST": quote_payload("TEST"),
                "SECOND": quote_payload("SECOND"),
                "SPY": quote_payload("SPY", bid=625.00, ask=625.02),
                "IWM": quote_payload("IWM", bid=225.00, ask=225.02),
            }
        )

        result = AutomaticShadowSelector(
            self.service,
            quote_source=source,
        ).select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_STARTED, result.status)
        self.assertEqual(
            [(("TEST", "SECOND", "SPY", "IWM"), self.decision_at)],
            source.calls,
        )

    def test_score_and_symbol_are_stable_tie_breakers(self) -> None:
        self.activate()
        payload = report_payload()
        rows = []
        for symbol, score in (("ZZZ", 90), ("AAA", 90), ("MID", 95)):
            row = copy.deepcopy(payload["candidates"][0])
            row["rank"] = 1
            row["symbol"] = symbol
            row["evidence_integrity"]["rvol_evidence"]["symbol"] = symbol
            row["scoring"]["composite_score"] = score
            rows.append(row)
            self.quote_source.quotes[symbol] = quote_payload(symbol)
        payload["candidates"] = rows
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual("MID", result.selected_symbol)
        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        self.assertEqual(
            ["MID", "AAA", "ZZZ"],
            [item["symbol"] for item in cycle["candidate_assessments"]],
        )

    def test_decimal_scores_are_not_truncated_and_duplicate_identity_fails_closed(
        self,
    ) -> None:
        self.activate()
        payload = report_payload()
        low = copy.deepcopy(payload["candidates"][0])
        low["rank"] = 1
        low["symbol"] = "LOW"
        low["evidence_integrity"]["rvol_evidence"]["symbol"] = "LOW"
        low["scoring"]["composite_score"] = 90.1
        high = copy.deepcopy(payload["candidates"][0])
        high["rank"] = 1
        high["symbol"] = "HIGH"
        high["evidence_integrity"]["rvol_evidence"]["symbol"] = "HIGH"
        high["scoring"]["composite_score"] = 90.9
        payload["candidates"] = [low, high]
        self.quote_source.quotes.update(
            {
                "LOW": quote_payload("LOW"),
                "HIGH": quote_payload("HIGH"),
            }
        )
        self.write_report(payload)

        selected = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual("HIGH", selected.selected_symbol)
        cycle = self.selector().decision_store.find_report(
            hashlib.sha256(self.report_path.read_bytes()).hexdigest()
        )
        self.assertIsNotNone(cycle)
        assert cycle is not None
        self.assertEqual(90.9, cycle["candidate_assessments"][0]["composite_score"])
        self.assertEqual(90.9, self.service.store.load().trades[0].candidate_score)

        duplicate_payload = report_payload()
        duplicate = copy.deepcopy(duplicate_payload["candidates"][0])
        duplicate["rank"] = 2
        duplicate_payload["candidates"].append(duplicate)
        duplicate_payload["metadata"]["source_capture_path"] = (
            "synthetic/duplicate-identity.json"
        )
        duplicate_payload["metadata"]["source_capture_time"] = (
            "2026-07-23T10:01:00-05:00"
        )
        duplicate_payload["metadata"]["generated_at"] = (
            "2026-07-23T10:01:30-05:00"
        )
        duplicate_path = (
            self.reports_dir / "trade-plan-briefing-duplicate-identity.json"
        )
        self.write_report(duplicate_payload, path=duplicate_path)

        with self.assertRaisesRegex(ValueError, "duplicated"):
            self.selector().select(
                duplicate_path,
                decision_at=at("2026-07-23T10:02:00-05:00"),
            )

        nonfinite_payload = report_payload()
        nonfinite_payload["candidates"][0]["scoring"]["composite_score"] = (
            float("nan")
        )
        nonfinite_payload["metadata"]["source_capture_path"] = (
            "synthetic/nonfinite-score.json"
        )
        nonfinite_payload["metadata"]["source_capture_time"] = (
            "2026-07-23T10:01:00-05:00"
        )
        nonfinite_payload["metadata"]["generated_at"] = (
            "2026-07-23T10:01:30-05:00"
        )
        nonfinite_path = (
            self.reports_dir / "trade-plan-briefing-nonfinite-score.json"
        )
        self.write_report(nonfinite_payload, path=nonfinite_path)
        with self.assertRaisesRegex(ValueError, "finite canonical score"):
            self.selector().select(
                nonfinite_path,
                decision_at=at("2026-07-23T10:02:00-05:00"),
            )

    def test_informational_provider_warning_does_not_hide_fresh_quote(self) -> None:
        self.activate()
        payload = report_payload()
        payload["candidates"][0]["trade_plan"]["warnings"] = [
            "QUOTE_HTTP_401"
        ]
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_STARTED, result.status)
        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        assessment = cycle["candidate_assessments"][0]
        self.assertEqual([], assessment["fatal_warnings"])
        self.assertEqual(["QUOTE_HTTP_401"], assessment["informational_warnings"])
        self.assertEqual("COMPLETE", self.service.store.load().trades[0].data_quality_state)

    def test_unknown_and_structural_warnings_fail_closed(self) -> None:
        assessment = classify_warnings(
            ["UNKNOWN_PROVIDER_MAGIC", "MISSING_BID_ASK"],
            ["MISSING_STOP"],
        )
        self.assertEqual(
            ("MISSING_STOP", "UNKNOWN_PROVIDER_MAGIC"),
            assessment.fatal,
        )
        self.assertEqual(("MISSING_BID_ASK",), assessment.informational)

    def test_multi_clock_freshness_rejects_each_stale_or_ambiguous_boundary(self) -> None:
        cases = (
            (
                "stale-capture",
                "2026-07-23T09:49:59-05:00",
                "2026-07-23T09:59:30-05:00",
                "Source capture is stale",
            ),
            (
                "report-delay",
                "2026-07-23T09:58:00-05:00",
                "2026-07-23T09:58:59-05:00",
                "Report-to-selection delay is 61 seconds",
            ),
            (
                "future-report",
                "2026-07-23T09:58:00-05:00",
                "2026-07-23T10:00:01-05:00",
                "later than the decision",
            ),
            (
                "offsetless",
                "2026-07-23T09:58:00-05:00",
                "2026-07-23T09:59:30",
                "utc offsets",
            ),
        )
        for name, capture_time, report_time, expected in cases:
            with self.subTest(name=name):
                temporary = Path(self.root / name)
                temporary.mkdir()
                service = ShadowTradingService(
                    store=ShadowStateStore(temporary / "state.json")
                )
                with patch(
                    "momentum_hunter.shadow_trading.now_central",
                    return_value=at("2026-07-23T09:47:00-05:00"),
                ):
                    service.activate_official_sample(
                        confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION
                    )
                service.arm_automatic_selector(
                    confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                    prerequisite_proof_paths=write_synthetic_proof_artifacts(
                        temporary,
                        name,
                        sample_version=service.sample_definition.sample_version,
                        activation_path=service.activation_store.path,
                        verified_at=at("2026-07-23T09:47:20-05:00"),
                    ),
                    armed_at=at("2026-07-23T09:47:30-05:00"),
                )
                payload = report_payload()
                payload["metadata"]["source_capture_time"] = capture_time
                payload["metadata"]["generated_at"] = report_time
                path = temporary / "trade-plan-briefing-test.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                selector = AutomaticShadowSelector(
                    service,
                    quote_source=self.quote_source,
                )
                try:
                    result = selector.select(path, decision_at=self.decision_at)
                except ValueError as exc:
                    reason = str(exc)
                else:
                    reason = result.reason
                    self.assertEqual(SELECTION_INVALID_REPORT, result.status)
                self.assertIn(expected.lower(), reason.lower())
                self.assertFalse((temporary / "state.json").exists())

    def test_provider_schema_quote_identity_and_latency_evidence_are_frozen(
        self,
    ) -> None:
        self.activate()
        missing_provider = report_payload()
        missing_provider["metadata"]["source_provider"] = ""
        self.write_report(missing_provider)

        invalid = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_INVALID_REPORT, invalid.status)
        self.assertIn("source-provider", invalid.reason)

        valid_root = self.root / "valid-identity"
        valid_root.mkdir()
        valid_service = activated_armed_service(
            valid_root,
            seed="valid-identity",
        )
        valid_path = valid_root / "trade-plan-briefing-valid.json"
        valid_path.write_text(json.dumps(report_payload()), encoding="utf-8")
        valid_result = AutomaticShadowSelector(
            valid_service,
            quote_source=self.quote_source,
        ).select(valid_path, decision_at=self.decision_at)
        cycle = valid_service.decision_cycle_store.get(
            valid_result.decision_cycle_id
        )
        assessment = cycle["candidate_assessments"][0]
        self.assertEqual(60.0, cycle["clock_evidence"]["capture_to_report_seconds"])
        self.assertEqual(60.0, cycle["clock_evidence"]["report_to_selection_seconds"])
        self.assertEqual("synthetic-test-provider", cycle["source_provider"])
        self.assertEqual("synthetic-read-only-quote", assessment["quote_source"])
        self.assertEqual(16.0, assessment["quote_age_seconds"])

        mismatch_root = self.root / "quote-mismatch"
        mismatch_root.mkdir()
        mismatch_service = activated_armed_service(
            mismatch_root,
            seed="quote-mismatch",
        )
        mismatch_path = mismatch_root / "trade-plan-briefing-mismatch.json"
        mismatch_path.write_text(json.dumps(report_payload()), encoding="utf-8")
        mismatch_result = AutomaticShadowSelector(
            mismatch_service,
            quote_source=DictQuoteSource(
                {
                    "TEST": quote_payload("WRONG"),
                    "SPY": quote_payload("SPY"),
                    "IWM": quote_payload("IWM"),
                }
            ),
        ).select(mismatch_path, decision_at=self.decision_at)
        mismatch_cycle = mismatch_service.decision_cycle_store.get(
            mismatch_result.decision_cycle_id
        )
        self.assertEqual(
            SELECTION_NO_ELIGIBLE_CANDIDATE,
            mismatch_result.status,
        )
        self.assertIn(
            "symbol does not match",
            " ".join(
                mismatch_cycle["candidate_assessments"][0][
                    "rejection_reasons"
                ]
            ),
        )

    def test_quote_boundary_rejects_stale_target_stop_spread_halt_and_session(self) -> None:
        mutations = {
            "stale": {"timestamp": "2026-07-23T09:59:29-05:00"},
            "nonfinite": {"bid": float("nan")},
            "target": {"bid": 10.50, "ask": 10.51, "last": 10.50},
            "stop": {"bid": 9.49, "ask": 9.50, "last": 9.49},
            "spread": {"bid": 9.00, "ask": 9.95, "last": 9.50},
            "halt": {"trading_state": "halted"},
            "extended": {"session": "extended"},
        }
        for name, changes in mutations.items():
            with self.subTest(name=name):
                temporary = Path(self.root / f"quote-{name}")
                temporary.mkdir()
                service = activated_armed_service(
                    temporary,
                    seed=name,
                )
                payload = report_payload()
                path = temporary / "trade-plan-briefing-test.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                quote = {**quote_payload("TEST"), **changes}
                selector = AutomaticShadowSelector(
                    service,
                    quote_source=DictQuoteSource(
                        {
                            "TEST": quote,
                            "SPY": quote_payload("SPY"),
                            "IWM": quote_payload("IWM"),
                        }
                    ),
                )

                result = selector.select(path, decision_at=self.decision_at)

                self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, result.status)
                cycle = service.decision_cycle_store.get(result.decision_cycle_id)
                self.assertTrue(
                    cycle["candidate_assessments"][0]["rejection_reasons"]
                )
                self.assertFalse((temporary / "state.json").exists())

    def test_entry_window_market_calendar_and_forced_exit_deadline_are_frozen(self) -> None:
        self.assertTrue(
            entry_window_findings(at("2026-07-23T08:34:59-05:00"))
        )
        self.assertEqual(
            (),
            entry_window_findings(at("2026-07-23T08:35:00-05:00")),
        )
        self.assertEqual(
            (),
            entry_window_findings(at("2026-07-23T14:30:00-05:00")),
        )
        self.assertTrue(
            entry_window_findings(at("2026-07-23T14:30:01-05:00"))
        )
        self.assertTrue(
            entry_window_findings(at("2026-07-25T10:00:00-05:00"))
        )
        self.assertEqual(
            "2026-07-23T15:55:00-04:00",
            forced_exit_deadline(
                at("2026-07-23T10:00:00-05:00")
            ).isoformat(),
        )
        self.assertEqual(
            (),
            entry_window_findings(at("2026-11-27T11:30:00-06:00")),
        )
        self.assertTrue(
            entry_window_findings(at("2026-11-27T11:30:01-06:00"))
        )
        self.assertEqual(
            "2026-11-27T12:55:00-05:00",
            forced_exit_deadline(
                at("2026-11-27T11:00:00-06:00")
            ).isoformat(),
        )
        self.assertFalse(is_nyse_early_close(datetime(2026, 7, 2).date()))
        self.assertEqual(
            "2026-07-02T15:55:00-04:00",
            forced_exit_deadline(
                at("2026-07-02T10:00:00-05:00")
            ).isoformat(),
        )
        with self.assertRaisesRegex(ValueError, "not frozen"):
            is_nyse_early_close(datetime(2029, 1, 2).date())

    def test_official_position_is_forced_flat_and_never_held_overnight(self) -> None:
        self.activate()
        self.write_report()
        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )
        self.assertEqual(SELECTION_STARTED, result.status)
        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-07-23T10:00:05-05:00",
                bid=9.94,
                ask=9.95,
                last=9.94,
                session="regular",
                trading_state="tradable",
                source="synthetic-fill",
            ),
            received_at=at("2026-07-23T10:00:05-05:00"),
        )
        self.assertEqual("open", self.service.store.load().trades[0].status)

        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-07-23T14:55:00-05:00",
                bid=10.10,
                ask=10.11,
                last=10.10,
                session="regular",
                trading_state="tradable",
                source="synthetic-forced-exit",
            ),
            received_at=at("2026-07-23T14:55:00-05:00"),
        )

        trade = self.service.store.load().trades[0]
        self.assertEqual("completed", trade.status)
        self.assertEqual("forced_session_exit", trade.outcome.exit_reason)
        self.assertTrue(audit_shadow_trade(trade).passed)

    def test_early_close_position_is_forced_flat_at_frozen_deadline(self) -> None:
        decision_at = at("2026-11-27T11:00:00-06:00")
        with patch(
            "momentum_hunter.shadow_trading.now_central",
            return_value=at("2026-11-27T10:57:00-06:00"),
        ):
            self.service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
            )
        self.service.arm_automatic_selector(
            confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
            prerequisite_proof_paths=self.proof_artifacts(
                "early-close",
                verified_at=at("2026-11-27T10:57:20-06:00"),
            ),
            armed_at=at("2026-11-27T10:57:30-06:00"),
        )
        payload = report_payload()
        payload["metadata"]["generated_at"] = "2026-11-27T10:59:00-06:00"
        payload["metadata"]["source_capture_time"] = (
            "2026-11-27T10:58:00-06:00"
        )
        report = self.write_report(
            payload,
            path=(
                self.reports_dir
                / "trade-plan-briefing-2026-11-27-morning.json"
            ),
        )
        self.quote_source = DictQuoteSource(
            {
                "TEST": quote_payload(
                    "TEST",
                    timestamp="2026-11-27T10:59:45-06:00",
                ),
                "SPY": quote_payload(
                    "SPY",
                    timestamp="2026-11-27T10:59:45-06:00",
                    bid=625.00,
                    ask=625.02,
                ),
                "IWM": quote_payload(
                    "IWM",
                    timestamp="2026-11-27T10:59:45-06:00",
                    bid=225.00,
                    ask=225.02,
                ),
            }
        )
        result = self.selector().select(report, decision_at=decision_at)
        self.assertEqual(SELECTION_STARTED, result.status)
        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-11-27T11:00:05-06:00",
                bid=9.94,
                ask=9.95,
                last=9.94,
                session="regular",
                trading_state="tradable",
                source="synthetic-early-close-fill",
            ),
            received_at=at("2026-11-27T11:00:05-06:00"),
        )
        self.assertEqual("open", self.service.store.load().trades[0].status)

        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-11-27T11:55:00-06:00",
                bid=10.10,
                ask=10.11,
                last=10.10,
                session="regular",
                trading_state="tradable",
                source="synthetic-early-close-exit",
            ),
            received_at=at("2026-11-27T11:55:00-06:00"),
        )

        trade = self.service.store.load().trades[0]
        self.assertEqual("completed", trade.status)
        self.assertEqual("forced_session_exit", trade.outcome.exit_reason)
        self.assertEqual(
            "2026-11-27T12:55:00-05:00",
            forced_exit_deadline(decision_at).isoformat(),
        )
        self.assertTrue(audit_shadow_trade(trade).passed)

    def test_unfilled_official_entry_is_cancelled_after_entry_window(self) -> None:
        self.activate()
        self.write_report()
        self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-07-23T14:31:00-05:00",
                bid=10.01,
                ask=10.02,
                last=10.01,
                session="regular",
                trading_state="tradable",
                source="synthetic-late-entry",
            ),
            received_at=at("2026-07-23T14:31:00-05:00"),
        )

        trade = self.service.store.load().trades[0]
        self.assertEqual("cancelled", trade.status)
        self.assertEqual("cancelled", trade.order.status)
        self.assertIn("entry window", trade.last_reason)
        transition = trade.ledger_events[-1].payload
        self.assertEqual("pending_entry", transition["previous_state"])
        self.assertEqual("cancelled", transition["new_state"])
        self.assertEqual("synthetic-late-entry", transition["quote_provider"])
        self.assertEqual(
            "2026-07-23T14:31:00-05:00",
            transition["provider_timestamp"],
        )
        self.assertEqual(10.01, transition["executable_mark"])
        self.assertEqual(
            trade.ledger_events[-1].event_id,
            transition["ledger_event_id"],
        )

    def test_official_fill_observation_older_than_ten_seconds_is_rejected(
        self,
    ) -> None:
        self.activate()
        self.write_report()
        self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-07-23T10:00:01-05:00",
                bid=9.94,
                ask=9.95,
                last=9.94,
                session="regular",
                trading_state="tradable",
                source="synthetic-stale-fill",
            ),
            received_at=at("2026-07-23T10:00:32-05:00"),
        )

        trade = self.service.store.load().trades[0]
        self.assertEqual("pending_entry", trade.status)
        self.assertIsNone(trade.position)
        self.assertIn("10-second", trade.last_reason)

    def test_next_session_observation_forces_flat_instead_of_overnight_hold(
        self,
    ) -> None:
        self.activate()
        self.write_report()
        self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )
        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-07-23T10:00:05-05:00",
                bid=9.94,
                ask=9.95,
                last=9.94,
                session="regular",
                trading_state="tradable",
                source="synthetic-fill",
            ),
            received_at=at("2026-07-23T10:00:05-05:00"),
        )

        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-07-24T08:30:00-05:00",
                bid=10.00,
                ask=10.01,
                last=10.00,
                session="regular",
                trading_state="tradable",
                source="synthetic-next-session",
            ),
            received_at=at("2026-07-24T08:30:00-05:00"),
        )

        trade = self.service.store.load().trades[0]
        self.assertEqual("completed", trade.status)
        self.assertEqual("forced_session_exit", trade.outcome.exit_reason)

    def test_one_active_position_blocks_every_later_report(self) -> None:
        self.activate()
        self.write_report()
        first = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )
        payload = report_payload()
        payload["metadata"]["source_capture_path"] = "synthetic/second-capture.json"
        payload["metadata"]["source_capture_time"] = "2026-07-23T10:03:00-05:00"
        payload["metadata"]["generated_at"] = "2026-07-23T10:03:30-05:00"
        payload["candidates"][0]["symbol"] = "OTHER"
        payload["candidates"][0]["evidence_integrity"]["rvol_evidence"]["symbol"] = "OTHER"
        payload["candidates"][0]["rank"] = 1
        second_path = self.reports_dir / "trade-plan-briefing-second.json"
        second_path.write_text(json.dumps(payload), encoding="utf-8")
        self.quote_source.quotes["OTHER"] = quote_payload(
            "OTHER",
            timestamp="2026-07-23T10:03:45-05:00",
        )

        second = self.selector().select(
            second_path,
            decision_at=at("2026-07-23T10:04:00-05:00"),
        )

        self.assertEqual(SELECTION_STARTED, first.status)
        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, second.status)
        cycle = self.service.decision_cycle_store.get(second.decision_cycle_id)
        self.assertIn(
            "already active",
            " ".join(cycle["candidate_assessments"][0]["rejection_reasons"]),
        )
        self.assertEqual(1, len(self.service.store.load().trades))

    def test_completed_symbol_and_opportunity_cannot_reenter_same_day(self) -> None:
        self.activate()
        self.write_report()
        first = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )
        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-07-23T10:00:05-05:00",
                bid=9.94,
                ask=9.95,
                last=9.94,
                high=9.96,
                low=9.93,
                source="synthetic-read-only-quote",
            ),
            received_at=at("2026-07-23T10:00:05-05:00"),
        )
        self.service.process_quote(
            ShadowQuote(
                symbol="TEST",
                timestamp="2026-07-23T10:00:10-05:00",
                bid=10.55,
                ask=10.56,
                last=10.55,
                high=10.57,
                low=10.50,
                source="synthetic-read-only-quote",
            ),
            received_at=at("2026-07-23T10:00:10-05:00"),
        )
        completed = self.service.store.load().trades[0]
        self.assertEqual("completed", completed.status)
        self.assertIsNotNone(completed.outcome)

        payload = report_payload()
        payload["metadata"]["source_capture_path"] = "synthetic/later-capture.json"
        payload["metadata"]["source_capture_time"] = "2026-07-23T10:03:00-05:00"
        payload["metadata"]["generated_at"] = "2026-07-23T10:03:30-05:00"
        later_path = self.reports_dir / "trade-plan-briefing-later.json"
        self.write_report(payload, path=later_path)
        later = self.selector().select(
            later_path,
            decision_at=at("2026-07-23T10:04:00-05:00"),
        )

        self.assertEqual(SELECTION_STARTED, first.status)
        self.assertEqual(SELECTION_NO_ELIGIBLE_CANDIDATE, later.status)
        cycle = self.service.decision_cycle_store.get(later.decision_cycle_id)
        reasons = " ".join(
            cycle["candidate_assessments"][0]["rejection_reasons"]
        )
        self.assertIn("already has", reasons)
        self.assertIn("opportunity has already been traded", reasons)

    def test_frozen_daily_loss_ceiling_blocks_new_entry(self) -> None:
        trade = type(
            "LossTrade",
            (),
            {
                "status": "completed",
                "symbol": "OLD",
                "opportunity_id": "old-opportunity",
                "decision_timestamp": "2026-07-23T09:40:00-05:00",
                "outcome": type(
                    "Outcome",
                    (),
                    {"executable_pnl": -500.0},
                )(),
            },
        )()

        findings = portfolio_findings(
            (trade,),
            symbol="NEW",
            opportunity_id="new-opportunity",
            decision_at=self.decision_at,
            daily_loss_limit=500.0,
        )

        self.assertIn(
            "The frozen daily-loss ceiling has been reached.",
            findings,
        )

    def test_same_capture_is_idempotent_even_when_report_bytes_change(self) -> None:
        self.activate()
        self.write_report()
        first = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )
        duplicate_payload = report_payload()
        duplicate_payload["metadata"]["generated_at"] = (
            "2026-07-23T09:59:30-05:00"
        )
        duplicate_path = self.reports_dir / "trade-plan-briefing-regenerated.json"
        duplicate_path.write_text(json.dumps(duplicate_payload), encoding="utf-8")

        duplicate = self.selector().select(
            duplicate_path,
            decision_at=self.decision_at,
        )

        self.assertEqual(SELECTION_STARTED, first.status)
        self.assertEqual(SELECTION_DUPLICATE_CAPTURE, duplicate.status)
        self.assertEqual(1, len(self.service.store.load().trades))

    def test_cycle_preserves_all_rejections_random_candidate_and_benchmarks(self) -> None:
        self.activate()
        payload = report_payload()
        eligible = copy.deepcopy(payload["candidates"][0])
        blocked = copy.deepcopy(eligible)
        blocked["rank"] = 1
        blocked["symbol"] = "BLOCK"
        blocked["evidence_integrity"]["rvol_evidence"]["symbol"] = "BLOCK"
        blocked["trade_plan"]["bullish_stop"] = None
        eligible["rank"] = 2
        eligible["symbol"] = "TEST"
        eligible["evidence_integrity"]["rvol_evidence"]["symbol"] = "TEST"
        payload["candidates"] = [blocked, eligible]
        self.write_report(payload)

        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )

        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        self.assertEqual(2, len(cycle["candidate_assessments"]))
        self.assertTrue(cycle["candidate_assessments"][0]["rejection_reasons"])
        self.assertEqual(
            "TEST",
            cycle["deterministic_random_eligible"]["symbol"],
        )
        self.assertEqual({"SPY", "IWM"}, set(cycle["benchmark_baselines"]))
        summary = decision_cycle_summary(
            self.service.decision_cycle_store.load().cycles
        )
        self.assertEqual(1, summary["expectedCycles"])
        self.assertEqual(1, summary["tradesStarted"])

    def test_exact_report_repeat_returns_cycle_without_new_trade(self) -> None:
        self.activate()
        self.write_report()
        selector = self.selector()
        first = selector.select(self.report_path, decision_at=self.decision_at)
        repeated = selector.select(
            self.report_path,
            decision_at=self.decision_at + timedelta(seconds=20),
        )

        self.assertEqual(SELECTION_STARTED, first.status)
        self.assertEqual(SELECTION_ALREADY_PROCESSED, repeated.status)
        self.assertEqual(first.decision_cycle_id, repeated.decision_cycle_id)
        self.assertEqual(1, len(self.service.store.load().trades))

    def test_trade_and_audit_freeze_market_validity_chain(self) -> None:
        self.activate()
        self.write_report()
        before = self.report_path.read_bytes()
        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )
        trade = self.service.store.load().trades[0]

        self.assertEqual(before, self.report_path.read_bytes())
        self.assertEqual(result.decision_cycle_id, trade.decision_cycle_id)
        self.assertEqual(result.opportunity_id, trade.opportunity_id)
        self.assertTrue(trade.selector_arm_id)
        self.assertEqual(shadow_constitution_hash(), trade.constitution_hash)
        self.assertTrue(audit_shadow_trade(trade).passed)
        self.assertFalse(
            audit_shadow_trade(
                replace(trade, opportunity_id="0" * 64)
            ).passed
        )

    def test_persisted_quote_source_is_read_only_and_selects_latest_past_quote(self) -> None:
        observations_path = self.root / "observations.json"
        payload = {
            "observations": [
                {
                    "symbol": "TEST",
                    "timestamp": "2026-07-23T10:00:00-05:00",
                    "quote_timestamp": "2026-07-23T09:59:30-05:00",
                    "quote_source": "provider-a",
                    "price": 9.94,
                    "bid": 9.93,
                    "ask": 9.95,
                    "source_report": "monitor-a",
                },
                {
                    "symbol": "TEST",
                    "timestamp": "2026-07-23T10:00:02-05:00",
                    "quote_timestamp": "2026-07-23T10:00:01-05:00",
                    "quote_source": "provider-a",
                    "price": 10.00,
                    "bid": 9.99,
                    "ask": 10.01,
                    "source_report": "future",
                },
                {
                    "symbol": "TEST",
                    "timestamp": "2026-07-23T10:00:03-05:00",
                    "price": 10.20,
                    "bid": 10.19,
                    "ask": 10.21,
                    "source_report": "fresh-wrapper-without-provider-time",
                },
            ]
        }
        observations_path.write_text(json.dumps(payload), encoding="utf-8")
        before = observations_path.read_bytes()
        source = PersistedObservationQuoteSource(observations_path)

        quote = source.quote("TEST", decision_at=self.decision_at)

        self.assertEqual("2026-07-23T09:59:30-05:00", quote["timestamp"])
        self.assertEqual("provider-a", quote["source"])
        self.assertEqual(before, observations_path.read_bytes())

    def test_persisted_quote_source_rejects_fresh_wrapper_without_provider_time(self) -> None:
        observations_path = self.root / "observations.json"
        observations_path.write_text(
            json.dumps(
                {
                    "observations": [
                        {
                            "symbol": "TEST",
                            "timestamp": "2026-07-23T09:59:59-05:00",
                            "price": 10.00,
                            "bid": 9.99,
                            "ask": 10.01,
                            "source_report": "monitor-wrapper",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        quote = PersistedObservationQuoteSource(observations_path).quote(
            "TEST",
            decision_at=self.decision_at,
        )

        self.assertIsNone(quote)

    def test_workspace_records_counterfactual_observations_without_source_mutation(self) -> None:
        self.activate()
        self.write_report()
        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )
        observations_path = self.root / "observations.json"
        observations = {
            "observations": [
                {
                    "symbol": "SPY",
                    "timestamp": "2026-07-23T10:01:00-05:00",
                    "quote_timestamp": "2026-07-23T10:01:00-05:00",
                    "quote_source": "benchmark-provider",
                    "price": 626.0,
                    "bid": 625.99,
                    "ask": 626.01,
                    "source_report": "benchmark",
                },
                {
                    "symbol": "TEST",
                    "timestamp": "2026-07-23T10:01:00-05:00",
                    "quote_timestamp": "2026-07-23T10:01:00-05:00",
                    "quote_source": "candidate-provider",
                    "price": 10.10,
                    "bid": 10.09,
                    "ask": 10.11,
                    "source_report": "candidate",
                },
            ]
        }
        observations_path.write_text(json.dumps(observations), encoding="utf-8")
        before = observations_path.read_bytes()
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                self.reports_dir,
                observations_path,
                self.state_path,
            ),
            service=self.service,
        )

        workspace.advance_observations(
            received_at=at("2026-07-23T10:01:00-05:00")
        )

        cycle = self.service.decision_cycle_store.get(result.decision_cycle_id)
        self.assertEqual(
            {"SPY", "TEST"},
            {item["symbol"] for item in cycle["market_observations"]},
        )
        marks = {
            item["symbol"]: item for item in cycle["counterfactual_marks"]
        }
        self.assertTrue(marks["SPY"]["available"])
        self.assertTrue(marks["TEST"]["available"])
        self.assertEqual(
            "MARK_TO_LATEST_NOT_A_TRADED_OUTCOME",
            marks["TEST"]["measurement"],
        )
        self.assertGreater(marks["SPY"]["return_percent"], 0)
        self.assertGreater(marks["TEST"]["return_percent"], 0)
        self.assertEqual(before, observations_path.read_bytes())

    def test_expected_cycle_accounting_infers_restart_downtime_and_links_outcome(
        self,
    ) -> None:
        self.activate()
        workspace = ShadowWorkspaceService(
            paths=ShadowWorkspacePaths(
                self.reports_dir,
                self.root / "observations.json",
                self.state_path,
            ),
            service=self.service,
        )

        first = workspace.record_collection_attempt(
            observed_at=at("2026-07-23T10:00:00-05:00")
        )
        current = workspace.record_collection_attempt(
            observed_at=at("2026-07-23T10:16:00-05:00")
        )
        workspace.record_collection_outcome(
            current["cycleId"],
            {
                "status": "NO_ELIGIBLE_CANDIDATE",
                "reason": "No candidate passed.",
                "reportSha256": "a" * 64,
                "decisionCycleId": "b" * 64,
            },
        )

        cycles = self.service.decision_cycle_store.load().cycles
        attempts = [
            item
            for item in cycles
            if item.get("cycle_kind") == "COLLECTION_ATTEMPT"
        ]
        summary = decision_cycle_summary(cycles)
        self.assertTrue(first["recorded"])
        self.assertEqual(4, len(attempts))
        self.assertEqual(4, summary["expectedCycles"])
        self.assertEqual(2, summary["systemDowntimeCycles"])
        self.assertEqual(1, summary["successfulCaptures"])
        linked = self.service.decision_cycle_store.get(current["cycleId"])
        self.assertEqual("NO_ELIGIBLE_CANDIDATE", linked["status"])
        self.assertEqual("b" * 64, linked["linked_decision_cycle_id"])

    def test_counterfactual_holding_window_finalization_is_immutable(self) -> None:
        self.activate()
        self.write_report()
        result = self.selector().select(
            self.report_path,
            decision_at=self.decision_at,
        )
        store = self.service.decision_cycle_store
        store.append_observations(
            (
                {
                    "symbol": "TEST",
                    "timestamp": "2026-07-23T10:05:00-05:00",
                    "bid": 10.09,
                    "ask": 10.11,
                    "last": 10.10,
                    "source": "candidate",
                },
                {
                    "symbol": "TEST",
                    "timestamp": "2026-07-23T10:20:00-05:00",
                    "bid": 10.49,
                    "ask": 10.51,
                    "last": 10.50,
                    "source": "candidate",
                },
            )
        )

        finalized = store.finalize_counterfactuals(
            result.decision_cycle_id,
            horizon_at="2026-07-23T10:10:00-05:00",
        )

        test_mark = next(
            item
            for item in finalized["counterfactual_marks"]
            if item["symbol"] == "TEST"
        )
        self.assertEqual(
            "SELECTED_TRADE_HOLDING_WINDOW",
            test_mark["measurement"],
        )
        self.assertEqual(
            "2026-07-23T10:05:00-05:00",
            test_mark["latest_timestamp"],
        )
        with self.assertRaisesRegex(ValueError, "immutable"):
            store.finalize_counterfactuals(
                result.decision_cycle_id,
                horizon_at="2026-07-23T10:11:00-05:00",
            )


def activated_armed_service(root: Path, *, seed: str) -> ShadowTradingService:
    service = ShadowTradingService(store=ShadowStateStore(root / "state.json"))
    with patch(
        "momentum_hunter.shadow_trading.now_central",
        return_value=at("2026-07-23T09:57:00-05:00"),
    ):
        service.activate_official_sample(
            confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
        )
    service.arm_automatic_selector(
        confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
        prerequisite_proof_paths=write_synthetic_proof_artifacts(
            root,
            seed,
            sample_version=service.sample_definition.sample_version,
            activation_path=service.activation_store.path,
            verified_at=at("2026-07-23T09:57:20-05:00"),
        ),
        armed_at=at("2026-07-23T09:57:30-05:00"),
    )
    return service


def quote_payload(
    symbol: str,
    *,
    timestamp: str = "2026-07-23T09:59:45-05:00",
    bid: float = 9.94,
    ask: float = 9.96,
) -> dict:
    return {
        "symbol": symbol,
        "timestamp": timestamp,
        "bid": bid,
        "ask": ask,
        "last": bid,
        "volume": 100_000,
        "session": "regular",
        "trading_state": "tradable",
        "source": "synthetic-read-only-quote",
    }


def at(value: str) -> datetime:
    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
