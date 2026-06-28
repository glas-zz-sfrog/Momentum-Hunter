from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from momentum_hunter.app import MomentumHunterWindow


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
        self.assertIn("Broker\nNone connected", status_text)
        self.assertIn("Live Trading\nLocked", status_text)
        self.assertIn("Risk Governor\nPreview only", status_text)
        self.assertIn("Kill Switch\nAvailable", status_text)
        self.assertIn("not live trading permission", self.label("argusRiskWarningLabel").text())

    def test_argus_machine_shows_five_top_trade_plan_candidate_rows(self) -> None:
        self.window.open_argus_machine_console()

        self.assertEqual(5, len(self.window.argus_candidate_buttons))
        button_texts = [button.text() for button in self.window.argus_candidate_buttons]
        self.assertTrue(all("Gate:" in text for text in button_texts))
        self.assertTrue(all("approved live" not in text.lower() for text in button_texts))
        self.assertFalse(any("Strongest Trades" in text for text in button_texts))

    def test_clicking_candidate_populates_trade_plan_ladder(self) -> None:
        self.window.open_argus_machine_console()

        self.button("argusCandidateButton_AMD").click()
        self.app.processEvents()

        self.assertIn("Selected ticker: AMD", self.window.argus_workbench_ticker_label.text())
        self.assertIn("Trade Plan Ladder populated for AMD", self.window.argus_ladder_empty_label.text())
        self.assertEqual("AMD", self.ladder_value("Ticker"))
        self.assertEqual("Relative strength pullback", self.ladder_value("Setup type"))
        self.assertEqual("Reclaim demo pivot with volume confirmation", self.ladder_value("Entry trigger"))
        self.assertEqual("Demo invalidation: lower-low under pullback base", self.ladder_value("Stop/invalidation"))
        self.assertEqual("None. Any future Steven edit requires Risk Governor re-check.", self.ladder_value("Manual override state"))
        self.assertEqual("Stop required", self.ladder_value("Risk Governor status"))

    def test_live_order_controls_are_locked_and_disabled(self) -> None:
        self.window.open_argus_machine_console()

        locked_buttons = [
            self.window.argus_preview_order_button,
            self.window.argus_submit_paper_button,
            self.window.argus_submit_live_button,
        ]
        self.assertEqual(["Preview Order", "Submit Paper Order", "Submit Live Order"], [button.text() for button in locked_buttons])
        self.assertTrue(all(not button.isEnabled() for button in locked_buttons))
        self.assertIn("live trading requires separate Steven approval", self.window.argus_submit_live_button.toolTip())
        self.assertIn("No broker connected. Live trading locked.", self.window.argus_machine_log.toPlainText())

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


if __name__ == "__main__":
    unittest.main()
