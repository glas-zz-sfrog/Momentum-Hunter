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
    QCheckBox,
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
from momentum_hunter.historical_clusters import (
    CLUSTER_RESEARCH_LABEL,
    HistoricalClusterReport,
    build_historical_cluster_report,
)
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
from momentum_hunter.replay import TimelineRow, build_candidate_timeline, build_replay_view_model
from momentum_hunter.review import (
    CandidateIdentity,
    ReviewDecision,
    ReviewStatus,
    load_review_decisions,
    make_capture_id,
    upsert_review_decision,
)
from momentum_hunter.scoring import score_candidates
from momentum_hunter.score_breakdowns import (
    find_score_breakdown,
    score_breakdown_identity,
    upsert_score_breakdowns_for_candidates,
    upsert_score_breakdowns_for_capture_payload,
)
from momentum_hunter.scheduling import CaptureDecision, evaluate_automatic_capture
from momentum_hunter.startup import install_startup_script, is_startup_installed
from momentum_hunter.storage import (
    RawCaptureAlreadyExistsError,
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
    REVIEW_ALL,
    SCANNER_ALL,
    SECTOR_ALL,
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
        self.review_decisions: dict[str, ReviewDecision] = load_review_decisions()
        self.live_candidates: list[Candidate] = []
        self.live_saved_candidates: dict[str, Candidate] = {}
        self.live_reviewed_tickers: set[str] = set()
        self.selected_ticker: str | None = None
        self.last_snapshot_key: str = ""
        self.data_view_state = DataViewState.CURRENT
        self.current_capture_time: datetime | None = None
        self.display_capture_time: datetime | None = None
        self.display_session_label = ""
        self.display_provider_label = self.config.provider
        self.display_scanner_label = next(iter(SCANNER_PRESETS))
        self.display_mode_label = self.config.mode.value
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

        self.save_button = QPushButton("Mark Interested")
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

        review_bar = QWidget()
        review_layout = QHBoxLayout(review_bar)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(6)
        self.mark_interested_button = QPushButton("Mark Interested")
        self.mark_interested_button.clicked.connect(self.mark_interested_candidates)
        self.mark_rejected_button = QPushButton("Mark Rejected")
        self.mark_rejected_button.clicked.connect(self.mark_rejected_candidates)
        self.add_interested_button = QPushButton("Add Interested to Watchlist")
        self.add_interested_button.clicked.connect(self.add_interested_to_watchlist)
        self.timeline_button = QPushButton("View Timeline")
        self.timeline_button.clicked.connect(self.view_candidate_timeline)
        review_layout.addWidget(self.mark_interested_button)
        review_layout.addWidget(self.mark_rejected_button)
        review_layout.addWidget(self.add_interested_button)
        review_layout.addWidget(self.timeline_button)
        review_layout.addStretch(1)
        layout.addWidget(review_bar)

        self.table = WatermarkTableWidget(0, 12, APP_LOGO_PATH)
        self.table.setHorizontalHeaderLabels(
            [
                "Mark",
                "Status",
                "Score",
                "News Stack",
                "Ticker",
                "Price",
                "% Chg",
                "Volume",
                "Rel Vol",
                "Market Cap",
                "Sector",
                "Industry",
            ]
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
        self.why_score_button = QPushButton("Why?")
        self.why_score_button.clicked.connect(self.show_score_breakdown)
        self.why_score_button.setEnabled(False)
        self.review_status_label = QLabel("Status: unreviewed")
        self.review_status_label.setObjectName("reviewStatusLabel")
        self.news_stack_label = QLabel("")
        self.news_stack_label.setWordWrap(True)
        self.reasons_label = QLabel("")
        self.reasons_label.setWordWrap(True)
        identity_layout.addWidget(self.detail_state_label, 0, 0, 1, 3)
        identity_layout.addWidget(self.ticker_label, 1, 0)
        identity_layout.addWidget(self.score_label, 1, 1)
        identity_layout.addWidget(self.why_score_button, 1, 2)
        identity_layout.addWidget(self.company_label, 2, 0, 1, 3)
        identity_layout.addWidget(self.review_status_label, 3, 0, 1, 3)
        identity_layout.addWidget(self.news_stack_label, 4, 0, 1, 3)
        identity_layout.addWidget(self.reasons_label, 5, 0, 1, 3)
        layout.addWidget(identity)

        health_box = QGroupBox("Capture Health")
        health_layout = QVBoxLayout(health_box)
        self.provider_status_label = QLabel(self.provider_status_text)
        self.provider_status_label.setWordWrap(True)
        self.last_morning_capture_label = QLabel("Last morning capture: checking...")
        self.last_morning_capture_label.setWordWrap(True)
        self.last_evening_capture_label = QLabel("Last evening capture: checking...")
        self.last_evening_capture_label.setWordWrap(True)
        self.last_preopen_capture_label = QLabel("Last preopen capture: checking...")
        self.last_preopen_capture_label.setWordWrap(True)
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
        health_layout.addWidget(self.last_preopen_capture_label)
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
            self.display_provider_label = self.provider_combo.currentText()
            self.display_scanner_label = self.scanner_combo.currentText()
            self.display_mode_label = self.config.mode.value
            self.data_view_state = DataViewState.CURRENT
            self.live_candidates = list(self.candidates)
            self.live_saved_candidates = dict(self.saved_candidates)
            self.live_reviewed_tickers = set(self.reviewed_tickers)
            self.provider_status_text = f"Provider: {self.provider_combo.currentText()} OK at {format_central(scan_time)}"
            self.provider_status_ok = True
            self.retry_scan_button.hide()
            self._persist_score_breakdowns_for_candidates("live", scan_time)
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
            review_status = self._candidate_review_status(candidate)
            values = [
                "",
                review_status.value.title(),
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
                    item.setCheckState(Qt.CheckState.Unchecked)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                elif column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(review_status_color(review_status))
                elif column == 2:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(score_color(candidate.score))
                elif column == 3:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(freshness_color(candidate.news_stack.freshness))
                if candidate.ticker in self.reviewed_tickers and column not in (1, 2, 3):
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
        self.why_score_button.setText(f"Why {candidate.score}?")
        self.why_score_button.setEnabled(True)
        decision = self._candidate_review_decision(candidate)
        status = self._candidate_review_status(candidate)
        timestamp = format_central(decision.decision_timestamp) if decision and decision.decision_timestamp else "not decided"
        self.review_status_label.setText(f"Status: {status.value.title()} | Decision: {timestamp}")
        self.news_stack_label.setText(" | ".join(news_stack_summary(candidate)))
        self.reasons_label.setText(", ".join(candidate.score_reasons) or "No score reasons yet.")
        self.notes_edit.blockSignals(True)
        self.notes_edit.setPlainText(decision.decision_note if decision and decision.decision_note else candidate.user_notes)
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
        self.why_score_button.setText("Why?")
        self.why_score_button.setEnabled(False)
        self.review_status_label.setText("Status: unreviewed")
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
        self.mark_interested_candidates()

    def mark_interested_candidates(self) -> None:
        self._mark_review_status_for_targets(ReviewStatus.INTERESTED, "Marked {count} candidate(s) interested.")

    def mark_rejected_candidates(self) -> None:
        self._mark_review_status_for_targets(ReviewStatus.REJECTED, "Marked {count} candidate(s) rejected.")

    def add_interested_to_watchlist(self) -> None:
        if self._is_read_only_view():
            self._update_status("This view is read-only. Return to current data before changing review status.")
            return
        interested = [
            candidate
            for candidate in self.candidates
            if self._candidate_review_status(candidate) == ReviewStatus.INTERESTED
        ]
        if not interested:
            self._update_status("No interested candidates are ready to add to the watchlist.")
            return
        for candidate in interested:
            self._set_candidate_review_status(candidate, ReviewStatus.WATCHLIST)
        self._refresh_row_states()
        self._update_status(f"Added {len(interested)} interested candidate(s) to watchlist status.")

    def _mark_review_status_for_targets(self, status: ReviewStatus, message_template: str) -> None:
        if self._is_read_only_view():
            self._update_status("This view is read-only. Return to current data before changing review status.")
            return
        marked = self._marked_candidates()
        if not marked:
            candidate = self._selected_candidate()
            if candidate is None:
                self._update_status("Check one or more rows or select a candidate first.")
                return
            marked = [candidate]
        for candidate in marked:
            self._set_candidate_review_status(candidate, status)
        self._refresh_row_states()
        self._update_status(message_template.format(count=len(marked)))

    def _set_candidate_review_status(self, candidate: Candidate, status: ReviewStatus) -> None:
        if candidate.ticker == self.selected_ticker:
            candidate.user_notes = self.notes_edit.toPlainText()
        identity = self._candidate_identity(candidate)
        decision = upsert_review_decision(
            self.review_decisions,
            identity,
            status,
            note=candidate.user_notes,
        )
        self.review_decisions[identity.key] = decision
        self.reviewed_tickers.add(candidate.ticker)
        if status == ReviewStatus.WATCHLIST:
            candidate.saved_at = decision.decision_timestamp
            self.saved_candidates[candidate.ticker] = candidate
        else:
            self.saved_candidates.pop(candidate.ticker, None)
        if self.data_view_state == DataViewState.CURRENT:
            self.live_reviewed_tickers.add(candidate.ticker)
            if status == ReviewStatus.WATCHLIST:
                self.live_saved_candidates[candidate.ticker] = candidate
            else:
                self.live_saved_candidates.pop(candidate.ticker, None)
        if candidate.ticker == self.selected_ticker:
            timestamp = format_central(decision.decision_timestamp) if decision.decision_timestamp else "not decided"
            self.review_status_label.setText(f"Status: {status.value.title()} | Decision: {timestamp}")

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
        watchlist_candidates = self._watchlist_candidates()
        if not watchlist_candidates:
            self._update_status("No watchlist candidates yet. Mark candidates interested, then add interested to watchlist.")
            return
        session_date = next_market_session()
        path = save_watchlist(watchlist_candidates, session_date)
        report = save_watchlist_report(watchlist_candidates, session_date)
        self.capture_daily_snapshot(session=CaptureSession.MANUAL, show_message=False)
        self._load_capture_history()
        QMessageBox.information(
            self,
            "Watchlist Report Generated",
            f"Saved {len(watchlist_candidates)} candidates.\n\nData:\n{path}\n\nReport:\n{report}",
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

    def view_candidate_timeline(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            self._update_status("Select a candidate before opening its timeline.")
            return
        self._show_timeline_dialog(candidate.ticker)

    def _show_timeline_dialog(self, ticker: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Candidate Timeline - {ticker}")
        dialog.resize(1280, 720)
        layout = QVBoxLayout(dialog)

        banner = QLabel(
            "Candidate Timeline - active trusted captures by default. Outcomes and review notes are later-derived annotations."
        )
        banner.setObjectName("detailStateLabel")
        banner.setWordWrap(True)
        layout.addWidget(banner)

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        sort_combo = QComboBox()
        sort_combo.addItems(["Oldest First", "Newest First"])
        show_quarantined = QCheckBox("Show quarantined captures")
        show_non_trading_day = QCheckBox("Show non-trading-day captures")
        replay_button = QPushButton("Replay Capture")
        controls_layout.addWidget(QLabel("Sort"))
        controls_layout.addWidget(sort_combo)
        controls_layout.addWidget(show_quarantined)
        controls_layout.addWidget(show_non_trading_day)
        controls_layout.addStretch(1)
        controls_layout.addWidget(replay_button)
        layout.addWidget(controls)

        table = QTableWidget(0, 26)
        headers = [
            "Capture",
            "Session",
            "Calendar",
            "Provider",
            "Scanner",
            "Ticker",
            "Price",
            "% Chg",
            "Volume",
            "Rel Vol",
            "Market Cap",
            "Sector",
            "Industry",
            "Score",
            "Profile",
            "Score Ver",
            "Score Regime",
            "Market Regime",
            "Breakdown",
            "Review",
            "Note",
            "Outcome",
            "Next Day",
            "5 Day",
            "Max Gain",
            "Trust",
        ]
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(table, 1)

        timeline_rows: list[TimelineRow] = []

        def refresh() -> None:
            nonlocal timeline_rows
            timeline_rows = build_candidate_timeline(
                ticker,
                include_quarantined=show_quarantined.isChecked(),
                include_non_trading_day=show_non_trading_day.isChecked(),
                newest_first=sort_combo.currentText() == "Newest First",
            )
            populate_timeline_table(table, timeline_rows)
            replay_button.setEnabled(bool(timeline_rows))

        def replay_selected() -> None:
            if not timeline_rows:
                return
            row_index = table.currentRow()
            if row_index < 0:
                row_index = 0
            self._show_replay_dialog(timeline_rows[row_index])

        sort_combo.currentTextChanged.connect(refresh)
        show_quarantined.stateChanged.connect(refresh)
        show_non_trading_day.stateChanged.connect(refresh)
        replay_button.clicked.connect(replay_selected)
        table.itemDoubleClicked.connect(lambda _item: replay_selected())
        refresh()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.setStyleSheet(STYLESHEET)
        dialog.exec()

    def _show_replay_dialog(self, timeline_row: TimelineRow) -> None:
        view_model = build_replay_view_model(timeline_row)
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Historical Replay - {timeline_row.ticker} - {timeline_row.capture_time_text}")
        dialog.resize(980, 760)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(format_replay_html(view_model))
        layout.addWidget(browser, 1)

        button_row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        why_button = QPushButton(f"Why {timeline_row.fields['score'].value}?")
        why_button.setEnabled(timeline_row.score_breakdown is not None)
        button_row.addButton(why_button, QDialogButtonBox.ButtonRole.ActionRole)

        def show_why() -> None:
            if timeline_row.score_breakdown:
                self._show_score_breakdown_dialog(timeline_row.score_breakdown)
            else:
                QMessageBox.information(self, "Score Breakdown Missing", "No stored score breakdown exists for this replay row.")

        why_button.clicked.connect(show_why)
        button_row.rejected.connect(dialog.reject)
        button_row.accepted.connect(dialog.accept)
        layout.addWidget(button_row)
        dialog.setStyleSheet(STYLESHEET)
        dialog.exec()

    def capture_daily_snapshot(
        self,
        session: CaptureSession | None = None,
        show_message: bool = True,
        capture_time: datetime | None = None,
    ) -> None:
        candidates = self.candidates or list(self.saved_candidates.values())
        if not candidates:
            self._update_status("No scanned candidates available to capture.")
            return
        selected = {candidate.ticker for candidate in self._watchlist_candidates()} | set(self.saved_candidates)
        for candidate in candidates:
            if candidate.ticker in selected:
                self.saved_candidates[candidate.ticker] = candidate
        session = session or self._current_capture_session()
        if self.market_regime.regime == MarketRegime.UNKNOWN:
            self.refresh_market_regime(show_status=False)
        try:
            json_path, report_path = save_daily_capture(
                candidates=candidates,
                selected_tickers=selected,
                reviewed_tickers=self.reviewed_tickers,
                criteria=SCANNER_PRESETS[self.scanner_combo.currentText()],
                provider=self.provider_combo.currentText(),
                mode=self.config.mode,
                session=session,
                market_regime=self.market_regime,
                capture_time=capture_time,
            )
            try:
                upsert_score_breakdowns_for_capture_payload(load_capture_json(session_date_from_path(json_path), session))
            except Exception as exc:
                self._update_status(f"Saved capture, but score breakdown persistence failed: {exc}")
        except RawCaptureAlreadyExistsError as exc:
            self._update_status(str(exc))
            if show_message:
                QMessageBox.warning(self, "Capture Already Exists", str(exc))
            return
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
        for requested_session in (CaptureSession.MORNING, CaptureSession.EVENING):
            decision = evaluate_automatic_capture(requested_session, current_time=current)
            if decision.should_capture:
                self._auto_capture_once(decision)
                return

    def _auto_capture_once(self, decision: CaptureDecision) -> None:
        session = decision.capture_session
        key = decision.run_at.strftime("%Y-%m-%d") + f"-{session.value}"
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
                    self._persist_score_breakdowns_for_candidates("live", self.current_capture_time)
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
            self.capture_daily_snapshot(session=session, show_message=False, capture_time=decision.run_at)
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
        self.last_preopen_capture_label.setText(format_capture_success("Last successful preopen", health.last_preopen_capture))
        if health.last_morning_capture.capture_time:
            self.last_morning_capture_label.setStyleSheet("color: #cbd8e6;")
        else:
            self.last_morning_capture_label.setStyleSheet("color: #fcd34d; font-weight: 700;")
        if health.last_evening_capture.capture_time:
            self.last_evening_capture_label.setStyleSheet("color: #cbd8e6;")
        else:
            self.last_evening_capture_label.setStyleSheet("color: #fcd34d; font-weight: 700;")
        if health.last_preopen_capture.capture_time:
            self.last_preopen_capture_label.setStyleSheet("color: #cbd8e6;")
        else:
            self.last_preopen_capture_label.setStyleSheet("color: #9fb0c2;")

        self.capture_failure_label.setText(format_capture_failure(health.last_failed_capture))
        if health.last_failed_capture.failure_time:
            self.capture_failure_label.setStyleSheet("color: #fcd34d; font-weight: 700;")
        else:
            self.capture_failure_label.setStyleSheet("color: #cbd8e6;")
        self.next_capture_label.setText(
            "Next scheduled runs: "
            f"Morning {format_central(health.next_morning_run)} | "
            f"Evening {format_central(health.next_evening_run)} | "
            f"Preopen {format_central(health.next_preopen_run)}"
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
        self.display_provider_label = payload.get("provider", "")
        self.display_mode_label = payload.get("mode", "")
        scanner_payload = payload.get("scanner", {})
        self.display_scanner_label = scanner_payload.get("name", "") if isinstance(scanner_payload, dict) else str(scanner_payload)
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
        self.display_provider_label = self.provider_combo.currentText()
        self.display_scanner_label = self.scanner_combo.currentText()
        self.display_mode_label = self.config.mode.value
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
        self.mark_interested_button.setEnabled(not read_only)
        self.mark_rejected_button.setEnabled(not read_only)
        self.add_interested_button.setEnabled(not read_only)
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
            decision = evaluate_automatic_capture(CaptureSession.MORNING, current_time=current)
            return decision.capture_session if decision.should_capture else CaptureSession.MANUAL
        if 12 <= current.hour <= 23:
            decision = evaluate_automatic_capture(CaptureSession.EVENING, current_time=current)
            return decision.capture_session if decision.should_capture else CaptureSession.MANUAL
        return CaptureSession.MANUAL

    def _ensure_windows_startup(self) -> None:
        if is_startup_installed():
            return
        try:
            install_startup_script(Path(__file__).resolve().parents[1])
        except Exception as exc:
            self._update_status(f"Could not install Windows startup launcher: {exc}")

    def _persist_score_breakdowns_for_candidates(self, session_label: str, capture_time: datetime) -> None:
        if not self.candidates:
            return
        try:
            upsert_score_breakdowns_for_candidates(
                self.candidates,
                capture_time=capture_time,
                session=session_label,
                provider=self.display_provider_label or self.provider_combo.currentText(),
                scanner=self.display_scanner_label or self.scanner_combo.currentText(),
                mode=self.display_mode_label or self.config.mode.value,
                regime=self.market_regime.regime,
            )
        except Exception as exc:
            self._update_status(f"Score breakdown persistence failed: {exc}")

    def show_score_breakdown(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            self._update_status("Select a candidate before opening score details.")
            return
        identity = self._score_breakdown_identity(candidate)
        record = find_score_breakdown(identity)
        if record is None and self.data_view_state == DataViewState.CURRENT:
            capture_time = self.display_capture_time or self.current_capture_time or now_central()
            generated = upsert_score_breakdowns_for_candidates(
                [candidate],
                capture_time=capture_time,
                session=self.display_session_label or "live",
                provider=self.display_provider_label or self.provider_combo.currentText(),
                scanner=self.display_scanner_label or self.scanner_combo.currentText(),
                mode=self.display_mode_label or self.config.mode.value,
                regime=self.market_regime.regime,
            )
            record = generated[0] if generated else None
        if record is None:
            QMessageBox.information(
                self,
                "Score Breakdown Missing",
                "No stored score breakdown was found for this historical candidate. Run rebuild_score_breakdowns before relying on this view.",
            )
            return
        self._show_score_breakdown_dialog(record)

    def _show_score_breakdown_dialog(self, record: dict) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Why {record.get('final_score', '')}? - {record.get('ticker', '')}")
        dialog.resize(920, 720)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(format_score_breakdown_html(record))
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def _score_breakdown_identity(self, candidate: Candidate) -> dict:
        capture_time = self.display_capture_time or self.current_capture_time or now_central()
        return score_breakdown_identity(
            capture_date=capture_time.strftime("%Y-%m-%d"),
            capture_time=capture_time.isoformat(),
            session=self.display_session_label or "live",
            provider=self.display_provider_label or self.provider_combo.currentText(),
            scanner=self.display_scanner_label or self.scanner_combo.currentText(),
            ticker=candidate.ticker,
            mode=self.display_mode_label or self.config.mode.value,
        )

    def _selected_candidate(self) -> Candidate | None:
        if self.selected_ticker is None:
            return None
        return next((candidate for candidate in self.candidates if candidate.ticker == self.selected_ticker), None)

    def _candidate_identity(self, candidate: Candidate) -> CandidateIdentity:
        capture_time = self.display_capture_time or self.current_capture_time or now_central()
        capture_date = capture_time.strftime("%Y-%m-%d")
        session = self.display_session_label or "live"
        provider = self.display_provider_label or self.provider_combo.currentText()
        scanner = self.display_scanner_label or self.scanner_combo.currentText()
        capture_id = make_capture_id(capture_date, session, provider, scanner)
        return CandidateIdentity(
            capture_id=capture_id,
            capture_date=capture_date,
            session=session,
            provider=provider,
            scanner=scanner,
            ticker=candidate.ticker,
        )

    def _candidate_review_decision(self, candidate: Candidate) -> ReviewDecision | None:
        identity = self._candidate_identity(candidate)
        return self.review_decisions.get(identity.key)

    def _candidate_review_status(self, candidate: Candidate) -> ReviewStatus:
        decision = self._candidate_review_decision(candidate)
        if decision is not None:
            return decision.review_status
        if candidate.ticker in self.saved_candidates:
            return ReviewStatus.WATCHLIST
        return ReviewStatus.UNREVIEWED

    def _watchlist_candidates(self) -> list[Candidate]:
        return [candidate for candidate in self.candidates if self._candidate_review_status(candidate) == ReviewStatus.WATCHLIST]

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
                item.setCheckState(Qt.CheckState.Unchecked)
            status_item = self.table.item(row, 1)
            if status_item is not None:
                status = self._candidate_review_status(candidate)
                status_item.setText(status.value.title())
                status_item.setBackground(review_status_color(status))
            if candidate.ticker in self.reviewed_tickers:
                for column in range(self.table.columnCount()):
                    cell = self.table.item(row, column)
                    if cell is not None and column not in (1, 2, 3):
                        cell.setBackground(
                            QBrush(QColor("#20394a" if self.data_view_state == DataViewState.CURRENT else "#3a314d"))
                        )

    def _update_status(self, message: str) -> None:
        self.clock_label.setText(format_central())
        self.status_label.setText(message)

    def _set_table_widths(self) -> None:
        widths = [48, 112, 62, 190, 72, 88, 78, 116, 86, 104, 128, 180]
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
        dialog.resize(1320, 820)
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
        session_combo.addItems([SESSION_ALL, "morning", "evening", "preopen", "manual"])
        filter_layout.addWidget(session_combo)
        include_non_study_checkbox = QCheckBox("Include non-trading-day/preopen")
        filter_layout.addWidget(include_non_study_checkbox)
        filter_layout.addWidget(QLabel("Regime"))
        regime_combo = QComboBox()
        regime_combo.addItems([REGIME_ALL, "bull", "bear", "neutral", "unknown"])
        filter_layout.addWidget(regime_combo)
        filter_layout.addStretch(1)
        layout.addWidget(filter_row)

        cluster_filter_row = QWidget()
        cluster_filter_layout = QHBoxLayout(cluster_filter_row)
        cluster_filter_layout.setContentsMargins(0, 0, 0, 0)
        cluster_filter_layout.addWidget(QLabel("Scanner"))
        scanner_edit = QLineEdit()
        scanner_edit.setPlaceholderText("all scanners")
        cluster_filter_layout.addWidget(scanner_edit)
        cluster_filter_layout.addWidget(QLabel("Sector"))
        sector_edit = QLineEdit()
        sector_edit.setPlaceholderText("all sectors")
        cluster_filter_layout.addWidget(sector_edit)
        cluster_filter_layout.addWidget(QLabel("Min Score"))
        minimum_score_edit = QLineEdit()
        minimum_score_edit.setPlaceholderText("0")
        minimum_score_edit.setMaximumWidth(70)
        cluster_filter_layout.addWidget(minimum_score_edit)
        cluster_filter_layout.addWidget(QLabel("Review"))
        review_combo = QComboBox()
        review_combo.addItems([REVIEW_ALL, "unreviewed", "interested", "rejected", "watchlist"])
        cluster_filter_layout.addWidget(review_combo)
        cluster_filter_layout.addStretch(1)
        layout.addWidget(cluster_filter_row)

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
            minimum_score = 0
            try:
                minimum_score = int(float(minimum_score_edit.text().strip() or "0"))
            except ValueError:
                minimum_score = 0
            return StudyFilter(
                row_filter=filter_combo.currentText(),
                start_date=start_date_edit.text().strip(),
                end_date=end_date_edit.text().strip(),
                session=session_combo.currentText(),
                regime=regime_combo.currentText(),
                include_non_study_eligible=include_non_study_checkbox.isChecked(),
                scanner=scanner_edit.text().strip() or SCANNER_ALL,
                sector=sector_edit.text().strip() or SECTOR_ALL,
                minimum_score=minimum_score,
                review_status=review_combo.currentText(),
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
            chart_tabs.addTab(
                build_historical_cluster_panel(
                    build_historical_cluster_report(study_filter=current_study_filter()),
                    filtered_style,
                ),
                "Historical Clusters",
            )
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
        include_non_study_checkbox.stateChanged.connect(refresh_study_view)
        regime_combo.currentTextChanged.connect(refresh_study_view)
        scanner_edit.editingFinished.connect(refresh_study_view)
        sector_edit.editingFinished.connect(refresh_study_view)
        minimum_score_edit.editingFinished.connect(refresh_study_view)
        review_combo.currentTextChanged.connect(refresh_study_view)
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


def format_score_breakdown_html(record: dict) -> str:
    status = record.get("status", "complete")
    warning = ""
    if status != "complete":
        warning = (
            "<p style='color:#fcd34d;font-weight:700;'>"
            f"{escape(str(status).upper())}: this explanation is marked {escape(str(status))}. "
            "Use it as historical context, not a clean current-engine reconciliation."
            "</p>"
        )
    identity = record.get("identity", {})
    compact_rows = []
    compact_summary = record.get("compact_summary") or compact_score_summary_from_components(record.get("components", []))
    for item in compact_summary:
        contribution = int(item.get("contribution", 0))
        compact_rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('label', '')))}</td>"
            f"<td style='text-align:right;font-weight:700;color:{'#a7f3d0' if contribution >= 0 else '#fecaca'};'>"
            f"{format_signed_points(contribution)}</td>"
            f"<td>{escape(format_raw_inputs(item.get('raw_inputs', {})))}</td>"
            "</tr>"
        )
    component_rows = []
    for component in record.get("components", []):
        contribution = int(component.get("points_after_adjustment", 0))
        component_rows.append(
            "<tr>"
            f"<td>{escape(str(component.get('label', '')))}</td>"
            f"<td>{escape(str(component.get('category', '')))}</td>"
            f"<td>{escape(str(component.get('rule', '')))}</td>"
            f"<td>{escape(format_raw_inputs(component.get('raw_inputs', {})))}</td>"
            f"<td style='text-align:right;'>{escape(str(component.get('points_before_adjustment', '')))}</td>"
            f"<td style='text-align:right;font-weight:700;color:{'#a7f3d0' if contribution >= 0 else '#fecaca'};'>"
            f"{escape(format_signed_points(contribution))}</td>"
            f"<td>{escape(str(component.get('explanation', '')))}</td>"
            "</tr>"
        )
    reconciliation = record.get("reconciliation", {})
    caps = record.get("caps", [])
    floors = record.get("floors", [])
    cap = caps[0] if caps else {}
    floor = floors[0] if floors else {}
    return f"""
    <html>
    <body style="font-family: Segoe UI, Arial; color: #e7edf4; background: #0b1118;">
      <h2>Why {escape(str(record.get('final_score', '')))}? {escape(str(record.get('ticker', '')))}</h2>
      {warning}
      <p>
        <b>Captured:</b> {escape(str(identity.get('capture_time', record.get('capture_time', ''))))}<br>
        <b>Session:</b> {escape(str(identity.get('session', '')))} |
        <b>Provider:</b> {escape(str(identity.get('provider', '')))} |
        <b>Scanner:</b> {escape(str(identity.get('scanner', '')))} |
        <b>Mode:</b> {escape(str(identity.get('mode', '')))} |
        <b>Profile:</b> {escape(str(record.get('score_profile', '')))} |
        <b>Regime:</b> {escape(str(record.get('score_regime', '')))}<br>
        <b>Scoring Version:</b> {escape(str(record.get('score_engine_version', '')))} |
        <b>Schema:</b> {escape(str(record.get('explanation_schema_version', '')))}
      </p>
      <h3>Reconciliation</h3>
      <pre style="background:#111b26;padding:10px;border:1px solid #2f4054;">
Base component subtotal: {escape(str(record.get('subtotal_before_global_adjustments', '')))}
Floor applied: {escape(str(floor.get('applied', False)))} | Floor output: {escape(str(floor.get('output', '')))}
Pre-cap total: {escape(str(record.get('pre_cap_total', '')))}
Global cap applied: {escape(str(cap.get('applied', False)))} | Cap output: {escape(str(cap.get('output', '')))}
Computed final score: {escape(str(record.get('computed_final_score', '')))}
Displayed final score: {escape(str(record.get('final_score', '')))}
Reconciliation status: {escape(str(reconciliation.get('status', record.get('reconciliation_status', ''))))}
      </pre>
      <h3>Compact Summary</h3>
      <table cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;">
        <tr style="background:#182536;">
          <th align="left">Component</th>
          <th align="right">Contribution</th>
          <th align="left">Raw Value</th>
        </tr>
        {''.join(compact_rows)}
      </table>
      <h3>Detailed Components</h3>
      <table cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;">
        <tr style="background:#182536;">
          <th align="left">Component</th>
          <th align="left">Type</th>
          <th align="left">Rule</th>
          <th align="left">Raw Inputs</th>
          <th align="right">Before</th>
          <th align="right">Contribution</th>
          <th align="left">Explanation</th>
        </tr>
        {''.join(component_rows)}
      </table>
    </body>
    </html>
    """


def compact_score_summary_from_components(components: list[dict]) -> list[dict]:
    groups = [
        ("base_score", "Base"),
        ("volume", "Volume"),
        ("relative_volume", "Relative Volume"),
        ("market_cap", "Market Cap"),
        ("price_momentum", "Price Move"),
        ("positive_catalyst.", "Catalyst"),
        ("freshness_context", "Freshness"),
        ("risk_term.", "Risk Penalty"),
        ("low_price", "Price Risk"),
    ]
    summary: list[dict] = []
    for key_prefix, label in groups:
        matching = [
            component
            for component in components
            if str(component.get("key", "")) == key_prefix or str(component.get("key", "")).startswith(key_prefix)
        ]
        if matching:
            summary.append(
                {
                    "label": label,
                    "contribution": sum(int(component.get("points_after_adjustment", 0)) for component in matching),
                    "raw_inputs": {
                        key: value
                        for component in matching
                        for key, value in (component.get("raw_inputs", {}) if isinstance(component.get("raw_inputs"), dict) else {}).items()
                    },
                }
            )
    return summary


def format_signed_points(value: int) -> str:
    if value > 0:
        return f"+{value}"
    return str(value)


def format_raw_inputs(raw_inputs: dict) -> str:
    if not isinstance(raw_inputs, dict):
        return str(raw_inputs)
    return "; ".join(f"{key}={value}" for key, value in raw_inputs.items())


def populate_timeline_table(table: QTableWidget, rows: list[TimelineRow]) -> None:
    table.setRowCount(len(rows))
    for row_index, row in enumerate(rows):
        values = [
            row.capture_time_text,
            row.session,
            row.calendar_label,
            row.provider,
            row.scanner,
            row.ticker,
            timeline_value(row, "price"),
            timeline_value(row, "percent_change"),
            timeline_value(row, "volume"),
            timeline_value(row, "relative_volume"),
            timeline_value(row, "market_cap"),
            timeline_value(row, "sector"),
            timeline_value(row, "industry"),
            timeline_value(row, "score"),
            timeline_value(row, "score_profile"),
            timeline_value(row, "score_engine_version"),
            timeline_value(row, "score_regime"),
            timeline_value(row, "market_regime"),
            timeline_value(row, "score_breakdown_status"),
            timeline_value(row, "review_status"),
            timeline_value(row, "note_indicator"),
            timeline_value(row, "outcome_status"),
            timeline_value(row, "next_day_return_pct"),
            timeline_value(row, "five_day_return_pct"),
            timeline_value(row, "max_gain_pct"),
            row.trust_label,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            if row.quarantined:
                item.setBackground(QBrush(QColor("#6d3030")))
            elif row.calendar_classification.capture_calendar_status == "PREOPEN_GAP_REVIEW_DAY":
                item.setBackground(QBrush(QColor("#244d63")))
            elif row.warnings:
                item.setBackground(QBrush(QColor("#735f24")))
            table.setItem(row_index, column, item)
    table.resizeColumnsToContents()
    if rows:
        table.selectRow(0)


def timeline_value(row: TimelineRow, key: str) -> object:
    value = row.fields.get(key)
    return value.value if value else ""


def format_replay_html(view_model) -> str:
    row = view_model.row
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in view_model.warnings)
    warning_block = f"<ul style='color:#fcd34d;font-weight:700;'>{warnings}</ul>" if warnings else "<p>No replay warnings.</p>"
    raw_rows = "".join(
        "<tr>"
        f"<td>{escape(label_for_field(key))}</td>"
        f"<td>{escape(str(value.value))}</td>"
        f"<td>{escape(value.source)}</td>"
        "</tr>"
        for key, value in row.fields.items()
        if value.source == "raw capture"
    )
    review = row.review_decision
    review_text = (
        f"{review.review_status.value.title()} at {format_central(review.decision_timestamp) if review.decision_timestamp else 'unknown time'}"
        if review
        else "No review decision recorded."
    )
    review_note = escape(review.decision_note) if review and review.decision_note else "No note."
    outcome = row.outcome or {}
    score_status = row.score_breakdown.get("status", "unavailable") if row.score_breakdown else "missing"
    return f"""
    <html>
    <body style="font-family: Segoe UI, Arial; color:#e7edf4; background:#0b1118;">
      <h2>{escape(view_model.banner)}</h2>
      <p>
        <b>{escape(row.ticker)}</b> |
        Captured: {escape(row.capture_time_text)} |
        Age now: {escape(row.age_text)} |
        Session: {escape(row.session)} |
        Calendar: {escape(row.calendar_label)} |
        Provider: {escape(row.provider)} |
        Scanner: {escape(row.scanner)}
      </p>
      <p>
        Study eligible: <b>{escape(str(row.calendar_classification.is_study_eligible))}</b> |
        Market-open day: <b>{escape(str(row.calendar_classification.is_market_open_day))}</b> |
        Next market session: <b>{escape(row.calendar_classification.next_market_session_date)}</b>
      </p>
      <p style="color:#9fb0c2;">
        Read-only replay. Raw capture facts are separated from stored score explanations,
        later review decisions, and later outcome labels.
      </p>
      <h3>Point-in-Time Boundaries</h3>
      <ul>
        <li>Raw facts are loaded from the immutable capture file at {escape(row.capture_path)}.</li>
        <li>Score details are loaded from score-breakdowns.json for the stored historical identity.</li>
        <li>Review decisions are later user annotations from review-decisions.json.</li>
        <li>Outcomes are post-capture labels from analysis-outcomes.csv.</li>
      </ul>
      <h3>Warnings</h3>
      {warning_block}
      <h3>Capture-Time Facts</h3>
      <table cellspacing="0" cellpadding="6" style="border-collapse:collapse;width:100%;">
        <tr style="background:#182536;"><th align="left">Field</th><th align="left">Value</th><th align="left">Source</th></tr>
        {raw_rows}
      </table>
      <h3>Stored Score Explanation</h3>
      <p>
        Score breakdown status: <b>{escape(str(score_status))}</b> |
        Version: <b>{escape(str(timeline_value(row, 'score_engine_version')))}</b>.
        This uses the stored score-breakdown record for the historical identity, not a fresh market-data fetch or score recalculation.
      </p>
      <h3>Later Review Decision</h3>
      <p>{escape(review_text)}<br>Note: {review_note}</p>
      <h3>Outcome Calculated After Capture</h3>
      <p style="color:#fcd34d;">Outcome values are labels calculated after the capture. They were not known during the replayed moment.</p>
      <ul>
        <li>Status: {escape(str(outcome.get('outcome_status', 'missing')))}</li>
        <li>Next-day return: {escape(str(outcome.get('next_day_return_pct', '')))}</li>
        <li>Five-day return: {escape(str(outcome.get('five_day_return_pct', '')))}</li>
        <li>Max gain: {escape(str(outcome.get('max_gain_pct', '')))}</li>
        <li>Max drawdown: {escape(str(outcome.get('max_drawdown_pct', '')))}</li>
      </ul>
    </body>
    </html>
    """


def label_for_field(key: str) -> str:
    labels = {
        "price": "Price",
        "percent_change": "% Change",
        "volume": "Volume",
        "relative_volume": "Relative Volume",
        "market_cap": "Market Cap",
        "sector": "Sector",
        "industry": "Industry",
        "score": "Momentum Score",
        "score_profile": "Score Profile",
        "score_engine_version": "Score Engine Version",
        "score_breakdown_status": "Score Breakdown Status",
        "score_regime": "Score Regime",
        "market_regime": "Market Regime",
        "capture_calendar_status": "Calendar Status",
        "is_study_eligible": "Study Eligible",
        "next_market_session_date": "Next Market Session",
    }
    return labels.get(key, key.replace("_", " ").title())


def session_date_from_path(path: Path) -> str:
    return path.parent.name


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


def review_status_color(status: ReviewStatus) -> QColor:
    if status == ReviewStatus.WATCHLIST:
        return QColor("#1f6f4a")
    if status == ReviewStatus.INTERESTED:
        return QColor("#2c4f73")
    if status == ReviewStatus.REJECTED:
        return QColor("#6d3030")
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


def build_historical_cluster_panel(report: HistoricalClusterReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}{CLUSTER_RESEARCH_LABEL} | "
        f"Candidates: {report.total_candidates} | Source: {report.source}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    if report.warnings:
        warning = QLabel(" | ".join(report.warnings))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
        layout.addWidget(warning)

    table = QTableWidget(0, 13)
    table.setHorizontalHeaderLabels(
        [
            "Cluster",
            "Count",
            "Tickers",
            "Date Range",
            "Avg Score",
            "Avg Max Gain",
            "Avg Max Drawdown",
            "Win Rate",
            "Top Winners",
            "Worst Failures",
            "Score Components",
            "Catalyst Keywords",
            "Warnings",
        ]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
    table.setRowCount(max(1, len(report.clusters)))

    if not report.clusters:
        values = ["No clusters", "0", "", "", "n/a", "n/a", "n/a", "n/a", "", "", "", "", "No historical candidates matched the filters."]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, cluster in enumerate(report.clusters):
            values = [
                cluster.name,
                str(cluster.candidate_count),
                ", ".join(cluster.tickers),
                cluster.date_range,
                format_number(cluster.average_score),
                format_percent(cluster.average_max_gain_pct),
                format_percent(cluster.average_max_drawdown_pct),
                format_percent(cluster.win_rate_pct),
                ", ".join(cluster.top_winners) or "n/a",
                ", ".join(cluster.worst_failures) or "n/a",
                ", ".join(cluster.common_score_components) or "n/a",
                ", ".join(cluster.common_catalyst_keywords) or "n/a",
                " | ".join(cluster.warnings) or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if cluster.candidate_count < 10:
                    item.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, item)

    table.resizeColumnsToContents()
    layout.addWidget(table, 1)
    return panel


def format_number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


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
