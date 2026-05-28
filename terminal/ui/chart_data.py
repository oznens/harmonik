"""Canlı grafik veri katmanı (UI bağımsız, saf veri → JSON-serileştirilebilir).

lightweight-charts (TradingView) tarafının beklediği biçimde mum + katman
verisi üretir. Katmanlar SADECE bu repoda gerçek veri karşılığı olanlardır:

  - Pivot   : ZigZag swing high/low işaretleri (find_pivots)
  - Vector  : pivotları birleştiren ZigZag çizgisi (piyasa yapısı)
  - Harmonic: en son tespit edilen Setup'ın XABCD çizimi + PRZ + Entry/SL/TP
  - HTF     : üst zaman dilimi trend rozeti (Setup.htf_trend)

Zaman birimi: lightweight-charts saniye (UTC) bekler; DB ms tutar → //1000.
"""
from __future__ import annotations

from typing import Any

from terminal.config import INTERVAL_SECONDS
from terminal.db.store import Store
from terminal.detection.pivots import find_pivots
from terminal.detection.scanner import default_threshold

# Mum renkleri (mevcut charts.py ile uyumlu)
UP_COLOR = "#26a69a"
DOWN_COLOR = "#ef5350"
VOL_UP = "rgba(38,166,154,0.45)"
VOL_DOWN = "rgba(239,83,80,0.45)"
GOLD = "#d4a72c"
GREEN = "#4caf50"
RED = "#ef5350"
BLUE = "#42a5f5"

_FALLBACK_SYMBOLS = ["BTCUSDT", "ETHUSDT"]


def _sec(ms: int) -> int:
    return int(ms) // 1000


def _bar(k: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": _sec(k["open_time"]),
        "open": k["open"], "high": k["high"],
        "low": k["low"], "close": k["close"],
    }


def _vol(k: dict[str, Any]) -> dict[str, Any]:
    up = k["close"] >= k["open"]
    return {
        "time": _sec(k["open_time"]),
        "value": k.get("volume") or 0.0,
        "color": VOL_UP if up else VOL_DOWN,
    }


def available_pairs(store: Store) -> dict[str, list[str]]:
    """DB'de mevcut parite ve aralıkları döner (combo doldurmak için)."""
    conn = store._conn
    syms: list[str] = []
    try:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM klines "
            "UNION SELECT DISTINCT symbol FROM setups ORDER BY symbol"
        ).fetchall()
        syms = [r[0] for r in rows if r[0]]
    except Exception:
        pass
    if not syms:
        syms = list(_FALLBACK_SYMBOLS)

    ivls: list[str] = []
    try:
        rows = conn.execute("SELECT DISTINCT interval FROM klines").fetchall()
        ivls = [r[0] for r in rows if r[0]]
    except Exception:
        pass
    if not ivls:
        ivls = ["15m", "60m", "4h", "1d"]
    # Kronolojik sırala (1m → 1d ...)
    ivls.sort(key=lambda iv: INTERVAL_SECONDS.get(iv, 1 << 30))
    return {"symbols": syms, "intervals": ivls}


def _load_klines(
    store: Store, symbol: str, interval: str, limit: int, client: Any | None,
) -> list[dict[str, Any]]:
    """Önce DB'den son `limit` mumu al; yetersizse MEXC'den çek (client verilmişse)."""
    cur = store._conn.execute(
        """SELECT open_time, close_time, open, high, low, close, volume, quote_volume
           FROM klines WHERE symbol = ? AND interval = ?
           ORDER BY open_time DESC LIMIT ?""",
        (symbol, interval, limit),
    )
    rows = cur.fetchall()
    klines = [
        {"open_time": r[0], "close_time": r[1], "open": r[2], "high": r[3],
         "low": r[4], "close": r[5], "volume": r[6], "quote_volume": r[7]}
        for r in reversed(rows)
    ]
    if len(klines) >= 20 or client is None:
        return klines
    # DB yetersiz → canlı fetch (kapanmamış son mum dahil olabilir)
    try:
        return client.klines(symbol, interval, limit=limit)
    except Exception:
        return klines


