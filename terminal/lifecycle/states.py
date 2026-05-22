"""Setup yaşam döngüsü durumları + geçiş kuralları."""
from __future__ import annotations

# Setup state'leri
ADAY = "Aday"
AKTIF = "Aktif"
TP = "TP"
STOP = "STOP"
ZI = "ZI"   # Zamansal İptal
EO = "EO"   # Entry Olmadı

TERMINAL_STATES = {TP, STOP, ZI, EO}

# Varsayılan zaman aşımları (mum sayısı, D pivotundan/entry'den itibaren)
DEFAULT_TIMEOUTS = {
    "aday_bars":  60,    # D pivot'tan sonra bu kadar mumda entry yoksa → EO
    "aktif_bars": 120,   # Entry'den sonra bu kadar mumda TP/SL yoksa → ZI
}
