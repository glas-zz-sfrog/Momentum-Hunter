from __future__ import annotations

import unittest
from pathlib import Path

from momentum_hunter.source_registry import definitions_by_table, registered_source_definitions


class SourceRegistryTests(unittest.TestCase):
    def test_registry_classifies_core_sources_and_user_state(self) -> None:
        root = Path("X:/MomentumHunterData/data")
        definitions = registered_source_definitions(data_dir=root)
        by_name = {definition.name: definition for definition in definitions}

        self.assertEqual("immutable_source_of_truth", by_name["raw_captures_json"].authority)
        self.assertEqual("immutable", by_name["raw_captures_json"].mutability)
        self.assertIn("Never mutate", by_name["raw_captures_json"].preservation_rule)
        self.assertTrue(by_name["analysis_capture_index"].included_in_all_safe)
        self.assertFalse(by_name["review_decisions"].included_in_all_safe)
        self.assertEqual("file_authoritative_user_state", by_name["entry_plans"].authority)

    def test_definitions_by_table_maps_all_mirrored_user_state_tables(self) -> None:
        definitions = registered_source_definitions()
        by_table = definitions_by_table(definitions)

        self.assertIn("opportunity_alerts", by_table)
        self.assertIn("alert_outcomes", by_table)
        self.assertIn("minute_bars", by_table)
        self.assertIn("evidence_runs", by_table)
        self.assertIn("evidence_metrics", by_table)
        self.assertIn("system_status_events", by_table)
        self.assertIn("captures", by_table)
        self.assertIn("capture_candidates", by_table)
        self.assertIn("candidate_reviews", by_table)
        self.assertIn("watchlist_items", by_table)
        self.assertIn("entry_plans", by_table)


if __name__ == "__main__":
    unittest.main()
