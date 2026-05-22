"""Kiraz — terminalMiraz'ın günlük yorumcusu (Claude API ile).

Resmi `anthropic` SDK + `messages.parse()` + Pydantic ile yapılandırılmış çıktı.
3 alanlı çıktı döner: yorum, ders, yarin_risk_modu (hepsi Türkçe kısa metin).
"""
from __future__ import annotations

import logging

import anthropic
from pydantic import BaseModel, Field

from terminal.config import ANTHROPIC_API_KEY, KIRAZ_MODEL
from terminal.learning.journal import JournalEntry, format_metrics_for_prompt

log = logging.getLogger(__name__)


class KirazNotes(BaseModel):
    """Kiraz'ın günlük defter notları."""
    yorum: str = Field(
        description="Bugünün genel performans yorumu, 2-4 cümle. "
                    "Win rate, en çok hangi tip setup'ın çalıştığı, dikkat çeken örüntü."
    )
    ders: str = Field(
        description="Bugünden çıkarılabilecek somut ders, 1-3 cümle. "
                    "Genel laflar değil; metrik-temelli, terminalMiraz'ın gelecekte uygulayacağı bir gözlem."
    )
    yarin_risk_modu: str = Field(
        description="Yarın için risk modu önerisi, 1-2 cümle. "
                    "Örneğin: 'Yarın yalnız HTF uyumlu Kaliteli setup'lara odaklan' veya "
                    "'Pozisyon boyutunu yarıya indir, yeterli kararlı örneklem yok'."
    )


_SYSTEM = """Sen Kiraz'sın — terminalMiraz adlı harmonik formasyon tabanlı bir kripto trade
sisteminin günlük yorumcusu ve defter tutucusu. Türkçe, kısa, doğrudan, çıkış olarak
sayılara dayalı yazarsın. Süslü dil, motivasyon klişesi, "her gün öğreniyoruz" gibi
genel cümleler KULLANMA.

Sana her gün şu metrikler verilir:
- O gün tespit edilen ve sonuçlanan setup sayıları
- TP / STOP / EO (Entry Olmadı) / ZI (Zamansal İptal) dağılımı
- Win Rate = TP / (TP + STOP)
- Pattern, zaman dilimi, yön ve Q kategorisi bazında kırılım
- En iyi ve en zayıf çalışan yapılar

Ürettiğin 3 alan:
1. **yorum**: bugünün genel resmi (2-4 cümle). Sayılar konuşsun.
2. **ders**: somut, metrik-temelli ders (1-3 cümle). Generic olmasın.
3. **yarin_risk_modu**: yarın için aksiyon önerisi (1-2 cümle). Riskli bir günden sonra
   sıkı, başarılı bir günden sonra normal.

Önemli kurallar:
- Örneklem yetersizse ("bugün 2 setup oldu") bunu açıkça söyle; sahte WR yorumları yapma.
- HTF zıt setup'lar elenmişse ve Elenen havuzunda farklı sonuçlanmışsa bunu vurgula.
- AB=CD onayı, Q skoru gibi yapısal göstergeler sonuçla ilişkiliyse bahset.
- Türkçe yaz; teknik terimler (TP, STOP, WR, PRZ, Q skoru) İngilizce kalsın.
"""


class KirazError(Exception):
    """Kiraz çağrısı başarısız."""


class Kiraz:
    """Tek günlük yorum üretir. Daily-once kullanım için tasarlandı."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = (api_key or ANTHROPIC_API_KEY).strip()
        self.model = (model or KIRAZ_MODEL).strip()
        if not self.api_key:
            raise KirazError("ANTHROPIC_API_KEY yok (.env veya parametre).")
        self._client = anthropic.Anthropic(api_key=self.api_key)

    def comment(self, entry: JournalEntry) -> KirazNotes:
        """JournalEntry → KirazNotes (Pydantic, validated)."""
        metrics_text = format_metrics_for_prompt(entry)
        user_msg = (
            f"Bugünün metrikleri:\n\n{metrics_text}\n\n"
            f"Yukarıdaki verilere bakarak yorum, ders ve yarın için risk modu üret."
        )
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=2000,
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                system=_SYSTEM,
                messages=[{"role": "user", "content": user_msg}],
                output_format=KirazNotes,
            )
        except anthropic.AuthenticationError as e:
            raise KirazError(f"Geçersiz ANTHROPIC_API_KEY: {e.message}") from e
        except anthropic.RateLimitError as e:
            raise KirazError(f"Rate limit: {e.message}") from e
        except anthropic.APIError as e:
            raise KirazError(f"Anthropic API hatası: {e}") from e

        notes = response.parsed_output
        if notes is None:
            raise KirazError("Claude refuse veya boş cevap döndü.")
        log.info("Kiraz yorumu üretildi (model=%s, input_tokens=%d, output_tokens=%d)",
                 self.model, response.usage.input_tokens, response.usage.output_tokens)
        return notes
