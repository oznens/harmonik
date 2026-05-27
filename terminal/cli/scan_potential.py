"""Potansiyel (oluşum bitmeden) harmonik pattern tarayıcı.

Kullanım:
    python -m terminal.cli.scan_potential --symbol TAOUSDT --interval 1d
    python -m terminal.cli.scan_potential --combos-file config/tracked_combos.txt
    python -m terminal.cli.scan_potential --symbol BTCUSDT --interval 4h --out /tmp/btc.png

Fiyat henüz D pivot'una gelmemiş ama X-A-B-C oluşmuş yapıları tespit eder.
"D bölgesine girerse formasyon tamamlanır" tipi öngörü için.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from terminal.cli.run_live_multi import _load_combos_file
from terminal.data.mexc_client import MexcClient, MexcError
from terminal.detection.pivots import find_pivots
from terminal.detection.potential import find_potential_patterns
from terminal.detection.scanner import default_threshold
from terminal.telegram_bot.charts import render_potential_chart


def scan_one(client: MexcClient, symbol: str, interval: str,
             bars: int = 500, out_dir: Path | None = None,
             threshold: float | None = None) -> bool:
    """Tek parite-TF için potansiyel pattern bul ve raporla."""
    try:
        klines = client.klines_paginated(symbol, interval, bars)
    except MexcError as e:
        print(f"  HATA {symbol} {interval}: {e}")
        return False
    if len(klines) < 50:
        return False
    thr = threshold if threshold is not None else default_threshold(interval)
    pivots = find_pivots(klines, thr)
    if len(pivots) < 4:
        return False
    matches = find_potential_patterns(pivots[-4:])
    if not matches:
        return False
    m = matches[0]
    arrow = "↑" if m.direction == "bull" else "↓"
    print(f"  ✓ {symbol:10s} {interval:4s}: {m.spec.name} {arrow} "
          f"D bölgesi={m.d_zone_low:.6g}-{m.d_zone_high:.6g} "
          f"(ideal {m.d_ideal_price:.6g})  B={m.b_ratio:.3f} C={m.c_ratio:.3f}")
    if out_dir is not None:
        png = render_potential_chart(symbol, interval, klines, zigzag_threshold=thr)
        if png:
            out_dir.mkdir(parents=True, exist_ok=True)
            fname = out_dir / f"{symbol}_{interval}_potential.png"
            fname.write_bytes(png)
            print(f"     -> {fname}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="terminal-scan-potential",
        description="Oluşum tamamlanmamış (potansiyel) harmonik pattern tarayıcı.",
    )
    parser.add_argument("--symbol", help="Tek parite tarama (örn. TAOUSDT)")
    parser.add_argument("--interval", help="Tek TF (15m/30m/60m/4h/1d)")
    parser.add_argument("--combos-file",
                        help="Çoklu tarama dosyası (config/tracked_combos.txt)")
    parser.add_argument("--bars", type=int, default=500,
                        help="Çekilecek mum sayısı (varsayılan 500)")
    parser.add_argument("--zigzag", type=float, default=None,
                        help="ZigZag eşik yüzdesi (yoksa TF default)")
    parser.add_argument("--out-dir", default="potential_charts",
                        help="Chart PNG çıktı klasörü (varsayılan: potential_charts/)")
    args = parser.parse_args(argv)

    client = MexcClient()
    out_dir = Path(args.out_dir) if args.out_dir else None

    if args.symbol and args.interval:
        combos = [(args.symbol.upper(), args.interval)]
    elif args.combos_file:
        combos = _load_combos_file(Path(args.combos_file))
    else:
        parser.error("--symbol+--interval VEYA --combos-file gerekli")
        return 2

    print(f"Tarama: {len(combos)} kombinasyon, {args.bars} bar/parite")
    print(f"Çıktı: {out_dir}/\n")
    found = 0
    for sym, iv in combos:
        if scan_one(client, sym, iv, bars=args.bars,
                    out_dir=out_dir, threshold=args.zigzag):
            found += 1
    print(f"\n{found} potansiyel pattern bulundu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
