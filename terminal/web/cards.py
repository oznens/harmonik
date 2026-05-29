"""Sonuç kartları (terminalMiraz tarzı) — saf stdlib HTML + inline SVG mini grafik.

Hem web dashboard'a hem masaüstü 'Kartlar' sekmesine AYNI görünümü verir.
Qt / matplotlib bağımlılığı YOK — sadece string + sqlite (salt-okunur).

Her kart: SYMBOL + TF rozeti · pattern/yön/sonuç pill'leri · XABCD mini grafik
(inline SVG) · D ZONE/Entry/SL/TP kutusu · "Sonuç <tarih>" altbilgisi.
"""
from __future__ import annotations

import html as html_mod
import sqlite3
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=3))  # IST — diğer UI ile tutarlı

# Pattern → renk (referans terminalMiraz paleti). İçerik araması (lower).
_PATTERN_COLORS: list[tuple[str, str]] = [
    ("gartley", "#26a69a"),   # yeşil
    ("butterfly", "#d4a72c"), # altın
    ("bat", "#ef5350"),       # kırmızı
    ("crab", "#ab47bc"),      # mor
    ("shark", "#9aa0aa"),     # gri
    ("cypher", "#42a5f5"),    # mavi
    ("ab=cd", "#26c6da"),     # camgöbeği
]
_DEFAULT_COLOR = "#9aa0aa"

# Pivot harfi → pill rengi (referans paleti)
_LETTER_COLORS = {"X": "#9aa0aa", "A": "#ab47bc", "B": "#42a5f5",
                  "C": "#d4a72c", "D": "#d05ce3"}

# Sonuç → (etiket, css sınıfı)
_OUTCOME = {"TP": ("TP", "g"), "STOP": ("STOP", "r"),
            "ZI": ("ZI", "d"), "EO": ("Entry Olmadı", "d")}

# Kartların ortak CSS'i — hem web hem masaüstü sayfaya gömülür.
CARD_CSS = """
  .tcards { display:grid; grid-template-columns:repeat(auto-fill,minmax(290px,1fr));
            gap:10px; margin:6px 0 16px; }
  .tcard { background:#16161b; border:1px solid #2a2a32; border-left:4px solid #9aa0aa;
           border-radius:10px; padding:10px 12px; }
  .tc-head { display:flex; align-items:center; gap:8px; margin-bottom:8px; }
  .tc-sym { font-size:16px; font-weight:800; letter-spacing:.3px; }
  .tc-tf { margin-left:auto; font-size:11px; color:#9aa0aa; border:1px solid #3a3a44;
           border-radius:6px; padding:1px 7px; }
  .tc-tags { display:flex; align-items:center; gap:6px; margin-bottom:8px; flex-wrap:wrap; }
  .tc-pill { font-size:11px; font-weight:700; border-radius:6px; padding:2px 8px;
             border:1px solid currentColor; }
  .tc-letter { font-size:11px; font-weight:800; border-radius:6px; padding:2px 8px;
               color:#0e0e10; }
  .tc-dir, .tc-status { font-size:11px; font-weight:700; border-radius:6px; padding:2px 8px; }
  .tc-dir.g, .tc-status.g { background:#13392f; color:#4caf50; border:1px solid #2e7d5b; }
  .tc-dir.r, .tc-status.r { background:#3a1a1c; color:#ef5350; border:1px solid #7d3a3a; }
  .tc-status.d { background:#23232b; color:#9aa0aa; border:1px solid #3a3a44; }
  .tc-status { margin-left:auto; }
  .tc-body { display:flex; gap:10px; align-items:stretch; }
  .tc-chart { flex:1 1 50%; background:#101015; border:1px solid #23232b; border-radius:8px;
              min-height:96px; display:flex; }
  .tc-chart svg { width:100%; height:100%; display:block; }
  .tc-info { flex:1 1 50%; display:flex; flex-direction:column; justify-content:center; gap:3px;
             font-size:12px; }
  .tc-info .row { display:flex; justify-content:space-between; gap:8px; }
  .tc-info .k { color:#7d8088; }
  .tc-info b { font-weight:700; }
  .tc-info .dim { color:#6a6d75; }
  .tc-info .g { color:#4caf50; }
  .tc-foot { margin-top:8px; text-align:right; font-size:10px; color:#6a6d75; }
"""


