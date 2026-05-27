"""MEXC Futures (contract) public REST istemcisi.

Spot ile farklılıklar:
  - Base URL: https://contract.mexc.com
  - Sembol formatı: BTC_USDT (underscore), spot'ta BTCUSDT
  - Endpoint: /api/v1/contract/kline/<symbol>
  - Interval: Min1/Min5/Min15/Min30/Min60/Hour4/Hour8/Day1/Week1/Month1
  - Response: kolon-bazlı (data.time[], data.open[], ...) — spot satır-bazlı

Bu istemci spot MexcClient ile aynı interface'i sunar:
  klines(symbol, interval, limit)
  klines_paginated(symbol, interval, total_bars, ...)
  ping()
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from terminal.config import HTTP_TIMEOUT

log = logging.getLogger(__name__)

MEXC_FUTURES_BASE = "https://contract.mexc.com"

# Futures'ta tek istek başına max bar (deneyimle ayarlandı, MEXC docs net belirtmez)
MAX_KLINE_LIMIT = 2000


# Spot interval → Futures interval mapping
_INTERVAL_MAP = {
    "1m": "Min1", "5m": "Min5", "15m": "Min15", "30m": "Min30",
    "60m": "Min60", "1h": "Min60", "4h": "Hour4", "8h": "Hour8",
    "1d": "Day1", "1W": "Week1", "1M": "Month1",
}

# Saniye cinsinden mapping (pagination için)
_INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "60m": 3600, "4h": 14400, "1d": 86400, "1W": 604800,
}


def _spot_to_futures_symbol(symbol: str) -> str:
    """BTCUSDT → BTC_USDT. Sembol zaten _ içeriyorsa olduğu gibi dön."""
    if "_" in symbol:
        return symbol
    # USDT, USDC, USD ile bitenleri ayır
    for quote in ("USDT", "USDC", "BUSD", "USD"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[:-len(quote)]}_{quote}"
    return symbol  # match yok → olduğu gibi


class MexcFuturesError(Exception):
    """MEXC futures API çağrısı başarısız."""


class MexcFuturesClient:
    """Sync futures REST istemcisi. MexcClient (spot) ile aynı interface."""

    def __init__(self, base_url: str = MEXC_FUTURES_BASE,
                 timeout: float = HTTP_TIMEOUT) -> None:
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout,
            headers={"User-Agent": "harmonik/1.0 (paper-trade)"},
        )

    def klines(self, symbol: str, interval: str,
               limit: int = 200) -> list[dict[str, Any]]:
        """Son `limit` mumu getirir. Spot ile aynı dönüş yapısı.

        Returns: list[dict] — open_time, close_time, open, high, low, close,
        volume, quote_volume keys. Spot ile uyumlu.
        """
        fut_symbol = _spot_to_futures_symbol(symbol)
        fut_interval = _INTERVAL_MAP.get(interval)
        if fut_interval is None:
            raise MexcFuturesError(f"Bilinmeyen aralık: {interval}")
        # MEXC futures klines son N mum çekmek için end=now, start hesaplama
        sec_per_bar = _INTERVAL_SECONDS.get(interval, 3600)
        end_s = int(time.time())
        start_s = end_s - limit * sec_per_bar
        try:
            r = self._client.get(
                f"/api/v1/contract/kline/{fut_symbol}",
                params={"interval": fut_interval, "start": start_s, "end": end_s},
            )
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            raise MexcFuturesError(f"futures klines({symbol}, {interval}): {e}") from e
        if not payload.get("success"):
            raise MexcFuturesError(f"futures API: {payload}")
        return self._parse_klines(payload["data"], sec_per_bar)

    @staticmethod
    def _parse_klines(data: dict, sec_per_bar: int) -> list[dict[str, Any]]:
        """Futures kolon-bazlı response'u satır-bazlı dict listeye çevir."""
        times = data.get("time", [])
        opens = data.get("open", [])
        highs = data.get("high", [])
        lows = data.get("low", [])
        closes = data.get("close", [])
        vols = data.get("vol", [])
        amounts = data.get("amount", [None] * len(times))
        out: list[dict[str, Any]] = []
        for i, t in enumerate(times):
            ot_ms = int(t) * 1000
            out.append({
                "open_time": ot_ms,
                "close_time": ot_ms + sec_per_bar * 1000 - 1,
                "open": float(opens[i]),
                "high": float(highs[i]),
                "low": float(lows[i]),
                "close": float(closes[i]),
                "volume": float(vols[i]) if vols and i < len(vols) else 0.0,
                "quote_volume": (float(amounts[i])
                                 if amounts and i < len(amounts) and amounts[i] is not None
                                 else None),
            })
        return out

    def klines_paginated(self, symbol: str, interval: str, total_bars: int,
                         end_time_ms: int | None = None,
                         throttle: float = 0.10,
                         max_empty_pages: int = 2) -> list[dict[str, Any]]:
        """`total_bars` kadar mumu sayfa sayfa çek (geriye doğru).

        Spot client ile aynı interface — drop-in replacement.
        """
        fut_symbol = _spot_to_futures_symbol(symbol)
        fut_interval = _INTERVAL_MAP.get(interval)
        if fut_interval is None:
            raise MexcFuturesError(f"Bilinmeyen aralık: {interval}")
        sec_per_bar = _INTERVAL_SECONDS.get(interval, 3600)

        collected: list[dict[str, Any]] = []
        end_s = (end_time_ms // 1000) if end_time_ms else int(time.time())
        empty_streak = 0

        while len(collected) < total_bars:
            remaining = total_bars - len(collected)
            limit = min(MAX_KLINE_LIMIT, remaining)
            start_s = end_s - limit * sec_per_bar
            try:
                r = self._client.get(
                    f"/api/v1/contract/kline/{fut_symbol}",
                    params={"interval": fut_interval, "start": start_s, "end": end_s},
                )
                r.raise_for_status()
                payload = r.json()
            except httpx.HTTPError as e:
                raise MexcFuturesError(
                    f"futures klines_paginated({symbol}, {interval}): {e}"
                ) from e
            if not payload.get("success"):
                raise MexcFuturesError(f"futures API: {payload}")
            page = self._parse_klines(payload["data"], sec_per_bar)
            if not page:
                empty_streak += 1
                if empty_streak >= max_empty_pages:
                    break
                end_s = start_s - 1
                continue
            empty_streak = 0
            collected = page + collected
            end_s = page[0]["open_time"] // 1000 - 1
            if throttle > 0:
                time.sleep(throttle)

        return collected[-total_bars:]

    def ping(self) -> bool:
        try:
            r = self._client.get("/api/v1/contract/ping")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MexcFuturesClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
