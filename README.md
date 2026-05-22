# harmonik

Kriptoda harmonik formasyonlar üzerine çalışan bir terminal projesi.

## Proje Aşamaları

1. **Öğrenme (şu anki aşama)** — Harmonik formasyonları kaynaklardan (PDF) öğrenip
   yapılandırılmış not bankasına dönüştürmek.
2. **Terminal** — Öğrenilen bilgiyle kriptoda kullanılacak bir terminal/araç geliştirmek.

## Klasör Yapısı

| Klasör | İçerik |
|--------|--------|
| `kaynaklar/` | Ham kaynaklar — buraya PDF'leri yükle |
| `notlar/`    | Kaynaklardan çıkarılan yapılandırılmış notlar (kalıcı bilgi bankası) |

## Nasıl Çalışıyor

Her oturum sıfırdan başladığı için kalıcı hafıza repodadır:

1. PDF'ler `kaynaklar/` klasörüne yüklenir.
2. PDF'ler okunur ve `notlar/` altında markdown notlarına dönüştürülür.
3. Notlar commit edilir → bilgi kalıcı olur, her oturumda kullanılabilir.

Detaylı kullanım için `kaynaklar/README.md` dosyasına bak.
