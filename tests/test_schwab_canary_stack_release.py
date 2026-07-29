from __future__ import annotations

import ast
from dataclasses import replace
from datetime import datetime, timezone
import inspect
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import momentum_hunter.schwab_canary_stack_release as release_module
from momentum_hunter.pending_foundation_release_gate import (
    PendingFoundationReleasePolicy,
    SourceCommitPolicy,
)
from momentum_hunter.schwab_canary_stack_integrity import (
    CANARY_STACK_COMPONENTS,
    CANARY_STACK_INTEGRITY_SCHEMA_VERSION,
)
from momentum_hunter.schwab_canary_stack_release import (
    CANARY_021_REVIEWED_SOURCE_COMMIT,
    CURRENT_CANARY_STACK_BASELINE_COMMIT,
    CURRENT_CANARY_STACK_BASELINE_REMOTE_REF,
    CURRENT_CANARY_STACK_RELEASE_BRANCH,
    DEFAULT_FINAL_CANARY_STACK_POLICY,
    FINAL_CANARY_STACK_RELEASE_SCHEMA,
    HISTORICAL_CANARY_STACK_SOURCE_COMMIT,
    REVIEWED_CANARY_STACK_SOURCE_COMMIT,
    evaluate_final_canary_stack_release,
    render_final_canary_stack_release,
)


EVALUATED_AT = datetime(2026, 7, 28, 7, 30, tzinfo=timezone.utc)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BRANCH = "codex/ARGUS-SCHWAB-004-account-shape-evidence-test"
OWNED_PATHS = (
    "momentum_hunter/release_gate.py",
    "tests/test_release_gate.py",
    "tools/verify_release_gate.py",
)
REVIEWED_TOOL_PATH = "tools/reviewed_stack_verifier.py"


class FinalCanaryStackReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-b", "master")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Momentum Hunter Tests")
        self.git("remote", "add", "origin", ".")
        self.write("AGENTS.md", "base\n")
        self.commit("base")
        self.base = self.head()
        self.git("update-ref", "refs/remotes/origin/master", self.base)

        self.git("switch", "-c", "reviewed/canary-stack")
        for component in CANARY_STACK_COMPONENTS:
            self.copy_component(component.relative_path)
        self.write(
            "docs/argus-office/ROADMAP.md",
            "reviewed stack roadmap\n",
        )
        self.write(REVIEWED_TOOL_PATH, "REVIEWED_TOOL = True\n")
        self.commit("reviewed stack")
        self.source = self.head()

        self.git("switch", "master")
        self.git("switch", "-c", BRANCH)
        for component in CANARY_STACK_COMPONENTS:
            self.checkout_file(
                self.source,
                component.relative_path,
            )
        self.checkout_file(self.source, REVIEWED_TOOL_PATH)
        self.write(
            "docs/argus-office/ROADMAP.md",
            "reconciled stack roadmap\n",
        )
        for path in OWNED_PATHS:
            self.write(path, "RELEASE_GATE = True\n")
        self.commit("final release gate")
        self.sync_upstream()
        self.policy = PendingFoundationReleasePolicy(
            base_ref="master",
            remote_base_ref="origin/master",
            allowed_branch_prefix=BRANCH,
            source_commits=(
                SourceCommitPolicy(
                    ref="reviewed/canary-stack",
                    commit=self.source,
                ),
            ),
            integration_owned_paths=OWNED_PATHS,
            equivalent_prefixes=(
                "momentum_hunter/",
                "tests/",
                "tools/",
            ),
        )

    def test_clean_synchronized_stack_emits_verified_v3_manifest(self) -> None:
        before_head = self.head()
        before_status = self.git("status", "--porcelain=v1").stdout

        result = self.evaluate()

        self.assertEqual("PASS", result["status"])
        self.assertEqual(FINAL_CANARY_STACK_RELEASE_SCHEMA, result["schemaVersion"])
        self.assertEqual([], result["findings"])
        self.assertEqual(before_head, result["head"])
        self.assertEqual(before_head, result["upstreamHead"])
        self.assertTrue(result["worktreeClean"])
        self.assertTrue(result["baseRemoteSynchronized"])
        self.assertTrue(result["branchUpstreamSynchronized"])
        self.assertTrue(result["exactSourcePathUnion"])
        self.assertTrue(result["runtimeTestEquivalent"])
        self.assertTrue(result["riskyPathsAbsent"])
        self.assertTrue(result["secretSignaturesAbsent"])
        self.assertTrue(result["stackManifestVerified"])
        self.assertEqual(64, len(result["stackManifestSha256"]))
        manifest = result["stackManifest"]
        self.assertEqual(
            CANARY_STACK_INTEGRITY_SCHEMA_VERSION,
            manifest["schemaVersion"],
        )
        self.assertEqual(18, manifest["componentCount"])
        self.assertFalse(result["gitMutationPerformed"])
        self.assertFalse(result["networkAccessed"])
        self.assertFalse(result["providerEvidence"])
        self.assertFalse(result["credentialsAccessed"])
        self.assertFalse(result["executionPermit"])
        self.assertFalse(result["brokerActionAllowed"])
        self.assertFalse(result["retryAllowed"])
        self.assertFalse(result["transmitting"])
        self.assertEqual("UNAVAILABLE", result["orderTransmission"])
        self.assertEqual(before_head, self.head())
        self.assertEqual(
            before_status,
            self.git("status", "--porcelain=v1").stdout,
        )

    def test_dirty_worktree_blocks_before_manifest_build(self) -> None:
        self.write("scratch.txt", "dirty\n")

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["worktreeClean"])
        self.assertFalse(result["stackManifestVerified"])
        self.assertIsNone(result["stackManifest"])

    def test_unpushed_head_blocks_before_manifest_build(self) -> None:
        self.write("docs/argus-office/ROADMAP.md", "new governance\n")
        self.commit("unpushed governance")

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Current branch and its upstream are not synchronized.",
            result["findings"],
        )
        self.assertFalse(result["branchUpstreamSynchronized"])
        self.assertIsNone(result["stackManifest"])

    def test_missing_upstream_blocks_before_manifest_build(self) -> None:
        self.git("branch", "--unset-upstream")

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Current branch upstream commit is unavailable.",
            result["findings"],
        )
        self.assertFalse(result["branchUpstreamSynchronized"])
        self.assertIsNone(result["stackManifest"])

    def test_lookalike_branch_name_fails_exact_release_check(self) -> None:
        lookalike = f"{BRANCH}-lookalike"
        self.git("switch", "-c", lookalike)
        self.git(
            "update-ref",
            f"refs/remotes/origin/{lookalike}",
            self.head(),
        )
        self.git(
            "branch",
            "--set-upstream-to",
            f"origin/{lookalike}",
        )

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Current branch is not the exact reviewed release branch.",
            result["findings"],
        )
        self.assertIsNone(result["stackManifest"])

    def test_runtime_drift_from_reviewed_source_fails_closed(self) -> None:
        target = CANARY_STACK_COMPONENTS[-1].relative_path
        self.write(
            target,
            (self.root / target).read_text(encoding="utf-8")
            + "\nCHANGED = True\n",
        )
        self.commit("runtime drift")
        self.sync_upstream()

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertFalse(result["runtimeTestEquivalent"])
        self.assertTrue(
            any(
                "differs from reviewed source" in finding
                for finding in result["findings"]
            )
        )
        self.assertIsNone(result["stackManifest"])

    def test_source_ref_and_base_drift_fail_closed(self) -> None:
        moved_source = replace(
            self.policy,
            source_commits=(
                SourceCommitPolicy(
                    ref="reviewed/canary-stack",
                    commit="0" * 40,
                ),
            ),
        )
        source_result = self.evaluate(policy=moved_source)
        self.git(
            "update-ref",
            "refs/remotes/origin/master",
            self.source,
        )
        base_result = self.evaluate()

        self.assertEqual("FAIL", source_result["status"])
        self.assertFalse(
            source_result["releaseGate"]["sourceRefsFrozen"]
        )
        self.assertEqual("FAIL", base_result["status"])
        self.assertFalse(base_result["baseRemoteSynchronized"])

    def test_default_policy_is_frozen_to_reviewed_stack_and_owned_paths(
        self,
    ) -> None:
        self.assertEqual(
            "b17fa6549ea239e9d807632e1c4c77abe474ab67",
            HISTORICAL_CANARY_STACK_SOURCE_COMMIT,
        )
        self.assertEqual(
            "249b2e8f4a6bf667a4900a5b97d98c2c6cf1d8db",
            CANARY_021_REVIEWED_SOURCE_COMMIT,
        )
        self.assertEqual(
            CURRENT_CANARY_STACK_RELEASE_BRANCH,
            DEFAULT_FINAL_CANARY_STACK_POLICY.allowed_branch_prefix,
        )
        self.assertEqual(
            CURRENT_CANARY_STACK_BASELINE_COMMIT,
            DEFAULT_FINAL_CANARY_STACK_POLICY.base_ref,
        )
        self.assertEqual(
            CURRENT_CANARY_STACK_BASELINE_REMOTE_REF,
            DEFAULT_FINAL_CANARY_STACK_POLICY.remote_base_ref,
        )
        self.assertEqual(
            REVIEWED_CANARY_STACK_SOURCE_COMMIT,
            DEFAULT_FINAL_CANARY_STACK_POLICY.source_commits[0].ref,
        )
        self.assertEqual(
            REVIEWED_CANARY_STACK_SOURCE_COMMIT,
            DEFAULT_FINAL_CANARY_STACK_POLICY.source_commits[0].commit,
        )
        self.assertEqual(
            (
                "momentum_hunter/schwab_canary_stack_release.py",
                "tests/test_schwab_canary_stack_release.py",
                "tools/verify_canary_stack_release.py",
            ),
            DEFAULT_FINAL_CANARY_STACK_POLICY.integration_owned_paths,
        )
        self.assertEqual(
            ("momentum_hunter/", "tests/", "tools/"),
            DEFAULT_FINAL_CANARY_STACK_POLICY.equivalent_prefixes,
        )

    def test_render_is_stable_json_without_authority(self) -> None:
        result = self.evaluate()

        rendered = render_final_canary_stack_release(result)

        self.assertEqual(rendered, render_final_canary_stack_release(result))
        self.assertIn('"status": "PASS"', rendered)
        self.assertIn('"orderTransmission": "UNAVAILABLE"', rendered)
        self.assertNotIn(str(self.root), rendered)

    def test_cli_can_start_directly_outside_repository(self) -> None:
        completed = subprocess.run(
            (
                sys.executable,
                "-B",
                str(
                    REPOSITORY_ROOT
                    / "tools"
                    / "verify_canary_stack_release.py"
                ),
                "--help",
            ),
            cwd=self.root,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn(
            "Verify the clean backed-up current-baseline canary stack",
            completed.stdout,
        )

    def test_module_has_no_provider_credential_or_broker_action(self) -> None:
        source = inspect.getsource(release_module)
        tree = ast.parse(source)
        imports: set[str] = set()
        actions: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                actions.add(node.name)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    actions.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    actions.add(node.func.attr)

        self.assertFalse(
            imports
            & {
                "httpx",
                "requests",
                "socket",
                "urllib",
                "momentum_hunter.schwab_onboarding",
                "momentum_hunter.schwab_readonly",
            }
        )
        self.assertFalse(
            actions
            & {
                "cancel_order",
                "delete_credentials",
                "kill",
                "place_order",
                "preview_order",
                "replace_order",
                "submit_order",
                "terminate",
                "transfer_money",
                "transmit_order",
                "withdraw",
            }
        )

    def evaluate(
        self,
        *,
        policy: PendingFoundationReleasePolicy | None = None,
    ) -> dict[str, object]:
        return evaluate_final_canary_stack_release(
            self.root,
            evaluated_at=EVALUATED_AT,
            policy=policy or self.policy,
        )

    def copy_component(self, relative_path: str) -> None:
        source = REPOSITORY_ROOT / relative_path
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def write(self, relative_path: str, content: str) -> None:
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def checkout_file(self, commit: str, relative_path: str) -> None:
        content = self.git("show", f"{commit}:{relative_path}").stdout
        self.write(relative_path, content)

    def commit(self, message: str) -> None:
        self.git("add", "--all")
        self.git("commit", "-m", message)

    def sync_upstream(self) -> None:
        remote_ref = f"refs/remotes/origin/{BRANCH}"
        self.git("update-ref", remote_ref, self.head())
        self.git(
            "branch",
            "--set-upstream-to",
            f"origin/{BRANCH}",
        )

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").stdout.strip()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("git", *arguments),
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )


if __name__ == "__main__":
    unittest.main()
