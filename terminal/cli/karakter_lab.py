"""Parite Karakter Tanıma Laboratuvarı — toplu backtest.

Her (parite × TF) için N mum çekip tüm tarihsel formasyonları simüle eder.
Sonuçlar karakter_samples + karakter_scores tablolarına yazılır.

Kullanım:
    python -m terminal.cli.karakter_lab \\
        --symbols BTCUSDT,ETHUSDT,AVAXUSDT \\
        --intervals 15m,30m,60m,4h \\
        --bars 20000
"""
from __future__ import annotations

import argparse
import logging
import sys

from terminal.cli.run_data import _normalize_interval
from terminal.data.mexc_client import MexcClient
from terminal.db.store import Store
from terminal.karakter.runner import run_lab

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-karakter-lab",
        description="terminalMiraz — Faz 5 (Parite Karakter Tanıma Laboratuvarı)",
    )
    parser.add_argument("--symbols", required=True,
                        help="Virgülle ayrılmış pariteler (örn. BTCUSDT,ETHUSDT)")
    parser.add_argument("--intervals", required=True,
                        help="Virgülle ayrılmış aralıklar (örn. 15m,30m,60m,4h)")
    parser.add_argument("--bars", type=int, default=20000,
                        help="Her parite × TF için çekilecek mum (varsayılan 20.000)")
    parser.add_argument("--zigzag", type=float, default=None,
                        help="Özel ZigZag eşiği; yoksa TF varsayılanı")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    intervals = [_normalize_interval(i) for i in args.intervals.split(",") if i.strip()]

    if not symbols or not intervals:
        print("HATA: --symbols ve --intervals boş olamaz.", file=sys.stderr)
        return 1

    print(f"\nKarakter Lab başlıyor — {len(symbols)} parite × {len(intervals)} TF "
          f"× {args.bars} mum  = {len(symbols) * len(intervals)} kombinasyon\n")

    def progress(msg: str) -> None:
        print(f"  {msg}", flush=True)

    client = MexcClient()
    store = Store()
    try:
        if not client.ping():
            print("MEXC ping başarısız.", file=sys.stderr)
            return 1
        run_id = run_lab(symbols, intervals, args.bars, store, client,
                        zigzag_threshold=args.zigzag, progress=progress)

        # Genel istatistik
        print()
        print("=" * 80)
        print("GENEL İSTATİSTİK")
        print("=" * 80)
        total = store._conn.execute("SELECT COUNT(*) FROM karakter_samples WHERE run_id = ?", (run_id,)).fetchone()[0]
        cur = store._conn.execute(
            "SELECT outcome, COUNT(*) FROM karakter_samples WHERE run_id = ? GROUP BY outcome ORDER BY 2 DESC",
            (run_id,),
        )
        outcomes = {r[0]: r[1] for r in cur.fetchall()}
        tp = outcomes.get("TP", 0)
        sl = outcomes.get("STOP", 0)
        wr = (tp / (tp + sl) * 100) if (tp + sl) > 0 else 0

        # R hesabı: bu koşumun toplam R kazancı
        from terminal.karakter.score import trade_r
        cur = store._conn.execute(
            "SELECT entry, stop, tp1, outcome FROM karakter_samples WHERE run_id = ?",
            (run_id,),
        )
        r_values = [trade_r(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]
        total_r = sum(r_values)
        decided_r = [r for r in r_values if r != 0.0]
        avg_r = (sum(decided_r) / len(decided_r)) if decided_r else 0.0
        avg_r_tp_only = (
            sum(r for r in decided_r if r > 0) / sum(1 for r in decided_r if r > 0)
        ) if any(r > 0 for r in decided_r) else 0.0

        print(f"  Toplam örneklem: {total}")
        for o, n in outcomes.items():
            pct = n / total * 100 if total else 0
            print(f"    {o:<5}: {n:>4}  ({pct:>5.1f}%)")
        print(f"  Win Rate: {wr:.1f}%  ({tp} TP / {tp+sl} kararlı)")
        print(f"  Toplam R: {total_r:+.2f}R   (kararlı işlem başı ort: {avg_r:+.2f}R)")
        print(f"  TP'lerin ort R: +{avg_r_tp_only:.2f}R   (1R = SL mesafesi kadar kazanç)")
        print()
        print("=" * 80)
        print("EN YÜKSEK KARAKTER SKORLARI (örneklem ≥ 2)")
        print("=" * 80)
        cur = store._conn.execute(
            """SELECT symbol, interval, pattern_name, direction,
                      sample_count, tp_count, stop_count, eo_count, zi_count,
                      win_rate, karakter_score
               FROM karakter_scores
               WHERE direction != 'all' AND sample_count >= 2
               ORDER BY karakter_score DESC, sample_count DESC LIMIT 15"""
        )
        rows = cur.fetchall()
        if not rows:
            print("  (örneklem yok)")
        else:
            print(f"  {'PARITE':<10} {'TF':<5} {'PATTERN':<14} {'YON':<5} {'N':<4} "
                  f"{'TP':<3} {'SL':<3} {'EO':<3} {'ZI':<3} {'WR':<6} {'KARAKTER':<8}")
            print("  " + "-" * 76)
            for r in rows:
                print(f"  {r[0]:<10} {r[1]:<5} {r[2]:<14} {r[3]:<5} {r[4]:<4} "
                      f"{r[5]:<3} {r[6]:<3} {r[7]:<3} {r[8]:<3} "
                      f"{r[9]*100:>5.1f}% {r[10]:>7.2f}")
        print()
        return 0
    finally:
        client.close()
        store.close()


if __name__ == "__main__":
    sys.exit(main())
