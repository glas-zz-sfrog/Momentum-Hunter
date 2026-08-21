from __future__ import annotations

import hashlib
import json
import secrets
import tempfile
import unittest
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.alpaca_paper_broker import AlpacaPaperPosition
from momentum_hunter.alpaca_paper_engineering import (
    PAPER_ENGINEERING_SAMPLE_CONFIRMATION,
    PaperEngineeringError,
    freeze_paper_engineering_sample,
)
from momentum_hunter.alpaca_paper_onboarding import ALPACA_LIVE_BASE_URL
from momentum_hunter.continuous_paper import (
    ARM_CONFIRMATION,
    CANARY_ARMED_ONE_ENTRY,
    LOCKED_AFTER_CANARY_ENTRY,
    ContinuousPaperConfig,
    ContinuousPaperEnvironmentAnomaly,
    ContinuousPaperError,
    ContinuousPaperSupervisor,
    _canonical_bytes,
    _fingerprint,
    load_config,
    load_state,
    write_disabled_config,
)
from momentum_hunter.continuous_production import (
    _topology,
    deployment_configuration_fingerprint,
)
from momentum_hunter.continuous_runtime import WRITER_ACCEPTED
from momentum_hunter.intraday_trade_plan import (
    expected_intraday_plan_id,
    intraday_plan_fingerprint,
)
from tests.test_alpaca_paper_engineering import SyntheticAdapter, policy, registry
from tests.test_continuous_paper_contract import at, fixtures
from momentum_hunter.continuous_paper_contract import (
    _intent_fingerprint,
    build_continuous_paper_admission_intent,
)


@dataclass
class WriterResult:
    status: str = WRITER_ACCEPTED


class FakeWriter:
    def __init__(self) -> None:
        self.intents = []

    def write_intent(self, intent):
        self.intents.append(intent)
        return WriterResult()


class FakeEngine:
    def __init__(self) -> None:
        self.calls = 0

    def reconcile_active(self):
        return []

    def run_continuous_admission(self, *_args, **_kwargs):
        self.calls += 1
        return {
            "classification": "PAPER_TRADE_CREATED",
            "terminal": False,
            "reasons": [],
            "decisionCycleId": "paper-cycle-test",
            "continuousAdmissionId": "admission-test",
            "selectedSymbol": "SPCX",
            "paperOrderCreated": True,
            "positionProtected": True,
            "positionFlat": False,
            "entryOrder": {
                "orderId": "paper-order-test",
                "filledQuantity": "0.5",
            },
            "protectiveStopOrder": {
                "orderId": "paper-stop-test",
                "status": "accepted",
            },
            "providerCalls": [],
        }


class ContinuousPaperSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        key = self.root / "ipc.key"
        key.write_bytes(secrets.token_bytes(32))
        self.research = {
            "activationProfile": "research-only-continuous-deployment-v1",
            "mode": "RESEARCH_ONLY",
            "orderCapability": "UNAVAILABLE",
            "runtimeIdentity": "production-continuous-runtime-test",
            "runtimeBuildHash": "a" * 64,
            "evidenceProgramId": "continuous-opportunity-production",
            "evidenceRoot": str(self.root / "evidence"),
            "runtimeStateRoot": str(self.root / "runtime"),
            "ipcKeyPath": str(key),
            "ipcHost": "127.0.0.1",
            "ipcPort": 49281,
            "expectedAccountEnding": "2573",
            "broadDiscoverySeconds": 300,
            "installedProductSha": "1" * 40,
            "continuousTradePlanProducer": "AVAILABLE",
        }
        self.research["configurationFingerprint"] = (
            deployment_configuration_fingerprint(self.research)
        )
        self.research_path = self.root / "research.json"
        self.research_path.write_bytes(_canonical_bytes(self.research))
        sample_id = "continuous-paper-engineering-20260820-v1"
        paper_policy = replace(
            policy(),
            policy_id="continuous-paper-engineering-policy-20260820-v1",
            sample_id=sample_id,
        )
        lifecycle = self.root / "lifecycle-final.json"
        lifecycle.write_text(json.dumps({"fingerprint": "A" * 64}), encoding="ascii")
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            arm = freeze_paper_engineering_sample(
                policy=paper_policy,
                lifecycle_proof_path=lifecycle,
                output_directory=self.root / "paper-engineering",
                confirmation=PAPER_ENGINEERING_SAMPLE_CONFIRMATION,
                activated_at=at(11, 0),
            )
        self.config = ContinuousPaperConfig(
            research_deployment_config_path=self.research_path,
            paper_state_root=self.root / "paper-state",
            paper_engineering_root=self.root / "paper-engineering",
            installed_product_sha="1" * 40,
            sample_id=sample_id,
            policy_fingerprint=paper_policy.fingerprint,
            activation_timestamp=arm.activated_at,
        )
        cycle, member_result, universe_member = fixtures()
        self.admission = build_continuous_paper_admission_intent(
            cycle=cycle,
            member=member_result,
            universe_member=universe_member,
            runtime_configuration_fingerprint=str(
                self.research["configurationFingerprint"]
            ),
            product_sha="1" * 40,
        )
        self._write_admission_record()

    def _write_admission_record(self, admission=None) -> None:
        admission = admission or self.admission
        topology = _topology(self.research)
        record = {
            "schemaVersion": 2,
            "profile": "production-continuous-evidence-record-v2",
            "authority": "RESEARCH_ONLY",
            "executionAuthority": "NONE",
            "orderCapability": "UNAVAILABLE",
            "topologyFingerprint": topology.fingerprint,
            "artifactName": "continuous-plan-ledger",
            "intent": {
                "evidence_type": "PAPER_ADMISSION_INTENT",
                "record_identity": admission.admission_id,
                "record_fingerprint": admission.fingerprint,
            },
            "payload": admission.to_dict(),
        }
        record["recordFingerprint"] = _fingerprint(
            "production-continuous-record-v1", record
        )
        path = (
            Path(str(self.research["evidenceRoot"]))
            / topology.namespace
            / "records"
            / "continuous-plan-ledger"
            / admission.fingerprint[:2]
            / f"{admission.fingerprint}.json"
        )
        path.parent.mkdir(parents=True)
        path.write_bytes(_canonical_bytes(record))

    def _derived_admission(self, *, suffix: str, rank: int, minute: int):
        symbol = suffix.upper()
        plan = replace(
            self.admission.trade_plan,
            plan_id="",
            symbol=symbol,
            lifecycle_updated_at=at(11, minute).isoformat(),
            fingerprint="",
        )
        plan = replace(plan, plan_id=expected_intraday_plan_id(plan))
        plan = replace(plan, fingerprint=intraday_plan_fingerprint(plan))
        setup_id = hashlib.sha256(f"setup-{suffix}".encode("ascii")).hexdigest()
        unsigned = replace(
            self.admission,
            admission_id=f"continuous-paper-admission-{suffix:0<24}"[:52],
            composition_cycle_id=f"cycle-{suffix}",
            universe_member_id=f"member-{suffix}",
            candidate_id=f"candidate-{suffix}",
            canonical_rank=rank,
            symbol=symbol,
            known_at=at(11, minute).isoformat(),
            setup_id=setup_id,
            trade_plan_id=plan.plan_id,
            trade_plan=plan,
            fingerprint="0" * 64,
        )
        return replace(unsigned, fingerprint=_intent_fingerprint(unsigned))

    def supervisor(self, adapter=None):
        writer = FakeWriter()
        with patch(
            "momentum_hunter.alpaca_paper_engineering.adjudicate_lifecycle_capabilities",
            return_value=registry(),
        ):
            supervisor = ContinuousPaperSupervisor(
                config=self.config,
                adapter=adapter or SyntheticAdapter(),
                quote_source=object(),
                writer=writer,
                clock=lambda: at(11, 1),
            )
        return supervisor, writer

    def test_arm_is_read_only_then_one_entry_lock_survives_restart(self):
        supervisor, writer = self.supervisor()

        armed = supervisor.arm(confirmation=ARM_CONFIRMATION)
        self.assertEqual(CANARY_ARMED_ONE_ENTRY, armed["mode"])
        self.assertEqual(1, len(writer.intents))

        engine = FakeEngine()
        supervisor.engine = engine
        state = supervisor.tick()
        self.assertEqual(LOCKED_AFTER_CANARY_ENTRY, state.mode)
        self.assertEqual("PROTECTED", state.pipeline_state)
        self.assertTrue(state.entry_budget_consumed)
        self.assertEqual(1, engine.calls)
        self.assertEqual("paper-order-test", state.current_broker_order_id)
        self.assertEqual("0.5", state.current_position_quantity)
        self.assertEqual("accepted:paper-stop-test", state.protective_order_state)

        restarted, _ = self.supervisor()
        restarted.engine = engine
        restarted_state = restarted.tick()
        self.assertEqual(LOCKED_AFTER_CANARY_ENTRY, restarted_state.mode)
        self.assertEqual(1, engine.calls)
        self.assertTrue(load_state(self.config).entry_budget_consumed)

    def test_unknown_paper_activity_blocks_arm_without_mutation(self):
        adapter = SyntheticAdapter()
        adapter.positions.append(
            AlpacaPaperPosition(
                symbol="OTHER",
                quantity=Decimal("1"),
                side="long",
                average_entry_price=Decimal("10"),
                market_value=Decimal("10"),
                current_price=Decimal("10"),
            )
        )
        supervisor, _ = self.supervisor(adapter)

        with self.assertRaises(ContinuousPaperEnvironmentAnomaly):
            supervisor.arm(confirmation=ARM_CONFIRMATION)
        self.assertFalse(any(call.startswith("POST ") for call in adapter.calls))
        self.assertFalse(any(call.startswith("DELETE ") for call in adapter.calls))

    def test_unknown_activity_after_arm_latches_environment_contamination(self):
        adapter = SyntheticAdapter()
        supervisor, _ = self.supervisor(adapter)
        supervisor.arm(confirmation=ARM_CONFIRMATION)
        adapter.positions.append(
            AlpacaPaperPosition(
                symbol="OTHER",
                quantity=Decimal("1"),
                side="long",
                average_entry_price=Decimal("10"),
                market_value=Decimal("10"),
                current_price=Decimal("10"),
            )
        )
        engine = FakeEngine()
        supervisor.engine = engine

        state = supervisor.tick()

        self.assertEqual("DEGRADED", state.pipeline_state)
        self.assertEqual("PAPER_ENVIRONMENT_CONTAMINATED", state.broker_state)
        self.assertEqual(0, engine.calls)
        self.assertFalse(any(call.startswith("POST ") for call in adapter.calls))
        self.assertFalse(any(call.startswith("DELETE ") for call in adapter.calls))

    def test_live_host_is_rejected_before_adapter_creation(self):
        invalid = ContinuousPaperConfig(
            **{
                **self.config.__dict__,
                "broker_host": ALPACA_LIVE_BASE_URL,
            }
        )

        with self.assertRaises(ContinuousPaperError):
            invalid.validate()

    def test_disabled_configuration_is_write_once_and_fingerprinted(self):
        path = self.root / "paper-config.json"
        written = write_disabled_config(
            path=path,
            research_deployment_config_path=self.research_path,
            paper_state_root=self.config.paper_state_root,
            paper_engineering_root=self.config.paper_engineering_root,
            installed_product_sha=self.config.installed_product_sha,
            sample_id=self.config.sample_id,
            policy_fingerprint=self.config.policy_fingerprint,
            activation_timestamp=self.config.activation_timestamp,
        )
        duplicate = write_disabled_config(
            path=path,
            research_deployment_config_path=self.research_path,
            paper_state_root=self.config.paper_state_root,
            paper_engineering_root=self.config.paper_engineering_root,
            installed_product_sha=self.config.installed_product_sha,
            sample_id=self.config.sample_id,
            policy_fingerprint=self.config.policy_fingerprint,
            activation_timestamp=self.config.activation_timestamp,
        )

        self.assertEqual(written, duplicate)
        self.assertEqual(written, load_config(path))
        with self.assertRaisesRegex(ContinuousPaperError, "conflicts"):
            write_disabled_config(
                path=path,
                research_deployment_config_path=self.research_path,
                paper_state_root=self.config.paper_state_root,
                paper_engineering_root=self.config.paper_engineering_root,
                installed_product_sha=self.config.installed_product_sha,
                sample_id="continuous-paper-engineering-20260821-v1",
                policy_fingerprint=self.config.policy_fingerprint,
                activation_timestamp=self.config.activation_timestamp,
            )

    def test_arm_rejects_missing_trade_plan_producer_before_broker_read(self):
        research = dict(self.research)
        research["continuousTradePlanProducer"] = "UNAVAILABLE"
        research["configurationFingerprint"] = deployment_configuration_fingerprint(
            research
        )
        self.research_path.write_bytes(_canonical_bytes(research))
        adapter = SyntheticAdapter()
        supervisor, _ = self.supervisor(adapter)

        with self.assertRaisesRegex(
            ContinuousPaperError,
            "CONTINUOUS_TRADEPLAN_PRODUCER_UNAVAILABLE",
        ):
            supervisor.arm(confirmation=ARM_CONFIRMATION)
        self.assertEqual([], adapter.calls)

    def test_admission_lineage_requires_current_runtime_configuration(self):
        research = dict(self.research)
        research["broadDiscoverySeconds"] = 600
        research["configurationFingerprint"] = deployment_configuration_fingerprint(
            research
        )
        self.research_path.write_bytes(_canonical_bytes(research))
        self.research = research
        self._write_admission_record()
        supervisor, _ = self.supervisor()

        with self.assertRaisesRegex(ContinuousPaperError, "lineage"):
            supervisor._admissions()

    def test_pre_activation_admission_is_not_processed(self):
        later_config = ContinuousPaperConfig(
            **{
                **self.config.__dict__,
                "activation_timestamp": at(12, 0).isoformat(),
            }
        )
        supervisor, _ = self.supervisor()
        supervisor.config = later_config

        self.assertEqual([], supervisor._admissions())

    def test_immediate_fail_safe_flat_pauses_the_consumed_canary(self):
        supervisor, _ = self.supervisor()
        supervisor.arm(confirmation=ARM_CONFIRMATION)

        class FlatEngine:
            def reconcile_active(self):
                return []

            def run_continuous_admission(self, *_args, **_kwargs):
                return {
                    "classification": "PAPER_TRADE_CREATED",
                    "terminal": True,
                    "paperOrderCreated": True,
                    "positionProtected": False,
                    "positionFlat": True,
                    "reasons": ["PAPER_POST_FILL_RISK_FAILED_EMERGENCY_EXIT"],
                    "providerCalls": [],
                }

        supervisor.engine = FlatEngine()
        state = supervisor.tick()

        self.assertEqual("PAUSED_AFTER_CANARY", state.mode)
        self.assertEqual("TERMINAL", state.pipeline_state)
        self.assertTrue(state.entry_budget_consumed)

    def test_transmitted_unfilled_entry_pauses_the_consumed_canary(self):
        supervisor, _ = self.supervisor()
        supervisor.arm(confirmation=ARM_CONFIRMATION)

        class UnfilledEngine:
            def reconcile_active(self):
                return []

            def run_continuous_admission(self, *_args, **_kwargs):
                return {
                    "classification": "PAPER_BROKER_REJECTED",
                    "terminal": True,
                    "paperOrderCreated": True,
                    "reasons": ["PAPER_ENTRY_UNFILLED"],
                    "providerCalls": [],
                }

        supervisor.engine = UnfilledEngine()
        state = supervisor.tick()

        self.assertEqual("PAUSED_AFTER_CANARY", state.mode)
        self.assertEqual("TERMINAL", state.pipeline_state)
        self.assertTrue(state.entry_budget_consumed)

    def test_event_replay_is_deterministic_after_writer_accept_before_state_save(self):
        supervisor, writer = self.supervisor()
        first = load_state(self.config)
        second = load_state(self.config)
        detail = {
            "classification": "PAPER_RISK_REJECTED",
            "decisionAt": at(11, 1).isoformat(),
        }

        supervisor._write_event("PAPER_ADMISSION_RESULT", first, detail)
        supervisor._write_event("PAPER_ADMISSION_RESULT", second, detail)

        self.assertEqual(writer.intents[0].fingerprint, writer.intents[1].fingerprint)
        self.assertEqual(writer.intents[0].payload_json, writer.intents[1].payload_json)

    def test_accelerated_whole_day_recovers_and_consumes_exactly_one_entry(self):
        second = self._derived_admission(suffix="second", rank=2, minute=2)
        third = self._derived_admission(suffix="third", rank=3, minute=3)
        self._write_admission_record(second)
        self._write_admission_record(third)
        supervisor, writer = self.supervisor()
        supervisor.arm(confirmation=ARM_CONFIRMATION)

        class DayEngine:
            def __init__(self):
                self.entry_calls = 0
                self.failed_once = False
                self.reconcile_calls = 0

            def run_continuous_admission(self, payload, **_kwargs):
                symbol = payload["symbol"]
                if symbol == "SPCX":
                    return {
                        "classification": "PAPER_RISK_REJECTED",
                        "terminal": True,
                        "reasons": ["PAPER_PLAN_NOT_TRIGGERED"],
                        "paperOrderCreated": False,
                        "providerCalls": [],
                    }
                if not self.failed_once:
                    self.failed_once = True
                    raise PaperEngineeringError("synthetic provider interruption")
                self.entry_calls += 1
                return {
                    "classification": "PAPER_TRADE_CREATED",
                    "terminal": False,
                    "reasons": [],
                    "paperOrderCreated": True,
                    "positionProtected": True,
                    "positionFlat": False,
                    "providerCalls": [],
                }

            def reconcile_active(self):
                if self.entry_calls == 0:
                    return []
                self.reconcile_calls += 1
                if self.reconcile_calls < 2:
                    return []
                return [
                    {
                        "classification": "POSITION_CLOSED",
                        "terminal": True,
                        "positionFlat": True,
                        "providerCalls": [],
                    }
                ]

        engine = DayEngine()
        supervisor.engine = engine
        rejected = supervisor.tick()
        self.assertEqual(CANARY_ARMED_ONE_ENTRY, rejected.mode)
        with self.assertRaises(PaperEngineeringError):
            supervisor.tick()

        restarted, _ = self.supervisor()
        restarted.engine = engine
        entered = restarted.tick()
        self.assertEqual(LOCKED_AFTER_CANARY_ENTRY, entered.mode)
        self.assertEqual(1, engine.entry_calls)
        self.assertEqual(2, len(entered.processed_admission_fingerprints))
        self.assertEqual(2, len(entered.processed_trade_plan_ids))
        self.assertNotIn(third.fingerprint, entered.processed_admission_fingerprints)

        still_active = restarted.tick()
        self.assertEqual(LOCKED_AFTER_CANARY_ENTRY, still_active.mode)
        terminal = restarted.tick()
        self.assertEqual("PAUSED_AFTER_CANARY", terminal.mode)
        self.assertEqual(1, engine.entry_calls)
        self.assertGreaterEqual(len(writer.intents), 2)

    def test_same_trade_plan_from_later_cycle_is_not_evaluated_twice(self):
        supervisor, _ = self.supervisor()
        supervisor.arm(confirmation=ARM_CONFIRMATION)

        later = replace(
            self.admission,
            composition_cycle_id="cycle-spcx-later",
            composition_cycle_fingerprint="d" * 64,
            fingerprint="0" * 64,
        )
        later = replace(later, fingerprint=_intent_fingerprint(later))
        self._write_admission_record(later)

        class RejectingEngine:
            def __init__(self):
                self.calls = 0

            def reconcile_active(self):
                return []

            def run_continuous_admission(self, *_args, **_kwargs):
                self.calls += 1
                return {
                    "classification": "PAPER_RISK_REJECTED",
                    "terminal": True,
                    "reasons": ["PAPER_PLAN_NOT_TRIGGERED"],
                    "paperOrderCreated": False,
                    "providerCalls": [],
                }

        engine = RejectingEngine()
        supervisor.engine = engine
        supervisor.tick()
        supervisor.tick()

        self.assertEqual(1, engine.calls)
        state = load_state(self.config)
        self.assertEqual([self.admission.trade_plan_id], state.processed_trade_plan_ids)


if __name__ == "__main__":
    unittest.main()
