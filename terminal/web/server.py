"""Mobil-uyumlu paper trade web dashboard.

Python stdlib http.server üstünde çalışır — FastAPI/Flask gibi ekstra bağımlılık
yok (yalnızca jinja2, o da zaten kurulu). Aynı terminal.db'yi SALT-OKUNUR okur;
tracker'dan tamamen bağımsız ayrı bir servistir, yazma yapmaz. HTTP Basic Auth
ile korunur. Sayfa ~10 sn'de bir otomatik yenilenir.

Kullanım:
    WEB_USER=admin WEB_PASS=gizli python -m terminal.web.server --port 8080
    # veya
    python -m terminal.web.server --user admin --password gizli --port 8080

Telefondan:  http://<VPS_IP>:8080  → kullanıcı adı + şifre sorar.
"""
from __future__ import annotations

import argparse
import base64
import logging
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jinja2 import Template

from terminal.config import DB_PATH

log = logging.getLogger(__name__)

TZ = timezone(timedelta(hours=3))  # IST — UI ile tutarlı


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


PAGE = Template("""<!doctype html>
<html lang="tr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{{ refresh }}">
<title>Harmonik · Paper</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; background:#0e0e10; color:#e6e6ea;
         font-family:-apple-system,'Segoe UI',Roboto,sans-serif; font-size:14px; }
  .wrap { max-width:980px; margin:0 auto; padding:12px; }
  h1 { font-size:18px; color:#d4a72c; margin:4px 0 12px; }
  .muted { color:#888; font-size:12px; }
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
  td:first-child, th:first-child, td.l, th.l { text-align:left; }
  tr:nth-child(even) td { background:#121217; }
  .g { color:#4caf50; } .r { color:#ef5350; } .d { color:#888; }
  .bull { color:#4caf50; font-weight:600; } .bear { color:#ef5350; font-weight:600; }
  .empty { padding:18px; text-align:center; color:#888; }
  .foot { margin-top:16px; color:#666; font-size:11px; text-align:center; }
</style></head>
<body><div class="wrap">
  <h1>💼 Harmonik — Paper Trade</h1>
  <div class="cards">
    <div class="card"><div class="lbl">Equity</div>
      <div class="val {{ 'g' if equity>=initial else 'r' }}">${{ '%.2f'|format(equity) }}</div></div>
    <div class="card"><div class="lbl">Toplam P&L</div>
      <div class="val {{ pnl_cls }}">{{ '+' if total_pnl>=0 else '' }}${{ '%.2f'|format(total_pnl) }}</div></div>
    <div class="card"><div class="lbl">P&L %</div>
      <div class="val {{ pnl_cls }}">{{ '+' if pnl_pct>=0 else '' }}{{ '%.1f'|format(pnl_pct) }}%</div></div>
    <div class="card"><div class="lbl">Win Rate</div>
      <div class="val {{ wr_cls }}">{{ wr_txt }}</div></div>
    <div class="card"><div class="lbl">Trade</div><div class="val">{{ total_trades }}</div></div>
    <div class="card"><div class="lbl">TP</div><div class="val g">{{ tp }}</div></div>
    <div class="card"><div class="lbl">STOP</div><div class="val r">{{ stop }}</div></div>
    <div class="card"><div class="lbl">Açık</div><div class="val" style="color:#42a5f5">{{ open_rows|length }}</div></div>
  </div>

  <div class="sec">🟢 Açık Pozisyonlar ({{ open_rows|length }})</div>
  <div class="tablewrap">
  {% if open_rows %}
    <table><thead><tr>
      <th class="l">Parite</th><th>TF</th><th class="l">Pattern</th><th>Yön</th>
      <th>Entry</th><th>Stop</th><th>TP1</th><th>R:R</th>
      <th>Pozisyon</th><th>Lev</th><th>Açıldı</th><th>Yaş</th>
    </tr></thead><tbody>
    {% for t in open_rows %}
      <tr>
        <td class="l">{{ t.symbol }}</td><td>{{ t.interval }}</td>
        <td class="l">{{ t.pattern }}</td>
        <td class="{{ t.dir_cls }}">{{ t.dir_txt }}</td>
        <td>{{ t.entry }}</td><td>{{ t.stop }}</td><td>{{ t.tp1 }}</td>
        <td class="{{ t.rr_cls }}">{{ t.rr }}</td>
        <td>${{ t.pos }}</td><td>{{ t.lev }}x</td>
        <td class="d">{{ t.opened }}</td><td class="d">{{ t.age }}</td>
      </tr>
    {% endfor %}
    </tbody></table>
  {% else %}<div class="empty">Açık pozisyon yok.</div>{% endif %}
  </div>

  <div class="sec dim">📋 Son Kapanan Trade'ler ({{ closed_rows|length }})</div>
  <div class="tablewrap">
  {% if closed_rows %}
    <table><thead><tr>
      <th class="l">Parite</th><th>TF</th><th class="l">Pattern</th><th>Yön</th>
      <th>Entry</th><th>R:R</th><th>Exit</th><th>Sonuç</th><th>P&L</th><th>Lev</th><th>Kapandı</th>
    </tr></thead><tbody>
    {% for t in closed_rows %}
      <tr>
        <td class="l">{{ t.symbol }}</td><td>{{ t.interval }}</td>
        <td class="l">{{ t.pattern }}</td>
        <td class="{{ t.dir_cls }}">{{ t.dir_txt }}</td>
        <td>{{ t.entry }}</td><td class="{{ t.rr_cls }}">{{ t.rr }}</td>
        <td>{{ t.exit }}</td>
        <td class="{{ t.out_cls }}">{{ t.outcome }}</td>
        <td class="{{ t.pnl_cls }}">{{ t.pnl }}</td>
        <td>{{ t.lev }}x</td><td class="d">{{ t.closed }}</td>
      </tr>
    {% endfor %}
    </tbody></table>
  {% else %}<div class="empty">Henüz kapanan trade yok.</div>{% endif %}
  </div>

  <div class="foot">Güncelleme: {{ now }} · {{ refresh }} sn'de bir otomatik yenilenir</div>
</div></body></html>""")


