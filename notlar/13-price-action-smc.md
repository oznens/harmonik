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
[2] PA BÖLGE FİLTRESİ   → D, kurumsal bir bölgeyle çakışıyor mu?  ← #4-6
        │  (Order Block · FVG · Liquidity Sweep — aynı TF, --min-smc)
        ▼
[3] GİRİŞ ONAYI         → ALT TF'de (LTF) yön gerçekten döndü mü?  ← #3
        │  (CHoCH / MSB, --ltf-choch)
        ▼
     İŞLEME GİR
```

Bu dosya **#3 — CHoCH/MSB (giriş onayı)** ve **#4-6 — SMC bölge filtreleri
(Order Block · FVG · Liquidity Sweep)** katmanlarını tanımlar. Hepsi uygulandı.

### ANA ANAHTAR (tek düğme: PA açık ↔ salt harmonik)

Tüm Price Action katmanını tek hamlede aç/kapat:

| Yöntem | Aç | Kapat (salt harmonik) |
|--------|-----|------------------------|
| CLI | `--price-action` | `--no-price-action` (veya hiçbiri) |
| Env | `HARMONIK_PRICE_ACTION=on` | `=off` (veya tanımsız) |

`--price-action` = `--ltf-choch` + `--min-smc 30` (elle `--min-smc 60` verirsen o
korunur). Hiçbiri verilmezse **varsayılan KAPALI = eski salt-harmonik davranış**.

**Sunucuda (systemd) unit'e dokunmadan toggle:** `pa.env` dosyası (`EnvironmentFile`)
içinde `HARMONIK_PRICE_ACTION=on|off` → değiştir + `systemctl restart harmonik`.
Örnek: `deploy/pa.env.example`.

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

---

## #4-6 — SMC Bölge Filtreleri (aynı TF, --min-smc)

Harmonik D noktası sadece Fibonacci'ye değil, **kurumsal iz bölgelerine** de denk
geliyorsa dönüş ihtimali artar. Üç bağımsız sinyal 0-100 skorda birleşir
(`quality/smc.py` → `compute_smc`); hepsi D'nin SOLUNDAKİ aynı-TF mumlarla çalışır
(yeni veri altyapısı gerektirmez).

| # | Sinyal | Puan | Kural (bull) |
|---|--------|------|--------------|
| #4 | **Order Block** | 40 | D, geçmiş bir bull OB kutusunun içinde. OB = sert yükselişten önceki son kırmızı mum (sonraki mumlar high'ı kapanışla kırar). |
| #5 | **FVG / Imbalance** | 30 | D, dolmamış bull FVG'nin içinde. FVG = ardışık 3 mumda boşluk (high[i-1] < low[i+1]). |
| #6 | **Liquidity Sweep** | 30 | D barı soldaki dibin altına iğne atıp gövdeyi üstünde kapatır (stop avı). |

Eşik mantığı: `--min-smc 30` = en az bir bölge onayı (yol haritasının "EN AZ
BİRİ" kuralı), `60` = en az iki, `100` = üçü birden.

**Kodda:** `detection/structure.py` → `find_order_blocks()`, `find_fair_value_gaps()`,
`check_liquidity_sweep()`. `quality/smc.py` → `compute_smc()` (0-100 + bileşen).
`scanner.py` → `_apply_smc()` her setup'a yazar (`Setup.smc_score`).
`karakter/portfolio.py` → `format_smc_sweep()` eşik taraması.
`cli/run_live_multi.py` → `--min-smc` paper AKTIF kapısı.
Testler: `tests/test_smc.py`.

```bash
# Canlı: en az bir kurumsal bölge onayı olmadan paper açma
python -m terminal.cli.run_live_multi --symbols BTCUSDT --intervals 60m,4h \
    --paper --min-smc 30 --ltf-choch     # #4-6 + #3 birlikte
```

> Hepsi `confluence` kalıbındadır: önce backtest `format_smc_sweep` ile ölç,
> edge görülen eşikte canlıda aç.

---

## Giriş denetimi — 3 kontrol noktası (`pa_check`)

Bot bir işlem açtığında girişin "doğru yer / doğru zaman / doğru stop" olup
olmadığını mekanik olarak raporlar (`quality/pa_check.py` → `pa_checklist()`):

| # | Kontrol | Kural |
|---|---------|-------|
| 1 | **Doğru yer** | D, geçmiş bir OB/FVG bölgesinin içinde mi (`compute_smc`). |
| 2 | **Doğru zaman** | Girişten önce ALT TF'de CHoCH onaylandı mı (`check_choch`). |
| 3 | **Doğru stop** | Stop, PA yapısının (sweep iğnesi / OB kutusu / FVG tabanı) arkasında mı — yoksa harmonik/sabit-% mi (`pa_stop`). |

```bash
python -m terminal.cli.pa_check --setup-id 123          # DB'deki setup (HTF+LTF DB'den)
python -m terminal.cli.pa_check --symbol BTCUSDT --interval 60m --last 5   # canlı
```

Çıktı her madde için ✅ EVET / ❌ HAYIR / ⚠️ ? (LTF verisi yoksa) verir.

> **Bilinen açık (#3):** Mevcut canlı/backtest girişi `setup.stop`'u **harmonik**
> (XA-tabanlı) + `MIN_SL_PCT=%0.4` taban ile koyar — PA yapısına göre DEĞİL.
> `pa_stop()` PA stop'un nerede olması gerektiğini hesaplar; denetim mevcut stop
> ile PA stop arasındaki sapmayı gösterir. Girişi gerçekten PA stop'a bağlamak
> (opt-in `--pa-stop`) sıradaki adım.
