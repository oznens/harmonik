"""Buffer üstünde gezip Setup listesi üreten ana orkestratör.

Stateless: her çağrıda kline listesini alır, ZigZag çalıştırır, ardışık
5'li pivot pencerelerinde formasyon arar, eşleşenleri Setup olarak döner.
İsteğe bağlı HTF mum dizisi verilirse Q skoru ve elenen bayrağı hesaplanır.
"""
from __future__ import annotations

import logging
import time
from typing import Any

from terminal.detection.matcher import match_xabcd
from terminal.detection.models import Setup
from terminal.detection.patterns.abcd import build_abcd_setup, match_abcd
from terminal.detection.patterns.cypher import build_cypher_setup, match_cypher
from terminal.detection.patterns.shark import build_shark_setup, match_shark
# PDF kapsamı dışı patternler (5-0, Three Drives) detection'a dahil edilmiyor.
from terminal.detection.pivots import find_pivots
from terminal.detection.prz import compute_prz, compute_trade_levels
from terminal.quality.confluence import compute_confluence
from terminal.quality.htf_ltf import alignment, detect_trend, htf_for
from terminal.quality.score import compute_q

log = logging.getLogger(__name__)

# TF başı varsayılan ZigZag eşikleri (yüzde olarak).
# Kullanıcı geri bildirimi: "iç dalgaları yakala". %30 azaltma — daha
# fazla pivot ama gürültü kontrolünde. (2x agresif denendi: sample 2.5x
# arttı ama gerçekçi maliyetli R 5x kötüleşti. %30 daha sağlıklı denge.)
DEFAULT_THRESHOLDS: dict[str, float] = {
    "1m": 0.002,
    "5m": 0.0035,
    "15m": 0.007,
    "30m": 0.010,
    "60m": 0.014,
    "2h":  0.017,
    "4h":  0.021,
    "8h":  0.028,
    "1d":  0.035,
    "1W":  0.056,
}


def default_threshold(interval: str) -> float:
    return DEFAULT_THRESHOLDS.get(interval, 0.02)


