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
| 3 | Trade yaşam döngüsü + Telegram bildirim | ✓ tamam |
| 4 | Q skoru + HTF-LTF kontrol | ✓ tamam |
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

# 3) Canlı veri + tespit + lifecycle + Telegram bildirim — Faz 3
python -m terminal.cli.tg_setup                        # ilk kez: chat_id keşfi
python -m terminal.cli.run_live --symbol BTCUSDT --interval 1h
python -m terminal.cli.run_live --symbol AVAXUSDT --interval 60m --no-telegram   # sadece DB

# Testler
pytest tests/ -v
```

### Telegram kurulumu

1. [@BotFather](https://t.me/BotFather) ile bot oluştur, token al.
2. `.env` dosyasına yaz: `TELEGRAM_BOT_TOKEN=...`
3. Telegram'da bot'a `/start` yaz (veya herhangi bir mesaj).
4. `python -m terminal.cli.tg_setup` → chat_id'i bulup `.env`'e yazar, test mesajı yollar.

`.env` dosyası `.gitignore`'da — repoya **gitmez**.

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

### Yaşam döngüsü (Faz 3)

Her tespit edilen setup için durum makinesi:

```
        ┌─────────── timeout (Aday > N mum) ─────────────┐
        ▼                                                │
       EO ◀──────────────────────────────────────────  Aday
                                                         │
                                              entry tetiklendi
                                                         │
                                                         ▼
                       ┌── timeout ───────────────────  Aktif ──┐
                       ▼                                         │
                       ZI                                  ┌─────┼─────┐
                                                           ▼     ▼     ▼
                                                           TP   STOP   (devam)
```

- **Aday:** setup tespit edildi, fiyat henüz entry'ye değmedi
- **Aktif:** entry seviyesi tetiklendi (bull: low ≤ entry / bear: high ≥ entry)
- **TP:** TP1'e ulaşıldı
- **STOP:** stop seviyesi kırıldı
- **EO (Entry Olmadı):** Aday'dayken timeout (varsayılan 60 mum)
- **ZI (Zamansal İptal):** Aktif'teyken timeout (varsayılan 120 mum)

Her geçiş `setup_events` audit log'una yazılır.

### Telegram kartları (Faz 3)

- **Aday kartı:** parite + TF + pattern + PRZ + Entry/SL/TP + R:R + B/D oranları + AB=CD + D zamanı + **chart PNG** (X-A-B-C-D etiketli, PRZ kutulu, seviyeli)
- **Aktif kartı:** entry tetik fiyatı + zamanı
- **TP/STOP/ZI/EO kartları:** çıkış fiyatı + % kazanç/kayıp

**Stale Aday filtresi:** D pivot'u son 3 mumdan eski olan Aday'lar Telegram'a
gitmez, sadece DB'ye kaydedilir (bootstrap spam'ini önler).

### Q (Quality) skoru ve HTF/LTF (Faz 4)

Her setup için 0-100 arası bütünleşik kalite ölçütü, kart üstünde rozet:

| Bileşen | Ağırlık | Ne ölçer |
|---------|---------|----------|
| PRZ density | 25 | PRZ bileşenlerinin yakınsama darlığı + sayısı |
| B precision | 15 | B'nin spec bandı merkezine yakınlığı |
| D precision | 25 | D'nin tanımlayıcı ideal'e yakınlığı |
| AB=CD bonus | 15 | AB=CD onayı varsa tam puan |
| BC projection | 5 | BC band içindeyse tam puan |
| HTF alignment | 15 | Üst zaman dilimi trendi setup yönüyle uyumlu mu |

**Kategoriler:**
- 0-49 → **Riskli**
- 50-69 → **Normal**
- 70+ → **Kaliteli**

**HTF/LTF eşleştirmesi:** 15m→1h, 30m→4h, 1h→4h, 4h→1d, 1d→1W

HTF trendi EMA20 vs EMA50 ile belirlenir (±%0.3 nötr bandı). Setup yönü
HTF trendiyle zıt ise **Elenen** bayrağı set edilir — Telegram'a gitmez
(varsayılan), sadece DB'de tutulur. `--include-elenen` ile dahil edilebilir.

`run_live.py` argümanları:
- `--min-q 50` — bu Q skorunun altındakileri Telegram'a gönderme
- `--include-elenen` — elenen setup'ları da gönder
- `--no-htf` — HTF kontrolünü atla (Q skorunda HTF=0)

## Klasör yapısı

```
terminal/
├── config.py            # genel sabitler + .env yükleyici
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
├── lifecycle/
│   ├── states.py        # state sabitleri + timeout varsayılanları
│   └── tracker.py       # Aday → Aktif → TP/STOP/EO/ZI durum makinesi
├── quality/
│   ├── score.py         # Q skoru hesaplayıcı (0-100) + kategori
│   └── htf_ltf.py       # HTF eşleştirme + EMA trend tespiti + uyum kontrolü
├── telegram_bot/
│   ├── client.py        # httpx tabanlı Telegram API sarmalayıcı
│   ├── cards.py         # Aday/Aktif/Exit kart formatlayıcısı
│   └── charts.py        # mplfinance ile setup chart PNG üreteci
├── db/
│   ├── schema.sql       # klines + setups + setup_lifecycle + setup_events
│   └── store.py         # DB erişim katmanı
└── cli/
    ├── run_data.py      # Faz 1 (sadece veri)
    ├── scan_history.py  # Faz 2 (tarihsel tarama, tek seferlik)
    ├── tg_setup.py      # Faz 3 (Telegram chat_id keşfi)
    └── run_live.py      # Faz 3 (veri + tespit + lifecycle + Telegram)

tests/
├── synthetic.py         # bilinen oranlardan sentetik XABCD kline üretici
├── test_pivots.py
├── test_matcher.py
├── test_scanner.py
└── test_lifecycle.py
```
