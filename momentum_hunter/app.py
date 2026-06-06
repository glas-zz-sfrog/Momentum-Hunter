from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QPainter, QPixmap
from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QValueAxis
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGraphicsSimpleTextItem,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QAbstractScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from momentum_hunter.capture_health import (
    CaptureFailureInfo,
    CaptureSuccessInfo,
    CsvStatus,
    build_capture_health_snapshot,
)
from momentum_hunter.config import AppConfig, load_config, save_config
from momentum_hunter.market import MarketRegimeSnapshot, detect_market_regime
from momentum_hunter.models import Candidate, CaptureSession, MarketRegime, SCANNER_PRESETS, TradingMode
from momentum_hunter.news_age import (
    apply_candidate_news_stack,
    evaluate_news_freshness,
    format_news_age,
    news_stack_badge,
    news_stack_summary,
)
from momentum_hunter.providers import ProviderUnavailableError, provider_from_name
from momentum_hunter.recommendations import RecommendationReport, build_weight_recommendations
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
from momentum_hunter.study import (
    FILTER_ALL,
    FILTER_REVIEWED,
    FILTER_SELECTED,
    REGIME_ALL,
    SESSION_ALL,
    StudyFilter,
    StudySummary,
    build_capture_study,
)
from momentum_hunter.time_utils import format_central, next_market_session, now_central
from momentum_hunter.ui.data_view_state import DataViewState, DataViewStyle, get_data_view_style


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_LOGO_PATH = PROJECT_ROOT / "assets" / "momentum_hunter_logo.jpg"


