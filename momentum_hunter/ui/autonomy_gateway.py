from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from momentum_hunter.autonomy.broker import FakeBrokerAdapter
from momentum_hunter.autonomy.ledger import ExecutionLedger, render_machine_log
from momentum_hunter.autonomy.risk_governor import RiskGovernorResult, SIMULATION_MODE
from momentum_hunter.autonomy.simulation import SimulationLabEngine
from momentum_hunter.autonomy.view_models import Top5CandidatePlan, build_top5_candidate_plans
from momentum_hunter.monitor_targets import latest_trade_report_path
from momentum_hunter.ui.trade_plan_ladder import TradePlanLadderWidget


def build_gateway_page(window: Any) -> QWidget:
    page = QWidget()
    page.setObjectName("argusGatewayPage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(26, 26, 26, 26)
    layout.setSpacing(18)

    eyebrow = QLabel("MOMENTUM HUNTER")
    eyebrow.setObjectName("gatewayEyebrow")
    layout.addWidget(eyebrow)

    title = QLabel("Choose the operating room")
    title.setObjectName("gatewayTitle")
    title.setWordWrap(True)
    layout.addWidget(title)

    subtitle = QLabel(
        "Steven Desk preserves the human-guided dashboard. Argus Machine opens the safe autonomous console shell. "
        "Simulation only. FakeBroker only. Live trading locked."
    )
    subtitle.setObjectName("gatewaySubtitle")
    subtitle.setWordWrap(True)
    layout.addWidget(subtitle)

    choice_row = QWidget()
    choice_layout = QHBoxLayout(choice_row)
    choice_layout.setContentsMargins(0, 0, 0, 0)
    choice_layout.setSpacing(16)
    choice_layout.addWidget(
        build_gateway_choice(
            "Steven Desk",
            "Human-guided momentum operations",
            "Current dashboard, Daily Workflow, watchlist discipline, research, replay, and health checks.",
            "Human review remains in charge.",
            window.open_steven_desk,
        )
    )
    choice_layout.addWidget(
        build_gateway_choice(
            "Argus Machine",
            "Autonomous planning, simulation, and execution control",
            "Machine status, Top 5 plan candidates, Trade Plan Ladder, Risk Governor, simulation-only controls, and Machine Log.",
            "Simulation Lab. FakeBroker only. Paper and live trading locked.",
            window.open_argus_machine_console,
        )
    )
    layout.addWidget(choice_row)
    layout.addStretch(1)

    footer = QLabel("Gateway state: safe startup shell. Orders cannot be paper-traded, live-traded, or routed from here.")
    footer.setObjectName("gatewaySafetyFooter")
    footer.setWordWrap(True)
    layout.addWidget(footer)
    return page


def build_gateway_choice(
    title: str,
    subtitle: str,
    detail: str,
    safety: str,
    callback: Callable[[], None],
) -> QWidget:
    card = QGroupBox(title)
    card.setObjectName("gatewayChoiceCard")
    card.setMinimumHeight(250)
    layout = QVBoxLayout(card)
    layout.setSpacing(10)

    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName(f"gateway{title.replace(' ', '')}Subtitle")
    subtitle_label.setWordWrap(True)
    layout.addWidget(subtitle_label)

    detail_label = QLabel(detail)
    detail_label.setObjectName("criteriaLabel")
    detail_label.setWordWrap(True)
    layout.addWidget(detail_label)

    safety_label = QLabel(safety)
    safety_label.setObjectName("gatewaySafetyLabel")
    safety_label.setWordWrap(True)
    layout.addWidget(safety_label)

    button = QPushButton(title)
    button.setObjectName(f"gateway{title.replace(' ', '')}Button")
    button.setMinimumHeight(72)
    button.setToolTip(subtitle)
    button.clicked.connect(callback)
    layout.addWidget(button)
    layout.addStretch(1)
    return card


def build_argus_machine_console_page(window: Any) -> QWidget:
    ensure_argus_machine_runtime(window)
    page = QWidget()
    page.setObjectName("argusMachineConsolePage")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)

    header_row = QWidget()
    header_layout = QHBoxLayout(header_row)
    header_layout.setContentsMargins(0, 0, 0, 0)
    header_layout.setSpacing(10)
    title = QLabel(
        "ARGUS MACHINE\n"
        "Structured planning and simulation console. FakeBroker only. Paper and live trading locked."
    )
    title.setObjectName("argusMachineTitle")
    title.setWordWrap(True)
    header_layout.addWidget(title, 1)
    gateway_button = QPushButton("Gateway")
    gateway_button.setObjectName("argusMachineGatewayButton")
    gateway_button.setToolTip("Return to the startup gateway.")
    gateway_button.clicked.connect(window.show_gateway)
    desk_button = QPushButton("Steven Desk")
    desk_button.setObjectName("argusMachineStevenDeskButton")
    desk_button.setToolTip("Open the existing human-guided dashboard.")
    desk_button.clicked.connect(window.open_steven_desk)
    header_layout.addWidget(gateway_button)
    header_layout.addWidget(desk_button)
    layout.addWidget(header_row)

    layout.addWidget(build_argus_machine_status_bar(window))

    body = QSplitter(Qt.Orientation.Horizontal)
    left = QWidget()
    left_layout = QVBoxLayout(left)
    left_layout.setContentsMargins(0, 0, 0, 0)
    left_layout.setSpacing(10)
    left_layout.addWidget(build_argus_top5_panel(window), 4)
    left_layout.addWidget(build_argus_workbench_panel(window), 2)
    body.addWidget(left)

    right = QWidget()
    right_layout = QVBoxLayout(right)
    right_layout.setContentsMargins(0, 0, 0, 0)
    right_layout.setSpacing(10)
    right_layout.addWidget(build_argus_trade_plan_ladder_panel(window), 2)
    right_layout.addWidget(build_argus_risk_governor_panel(window))
    right_layout.addWidget(build_argus_order_console_panel(window))
    body.addWidget(right)
    body.setStretchFactor(0, 2)
    body.setStretchFactor(1, 3)
    layout.addWidget(body, 1)

    layout.addWidget(build_argus_machine_log_panel(window))
    refresh_argus_machine_console(window)
    return page


