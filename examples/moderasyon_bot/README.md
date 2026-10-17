# 🛡️ Gelişmiş Moderasyon Botu

## Çalıştırma (Windows)

```bat
python -m pip install -e .
set BOT_TOKEN=tokenin
python examples\moderasyon_bot\bot.py
```

Ayarlar ve vakalar `examples\moderasyon_bot\moderasyon_data.json` dosyasındadır.

## İlk kurulum (Sunucuyu Yönet izni)

```
/ayarla log kanal:#mod-log
/ayarla mesaj-log kanal:#mesaj-log
/ayarla giris-log kanal:#giris-cikis
/ayarla mod-rol rol:@Moderatör
/automod durum acik:True
```

## Moderasyon komutları

| Komut | Açıklama |
|---|---|
| `/ban kullanici: [sebep] [sure:1g] [mesaj_sil:0-7]` | Ban. `sure` verilirse **süreli ban**, süre dolunca otomatik kalkar |
| `/unban kullanici_id:` | Banı kaldır |
| `/kick kullanici:` | Sunucudan at |
| `/sustur kullanici: sure:10dk` | Zaman aşımı (en fazla 28 gün) |
| `/susturma-kaldir kullanici:` | Susturmayı kaldır |
| `/uyari ver / liste / sil vaka: / temizle` | Uyarı sistemi |
| `/sicil kullanici:` | Tüm ceza geçmişi + hesap yaşı |
| `/vaka numara:` | Tek vaka detayı |
| `/temizle miktar:1-100 [kullanici]` | Toplu mesaj silme |
| `/kilit [kanal] [sebep]`, `/kilit-ac [kanal]` | Kanalı yazmaya kapat/aç |
| `/rol ver / al`, `/isim` | Rol ve takma ad |

Süre biçimleri: `30s`, `10dk` / `10m`, `2sa` / `2h`, `3g` / `3d`, `1hf` / `1w`, birleşik `1sa30dk`. Sadece sayı = dakika.

Her işlem **vaka numarası** alır, mod-log kanalına yazılır ve cezalıya DM gönderilir.
Kendine, bota, sunucu sahibine ceza verilemez; diğer yetkililere sadece yöneticiler işlem yapabilir.

## Uyarı cezaları

Varsayılan: **3 uyarı → 1 saat susturma, 5 uyarı → atma, 7 uyarı → ban**. Değiştirmek için:

```
/ayarla uyari-cezasi esik:3 eylem:Sustur sure:2sa
/ayarla uyari-cezasi esik:5 eylem:Kaldır
```

## AutoMod

| Komut | Açıklama |
|---|---|
| `/automod durum acik:` | Aç / kapat |
| `/automod kelime-ekle kelime:a, b, c` / `kelime-sil` | Yasaklı kelimeler |
| `/automod filtre link: davet: buyuk_harf:70 etiket:5 spam_mesaj:5 spam_saniye:5` | Filtreler |
| `/automod muaf rol: / kanal:` | Muafiyet ekle/kaldır (tekrar verince kaldırır) |
| `/automod goster` | Ayarları göster |

İhlalde mesaj silinir, kullanıcı otomatik **uyarı** alır (uyarı cezaları uygulanır). Spam'de 5 dakika susturulur.
Düzenlenen mesajlar da kontrol edilir. Yetkililer ve muaf roller/kanallar etkilenmez.

## Kayıtlar

- **Mesaj-log:** silinen ve düzenlenen mesajlar (önce/sonra içeriğiyle)
- **Giriş-log:** katılan/ayrılan üyeler, hesap yaşı; 7 günden yeni hesaplar ⚠️ ile işaretlenir
