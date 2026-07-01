from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from momentum_hunter.app import MomentumHunterWindow
from momentum_hunter.models import Candidate, NewsItem, NewsStack


class ArgusGatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.patches = [
            patch.object(MomentumHunterWindow, "_ensure_windows_startup", lambda window: None),
            patch.object(MomentumHunterWindow, "_load_capture_history", lambda window: None),
            patch.object(MomentumHunterWindow, "_start_snapshot_timer", lambda window: None),
            patch.object(MomentumHunterWindow, "refresh_market_regime", lambda window, show_status=True: None),
            patch("momentum_hunter.ui.autonomy_gateway.latest_trade_report_path", lambda: None),
        ]
        for patcher in self.patches:
            patcher.start()
        self.window = MomentumHunterWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        for patcher in reversed(self.patches):
            patcher.stop()

    def test_gateway_has_steven_desk_and_argus_machine_choices(self) -> None:
        self.assertEqual(self.window.gateway_page, self.window.app_stack.currentWidget())

        steven_button = self.button("gatewayStevenDeskButton")
        machine_button = self.button("gatewayArgusMachineButton")

        self.assertEqual("Steven Desk", steven_button.text())
        self.assertEqual("Argus Machine", machine_button.text())
        self.assertEqual(
            "Human-guided momentum operations",
            self.label("gatewayStevenDeskSubtitle").text(),
        )
        self.assertEqual(
            "Autonomous planning, simulation, and execution control",
            self.label("gatewayArgusMachineSubtitle").text(),
        )

    def test_steven_desk_opens_existing_dashboard_path(self) -> None:
        self.button("gatewayStevenDeskButton").click()
        self.app.processEvents()

        self.assertEqual(self.window.steven_desk_page, self.window.app_stack.currentWidget())
        self.assertEqual(0, self.window.page_stack.currentIndex())
        self.assertEqual("Dashboard", self.window.nav_buttons[0].text())
        self.assertEqual("Daily Checklist", self.window.daily_checklist_button.text())
        self.assertTrue(hasattr(self.window, "table"))

    def test_argus_machine_opens_safe_console_shell(self) -> None:
        self.button("gatewayArgusMachineButton").click()
        self.app.processEvents()

        self.assertEqual(self.window.argus_machine_page, self.window.app_stack.currentWidget())
        self.assertIn("ARGUS MACHINE", self.label("argusMachineTitle").text())
        status_text = "\n".join(label.text() for label in self.window.argus_machine_status_labels.values())
        self.assertIn("Mode\nSimulation Lab", status_text)
        self.assertIn("Broker\nFakeBroker only", status_text)
        self.assertIn("Live Trading\nLocked", status_text)
        self.assertIn("Risk Governor\nSelect candidate", status_text)
        self.assertIn("Auditor\nWARN", status_text)
        self.assertIn("Kill Switch\nAvailable", status_text)
        self.assertIn("not paper or live permission", self.label("argusRiskWarningLabel").text())
        self.assertIn("No paper broker, no live broker, no real order", self.label("argusOrderConsoleWarning").text())

    def test_argus_machine_shows_five_top_trade_plan_candidate_rows(self) -> None:
        self.window.candidates = sample_candidates()
        self.window.open_argus_machine_console()

        self.assertEqual(5, len(self.window.argus_candidate_buttons))
        button_texts = [button.text() for button in self.window.argus_candidate_buttons]
        gate_texts = [self.window.argus_top5_table.item(row, 3).text() for row in range(self.window.argus_top5_table.rowCount())]
        self.assertTrue(all(text for text in gate_texts))
        self.assertTrue(all("approved live" not in text.lower() for text in button_texts))
        self.assertFalse(any("Strongest Trades" in text for text in button_texts))

    def test_clicking_candidate_populates_trade_plan_ladder(self) -> None:
        self.window.candidates = sample_candidates()
        self.window.open_argus_machine_console()

        self.button("argusCandidateButton_AMD").click()
        self.app.processEvents()

        self.assertIn("Selected ticker: AMD", self.window.argus_workbench_ticker_label.text())
        self.assertIn("Trade Plan Ladder populated for AMD", self.window.argus_ladder_empty_label.text())
        self.assertEqual("AMD", self.ladder_value("Ticker"))
        self.assertNotIn("Demo", self.ladder_value("Entry trigger"))
        self.assertNotEqual("Missing", self.ladder_value("Entry/limit"))
        self.assertNotEqual("Missing", self.ladder_value("Stop/invalidation"))
        self.assertEqual("None. Any future Steven edit requires Risk Governor re-check.", self.ladder_value("Manual override state"))
        self.assertIn(self.ladder_value("Risk Governor status"), {"Needs review", "Simulation-only"})
        self.assertGreater(self.window.argus_risk_gate_table.rowCount(), 0)
        self.assertIn("candidate_selected", self.window.argus_machine_log.toPlainText())

    def test_live_order_controls_are_locked_and_disabled(self) -> None:
        self.window.open_argus_machine_console()

        self.assertEqual("Run Simulation Only", self.window.argus_run_simulation_button.text())
        self.assertFalse(self.window.argus_run_simulation_button.isEnabled())
        locked_buttons = [
            self.window.argus_submit_paper_button,
            self.window.argus_submit_live_button,
        ]
        self.assertEqual(["Paper Order Locked", "Live Order Locked"], [button.text() for button in locked_buttons])
        self.assertTrue(all(not button.isEnabled() for button in locked_buttons))
        self.assertIn("live trading requires separate Steven approval", self.window.argus_submit_live_button.toolTip())
        self.assertIn("Live trading locked.", self.window.argus_machine_log.toPlainText())

    def test_simulation_button_runs_fake_order_and_updates_log(self) -> None:
        self.window.candidates = sample_candidates()
        self.window.open_argus_machine_console()

        self.button("argusCandidateButton_AMD").click()
        self.app.processEvents()

        self.assertTrue(self.window.argus_run_simulation_button.isEnabled())
        self.window.argus_run_simulation_button.click()
        self.app.processEvents()

        self.assertEqual(1, self.window.argus_simulation_table.rowCount())
        self.assertTrue(self.table_value(self.window.argus_simulation_table, 0, 0).startswith("fake-"))
        self.assertEqual("AMD", self.table_value(self.window.argus_simulation_table, 0, 1))
        self.assertEqual("buy", self.table_value(self.window.argus_simulation_table, 0, 2))
        self.assertEqual("filled", self.table_value(self.window.argus_simulation_table, 0, 4))
        self.assertEqual("Simulation Lab", self.table_value(self.window.argus_simulation_table, 0, 5))
        self.assertTrue(self.table_value(self.window.argus_simulation_table, 0, 6))
        self.assertTrue(self.table_value(self.window.argus_simulation_table, 0, 7))
        self.assertEqual(1, self.window.argus_simulation_positions_table.rowCount())
        self.assertEqual("AMD", self.table_value(self.window.argus_simulation_positions_table, 0, 0))
        self.assertIn("FakeBroker only", self.table_value(self.window.argus_simulation_positions_table, 0, 3))
        event_names = {
            self.table_value(self.window.argus_simulation_events_table, row, 0)
            for row in range(self.window.argus_simulation_events_table.rowCount())
        }
        self.assertIn("simulated_order_previewed", event_names)
        self.assertIn("fake_order_submitted", event_names)
        self.assertIn("Auditor: PASS", self.label("argusAuditorStatusLabel").text())
        self.assertEqual("PASS", self.audit_value("Paper advancement gate"))
        self.assertIn("fake_order_submitted", self.window.argus_machine_log.toPlainText())
        self.assertIn("execution_audited", self.window.argus_machine_log.toPlainText())
        self.assertIn("AMD", self.window.argus_machine_log.toPlainText())

    def test_auditor_warns_before_final_simulation_outcome(self) -> None:
        self.window.candidates = sample_candidates()
        self.window.open_argus_machine_console()

        self.button("argusCandidateButton_AMD").click()
        self.app.processEvents()

        self.assertIn("Auditor: WARN", self.label("argusAuditorStatusLabel").text())
        self.assertEqual("Found", self.audit_value("Ledger risk gate"))
        self.assertEqual("Missing", self.audit_value("Ledger order/block"))
        self.assertIn("Waiting for final simulated order", self.label("argusAuditorDetailLabel").text())

    def test_empty_state_explains_missing_candidates(self) -> None:
        self.window.open_argus_machine_console()

        self.assertEqual(0, len(self.window.argus_candidate_buttons))
        empty = self.label("argusTop5EmptyState")
        self.assertIn("No Trade Plan Candidates available", empty.text())

    def button(self, object_name: str) -> QPushButton:
        button = self.window.findChild(QPushButton, object_name)
        if button is None:
            self.fail(f"Button not found: {object_name}")
        return button

    def label(self, object_name: str) -> QLabel:
        label = self.window.findChild(QLabel, object_name)
        if label is None:
            self.fail(f"Label not found: {object_name}")
        return label

    def ladder_value(self, field: str) -> str:
        table = self.window.argus_ladder_table
        for row in range(table.rowCount()):
            field_item = table.item(row, 0)
            value_item = table.item(row, 1)
            if field_item and field_item.text() == field and value_item:
                return value_item.text()
        self.fail(f"Ladder field not found: {field}")

    def audit_value(self, field: str) -> str:
        table = self.window.argus_auditor_evidence_table
        for row in range(table.rowCount()):
            field_item = table.item(row, 0)
            value_item = table.item(row, 1)
            if field_item and field_item.text() == field and value_item:
                return value_item.text()
        self.fail(f"Auditor field not found: {field}")

    def table_value(self, table, row: int, column: int) -> str:
        item = table.item(row, column)
        if item is None:
            self.fail(f"Table cell missing: {row}, {column}")
        return item.text()


def sample_candidates() -> list[Candidate]:
    return [
        sample_candidate("NVDA", 30.0, 93, "NVDA extends AI infrastructure momentum"),
        sample_candidate("AMD", 20.0, 91, "AMD gains on AI accelerator demand"),
        sample_candidate("PLTR", 16.0, 88, "PLTR rallies on government contract catalyst"),
        sample_candidate("TSLA", 25.0, 86, "TSLA breaks higher on delivery update"),
        sample_candidate("SMCI", 22.0, 84, "SMCI rebounds on server demand"),
    ]


def sample_candidate(ticker: str, price: float, score: int, headline: str) -> Candidate:
    return Candidate(
        ticker=ticker,
        company=f"{ticker} Corp",
        price=price,
        percent_change=5.0,
        volume=10_000_000,
        relative_volume=1.5,
        market_cap=10_000_000_000,
        sector="Technology",
        industry="Software",
        news=[NewsItem(headline=headline, source="Test")],
        score=score,
        freshness_score=90,
        news_stack=NewsStack(article_count=1, freshest_headline=headline, freshness_score=90, freshness="HOT"),
    )


if __name__ == "__main__":
    unittest.main()