def _e(s) -> str:
    return html_mod.escape(str(s))


def _fmt_ts(ms: int | None) -> str:
    if not ms:
        return "—"
    return datetime.fromtimestamp(ms / 1000, tz=TZ).strftime("%d.%m.%Y %H:%M")


def _fmt_price(p: float | None) -> str:
    if p is None:
        return "—"
    if p >= 1000:
        return f"{p:,.4f}"
    if p >= 1:
        return f"{p:.5f}"
    return f"{p:.8g}"


def pattern_color(pattern: str) -> str:
    p = (pattern or "").lower()
    for key, col in _PATTERN_COLORS:
        if key in p:
            return col
    return _DEFAULT_COLOR


def _completion_letter(pattern: str) -> str:
    """Girişin/tamamlanmanın olduğu pivot harfi (Shark→C, diğer XABCD→D)."""
    return "C" if "shark" in (pattern or "").lower() else "D"


def _mini_svg(prices: list[float | None], times: list[int | None],
              color: str, w: int = 160, h: int = 96) -> str:
    """5 pivotluk (X-A-B-C-D) mini zigzag grafiği — inline SVG.

    Pivot fiyatları/zamanları eksikse boş bir grafik (—) döner.
    """
    if any(p is None for p in prices) or any(t is None for t in times):
        return (f'<svg viewBox="0 0 {w} {h}"><text x="{w/2}" y="{h/2}" '
                f'fill="#4a4d55" font-size="11" text-anchor="middle">grafik yok</text></svg>')
    pmin, pmax = min(prices), max(prices)
    tmin, tmax = min(times), max(times)
    pr = (pmax - pmin) or 1.0
    tr = (tmax - tmin) or 1.0
    padx, padtop, padbot = 12, 16, 12

    def fx(t: float) -> float:
        return padx + (t - tmin) / tr * (w - 2 * padx)

    def fy(p: float) -> float:
        return padtop + (pmax - p) / pr * (h - padtop - padbot)

    pts = [(fx(t), fy(p)) for t, p in zip(times, prices)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    dots = []
    for (x, y), lbl in zip(pts, "XABCD"):
        ly = y - 7 if lbl in ("A", "C") else y + 13   # tepe üstte, dip altta etiket
        dots.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{color}"/>'
            f'<text x="{x:.1f}" y="{ly:.1f}" fill="#8a8d95" font-size="9" '
            f'text-anchor="middle">{lbl}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polyline points="{poly}" fill="none" stroke="{color}" '
            f'stroke-width="1.6" stroke-linejoin="round"/>{"".join(dots)}</svg>')


def card_html(t: dict) -> str:
    """Tek bir işlem/setup için kart HTML'i."""
    pattern = t.get("pattern") or ""
    color = pattern_color(pattern)
    direction = t.get("direction") or "bull"
    is_bull = direction == "bull"
    dir_txt = "Long" if is_bull else "Short"
    dir_cls = "g" if is_bull else "r"

    outcome = t.get("outcome")
    if t.get("closed_at"):
        st_txt, st_cls = _OUTCOME.get(outcome, (outcome or "—", "d"))
        foot = f"Sonuç {_fmt_ts(t.get('closed_at'))}"
    else:
        st_txt, st_cls = "AÇIK", "d"
        foot = f"Açıldı {_fmt_ts(t.get('opened_at'))}"

    letter = _completion_letter(pattern)
    letter_col = _LETTER_COLORS.get(letter, "#9aa0aa")

    prices = [t.get("x_price"), t.get("a_price"), t.get("b_price"),
              t.get("c_price"), t.get("d_price")]
    times = [t.get("x_time"), t.get("a_time"), t.get("b_time"),
             t.get("c_time"), t.get("d_time")]
    svg = _mini_svg(prices, times, color)

    d_zone = t.get("d_price")
    entry = t.get("entry_price")
    stop = t.get("stop_price")
    tp = t.get("tp1_price")

    return (
        f'<div class="tcard" style="border-left-color:{color}">'
        f'<div class="tc-head"><span class="tc-sym">{_e(t.get("symbol"))}</span>'
        f'<span class="tc-tf">{_e(t.get("interval"))}</span></div>'
        f'<div class="tc-tags">'
        f'<span class="tc-pill" style="color:{color}">{_e(pattern)}</span>'
        f'<span class="tc-letter" style="background:{letter_col}">{letter}</span>'
        f'<span class="tc-dir {dir_cls}">{dir_txt}</span>'
        f'<span class="tc-status {st_cls}">{_e(st_txt)}</span>'
        f'</div>'
        f'<div class="tc-body">'
        f'<div class="tc-chart">{svg}</div>'
        f'<div class="tc-info">'
        f'<div class="row"><span class="k">D ZONE</span><span class="dim">{_fmt_price(d_zone)}</span></div>'
        f'<div class="row"><span class="k">Entry</span><b>{_fmt_price(entry)}</b></div>'
        f'<div class="row"><span class="k">SL</span><b>{_fmt_price(stop)}</b></div>'
        f'<div class="row"><span class="k">Hedef</span><b class="g">{_fmt_price(tp)}</b></div>'
        f'</div></div>'
        f'<div class="tc-foot">{_e(foot)}</div>'
        f'</div>'
    )


