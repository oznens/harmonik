"""Kartlar sekmesi — kapanmış/açık işlemleri terminalMiraz tarzı kartlarla gösterir.

Web dashboard ile AYNI renderer'ı (terminal.web.cards) kullanır → birebir görünüm.
Veriyi DB'den salt-okunur çeker; içerik değişmediyse setHtml çağırmaz (titremesin).
"""
from __future__ import annotations

import logging

from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from terminal.web import cards

log = logging.getLogger(__name__)


class CardsTab(QWidget):
    """İşlem sonucu kartları (XABCD mini grafik + D ZONE/Entry/SL/TP)."""

    def __init__(self, store, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._last_html: str | None = None

        self.view = QWebEngineView(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.refresh()

    def refresh(self) -> None:
        try:
            conn = cards.connect_ro(self.store.path)
            try:
                trades = cards.load_card_trades(conn, limit=60)
            finally:
                conn.close()
        except Exception:
            log.exception("Kartlar yüklenemedi")
            return
        html = cards.cards_page(trades)
        if html == self._last_html:
            return   # değişiklik yok → titreme/scroll sıfırlama yapma
        self._last_html = html
        self.view.setHtml(html)
