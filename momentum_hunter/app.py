from __future__ import annotations

import sys
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from momentum_hunter.config import AppConfig, load_config, save_config
from momentum_hunter.models import Candidate, SCANNER_PRESETS, TradingMode
from momentum_hunter.providers import provider_from_name
from momentum_hunter.scoring import score_candidates
from momentum_hunter.storage import save_watchlist
from momentum_hunter.time_utils import format_central, next_market_session, now_central


class MomentumHunterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.candidates: list[Candidate] = []
        self.saved_candidates: dict[str, Candidate] = {}
        self.selected_ticker: str | None = None

        self.setWindowTitle("Momentum Hunter")
        self.resize(1280, 780)
        self.setMinimumSize(980, 620)
        self._build_ui()
        self._apply_config_to_controls()
        self._update_status("Ready. Human review required before any trading decision.")

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_top_bar())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_candidate_panel())
        splitter.addWidget(self._build_research_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)
        self.setCentralWidget(root)
        self.setStyleSheet(STYLESHEET)

    def _build_top_bar(self) -> QWidget:
        box = QGroupBox("Session")
        layout = QGridLayout(box)
        layout.setColumnStretch(7, 1)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems([TradingMode.PAPER.value, TradingMode.LIVE.value])
        self.mode_combo.currentTextChanged.connect(self._mode_changed)

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["sample", "finviz"])
        self.provider_combo.currentTextChanged.connect(self._provider_changed)

        self.scanner_combo = QComboBox()
        self.scanner_combo.addItems(list(SCANNER_PRESETS.keys()))
        self.scanner_combo.currentTextChanged.connect(self._scanner_changed)

        self.scan_button = QPushButton("Run Scanner")
        self.scan_button.clicked.connect(self.run_scan)

        self.save_button = QPushButton("Save Candidate")
        self.save_button.clicked.connect(self.save_selected_candidate)

        self.watchlist_button = QPushButton("Save Tomorrow Watchlist")
        self.watchlist_button.clicked.connect(self.save_tomorrow_watchlist)

        self.clock_label = QLabel(format_central())
        self.criteria_label = QLabel()
        self.criteria_label.setObjectName("criteriaLabel")

        layout.addWidget(QLabel("Mode"), 0, 0)
        layout.addWidget(self.mode_combo, 0, 1)
        layout.addWidget(QLabel("Provider"), 0, 2)
        layout.addWidget(self.provider_combo, 0, 3)
        layout.addWidget(QLabel("Scanner"), 0, 4)
        layout.addWidget(self.scanner_combo, 0, 5)
        layout.addWidget(self.scan_button, 0, 6)
        layout.addWidget(self.save_button, 0, 7)
        layout.addWidget(self.watchlist_button, 0, 8)
        layout.addWidget(self.clock_label, 1, 0, 1, 2)
        layout.addWidget(QLabel("Evening review: 7:00 PM - 8:00 PM CT"), 1, 2, 1, 3)
        layout.addWidget(QLabel("Morning review: 7:00 AM - 8:00 AM CT"), 1, 5, 1, 4)
        layout.addWidget(self.criteria_label, 2, 0, 1, 9)
        return box

    def _build_candidate_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Score", "Ticker", "Price", "% Chg", "Volume", "Rel Vol", "Market Cap", "Sector", "Industry"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table)
        return panel

    def _build_research_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        identity = QGroupBox("Candidate")
        identity_layout = QGridLayout(identity)
        self.ticker_label = QLabel("No candidate selected")
        self.ticker_label.setObjectName("tickerLabel")
        self.company_label = QLabel("")
        self.score_label = QLabel("")
        self.reasons_label = QLabel("")
        self.reasons_label.setWordWrap(True)
        identity_layout.addWidget(self.ticker_label, 0, 0)
        identity_layout.addWidget(self.score_label, 0, 1)
        identity_layout.addWidget(self.company_label, 1, 0, 1, 2)
        identity_layout.addWidget(self.reasons_label, 2, 0, 1, 2)
        layout.addWidget(identity)

        news_box = QGroupBox("News & Catalysts")
        news_layout = QVBoxLayout(news_box)
        self.news_text = QPlainTextEdit()
        self.news_text.setReadOnly(True)
        self.news_text.setPlaceholderText("Select a candidate to review headlines.")
        news_layout.addWidget(self.news_text)
        layout.addWidget(news_box, 2)

        notes_box = QGroupBox("Candidate Notes")
        notes_layout = QVBoxLayout(notes_box)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Watch breakout over 105; gap-and-go candidate; earnings continuation play.")
        self.notes_edit.textChanged.connect(self._notes_changed)
        notes_layout.addWidget(self.notes_edit)
        layout.addWidget(notes_box, 1)

        entry_box = QGroupBox("Entry Plan")
        entry_layout = QGridLayout(entry_box)
        self.entry_trigger = QLineEdit()
        self.stop_level = QLineEdit()
        self.risk_note = QLabel("Suggested discipline: define entry, invalidation, and max loss before placing any trade.")
        self.risk_note.setWordWrap(True)
        entry_layout.addWidget(QLabel("Trigger"), 0, 0)
        entry_layout.addWidget(self.entry_trigger, 0, 1)
        entry_layout.addWidget(QLabel("Stop"), 1, 0)
        entry_layout.addWidget(self.stop_level, 1, 1)
        entry_layout.addWidget(self.risk_note, 2, 0, 1, 2)
        layout.addWidget(entry_box)
        return panel

    def _apply_config_to_controls(self) -> None:
        self.mode_combo.setCurrentText(self.config.mode.value)
        self.provider_combo.setCurrentText(self.config.provider)
        self._scanner_changed(self.scanner_combo.currentText())

    def _mode_changed(self, value: str) -> None:
        self.config = replace(self.config, mode=TradingMode(value))
        save_config(self.config)
        if self.config.mode == TradingMode.LIVE:
            QMessageBox.information(
                self,
                "Live Mode",
                "LIVE mode is a research mode only in this version. Momentum Hunter does not place trades.",
            )
        self._update_status(f"Mode set to {self.config.mode.value}. No automatic trading is enabled.")

    def _provider_changed(self, value: str) -> None:
        self.config = replace(self.config, provider=value)
        save_config(self.config)
        self._update_status(f"Provider set to {value}.")

    def _scanner_changed(self, value: str) -> None:
        criteria = SCANNER_PRESETS[value]
        self.criteria_label.setText(
            "Scanner thresholds: "
            f"Volume >= {criteria.min_volume:,} | "
            f"Change >= {criteria.min_percent_change:.1f}% | "
            f"Market Cap >= {format_market_cap(criteria.min_market_cap)} | "
            f"Price >= ${criteria.min_price:,.2f} | "
            f"Relative Volume >= {criteria.min_relative_volume:.2f}x"
        )

    def run_scan(self) -> None:
        criteria = SCANNER_PRESETS[self.scanner_combo.currentText()]
        provider = provider_from_name(self.provider_combo.currentText())
        self._update_status(f"Running {criteria.name} with {provider.name} provider...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            candidates = provider.scan(criteria)
            for candidate in candidates:
                if not candidate.news:
                    candidate.news = provider.fetch_news(candidate.ticker)
            self.candidates = score_candidates(candidates)
            self._populate_table()
            self._update_status(f"Scan complete at {format_central()}. {len(self.candidates)} candidates found.")
        except Exception as exc:
            QMessageBox.warning(self, "Scanner Error", str(exc))
            self._update_status(f"Scanner failed: {exc}")
        finally:
            QApplication.restoreOverrideCursor()

    def _populate_table(self) -> None:
        self.table.setRowCount(len(self.candidates))
        for row, candidate in enumerate(self.candidates):
            values = [
                str(candidate.score),
                candidate.ticker,
                f"${candidate.price:,.2f}",
                f"{candidate.percent_change:.1f}%",
                f"{candidate.volume:,}",
                f"{candidate.relative_volume:.2f}x" if candidate.relative_volume else "n/a",
                format_market_cap(candidate.market_cap),
                candidate.sector,
                candidate.industry,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(score_color(candidate.score))
                self.table.setItem(row, column, item)
        if self.candidates:
            self.table.selectRow(0)

    def _selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        candidate = self.candidates[rows[0].row()]
        self.selected_ticker = candidate.ticker
        self.ticker_label.setText(candidate.ticker)
        self.company_label.setText(candidate.company)
        self.score_label.setText(f"Score: {candidate.score}")
        self.reasons_label.setText(", ".join(candidate.score_reasons) or "No score reasons yet.")
        self.notes_edit.blockSignals(True)
        self.notes_edit.setPlainText(candidate.user_notes)
        self.notes_edit.blockSignals(False)
        self.news_text.setPlainText(format_news(candidate))

    def _notes_changed(self) -> None:
        candidate = self._selected_candidate()
        if candidate is not None:
            candidate.user_notes = self.notes_edit.toPlainText()

    def save_selected_candidate(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            self._update_status("Select a candidate before saving.")
            return
        candidate.user_notes = self.notes_edit.toPlainText()
        candidate.saved_at = now_central()
        self.saved_candidates[candidate.ticker] = candidate
        self._update_status(f"Saved {candidate.ticker} to tomorrow watchlist staging.")

    def save_tomorrow_watchlist(self) -> None:
        if not self.saved_candidates:
            self._update_status("No saved candidates yet.")
            return
        session_date = next_market_session()
        path = save_watchlist(list(self.saved_candidates.values()), session_date)
        QMessageBox.information(self, "Watchlist Saved", f"Saved {len(self.saved_candidates)} candidates to:\n{path}")
        self._update_status(f"Watchlist saved to {path}")

    def _selected_candidate(self) -> Candidate | None:
        if self.selected_ticker is None:
            return None
        return next((candidate for candidate in self.candidates if candidate.ticker == self.selected_ticker), None)

    def _update_status(self, message: str) -> None:
        self.clock_label.setText(format_central())
        self.status_label.setText(message)


def format_news(candidate: Candidate) -> str:
    if not candidate.news:
        return "No headlines loaded. Review news manually before trading."
    blocks = []
    for item in candidate.news:
        source = f" ({item.source})" if item.source else ""
        summary = f"\n  {item.summary}" if item.summary else ""
        url = f"\n  {item.url}" if item.url else ""
        blocks.append(f"- {item.headline}{source}{summary}{url}")
    return "\n\n".join(blocks)


def format_market_cap(value: int) -> str:
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.1f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return "n/a"


def score_color(score: int) -> QColor:
    if score >= 85:
        return QColor("#b7e4c7")
    if score >= 70:
        return QColor("#d8f3dc")
    if score >= 50:
        return QColor("#fff3bf")
    return QColor("#ffd6d6")


STYLESHEET = """
QMainWindow, QWidget {
    background: #f7f8fa;
    color: #17202a;
    font-family: Segoe UI;
    font-size: 10pt;
}
QGroupBox {
    border: 1px solid #cfd6df;
    border-radius: 6px;
    margin-top: 8px;
    padding: 8px;
    background: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background: #1f6feb;
    color: #ffffff;
    border: 0;
    border-radius: 4px;
    padding: 7px 10px;
}
QPushButton:hover {
    background: #1a5fcc;
}
QComboBox, QLineEdit, QPlainTextEdit {
    background: #ffffff;
    border: 1px solid #b9c2cf;
    border-radius: 4px;
    padding: 5px;
}
QTableWidget {
    background: #ffffff;
    alternate-background-color: #f2f5f8;
    gridline-color: #d9e0e8;
    selection-background-color: #cfe3ff;
    selection-color: #17202a;
}
QHeaderView::section {
    background: #e9edf2;
    border: 0;
    border-right: 1px solid #d5dbe3;
    padding: 6px;
    font-weight: 600;
}
#tickerLabel {
    font-size: 22pt;
    font-weight: 700;
}
#statusLabel {
    color: #52616f;
}
#criteriaLabel {
    background: #eef3f8;
    border-radius: 4px;
    color: #263442;
    padding: 6px;
}
"""


def main() -> None:
    app = QApplication(sys.argv)
    window = MomentumHunterWindow()
    window.show()
    sys.exit(app.exec())
