# PHANTOM Vaka Kaydi

Bu dosya PHANTOM'da gorulen davranislari, kanit seviyesini ve bir duzeltmenin
ne zaman gercekten tamamlanmis sayilacagini tek yerde tutar. Yeni degisiklikler
once ilgili vaka kimligine baglanir; yalnizca kod testi gecen bir konu
`CANLIDA DOGRULANDI` sayilmaz.

Son guncelleme: 2026-09-10

## Durumlar

- `ACIK`: Kök neden veya çözüm henüz tamamlanmadı.
- `VIDEO GEREKIYOR`: Log tek başına davranışı ayırmaya yetmiyor.
- `KODDA DUZELTILDI`: Değişiklik yapıldı, otomatik test bekliyor.
- `TEST DOGRULANDI`: Otomatik test geçti, gerçek oyun testi bekliyor.
- `CANLIDA DOGRULANDI`: Aynı senaryo gerçek oyunda yeniden denenip geçti.
- `IZLEMEDE`: Sorun şu anda görünmüyor; tekrarında yeni kanıt toplanacak.

## Kanit Kurali

Her yeni olayda mümkünse aşağıdakiler birlikte kaydedilir:

1. Tarih ve saat aralığı.
2. Client numarası ve pencere kimliği.
3. Olaydan 30-60 saniye önce başlayan video.
4. `runtime/logs/events_YYYYMMDD.jsonl` dosyasındaki ilgili satırlar.
5. Beklenen davranış ve gerçekleşen davranış.
6. PHANTOM sürümü/değişiklik tarihi ve kullanılan kalibrasyon.

Bir tuşun işletim sistemine teslim edilmesi, oyunun o tuşu işlediğini tek
başına kanıtlamaz. Benzer şekilde `Mob oldu` logu gerçek kırılmayı değil,
algoritmanın verdiği kararı gösterir. Canlı kabul ölçütü ayrıca yazılır.

## Vaka Ozeti

| Kimlik | Konu | Durum | Canlı kabul ölçütü |
|---|---|---|---|
| PH-001 | `PHANTOM.bat` bazen pencere yok hatası verirken uygulama açılıyor | İZLEMEDE | Art arda 10 açılışta tek pencere, yanlış hata yok |
| PH-002 | Eski/geçersiz pencere kimliği ve canlı görüntü gelmemesi | İZLEMEDE | Client yeniden seçildikten sonra üç canlı görüntü de kesintisiz |
| PH-003 | Aynı çözünürlükte ortak HP kalibrasyonu | KODDA DUZELTILDI | C1/C2/C3 aynı boyutta aynı panel alanını doğru okur |
| PH-004 | Değişen yazı ve can yüzdesi yüzünden tam panel eşleşmesinin bozulması | TEST DOGRULANDI | İsim/yüzde değişirken panel 2/3 kare oyuyla görünür kalır |
| PH-005 | Çerçeve yokken başka kırmızı parçaların HP sayılması | TEST DOGRULANDI | Çerçeve skoru düşük kare HP örneği veya ölüm kararı üretmez |
| PH-006 | Can yüksekken panel kaybının ölüm sayılması veya süresiz bekleme | KODDA DUZELTILDI | Kısa kayıp hedefi korur; 6 sn kayıpta kurtarma, üç başarısız denemede kill/loot olmadan arama |
| PH-007 | Aynı hedefte canın `%0,9 -> %94` gibi imkânsız yükselmesi | TEST DOGRULANDI | `%4` üstü artış reddedilir; kurtarma/hedef değişimi tetiklemez |
| PH-008 | Metne giderken mob/engel yüzünden takılma | TEST DOGRULANDI | 8 sn hareketsizlik sonrası SPACE1+D2, hasar yoksa SPACE1+A4, yine yoksa SPACE1+D6; hasarda sıra durur |
| PH-009 | Metin kırıldıktan sonra yerdeki eşyanın alınmaması | AÇIK | Ölüm kanıtından sonra Z serisi loglanır ve eşya oyunda kaybolur |
| PH-010 | Metin yokken Hareketli Metin Arama | KODDA DUZELTILDI | Q-Q-Q-Q-G-T, her tuş 1 sn; her adımda kontrol, bulunursa sıra kesilir; bulunamazsa 4 sn sonra baştan |
| PH-011 | Güçlendirme dizisinin eksik/yanlış tuş üretmesi | İZLEMEDE | Başlangıçta ve 4 dakikada bir tüm güçlendirmeler görünür |
| PH-012 | RUMELİ2 CAPTCHA eksik OCR nedeniyle tıklamama | KODDA DUZELTILDI | Soru + dört seçenek okunur veya güvenli iki-kare elemesiyle doğru seçenek tıklanır ve panel kapanır |
| PH-013 | Üst üste gelen client pencerelerinde görüntünün başka client'tan gelmesi | KOK NEDEN DOGRULANDI | Örtülen HP alanı sonsuz kilit üretmez; client odaklanır veya güvenli aramaya döner |
| PH-014 | Çoklu client fare/klavye girdilerinin karışması | TEST DOGRULANDI | Eşzamanlı olayda girdi yalnız hedef pencerede gerçekleşir |
| PH-015 | Bir client yavaşken diğerlerinin eski kare kullanması | TEST DOGRULANDI | Her client sonucu bağımsız yayınlanır; `GORUNTU DONDU` yanlış kararı yok |
| PH-016 | DirectML açıkken yüksek CPU kullanımı | AÇIK | Üç client yükünde ölçülmüş CPU/GPU hedefleri belirlenip karşılanır |
| PH-017 | YOLO'nun metin olmayan nesneye tıklaması | AÇIK | Farklı haritalarda yanlış pozitif oranı ölçülür ve kabul eşiğinin altına iner |
| PH-018 | Video ile log zamanının ve client yönlendirmesinin eşleştirilmesi | TEST DOGRULANDI | Otomatik kayıt, yan dosya ve olay logu aynı milisaniye zamanını gösterir |

