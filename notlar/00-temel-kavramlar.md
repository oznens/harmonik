# Temel Kavramlar

Harmonik Trading = Fibonacci oranlarıyla tanımlanan fiyat formasyonlarının
tespiti. Her formasyon, belirli oranlarda hizalanan fiyat noktalarından oluşur.
Amaç: gelecekteki dönüş (reversal) bölgelerini önceden tanımlamak.

## 1. Fibonacci Oranları

Carney'nin kullandığı oranlar (Fibonacci dizisinden türetilir):

### Birincil (primary) oranlar
`0.618`, `0.786`, `1.27`, `1.618`

- `0.618` ve `1.618` → diziden doğrudan gelir (phi).
- `0.786 = √0.618`, `1.27 = √1.618`.
- Bir grafiğin "harmonik" sayılması için fiyatın bu sayılardan belirgin
  şekilde dönmesi beklenir.

### İkincil (secondary) oranlar
`0.382`, `0.50`, `1.00`, `2.0`, `2.24`, `2.618`, `3.14`

PRZ'yi tamamlayıcı sayılardır; birincil sayılar kadar kritik değildir.

### Ekstrem (extreme) oranlar
`2.24`, `2.618`, `3.14` (+ `3.618`)

Fiyat `1.618` projeksiyonunu aştığında devreye girer. Bu seviyelerden
dönüşler keskin ve volatildir.

### Diğer kullanılan oranlar
`0.707` (= √0.50), `0.886` (= √0.786), `1.13` (= √1.27), `1.41` (= √2.0)

### Retracement (geri çekilme) oranları
`0.382`, `0.50`, `0.618`, `0.707`, `0.786`, `0.886` — bir bacağın ne kadarının
geri alındığını ölçer (0 ile 1.0 arası).

### Extension/Projection (uzantı) oranları
`1.13`, `1.27`, `1.41`, `1.618`, `2.0`, `2.24`, `2.618`, `3.14`, `3.618` —
bir bacağın ötesine taşan hareketi ölçer (1.0 üstü).

## 2. Resiprokal (Reciprocal) Oran İlişkileri

AB=CD yapısında C noktası retracement'i ile BC projeksiyonu karşılıklı çalışır:

| C retracement | ↔ | BC projeksiyon |
|---------------|---|----------------|
| 0.382 | ↔ | 2.24 veya 2.618 |
| 0.50  | ↔ | 2.0 |
| 0.618 | ↔ | 1.618 |
| 0.707 | ↔ | 1.41 |
| 0.786 | ↔ | 1.27 |
| 0.886 | ↔ | 1.13 |

Kural: C noktası ne kadar sığ retracement yaparsa, BC projeksiyonu o kadar
uzun olur. Sığ C → uzun CD bacağı.

## 3. XABCD Yapısı (M ve W formasyonları)

Çoğu harmonik formasyon 5 noktalıdır: **X, A, B, C, D**.

- 4 bacak: XA, AB, BC, CD.
- Boğa (bullish) formasyon **W** şeklindedir → dipte alış sinyali.
- Ayı (bearish) formasyon **M** şeklindedir → tepede satış sinyali.
- **D noktası = formasyonun tamamlandığı, işleme girilen nokta (PRZ).**
- **X noktası = formasyonun başlangıcı / geçerlilik sınırı.**

4 noktalı formasyon (AB=CD) ise: A, B, C, D.

Standart dışı yapılar (Shark, 5-0) M/W kalıbına uymaz — kendi noktaları vardır.

## 4. PRZ — Potential Reversal Zone (Potansiyel Dönüş Bölgesi)

Carney'nin temel buluşu. Belirli bir fiyat yapısının **3 veya daha fazla
Fibonacci hesabının tek bir dar bölgede buluşması** = dönüş için aday bölge.

- D noktası civarında birden çok oran (ör. 0.886 XA + 1.27 AB=CD + 1.618 BC)
  yakınlaşır → bu küme PRZ'yi oluşturur.
- Sayılar ne kadar dar aralıkta toplanırsa, formasyon o kadar güçlü.
- İşlem genelde PRZ test edildikten sonra, dönüş teyidiyle açılır.
- "Tanımlayıcı limit" (defining limit): PRZ'deki en kritik tek sayı
  (formasyona göre değişir — ör. Bat'te 0.886 XA, Crab'de 1.618 XA).

## 5. Retracement vs. Extension Formasyonları

**Retracement (geri çekilme) formasyonları** — Gartley, Bat:
- D noktası, X noktasını **aşmadan** (içeride kalarak) tamamlanır.
- D, kritik bir dip/tepenin (X) yeniden testidir.
- Net geçerlilik sınırı: fiyat X'i aşarsa formasyon geçersiz → stop.

**Extension (uzantı) formasyonları** — Butterfly, Crab:
- D noktası, X noktasını **aşar** (XA bacağının uzantısına gider).
- X daha az belirleyicidir; stop loss daha özneldir.
- Aşırı alım/satım uçlarını yakalamaya çalışır; hareket daha keskindir.

## 6. İdeal vs. Perfect Formasyon

- **İdeal (ideal/standard):** Oranlar belirli bir aralıkta olabilir
  (ör. Bat'te B noktası < 0.618). Geçerli formasyonların çoğu budur.
- **Perfect:** En dar, en spesifik hizalanma (ör. Perfect Bat'te B = tam 0.50).
  Daha nadir ama en güvenilir kurulumlardır.

Her formasyon dosyasında hem ideal hem perfect varyant verilmiştir.

## Kaynak

The Harmonic Trader (1999), Böl. 5-6 (Primary/Secondary Numbers, PRZ);
Harmonic Trading Vol. 1, Giriş ve Böl. 4.
