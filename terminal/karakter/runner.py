"""Karakter Tanıma Laboratuvarı — toplu backtest runner.

Her (symbol, interval) kombinasyonu için:
  1. MEXC'den N (örn. 20.000) mum çek (sayfalanmış)
  2. (varsa) HTF mumlarını çek; setup başına D zamanı kadar prefiks ile
     HTF trendini tarihsel olarak yeniden hesapla
  3. scan_klines ile tüm tarihsel formasyonları bul
  4. Her setup için D pivotundan sonraki mumları simulate_outcome'a ver
  5. Outcome'ları (HTF bilgisi dahil) karakter_samples'a yaz
  6. Tüm koşu bittiğinde karakter_scores agregasyonunu güncelle
"""
from __future__ import annotations

import bisect
import logging
import time
from typing import Any, Callable

from terminal.data.mexc_client import MexcClient, MexcError
from terminal.db.store import Store
from terminal.detection.models import Setup
from terminal.detection.scanner import _is_elenen, default_threshold, scan_klines
from terminal.karakter.simulator import SimOutcome, simulate_outcome
from terminal.quality.htf_ltf import alignment, detect_trend, htf_for

log = logging.getLogger(__name__)

ProgressCb = Callable[[str], None]


def _find_d_index(klines: list[dict[str, Any]], d_time: int) -> int | None:
    # küçük dizilerde linear arama yeterli; binary olsa daha hızlı
    for i, k in enumerate(klines):
        if k["open_time"] == d_time:
            return i
    return None


