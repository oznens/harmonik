"""Miraz Konsept Ölçümü — fraktal teyit / PaMonic / 2-618'i gerçek veride sınar.

Canlı sisteme ve Karakter skoruna DOKUNMAZ; ayrı, salt-okuma bir ölçümdür.
Soru: "harmonik + fraktal teyit" ve "harmonik + PaMonic" WR'yi yükseltiyor mu;
2-618 tek başına nasıl? — sayıyla görmek.

Kullanım (localde, MEXC erişimi olan yerde):
    python -m terminal.cli.miraz_olcum --symbols BTCUSDT,ETHUSDT \\
        --intervals 15m,60m --bars 5000
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from terminal.cli.run_data import _normalize_interval
from terminal.data.mexc_client import MexcClient
from terminal.data.mexc_futures import MexcFuturesClient
from terminal.detection.pivots import find_pivots
from terminal.detection.scanner import default_threshold, scan_klines
from terminal.detection.two_618 import find_two_618
from terminal.karakter.runner import _fetch_retry, _find_d_index
from terminal.karakter.score import trade_r
from terminal.karakter.simulator import simulate_outcome
from terminal.quality.fraktal import simulate_fraktal_entry
from terminal.quality.miraz_measure import (
    Bucket, HarmonicRecord, format_buckets, harmonic_buckets, simulate_two_618,
)
from terminal.quality.pamonic import pamonic_confluence

# PaMonic sıkılaştırma: OB D'nin son N barında + min impuls.
PAMONIC_NEAR_BARS = 15
PAMONIC_MIN_DISP = 0.003

log = logging.getLogger(__name__)


def _confirm_index(klines: list[dict[str, Any]], d_idx: int, direction: str,
                   d_price: float, thr: float) -> int | None:
    """run_lab look-ahead düzeltmesi: D fraktalının doğrulandığı ilk bar."""
    bull = direction == "bull"
    confirm_price = d_price * (1 + thr) if bull else d_price * (1 - thr)
    for j in range(d_idx + 1, len(klines)):
        if bull and klines[j]["high"] >= confirm_price:
            return j
        if not bull and klines[j]["low"] <= confirm_price:
            return j
    return None


def measure(client, symbols, intervals, bars, threshold=None, progress=None):
    harmonic: list[HarmonicRecord] = []
    bucket_2618 = Bucket("2-618 (tek başına)")

    for symbol in symbols:
        for interval in intervals:
            tag = f"{symbol} {interval}"
            if progress:
                progress(f"{tag} — veri çekiliyor...")
            klines = _fetch_retry(
                lambda: client.klines_paginated(symbol, interval, bars), tag)
            if not klines or len(klines) < 100:
                if progress:
                    progress(f"{tag} — ATLANDI (veri yok/yetersiz)")
                continue

            thr = threshold if threshold is not None else default_threshold(interval)
            pivots = find_pivots(klines, thr)

            # --- Harmonikler: baz + fraktal + PaMonic (rr1 = canlıyla tutarlı) ---
            setups = scan_klines(klines, symbol, interval, zigzag_threshold=thr,
                                 target_mode="rr1")
            for s in setups:
                d_idx = _find_d_index(klines, s.pivots["D"].time)
                if d_idx is None:
                    continue
                ci = _confirm_index(klines, d_idx, s.direction, s.pivots["D"].price, thr)
                if ci is None or ci + 1 >= len(klines):
                    continue
                future = klines[ci + 1:]
                # Baz: LİMİT giriş (entry fiyatından)
                lim = simulate_outcome(s, future, entry_mode="limit")
                lim_r = trade_r(s.entry, s.stop, s.tp1, lim.outcome, actual_entry=s.entry)
                # FRAKTAL teyitli gecikmeli giriş + yapısal stop
                fr_out, fr_entry, fr_stop = simulate_fraktal_entry(future, s.direction, s.tp1)
                fr_r = trade_r(fr_entry or s.entry, fr_stop or s.stop, s.tp1,
                               fr_out, actual_entry=fr_entry)
                # PaMonic (sıkı): karar anına kadarki veride D'ye yakın taze OB
                hist = klines[:ci + 1]
                pm = pamonic_confluence(s, hist, min_displacement=PAMONIC_MIN_DISP,
                                        near_bars=PAMONIC_NEAR_BARS, d_index=d_idx) is not None
                harmonic.append(HarmonicRecord(lim.outcome, lim_r, fr_out, fr_r, pm))

            # --- 2-618 (tek başına) ---
            for pat in find_two_618(pivots):
                d = pat.points[3]                      # 5. nokta (lokal uç)
                if d.index + 1 >= len(klines):
                    continue
                future = klines[d.index + 1:]
                out = simulate_two_618(pat, future)
                r = trade_r(pat.entry, pat.stop, pat.tp1, out, actual_entry=pat.entry)
                bucket_2618.add(out, r)

            if progress:
                progress(f"{tag} — tamam ({len(setups)} harmonik)")

    return harmonic_buckets(harmonic), bucket_2618


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="terminal-miraz-olcum",
        description="Miraz konseptleri ölçümü (fraktal/PaMonic/2-618) — salt okuma",
    )
    ap.add_argument("--symbols", required=True, help="Virgüllü pariteler")
    ap.add_argument("--intervals", required=True, help="Virgüllü aralıklar")
    ap.add_argument("--bars", type=int, default=5000, help="Parite×TF mum (vars. 5000)")
    ap.add_argument("--zigzag", type=float, default=None, help="Özel ZigZag eşiği")
    ap.add_argument("--spot", action="store_true", help="Spot (vars. FUTURES)")
    ap.add_argument("--log-level", default="WARNING")
    args = ap.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s [%(levelname)s] %(message)s")
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    intervals = [_normalize_interval(i) for i in args.intervals.split(",") if i.strip()]
    if not symbols or not intervals:
        print("HATA: --symbols ve --intervals boş olamaz.", file=sys.stderr)
        return 1

    print(f"\nMiraz Ölçümü — {len(symbols)} parite × {len(intervals)} TF × {args.bars} mum\n")
    client = MexcClient() if args.spot else MexcFuturesClient()
    try:
        if not client.ping():
            print("MEXC ping başarısız.", file=sys.stderr)
            return 1
        harmonic, b2618 = measure(client, symbols, intervals, args.bars,
                                  threshold=args.zigzag,
                                  progress=lambda m: print(f"  {m}", flush=True))
        print("\n" + "=" * 60)
        print(format_buckets("📊 HARMONİK + Miraz filtreleri", harmonic))
        print("")
        print(format_buckets("📐 2-618 Stratejisi", [b2618]))
        print("=" * 60 + "\n")
        print("Yorum: 'Fraktal teyitli giriş' ve 'Limit + PaMonic' satırlarının WR'si")
        print("'Limit giriş (baz)'dan belirgin yüksekse filtre işe yarıyor (Miraz 8:1).")
        print("PaMonic 'Setup' sayısı baz'a yakınsa filtre seçici değil (gevşek).")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
