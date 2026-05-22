"""Üst status bar — Aktif / Aday / TP / Stop / Bugün / WR / Toplam sayaçları."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from terminal.ui.data_provider import StatusCounts


def _card(label: str, value: str, value_color: str = None) -> QFrame:
    box = QFrame()
    box.setObjectName("StatusCard")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(2)
    lbl = QLabel(label)
    lbl.setObjectName("StatusLabel")
    lbl.setAlignment(Qt.AlignCenter)
    val = QLabel(value)
    val.setObjectName("StatusValue")
    val.setAlignment(Qt.AlignCenter)
    if value_color:
        val.setStyleSheet(f"color: {value_color};")
    layout.addWidget(lbl)
    layout.addWidget(val)
    return box, val


class StatusBar(QFrame):
    """Üst sayaç barı. update_counts(StatusCounts) ile yenilenir."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from terminal.ui.styles import GREEN, RED, BLUE, ACCENT_GOLD, TEXT
        self._values: dict[str, QLabel] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        for key, label, color in [
            ("aktif",       "AKTİF",        BLUE),
            ("aday",        "ADAY",         ACCENT_GOLD),
            ("tp",          "TP",           GREEN),
            ("stop",        "STOP",         RED),
            ("eo",          "ENTRY YOK",    TEXT),
            ("zi",          "ZAMANSAL",     TEXT),
            ("bugun_setup", "BUGÜNKÜ SETUP", ACCENT_GOLD),
            ("win_rate",    "WINRATE",      GREEN),
            ("toplam",      "TOPLAM KAYIT", TEXT),
        ]:
            box, val = _card(label, "0", color)
            self._values[key] = val
            layout.addWidget(box)
        layout.addStretch()

    def update_counts(self, sc: StatusCounts) -> None:
        self._values["aktif"].setText(str(sc.aktif))
        self._values["aday"].setText(str(sc.aday))
        self._values["tp"].setText(str(sc.tp))
        self._values["stop"].setText(str(sc.stop))
        self._values["eo"].setText(str(sc.eo))
        self._values["zi"].setText(str(sc.zi))
        self._values["bugun_setup"].setText(str(sc.bugun_setup))
        self._values["win_rate"].setText(f"{sc.win_rate:.1f}%")
        self._values["toplam"].setText(str(sc.toplam))
