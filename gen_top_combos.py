"""Top-N pariteyi MEXC futures 24s hacmine göre seçip tracked_combos.txt üret.

MEXC futures ticker'ından USDT kontratlarını 24s ciroya (amount24) göre sıralar,
en yüksek N tanesini alır ve her biri için seçilen TF'lerle kombinasyon dosyası
yazar. Çıktı, run_live_multi'nin --combos-file ile okuduğu formattadır.

Kullanım:
    python gen_top_combos.py                         # top 50, 5 TF (varsayılan)
    python gen_top_combos.py --top 50 --tfs 4h,1d    # top 50, sadece swing
    python gen_top_combos.py --top 30 --tfs 60m,4h,1d
    python gen_top_combos.py --dry-run               # sadece listele, yazma

Notlar:
- Semboller spot biçiminde yazılır (BTC_USDT -> BTCUSDT); futures client bunu
  kendi içinde çevirir.
- Kombinasyon sayısı = top × TF sayısı. Her kombinasyon ayrı thread + poller
  demek (her 10sn'de 1 istek). 50×5=250 kombinasyon ~25 istek/sn → MEXC rate
  limit'ini zorlayabilir; çok TF için --top'u düşür ya da TF'leri azalt.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from terminal.data.mexc_futures import MexcFuturesClient

DEFAULT_TFS = ["15m", "30m", "60m", "4h", "1d"]
TF_LABELS = {
    "15m": "15m (kısa vadeli)", "30m": "30m (kısa-orta)",
    "60m": "1h/60m (orta)", "4h": "4h (swing)", "1d": "1d (uzun swing)",
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


def top_symbols(client: MexcFuturesClient, n: int) -> list[tuple[str, float]]:
    """En yüksek hacimli N USDT perpetual — [(BTCUSDT, hacim), ...]."""
    tickers = client.all_tickers()
    usdt = []
    for t in tickers:
        sym = t.get("symbol", "")
        if not sym.endswith("_USDT"):
            continue
        spot = sym.replace("_", "")  # BTC_USDT -> BTCUSDT
        usdt.append((spot, _volume(t)))
    usdt.sort(key=lambda x: x[1], reverse=True)
    return usdt[:n]


def render(combos: list[tuple[str, float]], tfs: list[str]) -> str:
    lines = [
        "# Canlı tarama kombinasyonları (parite + TF).",
        "# OTOMATİK ÜRETİLDİ: gen_top_combos.py — MEXC futures 24s hacim sıralaması.",
        f"# {len(combos)} parite × {len(tfs)} TF = {len(combos) * len(tfs)} kombinasyon.",
        "",
    ]
    width = max((len(s) for s, _ in combos), default=10)
    for tf in tfs:
        lines.append(f"# === {TF_LABELS.get(tf, tf)} ===")
        for sym, _vol in combos:
            lines.append(f"{sym:<{width}} {tf}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Top-N pariteyi hacme göre seç → combos")
    ap.add_argument("--top", type=int, default=50, help="Parite sayısı (varsayılan 50)")
    ap.add_argument("--tfs", default=",".join(DEFAULT_TFS),
                    help="Virgüllü TF listesi (varsayılan: 15m,30m,60m,4h,1d)")
    ap.add_argument("--out", default="config/tracked_combos.txt", help="Çıktı dosyası")
    ap.add_argument("--dry-run", action="store_true", help="Sadece listele, yazma")
    args = ap.parse_args(argv)

    tfs = [t.strip() for t in args.tfs.split(",") if t.strip()]
    if not tfs:
        print("HATA: en az bir TF gerekli", file=sys.stderr)
        return 1

    client = MexcFuturesClient()
    try:
        combos = top_symbols(client, args.top)
    finally:
        client.close()

    if not combos:
        print("HATA: MEXC'den parite alınamadı (ticker boş).", file=sys.stderr)
        return 1

    print(f"En yüksek hacimli {len(combos)} USDT perpetual:")
    for i, (sym, vol) in enumerate(combos, 1):
        print(f"  {i:2d}. {sym:<14s} 24s ciro ≈ ${vol:,.0f}")
    print(f"\nTF'ler: {', '.join(tfs)}  →  {len(combos) * len(tfs)} kombinasyon")

    content = render(combos, tfs)
    if args.dry_run:
        print("\n--dry-run: dosya yazılmadı.")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"\n✓ Yazıldı → {out.resolve()}")
    print("Servisi yeniden başlat: sudo systemctl restart harmonik")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
