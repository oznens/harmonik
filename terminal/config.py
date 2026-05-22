"""Terminal genel konfigürasyonu."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "terminal.db"

MEXC_REST_BASE = "https://api.mexc.com"

# MEXC v3 kline aralık değerleri: 1m, 5m, 15m, 30m, 60m, 4h, 1d, 1W, 1M
# Kullanıcı dostu eşlemeler de kabul edilir (1h -> 60m).
INTERVAL_ALIASES = {
    "1h": "60m",
}

VALID_INTERVALS = {"1m", "5m", "15m", "30m", "60m", "4h", "1d", "1W", "1M"}

INTERVAL_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "60m": 3600,
    "4h": 14400,
    "1d": 86400,
    "1W": 604800,
}

# Her (parite, aralık) için RAM'de tutulan kapanmış mum sayısı.
BUFFER_SIZE = 200

# REST polling sıklığı (saniye). Yeni kapanan mumu tespit etmek için.
POLL_INTERVAL_SECONDS = 10

# HTTP timeout (saniye).
HTTP_TIMEOUT = 10
