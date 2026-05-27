"""Potansiyel Setup'lar sekmesi — henüz D pivot oluşmamış formasyonlar.

Live tracker fiyat henüz D bölgesine girmeden X-A-B-C uyumlu yapılar
tespit eder ve potential_patterns tablosuna yazar. Bu sekme onları
listeler — kullanıcı önceden hazırlık yapabilir.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QTableView, QVBoxLayout, QWidget,
)

from terminal.db.store import Store

log = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=3))


def _fmt_ts(ms: int | None) -> str:
    if ms is None:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%m-%d %H:%M")


COLUMNS = ["Parite", "TF", "Pattern", "Yön", "D ideal",
           "D alt", "D üst", "B", "C", "C zaman", "Tespit"]


class PotentialTab(QWidget):
    """Potansiyel pattern'leri listele. Satıra tıkla → chart aç."""

    def __init__(self, store: Store, parent=None) -> None:
        super().__init__(parent)
        self.store = store

        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.model.setSortRole(Qt.UserRole)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(self._on_double_clicked)

        self.count_label = QLabel("0 potansiyel")
        self.count_label.setStyleSheet("color: #d4a72c; font-weight: bold;")

        info = QLabel("ℹ️ Fiyat D bölgesine girerse formasyon tamamlanır. "
                      "Çift tık → chart görüntüsü.")
        info.setStyleSheet("color: #888;")

        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self._force_refresh)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.count_label)
        toolbar.addSpacing(16)
        toolbar.addWidget(info)
        toolbar.addStretch()
        toolbar.addWidget(refresh_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

    def refresh(self) -> None:
        from terminal.ui.styles import GREEN, RED
        rows = self.store.list_potentials(limit=200)
        self.count_label.setText(f"{len(rows)} potansiyel")
        self.table.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        self._rows = rows  # double-click için
        for r in rows:
            (_id, sym, ivl, pat, dirn,
             x_t, x_p, a_t, a_p, b_t, b_p, c_t, c_p,
             d_low, d_high, d_ideal, b_ratio, c_ratio,
             detected, status) = r
            cells = [
                (sym, sym),
                (ivl, ivl),
                (pat, pat),
                ("BULL" if dirn == "bull" else "BEAR", dirn),
                (f"{d_ideal:.6g}", float(d_ideal)),
                (f"{d_low:.6g}", float(d_low)),
                (f"{d_high:.6g}", float(d_high)),
                (f"{b_ratio:.3f}", float(b_ratio)),
                (f"{c_ratio:.3f}", float(c_ratio)),
                (_fmt_ts(c_t), int(c_t)),
                (_fmt_ts(detected), int(detected)),
            ]
            items = []
            for txt, sv in cells:
                it = QStandardItem(txt)
                it.setData(sv, Qt.UserRole)
                items.append(it)
            dir_color = QColor(GREEN) if dirn == "bull" else QColor(RED)
            items[3].setForeground(dir_color)
            self.model.appendRow(items)
        self.table.setSortingEnabled(True)

    def _force_refresh(self) -> None:
        mw = self.window()
        if hasattr(mw, "refresh_all"):
            mw.refresh_all(force=True)
        else:
            self.refresh()

    def _on_double_clicked(self, index) -> None:
        """Çift tık → potansiyel pattern chart açar.

        Sıralama sonrası model.row != _rows index olabilir. Symbol+C zamanı
        ile orijinal DB row'unu bul.
        """
        sym = self.model.item(index.row(), 0).text()
        c_t = self.model.item(index.row(), 9).data(Qt.UserRole)
        if not hasattr(self, "_rows"):
            return
        r = next((rr for rr in self._rows if rr[1] == sym and rr[11] == c_t), None)
        if r is None:
            return

        try:
            from PySide6.QtGui import QPixmap
            from PySide6.QtWidgets import QDialog, QLabel as QLab, QScrollArea, QVBoxLayout

            from terminal.data.mexc_client import MexcClient
            from terminal.detection.pivots import Pivot
            from terminal.detection.potential import PotentialPattern
            from terminal.detection.spec import PATTERNS
            from terminal.telegram_bot.charts import render_potential_chart

            (_id, sym, ivl, pat_name, dirn,
             x_t, x_p, a_t, a_p, b_t, b_p, c_t, c_p,
             d_low, d_high, d_ideal, b_ratio, c_ratio,
             detected, status) = r

            # DB satırından PotentialPattern objesi inşa et — render'a ver
            spec = PATTERNS.get(pat_name)
            if spec is None:
                log.warning("Pattern spec bulunamadı: %s", pat_name)
                return
            x_kind = "low" if dirn == "bull" else "high"
            a_kind = "high" if dirn == "bull" else "low"
            b_kind = x_kind  # alternating: X=A=karşıt sıra
            c_kind = a_kind
            match = PotentialPattern(
                spec=spec, direction=dirn,
                x=Pivot(index=0, time=x_t, price=x_p, kind=x_kind),
                a=Pivot(index=1, time=a_t, price=a_p, kind=a_kind),
                b=Pivot(index=2, time=b_t, price=b_p, kind=b_kind),
                c=Pivot(index=3, time=c_t, price=c_p, kind=c_kind),
                b_ratio=b_ratio, c_ratio=c_ratio,
                d_zone_low=d_low, d_zone_high=d_high, d_ideal_price=d_ideal,
            )

            # Mum verisi — X pivotundan itibaren güncele kadar (yeterli kapsama)
            client = MexcClient()
            # Pagination ile X'ten sonraki tüm mumları çek (max 500)
            interval_ms = {
                "15m": 900_000, "30m": 1_800_000, "60m": 3_600_000,
                "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000,
            }.get(ivl, 3_600_000)
            import time as _t
            now_ms = int(_t.time() * 1000)
            bars_since_x = max(50, (now_ms - x_t) // interval_ms + 30)
            klines = client.klines_paginated(sym, ivl, min(int(bars_since_x), 1000))
            png = render_potential_chart(sym, ivl, klines, existing_match=match)
            if png is None:
                log.warning("render_potential_chart None döndü")
                return
            dlg = QDialog(self)
            dlg.setWindowTitle(f"{sym} {ivl} — Potansiyel {pat_name}")
            dlg.setWindowState(dlg.windowState() | Qt.WindowMaximized)
            dlg.resize(1400, 850)
            lbl = QLab()
            px = QPixmap()
            px.loadFromData(png)
            lbl.setPixmap(px)
            scroll = QScrollArea()
            scroll.setWidget(lbl)
            scroll.setWidgetResizable(True)
            lay = QVBoxLayout(dlg)
            lay.addWidget(scroll)
            dlg.exec()
        except Exception as e:
            log.exception("Potansiyel chart: %s", e)
