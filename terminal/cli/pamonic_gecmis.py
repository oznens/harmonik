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
from terminal.karakter.simulator import simulate_outcome
from terminal.quality.htf_ltf import htf_for
from terminal.quality.pamonic import find_order_blocks, pamonic_confluence

# 15m harmonik için "alt TF" (LTF) eşlemesi — OB'yi daha ince çözünürlükte ara.
_LTF_MAPPING = {
    "5m": "1m", "15m": "5m", "30m": "15m", "60m": "15m",
    "2h": "30m", "4h": "60m", "8h": "2h", "1d": "4h",
}


def _ob_interval(setup_interval: str, ob_tf: str) -> str:
    """OB'nin aranacağı zaman dilimi. same=setup TF, ltf=alt TF, htf=üst TF."""
    if ob_tf == "ltf":
        return _LTF_MAPPING.get(setup_interval, setup_interval)
    if ob_tf == "htf":
        return htf_for(setup_interval) or setup_interval
    return setup_interval


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


def _has_pamonic(conn, setup, near_bars, min_disp, lookback, ob_tf):
    """Setup'ın PRZ'sinde, `ob_tf` (same/ltf/htf) TF mumlarından OB var mı?

    OB farklı TF'de aransa bile PRZ (fiyat bölgesi) aynıdır — sadece OB'leri
    üreten mum çözünürlüğü değişir. Look-ahead: pencere D + birkaç bar.
    Returns: (ob_or_None, ob_interval, data_ok)
    """
    ob_iv = _ob_interval(setup.interval, ob_tf)
    ims = _INTERVAL_MS.get(ob_iv, 3_600_000)
    d_time = setup.pivots["D"].time
    # OB TF küçükse aynı zaman aralığını kapsamak için lookback'i ölçekle
    setup_ims = _INTERVAL_MS.get(setup.interval, 3_600_000)
    scaled_lookback = max(lookback, int(lookback * setup_ims / ims))
    kl = _klines_until(conn, setup.symbol, ob_iv, d_time, scaled_lookback, ims)
    if len(kl) < 5:
        return None, ob_iv, False
    d_index = next((i for i, k in enumerate(kl) if k["open_time"] <= d_time
                    and (i + 1 >= len(kl) or kl[i + 1]["open_time"] > d_time)),
                   len(kl) - 1)
    ob = pamonic_confluence(setup, kl, min_displacement=min_disp,
                            near_bars=near_bars, d_index=d_index)
    return ob, ob_iv, True


def _ob_stop(setup, ob, buffer_pct: float = 0.001) -> float:
    """OB'nin arkasına dar stop. bull → OB.bottom altı, bear → OB.top üstü.

    buffer_pct: blok kenarına küçük tampon (iğne payı). tradermiraz mantığı:
    'stop'u OB'nin hemen arkasına koy → mesafe daralır, R:R yükselir.'
    """
    if setup.direction == "bull":
        return ob.bottom * (1 - buffer_pct)
    return ob.top * (1 + buffer_pct)


def _resim_outcome(conn, setup, ob, buffer_pct: float = 0.001):
    """OB-tabanlı DAR stop ile setup'ı yeniden simüle et (counterfactual).

    Stop'u OB arkasına çeker, tp1'i AYNI tutar (R:R bu yüzden yükselir), sonra
    simulate_outcome (limit giriş, canlı motor) ile gerçek mumlarda TP/STOP'u
    yeniden hesaplar — dar stop bazı TP'leri STOP'a çevirebilir, bu DÜRÜST ölçüm.

    Returns: (outcome, r_multiple) — r = realized R (dar stop'a göre).
    """
    new_stop = _ob_stop(setup, ob, buffer_pct)
    risk = abs(setup.entry - new_stop)
    if risk <= 0:
        return None, 0.0
    # Geleceğe ait mumlar (D sonrası) — yeniden simülasyon için
    d_time = setup.pivots["D"].time
    ims = _INTERVAL_MS.get(setup.interval, 3_600_000)
    future = _klines_until(conn, setup.symbol, setup.interval, d_time,
                           lookback_bars=0, interval_ms=ims, pad_after=300)
    future = [k for k in future if k["open_time"] >= d_time]
    if len(future) < 3:
        return None, 0.0
    # setup kopyası: stop = OB arkası (tp1/entry aynı)
    import copy
    s2 = copy.copy(setup)
    s2.stop = new_stop
    out = simulate_outcome(s2, future, entry_mode="limit")
    rr = abs(setup.tp1 - setup.entry) / risk
    if out.outcome == "TP":
        return "TP", rr
    if out.outcome == "STOP":
        return "STOP", -1.0
    return out.outcome, 0.0


