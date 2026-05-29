# 13 — Price Action / SMC: Harmoniğe Yapısal Onay Katmanı

Harmonik formasyon (XABCD) sadece **matematiksel Fibonacci** der: "fiyat D'ye
gelince dön". Ama piyasa yapıcılar (Smart Money) Fibonacci'yi dinlemez; stop
avlar, boşluk doldurur, yapı kırar. Bu yüzden harmoniğin D noktasına **körü
körüne** girmek yerine, D'de **fiyat hareketinin (Price Action)** trade yönünü
mekanik kurallarla doğrulamasını şart koşarız.

> Amaç: sinyal sayısını azaltıp **kalan sinyallerin Win Rate'ini** yükseltmek.
> "Düşen bıçağı tutma" — D'yi delip geçen trendlerin gereksiz stoplarını ele.

## Katmanlı karar mimarisi

```
[1] HARMONİK TARAYICI   → XABCD bulundu, D noktası (PRZ) belirlendi
        │
[2] PA BÖLGE FİLTRESİ   → D, kurumsal bir bölgeyle çakışıyor mu?
        │  (Order Block · FVG · Liquidity Sweep — aynı TF, sonraki PR'lar)
        ▼
[3] GİRİŞ ONAYI         → ALT TF'de (LTF) yön gerçekten döndü mü?  ← BU DOSYA
        │  (CHoCH / MSB)
        ▼
     İŞLEME GİR
```

Bu dosya **#3 — CHoCH/MSB (giriş onayı)** katmanını tanımlar. Order Block, FVG
ve Liquidity Sweep katmanları sonraki adımlarda eklenecek (aynı kalıp).

---

## #3 — CHoCH / MSB: Alt Zaman Dilimi Yapı Kırılımı

**CHoCH (Change of Character)** = market yapısının karakterini değiştirmesi.
Harmonik üst TF'de (HTF) bulunur; **giriş onayı her zaman alt TF'de (LTF)** aranır.

| Setup TF (HTF) | Onay TF (LTF) |
|---|---|
| 15m / 30m / 1H | 5M |
| 4H | 15M |
| 1D | 1H |
| 1W | 4H |

### Kural (mekanik, IF/THEN)

**Boğa (Bullish) harmonik** — D = dip:
1. Fiyat D'ye (PRZ) iner. Düşüş trendinde sürekli **lower high** (gittikçe alçalan
   tepeler) yapılır.
2. LTF'de en son **onaylanmış swing high**'ı (fractal: kendinden önceki/sonraki
   `n` barın hepsinden yüksek tepe) takip et → `son_direnç`.
3. **Onay:** bir LTF barının **KAPANIŞI** `son_direnç`'in üzerinde gerçekleşirse
   → CHoCH = True. Karakter yukarı döndü, gir.

**Ayı (Bearish) harmonik** — D = tepe: tam tersi. En son swing low bir bar
kapanışıyla **aşağı** kırılırsa CHoCH = True.

### Lookahead yok (gerçek-zaman tutarlılığı)

Bir fractal swing ancak `right` bar sonra **onaylanır**. CHoCH kontrolü, her barda
yalnızca o ana kadar onaylanmış swing'leri görür — backtest ile canlı **birebir**
aynı kararı verir. (Bir swing onaylandığı barda zaten kırılamaz: tanımı gereği o
barın high/low'u swing'i geçemez → yapay erken tetik oluşmaz.)

### Giriş ve emir tipi

- **Agresif (market):** CHoCH kapanışından sonraki bar açılışından gir.
- **Muhafazakâr (limit):** kırılan bölgeye retest beklenir (R:R'yi uçurur).

Bu projede backtest, onaydan sonraki **HTF barı açılışından** market girişi
varsayar; TP/STOP setup'ın HTF seviyelerinde ölçülür. Onaydan **önce** stop
yenirse işlem hiç açılmaz (EO) — ters giden fiyata girmeyiz.

---

## Kodda nerede

| Parça | Yer |
|---|---|
| LTF eşleştirme | `terminal/quality/htf_ltf.py` → `ltf_for()`, `LTF_MAPPING` |
| Swing + CHoCH (saf) | `terminal/detection/structure.py` → `swing_points()`, `check_choch()` |
| Backtest giriş modu | `terminal/karakter/simulator.py` → `entry_mode="choch"` + `ltf_klines` |
| Backtest motoru | `terminal/backtest/engine.py` → `run_backtest(..., ltf_klines=...)` |
| Canlı gate | `terminal/cli/run_live_multi.py` → `--ltf-choch` (paper AKTIF kapısı) |
| Testler | `tests/test_structure.py`, `tests/test_choch_sim.py` |

### Ölç → sonra aç (proje felsefesi)

Diğer yapısal filtreler gibi (#1 BOS, #2 zaman simetrisi) önce **backtest** ile
ölçülür, edge görülürse canlıda açılır:

```bash
# Backtest: choch modunu çalıştırmak için HTF + LTF mum verisi gerekir
#   (run_backtest'e ltf_klines geçilir; UI/CLI veriyi DB'den yükler)

# Canlı paper gate (limit modda en sağlıklı):
python -m terminal.cli.run_live_multi \
    --symbols BTCUSDT,ETHUSDT --intervals 60m,4h \
    --paper --paper-entry-mode limit --ltf-choch
```

> Not: `--ltf-choch` en iyi `--paper-entry-mode limit` ile çalışır. limit modda
> AKTIF = "fiyat PRZ'ye değdi" anıdır; o an LTF'de birkaç onay barı oluşmuştur.
> market modda AKTIF tespit anında tetiklenir (D yeni) → CHoCH henüz oluşmamış
> olabilir; canlı veri çekilemezse fail-open (filtre uygulanmaz, işlem düşmez).

---

## Sıradaki katmanlar (yol haritası)

- **#4 Order Block:** D, geçmişteki son ters-yön kurumsal mum bloğuyla çakışıyor mu.
- **#5 FVG / Imbalance:** D, dolmamış bir fiyat boşluğunun (mıknatıs) içinde mi.
- **#6 Liquidity Sweep:** D barı, soldaki bir dip/tepenin likiditesini iğneyle
  temizleyip gövdeyi geri kapattı mı (stop avı).

Hepsi aynı-TF çalışır (yeni veri altyapısı gerektirmez) ve `confluence` kalıbında
0-100 skor + backtest sweep + canlı gate olarak eklenecek.
