from __future__ import annotations

import csv
import json
import sys
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from html import escape
from pathlib import Path

from PySide6.QtCore import QMargins, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QChart, QChartView, QLineSeries, QScatterSeries, QValueAxis
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
    QStackedWidget,
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
from momentum_hunter.candidate_story_view_model import (
    CandidateStoryPoint,
    CandidateStorySummary,
    build_candidate_story_summary,
    format_candidate_story_header_html,
    format_compact_volume,
    format_story_marker_detail,
    format_story_percent,
    format_story_price,
    format_story_rel_vol,
    format_story_score,
    format_story_score_delta,
    story_marker_specs,
)
from momentum_hunter.active_monitor import ACTIVE_MONITOR_STATUS_PATH, run_monitor_cycle
from momentum_hunter.alert_outcome_updater import (
    ALERT_OUTCOME_UPDATE_STATUS_PATH,
    update_alert_store_from_minute_bars,
)
from momentum_hunter.active_monitor_runner import (
    start_active_monitor_background,
    stop_active_monitor_background,
)
from momentum_hunter.evidence_console_view_model import (
    active_monitor_summary_text,
    alert_outcome_update_status_text,
    alert_performance_summary_text,
    evidence_autopilot_summary_text,
    evidence_health_summary_text,
    evidence_next_action_text,
    latest_active_monitor_cycle_json_path,
    load_active_alert_rows,
    load_active_monitor_dashboard_rows,
    load_alert_outcome_rows,
    load_alert_performance_dashboard_rows,
    load_evidence_autopilot_dashboard_rows,
    load_evidence_health_dashboard_rows,
    load_user_monitor_symbol_rows,
)
from momentum_hunter.monitor_targets import (
    remove_user_defined_symbol,
    upsert_user_defined_symbol,
)
from momentum_hunter.catalyst_age import (
    AGE_BUCKETS,
    CATALYST_AGE_RESEARCH_LABEL,
    TIMESTAMP_STATUSES,
    CatalystAgeAuditReport,
    build_catalyst_age_audit_report,
)
from momentum_hunter.catalyst_clusters import (
    CATALYST_RESEARCH_LABEL,
    CatalystClusterReport,
    build_catalyst_cluster_report,
    classify_catalyst_headline_detail,
)
from momentum_hunter.config import DATA_DIR, AppConfig, load_config, save_config
from momentum_hunter.daily_workflow import DailyWorkflowReport, build_daily_workflow_report
from momentum_hunter.entry_plans import (
    EntryPlan,
    entry_plan_warnings,
    load_entry_plans,
    upsert_entry_plan,
)
from momentum_hunter.evidence_autopilot import run_evidence_autopilot
from momentum_hunter.historical_clusters import (
    CLUSTER_RESEARCH_LABEL,
    HistoricalClusterReport,
    HistoricalRecurrenceReport,
    build_historical_cluster_report,
    build_historical_recurrence_report,
)
from momentum_hunter.headline_events import (
    HEADLINE_DEDUP_RESEARCH_LABEL,
    HeadlineDedupReport,
    build_headline_dedup_report,
)
from momentum_hunter.market import MarketRegimeSnapshot, detect_market_regime
from momentum_hunter.models import Candidate, CaptureSession, MarketRegime, SCANNER_PRESETS, TradingMode
from momentum_hunter.news_age import (
    apply_candidate_news_stack,
    evaluate_news_freshness,
    filter_news_known_at_capture,
    format_news_age,
    format_news_range,
    news_stack_badge,
    news_stack_summary,
)
from momentum_hunter.outcome_explorer import (
    OUTCOME_EXPLORER_LABEL,
    OutcomeExplorerReport,
    build_outcome_explorer_report,
)
from momentum_hunter.outcome_maturity import (
    OUTCOME_MATURITY_LABEL,
    OutcomeMaturityReport,
    build_outcome_maturity_report,
)
from momentum_hunter.operator_review import (
    OperatorReviewContext,
    OperatorReviewState,
    blocked_context,
    classify_current_manual_scan,
    classify_scheduled_snapshot,
)
from momentum_hunter.opportunity_research import (
    OPPORTUNITY_RESEARCH_LABEL,
    OpportunityResearchReport,
    build_opportunity_research_report,
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
from momentum_hunter.score_explanation_view_model import format_score_breakdown_html
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
    AGE_BUCKET_ALL,
    CATALYST_CLUSTER_ALL,
    REGIME_ALL,
    HISTORICAL_THEME_ALL,
    REVIEW_ALL,
    SCANNER_ALL,
    SECTOR_ALL,
    SESSION_ALL,
    SCORE_BUCKET_ALL,
    StudyFilter,
    StudySummary,
    TIMESTAMP_STATUS_ALL,
    build_capture_study,
)
from momentum_hunter.time_utils import format_central, next_market_session, now_central
from momentum_hunter.ui.autonomy_gateway import build_argus_machine_console_page, build_gateway_page, refresh_argus_machine_console
from momentum_hunter.ui.data_view_state import (
    DataViewState,
    DataViewStyle,
    get_data_view_style,
    load_freshness_settings,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_LOGO_PATH = PROJECT_ROOT / "assets" / "momentum_hunter_logo.jpg"
SCANNER_DISPLAY_NAMES = {
    "Base Momentum": "Basic Momentum",
    "Institutional Momentum": "Heavy Volume Momentum",
}
SCANNER_INTERNAL_NAMES = {value: key for key, value in SCANNER_DISPLAY_NAMES.items()}
SCANNER_DISPLAY_DESCRIPTIONS = {
    "Base Momentum": "Basic Momentum: broader scan with a stronger relative-volume spike requirement.",
    "Institutional Momentum": (
        "Heavy Volume Momentum: emphasizes higher absolute liquidity, larger market cap, "
        "and institutional participation; relative-volume threshold is intentionally lower."
    ),
}
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


class ReportLoaderWorker(QObject):
    finished = Signal(object, float)
    failed = Signal(str, str, float)

    def __init__(self, loader: Callable[[], object]) -> None:
        super().__init__()
        self.loader = loader

    def run(self) -> None:
        started = time.perf_counter()
        try:
            result = self.loader()
        except Exception as exc:
            self.failed.emit(type(exc).__name__, str(exc), time.perf_counter() - started)
        else:
            self.finished.emit(result, time.perf_counter() - started)


class MomentumHunterWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.candidates: list[Candidate] = []
        self.saved_candidates: dict[str, Candidate] = {}
        self.reviewed_tickers: set[str] = set()
        self.review_decisions: dict[str, ReviewDecision] = load_review_decisions()
        self.entry_plans: dict[str, EntryPlan] = load_entry_plans()
        self._loading_entry_plan = False
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
        self.display_calendar_status = ""
        self.display_next_market_session_date = ""
        self.display_quarantined = False
        self.replay_snapshot_candidates: list[Candidate] = []
        self.replay_snapshot_payload: dict | None = None
        self.current_view_style: DataViewStyle | None = None
        self.current_operator_context: OperatorReviewContext | None = None
        self.provider_status_text = "Provider: not checked"
        self.provider_status_ok = True
        self._report_loader_refs: list[tuple[QThread, ReportLoaderWorker, QDialog]] = []
        self._active_report_loader_titles: set[str] = set()
        self._page_history: list[int] = []
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
        self._refresh_execution_ready_panel()
        self._start_snapshot_timer()
        self._apply_data_view_state()
        self._update_status("Ready. Human review required before any trading decision.")

    def _build_ui(self) -> None:
        root = WatermarkWidget(APP_LOGO_PATH)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.app_stack = QStackedWidget()
        self.gateway_page = build_gateway_page(self)
        self.steven_desk_page = self._build_steven_desk_page()
        self.argus_machine_page = build_argus_machine_console_page(self)
        self.app_stack.addWidget(self.gateway_page)
        self.app_stack.addWidget(self.steven_desk_page)
        self.app_stack.addWidget(self.argus_machine_page)
        layout.addWidget(self.app_stack)

        self.setCentralWidget(root)
        self.setStyleSheet(STYLESHEET)
        self._navigate_to_page(0, record_history=False)

    def _build_steven_desk_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("stevenDeskPage")
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_navigation_rail())
        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self._build_dashboard_page())
        self.page_stack.addWidget(self._build_watchlist_center_page())
        self.page_stack.addWidget(self._build_evidence_console_page())
        self.page_stack.addWidget(self._build_research_lab_page())
        self.page_stack.addWidget(self._build_timeline_replay_page())
        self.page_stack.addWidget(self._build_capture_health_page())
        layout.addWidget(self.page_stack, 1)
        return page

    def show_gateway(self) -> None:
        if not hasattr(self, "app_stack"):
            return
        self.app_stack.setCurrentWidget(self.gateway_page)
        self._update_status("Gateway ready. Choose Steven Desk or Argus Machine.")

    def open_steven_desk(self) -> None:
        if not hasattr(self, "app_stack"):
            return
        self.app_stack.setCurrentWidget(self.steven_desk_page)
        self._navigate_to_page(0, record_history=False)
        self._update_status("Steven Desk open. Existing human-guided dashboard preserved.")

    def open_argus_machine_console(self) -> None:
        if not hasattr(self, "app_stack"):
            return
        refresh_argus_machine_console(self)
        self.app_stack.setCurrentWidget(self.argus_machine_page)
        self._update_status("Argus Machine open in Simulation Lab. FakeBroker only. Live trading locked.")

    def _build_navigation_rail(self) -> QWidget:
        rail = QGroupBox("Momentum")
        rail.setMaximumWidth(174)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(8)

        self.nav_buttons: list[QPushButton] = []
        self.gateway_nav_button = QPushButton("Gateway")
        self.gateway_nav_button.setObjectName("gatewayNavButton")
        self.gateway_nav_button.setToolTip("Return to the Steven Desk / Argus Machine gateway.")
        self.gateway_nav_button.clicked.connect(self.show_gateway)
        layout.addWidget(self.gateway_nav_button)

        self.back_button = QPushButton("Back")
        self.back_button.setEnabled(False)
        self.back_button.setToolTip("Return to the previous Momentum Hunter screen.")
        self.back_button.clicked.connect(self._go_back_page)
        layout.addWidget(self.back_button)

        nav_items = [
            ("Dashboard", "Daily command center: scanner, candidates, next action.", 0),
            ("Watchlist", "Watchlist candidates, entry plans, and saved reports.", 1),
            ("Evidence", "Active Monitor, Evidence Autopilot, alerts, outcomes, and performance.", 2),
            ("Research", "Research Lab and readiness gates. Research-only.", 3),
            ("Replay", "Historical snapshots, candidate timeline, and point-in-time replay.", 4),
            ("Health", "Capture/provider/CSV/outcome diagnostics.", 5),
        ]
        for label, tooltip, index in nav_items:
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(tooltip)
            button.clicked.connect(lambda _checked=False, page=index: self._navigate_to_page(page))
            layout.addWidget(button)
            self.nav_buttons.append(button)

        if APP_LOGO_PATH.exists():
            logo = QLabel()
            logo.setPixmap(contained_logo_pixmap(APP_LOGO_PATH, 92, 92))
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(logo)
        layout.addStretch(1)
        return rail

    def _navigate_to_page(self, index: int, *, record_history: bool = True) -> None:
        if not hasattr(self, "page_stack"):
            return
        if index < 0 or index >= self.page_stack.count():
            self._update_status(f"Navigation target {index} is not available.")
            return
        current_index = self.page_stack.currentIndex()
        if record_history and current_index != index and current_index >= 0:
            self._page_history.append(current_index)
            self._page_history = self._page_history[-25:]
        self.page_stack.setCurrentIndex(index)
        for button_index, button in enumerate(getattr(self, "nav_buttons", [])):
            button.setChecked(button_index == index)
        self._update_back_button()
        if index == 1:
            self._refresh_watchlist_center()
        if index == 4:
            QTimer.singleShot(0, self._autoload_replay_snapshot)

    def _go_back_page(self) -> None:
        if not getattr(self, "_page_history", []):
            self._update_status("No previous Momentum Hunter screen is available.")
            self._update_back_button()
            return
        previous = self._page_history.pop()
        self._navigate_to_page(previous, record_history=False)
        self._update_status(f"Returned to {self._page_name(previous)}.")

    def _update_back_button(self) -> None:
        if not hasattr(self, "back_button"):
            return
        enabled = bool(getattr(self, "_page_history", []))
        self.back_button.setEnabled(enabled)
        if enabled:
            self.back_button.setToolTip(f"Return to {self._page_name(self._page_history[-1])}.")
        else:
            self.back_button.setToolTip("No previous Momentum Hunter screen yet.")

    def _page_name(self, index: int) -> str:
        names = ["Dashboard", "Watchlist", "Evidence", "Research", "Replay", "Health"]
        if 0 <= index < len(names):
            return names[index]
        return f"page {index}"

    def _build_dashboard_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_top_bar())

        self.view_state_label = QLabel()
        self.view_state_label.setObjectName("viewStateCurrent")
        layout.addWidget(self.view_state_label)

        layout.addWidget(self._build_command_status_strip())

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
        return page

    def _build_command_status_strip(self) -> QWidget:
        strip = QGroupBox("Command Status")
        layout = QGridLayout(strip)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.status_market_card = QLabel("Market: checking...")
        self.status_snapshot_card = QLabel("Snapshot: checking...")
        self.status_evidence_card = QLabel("Evidence: checking...")
        self.status_alerts_card = QLabel("Alerts: checking...")
        self.status_outcomes_card = QLabel("Outcomes: checking...")
        self.status_execution_card = QLabel("Execution Ready: checking...")
        self.status_autopilot_card = QLabel("Autopilot: checking...")
        cards = [
            self.status_market_card,
            self.status_snapshot_card,
            self.status_evidence_card,
            self.status_alerts_card,
            self.status_outcomes_card,
            self.status_execution_card,
            self.status_autopilot_card,
        ]
        for index, card in enumerate(cards):
            card.setObjectName("criteriaLabel")
            card.setWordWrap(True)
            layout.addWidget(card, 0, index)
        return strip

    def _build_watchlist_center_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        header = QLabel(
            "WATCHLIST CENTER\n"
            "Review interested/watchlist candidates, complete entry plans, and generate read-only watchlist reports. "
            "No orders are placed."
        )
        header.setObjectName("detailStateLabel")
        header.setWordWrap(True)
        layout.addWidget(header)

        action_box = QGroupBox("Watchlist Actions")
        action_layout = QGridLayout(action_box)
        self.watchlist_center_move_button = QPushButton("Move Interested to Watchlist")
        self.watchlist_center_move_button.clicked.connect(self.add_interested_to_watchlist)
        self.watchlist_center_move_button.setToolTip("Promote all current Interested candidates to Watchlist status.")
        generate_button = QPushButton("Generate Watchlist Report")
        generate_button.clicked.connect(self.save_tomorrow_watchlist)
        latest_button = QPushButton("Open Latest Watchlist")
        latest_button.clicked.connect(self.view_research_list)
        morning_button = QPushButton("Open Morning Review")
        morning_button.clicked.connect(self.open_morning_review_workspace)
        action_layout.addWidget(self.watchlist_center_move_button, 0, 0)
        action_layout.addWidget(generate_button, 0, 1)
        action_layout.addWidget(latest_button, 0, 2)
        action_layout.addWidget(morning_button, 0, 3)
        layout.addWidget(action_box)

        self.watchlist_center_summary_label = QLabel("Watchlist Center: no candidates loaded.")
        self.watchlist_center_summary_label.setObjectName("criteriaLabel")
        self.watchlist_center_summary_label.setWordWrap(True)
        layout.addWidget(self.watchlist_center_summary_label)

        self.watchlist_center_table = QTableWidget(0, 6)
        self.watchlist_center_table.setHorizontalHeaderLabels(["Ticker", "Status", "Score", "Trade Plan", "Missing Fields", "Action"])
        self.watchlist_center_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.watchlist_center_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.watchlist_center_table.verticalHeader().setVisible(False)
        self.watchlist_center_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.watchlist_center_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.watchlist_center_table.itemDoubleClicked.connect(self._watchlist_center_item_open_plan)
        layout.addWidget(self.watchlist_center_table, 1)

        guidance = QLabel(
            "Use Edit Plan from any incomplete row to jump directly to the Dashboard entry-plan editor for that candidate."
        )
        guidance.setObjectName("criteriaLabel")
        guidance.setWordWrap(True)
        layout.addWidget(guidance)
        return page

    def _build_evidence_console_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        header = QLabel(
            "EVIDENCE CONSOLE\n"
            "Active Monitor, Evidence Autopilot, alerts, outcomes, performance, and state transitions. "
            "Evidence infrastructure only; no trading rules are changed."
        )
        header.setObjectName("detailStateLabel")
        header.setWordWrap(True)
        layout.addWidget(header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._build_execution_ready_panel())
        layout.addWidget(scroll, 1)
        return page

    def _build_research_lab_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        header = QLabel(
            "RESEARCH LAB\n"
            "Stored-data studies, catalyst research, outcome research, and readiness gates. Research-only."
        )
        header.setObjectName("detailStateLabel")
        header.setWordWrap(True)
        layout.addWidget(header)
        action_box = QGroupBox("Research Actions")
        action_layout = QHBoxLayout(action_box)
        open_research = QPushButton("Open Research Lab")
        open_research.clicked.connect(self.open_study_engine)
        readiness = QPushButton("Open Readiness Gate")
        readiness.clicked.connect(self.open_readiness_gate)
        action_layout.addWidget(open_research)
        action_layout.addWidget(readiness)
        action_layout.addStretch(1)
        layout.addWidget(action_box)
        note = QLabel(
            "Research views use stored data and post-capture outcomes. They remain read-only for trading workflow decisions."
        )
        note.setObjectName("criteriaLabel")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return page

    def _build_timeline_replay_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        header = QLabel(
            "TIMELINE / REPLAY\n"
            "Open historical snapshots and point-in-time candidate replay. Replay is read-only."
        )
        header.setObjectName("detailStateLabel")
        header.setWordWrap(True)
        layout.addWidget(header)

        controls = QGroupBox("Historical Snapshot")
        grid = QGridLayout(controls)
        grid.addWidget(QLabel("History Date"), 0, 0)
        grid.addWidget(self.capture_date_combo, 0, 1)
        grid.addWidget(QLabel("Session"), 0, 2)
        grid.addWidget(self.capture_session_combo, 0, 3)
        grid.addWidget(self.open_capture_button, 0, 4)
        grid.addWidget(self.current_button, 0, 5)
        layout.addWidget(controls)

        action_box = QGroupBox("Candidate Timeline")
        action_layout = QHBoxLayout(action_box)
        timeline_button = QPushButton("Open Timeline / Replay For Selected Candidate")
        timeline_button.clicked.connect(self.view_candidate_timeline)
        action_layout.addWidget(timeline_button)
        action_layout.addStretch(1)
        layout.addWidget(action_box)

        snapshot_box = QGroupBox("Snapshot Candidates")
        snapshot_layout = QVBoxLayout(snapshot_box)
        self.replay_snapshot_status_label = QLabel(
            "Open a historical snapshot to load candidates, or use the selected historical date/session above."
        )
        self.replay_snapshot_status_label.setObjectName("criteriaLabel")
        self.replay_snapshot_status_label.setWordWrap(True)
        snapshot_layout.addWidget(self.replay_snapshot_status_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.replay_snapshot_table = QTableWidget(0, 7)
        self.replay_snapshot_table.setHorizontalHeaderLabels(["Ticker", "Score", "Price", "% Chg", "Volume", "Rel Vol", "Market Cap"])
        self.replay_snapshot_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.replay_snapshot_table.horizontalHeader().setStretchLastSection(True)
        self.replay_snapshot_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.replay_snapshot_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.replay_snapshot_table.setMinimumHeight(260)
        self.replay_snapshot_table.itemSelectionChanged.connect(self._replay_snapshot_selection_changed)
        splitter.addWidget(self.replay_snapshot_table)
        self.replay_snapshot_detail = QTextBrowser()
        self.replay_snapshot_detail.setHtml(format_replay_snapshot_detail_html(None, reason="Open a historical snapshot to inspect its candidates."))
        splitter.addWidget(self.replay_snapshot_detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        snapshot_layout.addWidget(splitter, 1)
        layout.addWidget(snapshot_box, 1)
        return page

    def _build_capture_health_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        header = QLabel(
            "CAPTURE HEALTH\n"
            "Provider, scheduled capture, CSV, and outcome-update diagnostics. Read-only except Retry Scan."
        )
        header.setObjectName("detailStateLabel")
        header.setWordWrap(True)
        layout.addWidget(header)

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

        details_button = QPushButton("Open Capture Health Details")
        details_button.clicked.connect(self.open_capture_health_report)
        layout.addWidget(details_button)
        layout.addStretch(1)
        return page

    def _build_execution_ready_panel(self) -> QWidget:
        box = QGroupBox("Evidence Console")
        layout = QVBoxLayout(box)
        self.active_monitor_summary_label = QLabel("ACTIVE MONITOR: checking latest cycle...")
        self.active_monitor_summary_label.setWordWrap(True)
        monitor_controls = QHBoxLayout()
        self.run_monitor_button = QPushButton("Run Monitor Cycle")
        self.run_monitor_button.setToolTip("Run one derived active-monitor cycle from the latest trade-planning report. No orders are placed.")
        self.run_monitor_button.clicked.connect(self.run_active_monitor_cycle)
        self.start_monitor_loop_button = QPushButton("Start Monitor Loop")
        self.start_monitor_loop_button.setToolTip("Start background active monitoring. No orders are placed.")
        self.start_monitor_loop_button.clicked.connect(self.start_active_monitor_loop)
        self.stop_monitor_loop_button = QPushButton("Stop Monitor")
        self.stop_monitor_loop_button.setToolTip("Stop the background active monitor process.")
        self.stop_monitor_loop_button.clicked.connect(self.stop_active_monitor_loop)
        self.monitor_interval_combo = QComboBox()
        self.monitor_interval_combo.addItem("5 min", 300)
        self.monitor_interval_combo.addItem("15 min", 900)
        self.monitor_interval_combo.addItem("1 min", 60)
        self.monitor_interval_combo.setToolTip("Background monitor interval.")
        self.fetch_missing_quotes_checkbox = QCheckBox("Fetch missing quotes")
        self.fetch_missing_quotes_checkbox.setToolTip("Optionally fetch quote tape for watchlist/user-defined symbols missing from the latest trade-planning report.")
        self.refresh_target_quotes_checkbox = QCheckBox("Refresh target quotes")
        self.refresh_target_quotes_checkbox.setToolTip("Fetch fresh quote tape for every active monitor target into a derived monitoring report.")
        monitor_controls.addWidget(self.run_monitor_button)
        monitor_controls.addWidget(self.start_monitor_loop_button)
        monitor_controls.addWidget(self.stop_monitor_loop_button)
        monitor_controls.addWidget(self.monitor_interval_combo)
        monitor_controls.addWidget(self.fetch_missing_quotes_checkbox)
        monitor_controls.addWidget(self.refresh_target_quotes_checkbox)
        monitor_controls.addStretch(1)
        symbol_controls = QHBoxLayout()
        self.monitor_symbol_input = QLineEdit()
        self.monitor_symbol_input.setPlaceholderText("Symbol")
        self.monitor_symbol_input.setMaximumWidth(110)
        self.monitor_symbol_note_input = QLineEdit()
        self.monitor_symbol_note_input.setPlaceholderText("Monitor note")
        self.add_monitor_symbol_button = QPushButton("Add Symbol")
        self.add_monitor_symbol_button.setToolTip("Add a user-defined symbol to the active monitor universe.")
        self.add_monitor_symbol_button.clicked.connect(self.add_user_monitor_symbol)
        self.remove_monitor_symbol_button = QPushButton("Remove Selected")
        self.remove_monitor_symbol_button.setToolTip("Remove selected user-defined monitor symbol(s).")
        self.remove_monitor_symbol_button.clicked.connect(self.remove_selected_user_monitor_symbols)
        symbol_controls.addWidget(self.monitor_symbol_input)
        symbol_controls.addWidget(self.monitor_symbol_note_input, 1)
        symbol_controls.addWidget(self.add_monitor_symbol_button)
        symbol_controls.addWidget(self.remove_monitor_symbol_button)
        self.active_monitor_table = QTableWidget(0, 3)
        self.active_monitor_table.setHorizontalHeaderLabels(["Metric", "Value", "Note"])
        self.active_monitor_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.active_monitor_table.verticalHeader().setVisible(False)
        self.active_monitor_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.active_monitor_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.active_monitor_table.setMaximumHeight(115)
        autopilot_controls = QHBoxLayout()
        self.run_evidence_autopilot_button = QPushButton("Run Evidence Autopilot")
        self.run_evidence_autopilot_button.setToolTip("Run monitor cycle, outcome updater, evidence health report, and daily evidence brief. No trading rules are changed.")
        self.run_evidence_autopilot_button.clicked.connect(self.run_evidence_autopilot_once)
        autopilot_controls.addWidget(self.run_evidence_autopilot_button)
        autopilot_controls.addStretch(1)
        self.evidence_autopilot_summary_label = QLabel("EVIDENCE AUTOPILOT: checking latest run...")
        self.evidence_autopilot_summary_label.setWordWrap(True)
        self.evidence_autopilot_table = QTableWidget(0, 3)
        self.evidence_autopilot_table.setHorizontalHeaderLabels(["Metric", "Value", "Note"])
        self.evidence_autopilot_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.evidence_autopilot_table.verticalHeader().setVisible(False)
        self.evidence_autopilot_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.evidence_autopilot_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.evidence_autopilot_table.setMaximumHeight(120)
        self.evidence_health_summary_label = QLabel("EVIDENCE HEALTH: checking alert evidence pipeline...")
        self.evidence_health_summary_label.setWordWrap(True)
        self.evidence_health_table = QTableWidget(0, 3)
        self.evidence_health_table.setHorizontalHeaderLabels(["Metric", "Value", "Note"])
        self.evidence_health_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.evidence_health_table.verticalHeader().setVisible(False)
        self.evidence_health_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.evidence_health_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.evidence_health_table.setMaximumHeight(120)
        self.user_monitor_symbols_table = QTableWidget(0, 3)
        self.user_monitor_symbols_table.setHorizontalHeaderLabels(["Symbol", "Enabled", "Notes"])
        self.user_monitor_symbols_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.user_monitor_symbols_table.verticalHeader().setVisible(False)
        self.user_monitor_symbols_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.user_monitor_symbols_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.user_monitor_symbols_table.setMaximumHeight(95)
        self.execution_ready_summary_label = QLabel("EXECUTION READY: checking latest trade-planning report...")
        self.execution_ready_summary_label.setWordWrap(True)
        self.execution_ready_table = QTableWidget(0, 15)
        self.execution_ready_table.setHorizontalHeaderLabels(
            [
                "Symbol",
                "State",
                "Price",
                "Bid",
                "Ask",
                "Spread %",
                "Premkt %",
                "Premkt Vol",
                "RVOL Type",
                "RVOL",
                "Entry",
                "Stop",
                "Target 1",
                "Target 2",
                "Reason",
            ]
        )
        self.execution_ready_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.execution_ready_table.verticalHeader().setVisible(False)
        self.execution_ready_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.execution_ready_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.execution_ready_table.setMaximumHeight(150)
        self.state_transition_summary_label = QLabel("STATE TRANSITIONS: checking latest event report...")
        self.state_transition_summary_label.setWordWrap(True)
        self.state_transition_table = QTableWidget(0, 5)
        self.state_transition_table.setHorizontalHeaderLabels(["Timestamp", "Symbol", "Old State", "New State", "Reason"])
        self.state_transition_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.state_transition_table.verticalHeader().setVisible(False)
        self.state_transition_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.state_transition_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.state_transition_table.setMaximumHeight(105)
        self.active_alerts_summary_label = QLabel("ACTIVE ALERTS: checking alert store...")
        self.active_alerts_summary_label.setWordWrap(True)
        self.active_alerts_table = QTableWidget(0, 8)
        self.active_alerts_table.setHorizontalHeaderLabels(["Time", "Symbol", "Alert Type", "State", "Price", "RVOL", "Entry", "Reason"])
        self.active_alerts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.active_alerts_table.verticalHeader().setVisible(False)
        self.active_alerts_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.active_alerts_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.active_alerts_table.setMaximumHeight(120)
        outcome_controls = QHBoxLayout()
        self.update_alert_outcomes_button = QPushButton("Update Alert Outcomes")
        self.update_alert_outcomes_button.setToolTip("Update pending alert outcomes from one-minute bars. No orders are placed.")
        self.update_alert_outcomes_button.clicked.connect(self.run_alert_outcome_update)
        self.fetch_minute_bars_checkbox = QCheckBox("Fetch minute bars")
        self.fetch_minute_bars_checkbox.setToolTip("Fetch missing one-minute Yahoo chart bars for pending alerts.")
        outcome_controls.addWidget(self.update_alert_outcomes_button)
        outcome_controls.addWidget(self.fetch_minute_bars_checkbox)
        outcome_controls.addStretch(1)
        self.alert_outcome_update_status_label = QLabel("OUTCOME UPDATE: not run yet")
        self.alert_outcome_update_status_label.setWordWrap(True)
        self.alert_outcome_summary_label = QLabel("ALERT OUTCOME TRACKER: checking alert store...")
        self.alert_outcome_summary_label.setWordWrap(True)
        self.alert_outcome_table = QTableWidget(0, 8)
        self.alert_outcome_table.setHorizontalHeaderLabels(["Time", "Symbol", "Alert Type", "Status", "Class", "15m", "MFE 30m", "MAE 30m"])
        self.alert_outcome_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.alert_outcome_table.verticalHeader().setVisible(False)
        self.alert_outcome_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alert_outcome_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.alert_outcome_table.setMaximumHeight(120)
        self.alert_performance_summary_label = QLabel("ALERT PERFORMANCE: checking historical alert outcomes...")
        self.alert_performance_summary_label.setWordWrap(True)
        self.alert_performance_table = QTableWidget(0, 8)
        self.alert_performance_table.setHorizontalHeaderLabels(
            ["Section", "Group", "Alerts", "Completed", "Win %", "Avg 60m", "Avg MFE", "Avg MAE"]
        )
        self.alert_performance_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.alert_performance_table.verticalHeader().setVisible(False)
        self.alert_performance_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.alert_performance_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.alert_performance_table.setMaximumHeight(145)
        self.evidence_next_action_label = QLabel("Evidence Console: checking what needs attention...")
        self.evidence_next_action_label.setObjectName("detailStateLabel")
        self.evidence_next_action_label.setWordWrap(True)
        layout.addWidget(self.evidence_next_action_label)

        tabs = QTabWidget()
        monitor_tab = QWidget()
        monitor_layout = QVBoxLayout(monitor_tab)
        monitor_layout.addWidget(self.active_monitor_summary_label)
        monitor_layout.addLayout(monitor_controls)
        monitor_layout.addLayout(symbol_controls)
        monitor_layout.addWidget(self.user_monitor_symbols_table)
        monitor_layout.addWidget(self.active_monitor_table)
        monitor_layout.addLayout(autopilot_controls)
        monitor_layout.addWidget(self.evidence_autopilot_summary_label)
        monitor_layout.addWidget(self.evidence_autopilot_table)
        monitor_layout.addWidget(self.evidence_health_summary_label)
        monitor_layout.addWidget(self.evidence_health_table)

        execution_tab = QWidget()
        execution_layout = QVBoxLayout(execution_tab)
        execution_layout.addWidget(self.execution_ready_summary_label)
        execution_layout.addWidget(self.execution_ready_table)
        execution_layout.addWidget(self.state_transition_summary_label)
        execution_layout.addWidget(self.state_transition_table)
        execution_layout.addStretch(1)

        alerts_tab = QWidget()
        alerts_layout = QVBoxLayout(alerts_tab)
        alerts_layout.addWidget(self.active_alerts_summary_label)
        alerts_layout.addWidget(self.active_alerts_table)
        alerts_layout.addLayout(outcome_controls)
        alerts_layout.addWidget(self.alert_outcome_update_status_label)
        alerts_layout.addWidget(self.alert_outcome_summary_label)
        alerts_layout.addWidget(self.alert_outcome_table)
        alerts_layout.addStretch(1)

        performance_tab = QWidget()
        performance_layout = QVBoxLayout(performance_tab)
        performance_layout.addWidget(self.alert_performance_summary_label)
        performance_layout.addWidget(self.alert_performance_table)
        performance_layout.addStretch(1)

        tabs.addTab(monitor_tab, "Monitor + Health")
        tabs.addTab(execution_tab, "Execution Ready")
        tabs.addTab(alerts_tab, "Alerts + Outcomes")
        tabs.addTab(performance_tab, "Performance")
        layout.addWidget(tabs)
        return box

    def _refresh_execution_ready_panel(self) -> None:
        if not hasattr(self, "execution_ready_table"):
            return
        monitor_path = latest_active_monitor_cycle_json_path()
        monitor_rows = load_active_monitor_dashboard_rows(monitor_path)
        self.active_monitor_table.setRowCount(len(monitor_rows))
        for row_index, row in enumerate(monitor_rows):
            values = [row.get("metric", ""), row.get("value", ""), row.get("note", "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if row.get("severity") == "warn":
                    item.setBackground(QColor("#735f24"))
                elif row.get("severity") == "good":
                    item.setBackground(QColor("#1f6f4a"))
                self.active_monitor_table.setItem(row_index, col, item)
        if monitor_path and monitor_rows:
            self.active_monitor_summary_label.setText(active_monitor_summary_text(monitor_path))
            self.active_monitor_table.show()
        else:
            self.active_monitor_summary_label.setText("ACTIVE MONITOR: NO CYCLE REPORT YET")
            self.active_monitor_table.hide()
        autopilot_rows = load_evidence_autopilot_dashboard_rows()
        self.evidence_autopilot_table.setRowCount(len(autopilot_rows))
        for row_index, row in enumerate(autopilot_rows):
            values = [row.get("metric", ""), row.get("value", ""), row.get("note", "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if row.get("severity") == "warn":
                    item.setBackground(QColor("#735f24"))
                elif row.get("severity") == "good":
                    item.setBackground(QColor("#1f6f4a"))
                self.evidence_autopilot_table.setItem(row_index, col, item)
        self.evidence_autopilot_summary_label.setText(evidence_autopilot_summary_text())
        if autopilot_rows:
            self.evidence_autopilot_table.show()
        else:
            self.evidence_autopilot_table.hide()
        evidence_rows = load_evidence_health_dashboard_rows()
        self.evidence_health_table.setRowCount(len(evidence_rows))
        for row_index, row in enumerate(evidence_rows):
            values = [row.get("metric", ""), row.get("value", ""), row.get("note", "")]
            for col, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if row.get("severity") == "warn":
                    item.setBackground(QColor("#735f24"))
                elif row.get("severity") == "good":
                    item.setBackground(QColor("#1f6f4a"))
                self.evidence_health_table.setItem(row_index, col, item)
        self.evidence_health_summary_label.setText(evidence_health_summary_text())
        if evidence_rows:
            self.evidence_health_table.show()
        else:
            self.evidence_health_table.hide()
        user_symbol_rows = load_user_monitor_symbol_rows()
        self.user_monitor_symbols_table.setRowCount(len(user_symbol_rows))
        for row_index, row in enumerate(user_symbol_rows):
            values = [row.get("symbol", ""), row.get("enabled", ""), row.get("notes", "")]
            for col, value in enumerate(values):
                self.user_monitor_symbols_table.setItem(row_index, col, QTableWidgetItem(str(value)))
        if user_symbol_rows:
            self.user_monitor_symbols_table.show()
        else:
            self.user_monitor_symbols_table.hide()
        path = latest_trade_plan_csv_path()
        rows = load_execution_ready_rows(path) if path else []
        self.execution_ready_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = [
                row.get("Symbol", ""),
                row.get("Readiness", ""),
                execution_ready_display_price(row),
                row.get("Current Bid", ""),
                row.get("Current Ask", ""),
                row.get("Spread %", ""),
                row.get("Premarket %", ""),
                row.get("Premarket Volume", ""),
                row.get("RVOL Type", ""),
                row.get("Relative Volume", ""),
                row.get("Bullish Entry", ""),
                row.get("Bullish Stop", ""),
                row.get("Bullish Target 1", ""),
                row.get("Bullish Target 2", ""),
                execution_ready_reason(row),
            ]
            for col, value in enumerate(values):
                self.execution_ready_table.setItem(row_index, col, QTableWidgetItem(str(value)))
        if rows:
            self.execution_ready_summary_label.setText(f"EXECUTION READY: {len(rows)} trade(s) from {path.name}")
            self.execution_ready_table.show()
        else:
            source = f" Latest report: {path.name}" if path else " No trade-planning report found."
            self.execution_ready_summary_label.setText(f"EXECUTION READY: NONE.{source}")
            self.execution_ready_table.hide()
        transition_path = latest_trade_plan_json_path(path)
        transitions = load_state_transition_rows(transition_path)
        self.state_transition_table.setRowCount(len(transitions))
        for row_index, row in enumerate(transitions):
            values = [
                row.get("timestamp", ""),
                row.get("symbol", ""),
                row.get("old_state", ""),
                row.get("new_state", ""),
                row.get("reason", ""),
            ]
            for col, value in enumerate(values):
                self.state_transition_table.setItem(row_index, col, QTableWidgetItem(str(value)))
        if transitions:
            self.state_transition_summary_label.setText(f"STATE TRANSITIONS: {len(transitions)} change(s) from {transition_path.name if transition_path else 'latest report'}")
            self.state_transition_table.show()
        else:
            self.state_transition_summary_label.setText("STATE TRANSITIONS: NONE YET")
            self.state_transition_table.hide()
        alerts = load_active_alert_rows()
        self.active_alerts_table.setRowCount(len(alerts))
        for row_index, row in enumerate(alerts):
            values = [
                row.get("timestamp", ""),
                row.get("symbol", ""),
                row.get("alert_type", ""),
                row.get("current_state", ""),
                row.get("price", ""),
                row.get("rvol", ""),
                row.get("suggested_entry", ""),
                row.get("reason", ""),
            ]
            for col, value in enumerate(values):
                self.active_alerts_table.setItem(row_index, col, QTableWidgetItem(str(value)))
        if alerts:
            self.active_alerts_summary_label.setText(f"ACTIVE ALERTS: {len(alerts)} pending validation alert(s)")
            self.active_alerts_table.show()
        else:
            self.active_alerts_summary_label.setText("ACTIVE ALERTS: NONE")
            self.active_alerts_table.hide()
        if hasattr(self, "alert_outcome_update_status_label"):
            self.alert_outcome_update_status_label.setText(alert_outcome_update_status_text())
        outcome_rows = load_alert_outcome_rows()
        self.alert_outcome_table.setRowCount(len(outcome_rows))
        for row_index, row in enumerate(outcome_rows):
            outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
            values = [
                row.get("timestamp", ""),
                row.get("symbol", ""),
                row.get("alert_type", ""),
                outcome.get("status", ""),
                outcome.get("classification", ""),
                outcome.get("fifteen_minute_return_pct", ""),
                outcome.get("mfe_30m_pct", ""),
                outcome.get("mae_30m_pct", ""),
            ]
            for col, value in enumerate(values):
                self.alert_outcome_table.setItem(row_index, col, QTableWidgetItem(str(value)))
        if outcome_rows:
            completed = sum(1 for row in outcome_rows if isinstance(row.get("outcome"), dict) and row["outcome"].get("status") == "COMPLETED")
            self.alert_outcome_summary_label.setText(f"ALERT OUTCOME TRACKER: {len(outcome_rows)} recent alert(s), {completed} completed")
            self.alert_outcome_table.show()
        else:
            self.alert_outcome_summary_label.setText("ALERT OUTCOME TRACKER: NO ALERTS TRACKED YET")
            self.alert_outcome_table.hide()
        performance_rows = load_alert_performance_dashboard_rows()
        self.alert_performance_table.setRowCount(len(performance_rows))
        for row_index, row in enumerate(performance_rows):
            values = [
                row.get("section", ""),
                row.get("group", ""),
                row.get("alert_count", ""),
                row.get("completed_count", ""),
                row.get("win_rate_pct", ""),
                row.get("average_60m_return_pct", ""),
                row.get("average_mfe_pct", ""),
                row.get("average_mae_pct", ""),
            ]
            for col, value in enumerate(values):
                self.alert_performance_table.setItem(row_index, col, QTableWidgetItem(str(value)))
        if performance_rows:
            self.alert_performance_summary_label.setText(alert_performance_summary_text())
            self.alert_performance_table.show()
        else:
            self.alert_performance_summary_label.setText(alert_performance_summary_text())
            self.alert_performance_table.hide()
        if hasattr(self, "evidence_next_action_label"):
            self.evidence_next_action_label.setText(
                evidence_next_action_text(
                    execution_ready_count=len(rows),
                    active_alert_count=len(alerts),
                    outcome_count=len(outcome_rows),
                    performance_count=len(performance_rows),
                    monitor_summary=self.active_monitor_summary_label.text(),
                    evidence_summary=self.evidence_health_summary_label.text(),
                )
            )
        self._refresh_command_status_cards()

    def _refresh_command_status_cards(self) -> None:
        if not hasattr(self, "status_market_card"):
            return

        context = self.current_operator_context or self._operator_review_context()
        self.status_market_card.setText(f"Market: {self.market_regime.regime.value.upper()}")
        self.status_snapshot_card.setText(f"Snapshot: {context.label}")
        self.status_evidence_card.setText(
            compact_status_text(getattr(self, "evidence_health_summary_label", None), "Evidence: checking...")
        )
        self.status_alerts_card.setText(
            compact_status_text(getattr(self, "active_alerts_summary_label", None), "Alerts: checking...")
        )
        self.status_outcomes_card.setText(
            compact_status_text(getattr(self, "alert_outcome_summary_label", None), "Outcomes: checking...")
        )
        self.status_execution_card.setText(
            compact_status_text(getattr(self, "execution_ready_summary_label", None), "Execution Ready: checking...")
        )
        self.status_autopilot_card.setText(
            compact_status_text(getattr(self, "evidence_autopilot_summary_label", None), "Autopilot: checking...")
        )

    def _refresh_watchlist_center(self) -> None:
        if not hasattr(self, "watchlist_center_table"):
            return
        interested = [
            candidate
            for candidate in self.candidates
            if self._candidate_review_status(candidate) == ReviewStatus.INTERESTED
        ]
        watchlist = self._watchlist_candidates()
        rows = interested + [candidate for candidate in watchlist if candidate not in interested]
        self.watchlist_center_table.setRowCount(len(rows))
        for row_index, candidate in enumerate(rows):
            status = self._candidate_review_status(candidate)
            identity = self._candidate_identity(candidate)
            plan = self.entry_plans.get(identity.key)
            plan_warnings = entry_plan_warnings(plan) if plan else ["missing trigger", "missing stop", "missing invalidation", "missing max loss"]
            plan_progress = entry_plan_progress_text(plan_warnings)
            values = [
                candidate.ticker,
                status.value.title(),
                str(candidate.score),
                "Complete 4/4" if plan and plan.plan_complete and not plan_warnings else f"Incomplete {plan_progress}",
                " | ".join(plan_warnings) if plan_warnings else "none",
                "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setBackground(review_status_color(status))
                if column == 2:
                    item.setBackground(score_color(candidate.score))
                if column in {3, 4} and plan_warnings:
                    item.setBackground(QBrush(QColor("#735f24")))
                if column in {3, 4}:
                    item.setToolTip("Complete entry plan fields: trigger, stop, invalidation, and max loss.")
                if column == 4:
                    item.setToolTip("Missing: " + (" | ".join(plan_warnings) if plan_warnings else "none"))
                self.watchlist_center_table.setItem(row_index, column, item)
            button = QPushButton("Edit Plan" if plan_warnings else "View Plan")
            button.setProperty("ticker", candidate.ticker)
            button.setToolTip("Open this candidate in the Dashboard entry-plan editor.")
            button.clicked.connect(self._watchlist_center_open_plan_from_button)
            self.watchlist_center_table.setCellWidget(row_index, 5, button)
        self.watchlist_center_table.setVisible(bool(rows))
        self.watchlist_center_summary_label.setText(
            f"Interested: {len(interested)} | Watchlist: {len(watchlist)} | "
            f"{'Move Interested to Watchlist when ready.' if interested else 'No interested candidates waiting to move.'}"
        )

    def _watchlist_center_open_plan_from_button(self) -> None:
        sender = self.sender()
        ticker = str(sender.property("ticker")) if sender is not None and sender.property("ticker") else ""
        self._open_entry_plan_editor_for_ticker(ticker)

    def _watchlist_center_item_open_plan(self, item: QTableWidgetItem) -> None:
        ticker_item = self.watchlist_center_table.item(item.row(), 0)
        ticker = ticker_item.text() if ticker_item else ""
        self._open_entry_plan_editor_for_ticker(ticker)

    def _open_entry_plan_editor_for_ticker(self, ticker: str) -> None:
        if not ticker:
            self._show_action_blocked("No watchlist candidate selected.")
            return
        candidate = next((item for item in self.candidates if item.ticker.upper() == ticker.upper()), None)
        if candidate is None:
            self._show_action_blocked(f"{ticker} is not loaded in the current candidate set.")
            return
        self._navigate_to_page(0)
        for row, loaded in enumerate(self.candidates):
            if loaded.ticker.upper() == ticker.upper():
                self.table.selectRow(row)
                break
        self._show_candidate_details(candidate)
        self.entry_trigger.setFocus()
        self._update_status(f"Editing entry plan for {ticker}.")

    def run_active_monitor_cycle(self) -> None:
        if hasattr(self, "run_monitor_button"):
            self.run_monitor_button.setEnabled(False)
        fetch_missing_quotes = bool(
            hasattr(self, "fetch_missing_quotes_checkbox") and self.fetch_missing_quotes_checkbox.isChecked()
        )
        refresh_target_quotes = bool(
            hasattr(self, "refresh_target_quotes_checkbox") and self.refresh_target_quotes_checkbox.isChecked()
        )
        try:
            self._update_status("Running active monitor cycle...")
            report = run_monitor_cycle(
                fetch_missing_market_data=fetch_missing_quotes,
                refresh_target_market_data=refresh_target_quotes,
                status_path=ACTIVE_MONITOR_STATUS_PATH,
            )
            self._refresh_execution_ready_panel()
            warning_note = f" Warnings: {len(report.warnings)}." if report.warnings else ""
            self._update_status(
                f"Active monitor cycle complete: {report.target_count} target(s), "
                f"{report.new_alert_count} new alert(s), {report.active_alert_count} active alert(s).{warning_note}"
            )
        except Exception as exc:
            message = f"Active monitor cycle failed: {type(exc).__name__}: {exc}"
            self._show_action_blocked(message)
            self._update_status(message)
        finally:
            if hasattr(self, "run_monitor_button"):
                self.run_monitor_button.setEnabled(True)

    def run_evidence_autopilot_once(self) -> None:
        if hasattr(self, "run_evidence_autopilot_button"):
            self.run_evidence_autopilot_button.setEnabled(False)
        try:
            self._update_status("Running Evidence Autopilot...")
            status = run_evidence_autopilot()
            self._refresh_execution_ready_panel()
            warning_note = f" Warnings: {status.warning_count}." if status.warning_count else ""
            self._update_status(
                f"Evidence Autopilot complete: {status.new_alert_count} new alert(s), "
                f"{status.completed_outcome_count} completed outcome(s), "
                f"{status.pending_alert_count} pending alert(s).{warning_note}"
            )
        except Exception as exc:
            message = f"Evidence Autopilot failed: {type(exc).__name__}: {exc}"
            self._show_action_blocked(message)
            self._update_status(message)
            self._refresh_execution_ready_panel()
        finally:
            if hasattr(self, "run_evidence_autopilot_button"):
                self.run_evidence_autopilot_button.setEnabled(True)

    def run_alert_outcome_update(self) -> None:
        if hasattr(self, "update_alert_outcomes_button"):
            self.update_alert_outcomes_button.setEnabled(False)
        fetch_minute_bars = bool(
            hasattr(self, "fetch_minute_bars_checkbox") and self.fetch_minute_bars_checkbox.isChecked()
        )
        try:
            self._update_status("Updating alert outcomes from minute bars...")
            report = update_alert_store_from_minute_bars(
                fetch_missing_bars=fetch_minute_bars,
                status_path=ALERT_OUTCOME_UPDATE_STATUS_PATH,
            )
            self._refresh_execution_ready_panel()
            warning_note = f" Warnings: {len(report.warnings)}." if report.warnings else ""
            self._update_status(
                f"Alert outcomes updated: {report.updated_alert_count} changed, "
                f"{report.completed_alert_count} completed, {report.pending_alert_count} pending, "
                f"{report.unscorable_alert_count} unscorable.{warning_note}"
            )
        except Exception as exc:
            message = f"Alert outcome update failed: {type(exc).__name__}: {exc}"
            self._show_action_blocked(message)
            self._update_status(message)
        finally:
            if hasattr(self, "update_alert_outcomes_button"):
                self.update_alert_outcomes_button.setEnabled(True)

    def start_active_monitor_loop(self) -> None:
        fetch_missing_quotes = bool(
            hasattr(self, "fetch_missing_quotes_checkbox") and self.fetch_missing_quotes_checkbox.isChecked()
        )
        refresh_target_quotes = bool(
            hasattr(self, "refresh_target_quotes_checkbox") and self.refresh_target_quotes_checkbox.isChecked()
        )
        interval_seconds = 300
        if hasattr(self, "monitor_interval_combo"):
            value = self.monitor_interval_combo.currentData()
            try:
                interval_seconds = int(value)
            except (TypeError, ValueError):
                interval_seconds = 300
        try:
            state = start_active_monitor_background(
                interval_seconds=interval_seconds,
                fetch_missing_market_data=fetch_missing_quotes,
                refresh_target_market_data=refresh_target_quotes,
            )
            self._update_status(
                f"Active monitor loop running: PID {state.pid}, every {state.interval_seconds} seconds."
            )
            self._refresh_execution_ready_panel()
        except Exception as exc:
            message = f"Active monitor loop failed to start: {type(exc).__name__}: {exc}"
            self._show_action_blocked(message)
            self._update_status(message)

    def stop_active_monitor_loop(self) -> None:
        try:
            state = stop_active_monitor_background()
            self._update_status(f"Active monitor loop {state.state.lower()}: PID {state.pid}.")
            self._refresh_execution_ready_panel()
        except Exception as exc:
            message = f"Active monitor loop failed to stop: {type(exc).__name__}: {exc}"
            self._show_action_blocked(message)
            self._update_status(message)

    def add_user_monitor_symbol(self) -> None:
        symbol = self.monitor_symbol_input.text().strip() if hasattr(self, "monitor_symbol_input") else ""
        note = self.monitor_symbol_note_input.text().strip() if hasattr(self, "monitor_symbol_note_input") else ""
        if not symbol:
            self._show_action_blocked("No symbol entered. Type a symbol to add to the active monitor.")
            return
        try:
            record = upsert_user_defined_symbol(symbol, notes=note)
            if hasattr(self, "monitor_symbol_input"):
                self.monitor_symbol_input.clear()
            if hasattr(self, "monitor_symbol_note_input"):
                self.monitor_symbol_note_input.clear()
            self._refresh_execution_ready_panel()
            self._update_status(f"Added {record.symbol} to user-defined active monitor symbols.")
        except Exception as exc:
            message = f"Could not add monitor symbol: {type(exc).__name__}: {exc}"
            self._show_action_blocked(message)
            self._update_status(message)

    def remove_selected_user_monitor_symbols(self) -> None:
        if not hasattr(self, "user_monitor_symbols_table"):
            return
        rows = sorted({index.row() for index in self.user_monitor_symbols_table.selectedIndexes()}, reverse=True)
        if not rows:
            self._show_action_blocked("No monitor symbol selected.")
            return
        removed: list[str] = []
        for row in rows:
            item = self.user_monitor_symbols_table.item(row, 0)
            symbol = item.text().strip() if item else ""
            if symbol and remove_user_defined_symbol(symbol):
                removed.append(symbol)
        self._refresh_execution_ready_panel()
        if removed:
            self._update_status(f"Removed {', '.join(sorted(removed))} from user-defined monitor symbols.")
        else:
            self._show_action_blocked("Selected monitor symbol was not found in the user-defined monitor list.")

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
        self.scanner_combo.addItems([scanner_display_name(name) for name in SCANNER_PRESETS.keys()])
        for index, internal_name in enumerate(SCANNER_PRESETS.keys()):
            self.scanner_combo.setItemData(
                index,
                SCANNER_DISPLAY_DESCRIPTIONS.get(internal_name, scanner_display_name(internal_name)),
                Qt.ItemDataRole.ToolTipRole,
            )
        self.scanner_combo.currentTextChanged.connect(self._scanner_changed)

        self.scan_button = QPushButton("Run Scanner")
        self.scan_button.clicked.connect(self.run_scan)

        self.watchlist_button = QPushButton("Generate Watchlist Report")
        self.watchlist_button.clicked.connect(self.save_tomorrow_watchlist)
        self.watchlist_button.setToolTip("Daily workflow: generate the next-session watchlist report. No orders are placed.")

        self.view_button = QPushButton("Open Latest Watchlist")
        self.view_button.clicked.connect(self.view_research_list)
        self.view_button.setToolTip("Open the latest saved watchlist/report artifact. Read-only review.")

        self.capture_health_button = QPushButton("Capture Health")
        self.capture_health_button.clicked.connect(self.open_capture_health_report)
        self.capture_health_button.setToolTip("Daily workflow: inspect capture/provider/CSV/outcome health. Read-only diagnostic.")

        self.regime_combo = QComboBox()
        self.regime_combo.addItems([item.value for item in MarketRegime])
        self.regime_combo.currentTextChanged.connect(self._manual_regime_changed)

        self.regime_button = QPushButton("Refresh Regime")
        self.regime_button.clicked.connect(self.refresh_market_regime)
        self.regime_button.setToolTip("Refresh market regime context. This does not change scores or raw captures.")

        self.capture_date_combo = QComboBox()
        self.capture_date_combo.currentTextChanged.connect(self._capture_date_changed)

        self.capture_session_combo = QComboBox()
        self.open_capture_button = QPushButton("Open Historical Snapshot")
        self.open_capture_button.clicked.connect(self.open_selected_capture)
        self.open_capture_button.setToolTip("Historical/replay workflow: open a saved capture as read-only historical data.")

        self.current_button = QPushButton("Current Dashboard")
        self.current_button.clicked.connect(self.return_to_current_dashboard)
        self.current_button.setToolTip("Return to fresh/current dashboard state for live review.")

        self.morning_review_button = QPushButton("Morning Review")
        self.morning_review_button.clicked.connect(self.open_morning_review_workspace)
        self.morning_review_button.setToolTip("Daily workflow: review candidates, mark status, and complete entry plans.")

        self.daily_checklist_button = QPushButton("Daily Checklist")
        self.daily_checklist_button.clicked.connect(self.open_daily_workflow_checklist)
        self.daily_checklist_button.setToolTip("Daily workflow: check captures, reviews, watchlist plans, outcomes, and readiness.")

        self.study_button = QPushButton("Research Lab")
        self.study_button.clicked.connect(self.open_study_engine)
        self.study_button.setToolTip("Research-only workflow. Uses stored data and post-capture outcomes; no trade recommendations.")

        self.clock_label = QLabel(format_central())
        self.criteria_label = QLabel()
        self.criteria_label.setObjectName("criteriaLabel")
        self.operator_guidance_label = QLabel("What should I do next? Load a capture or run the scanner.")
        self.operator_guidance_label.setObjectName("criteriaLabel")
        self.operator_guidance_label.setWordWrap(True)
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
        layout.addWidget(self.clock_label, 1, 0, 1, 2)
        layout.addWidget(QLabel("Evening review: 7:00 PM - 8:00 PM CT"), 1, 2, 1, 3)
        layout.addWidget(QLabel("Morning review: 7:00 AM - 8:00 AM CT"), 1, 5, 1, 4)
        layout.addWidget(QLabel("Market"), 2, 0)
        layout.addWidget(self.regime_combo, 2, 1)
        layout.addWidget(self.regime_button, 2, 2)
        layout.addWidget(self.daily_checklist_button, 2, 3)
        layout.addWidget(self.brand_logo, 0, 9, 3, 1)
        layout.addWidget(self.criteria_label, 3, 0, 1, 10)
        layout.addWidget(QLabel("What should I do next?"), 4, 0, 1, 2)
        layout.addWidget(self.operator_guidance_label, 4, 2, 1, 8)
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
        self.mark_interested_button.setToolTip("Mark checked rows Interested. If none are checked, marks the selected row.")
        self.mark_rejected_button = QPushButton("Mark Rejected")
        self.mark_rejected_button.clicked.connect(self.mark_rejected_candidates)
        self.mark_rejected_button.setToolTip("Mark checked rows Rejected. If none are checked, marks the selected row.")
        self.add_interested_button = QPushButton("Move Interested to Watchlist")
        self.add_interested_button.clicked.connect(self.add_interested_to_watchlist)
        self.add_interested_button.setToolTip("Promote all Interested candidates to Watchlist status.")
        self.clear_button = QPushButton("Clear Checkmarks")
        self.clear_button.clicked.connect(self.clear_row_marks)
        self.clear_button.setToolTip("Clear table checkmarks only. Review decisions are not changed.")
        self.timeline_button = QPushButton("Timeline / Replay")
        self.timeline_button.clicked.connect(self.view_candidate_timeline)
        self.timeline_button.setToolTip("Open read-only point-in-time history for the selected candidate.")
        review_layout.addWidget(self.mark_interested_button)
        review_layout.addWidget(self.mark_rejected_button)
        review_layout.addWidget(self.add_interested_button)
        review_layout.addWidget(self.clear_button)
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
        self.entry_thesis = QPlainTextEdit()
        self.entry_thesis.setMaximumHeight(64)
        self.entry_invalidation = QPlainTextEdit()
        self.entry_invalidation.setMaximumHeight(64)
        self.entry_max_loss = QLineEdit()
        self.entry_position_size = QLineEdit()
        self.entry_hold_time = QLineEdit()
        self.entry_notes = QPlainTextEdit()
        self.entry_notes.setMaximumHeight(64)
        self.plan_complete_checkbox = QCheckBox("Plan Complete")
        self.plan_warnings_label = QLabel("Plan warnings: missing trigger | missing stop | missing invalidation | missing max loss")
        self.plan_warnings_label.setWordWrap(True)
        self.risk_note = QLabel("Suggested discipline: define entry, invalidation, and max loss before placing any trade.")
        self.risk_note.setWordWrap(True)
        for widget in [
            self.entry_trigger,
            self.stop_level,
            self.entry_max_loss,
            self.entry_position_size,
            self.entry_hold_time,
        ]:
            widget.editingFinished.connect(self._entry_plan_changed)
        for widget in [self.entry_thesis, self.entry_invalidation, self.entry_notes]:
            widget.textChanged.connect(self._entry_plan_changed)
        self.plan_complete_checkbox.stateChanged.connect(self._entry_plan_changed)
        entry_layout.addWidget(QLabel("Trigger"), 0, 0)
        entry_layout.addWidget(self.entry_trigger, 0, 1)
        entry_layout.addWidget(QLabel("Stop"), 1, 0)
        entry_layout.addWidget(self.stop_level, 1, 1)
        entry_layout.addWidget(QLabel("Thesis"), 2, 0)
        entry_layout.addWidget(self.entry_thesis, 2, 1)
        entry_layout.addWidget(QLabel("Invalidation"), 3, 0)
        entry_layout.addWidget(self.entry_invalidation, 3, 1)
        entry_layout.addWidget(QLabel("Max Loss"), 4, 0)
        entry_layout.addWidget(self.entry_max_loss, 4, 1)
        entry_layout.addWidget(QLabel("Position Size"), 5, 0)
        entry_layout.addWidget(self.entry_position_size, 5, 1)
        entry_layout.addWidget(QLabel("Hold Time"), 6, 0)
        entry_layout.addWidget(self.entry_hold_time, 6, 1)
        entry_layout.addWidget(QLabel("Plan Notes"), 7, 0)
        entry_layout.addWidget(self.entry_notes, 7, 1)
        entry_layout.addWidget(self.plan_complete_checkbox, 8, 1)
        entry_layout.addWidget(self.plan_warnings_label, 9, 0, 1, 2)
        entry_layout.addWidget(self.risk_note, 10, 0, 1, 2)
        layout.addWidget(entry_box)
        return panel

    def _apply_config_to_controls(self) -> None:
        self.mode_combo.setCurrentText(self.config.mode.value)
        self.provider_combo.setCurrentText(self.config.provider)
        if self.display_scanner_label:
            self.scanner_combo.setCurrentText(scanner_display_name(self.display_scanner_label))
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
        criteria = self._selected_scanner_criteria(value)
        description = SCANNER_DISPLAY_DESCRIPTIONS.get(criteria.name, scanner_display_name(criteria.name))
        self.scanner_combo.setToolTip(description)
        self.criteria_label.setText(
            f"{description} | "
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
            self.display_scanner_label = self._selected_scanner_key()
            self.display_mode_label = self.config.mode.value
            self.display_calendar_status = ""
            self.display_next_market_session_date = ""
            self.display_quarantined = False
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
        criteria = self._selected_scanner_criteria()
        provider = provider_from_name(self.provider_combo.currentText())
        self._update_status(f"Running {scanner_display_name(criteria.name)} with {provider.name} provider...")
        candidates = provider.scan(criteria)
        for candidate in candidates:
            if not candidate.news:
                candidate.news = provider.fetch_news(candidate.ticker, as_of=scan_time)
        return score_candidates(candidates, regime=self.market_regime.regime, now=scan_time), scan_time

    def _selected_scanner_key(self, value: str | None = None) -> str:
        selected = value if value is not None else self.scanner_combo.currentText()
        return scanner_internal_name(selected)

    def _selected_scanner_criteria(self, value: str | None = None):
        return SCANNER_PRESETS[self._selected_scanner_key(value)]

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
        self._refresh_watchlist_center()

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
        self._load_entry_plan_for_candidate(candidate)
        self.news_text.setHtml(format_news_html(candidate, now=self.display_capture_time))
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
        self._clear_entry_plan_fields()

    def _notes_changed(self) -> None:
        candidate = self._selected_candidate()
        if candidate is not None:
            candidate.user_notes = self.notes_edit.toPlainText()

    def _load_entry_plan_for_candidate(self, candidate: Candidate) -> None:
        identity = self._candidate_identity(candidate)
        plan = self.entry_plans.get(identity.key)
        self._loading_entry_plan = True
        self.entry_trigger.setText(plan.trigger if plan else "")
        self.stop_level.setText(plan.stop if plan else "")
        self.entry_thesis.setPlainText(plan.thesis if plan else "")
        self.entry_invalidation.setPlainText(plan.invalidation if plan else "")
        self.entry_max_loss.setText(plan.max_loss if plan else "")
        self.entry_position_size.setText(plan.position_size if plan else "")
        self.entry_hold_time.setText(plan.planned_hold_time if plan else "")
        self.entry_notes.setPlainText(plan.notes if plan else "")
        self.plan_complete_checkbox.setChecked(bool(plan and plan.plan_complete))
        self._loading_entry_plan = False
        self._update_entry_plan_warnings(plan)

    def _clear_entry_plan_fields(self) -> None:
        self._loading_entry_plan = True
        self.entry_trigger.clear()
        self.stop_level.clear()
        self.entry_thesis.clear()
        self.entry_invalidation.clear()
        self.entry_max_loss.clear()
        self.entry_position_size.clear()
        self.entry_hold_time.clear()
        self.entry_notes.clear()
        self.plan_complete_checkbox.setChecked(False)
        self._loading_entry_plan = False
        self._update_entry_plan_warnings(None)

    def _entry_plan_changed(self) -> None:
        if self._loading_entry_plan:
            return
        candidate = self._selected_candidate()
        if candidate is None:
            return
        if self._is_read_only_view():
            self._show_action_blocked((self.current_operator_context or self._operator_review_context()).block_reason or "This view is read-only.")
            return
        plan = self._save_entry_plan_for_candidate(candidate)
        self._update_entry_plan_warnings(plan)

    def _save_entry_plan_for_candidate(self, candidate: Candidate) -> EntryPlan:
        return self._upsert_entry_plan_for_candidate(
            candidate,
            trigger=self.entry_trigger.text(),
            stop=self.stop_level.text(),
            thesis=self.entry_thesis.toPlainText(),
            invalidation=self.entry_invalidation.toPlainText(),
            max_loss=self.entry_max_loss.text(),
            position_size=self.entry_position_size.text(),
            planned_hold_time=self.entry_hold_time.text(),
            notes=self.entry_notes.toPlainText(),
            plan_complete=self.plan_complete_checkbox.isChecked(),
        )

    def _upsert_entry_plan_for_candidate(
        self,
        candidate: Candidate,
        *,
        trigger: str = "",
        stop: str = "",
        thesis: str = "",
        invalidation: str = "",
        max_loss: str = "",
        position_size: str = "",
        planned_hold_time: str = "",
        notes: str = "",
        plan_complete: bool = False,
    ) -> EntryPlan:
        identity = self._candidate_identity(candidate)
        plan = upsert_entry_plan(
            self.entry_plans,
            identity,
            trigger=trigger,
            stop=stop,
            thesis=thesis,
            invalidation=invalidation,
            max_loss=max_loss,
            position_size=position_size,
            planned_hold_time=planned_hold_time,
            notes=notes,
            plan_complete=plan_complete,
        )
        self.entry_plans[identity.key] = plan
        if hasattr(self, "plan_complete_checkbox") and self.plan_complete_checkbox.isChecked() != plan.plan_complete:
            self._loading_entry_plan = True
            self.plan_complete_checkbox.setChecked(plan.plan_complete)
            self._loading_entry_plan = False
        return plan

    def _update_entry_plan_warnings(self, plan: EntryPlan | None) -> None:
        warnings = entry_plan_warnings(plan) if plan else ["missing trigger", "missing stop", "missing invalidation", "missing max loss"]
        if warnings:
            self.plan_warnings_label.setText("Plan warnings: " + " | ".join(warnings))
            self.plan_warnings_label.setStyleSheet("color: #fcd34d; font-weight: 700;")
        else:
            self.plan_warnings_label.setText("Plan complete.")
            self.plan_warnings_label.setStyleSheet("color: #86efac; font-weight: 700;")

    def save_selected_candidates(self) -> None:
        self.mark_interested_candidates()

    def mark_interested_candidates(self) -> None:
        self._mark_review_status_for_targets(ReviewStatus.INTERESTED, "Marked {count} candidate(s) interested.")

    def mark_rejected_candidates(self) -> None:
        self._mark_review_status_for_targets(ReviewStatus.REJECTED, "Marked {count} candidate(s) rejected.")

    def add_interested_to_watchlist(self) -> None:
        if self._is_read_only_view():
            self._show_action_blocked((self.current_operator_context or self._operator_review_context()).block_reason or "This view is read-only.")
            return
        interested = [
            candidate
            for candidate in self.candidates
            if self._candidate_review_status(candidate) == ReviewStatus.INTERESTED
        ]
        if not interested:
            watchlist_count = len(self._watchlist_candidates())
            if watchlist_count:
                self._show_action_blocked(
                    f"No interested candidates remain. {watchlist_count} candidate(s) are already on the Watchlist."
                )
            else:
                self._show_action_blocked("No interested candidates found. Mark candidates as Interested first.")
            return
        for candidate in interested:
            self._set_candidate_review_status(candidate, ReviewStatus.WATCHLIST)
        self._refresh_row_states(clear_checks=True)
        self._refresh_watchlist_center()
        self._update_status(f"Added {len(interested)} interested candidate(s) to watchlist status.")

    def _mark_review_status_for_targets(self, status: ReviewStatus, message_template: str) -> None:
        if self._is_read_only_view():
            self._show_action_blocked((self.current_operator_context or self._operator_review_context()).block_reason or "This view is read-only.")
            return
        marked = self._marked_candidates()
        if not marked:
            candidate = self._selected_candidate()
            if candidate is None:
                self._show_action_blocked("No candidate selected. Select a candidate first.")
                return
            marked = [candidate]
        for candidate in marked:
            self._set_candidate_review_status(candidate, status)
        self._refresh_row_states(clear_checks=True)
        self._refresh_watchlist_center()
        self._update_status(message_template.format(count=len(marked)))

    def _set_candidate_review_status(self, candidate: Candidate, status: ReviewStatus) -> None:
        if candidate.ticker == self.selected_ticker:
            candidate.user_notes = self.notes_edit.toPlainText()
        identity = self._candidate_identity(candidate)
        context = self.current_operator_context or self._operator_review_context()
        decision = upsert_review_decision(
            self.review_decisions,
            identity,
            status,
            note=candidate.user_notes,
            delayed_review=context.acknowledgement_required,
            review_delay_minutes=context.review_delay_minutes,
            review_context_state=context.state.value,
        )
        self.review_decisions[identity.key] = decision
        self.reviewed_tickers.add(candidate.ticker)
        if status == ReviewStatus.WATCHLIST:
            candidate.saved_at = decision.decision_timestamp
            self.saved_candidates[candidate.ticker] = candidate
            if candidate.ticker == self.selected_ticker:
                self._save_entry_plan_for_candidate(candidate)
            else:
                identity = self._candidate_identity(candidate)
                if identity.key not in self.entry_plans:
                    self.entry_plans[identity.key] = upsert_entry_plan(self.entry_plans, identity)
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
            self._show_action_blocked((self.current_operator_context or self._operator_review_context()).block_reason or "This view is read-only.")
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Unchecked)
        self._update_status("Cleared row marks.")

    def save_tomorrow_watchlist(self) -> None:
        if not self._can_generate_watchlist():
            self._show_action_blocked((self.current_operator_context or self._operator_review_context()).block_reason or "This view cannot generate a watchlist.")
            return
        watchlist_candidates = self._watchlist_candidates()
        if not watchlist_candidates:
            self._show_action_blocked("No watchlist candidates found. Mark candidates as Watchlist first.")
            return
        if (self.current_operator_context or self._operator_review_context()).acknowledgement_required:
            if not self._confirm_aging_review_watchlist():
                self._update_status("Watchlist report generation cancelled.")
                return
        session_date = next_market_session()
        entry_plans = self._entry_plans_for_candidates(watchlist_candidates)
        path = save_watchlist(watchlist_candidates, session_date)
        report = save_watchlist_report(watchlist_candidates, session_date, entry_plans=entry_plans)
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
            self._show_text_dialog("Open Latest Watchlist", report)
            self._update_status("Opened latest saved watchlist/report.")
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
            self._show_text_dialog("Open Latest Watchlist", fallback)
            self._update_status("Opened latest saved watchlist.")
            return

        self._show_text_dialog("Open Latest Watchlist", "No saved watchlist or report found yet.")
        self._update_status("No saved watchlist/report found.")

    def view_candidate_timeline(self) -> None:
        candidate = None
        if hasattr(self, "replay_snapshot_table") and self.page_stack.currentIndex() == 4:
            candidate = self._selected_replay_snapshot_candidate()
        if candidate is None:
            candidate = self._selected_candidate()
        if candidate is None:
            self._show_action_blocked("No candidate selected. Select a dashboard or Replay snapshot candidate first.")
            return
        self._show_timeline_dialog(candidate.ticker)

    def open_morning_review_workspace(self) -> None:
        if not self.candidates:
            self._show_action_blocked("No candidates loaded. Run Scanner or open the latest review snapshot first.")
            return
        style = self.current_view_style or get_data_view_style(
            self.data_view_state,
            captured_at=self.display_capture_time,
            session_label=self.display_session_label,
        )
        context = self.current_operator_context or self._operator_review_context()
        read_only = not context.can_review
        dialog = QDialog(self)
        dialog.setWindowTitle("Morning Review Workspace")
        dialog.resize(1380, 820)
        layout = QVBoxLayout(dialog)

        banner = QLabel(
            "MORNING REVIEW WORKSPACE\n"
            f"{style.banner_text}\n"
            "Workflow only. No broker connection, order placement, Opportunity Score, optimizer, or scoring changes."
        )
        banner.setObjectName(style.object_name)
        banner.setWordWrap(True)
        layout.addWidget(banner)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        table = QTableWidget(len(self.candidates), 8)
        table.setHorizontalHeaderLabels(
            ["Ticker", "Review", "Watchlist", "Score", "Catalyst", "Freshness", "Warnings", "Plan"]
        )
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setStyleSheet(style.header_stylesheet)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.morning_review_table = table

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        decision_card = QTextBrowser()
        decision_card.setOpenExternalLinks(True)
        decision_card.setMinimumHeight(185)
        self.morning_decision_card = decision_card
        right_layout.addWidget(decision_card)

        action_row = QWidget()
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        interested_button = QPushButton("Mark Interested")
        rejected_button = QPushButton("Mark Rejected")
        watchlist_button = QPushButton("Add to Watchlist")
        why_button = QPushButton("Open Why Score")
        timeline_button = QPushButton("Open Timeline/Replay")
        interested_button.setToolTip("Mark the selected Morning Review candidate Interested.")
        rejected_button.setToolTip("Mark the selected Morning Review candidate Rejected.")
        watchlist_button.setToolTip("Move the selected Morning Review candidate directly to Watchlist.")
        why_button.setToolTip("Open the stored score explanation for the selected candidate.")
        timeline_button.setToolTip("Open read-only Timeline / Replay for the selected candidate.")
        for button in [interested_button, rejected_button, watchlist_button]:
            button.setEnabled(not read_only)
        action_layout.addWidget(interested_button)
        action_layout.addWidget(rejected_button)
        action_layout.addWidget(watchlist_button)
        action_layout.addWidget(why_button)
        action_layout.addWidget(timeline_button)
        right_layout.addWidget(action_row)

        entry_box = QGroupBox("Entry Plan")
        entry_layout = QGridLayout(entry_box)
        trigger_edit = QLineEdit()
        stop_edit = QLineEdit()
        thesis_edit = QPlainTextEdit()
        thesis_edit.setMaximumHeight(66)
        invalidation_edit = QPlainTextEdit()
        invalidation_edit.setMaximumHeight(66)
        max_loss_edit = QLineEdit()
        position_size_edit = QLineEdit()
        hold_time_edit = QLineEdit()
        notes_edit = QPlainTextEdit()
        notes_edit.setMaximumHeight(66)
        plan_complete = QCheckBox("Plan Complete")
        plan_warning = QLabel()
        plan_warning.setWordWrap(True)
        for widget in [
            trigger_edit,
            stop_edit,
            thesis_edit,
            invalidation_edit,
            max_loss_edit,
            position_size_edit,
            hold_time_edit,
            notes_edit,
        ]:
            widget.setReadOnly(read_only)
        plan_complete.setEnabled(not read_only)
        self.morning_entry_trigger = trigger_edit
        self.morning_entry_stop = stop_edit
        self.morning_entry_thesis = thesis_edit
        self.morning_entry_invalidation = invalidation_edit
        self.morning_entry_max_loss = max_loss_edit
        self.morning_entry_position_size = position_size_edit
        self.morning_entry_hold_time = hold_time_edit
        self.morning_entry_notes = notes_edit
        self.morning_plan_complete = plan_complete
        self.morning_plan_warning = plan_warning

        entry_layout.addWidget(QLabel("Trigger"), 0, 0)
        entry_layout.addWidget(trigger_edit, 0, 1)
        entry_layout.addWidget(QLabel("Stop"), 1, 0)
        entry_layout.addWidget(stop_edit, 1, 1)
        entry_layout.addWidget(QLabel("Thesis"), 2, 0)
        entry_layout.addWidget(thesis_edit, 2, 1)
        entry_layout.addWidget(QLabel("Invalidation"), 3, 0)
        entry_layout.addWidget(invalidation_edit, 3, 1)
        entry_layout.addWidget(QLabel("Max Loss"), 4, 0)
        entry_layout.addWidget(max_loss_edit, 4, 1)
        entry_layout.addWidget(QLabel("Position Size"), 5, 0)
        entry_layout.addWidget(position_size_edit, 5, 1)
        entry_layout.addWidget(QLabel("Hold Time"), 6, 0)
        entry_layout.addWidget(hold_time_edit, 6, 1)
        entry_layout.addWidget(QLabel("Plan Notes"), 7, 0)
        entry_layout.addWidget(notes_edit, 7, 1)
        entry_layout.addWidget(plan_complete, 8, 1)
        entry_layout.addWidget(plan_warning, 9, 0, 1, 2)
        save_plan_button = QPushButton("Create/Edit Entry Plan")
        save_plan_button.setEnabled(not read_only)
        entry_layout.addWidget(save_plan_button, 10, 1)
        right_layout.addWidget(entry_box, 1)

        selected_candidate: Candidate | None = None
        loading_plan = False

        def candidate_for_selected_row() -> Candidate | None:
            rows = table.selectionModel().selectedRows()
            if not rows:
                return None
            row_index = rows[0].row()
            if row_index < 0 or row_index >= len(self.candidates):
                return None
            return self.candidates[row_index]

        def load_plan(candidate: Candidate) -> None:
            nonlocal loading_plan
            plan = self.entry_plans.get(self._candidate_identity(candidate).key)
            loading_plan = True
            trigger_edit.setText(plan.trigger if plan else "")
            stop_edit.setText(plan.stop if plan else "")
            thesis_edit.setPlainText(plan.thesis if plan else "")
            invalidation_edit.setPlainText(plan.invalidation if plan else "")
            max_loss_edit.setText(plan.max_loss if plan else "")
            position_size_edit.setText(plan.position_size if plan else "")
            hold_time_edit.setText(plan.planned_hold_time if plan else "")
            notes_edit.setPlainText(plan.notes if plan else "")
            plan_complete.setChecked(bool(plan and plan.plan_complete))
            loading_plan = False
            update_plan_warning(plan)

        def update_plan_warning(plan: EntryPlan | None) -> None:
            warnings = entry_plan_warnings(plan) if plan else ["missing trigger", "missing stop", "missing invalidation", "missing max loss"]
            if warnings:
                plan_warning.setText("Plan warnings: " + " | ".join(warnings))
                plan_warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
            else:
                plan_warning.setText("Plan complete.")
                plan_warning.setStyleSheet("color: #86efac; font-weight: 700;")

        def save_plan() -> None:
            nonlocal selected_candidate, loading_plan
            if read_only:
                self._show_action_blocked(context.block_reason or "This view is read-only.")
                return
            if selected_candidate is None:
                self._show_action_blocked("No candidate selected. Select a candidate before saving an entry plan.")
                return
            plan = self._upsert_entry_plan_for_candidate(
                selected_candidate,
                trigger=trigger_edit.text(),
                stop=stop_edit.text(),
                thesis=thesis_edit.toPlainText(),
                invalidation=invalidation_edit.toPlainText(),
                max_loss=max_loss_edit.text(),
                position_size=position_size_edit.text(),
                planned_hold_time=hold_time_edit.text(),
                notes=notes_edit.toPlainText(),
                plan_complete=plan_complete.isChecked(),
            )
            if plan_complete.isChecked() != plan.plan_complete:
                loading_plan = True
                plan_complete.setChecked(plan.plan_complete)
                loading_plan = False
            update_plan_warning(plan)
            refresh_table()
            update_decision_card(selected_candidate)
            self._update_status(f"Saved entry plan for {selected_candidate.ticker}.")

        def refresh_table() -> None:
            for row, candidate in enumerate(self.candidates):
                if candidate.news and candidate.news_stack.article_count == 0:
                    apply_candidate_news_stack(candidate, now=self.display_capture_time)
                status = self._candidate_review_status(candidate)
                context = morning_review_context(candidate)
                plan = self.entry_plans.get(self._candidate_identity(candidate).key)
                plan_warnings = entry_plan_warnings(plan) if plan else ["missing trigger", "missing stop", "missing invalidation", "missing max loss"]
                values = [
                    candidate.ticker,
                    status.value.title(),
                    "Yes" if status == ReviewStatus.WATCHLIST else "No",
                    str(candidate.score),
                    context["catalyst_cluster"],
                    context["freshness"],
                    " | ".join(context["warnings"]) or "none",
                    "Complete" if plan and plan.plan_complete else "Incomplete",
                ]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column == 1:
                        item.setBackground(review_status_color(status))
                    if column == 3:
                        item.setBackground(score_color(candidate.score))
                    if column in {6, 7} and (context["warnings"] or plan_warnings):
                        item.setBackground(QBrush(QColor("#735f24")))
                    table.setItem(row, column, item)
            table.resizeColumnsToContents()

        def update_decision_card(candidate: Candidate | None) -> None:
            nonlocal selected_candidate
            selected_candidate = candidate
            if candidate is None:
                decision_card.setHtml("<p>No candidate selected.</p>")
                return
            context = morning_review_context(candidate)
            status = self._candidate_review_status(candidate)
            plan = self.entry_plans.get(self._candidate_identity(candidate).key)
            plan_warnings = entry_plan_warnings(plan) if plan else ["missing trigger", "missing stop", "missing invalidation", "missing max loss"]
            warnings = list(context["warnings"]) + plan_warnings
            decision_card.setHtml(
                "<h2>{ticker} <span style='font-size:14px;'>Score {score}</span></h2>"
                "<p><b>Catalyst:</b> {summary}</p>"
                "<p><b>Cluster:</b> {cluster} | <b>Confidence:</b> {confidence} | <b>Purity:</b> {purity}</p>"
                "<p><b>Freshness:</b> {freshness} | <b>Review:</b> {status} | <b>Plan:</b> {plan_status}</p>"
                "<p><b>Key warnings:</b> {warnings}</p>"
                .format(
                    ticker=escape(candidate.ticker),
                    score=candidate.score,
                    summary=escape(context["catalyst_summary"]),
                    cluster=escape(context["catalyst_cluster"]),
                    confidence=escape(context["catalyst_confidence"]),
                    purity=escape(context["cluster_purity"]),
                    freshness=escape(context["freshness"]),
                    status=escape(status.value),
                    plan_status=escape("complete" if plan and plan.plan_complete else "incomplete"),
                    warnings=escape(" | ".join(warnings) if warnings else "none"),
                )
            )
            load_plan(candidate)

        def selection_changed() -> None:
            update_decision_card(candidate_for_selected_row())

        def mark_status(status: ReviewStatus) -> None:
            if read_only:
                self._show_action_blocked(context.block_reason or "This view is read-only.")
                return
            candidate = selected_candidate
            if candidate is None:
                self._show_action_blocked("No candidate selected. Select a candidate first.")
                return
            previous_selected_ticker = self.selected_ticker
            identity = self._candidate_identity(candidate)
            try:
                if status == ReviewStatus.WATCHLIST and identity.key in self.entry_plans:
                    self.selected_ticker = ""
                self._set_candidate_review_status(candidate, status)
            finally:
                self.selected_ticker = previous_selected_ticker
            self._refresh_row_states()
            self._refresh_watchlist_center()
            refresh_table()
            update_decision_card(candidate)
            if status == ReviewStatus.WATCHLIST:
                self._update_status(f"{candidate.ticker} moved to Watchlist from Morning Review.")
            else:
                self._update_status(f"{candidate.ticker} marked {status.value.title()} from Morning Review.")

        def open_why() -> None:
            if selected_candidate is None:
                self._show_action_blocked("No candidate selected. Select a candidate first.")
                return
            previous = self.selected_ticker
            self.selected_ticker = selected_candidate.ticker
            self.show_score_breakdown()
            self.selected_ticker = previous

        def open_timeline() -> None:
            if selected_candidate is None:
                self._show_action_blocked("No candidate selected. Select a candidate first.")
                return
            self._show_timeline_dialog(selected_candidate.ticker)

        table.itemSelectionChanged.connect(selection_changed)
        interested_button.clicked.connect(lambda: mark_status(ReviewStatus.INTERESTED))
        rejected_button.clicked.connect(lambda: mark_status(ReviewStatus.REJECTED))
        watchlist_button.clicked.connect(lambda: mark_status(ReviewStatus.WATCHLIST))
        save_plan_button.clicked.connect(save_plan)
        why_button.clicked.connect(open_why)
        timeline_button.clicked.connect(open_timeline)

        refresh_table()
        if self.candidates:
            table.selectRow(0)
            update_decision_card(self.candidates[0])

        splitter.addWidget(table)
        splitter.addWidget(right_panel)
        splitter.setSizes([760, 620])
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.setStyleSheet(STYLESHEET)
        dialog.exec()

    def _build_daily_workflow_report(self) -> DailyWorkflowReport:
        identities = {candidate.ticker: self._candidate_identity(candidate) for candidate in self.candidates}
        review_statuses = {
            identity.key: self._candidate_review_status(candidate)
            for candidate in self.candidates
            for identity in [identities[candidate.ticker]]
        }
        return build_daily_workflow_report(
            candidates=self.candidates,
            identities=identities,
            review_statuses=review_statuses,
            entry_plans=self.entry_plans,
            capture_health=build_capture_health_snapshot(),
            outcome_maturity=build_outcome_maturity_report(),
        )

    def open_daily_workflow_checklist(self) -> None:
        report = self._build_daily_workflow_report()
        style = self.current_view_style or get_data_view_style(
            self.data_view_state,
            captured_at=self.display_capture_time,
            session_label=self.display_session_label,
        )
        context = self.current_operator_context or self._operator_review_context()
        read_only = not context.can_review
        dialog = QDialog(self)
        dialog.setWindowTitle("Guided Daily Workflow")
        dialog.resize(1160, 820)
        layout = QVBoxLayout(dialog)

        banner = QLabel(
            "GUIDED DAILY WORKFLOW\n"
            f"{style.banner_text}\n"
            "Workflow discipline only. This does not evaluate trade quality, change scores, place orders, or optimize weights."
        )
        banner.setObjectName(style.object_name)
        banner.setWordWrap(True)
        layout.addWidget(banner)

        score_label = QLabel(
            f"Today's Workflow Score: {report.workflow_score}% | Workflow lights guide operator flow, not trade readiness."
        )
        score_label.setObjectName("tickerLabel")
        score_label.setWordWrap(True)
        self.daily_workflow_score_label = score_label
        layout.addWidget(score_label)

        morning_button = QPushButton("Open Morning Review")
        watchlist_button = QPushButton("Generate Watchlist Report")
        capture_button = QPushButton("Open Capture Health")
        readiness_button = QPushButton("Open Readiness Gate")
        morning_button.setEnabled(not read_only and bool(self.candidates))
        watchlist_button.setEnabled(context.can_generate_watchlist)
        morning_button.clicked.connect(lambda: self._run_daily_workflow_quick_action(dialog, self.open_morning_review_workspace))
        watchlist_button.clicked.connect(lambda: self._run_daily_workflow_quick_action(dialog, self.save_tomorrow_watchlist))
        capture_button.clicked.connect(lambda: self._run_daily_workflow_quick_action(dialog, self.open_capture_health_report))
        readiness_button.clicked.connect(lambda: self._run_daily_workflow_quick_action(dialog, self.open_readiness_gate))

        action_buttons = {
            "capture": capture_button,
            "review": morning_button,
            "report": watchlist_button,
            "readiness": readiness_button,
        }
        guided_panel, trust_label, next_action_label, step_status_labels = build_daily_workflow_guided_panel(
            report,
            style,
            context,
            action_buttons,
        )
        self.daily_workflow_trust_label = trust_label
        self.daily_workflow_next_action_label = next_action_label
        self.daily_workflow_step_status_labels = step_status_labels
        layout.addWidget(guided_panel)

        tabs = QTabWidget()
        summary_table = build_daily_workflow_summary_table(report, style)
        self.daily_workflow_summary_table = summary_table
        tabs.addTab(summary_table, "Audit Details")
        tabs.addTab(build_daily_workflow_warning_table(report, style), "Warning Detail")
        layout.addWidget(tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.setStyleSheet(STYLESHEET)
        dialog.exec()

    def _run_daily_workflow_quick_action(self, dialog: QDialog, action: Callable[[], None]) -> None:
        dialog.accept()
        action()

    def open_capture_health_report(self) -> None:
        health = build_capture_health_snapshot()
        lines = [
            format_capture_success("Last successful morning", health.last_morning_capture),
            format_capture_success("Last successful evening", health.last_evening_capture),
            format_capture_success("Last successful preopen", health.last_preopen_capture),
            format_capture_failure(health.last_failed_capture),
            "Next scheduled runs: "
            f"Morning {format_central(health.next_morning_run)} | "
            f"Evening {format_central(health.next_evening_run)} | "
            f"Preopen {format_central(health.next_preopen_run)}",
            format_csv_status("CSV append", health.csv_append_status),
            format_csv_status("Outcome update", health.outcome_update_status),
        ]
        self._show_text_dialog("Capture Health", "\n".join(lines))

    def open_readiness_gate(self) -> None:
        def show_readiness(report: object, elapsed_seconds: float) -> None:
            if not isinstance(report, OutcomeMaturityReport):
                self._show_action_blocked("Readiness Gate returned an unexpected report type.", "Readiness Gate Error")
                return
            self._show_readiness_gate_dialog(report, elapsed_seconds)

        self._run_report_loader(
            title="Readiness Gate",
            loading_message="Loading Readiness Gate without blocking the dashboard...",
            loader=build_outcome_maturity_report,
            on_success=show_readiness,
            error_title="Readiness Gate Error",
        )

    def _show_readiness_gate_dialog(self, report: OutcomeMaturityReport, elapsed_seconds: float) -> None:
        style = get_data_view_style(DataViewState.STUDY, captured_at=None, study_run_id="readiness-gate")
        dialog = QDialog(self)
        dialog.setWindowTitle("Readiness Gate")
        dialog.resize(980, 620)
        layout = QVBoxLayout(dialog)
        load_label = QLabel(f"Loaded in {elapsed_seconds:.2f} seconds. Research/readiness data is read-only.")
        load_label.setObjectName("criteriaLabel")
        layout.addWidget(load_label)
        layout.addWidget(build_outcome_maturity_panel(report, style), 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.setStyleSheet(STYLESHEET)
        self._update_status(f"Readiness Gate opened in {elapsed_seconds:.2f} seconds.")
        dialog.exec()

    def _show_timeline_dialog(self, ticker: str) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Candidate Story - {ticker}")
        dialog.resize(1320, 820)
        layout = QVBoxLayout(dialog)

        banner = QLabel(
            "Candidate Story - graph-first capture trail. Audit data is preserved separately. Outcomes and review notes are later-derived annotations."
        )
        banner.setObjectName("detailStateLabel")
        banner.setWordWrap(True)
        layout.addWidget(banner)

        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        sort_combo = QComboBox()
        sort_combo.addItems(["Oldest First", "Newest First"])
        mode_combo = QComboBox()
        mode_combo.addItems(["Trail", "Intraday", "5D", "Audit"])
        mode_combo.setToolTip("Trail is the graph-first capture story. Audit shows the dense replay identity table.")
        show_quarantined = QCheckBox("Show quarantined captures")
        show_non_trading_day = QCheckBox("Show non-trading-day captures")
        replay_button = QPushButton("Replay Capture")
        controls_layout.addWidget(QLabel("Sort"))
        controls_layout.addWidget(sort_combo)
        controls_layout.addWidget(QLabel("Mode"))
        controls_layout.addWidget(mode_combo)
        controls_layout.addWidget(show_quarantined)
        controls_layout.addWidget(show_non_trading_day)
        controls_layout.addStretch(1)
        controls_layout.addWidget(replay_button)
        layout.addWidget(controls)

        story_header = QTextBrowser()
        story_header.setMaximumHeight(178)
        layout.addWidget(story_header)

        chart_holder = QWidget()
        chart_layout = QVBoxLayout(chart_holder)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(0)
        chart_widget: list[QWidget | None] = [None]
        layout.addWidget(chart_holder, 2)

        mode_placeholder = story_placeholder("")
        mode_placeholder.hide()
        layout.addWidget(mode_placeholder, 1)

        story_table = QTableWidget(0, 9)
        story_table.setHorizontalHeaderLabels(
            ["Capture", "Price", "Move", "Score", "Score Δ", "Rel Vol", "Volume", "Note", "Later Annotation"]
        )
        story_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        story_table.horizontalHeader().setStretchLastSection(True)
        story_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        story_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        story_table.setMinimumHeight(190)
        layout.addWidget(story_table, 1)

        audit_box = QGroupBox("Advanced Capture Audit")
        audit_layout = QVBoxLayout(audit_box)
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
        audit_layout.addWidget(table, 1)
        detail_browser = QTextBrowser()
        detail_browser.setMaximumHeight(190)
        audit_layout.addWidget(detail_browser)
        layout.addWidget(audit_box, 2)

        timeline_rows: list[TimelineRow] = []
        story_summary: CandidateStorySummary = build_candidate_story_summary([])

        def replace_chart(widget: QWidget) -> None:
            if chart_widget[0] is not None:
                old_widget = chart_widget[0]
                chart_layout.removeWidget(old_widget)
                old_widget.deleteLater()
            chart_widget[0] = widget
            chart_layout.addWidget(widget)

        def update_detail() -> None:
            if not timeline_rows:
                detail_browser.setHtml(
                    format_timeline_detail_html(
                        None,
                        reason=(
                            f"No Replay rows found for {ticker}. "
                            "The selected filters may hide non-trading-day or quarantined captures, "
                            "or this symbol may not exist in stored captures."
                        ),
                    )
                )
                return
            selected_row = selected_timeline_row(timeline_rows, table.currentRow())
            if selected_row is None:
                detail_browser.setHtml(format_timeline_detail_html(None, reason="No Replay row selected. Select a row to inspect its identity."))
                return
            detail_browser.setHtml(format_timeline_detail_html(selected_row))

        def selected_story_row() -> TimelineRow | None:
            row_index = story_table.currentRow()
            if row_index < 0:
                row_index = 0
            if row_index < 0 or row_index >= len(story_summary.points):
                return None
            return story_summary.points[row_index].row

        def update_mode() -> None:
            mode = mode_combo.currentText()
            audit_mode = mode == "Audit"
            trail_mode = mode == "Trail"
            story_header.setVisible(True)
            chart_holder.setVisible(trail_mode)
            story_table.setVisible(trail_mode)
            audit_box.setVisible(audit_mode)
            mode_placeholder.setVisible(mode in {"Intraday", "5D"})
            if mode == "Intraday":
                mode_placeholder.setText("No minute bars available for this symbol/date in Candidate Story v1. Capture-only trail is available in Trail mode.")
            elif mode == "5D":
                mode_placeholder.setText("No 5D stored price context is available in Candidate Story v1. Capture-only trail is available in Trail mode.")
            replay_button.setEnabled(bool(timeline_rows))

        def refresh() -> None:
            nonlocal timeline_rows, story_summary
            timeline_rows = build_candidate_timeline(
                ticker,
                include_quarantined=show_quarantined.isChecked(),
                include_non_trading_day=show_non_trading_day.isChecked(),
                newest_first=sort_combo.currentText() == "Newest First",
            )
            story_summary = build_candidate_story_summary(timeline_rows)
            story_header.setHtml(format_candidate_story_header_html(story_summary))
            replace_chart(build_candidate_story_chart(story_summary))
            populate_candidate_story_rows(story_table, story_summary)
            populate_timeline_table(table, timeline_rows)
            apply_timeline_preset(table, "Audit")
            replay_button.setEnabled(bool(timeline_rows))
            update_detail()
            update_mode()

        def replay_selected() -> None:
            if not timeline_rows:
                self._show_action_blocked(f"No Replay rows found for {ticker}. Change filters or choose a different candidate.")
                return
            selected_row = selected_timeline_row(timeline_rows, table.currentRow()) if mode_combo.currentText() == "Audit" else selected_story_row()
            if selected_row is None:
                self._show_action_blocked("No Replay row selected. Select a capture row before opening Replay.")
                return
            self._show_replay_dialog(selected_row)

        sort_combo.currentTextChanged.connect(refresh)
        mode_combo.currentTextChanged.connect(lambda _value: update_mode())
        show_quarantined.stateChanged.connect(refresh)
        show_non_trading_day.stateChanged.connect(refresh)
        replay_button.clicked.connect(replay_selected)
        table.itemSelectionChanged.connect(update_detail)
        table.itemDoubleClicked.connect(lambda _item: replay_selected())
        story_table.itemDoubleClicked.connect(lambda _item: replay_selected())
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
                criteria=self._selected_scanner_criteria(),
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
        self._refresh_command_status_cards()

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

    def _autoload_replay_snapshot(self) -> None:
        if not hasattr(self, "page_stack") or self.page_stack.currentIndex() != 4:
            return
        if getattr(self, "replay_snapshot_candidates", None):
            return

        selected_payload = self._selected_capture_payload()
        if selected_payload and selected_payload.get("candidates"):
            self._load_historical_capture(selected_payload)
            self._load_replay_snapshot(selected_payload)
            return

        latest_payload = self._latest_capture_payload_with_candidates()
        if latest_payload:
            date_text = str(latest_payload.get("capture_date") or "")
            session_text = str(latest_payload.get("session") or "")
            if date_text:
                if self.capture_date_combo.findText(date_text) < 0:
                    self.capture_date_combo.addItem(date_text)
                self.capture_date_combo.setCurrentText(date_text)
                self._capture_date_changed(date_text)
            if session_text:
                if self.capture_session_combo.findText(session_text) < 0:
                    self.capture_session_combo.addItem(session_text)
                self.capture_session_combo.setCurrentText(session_text)
            self._load_historical_capture(latest_payload)
            self._load_replay_snapshot(latest_payload)
            return

        if selected_payload:
            self._load_historical_capture(selected_payload)
            self._load_replay_snapshot(selected_payload)
            return

        if hasattr(self, "replay_snapshot_status_label"):
            self.replay_snapshot_status_label.setText(
                "No historical snapshot candidates are available yet. Choose another date/session or run a capture."
            )

    def _selected_capture_payload(self) -> dict:
        date_text = self.capture_date_combo.currentText()
        session_text = self.capture_session_combo.currentText()
        if not date_text or not session_text or date_text == "No captures yet" or session_text == "No sessions yet":
            return {}
        try:
            session = CaptureSession(session_text)
        except ValueError:
            return {}
        payload = load_capture_json(date_text, session)
        if payload:
            payload = dict(payload)
            payload.setdefault("capture_date", date_text)
            payload.setdefault("session", session.value)
            payload["_source_path"] = str(DATA_DIR / "captures" / date_text / f"{session.value}.json")
        return payload

    def _latest_capture_payload_with_candidates(self) -> dict:
        for date_text in list_capture_dates():
            for session in list_capture_sessions(date_text):
                payload = load_capture_json(date_text, session)
                if not payload or not payload.get("candidates"):
                    continue
                payload = dict(payload)
                payload.setdefault("capture_date", date_text)
                payload.setdefault("session", session.value)
                payload["_source_path"] = str(DATA_DIR / "captures" / date_text / f"{session.value}.json")
                return payload
        return {}

    def open_selected_capture(self) -> None:
        date_text = self.capture_date_combo.currentText()
        session_text = self.capture_session_combo.currentText()
        if not date_text or not session_text or date_text == "No captures yet" or session_text == "No sessions yet":
            self._show_text_dialog("Daily Capture", "No daily capture is available yet.")
            return
        session = CaptureSession(session_text)
        payload = self._selected_capture_payload()
        if payload:
            self._load_historical_capture(payload)
            self._load_replay_snapshot(payload)
            return
        report = load_capture_report(date_text, session)
        if not report:
            self._show_text_dialog("Daily Capture", "No report exists for that date and session.")
            return
        self._show_text_dialog(f"{date_text} {session_text.title()} Capture", report)

    def open_study_engine(self) -> None:
        def show_research(summary: object, elapsed_seconds: float) -> None:
            if not isinstance(summary, StudySummary):
                self._show_action_blocked("Research Lab returned an unexpected study summary type.", "Research Lab Error")
                return
            self._update_status(f"Research Lab opened in {elapsed_seconds:.2f} seconds.")
            self._show_study_dialog(summary)

        self._run_report_loader(
            title="Research Lab",
            loading_message="Loading Research Lab without blocking the dashboard...",
            loader=build_capture_study,
            on_success=show_research,
            error_title="Research Lab Error",
        )

    def _show_study_engine_dialog(self, summary: StudySummary, elapsed_seconds: float) -> None:
        self._update_status(f"Research Lab opened in {elapsed_seconds:.2f} seconds.")
        self._show_study_dialog(summary)

    def _run_report_loader(
        self,
        *,
        title: str,
        loading_message: str,
        loader: Callable[[], object],
        on_success: Callable[[object, float], None],
        error_title: str,
    ) -> None:
        if title in self._active_report_loader_titles:
            self._update_status(f"{title} is already loading; please wait.")
            return
        self._active_report_loader_titles.add(title)
        progress = self._show_loading_dialog(title, loading_message)
        thread = QThread(self)
        worker = ReportLoaderWorker(loader)
        worker.moveToThread(thread)
        ref = (thread, worker, progress)
        self._report_loader_refs.append(ref)
        self._update_status(loading_message)

        def cleanup() -> None:
            if ref in self._report_loader_refs:
                self._report_loader_refs.remove(ref)
            self._active_report_loader_titles.discard(title)
            thread.quit()
            thread.wait(1500)
            worker.deleteLater()
            thread.deleteLater()

        def finish(result: object, elapsed_seconds: float) -> None:
            progress.close()
            cleanup()
            try:
                on_success(result, elapsed_seconds)
            except Exception as exc:
                self._show_action_blocked(
                    f"{title} loaded data but failed while opening the UI: {type(exc).__name__}: {exc}",
                    error_title,
                )

        def fail(error_type: str, message: str, elapsed_seconds: float) -> None:
            progress.close()
            cleanup()
            self._show_action_blocked(
                f"{title} failed after {elapsed_seconds:.2f} seconds: {error_type}: {message}",
                error_title,
            )

        thread.started.connect(worker.run)
        worker.finished.connect(finish)
        worker.failed.connect(fail)
        thread.start()

    def _show_loading_dialog(self, title: str, message: str) -> QDialog:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(False)
        layout = QVBoxLayout(dialog)
        label = QLabel(message)
        label.setObjectName("criteriaLabel")
        label.setWordWrap(True)
        layout.addWidget(label)
        dialog.resize(460, 120)
        dialog.setStyleSheet(STYLESHEET)
        dialog.show()
        return dialog

    def _load_historical_capture(self, payload: dict) -> None:
        self.display_capture_time = datetime.fromisoformat(payload["capture_time"]) if payload.get("capture_time") else None
        self.display_session_label = payload.get("session", "snapshot")
        self.display_provider_label = payload.get("provider", "")
        self.display_mode_label = payload.get("mode", "")
        scanner_payload = payload.get("scanner", {})
        self.display_scanner_label = scanner_payload.get("name", "") if isinstance(scanner_payload, dict) else str(scanner_payload)
        self.display_calendar_status = payload.get("capture_calendar_status", "")
        self.display_next_market_session_date = payload.get("next_market_session_date", "")
        self.display_quarantined = str(payload.get("capture_status", "")).lower() == "quarantined"
        context = classify_scheduled_snapshot(
            capture_time=self.display_capture_time,
            session=self.display_session_label,
            next_market_session_date=self.display_next_market_session_date,
            freshness_threshold_minutes=load_freshness_settings().current_dashboard_stale_minutes,
            quarantined=self.display_quarantined,
        )
        if context.can_review:
            self.data_view_state = DataViewState.NEXT_SESSION_REVIEW
        elif context.state == OperatorReviewState.EXPIRED_REVIEW_SNAPSHOT:
            self.data_view_state = DataViewState.EXPIRED_REVIEW
        else:
            self.data_view_state = DataViewState.HISTORICAL
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
        loaded_context = self.current_operator_context or self._operator_review_context()
        candidate_count = len(self.candidates)
        suffix = f"{candidate_count} candidate(s) loaded." if candidate_count else "No candidates found in this capture."
        self._update_status(f"Loaded capture: {loaded_context.label}. {suffix}")

    def _load_replay_snapshot(self, payload: dict) -> None:
        self.replay_snapshot_payload = dict(payload)
        self.replay_snapshot_candidates = [candidate_from_dict(item) for item in payload.get("candidates", [])]
        for raw_candidate, candidate in zip(payload.get("candidates", []), self.replay_snapshot_candidates):
            if not raw_candidate.get("news_stack"):
                apply_candidate_news_stack(candidate, now=self.display_capture_time)
        self._populate_replay_snapshot_table()

    def _populate_replay_snapshot_table(self) -> None:
        if not hasattr(self, "replay_snapshot_table"):
            return
        table = self.replay_snapshot_table
        candidate_count = len(self.replay_snapshot_candidates)
        date_text = ""
        session_text = ""
        if isinstance(self.replay_snapshot_payload, dict):
            date_text = str(self.replay_snapshot_payload.get("capture_date") or "")
            session_text = str(self.replay_snapshot_payload.get("session") or "")
        if hasattr(self, "replay_snapshot_status_label"):
            if candidate_count:
                source_label = " ".join(part for part in [date_text, session_text] if part).strip()
                suffix = f" from {source_label}" if source_label else ""
                self.replay_snapshot_status_label.setText(
                    f"Loaded {candidate_count} candidate(s){suffix}. Select a row, then open Timeline / Replay."
                )
            else:
                source_label = " ".join(part for part in [date_text, session_text] if part).strip()
                suffix = f" for {source_label}" if source_label else ""
                self.replay_snapshot_status_label.setText(
                    f"Selected historical snapshot{suffix} has no candidates. Choose another date/session."
                )
        table.blockSignals(True)
        table.clearSelection()
        table.setRowCount(candidate_count)
        for row, candidate in enumerate(self.replay_snapshot_candidates):
            values = [
                candidate.ticker,
                str(candidate.score),
                f"${candidate.price:,.2f}",
                f"{candidate.percent_change:.1f}%",
                f"{candidate.volume:,}",
                f"{candidate.relative_volume:.2f}x" if candidate.relative_volume else "n/a",
                format_market_cap(candidate.market_cap),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    item.setBackground(score_color(candidate.score))
                table.setItem(row, column, item)
        table.resizeColumnsToContents()
        table.blockSignals(False)
        if self.replay_snapshot_candidates:
            table.selectRow(0)
            self._replay_snapshot_selection_changed()
        else:
            self.replay_snapshot_detail.setHtml(
                format_replay_snapshot_detail_html(
                    None,
                    payload=self.replay_snapshot_payload,
                    reason="Selected capture has no candidates.",
                )
            )

    def _selected_replay_snapshot_candidate(self) -> Candidate | None:
        if not hasattr(self, "replay_snapshot_table"):
            return None
        rows = self.replay_snapshot_table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if row < 0 or row >= len(self.replay_snapshot_candidates):
            return None
        return self.replay_snapshot_candidates[row]

    def _replay_snapshot_selection_changed(self) -> None:
        candidate = self._selected_replay_snapshot_candidate()
        if not hasattr(self, "replay_snapshot_detail"):
            return
        selected_index = -1
        if hasattr(self, "replay_snapshot_table"):
            rows = self.replay_snapshot_table.selectionModel().selectedRows()
            selected_index = rows[0].row() if rows else -1
        self.replay_snapshot_detail.setHtml(
            format_replay_snapshot_detail_html(
                candidate,
                payload=self.replay_snapshot_payload,
                selected_index=selected_index,
            )
        )

    def return_to_current_dashboard(self) -> None:
        self.data_view_state = DataViewState.CURRENT
        self.display_capture_time = self.current_capture_time
        self.display_session_label = "live"
        self.display_provider_label = self.provider_combo.currentText()
        self.display_scanner_label = self._selected_scanner_key()
        self.display_mode_label = self.config.mode.value
        self.display_calendar_status = ""
        self.display_next_market_session_date = ""
        self.display_quarantined = False
        self.candidates = list(self.live_candidates)
        self.saved_candidates = dict(self.live_saved_candidates)
        self.reviewed_tickers = set(self.live_reviewed_tickers)
        self.selected_ticker = None
        self._apply_data_view_state()
        self._populate_table()
        self._update_score_chart()
        self._update_status("Returned to current dashboard. Run Scanner for fresh data.")
        self._navigate_to_page(0)

    def _apply_data_view_state(self) -> None:
        style = get_data_view_style(
            self.data_view_state,
            captured_at=self.display_capture_time,
            session_label=self.display_session_label,
        )
        self.current_view_style = style
        self.current_operator_context = self._operator_review_context()
        self.view_state_label.setObjectName(style.object_name)
        self.view_state_label.setText(style.banner_text)
        self.detail_state_label.setText(style.detail_label)
        self.chart_state_label.setText(f"{style.chart_prefix}Top Momentum Candidates")
        self._set_chart_watermark(style)
        self.table.horizontalHeader().setStyleSheet(style.header_stylesheet)
        can_review = self.current_operator_context.can_review
        can_generate = self.current_operator_context.can_generate_watchlist
        self.mark_interested_button.setEnabled(can_review)
        self.mark_rejected_button.setEnabled(can_review)
        self.add_interested_button.setEnabled(can_review)
        self.clear_button.setEnabled(can_review)
        if hasattr(self, "watchlist_center_move_button"):
            self.watchlist_center_move_button.setEnabled(can_review)
        self.watchlist_button.setEnabled(can_generate)
        self.morning_review_button.setEnabled(bool(self.candidates or self.live_candidates))
        self.notes_edit.setReadOnly(not can_review)
        self.entry_trigger.setReadOnly(not can_review)
        self.stop_level.setReadOnly(not can_review)
        self.entry_thesis.setReadOnly(not can_review)
        self.entry_invalidation.setReadOnly(not can_review)
        self.entry_max_loss.setReadOnly(not can_review)
        self.entry_position_size.setReadOnly(not can_review)
        self.entry_hold_time.setReadOnly(not can_review)
        self.entry_notes.setReadOnly(not can_review)
        self.plan_complete_checkbox.setEnabled(can_review)
        self.scan_button.setProperty("emphasized", not can_review)
        self.scan_button.style().unpolish(self.scan_button)
        self.scan_button.style().polish(self.scan_button)
        self._refresh_view_state_style()
        self._update_operator_guidance()
        self._update_score_chart()
        self._refresh_command_status_cards()
        self._refresh_watchlist_center()

    def _refresh_view_state_style(self) -> None:
        self.view_state_label.style().unpolish(self.view_state_label)
        self.view_state_label.style().polish(self.view_state_label)

    def _is_read_only_view(self) -> bool:
        context = self.current_operator_context or self._operator_review_context()
        return not context.can_review

    def _can_generate_watchlist(self) -> bool:
        context = self.current_operator_context or self._operator_review_context()
        return context.can_generate_watchlist

    def _operator_review_context(self) -> OperatorReviewContext:
        settings = load_freshness_settings()
        if self.display_quarantined:
            return blocked_context(
                OperatorReviewState.QUARANTINED_BLOCKED,
                "Quarantined Capture - Blocked",
                "This capture is quarantined and blocked from review workflow.",
            )
        if self.data_view_state == DataViewState.STUDY:
            return blocked_context(
                OperatorReviewState.STUDY_READ_ONLY,
                "Research View - Read Only",
                "This view is research-only.",
            )
        if self.data_view_state == DataViewState.HISTORICAL:
            return blocked_context(
                OperatorReviewState.HISTORICAL_READ_ONLY,
                "Historical Snapshot - Read Only",
                "This capture is historical and cannot be used for a new watchlist.",
            )
        if self.data_view_state == DataViewState.EXPIRED_REVIEW:
            return blocked_context(
                OperatorReviewState.EXPIRED_REVIEW_SNAPSHOT,
                "Expired Review Snapshot - Read Only",
                "This snapshot is expired for trading workflow.",
            )
        if self.data_view_state == DataViewState.NEXT_SESSION_REVIEW:
            return classify_scheduled_snapshot(
                capture_time=self.display_capture_time,
                session=self.display_session_label,
                next_market_session_date=self.display_next_market_session_date,
                freshness_threshold_minutes=settings.current_dashboard_stale_minutes,
                quarantined=self.display_quarantined,
            )
        return classify_current_manual_scan(
            capture_time=self.display_capture_time,
            candidates_loaded=bool(self.candidates),
            freshness_threshold_minutes=settings.current_dashboard_stale_minutes,
        )

    def _update_operator_guidance(self) -> None:
        if not hasattr(self, "operator_guidance_label"):
            return
        context = self.current_operator_context or self._operator_review_context()
        guidance = context.guidance
        if context.can_review and self.candidates:
            unreviewed = [
                candidate
                for candidate in self.candidates
                if self._candidate_review_status(candidate) == ReviewStatus.UNREVIEWED
            ]
            watchlist = self._watchlist_candidates()
            incomplete_plans = []
            for candidate in watchlist:
                identity = self._candidate_identity(candidate)
                plan = self.entry_plans.get(identity.key)
                if plan is None or entry_plan_warnings(plan):
                    incomplete_plans.append(candidate)
            if unreviewed:
                guidance = "You have unreviewed candidates. Mark them Interested, Rejected, or Watchlist."
            elif incomplete_plans:
                guidance = "Watchlist candidates are missing entry plans."
            elif watchlist:
                guidance = "Watchlist report is ready to generate."
        self.operator_guidance_label.setText(guidance)

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
            DataViewState.NEXT_SESSION_REVIEW: "REVIEW" if not style.is_warning else "AGING REVIEW",
            DataViewState.EXPIRED_REVIEW: "EXPIRED",
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
                scanner=self.display_scanner_label or self._selected_scanner_key(),
                mode=self.display_mode_label or self.config.mode.value,
                regime=self.market_regime.regime,
            )
        except Exception as exc:
            self._update_status(f"Score breakdown persistence failed: {exc}")

    def show_score_breakdown(self) -> None:
        candidate = self._selected_candidate()
        if candidate is None:
            self._show_action_blocked("No candidate selected. Select a candidate first.")
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
                scanner=self.display_scanner_label or self._selected_scanner_key(),
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
        self._show_score_breakdown_dialog(record, candidate=candidate)

    def _show_score_breakdown_dialog(self, record: dict, candidate: Candidate | None = None) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Why {record.get('final_score', '')}? - {record.get('ticker', '')}")
        dialog.resize(920, 720)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(format_score_breakdown_html(record, candidate=candidate))
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
            scanner=self.display_scanner_label or self._selected_scanner_key(),
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
        scanner = self.display_scanner_label or self._selected_scanner_key()
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

    def _entry_plans_for_candidates(self, candidates: list[Candidate]) -> dict[str, EntryPlan]:
        plans: dict[str, EntryPlan] = {}
        for candidate in candidates:
            identity = self._candidate_identity(candidate)
            plan = self.entry_plans.get(identity.key)
            if plan is None:
                plan = upsert_entry_plan(self.entry_plans, identity)
            plans[candidate.ticker] = plan
        return plans

    def _marked_candidates(self) -> list[Candidate]:
        marked: list[Candidate] = []
        for row, candidate in enumerate(self.candidates):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                marked.append(candidate)
        return marked

    def _refresh_row_states(self, *, clear_checks: bool = False) -> None:
        for row, candidate in enumerate(self.candidates):
            item = self.table.item(row, 0)
            if item is not None and clear_checks:
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
        self._update_operator_guidance()

    def _update_status(self, message: str) -> None:
        self.clock_label.setText(format_central())
        self.status_label.setText(message)

    def _show_action_blocked(self, message: str, title: str = "Action Not Available") -> None:
        QMessageBox.information(self, title, message)
        self._update_status(message)

    def _confirm_aging_review_watchlist(self) -> bool:
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowTitle("Aging but Reviewable")
        dialog.setText(
            "This capture is older, but it is still the active review snapshot for the next market session. Continue?"
        )
        continue_button = dialog.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() == continue_button

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
        dialog.setWindowTitle("Momentum Hunter Research Lab")
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
        cluster_filter_layout.addWidget(QLabel("Industry"))
        industry_edit = QLineEdit()
        industry_edit.setPlaceholderText("all industries")
        cluster_filter_layout.addWidget(industry_edit)
        cluster_filter_layout.addWidget(QLabel("Score Bucket"))
        score_bucket_combo = QComboBox()
        score_bucket_combo.addItems([SCORE_BUCKET_ALL, "0-49", "50-69", "70-84", "85-100"])
        cluster_filter_layout.addWidget(score_bucket_combo)
        cluster_filter_layout.addWidget(QLabel("Min Score"))
        minimum_score_edit = QLineEdit()
        minimum_score_edit.setPlaceholderText("0")
        minimum_score_edit.setMaximumWidth(70)
        cluster_filter_layout.addWidget(minimum_score_edit)
        cluster_filter_layout.addWidget(QLabel("Review"))
        review_combo = QComboBox()
        review_combo.addItems([REVIEW_ALL, "unreviewed", "interested", "rejected", "watchlist"])
        cluster_filter_layout.addWidget(review_combo)
        cluster_filter_layout.addWidget(QLabel("Theme"))
        theme_combo = QComboBox()
        theme_combo.addItems(
            [
                HISTORICAL_THEME_ALL,
                "Earnings / guidance",
                "Analyst upgrade / downgrade",
                "AI infrastructure",
                "Healthcare / FDA / biotech",
                "High volume institutional momentum",
                "Low-quality hype / weak catalyst",
                "Sector sympathy move",
                "No clear catalyst",
            ]
        )
        cluster_filter_layout.addWidget(theme_combo)
        cluster_filter_layout.addStretch(1)
        layout.addWidget(cluster_filter_row)

        age_filter_row = QWidget()
        age_filter_layout = QHBoxLayout(age_filter_row)
        age_filter_layout.setContentsMargins(0, 0, 0, 0)
        age_filter_layout.addWidget(QLabel("Ticker"))
        ticker_edit = QLineEdit()
        ticker_edit.setPlaceholderText("all tickers")
        ticker_edit.setMaximumWidth(90)
        age_filter_layout.addWidget(ticker_edit)
        age_filter_layout.addWidget(QLabel("Catalyst"))
        catalyst_combo = QComboBox()
        catalyst_combo.addItems(
            [
                CATALYST_CLUSTER_ALL,
                "Earnings beat",
                "Guidance raise",
                "Earnings/guidance general",
                "Analyst upgrade",
                "Analyst target raise",
                "Analyst downgrade",
                "AI infrastructure",
                "AI partnership",
                "Contract / customer win",
                "FDA approval",
                "FDA binary event",
                "Biotech clinical data",
                "Merger / acquisition",
                "Product / platform launch",
                "Capital markets / financing",
                "Legal / regulatory",
                "Leadership / strategic update",
                "Index / fund flow",
                "Macro-only",
                "Price action / no catalyst detail",
                "Weak / vague catalyst",
                "Sector sympathy",
                "No clear catalyst",
                "Unknown / uncategorized",
            ]
        )
        age_filter_layout.addWidget(catalyst_combo)
        age_filter_layout.addWidget(QLabel("Timestamp"))
        timestamp_combo = QComboBox()
        timestamp_combo.addItems([TIMESTAMP_STATUS_ALL, *TIMESTAMP_STATUSES])
        age_filter_layout.addWidget(timestamp_combo)
        age_filter_layout.addWidget(QLabel("Age"))
        age_bucket_combo = QComboBox()
        age_bucket_combo.addItems([AGE_BUCKET_ALL, *AGE_BUCKETS])
        age_filter_layout.addWidget(age_bucket_combo)
        age_filter_layout.addStretch(1)
        layout.addWidget(age_filter_row)

        quality_filter_row = QWidget()
        quality_filter_layout = QHBoxLayout(quality_filter_row)
        quality_filter_layout.setContentsMargins(0, 0, 0, 0)
        quality_filter_layout.addWidget(QLabel("Min Confidence"))
        confidence_edit = QLineEdit()
        confidence_edit.setPlaceholderText("0")
        confidence_edit.setMaximumWidth(70)
        quality_filter_layout.addWidget(confidence_edit)
        quality_filter_layout.addWidget(QLabel("Min Purity %"))
        purity_edit = QLineEdit()
        purity_edit.setPlaceholderText("0")
        purity_edit.setMaximumWidth(70)
        quality_filter_layout.addWidget(purity_edit)
        quality_filter_layout.addWidget(QLabel("Min Exact Timestamp %"))
        timestamp_quality_edit = QLineEdit()
        timestamp_quality_edit.setPlaceholderText("0")
        timestamp_quality_edit.setMaximumWidth(70)
        quality_filter_layout.addWidget(timestamp_quality_edit)
        quality_filter_layout.addWidget(QLabel("Source"))
        source_edit = QLineEdit()
        source_edit.setPlaceholderText("all sources")
        source_edit.setMaximumWidth(140)
        quality_filter_layout.addWidget(source_edit)
        quality_filter_layout.addWidget(QLabel("Min Duplicates"))
        duplicate_edit = QLineEdit()
        duplicate_edit.setPlaceholderText("0")
        duplicate_edit.setMaximumWidth(70)
        quality_filter_layout.addWidget(duplicate_edit)
        quality_filter_layout.addStretch(1)
        layout.addWidget(quality_filter_row)

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
            minimum_confidence = 0
            minimum_purity = 0
            minimum_timestamp_quality = 0
            minimum_duplicate_count = 0
            try:
                minimum_score = int(float(minimum_score_edit.text().strip() or "0"))
            except ValueError:
                minimum_score = 0
            try:
                minimum_confidence = int(float(confidence_edit.text().strip() or "0"))
            except ValueError:
                minimum_confidence = 0
            try:
                minimum_purity = int(float(purity_edit.text().strip() or "0"))
            except ValueError:
                minimum_purity = 0
            try:
                minimum_timestamp_quality = int(float(timestamp_quality_edit.text().strip() or "0"))
            except ValueError:
                minimum_timestamp_quality = 0
            try:
                minimum_duplicate_count = int(float(duplicate_edit.text().strip() or "0"))
            except ValueError:
                minimum_duplicate_count = 0
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
                score_bucket=score_bucket_combo.currentText(),
                industry=industry_edit.text().strip(),
                review_status=review_combo.currentText(),
                historical_cluster_theme=theme_combo.currentText(),
                ticker=ticker_edit.text().strip().upper(),
                catalyst_cluster=catalyst_combo.currentText(),
                timestamp_status=timestamp_combo.currentText(),
                age_bucket=age_bucket_combo.currentText(),
                minimum_confidence=minimum_confidence,
                minimum_purity=minimum_purity,
                minimum_timestamp_quality=minimum_timestamp_quality,
                source=source_edit.text().strip(),
                minimum_duplicate_count=minimum_duplicate_count,
            )

        def make_lazy_research_tab(title: str, description: str, builder: Callable[[], QWidget]) -> QWidget:
            panel = QWidget()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(12, 12, 12, 12)

            label = QLabel(description)
            label.setObjectName("criteriaLabel")
            label.setWordWrap(True)
            panel_layout.addWidget(label)

            load_button = QPushButton(f"Load {title}")
            load_button.setToolTip("Build this research panel on demand so opening Research Lab does not freeze the app.")
            panel_layout.addWidget(load_button)
            panel_layout.addStretch(1)

            def load_panel() -> None:
                started = time.perf_counter()
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                load_button.setEnabled(False)
                label.setText(f"Loading {title}...")
                QApplication.processEvents()
                try:
                    widget = builder()
                    while panel_layout.count():
                        item = panel_layout.takeAt(0)
                        child = item.widget()
                        if child is not None:
                            child.deleteLater()
                    panel_layout.addWidget(widget, 1)
                    elapsed = time.perf_counter() - started
                    self._update_status(f"{title} loaded in {elapsed:.2f} seconds.")
                except Exception as exc:
                    load_button.setEnabled(True)
                    label.setText(f"{title} failed safely: {type(exc).__name__}: {exc}")
                    self._update_status(f"{title} failed safely: {type(exc).__name__}: {exc}")
                finally:
                    QApplication.restoreOverrideCursor()

            load_button.clicked.connect(load_panel)
            return panel

        def refresh_study_view() -> None:
            started = time.perf_counter()
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                active_filter = current_study_filter()
                filtered = build_capture_study(study_filter=active_filter)
                filtered_style = get_data_view_style(
                    DataViewState.STUDY,
                    captured_at=None,
                    study_run_id=filtered.run_id,
                    source_range=filtered.source_range,
                )
                banner.setText(filtered_style.banner_text)
                stats.setText(f"{study_stats_text(filtered)} | Research panels are available on demand.")

                chart_tabs.clear()
                chart_tabs.addTab(build_study_chart(filtered, filtered_style), "Overview - Coverage")
                chart_tabs.addTab(build_outcome_chart(filtered, filtered_style), "Overview - Outcomes")
                chart_tabs.addTab(
                    make_lazy_research_tab(
                        "Historical Setups",
                        "Historical setup clustering is research-only and can take time. Load it when you need that panel.",
                        lambda active_filter=active_filter, filtered_style=filtered_style: build_historical_cluster_panel(
                            build_historical_cluster_report(study_filter=active_filter),
                            filtered_style,
                            build_historical_recurrence_report(study_filter=active_filter),
                            replay_callback=self._show_replay_dialog,
                        ),
                    ),
                    "Catalyst - Historical Setups",
                )
                chart_tabs.addTab(
                    make_lazy_research_tab(
                        "Catalyst Clusters",
                        "Catalyst Cluster Explorer is loaded on demand to keep the Research Lab responsive.",
                        lambda active_filter=active_filter, filtered_style=filtered_style: build_catalyst_cluster_panel(
                            build_catalyst_cluster_report(study_filter=active_filter),
                            filtered_style,
                        ),
                    ),
                    "Catalyst - Clusters",
                )
                chart_tabs.addTab(
                    make_lazy_research_tab(
                        "Catalyst Age",
                        "Catalyst age and timestamp-quality analysis is loaded only when requested.",
                        lambda active_filter=active_filter, filtered_style=filtered_style: build_catalyst_age_panel(
                            build_catalyst_age_audit_report(study_filter=active_filter),
                            filtered_style,
                        ),
                    ),
                    "Catalyst - Age",
                )
                chart_tabs.addTab(
                    make_lazy_research_tab(
                        "Headline Dedup",
                        "Headline deduplication and source quality can be heavy, so it is loaded on demand.",
                        lambda active_filter=active_filter, filtered_style=filtered_style: build_headline_dedup_panel(
                            build_headline_dedup_report(study_filter=active_filter),
                            filtered_style,
                        ),
                    ),
                    "Catalyst - Headline Dedup",
                )
                chart_tabs.addTab(
                    make_lazy_research_tab(
                        "Outcome Explorer",
                        "Outcome Explorer is post-capture research data. Load it when you want outcome tables.",
                        lambda active_filter=active_filter, filtered_style=filtered_style: build_outcome_explorer_panel(
                            build_outcome_explorer_report(study_filter=active_filter),
                            filtered_style,
                        ),
                    ),
                    "Readiness - Outcome Explorer",
                )
                chart_tabs.addTab(
                    make_lazy_research_tab(
                        "Readiness Gates",
                        "Readiness Gate checks completed outcomes and keeps optimization locked until enough evidence exists.",
                        lambda active_filter=active_filter, filtered_style=filtered_style: build_outcome_maturity_panel(
                            build_outcome_maturity_report(study_filter=active_filter),
                            filtered_style,
                        ),
                    ),
                    "Readiness - Gates",
                )
                chart_tabs.addTab(
                    make_lazy_research_tab(
                        "Opportunity Research",
                        "Opportunity Research is diagnostic only and remains locked from trading recommendations.",
                        lambda active_filter=active_filter, filtered_style=filtered_style: build_opportunity_research_panel(
                            build_opportunity_research_report(study_filter=active_filter),
                            filtered_style,
                        ),
                    ),
                    "Readiness - Opportunity Research",
                )
                chart_tabs.addTab(
                    make_lazy_research_tab(
                        "Locked Research Notes",
                        "Locked Research Notes explain why recommendations remain disabled until evidence thresholds mature.",
                        lambda filtered_style=filtered_style: build_recommendation_panel(
                            build_weight_recommendations(),
                            filtered_style,
                        ),
                    ),
                    "Locked Research Notes",
                )

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
                elapsed = time.perf_counter() - started
                stats.setText(f"{study_stats_text(filtered)} | Initial panels loaded in {elapsed:.2f}s. Heavy panels load on demand.")
                self._update_status(f"Research Lab initial panels loaded in {elapsed:.2f} seconds.")
            except Exception as exc:
                chart_tabs.clear()
                error = QLabel(f"Research panel failed safely: {type(exc).__name__}: {exc}")
                error.setObjectName("detailStateLabel")
                error.setWordWrap(True)
                chart_tabs.addTab(error, "Research Error")
                stats.setText("Research panel failed safely. Main app remains available.")
                self._update_status(f"Research Lab panel failed safely: {type(exc).__name__}: {exc}")
            finally:
                QApplication.restoreOverrideCursor()

        filter_combo.currentTextChanged.connect(refresh_study_view)
        start_date_edit.editingFinished.connect(refresh_study_view)
        end_date_edit.editingFinished.connect(refresh_study_view)
        session_combo.currentTextChanged.connect(refresh_study_view)
        include_non_study_checkbox.stateChanged.connect(refresh_study_view)
        regime_combo.currentTextChanged.connect(refresh_study_view)
        scanner_edit.editingFinished.connect(refresh_study_view)
        sector_edit.editingFinished.connect(refresh_study_view)
        industry_edit.editingFinished.connect(refresh_study_view)
        score_bucket_combo.currentTextChanged.connect(refresh_study_view)
        minimum_score_edit.editingFinished.connect(refresh_study_view)
        review_combo.currentTextChanged.connect(refresh_study_view)
        theme_combo.currentTextChanged.connect(refresh_study_view)
        ticker_edit.editingFinished.connect(refresh_study_view)
        catalyst_combo.currentTextChanged.connect(refresh_study_view)
        timestamp_combo.currentTextChanged.connect(refresh_study_view)
        age_bucket_combo.currentTextChanged.connect(refresh_study_view)
        confidence_edit.editingFinished.connect(refresh_study_view)
        purity_edit.editingFinished.connect(refresh_study_view)
        timestamp_quality_edit.editingFinished.connect(refresh_study_view)
        source_edit.editingFinished.connect(refresh_study_view)
        duplicate_edit.editingFinished.connect(refresh_study_view)
        stats.setText("Research Lab opened. Building panels...")
        QTimer.singleShot(0, refresh_study_view)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.setStyleSheet(STYLESHEET)
        dialog.exec()


def build_daily_workflow_summary_table(report: DailyWorkflowReport, style: DataViewStyle) -> QTableWidget:
    rows = [
        ("Capture Status", "Capture health status", report.capture_health_status),
        ("Review Status", "Total candidates today", str(report.review.total_candidates)),
        ("Review Status", "Reviewed candidates", str(report.review.reviewed_candidates)),
        ("Review Status", "Unreviewed candidates", str(report.review.unreviewed_candidates)),
        ("Review Status", "Interested candidates", str(report.review.interested_candidates)),
        ("Review Status", "Rejected candidates", str(report.review.rejected_candidates)),
        ("Review Status", "Watchlist candidates", str(report.review.watchlist_candidates)),
        ("Entry Plan Status", "Watchlist candidates", str(report.entry_plans.watchlist_candidates)),
        ("Entry Plan Status", "Complete plans", str(report.entry_plans.complete_plans)),
        ("Entry Plan Status", "Incomplete plans", str(report.entry_plans.incomplete_plans)),
        ("Entry Plan Status", "Missing trigger", str(report.entry_plans.missing_trigger)),
        ("Entry Plan Status", "Missing stop", str(report.entry_plans.missing_stop)),
        ("Entry Plan Status", "Missing invalidation", str(report.entry_plans.missing_invalidation)),
        ("Entry Plan Status", "Missing max loss", str(report.entry_plans.missing_max_loss)),
        ("Outcome Status", "Completed next-day outcomes", str(report.completed_next_day_outcomes)),
        ("Outcome Status", "Completed five-day outcomes", str(report.completed_five_day_outcomes)),
        ("Outcome Status", "Pending outcomes", str(report.pending_outcomes)),
    ]
    for name, status in report.readiness_statuses.items():
        rows.append(("Readiness Status", name, status))

    table = QTableWidget(len(rows), 3)
    table.setHorizontalHeaderLabels(["Section", "Metric", "Value"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for row, (section, metric, value) in enumerate(rows):
        table.setItem(row, 0, QTableWidgetItem(section))
        table.setItem(row, 1, QTableWidgetItem(metric))
        item = QTableWidgetItem(value)
        if value in {"LOCKED", "warning - last scheduled capture failed"} or value.startswith("0") and "Complete" in metric:
            item.setBackground(QBrush(QColor("#735f24")))
        table.setItem(row, 2, item)
    return table


def build_daily_workflow_guided_panel(
    report: DailyWorkflowReport,
    style: DataViewStyle,
    context: OperatorReviewContext,
    action_buttons: dict[str, QPushButton],
) -> tuple[QWidget, QLabel, QLabel, dict[str, QLabel]]:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)

    trust = daily_workflow_trust_state(report, style, context)
    trust_label = QLabel(f"{trust['title']}\n{trust['detail']}")
    trust_label.setObjectName("dailyWorkflowTrustLabel")
    trust_label.setWordWrap(True)
    trust_label.setStyleSheet(daily_workflow_panel_stylesheet(trust["level"]))
    layout.addWidget(trust_label)

    next_action = daily_workflow_next_action(report, context)
    next_action_label = QLabel(f"{next_action['title']}\n{next_action['detail']}")
    next_action_label.setObjectName("dailyWorkflowNextActionLabel")
    next_action_label.setWordWrap(True)
    next_action_label.setStyleSheet(daily_workflow_panel_stylesheet(next_action["level"]))
    layout.addWidget(next_action_label)

    sequence_label = QLabel(
        "Sequence: Capture Health -> Morning Review -> Watchlist Plans -> Watchlist Report -> Readiness Gate"
    )
    sequence_label.setObjectName("criteriaLabel")
    sequence_label.setWordWrap(True)
    layout.addWidget(sequence_label)

    for key, button in action_buttons.items():
        button.setProperty("dailyWorkflowAction", key)
        if key == next_action["action_key"]:
            button.setStyleSheet("background: #1f6f4a; border: 1px solid #9ae6b4; font-weight: 700;")
            button.setToolTip("Next required Daily Workflow action.")
        else:
            button.setToolTip("Daily Workflow quick action.")

    step_row = QWidget()
    step_layout = QHBoxLayout(step_row)
    step_layout.setContentsMargins(0, 0, 0, 0)
    step_layout.setSpacing(8)
    step_status_labels: dict[str, QLabel] = {}
    for index, step in enumerate(daily_workflow_steps(report, context, next_action), start=1):
        card = QGroupBox(f"{index}. {step['name']}")
        card.setObjectName(f"dailyWorkflowStep_{step['id']}")
        card.setStyleSheet(daily_workflow_card_stylesheet(step["level"]))
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(6)

        status_label = QLabel(f"Light: {step['light']} | {step['status']}")
        status_label.setObjectName(f"dailyWorkflowStep_{step['id']}_status")
        status_label.setWordWrap(True)
        status_label.setStyleSheet(daily_workflow_light_stylesheet(step["level"]))
        step_status_labels[step["id"]] = status_label
        card_layout.addWidget(status_label)

        dependency_label = QLabel(f"Depends on: {step['dependency']}")
        dependency_label.setWordWrap(True)
        card_layout.addWidget(dependency_label)

        blocker_label = QLabel(f"Blocker: {step['blocker']}")
        blocker_label.setWordWrap(True)
        card_layout.addWidget(blocker_label)

        detail_label = QLabel(step["detail"])
        detail_label.setWordWrap(True)
        card_layout.addWidget(detail_label)

        action_key = step.get("action_key", "")
        if action_key and action_key in action_buttons:
            card_layout.addWidget(action_buttons[action_key])
        else:
            card_layout.addStretch(1)
        step_layout.addWidget(card)
    layout.addWidget(step_row)
    return panel, trust_label, next_action_label, step_status_labels


def daily_workflow_trust_state(
    report: DailyWorkflowReport,
    style: DataViewStyle,
    context: OperatorReviewContext,
) -> dict[str, str]:
    if not context.can_review:
        return {
            "title": f"Trust blocker: {context.label}",
            "detail": context.block_reason or context.guidance or "This view is not available for daily review.",
            "level": "blocked",
        }
    if report.capture_health_status.startswith("warning"):
        return {
            "title": "Trust blocker: capture failure detected",
            "detail": "Open Capture Health before trusting today's workflow.",
            "level": "blocked",
        }
    if report.capture_health_status == "incomplete":
        return {
            "title": "Trust attention: capture health incomplete",
            "detail": "Capture status is incomplete. Review Capture Health before assuming the day is clear.",
            "level": "attention",
        }
    if style.is_warning:
        return {
            "title": f"Trust attention: {context.label}",
            "detail": context.guidance or style.decision_status,
            "level": "attention",
        }
    return {
        "title": f"Trust clear: {context.label}",
        "detail": "Current workflow facts are loaded. Continue with the highlighted next required action.",
        "level": "complete",
    }


def daily_workflow_next_action(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return {
            "title": "Next Required Action: restore a reviewable current workflow",
            "detail": context.block_reason or context.guidance or "Return to a current reviewable capture before daily review.",
            "action_key": "capture",
            "active_step": "capture",
            "level": "blocked",
        }
    if report.capture_health_status.startswith("warning") or report.capture_health_status == "incomplete":
        return {
            "title": "Next Required Action: inspect Capture Health",
            "detail": "Capture health needs attention before the workflow lights can be trusted.",
            "action_key": "capture",
            "active_step": "capture",
            "level": "blocked" if report.capture_health_status.startswith("warning") else "attention",
        }
    if report.review.total_candidates == 0:
        return {
            "title": "Next Required Action: load review candidates",
            "detail": "No candidates are available in the current workflow. Run or load a current capture before review.",
            "action_key": "capture",
            "active_step": "capture",
            "level": "attention",
        }
    if report.review.unreviewed_candidates:
        return {
            "title": "Next Required Action: review candidates",
            "detail": f"{report.review.unreviewed_candidates} candidate(s) still need Interested, Rejected, or Watchlist decisions.",
            "action_key": "review",
            "active_step": "review",
            "level": "active",
        }
    if report.entry_plans.watchlist_candidates == 0:
        return {
            "title": "Daily workflow complete",
            "detail": "All candidates are reviewed and no Watchlist candidates are selected for a report.",
            "action_key": "",
            "active_step": "",
            "level": "complete",
        }
    if report.entry_plans.incomplete_plans:
        return {
            "title": "Next Required Action: complete watchlist plans",
            "detail": (
                f"{report.entry_plans.incomplete_plans} Watchlist plan(s) need trigger, stop, invalidation, "
                "or max-loss discipline."
            ),
            "action_key": "review",
            "active_step": "plans",
            "level": "active",
        }
    return {
        "title": "Next Required Action: generate the Watchlist Report",
        "detail": "Watchlist candidates have complete plan discipline. Generate the report, then use Readiness Gate as a check.",
        "action_key": "report",
        "active_step": "report",
        "level": "active",
    }


def daily_workflow_steps(
    report: DailyWorkflowReport,
    context: OperatorReviewContext,
    next_action: dict[str, str],
) -> list[dict[str, str]]:
    active_step = next_action["active_step"]
    readiness_locked = any(status == "LOCKED" for status in report.readiness_statuses.values())
    steps = [
        daily_workflow_capture_step(report, context),
        daily_workflow_review_step(report, context),
        daily_workflow_plan_step(report, context),
        daily_workflow_report_step(report, context),
        daily_workflow_readiness_step(readiness_locked),
    ]
    for step in steps:
        if step["id"] == active_step and step["level"] not in {"blocked", "locked"}:
            step["level"] = "active"
            step["light"] = "blue"
    return steps


def daily_workflow_capture_step(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return daily_workflow_step(
            "capture",
            "Capture Health",
            "blocked",
            "Blocked",
            "red",
            "A current reviewable capture.",
            context.block_reason or context.guidance or "This view is not available for daily review.",
            "Open Capture Health for diagnostics; return to a current capture before continuing.",
            "capture",
        )
    if report.capture_health_status.startswith("warning"):
        return daily_workflow_step(
            "capture",
            "Capture Health",
            "blocked",
            "Blocked",
            "red",
            "Successful scheduled or current capture health.",
            "A scheduled capture failure is recorded.",
            "Open Capture Health before trusting today's workflow.",
            "capture",
        )
    if report.capture_health_status == "healthy":
        return daily_workflow_step(
            "capture",
            "Capture Health",
            "complete",
            "Complete",
            "green",
            "Capture status from existing Capture Health.",
            "None.",
            "Capture Health reports healthy for the current workflow.",
            "capture",
        )
    return daily_workflow_step(
        "capture",
        "Capture Health",
        "attention",
        "Needs capture",
        "yellow",
        "Morning plus evening or preopen capture health.",
        "Capture Health is incomplete.",
        "Open Capture Health or load a current reviewable capture.",
        "capture",
    )


def daily_workflow_review_step(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return daily_workflow_waiting_step(
            "review",
            "Morning Review",
            "A current reviewable capture.",
            context.block_reason or context.guidance or "This view is read-only.",
            "review",
        )
    if report.review.total_candidates == 0:
        return daily_workflow_waiting_step(
            "review",
            "Morning Review",
            "One or more loaded candidates.",
            "No review candidates are available in the current workflow.",
            "review",
        )
    if report.review.unreviewed_candidates:
        return daily_workflow_step(
            "review",
            "Morning Review",
            "attention",
            "Needs review",
            "yellow",
            "Loaded candidates and a reviewable context.",
            f"{report.review.unreviewed_candidates} candidate(s) still need a review decision.",
            "Mark each candidate Interested, Rejected, or Watchlist.",
            "review",
        )
    return daily_workflow_step(
        "review",
        "Morning Review",
        "complete",
        "Complete",
        "green",
        "All loaded candidates reviewed.",
        "None.",
        f"{report.review.reviewed_candidates} of {report.review.total_candidates} candidate(s) are reviewed.",
        "review",
    )


def daily_workflow_plan_step(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return daily_workflow_waiting_step(
            "plans",
            "Watchlist Plans",
            "A reviewable workflow.",
            context.block_reason or context.guidance or "This view is read-only.",
        )
    if report.review.unreviewed_candidates:
        return daily_workflow_waiting_step(
            "plans",
            "Watchlist Plans",
            "Morning Review complete.",
            "Review decisions are still incomplete.",
        )
    if report.entry_plans.watchlist_candidates == 0:
        return daily_workflow_step(
            "plans",
            "Watchlist Plans",
            "waiting",
            "No watchlist",
            "gray",
            "At least one candidate marked Watchlist.",
            "No Watchlist candidates are selected.",
            "No entry plan is needed unless a candidate is moved to Watchlist.",
            "",
        )
    if report.entry_plans.incomplete_plans:
        return daily_workflow_step(
            "plans",
            "Watchlist Plans",
            "attention",
            "Needs plan",
            "yellow",
            "Watchlist candidates with complete entry-plan fields.",
            f"{report.entry_plans.incomplete_plans} plan(s) are incomplete.",
            "Use Morning Review to add trigger, stop, invalidation, and max loss.",
            "",
        )
    return daily_workflow_step(
        "plans",
        "Watchlist Plans",
        "complete",
        "Complete",
        "green",
        "All Watchlist candidates have complete plan discipline.",
        "None.",
        f"{report.entry_plans.complete_plans} Watchlist plan(s) are complete.",
        "",
    )


def daily_workflow_report_step(report: DailyWorkflowReport, context: OperatorReviewContext) -> dict[str, str]:
    if not context.can_review:
        return daily_workflow_waiting_step(
            "report",
            "Watchlist Report",
            "A reviewable workflow and Watchlist candidates.",
            context.block_reason or context.guidance or "This view is read-only.",
            "report",
        )
    if report.review.unreviewed_candidates:
        return daily_workflow_waiting_step(
            "report",
            "Watchlist Report",
            "Morning Review complete.",
            "Review decisions are still incomplete.",
            "report",
        )
    if report.entry_plans.watchlist_candidates == 0:
        return daily_workflow_step(
            "report",
            "Watchlist Report",
            "waiting",
            "Unavailable",
            "gray",
            "At least one candidate marked Watchlist.",
            "No Watchlist candidates are selected.",
            "The existing report action will explain this if clicked.",
            "report",
        )
    if report.entry_plans.incomplete_plans:
        return daily_workflow_waiting_step(
            "report",
            "Watchlist Report",
            "Complete Watchlist Plans.",
            "Entry-plan discipline is incomplete.",
            "report",
        )
    return daily_workflow_step(
        "report",
        "Watchlist Report",
        "attention",
        "Available",
        "yellow",
        "Reviewed candidates and complete Watchlist plans.",
        "None.",
        "Generate the Watchlist Report using the existing safe action.",
        "report",
    )


def daily_workflow_readiness_step(readiness_locked: bool) -> dict[str, str]:
    if readiness_locked:
        return daily_workflow_step(
            "readiness",
            "Readiness Gate",
            "locked",
            "Locked check",
            "gray",
            "Existing outcome-maturity/readiness report.",
            "One or more research/readiness gates are locked.",
            "This is a check/gate only; it does not approve trades or change readiness logic.",
            "readiness",
        )
    return daily_workflow_step(
        "readiness",
        "Readiness Gate",
        "complete",
        "Available check",
        "green",
        "Existing outcome-maturity/readiness report.",
        "None.",
        "Open Readiness Gate as a read-only check; trading decisions still require operator review.",
        "readiness",
    )


def daily_workflow_waiting_step(
    step_id: str,
    name: str,
    dependency: str,
    blocker: str,
    action_key: str = "",
) -> dict[str, str]:
    return daily_workflow_step(
        step_id,
        name,
        "waiting",
        "Waiting",
        "gray",
        dependency,
        blocker,
        "Complete the upstream light before this step becomes available.",
        action_key,
    )


def daily_workflow_step(
    step_id: str,
    name: str,
    level: str,
    status: str,
    light: str,
    dependency: str,
    blocker: str,
    detail: str,
    action_key: str,
) -> dict[str, str]:
    return {
        "id": step_id,
        "name": name,
        "level": level,
        "status": status,
        "light": light,
        "dependency": dependency,
        "blocker": blocker,
        "detail": detail,
        "action_key": action_key,
    }


def daily_workflow_panel_stylesheet(level: str) -> str:
    colors = {
        "complete": ("#123222", "#1f6f4a", "#d8ffe8"),
        "active": ("#172746", "#3c5d9d", "#eaf1ff"),
        "attention": ("#3a3117", "#a4812a", "#fff0bd"),
        "blocked": ("#3a1717", "#a14646", "#ffe1e1"),
        "locked": ("#2b1f36", "#6d5780", "#f4ecff"),
        "waiting": ("#1b2a3a", "#34475b", "#cbd8e6"),
    }
    background, border, color = colors.get(level, colors["waiting"])
    return (
        f"background: {background}; border: 1px solid {border}; border-radius: 6px; "
        f"color: {color}; font-weight: 700; padding: 8px;"
    )


def daily_workflow_card_stylesheet(level: str) -> str:
    colors = {
        "complete": ("#14251d", "#1f6f4a"),
        "active": ("#172746", "#3c5d9d"),
        "attention": ("#2d2818", "#a4812a"),
        "blocked": ("#2f1919", "#a14646"),
        "locked": ("#241f2d", "#6d5780"),
        "waiting": ("#162230", "#34475b"),
    }
    background, border = colors.get(level, colors["waiting"])
    return (
        "QGroupBox { "
        f"background: {background}; border: 1px solid {border}; border-radius: 6px; "
        "margin-top: 8px; padding: 8px; "
        "} "
        "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #e7edf4; }"
    )


def daily_workflow_light_stylesheet(level: str) -> str:
    colors = {
        "complete": ("#1f6f4a", "#d8ffe8"),
        "active": ("#2563eb", "#eaf1ff"),
        "attention": ("#a4812a", "#fff0bd"),
        "blocked": ("#a14646", "#ffe1e1"),
        "locked": ("#6d5780", "#f4ecff"),
        "waiting": ("#34475b", "#cbd8e6"),
    }
    background, color = colors.get(level, colors["waiting"])
    return (
        f"background: {background}; color: {color}; border-radius: 4px; "
        "font-weight: 700; padding: 5px;"
    )


def build_daily_workflow_warning_table(report: DailyWorkflowReport, style: DataViewStyle) -> QTableWidget:
    warnings = report.warnings or ["No critical workflow warnings."]
    table = QTableWidget(len(warnings), 2)
    table.setHorizontalHeaderLabels(["Warning", "Meaning"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    meanings = {
        "REVIEWS INCOMPLETE": "One or more candidates still needs a human review decision.",
        "WATCHLIST HAS NO ENTRY PLAN": "A watchlist candidate has no saved entry-plan record.",
        "INCOMPLETE ENTRY PLAN": "A watchlist plan is missing trigger, stop, invalidation, or max-loss discipline.",
        "CAPTURE FAILURE DETECTED": "A scheduled capture failure record exists and should be reviewed.",
        "READINESS GATE LOCKED": "Research gates still need more completed outcome data.",
    }
    for row, warning in enumerate(warnings):
        warning_item = QTableWidgetItem(warning)
        if warning in meanings:
            warning_item.setBackground(QBrush(QColor("#735f24")))
        table.setItem(row, 0, warning_item)
        table.setItem(row, 1, QTableWidgetItem(meanings.get(warning, "Workflow is clear for this checkpoint.")))
    return table


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


def morning_review_context(candidate: Candidate) -> dict[str, object]:
    headlines = [item.headline for item in candidate.news if item.headline]
    catalyst_text = candidate.news_stack.freshest_headline or (headlines[0] if headlines else "")
    if not catalyst_text:
        catalyst_text = ", ".join(candidate.score_reasons) or "No catalyst summary loaded."
    classification = classify_catalyst_headline_detail(
        catalyst_text,
        sector=candidate.sector,
        industry=candidate.industry,
        sector_sympathy=False,
    )
    normalized_headlines = [headline.strip().lower() for headline in headlines if headline.strip()]
    duplicate_count = len(normalized_headlines) - len(set(normalized_headlines))
    warnings = []
    if candidate.news_stack.unknown_timestamp_count:
        warnings.append("UNKNOWN TIMESTAMP SOURCE ISSUE")
    if candidate.news_stack.future_timestamp_count:
        warnings.append("FUTURE TIMESTAMP SOURCE ISSUE")
    if duplicate_count > 0:
        warnings.append("DUPLICATE HEADLINE WARNING")
    if classification.match_type != "explicit":
        warnings.append("LOW CATALYST CONFIDENCE")
    purity = "100%" if classification.match_type == "explicit" else "40% fallback"
    return {
        "catalyst_summary": catalyst_text,
        "catalyst_cluster": classification.cluster_name,
        "catalyst_confidence": f"{classification.confidence_label} {classification.confidence_score}",
        "cluster_purity": purity,
        "freshness": f"{candidate.news_stack.freshness} {candidate.news_stack.freshness_score} | {format_news_range(candidate.news_stack)}",
        "warnings": warnings,
    }


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


def compact_status_text(label: QLabel | None, fallback: str) -> str:
    if label is None:
        return fallback
    text = " ".join(label.text().split())
    if not text:
        return fallback
    return text.split(". ", 1)[0]


def entry_plan_progress_text(warnings: list[str]) -> str:
    required_count = 4
    missing_count = len([warning for warning in warnings if warning.startswith("missing ")])
    complete_count = max(0, required_count - missing_count)
    return f"{complete_count}/{required_count}"


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


def populate_candidate_story_rows(table: QTableWidget, summary: CandidateStorySummary) -> None:
    table.setRowCount(len(summary.points))
    for row_index, point in enumerate(summary.points):
        values = [
            f"{point.capture_label} {point.session_marker}",
            format_story_price(point.price),
            f"Prev {format_story_percent(point.price_change_previous_pct)} | First {format_story_percent(point.price_change_first_pct)}",
            format_story_score(point.score),
            format_story_score_delta(point.score_change_previous),
            format_story_rel_vol(point.relative_volume),
            format_compact_volume(point.volume),
            point.note,
            point.later_annotation,
        ]
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setToolTip(point.row.capture_time_text)
            if "Peak score" in point.note:
                item.setBackground(QBrush(QColor("#244d63")))
            elif "Latest capture" in point.note:
                item.setBackground(QBrush(QColor("#1f4d35")))
            elif "First seen" in point.note:
                item.setBackground(QBrush(QColor("#3d3a26")))
            table.setItem(row_index, column, item)
    table.resizeColumnsToContents()
    if summary.points:
        table.selectRow(0)


STORY_PRICE_COLOR = "#38bdf8"
STORY_SCORE_COLOR = "#f59e0b"
STORY_CAPTURE_COLOR = "#e2e8f0"
STORY_FIRST_COLOR = "#a78bfa"
STORY_PEAK_COLOR = "#fb7185"
STORY_LATEST_COLOR = "#22d3ee"


def story_legend_label(color: str, label: str, detail: str = "") -> QLabel:
    detail_html = f"<span style='color:#c5d4e6;'> {escape(detail)}</span>" if detail else ""
    label_widget = QLabel(
        "<span style='font-size:11pt; font-weight:700; color:#f8fafc;'>"
        f"<span style='background-color:{color}; color:{color}; border:1px solid #f8fafc;'>&nbsp;&nbsp;&nbsp;</span>"
        f"&nbsp;{escape(label)}{detail_html}</span>"
    )
    label_widget.setTextFormat(Qt.TextFormat.RichText)
    label_widget.setWordWrap(True)
    label_widget.setMinimumHeight(32)
    label_widget.setStyleSheet(
        "QLabel { background: #0b1624; border: 1px solid #2f4054; border-radius: 6px; padding: 5px 8px; }"
    )
    return label_widget



def story_marker_color(label: str) -> str:
    if label.startswith("First"):
        return STORY_FIRST_COLOR
    if label.startswith("Peak"):
        return STORY_PEAK_COLOR
    if label.startswith("Latest"):
        return STORY_LATEST_COLOR
    return STORY_CAPTURE_COLOR


def build_candidate_story_chart(summary: CandidateStorySummary) -> QWidget:
    if not summary.points:
        return story_placeholder("No trusted captures found for this ticker.")
    if not summary.chartable_price_points:
        return story_placeholder("Capture trail cannot be charted because stored prices are missing.")

    container = QWidget()
    container_layout = QVBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.setSpacing(8)

    legend_row = QWidget()
    legend_layout = QHBoxLayout(legend_row)
    legend_layout.setContentsMargins(10, 6, 10, 0)
    legend_layout.setSpacing(10)
    legend_layout.addWidget(story_legend_label(STORY_PRICE_COLOR, "Price", "left axis"))
    legend_layout.addWidget(story_legend_label(STORY_SCORE_COLOR, "Score", "right axis"))
    legend_layout.addWidget(story_legend_label(STORY_CAPTURE_COLOR, "Capture point"))
    legend_layout.addStretch(1)
    container_layout.addWidget(legend_row)

    marker_row = QWidget()
    marker_layout = QHBoxLayout(marker_row)
    marker_layout.setContentsMargins(10, 0, 10, 2)
    marker_layout.setSpacing(10)
    for label, index in story_marker_specs(summary):
        marker_layout.addWidget(
            story_legend_label(
                story_marker_color(label),
                label,
                format_story_marker_detail(summary, label, index),
            )
        )
    marker_layout.addStretch(1)
    container_layout.addWidget(marker_row)

    chart = QChart()
    chart.setTitle("Capture Trail")
    chart.setTitleBrush(QBrush(QColor("#dbeafe")))
    title_font = QFont()
    title_font.setPointSize(12)
    title_font.setBold(True)
    chart.setTitleFont(title_font)
    chart.setBackgroundBrush(QBrush(QColor("#08131f")))
    chart.setPlotAreaBackgroundBrush(QBrush(QColor("#122033")))
    chart.setPlotAreaBackgroundVisible(True)
    chart.setMargins(QMargins(12, 12, 12, 12))
    chart.legend().setVisible(False)

    price_series = QLineSeries()
    price_series.setName("Price")
    price_series.setPen(QPen(QColor(STORY_PRICE_COLOR), 3))
    price_markers = QScatterSeries()
    price_markers.setName("Capture points")
    price_markers.setMarkerSize(10)
    price_markers.setColor(QColor(STORY_CAPTURE_COLOR))
    price_markers.setBorderColor(QColor("#f8fafc"))
    score_series = QLineSeries()
    score_series.setName("Score")
    score_series.setPen(QPen(QColor(STORY_SCORE_COLOR), 3))

    price_values: list[float] = []
    score_values: list[float] = []
    for index, point in enumerate(summary.points):
        if point.price is not None:
            price_series.append(index, point.price)
            price_markers.append(index, point.price)
            price_values.append(point.price)
        if point.score is not None:
            score_series.append(index, point.score)
            score_values.append(point.score)

    chart.addSeries(price_series)
    chart.addSeries(price_markers)
    if score_values:
        chart.addSeries(score_series)

    axis_x = QValueAxis()
    axis_x.setTitleText("Capture sequence (details below)")
    axis_x.setLabelFormat("%d")
    axis_x.setRange(0, max(1, len(summary.points) - 1))
    axis_x.setTickCount(max(2, min(8, len(summary.points))))
    style_story_axis(axis_x)

    min_price = min(price_values)
    max_price = max(price_values)
    padding = max((max_price - min_price) * 0.12, max_price * 0.02, 0.5)
    axis_price = QValueAxis()
    axis_price.setTitleText("Price")
    axis_price.setLabelFormat("$%.2f")
    axis_price.setRange(max(0, min_price - padding), max_price + padding)
    style_story_axis(axis_price)

    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    chart.addAxis(axis_price, Qt.AlignmentFlag.AlignLeft)
    price_series.attachAxis(axis_x)
    price_series.attachAxis(axis_price)
    price_markers.attachAxis(axis_x)
    price_markers.attachAxis(axis_price)

    if score_values:
        axis_score = QValueAxis()
        axis_score.setTitleText("Score")
        axis_score.setLabelFormat("%.0f")
        axis_score.setRange(0, max(100, max(score_values) + 5))
        style_story_axis(axis_score)
        chart.addAxis(axis_score, Qt.AlignmentFlag.AlignRight)
        score_series.attachAxis(axis_x)
        score_series.attachAxis(axis_score)

    marker_specs = story_marker_specs(summary)
    for label, index in marker_specs:
        point = summary.points[index]
        if point.price is None:
            continue
        marker = QScatterSeries()
        marker.setName(label)
        marker.setMarkerSize(17)
        marker.setColor(QColor(story_marker_color(label)))
        marker.setBorderColor(QColor("#f8fafc"))
        marker.append(index, point.price)
        chart.addSeries(marker)
        marker.attachAxis(axis_x)
        marker.attachAxis(axis_price)

    chart_view = QChartView(chart)
    chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
    chart_view.setMinimumHeight(340)
    container_layout.addWidget(chart_view, 1)
    container.setMinimumHeight(410)
    return container


def style_story_axis(axis: QValueAxis) -> None:
    label_font = QFont()
    label_font.setPointSize(9)
    title_font = QFont()
    title_font.setPointSize(10)
    title_font.setBold(True)
    axis.setLabelsFont(label_font)
    axis.setTitleFont(title_font)
    axis.setLabelsColor(QColor("#f8fafc"))
    axis.setTitleBrush(QBrush(QColor("#dbeafe")))
    axis.setLinePen(QPen(QColor("#cbd5e1"), 1))
    axis.setGridLineColor(QColor("#5b6b80"))
    axis.setMinorGridLineColor(QColor("#334155"))



def story_placeholder(message: str) -> QLabel:
    label = QLabel(message)
    label.setObjectName("detailStateLabel")
    label.setWordWrap(True)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setMinimumHeight(220)
    return label


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
            if row.warnings:
                item.setToolTip(" | ".join(row.warnings))
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


TIMELINE_PRESET_COLUMNS = {
    "Signal": {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 25},
    "Outcome": {0, 1, 5, 13, 19, 20, 21, 22, 23, 24, 25},
    "Audit": set(range(26)),
}


def selected_timeline_row(rows: list[TimelineRow], row_index: int) -> TimelineRow | None:
    if not rows:
        return None
    if row_index < 0 or row_index >= len(rows):
        return None
    return rows[row_index]


def apply_timeline_preset(table: QTableWidget, preset: str) -> None:
    visible_columns = TIMELINE_PRESET_COLUMNS.get(preset, TIMELINE_PRESET_COLUMNS["Signal"])
    for column in range(table.columnCount()):
        table.setColumnHidden(column, column not in visible_columns)
    table.resizeColumnsToContents()


def format_timeline_detail_html(row: TimelineRow | None, *, reason: str = "No timeline row selected.") -> str:
    style = "font-family: Segoe UI, Arial; color:#e7edf4; background:#0b1118; font-size:10pt;"
    if row is None:
        return f"<body style='{style}'><p>{escape(reason)}</p></body>"
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in row.warnings) or "<li>No warnings.</li>"
    audit_strip = format_replay_audit_identity_html(row)
    capture_facts = [
        ("Captured", row.capture_time_text),
        ("Session", row.session),
        ("Provider", row.provider),
        ("Scanner", row.scanner),
        ("Price", timeline_value(row, "price")),
        ("% Change", timeline_value(row, "percent_change")),
        ("Volume", timeline_value(row, "volume")),
        ("Relative Volume", timeline_value(row, "relative_volume")),
        ("Score", timeline_value(row, "score")),
    ]
    later_facts = [
        ("Review", timeline_value(row, "review_status")),
        ("Outcome", timeline_value(row, "outcome_status")),
        ("Next Day State", timeline_value(row, "next_day_outcome_state")),
        ("Expected Next Day", timeline_value(row, "expected_next_day_session_date")),
        ("Next Day", timeline_value(row, "next_day_return_pct")),
        ("5 Day State", timeline_value(row, "five_day_outcome_state")),
        ("Expected 5 Day", timeline_value(row, "expected_five_day_session_date")),
        ("5 Day", timeline_value(row, "five_day_return_pct")),
        ("Max Gain", timeline_value(row, "max_gain_pct")),
        ("Max Drawdown", timeline_value(row, "max_drawdown_pct")),
        ("Outcome Window", f"{timeline_value(row, 'outcome_start_date')} -> {timeline_value(row, 'outcome_end_date')}"),
        ("Outcome Reason", timeline_value(row, "outcome_reason")),
        ("Outcome Version", timeline_value(row, "outcome_calculation_version")),
    ]
    return f"""
    <body style="{style}">
      <b>{escape(row.ticker)}</b> | {escape(row.trust_label)}
      {audit_strip}
      <table cellspacing="0" cellpadding="4" style="width:100%; margin-top:6px;">
        <tr><th align="left">Capture-Time Signal</th><th align="left">Later Annotations</th><th align="left">Warnings</th></tr>
        <tr>
          <td valign="top">{'<br>'.join(f'<b>{escape(label)}:</b> {escape(str(value))}' for label, value in capture_facts)}</td>
          <td valign="top">{'<br>'.join(f'<b>{escape(label)}:</b> {escape(str(value))}' for label, value in later_facts)}</td>
          <td valign="top"><ul style="margin-top:0; color:#fcd34d;">{warnings}</ul></td>
        </tr>
      </table>
    </body>
    """


def format_replay_snapshot_detail_html(
    candidate: Candidate | None,
    *,
    payload: dict | None = None,
    selected_index: int = -1,
    reason: str = "No Replay snapshot candidate selected.",
) -> str:
    style = "font-family: Segoe UI, Arial; color:#e7edf4; background:#0b1118; font-size:10pt;"
    payload = payload or {}
    scanner_payload = payload.get("scanner", {})
    scanner = scanner_payload.get("name", "") if isinstance(scanner_payload, dict) else str(scanner_payload or "")
    capture_date = str(payload.get("capture_date", ""))
    session = str(payload.get("session", ""))
    provider = str(payload.get("provider", ""))
    source_path = str(payload.get("_source_path", ""))
    capture_id = make_capture_id(capture_date, session, provider, scanner) if capture_date or session or provider or scanner else ""
    capture_time = str(payload.get("capture_time", ""))
    if candidate is None:
        return f"""
        <body style="{style}">
          <h3>Historical Snapshot</h3>
          <p>{escape(reason)}</p>
          <div style="margin-top:6px; padding:6px; border:1px solid #33506b; background:#111d2a; color:#d7e8ff;">
            <b>Snapshot Audit Identity</b><br>
            Selected capture timestamp: {escape(capture_time or 'n/a')} |
            Capture ID: {escape(capture_id or 'n/a')}<br>
            Source file/path: {escape(source_path or 'n/a')}<br>
            Last refresh time: {escape(format_central())}
          </div>
        </body>
        """
    candidate_row_id = f"{capture_date}|{session}|{provider}|{scanner}|row:{selected_index}|{candidate.ticker}".upper()
    candidate_fingerprint = "|".join(
        [
            scanner,
            candidate.ticker,
            f"{candidate.price}",
            f"{candidate.percent_change}",
            f"{candidate.volume}",
            f"{candidate.relative_volume}",
            f"{candidate.score}",
        ]
    ).upper()
    news_summary = " | ".join(news_stack_summary(candidate))
    return f"""
    <body style="{style}">
      <h3>{escape(candidate.ticker)} Historical Snapshot Candidate</h3>
      <div style="margin-top:6px; padding:6px; border:1px solid #33506b; background:#111d2a; color:#d7e8ff;">
        <b>Snapshot Audit Identity</b><br>
        Selected capture timestamp: {escape(capture_time)} |
        Capture ID: {escape(capture_id)} |
        Selected symbol: {escape(candidate.ticker)}<br>
        Candidate row ID: {escape(candidate_row_id)}<br>
        Candidate fingerprint: {escape(candidate_fingerprint)}<br>
        Source file/path: {escape(source_path)}<br>
        Last refresh time: {escape(format_central())}
      </div>
      <table cellspacing="0" cellpadding="5" style="width:100%; margin-top:8px;">
        <tr><td><b>Score</b></td><td>{escape(str(candidate.score))}</td></tr>
        <tr><td><b>Price</b></td><td>${candidate.price:,.2f}</td></tr>
        <tr><td><b>% Change</b></td><td>{candidate.percent_change:.1f}%</td></tr>
        <tr><td><b>Volume</b></td><td>{candidate.volume:,}</td></tr>
        <tr><td><b>Relative Volume</b></td><td>{escape(f'{candidate.relative_volume:.2f}x' if candidate.relative_volume else 'n/a')}</td></tr>
        <tr><td><b>Market Cap</b></td><td>{escape(format_market_cap(candidate.market_cap))}</td></tr>
        <tr><td><b>Sector</b></td><td>{escape(candidate.sector)}</td></tr>
        <tr><td><b>Industry</b></td><td>{escape(candidate.industry)}</td></tr>
        <tr><td><b>News Stack</b></td><td>{escape(news_summary or 'No stored news context.')}</td></tr>
      </table>
      <p style="color:#9fb0c2;">Use Open Timeline / Replay For Selected Candidate to inspect all captures for this ticker and its later outcome labels.</p>
    </body>
    """


def format_replay_audit_identity_html(row: TimelineRow) -> str:
    return f"""
      <div style="margin-top:6px; padding:6px; border:1px solid #33506b; background:#111d2a; color:#d7e8ff;">
        <b>Replay Audit Identity</b><br>
        Selected capture timestamp: {escape(row.capture_time_text)} |
        Capture ID: {escape(row.capture_id)} |
        Selected symbol: {escape(row.ticker)}<br>
        Candidate row ID: {escape(row.candidate_row_id)}<br>
        Candidate fingerprint: {escape(row.candidate_fingerprint)}<br>
        Outcome record ID: {escape(row.outcome_record_id)}<br>
        Source file/path: {escape(row.capture_path)}<br>
        Last refresh time: {escape(row.last_refresh_time_text)}
      </div>
    """


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
      {format_replay_audit_identity_html(row)}
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
        <li>Expected next-day session: {escape(str(timeline_value(row, 'expected_next_day_session_date')))}</li>
        <li>Next-day state: {escape(str(timeline_value(row, 'next_day_outcome_state')))}</li>
        <li>Next-day return: {escape(str(outcome.get('next_day_return_pct', '')))}</li>
        <li>Expected five-day session: {escape(str(timeline_value(row, 'expected_five_day_session_date')))}</li>
        <li>Five-day state: {escape(str(timeline_value(row, 'five_day_outcome_state')))}</li>
        <li>Five-day return: {escape(str(outcome.get('five_day_return_pct', '')))}</li>
        <li>Max gain: {escape(str(outcome.get('max_gain_pct', '')))}</li>
        <li>Max drawdown: {escape(str(outcome.get('max_drawdown_pct', '')))}</li>
        <li>Outcome reason: {escape(str(timeline_value(row, 'outcome_reason')))}</li>
        <li>Outcome calculation version: {escape(str(timeline_value(row, 'outcome_calculation_version')))}</li>
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


def scanner_display_name(internal_name: str) -> str:
    return SCANNER_DISPLAY_NAMES.get(internal_name, internal_name)


def latest_trade_plan_csv_path() -> Path | None:
    reports_dir = DATA_DIR / "reports"
    if not reports_dir.exists():
        return None
    files = list(reports_dir.glob("event-trade-plan-briefing-*.csv"))
    if not files:
        files = list(reports_dir.glob("trade-plan-briefing-*.csv"))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def latest_trade_plan_json_path(csv_path: Path | None = None) -> Path | None:
    if csv_path is not None:
        candidate = csv_path.with_suffix(".json")
        if candidate.exists():
            return candidate
    reports_dir = DATA_DIR / "reports"
    if not reports_dir.exists():
        return None
    files = list(reports_dir.glob("event-trade-plan-briefing-*.json"))
    if not files:
        files = list(reports_dir.glob("trade-plan-briefing-*.json"))
    if not files:
        return None
    return max(files, key=lambda path: path.stat().st_mtime)


def load_execution_ready_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    ready_states = {"EXECUTION_READY_PREMARKET", "EXECUTION_READY_TRADE"}
    return [row for row in rows if row.get("Readiness") in ready_states]


def execution_ready_reason(row: dict[str, str]) -> str:
    if row.get("Readiness") == "EXECUTION_READY_PREMARKET":
        return (
            f"premkt vol {row.get('Premarket Volume', 'n/a')} > 500k; "
            f"spread {row.get('Spread %', 'n/a')}% < 0.25%; "
            f"premkt {row.get('Premarket %', 'n/a')}% > 1%"
        )
    return (
        f"RVOL {row.get('Relative Volume', 'n/a')} > 1.2; "
        f"spread {row.get('Spread %', 'n/a')}% < 0.25%; "
        f"{row.get('RVOL Type', '')}"
    )


def execution_ready_display_price(row: dict[str, str]) -> str:
    if row.get("Readiness") == "EXECUTION_READY_PREMARKET":
        return row.get("Premarket Price") or row.get("Last Price", "")
    return row.get("Last Price", "")


def load_state_transition_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [
        {
            "timestamp": str(item.get("timestamp", "")),
            "symbol": str(item.get("symbol", "")),
            "old_state": str(item.get("old_state", "")),
            "new_state": str(item.get("new_state", "")),
            "reason": str(item.get("reason", "")),
        }
        for item in payload.get("state_transition_log", [])
        if isinstance(item, dict)
    ]


def scanner_internal_name(display_name: str) -> str:
    return SCANNER_INTERNAL_NAMES.get(display_name, display_name)


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
    if state in {DataViewState.STALE, DataViewState.EXPIRED_REVIEW}:
        return QColor("#c24d4d")
    return QColor("#2f9d68")


def chart_badge_color(state: DataViewState, is_warning: bool = False) -> QColor:
    if state == DataViewState.HISTORICAL:
        return QColor("#f4ecff")
    if state == DataViewState.STUDY:
        return QColor("#eaf1ff")
    if state in {DataViewState.STALE, DataViewState.EXPIRED_REVIEW}:
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


def build_historical_cluster_panel(
    report: HistoricalClusterReport,
    style: DataViewStyle,
    recurrence_report: HistoricalRecurrenceReport | None = None,
    replay_callback=None,
) -> QWidget:
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

    tabs = QTabWidget()
    tabs.addTab(build_historical_theme_table(report, style), "Themes")
    if recurrence_report is not None:
        tabs.addTab(build_historical_recurrence_panel(recurrence_report, style, replay_callback), "Recurring Clusters")
    layout.addWidget(tabs, 1)
    return panel


def build_historical_theme_table(report: HistoricalClusterReport, style: DataViewStyle) -> QTableWidget:
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
    table.setSortingEnabled(True)
    return table


def build_historical_recurrence_panel(report: HistoricalRecurrenceReport, style: DataViewStyle, replay_callback=None) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}{report.label} | "
        f"Appearances: {report.total_appearances} | Source: {report.source}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    if report.warnings:
        warning = QLabel(" | ".join(report.warnings))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
        layout.addWidget(warning)

    splitter = QSplitter(Qt.Orientation.Vertical)
    cluster_table = QTableWidget(max(1, len(report.clusters)), 13)
    cluster_table.setHorizontalHeaderLabels(
        [
            "Cluster Type",
            "Cluster Key",
            "Appearances",
            "First Seen",
            "Most Recent",
            "Scanners",
            "Sessions",
            "Avg Score",
            "Score Breakdowns",
            "Outcomes",
            "Avg Next",
            "Avg 5-Day",
            "Avg Max / Drawdown",
        ]
    )
    cluster_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    cluster_table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    cluster_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    cluster_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    cluster_table.setSortingEnabled(False)

    if not report.clusters:
        values = ["No repeated clusters", "", "0", "", "", "", "", "n/a", "", "", "n/a", "n/a", "n/a"]
        for column, value in enumerate(values):
            cluster_table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, cluster in enumerate(report.clusters):
            outcome = cluster.outcome_summary
            values = [
                cluster.cluster_type,
                cluster.cluster_key,
                str(cluster.appearance_count),
                cluster.first_seen,
                cluster.most_recent_seen,
                ", ".join(cluster.scanners_involved),
                ", ".join(cluster.sessions_involved),
                format_number(cluster.average_score),
                (
                    f"complete {cluster.complete_score_breakdown_count} | "
                    f"incomplete {cluster.incomplete_score_breakdown_count} | "
                    f"legacy {cluster.legacy_score_breakdown_count} | "
                    f"missing {cluster.missing_score_breakdown_count}"
                ),
                f"later-derived: complete {outcome.completed_count} | pending {outcome.pending_count}",
                format_percent(outcome.average_next_day_return_pct),
                format_percent(outcome.average_five_day_return_pct),
                f"{format_percent(outcome.average_max_gain_pct)} / {format_percent(outcome.average_max_drawdown_pct)}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row)
                elif column == 2:
                    item.setData(Qt.ItemDataRole.DisplayRole, cluster.appearance_count)
                elif column == 7:
                    item.setData(Qt.ItemDataRole.DisplayRole, cluster.average_score or 0)
                if cluster.missing_score_breakdown_count or cluster.incomplete_score_breakdown_count or cluster.legacy_score_breakdown_count:
                    item.setBackground(QBrush(QColor("#735f24")))
                cluster_table.setItem(row, column, item)
    cluster_table.resizeColumnsToContents()
    cluster_table.setSortingEnabled(True)

    detail_panel = QWidget()
    detail_layout = QVBoxLayout(detail_panel)
    detail_layout.setContentsMargins(0, 0, 0, 0)
    detail_note = QLabel("Outcome columns are later-derived labels, not capture-time facts.")
    detail_note.setObjectName("criteriaLabel")
    detail_note.setWordWrap(True)
    detail_layout.addWidget(detail_note)
    detail_table = QTableWidget(0, 13)
    detail_table.setHorizontalHeaderLabels(
        [
            "Ticker",
            "Capture Time",
            "Session",
            "Scanner",
            "Provider",
            "Score",
            "Review",
            "Score Breakdown",
            "Outcome",
            "Next-Day",
            "5-Day",
            "Max Gain",
            "Max Drawdown",
        ]
    )
    detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    detail_table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    detail_layout.addWidget(detail_table, 1)
    replay_button = QPushButton("Replay Selected Appearance")
    replay_button.setEnabled(False)
    detail_layout.addWidget(replay_button)

    current_appearances = []

    def populate_detail() -> None:
        nonlocal current_appearances
        selected_row = cluster_table.currentRow()
        index_item = cluster_table.item(selected_row, 0) if selected_row >= 0 else None
        cluster_index = index_item.data(Qt.ItemDataRole.UserRole) if index_item is not None else None
        if not isinstance(cluster_index, int) or cluster_index < 0 or cluster_index >= len(report.clusters):
            current_appearances = []
        else:
            current_appearances = list(report.clusters[cluster_index].appearances)
        detail_table.setRowCount(max(1, len(current_appearances)))
        if not current_appearances:
            values = ["No appearances", "", "", "", "", "", "", "", "", "", "", "", ""]
            for column, value in enumerate(values):
                detail_table.setItem(0, column, QTableWidgetItem(value))
            replay_button.setEnabled(False)
            return
        for row, appearance in enumerate(current_appearances):
            values = [
                appearance.ticker,
                appearance.capture_time_text,
                appearance.session,
                appearance.scanner,
                appearance.provider,
                str(appearance.score),
                appearance.review_status,
                appearance.score_breakdown_status,
                f"later-derived: {appearance.outcome_status}",
                format_percent(appearance.next_day_return_pct),
                format_percent(appearance.five_day_return_pct),
                format_percent(appearance.max_gain_pct),
                format_percent(appearance.max_drawdown_pct),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if "Quarantined" in appearance.trust_label or appearance.score_breakdown_status in {"missing", "legacy", "incomplete"}:
                    item.setBackground(QBrush(QColor("#735f24")))
                detail_table.setItem(row, column, item)
        detail_table.resizeColumnsToContents()
        detail_table.selectRow(0)
        replay_button.setEnabled(replay_callback is not None)

    def replay_selected() -> None:
        if replay_callback is None or not current_appearances:
            return
        row = detail_table.currentRow()
        if row < 0 or row >= len(current_appearances):
            row = 0
        replay_callback(current_appearances[row].timeline_row)

    cluster_table.itemSelectionChanged.connect(populate_detail)
    replay_button.clicked.connect(replay_selected)
    if report.clusters:
        cluster_table.selectRow(0)
    else:
        populate_detail()

    splitter.addWidget(cluster_table)
    splitter.addWidget(detail_panel)
    splitter.setSizes([330, 390])
    layout.addWidget(splitter, 1)
    return panel


def build_catalyst_cluster_panel(report: CatalystClusterReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}{CATALYST_RESEARCH_LABEL} | "
        f"Headlines: {report.total_headlines} | Candidates: {report.total_candidates} | Source: {report.source}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    if report.warnings:
        warning = QLabel(" | ".join(report.warnings))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
        layout.addWidget(warning)

    tabs = QTabWidget()
    splitter = QSplitter(Qt.Orientation.Vertical)
    table = QTableWidget(0, 19)
    table.setHorizontalHeaderLabels(
        [
            "Catalyst Cluster",
            "Headlines",
            "Candidates",
            "Tickers",
            "Date Range",
            "Confidence",
            "Purity",
            "Explicit",
            "Fallback",
            "Exact TS",
            "Unknown TS",
            "Future TS",
            "Avg Score",
            "Avg Max Gain",
            "Avg Max Drawdown",
            "Win Rate",
            "Representative Headlines",
            "Top Winners",
            "Worst Failures",
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
        values = ["No catalyst clusters", "0", "0", "", "", "n/a", "n/a", "0", "0", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "", "", "No stored headlines matched the filters."]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, cluster in enumerate(report.clusters):
            values = [
                cluster.name,
                str(cluster.headline_count),
                str(cluster.candidate_count),
                ", ".join(cluster.tickers),
                cluster.date_range,
                f"{cluster.dominant_confidence} {format_number(cluster.average_confidence_score)}",
                format_percent(cluster.purity_pct),
                str(cluster.explicit_match_count),
                str(cluster.fallback_match_count),
                format_percent(cluster.timestamp_quality.exact_pct),
                format_percent(cluster.timestamp_quality.unknown_pct),
                format_percent(cluster.timestamp_quality.future_pct),
                format_number(cluster.average_score),
                format_percent(cluster.average_max_gain_pct),
                format_percent(cluster.average_max_drawdown_pct),
                format_percent(cluster.win_rate_pct),
                " | ".join(cluster.representative_headlines),
                ", ".join(cluster.top_winners) or "n/a",
                ", ".join(cluster.worst_failures) or "n/a",
                " | ".join(cluster.warnings) or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if cluster.candidate_count < 10 or cluster.purity_pct < 60:
                    item.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, item)
    table.resizeColumnsToContents()

    detail = QTextBrowser()
    detail.setOpenExternalLinks(True)
    detail.setHtml(format_catalyst_cluster_detail_html(report.clusters[0]) if report.clusters else "<p>No catalyst cluster selected.</p>")

    def update_detail() -> None:
        if not report.clusters:
            return
        row = table.currentRow()
        if row < 0:
            row = 0
        detail.setHtml(format_catalyst_cluster_detail_html(report.clusters[row]))

    table.itemSelectionChanged.connect(update_detail)
    if report.clusters:
        table.selectRow(0)

    splitter.addWidget(table)
    splitter.addWidget(detail)
    splitter.setSizes([360, 360])
    cluster_tab = QWidget()
    cluster_layout = QVBoxLayout(cluster_tab)
    cluster_layout.setContentsMargins(0, 0, 0, 0)
    cluster_layout.addWidget(splitter, 1)
    tabs.addTab(cluster_tab, "Clusters")
    tabs.addTab(build_timestamp_quality_table(report.provider_quality, style, "Provider"), "Provider Quality")
    tabs.addTab(build_timestamp_quality_table(report.cluster_quality, style, "Cluster"), "Cluster Quality")
    tabs.addTab(build_timestamp_quality_table(report.ticker_quality, style, "Ticker"), "Ticker Quality")
    layout.addWidget(tabs, 1)
    return panel


def build_timestamp_quality_table(summaries, style: DataViewStyle, label: str) -> QTableWidget:
    table = QTableWidget(max(1, len(summaries)), 10)
    table.setHorizontalHeaderLabels(
        [label, "Headlines", "Exact", "Unknown", "Future", "Invalid", "Exact %", "Unknown %", "Future %", "Warnings"]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not summaries:
        values = ["No timestamp quality rows", "0", "0", "0", "0", "0", "n/a", "n/a", "n/a", ""]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, summary in enumerate(summaries):
            values = [
                summary.group,
                str(summary.headline_count),
                str(summary.exact_count),
                str(summary.unknown_count),
                str(summary.future_count),
                str(summary.invalid_count),
                format_percent(summary.exact_pct),
                format_percent(summary.unknown_pct),
                format_percent(summary.future_pct),
                " | ".join(summary.warnings),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if summary.warnings:
                    item.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, item)
    table.resizeColumnsToContents()
    return table


def build_catalyst_age_panel(report: CatalystAgeAuditReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}{CATALYST_AGE_RESEARCH_LABEL} | "
        f"Headlines: {report.total_headlines} | Source: {report.source}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    if report.warnings:
        warning = QLabel(" | ".join(report.warnings))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
        layout.addWidget(warning)

    tabs = QTabWidget()
    tabs.addTab(build_catalyst_age_audit_table(report, style), "Audit")
    tabs.addTab(build_catalyst_age_summary_table(report.cluster_summaries, style, "Cluster"), "Clusters")
    tabs.addTab(build_catalyst_age_summary_table(report.ticker_summaries, style, "Ticker"), "Tickers")
    tabs.addTab(build_catalyst_age_detail_table(report, style), "Headlines")
    layout.addWidget(tabs, 1)
    return panel


def build_headline_dedup_panel(report: HeadlineDedupReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}{HEADLINE_DEDUP_RESEARCH_LABEL} | "
        f"Raw Headlines: {report.total_raw_headlines} | Events: {report.total_events} | "
        f"Duplicate Rate: {format_percent(report.duplicate_rate_pct)} | Source: {report.source}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    if report.warnings:
        warning = QLabel(" | ".join(report.warnings))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
        layout.addWidget(warning)

    tabs = QTabWidget()
    tabs.addTab(build_headline_event_table(report, style), "Duplicate Events")
    tabs.addTab(build_source_reliability_table(report, style), "Source Reliability")
    tabs.addTab(build_dedup_impact_table(report.cluster_impact, style, "Cluster"), "Cluster Impact")
    tabs.addTab(build_dedup_impact_table(report.ticker_impact, style, "Ticker"), "Ticker Impact")
    layout.addWidget(tabs, 1)
    return panel


def build_outcome_explorer_panel(report: OutcomeExplorerReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}{OUTCOME_EXPLORER_LABEL} | "
        f"Candidates: {report.summary.candidate_count} | Completed: {report.summary.completed_outcome_count} | "
        f"Pending: {report.summary.pending_outcome_count} | Source: {report.source}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    if report.warnings:
        warning = QLabel(" | ".join(report.warnings))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
        layout.addWidget(warning)

    tabs = QTabWidget()
    tabs.addTab(build_outcome_summary_table(report, style), "Summary")
    tabs.addTab(build_outcome_performance_table(report.score_bucket_performance, style, "Score Bucket"), "Score Buckets")
    tabs.addTab(build_outcome_performance_table(report.regime_performance, style, "Regime"), "Regimes")
    tabs.addTab(build_outcome_performance_table(report.scanner_performance, style, "Scanner"), "Scanners")
    tabs.addTab(build_outcome_performance_table(report.sector_performance, style, "Sector"), "Sectors")
    tabs.addTab(build_outcome_performance_table(report.review_status_performance, style, "Review Status"), "Reviews")
    tabs.addTab(build_outcome_performance_table(report.catalyst_cluster_performance, style, "Catalyst Cluster"), "Catalysts")
    tabs.addTab(build_outcome_performance_table(report.catalyst_age_bucket_performance, style, "Age Bucket"), "Ages")
    tabs.addTab(build_outcome_performance_table(report.cluster_purity_performance, style, "Purity Bucket"), "Purity")
    tabs.addTab(build_outcome_candidate_table(report, style), "Candidates")
    layout.addWidget(tabs, 1)
    return panel


def build_outcome_maturity_panel(report: OutcomeMaturityReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}{OUTCOME_MATURITY_LABEL} | "
        f"Candidates: {report.total_candidates} | Next-Day Complete: {report.completed_next_day_outcomes} | "
        f"5-Day Complete: {report.completed_five_day_outcomes} | Source: {report.source}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    if report.warnings:
        warning = QLabel(" | ".join(report.warnings))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
        layout.addWidget(warning)

    tabs = QTabWidget()
    tabs.addTab(build_outcome_maturity_summary_table(report, style), "Summary")
    tabs.addTab(build_outcome_maturity_gate_table(report, style), "Gates")
    layout.addWidget(tabs, 1)
    return panel


def build_outcome_maturity_summary_table(report: OutcomeMaturityReport, style: DataViewStyle) -> QTableWidget:
    rows = [
        ("Label", report.label),
        ("Total candidates", str(report.total_candidates)),
        ("Study-eligible candidates", str(report.study_eligible_candidates)),
        ("Completed next-day outcomes", str(report.completed_next_day_outcomes)),
        ("Completed five-day outcomes", str(report.completed_five_day_outcomes)),
        ("Pending next-day outcomes", str(report.pending_next_day_outcomes)),
        ("Pending five-day outcomes", str(report.pending_five_day_outcomes)),
        ("Completed outcome percentage", format_percent(report.completed_outcome_pct)),
        ("Pending outcome percentage", format_percent(report.pending_outcome_pct)),
        ("Earliest capture date", report.earliest_capture_date),
        ("Latest capture date", report.latest_capture_date),
        ("Earliest date with usable five-day outcomes", report.earliest_date_with_usable_five_day_outcomes),
        ("Latest date with pending five-day outcomes", report.latest_date_with_pending_five_day_outcomes),
        ("Warnings", " | ".join(report.warnings)),
        ("Readiness note", "Readiness monitoring only. No Opportunity Score, optimizer logic, or trading recommendation is generated."),
    ]
    table = QTableWidget(len(rows), 2)
    table.setHorizontalHeaderLabels(["Metric", "Value"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for row, (metric, value) in enumerate(rows):
        table.setItem(row, 0, QTableWidgetItem(metric))
        item = QTableWidgetItem(value)
        if metric == "Warnings" and value:
            item.setBackground(QBrush(QColor("#735f24")))
        table.setItem(row, 1, item)
    return table


def build_outcome_maturity_gate_table(report: OutcomeMaturityReport, style: DataViewStyle) -> QTableWidget:
    table = QTableWidget(max(1, len(report.gates)), 6)
    table.setHorizontalHeaderLabels(["Gate", "Status", "Current", "Required", "Reason", "Estimated Earliest Readiness"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not report.gates:
        values = ["No gates", "LOCKED", "0", "0", "No outcome rows found.", "unknown - no captures"]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, gate in enumerate(report.gates):
            values = [
                gate.name,
                gate.status,
                str(gate.current_count),
                str(gate.required_count),
                gate.reason,
                gate.estimated_earliest_readiness_date,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if gate.status == "LOCKED":
                    item.setBackground(QBrush(QColor("#7f2d2d")))
                elif gate.status == "DIAGNOSTIC":
                    item.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, item)
    table.resizeColumnsToContents()
    return table


def build_opportunity_research_panel(report: OpportunityResearchReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}{OPPORTUNITY_RESEARCH_LABEL} | "
        f"Candidates: {report.summary.candidate_count} | Completed: {report.summary.completed_outcome_count} | "
        f"Pending: {report.summary.pending_outcome_count} | Source: {report.source}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    if report.summary.completed_outcome_count < 30:
        insufficient = QLabel("Insufficient completed outcomes for conclusions.")
        insufficient.setWordWrap(True)
        insufficient.setStyleSheet("color: #fcd34d; font-weight: 800;")
        layout.addWidget(insufficient)

    if report.warnings:
        warning = QLabel(" | ".join(report.warnings))
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #fcd34d; font-weight: 700;")
        layout.addWidget(warning)

    tabs = QTabWidget()
    tabs.addTab(build_opportunity_summary_table(report, style), "Summary")
    tabs.addTab(build_opportunity_condition_table(report.condition_rows, style), "Conditions")
    tabs.addTab(build_opportunity_condition_table(report.best_performing_conditions, style), "Best Performing")
    tabs.addTab(build_opportunity_condition_table(report.worst_performing_conditions, style), "Worst Performing")
    tabs.addTab(build_opportunity_condition_table(report.most_pending_conditions, style), "Most Pending")
    tabs.addTab(build_opportunity_condition_table(report.highest_max_gain_conditions, style), "Highest Max Gain")
    tabs.addTab(build_opportunity_condition_table(report.highest_drawdown_conditions, style), "Highest Drawdown")
    tabs.addTab(build_opportunity_condition_table(report.combination_rows, style), "Combinations")
    layout.addWidget(tabs, 1)
    return panel


def build_opportunity_summary_table(report: OpportunityResearchReport, style: DataViewStyle) -> QTableWidget:
    summary = report.summary
    rows = [
        ("Label", report.label),
        ("Candidate count", str(summary.candidate_count)),
        ("Completed outcome count", str(summary.completed_outcome_count)),
        ("Pending outcome count", str(summary.pending_outcome_count)),
        ("Pending rate", format_percent((summary.pending_outcome_count / summary.candidate_count) * 100 if summary.candidate_count else None)),
        ("Average next-day return", format_percent(summary.average_next_day_return_pct)),
        ("Median next-day return", format_percent(summary.median_next_day_return_pct)),
        ("Average five-day return", format_percent(summary.average_five_day_return_pct)),
        ("Median five-day return", format_percent(summary.median_five_day_return_pct)),
        ("Average max gain", format_percent(summary.average_max_gain_pct)),
        ("Average max drawdown", format_percent(summary.average_max_drawdown_pct)),
        ("Win rate", format_percent(summary.win_rate_pct)),
        ("Best winner", summary.best_winner),
        ("Worst loser", summary.worst_loser),
        ("Warnings", " | ".join(report.warnings)),
        ("Research note", "Post-capture outcomes only. Research-only. Do not use for trading decisions yet."),
    ]
    table = QTableWidget(len(rows), 2)
    table.setHorizontalHeaderLabels(["Metric", "Value"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for row, (metric, value) in enumerate(rows):
        table.setItem(row, 0, QTableWidgetItem(metric))
        item = QTableWidgetItem(value)
        if metric == "Warnings" and value:
            item.setBackground(QBrush(QColor("#735f24")))
        table.setItem(row, 1, item)
    return table


def build_opportunity_condition_table(rows, style: DataViewStyle) -> QTableWidget:
    table = QTableWidget(max(1, len(rows)), 15)
    table.setHorizontalHeaderLabels(
        [
            "Dimension",
            "Condition",
            "Candidates",
            "Completed",
            "Pending",
            "Pending Rate",
            "Avg Next",
            "Median Next",
            "Avg 5-Day",
            "Median 5-Day",
            "Avg Max Gain",
            "Avg Max Drawdown",
            "Win Rate",
            "Best / Worst",
            "Warnings",
        ]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not rows:
        values = ["No rows", "", "0", "0", "0", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "Insufficient completed outcomes for conclusions."]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, item_summary in enumerate(rows):
            values = [
                item_summary.dimension,
                item_summary.condition,
                str(item_summary.candidate_count),
                str(item_summary.completed_count),
                str(item_summary.pending_count),
                format_percent(item_summary.pending_rate_pct),
                format_percent(item_summary.average_next_day_return_pct),
                format_percent(item_summary.median_next_day_return_pct),
                format_percent(item_summary.average_five_day_return_pct),
                format_percent(item_summary.median_five_day_return_pct),
                format_percent(item_summary.average_max_gain_pct),
                format_percent(item_summary.average_max_drawdown_pct),
                format_percent(item_summary.win_rate_pct),
                f"{item_summary.best_winner} / {item_summary.worst_loser}",
                " | ".join(item_summary.warnings),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if item_summary.warnings:
                    cell.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, cell)
    table.resizeColumnsToContents()
    return table


def build_outcome_summary_table(report: OutcomeExplorerReport, style: DataViewStyle) -> QTableWidget:
    summary = report.summary
    rows = [
        ("Label", report.label),
        ("Candidate count", str(summary.candidate_count)),
        ("Completed outcome count", str(summary.completed_outcome_count)),
        ("Pending outcome count", str(summary.pending_outcome_count)),
        ("Average next-day return", format_percent(summary.average_next_day_return_pct)),
        ("Median next-day return", format_percent(summary.median_next_day_return_pct)),
        ("Average five-day return", format_percent(summary.average_five_day_return_pct)),
        ("Median five-day return", format_percent(summary.median_five_day_return_pct)),
        ("Average max gain", format_percent(summary.average_max_gain_pct)),
        ("Average max drawdown", format_percent(summary.average_max_drawdown_pct)),
        ("Win rate", format_percent(summary.win_rate_pct)),
        ("Best winner", summary.best_winner),
        ("Worst loser", summary.worst_loser),
        ("Warnings", " | ".join(summary.warnings)),
        ("Post-capture data note", "Outcome values are labels from analysis-outcomes.csv, not capture-time facts."),
    ]
    table = QTableWidget(len(rows), 2)
    table.setHorizontalHeaderLabels(["Metric", "Value"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for row, (metric, value) in enumerate(rows):
        item = QTableWidgetItem(value)
        if metric == "Warnings" and value:
            item.setBackground(QBrush(QColor("#735f24")))
        table.setItem(row, 0, QTableWidgetItem(metric))
        table.setItem(row, 1, item)
    return table


def build_outcome_performance_table(rows, style: DataViewStyle, label: str) -> QTableWidget:
    table = QTableWidget(max(1, len(rows)), 13)
    table.setHorizontalHeaderLabels(
        [
            label,
            "Candidates",
            "Completed",
            "Pending",
            "Avg Next",
            "Median Next",
            "Avg 5-Day",
            "Median 5-Day",
            "Avg Max Gain",
            "Avg Max Drawdown",
            "Win Rate",
            "Best / Worst",
            "Warnings",
        ]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not rows:
        values = ["No rows", "0", "0", "0", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", "n/a", ""]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, item_summary in enumerate(rows):
            values = [
                item_summary.group,
                str(item_summary.candidate_count),
                str(item_summary.completed_count),
                str(item_summary.pending_count),
                format_percent(item_summary.average_next_day_return_pct),
                format_percent(item_summary.median_next_day_return_pct),
                format_percent(item_summary.average_five_day_return_pct),
                format_percent(item_summary.median_five_day_return_pct),
                format_percent(item_summary.average_max_gain_pct),
                format_percent(item_summary.average_max_drawdown_pct),
                format_percent(item_summary.win_rate_pct),
                f"{item_summary.best_winner} / {item_summary.worst_loser}",
                " | ".join(item_summary.warnings),
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if item_summary.warnings:
                    cell.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, cell)
    table.resizeColumnsToContents()
    return table


def build_outcome_candidate_table(report: OutcomeExplorerReport, style: DataViewStyle) -> QTableWidget:
    table = QTableWidget(max(1, len(report.candidates)), 18)
    table.setHorizontalHeaderLabels(
        [
            "Capture",
            "Ticker",
            "Score",
            "Bucket",
            "Regime",
            "Scanner",
            "Sector",
            "Industry",
            "Review",
            "Historical Cluster",
            "Catalyst Cluster",
            "Catalyst Confidence",
            "Purity",
            "Age Bucket",
            "Outcome Status",
            "Next",
            "5-Day",
            "Post-Capture Note",
        ]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not report.candidates:
        values = ["No candidates", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "Filters removed all outcome rows."]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, candidate in enumerate(report.candidates):
            values = [
                f"{candidate.capture_date} {candidate.session}",
                candidate.ticker,
                str(candidate.score),
                candidate.score_bucket,
                candidate.market_regime,
                candidate.scanner,
                candidate.sector,
                candidate.industry,
                candidate.review_status,
                candidate.historical_cluster,
                candidate.catalyst_cluster,
                f"{candidate.catalyst_confidence} {format_number(candidate.catalyst_confidence_score)}",
                format_percent(candidate.cluster_purity_pct),
                candidate.age_bucket,
                candidate.outcome_status,
                format_percent(candidate.next_day_return_pct),
                format_percent(candidate.five_day_return_pct),
                "post-capture label",
            ]
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if candidate.outcome_status != "complete":
                    cell.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, cell)
    table.resizeColumnsToContents()
    return table


def build_headline_event_table(report: HeadlineDedupReport, style: DataViewStyle) -> QTableWidget:
    table = QTableWidget(max(1, len(report.events)), 14)
    table.setHorizontalHeaderLabels(
        [
            "Event ID",
            "Cluster",
            "Duplicate Count",
            "Unique Sources",
            "Tickers",
            "Sources",
            "First Seen",
            "Latest Seen",
            "Earliest Published",
            "Timestamp Summary",
            "Confidence",
            "Representative Headline",
            "Notes",
            "Warnings",
        ]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not report.events:
        values = ["No events", "", "0", "0", "", "", "", "", "", "", "n/a", "", "", "No duplicate events matched the filters."]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, event in enumerate(report.events):
            values = [
                event.event_id,
                event.catalyst_cluster,
                str(event.duplicate_headline_count),
                str(event.unique_source_count),
                ", ".join(event.tickers),
                ", ".join(event.sources),
                event.first_seen_capture_time,
                event.latest_seen_capture_time,
                event.earliest_published_at or "unknown",
                ", ".join(f"{status}:{count}" for status, count in event.timestamp_status_summary.items()),
                f"{event.confidence} {event.confidence_score}",
                event.representative_headline,
                " | ".join(event.notes),
                " | ".join(event.warnings),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if event.warnings:
                    item.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, item)
    table.resizeColumnsToContents()
    return table


def build_source_reliability_table(report: HeadlineDedupReport, style: DataViewStyle) -> QTableWidget:
    table = QTableWidget(max(1, len(report.source_reliability)), 10)
    table.setHorizontalHeaderLabels(
        [
            "Source / Provider",
            "Headlines",
            "Exact %",
            "Unknown %",
            "Future %",
            "Invalid %",
            "Duplicate Rate",
            "Unique Events",
            "Avg Headlines/Event",
            "Warnings",
        ]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not report.source_reliability:
        values = ["No source rows", "0", "n/a", "n/a", "n/a", "n/a", "n/a", "0", "n/a", ""]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, summary in enumerate(report.source_reliability):
            values = [
                summary.source,
                str(summary.total_headlines),
                format_percent(summary.exact_pct),
                format_percent(summary.unknown_pct),
                format_percent(summary.future_pct),
                format_percent(summary.invalid_pct),
                format_percent(summary.duplicate_rate_pct),
                str(summary.unique_event_count),
                format_number(summary.average_headlines_per_event),
                " | ".join(summary.warnings),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if summary.warnings:
                    item.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, item)
    table.resizeColumnsToContents()
    return table


def build_dedup_impact_table(summaries, style: DataViewStyle, label: str) -> QTableWidget:
    table = QTableWidget(max(1, len(summaries)), 6)
    table.setHorizontalHeaderLabels(
        [label, "Raw Headlines", "Deduped Events", "Duplicate Rate", "Top Duplicated Stories", "Warnings"]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not summaries:
        values = ["No impact rows", "0", "0", "n/a", "", ""]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, summary in enumerate(summaries):
            values = [
                summary.name,
                str(summary.raw_headline_count),
                str(summary.deduped_event_count),
                format_percent(summary.duplicate_rate_pct),
                " | ".join(summary.top_duplicated_stories),
                " | ".join(summary.warnings),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if summary.warnings:
                    item.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, item)
    table.resizeColumnsToContents()
    return table


def build_catalyst_age_audit_table(report: CatalystAgeAuditReport, style: DataViewStyle) -> QTableWidget:
    rows = [
        ("Total headlines", str(report.total_headlines)),
        ("Exact timestamp count", str(report.exact_timestamp_count)),
        ("Date-only count", str(report.date_only_count)),
        ("Estimated count", str(report.estimated_count)),
        ("Unknown timestamp count", str(report.unknown_timestamp_count)),
        ("Future timestamp count", str(report.future_timestamp_count)),
        ("Invalid timestamp count", str(report.invalid_timestamp_count)),
        ("Affected tickers", ", ".join(report.affected_tickers) or "none"),
        ("Affected clusters", ", ".join(report.affected_clusters) or "none"),
    ]
    rows.extend((f"Age bucket {bucket}", str(report.age_bucket_distribution.get(bucket, 0))) for bucket in AGE_BUCKETS)
    table = QTableWidget(len(rows), 2)
    table.setHorizontalHeaderLabels(["Metric", "Value"])
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    for row, (metric, value) in enumerate(rows):
        table.setItem(row, 0, QTableWidgetItem(metric))
        table.setItem(row, 1, QTableWidgetItem(value))
    return table


def build_catalyst_age_summary_table(summaries, style: DataViewStyle, label: str) -> QTableWidget:
    table = QTableWidget(max(1, len(summaries)), 9)
    table.setHorizontalHeaderLabels(
        [label, "Headlines", "Tickers", "Exact", "Unknown", "Future", "Invalid", "Avg Age", "Buckets"]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not summaries:
        values = ["No data", "0", "", "0", "0", "0", "0", "n/a", ""]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, summary in enumerate(summaries):
            bucket_text = ", ".join(
                f"{bucket}:{count}"
                for bucket, count in summary.bucket_distribution.items()
                if count
            )
            values = [
                summary.name,
                str(summary.headline_count),
                ", ".join(summary.tickers[:12]),
                str(summary.exact_count),
                str(summary.unknown_count),
                str(summary.future_count),
                str(summary.invalid_count),
                format_age_hours(summary.average_age_hours),
                bucket_text,
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
    table.resizeColumnsToContents()
    return table


def build_catalyst_age_detail_table(report: CatalystAgeAuditReport, style: DataViewStyle) -> QTableWidget:
    table = QTableWidget(max(1, len(report.records)), 14)
    table.setHorizontalHeaderLabels(
        [
            "Ticker",
            "Cluster",
            "Capture",
            "Published",
            "Timestamp Status",
            "Confidence",
            "Age",
            "Bucket",
            "Score",
            "Review",
            "Outcome",
            "Max Gain",
            "Max Drawdown",
            "Headline",
        ]
    )
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    table.horizontalHeader().setStyleSheet(style.header_stylesheet)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    if not report.records:
        values = ["No headlines", "", "", "", "", "", "", "", "", "", "", "", "", ""]
        for column, value in enumerate(values):
            table.setItem(0, column, QTableWidgetItem(value))
    else:
        for row, record in enumerate(report.records):
            values = [
                record.ticker,
                record.catalyst_cluster,
                record.capture_timestamp,
                record.published_at or "unknown",
                record.timestamp_status,
                record.timestamp_confidence,
                format_age_hours(record.age_at_capture_hours),
                record.age_bucket,
                str(record.score),
                record.review_status,
                record.outcome_status,
                format_percent(record.max_gain_pct),
                format_percent(record.max_drawdown_pct),
                record.headline,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if record.timestamp_status in {"FUTURE_TIMESTAMP", "INVALID_TIMESTAMP"}:
                    item.setBackground(QBrush(QColor("#6d3030")))
                elif record.timestamp_status == "UNKNOWN_TIMESTAMP":
                    item.setBackground(QBrush(QColor("#735f24")))
                table.setItem(row, column, item)
    table.resizeColumnsToContents()
    return table


def format_catalyst_cluster_detail_html(cluster) -> str:
    warnings = "".join(f"<li>{escape(warning)}</li>" for warning in cluster.warnings) or "<li>No cluster warnings.</li>"
    rows = []
    for headline in cluster.headlines:
        url = f"<a href='{escape(headline.url)}'>{escape(headline.url)}</a>" if headline.url else ""
        rows.append(
            "<tr>"
            f"<td>{escape(headline.ticker)}</td>"
            f"<td>{escape(headline.capture_time)}</td>"
            f"<td>{escape(headline.source)}</td>"
            f"<td>{escape(headline.timestamp_status)}</td>"
            f"<td>{escape(headline.classification_confidence)} {escape(str(headline.classification_confidence_score))}</td>"
            f"<td>{escape(headline.classification_rule)}</td>"
            f"<td>{escape(headline.classification_match_type)}</td>"
            f"<td>{escape(headline.fallback_reason)}</td>"
            f"<td>{escape(format_age_hours(headline.headline_age_hours))}</td>"
            f"<td>{escape(headline.freshness_label)}</td>"
            f"<td>{escape(str(headline.score))}</td>"
            f"<td>{escape(headline.review_status)}</td>"
            f"<td>{escape(headline.outcome_status)}</td>"
            f"<td>{escape(format_percent(headline.max_gain_pct))}</td>"
            f"<td>{escape(format_percent(headline.max_drawdown_pct))}</td>"
            f"<td>{escape(headline.headline)}</td>"
            f"<td>{url}</td>"
            "</tr>"
        )
    return f"""
    <html>
    <body style="font-family: Segoe UI, Arial; color:#e7edf4; background:#0b1118;">
      <h2>{escape(CATALYST_RESEARCH_LABEL)}</h2>
      <h3>{escape(cluster.name)}</h3>
      <p>
        Headlines: <b>{cluster.headline_count}</b> |
        Candidates: <b>{cluster.candidate_count}</b> |
        Unique tickers: <b>{cluster.unique_ticker_count}</b> |
        Date range: <b>{escape(cluster.date_range)}</b>
      </p>
      <p>
        Confidence: <b>{escape(cluster.dominant_confidence)} {escape(format_number(cluster.average_confidence_score))}</b> |
        Purity: <b>{escape(format_percent(cluster.purity_pct))}</b> |
        Explicit: <b>{cluster.explicit_match_count}</b> |
        Fallback: <b>{cluster.fallback_match_count}</b> |
        Exact timestamps: <b>{escape(format_percent(cluster.timestamp_quality.exact_pct))}</b> |
        Unknown timestamps: <b>{escape(format_percent(cluster.timestamp_quality.unknown_pct))}</b> |
        Future timestamps: <b>{escape(format_percent(cluster.timestamp_quality.future_pct))}</b>
      </p>
      <p style="color:#9fb0c2;">
        Common rules: {escape(', '.join(cluster.common_rules) or 'n/a')}<br>
        Fallback reasons: {escape(' | '.join(cluster.fallback_reasons) or 'n/a')}
      </p>
      <p style="color:#9fb0c2;">
        Detail rows use stored capture headlines only. Outcomes are post-capture labels and are not capture-time facts.
        Missing timestamps remain unknown; future timestamps are excluded from clustering.
      </p>
      <h3>Warnings</h3>
      <ul style="color:#fcd34d;font-weight:700;">{warnings}</ul>
      <h3>Matching Stored Headlines</h3>
      <table cellspacing="0" cellpadding="5" style="border-collapse:collapse;width:100%;">
        <tr style="background:#182536;">
          <th align="left">Ticker</th>
          <th align="left">Capture Time</th>
          <th align="left">Source</th>
          <th align="left">Timestamp</th>
          <th align="left">Confidence</th>
          <th align="left">Rule</th>
          <th align="left">Match</th>
          <th align="left">Fallback Reason</th>
          <th align="left">Age</th>
          <th align="left">Freshness</th>
          <th align="left">Score</th>
          <th align="left">Review</th>
          <th align="left">Outcome</th>
          <th align="left">Max Gain</th>
          <th align="left">Max Drawdown</th>
          <th align="left">Headline</th>
          <th align="left">URL</th>
        </tr>
        {''.join(rows)}
      </table>
    </body>
    </html>
    """


def format_age_hours(value: float | None) -> str:
    return "unknown" if value is None else f"{value:.2f}h"


def format_number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def build_recommendation_panel(report: RecommendationReport, style: DataViewStyle) -> QWidget:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)

    status = QLabel(
        f"{style.chart_prefix}Locked Research Notes | "
        f"Completed Rows: {report.completed_rows} | Minimum Rows: {report.minimum_rows} | {report.status}"
    )
    status.setObjectName("criteriaLabel")
    status.setWordWrap(True)
    layout.addWidget(status)

    table = QTableWidget(0, 7)
    table.setHorizontalHeaderLabels(
        ["Regime", "Bucket", "Rows", "5-Day Avg", "Win Rate", "Locked Note", "Rationale"]
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
#gatewayEyebrow {
    color: #e0b84a;
    font-weight: 800;
    font-size: 11pt;
}
#gatewayTitle {
    color: #fff2c2;
    font-size: 27pt;
    font-weight: 800;
}
#gatewaySubtitle {
    color: #cbd8e6;
    font-size: 12pt;
}
QGroupBox#gatewayChoiceCard {
    border: 1px solid #7a5c1d;
    background: #141f2c;
    padding: 16px;
}
#gatewaySafetyLabel, #gatewaySafetyFooter, #argusRiskWarningLabel, #argusOrderConsoleWarning {
    background: #341b1f;
    border: 1px solid #9a333f;
    border-radius: 5px;
    color: #ffd7dc;
    font-weight: 700;
    padding: 7px;
}
QPushButton#gatewayStevenDeskButton {
    background: #b98d2b;
    color: #101820;
    font-size: 16pt;
    font-weight: 800;
}
QPushButton#gatewayArgusMachineButton {
    background: #9b2f38;
    color: #fff4f4;
    font-size: 16pt;
    font-weight: 800;
}
#argusMachineTitle {
    background: #171f2a;
    border: 1px solid #7a5c1d;
    border-radius: 6px;
    color: #fff2c2;
    font-size: 15pt;
    font-weight: 800;
    padding: 10px;
}
#argusStatusCard {
    background: #101820;
    border: 1px solid #7a5c1d;
    border-radius: 5px;
    color: #f6e4a4;
    font-weight: 700;
    padding: 8px;
}
QGroupBox#argusTop5Panel, QGroupBox#argusWorkbenchPanel, QGroupBox#argusTradePlanLadderPanel,
QGroupBox#argusRiskGovernorPanel, QGroupBox#argusOrderConsolePanel, QGroupBox#argusMachineLogPanel {
    border: 1px solid #384a5c;
    background: #131f2b;
}
#argusWorkbenchTicker {
    background: #2b1a1f;
    border: 1px solid #9b2f38;
    border-radius: 5px;
    color: #ffe2e6;
    font-weight: 800;
    padding: 8px;
}
#argusTradePlanEmptyState {
    background: #1e2e3f;
    border: 1px solid #53677d;
    border-radius: 5px;
    color: #dce8f5;
    font-weight: 700;
    padding: 8px;
}
QPushButton[lockedOrderControl="true"] {
    background: #4b2027;
    color: #ffcdd3;
    border: 1px solid #8d2f3a;
}
"""


def main() -> None:
    app = QApplication(sys.argv)
    window = MomentumHunterWindow()
    window.show()
    sys.exit(app.exec())
