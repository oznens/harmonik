# Notlar — Harmonik Formasyon Bilgi Bankası

Scott Carney'nin 4 kitabından (`kaynaklar/`) çıkarılan yapılandırılmış notlar.
Bu klasör projenin kalıcı bilgi bankasıdır; terminal bu notlara göre yazılacak.

## Dosyalar

**Formasyon tanımları (öğrenme/açıklama):**

| Dosya | İçerik |
|-------|--------|
| [`00-temel-kavramlar.md`](00-temel-kavramlar.md) | Fibonacci oranları, XABCD yapısı, PRZ, retracement/extension ayrımı |
| [`01-ab-cd.md`](01-ab-cd.md) | AB=CD ve Reciprocal AB=CD — tüm formasyonların temeli |
| [`02-gartley.md`](02-gartley.md) | Gartley formasyonu |
| [`03-bat.md`](03-bat.md) | Bat ve Alternate Bat |
| [`04-butterfly.md`](04-butterfly.md) | Butterfly formasyonu |
| [`05-crab.md`](05-crab.md) | Crab ve Deep Crab |
| [`06-shark.md`](06-shark.md) | Shark formasyonu |
| [`07-5-0.md`](07-5-0.md) | 5-0 formasyonu |
| [`08-three-drives.md`](08-three-drives.md) | Three Drives formasyonu |

**Terminal uygulaması için (makine-uygulanabilir):**

| Dosya | İçerik |
|-------|--------|
| [`09-formasyon-spec.md`](09-formasyon-spec.md) | **Spec tablosu** — her formasyonun kesin parametreleri, B toleransları, stop loss limitleri (Vol. 3). Tespit motorunun temel referansı. |
| [`10-prz-ve-onay.md`](10-prz-ve-onay.md) | PRZ hesaplama/çakışma kuralları, Terminal Price Bar, ideal dönüş, uyarı sinyalleri (blowout) |
| [`11-islem-yonetimi.md`](11-islem-yonetimi.md) | İşlem yönetimi: IPO, PPZ, SLZ, 0.382 trailer, zaman projeksiyonları, kontrol listesi |
| [`12-rsi-bamm.md`](12-rsi-bamm.md) | RSI BAMM — RSI + harmonik formasyon onay/diverjans stratejisi |
| [`13-price-action-smc.md`](13-price-action-smc.md) | **Price Action / SMC** — harmoniğe yapısal onay katmanı: #3 CHoCH/MSB (alt TF giriş onayı) + #4-6 SMC bölge filtreleri (Order Block / FVG / Liquidity Sweep). |

## Hızlı Referans Tablosu

XABCD 5 noktalı formasyonlar — D noktası = formasyonun tamamlanma (PRZ) noktası.

| Formasyon | Tip | B noktası | D noktası (PRZ tanımlayıcı) | BC projeksiyon | AB=CD |
|-----------|-----|-----------|------------------------------|----------------|-------|
| **Gartley** | Retracement | 0.618 XA | 0.786 XA | 1.27 – 1.618 | Eşit (equivalent) |
| **Bat** | Retracement | < 0.618 XA (0.50 / 0.382 tercih) | 0.886 XA | 1.618 – 2.618 | Min eşit; 1.27 alternatif yaygın |
| **Alternate Bat** | Extension | ≤ 0.382 XA | 1.13 XA | ≥ 2.0 (çoğu 2.618 / 3.14) | — (genelde yok) |
| **Butterfly** | Extension | 0.786 XA | 1.27 XA | 1.618 – 2.24 | Min eşit; 1.27 alternatif yaygın |
| **Crab** | Extension | ≤ 0.618 XA | 1.618 XA | 2.618 / 3.14 / 3.618 | 1.27 / 1.618 alternatif |
| **Deep Crab** | Extension | 0.886 XA | 1.618 XA | 2.0 – 3.618 | 1.27 alternatif |

Standart dışı (M/W olmayan) reaksiyon formasyonları:

| Formasyon | Noktalar | Anahtar oranlar |
|-----------|----------|-----------------|
| **Shark** | 0-X-A-B-C | A = 0X'in 0.382–0.618'i · B = XA'nın 1.13–1.618 ekstansiyonu · C = AB'nin 1.618–2.24 ekstansiyonu **ve** 0B'nin 0.886–1.13'ü |
| **5-0** | X-A-B-C-D | B = XA'nın 1.13–1.618'i · C = AB'nin 1.618–2.24'ü · D = BC'nin %50 retracement'i + Reciprocal AB=CD |
| **AB=CD** | A-B-C-D | C = AB'nin 0.382–0.886'sı · D = resiprokal BC projeksiyonu (1.13–3.618) |
| **Three Drives** | 3 itiş | Retracement ~0.618/0.786 · Drive projeksiyonu ~1.27/1.618 · simetri esas |

> Not: **Cypher** formasyonu bu 4 kaynakta yer almaz (Carney'nin formasyonu değildir).
> Eklenmesi istenirse ayrı bir kaynak gerekir.
