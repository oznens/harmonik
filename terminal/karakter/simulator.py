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
    entered_price: float | None = None  # gerçek giriş fiyatı (aggressive = first bar open)


def simulate_outcome(
    setup: Setup,
    future_klines: list[dict[str, Any]],
    aday_timeout: int = 60,
    aktif_timeout: int = 120,
    force_immediate_entry: bool = True,
) -> SimOutcome:
    """D pivotundan sonraki mum dizisini gez, setup outcome'unu döner.

    Args:
        setup: tespit edilen setup (Entry/SL/TP1 seviyeleri kullanılır).
        future_klines: D pivotundan SONRAKİ mum dizisi (D dahil değil).
        aday_timeout: Aday'da kalış limiti (mum sayısı).
        aktif_timeout: Aktif'te kalış limiti.
        force_immediate_entry: True ise pattern doğrulanır doğrulanmaz hemen
            Aktif (fiyat geri dönsün diye bekleme yok, EO oluşmaz). Gerçek
            "agresif giriş" — D pivotu confirmasyonu = market order. SL/TP
            setup'tan gelir, R hesabı pattern entry'sine göredir (referans).
            False ise eski "Aday → fiyat entry'ye değince Aktif" pasif giriş.

    Returns:
        SimOutcome — terminal state'e ulaştıysa TP/STOP/EO/ZI; ulaşmadıysa
        'Aday' veya 'Aktif' (mum dizisi tükendi).
    """
    bull = setup.direction == "bull"
    entry_trigger = setup.entry

    if force_immediate_entry and future_klines:
        # İlk bar'da hemen Aktif başla — agresif giriş modu
        # Gerçek entry fiyatı = confirmation barı open (market order denkliği)
        state = "Aktif"
        entered_idx = 0
        entered_time = future_klines[0]["open_time"]
        entered_price: float | None = future_klines[0]["open"]
    else:
        state = "Aday"
        entered_idx = None
        entered_time = None
        entered_price = None

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
                                      exited_idx=i, exited_time=bar["open_time"], entered_price=entered_price)
                state = "Aktif"
                entered_idx = i
                entered_time = bar["open_time"]
                # Entry barında TP kontrol ETME — bar içinde hangi yön önce
                # gitti bilinmediği için TP'yi aynı barda eşleştirmek yanıltıcı.
                continue
            elif i >= aday_timeout:
                return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                                  exited_idx=i, exited_time=bar["open_time"], entered_price=entered_price)

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
                                  exited_time=bar["open_time"], ambiguous=True,
                                  entered_price=entered_price)
            if hit_tp:
                return SimOutcome(outcome="TP", entered_idx=entered_idx,
                                  entered_time=entered_time, exited_idx=i,
                                  exited_time=bar["open_time"],
                                  entered_price=entered_price)
            if hit_sl:
                return SimOutcome(outcome="STOP", entered_idx=entered_idx,
                                  entered_time=entered_time, exited_idx=i,
                                  exited_time=bar["open_time"],
                                  entered_price=entered_price)

            # Zaman aşımı (Aktif'te uzun kalma)
            bars_in_aktif = i - (entered_idx or i)
            if bars_in_aktif >= aktif_timeout:
                return SimOutcome(outcome="ZI", entered_idx=entered_idx,
                                  entered_time=entered_time, exited_idx=i,
                                  exited_time=bar["open_time"],
                                  entered_price=entered_price)

    # Mum dizisi tükendi, terminal durum yok
    return SimOutcome(outcome=state, entered_idx=entered_idx, entered_time=entered_time,
                      exited_idx=None, exited_time=None, entered_price=entered_price)
