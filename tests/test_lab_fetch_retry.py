"""karakter_lab veri çekimi: rate-limit (510) lab'i çökertmesin (retry/backoff)."""
from __future__ import annotations

import terminal.karakter.runner as runner
from terminal.data.mexc_futures import MexcFuturesError
from terminal.karakter.runner import _fetch_retry


def test_fetch_retry_returns_value_on_success():
    assert _fetch_retry(lambda: [1, 2, 3], "tag") == [1, 2, 3]


def test_fetch_retry_gives_up_after_attempts(monkeypatch):
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)  # bekleme yok (hızlı test)
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise MexcFuturesError("futures API: 510 too frequent")

    out = _fetch_retry(boom, "tag", attempts=3)
    assert out is None          # vazgeçti (lab çökmedi)
    assert calls["n"] == 3      # 3 kez denedi


def test_fetch_retry_succeeds_after_transient_error(monkeypatch):
    monkeypatch.setattr(runner.time, "sleep", lambda *_: None)
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] < 2:
            raise MexcFuturesError("510")
        return ["ok"]

    assert _fetch_retry(flaky, "tag", attempts=5) == ["ok"]
    assert state["n"] == 2      # ilk deneme 510, ikinci başarılı
