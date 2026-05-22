"""MEXC public REST istemcisi (sadece market data, API key gerekmez)."""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from terminal.config import HTTP_TIMEOUT, MEXC_REST_BASE
from terminal.config import INTERVAL_SECONDS

log = logging.getLogger(__name__)


# MEXC docs "max 1000" der ama gerçekte istek başı en fazla 500 mum döner.
MAX_KLINE_LIMIT = 500


class MexcError(Exception):
    """MEXC API çağrısı başarısız."""


class MexcClient:
    """Sync REST istemcisi. Faz 1 için yeterli; WS gerekirse sonra eklenir."""

    def __init__(self, base_url: str = MEXC_REST_BASE, timeout: float = HTTP_TIMEOUT) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def klines(self, symbol: str, interval: str, limit: int = 200) -> list[dict[str, Any]]:
        """Verilen parite + aralık için son `limit` mumu döner (eski → yeni sıralı).

        Dönen mumların sonuncusu **şu anda oluşmakta olan** mum olabilir;
        `close_time` ile filtreleyerek kapanmış olanları ayırt et.
        """
        try:
            r = self._client.get(
                "/api/v3/klines",
                params={"symbol": symbol, "interval": interval, "limit": limit},
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise MexcError(f"klines({symbol}, {interval}) başarısız: {e}") from e

        rows = r.json()
        return [self._parse_kline(row) for row in rows]

    @staticmethod
    def _parse_kline(row: list) -> dict[str, Any]:
        # MEXC formatı: [openTime, open, high, low, close, volume, closeTime, quoteVolume]
        return {
            "open_time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": int(row[6]),
            "quote_volume": float(row[7]) if len(row) > 7 and row[7] is not None else None,
        }

    def klines_paginated(
        self,
        symbol: str,
        interval: str,
        total_bars: int,
        end_time_ms: int | None = None,
        throttle: float = 0.10,
        max_empty_pages: int = 2,
    ) -> list[dict[str, Any]]:
        """`total_bars` kadar mumu sayfa sayfa çeker (geriye doğru).

        MEXC `endTime` tek başına işe yaramıyor — her sayfa için `startTime`
        + `endTime` birlikte verilmeli. Bu metod gerekli pencereleri otomatik
        hesaplar.

        Args:
            symbol: parite kodu.
            interval: aralık ("60m", "1d", vs).
            total_bars: istenen toplam mum sayısı.
            end_time_ms: en yeni mumun close_time üst sınırı (None = şimdi).
            throttle: ardışık istekler arası bekleme (saniye).
            max_empty_pages: art arda bu kadar boş sayfa gelirse durdurur.

        Returns:
            Kronolojik sıralı mum listesi (eski → yeni).
        """
        if interval not in INTERVAL_SECONDS:
            raise MexcError(f"klines_paginated: bilinmeyen aralık {interval!r}")
        interval_ms = INTERVAL_SECONDS[interval] * 1000

        collected: list[dict[str, Any]] = []
        cursor: int | None = end_time_ms  # None ise ilk sayfa "en güncel"
        empty_streak = 0

        while len(collected) < total_bars:
            remaining = total_bars - len(collected)
            limit = min(MAX_KLINE_LIMIT, remaining)
            params: dict[str, Any] = {
                "symbol": symbol, "interval": interval, "limit": limit,
            }
            if cursor is not None and len(collected) > 0:
                # Sonraki sayfalar: startTime + endTime ikisi de verilmeli
                # (MEXC `endTime` tek başına işe yaramıyor).
                start_t = max(0, cursor - limit * interval_ms)
                params["startTime"] = start_t
                params["endTime"] = cursor
            elif cursor is not None:
                # İlk sayfa, fakat kullanıcı end_time_ms verdi: o noktadan
                # geriye doğru pencere
                start_t = max(0, cursor - limit * interval_ms)
                params["startTime"] = start_t
                params["endTime"] = cursor
            # else: ilk sayfa, cursor=None → MEXC default (en güncel mumlar)

            try:
                r = self._client.get("/api/v3/klines", params=params)
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise MexcError(f"klines_paginated({symbol}, {interval}) başarısız: {e}") from e
            rows = r.json()
            if not rows:
                empty_streak += 1
                if empty_streak >= max_empty_pages:
                    break
                if cursor is not None:
                    cursor = max(0, cursor - limit * interval_ms) - 1
                continue
            empty_streak = 0
            page = [self._parse_kline(row) for row in rows]
            collected = page + collected
            cursor = page[0]["open_time"] - 1
            if throttle > 0:
                time.sleep(throttle)

        return collected[-total_bars:]

    def ping(self) -> bool:
        try:
            r = self._client.get("/api/v3/ping")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MexcClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
