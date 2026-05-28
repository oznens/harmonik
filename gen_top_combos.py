"""Top-N pariteyi seç → tracked_combos.txt üret.

İki sıralama kaynağı:
  --source marketcap (VARSAYILAN): CoinGecko piyasa değeri (market cap)
        sıralaması, MEXC futures'ta işlem gören USDT perpetual'larla kesiştirilir.
  --source volume: MEXC futures 24s cirosuna (amount24) göre.

Her iki durumda da semboller spot biçiminde yazılır (BTC_USDT -> BTCUSDT);
futures client bunu kendi içinde çevirir. Çıktı run_live_multi'nin
--combos-file ile okuduğu formattadır.

Kullanım:
    python gen_top_combos.py                              # market cap top 50, 5 TF
    python gen_top_combos.py --top 50 --tfs 4h,1d         # swing
    python gen_top_combos.py --source volume --top 50     # hacme göre
    python gen_top_combos.py --dry-run                    # sadece listele

Not: kombinasyon = top × TF; her biri ayrı thread + poller (poll aralığı kadar
istek). 50×5=250 → rate limit için run_live_multi'yi --poll-seconds 30 ile çalıştır.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from terminal.data.mexc_futures import MexcFuturesClient

COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"

DEFAULT_TFS = ["15m", "30m", "60m", "4h", "1d"]
TF_LABELS = {
    "15m": "15m (kısa vadeli)", "30m": "30m (kısa-orta)",
    "60m": "1h/60m (orta)", "4h": "4h (swing)", "1d": "1d (uzun swing)",
}

# Baz parite olamayan/çift sayılan tokenlar: stablecoin'ler + sarmalı (wrapped)
# ve staked türevler. CoinGecko piyasa-değeri listesinde üst sıralarda çıkarlar
# ama tek başına işlem pariteleri değildir (ya da BTC/ETH'in türevidir).
EXCLUDE_BASE = {
    # stablecoinler
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USDD", "USDP",
    "GUSD", "FRAX", "LUSD", "USTC", "BUSD", "EURT", "USD1",
    # wrapped / staked türevler
    "WBTC", "WETH", "WSTETH", "STETH", "WEETH", "WBETH", "RETH", "CBETH",
    "METH", "LBTC", "SOLVBTC", "BTCB", "WBT",
}


def _volume(t: dict) -> float:
    """24s USDT cirosu — amount24 yoksa volume24'e düş."""
    for k in ("amount24", "volume24", "amount", "volume"):
        v = t.get(k)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def mexc_futures_usdt_bases(client: MexcFuturesClient) -> set[str]:
    """MEXC futures'ta _USDT perpetual olarak listelenen baz semboller (BTC, ETH...)."""
    bases: set[str] = set()
    for t in client.all_tickers():
        sym = t.get("symbol", "")
        if sym.endswith("_USDT"):
            bases.add(sym[: -len("_USDT")])
    return bases


def coingecko_by_marketcap(per_page: int = 250) -> list[tuple[str, float]]:
    """CoinGecko piyasa değeri (market cap) sıralı [(SEMBOL, market_cap), ...]."""
    with httpx.Client(timeout=20.0, headers={"User-Agent": "harmonik/1.0"}) as c:
        r = c.get(COINGECKO_MARKETS, params={
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": min(per_page, 250), "page": 1, "sparkline": "false",
        })
        r.raise_for_status()
        data = r.json()
    out: list[tuple[str, float]] = []
    for coin in data:
        sym = (coin.get("symbol") or "").upper()
        if sym:
            out.append((sym, float(coin.get("market_cap") or 0.0)))
    return out


def pick_intersect(ranked: list[tuple[str, float]], futures: set[str],
                   n: int) -> list[tuple[str, float]]:
    """Piyasa-değeri sırasını koru; MEXC futures'ta olan + dışlanmayanları seç."""
    picked: list[tuple[str, float]] = []
    seen: set[str] = set()
    for base, metric in ranked:
        if base in EXCLUDE_BASE or base in seen:
            continue
        if base in futures:
            picked.append((base + "USDT", metric))
            seen.add(base)
            if len(picked) >= n:
                break
    return picked


