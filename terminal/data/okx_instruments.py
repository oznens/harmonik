"""OKX SWAP instrument bilgisi + pozisyon boyutlandırma (kontrat/kaldıraç).

Her parite farklı: ctVal (1 kontrat = kaç coin), max lever, minSz/lotSz.
Bu modül bu bilgiyi çeker (cache'ler) ve "$X risk + dinamik kaldıraç" niyetini
OKX kontrat adedine (sz) çevirir.

Dinamik kaldıraç mantığı (kullanıcı isteği): 1000$ bakiye ile aynı anda birçok
pozisyon açılabilsin → her işlem sabit $risk kullanır, kaldıraç pozisyon notional
/ ayrılan teminat'a göre türetilir, paritenin MAX kaldıracını AŞMAZ.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

from terminal.config import HTTP_TIMEOUT
from terminal.data.okx_futures import OKX_BASE, _to_inst

log = logging.getLogger(__name__)


@dataclass
class Instrument:
    inst_id: str
    ct_val: float        # 1 kontrat = kaç coin (örn. BTC 0.01)
    max_lever: float     # paritenin izin verdiği max kaldıraç
    min_sz: float        # min kontrat adedi
    lot_sz: float        # kontrat adımı (yuvarlama)
    tick_sz: float       # fiyat adımı

    def round_sz(self, sz: float) -> float:
        """Kontrat adedini lot adımına yuvarla (aşağı)."""
        if self.lot_sz <= 0:
            return sz
        return math.floor(sz / self.lot_sz) * self.lot_sz

    def round_px(self, px: float) -> float:
        if self.tick_sz <= 0:
            return px
        return round(round(px / self.tick_sz) * self.tick_sz, 10)


@dataclass
class Sizing:
    """Bir setup için hesaplanan OKX emir boyutu."""
    sz: float            # kontrat adedi (lot'a yuvarlı)
    leverage: int        # kullanılacak kaldıraç (max ile sınırlı)
    notional_usd: float  # pozisyon büyüklüğü ($)
    margin_usd: float    # ayrılan teminat ($) = notional / leverage
    ok: bool             # min boyut/teminat sağlandı mı
    reason: str = ""     # ok=False ise neden


class OkxInstruments:
    """SWAP instrument cache + pozisyon boyutlandırma."""

    def __init__(self, base_url: str = OKX_BASE, timeout: float = HTTP_TIMEOUT,
                 ttl: float = 3600.0, demo: bool = True) -> None:
        # KRİTİK: demo header ŞART. OKX demo ile production'da kontrat specs FARKLI
        # olabiliyor (örn. LIT-USDT-SWAP: prod ctVal=1, demo ctVal=10). Emirler
        # demo'ya gittiği için instrument'ı da demo'dan çekmezsek ctVal uyuşmaz →
        # sz N× şişer (notional/margin/risk N×). okx_trade & okx_futures ile aynı.
        headers = {"User-Agent": "harmonik/1.0 (okx-inst)"}
        if demo:
            headers["x-simulated-trading"] = "1"
        self._client = httpx.Client(base_url=base_url, timeout=timeout,
                                    headers=headers)
        self._cache: dict[str, Instrument] = {}
        self._loaded_at = 0.0
        self._ttl = ttl
        self._lock = threading.Lock()

    def _load_all(self) -> None:
        """Tüm SWAP instrument'larını tek çağrıda çek (cache)."""
        r = self._client.get("/api/v5/public/instruments",
                             params={"instType": "SWAP"})
        r.raise_for_status()
        data = r.json().get("data", [])
        cache: dict[str, Instrument] = {}
        for d in data:
            try:
                cache[d["instId"]] = Instrument(
                    inst_id=d["instId"],
                    ct_val=float(d.get("ctVal") or 0),
                    max_lever=float(d.get("lever") or 1),
                    min_sz=float(d.get("minSz") or 0),
                    lot_sz=float(d.get("lotSz") or 0),
                    tick_sz=float(d.get("tickSz") or 0),
                )
            except (TypeError, ValueError):
                continue
        if cache:
            self._cache = cache
            self._loaded_at = time.monotonic()

    def get(self, symbol: str) -> Instrument | None:
        inst_id = _to_inst(symbol)
        with self._lock:
            if not self._cache or (time.monotonic() - self._loaded_at) > self._ttl:
                try:
                    self._load_all()
                except httpx.HTTPError as e:
                    log.warning("OKX instruments çekilemedi: %s", e)
            return self._cache.get(inst_id)

    def size_for(self, symbol: str, entry: float, stop: float, price: float,
                 risk_usd: float, equity: float,
                 max_user_lever: int = 100,
                 aggressive_leverage: bool = True,
                 fixed_leverage: int = 0,
                 max_notional: float = 0.0,
                 target_margin: float = 0.0) -> Sizing | None:
        """$risk + kaldıraç → OKX kontrat adedi.

        risk = $risk_usd (SL'e değerse kaybedilecek). SL mesafesi %p.
        Notional = risk / p (paper ile aynı — risk SL mesafesiyle sabit).

        Kaldıraç (öncelik sırası):
          target_margin>0: HEDEF MARGIN modu — kaldıraç = notional/target_margin
            (paritenin max'ıyla sınırlı). Her işlem ~target_margin $ teminat tutar
            → 1K bakiyeye çok pozisyon sığar. Risk yine $20 SABİT.
          fixed_leverage>0: sabit kaldıraç (paritenin max'ıyla sınırlı).
          aggressive_leverage=True: paritenin MAX kaldıracı (margin minimum).
          else: ceil(notional/equity).
        ÖNEMLİ: kaldıraç sadece kaç $ KİLİTLENECEĞİNİ değiştirir, kayıp ($20) DEĞİL.
        """
        inst = self.get(symbol)
        if inst is None or inst.ct_val <= 0 or price <= 0 or entry <= 0:
            return None
        sl_pct = abs(entry - stop) / entry
        if sl_pct <= 0:
            return Sizing(0, 1, 0, 0, False, "SL mesafesi 0")
        notional = risk_usd / sl_pct
        # Notional tavanı: dar stop (PaMonic OB) notional'ı şişirir → margin
        # tüketir/51008. Tavanı aşan setup'ı atla (çok dar stop = riskli/likidite).
        if max_notional > 0 and notional > max_notional:
            return Sizing(0, 1, round(notional, 2), 0, False,
                          f"notional ${notional:.0f} > tavan ${max_notional:.0f} "
                          f"(SL %{sl_pct*100:.2f} çok dar)")
        if target_margin > 0:
            # MARGIN CAP modu: her işlem ~target_margin teminat tutsun. Kaldıracı
            # notional'a göre seç (parite max'ıyla sınırlı). Max kaldıraç YETMEZSE
            # (dar stop → dev notional), notional'ı KÜÇÜLT ki margin=cap olsun —
            # bu riski $20'nin altına indirir ama margin sabit kalır (kullanıcı kararı).
            lever = int(min(max(1, round(notional / target_margin)), inst.max_lever))
            max_notional_for_cap = target_margin * lever
            if notional > max_notional_for_cap:
                notional = max_notional_for_cap   # risk düşer, margin = cap
        elif fixed_leverage > 0:
            # Sabit kaldıraç (paritenin max'ıyla sınırlı)
            lever = int(min(fixed_leverage, inst.max_lever))
        elif aggressive_leverage:
            # Max kaldıraç → margin minimum (az parayla çok pozisyon)
            lever = int(min(inst.max_lever, max_user_lever))
        else:
            lever = max(1, math.ceil(notional / equity)) if equity > 0 else 1
            lever = int(min(lever, inst.max_lever, max_user_lever))
        lever = max(1, lever)
        # Kontrat adedi: notional (USD) / (fiyat * ctVal coin)
        coin_per_ct = price * inst.ct_val
        sz_raw = notional / coin_per_ct if coin_per_ct > 0 else 0
        sz = inst.round_sz(sz_raw)
        margin = notional / lever if lever else notional
        if sz < inst.min_sz or sz <= 0:
            return Sizing(sz, lever, notional, margin, False,
                          f"min kontrat altı (sz={sz} < min={inst.min_sz})")
        return Sizing(sz=sz, leverage=lever, notional_usd=round(notional, 2),
                      margin_usd=round(margin, 2), ok=True)

    def close(self) -> None:
        self._client.close()
