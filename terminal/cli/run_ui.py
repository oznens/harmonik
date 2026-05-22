"""terminalMiraz masaüstü UI giriş noktası.

Kullanım:
    pip install PySide6   # bir kez
    python -m terminal.cli.run_ui

DB (data/terminal.db) yoksa boş açılır. Önce `run_live.py` veya
`karakter_lab.py` çalıştırarak veri biriktir.
"""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from terminal.ui.app import run_app
    except ImportError as e:
        print(f"PySide6 kurulu değil: {e}", file=sys.stderr)
        print("Kurulum: pip install PySide6", file=sys.stderr)
        return 1
    return run_app()


if __name__ == "__main__":
    sys.exit(main())
