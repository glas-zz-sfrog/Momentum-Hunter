from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import unittest

import momentum_hunter.schwab_canary_credential_remediation as remediation_module
from momentum_hunter.schwab_canary_credential_remediation import (
    APPLICATION_REPLACED,
    CREDENTIAL_REMEDIATION_BLOCK,
    CREDENTIAL_REMEDIATION_PASS,
    CREDENTIAL_REMEDIATION_PROVEN,
    CREDENTIAL_REMEDIATION_REQUIRED,
    SECRET_ROTATED,
    VENDOR_REMEDIATED,
    CanaryCredentialRemediationError,
    CanaryCredentialRemediationObservation,
    CanaryCredentialRemediationPolicy,
    evaluate_canary_credential_remediation,
)


UTC = timezone.utc
INCIDENT_AT = datetime(2026, 7, 26, 14, 0, tzinfo=UTC)
OBSERVED_AT = INCIDENT_AT + timedelta(hours=1)
EVALUATED_AT = OBSERVED_AT + timedelta(minutes=1)
INCIDENT_ID = "SCHWAB-CLIENT-SECRET-2026-07-26"
APPLICATION_SHA256 = "a" * 64
EVIDENCE_SHA256 = "b" * 64


class CanaryCredentialRemediationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = CanaryCredentialRemediationPolicy(
            expected_incident_id=INCIDENT_ID,
            expected_application_commitment_sha256=APPLICATION_SHA256,
            expected_evidence_artifact_sha256=EVIDENCE_SHA256,
            incident_recorded_at=INCIDENT_AT,
        )
        self.observation = CanaryCredentialRemediationObservation(
            incident_id=INCIDENT_ID,
            application_commitment_sha256=APPLICATION_SHA256,
            remediation_state=SECRET_ROTATED,
            evidence_source="SCHWAB_DEVELOPER_PORTAL",
            evidence_artifact_sha256=EVIDENCE_SHA256,
            observed_at=OBSERVED_AT.isoformat(),
            old_credential_invalidated=True,
        )

    def test_exact_reviewed_rotation_passes_without_authority(self) -> None:
        result = self.evaluate()
        payload = result.to_dict()

        self.assertEqual(CREDENTIAL_REMEDIATION_PASS, result.status)
        self.assertEqual(CREDENTIAL_REMEDIATION_PROVEN, result.conclusion)
        self.assertTrue(result.remediation_proven)
        self.assertEqual((), result.findings)
        self.assertFalse(payload["credentialAccessed"])
        self.assertFalse(payload["credentialMutationPerformed"])
        self.assertFalse(payload["providerContactPerformed"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])
        self.assertNotIn("secret", "".join(payload).lower())

    def test_each_documented_remediation_path_can_pass(self) -> None:
        for state, source in (
            (SECRET_ROTATED, "SCHWAB_DEVELOPER_PORTAL"),
            (APPLICATION_REPLACED, "SCHWAB_DEVELOPER_PORTAL"),
            (VENDOR_REMEDIATED, "SCHWAB_SUPPORT"),
        ):
            with self.subTest(state=state):
                result = self.evaluate(
                    observation=replace(
                        self.observation,
                        remediation_state=state,
                        evidence_source=source,
                    )
                )
                self.assertEqual(CREDENTIAL_REMEDIATION_PASS, result.status)

    def test_missing_evidence_blocks_honestly(self) -> None:
        result = self.evaluate(observation=None)

        self.assertEqual(CREDENTIAL_REMEDIATION_BLOCK, result.status)
        self.assertEqual(CREDENTIAL_REMEDIATION_REQUIRED, result.conclusion)
        self.assertFalse(result.remediation_proven)
        self.assertEqual(
            ["REMEDIATION_EVIDENCE_MISSING"],
            [finding.code for finding in result.findings],
        )

    def test_identity_hash_source_and_invalidation_mismatches_block(self) -> None:
        cases = (
            (
                replace(self.observation, incident_id="OTHER-INCIDENT"),
                "INCIDENT_ID_MISMATCH",
            ),
            (
                replace(
                    self.observation,
                    application_commitment_sha256="c" * 64,
                ),
                "APPLICATION_COMMITMENT_MISMATCH",
            ),
            (
                replace(
                    self.observation,
                    evidence_artifact_sha256="d" * 64,
                ),
                "EVIDENCE_ARTIFACT_MISMATCH",
            ),
            (
                replace(self.observation, evidence_source="UNVERIFIED_SOURCE"),
                "EVIDENCE_SOURCE_NOT_ACCEPTED",
            ),
            (
                replace(
                    self.observation,
                    old_credential_invalidated=False,
                ),
                "OLD_CREDENTIAL_NOT_INVALIDATED",
            ),
        )
        for observation, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = self.evaluate(observation=observation)
                self.assertEqual(CREDENTIAL_REMEDIATION_BLOCK, result.status)
                self.assertIn(
                    expected_code,
                    [finding.code for finding in result.findings],
                )

    def test_unremediated_or_unknown_state_blocks(self) -> None:
        for state in ("UNREMEDIATED", "ROTATION_PENDING", ""):
            with self.subTest(state=state):
                result = self.evaluate(
                    observation=replace(
                        self.observation,
                        remediation_state=state,
                    )
                )
                self.assertEqual(CREDENTIAL_REMEDIATION_BLOCK, result.status)
                self.assertIn(
                    "REMEDIATION_STATE_NOT_ACCEPTED",
                    [finding.code for finding in result.findings],
                )

    def test_invalid_predating_and_future_observation_times_block(self) -> None:
        cases = (
            ("not-a-time", "OBSERVATION_TIME_INVALID"),
            (
                (INCIDENT_AT - timedelta(seconds=1)).isoformat(),
                "REMEDIATION_PREDATES_INCIDENT",
            ),
            (
                (EVALUATED_AT + timedelta(seconds=3)).isoformat(),
                "REMEDIATION_TIME_IN_FUTURE",
            ),
            (
                datetime(2026, 7, 26, 15, 0).isoformat(),
                "OBSERVATION_TIME_INVALID",
            ),
        )
        for observed_at, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                result = self.evaluate(
                    observation=replace(
                        self.observation,
                        observed_at=observed_at,
                    )
                )
                self.assertEqual(CREDENTIAL_REMEDIATION_BLOCK, result.status)
                self.assertIn(
                    expected_code,
                    [finding.code for finding in result.findings],
                )

    def test_policy_rejects_ambiguous_or_unbounded_identity(self) -> None:
        cases = (
            {"expected_incident_id": "bad incident"},
            {"expected_application_commitment_sha256": "not-a-hash"},
            {"expected_evidence_artifact_sha256": "not-a-hash"},
            {"incident_recorded_at": datetime(2026, 7, 26, 14, 0)},
            {"accepted_evidence_sources": ()},
            {
                "accepted_evidence_sources": (
                    "SCHWAB_SUPPORT",
                    "SCHWAB_SUPPORT",
                )
            },
            {"max_future_skew_seconds": -1},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                arguments = {
                    "expected_incident_id": INCIDENT_ID,
                    "expected_application_commitment_sha256": (
                        APPLICATION_SHA256
                    ),
                    "expected_evidence_artifact_sha256": EVIDENCE_SHA256,
                    "incident_recorded_at": INCIDENT_AT,
                }
                arguments.update(changes)
                with self.assertRaises(CanaryCredentialRemediationError):
                    CanaryCredentialRemediationPolicy(**arguments)

    def test_result_and_repr_retain_no_raw_credential_fields(self) -> None:
        result = self.evaluate()
        payload = result.to_dict()
        flattened_keys = " ".join(payload).lower()

        self.assertNotIn("clientsecret", flattened_keys)
        self.assertNotIn("accesstoken", flattened_keys)
        self.assertNotIn("refreshtoken", flattened_keys)
        self.assertNotIn("password", flattened_keys)
        self.assertNotIn(APPLICATION_SHA256, repr(result))
        self.assertNotIn(EVIDENCE_SHA256, repr(result))
        self.assertNotIn(APPLICATION_SHA256, repr(self.observation))
        self.assertNotIn(EVIDENCE_SHA256, repr(self.observation))

    def test_module_has_no_network_vault_provider_or_broker_action(self) -> None:
        source = inspect.getsource(remediation_module)
        tree = ast.parse(source)
        imports: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        self.assertTrue(
            imports.isdisjoint(
                {
                    "httpx",
                    "requests",
                    "socket",
                    "subprocess",
                    "urllib",
                    "urllib.request",
                    "momentum_hunter.schwab_setup",
                    "momentum_hunter.schwab_onboarding",
                }
            )
        )
        self.assertTrue(
            calls.isdisjoint(
                {
                    "delete_credentials",
                    "revoke",
                    "rotate_credentials",
                    "submit_order",
                    "replace_order",
                    "cancel_order",
                    "preview_order",
                    "transmit_order",
                }
            )
        )

    def evaluate(self, **changes: object):
        arguments = {
            "observation": self.observation,
            "evaluated_at": EVALUATED_AT,
            "policy": self.policy,
        }
        arguments.update(changes)
        return evaluate_canary_credential_remediation(**arguments)


if __name__ == "__main__":
    unittest.main()
