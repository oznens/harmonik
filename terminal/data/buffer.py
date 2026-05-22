"""RAM içi kline halka tamponu (her parite × aralık için son N kapanmış mum)."""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable


class KlineBuffer:
    """Sabit boyutlu, FIFO mum tamponu. Aynı open_time gelirse üzerine yazar."""

    def __init__(self, maxlen: int = 200) -> None:
        self.maxlen = maxlen
        self._buf: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def bulk_load(self, klines: Iterable[dict[str, Any]]) -> None:
        """Tamponu temizleyip verilen mumlarla doldurur (eski → yeni sıralı bekler)."""
        self._buf.clear()
        for k in klines:
            self._buf.append(k)

    def add(self, kline: dict[str, Any]) -> None:
        """Tek bir mum ekler. Son mumla aynı open_time'a sahipse onu günceller."""
        if self._buf and self._buf[-1]["open_time"] == kline["open_time"]:
            self._buf[-1] = kline
        else:
            self._buf.append(kline)

    @property
    def latest(self) -> dict[str, Any] | None:
        return self._buf[-1] if self._buf else None

    def __len__(self) -> int:
        return len(self._buf)

    def as_list(self) -> list[dict[str, Any]]:
        return list(self._buf)
