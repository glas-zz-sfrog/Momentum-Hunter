from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from dataclasses import asdict
from pathlib import Path

from momentum_hunter.prospective_denominator import (
    ProspectiveDenominatorStore,
    build_activation_record,
)
from tests.test_prospective_denominator import active_result
from tests.test_continuous_denominator import (
    composition_cycle,
    paginated_snapshot,
    universe_result,
)
from tools import run_stat_data_002_canary as canary


class StatData002PackageTests(unittest.TestCase):
    def test_terminal_packet_is_sanitized_self_contained_and_reproducible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "STAT-DATA-002-SYNTHETIC-TERMINAL"
            evidence.mkdir()
            activation = build_activation_record(
                activated_at="2026-08-17T09:00:00-04:00",
                first_eligible_session_date="2026-08-17",
                source_git_sha="1" * 40,
                configuration_fingerprint="2" * 64,
            )
            snapshot = paginated_snapshot(20, {1, 2})
            universe = universe_result(snapshot)
            result = active_result(
                snapshot,
                universe,
                composition_cycle(universe),
                activation,
            )
            store = ProspectiveDenominatorStore(
                evidence / "prospective-denominator",
                activation=activation,
            )
            store.persist_result(
                result,
                completed_at="2026-08-17T11:23:00-04:00",
            )
            canary._write_once(
                evidence / "activation.json",
                {
                    "recordType": "STAT_DATA_002_ACTIVATION",
                    "payload": asdict(activation),
                },
            )
            canary._write_once(
                evidence / "configuration.json",
                {
                    "authority": "RESEARCH_ONLY",
                    "executionAuthority": "NONE",
                },
            )
            canary._write_once(
                evidence / "terminal-result.json",
                {
                    "status": "PASS",
                    "authority": "RESEARCH_ONLY",
                    "executionAuthority": "NONE",
                },
            )

            packet = canary.package(
                task_root=Path(__file__).resolve().parents[1],
                evidence_root=evidence,
                python_executable=Path(sys.executable),
            )

            self.assertEqual("PASS", packet["status"])
            self.assertEqual("PASS", packet["secretScan"])
            self.assertEqual("PASS", packet["manifestVerification"])
            self.assertEqual("PASS", packet["preZipVerification"]["status"])
            self.assertEqual("PASS", packet["extractedZipVerification"]["status"])
            self.assertEqual(packet["manifestCount"] + 1, packet["fileCount"])
            with zipfile.ZipFile(packet["zipPath"]) as archive:
                names = set(archive.namelist())
            self.assertIn("INDEX.md", names)
            self.assertIn("MANIFEST.json", names)
            self.assertIn("evidence/terminal-result.json", names)
            self.assertIn("source/tools/run_stat_data_002_canary.py", names)


if __name__ == "__main__":
    unittest.main()
