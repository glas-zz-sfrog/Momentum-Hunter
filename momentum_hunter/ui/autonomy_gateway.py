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


ARGUS_MACHINE_PLACEHOLDER_CANDIDATES: list[dict[str, str]] = [
    {
        "ticker": "NVDA",
        "setup": "Opening drive continuation",
        "status": "Draft plan",
        "gate": "Preview only / live locked",
        "summary": "Placeholder setup for a high-liquidity momentum continuation candidate.",
        "catalyst": "Demo catalyst: earnings strength placeholder, not live research.",
        "chart": "Demo chart: trend continuation placeholder.",
        "plan_status": "Machine draft incomplete; Risk Governor preview only.",
        "entry_trigger": "Break and hold above demo opening range",
        "entry_limit": "Demo limit: prior high + 0.5%",
        "stop": "Demo invalidation: loses VWAP and opening range low",
        "target_1": "Demo target 1: +1R",
        "target_2": "Demo target 2: +2R",
        "target_3": "Demo target 3: trend extension",
        "trailing_rule": "Demo trail: below rising 9 EMA after Target 1",
        "position_size": "Not sized",
        "max_risk": "Not approved",
        "risk_reward": "Preview only",
    },
    {
        "ticker": "AMD",
        "setup": "Relative strength pullback",
        "status": "Needs risk check",
        "gate": "Stop required",
        "summary": "Placeholder setup for a pullback that still needs complete risk fields.",
        "catalyst": "Demo catalyst: sector strength placeholder.",
        "chart": "Demo chart: higher-low pullback placeholder.",
        "plan_status": "Waiting on stop and max-risk discipline.",
        "entry_trigger": "Reclaim demo pivot with volume confirmation",
        "entry_limit": "Demo limit: pivot reclaim",
        "stop": "Demo invalidation: lower-low under pullback base",
        "target_1": "Demo target 1: prior intraday high",
        "target_2": "Demo target 2: measured move",
        "target_3": "Demo target 3: stretch target",
        "trailing_rule": "Demo trail: move stop after Target 1",
        "position_size": "Not sized",
        "max_risk": "Missing",
        "risk_reward": "Needs check",
    },
    {
        "ticker": "PLTR",
        "setup": "Catalyst gap watch",
        "status": "Simulation candidate",
        "gate": "Broker mode locked",
        "summary": "Placeholder setup for a catalyst gap candidate in simulation-only mode.",
        "catalyst": "Demo catalyst: headline momentum placeholder.",
        "chart": "Demo chart: gap-and-hold placeholder.",
        "plan_status": "Simulation-ready only; broker mode is locked.",
        "entry_trigger": "Hold above demo gap support",
        "entry_limit": "Demo limit: first pullback",
        "stop": "Demo invalidation: gap support failure",
        "target_1": "Demo target 1: opening high retest",
        "target_2": "Demo target 2: gap extension",
        "target_3": "Demo target 3: runner only",
        "trailing_rule": "Demo trail: prior candle low after Target 2",
        "position_size": "Simulation only",
        "max_risk": "Demo $ risk only",
        "risk_reward": "Preview estimate",
    },
    {
        "ticker": "TSLA",
        "setup": "Volatility compression break",
        "status": "Blocked",
        "gate": "Steven approval required",
        "summary": "Placeholder setup intentionally blocked until explicit approval state exists.",
        "catalyst": "Demo catalyst: volatility event placeholder.",
        "chart": "Demo chart: compression range placeholder.",
        "plan_status": "Blocked: approval gate is not satisfied.",
        "entry_trigger": "Demo range break with confirmation",
        "entry_limit": "Demo limit: breakout retest",
        "stop": "Demo invalidation: range reclaim failure",
        "target_1": "Demo target 1: range height",
        "target_2": "Demo target 2: prior resistance",
        "target_3": "Demo target 3: no live target",
        "trailing_rule": "Demo trail: disabled while blocked",
        "position_size": "Blocked",
        "max_risk": "Blocked",
        "risk_reward": "Blocked",
    },
    {
        "ticker": "SMCI",
        "setup": "Late-day reclaim",
        "status": "Watch only",
        "gate": "Data freshness check",
        "summary": "Placeholder setup for a reclaim candidate that needs freshness review.",
        "catalyst": "Demo catalyst: watchlist-only placeholder.",
        "chart": "Demo chart: reclaim placeholder.",
        "plan_status": "Watch-only until data freshness is checked.",
        "entry_trigger": "Demo reclaim above afternoon pivot",
        "entry_limit": "Demo limit: pivot plus spread buffer",
        "stop": "Demo invalidation: pivot failure",
        "target_1": "Demo target 1: liquidity shelf",
        "target_2": "Demo target 2: session high",
        "target_3": "Demo target 3: locked",
        "trailing_rule": "Demo trail: not active",
        "position_size": "Not sized",
        "max_risk": "Needs freshness check",
        "risk_reward": "Not trusted yet",
    },
]


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
        "Simulation only. No broker connected. Live trading locked."
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
            "Machine status, Top 5 plan candidates, Trade Plan Ladder, Risk Governor, locked Order Console, and Machine Log.",
            "Simulation Lab. No broker connected. Live trading locked.",
            window.open_argus_machine_console,
        )
    )
    layout.addWidget(choice_row)
    layout.addStretch(1)

    footer = QLabel("Gateway state: safe startup shell. Orders cannot be previewed, simulated, submitted, or routed from here.")
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
        "Autonomous planning console shell. Placeholder/demo state only. No broker connected. Live trading locked."
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
    left_layout.addWidget(build_argus_top5_panel(window))
    left_layout.addWidget(build_argus_workbench_panel(window))
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
    clear_argus_trade_plan_ladder(window)
    return page


