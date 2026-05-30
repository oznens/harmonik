"""Price Action giriş denetimi — botun açtığı setup 3 kontrol noktasına uyuyor mu?

Kullanıcının "Check Listesi"ni mekanik olarak doğrular:
  #1 Doğru yer:  D, geçmiş bir Order Block / FVG bölgesinin içinde mi?
  #2 Doğru zaman: girişten önce ALT TF'de CHoCH (yapı kırılımı) onaylandı mı?
  #3 Doğru stop:  stop, fiyatı döndüren PA yapısının (sweep iğnesi / OB kutusu)
                  arkasında mı — yoksa harmonik/sabit-% stop mu?

Saf fonksiyonlar; canlı entry mantığını DEĞİŞTİRMEZ, sadece raporlar/ölçer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from terminal.detection.structure import check_choch
from terminal.quality.smc import SmcResult, compute_smc


def pa_stop(
    setup: Any,
    klines: list[dict[str, Any]],
    sr: SmcResult,
    buffer_pct: float = 0.0005,
) -> tuple[float | None, str]:
    """PA mantığına göre stop'un OLMASI gereken seviye + dayanağı.

    Bull: tetikleyen yapının ALTINA (en düşük aday = en güvenli), buffer kadar.
      - Sweep: D barının iğnesi (low) altı.
      - Order Block: OB kutusunun tabanı altı.
      - FVG: boşluğun tabanı altı.
    Bear: yapının ÜSTÜNE. Hiçbiri yoksa (None, "") → harmonik stop'a düşülür.
    """
    bull = setup.direction == "bull"
    d_time = setup.pivots["D"].time
    d_idx = next((i for i, k in enumerate(klines) if k["open_time"] == d_time), None)

    cands: list[tuple[float, str]] = []
    if sr.sweep and d_idx is not None:
        cands.append((klines[d_idx]["low"] if bull else klines[d_idx]["high"], "sweep iğnesi"))
    if sr.order_block and sr.ob_zone is not None:
        cands.append((sr.ob_zone["bottom"] if bull else sr.ob_zone["top"], "order block"))
    if sr.fvg and sr.fvg_zone is not None:
        cands.append((sr.fvg_zone["bottom"] if bull else sr.fvg_zone["top"], "fvg"))
    if not cands:
        return None, ""

    if bull:
        level, basis = min(cands, key=lambda c: c[0])
        return level * (1 - buffer_pct), basis
    level, basis = max(cands, key=lambda c: c[0])
    return level * (1 + buffer_pct), basis


@dataclass
class PaChecklist:
    zone_ok: bool                 # #1
    zone_detail: str
    choch_ok: bool | None         # #2 (None = LTF verisi yok, doğrulanamadı)
    choch_detail: str
    stop_ok: bool                 # #3
    current_stop: float
    pa_stop_level: float | None
    stop_detail: str
    smc_score: int

    def all_pass(self) -> bool:
        return self.zone_ok and self.choch_ok is True and self.stop_ok


def pa_checklist(
    setup: Any,
    klines: list[dict[str, Any]],
    ltf_klines: list[dict[str, Any]] | None = None,
    stop_tol_pct: float = 0.003,
) -> PaChecklist:
    """Bir setup için 3 kontrol noktasını değerlendir.

    Args:
        klines: setup TF'sinin mum dizisi (D dahil).
        ltf_klines: ALT TF mum dizisi (CHoCH doğrulaması için). Yoksa #2 = None.
        stop_tol_pct: #3 için mevcut stop, PA stop'a bu yakınlıktaysa "doğru".
    """
    sr = compute_smc(setup, klines)

    # #1 Bölge
    zone_ok = sr.order_block or sr.fvg
    z = []
    if sr.order_block:
        z.append(f"OB {sr.ob_zone['bottom']:.6g}-{sr.ob_zone['top']:.6g}")
    if sr.fvg:
        z.append(f"FVG {sr.fvg_zone['bottom']:.6g}-{sr.fvg_zone['top']:.6g}")
    if sr.sweep:
        z.append("sweep✓")
    zone_detail = " · ".join(z) if z else "D hiçbir OB/FVG/sweep bölgesinde değil"

    # #2 CHoCH
    if ltf_klines is None:
        choch_ok: bool | None = None
        choch_detail = "LTF verisi yok → doğrulanamadı"
    else:
        d_time = setup.pivots["D"].time
        after = [k for k in ltf_klines if k["open_time"] > d_time]
        cr = check_choch(after, setup.direction)
        choch_ok = cr.confirmed
        choch_detail = (f"kırılan seviye {cr.broken_level:.6g}"
                        if cr.confirmed else "LTF'de yapı kırılımı (CHoCH) yok")

    # #3 Stop
    pa_level, basis = pa_stop(setup, klines, sr)
    if pa_level is None:
        stop_ok = False
        stop_detail = "PA yapısı yok → stop dayanağı belirsiz (harmonik/sabit-%)"
    else:
        diff_pct = abs(setup.stop - pa_level) / setup.entry if setup.entry else 1.0
        stop_ok = diff_pct <= stop_tol_pct
        stop_detail = (f"PA stop ({basis}) {pa_level:.6g} | mevcut {setup.stop:.6g} "
                       f"| sapma {diff_pct * 100:.2f}%")

    return PaChecklist(
        zone_ok=zone_ok, zone_detail=zone_detail,
        choch_ok=choch_ok, choch_detail=choch_detail,
        stop_ok=stop_ok, current_stop=setup.stop, pa_stop_level=pa_level,
        stop_detail=stop_detail, smc_score=sr.score,
    )


def format_checklist(setup: Any, c: PaChecklist) -> str:
    """EVET/HAYIR check listesi metni."""
    def mark(v: bool | None) -> str:
        return "✅ EVET" if v is True else ("⚠️  ?" if v is None else "❌ HAYIR")

    return "\n".join([
        f"━━ PA CHECK: {setup.direction.upper()} {setup.pattern_name} "
        f"{getattr(setup, 'symbol', '')} {getattr(setup, 'interval', '')} "
        f"(SMC={c.smc_score}) ━━",
        f"  1) Doğru yer (OB/FVG):   {mark(c.zone_ok)}   {c.zone_detail}",
        f"  2) Doğru zaman (CHoCH):  {mark(c.choch_ok)}   {c.choch_detail}",
        f"  3) Doğru stop (PA):      {mark(c.stop_ok)}   {c.stop_detail}",
        f"  → Giriş mantığı %100 doğru mu: {mark(c.all_pass())}",
    ])