## Aktif Kritik Vakalar

### PH-019 - Karakter ölümü ve yerinde yeniden doğma

**12:25-14:34 canlı takip:** Uygulama 11:55'te yeniden açılmasına rağmen C1
ve C2 ölüm menüleri kaçırıldı; CAN logu oluşmadı. C1 menüsü eski şablonla
0.833, C2 menüsü ilk ek varyantla 0.753 skorda kaldı (eşik 0.88).
12:27 kaydında ikisinin de ölüm menüsü açık, 14:30'da üç karakter portal
çevresinde ARANIYOR ve hedef sayısı sıfır. Kesim bölgesine dönüş rotası yok.

Şablon setine bu iki görünüm eklendi; eşik düşürülmedi. Yeni kayıt/konum
örneklerinde 0.94-0.97 eşleşme, normal oyun karelerinde 0.37 altında skor
görüldü. Kayıtların yalnız oyun menüsü bölgesini içeren altı örneği regresyon
testine eklendi. Bu düzeltme de gerçek oyun yeniden doğmasıyla ayrıca
doğrulanmalıdır; önceki testlerin geçmesi canlı başarıyı kanıtlamamıştı.

2026-09-10 kaydında C1 08:06:10'da yerde, yeniden başlama menüsü açıkken
hedef HP takibi sürüyordu. Yeni akış iki yeni karede ölüm menüsünü doğrular,
istemcinin normal girdilerini keser. Girdi kilidi altında ilgili pencere öne
alınır, yeni ekran görüntüsünde iki düğmeli menü tekrar eşleştirilir ve yalnız
üstteki `Burada yeniden başla` düğmesine sol tıklanır. Şehir düğmesi seçilmez.
Tıklama sonucu en az 3 saniye beklenir. Menü hâlâ yeni görüntülerde
doğrulanıyorsa tekrar tıklanır; üç denemelik sınır kaldırılmıştır. CAPTCHA/global duraklama
ve kullanıcı durdurması sırasında yeniden doğma tıklaması gönderilmez.

