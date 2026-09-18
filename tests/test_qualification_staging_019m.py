from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.prepare_qualification_startup_019m import copy_git_blob, verify_frozen_source


class FrozenProductStagingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="mh-019m-git-staging-")
        self.root = Path(self.temporary.name)
        self.repo = self.root / "source"
        self.repo.mkdir()
        self._git("init", "-q")
        self._git("config", "user.name", "Qualification")
        self._git("config", "user.email", "qualification@example.invalid")
        (self.repo / "module.py").write_bytes(b"VALUE = 1\n")
        self._git("add", "module.py")
        self._git("commit", "-qm", "frozen fixture")
        self.head = self._git("rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(self.repo), *args],
                                check=True, capture_output=True, text=True)
        return result.stdout.strip()

    def test_stages_exact_committed_blob(self) -> None:
        tree = verify_frozen_source(self.repo, self.head)
        self.assertEqual(40, len(tree))
        row = copy_git_blob(self.repo, self.head, Path("module.py"),
                            self.root / "staged" / "module.py")
        self.assertEqual(b"VALUE = 1\n", Path(row["target"]).read_bytes())
        self.assertEqual(self.head, row["commit"])

    def test_modified_source_refused(self) -> None:
        (self.repo / "module.py").write_bytes(b"VALUE = 2\n")
        with self.assertRaisesRegex(ValueError, "FROZEN_PRODUCT_WORKTREE_DIRTY"):
            verify_frozen_source(self.repo, self.head)

    def test_wrong_head_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "FROZEN_PRODUCT_HEAD_DRIFT"):
            verify_frozen_source(self.repo, "0" * 40)

    def test_malformed_head_refused(self) -> None:
        with self.assertRaisesRegex(ValueError, "EXPECTED_HEAD_INVALID"):
            verify_frozen_source(self.repo, "bad")


if __name__ == "__main__":
    unittest.main()
