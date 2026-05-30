"""Geçmiş paper analizi — "PaMonic (OB@D) filtresi koysaydık WR artar mıydı?"

Salt-okuma. Sonuçlanmış (TP/STOP) paper işlemlerini gezer; her birinde harmonik
D bölgesinde Order Block (PaMonic) var mıydı diye bakar ve şu kıyası basar:
    Tüm işlemler  vs  yalnız PaMonic'li işlemler  →  WR / P&L farkı.

OB tespiti tradermiraz'ın "Gartley D'sinde OrderBlock kullan" konseptidir.
Look-ahead yok: OB yalnız D'nin son `near_bars` barı + birkaç bar penceresinde,
karar anına kadarki mumlarda aranır (geleceğe bakılmaz).

Kullanım:
    python -m terminal.cli.pamonic_gecmis [--db data/terminal.db]
        [--near-bars 15] [--min-disp 0.003]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from terminal.db.store import Store
from terminal.quality.pamonic import find_order_blocks, pamonic_confluence


def _klines_until(conn: sqlite3.Connection, symbol: str, interval: str,
                  d_time: int, lookback_bars: int, interval_ms: int,
                  pad_after: int = 3) -> list[dict]:
    """D bölgesi penceresi: D'den `lookback_bars` öncesi → D + pad_after bar.

    pad_after: OB'nin impulsu D'den 1-2 bar sonra olabilir (D'den dönüş), o yüzden
    karar anı = D + birkaç bar. Geleceğe (sonuç barlarına) bakılmaz.
    """
    start = d_time - lookback_bars * interval_ms
    end = d_time + pad_after * interval_ms
    rows = conn.execute(
        "SELECT open_time, close_time, open, high, low, close, volume, quote_volume "
        "FROM klines WHERE symbol=? AND interval=? AND open_time>=? AND open_time<=? "
        "ORDER BY open_time",
        (symbol, interval, start, end),
    ).fetchall()
    return [
        {"open_time": r[0], "close_time": r[1], "open": r[2], "high": r[3],
         "low": r[4], "close": r[5], "volume": r[6], "quote_volume": r[7]}
        for r in rows
    ]


_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "60m": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
    "1d": 86_400_000, "1W": 604_800_000,
}


def _wr(tp: int, sl: int) -> float:
    d = tp + sl
    return (tp / d * 100) if d else 0.0


def analyze(db_path: str, near_bars: int, min_disp: float,
            lookback: int = 40) -> dict:
    store = Store(path=db_path)
    conn = store._conn
    rows = conn.execute(
        "SELECT setup_id, symbol, interval, pattern, direction, outcome, pnl_usd "
        "FROM paper_trades WHERE closed_at IS NOT NULL AND outcome IN ('TP','STOP') "
        "ORDER BY closed_at"
    ).fetchall()

    # Kovalar: tüm / PaMonic var / PaMonic yok
    buckets = {
        "all":    {"tp": 0, "sl": 0, "pnl": 0.0},
        "pamonic": {"tp": 0, "sl": 0, "pnl": 0.0},
        "no_pamonic": {"tp": 0, "sl": 0, "pnl": 0.0},
    }
    per_pattern: dict[str, dict] = {}
    no_data = 0

    for r in rows:
        sid, symbol, interval, pattern, direction, outcome, pnl = (
            r[0], r[1], r[2], r[3], r[4], r[5], r[6] or 0.0)
        setup = store.load_setup(sid)
        if setup is None:
            no_data += 1
            continue
        ims = _INTERVAL_MS.get(interval, 3_600_000)
        d_idx_time = setup.pivots["D"].time
        kl = _klines_until(conn, symbol, interval, d_idx_time, lookback, ims)
        if len(kl) < 5:
            no_data += 1
            continue
        # D'nin kline penceresindeki indeksi (yoksa son bar)
        d_index = next((i for i, k in enumerate(kl) if k["open_time"] == d_idx_time),
                       len(kl) - 1)
        ob = pamonic_confluence(setup, kl, min_displacement=min_disp,
                                near_bars=near_bars, d_index=d_index)
        has_pm = ob is not None

        is_tp = outcome == "TP"
        for key in ("all", "pamonic" if has_pm else "no_pamonic"):
            buckets[key]["tp" if is_tp else "sl"] += 1
            buckets[key]["pnl"] += pnl

        pp = per_pattern.setdefault(pattern, {"all_tp": 0, "all_sl": 0,
                                              "pm_tp": 0, "pm_sl": 0, "pm_n": 0})
        pp["all_tp" if is_tp else "all_sl"] += 1
        if has_pm:
            pp["pm_n"] += 1
            pp["pm_tp" if is_tp else "pm_sl"] += 1

    store.close()
    return {"buckets": buckets, "per_pattern": per_pattern,
            "total": len(rows), "no_data": no_data}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="terminal-pamonic-gecmis",
        description="Geçmiş paper'da PaMonic (OB@D) filtresi WR'yi artırır mıydı?")
    ap.add_argument("--db", default="data/terminal.db")
    ap.add_argument("--near-bars", type=int, default=15,
                    help="OB, D'nin son bu kadar barı içinde aranır (taze OB)")
    ap.add_argument("--min-disp", type=float, default=0.003,
                    help="OB impuls eşiği (zayıf blokları ele)")
    args = ap.parse_args(argv)

    res = analyze(args.db, args.near_bars, args.min_disp)
    b = res["buckets"]

    print(f"\n📊 PaMonic (OB@D) Geçmiş Analizi — {res['total']} sonuçlanmış işlem "
          f"({res['no_data']} veri yetersiz)\n")
    print(f"{'Strateji':<24}{'İşlem':>7}{'TP':>5}{'SL':>5}{'WR':>8}{'P&L':>11}")
    for key, label in (("all", "Tümü (mevcut)"),
                       ("pamonic", "PaMonic VAR (filtre)"),
                       ("no_pamonic", "PaMonic YOK (elenen)")):
        d = b[key]
        n = d["tp"] + d["sl"]
        print(f"{label:<24}{n:>7}{d['tp']:>5}{d['sl']:>5}"
              f"{_wr(d['tp'], d['sl']):>7.1f}%{d['pnl']:>+10.2f}")

    # Yorum
    all_wr = _wr(b["all"]["tp"], b["all"]["sl"])
    pm_wr = _wr(b["pamonic"]["tp"], b["pamonic"]["sl"])
    pm_n = b["pamonic"]["tp"] + b["pamonic"]["sl"]
    print()
    if pm_n == 0:
        print("⚠️ Hiçbir geçmiş işlemde PaMonic bulunamadı (veri/eşik?).")
    else:
        diff = pm_wr - all_wr
        sign = "ARTIRIRDI ✅" if diff > 0 else "DÜŞÜRÜRDÜ ❌" if diff < 0 else "DEĞİŞTİRMEZDİ"
        print(f"PaMonic filtresi WR'yi {diff:+.1f} puan {sign} "
              f"({all_wr:.1f}% → {pm_wr:.1f}%), ama işlem sayısı {res['total']}→{pm_n} "
              f"(%{pm_n/max(1,res['total'])*100:.0f}'e düşerdi).")

    print(f"\n{'Pattern bazında':<18}{'Tüm WR':>9}{'PaMonic WR':>13}{'PaMonic N':>11}")
    for pat, p in sorted(res["per_pattern"].items(),
                         key=lambda x: -(x[1]["all_tp"] + x[1]["all_sl"])):
        all_n = p["all_tp"] + p["all_sl"]
        pm_n2 = p["pm_tp"] + p["pm_sl"]
        all_wr2 = _wr(p["all_tp"], p["all_sl"])
        pm_wr2 = _wr(p["pm_tp"], p["pm_sl"])
        pm_str = f"{pm_wr2:.0f}%" if pm_n2 else "—"
        print(f"{pat:<18}{all_wr2:>8.0f}%{pm_str:>13}{pm_n2:>8}/{all_n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
