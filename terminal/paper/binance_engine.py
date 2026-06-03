"""Binance testnet trade motoru — OkxDemoEngine'in Binance karşılığı (ayrı, paralel).

Kendi DB tablosu (binance_trades). Setup AKTIF olunca testnet'e tek LIMIT/MARKET
entry atar. Dolum sonrası BORSADA-DURAN TP/SL koyar (conditional algo emri,
/fapi/v1/algoOrder — 2025-12'de conditional emirler buraya taşındı). markPrice
backstop yedek kalır (algo gecikmesi/başarısızlığı için). Pozisyonu positionRisk'ten,
P&L'i income(REALIZED_PNL)'den takip eder.

Akış:
  open_trade(setup) → size → set_leverage → entry → binance_trades'e kaydet (stop/tp saklı)
  sync()            → dolum/iptal; dolunca SL+TP algo koy (OCO, biri tetiklenince
                      diğeri otomatik iptal); markPrice backstop; kapanınca realizedPnl yaz
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from decimal import Decimal

from terminal.data.binance_instruments import BinanceInstruments
from terminal.data.binance_trade import BinanceAuthError, BinanceTestClient
from terminal.db.store import Store
from terminal.detection.models import Setup
from terminal.lifecycle.states import TERMINAL_STATES
from terminal.quality.pamonic import pamonic_confluence
from terminal.quality.pa_confluence import pa_signals

log = logging.getLogger(__name__)

RISK_PER_TRADE_USD = 5.0       # düzeltme: düşük risk → PaMonic dar stopları tavana sığar
INITIAL_EQUITY_USD = 1000.0
MAX_USER_LEVER = 50
OB_STOP_BUFFER = 0.001
PAMONIC_NEAR_BARS = 15
PAMONIC_MIN_DISP = 0.003


@dataclass
class BinanceTrade:
    setup_id: int
    symbol: str
    interval: str
    pattern: str
    direction: str
    ord_id: str
    entry_px: float
    stop_px: float
    tp_px: float
    qty: float
    leverage: int
    notional_usd: float
    opened_at: int


class BinanceTestEngine:
    """Binance testnet emir motoru. Store + Binance client'larını kullanır."""

    def __init__(self, store: Store, client: BinanceTestClient,
                 instruments: BinanceInstruments,
                 risk_per_trade: float = RISK_PER_TRADE_USD,
                 initial_equity: float = INITIAL_EQUITY_USD,
                 max_lever: int = MAX_USER_LEVER,
                 pamonic: bool = False, max_open: int = 0,
                 fixed_leverage: int = 0, max_notional: float = 0.0,
                 target_margin: float = 0.0, min_free_usdt: float = 0.0,
                 entry_type: str = "limit", pa_gate: str = "", tg=None) -> None:
        self.store = store
        self.client = client
        self.instruments = instruments
        self.tg = tg            # opsiyonel TelegramClient — açılış/kapanış bildirimi
        self.risk = risk_per_trade
        self.initial_equity = initial_equity
        self.max_lever = max_lever
        self.pamonic = pamonic
        # PA confluence kapısı (OB'ye EK price-action filtresi). "" = kapalı.
        # "pa" = (likidite_süpürme VEYA rejection) VE discount — backtest kazananı.
        self.pa_gate = pa_gate
        self.entry_type = "market" if entry_type == "market" else "limit"
        self.max_open = max_open
        self.fixed_leverage = fixed_leverage
        self.max_notional = max_notional
        self.target_margin = target_margin
        self.min_free_usdt = min_free_usdt
        self._lock = threading.RLock()
        self._migrate()

    # ---- PaMonic seviyeleri (OkxDemoEngine ile aynı mantık) ----
    def _pamonic_levels(self, setup: Setup, klines: list | None):
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
        tp = setup.tp2 if setup.tp2 else setup.tp1
        return stop, tp, True

    def _pa_gate_ok(self, setup: Setup, klines: list | None) -> bool:
        """OB'ye EK price-action confluence kapısı (SMC). pa_gate boşsa hep True.

        Backtest (OKX 3ay, gerçekçi limit dolum) en sağlam kapı:
          "pa" = (likidite_süpürme VEYA rejection_candle) VE discount.
        Bu kapı baz beklentiyi −0.09R'den +0.89R/işlem'e çıkardı (her iki dönem +).
        """
        if not self.pa_gate:
            return True
        if not klines or len(klines) < 10:
            return True
        d_idx = next((i for i, k in enumerate(klines)
                      if k["open_time"] == setup.pivots["D"].time), len(klines) - 1)
        sig = pa_signals(setup, klines, d_idx)
        g = self.pa_gate
        if g == "sweep":
            ok = sig.liq_sweep
        elif g == "reject":
            ok = sig.rejection
        elif g in ("sweep|reject", "sweep_reject"):
            ok = sig.liq_sweep or sig.rejection
        elif g.startswith("score>="):
            try:
                ok = sig.score >= int(g.split(">=")[1])
            except ValueError:
                ok = True
        else:  # "pa" (varsayılan kazanan) ve bilinmeyenler
            ok = (sig.liq_sweep or sig.rejection) and sig.discount
        if not ok:
            log.info("BNB SKIP (PA '%s'): %s %s sweep=%s reject=%s disc=%s → pas",
                     g, setup.symbol, setup.interval, sig.liq_sweep, sig.rejection,
                     sig.discount)
        return ok

    def _migrate(self) -> None:
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS binance_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_id INTEGER NOT NULL UNIQUE,
                symbol TEXT NOT NULL, interval TEXT NOT NULL,
                pattern TEXT NOT NULL, direction TEXT NOT NULL,
                ord_id TEXT, sl_ord_id TEXT, tp_ord_id TEXT, cl_ord_id TEXT,
                entry_px REAL NOT NULL, stop_px REAL NOT NULL, tp_px REAL NOT NULL,
                qty REAL NOT NULL, leverage INTEGER NOT NULL, notional_usd REAL NOT NULL,
                opened_at INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'live',
                exit_px REAL, pnl_usd REAL, closed_at INTEGER
            )
        """)

    @staticmethod
    def _num(x: float) -> str:
        """Binance sayı string'i — bilimsel notasyon YOK (düşük fiyatlı coinler)."""
        d = Decimal(repr(float(x))).normalize()
        s = format(d, "f")
        if "." in s:
            s = s.rstrip("0").rstrip(".")
        return s

    def _notify(self, text: str) -> None:
        """Telegram bildirimi (varsa) — hata yutulur, akışı bozmaz."""
        if self.tg is None:
            return
        try:
            self.tg.send_message(text)
        except Exception as e:
            log.warning("BNB Telegram bildirim hatası: %s", e)

    def _equity(self) -> float:
        try:
            eq = self.client.equity()
            return eq if eq else self.initial_equity
        except BinanceAuthError:
            return self.initial_equity

    def open_trade(self, setup: Setup, setup_id: int, opened_at: int,
                   klines: list | None = None) -> BinanceTrade | None:
        """Setup AKTIF olunca testnet'e entry + TP/SL emirleri at."""
        with self._lock:
            if self.store._conn.execute(
                    "SELECT 1 FROM binance_trades WHERE setup_id=?", (setup_id,)
            ).fetchone() is not None:
                return None
            if self.store._conn.execute(
                    "SELECT 1 FROM binance_trades WHERE symbol=? AND closed_at IS NULL LIMIT 1",
                    (setup.symbol,)).fetchone() is not None:
                log.info("BNB SKIP: %s zaten açık (parite başı tek)", setup.symbol)
                return None
            # Gerçek pozisyon kontrolü (DB sync gecikmesine karşı)
            try:
                if self.client.position_for(setup.symbol) is not None:
                    log.info("BNB SKIP: %s testnet'te ZATEN açık pozisyon", setup.symbol)
                    return None
            except BinanceAuthError:
                pass

            if self.max_open > 0:
                open_n = self.store._conn.execute(
                    "SELECT COUNT(*) FROM binance_trades WHERE closed_at IS NULL").fetchone()[0]
                if open_n >= self.max_open:
                    log.info("BNB SKIP: max açık pozisyon (%d) doldu", self.max_open)
                    return None

            if self.pamonic:
                ob_stop, ob_tp, ok = self._pamonic_levels(setup, klines)
                if not ok:
                    log.info("BNB SKIP (PaMonic): %s %s OB yok → pas geç",
                             setup.symbol, setup.interval)
                    return None
                if not self._pa_gate_ok(setup, klines):
                    return None
                stop_level, tp_level = ob_stop, ob_tp
            else:
                stop_level, tp_level = setup.stop, setup.tp1

            e = setup.entry
            valid = (stop_level < e < tp_level) if setup.direction == "bull" \
                else (tp_level < e < stop_level)
            if not valid:
                log.info("BNB SKIP: %s SL/TP yanlış tarafta (entry=%.6g SL=%.6g TP=%.6g %s)",
                         setup.symbol, e, stop_level, tp_level, setup.direction)
                return None

            equity = self._equity()
            sizing = self.instruments.size_for(
                setup.symbol, setup.entry, stop_level, setup.entry,
                risk_usd=self.risk, equity=equity, max_user_lever=self.max_lever,
                fixed_leverage=self.fixed_leverage, max_notional=self.max_notional,
                target_margin=self.target_margin)
            if sizing is None or not sizing.ok:
                log.info("BNB SKIP: %s boyut hesaplanamadı (%s)", setup.symbol,
                         sizing.reason if sizing else "instrument yok")
                return None

            try:
                free = self.client.free_usdt()
            except BinanceAuthError:
                free = None
            if free is not None and free < sizing.margin_usd + self.min_free_usdt:
                log.info("BNB SKIP: boş USDT $%.0f < gereken $%.0f — %s",
                         free, sizing.margin_usd + self.min_free_usdt, setup.symbol)
                return None

            inst = self.instruments.get(setup.symbol)
            is_bull = setup.direction == "bull"
            entry_side = "BUY" if is_bull else "SELL"
            exit_side = "SELL" if is_bull else "BUY"
            entry_px = inst.round_px(setup.entry)
            tp_px = inst.round_px(tp_level)
            sl_px = inst.round_px(stop_level)
            # yuvarlama sonrası tutarlılık
            consistent = (sl_px < entry_px < tp_px) if is_bull else (tp_px < entry_px < sl_px)
            if not consistent:
                log.info("BNB SKIP: %s yuvarlama sonrası SL/TP tutarsız "
                         "(entry=%.6g SL=%.6g TP=%.6g)", setup.symbol, entry_px, sl_px, tp_px)
                return None
            # CANLI-FİYAT GUARD (limit + market): emir anında fiyat SL/TP aralığının
            # DIŞINDAYSA fiyat entry'yi çoktan geçmiş → bayat/dejenere işlem. Örn. bull
            # limit'i fiyat stop'un altına düşmüşken koymak: anında market'ten dolar +
            # SL zaten ihlal → aç-anında-kapa (sadece komisyon kaybı). Bunu engelle.
            if klines:
                last_px = float(klines[-1].get("close") or 0)
                if last_px > 0:
                    ok_live = (sl_px < last_px < tp_px) if is_bull else (tp_px < last_px < sl_px)
                    if not ok_live:
                        log.info("BNB SKIP: %s canlı fiyat %.6g SL/TP aralığı dışı "
                                 "(entry'yi geçmiş, bayat) → girme", setup.symbol, last_px)
                        return None

            cl_id = f"h{setup_id}"[:36]
            self.client.set_margin_type(setup.symbol, "CROSSED")
            self.client.set_leverage(setup.symbol, sizing.leverage)
            qty_str = self._num(sizing.sz)
            try:
                if self.entry_type == "market":
                    r = self.client.place_order(setup.symbol, entry_side, qty=qty_str,
                                                ord_type="MARKET", client_id=cl_id)
                else:
                    r = self.client.place_order(setup.symbol, entry_side, qty=qty_str,
                                                ord_type="LIMIT", price=self._num(entry_px),
                                                client_id=cl_id)
            except BinanceAuthError as ex:
                log.warning("BNB entry hatası %s: %s", setup.symbol, ex)
                return None
            ord_id = str(r.get("orderId") or "")
            if not ord_id:
                log.warning("BNB entry reddedildi %s: %s", setup.symbol, r)
                return None

            # TP/SL: borsa-native STOP_MARKET/TAKE_PROFIT_MARKET bu testnet'te
            # /fapi/v1/order'da DESTEKLENMİYOR (-4120). Bunun yerine ENGINE-YÖNETİMLİ
            # exit: sync() her turda markPrice'a bakar, stop/tp seviyesine değince
            # MARKET reduceOnly ile kapatır. stop_px/tp_px DB'de saklanır (kontrol için).
            sl_id = tp_id = None

            self.store._conn.execute(
                """INSERT INTO binance_trades
                   (setup_id, symbol, interval, pattern, direction, ord_id, sl_ord_id,
                    tp_ord_id, cl_ord_id, entry_px, stop_px, tp_px, qty, leverage,
                    notional_usd, opened_at, state)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'live')""",
                (setup_id, setup.symbol, setup.interval, setup.pattern_name,
                 setup.direction, ord_id, sl_id, tp_id, cl_id, entry_px, sl_px, tp_px,
                 sizing.sz, sizing.leverage, sizing.notional_usd, opened_at))
            log.info("BNB OPEN(%s): %s %s %s qty=%s lev=%dx entry=%.6g TP=%.6g SL=%.6g ord=%s",
                     self.entry_type, setup.symbol, setup.interval, setup.pattern_name,
                     sizing.sz, sizing.leverage, entry_px, tp_px, sl_px, ord_id)
            arrow = "🟢 LONG" if is_bull else "🔴 SHORT"
            self._notify(
                f"🟡 *BINANCE AÇILDI* {arrow}\n*{setup.symbol}* `{setup.interval}` "
                f"{setup.pattern_name}\nEntry `{self._num(entry_px)}` · SL `{self._num(sl_px)}` "
                f"· TP `{self._num(tp_px)}`\nlev {sizing.leverage}x · risk ${self.risk:.0f}")
            return BinanceTrade(setup_id, setup.symbol, setup.interval, setup.pattern_name,
                                setup.direction, ord_id, entry_px, sl_px, tp_px,
                                sizing.sz, sizing.leverage, sizing.notional_usd, opened_at)

    def cancel_if_unfilled(self, setup_id: int) -> bool:
        """Setup terminal'e geçti — entry hâlâ DOLMADIYSA entry+TP+SL iptal."""
        with self._lock:
            row = self.store._conn.execute(
                "SELECT symbol, ord_id, state FROM binance_trades "
                "WHERE setup_id=? AND closed_at IS NULL", (setup_id,)).fetchone()
            if row is None:
                return False
            symbol, ord_id, state = row
            if state != "live":
                return False
            try:
                st = self.client.order_state(symbol, ord_id).get("status", "")
            except BinanceAuthError:
                return False
            if st in ("FILLED", "PARTIALLY_FILLED"):
                self.store._conn.execute(
                    "UPDATE binance_trades SET state='filled' WHERE setup_id=?", (setup_id,))
                return False
            # dolmadı → paritedeki tüm emirleri (entry+TP+SL) iptal et
            self.client.cancel_all(symbol)
            self.store._conn.execute(
                "UPDATE binance_trades SET state='canceled', closed_at=? WHERE setup_id=?",
                (int(time.time() * 1000), setup_id))
            log.info("BNB CANCEL: #%d %s emir dolmadan setup çözüldü → iptal", setup_id, symbol)
            return True

    def sync(self) -> int:
        """Açık binance trade'leri testnet'ten senkronla.

        Engine-yönetimli exit: borsa-native TP/SL yok (testnet -4120). Her turda
        markPrice'a bakılır; stop/tp seviyesine değen pozisyon MARKET reduceOnly ile
        kapatılır. Kapanış ile P&L kaydı AYRI turlarda — kapat → income yerleşsin →
        bir sonraki sync 'pozisyon yok' dalında gerçek realizedPnl'i yazar.
        """
        with self._lock:
            try:
                positions = {p.get("symbol"): p for p in self.client.positions()}
            except BinanceAuthError:
                positions = {}
            rows = self.store._conn.execute(
                "SELECT setup_id, symbol, ord_id, sl_ord_id, tp_ord_id, state, direction, "
                "stop_px, tp_px, opened_at FROM binance_trades WHERE closed_at IS NULL").fetchall()
            updated = 0
            now = int(time.time() * 1000)
            for (sid, symbol, ord_id, sl_ord_id, tp_ord_id, state, direction,
                 stop_px, tp_px, opened_at) in rows:
                in_pos = symbol in positions
                try:
                    st = self.client.order_state(symbol, ord_id).get("status", "")
                except BinanceAuthError:
                    st = ""
                # İptal/expired + pozisyon yok → kapat
                if st in ("CANCELED", "EXPIRED", "REJECTED") and not in_pos:
                    self.client.cancel_all(symbol)
                    self.store._conn.execute(
                        "UPDATE binance_trades SET state='canceled', closed_at=? WHERE setup_id=?",
                        (now, sid))
                    updated += 1
                    continue
                # Dolmamış + setup terminal → entry iptal (backstop)
                if state == "live" and st not in ("FILLED", "PARTIALLY_FILLED") and not in_pos:
                    life = self.store.get_lifecycle(sid)
                    if life is not None and life["state"] in TERMINAL_STATES:
                        if self.cancel_if_unfilled(sid):
                            updated += 1
                            continue
                if st in ("FILLED", "PARTIALLY_FILLED") and state == "live":
                    self.store._conn.execute(
                        "UPDATE binance_trades SET state='filled' WHERE setup_id=?", (sid,))
                    state = "filled"
                if state != "filled":
                    continue
                # Pozisyon AÇIK
                if in_pos:
                    p = positions[symbol]
                    try:
                        mark = float(p.get("markPrice") or 0)
                        amt = float(p.get("positionAmt") or 0)
                    except (ValueError, TypeError):
                        continue
                    if mark <= 0 or amt == 0:
                        continue
                    is_bull = direction == "bull"
                    exit_side = "SELL" if is_bull else "BUY"
                    # 1) Borsada-duran TP/SL — SL ve TP'yi BAĞIMSIZ koy (biri olmazsa
                    #    diğerini tekrar koyma). Başarısızsa 'bs' sentinel sakla →
                    #    bir daha deneme, markPrice backstop devralır. (PaMonic'in dar
                    #    SL'i sık -2021 'would immediately trigger' verir → backstop.)
                    if not sl_ord_id:
                        try:
                            r = self.client.place_algo_order(symbol, exit_side, "STOP_MARKET",
                                    self._num(stop_px), close_position=True)
                            sl_ord_id = str(r.get("algoId") or "") or "bs"
                        except BinanceAuthError as ex:
                            log.warning("BNB SL algo %s: %s → backstop", symbol, ex)
                            sl_ord_id = "bs"
                        self.store._conn.execute(
                            "UPDATE binance_trades SET sl_ord_id=? WHERE setup_id=?", (sl_ord_id, sid))
                    if not tp_ord_id:
                        try:
                            r = self.client.place_algo_order(symbol, exit_side,
                                    "TAKE_PROFIT_MARKET", self._num(tp_px), close_position=True)
                            tp_ord_id = str(r.get("algoId") or "") or "bs"
                        except BinanceAuthError as ex:
                            log.warning("BNB TP algo %s: %s → backstop", symbol, ex)
                            tp_ord_id = "bs"
                        self.store._conn.execute(
                            "UPDATE binance_trades SET tp_ord_id=? WHERE setup_id=?", (tp_ord_id, sid))
                        log.info("BNB TP/SL: %s SL=%s TP=%s", symbol, sl_ord_id, tp_ord_id)
                    # 2) markPrice BACKSTOP — algo konamayan (bs) / gecikmeli için yedek
                    hit_sl = (mark <= stop_px) if is_bull else (mark >= stop_px)
                    hit_tp = (mark >= tp_px) if is_bull else (mark <= tp_px)
                    if hit_sl or hit_tp:
                        try:
                            self.client.place_order(symbol, "SELL" if amt > 0 else "BUY",
                                    qty=self._num(abs(amt)), ord_type="MARKET", reduce_only=True)
                            log.info("BNB EXIT(%s backstop): %s setup#%d mark=%.6g",
                                     "SL" if hit_sl else "TP", symbol, sid, mark)
                            updated += 1
                        except BinanceAuthError as ex:
                            log.warning("BNB exit hatası %s: %s", symbol, ex)
                    continue
                # Doldu ama pozisyon YOK → kapanmış (bizim exit ya da dış) → gerçek P&L yaz
                pnl = self.client.realized_pnl(symbol, since_ms=opened_at - 1000)
                self.client.cancel_all(symbol)
                self.store._conn.execute(
                    "UPDATE binance_trades SET state='closed', pnl_usd=?, closed_at=? "
                    "WHERE setup_id=? AND closed_at IS NULL", (round(pnl, 4), now, sid))
                log.info("BNB CLOSE: %s setup#%d realizedPnl=%.4f", symbol, sid, pnl)
                res = "✅ TP" if pnl > 0 else ("❌ STOP" if pnl < 0 else "➖ ZI")
                self._notify(f"🟡 *BINANCE KAPANDI* {res}\n*{symbol}*\n"
                             f"P&L: `${pnl:+.2f}`")
                updated += 1

            # ÖKSÜZ pozisyon temizliği: borsada açık ama binance_trades'te AÇIK kaydı
            # olmayan pozisyonlar (eski koşu / wipe artığı). open_trade kaydı kilit
            # içinde atomik eklediğinden yarış yok → kayıtsız pozisyon = gerçek orphan.
            db_syms = {r[0] for r in self.store._conn.execute(
                "SELECT symbol FROM binance_trades WHERE closed_at IS NULL").fetchall()}
            for sym, p in positions.items():
                if sym in db_syms:
                    continue
                try:
                    amt = float(p.get("positionAmt") or 0)
                except (ValueError, TypeError):
                    amt = 0.0
                if amt == 0:
                    continue
                try:
                    for a in self.client.open_algo_orders(sym):
                        self.client.cancel_algo_order(sym, a.get("algoId"))
                except BinanceAuthError:
                    pass
                self.client.cancel_all(sym)
                try:
                    self.client.place_order(sym, "SELL" if amt > 0 else "BUY",
                            qty=self._num(abs(amt)), ord_type="MARKET", reduce_only=True)
                    log.info("BNB ORPHAN kapatıldı: %s (DB kaydı yok, eski artık)", sym)
                    updated += 1
                except BinanceAuthError as ex:
                    log.warning("BNB orphan kapat %s: %s", sym, ex)
            return updated

    def summary(self) -> str:
        c = self.store._conn
        op = c.execute("SELECT COUNT(*) FROM binance_trades WHERE closed_at IS NULL").fetchone()[0]
        cl, pnl = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(pnl_usd),0) FROM binance_trades "
            "WHERE state='closed'").fetchone()
        wins = c.execute("SELECT COUNT(*) FROM binance_trades WHERE state='closed' "
                         "AND pnl_usd>0").fetchone()[0]
        wr = (wins / cl * 100) if cl else 0.0
        return f"açık {op} | kapalı {cl} (WR {wr:.0f}%) | P&L ${pnl:.2f}"

    def send_daily_summary(self) -> None:
        """Telegram'a günlük özet — açık/son24s/toplam + bakiye + günün en iyisi."""
        if self.tg is None:
            return
        c = self.store._conn
        day_ago = int(time.time() * 1000) - 24 * 3600 * 1000
        op = c.execute("SELECT COUNT(*) FROM binance_trades WHERE closed_at IS NULL").fetchone()[0]
        tc, ttp, tsl, tpnl = c.execute(
            "SELECT COUNT(*),COALESCE(SUM(pnl_usd>0),0),COALESCE(SUM(pnl_usd<0),0),"
            "COALESCE(SUM(pnl_usd),0) FROM binance_trades WHERE state='closed' AND closed_at>=?",
            (day_ago,)).fetchone()
        ac, atp, asl, apnl = c.execute(
            "SELECT COUNT(*),COALESCE(SUM(pnl_usd>0),0),COALESCE(SUM(pnl_usd<0),0),"
            "COALESCE(SUM(pnl_usd),0) FROM binance_trades WHERE state='closed'").fetchone()
        twr = ttp / (ttp + tsl) * 100 if (ttp + tsl) else 0
        awr = atp / (atp + asl) * 100 if (atp + asl) else 0
        wallet = upnl = None
        try:
            a = self.client.account()
            wallet = float(a.get("totalWalletBalance") or 0)
            upnl = float(a.get("totalUnrealizedProfit") or 0)
        except BinanceAuthError:
            pass
        best = c.execute("SELECT symbol,pnl_usd FROM binance_trades WHERE state='closed' "
                         "AND closed_at>=? ORDER BY pnl_usd DESC LIMIT 1", (day_ago,)).fetchone()
        lines = ["🟡 *BINANCE GÜNLÜK ÖZET*"]
        if wallet is not None:
            lines.append(f"💰 Cüzdan `${wallet:,.0f}` · Açık P&L `${upnl:+.1f}`")
        lines.append(f"🟢 Açık pozisyon: *{op}*")
        lines.append(f"📋 Son 24s: {tc} kapandı (TP {ttp}/STOP {tsl}, WR %{twr:.0f}) → `${tpnl:+.1f}`")
        lines.append(f"📈 Toplam: {ac} kapandı, WR %{awr:.0f} → `${apnl:+.1f}`")
        if best and best[1] is not None:
            lines.append(f"🏆 Bugün en iyi: {best[0]} `${best[1]:+.1f}`")
        self._notify("\n".join(lines))
