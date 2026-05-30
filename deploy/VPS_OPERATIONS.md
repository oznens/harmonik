# VPS İşletim Notları (hızlı referans)

> Canlı sistem `/home/harmonik/` altında, `harmonik` kullanıcısıyla çalışır.
> İki ayrı servis + iki ayrı git klonu var. **root ile git komutu çalıştırma** —
> "dubious ownership" çıkar ve pull tutmaz.

## Servisler & klonlar

| Servis | Klon | İçerik |
|---|---|---|
| `harmonik` (paper tracker) | `/home/harmonik/harmonik` | Canlı tarama + paper trade |
| `harmonik-web` (dashboard) | `/home/harmonik/harmonik-web` | Salt-okunur web (paper DB'sini okur) |

> Web klonu paper'ın DB'sini okur: `--db /home/harmonik/harmonik/data/terminal.db`

## Kod güncelleme — DOĞRU yöntem (hep `sudo -u harmonik`)

**Web güncelle:**
```bash
cd /home/harmonik/harmonik-web
sudo -u harmonik git pull origin claude/brave-thompson-XRsFg
sudo systemctl restart harmonik-web
sudo systemctl is-active harmonik-web
```

**Paper güncelle:**
```bash
cd /home/harmonik/harmonik
sudo -u harmonik git pull origin claude/brave-thompson-XRsFg
sudo systemctl restart harmonik
sleep 20 && sudo systemctl is-active harmonik
sudo systemctl show harmonik -p NRestarts --value   # artmıyorsa stabil
```

> ⚠️ `sudo -u harmonik` OLMADAN `git pull` yaparsan "dubious ownership" çıkar,
> pull sessizce tutmaz, servis ESKİ kodu çalıştırmaya devam eder.

## "dubious ownership" çıkarsa düzelt
```bash
sudo chown -R harmonik:harmonik /home/harmonik/harmonik-web
sudo -u harmonik git config --global --add safe.directory /home/harmonik/harmonik-web
```

## Web klonu venv — bağımlılıklar (grafik için ŞART)
Web grafiği matplotlib ister. Yeni venv kurulduysa:
```bash
sudo -u harmonik /home/harmonik/harmonik-web/venv/bin/pip install -q matplotlib pandas mplfinance
sudo systemctl restart harmonik-web
```
> Eksikse: dashboard açılır ama `/chart.png` HTTP 500 verir ("yeterli mum verisi
> yok" yerine grafik gelmez). Log: `tail -n 40 /var/log/harmonik/web.err`

## Sağlık kontrolü (paper)
```bash
sudo systemctl is-active harmonik
sudo systemctl show harmonik -p NRestarts --value
P=$(systemctl show harmonik -p MainPID --value); ls /proc/$P/fd | wc -l   # açık dosya
systemctl status harmonik --no-pager | grep Tasks                          # thread sayısı
sudo journalctl -u harmonik --since "10 minutes ago" | grep -c "too frequent\|Too many open files\|Traceback"
```

## Kaynak ayarları (600 worker için — override.conf)
`/etc/systemd/system/harmonik.service.d/override.conf`:
```ini
[Service]
TasksMax=2000
LimitNOFILE=65536
```
Değişiklik sonrası: `sudo systemctl daemon-reload && sudo systemctl restart harmonik`

## Combos üretimi (kapsam değiştir)
```bash
cd /home/harmonik/harmonik
./venv/bin/python gen_top_combos.py --top 100 --tfs 15m,30m,60m,2h,4h,1d --dry-run  # önce gör
./venv/bin/python gen_top_combos.py --top 100 --tfs 15m,30m,60m,2h,4h,1d            # yaz
```
> 600 worker (100×6) için `--poll-seconds 60` şart (servis dosyasında).
> Her 2h worker'ı arka planda 60m çeker (resample) → istek yükü 600'den fazladır.

## Yedek / geri dönüş
```bash
# Kod yedeğine dön:
cd /home/harmonik/harmonik && sudo -u harmonik git checkout ana-yedek && sudo systemctl restart harmonik
# Tam ortam yedeği: /home/harmonik/yedek-pre600-*.tar.gz  +  ana-yedek (GitHub branch)
```

## Şifreler / portlar
- Web: port `8080`, kullanıcı `admin` (WEB_PASS servis dosyasında).
- MEXC throttle: `MEXC_FUTURES_MIN_INTERVAL` env (varsayılan 0.10 = 10 istek/s).