def ensure_argus_machine_runtime(window: Any) -> None:
    if not hasattr(window, "argus_execution_ledger"):
        window.argus_execution_ledger = ExecutionLedger()
    if not hasattr(window, "argus_fake_broker"):
        window.argus_fake_broker = FakeBrokerAdapter()
    window.argus_simulation_engine = SimulationLabEngine(
        adapter=window.argus_fake_broker,
        ledger=window.argus_execution_ledger,
    )
    if not hasattr(window, "argus_selected_candidate_plan"):
        window.argus_selected_candidate_plan = None


def build_argus_machine_status_bar(window: Any) -> QWidget:
    box = QGroupBox("Machine Status Bar")
    box.setObjectName("argusMachineStatusBar")
    layout = QGridLayout(box)
    layout.setSpacing(8)
    statuses = [
        ("Mode", SIMULATION_MODE),
        ("Broker", "FakeBroker only"),
        ("Order Ability", "Simulated only"),
        ("Risk Governor", "Select candidate"),
        ("Live Trading", "Locked"),
        ("Kill Switch", "Available"),
    ]
    window.argus_machine_status_labels = {}
    for column, (label, value) in enumerate(statuses):
        card = QLabel(f"{label}\n{value}")
        card.setObjectName("argusStatusCard")
        card.setWordWrap(True)
        layout.addWidget(card, 0, column)
        window.argus_machine_status_labels[label] = card
    return box


def build_argus_top5_panel(window: Any) -> QWidget:
    box = QGroupBox("Top 5 Trade Plan Candidates")
    box.setObjectName("argusTop5Panel")
    layout = QVBoxLayout(box)
    layout.setSpacing(8)
    window.argus_top5_note_label = QLabel(
        "Machine-plan candidates only; not approved trades. Click a ticker to populate the ladder."
    )
    window.argus_top5_note_label.setObjectName("criteriaLabel")
    window.argus_top5_note_label.setWordWrap(True)
    window.argus_top5_note_label.setMaximumHeight(48)
    layout.addWidget(window.argus_top5_note_label)

    window.argus_top5_empty_label = QLabel("")
    window.argus_top5_empty_label.setObjectName("argusTop5EmptyState")
    window.argus_top5_empty_label.setWordWrap(True)
    window.argus_top5_empty_label.hide()
    layout.addWidget(window.argus_top5_empty_label)

    window.argus_top5_table = QTableWidget(0, 4)
    window.argus_top5_table.setObjectName("argusTop5Table")
    window.argus_top5_table.setHorizontalHeaderLabels(["Ticker", "Setup", "Plan", "Gate"])
    window.argus_top5_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    window.argus_top5_table.verticalHeader().setVisible(False)
    window.argus_top5_table.verticalHeader().setDefaultSectionSize(28)
    window.argus_top5_table.setWordWrap(False)
    window.argus_top5_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    window.argus_top5_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    layout.addWidget(window.argus_top5_table, 1)
    window.argus_candidate_buttons = []
    window.argus_candidate_plans = []
    return box


