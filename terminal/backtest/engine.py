"""Görsel backtest motoru — UI'siz, saf fonksiyon.

Bir mum dizisi üzerinde harmonik formasyonları tarar (scan_klines), seçilen
giriş moduyla simüle eder (simulate_outcome), kronolojik portföyü hesaplar
(simulate_portfolio) ve HER İŞLEMİN grafik verisini (XABCD pivotları + giriş/
çıkış + sonuç) üretir. UI 'Backtest' sekmesi bunu lightweight-charts ile çizer.

DB'ye yazmaz. CLI'dan veya UI'dan çağrılabilir.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from terminal.detection.scanner import default_threshold, scan_klines
from terminal.karakter.portfolio import simulate_portfolio
from terminal.karakter.simulator import simulate_outcome

_PIVOT_LETTERS = "XABCD"


def _sec(ms: int) -> int:
    return int(ms) // 1000


@dataclass
class BacktestResult:
    symbol: str
    interval: str
    entry_mode: str
    candles: list[dict[str, Any]]   # lightweight-charts mum verisi (time saniye)
    trades: list[dict[str, Any]]    # her işlem: pivots + giriş/çıkış + outcome + pnl
    equity: list[dict[str, Any]]    # {time, value} equity eğrisi
    stats: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "interval": self.interval,
            "entry_mode": self.entry_mode, "candles": self.candles,
            "trades": self.trades, "equity": self.equity, "stats": self.stats,
        }


def _exit_price(setup, outcome: str) -> float:
    return {"TP": setup.tp1, "STOP": setup.stop}.get(outcome, setup.entry)


def load_db_klines(store, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
    """DB klines tablosundan son `limit` mumu kronolojik döner (backtest verisi).

    download_history ile doldurulur. Boşsa [] döner (çağıran canlı çekebilir).
    """
    rows = store._conn.execute(
        """SELECT open_time, close_time, open, high, low, close, volume, quote_volume
           FROM klines WHERE symbol = ? AND interval = ?
           ORDER BY open_time DESC LIMIT ?""",
        (symbol, interval, limit),
    ).fetchall()
    return [
        {"open_time": r[0], "close_time": r[1], "open": r[2], "high": r[3],
         "low": r[4], "close": r[5], "volume": r[6], "quote_volume": r[7]}
        for r in reversed(rows)
    ]


def run_backtest(
    klines: list[dict[str, Any]],
    symbol: str,
    interval: str,
    entry_mode: str = "limit",
    zigzag: float | None = None,
    min_rr: float = 1.0,
    target_mode: str = "rr1",
    include_abcd: bool = False,
) -> BacktestResult:
    """Mum dizisi üzerinde backtest çalıştır → grafik + istatistik verisi.

    Varsayılanlar CANLI sistemle (harmonik.service) aynı seçilir, böylece
    backtest sonuçları paper/journal ile birebir kıyaslanabilir:
        entry_mode="limit" (PRZ-zone dolum), target_mode="rr1" (tek 1:1 hedef),
        include_abcd=False (--no-abcd: yalnız gerçek harmonikler).
    Diğer modlar (market/structural/+AB=CD) karşılaştırma için override edilebilir.

    target_mode: "rr1" (canlı: tek sabit 1:1 R:R hedef) veya "structural"
        (TP1=B/TP2=A yapısal). include_abcd: True ise standalone AB=CD de taranır.
    """
    if not klines:
        return BacktestResult(symbol, interval, entry_mode, [], [], [], {})

    threshold = zigzag if zigzag is not None else default_threshold(interval)
    setups = scan_klines(klines, symbol, interval, zigzag_threshold=threshold,
                         min_rr=min_rr, target_mode=target_mode, include_abcd=include_abcd)

    idx_of = {k["open_time"]: i for i, k in enumerate(klines)}
    raw_trades: list[dict[str, Any]] = []
    setup_by_open: dict[int, Any] = {}   # giriş zamanı → setup (pivot çizimi için)
    sims: list[tuple[Any, Any]] = []     # (setup, outcome) — TÜM simüle edilen setuplar

    for s in setups:
        if s.elenen:
            continue
        d_idx = idx_of.get(s.pivots["D"].time)
        if d_idx is None or d_idx >= len(klines) - 1:
            continue
        future = klines[d_idx + 1:]
        o = simulate_outcome(s, future, entry_mode=entry_mode)
        sims.append((s, o))
        if o.entered_price is None or o.exited_time is None:
            continue  # girilmedi (EO) ya da kapanmadı → portföye girmez
        raw_trades.append({
            "symbol": s.symbol, "interval": s.interval, "pattern": s.pattern_name,
            "direction": s.direction, "ideal_entry": s.entry, "stop": s.stop,
            "tp1": s.tp1, "fill": o.entered_price, "open_time": o.entered_time,
            "close_time": o.exited_time, "outcome": o.outcome,
            "confluence": s.confluence_score or 0,
        })
        # Birden çok setup aynı bara girebilir; portföy parite-başı-tek ile birini
        # alır. Çizim için open_time → setup eşle (ilk gelen yeter).
        setup_by_open.setdefault(o.entered_time, (s, o))

    pf = simulate_portfolio(raw_trades)

    def _pivots(s) -> list[dict[str, Any]]:
        out = []
        for letter in _PIVOT_LETTERS:
            p = s.pivots.get(letter)
            if p is not None:
                out.append({"time": _sec(p.time), "value": p.price, "label": letter})
        return out

    # Portföyün GERÇEKTEN aldığı işlemleri (pf.closed) pivotlarıyla TAM çiz
    trades: list[dict[str, Any]] = []
    taken: set[int] = set()
    for c in pf.closed:
        so = setup_by_open.get(c["open_time"])
        if so is None:
            continue
        s, o = so
        taken.add(c["open_time"])
        trades.append({
            "pattern": s.pattern_name, "direction": s.direction,
            "outcome": c["outcome"], "pnl": c["pnl"], "faint": False,
            "pivots": _pivots(s),
            "entry": {"time": _sec(o.entered_time), "price": o.entered_price},
            "exit": {"time": _sec(o.exited_time or 0),
                     "price": _exit_price(s, c["outcome"])},
            "stop": s.stop, "tp1": s.tp1, "entry_level": s.entry,
        })

    # Dolmayan / portföyün almadığı setuplar — SOLUK çiz (XABCD + EO/sonuç etiketi)
    # "setup var ama işlem yok" durumunda grafik boş kalmasın diye.
    eo = 0
    for s, o in sims:
        if o.entered_price is None:
            eo += 1
        if (o.entered_price is not None and o.exited_time is not None
                and o.entered_time in taken):
            continue   # zaten tam çizildi
        trades.append({
            "pattern": s.pattern_name, "direction": s.direction,
            "outcome": o.outcome, "pnl": 0.0, "faint": True,
            "pivots": _pivots(s),
            "stop": s.stop, "tp1": s.tp1, "entry_level": s.entry,
        })

    equity = [{"time": _sec(ct), "value": eq} for ct, eq in pf.equity_curve]
    stats = {
        "n_trades": pf.n_trades, "tp": pf.tp, "stop": pf.stop, "zi": pf.zi,
        "win_rate": pf.win_rate, "total_pnl": pf.total_pnl, "pnl_pct": pf.pnl_pct,
        "max_drawdown_pct": pf.max_drawdown_pct, "final_equity": pf.final_equity,
        "initial_equity": pf.initial_equity, "n_setups": len(setups),
        "skipped_busy": pf.skipped_busy, "eo": eo, "n_detected": len(sims),
    }
    candles = [
        {"time": _sec(k["open_time"]), "open": k["open"], "high": k["high"],
         "low": k["low"], "close": k["close"]}
        for k in klines
    ]
    return BacktestResult(symbol, interval, entry_mode, candles, trades, equity, stats)
