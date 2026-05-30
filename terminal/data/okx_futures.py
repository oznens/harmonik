"""OKX V5 futures (SWAP) veri istemcisi — MEXC client ile AYNI arayüz.

Drop-in replacement: klines / klines_paginated / ping / close + aynı dönüş dict
formatı (open_time/close_time/open/high/low/close/volume/quote_volume).
Böylece poller/scanner hiç değişmeden OKX verisiyle çalışır.

Bu modül yalnız PUBLIC market verisi çeker (kimlik gerektirmez). Emir/hesap
(authenticated) ayrı modülde (okx_trade.py). Demo/canlı veri aynıdır; emir tarafı
x-simulated-trading başlığıyla demo'ya gider.

OKX SWAP sembol: BTCUSDT → BTC-USDT-SWAP. Bar: 15m/30m/1H/2H/4H/1D...
OKX candles confirm=0 → oluşmakta olan (kapanmamış) mum; confirm=1 → kapanmış.
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

OKX_BASE = "https://www.okx.com"

# OKX kline endpoint limiti: 20 istek / 2 saniye (public). Global throttle.
_MIN_REQUEST_INTERVAL = float(os.environ.get("OKX_MIN_INTERVAL", "0.12"))
MAX_KLINE_LIMIT = 300   # OKX /market/candles tek istek max 300 bar

# Spot biçimi (60m vb.) → OKX bar kodu
_BAR_MAP = {
    "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m",
    "60m": "1H", "1h": "1H", "2h": "2H", "4h": "4H", "8h": "8H",
    "1d": "1D", "1W": "1W", "1M": "1M",
}
_INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600,
    "2h": 7200, "4h": 14400, "8h": 28800, "1d": 86400, "1W": 604800,
}


def _to_inst(symbol: str) -> str:
    """BTCUSDT → BTC-USDT-SWAP. Zaten OKX biçimindeyse dokunma."""
    if "-" in symbol:
        return symbol
    for quote in ("USDT", "USDC", "USD"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[:-len(quote)]}-{quote}-SWAP"
    return symbol


class OkxError(Exception):
    """OKX API çağrısı başarısız."""


class OkxFuturesClient:
    """OKX SWAP public veri istemcisi (MexcFuturesClient arayüzüyle uyumlu)."""

    _rate_lock = threading.Lock()
    _last_request_ts = 0.0

    def __init__(self, base_url: str = OKX_BASE, timeout: float = HTTP_TIMEOUT) -> None:
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout,
            headers={"User-Agent": "harmonik/1.0 (okx-data)"},
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
        """OKX candle satırlarını (yeni→eski gelir) MEXC formatına çevir, eski→yeni sırala.

        OKX kolon: [ts, o, h, l, c, vol(kontrat), volCcy(coin), volCcyQuote(USDT), confirm]
        """
        out: list[dict[str, Any]] = []
        for r in rows:
            ot = int(r[0])
            out.append({
                "open_time": ot,
                "close_time": ot + sec_per_bar * 1000 - 1,
                "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
                "volume": float(r[6]) if len(r) > 6 else float(r[5]),  # coin cinsi
                "quote_volume": float(r[7]) if len(r) > 7 else None,    # USDT cirosu
                "_confirm": (r[8] if len(r) > 8 else "1"),              # 1=kapanmış
            })
        out.sort(key=lambda k: k["open_time"])
        return out

    def klines(self, symbol: str, interval: str, limit: int = 200) -> list[dict[str, Any]]:
        """Son `limit` mumu getirir (eski→yeni). MEXC ile aynı dönüş."""
        inst = _to_inst(symbol)
        bar = _BAR_MAP.get(interval)
        if bar is None:
            raise OkxError(f"Bilinmeyen aralık: {interval}")
        sec = _INTERVAL_SECONDS.get(interval, 3600)
        self._throttle()
        try:
            r = self._client.get("/api/v5/market/candles",
                                 params={"instId": inst, "bar": bar,
                                         "limit": str(min(limit, MAX_KLINE_LIMIT))})
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            raise OkxError(f"okx klines({symbol}, {interval}): {e}") from e
        if payload.get("code") != "0":
            raise OkxError(f"okx API: {payload.get('code')} {payload.get('msg')}")
        return self._parse(payload.get("data", []), sec)

    def klines_paginated(self, symbol: str, interval: str, total_bars: int,
                         end_time_ms: int | None = None, throttle: float = 0.12,
                         max_empty_pages: int = 2) -> list[dict[str, Any]]:
        """`total_bars` mumu sayfa sayfa çek (geriye doğru). MEXC arayüzüyle aynı.

        OKX: `after`=ts (bu zamandan ÖNCEKİ mumlar). Sayfa max 300.
        """
        inst = _to_inst(symbol)
        bar = _BAR_MAP.get(interval)
        if bar is None:
            raise OkxError(f"Bilinmeyen aralık: {interval}")
        sec = _INTERVAL_SECONDS.get(interval, 3600)
        collected: list[dict[str, Any]] = []
        after = end_time_ms  # None = en yeniden başla
        empty = 0
        while len(collected) < total_bars:
            params = {"instId": inst, "bar": bar, "limit": str(MAX_KLINE_LIMIT)}
            if after is not None:
                params["after"] = str(after)
            self._throttle()
            try:
                r = self._client.get("/api/v5/market/history-candles", params=params)
                r.raise_for_status()
                payload = r.json()
            except httpx.HTTPError as e:
                raise OkxError(f"okx history({symbol}, {interval}): {e}") from e
            if payload.get("code") != "0":
                raise OkxError(f"okx API: {payload.get('code')} {payload.get('msg')}")
            page = self._parse(payload.get("data", []), sec)
            if not page:
                empty += 1
                if empty >= max_empty_pages:
                    break
                continue
            empty = 0
            collected = page + collected
            after = page[0]["open_time"]   # en eski mumdan öncesine devam
            if throttle > 0:
                time.sleep(throttle)
        return collected[-total_bars:]

    def ping(self) -> bool:
        """Bağlantı/erişim kontrolü — sistem zamanı endpoint'i."""
        try:
            self._throttle()
            r = self._client.get("/api/v5/public/time")
            return r.status_code == 200 and r.json().get("code") == "0"
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        self._client.close()