def scan_klines(
    klines: list[dict[str, Any]],
    symbol: str,
    interval: str,
    zigzag_threshold: float | None = None,
    htf_klines: list[dict[str, Any]] | None = None,
    min_rr: float = 1.0,
    target_mode: str = "structural",
    include_abcd: bool = True,
) -> list[Setup]:
    """Mum dizisinden formasyonları çıkar; opsiyonel HTF ile Q skoru hesapla.

    Args:
        klines: setup TF'sinin mum dizisi (eski → yeni).
        symbol: parite kodu (örn. "BTCUSDT").
        interval: setup aralığı ("15m", "60m"/"1h", "4h", "1d"...).
        zigzag_threshold: özelse yüzde (örn. 0.02). Yoksa interval varsayılanı.
        htf_klines: üst zaman dilimi mum dizisi (HTF trend için). Yoksa
                    Q skorunda HTF bileşeni 0 olur, elenen tespiti yapılmaz.
        target_mode: hedef (TP) modeli — "structural" (varsayılan: TP1=B,
            TP2=A yapısal swing'ler, değişken R:R) veya "rr1" (terminalMiraz
            referans modeli: tek sabit 1:1 R:R hedef, TP1=Entry∓1R, TP2=∓2R).
        include_abcd: False ise standalone AB=CD (4-nokta) ailesi taranmaz —
            yalnızca gerçek 5-nokta harmonikler (Gartley/Bat/Butterfly/Crab/
            Shark/Cypher) kalır. AB=CD en gürültülü + en zayıf aile; referans
            terminalMiraz da kullanmıyor.

    Returns:
        Setup listesi (Q skoru ve HTF bilgisi doldurulmuş).
    """
    threshold = zigzag_threshold if zigzag_threshold is not None else default_threshold(interval)
    pivots = find_pivots(klines, threshold)
    if len(pivots) < 4:
        return []

    # HTF trendi (tüm setup'lar için aynı, bir kez hesapla)
    htf_interval = htf_for(interval)
    htf_trend: str | None = None
    if htf_klines is not None and htf_interval is not None:
        htf_trend = detect_trend(htf_klines)

    detected_at = int(time.time() * 1000)
    setups: list[Setup] = []
    seen_keys: set[tuple] = set()  # aynı pivot kombinasyonu birden fazla pattern olarak eşleşmesin

    # 1) 5-pivot pencerelerde XABCD ailesi (Gartley/Bat/Butterfly/Crab/...)
    for i in range(len(pivots) - 4):
        m = match_xabcd(pivots[i:i + 5])
        if m is None:
            continue
        q = m.quintet
        prz = compute_prz(m)
        levels = compute_trade_levels(m, prz)
        setup = Setup(
            symbol=symbol, interval=interval,
            pattern_name=m.spec.name, direction=q.direction,
            pivots={"X": q.x, "A": q.a, "B": q.b, "C": q.c, "D": q.d},
            b_ratio=m.b_ratio, c_ratio=m.c_ratio, d_ratio=m.d_ratio,
            bc_proj=m.bc_proj, cd_ab_ratio=m.cd_ab_ratio,
            ab_cd_equivalent=m.ab_cd_equivalent,
            prz_low=prz["prz_low"], prz_high=prz["prz_high"],
            prz_components=prz["prz_components"],
            entry=levels["entry"], stop=levels["stop"],
            tp1=levels["tp1"], tp2=levels["tp2"],
            detected_at=detected_at,
            htf_interval=htf_interval, htf_trend=htf_trend,
            pattern_family="xabcd",
        )
        _finalize(setup, htf_trend)
        _normalize_sl(setup)
        _apply_target_mode(setup, target_mode)
        if not _has_valid_rr(setup, min_rr):
            continue
        _apply_confluence(setup, klines)
        setups.append(setup)
        seen_keys.add((m.spec.name, q.x.time, q.a.time, q.b.time, q.c.time, q.d.time))

    # 2) 4-pivot pencerelerde standalone AB=CD (include_abcd=False ise atla)
    if include_abcd:
        for i in range(len(pivots) - 3):
            m_abcd = match_abcd(pivots[i:i + 4])
            if m_abcd is None:
                continue
            setup = build_abcd_setup(m_abcd, symbol, interval)
            setup.detected_at = detected_at
            setup.htf_interval = htf_interval
            setup.htf_trend = htf_trend
            # Aynı pivotları XABCD olarak da eşleşmişse atla (XABCD'nin parçası zaten)
            key = ("ABCD", setup.pivots["A"].time, setup.pivots["B"].time,
                   setup.pivots["C"].time, setup.pivots["D"].time)
            if any(k[2:] == key[1:] for k in seen_keys):
                continue
            _finalize(setup, htf_trend)
            _normalize_sl(setup)
            _apply_target_mode(setup, target_mode)
            if not _has_valid_rr(setup, min_rr):
                continue
            _apply_confluence(setup, klines)
            setups.append(setup)

    # 3) 5-pivot pencerelerde Shark (0-X-A-B-C, farklı kural)
    for i in range(len(pivots) - 4):
        m_sh = match_shark(pivots[i:i + 5])
        if m_sh is None:
            continue
        setup = build_shark_setup(m_sh, symbol, interval)
        setup.detected_at = detected_at
        setup.htf_interval = htf_interval
        setup.htf_trend = htf_trend
        # Aynı 5 pivot XABCD olarak da eşleşmişse atla (daha katı XABCD önceliklidir)
        key = (m_sh.p0.time, m_sh.x.time, m_sh.a.time, m_sh.b.time, m_sh.c.time)
        already = any(k[1:6] == key for k in seen_keys)
        if already:
            continue
        _finalize(setup, htf_trend)
        _normalize_sl(setup)
        _apply_target_mode(setup, target_mode)
        if not _has_valid_rr(setup, min_rr):
            continue
        _apply_confluence(setup, klines)
        setups.append(setup)

    # 4) 5-pivot pencerelerde Cypher (X-A-B-C-D, C XA extension'ı)
    for i in range(len(pivots) - 4):
        m_cy = match_cypher(pivots[i:i + 5])
        if m_cy is None:
            continue
        setup = build_cypher_setup(m_cy, symbol, interval)
        setup.detected_at = detected_at
        setup.htf_interval = htf_interval
        setup.htf_trend = htf_trend
        # Aynı 5 pivot XABCD/Shark olarak da eşleşmişse atla
        key = (m_cy.x.time, m_cy.a.time, m_cy.b.time, m_cy.c.time, m_cy.d.time)
        already = any(k[1:6] == key for k in seen_keys)
        if already:
            continue
        _finalize(setup, htf_trend)
        _normalize_sl(setup)
        _apply_target_mode(setup, target_mode)
        if not _has_valid_rr(setup, min_rr):
            continue
        _apply_confluence(setup, klines)
        setups.append(setup)

    # PDF kapsamı dışı: 5-0 ve Three Drives pattern detection devre dışı.
    return setups


