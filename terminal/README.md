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
| 1 | Veri omurgası (MEXC REST + SQLite + RAM buffer) | **şu an** |
| 2 | Formasyon tespit motoru (ZigZag + XABCD eşleştirici) | bekliyor |
| 3 | Trade yaşam döngüsü + Telegram bildirim | bekliyor |
| 4 | Q skoru + HTF-LTF kontrol | bekliyor |
| 5 | Parite Karakter Laboratuvarı | bekliyor |
| 6 | PySide6 masaüstü UI | bekliyor |
| 7 | Learning Journal + Kiraz (AI notları) | bekliyor |
| 8 | Ölçek (75 parite) + denetim arayüzü | bekliyor |

## Faz 1 kullanım

```bash
# bağımlılıklar (bir kez)
pip install -r requirements.txt

# tek parite × tek aralık için canlı veri akışı
python -m terminal.cli.run_data --symbol BTCUSDT --interval 1h
python -m terminal.cli.run_data --symbol ETHUSDT --interval 15m
```

Çıktı: her yeni **kapanmış** mum konsola log'lanır ve `data/terminal.db`
dosyasına yazılır. Ctrl+C ile temiz kapanır.

### Geçerli aralık değerleri

`1m`, `5m`, `15m`, `30m`, `60m` (veya `1h` — eş anlamlı), `4h`, `1d`, `1W`, `1M`.

### Veritabanı

`data/terminal.db` — SQLite. Tek tablo (Faz 1): `klines`.
Yedekleme = dosyayı kopyalamak.

## Klasör yapısı

```
terminal/
├── config.py           # genel sabitler
├── data/
│   ├── mexc_client.py  # MEXC REST sarmalayıcı
│   ├── buffer.py       # RAM içi kline halka tamponu
│   └── kline_poller.py # polling döngüsü, yeni kapanan mum tespiti
├── db/
│   ├── schema.sql      # SQLite şeması
│   └── store.py        # DB erişim katmanı
└── cli/
    └── run_data.py     # Faz 1 giriş noktası
```
