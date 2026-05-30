"""PaMonic (OB@D) testleri — harmonik D ile Order Block çakışması."""
from __future__ import annotations

from terminal.detection.models import Setup
from terminal.detection.pivots import Pivot
from terminal.quality.pamonic import (
    find_order_blocks, pamonic_confluence,
)

MS = 3_600_000
T0 = 1_700_000_000_000


def _k(i, o, h, l, c):
    return {"open_time": T0 + i * MS, "close_time": T0 + i * MS + MS - 1,
            "open": o, "high": h, "low": l, "close": c,
            "volume": 100.0, "quote_volume": 1e4}


def _piv(i, price, kind):
    return Pivot(index=i, time=T0 + i * MS, price=price, kind=kind)


def _setup(direction="bull", prz_low=98.0, prz_high=101.0, d_index=2):
    pivots = {"X": _piv(0, 90, "high"), "A": _piv(0, 90, "high"),
              "B": _piv(1, 95, "high"), "C": _piv(1, 95, "high"),
              "D": _piv(d_index, (prz_low + prz_high) / 2, "low" if direction == "bull" else "high")}
    return Setup(
        symbol="T", interval="60m", pattern_name="Gartley", direction=direction,
        pivots=pivots, b_ratio=0.6, c_ratio=0.5, d_ratio=0.786, bc_proj=1.3,
        cd_ab_ratio=1.0, ab_cd_equivalent=False, prz_low=prz_low, prz_high=prz_high,
        prz_components=[], entry=(prz_low + prz_high) / 2, stop=prz_low - 5,
        tp1=prz_high + 5, tp2=prz_high + 10, detected_at=T0,
    )


def test_find_order_block_bull():
    # idx1 düşüş mumu (high=101), idx2 yükseliş 101'i kapanışla aşar → bull OB
    kl = [_k(0, 100, 100, 99, 99.5), _k(1, 100, 101, 98, 98.5),
          _k(2, 99, 105, 99, 104), _k(3, 104, 106, 103, 105)]
    obs = find_order_blocks(kl)
    assert len(obs) == 1 and obs[0].kind == "bull"
    assert obs[0].top == 101 and obs[0].bottom == 98
    assert obs[0].mitigated is False


def test_pamonic_bull_overlap():
    # OB [98,101] PRZ [98,101] ile çakışıyor, D idx2'den önce (idx1) → PaMonic var
    kl = [_k(0, 100, 100, 99, 99.5), _k(1, 100, 101, 98, 98.5),
          _k(2, 99, 105, 99, 104)]
    setup = _setup(direction="bull", prz_low=98.0, prz_high=101.0, d_index=2)
    ob = pamonic_confluence(setup, kl)
    assert ob is not None and ob.kind == "bull"


def test_pamonic_none_when_no_overlap():
    # OB [98,101] ama PRZ [120,122] → çakışma yok
    kl = [_k(0, 100, 100, 99, 99.5), _k(1, 100, 101, 98, 98.5),
          _k(2, 99, 105, 99, 104)]
    setup = _setup(direction="bull", prz_low=120.0, prz_high=122.0, d_index=2)
    assert pamonic_confluence(setup, kl) is None


def test_pamonic_wrong_direction():
    # bull OB var ama setup bear → eşleşmez (yön tutmuyor)
    kl = [_k(0, 100, 100, 99, 99.5), _k(1, 100, 101, 98, 98.5),
          _k(2, 99, 105, 99, 104)]
    setup = _setup(direction="bear", prz_low=98.0, prz_high=101.0, d_index=2)
    assert pamonic_confluence(setup, kl) is None


def test_pamonic_unconfirmed_ob_when_sliced_at_d():
    # Çağıran klines'i D'de keserse (impuls barı YOK) → OB henüz onaysız → None.
    # Look-ahead'i çağıran kontrol eder: kl[:2] = impuls (idx2) dahil değil.
    kl = [_k(0, 100, 100, 99, 99.5), _k(1, 100, 101, 98, 98.5),
          _k(2, 99, 105, 99, 104)]
    setup = _setup(direction="bull", prz_low=98.0, prz_high=101.0, d_index=1)
    assert pamonic_confluence(setup, kl[:2]) is None        # impulssuz → OB yok
    assert pamonic_confluence(setup, kl) is not None         # impuls dahil → PaMonic
