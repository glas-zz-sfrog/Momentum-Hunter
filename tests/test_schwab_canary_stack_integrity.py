from __future__ import annotations

import ast
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

import momentum_hunter.schwab_canary_stack_integrity as integrity_module
from momentum_hunter.schwab_canary_stack_integrity import (
    CANARY_STACK_COMPONENTS,
    CANARY_STACK_COMPONENTS_V1,
    CANARY_STACK_COMPONENTS_V2,
    CANARY_STACK_INTEGRITY_SCHEMA_VERSION,
    CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V1,
    CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V2,
    CanaryStackIntegrityError,
    build_canary_stack_integrity_manifest,
    canonical_manifest_json,
    verify_canary_stack_integrity_manifest,
)


UTC = timezone.utc
CREATED_AT = datetime(2026, 7, 27, 22, 0, tzinfo=UTC)
BUILD_IDENTITY = "a" * 40
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class CanaryStackIntegrityTests(unittest.TestCase):
    def test_current_canary_stack_builds_and_revalidates_exact_manifest(self) -> None:
        manifest = self.build_manifest(REPOSITORY_ROOT)

        findings = self.verify(manifest, REPOSITORY_ROOT)

        self.assertEqual((), findings)
        self.assertEqual(
            CANARY_STACK_INTEGRITY_SCHEMA_VERSION,
            manifest["schemaVersion"],
        )
        self.assertEqual(17, manifest["componentCount"])
        self.assertEqual(len(CANARY_STACK_COMPONENTS), manifest["componentCount"])
        expected_names = [
            *(f"CANARY-{index:03d}" for index in range(1, 14)),
            *(f"CANARY-{index:03d}" for index in range(15, 19)),
        ]
        self.assertEqual(
            expected_names,
            [item.name for item in CANARY_STACK_COMPONENTS],
        )
        self.assertEqual(
            expected_names,
            [item["name"] for item in manifest["components"]],
        )
        self.assertTrue(manifest["integrationOnly"])
        self.assertFalse(manifest["providerEvidence"])
        self.assertFalse(manifest["executionPermit"])
        self.assertFalse(manifest["brokerActionAllowed"])
        self.assertFalse(manifest["retryAllowed"])
        self.assertFalse(manifest["transmitting"])
        self.assertEqual("UNAVAILABLE", manifest["orderTransmission"])
        self.assertEqual(
            canonical_manifest_json(manifest),
            canonical_manifest_json(deepcopy(manifest)),
        )

    def test_legacy_v1_manifest_policy_remains_explicitly_verifiable(self) -> None:
        manifest = build_canary_stack_integrity_manifest(
            repository_root=REPOSITORY_ROOT,
            build_identity=BUILD_IDENTITY,
            created_at=CREATED_AT,
            components=CANARY_STACK_COMPONENTS_V1,
        )

        findings = verify_canary_stack_integrity_manifest(
            manifest,
            repository_root=REPOSITORY_ROOT,
            expected_build_identity=BUILD_IDENTITY,
            evaluated_at=CREATED_AT,
            components=CANARY_STACK_COMPONENTS_V1,
        )
        default_findings = self.verify(manifest, REPOSITORY_ROOT)

        self.assertEqual((), findings)
        self.assertEqual(
            CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V1,
            manifest["schemaVersion"],
        )
        self.assertEqual(10, manifest["componentCount"])
        self.assertEqual(
            [f"CANARY-{index:03d}" for index in range(1, 11)],
            [item["name"] for item in manifest["components"]],
        )
        self.assertIn(
            "Canary stack integrity schema is unsupported.",
            default_findings,
        )
        self.assertIn(
            "Canary stack component count does not match policy.",
            default_findings,
        )

    def test_legacy_v2_manifest_policy_remains_explicitly_verifiable(self) -> None:
        manifest = build_canary_stack_integrity_manifest(
            repository_root=REPOSITORY_ROOT,
            build_identity=BUILD_IDENTITY,
            created_at=CREATED_AT,
            components=CANARY_STACK_COMPONENTS_V2,
        )

        findings = verify_canary_stack_integrity_manifest(
            manifest,
            repository_root=REPOSITORY_ROOT,
            expected_build_identity=BUILD_IDENTITY,
            evaluated_at=CREATED_AT,
            components=CANARY_STACK_COMPONENTS_V2,
        )
        default_findings = self.verify(manifest, REPOSITORY_ROOT)

        self.assertEqual((), findings)
        self.assertEqual(
            CANARY_STACK_INTEGRITY_SCHEMA_VERSION_V2,
            manifest["schemaVersion"],
        )
        self.assertEqual(13, manifest["componentCount"])
        self.assertEqual(
            [f"CANARY-{index:03d}" for index in range(1, 14)],
            [item["name"] for item in manifest["components"]],
        )
        self.assertIn(
            "Canary stack integrity schema is unsupported.",
            default_findings,
        )
        self.assertIn(
            "Canary stack component count does not match policy.",
            default_findings,
        )

    def test_manifest_build_and_verify_do_not_mutate_stack_sources(self) -> None:
        before = {
            component.relative_path: (
                REPOSITORY_ROOT / component.relative_path
            ).read_bytes()
            for component in CANARY_STACK_COMPONENTS
        }

        manifest = self.build_manifest(REPOSITORY_ROOT)
        self.verify(manifest, REPOSITORY_ROOT)

        after = {
            component.relative_path: (
                REPOSITORY_ROOT / component.relative_path
            ).read_bytes()
            for component in CANARY_STACK_COMPONENTS
        }
        self.assertEqual(before, after)

    def test_changed_component_fingerprint_fails_revalidation(self) -> None:
        with self.stack_copy() as root:
            manifest = self.build_manifest(root)
            component_path = root / CANARY_STACK_COMPONENTS[0].relative_path
            component_path.write_text(
                component_path.read_text(encoding="utf-8") + "\n# changed\n",
                encoding="utf-8",
            )

            findings = self.verify(manifest, root)

        self.assertIn("CANARY-001 content fingerprint changed.", findings)
        self.assertIn("CANARY-001 byte count changed.", findings)

    def test_missing_component_fails_closed(self) -> None:
        with self.stack_copy() as root:
            manifest = self.build_manifest(root)
            target = root / CANARY_STACK_COMPONENTS[-1].relative_path
            target.unlink()

            findings = self.verify(manifest, root)

        self.assertTrue(
            any("CANARY-018 cannot be re-read" in item for item in findings)
        )

    def test_unsafe_import_action_and_endpoint_cannot_build_manifest(self) -> None:
        unsafe_fragments = (
            "import requests\n",
            "def submit_order():\n    return None\n",
            "def revoke():\n    return None\n",
            "def terminate():\n    return None\n",
            "def urlopen():\n    return None\n",
            "UNSAFE_ENDPOINT = 'https://broker.invalid/order'\n",
        )
        for fragment in unsafe_fragments:
            with self.subTest(fragment=fragment), self.stack_copy() as root:
                target = root / CANARY_STACK_COMPONENTS[-1].relative_path
                target.write_text(
                    target.read_text(encoding="utf-8") + "\n" + fragment,
                    encoding="utf-8",
                )
                with self.assertRaises(CanaryStackIntegrityError):
                    self.build_manifest(root)

    def test_offline_url_parser_exception_is_exact_and_component_scoped(
        self,
    ) -> None:
        manifest = self.build_manifest(REPOSITORY_ROOT)
        self.assertEqual((), self.verify(manifest, REPOSITORY_ROOT))

        with self.stack_copy() as root:
            schema_component = next(
                item
                for item in CANARY_STACK_COMPONENTS
                if item.name == "CANARY-011"
            )
            self.assertEqual(("urllib.parse",), schema_component.allowed_imports)
            self.assertEqual(("urlparse",), schema_component.allowed_actions)
            target = root / schema_component.relative_path
            target.write_text(
                target.read_text(encoding="utf-8")
                + "\nimport urllib.request\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CanaryStackIntegrityError,
                "urllib.request",
            ):
                self.build_manifest(root)

        widened = list(CANARY_STACK_COMPONENTS)
        widened[-1] = replace(
            widened[-1],
            allowed_imports=("urllib.parse",),
        )
        with self.assertRaisesRegex(
            CanaryStackIntegrityError,
            "import exceptions do not match policy",
        ):
            build_canary_stack_integrity_manifest(
                repository_root=REPOSITORY_ROOT,
                build_identity=BUILD_IDENTITY,
                created_at=CREATED_AT,
                components=widened,
            )

    def test_worker_launch_exception_is_exact_and_component_scoped(self) -> None:
        lifecycle_component = next(
            item
            for item in CANARY_STACK_COMPONENTS
            if item.name == "CANARY-017"
        )
        self.assertEqual(("subprocess",), lifecycle_component.allowed_imports)
        self.assertEqual(("Popen",), lifecycle_component.allowed_actions)
        self.assertEqual(
            (),
            self.verify(
                self.build_manifest(REPOSITORY_ROOT),
                REPOSITORY_ROOT,
            ),
        )

        unsafe_calls = (
            "subprocess.run(['python', '--version'])",
            "subprocess.check_output(['python', '--version'])",
            "__import__('subprocess').Popen(['python', '--version'])",
        )
        for unsafe_call in unsafe_calls:
            with self.subTest(unsafe_call=unsafe_call), self.stack_copy() as root:
                target = root / lifecycle_component.relative_path
                target.write_text(
                    target.read_text(encoding="utf-8")
                    + "\ndef unsafe_process_action():\n"
                    + f"    return {unsafe_call}\n",
                    encoding="utf-8",
                )
                with self.assertRaises(CanaryStackIntegrityError):
                    self.build_manifest(root)

        with self.stack_copy() as root:
            target = root / lifecycle_component.relative_path
            target.write_text(
                target.read_text(encoding="utf-8")
                + "\nimport subprocess as process_runner\n"
                + "def unsafe_aliased_process_action():\n"
                + "    return process_runner.check_call(['python', '--version'])\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CanaryStackIntegrityError,
                "check_call",
            ):
                self.build_manifest(root)

        widened = list(CANARY_STACK_COMPONENTS)
        widened[-1] = replace(
            widened[-1],
            allowed_actions=("Popen",),
        )
        with self.assertRaisesRegex(
            CanaryStackIntegrityError,
            "action exceptions do not match policy",
        ):
            build_canary_stack_integrity_manifest(
                repository_root=REPOSITORY_ROOT,
                build_identity=BUILD_IDENTITY,
                created_at=CREATED_AT,
                components=widened,
            )

    def test_authority_and_provider_escalation_fail_revalidation(self) -> None:
        manifest = self.build_manifest(REPOSITORY_ROOT)
        variants = []
        for field, value in (
            ("integrationOnly", False),
            ("providerEvidence", True),
            ("executionPermit", True),
            ("brokerActionAllowed", True),
            ("retryAllowed", True),
            ("transmitting", True),
            ("orderTransmission", "AVAILABLE"),
        ):
            changed = deepcopy(manifest)
            changed[field] = value
            variants.append((field, changed))

        for field, variant in variants:
            with self.subTest(field=field):
                findings = self.verify(variant, REPOSITORY_ROOT)
                self.assertIn(
                    f"Canary stack authority boundary changed: {field}.",
                    findings,
                )

    def test_component_path_escape_and_unallowlisted_component_fail(self) -> None:
        manifest = self.build_manifest(REPOSITORY_ROOT)
        escaped = deepcopy(manifest)
        escaped["components"][0]["path"] = "../outside.py"
        extra = deepcopy(manifest)
        extra["components"].append(
            {
                "name": "CANARY-999",
                "role": "unsafe",
                "path": "momentum_hunter/unsafe.py",
                "sha256": "0" * 64,
                "sizeBytes": 0,
                "sourceReview": "PASS_NONTRANSMITTING_STATIC_BOUNDARY",
            }
        )
        extra["componentCount"] += 1

        escaped_findings = self.verify(escaped, REPOSITORY_ROOT)
        extra_findings = self.verify(extra, REPOSITORY_ROOT)

        self.assertIn("CANARY-001 path does not match policy.", escaped_findings)
        self.assertTrue(
            any("not allowlisted" in item for item in extra_findings)
        )
        self.assertIn(
            "Canary stack component count does not match policy.",
            extra_findings,
        )

    def test_duplicate_missing_and_aggregate_tamper_fail(self) -> None:
        manifest = self.build_manifest(REPOSITORY_ROOT)
        duplicate = deepcopy(manifest)
        duplicate["components"][1] = deepcopy(duplicate["components"][0])
        changed_digest = deepcopy(manifest)
        changed_digest["stackSha256"] = "0" * 64

        duplicate_findings = self.verify(duplicate, REPOSITORY_ROOT)
        digest_findings = self.verify(changed_digest, REPOSITORY_ROOT)

        self.assertTrue(
            any("duplicated" in item for item in duplicate_findings)
        )
        self.assertTrue(
            any(
                "required components are missing" in item
                for item in duplicate_findings
            )
        )
        self.assertIn(
            "Canary stack aggregate fingerprint does not match.",
            digest_findings,
        )

    def test_wrong_build_identity_future_and_expired_manifest_fail(self) -> None:
        manifest = self.build_manifest(REPOSITORY_ROOT)
        wrong_build = self.verify(
            manifest,
            REPOSITORY_ROOT,
            expected_build_identity="b" * 40,
        )
        future = self.verify(
            manifest,
            REPOSITORY_ROOT,
            evaluated_at=CREATED_AT - timedelta(seconds=1),
        )
        expired = self.verify(
            manifest,
            REPOSITORY_ROOT,
            evaluated_at=CREATED_AT + timedelta(days=2),
        )

        self.assertIn(
            "Canary stack build identity does not match.",
            wrong_build,
        )
        self.assertIn("Canary stack manifest is future-dated.", future)
        self.assertIn(
            "Canary stack manifest is older than the allowed integration window.",
            expired,
        )

    def test_malformed_manifest_and_component_policy_fail_closed(self) -> None:
        self.assertEqual(
            ("Canary stack integrity manifest is missing or malformed.",),
            self.verify(None, REPOSITORY_ROOT),
        )
        with self.assertRaisesRegex(
            CanaryStackIntegrityError,
            "cannot be empty",
        ):
            build_canary_stack_integrity_manifest(
                repository_root=REPOSITORY_ROOT,
                build_identity=BUILD_IDENTITY,
                created_at=CREATED_AT,
                components=(),
            )
        with self.assertRaisesRegex(
            CanaryStackIntegrityError,
            "frozen policy version",
        ):
            build_canary_stack_integrity_manifest(
                repository_root=REPOSITORY_ROOT,
                build_identity=BUILD_IDENTITY,
                created_at=CREATED_AT,
                components=CANARY_STACK_COMPONENTS[:-1],
            )

    def test_verifier_has_no_git_network_credential_or_broker_action_capability(
        self,
    ) -> None:
        source = inspect.getsource(integrity_module)
        tree = ast.parse(source)
        imports: set[str] = set()
        functions: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.add(node.name)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)

        self.assertFalse(
            imports
            & {
                "git",
                "requests",
                "httpx",
                "urllib",
                "socket",
                "subprocess",
                "momentum_hunter.schwab_onboarding",
                "momentum_hunter.schwab_market_data",
            }
        )
        forbidden = {
            "preview_order",
            "submit_order",
            "place_order",
            "replace_order",
            "cancel_order",
            "transmit_order",
            "transfer_money",
            "withdraw",
        }
        self.assertFalse(functions & forbidden)
        self.assertFalse(calls & forbidden)
        lowered = source.lower()
        self.assertNotIn("api_key", lowered)
        self.assertNotIn("client_secret", lowered)
        self.assertNotIn("access_token", lowered)
        self.assertNotIn("refresh_token", lowered)

    def build_manifest(self, root: Path) -> dict[str, object]:
        return build_canary_stack_integrity_manifest(
            repository_root=root,
            build_identity=BUILD_IDENTITY,
            created_at=CREATED_AT,
        )

    def verify(
        self,
        manifest: object,
        root: Path,
        *,
        expected_build_identity: str = BUILD_IDENTITY,
        evaluated_at: datetime = CREATED_AT,
    ) -> tuple[str, ...]:
        return verify_canary_stack_integrity_manifest(
            manifest,
            repository_root=root,
            expected_build_identity=expected_build_identity,
            evaluated_at=evaluated_at,
        )

    def stack_copy(self):
        temporary = TemporaryDirectory()
        root = Path(temporary.name)
        for component in CANARY_STACK_COMPONENTS:
            source = REPOSITORY_ROOT / component.relative_path
            destination = root / component.relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        return _TemporaryStack(temporary, root)


class _TemporaryStack:
    def __init__(self, temporary: TemporaryDirectory, root: Path) -> None:
        self._temporary = temporary
        self._root = root

    def __enter__(self) -> Path:
        return self._root

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
