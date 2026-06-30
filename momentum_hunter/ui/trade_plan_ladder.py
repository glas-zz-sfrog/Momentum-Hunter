from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from momentum_hunter.autonomy.view_models import Top5CandidatePlan, ladder_rows_for_candidate


class TradePlanLadderWidget(QGroupBox):
    def __init__(self) -> None:
        super().__init__("Trade Plan Ladder")
        self.setObjectName("argusTradePlanLadderPanel")
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        self.empty_label = QLabel("Select a candidate to populate the Trade Plan Ladder")
        self.empty_label.setObjectName("argusTradePlanEmptyState")
        self.empty_label.setWordWrap(True)
        layout.addWidget(self.empty_label)

        self.table = QTableWidget(0, 2)
        self.table.setObjectName("argusTradePlanLadderTable")
        self.table.setHorizontalHeaderLabels(["Field", "TradePlan Value"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table, 1)

    def clear(self) -> None:
        self.empty_label.setText("Select a candidate to populate the Trade Plan Ladder")
        self.table.setRowCount(0)

    def render_candidate(self, candidate: Top5CandidatePlan | None) -> None:
        if candidate is None:
            self.clear()
            return
        self.empty_label.setText(
            f"Trade Plan Ladder populated for {candidate.ticker} from structured TradePlan data."
        )
        rows = ladder_rows_for_candidate(candidate)
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(row.field))
            self.table.setItem(row_index, 1, QTableWidgetItem(row.value))
