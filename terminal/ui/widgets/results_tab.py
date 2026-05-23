"""Sonuçlar sekmesi — kapanmış setup'lar (TP/STOP/EO/ZI)."""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget,
)

from terminal.ui.data_provider import DataProvider, SetupRow
from terminal.ui.widgets.detail_panel import DetailPanel

COLUMNS = ["Parite", "TF", "Pattern", "Yön", "Sonuç", "Q", "Entry", "SL", "TP1", "Tespit"]


def _fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")


class ResultsTab(QWidget):
    """TP/STOP/EO/ZI durumundaki setup'lar."""

    def __init__(self, provider: DataProvider, parent=None) -> None:
        super().__init__(parent)
        self.provider = provider
        self._rows: list[SetupRow] = []

        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.clicked.connect(self._on_row_clicked)

        # Filtreler
        self.outcome_filter = QComboBox()
        self.outcome_filter.addItems(["Hepsi", "TP", "STOP", "EO", "ZI"])
        self.outcome_filter.currentTextChanged.connect(self.refresh)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Sonuç:"))
        toolbar.addWidget(self.outcome_filter)
        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()

        self.detail = DetailPanel()
        self.detail.outcome_overridden.connect(lambda _sid: self.refresh())
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(splitter)

    def refresh(self) -> None:
        from terminal.ui.styles import GREEN, RED, TEXT_DIM
        outcome = self.outcome_filter.currentText()
        states = ["TP", "STOP", "EO", "ZI"] if outcome == "Hepsi" else [outcome]
        self._rows = self.provider.setups(states=states)
        self.model.removeRows(0, self.model.rowCount())
        for r in self._rows:
            items = [
                QStandardItem(r.symbol),
                QStandardItem(r.interval),
                QStandardItem(r.pattern_name),
                QStandardItem("BULL" if r.direction == "bull" else "BEAR"),
                QStandardItem(r.state),
                QStandardItem(str(r.q_score) if r.q_score else "—"),
                QStandardItem(f"{r.entry:.6g}"),
                QStandardItem(f"{r.stop:.6g}"),
                QStandardItem(f"{r.tp1:.6g}"),
                QStandardItem(_fmt(r.detected_at)),
            ]
            dir_color = QColor(GREEN) if r.direction == "bull" else QColor(RED)
            items[3].setForeground(dir_color)
            state_color = {
                "TP": QColor(GREEN), "STOP": QColor(RED),
                "EO": QColor(TEXT_DIM), "ZI": QColor(TEXT_DIM),
            }.get(r.state)
            if state_color:
                items[4].setForeground(state_color)
            self.model.appendRow(items)

    def _on_row_clicked(self, index) -> None:
        row = index.row()
        if 0 <= row < len(self._rows):
            self.detail.show_setup(self._rows[row], self.provider)
