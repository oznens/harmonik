"""Tradeler sekmesi — açık paper pozisyonlar + kapanan trade'ler dashboard'u.

Üstte özet kartlar (Equity / Toplam P&L / WR / Açık), ortada AÇIK POZİSYONLAR
tablosu (canlı), altta SON KAPANAN TRADELER (50 kayıt). Yenile butonu
parent.refresh_all(force=True) çağırır.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QPushButton, QTableView, QVBoxLayout, QWidget,
)

from terminal.db.store import Store

log = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=3))


def _fmt_ts(ms: int | None) -> str:
    if ms is None:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%m-%d %H:%M")


def _fmt_age(opened_ms: int | None) -> str:
    if opened_ms is None:
        return "—"
    delta = int(time.time() * 1000) - opened_ms
    if delta < 0:
        return "—"
    mins = delta // 60000
    if mins < 60:
        return f"{mins}dk"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}sa {mins % 60}dk"
    days = hrs // 24
    return f"{days}g {hrs % 24}sa"


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6g}"


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


class TradesTab(QWidget):
    """Paper trade canlı dashboard'u."""

    def __init__(self, store: Store, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        # Paper tabloları yoksa oluştur
        from terminal.paper.engine import PaperEngine
        PaperEngine(store)

        # --- Üst toolbar ---
        top_row = QHBoxLayout()
        title = QLabel("💼 Paper Trade Dashboard")
        title.setStyleSheet("color: #d4a72c; font-weight: bold; font-size: 14px;")
        top_row.addWidget(title)
        top_row.addStretch()
        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self._force_refresh)
        top_row.addWidget(refresh_btn)

        # --- Özet kartlar ---
        self.c_equity, self.l_equity = _stat_card("EQUITY", "$1000.00")
        self.c_pnl, self.l_pnl = _stat_card("TOPLAM P&L", "$0.00", "#d4a72c")
        self.c_pnl_pct, self.l_pnl_pct = _stat_card("P&L %", "0.0%", "#d4a72c")
        self.c_wr, self.l_wr = _stat_card("WIN RATE", "—", "#26a69a")
        self.c_total, self.l_total = _stat_card("TOPLAM TRADE", "0")
        self.c_tp, self.l_tp = _stat_card("TP", "0", "#26a69a")
        self.c_stop, self.l_stop = _stat_card("STOP", "0", "#ef5350")
        self.c_open, self.l_open = _stat_card("AÇIK POZ.", "0", "#42a5f5")

        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        for c in [self.c_equity, self.c_pnl, self.c_pnl_pct, self.c_wr,
                  self.c_total, self.c_tp, self.c_stop, self.c_open]:
            cards_row.addWidget(c)
        cards_row.addStretch()

        # --- AÇIK POZİSYONLAR ---
        self.open_table = self._make_table([
            "Parite", "TF", "Pattern", "Yön", "Entry", "Stop", "TP1",
            "Pozisyon", "Lev", "Risk", "Açıldı", "Yaş",
        ])

        # --- KAPANAN TRADELER ---
        self.closed_table = self._make_table([
            "Parite", "TF", "Pattern", "Yön", "Entry", "Exit",
            "Outcome", "P&L", "Lev", "Kapandı",
        ])

        # Ana layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addLayout(top_row)
        layout.addLayout(cards_row)

        # Açık pozisyonlar başlık + tablo
        open_lbl = QLabel("🟢 Açık Pozisyonlar")
        open_lbl.setStyleSheet("color: #42a5f5; font-weight: bold; padding-top: 4px;")
        layout.addWidget(open_lbl)
        layout.addWidget(self.open_table, 1)

        # Kapanan trades başlık + tablo
        closed_lbl = QLabel("📋 Son Kapanan Tradeler (50)")
        closed_lbl.setStyleSheet("color: #888; font-weight: bold; padding-top: 4px;")
        layout.addWidget(closed_lbl)
        layout.addWidget(self.closed_table, 1)

    def _make_table(self, columns: list[str]) -> QTableView:
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

    def refresh(self) -> None:
        # --- Account snapshot ---
        acc = self.store._conn.execute(
            "SELECT initial_equity, current_equity, total_trades, tp_count, "
            "stop_count, total_pnl FROM paper_account WHERE id = 1"
        ).fetchone()
        if acc:
            initial, current, total, tp, stop, total_pnl = acc
        else:
            initial, current, total, tp, stop, total_pnl = 1000.0, 1000.0, 0, 0, 0, 0.0

        decided = tp + stop
        wr = (tp / decided * 100) if decided else 0
        pnl_pct = ((current - initial) / initial * 100) if initial else 0

        # --- Açık pozisyon sayısı ---
        open_count_row = self.store._conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE closed_at IS NULL"
        ).fetchone()
        open_count = int(open_count_row[0]) if open_count_row else 0

        # Kartlar
        self.l_equity.setText(f"${current:.2f}")
        eq_color = "#26a69a" if current >= initial else "#ef5350"
        self.l_equity.setStyleSheet(f"color: {eq_color}; font-size: 16px; font-weight: bold;")
        self.l_pnl.setText(f"{'+' if total_pnl >= 0 else ''}${total_pnl:.2f}")
        pnl_color = "#26a69a" if total_pnl > 0 else ("#ef5350" if total_pnl < 0 else "#888")
        self.l_pnl.setStyleSheet(f"color: {pnl_color}; font-size: 16px; font-weight: bold;")
        self.l_pnl_pct.setText(f"{'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%")
        self.l_pnl_pct.setStyleSheet(f"color: {pnl_color}; font-size: 16px; font-weight: bold;")
        self.l_wr.setText(f"{wr:.1f}%" if decided else "—")
        wr_color = ("#26a69a" if wr >= 60 else "#ff9800" if wr >= 45 else "#ef5350") if decided else "#888"
        self.l_wr.setStyleSheet(f"color: {wr_color}; font-size: 16px; font-weight: bold;")
        self.l_total.setText(str(total))
        self.l_tp.setText(str(tp))
        self.l_stop.setText(str(stop))
        self.l_open.setText(str(open_count))

        # --- Açık pozisyonlar tablosu ---
        self._fill_open()
        # --- Kapanan tablo ---
        self._fill_closed()

    def _fill_open(self) -> None:
        from terminal.ui.styles import GREEN, RED, TEXT_DIM
        cur = self.store._conn.execute(
            """SELECT symbol, interval, pattern, direction,
                      entry_price, stop_price, tp1_price,
                      position_usd, leverage, risk_usd, opened_at
               FROM paper_trades
               WHERE closed_at IS NULL
               ORDER BY opened_at DESC"""
        )
        rows = cur.fetchall()
        model = self.open_table.model()
        self.open_table.setSortingEnabled(False)
        model.removeRows(0, model.rowCount())
        for r in rows:
            (sym, ivl, pat, dirn, entry, stop, tp1,
             pos, lev, risk, opened) = r
            dir_txt = "BULL ▲" if dirn == "bull" else "BEAR ▼"
            cells = [
                (sym, sym),
                (ivl, ivl),
                (pat, pat),
                (dir_txt, dirn),
                (_fmt_price(entry), entry),
                (_fmt_price(stop), stop),
                (_fmt_price(tp1), tp1),
                (f"${pos:.0f}", pos),
                (f"{lev:.0f}x", lev),
                (f"${risk:.0f}", risk),
                (_fmt_ts(opened), opened or 0),
                (_fmt_age(opened), opened or 0),
            ]
            items_row = []
            for txt, sort_val in cells:
                it = QStandardItem(txt)
                it.setData(sort_val, Qt.UserRole)
                items_row.append(it)
            # Yön rengi
            items_row[3].setForeground(QColor(GREEN if dirn == "bull" else RED))
            items_row[11].setForeground(QColor(TEXT_DIM))
            model.appendRow(items_row)
        self.open_table.setSortingEnabled(True)

    def _fill_closed(self) -> None:
        from terminal.ui.styles import GREEN, RED, TEXT_DIM
        cur = self.store._conn.execute(
            """SELECT symbol, interval, pattern, direction,
                      entry_price, exit_price, outcome, pnl_usd,
                      leverage, closed_at
               FROM paper_trades
               WHERE closed_at IS NOT NULL
               ORDER BY closed_at DESC
               LIMIT 50"""
        )
        rows = cur.fetchall()
        model = self.closed_table.model()
        self.closed_table.setSortingEnabled(False)
        model.removeRows(0, model.rowCount())
        for r in rows:
            (sym, ivl, pat, dirn, entry, exitp, outcome, pnl,
             lev, closed) = r
            pnl = pnl or 0
            dir_txt = "BULL ▲" if dirn == "bull" else "BEAR ▼"
            outcome_color = {
                "TP": GREEN, "STOP": RED, "EO": TEXT_DIM, "ZI": TEXT_DIM,
            }.get(outcome, TEXT_DIM)
            cells = [
                (sym, sym),
                (ivl, ivl),
                (pat, pat),
                (dir_txt, dirn),
                (_fmt_price(entry), entry),
                (_fmt_price(exitp), exitp or 0),
                (outcome or "—", outcome or ""),
                (f"{'+' if pnl >= 0 else ''}${pnl:.2f}", pnl),
                (f"{lev:.0f}x", lev),
                (_fmt_ts(closed), closed or 0),
            ]
            items_row = []
            for txt, sort_val in cells:
                it = QStandardItem(txt)
                it.setData(sort_val, Qt.UserRole)
                items_row.append(it)
            items_row[3].setForeground(QColor(GREEN if dirn == "bull" else RED))
            items_row[6].setForeground(QColor(outcome_color))
            pnl_color = GREEN if pnl > 0 else (RED if pnl < 0 else TEXT_DIM)
            items_row[7].setForeground(QColor(pnl_color))
            model.appendRow(items_row)
        self.closed_table.setSortingEnabled(True)

    def _force_refresh(self) -> None:
        mw = self.window()
        if hasattr(mw, "refresh_all"):
            mw.refresh_all(force=True)
        else:
            self.refresh()
