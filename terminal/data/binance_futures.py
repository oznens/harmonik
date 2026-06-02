"""Binance USDT-M Futures veri istemcisi — OkxFuturesClient ile AYNI arayüz.

Drop-in: klines / klines_paginated / ping / close + aynı dönüş dict formatı
(open_time/close_time/open/high/low/close/volume/quote_volume). Poller/scanner
hiç değişmeden Binance verisiyle çalışır.

Yalnız PUBLIC market verisi (kimlik gerektirmez). Emir/hesap → binance_trade.py.

VERİ KAYNAĞI: varsayılan mainnet fapi (fapi.binance.com) — temiz/derin piyasa
yapısı. Bazı bölgelerden 451 (coğrafi engel) gelebilir; o durumda testnet kendi
verisine düş: BINANCE_DATA_BASE=https://testnet.binancefuture.com
(testnet fiyatları mainnet'i yakından takip eder, fill ile tutarlı olur).

Binance sembol: BTCUSDT (dönüşüm yok). Bar: 15m/30m/1h/4h/1d...
Binance klines confirm: son bar henüz kapanmamış olabilir (canlı); biz olduğu
gibi kullanıyoruz (scanner kapanmış barlara göre çalışır).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

import httpx

from terminal.config import HTTP_TIMEOUT

log = logging.getLogger(__name__)

# Canlı tarama verisi (default mainnet). VPS coğrafi engelliyse env ile testnet'e al.
BINANCE_DATA_BASE = os.environ.get("BINANCE_DATA_BASE", "https://fapi.binance.com")

_MIN_REQUEST_INTERVAL = float(os.environ.get("BINANCE_MIN_INTERVAL", "0.06"))
MAX_KLINE_LIMIT = 1500   # Binance /fapi/v1/klines tek istek max 1500 bar

# Bizim aralık biçimi → Binance bar kodu (Binance "60m" yerine "1h" kullanır)
_BAR_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "1h", "1h": "1h", "2h": "2h", "4h": "4h", "8h": "8h",
    "1d": "1d", "1W": "1w", "1M": "1M",
}
_INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600,
    "2h": 7200, "4h": 14400, "8h": 28800, "1d": 86400, "1W": 604800,
}


class BinanceError(Exception):
    """Binance API çağrısı başarısız."""


class BinanceFuturesClient:
    """Binance USDT-M futures public veri istemcisi (OKX/MEXC arayüzüyle uyumlu)."""

    _rate_lock = threading.Lock()
    _last_request_ts = 0.0

    def __init__(self, base_url: str = BINANCE_DATA_BASE,
                 timeout: float = HTTP_TIMEOUT) -> None:
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout,
            headers={"User-Agent": "harmonik/1.0 (binance-data)"},
        )

    @classmethod
    def _throttle(cls) -> None:
        with cls._rate_lock:
            now = time.monotonic()
            wait = _MIN_REQUEST_INTERVAL - (now - cls._last_request_ts)
            if wait > 0:
                time.sleep(wait)
            cls._last_request_ts = time.monotonic()

    def _parse(self, rows: list[list], sec_per_bar: int) -> list[dict[str, Any]]:
        """Binance kline satırlarını (eski→yeni gelir) ortak formata çevir.

        Binance kolon: [openTime, o, h, l, c, volume, closeTime, quoteAssetVolume,
                        trades, takerBuyBase, takerBuyQuote, ignore]
        """
        out: list[dict[str, Any]] = []
        for r in rows:
            ot = int(r[0])
            out.append({
                "open_time": ot,
                "close_time": int(r[6]) if len(r) > 6 else ot + sec_per_bar * 1000 - 1,
                "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
                "volume": float(r[5]),                                  # base (coin)
                "quote_volume": float(r[7]) if len(r) > 7 else None,    # USDT cirosu
                "_confirm": "1",
            })
        out.sort(key=lambda k: k["open_time"])
        return out

    def _bar(self, interval: str) -> str:
        bar = _BAR_MAP.get(interval)
        if bar is None:
            raise BinanceError(f"Bilinmeyen aralık: {interval}")
        return bar

    def klines(self, symbol: str, interval: str, limit: int = 200) -> list[dict[str, Any]]:
        """Son `limit` mumu getirir (eski→yeni). MEXC/OKX ile aynı dönüş."""
        bar = self._bar(interval)
        sec = _INTERVAL_SECONDS.get(interval, 3600)
        self._throttle()
        try:
            r = self._client.get("/fapi/v1/klines",
                                 params={"symbol": symbol, "interval": bar,
                                         "limit": str(min(limit, MAX_KLINE_LIMIT))})
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            raise BinanceError(f"binance klines({symbol}, {interval}): {e}") from e
        if not isinstance(payload, list):
            raise BinanceError(f"binance API: {payload}")
        return self._parse(payload, sec)

    def klines_paginated(self, symbol: str, interval: str, total_bars: int,
                         end_time_ms: int | None = None, throttle: float = 0.0,
                         max_empty_pages: int = 2) -> list[dict[str, Any]]:
        """`total_bars` mumu sayfa sayfa çek (geriye doğru). MEXC/OKX arayüzü.

        Binance: `endTime`=bu zamana kadar (dahil) barlar; sayfa max 1500, eski→yeni
        gelir. En eski openTime - 1'i bir sonraki endTime yaparak geriye sayfala.
        """
        bar = self._bar(interval)
        sec = _INTERVAL_SECONDS.get(interval, 3600)
        collected: list[dict[str, Any]] = []
        end = end_time_ms
        empty = 0
        while len(collected) < total_bars:
            params: dict[str, str] = {"symbol": symbol, "interval": bar,
                                      "limit": str(MAX_KLINE_LIMIT)}
            if end is not None:
                params["endTime"] = str(end)
            self._throttle()
            try:
                r = self._client.get("/fapi/v1/klines", params=params)
                r.raise_for_status()
                payload = r.json()
            except httpx.HTTPError as e:
                raise BinanceError(f"binance history({symbol}, {interval}): {e}") from e
            if not isinstance(payload, list):
                raise BinanceError(f"binance API: {payload}")
            page = self._parse(payload, sec)
            if not page:
                empty += 1
                if empty >= max_empty_pages:
                    break
                # daha geriye git
                if end is not None:
                    end -= MAX_KLINE_LIMIT * sec * 1000
                continue
            empty = 0
            collected = page + collected
            end = page[0]["open_time"] - 1
            if len(page) < MAX_KLINE_LIMIT:
                break   # daha eski veri yok
        return collected[-total_bars:] if len(collected) > total_bars else collected

    def ping(self) -> bool:
        try:
            self._throttle()
            r = self._client.get("/fapi/v1/ping")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()