class WatermarkWidget(QWidget):
    def __init__(self, watermark_path: Path) -> None:
        super().__init__()
        self.watermark = QPixmap(str(watermark_path)) if watermark_path.exists() else QPixmap()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.watermark.isNull():
            return
        max_width = max(240, min(520, int(self.width() * 0.34)))
        max_height = max(280, min(620, int(self.height() * 0.62)))
        scaled = self.watermark.scaled(
            max_width,
            max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = int((self.width() - scaled.width()) / 2)
        y = int((self.height() - scaled.height()) / 2) + 36
        painter = QPainter(self)
        painter.setOpacity(0.055)
        painter.drawPixmap(x, y, scaled)


class WatermarkTableWidget(QTableWidget):
    def __init__(self, rows: int, columns: int, watermark_path: Path) -> None:
        super().__init__(rows, columns)
        self.watermark = QPixmap(str(watermark_path)) if watermark_path.exists() else QPixmap()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.watermark.isNull():
            return
        viewport = self.viewport()
        max_width = max(275, min(575, int(viewport.width() * 0.52)))
        max_height = max(325, min(650, int(viewport.height() * 0.88)))
        scaled = self.watermark.scaled(
            max_width,
            max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = int((viewport.width() - scaled.width()) / 2)
        y = int((viewport.height() - scaled.height()) / 2)
        painter = QPainter(viewport)
        painter.setOpacity(0.045)
        painter.drawPixmap(x, y, scaled)


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
        self.provider_status_text = "Provider: not checked"
        self.provider_status_ok = True
        self.market_regime = MarketRegimeSnapshot(
            regime=MarketRegime.UNKNOWN,
            symbol="SPY",
            reason="Not refreshed yet.",
        )

        self.setWindowTitle("Momentum Hunter")
        if APP_LOGO_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_LOGO_PATH)))
        self.resize(1280, 780)
        self.setMinimumSize(980, 620)
        self._build_ui()
        self._apply_config_to_controls()
        self._ensure_windows_startup()
        self._load_capture_history()
        self._refresh_capture_health()
        self._start_snapshot_timer()
        self._apply_data_view_state()
        self._update_status("Ready. Human review required before any trading decision.")

    def _build_ui(self) -> None:
        root = WatermarkWidget(APP_LOGO_PATH)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_top_bar())

        self.view_state_label = QLabel()
        self.view_state_label.setObjectName("viewStateCurrent")
        layout.addWidget(self.view_state_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_candidate_panel())
        research_scroll = QScrollArea()
        research_scroll.setWidgetResizable(True)
        research_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        research_scroll.setWidget(self._build_research_panel())
        splitter.addWidget(research_scroll)
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

        self.watchlist_button = QPushButton("Watchlist Report")
        self.watchlist_button.clicked.connect(self.save_tomorrow_watchlist)

        self.view_button = QPushButton("Research List")
        self.view_button.clicked.connect(self.view_research_list)

        self.regime_combo = QComboBox()
        self.regime_combo.addItems([item.value for item in MarketRegime])
        self.regime_combo.currentTextChanged.connect(self._manual_regime_changed)

        self.regime_button = QPushButton("Refresh Regime")
        self.regime_button.clicked.connect(self.refresh_market_regime)

        self.capture_date_combo = QComboBox()
        self.capture_date_combo.currentTextChanged.connect(self._capture_date_changed)

        self.capture_session_combo = QComboBox()
        self.open_capture_button = QPushButton("Open Snapshot")
        self.open_capture_button.clicked.connect(self.open_selected_capture)

        self.current_button = QPushButton("Current")
        self.current_button.clicked.connect(self.return_to_current_dashboard)

        self.study_button = QPushButton("Study Engine")
        self.study_button.clicked.connect(self.open_study_engine)

        self.clock_label = QLabel(format_central())
        self.criteria_label = QLabel()
        self.criteria_label.setObjectName("criteriaLabel")
        self.brand_logo = QLabel()
        self.brand_logo.setObjectName("brandLogo")
        self.brand_logo.setToolTip("Momentum Hunter")
        if APP_LOGO_PATH.exists():
            self.brand_logo.setPixmap(contained_logo_pixmap(APP_LOGO_PATH, 76, 76))
        self.brand_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.brand_logo.setFixedSize(82, 82)

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
        layout.addWidget(self.current_button, 2, 8)
        layout.addWidget(self.study_button, 2, 9, 1, 2)
        layout.addWidget(self.brand_logo, 0, 11, 3, 1)
        layout.addWidget(self.criteria_label, 3, 0, 1, 12)
        return box

    def _build_candidate_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        self.table = WatermarkTableWidget(0, 11, APP_LOGO_PATH)
        self.table.setHorizontalHeaderLabels(
            ["Pick", "Score", "News Stack", "Ticker", "Price", "% Chg", "Volume", "Rel Vol", "Market Cap", "Sector", "Industry"]
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
        layout.setSpacing(6)

        identity = QGroupBox("Candidate")
        identity_layout = QGridLayout(identity)
        self.detail_state_label = QLabel("LIVE REVIEW CANDIDATE")
        self.detail_state_label.setObjectName("detailStateLabel")
        self.ticker_label = QLabel("No candidate selected")
        self.ticker_label.setObjectName("tickerLabel")
        self.company_label = QLabel("")
        self.score_label = QLabel("")
        self.news_stack_label = QLabel("")
        self.news_stack_label.setWordWrap(True)
        self.reasons_label = QLabel("")
        self.reasons_label.setWordWrap(True)
        identity_layout.addWidget(self.detail_state_label, 0, 0, 1, 2)
        identity_layout.addWidget(self.ticker_label, 1, 0)
        identity_layout.addWidget(self.score_label, 1, 1)
        identity_layout.addWidget(self.company_label, 2, 0, 1, 2)
        identity_layout.addWidget(self.news_stack_label, 3, 0, 1, 2)
        identity_layout.addWidget(self.reasons_label, 4, 0, 1, 2)
        layout.addWidget(identity)

        health_box = QGroupBox("Capture Health")
        health_layout = QVBoxLayout(health_box)
        self.provider_status_label = QLabel(self.provider_status_text)
        self.provider_status_label.setWordWrap(True)
        self.last_morning_capture_label = QLabel("Last morning capture: checking...")
        self.last_morning_capture_label.setWordWrap(True)
        self.last_evening_capture_label = QLabel("Last evening capture: checking...")
        self.last_evening_capture_label.setWordWrap(True)
        self.capture_failure_label = QLabel("Scheduled captures: no failures recorded.")
        self.capture_failure_label.setWordWrap(True)
        self.next_capture_label = QLabel("Next scheduled runs: checking...")
        self.next_capture_label.setWordWrap(True)
        self.csv_append_label = QLabel("CSV append: checking...")
        self.csv_append_label.setWordWrap(True)
        self.outcome_update_label = QLabel("Outcome update: checking...")
        self.outcome_update_label.setWordWrap(True)
        self.retry_scan_button = QPushButton("Retry Scan")
        self.retry_scan_button.clicked.connect(self.run_scan)
        self.retry_scan_button.hide()
        health_layout.addWidget(self.provider_status_label)
        health_layout.addWidget(self.last_morning_capture_label)
        health_layout.addWidget(self.last_evening_capture_label)
        health_layout.addWidget(self.capture_failure_label)
        health_layout.addWidget(self.next_capture_label)
        health_layout.addWidget(self.csv_append_label)
        health_layout.addWidget(self.outcome_update_label)
        health_layout.addWidget(self.retry_scan_button)
        layout.addWidget(health_box)

        chart_box = QGroupBox("Momentum Chart")
        chart_layout = QVBoxLayout(chart_box)
        self.chart_state_label = QLabel("STALE - Top Momentum Candidates")
        self.chart_state_label.setObjectName("chartStateLabel")
        self.score_chart = QChart()
        self.score_chart.legend().hide()
        self.score_chart.setBackgroundVisible(False)
        self.score_chart.plotAreaChanged.connect(self._position_chart_watermark)
        self.chart_watermark = QGraphicsSimpleTextItem(self.score_chart)
        self.chart_watermark.setBrush(QBrush(QColor("#cbd8e6")))
        self.chart_watermark.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.chart_watermark.setOpacity(0.28)
        self.score_chart_view = QChartView(self.score_chart)
        self.score_chart_view.setMinimumHeight(180)
        chart_layout.addWidget(self.chart_state_label)
        chart_layout.addWidget(self.score_chart_view)
        layout.addWidget(chart_box, 1)

        news_box = QGroupBox("News & Catalysts")
        news_layout = QVBoxLayout(news_box)
        self.news_text = QTextBrowser()
        self.news_text.setOpenExternalLinks(True)
        self.news_text.setMinimumHeight(88)
        self.news_text.setPlaceholderText("Select a candidate to review headlines.")
        news_layout.addWidget(self.news_text)
        layout.addWidget(news_box, 2)

        notes_box = QGroupBox("Candidate Notes")
        notes_layout = QVBoxLayout(notes_box)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setMaximumHeight(72)
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
        self.provider_status_text = f"Provider: {value} not checked"
        self.provider_status_ok = True
        if hasattr(self, "retry_scan_button"):
            self.retry_scan_button.hide()
        self._refresh_capture_health()
        self._update_status(f"Provider set to {value}.")

    def _scanner_changed(self, value: str) -> None:
        criteria = SCANNER_PRESETS[value]
        self.criteria_label.setText(
            "Scanner thresholds: "
            f"Volume >= {criteria.min_volume:,} | "
            f"Change >= {criteria.min_percent_change:.1f}% | "
            f"Market Cap >= {format_market_cap(criteria.min_market_cap)} | "
            f"Price >= ${criteria.min_price:,.2f} | "
            f"Relative Volume >= {criteria.min_relative_volume:.2f}x | "
            "Scoring: regime-aware-v1"
        )

    def run_scan(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._update_status(f"Running {self.scanner_combo.currentText()} with {self.provider_combo.currentText()} provider...")
            result = self._scan_current_candidates()
            if result is None:
                candidates = self.candidates
                scan_time = now_central()
            else:
                candidates, scan_time = result
            self.candidates = candidates
            self.current_capture_time = scan_time
            self.display_capture_time = self.current_capture_time
            self.display_session_label = "live"
            self.data_view_state = DataViewState.CURRENT
            self.live_candidates = list(self.candidates)
            self.live_saved_candidates = dict(self.saved_candidates)
            self.live_reviewed_tickers = set(self.reviewed_tickers)
            self.provider_status_text = f"Provider: {self.provider_combo.currentText()} OK at {format_central(scan_time)}"
            self.provider_status_ok = True
            self.retry_scan_button.hide()
            self._apply_data_view_state()
            self._refresh_capture_health()
            self._populate_table()
            self._update_score_chart()
            self._update_status(f"Scan complete at {format_central()}. {len(self.candidates)} candidates found.")
        except ProviderUnavailableError as exc:
            self.provider_status_text = f"Provider: {exc.user_message}"
            self.provider_status_ok = False
            self.retry_scan_button.show()
            self._refresh_capture_health()
            self._apply_data_view_state()
            QMessageBox.warning(self, "Scanner Error", exc.user_message)
            self._update_status(f"{exc.user_message} Old data was left in place.")
        except Exception as exc:
            self.provider_status_text = f"Provider: scanner failed. {exc}"
            self.provider_status_ok = False
            self.retry_scan_button.show()
            self._refresh_capture_health()
            self._apply_data_view_state()
            QMessageBox.warning(self, "Scanner Error", "Scanner failed. Old data was left in place.")
            self._update_status(f"Scanner failed. Old data was left in place. Detail: {exc}")
        finally:
            QApplication.restoreOverrideCursor()

    def _scan_current_candidates(self) -> tuple[list[Candidate], datetime] | None:
        if self.market_regime.regime == MarketRegime.UNKNOWN:
            self.refresh_market_regime(show_status=False)
        scan_time = now_central()
        criteria = SCANNER_PRESETS[self.scanner_combo.currentText()]
        provider = provider_from_name(self.provider_combo.currentText())
        self._update_status(f"Running {criteria.name} with {provider.name} provider...")
        candidates = provider.scan(criteria)
        for candidate in candidates:
            if not candidate.news:
                candidate.news = provider.fetch_news(candidate.ticker, as_of=scan_time)
        return score_candidates(candidates, regime=self.market_regime.regime, now=scan_time), scan_time

    def _populate_table(self) -> None:
        read_only = self._is_read_only_view()
        self.table.clearSelection()
        self.selected_ticker = None
        self.table.setRowCount(len(self.candidates))
        for row, candidate in enumerate(self.candidates):
            if candidate.news and candidate.news_stack.article_count == 0:
                apply_candidate_news_stack(candidate, now=self.display_capture_time)
            values = [
                "",
                str(candidate.score),
                news_stack_badge(candidate),
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
                elif column == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(freshness_color(candidate.news_stack.freshness))
                if candidate.ticker in self.reviewed_tickers and column not in (1, 2):
                    item.setBackground(QBrush(QColor("#20394a" if self.data_view_state == DataViewState.CURRENT else "#3a314d")))
                self.table.setItem(row, column, item)
        if self.candidates:
            self.table.selectRow(0)
            self._selection_changed()
        else:
            self._clear_candidate_details()
        self._update_score_chart()

    def _selection_changed(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        candidate = self.candidates[rows[0].row()]
        self._show_candidate_details(candidate)

    def _show_candidate_details(self, candidate: Candidate) -> None:
        self.selected_ticker = candidate.ticker
        self.ticker_label.setText(candidate.ticker)
        self.company_label.setText(candidate.company)
        self.score_label.setText(
            f"Momentum: {candidate.score} | Freshness: {candidate.news_stack.freshness_score} {candidate.news_stack.freshness}"
        )
        self.news_stack_label.setText(" | ".join(news_stack_summary(candidate)))
        self.reasons_label.setText(", ".join(candidate.score_reasons) or "No score reasons yet.")
        self.notes_edit.blockSignals(True)
        self.notes_edit.setPlainText(candidate.user_notes)
        self.notes_edit.blockSignals(False)
        self.news_text.setHtml(format_news_html(candidate, now=self.display_capture_time))
        self.reviewed_tickers.add(candidate.ticker)
        if self.data_view_state == DataViewState.CURRENT:
            self.live_reviewed_tickers.add(candidate.ticker)
        self._refresh_row_states()

    def _clear_candidate_details(self, message: str = "No candidate selected") -> None:
        self.selected_ticker = None
        self.ticker_label.setText(message)
        self.company_label.setText("")
        self.score_label.setText("")
        self.news_stack_label.setText("")
        self.reasons_label.setText("")
        self.notes_edit.blockSignals(True)
        self.notes_edit.clear()
        self.notes_edit.blockSignals(False)
        self.news_text.clear()
        self.entry_trigger.clear()
        self.stop_level.clear()

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
        self._refresh_capture_health()
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
        self.snapshot_timer.timeout.connect(self._refresh_capture_health)
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
                result = self._scan_current_candidates()
                if result is not None:
                    self.candidates, self.current_capture_time = result
                    self.display_capture_time = self.current_capture_time
                    self.provider_status_text = f"Provider: {self.provider_combo.currentText()} OK at {format_central(self.current_capture_time)}"
                    self.provider_status_ok = True
                    self.retry_scan_button.hide()
                    self._refresh_capture_health()
                self._populate_table()
            except ProviderUnavailableError as exc:
                self.provider_status_text = f"Provider: {exc.user_message}"
                self.provider_status_ok = False
                self.retry_scan_button.show()
                self._refresh_capture_health()
                self._update_status(f"Auto scan failed before {session.value} capture: {exc.user_message}")
                return
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

    def _refresh_capture_health(self) -> None:
        if not hasattr(self, "provider_status_label"):
            return
        health = build_capture_health_snapshot()
        self.provider_status_label.setText(self.provider_status_text)
        self.provider_status_label.setStyleSheet(
            "color: #a7f3d0; font-weight: 600;" if self.provider_status_ok else "color: #fecaca; font-weight: 700;"
        )
        self.last_morning_capture_label.setText(format_capture_success("Last successful morning", health.last_morning_capture))
        self.last_evening_capture_label.setText(format_capture_success("Last successful evening", health.last_evening_capture))
        if health.last_morning_capture.capture_time:
            self.last_morning_capture_label.setStyleSheet("color: #cbd8e6;")
        else:
            self.last_morning_capture_label.setStyleSheet("color: #fcd34d; font-weight: 700;")
        if health.last_evening_capture.capture_time:
            self.last_evening_capture_label.setStyleSheet("color: #cbd8e6;")
        else:
            self.last_evening_capture_label.setStyleSheet("color: #fcd34d; font-weight: 700;")

        self.capture_failure_label.setText(format_capture_failure(health.last_failed_capture))
        if health.last_failed_capture.failure_time:
            self.capture_failure_label.setStyleSheet("color: #fcd34d; font-weight: 700;")
        else:
            self.capture_failure_label.setStyleSheet("color: #cbd8e6;")
        self.next_capture_label.setText(
            "Next scheduled runs: "
            f"Morning {format_central(health.next_morning_run)} | "
            f"Evening {format_central(health.next_evening_run)}"
        )
        self.next_capture_label.setStyleSheet("color: #cbd8e6;")
        self.csv_append_label.setText(format_csv_status("CSV append", health.csv_append_status))
        self.csv_append_label.setStyleSheet("color: #cbd8e6;" if health.csv_append_status.exists else "color: #fcd34d; font-weight: 700;")
        self.outcome_update_label.setText(format_csv_status("Outcome update", health.outcome_update_status))
        self.outcome_update_label.setStyleSheet(
            "color: #cbd8e6;" if health.outcome_update_status.exists else "color: #fcd34d; font-weight: 700;"
        )

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

    def open_study_engine(self) -> None:
        summary = build_capture_study()
        self._show_study_dialog(summary)

    def _load_historical_capture(self, payload: dict) -> None:
        self.data_view_state = DataViewState.HISTORICAL
        self.display_capture_time = datetime.fromisoformat(payload["capture_time"]) if payload.get("capture_time") else None
        self.display_session_label = payload.get("session", "snapshot")
        self.candidates = [candidate_from_dict(item) for item in payload.get("candidates", [])]
        for raw_candidate, candidate in zip(payload.get("candidates", []), self.candidates):
            if not raw_candidate.get("news_stack"):
                apply_candidate_news_stack(candidate, now=self.display_capture_time)
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
        self._update_score_chart()
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
        self._update_score_chart()
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
        self.chart_state_label.setText(f"{style.chart_prefix}Top Momentum Candidates")
        self._set_chart_watermark(style)
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
        self._update_score_chart()

    def _refresh_view_state_style(self) -> None:
        self.view_state_label.style().unpolish(self.view_state_label)
        self.view_state_label.style().polish(self.view_state_label)

    def _is_read_only_view(self) -> bool:
        return bool(self.current_view_style and self.current_view_style.read_only)

    def _update_score_chart(self) -> None:
        if not hasattr(self, "score_chart"):
            return
        self.score_chart.removeAllSeries()
        for axis in list(self.score_chart.axes()):
            self.score_chart.removeAxis(axis)

        top_candidates = sorted(self.candidates, key=lambda item: item.score, reverse=True)[:8]
        if not top_candidates:
            self.score_chart.setTitle("No candidates loaded")
            return

        style = self.current_view_style or get_data_view_style(
            self.data_view_state,
            captured_at=self.display_capture_time,
            session_label=self.display_session_label,
        )
        self.score_chart.setTitle(f"{style.chart_prefix}Candidate Scores")
        self.score_chart.setTitleBrush(QBrush(QColor("#e7edf4")))
        self._set_chart_watermark(style)

        score_set = QBarSet("Score")
        score_set.setColor(chart_bar_color(style.state))
        for candidate in top_candidates:
            score_set.append(candidate.score)

        series = QBarSeries()
        series.append(score_set)
        self.score_chart.addSeries(series)

        category_axis = QBarCategoryAxis()
        category_axis.append([candidate.ticker for candidate in top_candidates])
        category_axis.setLabelsColor(QColor("#cbd8e6"))

        value_axis = QValueAxis()
        value_axis.setRange(0, 100)
        value_axis.setTickCount(6)
        value_axis.setLabelsColor(QColor("#cbd8e6"))

        self.score_chart.addAxis(category_axis, Qt.AlignmentFlag.AlignBottom)
        self.score_chart.addAxis(value_axis, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(category_axis)
        series.attachAxis(value_axis)

        self.score_chart.setPlotAreaBackgroundVisible(True)
        self.score_chart.setPlotAreaBackgroundBrush(QBrush(QColor("#0f1720")))
        self._position_chart_watermark()

    def _set_chart_watermark(self, style: DataViewStyle) -> None:
        label = {
            DataViewState.CURRENT: "LIVE DATA" if not style.is_warning else "AGING DATA",
            DataViewState.STALE: "STALE DATA",
            DataViewState.HISTORICAL: "HISTORICAL",
            DataViewState.STUDY: "SIMULATED",
        }[style.state]
        self.chart_watermark.setText(label)
        self.chart_watermark.setBrush(QBrush(chart_badge_color(style.state, style.is_warning)))
        self._position_chart_watermark()

    def _position_chart_watermark(self) -> None:
        if not hasattr(self, "chart_watermark"):
            return
        area = self.score_chart.plotArea()
        if area.isNull():
            self.chart_watermark.setPos(24, 44)
            return
        self.chart_watermark.setPos(area.left() + 14, area.top() + 10)

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
                    if cell is not None and column not in (1, 2):
                        cell.setBackground(
                            QBrush(QColor("#20394a" if self.data_view_state == DataViewState.CURRENT else "#3a314d"))
                        )

    def _update_status(self, message: str) -> None:
        self.clock_label.setText(format_central())
        self.status_label.setText(message)

    def _set_table_widths(self) -> None:
        widths = [48, 62, 190, 72, 88, 78, 116, 86, 104, 128, 180]
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

    def _show_study_dialog(self, summary: StudySummary) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Momentum Hunter Study Engine")
        dialog.resize(980, 760)
        layout = QVBoxLayout(dialog)

        style = get_data_view_style(
            DataViewState.STUDY,
            captured_at=None,
            study_run_id=summary.run_id,
            source_range=summary.source_range,
        )
        banner = QLabel(style.banner_text)
        banner.setObjectName(style.object_name)
        banner.setWordWrap(True)
        layout.addWidget(banner)

        filter_row = QWidget()
        filter_layout = QHBoxLayout(filter_row)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.addWidget(QLabel("Study Filter"))
        filter_combo = QComboBox()
        filter_combo.addItems([FILTER_ALL, FILTER_SELECTED, FILTER_REVIEWED])
        filter_layout.addWidget(filter_combo)
        filter_layout.addWidget(QLabel("Start"))
        start_date_edit = QLineEdit()
        start_date_edit.setPlaceholderText("YYYY-MM-DD")
        filter_layout.addWidget(start_date_edit)
        filter_layout.addWidget(QLabel("End"))
        end_date_edit = QLineEdit()
        end_date_edit.setPlaceholderText("YYYY-MM-DD")
        filter_layout.addWidget(end_date_edit)
        filter_layout.addWidget(QLabel("Session"))
        session_combo = QComboBox()
        session_combo.addItems([SESSION_ALL, "morning", "evening", "manual"])
        filter_layout.addWidget(session_combo)
        filter_layout.addWidget(QLabel("Regime"))
        regime_combo = QComboBox()
        regime_combo.addItems([REGIME_ALL, "bull", "bear", "neutral", "unknown"])
        filter_layout.addWidget(regime_combo)
        filter_layout.addStretch(1)
        layout.addWidget(filter_row)

        stats = QLabel()
        stats.setObjectName("criteriaLabel")
        layout.addWidget(stats)

        chart_tabs = QTabWidget()
        layout.addWidget(chart_tabs, 2)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        bucket_table = QTableWidget(0, 6)
        bucket_table.setHorizontalHeaderLabels(
            ["Score Bucket", "Candidates", "Selected", "Reviewed", "Next Avg", "5-Day Avg"]
        )
        bucket_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        bucket_table.horizontalHeader().setStyleSheet(style.header_stylesheet)
        bucket_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        regime_table = QTableWidget(0, 2)
        regime_table.setHorizontalHeaderLabels(["Market Regime", "Candidates"])
        regime_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        regime_table.horizontalHeader().setStyleSheet(style.header_stylesheet)
        regime_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        splitter.addWidget(bucket_table)
        splitter.addWidget(regime_table)
        splitter.setSizes([620, 320])
        layout.addWidget(splitter, 2)

        def current_study_filter() -> StudyFilter:
            return StudyFilter(
                row_filter=filter_combo.currentText(),
                start_date=start_date_edit.text().strip(),
                end_date=end_date_edit.text().strip(),
                session=session_combo.currentText(),
                regime=regime_combo.currentText(),
            )

        def refresh_study_view() -> None:
            filtered = build_capture_study(study_filter=current_study_filter())
            filtered_style = get_data_view_style(
                DataViewState.STUDY,
                captured_at=None,
                study_run_id=filtered.run_id,
                source_range=filtered.source_range,
            )
            banner.setText(filtered_style.banner_text)
            stats.setText(study_stats_text(filtered))

            chart_tabs.clear()
            chart_tabs.addTab(build_study_chart(filtered, filtered_style), "Coverage")
            chart_tabs.addTab(build_outcome_chart(filtered, filtered_style), "Outcomes")
            chart_tabs.addTab(build_recommendation_panel(build_weight_recommendations(), filtered_style), "Recommendations")

            bucket_table.setRowCount(len(filtered.score_buckets))
            for row, bucket in enumerate(filtered.score_buckets):
                values = [
                    bucket.label,
                    str(bucket.count),
                    str(bucket.selected_count),
                    str(bucket.reviewed_count),
                    format_percent(bucket.avg_next_day_return_pct),
                    format_percent(bucket.avg_five_day_return_pct),
                ]
                for column, value in enumerate(values):
                    bucket_table.setItem(row, column, QTableWidgetItem(value))

            regime_table.setRowCount(len(filtered.regimes))
            for row, regime in enumerate(filtered.regimes):
                regime_table.setItem(row, 0, QTableWidgetItem(regime.regime))
                regime_table.setItem(row, 1, QTableWidgetItem(str(regime.count)))

        filter_combo.currentTextChanged.connect(refresh_study_view)
        start_date_edit.editingFinished.connect(refresh_study_view)
        end_date_edit.editingFinished.connect(refresh_study_view)
        session_combo.currentTextChanged.connect(refresh_study_view)
        regime_combo.currentTextChanged.connect(refresh_study_view)
        refresh_study_view()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.setStyleSheet(STYLESHEET)
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


def format_capture_success(label: str, info: CaptureSuccessInfo) -> str:
    if info.capture_time is None:
        return f"{label}: missing"
    scanner = f" | {info.scanner}" if info.scanner else ""
    provider = f" | {info.provider}" if info.provider else ""
    return f"{label}: {format_central(info.capture_time)} | {info.candidate_count} candidates{provider}{scanner}"


def format_capture_failure(info: CaptureFailureInfo) -> str:
    if info.failure_time is None:
        return "Last failed capture: none recorded."
    session = info.session or "unknown session"
    provider = info.provider or "unknown provider"
    message = info.error_message or "unknown failure"
    return f"Last failed capture: {format_central(info.failure_time)} | {session} | {provider} | {message}"


def format_csv_status(label: str, status: CsvStatus) -> str:
    if not status.exists:
        return f"{label}: missing"
    updated = format_central(status.last_updated) if status.last_updated else "unknown time"
    return f"{label}: OK | {status.row_count} rows | updated {updated}"


def format_news_html(candidate: Candidate, now: datetime | None = None) -> str:
    if not candidate.news:
        return "<p>No headlines loaded. Review news manually before trading.</p>"
    blocks = []
    for item in candidate.news:
        headline = escape(item.headline)
        source = f" <span class='source'>({escape(item.source)})</span>" if item.source else ""
        if item.url:
            headline = f"<a href='{escape(item.url, quote=True)}'>{headline}</a>"
        age = ""
        if item.published_at:
            freshness = evaluate_news_freshness(
                ticker=candidate.ticker,
                headline=item.headline,
                publish_time=item.published_at,
                now=now,
            )
            age = (
                f"<div class='age'>{escape(freshness.freshness)} "
                f"{freshness.score} | Age: {escape(format_news_age(freshness.hours_old))}</div>"
            )
        summary = f"<div class='summary'>{escape(item.summary)}</div>" if item.summary else ""
        blocks.append(f"<li>{headline}{source}{age}{summary}</li>")
    return (
        "<style>"
        "body { color: #e7edf4; background: #0f1720; font-family: Segoe UI; font-size: 10pt; }"
        "a { color: #7fb4ff; text-decoration: none; font-weight: 600; }"
        "a:hover { text-decoration: underline; }"
        ".source { color: #9cb0c4; }"
        ".age { color: #f3d28b; margin-top: 3px; font-size: 9pt; }"
        ".summary { color: #cbd8e6; margin-top: 4px; margin-bottom: 10px; }"
        "li { margin-bottom: 10px; }"
        "</style>"
        f"<ul>{''.join(blocks)}</ul>"
    )


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


def freshness_color(freshness: str) -> QColor:
    if freshness == "HOT":
        return QColor("#8a2e2e")
    if freshness == "ACTIVE":
        return QColor("#735f24")
    if freshness == "STALE":
        return QColor("#2c4f73")
    return QColor("#334155")


def chart_bar_color(state: DataViewState) -> QColor:
    if state == DataViewState.HISTORICAL:
        return QColor("#8f6bb5")
    if state == DataViewState.STUDY:
        return QColor("#5f86d9")
    if state == DataViewState.STALE:
        return QColor("#c24d4d")
    return QColor("#2f9d68")


def chart_badge_color(state: DataViewState, is_warning: bool = False) -> QColor:
    if state == DataViewState.HISTORICAL:
        return QColor("#f4ecff")
    if state == DataViewState.STUDY:
        return QColor("#eaf1ff")
    if state == DataViewState.STALE:
        return QColor("#ffe1e1")
    if is_warning:
        return QColor("#fff0bd")
    return QColor("#d8ffe8")


def contained_logo_pixmap(path: Path, width: int, height: int) -> QPixmap:
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        width,
        height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def study_stats_text(summary: StudySummary) -> str:
    return (
        f"Captures: {summary.capture_count} | Candidates: {summary.candidate_count} | "
        f"Selected: {summary.selected_count} | Reviewed: {summary.reviewed_count} | "
        f"Profiles: {', '.join(summary.scoring_profiles) or 'n/a'} | "
        f"Outcome Rows: {summary.outcome_count} | Complete 5-Day Outcomes: {summary.complete_outcome_count} | "
        f"Next-Day Avg: {format_percent(summary.avg_next_day_return_pct)} | "
        f"5-Day Avg: {format_percent(summary.avg_five_day_return_pct)} | "
        f"5-Day Win Rate: {format_percent(summary.five_day_win_rate_pct)}"
    )


def build_study_chart(summary: StudySummary, style: DataViewStyle) -> QChartView:
    chart = QChart()
    chart.legend().hide()
    chart.setBackgroundVisible(False)
    chart.setTitle(f"{style.chart_prefix}Score Bucket Coverage")
    chart.setTitleBrush(QBrush(QColor("#e7edf4")))

    score_set = QBarSet("Candidates")
    score_set.setColor(chart_bar_color(DataViewState.STUDY))
    for bucket in summary.score_buckets:
        score_set.append(bucket.count)

    series = QBarSeries()
    series.append(score_set)
    chart.addSeries(series)

    category_axis = QBarCategoryAxis()
    category_axis.append([bucket.label for bucket in summary.score_buckets])
    category_axis.setLabelsColor(QColor("#cbd8e6"))

    max_count = max([bucket.count for bucket in summary.score_buckets] or [1])
    value_axis = QValueAxis()
    value_axis.setRange(0, max(1, max_count))
    value_axis.setTickCount(min(6, max(2, max_count + 1)))
    value_axis.setLabelsColor(QColor("#cbd8e6"))

    chart.addAxis(category_axis, Qt.AlignmentFlag.AlignBottom)
    chart.addAxis(value_axis, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(category_axis)
    series.attachAxis(value_axis)
    chart.setPlotAreaBackgroundVisible(True)
    chart.setPlotAreaBackgroundBrush(QBrush(QColor("#0f1720")))

    watermark = QGraphicsSimpleTextItem(chart)
    watermark.setText("SIMULATED")
    watermark.setBrush(QBrush(chart_badge_color(DataViewState.STUDY)))
    watermark.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
    watermark.setOpacity(0.28)

    def position_watermark() -> None:
        area = chart.plotArea()
        watermark.setPos(area.left() + 14 if not area.isNull() else 24, area.top() + 10 if not area.isNull() else 44)

    chart.plotAreaChanged.connect(position_watermark)
    position_watermark()

    view = QChartView(chart)
    view.setMinimumHeight(280)
    return view


def build_outcome_chart(summary: StudySummary, style: DataViewStyle) -> QChartView:
    chart = QChart()
    chart.legend().hide()
    chart.setBackgroundVisible(False)
    chart.setTitleBrush(QBrush(QColor("#e7edf4")))
    chart.setPlotAreaBackgroundVisible(True)
    chart.setPlotAreaBackgroundBrush(QBrush(QColor("#0f1720")))

    completed = [bucket for bucket in summary.score_buckets if bucket.avg_five_day_return_pct is not None]
    if not completed:
        chart.setTitle(f"{style.chart_prefix}5-Day Outcomes Pending")
        add_chart_watermark(chart, "PENDING OUTCOMES", QColor("#fff0bd"), opacity=0.32)
        view = QChartView(chart)
        view.setMinimumHeight(280)
        return view

    chart.setTitle(f"{style.chart_prefix}5-Day Avg Return by Score Bucket")

    return_set = QBarSet("5-Day Avg")
    return_set.setColor(QColor("#5f86d9"))
    values = []
    for bucket in summary.score_buckets:
        value = bucket.avg_five_day_return_pct if bucket.avg_five_day_return_pct is not None else 0.0
        values.append(value)
        return_set.append(value)

    series = QBarSeries()
    series.append(return_set)
    chart.addSeries(series)

    category_axis = QBarCategoryAxis()
    category_axis.append([bucket.label for bucket in summary.score_buckets])
    category_axis.setLabelsColor(QColor("#cbd8e6"))

    lowest = min(values)
    highest = max(values)
    padding = max(1.0, (highest - lowest) * 0.2)
    value_axis = QValueAxis()
    value_axis.setRange(min(0.0, lowest - padding), max(1.0, highest + padding))
    value_axis.setTickCount(6)
    value_axis.setLabelsColor(QColor("#cbd8e6"))
    value_axis.setLabelFormat("%.2f%%")

    chart.addAxis(category_axis, Qt.AlignmentFlag.AlignBottom)
    chart.addAxis(value_axis, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(category_axis)
    series.attachAxis(value_axis)
    add_chart_watermark(chart, "SIMULATED", chart_badge_color(DataViewState.STUDY))

    view = QChartView(chart)
    view.setMinimumHeight(280)
    return view


def build_recommendation_panel(report: RecommendationReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}Score-Weight Recommendations | "
        f"Completed Rows: {report.completed_rows} | Minimum Rows: {report.minimum_rows} | {report.status}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    table = QTableWidget(0, 7)
    table.setHorizontalHeaderLabels(
        ["Regime", "Bucket", "Rows", "5-Day Avg", "Win Rate", "Recommendation", "Rationale"]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setRowCount(max(1, len(report.recommendations)))

    if not report.recommendations:
        values = ["all", "all", str(report.completed_rows), "n/a", "n/a", "Wait", report.status]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, item in enumerate(report.recommendations):
            values = [
                item.regime,
                item.bucket,
                str(item.sample_size),
                format_percent(item.avg_five_day_return_pct),
                format_percent(item.win_rate_pct),
                item.recommendation,
                item.rationale,
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))

    layout.addWidget(table, 1)
    return panel


def add_chart_watermark(chart: QChart, text: str, color: QColor, opacity: float = 0.28) -> QGraphicsSimpleTextItem:
    watermark = QGraphicsSimpleTextItem(chart)
    watermark.setText(text)
    watermark.setBrush(QBrush(color))
    watermark.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
    watermark.setOpacity(opacity)

    def position_watermark() -> None:
        area = chart.plotArea()
        watermark.setPos(area.left() + 14 if not area.isNull() else 24, area.top() + 10 if not area.isNull() else 44)

    chart.plotAreaChanged.connect(position_watermark)
    position_watermark()
    return watermark


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
QLabel#brandLogo {
    background: #0f1720;
    border: 1px solid #334457;
    border-radius: 6px;
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
#chartStateLabel {
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
