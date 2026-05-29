"""Tarihsel kline indir → DB (klines tablosu). Backtest bundan çalışır.

Bir kez indir, sonra Backtest sekmesi offline + hızlı + rate-limit'siz çalışır.
VPS'te indirip DB'yi lokale sync edebilirsin (lokalde MEXC erişimi gerekmez).

Kullanım:
    python -m terminal.cli.download_history \
        --symbols BTCUSDT,ETHUSDT,SOLUSDT --intervals 15m,30m,60m,4h,1d --days 730
    python -m terminal.cli.download_history --symbols BTCUSDT --intervals 4h --days 730 --spot
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from terminal.cli.run_data import _normalize_interval
from terminal.data.mexc_client import MexcClient, MexcError
from terminal.data.mexc_futures import MexcFuturesClient, MexcFuturesError
from terminal.db.store import Store

log = logging.getLogger(__name__)

_BARS_PER_DAY = {"15m": 96, "30m": 48, "60m": 24, "4h": 6, "1d": 1}
_FETCH_ERRORS = (MexcError, MexcFuturesError)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="terminal-download-history",
        description="Tarihsel kline indir → DB (backtest verisi)")
    ap.add_argument("--symbols", required=True, help="Virgüllü pariteler")
    ap.add_argument("--intervals", required=True, help="Virgüllü aralıklar")
    ap.add_argument("--days", type=int, default=730, help="Geriye kaç gün (varsayılan 730=2yıl)")
    ap.add_argument("--spot", action="store_true", help="Spot (varsayılan: futures)")
    ap.add_argument("--log-level", default="WARNING")
    args = ap.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s [%(levelname)s] %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    intervals = [_normalize_interval(i) for i in args.intervals.split(",") if i.strip()]
    client = MexcClient() if args.spot else MexcFuturesClient()
    store = Store()

    total_combos = len(symbols) * len(intervals)
    print(f"İndiriliyor: {len(symbols)} parite × {len(intervals)} TF "
          f"× {args.days} gün = {total_combos} kombinasyon\n")
    ok = 0
    try:
        for sym in symbols:
            for iv in intervals:
                bars = args.days * _BARS_PER_DAY.get(iv, 24)
                klines = None
                for attempt in range(1, 6):
                    try:
                        klines = client.klines_paginated(sym, iv, bars, throttle=0.08)
                        break
                    except _FETCH_ERRORS as e:
                        wait = min(30, 2 ** attempt)
                        print(f"  {sym} {iv}: deneme {attempt} hata ({e}) — {wait}s bekle")
                        time.sleep(wait)
                if not klines:
                    print(f"  {sym} {iv}: ATLANDI (veri yok)")
                    continue
                store.upsert_klines(sym, iv, klines)
                ok += 1
                print(f"  ✓ {sym} {iv}: {len(klines)} mum kaydedildi "
                      f"({klines[0]['open_time']} → {klines[-1]['open_time']})")
    finally:
        try:
            client.close()
        except Exception:
            pass
        store.close()

    print(f"\nBitti: {ok}/{total_combos} kombinasyon indirildi. "
          "Backtest sekmesi artık DB'den çalışır.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
