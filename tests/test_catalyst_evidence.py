from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from momentum_hunter.catalyst_evidence import (
    AVAILABLE,
    CATALYST_ATTRIBUTION_CHANGED,
    CATALYST_AUTHORITY_CHANGED,
    CATALYST_BECAME_CURRENT,
    CATALYST_BECAME_STALE,
    CATALYST_CONTENT_CHANGED,
    CATALYST_DISCOVERED,
    CATALYST_DUPLICATE_STATUS_CHANGED,
    CATALYST_SOURCE_METADATA_CHANGED,
    CREATED,
    CURRENT,
    DUPLICATE,
    DUPLICATE_CONTENT,
    OUTAGE,
    RECOVERED,
    REVISED,
    SOURCE_OUTAGE,
    SOURCE_RECOVERED,
    STALE,
    UNKNOWN_TIMESTAMP,
    UNRESOLVED_STATE,
    CatalystEvidenceCoordinator,
    CatalystEvidenceError,
    CatalystEvidencePolicy,
    CatalystEvidenceStore,
    CatalystObservation,
    compare_catalyst_snapshots,
    expected_catalyst_event_id,
    fingerprint_payload,
    validate_snapshot,
)
from momentum_hunter.evidence_integrity import (
    CATALYST_SCORE_BLOCKED,
    CATALYST_SCORE_SUPPORTED,
    CUSTOMER_SUPPLIER,
    DIRECT_ISSUER,
    MACRO,
    PEER,
    RESEARCH_ONLY,
    SECTOR,
    UNRESOLVED,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 10, 14, 30, tzinfo=UTC)


class CatalystEvidenceRevisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "catalyst-evidence.json"
        self.policy = policy()
        self.store = CatalystEvidenceStore(self.path)
        self.coordinator = CatalystEvidenceCoordinator(
            self.store,
            policy=self.policy,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_first_observation_creates_stable_discovery_revision(self) -> None:
        result = self.coordinator.observe(observation())

        self.assertEqual(CREATED, result.status)
        self.assertEqual(1, result.revision.revision_number)
        self.assertEqual((CATALYST_DISCOVERED,), result.revision.material_delta_kinds)
        self.assertTrue(result.revision.triggers_reevaluation)
        self.assertEqual(RESEARCH_ONLY, result.revision.visibility)
        self.assertEqual(result.revision.revision_id, result.material_delta.revision_id)
        self.assertEqual(
            expected_catalyst_event_id("synthetic-feed-v1", "article-100", "NVDA"),
            result.revision.event_id,
        )
        self.assertEqual(1, len(self.store.load().revisions))
        self.assertEqual(1, len(self.store.load().material_deltas))

    def test_exact_duplicate_is_idempotent_and_byte_stable(self) -> None:
        first = self.coordinator.observe(observation())
        before = self.path.read_bytes()

        duplicate = self.coordinator.observe(observation())

        self.assertEqual(DUPLICATE, duplicate.status)
        self.assertEqual(first.revision, duplicate.revision)
        self.assertIsNone(duplicate.material_delta)
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(1, len(self.store.load().revisions))

    def test_redelivery_is_preserved_without_refresh_or_reevaluation(self) -> None:
        first = self.coordinator.observe(observation())
        redelivery = replace(
            observation(),
            provider_timestamp=iso(BASE + timedelta(seconds=30)),
            receipt_timestamp=iso(BASE + timedelta(seconds=31)),
            notes="Second delivery of the same source record.",
        )

        second = self.coordinator.observe(redelivery)
        snapshot = self.coordinator.snapshot(
            first.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=120),
        )

        self.assertEqual(REVISED, second.status)
        self.assertEqual(2, second.revision.revision_number)
        self.assertEqual((), second.revision.material_delta_kinds)
        self.assertFalse(second.revision.triggers_reevaluation)
        self.assertIsNone(second.material_delta)
        self.assertEqual(120.0, snapshot.age_seconds)
        self.assertEqual(1, len(self.store.load().material_deltas))

    def test_cosmetic_text_revision_is_nonmaterial_but_preserved(self) -> None:
        self.coordinator.observe(observation())
        revised = replace(
            observation(),
            headline="NVDA expands AI production!!!",
            provider_timestamp=iso(BASE + timedelta(seconds=10)),
            receipt_timestamp=iso(BASE + timedelta(seconds=11)),
        )

        result = self.coordinator.observe(revised)

        self.assertEqual(REVISED, result.status)
        self.assertEqual((), result.revision.material_delta_kinds)
        self.assertIsNone(result.material_delta)
        self.assertEqual(2, len(self.store.load().revisions))

    def test_content_revision_creates_one_material_delta(self) -> None:
        self.coordinator.observe(observation())
        revised = replace(
            observation(),
            headline="NVDA raises production guidance after demand update",
            summary="Management raised current-quarter production guidance.",
            provider_timestamp=iso(BASE + timedelta(seconds=20)),
            receipt_timestamp=iso(BASE + timedelta(seconds=21)),
        )

        result = self.coordinator.observe(revised)

        self.assertEqual(REVISED, result.status)
        self.assertEqual((CATALYST_CONTENT_CHANGED,), result.revision.material_delta_kinds)
        self.assertEqual(result.revision.material_delta_kinds, result.material_delta.delta_kinds)
        self.assertTrue(result.material_delta.triggers_reevaluation)
        self.assertEqual(2, len(self.store.load().material_deltas))

    def test_source_metadata_change_is_explicitly_material(self) -> None:
        self.coordinator.observe(observation())
        revised = replace(
            observation(),
            canonical_url="https://example.invalid/articles/100-canonical",
            published_at=iso(BASE + timedelta(seconds=5)),
            provider_timestamp=iso(BASE + timedelta(seconds=20)),
            receipt_timestamp=iso(BASE + timedelta(seconds=21)),
        )

        result = self.coordinator.observe(revised)

        self.assertEqual(
            (CATALYST_SOURCE_METADATA_CHANGED,),
            result.revision.material_delta_kinds,
        )

    def test_unresolved_revision_remains_visible_and_authority_blocked(self) -> None:
        first = self.coordinator.observe(observation())
        unresolved = replace(
            observation(),
            headline="Unrelated company discusses a manufacturing expansion",
            summary="No stored relationship to the candidate is proven.",
            relationship_type=UNRESOLVED,
            relationship_evidence="No supported relationship was supplied.",
            score_authority=CATALYST_SCORE_BLOCKED,
            mentioned_symbol="",
            provider_timestamp=iso(BASE + timedelta(seconds=20)),
            receipt_timestamp=iso(BASE + timedelta(seconds=21)),
        )

        result = self.coordinator.observe(unresolved)
        snapshot = self.coordinator.snapshot(
            first.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=30),
        )

        self.assertEqual(
            (CATALYST_CONTENT_CHANGED, CATALYST_ATTRIBUTION_CHANGED, CATALYST_AUTHORITY_CHANGED),
            result.revision.material_delta_kinds,
        )
        self.assertEqual(UNRESOLVED_STATE, snapshot.evidence_state)
        self.assertEqual(CATALYST_SCORE_BLOCKED, snapshot.effective_score_authority)
        self.assertEqual(RESEARCH_ONLY, snapshot.visibility)
        self.assertFalse(snapshot.can_initiate_trade)

    def test_relationship_classes_are_preserved_not_inferred(self) -> None:
        cases = (
            (DIRECT_ISSUER, CATALYST_SCORE_SUPPORTED),
            (SECTOR, CATALYST_SCORE_SUPPORTED),
            (PEER, CATALYST_SCORE_SUPPORTED),
            (CUSTOMER_SUPPLIER, CATALYST_SCORE_SUPPORTED),
            (MACRO, CATALYST_SCORE_SUPPORTED),
            (UNRESOLVED, CATALYST_SCORE_BLOCKED),
        )
        for index, (relationship, authority) in enumerate(cases):
            with self.subTest(relationship=relationship):
                value = replace(
                    observation(),
                    source_article_id=f"article-{index}",
                    relationship_type=relationship,
                    relationship_evidence=f"Caller supplied {relationship} evidence.",
                    score_authority=authority,
                )
                result = self.coordinator.observe(value)
                self.assertEqual(relationship, result.revision.relationship_type)
                self.assertEqual(authority, result.revision.score_authority)

    def test_unresolved_attribution_cannot_claim_supported_authority(self) -> None:
        with self.assertRaisesRegex(CatalystEvidenceError, "must remain"):
            self.coordinator.observe(
                replace(
                    observation(),
                    relationship_type=UNRESOLVED,
                    relationship_evidence="No relationship is proven.",
                    score_authority=CATALYST_SCORE_SUPPORTED,
                )
            )

    def test_same_article_for_different_candidate_has_distinct_event_identity(self) -> None:
        nvda = self.coordinator.observe(observation())
        amd = self.coordinator.observe(
            replace(
                observation(),
                candidate_symbol="AMD",
                candidate_company="Advanced Micro Devices",
                relationship_type=PEER,
                relationship_evidence="Caller supplied a peer relationship.",
                mentioned_symbol="NVDA",
            )
        )

        self.assertNotEqual(nvda.revision.event_id, amd.revision.event_id)
        self.assertEqual(2, len(self.store.load().revisions))

    def test_same_source_content_under_new_article_id_is_preserved_once_materially(self) -> None:
        original = self.coordinator.observe(observation())
        duplicate = self.coordinator.observe(
            replace(
                observation(),
                source_article_id="article-duplicate",
                canonical_url="https://example.invalid/articles/duplicate",
                provider_timestamp=iso(BASE + timedelta(seconds=10)),
                receipt_timestamp=iso(BASE + timedelta(seconds=11)),
                notes="Provider emitted a second record for the same catalyst.",
            )
        )
        ledger = self.store.load()

        self.assertEqual(CREATED, duplicate.status)
        self.assertTrue(duplicate.revision.is_duplicate)
        self.assertEqual(
            original.revision.event_id,
            duplicate.revision.duplicate_of_event_id,
        )
        self.assertEqual((), duplicate.revision.material_delta_kinds)
        self.assertFalse(duplicate.revision.triggers_reevaluation)
        self.assertIsNone(duplicate.material_delta)
        self.assertEqual(2, len(ledger.revisions))
        self.assertEqual(1, len(ledger.material_deltas))
        snapshot = self.coordinator.snapshot(
            duplicate.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=20),
        )
        self.assertEqual(DUPLICATE_CONTENT, snapshot.evidence_state)
        self.assertTrue(snapshot.is_duplicate)
        self.assertEqual(
            CATALYST_SCORE_BLOCKED, snapshot.effective_score_authority
        )
        self.assertFalse(snapshot.can_initiate_trade)

    def test_identical_content_from_a_different_source_is_independent(self) -> None:
        original = self.coordinator.observe(observation())
        other_source = self.coordinator.observe(
            replace(
                observation(),
                source_identity="independent-synthetic-feed-v1",
                source_article_id="independent-article-100",
                provider="independent-provider",
                source_name="Independent Synthetic Wire",
                canonical_url="https://independent.invalid/articles/100",
                provider_timestamp=iso(BASE + timedelta(seconds=10)),
                receipt_timestamp=iso(BASE + timedelta(seconds=11)),
            )
        )

        self.assertNotEqual(original.revision.event_id, other_source.revision.event_id)
        self.assertFalse(other_source.revision.is_duplicate)
        self.assertEqual("", other_source.revision.duplicate_of_event_id)
        self.assertEqual(
            (CATALYST_DISCOVERED,), other_source.revision.material_delta_kinds
        )
        self.assertEqual(2, len(self.store.load().material_deltas))

    def test_duplicate_article_later_diverges_and_becomes_material(self) -> None:
        original = self.coordinator.observe(observation())
        duplicate_observation = replace(
            observation(),
            source_article_id="article-duplicate",
            canonical_url="https://example.invalid/articles/duplicate",
            provider_timestamp=iso(BASE + timedelta(seconds=10)),
            receipt_timestamp=iso(BASE + timedelta(seconds=11)),
        )
        duplicate = self.coordinator.observe(duplicate_observation)
        changed = self.coordinator.observe(
            replace(
                duplicate_observation,
                headline="NVDA raises production guidance after AI demand update",
                summary="Management raised current-quarter production guidance.",
                provider_timestamp=iso(BASE + timedelta(seconds=20)),
                receipt_timestamp=iso(BASE + timedelta(seconds=21)),
            )
        )

        self.assertEqual(original.revision.event_id, duplicate.revision.duplicate_of_event_id)
        self.assertTrue(duplicate.revision.is_duplicate)
        self.assertFalse(changed.revision.is_duplicate)
        self.assertEqual("", changed.revision.duplicate_of_event_id)
        self.assertEqual(
            (
                CATALYST_DUPLICATE_STATUS_CHANGED,
                CATALYST_CONTENT_CHANGED,
            ),
            changed.revision.material_delta_kinds,
        )
        self.assertIsNotNone(changed.material_delta)
        self.assertEqual(2, len(self.store.load().material_deltas))

    def test_unique_article_becoming_duplicate_triggers_authority_reevaluation(self) -> None:
        original = self.coordinator.observe(observation())
        unique_observation = replace(
            observation(),
            source_article_id="article-unique",
            headline="NVDA opens a second manufacturing facility",
            summary="A separate facility opened after construction completed.",
            canonical_url="https://example.invalid/articles/unique",
            provider_timestamp=iso(BASE + timedelta(seconds=10)),
            receipt_timestamp=iso(BASE + timedelta(seconds=11)),
        )
        unique = self.coordinator.observe(unique_observation)
        now_duplicate = self.coordinator.observe(
            replace(
                unique_observation,
                headline=observation().headline,
                summary=observation().summary,
                provider_timestamp=iso(BASE + timedelta(seconds=20)),
                receipt_timestamp=iso(BASE + timedelta(seconds=21)),
            )
        )

        self.assertFalse(unique.revision.is_duplicate)
        self.assertTrue(now_duplicate.revision.is_duplicate)
        self.assertEqual(
            original.revision.event_id,
            now_duplicate.revision.duplicate_of_event_id,
        )
        self.assertEqual(
            (CATALYST_DUPLICATE_STATUS_CHANGED,),
            now_duplicate.revision.material_delta_kinds,
        )
        self.assertTrue(now_duplicate.revision.triggers_reevaluation)
        snapshot = self.coordinator.snapshot(
            now_duplicate.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=30),
        )
        self.assertEqual(DUPLICATE_CONTENT, snapshot.evidence_state)
        self.assertEqual(
            CATALYST_SCORE_BLOCKED, snapshot.effective_score_authority
        )
        self.assertEqual(3, len(self.store.load().material_deltas))

    def test_duplicate_can_reference_a_matching_later_revision_of_source_event(self) -> None:
        original = observation()
        self.coordinator.observe(original)
        revised = replace(
            original,
            headline="NVDA raises production guidance after AI demand update",
            summary="Management raised current-quarter production guidance.",
            provider_timestamp=iso(BASE + timedelta(seconds=10)),
            receipt_timestamp=iso(BASE + timedelta(seconds=11)),
        )
        revised_result = self.coordinator.observe(revised)
        duplicate = self.coordinator.observe(
            replace(
                revised,
                source_article_id="article-revised-duplicate",
                canonical_url="https://example.invalid/articles/revised-duplicate",
                provider_timestamp=iso(BASE + timedelta(seconds=20)),
                receipt_timestamp=iso(BASE + timedelta(seconds=21)),
            )
        )

        self.assertTrue(duplicate.revision.is_duplicate)
        self.assertEqual(
            revised_result.revision.event_id,
            duplicate.revision.duplicate_of_event_id,
        )
        self.assertEqual((), duplicate.revision.material_delta_kinds)
        self.assertEqual(2, len(self.store.load().material_deltas))

    def test_stable_source_chain_rejects_provider_identity_drift(self) -> None:
        self.coordinator.observe(observation())

        with self.assertRaisesRegex(CatalystEvidenceError, "stable identity"):
            self.coordinator.observe(
                replace(
                    observation(),
                    provider="different-provider",
                    provider_timestamp=iso(BASE + timedelta(seconds=10)),
                    receipt_timestamp=iso(BASE + timedelta(seconds=11)),
                )
            )

    def test_revision_receipt_cannot_move_backward(self) -> None:
        self.coordinator.observe(observation())

        with self.assertRaisesRegex(CatalystEvidenceError, "chronology"):
            self.coordinator.observe(
                replace(
                    observation(),
                    headline="NVDA changes the production plan",
                    receipt_timestamp=iso(BASE + timedelta(seconds=1)),
                )
            )

    def test_future_provider_and_publication_timestamps_fail_closed(self) -> None:
        with self.assertRaisesRegex(CatalystEvidenceError, "provider timestamp"):
            self.coordinator.observe(
                replace(
                    observation(),
                    provider_timestamp=iso(BASE + timedelta(seconds=30)),
                )
            )
        with self.assertRaisesRegex(CatalystEvidenceError, "publication timestamp"):
            self.coordinator.observe(
                replace(
                    observation(),
                    published_at=iso(BASE + timedelta(seconds=30)),
                )
            )

    def test_input_observation_is_not_mutated(self) -> None:
        source = observation(candidate_symbol="nvda")
        before = asdict(source)

        self.coordinator.observe(source)

        self.assertEqual(before, asdict(source))


class CatalystEvidenceStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "catalyst-evidence.json"
        self.policy = policy(maximum_age_seconds=60)
        self.store = CatalystEvidenceStore(self.path)
        self.coordinator = CatalystEvidenceCoordinator(self.store, policy=self.policy)
        self.created = self.coordinator.observe(observation())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_current_evidence_becomes_stale_without_store_mutation(self) -> None:
        current = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=30),
        )
        before = self.path.read_bytes()
        stale = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=61),
        )
        delta = compare_catalyst_snapshots(current, stale)

        self.assertEqual(CURRENT, current.evidence_state)
        self.assertEqual(STALE, stale.evidence_state)
        self.assertEqual(CATALYST_SCORE_BLOCKED, stale.effective_score_authority)
        self.assertEqual(
            (CATALYST_BECAME_STALE, CATALYST_AUTHORITY_CHANGED),
            delta.delta_kinds,
        )
        self.assertEqual(before, self.path.read_bytes())

    def test_repeated_stale_evaluation_does_not_create_another_delta(self) -> None:
        first = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=61),
        )
        second = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=62),
        )

        self.assertIsNone(compare_catalyst_snapshots(first, second))

    def test_missing_publication_timestamp_is_explicitly_unknown(self) -> None:
        other = self.coordinator.observe(
            replace(observation(), source_article_id="article-unknown", published_at="")
        )

        snapshot = self.coordinator.snapshot(
            other.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=30),
        )

        self.assertEqual(UNKNOWN_TIMESTAMP, snapshot.evidence_state)
        self.assertIsNone(snapshot.age_seconds)
        self.assertEqual(CATALYST_SCORE_BLOCKED, snapshot.effective_score_authority)

    def test_source_outage_blocks_effective_authority(self) -> None:
        before = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=30),
        )
        outage = self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=OUTAGE,
            occurred_at=BASE + timedelta(seconds=31),
            reason="Synthetic provider unavailable.",
        )
        during = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=32),
        )
        delta = compare_catalyst_snapshots(before, during)

        self.assertEqual(CREATED, outage.status)
        self.assertEqual(SOURCE_OUTAGE, outage.event.material_delta_kind)
        self.assertEqual(SOURCE_OUTAGE, during.evidence_state)
        self.assertEqual(OUTAGE, during.availability_status)
        self.assertEqual(CATALYST_SCORE_BLOCKED, during.effective_score_authority)
        self.assertEqual(
            (SOURCE_OUTAGE, CATALYST_AUTHORITY_CHANGED), delta.delta_kinds
        )

    def test_repeated_outage_is_preserved_but_not_material(self) -> None:
        first = self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=OUTAGE,
            occurred_at=BASE + timedelta(seconds=31),
            reason="Synthetic provider unavailable.",
        )
        repeated = self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=OUTAGE,
            occurred_at=BASE + timedelta(seconds=40),
            reason="Synthetic provider remains unavailable.",
        )

        self.assertTrue(first.event.triggers_reevaluation)
        self.assertFalse(repeated.event.triggers_reevaluation)
        self.assertEqual("", repeated.event.material_delta_kind)
        self.assertEqual(2, len(self.store.load().availability_events))

    def test_observation_during_outage_requires_explicit_recovery(self) -> None:
        self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=OUTAGE,
            occurred_at=BASE + timedelta(seconds=31),
            reason="Synthetic provider unavailable.",
        )

        with self.assertRaisesRegex(CatalystEvidenceError, "explicitly recovered"):
            self.coordinator.observe(
                replace(
                    observation(),
                    headline="NVDA reports another production update",
                    provider_timestamp=iso(BASE + timedelta(seconds=40)),
                    receipt_timestamp=iso(BASE + timedelta(seconds=41)),
                )
            )

    def test_recovery_does_not_refresh_old_publication_time(self) -> None:
        self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=OUTAGE,
            occurred_at=BASE + timedelta(seconds=31),
            reason="Synthetic provider unavailable.",
        )
        recovered = self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=RECOVERED,
            occurred_at=BASE + timedelta(seconds=70),
            reason="Synthetic provider recovered.",
        )
        snapshot = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=71),
        )

        self.assertEqual(SOURCE_RECOVERED, recovered.event.material_delta_kind)
        self.assertEqual(RECOVERED, snapshot.availability_status)
        self.assertEqual(STALE, snapshot.evidence_state)
        self.assertEqual(71.0, snapshot.age_seconds)
        self.assertEqual(CATALYST_SCORE_BLOCKED, snapshot.effective_score_authority)

    def test_recovery_returns_fresh_record_to_current_without_new_revision(self) -> None:
        self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=OUTAGE,
            occurred_at=BASE + timedelta(seconds=10),
            reason="Synthetic provider unavailable.",
        )
        during = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=11),
        )
        self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=RECOVERED,
            occurred_at=BASE + timedelta(seconds=20),
            reason="Synthetic provider recovered.",
        )
        after = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=21),
        )
        delta = compare_catalyst_snapshots(during, after)

        self.assertEqual(CURRENT, after.evidence_state)
        self.assertEqual(
            (SOURCE_RECOVERED, CATALYST_BECAME_CURRENT, CATALYST_AUTHORITY_CHANGED),
            delta.delta_kinds,
        )
        self.assertEqual(1, len(self.store.load().revisions))

    def test_recovery_without_outage_fails_closed(self) -> None:
        with self.assertRaisesRegex(CatalystEvidenceError, "prior outage"):
            self.coordinator.record_availability(
                source_identity="synthetic-feed-v1",
                status=RECOVERED,
                occurred_at=BASE + timedelta(seconds=20),
                reason="Impossible recovery.",
            )

    def test_historical_snapshot_ignores_future_revision_and_outage(self) -> None:
        self.coordinator.observe(
            replace(
                observation(),
                headline="NVDA raises production guidance",
                provider_timestamp=iso(BASE + timedelta(seconds=89)),
                receipt_timestamp=iso(BASE + timedelta(seconds=90)),
            )
        )
        self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=OUTAGE,
            occurred_at=BASE + timedelta(seconds=100),
            reason="Later outage.",
        )

        historical = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=30),
        )

        self.assertEqual(self.created.revision.revision_id, historical.revision_id)
        self.assertEqual(AVAILABLE, historical.availability_status)
        self.assertEqual(CURRENT, historical.evidence_state)

    def test_late_observation_before_later_outage_has_no_outage_lookahead(self) -> None:
        self.coordinator.record_availability(
            source_identity="synthetic-feed-v1",
            status=OUTAGE,
            occurred_at=BASE + timedelta(seconds=100),
            reason="Later outage.",
        )
        late = replace(
            observation(),
            source_article_id="article-late",
            headline="NVDA published a second earlier update",
            provider_timestamp=iso(BASE + timedelta(seconds=49)),
            receipt_timestamp=iso(BASE + timedelta(seconds=50)),
        )

        result = self.coordinator.observe(late)

        self.assertEqual(CREATED, result.status)
        snapshot = self.coordinator.snapshot(
            result.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=60),
        )
        self.assertEqual(CURRENT, snapshot.evidence_state)
        self.assertEqual(AVAILABLE, snapshot.availability_status)

    def test_state_comparison_rejects_cross_event_identity(self) -> None:
        other = self.coordinator.observe(
            replace(observation(), source_article_id="article-200")
        )
        first = self.coordinator.snapshot(
            self.created.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=20),
        )
        second = self.coordinator.snapshot(
            other.revision.event_id,
            evaluated_at=BASE + timedelta(seconds=20),
        )

        with self.assertRaisesRegex(CatalystEvidenceError, "one event"):
            compare_catalyst_snapshots(first, second)


class CatalystEvidenceStoreAndBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "catalyst-evidence.json"
        self.policy = policy()
        self.store = CatalystEvidenceStore(self.path)
        self.coordinator = CatalystEvidenceCoordinator(self.store, policy=self.policy)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_same_input_sequence_is_deterministic_across_stores(self) -> None:
        self.coordinator.observe(observation())
        first_bytes = self.path.read_bytes()
        other_path = Path(self.temporary.name) / "other.json"
        other = CatalystEvidenceCoordinator(
            CatalystEvidenceStore(other_path),
            policy=self.policy,
        )

        other.observe(observation())

        self.assertEqual(first_bytes, other_path.read_bytes())

    def test_tampered_revision_fails_closed(self) -> None:
        self.coordinator.observe(observation())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["revisions"][0]["headline"] = "Tampered headline"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CatalystEvidenceError, "fingerprint"):
            self.store.load()

    def test_tampered_duplicate_reference_fails_closed(self) -> None:
        self.coordinator.observe(observation())
        self.coordinator.observe(
            replace(
                observation(),
                source_article_id="article-duplicate",
                canonical_url="https://example.invalid/articles/duplicate",
                provider_timestamp=iso(BASE + timedelta(seconds=10)),
                receipt_timestamp=iso(BASE + timedelta(seconds=11)),
            )
        )
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["revisions"][1]["duplicate_of_event_id"] = "f" * 64
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CatalystEvidenceError, "fingerprint"):
            self.store.load()

    def test_tampered_material_delta_fails_closed(self) -> None:
        self.coordinator.observe(observation())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        payload["material_deltas"][0]["delta_kinds"] = [
            CATALYST_CONTENT_CHANGED
        ]
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CatalystEvidenceError, "fingerprint"):
            self.store.load()

    def test_rehashed_material_delta_cannot_reference_unknown_revision(self) -> None:
        self.coordinator.observe(observation())
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        delta = payload["material_deltas"][0]
        delta["revision_id"] = "f" * 64
        fingerprint_input = {
            key: value
            for key, value in delta.items()
            if key not in {"fingerprint", "delta_id"}
        }
        delta["fingerprint"] = fingerprint_payload(fingerprint_input)
        delta["delta_id"] = f"catalyst-delta-{delta['fingerprint'][:24]}"
        self.path.write_text(json.dumps(payload), encoding="utf-8")

        with self.assertRaisesRegex(CatalystEvidenceError, "unknown revision"):
            self.store.load()

    def test_atomic_replace_failure_preserves_prior_ledger(self) -> None:
        self.coordinator.observe(observation())
        before = self.path.read_bytes()

        with patch(
            "momentum_hunter.catalyst_evidence.os.replace",
            side_effect=OSError("synthetic replace failure"),
        ):
            with self.assertRaises(OSError):
                self.coordinator.observe(
                    replace(
                        observation(),
                        headline="NVDA raises production guidance",
                        provider_timestamp=iso(BASE + timedelta(seconds=20)),
                        receipt_timestamp=iso(BASE + timedelta(seconds=21)),
                    )
                )

        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual([], list(self.path.parent.glob(".*.tmp")))
        self.assertEqual(1, len(self.store.load().revisions))

    def test_malformed_json_fails_closed_with_redacted_error(self) -> None:
        self.path.write_text("{not-json", encoding="utf-8")

        with self.assertRaisesRegex(CatalystEvidenceError, "JSONDecodeError"):
            self.store.load()

    def test_malformed_ledger_collection_entry_is_not_silently_skipped(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile": "provider-neutral-catalyst-evidence-v1",
                    "revisions": ["not-an-object"],
                    "material_deltas": [],
                    "availability_events": [],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(CatalystEvidenceError, "collection is malformed"):
            self.store.load()

    def test_boolean_schema_and_none_identity_fail_closed(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": True,
                    "profile": "provider-neutral-catalyst-evidence-v1",
                    "revisions": [],
                    "material_deltas": [],
                    "availability_events": [],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CatalystEvidenceError, "schema version"):
            self.store.load()

        with self.assertRaisesRegex(CatalystEvidenceError, "source identity"):
            self.coordinator.observe(
                replace(observation(), source_identity=None)
            )

    def test_invalid_policy_values_fail_closed(self) -> None:
        with self.assertRaisesRegex(CatalystEvidenceError, "positive"):
            CatalystEvidenceCoordinator(
                self.store,
                policy=policy(maximum_age_seconds=0),
            )
        with self.assertRaisesRegex(CatalystEvidenceError, "nonnegative"):
            CatalystEvidenceCoordinator(
                self.store,
                policy=policy(future_tolerance_seconds=-1),
            )

    def test_snapshots_are_deterministically_sorted(self) -> None:
        self.coordinator.observe(
            replace(
                observation(),
                source_article_id="article-z",
                candidate_symbol="ZETA",
                candidate_company="Zeta Global",
            )
        )
        self.coordinator.observe(
            replace(
                observation(),
                source_article_id="article-a",
                candidate_symbol="AMD",
                candidate_company="Advanced Micro Devices",
            )
        )

        snapshots = self.coordinator.snapshots(
            evaluated_at=BASE + timedelta(seconds=30)
        )

        self.assertEqual(["AMD", "ZETA"], [item.candidate_symbol for item in snapshots])
        for snapshot in snapshots:
            validate_snapshot(snapshot)

    def test_module_has_no_network_broker_scoring_or_runtime_imports(self) -> None:
        source_path = Path(__file__).parents[1] / "momentum_hunter" / "catalyst_evidence.py"
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            {
                "requests",
                "httpx",
                "urllib",
                "socket",
                "alpaca",
                "schwab",
            }.isdisjoint(imported)
        )
        for forbidden in (
            "submit_order",
            "cancel_order",
            "RiskGovernor",
            "build_trade_planning_report",
            "composite_score",
            "CandidateLifecycleCoordinator(",
        ):
            self.assertNotIn(forbidden, source)


