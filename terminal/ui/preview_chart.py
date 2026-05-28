"""Canlı grafiği TARAYICIDA önizle — PySide6/Qt gerektirmeden.

Gerçek `chart.html` + gerçek `lightweight-charts` + gerçek `chart_data` yükünü
tek bir bağımsız HTML dosyasına gömer. Qt'nin QWebChannel köprüsü, önceden
hesaplanmış payload'ları besleyen küçük bir JS taklidiyle değiştirilir; böylece
formasyon seçici (dropdown) ve katmanlar (Pivot/Vector/Harmonic/HTF) tarayıcıda
gerçekten test edilebilir.

Kullanım:
    python -m terminal.ui.preview_chart                 # gerçek DB; boşsa sentetik
    python -m terminal.ui.preview_chart --out /tmp/x.html
    python -m terminal.ui.preview_chart --symbol BTCUSDT --interval 60m
    python -m terminal.ui.preview_chart --synthetic     # her zaman sentetik demo

Not: Çıktı STATİK bir önizlemedir — canlı mum akışı yoktur, ama setup dropdown'ı
her seçenek için önceden çizilmiş gerçek formasyonu gösterir.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from terminal.db.store import Store
from terminal.ui import chart_data

_ASSETS = Path(__file__).resolve().parent / "assets"
_HTML = _ASSETS / "chart.html"
_LWC = _ASSETS / "lightweight-charts.standalone.production.js"


def _has_klines(store: Store) -> bool:
    try:
        n = store._conn.execute("SELECT COUNT(*) FROM klines").fetchone()[0]
        return bool(n)
    except Exception:
        return False


def _seed_synthetic(store: Store, symbol: str, interval: str) -> None:
    """DB boşsa: birkaç gerçek formasyon üret (Aktif + Aday + kapalı)."""
    from terminal.detection.scanner import scan_klines
    from terminal.lifecycle.states import TP
    from terminal.lifecycle.tracker import LifecycleTracker
    from tests.synthetic import bat_bull, gartley_bull, make_xabcd_klines

    tr = LifecycleTracker(symbol, interval, store)
    specs = [
        (gartley_bull, 1_700_000_000_000, "aktif"),
        (bat_bull,     1_700_120_000_000, "aday"),
    ]
    for fn, base_t, kind in specs:
        prices, kinds = fn()
        klines = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=base_t)
        store.upsert_klines(symbol, interval, klines)
        setups = scan_klines(klines, symbol, interval, zigzag_threshold=0.01, min_rr=0.0)
        if not setups:
            continue
        sid = store.upsert_setup(setups[0])
        tr.register_new(setups[0], sid, aggressive_entry=(kind == "aktif"))
    # bir de kapalı (TP) setup — dropdown'da görünmez ama açıkça seçilebilir
    prices, kinds = gartley_bull()
    klines = make_xabcd_klines(prices, kinds, bars_per_leg=12, base_time=1_700_240_000_000)
    store.upsert_klines(symbol, interval, klines)
    setups = scan_klines(klines, symbol, interval, zigzag_threshold=0.01, min_rr=0.0)
    if setups:
        sid = store.upsert_setup(setups[0])
        store.upsert_lifecycle(sid, TP, state_changed_at=1_700_300_000_000,
                               exited_at=1_700_300_000_000, exit_reason="tp1")


def _build_payloads(store: Store, symbol: str, interval: str) -> dict[str, dict]:
    """'auto' + her açık setup için önceden hesaplanmış grafik yükleri."""
    base = chart_data.build_payload(store, symbol, interval, include_pairs=True)
    payloads: dict[str, dict] = {"auto": base}
    for opt in base.get("setups", []):
        sid = opt["id"]
        payloads[str(sid)] = chart_data.build_payload(
            store, symbol, interval, setup_id=sid, include_pairs=False)
    return payloads


def _safe_js(text: str) -> str:
    """Satır içi <script> kapanışını kazara tetiklemeyi engelle."""
    return text.replace("</", "<\\/")


def build_html(store: Store, symbol: str, interval: str, synthetic: bool) -> str:
    payloads = _build_payloads(store, symbol, interval)
    html = _HTML.read_text(encoding="utf-8")
    lwc_js = _LWC.read_text(encoding="utf-8")

    note = ("SENTETİK DEMO VERİSİ" if synthetic else f"{symbol} {interval}")
    # ensure_ascii=True → tüm non-ASCII \uXXXX olur (U+2028/2029 dahil), JS güvenli.
    payloads_js = _safe_js(json.dumps(payloads, ensure_ascii=True))
    shim = f"""<script>
// ---- QWebChannel TAKLİDİ (statik önizleme) ----------------------------------
const PAYLOADS = {payloads_js};
function _sig() {{ const cbs = []; return {{ connect: f => cbs.push(f),
  emit: (...a) => cbs.forEach(f => f(...a)) }}; }}
const _bridge = {{
  dataReady: _sig(), liveUpdate: _sig(), liveState: _sig(),
  _emit(val) {{
    const p = PAYLOADS[val] || PAYLOADS["auto"];
    this.dataReady.emit(JSON.stringify(p));
    this.liveState.emit(true, "önizleme · {_safe_js(note)}");
  }},
  ready() {{ this._emit("auto"); }},
  requestData(symbol, interval, setup) {{ this._emit(setup); }},
}};
const qt = {{ webChannelTransport: {{}} }};
function QWebChannel(transport, cb) {{ cb({{ objects: {{ bridge: _bridge }} }}); }}
</script>"""

    html = html.replace(
        '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>', shim)
    html = html.replace(
        '<script src="lightweight-charts.standalone.production.js"></script>',
        f"<script>{_safe_js(lwc_js)}</script>")
    return html


def main() -> None:
    ap = argparse.ArgumentParser(description="Canlı grafiği tarayıcıda önizle")
    ap.add_argument("--db", help="SQLite DB yolu (varsayılan: config.DB_PATH)")
    ap.add_argument("--symbol", help="Parite (varsayılan: ilk mevcut)")
    ap.add_argument("--interval", help="Zaman dilimi (varsayılan: 60m varsa)")
    ap.add_argument("--out", default="chart_preview.html", help="Çıktı HTML yolu")
    ap.add_argument("--synthetic", action="store_true", help="Her zaman sentetik demo")
    args = ap.parse_args()

    store = Store(path=args.db) if args.db else Store()

    synthetic = args.synthetic or not _has_klines(store)
    symbol = args.symbol or "DEMOUSDT"
    interval = args.interval or "60m"

    if synthetic:
        # sentetik demo için ayrı bellek-içi DB (gerçek DB'yi kirletme)
        store = Store(path=":memory:")
        _seed_synthetic(store, symbol, interval)
    else:
        pairs = chart_data.available_pairs(store)
        symbol = args.symbol or (pairs["symbols"][0] if pairs["symbols"] else "BTCUSDT")
        ivls = pairs["intervals"]
        interval = args.interval or ("60m" if "60m" in ivls else (ivls[0] if ivls else "60m"))

    html = build_html(store, symbol, interval, synthetic)
    out = Path(args.out)
    out.write_text(html, encoding="utf-8")
    store.close()

    kind = "SENTETİK demo" if synthetic else f"{symbol} {interval}"
    print(f"Önizleme yazıldı → {out.resolve()}  ({kind})")
    print("Tarayıcıda aç: dosyayı çift tıkla ya da `file://` ile aç.")


if __name__ == "__main__":
    main()
