from __future__ import annotations

import ast
import csv
import json
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.research_data_inventory import (
    INSUFFICIENT,
    PARTIAL,
    ResearchDataInventoryError,
    ResearchDataPaths,
    build_research_data_inventory,
    render_inventory_markdown,
    write_inventory_outputs,
)


AS_OF = "2026-08-14T16:00:00-05:00"


class ResearchDataInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = ResearchDataPaths(
            canonical_minute_root=self.root / "minute",
            canonical_daily_root=self.root / "daily",
            research_daily_path=self.root / "research-daily.json",
            analysis_captures_path=self.root / "analysis-captures.csv",
            analysis_outcomes_path=self.root / "analysis-outcomes.csv",
            opening_captures_root=self.root / "captures",
            successor_setup_root=self.root / "setup",
        )
        self._seed_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_inventories_authority_coverage_and_sessions(self) -> None:
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        datasets = {item["datasetId"]: item for item in inventory["datasets"]}
        minute = datasets["canonicalSchwabMinute"]
        self.assertEqual(minute["authority"], "CANONICAL")
        self.assertEqual(minute["recordCount"], 3)
        self.assertEqual(minute["symbolCount"], 1)
        self.assertEqual(minute["sessionCoverage"], {"PREMARKET": 2, "REGULAR": 1})
        self.assertEqual(minute["sessionSymbolDateCount"], {"PREMARKET": 1, "REGULAR": 1})
        self.assertEqual(minute["observedInternalGapMinutes"], 1)
        self.assertFalse(minute["stableSecurityIdentity"])
        self.assertEqual(datasets["researchDaily263"]["authority"], "RESEARCH_ONLY")
        self.assertEqual(datasets["researchDaily263"]["priceBasis"], "ADJUSTED_OHLCV_WITHOUT_EVENT_LEVEL_FACTOR_LINEAGE")
        self.assertEqual(datasets["researchDaily263"]["minimumBarsPerSymbol"], 1)
        self.assertEqual(datasets["researchDaily263"]["symbolsWithAtLeast200Bars"], 0)

    def test_capability_matrix_does_not_overstate_local_history(self) -> None:
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        matrix = {item["researchUse"]: item for item in inventory["capabilityMatrix"]}
        self.assertEqual(matrix["dailyTechnicalPatterns"]["status"], INSUFFICIENT)
        self.assertEqual(matrix["intradayTechnicalPatternsAndAnalogs"]["status"], INSUFFICIENT)
        self.assertEqual(matrix["rankAndSetupConditionedOutcomes"]["status"], PARTIAL)
        self.assertEqual(matrix["historicalAnalogModeling"]["status"], INSUFFICIENT)

    def test_daily_pattern_status_is_only_partial_with_real_depth(self) -> None:
        payload = json.loads(self.paths.research_daily_path.read_text(encoding="utf-8"))
        template = payload["records"][0]
        payload["records"] = [
            {**template, "date": f"2025-{1 + index // 28:02d}-{1 + index % 28:02d}"}
            for index in range(200)
        ]
        self.paths.research_daily_path.write_text(json.dumps(payload), encoding="utf-8")
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        matrix = {item["researchUse"]: item for item in inventory["capabilityMatrix"]}
        self.assertEqual(matrix["dailyTechnicalPatterns"]["status"], INSUFFICIENT)

        payload["records"] = [
            {**row, "symbol": f"T{symbol:03d}"}
            for symbol in range(200)
            for row in payload["records"]
        ]
        self.paths.research_daily_path.write_text(json.dumps(payload), encoding="utf-8")
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        matrix = {item["researchUse"]: item for item in inventory["capabilityMatrix"]}
        self.assertEqual(matrix["dailyTechnicalPatterns"]["status"], PARTIAL)

    def test_universe_integrity_fails_closed_without_durable_identity(self) -> None:
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        integrity = inventory["universeIntegrity"]
        self.assertFalse(integrity["stableSecurityIdentityAvailable"])
        self.assertFalse(integrity["delistedSecurityCoverageAvailable"])
        self.assertFalse(integrity["corporateActionEventLineageAvailable"])
        self.assertEqual(integrity["survivorshipBiasControl"], "INSUFFICIENT")

    def test_candidate_history_does_not_invent_rejected_denominator(self) -> None:
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        candidate = next(item for item in inventory["datasets"] if item["datasetId"] == "candidateOutcomeHistory")
        self.assertEqual(candidate["recordCount"], 1)
        self.assertEqual(candidate["completeOutcomeCount"], 1)
        self.assertEqual(candidate["openingCandidateCount"], 1)
        self.assertEqual(candidate["emptyOpeningSessionCount"], 0)
        self.assertFalse(candidate["fullRejectedCandidateHistory"])
        self.assertEqual(len(candidate["captureFileSha256"]), 64)
        self.assertEqual(len(candidate["outcomeFileSha256"]), 64)

    def test_setup_activation_is_capability_not_observed_sample(self) -> None:
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        setup = next(item for item in inventory["datasets"] if item["datasetId"] == "successorSetupProspective")
        self.assertEqual(setup["status"], "ACTIVE_PROSPECTIVE_EMPTY")
        self.assertEqual(setup["passOneCount"], 0)
        self.assertEqual(setup["passTwoCount"], 0)
        self.assertEqual(setup["executionAuthority"], "NONE")

    def test_malformed_canonical_partition_fails_closed(self) -> None:
        path = self.paths.canonical_minute_root / "2026-08-14" / "TEST.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["legacySourceMixed"] = True
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ResearchDataInventoryError, "legacy-source isolation"):
            build_research_data_inventory(self.paths, as_of=AS_OF)

    def test_nonpartition_run_metadata_is_not_counted_as_minute_evidence(self) -> None:
        runs = self.paths.canonical_minute_root / "runs"
        runs.mkdir()
        self._write_json(runs / "backfill.json", {"bars": ["not canonical evidence"]})
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        minute = next(item for item in inventory["datasets"] if item["datasetId"] == "canonicalSchwabMinute")
        self.assertEqual(minute["fileCount"], 1)
        self.assertEqual(minute["recordCount"], 3)

    def test_research_daily_must_prove_research_only_schema(self) -> None:
        payload = json.loads(self.paths.research_daily_path.read_text(encoding="utf-8"))
        payload["research_only"] = False
        self.paths.research_daily_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(ResearchDataInventoryError, "research-only schema"):
            build_research_data_inventory(self.paths, as_of=AS_OF)

    def test_inventory_is_deterministic_and_does_not_mutate_sources(self) -> None:
        before = self._source_bytes()
        first = build_research_data_inventory(self.paths, as_of=AS_OF)
        second = build_research_data_inventory(self.paths, as_of=AS_OF)
        self.assertEqual(first, second)
        self.assertEqual(before, self._source_bytes())

    def test_write_once_outputs_are_idempotent_and_conflicts_fail(self) -> None:
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        json_path = self.root / "out" / "inventory.json"
        md_path = self.root / "out" / "inventory.md"
        write_inventory_outputs(inventory, json_path=json_path, markdown_path=md_path)
        write_inventory_outputs(inventory, json_path=json_path, markdown_path=md_path)
        changed = dict(inventory)
        changed["asOf"] = "2026-08-14T16:01:00-05:00"
        with self.assertRaisesRegex(ResearchDataInventoryError, "Conflicting"):
            write_inventory_outputs(changed, json_path=json_path, markdown_path=md_path)

    def test_markdown_states_provider_minimalism_and_denied_authority(self) -> None:
        inventory = build_research_data_inventory(self.paths, as_of=AS_OF)
        rendered = render_inventory_markdown(inventory)
        self.assertIn("No new provider is selected or recommended", rendered)
        self.assertIn("Execution authority: `NONE`", rendered)
        self.assertIn("PROSPECTIVE_OPPORTUNITY_DENOMINATOR", rendered)
        self.assertIn("EXTENDED_SESSION_TIMESTAMP_SEMANTICS", rendered)
        self.assertNotIn("guaranteed", rendered.lower())

    def test_module_has_no_network_or_broker_imports(self) -> None:
        path = Path(__file__).parents[1] / "momentum_hunter" / "research_data_inventory.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            str(node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        self.assertTrue(imports.isdisjoint({"requests", "httpx", "urllib", "socket"}))
        source = path.read_text(encoding="utf-8").lower()
        self.assertNotIn("alpaca_paper_broker", source)
        self.assertNotIn("submit_order", source)

    def _seed_fixture(self) -> None:
        minute_dir = self.paths.canonical_minute_root / "2026-08-14"
        minute_dir.mkdir(parents=True)
        bars = [
            self._minute_bar("2026-08-14T11:00:00+00:00", "extended"),
            self._minute_bar("2026-08-14T11:02:00+00:00", "extended"),
            self._minute_bar("2026-08-14T13:30:00+00:00", "regular"),
        ]
        self._write_json(
            minute_dir / "TEST.json",
            {
                "schemaVersion": 1,
                "storeKind": "SCHWAB_INCREMENTAL_MINUTE_CANDLES",
                "symbol": "TEST",
                "sessionDate": "2026-08-14",
                "canonicalSource": "schwab_marketdata_v1_pricehistory:v1",
                "legacySourceMixed": False,
                "bars": bars,
            },
        )
        self.paths.canonical_daily_root.mkdir(parents=True)
        self._write_json(
            self.paths.canonical_daily_root / "TEST.json",
            {
                "schemaVersion": 1,
                "storeKind": "SCHWAB_CANONICAL_DAILY_CANDLES",
                "symbol": "TEST",
                "canonicalSource": "schwab_marketdata_v1_pricehistory:v1",
                "legacySourceMixed": False,
                "bars": [
                    {
                        "dailyIdentity": "schwab-equity-1d:v1|TEST|2026-08-13",
                        "sessionDate": "2026-08-13",
                        "timestamp": "2026-08-13T04:00:00+00:00",
                        "state": "CANONICAL",
                        "historyVersions": [],
                        "canonicalCandle": {
                            "symbol": "TEST",
                            "sessionDate": "2026-08-13",
                            "timestamp": "2026-08-13T04:00:00+00:00",
                            "source": "schwab_marketdata_v1_pricehistory:v1",
                            "open": 10.0,
                            "high": 11.0,
                            "low": 9.0,
                            "close": 10.5,
                            "volume": 1000,
                        },
                    }
                ],
            },
        )
        self._write_json(
            self.paths.research_daily_path,
            {
                "schema_version": 1,
                "engine_version": "daily_ohlc_research_source_v1",
                "generated_at": "2026-08-14T12:00:00-05:00",
                "research_only": True,
                "records": [
                    {
                        "symbol": "TEST",
                        "date": "2026-08-13",
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume": 1000,
                        "source": "yahoo_chart_1d_adjusted",
                        "adjusted": True,
                    }
                ],
            },
        )
        self._write_csv(
            self.paths.analysis_captures_path,
            [{"capture_time": "2026-08-14T08:35:00-05:00", "ticker": "TEST", "selected": "False", "reviewed": "False"}],
        )
        self._write_csv(
            self.paths.analysis_outcomes_path,
            [{"capture_time": "2026-08-14T08:35:00-05:00", "ticker": "TEST", "outcome_status": "complete"}],
        )
        opening_dir = self.paths.opening_captures_root / "2026-08-14"
        opening_dir.mkdir(parents=True)
        self._write_json(
            opening_dir / "opening.json",
            {"capture_date": "2026-08-14", "candidates": [{"ticker": "TEST", "rank": 1}]},
        )
        self.paths.successor_setup_root.mkdir(parents=True)
        self._write_json(
            self.paths.successor_setup_root / "sample-charter.json",
            {"schemaVersion": 1, "task": "ARGUS-SETUP-002", "sampleId": "sample", "status": "EMPTY_PENDING_FUTURE_ACTIVATION", "executionAuthority": "NONE"},
        )
        self._write_json(
            self.paths.successor_setup_root / "activation.json",
            {"schemaVersion": 1, "task": "ARGUS-SETUP-002A", "sampleId": "sample", "status": "ACTIVE_PROSPECTIVE_EMPTY", "activatedAt": "2026-08-14T10:00:00-05:00", "firstEligibleSessionDate": "2026-08-17", "expectedGitHead": "a" * 40, "executionAuthority": "NONE"},
        )

    @staticmethod
    def _minute_bar(timestamp: str, session: str) -> dict[str, object]:
        return {
            "minuteIdentity": f"schwab-equity-1m:v1|TEST|{timestamp}",
            "timestamp": timestamp,
            "session": session,
            "state": "RECONCILED",
            "historyVersions": [],
            "streamVersions": [],
            "canonicalCandle": {
                "symbol": "TEST",
                "timestamp": timestamp,
                "sessionDate": "2026-08-14",
                "source": "schwab_marketdata_v1_pricehistory:v1",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 100,
            },
        }

    @staticmethod
    def _write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def _source_bytes(self) -> dict[str, bytes]:
        output: dict[str, bytes] = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file() and "out" not in path.parts:
                output[str(path.relative_to(self.root))] = path.read_bytes()
        return output


if __name__ == "__main__":
    unittest.main()
