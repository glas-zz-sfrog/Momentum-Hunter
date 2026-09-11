from __future__ import annotations

import copy
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import writer_backlog_readmission as gate


class WriterBacklogReadmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.manifest = {"profile": gate.PROFILE, "candidate_root": str(cls.root),
            "candidate_files": [{"path": name, "bytes": (cls.root / name).stat().st_size,
                                 "sha256": gate.original.digest((cls.root / name).read_bytes())}
                                for name in sorted(gate.source_inventory(cls.root))]}

    def test_exact_raw_candidate_and_loaded_modules_pass(self):
        gate.verify_candidate(self.root, self.manifest)

    def test_changed_byte_fails(self):
        changed = copy.deepcopy(self.manifest)
        changed["candidate_files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(AssertionError, "CANDIDATE_BYTES_CHANGED"):
            gate.verify_candidate(self.root, changed)

    def test_added_removed_or_case_duplicate_source_fails(self):
        for change in ("add", "remove", "duplicate"):
            with self.subTest(change=change):
                changed = copy.deepcopy(self.manifest)
                if change == "remove":
                    changed["candidate_files"].pop()
                else:
                    entry = copy.deepcopy(changed["candidate_files"][0])
                    entry["path"] = "tests/not-in-candidate.py" if change == "add" else entry["path"].upper()
                    changed["candidate_files"].append(entry)
                with self.assertRaises(AssertionError):
                    gate.verify_candidate(self.root, changed)

    def test_wrong_root_and_profile_fail(self):
        for field, value in (("profile", "SELF_APPROVED"), ("candidate_root", str(self.root.parent))):
            changed = {**self.manifest, field: value}
            with self.assertRaises(AssertionError):
                gate.verify_candidate(self.root, changed)

    def test_mixed_loaded_module_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "outside.py"
            path.write_text("# disposable fixture\n", encoding="ascii")
            module = types.ModuleType("momentum_hunter.outside")
            module.__file__ = str(path)
            with patch.dict(sys.modules, {module.__name__: module}):
                with self.assertRaisesRegex(AssertionError, "MIXED_CANDIDATE_IMPORT"):
                    gate.verify_candidate(self.root, self.manifest)

    def test_no_opt_in_preserves_original_strict_gate(self):
        env = {key: value for key, value in os.environ.items() if key not in {gate.MANIFEST_ENV, gate.PIN_ENV}}
        with patch.dict(os.environ, env, clear=True), patch.object(gate.original, "verify_custody", return_value=42) as strict:
            self.assertEqual(42, gate.verify_for_current_source(Path("evidence"), self.root))
            strict.assert_called_once_with(Path("evidence"), self.root)

    def test_unpaired_opt_in_and_wrong_pin_fail_before_original_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text("{}", encoding="ascii")
            for values in ({gate.MANIFEST_ENV: str(path)}, {gate.PIN_ENV: "0" * 64},
                           {gate.MANIFEST_ENV: str(path), gate.PIN_ENV: "0" * 64}):
                with self.subTest(values=list(values)):
                    env = {key: value for key, value in os.environ.items() if key not in {gate.MANIFEST_ENV, gate.PIN_ENV}}
                    env.update(values)
                    with patch.dict(os.environ, env, clear=True), patch.object(gate.original, "verify_custody") as strict:
                        with self.assertRaises(AssertionError):
                            gate.verify_for_current_source(Path("evidence"), self.root)
                        strict.assert_not_called()
