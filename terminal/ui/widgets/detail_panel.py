"""Setup detay paneli (sağ panel): metin bilgileri + outcome düzeltme."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from terminal.timeutil import format_local
from terminal.ui.data_provider import DataProvider, SetupRow

log = logging.getLogger(__name__)


def _fmt(ms: int) -> str:
    return format_local(ms)


OVERRIDE_OPTIONS = ["TP", "STOP", "EO", "ZI", "Aday", "Aktif"]


class DetailPanel(QFrame):
    """Seçilen setup'ın detayını gösterir. show_setup(row, provider) ile güncellenir.

    Sinyal `outcome_overridden` outcome düzeltildiğinde yayınlanır — üst widget
    tabloyu yenilesin diye.
    """

    outcome_overridden = Signal(int)  # setup_id

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from terminal.ui.styles import BG_PANEL, BORDER
        self.setStyleSheet(f"background-color: {BG_PANEL}; border: 1px solid {BORDER};")
        self.setMinimumWidth(380)
        self._current_setup_id: int | None = None
        self._provider: DataProvider | None = None

        self._content = QLabel("Bir setup seçin")
        self._content.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._content.setWordWrap(True)
        self._content.setTextFormat(Qt.RichText)
        self._content.setStyleSheet("padding: 14px; font-size: 12px;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._content)

        # Outcome düzeltme paneli (alt)
        self._override_panel = QFrame()
        self._override_panel.setVisible(False)
        opl = QHBoxLayout(self._override_panel)
        opl.setContentsMargins(8, 4, 8, 8)
        self._chart_btn = QPushButton("📈 Grafiği Aç")
        self._chart_btn.clicked.connect(self._on_open_chart)
        opl.addWidget(self._chart_btn)
        opl.addSpacing(12)
        opl.addWidget(QLabel("Outcome düzelt:"))
        self._override_buttons: list[QPushButton] = []
        for state in OVERRIDE_OPTIONS:
            btn = QPushButton(state)
            btn.clicked.connect(lambda _checked=False, s=state: self._on_override(s))
            opl.addWidget(btn)
            self._override_buttons.append(btn)
        opl.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._override_panel)

    def show_setup(self, row: SetupRow, provider: DataProvider) -> None:
        self._current_setup_id = row.id
        self._provider = provider
        self._override_panel.setVisible(True)
        setup = provider.store.load_setup(row.id)
        if setup is None:
            self._content.setText("(Setup yüklenemedi)")
            return

        risk_pct = abs(setup.stop - setup.entry) / setup.entry * 100 if setup.entry else 0
        reward_pct = abs(setup.tp1 - setup.entry) / setup.entry * 100 if setup.entry else 0
        rr = reward_pct / risk_pct if risk_pct else 0

        # HTF satırı
        htf_line = ""
        if setup.htf_trend:
            arrow = {"bull": "▲", "bear": "▼", "neutral": "─"}.get(setup.htf_trend, "?")
            ok = "✓" if setup.htf_aligned else ("⚠" if setup.htf_aligned is False else "—")
            htf_line = f"<b>HTF ({setup.htf_interval}):</b> {arrow} {setup.htf_trend} {ok}<br>"

        # Karakter skoru
        karakter_line = ""
        kar = provider.store.get_karakter_score(
            setup.symbol, setup.interval, setup.pattern_name, setup.direction,
        )
        if kar:
            karakter_line = f"<b>Karakter:</b> {kar[0]:.0f}/100 ({kar[1]} örneklem)<br>"

        # PRZ bileşenleri
        prz_html = ""
        for label, price in setup.prz_components:
            prz_html += f"&nbsp;&nbsp;{label}: <code>{price:.6g}</code><br>"

        # Pivotlar
        pivots_html = ""
        for k in "XABCD":
            p = setup.pivots[k]
            pivots_html += f"&nbsp;&nbsp;<b>{k}</b> @ {_fmt(p.time)} = <code>{p.price:.6g}</code><br>"

        cat_badge = ""
        if setup.q_category:
            color = {"Kaliteli": "#4caf50", "Normal": "#42a5f5", "Riskli": "#ff9800"}.get(setup.q_category, "#888")
            cat_badge = f' <span style="color: {color}; font-weight: bold;">{setup.q_category}</span>'

        elenen_badge = ' <span style="color: #ef5350;">[ELENEN]</span>' if setup.elenen else ""

        arrow = "▲ BULL" if setup.direction == "bull" else "▼ BEAR"
        dir_color = "#4caf50" if setup.direction == "bull" else "#ef5350"

        html = f"""
        <div style="font-size: 14px; font-weight: bold; color: {dir_color};">
            {arrow}{elenen_badge}
        </div>
        <div style="font-size: 16px; font-weight: bold; margin-top: 4px;">
            {setup.symbol} · {setup.interval} · {setup.pattern_name}
        </div>
        <div style="margin-top: 8px;">
            <b>Q skoru:</b> {setup.q_score or '—'}/100{cat_badge}<br>
            <b>Durum:</b> {row.state}<br>
            {htf_line}{karakter_line}
        </div>
        <hr>
        <div>
            <b>Entry:</b> <code>{setup.entry:.6g}</code><br>
            <b>SL:</b> <code>{setup.stop:.6g}</code> ({risk_pct:.2f}%)<br>
            <b>TP1:</b> <code>{setup.tp1:.6g}</code> ({reward_pct:.2f}%) · R:R <b>{rr:.2f}</b><br>
            <b>TP2:</b> <code>{setup.tp2:.6g}</code><br>
        </div>
        <hr>
        <div><b>PRZ Bileşenleri:</b><br>{prz_html}</div>
        <hr>
        <div><b>Pivotlar:</b><br>{pivots_html}</div>
        <hr>
        <div><b>Oranlar:</b><br>
            &nbsp;&nbsp;B (XA retr.): <code>{setup.b_ratio:.3f}</code><br>
            &nbsp;&nbsp;C (AB retr.): <code>{setup.c_ratio:.3f}</code><br>
            &nbsp;&nbsp;D (XA): <code>{setup.d_ratio:.3f}</code><br>
            &nbsp;&nbsp;BC proj.: <code>{setup.bc_proj:.3f}</code><br>
            &nbsp;&nbsp;CD/AB: <code>{setup.cd_ab_ratio:.3f}</code> {'✓ AB=CD' if setup.ab_cd_equivalent else ''}<br>
        </div>
        <hr>
        <div style="color: #888; font-size: 11px;">
            Tespit edildi: {_fmt(setup.detected_at)}
        </div>
        """
        # Override geçmişi varsa ekle
        overrides = provider.store.get_overrides(row.id)
        if overrides:
            html += '<hr><div><b>Manuel Düzeltmeler:</b><br>'
            for ov in overrides[:5]:
                html += (f'&nbsp;&nbsp;{_fmt(ov["created_at"])}: '
                         f'<b>{ov["original_state"]}</b> → <b>{ov["override_state"]}</b>')
                if ov["reason"]:
                    html += f' — <i>{ov["reason"]}</i>'
                html += '<br>'
            html += '</div>'
        self._content.setText(html)

    def _on_open_chart(self) -> None:
        if self._current_setup_id is None or self._provider is None:
            return
        setup = self._provider.store.load_setup(self._current_setup_id)
        if setup is None:
            QMessageBox.warning(self, "Hata", "Setup yüklenemedi.")
            return
        # Lazy import — mplfinance ağır, sadece chart açılırken yükle
        from terminal.ui.widgets.chart_window import ChartWindow
        try:
            win = ChartWindow(setup, self._provider.store, parent=self,
                              setup_id=self._current_setup_id)
            if win.isVisible() or win.windowTitle():
                win.exec()
        except Exception as e:
            log.exception("ChartWindow açma hatası")
            QMessageBox.critical(self, "Hata", f"Grafik penceresi açılamadı: {e}")

    def _on_override(self, new_state: str) -> None:
        if self._current_setup_id is None or self._provider is None:
            return
        reason, ok = QInputDialog.getText(
            self, "Outcome Düzelt",
            f"Bu setup'ı '{new_state}' olarak işaretle. Neden (opsiyonel):",
        )
        if not ok:
            return
        try:
            self._provider.store.override_outcome(
                self._current_setup_id, new_state, reason.strip()
            )
            self.outcome_overridden.emit(self._current_setup_id)
            QMessageBox.information(
                self, "Düzeltildi",
                f"Setup #{self._current_setup_id} → {new_state}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Hata", f"Düzeltme başarısız: {e}")
