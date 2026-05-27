# Otomatik Journal Özetleri — systemd timer

Pazar 20:00 haftalık + her gece 22:00 günlük Telegram özeti.

## Kurulum (root olarak VPS'te)

```bash
cd /home/harmonik/harmonik

# Service + timer dosyalarını sistemd'ye kopyala
cp deploy/harmonik-journal.service /etc/systemd/system/
cp deploy/harmonik-journal.timer /etc/systemd/system/
cp deploy/harmonik-journal-daily.service /etc/systemd/system/
cp deploy/harmonik-journal-daily.timer /etc/systemd/system/

# Etkinleştir
systemctl daemon-reload
systemctl enable --now harmonik-journal.timer
systemctl enable --now harmonik-journal-daily.timer
```

## Durum kontrolü

```bash
# Aktif timer'ları gör (harmonik-journal*.timer satırlarını gör)
systemctl list-timers --all | grep harmonik

# Bir sonraki tetiklenme zamanları
systemctl status harmonik-journal.timer
systemctl status harmonik-journal-daily.timer
```

## Hemen test et (Pazar beklemeden)

```bash
# Haftalık özet hemen gönder
systemctl start harmonik-journal.service

# Log kontrolü
tail -f /var/log/harmonik/journal.log
```

Telegram'a "📊 TRADING JOURNAL — Son HAFTA" başlıklı uzun mesaj gelmeli.

## Durdurma

```bash
systemctl disable --now harmonik-journal.timer
systemctl disable --now harmonik-journal-daily.timer
```

## Zaman değiştir

`deploy/harmonik-journal.timer` içindeki `OnCalendar` satırını düzenle (UTC zamanı).
İstanbul saatine göre çevir: UTC = İstanbul - 3 saat.

Örnek: Pazar 09:00 İstanbul = 06:00 UTC → `OnCalendar=Sun *-*-* 06:00:00 UTC`

Sonra:
```bash
cp deploy/harmonik-journal.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart harmonik-journal.timer
```
