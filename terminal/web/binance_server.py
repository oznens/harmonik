"""Binance testnet dashboard — binance_trades tablosunu gösteren mobil web (salt-okunur).

okx_server'ın Binance karşılığı. binance_trades + canlı testnet bakiyesini okur.
Ayrı port (varsayılan 8091).

Kullanım:
    BINANCE_API_KEY=.. BINANCE_SECRET=.. WEB_PASS=gizli \\
    python -m terminal.web.binance_server --port 8091
"""
from __future__ import annotations

import argparse
import base64
import html as html_mod
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from terminal.config import DB_PATH

log = logging.getLogger(__name__)
TZ = timezone(timedelta(hours=3))


def _e(s) -> str:
    return html_mod.escape(str(s))


def _fmt_ts(ms) -> str:
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%d.%m %H:%M")


def _fmt_px(p) -> str:
    if p is None:
        return "—"
    p = float(p)
    return f"{p:,.4f}" if p >= 1000 else f"{p:.6g}"


STYLE = """
:root{color-scheme:dark}*{box-sizing:border-box}
body{margin:0;background:#0e0e10;color:#e6e6ea;font-family:-apple-system,'Segoe UI',Roboto,sans-serif;font-size:14px}
.wrap{max-width:1000px;margin:0 auto;padding:12px}
h1{font-size:18px;color:#f0b90b;margin:4px 0 12px}
.cards{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px}
.card{flex:1 1 90px;background:#1a1a1f;border:1px solid #2a2a32;border-radius:8px;padding:8px 10px;text-align:center}
.card .lbl{color:#888;font-size:10px;text-transform:uppercase}
.card .val{font-size:17px;font-weight:700;margin-top:2px}
.sec{color:#f0b90b;font-weight:700;margin:14px 0 6px}
.sec.dim{color:#888}
.tablewrap{overflow-x:auto;border:1px solid #2a2a32;border-radius:8px}
table{border-collapse:collapse;width:100%;min-width:560px;font-size:13px}
th,td{padding:7px 9px;text-align:right;white-space:nowrap;border-bottom:1px solid #20202a}
th{background:#15151a;color:#9aa;font-weight:600;position:sticky;top:0}
td.l,th.l{text-align:left}
tr:nth-child(even) td{background:#121217}
.g{color:#4caf50}.r{color:#ef5350}.d{color:#888}
.empty{padding:18px;text-align:center;color:#888}
.foot{margin-top:16px;color:#666;font-size:11px;text-align:center}
table.sortable th{cursor:pointer;user-select:none}
table.sortable th:hover{color:#cdd0d6}
table.sortable th.asc::after{content:" \\2191";color:#f0b90b;font-size:10px}
table.sortable th.desc::after{content:" \\2193";color:#f0b90b;font-size:10px}
"""


def _dir(d):
    return ("BULL ▲", "g") if d == "bull" else ("BEAR ▼", "r")


def _connect(db):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)


def _live_equity() -> str:
    """Binance testnet'ten kullanılabilir USDT (availableBalance)."""
    try:
        from terminal.data.binance_trade import BinanceTestClient
        c = BinanceTestClient()
        if not c.has_credentials():
            return "—"
        av = c.free_usdt()
        c.close()
        return f"{float(av):,.0f}" if av is not None else "—"
    except Exception:
        return "—"


