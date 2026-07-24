from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from momentum_hunter.shadow_trading import (
    DEFAULT_SHADOW_SAMPLE_VERSION,
    SHADOW_EVIDENCE_SCHEMA_VERSION,
    SHADOW_FILL_MODEL_VERSION,
    ShadowExecutionPolicy,
    ShadowStateError,
    ShadowStateStore,
    ShadowTradingState,
    ShadowTradingService,
    audit_shadow_sample_readiness,
    audit_shadow_trade,
    build_shadow_review_snapshot,
    build_shadow_sample_metadata,
)
from tests.test_shadow_trading import (
    at,
    completed_auditable_trade,
    completed_trade,
    report_payload,
)


class ShadowSampleReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.report_path = self.root / "trade-plan.json"
        self.state_path = self.root / "shadow-state.json"
        self.report_path.write_text(json.dumps(report_payload()), encoding="utf-8")
        self.policy = ShadowExecutionPolicy(slippage_bps=7.5, buying_power=25_000)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def service(
        self,
        *,
        sample_version: str = DEFAULT_SHADOW_SAMPLE_VERSION,
        authorized: bool = False,
        policy: ShadowExecutionPolicy | None = None,
    ) -> ShadowTradingService:
        return ShadowTradingService(
            store=ShadowStateStore(self.state_path),
            policy=policy or self.policy,
            sample_version=sample_version,
            official_sample_authorized=authorized,
        )

    def start(self, service: ShadowTradingService, command_id: str = "sample-command"):
        return service.start_trade(
            self.report_path,
            symbol="TEST",
            simulation_command_id=command_id,
            decision_at=at("2026-07-24T10:00:00-05:00"),
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
        self.assertEqual("BLOCKED", snapshot["sampleReadiness"]["status"])
        self.assertFalse(snapshot["sampleReadiness"]["canStartOfficialSample"])
        self.assertFalse(snapshot["sample"]["officialSampleAuthorized"])
        self.assertTrue(
            any(
                "separate authorization" in finding
                for finding in snapshot["sampleReadiness"]["findings"]
            )
        )

    def test_explicit_authorized_definition_can_pass_without_creating_trade(self) -> None:
        service = self.service(sample_version="official-shadow-v1", authorized=True)

        snapshot = service.snapshot()

        self.assertFalse(self.state_path.exists())
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
        changed = self.service(
            sample_version="official-shadow-v1",
            authorized=True,
            policy=replace(self.policy, slippage_bps=12.0),
        )

        snapshot = changed.snapshot()

        self.assertEqual("BLOCKED", snapshot["sampleReadiness"]["status"])
        self.assertFalse(snapshot["sampleReadiness"]["canStartOfficialSample"])
        self.assertTrue(
            any(
                "conflicts with the active sample definition" in finding
                for finding in snapshot["sampleReadiness"]["findings"]
            )
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


if __name__ == "__main__":
    unittest.main()
