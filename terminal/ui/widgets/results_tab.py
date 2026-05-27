"""Sonuçlar sekmesi — kapanmış setup'lar (TP/STOP/EO/ZI), kaynak ayrımı + filtre butonları."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSplitter, QTableView, QVBoxLayout, QWidget,
)

from terminal.timeutil import format_local_short
from terminal.ui.data_provider import DataProvider, SetupRow
from terminal.ui.widgets.detail_panel import DetailPanel

COLUMNS = ["Kaynak", "Parite", "TF", "Pattern", "Yön", "Sonuç", "Q",
           "Entry", "SL", "TP1", "Tespit"]

OUTCOMES = ["Hepsi", "TP", "STOP", "EO", "ZI"]
SOURCES = ["Hepsi", "Live", "Backtest"]


def _fmt(ms: int) -> str:
    return format_local_short(ms)


def _filter_button(text: str, checked: bool = False) -> QPushButton:
    btn = QPushButton(text)
    btn.setCheckable(True)
    btn.setChecked(checked)
    btn.setStyleSheet(
        "QPushButton { padding: 4px 12px; }"
        "QPushButton:checked { background-color: #d4a72c; color: #0e0e10; font-weight: bold; }"
    )
    return btn


class ResultsTab(QWidget):
    """TP/STOP/EO/ZI durumundaki setup'lar; kaynak (live/backtest) + outcome filtreleri."""

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
        # Sütun başlığına tıklayınca sıralama; sayısal sütunlar UserRole'daki
        # numeric değere göre, string sütunlar görünür metne göre.
        self.table.setSortingEnabled(True)
        self.model.setSortRole(Qt.UserRole)
        self.table.clicked.connect(self._on_row_clicked)

        # --- Outcome filtre butonları (toggle group, tek seçim) ---
        self.outcome_group = QButtonGroup(self)
        self.outcome_group.setExclusive(True)
        self.outcome_buttons: dict[str, QPushButton] = {}
        outcome_row = QHBoxLayout()
        outcome_row.addWidget(QLabel("Sonuç:"))
        for i, oc in enumerate(OUTCOMES):
            btn = _filter_button(oc, checked=(i == 0))
            self.outcome_buttons[oc] = btn
            self.outcome_group.addButton(btn, i)
            outcome_row.addWidget(btn)
        self.outcome_group.idClicked.connect(lambda _id: self.refresh())

        # --- Kaynak filtre butonları ---
        self.source_group = QButtonGroup(self)
        self.source_group.setExclusive(True)
        self.source_buttons: dict[str, QPushButton] = {}
        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Kaynak:"))
        for i, src in enumerate(SOURCES):
            btn = _filter_button(src, checked=(i == 0))
            self.source_buttons[src] = btn
            self.source_group.addButton(btn, i)
            source_row.addWidget(btn)
        self.source_group.idClicked.connect(lambda _id: self.refresh())

        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self._force_refresh)

        # Üst toolbar: 2 satır filtre
        toolbar_top = QHBoxLayout()
        toolbar_top.addLayout(outcome_row)
        toolbar_top.addSpacing(16)
        toolbar_top.addLayout(source_row)
        toolbar_top.addStretch()
        toolbar_top.addWidget(refresh_btn)

        self.detail = DetailPanel()
        self.detail.outcome_overridden.connect(lambda _sid: self.refresh())
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar_top)
        layout.addWidget(splitter)

    def refresh(self) -> None:
        from terminal.ui.styles import GREEN, RED, TEXT_DIM

        # Filtreleri oku
        outcome_sel = next((k for k, b in self.outcome_buttons.items() if b.isChecked()), "Hepsi")
        source_sel = next((k for k, b in self.source_buttons.items() if b.isChecked()), "Hepsi")
        states = ["TP", "STOP", "EO", "ZI"] if outcome_sel == "Hepsi" else [outcome_sel]
        source = None if source_sel == "Hepsi" else source_sel.lower()

        self._rows = self.provider.setups(states=states, source=source)
        # Sıralama performansı: doldururken sıralamayı kapat, sonra aç
        self.table.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        # Outcome için stabil sıralama önceliği: TP < STOP < EO < ZI < Aday < Aktif
        outcome_order = {"TP": 0, "STOP": 1, "EO": 2, "ZI": 3, "Aday": 4, "Aktif": 5}
        for r in self._rows:
            src_label = "BT" if r.source == "backtest" else "LV"
            src_color = "#9c27b0" if r.source == "backtest" else "#42a5f5"
            items = [
                QStandardItem(src_label),
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
            # Sıralama değerleri (UserRole) — sayısal sütunlar doğru sıralanır
            items[0].setData(src_label, Qt.UserRole)
            items[1].setData(r.symbol, Qt.UserRole)
            items[2].setData(r.interval, Qt.UserRole)
            items[3].setData(r.pattern_name, Qt.UserRole)
            items[4].setData(r.direction, Qt.UserRole)
            items[5].setData(outcome_order.get(r.state, 99), Qt.UserRole)
            items[6].setData(int(r.q_score) if r.q_score else -1, Qt.UserRole)
            items[7].setData(float(r.entry), Qt.UserRole)
            items[8].setData(float(r.stop), Qt.UserRole)
            items[9].setData(float(r.tp1), Qt.UserRole)
            items[10].setData(int(r.detected_at), Qt.UserRole)
            items[0].setForeground(QColor(src_color))
            dir_color = QColor(GREEN) if r.direction == "bull" else QColor(RED)
            items[4].setForeground(dir_color)
            state_color = {
                "TP": QColor(GREEN), "STOP": QColor(RED),
                "EO": QColor(TEXT_DIM), "ZI": QColor(TEXT_DIM),
            }.get(r.state)
            if state_color:
                items[5].setForeground(state_color)
            self.model.appendRow(items)
        self.table.setSortingEnabled(True)

    def _force_refresh(self) -> None:
        mw = self.window()
        if hasattr(mw, "refresh_all"):
            mw.refresh_all(force=True)
        else:
            self.refresh()

    def _on_row_clicked(self, index) -> None:
        # Sıralama yapıldığında model row != insertion order. Symbol+interval
        # +pattern+detected_at ile orijinal SetupRow'u bul.
        symbol = self.model.item(index.row(), 1).text()
        interval = self.model.item(index.row(), 2).text()
        pattern = self.model.item(index.row(), 3).text()
        det_at = self.model.item(index.row(), 10).data(Qt.UserRole)
        for r in self._rows:
            if (r.symbol == symbol and r.interval == interval
                    and r.pattern_name == pattern and r.detected_at == det_at):
                self.detail.show_setup(r, self.provider)
                return