def render(db_path, refresh: int) -> str:
    rows_open, rows_closed, pat_rows = [], [], []
    tp = sl = 0
    total_pnl = 0.0
    try:
        conn = _connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows_open = conn.execute(
                "SELECT o.symbol,o.interval,o.pattern,o.direction,o.entry_px,o.stop_px,"
                "o.tp_px,o.leverage,o.notional_usd,o.opened_at,o.state,"
                "s.q_score,s.confluence_score "
                "FROM binance_trades o LEFT JOIN setups s ON s.id=o.setup_id "
                "WHERE o.closed_at IS NULL ORDER BY o.opened_at DESC").fetchall()
            rows_closed = conn.execute(
                "SELECT o.symbol,o.interval,o.pattern,o.direction,o.entry_px,o.exit_px,"
                "o.leverage,o.pnl_usd,o.state,o.closed_at,s.q_score,s.confluence_score "
                "FROM binance_trades o LEFT JOIN setups s ON s.id=o.setup_id "
                "WHERE o.closed_at IS NOT NULL ORDER BY o.closed_at DESC LIMIT 100").fetchall()
            pat_rows = conn.execute(
                "SELECT pattern, "
                "SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END) tp, "
                "SUM(CASE WHEN pnl_usd<0 THEN 1 ELSE 0 END) sl, "
                "SUM(COALESCE(pnl_usd,0)) pnl "
                "FROM binance_trades WHERE closed_at IS NOT NULL "
                "GROUP BY pattern ORDER BY (tp+sl) DESC").fetchall()
            acc = conn.execute(
                "SELECT SUM(CASE WHEN pnl_usd>0 THEN 1 ELSE 0 END),"
                "SUM(CASE WHEN pnl_usd<0 THEN 1 ELSE 0 END),"
                "SUM(COALESCE(pnl_usd,0)) FROM binance_trades WHERE closed_at IS NOT NULL"
            ).fetchone()
            if acc:
                tp, sl, total_pnl = acc[0] or 0, acc[1] or 0, acc[2] or 0.0
        finally:
            conn.close()
    except sqlite3.Error as e:
        log.warning("Binance DB okuma: %s", e)

    decided = tp + sl
    wr = (tp / decided * 100) if decided else 0
    pnl_cls = "g" if total_pnl > 0 else "r" if total_pnl < 0 else "d"
    now = datetime.now(tz=TZ).strftime("%H:%M:%S")
    equity = _live_equity()

    cards = f"""<div class="cards">
      <div class="card"><div class="lbl">Kullanılabilir USDT</div><div class="val">${equity}</div></div>
      <div class="card"><div class="lbl">Toplam P&amp;L</div><div class="val {pnl_cls}">{'+' if total_pnl>=0 else ''}${total_pnl:.2f}</div></div>
      <div class="card"><div class="lbl">Win Rate</div><div class="val {'g' if wr>=50 else 'r'}">{wr:.0f}%</div></div>
      <div class="card"><div class="lbl">TP</div><div class="val g">{tp}</div></div>
      <div class="card"><div class="lbl">STOP</div><div class="val r">{sl}</div></div>
      <div class="card"><div class="lbl">Açık</div><div class="val" style="color:#f0b90b">{len(rows_open)}</div></div>
    </div>"""

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>Binance Testnet · Harmonik</title><style>{STYLE}</style></head>
<body><div class="wrap">
<h1>🟡 Binance Testnet — Harmonik (gerçek testnet borsa)</h1>
{cards}
<div class="sec">📊 Harmonik Performansı ({len(pat_rows)})</div>
<div class="tablewrap">{_pattern_table(pat_rows)}</div>
<div class="sec">🟢 Açık Pozisyonlar ({len(rows_open)})</div>
<div class="tablewrap">{_open_table(rows_open)}</div>
<div class="sec dim">📋 Kapanan İşlemler ({len(rows_closed)})</div>
<div class="tablewrap">{_closed_table(rows_closed)}</div>
<div class="foot">Güncelleme: {now} · {refresh} sn · başlıklara tıkla sırala</div>
</div>
<script>
document.querySelectorAll('table.sortable').forEach(function(tb){{
 var h=tb.tHead.rows[0].cells;Array.prototype.forEach.call(h,function(th,ci){{
  th.onclick=function(){{var rows=Array.prototype.slice.call(tb.tBodies[0].rows);
   var asc=!th.classList.contains('asc');
   Array.prototype.forEach.call(h,function(x){{x.classList.remove('asc','desc')}});
   th.classList.add(asc?'asc':'desc');
   rows.sort(function(a,b){{var x=a.cells[ci].getAttribute('data-s')||a.cells[ci].textContent.trim();
    var y=b.cells[ci].getAttribute('data-s')||b.cells[ci].textContent.trim();
    var nx=parseFloat(x.replace(/[$%,x]/g,'')),ny=parseFloat(y.replace(/[$%,x]/g,''));
    if(!isNaN(nx)&&!isNaN(ny)){{x=nx;y=ny}}
    return (x<y?-1:x>y?1:0)*(asc?1:-1)}});
   rows.forEach(function(r){{tb.tBodies[0].appendChild(r)}});}};}});}});
