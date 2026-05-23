"""Store üzerine ince katman: UI'nin ihtiyaç duyduğu sorguları sağlar.

DB'yi doğrudan ellemek yerine bu katmandan geçilir; tüm sorgular tek yerde.
Bütün metodlar saf veri döndürür (UI bağımsız), kolayca test edilebilir.
"""
from __future__ import annotations

from dataclasses import dataclass

from terminal.db.store import Store
from terminal.timeutil import start_of_today_ms


@dataclass
class StatusCounts:
    aktif: int = 0
    aday: int = 0
    tp: int = 0
    stop: int = 0
    eo: int = 0
    zi: int = 0
    bugun_setup: int = 0
    toplam: int = 0
    win_rate: float = 0.0  # 0-100


@dataclass
class SetupRow:
    id: int
    symbol: str
    interval: str
    pattern_name: str
    direction: str
    state: str
    q_score: int | None
    q_category: str | None
    entry: float
    stop: float
    tp1: float
    d_time: int
    d_price: float
    detected_at: int
    htf_aligned: bool | None
    elenen: bool


@dataclass
class KarakterRow:
    symbol: str
    interval: str
    pattern_name: str
    direction: str
    sample_count: int
    tp_count: int
    stop_count: int
    eo_count: int
    zi_count: int
    win_rate: float
    karakter_score: float


class DataProvider:
    """UI sorgu katmanı. Store'u sarmalayıp UI-spesifik agregeler döner."""

    def __init__(self, store: Store) -> None:
        self.store = store

    # ---- status bar ----

    def status_counts(self) -> StatusCounts:
        c = self.store._conn
        sc = StatusCounts()
        cur = c.execute(
            """SELECT l.state, COUNT(*) FROM setup_lifecycle l GROUP BY l.state""",
        )
        for state, n in cur.fetchall():
            n = int(n)
            if state == "Aktif": sc.aktif = n
            elif state == "Aday": sc.aday = n
            elif state == "TP":   sc.tp = n
            elif state == "STOP": sc.stop = n
            elif state == "EO":   sc.eo = n
            elif state == "ZI":   sc.zi = n
        sc.toplam = c.execute("SELECT COUNT(*) FROM setups").fetchone()[0]
        # Bugün tespit edilen
        sc.bugun_setup = c.execute(
            "SELECT COUNT(*) FROM setups WHERE detected_at >= ?",
            (start_of_today_ms(),),
        ).fetchone()[0]
        decided = sc.tp + sc.stop
        sc.win_rate = (sc.tp / decided * 100) if decided > 0 else 0.0
        return sc

    # ---- setups tab ----

    def setups(self, states: list[str] | None = None, limit: int = 500,
               symbol: str | None = None, interval: str | None = None) -> list[SetupRow]:
        sql = """
            SELECT s.id, s.symbol, s.interval, s.pattern_name, s.direction,
                   COALESCE(l.state, 'Aday') AS state,
                   s.q_score, s.q_category,
                   s.entry, s.stop, s.tp1,
                   s.d_time, s.d_price, s.detected_at,
                   s.htf_aligned, s.elenen
            FROM setups s
            LEFT JOIN setup_lifecycle l ON l.setup_id = s.id
            WHERE 1=1
        """
        params: list = []
        if states:
            placeholders = ",".join("?" * len(states))
            sql += f" AND COALESCE(l.state, 'Aday') IN ({placeholders})"
            params.extend(states)
        if symbol:
            sql += " AND s.symbol = ?"; params.append(symbol)
        if interval:
            sql += " AND s.interval = ?"; params.append(interval)
        sql += " ORDER BY s.detected_at DESC, s.d_time DESC LIMIT ?"
        params.append(limit)
        cur = self.store._conn.execute(sql, params)
        return [_row_to_setup(r) for r in cur.fetchall()]

    # ---- karakter tab ----

    def karakter_scores(self, direction: str = "all", min_samples: int = 1,
                        limit: int = 200) -> list[KarakterRow]:
        cur = self.store._conn.execute(
            """SELECT symbol, interval, pattern_name, direction,
                      sample_count, tp_count, stop_count, eo_count, zi_count,
                      win_rate, karakter_score
               FROM karakter_scores
               WHERE direction = ? AND sample_count >= ?
               ORDER BY karakter_score DESC, sample_count DESC
               LIMIT ?""",
            (direction, min_samples, limit),
        )
        return [
            KarakterRow(
                symbol=r[0], interval=r[1], pattern_name=r[2], direction=r[3],
                sample_count=int(r[4]), tp_count=int(r[5]), stop_count=int(r[6]),
                eo_count=int(r[7]), zi_count=int(r[8]),
                win_rate=float(r[9] or 0), karakter_score=float(r[10] or 0),
            )
            for r in cur.fetchall()
        ]


def _row_to_setup(r) -> SetupRow:
    return SetupRow(
        id=int(r[0]), symbol=r[1], interval=r[2], pattern_name=r[3], direction=r[4],
        state=r[5], q_score=r[6], q_category=r[7],
        entry=float(r[8]), stop=float(r[9]), tp1=float(r[10]),
        d_time=int(r[11]), d_price=float(r[12]), detected_at=int(r[13]),
        htf_aligned=bool(r[14]) if r[14] is not None else None,
        elenen=bool(r[15]),
    )
