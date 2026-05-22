# terminal/ — terminalMiraz uygulama kodu

Harmonik formasyon tabanlı kripto sinyal terminali. Her şey Python.

## Mimari (tam vizyon)

7 katman:

1. **Veri** — MEXC REST/WebSocket, RAM tampon, SQLite.
2. **Tespit** — ZigZag swing dedektörü + `notlar/09-formasyon-spec.md` eşleştiricisi.
3. **Kalite & Filtre** — Q skoru (Riskli/Normal/Kaliteli), uyarı sinyali kontrolü.
4. **HTF-LTF Kontrol** — üst zaman dilimi trend uyumu; Elenen Setup ayrımı.
5. **Parite Karakter Lab** — ~20K mum üstünde konsept×parite×TF skor matrisi.
6. **Yaşam Döngüsü + Hafıza** — Aday→Aktif→TP/STOP/EO/Zamansal İptal; audit log.
7. **Sunum** — Telegram bot + PySide6 masaüstü UI (Scanner Journal, Trade Playback, Learning Journal).

## Geliştirme fazları

| Faz | İçerik | Durum |
|-----|--------|-------|
| 1 | Veri omurgası (MEXC REST + SQLite + RAM buffer) | ✓ tamam |
| 2 | Formasyon tespit motoru (ZigZag + XABCD eşleştirici) | ✓ tamam |
| 3 | Trade yaşam döngüsü + Telegram bildirim | bekliyor |
| 4 | Q skoru + HTF-LTF kontrol | bekliyor |
| 5 | Parite Karakter Laboratuvarı | bekliyor |
| 6 | PySide6 masaüstü UI | bekliyor |
| 7 | Learning Journal + Kiraz (AI notları) | bekliyor |
| 8 | Ölçek (75 parite) + denetim arayüzü | bekliyor |

## Kullanım

```bash
# bağımlılıklar (bir kez)
pip install -r requirements.txt
pip install -r requirements-dev.txt   # test çalıştırmak için

# 1) Canlı veri akışı (sadece kline, formasyon yok) — Faz 1
python -m terminal.cli.run_data --symbol BTCUSDT --interval 1h

# 2) Tarihsel formasyon taraması (tek seferlik) — Faz 2
python -m terminal.cli.scan_history --symbol BTCUSDT --interval 1h --bars 500
python -m terminal.cli.scan_history --symbol AVAXUSDT --interval 60m --store
# --store: bulunan setup'ları data/terminal.db'ye yazar
# --zigzag 0.012: özel ZigZag eşiği (varsayılan TF'e göre değişir)

# 3) Canlı veri + her kapanan mumda formasyon taraması — Faz 2
python -m terminal.cli.run_live --symbol BTCUSDT --interval 1h
# bootstrap'tan sonra tarihsel formasyonları log'lar, sonra canlı bekler

# Testler
pytest tests/ -v
```

### Geçerli aralık değerleri

`1m`, `5m`, `15m`, `30m`, `60m` (veya `1h` — eş anlamlı), `4h`, `1d`, `1W`, `1M`.

### Veritabanı

`data/terminal.db` — SQLite, WAL modu. Tablolar:
- `klines` — ham mumlar (symbol, interval, open_time PK)
- `setups` — tespit edilen formasyonlar (5 pivot + oranlar + PRZ + Entry/SL/TP)

Yedekleme = dosyayı kopyalamak.

### Tespit edilen formasyonlar (Faz 2)

`notlar/09-formasyon-spec.md` Vol.3 değerleriyle birebir:
- **XABCD M/W:** Gartley, Bat, Alternate Bat, Butterfly, Crab, Deep Crab
- AB=CD onayı (yaklaşıklık ±%10)
- ZigZag pivot dedektörü (yüzde tabanlı, TF başına ayarlanabilir)

PRZ bileşenleri: tanımlayıcı XA + AB=CD katları + BC projeksiyonu uç değerleri.
Entry = tanımlayıcı limit (D ideal). SL = `stop_at_xa` katında. TP1/TP2 =
formasyon uç noktalarından 0.382 / 0.618 IPO.

> Shark + 5-0 + Three Drives (M/W olmayan) ileri fazlarda eklenecek.

## Klasör yapısı

```
terminal/
├── config.py            # genel sabitler
├── data/
│   ├── mexc_client.py   # MEXC REST sarmalayıcı
│   ├── buffer.py        # RAM içi kline halka tamponu
│   └── kline_poller.py  # polling döngüsü, yeni kapanan mum tespiti
├── detection/
│   ├── pivots.py        # ZigZag (yüzde tabanlı)
│   ├── ratios.py        # Fibonacci oran hesaplayıcıları
│   ├── spec.py          # PatternSpec + Vol.3 PATTERNS tablosu
│   ├── models.py        # Setup veri sınıfı
│   ├── matcher.py       # XABCD 5-pivot eşleştirici
│   ├── prz.py           # PRZ + Entry/SL/TP
│   └── scanner.py       # ana orkestratör (klines → list[Setup])
├── db/
│   ├── schema.sql       # SQLite şeması (klines + setups)
│   └── store.py         # DB erişim katmanı
└── cli/
    ├── run_data.py      # Faz 1 (sadece veri)
    ├── scan_history.py  # Faz 2 (tarihsel tarama, tek seferlik)
    └── run_live.py      # Faz 2 (veri + her kapanışta tarama)

tests/
├── synthetic.py         # bilinen oranlardan sentetik XABCD kline üretici
├── test_pivots.py
├── test_matcher.py
└── test_scanner.py
```
