"""Canlı katmanlı mum grafiği sekmesi.

TradingView lightweight-charts'ı QWebEngineView içinde gömer. Mum verisi ve
katmanlar (Pivot / Vector / Harmonic / HTF) chart_data üzerinden üretilir.

Thread modeli: SQLite bağlantısı thread'e bağlı olduğundan tüm DB erişimi ve
yük (payload) üretimi ANA thread'de yapılır (hızlı, lokal). Sadece MEXC ağ
çağrıları (canlı mum çekimi / DB boşsa ilk fetch) worker thread'e taşınır.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from terminal.config import BUFFER_SIZE
from terminal.data.mexc_client import MexcClient
from terminal.db.store import Store
from terminal.ui import chart_data

log = logging.getLogger(__name__)

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
_HTML = _ASSETS / "chart.html"

LIVE_INTERVAL_MS = 5000      # canlı mum yoklama sıklığı
FULL_REBUILD_EVERY = 6       # her N canlı tikte bir overlay'leri tam yenile


class ChartBridge(QObject):
    """JS <-> Python köprüsü (QWebChannel ile sayfaya enjekte edilir)."""

    dataReady = Signal(str)        # tam payload (JSON)
    liveUpdate = Signal(str)       # canlı mum güncellemesi (JSON)
    liveState = Signal(bool, str)  # canlı bağlantı durumu (açık?, etiket)
    pageReady = Signal()
    dataRequested = Signal(str, str, str)  # symbol, interval, setup ("auto"|id)

    @Slot()
    def ready(self) -> None:
        self.pageReady.emit()

    @Slot(str, str, str)
    def requestData(self, symbol: str, interval: str, setup: str) -> None:
        self.dataRequested.emit(symbol, interval, setup)


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Task(QRunnable):
    """Tek seferlik fonksiyonu thread havuzunda çalıştırır."""

    def __init__(self, fn) -> None:
        super().__init__()
        self._fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:  # noqa: D401
        try:
            result = self._fn()
        except Exception as e:  # ağ hatası vb.
            try:
                self.signals.failed.emit(str(e))
            except RuntimeError:
                pass  # widget kapanış sırasında silinmiş olabilir
            return
        try:
            self.signals.done.emit(result)
        except RuntimeError:
            pass


class LiveChartTab(QWidget):
    """Canlı grafik sekmesi."""

    def __init__(self, store: Store, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._pool = QThreadPool.globalInstance()
        self._tasks: set[_Task] = set()
        self._client: MexcClient | None = None
        self._fetching_live = False
        self._loading_full = False
        self._tick = 0
        self._ready = False
        self._setup_id: int | None = None  # None = otomatik seçim

        pairs = chart_data.available_pairs(store)
        self._symbol = pairs["symbols"][0] if pairs["symbols"] else "BTCUSDT"
        ivls = pairs["intervals"]
        self._interval = "60m" if "60m" in ivls else (ivls[0] if ivls else "60m")

        # WebEngine + köprü
        self.view = QWebEngineView(self)
        self.bridge = ChartBridge()
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.bridge.pageReady.connect(self._on_page_ready)
        self.bridge.dataRequested.connect(self._on_request)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.view.setUrl(QUrl.fromLocalFile(str(_HTML)))

        self._timer = QTimer(self)
        self._timer.setInterval(LIVE_INTERVAL_MS)
        self._timer.timeout.connect(self._live_tick)

    # ---- altyapı ----

    def _get_client(self) -> MexcClient:
        if self._client is None:
            self._client = MexcClient()
        return self._client

    def _run(self, fn, on_done, on_fail=None) -> None:
        task = _Task(fn)
        task.signals.done.connect(on_done)
        task.signals.done.connect(lambda _=None, t=task: self._tasks.discard(t))
        if on_fail is not None:
            task.signals.failed.connect(on_fail)
        task.signals.failed.connect(lambda _=None, t=task: self._tasks.discard(t))
        self._tasks.add(task)
        self._pool.start(task)

    # ---- köprü olayları ----

    @Slot()
    def _on_page_ready(self) -> None:
        self._ready = True
        self._request_full(include_pairs=True)
        self._timer.start()

    @Slot(str, str, str)
    def _on_request(self, symbol: str, interval: str, setup: str) -> None:
        self._symbol, self._interval = symbol, interval
        self._setup_id = int(setup) if setup.isdigit() else None
        self._request_full(include_pairs=False)

    # ---- tam yük (overlay'ler dahil) ----

    def _request_full(self, include_pairs: bool = False) -> None:
        if not self._ready or self._loading_full:
            return
        sym, ivl = self._symbol, self._interval
        klines = chart_data._load_klines(self.store, sym, ivl, BUFFER_SIZE, client=None)
        if len(klines) >= 20:
            payload = chart_data.build_payload(
                self.store, sym, ivl, klines=klines, include_pairs=include_pairs)
            self.bridge.dataReady.emit(json.dumps(payload))
            return
        # DB yetersiz → MEXC'den ilk yükleme (ağ worker'da)
        self._loading_full = True

        def work():
            return self._get_client().klines(sym, ivl, limit=BUFFER_SIZE)

        def done(fetched):
            self._loading_full = False
            payload = chart_data.build_payload(
                self.store, sym, ivl, klines=fetched, include_pairs=include_pairs)
            self.bridge.dataReady.emit(json.dumps(payload))
            self.bridge.liveState.emit(True, "canlı")

        def fail(msg):
            self._loading_full = False
            payload = chart_data.build_payload(
                self.store, sym, ivl, klines=[], include_pairs=include_pairs)
            self.bridge.dataReady.emit(json.dumps(payload))
            self.bridge.liveState.emit(False, "MEXC erişilemedi")
            log.warning("Canlı grafik ilk fetch hatası: %s", msg)

        self._run(work, done, fail)

    # ---- canlı tik ----

    @Slot()
    def _live_tick(self) -> None:
        if not self._ready:
            return
        self._tick += 1
        if self._tick % FULL_REBUILD_EVERY == 0:
            self._request_full(include_pairs=False)
            return
        if self._fetching_live or self._loading_full:
            return
        self._fetching_live = True
        sym, ivl = self._symbol, self._interval

        def work():
            return chart_data.fetch_live(sym, ivl, self._get_client())

        def done(payload):
            self._fetching_live = False
            self.bridge.liveUpdate.emit(json.dumps(payload))
            self.bridge.liveState.emit(True, "canlı")

        def fail(msg):
            self._fetching_live = False
            self.bridge.liveState.emit(False, "çevrimdışı")
            log.debug("Canlı tik hatası: %s", msg)

        self._run(work, done, fail)

    # ---- main_window entegrasyonu ----

    def refresh(self) -> None:
        """main_window 5sn döngüsü çağırır — kendi timer'ımız işi yapıyor, no-op."""

    def set_store(self, store: Store) -> None:
        self.store = store

    def shutdown(self) -> None:
        self._timer.stop()
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None
