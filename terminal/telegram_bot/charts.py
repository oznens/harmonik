"""Setup için chart PNG üreteci.

Açık tema (beyaz arkaplan + altın aksent), X/A/B/C/D etiketli pivot daireleri,
kesik bağlantı çizgileri, PRZ (D bölgesi) kutusu, üstte koyu başlık bandı.
"""
from __future__ import annotations

import io
from typing import Any

import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.patches import Rectangle

from terminal.detection.models import Setup

# Renk paleti
BG_HEADER = "#0e0e10"
TXT_GOLD = "#d4a72c"
TXT_SUB = "#9a9a9a"
GREEN = "#26a69a"
RED = "#ef5350"
PIVOT_CIRCLE_FACE = "#ffffff"
PIVOT_CIRCLE_EDGE = "#444444"
DASH = "#444444"
PRZ_FILL = "#f5e6c8"
PRZ_EDGE = "#d4a72c"
ENTRY_COLOR = "#0288d1"
SL_COLOR = "#ef5350"
TP_COLOR = "#26a69a"


def _klines_to_df(klines: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(klines)
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt")
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })
    return df[["Open", "High", "Low", "Close", "Volume"]]


def render_setup_chart(setup: Setup, klines: list[dict[str, Any]]) -> bytes:
    """Açık temalı setup chart'ı: X-A-B-C-D etiketli + bağlantı çizgileri + PRZ kutusu."""
    df = _klines_to_df(klines)

    # Pivot zaman/fiyat
    pivot_points: list[tuple[str, pd.Timestamp, float]] = []
    for letter in "XABCD":
        p = setup.pivots[letter]
        t = pd.to_datetime(p.time, unit="ms", utc=True)
        pivot_points.append((letter, t, p.price))

    # Açık tema mplfinance
    mc = mpf.make_marketcolors(
        up=GREEN, down=RED, edge="inherit", wick="inherit",
        volume="in", inherit=True,
    )
    style = mpf.make_mpf_style(
        base_mpf_style="classic",
        marketcolors=mc,
        gridcolor="#eaeaea",
        gridstyle="-",
        facecolor="#ffffff",
        edgecolor="#cccccc",
        figcolor="#ffffff",
        rc={
            "font.size": 10,
            "axes.labelcolor": "#333",
            "axes.edgecolor": "#cccccc",
            "xtick.color": "#666",
            "ytick.color": "#666",
        },
    )

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        volume=False,
        figsize=(14, 7),
        returnfig=True,
        tight_layout=False,
        warn_too_much_data=10_000,
        update_width_config={"candle_width": 0.6},
    )
    ax = axes[0]

    # 1) X-A-B-C-D bağlantı çizgileri (kesik)
    for i in range(len(pivot_points) - 1):
        _, ta, pa = pivot_points[i]
        _, tb, pb = pivot_points[i + 1]
        if ta in df.index and tb in df.index:
            ia = df.index.get_loc(ta)
            ib = df.index.get_loc(tb)
            ax.plot([ia, ib], [pa, pb], linestyle="--",
                    color=DASH, linewidth=1.2, zorder=5)

    # 2) Pivot daireleri (X/A/B/C/D)
    d_idx_x = None
    for letter, t, price in pivot_points:
        if t not in df.index:
            continue
        x_idx = df.index.get_loc(t)
        ax.scatter([x_idx], [price], s=450, color=PIVOT_CIRCLE_FACE,
                   edgecolor=PIVOT_CIRCLE_EDGE, linewidth=1.5, zorder=10)
        ax.text(x_idx, price, letter, ha="center", va="center",
                fontsize=11, fontweight="bold", color="#000", zorder=11)
        if letter == "D":
            d_idx_x = x_idx

    # 3) PRZ ("D bölgesi") kutusu — C noktasından D'nin biraz ötesine
    if d_idx_x is not None:
        # C bar'ından başla
        c_pivot = setup.pivots["C"]
        c_time = pd.to_datetime(c_pivot.time, unit="ms", utc=True)
        c_idx = df.index.get_loc(c_time) if c_time in df.index else max(0, d_idx_x - 20)
        # Sağa biraz uzat (D'nin sağı)
        right_edge = min(len(df) - 1, d_idx_x + 5)
        width = right_edge - c_idx
        rect = Rectangle(
            (c_idx, setup.prz_low), width, setup.prz_high - setup.prz_low,
            facecolor=PRZ_FILL, edgecolor=PRZ_EDGE,
            linewidth=1.0, alpha=0.55, zorder=4,
        )
        ax.add_patch(rect)
        # D? etiketi (D pivot mu, hedef mi belli olsun diye sağ üst)
        ax.text(right_edge, setup.prz_high, "D?",
                ha="right", va="bottom", fontsize=11, fontweight="bold",
                color=PRZ_EDGE, zorder=12)

    # 4) Entry / SL / TP yatay çizgileri (sade)
    ax.axhline(setup.entry, color=ENTRY_COLOR, linewidth=1.0,
               linestyle="-", alpha=0.6, zorder=3)
    ax.axhline(setup.stop, color=SL_COLOR, linewidth=0.8,
               linestyle="--", alpha=0.5, zorder=3)
    ax.axhline(setup.tp1, color=TP_COLOR, linewidth=0.8,
               linestyle="--", alpha=0.5, zorder=3)

    # 5) Başlık (üstte koyu band)
    direction_text = "Bearish" if setup.direction == "bear" else "Bullish"
    title = f"terminalMiraz / {setup.symbol} {setup.interval} / {direction_text} {setup.pattern_name}"
    subtitle = (f"D bölgesi: {setup.prz_low:.6g} - {setup.prz_high:.6g}"
                + (f"  ·  Q {setup.q_score} {setup.q_category}" if setup.q_score else ""))

    # Header band üstte
    fig.patch.set_facecolor("#ffffff")
    header_h = 0.07
    fig.subplots_adjust(top=1 - header_h - 0.02)
    header_ax = fig.add_axes([0, 1 - header_h, 1, header_h])
    header_ax.set_facecolor(BG_HEADER)
    header_ax.set_xticks([])
    header_ax.set_yticks([])
    for spine in header_ax.spines.values():
        spine.set_visible(False)
    header_ax.text(0.012, 0.65, title, color=TXT_GOLD,
                   fontsize=14, fontweight="bold", va="center", ha="left")
    header_ax.text(0.012, 0.22, subtitle, color=TXT_SUB,
                   fontsize=10, va="center", ha="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches=None,
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
