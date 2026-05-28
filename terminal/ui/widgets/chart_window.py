"""Setup için chart penceresi — X-A-B-C-D pivotları, PRZ kutusu, Entry/SL/TP
çizgileri ile birlikte gömülü mum grafiği.

Mumlar önce DB'den (klines tablosu) alınır; yetersizse MEXC'den canlı fetch
yapılır (kullanıcıya progress mesajıyla).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QLabel, QMessageBox, QScrollArea, QVBoxLayout,
)

from terminal.data.mexc_client import MexcClient, MexcError
from terminal.db.store import Store
from terminal.detection.models import Setup
from terminal.telegram_bot.charts import render_setup_chart

log = logging.getLogger(__name__)

_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "60m": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1W": 604_800_000,
}


def _window_bounds(setup: Setup, exit_time: int | None,
                   padding_before: int, padding_after: int,
                   padding_after_exit: int = 8) -> tuple[int, int]:
    """Chart penceresi (start_t, end_t). Kapanmışsa çıkışa kadar uzar."""
    interval_ms = _INTERVAL_MS.get(setup.interval, 3_600_000)
    start_t = setup.pivots["X"].time - padding_before * interval_ms
    if exit_time is not None:
        end_t = exit_time + padding_after_exit * interval_ms
    else:
        end_t = setup.pivots["D"].time + padding_after * interval_ms
    return start_t, end_t


def _klines_from_db(store: Store, setup: Setup, exit_time: int | None = None,
                    padding_before: int = 10, padding_after: int = 30) -> list[dict] | None:
    """X öncesinden D (veya çıkış) sonrasına kadar mumları DB'den getir; yetersizse None."""
    interval_ms = _INTERVAL_MS.get(setup.interval, 3_600_000)
    start_t, end_t = _window_bounds(setup, exit_time, padding_before, padding_after)

    cur = store._conn.execute(
        """SELECT open_time, close_time, open, high, low, close, volume, quote_volume
           FROM klines
           WHERE symbol = ? AND interval = ?
             AND open_time >= ? AND open_time <= ?
           ORDER BY open_time""",
        (setup.symbol, setup.interval, start_t, end_t),
    )
    rows = cur.fetchall()
    if not rows:
        return None
    expected_bars = (end_t - start_t) // interval_ms
    if len(rows) < expected_bars * 0.5:
        return None  # çok az mum, MEXC'den çekmek gerek
    return [
        {"open_time": r[0], "close_time": r[1],
         "open": r[2], "high": r[3], "low": r[4], "close": r[5],
         "volume": r[6], "quote_volume": r[7]}
        for r in rows
    ]


def _klines_from_mexc(setup: Setup, exit_time: int | None = None,
                     padding_before: int = 10, padding_after: int = 30) -> list[dict] | None:
    """MEXC'den gerekli pencereyi çek (paginated, doğru tarih aralığı).

    Geçmiş tarihli setup'lar için: klines_paginated'e end_time_ms parametresi
    geçerek doğru zaman penceresinin sonundan geriye doğru çek.
    """
    interval_ms = _INTERVAL_MS.get(setup.interval, 3_600_000)
    start_t, end_t = _window_bounds(setup, exit_time, padding_before, padding_after)
    bars_needed = int((end_t - start_t) // interval_ms) + 30  # ekstra tampon
    bars_needed = max(bars_needed, 100)
    try:
        client = MexcClient()
        try:
            klines = client.klines_paginated(
                setup.symbol, setup.interval,
                bars_needed,
                end_time_ms=end_t,
                throttle=0.05,
            )
        finally:
            client.close()
    except MexcError:
        return None
    return [k for k in klines if start_t <= k["open_time"] <= end_t]


def _lifecycle_exit(store: Store, setup_id: int | None) -> tuple[int, str] | None:
    """Kapanmış setup için (exit_time_ms, outcome). Açık/bilinmiyorsa None."""
    if setup_id is None:
        return None
    try:
        row = store.get_lifecycle(setup_id)
    except Exception:
        return None
    if row and row["state"] in ("TP", "STOP", "ZI", "EO") and row["exited_at"]:
        return int(row["exited_at"]), row["state"]
    return None


class ChartWindow(QDialog):
    """Setup için gömülü chart gösteren modal pencere."""

    def __init__(self, setup: Setup, store: Store, parent=None,
                 setup_id: int | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            f"{setup.symbol} {setup.interval} — {setup.direction.upper()} "
            f"{setup.pattern_name}"
            + (f"  ·  Q {setup.q_score} {setup.q_category}" if setup.q_score else "")
        )
        # Pencere maksimize açılsın — kullanıcı her chart için manuel
        # büyütmek zorunda kalmasın.
        self.setWindowState(self.windowState() | Qt.WindowMaximized)
        self.resize(1400, 850)  # ekran kapsamı yoksa fallback boyutu

        # Kapanmışsa pencereyi çıkış anına kadar uzat + işaretle
        exit_marker = _lifecycle_exit(store, setup_id)
        exit_time = exit_marker[0] if exit_marker else None

        # 1) DB'den dene
        klines = _klines_from_db(store, setup, exit_time=exit_time)
        if klines is None:
            # 2) Yetersiz → MEXC fetch
            self.setWindowTitle(self.windowTitle() + " (MEXC fetch…)")
            klines = _klines_from_mexc(setup, exit_time=exit_time)

        if not klines or len(klines) < 20:
            QMessageBox.warning(
                self, "Grafik çizilemedi",
                "Yeterli mum verisi bulunamadı. Önce run_live veya "
                "run_live_multi ile veri akışını çalıştır.",
            )
            self.close()
            return

        try:
            png_bytes = render_setup_chart(setup, klines, exit_marker=exit_marker)
        except Exception as e:
            log.exception("Chart render hatası")
            QMessageBox.critical(self, "Hata", f"Grafik üretimi başarısız: {e}")
            self.close()
            return

        pixmap = QPixmap()
        pixmap.loadFromData(png_bytes)

        label = QLabel()
        label.setPixmap(pixmap)
        label.setAlignment(Qt.AlignCenter)
        label.setScaledContents(False)

        scroll = QScrollArea()
        scroll.setWidget(label)
        scroll.setWidgetResizable(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