Menünün kaybolması tek başına yeterli değildir: ilgili pencere öndeyken
üç yeni karede menü yokluğu ve alt-sol HUD'da can işareti aranır. Onay sonrası
eski hedef, HP geçmişi ve hedef belleği temizlenir; hedef nesli yenilenir.
Doğum doğrulanınca bir kez CTRL+G gönderilir; gönderim engellenirse normal
arama başlamadan yeniden denenecek güvenli an beklenir. Tuş gönderildikten
sonra tekrar toggle yapılmaz. Yarım kalmış güçlendirme-biniş işareti temizlenir;
hemen tekrar attan inilmemesi için sonraki güçlendirme dört dakika sonraya
ayarlanır. Ata gerçekten binildiği henüz görsel olarak doğrulanmıyor.

Son güncelleme testi: dört ardışık yeniden doğma tıklaması, üç saniyelik
bekleme, tek CTRL+G ve durdurmada tuş bırakma dahil 77 test geçti.

Görsel şablon kayıtlı Rumeli2 ölüm menüsünden çıkarıldı. İki gerçek ölüm
karesinde yaklaşık 0.968 eşleşme, iki normal karede 0.255 altında skor alındı.
Arayüz boyutu/tema değişirse yeniden kalibrasyon gerekebilir. Canlı yeniden
doğma henüz doğrulanmadı; gerçek oyuna test girdisi gönderilmedi.

### PH-020 - HP doğrulama başarısızlığı ve hedefler arasında dönme

C2 07:06'dan sonra görünür HP panelini doğrulayamayıp yaklaşık beş saniyede
bir iki hedef arasında dönüyordu. Kalibre edilmiş HP akışında bu erken çıkış
kaldırıldı: sürekli panel kaybında ilk kurtarma 8 saniye sonra, sonraki
denemeler yeni görüntülere göre en az 6 saniye arayla uygulanır. Üç deneme
veya 45 saniyelik yaklaşma sınırı sonrasında hedef bırakılır.

Son sekiz başarısız hedef 60 saniyelik ayrı kayıtlarla hatırlanır; aynı/çok
yakın konumlar hedef seçimi ve arama sonucu kontrolünden çıkarılır. Tüm
adaylar elenirse mevcut Q-Q-Q-Q-G-T araması çalışır. İki dakika gerçek hasar
doğrulanamazsa en fazla dakikada bir `[ILERLEME-Cx]` uyarısı yazılır.

Doğrulama: ölüm/yeniden doğma, üst düğmeye pencere yönlendirmesi, tekrar
sınırı, eski/örtülü karelerin reddi, hedef hafızasının süre ve kapasitesi,
8 saniyelik HP kurtarması ve mevcut savaş/arama/güçlendirme/yönlendirme
regresyonları dahil 76 test geçti. Bu değişiklikler uygulamanın tamamen
kapatılıp yeniden açılmasıyla yüklenir. Durum: TEST DOGRULANDI.

### PH-005 - Çerçevesiz kırmızı parça HP sayılıyor

**Belirti:** HP paneli yapısal olarak kaybolduğu halde dünyadaki veya başka bir
arayüzdeki kırmızı çizgiler can yüzdesi olarak okunuyor.

**Kanıt:** 2026-09-10 oturumunda Client 2 için çerçeve skoru yaklaşık
`0.27-0.34` iken aynı saniyelerde `%43,4`, `%67,9`, `%75,5`, `%31,1` gibi
birbirini izlemeyen değerler üretildi.

**Kök neden:** Önceden doğrulanmış panelde kırmızı dolgu, çerçeve eşleşmese de
paneli görünür tutabiliyordu. Aynı karede çerçeve doğrulaması olmadan dolgu
örneği de geçmişe ekleniyordu.

**Düzeltme:** Panel var/yok oyu yalnız sabit çerçeve/ankrajdan gelir. Kırmızı
dolgu yalnız aynı karede çerçeve de doğrulanmışsa zaman serisine girer.

**Canlı doğrulama:** Logda düşük `cerceve_skor` ile `ornek_gecerli=1` birlikte
görülmemeli; böyle bir kare loot veya hedef değişimi üretmemeli.

### PH-006 - Yüksek canda yanlış ölüm

