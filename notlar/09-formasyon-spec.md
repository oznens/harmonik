# Formasyon Spec Tablosu — Terminal Referansı

Bu dosya formasyonların **makine-uygulanabilir** kesin parametreleridir.
Veriler büyük ölçüde Harmonic Trading Vol. 3'ün yapılandırılmış özetinden
alınmıştır (Carney'nin en güncel rafine ettiği değerler). Terminal formasyon
tespit motoru bu tabloyu temel almalıdır.

## Notasyon

- **B / D oranları:** XA bacağına göre retracement/extension (aksi belirtilmedikçe).
- **Tolerans:** B noktasının ideal değerden sapma payı — **yüzde puanı** olarak
  (ör. 0.618 ±%3 → geçerli aralık 0.588–0.648).
- **Stop Loss:** geçersizlik sınırı; fiyat bu seviyeyi aşarsa formasyon iptal.
  "AB=CD'ye bağlı" = kesin stop, formasyon içi AB=CD tamamlanmasına göre ayarlanır.

## Ana Tablo (XABCD — M/W formasyonları)

| Formasyon | B (XA ret.) | B tolerans | AB=CD tipi | BC | D = XA | Stop Loss |
|-----------|-------------|------------|------------|-----|--------|-----------|
| **Gartley** | 0.618 | ±%3 (0.588–0.648) | AB=CD veya 1.27 AB=CD | 1.13–1.618 | 0.786 | > 1.0 XA |
| **Deep Gartley** ¹ | 0.618 | ±%3 | AB=CD | 1.618–2.618 | 0.786–0.886 | > 1.0–1.13 XA |
| **Bat** | 0.382–0.50 | ±%5 (0.50 etrafında) | AB=CD min; 1.27 AB=CD tipik | 1.618–2.618 | 0.886 | > 1.13 XA |
| **Alternate Bat** | ≤ 0.382 | −%3 max | 1.618 AB=CD | 2.0–3.618 | 0.886–1.13 ² | > 1.27 XA |
| **Crab** | 0.382–0.618 | ±%5 | AB=CD veya 1.618 AB=CD | 2.618–3.618 | 1.618 | > 2.0 XA |
| **Deep Crab** | 0.886 | +%5 | AB=CD veya 1.618 AB=CD | 2.0–3.618 | 1.618 | > 2.0 XA |
| **Crab @ 1.902** ³ | 0.382–0.618 | ±%5 | AB=CD veya 1.618 AB=CD | 2.0–3.618 | 1.618–1.902 | > 2.0 XA |
| **Butterfly** | 0.786 | ±%3 (0.756–0.816) | AB=CD veya 1.27 AB=CD | 1.618–2.24 | 1.27 | > 1.414 XA |

¹ **Deep Gartley** — özel durum: formasyon içi AB=CD, 0.786 XA'yı aşarsa
devreye girer; ideal giriş 0.886 XA retracement'i olur.
² **Alternate Bat** — D tanımlayıcı: 1.13 XA ekstansiyonu; 0.886 minimum.
³ **Crab @ 1.902** — özel durum: ekstrem fiyat hareketinde 1.618'in ötesine
ek tolerans (1.902 ölçüsü, Bryce Gilmore *Geometry of Markets* 1989'dan).

## Standart Dışı Formasyonlar (M/W olmayan reaksiyon yapıları)

| Formasyon | Noktalar | Yapı | Stop Loss | Kâr hedefi |
|-----------|----------|------|-----------|------------|
| **Shark** | 0-X-A-B-C | A=0X'in 0.382–0.618'i · B=XA'nın 1.13–1.618 ekst. · C=AB'nin 1.618–2.24 ekst. **ve** 0B'nin 0.886–1.13'ü | 1.13 ekstansiyonun hemen ötesi | %50 seviyesi veya Reciprocal AB=CD |
| **5-0** | X-A-B-C-D | B=XA'nın 1.13–1.618'i · C=AB'nin 1.618–2.24'ü · D=BC'nin %50 retracement'i + Reciprocal AB=CD | BC'nin 0.618 retracement'inin ötesi | — |

## Tolerans Kuralları (B noktası, Vol. 3)

- **±%3** → Gartley ve Butterfly. En katı. Gartley B'si 58.8–64.8% dışındaysa:
  - %3'ten az ise → büyük olasılıkla **Bat**'e döner.
  - üst limiti aşarsa → **geçersiz**.
  - Butterfly B'si 78.6% ±%3 dışındaysa → genelde 1.618'de **Crab** oluşur.
- **±%5** → Bat ve Crab dahil diğer yapılar. Hangi tip yapıyla
  uğraşıldığını kategorize etmek için kullanılır.

## Her Formasyon İçin Vol. 3 Yürütme Notları

**Gartley** — Tüm PRZ test edilmeli (özellikle 0.786 XA + AB=CD). İlk test
PRZ'yi **aşmamalı**; geçerli Gartley kararlı dönüş gösterir. Fiyat tüm PRZ'yi
test ettikten **hemen sonra** dönmeli. AB=CD 78.6%'yı aşarsa → Deep Gartley
(0.886) + 1.13 XA stop devreye girer.

**Bat** — 0.886 XA retracement + minimum AB=CD (tipik 1.27 AB=CD) test
beklenir. İlk test 1.0 XA'ya yakın gelebilir. 1.13 XA = ol-ya-da-öl stop.
Fiyat 0.886 XA'yı test ettikten hemen sonra dönmeli.

**Alternate Bat** — 0.886 XA minimum ama 1.0 XA dahil edilmeli. 1.27 XA =
ol-ya-da-öl stop (özellikle 1.13 XA geçerliyse). Fiyat 1.0 XA bölgesini
aştıktan hemen sonra dönmeli.

**Crab** — PRZ testi 1.618 XA'yı aşar, volatil fiyat hareketiyle. 2.0 XA
ötesi = ol-ya-da-öl stop. Tamamlanmadaki dönüş ekstremse fiyat 1.618 XA'yı
aştıktan hemen sonra dönmeli.

**Deep Crab** — B @ 0.886 XA, formasyonu tetikleyen minimum (test edilmeli),
+%5 tolerans. 2.0 XA = ol-ya-da-öl stop. Fiyat 1.618 XA bölgesini aştıktan
hemen sonra dönmeli.

**Butterfly** — B kesin 0.786 XA olmalı (±%3). 1.414 XA = ol-ya-da-öl stop;
AB=CD 1.27 XA'yı aşarsa 1.414'ü tercih et. Fiyat 1.27 XA bölgesini aştıktan
hemen sonra dönmeli.

> Detaylı tanımlar için her formasyonun kendi dosyasına bak (`02`–`08`).
> Vol. 1 ile Vol. 3 arasında küçük rafine farkları varsa, terminal için
> **Vol. 3 değerleri (bu dosya)** esas alınır.

## Kaynak

Harmonic Trading Vol. 3, "Harmonic Patterns" bölümü (yapılandırılmış
formasyon özetleri, s. 92–135).
