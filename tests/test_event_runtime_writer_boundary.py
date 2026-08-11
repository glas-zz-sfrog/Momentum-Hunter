from __future__ import annotations

import ast
import unittest
from dataclasses import replace
from pathlib import Path

from momentum_hunter.event_runtime_writer_boundary import (
    AUTOMATION_SERVICE,
    BLOCKED,
    BROKERED_EPHEMERAL,
    CONTRACT_FEASIBLE_PENDING_PROOF,
    DEDICATED_EVIDENCE_WRITER,
    DIRECT_FILESYSTEM,
    DISTINCT_ENGINE_HOST_PRINCIPAL,
    DPAPI_CURRENT_USER,
    ENGINE_HOST,
    EVIDENCE_WRITER,
    INHERITED_HANDLE,
    INHERITED_UNFORGEABLE_CAPABILITY,
    NAMED_PIPE,
    NO_AUTHENTICATION,
    NO_CREDENTIALS,
    SAME_PRINCIPAL_LOGICAL_ONLY,
    SEPARATELY_PROVISIONED_DPAPI,
    SHARED_SECRET,
    WINDOWS_PRINCIPAL,
    WPF_FRONTEND,
    REQUIRED_INSTALLED_PROOFS,
    RuntimeBoundaryProcess,
    RuntimeWriterBoundaryError,
    build_runtime_writer_boundary_policy,
    build_runtime_writer_boundary_proposal,
    evaluate_runtime_writer_boundary,
    validate_runtime_writer_boundary_proposal,
    validate_runtime_writer_boundary_result,
)


USER = "S-1-5-21-100-200-300-1001"
ENGINE = "S-1-5-80-1001"
WRITER = "S-1-5-80-1002"
ROOT_POLICY = "a" * 64


