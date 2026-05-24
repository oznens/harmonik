"""terminalMiraz canlı tarayıcı — başlatma script'i.

Kullanım (terminal yerine doğrudan IDE'den veya çift tıklamayla çalıştır):
    python start_tracker.py

Önerilen 38 parite-TF kombinasyonunu (config/tracked_combos.txt) tarar.
Durdurmak için Ctrl+C.

Telegram için proje kökünde .env dosyası gerek:
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...
Yoksa sadece DB'ye yazılır.
"""
from __future__ import annotations

import sys
from pathlib import Path

from terminal.cli.run_live_multi import main


# Bu script'in bulunduğu dizini repo kökü kabul et
REPO_ROOT = Path(__file__).resolve().parent
COMBOS_FILE = REPO_ROOT / "config" / "tracked_combos.txt"


if __name__ == "__main__":
    if not COMBOS_FILE.exists():
        print(f"HATA: Kombinasyon dosyası yok: {COMBOS_FILE}", file=sys.stderr)
        sys.exit(1)

    # run_live_multi.main()'a CLI argümanı olarak ilet
    argv = [
        "--combos-file", str(COMBOS_FILE),
        # min-q default 50 (zaten parser default'u), istersen değiştir:
        # "--min-q", "60",
        # Elenen (1.62 AB=CD HTF zıt) setuplar da gelsin:
        # "--include-elenen",
    ]
    # Komut satırından ek bayrak verilmişse onları da ekle
    argv.extend(sys.argv[1:])

    print(f"Başlatılıyor: {COMBOS_FILE.name}")
    print(f"Ek bayraklar: {' '.join(sys.argv[1:]) if len(sys.argv) > 1 else '(yok)'}")
    print(f"Durdurmak için Ctrl+C\n")

    sys.exit(main(argv) or 0)
