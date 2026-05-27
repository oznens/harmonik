# Lokal'den VPS'teki DB'yi çek + UI'yı aç.
# Kullanım: dosyayı çift tıkla VEYA `.\sync_from_vps.ps1`
#
# İlk çalıştırmada VPS_HOST'u kendi VPS'inle değiştir.

$VPS_HOST = "harmonik@<VPS_IP_BURAYA>"   # örn: harmonik@192.168.1.1
$REMOTE_DB = "/home/harmonik/harmonik/data/terminal.db"
$LOCAL_DB = "data\terminal.db"

# Lokal data klasörü yoksa oluştur
New-Item -ItemType Directory -Force -Path "data" | Out-Null

Write-Host "→ VPS'ten DB indiriliyor..." -ForegroundColor Cyan
scp "$($VPS_HOST):$REMOTE_DB" $LOCAL_DB
if ($LASTEXITCODE -ne 0) {
    Write-Host "⚠ SCP hatası — VPS_HOST ve SSH erişimini kontrol et." -ForegroundColor Red
    Pause
    exit 1
}

# WAL/SHM dosyalarını da çek (varsa — SQLite WAL mode için)
scp "$($VPS_HOST):$REMOTE_DB-wal" "$LOCAL_DB-wal" 2>$null
scp "$($VPS_HOST):$REMOTE_DB-shm" "$LOCAL_DB-shm" 2>$null

Write-Host "✓ DB güncel. UI açılıyor..." -ForegroundColor Green
python -m terminal.ui.app
