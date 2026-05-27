"""terminalMiraz masaüstü ana pencere."""
from __future__ import annotations

import logging
import os

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
    """Status bar + sekmeler. DB dosyası dış değişikliklerini otomatik yakalar."""

    def __init__(self, store: Store) -> None:
        super().__init__()
        self.setWindowTitle("terminalMiraz")
        self.resize(1280, 760)

        self.store = store
        self.provider = DataProvider(store)
        # DB dosyasının son değişiklik zamanı — dış değişiklik tespiti
        try:
            self._last_db_mtime = os.path.getmtime(store.path)
        except Exception:
            self._last_db_mtime = 0.0

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

    def refresh_all(self, force: bool = False) -> None:
        """Tüm UI sekmelerini DB'den yeniden yükle.

        Args:
            force: True ise Store connection'u her zaman yeniden açılır
                (manuel Yenile butonu). False ise sadece DB mtime
                değişmişse reopen (5sn timer için yeterli).
        """
        try:
            self._check_db_changed(force=force)
            self.status_bar.update_counts(self.provider.status_counts())
            self.setups_tab.refresh()
            self.potential_tab.refresh()
            self.results_tab.refresh()
            self.karakter_tab.refresh()
            self.journal_tab.refresh()
        except Exception:
            log.exception("UI yenileme hatası")

    def _check_db_changed(self, force: bool = False) -> None:
        """DB dosyası dış değiştiyse Store'u yeniden aç (SCP / harici yazım)."""
        try:
            mtime = os.path.getmtime(self.store.path)
        except Exception:
            return
        if not force and mtime <= self._last_db_mtime:
            return  # değişiklik yok, force değil
        if force:
            log.info("Manuel yenile → Store yeniden açılıyor")
        else:
            log.info("DB dosyası değişti → Store yeniden açılıyor")
        try:
            self.store.close()
        except Exception:
            pass
        self.store = Store()
        self.provider = DataProvider(self.store)
        self.setups_tab.provider = self.provider
        self.results_tab.provider = self.provider
        self.karakter_tab.provider = self.provider
        self.potential_tab.store = self.store
        self.journal_tab.store = self.store
        self._last_db_mtime = mtime