def _connect_ro(db_path) -> sqlite3.Connection:
    """terminal.db'ye salt-okunur bağlan (writer'ı kilitlemez, WAL uyumlu)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def render_dashboard(db_path, refresh: int) -> str:
    ctx: dict = {"refresh": refresh, "now": datetime.now(tz=TZ).strftime("%H:%M:%S")}
    try:
        conn = _connect_ro(db_path)
    except sqlite3.Error:
        # DB henüz yok → boş dashboard
        ctx.update(_empty_account(), open_rows=[], closed_rows=[])
        return PAGE.render(**ctx)
    try:
        acc = conn.execute(
            "SELECT initial_equity, current_equity, total_trades, tp_count, "
            "stop_count, total_pnl FROM paper_account WHERE id = 1"
        ).fetchone()
        open_raw = conn.execute(
            "SELECT symbol, interval, pattern, direction, entry_price, stop_price, "
            "tp1_price, position_usd, leverage, opened_at FROM paper_trades "
            "WHERE closed_at IS NULL ORDER BY opened_at DESC"
        ).fetchall()
        closed_raw = conn.execute(
            "SELECT symbol, interval, pattern, direction, entry_price, stop_price, "
            "tp1_price, exit_price, outcome, pnl_usd, leverage, closed_at "
            "FROM paper_trades WHERE closed_at IS NOT NULL "
            "ORDER BY closed_at DESC LIMIT 50"
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        ctx.update(_empty_account(), open_rows=[], closed_rows=[])
        return PAGE.render(**ctx)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if acc:
        initial, equity, total_trades, tp, stop, total_pnl = (
            acc["initial_equity"], acc["current_equity"], acc["total_trades"],
            acc["tp_count"], acc["stop_count"], acc["total_pnl"],
        )
    else:
        initial, equity, total_trades, tp, stop, total_pnl = 1000.0, 1000.0, 0, 0, 0, 0.0

    decided = tp + stop
    wr = (tp / decided * 100) if decided else 0
    pnl_pct = ((equity - initial) / initial * 100) if initial else 0

    ctx.update(
        initial=initial, equity=equity, total_pnl=total_pnl, pnl_pct=pnl_pct,
        total_trades=total_trades, tp=tp, stop=stop,
        pnl_cls=("g" if total_pnl > 0 else "r" if total_pnl < 0 else "d"),
        wr_txt=(f"{wr:.1f}%" if decided else "—"),
        wr_cls=("g" if decided and wr >= 60 else "r" if decided and wr < 45 else "d"),
        open_rows=[_open_row(r) for r in open_raw],
        closed_rows=[_closed_row(r) for r in closed_raw],
    )
    return PAGE.render(**ctx)


def _empty_account() -> dict:
    return dict(initial=1000.0, equity=1000.0, total_pnl=0.0, pnl_pct=0.0,
                total_trades=0, tp=0, stop=0, pnl_cls="d", wr_txt="—", wr_cls="d")


def _dir(direction: str) -> tuple[str, str]:
    return ("BULL ▲", "bull") if direction == "bull" else ("BEAR ▼", "bear")


def _rr_cls(rr: float) -> str:
    return "g" if rr >= 1.5 else "r" if rr < 1.0 else "d"


def _open_row(r: sqlite3.Row) -> dict:
    dir_txt, dir_cls = _dir(r["direction"])
    rr = _rr(r["entry_price"], r["stop_price"], r["tp1_price"])
    return dict(
        symbol=r["symbol"], interval=r["interval"], pattern=r["pattern"],
        dir_txt=dir_txt, dir_cls=dir_cls,
        entry=_fmt_price(r["entry_price"]), stop=_fmt_price(r["stop_price"]),
        tp1=_fmt_price(r["tp1_price"]), rr=f"{rr:.2f}", rr_cls=_rr_cls(rr),
        pos=f"{r['position_usd']:.0f}", lev=f"{r['leverage']:.0f}",
        opened=_fmt_ts(r["opened_at"]), age=_fmt_age(r["opened_at"]),
    )


def _closed_row(r: sqlite3.Row) -> dict:
    dir_txt, dir_cls = _dir(r["direction"])
    rr = _rr(r["entry_price"], r["stop_price"], r["tp1_price"])
    pnl = r["pnl_usd"] or 0
    return dict(
        symbol=r["symbol"], interval=r["interval"], pattern=r["pattern"],
        dir_txt=dir_txt, dir_cls=dir_cls,
        entry=_fmt_price(r["entry_price"]), rr=f"{rr:.2f}", rr_cls=_rr_cls(rr),
        exit=_fmt_price(r["exit_price"]),
        outcome=r["outcome"] or "—",
        out_cls={"TP": "g", "STOP": "r"}.get(r["outcome"], "d"),
        pnl=f"{'+' if pnl >= 0 else ''}${pnl:.2f}",
        pnl_cls=("g" if pnl > 0 else "r" if pnl < 0 else "d"),
        lev=f"{r['leverage']:.0f}", closed=_fmt_ts(r["closed_at"]),
    )


def make_handler(db_path, user: str, password: str, refresh: int):
    expected = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()

    class Handler(BaseHTTPRequestHandler):
        server_version = "harmonik-web"

        def _auth_ok(self) -> bool:
            got = self.headers.get("Authorization", "")
            # sabit-zamanlı karşılaştırma (timing attack'a karşı)
            return secrets.compare_digest(got, expected)

        def _deny(self) -> None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Harmonik"')
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("Yetki gerekli.".encode("utf-8"))

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            if not self._auth_ok():
                self._deny()
                return
            if self.path not in ("/", "/index.html"):
                self.send_response(404)
                self.end_headers()
                return
            try:
                html = render_dashboard(db_path, refresh)
                body = html.encode("utf-8")
            except Exception:
                log.exception("dashboard render hatası")
                self.send_response(500)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args) -> None:  # sessiz: erişim log spam'i yok
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
