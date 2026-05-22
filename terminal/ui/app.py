"""PySide6 uygulama giriş noktası — QApplication kurulumu + tema."""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from terminal.db.store import Store
from terminal.ui.main_window import MainWindow
from terminal.ui.styles import QSS


def run_app() -> int:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setApplicationName("terminalMiraz")
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)

    store = Store()  # data/terminal.db
    win = MainWindow(store)
    win.show()

    try:
        return app.exec()
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(run_app())
