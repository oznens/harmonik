"""Portföy backtest simülatörü — karakter lab setuplarını canlı paper kuralları
ile tek hesapta kronolojik simüle eder.

Canlı sistemle aynı kurallar:
- Tek $1000 hesap, $20 risk/işlem, kaldıraç SL mesafesine göre (compute_position)
- Dolum = sonraki barın açılışı (SimOutcome.entered_price); P&L bu fiyata göre
- Parite başına tek açık pozisyon (ilk AKTIF kazanır)
- Komisyon TP/STOP'ta (COMMISSION_PCT × 2)
- Equity bileşik büyür; kronolojik (open_time sırası, kapanışlar zamanında işlenir)

Pure function: DB'ye yazmaz, sadece sonuç döner.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any

from terminal.paper.engine import COMMISSION_PCT, compute_position


@dataclass
class PortfolioResult:
    initial_equity: float
    final_equity: float
    total_pnl: float
    pnl_pct: float
    n_trades: int              # kapanan işlem sayısı
    tp: int
    stop: int
    zi: int
    win_rate: float
    max_drawdown_pct: float
    skipped_busy: int          # parite dolu olduğu için açılmayan
    equity_curve: list[tuple[int, float]]  # (close_time_ms, equity)
    closed: list[dict] = field(default_factory=list)


def simulate_portfolio(
    trades: list[dict[str, Any]],
    initial_equity: float = 1000.0,
    risk_per_trade: float = 20.0,
    max_leverage: int = 20,
    min_confluence: int = 0,
) -> PortfolioResult:
    """Setup işlemlerini kronolojik portföy olarak simüle et.

    Args:
        trades: her biri şu alanları içeren dict listesi:
            symbol, interval, pattern, direction,
            ideal_entry, stop, tp1,        # pozisyon boyutu ideal'den
            fill,                          # gerçek dolum (sonraki bar açılışı)
            open_time, close_time,         # ms
            outcome,                       # 'TP'/'STOP'/'ZI'
            confluence                     # confluence skoru (filtre için)
        min_confluence: yalnızca confluence >= bu eşik işlemler alınır
            (0 = filtre yok). Canlı --paper-min-confluence ile aynı mantık.
    """
    # Sadece gerçekten pozisyon açan & kapanan işlemler (EO girilmez, Aktif kapanmadı)
    cand = [
        t for t in trades
        if t.get("open_time") is not None and t.get("close_time") is not None
        and t.get("fill") and t["outcome"] in ("TP", "STOP", "ZI")
        and t.get("confluence", 0) >= min_confluence
    ]
    cand.sort(key=lambda t: t["open_time"])

    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0
    skipped_busy = 0
    open_symbols: set[str] = set()
    closed: list[dict] = []
    curve: list[tuple[int, float]] = []
    heap: list[tuple[int, int, dict]] = []  # (close_time, seq, result)
    seq = 0

    def _settle_until(t_time: int) -> None:
        nonlocal equity, peak, max_dd
        while heap and heap[0][0] <= t_time:
            ct, _, res = heapq.heappop(heap)
            equity += res["pnl"]
            open_symbols.discard(res["symbol"])
            res["equity_after"] = round(equity, 2)
            closed.append(res)
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)
            curve.append((ct, round(equity, 2)))

    for t in cand:
        _settle_until(t["open_time"])
        if t["symbol"] in open_symbols:
            skipped_busy += 1
            continue
        position, leverage = compute_position(
            t["ideal_entry"], t["stop"], equity, risk_per_trade, max_leverage,
        )
        if position <= 0:
            continue
        fill = t["fill"]
        if t["outcome"] == "TP":
            pnl_gross = position * abs(t["tp1"] - fill) / fill
        elif t["outcome"] == "STOP":
            pnl_gross = -position * abs(fill - t["stop"]) / fill
        else:  # ZI
            pnl_gross = 0.0
        commission = position * COMMISSION_PCT * 2 if t["outcome"] in ("TP", "STOP") else 0.0
        pnl_net = round(pnl_gross - commission, 2)

        res = {
            "symbol": t["symbol"], "interval": t["interval"],
            "pattern": t["pattern"], "direction": t["direction"],
            "fill": fill, "stop": t["stop"], "tp1": t["tp1"],
            "position": position, "leverage": leverage,
            "outcome": t["outcome"], "pnl": pnl_net,
            "open_time": t["open_time"], "close_time": t["close_time"],
        }
        open_symbols.add(t["symbol"])
        seq += 1
        heapq.heappush(heap, (t["close_time"], seq, res))

    _settle_until(float("inf"))  # kalan açıkları kapat

    tp = sum(1 for c in closed if c["outcome"] == "TP")
    stop = sum(1 for c in closed if c["outcome"] == "STOP")
    zi = sum(1 for c in closed if c["outcome"] == "ZI")
    decided = tp + stop
    wr = (tp / decided * 100) if decided else 0.0
    total_pnl = equity - initial_equity

    return PortfolioResult(
        initial_equity=initial_equity,
        final_equity=round(equity, 2),
        total_pnl=round(total_pnl, 2),
        pnl_pct=round(total_pnl / initial_equity * 100, 2) if initial_equity else 0.0,
        n_trades=len(closed),
        tp=tp, stop=stop, zi=zi,
        win_rate=round(wr, 1),
        max_drawdown_pct=round(max_dd * 100, 2),
        skipped_busy=skipped_busy,
        equity_curve=curve,
        closed=closed,
    )


def format_portfolio_summary(r: PortfolioResult) -> str:
    """Backtest dialog log'u için kısa metin özeti."""
    sign = "+" if r.total_pnl >= 0 else ""
    lines = [
        "",
        "═══ PORTFÖY SİMÜLASYONU (canlı kurallar) ═══",
        f"Başlangıç: ${r.initial_equity:.0f}  →  Final: ${r.final_equity:.2f}",
        f"Toplam P&L: {sign}${r.total_pnl:.2f}  ({sign}{r.pnl_pct:.1f}%)",
        f"İşlem: {r.n_trades}  (TP {r.tp} / STOP {r.stop} / ZI {r.zi})",
        f"Win Rate: {r.win_rate:.1f}%   ·   Max Drawdown: {r.max_drawdown_pct:.1f}%",
        f"Parite dolu olduğu için atlanan: {r.skipped_busy}",
    ]
    # En iyi / en kötü 3
    if r.closed:
        by_pnl = sorted(r.closed, key=lambda c: c["pnl"])
        worst = by_pnl[:3]
        best = by_pnl[-3:][::-1]
        lines.append("En iyi:  " + ", ".join(
            f"{c['symbol']} {c['interval']} {c['pnl']:+.0f}$" for c in best))
        lines.append("En kötü: " + ", ".join(
            f"{c['symbol']} {c['interval']} {c['pnl']:+.0f}$" for c in worst))
    return "\n".join(lines)


