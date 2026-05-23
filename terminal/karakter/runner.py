"""Karakter Tanıma Laboratuvarı — toplu backtest runner.

Her (symbol, interval) kombinasyonu için:
  1. MEXC'den N (örn. 20.000) mum çek (sayfalanmış)
  2. scan_klines ile tüm tarihsel formasyonları bul
  3. Her setup için D pivotundan sonraki mumları simulate_outcome'a ver
  4. Outcome'ları karakter_samples'a yaz
  5. Tüm koşu bittiğinde karakter_scores agregasyonunu güncelle
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from terminal.data.mexc_client import MexcClient, MexcError
from terminal.db.store import Store
from terminal.detection.models import Setup
from terminal.detection.scanner import default_threshold, scan_klines
from terminal.karakter.simulator import SimOutcome, simulate_outcome

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

            threshold = zigzag_threshold if zigzag_threshold is not None else default_threshold(interval)
            setups = scan_klines(klines, symbol, interval, zigzag_threshold=threshold)

            if progress:
                progress(f"{tag} — {len(klines)} mum, {len(setups)} formasyon, simüle ediliyor...")

            for s in setups:
                d_idx = _find_d_index(klines, s.pivots["D"].time)
                if d_idx is None:
                    continue
                future = klines[d_idx + 1:]
                if not future:
                    continue
                # Lab: detected_at = D pivot zamanı (kronolojik gerçek tespit anı)
                # — scan_klines bunu int(time.time())'a set ediyor, lab için
                # tarihsel zaman daha anlamlı
                s.detected_at = s.pivots["D"].time
                outcome = simulate_outcome(s, future)
                store.add_karakter_sample(run_id, s, outcome)
                total_samples += 1

            if progress:
                progress(f"{tag} — tamam.")

    store.finish_karakter_run(run_id, total_samples)
    store.recompute_karakter_scores()
    if progress:
        progress(f"Lab tamamlandı: {total_samples} örneklem, run_id={run_id}")
    return run_id