def run_lab(
    symbols: list[str],
    intervals: list[str],
    bars_per_pair: int,
    store: Store,
    client: MexcClient,
    zigzag_threshold: float | None = None,
    progress: ProgressCb | None = None,
) -> int:
    """Karakter lab'i tek seferde çalıştır. run_id döner.

    HTF entegrasyonu yok — backtest sırasında HTF anlık trend bilinemediği
    için Q skoru HTF bileşeni dışlanır. Lab tamamen LTF outcomes'a odaklanır.
    """
    started = int(time.time() * 1000)
    run_id = store.create_karakter_run(started, bars_per_pair, symbols, intervals)

    total_combos = len(symbols) * len(intervals)
    combo_idx = 0
    total_samples = 0
    portfolio_trades: list[dict[str, Any]] = []  # canlı-kural portföy simülasyonu için

    for symbol in symbols:
        for interval in intervals:
            combo_idx += 1
            tag = f"[{combo_idx}/{total_combos}] {symbol} {interval}"
            if progress:
                progress(f"{tag} — veri çekiliyor...")

            try:
                klines = client.klines_paginated(symbol, interval, bars_per_pair)
            except MexcError as e:
                log.warning("%s veri çekme hatası: %s", tag, e)
                if progress:
                    progress(f"{tag} — ATLANDI (veri yok)")
                continue

            if len(klines) < 100:
                log.warning("%s yetersiz mum (%d)", tag, len(klines))
                if progress:
                    progress(f"{tag} — ATLANDI (yetersiz mum)")
                continue

            # HTF mumları (varsa) — backtest süresince setup başı tarihsel trend
            htf_int = htf_for(interval)
            htf_klines: list[dict[str, Any]] | None = None
            htf_close_times: list[int] = []
            if htf_int is not None:
                # LTF zaman aralığı kadar HTF mumu çek (LTF bars ÷ ölçek + tampon)
                htf_bars = max(300, bars_per_pair // 4 + 200)
                try:
                    htf_klines = client.klines_paginated(symbol, htf_int, htf_bars, throttle=0.05)
                    htf_close_times = [k["close_time"] for k in htf_klines]
                except MexcError as e:
                    log.warning("%s HTF (%s) veri hatası: %s", tag, htf_int, e)
                    htf_klines = None

            threshold = zigzag_threshold if zigzag_threshold is not None else default_threshold(interval)
            setups = scan_klines(klines, symbol, interval, zigzag_threshold=threshold,
                                 htf_klines=htf_klines)

            if progress:
                htf_note = f", HTF={htf_int}" if htf_klines else ", HTF=yok"
                progress(f"{tag} — {len(klines)} mum{htf_note}, {len(setups)} formasyon, simüle ediliyor...")

            for s in setups:
                d_idx = _find_d_index(klines, s.pivots["D"].time)
                if d_idx is None:
                    continue

                # LOOK-AHEAD FIX: ZigZag pivot retrospective — D pivot olusturken
                # backtest ileri bakiyor. Live'da D pivot'un PIVOT oldugu, fiyat
                # ZigZag eşik kadar D'den uzaklaştigi an anlasilir (genelde 1-2
                # bar sonra). O ana kadar setup henüz tespit edilmemis sayilir.
                d_price = s.pivots["D"].price
                bull = s.direction == "bull"
                confirm_price = d_price * (1 + threshold) if bull else d_price * (1 - threshold)
                confirm_idx = None
                for j in range(d_idx + 1, len(klines)):
                    bar = klines[j]
                    if bull and bar["high"] >= confirm_price:
                        confirm_idx = j
                        break
                    if not bull and bar["low"] <= confirm_price:
                        confirm_idx = j
                        break
                if confirm_idx is None:
                    continue  # D pivot dataset bitene dek dogrulanmadi - atla

                future = klines[confirm_idx + 1:]
                if not future:
                    continue
                # Lab: detected_at = D pivot zamanı (kronolojik gerçek tespit anı)
                # — scan_klines bunu int(time.time())'a set ediyor, lab için
                # tarihsel zaman daha anlamlı
                s.detected_at = s.pivots["D"].time

                # HTF trendini D pivot anı için yeniden hesapla (look-ahead engelle)
                if htf_klines is not None and htf_close_times:
                    d_time = s.pivots["D"].time
                    cutoff = bisect.bisect_right(htf_close_times, d_time)
                    htf_prefix = htf_klines[:cutoff]
                    if len(htf_prefix) >= 60:
                        trend_at_d = detect_trend(htf_prefix)
                        s.htf_trend = trend_at_d
                        s.htf_aligned = alignment(s.direction, trend_at_d)
                        s.elenen = _is_elenen(s)
                    else:
                        s.htf_trend = None
                        s.htf_aligned = None
                        s.elenen = False

                outcome = simulate_outcome(s, future)
                store.add_karakter_sample(run_id, s, outcome)
                total_samples += 1

                # Portföy simülasyonu için trade kaydı (elenen hariç — canlıda
                # elenen setup lifecycle'a/paper'a girmez).
                if not s.elenen and outcome.entered_price is not None:
                    portfolio_trades.append({
                        "symbol": s.symbol, "interval": s.interval,
                        "pattern": s.pattern_name, "direction": s.direction,
                        "ideal_entry": s.entry, "stop": s.stop, "tp1": s.tp1,
                        "fill": outcome.entered_price,
                        "open_time": outcome.entered_time,
                        "close_time": outcome.exited_time,
                        "outcome": outcome.outcome,
                    })

            if progress:
                progress(f"{tag} — tamam.")

    store.finish_karakter_run(run_id, total_samples)
    store.recompute_karakter_scores()

    # Canlı kurallarla portföy P&L simülasyonu
    if progress:
        try:
            from terminal.karakter.portfolio import (
                format_portfolio_summary, simulate_portfolio,
            )
            result = simulate_portfolio(portfolio_trades)
            progress(format_portfolio_summary(result))
        except Exception as e:  # özet başarısız olsa da lab sonucu kaybolmasın
            log.warning("portföy simülasyonu hatası: %s", e)
        progress(f"Lab tamamlandı: {total_samples} örneklem, run_id={run_id}")
    return run_id
