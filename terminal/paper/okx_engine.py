"""OKX demo trade motoru — paper engine'in OKX karşılığı (ayrı, paralel).

Paper engine'e DOKUNMAZ; kendi DB tabloları (okx_account/okx_trades). Setup AKTIF
olunca OKX demo'ya iliştirilmiş TP/SL'li LIMIT emir atar; pozisyonu OKX'ten takip
eder. Dinamik kaldıraç + parite-max-cap (OkxInstruments.size_for).

Akış:
  open_trade(setup)  → size hesapla → set_leverage → place_order(limit+TP/SL)
                       → okx_trades'e kaydet (ordId ile)
  sync()             → açık emirleri OKX'ten sorgula; dolmuş/kapanmış olanları
                       güncelle, P&L hesapla, equity güncelle.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from terminal.data.okx_instruments import OkxInstruments
from terminal.data.okx_trade import OkxAuthError, OkxDemoClient
from terminal.db.store import Store
from terminal.detection.models import Setup
from terminal.lifecycle.states import TERMINAL_STATES
from terminal.quality.pamonic import pamonic_confluence

log = logging.getLogger(__name__)

RISK_PER_TRADE_USD = 20.0
INITIAL_EQUITY_USD = 1000.0
MAX_USER_LEVER = 50          # kullanıcı tavanı (parite max'ı bundan düşükse o geçerli)
OB_STOP_BUFFER = 0.001       # OB kenarına %0.1 tampon (iğne payı)
PAMONIC_NEAR_BARS = 15       # OB D'nin son N barında olmalı (taze)
PAMONIC_MIN_DISP = 0.003     # OB min impuls


@dataclass
class OkxTrade:
    setup_id: int
    symbol: str
    interval: str
    pattern: str
    direction: str
    ord_id: str
    cl_ord_id: str
    entry_px: float
    stop_px: float
    tp_px: float
    sz: float
    leverage: int
    notional_usd: float
    opened_at: int
    state: str = "live"       # live / filled / closed / canceled
    exit_px: float | None = None
    pnl_usd: float | None = None
    closed_at: int | None = None


class OkxDemoEngine:
    """OKX demo emir motoru. Store + OKX client'larını kullanır."""

    def __init__(self, store: Store, client: OkxDemoClient,
                 instruments: OkxInstruments,
                 risk_per_trade: float = RISK_PER_TRADE_USD,
                 initial_equity: float = INITIAL_EQUITY_USD,
                 max_lever: int = MAX_USER_LEVER,
                 pamonic: bool = False, max_open: int = 0,
                 fixed_leverage: int = 0, max_notional: float = 0.0,
                 target_margin: float = 0.0, min_free_usdt: float = 0.0,
                 entry_type: str = "market") -> None:
        """pamonic=True: PaMonic modu — OB yoksa pas geç (enforce), OB varsa
        stop'u OB arkasına çek (dar) + TP yapısal (tp2=A harmonik hedef).
        entry_type: "market" (paper gibi anında dol — setup AKTIF olunca girilir,
        kazanan sıçrayışlar kaçmaz) veya "limit" (entry'ye fiyat geri dönerse dol;
        çoğu harmonik dönüşte dolmaz → cancel yığını). Paper market kullanır.
        max_open: aynı anda max açık pozisyon (0=sınırsız) — margin tükenmesini
        (51008) önler. 0 ise sınır YOK: pozisyon sayısı boş USDT'ye göre doğal
        sınırlanır (her açılışta canlı availBal kapısı uygulanır).
        min_free_usdt: işlem sonrası boşta kalması gereken min USDT tamponu (0=tümü
        kullanılabilir, 'bakiye oldukça aç').
        fixed_leverage: sabit kaldıraç (>0). 0=agresif (paritenin max'ı). Kullanıcı
        sabit 20x isterse 20. Risk yine $20 SABİT (SL belirler), kaldıraç sadece
        kilitlenen teminatı belirler (cross margin)."""
        self.store = store
        self.client = client
        self.instruments = instruments
        self.risk = risk_per_trade
        self.initial_equity = initial_equity
        self.max_lever = max_lever
        self.pamonic = pamonic
        self.entry_type = "market" if entry_type == "market" else "limit"
        self.max_open = max_open
        self.fixed_leverage = fixed_leverage
        self.max_notional = max_notional
        self.target_margin = target_margin
        self.min_free_usdt = min_free_usdt
        self._lock = threading.RLock()
        self._migrate()

    def _pamonic_levels(self, setup: Setup, klines: list | None):
        """PaMonic modu seviyeleri. Returns (stop, tp, ok) ya da OB yoksa (.,.,False).

        OB ara (D bölgesi mumlarında). Yoksa → ok=False (pas geç, enforce).
        Varsa → stop = OB arkası (dar), tp = yapısal harmonik hedef (tp2=A; tradermiraz
        'R:R uçar' → uzak yapısal hedef). Dar stop + uzak TP = yüksek R:R.
        """
        if not klines or len(klines) < 5:
            return None, None, False
        d_idx = next((i for i, k in enumerate(klines)
                      if k["open_time"] == setup.pivots["D"].time), len(klines) - 1)
        ob = pamonic_confluence(setup, klines, min_displacement=PAMONIC_MIN_DISP,
                                near_bars=PAMONIC_NEAR_BARS, d_index=d_idx)
        if ob is None:
            return None, None, False
        if setup.direction == "bull":
            stop = ob.bottom * (1 - OB_STOP_BUFFER)
        else:
            stop = ob.top * (1 + OB_STOP_BUFFER)
        # Yapısal TP: tp2 (A noktası, en uzak harmonik hedef). tp2 yoksa tp1.
        tp = setup.tp2 if setup.tp2 else setup.tp1
        return stop, tp, True

    def _migrate(self) -> None:
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS okx_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_id INTEGER NOT NULL UNIQUE,
                symbol TEXT NOT NULL, interval TEXT NOT NULL,
                pattern TEXT NOT NULL, direction TEXT NOT NULL,
                ord_id TEXT, cl_ord_id TEXT,
                entry_px REAL NOT NULL, stop_px REAL NOT NULL, tp_px REAL NOT NULL,
                sz REAL NOT NULL, leverage INTEGER NOT NULL, notional_usd REAL NOT NULL,
                opened_at INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'live',
                exit_px REAL, pnl_usd REAL, closed_at INTEGER
            )
        """)

    def _balance_raw(self) -> dict:
        """Ham OKX bakiye data[0]; hata olursa {}."""
        try:
            return self.client.balance()
        except (OkxAuthError, ValueError, IndexError, KeyError):
            return {}

    def _equity_from(self, bal: dict) -> float:
        """Bakiye dict'inden gerçek equity (totalEq); yoksa initial."""
        try:
            te = bal.get("totalEq") or (bal.get("details") or [{}])[0].get("cashBal")
            return float(te) if te else self.initial_equity
        except (ValueError, IndexError, KeyError, TypeError):
            return self.initial_equity

    def _free_usdt_from(self, bal: dict) -> float | None:
        """Boş (kullanılabilir) USDT margin = availBal. None=okunamadı → kapı pas.

        Cross margin'de availBal yeni pozisyona ayrılabilecek serbest teminattır;
        emir verilince (limit dahil) anında düşer → bir sonraki açılış güncel görür.
        """
        for d in bal.get("details", []):
            if d.get("ccy") == "USDT":
                av = d.get("availBal") or d.get("availEq") or d.get("cashBal")
                try:
                    return float(av) if av else None
                except (ValueError, TypeError):
                    return None
        return None

    def _equity(self) -> float:
        """Demo hesap gerçek equity'si (OKX'ten); hata olursa initial."""
        return self._equity_from(self._balance_raw())

    def open_trade(self, setup: Setup, setup_id: int, opened_at: int,
                   klines: list | None = None) -> OkxTrade | None:
        """Setup AKTIF olunca OKX demo'ya iliştirilmiş TP/SL'li limit emir at.

        klines: PaMonic modunda OB tespiti için D bölgesi mumları (yoksa OB
        bulunamaz → enforce: pas geç).
        """
        with self._lock:
            # Zaten açık mı (aynı setup) / parite başı tek pozisyon (DB)
            if self.store._conn.execute(
                    "SELECT 1 FROM okx_trades WHERE setup_id=?", (setup_id,)
            ).fetchone() is not None:
                return None
            busy = self.store._conn.execute(
                "SELECT 1 FROM okx_trades WHERE symbol=? AND closed_at IS NULL LIMIT 1",
                (setup.symbol,)).fetchone()
            if busy is not None:
                log.info("OKX SKIP: %s zaten açık pozisyonda (parite başı tek)", setup.symbol)
                return None
            # KRİTİK: OKX'in GERÇEK pozisyonunu da kontrol et (DB sync gecikmesi →
            # aynı parite birikip dev pozisyon olmasını engeller — -601 bug'ı).
            inst = self._inst_id(setup.symbol)
            try:
                live_insts = {p.get("instId") for p in self.client.positions()
                              if float(p.get("pos") or 0) != 0}
            except OkxAuthError:
                live_insts = set()
            if inst in live_insts:
                log.info("OKX SKIP: %s OKX'te ZATEN açık pozisyon (gerçek kontrol)",
                         setup.symbol)
                return None
            # Max açık pozisyon sınırı (margin tükenmesini önler)
            if self.max_open > 0:
                open_n = self.store._conn.execute(
                    "SELECT COUNT(*) FROM okx_trades WHERE closed_at IS NULL").fetchone()[0]
                if open_n >= self.max_open:
                    log.info("OKX SKIP: max açık pozisyon (%d) doldu", self.max_open)
                    return None

            # PaMonic modu: OB seviyeleri (dar stop + yapısal TP). OB yoksa pas geç.
            if self.pamonic:
                ob_stop, ob_tp, ok = self._pamonic_levels(setup, klines)
                if not ok:
                    log.info("OKX SKIP (PaMonic): %s %s OB yok → pas geç (enforce)",
                             setup.symbol, setup.interval)
                    return None
                stop_level, tp_level = ob_stop, ob_tp
            else:
                stop_level, tp_level = setup.stop, setup.tp1

            # OKX kuralı (51049): bull → SL<entry<TP, bear → TP<entry<SL. Yanlış
            # taraftaysa (PaMonic dar stop bazen ters çıkabilir) → emir atma, atla.
            e = setup.entry
            if setup.direction == "bull":
                valid = stop_level < e < tp_level
            else:
                valid = tp_level < e < stop_level
            if not valid:
                log.info("OKX SKIP: %s SL/TP yanlış tarafta (entry=%.6g SL=%.6g TP=%.6g %s)",
                         setup.symbol, e, stop_level, tp_level, setup.direction)
                return None

            bal = self._balance_raw()
            equity = self._equity_from(bal)
            sizing = self.instruments.size_for(
                setup.symbol, setup.entry, stop_level, setup.entry,
                risk_usd=self.risk, equity=equity, max_user_lever=self.max_lever,
                fixed_leverage=self.fixed_leverage, max_notional=self.max_notional,
                target_margin=self.target_margin)
            if sizing is None or not sizing.ok:
                log.info("OKX SKIP: %s boyut hesaplanamadı (%s)", setup.symbol,
                         sizing.reason if sizing else "instrument yok")
                return None

            # BAKİYE KAPISI: sabit max-open yerine gerçek boş USDT (availBal). Bu
            # işlemin margin'i + tampon boş USDT'yi aşıyorsa açma → 51008 (yetersiz
            # teminat) baştan önlenir, pozisyon sayısı bakiyeye göre doğal sınırlanır.
            free = self._free_usdt_from(bal)
            if free is not None and free < sizing.margin_usd + self.min_free_usdt:
                log.info("OKX SKIP: boş USDT $%.0f < gereken $%.0f (margin $%.0f"
                         "+tampon $%.0f) — %s bakiye yetmez",
                         free, sizing.margin_usd + self.min_free_usdt,
                         sizing.margin_usd, self.min_free_usdt, setup.symbol)
                return None

            inst = self.instruments.get(setup.symbol)
            side = "buy" if setup.direction == "bull" else "sell"
            entry_px = inst.round_px(setup.entry)
            tp_px = inst.round_px(tp_level)
            sl_px = inst.round_px(stop_level)
            cl_id = f"h{setup_id}"[:32]

            # SON GÜVENLİK (51053): OKX iliştirilmiş TP/SL'i emir fiyatına göre
            # kontrol eder. side ile YUVARLANMIŞ seviyelerin tutarlılığını garantile
            # — buy → sl<entry<tp, sell → tp<entry<sl. Değilse emri ATMA (yuvarlama
            # sonrası ters dönebilir; ya da setup seviyeleri tutarsız).
            if side == "buy":
                consistent = sl_px < entry_px < tp_px
            else:
                consistent = tp_px < entry_px < sl_px
            if not consistent:
                log.info("OKX SKIP: %s %s yuvarlama sonrası SL/TP tutarsız "
                         "(entry=%.6g SL=%.6g TP=%.6g) → emir atma",
                         setup.symbol, side, entry_px, sl_px, tp_px)
                return None

            # MARKET 51050 koruması: market emirde OKX iliştirilmiş TP/SL'i CANLI son
            # fiyata göre kontrol eder (entry'ye değil). Setup AKTİF olduğu an fiyat
            # zaten TP'yi geçmişse (tükenmiş hareket — 'Aktif → TP' aynı bar) TP yanlış
            # tarafta kalır → 51050. Son mum kapanışını referans al; TP/SL ona göre
            # tutarsızsa gir(me) — bu fırsat zaten kaçmış.
            if self.entry_type == "market" and klines:
                last_px = float(klines[-1].get("close") or 0)
                if last_px > 0:
                    if side == "buy":
                        ok_live = sl_px < last_px < tp_px
                    else:
                        ok_live = tp_px < last_px < sl_px
                    if not ok_live:
                        log.info("OKX SKIP (market): %s canlı fiyat %.6g TP/SL aralığı "
                                 "dışında (SL=%.6g TP=%.6g %s) → tükenmiş hareket, girme",
                                 setup.symbol, last_px, sl_px, tp_px, side)
                        return None

            self.client.set_leverage(setup.symbol, sizing.leverage)
            try:
                if self.entry_type == "market":
                    # Paper gibi anında dol — setup AKTIF olunca girilir. px yok.
                    r = self.client.place_order(
                        setup.symbol, side=side, sz=str(sizing.sz), ord_type="market",
                        tp_trigger=self._px(tp_px), sl_trigger=self._px(sl_px),
                        cl_ord_id=cl_id)
                else:
                    r = self.client.place_order(
                        setup.symbol, side=side, sz=str(sizing.sz), ord_type="limit",
                        px=self._px(entry_px), tp_trigger=self._px(tp_px),
                        sl_trigger=self._px(sl_px), cl_ord_id=cl_id)
            except OkxAuthError as e:
                log.warning("OKX emir hatası %s: %s", setup.symbol, e)
                return None
            ord_id = r.get("ordId")
            if not ord_id or r.get("sCode") not in ("0", 0):
                log.warning("OKX emir reddedildi %s: %s", setup.symbol, r.get("sMsg"))
                return None

            self.store._conn.execute(
                """INSERT INTO okx_trades
                   (setup_id, symbol, interval, pattern, direction, ord_id, cl_ord_id,
                    entry_px, stop_px, tp_px, sz, leverage, notional_usd, opened_at, state)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'live')""",
                (setup_id, setup.symbol, setup.interval, setup.pattern_name,
                 setup.direction, ord_id, cl_id, entry_px, sl_px, tp_px,
                 sizing.sz, sizing.leverage, sizing.notional_usd, opened_at))
            log.info("OKX OPEN(%s): %s %s %s sz=%s lev=%dx entry=%.6g TP=%.6g SL=%.6g ord=%s",
                     self.entry_type, setup.symbol, setup.interval, setup.pattern_name,
                     sizing.sz, sizing.leverage, entry_px, tp_px, sl_px, ord_id)
            return OkxTrade(
                setup_id=setup_id, symbol=setup.symbol, interval=setup.interval,
                pattern=setup.pattern_name, direction=setup.direction,
                ord_id=ord_id, cl_ord_id=cl_id, entry_px=entry_px, stop_px=sl_px,
                tp_px=tp_px, sz=sizing.sz, leverage=sizing.leverage,
                notional_usd=sizing.notional_usd, opened_at=opened_at)

    def _inst_id(self, symbol: str) -> str:
        from terminal.data.okx_futures import _to_inst
        return _to_inst(symbol)

    @staticmethod
    def _px(px: float) -> str:
        """OKX fiyat string'i: ASLA bilimsel notasyon (51000 tpTriggerPx error).
        FLOKI gibi düşük fiyatlarda str(2.9e-05)='2.9e-05' → OKX reddeder. Decimal
        ile sabit-ondalık string üret (sondaki gereksiz sıfırlar kırpılır)."""
        d = Decimal(repr(float(px))).normalize()
        s = format(d, "f")            # 'f' = bilimsel notasyon YOK
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s

    @staticmethod
    def _calc_pnl(direction, entry_px, exit_px, notional) -> float:
        """Kendi P&L hesabı: notional × yön × (exit-entry)/entry. Risk $20 niyetiyle
        tutarlı (SL'e değerse ~-$20). realizedPnl yanlış eşleşmesine karşı doğrulama."""
        if not entry_px:
            return 0.0
        pct = (exit_px - entry_px) / entry_px
        sign = 1.0 if direction == "bull" else -1.0
        return notional * pct * sign

    def _cancel_unfilled(self, symbol: str, ord_id: str, setup_id: int,
                         now: int, ostate: str | None = None) -> bool:
        """Dolmamış limit emri OKX'te iptal et + DB'de canceled işaretle.

        Lock ÇAĞIRAN tarafta tutulur (RLock reentrant). ostate verilmezse OKX'ten
        okunur. Emir (kısmen) dolmuşsa iptal ETMEZ — pozisyon vardır, sync kapanışı
        yönetir (state='filled' bırakılır). Returns True sadece temiz iptalde.
        """
        if ostate is None:
            try:
                ostate = self.client.order_state(symbol, ord_id).get("state", "")
            except OkxAuthError:
                return False
        if ostate in ("filled", "partially_filled"):
            # (Kısmen) doldu → pozisyon açık; iptal değil filled bırak (sync kapatır)
            self.store._conn.execute(
                "UPDATE okx_trades SET state='filled' WHERE setup_id=? AND state='live'",
                (setup_id,))
            return False
        try:
            r = self.client.cancel_order(symbol, ord_id)
        except OkxAuthError as e:
            log.warning("OKX iptal hatası %s #%d: %s", symbol, setup_id, e)
            return False
        if str(r.get("sCode", "")) != "0":
            # İptal başarısız → büyük ihtimal arada doldu; doğrula, filled işaretle
            try:
                if self.client.order_state(symbol, ord_id).get("state") == "filled":
                    self.store._conn.execute(
                        "UPDATE okx_trades SET state='filled' WHERE setup_id=? "
                        "AND state='live'", (setup_id,))
            except OkxAuthError:
                pass
            log.info("OKX iptal atlandı #%d %s (sCode=%s %s)",
                     setup_id, symbol, r.get("sCode"), r.get("sMsg"))
            return False
        self.store._conn.execute(
            "UPDATE okx_trades SET state='canceled', closed_at=? "
            "WHERE setup_id=? AND closed_at IS NULL", (now, setup_id))
        log.info("OKX CANCEL: #%d %s emir dolmadan setup çözüldü → iptal (margin serbest)",
                 setup_id, symbol)
        return True

    def cancel_if_unfilled(self, setup_id: int) -> bool:
        """Setup terminal duruma (TP/STOP/ZI/EO) geçti — OKX limit emrimiz hâlâ
        DOLMADIYSA iptal et. Dolduysa (pozisyon) dokunma, sync kapanışı yönetir.

        Senaryo: agresif giriş → tespitte AKTIF + limit emir. Fiyat entry'ye dönmeden
        TP/SL'e gidince setup terminal olur ama limit dolmamıştır → öksüz emir parkta
        margin/parite kilitler. Bu onu temizler. Worker terminal geçişte çağırır.
        """
        with self._lock:
            row = self.store._conn.execute(
                "SELECT symbol, ord_id, state FROM okx_trades "
                "WHERE setup_id=? AND closed_at IS NULL", (setup_id,)).fetchone()
            if row is None:
                return False
            symbol, ord_id, state = row
            if state != "live":
                return False   # zaten dolmuş (pozisyon) → sync kapatır
            return self._cancel_unfilled(symbol, ord_id, setup_id,
                                         int(time.time() * 1000))

    def sync(self) -> int:
        """Açık OKX trade'leri OKX'ten senkronla.

        1) Emir hâlâ live/canceled mı? canceled → kapat.
        2) Dolmamış limit + setup terminal (TP/STOP/ZI/EO) → öksüz emri iptal et.
        3) Pozisyon kapanmış mı? P&L'i positions-history realizedPnl ile (posId/
           clOrdId benzersiz eşleştirme); o bulunamazsa kendi entry/exit'ten hesapla.
        """
        with self._lock:
            # positions-history: instId değil clOrdId/posId bazlı (aynı parite çok
            # kez açılıp kapandığında karışmasın). closeOrdId/last fill eşleştir.
            try:
                hist_list = self.client.positions_history()
            except OkxAuthError:
                hist_list = []
            try:
                open_pos = {p.get("instId") for p in self.client.positions()
                            if float(p.get("pos") or 0) != 0}
            except OkxAuthError:
                open_pos = set()

            rows = self.store._conn.execute(
                "SELECT setup_id, symbol, ord_id, cl_ord_id, state, direction, "
                "entry_px, stop_px, tp_px, sz, notional_usd "
                "FROM okx_trades WHERE closed_at IS NULL").fetchall()
            updated = 0
            now = int(time.time() * 1000)
            for (sid, symbol, ord_id, cl_ord_id, state, direction,
                 entry_px, stop_px, tp_px, sz, notional) in rows:
                inst = self._inst_id(symbol)
                # Emir durumu
                try:
                    od = self.client.order_state(symbol, ord_id)
                    ostate = od.get("state", "")
                except OkxAuthError:
                    ostate = ""
                if ostate == "canceled" and inst not in open_pos:
                    self.store._conn.execute(
                        "UPDATE okx_trades SET state='canceled', closed_at=? WHERE setup_id=?",
                        (now, sid))
                    updated += 1
                    continue
                # Öksüz limit temizliği (backstop): emir hâlâ dolmadı (live) ama
                # setup terminal'e geçtiyse (TP/STOP/ZI/EO) → iptal et. Worker'ın
                # terminal geçişte kaçırdığı/sessiz backfill durumlarını da yakalar.
                if (state == "live" and ostate not in ("filled", "partially_filled")
                        and inst not in open_pos):
                    life = self.store.get_lifecycle(sid)
                    if life is not None and life["state"] in TERMINAL_STATES:
                        if self._cancel_unfilled(symbol, ord_id, sid, now, ostate):
                            updated += 1
                            continue
                if ostate == "filled" and state == "live":
                    self.store._conn.execute(
                        "UPDATE okx_trades SET state='filled' WHERE setup_id=?", (sid,))
                # Pozisyon kapandı mı: artık açık değil + emir filled olmuştu
                if inst not in open_pos and ostate in ("filled", ""):
                    # Bu emre ait history kaydı: instId eşleşen (clOrdId varsa onunla
                    # önceliklendir). realizedPnl'i KENDİ hesabımız doğrular → yanlış
                    # eşleşme (aynı parite çok kapanış) zararı engellenir.
                    cands = [x for x in hist_list if x.get("instId") == inst]
                    h = next((x for x in cands if x.get("clOrdId") == cl_ord_id), None) \
                        or (cands[-1] if cands else None)
                    pnl = None
                    exit_px = None
                    if h is not None:
                        # realizedPnl o paritenin bu kapanışına ait — ama emin değilsek
                        # kendi hesabımızla DOĞRULA (sapma büyükse kendi hesabı kullan)
                        rp = float(h.get("realizedPnl") or 0)
                        exit_px = float(h.get("closeAvgPx") or 0) or None
                        if exit_px:
                            calc = self._calc_pnl(direction, entry_px, exit_px, notional)
                            # realizedPnl ile kendi hesabımız uyuşuyorsa onu kullan,
                            # büyük sapma varsa (yanlış eşleşme) kendi hesabımızı al
                            pnl = rp if abs(rp - calc) < abs(calc) * 0.5 + 1 else calc
                        else:
                            pnl = rp
                    if pnl is None:
                        # history yok → entry/exit bilinmiyor; risk tabanlı tahmin yok,
                        # ZI (sonuçsuz) bırak, bir sonraki sync'te tekrar dene
                        continue
                    self.store._conn.execute(
                        "UPDATE okx_trades SET state='closed', pnl_usd=?, exit_px=?, "
                        "closed_at=? WHERE setup_id=? AND closed_at IS NULL",
                        (round(pnl, 4), exit_px, now, sid))
                    log.info("OKX CLOSE: %s setup#%d realizedPnl=%.4f", symbol, sid, pnl)
                    updated += 1

            # ÖKSÜZ OCO temizliği: pozisyon kapanınca (TP/SL biri tetiklenince OCO
            # zaten gider, ama elle 'Close all' ya da eski birikme sonrası) açık
            # pozisyonu OLMAYAN iliştirilmiş TP/SL emirleri parkta kalabiliyor →
            # margin/parite kilitler. Pozisyonsuz OCO'ları iptal et.
            updated += self._cleanup_orphan_algos(open_pos)
            return updated

    def _cleanup_orphan_algos(self, open_pos: set) -> int:
        """Açık pozisyonu olmayan bekleyen OCO (TP/SL) emirlerini iptal et."""
        cleaned = 0
        try:
            algos = self.client.algo_pending(ord_type="oco")
        except (OkxAuthError, AttributeError):
            return 0
        for a in algos:
            inst = a.get("instId")
            algo_id = a.get("algoId")
            if not inst or not algo_id or inst in open_pos:
                continue   # pozisyonu var → koruması geçerli, dokunma
            try:
                self.client.cancel_algo(inst, algo_id, ord_type="oco")
                log.info("OKX OCO temizlik: %s öksüz TP/SL iptal (algoId=%s, pozisyon yok)",
                         inst, algo_id)
                cleaned += 1
            except OkxAuthError as e:
                log.warning("OKX OCO iptal hatası %s: %s", inst, e)
        return cleaned

    def summary(self) -> dict[str, Any]:
        with self._lock:
            rows = self.store._conn.execute(
                "SELECT state, COUNT(*), COALESCE(SUM(pnl_usd),0) FROM okx_trades "
                "GROUP BY state").fetchall()
            by_state = {r[0]: r[1] for r in rows}
            total_pnl = sum(r[2] for r in rows)
            open_n = self.store._conn.execute(
                "SELECT COUNT(*) FROM okx_trades WHERE closed_at IS NULL").fetchone()[0]
            return {"by_state": by_state, "open": open_n,
                    "total_pnl": round(total_pnl, 2), "equity": self._equity()}

    def open_positions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.store._conn.execute(
                "SELECT symbol, interval, pattern, direction, entry_px, stop_px, tp_px, "
                "sz, leverage, notional_usd, opened_at, state FROM okx_trades "
                "WHERE closed_at IS NULL ORDER BY opened_at DESC").fetchall()
            keys = ["symbol", "interval", "pattern", "direction", "entry_px", "stop_px",
                    "tp_px", "sz", "leverage", "notional_usd", "opened_at", "state"]
            return [dict(zip(keys, r)) for r in rows]
