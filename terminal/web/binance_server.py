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
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

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
a.tlink{color:inherit;text-decoration:none}
a.tlink:hover{color:#f0b90b;text-decoration:underline}
.tcards{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.tcard{flex:1 1 150px;min-width:148px;background:#15171c;border:1px solid #2a2a32;border-left:3px solid #4caf50;border-radius:8px;padding:9px 11px;text-decoration:none;color:#e6e6ea;display:block}
.tcard:hover{border-color:#f0b90b;background:#1c1f26}
.tcard .h{display:flex;justify-content:space-between;align-items:center}
.tcard .sym{font-size:14px;font-weight:700}
.tcard .tf{font-size:10px;color:#aaa;background:#252833;padding:1px 6px;border-radius:4px}
.tcard .pat{font-size:11px;color:#9aa;margin:3px 0}
.tcard .pnl{font-size:18px;font-weight:800;margin:2px 0}
.tcard .px{font-size:10px;color:#888}.tcard .dt{font-size:10px;color:#666;margin-top:3px}
"""


def _dir(d):
    return ("BULL ▲", "g") if d == "bull" else ("BEAR ▼", "r")


_TV_TF = {"15m": "15", "30m": "30", "60m": "60", "1h": "60", "2h": "120",
          "4h": "240", "8h": "480", "1d": "1D"}


def _tv(symbol, interval):
    """TradingView grafik linki (Binance perp) — karta/satıra tıklayınca açılır."""
    return (f"https://www.tradingview.com/chart/?symbol=BINANCE:"
            f"{_e(symbol)}.P&interval={_TV_TF.get(interval, '15')}")


def _best_cards(rows):
    """O güne kadarki en iyi N kapanan işlem — MEXC kartı stili (tıklanabilir)."""
    if not rows:
        return '<div class="empty">Henüz kapanan işlem yok.</div>'
    out = ['<div class="tcards">']
    for r in rows:
        dt, dc = _dir(r["direction"])
        pnl = r["pnl_usd"] or 0
        out.append(
            f'<a class="tcard" href="{_trade_link(r["setup_id"])}" '
            f'title="İşlem grafiğini aç (entry/SL/TP)">'
            f'<div class="h"><span class="sym {dc}">{_e(r["symbol"])}</span>'
            f'<span class="tf">{_e(r["interval"])}</span></div>'
            f'<div class="pat">{_e(r["pattern"])} · <span class="{dc}">{dt}</span></div>'
            f'<div class="pnl g">+${pnl:.2f}</div>'
            f'<div class="px">Entry {_fmt_px(r["entry_px"])} → TP {_fmt_px(r["tp_px"])}</div>'
            f'<div class="dt">{_fmt_ts(r["closed_at"])}</div></a>')
    out.append("</div>")
    return "".join(out)


def _connect(db):
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)


def _live_account() -> dict:
    """Binance testnet'ten gerçek hesap özeti + açık pozisyon uPnL'leri.

    Returns: {wallet, margin, avail, upnl, positions:{symbol:{upnl,mark}}} —
    okunamazsa değerler None.
    """
    out = {"wallet": None, "margin": None, "avail": None, "upnl": None,
           "positions": {}}
    try:
        from terminal.data.binance_trade import BinanceTestClient
        c = BinanceTestClient()
        if not c.has_credentials():
            return out
        a = c.account()
        out["wallet"] = float(a.get("totalWalletBalance") or 0)
        out["margin"] = float(a.get("totalMarginBalance") or 0)
        out["avail"] = float(a.get("availableBalance") or 0)
        out["upnl"] = float(a.get("totalUnrealizedProfit") or 0)
        for p in c.positions():
            try:
                out["positions"][p["symbol"]] = {
                    "upnl": float(p.get("unRealizedProfit") or 0),
                    "mark": float(p.get("markPrice") or 0),
                }
            except (ValueError, TypeError, KeyError):
                pass
        c.close()
    except Exception:
        pass
    return out


def _m(v) -> str:
    return f"${v:,.2f}" if v is not None else "—"


def render(db_path, refresh: int) -> str:
    rows_open, rows_closed, pat_rows, best5 = [], [], [], []
    tp = sl = 0
    total_pnl = 0.0
    try:
        conn = _connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows_open = conn.execute(
                "SELECT o.setup_id,o.symbol,o.interval,o.pattern,o.direction,o.entry_px,o.stop_px,"
                "o.tp_px,o.leverage,o.notional_usd,o.opened_at,o.state,"
                "s.q_score,s.confluence_score "
                "FROM binance_trades o LEFT JOIN setups s ON s.id=o.setup_id "
                "WHERE o.closed_at IS NULL ORDER BY o.opened_at DESC").fetchall()
            rows_closed = conn.execute(
                "SELECT o.setup_id,o.symbol,o.interval,o.pattern,o.direction,o.entry_px,o.exit_px,"
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
            best5 = conn.execute(
                "SELECT setup_id,symbol,interval,pattern,direction,entry_px,tp_px,stop_px,"
                "pnl_usd,closed_at FROM binance_trades "
                "WHERE state='closed' AND pnl_usd IS NOT NULL AND pnl_usd>0 "
                "ORDER BY pnl_usd DESC LIMIT 5").fetchall()
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
    acct = _live_account()
    upnl = acct["upnl"]
    upnl_cls = "g" if (upnl or 0) > 0 else "r" if (upnl or 0) < 0 else "d"
    upnl_str = "—" if upnl is None else f"{'+' if upnl >= 0 else '-'}${abs(upnl):,.2f}"

    cards = f"""<div class="cards">
      <div class="card"><div class="lbl">Cüzdan</div><div class="val">{_m(acct['wallet'])}</div></div>
      <div class="card"><div class="lbl">Equity</div><div class="val">{_m(acct['margin'])}</div></div>
      <div class="card"><div class="lbl">Kullanılabilir</div><div class="val">{_m(acct['avail'])}</div></div>
      <div class="card"><div class="lbl">Açık P&amp;L</div><div class="val {upnl_cls}">{upnl_str}</div></div>
      <div class="card"><div class="lbl">Kapalı P&amp;L</div><div class="val {pnl_cls}">{'+' if total_pnl>=0 else ''}${total_pnl:.2f}</div></div>
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
<div class="sec">🏆 En İyi 5 İşlem (o güne kadarki)</div>
{_best_cards(best5)}
<div class="sec">📊 Harmonik Performansı ({len(pat_rows)})</div>
<div class="tablewrap">{_pattern_table(pat_rows)}</div>
<div class="sec">🟢 Açık Pozisyonlar ({len(rows_open)})</div>
<div class="tablewrap">{_open_table(rows_open, acct["positions"])}</div>
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


def _open_table(rows, live_pos=None):
    live_pos = live_pos or {}
    if not rows:
        return '<div class="empty">Açık pozisyon yok.</div>'
    h = ('<table class="sortable"><thead><tr><th class="l">Parite</th><th>TF</th>'
         '<th class="l">Pattern</th><th>Yön</th><th>Entry</th><th>Mark</th><th>Stop</th>'
         '<th>Hedef</th><th>Canlı P&amp;L</th><th>Lev</th><th>Notional</th><th>Q</th>'
         '<th>Conf</th><th>Açıldı</th></tr></thead><tbody>')
    b = []
    for r in rows:
        dt, dc = _dir(r["direction"])
        lp = live_pos.get(r["symbol"], {})
        mark = lp.get("mark")
        up = lp.get("upnl")
        up_html = ('<td class="d">—</td>' if up is None else
                   f'<td class="{"g" if up>=0 else "r"}" data-s="{up}">'
                   f'{"+" if up>=0 else ""}${up:.2f}</td>')
        b.append(f'<tr><td class="l"><a class="tlink" href="{_trade_link(r["setup_id"])}" '
                 f'title="İşlem grafiği">{_e(r["symbol"])}</a></td><td>{_e(r["interval"])}</td>'
                 f'<td class="l">{_e(r["pattern"])}</td><td class="{dc}">{dt}</td>'
                 f'<td>{_fmt_px(r["entry_px"])}</td><td>{_fmt_px(mark)}</td>'
                 f'<td>{_fmt_px(r["stop_px"])}</td><td>{_fmt_px(r["tp_px"])}</td>'
                 f'{up_html}<td>{r["leverage"]:.0f}x</td>'
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
        b.append(f'<tr><td class="l"><a class="tlink" href="{_trade_link(r["setup_id"])}" '
                 f'title="İşlem grafiği">{_e(r["symbol"])}</a></td><td>{_e(r["interval"])}</td>'
                 f'<td class="l">{_e(r["pattern"])}</td><td class="{dc}">{dt}</td>'
                 f'<td>{_fmt_px(r["entry_px"])}</td><td>{_fmt_px(r["exit_px"])}</td>'
                 f'<td>{r["leverage"]:.0f}x</td>'
                 f'{_score(r["q_score"])}{_score(r["confluence_score"])}'
                 f'<td class="{rc}" data-s="{pnl}">{"+" if pnl>=0 else ""}${pnl:.2f}</td>'
                 f'<td class="{rc}">{res}</td>'
                 f'<td class="d" data-s="{r["closed_at"] or 0}">{_fmt_ts(r["closed_at"])}</td></tr>')
    return h + "".join(b) + "</tbody></table>"


_LWC_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "assets",
                         "lightweight-charts.standalone.production.js")
_ISEC = {"15m": 900, "30m": 1800, "60m": 3600, "1h": 3600, "2h": 7200,
         "4h": 14400, "8h": 28800, "1d": 86400}


def _trade_link(setup_id) -> str:
    return f"/trade?id={setup_id}"


def _fetch_klines(symbol, interval, end_ms=None):
    """Mum verisi BINANCE'ten (işlemin gerçekleştiği borsa; 42 sembolün hepsi var).
    testnet (fill ile tutarlı) → mainnet fallback. Ham dict listesi döner."""
    from terminal.data.binance_futures import BINANCE_DATA_BASE, BinanceFuturesClient
    from terminal.data.binance_trade import BINANCE_TESTNET
    bases = ([BINANCE_DATA_BASE, BINANCE_TESTNET] if os.environ.get("WEB_KLINES_MAINNET")
             else [BINANCE_TESTNET, BINANCE_DATA_BASE])
    for base in bases:
        c = BinanceFuturesClient(base_url=base)
        try:
            kl = (c.klines_paginated(symbol, interval, 300, end_time_ms=end_ms)
                  if end_ms else c.klines(symbol, interval, 300))
        except Exception:
            kl = []
        finally:
            c.close()
        if kl:
            return kl
    return []


def _klines_json(symbol, interval, end_ms=None) -> bytes:
    """Grafik mum verisi (sunucu proxy → CORS yok)."""
    kl = _fetch_klines(symbol, interval, end_ms)
    candles = [{"time": int(k["open_time"] // 1000), "open": k["open"], "high": k["high"],
                "low": k["low"], "close": k["close"]} for k in kl]
    return json.dumps({"candles": candles}).encode("utf-8")


_TRADE_HTML = """<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__SYM__ __IV__ · işlem grafiği</title>
<style>body{margin:0;background:#0e0e10;color:#e6e6ea;font-family:-apple-system,'Segoe UI',sans-serif}
.bar{padding:9px 12px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;font-size:13px;border-bottom:1px solid #222}
.bar b{font-size:15px}.g{color:#4caf50}.r{color:#ef5350}.d{color:#888}a{color:#f0b90b;text-decoration:none}
#wrap{position:relative;width:100vw;height:78vh}#c{width:100%;height:100%}
#ov{position:absolute;inset:0;pointer-events:none;overflow:hidden;z-index:5}
.note{color:#888;font-size:11px;padding:6px 12px}</style></head>
<body><div class="bar"><a href="/">← geri</a> <b>__SYM__</b> <span class="d">__IV__</span>
<span class="__DC__">__DIR__</span> <span class="d">__PAT__</span>
<span>Entry <b>__ENTRY__</b></span> <span class="r">SL __STOP__</span> <span class="g">TP __TP__</span>
<span>Sonuç <b class="__PC__">__PNL__</b></span>
<a href="__TVURL__" target="_blank">TradingView ↗</a></div>
<div id="wrap"><div id="c"></div><div id="ov"></div></div>
<div class="note">Mor kutu=OB (Order Block) · CE=OB ortası · Kırmızı=SL bölgesi · Yeşil=TP bölgesi · Sarı=XABCD · oklar giriş/çıkış. Mumlar Binance.</div>
<script src="/lwc.js"></script><script>
var L=window.LightweightCharts, wrap=document.getElementById('wrap'), ov=document.getElementById('ov');
var ch=L.createChart(document.getElementById('c'),{width:wrap.clientWidth,height:wrap.clientHeight,
 layout:{background:{color:'#0e0e10'},textColor:'#aaa'},grid:{vertLines:{color:'#181818'},horzLines:{color:'#181818'}},
 timeScale:{timeVisible:true,borderColor:'#333'},rightPriceScale:{borderColor:'#333'}});
var s=ch.addCandlestickSeries({upColor:'#26a69a',downColor:'#ef5350',borderVisible:false,
 wickUpColor:'#26a69a',wickDownColor:'#ef5350'});
function pl(p,c,t){s.createPriceLine({price:p,color:c,lineWidth:1,lineStyle:2,axisLabelVisible:true,title:t});}
var EN=__ENTRYV__,SL=__STOPV__,TP=__TPV__,BULL=__BULL__,OBLO=__OBLOW__,OBHI=__OBHIGH__,OBT=__OBT__,T0=__T0__,T1=__T1__;
function box(t0,t1,pHi,pLo,bg,bd){
 var x0=ch.timeScale().timeToCoordinate(t0),x1=ch.timeScale().timeToCoordinate(t1),
     yH=s.priceToCoordinate(pHi),yL=s.priceToCoordinate(pLo),W=ov.clientWidth;
 if(yH==null||yL==null)return; if(x0==null)x0=0; if(x1==null)x1=W; if(x1<x0){var z=x0;x0=x1;x1=z;}
 var d=document.createElement('div');
 d.style.cssText='position:absolute;left:'+x0+'px;top:'+yH+'px;width:'+(x1-x0)+'px;height:'+
  (yL-yH)+'px;background:'+bg+';border:1px solid '+bd+';box-sizing:border-box;border-radius:2px';
 ov.appendChild(d);
}
function draw(){
 ov.innerHTML='';
 if(BULL) box(T0,T1,TP,EN,'rgba(38,166,154,0.10)','rgba(38,166,154,0.45)');
 else     box(T0,T1,EN,TP,'rgba(38,166,154,0.10)','rgba(38,166,154,0.45)');
 if(OBLO!=null){
  if(BULL) box(OBT,T1,OBLO,SL,'rgba(239,83,80,0.15)','rgba(239,83,80,0.45)');
  else     box(OBT,T1,SL,OBHI,'rgba(239,83,80,0.15)','rgba(239,83,80,0.45)');
  box(OBT,T1,OBHI,OBLO,'rgba(124,77,255,0.18)','rgba(124,77,255,0.7)');
 }
}
fetch('/klines?symbol=__SYM__&interval=__IV__&end=__END__').then(x=>x.json()).then(function(d){
 s.setData(d.candles||[]);
 var hd=__HARMONIC__;
 if(hd.length){var hl=ch.addLineSeries({color:'#f0b90b',lineWidth:2,lineStyle:0,
   lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false});hl.setData(hd);}
 pl(EN,'#42a5f5','Entry'); pl(SL,'#ef5350','SL'); pl(TP,'#26a69a','TP');
 if(OBLO!=null) pl((OBHI+OBLO)/2,'#7c4dff','CE');
 var m=__MARKERS__; if(m.length) s.setMarkers(m);
 ch.timeScale().fitContent();
 requestAnimationFrame(draw); setTimeout(draw,80); setTimeout(draw,300);
});
ch.timeScale().subscribeVisibleTimeRangeChange(draw);
window.addEventListener('resize',function(){
 ch.applyOptions({width:wrap.clientWidth,height:wrap.clientHeight}); draw();});
</script></body></html>"""


def _trade_page(db_path, setup_id) -> bytes:
    try:
        conn = _connect(db_path)
        conn.row_factory = sqlite3.Row
        r = conn.execute(
            "SELECT b.symbol,b.interval,b.direction,b.pattern,b.entry_px,b.stop_px,b.tp_px,"
            "b.opened_at,b.closed_at,b.pnl_usd,"
            "s.x_time,s.x_price,s.a_time,s.a_price,s.b_time,s.b_price,"
            "s.c_time,s.c_price,s.d_time,s.d_price,s.prz_low,s.prz_high "
            "FROM binance_trades b LEFT JOIN setups s ON s.id=b.setup_id "
            "WHERE b.setup_id=?", (setup_id,)).fetchone()
        conn.close()
    except sqlite3.Error:
        r = None
    if r is None:
        return (b"<html><body style='background:#0e0e10;color:#ccc;font-family:sans-serif'>"
                b"<p style='padding:20px'>\xc4\xb0\xc5\x9flem bulunamad\xc4\xb1. <a style='color:#f0b90b' href='/'>geri</a></p></body></html>")
    sec = _ISEC.get(r["interval"], 900)
    end = (r["closed_at"] or r["opened_at"] or 0) + 60 * sec * 1000
    dirn, dc = _dir(r["direction"])
    pnl = r["pnl_usd"]
    pc = "g" if (pnl or 0) >= 0 else "r"
    pstr = "—" if pnl is None else f"{'+' if pnl >= 0 else ''}${pnl:.2f}"
    markers = []
    if r["opened_at"]:
        markers.append({"time": (r["opened_at"] // 1000 // sec) * sec, "position": "belowBar",
                        "color": "#42a5f5", "shape": "arrowUp", "text": "giriş"})
    if r["closed_at"]:
        col = "#26a69a" if (pnl or 0) >= 0 else "#ef5350"
        markers.append({"time": (r["closed_at"] // 1000 // sec) * sec, "position": "aboveBar",
                        "color": col, "shape": "arrowDown", "text": "çıkış"})
    # XABCD harmonik formasyon (setups tablosundan pivotlar)
    harmonic = []
    try:
        if r["x_time"] is not None:
            for key in ("x", "a", "b", "c", "d"):
                harmonic.append({"time": int(r[f"{key}_time"]) // 1000,
                                 "value": r[f"{key}_price"]})
    except (KeyError, TypeError, ValueError):
        harmonic = []
    markers.sort(key=lambda m: m["time"])
    # Order Block — PaMonic'in D bölgesinde bulduğu OB'yi mumlardan yeniden hesapla
    ob_low = ob_high = ob_time = None
    try:
        if r["d_time"] is not None and r["prz_low"] is not None:
            kl = _fetch_klines(r["symbol"], r["interval"], end)
            di = next((i for i, k in enumerate(kl) if k["open_time"] == r["d_time"]), None)
            if di is not None:
                from terminal.quality.pamonic import pamonic_confluence

                class _S:
                    pass
                st = _S()
                st.direction = r["direction"]
                st.prz_low = r["prz_low"]
                st.prz_high = r["prz_high"]
                ob = pamonic_confluence(st, kl, min_displacement=0.003, near_bars=15, d_index=di)
                if ob is not None:
                    ob_low, ob_high, ob_time = ob.bottom, ob.top, ob.time
    except Exception:
        ob_low = ob_high = ob_time = None
    is_bull = r["direction"] == "bull"
    t0 = (r["opened_at"] or r["d_time"] or 0) // 1000
    t1 = end // 1000
    obt = (ob_time or r["d_time"] or 0) // 1000
    tv = (f"https://www.tradingview.com/chart/?symbol=BINANCE:{_e(r['symbol'])}.P"
          f"&interval={_TV_TF.get(r['interval'], '15')}")
    html = _TRADE_HTML
    for k, v in {
        "__SYM__": _e(r["symbol"]), "__IV__": _e(r["interval"]), "__DIR__": dirn, "__DC__": dc,
        "__PAT__": _e(r["pattern"]), "__ENTRY__": _fmt_px(r["entry_px"]),
        "__STOP__": _fmt_px(r["stop_px"]), "__TP__": _fmt_px(r["tp_px"]),
        "__PNL__": pstr, "__PC__": pc, "__TVURL__": tv, "__END__": str(end),
        "__ENTRYV__": repr(r["entry_px"]), "__STOPV__": repr(r["stop_px"]),
        "__TPV__": repr(r["tp_px"]), "__MARKERS__": json.dumps(markers),
        "__HARMONIC__": json.dumps(harmonic),
        "__BULL__": "true" if is_bull else "false",
        "__OBLOW__": repr(ob_low) if ob_low is not None else "null",
        "__OBHIGH__": repr(ob_high) if ob_high is not None else "null",
        "__OBT__": str(obt), "__T0__": str(t0), "__T1__": str(t1),
    }.items():
        html = html.replace(k, v)
    return html.encode("utf-8")


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
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
                return
            try:
                if path == "/lwc.js":
                    with open(_LWC_PATH, "rb") as f:
                        body = f.read()
                    ctype = "application/javascript"
                elif path == "/klines":
                    q = parse_qs(parsed.query)
                    sym = q.get("symbol", [""])[0].upper()
                    iv = q.get("interval", ["15m"])[0]
                    end = q.get("end", [None])[0]
                    body = _klines_json(sym, iv, int(end) if end and end.isdigit() else None)
                    ctype = "application/json"
                elif path == "/trade":
                    sid = parse_qs(parsed.query).get("id", [""])[0]
                    body = _trade_page(db_path, int(sid)) if sid.isdigit() \
                        else b"<a href='/'>geri</a>"
                    ctype = "text/html; charset=utf-8"
                else:
                    body = render(db_path, refresh).encode("utf-8")
                    ctype = "text/html; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
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
