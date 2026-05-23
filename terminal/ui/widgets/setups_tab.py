"""Setup'lar sekmesi — Aktif + Aday tablosu, sağda detay paneli."""
from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QPushButton,
    QSplitter, QTableView, QVBoxLayout, QWidget,
)

from terminal.ui.data_provider import DataProvider, SetupRow
from terminal.ui.widgets.detail_panel import DetailPanel

COLUMNS = ["Parite", "TF", "Pattern", "Yön", "Durum", "Q", "Entry", "SL", "TP1", "D Zamanı"]


def _fmt(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")


class SetupsTab(QWidget):
    """Açık + tüm setup'ları gösterir; satıra tıklayınca sağda detay açılır."""

    def __init__(self, provider: DataProvider, only_open: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.provider = provider
        self.only_open = only_open
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

        self.detail = DetailPanel()
        self.detail.outcome_overridden.connect(lambda _sid: self.refresh())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Üstteki kontrol satırı
        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(splitter)

    def refresh(self) -> None:
        from terminal.ui.styles import BLUE, ACCENT_GOLD, GREEN, RED, TEXT_DIM
        states = ["Aday", "Aktif"] if self.only_open else None
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
                QStandardItem(_fmt(r.d_time)),
            ]
            # Renkler
            dir_color = QColor(GREEN) if r.direction == "bull" else QColor(RED)
            items[3].setForeground(dir_color)
            state_color = {
                "Aktif": QColor(BLUE), "Aday": QColor(ACCENT_GOLD),
                "TP": QColor(GREEN), "STOP": QColor(RED),
                "EO": QColor(TEXT_DIM), "ZI": QColor(TEXT_DIM),
            }.get(r.state)
            if state_color:
                items[4].setForeground(state_color)
            if r.elenen:
                items[0].setText(r.symbol + " ⚠")
            self.model.appendRow(items)

    def _on_row_clicked(self, index) -> None:
        row = index.row()
        if 0 <= row < len(self._rows):
            self.detail.show_setup(self._rows[row], self.provider)