def build_argus_workbench_panel(window: Any) -> QWidget:
    box = QGroupBox("Selected Candidate Workbench")
    box.setObjectName("argusWorkbenchPanel")
    layout = QGridLayout(box)
    layout.setSpacing(8)

    window.argus_workbench_ticker_label = QLabel("Selected ticker: none")
    window.argus_workbench_ticker_label.setObjectName("argusWorkbenchTicker")
    window.argus_workbench_ticker_label.setWordWrap(True)
    window.argus_workbench_summary_label = QLabel("Setup summary: select a Top 5 Trade Plan Candidate.")
    window.argus_workbench_summary_label.setWordWrap(True)
    window.argus_workbench_catalyst_label = QLabel("Catalyst: waiting for candidate selection.")
    window.argus_workbench_catalyst_label.setWordWrap(True)
    window.argus_workbench_chart_label = QLabel("Chart context: waiting for candidate selection.")
    window.argus_workbench_chart_label.setWordWrap(True)
    window.argus_workbench_plan_status_label = QLabel("Plan status: no TradePlan selected.")
    window.argus_workbench_plan_status_label.setWordWrap(True)

    labels = [
        window.argus_workbench_ticker_label,
        window.argus_workbench_summary_label,
        window.argus_workbench_catalyst_label,
        window.argus_workbench_chart_label,
        window.argus_workbench_plan_status_label,
    ]
    for row, label in enumerate(labels):
        label.setObjectName(label.objectName() or "criteriaLabel")
        layout.addWidget(label, row, 0)
    return box


def build_argus_trade_plan_ladder_panel(window: Any) -> QWidget:
    widget = TradePlanLadderWidget()
    window.argus_ladder_widget = widget
    window.argus_ladder_empty_label = widget.empty_label
    window.argus_ladder_table = widget.table
    return widget


def build_argus_risk_governor_panel(window: Any) -> QWidget:
    box = QGroupBox("Risk Governor - Simulation Gate")
    box.setObjectName("argusRiskGovernorPanel")
    layout = QVBoxLayout(box)
    window.argus_risk_warning_label = QLabel(
        "Select a TradePlan candidate to see current simulation gate status. This is not paper or live permission."
    )
    window.argus_risk_warning_label.setObjectName("argusRiskWarningLabel")
    window.argus_risk_warning_label.setWordWrap(True)
    layout.addWidget(window.argus_risk_warning_label)

    window.argus_risk_gate_table = QTableWidget(0, 3)
    window.argus_risk_gate_table.setObjectName("argusRiskGateTable")
    window.argus_risk_gate_table.setHorizontalHeaderLabels(["Gate", "State", "Reason"])
    window.argus_risk_gate_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    window.argus_risk_gate_table.verticalHeader().setVisible(False)
    window.argus_risk_gate_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    layout.addWidget(window.argus_risk_gate_table)
    return box