class EventRuntimeWriterBoundaryTests(unittest.TestCase):
    def policy(self, **changes):
        values = {
            "policy_version": "synthetic-writer-boundary-v1",
            "current_secret_owner_sid": USER,
            "required_root_security_policy_fingerprint": ROOT_POLICY,
        }
        values.update(changes)
        return build_runtime_writer_boundary_policy(**values)

    def process(
        self,
        role: str,
        identity: str,
        sid: str,
        *,
        interactive: bool = False,
        read: bool = False,
        write: bool = False,
        credentials: bool = False,
        credential_access: str = NO_CREDENTIALS,
    ) -> RuntimeBoundaryProcess:
        return RuntimeBoundaryProcess(
            role=role,
            process_identity=identity,
            principal_sid=sid,
            interactive_session=interactive,
            can_read_runtime_root=read,
            can_write_runtime_root=write,
            requires_provider_credentials=credentials,
            credential_access=credential_access,
        )

    def distinct_host_processes(self):
        return (
            self.process(AUTOMATION_SERVICE, "service", USER),
            self.process(
                ENGINE_HOST,
                "engine-writer",
                ENGINE,
                read=True,
                write=True,
                credentials=True,
                credential_access=SEPARATELY_PROVISIONED_DPAPI,
            ),
            self.process(
                WPF_FRONTEND,
                "wpf",
                USER,
                interactive=True,
            ),
            self.process(
                EVIDENCE_WRITER,
                "engine-writer",
                ENGINE,
                read=True,
                write=True,
                credentials=True,
                credential_access=SEPARATELY_PROVISIONED_DPAPI,
            ),
        )

    def dedicated_writer_processes(
        self,
        *,
        engine_sid: str = USER,
        engine_credential_access: str = DPAPI_CURRENT_USER,
    ):
        return (
            self.process(AUTOMATION_SERVICE, "service", USER),
            self.process(
                ENGINE_HOST,
                "engine",
                engine_sid,
                credentials=True,
                credential_access=engine_credential_access,
            ),
            self.process(
                WPF_FRONTEND,
                "wpf",
                USER,
                interactive=True,
            ),
            self.process(
                EVIDENCE_WRITER,
                "writer",
                WRITER,
                read=True,
                write=True,
            ),
        )

    def proposal(self, **changes):
        values = {
            "proposal_version": "synthetic-proposal-v1",
            "boundary_kind": DEDICATED_EVIDENCE_WRITER,
            "source_identity": "SYNTHETIC_ARCHITECTURE_FIXTURE",
            "processes": self.dedicated_writer_processes(),
            "engine_to_writer_channel": INHERITED_HANDLE,
            "channel_authentication": INHERITED_UNFORGEABLE_CAPABILITY,
            "channel_capability_persisted": False,
            "channel_capability_visible_to_interactive_user": False,
            "credential_broker_present": False,
            "credential_broker_authentication": NO_AUTHENTICATION,
            "credential_broker_capability_persisted": False,
            "credential_broker_capability_visible_to_interactive_user": False,
            "credential_reprovisioning_approved": False,
            "credential_material_persisted_for_writer": False,
            "credential_material_visible_to_wpf": False,
            "root_security_policy_fingerprint": ROOT_POLICY,
        }
        values.update(changes)
        return build_runtime_writer_boundary_proposal(**values)

    def test_dedicated_writer_with_unforgeable_handle_is_contract_feasible_only(self):
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(),
        )

        self.assertEqual(CONTRACT_FEASIBLE_PENDING_PROOF, result.status)
        self.assertEqual((), result.blockers)
        self.assertEqual(REQUIRED_INSTALLED_PROOFS, result.required_installed_proofs)
        self.assertFalse(result.activation_authorized)
        self.assertEqual("DORMANT_CONTRACT_ONLY", result.authority)

    def test_distinct_engine_host_with_separate_dpapi_is_contract_feasible_only(self):
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(
                boundary_kind=DISTINCT_ENGINE_HOST_PRINCIPAL,
                processes=self.distinct_host_processes(),
                engine_to_writer_channel=DIRECT_FILESYSTEM,
                channel_authentication=WINDOWS_PRINCIPAL,
                credential_reprovisioning_approved=True,
            ),
        )

        self.assertEqual(CONTRACT_FEASIBLE_PENDING_PROOF, result.status)
        self.assertFalse(result.activation_authorized)

    def test_current_same_user_service_engine_wpf_model_is_blocked(self):
        processes = (
            self.process(AUTOMATION_SERVICE, "service", USER),
            self.process(
                ENGINE_HOST,
                "engine-writer",
                USER,
                read=True,
                write=True,
                credentials=True,
                credential_access=DPAPI_CURRENT_USER,
            ),
            self.process(
                WPF_FRONTEND,
                "wpf",
                USER,
                interactive=True,
                read=True,
                write=True,
            ),
            self.process(
                EVIDENCE_WRITER,
                "engine-writer",
                USER,
                read=True,
                write=True,
                credentials=True,
                credential_access=DPAPI_CURRENT_USER,
            ),
        )
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(
                boundary_kind=SAME_PRINCIPAL_LOGICAL_ONLY,
                processes=processes,
                engine_to_writer_channel=DIRECT_FILESYSTEM,
                channel_authentication=WINDOWS_PRINCIPAL,
            ),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("WPF_DIRECT_RUNTIME_ROOT_ACCESS", result.blockers)
        self.assertIn("WRITER_PRINCIPAL_NOT_ISOLATED", result.blockers)
        self.assertIn("MULTIPLE_OR_CONTRADICTORY_ROOT_WRITERS", result.blockers)
        self.assertIn("SAME_PRINCIPAL_LOGICAL_BOUNDARY_INSUFFICIENT", result.blockers)

    def test_same_sid_named_pipe_cannot_distinguish_engine_from_wpf(self):
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(
                engine_to_writer_channel=NAMED_PIPE,
                channel_authentication=WINDOWS_PRINCIPAL,
            ),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("NAMED_PIPE_SID_AUTH_CANNOT_DISTINGUISH_WPF", result.blockers)

    def test_inherited_handle_requires_unforgeable_nonpersisted_capability(self):
        cases = (
            (
                {"channel_authentication": WINDOWS_PRINCIPAL},
                "INHERITED_HANDLE_REQUIRES_UNFORGEABLE_CAPABILITY",
            ),
            (
                {"channel_capability_persisted": True},
                "CHANNEL_CAPABILITY_PERSISTED",
            ),
            (
                {"channel_capability_visible_to_interactive_user": True},
                "CHANNEL_CAPABILITY_VISIBLE_TO_INTERACTIVE_USER",
            ),
        )
        for changes, blocker in cases:
            with self.subTest(blocker=blocker):
                result = evaluate_runtime_writer_boundary(
                    policy=self.policy(),
                    proposal=self.proposal(**changes),
                )
                self.assertEqual(BLOCKED, result.status)
                self.assertIn(blocker, result.blockers)

    def test_shared_secret_channel_is_forbidden(self):
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(
                engine_to_writer_channel=NAMED_PIPE,
                channel_authentication=SHARED_SECRET,
            ),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("PERSISTABLE_SHARED_SECRET_CHANNEL_FORBIDDEN", result.blockers)

    def test_dedicated_writer_cannot_be_bypassed_by_engine_filesystem_access(self):
        processes = list(self.dedicated_writer_processes())
        processes[1] = replace(
            processes[1],
            can_read_runtime_root=True,
            can_write_runtime_root=True,
        )
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(processes=tuple(processes)),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("ENGINE_HOST_BYPASSES_DEDICATED_WRITER", result.blockers)
        self.assertIn("MULTIPLE_OR_CONTRADICTORY_ROOT_WRITERS", result.blockers)

    def test_service_stays_supervisor_only_and_wpf_has_no_root_access(self):
        for index, changes, blocker in (
            (0, {"can_read_runtime_root": True}, "AUTOMATION_SERVICE_NOT_SUPERVISOR_ONLY"),
            (2, {"can_read_runtime_root": True}, "WPF_DIRECT_RUNTIME_ROOT_ACCESS"),
        ):
            with self.subTest(blocker=blocker):
                processes = list(self.dedicated_writer_processes())
                processes[index] = replace(processes[index], **changes)
                result = evaluate_runtime_writer_boundary(
                    policy=self.policy(),
                    proposal=self.proposal(processes=tuple(processes)),
                )
                self.assertEqual(BLOCKED, result.status)
                self.assertIn(blocker, result.blockers)

    def test_service_and_dedicated_writer_cannot_claim_provider_credentials(self):
        cases = (
            (0, "AUTOMATION_SERVICE_PROVIDER_CREDENTIAL_ACCESS"),
            (3, "DEDICATED_WRITER_PROVIDER_CREDENTIAL_ACCESS"),
        )
        for index, blocker in cases:
            with self.subTest(blocker=blocker):
                processes = list(self.dedicated_writer_processes())
                processes[index] = replace(
                    processes[index],
                    requires_provider_credentials=True,
                    credential_access=DPAPI_CURRENT_USER,
                )
                result = evaluate_runtime_writer_boundary(
                    policy=self.policy(),
                    proposal=self.proposal(processes=tuple(processes)),
                )
                self.assertEqual(BLOCKED, result.status)
                self.assertIn(blocker, result.blockers)

    def test_writer_principal_must_differ_from_service_and_wpf(self):
        processes = list(self.dedicated_writer_processes())
        processes[3] = replace(processes[3], principal_sid=USER)
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(processes=tuple(processes)),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("WRITER_PRINCIPAL_NOT_ISOLATED", result.blockers)

    def test_dedicated_writer_principal_must_differ_from_engine(self):
        processes = list(self.dedicated_writer_processes(engine_sid=WRITER))
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(processes=tuple(processes)),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn(
            "DEDICATED_WRITER_PRINCIPAL_NOT_ISOLATED_FROM_ENGINE",
            result.blockers,
        )

    def test_distinct_engine_host_cannot_reuse_current_user_dpapi(self):
        processes = list(self.distinct_host_processes())
        for index in (1, 3):
            processes[index] = replace(
                processes[index],
                credential_access=DPAPI_CURRENT_USER,
            )
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(
                boundary_kind=DISTINCT_ENGINE_HOST_PRINCIPAL,
                processes=tuple(processes),
                engine_to_writer_channel=DIRECT_FILESYSTEM,
                channel_authentication=WINDOWS_PRINCIPAL,
            ),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("DPAPI_CURRENT_USER_OWNER_MISMATCH", result.blockers)

    def test_separate_dpapi_requires_explicit_reprovisioning_approval(self):
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(
                boundary_kind=DISTINCT_ENGINE_HOST_PRINCIPAL,
                processes=self.distinct_host_processes(),
                engine_to_writer_channel=DIRECT_FILESYSTEM,
                channel_authentication=WINDOWS_PRINCIPAL,
                credential_reprovisioning_approved=False,
            ),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("CREDENTIAL_REPROVISIONING_NOT_APPROVED", result.blockers)

    def test_ephemeral_credential_broker_requires_authenticated_broker(self):
        processes = self.dedicated_writer_processes(
            engine_sid=ENGINE,
            engine_credential_access=BROKERED_EPHEMERAL,
        )
        blocked = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(processes=processes),
        )
        feasible = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(
                processes=processes,
                credential_broker_present=True,
                credential_broker_authentication=INHERITED_UNFORGEABLE_CAPABILITY,
            ),
        )

        self.assertIn("CREDENTIAL_BROKER_MISSING", blocked.blockers)
        self.assertEqual(CONTRACT_FEASIBLE_PENDING_PROOF, feasible.status)

    def test_credential_broker_same_sid_auth_and_capability_leaks_are_blocked(self):
        processes = self.dedicated_writer_processes(
            engine_sid=USER,
            engine_credential_access=BROKERED_EPHEMERAL,
        )
        cases = (
            (
                {
                    "credential_broker_present": True,
                    "credential_broker_authentication": WINDOWS_PRINCIPAL,
                },
                "CREDENTIAL_BROKER_SID_AUTH_CANNOT_DISTINGUISH_WPF",
            ),
            (
                {
                    "credential_broker_present": True,
                    "credential_broker_authentication": INHERITED_UNFORGEABLE_CAPABILITY,
                    "credential_broker_capability_persisted": True,
                },
                "CREDENTIAL_BROKER_CAPABILITY_PERSISTED",
            ),
            (
                {
                    "credential_broker_present": True,
                    "credential_broker_authentication": INHERITED_UNFORGEABLE_CAPABILITY,
                    "credential_broker_capability_visible_to_interactive_user": True,
                },
                "CREDENTIAL_BROKER_CAPABILITY_VISIBLE_TO_INTERACTIVE_USER",
            ),
        )
        for changes, blocker in cases:
            with self.subTest(blocker=blocker):
                result = evaluate_runtime_writer_boundary(
                    policy=self.policy(),
                    proposal=self.proposal(processes=processes, **changes),
                )
                self.assertEqual(BLOCKED, result.status)
                self.assertIn(blocker, result.blockers)

    def test_credentials_cannot_be_persisted_for_writer_or_visible_to_wpf(self):
        for field, blocker in (
            ("credential_material_persisted_for_writer", "WRITER_CREDENTIAL_MATERIAL_PERSISTED"),
            ("credential_material_visible_to_wpf", "CREDENTIAL_MATERIAL_VISIBLE_TO_WPF"),
        ):
            with self.subTest(field=field):
                result = evaluate_runtime_writer_boundary(
                    policy=self.policy(),
                    proposal=self.proposal(**{field: True}),
                )
                self.assertEqual(BLOCKED, result.status)
                self.assertIn(blocker, result.blockers)

    def test_unused_credential_broker_or_reprovisioning_configuration_is_blocked(self):
        cases = (
            (
                {
                    "credential_broker_present": True,
                    "credential_broker_authentication": INHERITED_UNFORGEABLE_CAPABILITY,
                },
                "CREDENTIAL_BROKER_CONFIGURATION_UNEXPECTED",
            ),
            (
                {"credential_reprovisioning_approved": True},
                "CREDENTIAL_REPROVISIONING_CONFIGURATION_UNEXPECTED",
            ),
        )
        for changes, blocker in cases:
            with self.subTest(blocker=blocker):
                result = evaluate_runtime_writer_boundary(
                    policy=self.policy(),
                    proposal=self.proposal(**changes),
                )
                self.assertEqual(BLOCKED, result.status)
                self.assertIn(blocker, result.blockers)

    def test_root_security_policy_identity_must_match(self):
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=self.proposal(root_security_policy_fingerprint="b" * 64),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("ROOT_SECURITY_POLICY_MISMATCH", result.blockers)

    def test_process_roles_are_complete_unique_and_consistent(self):
        with self.assertRaisesRegex(RuntimeWriterBoundaryError, "each required role"):
            self.proposal(processes=self.dedicated_writer_processes()[:-1])
        inconsistent = list(self.distinct_host_processes())
        inconsistent[3] = replace(inconsistent[3], principal_sid=WRITER)
        with self.assertRaisesRegex(RuntimeWriterBoundaryError, "identical process facts"):
            self.proposal(
                boundary_kind=DISTINCT_ENGINE_HOST_PRINCIPAL,
                processes=tuple(inconsistent),
            )

    def test_malformed_sid_boolean_and_fingerprint_fail_closed(self):
        processes = list(self.dedicated_writer_processes())
        processes[3] = replace(processes[3], principal_sid="not-a-sid")
        with self.assertRaisesRegex(RuntimeWriterBoundaryError, "Windows SID"):
            self.proposal(processes=tuple(processes))
        with self.assertRaisesRegex(RuntimeWriterBoundaryError, "must be boolean"):
            self.proposal(channel_capability_persisted=1)
        with self.assertRaisesRegex(RuntimeWriterBoundaryError, "SHA-256"):
            self.proposal(root_security_policy_fingerprint="short")

    def test_fingerprints_are_deterministic_and_tampering_is_rejected(self):
        first = self.proposal()
        second = self.proposal(processes=tuple(reversed(self.dedicated_writer_processes())))
        self.assertEqual(first, second)
        with self.assertRaisesRegex(RuntimeWriterBoundaryError, "fingerprint is invalid"):
            validate_runtime_writer_boundary_proposal(
                replace(first, source_identity="TAMPERED")
            )
        result = evaluate_runtime_writer_boundary(
            policy=self.policy(),
            proposal=first,
        )
        with self.assertRaisesRegex(RuntimeWriterBoundaryError, "cannot authorize activation"):
            validate_runtime_writer_boundary_result(
                replace(result, activation_authorized=True)
            )
        with self.assertRaisesRegex(RuntimeWriterBoundaryError, "fingerprint is invalid"):
            validate_runtime_writer_boundary_result(
                replace(result, proposal_fingerprint="b" * 64)
            )

    def test_module_has_no_os_network_process_secret_or_activation_capability(self):
        source_path = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "event_runtime_writer_boundary.py"
        )
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(
            imports.isdisjoint(
                {
                    "ctypes",
                    "os",
                    "pathlib",
                    "requests",
                    "socket",
                    "subprocess",
                    "urllib",
                    "win32api",
                    "win32security",
                }
            )
        )
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertTrue(
            names.isdisjoint(
                {
                    "LocalSecretStore",
                    "WindowsDpapiProtector",
                    "submit_order",
                    "start_service",
                    "create_user",
                    "set_acl",
                }
            )
        )


if __name__ == "__main__":
    unittest.main()