</script></body></html>"""


def _score(v):
    if v is None:
        return '<td class="d">—</td>'
    v = int(v)
    return f'<td class="{"g" if v>=70 else "r" if v<40 else "d"}">{v}</td>'


def _pattern_table(rows):
    if not rows:
        return '<div class="empty">Kapanan işlem yok.</div>'
    h = ('<table class="sortable"><thead><tr><th class="l">Pattern</th><th>TP</th>'
         '<th>SL</th><th>WR</th><th>P&amp;L</th></tr></thead><tbody>')
    b = []
    for r in rows:
        tp, sl = r["tp"] or 0, r["sl"] or 0
        wr = (tp / (tp + sl) * 100) if (tp + sl) else 0
        pnl = r["pnl"] or 0
        b.append(f'<tr><td class="l">{_e(r["pattern"])}</td><td class="g">{tp}</td>'
                 f'<td class="r">{sl}</td><td class="{"g" if wr>=50 else "r"}">{wr:.0f}%</td>'
                 f'<td class="{"g" if pnl>=0 else "r"}" data-s="{pnl}">{"+" if pnl>=0 else ""}${pnl:.2f}</td></tr>')
    return h + "".join(b) + "</tbody></table>"


def _open_table(rows):
    if not rows:
        return '<div class="empty">Açık pozisyon yok.</div>'
    h = ('<table class="sortable"><thead><tr><th class="l">Parite</th><th>TF</th>'
         '<th class="l">Pattern</th><th>Yön</th><th>Entry</th><th>Stop</th><th>Hedef</th>'
         '<th>Lev</th><th>Notional</th><th>Q</th><th>Conf</th><th>Açıldı</th>'
         '</tr></thead><tbody>')
    b = []
    for r in rows:
        dt, dc = _dir(r["direction"])
        b.append(f'<tr><td class="l">{_e(r["symbol"])}</td><td>{_e(r["interval"])}</td>'
                 f'<td class="l">{_e(r["pattern"])}</td><td class="{dc}">{dt}</td>'
                 f'<td>{_fmt_px(r["entry_px"])}</td><td>{_fmt_px(r["stop_px"])}</td>'
                 f'<td>{_fmt_px(r["tp_px"])}</td><td>{r["leverage"]:.0f}x</td>'
                 f'<td data-s="{r["notional_usd"]}">${r["notional_usd"]:.0f}</td>'
                 f'{_score(r["q_score"])}{_score(r["confluence_score"])}'
                 f'<td class="d" data-s="{r["opened_at"] or 0}">{_fmt_ts(r["opened_at"])}</td></tr>')
    return h + "".join(b) + "</tbody></table>"


def _closed_table(rows):
    if not rows:
        return '<div class="empty">Kapanan işlem yok.</div>'
    h = ('<table class="sortable"><thead><tr><th class="l">Parite</th><th>TF</th>'
         '<th class="l">Pattern</th><th>Yön</th><th>Entry</th><th>Exit</th><th>Lev</th>'
         '<th>Q</th><th>Conf</th><th>P&amp;L</th><th>Sonuç</th><th>Kapandı</th>'
         '</tr></thead><tbody>')
    b = []
    for r in rows:
        dt, dc = _dir(r["direction"])
        pnl = r["pnl_usd"] or 0
        res = "TP" if pnl > 0 else "STOP" if pnl < 0 else r["state"]
        rc = "g" if pnl > 0 else "r" if pnl < 0 else "d"
        b.append(f'<tr><td class="l">{_e(r["symbol"])}</td><td>{_e(r["interval"])}</td>'
                 f'<td class="l">{_e(r["pattern"])}</td><td class="{dc}">{dt}</td>'
                 f'<td>{_fmt_px(r["entry_px"])}</td><td>{_fmt_px(r["exit_px"])}</td>'
                 f'<td>{r["leverage"]:.0f}x</td>'
                 f'{_score(r["q_score"])}{_score(r["confluence_score"])}'
                 f'<td class="{rc}" data-s="{pnl}">{"+" if pnl>=0 else ""}${pnl:.2f}</td>'
                 f'<td class="{rc}">{res}</td>'
                 f'<td class="d" data-s="{r["closed_at"] or 0}">{_fmt_ts(r["closed_at"])}</td></tr>')
    return h + "".join(b) + "</tbody></table>"


def make_handler(db_path, user, password, refresh):
    import secrets
    expect = base64.b64encode(f"{user}:{password}".encode()).decode()

    class H(BaseHTTPRequestHandler):
        def _auth(self):
            hdr = self.headers.get("Authorization", "")
            return hdr.startswith("Basic ") and secrets.compare_digest(hdr[6:], expect)

        def do_GET(self):  # noqa: N802
            if not self._auth():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="binance"')
                self.end_headers()
                return
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            try:
                body = render(db_path, refresh).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                log.exception("istek hatası")
                self.send_response(500)
                self.end_headers()

        def log_message(self, *a):
            pass
    return H


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="terminal-binance-web",
                                 description="Binance testnet dashboard (salt-okunur)")
    ap.add_argument("--host", default=os.environ.get("WEB_HOST", "0.0.0.0"))
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("BINANCE_WEB_PORT", "8091")))
    ap.add_argument("--user", default=os.environ.get("WEB_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("WEB_PASS", ""))
    ap.add_argument("--refresh", type=int, default=int(os.environ.get("WEB_REFRESH", "15")))
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--log-level", default="INFO")
    args = ap.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format="%(asctime)s [%(levelname)s] %(message)s")
    if not args.password:
        raise SystemExit("Şifre gerekli: WEB_PASS env ya da --password")
    httpd = ThreadingHTTPServer((args.host, args.port),
                                make_handler(args.db, args.user, args.password, args.refresh))
    log.info("Binance web dashboard: http://%s:%d (db: %s)", args.host, args.port, args.db)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
