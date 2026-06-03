from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QAbstractScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from momentum_hunter.config import AppConfig, load_config, save_config
from momentum_hunter.market import MarketRegimeSnapshot, detect_market_regime
from momentum_hunter.models import Candidate, CaptureSession, MarketRegime, SCANNER_PRESETS, TradingMode
from momentum_hunter.providers import provider_from_name
from momentum_hunter.scoring import score_candidates
from momentum_hunter.startup import install_startup_script, is_startup_installed
from momentum_hunter.storage import (
    candidate_from_dict,
    list_capture_dates,
    list_capture_sessions,
    load_capture_json,
    load_capture_report,
    load_latest_report,
    load_latest_watchlist,
    save_daily_capture,
    save_snapshot_report,
    save_watchlist,
    save_watchlist_report,
)
from momentum_hunter.time_utils import format_central, next_market_session, now_central
from momentum_hunter.ui.data_view_state import DataViewState, DataViewStyle, get_data_view_style


class MomentumHunterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.candidates: list[Candidate] = []
        self.saved_candidates: dict[str, Candidate] = {}
        self.reviewed_tickers: set[str] = set()
        self.live_candidates: list[Candidate] = []
        self.live_saved_candidates: dict[str, Candidate] = {}
        self.live_reviewed_tickers: set[str] = set()
        self.selected_ticker: str | None = None
        self.last_snapshot_key: str = ""
        self.data_view_state = DataViewState.CURRENT
        self.current_capture_time: datetime | None = None
        self.display_capture_time: datetime | None = None
        self.display_session_label = ""
        self.current_view_style: DataViewStyle | None = None
        self.market_regime = MarketRegimeSnapshot(
            regime=MarketRegime.UNKNOWN,
            symbol="SPY",
            reason="Not refreshed yet.",
        )

        self.setWindowTitle("Momentum Hunter")
        self.resize(1280, 780)
        self.setMinimumSize(980, 620)
        self._build_ui()
        self._apply_config_to_controls()
        self._ensure_windows_startup()
        self._load_capture_history()
        self._start_snapshot_timer()
        self._apply_data_view_state()
        self._update_status("Ready. Human review required before any trading decision.")

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_top_bar())

        self.view_state_label = QLabel()
        self.view_state_label.setObjectName("viewStateCurrent")
        layout.addWidget(self.view_state_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_candidate_panel())
        splitter.addWidget(self._build_research_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 520])
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

        self.save_button = QPushButton("Add Selected")
        self.save_button.clicked.connect(self.save_selected_candidates)

        self.clear_button = QPushButton("Clear Marks")
        self.clear_button.clicked.connect(self.clear_row_marks)

        self.watchlist_button = QPushButton("Generate Watchlist Report")
        self.watchlist_button.clicked.connect(self.save_tomorrow_watchlist)

        self.view_button = QPushButton("View Research List")
        self.view_button.clicked.connect(self.view_research_list)

        self.regime_combo = QComboBox()
        self.regime_combo.addItems([item.value for item in MarketRegime])
        self.regime_combo.currentTextChanged.connect(self._manual_regime_changed)

        self.regime_button = QPushButton("Refresh Regime")
        self.regime_button.clicked.connect(self.refresh_market_regime)

        self.capture_date_combo = QComboBox()
        self.capture_date_combo.currentTextChanged.connect(self._capture_date_changed)

        self.capture_session_combo = QComboBox()
        self.open_capture_button = QPushButton("Open Capture")
        self.open_capture_button.clicked.connect(self.open_selected_capture)

        self.current_button = QPushButton("Current Dashboard")
        self.current_button.clicked.connect(self.return_to_current_dashboard)

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
        layout.addWidget(self.clear_button, 0, 8)
        layout.addWidget(self.watchlist_button, 0, 9)
        layout.addWidget(self.view_button, 0, 10)
        layout.addWidget(self.clock_label, 1, 0, 1, 2)
        layout.addWidget(QLabel("Evening review: 7:00 PM - 8:00 PM CT"), 1, 2, 1, 3)
        layout.addWidget(QLabel("Morning review: 7:00 AM - 8:00 AM CT"), 1, 5, 1, 4)
        layout.addWidget(QLabel("Market"), 2, 0)
        layout.addWidget(self.regime_combo, 2, 1)
        layout.addWidget(self.regime_button, 2, 2)
        layout.addWidget(QLabel("History Date"), 2, 3)
        layout.addWidget(self.capture_date_combo, 2, 4)
        layout.addWidget(QLabel("Session"), 2, 5)
        layout.addWidget(self.capture_session_combo, 2, 6)
        layout.addWidget(self.open_capture_button, 2, 7)
        layout.addWidget(self.current_button, 2, 8, 1, 3)
        layout.addWidget(self.criteria_label, 3, 0, 1, 11)
        return box

    def _build_candidate_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["Pick", "Score", "Ticker", "Price", "% Chg", "Volume", "Rel Vol", "Market Cap", "Sector", "Industry"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self._set_table_widths()
        layout.addWidget(self.table)
        return panel

    def _build_research_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        identity = QGroupBox("Candidate")
        identity_layout = QGridLayout(identity)
        self.detail_state_label = QLabel("LIVE REVIEW CANDIDATE")
        self.detail_state_label.setObjectName("detailStateLabel")
        self.ticker_label = QLabel("No candidate selected")
        self.ticker_label.setObjectName("tickerLabel")
        self.company_label = QLabel("")
        self.score_label = QLabel("")
        self.reasons_label = QLabel("")
        self.reasons_label.setWordWrap(True)
        identity_layout.addWidget(self.detail_state_label, 0, 0, 1, 2)
        identity_layout.addWidget(self.ticker_label, 1, 0)
        identity_layout.addWidget(self.score_label, 1, 1)
        identity_layout.addWidget(self.company_label, 2, 0, 1, 2)
        identity_layout.addWidget(self.reasons_label, 3, 0, 1, 2)
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
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._scan_current_candidates()
            self.current_capture_time = now_central()
            self.display_capture_time = self.current_capture_time
            self.display_session_label = "live"
            self.data_view_state = DataViewState.CURRENT
            self.live_candidates = list(self.candidates)
            self.live_saved_candidates = dict(self.saved_candidates)
            self.live_reviewed_tickers = set(self.reviewed_tickers)
            self._apply_data_view_state()
            self._populate_table()
            self._update_status(f"Scan complete at {format_central()}. {len(self.candidates)} candidates found.")
        except Exception as exc:
            QMessageBox.warning(self, "Scanner Error", str(exc))
            self._update_status(f"Scanner failed: {exc}")
        finally:
            QApplication.restoreOverrideCursor()

    def _scan_current_candidates(self) -> None:
        criteria = SCANNER_PRESETS[self.scanner_combo.currentText()]
        provider = provider_from_name(self.provider_combo.currentText())
        self._update_status(f"Running {criteria.name} with {provider.name} provider...")
        candidates = provider.scan(criteria)
        for candidate in candidates:
            if not candidate.news:
                candidate.news = provider.fetch_news(candidate.ticker)
        self.candidates = score_candidates(candidates)

    def _populate_table(self) -> None:
        read_only = self._is_read_only_view()
        self.table.setRowCount(len(self.candidates))
        for row, candidate in enumerate(self.candidates):
            values = [
                "",
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
                    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                    if not read_only:
                        flags |= Qt.ItemFlag.ItemIsUserCheckable
                    item.setFlags(flags)
                    item.setCheckState(
                        Qt.CheckState.Checked if candidate.ticker in self.saved_candidates else Qt.CheckState.Unchecked
                    )
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(score_color(candidate.score))
                if candidate.ticker in self.reviewed_tickers:
                    item.setBackground(QBrush(QColor("#20394a" if self.data_view_state == DataViewState.CURRENT else "#3a314d")))
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
        self.reviewed_tickers.add(candidate.ticker)
        if self.data_view_state == DataViewState.CURRENT:
            self.live_reviewed_tickers.add(candidate.ticker)
        self._refresh_row_states()

    def _notes_changed(self) -> None:
        candidate = self._selected_candidate()
        if candidate is not None:
            candidate.user_notes = self.notes_edit.toPlainText()

    def save_selected_candidates(self) -> None:
        if self._is_read_only_view():
            self._update_status("This view is read-only. Run Scanner for fresh current data before staging picks.")
            return
        marked = self._marked_candidates()
        if not marked:
            candidate = self._selected_candidate()
            if candidate is None:
                self._update_status("Check one or more rows before adding to the watchlist.")
                return
            marked = [candidate]
        for candidate in marked:
            if candidate.ticker == self.selected_ticker:
                candidate.user_notes = self.notes_edit.toPlainText()
            candidate.saved_at = now_central()
            self.saved_candidates[candidate.ticker] = candidate
            self.live_saved_candidates[candidate.ticker] = candidate
            self.reviewed_tickers.add(candidate.ticker)
            self.live_reviewed_tickers.add(candidate.ticker)
        self._refresh_row_states()
        self._update_status(f"Added {len(marked)} candidate(s) to watchlist staging.")

    def clear_row_marks(self) -> None:
        if self._is_read_only_view():
            self._update_status("This view is read-only.")
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._update_status("Cleared row marks.")

    def save_tomorrow_watchlist(self) -> None:
        if self._is_read_only_view():
            self._update_status("Run Scanner for fresh current data before generating a watchlist.")
            return
        if not self.saved_candidates:
            self._update_status("No saved candidates yet.")
            return
        session_date = next_market_session()
        path = save_watchlist(list(self.saved_candidates.values()), session_date)
        report = save_watchlist_report(list(self.saved_candidates.values()), session_date)
        self.capture_daily_snapshot(session=CaptureSession.MANUAL, show_message=False)
        self._load_capture_history()
        QMessageBox.information(
            self,
            "Watchlist Report Generated",
            f"Saved {len(self.saved_candidates)} candidates.\n\nData:\n{path}\n\nReport:\n{report}",
        )
        self._update_status(f"Watchlist report generated: {report}")

    def view_research_list(self) -> None:
        report = load_latest_report()
        if report:
            self._show_text_dialog("Latest Research List", report)
            self._update_status("Opened latest saved research list.")
            return

        staged = load_latest_watchlist()
        if staged:
            fallback = "\n\n".join(
                [
                    f"{index}. {candidate.ticker} - {candidate.company} | Score {candidate.score}\n"
                    f"Price ${candidate.price:,.2f} | Change {candidate.percent_change:.1f}% | "
                    f"Notes: {candidate.user_notes or 'None'}"
                    for index, candidate in enumerate(staged, 1)
                ]
            )
            self._show_text_dialog("Latest Watchlist", fallback)
            self._update_status("Opened latest saved watchlist.")
            return

        self._show_text_dialog("Latest Research List", "No saved research list found yet.")
        self._update_status("No saved research list found.")

    def capture_daily_snapshot(self, session: CaptureSession | None = None, show_message: bool = True) -> None:
        candidates = self.candidates or list(self.saved_candidates.values())
        if not candidates:
            self._update_status("No scanned candidates available to capture.")
            return
        selected = {candidate.ticker for candidate in self._marked_candidates()} | set(self.saved_candidates)
        for candidate in candidates:
            if candidate.ticker in selected:
                self.saved_candidates[candidate.ticker] = candidate
        session = session or self._current_capture_session()
        if self.market_regime.regime == MarketRegime.UNKNOWN:
            self.refresh_market_regime(show_status=False)
        json_path, report_path = save_daily_capture(
            candidates=candidates,
            selected_tickers=selected,
            reviewed_tickers=self.reviewed_tickers,
            criteria=SCANNER_PRESETS[self.scanner_combo.currentText()],
            provider=self.provider_combo.currentText(),
            mode=self.config.mode,
            session=session,
            market_regime=self.market_regime,
        )
        self._load_capture_history()
        if show_message:
            QMessageBox.information(
                self,
                "Daily Capture Saved",
                f"Saved {session.value} capture.\n\nData:\n{json_path}\n\nReport:\n{report_path}",
            )
        self._update_status(f"Saved {session.value} capture: {report_path}")

    def _capture_snapshot(self, label: str) -> None:
        if not self.saved_candidates:
            return
        snapshot_time = now_central()
        key = snapshot_time.strftime("%Y-%m-%d-%H%M") + f"-{label}"
        if key == self.last_snapshot_key:
            return
        save_snapshot_report(list(self.saved_candidates.values()), snapshot_time=snapshot_time, label=label)
        self.last_snapshot_key = key

    def _start_snapshot_timer(self) -> None:
        self.snapshot_timer = QTimer(self)
        self.snapshot_timer.setInterval(60_000)
        self.snapshot_timer.timeout.connect(self._auto_snapshot_check)
        self.snapshot_timer.timeout.connect(self._refresh_current_freshness)
        self.snapshot_timer.start()

    def _auto_snapshot_check(self) -> None:
        current = now_central()
        in_evening = current.hour == 19 or (current.hour == 20 and current.minute == 0)
        in_morning = current.hour == 7 or (current.hour == 8 and current.minute == 0)
        if in_evening:
            self._auto_capture_once(CaptureSession.EVENING)
        elif in_morning:
            self._auto_capture_once(CaptureSession.MORNING)

    def _auto_capture_once(self, session: CaptureSession) -> None:
        key = now_central().strftime("%Y-%m-%d") + f"-{session.value}"
        if key == self.last_snapshot_key:
            return
        if not self.candidates:
            try:
                self._scan_current_candidates()
                self._populate_table()
            except Exception as exc:
                self._update_status(f"Auto scan failed before {session.value} capture: {exc}")
                return
        if self.candidates or self.saved_candidates:
            self.capture_daily_snapshot(session=session, show_message=False)
            self.last_snapshot_key = key

    def _refresh_current_freshness(self) -> None:
        if self.data_view_state != DataViewState.CURRENT:
            return
        old_read_only = self._is_read_only_view()
        self._apply_data_view_state()
        if old_read_only != self._is_read_only_view() and self.candidates:
            self._populate_table()

    def _load_capture_history(self) -> None:
        current_date = self.capture_date_combo.currentText()
        self.capture_date_combo.blockSignals(True)
        self.capture_date_combo.clear()
        dates = list_capture_dates()
        if not dates:
            self.capture_date_combo.addItem("No captures yet")
        for date_text in dates:
            self.capture_date_combo.addItem(date_text)
        if current_date and current_date in [self.capture_date_combo.itemText(i) for i in range(self.capture_date_combo.count())]:
            self.capture_date_combo.setCurrentText(current_date)
        self.capture_date_combo.blockSignals(False)
        self._capture_date_changed(self.capture_date_combo.currentText())

    def _capture_date_changed(self, value: str) -> None:
        current_session = self.capture_session_combo.currentText()
        self.capture_session_combo.blockSignals(True)
        self.capture_session_combo.clear()
        if not value or value == "No captures yet":
            self.capture_session_combo.addItem("No sessions yet")
            self.capture_session_combo.blockSignals(False)
            return
        for session in list_capture_sessions(value):
            self.capture_session_combo.addItem(session.value)
        if self.capture_session_combo.count() == 0:
            self.capture_session_combo.addItem("No sessions yet")
        if current_session and current_session in [
            self.capture_session_combo.itemText(i) for i in range(self.capture_session_combo.count())
        ]:
            self.capture_session_combo.setCurrentText(current_session)
        self.capture_session_combo.blockSignals(False)

    def open_selected_capture(self) -> None:
        date_text = self.capture_date_combo.currentText()
        session_text = self.capture_session_combo.currentText()
        if not date_text or not session_text or date_text == "No captures yet" or session_text == "No sessions yet":
            self._show_text_dialog("Daily Capture", "No daily capture is available yet.")
            return
        session = CaptureSession(session_text)
        payload = load_capture_json(date_text, session)
        if payload:
            self._load_historical_capture(payload)
            return
        report = load_capture_report(date_text, session)
        if not report:
            self._show_text_dialog("Daily Capture", "No report exists for that date and session.")
            return
        self._show_text_dialog(f"{date_text} {session_text.title()} Capture", report)

    def _load_historical_capture(self, payload: dict) -> None:
        self.data_view_state = DataViewState.HISTORICAL
        self.display_capture_time = datetime.fromisoformat(payload["capture_time"]) if payload.get("capture_time") else None
        self.display_session_label = payload.get("session", "snapshot")
        self.candidates = [candidate_from_dict(item) for item in payload.get("candidates", [])]
        self.saved_candidates = {
            item["ticker"]: candidate
            for item, candidate in zip(payload.get("candidates", []), self.candidates)
            if item.get("selected")
        }
        self.reviewed_tickers = {
            item["ticker"] for item in payload.get("candidates", []) if item.get("reviewed") or item.get("selected")
        }
        self.selected_ticker = None
        self._apply_data_view_state()
        self._populate_table()
        self._update_status("Loaded historical capture into the main table.")

    def return_to_current_dashboard(self) -> None:
        self.data_view_state = DataViewState.CURRENT
        self.display_capture_time = self.current_capture_time
        self.display_session_label = "live"
        self.candidates = list(self.live_candidates)
        self.saved_candidates = dict(self.live_saved_candidates)
        self.reviewed_tickers = set(self.live_reviewed_tickers)
        self.selected_ticker = None
        self._apply_data_view_state()
        self._populate_table()
        self._update_status("Returned to current dashboard. Run Scanner for fresh data.")

    def _apply_data_view_state(self) -> None:
        style = get_data_view_style(
            self.data_view_state,
            captured_at=self.display_capture_time,
            session_label=self.display_session_label,
        )
        self.current_view_style = style
        self.view_state_label.setObjectName(style.object_name)
        self.view_state_label.setText(style.banner_text)
        self.detail_state_label.setText(style.detail_label)
        self.table.horizontalHeader().setStyleSheet(style.header_stylesheet)
        read_only = style.read_only
        self.save_button.setEnabled(not read_only)
        self.clear_button.setEnabled(not read_only)
        self.watchlist_button.setEnabled(not read_only)
        self.notes_edit.setReadOnly(read_only)
        self.entry_trigger.setReadOnly(read_only)
        self.stop_level.setReadOnly(read_only)
        self.scan_button.setProperty("emphasized", style.state == DataViewState.STALE)
        self.scan_button.style().unpolish(self.scan_button)
        self.scan_button.style().polish(self.scan_button)
        self._refresh_view_state_style()

    def _refresh_view_state_style(self) -> None:
        self.view_state_label.style().unpolish(self.view_state_label)
        self.view_state_label.style().polish(self.view_state_label)

    def _is_read_only_view(self) -> bool:
        return bool(self.current_view_style and self.current_view_style.read_only)

    def refresh_market_regime(self, show_status: bool = True) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.market_regime = detect_market_regime()
            self.regime_combo.blockSignals(True)
            self.regime_combo.setCurrentText(self.market_regime.regime.value)
            self.regime_combo.blockSignals(False)
            if show_status:
                self._update_status(self.market_regime.reason)
        finally:
            QApplication.restoreOverrideCursor()

    def _manual_regime_changed(self, value: str) -> None:
        self.market_regime = MarketRegimeSnapshot(
            regime=MarketRegime(value),
            symbol="manual",
            reason=f"Manually set to {value}.",
        )

    def _current_capture_session(self) -> CaptureSession:
        current = now_central()
        if 5 <= current.hour < 12:
            return CaptureSession.MORNING
        if 12 <= current.hour <= 23:
            return CaptureSession.EVENING
        return CaptureSession.MANUAL

    def _ensure_windows_startup(self) -> None:
        if is_startup_installed():
            return
        try:
            install_startup_script(Path(__file__).resolve().parents[1])
        except Exception as exc:
            self._update_status(f"Could not install Windows startup launcher: {exc}")

    def _selected_candidate(self) -> Candidate | None:
        if self.selected_ticker is None:
            return None
        return next((candidate for candidate in self.candidates if candidate.ticker == self.selected_ticker), None)

    def _marked_candidates(self) -> list[Candidate]:
        marked: list[Candidate] = []
        for row, candidate in enumerate(self.candidates):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                marked.append(candidate)
        return marked

    def _refresh_row_states(self) -> None:
        for row, candidate in enumerate(self.candidates):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(
                    Qt.CheckState.Checked if candidate.ticker in self.saved_candidates else Qt.CheckState.Unchecked
                )
            if candidate.ticker in self.reviewed_tickers:
                for column in range(self.table.columnCount()):
                    cell = self.table.item(row, column)
                    if cell is not None and column != 1:
                        cell.setBackground(
                            QBrush(QColor("#20394a" if self.data_view_state == DataViewState.CURRENT else "#3a314d"))
                        )

    def _update_status(self, message: str) -> None:
        self.clock_label.setText(format_central())
        self.status_label.setText(message)

    def _set_table_widths(self) -> None:
        widths = [48, 58, 72, 88, 78, 116, 86, 104, 128, 180]
        for column, width in enumerate(widths):
            self.table.setColumnWidth(column, width)

    def _show_text_dialog(self, title: str, text: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(900, 700)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()


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
        return QColor("#1f6f4a")
    if score >= 70:
        return QColor("#285943")
    if score >= 50:
        return QColor("#735f24")
    return QColor("#6d3030")


STYLESHEET = """
QMainWindow, QWidget {
    background: #101820;
    color: #e7edf4;
    font-family: Segoe UI;
    font-size: 10pt;
}
QGroupBox {
    border: 1px solid #2d3b4a;
    border-radius: 6px;
    margin-top: 8px;
    padding: 8px;
    background: #162230;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
    color: #b9c8d8;
}
QPushButton {
    background: #2f80ed;
    color: #ffffff;
    border: 0;
    border-radius: 4px;
    padding: 7px 10px;
}
QPushButton:hover {
    background: #4392ff;
}
QPushButton[emphasized="true"] {
    background: #b83232;
    color: #fff4f4;
    font-weight: 700;
}
QComboBox, QLineEdit, QPlainTextEdit {
    background: #0f1720;
    color: #e7edf4;
    border: 1px solid #34475b;
    border-radius: 4px;
    padding: 5px;
}
QTableWidget {
    background: #0f1720;
    color: #e7edf4;
    alternate-background-color: #132030;
    gridline-color: #263648;
    selection-background-color: #315f88;
    selection-color: #ffffff;
}
QHeaderView::section {
    background: #243445;
    color: #e8eef6;
    border: 0;
    border-right: 1px solid #35485d;
    padding: 6px;
    font-weight: 600;
}
#tickerLabel {
    font-size: 22pt;
    font-weight: 700;
}
#statusLabel {
    color: #9cb0c4;
}
#criteriaLabel {
    background: #18283a;
    border-radius: 4px;
    color: #cbd8e6;
    padding: 6px;
}
#viewStateCurrent {
    background: #123222;
    border: 1px solid #1f6f4a;
    border-radius: 6px;
    color: #d8ffe8;
    font-weight: 700;
    padding: 8px;
}
#viewStateAging {
    background: #3a3117;
    border: 1px solid #a4812a;
    border-radius: 6px;
    color: #fff0bd;
    font-weight: 700;
    padding: 8px;
}
#viewStateStale {
    background: #3a1717;
    border: 1px solid #a14646;
    border-radius: 6px;
    color: #ffe1e1;
    font-weight: 700;
    padding: 8px;
}
#viewStateHistorical {
    background: #2b1f36;
    border: 1px solid #6d5780;
    border-radius: 6px;
    color: #f4ecff;
    font-weight: 700;
    padding: 8px;
}
#viewStateStudy {
    background: #172746;
    border: 1px solid #3c5d9d;
    border-radius: 6px;
    color: #eaf1ff;
    font-weight: 700;
    padding: 8px;
}
#detailStateLabel {
    background: #1b2a3a;
    border-radius: 4px;
    color: #cbd8e6;
    font-weight: 700;
    padding: 5px;
}
"""


def main() -> None:
    app = QApplication(sys.argv)
    window = MomentumHunterWindow()
    window.show()
    sys.exit(app.exec())
