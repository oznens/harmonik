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
from typing import Any

from terminal.data.okx_instruments import OkxInstruments
from terminal.data.okx_trade import OkxAuthError, OkxDemoClient
from terminal.db.store import Store
from terminal.detection.models import Setup

log = logging.getLogger(__name__)

RISK_PER_TRADE_USD = 20.0
INITIAL_EQUITY_USD = 1000.0
MAX_USER_LEVER = 50          # kullanıcı tavanı (parite max'ı bundan düşükse o geçerli)


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
                 max_lever: int = MAX_USER_LEVER) -> None:
        self.store = store
        self.client = client
        self.instruments = instruments
        self.risk = risk_per_trade
        self.initial_equity = initial_equity
        self.max_lever = max_lever
        self._lock = threading.RLock()
        self._migrate()

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

    def _equity(self) -> float:
        """Demo hesap gerçek equity'si (OKX'ten); hata olursa initial."""
        try:
            bal = self.client.balance()
            te = bal.get("totalEq") or bal.get("details", [{}])[0].get("cashBal")
            return float(te) if te else self.initial_equity
        except (OkxAuthError, ValueError, IndexError, KeyError):
            return self.initial_equity

    def open_trade(self, setup: Setup, setup_id: int, opened_at: int) -> OkxTrade | None:
        """Setup AKTIF olunca OKX demo'ya iliştirilmiş TP/SL'li limit emir at."""
        with self._lock:
            # Zaten açık mı (aynı setup) / parite başı tek pozisyon
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

            equity = self._equity()
            sizing = self.instruments.size_for(
                setup.symbol, setup.entry, setup.stop, setup.entry,
                risk_usd=self.risk, equity=equity, max_user_lever=self.max_lever)
            if sizing is None or not sizing.ok:
                log.info("OKX SKIP: %s boyut hesaplanamadı (%s)", setup.symbol,
                         sizing.reason if sizing else "instrument yok")
                return None

            inst = self.instruments.get(setup.symbol)
            side = "buy" if setup.direction == "bull" else "sell"
            entry_px = inst.round_px(setup.entry)
            tp_px = inst.round_px(setup.tp1)
            sl_px = inst.round_px(setup.stop)
            cl_id = f"h{setup_id}"[:32]

            self.client.set_leverage(setup.symbol, sizing.leverage)
            try:
                r = self.client.place_order(
                    setup.symbol, side=side, sz=str(sizing.sz), ord_type="limit",
                    px=str(entry_px), tp_trigger=str(tp_px), sl_trigger=str(sl_px),
                    cl_ord_id=cl_id)
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
            log.info("OKX OPEN: %s %s %s sz=%s lev=%dx entry=%.6g TP=%.6g SL=%.6g ord=%s",
                     setup.symbol, setup.interval, setup.pattern_name, sizing.sz,
                     sizing.leverage, entry_px, tp_px, sl_px, ord_id)
            return OkxTrade(
                setup_id=setup_id, symbol=setup.symbol, interval=setup.interval,
                pattern=setup.pattern_name, direction=setup.direction,
                ord_id=ord_id, cl_ord_id=cl_id, entry_px=entry_px, stop_px=sl_px,
                tp_px=tp_px, sz=sizing.sz, leverage=sizing.leverage,
                notional_usd=sizing.notional_usd, opened_at=opened_at)

    def _inst_id(self, symbol: str) -> str:
        from terminal.data.okx_futures import _to_inst
        return _to_inst(symbol)

    def sync(self) -> int:
        """Açık OKX trade'leri OKX'ten senkronla.

        1) Emir hâlâ live/canceled mı? canceled → kapat (state=canceled).
        2) Pozisyon kapanmış mı? positions-history'deki realizedPnl ile kesinleştir.
        Güncellenen kayıt sayısını döner.
        """
        with self._lock:
            # Önce kapanmış pozisyon geçmişini bir kez çek (realizedPnl kaynağı)
            try:
                hist = {h.get("instId"): h for h in self.client.positions_history()}
            except OkxAuthError:
                hist = {}
            try:
                open_pos = {p.get("instId") for p in self.client.positions()
                            if float(p.get("pos") or 0) != 0}
            except OkxAuthError:
                open_pos = set()

            rows = self.store._conn.execute(
                "SELECT setup_id, symbol, ord_id, state FROM okx_trades "
                "WHERE closed_at IS NULL").fetchall()
            updated = 0
            now = int(time.time() * 1000)
            for sid, symbol, ord_id, state in rows:
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
                if ostate == "filled" and state == "live":
                    self.store._conn.execute(
                        "UPDATE okx_trades SET state='filled' WHERE setup_id=?", (sid,))
                # Pozisyon kapandı mı: artık açık değil + geçmişte realizedPnl var
                if inst not in open_pos and inst in hist:
                    h = hist[inst]
                    pnl = float(h.get("realizedPnl") or 0)
                    exit_px = float(h.get("closeAvgPx") or 0) or None
                    self.store._conn.execute(
                        "UPDATE okx_trades SET state='closed', pnl_usd=?, exit_px=?, "
                        "closed_at=? WHERE setup_id=? AND closed_at IS NULL",
                        (round(pnl, 4), exit_px, now, sid))
                    log.info("OKX CLOSE: %s setup#%d realizedPnl=%.4f", symbol, sid, pnl)
                    updated += 1
            return updated

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
