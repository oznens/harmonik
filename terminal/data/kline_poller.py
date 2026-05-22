"""REST polling tabanlı kline akışı.

Her POLL_INTERVAL_SECONDS saniyede bir son birkaç mumu çeker; yeni KAPANMIŞ
mumlar varsa bunları sırayla:
  - RAM tamponuna ekler,
  - SQLite'a yazar,
  - opsiyonel `on_closed` callback'ine iletir.

Sonraki fazlarda WebSocket eklenebilir; arayüz değişmez.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from terminal.config import BUFFER_SIZE, POLL_INTERVAL_SECONDS
from terminal.data.buffer import KlineBuffer
from terminal.data.mexc_client import MexcClient, MexcError
from terminal.db.store import Store

log = logging.getLogger(__name__)

OnClosed = Callable[[dict[str, Any]], None]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _fmt_ts(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class KlinePoller:
    """Tek bir (parite, aralık) için kline polling döngüsü."""

    def __init__(
        self,
        symbol: str,
        interval: str,
        client: MexcClient,
        store: Store,
        on_closed: OnClosed | None = None,
        buffer_size: int = BUFFER_SIZE,
        poll_seconds: int = POLL_INTERVAL_SECONDS,
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.client = client
        self.store = store
        self.on_closed = on_closed
        self.buffer = KlineBuffer(maxlen=buffer_size)
        self._buffer_size = buffer_size
        self._poll_seconds = poll_seconds
        self._last_closed_open: int | None = None
        self._running = False
        self._tag = f"[{symbol} {interval}]"

    def bootstrap(self) -> None:
        """Son N kapanmış mumu çek, tampona ve DB'ye yaz."""
        log.info("%s bootstrap: son %d mum alınıyor", self._tag, self._buffer_size)
        # Sona düşen, oluşmakta olan mumu kaçırmamak için bir fazla iste
        klines = self.client.klines(self.symbol, self.interval, limit=self._buffer_size + 1)
        closed = [k for k in klines if self._is_closed(k)]
        if not closed:
            log.warning("%s bootstrap'ta kapanmış mum yok", self._tag)
            return
        closed = closed[-self._buffer_size:]
        self.buffer.bulk_load(closed)
        self.store.upsert_klines(self.symbol, self.interval, closed)
        self._last_closed_open = closed[-1]["open_time"]
        log.info(
            "%s bootstrap tamam: %d mum, son kapanış %s, kapanış fiyatı %s",
            self._tag, len(closed),
            _fmt_ts(closed[-1]["close_time"]),
            closed[-1]["close"],
        )

    def poll_once(self) -> int:
        """Tek bir polling adımı. İşlenen yeni kapanmış mum sayısını döner."""
        try:
            klines = self.client.klines(self.symbol, self.interval, limit=5)
        except MexcError as e:
            log.warning("%s polling hatası: %s", self._tag, e)
            return 0

        new_closed = [
            k for k in klines
            if self._is_closed(k)
            and (self._last_closed_open is None or k["open_time"] > self._last_closed_open)
        ]
        for k in new_closed:
            self._emit(k)
            self._last_closed_open = k["open_time"]
        return len(new_closed)

    def _emit(self, kline: dict[str, Any]) -> None:
        self.buffer.add(kline)
        self.store.upsert_kline(self.symbol, self.interval, kline)
        log.info(
            "%s KAPANDI %s  O=%s H=%s L=%s C=%s V=%.2f",
            self._tag,
            _fmt_ts(kline["close_time"]),
            kline["open"], kline["high"], kline["low"], kline["close"],
            kline["volume"],
        )
        if self.on_closed:
            try:
                self.on_closed(kline)
            except Exception:
                log.exception("%s on_closed callback hatası", self._tag)

    @staticmethod
    def _is_closed(kline: dict[str, Any]) -> bool:
        return kline["close_time"] < _now_ms()

    def run(self) -> None:
        """Sonsuz polling döngüsü. stop() çağrılana kadar çalışır."""
        self._running = True
        self.bootstrap()
        log.info("%s polling döngüsü başladı (her %ds)", self._tag, self._poll_seconds)
        while self._running:
            self.poll_once()
            # Sleep'i küçük adımlara böl ki Ctrl+C hızlı yakalansın
            slept = 0.0
            while self._running and slept < self._poll_seconds:
                time.sleep(0.5)
                slept += 0.5

    def stop(self) -> None:
        self._running = False
