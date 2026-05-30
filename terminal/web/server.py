"""Mobil-uyumlu paper trade web dashboard.

Tamamen Python stdlib — hiçbir ekstra bağımlılık yok (http.server + string).
Aynı terminal.db'yi SALT-OKUNUR okur; tracker'dan bağımsız ayrı bir servistir,
yazma yapmaz. HTTP Basic Auth ile korunur. Sayfa ~10 sn'de bir otomatik yenilenir.

Kullanım:
    WEB_USER=admin WEB_PASS=gizli python -m terminal.web.server --port 8080
    python -m terminal.web.server --user admin --password gizli --port 8080

Telefondan:  http://<VPS_IP>:8080  → kullanıcı adı + şifre sorar.
"""
from __future__ import annotations

import argparse
import base64
import html as html_mod
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from terminal.config import DB_PATH
from terminal.web import cards

log = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=3))  # IST — UI ile tutarlı

_INTERVAL_MS = {
    "1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "60m": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "1W": 604_800_000,
}

# matplotlib/mplfinance global state thread-safe değil → grafik render serileştir.
_CHART_LOCK = threading.Lock()


def _fmt_ts(ms: int | None) -> str:
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%m-%d %H:%M")


def _fmt_age(ms: int | None) -> str:
    if not ms:
        return "—"
    delta = int(time.time() * 1000) - ms
    if delta < 0:
        return "—"
    mins = delta // 60000
    if mins < 60:
        return f"{mins}dk"
    hrs = mins // 60
    if hrs < 24:
        return f"{hrs}sa"
    return f"{hrs // 24}g"


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:.4f}"
    return f"{p:.6g}"


def _rr(entry: float, stop: float, tp1: float) -> float:
    risk = abs(entry - stop)
    return abs(tp1 - entry) / risk if risk else 0.0


def _e(s) -> str:
    """HTML-escape (DB verisi kontrollü ama yine de güvenli taraf)."""
    return html_mod.escape(str(s))


