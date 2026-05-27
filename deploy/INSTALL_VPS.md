# VPS Kurulum — Ubuntu 22.04 / 24.04

Adım adım talimat. Tahmini süre: 15-20 dk.

---

## 1. VPS'e bağlan

```bash
ssh root@<VPS_IP>
```

## 2. Sistem güncelle ve Python kur

```bash
apt update && apt upgrade -y
apt install -y python3.11 python3.11-venv python3-pip git
```

## 3. Çalıştıracak kullanıcı oluştur (root altında değil)

```bash
adduser --disabled-password --gecos "" harmonik
su - harmonik
```

## 4. Repo'yu klonla + bağımlılıkları kur

```bash
cd ~
git clone https://github.com/oznens/harmonik.git
cd harmonik
git checkout claude/compassionate-cannon-GMeFw   # veya: stable-2026-05-27
python3.11 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## 5. .env dosyası (Telegram için)

```bash
nano .env
```

Yapıştır (kendi chat_id'ni gir):
```
TELEGRAM_BOT_TOKEN=8639365761:AAE1M-usgIWEkMQkUCoELPuqWGWQjIY-_cI
TELEGRAM_CHAT_ID=<senin_chat_id>
```

Kaydet: `Ctrl+O`, Enter, `Ctrl+X`

## 6. Test (1-2 dk)

```bash
# Spot ile dene
python -m terminal.cli.run_live_multi \
    --combos-file config/tracked_combos.txt \
    --paper --min-confluence 70

# Çıktı görmen lazım:
# "Telegram bağlı: @botadın"
# "PAPER TRADE: başlangıç=$1000, mevcut=$1000.00, toplam_trade=0, WR=0.0%"
# "Toplam 14 kombinasyon..."
# "[ATOMUSDT 15m] başlıyor (SPOT, ZigZag 0.0070)"

# Ctrl+C ile durdur

# Futures ile dene (geo-block kontrolü)
python -m terminal.cli.run_live_multi \
    --combos-file config/tracked_combos.txt \
    --futures --paper --min-confluence 70

# "[ATOMUSDT 15m] başlıyor (FUTURES, ZigZag 0.0070)" görmelisin
# Eğer hata: "Access Denied" / 403 → VPS lokasyonu MEXC tarafından engellenmiş
# Bu durumda --futures'ı kaldır, spot kullan
```

## 7. systemd servisi kur (otomatik başlat + restart)

`root` olarak (VPS terminalinde `exit` ile harmonik kullanıcısından çık):

```bash
# Log klasörü
mkdir -p /var/log/harmonik
chown harmonik:harmonik /var/log/harmonik

# Service dosyasını kopyala
cp /home/harmonik/harmonik/deploy/harmonik.service /etc/systemd/system/

# Service'i etkinleştir
systemctl daemon-reload
systemctl enable harmonik
systemctl start harmonik

# Durum kontrolü
systemctl status harmonik
```

## 8. Log takibi

```bash
# Canlı log
tail -f /var/log/harmonik/tracker.log

# Son 100 satır
journalctl -u harmonik -n 100

# Service yeniden başlat
systemctl restart harmonik

# Durdur
systemctl stop harmonik
```

## 9. Güncelleme (yeni commit geldiğinde)

```bash
su - harmonik
cd harmonik
git pull
exit  # root'a dön
systemctl restart harmonik
```

## 10. Paper trade özetini görme

```bash
su - harmonik
cd harmonik
source venv/bin/activate
python -c "
from terminal.db.store import Store
from terminal.paper.engine import PaperEngine
e = PaperEngine(Store())
import json
print(json.dumps(e.summary(), indent=2))
"
```

---

## Sorun Giderme

**"Access Denied" futures'ta:**
VPS lokasyonu engellenmiş. `--futures` flag'ini kaldır, spot çalışır. Veya VPS'i farklı bölgeye taşı (Singapore, Almanya, ABD).

**Telegram bildirim gelmiyor:**
1. `.env` doğru mu — `cat .env`
2. Bot'a Telegram'da `/start` attın mı?
3. Log'da "Telegram bağlı" görüyor musun?
4. `--min-confluence 70` çok sıkı olabilir, düşür: `--min-confluence 50`

**Disk dolması:**
DB ve log büyür. Aylık temizlik:
```bash
# 30 gün öncesi log'ları sil
find /var/log/harmonik -name "*.log" -mtime +30 -delete

# DB boyutu
du -h /home/harmonik/harmonik/data/terminal.db
```
