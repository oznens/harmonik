"""Setup yaşam döngüsü durum makinesi.

Her yeni kapanan mum geldiğinde, açık Aday/Aktif setup'lar üstünde gezer:
  - Aday: fiyat PRZ'ye girdi mi (entry tetiklenir) → Aktif
  - Aday: D pivot'tan beri çok mum geçti, hâlâ Aday → Entry Olmadı
  - Aktif: TP1 / SL vuruldu mu → TP / STOP
  - Aktif: Entry'den beri çok mum geçti, sonuç yok → Zamansal İptal

Her geçiş audit log'a yazılır + opsiyonel `on_transition` callback ile
(Telegram bot vs.) dış dünyaya iletilir.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from terminal.db.store import Store
from terminal.detection.models import Setup
from terminal.lifecycle.states import (
    ADAY,
    AKTIF,
    DEFAULT_TIMEOUTS,
    EO,
    STOP,
    TERMINAL_STATES,
    TP,
    ZI,
)

log = logging.getLogger(__name__)


@dataclass
class Transition:
    setup: Setup
    prev_state: str | None
    new_state: str
    trigger_price: float | None
    trigger_time: int        # ms
    notes: str = ""


OnTransition = Callable[[Transition], None]


class LifecycleTracker:
    """Tek bir (symbol, interval) için yaşam döngüsü takipçisi."""

    def __init__(
        self,
        symbol: str,
        interval: str,
        store: Store,
        on_transition: OnTransition | None = None,
        aday_bars_timeout: int = DEFAULT_TIMEOUTS["aday_bars"],
        aktif_bars_timeout: int = DEFAULT_TIMEOUTS["aktif_bars"],
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.store = store
        self.on_transition = on_transition
        self._aday_to = aday_bars_timeout
        self._aktif_to = aktif_bars_timeout
        # backfill sırasında True olur → on_transition'a iletilmez
        self._silent = False

    def register_new(self, setup: Setup, setup_id: int,
                     klines: list[dict[str, Any]] | None = None) -> None:
        """Yeni tespit edilen setup'ı Aday durumunda başlat.

        Eğer `klines` verilirse, D pivot'tan sonraki tüm mumlar sırayla
        işlenerek setup'ın güncel doğru durumu hesaplanır (backfill). Bu
        sayede tarihsel setup'lar (D pivot eskidir) "yanlışlıkla EO" olarak
        işaretlenmez — gerçek geçişler (TP/STOP/EO/ZI) yakalanır.

        Backfill sırasında on_transition geçici olarak susturulur — eski
        transition'lar Telegram'a gitmesin.
        """
        existing = self.store.get_lifecycle(setup_id)
        if existing is not None:
            return  # zaten kayıtlı
        self.store.upsert_lifecycle(
            setup_id=setup_id,
            state=ADAY,
            state_changed_at=setup.detected_at,
            entered_at=None,
            exited_at=None,
            exit_reason=None,
        )
        self.store.add_event(setup_id, prev=None, new=ADAY,
                             ev_time=setup.detected_at, price=None,
                             notes="aday tespit edildi")
        self._emit(Transition(setup, None, ADAY, None, setup.detected_at, "aday tespit"))

        if klines:
            self._backfill(setup, setup_id, klines)

    def _backfill(self, setup: Setup, setup_id: int,
                  klines: list[dict[str, Any]]) -> None:
        """D pivot sonrasındaki tüm mumları sırayla işle (silent).

        Bu metod register_new sırasında çağrılır. Telegram emit'i kapatılır
        çünkü tarihsel transition'lar bildirim üretmemelidir.
        """
        d_time = setup.pivots["D"].time
        d_idx = next((i for i, k in enumerate(klines) if k["open_time"] == d_time), None)
        if d_idx is None or d_idx >= len(klines) - 1:
            return

        interval_ms = self._interval_ms()
        self._silent = True
        try:
            for i in range(d_idx + 1, len(klines)):
                bar = klines[i]
                row = self.store.get_lifecycle(setup_id)
                if row is None:
                    break
                state = row["state"]
                if state in TERMINAL_STATES:
                    break

                bars_since_d = max(0, (bar["open_time"] - d_time) // interval_ms)

                if state == ADAY:
                    self._check_aday(setup, setup_id, bar["high"], bar["low"],
                                     bar["open_time"], bars_since_d)
                elif state == AKTIF:
                    entered_at = row["entered_at"]
                    bars_since_entry = (
                        max(0, (bar["open_time"] - entered_at) // interval_ms)
                        if entered_at else 0
                    )
                    self._check_aktif(setup, setup_id, bar["high"], bar["low"],
                                      bar["open_time"], bars_since_entry)
        finally:
            self._silent = False

    def advance(self, klines: list[dict[str, Any]]) -> list[Transition]:
        """Yeni kapanan mum(lar) gelince açık tüm setup'lar için durumu ilerlet.

        Args:
            klines: chronological kline listesi (en az son birkaç mum).

        Returns:
            Bu çağrıda gerçekleşen tüm geçişler.
        """
        if not klines:
            return []
        latest = klines[-1]
        latest_high = latest["high"]
        latest_low = latest["low"]
        latest_time = latest["open_time"]

        transitions: list[Transition] = []
        open_rows = self.store.open_setups(self.symbol, self.interval)
        for row in open_rows:
            setup_id = int(row["setup_id"])
            state = row["state"]
            setup = self.store.load_setup(setup_id)
            if setup is None:
                continue

            d_time = setup.pivots["D"].time
            interval_ms = self._interval_ms()
            bars_since_d = max(0, (latest_time - d_time) // interval_ms)

            if state == ADAY:
                t = self._check_aday(setup, setup_id, latest_high, latest_low, latest_time, bars_since_d)
                if t:
                    transitions.append(t)
            elif state == AKTIF:
                entered_at = row["entered_at"]
                bars_since_entry = max(0, (latest_time - entered_at) // interval_ms) if entered_at else 0
                t = self._check_aktif(setup, setup_id, latest_high, latest_low, latest_time, bars_since_entry)
                if t:
                    transitions.append(t)

        return transitions

    # ---- iç kontrol mantığı ----

    def _check_aday(self, setup: Setup, setup_id: int,
                    h: float, l: float, t: int, bars_since_d: int) -> Transition | None:
        # Carney'nin tutucu girişi: D ideal seviyesinde tetik
        #   Bull setup: bar.low <= setup.entry (D ideal, 0.786 XA gibi)
        #   Bear setup: bar.high >= setup.entry
        # Bu, "PRZ tam test edildi + tanımlayıcı limit dokunuldu" anlamına gelir.
        if setup.direction == "bull":
            triggered = l <= setup.entry
        else:
            triggered = h >= setup.entry
        if triggered:
            return self._transition(setup, setup_id, ADAY, AKTIF, setup.entry, t,
                                    notes=f"entry tetiklendi (bar high={h:.6g} low={l:.6g})",
                                    entered_at=t)
        # Zaman aşımı
        if bars_since_d >= self._aday_to:
            return self._transition(setup, setup_id, ADAY, EO, None, t,
                                    notes=f"{bars_since_d} mum, entry tetiklenmedi",
                                    exit_reason="aday timeout")
        return None

    def _check_aktif(self, setup: Setup, setup_id: int,
                     h: float, l: float, t: int, bars_since_entry: int) -> Transition | None:
        # Bull: STOP fiyatın altında, TP üstünde
        # Bear: STOP fiyatın üstünde, TP altında
        if setup.direction == "bull":
            if l <= setup.stop:
                return self._transition(setup, setup_id, AKTIF, STOP, setup.stop, t,
                                        notes=f"SL kırıldı (bar low={l})",
                                        exit_reason="stop")
            if h >= setup.tp1:
                return self._transition(setup, setup_id, AKTIF, TP, setup.tp1, t,
                                        notes=f"TP1 vuruldu (bar high={h})",
                                        exit_reason="tp1")
        else:
            if h >= setup.stop:
                return self._transition(setup, setup_id, AKTIF, STOP, setup.stop, t,
                                        notes=f"SL kırıldı (bar high={h})",
                                        exit_reason="stop")
            if l <= setup.tp1:
                return self._transition(setup, setup_id, AKTIF, TP, setup.tp1, t,
                                        notes=f"TP1 vuruldu (bar low={l})",
                                        exit_reason="tp1")
        # Zaman aşımı (Zamansal İptal)
        if bars_since_entry >= self._aktif_to:
            return self._transition(setup, setup_id, AKTIF, ZI, None, t,
                                    notes=f"{bars_since_entry} mum aktif, sonuç yok",
                                    exit_reason="aktif timeout")
        return None

    def _transition(self, setup: Setup, setup_id: int,
                    prev: str, new: str, price: float | None, t: int,
                    notes: str = "", entered_at: int | None = None,
                    exit_reason: str | None = None) -> Transition:
        is_terminal = new in TERMINAL_STATES
        self.store.upsert_lifecycle(
            setup_id=setup_id,
            state=new,
            state_changed_at=t,
            entered_at=entered_at,  # None ise eski değer korunur
            exited_at=t if is_terminal else None,
            exit_reason=exit_reason,
        )
        self.store.add_event(setup_id, prev=prev, new=new, ev_time=t,
                             price=price, notes=notes)
        log.info("[%s %s] setup #%d: %s → %s @ %s (%s)",
                 self.symbol, self.interval, setup_id, prev, new, price, notes)
        trans = Transition(setup, prev, new, price, t, notes)
        self._emit(trans)
        return trans

    def _emit(self, trans: Transition) -> None:
        if self.on_transition and not self._silent:
            try:
                self.on_transition(trans)
            except Exception:
                log.exception("on_transition callback hatası")

    def _interval_ms(self) -> int:
        # Aralık → ms eşlemesi (config'deki ile aynı). Basit harita.
        m = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
             "60m": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1W": 604_800_000}
        return m.get(self.interval, 3_600_000)
