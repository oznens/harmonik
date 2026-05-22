"""SQLite kalıcı depo. Her parite × aralık için kline'lar burada yazılır."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from terminal.config import DB_PATH

log = logging.getLogger(__name__)


class Store:
    """SQLite üstüne ince bir sarmalayıcı. Faz 1 boyutunda yeterli."""

    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self._conn = sqlite3.connect(self.path, isolation_level=None)  # autocommit
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._init_schema()

    def _init_schema(self) -> None:
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path) as f:
            self._conn.executescript(f.read())

    def upsert_kline(self, symbol: str, interval: str, k: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO klines
              (symbol, interval, open_time, close_time,
               open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol, interval,
                k["open_time"], k["close_time"],
                k["open"], k["high"], k["low"], k["close"],
                k["volume"], k.get("quote_volume"),
            ),
        )

    def upsert_klines(self, symbol: str, interval: str, klines: Iterable[dict[str, Any]]) -> None:
        rows = [
            (
                symbol, interval,
                k["open_time"], k["close_time"],
                k["open"], k["high"], k["low"], k["close"],
                k["volume"], k.get("quote_volume"),
            )
            for k in klines
        ]
        if not rows:
            return
        self._conn.executemany(
            """
            INSERT OR REPLACE INTO klines
              (symbol, interval, open_time, close_time,
               open, high, low, close, volume, quote_volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def latest_open_time(self, symbol: str, interval: str) -> int | None:
        cur = self._conn.execute(
            "SELECT MAX(open_time) FROM klines WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        )
        row = cur.fetchone()
        return row[0] if row and row[0] is not None else None

    def count(self, symbol: str, interval: str) -> int:
        cur = self._conn.execute(
            "SELECT COUNT(*) FROM klines WHERE symbol = ? AND interval = ?",
            (symbol, interval),
        )
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()
