from __future__ import annotations

import ast
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from momentum_hunter.event_runtime_root_security import (
    APPEND,
    BLOCKED,
    CHANGE_PERMISSIONS,
    CONTRACT_ELIGIBLE,
    CREATE_CHILD,
    DELETE,
    DELETE_CHILD,
    READ,
    TAKE_OWNERSHIP,
    TRAVERSE,
    WRITE,
    RuntimePathSecurityEvidence,
    RuntimePrincipalAccess,
    RuntimeRootSecurityError,
    build_runtime_root_security_policy,
    build_runtime_root_security_snapshot,
    evaluate_runtime_root_security,
    validate_runtime_root_security_result,
)


BASE = r"C:\ProgramData\MomentumHunter"
ROOT = BASE + r"\EventRuntime"
WRITER = "S-1-5-21-100-200-300-4101"
INTERACTIVE = "S-1-5-21-100-200-300-1001"
EVERYONE = "S-1-1-0"
USERS = "S-1-5-32-545"
SYSTEM = "S-1-5-18"
ADMINISTRATORS = "S-1-5-32-544"
TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
OBSERVED = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)


class EventRuntimeRootSecurityTests(unittest.TestCase):
    def policy(self, **changes):
        values = {
            "policy_version": "synthetic-root-policy-v1",
            "approved_base_path": BASE,
            "writer_principal_sid": WRITER,
            "interactive_principal_sids": (INTERACTIVE,),
            "broad_principal_sids": (EVERYONE, USERS),
            "trusted_owner_sids": (SYSTEM, ADMINISTRATORS, TRUSTED_INSTALLER),
        }
        values.update(changes)
        return build_runtime_root_security_policy(**values)

    def access(self, principal: str, *rights: str) -> RuntimePrincipalAccess:
        return RuntimePrincipalAccess(principal, tuple(rights))

    def component(
        self,
        path: str,
        *,
        root: bool = False,
        owner: str = SYSTEM,
        dacl_protected: bool | None = None,
        reparse: bool = False,
        symlink: bool = False,
        exists: bool = True,
        is_directory: bool = True,
        writer_rights: tuple[str, ...] | None = None,
        interactive_rights: tuple[str, ...] = (READ, TRAVERSE),
        everyone_rights: tuple[str, ...] = (READ, TRAVERSE),
        users_rights: tuple[str, ...] = (READ, TRAVERSE),
    ) -> RuntimePathSecurityEvidence:
        writer = writer_rights or (
            APPEND,
            CREATE_CHILD,
            DELETE,
            DELETE_CHILD,
            READ,
            TRAVERSE,
            WRITE,
        )
        return RuntimePathSecurityEvidence(
            path=path,
            exists=exists,
            is_directory=is_directory,
            is_symlink=symlink,
            is_reparse_point=reparse,
            owner_sid=owner,
            dacl_protected=root if dacl_protected is None else dacl_protected,
            principal_access=(
                self.access(WRITER, *writer),
                self.access(INTERACTIVE, *interactive_rights),
                self.access(EVERYONE, *everyone_rights),
                self.access(USERS, *users_rights),
            ),
        )

    def components(self, **root_changes):
        return (
            self.component("C:\\"),
            self.component(r"C:\ProgramData"),
            self.component(BASE),
            self.component(ROOT, root=True, **root_changes),
        )

    def snapshot(self, *, root_path: str = ROOT, components=None):
        return build_runtime_root_security_snapshot(
            root_path=root_path,
            source_identity="SYNTHETIC_EFFECTIVE_ACCESS_FIXTURE",
            observed_at=OBSERVED,
            components=self.components() if components is None else components,
        )

    def test_distinct_writer_and_hardened_root_are_contract_eligible_only(self) -> None:
        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(),
        )

        self.assertEqual(CONTRACT_ELIGIBLE, result.status)
        self.assertEqual((), result.blockers)
        self.assertFalse(result.activation_authorized)
        self.assertEqual("DORMANT_CONTRACT_ONLY", result.authority)
        self.assertRegex(result.fingerprint, r"^[0-9a-f]{64}$")

    def test_same_writer_and_interactive_sid_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeRootSecurityError, "must be distinct"):
            self.policy(writer_principal_sid=INTERACTIVE)

    def test_writer_or_nonwriter_cannot_be_a_trusted_owner(self) -> None:
        with self.assertRaisesRegex(RuntimeRootSecurityError, "cannot own"):
            self.policy(trusted_owner_sids=(SYSTEM, WRITER))
        with self.assertRaisesRegex(RuntimeRootSecurityError, "Nonwriter"):
            self.policy(trusted_owner_sids=(SYSTEM, INTERACTIVE))

    def test_current_same_user_service_host_model_cannot_claim_acl_isolation(self) -> None:
        current_user = "S-1-5-21-100-200-300-1001"

        with self.assertRaisesRegex(RuntimeRootSecurityError, "must be distinct"):
            self.policy(
                writer_principal_sid=current_user,
                interactive_principal_sids=(current_user,),
            )

    def test_root_reparse_or_symlink_component_blocks(self) -> None:
        for changes in ({"reparse": True}, {"symlink": True}):
            with self.subTest(changes=changes):
                result = evaluate_runtime_root_security(
                    policy=self.policy(),
                    snapshot=self.snapshot(components=self.components(**changes)),
                )
                self.assertEqual(BLOCKED, result.status)
                self.assertIn("ROOT_REPARSE_OR_SYMLINK", result.blockers)

    def test_ancestor_reparse_blocks_even_when_root_acl_is_hardened(self) -> None:
        components = list(self.components())
        components[2] = self.component(BASE, reparse=True)

        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(components=tuple(components)),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertIn("ANCESTOR_2_REPARSE_OR_SYMLINK", result.blockers)

    def test_root_inheritance_or_nonwriter_write_access_blocks(self) -> None:
        components = self.components(
            dacl_protected=False,
            interactive_rights=(READ, TRAVERSE, WRITE),
            everyone_rights=(READ, TRAVERSE, CREATE_CHILD),
        )

        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(components=components),
        )

        self.assertIn("ROOT_DACL_INHERITANCE_ENABLED", result.blockers)
        self.assertTrue(
            any(item.startswith("ROOT_NONWRITER_MUTATION:") for item in result.blockers)
        )

    def test_ancestor_delete_child_or_acl_control_blocks_replacement(self) -> None:
        components = list(self.components())
        components[1] = self.component(
            r"C:\ProgramData",
            interactive_rights=(READ, TRAVERSE, DELETE_CHILD),
            users_rights=(READ, TRAVERSE, CHANGE_PERMISSIONS, TAKE_OWNERSHIP),
        )

        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(components=tuple(components)),
        )

        self.assertEqual(BLOCKED, result.status)
        self.assertTrue(
            any(
                item.startswith("ANCESTOR_REPLACEMENT_ACCESS:")
                for item in result.blockers
            )
        )

    def test_missing_writer_rights_block_atomic_append_boundary(self) -> None:
        rights = (APPEND, CREATE_CHILD, READ, TRAVERSE, WRITE)

        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(
                components=self.components(writer_rights=rights)
            ),
        )

        self.assertIn("WRITER_RIGHTS_MISSING:DELETE,DELETE_CHILD", result.blockers)

    def test_writer_acl_or_ownership_control_blocks(self) -> None:
        rights = (
            APPEND,
            CHANGE_PERMISSIONS,
            CREATE_CHILD,
            DELETE,
            DELETE_CHILD,
            READ,
            TAKE_OWNERSHIP,
            TRAVERSE,
            WRITE,
        )

        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(
                components=self.components(writer_rights=rights)
            ),
        )

        self.assertIn(
            "WRITER_SECURITY_CONTROL_PRESENT:CHANGE_PERMISSIONS,TAKE_OWNERSHIP",
            result.blockers,
        )

    def test_nonboolean_path_evidence_is_rejected(self) -> None:
        components = list(self.components())
        components[-1] = replace(components[-1], exists=1)

        with self.assertRaisesRegex(RuntimeRootSecurityError, "must be boolean"):
            self.snapshot(components=tuple(components))

    def test_missing_effective_access_evidence_fails_closed(self) -> None:
        components = list(self.components())
        root = components[-1]
        components[-1] = replace(
            root,
            principal_access=tuple(
                item for item in root.principal_access if item.principal_sid != EVERYONE
            ),
        )

        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(components=tuple(components)),
        )

        self.assertIn(f"ROOT_ACCESS_EVIDENCE_MISSING:{EVERYONE}", result.blockers)

    def test_untrusted_owner_missing_root_and_file_shape_block(self) -> None:
        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(
                components=self.components(
                    owner=INTERACTIVE,
                    exists=False,
                    is_directory=False,
                )
            ),
        )

        self.assertIn("ROOT_MISSING", result.blockers)
        self.assertIn("ROOT_NOT_DIRECTORY", result.blockers)
        self.assertIn("ROOT_OWNER_UNTRUSTED", result.blockers)

    def test_root_must_be_strict_descendant_with_complete_component_chain(self) -> None:
        outside = r"C:\Other\EventRuntime"
        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(root_path=outside),
        )

        self.assertIn("ROOT_OUTSIDE_APPROVED_DESCENDANT", result.blockers)
        self.assertIn("PATH_COMPONENT_CHAIN_INCOMPLETE", result.blockers)

        base_result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=self.snapshot(root_path=BASE),
        )
        self.assertIn("ROOT_OUTSIDE_APPROVED_DESCENDANT", base_result.blockers)

    def test_unc_relative_and_parent_traversal_paths_are_rejected(self) -> None:
        for path in ("relative", r"\\server\share\root", BASE + r"\..\escape"):
            with self.subTest(path=path):
                with self.assertRaises(RuntimeRootSecurityError):
                    self.snapshot(root_path=path)

    def test_snapshot_and_result_tampering_are_rejected(self) -> None:
        snapshot = self.snapshot()
        with self.assertRaisesRegex(RuntimeRootSecurityError, "fingerprint"):
            evaluate_runtime_root_security(
                policy=self.policy(),
                snapshot=replace(snapshot, fingerprint="0" * 64),
            )

        result = evaluate_runtime_root_security(
            policy=self.policy(),
            snapshot=snapshot,
        )
        with self.assertRaisesRegex(RuntimeRootSecurityError, "fingerprint"):
            validate_runtime_root_security_result(
                replace(result, fingerprint="0" * 64)
            )
        with self.assertRaisesRegex(RuntimeRootSecurityError, "cannot authorize"):
            validate_runtime_root_security_result(
                replace(result, activation_authorized=True, fingerprint="0" * 64)
            )

    def test_deterministic_inputs_produce_identical_results(self) -> None:
        policy = self.policy()
        snapshot = self.snapshot()

        self.assertEqual(
            evaluate_runtime_root_security(policy=policy, snapshot=snapshot),
            evaluate_runtime_root_security(policy=policy, snapshot=snapshot),
        )

    def test_module_has_no_filesystem_acl_network_service_or_broker_capability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        module_path = root / "momentum_hunter" / "event_runtime_root_security.py"
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
                imports.add(node.module.rsplit(".", 1)[-1])
        self.assertTrue(
            imports.isdisjoint(
                {
                    "os",
                    "ctypes",
                    "subprocess",
                    "win32security",
                    "requests",
                    "urllib",
                    "httpx",
                    "socket",
                    "alpaca_paper",
                    "schwab_market_data",
                    "shadow_trading",
                    "automation_supervisor",
                    "engine_host",
                }
            )
        )
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            calls.isdisjoint(
                {
                    "mkdir",
                    "write_text",
                    "write_bytes",
                    "chmod",
                    "submit_order",
                    "cancel_order",
                    "replace_order",
                    "get_account",
                    "get_positions",
                    "start_service",
                    "start_host",
                }
            )
        )

    def test_no_existing_runtime_imports_root_security_contract(self) -> None:
        root = Path(__file__).resolve().parents[1] / "momentum_hunter"
        importers = []
        for path in root.rglob("*.py"):
            if path.name == "event_runtime_root_security.py":
                continue
            if "event_runtime_root_security" in path.read_text(encoding="utf-8"):
                importers.append(path.name)
        self.assertEqual([], importers)


if __name__ == "__main__":
    unittest.main()
