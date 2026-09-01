from __future__ import annotations

import json
import unittest
from copy import deepcopy
from pathlib import Path

from momentum_hunter.opening_runtime_observer import (
    AUTHORIZED_OBSERVER_RUNTIME_IDENTITY,
    CURRENT_AUTHORIZED_RELEASE,
    DEFAULT_CHANNEL,
    HEARTBEAT_SAFETY_SCHEMA,
    OBSERVER_RESULT_SCHEMA,
    SOURCE_GIT_DIFFERENT,
    evaluate_opening_observer_heartbeat,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "opening_runtime_observer"
    / "september-1-source-git-overbinding.json"
)


class OpeningRuntimeObserverPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.observer_result = {
            "schemaVersion": OBSERVER_RESULT_SCHEMA,
            "observerResult": "PASS",
            "classification": "AUTHORIZED_RUNTIME_MATCH",
            "diagnosticCode": "AUTHORIZED_RUNTIME_MATCH",
            "mode": CURRENT_AUTHORIZED_RELEASE,
            "channel": DEFAULT_CHANNEL,
            "authoritySource": (
                "fixture://opening-capture+verified-promotion-chain"
                "+immutable-release"
            ),
            "authorizedReleaseResolved": True,
            "expectedReleaseId": self.fixture["authorizedReleaseId"],
            "expectedRuntimeFingerprint": self.fixture[
                "authorizedRuntimeFingerprint"
            ],
            "expectedReleaseFingerprint": self.fixture[
                "authorizedReleaseFingerprint"
            ],
            "expectedReleaseSourceGitSha": self.fixture[
                "authorizedReleaseSourceGitSha"
            ],
            "promotionReceiptFingerprint": self.fixture[
                "promotionReceiptFingerprint"
            ],
            "actualReleaseId": self.fixture["authorizedReleaseId"],
            "actualRuntimeFingerprint": self.fixture[
                "authorizedRuntimeFingerprint"
            ],
            "expectedCanonicalGitSha": self.fixture["currentCanonicalGitSha"],
            "actualCanonicalGitSha": self.fixture["currentCanonicalGitSha"],
            "canonicalWorktreeClean": True,
            "runtimeDrift": False,
            "canonicalDrift": False,
            "mutationPerformed": False,
            "orderTransmission": "UNAVAILABLE",
            "authorizedReleaseSourceProvenanceVerified": True,
            "currentSourceEqualsReleaseSource": False,
            "sourceGitRelationship": SOURCE_GIT_DIFFERENT,
        }
        self.safety = {
            "schemaVersion": HEARTBEAT_SAFETY_SCHEMA,
            "observerRuntimeIdentity": AUTHORIZED_OBSERVER_RUNTIME_IDENTITY,
            "observerInstanceCount": 1,
            "readOnly": True,
            "protectedProductionHashesUnchanged": True,
            "servicesUnchanged": True,
            "schedulerUnchanged": True,
            "canonicalLocalOriginSynchronized": True,
            "externalProviderOrAuthenticationContacted": False,
            "brokerOrAccountContacted": False,
            "paperAuthorityUsed": False,
            "executionAuthorityUsed": False,
        }

    def _evaluate(
        self,
        *,
        observer_updates: dict[str, object] | None = None,
        safety_updates: dict[str, object] | None = None,
    ) -> dict[str, object]:
        observer = deepcopy(self.observer_result)
        safety = deepcopy(self.safety)
        observer.update(observer_updates or {})
        safety.update(safety_updates or {})
        return evaluate_opening_observer_heartbeat(observer, safety)

    def test_exact_september_1_source_difference_is_diagnostic_only(self) -> None:
        self.assertNotEqual(
            self.fixture["currentCanonicalGitSha"],
            self.fixture["authorizedReleaseSourceGitSha"],
        )
        self.assertEqual(
            "FAIL_SOURCE_GIT_EQUALITY_OVERBINDING",
            self.fixture["legacyPromptPredicateResult"],
        )

        result = self._evaluate()

        self.assertEqual("PASS", result["heartbeatResult"])
        self.assertEqual(
            "AUTHORIZED_OBSERVER_CAPTURE_VALID",
            result["classification"],
        )
        self.assertTrue(result["authorizedReleaseSourceProvenanceVerified"])
        self.assertFalse(result["currentSourceEqualsReleaseSource"])
        self.assertEqual(SOURCE_GIT_DIFFERENT, result["sourceGitRelationship"])

    def test_unauthorized_release_fails_closed(self) -> None:
        result = self._evaluate(observer_updates={"authorizedReleaseResolved": False})
        self.assertEqual("FAIL", result["heartbeatResult"])
        self.assertEqual(
            "AUTHORIZED_RELEASE_IDENTITY_UNVERIFIED",
            result["diagnosticCode"],
        )

    def test_failed_release_binding_fails_closed(self) -> None:
        result = self._evaluate(
            observer_updates={
                "observerResult": "FAIL",
                "diagnosticCode": "RELEASE_POINTER_CHAIN_INVALID",
            }
        )
        self.assertEqual("AUTHORIZED_RELEASE_BINDING_FAILED", result["diagnosticCode"])

    def test_unauthorized_runtime_and_fingerprint_mismatch_fail_closed(self) -> None:
        cases = (
            {"actualReleaseId": "OPENING-RUNTIME-" + "0" * 20},
            {"actualRuntimeFingerprint": "0" * 64},
            {"runtimeDrift": True},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                result = self._evaluate(observer_updates=updates)
                self.assertEqual(
                    "AUTHORIZED_RUNTIME_IDENTITY_UNVERIFIED",
                    result["diagnosticCode"],
                )

    def test_broken_promotion_or_channel_fails_closed(self) -> None:
        cases = (
            {"promotionReceiptFingerprint": ""},
            {"channel": "unapproved-channel"},
            {"authoritySource": ""},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                result = self._evaluate(observer_updates=updates)
                self.assertEqual(
                    "AUTHORIZED_RELEASE_PROMOTION_CHAIN_UNVERIFIED",
                    result["diagnosticCode"],
                )

    def test_unverified_release_source_provenance_fails_closed(self) -> None:
        cases = (
            {"authorizedReleaseSourceProvenanceVerified": False},
            {"expectedReleaseSourceGitSha": ""},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                result = self._evaluate(observer_updates=updates)
                self.assertEqual(
                    "AUTHORIZED_RELEASE_SOURCE_PROVENANCE_UNVERIFIED",
                    result["diagnosticCode"],
                )

    def test_observer_identity_and_singleton_fail_closed(self) -> None:
        identity = self._evaluate(
            safety_updates={"observerRuntimeIdentity": "unauthorized-observer"}
        )
        singleton = self._evaluate(safety_updates={"observerInstanceCount": 2})
        self.assertEqual(
            "OBSERVER_RUNTIME_IDENTITY_UNAUTHORIZED", identity["diagnosticCode"]
        )
        self.assertEqual("OBSERVER_SINGLETON_VIOLATION", singleton["diagnosticCode"])

    def test_read_only_and_protected_production_fail_closed(self) -> None:
        read_only = self._evaluate(safety_updates={"readOnly": False})
        mutation = self._evaluate(observer_updates={"mutationPerformed": True})
        protected = self._evaluate(
            safety_updates={"protectedProductionHashesUnchanged": False}
        )
        self.assertEqual("OBSERVER_READ_ONLY_VIOLATION", read_only["diagnosticCode"])
        self.assertEqual("OBSERVER_READ_ONLY_VIOLATION", mutation["diagnosticCode"])
        self.assertTrue(mutation["mutationPerformed"])
        self.assertEqual("PROTECTED_PRODUCTION_MUTATION", protected["diagnosticCode"])

    def test_execution_authority_and_order_transmission_fail_closed(self) -> None:
        cases = (
            ({"paperAuthorityUsed": True}, {}),
            ({"executionAuthorityUsed": True}, {}),
            ({}, {"orderTransmission": "AVAILABLE"}),
        )
        for safety_updates, observer_updates in cases:
            with self.subTest(
                safety_updates=safety_updates,
                observer_updates=observer_updates,
            ):
                result = self._evaluate(
                    safety_updates=safety_updates,
                    observer_updates=observer_updates,
                )
                self.assertEqual("EXECUTION_AUTHORITY_PRESENT", result["diagnosticCode"])
                if observer_updates:
                    self.assertEqual("AVAILABLE", result["orderTransmission"])

    def test_invalid_current_canonical_state_fails_closed(self) -> None:
        cases = (
            {"canonicalWorktreeClean": False},
            {"canonicalDrift": True},
            {"actualCanonicalGitSha": "b" * 40},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                result = self._evaluate(observer_updates=updates)
                self.assertEqual(
                    "CURRENT_CANONICAL_INTEGRITY_UNVERIFIED",
                    result["diagnosticCode"],
                )

        unsynchronized = self._evaluate(
            safety_updates={"canonicalLocalOriginSynchronized": False}
        )
        self.assertEqual(
            "CURRENT_CANONICAL_INTEGRITY_UNVERIFIED",
            unsynchronized["diagnosticCode"],
        )

    def test_source_git_diagnostic_must_match_verified_identities(self) -> None:
        cases = (
            {"currentSourceEqualsReleaseSource": True},
            {"sourceGitRelationship": "UNTRUTHFUL_RELATIONSHIP"},
        )
        for updates in cases:
            with self.subTest(updates=updates):
                result = self._evaluate(observer_updates=updates)
                self.assertEqual(
                    "SOURCE_GIT_DIAGNOSTIC_INCONSISTENT",
                    result["diagnosticCode"],
                )

    def test_external_provider_broker_and_account_contact_fail_closed(self) -> None:
        provider = self._evaluate(
            safety_updates={"externalProviderOrAuthenticationContacted": True}
        )
        broker = self._evaluate(safety_updates={"brokerOrAccountContacted": True})
        self.assertEqual(
            "OBSERVER_EXTERNAL_CONTACT_VIOLATION",
            provider["diagnosticCode"],
        )
        self.assertEqual(
            "OBSERVER_BROKER_ACCOUNT_CONTACT_VIOLATION",
            broker["diagnosticCode"],
        )

    def test_service_scheduler_and_malformed_safety_evidence_fail_closed(self) -> None:
        services = self._evaluate(safety_updates={"servicesUnchanged": False})
        scheduler = self._evaluate(safety_updates={"schedulerUnchanged": False})
        malformed = self._evaluate(safety_updates={"observerInstanceCount": True})
        self.assertEqual("PRODUCTION_CONTROL_STATE_CHANGED", services["diagnosticCode"])
        self.assertEqual("PRODUCTION_CONTROL_STATE_CHANGED", scheduler["diagnosticCode"])
        self.assertEqual("OBSERVER_INSTANCE_COUNT_INVALID", malformed["diagnosticCode"])


if __name__ == "__main__":
    unittest.main()
