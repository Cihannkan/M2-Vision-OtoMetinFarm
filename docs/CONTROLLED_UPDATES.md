# Kontrollü PHANTOM güncellemeleri

## İlk geçiş

Bu sürümden önce açılmış uygulama kontrol protokolünü bilmez. Bir defa botu
durdurup PHANTOM'u kapatın ve `PHANTOM.bat` ile yeniden açın. Oyun istemcileri
açık kalır. İlk açılışta bot kendiliğinden başlamaz; normal Başlat/F5 kullanılır.

## Güncelleme isteği

Proje kökünde:

```
.venv\Scripts\python.exe phantom_supervisor.py update
.venv\Scripts\python.exe phantom_supervisor.py status
```

İstek yalnızca yerel kontrol dosyasına yazılır. Uygulama yöneticisi kaynakların
ayrı bir sürüm kopyasını hazırlar ve belirtilen regresyon testlerini çalıştırır.
Test başarısızsa çalışan bot durdurulmaz. Ağ servisi, uzaktan komut veya GitHub
gönderimi yoktur. Yönetici kendi kodundaki değişiklikler için ayrıca yeniden
başlatılmalıdır; otomatik güncelleme uygulama kodunu yeniler.

Savaş/canlanma/güçlendirme/loot ve global duraklama yokken güvenli geçiş beklenir
(en fazla yaklaşık iki dakika). Bot iş parçacıkları durdurulur ve sonlanmaları
doğrulanır; tuşlar bırakılır, video dosyası kapatılır. Eski uygulama tamamen
çıkmadan yenisi açılmaz. Hiçbir oyun süreci kapatılmaz veya yeniden açılmaz.

Yeni uygulama aynı ayarları ve oyun pencerelerini (HWND, PID, başlık, konum)
doğrular. Model dosyası ve HP seçimi de kontrol edilir. Bir uyuşmazlıkta uygulama
açık fakat bot duraklatılmış kalır. Aktif botun güçlendirme zamanları ve kesim
sayıları korunur; eski hedef/tıklama koordinatları taşınmaz. Kullanıcı tarafından
kapatılmış uygulama kendiliğinden yeniden başlatılmaz.

Yeni sürüm açılışta hata verip kapanırsa önceki sürüm bir kez açılır. Yeni süreç
kapanmadan kilitlenirse zorla öldürülmez; ikinci bot başlatılmaz, müdahale istenir.
Bu ilk aşama açılış geri dönüşüdür: oyun içindeki tüm davranışların iyi olduğunu
garanti etmez, ilerideki oyun hataları için otomatik sürüm geri dönüşü yapmaz.

## Kayıtlar ve sınırlar

- `runtime/manager/status.json`: yönetici durumu ve sürüm yolu.
- `runtime/manager/tests_latest.log`: son test çıktısı.
- `runtime/manager/runs/`: uygulama sağlık bilgisi ve geçiş kayıtları.
- `runtime/manager/releases/`: kaynak/test/yerleşik şablon kopyaları.
- Modeller, kişisel ayarlar ve çalışma videoları sürüm kopyasına alınmaz.
- Yönetici klasörü Git tarafından yok sayılır. Sürüm kopyaları otomatik silinmez;
  uzun süreli kullanımda disk boyutu kontrol edilmelidir.
- Videolar yaklaşık 60 saniyelik parçalarda kapatılır (bir sonraki karede geçiş).
- Sürekli Codex takibi bu altyapıdan ayrıdır; henüz zamanlanmış takip kurulmaz.
- Otomatik testler gerçek oyunda güvenli geçişin kanıtı değildir. İlk geçiş
  kullanıcı gözetiminde doğrulanmalıdır.