def format_confluence_sweep(
    trades: list[dict[str, Any]],
    thresholds: tuple[int, ...] = (0, 30, 40, 50, 60, 70),
    **sim_kwargs: Any,
) -> str:
    """Aynı backtest setlerini farklı confluence eşikleriyle simüle edip karşılaştır.

    Tek çalıştırmada hangi confluence eşiğinin en iyi P&L verdiğini gösterir —
    canlı `--paper-min-confluence` için veri-temelli doğrulama.
    """
    lines = [
        "",
        "═══ CONFLUENCE EŞİĞİ TARAMASI (portföy, canlı kurallar) ═══",
        f"{'eşik':>6s} {'işlem':>6s} {'WR':>7s} {'P&L':>11s} {'P&L%':>8s} {'maxDD':>7s}",
    ]
    best = None
    for th in thresholds:
        r = simulate_portfolio(trades, min_confluence=th, **sim_kwargs)
        if r.n_trades == 0:
            lines.append(f">={th:<4d}   (işlem yok)")
            continue
        lines.append(f">={th:<4d} {r.n_trades:6d} {r.win_rate:6.1f}% "
                     f"{r.total_pnl:+10.2f} {r.pnl_pct:+7.1f}% {r.max_drawdown_pct:6.1f}%")
        if best is None or r.total_pnl > best[1]:
            best = (th, r.total_pnl)
    if best:
        lines.append(f"→ En yüksek P&L: confluence >= {best[0]}")
    return "\n".join(lines)