**Belirti:** Client 2 metni keserken panel kısa süre kayboluyor; bot taşı öldü
sayarak loot'a ve başka hedefe geçiyor.

**Kesin kanıt:** 2026-09-10 `01:50:41` civarında C2/G11 son güvenilir taban
`%23,6` iken `Mob oldu` üretildi. Yaklaşık 11 saniye sonra aynı C2/G11 için
yeniden can düşüşü ve `Hasar basladi` görüldü. Bu, gerçek ölüm değil yanlış
karardı.

**Düzeltme:** Son güvenilir can `%6` üzerindeyse panel kaybı ölüm sayılmaz.
İlk 6 saniye hedef korunur. Panel en az üç yeni kareyle doğrulanarak hâlâ
kayıpsa ilgili client öne alınır ve sırasıyla `SPACE1+D2`, `SPACE1+A4`,
`SPACE1+D6` kurtarmaları uygulanır (süreler saniye).
Panel geri dönmezse bu işlem en fazla üç kez tekrarlanır; üç başarısız deneme
veya toplam 45 saniyelik kayıpta kill ya da Z/loot üretmeden aramaya dönülür.
Eski hedef 11 saniye beklemeye alınır. Panel geri gelirse kayıp süresi sıfırlanır.

**2026-09-10 ek kanıt:** 03:43:53 C1 son can `%50,9` ile 60 saniyedir;
03:43:55 C3 son can `%86,8` ile 595 saniyedir panel bekliyordu. Önceki
süresiz koruma iki istemciyi SAVASIYOR durumunda kilitliyordu.

**Otomatik doğrulama:** Yeni test yüksek/bilinmeyen canla uzun kayıpta önce üç
kurtarma uygulanmasını, ardından aramaya dönüşü, kill/loot üretilmemesini ve
aynı karenin tekrarının geçiş yaptıramamasını doğruluyor.

**Canlı doğrulama:** Uygulama yeniden açıldıktan sonra kısa kayıpta hedef
korunmalı; 6 saniyelik kayıpta `[HP-Cx] kayip panel kurtarmasi` görülmeli.
Panel dönmezse üç denemeden sonra `olum dogrulanmadi, kill/loot uygulanmadan`
gerekçesiyle arama başlamalı. Bu son düzeltme henüz canlıda doğrulanmadı.

### PH-007 - İmkânsız can artışı ve hedef kimliği karışması

**Belirti:** Aynı hedef neslinde çok düşük canın ardından yüksek/yüzde yüz can
görülüyor; taban düşük kaldığı için bot üç kurtarma yapıp hedefi bırakabiliyor.

**Kanıt:** C3/G7 `01:42:07` civarında `%0,9` tabana indikten sonra aynı nesilde
`%100`, `%98,1`, `%97,2` görüldü. C1/G20 için de `%0,9` sonrasında `%45,3` ve
daha büyük sıçramalar oluştu.

**Düzeltme:** Aynı hedef neslinde son kabul edilen değere göre `%4`ten büyük
yukarı sıçrama geçersizdir. Geçersiz kare ilerleme, kurtarma veya hedef değişimi
zamanlayamaz. Yeni gerçek hedef tıklanınca nesil değişir ve HP geçmişi sıfırlanır.

**Canlı doğrulama:** `[HP-Cx] ... imkansiz can artisi reddedildi` logu çıkabilir,
ancak hemen arkasından kurtarma veya hedef değişimi gelmemelidir.

### PH-008 - Kademeli yönlü kurtarma

İlk yaklaşma kurtarması 8 saniyelik sahne hareketsizliğinde başlar. Her deneme
1 saniye SPACE ile başlar; yön/süre sırası D 2 saniye, A 4 saniye, D 6 saniyedir.
Yaklaşmada her manevradan sonra en az 3 saniye beklenir ve taze/geçerli HP
ölçümü kontrol edilir. Doğrulanan can düşüşünde savaş başlar, kalan adımlar
uygulanmaz. Yalnız sahne hareketi başarı kabul edilmez. Üç başarısız denemeden
sonra hedef bırakılır. Yaklaşmanın toplam sınırı 45 saniyedir.

