"""Binance testnet trade motoru — OkxDemoEngine'in Binance karşılığı (ayrı, paralel).

Kendi DB tablosu (binance_trades). Setup AKTIF olunca testnet'e LIMIT/MARKET entry
+ ayrı STOP_MARKET(SL) + TAKE_PROFIT_MARKET(TP) (ikisi closePosition=true) atar.
Pozisyonu positionRisk'ten, P&L'i income(REALIZED_PNL)'den takip eder.

Akış:
  open_trade(setup) → size → set_leverage → entry + SL + TP → binance_trades'e kaydet
  sync()            → emir/pozisyon durumu; dolmuş/kapanmış → güncelle, P&L, temizlik
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
                 entry_type: str = "limit") -> None:
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
            if self.entry_type == "market" and klines:
                last_px = float(klines[-1].get("close") or 0)
                if last_px > 0:
                    ok_live = (sl_px < last_px < tp_px) if is_bull else (tp_px < last_px < sl_px)
                    if not ok_live:
                        log.info("BNB SKIP (market): %s canlı %.6g TP/SL dışı → girme",
                                 setup.symbol, last_px)
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

            # TP/SL closePosition emirleri (biri tetiklenince diğerini Binance iptal eder)
            sl_id = tp_id = None
            try:
                rs = self.client.place_order(setup.symbol, exit_side, ord_type="STOP_MARKET",
                                             stop_price=self._num(sl_px), close_position=True,
                                             client_id=f"{cl_id}s"[:36])
                sl_id = str(rs.get("orderId") or "")
            except BinanceAuthError as ex:
                log.warning("BNB SL hatası %s: %s", setup.symbol, ex)
            try:
                rt = self.client.place_order(setup.symbol, exit_side,
                                             ord_type="TAKE_PROFIT_MARKET",
                                             stop_price=self._num(tp_px), close_position=True,
                                             client_id=f"{cl_id}t"[:36])
                tp_id = str(rt.get("orderId") or "")
            except BinanceAuthError as ex:
                log.warning("BNB TP hatası %s: %s", setup.symbol, ex)

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
        """Açık binance trade'leri testnet'ten senkronla (dolum/kapanış/P&L/temizlik)."""
        with self._lock:
            try:
                open_pos = {p.get("symbol") for p in self.client.positions()}
            except BinanceAuthError:
                open_pos = set()
            rows = self.store._conn.execute(
                "SELECT setup_id, symbol, ord_id, state, opened_at "
                "FROM binance_trades WHERE closed_at IS NULL").fetchall()
            updated = 0
            now = int(time.time() * 1000)
            for sid, symbol, ord_id, state, opened_at in rows:
                try:
                    st = self.client.order_state(symbol, ord_id).get("status", "")
                except BinanceAuthError:
                    st = ""
                # İptal olmuş + pozisyon yok → kapat
                if st in ("CANCELED", "EXPIRED", "REJECTED") and symbol not in open_pos:
                    self.client.cancel_all(symbol)   # öksüz TP/SL temizliği
                    self.store._conn.execute(
                        "UPDATE binance_trades SET state='canceled', closed_at=? WHERE setup_id=?",
                        (now, sid))
                    updated += 1
                    continue
                # Dolmamış + setup terminal → öksüz emirleri iptal (backstop)
                if state == "live" and st not in ("FILLED", "PARTIALLY_FILLED") \
                        and symbol not in open_pos:
                    life = self.store.get_lifecycle(sid)
                    if life is not None and life["state"] in TERMINAL_STATES:
                        if self.cancel_if_unfilled(sid):
                            updated += 1
                            continue
                if st in ("FILLED", "PARTIALLY_FILLED") and state == "live":
                    self.store._conn.execute(
                        "UPDATE binance_trades SET state='filled' WHERE setup_id=?", (sid,))
                    state = "filled"
                # Pozisyon kapandı mı: doldu (filled) ama artık açık pozisyon yok
                if state in ("filled",) and symbol not in open_pos:
                    pnl = self.client.realized_pnl(symbol, since_ms=opened_at - 1000)
                    self.client.cancel_all(symbol)   # kalan closePosition emrini temizle
                    self.store._conn.execute(
                        "UPDATE binance_trades SET state='closed', pnl_usd=?, closed_at=? "
                        "WHERE setup_id=? AND closed_at IS NULL", (round(pnl, 4), now, sid))
                    log.info("BNB CLOSE: %s setup#%d realizedPnl=%.4f", symbol, sid, pnl)
                    updated += 1
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
