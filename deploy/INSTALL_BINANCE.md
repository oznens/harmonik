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
sudo -u harmonik venv/bin/pip install -r requirements.txt
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

## Config (OKX analizinden DÜZELTME)
Servis defaultları (`harmonik-binance.service`):
- `--risk 5` — düşük risk, PaMonic'in dar OB-stoplarını sığdırır.
- **`--max-notional` YOK** — tavan PaMonic'in yüksek-R kazananlarını eliyordu
  (OKX'te cap 6000: +213K backtest → −4K canlı). Sınırsız.
- `--target-margin 30` — her işlem ~$30 teminat, çok pozisyon.
- `--pamonic` — D'de OB olan setuplar (dar stop + yapısal TP). Giriş limit (default).

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
