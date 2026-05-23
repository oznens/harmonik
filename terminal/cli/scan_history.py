"""Tek seferlik tarihsel formasyon taraması.

Kullanım:
    python -m terminal.cli.scan_history --symbol BTCUSDT --interval 1h --bars 500
    python -m terminal.cli.scan_history --symbol ETHUSDT --interval 15m --bars 1000 --zigzag 0.012
"""
from __future__ import annotations

import argparse
import logging
import sys

from terminal.cli.run_data import _normalize_interval
from terminal.data.mexc_client import MexcClient
from terminal.db.store import Store
from terminal.detection.scanner import default_threshold, scan_klines
from terminal.timeutil import format_local


def _fmt(ms: int) -> str:
    return format_local(ms)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-scan-history",
        description="terminalMiraz — tarihsel mum dizisinde formasyon taraması",
    )
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--bars", type=int, default=500, help="Çekilecek mum sayısı (max 1000)")
    parser.add_argument("--zigzag", type=float, default=None,
                        help="ZigZag yüzde eşiği (örn. 0.02). Yoksa interval'a göre varsayılan.")
    parser.add_argument("--store", action="store_true", help="Bulunan setup'ları DB'ye yaz")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    symbol = args.symbol.upper().strip()
    interval = _normalize_interval(args.interval)
    bars = max(50, min(args.bars, 1000))
    threshold = args.zigzag if args.zigzag is not None else default_threshold(interval)

    from terminal.quality.htf_ltf import htf_for
    htf_interval = htf_for(interval)
    with MexcClient() as client:
        if not client.ping():
            print("MEXC ping başarısız.", file=sys.stderr)
            return 1
        klines = client.klines(symbol, interval, limit=bars)
        htf_klines = None
        if htf_interval is not None:
            try:
                htf_klines = client.klines(symbol, htf_interval, limit=120)
            except Exception:
                htf_klines = None

    if not klines:
        print(f"{symbol} {interval}: veri yok.", file=sys.stderr)
        return 1

    setups = scan_klines(klines, symbol, interval,
                         zigzag_threshold=threshold,
                         htf_klines=htf_klines)

    first_t = klines[0]["open_time"]
    last_t = klines[-1]["open_time"]
    print()
    print(f"{symbol} {interval} | {len(klines)} mum [{_fmt(first_t)} → {_fmt(last_t)}] "
          f"| ZigZag eşik {threshold:.4f} | {len(setups)} formasyon")
    print("-" * 100)
    for s in setups:
        d_time = s.pivots["D"].time
        print(f"  D@{_fmt(d_time)}  {s.summary()}")
    print()

    if args.store and setups:
        store = Store()
        try:
            for s in setups:
                store.upsert_setup(s)
            print(f"DB'ye yazıldı: {len(setups)} setup, toplam {store.count_setups(symbol, interval)} kayıt.")
        finally:
            store.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
