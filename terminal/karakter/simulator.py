"""Setup outcome simülatörü — bir setup'ın D pivotundan sonraki mum dizisinde
ne olacağını (TP/STOP/EO/ZI) yaşam döngüsü kurallarıyla hesaplar.

Pure function: DB'ye yazmaz, sadece outcome döner. Lab/backtest için.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from terminal.detection.models import Setup


@dataclass
class SimOutcome:
    """Backtest outcome'u."""
    outcome: str            # 'TP', 'STOP', 'EO', 'ZI', 'Aday' (henüz aktif değil),
                            # 'Aktif' (henüz sonuç yok)
    entered_idx: int | None    # Aktif olduğu kline indeksi (D'den sonra)
    entered_time: int | None   # ms
    exited_idx: int | None     # terminal duruma geçtiği kline indeksi
    exited_time: int | None    # ms
    ambiguous: bool = False    # aynı barda hem TP hem SL vurulduysa True (konservatif → STOP)


def simulate_outcome(
    setup: Setup,
    future_klines: list[dict[str, Any]],
    aday_timeout: int = 60,
    aktif_timeout: int = 120,
) -> SimOutcome:
    """D pivotundan sonraki mum dizisini gez, setup outcome'unu döner.

    Args:
        setup: tespit edilen setup (Entry/SL/TP1 seviyeleri kullanılır).
        future_klines: D pivotundan SONRAKİ mum dizisi (D dahil değil).
        aday_timeout: Aday'da kalış limiti (mum sayısı).
        aktif_timeout: Aktif'te kalış limiti.

    Returns:
        SimOutcome — terminal state'e ulaştıysa TP/STOP/EO/ZI; ulaşmadıysa
        'Aday' veya 'Aktif' (mum dizisi tükendi).
    """
    state = "Aday"
    entered_idx: int | None = None
    entered_time: int | None = None
    bull = setup.direction == "bull"

    # Carney tutucu girişi (live tracker ile aynı kural): D ideal seviyesi.
    #   Bull: bar.low <= setup.entry
    #   Bear: bar.high >= setup.entry
    entry_trigger = setup.entry

    for i, bar in enumerate(future_klines):
        if state == "Aday":
            triggered = (bull and bar["low"] <= entry_trigger) or \
                        (not bull and bar["high"] >= entry_trigger)
            if triggered:
                # Reversal confirmation: entry barında SL de touch ediliyorsa
                # fiyat PRZ'ye değip aynı bar'da SL'i geçti — reversal yok,
                # gerçek live'da bu setupta kullanıcı emir koymaz (pasif giriş
                # stratejisi: reversal candle gerek). EO olarak işaretle.
                sl_touched_same_bar = (bull and bar["low"] <= setup.stop) or \
                                       (not bull and bar["high"] >= setup.stop)
                if sl_touched_same_bar:
                    return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                                      exited_idx=i, exited_time=bar["open_time"])
                state = "Aktif"
                entered_idx = i
                entered_time = bar["open_time"]
                # Entry barında TP kontrol ETME — bar içinde hangi yön önce
                # gitti bilinmediği için TP'yi aynı barda eşleştirmek yanıltıcı.
                continue
            elif i >= aday_timeout:
                return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                                  exited_idx=i, exited_time=bar["open_time"])

        if state == "Aktif":
            if bull:
                hit_tp = bar["high"] >= setup.tp1
                hit_sl = bar["low"] <= setup.stop
            else:
                hit_tp = bar["low"] <= setup.tp1
                hit_sl = bar["high"] >= setup.stop

            if hit_tp and hit_sl:
                # Aynı barda hem TP hem SL touch oldu → bar içi sıralama
                # bilinmiyor (özellikle 1d gibi büyük TF'lerde sık).
                # Kural: bar KAPANIŞ pozisyonu kazançta ise TP varsay,
                # zararda ise STOP. (Eski mantık: hep STOP — yanıltıcı,
                # XRPUSDT 1d gibi rally'li bar'lar TP yerine STOP işaretliyordu.)
                close = bar["close"]
                close_in_profit = (
                    (bull and close > entry_trigger) or
                    (not bull and close < entry_trigger)
                )
                outcome = "TP" if close_in_profit else "STOP"
                return SimOutcome(outcome=outcome, entered_idx=entered_idx,
                                  entered_time=entered_time, exited_idx=i,
                                  exited_time=bar["open_time"], ambiguous=True)
            if hit_tp:
                return SimOutcome(outcome="TP", entered_idx=entered_idx,
                                  entered_time=entered_time, exited_idx=i,
                                  exited_time=bar["open_time"])
            if hit_sl:
                return SimOutcome(outcome="STOP", entered_idx=entered_idx,
                                  entered_time=entered_time, exited_idx=i,
                                  exited_time=bar["open_time"])

            # Zaman aşımı (Aktif'te uzun kalma)
            bars_in_aktif = i - (entered_idx or i)
            if bars_in_aktif >= aktif_timeout:
                return SimOutcome(outcome="ZI", entered_idx=entered_idx,
                                  entered_time=entered_time, exited_idx=i,
                                  exited_time=bar["open_time"])

    # Mum dizisi tükendi, terminal durum yok
    return SimOutcome(outcome=state, entered_idx=entered_idx, entered_time=entered_time,
                      exited_idx=None, exited_time=None)
