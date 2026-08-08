from __future__ import annotations

import json
import io
import inspect
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from momentum_hunter.shadow_market_validity import (
    SHADOW_SELECTOR_ARM_CONFIRMATION,
)
from momentum_hunter.shadow_selection import (
    SELECTION_STARTED,
    AutomaticShadowSelector,
)
from momentum_hunter.shadow_opening import build_https_clock_skew_proof
from momentum_hunter.shadow_trading import (
    DEFAULT_SHADOW_SAMPLE_VERSION,
    OFFICIAL_SHADOW_SAMPLE_VERSION,
    SHADOW_DECISION_CYCLES_PATH,
    SHADOW_EVIDENCE_SCHEMA_VERSION,
    SHADOW_FILL_MODEL_VERSION,
    SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
    SHADOW_SAMPLE_ACTIVATION_PATH,
    SHADOW_SELECTION_POLICY_PATH,
    SHADOW_SELECTOR_ARM_PATH,
    SHADOW_STATE_PATH,
    ShadowExecutionPolicy,
    ShadowSampleActivationStore,
    ShadowStateError,
    ShadowStateStore,
    ShadowTradingState,
    ShadowTradingService,
    audit_shadow_sample_readiness,
    audit_shadow_trade,
    build_shadow_review_snapshot,
    build_shadow_sample_metadata,
    main,
)
from momentum_hunter.trade_planning import parse_datetime
from momentum_hunter.time_utils import now_central
from tests.test_shadow_trading import (
    at,
    bind_setup_identity,
    completed_auditable_trade,
    completed_trade,
    report_payload,
)
from tests.shadow_proof_fixtures import write_synthetic_proof_artifacts


class ClockedQuoteSource:
    def __init__(self, loader) -> None:
        self.loader = loader

    def quote(self, symbol: str, *, decision_at):
        return self.loader(symbol, decision_at=decision_at)

    def quotes_with_clock(self, symbols, *, decision_at):
        return SimpleNamespace(
            quotes={
                symbol: self.loader(symbol, decision_at=decision_at)
                for symbol in symbols
            },
            clock_skew_proof=build_https_clock_skew_proof(
                request_started_at=decision_at,
                response_received_at=decision_at,
                remote_date_header=format_datetime(decision_at),
                source_identity="synthetic-test-https-date",
            ),
        )


class ShadowSampleReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report_path = (
            self.root / "trade-plan-briefing-2026-07-24-morning.json"
        )
        self.state_path = self.root / "shadow-state.json"
        self.report_path.write_text(json.dumps(report_payload()), encoding="utf-8")
        self.policy = ShadowExecutionPolicy(slippage_bps=7.5, buying_power=25_000)
        self.activation_path = (
            ShadowSampleActivationStore.for_state_store(
                ShadowStateStore(self.state_path)
            ).path
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def service(
        self,
        *,
        sample_version: str = DEFAULT_SHADOW_SAMPLE_VERSION,
        authorized: bool = False,
        policy: ShadowExecutionPolicy | None = None,
    ) -> ShadowTradingService:
        service = ShadowTradingService(
            store=ShadowStateStore(self.state_path),
            policy=policy or self.policy,
            sample_version=sample_version,
        )
        if authorized and service.sample_activation is None:
            self.activate(
                service,
                sample_version=sample_version,
            )
        return service

    def activate(
        self,
        service: ShadowTradingService,
        *,
        sample_version: str = OFFICIAL_SHADOW_SAMPLE_VERSION,
        timestamp: str = "2026-07-23T09:57:00-05:00",
    ):
        with patch(
            "momentum_hunter.shadow_trading.now_central",
            return_value=at(timestamp),
        ):
            return service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
                sample_version=sample_version,
            )

    def start(
        self,
        service: ShadowTradingService,
        command_id: str = "sample-command",
        *,
        decision_at=None,
    ):
        payload = json.loads(self.report_path.read_text(encoding="utf-8"))
        generated_at = parse_datetime(
            str(payload.get("metadata", {}).get("generated_at", ""))
        )
        decision_at = decision_at or (
            generated_at + timedelta(seconds=30)
            if generated_at is not None
            else at("2026-07-24T10:00:00-05:00")
        )
        if service.sample_activation is None:
            return service.start_trade(
                self.report_path,
                symbol="TEST",
                simulation_command_id=command_id,
                decision_at=decision_at,
            )
        if not service.selector_is_armed():
            service.arm_automatic_selector(
                confirmation=SHADOW_SELECTOR_ARM_CONFIRMATION,
                prerequisite_proof_paths=write_synthetic_proof_artifacts(
                    self.root,
                    self.id(),
                    sample_version=service.sample_definition.sample_version,
                    activation_path=service.activation_store.path,
                    verified_at=decision_at - timedelta(seconds=30),
                ),
                armed_at=decision_at - timedelta(seconds=20),
            )
        quote = {
            "symbol": "TEST",
            "timestamp": (decision_at - timedelta(seconds=5)).isoformat(),
            "bid": 9.94,
            "ask": 9.96,
            "last": 9.94,
            "session": "regular",
            "trading_state": "tradable",
            "source": "synthetic-read-only-quote",
        }
        selector = AutomaticShadowSelector(
            service,
            quote_source=ClockedQuoteSource(
                lambda symbol, *, decision_at: (
                    quote
                    if symbol == "TEST"
                    else {
                        **quote,
                        "symbol": symbol,
                        "bid": 100.0,
                        "ask": 100.01,
                        "last": 100.0,
                    }
                )
            ),
        )
        result = selector.select(
            self.report_path,
            decision_at=decision_at,
        )
        if result.status != SELECTION_STARTED:
            raise ValueError(result.reason)
        return next(
            trade
            for trade in service.store.load().trades
            if trade.shadow_trade_id == result.shadow_trade_id
        )

    def test_definition_fingerprint_is_deterministic_and_policy_sensitive(self) -> None:
        first = build_shadow_sample_metadata(
            self.policy,
            sample_version="official-shadow-v1",
            official_sample_authorized=True,
        )
        repeated = build_shadow_sample_metadata(
            self.policy,
            sample_version="official-shadow-v1",
            official_sample_authorized=True,
        )
        changed = build_shadow_sample_metadata(
            replace(self.policy, slippage_bps=8.0),
            sample_version="official-shadow-v1",
            official_sample_authorized=True,
        )

        self.assertEqual(first, repeated)
        self.assertNotEqual(
            first.strategy_configuration_fingerprint,
            changed.strategy_configuration_fingerprint,
        )
        self.assertEqual(SHADOW_FILL_MODEL_VERSION, first.fill_model_version)
        self.assertEqual(SHADOW_EVIDENCE_SCHEMA_VERSION, first.evidence_schema_version)

    def test_new_trade_and_ticket_freeze_metadata_across_restart(self) -> None:
        service = self.service(sample_version="official-shadow-v1", authorized=True)
        trade = self.start(service)
        source_before = self.report_path.read_bytes()

        restarted = self.service(sample_version="official-shadow-v1", authorized=True)
        loaded = restarted.store.load().trades[0]

        self.assertEqual(source_before, self.report_path.read_bytes())
        self.assertEqual(trade.sample_metadata, loaded.sample_metadata)
        self.assertEqual("official-shadow-v1", loaded.sample_metadata.sample_version)
        self.assertTrue(loaded.sample_metadata.official_sample_authorized)
        self.assertEqual(
            loaded.sample_metadata.strategy_configuration_fingerprint,
            loaded.ticket.strategy_configuration_fingerprint if loaded.ticket else "",
        )
        self.assertTrue(audit_shadow_trade(loaded).passed)

    def test_default_runtime_is_blocked_and_snapshot_does_not_start_or_write_sample(self) -> None:
        service = self.service()

        snapshot = service.snapshot()

        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.activation_path.exists())
        self.assertEqual("BLOCKED", snapshot["sampleReadiness"]["status"])
        self.assertFalse(snapshot["sampleReadiness"]["canStartOfficialSample"])
        self.assertFalse(snapshot["sample"]["officialSampleAuthorized"])
        self.assertTrue(
            any(
                "persisted activation" in finding
                for finding in snapshot["sampleReadiness"]["findings"]
            )
        )

    def test_explicit_authorized_definition_can_pass_without_creating_trade(self) -> None:
        service = self.service(sample_version="official-shadow-v1", authorized=True)

        snapshot = service.snapshot()

        self.assertFalse(self.state_path.exists())
        self.assertTrue(self.activation_path.exists())
        self.assertEqual("PASS", snapshot["sampleReadiness"]["status"])
        self.assertTrue(snapshot["sampleReadiness"]["canStartOfficialSample"])
        self.assertEqual([], snapshot["trades"])

    def test_legacy_record_is_preserved_but_excluded_without_backfill(self) -> None:
        service = self.service(sample_version="official-shadow-v1", authorized=True)
        self.start(service)
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        del payload["trades"][0]["sample_metadata"]
        ticket = payload["trades"][0].get("ticket")
        if isinstance(ticket, dict):
            for field_name in (
                "sample_version",
                "strategy_configuration_fingerprint",
                "fill_model_version",
                "evidence_schema_version",
            ):
                ticket.pop(field_name, None)
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        before = self.state_path.read_bytes()

        snapshot = service.snapshot()

        self.assertEqual(before, self.state_path.read_bytes())
        self.assertEqual("", snapshot["trades"][0]["sample_metadata"]["sample_version"])
        self.assertFalse(snapshot["reviewTrades"][0]["evidenceEligible"])
        self.assertFalse(snapshot["reviewTrades"][0]["countsTowardSample"])
        self.assertEqual("FAIL", snapshot["audits"][snapshot["trades"][0]["shadow_trade_id"]]["status"])

    def test_tampered_configuration_fingerprint_fails_audit_and_eligibility(self) -> None:
        service = self.service(sample_version="official-shadow-v1", authorized=True)
        trade = self.start(service)
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload["trades"][0]["sample_metadata"]["strategy_configuration_json"] = "{}"
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")

        snapshot = service.snapshot()
        review = snapshot["reviewTrades"][0]

        self.assertFalse(review["evidenceEligible"])
        self.assertFalse(review["countsTowardSample"])
        self.assertEqual("FAIL", snapshot["audits"][trade.shadow_trade_id]["status"])
        self.assertTrue(
            any(
                "fingerprint" in reason.lower()
                for reason in review["evidenceLock"]["reasons"]
            )
        )

    def test_non_object_sample_metadata_fails_state_load_safely(self) -> None:
        service = self.service(sample_version="official-shadow-v1", authorized=True)
        self.start(service)
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        payload["trades"][0]["sample_metadata"] = "invalid"
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ShadowStateError, "sample_metadata"):
            service.snapshot()

    def test_reusing_sample_version_with_changed_policy_blocks_readiness(self) -> None:
        first = self.service(sample_version="official-shadow-v1", authorized=True)
        self.start(first)

        with self.assertRaisesRegex(ShadowStateError, "active policy"):
            self.service(
                sample_version="official-shadow-v1",
                authorized=True,
                policy=replace(self.policy, slippage_bps=12.0),
            )

    def test_review_counts_only_the_active_authorized_sample_version(self) -> None:
        current = completed_auditable_trade(1)
        previous = completed_auditable_trade(2)
        previous_metadata = replace(
            previous.sample_metadata,
            sample_version="synthetic-previous-v1",
        )
        previous_ticket = (
            replace(previous.ticket, sample_version=previous_metadata.sample_version)
            if previous.ticket is not None
            else None
        )
        previous = replace(
            previous,
            sample_metadata=previous_metadata,
            ticket=previous_ticket,
        )

        review = build_shadow_review_snapshot(
            [current, previous],
            sample_definition=current.sample_metadata,
        )

        self.assertEqual(1, review["sample"]["eligibleCompleted"])
        self.assertTrue(review["trades"][0]["countsTowardSample"])
        self.assertFalse(review["trades"][1]["countsTowardSample"])

    def test_unauthorized_completed_trade_never_counts(self) -> None:
        trade = completed_trade(1, executable_pnl=10)

        review = build_shadow_review_snapshot([trade])
        service = self.service()
        service.store.save(ShadowTradingState(trades=(trade,)))
        snapshot = service.snapshot()

        self.assertEqual(0, review["sample"]["eligibleCompleted"])
        self.assertFalse(review["trades"][0]["countsTowardSample"])
        self.assertEqual("BLOCKED", review["sample"]["readinessStatus"])
        self.assertIsNone(snapshot["metrics"]["winRatePercent"])
        self.assertIsNone(snapshot["reviewMetrics"]["winRatePercent"])

    def test_invalid_sample_version_is_rejected_before_state_access(self) -> None:
        with self.assertRaisesRegex(ValueError, "sample version"):
            self.service(sample_version="Official Sample 1", authorized=True)

        self.assertFalse(self.state_path.exists())

    def test_readiness_audit_is_pure_and_has_no_start_method(self) -> None:
        definition = build_shadow_sample_metadata(
            self.policy,
            sample_version="official-shadow-v1",
            official_sample_authorized=True,
        )

        readiness = audit_shadow_sample_readiness(definition, policy=self.policy)

        self.assertEqual("PASS", readiness.status)
        self.assertTrue(readiness.can_start_official_sample)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(hasattr(readiness, "start"))

    def test_sample_status_is_pure_and_does_not_create_files(self) -> None:
        status = self.service().sample_activation_status()

        self.assertEqual("NOT_ACTIVE", status["activationState"])
        self.assertEqual("SAMPLE_ACTIVATION_ONLY", status["readinessScope"])
        self.assertEqual("NOT_ARMED", status["selectorArmState"])
        self.assertIsNone(status["selectorArmId"])
        self.assertFalse(status["automaticCollectionEnabled"])
        self.assertFalse(status["canCollectOfficialTrade"])
        self.assertEqual("NOT_ACTIVATED", status["collectionState"])
        self.assertEqual("SAMPLE_ACTIVATION", status["nextRequiredGate"])
        self.assertEqual("UNAVAILABLE", status["orderTransmission"])
        self.assertFalse(status["transmitting"])
        self.assertFalse(self.state_path.exists())
        self.assertFalse(self.activation_path.exists())

    def test_exact_confirmation_is_checked_before_any_state_or_activation_read(self) -> None:
        service = self.service()

        with (
            patch.object(
                service.activation_store,
                "load",
                side_effect=AssertionError("activation store was read"),
            ),
            patch.object(
                service.store,
                "load",
                side_effect=AssertionError("state store was read"),
            ),
        ):
            with self.assertRaisesRegex(ValueError, "Exact internal"):
                service.activate_official_sample(confirmation="yes")

    def test_activation_writes_only_write_once_activation_evidence(self) -> None:
        service = self.service()
        report_before = self.report_path.read_bytes()

        activation = self.activate(
            service,
            timestamp="2026-07-24T09:57:00-05:00",
        )

        self.assertEqual(OFFICIAL_SHADOW_SAMPLE_VERSION, activation.sample_metadata.sample_version)
        self.assertTrue(self.activation_path.exists())
        self.assertFalse(self.state_path.exists())
        self.assertEqual(report_before, self.report_path.read_bytes())
        self.assertEqual(
            {self.report_path.name, self.activation_path.name},
            {path.name for path in self.root.iterdir()},
        )

    def test_official_v2_namespace_preserves_failed_v1_evidence(self) -> None:
        v1_files = {
            self.root / "shadow-trading-state.json": b"v1-state\n",
            self.root / "shadow-sample-activation.json": b"v1-activation\n",
            self.root / "shadow-selection-policy.json": b"v1-policy\n",
            self.root / "shadow-selector-arm.json": b"v1-arm\n",
            self.root / "shadow-decision-cycles.json": b"v1-cycles\n",
        }
        for path, content in v1_files.items():
            path.write_bytes(content)
        v2_state_path = self.root / SHADOW_STATE_PATH.name
        service = ShadowTradingService(
            store=ShadowStateStore(v2_state_path),
            policy=self.policy,
        )

        activation = self.activate(service)

        self.assertEqual(
            "official-shadow-v3",
            activation.sample_metadata.sample_version,
        )
        self.assertFalse(v2_state_path.exists())
        self.assertTrue(
            v2_state_path.with_name(
                f"{v2_state_path.stem}-sample-activation.json"
            ).exists()
        )
        for path, content in v1_files.items():
            self.assertEqual(content, path.read_bytes())
        self.assertEqual(
            {
                "official-shadow-v3-state.json",
                "official-shadow-v3-sample-activation.json",
                "official-shadow-v3-selection-policy.json",
                "official-shadow-v3-selector-arm.json",
                "official-shadow-v3-decision-cycles.json",
            },
            {
                SHADOW_STATE_PATH.name,
                SHADOW_SAMPLE_ACTIVATION_PATH.name,
                SHADOW_SELECTION_POLICY_PATH.name,
                SHADOW_SELECTOR_ARM_PATH.name,
                SHADOW_DECISION_CYCLES_PATH.name,
            },
        )

    def test_persisted_activation_loads_automatically_across_restart(self) -> None:
        service = self.service()
        expected = self.activate(
            service,
            timestamp="2026-07-24T09:57:00-05:00",
        )

        restarted = ShadowTradingService(
            store=ShadowStateStore(self.state_path),
            policy=self.policy,
        )

        self.assertEqual(expected, restarted.sample_activation)
        self.assertEqual(expected.sample_metadata, restarted.sample_definition)
        self.assertEqual("ACTIVE", restarted.sample_activation_status()["activationState"])

    def test_direct_authorized_constructor_cannot_bypass_persisted_activation(self) -> None:
        with self.assertRaisesRegex(ShadowStateError, "persisted activation"):
            ShadowTradingService(
                store=ShadowStateStore(self.state_path),
                policy=self.policy,
                sample_version=OFFICIAL_SHADOW_SAMPLE_VERSION,
                official_sample_authorized=True,
            )

        self.assertFalse(self.activation_path.exists())
        self.assertFalse(self.state_path.exists())

    def test_activation_api_does_not_accept_a_caller_supplied_timestamp(self) -> None:
        parameters = inspect.signature(
            ShadowTradingService.activate_official_sample
        ).parameters

        self.assertNotIn("activated_at", parameters)

    def test_activation_is_idempotent_only_for_the_identical_definition(self) -> None:
        service = self.service()
        first = self.activate(
            service,
            timestamp="2026-07-24T09:57:00-05:00",
        )
        before = self.activation_path.read_bytes()

        repeated = self.activate(
            service,
            timestamp="2026-07-24T10:15:00-05:00",
        )

        self.assertEqual(first, repeated)
        self.assertEqual(before, self.activation_path.read_bytes())
        with self.assertRaisesRegex(ShadowStateError, "different immutable definition"):
            service.activate_official_sample(
                confirmation=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
                sample_version="official-shadow-v4",
            )
        self.assertEqual(before, self.activation_path.read_bytes())

    def test_malformed_or_tampered_activation_fails_closed(self) -> None:
        service = self.service()
        self.activate(
            service,
            timestamp="2026-07-24T09:57:00-05:00",
        )
        payload = json.loads(self.activation_path.read_text(encoding="utf-8"))
        payload["sample_metadata"]["strategy_configuration_fingerprint"] = "0" * 64
        self.activation_path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(ShadowStateError, "activation is invalid"):
            ShadowTradingService(
                store=ShadowStateStore(self.state_path),
                policy=self.policy,
            )

    def test_active_preflight_trade_blocks_official_activation(self) -> None:
        service = self.service()
        self.start(service, command_id="preflight-active")

        with self.assertRaisesRegex(ShadowStateError, "active legacy or preflight"):
            self.activate(
                service,
                timestamp="2026-07-24T10:01:00-05:00",
            )

        self.assertFalse(self.activation_path.exists())

    def test_preactivation_report_cannot_create_official_trade(self) -> None:
        service = self.service()
        self.activate(
            service,
            timestamp="2026-07-24T09:57:00-05:00",
        )

        with self.assertRaisesRegex(ValueError, "predates official sample activation"):
            self.start(
                service,
                command_id="stale-report",
                decision_at=at("2026-07-24T10:00:00-05:00"),
            )

        self.assertFalse(self.state_path.exists())

    def test_fresh_postactivation_report_can_freeze_first_official_record(self) -> None:
        payload = report_payload()
        payload["metadata"]["source_capture_time"] = "2026-07-24T09:58:00-05:00"
        payload["metadata"]["generated_at"] = "2026-07-24T09:59:00-05:00"
        for row in (
            payload["candidates"][0],
            payload["top_5_for_capital"][0],
        ):
            bind_setup_identity(
                row,
                created_at=at("2026-07-24T09:59:00-05:00"),
            )
        self.report_path.write_text(json.dumps(payload), encoding="utf-8")
        service = self.service()
        self.activate(
            service,
            timestamp="2026-07-24T09:57:00-05:00",
        )

        trade = self.start(service, command_id="official-first")

        self.assertEqual(OFFICIAL_SHADOW_SAMPLE_VERSION, trade.sample_metadata.sample_version)
        self.assertTrue(trade.sample_metadata.official_sample_authorized)
        self.assertEqual(1, len(service.store.load().trades))
        self.assertEqual(
            "2026-07-24T09:58:00-05:00",
            trade.evidence.source_capture_time,
        )

    def test_official_sample_rejects_future_inverted_or_offsetless_evidence_times(self) -> None:
        service = self.service()
        self.activate(
            service,
            timestamp="2026-07-24T09:57:00-05:00",
        )
        cases = (
            (
                "capture-after-generation",
                "2026-07-24T09:59:30-05:00",
                "2026-07-24T09:59:00-05:00",
                "capture is later",
            ),
            (
                "future-report",
                "2026-07-24T09:59:00-05:00",
                "2026-07-24T10:01:00-05:00",
                "later than the decision",
            ),
            (
                "offsetless-report",
                "2026-07-24T09:58:00-05:00",
                "2026-07-24T09:59:00",
                "must include UTC offsets",
            ),
        )
        for command_id, capture_time, generated_at, expected in cases:
            with self.subTest(command_id=command_id):
                payload = report_payload()
                payload["metadata"]["source_capture_time"] = capture_time
                payload["metadata"]["generated_at"] = generated_at
                self.report_path.write_text(json.dumps(payload), encoding="utf-8")
                source_before = self.report_path.read_bytes()

                with self.assertRaisesRegex(ValueError, expected):
                    self.start(
                        service,
                        command_id=command_id,
                        decision_at=at("2026-07-24T10:00:00-05:00"),
                    )

                self.assertEqual(source_before, self.report_path.read_bytes())
                self.assertFalse(self.state_path.exists())

    def test_service_exposes_no_provider_network_or_transmitting_method(self) -> None:
        method_names = {
            name.lower()
            for name in dir(ShadowTradingService)
            if callable(getattr(ShadowTradingService, name, None))
        }

        for forbidden in (
            "submit_order",
            "transmit_order",
            "place_order",
            "cancel_order",
            "replace_order",
            "fetch_quote",
            "request_market_data",
        ):
            self.assertNotIn(forbidden, method_names)

    def test_cli_sample_start_prompts_internally_and_sample_status_is_read_only(self) -> None:
        output = io.StringIO()
        with patch(
            "builtins.input",
            return_value=SHADOW_SAMPLE_ACTIVATION_CONFIRMATION,
        ), redirect_stdout(output):
            self.assertEqual(
                0,
                main(
                    [
                        "--state-path",
                        str(self.state_path),
                        "sample-start",
                    ]
                ),
            )
        activated = json.loads(output.getvalue())
        self.assertEqual("ACTIVE", activated["activationState"])
        self.assertEqual(0, activated["persistedTradeCount"])
        self.assertEqual("UNAVAILABLE", activated["orderTransmission"])
        self.assertFalse(self.state_path.exists())

        status_output = io.StringIO()
        before = self.activation_path.read_bytes()
        with redirect_stdout(status_output):
            self.assertEqual(
                0,
                main(
                    [
                        "--state-path",
                        str(self.state_path),
                        "sample-status",
                    ]
                ),
            )
        status = json.loads(status_output.getvalue())
        self.assertEqual("ACTIVE", status["activationState"])
        self.assertEqual("SAMPLE_ACTIVATION_ONLY", status["readinessScope"])
        self.assertTrue(status["readiness"]["canStartOfficialSample"])
        self.assertEqual("NOT_ARMED", status["selectorArmState"])
        self.assertIsNone(status["selectorArmId"])
        self.assertFalse(status["automaticCollectionEnabled"])
        self.assertFalse(status["canCollectOfficialTrade"])
        self.assertEqual(
            "ACTIVATED_SELECTOR_NOT_ARMED",
            status["collectionState"],
        )
        self.assertEqual(
            "REGULAR_MARKET_QUOTE_PROOF_AND_SELECTOR_BUNDLE",
            status["nextRequiredGate"],
        )
        self.assertEqual(before, self.activation_path.read_bytes())
        self.assertFalse(self.state_path.exists())

    def test_cli_selector_arm_check_is_nonmutating_and_arm_is_guarded(self) -> None:
        service = ShadowTradingService(store=ShadowStateStore(self.state_path))
        self.activate(service)
        proof_paths = write_synthetic_proof_artifacts(
            self.root,
            "cli-selector-arm",
            sample_version=service.sample_definition.sample_version,
            activation_path=service.activation_store.path,
            verified_at=now_central(),
        )
        proof_bundle = next(iter(proof_paths.values())).parent
        policy_path = service.selection_policy_store.path
        arm_path = service.selector_arm_store.path
        cycles_path = service.decision_cycle_store.path

        with self.assertRaisesRegex(ShadowStateError, "unavailable"):
            main(
                [
                    "--state-path",
                    str(self.state_path),
                    "selector-arm-check",
                    "--proof-bundle",
                    str(self.root / "missing-proof-bundle"),
                ]
            )
        self.assertFalse(self.state_path.exists())
        self.assertFalse(policy_path.exists())
        self.assertFalse(arm_path.exists())
        self.assertFalse(cycles_path.exists())

        check_output = io.StringIO()
        with redirect_stdout(check_output):
            self.assertEqual(
                0,
                main(
                    [
                        "--state-path",
                        str(self.state_path),
                        "selector-arm-check",
                        "--proof-bundle",
                        str(proof_bundle),
                    ]
                ),
            )
        check = json.loads(check_output.getvalue())
        self.assertEqual("READY_TO_ARM", check["armState"])
        self.assertEqual(len(proof_paths), check["proofArtifactCount"])
        self.assertFalse(check["stateMutated"])
        self.assertFalse(check["transmitting"])
        self.assertEqual("UNAVAILABLE", check["orderTransmission"])
        self.assertFalse(self.state_path.exists())
        self.assertFalse(policy_path.exists())
        self.assertFalse(arm_path.exists())
        self.assertFalse(cycles_path.exists())

        with patch("builtins.input", return_value="wrong phrase"):
            with self.assertRaisesRegex(ValueError, "confirmation"):
                main(
                    [
                        "--state-path",
                        str(self.state_path),
                        "selector-arm",
                        "--proof-bundle",
                        str(proof_bundle),
                    ]
                )
        self.assertFalse(policy_path.exists())
        self.assertFalse(arm_path.exists())

        arm_output = io.StringIO()
        with patch(
            "builtins.input",
            return_value=SHADOW_SELECTOR_ARM_CONFIRMATION,
        ), redirect_stdout(arm_output):
            self.assertEqual(
                0,
                main(
                    [
                        "--state-path",
                        str(self.state_path),
                        "selector-arm",
                        "--proof-bundle",
                        str(proof_bundle),
                    ]
                ),
            )
        armed = json.loads(arm_output.getvalue())
        self.assertEqual("ARMED", armed["armState"])
        self.assertEqual(len(proof_paths), armed["proofArtifactCount"])
        self.assertEqual(0, armed["persistedTradeCount"])
        self.assertFalse(armed["transmitting"])
        self.assertEqual("UNAVAILABLE", armed["orderTransmission"])
        self.assertFalse(self.state_path.exists())
        self.assertTrue(policy_path.exists())
        self.assertTrue(arm_path.exists())
        self.assertFalse(cycles_path.exists())

        persisted_before = {
            path: path.read_bytes()
            for path in (
                self.activation_path,
                policy_path,
                arm_path,
            )
        }
        armed_status_output = io.StringIO()
        with redirect_stdout(armed_status_output):
            self.assertEqual(
                0,
                main(
                    [
                        "--state-path",
                        str(self.state_path),
                        "sample-status",
                    ]
                ),
            )
        armed_status = json.loads(armed_status_output.getvalue())
        self.assertEqual("ARMED", armed_status["selectorArmState"])
        self.assertEqual(armed["armId"], armed_status["selectorArmId"])
        self.assertTrue(armed_status["automaticCollectionEnabled"])
        self.assertTrue(armed_status["canCollectOfficialTrade"])
        self.assertEqual(
            "ARMED_AWAITING_ELIGIBLE_CYCLE",
            armed_status["collectionState"],
        )
        self.assertEqual(
            "AWAIT_ELIGIBLE_DECISION_CYCLE",
            armed_status["nextRequiredGate"],
        )
        self.assertFalse(self.state_path.exists())
        self.assertEqual(
            persisted_before,
            {path: path.read_bytes() for path in persisted_before},
        )


if __name__ == "__main__":
    unittest.main()