def build_argus_machine_status_bar(window: Any) -> QWidget:
    box = QGroupBox("Machine Status Bar")
    box.setObjectName("argusMachineStatusBar")
    layout = QGridLayout(box)
    layout.setSpacing(8)
    statuses = [
        ("Mode", "Simulation Lab"),
        ("Broker", "None connected"),
        ("Live Trading", "Locked"),
        ("Risk Governor", "Preview only"),
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
    box = QGroupBox("Top 5 Trade Plan Candidates - Placeholder")
    box.setObjectName("argusTop5Panel")
    layout = QVBoxLayout(box)
    layout.setSpacing(8)
    note = QLabel(
        "Demo candidates only. These are machine-plan candidates, not approved live trades. "
        "Click a ticker row to populate the Trade Plan Ladder."
    )
    note.setObjectName("criteriaLabel")
    note.setWordWrap(True)
    layout.addWidget(note)

    window.argus_candidate_buttons = []
    for candidate in ARGUS_MACHINE_PLACEHOLDER_CANDIDATES:
        button = QPushButton(
            f"{candidate['ticker']} | {candidate['setup']} | {candidate['status']} | Gate: {candidate['gate']}"
        )
        button.setObjectName(f"argusCandidateButton_{candidate['ticker']}")
        button.setProperty("argusTicker", candidate["ticker"])
        button.setToolTip("Placeholder Top 5 candidate. Click to populate the Trade Plan Ladder.")
        button.clicked.connect(lambda _checked=False, item=candidate: select_argus_machine_candidate(window, item))
        layout.addWidget(button)
        window.argus_candidate_buttons.append(button)
    return box


def build_argus_workbench_panel(window: Any) -> QWidget:
    box = QGroupBox("Selected Candidate Workbench")
    box.setObjectName("argusWorkbenchPanel")
    layout = QGridLayout(box)
    layout.setSpacing(8)

    window.argus_workbench_ticker_label = QLabel("Selected ticker: none")
    window.argus_workbench_ticker_label.setObjectName("argusWorkbenchTicker")
    window.argus_workbench_ticker_label.setWordWrap(True)
    window.argus_workbench_summary_label = QLabel("Setup summary: select a Top 5 placeholder candidate.")
    window.argus_workbench_summary_label.setWordWrap(True)
    window.argus_workbench_catalyst_label = QLabel("Catalyst placeholder: waiting for candidate selection.")
    window.argus_workbench_catalyst_label.setWordWrap(True)
    window.argus_workbench_chart_label = QLabel("Chart placeholder: waiting for candidate selection.")
    window.argus_workbench_chart_label.setWordWrap(True)
    window.argus_workbench_plan_status_label = QLabel("Plan status: no Trade Plan selected.")
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
    box = QGroupBox("Trade Plan Ladder")
    box.setObjectName("argusTradePlanLadderPanel")
    layout = QVBoxLayout(box)
    layout.setSpacing(8)

    window.argus_ladder_empty_label = QLabel("Select a candidate to populate the Trade Plan Ladder")
    window.argus_ladder_empty_label.setObjectName("argusTradePlanEmptyState")
    window.argus_ladder_empty_label.setWordWrap(True)
    layout.addWidget(window.argus_ladder_empty_label)

    window.argus_ladder_table = QTableWidget(0, 2)
    window.argus_ladder_table.setObjectName("argusTradePlanLadderTable")
    window.argus_ladder_table.setHorizontalHeaderLabels(["Field", "Placeholder Value"])
    window.argus_ladder_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    window.argus_ladder_table.verticalHeader().setVisible(False)
    window.argus_ladder_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    window.argus_ladder_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    layout.addWidget(window.argus_ladder_table, 1)
    return box


def build_argus_risk_governor_panel(window: Any) -> QWidget:
    box = QGroupBox("Risk Governor - Display Only")
    box.setObjectName("argusRiskGovernorPanel")
    layout = QVBoxLayout(box)
    warning = QLabel(
        "Preview only. This panel is not live trading permission and cannot approve broker execution."
    )
    warning.setObjectName("argusRiskWarningLabel")
    warning.setWordWrap(True)
    layout.addWidget(warning)

    window.argus_risk_gate_table = QTableWidget(6, 3)
    window.argus_risk_gate_table.setObjectName("argusRiskGateTable")
    window.argus_risk_gate_table.setHorizontalHeaderLabels(["Gate", "State", "Reason"])
    window.argus_risk_gate_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    window.argus_risk_gate_table.verticalHeader().setVisible(False)
    window.argus_risk_gate_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    gates = [
        ("Data freshness", "Demo check", "Placeholder data requires operator review."),
        ("Stop defined", "Preview", "Demo stop only; not approved for orders."),
        ("Max risk", "Missing/preview", "No account risk model is connected."),
        ("Duplicate order", "Locked", "No broker or order ledger connected."),
        ("Broker mode", "None connected", "Broker adapter is not active."),
        ("Steven approval", "Required", "Live execution needs separate explicit approval."),
    ]
    for row, values in enumerate(gates):
        for column, value in enumerate(values):
            window.argus_risk_gate_table.setItem(row, column, QTableWidgetItem(value))
    layout.addWidget(window.argus_risk_gate_table)
    return box


def build_argus_order_console_panel(window: Any) -> QWidget:
    box = QGroupBox("Order Console - Locked")
    box.setObjectName("argusOrderConsolePanel")
    layout = QVBoxLayout(box)
    note = QLabel(
        "Display-only shell. No preview, paper order, live order, broker connection, or execution route exists."
    )
    note.setObjectName("argusOrderConsoleWarning")
    note.setWordWrap(True)
    layout.addWidget(note)

    button_row = QWidget()
    button_layout = QHBoxLayout(button_row)
    button_layout.setContentsMargins(0, 0, 0, 0)
    window.argus_preview_order_button = QPushButton("Preview Order")
    window.argus_submit_paper_button = QPushButton("Submit Paper Order")
    window.argus_submit_live_button = QPushButton("Submit Live Order")
    locked_buttons = [
        window.argus_preview_order_button,
        window.argus_submit_paper_button,
        window.argus_submit_live_button,
    ]
    for button in locked_buttons:
        button.setEnabled(False)
        button.setProperty("lockedOrderControl", True)
        button.setToolTip("Locked: display-only shell. No broker or execution behavior is connected.")
        button_layout.addWidget(button)
    window.argus_submit_live_button.setObjectName("argusSubmitLiveOrderButton")
    window.argus_submit_live_button.setToolTip("Locked: live trading requires separate Steven approval and broker safety gates.")
    layout.addWidget(button_row)
    return box


def build_argus_machine_log_panel(window: Any) -> QWidget:
    box = QGroupBox("Machine Log")
    box.setObjectName("argusMachineLogPanel")
    layout = QVBoxLayout(box)
    window.argus_machine_log = QPlainTextEdit()
    window.argus_machine_log.setObjectName("argusMachineLog")
    window.argus_machine_log.setReadOnly(True)
    window.argus_machine_log.setMaximumHeight(96)
    window.argus_machine_log.setPlainText(
        "Argus Machine loaded in Simulation Lab. No broker connected. Live trading locked.\n"
        "Top 5 placeholder candidates ready. Selecting a ticker populates the Trade Plan Ladder.\n"
        "Order Console disabled. This shell cannot place, preview, simulate, or submit trades."
    )
    layout.addWidget(window.argus_machine_log)
    return box


def clear_argus_trade_plan_ladder(window: Any) -> None:
    window.argus_ladder_empty_label.setText("Select a candidate to populate the Trade Plan Ladder")
    window.argus_ladder_table.setRowCount(0)


def select_argus_machine_candidate(window: Any, candidate: dict[str, str]) -> None:
    window.argus_workbench_ticker_label.setText(f"Selected ticker: {candidate['ticker']}")
    window.argus_workbench_summary_label.setText(f"Setup summary: {candidate['summary']}")
    window.argus_workbench_catalyst_label.setText(f"Catalyst placeholder: {candidate['catalyst']}")
    window.argus_workbench_chart_label.setText(f"Chart placeholder: {candidate['chart']}")
    window.argus_workbench_plan_status_label.setText(f"Plan status: {candidate['plan_status']}")
    window.argus_ladder_empty_label.setText(
        f"Trade Plan Ladder populated for {candidate['ticker']} - placeholder/demo state only."
    )
    rows = [
        ("Ticker", candidate["ticker"]),
        ("Setup type", candidate["setup"]),
        ("Entry trigger", candidate["entry_trigger"]),
        ("Entry/limit", candidate["entry_limit"]),
        ("Stop/invalidation", candidate["stop"]),
        ("Target 1", candidate["target_1"]),
        ("Target 2", candidate["target_2"]),
        ("Target 3", candidate["target_3"]),
        ("Trailing rule", candidate["trailing_rule"]),
        ("Position size", candidate["position_size"]),
        ("Max dollar risk", candidate["max_risk"]),
        ("Risk/reward", candidate["risk_reward"]),
        ("Manual override state", "None. Any future Steven edit requires Risk Governor re-check."),
        ("Risk Governor status", candidate["gate"]),
    ]
    window.argus_ladder_table.setRowCount(len(rows))
    for row, (field, value) in enumerate(rows):
        window.argus_ladder_table.setItem(row, 0, QTableWidgetItem(field))
        window.argus_ladder_table.setItem(row, 1, QTableWidgetItem(value))
    window.argus_machine_log.appendPlainText(
        f"{candidate['ticker']} selected. Ladder populated with placeholder plan fields. Live trading remains locked."
    )