def top_marketcap(client: MexcFuturesClient, n: int) -> list[tuple[str, float]]:
    futures = mexc_futures_usdt_bases(client)
    ranked = coingecko_by_marketcap(250)
    return pick_intersect(ranked, futures, n)


def top_volume(client: MexcFuturesClient, n: int) -> list[tuple[str, float]]:
    """En yüksek 24s cirolu N USDT perpetual."""
    usdt = []
    for t in client.all_tickers():
        sym = t.get("symbol", "")
        if sym.endswith("_USDT"):
            base = sym[: -len("_USDT")]
            if base not in EXCLUDE_BASE:
                usdt.append((sym.replace("_", ""), _volume(t)))
    usdt.sort(key=lambda x: x[1], reverse=True)
    return usdt[:n]


def render(combos: list[tuple[str, float]], tfs: list[str], source: str) -> str:
    metric = "piyasa değeri" if source == "marketcap" else "24s ciro"
    lines = [
        "# Canlı tarama kombinasyonları (parite + TF).",
        f"# OTOMATİK ÜRETİLDİ: gen_top_combos.py — {metric} sıralaması "
        "(MEXC futures'ta işlem görenler).",
        f"# {len(combos)} parite × {len(tfs)} TF = {len(combos) * len(tfs)} kombinasyon.",
        "",
    ]
    width = max((len(s) for s, _ in combos), default=10)
    for tf in tfs:
        lines.append(f"# === {TF_LABELS.get(tf, tf)} ===")
        for sym, _v in combos:
            lines.append(f"{sym:<{width}} {tf}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Top-N pariteyi seç → combos dosyası")
    ap.add_argument("--top", type=int, default=50, help="Parite sayısı (varsayılan 50)")
    ap.add_argument("--tfs", default=",".join(DEFAULT_TFS),
                    help="Virgüllü TF listesi (varsayılan: 15m,30m,60m,4h,1d)")
    ap.add_argument("--source", choices=["marketcap", "volume"], default="marketcap",
                    help="Sıralama: marketcap (CoinGecko, varsayılan) veya volume (MEXC 24s)")
    ap.add_argument("--out", default="config/tracked_combos.txt", help="Çıktı dosyası")
    ap.add_argument("--dry-run", action="store_true", help="Sadece listele, yazma")
    args = ap.parse_args(argv)

    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]
    if not tfs:
        print("HATA: en az bir TF gerekli", file=sys.stderr)
        return 1

    client = MexcFuturesClient()
    try:
        if args.source == "marketcap":
            combos = top_marketcap(client, args.top)
        else:
            combos = top_volume(client, args.top)
    except httpx.HTTPError as e:
        print(f"HATA: veri çekilemedi ({type(e).__name__}: {e})", file=sys.stderr)
        client.close()
        return 1
    finally:
        client.close()

    if not combos:
        print("HATA: parite seçilemedi (liste boş).", file=sys.stderr)
        return 1

    metric_lbl = "piyasa değeri" if args.source == "marketcap" else "24s ciro"
    print(f"Top {len(combos)} parite ({metric_lbl}, MEXC futures'ta işlem görenler):")
    for i, (sym, v) in enumerate(combos, 1):
        print(f"  {i:2d}. {sym:<14s} {metric_lbl} ≈ ${v:,.0f}")
    print(f"\nTF'ler: {', '.join(tfs)}  →  {len(combos) * len(tfs)} kombinasyon")

    if args.dry_run:
        print("\n--dry-run: dosya yazılmadı.")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(combos, tfs, args.source), encoding="utf-8")
    print(f"\n✓ Yazıldı → {out.resolve()}")
    print("Servisi yeniden başlat: sudo systemctl restart harmonik")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
