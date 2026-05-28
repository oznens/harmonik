"""Paper trade motoru — gerçek emir vermeden P&L tracking.

Her setup Aktif olduğunda otomatik paper pozisyon açar:
- Risk sabit $20/trade (config)
- Pozisyon büyüklüğü = $20 / SL_pct
- Leverage = ceil(pozisyon / sermaye/X) — otomatik
- TP/STOP kapanışında P&L USDT olarak hesaplanır
- Equity güncellenir

DB tabloları: paper_account (tek satır), paper_trades.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from terminal.db.store import Store
from terminal.detection.models import Setup

log = logging.getLogger(__name__)

# Sabit parametreler (config'den alınabilir ileride)
RISK_PER_TRADE_USD = 20.0
INITIAL_EQUITY_USD = 1000.0
COMMISSION_PCT = 0.0006  # MEXC futures taker %0.06


@dataclass
class PaperTrade:
    """Açık veya kapanmış paper trade kaydı."""
    setup_id: int
    symbol: str
    interval: str
    pattern: str
    direction: str       # bull/bear
    entry_price: float
    stop_price: float
    tp1_price: float
    position_usd: float  # pozisyon notional ($ cinsi)
    leverage: float      # 1x, 2x, 5x, ...
    risk_usd: float      # her zaman ~$20
    opened_at: int       # ms
    closed_at: int | None = None
    exit_price: float | None = None
    outcome: str | None = None     # TP/STOP/EO/ZI
    pnl_usd: float | None = None   # net P&L (komisyon dahil)


def compute_position(entry: float, stop: float, equity: float,
                     risk_usd: float = RISK_PER_TRADE_USD,
                     max_leverage: int = 20) -> tuple[float, float]:
    """Pozisyon büyüklüğü (USD) + leverage hesapla.

    Risk $X (SL'e değerse kaybedilecek). SL mesafesi %P. Pozisyon = X / P.
    Leverage = ceil(pozisyon / equity), max_leverage ile sınırlı.

    Returns:
        (position_usd, leverage)
    """
    if entry <= 0:
        return 0.0, 1.0
    sl_pct = abs(entry - stop) / entry
    if sl_pct <= 0:
        return 0.0, 1.0
    position = risk_usd / sl_pct
    # Leverage equity baz alarak
    leverage = max(1.0, math.ceil(position / equity))
    leverage = min(leverage, max_leverage)
    # Leverage cap uygulandıysa pozisyon küçülür (risk yine sabit kalır SL açısından)
    return round(position, 2), float(leverage)


class PaperEngine:
    """Paper trade motoru. Store'a okuma/yazma yapar."""

    def __init__(self, store: Store, initial_equity: float = INITIAL_EQUITY_USD,
                 risk_per_trade: float = RISK_PER_TRADE_USD) -> None:
        self.store = store
        self.initial_equity = initial_equity
        self.risk_per_trade = risk_per_trade
        self._migrate()
        self._init_account()

    def _migrate(self) -> None:
        """Paper tabloları idempotent oluştur."""
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_account (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                initial_equity REAL NOT NULL,
                current_equity REAL NOT NULL,
                total_trades INTEGER NOT NULL DEFAULT 0,
                tp_count INTEGER NOT NULL DEFAULT 0,
                stop_count INTEGER NOT NULL DEFAULT 0,
                total_pnl REAL NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)
        self.store._conn.execute("""
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                setup_id INTEGER NOT NULL UNIQUE,
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                pattern TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                stop_price REAL NOT NULL,
                tp1_price REAL NOT NULL,
                position_usd REAL NOT NULL,
                leverage REAL NOT NULL,
                risk_usd REAL NOT NULL,
                opened_at INTEGER NOT NULL,
                closed_at INTEGER,
                exit_price REAL,
                outcome TEXT,
                pnl_usd REAL,
                FOREIGN KEY (setup_id) REFERENCES setups(id) ON DELETE CASCADE
            )
        """)

    def _init_account(self) -> None:
        """Account satırı yoksa oluştur."""
        cur = self.store._conn.execute("SELECT id FROM paper_account WHERE id = 1")
        if cur.fetchone() is None:
            self.store._conn.execute(
                "INSERT INTO paper_account (id, initial_equity, current_equity, created_at) "
                "VALUES (1, ?, ?, ?)",
                (self.initial_equity, self.initial_equity, int(time.time() * 1000)),
            )

    def get_equity(self) -> float:
        cur = self.store._conn.execute(
            "SELECT current_equity FROM paper_account WHERE id = 1"
        )
        return float(cur.fetchone()[0])

    def open_trade(self, setup: Setup, setup_id: int, opened_at: int) -> PaperTrade | None:
        """Setup Aktif olduğunda paper pozisyon aç. Zaten varsa None."""
        # Aynı setup için açık trade var mı
        cur = self.store._conn.execute(
            "SELECT 1 FROM paper_trades WHERE setup_id = ?", (setup_id,)
        )
        if cur.fetchone() is not None:
            return None

        # Parite başına tek açık pozisyon: aynı sembolde halen açık trade
        # varsa yenisini açma (ilk AKTIF olan TF kazanır). Korelasyonlu risk
        # yığılmasını engeller.
        busy = self.store._conn.execute(
            "SELECT setup_id, interval FROM paper_trades "
            "WHERE symbol = ? AND closed_at IS NULL LIMIT 1",
            (setup.symbol,),
        ).fetchone()
        if busy is not None:
            log.info("PAPER SKIP: %s zaten açık pozisyonda (#%s %s) — "
                     "parite başı tek pozisyon", setup.symbol, busy[0], busy[1])
            return None

        equity = self.get_equity()
        position, leverage = compute_position(
            setup.entry, setup.stop, equity, self.risk_per_trade,
        )
        if position <= 0:
            return None

        self.store._conn.execute(
            """INSERT INTO paper_trades
               (setup_id, symbol, interval, pattern, direction,
                entry_price, stop_price, tp1_price,
                position_usd, leverage, risk_usd, opened_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (setup_id, setup.symbol, setup.interval, setup.pattern_name,
             setup.direction, setup.entry, setup.stop, setup.tp1,
             position, leverage, self.risk_per_trade, opened_at),
        )
        log.info("PAPER OPEN: %s %s %s pos=$%.2f lev=%.0fx risk=$%.0f",
                 setup.symbol, setup.interval, setup.pattern_name,
                 position, leverage, self.risk_per_trade)
        return PaperTrade(
            setup_id=setup_id, symbol=setup.symbol, interval=setup.interval,
            pattern=setup.pattern_name, direction=setup.direction,
            entry_price=setup.entry, stop_price=setup.stop, tp1_price=setup.tp1,
            position_usd=position, leverage=leverage,
            risk_usd=self.risk_per_trade, opened_at=opened_at,
        )

    def close_trade(self, setup_id: int, outcome: str, exit_price: float,
                    closed_at: int) -> PaperTrade | None:
        """Setup TP/STOP/EO/ZI olduğunda paper trade'i kapat, P&L hesapla."""
        cur = self.store._conn.execute(
            """SELECT symbol, interval, pattern, direction,
                      entry_price, stop_price, tp1_price,
                      position_usd, leverage, risk_usd, opened_at, closed_at
               FROM paper_trades WHERE setup_id = ?""", (setup_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        (sym, ivl, pat, dirn, entry, stop, tp1,
         position, leverage, risk, opened_at, already_closed) = row
        if already_closed is not None:
            return None  # zaten kapalı

        # P&L: pozisyon * (exit - entry) / entry (bull) veya (entry - exit) / entry (bear)
        if outcome == "TP":
            pnl_pct = abs(tp1 - entry) / entry
            pnl_gross = position * pnl_pct
        elif outcome == "STOP":
            pnl_pct = abs(entry - stop) / entry
            pnl_gross = -position * pnl_pct  # zarar
        else:  # EO / ZI / Aday / Aktif
            pnl_gross = 0.0  # pozisyon açılmadı veya kapanmadı

        # Komisyon (alım + satım)
        commission = position * COMMISSION_PCT * 2 if outcome in ("TP", "STOP") else 0.0
        pnl_net = pnl_gross - commission

        # DB güncelle
        self.store._conn.execute(
            """UPDATE paper_trades
               SET closed_at = ?, exit_price = ?, outcome = ?, pnl_usd = ?
               WHERE setup_id = ?""",
            (closed_at, exit_price, outcome, round(pnl_net, 2), setup_id),
        )
        # Account güncelle
        delta_tp = 1 if outcome == "TP" else 0
        delta_stop = 1 if outcome == "STOP" else 0
        self.store._conn.execute(
            """UPDATE paper_account
               SET current_equity = current_equity + ?,
                   total_trades = total_trades + 1,
                   tp_count = tp_count + ?,
                   stop_count = stop_count + ?,
                   total_pnl = total_pnl + ?
               WHERE id = 1""",
            (pnl_net, delta_tp, delta_stop, pnl_net),
        )
        new_eq = self.get_equity()
        sign = "+" if pnl_net >= 0 else ""
        log.info("PAPER CLOSE: %s %s %s outcome=%s P&L=%s$%.2f equity=$%.2f",
                 sym, ivl, pat, outcome, sign, pnl_net, new_eq)
        return PaperTrade(
            setup_id=setup_id, symbol=sym, interval=ivl, pattern=pat,
            direction=dirn, entry_price=entry, stop_price=stop, tp1_price=tp1,
            position_usd=position, leverage=leverage, risk_usd=risk,
            opened_at=opened_at, closed_at=closed_at, exit_price=exit_price,
            outcome=outcome, pnl_usd=round(pnl_net, 2),
        )

    def summary(self) -> dict[str, Any]:
        """Account özeti."""
        cur = self.store._conn.execute(
            """SELECT initial_equity, current_equity, total_trades,
                      tp_count, stop_count, total_pnl
               FROM paper_account WHERE id = 1"""
        )
        r = cur.fetchone()
        if r is None:
            return {}
        initial, current, total, tp, stop, pnl = r
        decided = tp + stop
        wr = (tp / decided * 100) if decided else 0
        return {
            "initial_equity": initial,
            "current_equity": round(current, 2),
            "total_pnl": round(pnl, 2),
            "pnl_pct": round((current - initial) / initial * 100, 2),
            "total_trades": total,
            "tp": tp, "stop": stop,
            "win_rate": round(wr, 1),
        }

    def open_positions(self) -> list[dict[str, Any]]:
        """Halen açık paper trade'ler."""
        cur = self.store._conn.execute(
            """SELECT symbol, interval, pattern, direction, entry_price,
                      stop_price, tp1_price, position_usd, leverage, opened_at
               FROM paper_trades WHERE closed_at IS NULL ORDER BY opened_at DESC"""
        )
        return [
            {
                "symbol": r[0], "interval": r[1], "pattern": r[2],
                "direction": r[3], "entry": r[4], "stop": r[5], "tp1": r[6],
                "position_usd": r[7], "leverage": r[8], "opened_at": r[9],
            }
            for r in cur.fetchall()
        ]
