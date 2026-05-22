"""Setup için chart PNG üreteci — X/A/B/C/D işaretleri, PRZ, Entry/SL/TP."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

import matplotlib
matplotlib.use("Agg")  # headless backend
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd

from terminal.detection.models import Setup


def _klines_to_df(klines: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(klines)
    df["dt"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("dt")
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
    })
    return df[["Open", "High", "Low", "Close", "Volume"]]


def render_setup_chart(setup: Setup, klines: list[dict[str, Any]]) -> bytes:
    """Setup'ın X-A-B-C-D çizgisi + PRZ kutusu + Entry/SL/TP yatay çizgilerini içeren PNG döner.

    Görsel ayarı: koyu tema, candle (boğa yeşil / ayı kırmızı), hacim alt panel.
    """
    df = _klines_to_df(klines)

    # 5 pivot için (zaman, fiyat) noktaları
    p_times = [pd.to_datetime(setup.pivots[k].time, unit="ms", utc=True) for k in "XABCD"]
    p_prices = [setup.pivots[k].price for k in "XABCD"]

    # X-A-B-C-D çizgisi — alongside series uzun, sadece pivot noktalarında değer var
    pivot_series = pd.Series(index=df.index, dtype=float)
    for t, p in zip(p_times, p_prices):
        if t in pivot_series.index:
            pivot_series.loc[t] = p

    addplots = [
        mpf.make_addplot(pivot_series, type="scatter", markersize=70,
                         marker="o", color="#00d4ff"),
    ]

    # PRZ aralığı — yatay alan (hlines)
    hlines = dict(
        hlines=[setup.entry, setup.stop, setup.tp1, setup.tp2, setup.prz_low, setup.prz_high],
        colors=["#00d4ff", "#ff5252", "#4caf50", "#4caf50", "#888888", "#888888"],
        linestyle=["-", "--", "--", ":", ":", ":"],
        linewidths=[1.5, 1.2, 1.0, 0.8, 0.6, 0.6],
    )

    title = (
        f"{setup.symbol} {setup.interval}  "
        f"{setup.direction.upper()} {setup.pattern_name}  "
        f"B={setup.b_ratio:.3f} D={setup.d_ratio:.3f}"
        + ("  AB=CD" if setup.ab_cd_equivalent else "")
    )

    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        rc={"font.size": 9},
    )

    buf = io.BytesIO()
    fig, _ = mpf.plot(
        df,
        type="candle",
        style=style,
        addplot=addplots,
        hlines=hlines,
        volume=True,
        title=title,
        figsize=(11, 6),
        returnfig=True,
        tight_layout=True,
        warn_too_much_data=10_000,
    )

    # X-A-B-C-D etiketlerini pivot noktalarına yaz
    ax = fig.axes[0]
    # mplfinance kategorik x ekseni kullanıyor — index'leri çevirmek lazım
    for label, t, p in zip("XABCD", p_times, p_prices):
        if t in df.index:
            x_idx = df.index.get_loc(t)
            ax.annotate(label, xy=(x_idx, p),
                        xytext=(0, 12 if label in ("A", "C") else -16),
                        textcoords="offset points",
                        ha="center", fontsize=11, fontweight="bold",
                        color="#00d4ff")

    # PRZ kutusu — pivot D zamanından sonra ileri 20 bar
    if p_times[-1] in df.index:
        d_idx = df.index.get_loc(p_times[-1])
        ax.axhspan(setup.prz_low, setup.prz_high, xmin=d_idx / len(df),
                   alpha=0.15, color="#00d4ff")

    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()