def _zigzag_layers(
    klines: list[dict[str, Any]], interval: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Pivot işaretleri + Vector (zigzag) çizgisi."""
    pivots = find_pivots(klines, default_threshold(interval))
    markers = []
    line = []
    for p in pivots:
        t = _sec(p.time)
        line.append({"time": t, "value": p.price})
        if p.kind == "high":
            markers.append({"time": t, "position": "aboveBar",
                            "color": RED, "shape": "arrowDown"})
        else:
            markers.append({"time": t, "position": "belowBar",
                            "color": GREEN, "shape": "arrowUp"})
    markers.sort(key=lambda m: m["time"])
    line.sort(key=lambda d: d["time"])
    return ({"markers": markers}, {"line": line})


def _latest_setup_id(store: Store, symbol: str, interval: str) -> int | None:
    """Bu parite/aralık için gösterilecek setup.

    Önce AÇIK (Aktif/Aday) setup'lar arasından en son OLUŞAN'ı (en yeni D
    zamanı) seçer; yoksa kapalılar dahil en son oluşan setup'a düşer.
    `detected_at` (tarama anı) yerine `d_time` (formasyon anı) kullanılır —
    aksi halde eski bir formasyon yeniden tarandığında "en yeni" sanılır.
    """
    c = store._conn
    row = c.execute(
        """SELECT s.id FROM setups s
           JOIN setup_lifecycle l ON l.setup_id = s.id
           WHERE s.symbol = ? AND s.interval = ? AND s.elenen = 0
             AND l.state IN ('Aktif', 'Aday')
           ORDER BY s.d_time DESC LIMIT 1""",
        (symbol, interval),
    ).fetchone()
    if row:
        return int(row[0])
    row = c.execute(
        """SELECT id FROM setups
           WHERE symbol = ? AND interval = ? AND elenen = 0
           ORDER BY d_time DESC LIMIT 1""",
        (symbol, interval),
    ).fetchone()
    return int(row[0]) if row else None


def _harmonic_layer(store: Store, symbol: str, interval: str) -> dict[str, Any]:
    """En son Setup → XABCD çizgisi + harf işaretleri + Entry/SL/TP/PRZ seviyeleri."""
    sid = _latest_setup_id(store, symbol, interval)
    if sid is None:
        return {"present": False}
    setup = store.load_setup(sid)
    if setup is None:
        return {"present": False}

    line = []
    markers = []
    for letter in "XABCD":
        p = setup.pivots.get(letter)
        if p is None:
            continue
        t = _sec(p.time)
        line.append({"time": t, "value": p.price})
        above = p.kind == "high"
        markers.append({
            "time": t,
            "position": "aboveBar" if above else "belowBar",
            "color": GOLD, "shape": "circle", "text": letter,
        })
    line.sort(key=lambda d: d["time"])
    markers.sort(key=lambda m: m["time"])

    levels = [
        {"price": setup.entry, "color": BLUE, "title": "Entry", "style": "solid"},
        {"price": setup.stop, "color": RED, "title": "SL", "style": "dashed"},
        {"price": setup.tp1, "color": GREEN, "title": "TP1", "style": "dashed"},
        {"price": setup.tp2, "color": GREEN, "title": "TP2", "style": "dotted"},
        {"price": setup.prz_low, "color": GOLD, "title": "PRZ↓", "style": "dotted"},
        {"price": setup.prz_high, "color": GOLD, "title": "PRZ↑", "style": "dotted"},
    ]
    q_part = f" · Q{setup.q_score} {setup.q_category}".rstrip() if setup.q_score else ""
    label = f"{setup.direction.upper()} {setup.pattern_name}{q_part}"
    return {
        "present": True, "label": label, "direction": setup.direction,
        "line": line, "markers": markers, "levels": levels,
    }


def _htf_layer(store: Store, symbol: str, interval: str) -> dict[str, Any]:
    sid = _latest_setup_id(store, symbol, interval)
    if sid is None:
        return {"present": False}
    setup = store.load_setup(sid)
    if setup is None or not setup.htf_trend:
        return {"present": False}
    trend = setup.htf_trend
    arrow = {"bull": "▲", "bear": "▼"}.get(trend, "■")
    color = {"bull": GREEN, "bear": RED}.get(trend, "#888894")
    htf_iv = setup.htf_interval or "HTF"
    return {
        "present": True, "trend": trend, "color": color,
        "text": f"HTF {htf_iv} {arrow} {trend.upper()}",
    }


def build_payload(
    store: Store, symbol: str, interval: str,
    limit: int = 200, client: Any | None = None,
    include_pairs: bool = True,
    klines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tam grafik yükü: mumlar + tüm katmanlar (full reload).

    `klines` verilirse DB/ağ yüklemesi atlanır (çağıran kendi mumunu sağlar).
    """
    if klines is None:
        klines = _load_klines(store, symbol, interval, limit, client)
    payload: dict[str, Any] = {
        "type": "full",
        "symbol": symbol,
        "interval": interval,
        "candles": [_bar(k) for k in klines],
        "volume": [_vol(k) for k in klines],
        "pivots": {"markers": []},
        "vector": {"line": []},
        "harmonic": {"present": False},
        "htf": {"present": False},
    }
    if klines:
        payload["pivots"], payload["vector"] = _zigzag_layers(klines, interval)
        payload["harmonic"] = _harmonic_layer(store, symbol, interval)
        payload["htf"] = _htf_layer(store, symbol, interval)
    if include_pairs:
        payload["pairs"] = available_pairs(store)
    return payload


def fetch_live(
    symbol: str, interval: str, client: Any, limit: int = 3,
) -> dict[str, Any]:
    """Son birkaç mumu canlı çek → sadece candle/volume güncellemesi."""
    klines = client.klines(symbol, interval, limit=limit)
    return {
        "type": "live",
        "candles": [_bar(k) for k in klines],
        "volume": [_vol(k) for k in klines],
    }
