"""Parite Karakter sekmesi — lab skor tablosu."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSpinBox, QTableView, QVBoxLayout, QWidget,
)

from terminal.ui.data_provider import DataProvider

COLUMNS = ["Parite", "TF", "Pattern", "Yön", "N", "TP", "STOP", "EO", "ZI", "WR %", "Karakter"]


class KarakterTab(QWidget):
    """karakter_scores tablosunu sıralanabilir görüntüler."""

    def __init__(self, provider: DataProvider, parent=None) -> None:
        super().__init__(parent)
        self.provider = provider

        self.direction_filter = QComboBox()
        self.direction_filter.addItems(["all", "bull", "bear"])
        self.direction_filter.currentTextChanged.connect(self.refresh)

        self.min_samples = QSpinBox()
        self.min_samples.setMinimum(1)
        self.min_samples.setMaximum(100)
        self.min_samples.setValue(1)
        self.min_samples.valueChanged.connect(self.refresh)

        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self.refresh)

        self.backtest_btn = QPushButton("🧪 Backtest Çalıştır")
        self.backtest_btn.clicked.connect(self._on_backtest)
        self.backtest_btn.setStyleSheet(
            "QPushButton { background-color: #d4a72c; color: #0e0e10; "
            "font-weight: bold; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #e6b840; }"
        )

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.backtest_btn)
        toolbar.addSpacing(20)
        toolbar.addWidget(QLabel("Yön:"))
        toolbar.addWidget(self.direction_filter)
        toolbar.addWidget(QLabel("Min örneklem:"))
        toolbar.addWidget(self.min_samples)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()

        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        from terminal.ui.styles import GREEN, RED, TEXT
        rows = self.provider.karakter_scores(
            direction=self.direction_filter.currentText(),
            min_samples=self.min_samples.value(),
        )
        self.model.removeRows(0, self.model.rowCount())
        for r in rows:
            items = [
                QStandardItem(r.symbol),
                QStandardItem(r.interval),
                QStandardItem(r.pattern_name),
                QStandardItem(r.direction),
                QStandardItem(str(r.sample_count)),
                QStandardItem(str(r.tp_count)),
                QStandardItem(str(r.stop_count)),
                QStandardItem(str(r.eo_count)),
                QStandardItem(str(r.zi_count)),
                QStandardItem(f"{r.win_rate * 100:.1f}"),
                QStandardItem(f"{r.karakter_score:.2f}"),
            ]
            # Karakter skoru rengi
            if r.karakter_score >= 50:
                items[10].setForeground(QColor(GREEN))
            elif r.karakter_score < 30:
                items[10].setForeground(QColor(RED))
            self.model.appendRow(items)

    def _on_backtest(self) -> None:
        from terminal.ui.widgets.backtest_dialog import BacktestDialog
        dlg = BacktestDialog(self)
        dlg.finished_ok.connect(self.refresh)
        dlg.exec()
