"""terminalMiraz masaüstü ana pencere."""
from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMainWindow, QTabWidget, QVBoxLayout, QWidget

from terminal.db.store import Store
from terminal.ui.data_provider import DataProvider
from terminal.ui.status_bar import StatusBar
from terminal.ui.widgets.journal_tab import JournalTab
from terminal.ui.widgets.karakter_tab import KarakterTab
from terminal.ui.widgets.potential_tab import PotentialTab
from terminal.ui.widgets.results_tab import ResultsTab
from terminal.ui.widgets.setups_tab import SetupsTab

log = logging.getLogger(__name__)

REFRESH_INTERVAL_MS = 5000  # 5 saniye


class MainWindow(QMainWindow):
    """Status bar + 3 sekme (Setup'lar, Sonuçlar, Karakter Lab)."""

    def __init__(self, store: Store) -> None:
        super().__init__()
        self.setWindowTitle("terminalMiraz")
        self.resize(1280, 760)

        self.store = store
        self.provider = DataProvider(store)

        # Status bar
        self.status_bar = StatusBar()

        # Sekmeler
        self.setups_tab = SetupsTab(self.provider, only_open=True)
        self.potential_tab = PotentialTab(store)
        self.results_tab = ResultsTab(self.provider)
        self.karakter_tab = KarakterTab(self.provider)
        self.journal_tab = JournalTab(store)

        tabs = QTabWidget()
        tabs.addTab(self.setups_tab, "Setup'lar (Aday / Aktif)")
        tabs.addTab(self.potential_tab, "🔮 Potansiyel")
        tabs.addTab(self.results_tab, "Sonuçlar")
        tabs.addTab(self.journal_tab, "📊 Journal")
        tabs.addTab(self.karakter_tab, "Parite Karakter")

        # Container
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.status_bar)
        layout.addWidget(tabs)
        self.setCentralWidget(central)

        # Periyodik yenileme
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh_all)
        self._timer.start()

        # İlk yükleme
        self.refresh_all()

    def refresh_all(self) -> None:
        try:
            self.status_bar.update_counts(self.provider.status_counts())
            self.setups_tab.refresh()
            self.potential_tab.refresh()
            self.results_tab.refresh()
            self.karakter_tab.refresh()
            self.journal_tab.refresh()
        except Exception:
            log.exception("UI yenileme hatası")