def cards_grid_html(trades: list[dict], empty_msg: str = "Henüz kart yok.") -> str:
    """Kart ızgarası (grid) — gömülebilir iç HTML."""
    if not trades:
        return f'<div class="empty" style="padding:18px;text-align:center;color:#888">{_e(empty_msg)}</div>'
    return '<div class="tcards">' + "".join(card_html(t) for t in trades) + "</div>"


def connect_ro(db_path) -> sqlite3.Connection:
    """terminal.db'ye salt-okunur bağlan (writer'ı kilitlemez, WAL uyumlu)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
    return conn


# paper_trades + setups JOIN sütun sırası (load_card_trades pozisyonel okur)
_COLS = (
    "pt.symbol", "pt.interval", "pt.pattern", "pt.direction",
    "pt.entry_price", "pt.stop_price", "pt.tp1_price", "pt.exit_price",
    "pt.outcome", "pt.opened_at", "pt.closed_at",
    "s.x_price", "s.a_price", "s.b_price", "s.c_price", "s.d_price",
    "s.x_time", "s.a_time", "s.b_time", "s.c_time", "s.d_time",
)
_KEYS = (
    "symbol", "interval", "pattern", "direction",
    "entry_price", "stop_price", "tp1_price", "exit_price",
    "outcome", "opened_at", "closed_at",
    "x_price", "a_price", "b_price", "c_price", "d_price",
    "x_time", "a_time", "b_time", "c_time", "d_time",
)


def load_card_trades(conn: sqlite3.Connection, limit: int = 24,
                     only_closed: bool = False) -> list[dict]:
    """paper_trades + setups JOIN'inden kart verisi (en yeni önce).

    row_factory'den bağımsız (pozisyonel okur) → hem RO bağlantı hem Store._conn.
    """
    where = "WHERE pt.closed_at IS NOT NULL" if only_closed else ""
    sql = (f"SELECT {', '.join(_COLS)} FROM paper_trades pt "
           f"LEFT JOIN setups s ON s.id = pt.setup_id {where} "
           f"ORDER BY COALESCE(pt.closed_at, pt.opened_at) DESC LIMIT ?")
    try:
        rows = conn.execute(sql, (limit,)).fetchall()
    except sqlite3.Error:
        return []
    return [dict(zip(_KEYS, row)) for row in rows]


def cards_page(trades: list[dict], title: str = "Sonuç Kartları") -> str:
    """Bağımsız tam HTML sayfa (masaüstü QWebEngine setHtml için)."""
    return (
        '<!doctype html><html lang="tr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{_e(title)}</title><style>'
        ':root{color-scheme:dark}*{box-sizing:border-box}'
        "body{margin:0;background:#0e0e10;color:#e6e6ea;"
        "font-family:-apple-system,'Segoe UI',Roboto,sans-serif;font-size:14px;padding:12px}"
        f"{CARD_CSS}</style></head><body>"
        f"{cards_grid_html(trades)}"
        "</body></html>"
    )
