"""MEXC public REST istemcisi (sadece market data, API key gerekmez)."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from terminal.config import HTTP_TIMEOUT, MEXC_REST_BASE

log = logging.getLogger(__name__)


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
