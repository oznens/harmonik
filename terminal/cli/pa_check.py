"""PA giriş denetimi CLI — bir setup'ın 3 kontrol noktasına uyup uymadığını raporlar.

Kullanım:
    # DB'deki bir setup'ı check et (HTF + LTF mumları DB'den):
    python -m terminal.cli.pa_check --setup-id 123

    # Canlı: pariteyi tara, son N setup'ı check et (LTF canlı çekilir):
    python -m terminal.cli.pa_check --symbol BTCUSDT --interval 60m --last 5
"""
from __future__ import annotations

import argparse
import sys

from terminal.backtest.engine import load_db_klines
from terminal.cli.run_data import _normalize_interval
from terminal.detection.scanner import default_threshold, scan_klines
from terminal.quality.htf_ltf import ltf_for
from terminal.quality.pa_check import format_checklist, pa_checklist


def _check_db_setup(setup_id: int) -> int:
    from terminal.db.store import Store
    store = Store()
    setup = store.load_setup(setup_id)
    if setup is None:
        print(f"Setup #{setup_id} DB'de yok.")
        return 1
    klines = load_db_klines(store, setup.symbol, setup.interval, limit=2000)
    if not klines:
        print(f"{setup.symbol} {setup.interval} için DB'de mum yok "
              "(download_history ile indir).")
        return 1
    ltf_iv = ltf_for(setup.interval)
    ltf = load_db_klines(store, setup.symbol, ltf_iv, limit=3000) if ltf_iv else None
    if not ltf:
        ltf = None  # LTF mumu yoksa CHoCH "?" raporlanır
    c = pa_checklist(setup, klines, ltf_klines=ltf)
    print(format_checklist(setup, c))
    store.close()
    return 0


def _check_live(symbol: str, interval: str, last: int) -> int:
    from terminal.data.mexc_client import MexcClient, MexcError
    client = MexcClient()
    try:
        klines = client.klines(symbol, interval, limit=500)
    except MexcError as e:
        print(f"MEXC mum çekme hatası: {e}")
        return 1
    setups = scan_klines(klines, symbol, interval,
                         zigzag_threshold=default_threshold(interval))
    setups = [s for s in setups if not s.elenen]
    if not setups:
        print(f"{symbol} {interval}: setup bulunamadı.")
        return 0
    ltf_iv = ltf_for(interval)
    ltf = None
    if ltf_iv:
        try:
            ltf = client.klines(symbol, ltf_iv, limit=500)
        except MexcError as e:
            print(f"(LTF {ltf_iv} çekilemedi: {e} → CHoCH '?')")
    for s in setups[-last:]:
        c = pa_checklist(s, klines, ltf_klines=ltf)
        print(format_checklist(s, c))
        print()
    client.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="terminal-pa-check",
        description="Setup'ın PA giriş kontrol noktalarını (yer/zaman/stop) denetle.",
    )
    p.add_argument("--setup-id", type=int, help="DB'deki setup id'si")
    p.add_argument("--symbol", help="Canlı tara (örn. BTCUSDT)")
    p.add_argument("--interval", help="Aralık (örn. 60m)")
    p.add_argument("--last", type=int, default=3, help="Canlı modda son N setup (varsayılan 3)")
    args = p.parse_args(argv)

    if args.setup_id is not None:
        return _check_db_setup(args.setup_id)
    if args.symbol and args.interval:
        return _check_live(args.symbol.upper(), _normalize_interval(args.interval), args.last)
    p.error("--setup-id VEYA --symbol+--interval gerekli")
    return 2


if __name__ == "__main__":
    sys.exit(main())