def build_argus_order_console_panel(window: Any) -> QWidget:
    box = QGroupBox("Simulation Order Console - Locked From Paper/Live")
    box.setObjectName("argusOrderConsolePanel")
    layout = QVBoxLayout(box)
    window.argus_order_console_note = QLabel(
        "Simulation only. FakeBroker can preview and submit fake orders into the ledger. Paper and live controls are locked."
    )
    window.argus_order_console_note.setObjectName("argusOrderConsoleWarning")
    window.argus_order_console_note.setWordWrap(True)
    layout.addWidget(window.argus_order_console_note)

    button_row = QWidget()
    button_layout = QHBoxLayout(button_row)
    button_layout.setContentsMargins(0, 0, 0, 0)
    window.argus_run_simulation_button = QPushButton("Run Simulation Only")
    window.argus_run_simulation_button.setEnabled(False)
    window.argus_run_simulation_button.setToolTip("Select a candidate with no blocked Risk Governor gates.")
    window.argus_run_simulation_button.clicked.connect(lambda: run_argus_simulation(window))
    window.argus_submit_paper_button = QPushButton("Paper Order Locked")
    window.argus_submit_live_button = QPushButton("Live Order Locked")
    locked_buttons = [window.argus_submit_paper_button, window.argus_submit_live_button]
    button_layout.addWidget(window.argus_run_simulation_button)
    for button in locked_buttons:
        button.setEnabled(False)
        button.setProperty("lockedOrderControl", True)
        button.setToolTip("Locked: no paper or live broker path is connected.")
        button_layout.addWidget(button)
    window.argus_preview_order_button = window.argus_run_simulation_button
    window.argus_submit_live_button.setObjectName("argusSubmitLiveOrderButton")
    window.argus_submit_live_button.setToolTip("Locked: live trading requires separate Steven approval and broker safety gates.")
    layout.addWidget(button_row)

    window.argus_simulation_table = QTableWidget(0, 5)
    window.argus_simulation_table.setObjectName("argusSimulationOrderTable")
    window.argus_simulation_table.setHorizontalHeaderLabels(["Order", "Ticker", "Status", "Qty", "Reason"])
    window.argus_simulation_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    window.argus_simulation_table.verticalHeader().setVisible(False)
    window.argus_simulation_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    layout.addWidget(window.argus_simulation_table)
    return box


def build_argus_machine_log_panel(window: Any) -> QWidget:
    box = QGroupBox("Machine Log")
    box.setObjectName("argusMachineLogPanel")
    layout = QVBoxLayout(box)
    window.argus_machine_log = QPlainTextEdit()
    window.argus_machine_log.setObjectName("argusMachineLog")
    window.argus_machine_log.setReadOnly(True)
    window.argus_machine_log.setMaximumHeight(120)
    if not window.argus_execution_ledger.events:
        window.argus_execution_ledger.record(
            event_type="machine_loaded",
            mode=SIMULATION_MODE,
            requested_action="machine_loaded",
            result="ready",
            broker_adapter="FakeBrokerAdapter",
            reason="Argus Machine loaded. FakeBroker simulation only. Live trading locked.",
        )
    render_argus_machine_log(window)
    layout.addWidget(window.argus_machine_log)
    return box


def refresh_argus_machine_console(window: Any) -> None:
    ensure_argus_machine_runtime(window)
    report_path = latest_trade_report_path()
    plans = build_top5_candidate_plans(
        report_path=report_path,
        candidates=getattr(window, "candidates", []),
        limit=5,
    )
    window.argus_candidate_plans = plans
    window.argus_candidate_buttons = []
    if plans:
        source = plans[0].source_name
        window.argus_top5_note_label.setText(
            f"Top 5 from {source}; machine-plan candidates, not approved trades."
        )
        window.argus_top5_empty_label.hide()
        window.argus_top5_table.show()
        window.argus_top5_table.setRowCount(len(plans))
        for row, candidate in enumerate(plans):
            button = QPushButton(f"{candidate.rank}. {candidate.ticker}")
            button.setObjectName(f"argusCandidateButton_{candidate.ticker}")
            button.setProperty("argusTicker", candidate.ticker)
            button.setToolTip(candidate.button_text)
            button.setMinimumHeight(24)
            button.setMaximumHeight(26)
            button.clicked.connect(lambda _checked=False, item=candidate: select_argus_machine_candidate(window, item))
            window.argus_top5_table.setCellWidget(row, 0, button)
            values = [candidate.setup_label, candidate.plan_status, candidate.gate_state]
            for column, value in enumerate(values, 1):
                window.argus_top5_table.setItem(row, column, QTableWidgetItem(value))
            window.argus_candidate_buttons.append(button)
    else:
        window.argus_top5_table.setRowCount(0)
        window.argus_top5_table.hide()
        window.argus_top5_empty_label.setText(
            "No Trade Plan Candidates available. Generate a trade-planning report or load scanner candidates first."
        )
        window.argus_top5_empty_label.show()
        clear_argus_trade_plan_ladder(window)
        render_argus_risk_result(window, None)
        window.argus_run_simulation_button.setEnabled(False)
    render_simulation_orders(window)
    render_argus_machine_log(window)


def clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def clear_argus_trade_plan_ladder(window: Any) -> None:
    window.argus_ladder_widget.clear()


def select_argus_machine_candidate(window: Any, candidate: Top5CandidatePlan) -> None:
    window.argus_selected_candidate_plan = candidate
    window.argus_workbench_ticker_label.setText(f"Selected ticker: {candidate.ticker}")
    window.argus_workbench_summary_label.setText(f"Setup summary: {candidate.source_summary}")
    window.argus_workbench_catalyst_label.setText(f"Catalyst: {candidate.catalyst_summary}")
    window.argus_workbench_chart_label.setText(f"Chart context: {candidate.chart_summary}")
    window.argus_workbench_plan_status_label.setText(
        f"Plan status: {candidate.plan_status}; Risk Governor: {candidate.risk_result.status}"
    )
    window.argus_ladder_widget.render_candidate(candidate)
    render_argus_risk_result(window, candidate.risk_result)
    window.argus_execution_ledger.record(
        event_type="candidate_selected",
        mode=SIMULATION_MODE,
        ticker=candidate.ticker,
        trade_plan_id=candidate.trade_plan_id,
        risk_result_id=candidate.risk_result.result_id,
        broker_adapter="FakeBrokerAdapter",
        requested_action="candidate_selected",
        result=candidate.plan_status,
        reason=f"Risk Governor status: {candidate.risk_result.status}",
        payload={"source": candidate.source_name, "composite_score": candidate.composite_score},
    )
    window.argus_execution_ledger.record(
        event_type="risk_gate_evaluated",
        mode=SIMULATION_MODE,
        ticker=candidate.ticker,
        trade_plan_id=candidate.trade_plan_id,
        risk_result_id=candidate.risk_result.result_id,
        broker_adapter="FakeBrokerAdapter",
        requested_action="risk_gate_evaluated",
        result=candidate.risk_result.status,
        reason=" | ".join(candidate.risk_result.reasons),
    )
    can_simulate = candidate.risk_result.allows_simulation
    window.argus_run_simulation_button.setEnabled(can_simulate)
    window.argus_run_simulation_button.setToolTip(
        "Run this TradePlan through FakeBroker simulation."
        if can_simulate
        else "Simulation blocked by current Risk Governor gates."
    )
    update_status_card(window, "Risk Governor", candidate.risk_result.status)
    render_argus_machine_log(window)


def render_argus_risk_result(window: Any, result: RiskGovernorResult | None) -> None:
    if result is None:
        window.argus_risk_warning_label.setText(
            "Select a TradePlan candidate to see current simulation gate status. This is not paper or live permission."
        )
        window.argus_risk_gate_table.setRowCount(0)
        return
    window.argus_risk_warning_label.setText(
        f"{result.ticker}: {result.status}. Simulation-only gate; paper and live remain locked."
    )
    window.argus_risk_gate_table.setRowCount(len(result.gates))
    for row, gate in enumerate(result.gates):
        for column, value in enumerate([gate.name, gate.state, gate.reason]):
            window.argus_risk_gate_table.setItem(row, column, QTableWidgetItem(value))


def run_argus_simulation(window: Any) -> None:
    candidate = getattr(window, "argus_selected_candidate_plan", None)
    if candidate is None:
        return
    result = window.argus_simulation_engine.run_candidate(candidate)
    render_simulation_orders(window)
    render_argus_machine_log(window)
    update_status_card(window, "Order Ability", f"Simulation {result.status}")


def render_simulation_orders(window: Any) -> None:
    orders = window.argus_fake_broker.list_orders() if hasattr(window, "argus_fake_broker") else []
    window.argus_simulation_table.setRowCount(len(orders))
    for row, order in enumerate(orders):
        values = [order.order_id, order.ticker, order.status, str(order.quantity), order.reason]
        for column, value in enumerate(values):
            window.argus_simulation_table.setItem(row, column, QTableWidgetItem(value))


def render_argus_machine_log(window: Any) -> None:
    if not hasattr(window, "argus_machine_log"):
        return
    window.argus_machine_log.setPlainText(render_machine_log(window.argus_execution_ledger.events))


def update_status_card(window: Any, label: str, value: str) -> None:
    card = getattr(window, "argus_machine_status_labels", {}).get(label)
    if card is not None:
        card.setText(f"{label}\n{value}")