Savaşta aynı yön sırası kullanılır; mevcut 6 saniyelik ilerlememe kontrolü
korunur. Hasar yeniden başladığında kurtarma sayacı sıfırlanır.

Doğrulama: kurtarma sırası, savaş/görüntü ve client yönlendirme testlerinden
60 test geçti. Gerçek klavye/fare girdisi gönderilmedi. Canlı oyun doğrulaması
uygulamanın tamamen kapatılıp yeniden açılmasından sonra yapılmalıdır.

### PH-009 - Loot teslimi ile gerçek toplama ayrımı

**Belirti:** Metin kırıldıktan sonra Z gönderildiği halde eşya yerde kalabiliyor;
bazı olaylarda ise yanlış ölüm kararı yüzünden doğru anda Z hiç başlamıyor.

**Mevcut kanıt sınırı:** `OS_teslim=N/N` yalnızca tuş olayının Windows'a
gönderildiğini kanıtlar. Oyunun eşyayı aldığını kanıtlamaz.

**Sonraki adım:** Önce PH-006 canlıda doğrulanacak. Ardından ölüm zamanı,
odaklanan HWND, her Z denemesi ve loot sonu tek vaka kimliğiyle loglanacak.
Videoda eşyanın kaybolup kaybolmadığıyla eşleştirilecek.

### PH-012 - CAPTCHA kısmi OCR

**Belirti:** Panel doğru algılansa bile seçeneklerden biri boş okunursa güvenli
olarak tıklama yapılmıyor.

**Beklenen davranış:** Eksik/düşük güvenli OCR'da rastgele tıklamak yerine farm
bekletilir. Başarılı sayılması için solver ve tıklama loguna ek olarak CAPTCHA
panelinin kapandığı görülmelidir.

**2026-09-10 canlı kanıtı:** Client 1 paneli `0.99`, sabit yazı bölgesi `1.00`
skoruyla doğru algıladı. Hedef `299170`; seçenekler
`171307, 340242, [boş], 541685` okundu. Tek boş olan üçüncü satır şekil
skorunda `0.40` ile en iyi, ikinci skor `0.29` olmasına rağmen motor eleme
yapmadığı için tıklamadı; kullanıcı elle seçti.

**Düzeltme:** Hedef altı hane, diğer üç seçenek altı hane ve hedeften farklı,
tek okunamayan seçenek de şekil karşılaştırmasında en az `0.36` ve en az
`0.07` farkla birinciyse aynı sonuç iki ardışık OCR turunda doğrulanır. Ancak
ondan sonra tek okunamayan seçenek tıklanabilir. Belirsiz ilk turda CAPTCHA
paneli ve karar değerleri `runtime/evidence/captcha/` altına kaydedilir.

**Canlı doğrulama:** Benzer tek-satır OCR kaybında önce `eleme=1/2`, ardından
`iki-kare-eleme+sekil` ve doğru `CAPTCHA ÇÖZÜLDÜ` kaydı görülmeli; panel
kapanmalıdır. Diğer koşullarda otomatik tıklama yapılmamalıdır.

### PH-013 - Çoklu pencere görüntü karışması

**Belirti:** Bir client'ın can dizisi başka bir hedef/client paneline geçmiş gibi
aniden yükseliyor veya canlı görüntüsü beklenen karakteri göstermiyor.

**2026-09-10 kesin video kanıtı:** C2 dikdörtgeni
`(1240, 0)-(2536, 839)`, C3 dikdörtgeni `(1225, 779)-(2521, 1618)` idi. C2,
C3'ün üstteki 60 pikselini ve böylece HP panel alanını kapattı. C3/G31 canı
`%86,8`e kadar düşürdükten sonra panel `03:34:00` civarında kayboldu; bot
`03:47:38`de bile 818 saniyedir aynı SAVASIYOR durumundaydı. Aynı oturumda C1
de `%50,9`da 286 saniye aynı nedenle bekledi.

