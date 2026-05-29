"""Parite Karakter sekmesi — lab skor tablosu + backtest çalıştırma + run özetleri."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QSpinBox, QTableView, QVBoxLayout, QWidget,
)

from terminal.timeutil import format_local_short
from terminal.ui.data_provider import DataProvider, RunSummary

COLUMNS = ["Parite", "TF", "Pattern", "Yön", "N", "TP", "STOP", "EO", "ZI", "WR %", "Karakter"]


def _stat_card(label: str, value: str, color: str | None = None) -> tuple[QFrame, QLabel]:
    box = QFrame()
    box.setObjectName("StatCard")
    box.setStyleSheet(
        "QFrame#StatCard { background-color: #1a1a1f; border: 1px solid #2a2a32;"
        " border-radius: 6px; padding: 6px 12px; }"
    )
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 4, 8, 4)
    layout.setSpacing(0)
    lbl = QLabel(label)
    lbl.setStyleSheet("color: #888; font-size: 10px;")
    lbl.setAlignment(Qt.AlignCenter)
    val = QLabel(value)
    val.setStyleSheet(f"color: {color or '#e6e6ea'}; font-size: 16px; font-weight: bold;")
    val.setAlignment(Qt.AlignCenter)
    layout.addWidget(lbl)
    layout.addWidget(val)
    return box, val


class KarakterTab(QWidget):
    """karakter_scores tablosu + backtest çalıştırma + son koşumların özeti."""

    def __init__(self, provider: DataProvider, parent=None) -> None:
        super().__init__(parent)
        self.provider = provider

        # --- Backtest butonu (ön plan) ---
        self.backtest_btn = QPushButton("🧪 Backtest Çalıştır")
        self.backtest_btn.clicked.connect(self._on_backtest)
        self.backtest_btn.setStyleSheet(
            "QPushButton { background-color: #d4a72c; color: #0e0e10; "
            "font-weight: bold; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #e6b840; }"
        )

        # --- Run seçici ---
        self.run_selector = QComboBox()
        self.run_selector.setMinimumWidth(280)
        self.run_selector.currentIndexChanged.connect(self._on_run_changed)

        run_row = QHBoxLayout()
        run_row.addWidget(self.backtest_btn)
        run_row.addSpacing(16)
        run_row.addWidget(QLabel("Backtest koşumu:"))
        run_row.addWidget(self.run_selector)
        run_row.addStretch()

        # --- Run özet kartları ---
        self.card_total, self.lbl_total = _stat_card("ÖRNEKLEM", "0")
        self.card_tp, self.lbl_tp = _stat_card("TP", "0", "#26a69a")
        self.card_stop, self.lbl_stop = _stat_card("STOP", "0", "#ef5350")
        self.card_wr, self.lbl_wr = _stat_card("WIN RATE", "—", "#26a69a")
        self.card_total_r, self.lbl_total_r = _stat_card("TOPLAM R", "—", "#d4a72c")
        self.card_avg_r, self.lbl_avg_r = _stat_card("ORT. R/İŞLEM", "—", "#d4a72c")
        self.card_eo, self.lbl_eo = _stat_card("ENTRY YOK", "0", "#888")
        self.card_zi, self.lbl_zi = _stat_card("ZAMANSAL", "0", "#888")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        for c in [self.card_total, self.card_tp, self.card_stop, self.card_wr,
                  self.card_total_r, self.card_avg_r,
                  self.card_eo, self.card_zi]:
            cards_row.addWidget(c)
        cards_row.addStretch()

        # --- Karakter skoru tablosu filtreleri ---
        self.direction_filter = QComboBox()
        self.direction_filter.addItems(["all", "bull", "bear"])
        self.direction_filter.currentTextChanged.connect(self._refresh_scores)

        self.min_samples = QSpinBox()
        self.min_samples.setMinimum(1)
        self.min_samples.setMaximum(100)
        self.min_samples.setValue(1)
        self.min_samples.valueChanged.connect(self._refresh_scores)

        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self._force_refresh)

        score_toolbar = QHBoxLayout()
        score_toolbar.addWidget(QLabel("Karakter Skor Tablosu"))
        score_toolbar.addSpacing(16)
        score_toolbar.addWidget(QLabel("Yön:"))
        score_toolbar.addWidget(self.direction_filter)
        score_toolbar.addWidget(QLabel("Min örneklem:"))
        score_toolbar.addWidget(self.min_samples)
        score_toolbar.addWidget(refresh_btn)
        score_toolbar.addStretch()

        # --- Skor tablosu ---
        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.model.setSortRole(Qt.UserRole)  # sayısal sütunlar doğru sıralansın
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)

        # Ana layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addLayout(run_row)
        layout.addLayout(cards_row)
        layout.addLayout(score_toolbar)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        self._refresh_runs()
        self._refresh_scores()

    def _refresh_runs(self) -> None:
        runs = self.provider.list_runs()
        # Mevcut seçili koşumu koru: 5 sn'lik periyodik refresh_all bu listeyi
        # yeniden kuruyordu; eskiden seçim her seferinde "Tüm koşumlar"a (index 0)
        # düşüyor, kullanıcı bir koşum seçince 1-2 sn sonra geri alınıyordu.
        prev = self.run_selector.currentData()
        self.run_selector.blockSignals(True)
        self.run_selector.clear()
        self.run_selector.addItem("Tüm koşumlar (toplam)", userData=None)
        for r in runs:
            label = f"#{r.run_id} · {format_local_short(r.started_at)} · {r.sample_count} örneklem"
            self.run_selector.addItem(label, userData=r.run_id)
        # Önceki seçimi geri yükle (koşum hâlâ listede ise); yoksa "Tüm koşumlar".
        idx = 0 if prev is None else self.run_selector.findData(prev)
        self.run_selector.setCurrentIndex(idx if idx >= 0 else 0)
        self.run_selector.blockSignals(False)
        self._update_cards()

    def _on_run_changed(self) -> None:
        self._update_cards()

    def _update_cards(self) -> None:
        from terminal.karakter.score import trade_r
        run_id = self.run_selector.currentData()
        if run_id is None:
            # Toplam: tüm karakter_samples
            cur = self.provider.store._conn.execute(
                "SELECT outcome, COUNT(*) FROM karakter_samples GROUP BY outcome"
            )
            stats = {"TP": 0, "STOP": 0, "EO": 0, "ZI": 0, "Aktif": 0, "Aday": 0}
            for o, n in cur.fetchall():
                stats[o] = int(n)
            total = sum(stats.values())
            rcur = self.provider.store._conn.execute(
                "SELECT entry, stop, tp1, outcome FROM karakter_samples"
            )
        else:
            stats = self.provider._run_outcome_stats(run_id)
            total = sum(stats.values())
            rcur = self.provider.store._conn.execute(
                "SELECT entry, stop, tp1, outcome FROM karakter_samples WHERE run_id = ?",
                (run_id,),
            )
        decided = stats["TP"] + stats["STOP"]
        wr = (stats["TP"] / decided * 100) if decided else 0.0
        # R hesabı
        rs = [trade_r(r[0], r[1], r[2], r[3]) for r in rcur.fetchall()]
        decided_rs = [r for r in rs if r != 0.0]
        total_r = sum(rs)
        avg_r = (sum(decided_rs) / len(decided_rs)) if decided_rs else 0.0

        self.lbl_total.setText(str(total))
        self.lbl_tp.setText(str(stats["TP"]))
        self.lbl_stop.setText(str(stats["STOP"]))
        self.lbl_eo.setText(str(stats["EO"]))
        self.lbl_zi.setText(str(stats["ZI"]))
        self.lbl_wr.setText(f"{wr:.1f}%" if decided else "—")
        self.lbl_total_r.setText(f"{total_r:+.2f}R" if decided_rs else "—")
        self.lbl_avg_r.setText(f"{avg_r:+.2f}R" if decided_rs else "—")
        # WR rengi
        wr_color = "#26a69a" if wr >= 60 else ("#ff9800" if wr >= 45 else "#ef5350") if decided else "#888"
        self.lbl_wr.setStyleSheet(f"color: {wr_color}; font-size: 16px; font-weight: bold;")
        # R rengi
        r_color = "#26a69a" if total_r > 0 else "#ef5350" if total_r < 0 else "#888"
        self.lbl_total_r.setStyleSheet(f"color: {r_color}; font-size: 16px; font-weight: bold;")
        avg_color = "#26a69a" if avg_r > 0 else "#ef5350" if avg_r < 0 else "#888"
        self.lbl_avg_r.setStyleSheet(f"color: {avg_color}; font-size: 16px; font-weight: bold;")

    def _refresh_scores(self) -> None:
        from terminal.ui.styles import GREEN, RED
        rows = self.provider.karakter_scores(
            direction=self.direction_filter.currentText(),
            min_samples=self.min_samples.value(),
        )
        self.table.setSortingEnabled(False)
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
            # Sıralama değerleri — sayısal sütunlar doğru sıralansın
            items[0].setData(r.symbol, Qt.UserRole)
            items[1].setData(r.interval, Qt.UserRole)
            items[2].setData(r.pattern_name, Qt.UserRole)
            items[3].setData(r.direction, Qt.UserRole)
            items[4].setData(int(r.sample_count), Qt.UserRole)
            items[5].setData(int(r.tp_count), Qt.UserRole)
            items[6].setData(int(r.stop_count), Qt.UserRole)
            items[7].setData(int(r.eo_count), Qt.UserRole)
            items[8].setData(int(r.zi_count), Qt.UserRole)
            items[9].setData(float(r.win_rate * 100), Qt.UserRole)
            items[10].setData(float(r.karakter_score), Qt.UserRole)
            if r.karakter_score >= 50:
                items[10].setForeground(QColor(GREEN))
            elif r.karakter_score < 30:
                items[10].setForeground(QColor(RED))
            self.model.appendRow(items)
        self.table.setSortingEnabled(True)

    def _force_refresh(self) -> None:
        mw = self.window()
        if hasattr(mw, "refresh_all"):
            mw.refresh_all(force=True)
        else:
            self.refresh()

    def _on_backtest(self) -> None:
        from terminal.ui.widgets.backtest_dialog import BacktestDialog
        dlg = BacktestDialog(self)
        dlg.finished_ok.connect(self.refresh)
        dlg.exec()
