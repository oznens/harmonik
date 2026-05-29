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
    entry_mode: str | None = None,
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
        entry_mode: None ise force_immediate_entry'den türetilir
            ("immediate"/"passive"). "confirm" → ONAYLI giriş: D'den sonra ilk
            yapı kırılımı (BOS: kapanış önceki barın ekstremini kırar) beklenir;
            onaydan önce stop yenirse işlem AÇILMAZ (EO). Fakeout filtresi.

    Returns:
        SimOutcome — terminal state'e ulaştıysa TP/STOP/EO/ZI; ulaşmadıysa
        'Aday' veya 'Aktif' (mum dizisi tükendi).
    """
    if entry_mode is None:
        entry_mode = "immediate" if force_immediate_entry else "passive"
    if entry_mode == "confirm":
        return _simulate_confirm(setup, future_klines, aday_timeout, aktif_timeout)
    if entry_mode == "limit":
        return _simulate_limit(setup, future_klines, aday_timeout, aktif_timeout)

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
                # Canlı motorla (_check_aktif: önce STOP kontrol eder) TUTARLI:
                # aynı barda ikisi de değerse bar içi sıralama bilinmediğinden
                # STOP varsay (tutucu). Böylece backtest WR'si canlı paper ile
                # birebir karşılaştırılabilir. (Eski: kapanış yönüne göre TP/STOP
                # — canlıdan iyimserdi, WR'yi şişiriyordu.)
                return SimOutcome(outcome="STOP", entered_idx=entered_idx,
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


def _simulate_confirm(
    setup: Setup,
    future: list[dict[str, Any]],
    confirm_timeout: int,
    aktif_timeout: int,
) -> SimOutcome:
    """ONAYLI giriş: D'den sonra yapı kırılımı (BOS) beklenir.

    Kural:
      - Bull (D=dip): bir bar KAPANIŞI önceki barın HIGH'ını kırarsa onay.
      - Bear (D=tepe): kapanış önceki barın LOW'unu kırarsa onay.
      - Onaydan ÖNCE stop yenirse → işlem AÇILMAZ (EO) — fiyat ters gitti.
      - Onay gelirse SONRAKİ barın açılışından gir; sonra TP/STOP (önce STOP,
        canlı motorla tutarlı). confirm_timeout içinde onay yoksa → EO.
    """
    bull = setup.direction == "bull"
    n = len(future)
    entered_idx: int | None = None
    entered_time: int | None = None
    entered_price: float | None = None

    for i in range(1, n):
        prev, bar = future[i - 1], future[i]
        # Girişten önce stop yenirse setup iptal (reversal gelmedi)
        if (bull and bar["low"] <= setup.stop) or (not bull and bar["high"] >= setup.stop):
            return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                              exited_idx=i, exited_time=bar["open_time"],
                              entered_price=None)
        bos = ((bull and bar["close"] > prev["high"]) or
               (not bull and bar["close"] < prev["low"]))
        if bos:
            if i + 1 >= n:
                # Onay son barda; girilecek bar yok
                return SimOutcome(outcome="Aday", entered_idx=None, entered_time=None,
                                  exited_idx=None, exited_time=None, entered_price=None)
            entered_idx = i + 1
            entered_time = future[i + 1]["open_time"]
            entered_price = future[i + 1]["open"]
            break
        if i >= confirm_timeout:
            return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                              exited_idx=i, exited_time=bar["open_time"],
                              entered_price=None)

    if entered_idx is None:
        return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                          exited_idx=None, exited_time=None, entered_price=None)

    # AKTIF: TP/STOP (önce STOP — canlı _check_aktif ile tutarlı)
    for j in range(entered_idx, n):
        bar = future[j]
        hit_sl = (bull and bar["low"] <= setup.stop) or (not bull and bar["high"] >= setup.stop)
        hit_tp = (bull and bar["high"] >= setup.tp1) or (not bull and bar["low"] <= setup.tp1)
        if hit_sl:
            return SimOutcome(outcome="STOP", entered_idx=entered_idx,
                              entered_time=entered_time, exited_idx=j,
                              exited_time=bar["open_time"], entered_price=entered_price,
                              ambiguous=hit_tp)
        if hit_tp:
            return SimOutcome(outcome="TP", entered_idx=entered_idx,
                              entered_time=entered_time, exited_idx=j,
                              exited_time=bar["open_time"], entered_price=entered_price)
        if j - entered_idx >= aktif_timeout:
            return SimOutcome(outcome="ZI", entered_idx=entered_idx,
                              entered_time=entered_time, exited_idx=j,
                              exited_time=bar["open_time"], entered_price=entered_price)

    return SimOutcome(outcome="Aktif", entered_idx=entered_idx, entered_time=entered_time,
                      exited_idx=None, exited_time=None, entered_price=entered_price)


def _simulate_limit(
    setup: Setup,
    future: list[dict[str, Any]],
    fill_timeout: int,
    aktif_timeout: int,
) -> SimOutcome:
    """LİMİT giriş: D/entry fiyatına limit emir konur, fiyat değince TAM entry'den dolar.

    Klasik harmonik execution (Carney: PRZ'de limit). Slippage YOK — dolum = entry.
    - Bull: fiyat entry'ye iner (low <= entry) → dol. Bear: high >= entry.
    - fill_timeout içinde fiyat entry'ye değmezse → limit dolmaz (EO).
    - Dolum barında stop da değdiyse → STOP (dolup hemen stop; tutucu).
    - TP/STOP önce-STOP (canlı _check_aktif ile tutarlı).
    - Limit dolmadan TP1 vurulduysa → setup iptal (tükenmiş hareket, EO).
    """
    bull = setup.direction == "bull"
    entry = setup.entry
    n = len(future)
    entered_idx: int | None = None
    entered_time: int | None = None

    for i in range(n):
        bar = future[i]
        # TP1 entry'den ÖNCE vurulduysa → hareket bizsiz oldu, geç girme (EO)
        tp_first = (bull and bar["high"] >= setup.tp1) or (not bull and bar["low"] <= setup.tp1)
        if tp_first:
            return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                              exited_idx=i, exited_time=bar["open_time"],
                              entered_price=None)
        touched = (bull and bar["low"] <= entry) or (not bull and bar["high"] >= entry)
        if touched:
            entered_idx = i
            entered_time = bar["open_time"]
            break
        if i >= fill_timeout:
            return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                              exited_idx=i, exited_time=bar["open_time"],
                              entered_price=None)
    if entered_idx is None:
        return SimOutcome(outcome="EO", entered_idx=None, entered_time=None,
                          exited_idx=None, exited_time=None, entered_price=None)

    # Dolum = TAM entry fiyatı (limit). AKTIF: önce STOP (canlı ile tutarlı).
    for j in range(entered_idx, n):
        bar = future[j]
        hit_sl = (bull and bar["low"] <= setup.stop) or (not bull and bar["high"] >= setup.stop)
        hit_tp = (bull and bar["high"] >= setup.tp1) or (not bull and bar["low"] <= setup.tp1)
        if hit_sl:
            return SimOutcome(outcome="STOP", entered_idx=entered_idx,
                              entered_time=entered_time, exited_idx=j,
                              exited_time=bar["open_time"], entered_price=entry,
                              ambiguous=hit_tp)
        if hit_tp:
            return SimOutcome(outcome="TP", entered_idx=entered_idx,
                              entered_time=entered_time, exited_idx=j,
                              exited_time=bar["open_time"], entered_price=entry)
        if j - entered_idx >= aktif_timeout:
            return SimOutcome(outcome="ZI", entered_idx=entered_idx,
                              entered_time=entered_time, exited_idx=j,
                              exited_time=bar["open_time"], entered_price=entry)

    return SimOutcome(outcome="Aktif", entered_idx=entered_idx, entered_time=entered_time,
                      exited_idx=None, exited_time=None, entered_price=entry)
