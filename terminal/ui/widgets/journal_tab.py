"""Journal (paper trade analizi) sekmesi.

Üst toolbar: period seçici (Gün/Hafta/Ay/Tüm Zaman) + Telegram'a yolla butonu.
İçerik: özet kartlar (Equity/P&L/WR/Trade) + 3 tablo (TF/Pattern/Parite) +
en iyi 5 / en kötü 5 trade.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableView, QVBoxLayout, QWidget,
)

from terminal.db.store import Store

log = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=3))


def _fmt_ts(ms: int | None) -> str:
    if ms is None:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%m-%d %H:%M")


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


def _filter_button(label: str, checked: bool = False) -> QPushButton:
    btn = QPushButton(label)
    btn.setCheckable(True)
    btn.setChecked(checked)
    btn.setStyleSheet(
        "QPushButton { padding: 4px 12px; background: #1a1a1f; color: #aaa;"
        " border: 1px solid #2a2a32; border-radius: 4px; }"
        "QPushButton:checked { background: #d4a72c; color: #0e0e10;"
        " font-weight: bold; }"
    )
    return btn


class JournalTab(QWidget):
    """Paper trade dönemsel analiz sekmesi."""

    PERIODS = [("Bugün", "day"), ("Hafta", "week"), ("Ay", "month"), ("Tüm", "all")]

    def __init__(self, store: Store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self._period = "week"  # default
        # Paper tabloları yoksa oluştur (tracker --paper ile başlatılmamışsa da)
        from terminal.paper.engine import PaperEngine
        PaperEngine(store)

        # --- Üst toolbar: Period butonları + Telegram ---
        self.period_group = QButtonGroup(self)
        self.period_group.setExclusive(True)
        self.period_buttons: dict[str, QPushButton] = {}
        period_row = QHBoxLayout()
        period_row.addWidget(QLabel("Dönem:"))
        for i, (label, key) in enumerate(self.PERIODS):
            btn = _filter_button(label, checked=(key == "week"))
            self.period_buttons[key] = btn
            self.period_group.addButton(btn, i)
            period_row.addWidget(btn)
        self.period_group.idClicked.connect(self._on_period_changed)
        period_row.addStretch()

        self.tg_btn = QPushButton("📤 Telegram'a Yolla")
        self.tg_btn.setStyleSheet(
            "QPushButton { background: #229ed9; color: white; padding: 6px 12px;"
            " font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background: #1e8bbf; }"
        )
        self.tg_btn.clicked.connect(self._send_telegram)
        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self.refresh)
        period_row.addWidget(refresh_btn)
        period_row.addWidget(self.tg_btn)

        # --- Özet kartlar ---
        self.c_equity, self.l_equity = _stat_card("EQUITY", "$1000.00")
        self.c_pnl, self.l_pnl = _stat_card("DÖNEM P&L", "$0.00", "#d4a72c")
        self.c_total_pnl, self.l_total_pnl = _stat_card("TOPLAM P&L", "$0.00", "#d4a72c")
        self.c_wr, self.l_wr = _stat_card("WIN RATE", "—", "#26a69a")
        self.c_trades, self.l_trades = _stat_card("TRADE", "0")
        self.c_tp, self.l_tp = _stat_card("TP", "0", "#26a69a")
        self.c_stop, self.l_stop = _stat_card("STOP", "0", "#ef5350")
        self.c_lev, self.l_lev = _stat_card("ORT. LEV", "1.0x", "#888")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        for c in [self.c_equity, self.c_pnl, self.c_total_pnl, self.c_wr,
                  self.c_trades, self.c_tp, self.c_stop, self.c_lev]:
            cards_row.addWidget(c)
        cards_row.addStretch()

        # --- 3 bucket tablosu (TF, Pattern, Parite) yan yana ---
        self.tf_table = self._make_bucket_table(["TF", "N", "TP", "STP", "WR", "P&L($)"])
        self.pat_table = self._make_bucket_table(["Pattern", "N", "TP", "STP", "WR", "P&L($)"])
        self.sym_table = self._make_bucket_table(["Parite", "N", "TP", "STP", "WR", "P&L($)"])

        tables_row = QHBoxLayout()
        tables_row.addWidget(self._wrap_table("⏱️ TF Bazlı", self.tf_table))
        tables_row.addWidget(self._wrap_table("🎯 Pattern Bazlı", self.pat_table))
        tables_row.addWidget(self._wrap_table("💰 Parite Bazlı", self.sym_table))

        # --- En iyi/kötü 5 trade ---
        self.best_table = self._make_trade_table()
        self.worst_table = self._make_trade_table()
        tr_row = QHBoxLayout()
        tr_row.addWidget(self._wrap_table("🏆 En İyi 5 Trade", self.best_table))
        tr_row.addWidget(self._wrap_table("💀 En Kötü 5 Trade", self.worst_table))

        # Ana layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addLayout(period_row)
        layout.addLayout(cards_row)
        layout.addLayout(tables_row, 1)
        layout.addLayout(tr_row, 1)

    def _make_bucket_table(self, columns: list[str]) -> QTableView:
        model = QStandardItemModel(0, len(columns))
        model.setHorizontalHeaderLabels(columns)
        model.setSortRole(Qt.UserRole)
        table = QTableView()
        table.setModel(model)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setSortingEnabled(True)
        return table

    def _make_trade_table(self) -> QTableView:
        cols = ["P&L", "Parite", "TF", "Pattern", "Yön", "Zaman"]
        return self._make_bucket_table(cols)

    def _wrap_table(self, title: str, table: QTableView) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(title)
        lbl.setStyleSheet("color: #d4a72c; font-weight: bold; padding-bottom: 4px;")
        l.addWidget(lbl)
        l.addWidget(table)
        return w

    def _on_period_changed(self, idx: int) -> None:
        self._period = self.PERIODS[idx][1]
        self.refresh()

    def refresh(self) -> None:
        now_ms = int(time.time() * 1000)
        period_ms = {
            "day": 24 * 3600 * 1000,
            "week": 7 * 24 * 3600 * 1000,
            "month": 30 * 24 * 3600 * 1000,
            "all": None,
        }[self._period]
        if period_ms is None:
            where = ""
            params: tuple = ()
        else:
            where = "WHERE pt.closed_at >= ?"
            params = (now_ms - period_ms,)

        cur = self.store._conn.execute(f"""
            SELECT pt.symbol, pt.interval, pt.pattern, pt.direction,
                   pt.outcome, pt.pnl_usd, pt.position_usd, pt.leverage,
                   pt.closed_at
            FROM paper_trades pt
            {where} {'AND' if where else 'WHERE'} pt.closed_at IS NOT NULL
            ORDER BY pt.closed_at DESC
        """, params)
        trades = cur.fetchall()

        # Account snapshot
        acc = self.store._conn.execute(
            "SELECT initial_equity, current_equity, total_pnl "
            "FROM paper_account WHERE id = 1"
        ).fetchone()
        if acc:
            initial, current, total_pnl = acc
        else:
            initial, current, total_pnl = 1000.0, 1000.0, 0.0

        n = len(trades)
        tp = sum(1 for t in trades if t[4] == "TP")
        stp = sum(1 for t in trades if t[4] == "STOP")
        decided = tp + stp
        wr = (tp / decided * 100) if decided else 0
        period_pnl = sum(t[5] or 0 for t in trades)
        avg_lev = (sum(t[7] or 1 for t in trades) / n) if n else 0

        # Kart güncelle
        self.l_equity.setText(f"${current:.2f}")
        eq_color = "#26a69a" if current >= initial else "#ef5350"
        self.l_equity.setStyleSheet(f"color: {eq_color}; font-size: 16px; font-weight: bold;")
        self.l_pnl.setText(f"{'+' if period_pnl >= 0 else ''}${period_pnl:.2f}")
        pnl_color = "#26a69a" if period_pnl > 0 else ("#ef5350" if period_pnl < 0 else "#888")
        self.l_pnl.setStyleSheet(f"color: {pnl_color}; font-size: 16px; font-weight: bold;")
        self.l_total_pnl.setText(f"{'+' if total_pnl >= 0 else ''}${total_pnl:.2f}")
        tpnl_color = "#26a69a" if total_pnl > 0 else ("#ef5350" if total_pnl < 0 else "#888")
        self.l_total_pnl.setStyleSheet(f"color: {tpnl_color}; font-size: 16px; font-weight: bold;")
        self.l_wr.setText(f"{wr:.1f}%" if decided else "—")
        wr_color = "#26a69a" if wr >= 60 else ("#ff9800" if wr >= 45 else "#ef5350") if decided else "#888"
        self.l_wr.setStyleSheet(f"color: {wr_color}; font-size: 16px; font-weight: bold;")
        self.l_trades.setText(str(n))
        self.l_tp.setText(str(tp))
        self.l_stop.setText(str(stp))
        self.l_lev.setText(f"{avg_lev:.1f}x")

        # Bucket tabloları
        by_tf = defaultdict(list)
        by_pat = defaultdict(list)
        by_sym = defaultdict(list)
        for t in trades:
            entry = (t[4], t[5] or 0)
            by_tf[t[1]].append(entry)
            by_pat[t[2]].append(entry)
            by_sym[t[0]].append(entry)

        self._fill_bucket(self.tf_table, by_tf)
        self._fill_bucket(self.pat_table, by_pat)
        self._fill_bucket(self.sym_table, by_sym)

        # Best/Worst 5
        sorted_by_pnl = sorted(trades, key=lambda t: -(t[5] or 0))
        best = [t for t in sorted_by_pnl[:5] if (t[5] or 0) > 0]
        worst = [t for t in sorted_by_pnl[-5:][::-1] if (t[5] or 0) < 0]
        self._fill_trades(self.best_table, best, color_positive=True)
        self._fill_trades(self.worst_table, worst, color_positive=False)

    def _fill_bucket(self, table: QTableView, buckets: dict[str, list]) -> None:
        from terminal.ui.styles import GREEN, RED, TEXT_DIM
        model = table.model()
        table.setSortingEnabled(False)
        model.removeRows(0, model.rowCount())
        rows_sorted = sorted(buckets.items(), key=lambda kv: -sum(x[1] for x in kv[1]))
        for name, items in rows_sorted:
            n = len(items)
            tp = sum(1 for x in items if x[0] == "TP")
            stp = sum(1 for x in items if x[0] == "STOP")
            decided = tp + stp
            wr = (tp / decided * 100) if decided else 0
            pnl = sum(x[1] for x in items)
            cells = [
                (name, name),
                (str(n), n),
                (str(tp), tp),
                (str(stp), stp),
                (f"{wr:.1f}%", wr),
                (f"{'+' if pnl >= 0 else ''}{pnl:.2f}", pnl),
            ]
            items_row = []
            for txt, sort_val in cells:
                it = QStandardItem(txt)
                it.setData(sort_val, Qt.UserRole)
                items_row.append(it)
            # Renk: P&L hücresi
            pnl_color = QColor(GREEN) if pnl > 0 else (QColor(RED) if pnl < 0 else QColor(TEXT_DIM))
            items_row[5].setForeground(pnl_color)
            model.appendRow(items_row)
        table.setSortingEnabled(True)

    def _fill_trades(self, table: QTableView, trades: list, color_positive: bool) -> None:
        from terminal.ui.styles import GREEN, RED
        model = table.model()
        table.setSortingEnabled(False)
        model.removeRows(0, model.rowCount())
        for t in trades:
            pnl = t[5] or 0
            cells = [
                (f"{'+' if pnl >= 0 else ''}${pnl:.2f}", pnl),
                (t[0], t[0]),
                (t[1], t[1]),
                (t[2], t[2]),
                ("BULL" if t[3] == "bull" else "BEAR", t[3]),
                (_fmt_ts(t[8]), t[8] or 0),
            ]
            items_row = []
            for txt, sort_val in cells:
                it = QStandardItem(txt)
                it.setData(sort_val, Qt.UserRole)
                items_row.append(it)
            items_row[0].setForeground(QColor(GREEN if color_positive else RED))
            model.appendRow(items_row)
        table.setSortingEnabled(True)

    def _send_telegram(self) -> None:
        try:
            from terminal.cli.journal import journal as gen_journal
            from terminal.telegram_bot.client import TelegramClient
            report = gen_journal(self.store, period=self._period)
            tg = TelegramClient()
            tg.send_message(report, parse_mode="Markdown")
            self.tg_btn.setText("✓ Yollandı")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self.tg_btn.setText("📤 Telegram'a Yolla"))
        except Exception as e:
            log.exception("Telegram journal: %s", e)
            self.tg_btn.setText("⚠ Hata")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(2000, lambda: self.tg_btn.setText("📤 Telegram'a Yolla"))