# Pattern-spesifik HTF zıt elenen listesi.
# Backtest (3 ay × 5 parite × 3 TF) verisinde HTF zıt durumda net negatif R
# üreten pattern'ler. Diğer harmonik desenler mean-reversion doğası gereği
# HTF zıt'ta daha iyi performe ediyor (toplam +18.52R zıt vs +11.28R uyumlu)
# — bu yüzden default olarak elenen sayılmıyor.
HTF_OPPOSITE_PENALIZED: frozenset[str] = frozenset({
    "1.62 AB=CD",  # HTF zıt: N=28, WR=33.3%, TotR=-7.43, AvgR=-0.31
})

# Minimum SL mesafesi (entry'nin yüzdesi olarak). Dar PRZ aralığında entry
# pattern_stop'a çok yakın geliyor — 1-tick slippage SL'yi geçirir, R hesabı
# anlamsız. 14 parite × 15m × 1 ay backtest: 14 standalone AB=CD setup
# %0.3'ün altındaydı (R:R 10-53, %5'i toplam sample'ın). Bu filtre live'da
# riski yönetilebilir setuplarla sınırlar.
MIN_SL_PCT = 0.004  # %0.4


def _is_elenen(setup: Setup) -> bool:
    """Setup elenen havuzuna mı düşmeli? Pattern-spesifik kötü kombinasyonlar."""
    if setup.htf_aligned is False and setup.pattern_name in HTF_OPPOSITE_PENALIZED:
        return True
    return False


def _normalize_sl(setup: Setup) -> None:
    """SL mesafesi MIN_SL_PCT'in altındaysa, SL'i entry'den MIN_SL_PCT uzağa it.

    Dar PRZ aralığında entry ≈ pattern_stop oluşuyor — 1-tick slippage SL'yi
    geçirir, R hesabı anlamsız. Setup'ı düşürmek yerine SL'i normalize ediyoruz:
    sample korunur, R:R gerçekçi olur (53.65 → 5 gibi), live'da uygulanabilir.
    """
    if setup.entry <= 0:
        return
    dist_pct = abs(setup.entry - setup.stop) / setup.entry
    if dist_pct >= MIN_SL_PCT:
        return
    if setup.direction == "bull":
        setup.stop = setup.entry * (1 - MIN_SL_PCT)
    else:
        setup.stop = setup.entry * (1 + MIN_SL_PCT)


