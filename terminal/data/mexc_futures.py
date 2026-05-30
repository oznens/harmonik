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
import os
import threading
import time
from typing import Any

import httpx

from terminal.config import HTTP_TIMEOUT

log = logging.getLogger(__name__)

MEXC_FUTURES_BASE = "https://contract.mexc.com"

# GLOBAL hız sınırı: tüm MexcFuturesClient örnekleri (250 worker thread) tek bir
# sayaçtan geçer → toplam istek hızı sınırlanır, MEXC 510 (too frequent) önlenir.
# İstekler arası min boşluk (sn). .env'de MEXC_FUTURES_MIN_INTERVAL ile ayarlanır.
# 0.10 ≈ 10 istek/sn. 510 hâlâ gelirse bu değeri artır (0.15, 0.2 ...).
_MIN_REQUEST_INTERVAL = float(os.environ.get("MEXC_FUTURES_MIN_INTERVAL", "0.10"))

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
    "60m": 3600, "2h": 7200, "4h": 14400, "8h": 28800,
    "1d": 86400, "1W": 604800,
}

# MEXC native DESTEKLEMEYEN aralıklar → (alt_aralık, kaç_tanesi) ile resample.
# 2h native yok (Min60'tan sonra Hour4 geliyor) → 60m mumları 2'şerli birleştir.
_RESAMPLE_FROM: dict[str, tuple[str, int]] = {
    "2h": ("60m", 2),
}


def _resample(base: list[dict[str, Any]], factor: int, out_sec: int) -> list[dict[str, Any]]:
    """`factor` adet alt-mumu tek üst-muma birleştir (OHLCV).

    Üst mumlar zaman sınırına HİZALANIR (örn. 2h → 00:00, 02:00 ...): grup,
    open_time'ın out_sec'e bölümünün tabanına göre yapılır. Eksik (yarım) son
    grup da döner — close_time gelecekte kaldığından poller onu 'kapanmamış'
    sayar (forming bar), tam dolunca kapanmış olur.
    """
    if factor <= 1 or not base:
        return base
    out_ms = out_sec * 1000
    buckets: dict[int, list[dict[str, Any]]] = {}
    for k in base:
        key = (k["open_time"] // out_ms) * out_ms   # hizalanmış üst-mum başlangıcı
        buckets.setdefault(key, []).append(k)
    merged: list[dict[str, Any]] = []
    for start in sorted(buckets):
        grp = sorted(buckets[start], key=lambda x: x["open_time"])
        qv = [g.get("quote_volume") for g in grp]
        merged.append({
            "open_time": start,
            "close_time": start + out_ms - 1,
            "open": grp[0]["open"],
            "high": max(g["high"] for g in grp),
            "low": min(g["low"] for g in grp),
            "close": grp[-1]["close"],
            "volume": sum(g.get("volume", 0.0) for g in grp),
            "quote_volume": (sum(v for v in qv if v is not None)
                             if any(v is not None for v in qv) else None),
        })
    return merged


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

    # Tüm örnekler arası paylaşılan global hız sınırı (sınıf seviyesi).
    _rate_lock = threading.Lock()
    _last_request_ts = 0.0

    def __init__(self, base_url: str = MEXC_FUTURES_BASE,
                 timeout: float = HTTP_TIMEOUT) -> None:
        self._client = httpx.Client(
            base_url=base_url, timeout=timeout,
            headers={"User-Agent": "harmonik/1.0 (paper-trade)"},
        )

    @classmethod
    def _throttle(cls) -> None:
        """Global istek aralığını uygula — tüm worker'lar burada serileşir."""
        with cls._rate_lock:
            now = time.monotonic()
            wait = _MIN_REQUEST_INTERVAL - (now - cls._last_request_ts)
            if wait > 0:
                time.sleep(wait)
            cls._last_request_ts = time.monotonic()

    def klines(self, symbol: str, interval: str,
               limit: int = 200) -> list[dict[str, Any]]:
        """Son `limit` mumu getirir. Spot ile aynı dönüş yapısı.

        Returns: list[dict] — open_time, close_time, open, high, low, close,
        volume, quote_volume keys. Spot ile uyumlu.
        """
        # Native desteklenmeyen aralık (örn. 2h) → alt aralığı çekip resample et.
        if interval in _RESAMPLE_FROM:
            base_iv, factor = _RESAMPLE_FROM[interval]
            base = self.klines(symbol, base_iv, limit=limit * factor + factor)
            out = _resample(base, factor, _INTERVAL_SECONDS[interval])
            return out[-limit:]

        fut_symbol = _spot_to_futures_symbol(symbol)
        fut_interval = _INTERVAL_MAP.get(interval)
        if fut_interval is None:
            raise MexcFuturesError(f"Bilinmeyen aralık: {interval}")
        # MEXC futures klines son N mum çekmek için end=now, start hesaplama
        sec_per_bar = _INTERVAL_SECONDS.get(interval, 3600)
        end_s = int(time.time())
        start_s = end_s - limit * sec_per_bar
        self._throttle()
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
        # Native desteklenmeyen aralık (örn. 2h) → alt aralığı sayfalı çek + resample.
        if interval in _RESAMPLE_FROM:
            base_iv, factor = _RESAMPLE_FROM[interval]
            base = self.klines_paginated(symbol, base_iv, total_bars * factor + factor,
                                         end_time_ms=end_time_ms, throttle=throttle,
                                         max_empty_pages=max_empty_pages)
            out = _resample(base, factor, _INTERVAL_SECONDS[interval])
            return out[-total_bars:]

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
            self._throttle()
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

    def all_tickers(self) -> list[dict[str, Any]]:
        """Tüm futures kontratları için 24s ticker verisi.

        Her öğe en azından `symbol` (örn. 'BTC_USDT') ve hacim alanları içerir
        (`amount24` = 24s USDT cirosu, `volume24` = kontrat adedi). Hacme göre
        parite sıralamak için kullanılır.
        """
        self._throttle()
        r = self._client.get("/api/v1/contract/ticker")
        r.raise_for_status()
        data = r.json()
        items = data.get("data", data) if isinstance(data, dict) else data
        return items if isinstance(items, list) else []

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