**Çözüm:** Masaüstü yakalamasının örtülme sınırı korunuyor; fakat yüksek canlı
panel kaybı artık sonsuz beklemiyor. Altı saniyede ilgili client odaklanarak
mevcut kademeli kurtarma deneniyor. Odaklanma örtüyü kaldırıp paneli görünür
yaparsa hedef devam ediyor; üç denemede panel dönmezse yanlış kill/loot olmadan
hedef bırakılıyor.
Pencereleri üst üste getirmemek hâlâ en güvenilir yerleşimdir.

### PH-018 - Otomatik tanı videosu ve zaman eşleştirme

**Amaç:** Kullanıcının olayı fark etmesinden önceki görüntüyü kaybetmeden,
videodaki her kareyi PHANTOM karar loglarıyla eşleştirmek.

**Uygulama:** PHANTOM açıldığında 2 FPS sessiz masaüstü kaydı başlar. Beş
dakikalık video parçasının yanında aynı adlı `.jsonl` bulunur. Video üstünde
yerel saat, foreground HWND ve client kutuları; yan dosyada ise milisaniyeli
epoch, fare konumu, pencere koordinatları, client durumu, hedef nesli, HP değeri
ve güven skorları vardır. Ana olay loglarına da milisaniye, epoch ve başarılı
hedef tıklamasının koordinatı/yöntemi eklendi.

**Otomatik doğrulama:** Sentetik kareyle gerçek video ve iki kayıtlı yan dosya
satırı oluşturuldu; boyut, adlandırma, overlay ve yalnız PHANTOM dosyalarını
temizleme kuralları test edildi.

**Canlı doğrulama:** Uygulama yeniden açıldıktan sonra arayüzde `Kayıt aktif`
görülmeli. İlk `.mp4`/`.avi`, aynı adlı `.jsonl` ve `[VIDEO] tani kaydi basladi`
olayı aynı başlangıç zamanını göstermelidir.

## Video Gonderim Formati

- `Tanı Videosu` varsayılan olarak açıktır ve PHANTOM açılır açılmaz kayıt başlar.
- Beş dakikalık sessiz parçalar `runtime/evidence/videos/` altında oluşur.
- Her videonun aynı adlı `.jsonl` yan dosyası; kare zamanı, foreground pencere,
  C1/C2/C3 HWND/konum, durum, hedef nesli ve HP ölçümünü saklar.
- Kayıt 2 FPS ve en fazla 1280x720 çözünürlüktedir. İki günden eski veya toplam
  2 GB sınırını aşan PHANTOM tanı kayıtları otomatik temizlenir.
- Ayarlar > Güvenlik > `Tanı Videosu` anahtarıyla kayıt kapatılabilir.
- Sorunu fark ettiğinizde yaklaşık saati not edin; otomatik kayıt önceki anları
  zaten aynı beş dakikalık parçada tutar.
- Oyun penceresinin başlığı, HP paneli ve karakter görünür olsun.
- Mümkünse PHANTOM'daki üç canlı görüntü ve Loglar sekmesi de kadrajda olsun.
- Mesajda `Client N`, yaklaşık saat ve beklenen/gerçekleşen davranışı tek cümleyle yazın.
- Video kesilmeden önce yanlış hedef tıklaması, kurtarma veya yerde kalan eşya da görünsün.

## Degisiklik Sonrasi Kontrol Listesi

1. Tüm otomatik testler geçiyor mu?
2. Kodda düzeltilen vaka kimlikleri bu dosyada güncellendi mi?
3. C1 tek başına 10 metin boyunca hedef değiştirmeden çalışıyor mu?
4. C2 ve C3 aynı testte kendi HP dizilerini mi gösteriyor?
5. Düşük can + panel kapanması yalnız üç taze yok-kareden sonra ölüm sayılıyor mu?
6. Yüksek canda panel kaybı `karar bekletildi` üretiyor mu?
7. Gerçek ölümden sonra Z logu ve oyundaki eşya kaybolması birlikte doğrulandı mı?
8. CAPTCHA testinde solver sonucu, tıklama ve panel kapanması birlikte görüldü mü?
9. İlgili video parçası ve aynı adlı `.jsonl` dosyası olay saatini kapsıyor mu?
