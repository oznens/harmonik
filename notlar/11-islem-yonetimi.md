# İşlem Yönetimi — Harmonic Trade Management System

Formasyon tamamlanıp işleme girildikten sonra pozisyonun yönetimi. Carney'nin
amacı: kararları **duyguya değil, piyasanın sinyallerine** dayandırmak. Tüm
parametreler (giriş, hedef, stop) işlem öncesinde tanımlanır.

## Temel Terimler

### PRZ — Potential Reversal Zone
Formasyonun tamamlandığı, Fibonacci projeksiyonlarının buluştuğu alan.
İşlem buraya yakın açılır. (Detay: `10-prz-ve-onay.md`)

### IPO — Initial Profit Objective (İlk Kâr Hedefi)
- Pozisyonun ilk kâr hedefi.
- **Formasyonun uç noktalarına (en yüksek + en düşük) göre** ölçülen bir
  Fibonacci retracement seviyesi.
- En sık: uç noktalardan **0.382** veya **0.618** retracement.
- 0.382 mı 0.618 mi? → 0.382'deki fiyat hareketine bakılır. 0.382 seviyesi
  bir boşluk / ekstrem aralık / kuyruk kapanışıyla "blow out" edilirse →
  **0.618'i IPO al**.
- İlk hedef sonrası bir trend çizgisi ihlali de IPO olabilir.
- Fiyat IPO'ya ulaşıp **net devam etmezse** → kârı kesinleştir (geçici
  tükenme işaretidir).

### Pozisyonu Bölmek (Portioning the IPO)
- Pozisyonu 2 (hatta 3) parçaya bölmek avantajlıdır:
  - Bir parça limit emirle otomatik kâra kilitlenir → işlemin bir kısmı
    kazançlı garanti.
  - Diğer parça "bedavaya devam eder" (ride for free) → büyük hareketi
    kaçırma riski azalır.
- Bu, davranışı duygudan piyasaya kaydırır.

### PPZ — Profit Protection Zone (Kâr Koruma Bölgesi)
- Küçük bir kâr elde edildikten sonra, giriş noktasının ötesinde önceden
  belirlenen seviye → **kârın zarara dönmesini engeller**.
- Temel kural: **"Bir kârın asla zarara dönmesine izin verme."**
- Eşdeğer zaman projeksiyonuyla (aşağıya bak) tanımlanır.
- Bazen PPZ pozisyonu kapatır, sonra fiyat dönüşe devam eder — sinir bozucu
  ama uzun vadede formasyon başarısızlıklarından korur.

### SLZ — Stop Loss Zone (Zarar-Durdur Bölgesi)
- PRZ'nin ötesindeki, **geçersiz formasyonu** temsil eden alan.
- Fiyat buraya girerse → PRZ uygun dönüş noktası değildir; pozisyon kapatılır,
  zarar alınır.
- Her formasyonun kesin stop loss limiti için → `09-formasyon-spec.md`.
  - Retracement formasyonları (Gartley, Bat): stop X noktasının / 1.0–1.13 XA'nın ötesi.
  - Extension formasyonları (Butterfly, Crab): stop daha özneldir
    (Butterfly > 1.414 XA, Crab > 2.0 XA).

### 0.382 Trailer (0.382 Takip Eden Stop)
- IPO'ya ulaşıldıktan sonra kullanılan trailing stop.
- Dönüşün "ol-ya-da-öl" sınırını temsil eder.
- **Dönüş noktasından dönüşün ucuna** (boğada en yüksek, ayıda en düşük)
  ölçülen 0.382 retracement.
- En güçlü dönüşler trend devam etmeden önce yalnızca bu seviyeye kadar geri
  çekilir. Stop, 0.382'nin ötesine geçilince tetiklenir.

### Angle of Ascent/Descent (Çıkış/İniş Açısı)
- Formasyon tamamlandıktan sonraki fiyat hareketinin dikliği.
- Güçlü dönüşler genelde dik trend çizgileri + kararlı devam içerir.
- Ölçülmez ama dikkate alınır.

### Trend Çizgileri
İki tür kullanılır:
1. Dönüş sonrası fiyatın uyduğu genel trend çizgisi → yeni hareketin
   sürdürülebilirliğini ölçer.
2. IPO (genelde 0.382) ile çakışan, formasyonun uç noktalarından (A ve C)
   çizilen trend çizgisi → "kuma çizilen çizgi". Dönüş bu seviyeleri aşarsa
   geçici tepkiden büyük bir hareket olasılığı yüksektir.

## Zaman Hesapları (Time Considerations)

Fiyat zamandan önemlidir; ama zaman trade yönetimini kolaylaştırır.

### Eşdeğer zaman projeksiyonu (Equivalent Time Projection)
- X noktasından orta nokta (B)'ye kadarki süre ölçülür.
- Bu süre B noktasından ileri projekte edilerek yaklaşık **D tamamlanma
  zamanı** bulunur.
- Örnek: X→B 10 gün sürdüyse, B→D de ~10 gün sonra tamamlanmalı.
- Eşdeğer zaman projeksiyonu aynı zamanda **PPZ'yi tanımlar**.

### Alternatif zaman hesabı (Alternate Time Calculation)
- Fibonacci oranları (0.382 – 1.618) zaman ekseninde de uygulanır.
- CD bacağı sıklıkla eşdeğer zamandan önce tamamlanır.

### Minimum 0.382 zaman projeksiyonu
- Formasyon, **0.382 zaman projeksiyonuna ulaşmadan tamamlanmamalı**.
- Örnek: X→B 10 gün ise, B→D en az ~3.82 (≈4) gün işlem görmeli.
- Çok keskin / kısa CD bacağı → kırmızı bayrak; formasyon şüpheli.

## Trading Checklist (İşlem Kontrol Listesi)

1. Bir formasyon var mı?
2. Hangi formasyon?
3. AB=CD var mı?
4. Nerede tamamlanıyor?
5. PRZ'de 3 veya daha fazla sayı çakışıyor mu?
6. Bu sayılar neler?
7. Zaman döngüleri (simetri) ne diyor?
8. Uyarı işareti var mı?
9. PRZ hangi noktada artık geçerli değil? (Stop Loss)
10. Ne kadar risk almam gerekiyor? Almaya razı mıyım?

## Kaynak

Harmonic Trading Vol. 1, Böl. 11 (The Harmonic Trade Management System);
Böl. 9 (Trading Checklist).