STYLE = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; background:#0e0e10; color:#e6e6ea;
         font-family:-apple-system,'Segoe UI',Roboto,sans-serif; font-size:14px; }
  .wrap { max-width:980px; margin:0 auto; padding:12px; }
  h1 { font-size:18px; color:#d4a72c; margin:4px 0 12px; }
  .cards { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:16px; }
  .card { flex:1 1 90px; background:#1a1a1f; border:1px solid #2a2a32;
          border-radius:8px; padding:8px 10px; text-align:center; }
  .card .lbl { color:#888; font-size:10px; text-transform:uppercase; }
  .card .val { font-size:17px; font-weight:700; margin-top:2px; }
  .sec { color:#42a5f5; font-weight:700; margin:14px 0 6px; }
  .sec.dim { color:#888; }
  .tablewrap { overflow-x:auto; -webkit-overflow-scrolling:touch;
               border:1px solid #2a2a32; border-radius:8px; }
  table { border-collapse:collapse; width:100%; min-width:560px; font-size:13px; }
  th,td { padding:7px 9px; text-align:right; white-space:nowrap;
          border-bottom:1px solid #20202a; }
  th { background:#15151a; color:#9aa; font-weight:600; position:sticky; top:0; }
  td.l, th.l { text-align:left; }
  tr:nth-child(even) td { background:#121217; }
  .g { color:#4caf50; } .r { color:#ef5350; } .d { color:#888; }
  .empty { padding:18px; text-align:center; color:#888; }
  .foot { margin-top:16px; color:#666; font-size:11px; text-align:center; }
"""


def _connect_ro(db_path) -> sqlite3.Connection:
    """terminal.db'ye salt-okunur bağlan (writer'ı kilitlemez, WAL uyumlu)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _load_setup_ro(conn: sqlite3.Connection, setup_id: int):
    """Setup'ı salt-okunur bağlantıdan yükle (Store.load_setup'ın read-only kopyası;
    Store import edip şema yazımı tetiklememek + PySide6 çekmemek için)."""
    from terminal.detection.models import Setup
    from terminal.detection.pivots import Pivot

    row = conn.execute("SELECT * FROM setups WHERE id = ?", (setup_id,)).fetchone()
    if row is None:
        return None
    d = row["direction"]
    return Setup(
        symbol=row["symbol"], interval=row["interval"],
        pattern_name=row["pattern_name"], direction=d,
        pivots={
            "X": Pivot(0, row["x_time"], row["x_price"], "low" if d == "bull" else "high"),
            "A": Pivot(0, row["a_time"], row["a_price"], "high" if d == "bull" else "low"),
            "B": Pivot(0, row["b_time"], row["b_price"], "low" if d == "bull" else "high"),
            "C": Pivot(0, row["c_time"], row["c_price"], "high" if d == "bull" else "low"),
            "D": Pivot(0, row["d_time"], row["d_price"], "low" if d == "bull" else "high"),
        },
        b_ratio=row["b_ratio"], c_ratio=row["c_ratio"], d_ratio=row["d_ratio"],
        bc_proj=row["bc_proj"], cd_ab_ratio=row["cd_ab_ratio"],
        ab_cd_equivalent=bool(row["ab_cd_equivalent"]),
        prz_low=row["prz_low"], prz_high=row["prz_high"],
        prz_components=json.loads(row["prz_components"]),
        entry=row["entry"], stop=row["stop"], tp1=row["tp1"], tp2=row["tp2"],
        detected_at=row["detected_at"],
        q_score=row["q_score"] or 0, q_category=row["q_category"] or "",
        htf_interval=row["htf_interval"], htf_trend=row["htf_trend"],
        elenen=bool(row["elenen"]),
    )


def _lifecycle_exit(conn: sqlite3.Connection, setup_id: int) -> tuple[int, str] | None:
    """Kapanmış setup için (exit_time_ms, outcome). Açıksa None."""
    try:
        row = conn.execute(
            "SELECT state, exited_at FROM setup_lifecycle WHERE setup_id = ?",
            (setup_id,),
        ).fetchone()
    except sqlite3.Error:
        return None
    if row and row["state"] in ("TP", "STOP", "ZI", "EO") and row["exited_at"]:
        return int(row["exited_at"]), row["state"]
    return None


def _klines_for_setup(conn: sqlite3.Connection, setup, exit_time: int | None = None,
                      pad_before: int = 10, pad_after: int = 30,
                      pad_after_exit: int = 8) -> list | None:
    """Setup penceresindeki mumları DB'den getir.

    Kapanmış trade'de (exit_time verilmiş) pencere ÇIKIŞ anına kadar uzar
    (X-öncesi → çıkış+pad); aksi halde D-sonrası sabit pencere.
    """
    ms = _INTERVAL_MS.get(setup.interval, 3_600_000)
    start_t = setup.pivots["X"].time - pad_before * ms
    if exit_time is not None:
        end_t = exit_time + pad_after_exit * ms
    else:
        end_t = setup.pivots["D"].time + pad_after * ms
    rows = conn.execute(
        "SELECT open_time, close_time, open, high, low, close, volume, quote_volume "
        "FROM klines WHERE symbol = ? AND interval = ? "
        "AND open_time >= ? AND open_time <= ? ORDER BY open_time",
        (setup.symbol, setup.interval, start_t, end_t),
    ).fetchall()
    if not rows:
        return None
    return [
        {"open_time": r[0], "close_time": r[1], "open": r[2], "high": r[3],
         "low": r[4], "close": r[5], "volume": r[6], "quote_volume": r[7]}
        for r in rows
    ]


def render_chart_png(db_path, setup_id: int) -> bytes | None:
    """Setup grafiğini PNG olarak üret. Veri yetersizse None."""
    try:
        conn = _connect_ro(db_path)
    except sqlite3.Error:
        return None
    try:
        setup = _load_setup_ro(conn, setup_id)
        if setup is None:
            return None
        exit_marker = _lifecycle_exit(conn, setup_id)
        exit_time = exit_marker[0] if exit_marker else None
        klines = _klines_for_setup(conn, setup, exit_time=exit_time)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if not klines or len(klines) < 5:
        return None
    from terminal.telegram_bot.charts import render_setup_chart  # lazy: matplotlib ağır
    with _CHART_LOCK:
        return render_setup_chart(setup, klines, exit_marker=exit_marker)


def chart_page(db_path, setup_id: int) -> str:
    """Grafiği gömen küçük HTML sayfası (geri linki + başlık). Auto-refresh yok."""
    title = f"Setup #{setup_id}"
    try:
        conn = _connect_ro(db_path)
        try:
            row = conn.execute(
                "SELECT symbol, interval, pattern_name, direction FROM setups WHERE id = ?",
                (setup_id,),
            ).fetchone()
        finally:
            conn.close()
        if row:
            arrow = "▲" if row["direction"] == "bull" else "▼"
            title = f'{row["symbol"]} {row["interval"]} · {row["pattern_name"]} {arrow}'
    except sqlite3.Error:
        pass
    return f"""<!doctype html>
<html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<style>{STYLE}
  .imgwrap {{ border:1px solid #2a2a32; border-radius:8px; overflow:hidden; background:#fff; }}
  .imgwrap img {{ display:block; width:100%; height:auto; }}
  a.back {{ display:inline-block; margin:8px 0 12px; color:#42a5f5; text-decoration:none;
           font-weight:600; }}
</style></head>
<body><div class="wrap">
  <a class="back" href="/">← Geri</a>
  <h1>{_e(title)}</h1>
  <div class="imgwrap"><img src="/chart.png?id={setup_id}" alt="grafik"
       onerror="this.parentNode.innerHTML='<div class=empty>Grafik için yeterli mum verisi yok.</div>'"></div>
</div></body></html>"""


def _pattern_table(rows: list) -> str:
    """Harmonik bazında performans: TP / SL / WR / P&L + ortalama skorlar."""
    if not rows:
        return '<div class="empty">Henüz kapanan kararlı işlem yok.</div>'
    head = ("<table><thead><tr>"
            '<th class="l">Pattern</th><th>TP</th><th>SL</th><th>WR</th>'
            "<th>P&amp;L</th><th>Ø Q</th><th>Ø Conf</th>"
            "</tr></thead><tbody>")
    body = []
    for r in rows:
        tp = r["tp"] or 0
        sl = r["sl"] or 0
        dec = tp + sl
        wr = (tp / dec * 100) if dec else 0
        pnl = r["pnl"] or 0
        wr_cls = "g" if wr >= 50 else "r"
        pnl_cls = "g" if pnl > 0 else "r" if pnl < 0 else "d"
        body.append(
            f'<tr><td class="l">{_e(r["pattern"])}</td>'
            f'<td class="g">{tp}</td><td class="r">{sl}</td>'
            f'<td class="{wr_cls}">{wr:.0f}%</td>'
            f'<td class="{pnl_cls}">{"+" if pnl >= 0 else ""}${pnl:.2f}</td>'
            f'<td>{(r["avg_q"] or 0):.0f}</td>'
            f'<td>{(r["avg_conf"] or 0):.0f}</td></tr>'
        )
    return head + "".join(body) + "</tbody></table>"


def render_dashboard(db_path, refresh: int) -> str:
    initial = equity = 1000.0
    total_pnl = pnl_pct = 0.0
    total_trades = tp = stop = 0
    open_raw: list = []
    closed_raw: list = []
    pattern_raw: list = []
    card_trades: list = []

    try:
        conn = _connect_ro(db_path)
        try:
            acc = conn.execute(
                "SELECT initial_equity, current_equity, total_trades, tp_count, "
                "stop_count, total_pnl FROM paper_account WHERE id = 1"
            ).fetchone()
            open_raw = conn.execute(
                "SELECT setup_id, symbol, interval, pattern, direction, entry_price, "
                "stop_price, tp1_price, position_usd, leverage, opened_at FROM paper_trades "
                "WHERE closed_at IS NULL ORDER BY opened_at DESC"
            ).fetchall()
            closed_raw = conn.execute(
                "SELECT setup_id, symbol, interval, pattern, direction, entry_price, "
                "stop_price, tp1_price, exit_price, outcome, pnl_usd, leverage, closed_at "
                "FROM paper_trades WHERE closed_at IS NOT NULL "
                "ORDER BY closed_at DESC LIMIT 50"
            ).fetchall()
            pattern_raw = conn.execute(
                "SELECT pt.pattern AS pattern, "
                "SUM(CASE WHEN pt.outcome='TP' THEN 1 ELSE 0 END) AS tp, "
                "SUM(CASE WHEN pt.outcome='STOP' THEN 1 ELSE 0 END) AS sl, "
                "SUM(COALESCE(pt.pnl_usd, 0)) AS pnl, "
                "AVG(s.q_score) AS avg_q, AVG(s.confluence_score) AS avg_conf "
                "FROM paper_trades pt LEFT JOIN setups s ON s.id = pt.setup_id "
                "WHERE pt.closed_at IS NOT NULL AND pt.outcome IN ('TP','STOP') "
                "GROUP BY pt.pattern ORDER BY (tp + sl) DESC"
            ).fetchall()
            card_trades = cards.load_card_trades(conn, limit=24)
            if acc:
                initial = acc["initial_equity"]
                equity = acc["current_equity"]
                total_trades = acc["total_trades"]
                tp = acc["tp_count"]
                stop = acc["stop_count"]
                total_pnl = acc["total_pnl"]
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.warning("DB okuma: %s", e)

    decided = tp + stop
    wr = (tp / decided * 100) if decided else 0
    pnl_pct = ((equity - initial) / initial * 100) if initial else 0
    pnl_cls = "g" if total_pnl > 0 else "r" if total_pnl < 0 else "d"
    wr_txt = f"{wr:.1f}%" if decided else "—"
    wr_cls = "g" if decided and wr >= 60 else "r" if decided and wr < 45 else "d"
    now = datetime.now(tz=TZ).strftime("%H:%M:%S")

    stat_cards = f"""
    <div class="cards">
      <div class="card"><div class="lbl">Equity</div>
        <div class="val {'g' if equity >= initial else 'r'}">${equity:.2f}</div></div>
      <div class="card"><div class="lbl">Toplam P&amp;L</div>
        <div class="val {pnl_cls}">{'+' if total_pnl >= 0 else ''}${total_pnl:.2f}</div></div>
      <div class="card"><div class="lbl">P&amp;L %</div>
        <div class="val {pnl_cls}">{'+' if pnl_pct >= 0 else ''}{pnl_pct:.1f}%</div></div>
      <div class="card"><div class="lbl">Win Rate</div>
        <div class="val {wr_cls}">{wr_txt}</div></div>
      <div class="card"><div class="lbl">Trade</div><div class="val">{total_trades}</div></div>
      <div class="card"><div class="lbl">TP</div><div class="val g">{tp}</div></div>
      <div class="card"><div class="lbl">STOP</div><div class="val r">{stop}</div></div>
      <div class="card"><div class="lbl">Açık</div>
        <div class="val" style="color:#42a5f5">{len(open_raw)}</div></div>
    </div>"""

    open_table = _open_table(open_raw)
    closed_table = _closed_table(closed_raw)
    pattern_table = _pattern_table(pattern_raw)
    cards_grid = cards.cards_grid_html(card_trades, "Henüz işlem yok.")

    return f"""<!doctype html>
<html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>Harmonik · Paper</title>
<style>{STYLE}{cards.CARD_CSS}</style></head>
<body><div class="wrap">
  <h1>💼 Harmonik — Paper Trade</h1>
  {stat_cards}
  <div class="sec">📇 Sonuç Kartları ({len(card_trades)})</div>
  {cards_grid}
  <div class="sec">📊 Harmonik Performansı ({len(pattern_raw)})</div>
  <div class="tablewrap">{pattern_table}</div>
  <div class="sec">🟢 Açık Pozisyonlar ({len(open_raw)})</div>
  <div class="tablewrap">{open_table}</div>
  <div class="sec dim">📋 Son Kapanan Trade'ler ({len(closed_raw)})</div>
  <div class="tablewrap">{closed_table}</div>
  <div class="foot">Güncelleme: {now} · {refresh} sn'de bir otomatik yenilenir</div>
</div></body></html>"""


def _dir(direction: str) -> tuple[str, str]:
    return ("BULL ▲", "g") if direction == "bull" else ("BEAR ▼", "r")


def _rr_cls(rr: float) -> str:
    return "g" if rr >= 1.5 else "r" if rr < 1.0 else "d"


def _sym_link(setup_id, symbol) -> str:
    """Parite hücresi → setup grafiği linki."""
    return (f'<a href="/chart?id={int(setup_id)}" '
            f'style="color:#42a5f5;text-decoration:none;font-weight:600">{_e(symbol)} ›</a>')


def _open_table(rows: list) -> str:
    if not rows:
        return '<div class="empty">Açık pozisyon yok.</div>'
    head = ("<table><thead><tr>"
            '<th class="l">Parite</th><th>TF</th><th class="l">Pattern</th><th>Yön</th>'
            "<th>Entry</th><th>Stop</th><th>Hedef</th><th>R:R</th>"
            "<th>Pozisyon</th><th>Lev</th><th>Açıldı</th><th>Yaş</th>"
            "</tr></thead><tbody>")
    body = []
    for r in rows:
        dir_txt, dir_cls = _dir(r["direction"])
        rr = _rr(r["entry_price"], r["stop_price"], r["tp1_price"])
        body.append(
            f'<tr><td class="l">{_sym_link(r["setup_id"], r["symbol"])}</td>'
            f'<td>{_e(r["interval"])}</td>'
            f'<td class="l">{_e(r["pattern"])}</td>'
            f'<td class="{dir_cls}">{dir_txt}</td>'
            f'<td>{_fmt_price(r["entry_price"])}</td><td>{_fmt_price(r["stop_price"])}</td>'
            f'<td>{_fmt_price(r["tp1_price"])}</td>'
            f'<td class="{_rr_cls(rr)}">{rr:.2f}</td>'
            f'<td>${r["position_usd"]:.0f}</td><td>{r["leverage"]:.0f}x</td>'
            f'<td class="d">{_fmt_ts(r["opened_at"])}</td>'
            f'<td class="d">{_fmt_age(r["opened_at"])}</td></tr>'
        )
    return head + "".join(body) + "</tbody></table>"


def _closed_table(rows: list) -> str:
    if not rows:
        return '<div class="empty">Henüz kapanan trade yok.</div>'
    head = ("<table><thead><tr>"
            '<th class="l">Parite</th><th>TF</th><th class="l">Pattern</th><th>Yön</th>'
            "<th>Entry</th><th>R:R</th><th>Exit</th><th>Sonuç</th><th>P&amp;L</th>"
            "<th>Lev</th><th>Kapandı</th>"
            "</tr></thead><tbody>")
    body = []
    for r in rows:
        dir_txt, dir_cls = _dir(r["direction"])
        rr = _rr(r["entry_price"], r["stop_price"], r["tp1_price"])
        pnl = r["pnl_usd"] or 0
        out = r["outcome"] or "—"
        out_cls = {"TP": "g", "STOP": "r"}.get(r["outcome"], "d")
        pnl_cls = "g" if pnl > 0 else "r" if pnl < 0 else "d"
        body.append(
            f'<tr><td class="l">{_sym_link(r["setup_id"], r["symbol"])}</td>'
            f'<td>{_e(r["interval"])}</td>'
            f'<td class="l">{_e(r["pattern"])}</td>'
            f'<td class="{dir_cls}">{dir_txt}</td>'
            f'<td>{_fmt_price(r["entry_price"])}</td>'
            f'<td class="{_rr_cls(rr)}">{rr:.2f}</td>'
            f'<td>{_fmt_price(r["exit_price"])}</td>'
            f'<td class="{out_cls}">{_e(out)}</td>'
            f'<td class="{pnl_cls}">{"+" if pnl >= 0 else ""}${pnl:.2f}</td>'
            f'<td>{r["leverage"]:.0f}x</td>'
            f'<td class="d">{_fmt_ts(r["closed_at"])}</td></tr>'
        )
    return head + "".join(body) + "</tbody></table>"


def make_handler(db_path, user: str, password: str, refresh: int):
    expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "harmonik-web"

        def _auth_ok(self) -> bool:
            got = self.headers.get("Authorization", "")
            return secrets.compare_digest(got, expected)

        def _deny(self) -> None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Harmonik"')
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Yetki gerekli.".encode("utf-8"))

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _setup_id_param(self, qs: dict) -> int | None:
            try:
                return int(qs.get("id", [""])[0])
            except (ValueError, TypeError):
                return None

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if not self._auth_ok():
                self._deny()
                return
            parsed = urlparse(self.path)
            path = parsed.path
            qs = parse_qs(parsed.query)
            try:
                if path in ("/", "/index.html"):
                    self._send(200, render_dashboard(db_path, refresh).encode("utf-8"),
                               "text/html; charset=utf-8")
                elif path == "/chart":
                    sid = self._setup_id_param(qs)
                    if sid is None:
                        self._send(400, b"id gerekli", "text/plain; charset=utf-8")
                        return
                    self._send(200, chart_page(db_path, sid).encode("utf-8"),
                               "text/html; charset=utf-8")
                elif path == "/chart.png":
                    sid = self._setup_id_param(qs)
                    png = render_chart_png(db_path, sid) if sid is not None else None
                    if png is None:
                        self.send_response(404)
                        self.end_headers()
                        return
                    self._send(200, png, "image/png")
                else:
                    self.send_response(404)
                    self.end_headers()
            except Exception:
                log.exception("istek hatası: %s", self.path)
                self.send_response(500)
                self.end_headers()

        def log_message(self, fmt, *args) -> None:
            log.debug("%s - %s", self.address_string(), fmt % args)

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="terminal-web",
        description="Harmonik paper trade mobil web dashboard (salt-okunur).",
    )
    ap.add_argument("--host", default=os.environ.get("WEB_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("WEB_PORT", "8080")))
    ap.add_argument("--user", default=os.environ.get("WEB_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("WEB_PASS", ""))
    ap.add_argument("--refresh", type=int,
                    default=int(os.environ.get("WEB_REFRESH", "10")),
                    help="Otomatik yenileme süresi (sn).")
    ap.add_argument("--db", default=str(DB_PATH), help="terminal.db yolu.")
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)

    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s [%(levelname)s] %(message)s")

    if not args.password:
        raise SystemExit(
            "Şifre gerekli. WEB_PASS ortam değişkeni ya da --password ile ver.\n"
            "Örnek: WEB_USER=admin WEB_PASS=gizli python -m terminal.web.server"
        )

    handler = make_handler(args.db, args.user, args.password, args.refresh)
    httpd = ThreadingHTTPServer((args.host, args.port), handler)
    log.info("Web dashboard: http://%s:%d  (kullanıcı: %s, db: %s)",
             args.host, args.port, args.user, args.db)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Kapatılıyor...")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
