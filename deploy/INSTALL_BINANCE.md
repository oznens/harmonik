# Binance Testnet hattı — kurulum / OKX'ten geçiş

OKX demo hattının yerine Binance USDT-M **testnet** hattı. Ayrı klon, ayrı
servis, ayrı DB tablosu (`binance_trades`). Paper hattına dokunmaz.

## 0) Testnet API anahtarı
1. https://testnet.binancefuture.com → giriş (GitHub ile) → **API Key** oluştur.
2. `BINANCE_API_KEY` + `BINANCE_SECRET` (passphrase YOK).
3. Testnet otomatik bakiye verir (~15.000 USDT). Net (one-way) mod servis
   açılışta otomatik ayarlanır.

## 1) Klon + venv (VPS'te)
```bash
sudo -u harmonik git clone -b claude/brave-thompson-XRsFg <repo> /home/harmonik/harmonik-binance
cd /home/harmonik/harmonik-binance
sudo -u harmonik python3 -m venv venv
# SLIM: trade hattı + web YALNIZ httpx ister (PySide6/mplfinance/pandas GEREKMEZ).
sudo -u harmonik venv/bin/pip install -r deploy/requirements-server.txt
```

## 2) Servisleri kur
```bash
sudo cp deploy/harmonik-binance.service /etc/systemd/system/
sudo cp deploy/harmonik-binance-web.service /etc/systemd/system/
sudo systemctl edit harmonik-binance        # BINANCE_API_KEY/SECRET doldur (drop-in)
sudo systemctl edit harmonik-binance-web     # WEB_PASS + key (canlı bakiye için)
sudo systemctl daemon-reload
```

Anahtarları dosyaya yazmak yerine drop-in (override.conf) önerilir:
```
[Service]
Environment=BINANCE_API_KEY=...
Environment=BINANCE_SECRET=...
```

## 3) OKX'i durdur, Binance'i başlat (cutover)
```bash
sudo systemctl disable --now harmonik-okx harmonik-okx-web
sudo systemctl enable --now harmonik-binance harmonik-binance-web
sudo journalctl -u harmonik-binance -n 20 --no-pager
tail -f /var/log/harmonik/binance.log
```
Dashboard: `http://<vps>:8091` (admin / WEB_PASS).

## Config = MEXC paper VPS ile AYNI
Servis (`harmonik-binance.service`) MEXC paper (`harmonik.service`) ile eşleşir:
- `--risk 20` — paper ile aynı sabit risk.
- **PaMonic YOK** → worker otomatik `rr1` target (MEXC `--target-mode rr1`).
- `--entry-type limit` — ideal harmonik fiyat (MEXC `--paper-entry-mode limit`).
- Filtre yok (MEXC `--paper-min-confluence 0` karşılığı, tüm setuplar).
- max-notional / target-margin yok → risk tam $20.

Kaçınılmaz fark: MEXC paper ideal fiyattan %100 dolar; Binance GERÇEK limit emir
(fiyat D'ye dönerse dolar) + engine-yönetimli exit (testnet native TP/SL'i reddediyor).

## Çıkış (TP/SL) mekanizması
Bu testnet borsa-native STOP_MARKET/TAKE_PROFIT_MARKET'i reddediyor (`-4120`).
Çıkış **engine-yönetimli**: `sync()` (her `--sync-seconds`, default 30sn) açık
pozisyonun `markPrice`'ını okur, stop/tp seviyesine değince **MARKET reduceOnly**
ile kapatır. Sonuç: SL/TP `--sync-seconds` çözünürlüğünde uygulanır (15m+ için
yeterli). Servis dururken pozisyon korumasızdır — uzun süre kapalı bırakma.

## Veri kaynağı
- Default: **mainnet fapi** (temiz piyasa yapısı).
- VPS'ten `451` (coğrafi engel) gelirse → `ExecStart`'a **`--testnet-data`** ekle:
  testnet kendi mum verisini kullanır (fiyatlar mainnet'i yakından takip eder,
  fill ile tutarlı olur).

## Reset (sıfırla)
```bash
sudo systemctl stop harmonik-binance
cd /home/harmonik/harmonik-binance && sudo -u harmonik env \
  $(sudo sed -n 's/^Environment=//p' /etc/systemd/system/harmonik-binance.service.d/*.conf) \
  venv/bin/python -m terminal.cli.binance_flat --wipe-db --yes
sudo systemctl start harmonik-binance
```