def policy(
    *,
    maximum_age_seconds: int = 300,
    future_tolerance_seconds: int = 5,
) -> CatalystEvidencePolicy:
    return CatalystEvidencePolicy(
        policy_version="synthetic-catalyst-policy-v1",
        maximum_age_seconds=maximum_age_seconds,
        future_tolerance_seconds=future_tolerance_seconds,
        material_delta_profile="synthetic-material-delta-v1",
    )


def observation(**changes) -> CatalystObservation:
    value = CatalystObservation(
        source_identity="synthetic-feed-v1",
        source_article_id="article-100",
        provider="synthetic-provider",
        source_name="Synthetic Wire",
        candidate_symbol="NVDA",
        candidate_company="NVIDIA Corp",
        headline="NVDA expands AI production",
        summary="The company expanded production after demand increased.",
        published_at=iso(BASE),
        provider_timestamp=iso(BASE + timedelta(seconds=1)),
        receipt_timestamp=iso(BASE + timedelta(seconds=2)),
        relationship_type=DIRECT_ISSUER,
        relationship_evidence="The supplied source explicitly names NVDA.",
        score_authority=CATALYST_SCORE_SUPPORTED,
        canonical_url="https://example.invalid/articles/100",
        mentioned_symbol="NVDA",
        mentioned_company="NVIDIA Corp",
        notes="Synthetic fixture only.",
    )
    return replace(value, **changes)


def iso(value: datetime) -> str:
    return value.isoformat()


if __name__ == "__main__":
    unittest.main()