def analyze(db_path: str, near_bars: int, min_disp: float,
            ob_tf: str = "same", lookback: int = 40,
            resimule: bool = False) -> dict:
    store = Store(path=db_path)
    conn = store._conn
    rows = conn.execute(
        "SELECT setup_id, symbol, interval, pattern, direction, outcome, pnl_usd "
        "FROM paper_trades WHERE closed_at IS NOT NULL AND outcome IN ('TP','STOP') "
        "ORDER BY closed_at"
    ).fetchall()

    buckets = {
        "all":    {"tp": 0, "sl": 0, "pnl": 0.0},
        "pamonic": {"tp": 0, "sl": 0, "pnl": 0.0},
        "no_pamonic": {"tp": 0, "sl": 0, "pnl": 0.0},
    }
    per_pattern: dict[str, dict] = {}
    no_data = 0
    # OB-stop yeniden simülasyonu (counterfactual): dar stop ile R toplamı
    resim = {"tp": 0, "sl": 0, "other": 0, "total_r": 0.0, "rr_sum": 0.0, "n": 0}

    for r in rows:
        sid, symbol, interval, pattern, direction, outcome, pnl = (
            r[0], r[1], r[2], r[3], r[4], r[5], r[6] or 0.0)
        setup = store.load_setup(sid)
        if setup is None:
            no_data += 1
            continue
        ob, _ob_iv, ok = _has_pamonic(conn, setup, near_bars, min_disp,
                                      lookback, ob_tf)
        if not ok:
            no_data += 1
            continue
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
            # OB varsa: dar stop ile yeniden simüle et (R:R sıçraması ölçümü)
            if resimule:
                ro, rr = _resim_outcome(conn, setup, ob)
                if ro is not None:
                    resim["n"] += 1
                    resim["rr_sum"] += rr
                    if ro == "TP":
                        resim["tp"] += 1
                        resim["total_r"] += rr
                    elif ro == "STOP":
                        resim["sl"] += 1
                        resim["total_r"] -= 1.0
                    else:
                        resim["other"] += 1

    store.close()
    return {"buckets": buckets, "per_pattern": per_pattern,
            "total": len(rows), "no_data": no_data, "ob_tf": ob_tf,
            "resim": resim}


_OB_TF_LABEL = {"same": "Aynı TF", "ltf": "Alt TF (LTF)", "htf": "Üst TF (HTF)"}