def _apply_target_mode(setup: Setup, target_mode: str) -> None:
    """Hedef (TP) modelini setup'a uygula (in-place). _normalize_sl SONRASI çağır.

    "structural" (varsayılan): pattern-spesifik yapısal hedefler (TP1=B, TP2=A
        XABCD'de; AB=CD/Shark/Cypher kendi swing'leri). Değişken R:R.
    "rr1": terminalMiraz referans modeli — TEK sabit 1:1 R:R hedef.
        Hedef = Entry ∓ 1×|Stop−Entry|. TP1=1R (referansın "Hedef"i), TP2=2R
        (genişletilmiş/runner, bilgi amaçlı). Tüm pattern aileleri için aynı.
        Referans örnekleri: ARB short E0.11289/SL0.11674→H0.10904 (risk=ödül),
        FIL short E1.07615/SL1.13739→H1.01491, DYDX long E0.13876/SL0.12704→H0.15047.
    """
    if target_mode != "rr1":
        return
    sign = -1 if setup.direction == "bull" else 1
    risk = abs(setup.stop - setup.entry)
    if risk <= 0:
        return
    # sign=-1 (bull) → hedef yukarı (entry+risk); sign=+1 (bear) → aşağı (entry−risk)
    setup.tp1 = setup.entry - sign * risk
    setup.tp2 = setup.entry - sign * 2.0 * risk


def time_symmetry(setup: Setup) -> float:
    """AB ve CD bacaklarının ZAMAN (bar süresi) simetrisi → [0,1].

    1.0 = bacaklar eşit süreli (temiz AB=CD). Düşük = bir bacak çok hızlı
    (sert trend-dump, harmonik görünümlü ama değil). Filtre: bu eşiğin altı
    elenir → fakeout azalır.
    """
    p = setup.pivots
    t_ab = abs(p["B"].time - p["A"].time)
    t_cd = abs(p["D"].time - p["C"].time)
    if t_ab <= 0 or t_cd <= 0:
        return 0.0
    return min(t_ab, t_cd) / max(t_ab, t_cd)


def _has_valid_rr(setup: Setup, min_rr: float = 1.0) -> bool:
    """R:R ≥ min_rr mu? TP-mesafesi SL-mesafesinden az olan setuplar reject edilir.

    Trade inceleme (1 ay × 14 parite × 15m): 13 TP "kazandı" ama R:R < 1
    (kazanç < SL boyutu). Çoğu 1.62 AB=CD'de — uzun CD bacağı yüzünden TP=B
    yapısal swing entry'ye çok yakın geliyor. Bu setuplarda potansiyel kazanç
    risk'ten küçük, asimetrik dezavantaj. min_rr=0.0 → filtre bypass (testler).
    """
    if min_rr <= 0:
        return True
    sl_dist = abs(setup.entry - setup.stop)
    tp_dist = abs(setup.tp1 - setup.entry)
    return sl_dist > 0 and (tp_dist / sl_dist) >= min_rr


def _finalize(setup: Setup, htf_trend: str | None) -> None:
    """Setup'a Q skoru ve HTF uyumu doldur (in-place)."""
    qr = compute_q(setup, htf_trend=htf_trend)
    setup.q_score = qr.score
    setup.q_category = qr.category
    setup.q_components = qr.components
    setup.htf_aligned = alignment(setup.direction, htf_trend)
    setup.elenen = _is_elenen(setup)


def _apply_confluence(setup: Setup, klines: list[dict[str, Any]]) -> None:
    """Setup'a RSI + hacim confluence skorunu ekle. klines D pivot dahil."""
    d_time = setup.pivots["D"].time
    d_idx = next((i for i, k in enumerate(klines) if k["open_time"] == d_time), None)
    if d_idx is None:
        return
    b_time = setup.pivots.get("B", setup.pivots["D"]).time
    b_idx = next((i for i, k in enumerate(klines) if k["open_time"] == b_time), None)
    cr = compute_confluence(setup.direction, d_idx, klines, b_idx=b_idx)
    setup.confluence_score = cr.score
    setup.confluence_components = cr.components
    setup.rsi_at_d = cr.rsi_at_d
    setup.volume_ratio = cr.volume_ratio
