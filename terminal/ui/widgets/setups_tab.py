"""Setup'lar sekmesi — Aktif + Aday tablosu, sağda detay paneli."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QPushButton,
    QSplitter, QTableView, QVBoxLayout, QWidget,
)

from terminal.timeutil import format_local_short
from terminal.ui.data_provider import DataProvider, SetupRow
from terminal.ui.widgets.detail_panel import DetailPanel

COLUMNS = ["Parite", "TF", "Pattern", "Yön", "Durum", "Poz",
           "Q", "Entry", "SL", "Hedef", "D Zamanı"]


def _fmt(ms: int) -> str:
    return format_local_short(ms)


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
        # Sütun başlığı tıklayınca sıralama (sayısal sütunlar UserRole'a göre)
        self.table.setSortingEnabled(True)
        self.model.setSortRole(Qt.UserRole)
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
        refresh_btn.clicked.connect(self._force_refresh)
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
        self.table.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        state_order = {"Aktif": 0, "Aday": 1, "TP": 2, "STOP": 3, "EO": 4, "ZI": 5}
        for r in self._rows:
            items = [
                QStandardItem(r.symbol),
                QStandardItem(r.interval),
                QStandardItem(r.pattern_name),
                QStandardItem("BULL" if r.direction == "bull" else "BEAR"),
                QStandardItem(r.state),
                QStandardItem("●" if r.has_open_paper else ""),
                QStandardItem(str(r.q_score) if r.q_score else "—"),
                QStandardItem(f"{r.entry:.6g}"),
                QStandardItem(f"{r.stop:.6g}"),
                QStandardItem(f"{r.tp1:.6g}"),
                QStandardItem(_fmt(r.d_time)),
            ]
            # Sıralama değerleri (UserRole)
            items[0].setData(r.symbol, Qt.UserRole)
            items[1].setData(r.interval, Qt.UserRole)
            items[2].setData(r.pattern_name, Qt.UserRole)
            items[3].setData(r.direction, Qt.UserRole)
            items[4].setData(state_order.get(r.state, 99), Qt.UserRole)
            items[5].setData(1 if r.has_open_paper else 0, Qt.UserRole)
            items[6].setData(int(r.q_score) if r.q_score else -1, Qt.UserRole)
            items[7].setData(float(r.entry), Qt.UserRole)
            items[8].setData(float(r.stop), Qt.UserRole)
            items[9].setData(float(r.tp1), Qt.UserRole)
            items[10].setData(int(r.d_time), Qt.UserRole)
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
            # Açık paper pozisyonu olan setup → yeşil nokta + ortalı
            if r.has_open_paper:
                items[5].setForeground(QColor(GREEN))
            items[5].setTextAlignment(Qt.AlignCenter)
            if r.elenen:
                items[0].setText(r.symbol + " ⚠")
            self.model.appendRow(items)
        self.table.setSortingEnabled(True)

    def _force_refresh(self) -> None:
        """Yenile butonu — Store'u zorla yeniden açar (fresh data garantili)."""
        mw = self.window()
        if hasattr(mw, "refresh_all"):
            mw.refresh_all(force=True)
        else:
            self.refresh()

    def _on_row_clicked(self, index) -> None:
        # Sıralama sonrası model index ≠ _rows index. d_time + symbol ile bul.
        symbol = self.model.item(index.row(), 0).text().replace(" ⚠", "")
        d_time = self.model.item(index.row(), 10).data(Qt.UserRole)
        for r in self._rows:
            if r.symbol == symbol and r.d_time == d_time:
                self.detail.show_setup(r, self.provider)
                return