def _print_one(res: dict, ob_tf: str, show_pattern: bool = True) -> None:
    b = res["buckets"]
    all_wr = _wr(b["all"]["tp"], b["all"]["sl"])
    pm_wr = _wr(b["pamonic"]["tp"], b["pamonic"]["sl"])
    pm_n = b["pamonic"]["tp"] + b["pamonic"]["sl"]
    print(f"{'Strateji':<24}{'İşlem':>7}{'TP':>5}{'SL':>5}{'WR':>8}{'P&L':>11}")
    for key, label in (("all", "Tümü (mevcut)"),
                       ("pamonic", "PaMonic VAR (filtre)"),
                       ("no_pamonic", "PaMonic YOK (elenen)")):
        d = b[key]
        n = d["tp"] + d["sl"]
        print(f"{label:<24}{n:>7}{d['tp']:>5}{d['sl']:>5}"
              f"{_wr(d['tp'], d['sl']):>7.1f}%{d['pnl']:>+10.2f}")
    if pm_n == 0:
        print("⚠️ Hiçbir işlemde PaMonic bulunamadı (veri/eşik?).")
    else:
        diff = pm_wr - all_wr
        sign = "↑" if diff > 0 else "↓" if diff < 0 else "="
        print(f"→ PaMonic WR {diff:+.1f} puan {sign} ({all_wr:.1f}%→{pm_wr:.1f}%), "
              f"işlem {res['total']}→{pm_n} (%{pm_n/max(1,res['total'])*100:.0f}).")
    if show_pattern:
        print(f"\n{'Pattern':<18}{'Tüm WR':>9}{'PaMonic WR':>13}{'PaMonic N':>11}")
        for pat, p in sorted(res["per_pattern"].items(),
                             key=lambda x: -(x[1]["all_tp"] + x[1]["all_sl"])):
            all_n = p["all_tp"] + p["all_sl"]
            pm_n2 = p["pm_tp"] + p["pm_sl"]
            pm_str = f"{_wr(p['pm_tp'], p['pm_sl']):.0f}%" if pm_n2 else "—"
            print(f"{pat:<18}{_wr(p['all_tp'], p['all_sl']):>8.0f}%{pm_str:>13}"
                  f"{pm_n2:>8}/{all_n}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="terminal-pamonic-gecmis",
        description="Geçmiş paper'da PaMonic (OB@D) filtresi WR'yi artırır mıydı?")
    ap.add_argument("--db", default="data/terminal.db")
    ap.add_argument("--near-bars", type=int, default=15,
                    help="OB, D'nin son bu kadar barı içinde aranır (taze OB)")
    ap.add_argument("--min-disp", type=float, default=0.003,
                    help="OB impuls eşiği (zayıf blokları ele)")
    ap.add_argument("--ob-tf", choices=["same", "ltf", "htf"], default="same",
                    help="OB hangi TF'de aransın: same=harmonik TF, ltf=alt TF, htf=üst TF")
    ap.add_argument("--compare", action="store_true",
                    help="same/ltf/htf üçünü birden çalıştır, WR'leri kıyasla")
    ap.add_argument("--resim", action="store_true",
                    help="OB-tabanlı DAR stop ile yeniden simüle et — R:R sıçramasını "
                         "ölç (stop OB arkasına, tp1 aynı; dar stop bazı TP'leri "
                         "STOP'a çevirebilir → dürüst net R)")
    args = ap.parse_args(argv)

    if args.compare:
        print("\n📊 PaMonic OB-TF Karşılaştırması — 15m harmonik için OB hangi "
              "TF'de en iyi?\n")
        summary = []
        for tf in ("same", "ltf", "htf"):
            res = analyze(args.db, args.near_bars, args.min_disp, ob_tf=tf)
            print(f"━━━ {_OB_TF_LABEL[tf]} ({tf}) ━━━")
            _print_one(res, tf, show_pattern=False)
            b = res["buckets"]
            pm_n = b["pamonic"]["tp"] + b["pamonic"]["sl"]
            summary.append((tf, _wr(b["all"]["tp"], b["all"]["sl"]),
                            _wr(b["pamonic"]["tp"], b["pamonic"]["sl"]),
                            pm_n, b["pamonic"]["pnl"]))
            print()
        print("═" * 56)
        print(f"{'OB-TF':<14}{'Baz WR':>9}{'PaMonic WR':>13}{'N':>6}{'PaMonic P&L':>14}")
        for tf, awr, pwr, n, pnl in summary:
            print(f"{_OB_TF_LABEL[tf]:<14}{awr:>8.1f}%{pwr:>12.1f}%{n:>6}{pnl:>+13.2f}")
        best = max(summary, key=lambda x: (x[2], x[4]))   # en iyi PaMonic WR, sonra P&L
        print(f"\n🏆 En iyi: {_OB_TF_LABEL[best[0]]} — PaMonic WR {best[2]:.1f}%, "
              f"{best[3]} işlem, P&L {best[4]:+.2f}")
        return 0

    res = analyze(args.db, args.near_bars, args.min_disp, ob_tf=args.ob_tf,
                  resimule=args.resim)
    print(f"\n📊 PaMonic (OB@D, {_OB_TF_LABEL[args.ob_tf]}) Geçmiş Analizi — "
          f"{res['total']} sonuçlanmış işlem ({res['no_data']} veri yetersiz)\n")
    _print_one(res, args.ob_tf)

    if args.resim:
        rs = res["resim"]
        n = rs["n"]
        print(f"\n🎯 OB-tabanlı DAR STOP yeniden simülasyonu ({n} PaMonic işlemi):")
        if n == 0:
            print("  (yeniden simüle edilebilir PaMonic işlemi yok)")
        else:
            dec = rs["tp"] + rs["sl"]
            wr = (rs["tp"] / dec * 100) if dec else 0.0
            avg_rr = rs["rr_sum"] / n
            other_str = f", {rs['other']} diğer" if rs["other"] else ""
            print(f"  Ort. R:R (dar stop) : {avg_rr:.2f}   (geniş stop ~1.00 idi)")
            print(f"  Yeniden WR          : {wr:.1f}%  "
                  f"({rs['tp']} TP / {rs['sl']} STOP{other_str})")
            print(f"  Toplam R (net)      : {rs['total_r']:+.2f}R")
            print(f"  → Dar stop, TP'leri {rs['sl']} kez STOP'a çevirdi ama her TP "
                  f"~{avg_rr:.1f}R kazandırdı. Net R yukarıdaki.")
            print("  NOT: Bu R:R'nin OB ile NE KADAR yükseldiğini gösterir "
                  "(tradermiraz'ın asıl iddiası). WR yerine NET R'ye bak.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
