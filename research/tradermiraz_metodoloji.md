# tradermiraz — Metodoloji Dökümü & Proje Pusulası

> Kaynak: `kaynaklar/TwExportly_tradermiraz_tweets_2026_05_30.csv` (1012 tweet,
> Mart 2025 → Mayıs 2026). Bu döküm, @tradermiraz hesabının paylaşımlarından
> tersine mühendislikle çıkarılmıştır. Amaç: bu projeyi (harmonik bot) onun
> "terminalMiraz" sistemine sadık şekilde geliştirmek.
>
> **Kullanım:** Projede bir yön belirlerken bu dökümdeki ilkelere bakılır.
> Buradan sapan bir karar alınırsa önce tartışılır (bkz. §7 Pusula).

---

## 1) Trader profili
- ~6 yıllık tam zamanlı trader. İçeriğin yarısı **trade psikolojisi + günlük
  (journal) + risk**, yarısı **harmonik + teknik analiz + plan**.
- Kendi botunu ("terminalMiraz") açıkça anlatıyor — bu proje onun izinde.
- Programı satmıyor/paylaşmıyor, setupları özel; **yalnız public paylaşımlardan**
  metodoloji çıkarılabilir.

## 2) Gerçek edge (önem sırasıyla)
1. **Trend her şeyin önünde — "doğru trene binmek".**
   > "Mesele trene binmek değil, doğru trene binmek… Trend yönü işleminizle
   > çelişirse psikolojiniz sizi ele geçirir."
2. **Harmonikleri trende GÖRE yönet.** Ölçü ezberini (786/886) küçümser;
   asıl mesele harmoniğin hangi fraktal/trend bağlamında çalıştığını
   **back-test** ile bilmek.
   > "Harmonikleri trendin kurallarına göre yönetmezsen — ister harmonik ister
   > price action — yenilirsin."
3. **Risk & sermaye koruma = asıl iş.** Giriş/çıkışta kademeli (DCA).
   > "Teknik analiz para kazanmayı değil, parayı korumayı öğretir."
4. **Psikoloji + trade günlüğü.** Disiplin, kendi hatasıyla yüzleşme.

## 2.5) KRİTİK NÜANS — harmonik = mean-reversion (yön ELEME)
"Trend önceliği" ilkesi YANLIŞ uygulanırsa "trend-tersi harmonikleri eleyelim"
sapmasına yol açar. İKİ bağımsız kaynak bunun yanlış olduğunu söylüyor:
- **Bu projenin backtest'i** (score.py notu): "harmonik mean-reversion setupları
  HTF zıt'ta DAHA İYİ performe ediyor (uyumlu +11R vs zıt +18R)" → HTF Q'dan çıkarıldı.
