from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from momentum_hunter.continuous_live_qualification import (
    LiveQualificationError,
    validate_qualification_root,
)
from momentum_hunter.opportunity_denominator import (
    LIVE_READ_ONLY_QUALIFICATION,
    OBSERVATION_MODES,
)


class ContinuousLiveQualificationTests(unittest.TestCase):
    def test_disposable_root_rejects_production_and_canonical_paths(self) -> None:
        canonical = Path("C:/Users/steve/OneDrive/Documents/Investing")
        with self.assertRaises(LiveQualificationError):
            validate_qualification_root(
                canonical / "qualification",
                canonical_root=canonical,
            )
        with self.assertRaises(LiveQualificationError):
            validate_qualification_root(
                Path("C:/ProgramData/MomentumHunter/qualification"),
                canonical_root=canonical,
            )
        with self.assertRaises(LiveQualificationError):
            validate_qualification_root(
                Path("C:/temp/MomentumHunterData/qualification"),
                canonical_root=canonical,
            )

    def test_disposable_user_local_root_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "generation-1"
            self.assertEqual(root.resolve(), validate_qualification_root(root))

    def test_live_qualification_mode_is_distinct_and_nonprospective(self) -> None:
        self.assertIn(LIVE_READ_ONLY_QUALIFICATION, OBSERVATION_MODES)
        self.assertNotEqual("PROSPECTIVE", LIVE_READ_ONLY_QUALIFICATION)

    def test_module_has_no_order_or_broker_capability(self) -> None:
        source = (
            Path(__file__).parents[1]
            / "momentum_hunter"
            / "continuous_live_qualification.py"
        )
        tree = ast.parse(source.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertFalse(
            imports.intersection(
                {
                    "momentum_hunter.alpaca_paper_broker",
                    "momentum_hunter.alpaca_paper_engineering",
                    "momentum_hunter.shadow_selection",
                    "momentum_hunter.shadow_opening",
                }
            )
        )
        calls = {
            node.func.attr.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(
            calls.intersection({"submit_order", "cancel_order", "replace_order"})
        )


if __name__ == "__main__":
    unittest.main()
