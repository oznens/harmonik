"""Binance USDT-M Futures instrument bilgisi + pozisyon boyutlandırma.

OkxInstruments karşılığı. Binance'te miktar BASE coin cinsinden (kontrat yok):
    notional = qty * price ,  qty = notional / price.
Filtreler: PRICE_FILTER(tickSize), LOT_SIZE(stepSize/minQty), MIN_NOTIONAL.

size_for: "$risk + dinamik kaldıraç" niyetini Binance qty'ye çevirir — OKX ile
AYNI kurallar (notional tavanı, hedef-margin/sabit/agresif kaldıraç, min kontrol).

Max kaldıraç: exchangeInfo'da yok (leverageBracket signed). v1'de env default
(BINANCE_MAX_LEVER) kullanılır; set_leverage best-effort uygular, Binance clamp'ler.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

import httpx

from terminal.config import HTTP_TIMEOUT
from terminal.data.binance_futures import BINANCE_DATA_BASE

log = logging.getLogger(__name__)

# exchangeInfo PUBLIC — testnet/mainnet ikisinde de aynı şema. Default mainnet;
# coğrafi engel varsa BINANCE_DATA_BASE=testnet zaten data ile aynı tabanı kullanır.
_DEFAULT_MAX_LEVER = float(os.environ.get("BINANCE_MAX_LEVER", "50"))


@dataclass
class Instrument:
    symbol: str
    tick_sz: float       # fiyat adımı
    step_sz: float       # miktar adımı (qty yuvarlama)
    min_qty: float       # min miktar (coin)
    min_notional: float  # min pozisyon büyüklüğü ($)
    max_lever: float     # izin verilen max kaldıraç
    lev_notional_cap: float = 0.0  # en yüksek kaldıraç kademesinin max notional'ı
                                    # (0=bilinmiyor; aşılırsa -2027). leverageBracket'ten.

    def round_qty(self, qty: float) -> float:
        """Miktarı step adımına yuvarla (aşağı) — Decimal ile temiz kuyruk."""
        if self.step_sz <= 0:
            return qty
        d = Decimal(str(self.step_sz))
        steps = (Decimal(str(qty)) / d).to_integral_value(rounding=ROUND_DOWN)
        return float(steps * d)

    def round_px(self, px: float) -> float:
        if self.tick_sz <= 0:
            return px
        d = Decimal(str(self.tick_sz))
        steps = (Decimal(str(px)) / d).to_integral_value(rounding=ROUND_DOWN)
        return float(steps * d)


@dataclass
class Sizing:
    """Bir setup için hesaplanan Binance emir boyutu."""
    sz: float            # miktar (coin, step'e yuvarlı)
    leverage: int
    notional_usd: float
    margin_usd: float
    ok: bool
    reason: str = ""


class BinanceInstruments:
    """Futures instrument cache + pozisyon boyutlandırma."""

    def __init__(self, base_url: str = BINANCE_DATA_BASE, timeout: float = HTTP_TIMEOUT,
                 ttl: float = 3600.0, max_lever: float = _DEFAULT_MAX_LEVER) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout,
                                    headers={"User-Agent": "harmonik/1.0 (binance-inst)"})
        self._cache: dict[str, Instrument] = {}
        self._loaded_at = 0.0
        self._ttl = ttl
        self._default_max_lever = max_lever
        self._lock = threading.Lock()

    def _load_all(self) -> None:
        r = self._client.get("/fapi/v1/exchangeInfo")
        r.raise_for_status()
        data = r.json().get("symbols", [])
        cache: dict[str, Instrument] = {}
        for d in data:
            if d.get("contractType") != "PERPETUAL" or d.get("status") != "TRADING":
                continue
            try:
                tick = step = min_qty = min_notional = 0.0
                for f in d.get("filters", []):
                    ft = f.get("filterType")
                    if ft == "PRICE_FILTER":
                        tick = float(f.get("tickSize") or 0)
                    elif ft == "LOT_SIZE":
                        step = float(f.get("stepSize") or 0)
                        min_qty = float(f.get("minQty") or 0)
                    elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                        min_notional = float(f.get("notional") or f.get("minNotional") or 0)
                cache[d["symbol"]] = Instrument(
                    symbol=d["symbol"], tick_sz=tick, step_sz=step,
                    min_qty=min_qty, min_notional=min_notional,
                    max_lever=self._default_max_lever,
                )
            except (TypeError, ValueError):
                continue
        if cache:
            self._cache = cache
            self._loaded_at = time.monotonic()

    def get(self, symbol: str) -> Instrument | None:
        with self._lock:
            if not self._cache or (time.monotonic() - self._loaded_at) > self._ttl:
                try:
                    self._load_all()
                except httpx.HTTPError as e:
                    log.warning("Binance instruments çekilemedi: %s", e)
            return self._cache.get(symbol)

    def apply_brackets(self, brackets: list[dict[str, Any]]) -> int:
        """leverageBracket sonucunu uygula: her sembolün GERÇEK max kaldıracı +
        notional cap'i. -4028 (geçersiz kaldıraç) ve -2027 (max pozisyon) önler;
        düşük-max-kaldıraçlı junk semboller min_lever kapısıyla elenir. Returns:
        güncellenen sembol sayısı."""
        with self._lock:
            if not self._cache:
                try:
                    self._load_all()
                except httpx.HTTPError:
                    return 0
            n = 0
            for b in brackets or []:
                inst = self._cache.get(b.get("symbol"))
                brs = b.get("brackets") or []
                if inst is None or not brs:
                    continue
                top = brs[0]
                try:
                    lev = float(top.get("initialLeverage") or 0)
                    cap = float(top.get("notionalCap") or 0)
                except (TypeError, ValueError):
                    continue
                if lev > 0:
                    inst.max_lever = lev
                if cap > 0:
                    inst.lev_notional_cap = cap
                n += 1
            return n

    def size_for(self, symbol: str, entry: float, stop: float, price: float,
                 risk_usd: float, equity: float,
                 max_user_lever: int = 100, aggressive_leverage: bool = True,
                 fixed_leverage: int = 0, max_notional: float = 0.0,
                 target_margin: float = 0.0, min_lever: int = 10) -> Sizing | None:
        """$risk + kaldıraç → Binance qty (coin). OKX size_for ile AYNI mantık.

        risk = $risk_usd (SL'e değerse). notional = risk / sl_pct. Kaldıraç sadece
        kilitlenen teminatı belirler, kaybı ($risk) DEĞİL.
        """
        inst = self.get(symbol)
        if inst is None or price <= 0 or entry <= 0:
            return None
        if min_lever > 0 and inst.max_lever < min_lever:
            return Sizing(0, 1, 0, 0, False,
                          f"max kaldıraç düşük ({inst.max_lever:g}x < {min_lever}x), atla")
        sl_pct = abs(entry - stop) / entry
        if sl_pct <= 0:
            return Sizing(0, 1, 0, 0, False, "SL mesafesi 0")
        notional = risk_usd / sl_pct
        # Notional tavanı: dar stop notional'ı şişirir → tavanı aşan setup'ı atla.
        if max_notional > 0 and notional > max_notional:
            return Sizing(0, 1, round(notional, 2), 0, False,
                          f"notional ${notional:.0f} > tavan ${max_notional:.0f} "
                          f"(SL %{sl_pct*100:.2f} çok dar)")
        # Borsa bracket cap'i (leverageBracket): aşılırsa Binance -2027 reddeder → atla.
        if inst.lev_notional_cap > 0 and notional > inst.lev_notional_cap:
            return Sizing(0, 1, round(notional, 2), 0, False,
                          f"notional ${notional:.0f} > borsa bracket cap "
                          f"${inst.lev_notional_cap:.0f} ({symbol} düşük-likidite)")
        if target_margin > 0:
            lever = int(min(max(1, round(notional / target_margin)),
                            inst.max_lever, max_user_lever))
            cap = target_margin * lever
            if notional > cap:
                notional = cap   # risk düşer, margin = cap (kullanıcı kararı)
        elif fixed_leverage > 0:
            lever = int(min(fixed_leverage, inst.max_lever))
        elif aggressive_leverage:
            lever = int(min(inst.max_lever, max_user_lever))
        else:
            lever = max(1, math.ceil(notional / equity)) if equity > 0 else 1
            lever = int(min(lever, inst.max_lever, max_user_lever))
        lever = max(1, lever)
        qty = inst.round_qty(notional / price) if price > 0 else 0
        margin = notional / lever if lever else notional
        if qty < inst.min_qty or qty <= 0:
            return Sizing(qty, lever, notional, margin, False,
                          f"min miktar altı (qty={qty} < min={inst.min_qty})")
        if inst.min_notional > 0 and qty * price < inst.min_notional:
            return Sizing(qty, lever, qty * price, margin, False,
                          f"min notional altı (${qty*price:.2f} < ${inst.min_notional:.0f})")
        return Sizing(sz=qty, leverage=lever, notional_usd=round(qty * price, 2),
                      margin_usd=round(margin, 2), ok=True)

    def close(self) -> None:
        self._client.close()