- **tradermiraz (#9, 9 May):** "Elenen setuplar genel olarak trend tersi… ancak
  garip bir şekilde trend tersi işlemlerde de oldukça iyi sonuçlar görüyorum."

**Sonuç:** Harmoniği YÖNÜNE göre eleme. "Trend"in rolü yön filtresi değil:
(a) pozisyon **yönetimi**, (b) giriş **TEYİDİ/zamanlaması** (fraktal kırılımı).
Harmoniğin doğası ters-tepki (PRZ'den dönüş) olduğu için trend-tersi normaldir.

## 3) ONUN "Price Action" tanımı (KRİTİK)
ICT/SMC framework **DEĞİL**. Kavram sıklığı kanıtı: CHoCH=0, BOS=0,
premium/discount=0, sweep=0, FVG=2. Onun PA yapı taşları:

| Kavram | Anlamı (onun dilinde) |
|---|---|
| **Fraktal** | = Pivot (kendi itirafı: "Pivot → Fraktal"). Swing tabanlı karar / S-R bölgesi, "son umut alanı"; kırılım = fırsat/karar noktası |
| **Kutular** | Mavi = birikim/long bölgesi; Kırmızı/Mor = dağıtım/short/strateji bölgesi. DCA in/out |
| **GAP / FVG / imbalance** | CME gap'leri + fib FVG dolum bölgeleri |
| **Fibonacci** | 0.618 / 0.786 / 0.5 "sağlıklı düzeltme" bölgeleri |
| **2-618 Stratejisi** | Hocası @finansalTRader'dan ("Libra & 2-618"): Çift Dip/Çift Tepe + trend filtresi + momentum + 0.5 testi |
| **PaMonic** | **Price Action + Harmonic** = harmonik D bölgesinde Order Block kullanıp pozisyonu ona göre yönetmek |

> Not: "Order Block @ D" = **PaMonic**, onun gerçekten kullandığı tek SMC öğesi.
> Backtest: **nadir ama güçlü** (BTC 4H 5'te 1 TP zayıf; ETH 2H 4 yapı %100 TP).
> Tüm ICT framework'ünü kullanmıyor.

## 4) En değerli aktüel itiraf (29 May 2026, canlı test)
> "Bazı günler 1 TP'ye karşılık **17 STOP** gördüm… Sorun harmoniklerde değil,
> **harmonikleri filtreleme şeklimde**ydi. PA filtreleri harmoniklerde aktif
> değildi. Düzelttim → **8 TP - 1 STOP**." + "Amaç daha fazla setup değil, daha
> **kaliteli** setup."

**Tek cümle:** Çıplak harmonik kanatır; **harmonik + (trend + fraktal + PaMonic)
filtresi** kazandırır.

## 5) terminalMiraz mimarisi ↔ bu projenin durumu
| terminalMiraz özelliği | Bu projede |
|---|---|
| 75 parite, M15/M30/H1/H2 tarama | ✅ var (250 akış / top-50 futures) |
| Analiz katmanları (trend→harmonik→özel konsept) | ✅ katmanlı yapı var |
| HTF-LTF kontrol → "Elenen Setup" | ✅ var |
| Karakter Tanıma Laboratuvarı (20k mum) | ✅ var |
| rr1 (1:1) + ileride 3 risk modu (Güvenli/Dengeli/Riskli) | ✅ rr1 var; 3 mod yok |
| Telegram'da konsept görseliyle sinyal | ✅ kart/grafik var |
| SQL DB (setup öncesi/sonrası/sonuç) | ✅ store var |
| **Price Action Labs: TP / Giriş / Stop Lab** (2020-26 + mevsimsellik) | ❌ yok |
| **2-618 (Çift Dip/Tepe) stratejisi** otomatik tespit | ❌ yok |
| **PaMonic** (OB @ harmonik D) confluence | ❌ yok |
| "öğrenci" — sistemin X'te kendi paylaşması | ❌ yok |

## 6) Eksikler (öncelik sırası)
1. **Harmoniklere PA filtresi** (onun 1:17 → 8:1 dönüşü) — trend + fraktal teyidi.
2. **Price Action Labs** (Giriş/Stop/TP Lab + mevsimsellik) — Karakter Lab'in kardeşi.
3. **2-618 (Çift Dip/Tepe) stratejisi** — ayrı konsept dedektörü.
4. **PaMonic** (OB@D) — sade haliyle, confluence olarak.

## 7) PUSULA — sapma kontrol listesi
Yeni bir özellik/karar bu ilkelere uymuyorsa, uygulamadan ÖNCE tartışılır:

- [ ] **Trend doğru rolde mi?** Trend YÖN filtresi DEĞİL — harmonik mean-reversion
      olduğundan trend-tersi setup ELENMEZ (bkz. §2.5; proje + tradermiraz aynı
      veriyi gördü). Trendin rolü: yönetim + giriş TEYİDİ (fraktal). "Trend-tersi
      harmonikleri eleyelim" = SAPMA, uyar.
- [ ] **Harmonik tek başına mı çalışıyor?** Çıplak harmonik kanatır — ama çözüm
      yön elemek değil, **giriş teyidi/kalitesi** (fraktal kırılımı + PaMonic).
      "Daha kaliteli setup > daha çok setup."
- [ ] **SMC/ICT aşırılığı var mı?** tradermiraz CHoCH/BOS/premium-discount
      kullanmıyor. Tek SMC öğesi = OB@D (PaMonic). ICT framework'üne sapma = uyarı.
- [ ] **Risk/sermaye koruma merkezde mi?** rr1, kademeli (DCA), stop disiplini.
      "Önce parayı koru."
- [ ] **Veriyle mi karar?** Yeni konsept eklenince mutlaka backtest/Lab ile ölç
      (mevsimsellik dahil). Teoriyle değil veriyle.
- [ ] **Sadelik korunuyor mu?** Çok-ajanlı "konsey", ağır framework gibi
      fazlalıklar onun yaklaşımında yok — sade katmanlı filtre yeterli.

## 8) 2-618 Stratejisi — DOĞRULANMIŞ spec (web kaynağı + kullanıcı tarifi)
Kanonik "2618 formasyonu" (coinotag/coinnewstr) + kullanıcının görselli tarifi
birebir aynı. `terminal/detection/two_618.py` bunu uygular.

**Yapı:** BOZULMUŞ (neckline kırılmış) çift dip / çift tepe. Çift tepe: "boyun
bölgesi kırıldıktan sonra fiyat düşer, ama düşüş sürmez ve tekrar yükselir."

**Kurallar (alıntı):**
- "trendi çeviren son harekete Fibonacci çekilir" → 4 (ikinci dip/tepe) → 5 (lokal uç) bacağı.
- "0.618 Fibonacci seviyesine gelmesi ile işleme girilir" → giriş = 0.618 retracement.
- Stop: "çift dip → dip noktasının altı; çift tepe → tepe noktasının üzeri" (= 4 seviyesi).
- "Hedef noktaları sırasıyla 0 ile -0.272" → Hedef1 = 5 (0 seviyesi); Hedef2 = 1.272 uzama.

**Bizim ek (tradermiraz'ın katkıları — base formasyonda YOK, opsiyonel):**
trend filtresi (yön ELEME — bkz §2.5), momentum onayı, 0.5 seviyesi ikincil test.
Şimdilik eklenmedi; ölçümden sonra değerlendirilir.

Kaynak: coinotag.com/2618-formasyonu-nedir-nasil-kullanilir (HTTP doğrulandı,
2026-05-30). Detektör R:R ~1.618 (0.618/0.382 geometrisi).

## 9) BEKLEYEN KARARLAR (gelecekte tekrar bakılacak)

### 9.1 PaMonic (OB@D) → 200 örneklemde tekrar değerlendir ⏳
**Durum:** PaMonic dedektörü (`terminal/quality/pamonic.py`) + geçmiş analiz aracı
(`terminal/cli/pamonic_gecmis.py`) hazır. Canlıya KATILMADI (kullanıcı kararı:
"şimdilik bırak, 200 örneklem gelince bak").

**İlk ölçüm (2026-05-30, 40 sonuçlanmış paper işlemi):**
- Tümü: 40 işlem, %62.5 WR, +71.66$
- PaMonic VAR: 16 işlem, %68.8 WR, **+70.53$ (toplam kârın %98'i!)**
- PaMonic YOK: 24 işlem, %58.3 WR, +1.13$ (çok işlem, ~sıfır kâr)
- Pattern: 1.27 AB=CD %70→%86, Gartley %50→%60, Bat %33→%33 (etkisiz)

**Sonuç:** Umut verici (kâr OB'li işlemlerde yoğun) AMA örneklem KÜÇÜK — %6.2 WR
farkı 40 işlemde istatistiksel kesin değil.

**KARAR KURALI:** Paper geçmişi **≥200 sonuçlanmış işleme** ulaşınca analizi
tekrar çalıştır:
```bash
cp /home/harmonik/harmonik/data/terminal.db /tmp/analiz.db
./venv/bin/python -m terminal.cli.pamonic_gecmis --db /tmp/analiz.db
rm /tmp/analiz.db
```
- PaMonic WR hâlâ belirgin yüksek + kâr konsantrasyonu sürüyorsa → **Shadow mod**
  (canlıda hesapla+göster, engelleme; daha da büyük örneklemle teyit) → sonra enforce.
- Fark erimişse → küçük örneklem yanılsamasıydı, bırak.

**Pusula notu:** Doğrudan ENFORCE (PaMonic yoksa girme) küçük örneklemde riskli;
işlem sayısını %40'a düşürür. tradermiraz'ın yolu da "önce gözlemle". Shadow > Enforce.

---

*Bu döküm yaşayan bir belgedir; yeni tweet/analiz geldikçe güncellenir.*
