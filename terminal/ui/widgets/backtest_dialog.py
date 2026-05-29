"""Backtest çalıştırma dialog'u: parite/aralık/mum sayısı seçimi + ilerleme.

Backtest arka planda thread'de çalışır; UI bloklanmaz. Progress callback
Qt sinyali üzerinden ana thread'e taşınır.
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QProgressBar, QPushButton, QSpinBox, QTextEdit, QVBoxLayout,
)

from terminal.data.mexc_futures import MexcFuturesClient
from terminal.db.store import Store
from terminal.karakter.runner import run_lab

log = logging.getLogger(__name__)


class _LabWorker(QThread):
    """Karakter lab'i arka planda çalıştırır; progress/sonuc sinyaller ile döner."""

    progress = Signal(str)
    finished_ok = Signal(int)   # run_id
    failed = Signal(str)

    def __init__(self, symbols: list[str], intervals: list[str], bars: int) -> None:
        super().__init__()
        self.symbols = symbols
        self.intervals = intervals
        self.bars = bars

    def run(self) -> None:
        client = MexcFuturesClient()   # canlı sistemle aynı veri kaynağı (futures)
        store = Store()
        try:
            run_id = run_lab(
                self.symbols, self.intervals, self.bars, store, client,
                progress=lambda msg: self.progress.emit(msg),
            )
            self.finished_ok.emit(run_id)
        except Exception as e:
            log.exception("Backtest hatası")
            self.failed.emit(str(e))
        finally:
            try:
                client.close()
            except Exception:
                pass
            try:
                store.close()
            except Exception:
                pass


class BacktestDialog(QDialog):
    """Kullanıcıya backtest parametrelerini sorar ve çalıştırır."""

    finished_ok = Signal()  # parent karakter sekmesini yenilesin diye

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Backtest Çalıştır — Karakter Lab")
        self.resize(720, 520)

        # Inputlar
        self.symbols_input = QLineEdit("BTCUSDT,ETHUSDT,SOLUSDT,AVAXUSDT,DOGEUSDT,XRPUSDT,LINKUSDT,BNBUSDT")
        self.intervals_input = QLineEdit("15m,30m,60m,4h")
        self.bars_input = QSpinBox()
        self.bars_input.setMinimum(200)
        self.bars_input.setMaximum(20000)
        self.bars_input.setSingleStep(500)
        self.bars_input.setValue(5000)
        self.bars_input.setSuffix("  mum")

        form = QVBoxLayout()
        form.addWidget(QLabel("Pariteler (virgülle ayır):"))
        form.addWidget(self.symbols_input)
        form.addWidget(QLabel("Aralıklar (virgülle ayır — 15m, 30m, 60m, 4h, 1d):"))
        form.addWidget(self.intervals_input)
        row = QHBoxLayout()
        row.addWidget(QLabel("Her kombinasyon için mum:"))
        row.addWidget(self.bars_input)
        row.addStretch()
        form.addLayout(row)

        # Butonlar
        self.start_btn = QPushButton("Backtest'i Başlat")
        self.start_btn.clicked.connect(self._on_start)
        self.cancel_btn = QPushButton("Kapat")
        self.cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.start_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.cancel_btn)

        # İlerleme
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # belirsiz
        self.progress.setVisible(False)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(200)
        self.log.setStyleSheet("font-family: 'Consolas', monospace; font-size: 11px;")

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(btn_row)
        layout.addWidget(self.progress)
        layout.addWidget(QLabel("İlerleme:"))
        layout.addWidget(self.log, 1)

        self._worker: _LabWorker | None = None

    def _on_start(self) -> None:
        symbols = [s.strip().upper() for s in self.symbols_input.text().split(",") if s.strip()]
        intervals = [i.strip() for i in self.intervals_input.text().split(",") if i.strip()]
        bars = self.bars_input.value()

        if not symbols or not intervals:
            QMessageBox.warning(self, "Eksik bilgi", "Parite ve aralık listesi boş olamaz.")
            return

        # Interval normalize (1h → 60m vs)
        from terminal.config import INTERVAL_ALIASES, VALID_INTERVALS
        norm = []
        for iv in intervals:
            v = INTERVAL_ALIASES.get(iv, iv)
            if v not in VALID_INTERVALS:
                QMessageBox.warning(self, "Geçersiz aralık",
                                    f"'{iv}' geçerli değil. Geçerli: {sorted(VALID_INTERVALS)}")
                return
            norm.append(v)
        intervals = norm

        total = len(symbols) * len(intervals)
        self.log.append(f"<b>Başlıyor: {len(symbols)} parite × {len(intervals)} TF × {bars} mum = {total} kombinasyon</b>\n")

        self.start_btn.setEnabled(False)
        self.progress.setVisible(True)

        self._worker = _LabWorker(symbols, intervals, bars)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, msg: str) -> None:
        self.log.append(msg)
        # Scroll to bottom
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, run_id: int) -> None:
        self.progress.setVisible(False)
        self.start_btn.setEnabled(True)
        self.log.append(f"\n<b style='color:#4caf50'>✓ Tamamlandı (run_id={run_id})</b>")
        self.log.append("Karakter skorları tablosu artık yenilenebilir.")
        self.finished_ok.emit()

    def _on_failed(self, err: str) -> None:
        self.progress.setVisible(False)
        self.start_btn.setEnabled(True)
        self.log.append(f"\n<b style='color:#ef5350'>HATA: {err}</b>")
        QMessageBox.critical(self, "Backtest hatası", err)

    def reject(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            ans = QMessageBox.question(
                self, "Çalışan backtest",
                "Backtest hâlâ çalışıyor. Yine de kapatmak istiyor musun?\n"
                "(Çalışan iş arka planda biter, sonuç DB'ye yazılır.)",
            )
            if ans != QMessageBox.Yes:
                return
        super().reject()
