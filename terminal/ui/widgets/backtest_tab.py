"""Backtest sekmesi — seçilen parite/TF/aralık/giriş modunda tarihsel backtest
çalıştırıp HER İŞLEMİ grafikte (XABCD + giriş/çıkış) gösterir.

Veri MEXC futures'tan çekilir (canlı ile aynı kaynak, global throttle'lı), motor
terminal.backtest.engine.run_backtest. Ağ + simülasyon worker thread'de.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from terminal.backtest.engine import load_db_klines, run_backtest
from terminal.config import DB_PATH
from terminal.data.mexc_futures import MexcFuturesClient
from terminal.db.store import Store

log = logging.getLogger(__name__)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_HTML = _ASSETS / "backtest.html"

# Interval → bir günde kaç bar (aralık × gün = bar sayısı)
_BARS_PER_DAY = {"15m": 96, "30m": 48, "60m": 24, "4h": 6, "1d": 1}
_MAX_BARS = 20000  # çok uzun + düşük TF (15m×2yıl=70k) için tavan


class BacktestBridge(QObject):
    """JS <-> Python köprüsü."""
    resultReady = Signal(str)   # backtest payload (JSON)
    failed = Signal(str)
    pageReady = Signal()
    requested = Signal(str, str, int, str, str, str)  # symbol, interval, days, mode, target, abcd

    @Slot()
    def ready(self) -> None:
        self.pageReady.emit()

    @Slot(str, str, int, str, str, str)
    def requestBacktest(self, symbol: str, interval: str, days: int,
                        mode: str, target: str, abcd: str) -> None:
        self.requested.emit(symbol, interval, days, mode, target, abcd)


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:  # noqa: D401
        try:
            result = self._fn()
        except Exception as e:
            try:
                self.signals.failed.emit(str(e))
            except RuntimeError:
                pass
            return
        try:
            self.signals.done.emit(result)
        except RuntimeError:
            pass


class BacktestTab(QWidget):
    """Backtest sekmesi."""

    def __init__(self, store=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._tasks: set[_Task] = set()
        # Worker thread kendi Store bağlantısını açar (cross-thread güvenli)
        self._db_path = str(store.path) if store is not None else str(DB_PATH)

        self.view = QWebEngineView(self)
        self.bridge = BacktestBridge()
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.bridge.requested.connect(self._on_request)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.view.setUrl(QUrl.fromLocalFile(str(_HTML)))

    def _run(self, fn, on_done, on_fail) -> None:
        task = _Task(fn)
        task.signals.done.connect(on_done)
        task.signals.done.connect(lambda _=None, t=task: self._tasks.discard(t))
        task.signals.failed.connect(on_fail)
        task.signals.failed.connect(lambda _=None, t=task: self._tasks.discard(t))
        self._tasks.add(task)
        self._pool.start(task)

    @Slot(str, str, int, str, str, str)
    def _on_request(self, symbol: str, interval: str, days: int,
                    mode: str, target: str, abcd: str) -> None:
        bars = min(_MAX_BARS, max(200, days * _BARS_PER_DAY.get(interval, 24)))
        include_abcd = abcd == "all"   # "harmonic" → AB=CD hariç (canlıyla aynı)

        def work():
            store = Store(self._db_path)   # worker thread'e ait bağlantı
            source = "DB"
            try:
                klines = load_db_klines(store, symbol, interval, bars)
                # DB yetersizse canlı çek + cache'le (sonraki koşum DB'den hızlı)
                if len(klines) < max(100, int(bars * 0.6)):
                    client = MexcFuturesClient()
                    try:
                        klines = client.klines_paginated(symbol, interval, bars, throttle=0.08)
                    finally:
                        try:
                            client.close()
                        except Exception:
                            pass
                    if klines:
                        store.upsert_klines(symbol, interval, klines)
                    source = "canlı+cache"
            finally:
                store.close()
            result = run_backtest(klines, symbol, interval, entry_mode=mode,
                                  target_mode=target, include_abcd=include_abcd)
            payload = result.to_payload()
            payload["source"] = source
            payload["bars_used"] = len(klines)
            payload["target_mode"] = target
            payload["abcd"] = abcd
            return json.dumps(payload)

        self._run(
            work,
            on_done=lambda js: self.bridge.resultReady.emit(js),
            on_fail=lambda m: (log.warning("Backtest hatası: %s", m),
                               self.bridge.failed.emit(m)),
        )

    # main_window entegrasyonu
    def refresh(self) -> None:
        """Periyodik yenileme yok — manuel çalıştırılır."""

    def set_store(self, store) -> None:
        pass
