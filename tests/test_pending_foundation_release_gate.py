from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest

from momentum_hunter.pending_foundation_release_gate import (
    CommandResult,
    PendingFoundationReleaseGateError,
    PendingFoundationReleasePolicy,
    SourceCommitPolicy,
    evaluate_pending_foundation_release,
)


EVALUATED_AT = datetime(2026, 7, 28, 5, 0, tzinfo=timezone.utc)


class PendingFoundationReleaseGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "-b", "master")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "Momentum Hunter Tests")
        self.write("AGENTS.md", "base\n")
        self.commit("base")
        self.base = self.head()
        self.git("update-ref", "refs/remotes/origin/master", self.base)

        self.git("switch", "-c", "source/a")
        self.write("momentum_hunter/a.py", "VALUE = 'source-a'\n")
        self.write("docs/argus-office/ROADMAP.md", "source a roadmap\n")
        self.commit("source a")
        self.source_a = self.head()

        self.git("switch", "master")
        self.git("switch", "-c", "source/b")
        self.write("tests/test_b.py", "VALUE = 'source-b'\n")
        self.write("docs/argus-office/CHANGELOG_ARGUS.md", "source b changelog\n")
        self.commit("source b")
        self.source_b = self.head()

        self.git("switch", "master")
        self.git("switch", "-c", "codex/ARGUS-INTEGRATION-test")
        self.checkout_file(self.source_a, "momentum_hunter/a.py")
        self.checkout_file(self.source_b, "tests/test_b.py")
        self.write("docs/argus-office/ROADMAP.md", "reconciled roadmap\n")
        self.write(
            "docs/argus-office/CHANGELOG_ARGUS.md",
            "reconciled changelog\n",
        )
        self.write("momentum_hunter/gate.py", "GATE = True\n")
        self.write("tests/test_gate.py", "TEST_GATE = True\n")
        self.write("tools/gate.py", "TOOL_GATE = True\n")
        self.commit("integration")
        self.policy = PendingFoundationReleasePolicy(
            base_ref="master",
            remote_base_ref="origin/master",
            allowed_branch_prefix="codex/ARGUS-INTEGRATION-",
            source_commits=(
                SourceCommitPolicy("source/a", self.source_a),
                SourceCommitPolicy("source/b", self.source_b),
            ),
            integration_owned_paths=(
                "momentum_hunter/gate.py",
                "tests/test_gate.py",
                "tools/gate.py",
            ),
        )

    def test_clean_exact_integration_passes_without_mutation(self) -> None:
        before_head = self.head()
        before_status = self.git("status", "--porcelain").stdout

        result = self.evaluate()

        self.assertEqual("PASS", result["status"])
        self.assertEqual([], result["findings"])
        self.assertTrue(result["worktreeClean"])
        self.assertTrue(result["baseRemoteSynchronized"])
        self.assertTrue(result["baseAncestorOfHead"])
        self.assertTrue(result["sourceRefsFrozen"])
        self.assertTrue(result["exactSourcePathUnion"])
        self.assertTrue(result["runtimeTestEquivalent"])
        self.assertTrue(result["riskyPathsAbsent"])
        self.assertTrue(result["secretSignaturesAbsent"])
        self.assertEqual(7, result["changedPathCount"])
        self.assertEqual(4, result["sourceUnionPathCount"])
        self.assertEqual(2, result["equivalentRuntimeTestPathCount"])
        self.assertFalse(result["providerEvidence"])
        self.assertFalse(result["executionPermit"])
        self.assertFalse(result["brokerActionAllowed"])
        self.assertFalse(result["retryAllowed"])
        self.assertFalse(result["transmitting"])
        self.assertEqual("UNAVAILABLE", result["orderTransmission"])
        self.assertEqual(before_head, self.head())
        self.assertEqual(before_status, self.git("status", "--porcelain").stdout)

    def test_dirty_worktree_fails_closed(self) -> None:
        self.write("scratch.txt", "dirty\n")

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Integration release gate requires a clean worktree.",
            result["findings"],
        )
        self.assertFalse(result["worktreeClean"])

    def test_remote_base_drift_fails_closed(self) -> None:
        self.git("update-ref", "refs/remotes/origin/master", self.source_a)

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Local base and remote base are not synchronized.",
            result["findings"],
        )
        self.assertFalse(result["baseRemoteSynchronized"])

    def test_moved_source_ref_fails_closed(self) -> None:
        self.git("branch", "-f", "source/a", self.source_b)

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn("Source ref moved: source/a.", result["findings"])
        self.assertFalse(result["sourceRefsFrozen"])

    def test_unexpected_changed_path_fails_closed(self) -> None:
        self.write("momentum_hunter/extra.py", "EXTRA = True\n")
        self.commit("unexpected path")

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertTrue(
            any(
                item.startswith("Unexpected integration paths are present:")
                for item in result["findings"]
            )
        )
        self.assertFalse(result["exactSourcePathUnion"])

    def test_missing_reviewed_source_path_fails_closed(self) -> None:
        (self.root / "tests" / "test_b.py").unlink()
        self.commit("missing source path")

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertTrue(
            any(
                item.startswith("Expected integration paths are missing:")
                and "tests/test_b.py" in item
                for item in result["findings"]
            )
        )
        self.assertFalse(result["exactSourcePathUnion"])

    def test_runtime_drift_from_reviewed_source_fails_closed(self) -> None:
        self.write("momentum_hunter/a.py", "VALUE = 'changed'\n")
        self.commit("runtime drift")

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Runtime/test path differs from reviewed source: "
            "momentum_hunter/a.py.",
            result["findings"],
        )
        self.assertFalse(result["runtimeTestEquivalent"])

    def test_unrelated_integration_history_fails_closed(self) -> None:
        tree = self.git("write-tree").stdout.strip()
        unrelated = self.git(
            "commit-tree",
            tree,
            "-m",
            "unrelated integration",
        ).stdout.strip()
        self.git("reset", "--hard", unrelated)

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Integration head is not a descendant of the base.",
            result["findings"],
        )
        self.assertFalse(result["baseAncestorOfHead"])

    def test_risky_path_and_secret_signature_fail_closed(self) -> None:
        self.write(".env", "SAFE_PLACEHOLDER=true\n")
        self.write("tools/gate.py", "TOKEN = 'sk-" + "a" * 24 + "'\n")
        self.commit("unsafe integration")
        unsafe_policy = replace(
            self.policy,
            integration_owned_paths=(*self.policy.integration_owned_paths, ".env"),
        )

        result = self.evaluate(policy=unsafe_policy)

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Risky path is present in integration diff: .env.",
            result["findings"],
        )
        self.assertIn(
            "High-risk secret signature found in changed file: tools/gate.py.",
            result["findings"],
        )
        self.assertFalse(result["riskyPathsAbsent"])
        self.assertFalse(result["secretSignaturesAbsent"])

    def test_wrong_branch_prefix_fails_closed(self) -> None:
        self.git("branch", "-m", "feature/wrong")

        result = self.evaluate()

        self.assertEqual("FAIL", result["status"])
        self.assertIn(
            "Current branch is outside the allowed integration branch prefix.",
            result["findings"],
        )

    def test_malformed_policy_and_naive_time_are_rejected(self) -> None:
        with self.assertRaises(PendingFoundationReleaseGateError):
            evaluate_pending_foundation_release(
                self.root,
                evaluated_at=EVALUATED_AT.replace(tzinfo=None),
                policy=self.policy,
            )
        with self.assertRaises(PendingFoundationReleaseGateError):
            evaluate_pending_foundation_release(
                self.root,
                evaluated_at=EVALUATED_AT,
                policy=replace(self.policy, source_commits=()),
            )
        with self.assertRaisesRegex(
            PendingFoundationReleaseGateError,
            "Git ref is unsafe",
        ):
            evaluate_pending_foundation_release(
                self.root,
                evaluated_at=EVALUATED_AT,
                policy=replace(self.policy, base_ref="--upload-pack=bad"),
            )
        with self.assertRaisesRegex(
            PendingFoundationReleaseGateError,
            "path prefix policy",
        ):
            evaluate_pending_foundation_release(
                self.root,
                evaluated_at=EVALUATED_AT,
                policy=replace(self.policy, equivalent_prefixes=("",)),
            )

    def test_git_failure_never_projects_optimistic_evidence_flags(self) -> None:
        def failing_runner(
            command: tuple[str, ...] | list[str],
            cwd: Path,
            timeout_seconds: float,
        ) -> CommandResult:
            del cwd, timeout_seconds
            normalized = tuple(command)
            return CommandResult(normalized, 1, "", "forced failure")

        result = evaluate_pending_foundation_release(
            self.root,
            evaluated_at=EVALUATED_AT,
            policy=self.policy,
            command_runner=failing_runner,
        )

        self.assertEqual("FAIL", result["status"])
        for field in (
            "worktreeClean",
            "baseRemoteSynchronized",
            "baseAncestorOfHead",
            "sourceRefsFrozen",
            "exactSourcePathUnion",
            "runtimeTestEquivalent",
            "riskyPathsAbsent",
            "secretSignaturesAbsent",
        ):
            self.assertFalse(result[field], field)

    def evaluate(
        self,
        *,
        policy: PendingFoundationReleasePolicy | None = None,
    ) -> dict[str, object]:
        return evaluate_pending_foundation_release(
            self.root,
            evaluated_at=EVALUATED_AT,
            policy=policy or self.policy,
        )

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
