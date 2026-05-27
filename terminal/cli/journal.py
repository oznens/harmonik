"""Trading journal — paper trade sonuçlarının dönemsel analizi.

Kullanım:
    python -m terminal.cli.journal --period week     # son 7 gün
    python -m terminal.cli.journal --period month    # son 30 gün
    python -m terminal.cli.journal --period all      # tüm zamanlar
    python -m terminal.cli.journal --period week --send-telegram

Çıktı:
- Toplam P&L, WR, equity değişim
- TF bazlı kırılım (15m vs 1d vs ...)
- Pattern bazlı kırılım (en karlı ve zararlı)
- Parite bazlı kırılım
- En kötü 5 / en iyi 5 trade
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from terminal.db.store import Store


TZ = timezone(timedelta(hours=3))


def _fmt_ts(ms: int | None) -> str:
    if ms is None:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%m-%d %H:%M")


def _stats(rows: list) -> dict:
    """rows = list of (outcome, pnl_usd, position_usd, leverage)"""
    n = len(rows)
    tp = sum(1 for r in rows if r[0] == "TP")
    stp = sum(1 for r in rows if r[0] == "STOP")
    eo = sum(1 for r in rows if r[0] in ("EO", "ZI"))
    decided = tp + stp
    wr = (tp / decided * 100) if decided else 0
    pnl = sum(r[1] or 0 for r in rows)
    avg_lev = (sum(r[3] or 1 for r in rows) / n) if n else 0
    return {
        "n": n, "tp": tp, "stop": stp, "eo": eo,
        "wr": wr, "pnl": pnl, "avg_lev": avg_lev,
    }


def _bucket_report(label: str, buckets: dict[str, list]) -> str:
    """Bucket bazlı tablo (TF/Pattern/Parite)."""
    lines = [f"\n=== {label} ===",
             f"{'Bucket':16s} {'N':>4s}  {'TP':>3s}  {'STP':>3s}  {'WR':>5s}  {'P&L($)':>9s}"]
    rows = sorted(buckets.items(), key=lambda kv: -_stats(kv[1])["pnl"])
    for name, items in rows:
        s = _stats(items)
        sign = "+" if s["pnl"] >= 0 else ""
        lines.append(f"{name[:16]:16s} {s['n']:4d}  {s['tp']:3d}  {s['stop']:3d}  "
                     f"{s['wr']:4.1f}% {sign}{s['pnl']:7.2f}")
    return "\n".join(lines)


def journal(store: Store, period: str = "week") -> str:
    """Dönem için journal raporu döner (string)."""
    now_ms = int(time.time() * 1000)
    period_ms = {
        "day":   24 * 3600 * 1000,
        "week":  7 * 24 * 3600 * 1000,
        "month": 30 * 24 * 3600 * 1000,
        "all":   None,
    }.get(period)
    if period == "all":
        where = ""
        params: tuple = ()
    else:
        where = "WHERE pt.closed_at >= ?"
        params = (now_ms - period_ms,)

    cur = store._conn.execute(f"""
        SELECT pt.symbol, pt.interval, pt.pattern, pt.direction,
               pt.entry_price, pt.exit_price, pt.outcome, pt.pnl_usd,
               pt.position_usd, pt.leverage, pt.opened_at, pt.closed_at
        FROM paper_trades pt
        {where}
        ORDER BY pt.closed_at DESC
    """, params)
    trades = cur.fetchall()

    # Açık (closed_at IS NULL) trade'ler dahil değil
    closed = [t for t in trades if t[6] is not None]
    if not closed:
        return f"📊 Son {period} — kapalı trade yok henüz."

    # Account snapshot
    acc = store._conn.execute(
        "SELECT initial_equity, current_equity, total_trades, tp_count, stop_count, total_pnl "
        "FROM paper_account WHERE id = 1"
    ).fetchone()
    initial, current, total, tp, stop, total_pnl = acc or (1000.0, 1000.0, 0, 0, 0, 0)

    # Genel
    g_stats = _stats([(t[6], t[7], t[8], t[9]) for t in closed])

    # TF bazlı
    by_tf: dict[str, list] = defaultdict(list)
    for t in closed:
        by_tf[t[1]].append((t[6], t[7], t[8], t[9]))

    # Pattern bazlı
    by_pat: dict[str, list] = defaultdict(list)
    for t in closed:
        by_pat[t[2]].append((t[6], t[7], t[8], t[9]))

    # Parite bazlı
    by_sym: dict[str, list] = defaultdict(list)
    for t in closed:
        by_sym[t[0]].append((t[6], t[7], t[8], t[9]))

    # En iyi/en kötü 5 trade
    closed_by_pnl = sorted(closed, key=lambda t: -(t[7] or 0))
    best5 = closed_by_pnl[:5]
    worst5 = closed_by_pnl[-5:][::-1]

    period_label = {"day": "GÜN", "week": "HAFTA", "month": "AY", "all": "TÜM ZAMAN"}[period]
    lines = [
        f"📊 *TRADING JOURNAL — Son {period_label}*",
        "",
        f"*Equity*: ${initial:.0f} → ${current:.2f} ({(current-initial)/initial*100:+.1f}%)",
        f"*Toplam P&L (tüm zamanlar)*: ${total_pnl:+.2f}",
        "",
        f"_Dönem özeti ({g_stats['n']} kapalı trade):_",
        f"  TP: {g_stats['tp']}  ·  STOP: {g_stats['stop']}  ·  EO/ZI: {g_stats['eo']}",
        f"  WR: {g_stats['wr']:.1f}%  ·  P&L: ${g_stats['pnl']:+.2f}",
        f"  Ortalama leverage: {g_stats['avg_lev']:.1f}x",
    ]
    lines.append(_bucket_report("⏱️ TF BAZLI", by_tf))
    lines.append(_bucket_report("🎯 PATTERN BAZLI", by_pat))
    lines.append(_bucket_report("💰 PARİTE BAZLI", by_sym))

    lines.append("\n=== 🏆 EN İYİ 5 TRADE ===")
    for t in best5:
        if t[7] is None or t[7] <= 0:
            break
        lines.append(f"  +${t[7]:>6.2f}  {t[0]:9s} {t[1]:4s} {t[2]:14s} {t[3]:5s} {_fmt_ts(t[11])}")

    lines.append("\n=== 💀 EN KÖTÜ 5 TRADE ===")
    for t in worst5:
        if t[7] is None or t[7] >= 0:
            break
        lines.append(f"  ${t[7]:>7.2f}  {t[0]:9s} {t[1]:4s} {t[2]:14s} {t[3]:5s} {_fmt_ts(t[11])}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-journal",
        description="Paper trade dönemsel rapor (terminal + opsiyonel Telegram).",
    )
    parser.add_argument("--period", choices=["day", "week", "month", "all"],
                        default="week", help="Rapor dönemi")
    parser.add_argument("--send-telegram", action="store_true",
                        help=".env'deki bot ile Telegram'a yolla")
    args = parser.parse_args(argv)

    store = Store()
    report = journal(store, period=args.period)
    print(report)

    if args.send_telegram:
        from terminal.telegram_bot.client import TelegramClient, TelegramError
        try:
            tg = TelegramClient()
            tg.send_message(report, parse_mode="Markdown")
            print("\n✓ Telegram'a yollandı.")
        except TelegramError as e:
            print(f"\n⚠ Telegram hatası: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