def format_symmetry_sweep(
    trades: list[dict[str, Any]],
    thresholds: tuple[float, ...] = (0.0, 0.3, 0.5, 0.7, 0.9),
    **sim_kwargs: Any,
) -> str:
    """Zaman-simetrisi eşiğini tara (trade'leri 'symmetry' alanına göre süzerek).

    Yapısal filtrenin (AB/CD süre simetrisi) WR/P&L'i gerçekten iyileştirip
    iyileştirmediğini tek backtest'te gösterir.
    """
    lines = [
        "",
        "═══ ZAMAN SİMETRİSİ EŞİĞİ TARAMASI (portföy) ═══",
        f"{'eşik':>6s} {'işlem':>6s} {'WR':>7s} {'P&L':>11s} {'P&L%':>8s} {'maxDD':>7s}",
    ]
    best = None
    for th in thresholds:
        subset = [t for t in trades if t.get("symmetry", 0.0) >= th]
        if not subset:
            lines.append(f">={th:<4.2f}   (işlem yok)")
            continue
        r = simulate_portfolio(subset, **sim_kwargs)
        lines.append(f">={th:<4.2f} {r.n_trades:6d} {r.win_rate:6.1f}% "
                     f"{r.total_pnl:+10.2f} {r.pnl_pct:+7.1f}% {r.max_drawdown_pct:6.1f}%")
        if best is None or r.total_pnl > best[1]:
            best = (th, r.total_pnl)
    if best:
        lines.append(f"→ En yüksek P&L: simetri >= {best[0]:.2f}")
    return "\n".join(lines)


def format_smc_sweep(
    trades: list[dict[str, Any]],
    thresholds: tuple[int, ...] = (0, 30, 40, 60, 70, 100),
    **sim_kwargs: Any,
) -> str:
    """SMC bölge skoru eşiğini tara (trade'leri 'smc' alanına göre süzerek).

    #4-6 yapısal filtrenin (Order Block + FVG + Liquidity Sweep) WR/P&L'i
    gerçekten iyileştirip iyileştirmediğini tek backtest'te gösterir.
    Eşik: 30 = en az bir bölge onayı, 60 = en az iki, 100 = üçü birden.
    """
    lines = [
        "",
        "═══ SMC BÖLGE EŞİĞİ TARAMASI (portföy, canlı kurallar) ═══",
        f"{'eşik':>6s} {'işlem':>6s} {'WR':>7s} {'P&L':>11s} {'P&L%':>8s} {'maxDD':>7s}",
    ]
    best = None
    for th in thresholds:
        subset = [t for t in trades if t.get("smc", 0) >= th]
        if not subset:
            lines.append(f">={th:<4d}   (işlem yok)")
            continue
        r = simulate_portfolio(subset, **sim_kwargs)
        lines.append(f">={th:<4d} {r.n_trades:6d} {r.win_rate:6.1f}% "
                     f"{r.total_pnl:+10.2f} {r.pnl_pct:+7.1f}% {r.max_drawdown_pct:6.1f}%")
        if best is None or r.total_pnl > best[1]:
            best = (th, r.total_pnl)
    if best:
        lines.append(f"→ En yüksek P&L: smc >= {best[0]}")
    return "\n".join(lines)
